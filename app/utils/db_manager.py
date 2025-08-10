# FILE: app/utils/db_manager.py
# ==============================================================================
import functools
from ..database import AsyncSessionLocal

def db_session_manager(func):
    """
    A decorator to automatically handle async database session management.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        async with AsyncSessionLocal() as session:
            try:
                # Pass the async session to the wrapped function
                return await func(*args, db=session, **kwargs)
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    return wrapper