#!/usr/bin/env python3
"""X API wrapper for OAuth1.0a-authenticated tweet search."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from typing import Any

import requests
try:
    from requests_oauthlib import OAuth1Session
    HAS_REQUESTS_OAUTHLIB = True
except ImportError:
    OAuth1Session = None  # type: ignore[assignment]
    HAS_REQUESTS_OAUTHLIB = False

BASE_URL = "https://api.x.com/2/"
REQUEST_TIMEOUT = 15

REQUIRED_ENV_VARS = (
    "X_API_KEY",
    "X_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
)

TWEET_FIELDS = "text,created_at,public_metrics,author_id,conversation_id"
EXPANSIONS = "author_id"
USER_FIELDS = "username,name"


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def format_search_query(query: str) -> str:
    """Normalize query and enforce baseline operators."""
    normalized = " ".join((query or "").split())
    if "-is:retweet" not in normalized:
        normalized = f"{normalized} -is:retweet".strip()
    if re.search(r"\blang:[a-zA-Z]{2,}\b", normalized) is None:
        normalized = f"{normalized} lang:en".strip()
    return normalized


class XClient:
    """Lightweight X API client for search-focused operations."""

    def __init__(self):
        """Init OAuth1 session from env vars."""
        missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Missing required environment variables: {joined}")

        if HAS_REQUESTS_OAUTHLIB:
            self.session = OAuth1Session(
                os.environ["X_API_KEY"],
                client_secret=os.environ["X_API_SECRET"],
                resource_owner_key=os.environ["X_ACCESS_TOKEN"],
                resource_owner_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
            )
        else:
            # Keeps tests/imports runnable in minimal environments.
            self.session = requests.Session()
            print(
                "warning: requests-oauthlib not installed; requests will be unsigned",
                file=sys.stderr,
            )

    @staticmethod
    def _rate_limit_from_headers(headers: Any) -> dict[str, int | None]:
        return {
            "limit": _to_int(getattr(headers, "get", lambda *_: None)("x-rate-limit-limit"), None),
            "remaining": _to_int(getattr(headers, "get", lambda *_: None)("x-rate-limit-remaining"), None),
            "reset": _to_int(getattr(headers, "get", lambda *_: None)("x-rate-limit-reset"), None),
        }

    def _log_rate_limit(self, endpoint: str, headers: Any) -> None:
        rate = self._rate_limit_from_headers(headers)
        if rate["remaining"] is None:
            return

        msg = f"rate limit {endpoint}: remaining={rate['remaining']}"
        if rate["limit"] is not None:
            msg += f"/{rate['limit']}"
        if rate["reset"]:
            reset_time = datetime.fromtimestamp(rate["reset"], tz=UTC).isoformat()
            msg += f" reset={reset_time}"
        print(msg, file=sys.stderr)

        if rate["remaining"] < 50:
            print("warning: X rate limit is low (<50 remaining)", file=sys.stderr)

    def _request_json(self, endpoint: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, requests.Response | None]:
        url = f"{BASE_URL}{endpoint.lstrip('/')}"
        try:
            response = self.session.get(url, params=params or {}, timeout=REQUEST_TIMEOUT)
        except requests.Timeout:
            print(f"warning: request timeout for {endpoint}", file=sys.stderr)
            return None, None
        except requests.RequestException as exc:
            print(f"warning: request failed for {endpoint}: {exc}", file=sys.stderr)
            return None, None

        self._log_rate_limit(endpoint, response.headers)

        if response.status_code == 429:
            print("warning: X API rate limit exceeded (429)", file=sys.stderr)
            return None, response

        if response.status_code >= 400:
            err_text = response.text.strip().replace("\n", " ")[:300]
            print(
                f"warning: X API error for {endpoint}: HTTP {response.status_code} {err_text}",
                file=sys.stderr,
            )
            return None, response

        try:
            payload = response.json()
        except ValueError:
            print(f"warning: invalid JSON response from {endpoint}", file=sys.stderr)
            return None, response

        return payload, response

    @staticmethod
    def _build_user_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        users = payload.get("includes", {}).get("users", [])
        lookup: dict[str, dict[str, Any]] = {}
        if isinstance(users, list):
            for user in users:
                if not isinstance(user, dict):
                    continue
                user_id = str(user.get("id", ""))
                if user_id:
                    lookup[user_id] = user
        return lookup

    @staticmethod
    def _parse_tweet(tweet: dict[str, Any], user_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
        tweet_id = str(tweet.get("id", ""))
        author_id = str(tweet.get("author_id", ""))
        user = user_lookup.get(author_id, {})

        author_username = str(user.get("username") or "unknown")
        author_name = str(user.get("name") or "")

        metrics = tweet.get("public_metrics") or {}
        parsed_metrics = {
            "like_count": _to_int(metrics.get("like_count"), 0),
            "retweet_count": _to_int(metrics.get("retweet_count"), 0),
            "reply_count": _to_int(metrics.get("reply_count"), 0),
            "impression_count": _to_int(metrics.get("impression_count"), 0),
        }

        return {
            "id": tweet_id,
            "text": str(tweet.get("text") or ""),
            "author_username": author_username,
            "author_name": author_name,
            "created_at": str(tweet.get("created_at") or ""),
            "metrics": parsed_metrics,
            "url": f"https://x.com/{author_username}/status/{tweet_id}" if tweet_id else "",
        }

    @classmethod
    def _parse_search_payload(cls, payload: dict[str, Any]) -> list[dict[str, Any]]:
        user_lookup = cls._build_user_lookup(payload)
        tweets = payload.get("data", [])
        if not isinstance(tweets, list):
            return []
        parsed: list[dict[str, Any]] = []
        for tweet in tweets:
            if isinstance(tweet, dict):
                parsed.append(cls._parse_tweet(tweet, user_lookup))
        return parsed

    def search_recent(self, query: str, max_results: int = 10, sort_order: str = "relevancy") -> list[dict[str, Any]]:
        """Search recent tweets."""
        if not query or not query.strip():
            print("warning: empty query", file=sys.stderr)
            return []

        if sort_order not in {"relevancy", "recency"}:
            print("warning: invalid sort_order, fallback to relevancy", file=sys.stderr)
            sort_order = "relevancy"

        max_results = max(10, min(100, int(max_results)))
        query = format_search_query(query)

        payload, _response = self._request_json(
            "tweets/search/recent",
            params={
                "query": query,
                "max_results": max_results,
                "sort_order": sort_order,
                "tweet.fields": TWEET_FIELDS,
                "expansions": EXPANSIONS,
                "user.fields": USER_FIELDS,
            },
        )
        if payload is None:
            return []

        return self._parse_search_payload(payload)

    def get_tweet(self, tweet_id: str) -> dict[str, Any] | None:
        """Get a single tweet by ID. Same fields as search."""
        if not tweet_id.strip():
            print("warning: empty tweet_id", file=sys.stderr)
            return None

        payload, _response = self._request_json(
            f"tweets/{tweet_id}",
            params={
                "tweet.fields": TWEET_FIELDS,
                "expansions": EXPANSIONS,
                "user.fields": USER_FIELDS,
            },
        )
        if payload is None:
            return None

        tweet = payload.get("data")
        if not isinstance(tweet, dict):
            return None

        user_lookup = self._build_user_lookup(payload)
        return self._parse_tweet(tweet, user_lookup)

    def status(self) -> dict[str, Any]:
        """Check auth + search endpoint availability and surface rate limit info."""
        payload, response = self._request_json(
            "tweets/search/recent",
            params={
                "query": "AI -is:retweet lang:en",
                "max_results": 10,
                "sort_order": "relevancy",
                "tweet.fields": TWEET_FIELDS,
                "expansions": EXPANSIONS,
                "user.fields": USER_FIELDS,
            },
        )

        if response is None:
            return {
                "ok": False,
                "error": "request_failed",
            }

        info = {
            "ok": payload is not None,
            "http_status": response.status_code,
            "rate_limit": self._rate_limit_from_headers(response.headers),
            "results": len(payload.get("data", [])) if isinstance(payload, dict) else 0,
        }
        if payload is None:
            info["error"] = "api_error"
        return info


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="X API wrapper")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="Search recent tweets")
    search.add_argument("query", help="Search query")
    search.add_argument("--max-results", type=int, default=10)
    search.add_argument("--sort", default="relevancy", choices=["relevancy", "recency"])

    tweet = sub.add_parser("tweet", help="Get tweet by ID")
    tweet.add_argument("tweet_id", help="Tweet ID")

    sub.add_parser("status", help="Check auth and rate limit")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        client = XClient()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.command == "search":
        result = client.search_recent(args.query, max_results=args.max_results, sort_order=args.sort)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "tweet":
        result = client.get_tweet(args.tweet_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "status":
        print(json.dumps(client.status(), ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
