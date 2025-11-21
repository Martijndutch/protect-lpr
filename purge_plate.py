"""
Purge Plate Endpoint for Protect LPR
- Exposes a Flask Blueprint with /config/purge_plate POST endpoint
- Removes all events and images for a given license plate from the database and disk
"""

import os
import json
import sqlite3
from flask import Blueprint, request, jsonify, current_app, render_template_string
import sys
from functools import wraps
from flask import session, redirect, url_for, flash

purge_bp = Blueprint('purge_bp', __name__)

# These should be set by the main app before registering the blueprint
DB_FILE = None
IMAGE_DIR = None

@purge_bp.record_once
def set_config(state):
    global DB_FILE, IMAGE_DIR
    app = state.app
    # Load config.json from the same directory as this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    config = {}
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
    except Exception as e:
        print(f"Could not load config.json: {e}", file=sys.stderr)
    # Prefer config.json for DB_FILE, fallback to app config/env
    DB_FILE = config.get("sqlite3_db_file") or getattr(app, 'DB_FILE', None) or app.config.get('DB_FILE')
    IMAGE_DIR = config.get("paths", {}).get("image_dir") or getattr(app, 'IMAGE_DIR', None) or app.config.get('IMAGE_DIR')
    if not DB_FILE or not IMAGE_DIR:
        raise RuntimeError("DB_FILE and IMAGE_DIR must be set on the Flask app or in config.json before registering purge_bp")

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "role" not in session or session.get("role") != "admin":
            flash("Geen toegang.", "err")
            return redirect(url_for('config_bp.config_page'))
        return f(*args, **kwargs)
    return decorated_function

@purge_bp.route('/purge_plate', methods=['GET', 'POST'])
@purge_bp.route('/purge_plate/<plate>', methods=['GET', 'POST'])
@admin_required
def purge_plate(plate=None):
    import logging
    logging.debug(f"purge_plate endpoint using DB_FILE: {DB_FILE}")
    base_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Purge Plate - Protect LPR</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f7f7f7; }
            .container { max-width: 900px; margin: 40px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 32px; }
            h1 { text-align: center; color: #2c3e50; }
            form { margin-top: 24px; }
            label { display: block; margin-top: 16px; font-weight: bold; }
            input[type="text"], input[type="number"] { width: 100%; padding: 8px; border-radius: 4px; border: 1px solid #ccc; margin-top: 4px; }
            input[type="submit"], button { margin-top: 16px; padding: 8px 16px; border-radius: 4px; border: none; background: #2c3e50; color: #fff; cursor: pointer; }
            .msg { color: green; text-align: center; }
            .err { color: red; text-align: center; }
            a { color: #2c3e50; text-decoration: underline; }
            .section { margin-bottom: 32px; }
            .center { text-align: center; }
            @media (max-width: 700px) {
                .container { max-width: 98vw; margin: 10px; padding: 8vw 2vw; }
                h1 { font-size: 1.3em; }
                input[type="text"], input[type="number"] { font-size: 1em; }
                input[type="submit"], button { font-size: 1em; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div style="text-align:right;"><a href="{{ url_for('config_bp.config_page') }}">Terug naar configuratie</a></div>
            <h1>Kenteken wissen</h1>
            {{ content|safe }}
        </div>
    </body>
    </html>
    """
    form_html = """
    <form method="post">
        <label for="plate">License plate:</label>
        <input type="text" id="plate" name="plate" required>
        <input type="submit" value="Check">
    </form>
    """
    confirm_html = """
    <form method="post">
        <input type="hidden" name="plate" value="{{ plate }}">
        <input type="hidden" name="confirm" value="yes">
        <p style="color:red;">You're purging {{ n_events }} records and {{ n_files }} files for plate <b>{{ plate }}</b>. Are you sure?</p>
        <input type="submit" value="Yes, purge">
        <a href="/config/purge_plate">Cancel</a>
    </form>
    """

    if request.method == 'GET':
        # If plate is provided in URL, pre-fill the form
        if plate:
            return render_template_string(base_html, content=form_html + f"<script>document.getElementById('plate').value='{plate}';</script>")
        return render_template_string(base_html, content=form_html)

    # POST
    plate = ''
    confirm = ''
    # Debug: log all incoming POST data
    logging.debug(f"request.form: {dict(request.form)}")
    logging.debug(f"request.is_json: {request.is_json}")
    if request.is_json:
        try:
            data = request.get_json(force=True)
            logging.debug(f"request.get_json(): {data}")
        except Exception as e:
            logging.debug(f"Error parsing JSON: {e}")
            data = {}
        plate = (data.get('plate') or '').strip()
        confirm = data.get('confirm', '')
    elif request.form:
        plate = (request.form.get('plate') or '').strip()
        confirm = request.form.get('confirm', '')
    else:
        plate = ''
        confirm = ''
    logging.debug(f"Extracted plate: '{plate}', confirm: '{confirm}'")

    if not plate:
        if request.is_json:
            return jsonify({'success': False, 'msg': 'Geen kenteken opgegeven.'}), 400
        return render_template_string(base_html, content=form_html + "<p class='err'>Geen kenteken opgegeven.</p>")

    norm_plate = plate.replace('-', '').replace(' ', '').lower()
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        # Debug: check if 'event' table exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='event'")
        table_exists = c.fetchone()
        if not table_exists:
            error_msg = (
                "Database table 'event' does not exist. "
                "Please initialize your database. "
                "You can create it with the following SQL:<br>"
                "<pre>CREATE TABLE event ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "datetime TEXT, "
                "license_plate TEXT, "
                "media_urls TEXT"
                ");</pre>"
            )
            import logging
            logging.error(error_msg)
            if request.is_json:
                return jsonify({'success': False, 'msg': "Database table 'event' does not exist. Please initialize your database."}), 500
            return render_template_string(
                base_html.format(content=form_html + f"<p class='err'>{error_msg}</p><a href='/config/purge_plate'>Back</a>")
            )
        c.execute("SELECT id, media_urls FROM event WHERE replace(replace(lower(license_plate), '-', ''), ' ', '') = ?", (norm_plate,))
        rows = c.fetchall()
        event_ids = [row[0] for row in rows]
        media_files = []
        for row in rows:
            try:
                media_files += json.loads(row[1])
            except Exception:
                continue
        n_events = len(event_ids)
        n_files = len(media_files)

        # --- Check for license plate folder on disk ---
        license_dir = os.path.join(IMAGE_DIR, plate)
        folder_exists = os.path.isdir(license_dir)
        folder_file_count = 0
        if folder_exists:
            folder_file_count = sum(len(files) for _, _, files in os.walk(license_dir))

        # When showing confirmation, include folder info
        if not confirm:
            # Show warning and ask for confirmation
            if request.is_json:
                return jsonify({
                    'success': False,
                    'msg': f"You're purging {n_events} records and {n_files} files for plate {plate}. "
                           f"Folder exists: {folder_exists}, files in folder: {folder_file_count}. "
                           "Set confirm=yes to proceed.",
                    'n_events': n_events,
                    'n_files': n_files,
                    'folder_exists': folder_exists,
                    'folder_file_count': folder_file_count
                }), 400
            folder_info = ""
            if folder_exists:
                folder_info = f"<p style='color:#888;'>Let op: er zijn {folder_file_count} bestanden in de map <b>{plate}</b> op schijf.</p>"
            return render_template_string(
                base_html,
                content=render_template_string(confirm_html, plate=plate, n_events=n_events, n_files=n_files) + folder_info
            )
        # Purge confirmed
        if event_ids:
            c.execute(f"DELETE FROM event WHERE id IN ({','.join(['?']*len(event_ids))})", event_ids)
            conn.commit()
        conn.close()
        deleted_files = []
        for mf in media_files:
            abs_path = os.path.join(IMAGE_DIR, mf)
            # Remove the file and all files with the same base name but different extensions (e.g., .mp4, .jpg, .thumb.jpg, .original.mp4)
            base, _ = os.path.splitext(abs_path)
            # Remove main file
            if os.path.isfile(abs_path):
                try:
                    os.remove(abs_path)
                    deleted_files.append(os.path.relpath(abs_path, IMAGE_DIR))
                except Exception:
                    pass
            # Remove .thumb.jpg
            thumb_path = base + '.thumb.jpg'
            if os.path.isfile(thumb_path):
                try:
                    os.remove(thumb_path)
                    deleted_files.append(os.path.relpath(thumb_path, IMAGE_DIR))
                except Exception:
                    pass
            # Remove .original.mp4
            orig_mp4 = base + '.original.mp4'
            if os.path.isfile(orig_mp4):
                try:
                    os.remove(orig_mp4)
                    deleted_files.append(os.path.relpath(orig_mp4, IMAGE_DIR))
                except Exception:
                    pass
            # Remove .center.jpg
            center_jpg = base + '_center.jpg'
            if os.path.isfile(center_jpg):
                try:
                    os.remove(center_jpg)
                    deleted_files.append(os.path.relpath(center_jpg, IMAGE_DIR))
                except Exception:
                    pass

        # --- Delete license plate folder if it exists ---
        folder_deleted = False
        if folder_exists:
            try:
                import shutil
                shutil.rmtree(license_dir)
                folder_deleted = True
            except Exception:
                folder_deleted = False

        if request.is_json:
            return jsonify({
                'success': True,
                'deleted_events': n_events,
                'deleted_files': deleted_files,
                'folder_deleted': folder_deleted
            })
        folder_msg = ""
        if folder_deleted:
            folder_msg = f"<p class='msg'>Map <b>{plate}</b> is verwijderd van schijf.</p>"
        elif folder_exists:
            folder_msg = f"<p class='err'>Map <b>{plate}</b> kon niet worden verwijderd.</p>"
        return render_template_string(
            base_html,
            content=f"<p class='msg'>Purge complete: {n_events} records and {len(deleted_files)} files deleted for plate <b>{plate}</b>.</p>{folder_msg}",
            n_events=n_events, n_files=len(deleted_files), plate=plate
        )
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'msg': str(e)}), 500
        # Show error and link back to config page, same formatting
        return render_template_string(
            base_html, content=form_html + f"<p class='err'>Error: {str(e)}</p>"
        )

if __name__ == "__main__":
    from flask import Flask

    app = Flask(__name__)

    # Set DB_FILE and IMAGE_DIR from environment or use defaults
    db_file = os.environ.get("DB_FILE", "protect-lpr.db")
    image_dir = os.environ.get("IMAGE_DIR", "./images")

    app.config["DB_FILE"] = db_file
    app.config["IMAGE_DIR"] = image_dir

    app.register_blueprint(purge_bp)

    # Optionally, set debug and port from env
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", 8084))

    print(f"Running purge_plate endpoint on http://0.0.0.0:{port}/config/purge_plate")
    app.run(debug=debug, port=port, host="0.0.0.0")
