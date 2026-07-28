import io
import unittest
from contextlib import redirect_stderr

from main import build_parser, resolve_start_date


class StartDateArgumentTests(unittest.TestCase):
    def test_rejects_malformed_impossible_and_future_dates(self):
        parser = build_parser()

        for value in ("not-a-date", "2026-02-30", "2020-2-09", "9999-12-31"):
            with self.subTest(value=value):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        parser.parse_args(["--start-date", value])
                self.assertEqual(raised.exception.code, 2)

    def test_preserves_valid_date_in_canonical_format(self):
        args = build_parser().parse_args(["--start-date", "2020-02-29"])

        self.assertEqual(args.start_date, "2020-02-29")


class ResolveStartDateTests(unittest.TestCase):
    def test_explicit_start_date_overrides_latest_existing_date(self):
        activity = [{"date": "2026-07-26"}]

        self.assertEqual(resolve_start_date("2026-02-10", activity), "2026-02-10")

    def test_omitted_start_date_uses_latest_existing_date(self):
        activity = [{"date": "2026-07-25"}, {"date": "2026-07-26"}]
        args = build_parser().parse_args([])

        self.assertIsNone(args.start_date)
        self.assertEqual(resolve_start_date(args.start_date, activity), "2026-07-26")


if __name__ == "__main__":
    unittest.main()
