import argparse
import json
from pathlib import Path

from kindle_stats.config import DEFAULT_DATA_DIR, load_config
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

    data_dir = Path(args.data_dir or load_config().get("data_dir") or DEFAULT_DATA_DIR).expanduser()
    merged_file = data_dir / "reading_data.json"
    if not merged_file.exists():
        raise SystemExit(f"No reading data at {merged_file}. Run `python main.py` first.")

    summary = summarize(json.loads(merged_file.read_text()), days=args.days)
    print(json.dumps(summary, indent=2) if args.json else format_summary(summary))


if __name__ == "__main__":
    main()
