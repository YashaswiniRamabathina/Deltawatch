# Smart Market Watchlist

*Built for Groww CODE 2026.*

## The idea, in one sentence

A watchlist shouldn't tell you a stock's price — you can get that from a hundred apps. It should tell you **what's different since you personally last looked**, and explain *why* that's worth your attention.

Most watchlist clones show a live-updating table. That's a solved problem and a low-value one — you already know prices move every day. The actual product problem is **attention triage**: out of everything on your list, what deserves 10 seconds of your time right now? This app answers that with a scoring engine that's personal (per-user "since you left" diffing, not a global "today's movers" list) and explainable (every score traces to plain-English reasons, never a bare number).

---

## What counts as a "meaningful" change

Not `abs(% change) > 5%`. A flat threshold treats a sleepy utility stock and a volatile small-cap identically, and can't distinguish routine drift from a structural event. The engine ([`app/services/scoring.py`](backend/app/services/scoring.py)) combines four independent signals, each contributing an explainable point value:

| Signal | Why it matters |
|---|---|
| **Volatility-normalized move** | A 2% move is huge for a utility stock and noise for a small-cap. We z-score today's move against *that stock's own* trailing 20-day volatility, not a fixed percentage. |
| **Volume anomaly** | A price move on 3x normal volume signals real conviction; the same move on thin volume is noise. |
| **52-week high/low breach** | A structural level, independent of today's percentage move — often the actual reason a move gets talked about. |
| **Opening gap** | Did the move happen instantly at the open (news-driven) or drift intraday? Different story either way. |

Scores **stack** (not average) — a stock that gapped down 3%, on 3x volume, at a new 52-week low is far more notable than any one signal alone, and the UI shows exactly which signals fired.

On top of this **global** score sits a **personal** layer (`score_personal_delta`): even a stock that never had one big single-day move can matter to a user who hasn't checked in two weeks, because moves compound. This is what makes the "Since you left" feed genuinely personal — two users watching the same stock can see different framings depending on when *they* each last looked.

**Cold start honesty**: a newly-added symbol has no volatility/volume history yet. Rather than pretend precision it doesn't have, the engine explicitly falls back to a flat 3% threshold until enough snapshots accumulate (`app/services/stats.py`) — a deliberate simple-over-clever choice; a proper historical backfill is a natural next step, not core to proving the idea.

---

## Architecture

```
┌─────────────┐        ┌───────────────────────────────────────┐
│   React UI  │◄──────►│              FastAPI                   │
│  (Vite)     │  REST  │  /auth  /watchlist  /digest             │
└─────────────┘        └───────────────┬─────────────────────────┘
                                        │ reads only
                                        ▼
                              ┌───────────────────┐
                              │   SymbolState      │  ← the cache: API never
                              │  (Postgres/SQLite) │    talks to the market
                              └────────▲───────────┘    data provider directly
                                       │ writes
                              ┌────────┴───────────┐
                              │  Background Poller  │  tiered polling:
                              │  (thread / worker)  │  hot/warm/cold by
                              └────────┬───────────┘  watcher count
                                       │
                         ┌─────────────┴──────────────┐
                         ▼                             ▼
                  ┌─────────────┐              ┌──────────────┐
                  │   Yahoo      │              │   Stooq       │
                  │  (primary)   │              │  (fallback)   │
                  └─────────────┘              └──────────────┘
```

- **Backend**: FastAPI + SQLAlchemy. SQLite by default (zero setup); point `DATABASE_URL` at Postgres for production — the ORM layer doesn't change.
- **Data providers**: two independent, keyless sources (Yahoo Finance's public chart endpoint, Stooq's CSV endpoint) behind a common `QuoteProvider` interface (`app/services/data_providers/`), so adding a paid provider later is a new class, not a rewrite.
- **Background poller**: refreshes `SymbolState` on a schedule. Every API read hits this table, never the upstream provider — this is *the* thing that makes reads cheap regardless of how many users are watching.
- **Frontend**: React (Vite), no framework beyond that — this app's complexity is in the scoring logic, not the UI, so the UI stays plain.

---

## How state persists across sessions/devices

Accounts are real (email + password, JWT auth) — not localStorage-only. `WatchlistItem` rows are keyed by `user_id`, so logging in from a different device gives the same list. Each `WatchlistItem` also carries a personal `last_seen_at` / `last_seen_price` pointer, which is *why* the digest is personal rather than global: it's the diff base for that specific user on that specific symbol, updated via `POST /watchlist/{symbol}/seen` when they acknowledge a change.

---

## Handling stale, delayed, and conflicting data

This was treated as a first-class requirement, not an afterthought:

- **Two independent sources**, queried on every poll. If they disagree by more than 1.5%, the reading is flagged `flagged_conflict` rather than silently averaged or silently trusted — see `QuoteAggregator.fetch` in [`aggregator.py`](backend/app/services/data_providers/aggregator.py).
- **Failover**: if the primary (Yahoo) fails, the aggregator falls back to Stooq automatically. If *both* fail, the poller marks `SymbolState.is_stale = True` rather than serving the last good value as if it were live.
- **Staleness is explicit, not implicit**: every quote carries `updated_at` and `is_stale`, both returned to the frontend, which shows a "delayed" tag rather than presenting old data as current.
- **A single provider failure never takes down a poll cycle** — each symbol is wrapped in its own try/except in the poller loop.

---

## Scaling

- **Cost scales with distinct symbols, not distinct users.** 500 users watching AAPL is one poll target because the poller queries `WatchlistItem` grouped by symbol, not per-user.
- **Tiered polling**: symbols with ≥5 watchers poll every 15s ("hot"), ≥1 watcher every 60s ("warm"), otherwise every 5 minutes ("cold") — configurable via env vars. Popular symbols stay fresh; unpopular ones don't waste provider quota.
- **Reads are decoupled from fetches**: the API is a thin read layer over `SymbolState`; it can scale horizontally with zero coordination since it never calls the upstream provider itself.
- **The poller is a single logical process** by design (avoids duplicate/racing fetches). For a single-instance deployment it runs as a background thread inside the API process (`ENABLE_INPROCESS_POLLER=true`, the default — zero extra setup). For a horizontally-scaled deployment, set that to `false` and run `python -m app.worker` as its own singleton process/container instead, so N API replicas don't each poll redundantly.
- **In-memory cache, not Redis, by default** — see "where we kept it simple" below.

---

## Where we kept things simple (and why)

Being honest about trade-offs, since the brief asks for it explicitly:

- **No Redis.** A `Cache` class (`app/services/cache.py`) exists as a narrow interface (get/set/lock) specifically so a Redis-backed implementation is a drop-in swap later — but for a single-process demo, an in-memory dict has one less moving part to install and explain. This is the single biggest "add complexity later, not now" call in the codebase.
- **Polling, not WebSocket streaming from the exchange.** True tick-by-tick streaming is the "obvious" scaling answer but is over-engineering for what this app needs: users check a watchlist periodically, not tick-by-tick. Tiered polling gets 90% of the freshness at a fraction of the infrastructure. The provider interface doesn't preclude adding a streaming source later.
- **SQLite by default.** Runs with zero setup; the ORM makes Postgres a one-line config change (`DATABASE_URL`) with no code changes.
- **No historical backfill job.** New symbols start with a flat-threshold fallback until enough polls accumulate rather than fetching a year of history up front (slow, and easy to rate-limit against on free APIs).

Where we *did* spend complexity: the scoring engine and the conflict/staleness handling, because those are the actual product differentiators the brief is asking for ("don't build the obvious watchlist").

---

## Honesty about testing

This was built and reasoned about, then verified as much as the environment allowed:

- **24 unit tests pass** covering the scoring engine (edge cases: missing data, volatile vs. calm stocks, stacking signals, personal-delta logic) and the provider parsing/aggregator logic (conflict flagging, fallback, staleness) — run `pytest` in `backend/`.
- **A full HTTP smoke test** (register → add symbol → list → digest → mark-seen → digest-clears → delete → duplicate-blocked → unauthenticated-blocked) passes against a real FastAPI `TestClient`, using a mocked data provider.
- **What wasn't verified live**: the sandbox this was built in has network egress locked to package registries, so the real calls to Yahoo Finance / Stooq were never exercised against the live internet from here. The parsing logic (`YahooProvider._parse`, `StooqProvider._parse`) is tested against realistic fixture payloads shaped like the real API responses, but if either endpoint's shape has drifted, you may need to adjust the parsing on first real run. Run it locally and it will tell you immediately — provider failures raise a clear, typed `QuoteProviderError` rather than failing silently.

---

## Running it locally

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Runs on `http://localhost:8000` with a local SQLite file (`watchlist.db`) and the poller running in-process. Swagger docs at `/docs`.

Run tests:
```bash
pytest
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env    # points at http://localhost:8000 by default
npm run dev
```

Runs on `http://localhost:5173`.

### Try it

1. Open the frontend, create an account.
2. Add a few real US tickers (e.g. `AAPL`, `TSLA`, `MSFT`).
3. Wait ~15–30s (poller cycle) and refresh — prices populate, and any symbol that crosses the meaningful-change bar appears in "Since you left."
4. Click "Mark as seen" on an entry — it drops out of the digest and the personal `last_seen` pointer advances, so future visits diff from now.

### Scaling to multiple API instances

```bash
# run the poller as its own process:
ENABLE_INPROCESS_POLLER=false python -m app.worker
# and scale the API separately:
ENABLE_INPROCESS_POLLER=false uvicorn app.main:app --workers 4
```

---

## API summary

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create account, returns JWT |
| POST | `/auth/login` | Login (OAuth2 form), returns JWT |
| GET | `/auth/me` | Current user |
| GET | `/watchlist` | List watched symbols with live quotes + personalized delta |
| POST | `/watchlist` | Add a symbol (validates + warms cache synchronously) |
| DELETE | `/watchlist/{symbol}` | Remove a symbol |
| POST | `/watchlist/{symbol}/seen` | Acknowledge — advances the personal "last checked" pointer |
| GET | `/digest` | Ranked "what changed since you left" feed |

Full interactive docs at `/docs` once running.

---

## Project layout

```
backend/
  app/
    main.py                  FastAPI app + lifespan (starts poller)
    worker.py                standalone poller process for scaled deployments
    config.py                all tunables, env-driven
    models.py / schemas.py   SQLAlchemy ORM / Pydantic
    auth.py                  JWT + password hashing
    routers/                 auth, watchlist, digest endpoints
    services/
      scoring.py             the meaningful-change engine (core logic)
      stats.py                rolling volatility/volume/52w baselines
      poller.py               background refresh loop, tiered by popularity
      cache.py                in-memory TTL cache (Redis-swappable interface)
      data_providers/
        base.py               provider interface
        yahoo.py / stooq.py   two independent keyless sources
        aggregator.py         conflict/fallback/staleness reconciliation
    tests/                    24 unit tests
frontend/
  src/
    api/client.js             typed fetch wrapper
    context/AuthContext.jsx   JWT session state
    pages/                    AuthPage, Dashboard
    components/
      ChangeFeed.jsx           "Since you left" hero
      WatchlistTable.jsx       full reference table
      AddSymbolForm.jsx
```
