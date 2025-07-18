# FILE: app/utils/db_manager.py
import functools
from ..database import get_db

def db_session_manager(func):
    """
    A decorator to automatically handle database session management.
    It provides a `db` session object to the decorated function and ensures
    the session is closed afterward.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        db = next(get_db())
        try:
            # Pass the db session as a keyword argument to the wrapped function
            return await func(*args, db=db, **kwargs)
        finally:
            db.close()
    return wrapper