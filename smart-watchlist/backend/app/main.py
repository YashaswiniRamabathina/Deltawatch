import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS, ENABLE_INPROCESS_POLLER, require_jwt_secret
from app.db import ensure_schema
from app.routers import auth, watchlist, market
from app.services.poller import start_background_thread

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    require_jwt_secret()
    ensure_schema()
    stop_event = None
    if ENABLE_INPROCESS_POLLER:
        stop_event = start_background_thread()
        logging.info("Smart Watchlist API started; background poller running in-process.")
    else:
        logging.info("Smart Watchlist API started; poller disabled here, run `python -m app.worker` separately.")
    yield
    if stop_event:
        stop_event.set()


app = FastAPI(title="Smart Market Watchlist API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(watchlist.router)
app.include_router(market.router)


@app.get("/health")
def health():
    return {"status": "ok"}
