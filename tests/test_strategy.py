"""Tests for StrategyEngine."""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from app.services.strategy import (
    Action,
    MAX_CONSECUTIVE_FAILURES,
    REQUIRED_SIGNAL_KEYS,
    STRATEGY_TIMEOUT_SEC,
    StrategyEngine,
    StrategyInfo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_strategy(tmp_path: Path, name: str, body: str) -> Path:
    """Write a strategy .py file and return its path."""
    p = tmp_path / f"{name}.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


GOOD_STRATEGY = """\
def run(context):
    return {
        "action": "BUY",
        "ticker": "005930",
        "confidence": 0.85,
        "reason": "golden cross",
    }
"""

HOLD_STRATEGY = """\
def run(context):
    return {
        "action": "HOLD",
        "ticker": "005930",
        "confidence": 0.5,
        "reason": "no signal",
    }
"""

ERROR_STRATEGY = """\
def run(context):
    raise RuntimeError("strategy exploded")
"""

BAD_RETURN_TYPE = """\
def run(context):
    return "not a dict"
"""

MISSING_KEYS = """\
def run(context):
    return {"action": "BUY"}
"""

INVALID_ACTION = """\
def run(context):
    return {
        "action": "YOLO",
        "ticker": "005930",
        "confidence": 0.5,
        "reason": "test",
    }
"""

BAD_CONFIDENCE = """\
def run(context):
    return {
        "action": "BUY",
        "ticker": "005930",
        "confidence": "high",
        "reason": "test",
    }
"""

SLOW_STRATEGY = """\
import time
def run(context):
    time.sleep(60)
    return {"action": "HOLD", "ticker": "X", "confidence": 0, "reason": "slow"}
"""

NO_RUN_STRATEGY = """\
def execute(context):
    pass
"""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class TestStrategyLoading:

    def test_load_good_strategy(self, tmp_path):
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        loaded = engine.load_strategies()
        assert "alpha" in loaded

    def test_load_skips_underscore_files(self, tmp_path):
        _write_strategy(tmp_path, "_helper", GOOD_STRATEGY)
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        loaded = engine.load_strategies()
        assert "_helper" not in loaded
        assert "alpha" in loaded

    def test_load_nonexistent_dir(self, tmp_path):
        engine = StrategyEngine(strategies_dir=tmp_path / "nope")
        assert engine.load_strategies() == []

    def test_load_no_run_function_skipped(self, tmp_path):
        _write_strategy(tmp_path, "bad", NO_RUN_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        loaded = engine.load_strategies()
        assert "bad" not in loaded

    def test_load_multiple_strategies(self, tmp_path):
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        _write_strategy(tmp_path, "beta", HOLD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        loaded = engine.load_strategies()
        assert sorted(loaded) == ["alpha", "beta"]

    def test_get_loaded_metadata(self, tmp_path):
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()
        meta = engine.get_loaded()
        assert len(meta) == 1
        assert meta[0]["name"] == "alpha"
        assert meta[0]["enabled"] is True
        assert meta[0]["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class TestStrategyExecution:

    @pytest.mark.asyncio
    async def test_run_good_strategy(self, tmp_path):
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()

        result = await engine.run_strategy("alpha", {"market": "data"})
        assert result is not None
        assert result["action"] == "BUY"
        assert result["ticker"] == "005930"
        assert result["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_run_hold_strategy(self, tmp_path):
        _write_strategy(tmp_path, "hold", HOLD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()

        result = await engine.run_strategy("hold", {})
        assert result is not None
        assert result["action"] == "HOLD"

    @pytest.mark.asyncio
    async def test_run_unknown_strategy_raises(self, tmp_path):
        engine = StrategyEngine(strategies_dir=tmp_path)
        with pytest.raises(KeyError):
            await engine.run_strategy("nonexistent", {})

    @pytest.mark.asyncio
    async def test_run_disabled_strategy_returns_none(self, tmp_path):
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()
        engine.disable_strategy("alpha")

        result = await engine.run_strategy("alpha", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_run_error_strategy_returns_none(self, tmp_path):
        _write_strategy(tmp_path, "bad", ERROR_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()

        result = await engine.run_strategy("bad", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_run_all_collects_signals(self, tmp_path):
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        _write_strategy(tmp_path, "beta", HOLD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()

        signals = await engine.run_all(lambda: {"market": "data"})
        assert len(signals) == 2
        actions = {s["action"] for s in signals}
        assert actions == {"BUY", "HOLD"}

    @pytest.mark.asyncio
    async def test_run_all_skips_disabled(self, tmp_path):
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        _write_strategy(tmp_path, "beta", HOLD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()
        engine.disable_strategy("beta")

        signals = await engine.run_all(lambda: {})
        assert len(signals) == 1
        assert signals[0]["action"] == "BUY"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestSignalValidation:

    @pytest.mark.asyncio
    async def test_bad_return_type(self, tmp_path):
        _write_strategy(tmp_path, "bad", BAD_RETURN_TYPE)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()
        result = await engine.run_strategy("bad", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_missing_keys(self, tmp_path):
        _write_strategy(tmp_path, "bad", MISSING_KEYS)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()
        result = await engine.run_strategy("bad", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_action(self, tmp_path):
        _write_strategy(tmp_path, "bad", INVALID_ACTION)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()
        result = await engine.run_strategy("bad", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_bad_confidence_type(self, tmp_path):
        _write_strategy(tmp_path, "bad", BAD_CONFIDENCE)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()
        result = await engine.run_strategy("bad", {})
        assert result is None


# ---------------------------------------------------------------------------
# Auto-disable after consecutive failures
# ---------------------------------------------------------------------------

class TestAutoDisable:

    @pytest.mark.asyncio
    async def test_auto_disable_after_max_failures(self, tmp_path):
        _write_strategy(tmp_path, "bad", ERROR_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()

        for _ in range(MAX_CONSECUTIVE_FAILURES):
            await engine.run_strategy("bad", {})

        meta = engine.get_loaded()
        info = [m for m in meta if m["name"] == "bad"][0]
        assert info["enabled"] is False
        assert info["consecutive_failures"] == MAX_CONSECUTIVE_FAILURES

    @pytest.mark.asyncio
    async def test_success_resets_failure_counter(self, tmp_path):
        # Strategy that alternates: fail once, then succeed
        code = """\
_call_count = 0
def run(context):
    global _call_count
    _call_count += 1
    if _call_count <= 1:
        raise ValueError("fail")
    return {"action": "HOLD", "ticker": "X", "confidence": 0.5, "reason": "ok"}
"""
        _write_strategy(tmp_path, "flaky", code)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()

        # First call fails
        r1 = await engine.run_strategy("flaky", {})
        assert r1 is None

        # Second call succeeds - counter should reset
        r2 = await engine.run_strategy("flaky", {})
        assert r2 is not None

        meta = engine.get_loaded()
        info = [m for m in meta if m["name"] == "flaky"][0]
        assert info["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

class TestStrategyTimeout:

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, tmp_path):
        """Strategy that sleeps longer than timeout should return None."""
        code = """\
import time
def run(context):
    time.sleep(5)
    return {"action": "HOLD", "ticker": "X", "confidence": 0, "reason": "slow"}
"""
        _write_strategy(tmp_path, "slow", code)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()

        # Monkey-patch timeout to 0.1s for test speed
        import app.services.strategy as strat_mod
        original = strat_mod.STRATEGY_TIMEOUT_SEC
        strat_mod.STRATEGY_TIMEOUT_SEC = 0.1
        try:
            result = await engine.run_strategy("slow", {})
            assert result is None
        finally:
            strat_mod.STRATEGY_TIMEOUT_SEC = original


# ---------------------------------------------------------------------------
# Enable / Disable
# ---------------------------------------------------------------------------

class TestEnableDisable:

    def test_enable_strategy(self, tmp_path):
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()
        engine.disable_strategy("alpha")
        engine.enable_strategy("alpha")
        meta = engine.get_loaded()
        assert meta[0]["enabled"] is True

    def test_enable_resets_failure_counter(self, tmp_path):
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()
        # Manually bump failures
        engine._strategies["alpha"].consecutive_failures = 5
        engine.enable_strategy("alpha")
        assert engine._strategies["alpha"].consecutive_failures == 0

    def test_disable_strategy(self, tmp_path):
        _write_strategy(tmp_path, "alpha", GOOD_STRATEGY)
        engine = StrategyEngine(strategies_dir=tmp_path)
        engine.load_strategies()
        engine.disable_strategy("alpha")
        meta = engine.get_loaded()
        assert meta[0]["enabled"] is False

    def test_enable_unknown_raises(self, tmp_path):
        engine = StrategyEngine(strategies_dir=tmp_path)
        with pytest.raises(KeyError):
            engine.enable_strategy("nope")

    def test_disable_unknown_raises(self, tmp_path):
        engine = StrategyEngine(strategies_dir=tmp_path)
        with pytest.raises(KeyError):
            engine.disable_strategy("nope")


# ---------------------------------------------------------------------------
# Action enum
# ---------------------------------------------------------------------------

class TestAction:

    def test_valid_actions(self):
        assert Action("BUY") is Action.BUY
        assert Action("SELL") is Action.SELL
        assert Action("HOLD") is Action.HOLD

    def test_invalid_action(self):
        with pytest.raises(ValueError):
            Action("YOLO")
