#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import subprocess
from datetime import datetime
import os
import concurrent.futures

# Laad configuratie uit config.json
CONFIG_FILE = "/opt/protect-lpr/config.json"

try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"Configuration file {CONFIG_FILE} not found")
except json.JSONDecodeError:
    raise ValueError(f"Invalid JSON in configuration file {CONFIG_FILE}")

# Haal configuratiewaarden op
PATHS = config.get('paths', {})
LOG_DIR = PATHS.get('log_dir', '/var/log/protect-lpr')
LOG_FILE = PATHS.get('log_file', os.path.join(LOG_DIR, 'protect-lpr.log'))
IMAGE_DIR = PATHS.get('image_dir', '/var/lib/protect-lpr/images')
UNKNOWN_DIR = PATHS.get('unknown_dir', os.path.join(IMAGE_DIR, 'unknown'))

LOGGING_CONFIG = config.get('logging', {})
LOG_LEVEL = getattr(logging, LOGGING_CONFIG.get('level', 'INFO'), logging.INFO)
LOG_FORMAT = LOGGING_CONFIG.get('format', '%(asctime)s - %(levelname)s - %(message)s')

DEVICE_RTSP_MAP = config.get('rtsp_streams', {})
SERVER_PORT = config.get('server', {}).get('port', 1025)

# Zorg ervoor dat de basismappen bestaan
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(UNKNOWN_DIR, exist_ok=True)

# Configureer logging
logger = logging.getLogger('WebhookLogger')
logger.setLevel(LOG_LEVEL)

# File handler voor logging naar bestand
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(file_handler)

# Stream handler voor logging naar console
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(console_handler)

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Behandel GET-verzoeken
        logger.info("Received GET request")
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "received"}).encode())

    def capture_image(self, rtsp_url, output_file):
        """Helper functie om een afbeelding te capturen met FFmpeg."""
        ffmpeg_cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-vframes", "1",
            "-f", "image2",
            output_file
        ]
        try:
            result = subprocess.run(
                ffmpeg_cmd,
                check=True,
                capture_output=True,
                text=True
            )
            return {"status": "success", "image": output_file}
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to capture image from {rtsp_url}: {e.stderr}"
            return {"status": "error", "error": error_msg}
        except FileNotFoundError:
            error_msg = "FFmpeg not found. Ensure FFmpeg is installed and in PATH."
            return {"status": "error", "error": error_msg}

    def do_POST(self):
        # Behandel POST-verzoeken
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            # Probeer JSON-data te parsen
            try:
                message = json.loads(post_data.decode())
            except json.JSONDecodeError:
                message = post_data.decode()
                logger.warning(f"Received non-JSON webhook: {message}")
                message = {"alarm": {}}

            # Log het webhook-bericht
            logger.info(f"Received POST webhook: {message}")

            # Extraheer relevante data uit webhook-payload
            device_id = None
            source = None
            event_timestamp = None
            license_plate = None
            try:
                triggers = message.get('alarm', {}).get('triggers', [])
                if triggers:
                    device_id = triggers[0].get('device')
                    source = triggers[0].get('key')
                    license_plate = triggers[0].get('value')  # License plate (e.g., Z144PRSIM1)
                    # Converteer timestamp (ms) naar tijd met milliseconden
                    timestamp_ms = triggers[0].get('timestamp', message.get('timestamp'))
                    if timestamp_ms:
                        event_timestamp = datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d_%H-%M-%S-%f')[:-3]  # Milliseconden (3 cijfers)
            except (KeyError, IndexError, TypeError):
                logger.warning("Could not extract device ID, source, timestamp, or license plate from webhook payload")

            # Valideer geëxtraheerde data
            if not all([device_id, source, event_timestamp]):
                logger.warning(f"Missing required data: device_id={device_id}, source={source}, event_timestamp={event_timestamp}")
                response = {"status": "received", "images": [], "error": "Missing required webhook data"}
            else:
                # Bepaal RTSP streams op basis van device ID
                streams = DEVICE_RTSP_MAP.get(device_id, [])
                if not streams:
                    logger.warning(f"No RTSP streams mapped for device ID: {device_id}")
                    response = {"status": "received", "images": [], "error": f"No RTSP streams for device {device_id}"}
                else:
                    # Bepaal submap
                    if license_plate:
                        sub_dir = os.path.join(IMAGE_DIR, license_plate)
                    else:
                        sub_dir = UNKNOWN_DIR
                    
                    # Zorg ervoor dat de submap bestaat
                    os.makedirs(sub_dir, exist_ok=True)
                    
                    # Capture afbeeldingen van alle streams in parallel
                    results = []
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        futures = []
                        for stream in streams:
                            stream_name = stream['name']
                            rtsp_url = stream['url']
                            # Genereer bestandsnaam: yyyy-mm-dd_hh-mm-ss-mmm_plateid_streamname.jpg
                            plate_id = license_plate if license_plate else "unknown"
                            output_file = os.path.join(sub_dir, f"{event_timestamp}_{plate_id}_{stream_name}.jpg")
                            futures.append(executor.submit(self.capture_image, rtsp_url, output_file))
                        
                        # Verzamel resultaten
                        for future in concurrent.futures.as_completed(futures):
                            result = future.result()
                            if result["status"] == "success":
                                logger.info(f"Image captured successfully: {result['image']}")
                            else:
                                logger.error(result["error"])
                            results.append(result)

                    # Bereid response voor
                    images = [r["image"] for r in results if r["status"] == "success"]
                    errors = [r["error"] for r in results if r["status"] == "error"]
                    response = {
                        "status": "received",
                        "images": images,
                        "errors": errors if errors else None
                    }

            # Stuur response
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        except Exception as e:
            logger.error(f"Error processing POST request: {str(e)}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

def run_server(port=SERVER_PORT):
    server_address = ('', port)
    httpd = HTTPServer(server_address, WebhookHandler)
    
    logger.info(f"Starting webhook server on port {port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down webhook server")
        httpd.server_close()

if __name__ == '__main__':
    run_server()