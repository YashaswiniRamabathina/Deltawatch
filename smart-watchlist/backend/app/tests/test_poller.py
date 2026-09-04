import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import QuoteSnapshot, SymbolState, WatchlistItem
from app.services.data_providers.base import RawQuote
from app.services.poller import (
    DAILY_RETAIN_DAYS,
    WARM_MIN_DAILY_BARS,
    has_fresh_quote,
    load_history_for_baseline,
    needs_history_warm,
    resolve_52w,
    seed_yahoo_history,
    trim_snapshots,
)
from app.services.stats import SymbolBaseline
from app.routers.watchlist import seed_last_seen


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add_snap(db, symbol, price, when):
    row = QuoteSnapshot(
        symbol=symbol,
        source="yahoo",
        price=price,
        fetched_at=when,
    )
    db.add(row)
    db.flush()
    return row


def test_load_history_keeps_newest_rows_oldest_first(monkeypatch):
    import app.services.poller as poller

    monkeypatch.setattr(poller, "HISTORY_LOAD_LIMIT", 3)
    db = _session()
    now = dt.datetime(2026, 9, 4, 12, 0, 0)
    for i in range(5):
        _add_snap(db, "AAPL", 100 + i, now + dt.timedelta(minutes=i))
    db.commit()

    history = load_history_for_baseline(db, "AAPL")
    assert [h.price for h in history] == [102.0, 103.0, 104.0]


def test_trim_keeps_recent_ticks_and_one_bar_per_older_day():
    db = _session()
    now = dt.datetime(2026, 9, 4, 12, 0, 0)

    _add_snap(db, "AAPL", 1.0, now - dt.timedelta(days=DAILY_RETAIN_DAYS + 20))  # too old
    old_day = now - dt.timedelta(days=10)
    _add_snap(db, "AAPL", 10.0, old_day)
    keep_old = _add_snap(db, "AAPL", 11.0, old_day + dt.timedelta(hours=3))
    recent_a = _add_snap(db, "AAPL", 20.0, now - dt.timedelta(hours=1))
    recent_b = _add_snap(db, "AAPL", 21.0, now - dt.timedelta(minutes=15))
    db.commit()

    deleted = trim_snapshots(db, "AAPL", now=now)
    db.commit()
    remaining = {row.id for row in db.query(QuoteSnapshot).all()}
    assert deleted == 2  # too-old day + first snapshot of the 10-day-old day
    assert remaining == {keep_old.id, recent_a.id, recent_b.id}


def test_resolve_52w_prefers_provider_over_thin_history():
    quote = RawQuote(symbol="AAPL", source="yahoo", price=227.0, high_52w=260.0, low_52w=164.0)
    baseline = SymbolBaseline(high_52w=None, low_52w=None)
    assert resolve_52w(quote, baseline) == (260.0, 164.0)


def test_resolve_52w_falls_back_to_baseline_when_provider_omits_it():
    quote = RawQuote(symbol="AAPL", source="stooq", price=227.0)
    baseline = SymbolBaseline(high_52w=250.0, low_52w=170.0)
    assert resolve_52w(quote, baseline) == (250.0, 170.0)


def test_seed_last_seen_copies_current_price():
    item = WatchlistItem(user_id=1, symbol="AAPL")
    state = SymbolState(symbol="AAPL", last_price=227.52)
    when = dt.datetime(2026, 9, 4, 12, 0, 0)
    seed_last_seen(item, state, now=when)
    assert item.last_seen_at == when
    assert item.last_seen_price == 227.52


def test_seed_last_seen_without_quote_still_sets_the_clock():
    item = WatchlistItem(user_id=1, symbol="AAPL")
    when = dt.datetime(2026, 9, 4, 12, 0, 0)
    seed_last_seen(item, None, now=when)
    assert item.last_seen_at == when
    assert item.last_seen_price is None


def test_needs_history_warm_until_enough_distinct_days():
    db = _session()
    assert needs_history_warm(db, "AAPL") is True
    now = dt.datetime(2026, 9, 4, 12, 0, 0)
    for i in range(WARM_MIN_DAILY_BARS):
        _add_snap(db, "AAPL", 100 + i, now - dt.timedelta(days=i))
    db.commit()
    assert needs_history_warm(db, "AAPL") is False


def test_has_fresh_quote_requires_price_and_warmed_history():
    db = _session()
    assert has_fresh_quote(db, "AAPL") is False
    db.add(SymbolState(symbol="AAPL", last_price=100.0))
    db.commit()
    assert has_fresh_quote(db, "AAPL") is False  # not enough daily bars
    now = dt.datetime(2026, 9, 4, 12, 0, 0)
    for i in range(WARM_MIN_DAILY_BARS):
        _add_snap(db, "AAPL", 100 + i, now - dt.timedelta(days=i))
    db.commit()
    assert has_fresh_quote(db, "AAPL") is True


def test_seed_yahoo_history_inserts_bars(monkeypatch):
    bars = [
        RawQuote(
            symbol="AAPL",
            source="yahoo",
            price=100.0 + i,
            fetched_at=dt.datetime(2026, 7, 1) + dt.timedelta(days=i),
        )
        for i in range(5)
    ]

    def fake_history(self, symbol, range_="1y"):
        return bars

    monkeypatch.setattr(
        "app.services.poller.YahooProvider.fetch_daily_history",
        fake_history,
    )
    db = _session()
    n = seed_yahoo_history(db, "AAPL")
    db.commit()
    assert n == 5
    assert db.query(QuoteSnapshot).filter(QuoteSnapshot.symbol == "AAPL").count() == 5
