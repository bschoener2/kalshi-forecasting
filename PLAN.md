# Kalshi Trading System — Implementation Plan

## Overview

Buy and sell Kalshi prediction market contracts based on time series forecasts.
Daily decision at noon PST: buy/sell/hold, with human approval gate before execution.

---

## Phase 1: Data Infrastructure

### 1a. Kalshi API Client
- Python wrapper around the Kalshi REST API (v2)
- Authentication: API key ID + RSA private key (env vars)
- Methods: list markets, get market price history, get current positions/balance
- Rate limiting and retry logic

### 1b. Database Schema (PostgreSQL + SQLAlchemy + Alembic)

| Table | Key columns |
|---|---|
| `markets` | ticker, title, category, close_date, created_at |
| `market_prices` | ticker, timestamp, yes_bid, yes_ask, volume |
| `positions` | ticker, quantity, avg_cost, opened_at |
| `orders` | id, ticker, side, quantity, price, status (PENDING/APPROVED/EXECUTED/REJECTED), timestamps, pnl |
| `daily_decisions` | date, ticker, model, forecast, recommended_action, confidence, status |

### 1c. Historical Data Ingestion
- Backfill script: fetch all markets with 1+ year of price history
- Scheduled nightly incremental sync

---

## Phase 2: Market Selection

- Pull all active and recently-closed markets from Kalshi
- Filter: markets with daily data going back 365+ days
- Compute: avg daily volume, price volatility, bid/ask spread
- Output: ranked list of candidate markets for modeling

---

## Phase 3: Forecasting Models

### Models (tuned per market)
- Naive baseline (yesterday's noon price)
- ARIMA / SARIMA (statsmodels)
- Exponential smoothing (ETS)
- XGBoost with lag features
- Simple LSTM (PyTorch)

### Evaluation Framework
- Walk-forward cross-validation (strict temporal splits, no data leakage)
- Train on past → predict next-day noon price
- Metrics: MAE, RMSE, directional accuracy, calibration
- Expected value: `EV = P(correct) × profit_if_correct - P(wrong) × loss_if_wrong - transaction_cost`
- Multiple-testing correction (Bonferroni or BH FDR) across all model×market combos

### Output
- Ranked leaderboard of (model, market) pairs by Sharpe-adjusted EV
- Small set of high-confidence combos selected for live trading

---

## Phase 4: Execution System

### Daily Noon Runner (APScheduler)
1. Fetch current prices for selected markets
2. Run forecast models → buy/sell/hold recommendation + confidence
3. Compute position sizes (Kelly fraction heuristic)
4. Write proposed orders to DB with status `PENDING_APPROVAL`
5. Trigger dashboard alert for human review

### Human Approval Gate
- Web UI shows pending decisions with forecast details
- Human clicks Approve or Reject per trade
- On approval: call Kalshi order API, log execution to DB and CSV

### Budget Management
- Hard cap: never invest more than `BUDGET_DOLLARS`
- Position sizing: fractional Kelly (0.25× multiplier) scaled by confidence
- Max per trade: 20% of current budget
- Goal: maximize long-term returns while avoiding ruin

### Logging
- All orders appended to `orders.csv`
- All orders inserted into `orders` DB table with full audit trail

---

## Phase 5: Web UI

**Stack:** FastAPI + HTMX + Jinja2 (no JS build step)

| Route | Purpose |
|---|---|
| `/` | Dashboard: open positions, today's P&L, total performance chart |
| `/decisions` | Pending noon decisions: forecast, recommended trade, Approve/Reject |
| `/history` | All past orders with outcomes and P&L |
| `/models` | Model leaderboard: accuracy and EV per market |
| `/settings` | Budget, risk limits, active markets/models |

---

## Build Order

1. Kalshi API client + auth
2. DB schema + Alembic migrations
3. Historical data ingestion
4. Market selection filter
5. Forecasting models + evaluation framework
6. FastAPI backend skeleton + HTMX UI shell
7. Noon execution runner + approval gate
8. Position sizing + budget management
9. Polish: alerts, logging, metrics dashboard

---

## Key Risks

- **Kalshi API data gaps** — some markets may not have full price history; need fallback handling
- **Overfitting** — strict temporal splits and multiple-testing corrections are mandatory
- **Transaction costs** — Kalshi charges ~7% of winnings; every model must clear this EV bar
- **Execution timing** — orders must be submitted before noon price moves; runner needs a time buffer
