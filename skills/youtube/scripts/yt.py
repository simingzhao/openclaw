#!/usr/bin/env python3
"""YouTube helper: search, transcript, channel lookup."""

import argparse
import json
import os
import subprocess
import sys

from googleapiclient.discovery import build


def get_youtube_service():
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        print("Error: YOUTUBE_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    return build("youtube", "v3", developerKey=key)


def _parse_video_id(raw):
    """Extract video ID from URL or return as-is."""
    if "youtube.com" in raw or "youtu.be" in raw:
        if "v=" in raw:
            return raw.split("v=")[1].split("&")[0]
        elif "youtu.be/" in raw:
            return raw.split("youtu.be/")[1].split("?")[0]
    return raw


# ── channel lookup ──────────────────────────────────────────────
def cmd_channel(args):
    yt = get_youtube_service()
    handle = args.handle if args.handle.startswith("@") else f"@{args.handle}"
    resp = yt.channels().list(part="id,snippet", forHandle=handle).execute()
    items = resp.get("items", [])
    if not items:
        print(f"Channel not found: {handle}", file=sys.stderr)
        sys.exit(1)
    ch = items[0]
    print(json.dumps({"id": ch["id"], "title": ch["snippet"]["title"]}, ensure_ascii=False))


# ── search ──────────────────────────────────────────────────────
def cmd_search(args):
    yt = get_youtube_service()
    params = dict(part="snippet", q=args.query, type="video",
                  order=args.order, maxResults=args.max)
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


# ── transcript ──────────────────────────────────────────────────
def _try_transcript_api(video_id, langs):
    """Try youtube_transcript_api first."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api.formatters import TextFormatter
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id, languages=langs)
        return TextFormatter().format_transcript(transcript)
    except Exception as e:
        print(f"[transcript-api] Failed: {e}", file=sys.stderr)
        return None


def _try_summarize_cli(video_id):
    """Fallback: use summarize CLI with --extract-only."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        result = subprocess.run(
            ["summarize", url, "--youtube", "auto", "--extract-only"],
            capture_output=True, text=True, timeout=60
        )
        text = result.stdout.strip()
        # summarize returns generic YouTube description if it fails
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


def cmd_transcript(args):
    video_id = _parse_video_id(args.video_id)
    langs = tuple(args.lang.split(",")) if args.lang else ("en",)

    # Try methods in order
    text = _try_transcript_api(video_id, langs)
    if not text:
        print("Trying summarize CLI fallback...", file=sys.stderr)
        text = _try_summarize_cli(video_id)
    if not text:
        print("Error: Could not get transcript via any method. "
              "Video may have no captions, or IP is blocked by YouTube.", file=sys.stderr)
        sys.exit(1)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Saved to {args.out}", file=sys.stderr)
    else:
        print(text)


# ── video info ──────────────────────────────────────────────────
def cmd_info(args):
    yt = get_youtube_service()
    video_id = _parse_video_id(args.video_id)
    resp = yt.videos().list(part="snippet,contentDetails,statistics", id=video_id).execute()
    items = resp.get("items", [])
    if not items:
        print("Video not found", file=sys.stderr)
        sys.exit(1)
    v = items[0]
    info = {
        "videoId": v["id"],
        "title": v["snippet"]["title"],
        "channel": v["snippet"]["channelTitle"],
        "published": v["snippet"]["publishedAt"],
        "duration": v["contentDetails"]["duration"],
        "views": v["statistics"].get("viewCount"),
        "likes": v["statistics"].get("likeCount"),
        "description": v["snippet"]["description"][:500],
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))


# ── main ────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(prog="yt", description="YouTube helper CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    # channel
    ch = sub.add_parser("channel", help="Lookup channel by handle")
    ch.add_argument("handle", help="YouTube handle e.g. @MKBHD")

    # search
    s = sub.add_parser("search", help="Search videos")
    s.add_argument("query", help="Search query")
    s.add_argument("--channel", help="Restrict to channel ID")
    s.add_argument("--max", type=int, default=5, help="Max results (default 5)")
    s.add_argument("--order", default="relevance",
                   choices=["relevance", "date", "rating", "viewCount"])

    # transcript
    t = sub.add_parser("transcript", help="Get video transcript")
    t.add_argument("video_id", help="Video ID or URL")
    t.add_argument("--lang", help="Language codes, comma-separated (e.g. en,zh)")
    t.add_argument("--out", help="Save to file instead of stdout")

    # info
    i = sub.add_parser("info", help="Get video metadata")
    i.add_argument("video_id", help="Video ID or URL")

    args = p.parse_args()
    {"channel": cmd_channel, "search": cmd_search,
     "transcript": cmd_transcript, "info": cmd_info}[args.cmd](args)


if __name__ == "__main__":
    main()
