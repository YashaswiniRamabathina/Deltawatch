"""
The background worker. This is what makes reads cheap: user requests
never call the market data provider directly, they only ever read
`SymbolState`, which this loop keeps fresh.

Polling is tiered by popularity (see config.HOT/WARM/COLD thresholds) so
cost scales with distinct *symbols*, not with distinct *users* — 500 users
all watching AAPL is one poll target, not 500.
"""
import datetime as dt
import json
import logging
import threading
import time
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import (
    POLL_INTERVAL_HOT_SECONDS, POLL_INTERVAL_WARM_SECONDS, POLL_INTERVAL_COLD_SECONDS,
    HOT_WATCHER_THRESHOLD, WARM_WATCHER_THRESHOLD,
)
from app.db import SessionLocal
from app.models import WatchlistItem, SymbolState, QuoteSnapshot, ChangeEvent
from app.services.cache import cache
from app.services.data_providers.aggregator import QuoteAggregator
from app.services.data_providers.base import QuoteProviderError
from app.services.data_providers.yahoo import YahooProvider
from app.services.stats import compute_baseline
from app.services.scoring import score_symbol, is_meaningful

logger = logging.getLogger("watchlist.poller")

# Newest-N cap after we reverse to oldest->newest. Trim keeps this bounded:
# a few hours of ticks plus one bar per retained day.
HISTORY_LOAD_LIMIT = 4000
TICK_RETAIN_HOURS = 6
DAILY_RETAIN_DAYS = 400  # keep a full 1y warm for 200-DMA
WARM_MIN_DAILY_BARS = 200


def tier_interval_seconds(watcher_count: int) -> int:
    if watcher_count >= HOT_WATCHER_THRESHOLD:
        return POLL_INTERVAL_HOT_SECONDS
    if watcher_count >= WARM_WATCHER_THRESHOLD:
        return POLL_INTERVAL_WARM_SECONDS
    return POLL_INTERVAL_COLD_SECONDS


def _watched_symbols_with_counts(db: Session) -> dict[str, int]:
    rows = (
        db.query(WatchlistItem.symbol, func.count(WatchlistItem.id))
        .group_by(WatchlistItem.symbol)
        .all()
    )
    return {symbol: count for symbol, count in rows}


def _due_for_refresh(state: Optional[SymbolState], interval_seconds: int, now: dt.datetime) -> bool:
    if state is None or state.last_updated_at is None:
        return True
    return (now - state.last_updated_at).total_seconds() >= interval_seconds


def load_history_for_baseline(db: Session, symbol: str) -> list[QuoteSnapshot]:
    """Newest snapshots first, then reverse so callers get oldest -> newest.

    The previous `.order_by(asc).limit(500)` kept the *oldest* 500 rows, so
    after a couple of hours of 15s polls the baseline froze on stale history.
    """
    rows = (
        db.query(QuoteSnapshot)
        .filter(QuoteSnapshot.symbol == symbol)
        .order_by(QuoteSnapshot.fetched_at.desc())
        .limit(HISTORY_LOAD_LIMIT)
        .all()
    )
    rows.reverse()
    return rows


def trim_snapshots(db: Session, symbol: str, now: Optional[dt.datetime] = None) -> int:
    """Keep recent ticks for audit, plus the last snapshot of each UTC day
    so 20-day volume/volatility still have daily bars to work with."""
    now = now or dt.datetime.utcnow()
    tick_cutoff = now - dt.timedelta(hours=TICK_RETAIN_HOURS)
    day_cutoff = now - dt.timedelta(days=DAILY_RETAIN_DAYS)

    rows = (
        db.query(QuoteSnapshot)
        .filter(QuoteSnapshot.symbol == symbol)
        .order_by(QuoteSnapshot.fetched_at.asc())
        .all()
    )
    keep_ids: set[int] = set()
    last_id_by_day: dict = {}
    for row in rows:
        if row.id is None or row.fetched_at is None:
            continue
        if row.fetched_at >= tick_cutoff:
            keep_ids.add(row.id)
        if row.fetched_at >= day_cutoff:
            last_id_by_day[row.fetched_at.date()] = row.id
    keep_ids.update(last_id_by_day.values())

    stale_ids = [row.id for row in rows if row.id not in keep_ids]
    if not stale_ids:
        return 0
    deleted = (
        db.query(QuoteSnapshot)
        .filter(QuoteSnapshot.id.in_(stale_ids))
        .delete(synchronize_session=False)
    )
    return deleted


def resolve_52w(quote, baseline) -> tuple[Optional[float], Optional[float]]:
    """Prefer the provider's real 52-week range. Fall back to history only
    when compute_baseline had enough calendar span to mean it."""
    high = quote.high_52w if getattr(quote, "high_52w", None) else baseline.high_52w
    low = quote.low_52w if getattr(quote, "low_52w", None) else baseline.low_52w
    return high, low


def daily_bar_count(db: Session, symbol: str) -> int:
    n = (
        db.query(func.count(func.distinct(func.date(QuoteSnapshot.fetched_at))))
        .filter(QuoteSnapshot.symbol == symbol)
        .scalar()
    )
    return int(n or 0)


def needs_history_warm(db: Session, symbol: str) -> bool:
    return daily_bar_count(db, symbol) < WARM_MIN_DAILY_BARS


def seed_yahoo_history(db: Session, symbol: str) -> int:
    """Insert Yahoo daily bars. Does not score or emit ChangeEvents — those
    belong to the live quote that follows."""
    bars = YahooProvider(timeout=10.0).fetch_daily_history(symbol)
    for bar in bars:
        db.add(QuoteSnapshot(
            symbol=symbol,
            source=bar.source,
            price=bar.price,
            prev_close=bar.prev_close,
            day_open=bar.day_open,
            day_high=bar.day_high,
            day_low=bar.day_low,
            volume=bar.volume,
            fetched_at=bar.fetched_at,
            flagged_conflict=False,
        ))
    db.flush()
    return len(bars)


def has_fresh_quote(db: Session, symbol: str) -> bool:
    """True if another user (or a prior add) already warmed this symbol."""
    state = db.query(SymbolState).filter(SymbolState.symbol == symbol).first()
    if state is None or state.last_price is None:
        return False
    return not needs_history_warm(db, symbol)


def refresh_symbol(db: Session, aggregator: QuoteAggregator, symbol: str) -> None:
    """Fetch, reconcile, persist a snapshot, recompute baseline + score,
    and log a ChangeEvent if the symbol just crossed the 'meaningful'
    bar. Any failure here is caught by the caller — one bad symbol must
    never take down the whole poll cycle."""
    with cache.lock_for(f"refresh:{symbol}"):
        _refresh_symbol_locked(db, aggregator, symbol)


def _refresh_symbol_locked(db: Session, aggregator: QuoteAggregator, symbol: str) -> None:
    if needs_history_warm(db, symbol):
        try:
            n = seed_yahoo_history(db, symbol)
            db.commit()
            logger.info("warmed %s with %s daily bars from Yahoo", symbol, n)
        except QuoteProviderError as e:
            db.rollback()
            logger.info("history warm skipped for %s: %s", symbol, e)

    reconciled = aggregator.fetch(symbol)  # raises QuoteProviderError on total failure
    q = reconciled.quote

    snapshot = QuoteSnapshot(
        symbol=symbol,
        source=q.source,
        price=q.price,
        prev_close=q.prev_close,
        day_open=q.day_open,
        day_high=q.day_high,
        day_low=q.day_low,
        volume=q.volume,
        fetched_at=q.fetched_at,
        flagged_conflict=reconciled.flagged_conflict,
    )
    db.add(snapshot)
    db.flush()  # assign id + include this tick in the history query (autoflush is off)

    history = load_history_for_baseline(db, symbol)
    baseline = compute_baseline(history)
    high_52w, low_52w = resolve_52w(q, baseline)

    # prev_close fallback: some providers (stooq) don't return it directly;
    # use the most recent prior snapshot's price if we have one.
    prev_close = q.prev_close
    if prev_close is None and len(history) >= 2:
        prev_close = history[-2].price

    state = db.query(SymbolState).filter(SymbolState.symbol == symbol).first()
    earnings_at = getattr(q, "earnings_at", None) or (state.earnings_at if state else None)
    ex_dividend_at = getattr(q, "ex_dividend_at", None) or (state.ex_dividend_at if state else None)

    result = score_symbol(
        price=q.price,
        prev_close=prev_close,
        day_open=q.day_open,
        volume=q.volume,
        avg_volume_20d=baseline.avg_volume_20d,
        volatility_20d_pct=baseline.volatility_20d_pct,
        high_52w=high_52w,
        low_52w=low_52w,
        earnings_at=earnings_at,
        ex_dividend_at=ex_dividend_at,
        dma_50=baseline.dma_50,
        dma_200=baseline.dma_200,
        now=q.fetched_at,
    )

    if state is None:
        state = SymbolState(symbol=symbol)
        db.add(state)

    previously_meaningful = is_meaningful(state.change_score or 0.0)

    state.last_price = q.price
    state.prev_close = prev_close
    state.day_open = q.day_open
    state.day_high = q.day_high
    state.day_low = q.day_low
    state.volume = q.volume
    state.avg_volume_20d = baseline.avg_volume_20d
    state.volatility_20d = baseline.volatility_20d_pct
    state.high_52w = high_52w
    state.low_52w = low_52w
    state.dma_50 = baseline.dma_50
    state.dma_200 = baseline.dma_200
    state.last_source = q.source
    state.last_updated_at = q.fetched_at
    state.is_stale = reconciled.is_stale
    state.flagged_conflict = reconciled.flagged_conflict
    state.earnings_at = earnings_at
    state.ex_dividend_at = ex_dividend_at
    state.change_score = result.score
    state.change_reasons = json.dumps(result.reasons)

    # Log a ChangeEvent only on the *transition* into "meaningful", not
    # every poll cycle while it stays meaningful — otherwise the digest
    # would just fill up with duplicates of the same event.
    if is_meaningful(result.score) and not previously_meaningful:
        db.add(ChangeEvent(
            symbol=symbol,
            occurred_at=q.fetched_at,
            score=result.score,
            price_at_event=q.price,
            reasons=json.dumps(result.reasons),
        ))

    trim_snapshots(db, symbol, now=q.fetched_at)
    db.commit()


def run_once(aggregator: Optional[QuoteAggregator] = None) -> None:
    aggregator = aggregator or QuoteAggregator()
    db = SessionLocal()
    try:
        watcher_counts = _watched_symbols_with_counts(db)
        now = dt.datetime.utcnow()

        for symbol, count in watcher_counts.items():
            interval = tier_interval_seconds(count)
            state = db.query(SymbolState).filter(SymbolState.symbol == symbol).first()
            if not _due_for_refresh(state, interval, now):
                continue
            try:
                refresh_symbol(db, aggregator, symbol)
            except QuoteProviderError as e:
                logger.warning("poll failed for %s: %s", symbol, e)
                if state:
                    # Don't silently keep serving old data as if it's live —
                    # mark it stale so the API/UI can be honest about it.
                    state.is_stale = True
                    db.commit()
            except Exception:
                db.rollback()
                logger.exception("unexpected error polling %s", symbol)
    finally:
        db.close()


def run_forever(stop_event: Optional[threading.Event] = None) -> None:
    stop_event = stop_event or threading.Event()
    tick_seconds = min(POLL_INTERVAL_HOT_SECONDS, POLL_INTERVAL_WARM_SECONDS, POLL_INTERVAL_COLD_SECONDS)
    logger.info("poller started, tick=%ss", tick_seconds)
    while not stop_event.is_set():
        try:
            run_once()
        except Exception:
            logger.exception("poll cycle crashed, will retry next tick")
        stop_event.wait(tick_seconds)


def start_background_thread() -> threading.Event:
    stop_event = threading.Event()
    t = threading.Thread(target=run_forever, args=(stop_event,), daemon=True)
    t.start()
    return stop_event
