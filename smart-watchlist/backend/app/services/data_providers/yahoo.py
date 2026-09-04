"""
Primary quote source: Yahoo Finance's public chart endpoint. No API key
required. This is an unofficial/undocumented endpoint, which is exactly
why the app treats it as one interchangeable provider behind an
abstraction rather than something core logic depends on directly.
"""
import datetime as dt

import requests

from .base import QuoteProvider, RawQuote, QuoteProviderError

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


def _optional_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _unix_to_dt(value):
    """Yahoo chart meta stores earnings/dividend as unix seconds, sometimes
    nested in a list or {raw: N} quoteSummary shape."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("raw")
    if isinstance(value, list):
        value = value[0] if value else None
        if isinstance(value, dict):
            value = value.get("raw")
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return dt.datetime.utcfromtimestamp(ts)


def _earnings_from_meta(meta: dict):
    return (
        _unix_to_dt(meta.get("earningsTimestampStart"))
        or _unix_to_dt(meta.get("earningsTimestamp"))
        or _unix_to_dt(meta.get("earningsTimestampEnd"))
    )


class YahooProvider(QuoteProvider):
    name = "yahoo"

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    def fetch(self, symbol: str) -> RawQuote:
        data = self._get_chart(symbol, range_="1d", interval="1d")
        return self._parse(symbol, data)

    def fetch_daily_history(self, symbol: str, range_: str = "1y") -> list[RawQuote]:
        """One request of daily bars so scoring has real 20-day vol/volume
        and enough closes for 50- and 200-day averages on first add."""
        data = self._get_chart(symbol, range_=range_, interval="1d")
        return self._parse_daily_bars(symbol, data)

    def _get_chart(self, symbol: str, range_: str, interval: str) -> dict:
        try:
            resp = requests.get(
                CHART_URL.format(symbol=symbol),
                params={"interval": interval, "range": range_},
                headers={"User-Agent": "Mozilla/5.0 (smart-watchlist)"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            raise QuoteProviderError(f"yahoo: request failed for {symbol}: {e}") from e

    @staticmethod
    def _parse(symbol: str, data: dict) -> RawQuote:
        try:
            result = data["chart"]["result"][0]
            meta = result["meta"]
            price = meta.get("regularMarketPrice")
            if price is None:
                raise KeyError("regularMarketPrice")

            quote_block = result.get("indicators", {}).get("quote", [{}])[0]
            volumes = [v for v in quote_block.get("volume", []) if v is not None]
            highs = [v for v in quote_block.get("high", []) if v is not None]
            lows = [v for v in quote_block.get("low", []) if v is not None]
            opens = [v for v in quote_block.get("open", []) if v is not None]

            return RawQuote(
                symbol=symbol,
                source="yahoo",
                price=float(price),
                prev_close=meta.get("chartPreviousClose") or meta.get("previousClose"),
                day_open=opens[0] if opens else meta.get("regularMarketOpen"),
                day_high=max(highs) if highs else meta.get("regularMarketDayHigh"),
                day_low=min(lows) if lows else meta.get("regularMarketDayLow"),
                volume=sum(volumes) if volumes else meta.get("regularMarketVolume"),
                # Chart meta includes the real 52-week range even when we only
                # asked for range=1d. Scoring must not invent this from a few polls.
                high_52w=_optional_float(meta.get("fiftyTwoWeekHigh")),
                low_52w=_optional_float(meta.get("fiftyTwoWeekLow")),
                earnings_at=_earnings_from_meta(meta),
                ex_dividend_at=_unix_to_dt(meta.get("dividendDate")),
                fetched_at=_unix_to_dt(meta.get("regularMarketTime")) or dt.datetime.utcnow(),
            )
        except (KeyError, IndexError, TypeError) as e:
            raise QuoteProviderError(f"yahoo: unexpected response shape for {symbol}: {e}") from e

    @staticmethod
    def _parse_daily_bars(symbol: str, data: dict) -> list[RawQuote]:
        try:
            result = data["chart"]["result"][0]
            timestamps = result.get("timestamp") or []
            quote_block = result.get("indicators", {}).get("quote", [{}])[0]
            opens = quote_block.get("open") or []
            highs = quote_block.get("high") or []
            lows = quote_block.get("low") or []
            closes = quote_block.get("close") or []
            volumes = quote_block.get("volume") or []
        except (KeyError, IndexError, TypeError) as e:
            raise QuoteProviderError(f"yahoo: unexpected history shape for {symbol}: {e}") from e

        bars: list[RawQuote] = []
        prev_close = None
        for i, ts in enumerate(timestamps):
            if i >= len(closes) or closes[i] is None:
                continue
            close = float(closes[i])
            bars.append(RawQuote(
                symbol=symbol,
                source="yahoo",
                price=close,
                prev_close=prev_close,
                day_open=_optional_float(opens[i] if i < len(opens) else None),
                day_high=_optional_float(highs[i] if i < len(highs) else None),
                day_low=_optional_float(lows[i] if i < len(lows) else None),
                volume=_optional_float(volumes[i] if i < len(volumes) else None),
                fetched_at=dt.datetime.utcfromtimestamp(int(ts)),
            ))
            prev_close = close

        if not bars:
            raise QuoteProviderError(f"yahoo: no daily bars for {symbol}")
        return bars
