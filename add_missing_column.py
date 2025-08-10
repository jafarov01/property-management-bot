import asyncio
from sqlalchemy import text
from app.database import async_engine

async def add_reminders_sent_column():
    """
    Adds the 'reminders_sent' column to the 'bookings' table if it doesn't exist.
    """
    async with async_engine.connect() as conn:
        try:
            async with conn.begin():
                await conn.execute(text(
                    "ALTER TABLE bookings ADD COLUMN reminders_sent INTEGER NOT NULL DEFAULT 0"
                ))
            print("✅ Successfully added 'reminders_sent' column to 'bookings' table.")
        except Exception as e:
            if "already exists" in str(e):
                print("⚠️ Column 'reminders_sent' already exists.")
            else:
                print(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    print("Running migration script to add 'reminders_sent' column...")
    asyncio.run(add_reminders_sent_column())