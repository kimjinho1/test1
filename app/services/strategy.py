"""Strategy engine - loads, manages, and executes trading strategies."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import logging
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

STRATEGIES_DIR = Path(__file__).resolve().parent.parent / "strategies"
STRATEGY_TIMEOUT_SEC = 30
MAX_CONSECUTIVE_FAILURES = 3

REQUIRED_SIGNAL_KEYS = {"action", "ticker", "confidence", "reason"}


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyInfo:
    """Runtime metadata for a loaded strategy."""

    name: str
    module: types.ModuleType
    enabled: bool = True
    consecutive_failures: int = 0
    file_path: str = ""

    @property
    def run_fn(self) -> Callable[[dict], dict]:
        return self.module.run  # type: ignore[attr-defined]


class StrategyEngine:
    """Load, manage, and execute trading strategy modules."""

    def __init__(self, strategies_dir: Path | None = None) -> None:
        self._strategies_dir = strategies_dir or STRATEGIES_DIR
        self._strategies: dict[str, StrategyInfo] = {}
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="strategy")

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_strategies(self) -> list[str]:
        """Scan the strategies directory and load every valid strategy module.

        Returns the list of successfully loaded strategy names.
        """
        loaded: list[str] = []
        if not self._strategies_dir.is_dir():
            logger.warning("Strategies directory not found: %s", self._strategies_dir)
            return loaded

        for path in sorted(self._strategies_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            name = path.stem
            try:
                self._load_module(name, path)
                loaded.append(name)
                logger.info("Loaded strategy: %s", name)
            except Exception:
                logger.exception("Failed to load strategy '%s' from %s", name, path)

        return loaded

    def reload_strategy(self, name: str) -> None:
        """Hot-reload a single strategy by name."""
        info = self._strategies.get(name)
        if info is None:
            raise KeyError(f"Strategy '{name}' is not loaded")

        path = Path(info.file_path)
        if not path.exists():
            raise FileNotFoundError(f"Strategy file not found: {path}")

        self._load_module(name, path)
        # Preserve enabled/disabled state but reset failure counter
        new_info = self._strategies[name]
        new_info.enabled = info.enabled
        new_info.consecutive_failures = 0
        logger.info("Reloaded strategy: %s", name)

    def _load_module(self, name: str, path: Path) -> None:
        """Import (or re-import) a strategy module and validate it."""
        module_name = f"app.strategies.{name}"

        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        # Validate the module exposes a callable `run`
        run_fn = getattr(module, "run", None)
        if run_fn is None or not callable(run_fn):
            raise AttributeError(f"Strategy '{name}' must expose a callable run(context)")

        # Register in sys.modules so relative imports inside the strategy work
        sys.modules[module_name] = module

        self._strategies[name] = StrategyInfo(
            name=name,
            module=module,
            file_path=str(path),
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run_strategy(self, name: str, context: dict[str, Any]) -> dict[str, Any] | None:
        """Execute a single strategy in a thread with a timeout.

        Returns the validated signal dict or ``None`` on failure.
        """
        info = self._strategies.get(name)
        if info is None:
            raise KeyError(f"Strategy '{name}' is not loaded")
        if not info.enabled:
            logger.debug("Strategy '%s' is disabled, skipping", name)
            return None

        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(self._executor, info.run_fn, context),
                timeout=STRATEGY_TIMEOUT_SEC,
            )
            signal = self._validate_signal(result, name)
            info.consecutive_failures = 0
            return signal
        except asyncio.TimeoutError:
            logger.error("Strategy '%s' timed out after %ds", name, STRATEGY_TIMEOUT_SEC)
            self._record_failure(info)
        except Exception:
            logger.exception("Strategy '%s' raised an error", name)
            self._record_failure(info)

        return None

    async def run_all(
        self, context_provider: Callable[[], dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Run every enabled strategy and collect valid signals.

        ``context_provider`` is a callable that returns the context dict.  It is
        called once and the same context is shared across all strategies.
        """
        context = context_provider()
        tasks = [
            self.run_strategy(name, context)
            for name, info in self._strategies.items()
            if info.enabled
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Unexpected gather error: %s", result)
                continue
            if result is not None:
                signals.append(result)

        return signals

    # ------------------------------------------------------------------
    # Enable / Disable
    # ------------------------------------------------------------------

    def enable_strategy(self, name: str) -> None:
        info = self._strategies.get(name)
        if info is None:
            raise KeyError(f"Strategy '{name}' is not loaded")
        info.enabled = True
        info.consecutive_failures = 0
        logger.info("Enabled strategy: %s", name)

    def disable_strategy(self, name: str) -> None:
        info = self._strategies.get(name)
        if info is None:
            raise KeyError(f"Strategy '{name}' is not loaded")
        info.enabled = False
        logger.info("Disabled strategy: %s", name)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_loaded(self) -> list[dict[str, Any]]:
        """Return metadata for every loaded strategy."""
        return [
            {
                "name": info.name,
                "enabled": info.enabled,
                "consecutive_failures": info.consecutive_failures,
                "file": info.file_path,
            }
            for info in self._strategies.values()
        ]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _validate_signal(self, result: Any, strategy_name: str) -> dict[str, Any]:
        """Validate that a strategy result conforms to the signal schema."""
        if not isinstance(result, dict):
            raise TypeError(
                f"Strategy '{strategy_name}' returned {type(result).__name__}, expected dict"
            )

        missing = REQUIRED_SIGNAL_KEYS - result.keys()
        if missing:
            raise ValueError(
                f"Strategy '{strategy_name}' signal missing keys: {missing}"
            )

        action = result["action"]
        try:
            Action(action)
        except ValueError:
            raise ValueError(
                f"Strategy '{strategy_name}' returned invalid action '{action}'. "
                f"Must be one of: {', '.join(a.value for a in Action)}"
            )

        confidence = result["confidence"]
        if not isinstance(confidence, (int, float)):
            raise TypeError(
                f"Strategy '{strategy_name}' confidence must be a number, "
                f"got {type(confidence).__name__}"
            )

        return result

    def _record_failure(self, info: StrategyInfo) -> None:
        """Increment failure counter and auto-disable after threshold."""
        info.consecutive_failures += 1
        if info.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            info.enabled = False
            logger.warning(
                "Auto-disabled strategy '%s' after %d consecutive failures",
                info.name,
                info.consecutive_failures,
            )

    def shutdown(self) -> None:
        """Shut down the thread pool executor."""
        self._executor.shutdown(wait=False)
