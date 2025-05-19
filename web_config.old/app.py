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
    try {
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info("Config updated successfully")
    } except Exception as e {
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
