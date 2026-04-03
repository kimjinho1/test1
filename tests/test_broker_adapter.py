"""Tests for BrokerAdapter and SubscriptionManager."""

from __future__ import annotations

import types
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.broker_adapter import (
    MAX_SUBSCRIPTIONS,
    BrokerAdapter,
    OrderAction,
    OrderResult,
    OHLCVBar,
    PortfolioItem,
    PriceSnapshot,
    SubscriptionManager,
)


# ---------------------------------------------------------------------------
# SubscriptionManager
# ---------------------------------------------------------------------------

class TestSubscriptionManager:

    def test_subscribe_returns_true(self):
        mgr = SubscriptionManager()
        assert mgr.subscribe("005930", "ticket-a") is True

    def test_subscribe_duplicate_returns_false(self):
        mgr = SubscriptionManager()
        mgr.subscribe("005930", "ticket-a")
        assert mgr.subscribe("005930", "ticket-b") is False

    def test_subscribe_at_max_limit_returns_false(self):
        mgr = SubscriptionManager(max_subscriptions=2)
        mgr.subscribe("A", "t1")
        mgr.subscribe("B", "t2")
        assert mgr.subscribe("C", "t3") is False

    def test_subscribe_respects_default_max(self):
        mgr = SubscriptionManager()
        assert mgr._max == MAX_SUBSCRIPTIONS

    def test_unsubscribe_existing(self):
        mgr = SubscriptionManager()
        mgr.subscribe("005930", "ticket")
        assert mgr.unsubscribe("005930") is True
        assert mgr.is_subscribed("005930") is False

    def test_unsubscribe_nonexistent_returns_false(self):
        mgr = SubscriptionManager()
        assert mgr.unsubscribe("NOPE") is False

    def test_get_active_sorted(self):
        mgr = SubscriptionManager()
        mgr.subscribe("C", "t1")
        mgr.subscribe("A", "t2")
        mgr.subscribe("B", "t3")
        assert mgr.get_active() == ["A", "B", "C"]

    def test_is_subscribed(self):
        mgr = SubscriptionManager()
        assert mgr.is_subscribed("005930") is False
        mgr.subscribe("005930", "t")
        assert mgr.is_subscribed("005930") is True

    def test_count_property(self):
        mgr = SubscriptionManager()
        assert mgr.count == 0
        mgr.subscribe("A", "t")
        mgr.subscribe("B", "t")
        assert mgr.count == 2

    def test_clear(self):
        mgr = SubscriptionManager()
        mgr.subscribe("A", "t1")
        mgr.subscribe("B", "t2")
        cleared = mgr.clear()
        assert cleared == 2
        assert mgr.count == 0
        assert mgr.get_active() == []

    def test_clear_empty(self):
        mgr = SubscriptionManager()
        assert mgr.clear() == 0

    def test_subscribe_after_clear_works(self):
        mgr = SubscriptionManager(max_subscriptions=1)
        mgr.subscribe("A", "t1")
        mgr.clear()
        assert mgr.subscribe("B", "t2") is True

    def test_full_40_subscriptions(self):
        mgr = SubscriptionManager()
        for i in range(40):
            assert mgr.subscribe(f"T{i:04d}", f"ticket-{i}") is True
        assert mgr.count == 40
        assert mgr.subscribe("T9999", "overflow") is False


# ---------------------------------------------------------------------------
# Mock KIS client
# ---------------------------------------------------------------------------

def _make_mock_client():
    client = MagicMock()
    # No stream attribute so _subscribe_realtime returns mock ticket
    if hasattr(client, "stream"):
        del client.stream
    return client


# ---------------------------------------------------------------------------
# BrokerAdapter
# ---------------------------------------------------------------------------

class TestBrokerAdapterLifecycle:

    @patch("app.services.broker_adapter.settings")
    def test_connect_sets_connected(self, mock_settings):
        mock_settings.kis_is_virtual = True
        adapter = BrokerAdapter(client=_make_mock_client())
        adapter.connect()
        assert adapter.is_connected is True

    @patch("app.services.broker_adapter.settings")
    def test_connect_idempotent(self, mock_settings):
        mock_settings.kis_is_virtual = True
        adapter = BrokerAdapter(client=_make_mock_client())
        adapter.connect()
        adapter.connect()  # second call should be a no-op
        assert adapter.is_connected is True

    @patch("app.services.broker_adapter.settings")
    def test_disconnect(self, mock_settings):
        mock_settings.kis_is_virtual = True
        adapter = BrokerAdapter(client=_make_mock_client())
        adapter.connect()
        adapter.disconnect()
        assert adapter.is_connected is False

    def test_disconnect_when_not_connected_is_noop(self):
        adapter = BrokerAdapter(client=_make_mock_client())
        adapter.disconnect()  # should not raise
        assert adapter.is_connected is False


class TestBrokerAdapterOrders:

    def _connected_adapter(self):
        client = _make_mock_client()
        adapter = BrokerAdapter(client=client)
        adapter._connected = True
        return adapter, client

    def test_place_order_not_connected_raises(self):
        adapter = BrokerAdapter(client=_make_mock_client())
        with pytest.raises(RuntimeError, match="not connected"):
            adapter.place_order("005930", OrderAction.BUY, 10)

    def test_place_buy_order_success(self):
        adapter, client = self._connected_adapter()
        resp = MagicMock()
        resp.order_no = "ORD123"
        client.buy.return_value = resp

        result = adapter.place_order("005930", OrderAction.BUY, 10, 71000)

        client.buy.assert_called_once_with("005930", 10, 71000)
        assert result.success is True
        assert result.broker_order_id == "ORD123"
        assert result.filled_quantity == 10
        assert result.filled_price == 71000.0

    def test_place_sell_order_success(self):
        adapter, client = self._connected_adapter()
        resp = MagicMock()
        resp.order_no = "ORD456"
        client.sell.return_value = resp

        result = adapter.place_order("005930", "SELL", 5, 72000)

        client.sell.assert_called_once_with("005930", 5, 72000)
        assert result.success is True
        assert result.broker_order_id == "ORD456"

    def test_place_order_market_price(self):
        adapter, client = self._connected_adapter()
        resp = MagicMock()
        resp.order_no = "ORD789"
        client.buy.return_value = resp

        result = adapter.place_order("005930", OrderAction.BUY, 1, None)

        client.buy.assert_called_once_with("005930", 1, None)
        assert result.success is True
        assert result.filled_price == 0.0  # None price -> 0.0

    def test_place_order_broker_exception(self):
        adapter, client = self._connected_adapter()
        client.buy.side_effect = RuntimeError("Network error")

        result = adapter.place_order("005930", OrderAction.BUY, 10, 71000)

        assert result.success is False
        assert "Network error" in result.message

    def test_place_order_dict_response_odno(self):
        adapter, client = self._connected_adapter()
        client.buy.return_value = {"odno": "D001"}

        result = adapter.place_order("005930", OrderAction.BUY, 1, 50000)
        assert result.success is True
        assert result.broker_order_id == "D001"

    def test_place_order_none_response(self):
        adapter, client = self._connected_adapter()
        client.buy.return_value = None

        result = adapter.place_order("005930", OrderAction.BUY, 1, 50000)
        assert result.success is True
        assert result.broker_order_id is None


class TestBrokerAdapterPortfolio:

    def test_get_portfolio(self):
        client = _make_mock_client()
        holding = MagicMock()
        holding.ticker = "005930"
        holding.name = "삼성전자"
        holding.quantity = 10
        holding.avg_price = 70000.0
        holding.current_price = 72000.0
        client.balance.return_value = [holding]

        adapter = BrokerAdapter(client=client)
        adapter._connected = True

        items = adapter.get_portfolio()
        assert len(items) == 1
        assert items[0].ticker == "005930"
        assert items[0].name == "삼성전자"
        assert items[0].pnl == (72000.0 - 70000.0) * 10

    def test_get_portfolio_empty(self):
        client = _make_mock_client()
        client.balance.return_value = []
        adapter = BrokerAdapter(client=client)
        adapter._connected = True
        assert adapter.get_portfolio() == []

    def test_get_portfolio_exception_returns_empty(self):
        client = _make_mock_client()
        client.balance.side_effect = RuntimeError("fail")
        adapter = BrokerAdapter(client=client)
        adapter._connected = True
        assert adapter.get_portfolio() == []


class TestBrokerAdapterPrice:

    def test_get_current_price(self):
        client = _make_mock_client()
        quote = MagicMock()
        quote.price = 71500.0
        quote.volume = 123456
        client.quote.return_value = quote

        adapter = BrokerAdapter(client=client)
        adapter._connected = True

        snap = adapter.get_current_price("005930")
        assert snap is not None
        assert snap.ticker == "005930"
        assert snap.price == 71500.0
        assert snap.volume == 123456

    def test_get_current_price_exception_returns_none(self):
        client = _make_mock_client()
        client.quote.side_effect = RuntimeError("timeout")
        adapter = BrokerAdapter(client=client)
        adapter._connected = True
        assert adapter.get_current_price("005930") is None


class TestBrokerAdapterSubscribe:

    @patch("app.services.broker_adapter.settings")
    def test_subscribe_success(self, mock_settings):
        mock_settings.kis_is_virtual = True
        client = _make_mock_client()
        adapter = BrokerAdapter(client=client)
        adapter.connect()

        assert adapter.subscribe("005930") is True
        assert "005930" in adapter.get_subscribed_tickers()

    @patch("app.services.broker_adapter.settings")
    def test_subscribe_duplicate(self, mock_settings):
        mock_settings.kis_is_virtual = True
        client = _make_mock_client()
        adapter = BrokerAdapter(client=client)
        adapter.connect()

        adapter.subscribe("005930")
        assert adapter.subscribe("005930") is False

    @patch("app.services.broker_adapter.settings")
    def test_unsubscribe(self, mock_settings):
        mock_settings.kis_is_virtual = True
        client = _make_mock_client()
        adapter = BrokerAdapter(client=client)
        adapter.connect()

        adapter.subscribe("005930")
        assert adapter.unsubscribe("005930") is True
        assert "005930" not in adapter.get_subscribed_tickers()


class TestBrokerAdapterPriceCallback:

    def test_price_callback_invoked(self):
        callback = MagicMock()
        adapter = BrokerAdapter(client=_make_mock_client(), on_price_update=callback)

        snap = PriceSnapshot(ticker="005930", price=71000, volume=100, timestamp=datetime.now())
        adapter._emit_price(snap)

        callback.assert_called_once_with(snap)

    def test_price_callback_exception_suppressed(self):
        callback = MagicMock(side_effect=ValueError("boom"))
        adapter = BrokerAdapter(client=_make_mock_client(), on_price_update=callback)

        snap = PriceSnapshot(ticker="005930", price=71000, volume=100, timestamp=datetime.now())
        adapter._emit_price(snap)  # should not raise

    def test_no_callback_is_safe(self):
        adapter = BrokerAdapter(client=_make_mock_client())
        snap = PriceSnapshot(ticker="005930", price=71000, volume=100, timestamp=datetime.now())
        adapter._emit_price(snap)  # should not raise


class TestDataClasses:

    def test_order_action_enum(self):
        assert OrderAction("BUY") is OrderAction.BUY
        assert OrderAction("SELL") is OrderAction.SELL
        with pytest.raises(ValueError):
            OrderAction("HOLD")

    def test_order_result_frozen(self):
        r = OrderResult(success=True, broker_order_id="123")
        with pytest.raises(AttributeError):
            r.success = False  # type: ignore[misc]

    def test_price_snapshot_frozen(self):
        s = PriceSnapshot(ticker="A", price=100.0, volume=1, timestamp=datetime.now())
        assert s.ticker == "A"

    def test_ohlcv_bar(self):
        bar = OHLCVBar(
            date=datetime(2024, 1, 1),
            open=100.0, high=110.0, low=90.0, close=105.0, volume=1000,
        )
        assert bar.close == 105.0
