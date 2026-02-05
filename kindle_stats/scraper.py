import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

DASHBOARD_URL = "https://www.amazon.com/parentdashboard/activities/household-summary"
ACTIVITIES_API = "https://www.amazon.com/parentdashboard/ajax/get-weekly-activities-v2"
AJAX_PREFIX = "/parentdashboard/ajax/"


class KindleParentDashboard:
    def __init__(self, op_vault, op_item):
        self.op_vault = op_vault
        self.op_item = op_item

    @staticmethod
    def _op_read(ref):
        """Read a value using a 1Password secret reference."""
        result = subprocess.run(
            ["op", "read", ref],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"op read failed for '{ref}': {result.stderr.strip()}")
        return result.stdout.strip()

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

    def _do_login(self, page):
        """Handle Amazon sign-in using 1Password credentials."""
        print(f"Fetching credentials from 1Password item '{self.op_item}'...")
        email = self._op_read(f"op://{self.op_vault}/{self.op_item}/username")
        password = self._op_read(f"op://{self.op_vault}/{self.op_item}/password")

        Path("data").mkdir(exist_ok=True)

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
            page.screenshot(path="data/debug_pre_submit.png")
            page.locator('#signInSubmit').click()
            page.wait_for_load_state("networkidle")
            print(f"  After password: {page.url}")
            page.screenshot(path="data/debug_post_password.png")

        # Attempt OTP if Amazon asks for it
        otp_input = page.locator('#auth-mfa-otpcode')
        if otp_input.is_visible(timeout=5000):
            result = subprocess.run(
                ["op", "item", "get", self.op_item, "--otp"],
                capture_output=True, text=True,
            )
            otp = result.stdout.strip() if result.returncode == 0 else None
            if otp:
                print("  Filling OTP from 1Password...")
                otp_input.click()
                otp_input.type(otp, delay=20)
                page.wait_for_timeout(500)
                page.locator('#auth-signin-button').click()

        # Wait for dashboard regardless of which step we're at
        if "/ap/" in page.url:
            self._wait_for_dashboard(page)

    def fetch_reading_data(self, debug=False):
        """Logs in, navigates to dashboard, then calls the activities API
        for every week from January 2025 to now."""
        # We intercept the initial page load to discover the childDirectedId
        initial_responses = []

        def handle_response(response):
            url = response.url
            if AJAX_PREFIX not in url:
                return
            content_type = response.headers.get("content-type", "")
            if "json" not in content_type:
                return
            try:
                body = response.json()
                initial_responses.append({
                    "url": url,
                    "status": response.status,
                    "body": body,
                })
            except Exception:
                pass

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
                self._do_login(page)
                page.wait_for_load_state("networkidle")

            print(f"Landed on: {page.url}")
            print(f"Page title: {page.title()}")

            if debug:
                Path("data").mkdir(exist_ok=True)
                page.screenshot(path="data/debug_landing.png", full_page=True)
                print("Screenshot saved to data/debug_landing.png")

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
            children = self._find_child_ids(initial_responses)

            print(f"Found children: {children or 'none'}")
            print(f"CSRF token: {'found' if csrf_token else 'NOT FOUND'}")

            # Fetch historical data for each child
            all_api_responses = list(initial_responses)

            if children and csrf_token:
                for child_id, child_name in children.items():
                    print(f"\nFetching history for {child_name} ({child_id})...")
                    responses = self._fetch_all_weeks(
                        page, child_id, csrf_token, debug
                    )
                    all_api_responses.extend(responses)
            elif not csrf_token:
                print("\nNo CSRF token found — cannot fetch historical data.")
            elif not children:
                print("\nNo children found in household response.")

            context.close()
            browser.close()

        return self._extract_reading_info(all_api_responses)

    def _find_child_ids(self, responses):
        """Extract child directedIds from the get-household API response."""
        child_ids = {}
        for resp in responses:
            body = resp.get("body", {})
            if "members" not in body:
                continue
            for member in body["members"]:
                if member.get("role") == "CHILD" and member.get("directedId"):
                    child_ids[member["directedId"]] = member.get("firstName", "Unknown")
        return child_ids

    def _fetch_all_weeks(self, page, child_id, csrf_token, debug=False):
        """Call the activities API for every week from Jan 2025 to now."""
        tz = ZoneInfo("America/Los_Angeles")
        # Start from January 1, 2025
        start = datetime(2025, 1, 1, tzinfo=tz)
        now = datetime.now(tz)

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
                async ([url, childId, startTime, endTime, csrfToken]) => {
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
                                timeZone: 'America/Los_Angeles',
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
            """, [ACTIVITIES_API, child_id, current_start, current_end, csrf_token])

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

    def _extract_reading_info(self, responses):
        """Parses the activityV2Data structure from API responses."""
        tz = ZoneInfo("America/Los_Angeles")
        reading_activity = []

        for resp in responses:
            url = resp.get("url", "")
            body = resp.get("body", {})

            if "get-weekly-activities" not in url or not isinstance(body, dict):
                continue

            for category_data in body.get("activityV2Data", []):
                for interval in category_data.get("intervals", []):
                    start_ts = interval.get("startTime")
                    duration_secs = interval.get("aggregatedDuration", 0)
                    if start_ts is None or duration_secs == 0:
                        continue

                    date_str = datetime.fromtimestamp(start_ts, tz=tz).strftime("%Y-%m-%d")
                    books = []
                    for result in interval.get("aggregatedActivityResults", []):
                        attrs = result.get("attributes", {})
                        books.append({
                            "title": attrs.get("TITLE", "Unknown"),
                            "asin": attrs.get("ORIGINAL_KEY"),
                            "duration_seconds": result.get("activityDuration", 0),
                            "sessions": result.get("activityCount", 0),
                            "thumbnail": attrs.get("THUMBNAIL_URL"),
                        })

                    reading_activity.append({
                        "date": date_str,
                        "total_seconds": duration_secs,
                        "total_minutes": round(duration_secs / 60, 1),
                        "books": books,
                    })

        # Sort by date
        reading_activity.sort(key=lambda x: x["date"])

        return {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "reading_activity": reading_activity,
            "raw_responses": responses,
        }
