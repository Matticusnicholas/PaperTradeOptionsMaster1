# Sentiment Options Lab

Real-time sentiment-driven options paper trading dashboard. Continuously ingests stock news via RSS, performs local deterministic sentiment analysis, and uses a two-stage funnel to identify trading candidates and paper-trade options contracts.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Stage 1 (Continuous)                                │
│  RSS → NewsIngestor → TickerResolver → Sentiment    │
│  → CoverageTracker → CandidateFunnel               │
├─────────────────────────────────────────────────────┤
│  Stage 2 (30-min ticks, market hours only)          │
│  Candidates → OptionsChain (yfinance) → Greeks      │
│  → OptionsEngine → RiskEngine → SimBroker           │
├─────────────────────────────────────────────────────┤
│  Monitor Loop (60s)                                  │
│  Mark-to-Market → Exit Checks (PT/SL/Time)          │
├─────────────────────────────────────────────────────┤
│  EventBus → SQLite + WebSocket → Dashboard          │
└─────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- npm or yarn

### 1. Install

```bash
# Clone and enter repo
cd PaperTradeOptionsMaster1

# Install everything
make install
```

Or manually:

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install

# Config
cd ..
cp .env.example .env
```

### 2. Run

**One command (both backend + frontend):**

```bash
make dev
```

**Or separately:**

```bash
# Terminal 1 - Backend
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 - Frontend
cd frontend
npm run dev
```

### 3. Open Dashboard

Navigate to [http://localhost:3000](http://localhost:3000)

Backend API docs at [http://localhost:8000/docs](http://localhost:8000/docs)

### 4. Run Tests

```bash
make test
```

## How It Works

### Stage 1: News Triage (runs every 3 minutes)

1. **NewsIngestor** polls RSS feeds, normalizes headlines, deduplicates
2. **TickerResolver** maps news to tickers using watchlist aliases
3. **SentimentEngine** scores each news item with deterministic finance-aware analysis:
   - Weighted lexicon + catalyst pattern matching
   - Negation window handling ("not strong", "no longer")
   - Hedging/uncertainty penalties ("may", "could", "reportedly")
   - Contradiction resolution ("beats earnings but lowers guidance")
   - Narrative tags (BEAT, MISS, GUIDANCE_UP, FDA_APPROVAL, etc.)
4. **CoverageTracker** computes per-ticker coverage intensity
5. **CandidateFunnel** ranks tickers that pass thresholds

### Stage 2: Options Trading (30-minute ticks, market hours)

1. **OptionsChainProvider** fetches chains via yfinance for candidates only
2. **GreeksCalculator** computes Black-Scholes Greeks locally
3. **OptionsEngine** scores contracts (delta alignment, theta, spread, IV, gamma)
4. **RiskEngine** plans orders with position sizing, profit targets, stop losses
5. **SimBroker** fills orders, tracks positions, enforces exits

### Market Rules

- New trade entries: 9:30 AM - 3:00 PM ET only
- Position management/exits: allowed until 4:00 PM ET
- Decision ticks: every 30 minutes on :00 and :30
- Weekend: fully paused

## Configuration

All settings in `.env` (see `.env.example`). Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `NEWS_POLL_SECONDS` | 180 | RSS poll interval |
| `DECISION_TICK_MINUTES` | 30 | Options evaluation cadence |
| `MIN_SENTIMENT_MAG` | 0.65 | Min abs(sentiment) for candidate |
| `MIN_CONFIDENCE` | 0.75 | Min confidence for candidate |
| `MAX_OPEN_POSITIONS` | 6 | Position limit |
| `PROFIT_TARGET_PCT` | 0.30 | +30% profit target |
| `STOP_LOSS_PCT` | 0.25 | -25% stop loss |
| `STARTING_CASH` | 100000 | Paper trading starting capital |

## Dashboard Pages

- **Dashboard** - Account overview, market clock, candidates, positions, events
- **Live Events** - Scrolling event feed with filters
- **News Monitor** - News list with sentiment breakdown detail panel
- **Candidate Funnel** - Ranked candidates with urgency scores
- **Options Decision** - Contract scoring tables with Greeks
- **Trades** - Open positions with P/L, closed trade history
- **Ticker View** - Per-ticker sentiment/coverage charts
- **System Health** - Pipeline status, market clock, configuration

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/news` | List news items |
| GET | `/api/news/{id}` | News detail + sentiment |
| GET | `/api/sentiment` | Sentiment scores |
| GET | `/api/coverage` | Coverage metrics |
| GET | `/api/candidates` | Candidate funnel |
| GET | `/api/options/contracts` | Option contracts |
| GET | `/api/orders` | Orders |
| GET | `/api/positions` | Positions |
| GET | `/api/trades` | Closed trades |
| GET | `/api/account` | Account state |
| GET | `/api/events` | Event history |
| GET | `/api/market-clock` | Market clock status |
| GET | `/api/ticker/{ticker}` | Ticker overview |
| GET | `/api/health` | System health |
| WS | `/ws/events` | Live event stream |

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes.py          # REST + WebSocket endpoints
│   │   ├── models/
│   │   │   ├── base.py            # SQLAlchemy base
│   │   │   └── tables.py          # All DB models
│   │   ├── modules/
│   │   │   ├── news_ingestor.py   # RSS polling + dedup
│   │   │   ├── ticker_resolver.py # Watchlist entity matching
│   │   │   ├── sentiment_engine.py# Deterministic sentiment + catalysts
│   │   │   ├── coverage_tracker.py# Coverage intensity metrics
│   │   │   ├── candidate_funnel.py# Stage 1 ranking + gating
│   │   │   ├── market_data.py     # yfinance price provider
│   │   │   ├── options_chain.py   # yfinance options chain fetcher
│   │   │   ├── greeks.py          # Black-Scholes Greeks
│   │   │   ├── options_engine.py  # Contract scoring + selection
│   │   │   ├── risk_engine.py     # Position sizing + order planning
│   │   │   ├── sim_broker.py      # Paper trading broker
│   │   │   ├── market_clock.py    # ET market hours enforcement
│   │   │   ├── event_bus.py       # Event persistence + WS broadcast
│   │   │   └── orchestrator.py    # Main loop coordinator
│   │   ├── migrations/            # Alembic
│   │   ├── config.py              # Centralized config from .env
│   │   ├── database.py            # SQLAlchemy engine
│   │   ├── init_db.py             # Table creation
│   │   └── main.py                # FastAPI app entry point
│   ├── tests/
│   │   ├── test_sentiment.py      # Sentiment negation/hedging/contradiction
│   │   ├── test_greeks.py         # Black-Scholes validation
│   │   ├── test_options_engine.py # Contract scoring
│   │   └── test_market_clock.py   # Market clock + exits
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── app/                   # Next.js pages
│   │   ├── components/            # Shared components
│   │   └── lib/                   # API client + hooks
│   └── package.json
├── .env.example
├── Makefile
└── README.md
```
