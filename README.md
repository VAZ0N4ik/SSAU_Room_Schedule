# SSAU Room Schedule Bot

Телеграм-бот для просмотра расписания и поиска свободных аудиторий в СГАУ.

## ⚠️ Обновления в версии 2.0

Проект был полностью переработан согласно новым требованиям:

- ✅ **Полный семестр**: Парсинг всех 18 недель вместо только 2х
- ✅ **SQLite база данных**: Замена JSON на нормализованную структуру БД
- ✅ **Автоматическая авторизация**: Поддержка логина/пароля для API
- ✅ **Systemd сервис**: Автоматическое обновление расписания
- ✅ **Оптимизация**: Batch обработка и асинхронный парсинг
- ✅ **Улучшенная архитектура**: Разделение на модули

### Новые файлы:
- `schedule_db.py` - Новая структура базы данных
- `schedule_parser.py` - Улучшенный парсер с полным функционалом
- `schedule_updater.py` - Сервис автообновления
- `tg_bot_new.py` - Обновленный бот для работы с новой БД
- `ssau-schedule-updater.service` - Systemd сервис
- `ssau-schedule-updater.timer` - Systemd таймер
- `install_service.sh` - Скрипт автоустановки

## Возможности

- Просмотр расписания конкретной аудитории на выбранную дату
- Поиск свободных аудиторий в выбранном корпусе на определенное время
- Поиск свободных аудиторий на несколько пар подряд
- Административная панель для отправки уведомлений всем пользователям
- Статистика использования бота
- Управление пользовательскими настройками

## Установка и настройка (Версия 2.0)

### Быстрая установка с systemd (рекомендуется)

Для автоматической установки сервиса выполните:

```bash
sudo ./install_service.sh
```

Этот скрипт автоматически:
- Создаст пользователя системы
- Установит все зависимости
- Настроит systemd сервис
- Настроит автоматическое обновление

### Ручная установка

1. **Установка зависимостей**
   ```bash
   pip install -r requirements.txt
   ```

2. **Настройка переменных окружения**

   Создайте файл `.env` на основе `.env.example`:
   ```bash
   cp .env.example .env
   ```

   Отредактируйте файл `.env`, указав:
   - `BOT_TOKEN` - токен вашего бота от @BotFather
   - `ADMIN_IDS` - ID администраторов, разделенные запятыми
   - `SESSION_ID` - сессионный ID для API (опционально)
   - `SSAU_USERNAME` и `SSAU_PASSWORD` - логин и пароль для автоматической авторизации (рекомендуется)
   - `SEMESTER_START` - дата начала семестра

3. **Инициализация базы данных**

   Для миграции данных из старого JSON:
   ```bash
   python schedule_db.py
   ```

   Для парсинга нового расписания:
   ```bash
   python schedule_parser.py --scrape
   ```

4. **Запуск бота**

   Старая версия:
   ```bash
   python tg_bot.py
   ```

   Новая версия с SQLite:
   ```bash
   python tg_bot_new.py
   ```

### Автоматическое обновление (systemd)

После установки сервиса расписание будет автоматически обновляться ежедневно в 2:00.

Полезные команды:
```bash
# Запустить обновление вручную
sudo systemctl start ssau-schedule-updater.service

# Проверить статус сервиса
sudo systemctl status ssau-schedule-updater.service

# Посмотреть логи
sudo journalctl -u ssau-schedule-updater.service -f

# Проверить таймер
sudo systemctl list-timers ssau-schedule-updater.timer
```

## Команды бота

- `/start` - Начать работу с ботом
- `/menu` - Показать главное меню
- `/help` - Справка по использованию
- `/settings` - Настройки пользователя
- `/commands` - Список доступных команд
- `/admin` - Панель администратора (только для админов)
- `/cancel` - Отменить текущую операцию

## Структура проекта

### Основные файлы (Версия 2.0)
- `tg_bot.py` - Основной файл бота (работает с SQLite)
- `schedule_db.py` - Модель базы данных расписания (SQLite)
- `schedule_parser.py` - Парсер расписания с поддержкой полного семестра
- `schedule_updater.py` - Сервис автообновления для systemd
- `db_model.py` - Модель для работы с пользователями бота

### Системные файлы
- `install_service.sh` - Скрипт автоустановки systemd сервиса
- `ssau-schedule-updater.service` - Systemd service файл
- `ssau-schedule-updater.timer` - Systemd timer для автообновления
- `test_system.py` - Системные тесты

### Конфигурация и документация
- `.env.example` - Пример переменных окружения
- `requirements.txt` - Python зависимости
- `README.md` - Основная документация
- `API_DOCS.md` - Документация API и структуры БД

### Данные
- `schedule.db` - SQLite база данных расписания (создается автоматически)
- `bot_data.db` - SQLite база данных пользователей (создается автоматически)
- `occupied_rooms.json` - Файл для миграции из старой версии (опционально)

## База данных (Версия 2.0)

Система использует две SQLite базы данных:

### 1. Пользователи бота (`bot_data.db`)
- `users` - Информация о пользователях бота
- `notifications` - История уведомлений

### 2. Расписание (`schedule.db`)
- `buildings` - Корпуса университета
- `rooms` - Аудитории
- `disciplines` - Дисциплины
- `teachers` - Преподаватели
- `groups` - Группы студентов
- `schedule` - Основная таблица расписания
- `lesson_types`, `time_slots`, `weekdays` - Справочники
- `schedule_groups`, `schedule_teachers` - Связующие таблицы

Подробная документация структуры БД доступна в `API_DOCS.md`.

## Для разработчиков

### Разработка и тестирование

1. **Клонирование и настройка**
   ```bash
   git clone <repository-url>
   cd SSAU_Room_Schedule
   cp .env.example .env
   # Отредактируйте .env
   pip install -r requirements.txt
   ```

2. **Запуск тестов**
   ```bash
   python test_system.py
   ```

3. **Инициализация БД**
   ```bash
   # Миграция из старого JSON (если есть)
   python schedule_db.py

   # Или парсинг нового расписания
   python schedule_parser.py --scrape
   ```

### Автоматизация

Система поддерживает автоматическое обновление через systemd:

```bash
# Установка сервиса
sudo ./install_service.sh

# Ручное обновление
sudo systemctl start ssau-schedule-updater.service

# Проверка логов
sudo journalctl -u ssau-schedule-updater.service -f
```

### API интеграция

Для интеграции с другими системами используйте классы из `schedule_db.py`:

```python
from schedule_db import ScheduleDatabase

db = ScheduleDatabase()
schedule = db.get_room_schedule("1", "101", 4, "понедельник")
available = db.get_available_rooms("1", 4, "понедельник", "09:45", "11:20")
```

Полная документация API доступна в `API_DOCS.md`.