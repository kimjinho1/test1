# Implementation Plan: Personal Korean Stock Auto-Trading Dashboard

## Context

A code-literate trader wants to replace fragmented Python scripts + Korean brokerage HTS tools with a unified web dashboard for automated Korean stock trading. The design doc was produced by /office-hours and reviewed through a full /plan-eng-review cycle. This plan incorporates all review decisions including scope reductions and outside voice findings.

**Scope decisions from eng review:**
- Remove existing unrelated code (Trump Nonsense Predictor)
- Use `python-kis` library instead of building custom KIS API wrapper
- Switch from Next.js to Vite React SPA (single runtime, served by FastAPI)
- Replace APScheduler with native asyncio tasks
- Add in-memory shadow ledger for accurate risk controls
- Add WebSocket subscription manager to prevent GC-based silent unsubs
- Add staleness indicator in frontend
- Configurable strategy evaluation intervals
- Full test coverage (35 paths, 8 E2E)

## Architecture

```
┌──────────────────────────────────────────────────┐
│  Vite React SPA (served as static files)         │
│  ┌──────────────┐ ┌───────────┐ ┌─────────────┐ │
│  │ TradingView   │ │ Portfolio │ │ Signals +   │ │
│  │ Charts        │ │ Panel     │ │ Trade Log   │ │
│  └──────┬───────┘ └─────┬─────┘ └──────┬──────┘ │
│         │   WebSocket    │              │        │
└─────────┼────────────────┼──────────────┼────────┘
          │                │              │
┌─────────┼────────────────┼──────────────┼────────┐
│  FastAPI (single Python process)                  │
│                                                   │
│  ┌─────────────────┐  ┌──────────────────────┐   │
│  │ Strategy Engine  │  │ Order Manager        │   │
│  │ (importlib +     │→ │ + Shadow Ledger      │   │
│  │  asyncio tasks)  │  │ + Risk Controls      │   │
│  └────────┬────────┘  └──────────┬───────────┘   │
│           │                      │                │
│  ┌────────┴──────────────────────┴───────────┐   │
│  │ Broker Adapter (thin layer over python-kis)│   │
│  │ + SubscriptionManager (ticket lifecycle)   │   │
│  └────────────────────┬──────────────────────┘   │
│                       │                          │
│  ┌────────────────────┴──────────────────────┐   │
│  │ SQLite (WAL) — trades, signals, positions │   │
│  └───────────────────────────────────────────┘   │
│                                                   │
│  ┌───────────────────────────────────────────┐   │
│  │ WebSocket Hub → broadcast to browser      │   │
│  └───────────────────────────────────────────┘   │
│                                                   │
│  ┌───────────────────────────────────────────┐   │
│  │ asyncio background tasks:                 │   │
│  │  - portfolio poller (30s)                 │   │
│  │  - strategy runners (per-strategy interval)│   │
│  │  - token refresh (pre-market)             │   │
│  │  - market-hours guard                     │   │
│  └───────────────────────────────────────────┘   │
└───────────────────────────────────────────────────┘
          │
    python-kis → 한국투자증권 Open API (REST + WebSocket)
```

## Tech Stack (revised)

| Layer | Technology | Why |
|-------|-----------|-----|
| Backend | FastAPI (Python 3.11+) | Async, WebSocket native, serves frontend too |
| Frontend | React + Vite | Static SPA, no SSR needed, one runtime |
| Charts | TradingView Lightweight Charts | Free, fast, professional candlesticks |
| Database | SQLite + SQLAlchemy (WAL mode) | Zero config, single user |
| Broker API | python-kis (PyPI) | Handles auth, tokens, REST, WebSocket |
| Scheduling | asyncio tasks + sleep loops | Native, zero-dependency, simpler than APScheduler |
| Testing | pytest (backend) + Vitest (frontend) | Standard for each stack |

## File Structure

```
app/
├── main.py                 # FastAPI app, startup/shutdown, static file serving
├── config.py               # Settings (from .env), market hours, risk defaults
├── services/
│   ├── broker_adapter.py   # Thin layer over python-kis + SubscriptionManager
│   ├── strategy.py         # Strategy Engine (importlib + asyncio runner)
│   └── orders.py           # Order Manager + Shadow Ledger + Risk Controls
├── ws/
│   └── hub.py              # WebSocket Hub (connection manager + broadcast)
├── models/
│   └── database.py         # SQLAlchemy models + SQLite setup (WAL)
├── tasks/
│   └── background.py       # asyncio background tasks (polling, scheduling)
└── strategies/             # User strategy scripts go here
    └── example_momentum.py # Example strategy with run(context) -> Signal

frontend/
├── src/
│   ├── App.tsx             # Main dashboard layout (4 panels)
│   ├── components/
│   │   ├── Chart.tsx       # TradingView chart wrapper
│   │   ├── Portfolio.tsx   # Holdings + P&L panel
│   │   ├── Signals.tsx     # Strategy signals + execute/ignore
│   │   ├── TradeLog.tsx    # Chronological trade history
│   │   └── Header.tsx      # Market status, auto/manual toggle, API status
│   ├── hooks/
│   │   └── useWebSocket.ts # WebSocket connection + staleness detection
│   └── types.ts            # Shared TypeScript types
├── vite.config.ts
└── package.json

tests/
├── test_broker_adapter.py  # 8 test paths
├── test_strategy.py        # 8 test paths
├── test_orders.py          # 10 test paths (most critical)
├── test_ws_hub.py          # 4 test paths
└── test_e2e/               # 8 E2E test scenarios
    ├── test_startup.py
    ├── test_order_lifecycle.py
    └── test_emergency_stop.py

requirements.txt            # python-kis, fastapi, uvicorn, sqlalchemy, pytest
.env.example                # KIS API credentials template
docker-compose.yml          # Single service (FastAPI serves everything)
Dockerfile                  # Python + Node (for Vite build) → static files
```

## Implementation Steps

### Step 1: Project scaffolding + cleanup
- Remove existing app.py, requirements.txt, templates/
- Create directory structure above
- Set up requirements.txt with python-kis, fastapi, uvicorn, sqlalchemy
- Set up frontend/ with Vite + React + TypeScript
- Create .env.example with KIS credential placeholders
- Create config.py with pydantic Settings

### Step 2: Broker adapter + subscription manager
- `broker_adapter.py`: Initialize PyKis client, expose subscribe/unsubscribe/order/portfolio methods
- `SubscriptionManager`: Dict-based ticket storage keyed by ticker, prevents GC-based silent unsub
- Unit tests: 8 paths (init, subscribe, duplicate subscribe, max subs, order, portfolio, errors)

### Step 3: Strategy engine
- `strategy.py`: Load scripts via importlib, validate `run(context) -> Signal` interface
- Configurable evaluation interval per strategy (default 1m)
- Run in asyncio executor (ThreadPoolExecutor, bounded)
- Per-strategy error isolation (try/except + log + auto-disable after 3 consecutive failures)
- Unit tests: 8 paths (load, missing module, missing run(), invalid signal, timeout, exception)

### Step 4: Order manager + shadow ledger
- `orders.py`: Risk validation (position size, stop-loss, daily loss limit)
- In-memory shadow ledger: tracks pending/executed orders, adjusts risk checks
- Shadow reconciled against REST portfolio on each poll
- Auto/manual mode: auto → execute immediately, manual → push to frontend
- Emergency stop: cancel pending orders, set HALTED, broadcast
- Unit tests: 10 paths (within limits, exceed position, exceed daily loss, stop-loss, auto/manual, emergency stop, shadow ledger accuracy)

### Step 5: WebSocket hub + background tasks
- `hub.py`: Connection manager, broadcast to all connected clients, handle disconnects
- `background.py`: asyncio tasks for portfolio polling (30s), strategy scheduling, market-hours guard
- Unit tests: 4 paths (connect, disconnect, broadcast, client drop mid-broadcast)

### Step 6: Dashboard UI
- 4-panel layout: Chart, Portfolio, Signals, TradeLog
- TradingView Lightweight Charts for candlestick rendering
- WebSocket hook with staleness detection (10s timeout → stale badge)
- Execute/Ignore buttons on signals
- Emergency stop button in footer
- Auto/manual toggle in header
- Market status indicator (OPEN/CLOSED)

### Step 7: Integration + E2E tests
- Wire all components together in main.py
- FastAPI serves Vite build output as static files
- 8 E2E tests covering startup, order lifecycle, emergency stop
- Docker Compose file for single-service deployment

## Database Schema

```sql
CREATE TABLE trades (
  id INTEGER PRIMARY KEY,
  ticker TEXT NOT NULL,
  action TEXT NOT NULL,  -- BUY, SELL
  quantity INTEGER NOT NULL,
  price REAL NOT NULL,
  broker_order_id TEXT,
  strategy_name TEXT,
  signal_confidence REAL,
  status TEXT DEFAULT 'PENDING',  -- PENDING, FILLED, PARTIAL, CANCELLED, ERROR
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE signals (
  id INTEGER PRIMARY KEY,
  ticker TEXT NOT NULL,
  action TEXT NOT NULL,  -- BUY, SELL, HOLD
  confidence REAL,
  reason TEXT,
  strategy_name TEXT,
  acted_on INTEGER DEFAULT 0,  -- 0=pending, 1=executed, 2=ignored
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE positions (
  ticker TEXT PRIMARY KEY,
  quantity INTEGER NOT NULL,
  avg_price REAL NOT NULL,
  current_price REAL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## NOT in Scope (V1)
- **Backtesting** — deferred to V2. Separate subsystem (historical data pipeline, simulation engine).
- **Strategy sandboxing** — tracked in TODOS.md. Only matters if loading untrusted strategies.
- **Subscription multiplexing** — tracked in TODOS.md. Only matters with >40 tickers.
- **Multi-market support** (US stocks, crypto) — V2+.
- **Mobile responsive UI** — personal desktop tool, not needed.
- **CI/CD pipeline** — manual deploy via Docker Compose for personal use.
- **Authentication** — localhost only.

## What Already Exists
- **python-kis**: Handles KIS auth, token refresh, REST, WebSocket, orders. Eliminates custom broker wrapper.
- **TradingView Lightweight Charts**: Free charting library, handles candlestick rendering.

## Failure Modes

| Component | Failure | Test? | Error handling? | User sees? |
|-----------|---------|-------|-----------------|------------|
| Broker adapter | KIS auth failure | YES | Retry 3x, abort startup | Error screen: "API 연결 실패" |
| Broker adapter | WS disconnect | YES | python-kis auto-reconnect | Staleness badge (10s) |
| Strategy engine | Script throws exception | YES | try/except, auto-disable after 3 fails | Signal: "전략 오류" in trade log |
| Strategy engine | Script blocks >30s | YES | ThreadPool timeout | Strategy marked as timed out |
| Order manager | API error on order | YES | Retry once, then halt + alert | "주문 실패" in trade log |
| Order manager | Partial fill | YES | Log, track, no re-order | Partial fill shown in trade log |
| Order manager | Risk limit exceeded | YES | Reject signal, log | "위험 한도 초과" badge on signal |
| WebSocket hub | Client disconnects | YES | Remove from connection set | N/A (client gone) |
| SQLite | Write contention | NO | WAL mode, serialized writes | Possible brief delay |

## Worktree Parallelization Strategy

| Step | Modules touched | Depends on |
|------|----------------|------------|
| Step 1: Scaffolding | all (project structure) | — |
| Step 2: Broker adapter | app/services/ | Step 1 |
| Step 3: Strategy engine | app/services/ | Step 1 |
| Step 4: Order manager | app/services/ | Step 1 |
| Step 5: WS hub + tasks | app/ws/, app/tasks/ | Step 1 |
| Step 6: Dashboard UI | frontend/ | Step 1 |
| Step 7: Integration | app/main.py, tests/ | Steps 2-6 |

**Parallel lanes:**
- Lane A: Step 2 (broker adapter) → Step 4 (order manager) — sequential, shared services/
- Lane B: Step 3 (strategy engine) — independent (only reads from broker adapter interface)
- Lane C: Step 6 (dashboard UI) — independent (frontend/, different runtime)
- Lane D: Step 5 (WS hub) — independent (app/ws/, app/tasks/)

**Execution order:**
1. Step 1 (scaffolding) — sequential, first
2. Launch Lanes A + B + C + D in parallel worktrees
3. Step 7 (integration) — sequential, after all lanes merge

## Verification

1. **Backend unit tests:** `pytest tests/ -v` — all 30 unit test paths pass
2. **Frontend:** `cd frontend && npm run build` — Vite builds static bundle without errors
3. **Integration:** `uvicorn app.main:app` — dashboard loads at localhost:8000
4. **Manual smoke test:** Open dashboard → verify portfolio loads → verify chart shows prices → trigger a test signal → verify it appears in signals panel
5. **E2E tests:** `pytest tests/test_e2e/ -v` — all 8 E2E scenarios pass (requires KIS paper trading credentials)
6. **Docker:** `docker compose up` — single container serves everything

## V2 TODO

- [ ] **Strategy sandboxing** — Add restricted execution for untrusted strategy scripts
- [ ] **Subscription multiplexing** — Deduplicate WebSocket subscriptions across strategies + dashboard
- [ ] **Strategy isolation hardening** — Per-strategy try/except + auto-disable after N consecutive failures
- [ ] **Backtesting** — Run strategies against historical data in the same dashboard
- [ ] **Multi-market** — Support US stocks + crypto alongside KRX

## Review Status

| Review | Status | Findings |
|--------|--------|----------|
| Eng Review | CLEARED | 7 issues, 0 critical gaps |
| Outside Voice | issues_found (claude) | 8 findings, 3 incorporated |
| **VERDICT** | **Ready to implement** | |
