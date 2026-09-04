"""UTC instants. SQLite stores naive datetimes; we treat those as UTC and
emit ISO-8601 with a Z so browsers do not parse them as local time (IST)."""
import datetime as dt
from typing import Annotated, Optional

from pydantic import AfterValidator, PlainSerializer


def utcnow() -> dt.datetime:
    """Naive UTC, matching what SQLite round-trips."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def as_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def to_iso_z(value: dt.datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[
    dt.datetime,
    AfterValidator(as_utc),
    PlainSerializer(to_iso_z, return_type=str, when_used="json"),
]

OptionalUtcDateTime = Optional[UtcDateTime]
