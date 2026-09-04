"""
Turns raw snapshot history into the baselines the scoring engine needs
(20-day average volume, 20-day return volatility, 52-week range,
50- and 200-day simple moving averages).

Volatility and average volume are computed from **daily** bars — the last
snapshot of each UTC calendar day — not from consecutive poll ticks. Hot
symbols refresh every 15s; tick-to-tick returns have tiny stdev, which
would make any real daily move look like 10x usual.

52-week high/low from poll history is only trusted once we actually have
~a year of daily bars. Until then the poller should use the provider's
52-week range (Yahoo sends it on every chart response) or leave it blank
so scoring does not fire a fake "new 52-week high" on the first fetch.

DMA is the same honesty rule: do not call 10 closes a 50-day average.
"""
import datetime as dt
import statistics
from dataclasses import dataclass
from typing import List, Optional

from app.models import QuoteSnapshot

# Don't label a handful of poll ticks as a 52-week range. ~300 calendar
# days is enough to be in the right ballpark if a provider never sent one.
MIN_CALENDAR_DAYS_FOR_52W = 300
DMA_50_WINDOW = 50
DMA_200_WINDOW = 200


@dataclass
class SymbolBaseline:
    avg_volume_20d: Optional[float] = None
    volatility_20d_pct: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    dma_50: Optional[float] = None
    dma_200: Optional[float] = None


def daily_bars(history: List[QuoteSnapshot]) -> List[QuoteSnapshot]:
    """Keep the last snapshot per UTC calendar day. `history` should be
    oldest -> newest so the last write for a day wins."""
    by_day: dict[dt.date, QuoteSnapshot] = {}
    for snap in history:
        if snap.fetched_at is None or snap.price is None:
            continue
        by_day[snap.fetched_at.date()] = snap
    return [by_day[day] for day in sorted(by_day)]


def _sma(prices: List[float], window: int) -> Optional[float]:
    if len(prices) < window:
        return None
    return statistics.mean(prices[-window:])


def compute_baseline(history: List[QuoteSnapshot]) -> SymbolBaseline:
    """`history` should be ordered oldest -> newest. Intraday polls are
    collapsed to one bar per day before volume/volatility/range/DMA."""
    daily = daily_bars(history)
    if not daily:
        return SymbolBaseline()

    volumes = [h.volume for h in daily if h.volume]
    avg_volume_20d = statistics.mean(volumes[-20:]) if volumes else None

    prices = [h.price for h in daily if h.price]
    returns_pct = []
    for prev, curr in zip(prices, prices[1:]):
        if prev:
            returns_pct.append((curr - prev) / prev * 100)
    volatility_20d_pct = (
        statistics.pstdev(returns_pct[-20:]) if len(returns_pct) >= 3 else None
    )

    high_52w = None
    low_52w = None
    span_days = (daily[-1].fetched_at.date() - daily[0].fetched_at.date()).days
    if span_days >= MIN_CALENDAR_DAYS_FOR_52W:
        high_52w = max(h.day_high or h.price for h in daily)
        low_52w = min(h.day_low or h.price for h in daily)

    return SymbolBaseline(
        avg_volume_20d=avg_volume_20d,
        volatility_20d_pct=volatility_20d_pct,
        high_52w=high_52w,
        low_52w=low_52w,
        dma_50=_sma(prices, DMA_50_WINDOW),
        dma_200=_sma(prices, DMA_200_WINDOW),
    )
