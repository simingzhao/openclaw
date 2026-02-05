---
name: youtube
description: Search YouTube videos, fetch transcripts, and summarize content. Use when the user asks to find, watch, summarize, or get transcripts of YouTube videos. Supports video URL, search by keyword, and channel-scoped search. Always summarize with Gemini CLI.
---

# YouTube

Search videos, fetch transcripts, and summarize with Gemini CLI.

## Prerequisites

- `YOUTUBE_API_KEY` env var (YouTube Data API v3 key)
- Python packages: `google-api-python-client`, `youtube_transcript_api`
- `gemini` CLI for summarization
- `summarize` CLI (optional fallback for transcript extraction)

## CLI: `yt.py`

Script location: `scripts/yt.py` (relative to this skill directory).

### Commands

```bash
# Lookup channel ID by handle
python3 scripts/yt.py channel @MKBHD

# Search videos (global)
python3 scripts/yt.py search "AI agents 2026" --max 5

# Search within a channel
python3 scripts/yt.py search "entropy" --channel UCHnyfMqiRRG1u-2MsSQLbXA --max 3

# Get video transcript (by ID or URL) — auto fallback chain
python3 scripts/yt.py transcript "dQw4w9WgXcQ"
python3 scripts/yt.py transcript "https://www.youtube.com/watch?v=VIDEO_ID"
python3 scripts/yt.py transcript "VIDEO_ID" --lang en,zh
python3 scripts/yt.py transcript "VIDEO_ID" --out /tmp/transcript.txt

# Get video metadata
python3 scripts/yt.py info "VIDEO_ID"
```

### Transcript fallback chain

1. `youtube_transcript_api` (direct, fast)
2. `summarize` CLI with `--extract-only` (Apify fallback if configured)
3. Error with explanation

## Workflow: Summarize a Video

1. Get video info: `python3 scripts/yt.py info "<url_or_id>"`
2. Fetch transcript: `python3 scripts/yt.py transcript "<url_or_id>" --out /tmp/yt_transcript.txt`
3. Summarize with Gemini CLI:
   ```bash
   gemini "Summarize this YouTube video transcript concisely. List key points and main arguments. Transcript: $(cat /tmp/yt_transcript.txt)"
   ```
   For long transcripts (>30k chars), pipe instead:
   ```bash
   cat /tmp/yt_transcript.txt | gemini "Summarize this YouTube video transcript. Key points and concise summary."
   ```

## Workflow: Search + Summarize

1. Search: `python3 scripts/yt.py search "topic" --max 5`
2. Pick best result → transcript → summarize (steps above)

## Workflow: Channel Search + Summarize

1. Get channel ID: `python3 scripts/yt.py channel @handle`
2. Search in channel: `python3 scripts/yt.py search "query" --channel CHANNEL_ID`
3. Transcript → summarize

## Notes

- Transcript may fail if video has no captions or IP is blocked by YouTube.
- If all transcript methods fail, inform the user and suggest trying from a different network.
- Always use Gemini CLI for the final summary — never summarize inline.
- Search API cost: 100 units per call; use sparingly.
