"""
These tests exercise the exact parsing code paths (YahooProvider._parse,
StooqProvider._parse) against realistic fixture payloads shaped like the
real endpoints, without making a live network call. This sandbox's
network egress is locked to package registries, so live calls can't be
verified from here — run `pytest -k live` manually against the real
internet to confirm connectivity once you have it (see README).
"""
import datetime as dt

import pytest

from app.services.data_providers.yahoo import YahooProvider
from app.services.data_providers.stooq import StooqProvider
from app.services.data_providers.base import QuoteProviderError


YAHOO_FIXTURE = {
    "chart": {
        "result": [{
            "meta": {
                "symbol": "AAPL",
                "regularMarketPrice": 227.52,
                "chartPreviousClose": 225.12,
                "regularMarketVolume": 48_000_000,
                "regularMarketDayHigh": 228.10,
                "regularMarketDayLow": 225.80,
                "regularMarketOpen": 226.00,
                "fiftyTwoWeekHigh": 260.10,
                "fiftyTwoWeekLow": 164.08,
                "regularMarketTime": 1756933200,
            },
            "indicators": {
                "quote": [{
                    "volume": [48_000_000],
                    "high": [228.10],
                    "low": [225.80],
                    "open": [226.00],
                }]
            },
        }],
        "error": None,
    }
}

YAHOO_MALFORMED = {"chart": {"result": [{"meta": {}}]}}

STOOQ_CSV = "Symbol,Date,Time,Open,High,Low,Close,Volume\naapl.us,2026-09-03,21:00:00,226.00,228.10,225.80,227.52,48000000\n"
STOOQ_CSV_UNKNOWN_SYMBOL = "Symbol,Date,Time,Open,High,Low,Close,Volume\nzzzz.us,N/D,N/D,N/D,N/D,N/D,N/D,N/D\n"


def test_yahoo_parses_well_formed_response():
    q = YahooProvider._parse("AAPL", YAHOO_FIXTURE)
    assert q.symbol == "AAPL"
    assert q.source == "yahoo"
    assert q.price == 227.52
    assert q.prev_close == 225.12
    assert q.volume == 48_000_000
    assert q.day_high == 228.10
    assert q.day_low == 225.80
    assert q.high_52w == 260.10
    assert q.low_52w == 164.08
    assert q.earnings_at is None
    assert q.ex_dividend_at is None
    assert q.fetched_at == dt.datetime.utcfromtimestamp(1756933200)


def test_yahoo_omits_52w_when_meta_lacks_it():
    data = {
        "chart": {
            "result": [{
                "meta": {"regularMarketPrice": 227.52},
                "indicators": {"quote": [{}]},
            }],
        }
    }
    q = YahooProvider._parse("AAPL", data)
    assert q.high_52w is None
    assert q.low_52w is None


def test_yahoo_parses_earnings_and_dividend_from_chart_meta():
    earn_ts = 1757520000
    div_ts = 1757606400
    data = {
        "chart": {
            "result": [{
                "meta": {
                    "regularMarketPrice": 227.52,
                    "earningsTimestampStart": earn_ts,
                    "earningsTimestamp": earn_ts - 3600,
                    "dividendDate": [div_ts],
                },
                "indicators": {"quote": [{}]},
            }],
        }
    }
    q = YahooProvider._parse("AAPL", data)
    assert q.earnings_at == dt.datetime.utcfromtimestamp(earn_ts)
    assert q.ex_dividend_at == dt.datetime.utcfromtimestamp(div_ts)


def test_yahoo_parses_calendar_raw_dict_shape():
    from app.services.data_providers.yahoo import _unix_to_dt
    ts = 1757520000
    assert _unix_to_dt({"raw": ts}) == dt.datetime.utcfromtimestamp(ts)
    assert _unix_to_dt(None) is None
    assert _unix_to_dt(0) is None


def test_yahoo_parses_daily_history_skipping_null_closes():
    data = {
        "chart": {
            "result": [{
                "timestamp": [1693526400, 1693612800, 1693699200],
                "indicators": {
                    "quote": [{
                        "open": [100.0, 101.0, None],
                        "high": [102.0, 103.0, None],
                        "low": [99.0, 100.0, None],
                        "close": [101.0, 102.5, None],
                        "volume": [1_000_000, 1_100_000, None],
                    }]
                },
            }]
        }
    }
    bars = YahooProvider._parse_daily_bars("AAPL", data)
    assert len(bars) == 2
    assert bars[0].price == 101.0
    assert bars[0].prev_close is None
    assert bars[1].price == 102.5
    assert bars[1].prev_close == 101.0
    assert bars[1].volume == 1_100_000


def test_yahoo_history_raises_when_empty():
    data = {"chart": {"result": [{"timestamp": [], "indicators": {"quote": [{}]}}]}}
    with pytest.raises(QuoteProviderError, match="no daily bars"):
        YahooProvider._parse_daily_bars("AAPL", data)


def test_yahoo_raises_provider_error_on_malformed_response():
    with pytest.raises(QuoteProviderError):
        YahooProvider._parse("AAPL", YAHOO_MALFORMED)


def test_stooq_parses_well_formed_csv():
    q = StooqProvider._parse("AAPL", STOOQ_CSV)
    assert q.source == "stooq"
    assert q.price == 227.52
    assert q.volume == 48_000_000.0
    assert q.prev_close is None  # stooq's free endpoint doesn't provide this
    assert q.fetched_at == dt.datetime(2026, 9, 3, 21, 0, 0)


def test_stooq_raises_on_unknown_symbol():
    with pytest.raises(QuoteProviderError):
        StooqProvider._parse("ZZZZ", STOOQ_CSV_UNKNOWN_SYMBOL)


def test_stooq_skips_indian_listings_without_a_network_call():
    with pytest.raises(QuoteProviderError, match="no coverage"):
        StooqProvider().fetch("RELIANCE.NS")


def test_stooq_symbol_suffixing():
    from app.services.data_providers.stooq import _to_stooq_symbol
    assert _to_stooq_symbol("AAPL") == "aapl.us"  # bare US ticker gets .us appended
    assert _to_stooq_symbol("RELIANCE.NS") == "reliance.ns"  # already-suffixed symbols pass through untouched
