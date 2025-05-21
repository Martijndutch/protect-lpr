from flask import Flask, render_template, request, redirect, url_for, flash, Blueprint, session
import json
import os
from werkzeug.security import generate_password_hash, check_password_hash
import logging

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'protect-lpr-secret')

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

config_bp = Blueprint('config_bp', __name__, url_prefix='/config')

CONFIG_FILE = "/opt/protect-lpr/config.json"
USERS_FILE = "/opt/protect-lpr/users.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {
            'paths': {
                'log_dir': '/var/log/protect-lpr',
                'log_file': '/var/log/protect-lpr/protect-lpr.log',
                'image_dir': '/var/lib/protect-lpr/images',
                'unknown_dir': '/var/lib/protect-lpr/images/unknown'
            },
            'logging': {
                'level': 'INFO',
                'format': '%(asctime)s - %(levelname)s - %(message)s'
            },
            'server': {
                'port': 1025,
                'max_concurrent_ffmpeg': 4
            },
            'mysql_db_file': '/var/lib/protect-lpr/mysql/protect-lpr.db',
            'ignored_plates': [],
            'rtsp_streams': {}
        }
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def load_users():
    if not os.path.exists(USERS_FILE):
        users = {
            "admin": {
                "password": generate_password_hash("100%lpr"),
                "role": "admin"
            }
        }
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=2)
        return users
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

@config_bp.route('/', methods=['GET', 'POST'])
def config_page():
    if request.method == 'POST':
        try:
            logger.debug(f"Received form data: {request.form}")
            config = load_config()
            # Paths
            config['paths']['log_dir'] = request.form.get('log_dir', config['paths']['log_dir'])
            config['paths']['log_file'] = request.form.get('log_file', config['paths']['log_file'])
            config['paths']['image_dir'] = request.form.get('image_dir', config['paths']['image_dir'])
            config['paths']['unknown_dir'] = request.form.get('unknown_dir', config['paths']['unknown_dir'])
            # Logging
            config['logging']['level'] = request.form.get('log_level', config['logging']['level'])
            config['logging']['format'] = request.form.get('log_format', config['logging']['format'])
            # Server
            config['server']['port'] = int(request.form.get('server_port', config['server']['port']))
            config['server']['max_concurrent_ffmpeg'] = int(request.form.get('max_concurrent_ffmpeg', config['server']['max_concurrent_ffmpeg']))
            # MySQL DB file
            config['mysql_db_file'] = request.form.get('mysql_db_file', config['mysql_db_file'])
            # Ignored plates
            config['ignored_plates'] = [p for p in request.form.getlist('ignored_plates') if p.strip()]
            # RTSP streams
            rtsp_streams = {}
            device_ids = request.form.getlist('device_ids')
            for idx, device_id in enumerate(device_ids):
                if not device_id.strip():
                    logger.warning(f"Skipping device {idx+1}: empty device_id")
                    continue
                streams = []
                stream_prefix = f"streams_{idx+1}"
                names = request.form.getlist(f"stream_names_{stream_prefix}[]")
                urls = request.form.getlist(f"stream_urls_{stream_prefix}[]")
                initial_delays = request.form.getlist(f"initial_delay_ms_{stream_prefix}[]")
                intervals = request.form.getlist(f"interval_ms_{stream_prefix}[]")
                num_images = request.form.getlist(f"num_images_{stream_prefix}[]")
                video_durations = request.form.getlist(f"video_duration_s_{stream_prefix}[]")
                for i in range(len(names)):
                    if not names[i].strip() or not urls[i].strip():
                        logger.warning(f"Skipping stream {i+1} for device {device_id}: empty name or URL")
                        continue
                    streams.append({
                        "name": names[i],
                        "url": urls[i],
                        "initial_delay_ms": int(initial_delays[i]) if initial_delays[i] else 0,
                        "interval_ms": int(intervals[i]) if intervals[i] else 0,
                        "num_images": int(num_images[i]) if num_images[i] else 1,
                        "video_duration_s": int(video_durations[i]) if video_durations[i] else 0
                    })
                if streams:
                    rtsp_streams[device_id] = streams
            config['rtsp_streams'] = rtsp_streams
            save_config(config)
            flash("Configuratie succesvol opgeslagen.", "msg")
            return redirect(url_for('config_bp.config_page'))
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            flash(f"Fout bij opslaan: {e}", "err")
            config = load_config()
            return render_template('config.html', config=config)
    else:
        config = load_config()
        return render_template('config.html', config=config)

@config_bp.route('/users', methods=['GET', 'POST'])
def users_page():
    if session.get("role") != "admin":
        flash("Geen toegang.", "err")
        return redirect(url_for('config_bp.config_page'))
    users = load_users()
    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username', '').strip()
        if action == "add":
            password = request.form.get('password', '')
            role = request.form.get('role', 'readonly')
            if username in users:
                flash("Gebruiker bestaat al.", "err")
            else:
                users[username] = {
                    "password": generate_password_hash(password),
                    "role": role
                }
                save_users(users)
                flash("Gebruiker toegevoegd.", "msg")
        elif action == "delete":
            if username == "admin":
                flash("Kan admin niet verwijderen.", "err")
            elif username in users:
                users.pop(username)
                save_users(users)
                flash("Gebruiker verwijderd.", "msg")
    return render_template('users.html', users=users)

app.register_blueprint(config_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8083, debug=True)