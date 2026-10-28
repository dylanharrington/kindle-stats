import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.json"
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_TIME_ZONE = "America/Los_Angeles"


def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def get_config():
    """Load config, prompting only when no config.json exists yet.

    An existing config.json is used as-is so unattended runs never block on a
    prompt. Without one, interactive runs ask a few questions and non-interactive
    runs stop with instructions.
    """
    config = load_config()
    if config:
        return config

    if not sys.stdin.isatty():
        raise SystemExit(
            f"No config found at {CONFIG_PATH}.\n"
            "Copy config.example.json to config.json and edit it, "
            "or run `python main.py` once in a terminal to answer the setup prompts."
        )

    print("First-run setup. Answers are saved to config.json (gitignored).")
    login = input("How should Amazon credentials be filled? [bitwarden/1password/manual] (bitwarden): ")
    login = login.strip().lower() or "bitwarden"

    if login == "manual":
        config["login"] = "manual"
    elif login in ("1password", "op"):
        config["op_vault"] = input("1Password vault name: ").strip()
        config["op_item"] = input("1Password item name for Amazon: ").strip()
    else:
        config["bw_item"] = input("Bitwarden item name for Amazon [Amazon]: ").strip() or "Amazon"

    save_config(config)
    print(f"Config saved to {CONFIG_PATH}")
    return config
