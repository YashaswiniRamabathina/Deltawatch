import datetime as dt

from app.services.scoring import (
    score_symbol,
    is_meaningful,
    score_personal_delta,
    should_surface_calendar,
    MEANINGFUL_THRESHOLD,
)


def test_flat_day_scores_low_with_no_baseline():
    r = score_symbol(price=101.0, prev_close=100.0)  # +1%, no history at all
    assert not is_meaningful(r.score)
    assert r.reasons == []


def test_large_move_without_baseline_falls_back_to_flat_threshold():
    r = score_symbol(price=105.0, prev_close=100.0)  # +5%, no volatility baseline yet
    assert r.score > 0
    assert any("5.0%" in reason for reason in r.reasons)


def test_normal_move_for_volatile_stock_is_not_flagged():
    # A stock that normally swings 4%/day moving 3% is unremarkable for it.
    r = score_symbol(price=103.0, prev_close=100.0, volatility_20d_pct=4.0)
    assert not is_meaningful(r.score)


def test_unusual_move_for_calm_stock_is_flagged():
    # Same 3% move, but this stock normally only moves 0.5%/day.
    r = score_symbol(price=103.0, prev_close=100.0, volatility_20d_pct=0.5)
    assert is_meaningful(r.score)
    assert any("x its usual daily move" in reason for reason in r.reasons)


def test_volume_spike_contributes_even_without_big_price_move():
    r = score_symbol(price=100.5, prev_close=100.0, volume=5_000_000, avg_volume_20d=1_000_000)
    assert any("average volume" in reason for reason in r.reasons)


def test_52_week_signal_silent_when_range_unknown():
    # Price sitting on today's high must not invent a 52-week breakout.
    r = score_symbol(price=150.0, prev_close=149.0, high_52w=None, low_52w=None)
    assert "new 52-week high" not in r.reasons
    assert "new 52-week low" not in r.reasons
    r = score_symbol(price=150.0, prev_close=149.0, high_52w=150.0)
    assert is_meaningful(r.score)
    assert "new 52-week high" in r.reasons


def test_52_week_low_breach_flagged():
    r = score_symbol(price=49.9, prev_close=50.5, low_52w=50.0)
    assert "new 52-week low" in r.reasons


def test_opening_gap_flagged():
    r = score_symbol(price=101.0, prev_close=100.0, day_open=97.5)  # gapped down 2.5% then recovered
    assert any("gapped down" in reason for reason in r.reasons)


def test_missing_prev_close_does_not_crash():
    r = score_symbol(price=100.0, prev_close=None)
    assert r.score == 0
    assert r.reasons == []


def test_multiple_confirming_signals_stack_score_higher_than_any_alone():
    combo = score_symbol(
        price=110.0, prev_close=100.0, day_open=108.0,
        volume=4_000_000, avg_volume_20d=1_000_000,
        volatility_20d_pct=1.5, high_52w=110.0,
    )
    price_only = score_symbol(price=110.0, prev_close=100.0, volatility_20d_pct=1.5)
    assert combo.score > price_only.score


def test_personal_delta_triggers_even_when_daily_move_is_normal():
    # User hasn't checked in a while; price crept up 10% since their last visit,
    # even if today's single-day move alone wasn't unusual.
    reason = score_personal_delta(current_price=110.0, last_seen_price=100.0, volatility_20d_pct=1.0)
    assert reason is not None
    assert "since you last checked" in reason


def test_personal_delta_silent_when_price_barely_moved():
    reason = score_personal_delta(current_price=100.3, last_seen_price=100.0, volatility_20d_pct=1.0)
    assert reason is None


def test_personal_delta_silent_with_no_prior_visit():
    reason = score_personal_delta(current_price=110.0, last_seen_price=None, volatility_20d_pct=1.0)
    assert reason is None


NOW = dt.datetime(2026, 9, 4, 12, 0, 0)


def test_earnings_in_three_days_clears_the_bar():
    when = NOW + dt.timedelta(days=3)
    r = score_symbol(price=100.0, prev_close=100.0, earnings_at=when, now=NOW)
    assert is_meaningful(r.score)
    assert r.score >= MEANINGFUL_THRESHOLD
    assert any("results due" in reason for reason in r.reasons)


def test_earnings_a_month_out_is_silent():
    when = NOW + dt.timedelta(days=30)
    r = score_symbol(price=100.0, prev_close=100.0, earnings_at=when, now=NOW)
    assert r.reasons == []
    assert not is_meaningful(r.score)


def test_past_earnings_is_silent():
    when = NOW - dt.timedelta(hours=6)
    r = score_symbol(price=100.0, prev_close=100.0, earnings_at=when, now=NOW)
    assert r.reasons == []


def test_ex_dividend_later_this_week_uses_groww_style_copy():
    when = NOW + dt.timedelta(days=4)
    r = score_symbol(price=100.0, prev_close=100.0, ex_dividend_at=when, now=NOW)
    assert is_meaningful(r.score)
    assert "ex-dividend this week" in r.reasons


def test_surface_calendar_skips_just_added_symbol():
    event = NOW + dt.timedelta(days=3)
    assert not should_surface_calendar(event, last_seen_at=NOW, now=NOW)


def test_surface_calendar_after_being_away_ten_days():
    event = NOW + dt.timedelta(days=3)
    last_seen = NOW - dt.timedelta(days=10)
    assert should_surface_calendar(event, last_seen_at=last_seen, now=NOW)


def test_surface_calendar_with_no_last_seen():
    event = NOW + dt.timedelta(days=3)
    assert should_surface_calendar(event, last_seen_at=None, now=NOW)


def test_dma_cross_above_50_clears_the_bar():
    r = score_symbol(price=101.0, prev_close=99.0, dma_50=100.0)
    assert is_meaningful(r.score)
    assert "crossed above 50-day average" in r.reasons


def test_sitting_above_dma_is_not_an_event():
    r = score_symbol(price=101.0, prev_close=100.5, dma_50=100.0)
    assert not any("day average" in reason for reason in r.reasons)


def test_dma_silent_when_average_unknown():
    r = score_symbol(price=101.0, prev_close=99.0)
    assert not any("day average" in reason for reason in r.reasons)


def test_dma_200_cross_below_clears_the_bar():
    r = score_symbol(price=99.0, prev_close=101.0, dma_200=100.0)
    assert is_meaningful(r.score)
    assert "crossed below 200-day average" in r.reasons


def test_dma_needs_prev_close_to_call_it_a_cross():
    r = score_symbol(price=101.0, prev_close=None, dma_50=100.0)
    assert r.reasons == []
