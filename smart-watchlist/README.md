# Smart Market Watchlist

*Built for Groww CODE 2026.*

A watchlist that answers **what on my list is unusual since I last looked** — not another live price table.

Groww already tells you a name moved ±5% today. This app is attention triage: an explainable score (plain-English reasons, never a bare number) and a personal **Since you left** feed. Two people watching `AAPL` can see different cards depending on when *each of them* last checked.

---

## What counts as meaningful

Not `abs(% change) > 5%`. A flat 5% treats HDFC Bank and a small-cap the same. The engine in [`backend/app/services/scoring.py`](backend/app/services/scoring.py) stacks independent signals:

| Signal | Why it matters |
|---|---|
| **Volatility-normalized move** | Today's % is compared to *this stock's* trailing 20-day daily volatility. |
| **Volume anomaly** | A move on ~2× usual volume is conviction; the same move on thin volume is noise. |
| **52-week high / low** | A structural level. Taken from Yahoo's real 52-week range, not from a few polls. |
| **Opening gap** | Gapped at the open (often news) vs drifted intraday. |
| **Calendar** | Results or ex-dividend in the next 7 days. |
| **DMA cross** | Price crossed the 50- or 200-day average vs yesterday's close. Sitting above the 50-day is not an event. |

On top of that global score is a **personal delta**: slow multi-day drift can still matter if *you* have been away.

Volatility and DMA are computed from **daily bars** (last snapshot per UTC day), not 15-second poll ticks. On first add, Yahoo is asked for **~1 year of daily history** so 20-day vol and 200-day DMA are real immediately.

**US** tickers work as-is (`AAPL`). **NSE/BSE** need Yahoo suffixes (`RELIANCE.NS`, `TCS.BO`); those prices show in ₹. Stooq has no India coverage — Yahoo alone is used for `.NS` / `.BO`.

---

## Since you left

The digest is empty right after you add a symbol. That is correct: adding is looking. The pointer (`last_seen_at` / `last_seen_price`) is set on add, and again on **Mark as seen** or **Catch up**.

A name appears in the feed only if, *after that pointer*:

1. A scored event fired (vol, volume, 52-week, gap, DMA, …), or
2. Price drifted enough since *your* last price, or
3. Results / ex-div fall in the next week and you last looked *before* that week started.

Holdings (`I hold this`) rank above names you only watch, in both the table and the digest.

---

## Architecture

API requests never call Yahoo or Stooq. They read `SymbolState`. A background poller keeps that table fresh. Cost scales with **distinct symbols**, not users: 500 people watching `AAPL` is one poll target.

```
┌─────────────┐   REST + JWT    ┌──────────────────────────────┐
│  React/Vite │ ◄─────────────► │ FastAPI                      │
│  :5173      │                 │ /auth /watchlist /digest     │
└─────────────┘                 └───────────────┬──────────────┘
                                                │ reads only
                                                ▼
                                       ┌─────────────────┐
                                       │  SymbolState    │
                                       │  SQLite / PG    │
                                       └────────▲────────┘
                                                │ writes
                                       ┌────────┴────────┐
                                       │ Poller thread   │
                                       │ (or app.worker) │
                                       └────────┬────────┘
                          ┌─────────────────────┴─────────────────────┐
                          ▼                                           ▼
                 ┌─────────────────┐                         ┌─────────────────┐
                 │ Yahoo (primary) │                         │ Stooq (fallback)│
                 │ keyless chart   │                         │ keyless CSV     │
                 └─────────────────┘                         └─────────────────┘
```

- **Backend:** FastAPI + SQLAlchemy. SQLite by default (`watchlist.db`). `DATABASE_URL` can point at Postgres with no code change.
- **Providers:** Yahoo + Stooq behind `QuoteProvider`. Fetched in parallel. Disagree by more than 1.5% → `sources disagree`. Both fail → `delayed`, not a fake live price.
- **Stale means the quote clock**, not download time: Yahoo `regularMarketTime`, Stooq Date+Time. A Friday close on Saturday shows delayed.
- **Frontend:** React (Vite). Login/register, then the dashboard. Polls every 20s while the tab is visible. Does not talk to Yahoo or Stooq.

There are **no market-data API keys**. `JWT_SECRET` signs login tokens; set a real one when `ENV` is not `dev`/`test` or the API will refuse to boot. See [PRODUCT.md](PRODUCT.md) for the key story.

---

## Running it locally

Repo root is the inner `smart-watchlist/` folder (the one that contains `backend/` and `frontend/`).

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

macOS / Linux: `source .venv/bin/activate` instead of the `Activate.ps1` line.

API: `http://localhost:8000` · Swagger: `http://localhost:8000/docs`

```powershell
python -m pytest app/tests
```

### Frontend

```powershell
cd frontend
npm install
copy .env.example .env    # Unix: cp .env.example .env
npm run dev
```

UI: `http://localhost:5173`

### Try it

1. Create an account (email is stored lowercase).
2. Add `AAPL` or `RELIANCE.NS`. The table fills; **Since you left stays empty** until something changes after you looked.
3. Toggle **I hold this** on names you own — they rank first.
4. When a card appears: reasons explain why. **Mark as seen** clears one name; **Catch up** clears the feed.

### Multiple API workers

```powershell
$env:ENABLE_INPROCESS_POLLER="false"
python -m app.worker
uvicorn app.main:app --workers 4
```

---

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/auth/register` | No | Create account, JWT |
| POST | `/auth/login` | No | OAuth2 form (`username` = email), JWT |
| GET | `/auth/me` | Yes | Current user |
| GET | `/watchlist` | Yes | List + quotes, ranked by holdings then attention |
| POST | `/watchlist` | Yes | Add symbol (warm Yahoo history unless already cached) |
| DELETE | `/watchlist/{symbol}` | Yes | Remove |
| POST | `/watchlist/{symbol}/seen` | Yes | Advance last-seen for one name |
| POST | `/watchlist/seen-all` | Yes | Catch up — all names |
| POST | `/watchlist/{symbol}/held` | Yes | `{ "held": true }` — I hold this |
| GET | `/digest` | Yes | Ranked since-you-left feed |
| GET | `/health` | No | Liveness |

---

## What we kept simple (and why)

The brief asks for honesty about trade-offs:

- **No Redis.** [`cache.py`](backend/app/services/cache.py) is an in-memory lock so add and the poller do not double-fetch the same symbol. A Redis swap is a new `Cache` class, not a rewrite.
- **Polling, not WebSockets.** Users open a watchlist periodically. Live ticks are what Groww Terminal already owns.
- **SQLite by default.** Zero setup. Postgres is `DATABASE_URL`.
- **No F&O, VIX, LLM news, licensed NSE feed.** Those need data we do not have, or they clone Groww. The gap we fill is personal catch-up with inspectable reasons.

Complexity went into scoring, last-seen, conflict/staleness, and daily-bar honesty — not a second price table.

---

## Testing

From `backend/`:

```powershell
python -m pytest app/tests
```

- Unit tests for scoring (vol, 52-week, calendar, DMA crosses, personal delta), daily-bar stats, Yahoo/Stooq parse fixtures, aggregator conflict/fallback/staleness, digest ranking, auth (email case, JWT secret in prod).
- HTTP smoke test (`TestClient`, mocked quotes): register → add → list → digest empty on add → event after last-seen → mark-seen clears → duplicate 409 → delete → unauthenticated 401.

Parsing is tested against fixture payloads. Yahoo/Stooq can change shape in the wild; failures raise `QuoteProviderError` instead of failing silent.

---

## Layout

```
backend/app/
  main.py                 FastAPI, CORS, poller lifespan, JWT secret check
  worker.py               standalone poller
  config.py               env tunables
  db.py                   SQLite/Postgres + column migrate
  models.py / schemas.py
  auth.py                 JWT, bcrypt (72-byte cap), lowercase email
  routers/                auth, watchlist, digest
  services/
    scoring.py            attention score + calendar + DMA
    stats.py              daily-bar vol/volume/DMA
    poller.py             warm 1y Yahoo history, trim, lock
    cache.py              in-process fetch lock
    symbols.py            AAPL vs RELIANCE.NS
    data_providers/       yahoo, stooq, aggregator
  tests/
frontend/src/
  api/client.js           REST + Bearer; 401 logs out
  context/AuthContext.jsx
  pages/                  AuthPage, Dashboard
  components/             ChangeFeed, WatchlistTable, AddSymbolForm
```
