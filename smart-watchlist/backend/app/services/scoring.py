"""
The scoring engine is the actual product idea of this app: a single
number (and a plain-English explanation) for "does this symbol deserve
this user's attention right now".

Deliberately NOT just `abs(% change) > threshold%`. A flat percentage
threshold treats a sleepy utility stock and a volatile small-cap the same,
and it can't tell a routine drift from a structural event. Instead we
combine six independent, cheap-to-compute signals:

  1. Volatility-normalized move   — how unusual is today's move FOR THIS
                                     STOCK specifically (z-score vs its own
                                     trailing daily volatility)?
  2. Volume anomaly                — is this move backed by unusual
                                     participation, or thin/noisy trading?
  3. 52-week high/low breach       — a structural level, independent of
                                     today's percentage move.
  4. Opening gap                   — did the move happen instantly at the
                                     open (news-driven) vs. drift intraday?
  5. Calendar                      — results or ex-dividend in the next week,
                                     independent of today's price move.
  6. DMA cross                     — price crossed the 50- or 200-day average
                                     (Groww's DMA alert, as a last-seen event).

Each contributes an independent 0..~3 point score; they're summed, not
averaged, because multiple confirming signals (big move + high volume +
new high) should rank above any single signal alone. This keeps the model
inspectable: every point on the score traces to one plain-English reason,
which is what lets the UI show *why* something surfaced instead of a bare
number nobody trusts.
"""
import datetime as dt
from dataclasses import dataclass, field
from typing import List, Optional


MEANINGFUL_THRESHOLD = 2.5  # score at/above this is surfaced in the digest
CALENDAR_WINDOW_DAYS = 7


@dataclass
class ScoreResult:
    score: float
    reasons: List[str] = field(default_factory=list)


def _pct(a: float, b: float) -> Optional[float]:
    """% change of a relative to b, or None if b is unusable."""
    if b in (None, 0):
        return None
    return (a - b) / b * 100


def _fmt_event_when(when: dt.datetime, now: dt.datetime) -> str:
    days = (when.date() - now.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return when.strftime("%a %d %b")


def event_is_upcoming(when: Optional[dt.datetime], now: Optional[dt.datetime] = None) -> bool:
    if when is None:
        return False
    now = now or dt.datetime.utcnow()
    return now <= when <= now + dt.timedelta(days=CALENDAR_WINDOW_DAYS)


def should_surface_calendar(
    event_at: Optional[dt.datetime],
    last_seen_at: Optional[dt.datetime],
    now: Optional[dt.datetime] = None,
) -> bool:
    """Personal digest rule for a known-soon event.

    Show only if the event is still ahead in the next week, and the user
    last looked *before* that week started. Adding a symbol (last_seen=now)
    therefore does not dump already-known Friday results; being away 10
    days still surfaces them.
    """
    now = now or dt.datetime.utcnow()
    if not event_is_upcoming(event_at, now):
        return False
    if last_seen_at is None:
        return True
    return last_seen_at < event_at - dt.timedelta(days=CALENDAR_WINDOW_DAYS)


def score_calendar_events(
    earnings_at: Optional[dt.datetime] = None,
    ex_dividend_at: Optional[dt.datetime] = None,
    now: Optional[dt.datetime] = None,
) -> ScoreResult:
    """Upcoming results / ex-div in the next week is itself attention-worthy,
    even if price has not moved yet."""
    now = now or dt.datetime.utcnow()
    reasons: List[str] = []
    score = 0.0
    if event_is_upcoming(earnings_at, now):
        score += MEANINGFUL_THRESHOLD
        reasons.append(f"results due {_fmt_event_when(earnings_at, now)}")
    if event_is_upcoming(ex_dividend_at, now):
        score += MEANINGFUL_THRESHOLD
        days = (ex_dividend_at.date() - now.date()).days
        when = _fmt_event_when(ex_dividend_at, now)
        reasons.append("ex-dividend this week" if days > 1 else f"ex-dividend {when}")
    return ScoreResult(score=score, reasons=reasons)


def dma_cross_side(price: float, prev_close: Optional[float], dma: Optional[float]) -> Optional[str]:
    """'above' / 'below' if today's price crossed the average vs prev_close.
    Sitting on one side of the DMA is the normal state — not an event."""
    if dma in (None, 0) or prev_close in (None, 0):
        return None
    if prev_close < dma and price >= dma:
        return "above"
    if prev_close > dma and price <= dma:
        return "below"
    return None


def score_dma_crosses(
    price: float,
    prev_close: Optional[float] = None,
    dma_50: Optional[float] = None,
    dma_200: Optional[float] = None,
) -> ScoreResult:
    reasons: List[str] = []
    score = 0.0
    # 200-day first: rarer, same stackable points as 52-week.
    for window, dma in ((200, dma_200), (50, dma_50)):
        side = dma_cross_side(price, prev_close, dma)
        if side:
            score += MEANINGFUL_THRESHOLD
            reasons.append(f"crossed {side} {window}-day average")
    return ScoreResult(score=score, reasons=reasons)


def score_symbol(
    price: float,
    prev_close: Optional[float],
    day_open: Optional[float] = None,
    volume: Optional[float] = None,
    avg_volume_20d: Optional[float] = None,
    volatility_20d_pct: Optional[float] = None,
    high_52w: Optional[float] = None,
    low_52w: Optional[float] = None,
    earnings_at: Optional[dt.datetime] = None,
    ex_dividend_at: Optional[dt.datetime] = None,
    dma_50: Optional[float] = None,
    dma_200: Optional[float] = None,
    now: Optional[dt.datetime] = None,
) -> ScoreResult:
    reasons: List[str] = []
    score = 0.0

    change_pct = _pct(price, prev_close)

    # --- 1. Volatility-normalized move ---
    if change_pct is not None:
        if volatility_20d_pct and volatility_20d_pct > 0.05:
            z = abs(change_pct) / volatility_20d_pct
            if z >= 1.5:
                points = min(z / 1.5, 3.0)
                score += points
                direction = "up" if change_pct > 0 else "down"
                reasons.append(
                    f"{direction} {abs(change_pct):.1f}% — {z:.1f}x its usual daily move"
                )
        else:
            # No volatility baseline yet (new symbol / thin history):
            # fall back to a flat, conservative threshold.
            if abs(change_pct) >= 3.0:
                direction = "up" if change_pct > 0 else "down"
                score += 1.0
                reasons.append(f"{direction} {abs(change_pct):.1f}% today")

    # --- 2. Volume anomaly ---
    if volume and avg_volume_20d and avg_volume_20d > 0:
        vol_ratio = volume / avg_volume_20d
        if vol_ratio >= 1.8:
            points = min((vol_ratio - 1) / 1.5, 2.5)
            score += points
            reasons.append(f"trading at {vol_ratio:.1f}x average volume")

    # --- 3. 52-week high/low breach ---
    if high_52w and price >= high_52w * 0.999:
        score += MEANINGFUL_THRESHOLD
        reasons.append("new 52-week high")
    elif low_52w and price <= low_52w * 1.001:
        score += MEANINGFUL_THRESHOLD
        reasons.append("new 52-week low")

    # --- 4. Opening gap ---
    gap_pct = _pct(day_open, prev_close) if day_open else None
    if gap_pct is not None and abs(gap_pct) >= 2.0:
        direction = "up" if gap_pct > 0 else "down"
        score += 1.5
        reasons.append(f"gapped {direction} {abs(gap_pct):.1f}% at the open")

    # --- 5. Calendar (results / ex-div in the next week) ---
    cal = score_calendar_events(earnings_at, ex_dividend_at, now=now)
    score += cal.score
    reasons.extend(cal.reasons)

    # --- 6. DMA cross (50 / 200 day) ---
    dma = score_dma_crosses(price, prev_close, dma_50=dma_50, dma_200=dma_200)
    score += dma.score
    reasons.extend(dma.reasons)

    return ScoreResult(score=round(score, 2), reasons=reasons)


def is_meaningful(score: float) -> bool:
    return score >= MEANINGFUL_THRESHOLD


def score_personal_delta(
    current_price: float,
    last_seen_price: Optional[float],
    volatility_20d_pct: Optional[float],
) -> Optional[str]:
    """A second, personalized layer on top of the global score: even a
    symbol that never crossed the global 'meaningful' bar on any single
    day can still be a big deal to a user who hasn't looked in two weeks,
    because moves compound. This looks at price drift since THIS user's
    last visit, independent of today's score."""
    if last_seen_price in (None, 0):
        return None
    change_pct = _pct(current_price, last_seen_price)
    if change_pct is None:
        return None

    threshold = max(volatility_20d_pct or 2.0, 2.0) * 1.5
    if abs(change_pct) >= threshold:
        direction = "up" if change_pct > 0 else "down"
        return f"{direction} {abs(change_pct):.1f}% since you last checked"
    return None
