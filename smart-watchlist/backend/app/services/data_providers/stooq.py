"""
Fallback quote source: Stooq's free, keyless CSV endpoint. Independent of
Yahoo (different upstream entirely), which is what makes it useful both
as a failover *and* as a cross-check for conflict detection.
"""
import csv
import datetime as dt
import io

import requests

from .base import QuoteProvider, RawQuote, QuoteProviderError
from app.services.symbols import is_india_listing

QUOTE_URL = "https://stooq.com/q/l/"


def _stooq_quote_time(row: dict) -> dt.datetime:
    """Stooq Date+Time is the exchange clock, not when we downloaded the CSV."""
    date_s = (row.get("Date") or "").strip()
    time_s = (row.get("Time") or "").strip()
    if date_s in ("", "N/D"):
        return dt.datetime.utcnow()
    try:
        if time_s in ("", "N/D"):
            return dt.datetime.strptime(date_s, "%Y-%m-%d")
        return dt.datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return dt.datetime.utcnow()


def _to_stooq_symbol(symbol: str) -> str:
    # Stooq expects US tickers suffixed with `.us` (e.g. aapl.us).
    # Dotted suffixes stay as-is so RELIANCE.NS is not rewritten to RELIANCE.us.
    if "." in symbol:
        return symbol.lower()
    return f"{symbol.lower()}.us"


class StooqProvider(QuoteProvider):
    name = "stooq"

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    def fetch(self, symbol: str) -> RawQuote:
        if is_india_listing(symbol):
            raise QuoteProviderError(
                f"stooq: no coverage for Indian listing {symbol}"
            )
        try:
            resp = requests.get(
                QUOTE_URL,
                params={"s": _to_stooq_symbol(symbol), "f": "sd2t2ohlcv", "h": "", "e": "csv"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            raise QuoteProviderError(f"stooq: request failed for {symbol}: {e}") from e

        return self._parse(symbol, resp.text)

    @staticmethod
    def _parse(symbol: str, csv_text: str) -> RawQuote:
        reader = csv.DictReader(io.StringIO(csv_text))
        try:
            row = next(reader)
        except StopIteration as e:
            raise QuoteProviderError(f"stooq: empty response for {symbol}") from e

        close = row.get("Close")
        if close in (None, "", "N/D"):
            raise QuoteProviderError(f"stooq: no data for {symbol} (unknown symbol or market closed)")

        try:
            return RawQuote(
                symbol=symbol,
                source="stooq",
                price=float(close),
                day_open=float(row["Open"]) if row.get("Open") not in (None, "", "N/D") else None,
                day_high=float(row["High"]) if row.get("High") not in (None, "", "N/D") else None,
                day_low=float(row["Low"]) if row.get("Low") not in (None, "", "N/D") else None,
                volume=float(row["Volume"]) if row.get("Volume") not in (None, "", "N/D") else None,
                # Stooq's free endpoint doesn't return previous close directly;
                # the aggregator fills this from our own snapshot history instead.
                prev_close=None,
                fetched_at=_stooq_quote_time(row),
            )
        except (KeyError, ValueError) as e:
            raise QuoteProviderError(f"stooq: unexpected response shape for {symbol}: {e}") from e
