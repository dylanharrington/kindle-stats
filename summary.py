import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kindle_stats.config import DEFAULT_DATA_DIR, DEFAULT_TIME_ZONE, load_config, resolve_data_dir
from kindle_stats.summary import format_summary, summarize


def main():
    parser = argparse.ArgumentParser(
        description="Summarize saved Kindle reading data (read-only, no Amazon login)",
    )
    parser.add_argument("--days", type=int, default=7, help="Recent window in days (default: 7)")
    parser.add_argument("--data-dir", type=Path, help=f"Data directory (default: {DEFAULT_DATA_DIR})")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")

    config = load_config()
    data_dir = resolve_data_dir(args.data_dir, config)
    merged_file = data_dir / "reading_data.json"
    if not merged_file.exists():
        raise SystemExit(f"No reading data at {merged_file}. Run `python main.py` first.")

    try:
        today = datetime.now(ZoneInfo(config.get("time_zone") or DEFAULT_TIME_ZONE)).date()
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise SystemExit(f"Invalid time_zone in config.json: {config.get('time_zone')!r}") from exc

    summary = summarize(json.loads(merged_file.read_text()), days=args.days, today=today)
    print(json.dumps(summary, indent=2) if args.json else format_summary(summary))


if __name__ == "__main__":
    main()
