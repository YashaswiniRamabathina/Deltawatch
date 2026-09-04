import datetime as dt
import json

from app.schemas import DigestOut
from app.timeutils import to_iso_z


def test_naive_datetime_is_emitted_as_utc_z():
    naive = dt.datetime(2026, 9, 4, 8, 35, 0)
    assert to_iso_z(naive) == "2026-09-04T08:35:00Z"


def test_aware_utc_keeps_z():
    aware = dt.datetime(2026, 9, 4, 8, 35, 0, tzinfo=dt.timezone.utc)
    assert to_iso_z(aware) == "2026-09-04T08:35:00Z"


def test_digest_json_uses_z_suffix():
    payload = DigestOut(generated_at=dt.datetime(2026, 9, 4, 8, 35, 0), entries=[])
    dumped = json.loads(payload.model_dump_json())
    assert dumped["generated_at"] == "2026-09-04T08:35:00Z"
