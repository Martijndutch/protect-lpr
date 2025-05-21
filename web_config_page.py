from flask import Flask, render_template_string, request, redirect, url_for, flash, Blueprint, session
import json
import os
from werkzeug.security import generate_password_hash, check_password_hash
import logging

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'protect-lpr-secret')  # Use environment variable for secret key

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

config_bp = Blueprint('config_bp', __name__, url_prefix='/config')

CONFIG_FILE = "/opt/protect-lpr/config.json"
USERS_FILE = "/opt/protect-lpr/users.json"

CONFIG_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Protect LPR Imaging - Configuratie</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f7f7f7; }
        .container { max-width: 900px; margin: 40px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 32px; }
        h1 { text-align: center; color: #2c3e50; }
        form { margin-top: 24px; }
        label { display: block; margin-top: 16px; font-weight: bold; }
        input[type="text"], input[type="number"] { width: 100%; padding: 8px; border-radius: 4px; border: 1px solid #ccc; margin-top: 4px; }
        textarea { width: 100%; min-height: 60px; font-family: monospace; font-size: 14px; border-radius: 4px; border: 1px solid #ccc; padding: 8px; }
        input[type="submit"], button { margin-top: 16px; padding: 8px 16px; border-radius: 4px; border: none; background: #2c3e50; color: #fff; cursor: pointer; }
        .msg { color: green; text-align: center; }
        .err { color: red; text-align: center; }
        a { display: inline-block; margin-top: 16px; color: #2c3e50; }
        .section { margin-bottom: 32px; }
        .inline-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
        .inline-list input[type="text"] { width: auto; flex: 1; }
        .inline-list button { padding: 4px 8px; }
        .rtsp-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
        .rtsp-table th, .rtsp-table td { border: 1px solid #ccc; padding: 6px 8px; text-align: left; }
        .rtsp-table th { background: #f0f0f0; }
        .rtsp-table input, .rtsp-table select { width: 100%; }
        .rtsp-actions { display: flex; gap: 8px; }
        .add-btn { background: #27ae60; }
        .del-btn { background: #c0392b; }
    </style>
    <script>
        function addDeviceRow() {
            const table = document.getElementById('rtsp_devices');
            const existingDevices = {{ config['rtsp_streams']|length }};
            const newIndex = table.rows.length - 1 + existingDevices;
            const row = table.insertRow(-1);
            row.innerHTML = `
                <td><input type="text" name="device_ids" placeholder="Device ID"></td>
                <td colspan="8">
                    <table class="rtsp-table" style="margin:0;">
                        <tbody id="streams_${newIndex}">
                            <!-- Stream rows will be added here -->
                        </tbody>
                    </table>
                    <button type="button" class="add-btn" onclick="addStreamRow('streams_${newIndex}')">+ Stream</button>
                </td>
                <td><button type="button" class="del-btn" onclick="this.closest('tr').remove()">Verwijder</button></td>
            `;
        }
        function addStreamRow(tbodyId) {
            const tbody = document.getElementById(tbodyId);
            const row = document.createElement('tr');
            row.innerHTML = `
                <td><input type="text" name="stream_names_${tbodyId}[]" placeholder="Naam"></td>
                <td><input type="text" name="stream_urls_${tbodyId}[]" placeholder="RTSP URL"></td>
                <td><input type="number" name="initial_delay_ms_${tbodyId}[]" value="100"></td>
                <td><input type="number" name="interval_ms_${tbodyId}[]" value="200"></td>
                <td><input type="number" name="num_images_${tbodyId}[]" value="2"></td>
                <td><input type="number" name="video_duration_s_${tbodyId}[]" value="0"></td>
                <td><button type="button" class="del-btn" onclick="this.closest('tr').remove()">Verwijder</button></td>
            `;
            tbody.appendChild(row);
        }
    </script>
</head>
<body>
    <div class="container">
        <h1>Configuratie aanpassen</h1>
        <div style="text-align:right;"><a href="{{ url_for('config_bp.users_page') }}">Gebruikersbeheer</a></div>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        <form method="post">
            <div class="section">
                <label>Log directory</label>
                <input type="text" name="log_dir" value="{{ config['paths']['log_dir'] }}">
                <label>Log file</label>
                <input type="text" name="log_file" value="{{ config['paths']['log_file'] }}">
                <label>Image directory</label>
                <input type="text" name="image_dir" value="{{ config['paths']['image_dir'] }}">
                <label>Unknown directory</label>
                <input type="text" name="unknown_dir" value="{{ config['paths']['unknown_dir'] }}">
            </div>
            <div class="section">
                <label>Logging level</label>
                <input type="text" name="log_level" value="{{ config['logging']['level'] }}">
                <label>Logging format</label>
                <input type="text" name="log_format" value="{{ config['logging']['format'] }}">
            </div>
            <div class="section">
                <label>Server port</label>
                <input type="number" name="server_port" value="{{ config['server']['port'] }}">
                <label>Max concurrent ffmpeg</label>
                <input type="number" name="max_concurrent_ffmpeg" value="{{ config['server']['max_concurrent_ffmpeg'] }}">
            </div>
            <div class="section">
                <label>MySQL DB file</label>
                <input type="text" name="mysql_db_file" value="{{ config['mysql_db_file'] }}">
            </div>
            <div class="section">
                <label>Genegeerde kentekens (Ignored plates)</label>
                <div id="ignored_plates_list" class="inline-list">
                    {% for plate in config['ignored_plates'] %}
                        <input type="text" name="ignored_plates" value="{{ plate }}">
                    {% endfor %}
                    <input type="text" name="ignored_plates" placeholder="Kenteken">
                </div>
                <button type="button" onclick="document.getElementById('ignored_plates_list').appendChild(document.createElement('input')).setAttribute('name','ignored_plates')">Voeg toe</button>
            </div>
            <div class="section">
                <label>RTSP streams per device</label>
                <table class="rtsp-table" id="rtsp_devices">
                    <thead>
                        <tr>
                            <th style="width:120px;">Device ID</th>
                            <th>Streams</th>
                            <th style="width:80px;">Actie</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for device_id, streams in config['rtsp_streams'].items() %}
                        {% set device_index = loop.index %}
                        <tr>
                            <td>
                                <input type="text" name="device_ids" value="{{ device_id }}">
                            </td>
                            <td>
                                <table class="rtsp-table">
                                    <thead>
                                        <tr>
                                            <th>Naam</th>
                                            <th>RTSP URL</th>
                                            <th>Initial delay (ms)</th>
                                            <th>Interval (ms)</th>
                                            <th># Images</th>
                                            <th>Video duration (s)</th>
                                            <th>Actie</th>
                                        </tr>
                                    </thead>
                                    <tbody id="streams_{{ device_index }}">
                                        {% for stream in streams %}
                                        <tr>
                                            <td><input type="text" name="stream_names_streams_{{ device_index }}[]" value="{{ stream['name'] }}"></td>
                                            <td><input type="text" name="stream_urls_streams_{{ device_index }}[]" value="{{ stream['url'] }}"></td>
                                            <td><input type="number" name="initial_delay_ms_streams_{{ device_index }}[]" value="{{ stream['initial_delay_ms'] }}"></td>
                                            <td><input type="number" name="interval_ms_streams_{{ device_index }}[]" value="{{ stream['initial_delay_ms'] }}"></td>
                                            <td><input type="number" name="num_images_streams_{{ device_index }}[]" value="{{ stream['num_images'] }}"></td>
                                            <td><input type="number" name="video_duration_s_streams_{{ device_index }}[]" value="{{ stream['video_duration_s'] }}"></td>
                                            <td><button type="button" class="del-btn" onclick="this.closest('tr').remove()">Verwijder</button></td>
                                        </tr>
                                        {% endfor %}
                                    </tbody>
                                </table>
                                <button type="button" class="add-btn" onclick="addStreamRow('streams_{{ device_index }}')">+ Stream</button>
                            </td>
                            <td><button type="button" class="del-btn" onclick="this.closest('tr').remove()">Verwijder</button></td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
                <button type="button" class="add-btn" onclick="addDeviceRow()">+ Device</button>
            </div>
            <input type="submit" value="Opslaan">
        </form>
        <a href="/">Terug naar overzicht</a>
    </div>
</body>
</html>
"""

USERS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Gebruikersbeheer</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
    body { font-family: Arial, sans-serif; background: #f7f7f7; }
    .container { max-width: 500px; margin: 40px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 32px; }
    h2 { text-align: center; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 16px; }
    th, td { border: 1px solid #ccc; padding: 6px 8px; text-align: left; }
    th { background: #f0f0f0; }
    input[type="text"], input[type="password"], select { width: 100%; padding: 6px; border-radius: 4px; border: 1px solid #ccc; }
    input[type="submit"], button { padding: 6px 12px; border-radius: 4px; border: none; background: #2c3e50; color: #fff; cursor: pointer; }
    .msg { color: green; text-align: center; }
    .err { color: red; text-align: center; }
    a { display: inline-block; margin-top: 16px; color: #2c3e50; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Gebruikersbeheer</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        <table>
            <tr><th>Gebruiker</th><th>Rol</th><th>Actie</th></tr>
            {% for uname, u in users.items() %}
            <tr>
                <td>{{ uname }}</td>
                <td>{{ u['role'] }}</td>
                <td>
                    {% if uname != 'admin' %}
                    <form method="post" style="display:inline;">
                        <input type="hidden" name="username" value="{{ uname }}">
                        <input type="hidden" name="action" value="delete">
                        <input type="submit" value="Verwijder">
                    </form>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </table>
        <h3>Nieuwe gebruiker toevoegen</h3>
        <form method="post">
            <input type="hidden" name="action" value="add">
            <input type="text" name="username" placeholder="Gebruikersnaam" required>
            <input type="password" name="password" placeholder="Wachtwoord" required>
            <select name="role">
                <option value="readonly">Alleen lezen</option>
                <option value="admin">Admin</option>
            </select>
            <input type="submit" value="Toevoegen">
        </form>
        <a href="{{ url_for('config_bp.config_page') }}">Terug naar configuratie</a>
    </div>
</body>
</html>
"""

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
            return render_template_string(CONFIG_TEMPLATE, config=config)
    else:
        config = load_config()
        return render_template_string(CONFIG_TEMPLATE, config=config)

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
    return render_template_string(USERS_TEMPLATE, users=users)

app.register_blueprint(config_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8083, debug=True)