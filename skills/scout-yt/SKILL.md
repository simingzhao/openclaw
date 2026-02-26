---
name: scout-yt
description: Unified YouTube skill. Patrol channels, fetch transcripts, search videos, and summarize with Gemini API. No yt-dlp required. Long videos use map-reduce. Parallel processing.
---

# Scout YouTube (Unified)

Unified YouTube skill: channel patrol, video search, transcript extraction, and Gemini-powered summarization. Replaces both the old `youtube` and `scout-yt` skills.

## Dependencies

**Python packages** (install in scout-yt's own venv):

```bash
cd /Users/simingzhao/Desktop/openclaw/skills/scout-yt
python3 -m venv .venv
.venv/bin/pip install google-api-python-client youtube_transcript_api google-genai PyYAML
```

**Optional CLI** (fallback transcript extraction):

```bash
brew install steipete/tap/summarize
```

**Environment variables:**

```bash
export YOUTUBE_API_KEY="your-key"     # Required: YouTube Data API v3
export GEMINI_API_KEY="your-key"      # Required: Gemini API for summarization
# Optional:
export APIFY_API_TOKEN="your-token"   # YouTube transcript fallback via summarize CLI
export HTTPS_PROXY="..."              # Proxy for youtube_transcript_api
```

## Configuration

Watchlist config stored at:

```
~/.openclaw/workspace-scout/sources/yt-watchlist.yaml
```

## Directory Structure

```
~/.openclaw/workspace-scout/raw/youtube/
├── 3blue1brown/
│   ├── transcripts/
│   │   └── 2026-02-16_video-title.txt
│   └── summaries/
│       └── 2026-02-16_video-title.md
├── ai-explained/
│   ├── transcripts/
│   └── summaries/
└── ...
```

## Usage

```bash
VENV="/Users/simingzhao/Desktop/openclaw/skills/scout-yt/.venv/bin/python3"
SCOUT="$VENV /Users/simingzhao/Desktop/openclaw/skills/scout-yt/scripts/scout_yt.py"

# ── Patrol (check watched channels for new videos) ──
$SCOUT patrol
$SCOUT patrol --channel "AI Explained"

# ── Process single video ──
$SCOUT process "https://youtube.com/watch?v=xxx"

# ── Search YouTube videos ──
$SCOUT search "AI agents 2026" --max 5
$SCOUT search "entropy" --channel UCHnyfMqiRRG1u-2MsSQLbXA --max 3

# ── Get video transcript ──
$SCOUT transcript "VIDEO_ID_OR_URL"
$SCOUT transcript "VIDEO_ID" --lang en,zh
$SCOUT transcript "VIDEO_ID" --out /tmp/transcript.txt

# ── Get video metadata ──
$SCOUT info "VIDEO_ID_OR_URL"

# ── Lookup channel by handle ──
$SCOUT channel @MKBHD

# ── Show config status + dependency check ──
$SCOUT status

# ── Add channel to watchlist ──
$SCOUT add-channel "@AIExplained" --name "AI Explained" --tier tier1
```

## Patrol Strategy

1. **Tier-based priority**: tier1 channels are checked every run; tier2 channels rotate (3 per run by default)
2. **YouTube Data API listing**: fetch latest videos per channel via `search().list()` (no yt-dlp)
3. **Duration filter**: skip videos shorter than 2 min or longer than 2 hours
4. **Deduplication**: track processed video IDs in config (keeps last 100)
5. **Parallel processing**: up to 3 videos processed concurrently via ThreadPoolExecutor

## Summarization

### Short videos (< 45 min)

Two-step: fetch transcript, then single Gemini API call.

### Long videos (>= 45 min)

Map-reduce via Gemini API (all in Python, no temp files):

1. Split transcript into ~20KB chunks (on line boundaries)
2. **Map**: parallel Gemini API calls (3 workers) extract 8-10 key points per chunk
3. **Reduce**: single Gemini API call merges all points into structured summary (1500+ words)

Output includes: video overview, core concepts with quotes, tools/config table, methodology, bilingual key quotes, action items.

### Transcript fallback chain

1. `youtube_transcript_api` (fast, supports proxy)
2. `summarize` CLI `--extract --youtube auto` — only if output looks like real transcript (not description)
3. **Gemini direct** — passes YouTube URL to Gemini API (`video/mp4` MIME type); Gemini's servers fetch the video directly, bypassing any IP blocks. Falls back from `gemini-3-flash-preview` to `gemini-2.5-flash` on error.

> **IP block workaround**: If `youtube_transcript_api` returns `IpBlocked`, the skill automatically falls through to Gemini direct, which always works regardless of the client IP.

## Summary Format

```markdown
# Video Title

**Channel:** channel-slug
**Date:** 2026-02-16
**Duration:** 15:32
**URL:** https://youtube.com/watch?v=xxx

---

[Gemini summary content]
```

## Notes

- No yt-dlp dependency. All metadata comes from YouTube Data API.
- Summarization uses Gemini API directly (google-genai SDK), not the gemini CLI.
- Search API costs 100 units per call; use sparingly.
- If transcript methods fail, the video may have no captions or IP is blocked.
- Results are synced to iCloud/Obsidian after each patrol run.
