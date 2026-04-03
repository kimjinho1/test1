"""Order manager with shadow ledger for Korean stock auto-trading dashboard."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

from app.config import Settings
from app.models.database import SessionLocal, Trade, Position

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants / enums
# ---------------------------------------------------------------------------

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"
    HALTED = "HALTED"


class TradingMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# Risk controls (stateless helpers)
# ---------------------------------------------------------------------------

class RiskControls:
    """Pure risk-check functions.  Each returns ``(passed, reason)``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check_position_limit(
        self,
        ticker: str,
        quantity: int,
        price: float,
        total_portfolio_value: float,
    ) -> tuple[bool, str]:
        """Reject if a single position would exceed *max_position_pct* of the portfolio."""
        if total_portfolio_value <= 0:
            return False, "Portfolio value is zero or negative"
        position_value = quantity * price
        pct = (position_value / total_portfolio_value) * 100
        limit = self._settings.max_position_pct
        if pct > limit:
            return (
                False,
                f"{ticker} position would be {pct:.1f}% of portfolio (limit {limit}%)",
            )
        return True, ""

    def check_daily_loss(self, total_portfolio_value: float) -> tuple[bool, str]:
        """Halt trading when the daily P&L drawdown exceeds *daily_loss_limit_pct*."""
        if not hasattr(self, "_day_start_value") or self._current_date != date.today():
            # First call of the day – snapshot the starting value.
            self._day_start_value: float = total_portfolio_value
            self._current_date: date = date.today()
            return True, ""

        if self._day_start_value <= 0:
            return False, "Day-start portfolio value is zero or negative"

        loss_pct = ((self._day_start_value - total_portfolio_value) / self._day_start_value) * 100
        limit = self._settings.daily_loss_limit_pct
        if loss_pct >= limit:
            return (
                False,
                f"Daily loss {loss_pct:.2f}% has reached limit of {limit}%",
            )
        return True, ""

    def check_stop_loss(
        self,
        ticker: str,
        current_price: float,
        avg_price: float,
    ) -> tuple[bool, str]:
        """Trigger stop-loss when the unrealised loss exceeds *stop_loss_pct*."""
        if avg_price <= 0:
            return False, f"{ticker}: average price is zero or negative"
        loss_pct = ((avg_price - current_price) / avg_price) * 100
        limit = self._settings.stop_loss_pct
        if loss_pct >= limit:
            return (
                False,
                f"{ticker} stop-loss triggered: down {loss_pct:.2f}% (limit {limit}%)",
            )
        return True, ""


# ---------------------------------------------------------------------------
# Shadow ledger
# ---------------------------------------------------------------------------

@dataclass
class ShadowOrder:
    order_id: str
    ticker: str
    action: str  # BUY / SELL
    quantity: int
    price: float
    status: OrderStatus = OrderStatus.PENDING
    fill_price: float | None = None
    fill_qty: int | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class ShadowLedger:
    """In-memory ledger that mirrors the broker's state and detects drift."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._orders: dict[str, ShadowOrder] = {}

    # -- mutations ----------------------------------------------------------

    def add_pending(self, order: ShadowOrder) -> None:
        with self._lock:
            self._orders[order.order_id] = order
            logger.info("Shadow: added pending %s %s %s x%d @%.2f",
                        order.order_id, order.action, order.ticker,
                        order.quantity, order.price)

    def mark_filled(self, order_id: str, fill_price: float, fill_qty: int) -> None:
        with self._lock:
            order = self._orders.get(order_id)
            if order is None:
                logger.warning("Shadow: unknown order_id %s on fill", order_id)
                return
            order.fill_price = fill_price
            order.fill_qty = fill_qty
            if fill_qty >= order.quantity:
                order.status = OrderStatus.FILLED
            else:
                order.status = OrderStatus.PARTIAL
            logger.info("Shadow: %s now %s (filled %d @%.2f)",
                        order_id, order.status.value, fill_qty, fill_price)

    def mark_cancelled(self, order_id: str) -> None:
        with self._lock:
            order = self._orders.get(order_id)
            if order is None:
                logger.warning("Shadow: unknown order_id %s on cancel", order_id)
                return
            order.status = OrderStatus.CANCELLED
            logger.info("Shadow: %s cancelled", order_id)

    # -- queries ------------------------------------------------------------

    def get_shadow_positions(self) -> dict[str, dict[str, Any]]:
        """Return net position per ticker including pending orders.

        Returns a dict keyed by ticker::

            {"005930": {"quantity": 10, "avg_price": 71000.0}, ...}
        """
        positions: dict[str, dict[str, float]] = {}
        with self._lock:
            for order in self._orders.values():
                if order.status in (OrderStatus.CANCELLED, OrderStatus.ERROR):
                    continue
                ticker = order.ticker
                if ticker not in positions:
                    positions[ticker] = {"quantity": 0, "avg_price": 0.0}

                qty = order.fill_qty if order.fill_qty is not None else order.quantity
                price = order.fill_price if order.fill_price is not None else order.price

                pos = positions[ticker]
                if order.action == "BUY":
                    total_cost = pos["avg_price"] * pos["quantity"] + price * qty
                    pos["quantity"] += qty
                    pos["avg_price"] = total_cost / pos["quantity"] if pos["quantity"] else 0.0
                elif order.action == "SELL":
                    pos["quantity"] -= qty
                    # avg_price stays the same on sells

        return positions

    def reconcile(self, broker_positions: dict[str, dict[str, Any]]) -> list[str]:
        """Compare shadow positions with actual broker positions.

        *broker_positions* should be a dict keyed by ticker with at least
        ``quantity`` and ``avg_price`` fields.

        Returns a list of human-readable discrepancy strings (empty == clean).
        """
        shadow = self.get_shadow_positions()
        discrepancies: list[str] = []

        all_tickers = set(shadow.keys()) | set(broker_positions.keys())
        for ticker in sorted(all_tickers):
            s_qty = shadow.get(ticker, {}).get("quantity", 0)
            b_qty = broker_positions.get(ticker, {}).get("quantity", 0)
            if s_qty != b_qty:
                msg = (f"{ticker}: shadow qty={s_qty} vs broker qty={b_qty}")
                discrepancies.append(msg)
                logger.warning("Reconcile mismatch – %s", msg)

        if not discrepancies:
            logger.info("Reconcile: shadow and broker positions match")
        return discrepancies


# ---------------------------------------------------------------------------
# Order manager
# ---------------------------------------------------------------------------

class OrderManager:
    """Central order routing with risk checks, mode switching, and trade logging."""

    def __init__(self, broker_adapter: Any, settings: Settings) -> None:
        self._broker = broker_adapter
        self._settings = settings
        self._risk = RiskControls(settings)
        self._ledger = ShadowLedger()
        self._mode: TradingMode = TradingMode.MANUAL
        self._halted: bool = False
        self._pending_signals: dict[str, dict[str, Any]] = {}  # signal_id -> signal_dict
        self._lock = threading.Lock()
        self._callbacks: list[Any] = []  # optional broadcast listeners

    # -- properties ---------------------------------------------------------

    @property
    def ledger(self) -> ShadowLedger:
        return self._ledger

    @property
    def risk(self) -> RiskControls:
        return self._risk

    # -- mode management ----------------------------------------------------

    def set_mode(self, mode: str) -> None:
        if mode not in (TradingMode.AUTO, TradingMode.MANUAL):
            raise ValueError(f"Invalid mode: {mode!r}. Must be 'auto' or 'manual'.")
        self._mode = TradingMode(mode)
        logger.info("Trading mode set to %s", self._mode.value)

    def get_mode(self) -> str:
        return self._mode.value

    # -- signal queue (manual mode) -----------------------------------------

    def get_pending_signals(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._pending_signals.values())

    def approve_signal(self, signal_id: str) -> dict[str, Any] | None:
        """Approve and immediately execute a queued signal."""
        with self._lock:
            signal = self._pending_signals.pop(signal_id, None)
        if signal is None:
            logger.warning("Signal %s not found in pending queue", signal_id)
            return None
        return self._place_order(signal)

    def reject_signal(self, signal_id: str) -> bool:
        """Remove a signal from the pending queue without executing."""
        with self._lock:
            signal = self._pending_signals.pop(signal_id, None)
        if signal is None:
            logger.warning("Signal %s not found in pending queue", signal_id)
            return False
        logger.info("Signal %s rejected", signal_id)
        return True

    # -- core execution -----------------------------------------------------

    def execute_signal(self, signal_dict: dict[str, Any]) -> dict[str, Any] | None:
        """Validate risk constraints, then place (auto) or queue (manual) the order.

        *signal_dict* must contain at least: ``ticker``, ``action``, ``quantity``,
        ``price``.  Optional: ``strategy_name``, ``signal_confidence``, ``signal_id``.

        Returns a result dict on immediate execution, or ``None`` when queued.
        """
        if self._halted:
            logger.warning("Order rejected – system is HALTED")
            return {"status": OrderStatus.HALTED.value, "reason": "System is halted"}

        # Ensure a unique signal_id for queue tracking
        if "signal_id" not in signal_dict:
            signal_dict["signal_id"] = uuid.uuid4().hex

        # --- risk checks ---
        ticker = signal_dict["ticker"]
        quantity = int(signal_dict["quantity"])
        price = float(signal_dict["price"])

        portfolio = self._broker.get_portfolio()
        total_value: float = portfolio.get("total_value", 0.0) if isinstance(portfolio, dict) else 0.0

        # Position limit
        if signal_dict["action"] == "BUY":
            ok, reason = self._risk.check_position_limit(ticker, quantity, price, total_value)
            if not ok:
                logger.warning("Risk: position limit – %s", reason)
                self._log_trade(signal_dict, status=OrderStatus.ERROR, reason=reason)
                return {"status": OrderStatus.ERROR.value, "reason": reason}

        # Daily loss
        ok, reason = self._risk.check_daily_loss(total_value)
        if not ok:
            logger.warning("Risk: daily loss – %s", reason)
            self.emergency_stop()
            return {"status": OrderStatus.HALTED.value, "reason": reason}

        # Stop-loss (for sells triggered by stop-loss, or informational)
        if signal_dict["action"] == "SELL":
            positions = portfolio.get("positions", {}) if isinstance(portfolio, dict) else {}
            pos = positions.get(ticker)
            if pos:
                avg = pos.get("avg_price", 0.0)
                ok, reason = self._risk.check_stop_loss(ticker, price, avg)
                if not ok:
                    logger.info("Risk: stop-loss info – %s (proceeding with sell)", reason)

        # --- route by mode ---
        if self._mode == TradingMode.AUTO:
            return self._place_order(signal_dict)
        else:
            with self._lock:
                self._pending_signals[signal_dict["signal_id"]] = signal_dict
            logger.info("Signal %s queued for manual approval", signal_dict["signal_id"])
            return None

    # -- emergency stop -----------------------------------------------------

    def emergency_stop(self) -> None:
        """Cancel all pending orders, set HALTED, broadcast to listeners."""
        self._halted = True
        logger.critical("EMERGENCY STOP activated")

        # Cancel pending signals in the queue
        with self._lock:
            cancelled_ids = list(self._pending_signals.keys())
            self._pending_signals.clear()

        for sid in cancelled_ids:
            logger.info("Emergency: cancelled queued signal %s", sid)

        # Mark all shadow-pending orders as cancelled
        with self._ledger._lock:
            for order in self._ledger._orders.values():
                if order.status == OrderStatus.PENDING:
                    order.status = OrderStatus.CANCELLED
                    logger.info("Emergency: cancelled shadow order %s", order.order_id)

        # Broadcast
        for cb in self._callbacks:
            try:
                cb({"event": "emergency_stop", "timestamp": datetime.utcnow().isoformat()})
            except Exception:
                logger.exception("Error in emergency_stop callback")

    def reset_halt(self) -> None:
        """Clear the HALTED state so trading can resume."""
        self._halted = False
        logger.info("HALTED state cleared")

    def register_callback(self, callback: Any) -> None:
        self._callbacks.append(callback)

    # -- internal -----------------------------------------------------------

    def _place_order(self, signal_dict: dict[str, Any]) -> dict[str, Any]:
        """Send an order to the broker and update both shadow ledger and DB."""
        ticker = signal_dict["ticker"]
        action = signal_dict["action"]
        quantity = int(signal_dict["quantity"])
        price = float(signal_dict["price"])

        order_id = uuid.uuid4().hex

        # Shadow ledger
        shadow_order = ShadowOrder(
            order_id=order_id,
            ticker=ticker,
            action=action,
            quantity=quantity,
            price=price,
        )
        self._ledger.add_pending(shadow_order)

        # Call broker
        try:
            result = self._broker.place_order(ticker, action, quantity, price)
            broker_order_id = result.get("order_id", "") if isinstance(result, dict) else str(result)
        except Exception as exc:
            logger.exception("Broker order failed for %s", ticker)
            self._ledger.mark_cancelled(order_id)
            self._log_trade(signal_dict, status=OrderStatus.ERROR, broker_order_id="", reason=str(exc))
            return {"status": OrderStatus.ERROR.value, "reason": str(exc)}

        # Assume FILLED for simplicity; real system would poll / use websocket.
        self._ledger.mark_filled(order_id, price, quantity)

        # Persist to DB
        self._log_trade(
            signal_dict,
            status=OrderStatus.FILLED,
            broker_order_id=broker_order_id,
        )

        logger.info("Order placed: %s %s %s x%d @%.2f [broker_id=%s]",
                     order_id, action, ticker, quantity, price, broker_order_id)

        return {
            "status": OrderStatus.FILLED.value,
            "order_id": order_id,
            "broker_order_id": broker_order_id,
            "ticker": ticker,
            "action": action,
            "quantity": quantity,
            "price": price,
        }

    @staticmethod
    def _log_trade(
        signal_dict: dict[str, Any],
        *,
        status: OrderStatus,
        broker_order_id: str = "",
        reason: str = "",
    ) -> None:
        """Persist a trade record to the database."""
        db = SessionLocal()
        try:
            trade = Trade(
                ticker=signal_dict["ticker"],
                action=signal_dict["action"],
                quantity=int(signal_dict["quantity"]),
                price=float(signal_dict["price"]),
                broker_order_id=broker_order_id,
                strategy_name=signal_dict.get("strategy_name", ""),
                signal_confidence=signal_dict.get("signal_confidence"),
                status=status.value,
            )
            db.add(trade)
            db.commit()
            logger.debug("Trade logged: %s %s %s – %s",
                         trade.action, trade.ticker, trade.status, reason or "ok")
        except Exception:
            db.rollback()
            logger.exception("Failed to log trade to database")
        finally:
            db.close()
