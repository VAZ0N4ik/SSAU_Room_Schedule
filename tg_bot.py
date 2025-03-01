import logging
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, \
    ConversationHandler, filters
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

"""Игнорируем ВУЦ и Спорткомплекс"""
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
) = range(10)

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

# Reverse weekday translation for converting from Russian to day number
WEEKDAY_TO_NUMBER = {
    "понедельник": 0,
    "вторник": 1,
    "среда": 2,
    "четверг": 3,
    "пятница": 4,
    "суббота": 5,
    "воскресенье": 6
}

# Path to the data file
DATA_FILE = "occupied_rooms.json"

# Global data store
occupied_rooms = {}

# Semester start date (for calculating academic weeks)
SEMESTER_START = "2024-09-02"

async def commands_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available commands when /commands is issued."""
    commands_text = (
        "📋 *Доступные команды бота:*\n\n"
        "/start - Начать работу с ботом\n"
        "/menu - Показать главное меню\n"
        "/help - Подробная справка по использованию\n"
        "/commands - Показать эту справку по командам\n"
        "/cancel - Отменить текущую операцию\n\n"

        "💡 *Совет:* Эти команды также доступны в меню бота (нажмите на значок '/' в поле ввода)"
    )
    await update.message.reply_text(commands_text, parse_mode="Markdown")

def calculate_current_academic_week():
    """Calculate the current academic week based on semester start"""
    today = datetime.now()
    semester_start_date = datetime.strptime(SEMESTER_START, "%Y-%m-%d")

    # Calculate days since semester start
    delta_days = (today - semester_start_date).days

    # Calculate current academic week
    if delta_days < 0:
        return 1  # If before semester start, return week 1

    current_week = (delta_days // 7) + 1
    return current_week


def load_data():
    """Load room occupation data from file"""
    global occupied_rooms
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            occupied_rooms = json.load(f)
        logger.info(f"Loaded data for {len(occupied_rooms)} buildings")
    except FileNotFoundError:
        logger.error(f"Data file {DATA_FILE} not found!")
        occupied_rooms = {}
    except json.JSONDecodeError:
        logger.error(f"Error parsing data file {DATA_FILE}")
        occupied_rooms = {}


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

    # Get class periods
    class_periods = get_class_periods()

    for label, start_time, end_time in class_periods:
        keyboard.append([InlineKeyboardButton(
            label,
            callback_data=f"time_{start_time}_{end_time}"
        )])

    # Add cancel button
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_end_period_keyboard(start_period):
    """Create keyboard with end period options based on start period"""
    keyboard = []

    # Get class periods
    class_periods = get_class_periods()

    # Only show periods that come after the start period
    for i, (label, start_time, end_time) in enumerate(class_periods):
        period_num = i + 1  # Period numbers are 1-based
        if period_num >= start_period:
            keyboard.append([InlineKeyboardButton(
                label,
                callback_data=f"end_period_{period_num}"
            )])

    # Add cancel button
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_buildings_keyboard(highlight_building=None):
    """Create keyboard with building options, with optional highlighting and proper sorting"""
    # Получаем все корпуса и фильтруем, исключая игнорируемые
    all_buildings = list(occupied_rooms.keys())
    buildings = [building for building in all_buildings if building not in IGNORED_BUILDINGS]

    # Sort buildings numerically (treating them as integers where possible)
    def building_sort_key(building):
        # Convert all buildings to strings first to ensure consistent comparison
        building_str = str(building)
        try:
            # Try to convert to integer for proper numerical sorting
            return (0, int(building_str))  # Tuple with 0 as first element for numbers
        except ValueError:
            # If not a number, use a tuple with 1 as first element to keep strings after numbers
            return (1, building_str)

    sorted_buildings = sorted(buildings, key=building_sort_key)

    keyboard = []
    row = []
    for i, building in enumerate(sorted_buildings):
        # Add ✓ symbol to the previously selected building
        label = f"✓ {building}" if building == highlight_building else building
        row.append(InlineKeyboardButton(label, callback_data=f"building_{building}"))
        if (i + 1) % 3 == 0 or i == len(sorted_buildings) - 1:  # 3 buttons per row
            keyboard.append(row)
            row = []

    # Add cancel button
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_rooms_keyboard(building):
    """Create keyboard with room options for a specific building"""
    if building not in occupied_rooms:
        return None

    rooms = sorted(occupied_rooms[building].keys())
    keyboard = []
    row = []
    for i, room in enumerate(rooms):
        # Just show room number without building
        room_display = room.split('-')[0]
        row.append(InlineKeyboardButton(room_display, callback_data=f"room_{room}"))
        if (i + 1) % 4 == 0 or i == len(rooms) - 1:  # 4 buttons per row
            keyboard.append(row)
            row = []

    # Add back and cancel buttons
    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="back_to_buildings"),
        InlineKeyboardButton("Отмена", callback_data="cancel")
    ])
    return InlineKeyboardMarkup(keyboard)


def get_week_keyboard(current_week):
    """Create keyboard for selecting academic week"""
    keyboard = []

    # Add navigation row first with current week indicator
    nav_row = [
        InlineKeyboardButton("⬅️", callback_data=f"week_prev_{current_week}"),
        InlineKeyboardButton(f"Неделя {current_week}", callback_data=f"week_{current_week}"),
        InlineKeyboardButton("➡️", callback_data=f"week_next_{current_week}")
    ]
    keyboard.append(nav_row)

    # Add weeks around current week (2 before and 2 after if possible)
    weeks_row = []
    for week_num in range(max(1, current_week - 2), current_week + 3):
        if week_num != current_week:  # Skip current week as it's already in nav row
            weeks_row.append(InlineKeyboardButton(str(week_num), callback_data=f"week_{week_num}"))

    # Add weeks in a single row
    if weeks_row:
        keyboard.append(weeks_row)

    # Add cancel button
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_days_keyboard(week_number):
    """Create keyboard with day options for a specific week, excluding Sunday"""
    keyboard = []

    # Calculate date range for selected week
    semester_start = datetime.strptime(SEMESTER_START, "%Y-%m-%d")
    week_start = semester_start + timedelta(days=(week_number - 1) * 7)

    # Show only 6 days of the week (Monday through Saturday)
    for day_offset in range(6):  # 0-5 instead of 0-6
        date = week_start + timedelta(days=day_offset)
        date_str = date.strftime("%d.%m.%Y")
        day_name = WEEKDAY_TRANSLATION[date.weekday()]
        label = f"{date_str} ({day_name})"

        # Store both weekday name and date in callback data
        callback_data = f"day_{day_name}_{date.strftime('%Y-%m-%d')}"
        keyboard.append([InlineKeyboardButton(label, callback_data=callback_data)])

    # Add back and cancel buttons
    keyboard.append([
        InlineKeyboardButton("⬅️ Назад к выбору недели", callback_data="back_to_weeks"),
        InlineKeyboardButton("Отмена", callback_data="cancel")
    ])
    return InlineKeyboardMarkup(keyboard)


def get_academic_week(date_str, semester_start=SEMESTER_START):
    """Calculate academic week number from a date"""
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    semester_start_date = datetime.strptime(semester_start, "%Y-%m-%d")

    delta_days = (date_obj - semester_start_date).days
    if delta_days < 0:
        return None

    return (delta_days // 7) + 1


def get_schedule_for_day(building_name, room_name, date_str, academic_week=None):
    """Get schedule for a specific room on a specific date"""
    if academic_week is None:
        academic_week = get_academic_week(date_str)

    if academic_week is None:
        return f"Дата {date_str} находится до начала семестра."

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAY_TRANSLATION[date_obj.weekday()]

    if building_name not in occupied_rooms:
        return f"Здание {building_name} не найдено."

    building = occupied_rooms[building_name]

    if room_name not in building:
        return f"Комната {room_name} не найдена в {building_name}."

    room_schedule = building[room_name]

    # Filter lessons by week and weekday
    filtered_lessons = [
        lesson for lesson in room_schedule
        if lesson["weekday"] == weekday and lesson["week"] == academic_week
    ]

    # Deduplicate lessons based on time, discipline, groups and teachers
    unique_lessons = []
    seen_lessons = set()

    for lesson in filtered_lessons:
        # Create a unique key for each lesson based on its contents
        lesson_key = (
            lesson["begin_time"],
            lesson["end_time"],
            lesson["discipline"],
            tuple(sorted(lesson["groups"])),
            tuple(sorted(lesson["teacher"]))
        )

        if lesson_key not in seen_lessons:
            seen_lessons.add(lesson_key)
            unique_lessons.append(lesson)

    # Sort lessons by begin time
    sorted_lessons = sorted(unique_lessons, key=lambda lesson: lesson["begin_time"])

    # Format schedule message
    date_formatted = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    result = f"📅 Расписание аудитории {room_name} ({building_name} корпус)\n"
    result += f"🗓️ Дата: {date_formatted} ({weekday})\n"
    result += f"📊 Учебная неделя: {academic_week}\n\n"

    if not sorted_lessons:
        result += "🕓 На этот день занятий нет."
        return result

    for i, lesson in enumerate(sorted_lessons, 1):
        result += f"{i}. ⏰ {lesson['begin_time']} - {lesson['end_time']}\n"
        result += f"   📚 {lesson['discipline']}\n"
        result += f"   👥 Группы: {', '.join(lesson['groups'])}\n"
        result += f"   👨‍🏫 Преподаватели: {', '.join(lesson['teacher'])}\n\n"

    return result


def find_available_rooms(building_name, date_str, start_time, end_time=None, academic_week=None):
    """Find available rooms in a building at a specific time range"""
    if academic_week is None:
        academic_week = get_academic_week(date_str)

    if academic_week is None:
        return f"Дата {date_str} находится до начала семестра."

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAY_TRANSLATION[date_obj.weekday()]

    if building_name not in occupied_rooms:
        return f"Здание {building_name} не найдено."

    building = occupied_rooms[building_name]

    start_time_obj = datetime.strptime(start_time, "%H:%M")
    if end_time:
        end_time_obj = datetime.strptime(end_time, "%H:%M")
    else:
        # If no end time provided, use start time + 1.5 hours
        end_time_obj = start_time_obj + timedelta(hours=1, minutes=30)
        end_time = end_time_obj.strftime("%H:%M")

    available_rooms = []

    for room_name, room_schedule in building.items():
        is_room_available = True

        for lesson in room_schedule:
            if lesson["weekday"] == weekday and lesson["week"] == academic_week:
                lesson_begin = datetime.strptime(lesson["begin_time"], "%H:%M")
                lesson_end = datetime.strptime(lesson["end_time"], "%H:%M")

                # Check for overlap
                if (lesson_begin < end_time_obj and lesson_end > start_time_obj):
                    is_room_available = False
                    break

        if is_room_available:
            # Just use room number without building
            room_display = room_name.split('-')[0]
            available_rooms.append(room_display)

    # Format response
    date_formatted = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    result = f"🔍 Свободные аудитории в {building_name} корпусе\n"
    result += f"📅 Дата: {date_formatted} ({weekday})\n"
    result += f"📊 Учебная неделя: {academic_week}\n"
    result += f"⏰ Время: {start_time}"
    if end_time:
        result += f" - {end_time}"
    result += "\n\n"

    if available_rooms:
        # Group rooms by floor
        rooms_by_floor = {}
        for room in available_rooms:
            # Try to extract floor from room number (first digit)
            try:
                floor = room[0]
                if floor not in rooms_by_floor:
                    rooms_by_floor[floor] = []
                rooms_by_floor[floor].append(room)
            except (IndexError, ValueError):
                # If can't determine floor, put in "Other"
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


def find_available_rooms_for_period_range(building_name, date_str, start_period, end_period, academic_week=None):
    """Find rooms available for the entire period range from start_period to end_period"""
    if academic_week is None:
        academic_week = get_academic_week(date_str)

    if academic_week is None:
        return f"Дата {date_str} находится до начала семестра."

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAY_TRANSLATION[date_obj.weekday()]

    if building_name not in occupied_rooms:
        return f"Здание {building_name} не найдено."

    building = occupied_rooms[building_name]

    # Get class periods
    class_periods = get_class_periods()

    # Get start time of the first period and end time of the last period
    start_time = class_periods[start_period - 1][1]  # First period's start time
    end_time = class_periods[end_period - 1][2]  # Last period's end time

    start_time_obj = datetime.strptime(start_time, "%H:%M")
    end_time_obj = datetime.strptime(end_time, "%H:%M")

    available_rooms = []

    for room_name, room_schedule in building.items():
        is_room_available = True

        for lesson in room_schedule:
            if lesson["weekday"] == weekday and lesson["week"] == academic_week:
                lesson_begin = datetime.strptime(lesson["begin_time"], "%H:%M")
                lesson_end = datetime.strptime(lesson["end_time"], "%H:%M")

                # Check for any overlap in the entire period range
                # If there's any overlap between this lesson and our period range, room is not available
                if (lesson_begin < end_time_obj and lesson_end > start_time_obj):
                    is_room_available = False
                    break

        if is_room_available:
            # Just use room number without building
            room_display = room_name.split('-')[0]
            available_rooms.append(room_display)

    # Format response
    date_formatted = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    result = f"🔍 Свободные аудитории в {building_name} корпусе\n"
    result += f"📅 Дата: {date_formatted} ({weekday})\n"
    result += f"📊 Учебная неделя: {academic_week}\n"
    result += f"⏰ Время: с {start_time} до {end_time} ({start_period}-{end_period} пары)\n\n"

    if available_rooms:
        # Group rooms by floor
        rooms_by_floor = {}
        for room in available_rooms:
            # Try to extract floor from room number (first digit)
            try:
                floor = room[0]
                if floor not in rooms_by_floor:
                    rooms_by_floor[floor] = []
                rooms_by_floor[floor].append(room)
            except (IndexError, ValueError):
                # If can't determine floor, put in "Other"
                if "Other" not in rooms_by_floor:
                    rooms_by_floor["Other"] = []
                rooms_by_floor["Other"].append(room)

        # Format rooms by floor
        for floor, rooms in sorted(rooms_by_floor.items()):
            result += f"🔹 {floor} этаж: {', '.join(sorted(rooms))}\n"

        result += f"\nВсего найдено: {len(available_rooms)} аудиторий"
    else:
        result += "😔 Нет свободных аудиторий на весь указанный период."

    return result


# Новая функция для создания клавиатуры после отображения результатов
def get_results_keyboard(context):
    """Create keyboard with navigation options after showing results."""
    keyboard = []

    # Опции зависят от текущего действия
    action = context.user_data.get("action", "")

    if action == "view_schedule":
        # Для просмотра расписания аудитории
        keyboard.append([
            InlineKeyboardButton("📅 Другой день", callback_data="different_day"),
            InlineKeyboardButton("🚪 Другая аудитория", callback_data="different_room")
        ])
        keyboard.append([
            InlineKeyboardButton("🏢 Другой корпус", callback_data="different_building"),
            InlineKeyboardButton("🔄 Новый поиск", callback_data="new_search")
        ])
    else:
        # Для поиска свободных аудиторий
        keyboard.append([
            InlineKeyboardButton("📅 Другой день", callback_data="different_day"),
            InlineKeyboardButton("⏰ Другое время", callback_data="different_time")
        ])
        keyboard.append([
            InlineKeyboardButton("🏢 Другой корпус", callback_data="different_building"),
            InlineKeyboardButton("🔄 Новый поиск", callback_data="new_search")
        ])

    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation."""
    user = update.effective_user
    user_id = update.effective_user.id

    # Preserve the last building if it exists
    last_building = None
    if 'building' in context.user_data:
        last_building = context.user_data['building']

    # Reset user data for a new session but keep the last building
    context.user_data.clear()

    # Restore the last building
    if last_building:
        context.user_data['last_building'] = last_building

    keyboard = [
        ["1. Посмотреть расписание аудитории"],
        ["2. Найти свободные аудитории (на одну пару)"],
        ["3. Найти свободные аудитории (на несколько пар)"]  # Раскомментировано
    ]

    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "Я помогу тебе найти информацию о расписании аудиторий.\n"
        "Выбери, что ты хочешь сделать:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

    return SELECTING_ACTION


async def select_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle action selection."""
    text = update.message.text

    # Check if we have a last building
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

    else:
        await update.message.reply_text(
            "Пожалуйста, выбери один из вариантов, используя кнопки."
        )
        return SELECTING_ACTION


async def select_building(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle building selection."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    # Extract building ID from callback data
    building_id = query.data.split("_")[1]
    context.user_data["building"] = building_id

    if context.user_data["action"] == "view_schedule":
        await query.edit_message_text(
            f"Выбран корпус: {building_id}\nТеперь выбери аудиторию:",
            reply_markup=get_rooms_keyboard(building_id)
        )
        return SELECT_ROOM
    else:
        # Get current academic week
        current_week = calculate_current_academic_week()
        context.user_data["current_week"] = current_week

        await query.edit_message_text(
            f"Выбран корпус: {building_id}\nВыбери учебную неделю:",
            reply_markup=get_week_keyboard(current_week)
        )
        return SELECT_WEEK


async def select_room(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle room selection."""
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

    # Extract room ID from callback data
    room_id = query.data.split("_")[1]
    context.user_data["room"] = room_id

    # Get current academic week
    current_week = calculate_current_academic_week()
    context.user_data["current_week"] = current_week

    await query.edit_message_text(
        f"Выбрана аудитория: {room_id}\nТеперь выбери учебную неделю:",
        reply_markup=get_week_keyboard(current_week)
    )
    return SELECT_WEEK


async def select_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle week selection and navigation."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    parts = query.data.split("_")
    action = parts[1]

    if action == "prev":
        # Handle previous week button
        current_week = int(parts[2])
        new_week = max(1, current_week - 1)

        await query.edit_message_text(
            "Выбери учебную неделю:",
            reply_markup=get_week_keyboard(new_week)
        )
        return SELECT_WEEK

    elif action == "next":
        # Handle next week button
        current_week = int(parts[2])
        new_week = current_week + 1

        await query.edit_message_text(
            "Выбери учебную неделю:",
            reply_markup=get_week_keyboard(new_week)
        )
        return SELECT_WEEK

    else:
        # Week selected
        week_number = int(parts[1])
        context.user_data["academic_week"] = week_number

        await query.edit_message_text(
            f"Выбрана учебная неделя: {week_number}\nТеперь выбери день недели:",
            reply_markup=get_days_keyboard(week_number)
        )
        return SELECT_DAY


async def select_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle day selection."""
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

    # Extract date info from callback data (format: day_weekday_YYYY-MM-DD)
    parts = query.data.split("_")
    weekday = parts[1]
    date_str = parts[2]

    context.user_data["weekday"] = weekday
    context.user_data["date"] = date_str

    academic_week = context.user_data["academic_week"]

    if context.user_data["action"] == "view_schedule":
        # Show schedule directly
        building = context.user_data["building"]
        room = context.user_data["room"]

        schedule = get_schedule_for_day(building, room, date_str, academic_week)

        # Вместо завершения диалога, предоставляем варианты навигации
        await query.edit_message_text(
            schedule,
            reply_markup=get_results_keyboard(context)
        )
        return HANDLE_RESULTS
    else:
        # Format date for display
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        date_formatted = date_obj.strftime("%d.%m.%Y")

        # Ask for start time
        await query.edit_message_text(
            f"Выбрана дата: {date_formatted} ({weekday}), неделя {academic_week}\n"
            f"Выбери пару или время:",
            reply_markup=get_time_keyboard()
        )
        return SELECT_TIME_START


async def select_time_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle start time selection."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    # Extract time from callback data
    parts = query.data.split("_")
    start_time = parts[1]
    context.user_data["start_time"] = start_time

    # Store end time if it's included (from class period)
    if len(parts) > 2:
        end_time = parts[2]
        context.user_data["class_end_time"] = end_time  # Store class period end time separately

    academic_week = context.user_data["academic_week"]

    if context.user_data["action"] == "find_available_moment":
        # For single time check, use start and end time of selected class period
        building = context.user_data["building"]
        date = context.user_data["date"]

        if len(parts) > 2:
            end_time = parts[2]
            available_rooms = find_available_rooms(building, date, start_time, end_time, academic_week)
        else:
            available_rooms = find_available_rooms(building, date, start_time, None, academic_week)

        # Добавляем клавиатуру с навигацией вместо завершения диалога
        await query.edit_message_text(
            available_rooms,
            reply_markup=get_results_keyboard(context)
        )
        return HANDLE_RESULTS
    else:
        # For time range, ask for end class period
        # Store which class period was selected (extract number from label for later display)
        for i, (label, start, end) in enumerate(get_class_periods()):
            if start == start_time and (
                    not "class_end_time" in context.user_data or end == context.user_data["class_end_time"]):
                context.user_data["start_period"] = i + 1
                break

        # Ask for ending class period
        await query.edit_message_text(
            f"Выбрана начальная пара: {context.user_data['start_period']} пара\n"
            f"Выбери конечную пару:",
            reply_markup=get_end_period_keyboard(context.user_data["start_period"])
        )
        return SELECT_TIME_END


async def select_time_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle end time or end period selection."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    parts = query.data.split("_")

    # Handle end period selection (for third option)
    if parts[0] == "end":
        end_period = int(parts[2])
        context.user_data["end_period"] = end_period

        # Get start period
        start_period = context.user_data["start_period"]

        building = context.user_data["building"]
        date = context.user_data["date"]
        academic_week = context.user_data["academic_week"]

        # Проверка на корректность диапазона
        if end_period < start_period:
            await query.edit_message_text(
                "Ошибка: конечная пара не может быть раньше начальной пары.\n"
                "Пожалуйста, выберите конечную пару снова:",
                reply_markup=get_end_period_keyboard(start_period)
            )
            return SELECT_TIME_END

        # Use the specialized function for period range search
        result = find_available_rooms_for_period_range(building, date, start_period, end_period, academic_week)

        # Добавляем клавиатуру с навигацией
        await query.edit_message_text(
            result,
            reply_markup=get_results_keyboard(context)
        )
        return HANDLE_RESULTS

    # Handle normal time selection
    else:
        # Extract time from callback data
        if len(parts) > 2:
            time = parts[2]  # End time from class period
        else:
            time = parts[1]  # Direct time

        context.user_data["end_time"] = time

        # Validate time range
        start_time = datetime.strptime(context.user_data["start_time"], "%H:%M")
        end_time = datetime.strptime(time, "%H:%M")

        if end_time <= start_time:
            await query.edit_message_text(
                "Ошибка: Время окончания должно быть позже времени начала.\n"
                "Пожалуйста, начните заново. Нажмите /start",
            )
            return ConversationHandler.END

        # Show available rooms for the time range
        building = context.user_data["building"]
        date = context.user_data["date"]
        start_time_str = context.user_data["start_time"]
        academic_week = context.user_data["academic_week"]

        available_rooms = find_available_rooms(building, date, start_time_str, time, academic_week)

        # Добавляем клавиатуру с навигацией
        await query.edit_message_text(
            available_rooms,
            reply_markup=get_results_keyboard(context)
        )
        return HANDLE_RESULTS


# Новый обработчик для навигации после отображения результатов
async def handle_results_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle navigation from results screen."""
    query = update.callback_query
    await query.answer()

    if query.data == "new_search":
        # Начать новый поиск, сохраняя последний корпус
        if 'building' in context.user_data:
            last_building = context.user_data['building']
            context.user_data.clear()
            context.user_data['last_building'] = last_building
        else:
            context.user_data.clear()

        # Сначала удаляем inline кнопки из текущего сообщения
        await query.edit_message_text(
            "Начинаем новый поиск...",
            reply_markup=None
        )

        # Затем отправляем новое сообщение с обычными кнопками
        keyboard = [
            ["1. Посмотреть расписание аудитории"],
            ["2. Найти свободные аудитории (на одну пару)"],
            ["3. Найти свободные аудитории (на несколько пар)"]
        ]

        await query.message.reply_text(
            "Выбери, что ты хочешь сделать:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return SELECTING_ACTION

    elif query.data == "different_day":
        # Показать выбор другого дня, сохраняя контекст корпуса/аудитории
        academic_week = context.user_data.get("academic_week", calculate_current_academic_week())

        await query.edit_message_text(
            "Выбери день недели:",
            reply_markup=get_days_keyboard(academic_week)
        )
        return SELECT_DAY

    elif query.data == "different_room":
        # Показать выбор другой аудитории, сохраняя контекст корпуса
        building = context.user_data["building"]

        await query.edit_message_text(
            f"Выбери аудиторию в корпусе {building}:",
            reply_markup=get_rooms_keyboard(building)
        )
        return SELECT_ROOM

    elif query.data == "different_building":
        # Показать выбор другого корпуса
        current_building = context.user_data.get("building")

        await query.edit_message_text(
            "Выбери корпус:",
            reply_markup=get_buildings_keyboard(current_building)
        )
        return SELECT_BUILDING

    elif query.data == "different_time":
        # Вернуться к выбору времени, сохраняя контекст корпуса/дня
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
            # Если почему-то данные отсутствуют, начать заново
            await query.edit_message_text(
                "Произошла ошибка. Пожалуйста, начните поиск заново.",
                reply_markup=None
            )
            return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel and end the conversation."""
    if update.message:
        await update.message.reply_text(
            "Операция отменена.", reply_markup=ReplyKeyboardRemove()
        )
    else:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Операция отменена.")

    return ConversationHandler.END


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Display the main menu when /menu command is issued."""
    user = update.effective_user

    # Сохраняем последний корпус
    last_building = None
    if 'building' in context.user_data:
        last_building = context.user_data['building']

    # Очищаем данные пользователя, но сохраняем последний корпус
    context.user_data.clear()
    if last_building:
        context.user_data['last_building'] = last_building

    keyboard = [
        ["1. Посмотреть расписание аудитории"],
        ["2. Найти свободные аудитории (на одну пару)"],
        ["3. Найти свободные аудитории (на несколько пар)"]
    ]

    await update.message.reply_text(
        f"Главное меню 📋\n\n"
        "Выбери, что ты хочешь сделать:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

    return SELECTING_ACTION


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = (
        "🤖 *Помощь по использованию бота*\n\n"
        "*Доступные команды:*\n"
        "/start - Начать работу с ботом\n"
        "/menu - Показать главное меню (можно использовать в любой момент)\n"
        "/help - Показать это сообщение\n"
        "/cancel - Отменить текущую операцию\n\n"

        "*Что умеет этот бот:*\n"
        "1️⃣ Показывать расписание для конкретной аудитории на выбранную дату и неделю\n"
        "2️⃣ Находить свободные аудитории в корпусе на одну пару\n"
        "3️⃣ Находить свободные аудитории в корпусе на несколько пар подряд\n\n"

        "*Как пользоваться:*\n"
        "- Используйте /start или /menu для вызова главного меню\n"
        "- Выберите нужный вариант поиска (1, 2 или 3)\n"
        "- Следуйте инструкциям бота, выбирая опции из предложенных кнопок\n"
        "- Сначала выберите корпус, затем учебную неделю, затем день недели\n"
        "- Для навигации по неделям используйте стрелки ⬅️ и ➡️\n\n"

        "*Навигация после получения результатов:*\n"
        "После каждого результата поиска вам предлагаются кнопки для продолжения:\n"
        "- 📅 *Другой день* - посмотреть информацию для другого дня (в том же корпусе/аудитории)\n"
        "- 🚪 *Другая аудитория* - выбрать другую аудиторию в том же корпусе\n"
        "- 🏢 *Другой корпус* - выбрать другой корпус\n"
        "- ⏰ *Другое время* - выбрать другое время для поиска свободных аудиторий\n"
        "- 🔄 *Новый поиск* - начать новый поиск с главного меню\n\n"

        "*Расписание пар:*\n"
        "1 пара: 08:00-09:35\n"
        "2 пара: 09:45-11:20\n"
        "3 пара: 11:30-13:05\n"
        "4 пара: 13:30-15:05\n"
        "5 пара: 15:15-16:50\n"
        "6 пара: 17:00-18:35\n"
        "7 пара: 18:45-20:20\n"
        "8 пара: 20:30-22:05\n\n"

        "*Советы:*\n"
        "- Бот запоминает последний выбранный корпус для более быстрого поиска\n"
        "- Используйте команду /menu вместо /start для быстрого доступа к главному меню\n"
        "- При поиске аудитории на несколько пар, сначала выберите начальную пару, затем конечную\n"
        "- Все команды доступны в меню бота (нажмите на значок '/' в поле ввода)\n"
        "- Используйте /commands для быстрого просмотра списка команд\n\n"

        "Удачного поиска аудиторий! 📚"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def setup_commands(application: Application) -> None:
    """Setup bot commands in Telegram UI."""
    commands = [
        ("start", "Начать работу с ботом"),
        ("menu", "Главное меню"),
        ("help", "Помощь и инструкции"),
        ("commands", "Список доступных команд"),
        ("cancel", "Отменить текущую операцию")
    ]

    await application.bot.set_my_commands(commands)
    logger.info("Bot commands have been set up")


async def post_init(application: Application) -> None:
    """Actions to execute once the bot has started."""
    await setup_commands(application)


def main() -> None:
    """Start the bot."""
    # Load data from file
    load_data()

    # Create the Application using environment variable with post_init callback
    application = Application.builder().token(os.getenv("BOT_TOKEN")).post_init(post_init).build()

    # Add conversation handler with expanded states
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("menu", menu_command),
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
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("menu", menu_command),
        ],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("commands", commands_command))

    # Run the bot until the user presses Ctrl-C
    print("Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()