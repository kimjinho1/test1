"""Tests for OrderManager, ShadowLedger, and RiskControls."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.services.orders import (
    OrderManager,
    OrderStatus,
    RiskControls,
    ShadowLedger,
    ShadowOrder,
    TradingMode,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_settings() -> Settings:
    """Settings with default risk parameters."""
    return Settings(
        max_position_pct=10.0,
        stop_loss_pct=3.0,
        daily_loss_limit_pct=5.0,
    )


@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.get_portfolio.return_value = {
        "total_value": 100_000_000.0,
        "positions": {},
    }
    broker.place_order.return_value = {"order_id": "BROKER-001"}
    return broker


# ---------------------------------------------------------------------------
# RiskControls
# ---------------------------------------------------------------------------

class TestRiskControls:

    def test_position_limit_passes(self, default_settings):
        rc = RiskControls(default_settings)
        ok, reason = rc.check_position_limit("005930", 10, 70_000, 100_000_000)
        assert ok is True
        assert reason == ""

    def test_position_limit_exceeds(self, default_settings):
        rc = RiskControls(default_settings)
        # 11% of portfolio
        ok, reason = rc.check_position_limit("005930", 110, 100_000, 100_000_000)
        assert ok is False
        assert "limit" in reason

    def test_position_limit_zero_portfolio(self, default_settings):
        rc = RiskControls(default_settings)
        ok, reason = rc.check_position_limit("005930", 1, 70_000, 0)
        assert ok is False
        assert "zero or negative" in reason

    def test_position_limit_exactly_at_limit(self, default_settings):
        rc = RiskControls(default_settings)
        # Exactly 10% should pass
        ok, reason = rc.check_position_limit("005930", 10, 100_000, 10_000_000)
        assert ok is True

    def test_position_limit_just_over(self, default_settings):
        rc = RiskControls(default_settings)
        # 10.001% should fail
        ok, reason = rc.check_position_limit("005930", 10001, 100, 10_000_000)
        assert ok is False

    def test_daily_loss_first_call_passes(self, default_settings):
        rc = RiskControls(default_settings)
        ok, reason = rc.check_daily_loss(100_000_000)
        assert ok is True

    def test_daily_loss_within_limit(self, default_settings):
        rc = RiskControls(default_settings)
        rc.check_daily_loss(100_000_000)  # set baseline
        ok, reason = rc.check_daily_loss(96_000_000)  # 4% loss, limit is 5%
        assert ok is True

    def test_daily_loss_exceeds_limit(self, default_settings):
        rc = RiskControls(default_settings)
        rc._day_start_value = 100_000_000
        rc._current_date = date.today()
        ok, reason = rc.check_daily_loss(94_000_000)  # 6% loss
        assert ok is False
        assert "limit" in reason

    def test_daily_loss_zero_start_value(self, default_settings):
        rc = RiskControls(default_settings)
        rc._day_start_value = 0
        rc._current_date = date.today()
        ok, reason = rc.check_daily_loss(100)
        assert ok is False
        assert "zero or negative" in reason

    def test_stop_loss_passes(self, default_settings):
        rc = RiskControls(default_settings)
        # Price down 2%, limit 3%
        ok, reason = rc.check_stop_loss("005930", 69_000, 70_000)
        assert ok is True

    def test_stop_loss_triggers(self, default_settings):
        rc = RiskControls(default_settings)
        # Price down 5%, limit 3%
        ok, reason = rc.check_stop_loss("005930", 66_500, 70_000)
        assert ok is False
        assert "stop-loss" in reason

    def test_stop_loss_zero_avg_price(self, default_settings):
        rc = RiskControls(default_settings)
        ok, reason = rc.check_stop_loss("005930", 70_000, 0)
        assert ok is False
        assert "zero or negative" in reason

    def test_stop_loss_exactly_at_limit(self, default_settings):
        rc = RiskControls(default_settings)
        # Exactly 3% down
        ok, reason = rc.check_stop_loss("005930", 67_900, 70_000)
        assert ok is False  # >= limit triggers


# ---------------------------------------------------------------------------
# ShadowLedger
# ---------------------------------------------------------------------------

class TestShadowLedger:

    def _make_order(self, **kwargs) -> ShadowOrder:
        defaults = dict(
            order_id="O001",
            ticker="005930",
            action="BUY",
            quantity=10,
            price=70_000.0,
        )
        defaults.update(kwargs)
        return ShadowOrder(**defaults)

    def test_add_pending(self):
        ledger = ShadowLedger()
        order = self._make_order()
        ledger.add_pending(order)
        positions = ledger.get_shadow_positions()
        assert "005930" in positions
        assert positions["005930"]["quantity"] == 10

    def test_mark_filled_full(self):
        ledger = ShadowLedger()
        order = self._make_order()
        ledger.add_pending(order)
        ledger.mark_filled("O001", 71_000.0, 10)

        # Check the order status
        assert ledger._orders["O001"].status == OrderStatus.FILLED
        assert ledger._orders["O001"].fill_price == 71_000.0

    def test_mark_filled_partial(self):
        ledger = ShadowLedger()
        order = self._make_order(quantity=10)
        ledger.add_pending(order)
        ledger.mark_filled("O001", 71_000.0, 5)

        assert ledger._orders["O001"].status == OrderStatus.PARTIAL

    def test_mark_filled_unknown_order(self):
        ledger = ShadowLedger()
        ledger.mark_filled("NOPE", 100.0, 1)  # should not raise

    def test_mark_cancelled(self):
        ledger = ShadowLedger()
        order = self._make_order()
        ledger.add_pending(order)
        ledger.mark_cancelled("O001")
        assert ledger._orders["O001"].status == OrderStatus.CANCELLED

    def test_mark_cancelled_unknown_order(self):
        ledger = ShadowLedger()
        ledger.mark_cancelled("NOPE")  # should not raise

    def test_cancelled_excluded_from_positions(self):
        ledger = ShadowLedger()
        order = self._make_order()
        ledger.add_pending(order)
        ledger.mark_cancelled("O001")
        positions = ledger.get_shadow_positions()
        # Cancelled orders are excluded
        qty = positions.get("005930", {}).get("quantity", 0)
        assert qty == 0

    def test_shadow_positions_buy_then_sell(self):
        ledger = ShadowLedger()
        ledger.add_pending(self._make_order(order_id="B1", action="BUY", quantity=10, price=70_000))
        ledger.mark_filled("B1", 70_000, 10)

        ledger.add_pending(self._make_order(order_id="S1", action="SELL", quantity=3, price=72_000))
        ledger.mark_filled("S1", 72_000, 3)

        positions = ledger.get_shadow_positions()
        assert positions["005930"]["quantity"] == 7

    def test_shadow_positions_multiple_tickers(self):
        ledger = ShadowLedger()
        ledger.add_pending(self._make_order(order_id="B1", ticker="005930", action="BUY", quantity=10, price=70_000))
        ledger.add_pending(self._make_order(order_id="B2", ticker="000660", action="BUY", quantity=5, price=150_000))
        ledger.mark_filled("B1", 70_000, 10)
        ledger.mark_filled("B2", 150_000, 5)

        positions = ledger.get_shadow_positions()
        assert positions["005930"]["quantity"] == 10
        assert positions["000660"]["quantity"] == 5

    def test_reconcile_matching(self):
        ledger = ShadowLedger()
        ledger.add_pending(self._make_order(order_id="B1", action="BUY", quantity=10, price=70_000))
        ledger.mark_filled("B1", 70_000, 10)

        broker_positions = {"005930": {"quantity": 10, "avg_price": 70_000}}
        discrepancies = ledger.reconcile(broker_positions)
        assert discrepancies == []

    def test_reconcile_mismatch(self):
        ledger = ShadowLedger()
        ledger.add_pending(self._make_order(order_id="B1", action="BUY", quantity=10, price=70_000))
        ledger.mark_filled("B1", 70_000, 10)

        broker_positions = {"005930": {"quantity": 8, "avg_price": 70_000}}
        discrepancies = ledger.reconcile(broker_positions)
        assert len(discrepancies) == 1
        assert "shadow qty=10" in discrepancies[0]
        assert "broker qty=8" in discrepancies[0]

    def test_reconcile_broker_has_extra_ticker(self):
        ledger = ShadowLedger()
        broker_positions = {"000660": {"quantity": 5, "avg_price": 150_000}}
        discrepancies = ledger.reconcile(broker_positions)
        assert len(discrepancies) == 1
        assert "000660" in discrepancies[0]

    def test_reconcile_empty_both(self):
        ledger = ShadowLedger()
        assert ledger.reconcile({}) == []


# ---------------------------------------------------------------------------
# OrderManager
# ---------------------------------------------------------------------------

class TestOrderManagerMode:

    def test_default_mode_is_manual(self, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        assert om.get_mode() == "manual"

    def test_set_mode_auto(self, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        om.set_mode("auto")
        assert om.get_mode() == "auto"

    def test_set_mode_manual(self, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        om.set_mode("auto")
        om.set_mode("manual")
        assert om.get_mode() == "manual"

    def test_set_mode_invalid_raises(self, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        with pytest.raises(ValueError, match="Invalid mode"):
            om.set_mode("turbo")


class TestOrderManagerExecute:

    def _signal(self, **overrides):
        base = {
            "ticker": "005930",
            "action": "BUY",
            "quantity": 10,
            "price": 70_000.0,
            "strategy_name": "test",
        }
        base.update(overrides)
        return base

    @patch("app.services.orders.SessionLocal")
    def test_execute_auto_mode_places_order(self, mock_session_cls, mock_broker, default_settings):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        om = OrderManager(mock_broker, default_settings)
        om.set_mode("auto")

        result = om.execute_signal(self._signal())
        assert result is not None
        assert result["status"] == "FILLED"
        assert result["ticker"] == "005930"
        mock_broker.place_order.assert_called_once()

    @patch("app.services.orders.SessionLocal")
    def test_execute_manual_mode_queues_signal(self, mock_session_cls, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        om.set_mode("manual")

        result = om.execute_signal(self._signal())
        assert result is None  # queued, not executed
        assert len(om.get_pending_signals()) == 1
        mock_broker.place_order.assert_not_called()

    @patch("app.services.orders.SessionLocal")
    def test_approve_signal(self, mock_session_cls, mock_broker, default_settings):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        om = OrderManager(mock_broker, default_settings)
        om.set_mode("manual")

        signal = self._signal(signal_id="SIG001")
        om.execute_signal(signal)

        result = om.approve_signal("SIG001")
        assert result is not None
        assert result["status"] == "FILLED"
        assert len(om.get_pending_signals()) == 0

    @patch("app.services.orders.SessionLocal")
    def test_approve_nonexistent_signal(self, mock_session_cls, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        result = om.approve_signal("NOPE")
        assert result is None

    @patch("app.services.orders.SessionLocal")
    def test_reject_signal(self, mock_session_cls, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        om.set_mode("manual")

        signal = self._signal(signal_id="SIG002")
        om.execute_signal(signal)

        assert om.reject_signal("SIG002") is True
        assert len(om.get_pending_signals()) == 0

    def test_reject_nonexistent_signal(self, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        assert om.reject_signal("NOPE") is False

    @patch("app.services.orders.SessionLocal")
    def test_execute_when_halted(self, mock_session_cls, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        om.emergency_stop()

        result = om.execute_signal(self._signal())
        assert result is not None
        assert result["status"] == "HALTED"

    @patch("app.services.orders.SessionLocal")
    def test_position_limit_rejects_buy(self, mock_session_cls, mock_broker, default_settings):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        # Portfolio value very small, so buy will exceed limit
        mock_broker.get_portfolio.return_value = {"total_value": 100.0, "positions": {}}
        om = OrderManager(mock_broker, default_settings)
        om.set_mode("auto")

        result = om.execute_signal(self._signal(quantity=100, price=70_000))
        assert result is not None
        assert result["status"] == "ERROR"
        assert "limit" in result["reason"]

    @patch("app.services.orders.SessionLocal")
    def test_broker_exception_returns_error(self, mock_session_cls, mock_broker, default_settings):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        mock_broker.place_order.side_effect = RuntimeError("connection lost")
        om = OrderManager(mock_broker, default_settings)
        om.set_mode("auto")

        result = om.execute_signal(self._signal())
        assert result["status"] == "ERROR"
        assert "connection lost" in result["reason"]


class TestOrderManagerEmergencyStop:

    @patch("app.services.orders.SessionLocal")
    def test_emergency_stop_halts_system(self, mock_session_cls, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        om.emergency_stop()
        assert om._halted is True

    @patch("app.services.orders.SessionLocal")
    def test_emergency_stop_clears_pending(self, mock_session_cls, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        om.set_mode("manual")
        om.execute_signal({
            "ticker": "005930", "action": "BUY", "quantity": 1, "price": 70_000,
        })
        assert len(om.get_pending_signals()) == 1
        om.emergency_stop()
        assert len(om.get_pending_signals()) == 0

    @patch("app.services.orders.SessionLocal")
    def test_emergency_stop_cancels_shadow_pending(self, mock_session_cls, mock_broker, default_settings):
        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db

        om = OrderManager(mock_broker, default_settings)
        om.set_mode("auto")

        # Add a shadow order manually as pending
        order = ShadowOrder(
            order_id="X1", ticker="005930", action="BUY",
            quantity=10, price=70_000,
        )
        om.ledger.add_pending(order)
        om.emergency_stop()
        assert om.ledger._orders["X1"].status == OrderStatus.CANCELLED

    @patch("app.services.orders.SessionLocal")
    def test_reset_halt(self, mock_session_cls, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        om.emergency_stop()
        om.reset_halt()
        assert om._halted is False

    @patch("app.services.orders.SessionLocal")
    def test_emergency_stop_callback(self, mock_session_cls, mock_broker, default_settings):
        om = OrderManager(mock_broker, default_settings)
        cb = MagicMock()
        om.register_callback(cb)
        om.emergency_stop()
        cb.assert_called_once()
        call_arg = cb.call_args[0][0]
        assert call_arg["event"] == "emergency_stop"


class TestShadowLedgerAvgPrice:

    def test_avg_price_calculation(self):
        ledger = ShadowLedger()
        # Buy 10 @ 70000
        ledger.add_pending(ShadowOrder(
            order_id="B1", ticker="005930", action="BUY", quantity=10, price=70_000,
        ))
        ledger.mark_filled("B1", 70_000, 10)

        # Buy 10 @ 72000
        ledger.add_pending(ShadowOrder(
            order_id="B2", ticker="005930", action="BUY", quantity=10, price=72_000,
        ))
        ledger.mark_filled("B2", 72_000, 10)

        positions = ledger.get_shadow_positions()
        assert positions["005930"]["quantity"] == 20
        expected_avg = (70_000 * 10 + 72_000 * 10) / 20
        assert positions["005930"]["avg_price"] == pytest.approx(expected_avg)
