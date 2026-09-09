from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.settings import settings
import sys
import asyncio
import logging

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = logging.getLogger("sentinel.db")

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    connect_args={"prepare_threshold": None},
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables (Supabase: run migrations instead, but this is a safe fallback)."""
    from app import models  # noqa: F401 — registers all ORM models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all only creates missing tables; it never adds a column to one
        # that exists. Columns added after a table first shipped go here as
        # idempotent statements, so a running instance picks them up on restart
        # rather than failing its first query against them.
        for statement in _COLUMN_ADDITIONS:
            await conn.execute(text(statement))
    logger.info("Database tables initialised.")


# Additive-only. Each must be safe to run on every start.
_COLUMN_ADDITIONS = (
    "ALTER TABLE scene_observations "
    "ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'worker'",
    "CREATE INDEX IF NOT EXISTS ix_scene_observations_source "
    "ON scene_observations (source)",
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
