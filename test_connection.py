#!/usr/bin/env python3
"""
Simple database connection test
"""

import asyncio
import asyncpg

async def test_connection():
    try:
        # Test direct connection
        conn = await asyncpg.connect(
            host='localhost',
            port=5432,
            user='eivissa_user',
            password='eivissa_password',
            database='eivissa_operations'
        )
        print("✅ Connected as eivissa_user")
        
        # Test query
        result = await conn.fetchval('SELECT version()')
        print(f"✅ Connection successful!")
        print(f"PostgreSQL version: {result}")
        
        await conn.close()
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())