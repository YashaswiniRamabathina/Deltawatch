# Smart Watchlist — product, architecture, and keys

Built for **Groww CODE 2026**. This note is a walkthrough of what the product is, how the frontend and backend are split, how data moves, and why there are almost no API keys.

For setup commands, see [README.md](README.md).

---

## What this product is

A watchlist that answers: **what on my list actually deserves attention since I last looked?**

Price tables are a solved problem. This app is **attention triage**. It ranks symbols with an explainable score (plain-English reasons, not a bare number) and a **personal** “Since you left” feed. Two people watching `AAPL` can see different stories depending on when *each of them* last checked.

**Meaningful** is not “moved more than 5%.” The scoring engine combines:

| Signal | Idea |
|---|---|
| Volatility-normalized move | A 2% day is huge for a utility and noise for a small-cap. Today’s move is compared to *that stock’s* trailing 20-day daily volatility. |
| Volume anomaly | A move on 3× usual volume is conviction; the same move on thin volume is noise. |
| 52-week high / low | A structural level, independent of today’s percentage. |
| Opening gap | Did it gap at the open (often news) or drift intraday? |

Signals **stack**. A gap + volume spike + new low ranks above any one signal. On top of the global score is a **personal delta**: slow multi-day drift can still matter if you have been away.

US tickers work as-is (`AAPL`). Indian listings use Yahoo suffixes (`RELIANCE.NS`, `TCS.BO`). NSE/BSE prices show in ₹.

---

## Architecture

Reads never call Yahoo or Stooq. The API only reads a cache table (`SymbolState`) that a background poller keeps fresh. Cost scales with **distinct symbols**, not distinct users: 500 people watching `AAPL` is one poll target.

```
┌──────────────────┐          REST + JWT           ┌─────────────────────────┐
│  React (Vite)    │  ◄──────────────────────────► │  FastAPI                │
│  localhost:5173  │                               │  /auth /watchlist /digest│
└──────────────────┘                               └────────────┬────────────┘
                                                                │ reads only
                                                                ▼
                                                       ┌─────────────────┐
                                                       │  SymbolState    │
                                                       │  SQLite / PG    │
                                                       └────────▲────────┘
                                                                │ writes
                                                       ┌────────┴────────┐
                                                       │  Poller thread  │
                                                       │  (or app.worker)│
                                                       └────────┬────────┘
                                                                │
                                              ┌─────────────────┴─────────────────┐
                                              ▼                                   ▼
                                     ┌─────────────────┐                 ┌─────────────────┐
                                     │ Yahoo (primary) │                 │ Stooq (fallback)│
                                     │ keyless chart   │                 │ keyless CSV     │
                                     └─────────────────┘                 └─────────────────┘
```

On first add, Yahoo is also asked for **~3 months of daily bars** so 20-day volatility/volume exist immediately. Live polls then keep the latest quote. History is collapsed to **one bar per UTC day** before volatility is computed (not 15-second ticks).

**Datetimes** are UTC in the database and on the wire (`2026-09-04T08:35:00Z`). Relative UI copy (“3h ago”) is elapsed time from that instant. Clock times, if shown, should be IST for Groww users.

---

## Frontend

**Stack:** React 18, Vite, no router library. Two screens: login/register, then the dashboard.

| Piece | Role |
|---|---|
| `src/api/client.js` | `fetch` wrapper. Base URL from `VITE_API_URL`. Attaches `Authorization: Bearer <JWT>`. |
| `src/context/AuthContext.jsx` | Session: token in `localStorage`, `/auth/me` on load. |
| `src/pages/AuthPage.jsx` | Email + password, login or create account. |
| `src/pages/Dashboard.jsx` | Polls `/watchlist` and `/digest` every 20 seconds. |
| `src/components/ChangeFeed.jsx` | “Since you left” cards + **Mark as seen**. |
| `src/components/WatchlistTable.jsx` | Full list, sorted by attention, top reason, delayed / sources-disagree tags. |
| `src/components/AddSymbolForm.jsx` | Add `AAPL` or `RELIANCE.NS`. |

**User flow**

1. Create an account or log in → JWT stored locally.
2. Add tickers. The API warms quotes (and Yahoo history) before returning.
3. The table is the reference list (price, change, volume, 52-week range, attention).
4. The digest is the product: only symbols that crossed the bar *since this user’s* `last_seen` pointer.
5. **Mark as seen** advances that pointer so the same move does not stay in the feed forever.

The frontend does not talk to Yahoo or Stooq. It only talks to FastAPI.

---

## Backend

**Stack:** FastAPI, SQLAlchemy, SQLite by default (`watchlist.db`). Optional Postgres via `DATABASE_URL`. Passwords hashed with bcrypt. Sessions are JWTs signed with `JWT_SECRET`.

### HTTP API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/auth/register` | No | Create user, return JWT |
| `POST` | `/auth/login` | No | OAuth2 form (`username` = email), return JWT |
| `GET` | `/auth/me` | Yes | Current user |
| `GET` | `/watchlist` | Yes | List + quotes, ranked by attention score |
| `POST` | `/watchlist` | Yes | Add symbol, validate, warm cache |
| `DELETE` | `/watchlist/{symbol}` | Yes | Remove |
| `POST` | `/watchlist/{symbol}/seen` | Yes | Advance personal last-seen pointer |
| `GET` | `/digest` | Yes | Ranked “since you left” feed |
| `GET` | `/health` | No | Liveness |
| — | `/docs` | No | Swagger |

### Main tables

- **`users`** — email + password hash.
- **`watchlist_items`** — per user, per symbol. Holds `last_seen_at` / `last_seen_price` (set on add, updated on mark-seen).
- **`symbol_state`** — one row per symbol: last quote, baselines, score, reasons, stale/conflict flags. This is what GET endpoints read.
- **`quote_snapshots`** — poll (and warm) history for volatility/volume. Trimmed: recent ticks + last bar per day.
- **`change_events`** — log when a symbol *crosses into* “meaningful,” used by the digest.

### Scoring and polling

- `app/services/scoring.py` — global score + personal delta.
- `app/services/stats.py` — 20-day vol/volume from **daily** bars; 52-week range only from Yahoo’s real 52-week fields (or a full year of history), not from a few polls.
- `app/services/poller.py` — tiered refresh: hot (≥5 watchers, 15s), warm (≥1, 60s), cold (5 min). Default: in-process thread. For multiple API workers, set `ENABLE_INPROCESS_POLLER=false` and run `python -m app.worker`.

### Quote providers

Both implement `QuoteProvider.fetch(symbol)`:

1. **Yahoo** (primary) — public chart endpoint, no key. Live `range=1d`; on cold start, `range=3mo` daily bars. Meta includes `fiftyTwoWeekHigh` / `fiftyTwoWeekLow`.
2. **Stooq** (fallback + cross-check) — public CSV, no key. US names get a `.us` suffix. **NSE/BSE (`.NS` / `.BO`) are skipped** — Stooq does not cover those names; Yahoo alone is used.

If both answer and prices differ by more than **1.5%**, the quote is flagged `flagged_conflict` and the UI shows **sources disagree**. If the primary fails, Stooq is used. If both fail, `is_stale` is set rather than pretending the last value is live.

---

## How “API keys” work

There are **no market-data API keys**. Yahoo and Stooq are used as public, keyless endpoints on purpose (demo, zero signup, two independent sources for conflict detection). A paid vendor later would be a new `QuoteProvider` class plus an env var — the rest of the app would not change.

What *looks* like a key in this project:

| Name | What it actually is | Required? |
|---|---|---|
| **`JWT_SECRET`** | HMAC secret to **sign and verify login tokens**, not a finance API key. Default in code is a dev string. Set a real secret before any shared deploy. | For production, yes |
| **`VITE_API_URL`** | Frontend’s URL for the FastAPI server (default `http://localhost:8000`). Not a key. | Only if the API is not on localhost:8000 |
| **`DATABASE_URL`** | SQLite path or Postgres URL. Not a market key. | No (SQLite is the default) |
| **`Authorization: Bearer …`** | The user’s JWT after login/register, stored in `localStorage` as `watchlist_token`. Sent on `/watchlist` and `/digest`. | Yes, for those routes |
| Yahoo / Stooq tokens | **None.** Requests are unauthenticated HTTP with a normal User-Agent. | — |

Login is email + password. The server returns `{ "access_token": "<jwt>", "token_type": "bearer" }`. The JWT payload is `sub` (user id), `iat`, `exp` (14 days by default), signed with HS256 and `JWT_SECRET`.

```
Browser                    FastAPI                         Yahoo / Stooq
   │                          │                                 │
   │  POST /auth/login        │                                 │
   │  email + password        │                                 │
   │ ◄──── JWT ────────────── │                                 │
   │                          │                                 │
   │  GET /digest             │                                 │
   │  Authorization: Bearer   │                                 │
   │ ◄──── JSON (from DB) ─── │                                 │
   │                          │     poller (not the GET)        │
   │                          │ ──────────────────────────────► │
   │                          │ ◄──── quotes (no API key) ───── │
```

**Groww / production note:** unofficial Yahoo/Stooq endpoints can rate-limit or change shape. For a real Groww-scale product you would swap in a licensed market-data API behind the same `QuoteProvider` interface and put *that* vendor key in the server environment — never in the React app.

---

## Repo map

```
backend/app/
  main.py                 FastAPI app, CORS, poller lifespan
  auth.py                 JWT + password hashing
  config.py               env tunables
  routers/                auth, watchlist, digest
  services/scoring.py     attention score
  services/poller.py      refresh + Yahoo history warm
  services/data_providers/  yahoo, stooq, aggregator
frontend/src/
  api/client.js           REST + Bearer token
  pages/                  AuthPage, Dashboard
  components/             ChangeFeed, WatchlistTable, AddSymbolForm
```
