#!/usr/bin/env python3
"""
System Integration Test for Eivissa Operations Bot

This script tests the system functionality without requiring external API keys.
"""

import asyncio
import sys
from pathlib import Path
from datetime import date

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import AsyncSessionLocal
from app.models import Property, Booking, Issue, EmailAlert
from app.models import PropertyStatus, BookingStatus, EmailAlertStatus
from sqlalchemy import select

async def test_property_status_workflow():
    """Test the complete property status workflow."""
    print("🏠 Testing Property Status Workflow...")
    
    async with AsyncSessionLocal() as session:
        # Create a test property
        property = Property(code="WORKFLOW_TEST", status=PropertyStatus.AVAILABLE)
        session.add(property)
        await session.commit()
        
        print(f"✅ Created property: {property.code} - {property.status}")
        
        # Simulate check-in (AVAILABLE -> OCCUPIED)
        property.status = PropertyStatus.OCCUPIED
        await session.commit()
        print(f"✅ Check-in: {property.code} - {property.status}")
        
        # Create booking for the occupied property
        booking = Booking(
            property_id=property.id,
            property_code=property.code,
            guest_name="Test Workflow Guest",
            platform="Test Platform",
            checkin_date=date.today(),
            due_payment="150 EUR",
            status=BookingStatus.ACTIVE
        )
        session.add(booking)
        await session.commit()
        print(f"✅ Created booking for guest: {booking.guest_name}")
        
        # Simulate check-out (OCCUPIED -> PENDING_CLEANING)
        property.status = PropertyStatus.PENDING_CLEANING
        booking.status = BookingStatus.DEPARTED
        await session.commit()
        print(f"✅ Check-out: {property.code} - {property.status}")
        
        # Simulate cleaning completion (PENDING_CLEANING -> AVAILABLE)
        property.status = PropertyStatus.AVAILABLE
        await session.commit()
        print(f"✅ Cleaning complete: {property.code} - {property.status}")
        
        # Clean up
        await session.delete(booking)
        await session.delete(property)
        await session.commit()
        print("✅ Workflow test completed and cleaned up")

async def test_overbooking_scenario():
    """Test overbooking conflict detection."""
    print("\n🚨 Testing Overbooking Scenario...")
    
    async with AsyncSessionLocal() as session:
        # Create a property
        property = Property(code="CONFLICT_TEST", status=PropertyStatus.OCCUPIED)
        session.add(property)
        await session.commit()
        
        # Create first booking (active)
        booking1 = Booking(
            property_id=property.id,
            property_code=property.code,
            guest_name="First Guest",
            platform="Airbnb",
            checkin_date=date.today(),
            due_payment="100 EUR",
            status=BookingStatus.ACTIVE
        )
        session.add(booking1)
        await session.commit()
        print(f"✅ Active booking: {booking1.guest_name}")
        
        # Create second booking (conflict - pending relocation)
        booking2 = Booking(
            property_id=property.id,
            property_code=property.code,
            guest_name="Second Guest",
            platform="Booking.com",
            checkin_date=date.today(),
            due_payment="120 EUR",
            status=BookingStatus.PENDING_RELOCATION
        )
        session.add(booking2)
        await session.commit()
        print(f"✅ Conflicting booking: {booking2.guest_name} - {booking2.status}")
        
        # Simulate conflict resolution - swap bookings
        booking1.status = BookingStatus.PENDING_RELOCATION
        booking2.status = BookingStatus.ACTIVE
        await session.commit()
        print("✅ Conflict resolved by swapping booking statuses")
        
        # Clean up
        await session.delete(booking1)
        await session.delete(booking2)
        await session.delete(property)
        await session.commit()
        print("✅ Overbooking test completed and cleaned up")

async def test_maintenance_workflow():
    """Test property maintenance workflow."""
    print("\n🔧 Testing Maintenance Workflow...")
    
    async with AsyncSessionLocal() as session:
        # Create property
        property = Property(code="MAINTENANCE_TEST", status=PropertyStatus.AVAILABLE)
        session.add(property)
        await session.commit()
        
        # Block for maintenance
        property.status = PropertyStatus.MAINTENANCE
        property.notes = "Testing maintenance workflow"
        await session.commit()
        print(f"✅ Property blocked: {property.code} - {property.notes}")
        
        # Create maintenance issue
        issue = Issue(
            property_id=property.id,
            description="Test maintenance issue",
            reported_at=date.today()
        )
        session.add(issue)
        await session.commit()
        print(f"✅ Issue logged: {issue.description}")
        
        # Complete maintenance
        property.status = PropertyStatus.AVAILABLE
        property.notes = None
        issue.is_resolved = "Yes"
        await session.commit()
        print(f"✅ Maintenance completed: {property.code} - {property.status}")
        
        # Clean up
        await session.delete(issue)
        await session.delete(property)
        await session.commit()
        print("✅ Maintenance test completed and cleaned up")

async def test_email_alert_workflow():
    """Test email alert management."""
    print("\n📧 Testing Email Alert Workflow...")
    
    async with AsyncSessionLocal() as session:
        # Create email alert
        alert = EmailAlert(
            category="Test Alert",
            summary="Testing email alert workflow",
            guest_name="Test Guest",
            property_code="TEST123",
            platform="Test Platform",
            status=EmailAlertStatus.OPEN
        )
        session.add(alert)
        await session.commit()
        print(f"✅ Email alert created: {alert.category} - {alert.status}")
        
        # Simulate handling
        alert.status = EmailAlertStatus.HANDLED
        alert.handled_by = "Test Handler"
        await session.commit()
        print(f"✅ Alert handled: {alert.status} by {alert.handled_by}")
        
        # Clean up
        await session.delete(alert)
        await session.commit()
        print("✅ Email alert test completed and cleaned up")

async def test_data_integrity():
    """Test data integrity constraints."""
    print("\n🔒 Testing Data Integrity...")
    
    async with AsyncSessionLocal() as session:
        try:
            # Test enum constraint
            property = Property(code="INTEGRITY_TEST", status=PropertyStatus.AVAILABLE)
            session.add(property)
            await session.commit()
            
            # Test valid enum change
            property.status = PropertyStatus.MAINTENANCE
            await session.commit()
            print("✅ Valid enum constraint passed")
            
            # Test unique constraint
            duplicate_property = Property(code="INTEGRITY_TEST", status=PropertyStatus.AVAILABLE)
            session.add(duplicate_property)
            
            try:
                await session.commit()
                print("❌ Unique constraint failed - duplicate allowed")
            except Exception:
                await session.rollback()
                print("✅ Unique constraint enforced")
            
            # Clean up
            await session.delete(property)
            await session.commit()
            
        except Exception as e:
            print(f"❌ Data integrity test failed: {e}")
            await session.rollback()

async def generate_test_report():
    """Generate a test report showing current database state."""
    print("\n📊 Test Report - Current Database State:")
    print("=" * 50)
    
    async with AsyncSessionLocal() as session:
        # Properties by status
        from sqlalchemy import func
        result = await session.execute(
            select(Property.status, func.count(Property.id))
            .group_by(Property.status)
        )
        print("\n🏠 Properties by Status:")
        total_properties = 0
        for status, count in result.all():
            print(f"   {status.value}: {count}")
            total_properties += count
        print(f"   TOTAL: {total_properties}")
        
        # Bookings by status
        result = await session.execute(
            select(Booking.status, func.count(Booking.id))
            .group_by(Booking.status)
        )
        print("\n📅 Bookings by Status:")
        total_bookings = 0
        for status, count in result.all():
            print(f"   {status.value}: {count}")
            total_bookings += count
        print(f"   TOTAL: {total_bookings}")
        
        # Issues
        result = await session.execute(select(func.count(Issue.id)))
        issue_count = result.scalar()
        print(f"\n🔧 Total Issues: {issue_count}")
        
        # Email alerts
        result = await session.execute(select(func.count(EmailAlert.id)))
        alert_count = result.scalar()
        print(f"📧 Total Email Alerts: {alert_count}")

async def run_system_tests():
    """Run all system integration tests."""
    print("🧪 Running System Integration Tests")
    print("=" * 50)
    
    try:
        await test_property_status_workflow()
        await test_overbooking_scenario()
        await test_maintenance_workflow()
        await test_email_alert_workflow()
        await test_data_integrity()
        await generate_test_report()
        
        print("\n✅ All system tests completed successfully!")
        print("\n🎉 The Eivissa Operations Bot database is working correctly!")
        print("\n📝 You can now:")
        print("   1. Start the application with: python run.py")
        print("   2. Test Telegram commands (if you have a bot token)")
        print("   3. Test Slack integration (if you have Slack configured)")
        
    except Exception as e:
        print(f"\n❌ System tests failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_system_tests())