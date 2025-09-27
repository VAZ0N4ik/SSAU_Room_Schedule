#!/usr/bin/env python3
"""
SSAU Schedule Updater Service

This script is designed to run as a systemd service to automatically update
the schedule database at regular intervals.
"""

import asyncio
import logging
import sys
import os
import signal
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from schedule_parser import ScheduleParser
from schedule_db import ScheduleDatabase

# Setup logging for systemd
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),  # For systemd journal
        logging.FileHandler('/var/log/ssau-schedule-updater.log')  # Fallback log file
    ]
)
logger = logging.getLogger(__name__)


class ScheduleUpdaterService:
    """Service class for automated schedule updates"""

    def __init__(self, db_path: str = None):
        # Load environment variables
        load_dotenv()

        # Set paths
        self.base_dir = Path(__file__).parent
        self.db_path = db_path or self.base_dir / "schedule.db"

        # Initialize components
        self.db = None
        self.parser = None
        self.running = True

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.running = False

    async def initialize(self):
        """Initialize database and parser"""
        try:
            logger.info("Initializing schedule updater service...")

            # Initialize database
            self.db = ScheduleDatabase(str(self.db_path))
            logger.info(f"Database initialized at: {self.db_path}")

            # Initialize parser
            self.parser = ScheduleParser(self.db)
            logger.info("Parser initialized")

            # Log current database stats
            stats = self.db.get_stats()
            logger.info(f"Current database stats: {stats}")

            return True

        except Exception as e:
            logger.error(f"Failed to initialize service: {e}")
            return False

    async def update_schedule(self):
        """Perform a full schedule update"""
        logger.info("Starting schedule update process...")
        start_time = datetime.now()

        try:
            # Run the full parsing process
            await self.parser.run_full_process()

            # Log completion
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            # Get updated stats
            stats = self.db.get_stats()
            logger.info(f"Schedule update completed in {duration:.2f} seconds")
            logger.info(f"Updated database stats: {stats}")

            return True

        except Exception as e:
            logger.error(f"Schedule update failed: {e}")
            return False

    async def health_check(self):
        """Perform basic health checks"""
        try:
            # Check database connectivity
            if not self.db.connection:
                logger.error("Database connection lost")
                return False

            # Check if we have recent data
            stats = self.db.get_stats()
            if stats.get('schedule', 0) == 0:
                logger.warning("No schedule data in database")
                return False

            logger.info("Health check passed")
            return True

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    async def run_service(self):
        """Main service loop"""
        logger.info("SSAU Schedule Updater Service starting...")

        # Initialize service
        if not await self.initialize():
            logger.error("Service initialization failed, exiting")
            return 1

        try:
            # Run one-time update
            logger.info("Performing initial schedule update...")
            success = await self.update_schedule()

            if success:
                logger.info("Initial update completed successfully")
            else:
                logger.error("Initial update failed")
                return 1

            # Keep service running for potential future enhancements
            # (e.g., periodic health checks, metrics collection)
            logger.info("Service is running. Waiting for shutdown signal...")

            while self.running:
                # Perform periodic health checks
                await self.health_check()

                # Sleep for a minute before next health check
                for _ in range(60):  # Check every second for shutdown signal
                    if not self.running:
                        break
                    await asyncio.sleep(1)

            logger.info("Service shutdown initiated")
            return 0

        except Exception as e:
            logger.error(f"Service error: {e}")
            return 1

        finally:
            # Cleanup
            if self.db:
                self.db.close()
            logger.info("Service stopped")

    def close(self):
        """Cleanup resources"""
        if self.db:
            self.db.close()


async def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="SSAU Schedule Updater Service")
    parser.add_argument("--db-path", help="Database file path")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--health-check", action="store_true", help="Perform health check and exit")
    parser.add_argument("--migrate", help="Migrate from JSON file and exit")

    args = parser.parse_args()

    # Create service instance
    service = ScheduleUpdaterService(args.db_path)

    try:
        if args.health_check:
            # Health check mode
            if await service.initialize():
                success = await service.health_check()
                return 0 if success else 1
            else:
                return 1

        elif args.migrate:
            # Migration mode
            if await service.initialize():
                logger.info(f"Starting migration from {args.migrate}")
                success = service.db.migrate_from_json(args.migrate)
                if success:
                    logger.info("Migration completed successfully")
                    return 0
                else:
                    logger.error("Migration failed")
                    return 1
            else:
                return 1

        elif args.once:
            # One-time update mode
            if await service.initialize():
                success = await service.update_schedule()
                return 0 if success else 1
            else:
                return 1

        else:
            # Service mode
            return await service.run_service()

    finally:
        service.close()


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Service interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)