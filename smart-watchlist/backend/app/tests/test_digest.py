import datetime as dt

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import User, WatchlistItem, ChangeEvent
from app.routers.market import latest_change_events, rank_digest
from app.schemas import DigestEntry


def test_rank_digest_held_first_then_score():
    entries = [
        DigestEntry(symbol="AAPL", score=5.0, reasons=["big move"]),
        DigestEntry(symbol="MSFT", score=1.0, reasons=["results due tomorrow"], is_held=True),
        DigestEntry(symbol="TSLA", score=3.0, reasons=["volume"], is_held=True),
    ]
    ranked = rank_digest(entries)
    assert [e.symbol for e in ranked] == ["TSLA", "MSFT", "AAPL"]


def test_latest_change_events_picks_highest_score_after_each_last_seen():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    now = dt.datetime(2026, 9, 4, 12, 0, 0)
    user = User(email="a@b.com", hashed_password="x")
    db.add(user)
    db.flush()
    aapl = WatchlistItem(
        user_id=user.id, symbol="AAPL",
        added_at=now - dt.timedelta(days=10),
        last_seen_at=now - dt.timedelta(days=1),
    )
    msft = WatchlistItem(
        user_id=user.id, symbol="MSFT",
        added_at=now - dt.timedelta(days=10),
        last_seen_at=now - dt.timedelta(hours=1),
    )
    db.add_all([aapl, msft])
    db.add_all([
        ChangeEvent(symbol="AAPL", occurred_at=now - dt.timedelta(hours=2), score=1.0, reasons='["old"]'),
        ChangeEvent(symbol="AAPL", occurred_at=now - dt.timedelta(hours=2), score=4.0, reasons='["big"]'),
        ChangeEvent(symbol="AAPL", occurred_at=now - dt.timedelta(days=3), score=9.0, reasons='["too old"]'),
        ChangeEvent(symbol="MSFT", occurred_at=now - dt.timedelta(minutes=10), score=2.0, reasons='["recent"]'),
        ChangeEvent(symbol="MSFT", occurred_at=now - dt.timedelta(hours=3), score=8.0, reasons='["before last seen"]'),
    ])
    db.commit()

    best = latest_change_events(db, [aapl, msft])
    assert best["AAPL"].score == 4.0
    assert best["MSFT"].score == 2.0
