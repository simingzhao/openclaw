#!/usr/bin/env python3
"""
Scout YouTube Patrol v4 - Unified
- All YouTube operations in one script (no yt-dlp dependency)
- YouTube Data API for channel listing / video info
- youtube_transcript_api + summarize CLI fallback for transcripts
- Gemini API (google-genai SDK) for summarization
- Pure Python map-reduce for long videos
- Parallel processing via ThreadPoolExecutor
"""

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import yaml

# ── path / threshold config ─────────────────────────────────────
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace-scout"))
WATCHLIST_PATH = WORKSPACE / "sources" / "yt-watchlist.yaml"
RAW_DIR = WORKSPACE / "raw" / "youtube"

LONG_VIDEO_THRESHOLD = 2700  # 45 min -> map-reduce
CHUNK_SIZE = 20000  # ~20 KB per chunk (characters)
MAX_WORKERS = 3  # parallel workers for patrol & map phase

GEMINI_MODEL = "gemini-3-flash-preview"


# ── helpers ──────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')


def parse_video_id(raw: str) -> str:
    """Extract video ID from URL or return as-is."""
    if "youtube.com" in raw or "youtu.be" in raw:
        if "v=" in raw:
            return raw.split("v=")[1].split("&")[0]
        if "youtu.be/" in raw:
            return raw.split("youtu.be/")[1].split("?")[0]
    return raw


def parse_iso8601_duration(iso: str) -> int:
    """Convert ISO 8601 duration (e.g. PT1H23M45S) to seconds."""
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso)
    if not m:
        return 0
    h, mi, s = (int(v) if v else 0 for v in m.groups())
    return h * 3600 + mi * 60 + s


# ── config ───────────────────────────────────────────────────────

def load_config() -> dict:
    if not WATCHLIST_PATH.exists():
        print(f"Error: Config not found at {WATCHLIST_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(WATCHLIST_PATH, 'r') as f:
        return yaml.safe_load(f)


def save_config(config: dict):
    with open(WATCHLIST_PATH, 'w') as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ── YouTube Data API ─────────────────────────────────────────────

def get_youtube_service():
    from googleapiclient.discovery import build
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("Error: YOUTUBE_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    return build("youtube", "v3", developerKey=key)


def resolve_channel_id(handle: str, config: dict | None = None) -> str | None:
    """Resolve @handle to channel ID. Uses config cache when available."""
    handle = handle if handle.startswith("@") else f"@{handle}"

    # check cache
    if config:
        cache = config.setdefault("_channel_id_cache", {})
        if handle in cache:
            return cache[handle]

    try:
        yt = get_youtube_service()
        resp = yt.channels().list(part="id", forHandle=handle).execute()
        items = resp.get("items", [])
        if not items:
            return None
        cid = items[0]["id"]
        if config:
            config.setdefault("_channel_id_cache", {})[handle] = cid
        return cid
    except Exception as e:
        print(f"[yt-api] Failed to resolve {handle}: {e}", file=sys.stderr)
        return None


def get_channel_videos(handle: str, max_results: int = 5, config: dict | None = None) -> list[dict]:
    """Fetch latest videos for a channel via YouTube Data API search."""
    channel_id = resolve_channel_id(handle, config)
    if not channel_id:
        print(f"  Warning: Could not resolve channel ID for {handle}", file=sys.stderr, flush=True)
        return []

    try:
        yt = get_youtube_service()
        resp = yt.search().list(
            part="snippet",
            channelId=channel_id,
            order="date",
            type="video",
            maxResults=max_results,
        ).execute()

        video_ids = [item["id"]["videoId"] for item in resp.get("items", [])]
        if not video_ids:
            return []

        # fetch durations in batch
        details_resp = yt.videos().list(
            part="contentDetails,snippet",
            id=",".join(video_ids),
        ).execute()

        videos = []
        for item in details_resp.get("items", []):
            duration = parse_iso8601_duration(item["contentDetails"]["duration"])
            videos.append({
                "id": item["id"],
                "title": item["snippet"]["title"],
                "duration": duration,
                "url": f"https://www.youtube.com/watch?v={item['id']}",
            })
        return videos
    except Exception as e:
        print(f"  Warning: Failed to get videos for {handle}: {e}", file=sys.stderr, flush=True)
        return []


def get_video_info(video_id: str) -> dict | None:
    """Fetch video metadata via YouTube Data API."""
    try:
        yt = get_youtube_service()
        resp = yt.videos().list(
            part="snippet,contentDetails,statistics",
            id=video_id,
        ).execute()
        items = resp.get("items", [])
        if not items:
            return None
        v = items[0]
        return {
            "videoId": v["id"],
            "title": v["snippet"]["title"],
            "channel": v["snippet"]["channelTitle"],
            "published": v["snippet"]["publishedAt"],
            "duration": parse_iso8601_duration(v["contentDetails"]["duration"]),
            "duration_iso": v["contentDetails"]["duration"],
            "views": v["statistics"].get("viewCount"),
            "likes": v["statistics"].get("likeCount"),
            "description": v["snippet"]["description"][:500],
        }
    except Exception as e:
        print(f"[yt-api] Failed to get video info: {e}", file=sys.stderr)
        return None


# ── transcript ───────────────────────────────────────────────────

def _try_transcript_api(video_id: str, langs: tuple[str, ...] = ("en",)) -> str | None:
    """Primary: youtube_transcript_api with optional proxy."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api.formatters import TextFormatter

        proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        proxy_config = None
        if proxy_url:
            from youtube_transcript_api.proxies import GenericProxyConfig
            proxy_config = GenericProxyConfig(https_url=proxy_url)
            print(f"[transcript-api] Using proxy: {proxy_url}", file=sys.stderr)

        ytt = YouTubeTranscriptApi(proxy_config=proxy_config)
        transcript = ytt.fetch(video_id, languages=langs)
        return TextFormatter().format_transcript(transcript)
    except Exception as e:
        print(f"[transcript-api] Failed: {e}", file=sys.stderr)
        return None


def _try_summarize_cli(video_id: str) -> str | None:
    """Fallback: summarize CLI --extract."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        result = subprocess.run(
            ["summarize", url, "--youtube", "auto", "--extract"],
            capture_output=True, text=True, timeout=90,
        )
        text = result.stdout.strip()
        if text and "Enjoy the videos and music you love" not in text and len(text) > 100:
            return text
        print("[summarize-cli] Got generic/empty response", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("[summarize-cli] Not installed", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[summarize-cli] Failed: {e}", file=sys.stderr)
        return None


def get_transcript(video_id: str, langs: tuple[str, ...] = ("en",)) -> tuple[str | None, str | None]:
    """Fetch transcript with fallback chain. Returns (text, error)."""
    text = _try_transcript_api(video_id, langs)
    if text:
        return text, None

    print("[transcript] Trying summarize CLI fallback...", file=sys.stderr)
    text = _try_summarize_cli(video_id)
    if text:
        return text, None

    return None, "Could not get transcript via any method"


# ── Gemini API ───────────────────────────────────────────────────

def _get_gemini_client():
    """Create google-genai client (lazy import)."""
    try:
        from google import genai
    except ImportError:
        print("Error: google-genai not installed. Run: pip install google-genai", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    return genai.Client(api_key=api_key)


def gemini_generate(prompt: str, model: str = GEMINI_MODEL) -> str | None:
    """Single Gemini API call. Returns text or None."""
    try:
        from google.genai import types
        client = _get_gemini_client()
        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="LOW"),
            ),
        )
        return (getattr(response, "text", "") or "").strip()
    except Exception as e:
        print(f"[gemini] API error: {e}", file=sys.stderr)
        return None


# ── summarization ────────────────────────────────────────────────

def summarize_short(transcript: str, video_title: str) -> tuple[str | None, str | None]:
    """Summarize a short video transcript via Gemini API. Returns (summary, error)."""
    prompt = f"""总结这段YouTube视频transcript。

视频标题: {video_title}

要求：
1. 核心观点（3-5点）
2. 关键见解
3. 有意思的点或金句

用中文输出，保持信息密度高。

Transcript:
{transcript}"""

    text = gemini_generate(prompt)
    if text and len(text) > 50:
        return text, None
    return None, "Gemini summarization returned empty/short response"


def _split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Split text into chunks on line boundaries near chunk_size characters."""
    lines = text.split('\n')
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > chunk_size and current:
            chunks.append('\n'.join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len

    if current:
        chunks.append('\n'.join(current))
    return chunks


def _map_chunk(chunk: str, chunk_idx: int, total: int) -> str:
    """Map phase: extract key points from one chunk."""
    prompt = (
        f"这是YouTube视频transcript的第{chunk_idx + 1}/{total}部分。"
        "请提取8-10个核心要点，包括：观点、案例、数据、工具、方法论。"
        "每点一行bullet point，保留具体细节。必须包含原文引用（引号标注）。\n\n"
        f"{chunk}"
    )
    result = gemini_generate(prompt)
    return result or ""


def summarize_mapreduce(
    transcript: str,
    video_title: str,
    channel_name: str = "Unknown",
    duration_str: str = "Unknown",
) -> tuple[str | None, str | None]:
    """Map-reduce summarization for long videos. Returns (summary, error)."""
    chunks = _split_into_chunks(transcript)
    total = len(chunks)
    print(f"    [map-reduce] Split into {total} chunks", flush=True)

    # Map phase: parallel extraction
    all_points: list[str] = [""] * total
    print(f"    [map-reduce] Map phase ({MAX_WORKERS} workers)...", flush=True)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_map_chunk, chunk, i, total): i
            for i, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                all_points[idx] = future.result()
                print(f"      Chunk {idx + 1}/{total} done", flush=True)
            except Exception as e:
                print(f"      Chunk {idx + 1}/{total} failed: {e}", flush=True)

    merged = "\n".join(p for p in all_points if p.strip())
    if not merged.strip():
        return None, "Map phase produced no points"

    # Reduce phase
    print(f"    [map-reduce] Reduce phase...", flush=True)
    reduce_prompt = f"""以下是YouTube视频《{video_title}》（频道: {channel_name}，时长: {duration_str}）的完整要点。

生成详尽的中文总结，包括：
1. 视频概述（3-4句）
2. 核心理念（6-8条，详细展开，含原文引用）
3. 具体工具/配置（表格列出）
4. 方法论与技巧（可操作的建议）
5. 金句摘录（8-10句，中英对照）
6. 行动建议

要求：引用原文，不压缩内容，至少1500字。

{merged}"""

    summary = gemini_generate(reduce_prompt)
    if summary and len(summary) > 200:
        return summary, None
    return None, "Reduce phase returned empty/short response"


# ── video processing ─────────────────────────────────────────────

def process_video(video: dict, channel_slug: str, processed_set: set) -> dict:
    """Process a single video: transcript + summarize."""
    video_id = video['id']
    video_title = video['title']
    video_url = video['url']
    duration = video.get('duration', 0)
    date_str = datetime.now().strftime("%Y-%m-%d")

    result = {
        'id': video_id,
        'title': video_title,
        'url': video_url,
        'channel': channel_slug,
        'success': False,
        'error': None,
    }

    if video_id in processed_set:
        result['error'] = 'Already processed'
        return result

    # directories
    channel_dir = RAW_DIR / channel_slug
    transcript_dir = channel_dir / "transcripts"
    summary_dir = channel_dir / "summaries"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    title_slug = slugify(video_title)[:50]
    transcript_file = transcript_dir / f"{date_str}_{title_slug}.txt"
    summary_file = summary_dir / f"{date_str}_{title_slug}.md"

    dur_min = int(duration) // 60
    print(f"  [{channel_slug}] {video_title[:40]}... ({dur_min}min)", flush=True)

    # Step 1: get transcript
    print(f"    Step 1: Getting transcript...", flush=True)
    transcript_text, error = get_transcript(video_id)
    if error or not transcript_text:
        print(f"    Transcript failed: {error}", flush=True)
        result['error'] = f"Transcript: {error}"
        return result

    # validate transcript content
    if len(transcript_text) < 100 or "upload original content" in transcript_text.lower():
        print(f"    Transcript looks invalid (too short or generic)", flush=True)
        result['error'] = "Invalid transcript content"
        return result

    # save transcript
    with open(transcript_file, 'w', encoding='utf-8') as f:
        f.write(f"# {video_title}\n# URL: {video_url}\n# Date: {date_str}\n\n")
        f.write(transcript_text)
    print(f"    Transcript saved ({len(transcript_text)} chars)", flush=True)

    # Step 2: summarize
    if duration > LONG_VIDEO_THRESHOLD:
        print(f"    Step 2: Long video - map-reduce...", flush=True)
        dur_sec = int(duration) % 60
        summary, error = summarize_mapreduce(
            transcript_text,
            video_title,
            channel_slug,
            f"{dur_min}:{dur_sec:02d}",
        )
    else:
        print(f"    Step 2: Summarizing with Gemini API...", flush=True)
        summary, error = summarize_short(transcript_text, video_title)

    if error or not summary:
        print(f"    Summary failed: {error}", flush=True)
        result['error'] = f"Summary: {error}"
        return result

    # save summary
    dur_sec = int(duration) % 60
    header = f"""# {video_title}

**Channel:** {channel_slug}
**Date:** {date_str}
**Duration:** {dur_min}:{dur_sec:02d}
**URL:** {video_url}

---

"""
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(header + summary)

    print(f"    Summary saved: {summary_file.name}", flush=True)
    result['success'] = True
    result['file'] = str(summary_file)
    return result


# ── CLI commands: patrol ─────────────────────────────────────────

def cmd_patrol(args, config):
    """Run YouTube patrol with parallel processing."""
    print("Starting YouTube patrol (v4 - unified)...", flush=True)

    channels_config = config.get('channels', {})
    schedule = config.get('schedule', {})
    processing = config.get('processing', {})
    processed = set(config.get('processed_videos', []))

    tier1 = channels_config.get('tier1', [])
    tier2 = channels_config.get('tier2', [])
    channels_to_check = list(tier1)

    # tier2 rotation
    if tier2 and not args.channel:
        per_run = schedule.get('channels_per_run', 3)
        idx = schedule.get('channel_index', 0)
        for i in range(per_run):
            channels_to_check.append(tier2[(idx + i) % len(tier2)])
        schedule['channel_index'] = (idx + per_run) % len(tier2) if tier2 else 0

    # filter by specific channel
    if args.channel:
        channels_to_check = [
            c for c in (tier1 + tier2)
            if c.get('name', '').lower() == args.channel.lower()
            or c.get('handle', '').lower() == args.channel.lower()
        ]

    videos_per_channel = schedule.get('videos_per_channel', 2)
    min_duration = processing.get('min_duration_seconds', 120)
    max_duration = processing.get('max_duration_seconds', 7200)

    # Phase 1: collect videos
    print(f"\nScanning {len(channels_to_check)} channels...", flush=True)
    all_videos: list[dict] = []

    for channel in channels_to_check:
        handle = channel.get('handle')
        name = channel.get('name')
        slug = channel.get('slug', slugify(name))

        print(f"  {name}", flush=True)
        videos = get_channel_videos(handle, max_results=5, config=config)

        count = 0
        for video in videos:
            if count >= videos_per_channel:
                break
            vid = video['id']
            dur = video.get('duration', 0)
            if vid in processed or dur < min_duration or dur > max_duration:
                continue
            video['channel_slug'] = slug
            all_videos.append(video)
            count += 1

    if not all_videos:
        print("\nNo new videos to process", flush=True)
        return []

    print(f"\nProcessing {len(all_videos)} videos in parallel...\n", flush=True)

    # Phase 2: parallel processing
    results: list[dict] = []
    workers = min(MAX_WORKERS, len(all_videos))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(process_video, v, v['channel_slug'], processed): v
            for v in all_videos
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
                if result['success']:
                    processed.add(result['id'])
            except Exception as e:
                v = futures[future]
                print(f"  Exception processing {v['title']}: {e}", flush=True)

    # update config
    config['processed_videos'] = list(processed)[-100:]
    config['schedule']['last_run'] = datetime.now().isoformat()
    save_config(config)

    # sync to iCloud
    print("\nSyncing to iCloud...", flush=True)
    subprocess.run(
        ['rsync', '-av', '--delete',
         '--exclude=.git', '--exclude=.DS_Store',
         str(WORKSPACE) + '/',
         os.path.expanduser(
             "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/OpenClaw_Vault/Scout/"
         )],
        capture_output=True,
    )

    # report
    ok = sum(1 for r in results if r['success'])
    print(f"\n{'=' * 50}", flush=True)
    print(f"Patrol complete: {ok}/{len(results)} videos processed", flush=True)

    if ok > 0:
        print("\nSuccessful:", flush=True)
        for r in results:
            if r['success']:
                print(f"   [{r['channel']}] {r['title'][:40]}...", flush=True)

    failed = [r for r in results if not r['success'] and r.get('error') != 'Already processed']
    if failed:
        print("\nFailed:", flush=True)
        for r in failed:
            print(f"   [{r['channel']}] {r['title'][:40]}... - {r['error']}", flush=True)

    return results


# ── CLI commands: process ────────────────────────────────────────

def cmd_process(args, config):
    """Process a single video URL."""
    video_id = parse_video_id(args.url)

    info = get_video_info(video_id)
    if not info:
        print("Error: Failed to get video info", file=sys.stderr)
        sys.exit(1)

    video = {
        'id': video_id,
        'title': info['title'],
        'duration': info['duration'],
        'url': args.url,
    }

    slug = slugify(info.get('channel', 'unknown'))
    print(f"Processing: {video['title']}", flush=True)
    print(f"Channel: {info.get('channel', 'unknown')}", flush=True)
    print(f"Duration: {info['duration'] // 60}min", flush=True)

    result = process_video(video, slug, set())
    if result['success']:
        print(f"\nDone: {result.get('file')}", flush=True)
    else:
        print(f"\nFailed: {result.get('error')}", flush=True)


# ── CLI commands: status ─────────────────────────────────────────

def cmd_status(args, config):
    """Show configuration status."""
    channels = config.get('channels', {})
    schedule = config.get('schedule', {})

    print("=" * 50, flush=True)
    print("Scout YouTube Patrol Status (v4 - unified)", flush=True)
    print("=" * 50, flush=True)
    print(f"\nChannels:", flush=True)
    print(f"   Tier1: {len(channels.get('tier1', []))} channels", flush=True)
    print(f"   Tier2: {len(channels.get('tier2', []))} channels", flush=True)
    print(f"   Next index: {schedule.get('channel_index', 0)}", flush=True)

    print(f"\nLast run: {schedule.get('last_run', 'Never')}", flush=True)
    print(f"Processed videos: {len(config.get('processed_videos', []))}", flush=True)
    print(f"\nOutput directory: {RAW_DIR}", flush=True)

    print(f"\nStrategy:", flush=True)
    print(f"   Short video: transcript + Gemini API", flush=True)
    print(f"   Long video (>{LONG_VIDEO_THRESHOLD // 60}min): map-reduce via Gemini API", flush=True)
    print(f"   Parallel workers: {MAX_WORKERS}", flush=True)
    print(f"   Model: {GEMINI_MODEL}", flush=True)

    # dependency check
    print(f"\nDependency check:", flush=True)
    for env in ("YOUTUBE_API_KEY", "GEMINI_API_KEY"):
        ok = "set" if os.environ.get(env) else "MISSING"
        print(f"   {env}: {ok}", flush=True)
    for pkg in ("google.genai", "googleapiclient", "youtube_transcript_api", "yaml"):
        try:
            __import__(pkg)
            print(f"   {pkg}: ok", flush=True)
        except ImportError:
            print(f"   {pkg}: MISSING", flush=True)


# ── CLI commands: add-channel ────────────────────────────────────

def cmd_add_channel(args, config):
    """Add a channel to the watchlist."""
    handle = args.handle
    name = args.name or handle.lstrip('@')
    tier = args.tier or 'tier2'
    slug = slugify(name)

    channels = config.setdefault('channels', {})
    tier_list = channels.setdefault(tier, [])

    for ch in tier_list:
        if ch.get('handle') == handle:
            print(f"Already exists: {handle} in {tier}")
            return

    tier_list.append({'handle': handle, 'name': name, 'slug': slug})
    save_config(config)
    print(f"Added {handle} ({name}) to {tier}", flush=True)


# ── CLI commands: search (from yt.py) ────────────────────────────

def cmd_search(args, _config):
    """Search YouTube videos."""
    yt = get_youtube_service()
    params = dict(
        part="snippet", q=args.query, type="video",
        order=args.order, maxResults=args.max,
    )
    if args.channel:
        params["channelId"] = args.channel
    resp = yt.search().list(**params).execute()
    results = []
    for item in resp.get("items", []):
        results.append({
            "videoId": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "channel": item["snippet"]["channelTitle"],
            "published": item["snippet"]["publishedAt"],
        })
    print(json.dumps(results, ensure_ascii=False, indent=2))


# ── CLI commands: transcript (from yt.py) ────────────────────────

def cmd_transcript(args, _config):
    """Get video transcript."""
    video_id = parse_video_id(args.video_id)
    langs = tuple(args.lang.split(",")) if args.lang else ("en",)

    text, error = get_transcript(video_id, langs)
    if error or not text:
        print(f"Error: {error or 'Could not get transcript'}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Saved to {args.out}", file=sys.stderr)
    else:
        print(text)


# ── CLI commands: info (from yt.py) ──────────────────────────────

def cmd_info(args, _config):
    """Get video metadata."""
    video_id = parse_video_id(args.video_id)
    info = get_video_info(video_id)
    if not info:
        print("Video not found", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(info, ensure_ascii=False, indent=2))


# ── CLI commands: channel (from yt.py) ───────────────────────────

def cmd_channel(args, _config):
    """Lookup channel by handle."""
    yt = get_youtube_service()
    handle = args.handle if args.handle.startswith("@") else f"@{args.handle}"
    resp = yt.channels().list(part="id,snippet", forHandle=handle).execute()
    items = resp.get("items", [])
    if not items:
        print(f"Channel not found: {handle}", file=sys.stderr)
        sys.exit(1)
    ch = items[0]
    print(json.dumps({"id": ch["id"], "title": ch["snippet"]["title"]}, ensure_ascii=False))


# ── main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="scout_yt",
        description="Scout YouTube Patrol v4 - unified YouTube operations",
    )
    sub = parser.add_subparsers(dest='command', help='Commands')

    # patrol
    p_patrol = sub.add_parser('patrol', help='Run YouTube patrol')
    p_patrol.add_argument('--channel', help='Only check specific channel')

    # process
    p_proc = sub.add_parser('process', help='Process single video')
    p_proc.add_argument('url', help='YouTube video URL')

    # status
    sub.add_parser('status', help='Show config status')

    # add-channel
    p_add = sub.add_parser('add-channel', help='Add a channel to watchlist')
    p_add.add_argument('handle', help='Channel handle (e.g., @AIExplained)')
    p_add.add_argument('--name', help='Display name')
    p_add.add_argument('--tier', choices=['tier1', 'tier2'], default='tier2')

    # search
    p_search = sub.add_parser('search', help='Search YouTube videos')
    p_search.add_argument('query', help='Search query')
    p_search.add_argument('--channel', help='Restrict to channel ID')
    p_search.add_argument('--max', type=int, default=5, help='Max results (default 5)')
    p_search.add_argument('--order', default='relevance',
                          choices=['relevance', 'date', 'rating', 'viewCount'])

    # transcript
    p_trans = sub.add_parser('transcript', help='Get video transcript')
    p_trans.add_argument('video_id', help='Video ID or URL')
    p_trans.add_argument('--lang', help='Language codes, comma-separated (e.g. en,zh)')
    p_trans.add_argument('--out', help='Save to file instead of stdout')

    # info
    p_info = sub.add_parser('info', help='Get video metadata')
    p_info.add_argument('video_id', help='Video ID or URL')

    # channel
    p_ch = sub.add_parser('channel', help='Lookup channel by handle')
    p_ch.add_argument('handle', help='YouTube handle e.g. @MKBHD')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # commands that don't need config
    no_config = {'search', 'transcript', 'info', 'channel'}
    config = {} if args.command in no_config else load_config()

    dispatch = {
        'patrol': cmd_patrol,
        'process': cmd_process,
        'status': cmd_status,
        'add-channel': cmd_add_channel,
        'search': cmd_search,
        'transcript': cmd_transcript,
        'info': cmd_info,
        'channel': cmd_channel,
    }
    dispatch[args.command](args, config)


if __name__ == '__main__':
    main()
