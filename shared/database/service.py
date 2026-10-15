from sqlalchemy import MetaData, URL
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, create_async_engine
from shared.settings import settings
import logging

# single declarative base: every table lives in the "shop" schema of the shop database
class Base(DeclarativeBase):
    metadata = MetaData(schema="shop")

def database_url(drivername: str = "postgresql+asyncpg",
                 username: str = settings.DB_USER,
                 password: str = settings.DB_PASSWORD) -> URL:
    # URL.create, not an f-string: a password containing @ / : etc. would break the URL
    return URL.create(
        drivername,
        username=username,
        password=password,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        database=settings.DB_NAME,
    )


async def setup(username: str = settings.DB_USER,
                password: str = settings.DB_PASSWORD) -> tuple[sessionmaker[AsyncSession], AsyncEngine]:
    """Engine + session factory for one database user: the app user by default, or the
    read-only role the agent's SQL runs as (settings.DB_READER_USER)."""
    DB_USER = username
    DB_HOST = settings.DB_HOST
    DB_PORT = settings.DB_PORT
    DB_NAME = settings.DB_NAME

    engine = create_async_engine(database_url(username=username, password=password), echo=False)
    AsyncSessionFactory = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False
        )

    # tables are created by alembic migrations (alembic upgrade head), not here
    logging.info(f"Database setup complete for {DB_NAME} at {DB_HOST}:{DB_PORT} with user {DB_USER}")

    return AsyncSessionFactory, engine  # return the session factory to be used in the ingestion pipeline
