import argparse
import json
from datetime import datetime
from pathlib import Path

from kindle_stats.config import get_config
from kindle_stats.scraper import KindleParentDashboard

MERGED_FILE = Path("data/reading_data.json")
DATE_FORMAT = "%Y-%m-%d"


def load_existing():
    """Load the merged data file if it exists."""
    if MERGED_FILE.exists():
        return json.loads(MERGED_FILE.read_text())
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


def main():
    parser = argparse.ArgumentParser(description="Kindle Kids Reading Data Scraper")
    parser.add_argument(
        "--debug", action="store_true",
        help="Save screenshots and log all captured API responses",
    )

    args = parser.parse_args()
    config = get_config()
    dashboard = KindleParentDashboard(
        op_vault=config["op_vault"],
        op_item=config["op_item"],
    )
    existing = load_existing()
    old_activity = existing.get("reading_activity", [])
    start_date = latest_existing_date(old_activity)

    if start_date:
        print(f"  Incremental fetch starting from existing latest day: {start_date}")
    else:
        print("  No existing reading history found; using automatic bootstrap window")

    data = dashboard.fetch_reading_data(
        debug=args.debug,
        start_date=start_date,
    )

    new_activity = data.get("reading_activity", [])
    print(f"  Fetched {len(new_activity)} days of activity")

    # Save raw fetch to timestamped file (never overwritten)
    Path("data").mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    raw_path = Path(f"data/fetch_{timestamp}.json")
    raw_path.write_text(json.dumps(data, indent=2))
    print(f"  Raw fetch saved to {raw_path}")

    # Merge into the single canonical file
    merged = merge_activity(old_activity, new_activity)

    existing["reading_activity"] = merged
    existing["last_updated"] = datetime.now().isoformat()

    MERGED_FILE.write_text(json.dumps(existing, indent=2))

    new_days = len(merged) - len(old_activity)
    print(f"\n  Merged: {len(merged)} total days ({'+' + str(new_days) if new_days > 0 else new_days} new)")
    if merged:
        print(f"  Date range: {merged[0]['date']} to {merged[-1]['date']}")
    else:
        print("  Date range: no activity yet")
    print(f"  Saved to {MERGED_FILE}")


if __name__ == "__main__":
    main()
