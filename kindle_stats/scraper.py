import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

DASHBOARD_URL = "https://www.amazon.com/parentdashboard/activities/household-summary"
ACTIVITIES_API = "https://www.amazon.com/parentdashboard/ajax/get-weekly-activities-v2"
AJAX_PREFIX = "/parentdashboard/ajax/"
BOOTSTRAP_LOOKBACK_DAYS = 120
TIME_ZONE = "America/Los_Angeles"
DATE_FORMAT = "%Y-%m-%d"
BOOK_CATEGORY = "BOOK"
MANUAL_LOGIN_TIMEOUT_SECONDS = 300


def _run_quiet(args, **kwargs):
    """Run a helper CLI, returning None when it is missing or fails."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _short_id(child_id):
    """Shorten an Amazon account ID for log output."""
    return f"...{child_id[-6:]}" if len(child_id) > 6 else child_id


class KindleParentDashboard:
    time_zone = TIME_ZONE
    data_dir = Path("data")

    def __init__(
        self,
        bw_item=None,
        op_vault=None,
        op_item=None,
        op_auto_approve=False,
        manual_login=False,
        time_zone=TIME_ZONE,
        data_dir=Path("data"),
    ):
        self.bw_item = bw_item
        self.op_vault = op_vault
        self.op_item = op_item
        self.op_auto_approve = op_auto_approve
        self.manual_login = manual_login
        self.time_zone = time_zone
        self.data_dir = Path(data_dir)

    @staticmethod
    def _bw_get_field(item_name, field):
        """Read a credential field using Bitwarden CLI.

        field should be a jq expression like '.login.username' or '.login.password'.
        Requires BW_SESSION env var to be set.
        """
        if not item_name:
            return None
        item_json = _run_quiet(["bw", "get", "item", item_name])
        if item_json is None:
            return None
        value = _run_quiet(["jq", "-r", field], input=item_json)
        if value is None:
            return None
        value = value.strip()
        return value if value and value != "null" else None

    def _op_read(self, ref):
        """Read a value using a 1Password secret reference."""
        if self.op_auto_approve:
            # Opt-in only: the wrapper presses Space to approve the 1Password prompt.
            args = [str(Path(__file__).parent.parent / "op_read_auto.sh"), ref]
        else:
            args = ["op", "read", ref]
        try:
            result = subprocess.run(args, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError("1Password CLI (op) is not installed") from exc
        if result.returncode != 0:
            raise RuntimeError(f"op read failed for '{ref}': {result.stderr.strip()}")
        return result.stdout.strip()

    def _get_credential(self, field_name):
        """Get a credential, trying Bitwarden first then falling back to 1Password."""
        bw_fields = {"username": ".login.username", "password": ".login.password"}
        bw_field = bw_fields.get(field_name)
        if bw_field and self.bw_item:
            value = self._bw_get_field(self.bw_item, bw_field)
            if value:
                return value
            print(f"  Bitwarden lookup failed for {field_name}, falling back to 1Password...")
        if self.op_vault and self.op_item:
            return self._op_read(f"op://{self.op_vault}/{self.op_item}/{field_name}")
        raise RuntimeError(f"Could not retrieve '{field_name}' from Bitwarden or 1Password")

    def _get_otp(self):
        """Get a one-time code from Bitwarden or 1Password, or None."""
        if self.bw_item:
            otp = (_run_quiet(["bw", "get", "totp", self.bw_item]) or "").strip()
            if otp:
                print("  Filling OTP from Bitwarden...")
                return otp
        if self.op_item:
            args = ["op", "item", "get", self.op_item, "--otp"]
            if self.op_vault:
                args += ["--vault", self.op_vault]
            otp = (_run_quiet(args) or "").strip()
            if otp:
                print("  Filling OTP from 1Password...")
                return otp
        return None

    def _wait_for_dashboard(self, page, timeout_seconds=120):
        """Wait for the page to navigate away from sign-in to the dashboard."""
        print(f"Waiting up to {timeout_seconds}s for login to complete...")
        print("Complete any verification in the browser window.")
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            url = page.url
            if "parentdashboard" in url and "/ap/" not in url:
                print("Login successful!")
                return True
            time.sleep(1)
        raise TimeoutError("Login did not complete within timeout.")

    def _do_login(self, page, debug=False):
        """Handle Amazon sign-in using Bitwarden (with 1Password fallback)."""
        if self.manual_login:
            print("Manual login: sign in to Amazon in the browser window.")
            self._wait_for_dashboard(page, timeout_seconds=MANUAL_LOGIN_TIMEOUT_SECONDS)
            return

        print(f"Fetching credentials for '{self.bw_item or self.op_item}'...")
        email = self._get_credential("username")
        password = self._get_credential("password")

        if debug:
            self.data_dir.mkdir(parents=True, exist_ok=True)

        # Fill email
        email_input = page.locator('#ap_email')
        if email_input.is_visible(timeout=5000):
            email_input.click()
            email_input.fill(email)
            page.wait_for_timeout(500)
            page.locator('#continue').first.click()
            page.wait_for_load_state("networkidle")
            print(f"  After email: {page.url}")

        # Fill password — use click + type to trigger Amazon's JS validation
        password_input = page.locator('#ap_password')
        if password_input.is_visible(timeout=5000):
            password_input.click()
            password_input.type(password, delay=20)
            page.wait_for_timeout(500)
            if debug:
                page.screenshot(path=str(self.data_dir / "debug_pre_submit.png"))
            page.locator('#signInSubmit').click()
            page.wait_for_load_state("networkidle")
            print(f"  After password: {page.url}")
            if debug:
                page.screenshot(path=str(self.data_dir / "debug_post_password.png"))

        # Attempt OTP if Amazon asks for it
        otp_input = page.locator('#auth-mfa-otpcode')
        if otp_input.is_visible(timeout=5000):
            otp = self._get_otp()
            if otp:
                otp_input.click()
                otp_input.type(otp, delay=20)
                page.wait_for_timeout(500)
                page.locator('#auth-signin-button').click()

        # Wait for dashboard regardless of which step we're at
        if "/ap/" in page.url:
            self._wait_for_dashboard(page)

    @staticmethod
    def _is_activities_api_url(url):
        """Return whether url targets the weekly activities endpoint."""
        if not isinstance(url, str):
            return False
        try:
            parsed = urlsplit(url)
            expected = urlsplit(ACTIVITIES_API)
        except ValueError:
            return False
        return (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
        ) == (
            expected.scheme,
            expected.netloc,
            expected.path,
        )

    @classmethod
    def _capture_initial_response(cls, response):
        """Build a persisted response record with minimal request metadata."""
        url = response.url
        if AJAX_PREFIX not in url:
            return None
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            return None

        try:
            body = response.json()
        except Exception:
            return None

        record = {
            "url": url,
            "status": response.status,
            "body": body,
        }
        if cls._is_activities_api_url(url):
            try:
                request_body = response.request.post_data_json
            except Exception:
                request_body = None
            if isinstance(request_body, dict):
                child_id = request_body.get("childDirectedId")
                if isinstance(child_id, str) and child_id.strip():
                    record["request_body"] = {"childDirectedId": child_id}
        return record

    @staticmethod
    def _select_children(children, child_filter=None):
        """Pick which children to fetch.

        Each child's activity is stored by date without a child label, so one
        data directory must hold exactly one child. With several children, a
        filter (first name or directedId) is required.
        """
        if child_filter:
            wanted = child_filter.strip().casefold()
            selected = {
                child_id: name
                for child_id, name in children.items()
                if child_id.casefold() == wanted or str(name).casefold() == wanted
            }
            if not selected:
                found = ", ".join(
                    f"{name} ({_short_id(child_id)})" for child_id, name in children.items()
                ) or "none"
                raise RuntimeError(
                    f"No child matched '{child_filter}'. Children found: {found}. "
                    "Run with --debug to print full child IDs."
                )
            return selected

        if len(children) > 1:
            names = ", ".join(str(name) for name in children.values())
            raise RuntimeError(
                f"Found {len(children)} children ({names}). Their reading would be mixed "
                "together. Run once per child with --child NAME --data-dir data/NAME."
            )
        return dict(children)

    @classmethod
    def _responses_for_children(cls, responses, children):
        """Drop page-load activity responses that belong to an unselected child.

        The dashboard page loads activity for its default child, which may not
        be the child being synced.
        """
        return [
            response for response in responses
            if not cls._is_activities_api_url(response.get("url"))
            or (response.get("request_body") or {}).get("childDirectedId") in children
        ]

    def fetch_reading_data(self, debug=False, start_date=None, child=None):
        """Logs in, navigates to dashboard, then calls the activities API
        for every week from the provided start_date (inclusive) to now."""
        tz = ZoneInfo(self.time_zone)
        fetch_start, mode = self._resolve_start_date(start_date, tz)
        if mode == "incremental":
            print(f"Fetch window starts at: {fetch_start.strftime(DATE_FORMAT)} (inclusive)")
        else:
            print(
                f"Fetch window starts at: {fetch_start.strftime(DATE_FORMAT)} (auto bootstrap: "
                f"last {BOOTSTRAP_LOOKBACK_DAYS} days)"
            )

        # We intercept the initial page load to discover the childDirectedId
        initial_responses = []

        def handle_response(response):
            record = self._capture_initial_response(response)
            if record is not None:
                initial_responses.append(record)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.on("response", handle_response)

            print("Navigating to Parent Dashboard...")
            page.goto(DASHBOARD_URL, wait_until="networkidle")

            # If we hit a sign-in page, log in
            if "/ap/signin" in page.url or "/ap/challenge" in page.url:
                print("Sign-in required...")
                self._do_login(page, debug=debug)
                page.wait_for_load_state("load")

            print(f"Landed on: {page.url}")
            print(f"Page title: {page.title()}")

            if debug:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                landing_path = self.data_dir / "debug_landing.png"
                page.screenshot(path=str(landing_path), full_page=True)
                print(f"Screenshot saved to {landing_path}")

            # Wait a moment for all initial API calls to fire
            page.wait_for_timeout(3000)

            if debug:
                print(f"\n--- Initial API responses: {len(initial_responses)} ---")
                for r in initial_responses:
                    print(f"  {r['status']} {r['url']}")

            # Extract CSRF token from cookies
            cookies = context.cookies()
            csrf_token = None
            for cookie in cookies:
                if cookie["name"] == "ft-panda-csrf-token":
                    csrf_token = cookie["value"]
                    break

            if not csrf_token:
                print("WARNING: Could not find CSRF token in cookies.")
                if debug:
                    print("Cookies found:")
                    for c in cookies:
                        print(f"  {c['name']}")

            # Discover children from the get-household response
            found_children = self._find_child_ids(initial_responses)

            print(
                "Found children: "
                + (
                    ", ".join(
                        f"{name} ({_short_id(child_id)})"
                        for child_id, name in found_children.items()
                    )
                    or "none"
                )
            )
            print(f"CSRF token: {'found' if csrf_token else 'NOT FOUND'}")
            if debug:
                for child_id, name in found_children.items():
                    print(f"  Child ID for config: {child_id} ({name})")

            # Fail loudly so a broken login never looks like a quiet day.
            if not csrf_token:
                raise RuntimeError(
                    "No CSRF token found; login probably did not reach the Parent Dashboard. "
                    "Re-run with --debug and check data/debug_landing.png."
                )
            if not found_children:
                raise RuntimeError(
                    "No children found on the Parent Dashboard. "
                    "Re-run with --debug and check data/debug_landing.png."
                )
            children = self._select_children(found_children, child)

            all_api_responses = self._responses_for_children(initial_responses, children)

            # Fetch historical data for each child

            for child_id, child_name in children.items():
                print(f"\nFetching history for {child_name} ({_short_id(child_id)})...")
                responses = self._fetch_all_weeks(
                    page, child_id, csrf_token, fetch_start, debug
                )
                all_api_responses.extend(responses)

            context.close()
            browser.close()

        return self._extract_reading_info(all_api_responses)

    @staticmethod
    def _resolve_start_date(start_date, tz):
        """Parse a start date string, falling back to an automatic bootstrap window."""
        fallback_start = datetime.now(tz).date() - timedelta(days=BOOTSTRAP_LOOKBACK_DAYS)
        if not start_date:
            return fallback_start, "bootstrap"

        try:
            parsed = datetime.strptime(start_date, DATE_FORMAT).date()
        except ValueError:
            print(
                f"WARNING: Invalid start_date '{start_date}', using automatic bootstrap start "
                f"{fallback_start.strftime(DATE_FORMAT)}"
            )
            return fallback_start, "bootstrap"

        return parsed, "incremental"

    def _find_child_ids(self, responses):
        """Extract child directedIds from household or activity API traffic."""
        child_ids = {}
        for resp in responses:
            if not isinstance(resp, dict):
                continue

            body = resp.get("body")
            if isinstance(body, dict):
                members = body.get("members", [])
                if isinstance(members, list):
                    for member in members:
                        if not isinstance(member, dict):
                            continue
                        child_id = member.get("directedId")
                        if (
                            member.get("role") == "CHILD"
                            and isinstance(child_id, str)
                            and child_id.strip()
                        ):
                            child_ids[child_id] = member.get("firstName", "Unknown")

            request_body = resp.get("request_body")
            if self._is_activities_api_url(resp.get("url")) and isinstance(
                request_body, dict
            ):
                child_id = request_body.get("childDirectedId")
                if isinstance(child_id, str) and child_id.strip():
                    child_ids.setdefault(child_id, "Unknown")
        return child_ids

    def _fetch_all_weeks(self, page, child_id, csrf_token, start_date, debug=False):
        """Call the activities API for every week from start_date to now."""
        tz = ZoneInfo(self.time_zone)
        start = datetime.combine(start_date, datetime.min.time(), tzinfo=tz)
        now = datetime.now(tz)

        if start >= now:
            print(f"  No fetch needed for {_short_id(child_id)}: start date is in the future")
            return []

        responses = []
        week_seconds = 7 * 86400
        current_start = int(start.timestamp())
        end_ts = int(now.timestamp())

        total_weeks = (end_ts - current_start) // week_seconds + 1
        week_num = 0

        while current_start < end_ts:
            current_end = min(current_start + week_seconds, end_ts)
            week_num += 1

            result = page.evaluate("""
                async ([url, childId, startTime, endTime, csrfToken, timeZone]) => {
                    try {
                        const resp = await fetch(url, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json;charset=UTF-8',
                                'x-amzn-csrf': csrfToken,
                                'Accept': 'application/json',
                            },
                            body: JSON.stringify({
                                childDirectedId: childId,
                                startTime: startTime,
                                endTime: endTime,
                                aggregationInterval: 86400,
                                timeZone: timeZone,
                            }),
                        });
                        const text = await resp.text();
                        let body;
                        try {
                            body = JSON.parse(text);
                        } catch {
                            body = { _raw_text: text.substring(0, 500) };
                        }
                        return { status: resp.status, body: body };
                    } catch (e) {
                        return { status: 0, body: { _error: e.message } };
                    }
                }
            """, [ACTIVITIES_API, child_id, current_start, current_end, csrf_token, self.time_zone])

            status = result["status"]
            body = result["body"]

            start_date = datetime.fromtimestamp(current_start, tz=tz).strftime("%Y-%m-%d")
            end_date = datetime.fromtimestamp(current_end, tz=tz).strftime("%Y-%m-%d")

            if status == 200:
                responses.append({
                    "url": ACTIVITIES_API,
                    "status": status,
                    "body": body,
                    "query": {
                        "childDirectedId": child_id,
                        "startTime": current_start,
                        "endTime": current_end,
                    },
                })
                print(f"  Week {week_num}/{total_weeks}: {start_date} to {end_date} - OK")
            else:
                print(f"  Week {week_num}/{total_weeks}: {start_date} to {end_date} - HTTP {status}")
                if debug:
                    print(f"    Response: {json.dumps(body)[:200]}")

            current_start = current_end
            # Small delay to avoid rate limiting
            time.sleep(0.3)

        return responses

    @staticmethod
    def _extract_completion_evidence(result, attrs):
        """Return only explicit completion evidence supplied by Amazon."""
        sources = (result, attrs)

        for source in sources:
            for key in (
                "completed",
                "isCompleted",
                "is_complete",
                "COMPLETED",
                "IS_COMPLETED",
                "BOOK_COMPLETED",
            ):
                value = source.get(key)
                if value is True or (isinstance(value, str) and value.lower() == "true"):
                    return {"type": "explicit_completed", "value": True}

        for source in sources:
            for key in (
                "percentComplete",
                "progressPercent",
                "percent_complete",
                "progress_percent",
                "PERCENT_COMPLETE",
                "PERCENT_READ",
                "PROGRESS_PERCENT",
            ):
                value = source.get(key)
                try:
                    percent = float(value)
                except (TypeError, ValueError):
                    continue
                if percent >= 100:
                    return {"type": "progress_percent", "value": 100}

        for source in sources:
            for key in (
                "completionStatus",
                "readingStatus",
                "completion_status",
                "reading_status",
                "COMPLETION_STATUS",
                "READING_STATUS",
                "STATUS",
            ):
                value = source.get(key)
                if isinstance(value, str) and value.lower() in {"completed", "finished"}:
                    return {"type": "explicit_status", "value": value.lower()}

        return None

    def _extract_reading_info(self, responses):
        """Parses the activityV2Data structure from API responses."""
        tz = ZoneInfo(self.time_zone)
        reading_activity = []
        completed_books = {}
        skipped_categories = set()

        for resp in responses:
            url = resp.get("url", "")
            body = resp.get("body", {})

            if "get-weekly-activities" not in url or not isinstance(body, dict):
                continue

            for category_data in body.get("activityV2Data", []):
                # Fire tablets also report apps, video, and web time; keep books only.
                category = category_data.get("category")
                if category is not None and category != BOOK_CATEGORY:
                    skipped_categories.add(str(category))
                    continue
                for interval in category_data.get("intervals", []):
                    start_ts = interval.get("startTime")
                    duration_secs = interval.get("aggregatedDuration", 0)
                    if start_ts is None or duration_secs == 0:
                        continue

                    date_str = datetime.fromtimestamp(start_ts, tz=tz).strftime("%Y-%m-%d")
                    books = []
                    for result in interval.get("aggregatedActivityResults", []):
                        attrs = result.get("attributes", {})
                        book = {
                            "title": attrs.get("TITLE", "Unknown"),
                            "asin": attrs.get("ORIGINAL_KEY"),
                            "duration_seconds": result.get("activityDuration", 0),
                            "sessions": result.get("activityCount", 0),
                            "thumbnail": attrs.get("THUMBNAIL_URL"),
                        }
                        books.append(book)

                        evidence = self._extract_completion_evidence(result, attrs)
                        if evidence:
                            completed_at = datetime.fromtimestamp(
                                result.get("lastActivityTimeStamp") or start_ts,
                                tz=tz,
                            ).strftime("%Y-%m-%d")
                            identity = book["asin"] or book["title"].casefold()
                            completed_books[identity] = {
                                "title": book["title"],
                                "asin": book["asin"],
                                "completion_status": "completed",
                                "completed_at": completed_at,
                                "evidence": evidence,
                            }

                    reading_activity.append({
                        "date": date_str,
                        "total_seconds": duration_secs,
                        "total_minutes": round(duration_secs / 60, 1),
                        "books": books,
                    })

        if skipped_categories:
            print(f"  Skipped non-book activity: {', '.join(sorted(skipped_categories))}")

        # Sort by date
        reading_activity.sort(key=lambda x: x["date"])

        return {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "reading_activity": reading_activity,
            "completed_books": sorted(
                completed_books.values(),
                key=lambda book: (book.get("completed_at") or "", book.get("title") or ""),
            ),
            "raw_responses": responses,
        }
