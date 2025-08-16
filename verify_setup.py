#!/usr/bin/env python3
"""
Setup Verification Script for Eivissa Operations Bot

This script verifies that all components are properly set up and ready to run.
"""

import asyncio
import sys
from pathlib import Path

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

async def verify_setup():
    """Verify all system components are ready."""
    print("🔍 Verifying Eivissa Operations Bot Setup")
    print("=" * 50)
    
    checks_passed = 0
    total_checks = 6
    
    # Check 1: Database connection
    try:
        from app.database import async_engine
        from sqlalchemy import text
        
        async with async_engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            print("✅ Database connection: WORKING")
            checks_passed += 1
    except Exception as e:
        print(f"❌ Database connection: FAILED - {e}")
    
    # Check 2: Application imports
    try:
        from app.main import app
        print("✅ Application imports: WORKING")
        checks_passed += 1
    except Exception as e:
        print(f"❌ Application imports: FAILED - {e}")
    
    # Check 3: Database tables
    try:
        from app.models import Property, Booking, Issue, EmailAlert
        from app.database import AsyncSessionLocal
        from sqlalchemy import select, func
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(func.count(Property.id)))
            property_count = result.scalar()
            print(f"✅ Database tables: WORKING ({property_count} properties found)")
            checks_passed += 1
    except Exception as e:
        print(f"❌ Database tables: FAILED - {e}")
    
    # Check 4: Configuration
    try:
        from app.config import DATABASE_URL, TELEGRAM_BOT_TOKEN
        print("✅ Configuration: LOADED")
        checks_passed += 1
    except Exception as e:
        print(f"❌ Configuration: FAILED - {e}")
    
    # Check 5: Required files
    required_files = ['run.py', '.env', 'requirements.txt', 'docker-compose.yml']
    missing_files = []
    
    for file in required_files:
        if not Path(file).exists():
            missing_files.append(file)
    
    if not missing_files:
        print("✅ Required files: ALL PRESENT")
        checks_passed += 1
    else:
        print(f"❌ Required files: MISSING - {', '.join(missing_files)}")
    
    # Check 6: Docker container
    try:
        import subprocess
        result = subprocess.run(['docker-compose', 'ps'], capture_output=True, text=True)
        if 'eivissa_postgres' in result.stdout and 'Up' in result.stdout:
            print("✅ Docker container: RUNNING")
            checks_passed += 1
        else:
            print("❌ Docker container: NOT RUNNING")
    except Exception as e:
        print(f"❌ Docker container: CHECK FAILED - {e}")
    
    # Summary
    print("\n" + "=" * 50)
    print(f"📊 Setup Verification: {checks_passed}/{total_checks} checks passed")
    
    if checks_passed == total_checks:
        print("🎉 ALL CHECKS PASSED - System is ready!")
        print("\n🚀 Start the application with: python run.py")
        return True
    else:
        print("⚠️  Some checks failed - please review the issues above")
        print("\n📝 Common fixes:")
        print("   - Start Docker: docker-compose up -d postgres")
        print("   - Setup database: python setup_local_db.py")
        print("   - Install dependencies: pip install -r requirements.txt")
        return False

if __name__ == "__main__":
    success = asyncio.run(verify_setup())
    sys.exit(0 if success else 1)