#!/usr/bin/env python3
"""
Утилита для администрирования базы данных пользователей.
Позволяет просматривать и управлять пользователями и уведомлениями.
"""

import argparse
import os
from datetime import datetime, timedelta
from db_model import Database
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Инициализация базы данных
db = Database()


def format_date(date_str):
    """Format date for display"""
    if not date_str:
        return "Неизвестно"
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return date_obj.strftime("%d.%m.%Y %H:%M:%S")
    except:
        return date_str


def list_users(args):
    """List all users in the database"""
    users = db.get_all_users(active_only=args.active, with_notifications=args.notifications)

    print(f"\n{'=' * 70}")
    print(f"{'ID пользователя':<15} {'Имя пользователя':<20} {'Имя':<15} {'Админ':<6} {'Последняя активность':<20}")
    print(f"{'-' * 70}")

    for user in users:
        is_admin = "Да" if user['is_admin'] == 1 else "Нет"
        username = user['username'] or "Нет"
        first_name = user['first_name'] or "Нет"
        last_activity = format_date(user['last_activity'])

        print(f"{user['user_id']:<15} {username:<20} {first_name:<15} {is_admin:<6} {last_activity:<20}")

    print(f"{'=' * 70}")
    print(f"Всего пользователей: {len(users)}")


def user_stats(args):
    """Show user statistics"""
    stats = db.get_user_stats()

    print("\n=== Статистика пользователей ===")
    print(f"Всего пользователей: {stats['total']}")
    print(f"Активных за 30 дней: {stats['active_30_days']}")
    print(f"С включенными уведомлениями: {stats['with_notifications']}")
    print(f"Администраторов: {stats['admins']}")


def list_notifications(args):
    """List all notifications in the database"""
    cursor = db.cursor

    if args.pending:
        cursor.execute("SELECT * FROM notifications WHERE is_sent = 0 ORDER BY created_at DESC")
    else:
        cursor.execute("SELECT * FROM notifications ORDER BY created_at DESC")

    notifications = cursor.fetchall()

    print(f"\n{'=' * 100}")
    print(f"{'ID':<5} {'Дата создания':<20} {'Создатель':<15} {'Отправлено':<10} {'Текст':<50}")
    print(f"{'-' * 100}")

    for notification in notifications:
        is_sent = "Да" if notification['is_sent'] == 1 else "Нет"
        text = notification['text']
        if len(text) > 50:
            text = text[:47] + "..."

        # Get creator name
        creator_id = notification['created_by']
        cursor.execute("SELECT username FROM users WHERE user_id = ?", (creator_id,))
        creator = cursor.fetchone()
        creator_name = creator['username'] if creator else "Неизвестно"

        created_at = format_date(notification['created_at'])

        print(f"{notification['id']:<5} {created_at:<20} {creator_name:<15} {is_sent:<10} {text:<50}")

    print(f"{'=' * 100}")
    print(f"Всего уведомлений: {len(notifications)}")


def set_admin(args):
    """Set or remove admin status for a user"""
    user_id = args.user_id
    is_admin = not args.remove

    # Check if user exists
    user = db.get_user(user_id)
    if not user:
        print(f"Пользователь с ID {user_id} не найден в базе данных.")
        return

    # Update admin status
    db.set_admin(user_id, is_admin)

    status = "добавлены" if is_admin else "удалены"
    print(f"Права администратора {status} для пользователя {user_id} ({user['username'] or user['first_name']}).")


def main():
    parser = argparse.ArgumentParser(description="Утилита для администрирования базы данных пользователей")
    subparsers = parser.add_subparsers(dest="command", help="Команда")

    # List users command
    list_parser = subparsers.add_parser("list-users", help="Список пользователей")
    list_parser.add_argument("-a", "--active", action="store_true",
                             help="Только активные пользователи (за последние 30 дней)")
    list_parser.add_argument("-n", "--notifications", action="store_true",
                             help="Только пользователи с включенными уведомлениями")
    list_parser.set_defaults(func=list_users)

    # User stats command
    stats_parser = subparsers.add_parser("stats", help="Статистика пользователей")
    stats_parser.set_defaults(func=user_stats)

    # List notifications command
    notif_parser = subparsers.add_parser("list-notifications", help="Список уведомлений")
    notif_parser.add_argument("-p", "--pending", action="store_true", help="Только неотправленные уведомления")
    notif_parser.set_defaults(func=list_notifications)

    # Set admin command
    admin_parser = subparsers.add_parser("set-admin", help="Управление правами администратора")
    admin_parser.add_argument("user_id", type=int, help="ID пользователя")
    admin_parser.add_argument("-r", "--remove", action="store_true",
                              help="Удалить права администратора (по умолчанию - добавить)")
    admin_parser.set_defaults(func=set_admin)

    args = parser.parse_args()

    if args.command:
        args.func(args)
    else:
        parser.print_help()

    # Close database connection
    db.close()


if __name__ == "__main__":
    main()