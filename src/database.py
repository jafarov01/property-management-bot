# FILE: database.py
# ==============================================================================
# VERSION: 3.0
# UPDATED: Added 'pool_recycle' to the engine creation. This prevents the
# database connection from going stale, a common cause of silent errors in
# long-running background schedulers.
# ==============================================================================
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from config import DATABASE_URL

# Add pool_recycle to ensure connections are refreshed periodically.
engine = create_engine(DATABASE_URL, pool_recycle=3600) # Recycle connections every hour

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
