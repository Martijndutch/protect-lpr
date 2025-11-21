import logging
import logging.handlers
import os
import json

CONFIG_FILE = os.getenv("CONFIG_FILE", "config.json")
try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
except Exception:
    config = {}

LOG_FILE = config.get("paths", {}).get("log_file", "/var/log/protect-lpr/protect-lpr-pull.log")
log_format = config.get("logging", {}).get("format", "%(asctime)s - %(levelname)s - %(message)s")
log_level = getattr(logging, config.get("logging", {}).get("level", "INFO"))

logger = logging.getLogger("protect-lpr-pull")
logger.setLevel(log_level)
formatter = logging.Formatter(log_format)

file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=10*1024*1024, backupCount=5
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
