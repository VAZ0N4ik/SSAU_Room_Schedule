import asyncio
import aiohttp
import json
import time
import os
import re
import random
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from schedule_db import ScheduleDatabase
from typing import List, Dict, Any, Optional, Set
import logging
from tqdm.asyncio import tqdm

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
BASE_URL = "https://ssau.ru/rasp"
API_URL = "https://cabinet.ssau.ru/api/timetable/get-timetable"
AUTH_URL = "https://cabinet.ssau.ru/login"
CACHE_DIR = "cache"
MAX_CONCURRENT_REQUESTS = 30  # Maximum concurrent requests
REQUEST_DELAY = 0.01  # Minimal delay between requests
BATCH_SIZE = 50  # Process 50 groups at once
CONNECTION_LIMIT = 100  # Total connection pool limit
CONNECTION_LIMIT_PER_HOST = 30  # Per-host connection limit

# Create cache directory if it doesn't exist
os.makedirs(CACHE_DIR, exist_ok=True)

# Headers for requests
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Keep-Alive": "timeout=30, max=1000",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin"
}


class SSAUAuth:
    """Handle authentication for SSAU API"""

    def __init__(self):
        self.session_cookie = None
        self.username = os.getenv("SSAU_USERNAME")
        self.password = os.getenv("SSAU_PASSWORD")

    async def get_session_by_login(self, session: aiohttp.ClientSession) -> bool:
        """Get Laravel session by programmatic login"""
        if not self.username or not self.password:
            logger.error("SSAU_USERNAME and SSAU_PASSWORD are required for automatic authentication")
            return False

        try:
            logger.info("Starting programmatic authentication...")

            # Step 1: Get login page and extract CSRF token
            login_url = "https://cabinet.ssau.ru/login"
            async with session.get(login_url) as response:
                if response.status != 200:
                    logger.error(f"Failed to get login page: {response.status}")
                    return False

                html = await response.text()

                # Try multiple ways to extract CSRF token
                csrf_token = None

                # Method 1: Meta tag with name="csrf-token" (with or without spaces)
                csrf_match = re.search(r'<meta\s+name=(?:"?csrf-token"?)\s+content=(?:"([^"]+)"|([^\s>]+))', html)
                if csrf_match:
                    csrf_token = csrf_match.group(1) or csrf_match.group(2)
                    logger.info("CSRF token found in meta tag")

                # Method 2: Meta tag with name="_token"
                if not csrf_token:
                    csrf_match = re.search(r'<meta\s+name=(?:"?_token"?)\s+content=(?:"([^"]+)"|([^\s>]+))', html)
                    if csrf_match:
                        csrf_token = csrf_match.group(1) or csrf_match.group(2)
                        logger.info("CSRF token found in _token meta tag")

                # Method 3: JavaScript window.__APP__ object
                if not csrf_token:
                    csrf_match = re.search(r'window\.__APP__\s*=\s*{[^}]*"csrf"\s*:\s*"([^"]+)"', html)
                    if csrf_match:
                        csrf_token = csrf_match.group(1)
                        logger.info("CSRF token found in __APP__ JavaScript object")

                # Method 4: Laravel JavaScript variable
                if not csrf_token:
                    csrf_match = re.search(r'window\.Laravel\s*=\s*{[^}]*"csrfToken"\s*:\s*"([^"]+)"', html)
                    if csrf_match:
                        csrf_token = csrf_match.group(1)
                        logger.info("CSRF token found in Laravel JavaScript object")

                # Method 5: Hidden input field
                if not csrf_token:
                    csrf_match = re.search(r'<input[^>]*name="?_token"?[^>]*value="?([^"\s>]+)"?', html)
                    if csrf_match:
                        csrf_token = csrf_match.group(1)
                        logger.info("CSRF token found in hidden input")

                if not csrf_token:
                    logger.error("CSRF token not found in login page")
                    # Debug: save page content to see what we're getting
                    with open("debug_login_page.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    logger.info("Login page saved to debug_login_page.html for inspection")
                    return False

                logger.info(f"CSRF token extracted successfully: {csrf_token[:20]}...")

            # Step 2: Perform login with CSRF token
            login_data = {
                '_token': csrf_token,
                'login': self.username,
                'password': self.password
            }

            headers = {
                **HEADERS,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': login_url,
            }

            async with session.post(login_url, data=login_data, headers=headers, allow_redirects=False) as response:
                logger.info(f"Login response status: {response.status}")
                logger.info(f"Login response headers: {dict(response.headers)}")

                # Log all cookies received
                all_cookies = {cookie.key: cookie.value for cookie in session.cookie_jar}
                logger.info(f"Cookies after login: {list(all_cookies.keys())}")

                # Check for successful login (redirect or 200)
                if response.status in [200, 302, 303]:
                    # Extract Laravel session from cookies
                    laravel_session_found = False
                    for cookie in session.cookie_jar:
                        if cookie.key == 'laravel_session':
                            self.session_cookie = cookie.value
                            laravel_session_found = True
                            logger.info("✅ Laravel session cookie found!")
                            break

                    if laravel_session_found:
                        logger.info("✅ Authentication successful! Laravel session obtained.")

                        # Save session to .env for future use
                        self.save_session_to_env(self.session_cookie)

                        # Test the session by making a test API call
                        test_url = f"{API_URL}?yearId=14&week=1&userType=student&groupId=1282752616"
                        logger.info(f"Testing session with: {test_url}")

                        async with session.get(test_url, headers=HEADERS, cookies=self.get_cookies()) as test_response:
                            logger.info(f"Session test response status: {test_response.status}")
                            if test_response.status == 200:
                                test_data = await test_response.json()
                                if 'lessons' in test_data:
                                    logger.info("✅ Session validation successful!")
                                    return True
                                else:
                                    logger.warning("Session validation failed - no lessons in response")
                                    logger.info(f"Test response keys: {list(test_data.keys()) if test_data else 'None'}")
                            else:
                                logger.warning(f"Session validation failed - HTTP {test_response.status}")
                                try:
                                    error_text = await test_response.text()
                                    logger.warning(f"Test response text: {error_text[:200]}...")
                                except:
                                    pass

                        return laravel_session_found
                    else:
                        logger.error("Laravel session cookie not found after login")
                        logger.info(f"Available cookies: {list(all_cookies.keys())}")
                        return False
                else:
                    logger.error(f"Login failed with status: {response.status}")
                    # Try to get error message
                    try:
                        error_text = await response.text()
                        logger.error(f"Login error response: {error_text[:500]}...")
                        if "invalid" in error_text.lower() or "incorrect" in error_text.lower():
                            logger.error("Invalid credentials detected")
                    except Exception as e:
                        logger.error(f"Failed to read error response: {e}")
                    return False

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    async def authenticate(self, session: aiohttp.ClientSession) -> bool:
        """Main authentication method - tries existing session first, then login"""
        # First try existing session from env
        existing_session = os.getenv("SESSION_ID")
        if existing_session:
            logger.info("Trying existing SESSION_ID from .env...")
            self.session_cookie = existing_session

            # Test the existing session
            test_url = f"{API_URL}?yearId=14&week=1&userType=student&groupId=1282752616"
            try:
                async with session.get(test_url, headers=HEADERS, cookies=self.get_cookies()) as response:
                    if response.status == 200:
                        test_data = await response.json()
                        if 'lessons' in test_data:
                            logger.info("✅ Existing session is valid!")
                            return True
                    logger.warning("Existing session is invalid or expired")
            except Exception as e:
                logger.warning(f"Failed to test existing session: {e}")

        # If no existing session or it's invalid, try to login
        logger.info("Attempting to create new session via login...")
        return await self.get_session_by_login(session)

    def save_session_to_env(self, session_id: str) -> None:
        """Save session ID to .env file for future use"""
        try:
            env_path = ".env"
            lines = []

            # Read existing .env file
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

            # Update or add SESSION_ID
            session_line = f"SESSION_ID={session_id}\n"
            session_updated = False

            for i, line in enumerate(lines):
                if line.startswith('SESSION_ID='):
                    lines[i] = session_line
                    session_updated = True
                    break

            if not session_updated:
                lines.append(session_line)

            # Write back to .env
            with open(env_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            logger.info(f"✅ Session saved to .env file")

        except Exception as e:
            logger.warning(f"Failed to save session to .env: {e}")

    def get_cookies(self) -> Dict[str, str]:
        """Get cookies for requests"""
        if self.session_cookie:
            return {"laravel_session": self.session_cookie}
        return {}


class ScheduleParser:
    """Enhanced schedule parser with full semester support"""

    def __init__(self, db: ScheduleDatabase):
        self.db = db
        self.group_ids: Set[str] = set()
        self.auth = SSAUAuth()
        self.current_year_id = None
        self.total_weeks = 18  # Full semester

    async def get_current_year_id(self, session: aiohttp.ClientSession) -> Optional[int]:
        """Get current academic year ID from API"""
        try:
            # Try to get any group's schedule to determine current year
            test_group_id = "1282752616"  # Example group from tz.md
            url = f"{API_URL}?yearId=14&week=1&userType=student&groupId={test_group_id}"

            async with session.get(url, headers=HEADERS, cookies=self.auth.get_cookies()) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'currentYear' in data and data['currentYear']:
                        year_id = data['currentYear']['id']
                        logger.info(f"Detected current year ID: {year_id}")
                        return year_id

            # Fallback to default if detection fails
            logger.warning("Could not detect current year ID, using default 14")
            return 14

        except Exception as e:
            logger.error(f"Error getting current year ID: {e}")
            return 14

    async def fetch_page(self, session: aiohttp.ClientSession, url: str, retries: int = 3) -> Optional[str]:
        """Fetch a page with retries"""
        for attempt in range(retries):
            try:
                async with session.get(url, headers=HEADERS) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        logger.warning(f"HTTP {response.status} for {url}")
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

        logger.error(f"All {retries} attempts failed for {url}")
        return None

    async def fetch_json(self, session: aiohttp.ClientSession, url: str, retries: int = 2) -> Optional[Dict[str, Any]]:
        """Fetch JSON data with retries - optimized for speed"""
        for attempt in range(retries):
            try:
                timeout = aiohttp.ClientTimeout(total=10, connect=3, sock_read=7)
                async with session.get(url, headers=HEADERS, cookies=self.auth.get_cookies(), timeout=timeout) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 401:
                        logger.warning("Authentication expired, re-authenticating...")
                        if await self.auth.authenticate(session):
                            continue
                        else:
                            logger.error("Re-authentication failed")
                            return None
                    elif response.status == 429:  # Rate limited
                        wait_time = min(2 ** attempt, 5)  # Max 5 seconds
                        logger.warning(f"Rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.warning(f"HTTP {response.status} for {url}")
            except asyncio.TimeoutError:
                logger.warning(f"Timeout on attempt {attempt + 1} for {url}")
                if attempt < retries - 1:
                    await asyncio.sleep(0.5)  # Quick retry
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(0.5)

        logger.error(f"All {retries} attempts failed for {url}")
        return None

    async def extract_institute_links(self, session: aiohttp.ClientSession) -> List[str]:
        """Extract institute links from the main page"""
        html = await self.fetch_page(session, BASE_URL)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        links = soup.select('.card-default.faculties__item a')

        institute_links = []
        for a in links:
            href = a.get('href')
            if href:
                if href.startswith('/'):
                    href = f"https://ssau.ru{href}"
                institute_links.append(href)

        logger.info(f"Found {len(institute_links)} institutes")
        return institute_links

    async def extract_course_links(self, session: aiohttp.ClientSession, institute_url: str) -> List[str]:
        """Extract course links from an institute page"""
        html = await self.fetch_page(session, institute_url)
        if not html:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        links = soup.select('.btn-text.nav-course__item a')

        course_links = []
        for a in links:
            href = a.get('href')
            if href:
                if href.startswith('/'):
                    href = f"https://ssau.ru{href}"
                course_links.append(href)

        return course_links

    async def extract_group_ids(self, session: aiohttp.ClientSession, course_url: str) -> List[str]:
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

        return group_ids

    async def scrape_group_ids(self, session: aiohttp.ClientSession) -> None:
        """Scrape all group IDs from the university website"""
        cache_file = f"{CACHE_DIR}/group_ids.json"

        # Try to load from cache first
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_groups = json.load(f)
                    self.group_ids = set(cached_groups)
                    logger.info(f"Loaded {len(self.group_ids)} group IDs from cache")
                    return
            except Exception as e:
                logger.warning(f"Failed to load cached group IDs: {e}")

        logger.info("Scraping group IDs from website...")
        start_time = time.time()

        # Get all institute links
        institute_links = await self.extract_institute_links(session)

        # Get all course links
        course_links = []
        tasks = [self.extract_course_links(session, link) for link in institute_links]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                course_links.extend(result)
            else:
                logger.warning(f"Failed to get course links: {result}")

        logger.info(f"Found {len(course_links)} courses")

        # Get all group IDs
        all_group_ids = []
        tasks = [self.extract_group_ids(session, link) for link in course_links]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                all_group_ids.extend(result)
            else:
                logger.warning(f"Failed to get group IDs: {result}")

        self.group_ids = set(all_group_ids)
        logger.info(f"Found {len(self.group_ids)} unique group IDs")

        # Save to cache
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(list(self.group_ids), f)
            logger.info("Group IDs cached successfully")
        except Exception as e:
            logger.warning(f"Failed to cache group IDs: {e}")

        elapsed = time.time() - start_time
        logger.info(f"Group ID scraping completed in {elapsed:.2f} seconds")

    async def fetch_group_timetable(self, session: aiohttp.ClientSession, group_id: str,
                                  week: int, semaphore: asyncio.Semaphore) -> Optional[List[Dict[str, Any]]]:
        """Fetch timetable for a specific group and week"""
        async with semaphore:
            # Minimal delay only when necessary
            if random.random() < 0.1:  # 10% chance of delay to avoid rate limits
                await asyncio.sleep(REQUEST_DELAY)

            url = f"{API_URL}?yearId={self.current_year_id}&week={week}&userType=student&groupId={group_id}"
            data = await self.fetch_json(session, url)

            if data and 'lessons' in data:
                return data['lessons']
            return None

    async def process_group_batch(self, session: aiohttp.ClientSession, group_batch: List[str],
                                weeks: List[int], semaphore: asyncio.Semaphore,
                                progress_bar: tqdm) -> int:
        """Process a batch of groups for all weeks - fully parallel"""
        lessons_count = 0

        # Create all tasks for this batch
        tasks = []
        for group_id in group_batch:
            for week in weeks:
                task = self.fetch_group_timetable(session, group_id, week, semaphore)
                tasks.append((group_id, week, task))

        # Execute all tasks in parallel
        results = await asyncio.gather(*[task for _, _, task in tasks], return_exceptions=True)

        # Process results with database transaction
        cursor = self.db.connection.cursor()
        cursor.execute("BEGIN TRANSACTION")

        for i, result in enumerate(results):
            progress_bar.update(1)

            if isinstance(result, Exception):
                logger.warning(f"Failed to fetch for group {tasks[i][0]}, week {tasks[i][1]}: {result}")
                continue

            if result:  # lessons list
                for lesson in result:
                    try:
                        self.db.insert_schedule_lesson(lesson, self.current_year_id)
                        lessons_count += 1
                    except Exception as e:
                        if "FOREIGN KEY" not in str(e):
                            logger.warning(f"Failed to insert lesson: {e}")

        cursor.execute("COMMIT")
        return lessons_count

    async def scrape_full_semester(self) -> None:
        """Scrape timetables for all groups for the full semester"""
        if not self.group_ids:
            logger.error("No group IDs available")
            return

        logger.info(f"Starting full semester scraping for {len(self.group_ids)} groups")
        start_time = time.time()

        # Clear old data for current year
        self.db.clear_old_data(self.current_year_id)

        # Create session with optimized connection pooling
        connector = aiohttp.TCPConnector(
            limit=CONNECTION_LIMIT,
            limit_per_host=CONNECTION_LIMIT_PER_HOST,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
            force_close=False,
            keepalive_timeout=30
        )

        timeout = aiohttp.ClientTimeout(total=30, connect=5, sock_read=20)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Authenticate
            if not await self.auth.authenticate(session):
                logger.error("Authentication failed, cannot continue")
                return

            # Use semaphore to limit concurrent requests
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

            # Prepare weeks (1 to total_weeks)
            weeks = list(range(1, self.total_weeks + 1))

            # Split groups into batches
            group_ids_list = list(self.group_ids)
            total_operations = len(group_ids_list) * len(weeks)

            # Initialize progress bar
            progress_bar = tqdm(total=total_operations, desc="Scraping schedule", unit="requests")

            total_lessons = 0

            try:
                # Process groups in batches
                for i in range(0, len(group_ids_list), BATCH_SIZE):
                    batch = group_ids_list[i:i + BATCH_SIZE]
                    logger.info(f"Processing batch {i // BATCH_SIZE + 1}/{(len(group_ids_list) + BATCH_SIZE - 1) // BATCH_SIZE}")

                    lessons_count = await self.process_group_batch(
                        session, batch, weeks, semaphore, progress_bar
                    )
                    total_lessons += lessons_count

                    # Commit batch to database
                    try:
                        self.db.connection.commit()
                    except Exception as e:
                        logger.error(f"Database commit error: {e}")
                        self.db.connection.rollback()

                    # Log progress
                    if (i // BATCH_SIZE + 1) % 5 == 0:  # Log more frequently
                        logger.info(f"Processed {i + len(batch)} groups, {total_lessons} lessons inserted")

                    # Minimal delay between batches only if needed
                    if i % 10 == 0 and i > 0:  # Every 10 batches
                        await asyncio.sleep(0.1)

            finally:
                progress_bar.close()

            # Final commit
            self.db.connection.commit()

        elapsed = time.time() - start_time
        logger.info(f"Full semester scraping completed in {elapsed:.2f} seconds")
        logger.info(f"Total lessons inserted: {total_lessons}")

        # Show final statistics
        stats = self.db.get_stats()
        logger.info(f"Database statistics: {stats}")

    async def run_full_process(self) -> None:
        """Run the complete scraping process"""
        logger.info("Starting enhanced schedule scraping process...")

        async with aiohttp.ClientSession() as session:
            # Get current year ID
            self.current_year_id = await self.get_current_year_id(session)

            # Scrape group IDs
            await self.scrape_group_ids(session)

            # Scrape full semester
            await self.scrape_full_semester()

        logger.info("Enhanced scraping process completed!")


# CLI interface
async def main():
    """Main function for CLI usage"""
    import argparse

    parser = argparse.ArgumentParser(description="SSAU Schedule Parser")
    parser.add_argument("--migrate", action="store_true", help="Migrate from existing JSON file")
    parser.add_argument("--scrape", action="store_true", help="Scrape full semester")
    parser.add_argument("--groups-only", action="store_true", help="Only scrape group IDs")
    parser.add_argument("--db-path", default="schedule.db", help="Database path")
    parser.add_argument("--json-path", default="occupied_rooms.json", help="JSON file path for migration")

    args = parser.parse_args()

    # Initialize database
    db = ScheduleDatabase(args.db_path)

    try:
        if args.migrate:
            logger.info("Starting migration from JSON...")
            success = db.migrate_from_json(args.json_path)
            if success:
                logger.info("Migration completed successfully!")
            else:
                logger.error("Migration failed!")

        elif args.scrape:
            parser = ScheduleParser(db)
            await parser.run_full_process()

        elif args.groups_only:
            parser = ScheduleParser(db)
            async with aiohttp.ClientSession() as session:
                await parser.scrape_group_ids(session)

        else:
            # Default: show stats
            stats = db.get_stats()
            logger.info(f"Database statistics: {stats}")

    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())