"""HTTP flow against FastAPI TestClient with a mocked quote refresh.

Digest is empty right after add (last_seen is set then). We backdate
last_seen and insert a ChangeEvent to prove mark-seen actually clears it.
"""
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.models import ChangeEvent, SymbolState, WatchlistItem


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr("app.main.ENABLE_INPROCESS_POLLER", False)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)

    def fake_refresh(db, aggregator, symbol):
        now = dt.datetime.utcnow()
        state = db.query(SymbolState).filter(SymbolState.symbol == symbol).first()
        if state is None:
            state = SymbolState(symbol=symbol)
            db.add(state)
        state.last_price = 100.0
        state.prev_close = 99.0
        state.change_score = 0.0
        state.change_reasons = "[]"
        state.last_updated_at = now
        state.is_stale = False
        db.flush()

    monkeypatch.setattr("app.routers.watchlist.refresh_symbol", fake_refresh)
    monkeypatch.setattr("app.routers.watchlist.has_fresh_quote", lambda db, symbol: False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, TestingSession
    app.dependency_overrides.clear()


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_http_register_add_digest_seen_delete(api):
    client, Session = api

    unauth = client.get("/watchlist")
    assert unauth.status_code == 401

    created = client.post(
        "/auth/register",
        json={"email": "Judge@Example.com", "password": "password1"},
    )
    assert created.status_code == 201
    token = created.json()["access_token"]
    headers = _auth_header(token)

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "judge@example.com"

    login = client.post(
        "/auth/login",
        data={"username": "JUDGE@example.com", "password": "password1"},
    )
    assert login.status_code == 200

    added = client.post("/watchlist", json={"symbol": "AAPL"}, headers=headers)
    assert added.status_code == 201
    assert added.json()["symbol"] == "AAPL"
    assert added.json()["quote"]["has_data"] is True

    listed = client.get("/watchlist", headers=headers)
    assert [row["symbol"] for row in listed.json()] == ["AAPL"]

    empty_digest = client.get("/digest", headers=headers)
    assert empty_digest.status_code == 200
    assert empty_digest.json()["entries"] == []

    db = Session()
    try:
        item = db.query(WatchlistItem).filter(WatchlistItem.symbol == "AAPL").one()
        item.last_seen_at = dt.datetime.utcnow() - dt.timedelta(days=2)
        item.last_seen_price = 90.0
        db.add(ChangeEvent(
            symbol="AAPL",
            occurred_at=dt.datetime.utcnow() - dt.timedelta(hours=1),
            score=3.2,
            reasons='["crossed above 50-day average"]',
        ))
        db.commit()
    finally:
        db.close()

    digest = client.get("/digest", headers=headers)
    assert [e["symbol"] for e in digest.json()["entries"]] == ["AAPL"]

    seen = client.post("/watchlist/AAPL/seen", headers=headers)
    assert seen.status_code == 200
    assert client.get("/digest", headers=headers).json()["entries"] == []

    duplicate = client.post("/watchlist", json={"symbol": "AAPL"}, headers=headers)
    assert duplicate.status_code == 409

    removed = client.delete("/watchlist/AAPL", headers=headers)
    assert removed.status_code == 204
    assert client.get("/watchlist", headers=headers).json() == []
