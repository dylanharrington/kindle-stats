import unittest

from kindle_stats.scraper import KindleParentDashboard


class FakeRequest:
    def __init__(self, post_data_json):
        self._post_data_json = post_data_json
        self.read_count = 0

    @property
    def post_data_json(self):
        self.read_count += 1
        return self._post_data_json


class FakeResponse:
    def __init__(self, url, post_data_json):
        self.url = url
        self.status = 200
        self.headers = {"content-type": "application/json"}
        self.request = FakeRequest(post_data_json)

    def json(self):
        return {"activityV2Data": []}


class CaptureInitialResponseTests(unittest.TestCase):
    def test_capture_limits_request_metadata_to_weekly_child_id(self):
        weekly = FakeResponse(
            "https://www.amazon.com/parentdashboard/ajax/get-weekly-activities-v2?week=current",
            {
                "childDirectedId": "child-123",
                "startTime": 1,
                "unrelatedSecret": "must-not-persist",
            },
        )
        unrelated = FakeResponse(
            "https://www.amazon.com/parentdashboard/ajax/get-household",
            {
                "childDirectedId": "wrong-child",
                "unrelatedSecret": "must-not-persist",
            },
        )

        dashboard = KindleParentDashboard.__new__(KindleParentDashboard)
        weekly_record = dashboard._capture_initial_response(weekly)
        unrelated_record = dashboard._capture_initial_response(unrelated)

        self.assertEqual(
            weekly_record["request_body"],
            {"childDirectedId": "child-123"},
        )
        self.assertNotIn("request_body", unrelated_record)
        self.assertEqual(weekly.request.read_count, 1)
        self.assertEqual(unrelated.request.read_count, 0)

        for invalid_child_id in (None, "", "   ", 123, [], {}):
            with self.subTest(invalid_child_id=invalid_child_id):
                invalid = FakeResponse(
                    "https://www.amazon.com/parentdashboard/ajax/get-weekly-activities-v2",
                    {
                        "childDirectedId": invalid_child_id,
                        "unrelatedSecret": "must-not-persist",
                    },
                )
                invalid_record = dashboard._capture_initial_response(invalid)
                self.assertIsInstance(invalid_record, dict)
                self.assertNotIn("request_body", invalid_record or {})


class FindChildIdsTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = KindleParentDashboard.__new__(KindleParentDashboard)

    def test_ignores_malformed_json_shapes_and_non_string_ids(self):
        responses = [
            {"body": None},
            {"body": []},
            {"body": "not-an-object"},
            {"body": 42},
            {"body": {"members": None}},
            {"body": {"members": "not-a-list"}},
            {
                "url": "https://www.amazon.com/parentdashboard/ajax/get-household",
                "body": {
                    "members": [
                        None,
                        [],
                        "not-an-object",
                        {"role": "CHILD", "directedId": None},
                        {"role": "CHILD", "directedId": 123},
                        {"role": "CHILD", "directedId": ""},
                        {
                            "role": "CHILD",
                            "directedId": "child-household",
                            "firstName": "Alice",
                        },
                    ]
                },
                "request_body": [],
            },
            {
                "url": (
                    "https://www.amazon.com/parentdashboard/ajax/"
                    "get-weekly-activities-v2"
                ),
                "body": {},
                "request_body": None,
            },
            {
                "url": (
                    "https://www.amazon.com/parentdashboard/ajax/"
                    "get-weekly-activities-v2"
                ),
                "body": {},
                "request_body": "not-an-object",
            },
            {
                "url": (
                    "https://www.amazon.com/parentdashboard/ajax/"
                    "get-weekly-activities-v2"
                ),
                "body": {},
                "request_body": {"childDirectedId": "   "},
            },
            {
                "url": (
                    "https://www.amazon.com/parentdashboard/ajax/"
                    "get-weekly-activities-v2"
                ),
                "body": {},
                "request_body": {"childDirectedId": 123},
            },
            {
                "url": (
                    "https://www.amazon.com/parentdashboard/ajax/"
                    "get-weekly-activities-v2"
                ),
                "body": {},
                "request_body": {"childDirectedId": []},
            },
        ]

        self.assertEqual(
            self.dashboard._find_child_ids(responses),
            {"child-household": "Alice"},
        )

    def test_uses_child_id_from_weekly_activity_request_when_household_members_are_absent(self):
        responses = [
            {
                "url": "https://www.amazon.com/parentdashboard/ajax/get-weekly-activities-v2",
                "request_body": {"childDirectedId": "child-123"},
                "body": {"activityV2Data": []},
            }
        ]

        dashboard = KindleParentDashboard.__new__(KindleParentDashboard)
        self.assertEqual(
            dashboard._find_child_ids(responses),
            {"child-123": "Unknown"},
        )

    def test_restricts_fallback_to_exact_weekly_url_and_preserves_household_name(self):
        responses = [
            {
                "url": (
                    "https://www.amazon.com/parentdashboard/ajax/"
                    "get-weekly-activities-v2?week=current"
                ),
                "request_body": {"childDirectedId": "child-123"},
                "body": {"activityV2Data": []},
            },
            {
                "url": "https://www.amazon.com/parentdashboard/ajax/get-household",
                "request_body": {"childDirectedId": "wrong-endpoint"},
                "body": {
                    "members": [
                        {
                            "role": "CHILD",
                            "directedId": "child-123",
                            "firstName": "Alice",
                        }
                    ]
                },
            },
            {
                "url": (
                    "https://www.amazon.com/parentdashboard/ajax/"
                    "get-weekly-activities-v2-extra"
                ),
                "request_body": {"childDirectedId": "wrong-path"},
                "body": {},
            },
            {
                "url": (
                    "https://example.com/parentdashboard/ajax/"
                    "get-weekly-activities-v2"
                ),
                "request_body": {"childDirectedId": "wrong-host"},
                "body": {},
            },
        ]

        self.assertEqual(
            self.dashboard._find_child_ids(responses),
            {"child-123": "Alice"},
        )


if __name__ == "__main__":
    unittest.main()
