import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.config import settings
from app.models.database import init_db, SessionLocal, Signal as SignalModel, Trade as TradeModel, Position as PositionModel
from app.services.broker_adapter import BrokerAdapter
from app.services.strategy import StrategyEngine
from app.services.orders import OrderManager
from app.ws.hub import hub as ws_hub
from app.tasks.background import BackgroundTaskManager, is_market_open

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Global instances
broker: BrokerAdapter | None = None
strategy_engine: StrategyEngine | None = None
order_manager: OrderManager | None = None
task_manager: BackgroundTaskManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global broker, strategy_engine, order_manager, task_manager

    logger.info("Starting trading dashboard...")

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Initialize broker adapter
    broker = BrokerAdapter()
    try:
        broker.connect()
        logger.info("Broker connected")
    except Exception as e:
        logger.warning(f"Broker connection failed (running in offline mode): {e}")

    # Initialize strategy engine
    strategy_engine = StrategyEngine()
    strategy_engine.load_strategies()
    logger.info(f"Loaded {len(strategy_engine.get_loaded())} strategies")

    # Initialize order manager
    order_manager = OrderManager(broker, settings)
    logger.info(f"Order manager ready (mode: {order_manager.get_mode()})")

    # Start background tasks
    task_manager = BackgroundTaskManager()
    await task_manager.start(broker, strategy_engine, order_manager, ws_hub)
    logger.info("Background tasks started")

    yield

    # Shutdown
    logger.info("Shutting down...")
    if task_manager:
        await task_manager.stop()
    if broker:
        broker.disconnect()
    logger.info("Shutdown complete")


app = FastAPI(title="Stock Auto-Trading Dashboard", lifespan=lifespan)


# ---------- REST API ----------

class ModeRequest(BaseModel):
    mode: str


@app.get("/api/status")
async def get_status():
    return {
        "marketOpen": is_market_open(),
        "mode": order_manager.get_mode() if order_manager else "manual",
        "apiConnected": broker.is_connected if broker else False,
        "halted": order_manager._halted if order_manager else False,
    }


@app.get("/api/portfolio")
async def get_portfolio():
    db = SessionLocal()
    try:
        positions = db.query(PositionModel).all()
        return [
            {
                "ticker": p.ticker,
                "quantity": p.quantity,
                "avgPrice": p.avg_price,
                "currentPrice": p.current_price or 0,
                "pnl": (p.current_price - p.avg_price) * p.quantity if p.current_price else 0,
                "pnlPercent": ((p.current_price - p.avg_price) / p.avg_price * 100) if p.current_price and p.avg_price else 0,
                "updatedAt": str(p.updated_at) if p.updated_at else "",
            }
            for p in positions
        ]
    finally:
        db.close()


@app.get("/api/signals")
async def get_signals():
    db = SessionLocal()
    try:
        signals = db.query(SignalModel).order_by(SignalModel.created_at.desc()).limit(100).all()
        return [
            {
                "id": s.id,
                "ticker": s.ticker,
                "action": s.action,
                "confidence": s.confidence,
                "reason": s.reason,
                "strategyName": s.strategy_name,
                "actedOn": s.acted_on,
                "createdAt": str(s.created_at),
            }
            for s in signals
        ]
    finally:
        db.close()


@app.get("/api/trades")
async def get_trades():
    db = SessionLocal()
    try:
        trades = db.query(TradeModel).order_by(TradeModel.created_at.desc()).limit(200).all()
        return [
            {
                "id": t.id,
                "ticker": t.ticker,
                "action": t.action,
                "quantity": t.quantity,
                "price": t.price,
                "brokerOrderId": t.broker_order_id,
                "strategyName": t.strategy_name,
                "signalConfidence": t.signal_confidence,
                "status": t.status,
                "createdAt": str(t.created_at),
            }
            for t in trades
        ]
    finally:
        db.close()


@app.get("/api/chart/{ticker}")
async def get_chart_data(ticker: str):
    if not broker:
        return []
    try:
        ohlcv = broker.get_ohlcv(ticker, period="D")
        return [
            {"time": bar.date.strftime("%Y-%m-%d"), "open": bar.open, "high": bar.high,
             "low": bar.low, "close": bar.close, "volume": bar.volume}
            for bar in ohlcv
        ]
    except Exception as e:
        logger.error(f"Failed to get chart data for {ticker}: {e}")
        return []


@app.post("/api/mode")
async def set_mode(req: ModeRequest):
    if not order_manager:
        raise HTTPException(status_code=503, detail="Order manager not ready")
    if req.mode not in ("auto", "manual"):
        raise HTTPException(status_code=400, detail="Mode must be 'auto' or 'manual'")
    order_manager.set_mode(req.mode)
    await ws_hub.broadcast_status({"mode": req.mode})
    return {"mode": req.mode}


@app.post("/api/emergency-stop")
async def emergency_stop():
    if not order_manager:
        raise HTTPException(status_code=503, detail="Order manager not ready")
    order_manager.emergency_stop()
    await ws_hub.broadcast_status({"halted": True})
    return {"status": "halted"}


@app.post("/api/signals/{signal_id}/execute")
async def execute_signal(signal_id: int):
    if not order_manager:
        raise HTTPException(status_code=503, detail="Order manager not ready")
    db = SessionLocal()
    try:
        sig = db.query(SignalModel).filter(SignalModel.id == signal_id).first()
        if not sig:
            raise HTTPException(status_code=404, detail="Signal not found")
        if sig.acted_on != 0:
            raise HTTPException(status_code=400, detail="Signal already acted on")

        # Get current price for the order
        current_price = 0.0
        if broker:
            snapshot = broker.get_current_price(sig.ticker)
            if snapshot:
                current_price = snapshot.price

        result = order_manager.execute_signal({
            "ticker": sig.ticker,
            "action": sig.action,
            "quantity": 1,  # Default quantity; real logic should compute from risk controls
            "price": current_price,
            "signal_confidence": sig.confidence,
            "reason": sig.reason,
            "strategy_name": sig.strategy_name,
        })
        sig.acted_on = 1
        db.commit()
        return result
    finally:
        db.close()


@app.post("/api/signals/{signal_id}/ignore")
async def ignore_signal(signal_id: int):
    db = SessionLocal()
    try:
        sig = db.query(SignalModel).filter(SignalModel.id == signal_id).first()
        if not sig:
            raise HTTPException(status_code=404, detail="Signal not found")
        sig.acted_on = 2
        db.commit()
        return {"status": "ignored"}
    finally:
        db.close()


@app.get("/api/strategies")
async def get_strategies():
    if not strategy_engine:
        return []
    return strategy_engine.get_loaded()


# ---------- WebSocket ----------

@app.websocket("/ws/dashboard")
async def websocket_endpoint(websocket: WebSocket):
    await ws_hub.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # Handle client messages (e.g., signal actions)
            if data.get("type") == "signal_action":
                signal_id = data.get("signalId")
                action = data.get("action")
                if action == "execute":
                    await execute_signal(signal_id)
                elif action == "ignore":
                    await ignore_signal(signal_id)
    except WebSocketDisconnect:
        ws_hub.disconnect(websocket)


# ---------- Static files (serve frontend build) ----------

static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
else:
    @app.get("/")
    async def root():
        return JSONResponse({
            "message": "Trading Dashboard API",
            "note": "Frontend not built. Run 'cd frontend && npm run build' to generate static files.",
        })
