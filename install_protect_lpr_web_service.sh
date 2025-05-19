#!/bin/bash

# Install systemd service for protect-lpr-web (web.py)

set -e

APP_DIR="/opt/protect-lpr"
VENV_DIR="$APP_DIR/venv"
SERVICE_FILE="/etc/systemd/system/protect-lpr-web.service"
USER="martijn"
GROUP="www-data"
PORT="8082"

echo "[INFO] Creating systemd service file at $SERVICE_FILE"

# Check if venv exists, if not, create it and install gunicorn
if [ ! -x "$VENV_DIR/bin/gunicorn" ]; then
    echo "[INFO] Python venv or gunicorn not found, creating venv and installing gunicorn..."
    python3 -m venv "$VENV_DIR" || { echo "[ERROR] Failed to create Python venv at $VENV_DIR"; exit 1; }
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/python" -m pip install gunicorn flask
fi

# Double-check gunicorn exists and is executable
if [ ! -x "$VENV_DIR/bin/gunicorn" ]; then
    echo "[ERROR] gunicorn not found at $VENV_DIR/bin/gunicorn after install. Aborting."
    exit 1
fi

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Gunicorn instance for Protect LPR Web (web.py)
After=network.target

[Service]
User=$USER
Group=$GROUP
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin"
ExecStart=$VENV_DIR/bin/gunicorn --workers 3 --bind 0.0.0.0:$PORT web:app

[Install]
WantedBy=multi-user.target
EOF

echo "[INFO] Reloading systemd daemon"
systemctl daemon-reload

echo "[INFO] Enabling and starting protect-lpr-web service"
systemctl enable protect-lpr-web
systemctl restart protect-lpr-web

echo "[INFO] Service status:"
systemctl status protect-lpr-web --no-pager

echo "[INFO] Done. Service 'protect-lpr-web' should now be running on port $PORT."
