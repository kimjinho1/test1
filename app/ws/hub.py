"""WebSocket hub for broadcasting real-time updates to connected clients."""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketHub:
    """Manages WebSocket connections and broadcasts messages to all clients."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def client_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket client."""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WebSocket client connected (total: %d)", self.client_count)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket client from the connection set."""
        self._connections.discard(websocket)
        logger.info("WebSocket client disconnected (total: %d)", self.client_count)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a JSON message to every connected client.

        Clients that fail to receive the message are silently removed.
        """
        if not self._connections:
            return

        async with self._lock:
            stale: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_json(message)
                except Exception:
                    stale.append(ws)

            for ws in stale:
                self._connections.discard(ws)
                logger.warning("Removed stale WebSocket client (total: %d)", len(self._connections))

    # ------------------------------------------------------------------
    # Typed broadcast helpers
    # ------------------------------------------------------------------

    async def broadcast_price(self, ticker: str, price_data: dict[str, Any]) -> None:
        """Broadcast a real-time price update."""
        await self.broadcast({
            "type": "price",
            "data": {"ticker": ticker, **price_data},
        })

    async def broadcast_signal(self, signal: dict[str, Any]) -> None:
        """Broadcast a new trading signal."""
        await self.broadcast({
            "type": "signal",
            "data": signal,
        })

    async def broadcast_portfolio(self, portfolio: dict[str, Any]) -> None:
        """Broadcast a portfolio snapshot."""
        await self.broadcast({
            "type": "portfolio",
            "data": portfolio,
        })

    async def broadcast_trade(self, trade: dict[str, Any]) -> None:
        """Broadcast a trade execution event."""
        await self.broadcast({
            "type": "trade",
            "data": trade,
        })

    async def broadcast_status(self, status: dict[str, Any]) -> None:
        """Broadcast a system status event (market open/close, mode change, etc.)."""
        await self.broadcast({
            "type": "status",
            "data": status,
        })


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

hub = WebSocketHub()
