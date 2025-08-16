#!/usr/bin/env python3
"""
Local Database Setup Script for Eivissa Operations Bot

This script creates the database tables and optionally seeds test data.
Run this after starting the PostgreSQL container.
"""

import asyncio
import sys
import os
from datetime import date, datetime
from pathlib import Path

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import async_engine, AsyncSessionLocal
from app.models import Base, Property, Booking, Issue, EmailAlert, Relocation
from app.models import PropertyStatus, BookingStatus, EmailAlertStatus

async def create_tables():
    """Create all database tables."""
    print("Creating database tables...")
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database tables created successfully!")

async def seed_test_data():
    """Seed the database with test data for development."""
    print("Seeding test data...")
    
    async with AsyncSessionLocal() as session:
        # Create test properties
        properties = [
            Property(code="A1", status=PropertyStatus.AVAILABLE),
            Property(code="A2", status=PropertyStatus.OCCUPIED),
            Property(code="B1", status=PropertyStatus.PENDING_CLEANING),
            Property(code="B2", status=PropertyStatus.MAINTENANCE, notes="Fixing shower"),
            Property(code="C1", status=PropertyStatus.AVAILABLE),
            Property(code="C2", status=PropertyStatus.OCCUPIED),
            Property(code="D1", status=PropertyStatus.AVAILABLE),
            Property(code="D2", status=PropertyStatus.AVAILABLE),
        ]
        
        for prop in properties:
            session.add(prop)
        
        await session.flush()  # Get property IDs
        
        # Create test bookings
        bookings = [
            Booking(
                property_id=2,  # A2
                property_code="A2",
                guest_name="John Doe",
                platform="Airbnb",
                checkin_date=date(2025, 1, 15),
                checkout_date=date(2025, 1, 18),
                due_payment="150 EUR",
                status=BookingStatus.ACTIVE
            ),
            Booking(
                property_id=6,  # C2
                property_code="C2",
                guest_name="Maria Garcia",
                platform="Booking.com",
                checkin_date=date(2025, 1, 16),
                checkout_date=date(2025, 1, 20),
                due_payment="200 EUR",
                status=BookingStatus.ACTIVE
            ),
            Booking(
                property_id=3,  # B1 (departed guest)
                property_code="B1",
                guest_name="Alice Smith",
                platform="Airbnb",
                checkin_date=date(2025, 1, 10),
                checkout_date=date(2025, 1, 15),
                due_payment="180 EUR",
                status=BookingStatus.DEPARTED
            ),
        ]
        
        for booking in bookings:
            session.add(booking)
        
        # Create test issues
        issues = [
            Issue(
                property_id=4,  # B2
                description="Shower drain is clogged",
                reported_at=date(2025, 1, 16)
            ),
            Issue(
                property_id=2,  # A2
                description="WiFi password needs reset",
                reported_at=date(2025, 1, 17)
            ),
        ]
        
        for issue in issues:
            session.add(issue)
        
        # Create test email alert
        email_alert = EmailAlert(
            category="Guest Complaint",
            summary="Guest reports noise from neighboring room",
            guest_name="John Doe",
            property_code="A2",
            platform="Airbnb",
            status=EmailAlertStatus.OPEN
        )
        session.add(email_alert)
        
        await session.commit()
    
    print("✅ Test data seeded successfully!")

async def show_database_status():
    """Display current database status."""
    print("\n📊 Database Status:")
    
    async with AsyncSessionLocal() as session:
        # Count properties by status
        from sqlalchemy import select, func
        
        # Properties
        result = await session.execute(
            select(Property.status, func.count(Property.id))
            .group_by(Property.status)
        )
        print("\n🏠 Properties by Status:")
        for status, count in result.all():
            print(f"  {status}: {count}")
        
        # Bookings
        result = await session.execute(
            select(Booking.status, func.count(Booking.id))
            .group_by(Booking.status)
        )
        print("\n📅 Bookings by Status:")
        for status, count in result.all():
            print(f"  {status}: {count}")
        
        # Issues
        result = await session.execute(select(func.count(Issue.id)))
        issue_count = result.scalar()
        print(f"\n🔧 Total Issues: {issue_count}")
        
        # Email Alerts
        result = await session.execute(select(func.count(EmailAlert.id)))
        alert_count = result.scalar()
        print(f"📧 Total Email Alerts: {alert_count}")

async def main():
    """Main setup function."""
    print("🚀 Setting up Eivissa Operations Bot Local Database")
    print("=" * 50)
    
    try:
        # Test database connection
        print("Testing database connection...")
        async with async_engine.begin() as conn:
            from sqlalchemy import text
            result = await conn.execute(text("SELECT 1"))
            print("✅ Database connection successful!")
        
        # Create tables
        await create_tables()
        
        # Ask if user wants to seed test data
        seed_data = input("\n🌱 Would you like to seed test data? (y/N): ").lower().strip()
        if seed_data in ['y', 'yes']:
            await seed_test_data()
        
        # Show database status
        await show_database_status()
        
        print("\n✅ Database setup complete!")
        print("\n📝 Next steps:")
        print("1. Copy .env.local to .env and update with your API keys")
        print("2. Run: python run.py")
        print("3. Test the system with Telegram commands")
        
    except Exception as e:
        print(f"❌ Error setting up database: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())