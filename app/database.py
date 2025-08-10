# FILE: app/database.py
# ==============================================================================
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import DATABASE_URL

# Use the +asyncpg driver connection string
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Create an asynchronous engine
async_engine = create_async_engine(ASYNC_DATABASE_URL)

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