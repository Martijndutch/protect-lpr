#!/bin/bash

# Backup script for LPR application and scripts
# Run as: ./backup_lpr.sh
# User: martijn, Saves to: /home/martijn/protect_v.x

set -e

# Configuration variables
USER="martijn"
HOME_DIR="/home/$USER"
SRC_DIR="/opt/protect-lpr"
BASE_DEST_DIR="$HOME_DIR/protect_v"
SETUP_SCRIPT="setup_lpr_config.sh"

# Files and directories to collect (relative to SRC_DIR)
FILES=(
    "protect.py"
    "config.json"
    "web_config/app.py"
    "web_config/templates/index.html"
    "web_config/static/js/script.js"
    "web_config/static/css/styles.css"
)

# Function to print status
print_status() {
    echo -e "\033[1;32m[INFO]\033[0m $1"
}

# Function to print error and exit
print_error() {
    echo -e "\033[1;31m[ERROR]\033[0m $1"
    exit 1
}

# Check if running as correct user
if [ "$(whoami)" != "$USER" ]; then
    print_error "This script must be run as user $USER (not $(whoami))"
fi

# Step 1: Find next version number
print_status "Determining version number..."
VERSION=1
while [ -d "${BASE_DEST_DIR}.${VERSION}" ]; do
    VERSION=$((VERSION + 1))
done
DEST_DIR="${BASE_DEST_DIR}.${VERSION}"
print_status "Using destination: $DEST_DIR"

# Step 2: Create destination directory
print_status "Creating destination directory..."
mkdir -p "$DEST_DIR" || print_error "Failed to create $DEST_DIR"

# Step 3: Copy files
print_status "Copying LPR application files..."
for FILE in "${FILES[@]}"; do
    SRC_PATH="$SRC_DIR/$FILE"
    DEST_PATH="$DEST_DIR/$FILE"
    if [ -f "$SRC_PATH" ]; then
        mkdir -p "$(dirname "$DEST_PATH")"
        cp "$SRC_PATH" "$DEST_PATH" || print_error "Failed to copy $SRC_PATH"
        print_status "Copied $FILE"
    else
        print_status "Warning: $SRC_PATH not found, skipping"
    fi
done

# Step 4: Copy setup script if it exists in current directory
if [ -f "$SETUP_SCRIPT" ]; then
    print_status "Copying setup script..."
    cp "$SETUP_SCRIPT" "$DEST_DIR/$SETUP_SCRIPT" || print_error "Failed to copy $SETUP_SCRIPT"
    print_status "Copied $SETUP_SCRIPT"
else
    print_status "Warning: $SETUP_SCRIPT not found in current directory, skipping"
fi

# Step 5: Set permissions
print_status "Setting permissions..."
chown -R "$USER:$USER" "$DEST_DIR"
chmod -R 755 "$DEST_DIR"
chmod 644 "$DEST_DIR"/* "$DEST_DIR"/web_config/* "$DEST_DIR"/web_config/templates/* "$DEST_DIR"/web_config/static/*/* 2>/dev/null

# Step 6: Create README.md
print_status "Creating README.md..."
cat > "$DEST_DIR/README.md" << 'EOF'
# LPR Application Backup

This directory contains a backup of the License Plate Recognition (LPR) application files, including the webhook server and configuration web app, as of the backup date.

## Directory Structure
- `webhook_server.py`: LPR webhook server script (runs on port 1025).
- `config.json`: Configuration file for the LPR system (rtsp_streams, ignored_plates, etc.).
- `web_config/app.py`: Flask web application for configuring LPR settings.
- `web_config/templates/index.html`: HTML template for the web app interface.
- `web_config/static/js/script.js`: JavaScript for dynamic web app functionality.
- `web_config/static/css/styles.css`: CSS styles for the web app.
- `setup_lpr_config.sh`: Setup script to install and configure the web app (if included).

## Setup Instructions
To restore or set up the application on an Ubuntu system:

1. **Copy Files**:
   - Place files in `/opt/protect-lpr/` with the same structure.
   - Example: `sudo cp -r * /opt/protect-lpr/`

2. **Run Setup Script** (if included):
   ```bash
   cd /opt/protect-lpr
   sudo chmod +x setup_lpr_config.sh
   sudo ./setup_lpr_config.sh
   ```
   This installs dependencies, sets up the Flask app, configures Nginx, and starts the Gunicorn service.

3. **Manual Setup** (if no setup script):
   - Install dependencies:
     ```bash
     sudo apt update
     sudo apt install -y python3 python3-pip python3-venv nginx
     ```
   - Set up virtual environment:
     ```bash
     cd /opt/protect-lpr/web_config
     python3 -m venv venv
     source venv/bin/activate
     pip install flask gunicorn
     deactivate
     ```
   - Configure Nginx:
     ```bash
     sudo nano /etc/nginx/sites-available/lpr_config
     ```
     Add:
     ```
     server {
         listen 8080;
         server_name docker;
         location /static/ {
             alias /opt/protect-lpr/web_config/static/;
         }
         location / {
             proxy_pass http://localhost:5000;
             proxy_set_header Host $host;
             proxy_set_header X-Real-IP $remote_addr;
             proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
             proxy_set_header X-Forwarded-Proto $scheme;
         }
     }
     ```
     Enable and restart:
     ```bash
     sudo ln -s /etc/nginx/sites-available/lpr_config /etc/nginx/sites-enabled/
     sudo nginx -t
     sudo systemctl restart nginx
     ```
   - Set up Gunicorn service:
     ```bash
     sudo nano /etc/systemd/system/lpr_config.service
     ```
     Add:
     ```
     [Unit]
     Description=Gunicorn instance for LPR Config Web App
     After=network.target
     [Service]
     User=martijn
     Group=www-data
     WorkingDirectory=/opt/protect-lpr/web_config
     Environment="PATH=/opt/protect-lpr/web_config/venv/bin"
     ExecStart=/opt/protect-lpr/web_config/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 app:app
     [Install]
     WantedBy=multi-user.target
     ```
     Enable and start:
     ```bash
     sudo systemctl daemon-reload
     sudo systemctl start lpr_config
     sudo systemctl enable lpr_config
     ```
   - Set permissions:
     ```bash
     sudo chown martijn:www-data /opt/protect-lpr/config.json
     sudo chmod 664 /opt/protect-lpr/config.json
     sudo chown -R martijn:www-data /opt/protect-lpr/web_config/static
     sudo chmod -R 775 /opt/protect-lpr/web_config/static
     sudo chown martijn:www-data /var/log/protect-lpr
     sudo chmod 775 /var/log/protect-lpr
     ```

4. **Access the Web App**:
   - Navigate to `http://<hostname>:8080` (e.g., `http://docker:8080`).
   - Use the interface to configure `rtsp_streams` and `ignored_plates`.

5. **Run Webhook Server**:
   - Ensure the webhook server is running (port 1025):
     ```bash
     python3 /opt/protect-lpr/webhook_server.py
     ```
     Or set up as a systemd service.

## Notes
- **Backup Date**: Created on $(date '+%Y-%m-%d %H:%M:%S %Z').
- **Security**: The web app lacks authentication. Consider adding Flask-Login or Nginx basic auth.
- **Logs**: Check `/var/log/protect-lpr/web_config.log` for web app logs and `/var/log/nginx/error.log` for Nginx issues.
- **Webhook Server**: Restart the webhook server after config changes if it doesn't reload `config.json` dynamically.

For support, contact the system administrator or refer to the original setup documentation.
EOF

# Set permissions for README
chown "$USER:$USER" "$DEST_DIR/README.md"
chmod 644 "$DEST_DIR/README.md"
print_status "Created README.md"

# Step 7: Final instructions
print_status "Backup complete!"
echo "Files saved to: $DEST_DIR"
echo "Directory structure:"
tree "$DEST_DIR" || ls -R "$DEST_DIR"
echo "To restore, follow instructions in $DEST_DIR/README.md"
echo "Verify files with: ls -l $DEST_DIR"

exit 0
