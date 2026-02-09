# Kindle Kids Reading Stats

Scrapes reading activity data from the [Amazon Parent Dashboard](https://www.amazon.com/parentdashboard/) and saves it as structured JSON.

Uses Playwright to automate browser login (with 1Password CLI for credentials) and intercepts the dashboard's internal API to extract per-day, per-book reading data.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install playwright
playwright install chromium
```

Requires [1Password CLI](https://developer.1password.com/docs/cli/) (`op`) to be installed and authenticated.

## Usage

```bash
source .venv/bin/activate
python main.py
```

On first run you'll be prompted for your 1Password vault and item name. These are saved to `config.json` (gitignored) so you only enter them once.

The script will then:

1. Open a browser window
2. Log in to Amazon using credentials from 1Password
3. Handle OTP automatically if configured
4. Fetch weekly reading activity from your latest saved day forward (inclusive), or auto-bootstrap the last ~120 days on first run
5. Save results to `data/`

### Options

| Flag | Description |
|------|-------------|
| `--debug` | Save screenshots and log all API responses |

### Output files

| File | Description |
|------|-------------|
| `data/reading_data.json` | Canonical merged file — deduplicated by date, accumulates across runs |
| `data/fetch_<timestamp>.json` | Raw snapshot of each fetch including full API responses (never overwritten) |

Run it periodically (e.g. daily/weekly). Each run re-fetches your latest saved day and onward to capture any mid-day sync updates.

## Data format

`data/reading_data.json`:

```json
{
  "last_updated": "2026-02-05T12:53:59",
  "reading_activity": [
    {
      "date": "2026-01-15",
      "total_seconds": 6794,
      "total_minutes": 113.2,
      "books": [
        {
          "title": "Book Title",
          "asin": "B07HPCLJL6",
          "duration_seconds": 6794,
          "sessions": 2,
          "thumbnail": "https://images-na.ssl-images-amazon.com/..."
        }
      ]
    }
  ]
}
```

## How it works

1. **Login** — Playwright opens a Chromium browser, fills email/password/OTP from 1Password CLI
2. **Intercept** — Captures the dashboard's `get-household` API response to discover child IDs and the CSRF token from cookies
3. **Fetch** — Calls `get-weekly-activities-v2` for each week from your latest local day, or from an automatic ~120-day bootstrap window on first run
4. **Merge** — New data is deduplicated by date and merged into the canonical `reading_data.json`
