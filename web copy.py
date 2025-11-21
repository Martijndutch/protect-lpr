# File version: 1.0.0
# Version history:
# 1.0.0 - Add version history and file version header. (2024-06-09)

from flask import Flask, render_template_string, request, redirect, url_for, flash, session
import sqlite3
import os
import json
import subprocess
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import logging
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("PIL (Pillow) is not installed. Image thumbnail generation is disabled.")

from datetime import datetime
import pytz

def setup_logging_from_config(config):
    log_dir = config["paths"].get("log_dir", "/opt/protect-lpr/logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "web.log")
    log_level = config.get("logging", {}).get("level", "INFO").upper()
    log_format = config.get("logging", {}).get("format", "%(asctime)s [%(levelname)s] %(message)s")
    log_level_num = getattr(logging, log_level, logging.INFO)
    # Remove all handlers associated with the root logger object (avoid duplicate logs)
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(
        level=log_level_num,
        format=log_format,
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return log_level_num

# Load config.json for all paths
with open("config.json", "r") as f:
    CONFIG = json.load(f)

# Setup logging using log_dir from config
LOG_LEVEL_NUM = setup_logging_from_config(CONFIG)

# Import and register config blueprint
from web_config_page import config_bp
app = Flask(__name__)
app.secret_key = "protect-lpr-secret"  # Needed for flash messages
app.register_blueprint(config_bp)

# Import and register purge_plate blueprint
from purge_plate import purge_bp
app.config['DB_FILE'] = CONFIG["paths"]["mysql_db_file"]
app.config['IMAGE_DIR'] = CONFIG["paths"]["image_dir"]
# Register purge_bp at root of /config, not /config/config
app.register_blueprint(purge_bp, url_prefix='/config')

# Import and register stats blueprint
from web_stats import stats_bp
app.register_blueprint(stats_bp)

IMAGE_DIR = CONFIG["paths"]["image_dir"]
DB_FILE = CONFIG["paths"]["mysql_db_file"]
USERS_FILE = CONFIG["users_file"]
CONFIG_FILE = "config.json"

import logging
logging.debug(f"Using DB_FILE: {DB_FILE}")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Protect LPR Imaging</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f7f7f7; }
        .container { max-width: 700px; margin: 40px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 32px; }
        h1 { text-align: center; color: #2c3e50; }
        p { text-align: center; color: #555; }
        form { text-align: center; margin-bottom: 32px; }
        input[type="text"] { padding: 8px; width: 200px; border-radius: 4px; border: 1px solid #ccc; }
        input[type="submit"] { padding: 8px 16px; border-radius: 4px; border: none; background: #2c3e50; color: #fff; cursor: pointer; }
        .event { margin-bottom: 32px; border-bottom: 1px solid #eee; padding-bottom: 16px; }
        .event h3 { margin: 0 0 8px 0; }
        .thumbs { display: flex; flex-wrap: wrap; gap: 10px; flex-direction: row; }
        .thumbs img, .thumbs video { max-width: 120px; max-height: 90px; border-radius: 4px; border: 1px solid #ccc; cursor: pointer; }
        .no-results { text-align: center; color: #888; }
        .config-link { text-align: right; margin-bottom: 16px; }
        .config-link a { color: #2c3e50; text-decoration: underline; }
        @media (max-width: 700px) {
            .container { margin: 10px; padding: 16px; }
            .thumbs img, .thumbs video { max-width: 80px; max-height: 60px; }
        }
        .date-form { text-align: center; margin-bottom: 32px; }
        input[type="date"] { padding: 8px; border-radius: 4px; border: 1px solid #ccc; }
        .thumb-popup-bg {
            display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100vw; height: 100vh;
            background: rgba(0,0,0,0.7); align-items: center; justify-content: center;
        }
        .thumb-popup-bg.active { display: flex; }
        .thumb-popup-content { background: #fff; padding: 16px; border-radius: 8px; max-width: 90vw; max-height: 90vh; }
        .thumb-popup-content img, .thumb-popup-content video { max-width: 80vw; max-height: 80vh; }
        .thumb-hover {
            position: relative;
            display: inline-block;
        }
        .thumb-hover .thumb-tooltip {
            visibility: hidden;
            background: #222; color: #fff; text-align: left; border-radius: 4px; padding: 4px 8px;
            position: absolute; z-index: 10; bottom: 110%; left: 50%; transform: translateX(-50%);
            opacity: 0; transition: opacity 0.2s;
            font-size: 13px;
            white-space: nowrap;
        }
        .thumb-hover:hover .thumb-tooltip {
            visibility: visible;
            opacity: 1;
        }
        .wildcard-help {
            display: inline-block;
            cursor: pointer;
            color: #2c3e50;
            font-weight: bold;
            margin-left: 6px;
            border-radius: 50%;
            border: 1px solid #2c3e50;
            width: 18px;
            height: 18px;
            text-align: center;
            line-height: 16px;
            font-size: 14px;
            background: #f7f7f7;
        }
        .wildcard-popup-bg {
            display: none; position: fixed; z-index: 2000; left: 0; top: 0; width: 100vw; height: 100vh;
            background: rgba(0,0,0,0.4); align-items: center; justify-content: center;
        }
        .wildcard-popup-bg.active { display: flex; }
        .wildcard-popup-content {
            background: #fff; padding: 24px; border-radius: 8px; max-width: 400px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            font-size: 15px; color: #222;
        }
        .wildcard-popup-content button { margin-top: 16px; }
        .video-icon {
            position: absolute;
            bottom: 4px;
            right: 4px;
            width: 28px;
            height: 28px;
            background: rgba(255,255,255,0.7);
            border-radius: 50%;
            padding: 2px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.15);
            display: block;
            z-index: 2;
        }
    </style>
    <script>
        // Store media info for navigation
        var popupMediaList = [];
        var popupMediaIndex = 0;

        function openPopup(src, type, info, mediaList, idx) {
            var popupBg = document.getElementById('thumb-popup-bg');
            var popupContent = document.getElementById('thumb-popup-content');
            popupContent.innerHTML = '';
            popupMediaList = mediaList || [];
            popupMediaIndex = (typeof idx === "number") ? idx : 0;

            // Media element
            if(type === 'video') {
                var vid = document.createElement('video');
                vid.src = src;
                vid.controls = true;
                vid.autoplay = true;
                vid.style.maxWidth = '80vw';
                vid.style.maxHeight = '80vh';
                popupContent.appendChild(vid);
            } else {
                var img = document.createElement('img');
                img.src = src;
                img.style.maxWidth = '80vw';
                img.style.maxHeight = '80vh';
                popupContent.appendChild(img);
            }

            // Info line
            var infoDiv = document.createElement('div');
            infoDiv.style = "margin-top:12px; text-align:center; font-size:15px; color:#222;";
            infoDiv.innerHTML = info;
            popupContent.appendChild(infoDiv);

            // Controls
            var controlsDiv = document.createElement('div');
            controlsDiv.style = "margin-top:10px; text-align:center;";
            var prevBtn = document.createElement('button');
            prevBtn.innerText = "Vorige";
            prevBtn.onclick = function(e) {
                e.stopPropagation();
                showPopupMedia(popupMediaIndex - 1);
            };
            prevBtn.disabled = (popupMediaIndex <= 0);

            var nextBtn = document.createElement('button');
            nextBtn.innerText = "Volgende";
            nextBtn.onclick = function(e) {
                e.stopPropagation();
                showPopupMedia(popupMediaIndex + 1);
            };
            nextBtn.disabled = (popupMediaList.length === 0 || popupMediaIndex >= popupMediaList.length - 1);

            var closeBtn = document.createElement('button');
            closeBtn.innerText = "Sluiten";
            closeBtn.onclick = function(e) {
                e.stopPropagation();
                closePopup();
            };

            controlsDiv.appendChild(prevBtn);
            controlsDiv.appendChild(nextBtn);
            controlsDiv.appendChild(closeBtn);
            popupContent.appendChild(controlsDiv);

            popupBg.classList.add('active');
        }

        function showPopupMedia(idx) {
            if(!popupMediaList.length) return;
            if(idx < 0 || idx >= popupMediaList.length) return;
            var item = popupMediaList[idx];
            openPopup(item.src, item.type, item.info, popupMediaList, idx);
        }

        function closePopup() {
            document.getElementById('thumb-popup-bg').classList.remove('active');
        }
        window.addEventListener('DOMContentLoaded', function() {
            document.getElementById('thumb-popup-bg').addEventListener('click', function(e) {
                if(e.target === this) closePopup();
            });
        });
        function showWildcardHelp() {
            document.getElementById('wildcard-popup-bg').classList.add('active');
        }
        function closeWildcardHelp() {
            document.getElementById('wildcard-popup-bg').classList.remove('active');
        }
    </script>
</head>
<body>
    {% if debug_info %}
    <div style="background:#ffeeba;color:#856404;padding:10px 20px;margin-bottom:20px;border-radius:6px;border:1px solid #ffeeba;">
      <b>DEBUG:</b>
      Onverwerkte logbestanden: {{ debug_info.num_unprocessed }}<br>
      Laatste kenteken: {{ debug_info.last_license }}<br>
      Tijd laatste event: {{ debug_info.last_event_time }}
    </div>
    {% endif %}
    <div id="thumb-popup-bg" class="thumb-popup-bg">
        <div id="thumb-popup-content" class="thumb-popup-content"></div>
    </div>
    <div id="wildcard-popup-bg" class="wildcard-popup-bg" onclick="if(event.target===this)closeWildcardHelp()">
        <div class="wildcard-popup-content">
            <b>Wildcard uitleg voor kenteken zoeken</b><br><br>
            Gebruik <b>*</b> voor nul of meer willekeurige tekens.<br>
            Gebruik <b>%</b> voor exact één willekeurig teken.<br>
            Spaties en streepjes worden genegeerd.<br><br>
            <b>Voorbeelden:</b><br>
            <code>12*AB</code> vindt alles dat begint met 12 en eindigt op AB.<br>
            <code>12%AB</code> vindt alles dat begint met 12, gevolgd door één teken, dan AB.<br>
            <code>1*2*3</code> vindt alles met 1, dan ergens 2, dan ergens 3.<br>
            <button onclick="closeWildcardHelp()">Sluiten</button>
        </div>
    </div>
    <div class="container">
        <div class="config-link">
            {% if session.get('role') == 'admin' %}
                <a href="{{ url_for('config_bp.config_page') }}">Configuratie</a> |
            {% endif %}
            <a href="{{ url_for('stats_bp.stats_page') }}">Statistieken</a>
            {% if session.get('username') %}
                | <a href="{{ url_for('logout') }}">Logout ({{ session.get('username') }})</a>
            {% endif %}
        </div>
        <h1>Protect LPR Imaging</h1>
        <form method="get" action="/" class="date-form">
            <label for="date">Toon alle events op datum:</label>
            <input type="date" id="date" name="date" value="{{ date|default('') }}">
            <input type="submit" value="Toon">
        </form>
        <form method="get" action="/">
            <label for="plate">Zoek op kenteken:</label>
            <input type="text" id="plate" name="plate" placeholder="Kenteken" value="{{ plate|default('') }}">
            <span class="wildcard-help" title="Wildcard uitleg" onclick="showWildcardHelp()">?</span>
            <input type="submit" value="Zoek">
        </form>
        {% if searched %}
            {% if events %}
                {% for event in events %}
                    <div class="event">
                        {# Show license plate and section_time only (section_time already contains date and time) #}
                        <h3>{{ event.license_plate }} - {{ event.section_time }}</h3>
                        <div class="thumbs">
                            {% for item in event['media_with_thumbs'] %}
                                {% set idx = loop.index0 %}
                                {% set media_type = "video" if item.media.endswith('.mp4') or item.media.endswith('.webm') else "image" %}
                                {% set info_line = item.datetime|utc_to_amsterdam ~ " | " ~ event.license_plate %}
                                {% set media_src = url_for('media_file', path=item.media) %}
                                {% set thumb_src = url_for('media_file', path=item.thumb if item.thumb else item.media) %}
                                <span class="thumb-hover">
                                    {% if media_type == "image" %}
                                        <img src="{{ thumb_src }}"
                                             alt="thumb"
                                             onclick='openPopup({{ media_src|tojson }}, {{ media_type|tojson }}, {{ info_line|tojson }}, {{ event.media_list|tojson }}, {{ idx }})'>
                                    {% elif media_type == "video" %}
                                        <img src="{{ thumb_src }}"
                                             alt="video thumb"
                                             onclick='openPopup({{ media_src|tojson }}, {{ media_type|tojson }}, {{ info_line|tojson }}, {{ event.media_list|tojson }}, {{ idx }})'>
                                        <img src="{{ url_for('static', filename='videoicon.svg') }}" alt="Video Icon" class="video-icon">
                                    {% endif %}
                                    <span class="thumb-tooltip">
                                        Type: {{ media_type }}<br>
                                        Kenteken: {{ event.license_plate }}<br>
                                        Datum/tijd: {{ item.datetime|utc_to_amsterdam }}
                                    </span>
                                    <div style="text-align:center; font-size:12px; color:#666; margin-top:2px;">
                                        {{ item.datetime|utc_to_amsterdam }}
                                    </div>
                                </span>
                            {% endfor %}
                        </div>
                    </div>
                {% endfor %}
            {% else %}
                <div class="no-results">
                    {% if plate %}
                        Geen resultaten gevonden voor kenteken "{{ plate }}"
                    {% elif date %}
                        Geen resultaten gevonden voor datum "{{ date }}"
                    {% endif %}
                </div>
            {% endif %}
        {% else %}
            <p>Welkom bij het Protect LPR Imaging systeem.<br>
            Dit is het initiële web framework. Meer functies volgen binnenkort.</p>
        {% endif %}
    </div>
</body>
</html>
"""

CONFIG_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Configuratie (JSON)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; background: #f7f7f7; }
        .container { max-width: 700px; margin: 40px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 32px; }
        h2 { text-align: center; }
        textarea { width: 100%; min-height: 400px; font-family: monospace; font-size: 15px; border-radius: 4px; border: 1px solid #ccc; padding: 8px; }
        input[type="submit"] { margin-top: 16px; padding: 8px 16px; border-radius: 4px; border: none; background: #2c3e50; color: #fff; cursor: pointer; }
        .msg { color: green; text-align: center; }
        .err { color: red; text-align: center; }
        a { display: inline-block; margin-top: 16px; color: #2c3e50; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Configuratie (JSON)</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        <form method="post">
            <textarea name="config_json">{{ config_json }}</textarea>
            <input type="submit" value="Opslaan">
        </form>
        <a href="/">Terug naar overzicht</a>
    </div>
</body>
</html>
"""

import re

def normalize_plate_input(plate):
    # Remove dashes and spaces, allow only alphanumerics (defense-in-depth)
    import re
    plate = plate.replace('-', '').replace(' ', '')
    return re.sub(r'[^A-Za-z0-9]', '', plate)

def plate_to_sql_like(plate):
    # Remove dashes and spaces, but keep * and % as wildcards
    import re
    plate = plate.replace('-', '').replace(' ', '')
    # Only allow alphanumerics and wildcards * and %
    plate = re.sub(r'[^A-Za-z0-9\*\%]', '', plate)
    # Replace * with % (SQL wildcard), % with _ (SQL single-char wildcard)
    plate = plate.replace('%', '_')
    plate = plate.replace('*', '%')
    return plate

def get_events_by_plate(plate):
    events = []
    if not plate:
        return events
    sql_like = plate_to_sql_like(plate)
    if len(sql_like) > 32:
        return []
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Lowercase both field and input for case-insensitive search
    c.execute(
        "SELECT datetime, license_plate, media_urls FROM event WHERE replace(replace(lower(license_plate), '-', ''), ' ', '') LIKE ? ORDER BY datetime DESC",
        (sql_like.lower(),)
    )
    for row in c.fetchall():
        dt, lp, media_json = row
        try:
            media = json.loads(media_json)
        except Exception:
            media = []
        events.append({
            "datetime": dt,
            "license_plate": lp,
            "media": media
        })
    conn.close()
    return events

def get_events_by_date(date_str):
    events = []
    if not date_str:
        return events
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Validate date_str format (YYYY-MM-DD)
    import re
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return []
    c.execute(
        "SELECT datetime, license_plate, media_urls FROM event WHERE datetime LIKE ? ORDER BY datetime DESC",
        (f"{date_str}%",)
    )
    # Instead of grouping, collect each event as its own entry with its own datetime and media
    for row in c.fetchall():
        dt, lp, media_json = row
        try:
            media = json.loads(media_json)
        except Exception:
            media = []
        events.append({
            "datetime": dt,
            "license_plate": lp,
            "media": media
        })
    conn.close()
    # Sort by datetime descending
    events.sort(key=lambda e: e["datetime"], reverse=True)
    return events

def parse_media_info(media_filename):
    # Example filename: 2024-06-07_12-34-56_ABC123_front_1.jpg or ..._side_video.mp4
    # Returns (camera_name, media_type)
    name = ""
    mtype = ""
    base = os.path.basename(media_filename)
    parts = base.split('_')
    if len(parts) >= 4:
        name = parts[-2]
        ext = base.split('.')[-1].lower()
        if ext in ['jpg', 'jpeg', 'png']:
            mtype = "foto"
        elif ext in ['mp4', 'webm']:
            mtype = "video"
        else:
            mtype = ext
    return name, mtype

def get_video_thumbnail(video_path):
    """
    Returns the standardized thumbnail path for a video.
    If it does not exist, generate it using ffmpeg.
    """
    base, ext = os.path.splitext(video_path)
    thumb_path = base + ".thumb.jpg"
    if not os.path.exists(thumb_path):
        try:
            # Generate thumbnail using ffmpeg (first frame)
            subprocess.run([
                "ffmpeg", "-y", "-i", video_path, "-ss", "00:00:00.000", "-vframes", "1", "-vf", "scale=320:-1", thumb_path
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logging.error(f"Failed to generate video thumbnail for {video_path}: {e}")
            return None
    return thumb_path if os.path.exists(thumb_path) else None

def get_image_thumbnail(image_path):
    """
    Returns the standardized thumbnail path for an image.
    If it does not exist, generate it using PIL if available.
    """
    base, ext = os.path.splitext(image_path)
    thumb_path = base + ".thumb.jpg"
    if not os.path.exists(thumb_path):
        if not PIL_AVAILABLE:
            logging.warning(f"Cannot generate thumbnail for {image_path}: PIL not available.")
            return None
        try:
            with Image.open(image_path) as img:
                img.thumbnail((320, 240))
                img.save(thumb_path, "JPEG")
        except Exception as e:
            logging.error(f"Failed to generate image thumbnail for {image_path}: {e}")
            return None
    return thumb_path if os.path.exists(thumb_path) else None

def load_users():
    if not os.path.exists(USERS_FILE):
        # Create initial admin user if file does not exist
        users = {
            "admin": {
                "password": generate_password_hash("100%lpr"),
                "role": "admin"
            }
        }
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=2)
        logging.info("Created initial admin user.")
        return users
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    # Prevent path traversal for USERS_FILE
    if not os.path.abspath(USERS_FILE).startswith(os.path.abspath(os.path.dirname(__file__))):
        raise Exception("Invalid users file path")
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)
    logging.info("User database updated.")

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "username" not in session:
                return redirect(url_for("login", next=request.url))
            if role and session.get("role") != role:
                flash("Geen toegang.", "err")
                return redirect(url_for("home"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.route('/login', methods=['GET', 'POST'])
def login():
    users = load_users()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        # Only allow alphanumeric usernames (defense-in-depth)
        import re
        if not re.match(r'^[A-Za-z0-9_@.-]{1,32}$', username):
            flash("Ongeldige gebruikersnaam.", "err")
            return render_template_string("""
            <!DOCTYPE html>
            <html><head>
            <title>Login</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
            body { font-family: Arial, sans-serif; background: #f7f7f7; }
            .container { max-width: 350px; margin: 60px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 32px; }
            h2 { text-align: center; }
            input[type="text"], input[type="password"] { width: 100%; padding: 8px; margin-bottom: 12px; border-radius: 4px; border: 1px solid #ccc; }
            input[type="submit"] { width: 100%; padding: 8px; border-radius: 4px; border: none; background: #2c3e50; color: #fff; cursor: pointer; }
            .msg { color: green; text-align: center; }
            .err { color: red; text-align: center; }
            </style>
            </head><body>
            <div class="container">
                <h2>Login</h2>
                {% with messages = get_flashed_messages(with_categories=true) %}
                  {% if messages %}
                    {% for category, message in messages %}
                      <div class="{{ category }}">{{ message }}</div>
                    {% endfor %}
                  {% endif %}
                {% endwith %}
                <form method="post">
                    <input type="text" name="username" placeholder="Gebruikersnaam" required>
                    <input type="password" name="password" placeholder="Wachtwoord" required>
                    <input type="submit" value="Login">
                </form>
            </div>
            </body></html>
            """)
        user = users.get(username)
        if user and check_password_hash(user['password'], password):
            session['username'] = username
            session['role'] = user['role']
            logging.info(f"User '{username}' logged in.")
            flash("Ingelogd als %s" % username, "msg")
            return redirect(url_for('home'))
        else:
            logging.warning(f"Failed login attempt for user '{username}'.")
            flash("Ongeldige gebruikersnaam of wachtwoord.", "err")
    return render_template_string("""
    <!DOCTYPE html>
    <html><head>
    <title>Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
    body { font-family: Arial, sans-serif; background: #f7f7f7; }
    .container { max-width: 350px; margin: 60px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 32px; }
    h2 { text-align: center; }
    input[type="text"], input[type="password"] { width: 100%; padding: 8px; margin-bottom: 12px; border-radius: 4px; border: 1px solid #ccc; }
    input[type="submit"] { width: 100%; padding: 8px; border-radius: 4px; border: none; background: #2c3e50; color: #fff; cursor: pointer; }
    .msg { color: green; text-align: center; }
    .err { color: red; text-align: center; }
    </style>
    </head><body>
    <div class="container">
        <h2>Login</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        <form method="post">
            <input type="text" name="username" placeholder="Gebruikersnaam" required>
            <input type="password" name="password" placeholder="Wachtwoord" required>
            <input type="submit" value="Login">
        </form>
    </div>
    </body></html>
    """)

@app.route('/logout')
def logout():
    username = session.get('username')
    session.clear()
    logging.info(f"User '{username}' logged out.")
    flash("Uitgelogd.", "msg")
    return redirect(url_for('login'))

@app.route('/users', methods=['GET', 'POST'])
@login_required(role="admin")
def users():
    users = load_users()
    msg = None
    err = None
    if request.method == 'POST':
        action = request.form.get('action')
        username = request.form.get('username', '').strip()
        if action == "add":
            password = request.form.get('password', '')
            role = request.form.get('role', 'readonly')
            if username in users:
                flash("Gebruiker bestaat al.", "err")
                logging.warning(f"Attempt to add existing user '{username}'.")
            else:
                users[username] = {
                    "password": generate_password_hash(password),
                    "role": role
                }
                save_users(users)
                logging.info(f"User '{username}' added with role '{role}'.")
                flash("Gebruiker toegevoegd.", "msg")
        elif action == "delete":
            if username == "admin":
                flash("Kan admin niet verwijderen.", "err")
                logging.warning("Attempt to delete admin user.")
            elif username in users:
                users.pop(username)
                save_users(users)
                logging.info(f"User '{username}' deleted.")
                flash("Gebruiker verwijderd.", "msg")
    return render_template_string("""
    <!DOCTYPE html>
    <html><head>
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
    </style>
    </head><body>
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
        <a href="{{ url_for('home') }}">Terug naar overzicht</a>
    </div>
    </body></html>
    """, users=users)

@app.route('/', methods=['GET'])
@login_required()
def home():
    # Reload config at every home page load
    with open("config.json", "r") as f:
        config = json.load(f)
    # Re-setup logging in case config changed
    global LOG_LEVEL_NUM
    LOG_LEVEL_NUM = setup_logging_from_config(config)
    # Use config for paths
    image_dir = config["paths"]["image_dir"]
    db_file = config["paths"]["mysql_db_file"]
    plate = request.args.get('plate', '').strip()
    date = request.args.get('date', '').strip()
    # Default to today if no date or plate is given
    if not plate and not date:
        date = datetime.now().strftime("%Y-%m-%d")
    searched = bool(plate or date)
    if plate:
        events = get_events_by_plate(plate)
    elif date:
        events = get_events_by_date(date)
    else:
        events = []

    # --- DEBUG INFO: Show at top if logging level is DEBUG ---
    debug_info = None
    if LOG_LEVEL_NUM <= logging.DEBUG:
        # Count unprocessed log files
        unprocessed_logs = [
            f for f in os.listdir(image_dir)
            if f.startswith("event_") and f.endswith(".log")
        ]
        num_unprocessed = len(unprocessed_logs)

        # Get last processed event from DB
        conn = sqlite3.connect(db_file)
        c = conn.cursor()
        c.execute("SELECT license_plate, datetime FROM event ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        last_license = row[0] if row else "N/A"
        last_event_time = row[1] if row else "N/A"

        debug_info = {
            "num_unprocessed": num_unprocessed,
            "last_license": last_license,
            "last_event_time": last_event_time
        }

    # Group media files that are within 1 minute of each other
    grouped_events = []
    import datetime as dtmod  # avoid shadowing the datetime class

    # Helper to parse event datetime
    def parse_dt(dt):
        for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(dt, fmt)
            except Exception:
                continue
        return None

    # Flatten all media with their event info and datetime
    all_media = []
    for event in events:
        lp = event["license_plate"]
        dt = event["datetime"]
        dt_obj = parse_dt(dt)
        for media in event["media"]:
            all_media.append({
                "license_plate": lp,
                "event_datetime": dt,
                "event_dt_obj": dt_obj,
                "media": media
            })

    # Sort all media by datetime (oldest first)
    all_media.sort(key=lambda m: m["event_dt_obj"] or datetime.min)

    # Group media within 1 minute
    group = []
    last_dt = None
    last_lp = None
    for m in all_media:
        curr_dt = m["event_dt_obj"]
        curr_lp = m["license_plate"]
        if not group:
            group = [m]
            last_dt = curr_dt
            last_lp = curr_lp
        else:
            # Same license plate and within 1 minute?
            if curr_lp == last_lp and curr_dt and last_dt and abs((curr_dt - last_dt).total_seconds()) <= 60:
                group.append(m)
                last_dt = curr_dt
            else:
                grouped_events.append({
                    "license_plate": last_lp,
                    "datetime": group[0]["event_datetime"],
                    "media_group": list(group)
                })
                group = [m]
                last_dt = curr_dt
                last_lp = curr_lp
    if group:
        grouped_events.append({
            "license_plate": last_lp,
            "datetime": group[0]["event_datetime"],
            "media_group": list(group)
        })

    # Prepare for template
    final_events = []
    for group in grouped_events:
        lp = group["license_plate"]
        dt = group["datetime"]
        # Extract date part (YYYY-MM-DD) from datetime string
        if "_" in dt:
            date_part = dt.split("_")[0]
        else:
            date_part = dt.split(" ")[0]
        # Format time for section header
        section_time = utc_to_amsterdam(dt)
        thumbs = []
        media_list = []
        sorted_media_group = sorted(group["media_group"], key=lambda m: m["event_dt_obj"] or datetime.min)
        for m in sorted_media_group:
            media = m["media"]
            cam_name, mtype = parse_media_info(media)
            thumb = None
            if media.endswith(('.mp4', '.webm')):
                video_abs = os.path.join(image_dir, media)
                thumb_abs = get_video_thumbnail(video_abs)
                thumb = os.path.relpath(thumb_abs, image_dir) if thumb_abs else None
                media_type = "video"
            elif media.endswith(('.jpg', '.jpeg', '.png')):
                image_abs = os.path.join(image_dir, media)
                thumb_abs = get_image_thumbnail(image_abs)
                thumb = os.path.relpath(thumb_abs, image_dir) if thumb_abs else None
                media_type = "image"
            else:
                media_type = "image"
            thumbs.append({
                "media": media,
                "thumb": thumb,
                "cam_name": cam_name,
                "mtype": mtype,
                "datetime": dt
            })
            info_line = f"{utc_to_amsterdam(dt)} | {lp}"
            media_list.append({
                "src": url_for('media_file', path=media),
                "type": media_type,
                "info": info_line
            })
        final_events.append({
            "datetime": dt,
            "license_plate": lp,
            "date_part": date_part,
            "section_time": section_time,  # add section time for header
            "media_with_thumbs": thumbs,
            "media_list": media_list
        })

    # Sort by section_time (oldest first), then by license_plate, then by date_part, then by datetime
    def parse_section_time(section_time):
        # Try multiple formats for robustness
        for fmt in ("%d-%m-%Y %H:%M", "%Y-%m-%d_%H-%M-%S", "%Y-%m-%d_%H-%M-%S-%f"):
            try:
                return datetime.strptime(section_time, fmt)
            except Exception:
                continue
        # Try to extract from string like '2025-05-26_11-07-13-000'
        import re
        m = re.match(r"(\d{4}-\d{2}-\d{2})[_ ](\d{2})-(\d{2})-(\d{2})(?:-\d+)?", section_time)
        if m:
            dt_str = f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}"
            try:
                return datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        return datetime.min

    final_events.sort(
        key=lambda e: (
            parse_section_time(e.get("section_time", "")),
            e["license_plate"],
            e["date_part"],
            e["datetime"]
        )
    )
    return render_template_string(
        HTML_TEMPLATE,
        plate=plate,
        date=date,
        events=final_events,
        searched=searched,
        session=session,
        debug_info=debug_info
    )

@app.route('/media/<path:path>')
@login_required()
def media_file(path):
    # Prevent directory traversal
    abs_path = os.path.abspath(os.path.join(IMAGE_DIR, path))
    # Ensure abs_path is within IMAGE_DIR
    if not abs_path.startswith(os.path.abspath(IMAGE_DIR)):
        from flask import abort
        abort(403)
    if not os.path.isfile(abs_path):
        from flask import abort
        abort(404)
    from flask import send_file
    # Set mimetype based on file extension
    mimetype = None
    if abs_path.lower().endswith('.jpg') or abs_path.lower().endswith('.jpeg'):
        mimetype = 'image/jpeg'
    elif abs_path.lower().endswith('.png'):
        mimetype = 'image/png'
    elif abs_path.lower().endswith('.mp4'):
        mimetype = 'video/mp4'
    elif abs_path.lower().endswith('.webm'):
        mimetype = 'video/webm'
    return send_file(abs_path, mimetype=mimetype)

# Only allow admin to access config page
@app.route('/config', methods=['GET', 'POST'])
@login_required(role="admin")
def config():
    msg = None
    err = None
    if request.method == 'POST':
        config_json = request.form.get('config_json', '')
        try:
            # Validate config_json is valid JSON and not too large
            if len(config_json) > 100_000:
                raise Exception("Config too large")
            parsed = json.loads(config_json)
            # Optionally, validate structure here
            with open(CONFIG_FILE, 'w') as f:
                json.dump(parsed, f, indent=2)
            logging.info(f"Configuration updated by user '{session.get('username')}'.")
            flash("Configuratie succesvol opgeslagen.", "msg")
            return redirect(url_for('config'))
        except Exception as e:
            logging.error(f"Error saving configuration: {e}")
            flash(f"Fout bij opslaan: {e}", "err")
            # Show the submitted (possibly invalid) JSON again
            return render_template_string(CONFIG_TEMPLATE, config_json=config_json)
    else:
        # Load current config
        try:
            with open(CONFIG_FILE, 'r') as f:
                config_json = json.dumps(json.load(f), indent=2)
        except Exception as e:
            config_json = "{}"
            logging.error(f"Error loading configuration: {e}")
            flash(f"Fout bij laden van configuratie: {e}", "err")
        return render_template_string(CONFIG_TEMPLATE, config_json=config_json)

@app.route('/config/auto_save', methods=['POST'])
@login_required(role="admin")
def auto_save_config():
    data = request.get_json(force=True)
    try:
        # Load config
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        # Update config fields from posted data
        config['paths']['log_dir'] = data.get('log_dir', config['paths'].get('log_dir', ''))
        config['paths']['image_dir'] = data.get('image_dir', config['paths'].get('image_dir', ''))
        config['sqlite3_db_file'] = data.get('sqlite3_db_file', config.get('sqlite3_db_file', ''))
        config['users_file'] = data.get('users_file', config.get('users_file', ''))
        # --- Handle ignored plates with comments ---
        plates = data.get('ignored_plates', [])
        comments = data.get('ignored_plates_comment', [])
        if isinstance(plates, list) and isinstance(comments, list) and len(comments) == len(plates):
            config['ignored_plates'] = [
                {"plate": p.strip(), "comment": c.strip()}
                for p, c in zip(plates, comments)
                if p.strip()
            ]
        else:
            config['ignored_plates'] = [
                {"plate": p.strip(), "comment": ""}
                for p in plates if p.strip()
            ]
        if 'web' not in config:
            config['web'] = {}
        config['web']['port'] = int(data.get('web_port', config['web'].get('port', 8082)))
        # Backup video and window settings
        if 'backup_original_video' in data:
            config['backup_original_video'] = bool(data['backup_original_video']) if isinstance(data['backup_original_video'], bool) else str(data['backup_original_video']).lower() in ['true', '1', 'yes', 'on']
        if 'video_window_start_seconds' in data:
            config['video_window_start_seconds'] = int(data['video_window_start_seconds'])
        if 'video_window_end_seconds' in data:
            config['video_window_end_seconds'] = int(data['video_window_end_seconds'])
        # Always update log level if present
        if 'log_level' in data and data['log_level']:
            if 'logging' not in config:
                config['logging'] = {}
            config['logging']['level'] = data['log_level']
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

# Add this filter to your Flask app to support the date formatting in the template
def todatetime(value, fmt):
    from datetime import datetime
    try:
        return datetime.strptime(value, fmt)
    except Exception:
        return None

app.jinja_env.filters['todatetime'] = todatetime

def utc_to_amsterdam(dt_str):
    """Format datetime string as 'DD-MM-YYYY HH:MM' (no timezone conversion)."""
    for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.strftime("%d-%m-%Y %H:%M")
        except Exception:
            continue
    return dt_str  # fallback

app.jinja_env.filters['utc_to_amsterdam'] = utc_to_amsterdam

if __name__ == '__main__':
    # Use port from config if available, else default to 8082
    port = CONFIG.get("web", {}).get("port", 8082)
    app.run(host='0.0.0.0', port=port, debug=True)
