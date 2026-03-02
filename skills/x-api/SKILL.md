---
name: x-api
description: X/Twitter API wrapper for searching tweets, fetching single tweets, and checking auth/rate limit status. Lightweight CLI for quick X searches without the full x-ops patrol pipeline.
metadata:
  openclaw:
    emoji: "🐦"
    requires:
      env: ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
    primaryEnv: "X_API_KEY"
---

# X API

Lightweight X/Twitter API wrapper. Use for quick searches and tweet lookups without spinning up the full x-ops sense scan pipeline.

## Setup

Environment variables (OAuth 1.0a User Context):

```bash
export X_API_KEY="..."
export X_API_SECRET="..."
export X_ACCESS_TOKEN="..."
export X_ACCESS_TOKEN_SECRET="..."
```

Python dependencies (already in venv):

```bash
pip install requests requests-oauthlib
```

## Usage

```bash
VENV="/Users/simingzhao/Desktop/openclaw/skills/x-api/.venv/bin/python3"
XA="$VENV /Users/simingzhao/Desktop/openclaw/skills/x-api/scripts/x_api.py"

# Search recent tweets (default: 10 results, sorted by relevancy)
$XA search "AI agents"

# More results, sorted by recency
$XA search "vibe coding" --max-results 20 --sort recency

# Get a specific tweet by ID
$XA tweet "1234567890123456789"

# Check auth status and rate limits
$XA status
```

## Commands

| Command          | Description                                           |
| ---------------- | ----------------------------------------------------- |
| `search <query>` | Search recent tweets. Auto-adds `-is:retweet lang:en` |
| `tweet <id>`     | Fetch a single tweet by ID                            |
| `status`         | Check OAuth auth + rate limit info                    |

## Search Options

| Flag              | Description                | Default   |
| ----------------- | -------------------------- | --------- |
| `--max-results N` | Number of results (10-100) | 10        |
| `--sort`          | `relevancy` or `recency`   | relevancy |

## Output

JSON array of parsed tweets:

```json
[
  {
    "id": "...",
    "text": "tweet text",
    "author_username": "handle",
    "author_name": "Display Name",
    "created_at": "2026-03-01T...",
    "metrics": {
      "like_count": 42,
      "retweet_count": 5,
      "reply_count": 3,
      "impression_count": 1200
    },
    "url": "https://x.com/handle/status/..."
  }
]
```

## Rate Limits

- Search: 300 requests per 15-minute window (Basic tier)
- Rate limit info logged to stderr on each request
- Warning when remaining < 50

## When to Use

- **x-api**: Quick one-off searches, tweet lookups, checking what's trending on a topic
- **x-ops**: Full automated patrol pipeline with Gemini analysis, knowledge base sync, dynamic keywords
- x-api is the scalpel, x-ops is the combine harvester
