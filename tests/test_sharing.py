import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from kindle_stats import config as config_module
from kindle_stats import scraper as scraper_module
from kindle_stats.scraper import KindleParentDashboard
from kindle_stats.summary import format_summary, summarize
from main import build_post_sync_command


class SelectChildrenTests(unittest.TestCase):
    children = {"amzn1.account.AAA111": "Alice", "amzn1.account.BBB222": "Ben"}

    def test_single_child_needs_no_filter(self):
        only = {"amzn1.account.AAA111": "Unknown"}
        self.assertEqual(KindleParentDashboard._select_children(only), only)

    def test_multiple_children_without_filter_refuses_to_mix(self):
        with self.assertRaisesRegex(RuntimeError, "--child"):
            KindleParentDashboard._select_children(self.children)

    def test_filter_matches_name_case_insensitively_or_exact_id(self):
        self.assertEqual(
            KindleParentDashboard._select_children(self.children, "alice"),
            {"amzn1.account.AAA111": "Alice"},
        )
        self.assertEqual(
            KindleParentDashboard._select_children(self.children, "amzn1.account.BBB222"),
            {"amzn1.account.BBB222": "Ben"},
        )

    def test_unmatched_filter_lists_children_without_full_ids(self):
        with self.assertRaises(RuntimeError) as raised:
            KindleParentDashboard._select_children(self.children, "Cara")
        message = str(raised.exception)
        self.assertIn("Alice", message)
        self.assertNotIn("amzn1.account.AAA111", message)


class InitialResponseFilterTests(unittest.TestCase):
    def test_keeps_only_selected_childs_page_load_activity(self):
        url = scraper_module.ACTIVITIES_API
        responses = [
            {"url": url, "request_body": {"childDirectedId": "kid-a"}, "body": {}},
            {"url": url, "request_body": {"childDirectedId": "kid-b"}, "body": {}},
            {"url": url, "body": {}},
            {"url": "https://www.amazon.com/parentdashboard/ajax/get-household", "body": {}},
        ]
        kept = KindleParentDashboard._responses_for_children(responses, {"kid-b": "Ben"})
        self.assertEqual(
            [(r["url"], (r.get("request_body") or {}).get("childDirectedId")) for r in kept],
            [(url, "kid-b"), ("https://www.amazon.com/parentdashboard/ajax/get-household", None)],
        )


class BookCategoryTests(unittest.TestCase):
    def test_keeps_books_and_skips_other_fire_tablet_categories(self):
        def category(name, title, seconds):
            body = {
                "intervals": [{
                    "startTime": 1792911600,
                    "aggregatedDuration": seconds,
                    "aggregatedActivityResults": [{
                        "activityDuration": seconds,
                        "activityCount": 1,
                        "attributes": {"TITLE": title, "ORIGINAL_KEY": title.upper()},
                    }],
                }],
            }
            if name is not None:
                body["category"] = name
            return body

        responses = [{
            "url": scraper_module.ACTIVITIES_API,
            "body": {"activityV2Data": [
                category("BOOK", "A Book", 600),
                category("APP", "A Game", 900),
                category(None, "Uncategorized Book", 300),
            ]},
        }]
        dashboard = KindleParentDashboard()
        with redirect_stdout(io.StringIO()) as out:
            data = dashboard._extract_reading_info(responses)

        titles = [book["title"] for entry in data["reading_activity"] for book in entry["books"]]
        self.assertEqual(sorted(titles), ["A Book", "Uncategorized Book"])
        self.assertIn("APP", out.getvalue())


class CredentialHelperTests(unittest.TestCase):
    def test_missing_cli_is_treated_as_lookup_failure(self):
        with mock.patch.object(scraper_module.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(KindleParentDashboard._bw_get_field("Amazon", ".login.password"))
            self.assertIsNone(KindleParentDashboard(bw_item="Amazon", op_item="Amazon")._get_otp())

    def test_op_read_uses_plain_op_unless_auto_approve_is_opted_in(self):
        completed = mock.Mock(returncode=0, stdout="value\n", stderr="")
        with mock.patch.object(scraper_module.subprocess, "run", return_value=completed) as run:
            KindleParentDashboard(op_vault="V", op_item="I")._op_read("op://V/I/password")
            self.assertEqual(run.call_args.args[0], ["op", "read", "op://V/I/password"])

            KindleParentDashboard(op_auto_approve=True)._op_read("op://V/I/password")
            self.assertTrue(run.call_args.args[0][0].endswith("op_read_auto.sh"))


class FakeLocator:
    def __init__(self, visible):
        self.visible = visible
        self.first = self

    def is_visible(self, timeout=None):
        return self.visible

    def click(self):
        pass

    def fill(self, value):
        pass

    def type(self, value, delay=None):
        pass


class FakePage:
    url = "https://www.amazon.com/parentdashboard/activities/household-summary"

    def __init__(self):
        self.screenshots = []

    def locator(self, selector):
        return FakeLocator(selector in ("#ap_email", "#ap_password"))

    def wait_for_timeout(self, ms):
        pass

    def wait_for_load_state(self, state):
        pass

    def screenshot(self, path, **kwargs):
        self.screenshots.append(path)


class LoginScreenshotTests(unittest.TestCase):
    def test_login_screenshots_only_in_debug_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard = KindleParentDashboard(bw_item="Amazon", data_dir=Path(tmp))
            with mock.patch.object(dashboard, "_get_credential", return_value="x"), \
                    redirect_stdout(io.StringIO()):
                quiet_page = FakePage()
                dashboard._do_login(quiet_page)
                debug_page = FakePage()
                dashboard._do_login(debug_page, debug=True)

        self.assertEqual(quiet_page.screenshots, [])
        self.assertEqual(len(debug_page.screenshots), 2)
        self.assertTrue(all(path.startswith(tmp) for path in debug_page.screenshots))


class PostSyncTests(unittest.TestCase):
    def test_unset_hook_does_nothing(self):
        self.assertIsNone(build_post_sync_command(None, "data/reading_data.json"))

    def test_expands_reading_data_placeholder_and_cwd(self):
        argv, cwd = build_post_sync_command(
            {"command": ["node", "sync.mjs", "--input", "{reading_data}"], "cwd": "~/site"},
            "data/reading_data.json",
        )
        self.assertEqual(argv[:3], ["node", "sync.mjs", "--input"])
        self.assertTrue(Path(argv[3]).is_absolute())
        self.assertTrue(argv[3].endswith("data/reading_data.json"))
        self.assertEqual(cwd, str(Path.home() / "site"))

    def test_rejects_shell_strings(self):
        with self.assertRaises(ValueError):
            build_post_sync_command({"command": "node sync.mjs"}, "data/reading_data.json")


class ConfigTests(unittest.TestCase):
    def test_non_interactive_run_without_config_stops_with_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "config.json"
            with mock.patch.object(config_module, "CONFIG_PATH", missing), \
                    mock.patch.object(config_module.sys.stdin, "isatty", return_value=False):
                with self.assertRaises(SystemExit) as raised:
                    config_module.get_config()
        self.assertIn("config.example.json", str(raised.exception))

    def test_existing_config_is_used_without_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"login": "manual"}))
            with mock.patch.object(config_module, "CONFIG_PATH", path), \
                    mock.patch("builtins.input", side_effect=AssertionError("prompted")):
                self.assertEqual(config_module.get_config(), {"login": "manual"})

    def test_example_config_is_valid_json(self):
        example = Path(config_module.REPO_ROOT) / "config.example.json"
        self.assertIsInstance(json.loads(example.read_text()), dict)


class SummaryTests(unittest.TestCase):
    data = {
        "last_updated": "2026-10-27T17:30:00",
        "reading_activity": [
            {"date": "2026-10-01", "total_seconds": 3600, "books": [
                {"title": "Old Book", "asin": "B1", "duration_seconds": 3600},
            ]},
            {"date": "2026-10-25", "total_seconds": 1800, "books": [
                {"title": "New Book", "asin": "B2", "duration_seconds": 1200},
                {"title": "Old Book", "asin": "B1", "duration_seconds": 600},
            ]},
        ],
        "completed_books": [{"title": "Old Book", "asin": "B1", "completed_at": "2026-10-25"}],
    }

    def test_window_current_book_and_totals(self):
        summary = summarize(self.data, days=7, today=date(2026, 10, 27))

        self.assertEqual(summary["window"]["hours"], 0.5)
        self.assertEqual(summary["window"]["days_with_reading"], 1)
        self.assertEqual([b["title"] for b in summary["window"]["books"]], ["New Book", "Old Book"])
        self.assertEqual(summary["current_book"]["title"], "New Book")
        self.assertEqual(summary["all_time"]["hours"], 1.5)
        self.assertEqual(summary["all_time"]["books"], 2)
        self.assertEqual(summary["all_time"]["completed_books"], 1)
        self.assertIn("New Book: 20 min", format_summary(summary))

    def test_empty_data(self):
        summary = summarize({}, today=date(2026, 10, 27))
        self.assertIsNone(summary["current_book"])
        self.assertIn("No reading activity", format_summary(summary))


if __name__ == "__main__":
    unittest.main()
