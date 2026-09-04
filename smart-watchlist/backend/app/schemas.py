from typing import Optional, List

from pydantic import BaseModel, EmailStr, Field

from app.timeutils import OptionalUtcDateTime, UtcDateTime


# ---- Auth ----

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- Watchlist ----

class WatchlistAdd(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    is_held: bool = False


class WatchlistHeld(BaseModel):
    held: bool


class SymbolQuote(BaseModel):
    symbol: str
    price: Optional[float] = None
    prev_close: Optional[float] = None
    change_pct: Optional[float] = None
    day_open: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    volume: Optional[float] = None
    avg_volume_20d: Optional[float] = None
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    dma_50: Optional[float] = None
    dma_200: Optional[float] = None
    source: Optional[str] = None
    updated_at: OptionalUtcDateTime = None
    is_stale: bool = False
    flagged_conflict: bool = False
    has_data: bool = True

    # Meaningful-change scoring
    change_score: float = 0.0
    reasons: List[str] = []

    # Personalized "since you last checked" fields
    last_seen_at: OptionalUtcDateTime = None
    price_change_since_seen: Optional[float] = None
    price_change_since_seen_pct: Optional[float] = None


class WatchlistItemOut(BaseModel):
    symbol: str
    added_at: UtcDateTime
    is_held: bool = False
    quote: SymbolQuote

    class Config:
        from_attributes = True


class DigestEntry(BaseModel):
    symbol: str
    score: float
    reasons: List[str]
    price: Optional[float] = None
    change_pct: Optional[float] = None
    since: OptionalUtcDateTime = None
    is_held: bool = False


class DigestOut(BaseModel):
    generated_at: UtcDateTime
    entries: List[DigestEntry]
