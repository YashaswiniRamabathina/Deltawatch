"""
Central configuration. Everything that might change between a laptop demo
and a real deployment lives here, read from environment variables with
sane local-dev defaults so the app runs with zero setup.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SQLite by default (zero setup). Point DATABASE_URL at Postgres in prod,
# e.g. postgresql+psycopg2://user:pass@host:5432/watchlist
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'watchlist.db'}")

ENV = os.getenv("ENV", "dev").lower()
JWT_SECRET_DEFAULT = "dev-secret-change-me-in-prod"
JWT_SECRET = os.getenv("JWT_SECRET", JWT_SECRET_DEFAULT)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", str(60 * 24 * 14)))  # 14 days
BCRYPT_PASSWORD_MAX_BYTES = 72


def require_jwt_secret(secret: str | None = None, env: str | None = None) -> None:
    """Refuse to sign sessions with the baked-in default outside local/dev/test."""
    secret = JWT_SECRET if secret is None else secret
    env = ENV if env is None else env.lower()
    if env not in ("dev", "development", "test") and secret == JWT_SECRET_DEFAULT:
        raise RuntimeError(
            "JWT_SECRET must be set when ENV is not dev/test. "
            "Refusing to boot with the default signing key."
        )

# How often the background poller refreshes quotes, tiered by how many
# users are watching a symbol ("hot" symbols refresh faster). Keeping this
# tiered is what lets the system scale: N users watching AAPL cost the same
# upstream call as 1 user watching AAPL.
POLL_INTERVAL_HOT_SECONDS = int(os.getenv("POLL_INTERVAL_HOT_SECONDS", "15"))
POLL_INTERVAL_WARM_SECONDS = int(os.getenv("POLL_INTERVAL_WARM_SECONDS", "60"))
POLL_INTERVAL_COLD_SECONDS = int(os.getenv("POLL_INTERVAL_COLD_SECONDS", "300"))
HOT_WATCHER_THRESHOLD = int(os.getenv("HOT_WATCHER_THRESHOLD", "5"))   # >=N watchers => hot
WARM_WATCHER_THRESHOLD = int(os.getenv("WARM_WATCHER_THRESHOLD", "1"))  # >=N watchers => warm

# A quote older than this is flagged `stale: true` to the client rather than
# silently presented as live.
STALE_AFTER_SECONDS = int(os.getenv("STALE_AFTER_SECONDS", "180"))

# Two independent, keyless quote sources so we can demonstrate real
# conflict-resolution rather than fake it. Priority order matters when
# both respond but disagree.
PROVIDER_PRIORITY = ["yahoo", "stooq"]

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")

# For a single-instance demo, the poller runs as a background thread inside
# the API process (zero extra setup). If you scale the API horizontally
# (multiple uvicorn workers/replicas), set this to "false" and run the
# poller as its own singleton process instead (`python -m app.worker`) so
# quotes aren't fetched N times redundantly. See README "Scaling" section.
ENABLE_INPROCESS_POLLER = os.getenv("ENABLE_INPROCESS_POLLER", "true").lower() == "true"

