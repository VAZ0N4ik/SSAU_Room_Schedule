import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScheduleDatabase:
    def __init__(self, db_path: str = "schedule.db"):
        """Initialize schedule database connection"""
        self.db_path = db_path
        self.connection = None
        self.cursor = None
        self.connect()
        self.create_tables()

    def connect(self):
        """Create database connection"""
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.cursor = self.connection.cursor()

        # Enable foreign keys
        self.cursor.execute("PRAGMA foreign_keys = ON")
        self.connection.commit()

    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()

    def create_tables(self):
        """Create all necessary tables for schedule data"""

        # Buildings table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS buildings (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Rooms table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY,
            building_id INTEGER NOT NULL,
            room_number TEXT NOT NULL,
            full_name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (building_id) REFERENCES buildings (id),
            UNIQUE(building_id, room_number)
        )
        ''')

        # Disciplines table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS disciplines (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Teachers table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            state TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Groups table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Lesson types table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS lesson_types (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
        ''')

        # Time slots table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS time_slots (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            begin_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            UNIQUE(begin_time, end_time)
        )
        ''')

        # Weekdays table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS weekdays (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            abbrev TEXT NOT NULL
        )
        ''')

        # Main schedule table
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id INTEGER NOT NULL,
            week_number INTEGER NOT NULL,
            weekday_id INTEGER NOT NULL,
            time_slot_id INTEGER NOT NULL,
            discipline_id INTEGER NOT NULL,
            lesson_type_id INTEGER NOT NULL,
            room_id INTEGER,
            building_id INTEGER,
            is_online BOOLEAN DEFAULT 0,
            conference_url TEXT,
            comment TEXT,
            year_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (weekday_id) REFERENCES weekdays (id),
            FOREIGN KEY (time_slot_id) REFERENCES time_slots (id),
            FOREIGN KEY (discipline_id) REFERENCES disciplines (id),
            FOREIGN KEY (lesson_type_id) REFERENCES lesson_types (id),
            FOREIGN KEY (room_id) REFERENCES rooms (id),
            FOREIGN KEY (building_id) REFERENCES buildings (id)
        )
        ''')

        # Schedule to groups mapping (many-to-many)
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedule_groups (
            schedule_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            subgroup INTEGER,
            PRIMARY KEY (schedule_id, group_id),
            FOREIGN KEY (schedule_id) REFERENCES schedule (id) ON DELETE CASCADE,
            FOREIGN KEY (group_id) REFERENCES groups (id)
        )
        ''')

        # Schedule to teachers mapping (many-to-many)
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS schedule_teachers (
            schedule_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            PRIMARY KEY (schedule_id, teacher_id),
            FOREIGN KEY (schedule_id) REFERENCES schedule (id) ON DELETE CASCADE,
            FOREIGN KEY (teacher_id) REFERENCES teachers (id)
        )
        ''')

        # Cache table for quick room availability queries
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS room_availability_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            building_id INTEGER NOT NULL,
            room_id INTEGER NOT NULL,
            week_number INTEGER NOT NULL,
            weekday_id INTEGER NOT NULL,
            time_slot_id INTEGER NOT NULL,
            is_occupied BOOLEAN DEFAULT 0,
            year_id INTEGER NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (building_id) REFERENCES buildings (id),
            FOREIGN KEY (room_id) REFERENCES rooms (id),
            FOREIGN KEY (weekday_id) REFERENCES weekdays (id),
            FOREIGN KEY (time_slot_id) REFERENCES time_slots (id),
            UNIQUE(building_id, room_id, week_number, weekday_id, time_slot_id, year_id)
        )
        ''')

        # Create indexes for performance
        self.create_indexes()

        # Insert default data
        self.insert_default_data()

        self.connection.commit()

    def create_indexes(self):
        """Create indexes for better query performance"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_schedule_week_weekday ON schedule (week_number, weekday_id)",
            "CREATE INDEX IF NOT EXISTS idx_schedule_room_building ON schedule (room_id, building_id)",
            "CREATE INDEX IF NOT EXISTS idx_schedule_time ON schedule (time_slot_id)",
            "CREATE INDEX IF NOT EXISTS idx_schedule_year ON schedule (year_id)",
            "CREATE INDEX IF NOT EXISTS idx_schedule_lesson ON schedule (lesson_id)",
            "CREATE INDEX IF NOT EXISTS idx_room_availability_cache_lookup ON room_availability_cache (building_id, week_number, weekday_id, time_slot_id, year_id)",
            "CREATE INDEX IF NOT EXISTS idx_schedule_groups_schedule ON schedule_groups (schedule_id)",
            "CREATE INDEX IF NOT EXISTS idx_schedule_groups_group ON schedule_groups (group_id)",
            "CREATE INDEX IF NOT EXISTS idx_schedule_teachers_schedule ON schedule_teachers (schedule_id)",
            "CREATE INDEX IF NOT EXISTS idx_schedule_teachers_teacher ON schedule_teachers (teacher_id)"
        ]

        for index in indexes:
            try:
                self.cursor.execute(index)
            except sqlite3.OperationalError as e:
                logger.warning(f"Index creation failed: {e}")

    def insert_default_data(self):
        """Insert default reference data"""

        # Default lesson types
        lesson_types = [
            (1, "Лекция"),
            (2, "Лабораторная"),
            (3, "Практика"),
            (4, "Другое")
        ]

        for type_id, name in lesson_types:
            self.cursor.execute(
                "INSERT OR IGNORE INTO lesson_types (id, name) VALUES (?, ?)",
                (type_id, name)
            )

        # Default time slots
        time_slots = [
            (1, "1 пара (08:00-09:35)", "08:00", "09:35"),
            (2, "2 пара (09:45-11:20)", "09:45", "11:20"),
            (3, "3 пара (11:30-13:05)", "11:30", "13:05"),
            (4, "4 пара (13:30-15:05)", "13:30", "15:05"),
            (5, "5 пара (15:15-16:50)", "15:15", "16:50"),
            (6, "6 пара (17:00-18:35)", "17:00", "18:35"),
            (7, "7 пара (18:45-20:20)", "18:45", "20:20"),
            (8, "8 пара (20:30-22:05)", "20:30", "22:05")
        ]

        for slot_id, name, begin_time, end_time in time_slots:
            self.cursor.execute(
                "INSERT OR IGNORE INTO time_slots (id, name, begin_time, end_time) VALUES (?, ?, ?, ?)",
                (slot_id, name, begin_time, end_time)
            )

        # Default weekdays
        weekdays = [
            (1, "понедельник", "пн"),
            (2, "вторник", "вт"),
            (3, "среда", "ср"),
            (4, "четверг", "чт"),
            (5, "пятница", "пт"),
            (6, "суббота", "сб"),
            (7, "воскресенье", "вс")
        ]

        for day_id, name, abbrev in weekdays:
            self.cursor.execute(
                "INSERT OR IGNORE INTO weekdays (id, name, abbrev) VALUES (?, ?, ?)",
                (day_id, name, abbrev)
            )

    def get_or_create_building(self, building_id: int, building_name: str) -> int:
        """Get or create building and return its database ID"""
        self.cursor.execute(
            "SELECT id FROM buildings WHERE name = ?",
            (building_name,)
        )
        result = self.cursor.fetchone()

        if result:
            return result['id']

        self.cursor.execute(
            "INSERT INTO buildings (id, name) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET name = ?, updated_at = CURRENT_TIMESTAMP",
            (building_id, building_name, building_name)
        )
        return building_id

    def get_or_create_room(self, room_id: int, room_name: str, building_id: int) -> int:
        """Get or create room and return its database ID"""
        # Extract room number from full name (format: "RoomNumber-BuildingName")
        room_number = room_name.split('-')[0] if '-' in room_name else room_name
        full_name = room_name

        self.cursor.execute(
            "SELECT id FROM rooms WHERE building_id = ? AND room_number = ?",
            (building_id, room_number)
        )
        result = self.cursor.fetchone()

        if result:
            return result['id']

        self.cursor.execute(
            "INSERT INTO rooms (id, building_id, room_number, full_name) VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET full_name = ?, updated_at = CURRENT_TIMESTAMP",
            (room_id, building_id, room_number, full_name, full_name)
        )
        return room_id

    def get_or_create_discipline(self, discipline_id: int, discipline_name: str) -> int:
        """Get or create discipline and return its database ID"""
        self.cursor.execute(
            "SELECT id FROM disciplines WHERE name = ?",
            (discipline_name,)
        )
        result = self.cursor.fetchone()

        if result:
            return result['id']

        self.cursor.execute(
            "INSERT INTO disciplines (id, name) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP",
            (discipline_id, discipline_name)
        )
        return discipline_id

    def get_or_create_teacher(self, teacher_id: int, teacher_name: str, teacher_state: str = "") -> int:
        """Get or create teacher and return its database ID"""
        self.cursor.execute(
            "SELECT id FROM teachers WHERE name = ?",
            (teacher_name,)
        )
        result = self.cursor.fetchone()

        if result:
            return result['id']

        self.cursor.execute(
            "INSERT INTO teachers (id, name, state) VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET state = ?, updated_at = CURRENT_TIMESTAMP",
            (teacher_id, teacher_name, teacher_state, teacher_state)
        )
        return teacher_id

    def get_or_create_group(self, group_id: int, group_name: str) -> int:
        """Get or create group and return its database ID"""
        self.cursor.execute(
            "SELECT id FROM groups WHERE name = ?",
            (group_name,)
        )
        result = self.cursor.fetchone()

        if result:
            return result['id']

        self.cursor.execute(
            "INSERT INTO groups (id, name) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP",
            (group_id, group_name)
        )
        return group_id

    def insert_schedule_lesson(self, lesson_data: Dict[str, Any], year_id: int) -> int:
        """Insert a single lesson into the schedule"""

        # Get discipline ID
        discipline_id = self.get_or_create_discipline(
            lesson_data['discipline']['id'],
            lesson_data['discipline']['name']
        )

        # Get lesson type ID - ensure it exists
        lesson_type_id = lesson_data['type']['id']
        self.cursor.execute("SELECT id FROM lesson_types WHERE id = ?", (lesson_type_id,))
        if not self.cursor.fetchone():
            # Insert missing lesson type
            self.cursor.execute(
                "INSERT OR IGNORE INTO lesson_types (id, name) VALUES (?, ?)",
                (lesson_type_id, lesson_data['type']['name'])
            )

        # Get time slot ID - ensure it exists
        time_slot_id = lesson_data['time']['id']
        self.cursor.execute("SELECT id FROM time_slots WHERE id = ?", (time_slot_id,))
        if not self.cursor.fetchone():
            # Insert missing time slot
            self.cursor.execute(
                "INSERT OR IGNORE INTO time_slots (id, name, begin_time, end_time) VALUES (?, ?, ?, ?)",
                (time_slot_id, lesson_data['time']['name'],
                 lesson_data['time']['beginTime'], lesson_data['time']['endTime'])
            )

        # Get weekday ID - ensure it exists
        weekday_id = lesson_data['weekday']['id']
        self.cursor.execute("SELECT id FROM weekdays WHERE id = ?", (weekday_id,))
        if not self.cursor.fetchone():
            # Insert missing weekday
            self.cursor.execute(
                "INSERT OR IGNORE INTO weekdays (id, name, abbrev) VALUES (?, ?, ?)",
                (weekday_id, lesson_data['weekday']['name'], lesson_data['weekday']['abbrev'])
            )

        # Process each week for this lesson
        for week_info in lesson_data['weeks']:
            week_number = week_info['week']
            is_online = week_info.get('isOnline', 0)

            # Handle building and room
            building_id = None
            room_id = None

            if not is_online and week_info.get('building') and week_info.get('room'):
                building_db_id = self.get_or_create_building(
                    week_info['building']['id'],
                    week_info['building']['name']
                )
                room_db_id = self.get_or_create_room(
                    week_info['room']['id'],
                    week_info['room']['name'],
                    building_db_id
                )
                building_id = building_db_id
                room_id = room_db_id

            # Conference URL
            conference_url = None
            if lesson_data.get('conference') and lesson_data['conference'].get('url'):
                conference_url = lesson_data['conference']['url']

            # Check if schedule entry already exists
            self.cursor.execute('''
                SELECT id FROM schedule
                WHERE lesson_id = ? AND week_number = ? AND weekday_id = ?
                  AND time_slot_id = ? AND year_id = ?
            ''', (lesson_data['id'], week_number, weekday_id, time_slot_id, year_id))

            existing = self.cursor.fetchone()

            if existing:
                # Use existing schedule entry
                schedule_id = existing['id']
            else:
                # Insert new schedule entry
                self.cursor.execute('''
                    INSERT INTO schedule (
                        lesson_id, week_number, weekday_id, time_slot_id,
                        discipline_id, lesson_type_id, room_id, building_id,
                        is_online, conference_url, comment, year_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    lesson_data['id'], week_number, weekday_id, time_slot_id,
                    discipline_id, lesson_type_id, room_id, building_id,
                    is_online, conference_url, lesson_data.get('comment', ''), year_id
                ))

                schedule_id = self.cursor.lastrowid

            # Insert groups
            for group in lesson_data['groups']:
                group_db_id = self.get_or_create_group(group['id'], group['name'])
                subgroup = group.get('subgroup')

                self.cursor.execute('''
                    INSERT OR IGNORE INTO schedule_groups (schedule_id, group_id, subgroup)
                    VALUES (?, ?, ?)
                ''', (schedule_id, group_db_id, subgroup))

            # Insert teachers
            for teacher in lesson_data['teachers']:
                teacher_db_id = self.get_or_create_teacher(
                    teacher['id'],
                    teacher['name'],
                    teacher.get('state', '')
                )

                self.cursor.execute('''
                    INSERT OR IGNORE INTO schedule_teachers (schedule_id, teacher_id)
                    VALUES (?, ?)
                ''', (schedule_id, teacher_db_id))

        return schedule_id

    def clear_old_data(self, year_id: int):
        """Clear old schedule data for a specific year"""
        logger.info(f"Clearing old data for year_id: {year_id}")

        # First, delete related data using CASCADE on foreign keys
        # This is more efficient and avoids SQLite variable limits

        # Delete schedule_groups and schedule_teachers first (they reference schedule)
        self.cursor.execute("""
            DELETE FROM schedule_groups
            WHERE schedule_id IN (SELECT id FROM schedule WHERE year_id = ?)
        """, (year_id,))

        self.cursor.execute("""
            DELETE FROM schedule_teachers
            WHERE schedule_id IN (SELECT id FROM schedule WHERE year_id = ?)
        """, (year_id,))

        # Count schedule entries before deletion for logging
        self.cursor.execute("SELECT COUNT(*) as count FROM schedule WHERE year_id = ?", (year_id,))
        count_result = self.cursor.fetchone()
        schedule_count = count_result['count'] if count_result else 0

        # Delete schedule entries
        self.cursor.execute("DELETE FROM schedule WHERE year_id = ?", (year_id,))

        # Clear cache for this year
        self.cursor.execute("DELETE FROM room_availability_cache WHERE year_id = ?", (year_id,))

        self.connection.commit()
        logger.info(f"Cleared {schedule_count} schedule entries")

    def migrate_from_json(self, json_file_path: str, year_id: int = 14):
        """Migrate data from existing JSON file"""
        logger.info(f"Starting migration from {json_file_path}")

        if not os.path.exists(json_file_path):
            logger.error(f"JSON file not found: {json_file_path}")
            return False

        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)

            # Clear existing data for this year
            self.clear_old_data(year_id)

            # Mock lesson data structure from JSON room data
            # This is a simplified migration - you may need to adjust based on actual data structure
            lesson_id_counter = 1

            for building_name, rooms in json_data.items():
                building_id = int(building_name) if building_name.isdigit() else hash(building_name) % 1000000

                for room_name, lessons in rooms.items():
                    for lesson in lessons:
                        # Create a lesson structure compatible with the database
                        lesson_data = {
                            'id': lesson_id_counter,
                            'discipline': {
                                'id': hash(lesson['discipline']) % 1000000,
                                'name': lesson['discipline']
                            },
                            'type': {'id': 3},  # Default to practice
                            'time': self._get_time_slot_from_times(lesson['begin_time'], lesson['end_time']),
                            'weekday': self._get_weekday_from_name(lesson['weekday']),
                            'weeks': [{
                                'week': lesson['week'],
                                'building': {'id': building_id, 'name': building_name},
                                'room': {'id': hash(room_name) % 1000000, 'name': room_name},
                                'isOnline': 0
                            }],
                            'groups': [{'id': hash(group) % 1000000, 'name': group} for group in lesson['groups']],
                            'teachers': [{'id': hash(teacher) % 1000000, 'name': teacher, 'state': ''} for teacher in lesson['teacher']],
                            'comment': ''
                        }

                        self.insert_schedule_lesson(lesson_data, year_id)
                        lesson_id_counter += 1

            self.connection.commit()
            logger.info("Migration completed successfully")
            return True

        except Exception as e:
            logger.error(f"Migration failed: {e}")
            self.connection.rollback()
            return False

    def _get_time_slot_from_times(self, begin_time: str, end_time: str) -> Dict[str, Any]:
        """Get time slot info from begin and end times"""
        self.cursor.execute(
            "SELECT id, name FROM time_slots WHERE begin_time = ? AND end_time = ?",
            (begin_time, end_time)
        )
        result = self.cursor.fetchone()

        if result:
            return {'id': result['id'], 'name': result['name'], 'beginTime': begin_time, 'endTime': end_time}

        # If not found, return first slot as default
        return {'id': 1, 'name': f"{begin_time}-{end_time}", 'beginTime': begin_time, 'endTime': end_time}

    def _get_weekday_from_name(self, weekday_name: str) -> Dict[str, Any]:
        """Get weekday info from weekday name"""
        self.cursor.execute(
            "SELECT id, name, abbrev FROM weekdays WHERE name = ?",
            (weekday_name,)
        )
        result = self.cursor.fetchone()

        if result:
            return {'id': result['id'], 'name': result['name'], 'abbrev': result['abbrev']}

        # Default to Monday if not found
        return {'id': 1, 'name': 'понедельник', 'abbrev': 'пн'}

    def get_room_schedule(self, building_name: str, room_number: str, week_number: int, weekday_name: str, year_id: int = 14) -> List[Dict[str, Any]]:
        """Get schedule for a specific room"""
        query = '''
            SELECT
                s.lesson_id,
                s.week_number,
                w.name as weekday,
                ts.begin_time,
                ts.end_time,
                d.name as discipline,
                lt.name as lesson_type,
                s.is_online,
                s.conference_url,
                s.comment,
                GROUP_CONCAT(DISTINCT g.name) as groups,
                GROUP_CONCAT(DISTINCT t.name) as teachers
            FROM schedule s
            JOIN weekdays w ON s.weekday_id = w.id
            JOIN time_slots ts ON s.time_slot_id = ts.id
            JOIN disciplines d ON s.discipline_id = d.id
            JOIN lesson_types lt ON s.lesson_type_id = lt.id
            LEFT JOIN schedule_groups sg ON s.id = sg.schedule_id
            LEFT JOIN groups g ON sg.group_id = g.id
            LEFT JOIN schedule_teachers st ON s.id = st.schedule_id
            LEFT JOIN teachers t ON st.teacher_id = t.id
            LEFT JOIN rooms r ON s.room_id = r.id
            LEFT JOIN buildings b ON s.building_id = b.id
            WHERE b.name = ? AND r.room_number = ? AND s.week_number = ?
                  AND w.name = ? AND s.year_id = ?
            GROUP BY s.lesson_id, s.week_number, w.name, ts.begin_time, ts.end_time,
                     d.name, lt.name, s.is_online, s.conference_url, s.comment
            ORDER BY ts.begin_time
        '''

        self.cursor.execute(query, (building_name, room_number, week_number, weekday_name, year_id))
        return [dict(row) for row in self.cursor.fetchall()]

    def get_available_rooms(self, building_name: str, week_number: int, weekday_name: str,
                          begin_time: str, end_time: str, year_id: int = 14) -> List[str]:
        """Get list of available rooms in a building for specific time"""

        query = '''
            SELECT DISTINCT r.room_number
            FROM rooms r
            JOIN buildings b ON r.building_id = b.id
            WHERE b.name = ?
                AND r.id NOT IN (
                    SELECT DISTINCT s.room_id
                    FROM schedule s
                    JOIN weekdays w ON s.weekday_id = w.id
                    JOIN time_slots ts ON s.time_slot_id = ts.id
                    WHERE s.week_number = ? AND w.name = ? AND s.year_id = ?
                        AND s.room_id IS NOT NULL
                        AND (
                            (ts.begin_time < ? AND ts.end_time > ?) OR
                            (ts.begin_time < ? AND ts.end_time > ?) OR
                            (ts.begin_time >= ? AND ts.end_time <= ?)
                        )
                )
            ORDER BY r.room_number
        '''

        self.cursor.execute(query, (
            building_name, week_number, weekday_name, year_id,
            end_time, begin_time,  # Check if lesson ends after our start
            begin_time, end_time,  # Check if lesson starts before our end
            begin_time, end_time   # Check if lesson is completely within our time
        ))

        return [row['room_number'] for row in self.cursor.fetchall()]

    def get_buildings(self) -> List[Dict[str, Any]]:
        """Get all buildings"""
        self.cursor.execute("SELECT * FROM buildings ORDER BY name")
        return [dict(row) for row in self.cursor.fetchall()]

    def get_available_weeks(self, year_id: int = 14) -> List[int]:
        """Get list of available weeks in the database for a specific year"""
        self.cursor.execute(
            "SELECT DISTINCT week_number FROM schedule WHERE year_id = ? ORDER BY week_number",
            (year_id,)
        )
        return [row['week_number'] for row in self.cursor.fetchall()]

    def get_week_range(self, year_id: int = 14) -> Tuple[int, int]:
        """Get min and max week numbers available in the database"""
        self.cursor.execute(
            "SELECT MIN(week_number) as min_week, MAX(week_number) as max_week FROM schedule WHERE year_id = ?",
            (year_id,)
        )
        result = self.cursor.fetchone()
        if result and result['min_week'] is not None:
            return (result['min_week'], result['max_week'])
        return (1, 17)  # Default fallback

    def get_stats(self) -> Dict[str, int]:
        """Get database statistics"""
        stats = {}

        tables = ['buildings', 'rooms', 'disciplines', 'teachers', 'groups', 'schedule']

        for table in tables:
            self.cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
            stats[table] = self.cursor.fetchone()['count']

        return stats


if __name__ == "__main__":
    # Example usage
    db = ScheduleDatabase("schedule.db")

    # Show stats
    stats = db.get_stats()
    print("Database stats:", stats)

    # Migrate from JSON if exists
    if os.path.exists("occupied_rooms.json"):
        print("Starting migration from JSON...")
        success = db.migrate_from_json("occupied_rooms.json", year_id=14)
        if success:
            print("Migration completed!")
            print("New stats:", db.get_stats())
        else:
            print("Migration failed!")

    db.close()