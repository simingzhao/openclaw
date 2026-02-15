---
name: gemini-models
description: Multi-purpose Gemini API skill for QA, summarization, image generation/editing (Nano Banana), and grounded QA with Google Search.
homepage: https://ai.google.dev/gemini-api/docs
metadata:
  {
    "openclaw":
      {
        "emoji": "♊️",
        "requires": { "bins": ["python3"], "env": ["GEMINI_API_KEY"] },
        "primaryEnv": "GEMINI_API_KEY",
      },
  }
---

# Gemini Models

Use this skill as a general Gemini API runner for downstream agent tasks, not only search.

Supported workflows:

- `qa`: one-shot answers and Q/A pair generation (prompt-driven)
- `summarize`: summarize text input
- `grounded-qa`: answer with Google Search grounding (and optional URL Context)
- `image`: generate or edit images (Nano Banana path via Gemini image model)

## Setup

- Set `GEMINI_API_KEY` in your environment.
- Install the SDK once: `python3 -m pip install google-genai`

## Usage

```bash
GEMINI="{baseDir}/scripts/search.py"

# QA
python3 "$GEMINI" "Explain MCP in 5 bullets" --mode qa

# Generate Q/A pairs from source text (still mode=qa)
python3 "$GEMINI" "Generate 8 high-quality Q/A pairs from this chapter" \
  --mode qa --input-file /tmp/chapter.txt

# Summarize source text from file
python3 "$GEMINI" --mode summarize --input-file /tmp/meeting-notes.txt

# Grounded QA with Google Search
python3 "$GEMINI" "What changed in Gemini API this week?" --mode grounded-qa --thinking medium

# Grounded QA with specific URLs
python3 "$GEMINI" "Summarize the main updates" --mode grounded-qa \
  --url https://ai.google.dev/gemini-api/docs

# Image generation (Nano Banana path)
python3 "$GEMINI" --mode image "A cinematic sunset city skyline, ultra detailed" -o /tmp/skyline.png

# Image editing/composition
python3 "$GEMINI" --mode image "Turn this into a watercolor poster" \
  -i /tmp/input.png -o /tmp/output.png
```

## Key Options

| Flag                | Description                                           |
| ------------------- | ----------------------------------------------------- |
| `--mode`            | `qa`, `summarize`, `grounded-qa`, `image`             |
| `--thinking`        | `off`, `low`, `medium`, `high` (text modes)           |
| `--input-file`      | Source text for `qa` / `summarize`                    |
| `--url`             | URL context, repeatable; enables URL Context tool     |
| `-i, --input-image` | Input image(s) for image edit/composition, repeatable |
| `-o, --output`      | Output file path for image mode                       |
| `--image-size`      | Optional image size: `1K`, `2K`, `4K`                 |
| `--json`            | JSON output                                           |

## Model Defaults

- Text and grounded QA default to `gemini-2.5-flash`.
- Image mode defaults to `gemini-2.5-flash-image` and falls back to `gemini-2.5-flash-image-preview` if needed.
- Grounded mode prints discovered web sources by default (`--no-sources` to disable).

## Official References

- https://ai.google.dev/gemini-api/docs/text-generation
- https://ai.google.dev/gemini-api/docs/google-search
- https://ai.google.dev/gemini-api/docs/url-context
- https://ai.google.dev/gemini-api/docs/image-generation
