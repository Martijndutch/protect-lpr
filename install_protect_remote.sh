#!/bin/bash
# Usage: ./remote_install_and_deploy.sh <remote_user> <remote_host>
# This script will deploy the Protect LPR application to a remote Linux server.

set -e

if [ $# -ne 2 ]; then
    echo "Usage: $0 <remote_user> <remote_host>"
    exit 1
fi

REMOTE_USER="$1"
REMOTE_HOST="$2"
REMOTE_APP_DIR="/opt/protect-lpr"
LOCAL_APP_DIR="/opt/protect-lpr"
CONFIG_FILE="$LOCAL_APP_DIR/config.json"

# Read all required paths from config.json
REQUIRED_PATHS=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(' '.join([str(p) for p in c.get('paths',{}).values()]))")
LOG_FILE=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(c.get('paths',{}).get('log_file',''))")
MEDIA_DIR=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE')); print(c.get('paths',{}).get('image_dir',''))")

echo "==> Creating required directories, installing packages, and setting permissions on remote server (single sudo prompt)..."

TMP_SCRIPT="/tmp/protect_lpr_setup_$$.sh"

cat > "$TMP_SCRIPT" <<EOF
#!/bin/bash
set -e
REMOTE_APP_DIR="$REMOTE_APP_DIR"
REQUIRED_PATHS="$REQUIRED_PATHS"
LOG_FILE="$LOG_FILE"
REMOTE_USER="$REMOTE_USER"
MEDIA_DIR="$MEDIA_DIR"

# Create required directories and set permissions
mkdir -p "\$REMOTE_APP_DIR"
IFS=" " read -r -a DIRS <<< "\$REQUIRED_PATHS"
for DIR in "\${DIRS[@]}"; do
    mkdir -p "\$DIR"
    chown "\$REMOTE_USER:\$REMOTE_USER" "\$DIR"
    chmod 770 "\$DIR"
done
if [ -n "\$LOG_FILE" ]; then
    touch "\$LOG_FILE"
    chown "\$REMOTE_USER:\$REMOTE_USER" "\$LOG_FILE"
    chmod 660 "\$LOG_FILE"
fi

# Install required packages
apt-get update
apt-get install -y python3 python3-pip python3-venv samba nginx rsync

# Configure Samba if needed
if [ -n "\$MEDIA_DIR" ]; then
    grep -q '\\[protect-lpr-media\\]' /etc/samba/smb.conf || \
    echo -e '\\n[protect-lpr-media]\\n   path = '\$MEDIA_DIR'\\n   browseable = yes\\n   read only = no\\n   guest ok = yes\\n' | tee -a /etc/samba/smb.conf
    systemctl restart smbd
fi

# Enable and start nginx
systemctl enable nginx
systemctl restart nginx

rm -- "\$0"
EOF

chmod +x "$TMP_SCRIPT"
scp "$TMP_SCRIPT" "$REMOTE_USER@$REMOTE_HOST:/tmp/protect_lpr_setup.sh"
ssh -tt "$REMOTE_USER@$REMOTE_HOST" "sudo bash /tmp/protect_lpr_setup.sh"

rm "$TMP_SCRIPT"

echo "==> Copying application files to remote server..."
ssh "$REMOTE_USER@$REMOTE_HOST" "sudo chown -R $REMOTE_USER:$REMOTE_USER $REMOTE_APP_DIR"
rsync -avz --delete "$LOCAL_APP_DIR/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_APP_DIR/"
ssh "$REMOTE_USER@$REMOTE_HOST" "sudo chown -R root:root $REMOTE_APP_DIR"

echo "==> Setting up Python virtual environment and installing dependencies on remote server..."
ssh "$REMOTE_USER@$REMOTE_HOST" "cd $REMOTE_APP_DIR && python3 -m venv venv && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt"

echo "==> Deployment and installation complete on $REMOTE_HOST."

