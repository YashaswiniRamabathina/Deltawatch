"""Ticker normalization shared by the API and the Stooq adapter."""
import re

# Yahoo listing suffixes for Indian exchanges. Stooq does not cover
# individual NSE/BSE names, so these must not be rewritten to `.us`.
INDIA_YAHOO_SUFFIXES = (".NS", ".BO")

# Letters, digits, dot, hyphen. Covers AAPL, BRK-B, RELIANCE.NS.
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


class SymbolError(ValueError):
    pass


def normalize_symbol(raw: str) -> str:
    symbol = (raw or "").strip().upper()
    if not symbol:
        raise SymbolError("Symbol cannot be empty")
    if not _SYMBOL_RE.match(symbol):
        raise SymbolError("Use a ticker like AAPL or RELIANCE.NS")
    return symbol


def is_india_listing(symbol: str) -> bool:
    upper = symbol.upper()
    return any(upper.endswith(suffix) for suffix in INDIA_YAHOO_SUFFIXES)
