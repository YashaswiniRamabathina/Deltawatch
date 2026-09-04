"""
Standalone poller process. Run this separately from the API when the API
is scaled to multiple instances/workers, so quotes are fetched by exactly
one process instead of once per API replica.

    python -m app.worker
"""
import logging

from app.db import ensure_schema
from app.services.poller import run_forever

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    ensure_schema()
    run_forever()
