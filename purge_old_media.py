import os
import json
import sqlite3
import time
from datetime import datetime, timedelta

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
with open(CONFIG_PATH, 'r') as f:
    config = json.load(f)

# Get retention days from config, default to 30 if not set
retention_days = config.get('retention_days', 30)

# Get media/image directory from config
image_dir = config['paths'].get('image_dir')
if not image_dir:
    raise ValueError('image_dir not set in config.json')

# Get database file from config (try both possible keys)
db_file = config.get('db_file') or config.get('mysql_db_file') or 'lpr.db'
if not os.path.isabs(db_file):
    db_file = os.path.join(os.path.dirname(__file__), db_file)

# Calculate cutoff timestamp
now = time.time()
cutoff = now - retention_days * 86400

# Purge old media files
def purge_files(directory, cutoff):
    removed = 0
    for root, dirs, files in os.walk(directory):
        for name in files:
            path = os.path.join(root, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except Exception as e:
                print(f"Error removing {path}: {e}")
    return removed

# Purge old database records (event table, datetime as string)
def purge_db(db_path, cutoff_dt):
    removed = 0
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        # Fetch all ids and datetimes
        c.execute("SELECT id, datetime FROM event")
        rows = c.fetchall()
        to_delete = []
        for row in rows:
            row_id, dt_str = row
            try:
                # Try to parse datetime string (format: YYYY-MM-DD_HH-MM-SS-fff)
                dt_obj = datetime.strptime(dt_str, "%Y-%m-%d_%H-%M-%S-%f")
                if dt_obj < cutoff_dt:
                    to_delete.append(row_id)
            except Exception:
                continue
        if to_delete:
            c.executemany("DELETE FROM event WHERE id = ?", [(i,) for i in to_delete])
            removed = len(to_delete)
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error purging database: {e}")
    return removed

if __name__ == "__main__":
    print(f"Purging files older than {retention_days} days in {image_dir}")
    files_removed = purge_files(image_dir, cutoff)
    print(f"Removed {files_removed} files.")

    # Calculate cutoff datetime for event table
    cutoff_dt = datetime.fromtimestamp(cutoff)
    print(f"Purging database records older than {retention_days} days in {db_file}")
    db_removed = purge_db(db_file, cutoff_dt)
    print(f"Removed {db_removed} database records.")
