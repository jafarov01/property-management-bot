#!/usr/bin/env python3
"""
Test SQLAlchemy connection
"""

import asyncio
import sys
from pathlib import Path

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import async_engine

async def test_sqlalchemy_connection():
    try:
        async with async_engine.begin() as conn:
            from sqlalchemy import text
            result = await conn.execute(text("SELECT version()"))
            version = result.fetchone()[0]
            print(f"✅ SQLAlchemy connection successful!")
            print(f"PostgreSQL version: {version}")
            
    except Exception as e:
        print(f"❌ SQLAlchemy connection failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_sqlalchemy_connection())