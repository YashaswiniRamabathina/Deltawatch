import datetime as dt

from app.routers.watchlist import rank_watchlist
from app.schemas import SymbolQuote, WatchlistItemOut


def _row(symbol, score, has_data=True, is_held=False):
    return WatchlistItemOut(
        symbol=symbol,
        added_at=dt.datetime(2026, 9, 1),
        is_held=is_held,
        quote=SymbolQuote(symbol=symbol, has_data=has_data, change_score=score, price=1.0 if has_data else None),
    )


def test_rank_watchlist_highest_score_first():
    rows = [_row("MSFT", 0.4), _row("AAPL", 4.2), _row("TSLA", 2.1)]
    ranked = rank_watchlist(rows)
    assert [r.symbol for r in ranked] == ["AAPL", "TSLA", "MSFT"]


def test_rank_watchlist_pending_last():
    rows = [_row("ZZZZ", 0, has_data=False), _row("AAPL", 0.1)]
    ranked = rank_watchlist(rows)
    assert [r.symbol for r in ranked] == ["AAPL", "ZZZZ"]


def test_rank_watchlist_held_before_higher_score():
    rows = [_row("AAPL", 4.2), _row("MSFT", 0.4, is_held=True)]
    ranked = rank_watchlist(rows)
    assert [r.symbol for r in ranked] == ["MSFT", "AAPL"]


def test_rank_watchlist_pending_held_still_last():
    rows = [_row("ZZZZ", 0, has_data=False, is_held=True), _row("AAPL", 0.1)]
    ranked = rank_watchlist(rows)
    assert [r.symbol for r in ranked] == ["AAPL", "ZZZZ"]
