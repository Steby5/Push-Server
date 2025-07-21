import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}

def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)

def update_config(key: str, value):
    config = load_config()
    config[key] = value
    save_config(config)
    
def get_config_value(key: str, default=None):
    config = load_config()
    return config.get(key, default)