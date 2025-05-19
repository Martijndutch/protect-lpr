#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import subprocess
from datetime import datetime
import os
import concurrent.futures
import time

# Load configuration from config.json 
# version 1.0
# This script handles incoming webhooks, captures images and videos from RTSP streams,
# and operates a barrier based on license plate recognition events.
# Configuration file path

CONFIG_FILE = "/opt/protect-lpr/config.json"

try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
except FileNotFoundError:
    raise FileNotFoundError(f"Configuration file {CONFIG_FILE} not found")
except json.JSONDecodeError:
    raise ValueError(f"Invalid JSON in configuration file {CONFIG_FILE}")

# Retrieve configuration values
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
MAX_CONCURRENT_FFMPEG = config.get('server', {}).get('max_concurrent_ffmpeg', 4)
IGNORED_PLATES = [plate.lower() for plate in config.get('ignored_plates', [])]

# Ensure base directories exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(UNKNOWN_DIR, exist_ok=True)

# Configure logging
logger = logging.getLogger('WebhookLogger')
logger.setLevel(LOG_LEVEL)

# File handler for logging to file
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(file_handler)

# Stream handler for logging to console
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(console_handler)

def operate_barrier(license_plate, device_id):
    """Placeholder function to operate the barrier."""
    try:
        # Simulate barrier operation (replace with actual hardware/API call)
        logger.info(f"Operating barrier for license plate {license_plate} on device {device_id}")
        # Example: Send command to barrier hardware (e.g., via GPIO, HTTP request, etc.)
        # import requests
        # requests.post('http://barrier.local/open', data={'plate': license_plate})
        return {"status": "success", "message": f"Barrier opened for {license_plate}"}
    except Exception as e:
        logger.error(f"Failed to operate barrier for {license_plate}: {str(e)}")
        return {"status": "error", "error": str(e)}

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Handle GET requests
        logger.info("Received GET request")
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "received"}).encode())

    def capture_image(self, rtsp_url, output_file):
        """Helper function to capture a single image with FFmpeg."""
        ffmpeg_cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-vframes", "1",
            "-vf", "fps=1",
            "-f", "image2",
            "-y",
            output_file
        ]
        try:
            start_time = time.time()
            result = subprocess.run(
                ffmpeg_cmd,
                check=True,
                capture_output=True,
                text=True
            )
            logger.debug(f"FFmpeg image capture took {time.time() - start_time:.3f} seconds for {output_file}")
            return {"status": "success", "image": output_file}
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to capture image from {rtsp_url}: {e.stderr}"
            return {"status": "error", "error": error_msg}
        except FileNotFoundError:
            error_msg = "FFmpeg not found. Ensure FFmpeg is installed and in PATH."
            return {"status": "error", "error": error_msg}

    def capture_video(self, rtsp_url, output_file, duration_s):
        """Helper function to capture a video clip with FFmpeg."""
        if duration_s <= 0:
            return {"status": "skipped", "video": None}
        ffmpeg_cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-i", rtsp_url,
            "-t", str(duration_s),
            "-c:v", "copy",
            "-c:a", "copy",
            "-f", "mp4",
            "-y",
            output_file
        ]
        try:
            start_time = time.time()
            result = subprocess.run(
                ffmpeg_cmd,
                check=True,
                capture_output=True,
                text=True
            )
            logger.debug(f"FFmpeg video capture took {time.time() - start_time:.3f} seconds for {output_file}")
            return {"status": "success", "video": output_file}
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to capture video from {rtsp_url}: {e.stderr}"
            return {"status": "error", "error": error_msg}
        except FileNotFoundError:
            error_msg = "FFmpeg not found. Ensure FFmpeg is installed and in PATH."
            return {"status": "error", "error": error_msg}

    def capture_image_with_delay(self, rtsp_url, output_file, delay_ms):
        """Capture an image after a specified delay."""
        time.sleep(delay_ms / 1000.0)
        return self.capture_image(rtsp_url, output_file)

    def capture_image_sequence(self, rtsp_url, output_file_base, initial_delay_ms, num_images, interval_ms, video_duration_s, event_timestamp, plate_id, stream_name):
        """Capture a sequence of images and optionally a video in parallel."""
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_images + 1) as executor:
            futures = []
            # Schedule image captures
            for i in range(num_images):
                total_delay_ms = initial_delay_ms + (i * interval_ms)
                output_file = f"{output_file_base}_{i+1}.jpg"
                futures.append(executor.submit(
                    self.capture_image_with_delay,
                    rtsp_url,
                    output_file,
                    total_delay_ms
                ))
            # Schedule video capture if needed
            video_file = None
            if video_duration_s > 0:
                video_file = f"{output_file_base}_video.mp4"
                futures.append(executor.submit(
                    self.capture_video,
                    rtsp_url,
                    video_file,
                    video_duration_s
                ))
            
            # Collect results
            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                result = future.result()
                if result.get("status") == "success":
                    if "image" in result:
                        logger.info(f"Image {i+1}/{num_images} captured successfully: {result['image']}")
                    elif "video" in result and result["video"]:
                        logger.info(f"Video captured successfully: {result['video']}")
                elif result.get("status") != "skipped":
                    logger.error(f"Capture failed: {result['error']}")
                results.append(result)
        
        return results

    def do_POST(self):
        # Handle POST requests
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            # Try to parse JSON data
            try:
                message = json.loads(post_data.decode())
            except json.JSONDecodeError:
                message = post_data.decode()
                logger.warning(f"Received non-JSON webhook: {message}")
                message = {"alarm": {}}

            # Log the webhook message
            logger.info(f"Received POST webhook: {message}")

            # Extract relevant data from webhook payload
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
                    # Convert timestamp (ms) to time with milliseconds
                    timestamp_ms = triggers[0].get('timestamp', message.get('timestamp'))
                    if timestamp_ms:
                        event_timestamp = datetime.fromtimestamp(timestamp_ms / 1000).strftime('%Y-%m-%d_%H-%M-%S-%f')[:-3]  # Milliseconds (3 digits)
            except (KeyError, IndexError, TypeError):
                logger.warning("Could not extract device ID, source, timestamp, or license plate from webhook payload")

            # Validate extracted data
            if not all([device_id, source, event_timestamp, license_plate]):
                logger.warning(f"Missing required data: device_id={device_id}, source={source}, event_timestamp={event_timestamp}, license_plate={license_plate}")
                response = {"status": "received", "images": [], "videos": [], "barrier": None, "error": "Missing required webhook data"}
            else:
                # Operate barrier for all valid license plate events
                barrier_result = operate_barrier(license_plate, device_id)

                # Check if license plate is in ignored_plates
                skip_imaging = license_plate.lower() in IGNORED_PLATES
                if skip_imaging:
                    logger.info(f"License plate {license_plate} is in ignored_plates; skipping imaging")
                    response = {
                        "status": "received",
                        "images": [],
                        "videos": [],
                        "barrier": barrier_result,
                        "message": f"Imaging skipped for ignored plate {license_plate}"
                    }
                else:
                    # Determine RTSP streams based on device ID
                    streams = DEVICE_RTSP_MAP.get(device_id, [])
                    if not streams:
                        logger.warning(f"No RTSP streams mapped for device ID: {device_id}")
                        response = {
                            "status": "received",
                            "images": [],
                            "videos": [],
                            "barrier": barrier_result,
                            "error": f"No RTSP streams for device {device_id}"
                        }
                    else:
                        # Determine subdirectory
                        sub_dir = os.path.join(IMAGE_DIR, license_plate)
                        os.makedirs(sub_dir, exist_ok=True)
                        
                        # Capture images and videos from all streams in parallel
                        results = []
                        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_FFMPEG) as executor:
                            futures = []
                            for stream in streams:
                                stream_name = stream['name']
                                rtsp_url = stream['url']
                                # Retrieve capture settings with defaults
                                initial_delay_ms = stream.get('initial_delay_ms', 0)
                                num_images = stream.get('num_images', 1)
                                interval_ms = stream.get('interval_ms', 1000)
                                video_duration_s = stream.get('video_duration_s', 0)
                                # Generate base filename: yyyy-mm-dd_hh-mm-ss-mmm_plateid_streamname
                                plate_id = license_plate
                                output_file_base = os.path.join(sub_dir, f"{event_timestamp}_{plate_id}_{stream_name}")
                                # Schedule capture sequence in separate thread
                                futures.append(executor.submit(
                                    self.capture_image_sequence,
                                    rtsp_url,
                                    output_file_base,
                                    initial_delay_ms,
                                    num_images,
                                    interval_ms,
                                    video_duration_s,
                                    event_timestamp,
                                    plate_id,
                                    stream_name
                                ))
                            
                            # Collect results
                            for future in concurrent.futures.as_completed(futures):
                                result = future.result()
                                results.extend(result)  # Add all results from the sequence

                        # Prepare response
                        images = [r["image"] for r in results if r.get("status") == "success" and r.get("image")]
                        videos = [r["video"] for r in results if r.get("status") == "success" and r.get("video")]
                        errors = [r["error"] for r in results if r.get("status") == "error"]
                        response = {
                            "status": "received",
                            "images": images,
                            "videos": videos,
                            "barrier": barrier_result,
                            "errors": errors if errors else None
                        }

            # Send response
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