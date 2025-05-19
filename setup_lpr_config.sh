#!/bin/bash

# Setup script for LPR Configuration Web App
# Run as: sudo ./setup_lpr_config.sh
# User: martijn, Hostname: docker, Base dir: /opt/protect-lpr

set -e

# Configuration variables
BASE_DIR="/opt/protect-lpr"
APP_DIR="$BASE_DIR/web_config"
VENV_DIR="$APP_DIR/venv"
STATIC_DIR="$APP_DIR/static"
TEMPLATES_DIR="$APP_DIR/templates"
LOG_DIR="/var/log/protect-lpr"
CONFIG_FILE="$BASE_DIR/config.json"
NGINX_CONFIG="/etc/nginx/sites-available/lpr_config"
SYSTEMD_SERVICE="/etc/systemd/system/lpr_config.service"
USER="martijn"
GROUP="www-data"
FLASK_PORT="5000"
NGINX_PORT="8080"

# Function to print status
print_status() {
    echo -e "\033[1;32m[INFO]\033[0m $1"
}

# Function to print error and exit
print_error() {
    echo -e "\033[1;31m[ERROR]\033[0m $1"
    exit 1
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    print_error "This script must be run as root (use sudo)"
fi

# Step 1: Check and install dependencies
print_status "Checking and installing dependencies..."

# Update package lists
apt-get update

# Check Python version (need 3.8+)
if ! command -v python3 &> /dev/null || ! python3 --version | grep -q "3.[8-9]\|3.1[0-9]"; then
    print_status "Installing Python 3..."
    apt-get install -y python3 python3-pip python3-venv || print_error "Failed to install Python 3"
fi
PYTHON_VERSION=$(python3 --version)
print_status "Python version: $PYTHON_VERSION"

# Check pip
if ! command -v pip3 &> /dev/null; then
    print_status "Installing pip..."
    apt-get install -y python3-pip || print_error "Failed to install pip"
fi
PIP_VERSION=$(pip3 --version)
print_status "pip version: $PIP_VERSION"

# Check Nginx
if ! command -v nginx &> /dev/null; then
    print_status "Installing Nginx..."
    apt-get install -y nginx || print_error "Failed to install Nginx"
fi
NGINX_VERSION=$(nginx -v 2>&1)
print_status "Nginx version: $NGINX_VERSION"

# Check Git (optional, for future use)
if ! command -v git &> /dev/null; then
    print_status "Installing Git..."
    apt-get install -y git || print_error "Failed to install Git"
fi
GIT_VERSION=$(git --version)
print_status "Git version: $GIT_VERSION"

# Step 2: Create directories
print_status "Creating directories..."
mkdir -p "$APP_DIR" "$STATIC_DIR/css" "$STATIC_DIR/js" "$TEMPLATES_DIR" "$LOG_DIR"
chown -R "$USER:$GROUP" "$BASE_DIR" "$LOG_DIR"
chmod -R 775 "$BASE_DIR" "$LOG_DIR"

# Step 3: Set up virtual environment
print_status "Setting up Python virtual environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR" || print_error "Failed to create virtual environment"
fi
source "$VENV_DIR/bin/activate"

# Install Flask and Gunicorn in virtual environment
print_status "Installing Flask and Gunicorn..."
pip install flask gunicorn || print_error "Failed to install Flask or Gunicorn"
FLASK_VERSION=$(pip show flask | grep Version | awk '{print $2}')
GUNICORN_VERSION=$(pip show gunicorn | grep Version | awk '{print $2}')
print_status "Flask version: $FLASK_VERSION"
print_status "Gunicorn version: $GUNICORN_VERSION"
deactivate

# Step 4: Create application files
print_status "Creating application files..."

# Create app.py
cat > "$APP_DIR/app.py" << 'EOF'
from flask import Flask, jsonify, request, render_template
import json
import os
import logging

app = Flask(__name__)

CONFIG_FILE = "/opt/protect-lpr/config.json"
LOG_FILE = "/var/log/protect-lpr/web_config.log"

# Configure logging
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def read_config():
    """Read the config.json file."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        return config
    except Exception as e:
        logger.error(f"Failed to read config: {str(e)}")
        raise

def write_config(config):
    """Write the config.json file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info("Config updated successfully")
    except Exception as e:
        logger.error(f"Failed to write config: {str(e)}")
        raise

@app.route('/')
def index():
    """Render the main configuration page."""
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get the current configuration."""
    try:
        config = read_config()
        return jsonify({
            "status": "success",
            "config": {
                "rtsp_streams": config.get("rtsp_streams", {}),
                "ignored_plates": config.get("ignored_plates", [])
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/api/config', methods=['POST'])
def update_config():
    """Update the configuration."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "error": "No data provided"}), 400

        config = read_config()
        config["rtsp_streams"] = data.get("rtsp_streams", config.get("rtsp_streams", {}))
        config["ignored_plates"] = data.get("ignored_plates", config.get("ignored_plates", []))
        write_config(config)
        return jsonify({"status": "success", "message": "Configuration updated"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
EOF

# Create templates/index.html
cat > "$TEMPLATES_DIR/index.html" << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LPR Configuration</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="/static/css/styles.css">
</head>
<body class="bg-gray-100">
    <div class="container mx-auto p-4">
        <h1 class="text-3xl font-bold mb-4">LPR Configuration</h1>
        
        <!-- RTSP Streams Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-2">RTSP Streams</h2>
            <table id="streams-table" class="w-full border-collapse bg-white shadow-md">
                <thead>
                    <tr class="bg-gray-200">
                        <th class="border p-2">Device ID</th>
                        <th class="border p-2">Name</th>
                        <th class="border p-2">URL</th>
                        <th class="border p-2">Initial Delay (ms)</th>
                        <th class="border p-2">Num Images</th>
                        <th class="border p-2">Interval (ms)</th>
                        <th class="border p-2">Video Duration (s)</th>
                        <th class="border p-2">Actions</th>
                    </tr>
                </thead>
                <tbody></tbody>
            </table>
            <button id="add-stream-btn" class="mt-4 bg-blue-500 text-white px-4 py-2 rounded">Add Stream</button>
        </div>

        <!-- Ignored Plates Section -->
        <div class="mb-8">
            <h2 class="text-2xl font-semibold mb-2">Ignored Plates</h2>
            <ul id="plates-list" class="bg-white shadow-md p-4"></ul>
            <div class="mt-4 flex">
                <input id="new-plate" type="text" class="border p-2 flex-grow" placeholder="Enter license plate">
                <button id="add-plate-btn" class="bg-blue-500 text-white px-4 py-2 ml-2">Add Plate</button>
            </div>
        </div>

        <!-- Save Button -->
        <button id="save-btn" class="bg-green-500 text-white px-4 py-2 rounded">Save Changes</button>
        <p id="status-message" class="mt-2 text-red-500 hidden"></p>
    </div>

    <!-- Stream Form Modal -->
    <div id="stream-modal" class="fixed inset-0 bg-gray-600 bg-opacity-50 hidden flex items-center justify-center">
        <div class="bg-white p-6 rounded shadow-lg w-full max-w-lg">
            <h3 class="text-xl font-semibold mb-4">Add/Edit Stream</h3>
            <form id="stream-form">
                <input type="hidden" id="edit-device-id" name="edit_device_id">
                <input type="hidden" id="edit-stream-index" name="edit_stream_index">
                <div class="mb-4">
                    <label class="block">Device ID</label>
                    <input type="text" id="device-id" name="device_id" class="w-full border p-2" required>
                </div>
                <div class="mb-4">
                    <label class="block">Name</label>
                    <input type="text" id="name" name="name" class="w-full border p-2" required>
                </div>
                <div class="mb-4">
                    <label class="block">URL</label>
                    <input type="text" id="url" name="url" class="w-full border p-2" required>
                </div>
                <div class="mb-4">
                    <label class="block">Initial Delay (ms)</label>
                    <input type="number" id="initial_delay_ms" name="initial_delay_ms" class="w-full border p-2" required>
                </div>
                <div class="mb-4">
                    <label class="block">Number of Images</label>
                    <input type="number" id="num_images" name="num_images" class="w-full border p-2" required>
                </div>
                <div class="mb-4">
                    <label class="block">Interval (ms)</label>
                    <input type="number" id="interval_ms" name="interval_ms" class="w-full border p-2" required>
                </div>
                <div class="mb-4">
                    <label class="block">Video Duration (s)</label>
                    <input type="number" id="video_duration_s" name="video_duration_s" class="w-full border p-2" required>
                </div>
                <div class="flex justify-end">
                    <button type="button" id="cancel-stream-btn" class="bg-gray-500 text-white px-4 py-2 mr-2">Cancel</button>
                    <button type="submit" class="bg-blue-500 text-white px-4 py-2">Save</button>
                </div>
            </form>
        </div>
    </div>

    <script src="/static/js/script.js"></script>
</body>
</html>
EOF

# Create static/js/script.js
cat > "$STATIC_DIR/js/script.js" << 'EOF'
document.addEventListener('DOMContentLoaded', () => {
    const streamsTable = document.querySelector('#streams-table tbody');
    const platesList = document.querySelector('#plates-list');
    const addStreamBtn = document.querySelector('#add-stream-btn');
    const addPlateBtn = document.querySelector('#add-plate-btn');
    const newPlateInput = document.querySelector('#new-plate');
    const saveBtn = document.querySelector('#save-btn');
    const statusMessage = document.querySelector('#status-message');
    const streamModal = document.querySelector('#stream-modal');
    const streamForm = document.querySelector('#stream-form');
    const cancelStreamBtn = document.querySelector('#cancel-stream-btn');

    let config = { rtsp_streams: {}, ignored_plates: [] };

    // Fetch initial config
    fetchConfig();

    function fetchConfig() {
        fetch('/api/config')
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    config = data.config;
                    renderStreams();
                    renderPlates();
                } else {
                    showStatus('Failed to load configuration: ' + data.error);
                }
            })
            .catch(error => showStatus('Error: ' + error.message));
    }

    function renderStreams() {
        streamsTable.innerHTML = '';
        for (const deviceId in config.rtsp_streams) {
            config.rtsp_streams[deviceId].forEach((stream, index) => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="border p-2">${deviceId}</td>
                    <td class="border p-2">${stream.name}</td>
                    <td class="border p-2">${stream.url}</td>
                    <td class="border p-2">${stream.initial_delay_ms}</td>
                    <td class="border p-2">${stream.num_images}</td>
                    <td class="border p-2">${stream.interval_ms}</td>
                    <td class="border p-2">${stream.video_duration_s}</td>
                    <td class="border p-2">
                        <button class="edit-btn bg-yellow-500 text-white px-2 py-1 mr-2" data-device-id="${deviceId}" data-index="${index}">Edit</button>
                        <button class="delete-btn bg-red-500 text-white px-2 py-1" data-device-id="${deviceId}" data-index="${index}">Delete</button>
                    </td>
                `;
                streamsTable.appendChild(row);
            });
        }

        // Attach event listeners for edit and delete buttons
        document.querySelectorAll('.edit-btn').forEach(btn => {
            btn.addEventListener('click', () => editStream(btn.dataset.deviceId, btn.dataset.index));
        });
        document.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', () => deleteStream(btn.dataset.deviceId, btn.dataset.index));
        });
    }

    function renderPlates() {
        platesList.innerHTML = '';
        config.ignored_plates.forEach((plate, index) => {
            const li = document.createElement('li');
            li.className = 'flex justify-between items-center border-b py-2';
            li.innerHTML = `
                <span>${plate}</span>
                <button class="delete-plate-btn bg-red-500 text-white px-2 py-1" data-index="${index}">Remove</button>
            `;
            platesList.appendChild(li);
        });

        // Attach event listeners for delete plate buttons
        document.querySelectorAll('.delete-plate-btn').forEach(btn => {
            btn.addEventListener('click', () => deletePlate(btn.dataset.index));
        });
    }

    function showStatus(message, isError = true) {
        statusMessage.textContent = message;
        statusMessage.classList.remove('hidden');
        statusMessage.classList.toggle('text-red-500', isError);
        statusMessage.classList.toggle('text-green-500', !isError);
        setTimeout(() => statusMessage.classList.add('hidden'), 5000);
    }

    function editStream(deviceId, index) {
        const stream = config.rtsp_streams[deviceId][index];
        document.querySelector('#device-id').value = deviceId;
        document.querySelector('#edit-device-id').value = deviceId;
        document.querySelector('#edit-stream-index').value = index;
        document.querySelector('#name').value = stream.name;
        document.querySelector('#url').value = stream.url;
        document.querySelector('#initial_delay_ms').value = stream.initial_delay_ms;
        document.querySelector('#num_images').value = stream.num_images;
        document.querySelector('#interval_ms').value = stream.interval_ms;
        document.querySelector('#video_duration_s').value = stream.video_duration_s;
        streamModal.classList.remove('hidden');
    }

    function deleteStream(deviceId, index) {
        if (confirm(`Delete stream ${config.rtsp_streams[deviceId][index].name} for device ${deviceId}?`)) {
            config.rtsp_streams[deviceId].splice(index, 1);
            if (config.rtsp_streams[deviceId].length === 0) {
                delete config.rtsp_streams[deviceId];
            }
            renderStreams();
        }
    }

    function deletePlate(index) {
        if (confirm(`Remove plate ${config.ignored_plates[index]}?`)) {
            config.ignored_plates.splice(index, 1);
            renderPlates();
        }
    }

    addStreamBtn.addEventListener('click', () => {
        streamForm.reset();
        document.querySelector('#edit-device-id').value = '';
        document.querySelector('#edit-stream-index').value = '';
        streamModal.classList.remove('hidden');
    });

    addPlateBtn.addEventListener('click', () => {
        const plate = newPlateInput.value.trim();
        if (plate && !config.ignored_plates.includes(plate)) {
            config.ignored_plates.push(plate);
            renderPlates();
            newPlateInput.value = '';
        } else if (!plate) {
            showStatus('Please enter a license plate');
        } else {
            showStatus('Plate already exists');
        }
    });

    streamForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const deviceId = document.querySelector('#device-id').value.trim();
        const editDeviceId = document.querySelector('#edit-device-id').value;
        const editIndex = document.querySelector('#edit-stream-index').value;
        const stream = {
            name: document.querySelector('#name').value.trim(),
            url: document.querySelector('#url').value.trim(),
            initial_delay_ms: parseInt(document.querySelector('#initial_delay_ms').value),
            num_images: parseInt(document.querySelector('#num_images').value),
            interval_ms: parseInt(document.querySelector('#interval_ms').value),
            video_duration_s: parseInt(document.querySelector('#video_duration_s').value)
        };

        if (!config.rtsp_streams[deviceId]) {
            config.rtsp_streams[deviceId] = [];
        }

        if (editDeviceId && editIndex !== '') {
            if (editDeviceId !== deviceId) {
                config.rtsp_streams[editDeviceId].splice(editIndex, 1);
                if (config.rtsp_streams[editDeviceId].length === 0) {
                    delete config.rtsp_streams[editDeviceId];
                }
                config.rtsp_streams[deviceId].push(stream);
            } else {
                config.rtsp_streams[deviceId][editIndex] = stream;
            }
        } else {
            config.rtsp_streams[deviceId].push(stream);
        }

        renderStreams();
        streamModal.classList.add('hidden');
    });

    cancelStreamBtn.addEventListener('click', () => {
        streamModal.classList.add('hidden');
    });

    saveBtn.addEventListener('click', () => {
        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    showStatus('Configuration saved successfully', false);
                } else {
                    showStatus('Failed to save configuration: ' + data.error);
                }
            })
            .catch(error => showStatus('Error: ' + error.message));
    });
});
EOF

# Create static/css/styles.css
cat > "$STATIC_DIR/css/styles.css" << 'EOF'
/* Custom styles if needed */
table {
    width: 100%;
    border-collapse: collapse;
}
th, td {
    border: 1px solid #ddd;
    padding: 8px;
    text-align: left;
}
EOF

# Set permissions for app files
chown -R "$USER:$GROUP" "$APP_DIR"
chmod -R 775 "$APP_DIR"

# Step 5: Ensure config.json exists and has correct permissions
print_status "Configuring config.json..."
if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" << 'EOF'
{
    "rtsp_streams": {},
    "ignored_plates": [],
    "paths": {
        "log_dir": "/var/log/protect-lpr",
        "log_file": "/var/log/protect-lpr/protect-lpr.log",
        "image_dir": "/var/lib/protect-lpr/images",
        "unknown_dir": "/var/lib/protect-lpr/images/unknown"
    },
    "logging": {
        "level": "INFO",
        "format": "%(asctime)s - %(levelname)s - %(message)s"
    },
    "server": {
        "port": 1025,
        "max_concurrent_ffmpeg": 4
    }
}
EOF
fi
chown "$USER:$GROUP" "$CONFIG_FILE"
chmod 664 "$CONFIG_FILE"

# Step 6: Configure Nginx
print_status "Configuring Nginx..."
cat > "$NGINX_CONFIG" << EOF
server {
    listen $NGINX_PORT;
    server_name docker;

    # Serve static files
    location /static/ {
        alias $APP_DIR/static/;
    }

    # Proxy to Flask app
    location / {
        proxy_pass http://localhost:$FLASK_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Enable Nginx site
ln -sf "$NGINX_CONFIG" /etc/nginx/sites-enabled/lpr_config

# Test Nginx configuration
nginx -t || print_error "Nginx configuration test failed"

# Restart Nginx
systemctl restart nginx || print_error "Failed to restart Nginx"
print_status "Nginx configured and restarted"

# Step 7: Set up systemd service for Gunicorn
print_status "Configuring Gunicorn systemd service..."
cat > "$SYSTEMD_SERVICE" << EOF
[Unit]
Description=Gunicorn instance for LPR Config Web App
After=network.target

[Service]
User=$USER
Group=$GROUP
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin"
ExecStart=$VENV_DIR/bin/gunicorn --workers 3 --bind 0.0.0.0:$FLASK_PORT app:app

[Install]
WantedBy=multi-user.target
EOF

# Enable and start service
systemctl daemon-reload
systemctl start lpr_config
systemctl enable lpr_config
systemctl status lpr_config | grep -q "active (running)" || print_error "Gunicorn service failed to start"
print_status "Gunicorn service configured and running"

# Step 8: Final instructions
print_status "Setup complete!"
echo "Access the LPR Configuration web app at: http://docker:$NGINX_PORT"
echo "To test locally, run: curl http://localhost:$NGINX_PORT"
echo "Check logs at: $LOG_DIR/web_config.log"
echo "Nginx logs: /var/log/nginx/error.log"
echo "To update config, visit the web app and save changes to $CONFIG_FILE"
echo "If the LPR webhook server needs to reload config, restart it manually"

exit 0
