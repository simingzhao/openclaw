import os
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.x_api import XClient, format_search_query


class TestXApi(unittest.TestCase):
    def setUp(self) -> None:
        self.env = {
            "X_API_KEY": "k",
            "X_API_SECRET": "s",
            "X_ACCESS_TOKEN": "t",
            "X_ACCESS_TOKEN_SECRET": "ts",
        }
        self.env_patcher = patch.dict(os.environ, self.env, clear=False)
        self.env_patcher.start()
        self.client = XClient()

    def tearDown(self) -> None:
        self.env_patcher.stop()

    def test_query_formatting_auto_append(self) -> None:
        self.assertEqual(
            format_search_query("AI agents"),
            "AI agents -is:retweet lang:en",
        )
        self.assertEqual(
            format_search_query("vibe coding -is:retweet lang:en"),
            "vibe coding -is:retweet lang:en",
        )

    def test_response_parsing(self) -> None:
        payload = {
            "data": [
                {
                    "id": "1",
                    "text": "hello",
                    "author_id": "u1",
                    "created_at": "2026-02-27T00:00:00Z",
                    "public_metrics": {
                        "like_count": 3,
                        "retweet_count": 2,
                        "reply_count": 1,
                        "impression_count": 100,
                    },
                }
            ],
            "includes": {
                "users": [
                    {
                        "id": "u1",
                        "username": "alice",
                        "name": "Alice",
                    }
                ]
            },
        }

        with patch.object(self.client, "_request_json", return_value=(payload, Mock())):
            rows = self.client.search_recent("AI agents", max_results=10)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], "1")
        self.assertEqual(row["author_username"], "alice")
        self.assertEqual(row["author_name"], "Alice")
        self.assertEqual(row["metrics"]["like_count"], 3)
        self.assertEqual(row["url"], "https://x.com/alice/status/1")

    def test_error_handling_rate_limit_and_network(self) -> None:
        response_429 = Mock()
        response_429.status_code = 429
        response_429.headers = {
            "x-rate-limit-limit": "450",
            "x-rate-limit-remaining": "0",
            "x-rate-limit-reset": "1700000000",
        }
        response_429.text = "rate limit"
        response_429.json.side_effect = ValueError("no json")

        with patch.object(self.client.session, "get", return_value=response_429):
            rows = self.client.search_recent("AI agents")
            self.assertEqual(rows, [])

        with patch.object(self.client.session, "get", side_effect=requests.RequestException("boom")):
            rows = self.client.search_recent("AI agents")
            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
