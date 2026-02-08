#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["edge-tts"]
# ///
"""
Edge TTS script - converts text to speech and outputs OGG Opus for Telegram.
Only outputs file path, never reads binary content.
"""

import argparse
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path


async def list_voices():
    """List available voices."""
    import edge_tts
    voices = await edge_tts.list_voices()
    for v in voices:
        print(f"{v['ShortName']:30} {v['Locale']:10} {v['Gender']}")


async def synthesize(text: str, voice: str, output_path: str):
    """Synthesize text to speech and convert to OGG Opus."""
    import edge_tts
    
    # Create temp file for MP3
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_mp3 = tmp.name
    
    try:
        # Generate MP3 with edge-tts
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(tmp_mp3)
        
        # Convert to OGG Opus for Telegram voice bubble
        output = Path(output_path)
        if output.suffix.lower() != ".ogg":
            output = output.with_suffix(".ogg")
        
        # ffmpeg conversion: MP3 -> OGG Opus (mono, 48k bitrate)
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", tmp_mp3,
                "-c:a", "libopus",
                "-b:a", "48k",
                "-ac", "1",
                str(output)
            ],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"Error converting to OGG: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        
        # Output ONLY the path - never read file content!
        print(f"MEDIA: {output}")
        
    finally:
        # Clean up temp MP3
        Path(tmp_mp3).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Edge TTS - Text to Speech")
    parser.add_argument("--text", "-t", help="Text to synthesize")
    parser.add_argument("--voice", "-v", default="zh-CN-XiaoxiaoNeural", 
                        help="Voice name (default: zh-CN-XiaoxiaoNeural)")
    parser.add_argument("--output", "-o", default="/tmp/edge_tts_output.ogg",
                        help="Output file path (will be .ogg)")
    parser.add_argument("--list-voices", action="store_true",
                        help="List available voices")
    
    args = parser.parse_args()
    
    if args.list_voices:
        asyncio.run(list_voices())
        return
    
    if not args.text:
        print("Error: --text is required", file=sys.stderr)
        sys.exit(1)
    
    asyncio.run(synthesize(args.text, args.voice, args.output))


if __name__ == "__main__":
    main()
