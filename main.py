import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kindle_stats.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_TIME_ZONE,
    check_login_config,
    get_config,
    resolve_data_dir,
)
from kindle_stats.scraper import KindleParentDashboard

MERGED_FILENAME = "reading_data.json"
DATE_FORMAT = "%Y-%m-%d"
SECRET_ENV_PREFIXES = ("BW_", "OP_")


def write_private(path, text):
    """Write a data file that only the current user can read."""
    path.write_text(text)
    path.chmod(0o600)


def load_existing(merged_file):
    """Load the merged data file if it exists."""
    if merged_file.exists():
        return json.loads(merged_file.read_text())
    return {"reading_activity": []}


def merge_activity(existing, new_entries):
    """Merge new reading activity into existing, deduplicating by date.
    For duplicate dates, keeps the entry with the most books (freshest data)."""
    by_date = {}
    for entry in existing:
        by_date[entry["date"]] = entry
    for entry in new_entries:
        date = entry["date"]
        if date not in by_date or len(entry.get("books", [])) >= len(by_date[date].get("books", [])):
            by_date[date] = entry
    return sorted(by_date.values(), key=lambda x: x["date"])


def merge_completed_books(existing, new_entries):
    """Merge explicit completion records monotonically by ASIN, then title."""
    merged = {}
    for book in [*existing, *new_entries]:
        asin = str(book.get("asin") or "").strip().upper()
        title = str(book.get("title") or "").strip().casefold()
        identity = f"asin:{asin}" if asin else f"title:{title}"
        current = merged.get(identity)
        current_date = current.get("completed_at") if current else None
        candidate_date = book.get("completed_at")
        if title and (
            current is None
            or (candidate_date and (not current_date or candidate_date < current_date))
        ):
            merged[identity] = book
    return sorted(
        merged.values(),
        key=lambda book: (book.get("completed_at") or "", book.get("title") or ""),
    )


def build_post_sync_command(post_sync, merged_file):
    """Expand a post_sync config entry into (argv, cwd), or None when unset."""
    if not post_sync:
        return None
    command = post_sync.get("command")
    if not isinstance(command, list) or not command or not all(
        isinstance(part, str) for part in command
    ):
        raise ValueError('post_sync.command must be a non-empty list of strings')
    reading_data = str(Path(merged_file).resolve())
    argv = [part.replace("{reading_data}", reading_data) for part in command]
    cwd = post_sync.get("cwd")
    return argv, (os.path.expanduser(cwd) if cwd else None)


def run_post_sync(post_sync, merged_file):
    """Run the optional post_sync hook after reading_data.json is written."""
    built = build_post_sync_command(post_sync, merged_file)
    if built is None:
        return
    argv, cwd = built
    # The hook never needs password manager sessions, so do not pass them on.
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(SECRET_ENV_PREFIXES)
    }
    env["KINDLE_STATS_READING_DATA"] = str(Path(merged_file).resolve())
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"post_sync failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    print(f"  post_sync: {result.stdout.strip() or 'ok'}")


def latest_existing_date(reading_activity):
    """Return the latest valid date in reading_activity, or None if unavailable."""
    latest = None
    for entry in reading_activity:
        date_str = entry.get("date")
        if not date_str:
            continue
        try:
            entry_date = datetime.strptime(date_str, DATE_FORMAT).date()
        except ValueError:
            continue
        if latest is None or entry_date > latest:
            latest = entry_date
    return latest.strftime(DATE_FORMAT) if latest else None


def resolve_start_date(requested_start_date, reading_activity):
    """Use an explicit backfill date when provided, otherwise continue incrementally."""
    return requested_start_date or latest_existing_date(reading_activity)


def parse_start_date(value):
    """Validate and normalize an argparse start-date value."""
    try:
        parsed = datetime.strptime(value, DATE_FORMAT).date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"must be a valid date in {DATE_FORMAT} format"
        ) from exc

    canonical = parsed.strftime(DATE_FORMAT)
    if value != canonical:
        raise argparse.ArgumentTypeError(
            f"must use canonical {DATE_FORMAT} format"
        )
    if parsed > datetime.now().date():
        raise argparse.ArgumentTypeError("must not be in the future")
    return canonical


def build_parser():
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description="Kindle Kids Reading Data Scraper")
    parser.add_argument(
        "--debug", action="store_true",
        help="Save screenshots, list captured API calls, and print full child IDs",
    )
    parser.add_argument(
        "--start-date",
        type=parse_start_date,
        help="Force a historical backfill from YYYY-MM-DD instead of the latest saved day",
    )
    parser.add_argument(
        "--child",
        help="Only fetch this child (full child ID from --debug); required with 2+ children",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help=f"Where to keep data files (default: {DEFAULT_DATA_DIR})",
    )
    return parser


def resolve_time_zone(config):
    """Return the configured IANA time zone, validated."""
    name = config.get("time_zone") or DEFAULT_TIME_ZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise SystemExit(f"Invalid time_zone in config.json: {name!r}") from exc
    return name


def main():
    args = build_parser().parse_args()
    config = get_config()
    check_login_config(config)
    data_dir = resolve_data_dir(args.data_dir, config)
    merged_file = data_dir / MERGED_FILENAME
    dashboard = KindleParentDashboard(
        bw_item=config.get("bw_item"),
        op_vault=config.get("op_vault"),
        op_item=config.get("op_item"),
        op_auto_approve=config.get("op_auto_approve") is True,
        manual_login=config.get("login") == "manual",
        time_zone=resolve_time_zone(config),
        data_dir=data_dir,
    )
    existing = load_existing(merged_file)
    old_activity = existing.get("reading_activity", [])
    start_date = resolve_start_date(args.start_date, old_activity)

    if args.start_date:
        print(f"  Forced backfill starting from: {start_date}")
    elif start_date:
        print(f"  Incremental fetch starting from existing latest day: {start_date}")
    else:
        print("  No existing reading history found; using automatic bootstrap window")

    try:
        data = dashboard.fetch_reading_data(
            debug=args.debug,
            start_date=start_date,
            child=args.child or config.get("child"),
        )
    except (RuntimeError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    new_activity = data.get("reading_activity", [])
    new_completed_books = data.get("completed_books", [])
    print(f"  Fetched {len(new_activity)} days of activity")

    # Save raw fetch to timestamped file (never overwritten)
    if not data_dir.exists():
        data_dir.mkdir(mode=0o700, parents=True)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    raw_path = data_dir / f"fetch_{timestamp}.json"
    write_private(raw_path, json.dumps(data, indent=2))
    print(f"  Raw fetch saved to {raw_path}")

    # Merge into the single canonical file
    merged = merge_activity(old_activity, new_activity)

    existing["reading_activity"] = merged
    existing["completed_books"] = merge_completed_books(
        existing.get("completed_books", []),
        new_completed_books,
    )
    existing["last_updated"] = datetime.now().isoformat()

    write_private(merged_file, json.dumps(existing, indent=2))
    try:
        run_post_sync(config.get("post_sync"), merged_file)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    new_days = len(merged) - len(old_activity)
    print(f"\n  Merged: {len(merged)} total days ({'+' + str(new_days) if new_days > 0 else new_days} new)")
    if merged:
        print(f"  Date range: {merged[0]['date']} to {merged[-1]['date']}")
    else:
        print("  Date range: no activity yet")
    print(f"  Saved to {merged_file}")


if __name__ == "__main__":
    main()
