import unittest

from scripts.sense_scan import (
    _parse_analysis,
    _render_markdown,
    dedup_tweets,
    filter_excluded_tweets,
)


class TestSenseScan(unittest.TestCase):
    def test_exclude_keyword_filtering(self) -> None:
        tweets = [
            {"id": "1", "text": "AI agents are improving quickly"},
            {"id": "2", "text": "Bitcoin giveaway now"},
            {"id": "3", "text": "New Claude Code workflow"},
        ]
        kept, excluded = filter_excluded_tweets(tweets)
        self.assertEqual(excluded, 1)
        self.assertEqual([t["id"] for t in kept], ["1", "3"])

    def test_dedup_logic(self) -> None:
        seen = {"1", "2"}
        tweets = [
            {"id": "2", "text": "already seen"},
            {"id": "3", "text": "new"},
            {"id": "4", "text": "new2"},
            {"id": "4", "text": "duplicate in this run"},
        ]
        kept, next_seen, dropped = dedup_tweets(tweets, seen)
        self.assertEqual([row["id"] for row in kept], ["3", "4"])
        self.assertEqual(dropped, 2)
        self.assertIn("4", next_seen)

    def test_parse_analysis_json(self) -> None:
        text = """
```json
{
  "scan_date": "2026-02-27",
  "scan_time": "11:30",
  "total_tweets_analyzed": 10,
  "trends": [],
  "top_tweets": [],
  "topic_clusters": [],
  "new_keywords": {"x": ["agentic workflow"]},
  "executive_summary": "summary"
}
```
"""
        parsed = _parse_analysis(text, "gemini-test")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["scan_date"], "2026-02-27")
        self.assertEqual(parsed["_model_used"], "gemini-test")

    def test_markdown_rendering(self) -> None:
        analysis = {
            "scan_date": "2026-02-27",
            "scan_time": "12:00",
            "_model_used": "gemini-test",
            "executive_summary": "Signals are heating up.",
            "trends": [
                {
                    "signal": "Agentic IDE adoption",
                    "strength": "hot",
                    "category": "product_launch",
                    "evidence": "Multiple launches with high engagement",
                }
            ],
            "top_tweets": [
                {
                    "text": "Big launch",
                    "author": "dev",
                    "likes": 10,
                    "retweets": 2,
                    "replies": 1,
                    "category": "product_launch",
                    "insight": "High signal",
                }
            ],
            "topic_clusters": [
                {
                    "topic": "AI agents",
                    "tweet_count": 5,
                    "key_points": ["point1", "point2"],
                    "sentiment": "positive",
                }
            ],
            "new_keywords": {"x": ["agentic IDE"]},
        }
        markdown = _render_markdown(analysis)
        self.assertIn("# X Sense Scan Report - 2026-02-27", markdown)
        self.assertIn("## Trends", markdown)
        self.assertIn("## New Keywords", markdown)
        self.assertIn("agentic IDE", markdown)


if __name__ == "__main__":
    unittest.main()
