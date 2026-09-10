"""Direct SQLAlchemy async engine and session lifecycle helpers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative metadata shared by the application models and Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_database_engine(database_url: str | URL, *, echo: bool = False) -> AsyncEngine:
    """Create a PostgreSQL-only async engine using the pinned psycopg driver."""

    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("DATABASE_URL must use postgresql+psycopg; SQLite is not supported")
    return create_async_engine(url, echo=echo, pool_pre_ping=True)


def create_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Bind a maker whose calls always return independent async sessions."""

    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    session_maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield one session and roll back unfinished work when its scope fails."""

    async with session_maker() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
