import datetime as dt
import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, WatchlistItem, SymbolState, ChangeEvent
from app.schemas import DigestOut, DigestEntry
from app.auth import get_current_user
from app.services.scoring import (
    score_personal_delta,
    MEANINGFUL_THRESHOLD,
    score_calendar_events,
    should_surface_calendar,
)

router = APIRouter(tags=["digest"])


def latest_change_events(db: Session, items: list[WatchlistItem]) -> dict[str, ChangeEvent]:
    """One query for the whole list: highest-score ChangeEvent per symbol
    that occurred after that symbol's last_seen (or added_at)."""
    if not items:
        return {}
    since_by_symbol = {item.symbol: item.last_seen_at or item.added_at for item in items}
    times = [when for when in since_by_symbol.values() if when is not None]
    if not times:
        return {}
    min_since = min(times)
    rows = (
        db.query(ChangeEvent)
        .filter(
            ChangeEvent.symbol.in_(list(since_by_symbol)),
            ChangeEvent.occurred_at >= min_since,
        )
        .order_by(ChangeEvent.score.desc(), ChangeEvent.occurred_at.desc())
        .all()
    )
    best: dict[str, ChangeEvent] = {}
    for event in rows:
        since = since_by_symbol.get(event.symbol)
        if since is not None and event.occurred_at < since:
            continue
        if event.symbol not in best:
            best[event.symbol] = event
    return best


def rank_digest(entries: list[DigestEntry]) -> list[DigestEntry]:
    """Holdings first, then highest score."""
    entries.sort(key=lambda e: (0 if e.is_held else 1, -e.score, e.symbol))
    return entries


@router.get("/digest", response_model=DigestOut)
def get_digest(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """The hero endpoint: for every symbol the user watches, decide
    whether anything worth their attention happened since THEY last
    looked (not just 'today'), and rank the results.

    A symbol surfaces here if:
      (a) a global ChangeEvent occurred for it after the user's
          last_seen_at for that symbol, or
      (b) the price has drifted meaningfully since the user's own
          last_seen_price, even without a single-day event (this is what
          catches slow multi-day drift for someone who's been away a while), or
      (c) results or an ex-dividend date fall in the next week and the
          user last looked before that week started.
    """
    items = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id).all()
    if not items:
        return DigestOut(generated_at=dt.datetime.utcnow(), entries=[])

    symbols = [i.symbol for i in items]
    states = {s.symbol: s for s in db.query(SymbolState).filter(SymbolState.symbol.in_(symbols)).all()}
    events_by_symbol = latest_change_events(db, items)

    entries: list[DigestEntry] = []

    for item in items:
        state = states.get(item.symbol)
        if state is None or state.last_price is None:
            continue

        reasons: list[str] = []
        score = 0.0

        since = item.last_seen_at or item.added_at
        recent_event = events_by_symbol.get(item.symbol)
        if recent_event:
            score = max(score, recent_event.score)
            reasons.extend(json.loads(recent_event.reasons) if recent_event.reasons else [])

        personal_reason = score_personal_delta(state.last_price, item.last_seen_price, state.volatility_20d)
        if personal_reason:
            reasons.append(personal_reason)
            score = max(score, MEANINGFUL_THRESHOLD)  # personal drift alone clears the bar

        now = dt.datetime.utcnow()
        last_seen = item.last_seen_at
        earnings_at = getattr(state, "earnings_at", None)
        ex_dividend_at = getattr(state, "ex_dividend_at", None)
        cal = score_calendar_events(
            earnings_at if should_surface_calendar(earnings_at, last_seen, now) else None,
            ex_dividend_at if should_surface_calendar(ex_dividend_at, last_seen, now) else None,
            now=now,
        )
        if cal.reasons:
            reasons.extend(cal.reasons)
            score = max(score, cal.score)

        if not reasons:
            continue

        change_pct = None
        if item.last_seen_price:
            change_pct = (state.last_price - item.last_seen_price) / item.last_seen_price * 100
        elif state.prev_close:
            change_pct = (state.last_price - state.prev_close) / state.prev_close * 100

        entries.append(DigestEntry(
            symbol=item.symbol,
            score=round(score, 2),
            reasons=list(dict.fromkeys(reasons)),  # de-dupe, preserve order
            price=state.last_price,
            change_pct=round(change_pct, 2) if change_pct is not None else None,
            since=since,
            is_held=bool(getattr(item, "is_held", False)),
        ))

    return DigestOut(generated_at=dt.datetime.utcnow(), entries=rank_digest(entries))
