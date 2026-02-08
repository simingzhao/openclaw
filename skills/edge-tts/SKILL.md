---
name: edge-tts
description: Text-to-speech using Microsoft Edge TTS (free, no API key). Outputs OGG Opus for Telegram voice bubbles.
homepage: https://github.com/rany2/edge-tts
metadata:
  {
    "openclaw":
      {
        "emoji": "🔊",
        "requires": { "bins": ["uv", "ffmpeg"] },
        "install":
          [
            {
              "id": "uv-brew",
              "kind": "brew",
              "formula": "uv",
              "bins": ["uv"],
              "label": "Install uv (brew)",
            },
            {
              "id": "ffmpeg-brew",
              "kind": "brew",
              "formula": "ffmpeg",
              "bins": ["ffmpeg"],
              "label": "Install ffmpeg (brew)",
            },
          ],
      },
  }
---

# Edge TTS

Free text-to-speech using Microsoft Edge's online TTS service.

## Usage

```bash
uv run {baseDir}/scripts/tts.py --text "你好，我是小龙虾" --voice "zh-CN-XiaoxiaoNeural" --output "/tmp/voice.ogg"
```

## Voices

Chinese:

- `zh-CN-XiaoxiaoNeural` (female, recommended)
- `zh-CN-YunxiNeural` (male)
- `zh-CN-YunyangNeural` (male, news)

English:

- `en-US-JennyNeural` (female)
- `en-US-GuyNeural` (male)

List all voices:

```bash
uv run {baseDir}/scripts/tts.py --list-voices
```

## Telegram Voice Bubble

The script outputs OGG Opus format which Telegram requires for voice bubbles.

Send with OpenClaw:

```bash
# Script outputs: MEDIA: /tmp/voice.ogg
# Then use message tool with asVoice:true
```

## Important

- Script only outputs file path (MEDIA: line)
- DO NOT read the audio file content back into context
- Just report the path and use message tool to send
