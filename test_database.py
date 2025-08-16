#!/usr/bin/env python3
"""
Database Testing Script for Eivissa Operations Bot

This script tests database operations and model functionality.
"""

import asyncio
import sys
from pathlib import Path
from datetime import date, datetime

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import AsyncSessionLocal
from app.models import Property, Booking, Issue, EmailAlert, Relocation
from app.models import PropertyStatus, BookingStatus, EmailAlertStatus
from sqlalchemy import select, func

async def test_property_operations():
    """Test property CRUD operations."""
    print("🏠 Testing Property Operations...")
    
    async with AsyncSessionLocal() as session:
        # Test property creation
        new_property = Property(code="TEST1", status=PropertyStatus.AVAILABLE)
        session.add(new_property)
        await session.commit()
        print("✅ Property created successfully")
        
        # Test property query
        result = await session.execute(
            select(Property).where(Property.code == "TEST1")
        )
        property = result.scalar_one()
        print(f"✅ Property queried: {property.code} - {property.status}")
        
        # Test status update
        property.status = PropertyStatus.OCCUPIED
        await session.commit()
        print("✅ Property status updated")
        
        # Test property deletion
        await session.delete(property)
        await session.commit()
        print("✅ Property deleted successfully")

async def test_booking_operations():
    """Test booking CRUD operations."""
    print("\n📅 Testing Booking Operations...")
    
    async with AsyncSessionLocal() as session:
        # Get an existing property
        result = await session.execute(
            select(Property).where(Property.status == PropertyStatus.AVAILABLE).limit(1)
        )
        property = result.scalar_one_or_none()
        
        if not property:
            print("⚠️ No available property found for booking test")
            return
        
        # Create test booking
        booking = Booking(
            property_id=property.id,
            property_code=property.code,
            guest_name="Test Guest",
            platform="Test Platform",
            checkin_date=date.today(),
            due_payment="100 EUR",
            status=BookingStatus.ACTIVE
        )
        session.add(booking)
        await session.commit()
        print("✅ Booking created successfully")
        
        # Test booking query with relationship
        result = await session.execute(
            select(Booking).where(Booking.guest_name == "Test Guest")
        )
        booking = result.scalar_one()
        print(f"✅ Booking queried: {booking.guest_name} in {booking.property_code}")
        
        # Clean up
        await session.delete(booking)
        await session.commit()
        print("✅ Test booking cleaned up")

async def test_enum_constraints():
    """Test enum constraint validation."""
    print("\n🔒 Testing Enum Constraints...")
    
    async with AsyncSessionLocal() as session:
        try:
            # Test valid enum values
            property = Property(code="ENUM_TEST", status=PropertyStatus.AVAILABLE)
            session.add(property)
            await session.commit()
            print("✅ Valid enum value accepted")
            
            # Test enum value change
            property.status = PropertyStatus.MAINTENANCE
            await session.commit()
            print("✅ Enum value change successful")
            
            # Clean up
            await session.delete(property)
            await session.commit()
            
        except Exception as e:
            print(f"❌ Enum constraint test failed: {e}")
            await session.rollback()

async def test_relationships():
    """Test model relationships."""
    print("\n🔗 Testing Model Relationships...")
    
    async with AsyncSessionLocal() as session:
        # Get property with bookings
        result = await session.execute(
            select(Property).where(Property.status == PropertyStatus.OCCUPIED).limit(1)
        )
        property = result.scalar_one_or_none()
        
        if property:
            # Test property -> bookings relationship
            await session.refresh(property, ['bookings'])
            print(f"✅ Property {property.code} has {len(property.bookings)} bookings")
            
            # Test property -> issues relationship
            await session.refresh(property, ['issues'])
            print(f"✅ Property {property.code} has {len(property.issues)} issues")
        else:
            print("⚠️ No occupied property found for relationship test")

async def test_complex_queries():
    """Test complex database queries."""
    print("\n🔍 Testing Complex Queries...")
    
    async with AsyncSessionLocal() as session:
        # Test aggregation query
        result = await session.execute(
            select(Property.status, func.count(Property.id))
            .group_by(Property.status)
        )
        print("✅ Property status aggregation:")
        for status, count in result.all():
            print(f"   {status}: {count}")
        
        # Test join query
        result = await session.execute(
            select(Property.code, Booking.guest_name)
            .join(Booking, Property.id == Booking.property_id)
            .where(Booking.status == BookingStatus.ACTIVE)
        )
        print("✅ Active bookings with property codes:")
        for code, guest in result.all():
            print(f"   {code}: {guest}")

async def test_transaction_rollback():
    """Test transaction rollback functionality."""
    print("\n🔄 Testing Transaction Rollback...")
    
    async with AsyncSessionLocal() as session:
        try:
            # Start a transaction
            property = Property(code="ROLLBACK_TEST", status=PropertyStatus.AVAILABLE)
            session.add(property)
            await session.flush()  # Get the ID but don't commit
            
            property_id = property.id
            print(f"✅ Property created with ID: {property_id}")
            
            # Simulate an error and rollback
            await session.rollback()
            print("✅ Transaction rolled back")
            
            # Verify the property was not saved
            result = await session.execute(
                select(Property).where(Property.code == "ROLLBACK_TEST")
            )
            property = result.scalar_one_or_none()
            
            if property is None:
                print("✅ Rollback successful - property not found")
            else:
                print("❌ Rollback failed - property still exists")
                
        except Exception as e:
            print(f"❌ Transaction rollback test failed: {e}")
            await session.rollback()

async def run_all_tests():
    """Run all database tests."""
    print("🧪 Running Database Tests")
    print("=" * 40)
    
    try:
        await test_property_operations()
        await test_booking_operations()
        await test_enum_constraints()
        await test_relationships()
        await test_complex_queries()
        await test_transaction_rollback()
        
        print("\n✅ All database tests completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Database tests failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_all_tests())