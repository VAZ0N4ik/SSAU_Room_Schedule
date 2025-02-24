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

# Constants for ConversationHandler states
(
    SELECTING_ACTION,
    SELECT_BUILDING,
    SELECT_ROOM,
    SELECT_DATE,
    SELECT_TIME_START,
    SELECT_TIME_END,
    SHOW_SCHEDULE,
    FIND_AVAILABLE_ROOMS,
) = range(8)

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

# Path to the data file
DATA_FILE = "occupied_rooms.json"

# Global data store
occupied_rooms = {}


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


def get_buildings_keyboard():
    """Create keyboard with building options"""
    buildings = sorted(occupied_rooms.keys())
    keyboard = []
    row = []
    for i, building in enumerate(buildings):
        row.append(InlineKeyboardButton(building, callback_data=f"building_{building}"))
        if (i + 1) % 3 == 0 or i == len(buildings) - 1:  # 3 buttons per row
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


def get_date_keyboard():
    """Create keyboard with date options (next 7 days)"""
    keyboard = []
    today = datetime.now()

    for i in range(7):
        date = today + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        day_name = WEEKDAY_TRANSLATION[date.weekday()]
        label = f"{date_str} ({day_name})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"date_{date.strftime('%Y-%m-%d')}")])

    # Add cancel button
    keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def get_academic_week(date_str, semester_start="2024-09-02"):
    """Calculate academic week number from a date"""
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    semester_start_date = datetime.strptime(semester_start, "%Y-%m-%d")

    delta_days = (date_obj - semester_start_date).days
    if delta_days < 0:
        return None

    return (delta_days // 7) + 1


def get_schedule_for_day(building_name, room_name, date_str):
    """Get schedule for a specific room on a specific date"""
    week = get_academic_week(date_str)
    if week is None:
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
        if lesson["weekday"] == weekday and lesson["week"] == week
    ]

    # Sort lessons by begin time
    sorted_lessons = sorted(filtered_lessons, key=lambda lesson: lesson["begin_time"])

    # Format schedule message
    date_formatted = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    result = f"📅 Расписание аудитории {room_name} ({building_name} корпус)\n"
    result += f"🗓️ Дата: {date_formatted} ({weekday})\n"
    result += f"📊 Учебная неделя: {week}\n\n"

    if not sorted_lessons:
        result += "🕓 На этот день занятий нет."
        return result

    for i, lesson in enumerate(sorted_lessons, 1):
        result += f"{i}. ⏰ {lesson['begin_time']} - {lesson['end_time']}\n"
        result += f"   📚 {lesson['discipline']}\n"
        result += f"   👥 Группы: {', '.join(lesson['groups'])}\n"
        result += f"   👨‍🏫 Преподаватели: {', '.join(lesson['teacher'])}\n\n"

    return result


def find_available_rooms(building_name, date_str, start_time, end_time=None):
    """Find available rooms in a building at a specific time range"""
    week = get_academic_week(date_str)
    if week is None:
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
            if lesson["weekday"] == weekday and lesson["week"] == week:
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


def find_available_rooms_for_period_range(building_name, date_str, start_period, end_period):
    """Find rooms available for the entire period range from start_period to end_period"""
    week = get_academic_week(date_str)
    if week is None:
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
            if lesson["weekday"] == weekday and lesson["week"] == week:
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation."""
    user = update.effective_user

    # Reset user data for a new session
    context.user_data.clear()

    keyboard = [
        ["1. Посмотреть расписание аудитории"],
        ["2. Найти свободные аудитории (на одну пару)"],
        #["3. Найти свободные аудитории (на несколько пар)"]
    ]

    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "Я помогу тебе найти информацию о расписании аудиторий.\n"
        "/help - вывести подсказку.\n"
        "Выбери, что ты хочешь сделать:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

    return SELECTING_ACTION


async def select_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle action selection."""
    text = update.message.text

    if text.startswith("1."):
        context.user_data["action"] = "view_schedule"
        await update.message.reply_text(
            "Выбери корпус:",
            reply_markup=get_buildings_keyboard()
        )
        return SELECT_BUILDING

    elif text.startswith("2."):
        context.user_data["action"] = "find_available_moment"
        await update.message.reply_text(
            "Выбери корпус для поиска свободной аудитории на одну пару:",
            reply_markup=get_buildings_keyboard()
        )
        return SELECT_BUILDING

    elif text.startswith("3."):
        context.user_data["action"] = "find_available_range"
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
        await query.edit_message_text(
            f"Выбран корпус: {building_id}\nВыбери дату:",
            reply_markup=get_date_keyboard()
        )
        return SELECT_DATE


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

    await query.edit_message_text(
        f"Выбрана аудитория: {room_id}\nТеперь выбери дату:",
        reply_markup=get_date_keyboard()
    )
    return SELECT_DATE


async def select_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle date selection."""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Операция отменена.")
        return ConversationHandler.END

    # Extract date from callback data
    date = query.data.split("_")[1]
    context.user_data["date"] = date

    if context.user_data["action"] == "view_schedule":
        # Show schedule directly
        building = context.user_data["building"]
        room = context.user_data["room"]

        schedule = get_schedule_for_day(building, room, date)
        result_text = schedule + "\n\n👉 Нажмите /start чтобы начать новый поиск"
        await query.edit_message_text(result_text)
        return ConversationHandler.END
    else:
        # Format date for display
        date_obj = datetime.strptime(date, "%Y-%m-%d")
        date_formatted = date_obj.strftime("%d.%m.%Y")
        weekday = WEEKDAY_TRANSLATION[date_obj.weekday()]

        # Ask for start time
        await query.edit_message_text(
            f"Выбрана дата: {date_formatted} ({weekday})\n"
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

    if context.user_data["action"] == "find_available_moment":
        # For single time check, use start and end time of selected class period
        building = context.user_data["building"]
        date = context.user_data["date"]

        if len(parts) > 2:
            end_time = parts[2]
            available_rooms = find_available_rooms(building, date, start_time, end_time)
        else:
            available_rooms = find_available_rooms(building, date, start_time)

        result_text = available_rooms + "\n\n👉 Нажмите /start чтобы начать новый поиск"
        await query.edit_message_text(result_text)
        return ConversationHandler.END
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
    if parts[0] == "end_period":
        end_period = int(parts[1])
        context.user_data["end_period"] = end_period

        # Get start period
        start_period = context.user_data["start_period"]

        building = context.user_data["building"]
        date = context.user_data["date"]

        # Use the specialized function for period range search
        result = find_available_rooms_for_period_range(building, date, start_period, end_period)
        result_text = result + "\n\n👉 Нажмите /start чтобы начать новый поиск"
        await query.edit_message_text(result_text)
        return ConversationHandler.END

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

        available_rooms = find_available_rooms(building, date, start_time_str, time)
        result_text = available_rooms + "\n\n👉 Нажмите /start чтобы начать новый поиск"
        await query.edit_message_text(result_text)
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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    help_text = (
        "🤖 *Помощь по использованию бота*\n\n"
        "*Доступные команды:*\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать это сообщение\n\n"

        "*Что умеет этот бот:*\n"
        "1️⃣ Показывать расписание для конкретной аудитории на выбранную дату\n"
        "2️⃣ Находить свободные аудитории в корпусе на одну пару\n"
        "3️⃣ Находить свободные аудитории в корпусе на несколько пар подряд\n\n"

        "*Как пользоваться:*\n"
        "- Нажмите /start и выберите нужный вариант\n"
        "- Следуйте инструкциям бота, выбирая опции из предложенных кнопок\n"
        "- В любой момент можно отменить операцию, нажав кнопку 'Отмена'\n"
        "- После получения результата, нажмите /start чтобы начать новый поиск\n\n"

        "*Расписание пар:*\n"
        "1 пара: 08:00-09:35\n"
        "2 пара: 09:45-11:20\n"
        "3 пара: 11:30-13:05\n"
        "4 пара: 13:30-15:05\n"
        "5 пара: 15:15-16:50\n"
        "6 пара: 17:00-18:35\n"
        "7 пара: 18:45-20:20\n"
        "8 пара: 20:30-22:05\n\n"

        "Удачного поиска аудиторий! 📚"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


def main() -> None:
    """Start the bot."""
    # Load data from file
    load_data()

    # Create the Application using environment variable
    application = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    # Add conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECTING_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_action)],
            SELECT_BUILDING: [CallbackQueryHandler(select_building)],
            SELECT_ROOM: [CallbackQueryHandler(select_room)],
            SELECT_DATE: [CallbackQueryHandler(select_date)],
            SELECT_TIME_START: [CallbackQueryHandler(select_time_start)],
            SELECT_TIME_END: [CallbackQueryHandler(select_time_end)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))

    # Run the bot until the user presses Ctrl-C
    print("Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()