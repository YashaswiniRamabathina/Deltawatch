import datetime as dt

from app.services.data_providers.aggregator import QuoteAggregator
from app.services.data_providers.base import QuoteProvider, RawQuote, QuoteProviderError


class FakeProvider(QuoteProvider):
    def __init__(self, name, price=None, fail=False, age_seconds=0):
        self.name = name
        self._price = price
        self._fail = fail
        self._age_seconds = age_seconds

    def fetch(self, symbol: str) -> RawQuote:
        if self._fail:
            raise QuoteProviderError(f"{self.name} is down")
        return RawQuote(
            symbol=symbol,
            source=self.name,
            price=self._price,
            prev_close=self._price * 0.99,
            fetched_at=dt.datetime.utcnow() - dt.timedelta(seconds=self._age_seconds),
        )


def test_uses_primary_when_all_agree():
    agg = QuoteAggregator([FakeProvider("yahoo", price=100.0), FakeProvider("stooq", price=100.05)])
    result = agg.fetch("AAPL")
    assert result.quote.source == "yahoo"
    assert not result.flagged_conflict


def test_flags_conflict_when_sources_disagree_significantly():
    agg = QuoteAggregator([FakeProvider("yahoo", price=100.0), FakeProvider("stooq", price=105.0)])
    result = agg.fetch("AAPL")
    assert result.flagged_conflict is True
    assert result.quote.source == "yahoo"  # still prefers priority order even when flagging


def test_falls_back_when_primary_fails():
    agg = QuoteAggregator([FakeProvider("yahoo", fail=True), FakeProvider("stooq", price=100.0)])
    result = agg.fetch("AAPL")
    assert result.quote.source == "stooq"
    assert result.sources_succeeded == ["stooq"]


def test_raises_when_every_provider_fails():
    agg = QuoteAggregator([FakeProvider("yahoo", fail=True), FakeProvider("stooq", fail=True)])
    try:
        agg.fetch("AAPL")
        assert False, "expected QuoteProviderError"
    except QuoteProviderError:
        pass


def test_marks_stale_when_data_is_old():
    agg = QuoteAggregator([FakeProvider("yahoo", price=100.0, age_seconds=999)])
    result = agg.fetch("AAPL")
    assert result.is_stale is True


def test_not_stale_when_data_is_fresh():
    agg = QuoteAggregator([FakeProvider("yahoo", price=100.0, age_seconds=1)])
    result = agg.fetch("AAPL")
    assert result.is_stale is False
