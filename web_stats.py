from flask import Blueprint, render_template_string, current_app
import sqlite3
import os
import json
from datetime import datetime
from collections import defaultdict, Counter
from flask import send_file, request, Response
import io
import csv
import configparser

stats_bp = Blueprint('stats_bp', __name__, url_prefix='/stats')

def get_stats(db_file):
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    # Get all events
    c.execute("SELECT datetime, license_plate, media_urls FROM event")
    rows = c.fetchall()
    conn.close()

    today = datetime.now().strftime("%Y-%m-%d")
    week = datetime.now().isocalendar()[1]
    month = datetime.now().strftime("%Y-%m")
    licenses_day = set()
    licenses_week = set()
    licenses_month = set()
    files_day = 0
    files_week = 0
    files_month = 0

    # For graphs
    from collections import defaultdict
    unique_licenses_per_day = defaultdict(set)
    files_per_day = {}

    for dt, lp, media_json in rows:
        # Parse date
        date_part = dt.split("_")[0] if "_" in dt else dt.split(" ")[0]
        week_part = datetime.strptime(date_part, "%Y-%m-%d").isocalendar()[1] if len(date_part) == 10 else None
        month_part = date_part[:7]
        try:
            media = json.loads(media_json)
        except Exception:
            media = []
        # Unique licenses
        if date_part == today:
            licenses_day.add(lp)
        if week_part == week:
            licenses_week.add(lp)
        if month_part == month:
            licenses_month.add(lp)
        # Files
        if date_part == today:
            files_day += len(media)
        if week_part == week:
            files_week += len(media)
        if month_part == month:
            files_month += len(media)
        # For graphs
        unique_licenses_per_day[date_part].add(lp)
        files_per_day[date_part] = files_per_day.get(date_part, 0) + len(media)

    # For graphs: convert set counts to int
    unique_licenses_per_day = {k: len(v) for k, v in unique_licenses_per_day.items()}
    # Fill missing days for last 30 days
    from datetime import timedelta
    days = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    unique_licenses_per_day = {d: unique_licenses_per_day.get(d, 0) for d in days}
    files_per_day = {d: files_per_day.get(d, 0) for d in days}

    return {
        "unique_licenses_day": len(licenses_day),
        "unique_licenses_week": len(licenses_week),
        "unique_licenses_month": len(licenses_month),
        "files_day": files_day,
        "files_week": files_week,
        "files_month": files_month,
        "unique_licenses_per_day": unique_licenses_per_day,
        "files_per_day": files_per_day,
    }

def get_events_grouped_by_plate_and_time(db_file, start_date, end_date):
    """
    Returns a list of events grouped by license plate and event datetime
    for events between start_date and end_date (inclusive).
    Each event: {'license_plate': ..., 'date': ..., 'time': ...}
    """
    conn = sqlite3.connect(db_file)
    c = conn.cursor()
    # Fix: Use >= start_date 00:00:00 and < (end_date + 1) 00:00:00 for correct range
    from datetime import datetime, timedelta
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        start_str = start_dt.strftime("%Y-%m-%d 00:00:00")
        end_str = end_dt.strftime("%Y-%m-%d 00:00:00")
    except Exception:
        # fallback to original logic if parsing fails
        start_str = start_date + " 00:00:00"
        end_str = end_date + " 23:59:59"
    c.execute(
        "SELECT datetime, license_plate FROM event WHERE datetime >= ? AND datetime < ? ORDER BY datetime DESC",
        (start_str, end_str)
    )
    rows = c.fetchall()
    conn.close()
    seen = set()
    grouped = []
    for dt, lp in rows:
        key = (lp, dt)
        if key not in seen:
            seen.add(key)
            # Try to parse dt as "%Y-%m-%d_%H-%M-%S" or "%Y-%m-%d %H:%M:%S"
            date_part, time_part = "", ""
            for fmt in ("%Y-%m-%d_%H-%M-%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt_obj = datetime.strptime(dt, fmt)
                    date_part = dt_obj.strftime("%Y-%m-%d")
                    time_part = dt_obj.strftime("%H:%M:%S")
                    break
                except Exception:
                    continue
            if not date_part:
                # fallback: try to split manually
                if "_" in dt:
                    parts = dt.split("_")
                    if len(parts) >= 2:
                        date_part = parts[0]
                        time_part = parts[1].replace("-", ":")
                elif " " in dt:
                    parts = dt.split(" ")
                    if len(parts) >= 2:
                        date_part = parts[0]
                        time_part = parts[1]
            grouped.append({
                "license_plate": lp,
                "date": date_part,
                "time": time_part
            })
    return grouped

def get_disk_and_folder_stats(images_dir):
    """
    Returns a dict with:
      - used_space_bytes
      - free_space_bytes
      - total_space_bytes
      - unique_folders_count
    """
    # Get disk usage
    statvfs = os.statvfs(images_dir)
    total_space = statvfs.f_frsize * statvfs.f_blocks
    free_space = statvfs.f_frsize * statvfs.f_bavail
    used_space = total_space - free_space

    # Count unique folders (only directories, not files)
    unique_folders = set()
    for root, dirs, files in os.walk(images_dir):
        # Only count immediate subfolders of images_dir
        if root == images_dir:
            for d in dirs:
                unique_folders.add(d)
            break
    return {
        "used_space_bytes": used_space,
        "free_space_bytes": free_space,
        "total_space_bytes": total_space,
        "unique_folders_count": len(unique_folders)
    }

def load_config():
    """
    Loads config.json using the path from current_app.config['CONFIG_PATH'].
    Returns the config dict, or {} if not found.
    """
    config_path = current_app.config.get("CONFIG_PATH")
    if not config_path or not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def get_free_space_history():
    """
    Reads sizes.csv (path from config) and returns:
      - dates: list of date strings
      - free_pct: list of free space percentages (float)
    """
    config = load_config()
    sizes_path = config.get("paths", {}).get("sizes")
    if not sizes_path or not os.path.exists(sizes_path):
        return [], []

    dates = []
    free_pct = []
    try:
        with open(sizes_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Expect columns: Timestamp, Directory Size (Bytes), Free Space (Bytes), Free Space (%)
                try:
                    date = row.get("Timestamp")
                    pct_str = row.get("Free Space (%)", "").strip()
                    if pct_str.endswith("%"):
                        pct_str = pct_str[:-1]
                    pct = float(pct_str) if pct_str else None
                    if date and pct is not None:
                        dates.append(date)
                        free_pct.append(pct)
                except Exception:
                    continue
    except Exception:
        return [], []
    return dates, free_pct

def get_used_space_history_and_estimate():
    """
    Reads sizes.csv (path from config) and returns:
      - dates: list of date strings (full range, sorted)
      - used_pct: list of used space percentages (float, aligned with dates)
      - days_left_estimate: int or None
    """
    #config = load_config()
    
    sizes_path = current_app.config.get("SIZES")
    if not sizes_path or not os.path.exists(sizes_path):
        return [], [], None

    date_used_map = {}
    try:
        with open(sizes_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    date = row.get("Timestamp")
                    pct_str = row.get("Free Space (%)", "").strip()
                    if pct_str.endswith("%"):
                        pct_str = pct_str[:-1]
                    free_pct = float(pct_str) if pct_str else None
                    if date and free_pct is not None:
                        used = 100.0 - free_pct
                        date_used_map[date] = used
                except Exception:
                    continue
    except Exception:
        return [], [], None

    sorted_dates = sorted(date_used_map.keys())
    used_pct = [date_used_map[d] for d in sorted_dates]

    days_left_estimate = None
    if len(sorted_dates) >= 2:
        n = min(14, len(sorted_dates))
        x = list(range(n))
        y = used_pct[-n:]
        xm = sum(x) / n
        ym = sum(y) / n
        denom = sum((xi - xm) ** 2 for xi in x)
        if denom > 0:
            slope = sum((xi - xm) * (yi - ym) for xi, yi in zip(x, y)) / denom
            current_used = y[-1]
            if slope > 0:
                days_left_estimate = int((100.0 - current_used) / slope)
            else:
                days_left_estimate = None
    return sorted_dates, used_pct, days_left_estimate

@stats_bp.route("/", endpoint="stats_page")
def stats_page():
    db_file = current_app.config.get("DB_FILE") or "/var/lib/protect-lpr/mysql/protect-lpr.db"
    images_dir = current_app.config.get("IMAGE_DIR")
    if not images_dir:
        images_dir = "/var/lib/protect-lpr/images"
    stats = get_stats(db_file)
    disk_folder_stats = get_disk_and_folder_stats(images_dir)
    stats.update(disk_folder_stats)
    # Add GB values for disk stats
    stats['used_space_gb'] = round(stats['used_space_bytes'] / (1024*1024*1024), 2)
    stats['free_space_gb'] = round(stats['free_space_bytes'] / (1024*1024*1024), 2)
    stats['total_space_gb'] = round(stats['total_space_bytes'] / (1024*1024*1024), 2)
    # Add percentage used
    if stats['total_space_bytes'] > 0:
        stats['used_space_pct'] = round(100 * stats['used_space_bytes'] / stats['total_space_bytes'], 1)
    else:
        stats['used_space_pct'] = 0.0

    # Only get used space history and estimate for graph
    used_space_dates, used_space_pct, days_left_estimate = get_used_space_history_and_estimate()
    stats['used_space_dates'] = used_space_dates
    stats['used_space_pct_history'] = used_space_pct
    stats['days_left_estimate'] = days_left_estimate

    return render_template_string(STATS_TEMPLATE, stats=stats)

@stats_bp.route("/download_events")
def download_events():
    db_file = current_app.config.get("DB_FILE") or "/var/lib/protect-lpr/mysql/protect-lpr.db"
    # Parse date range from query params
    from datetime import datetime, timedelta
    today = datetime.now().strftime("%Y-%m-%d")
    period = request.args.get("period", "today")
    start_date = end_date = today

    if period == "today":
        start_date = end_date = today
    elif period == "week":
        start = datetime.now() - timedelta(days=datetime.now().weekday())
        end = start + timedelta(days=6)
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")
    elif period == "month":
        start = datetime.now().replace(day=1)
        end = datetime.now()
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")
    elif period == "ytd":
        start = datetime.now().replace(month=1, day=1)
        end = datetime.now()
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")
    elif period == "custom":
        start_date = request.args.get("start", today)
        end_date = request.args.get("end", today)
    else:
        start_date = end_date = today

    events = get_events_grouped_by_plate_and_time(db_file, start_date, end_date)

    # Prepare CSV with ; as separator, columns: license_plate;date;time
    import io
    import csv
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["license_plate", "date", "time"])
    for event in events:
        writer.writerow([
            event["license_plate"],
            event["date"],
            event["time"]
        ])
    output.seek(0)
    filename = f"events_{start_date}_to_{end_date}.csv"
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

STATS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Protect LPR - Statistieken</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f7f7f7; }
        .container { max-width: 900px; margin: 40px auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 32px; }
        h1 { text-align: center; color: #2c3e50; }
        .section { margin-bottom: 32px; }
        .center { text-align: center; }
        canvas { max-width: 100%; height: auto; }
        @media (max-width: 700px) {
            .container { max-width: 98vw; margin: 10px; padding: 8vw 2vw; }
            h1 { font-size: 1.3em; }
        }
        table { width: 100%; border-collapse: collapse; margin-top: 18px; }
        th, td { border: 1px solid #ccc; padding: 6px 8px; text-align: left; }
        th { background: #f0f0f0; }
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="container">
        <div style="text-align:right;">
            <a href="/">Terug naar overzicht</a>
        </div>
        <h1>Protect LPR Statistieken</h1>
        <div class="section">
            <h2>Opslag & Mappen</h2>
            <table>
                <tr><th>Vrije schijfruimte</th><td>{{ stats['used_space_gb'] }} GB ({{ stats['used_space_pct'] }}%)</td></tr>
                <tr><th>Beschikbare schijfruimte</th><td>{{ stats['free_space_gb'] }} GB</td></tr>
                <tr><th>Totaal schijfruimte</th><td>{{ stats['total_space_gb'] }} GB</td></tr>
                <tr><th>Unieke mappen in images</th><td>{{ stats['unique_folders_count'] }}</td></tr>
            </table>
        </div>
        <div class="section">
            <form method="get" action="{{ url_for('stats_bp.download_events') }}" style="margin-bottom:18px;">
                <label>Download events:</label>
                <select name="period" id="period" onchange="onPeriodChange()">
                    <option value="today">Vandaag</option>
                    <option value="week">Deze week</option>
                    <option value="month">Deze maand</option>
                    <option value="ytd">Jaar tot nu</option>
                    <option value="custom">Aangepast bereik</option>
                </select>
                <span id="custom-range" style="display:none;">
                    Van: <input type="date" name="start">
                    Tot: <input type="date" name="end">
                </span>
                <input type="submit" value="Download CSV">
            </form>
            <h2>Unieke kentekens</h2>
            <canvas id="uniqueLicensesChart"></canvas>
            <table>
                <tr><th>Periode</th><th>Unieke kentekens</th></tr>
                <tr><td>Vandaag</td><td>{{ stats['unique_licenses_day'] }}</td></tr>
                <tr><td>Deze week</td><td>{{ stats['unique_licenses_week'] }}</td></tr>
                <tr><td>Deze maand</td><td>{{ stats['unique_licenses_month'] }}</td></tr>
            </table>
        </div>
        <div class="section">
            <h2>Bestanden opgeslagen</h2>
            <canvas id="filesChart"></canvas>
            <table>
                <tr><th>Periode</th><th>Bestanden</th></tr>
                <tr><td>Vandaag</td><td>{{ stats['files_day'] }}</td></tr>
                <tr><td>Deze week</td><td>{{ stats['files_week'] }}</td></tr>
                <tr><td>Deze maand</td><td>{{ stats['files_month'] }}</td></tr>
            </table>
        </div>
        <div class="section">
            <h2>Vrije schijfruimte (%) historie</h2>
            <canvas id="usedSpaceChart"></canvas>
            {% if stats['days_left_estimate'] is not none %}
                <div style="margin-top:10px;color:#c0392b;font-weight:bold;">
                    Geschatte resterende dagen tot schijf vol: {{ stats['days_left_estimate'] }}
                </div>
            {% endif %}
        </div>
    </div>
    <script>
        function onPeriodChange() {
            var sel = document.getElementById('period');
            var custom = document.getElementById('custom-range');
            if (sel.value === 'custom') {
                custom.style.display = '';
            } else {
                custom.style.display = 'none';
            }
        }
        // Unique licenses per day for last 30 days
        const uniqueLicensesData = {{ stats['unique_licenses_per_day']|tojson }};
        const filesPerDayData = {{ stats['files_per_day']|tojson }};
        const days = Object.keys(uniqueLicensesData);
        const uniqueLicenses = Object.values(uniqueLicensesData);
        const filesPerDay = Object.values(filesPerDayData);

        new Chart(document.getElementById('uniqueLicensesChart'), {
            type: 'bar',
            data: {
                labels: days,
                datasets: [{
                    label: 'Unieke kentekens per dag',
                    data: uniqueLicenses,
                    backgroundColor: 'rgba(44, 62, 80, 0.7)'
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { x: { ticks: { maxTicksLimit: 10 } } }
            }
        });

        new Chart(document.getElementById('filesChart'), {
            type: 'bar',
            data: {
                labels: days,
                datasets: [{
                    label: 'Bestanden per dag',
                    data: filesPerDay,
                    backgroundColor: 'rgba(39, 174, 96, 0.7)'
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { x: { ticks: { maxTicksLimit: 10 } } }
            }
        });

        // Used disk space % history
        const usedSpaceDates = {{ stats['used_space_dates']|tojson }};
        const usedSpacePct = {{ stats['used_space_pct_history']|tojson }};
        if (usedSpaceDates.length > 0) {
            new Chart(document.getElementById('usedSpaceChart'), {
                type: 'line',
                data: {
                    labels: usedSpaceDates,
                    datasets: [{
                        label: 'Vrije schijfruimte (%)',
                        data: usedSpacePct,
                        fill: false,
                        borderColor: 'rgba(192, 57, 43, 0.8)',
                        backgroundColor: 'rgba(192, 57, 43, 0.3)',
                        tension: 0.2
                    }]
                },
                options: {
                    responsive: true,
                    plugins: { legend: { display: true } },
                    scales: {
                        x: { ticks: { maxTicksLimit: 10 } },
                        y: { min: 0, max: 100, title: { display: true, text: '%' } }
                    }
                }
            });
        }
    </script>
</body>
</html>
"""
