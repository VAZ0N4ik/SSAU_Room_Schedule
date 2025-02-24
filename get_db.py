import asyncio
import aiohttp
import json
import time
import os
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dotenv import load_dotenv
load_dotenv()

# Constants
BASE_URL = "https://ssau.ru/rasp"
API_URL = "https://cabinet.ssau.ru/api/timetable/get-timetable"
CACHE_DIR = "cache"
MAX_CONCURRENT_REQUESTS = 30  # Reduced to avoid overwhelming the server
REQUEST_DELAY = 0.1  # Small delay between requests in seconds

# Create cache directory if it doesn't exist
os.makedirs(CACHE_DIR, exist_ok=True)

# Cookie and headers setup
COOKIES = {
    "laravel_session": os.getenv("SESSION_ID")
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}


class TimeTableScraper:
    def __init__(self):
        self.group_ids = set()
        self.all_lessons = []
        self.cache = {}
        self.load_cache()

    def load_cache(self):
        """Load previously cached data"""
        try:
            with open(f"{CACHE_DIR}/group_ids.json", "r", encoding="utf-8") as f:
                self.group_ids = set(json.load(f))
            print(f"Loaded {len(self.group_ids)} group IDs from cache")
        except FileNotFoundError:
            pass

        try:
            with open(f"{CACHE_DIR}/timetable.json", "r", encoding="utf-8") as f:
                self.all_lessons = json.load(f)
                print(f"Loaded timetable with {len(self.all_lessons)} lessons from cache")
        except FileNotFoundError:
            pass

    def save_cache(self):
        """Save data to cache"""
        with open(f"{CACHE_DIR}/group_ids.json", "w", encoding="utf-8") as f:
            json.dump(list(self.group_ids), f)

        # Only save timetable if we have data
        if self.all_lessons:
            with open(f"{CACHE_DIR}/timetable.json", "w", encoding="utf-8") as f:
                json.dump(self.all_lessons, f)

    async def fetch_page(self, session, url, retries=3):
        """Fetch a page with retries"""
        for attempt in range(retries):
            try:
                async with session.get(url, headers=HEADERS) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        print(f"Error {response.status} fetching {url}")
            except Exception as e:
                print(f"Attempt {attempt + 1} failed for {url}: {str(e)}")
                if attempt < retries - 1:
                    await asyncio.sleep(2)  # Increased wait time between retries
        print(f"All {retries} attempts failed for {url}")
        return None

    async def fetch_json(self, session, url, retries=3):
        """Fetch JSON data with retries"""
        for attempt in range(retries):
            try:
                async with session.get(url, headers=HEADERS, cookies=COOKIES) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        print(f"Error {response.status} fetching {url}")
            except Exception as e:
                print(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(1)  # Wait before retry
        return None

    async def extract_institute_links(self, session):
        """Extract institute links from the main page"""
        html = await self.fetch_page(session, BASE_URL)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        links = soup.select('.card-default.faculties__item a')

        # Make sure to convert relative URLs to absolute
        institute_links = []
        for a in links:
            href = a.get('href')
            if href:
                # Check if it's a relative URL and make it absolute
                if href.startswith('/'):
                    href = f"https://ssau.ru{href}"
                institute_links.append(href)

        return institute_links

    async def extract_course_links(self, session, institute_url):
        """Extract course links from an institute page"""
        html = await self.fetch_page(session, institute_url)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        links = soup.select('.btn-text.nav-course__item a')

        # Make sure to convert relative URLs to absolute
        course_links = []
        for a in links:
            href = a.get('href')
            if href:
                # Check if it's a relative URL and make it absolute
                if href.startswith('/'):
                    href = f"https://ssau.ru{href}"
                course_links.append(href)

        return course_links

    async def extract_group_ids(self, session, course_url):
        """Extract group IDs from a course page"""
        html = await self.fetch_page(session, course_url)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        group_elements = soup.select('.btn-text.group-catalog__group')

        group_ids = []
        for group in group_elements:
            href = group.get('href')
            if href and 'groupId=' in href:
                group_id = href.split('groupId=')[-1]
                group_ids.append(group_id)

        print(f"Found {len(group_ids)} groups in {course_url}")
        return group_ids

    async def fetch_timetable(self, session, group_id, week, year_id=13):
        """Fetch timetable data for a specific group and week"""
        cache_key = f"{group_id}_{week}_{year_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        url = f"{API_URL}?yearId={year_id}&week={week}&userType=student&groupId={group_id}"
        data = await self.fetch_json(session, url)

        if data and 'lessons' in data:
            self.cache[cache_key] = data['lessons']
            return data['lessons']
        return []

    async def scrape_group_ids(self):
        """Scrape all group IDs"""
        if self.group_ids:
            print(f"Using {len(self.group_ids)} cached group IDs")
            return

        start_time = time.time()
        async with aiohttp.ClientSession() as session:
            # Get all institute links
            institute_links = await self.extract_institute_links(session)
            print(f"Found {len(institute_links)} institutes")

            # Get all course links
            course_links = []
            tasks = [self.extract_course_links(session, link) for link in institute_links]
            results = await asyncio.gather(*tasks)
            for links in results:
                course_links.extend(links)
            print(f"Found {len(course_links)} courses")

            # Get all group IDs
            all_group_ids = []
            tasks = [self.extract_group_ids(session, link) for link in course_links]
            results = await asyncio.gather(*tasks)
            for ids in results:
                all_group_ids.extend(ids)

            self.group_ids = set(all_group_ids)
            print(f"Found {len(self.group_ids)} group IDs")

        elapsed = time.time() - start_time
        print(f"Group ID scraping completed in {elapsed:.2f} seconds")
        self.save_cache()

    async def process_group_batch(self, session, group_batch, weeks, semaphore):
        """Process a batch of groups and weeks"""
        tasks = []
        for group_id in group_batch:
            for week in weeks:
                tasks.append(self.fetch_group_timetable(session, group_id, week, semaphore))
        return await asyncio.gather(*tasks)

    async def fetch_group_timetable(self, session, group_id, week, semaphore):
        """Fetch timetable for a specific group and week with rate limiting"""
        async with semaphore:
            # Add a small delay to avoid overwhelming the server
            await asyncio.sleep(REQUEST_DELAY)
            lessons = await self.fetch_timetable(session, group_id, week)
            return lessons

    async def scrape_timetables(self, weeks=(26, 27)):
        """Scrape timetables for all groups"""
        # Make sure we have group IDs first
        await self.scrape_group_ids()

        start_time = time.time()
        async with aiohttp.ClientSession() as session:
            # Use a semaphore to limit concurrent requests
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

            # Split group IDs into smaller batches to avoid memory issues
            group_ids_list = list(self.group_ids)
            batch_size = 100
            all_lessons = []

            total_batches = (len(group_ids_list) + batch_size - 1) // batch_size
            for i in range(0, len(group_ids_list), batch_size):
                batch = group_ids_list[i:i + batch_size]
                print(f"Processing batch {i // batch_size + 1}/{total_batches} ({len(batch)} groups)")

                results = await self.process_group_batch(session, batch, weeks, semaphore)
                for lesson_batch in results:
                    if lesson_batch:
                        all_lessons.extend(lesson_batch)

                # Save intermediate results
                if i % (batch_size * 5) == 0:
                    self.all_lessons = all_lessons
                    self.save_cache()
                    print(f"Saved {len(all_lessons)} lessons so far")

            self.all_lessons = all_lessons

        elapsed = time.time() - start_time
        print(f"Timetable scraping completed in {elapsed:.2f} seconds")
        print(f"Total lessons: {len(self.all_lessons)}")
        self.save_cache()

    def transform_schedule(self):
        """Transform schedule data to occupied rooms format"""
        occupied_rooms = {}

        for lesson in self.all_lessons:
            try:
                discipline_name = lesson["discipline"]["name"]
                weekday = lesson["weekday"]["name"]
                begin_time = lesson["time"]["beginTime"]
                end_time = lesson["time"]["endTime"]

                for week_schedule in lesson["weeks"]:
                    room = week_schedule.get("room")
                    building = week_schedule.get("building")
                    week = week_schedule.get("week")

                    if room and building:
                        room_name = f"{room['name']}-{building['name']}"
                        building_name = building["name"]

                        # Initialize building and room if needed
                        if building_name not in occupied_rooms:
                            occupied_rooms[building_name] = {}

                        if room_name not in occupied_rooms[building_name]:
                            occupied_rooms[building_name][room_name] = []

                        # Add lesson info
                        occupied_rooms[building_name][room_name].append({
                            "weekday": weekday,
                            "begin_time": begin_time,
                            "end_time": end_time,
                            "discipline": discipline_name,
                            "groups": [group["name"] for group in lesson["groups"]],
                            "teacher": [teacher["name"] for teacher in lesson["teachers"]],
                            "week": week
                        })
            except KeyError as e:
                print(f"Error processing lesson: {e}")
                continue

        # Save the transformed data
        with open("occupied_rooms.json", "w", encoding="utf-8") as f:
            json.dump(occupied_rooms, f, ensure_ascii=False, indent=4)

        print(f"✅ Room occupation data saved to occupied_rooms.json")
        return occupied_rooms

    async def run_full_process(self):
        """Run the complete scraping and transformation process"""
        print("Starting the scraping process...")

        # Step 1: Scrape group IDs if needed
        await self.scrape_group_ids()

        # Step 2: Scrape timetables
        await self.scrape_timetables()

        # Step 3: Transform data
        self.transform_schedule()

        print("Process completed!")


# Helper functions for room availability
def get_academic_week(date_str, semester_start="2024-09-02"):
    """Calculate academic week number from a date"""
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    semester_start_date = datetime.strptime(semester_start, "%Y-%m-%d")

    delta_days = (date_obj - semester_start_date).days
    if delta_days < 0:
        return None

    return (delta_days // 7) + 1


def find_available_rooms(occupied_rooms, building_name, date_str, begin_time):
    """Find available rooms in a building at a specific time"""
    # Get week and weekday
    week = get_academic_week(date_str)
    if week is None:
        print(f"Date {date_str} is before the semester start.")
        return []

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    weekday_map = {
        0: "понедельник", 1: "вторник", 2: "среда",
        3: "четверг", 4: "пятница", 5: "суббота", 6: "воскресенье"
    }
    weekday = weekday_map[date_obj.weekday()]

    available_rooms = []
    if building_name in occupied_rooms:
        building = occupied_rooms[building_name]

        # Check each room in the building
        for room_name, room_schedule in building.items():
            is_room_available = True

            for lesson in room_schedule:
                if lesson["weekday"] == weekday and lesson["week"] == week:
                    # Convert times to datetime for comparison
                    lesson_begin = datetime.strptime(lesson["begin_time"], "%H:%M")
                    lesson_end = datetime.strptime(lesson["end_time"], "%H:%M")
                    user_time = datetime.strptime(begin_time, "%H:%M")

                    # Check if the time overlaps with a lesson
                    if lesson_begin <= user_time < lesson_end:
                        is_room_available = False
                        break

            if is_room_available:
                available_rooms.append(room_name)

    return sorted(available_rooms)


# Run the scraper
if __name__ == "__main__":
    scraper = TimeTableScraper()
    asyncio.run(scraper.run_full_process())