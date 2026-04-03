"""
Broker adapter for 한국투자증권 (Korea Investment & Securities) Open API.

Wraps the python-kis library behind a clean interface for order execution,
portfolio queries, real-time price streaming, and historical data retrieval.
Designed so a mock client can be injected when python-kis is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# python-kis conditional import
# ---------------------------------------------------------------------------
try:
    import pykis  # type: ignore[import-untyped]

    KIS_AVAILABLE = True
except ImportError:
    pykis = None  # type: ignore[assignment]
    KIS_AVAILABLE = False
    logger.warning(
        "python-kis is not installed. BrokerAdapter will require an injected client."
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_SUBSCRIPTIONS = 40  # KIS WebSocket hard limit


# ---------------------------------------------------------------------------
# Data classes returned by the adapter
# ---------------------------------------------------------------------------
class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class OrderResult:
    success: bool
    broker_order_id: str | None = None
    message: str = ""
    filled_quantity: int = 0
    filled_price: float = 0.0


@dataclass(frozen=True)
class PortfolioItem:
    ticker: str
    name: str
    quantity: int
    avg_price: float
    current_price: float
    pnl: float
    pnl_pct: float


@dataclass(frozen=True)
class PriceSnapshot:
    ticker: str
    price: float
    volume: int
    timestamp: datetime


@dataclass(frozen=True)
class OHLCVBar:
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


# ---------------------------------------------------------------------------
# Protocol for the KIS client (enables dependency injection / mocking)
# ---------------------------------------------------------------------------
@runtime_checkable
class KisClientProtocol(Protocol):
    """Minimal interface that BrokerAdapter expects from a KIS client."""

    def buy(
        self, ticker: str, quantity: int, price: int | None = None
    ) -> Any: ...

    def sell(
        self, ticker: str, quantity: int, price: int | None = None
    ) -> Any: ...

    def balance(self) -> Any: ...

    def quote(self, ticker: str) -> Any: ...

    def daily_ohlcv(self, ticker: str, period: str) -> Any: ...


# ---------------------------------------------------------------------------
# SubscriptionManager
# ---------------------------------------------------------------------------
class SubscriptionManager:
    """
    Manages real-time price subscriptions.

    Keeps strong references to subscription tickets so the garbage collector
    cannot silently drop them.  Enforces the KIS WebSocket limit of 40
    concurrent subscriptions.
    """

    def __init__(self, max_subscriptions: int = MAX_SUBSCRIPTIONS) -> None:
        self._subscriptions: dict[str, Any] = {}
        self._max = max_subscriptions

    # -- public API --------------------------------------------------------

    def subscribe(self, ticker: str, ticket: Any) -> bool:
        """
        Register a subscription ticket.

        Returns True if added, False if already subscribed or at capacity.
        """
        if ticker in self._subscriptions:
            logger.debug("Already subscribed to %s", ticker)
            return False

        if len(self._subscriptions) >= self._max:
            logger.warning(
                "Subscription limit (%d) reached. Cannot subscribe to %s",
                self._max,
                ticker,
            )
            return False

        self._subscriptions[ticker] = ticket
        logger.info(
            "Subscribed to %s (%d/%d)",
            ticker,
            len(self._subscriptions),
            self._max,
        )
        return True

    def unsubscribe(self, ticker: str) -> bool:
        """Remove and return True if the ticker was subscribed, else False."""
        ticket = self._subscriptions.pop(ticker, None)
        if ticket is None:
            return False
        logger.info(
            "Unsubscribed from %s (%d/%d)",
            ticker,
            len(self._subscriptions),
            self._max,
        )
        return True

    def get_active(self) -> list[str]:
        """Return a sorted list of currently subscribed tickers."""
        return sorted(self._subscriptions)

    def is_subscribed(self, ticker: str) -> bool:
        return ticker in self._subscriptions

    @property
    def count(self) -> int:
        return len(self._subscriptions)

    def clear(self) -> int:
        """Unsubscribe all. Returns the number of subscriptions removed."""
        n = len(self._subscriptions)
        self._subscriptions.clear()
        logger.info("Cleared all %d subscriptions", n)
        return n


# ---------------------------------------------------------------------------
# BrokerAdapter
# ---------------------------------------------------------------------------
PriceCallback = Callable[[PriceSnapshot], Any]


class BrokerAdapter:
    """
    High-level broker facade.

    Parameters
    ----------
    client : KisClientProtocol | None
        An optional pre-built KIS client.  When *None* the adapter will try
        to create one from ``app.config.settings`` using python-kis.
    on_price_update : PriceCallback | None
        Callback invoked on every real-time price tick.
    """

    def __init__(
        self,
        client: KisClientProtocol | None = None,
        on_price_update: PriceCallback | None = None,
    ) -> None:
        self._client: KisClientProtocol | None = client
        self._connected: bool = False
        self._on_price_update: PriceCallback | None = on_price_update
        self._subscriptions = SubscriptionManager()

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> None:
        """Initialise the KIS client (if not injected) and mark as connected."""
        if self._connected:
            logger.debug("BrokerAdapter already connected")
            return

        if self._client is None:
            self._client = self._create_default_client()

        self._connected = True
        logger.info("BrokerAdapter connected (virtual=%s)", settings.kis_is_virtual)

    def disconnect(self) -> None:
        """Tear down subscriptions and mark as disconnected."""
        if not self._connected:
            return
        cleared = self._subscriptions.clear()
        self._connected = False
        logger.info("BrokerAdapter disconnected (cleared %d subscriptions)", cleared)

    @property
    def is_connected(self) -> bool:
        return self._connected

    # -- callbacks ---------------------------------------------------------

    def set_price_callback(self, callback: PriceCallback | None) -> None:
        self._on_price_update = callback

    def _emit_price(self, snapshot: PriceSnapshot) -> None:
        if self._on_price_update is not None:
            try:
                self._on_price_update(snapshot)
            except Exception:
                logger.exception("Price callback raised for %s", snapshot.ticker)

    # -- real-time subscriptions -------------------------------------------

    def subscribe(self, ticker: str) -> bool:
        """
        Subscribe to real-time price updates for *ticker*.

        Returns True on success, False if already subscribed or at capacity.
        """
        self._ensure_connected()

        if self._subscriptions.is_subscribed(ticker):
            return False

        try:
            # python-kis streaming returns a subscription ticket.
            # We store it to prevent GC from dropping it.
            ticket = self._subscribe_realtime(ticker)
            return self._subscriptions.subscribe(ticker, ticket)
        except Exception:
            logger.exception("Failed to subscribe to %s", ticker)
            return False

    def unsubscribe(self, ticker: str) -> bool:
        """Unsubscribe from real-time updates for *ticker*."""
        return self._subscriptions.unsubscribe(ticker)

    def get_subscribed_tickers(self) -> list[str]:
        return self._subscriptions.get_active()

    # -- order placement ---------------------------------------------------

    def place_order(
        self,
        ticker: str,
        action: str | OrderAction,
        quantity: int,
        price: int | None = None,
    ) -> OrderResult:
        """
        Place a buy or sell order.

        Parameters
        ----------
        ticker : str
            Stock code (e.g. ``"005930"`` for Samsung Electronics).
        action : str | OrderAction
            ``"BUY"`` or ``"SELL"``.
        quantity : int
            Number of shares.
        price : int | None
            Limit price in KRW.  ``None`` means market order.
        """
        self._ensure_connected()
        assert self._client is not None

        action_enum = OrderAction(action) if isinstance(action, str) else action

        logger.info(
            "Placing %s order: %s x%d @ %s",
            action_enum.value,
            ticker,
            quantity,
            price if price is not None else "MARKET",
        )

        try:
            if action_enum is OrderAction.BUY:
                resp = self._client.buy(ticker, quantity, price)
            else:
                resp = self._client.sell(ticker, quantity, price)

            order_id = self._extract_order_id(resp)

            return OrderResult(
                success=True,
                broker_order_id=order_id,
                message="Order placed",
                filled_quantity=quantity,
                filled_price=float(price) if price else 0.0,
            )

        except Exception as exc:
            logger.exception("Order failed for %s", ticker)
            return OrderResult(success=False, message=str(exc))

    # -- portfolio ---------------------------------------------------------

    def get_portfolio(self) -> list[PortfolioItem]:
        """Return current holdings as a list of ``PortfolioItem``."""
        self._ensure_connected()
        assert self._client is not None

        try:
            raw = self._client.balance()
            return self._parse_portfolio(raw)
        except Exception:
            logger.exception("Failed to fetch portfolio")
            return []

    # -- market data -------------------------------------------------------

    def get_current_price(self, ticker: str) -> PriceSnapshot | None:
        """Fetch the latest price snapshot for *ticker*."""
        self._ensure_connected()
        assert self._client is not None

        try:
            raw = self._client.quote(ticker)
            return self._parse_quote(ticker, raw)
        except Exception:
            logger.exception("Failed to get price for %s", ticker)
            return None

    def get_ohlcv(
        self, ticker: str, period: str = "D"
    ) -> list[OHLCVBar]:
        """
        Fetch historical OHLCV bars.

        Parameters
        ----------
        period : str
            ``"D"`` (daily), ``"W"`` (weekly), ``"M"`` (monthly).
        """
        self._ensure_connected()
        assert self._client is not None

        try:
            raw = self._client.daily_ohlcv(ticker, period)
            return self._parse_ohlcv(raw)
        except Exception:
            logger.exception("Failed to get OHLCV for %s", ticker)
            return []

    # ======================================================================
    # Private helpers
    # ======================================================================

    def _ensure_connected(self) -> None:
        if not self._connected or self._client is None:
            raise RuntimeError(
                "BrokerAdapter is not connected. Call connect() first."
            )

    # -- client factory ----------------------------------------------------

    @staticmethod
    def _create_default_client() -> KisClientProtocol:
        """Build a real PyKis client from settings. Raises if lib missing."""
        if not KIS_AVAILABLE or pykis is None:
            raise ImportError(
                "python-kis is not installed. "
                "Install it (`pip install python-kis`) or inject a mock client."
            )

        key = settings.kis_app_key
        secret = settings.kis_app_secret
        account = settings.kis_account_no
        virtual = settings.kis_is_virtual

        if not key or not secret or not account:
            raise ValueError(
                "KIS credentials are not configured. "
                "Set kis_app_key, kis_app_secret, and kis_account_no."
            )

        logger.info(
            "Creating PyKis client (account=%s, virtual=%s)", account, virtual
        )
        kis = pykis.Api(
            key=key,
            secret=secret,
            account=account,
            virtual=virtual,
        )
        return kis  # type: ignore[return-value]

    # -- real-time helpers -------------------------------------------------

    def _subscribe_realtime(self, ticker: str) -> Any:
        """
        Start a real-time price stream for *ticker*.

        Returns a subscription ticket (or a sentinel when the library is
        absent and a mock client is used).
        """
        assert self._client is not None

        if KIS_AVAILABLE and pykis is not None and hasattr(self._client, "stream"):
            stream = self._client.stream  # type: ignore[attr-defined]
            ticket = stream.subscribe(ticker, callback=self._handle_realtime_tick)
            return ticket

        # Fallback: client has no streaming support (e.g. mock).
        logger.debug(
            "Client has no streaming support; subscription for %s is a no-op",
            ticker,
        )
        return f"mock-ticket-{ticker}"

    def _handle_realtime_tick(self, data: Any) -> None:
        """Callback wired to the KIS WebSocket stream."""
        try:
            ticker = str(getattr(data, "ticker", getattr(data, "code", "")))
            price = float(getattr(data, "price", getattr(data, "current", 0)))
            volume = int(getattr(data, "volume", 0))

            snapshot = PriceSnapshot(
                ticker=ticker,
                price=price,
                volume=volume,
                timestamp=datetime.now(),
            )
            self._emit_price(snapshot)
        except Exception:
            logger.exception("Error handling real-time tick")

    # -- response parsers --------------------------------------------------

    @staticmethod
    def _extract_order_id(response: Any) -> str | None:
        """Best-effort extraction of the broker order ID from a KIS response."""
        if response is None:
            return None

        # python-kis response objects expose different attributes depending
        # on version; try common ones.
        for attr in ("order_no", "odno", "order_id"):
            val = getattr(response, attr, None)
            if val is not None:
                return str(val)

        # dict-style response
        if isinstance(response, dict):
            for key in ("order_no", "odno", "ODNO"):
                if key in response:
                    return str(response[key])

        return None

    @staticmethod
    def _parse_portfolio(raw: Any) -> list[PortfolioItem]:
        """Convert a KIS balance response into PortfolioItems."""
        items: list[PortfolioItem] = []

        # python-kis typically returns an iterable of holdings
        holdings = raw if hasattr(raw, "__iter__") else []

        for h in holdings:
            try:
                ticker = str(getattr(h, "ticker", getattr(h, "code", "")))
                name = str(getattr(h, "name", getattr(h, "prdt_name", ticker)))
                qty = int(getattr(h, "quantity", getattr(h, "hldg_qty", 0)))
                avg = float(getattr(h, "avg_price", getattr(h, "pchs_avg_pric", 0)))
                cur = float(
                    getattr(h, "current_price", getattr(h, "prpr", avg))
                )
                pnl = (cur - avg) * qty
                pnl_pct = ((cur - avg) / avg * 100) if avg else 0.0

                items.append(
                    PortfolioItem(
                        ticker=ticker,
                        name=name,
                        quantity=qty,
                        avg_price=avg,
                        current_price=cur,
                        pnl=pnl,
                        pnl_pct=round(pnl_pct, 2),
                    )
                )
            except Exception:
                logger.warning("Skipping unparseable holding: %s", h)

        return items

    @staticmethod
    def _parse_quote(ticker: str, raw: Any) -> PriceSnapshot:
        """Convert a KIS quote response into a PriceSnapshot."""
        price = float(getattr(raw, "price", getattr(raw, "stck_prpr", 0)))
        volume = int(getattr(raw, "volume", getattr(raw, "acml_vol", 0)))

        return PriceSnapshot(
            ticker=ticker,
            price=price,
            volume=volume,
            timestamp=datetime.now(),
        )

    @staticmethod
    def _parse_ohlcv(raw: Any) -> list[OHLCVBar]:
        """Convert a KIS OHLCV response into a list of OHLCVBars."""
        bars: list[OHLCVBar] = []

        rows = raw if hasattr(raw, "__iter__") else []

        for row in rows:
            try:
                # Attempt attribute access first, then dict-style
                def _get(name: str, default: Any = 0) -> Any:
                    val = getattr(row, name, None)
                    if val is not None:
                        return val
                    if isinstance(row, dict):
                        return row.get(name, default)
                    return default

                date_raw = _get("date", _get("stck_bsop_date", ""))
                if isinstance(date_raw, str) and len(date_raw) == 8:
                    dt = datetime.strptime(date_raw, "%Y%m%d")
                elif isinstance(date_raw, datetime):
                    dt = date_raw
                else:
                    dt = datetime.now()

                bars.append(
                    OHLCVBar(
                        date=dt,
                        open=float(_get("open", _get("stck_oprc", 0))),
                        high=float(_get("high", _get("stck_hgpr", 0))),
                        low=float(_get("low", _get("stck_lwpr", 0))),
                        close=float(_get("close", _get("stck_clpr", 0))),
                        volume=int(_get("volume", _get("acml_vol", 0))),
                    )
                )
            except Exception:
                logger.warning("Skipping unparseable OHLCV row: %s", row)

        return bars

    # -- repr --------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<BrokerAdapter connected={self._connected} "
            f"subscriptions={self._subscriptions.count}>"
        )
