from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

_EXTRA_COLUMNS = (
    ("symbol_state", "flagged_conflict", "BOOLEAN DEFAULT 0"),
    ("symbol_state", "earnings_at", "DATETIME"),
    ("symbol_state", "ex_dividend_at", "DATETIME"),
    ("symbol_state", "dma_50", "FLOAT"),
    ("symbol_state", "dma_200", "FLOAT"),
    ("watchlist_items", "is_held", "BOOLEAN DEFAULT 0"),
)


def ensure_schema():
    """create_all does not add columns to an existing SQLite file."""
    import app.models  # noqa: F401 — register tables on Base
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in _EXTRA_COLUMNS:
            if table not in inspector.get_table_names():
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column in cols:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
