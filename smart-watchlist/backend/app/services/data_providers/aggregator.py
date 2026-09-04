"""
This is where "handle stale, delayed or conflicting data" actually lives.

Strategy, deliberately kept simple and explainable rather than clever:
  1. Query every configured provider for the symbol (currently 2 — cheap
     enough, and having both readings is what lets us detect conflicts
     instead of just trusting whichever answered).
  2. If none respond, raise — callers must not silently serve nothing as
     something.
  3. If only one responds, use it, tagged with its own source.
  4. If more than one responds, prefer the highest-priority source's
     price, but compare it against the others: if they disagree by more
     than CONFLICT_THRESHOLD_PCT, flag the reading as a conflict so
     downstream consumers (and the UI) can show reduced confidence
     instead of pretending the number is exact.
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional

from app.config import PROVIDER_PRIORITY, STALE_AFTER_SECONDS
from .base import QuoteProvider, RawQuote, QuoteProviderError
from .yahoo import YahooProvider
from .stooq import StooqProvider

CONFLICT_THRESHOLD_PCT = 1.5  # disagreement beyond this between sources gets flagged


@dataclass
class ReconciledQuote:
    quote: RawQuote
    sources_tried: List[str]
    sources_succeeded: List[str]
    flagged_conflict: bool
    is_stale: bool


def build_default_providers() -> List[QuoteProvider]:
    registry = {"yahoo": YahooProvider, "stooq": StooqProvider}
    return [registry[name]() for name in PROVIDER_PRIORITY if name in registry]


class QuoteAggregator:
    def __init__(self, providers: Optional[List[QuoteProvider]] = None):
        self.providers = providers or build_default_providers()

    def fetch(self, symbol: str) -> ReconciledQuote:
        results: dict[str, RawQuote] = {}
        tried: List[str] = [provider.name for provider in self.providers]

        def _fetch_one(provider: QuoteProvider):
            return provider.name, provider.fetch(symbol)

        if self.providers:
            workers = min(len(self.providers), 4)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(_fetch_one, provider) for provider in self.providers]
                for fut in futs:
                    try:
                        name, quote = fut.result()
                        results[name] = quote
                    except QuoteProviderError:
                        continue  # a single provider failing is expected/routine, not fatal

        if not results:
            raise QuoteProviderError(
                f"all providers failed for {symbol} (tried: {', '.join(tried)})"
            )

        # Prefer providers in configured priority order.
        primary_name = next((p for p in PROVIDER_PRIORITY if p in results), None)
        primary = results[primary_name]

        flagged_conflict = False
        for name, other in results.items():
            if name == primary_name:
                continue
            if primary.price and other.price:
                diff_pct = abs(primary.price - other.price) / primary.price * 100
                if diff_pct > CONFLICT_THRESHOLD_PCT:
                    flagged_conflict = True

        age = (dt.datetime.utcnow() - primary.fetched_at).total_seconds()
        is_stale = age > STALE_AFTER_SECONDS

        return ReconciledQuote(
            quote=primary,
            sources_tried=tried,
            sources_succeeded=list(results.keys()),
            flagged_conflict=flagged_conflict,
            is_stale=is_stale,
        )
