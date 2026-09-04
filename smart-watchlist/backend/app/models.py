import datetime as dt

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from app.db import Base


def utcnow():
    return dt.datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    watchlist_items = relationship("WatchlistItem", back_populates="user", cascade="all, delete-orphan")


class WatchlistItem(Base):
    """A single symbol on a single user's watchlist. This is the only
    per-user, per-symbol persistent link — everything about the symbol
    itself (price, score, history) is shared/global so it's computed once
    and read by every user watching it."""
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_user_symbol"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    added_at = Column(DateTime, default=utcnow)

    # Personalized "since you last checked" pointer. This is what makes the
    # change feed personal rather than global: two users watching the same
    # symbol can see different "what changed" framings depending on when
    # each of them last looked.
    last_seen_at = Column(DateTime, nullable=True)
    last_seen_price = Column(Float, nullable=True)
    is_held = Column(Boolean, default=False)

    user = relationship("User", back_populates="watchlist_items")


class QuoteSnapshot(Base):
    """One polled data point for a symbol, tagged with its source and
    fetch time. We keep a rolling history (not just 'latest') so the
    scoring engine can compute volatility/volume baselines and so we have
    an audit trail when two sources disagree."""
    __tablename__ = "quote_snapshots"
    __table_args__ = (Index("ix_symbol_fetched", "symbol", "fetched_at"),)

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    source = Column(String(30), nullable=False)
    price = Column(Float, nullable=False)
    prev_close = Column(Float, nullable=True)
    day_open = Column(Float, nullable=True)
    day_high = Column(Float, nullable=True)
    day_low = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    fetched_at = Column(DateTime, default=utcnow, index=True)
    # True if the aggregator had to pick this over a conflicting reading
    # from another source, or if this reading itself looked anomalous.
    flagged_conflict = Column(Boolean, default=False)


class SymbolState(Base):
    """The single canonical 'current view' of a symbol: latest reconciled
    quote + rolling stats + the most recent change score. Recomputed once
    per poll cycle by the background worker, read by every request. This
    is the object that makes reads cheap regardless of watchlist size —
    an API request never talks to the market data provider directly."""
    __tablename__ = "symbol_state"

    symbol = Column(String(20), primary_key=True)
    last_price = Column(Float, nullable=True)
    prev_close = Column(Float, nullable=True)
    day_open = Column(Float, nullable=True)
    day_high = Column(Float, nullable=True)
    day_low = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    avg_volume_20d = Column(Float, nullable=True)
    volatility_20d = Column(Float, nullable=True)  # stdev of daily % returns
    high_52w = Column(Float, nullable=True)
    low_52w = Column(Float, nullable=True)
    dma_50 = Column(Float, nullable=True)
    dma_200 = Column(Float, nullable=True)
    last_source = Column(String(30), nullable=True)
    last_updated_at = Column(DateTime, nullable=True)
    is_stale = Column(Boolean, default=False)
    flagged_conflict = Column(Boolean, default=False)
    earnings_at = Column(DateTime, nullable=True)
    ex_dividend_at = Column(DateTime, nullable=True)

    # Most recent computed "meaningful change" score + explanation, so the
    # API can serve it instantly without recomputing per-request.
    change_score = Column(Float, default=0.0)
    change_reasons = Column(Text, nullable=True)  # JSON-encoded list[str]


class ChangeEvent(Base):
    """An immutable log of notable moments for a symbol (score crossed the
    'meaningful' threshold). This is what powers 'what changed since you
    left' — instead of diffing raw prices, we diff against this curated
    event log, which is cheap and explainable."""
    __tablename__ = "change_events"
    __table_args__ = (Index("ix_symbol_time", "symbol", "occurred_at"),)

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    occurred_at = Column(DateTime, default=utcnow, index=True)
    score = Column(Float, nullable=False)
    price_at_event = Column(Float, nullable=True)
    reasons = Column(Text, nullable=True)  # JSON-encoded list[str]
