"""Read-only summaries of reading_data.json for people and agents."""

from datetime import date, datetime, timedelta

DATE_FORMAT = "%Y-%m-%d"


def _book_key(book):
    return book.get("asin") or str(book.get("title") or "Unknown").casefold()


def summarize(data, days=7, today=None):
    """Summarize the last `days` days plus all-time totals.

    Returns plain dicts so callers can print text or dump JSON.
    """
    today = today or date.today()
    window_start = today - timedelta(days=days - 1)
    activity = sorted(data.get("reading_activity", []), key=lambda entry: entry["date"])

    all_books = {}
    window_books = {}
    window_seconds = 0
    window_days = 0

    for entry in activity:
        entry_date = datetime.strptime(entry["date"], DATE_FORMAT).date()
        in_window = window_start <= entry_date <= today
        if in_window and entry.get("total_seconds", 0) > 0:
            window_days += 1
            window_seconds += entry.get("total_seconds", 0)

        for book in entry.get("books", []):
            key = _book_key(book)
            seconds = book.get("duration_seconds", 0)
            record = all_books.setdefault(key, {
                "title": book.get("title") or "Unknown",
                "asin": book.get("asin"),
                "first_read": entry["date"],
                "last_read": entry["date"],
                "total_seconds": 0,
                "days": 0,
                "last_day_seconds": 0,
            })
            if record["last_read"] != entry["date"]:
                record["last_day_seconds"] = 0
            record["last_read"] = entry["date"]
            record["last_day_seconds"] += seconds
            record["total_seconds"] += seconds
            record["days"] += 1

            if in_window:
                window = window_books.setdefault(key, {
                    "title": record["title"],
                    "asin": record["asin"],
                    "seconds": 0,
                })
                window["seconds"] += seconds

    completed = {
        _book_key(book): book.get("completed_at")
        for book in data.get("completed_books", [])
    }
    for key, record in all_books.items():
        record["hours"] = round(record["total_seconds"] / 3600, 1)
        record["completed_at"] = completed.get(key)

    books_by_recency = sorted(
        all_books.values(),
        key=lambda record: (record["last_read"], record["last_day_seconds"]),
        reverse=True,
    )
    window_list = sorted(window_books.values(), key=lambda book: book["seconds"], reverse=True)
    for book in window_list:
        book["minutes"] = round(book["seconds"] / 60)

    total_seconds = sum(entry.get("total_seconds", 0) for entry in activity)
    return {
        "last_updated": data.get("last_updated"),
        "window": {
            "days": days,
            "start": window_start.strftime(DATE_FORMAT),
            "end": today.strftime(DATE_FORMAT),
            "hours": round(window_seconds / 3600, 1),
            "days_with_reading": window_days,
            "books": window_list,
        },
        "current_book": books_by_recency[0] if books_by_recency else None,
        "all_time": {
            "first_day": activity[0]["date"] if activity else None,
            "last_day": activity[-1]["date"] if activity else None,
            "hours": round(total_seconds / 3600, 1),
            "days_with_reading": sum(1 for entry in activity if entry.get("total_seconds", 0) > 0),
            "books": len(all_books),
            "completed_books": len(completed),
        },
        "books": books_by_recency,
    }


def format_summary(summary):
    """Render a summary as short plain text."""
    window = summary["window"]
    all_time = summary["all_time"]
    lines = [
        f"Last {window['days']} days ({window['start']} to {window['end']}): "
        f"{window['hours']} hours on {window['days_with_reading']} days",
    ]
    for book in window["books"]:
        lines.append(f"  - {book['title']}: {book['minutes']} min")

    current = summary["current_book"]
    if current:
        lines.append(f"Current book: {current['title']} (last read {current['last_read']})")

    if all_time["first_day"]:
        lines.append(
            f"All time ({all_time['first_day']} to {all_time['last_day']}): "
            f"{all_time['hours']} hours, {all_time['books']} books, "
            f"{all_time['completed_books']} marked complete by Amazon"
        )
    else:
        lines.append("No reading activity saved yet.")
    if summary["last_updated"]:
        lines.append(f"Data last synced: {summary['last_updated']}")
    return "\n".join(lines)
