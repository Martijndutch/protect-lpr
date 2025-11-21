# File version: 1.1.0
# Version history:
# 1.1.0 - Add "Restart Protect Services" button and endpoint. (2024-06-09)
# 1.0.0 - Add version history and file version header. (2024-06-09)

from flask import Flask, render_template, request, redirect, url_for, flash, Blueprint, session, jsonify
import json
import os
from werkzeug.security import generate_password_hash, check_password_hash
import logging
import re
import subprocess
import sqlite3

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'protect-lpr-secret')

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

config_bp = Blueprint('config_bp', __name__, url_prefix='/config')

CONFIG_FILE = "config.json"
USERS_FILE = "users.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Config file '{CONFIG_FILE}' not found. Exiting.")
        import sys
        sys.exit(f"Config file '{CONFIG_FILE}' not found. Please create it before starting the application.")
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

def password_is_complex(pw):
    # At least 8 chars, 1 uppercase, 1 lowercase, 1 digit, 1 special char
    requirements = []
    if len(pw) < 8:
        requirements.append("minimaal 8 tekens")
    if not re.search(r'[A-Z]', pw):
        requirements.append("minimaal 1 hoofdletter")
    if not re.search(r'[a-z]', pw):
        requirements.append("minimaal 1 kleine letter")
    if not re.search(r'\d', pw):
        requirements.append("minimaal 1 cijfer")
    if not re.search(r'[^A-Za-z0-9]', pw):
        requirements.append("minimaal 1 speciaal teken (!@#$%^&* etc.)")
    return requirements

@config_bp.route('/', methods=['GET', 'POST'])
def config_page():
    config = load_config()
    # --- Event count for each ignored plate ---
    db_path = config.get('sqlite3_db_file', '/opt/protect-lpr/mysql/protect-lpr.db')
    ignored_plates = config.get('ignored_plates', [])
    # Support comments: ignored_plates can be list of dicts or list of strings
    plate_event_counts = {}
    plate_comments = {}
    normalized_plates = []
    for plate in ignored_plates:
        if isinstance(plate, dict):
            plate_value = plate.get("plate", "")
            comment = plate.get("comment", "")
        else:
            plate_value = plate
            comment = ""
        normalized_plates.append({"plate": plate_value, "comment": comment})
        plate_comments[plate_value] = comment
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        for plate_obj in normalized_plates:
            plate = plate_obj["plate"]
            c.execute("SELECT COUNT(*) FROM event WHERE license_plate = ?", (plate,))
            plate_event_counts[plate] = c.fetchone()[0]
        conn.close()
    except Exception:
        plate_event_counts = {plate_obj["plate"]: 0 for plate_obj in normalized_plates}
    # ---
    if request.method == 'POST':
        try:
            logger.debug(f"Received form data: {request.form}")
            config['paths']['log_dir'] = request.form.get('log_dir', config['paths'].get('log_dir', ''))
            config['paths']['image_dir'] = request.form.get('image_dir', config['paths'].get('image_dir', ''))
            config['sqlite3_db_file'] = request.form.get('sqlite3_db_file', config.get('sqlite3_db_file', ''))
            config['users_file'] = request.form.get('users_file', config.get('users_file', ''))
            # Ignored plates (support multiple values and comments)
            plates = request.form.getlist('ignored_plates[]')
            comments = request.form.getlist('ignored_plates_comment[]')
            config['ignored_plates'] = [
                {"plate": p.strip(), "comment": c.strip()}
                for p, c in zip(plates, comments)
                if p.strip()
            ]
            # Web server settings (only port)
            if 'web' not in config:
                config['web'] = {}
            config['web']['port'] = int(request.form.get('web_port', config['web'].get('port', 8082)))
            # Backup video and window settings
            config['backup_original_video'] = request.form.get('backup_original_video', 'false').lower() in ['true', '1', 'yes', 'on']
            config['video_window_start_seconds'] = int(request.form.get('video_window_start_seconds', config.get('video_window_start_seconds', -15)))
            config['video_window_end_seconds'] = int(request.form.get('video_window_end_seconds', config.get('video_window_end_seconds', 20)))
            save_config(config)
            flash("Configuratie succesvol opgeslagen.", "msg")
            return redirect(url_for('config_bp.config_page'))
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            flash(f"Fout bij opslaan: {e}", "err")
            config = load_config()
            return render_template('config.html', config=config, plate_event_counts=plate_event_counts, plate_comments=plate_comments)
    else:
        return render_template('config.html', config=config, plate_event_counts=plate_event_counts, plate_comments=plate_comments, normalized_plates=normalized_plates)



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
                pw_reqs = password_is_complex(password)
                if pw_reqs:
                    flash("Wachtwoord voldoet niet aan de vereisten: " + ", ".join(pw_reqs) + ".", "err")
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
        elif action == "resetpw":
            new_password = request.form.get('new_password', '')
            if not new_password:
                flash("Nieuw wachtwoord is verplicht.", "err")
            elif username not in users:
                flash("Gebruiker bestaat niet.", "err")
            else:
                pw_reqs = password_is_complex(new_password)
                if pw_reqs:
                    flash("Wachtwoord voldoet niet aan de vereisten: " + ", ".join(pw_reqs) + ".", "err")
                else:
                    users[username]['password'] = generate_password_hash(new_password)
                    save_users(users)
                    flash("Wachtwoord gereset voor gebruiker '%s'." % username, "msg")
    return render_template('users.html', users=users)

@config_bp.route('/event_count')
def event_count():
    plate = request.args.get('plate', '').strip()
    config = load_config()
    db_path = config.get('sqlite3_db_file', '/opt/protect-lpr/mysql/protect-lpr.db')
    count = 0
    if plate:
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM event WHERE license_plate = ?", (plate,))
            count = c.fetchone()[0]
            conn.close()
        except Exception:
            count = 0
    return jsonify({'count': count})

# Change route from '/config/auto_save' to '/auto_save'
@config_bp.route('/auto_save', methods=['POST'])
def auto_save_config():
    if session.get("role") != "admin":
        return jsonify({"success": False, "msg": "Geen toegang."}), 403
    data = request.get_json(force=True)
    # DEBUG: Print incoming data to check what is received from frontend
    print("AUTO_SAVE received data:", data)
    # --- PATCH: If ignored_plates_comment is missing or too short, re-collect from the DOM using request.form as fallback ---
    plates = data.get('ignored_plates', [])
    comments = data.get('ignored_plates_comment', [])
    # If comments is not a list or is too short, try to recover from request.form (for debugging)
    if not isinstance(comments, list) or len(comments) < len(plates):
        # Try to get from request.form (if available, e.g. fallback for non-AJAX)
        if hasattr(request, 'form') and request.form:
            comments = request.form.getlist('ignored_plates_comment[]')
            print("DEBUG fallback comments from request.form:", comments)
        # If still too short, pad with empty strings
        if not isinstance(comments, list):
            comments = []
        if len(comments) < len(plates):
            comments = comments + [""] * (len(plates) - len(comments))
        data['ignored_plates_comment'] = comments
        print("DEBUG comments after fallback/pad:", comments)
    try:
        config = load_config()
        # Update config fields from posted data
        config['paths']['log_dir'] = data.get('log_dir', config['paths'].get('log_dir', ''))
        config['paths']['image_dir'] = data.get('image_dir', config['paths'].get('image_dir', ''))
        config['sqlite3_db_file'] = data.get('sqlite3_db_file', config.get('sqlite3_db_file', ''))
        config['users_file'] = data.get('users_file', config.get('users_file', ''))
        # --- Handle ignored plates with comments ---
        plates = data.get('ignored_plates', [])
        comments = data.get('ignored_plates_comment', [])
        # If only plates (no comments), fallback to empty comments
        if isinstance(plates, list) and isinstance(comments, list) and len(comments) == len(plates):
            config['ignored_plates'] = [
                {"plate": p.strip(), "comment": c.strip()}
                for p, c in zip(plates, comments)
                if p.strip()
            ]
        else:
            # fallback: just plates, no comments
            config['ignored_plates'] = [
                {"plate": p.strip(), "comment": ""}
                for p in plates if p.strip()
            ]
        # Web server settings (only port)
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
        save_config(config)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

app.register_blueprint(config_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8083, debug=True)