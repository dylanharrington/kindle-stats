import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def get_config():
    """Load config, prompting for missing values on first run."""
    config = load_config()
    changed = False

    if "op_vault" not in config:
        config["op_vault"] = input("1Password vault name: ").strip()
        changed = True

    if "op_item" not in config:
        config["op_item"] = input("1Password item name for Amazon: ").strip()
        changed = True

    if changed:
        save_config(config)
        print(f"Config saved to {CONFIG_PATH}")

    return config
