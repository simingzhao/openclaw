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

## Workflow: Long Video Summary (Map-Reduce)

For videos longer than 30 minutes with very long transcripts, use the map-reduce approach:

```bash
# One-command solution
./scripts/summarize_long.sh "VIDEO_URL_OR_ID" [output_dir]

# Example
./scripts/summarize_long.sh "https://youtu.be/SGEaHsul_y4" ~/Desktop/Openclaw_vault/YouTube_Transcripts
```

**How it works:**

1. **Fetch**: Get video info and full transcript via Apify
2. **Split**: Divide transcript into ~20KB chunks
3. **Map**: Extract 8-10 key points from each chunk (parallel Gemini calls)
4. **Reduce**: Merge all points into comprehensive 2000+ word summary with:
   - 视频概述
   - 核心理念（含原文引用）
   - 具体配置与工具（表格）
   - 方法论与技巧
   - 金句摘录（中英对照）
   - 案例故事
   - 行动建议

**When to use:**

- Video duration > 30 minutes
- Transcript > 50KB
- Need detailed, structured summary with quotes

**Output files:**

- `{video_id}_full.md` - Final comprehensive summary
- `transcript_{video_id}.txt` - Raw transcript
- `all_points_{video_id}.txt` - Extracted points from all chunks

## Notes

- Transcript may fail if video has no captions or IP is blocked by YouTube.
- If all transcript methods fail, inform the user and suggest trying from a different network.
- Always use Gemini CLI for the final summary — never summarize inline.
- Search API cost: 100 units per call; use sparingly.
- For long videos (1h+), prefer `summarize_long.sh` over direct `summarize` command.
- Map-Reduce handles transcripts of any length without timeout issues.
