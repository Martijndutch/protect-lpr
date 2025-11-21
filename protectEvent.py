#!/usr/bin/env python3
# File version: 1.0.0
# Version history:
# 1.0.0 - First production release.
#
# (c) 2025 monsultancy.eu. Author: Martijn Jongen
#
# Main event handler for the unifi protect LPR webhook

import os
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
import uuid
import sys

# Configuration file path (always relative to script location)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        print(f"Configuration file {CONFIG_FILE} not found", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Invalid JSON in configuration file {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)

# Load configuration from JSON file
try:
    config = load_config()
except FileNotFoundError:
    raise FileNotFoundError(f"Configuration file {CONFIG_FILE} not found")
except json.JSONDecodeError:
    raise ValueError(f"Invalid JSON in configuration file {CONFIG_FILE}")

# Retrieve configuration values
PATHS = config.get('paths', {})
LOG_DIR = PATHS.get('log_dir')
IMAGE_DIR = PATHS.get('image_dir')
LOG_FILE = os.path.join(LOG_DIR, 'protect-lpr.log')
LOGGING_CONFIG = config.get('logging', {})
LOG_LEVEL = getattr(logging, LOGGING_CONFIG.get('level', 'INFO'), logging.INFO)
LOG_FORMAT = LOGGING_CONFIG.get('format', '%(asctime)s - %(levelname)s - %(message)s')
SERVER_PORT = config.get('server', {}).get('webhook_port', 1025)
IGNORED_PLATES = [
    str(item["plate"]).lower().strip()
    for item in config.get('ignored_plates', [])
    if isinstance(item, dict) and "plate" in item and item["plate"]
]

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Configure logger for file and console output
logger = logging.getLogger('WebhookLogger')
logger.propagate = False
logger.setLevel(LOG_LEVEL)

try:
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(file_handler)
except Exception as e:
    print(f"Could not create log file {LOG_FILE}: {e}. Continuing without file logging.")

# Add a console handler so logs are also output to the terminal.
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(console_handler)

# Function to operate the barrier (stub for actual hardware/API call)
def operate_barrier(license_plate, device_id):
    try:
        logger.info(f"Operating barrier for license plate {license_plate} on device {device_id}")
        # Replace with actual hardware/API call if needed
        return {"status": "success", "message": f"Barrier opened for {license_plate}"}
    except Exception as e:
        logger.error(f"Failed to operate barrier for {license_plate}: {str(e)}")
        return {"status": "error", "error": str(e)}

# HTTP request handler for webhook server
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        logger.info("Received GET request")
        self.send_response(405)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"error": "only post allowed"}).encode())

    def do_POST(self):
        # Reload config on every event
        config = load_config()
        PATHS = config.get('paths', {})
        LOG_DIR = PATHS.get('log_dir')
        LOG_FILE = os.path.join(LOG_DIR, 'protect-lpr.log')
        LOGGING_CONFIG = config.get('logging', {})
        LOG_LEVEL = getattr(logging, LOGGING_CONFIG.get('level', 'INFO'), logging.INFO)
        IMAGE_DIR = PATHS.get('image_dir')
        LOGGING_CONFIG = config.get('logging', {})
        IGNORED_PLATES = [
            str(item["plate"]).lower().strip()
            for item in config.get('ignored_plates', [])
            if isinstance(item, dict) and "plate" in item and item["plate"]
        ]

        # Handle POST requests (webhook events)
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                message = json.loads(post_data.decode())
            except json.JSONDecodeError:
                logger.warning(f"Received non-JSON webhook: {post_data.decode()}")
                message = {"alarm": {}}

            logger.info(f"Received POST webhook: {message}")

            # Extract relevant data from webhook payload
            device_id = None
            source = None
            event_timestamp = None
            license_plate = None
            timestamp_ms = None
            try:
                triggers = message.get('alarm', {}).get('triggers', [])
                if triggers:
                    device_id = triggers[0].get('device')
                    source = triggers[0].get('key')
                    license_plate = triggers[0].get('value')
                    timestamp_ms = triggers[0].get('timestamp', message.get('timestamp'))
                    if timestamp_ms:
                        event_timestamp = datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d_%H-%M-%S-%f')[:-3]
            except (KeyError, IndexError, TypeError):
                logger.warning("Could not extract device ID, source, timestamp, or license plate from webhook payload")

            # Check if all required data is present
            if not all([device_id, source, event_timestamp, license_plate]):
                logger.warning(f"Missing required data: device_id={device_id}, source={source}, event_timestamp={event_timestamp}, license_plate={license_plate}")
                response = {"status": "received", "images": [], "videos": [], "barrier": None, "error": "Missing required webhook data"}
            else:
                # Operate the barrier if all data is present
                barrier_result = operate_barrier(license_plate, device_id)
                skip_imaging = license_plate.lower() in IGNORED_PLATES

                log_file_created = False
                log_file_path = None
                # Optionally log event to file if not ignored
                if not skip_imaging:
                    try:
                        now_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                        unique_id = str(uuid.uuid4())
                        log_filename = f"event_{license_plate}_{unique_id}.log"
                        log_filepath = os.path.join(IMAGE_DIR, log_filename)
                        with open(log_filepath, 'w') as logf:
                            logf.write(f"{now_str},{license_plate},{timestamp_ms}\n")
                        logger.info(f"Event log file created: {log_filepath}")
                        log_file_created = True
                        log_file_path = log_filepath
                    except Exception as e:
                        logger.error(f"Failed to create event log file: {e}")

                now_time_str = datetime.now().strftime('%H:%M:%S')
                response = {
                    "status": "received",
                    "message": f"license {license_plate} received at {now_time_str}",
                    "barrier": barrier_result,
                    "log_file_created": log_file_created,
                    "log_file_path": log_file_path
                }

            # Send JSON response
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        except Exception as e:
            logger.error(f"Error processing POST request: {str(e)}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

# Function to start the HTTP server
def run_server(port=SERVER_PORT):
    server_address = ('', port)
    httpd = HTTPServer(server_address, WebhookHandler)
    logger.info(f"Starting webhook server on port {port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down webhook server")
        httpd.server_close()

# Entry point for running the server
if __name__ == '__main__':
    run_server()