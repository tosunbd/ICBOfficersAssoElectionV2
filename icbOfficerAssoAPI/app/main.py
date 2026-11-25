"""FastAPI application entry point — ICB Officers' Association Election System (V2: ballot entry)."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

from app import database
from app.config import settings
from app.database import init_db
from app.routers import admin, auth, ballots, candidates, dashboard, elections, entry, reports
from app.routers.admin import APP_VERSION
from app.seed import ensure_election, ensure_users
from app.services.backup import backup_loop, backup_now

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting ICB Election API v%s", APP_VERSION)
    await init_db()
    await ensure_users()      # SA, Admin, EC1, EC2, EC3 (created once; passwords are never reset)
    await ensure_election()   # the 2026 election with its 13 posts and 30 candidates, on an empty database
    logger.info("Database: %s", settings.database_file)
    logger.info("Entry ranges: %s", settings.entry_ranges)
    await backup_now("start")
    backups = asyncio.create_task(backup_loop())
    logger.info("API is ready")
    yield
    backups.cancel()
    await backup_now("stop")
    logger.info("API stopped")


app = FastAPI(
    title="ICB Officers' Association Election System",
    description="Ballot entry by the Election Commissioners, vote counting, live results and reports "
                "for the ICB Officers' Association election.",
    version=APP_VERSION,
    lifespan=lifespan,
)

origins = settings.cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials="*" not in origins,  # browsers reject credentials with a wildcard origin
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(entry.router)
app.include_router(elections.router)
app.include_router(candidates.router)
app.include_router(ballots.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.include_router(reports.router)


@app.get("/", tags=["Health"])
async def root():
    return {"name": "ICB Officers' Association Election System", "version": APP_VERSION, "status": "running"}


@app.get("/api/health", tags=["Health"])
async def health():
    """Used by the watchdog of "1. Start.bat": healthy only when the database answers."""
    try:
        async with database.AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Health check: the database does not answer: %s", exc)
        return JSONResponse(status_code=503, content={"status": "database error", "version": APP_VERSION})
    return {"status": "healthy", "version": APP_VERSION, "database_year": settings.database_year}
