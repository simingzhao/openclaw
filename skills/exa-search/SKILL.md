---
name: exa-search
description: Search the live web with Exa Search API. Use for current events, fast source gathering, and domain-filtered research with optional extracted page text.
homepage: https://exa.ai/docs/reference/search
metadata:
  {
    "openclaw":
      {
        "emoji": "🔎",
        "requires": { "bins": ["python3"], "env": ["EXA_API_KEY"] },
        "primaryEnv": "EXA_API_KEY",
      },
  }
---

# Exa Search

Search the web using Exa's `POST /search` endpoint.

## Setup

- Set `EXA_API_KEY` in your shell environment.
- No extra Python packages are required.

## Usage

```bash
SKILL_DIR="/Users/simingzhao/Desktop/openclaw/skills/exa-search"
EXA="$SKILL_DIR/scripts/search.py"

# Basic search
python3 "$EXA" "latest ai model releases"

# JSON output (full API response)
python3 "$EXA" "latest ai model releases" --json

# Deterministic compact digest (no LLM calls)
python3 "$EXA" "latest ai model releases" --summary

# Compact digest with more items
python3 "$EXA" "latest ai model releases" --summary --summary-items 8

# Compact digest with longer per-article snippets
python3 "$EXA" "latest ai model releases" \
  --summary \
  --summary-items 5 \
  --summary-preview-chars 1100

# Deep search with explicit extra query variants
python3 "$EXA" "state of ai agents in 2026" \
  --type deep \
  --additional-query "agent benchmarks 2026" \
  --additional-query "autonomous agent research 2026"

# Restrict results to domains
python3 "$EXA" "multimodal model paper" \
  --include-domain arxiv.org \
  --include-domain openreview.net

# Exclude domains and customize result count
python3 "$EXA" "open source ai framework comparison" \
  --exclude-domain reddit.com \
  --exclude-domain quora.com \
  --num-results 8

# Disable page-text extraction
python3 "$EXA" "breaking enterprise ai funding news" --no-text
```

## Options

| Flag                      | Description                                                                       |
| ------------------------- | --------------------------------------------------------------------------------- |
| `--type`                  | Search mode: `auto`, `neural`, `fast`, `deep`, `instant`.                         |
| `--num-results`           | Number of results (1-100).                                                        |
| `--category`              | Optional Exa category (for example `news`, `research paper`, `company`).          |
| `--user-location`         | Two-letter country code (for example `US`).                                       |
| `--include-domain`        | Include only this domain (repeatable).                                            |
| `--exclude-domain`        | Exclude this domain (repeatable).                                                 |
| `--additional-query`      | Extra deep-search query variation (repeatable, requires `--type deep`).           |
| `--start-crawl-date`      | ISO-8601 lower bound for crawl date.                                              |
| `--end-crawl-date`        | ISO-8601 upper bound for crawl date.                                              |
| `--start-published-date`  | ISO-8601 lower bound for published date.                                          |
| `--end-published-date`    | ISO-8601 upper bound for published date.                                          |
| `--no-text`               | Disable text extraction from result pages.                                        |
| `--max-text-chars`        | Maximum extracted text characters per result when text is enabled (default 2500). |
| `--preview-chars`         | Maximum snippet characters shown in human output.                                 |
| `--summary`               | Print compact digest mode (deterministic formatting, no LLM calls).               |
| `--summary-items`         | Number of items shown in digest mode.                                             |
| `--summary-preview-chars` | Maximum snippet characters per item in digest mode (default 700).                 |
| `--json`                  | Print JSON response instead of formatted output.                                  |
| `--timeout`               | HTTP timeout in seconds.                                                          |

## Notes

- Query can be provided as a CLI argument or piped over stdin.
- If `--additional-query` is used, `--type` must be `deep`.
- `--json` takes precedence over `--summary` when both are provided.
- API errors are printed with status code and server response details.
