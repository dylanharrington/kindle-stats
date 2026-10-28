# Kindle Kids Reading Stats

Saves your child's daily Kindle reading time from the
[Amazon Parent Dashboard](https://www.amazon.com/parentdashboard/) as JSON on your own computer.
You get one file with every day, every book, and the minutes read. Amazon only keeps about
90 days of history, so running this regularly builds a permanent record.

It works with a Kindle Kids e-reader or a Fire Kids tablet that is managed in Amazon Parent
Dashboard. On a Fire tablet it keeps only book time and skips apps, video, and web time.

Setting this up with an AI agent? Give it [AGENTS.md](AGENTS.md). It has a step-by-step setup
runbook and example workflows.

Want the whole routine, including picking age-appropriate books, buying them, and putting them
on your child's Kindle? See [PLAYBOOK.md](PLAYBOOK.md).

## Safety and privacy

- **It runs on your computer.** During a run it talks only to Amazon's websites. No data goes
  anywhere else unless you add a `post_sync` hook yourself. (Setup downloads packages from PyPI
  and the Playwright browser.)
- **Your password is never saved.** Each run reads your Amazon login from Bitwarden or 1Password,
  or you sign in yourself in the browser window. The script does not write credentials to disk
  or print them.
- **Your data stays in `data/`.** That folder is gitignored. It holds book titles, dates, and
  minutes, plus raw snapshots of Amazon's dashboard responses. Those can include household
  member and device details. The files are readable only by your user. Do not commit or share
  them.
- **`--debug` screenshots can show your email address.** Delete `data/debug_*.png` after you
  finish debugging.
- **It uses Amazon's private dashboard endpoints.** These are undocumented, so Amazon can change
  them and break the script. Use it for your own family's account only. Each run makes about one
  request per week of history, with a short pause between requests.
- `op_read_auto.sh` is an opt-in helper that presses Space to approve the 1Password prompt. It
  is off by default. Leave it off unless you understand that it skips a 1Password security check.

## Requirements

- macOS or Linux with a desktop session. Each run opens a visible Chromium window.
- Python 3.10 or newer.
- The Amazon account that manages your child in Parent Dashboard.
- One way to sign in:
  - [Bitwarden CLI](https://bitwarden.com/help/cli/) (`bw`) plus `jq`, unlocked with `BW_SESSION` set, or
  - [1Password CLI](https://developer.1password.com/docs/cli/) (`op`), signed in, or
  - nobody: you type the password in the browser window each time (`"login": "manual"`).
- For unattended runs, store the Amazon two-step verification (TOTP) secret in the same
  password manager item. Otherwise someone has to type the code within 2 minutes.

## Quick start

```bash
git clone https://github.com/dylanharrington/kindle-stats.git
cd kindle-stats
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp config.example.json config.json   # then edit it (see below)
python main.py                       # first run fetches about the last 120 days
python summary.py                    # prints the last 7 days
```

If there is no `config.json`, running `python main.py` in a terminal asks a few setup
questions and saves the answers.

## Configuration

`config.json` is gitignored. Every key is optional, but you need one way to sign in.

| Key | Example | What it does |
|-----|---------|--------------|
| `bw_item` | `"Amazon"` | Bitwarden item with the Amazon username, password, and optional TOTP |
| `op_vault`, `op_item` | `"Private"`, `"Amazon"` | 1Password vault and item. Set both. Used if Bitwarden is not set or fails |
| `login` | `"manual"` | Skip the password manager. You sign in yourself (5-minute limit) |
| `child` | `"amzn1.account.AB12..."` | Full child ID to sync. Required if the account has 2 or more children |
| `time_zone` | `"America/New_York"` | IANA time zone for day boundaries. Default `America/Los_Angeles` |
| `data_dir` | `"~/kindle-data"` | Where data is saved. Default is `data/` in this repo. A relative path is relative to this repo |
| `post_sync` | see below | Command to run after each successful sync |
| `op_auto_approve` | `true` | Use `op_read_auto.sh`. Off by default. See the safety note above |

Examples:

```json
{ "bw_item": "Amazon", "time_zone": "America/Los_Angeles" }
```

```json
{ "op_vault": "Private", "op_item": "Amazon" }
```

```json
{ "login": "manual" }
```

### post_sync hook

Use `post_sync` to feed the data into something else, such as a family website. The command is
a list of arguments (no shell). `{reading_data}` becomes the absolute path to
`reading_data.json`, and the same path is in the `KINDLE_STATS_READING_DATA` environment
variable. If the command fails, `main.py` exits with an error.

```json
{
  "bw_item": "Amazon",
  "post_sync": {
    "command": ["node", "scripts/import-reading.mjs", "--input", "{reading_data}"],
    "cwd": "~/code/family-site"
  }
}
```

## Commands

```bash
python main.py                          # sync from the latest saved day to now
python main.py --debug                  # also save screenshots and print full child IDs
python main.py --start-date 2026-08-01  # re-fetch from a date (Amazon keeps about 90 days)
python main.py --child amzn1.account.AAAA... --data-dir data/ava

python summary.py                       # last 7 days, current book, all-time totals
python summary.py --days 30
python summary.py --json                # same data as JSON, for scripts and agents
```

`main.py` exits with status 1 and an `ERROR:` line when it cannot sign in, finds no child, or
the `post_sync` hook fails. A failed sign-in or child lookup leaves `reading_data.json`
unchanged.

`summary.py` only reads local files. It never signs in to Amazon.

## Running it on a schedule

Run it once a day, or at least once a week. Amazon drops activity older than about 90 days, so
a gap longer than that loses history for good.

The job must run inside a logged-in desktop session, because the browser window is visible.
Use your agent's scheduler, a macOS LaunchAgent, or cron on a Linux desktop. The password
manager must also be unlocked. A small wrapper script keeps the schedule simple:

```bash
#!/bin/bash
# ~/bin/kindle-sync.sh
set -euo pipefail
. ~/.config/kindle-stats.env   # exports BW_SESSION; chmod 600 this file
cd ~/code/kindle-stats
mkdir -p data
.venv/bin/python main.py >> data/sync.log 2>&1
```

A saved `BW_SESSION` unlocks your whole Bitwarden vault, not just the Amazon item. Keep that
file private (`chmod 600`), and decide on purpose whether you want a stored session at all.

## More than one child

Each child's reading is stored by date with no child label, so each data folder holds one child.
With 2 or more children, `main.py` stops instead of mixing them. Run it once per child:

```bash
python main.py --child amzn1.account.AAAA... --data-dir data/ava
python main.py --child amzn1.account.BBBB... --data-dir data/ben
```

Amazon currently does not send child names on this page, so names often show as `Unknown`.
Use the full child ID instead. `python main.py --debug` prints it. If a name matches more than
one child, `main.py` stops and asks for the ID.

This tool has been tested on an account with one child. The multi-child guard is covered by
unit tests but has not run against a real multi-child account.

## Output files

| File | Description |
|------|-------------|
| `data/reading_data.json` | Main file. One entry per day, merged across runs |
| `data/fetch_<timestamp>.json` | Raw snapshot of each run, including Amazon's responses. Never overwritten |
| `data/debug_*.png` | Only with `--debug`. Can show your email address |

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
  ],
  "completed_books": [
    {
      "title": "Book Title",
      "asin": "B07HPCLJL6",
      "completion_status": "completed",
      "completed_at": "2026-07-29",
      "evidence": {
        "type": "progress_percent",
        "value": 100
      }
    }
  ]
}
```

`completed_books` contains only explicit Amazon completion signals (`completed`, `finished`, or
100% progress). Reading time never creates a completion record. Amazon rarely sends these
signals, so expect this list to be short or empty.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No config found` | Copy `config.example.json` to `config.json`, or run `python main.py` in a terminal once |
| `Could not retrieve 'username'` | Unlock the password manager (`bw unlock`, `op signin`) or check the item name |
| `No CSRF token found` | Sign-in did not reach Parent Dashboard. Run `python main.py --debug` and look at `data/debug_landing.png` |
| `Found 2 children` | Set `child` in `config.json`, or use `--child` and `--data-dir` |
| Login waits for a code | Add the TOTP secret to the password manager item, or type the code in the window |
| `Week N/M ... HTTP 500` | That week is older than Amazon keeps. Safe to ignore |

## How it works

1. **Login.** Playwright opens Chromium and fills email, password, and the one-time code.
2. **Discover.** It reads the child ID and CSRF token from the dashboard's own page load.
3. **Fetch.** It calls `get-weekly-activities-v2` for each week from the latest saved day, or
   for the last 120 days on the first run.
4. **Merge.** New days merge into `reading_data.json`, keyed by date.

## Tests

```bash
python -m unittest discover -s tests
```
