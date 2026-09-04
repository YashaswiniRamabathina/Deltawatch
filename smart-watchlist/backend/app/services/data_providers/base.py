"""
Provider interface. Every market data source (Yahoo, Stooq, a future paid
API) implements this same shape, so the aggregator and the rest of the app
never know or care which upstream actually answered.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import datetime as dt


@dataclass
class RawQuote:
    symbol: str
    source: str
    price: float
    prev_close: Optional[float] = None
    day_open: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    volume: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    earnings_at: Optional[dt.datetime] = None
    ex_dividend_at: Optional[dt.datetime] = None
    fetched_at: dt.datetime = None

    def __post_init__(self):
        if self.fetched_at is None:
            self.fetched_at = dt.datetime.utcnow()


class QuoteProviderError(Exception):
    """Raised when a provider fails, times out, or returns unusable data.
    Deliberately a distinct type so the aggregator can catch it without
    swallowing programming errors."""


class QuoteProvider(ABC):
    name: str

    @abstractmethod
    def fetch(self, symbol: str) -> RawQuote:
        """Fetch a single quote. Must raise QuoteProviderError on any
        failure (network, bad symbol, malformed response) rather than
        returning partial/garbage data."""
        raise NotImplementedError
