from flask import Flask, render_template_string, request, redirect, url_for, flash, session
import sqlite3
import os
import json
import subprocess
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import logging

# Load config.json for all paths
with open("/opt/protect-lpr/config.json", "r") as f:
    CONFIG = json.load(f)

# Setup logging using log_dir from config
LOG_DIR = CONFIG["paths"].get("log_dir", "/opt/protect-lpr/logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "web.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

app = Flask(__name__)
app.secret_key = "protect-lpr-secret"  # Needed for flash messages

# Import and register config blueprint
from web_config_page import config_bp
app.register_blueprint(config_bp)

IMAGE_DIR = CONFIG["paths"]["image_dir"]
DB_FILE = CONFIG.get("mysql_db_file", "/opt/protect-lpr/lpr.db")  # Use default if not set
USERS_FILE = CONFIG.get("users_file", "/opt/protect-lpr/users.json")

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
        .thumbs { display: flex; flex-wrap: wrap; gap: 10px; }
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
        function openPopup(src, type) {
            var popupBg = document.getElementById('thumb-popup-bg');
            var popupContent = document.getElementById('thumb-popup-content');
            popupContent.innerHTML = '';
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
            popupBg.classList.add('active');
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
            {% if session.get('username') %}
                <a href="{{ url_for('logout') }}">Logout ({{ session.get('username') }})</a>
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
                        <h3>{{ event['datetime'] }} - {{ event['license_plate'] }}</h3>
                        <div class="thumbs">
                            {% for item in event['media_with_thumbs'] %}
                                <span class="thumb-hover">
                                    {% if item.media.endswith('.jpg') or item.media.endswith('.jpeg') or item.media.endswith('.png') %}
                                        <img src="{{ url_for('media_file', path=item.thumb if item.thumb else item.media) }}"
                                             alt="thumb"
                                             onclick="openPopup('{{ url_for('media_file', path=item.media) }}', 'image')">
                                    {% elif item.media.endswith('.mp4') or item.media.endswith('.webm') %}
                                        <img src="{{ url_for('media_file', path=item.thumb if item.thumb else item.media) }}"
                                             alt="video thumb"
                                             onclick="openPopup('{{ url_for('media_file', path=item.media) }}', 'video')">
                                        <img src="{{ url_for('static', filename='videoicon.svg') }}" alt="Video Icon" class="video-icon">
                                    {% endif %}
                                    <span class="thumb-tooltip">
                                        Camera: {{ item.cam_name }}<br>
                                        Type: {{ item.mtype }}
                                    </span>
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

import re

def normalize_plate_input(plate):
    # Remove dashes and spaces
    return plate.replace('-', '').replace(' ', '')

def plate_to_sql_like(plate):
    # Remove dashes and spaces
    plate = normalize_plate_input(plate)
    # Replace * with % (SQL wildcard for zero or more), % with _ (SQL single char)
    # (order matters: replace % first to avoid double replacement)
    plate = plate.replace('%', '_')
    plate = plate.replace('*', '%')
    return plate

def get_events_by_plate(plate):
    events = []
    if not plate:
        return events
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    sql_like = plate_to_sql_like(plate)
    # Use parameterized query to prevent SQL injection
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
    c.execute(
        "SELECT datetime, license_plate, media_urls FROM event WHERE datetime LIKE ? ORDER BY datetime DESC",
        (f"{date_str}%",)
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
    Returns the standardized thumbnail path for a video if it exists, else None.
    """
    base, ext = os.path.splitext(video_path)
    thumb_path = base + ".thumb.jpg"
    return thumb_path if os.path.exists(thumb_path) else None

def get_image_thumbnail(image_path):
    """
    Returns the standardized thumbnail path for an image if it exists, else None.
    """
    base, ext = os.path.splitext(image_path)
    thumb_path = base + ".thumb.jpg"
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
    plate = request.args.get('plate', '').strip()
    date = request.args.get('date', '').strip()
    searched = bool(plate or date)
    if plate:
        events = get_events_by_plate(plate)
    elif date:
        events = get_events_by_date(date)
    else:
        events = []
    # Prepare thumbnails for videos and images, annotate media info
    for event in events:
        thumbs = []
        for media in event["media"]:
            cam_name, mtype = parse_media_info(media)
            if media.endswith(('.mp4', '.webm')):
                video_abs = os.path.join(IMAGE_DIR, media)
                thumb_abs = get_video_thumbnail(video_abs)
                thumb_rel = os.path.relpath(thumb_abs, IMAGE_DIR) if thumb_abs else None
                thumbs.append({
                    "media": media,
                    "thumb": thumb_rel,
                    "cam_name": cam_name,
                    "mtype": mtype
                })
            elif media.endswith(('.jpg', '.jpeg', '.png')):
                image_abs = os.path.join(IMAGE_DIR, media)
                thumb_abs = get_image_thumbnail(image_abs)
                thumb_rel = os.path.relpath(thumb_abs, IMAGE_DIR) if thumb_abs else None
                thumbs.append({
                    "media": media,
                    "thumb": thumb_rel,
                    "cam_name": cam_name,
                    "mtype": mtype
                })
            else:
                thumbs.append({
                    "media": media,
                    "thumb": None,
                    "cam_name": cam_name,
                    "mtype": mtype
                })
        event["media_with_thumbs"] = thumbs
    return render_template_string(
        HTML_TEMPLATE,
        plate=plate,
        date=date,
        events=events,
        searched=searched,
        session=session
    )

@app.route('/media/<path:path>')
@login_required()
def media_file(path):
    abs_path = os.path.join(IMAGE_DIR, path)
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8082, debug=True)

# OWASP Top 10 quick review for this app:
# 1. Injection: SQL queries use parameterized queries, so SQL injection is mitigated.
# 2. Broken Authentication: Passwords are hashed, sessions are used, and login is required for all sensitive routes.
# 3. Sensitive Data Exposure: Passwords are hashed, but ensure HTTPS is used in production to protect credentials in transit.
# 4. XML External Entities (XXE): Not applicable (no XML processing).
# 5. Broken Access Control: Role checks are enforced for admin-only routes (e.g., config, users).
# 6. Security Misconfiguration: Flask debug mode should be disabled in production. Ensure file permissions are correct.
# 7. Cross-Site Scripting (XSS): Jinja2 auto-escapes variables, but be careful with user-supplied HTML.
# 8. Insecure Deserialization: Not applicable (no pickle or similar).
# 9. Using Components with Known Vulnerabilities: Keep Flask and dependencies up to date.
# 10. Insufficient Logging & Monitoring: Logging is present, but review log coverage and retention.

# Recommendations:
# - Always run behind HTTPS in production.
# - Set secure session cookie flags (SESSION_COOKIE_SECURE, SESSION_COOKIE_HTTPONLY).
# - Limit file upload/serving to prevent path traversal.
# - Regularly update dependencies.
# - Consider rate limiting and account lockout for brute-force protection.
# - Review logging for sensitive data leaks.
