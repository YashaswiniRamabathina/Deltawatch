import datetime as dt
import statistics

from app.models import QuoteSnapshot
from app.services.stats import (
    DMA_50_WINDOW,
    DMA_200_WINDOW,
    MIN_CALENDAR_DAYS_FOR_52W,
    compute_baseline,
    daily_bars,
)


def _snap(price, when, volume=1_000_000.0, day_high=None, day_low=None):
    return QuoteSnapshot(
        symbol="AAPL",
        source="yahoo",
        price=price,
        volume=volume,
        day_high=day_high if day_high is not None else price,
        day_low=day_low if day_low is not None else price,
        fetched_at=when,
    )


def test_daily_bars_keep_last_snapshot_per_utc_day():
    day = dt.datetime(2026, 9, 3, 14, 0, 0)
    history = [
        _snap(100.0, day),
        _snap(101.0, day + dt.timedelta(hours=1)),
        _snap(102.0, day + dt.timedelta(hours=2)),
        _snap(110.0, day + dt.timedelta(days=1)),
    ]
    bars = daily_bars(history)
    assert [round(b.price, 1) for b in bars] == [102.0, 110.0]


def test_intraday_ticks_do_not_produce_a_volatility_reading():
    """20 noisy ticks on one day collapse to a single bar — not enough
    daily returns to compute stdev, so scoring falls back to the flat 3%."""
    start = dt.datetime(2026, 9, 4, 14, 0, 0)
    history = [
        _snap(100.0 + (i % 3) * 0.02, start + dt.timedelta(seconds=15 * i))
        for i in range(20)
    ]
    baseline = compute_baseline(history)
    assert baseline.volatility_20d_pct is None
    assert baseline.high_52w is None
    assert baseline.low_52w is None


def test_volatility_uses_daily_closes_not_tick_noise():
    # Six trading days with real daily moves. Each day also has intra-day
    # wiggle that would collapse stdev if we used tick-to-tick returns.
    closes = [100.0, 104.0, 98.0, 102.0, 101.0, 105.0]
    history = []
    origin = dt.datetime(2026, 8, 24, 20, 0, 0)
    for i, close in enumerate(closes):
        day = origin + dt.timedelta(days=i)
        history.append(_snap(close - 0.3, day))
        history.append(_snap(close + 0.2, day + dt.timedelta(hours=1)))
        history.append(_snap(close, day + dt.timedelta(hours=2), volume=2_000_000 + i))

    baseline = compute_baseline(history)
    returns = [
        (curr - prev) / prev * 100
        for prev, curr in zip(closes, closes[1:])
    ]
    assert baseline.volatility_20d_pct == statistics.pstdev(returns)
    # last 20 daily volumes — we have 6 days, last snapshot of each day
    assert baseline.avg_volume_20d == statistics.mean(
        [2_000_000 + i for i in range(6)]
    )


def test_thin_history_does_not_claim_a_52_week_range():
    origin = dt.datetime(2026, 8, 1, 20, 0, 0)
    history = [_snap(100 + i, origin + dt.timedelta(days=i), day_high=110 + i) for i in range(14)]
    baseline = compute_baseline(history)
    assert baseline.high_52w is None
    assert baseline.low_52w is None


def test_long_history_can_supply_52_week_range():
    origin = dt.datetime(2025, 11, 1, 20, 0, 0)
    n = MIN_CALENDAR_DAYS_FOR_52W + 1
    history = []
    for i in range(n):
        price = 50.0 + (i % 7)
        history.append(
            _snap(
                price,
                origin + dt.timedelta(days=i),
                day_high=price + 1,
                day_low=price - 1,
            )
        )
    baseline = compute_baseline(history)
    assert baseline.high_52w == max(h.day_high for h in history)
    assert baseline.low_52w == min(h.day_low for h in history)


def test_dma_50_silent_until_fifty_daily_closes():
    origin = dt.datetime(2026, 1, 1, 20, 0, 0)
    short = [_snap(100.0, origin + dt.timedelta(days=i)) for i in range(DMA_50_WINDOW - 1)]
    assert compute_baseline(short).dma_50 is None
    full = short + [_snap(150.0, origin + dt.timedelta(days=DMA_50_WINDOW - 1))]
    expected = statistics.mean([100.0] * (DMA_50_WINDOW - 1) + [150.0])
    assert compute_baseline(full).dma_50 == expected
    assert compute_baseline(full).dma_200 is None


def test_dma_200_silent_until_two_hundred_daily_closes():
    origin = dt.datetime(2025, 1, 1, 20, 0, 0)
    prices = [10.0 + (i % 5) for i in range(DMA_200_WINDOW)]
    almost = [_snap(prices[i], origin + dt.timedelta(days=i)) for i in range(DMA_200_WINDOW - 1)]
    assert compute_baseline(almost).dma_200 is None
    full = almost + [_snap(prices[-1], origin + dt.timedelta(days=DMA_200_WINDOW - 1))]
    baseline = compute_baseline(full)
    assert baseline.dma_200 == statistics.mean(prices)
    assert baseline.dma_50 == statistics.mean(prices[-DMA_50_WINDOW:])
