import sqlite3
import os
from datetime import datetime, timedelta


class Database:
    def __init__(self, db_path="bot_data.db"):
        """Initialize database connection"""
        self.db_path = db_path
        self.connection = None
        self.cursor = None
        self.connect()
        self.create_tables()

    def connect(self):
        """Create database connection"""
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row  # Return rows as dict-like objects
        self.cursor = self.connection.cursor()

    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()

    def create_tables(self):
        """Create necessary tables if they don't exist"""
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            is_admin INTEGER DEFAULT 0,
            joined_date TEXT,
            last_activity TEXT,
            notifications_enabled INTEGER DEFAULT 1
        )
        ''')

        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by INTEGER,
            is_sent INTEGER DEFAULT 0,
            FOREIGN KEY (created_by) REFERENCES users (user_id)
        )
        ''')

        self.connection.commit()

    def add_user(self, user_id, username, first_name, last_name):
        """Add a new user or update existing user information"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Check if user exists
        self.cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        user = self.cursor.fetchone()

        if user:
            # Update existing user
            self.cursor.execute('''
            UPDATE users 
            SET username = ?, first_name = ?, last_name = ?, last_activity = ?
            WHERE user_id = ?
            ''', (username, first_name, last_name, current_time, user_id))
        else:
            # Add new user
            self.cursor.execute('''
            INSERT INTO users (user_id, username, first_name, last_name, joined_date, last_activity)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, username, first_name, last_name, current_time, current_time))

        self.connection.commit()

    def update_user_activity(self, user_id):
        """Update user's last activity timestamp"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute('''
        UPDATE users SET last_activity = ? WHERE user_id = ?
        ''', (current_time, user_id))
        self.connection.commit()

    def get_user(self, user_id):
        """Get user by ID"""
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()

    def get_all_users(self, active_only=False, with_notifications=None):
        """
        Get all users

        Parameters:
        active_only (bool): If True, return only users active in the last 30 days
        with_notifications (bool): If True, return only users with notifications enabled
                                  If False, return only users with notifications disabled
                                  If None, return all users
        """
        query = "SELECT * FROM users"
        conditions = []
        params = []

        if active_only:
            # Users active in the last 30 days
            thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            conditions.append("last_activity >= ?")
            params.append(thirty_days_ago)

        if with_notifications is not None:
            conditions.append("notifications_enabled = ?")
            params.append(1 if with_notifications else 0)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def toggle_notifications(self, user_id, enabled):
        """Enable or disable notifications for a user"""
        self.cursor.execute('''
        UPDATE users SET notifications_enabled = ? WHERE user_id = ?
        ''', (1 if enabled else 0, user_id))
        self.connection.commit()

    def is_admin(self, user_id):
        """Check if user is an admin"""
        self.cursor.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        return result and result['is_admin'] == 1

    def set_admin(self, user_id, is_admin=True):
        """Set or remove admin status for a user"""
        self.cursor.execute('''
        UPDATE users SET is_admin = ? WHERE user_id = ?
        ''', (1 if is_admin else 0, user_id))
        self.connection.commit()

    def add_notification(self, text, created_by):
        """Add a new notification to be sent to users"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute('''
        INSERT INTO notifications (text, created_at, created_by, is_sent)
        VALUES (?, ?, ?, 0)
        ''', (text, current_time, created_by))
        self.connection.commit()
        return self.cursor.lastrowid

    def mark_notification_sent(self, notification_id):
        """Mark a notification as sent"""
        self.cursor.execute('''
        UPDATE notifications SET is_sent = 1 WHERE id = ?
        ''', (notification_id,))
        self.connection.commit()

    def get_notification(self, notification_id):
        """Get a specific notification by ID"""
        self.cursor.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,))
        return self.cursor.fetchone()

    def get_pending_notifications(self):
        """Get all notifications that haven't been sent yet"""
        self.cursor.execute("SELECT * FROM notifications WHERE is_sent = 0")
        return self.cursor.fetchall()

    def get_user_stats(self):
        """Get user statistics"""
        stats = {
            'total': 0,
            'active_30_days': 0,
            'with_notifications': 0,
            'admins': 0
        }

        # Total users
        self.cursor.execute("SELECT COUNT(*) as count FROM users")
        stats['total'] = self.cursor.fetchone()['count']

        # Active users (last 30 days)
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute("SELECT COUNT(*) as count FROM users WHERE last_activity >= ?", (thirty_days_ago,))
        stats['active_30_days'] = self.cursor.fetchone()['count']

        # Users with notifications enabled
        self.cursor.execute("SELECT COUNT(*) as count FROM users WHERE notifications_enabled = 1")
        stats['with_notifications'] = self.cursor.fetchone()['count']

        # Admin users
        self.cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_admin = 1")
        stats['admins'] = self.cursor.fetchone()['count']

        return stats