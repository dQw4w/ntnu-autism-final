import os
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

_raw = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/records.db")

# Normalize Postgres URL for asyncpg driver (Render / Supabase provide postgres:// URLs)
if _raw.startswith("postgres://"):
    DATABASE_URL = _raw.replace("postgres://", "postgresql+asyncpg://", 1)
elif _raw.startswith("postgresql://") and "+asyncpg" not in _raw:
    DATABASE_URL = _raw.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _raw

_is_sqlite = DATABASE_URL.startswith("sqlite")

_connect_args: dict = {}
if _is_sqlite:
    _connect_args["check_same_thread"] = False
else:
    # Supabase routes through PgBouncer (transaction mode), which doesn't support
    # prepared statements — disable asyncpg's statement cache to avoid the error.
    _connect_args["statement_cache_size"] = 0
    if os.getenv("DATABASE_SSL", "false").strip().lower() in ("1", "true", "yes"):
        _connect_args["ssl"] = "require"

engine = create_async_engine(DATABASE_URL, connect_args=_connect_args, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id         = Column(Integer, primary_key=True)
    nickname   = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Session(Base):
    __tablename__ = "sessions"
    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    character_id = Column(Text, nullable=False)
    scenario_id  = Column(Text, nullable=False)
    started_at   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    saved_at     = Column(DateTime(timezone=True), nullable=True)
    result       = Column(Boolean, nullable=True)   # None=not judged, True/False=judged
    summary      = Column(Text, nullable=True)
    messages_json = Column(Text, nullable=True)     # JSON array [{role, content}]


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from loguru import logger
    safe_url = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
    logger.info("database ready  url=...{}", safe_url)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
