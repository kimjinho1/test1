"""Background tasks for portfolio polling, strategy execution, and market hours."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# KST is UTC+9, fixed offset (no DST)
KST = timezone(timedelta(hours=9))


def _now_kst() -> datetime:
    return datetime.now(KST)


def is_market_open() -> bool:
    """Return True if the current KST time falls within market hours on a weekday."""
    now = _now_kst()
    # Monday=0 .. Friday=4
    if now.weekday() > 4:
        return False

    market_open = now.replace(
        hour=settings.market_open_hour,
        minute=settings.market_open_minute,
        second=0,
        microsecond=0,
    )
    market_close = now.replace(
        hour=settings.market_close_hour,
        minute=settings.market_close_minute,
        second=0,
        microsecond=0,
    )
    return market_open <= now < market_close


class BackgroundTaskManager:
    """Manages long-running async background tasks for the trading system."""

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._broker: Any = None
        self._strategy_engine: Any = None
        self._order_manager: Any = None
        self._ws_hub: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(
        self,
        broker: Any,
        strategy_engine: Any,
        order_manager: Any,
        ws_hub: Any,
    ) -> None:
        """Start all background tasks."""
        if self._running:
            logger.warning("BackgroundTaskManager is already running")
            return

        self._broker = broker
        self._strategy_engine = strategy_engine
        self._order_manager = order_manager
        self._ws_hub = ws_hub
        self._running = True

        self._tasks = [
            asyncio.create_task(self._portfolio_poller(), name="portfolio_poller"),
            asyncio.create_task(self._strategy_runner(), name="strategy_runner"),
            asyncio.create_task(self._market_hours_guard(), name="market_hours_guard"),
        ]
        logger.info("Background tasks started (%d tasks)", len(self._tasks))

    async def stop(self) -> None:
        """Gracefully cancel and await all background tasks."""
        if not self._running:
            return

        self._running = False
        for task in self._tasks:
            task.cancel()

        results = await asyncio.gather(*self._tasks, return_exceptions=True)
        for task, result in zip(self._tasks, results):
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                logger.error("Task %s raised during shutdown: %s", task.get_name(), result)

        self._tasks.clear()
        logger.info("All background tasks stopped")

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def _portfolio_poller(self, interval: float = 30) -> None:
        """Poll broker portfolio periodically and broadcast updates."""
        logger.info("portfolio_poller started (interval=%ss)", interval)
        while self._running:
            try:
                if not getattr(self._broker, "is_connected", False):
                    logger.debug("portfolio_poller: broker not connected, skipping")
                else:
                    portfolio = await asyncio.to_thread(self._broker.get_portfolio)
                    await self._ws_hub.broadcast_portfolio(portfolio)
                    logger.debug("Portfolio broadcast: %d positions", len(portfolio) if isinstance(portfolio, list) else 0)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("portfolio_poller error")

            await asyncio.sleep(interval)

    async def _strategy_runner(self, interval: float | None = None) -> None:
        """Run all strategies during market hours and forward signals."""
        interval = interval or settings.strategy_eval_interval_sec
        logger.info("strategy_runner started (interval=%ss)", interval)
        while self._running:
            try:
                if not getattr(self._broker, "is_connected", False):
                    logger.debug("strategy_runner: broker not connected, skipping")
                elif is_market_open():
                    signals = await asyncio.to_thread(
                        self._strategy_engine.run_all,
                        self._broker,
                    )

                    for signal in signals or []:
                        if signal.get("action") in ("BUY", "SELL"):
                            await self._ws_hub.broadcast_signal(signal)
                            try:
                                trade = await asyncio.to_thread(
                                    self._order_manager.execute_signal,
                                    signal,
                                )
                                if trade:
                                    await self._ws_hub.broadcast_trade(trade)
                            except Exception:
                                logger.exception(
                                    "Order execution failed for signal: %s %s",
                                    signal.get("action"),
                                    signal.get("ticker"),
                                )
                else:
                    logger.debug("Market closed - strategy_runner sleeping")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("strategy_runner error")

            await asyncio.sleep(interval)

    async def _market_hours_guard(self, interval: float = 10) -> None:
        """Monitor market open/close transitions and broadcast status changes."""
        logger.info("market_hours_guard started (interval=%ss)", interval)
        last_state: bool | None = None
        while self._running:
            try:
                current_state = is_market_open()
                if current_state != last_state:
                    now = _now_kst()
                    if current_state:
                        logger.info("Market OPEN at %s", now.strftime("%Y-%m-%d %H:%M:%S KST"))
                        await self._ws_hub.broadcast_status({
                            "market": "open",
                            "timestamp": now.isoformat(),
                        })
                    else:
                        logger.info("Market CLOSED at %s", now.strftime("%Y-%m-%d %H:%M:%S KST"))
                        await self._ws_hub.broadcast_status({
                            "market": "closed",
                            "timestamp": now.isoformat(),
                        })
                    last_state = current_state
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market_hours_guard error")

            await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

task_manager = BackgroundTaskManager()
