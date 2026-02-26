#!/usr/bin/env python3
"""
Scout YouTube Patrol v6 - yt-dlp powered
- yt-dlp for subtitles, channel scanning, and metadata (no YouTube Data API quota)
- State separated from config (yt-patrol-state.json)
- Channel quality metrics tracking
- maintain / health / remove-channel commands
- --json output for all patrol commands
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

# ── paths / thresholds ──────────────────────────────────────────
WORKSPACE       = Path(os.environ.get("SCOUT_YT_WORKSPACE", os.path.expanduser("~/.openclaw/workspace")))
WATCHLIST_PATH  = WORKSPACE / "sources" / "yt-watchlist.yaml"
STATE_PATH      = WORKSPACE / "sources" / "yt-patrol-state.json"
METRICS_PATH    = WORKSPACE / "sources" / "yt-watchlist-metrics.json"
RAW_DIR         = WORKSPACE / "raw" / "youtube"

LONG_VIDEO_THRESHOLD = 2700   # 45 min → map-reduce
CHUNK_SIZE           = 20000  # ~20 KB per chunk
MAX_WORKERS          = 3

GEMINI_MODEL = "gemini-3-flash-preview"


# ── helpers ──────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')


def parse_video_id(raw: str) -> str:
    if "youtube.com" in raw or "youtu.be" in raw:
        if "v=" in raw:
            return raw.split("v=")[1].split("&")[0]
        if "youtu.be/" in raw:
            return raw.split("youtu.be/")[1].split("?")[0]
    return raw


def parse_iso8601_duration(iso: str) -> int:
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


# ── state (separated from config) ───────────────────────────────

def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, 'r') as f:
            return json.load(f)
    return {
        "channel_index": 0,
        "last_run": None,
        "processed_videos": [],
    }


def save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, 'w') as f:
        json.dump(state, f, indent=2)


# ── metrics ──────────────────────────────────────────────────────

def load_metrics() -> dict:
    if METRICS_PATH.exists():
        with open(METRICS_PATH, 'r') as f:
            return json.load(f)
    return {"channels": {}, "last_maintain": None}


def save_metrics(metrics: dict):
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(METRICS_PATH, 'w') as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)


def update_channel_metrics(metrics: dict, slug: str, result: dict):
    """更新频道处理质量指标。"""
    cm = metrics.setdefault("channels", {}).setdefault(slug, {
        "total_attempts": 0,
        "successes": 0,
        "failures": 0,
        "transcript_failures": 0,
        "summary_failures": 0,
        "last_success": None,
        "last_attempt": None,
        "consecutive_failures": 0,
    })
    cm["total_attempts"] += 1
    cm["last_attempt"] = datetime.now().isoformat()

    if result.get("success"):
        cm["successes"] += 1
        cm["last_success"] = datetime.now().isoformat()
        cm["consecutive_failures"] = 0
    else:
        cm["failures"] += 1
        cm["consecutive_failures"] = cm.get("consecutive_failures", 0) + 1
        err = result.get("error", "")
        if "Transcript" in err:
            cm["transcript_failures"] = cm.get("transcript_failures", 0) + 1
        elif "Summary" in err:
            cm["summary_failures"] = cm.get("summary_failures", 0) + 1

    if cm["total_attempts"] > 0:
        cm["success_rate"] = round(cm["successes"] / cm["total_attempts"], 2)


# ── yt-dlp helpers ───────────────────────────────────────────────

def _run_ytdlp(args: list, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run yt-dlp with common flags."""
    cmd = ["yt-dlp", "--no-warnings", "--no-check-certificates"] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def get_channel_videos(handle: str, max_results: int = 5, config: dict | None = None) -> list[dict]:
    """List recent videos from a channel using yt-dlp --flat-playlist."""
    handle = handle if handle.startswith("@") else f"@{handle}"
    url = f"https://www.youtube.com/{handle}/videos"
    try:
        result = _run_ytdlp([
            "--flat-playlist", "--dump-json",
            "--playlist-end", str(max_results),
            url,
        ], timeout=30)
        if result.returncode != 0:
            print(f"  Warning: yt-dlp failed for {handle}: {result.stderr[:200]}", file=sys.stderr, flush=True)
            return []
        videos = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                vid = d.get("id", "")
                if not vid:
                    continue
                videos.append({
                    "id": vid,
                    "title": d.get("title", "Unknown"),
                    "duration": int(d.get("duration") or 0),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                })
            except json.JSONDecodeError:
                continue
        return videos
    except subprocess.TimeoutExpired:
        print(f"  Warning: yt-dlp timeout for {handle}", file=sys.stderr, flush=True)
        return []
    except Exception as e:
        print(f"  Warning: Failed to get videos for {handle}: {e}", file=sys.stderr, flush=True)
        return []


def get_video_info(video_id: str) -> dict | None:
    """Get video metadata using yt-dlp --dump-json."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        result = _run_ytdlp(["--dump-json", "--skip-download", url], timeout=30)
        if result.returncode != 0:
            print(f"[yt-dlp] Failed to get info: {result.stderr[:200]}", file=sys.stderr)
            return None
        d = json.loads(result.stdout)
        return {
            "videoId": d.get("id", video_id),
            "title": d.get("title", "Unknown"),
            "channel": d.get("channel", d.get("uploader", "Unknown")),
            "published": d.get("upload_date", ""),
            "duration": int(d.get("duration") or 0),
            "views": d.get("view_count"),
            "likes": d.get("like_count"),
            "description": (d.get("description") or "")[:500],
        }
    except Exception as e:
        print(f"[yt-dlp] Failed to get video info: {e}", file=sys.stderr)
        return None


# ── transcript (yt-dlp powered) ──────────────────────────────────

def _try_ytdlp_subs(video_id: str, langs: tuple = ("en",)) -> str | None:
    """Download subtitles using yt-dlp. Fast, reliable, no IP issues."""
    import tempfile
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmpdir:
        out_template = os.path.join(tmpdir, "%(id)s")
        lang_str = ",".join(langs)
        try:
            # Try manual subs first, then auto-generated
            result = _run_ytdlp([
                "--write-subs", "--write-auto-subs",
                "--sub-langs", lang_str,
                "--sub-format", "srt",
                "--skip-download",
                "-o", out_template,
                url,
            ], timeout=30)

            # Find the subtitle file
            for f in os.listdir(tmpdir):
                if f.endswith(".srt"):
                    srt_path = os.path.join(tmpdir, f)
                    with open(srt_path, "r", encoding="utf-8") as fh:
                        srt_text = fh.read()
                    # Convert SRT to plain text (strip timestamps and indices)
                    lines = []
                    for line in srt_text.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        if re.match(r'^\d+$', line):
                            continue
                        if re.match(r'\d{2}:\d{2}:\d{2},\d{3}\s*-->', line):
                            continue
                        lines.append(line)
                    text = ' '.join(lines)
                    if len(text) > 200:
                        print(f"[yt-dlp-subs] Got {len(text)} chars", file=sys.stderr)
                        return text
                    print(f"[yt-dlp-subs] Too short ({len(text)} chars)", file=sys.stderr)
                    return None

            print("[yt-dlp-subs] No subtitle file found", file=sys.stderr)
            return None
        except subprocess.TimeoutExpired:
            print("[yt-dlp-subs] Timeout", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[yt-dlp-subs] Failed: {e}", file=sys.stderr)
            return None


def _try_gemini_direct_summary(
    video_id: str,
    video_title: str,
    duration: int = 0,
    channel_slug: str = "unknown",
) -> str | None:
    """
    Gemini native YouTube URL processing — bypasses IP blocks entirely.
    Gemini's servers fetch the video directly from YouTube.

    Key constraint: Gemini limits to 10800 frames per request.
    At 1 fps that's ~3 hours. For longer videos we lower fps proportionally
    so frames = duration_s * fps <= 9000 (safety margin).
    """
    try:
        from google import genai
        from google.genai import types
        client = _get_gemini_client()

        url = f"https://www.youtube.com/watch?v={video_id}"
        dur_min = duration // 60
        is_long = duration > LONG_VIDEO_THRESHOLD

        # Dynamic fps: balance 10800-frame limit AND 1M token limit.
        # Each video frame costs ~258 tokens. With 1M token budget and ~50K
        # reserved for prompt+response, we have ~950K / 258 ≈ 3680 frames max.
        # Use 800 frames as a conservative target so we stay well under both limits.
        MAX_FRAMES = 800
        fps = min(1.0, MAX_FRAMES / max(duration, 1))
        fps = round(max(fps, 0.01), 3)  # floor at 0.01 fps (~1 frame/100 s)
        print(f"[gemini-direct] fps={fps} ({int(duration * fps)} frames, duration={dur_min}min)", file=sys.stderr)

        if is_long:
            prompt = f"""请对这段YouTube视频进行详细分析和总结。

视频标题: {video_title}
频道: {channel_slug}
时长: {dur_min}分钟

生成详尽的中文总结，要求包含：
1. 视频概述（3-4句）
2. 核心理念与观点（6-8条，详细展开，含原文引用）
3. 具体工具/方法/配置（如有，表格列出）
4. 方法论与实操技巧（可行动的建议）
5. 金句摘录（8-10句，中英对照）
6. 行动建议

要求：引用具体内容，信息密度高，至少1500字。"""
        else:
            prompt = f"""请对这段YouTube视频进行分析和总结。

视频标题: {video_title}

要求：
1. 核心观点（3-5点，详细说明）
2. 关键见解与金句（含原文引用）
3. 可行动的建议

用中文输出，保持信息密度高。"""

        # Build video part with dynamic fps to stay under 10800-frame limit
        video_part = types.Part.from_uri(file_uri=url, mime_type="video/mp4")
        video_part.video_metadata = types.VideoMetadata(fps=fps)

        # Try primary model first, fall back to gemini-2.5-flash on error
        models_to_try = [GEMINI_MODEL, "gemini-2.5-flash"]
        last_error = None

        for model in models_to_try:
            try:
                # thinking_config only supported by gemini-3-* / gemini-2.5-pro, not 2.5-flash
                supports_thinking = any(x in model for x in ("gemini-3", "gemini-2.5-pro"))
                gen_config = types.GenerateContentConfig(
                    http_options=types.HttpOptions(timeout=180000),  # 3 min for long videos
                )
                if supports_thinking:
                    gen_config.thinking_config = types.ThinkingConfig(thinking_level="LOW")

                response = client.models.generate_content(
                    model=model,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[
                                video_part,
                                types.Part.from_text(text=prompt),
                            ],
                        )
                    ],
                    config=gen_config,
                )
                text = (getattr(response, "text", "") or "").strip()
                if text and len(text) > 200:
                    if model != GEMINI_MODEL:
                        print(f"[gemini-direct] Used fallback model: {model}", file=sys.stderr)
                    return text
                print(f"[gemini-direct] Response too short ({len(text)} chars) with {model}", file=sys.stderr)
                last_error = f"too short ({len(text)} chars)"
            except Exception as e:
                print(f"[gemini-direct] Failed with {model}: {e}", file=sys.stderr)
                last_error = str(e)

        print(f"[gemini-direct] All models failed. Last error: {last_error}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[gemini-direct] Outer error: {e}", file=sys.stderr)
        return None


def get_transcript(video_id: str, langs: tuple = ("en",)) -> tuple:
    """Get transcript using yt-dlp subtitles (primary) → Gemini direct (fallback)."""
    text = _try_ytdlp_subs(video_id, langs)
    if text:
        return text, None

    return None, "No captions available via yt-dlp"


# ── Gemini API ───────────────────────────────────────────────────

def _get_gemini_client():
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

def summarize_short(transcript: str, video_title: str) -> tuple:
    prompt = f"""总结这段YouTube视频transcript。

视频标题: {video_title}

要求：
1. 核心观点（3-5点）
2. 关键见解与金句
3. 可行动的建议

用中文输出，保持信息密度高。

Transcript:
{transcript}"""
    text = gemini_generate(prompt)
    if text and len(text) > 50:
        return text, None
    return None, "Gemini returned empty/short response"


def _split_into_chunks(text: str, chunk_size: int = CHUNK_SIZE) -> list:
    lines = text.split('\n')
    chunks, current, current_len = [], [], 0
    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > chunk_size and current:
            chunks.append('\n'.join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append('\n'.join(current))
    return chunks


def _map_chunk(chunk: str, chunk_idx: int, total: int) -> str:
    prompt = (
        f"这是YouTube视频transcript的第{chunk_idx + 1}/{total}部分。"
        "请提取8-10个核心要点，包括：观点、案例、数据、工具、方法论。"
        "每点一行bullet point，保留具体细节。必须包含原文引用（引号标注）。\n\n"
        f"{chunk}"
    )
    return gemini_generate(prompt) or ""


def summarize_mapreduce(transcript: str, video_title: str,
                        channel_name: str = "Unknown", duration_str: str = "Unknown") -> tuple:
    chunks = _split_into_chunks(transcript)
    total = len(chunks)
    print(f"    [map-reduce] Split into {total} chunks", flush=True)

    all_points = [""] * total
    print(f"    [map-reduce] Map phase ({MAX_WORKERS} workers)...", flush=True)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_map_chunk, chunk, i, total): i for i, chunk in enumerate(chunks)}
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
    video_id    = video['id']
    video_title = video['title']
    video_url   = video['url']
    duration    = video.get('duration', 0)
    date_str    = datetime.now().strftime("%Y-%m-%d")

    result = {
        'id': video_id, 'title': video_title, 'url': video_url,
        'channel': channel_slug, 'success': False, 'error': None,
    }

    if video_id in processed_set:
        result['error'] = 'Already processed'
        return result

    channel_dir  = RAW_DIR / channel_slug
    transcript_dir = channel_dir / "transcripts"
    summary_dir    = channel_dir / "summaries"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    title_slug = slugify(video_title)[:50]
    transcript_file = transcript_dir / f"{date_str}_{title_slug}.txt"
    summary_file    = summary_dir    / f"{date_str}_{title_slug}.md"

    dur_min = int(duration) // 60
    print(f"  [{channel_slug}] {video_title[:40]}... ({dur_min}min)", flush=True)

    # Step 1: transcript
    print(f"    Step 1: Getting transcript...", flush=True)
    transcript_text, error = get_transcript(video_id)

    dur_sec = int(duration) % 60
    summary = None

    if transcript_text and len(transcript_text) >= 500 and "upload original content" not in transcript_text.lower():
        with open(transcript_file, 'w', encoding='utf-8') as f:
            f.write(f"# {video_title}\n# URL: {video_url}\n# Date: {date_str}\n\n")
            f.write(transcript_text)
        print(f"    Transcript saved ({len(transcript_text)} chars)", flush=True)

        # Step 2: summarize from transcript
        if duration > LONG_VIDEO_THRESHOLD:
            print(f"    Step 2: Long video - map-reduce...", flush=True)
            summary, error = summarize_mapreduce(
                transcript_text, video_title, channel_slug, f"{dur_min}:{dur_sec:02d}",
            )
        else:
            print(f"    Step 2: Summarizing with Gemini...", flush=True)
            summary, error = summarize_short(transcript_text, video_title)

        if error or not summary:
            print(f"    Summary failed: {error}, will try Gemini direct...", flush=True)
            summary = None

    # Step 1b / Step 2b: Gemini direct from YouTube URL (fallback when transcript unavailable)
    if not summary:
        print(f"    Trying Gemini direct (YouTube URL processing)...", flush=True)
        summary = _try_gemini_direct_summary(video_id, video_title, duration, channel_slug)
        if summary:
            result['source'] = 'gemini-direct'
            print(f"    Gemini direct summary: {len(summary)} chars", flush=True)
        else:
            result['error'] = "Transcript: IpBlocked; Gemini direct: failed"
            return result

    source_tag = f"\n**Source:** Gemini direct (no transcript available)" if result.get('source') == 'gemini-direct' else ""
    header = f"""# {video_title}

**Channel:** {channel_slug}
**Date:** {date_str}
**Duration:** {dur_min}:{dur_sec:02d}
**URL:** {video_url}{source_tag}

---

"""
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(header + summary)

    print(f"    Summary saved: {summary_file.name}", flush=True)
    result['success'] = True
    result['file'] = str(summary_file)
    result['summary_preview'] = summary[:300]
    return result


# ── migration ────────────────────────────────────────────────────

def maybe_migrate(config: dict, state: dict) -> bool:
    """一次性迁移：把 processed_videos / channel_index / last_run 从 YAML 移到 state JSON。"""
    migrated = False
    schedule = config.get('schedule', {})

    if 'processed_videos' in config and not state.get('processed_videos'):
        state['processed_videos'] = config.pop('processed_videos', [])
        migrated = True

    if 'channel_index' in schedule and not state.get('channel_index'):
        state['channel_index'] = schedule.pop('channel_index', 0)
        migrated = True

    if 'last_run' in schedule and not state.get('last_run'):
        state['last_run'] = schedule.pop('last_run', None)
        migrated = True

    if migrated:
        save_state(state)
        save_config(config)
        print("✅ Migrated state → yt-patrol-state.json", file=sys.stderr)

    return migrated


# ── patrol command ───────────────────────────────────────────────

def cmd_patrol(args, config):
    state   = load_state()
    metrics = load_metrics()
    maybe_migrate(config, state)

    print("Starting YouTube patrol (v5)...", flush=True)

    channels_config = config.get('channels', {})
    schedule        = config.get('schedule', {})
    processing      = config.get('processing', {})
    processed       = set(state.get('processed_videos', []))

    tier1 = channels_config.get('tier1', [])
    tier2 = channels_config.get('tier2', [])
    channels_to_check = list(tier1)

    # tier2 rotation (index now in state)
    if tier2 and not getattr(args, 'channel', None):
        per_run = schedule.get('channels_per_run', 3)
        idx     = state.get('channel_index', 0)
        for i in range(per_run):
            channels_to_check.append(tier2[(idx + i) % len(tier2)])
        state['channel_index'] = (idx + per_run) % len(tier2) if tier2 else 0

    if getattr(args, 'channel', None):
        channels_to_check = [
            c for c in (tier1 + tier2)
            if c.get('name', '').lower() == args.channel.lower()
            or c.get('handle', '').lower() == args.channel.lower()
        ]

    videos_per_channel = schedule.get('videos_per_channel', 2)
    min_dur = processing.get('min_duration_seconds', 120)
    max_dur = processing.get('max_duration_seconds', 7200)

    # Phase 1: collect videos
    print(f"\nScanning {len(channels_to_check)} channels...", flush=True)
    all_videos: list = []
    for channel in channels_to_check:
        handle = channel.get('handle')
        name   = channel.get('name')
        slug   = channel.get('slug', slugify(name))
        print(f"  {name}", flush=True)
        videos = get_channel_videos(handle, max_results=5, config=config)
        count = 0
        for video in videos:
            if count >= videos_per_channel:
                break
            if video['id'] in processed or video.get('duration', 0) < min_dur or video.get('duration', 0) > max_dur:
                continue
            video['channel_slug'] = slug
            all_videos.append(video)
            count += 1

    if not all_videos:
        print("\nNo new videos to process", flush=True)
        state['last_run'] = datetime.now().isoformat()
        save_state(state)
        return []

    print(f"\nProcessing {len(all_videos)} videos in parallel...\n", flush=True)

    # Phase 2: parallel processing
    results = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(all_videos))) as executor:
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
                # update metrics
                update_channel_metrics(metrics, result['channel'], result)
            except Exception as e:
                v = futures[future]
                print(f"  Exception processing {v['title']}: {e}", flush=True)

    # save state (not config)
    state['processed_videos'] = list(processed)[-100:]
    state['last_run'] = datetime.now().isoformat()
    save_state(state)
    save_metrics(metrics)
    save_config(config)  # for _channel_id_cache

    # sync raw/youtube to iCloud
    print("\nSyncing to iCloud...", flush=True)
    src = str(RAW_DIR) + '/'
    dst = os.path.expanduser(
        "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/OpenClaw_Vault/Scout/raw/youtube/"
    )
    os.makedirs(dst, exist_ok=True)
    subprocess.run(
        ['rsync', '-av', '--exclude=.DS_Store', src, dst],
        capture_output=True,
    )

    # report
    ok     = sum(1 for r in results if r['success'])
    failed = [r for r in results if not r['success'] and r.get('error') != 'Already processed']
    print(f"\n{'=' * 50}", flush=True)
    print(f"Patrol complete: {ok}/{len(results)} videos processed", flush=True)

    if ok > 0:
        print("\nSuccessful:", flush=True)
        for r in results:
            if r['success']:
                print(f"   [{r['channel']}] {r['title'][:50]}...", flush=True)

    if failed:
        print("\nFailed:", flush=True)
        for r in failed:
            print(f"   [{r['channel']}] {r['title'][:40]}... — {r['error']}", flush=True)

    if getattr(args, 'json', False):
        summary = {
            "total": len(results),
            "ok": ok,
            "failed": len(failed),
            "timestamp": state['last_run'],
            "videos": [
                {
                    "channel": r['channel'],
                    "title": r['title'],
                    "success": r['success'],
                    "error": r.get('error'),
                    "summary_preview": r.get('summary_preview', '')[:200],
                }
                for r in results if r.get('error') != 'Already processed'
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    return results


# ── process command ──────────────────────────────────────────────

def cmd_process(args, config):
    video_id = parse_video_id(args.url)
    info = get_video_info(video_id)
    if not info:
        print("Error: Failed to get video info", file=sys.stderr)
        sys.exit(1)
    video = {
        'id': video_id, 'title': info['title'],
        'duration': info['duration'], 'url': args.url,
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


# ── status command ───────────────────────────────────────────────

def cmd_status(args, config):
    state   = load_state()
    metrics = load_metrics()
    channels = config.get('channels', {})
    schedule = config.get('schedule', {})

    print("═" * 50)
    print("Scout YouTube Patrol Status (v5)")
    print("═" * 50)
    print(f"\nChannels:")
    print(f"   Tier1: {len(channels.get('tier1', []))} channels")
    print(f"   Tier2: {len(channels.get('tier2', []))} channels")
    print(f"   Next tier2 index: {state.get('channel_index', 0)}")
    print(f"\nLast run: {state.get('last_run', 'Never')}")
    print(f"Last maintain: {metrics.get('last_maintain', 'Never')}")
    print(f"Processed videos: {len(state.get('processed_videos', []))}")
    print(f"\nModel: {GEMINI_MODEL}")
    print(f"Long video threshold: >{LONG_VIDEO_THRESHOLD // 60}min → map-reduce")
    print(f"Parallel workers: {MAX_WORKERS}")

    cm = metrics.get("channels", {})
    if cm:
        ranked = sorted(
            [(k, v) for k, v in cm.items() if v.get("total_attempts", 0) > 0],
            key=lambda x: -x[1].get("success_rate", 0)
        )
        print(f"\nChannel success rates:")
        for slug, data in ranked:
            rate = data.get("success_rate", 0)
            att  = data.get("total_attempts", 0)
            cf   = data.get("consecutive_failures", 0)
            flag = " ⚠️" if cf >= 3 else ""
            print(f"   {slug}: {rate:.0%} ({att} attempts){flag}")

    # Check deps
    ytdlp_ok = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True).returncode == 0
    print(f"\nyt-dlp: {'✅ ' + subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True).stdout.strip() if ytdlp_ok else '❌ NOT INSTALLED'}")
    gemini_ok = "✅" if os.environ.get("GEMINI_API_KEY") else "❌ MISSING"
    print(f"GEMINI_API_KEY: {gemini_ok}")


# ── maintain command ─────────────────────────────────────────────

def cmd_maintain(args, config):
    """分析频道质量，建议/执行清理。"""
    metrics  = load_metrics()
    cm       = metrics.get("channels", {})
    channels = config.get('channels', {})
    tier1    = channels.get('tier1', [])
    tier2    = channels.get('tier2', [])

    if not cm:
        print("⚠ 没有指标数据，需要先跑几次patrol积累。")
        return

    report = {
        "timestamp": datetime.now().isoformat(),
        "actions_taken": [],
        "suggestions": [],
    }

    print("\n📊 频道质量分析:")
    dead, struggling, stars = [], [], []

    for slug, data in cm.items():
        if data.get("total_attempts", 0) < 2:
            continue
        rate = data.get("success_rate", 0)
        cf   = data.get("consecutive_failures", 0)
        att  = data.get("total_attempts", 0)

        # find in which tier
        tier = None
        for ch in tier1:
            if ch.get('slug') == slug or ch.get('handle', '').lstrip('@') == slug:
                tier = 'tier1'
        for ch in tier2:
            if ch.get('slug') == slug or ch.get('handle', '').lstrip('@') == slug:
                tier = 'tier2'

        if cf >= 5 and rate < 0.2:
            dead.append((slug, tier, rate, cf))
        elif rate < 0.5 and att >= 3:
            struggling.append((slug, tier, rate, att))
        elif rate >= 0.9 and tier == 'tier2':
            stars.append((slug, tier, rate))

    if dead:
        print(f"\n  💀 持续失败频道 ({len(dead)}):")
        for slug, tier, rate, cf in dead:
            print(f"     {slug} [{tier}] — 成功率 {rate:.0%}, 连续失败 {cf}次")
            report["suggestions"].append({"action": "remove", "target": slug, "tier": tier,
                                          "reason": f"success_rate={rate:.0%}, consecutive_failures={cf}"})
    if struggling:
        print(f"\n  📉 低成功率频道 ({len(struggling)}):")
        for slug, tier, rate, att in struggling:
            print(f"     {slug} [{tier}] — 成功率 {rate:.0%} ({att} attempts)")
            report["suggestions"].append({"action": "investigate", "target": slug, "tier": tier,
                                          "reason": f"success_rate={rate:.0%}"})
    if stars:
        print(f"\n  ⭐ 高质量tier2频道 (考虑升tier1):")
        for slug, tier, rate in stars:
            print(f"     {slug} — 成功率 {rate:.0%}")
            report["suggestions"].append({"action": "promote", "target": slug,
                                          "from_tier": "tier2", "to_tier": "tier1",
                                          "reason": f"success_rate={rate:.0%}"})

    if not dead and not struggling and not stars:
        print("  ✅ 所有频道状态良好")

    # auto-apply
    if args.apply:
        removed = 0
        for slug, tier, rate, cf in dead:
            if tier == 'tier2':
                config['channels']['tier2'] = [
                    ch for ch in tier2 if ch.get('slug') != slug
                ]
                removed += 1
                print(f"  🗑 Removed {slug} from tier2")
                report["actions_taken"].append({"action": "removed", "target": slug})
        if removed:
            save_config(config)
            print(f"\n✅ 自动清理了 {removed} 个失败频道")
    else:
        if dead:
            print(f"\n💡 运行 `maintain --apply` 自动清理持续失败的频道")

    metrics["last_maintain"] = datetime.now().isoformat()
    save_metrics(metrics)

    if getattr(args, 'json', False):
        print(json.dumps(report, ensure_ascii=False, indent=2))


# ── health command ───────────────────────────────────────────────

def cmd_health(args, config):
    """快速健康检查，JSON输出供agent决策。"""
    state   = load_state()
    metrics = load_metrics()
    channels = config.get('channels', {})
    cm       = metrics.get("channels", {})

    tier1 = channels.get('tier1', [])
    tier2 = channels.get('tier2', [])

    problem_channels = [
        slug for slug, d in cm.items()
        if d.get("consecutive_failures", 0) >= 3
    ]

    health = {
        "tier1_count":          len(tier1),
        "tier2_count":          len(tier2),
        "processed_videos":     len(state.get("processed_videos", [])),
        "last_run":             state.get("last_run"),
        "last_maintain":        metrics.get("last_maintain"),
        "problem_channels":     problem_channels,
        "needs_maintain":       metrics.get("last_maintain") is None or (
            datetime.now() - datetime.fromisoformat(metrics["last_maintain"])
        ).days >= 3 if metrics.get("last_maintain") else True,
        "channels_with_data":  len(cm),
    }
    print(json.dumps(health, ensure_ascii=False, indent=2))


# ── add / remove channel commands ────────────────────────────────

def cmd_add_channel(args, config):
    handle = args.handle
    name   = args.name or handle.lstrip('@')
    tier   = args.tier or 'tier2'
    slug   = slugify(name)
    channels  = config.setdefault('channels', {})
    tier_list = channels.setdefault(tier, [])
    for ch in tier_list:
        if ch.get('handle') == handle:
            print(f"Already exists: {handle} in {tier}")
            return
    tier_list.append({'handle': handle, 'name': name, 'slug': slug})
    save_config(config)
    print(f"✅ Added {handle} ({name}) to {tier}")


def cmd_remove_channel(args, config):
    """从 tier1 或 tier2 中移除频道。"""
    target = args.handle.lstrip('@').lower()
    channels = config.get('channels', {})
    for tier_name in ('tier1', 'tier2'):
        tier_list = channels.get(tier_name, [])
        before = len(tier_list)
        channels[tier_name] = [
            ch for ch in tier_list
            if ch.get('handle', '').lstrip('@').lower() != target
            and ch.get('slug', '').lower() != target
            and ch.get('name', '').lower() != target
        ]
        if len(channels[tier_name]) < before:
            save_config(config)
            print(f"✅ Removed '{args.handle}' from {tier_name}")
            return
    print(f"Not found: '{args.handle}'")


# ── search / transcript / info / channel commands ─────────────────

def cmd_search(args, _config):
    """Search YouTube using yt-dlp."""
    query = args.query
    if args.channel:
        query = f"{query} site:youtube.com/c/{args.channel}"
    search_url = f"ytsearch{args.max}:{query}"
    try:
        result = _run_ytdlp([
            "--flat-playlist", "--dump-json", search_url,
        ], timeout=30)
        results = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                results.append({
                    "videoId": d.get("id", ""),
                    "title": d.get("title", ""),
                    "channel": d.get("channel", d.get("uploader", "")),
                    "duration": int(d.get("duration") or 0),
                    "url": d.get("url", f"https://www.youtube.com/watch?v={d.get('id', '')}"),
                })
            except json.JSONDecodeError:
                continue
        print(json.dumps(results, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Search failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_transcript(args, _config):
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


def cmd_info(args, _config):
    video_id = parse_video_id(args.video_id)
    info = get_video_info(video_id)
    if not info:
        print("Video not found", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(info, ensure_ascii=False, indent=2))


def cmd_channel(args, _config):
    """Lookup channel info using yt-dlp."""
    handle = args.handle if args.handle.startswith("@") else f"@{args.handle}"
    url = f"https://www.youtube.com/{handle}"
    try:
        result = _run_ytdlp([
            "--flat-playlist", "--dump-json", "--playlist-end", "1", url,
        ], timeout=30)
        if result.stdout.strip():
            d = json.loads(result.stdout.strip().split('\n')[0])
            print(json.dumps({
                "handle": handle,
                "channel": d.get("channel", d.get("uploader", "Unknown")),
                "channel_id": d.get("channel_id", ""),
            }, ensure_ascii=False))
        else:
            print(f"Channel not found: {handle}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Channel lookup failed: {e}", file=sys.stderr)
        sys.exit(1)


# ── migrate-state command ─────────────────────────────────────────

def cmd_migrate_state(args, config):
    state = load_state()
    maybe_migrate(config, state)
    print("✅ Migration complete (or nothing to migrate)")


# ── main ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="scout_yt",
                                     description="Scout YouTube Patrol v5")
    parser.add_argument('--json', action='store_true', help='Output JSON summary')
    sub = parser.add_subparsers(dest='command')

    p = sub.add_parser('patrol', help='Run YouTube patrol')
    p.add_argument('--channel', help='Only check specific channel')

    p = sub.add_parser('process', help='Process single video URL')
    p.add_argument('url')

    sub.add_parser('status', help='Show config & metrics status')
    sub.add_parser('health', help='Quick health check (JSON)')
    sub.add_parser('migrate-state', help='Migrate state from YAML to JSON')

    p = sub.add_parser('maintain', help='Analyze channel quality & auto-maintain')
    p.add_argument('--apply', action='store_true', help='Auto-remove dead channels')

    p = sub.add_parser('add-channel', help='Add a channel to watchlist')
    p.add_argument('handle')
    p.add_argument('--name')
    p.add_argument('--tier', choices=['tier1', 'tier2'], default='tier2')

    p = sub.add_parser('remove-channel', help='Remove a channel from watchlist')
    p.add_argument('handle', help='Handle, slug, or name')

    p = sub.add_parser('search', help='Search YouTube')
    p.add_argument('query')
    p.add_argument('--channel')
    p.add_argument('--max', type=int, default=5)
    p.add_argument('--order', default='relevance',
                   choices=['relevance', 'date', 'rating', 'viewCount'])

    p = sub.add_parser('transcript', help='Get video transcript')
    p.add_argument('video_id')
    p.add_argument('--lang', default='en')
    p.add_argument('--out')

    p = sub.add_parser('info', help='Get video metadata')
    p.add_argument('video_id')

    p = sub.add_parser('channel', help='Lookup channel by handle')
    p.add_argument('handle')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    no_config = {'search', 'transcript', 'info', 'channel'}
    config = {} if args.command in no_config else load_config()

    dispatch = {
        'patrol':        cmd_patrol,
        'process':       cmd_process,
        'status':        cmd_status,
        'health':        cmd_health,
        'maintain':      cmd_maintain,
        'add-channel':   cmd_add_channel,
        'remove-channel': cmd_remove_channel,
        'search':        cmd_search,
        'transcript':    cmd_transcript,
        'info':          cmd_info,
        'channel':       cmd_channel,
        'migrate-state': cmd_migrate_state,
    }
    dispatch[args.command](args, config)


if __name__ == '__main__':
    main()
