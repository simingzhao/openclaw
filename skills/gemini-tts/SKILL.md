---
name: gemini-tts
description: Text-to-speech using Google Gemini 2.5 Flash Preview TTS. High quality voices with warm, natural tone.
---

# Gemini TTS

Text-to-speech powered by Google Gemini 2.5 Flash Preview TTS model.

## Prerequisites

- `google-genai` Python package (auto-installed on first run)
- `ffmpeg` for OGG Opus conversion (Telegram voice)
- `GEMINI_API_KEY` environment variable

## Usage

```bash
# Basic usage (outputs WAV)
python3 scripts/tts.py "Hello, this is a test." -o /tmp/output.wav

# With specific voice
python3 scripts/tts.py "你好，这是一个测试。" -o /tmp/output.wav -v Kore

# Output OGG Opus for Telegram voice bubble
python3 scripts/tts.py "Hello!" -o /tmp/voice.ogg

# With API key
python3 scripts/tts.py "Hello!" --api-key YOUR_API_KEY -o /tmp/output.wav
```

## Available Voices

| Voice    | Style                                    |
| -------- | ---------------------------------------- |
| Kore     | Warm, friendly (recommended for Chinese) |
| Aoede    | Clear, professional                      |
| Charon   | Deep, authoritative                      |
| Fenrir   | Energetic                                |
| Puck     | Playful                                  |
| Achernar | Calm, soothing                           |

## Telegram Integration

For Telegram voice bubbles, output to `.ogg`:

```bash
python3 scripts/tts.py "消息内容" -o /tmp/voice_telegram.ogg
```

Then send with `message` tool:

```
message --action send --to <chat_id> --media /tmp/voice_telegram.ogg --asVoice true
```

## Notes

- Model: `gemini-2.5-flash-preview-tts`
- Supports multiple languages including Chinese
- Auto-converts to OGG Opus when output ends with `.ogg`
