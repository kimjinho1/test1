"""Tests for WebSocketHub."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ws.hub import WebSocketHub


# ---------------------------------------------------------------------------
# Mock WebSocket
# ---------------------------------------------------------------------------

class MockWebSocket:
    """Lightweight mock that mimics FastAPI's WebSocket for testing."""

    def __init__(self, *, fail_on_send: bool = False) -> None:
        self.accepted = False
        self.sent_messages: list[dict] = []
        self._fail_on_send = fail_on_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        if self._fail_on_send:
            raise RuntimeError("WebSocket send failed")
        self.sent_messages.append(data)


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

class TestWebSocketHubConnect:

    @pytest.mark.asyncio
    async def test_connect_accepts_websocket(self):
        hub = WebSocketHub()
        ws = MockWebSocket()
        await hub.connect(ws)
        assert ws.accepted is True
        assert hub.client_count == 1

    @pytest.mark.asyncio
    async def test_connect_multiple_clients(self):
        hub = WebSocketHub()
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        await hub.connect(ws1)
        await hub.connect(ws2)
        assert hub.client_count == 2

    @pytest.mark.asyncio
    async def test_disconnect_removes_client(self):
        hub = WebSocketHub()
        ws = MockWebSocket()
        await hub.connect(ws)
        hub.disconnect(ws)
        assert hub.client_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_is_safe(self):
        hub = WebSocketHub()
        ws = MockWebSocket()
        hub.disconnect(ws)  # should not raise
        assert hub.client_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_one_of_many(self):
        hub = WebSocketHub()
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        await hub.connect(ws1)
        await hub.connect(ws2)
        hub.disconnect(ws1)
        assert hub.client_count == 1


# ---------------------------------------------------------------------------
# Broadcast
# ---------------------------------------------------------------------------

class TestWebSocketHubBroadcast:

    @pytest.mark.asyncio
    async def test_broadcast_to_all(self):
        hub = WebSocketHub()
        ws1 = MockWebSocket()
        ws2 = MockWebSocket()
        await hub.connect(ws1)
        await hub.connect(ws2)

        msg = {"type": "test", "data": "hello"}
        await hub.broadcast(msg)

        assert msg in ws1.sent_messages
        assert msg in ws2.sent_messages

    @pytest.mark.asyncio
    async def test_broadcast_no_clients(self):
        hub = WebSocketHub()
        await hub.broadcast({"type": "test"})  # should not raise

    @pytest.mark.asyncio
    async def test_broadcast_removes_stale_clients(self):
        hub = WebSocketHub()
        good_ws = MockWebSocket()
        bad_ws = MockWebSocket(fail_on_send=True)
        await hub.connect(good_ws)
        await hub.connect(bad_ws)
        assert hub.client_count == 2

        await hub.broadcast({"type": "test"})

        # Stale client should be removed
        assert hub.client_count == 1
        assert {"type": "test"} in good_ws.sent_messages

    @pytest.mark.asyncio
    async def test_broadcast_all_stale(self):
        hub = WebSocketHub()
        ws1 = MockWebSocket(fail_on_send=True)
        ws2 = MockWebSocket(fail_on_send=True)
        await hub.connect(ws1)
        await hub.connect(ws2)

        await hub.broadcast({"type": "test"})
        assert hub.client_count == 0


# ---------------------------------------------------------------------------
# Typed broadcast helpers
# ---------------------------------------------------------------------------

class TestBroadcastHelpers:

    @pytest.mark.asyncio
    async def test_broadcast_price(self):
        hub = WebSocketHub()
        ws = MockWebSocket()
        await hub.connect(ws)

        await hub.broadcast_price("005930", {"price": 71500, "volume": 1000})

        assert len(ws.sent_messages) == 1
        msg = ws.sent_messages[0]
        assert msg["type"] == "price"
        assert msg["data"]["ticker"] == "005930"
        assert msg["data"]["price"] == 71500

    @pytest.mark.asyncio
    async def test_broadcast_signal(self):
        hub = WebSocketHub()
        ws = MockWebSocket()
        await hub.connect(ws)

        signal = {"action": "BUY", "ticker": "005930", "confidence": 0.9}
        await hub.broadcast_signal(signal)

        msg = ws.sent_messages[0]
        assert msg["type"] == "signal"
        assert msg["data"]["action"] == "BUY"

    @pytest.mark.asyncio
    async def test_broadcast_portfolio(self):
        hub = WebSocketHub()
        ws = MockWebSocket()
        await hub.connect(ws)

        portfolio = {"total_value": 100_000_000, "positions": []}
        await hub.broadcast_portfolio(portfolio)

        msg = ws.sent_messages[0]
        assert msg["type"] == "portfolio"
        assert msg["data"]["total_value"] == 100_000_000

    @pytest.mark.asyncio
    async def test_broadcast_trade(self):
        hub = WebSocketHub()
        ws = MockWebSocket()
        await hub.connect(ws)

        trade = {"ticker": "005930", "action": "BUY", "quantity": 10}
        await hub.broadcast_trade(trade)

        msg = ws.sent_messages[0]
        assert msg["type"] == "trade"
        assert msg["data"]["ticker"] == "005930"

    @pytest.mark.asyncio
    async def test_broadcast_status(self):
        hub = WebSocketHub()
        ws = MockWebSocket()
        await hub.connect(ws)

        await hub.broadcast_status({"mode": "auto", "halted": False})

        msg = ws.sent_messages[0]
        assert msg["type"] == "status"
        assert msg["data"]["mode"] == "auto"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestWebSocketHubEdgeCases:

    @pytest.mark.asyncio
    async def test_client_count_starts_at_zero(self):
        hub = WebSocketHub()
        assert hub.client_count == 0

    @pytest.mark.asyncio
    async def test_multiple_broadcasts_accumulate(self):
        hub = WebSocketHub()
        ws = MockWebSocket()
        await hub.connect(ws)

        await hub.broadcast({"n": 1})
        await hub.broadcast({"n": 2})
        await hub.broadcast({"n": 3})

        assert len(ws.sent_messages) == 3

    @pytest.mark.asyncio
    async def test_connect_disconnect_reconnect(self):
        hub = WebSocketHub()
        ws = MockWebSocket()
        await hub.connect(ws)
        hub.disconnect(ws)
        assert hub.client_count == 0

        # Reconnect the same object
        await hub.connect(ws)
        assert hub.client_count == 1
