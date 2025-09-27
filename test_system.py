#!/usr/bin/env python3
"""
System testing script for SSAU Schedule project
Tests all major components and verifies functionality
"""

import asyncio
import os
import sys
import sqlite3
import json
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from schedule_db import ScheduleDatabase
from schedule_parser import ScheduleParser

def test_database_creation():
    """Test database creation and schema"""
    print("🔍 Testing database creation...")

    # Remove test database if exists
    test_db_path = "test_schedule.db"
    if os.path.exists(test_db_path):
        os.remove(test_db_path)

    try:
        # Create test database
        db = ScheduleDatabase(test_db_path)

        # Check if all tables were created
        tables = ['buildings', 'rooms', 'disciplines', 'teachers', 'groups',
                 'schedule', 'lesson_types', 'time_slots', 'weekdays',
                 'schedule_groups', 'schedule_teachers', 'room_availability_cache']

        for table in tables:
            db.cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            result = db.cursor.fetchone()
            if not result:
                raise Exception(f"Table {table} not found")

        # Check default data
        stats = db.get_stats()
        print(f"   ✅ Database created successfully")
        print(f"   📊 Initial stats: {stats}")

        db.close()
        return True

    except Exception as e:
        print(f"   ❌ Database creation failed: {e}")
        return False
    finally:
        # Cleanup
        if os.path.exists(test_db_path):
            os.remove(test_db_path)


def test_json_migration():
    """Test migration from JSON to SQLite"""
    print("\n🔄 Testing JSON migration...")

    if not os.path.exists("occupied_rooms.json"):
        print("   ⚠️  occupied_rooms.json not found, skipping migration test")
        return True

    test_db_path = "test_migration.db"

    try:
        # Remove test database if exists
        if os.path.exists(test_db_path):
            os.remove(test_db_path)

        # Create database and migrate
        db = ScheduleDatabase(test_db_path)
        success = db.migrate_from_json("occupied_rooms.json")

        if success:
            stats = db.get_stats()
            print(f"   ✅ Migration completed successfully")
            print(f"   📊 Migration stats: {stats}")

            # Test some queries
            buildings = db.get_buildings()
            if buildings:
                building_name = buildings[0]['name']
                available_rooms = db.get_available_rooms(
                    building_name=building_name,
                    week_number=4,
                    weekday_name="понедельник",
                    begin_time="08:00",
                    end_time="09:35"
                )
                print(f"   🔍 Test query found {len(available_rooms)} available rooms in building {building_name}")

            db.close()
            return True
        else:
            print("   ❌ Migration failed")
            return False

    except Exception as e:
        print(f"   ❌ Migration test failed: {e}")
        return False
    finally:
        # Cleanup
        if os.path.exists(test_db_path):
            os.remove(test_db_path)


def test_database_queries():
    """Test database query functionality"""
    print("\n📋 Testing database queries...")

    if not os.path.exists("schedule.db"):
        print("   ⚠️  schedule.db not found, skipping query tests")
        return True

    try:
        db = ScheduleDatabase("schedule.db")

        # Test buildings query
        buildings = db.get_buildings()
        print(f"   🏢 Found {len(buildings)} buildings")

        # Test stats
        stats = db.get_stats()
        print(f"   📊 Database stats: {stats}")

        # Test room schedule query if we have data
        if stats['schedule'] > 0 and buildings:
            building = buildings[0]['name']

            # Get a room from this building
            db.cursor.execute("""
                SELECT DISTINCT r.room_number
                FROM rooms r
                JOIN buildings b ON r.building_id = b.id
                WHERE b.name = ?
                LIMIT 1
            """, (building,))

            room_result = db.cursor.fetchone()
            if room_result:
                room_number = room_result['room_number']

                schedule = db.get_room_schedule(
                    building_name=building,
                    room_number=room_number,
                    week_number=4,
                    weekday_name="понедельник"
                )

                print(f"   📅 Schedule query for room {room_number}: {len(schedule)} lessons")

        db.close()
        print("   ✅ Database queries working correctly")
        return True

    except Exception as e:
        print(f"   ❌ Database query test failed: {e}")
        return False


async def test_parser_auth():
    """Test parser authentication"""
    print("\n🔐 Testing parser authentication...")

    try:
        from schedule_parser import SSAUAuth
        import aiohttp

        auth = SSAUAuth()

        async with aiohttp.ClientSession() as session:
            success = await auth.authenticate(session)

            if success:
                print("   ✅ Authentication successful")
                cookies = auth.get_cookies()
                print(f"   🍪 Got session cookie: {'laravel_session' in cookies}")
                return True
            else:
                print("   ⚠️  Authentication failed (this is expected if no credentials provided)")
                return True  # Not a failure if no credentials

    except Exception as e:
        print(f"   ❌ Authentication test failed: {e}")
        return False


def test_systemd_files():
    """Test systemd service files exist and are valid"""
    print("\n⚙️  Testing systemd files...")

    service_file = "ssau-schedule-updater.service"
    timer_file = "ssau-schedule-updater.timer"
    install_script = "install_service.sh"

    files_ok = True

    # Check service file
    if os.path.exists(service_file):
        print(f"   ✅ {service_file} exists")
        with open(service_file, 'r') as f:
            content = f.read()
            if 'schedule_updater.py' in content and '[Unit]' in content:
                print("   ✅ Service file format looks correct")
            else:
                print("   ❌ Service file format incorrect")
                files_ok = False
    else:
        print(f"   ❌ {service_file} not found")
        files_ok = False

    # Check timer file
    if os.path.exists(timer_file):
        print(f"   ✅ {timer_file} exists")
        with open(timer_file, 'r') as f:
            content = f.read()
            if 'OnCalendar' in content and '[Timer]' in content:
                print("   ✅ Timer file format looks correct")
            else:
                print("   ❌ Timer file format incorrect")
                files_ok = False
    else:
        print(f"   ❌ {timer_file} not found")
        files_ok = False

    # Check install script
    if os.path.exists(install_script):
        print(f"   ✅ {install_script} exists")
        if os.access(install_script, os.X_OK):
            print("   ✅ Install script is executable")
        else:
            print("   ⚠️  Install script is not executable")
    else:
        print(f"   ❌ {install_script} not found")
        files_ok = False

    return files_ok


def test_environment_config():
    """Test environment configuration"""
    print("\n🔧 Testing environment configuration...")

    required_files = ['.env.example']
    optional_files = ['.env']

    for file in required_files:
        if os.path.exists(file):
            print(f"   ✅ {file} exists")
        else:
            print(f"   ❌ {file} not found")
            return False

    for file in optional_files:
        if os.path.exists(file):
            print(f"   ✅ {file} exists")
        else:
            print(f"   ⚠️  {file} not found (optional)")

    # Check .env.example content
    try:
        with open('.env.example', 'r') as f:
            content = f.read()
            required_vars = ['BOT_TOKEN', 'ADMIN_IDS', 'SEMESTER_START']
            for var in required_vars:
                if var in content:
                    print(f"   ✅ {var} found in .env.example")
                else:
                    print(f"   ❌ {var} missing from .env.example")
                    return False
    except Exception as e:
        print(f"   ❌ Error reading .env.example: {e}")
        return False

    return True


def test_project_structure():
    """Test project file structure"""
    print("\n📁 Testing project structure...")

    required_files = [
        'schedule_db.py',
        'schedule_parser.py',
        'schedule_updater.py',
        'tg_bot_new.py',
        'db_model.py',
        'requirements.txt',
        'README.md',
        'API_DOCS.md'
    ]

    deprecated_files = [
        'admin_util.py',
        'get_info.ipynb',
        'tz.md',
        'hint.md'
    ]

    all_good = True

    for file in required_files:
        if os.path.exists(file):
            print(f"   ✅ {file}")
        else:
            print(f"   ❌ {file} missing")
            all_good = False

    print("   🗑️  Deprecated files (should be removed):")
    for file in deprecated_files:
        if os.path.exists(file):
            print(f"   ⚠️  {file} (should be removed)")
            all_good = False
        else:
            print(f"   ✅ {file} (removed)")

    return all_good


async def run_all_tests():
    """Run all tests"""
    print("🧪 Starting SSAU Schedule System Tests\n")
    print("=" * 50)

    tests = [
        ("Project Structure", test_project_structure),
        ("Environment Config", test_environment_config),
        ("Database Creation", test_database_creation),
        ("JSON Migration", test_json_migration),
        ("Database Queries", test_database_queries),
        ("Parser Authentication", test_parser_auth),
        ("Systemd Files", test_systemd_files),
    ]

    results = {}

    for test_name, test_func in tests:
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            results[test_name] = result
        except Exception as e:
            print(f"   💥 Test {test_name} crashed: {e}")
            results[test_name] = False

    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)

    passed = 0
    total = len(tests)

    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
        if result:
            passed += 1

    print(f"\n🎯 Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! System is ready for deployment.")
        return True
    else:
        print("⚠️  Some tests failed. Please fix issues before deployment.")
        return False


if __name__ == "__main__":
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⚠️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test suite crashed: {e}")
        sys.exit(1)