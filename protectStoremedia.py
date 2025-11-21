import os
import sys
import time
import json
import sqlite3
import logging
import logging.handlers
import schedule
import tenacity
from datetime import datetime, timedelta, timezone
from typing import Optional
from pathlib import Path
from logger_setup import logger
logger.propagate = False
from processvideo import trim_motion_video
from protect_archiver.downloader import Downloader
from protect_archiver.client import ProtectClient
from protect_archiver.errors import ProtectError
from protect_archiver.utils import print_download_stats
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Configuration ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.getenv("CONFIG_FILE", os.path.join(SCRIPT_DIR, "config.json"))

def load_config(config_path: str) -> dict:
    """Load configuration from a JSON file."""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Config file {config_path} not found")
        print(f"Config file {config_path} not found", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in config file {config_path}")
        print(f"Invalid JSON in config file {config_path}", file=sys.stderr)
        sys.exit(1)

# Load config (initial, for startup/paths)
try:
    config = load_config(CONFIG_FILE)
except Exception as e:
    logger.critical(f"Failed to load configuration: {e}")
    exit(1)

# Extract configuration values
CAMERA_IDS = config.get("camera_ids", "")
SERVER_ADDRESS = config.get("server", {}).get("address", "127.0.0.1")
SERVER_PORT = config.get("server", {}).get("port", 443)
SERVER_USERNAME = os.getenv("SERVER_USERNAME", config.get("server", {}).get("username", "localtest"))
SERVER_PASSWORD = os.getenv("SERVER_PASSWORD", config.get("server", {}).get("password", "100%wifi100%WIFI"))
LOG_DIR = config.get("paths", {}).get("log_dir", "/var/log/protect-lpr")
IMAGE_DIR = config.get("paths", {}).get("image_dir", "/var/lib/protect-lpr/images")
MYSQL_DB_FILE = config.get("sqlite3_db_file", "/var/lib/protect-lpr/mysql/protect-lpr.db")
AGE_SECONDS = config.get("age_seconds", 20)
VIDEO_WINDOW_START = config.get("video_window_start_seconds", -15)
VIDEO_WINDOW_END = config.get("video_window_end_seconds", 20)
DOWNLOAD_WAIT = config.get("download_wait", 5)
DOWNLOAD_TIMEOUT = config.get("download_timeout", 15)
LOG_FILE = 'protectStoremedia.log'
LOG_PREFIX = config.get("log_prefix", "event_")
LOG_SUFFIX = config.get("log_suffix", ".log")
RETRY_ATTEMPTS = config.get("retry_attempts", 3)
RETRY_WAIT = config.get("retry_wait_seconds", 5)
SCHEDULE_INTERVAL = config.get("schedule_interval_seconds", 10)
BACKUP_ORIGINAL = config.get("backup_original_video", True)

# Create necessary directories
for path in [LOG_DIR, IMAGE_DIR, os.path.dirname(MYSQL_DB_FILE)]:
    Path(path).mkdir(parents=True, exist_ok=True)

# --- Database Setup ---
def init_db(db_file: str) -> sqlite3.Connection:
    """Initialize SQLite database and create event table."""
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datetime TEXT,
            license_plate TEXT,
            media_urls TEXT
        )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_media_urls ON event (json_extract(media_urls, '$[0]'))")
    conn.commit()
    return conn

# Initialize database
try:
    db_conn = init_db(MYSQL_DB_FILE)
except sqlite3.Error as e:
    logger.critical(f"Failed to initialize database {MYSQL_DB_FILE}: {e}")
    exit(1)

# --- Retry Logic ---
@tenacity.retry(
    stop=tenacity.stop_after_attempt(RETRY_ATTEMPTS),
    wait=tenacity.wait_fixed(RETRY_WAIT),
    retry=tenacity.retry_if_exception_type(ProtectError),
    before_sleep=lambda retry_state: logger.warning(
        f"Retrying download (attempt {retry_state.attempt_number}/{RETRY_ATTEMPTS})..."
    )
)
def download(
    dest: str,
    address: str,
    port: int,
    not_unifi_os: bool,
    username: str,
    password: str,
    verify_ssl: bool,
    cameras: str,
    download_wait: int,
    download_timeout: int,
    use_subfolders: bool,
    touch_files: bool,
    skip_existing_files: bool,
    ignore_failed_downloads: bool,
    start: datetime,
    end: datetime,
    disable_alignment: bool,
    disable_splitting: bool,
    create_snapshot: bool,
    use_utc_filenames: bool,
) -> ProtectClient:
    """Download video footage or snapshots from UniFi Protect."""
    if create_snapshot and (start or end):
        logger.warning("Ignoring --start and --end with --snapshot option")
        start = datetime.now(timezone.utc)

    client = ProtectClient(
        address=address,
        port=port,
        not_unifi_os=not_unifi_os,
        username=username,
        password=password,
        verify_ssl=verify_ssl,
        ignore_failed_downloads=ignore_failed_downloads,
        destination_path=dest,
        use_subfolders=use_subfolders,
        download_wait=download_wait,
        skip_existing_files=skip_existing_files,
        touch_files=touch_files,
        download_timeout=download_timeout,
        use_utc_filenames=use_utc_filenames,
    )

    try:
        logger.info("Fetching camera list")
        camera_list = client.get_camera_list()
        session = client.get_session()

        if cameras != "all":
            camera_s = set(cameras.split(","))
            camera_list = [c for c in camera_list if c["id"] in camera_s]

        if not create_snapshot:
            for camera in camera_list:
                logger.info(
                    f"Downloading video files between {start} and {end} from "
                    f"'{session.authority}{session.base_path}/video/export' for camera {camera['name']}"
                )
                Downloader.download_footage(
                    client, start, end, camera, disable_alignment, disable_splitting
                )
        else:
            logger.info(
                f"Downloading snapshot files for {start.ctime()} "
                f"from '{session.authority}{session.base_path}/cameras/[camera_id]/snapshot'"
            )
            for camera in camera_list:
                Downloader.download_snapshot(client, start, camera)

        print_download_stats(client)
        return client
    except ProtectError as e:
        logger.error(f"ProtectError: {e}")
        #return client
        raise

def process_log_file(fpath: str, db_conn: sqlite3.Connection):
    """Process a single event log file."""
    # Reload config for every file processed
    config = load_config(CONFIG_FILE)
    CAMERA_IDS = config.get("camera_ids", "")
    SERVER_ADDRESS = config.get("server", {}).get("address", "127.0.0.1")
    SERVER_PORT = config.get("server", {}).get("port", 443)
    SERVER_USERNAME = os.getenv("SERVER_USERNAME", config.get("server", {}).get("username", "localtest"))
    SERVER_PASSWORD = os.getenv("SERVER_PASSWORD", config.get("server", {}).get("password", "100%wifi100%WIFI"))
    LOG_DIR = config.get("paths", {}).get("log_dir", "/var/log/protect-lpr")
    IMAGE_DIR = config.get("paths", {}).get("image_dir", "/var/lib/protect-lpr/images")
    MYSQL_DB_FILE = config.get("sqlite3_db_file", "/var/lib/protect-lpr/mysql/protect-lpr.db")
    AGE_SECONDS = config.get("age_seconds", 20)
    VIDEO_WINDOW_START = config.get("video_window_start_seconds", -10)
    VIDEO_WINDOW_END = config.get("video_window_end_seconds", 15)
    DOWNLOAD_WAIT = config.get("download_wait", 5)
    DOWNLOAD_TIMEOUT = config.get("download_timeout", 15)
    LOG_PREFIX = config.get("log_prefix", "event_")
    LOG_SUFFIX = config.get("log_suffix", ".log")
    BACKUP_ORIGINAL = config.get("backup_original_video", True)


    logger.info(f"Processing log file: {fpath}")
    try:
        with open(fpath, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) != 3:
                    logger.warning(f"Unrecognized line: {line}")
                    continue

                log_time, license_plate, event_timestamp = parts
                logger.info(f"time: {log_time}, license: {license_plate}, event_timestamp: {event_timestamp}")
                sub_dir = os.path.join(IMAGE_DIR, license_plate)
                Path(sub_dir).mkdir(exist_ok=True)

                try:
                    event_timestamp_ms = int(event_timestamp)
                except ValueError as e:
                    logger.error(f"Error parsing event_timestamp '{event_timestamp}': {e}")
                    continue

                time_start = datetime.utcfromtimestamp(event_timestamp_ms / 1000 + VIDEO_WINDOW_START).replace(tzinfo=timezone.utc).astimezone()
                time_end = time_start + timedelta(seconds=VIDEO_WINDOW_END - VIDEO_WINDOW_START)

                try:
                    client = download(
                        dest=sub_dir,
                        address=SERVER_ADDRESS,
                        port=SERVER_PORT,
                        not_unifi_os=False,
                        username=SERVER_USERNAME,
                        password=SERVER_PASSWORD,
                        verify_ssl=False,  # Enable SSL verification by default
                        cameras=CAMERA_IDS,
                        download_wait=DOWNLOAD_WAIT,
                        download_timeout=DOWNLOAD_TIMEOUT,
                        use_subfolders=False,
                        touch_files=False,
                        skip_existing_files=False,
                        ignore_failed_downloads=False,
                        start=time_start,
                        end=time_end,
                        disable_alignment=False,
                        disable_splitting=False,
                        create_snapshot=False,
                        use_utc_filenames=False
                    )

                    c = db_conn.cursor()
                    for rel_path in getattr(client, "download_files", []):
                        abs_mp4_path = os.path.join(sub_dir, rel_path)
                        try:
                            produced_files = trim_motion_video(
                                abs_mp4_path,
                                abs_mp4_path,
                                motion_threshold=1.0,
                                motion_min_frames=5,
                                ffmpeg_compress=True,
                                backup_original=BACKUP_ORIGINAL
                            )
                            rel_paths = [os.path.relpath(f, IMAGE_DIR) for f in produced_files]
                        except Exception as e:
                            logger.error(f"Error trimming/compressing video {abs_mp4_path}: {e}")
                            rel_paths = [os.path.relpath(abs_mp4_path, IMAGE_DIR)]

                        c.execute(
                            "SELECT COUNT(*) FROM event WHERE json_extract(media_urls, '$[0]') = ?",
                            (rel_paths[0],)
                        )
                        if c.fetchone()[0] == 0:
                            c.execute(
                                "INSERT INTO event (datetime, license_plate, media_urls) VALUES (?, ?, ?)",
                                (log_time, license_plate, json.dumps(rel_paths))
                            )
                            db_conn.commit()
                            logger.info(f"Inserted event for {license_plate} with media {rel_paths} into database")
                        else:
                            logger.info(f"Event with media file {rel_paths[0]} already exists, skipping insert.")
                except ProtectError as e:
                    logger.error(f"Failed to download footage for {license_plate}: {e}")
                    continue

        # Rename processed log file
        done_path = fpath + ".done"
        try:
            os.rename(fpath, done_path)
            logger.info(f"Renamed {fpath} to {done_path}")
        except OSError as e:
            logger.error(f"Error renaming {fpath} to {done_path}: {e}")
    except FileNotFoundError:
        logger.error(f"Log file {fpath} not found")
    except PermissionError:
        logger.error(f"Permission denied accessing {fpath}")

def cleanup_old_files(directory: str, retention_days: float):
    """Remove .done files older than retention_days."""
    cutoff = time.time() - retention_days * 86400
    for fname in os.listdir(directory):
        if fname.endswith(".done"):
            fpath = os.path.join(directory, fname)
            if os.path.getmtime(fpath) < cutoff:
                try:
                    os.remove(fpath)
                    logger.info(f"Deleted old file: {fpath}")
                except OSError as e:
                    logger.error(f"Error deleting {fpath}: {e}")

def find_old_event_logs():
    """Scan for old event log files and process them in order of creation time (oldest first)."""
    # Reload config to get IMAGE_DIR, LOG_PREFIX, LOG_SUFFIX, AGE_SECONDS, retention_days
    config = load_config(CONFIG_FILE)
    IMAGE_DIR = config.get("paths", {}).get("image_dir", "/var/lib/protect-lpr/images")
    LOG_PREFIX = config.get("log_prefix", "event_")
    LOG_SUFFIX = config.get("log_suffix", ".log")
    AGE_SECONDS = config.get("age_seconds", 20)

    logger.info("Scanning for event logs")
    now = time.time()
    log_files = []
    for fname in os.listdir(IMAGE_DIR):
        if fname.startswith(LOG_PREFIX) and fname.endswith(LOG_SUFFIX):
            fpath = os.path.join(IMAGE_DIR, fname)
            if now - os.path.getmtime(fpath) > AGE_SECONDS:
                log_files.append(fpath)
    # Sort log files by creation/modification time (oldest first)
    log_files.sort(key=lambda f: os.path.getmtime(f))
    for fpath in log_files:
        process_log_file(fpath, db_conn)
    # Cleanup old .done files
    cleanup_old_files(IMAGE_DIR, config.get("retention_days", 7))

def main():
    """Main function to schedule log processing."""
    logger.info("Started protect-lpr-pull script")
    schedule.every(SCHEDULE_INTERVAL).seconds.do(find_old_event_logs)
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Terminated by KeyboardInterrupt")
    except Exception as e:
        logger.critical(f"Terminated due to unexpected error: {e}")
    finally:
        db_conn.close()
        logger.info("Closed database connection")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Script failed to start: {e}")
        exit(1)