import logging
import os
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, \
    ConversationHandler, filters
from dotenv import load_dotenv
from db_model import Database
from schedule_db import ScheduleDatabase
from typing import List, Dict, Any, Optional

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize databases
user_db = Database()  # For user management
schedule_db = ScheduleDatabase()  # For schedule data

# Load admin IDs from environment variable
ADMIN_IDS = [int(admin_id.strip()) for admin_id in os.getenv("ADMIN_IDS", "").split(",") if admin_id.strip()]
for admin_id in ADMIN_IDS:
    user = user_db.get_user(admin_id)
    if user:
        user_db.set_admin(admin_id, True)

# Ignored buildings (ВУЦ и Спорткомплекс)
IGNORED_BUILDINGS = ["4", "6"]

# Constants for ConversationHandler states
(
    SELECTING_ACTION,
    SELECT_BUILDING,
    SELECT_ROOM,
    SELECT_WEEK,
    SELECT_DAY,
    SELECT_TIME_START,
    SELECT_TIME_END,
    SHOW_SCHEDULE,
    HANDLE_RESULTS,
    FIND_AVAILABLE_ROOMS,
    ADMIN_MENU,
    ADMIN_BROADCAST,
    ADMIN_CONFIRM_BROADCAST,
    USER_SETTINGS,
    TOGGLE_NOTIFICATIONS,
) = range(15)

# Weekday translation map
WEEKDAY_TRANSLATION = {
    0: "понедельник",
    1: "вторник",
    2: "среда",
    3: "четверг",
    4: "пятница",
    5: "суббота",
    6: "воскресенье"
}

# Reverse weekday translation
WEEKDAY_TO_NUMBER = {v: k for k, v in WEEKDAY_TRANSLATION.items()}

# Semester start date
SEMESTER_START = os.getenv("SEMESTER_START", "2024-09-02")


# User tracking
async def track_user_activity(update: Update):
    """Update user information in database"""
    user = update.effective_user
    if user:
        user_db.add_user(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or ""
        )
        user_db.update_user_activity(user.id)


def calculate_current_academic_week():
    """Calculate the current academic week based on semester start with modular arithmetic"""
    today = datetime.now()
    semester_start_date = datetime.strptime(SEMESTER_START, "%Y-%m-%d")

    delta_days = (today - semester_start_date).days
    if delta_days < 0:
        return 1

    # Get available weeks from database
    available_weeks = schedule_db.get_available_weeks(year_id=14)

    if not available_weeks:
        # Fallback to simple calculation if no data
        current_week = (delta_days // 7) + 1
        return current_week

    # Get week range
    min_week, max_week = min(available_weeks), max(available_weeks)
    total_weeks = max_week - min_week + 1

    # Calculate week with modular arithmetic
    raw_week = (delta_days // 7) + 1

    # Map to actual week range using modulo
    if raw_week > max_week:
        # Use modular arithmetic to cycle through weeks
        normalized_week = ((raw_week - min_week) % total_weeks) + min_week
        return normalized_week

    return raw_week


def get_class_periods():
    """Return list of class periods with start and end times"""
    return [
        ("1 пара (08:00-09:35)", "08:00", "09:35"),
        ("2 пара (09:45-11:20)", "09:45", "11:20"),
        ("3 пара (11:30-13:05)", "11:30", "13:05"),
        ("4 пара (13:30-15:05)", "13:30", "15:05"),
        ("5 пара (15:15-16:50)", "15:15", "16:50"),
        ("6 пара (17:00-18:35)", "17:00", "18:35"),
        ("7 пара (18:45-20:20)", "18:45", "20:20"),
        ("8 пара (20:30-22:05)", "20:30", "22:05")
    ]


def get_time_keyboard():
    """Create keyboard with class period time options"""
    keyboard = []
    class_periods = get_class_periods()

    for label, start_time, end_time in class_periods:
        keyboard.append([InlineKeyboardButton(
            label,
            callback_data=f"time_{start_time}_{end_time}"
        )])

    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_end_time_keyboard(start_index: int):
    """Create keyboard with end time options starting from the selected start time"""
    keyboard = []
    class_periods = get_class_periods()

    # Show only periods from start_index onwards
    for i in range(start_index, len(class_periods)):
        label, start_time, end_time = class_periods[i]
        keyboard.append([InlineKeyboardButton(
            label,
            callback_data=f"endtime_{end_time}"
        )])

    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_buildings_keyboard(highlight_building=None):
    """Create keyboard with building options using new database"""
    buildings = schedule_db.get_buildings()

    # Filter out ignored buildings
    filtered_buildings = [b for b in buildings if b['name'] not in IGNORED_BUILDINGS]

    # Sort buildings numerically
    def building_sort_key(building):
        name = str(building['name'])
        try:
            return (0, int(name))
        except ValueError:
            return (1, name)

    sorted_buildings = sorted(filtered_buildings, key=building_sort_key)

    keyboard = []
    row = []
    for i, building in enumerate(sorted_buildings):
        label = f"✓ {building['name']}" if building['name'] == highlight_building else building['name']
        row.append(InlineKeyboardButton(label, callback_data=f"building_{building['name']}"))
        if (i + 1) % 3 == 0 or i == len(sorted_buildings) - 1:
            keyboard.append(row)
            row = []

    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_rooms_keyboard(building_name: str):
    """Create keyboard with room options for a specific building using new database"""
    try:
        # Get rooms from database
        query = '''
            SELECT DISTINCT r.room_number
            FROM rooms r
            JOIN buildings b ON r.building_id = b.id
            WHERE b.name = ?
            ORDER BY r.room_number
        '''
        schedule_db.cursor.execute(query, (building_name,))
        rooms = [row['room_number'] for row in schedule_db.cursor.fetchall()]

        if not rooms:
            return None

        keyboard = []
        row = []
        for i, room in enumerate(rooms):
            row.append(InlineKeyboardButton(room, callback_data=f"room_{room}"))
            if (i + 1) % 4 == 0 or i == len(rooms) - 1:
                keyboard.append(row)
                row = []

        keyboard.append([
            InlineKeyboardButton("⬅️ Назад", callback_data="back_to_buildings"),
            InlineKeyboardButton("Отмена", callback_data="cancel")
        ])
        return InlineKeyboardMarkup(keyboard)

    except Exception as e:
        logger.error(f"Error getting rooms for building {building_name}: {e}")
        return None


def get_week_keyboard(current_week):
    """Create keyboard for selecting academic week"""
    keyboard = []

    # Add navigation row
    nav_row = [
        InlineKeyboardButton("⬅️", callback_data=f"week_prev_{current_week}"),
        InlineKeyboardButton(f"Неделя {current_week}", callback_data=f"week_{current_week}"),
        InlineKeyboardButton("➡️", callback_data=f"week_next_{current_week}")
    ]
    keyboard.append(nav_row)

    # Add weeks around current week
    weeks_row = []
    for week_num in range(max(1, current_week - 2), current_week + 3):
        if week_num != current_week:
            weeks_row.append(InlineKeyboardButton(str(week_num), callback_data=f"week_{week_num}"))

    if weeks_row:
        keyboard.append(weeks_row)

    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_days_keyboard(week_number):
    """Create keyboard with day options for a specific week"""
    keyboard = []

    semester_start = datetime.strptime(SEMESTER_START, "%Y-%m-%d")
    week_start = semester_start + timedelta(days=(week_number - 1) * 7)

    # Show only 6 days (Monday through Saturday)
    for day_offset in range(6):
        date = week_start + timedelta(days=day_offset)
        date_str = date.strftime("%d.%m.%Y")
        day_name = WEEKDAY_TRANSLATION[date.weekday()]
        label = f"{date_str} ({day_name})"

        callback_data = f"day_{day_name}_{date.strftime('%Y-%m-%d')}"
        keyboard.append([InlineKeyboardButton(label, callback_data=callback_data)])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад к выбору недели", callback_data="back_to_weeks"),
        InlineKeyboardButton("Отмена", callback_data="cancel")
    ])
    return InlineKeyboardMarkup(keyboard)


def get_schedule_for_day_new(building_name: str, room_number: str, date_str: str, academic_week: int = None) -> str:
    """Get schedule for a specific room on a specific date using new database"""
    if academic_week is None:
        academic_week = get_academic_week(date_str)

    if academic_week is None:
        return f"Дата {date_str} находится до начала семестра."

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    weekday_name = WEEKDAY_TRANSLATION[date_obj.weekday()]

    try:
        # Pass year_id explicitly (14 is current year)
        lessons = schedule_db.get_room_schedule(building_name, room_number, academic_week, weekday_name, 14)

        # Format response
        date_formatted = date_obj.strftime("%d.%m.%Y")
        result = f"📅 Расписание аудитории {room_number} ({building_name} корпус)\n"
        result += f"🗓️ Дата: {date_formatted} ({weekday_name})\n"
        result += f"📊 Учебная неделя: {academic_week}\n\n"

        if not lessons:
            result += "🕓 На этот день занятий нет."
            return result

        # Sort lessons by time
        sorted_lessons = sorted(lessons, key=lambda x: x['begin_time'])

        for i, lesson in enumerate(sorted_lessons, 1):
            result += f"{i}. ⏰ {lesson['begin_time']} - {lesson['end_time']}\n"
            result += f"   📚 {lesson['discipline']}\n"
            if lesson['groups']:
                result += f"   👥 Группы: {lesson['groups']}\n"
            if lesson['teachers']:
                result += f"   👨‍🏫 Преподаватели: {lesson['teachers']}\n"
            result += "\n"

        return result

    except Exception as e:
        logger.error(f"Error getting schedule: {e}")
        return "❌ Ошибка при получении расписания."


def find_available_rooms_new(building_name: str, date_str: str, begin_time: str, end_time: str = None, academic_week: int = None) -> str:
    """Find available rooms using new database"""
    if academic_week is None:
        academic_week = get_academic_week(date_str)

    if academic_week is None:
        return f"Дата {date_str} находится до начала семестра."

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    weekday_name = WEEKDAY_TRANSLATION[date_obj.weekday()]

    if not end_time:
        # Default to 1.5 hours if no end time provided
        start_time_obj = datetime.strptime(begin_time, "%H:%M")
        end_time_obj = start_time_obj + timedelta(hours=1, minutes=30)
        end_time = end_time_obj.strftime("%H:%M")

    try:
        available_rooms = schedule_db.get_available_rooms(
            building_name, academic_week, weekday_name, begin_time, end_time, 14
        )

        # Format response
        date_formatted = date_obj.strftime("%d.%m.%Y")
        result = f"🔍 Свободные аудитории в {building_name} корпусе\n"
        result += f"📅 Дата: {date_formatted} ({weekday_name})\n"
        result += f"📊 Учебная неделя: {academic_week}\n"
        result += f"⏰ Время: {begin_time} - {end_time}\n\n"

        if available_rooms:
            # Group rooms by floor
            rooms_by_floor = {}
            for room in available_rooms:
                try:
                    floor = room[0]
                    if floor not in rooms_by_floor:
                        rooms_by_floor[floor] = []
                    rooms_by_floor[floor].append(room)
                except (IndexError, ValueError):
                    if "Other" not in rooms_by_floor:
                        rooms_by_floor["Other"] = []
                    rooms_by_floor["Other"].append(room)

            # Format rooms by floor
            for floor, rooms in sorted(rooms_by_floor.items()):
                result += f"🔹 {floor} этаж: {', '.join(sorted(rooms))}\n"

            result += f"\nВсего найдено: {len(available_rooms)} аудиторий"
        else:
            result += "😔 Нет свободных аудиторий в указанное время."

        return result

    except Exception as e:
        logger.error(f"Error finding available rooms: {e}")
        return "❌ Ошибка при поиске свободных аудиторий."


def get_academic_week(date_str: str, semester_start: str = SEMESTER_START) -> Optional[int]:
    """Calculate academic week number from a date with validation"""
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        semester_start_date = datetime.strptime(semester_start, "%Y-%m-%d")

        delta_days = (date_obj - semester_start_date).days
        if delta_days < 0:
            return None

        raw_week = (delta_days // 7) + 1

        # Get available weeks from database for validation
        available_weeks = schedule_db.get_available_weeks(year_id=14)

        if not available_weeks:
            return raw_week

        # Get week range
        min_week, max_week = min(available_weeks), max(available_weeks)
        total_weeks = max_week - min_week + 1

        # Map to actual week range using modulo if needed
        if raw_week > max_week:
            normalized_week = ((raw_week - min_week) % total_weeks) + min_week
            return normalized_week

        return raw_week
    except Exception:
        return None


def get_results_keyboard(context):
    """Create keyboard with navigation options after showing results"""
    keyboard = []
    action = context.user_data.get("action", "")

    if action == "view_schedule":
        keyboard.append([
            InlineKeyboardButton("📅 Другой день", callback_data="different_day"),
            InlineKeyboardButton("🚪 Другая аудитория", callback_data="different_room")
        ])
        keyboard.append([
            InlineKeyboardButton("🏢 Другой корпус", callback_data="different_building"),
            InlineKeyboardButton("🔄 Новый поиск", callback_data="new_search")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("📅 Другой день", callback_data="different_day"),
            InlineKeyboardButton("⏰ Другое время", callback_data="different_time")
        ])
        keyboard.append([
            InlineKeyboardButton("🏢 Другой корпус", callback_data="different_building"),
            InlineKeyboardButton("🔄 Новый поиск", callback_data="new_search")
        ])

    return InlineKeyboardMarkup(keyboard)


# Functions for user settings
def get_settings_keyboard(user_id):
    """Create keyboard for user settings"""
    user = user_db.get_user(user_id)
    notifications_enabled = user and user['notifications_enabled'] == 1
    notification_status = "🔔 Уведомления включены" if notifications_enabled else "🔕 Уведомления выключены"

    keyboard = [
        [InlineKeyboardButton("🔄 Переключить уведомления", callback_data="toggle_notifications")],
        [InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_menu")]
    ]

    return notification_status, InlineKeyboardMarkup(keyboard)


# Admin functions
def get_admin_keyboard():
    """Create keyboard for admin panel"""
    keyboard = [
        [InlineKeyboardButton("📢 Отправить уведомление всем", callback_data="broadcast")],
        [InlineKeyboardButton("📊 Статистика пользователей", callback_data="user_stats")],
        [InlineKeyboardButton("🗄️ Статистика БД расписания", callback_data="schedule_stats")],
        [InlineKeyboardButton("⬅️ Вернуться в меню", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, greeting: str = None) -> int:
    """Show main menu to user"""
    user = update.effective_user
    user_id = update.effective_user.id

    # Preserve the last building if it exists
    last_building = None
    if 'building' in context.user_data:
        last_building = context.user_data['building']

    context.user_data.clear()

    if last_building:
        context.user_data['last_building'] = last_building

    keyboard = [
        ["1. Посмотреть расписание аудитории"],
        ["2. Найти свободные аудитории (на одну пару)"],
        ["3. Найти свободные аудитории (на несколько пар)"]
    ]

    # Add admin button for admins
    if user_db.is_admin(user_id):
        keyboard.append(["👑 Панель администратора"])

    if greeting is None:
        greeting = "Выбери, что ты хочешь сделать:"

    await update.message.reply_text(
        greeting,
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

    return SELECTING_ACTION


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation"""
    await track_user_activity(update)

    user = update.effective_user
    greeting = f"Привет, {user.first_name}! 👋\n\n" \
               "Я помогу тебе найти информацию о расписании аудиторий.\n" \
               "Выбери, что ты хочешь сделать:"

    return await show_main_menu(update, context, greeting)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show menu (same as start but without greeting)"""
    await track_user_activity(update)

    greeting = "Главное меню:\n" \
               "Выбери, что ты хочешь сделать:"

    return await show_main_menu(update, context, greeting)


async def select_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle action selection"""
    await track_user_activity(update)

    text = update.message.text
    user_id = update.effective_user.id

    has_last_building = 'last_building' in context.user_data

    if text.startswith("1."):
        context.user_data["action"] = "view_schedule"

        if has_last_building:
            last_building = context.user_data['last_building']
            await update.message.reply_text(
                f"В прошлый раз вы выбирали корпус {last_building}.\n"
                f"Выберите корпус:",
                reply_markup=get_buildings_keyboard(last_building)
            )
        else:
            await update.message.reply_text(
                "Выбери корпус:",
                reply_markup=get_buildings_keyboard()
            )
        return SELECT_BUILDING

    elif text.startswith("2."):
        context.user_data["action"] = "find_available_moment"

        if has_last_building:
            last_building = context.user_data['last_building']
            await update.message.reply_text(
                f"В прошлый раз вы выбирали корпус {last_building}.\n"
                f"Выберите корпус для поиска свободной аудитории на одну пару:",
                reply_markup=get_buildings_keyboard(last_building)
            )
        else:
            await update.message.reply_text(
                "Выбери корпус для поиска свободной аудитории на одну пару:",
                reply_markup=get_buildings_keyboard()
            )
        return SELECT_BUILDING

    elif text.startswith("3."):
        context.user_data["action"] = "find_available_range"

        if has_last_building:
            last_building = context.user_data['last_building']
            await update.message.reply_text(
                f"В прошлый раз вы выбирали корпус {last_building}.\n"
                f"Выберите корпус для поиска свободной аудитории на несколько пар подряд:",
                reply_markup=get_buildings_keyboard(last_building)
            )
        else:
            await update.message.reply_text(
                "Выбери корпус для поиска свободной аудитории на несколько пар подряд:",
                reply_markup=get_buildings_keyboard()
            )
        return SELECT_BUILDING

    elif text == "👑 Панель администратора":
        if user_db.is_admin(user_id):
            await update.message.reply_text(
                "👑 *Панель администратора*\n\n"
                "Выберите действие:",
                parse_mode="Markdown",
                reply_markup=get_admin_keyboard()
            )
            return ADMIN_MENU
        else:
            await update.message.reply_text("У вас нет прав администратора.")
            return SELECTING_ACTION

    else:
        await update.message.reply_text(
            "Пожалуйста, выбери один из вариантов, используя кнопки."
        )
        return SELECTING_ACTION


# Rest of the handlers remain largely the same but use new database functions
async def select_building(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle building selection"""
    if update.callback_query:
        await track_user_activity(update)

    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    building_id = query.data.split("_")[1]
    context.user_data["building"] = building_id

    if context.user_data["action"] == "view_schedule":
        rooms_keyboard = get_rooms_keyboard(building_id)
        if rooms_keyboard:
            await query.edit_message_text(
                f"Выбран корпус: {building_id}\nТеперь выбери аудиторию:",
                reply_markup=rooms_keyboard
            )
            return SELECT_ROOM
        else:
            await query.edit_message_text("В данном корпусе нет доступных аудиторий.")
            return ConversationHandler.END
    else:
        current_week = calculate_current_academic_week()
        context.user_data["current_week"] = current_week

        await query.edit_message_text(
            f"Выбран корпус: {building_id}\nВыбери учебную неделю:",
            reply_markup=get_week_keyboard(current_week)
        )
        return SELECT_WEEK


async def select_room(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle room selection"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    if query.data == "back_to_buildings":
        await query.edit_message_text(
            "Выбери корпус:",
            reply_markup=get_buildings_keyboard()
        )
        return SELECT_BUILDING

    room_id = query.data.split("_")[1]
    context.user_data["room"] = room_id

    current_week = calculate_current_academic_week()
    context.user_data["current_week"] = current_week

    await query.edit_message_text(
        f"Выбрана аудитория: {room_id}\nТеперь выбери учебную неделю:",
        reply_markup=get_week_keyboard(current_week)
    )
    return SELECT_WEEK


async def select_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle week selection and navigation"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    parts = query.data.split("_")
    action = parts[1]

    if action == "prev":
        current_week = int(parts[2])
        new_week = max(1, current_week - 1)
        await query.edit_message_text(
            "Выбери учебную неделю:",
            reply_markup=get_week_keyboard(new_week)
        )
        return SELECT_WEEK

    elif action == "next":
        current_week = int(parts[2])
        new_week = current_week + 1
        await query.edit_message_text(
            "Выбери учебную неделю:",
            reply_markup=get_week_keyboard(new_week)
        )
        return SELECT_WEEK

    else:
        week_number = int(parts[1])
        context.user_data["academic_week"] = week_number

        await query.edit_message_text(
            f"Выбрана учебная неделя: {week_number}\nТеперь выбери день недели:",
            reply_markup=get_days_keyboard(week_number)
        )
        return SELECT_DAY


async def select_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle day selection"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    if query.data == "back_to_weeks":
        current_week = context.user_data.get("current_week", calculate_current_academic_week())
        await query.edit_message_text(
            "Выбери учебную неделю:",
            reply_markup=get_week_keyboard(current_week)
        )
        return SELECT_WEEK

    # Extract date info from callback data
    parts = query.data.split("_")
    weekday = parts[1]
    date_str = parts[2]

    context.user_data["weekday"] = weekday
    context.user_data["date"] = date_str

    academic_week = context.user_data["academic_week"]

    if context.user_data["action"] == "view_schedule":
        # Show schedule using new database
        building = context.user_data["building"]
        room = context.user_data["room"]

        schedule = get_schedule_for_day_new(building, room, date_str, academic_week)

        await query.edit_message_text(
            schedule,
            reply_markup=get_results_keyboard(context)
        )
        return HANDLE_RESULTS
    else:
        # Ask for start time
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        date_formatted = date_obj.strftime("%d.%m.%Y")

        await query.edit_message_text(
            f"Выбрана дата: {date_formatted} ({weekday}), неделя {academic_week}\n"
            f"Выбери пару или время:",
            reply_markup=get_time_keyboard()
        )
        return SELECT_TIME_START


async def select_time_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle start time selection"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    parts = query.data.split("_")
    start_time = parts[1]
    context.user_data["start_time"] = start_time

    if len(parts) > 2:
        end_time = parts[2]
        context.user_data["class_end_time"] = end_time

    academic_week = context.user_data["academic_week"]

    if context.user_data["action"] == "find_available_moment":
        # For single time check, use new database function
        building = context.user_data["building"]
        date = context.user_data["date"]

        if len(parts) > 2:
            end_time = parts[2]
            available_rooms = find_available_rooms_new(building, date, start_time, end_time, academic_week)
        else:
            available_rooms = find_available_rooms_new(building, date, start_time, None, academic_week)

        await query.edit_message_text(
            available_rooms,
            reply_markup=get_results_keyboard(context)
        )
        return HANDLE_RESULTS
    else:
        # For time range, show keyboard to select end time
        class_periods = get_class_periods()
        start_index = None

        # Find the index of the selected start time
        for i, (label, begin, end) in enumerate(class_periods):
            if begin == start_time:
                start_index = i
                break

        if start_index is None:
            await query.edit_message_text("Ошибка при определении начальной пары.")
            return ConversationHandler.END

        await query.edit_message_text(
            f"Начальная пара: {class_periods[start_index][0]}\n\nТеперь выберите конечную пару:",
            reply_markup=get_end_time_keyboard(start_index)
        )
        return SELECT_TIME_END


async def select_time_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle end time selection for time range"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    # Extract end time from callback data
    parts = query.data.split("_")
    end_time = parts[1]

    # Get data from context
    building = context.user_data["building"]
    date = context.user_data["date"]
    start_time = context.user_data["start_time"]
    academic_week = context.user_data["academic_week"]

    # Find available rooms for the time range
    available_rooms = find_available_rooms_new(building, date, start_time, end_time, academic_week)

    await query.edit_message_text(
        available_rooms,
        reply_markup=get_results_keyboard(context)
    )
    return HANDLE_RESULTS


# Navigation handlers
async def handle_results_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle navigation from results screen"""
    query = update.callback_query
    await query.answer()

    if query.data == "new_search":
        if 'building' in context.user_data:
            last_building = context.user_data['building']
            context.user_data.clear()
            context.user_data['last_building'] = last_building
        else:
            context.user_data.clear()

        await query.edit_message_text("Начинаем новый поиск...", reply_markup=None)

        keyboard = [
            ["1. Посмотреть расписание аудитории"],
            ["2. Найти свободные аудитории (на одну пару)"],
            ["3. Найти свободные аудитории (на несколько пар)"]
        ]

        if user_db.is_admin(update.effective_user.id):
            keyboard.append(["👑 Панель администратора"])

        await query.message.reply_text(
            "Выбери, что ты хочешь сделать:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return SELECTING_ACTION

    elif query.data == "different_day":
        academic_week = context.user_data.get("academic_week", calculate_current_academic_week())
        await query.edit_message_text(
            "Выбери день недели:",
            reply_markup=get_days_keyboard(academic_week)
        )
        return SELECT_DAY

    elif query.data == "different_room":
        building = context.user_data["building"]
        rooms_keyboard = get_rooms_keyboard(building)
        if rooms_keyboard:
            await query.edit_message_text(
                f"Выбери аудиторию в корпусе {building}:",
                reply_markup=rooms_keyboard
            )
            return SELECT_ROOM
        else:
            await query.edit_message_text("Нет доступных аудиторий.")
            return ConversationHandler.END

    elif query.data == "different_building":
        current_building = context.user_data.get("building")
        await query.edit_message_text(
            "Выбери корпус:",
            reply_markup=get_buildings_keyboard(current_building)
        )
        return SELECT_BUILDING

    elif query.data == "different_time":
        date_str = context.user_data.get("date")
        weekday = context.user_data.get("weekday")
        academic_week = context.user_data.get("academic_week")

        if date_str and weekday and academic_week:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            date_formatted = date_obj.strftime("%d.%m.%Y")

            await query.edit_message_text(
                f"Выбрана дата: {date_formatted} ({weekday}), неделя {academic_week}\n"
                f"Выбери пару или время:",
                reply_markup=get_time_keyboard()
            )
            return SELECT_TIME_START
        else:
            await query.edit_message_text(
                "Произошла ошибка. Пожалуйста, начните поиск заново.",
                reply_markup=None
            )
            return ConversationHandler.END


# Admin handlers
async def handle_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle admin panel menu selection"""
    query = update.callback_query
    await query.answer()

    if query.data == "schedule_stats":
        # Get schedule database statistics
        stats = schedule_db.get_stats()

        stats_text = (
            "🗄️ *Статистика базы данных расписания*\n\n"
            f"🏢 Корпусов: {stats['buildings']}\n"
            f"🚪 Аудиторий: {stats['rooms']}\n"
            f"📚 Дисциплин: {stats['disciplines']}\n"
            f"👨‍🏫 Преподавателей: {stats['teachers']}\n"
            f"👥 Групп: {stats['groups']}\n"
            f"📅 Записей расписания: {stats['schedule']}\n\n"
        )

        await query.edit_message_text(
            stats_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="back_to_admin")
            ]])
        )
        return ADMIN_MENU

    elif query.data == "user_stats":
        # Get user statistics
        stats = user_db.get_user_stats()

        stats_text = (
            "📊 *Статистика пользователей*\n\n"
            f"👥 Всего пользователей: {stats['total']}\n"
            f"🟢 Активных (30 дней): {stats['active_30_days']}\n"
            f"🔔 С включенными уведомлениями: {stats['with_notifications']}\n"
            f"👑 Администраторов: {stats['admins']}\n"
        )

        await query.edit_message_text(
            stats_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="back_to_admin")
            ]])
        )
        return ADMIN_MENU

    elif query.data == "broadcast":
        # Start broadcast flow
        await query.edit_message_text(
            "📢 *Отправка уведомления*\n\n"
            "Введите текст уведомления, которое будет отправлено всем пользователям.\n"
            "Используйте /cancel для отмены.",
            parse_mode="Markdown"
        )
        return ADMIN_BROADCAST

    elif query.data == "back_to_admin":
        await query.edit_message_text(
            "👑 *Панель администратора*\n\n"
            "Выберите действие:",
            parse_mode="Markdown",
            reply_markup=get_admin_keyboard()
        )
        return ADMIN_MENU

    elif query.data == "back_to_menu":
        # Return to main menu
        user_id = update.effective_user.id
        keyboard = [
            ["1. Посмотреть расписание аудитории"],
            ["2. Найти свободные аудитории (на одну пару)"],
            ["3. Найти свободные аудитории (на несколько пар)"]
        ]

        if user_db.is_admin(user_id):
            keyboard.append(["👑 Панель администратора"])

        await query.message.reply_text(
            "Выбери, что ты хочешь сделать:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        await query.edit_message_text("Возвращаемся в главное меню...")
        return SELECTING_ACTION

    return ADMIN_MENU


async def handle_admin_broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broadcast message text input"""
    await track_user_activity(update)

    text = update.message.text
    context.user_data["broadcast_text"] = text

    # Get user count for confirmation
    users = user_db.get_all_users()
    user_count = len(users)

    keyboard = [
        [InlineKeyboardButton("✅ Да, отправить", callback_data="confirm_broadcast")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_broadcast")]
    ]

    await update.message.reply_text(
        f"📢 *Подтверждение отправки*\n\n"
        f"Текст уведомления:\n{text}\n\n"
        f"Будет отправлено *{user_count}* пользователям.\n\n"
        f"Подтвердите отправку:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_CONFIRM_BROADCAST


async def handle_admin_broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broadcast confirmation"""
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_broadcast":
        broadcast_text = context.user_data.get("broadcast_text")
        if not broadcast_text:
            await query.edit_message_text("❌ Ошибка: текст уведомления не найден.")
            return ConversationHandler.END

        # Get all users
        users = user_db.get_all_users()
        sent_count = 0
        failed_count = 0

        await query.edit_message_text(
            f"📤 Отправка уведомления {len(users)} пользователям...\n"
            "Пожалуйста, подождите."
        )

        # Send to all users
        for user in users:
            try:
                await context.bot.send_message(
                    chat_id=user['user_id'],
                    text=f"📢 *Уведомление от администратора*\n\n{broadcast_text}",
                    parse_mode="Markdown"
                )
                sent_count += 1
                # Small delay to avoid hitting rate limits
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Failed to send broadcast to user {user['user_id']}: {e}")
                failed_count += 1

        # Show results
        result_text = (
            f"✅ *Рассылка завершена*\n\n"
            f"Отправлено: {sent_count}\n"
            f"Не удалось отправить: {failed_count}"
        )

        await query.message.reply_text(
            result_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад в панель", callback_data="back_to_admin")
            ]])
        )
        return ADMIN_MENU

    elif query.data == "cancel_broadcast":
        await query.edit_message_text(
            "❌ Рассылка отменена.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад в панель", callback_data="back_to_admin")
            ]])
        )
        return ADMIN_MENU

    return ADMIN_MENU


# Cancel and help handlers (similar to original)
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel and end the conversation"""
    if update.message:
        await update.message.reply_text(
            "Операция отменена.", reply_markup=ReplyKeyboardRemove()
        )
    else:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Операция отменена.")

    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help message"""
    await track_user_activity(update)

    help_text = (
        "🤖 *Помощь по использованию бота*\n\n"
        "Этот бот поможет вам найти информацию о расписании аудиторий Самарского университета.\n\n"
        "*Доступные команды:*\n"
        "/start - Начать работу с ботом\n"
        "/menu - Показать главное меню\n"
        "/help - Показать это сообщение\n"
        "/cancel - Отменить текущую операцию\n\n"
        "*Возможности:*\n"
        "1️⃣ Просмотр расписания конкретной аудитории\n"
        "2️⃣ Поиск свободных аудиторий на одну пару\n"
        "3️⃣ Поиск свободных аудиторий на несколько пар\n\n"
        "Используйте кнопки для навигации по меню."
    )

    await update.message.reply_text(help_text, parse_mode="Markdown")


def main() -> None:
    """Start the bot"""
    logger.info("Starting enhanced SSAU Schedule Bot...")

    # Create the Application
    application = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("menu", menu),
        ],
        states={
            SELECTING_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_action)],
            SELECT_BUILDING: [CallbackQueryHandler(select_building)],
            SELECT_ROOM: [CallbackQueryHandler(select_room)],
            SELECT_WEEK: [CallbackQueryHandler(select_week)],
            SELECT_DAY: [CallbackQueryHandler(select_day)],
            SELECT_TIME_START: [CallbackQueryHandler(select_time_start)],
            SELECT_TIME_END: [CallbackQueryHandler(select_time_end)],
            HANDLE_RESULTS: [CallbackQueryHandler(handle_results_navigation)],
            ADMIN_MENU: [CallbackQueryHandler(handle_admin_menu)],
            ADMIN_BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_broadcast_text)],
            ADMIN_CONFIRM_BROADCAST: [CallbackQueryHandler(handle_admin_broadcast_confirm)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
            CommandHandler("menu", menu),
        ],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))

    # Run the bot
    logger.info("Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    finally:
        # Close database connections
        user_db.close()
        schedule_db.close()