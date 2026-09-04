import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, WatchlistItem, SymbolState
from app.schemas import WatchlistAdd, WatchlistHeld, WatchlistItemOut, SymbolQuote
from app.auth import get_current_user
from app.services.data_providers.aggregator import QuoteAggregator
from app.services.data_providers.base import QuoteProviderError
from app.services.poller import has_fresh_quote, refresh_symbol
from app.services.scoring import score_personal_delta
from app.services.symbols import SymbolError, normalize_symbol

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


def seed_last_seen(item: WatchlistItem, state: SymbolState | None, now: dt.datetime | None = None) -> None:
    """Anchor the personal digest at *this* moment so “since you left”
    means since add (or since last acknowledge), not “everything notable
    that already happened today”."""
    item.last_seen_at = now or dt.datetime.utcnow()
    if state is not None and state.last_price is not None:
        item.last_seen_price = state.last_price


def _build_quote(item: WatchlistItem, state: SymbolState | None) -> SymbolQuote:
    if state is None or state.last_price is None:
        return SymbolQuote(symbol=item.symbol, has_data=False, last_seen_at=item.last_seen_at)

    change_pct = None
    if state.prev_close:
        change_pct = (state.last_price - state.prev_close) / state.prev_close * 100

    reasons = json.loads(state.change_reasons) if state.change_reasons else []

    since_delta = None
    since_pct = None
    personal_reason = score_personal_delta(state.last_price, item.last_seen_price, state.volatility_20d)
    if item.last_seen_price is not None:
        since_delta = state.last_price - item.last_seen_price
        since_pct = (since_delta / item.last_seen_price * 100) if item.last_seen_price else None
    if personal_reason:
        reasons = reasons + [personal_reason]

    return SymbolQuote(
        symbol=item.symbol,
        price=state.last_price,
        prev_close=state.prev_close,
        change_pct=round(change_pct, 2) if change_pct is not None else None,
        day_open=state.day_open,
        day_high=state.day_high,
        day_low=state.day_low,
        volume=state.volume,
        avg_volume_20d=state.avg_volume_20d,
        high_52w=state.high_52w,
        low_52w=state.low_52w,
        dma_50=getattr(state, "dma_50", None),
        dma_200=getattr(state, "dma_200", None),
        source=state.last_source,
        updated_at=state.last_updated_at,
        is_stale=bool(state.is_stale),
        has_data=True,
        change_score=state.change_score or 0.0,
        reasons=reasons,
        last_seen_at=item.last_seen_at,
        price_change_since_seen=round(since_delta, 2) if since_delta is not None else None,
        price_change_since_seen_pct=round(since_pct, 2) if since_pct is not None else None,
        flagged_conflict=bool(getattr(state, "flagged_conflict", False)),
    )


def _item_out(item: WatchlistItem, state: SymbolState | None) -> WatchlistItemOut:
    return WatchlistItemOut(
        symbol=item.symbol,
        added_at=item.added_at,
        is_held=bool(getattr(item, "is_held", False)),
        quote=_build_quote(item, state),
    )


def rank_watchlist(rows: list[WatchlistItemOut]) -> list[WatchlistItemOut]:
    """Pending quotes last; holdings before names you only watch; then score."""
    rows.sort(key=lambda row: (
        0 if row.quote.has_data else 1,
        0 if row.is_held else 1,
        -(row.quote.change_score or 0.0),
        row.symbol,
    ))
    return rows


@router.get("", response_model=list[WatchlistItemOut])
def list_watchlist(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    items = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id).order_by(WatchlistItem.added_at).all()
    states = {
        s.symbol: s
        for s in db.query(SymbolState).filter(SymbolState.symbol.in_([i.symbol for i in items])).all()
    }
    return rank_watchlist([
        _item_out(i, states.get(i.symbol))
        for i in items
    ])


@router.post("/seen-all", response_model=list[WatchlistItemOut])
def mark_all_seen(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Advance last-seen on every symbol this user watches — catch up."""
    now = dt.datetime.utcnow()
    items = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id).all()
    symbols = [i.symbol for i in items]
    states = {
        s.symbol: s
        for s in db.query(SymbolState).filter(SymbolState.symbol.in_(symbols)).all()
    } if symbols else {}
    for item in items:
        state = states.get(item.symbol)
        item.last_seen_at = now
        if state is not None and state.last_price is not None:
            item.last_seen_price = state.last_price
    db.commit()
    for item in items:
        db.refresh(item)
    return rank_watchlist([_item_out(i, states.get(i.symbol)) for i in items])


@router.post("", response_model=WatchlistItemOut, status_code=201)
def add_symbol(payload: WatchlistAdd, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        symbol = normalize_symbol(payload.symbol)
    except SymbolError as e:
        raise HTTPException(status_code=400, detail=str(e))

    existing = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id, WatchlistItem.symbol == symbol).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"{symbol} is already on your watchlist")

    # Validate + warm the cache synchronously so the user gets an instant
    # quote instead of waiting for the next poll tick. If every provider
    # fails we still add the symbol (it might be valid but temporarily
    # unreachable) but tell the caller so the UI can show "pending data"
    # rather than pretending it's confirmed.
    warmed = True
    if has_fresh_quote(db, symbol):
        pass  # already in SymbolState — skip Yahoo/Stooq so Add stays instant
    else:
        try:
            refresh_symbol(db, QuoteAggregator(), symbol)
        except QuoteProviderError:
            warmed = False

    item = WatchlistItem(user_id=user.id, symbol=symbol, is_held=bool(payload.is_held))
    state = db.query(SymbolState).filter(SymbolState.symbol == symbol).first()
    seed_last_seen(item, state)
    db.add(item)
    db.commit()
    db.refresh(item)

    result = _item_out(item, state)
    if not warmed:
        result.quote.has_data = False
    return result


@router.delete("/{symbol}", status_code=204)
def remove_symbol(symbol: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    item = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id, WatchlistItem.symbol == symbol).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"{symbol} is not on your watchlist")
    db.delete(item)
    db.commit()
    return None


@router.post("/{symbol}/seen", response_model=WatchlistItemOut)
def mark_seen(symbol: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Call this when the user views/acknowledges a symbol. Advances their
    personal 'last checked' pointer so future visits diff from *now*
    rather than re-surfacing the same change forever."""
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    item = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id, WatchlistItem.symbol == symbol).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"{symbol} is not on your watchlist")

    state = db.query(SymbolState).filter(SymbolState.symbol == symbol).first()
    item.last_seen_at = dt.datetime.utcnow()
    item.last_seen_price = state.last_price if state else item.last_seen_price
    db.commit()
    db.refresh(item)

    return _item_out(item, state)


@router.post("/{symbol}/held", response_model=WatchlistItemOut)
def set_held(symbol: str, payload: WatchlistHeld, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        symbol = normalize_symbol(symbol)
    except SymbolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    item = db.query(WatchlistItem).filter(WatchlistItem.user_id == user.id, WatchlistItem.symbol == symbol).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"{symbol} is not on your watchlist")
    item.is_held = bool(payload.held)
    db.commit()
    db.refresh(item)
    state = db.query(SymbolState).filter(SymbolState.symbol == symbol).first()
    return _item_out(item, state)
