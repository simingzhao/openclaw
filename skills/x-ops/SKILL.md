---
name: x-ops
description: >
  X/Twitter intelligence gathering and operations. Searches trending AI topics,
  analyzes with Gemini, syncs to shared knowledge hub. Dynamic keyword evolution.
metadata:
  openclaw:
    emoji: "🐦"
    requires:
      bins: ["python3"]
---

# x-ops

`x-ops` replaces the old `scout-x` patrol with keyword-driven AI intelligence scanning on X/Twitter.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

3. Export required X API credentials:

```bash
export X_API_KEY="..."
export X_API_SECRET="..."
export X_ACCESS_TOKEN="..."
export X_ACCESS_TOKEN_SECRET="..."
```

4. Optional Gemini and workspace config:

```bash
export GEMINI_API_KEY="..."
export SENSE_MODEL="gemini-3.1-pro-preview"
export X_OPS_WORKSPACE="$HOME/.openclaw/workspace"
export SHARED_KNOWLEDGE_DIR="$HOME/.openclaw/shared-knowledge"
```

## Usage

```bash
VENV="{baseDir}/.venv/bin/python3"

# Sense scan (main patrol)
$VENV "{baseDir}/scripts/sense_scan.py"
$VENV "{baseDir}/scripts/sense_scan.py" --json
$VENV "{baseDir}/scripts/sense_scan.py" --skip-analysis
$VENV "{baseDir}/scripts/sense_scan.py" --keywords "Claude 4,AI agents"

# X API direct
$VENV "{baseDir}/scripts/x_api.py" search "AI agents"
$VENV "{baseDir}/scripts/x_api.py" search "vibe coding" --max-results 20
$VENV "{baseDir}/scripts/x_api.py" status
```

## Environment Variables

- `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`: X OAuth1.0a credentials.
- `GEMINI_API_KEY`: Required for Gemini analysis.
- `SENSE_MODEL`: Optional primary Gemini model override.
- `X_OPS_WORKSPACE`: Base workspace (default `~/.openclaw/workspace`).
- `SHARED_KNOWLEDGE_DIR`: Shared knowledge repo path (default `~/.openclaw/shared-knowledge`).

## Outputs

Default output directory:

`$X_OPS_WORKSPACE/raw/x-posts`

Per run files:

- `{YYYY-MM-DD}_{HHMM}_raw.json`
- `{YYYY-MM-DD}_{HHMM}_analysis.json` (if analysis enabled)
- `{YYYY-MM-DD}_{HHMM}_report.md` (if analysis enabled)
- `latest.json` (latest analysis snapshot)
- `state.json` (dedup state, keeps last 500 tweet IDs)

## Cron Example

Run every hour:

```bash
0 * * * * /path/to/x-ops/.venv/bin/python3 /path/to/x-ops/scripts/sense_scan.py >> /tmp/x-ops.log 2>&1
```
