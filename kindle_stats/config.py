import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.json"
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_TIME_ZONE = "America/Los_Angeles"


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    try:
        config = json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{CONFIG_PATH} is not valid JSON: {exc}") from exc
    if not isinstance(config, dict):
        raise SystemExit(f"{CONFIG_PATH} must contain a JSON object, like {{\"bw_item\": \"Amazon\"}}")
    return config


def save_config(config):
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def resolve_data_dir(cli_value, config):
    """Pick the data directory. A relative data_dir in config.json is relative to the repo."""
    if cli_value:
        return Path(cli_value).expanduser()
    configured = config.get("data_dir")
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else REPO_ROOT / path
    return DEFAULT_DATA_DIR


def check_login_config(config):
    """Stop before the browser opens when config.json has no usable sign-in method."""
    if config.get("login") == "manual":
        return
    if config.get("bw_item") or (config.get("op_vault") and config.get("op_item")):
        return
    raise SystemExit(
        f"No sign-in method in {CONFIG_PATH}. Set \"bw_item\", both \"op_vault\" and "
        "\"op_item\", or \"login\": \"manual\". See config.example.json."
    )


def _ask(prompt, default=None):
    """Ask until the answer is not blank."""
    while True:
        answer = input(prompt).strip() or (default or "")
        if answer:
            return answer
        print("  Please enter a value.")


def get_config():
    """Load config, prompting only when no config.json exists yet.

    An existing config.json is used as-is so unattended runs never block on a
    prompt. Without one, interactive runs ask a few questions and non-interactive
    runs stop with instructions.
    """
    if CONFIG_PATH.exists():
        return load_config()

    if not sys.stdin.isatty():
        raise SystemExit(
            f"No config found at {CONFIG_PATH}.\n"
            "Copy config.example.json to config.json and edit it, "
            "or run `python main.py` once in a terminal to answer the setup prompts."
        )

    config = {}
    print("First-run setup. Answers are saved to config.json (gitignored).")
    login = input("How should Amazon credentials be filled? [bitwarden/1password/manual] (bitwarden): ")
    login = login.strip().lower() or "bitwarden"

    if login == "manual":
        config["login"] = "manual"
    elif login in ("1password", "op"):
        config["op_vault"] = _ask("1Password vault name: ")
        config["op_item"] = _ask("1Password item name for Amazon: ")
    else:
        config["bw_item"] = _ask("Bitwarden item name for Amazon [Amazon]: ", default="Amazon")

    save_config(config)
    print(f"Config saved to {CONFIG_PATH}")
    return config
