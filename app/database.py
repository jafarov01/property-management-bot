# FILE: app/database.py
# ==============================================================================
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import DATABASE_URL

# -- START OF FIX --
# This block handles multiple connection issues with Fly.io:
# 1. Replaces "postgres://" with the correct "postgresql+asyncpg://" driver.
# 2. Removes the "?sslmode=disable" parameter which can cause issues.
# 3. Explicitly passes `ssl=False` to the engine to prevent handshake errors.

temp_url = DATABASE_URL
if temp_url.startswith("postgres://"):
    temp_url = temp_url.replace("postgres://", "postgresql+asyncpg://", 1)

ASYNC_DATABASE_URL = temp_url.split("?")[0]

# Create an asynchronous engine, explicitly disabling SSL
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    connect_args={"ssl": False} # <-- This is the new, critical line
)
# -- END OF FIX --

# Create a session maker for async sessions
AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()

async def get_db() -> AsyncSession:
    """
    Dependency function that yields an async database session.
    """
    async with AsyncSessionLocal() as session:
        yield session