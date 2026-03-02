---
name: exa-search
description: Search the web and extract page contents via Exa API. Supports keyword/neural/deep search, text extraction, highlights, summaries, date filters, and domain filters. One-step search + content retrieval.
metadata:
  openclaw:
    emoji: "🔍"
    requires:
      env: ["EXA_API_KEY"]
    primaryEnv: "EXA_API_KEY"
---

# Exa Search

Search the web and extract page contents in one step via Exa API.

## Setup

```bash
export EXA_API_KEY="your-key"  # https://dashboard.exa.ai/api-keys
```

No SDK needed — pure Python stdlib (`urllib`), zero dependencies.

## Usage

```bash
SKILL_DIR="/Users/simingzhao/Desktop/openclaw/skills/exa-search"
EXA="python3 $SKILL_DIR/scripts/exa_search.py"

# Basic search (returns titles + URLs + highlights)
$EXA "latest AI agent frameworks 2026"

# Get full page text instead of highlights
$EXA --text "OpenAI Agents SDK tutorial"

# Get summaries focused on a specific aspect
$EXA --summary "main findings" "Fed report AI adoption impact"

# Limit results
$EXA -n 5 "Claude Code vs Cursor comparison"

# Filter by date (ISO 8601)
$EXA --after 2026-02-01 "Anthropic funding"

# Filter by domain
$EXA --domain arxiv.org --domain paperswithcode.com "transformer architecture"

# Exclude domains
$EXA --exclude reddit.com "best AI coding tools"

# Category filter (news, research paper, tweet, company, people, etc.)
$EXA --category news "OpenAI Anthropic Google AI"

# Search type: auto (default), neural, fast, deep, instant
$EXA --type deep --answer "Who is the CEO of Anthropic?"

# Deep search with answer synthesis
$EXA --type deep --answer "What are the key differences between Claude and GPT?"

# Combine everything
$EXA -n 10 --text --after 2026-01-01 --category news --domain techcrunch.com "AI startup funding"

# Raw JSON output (for piping to jq etc.)
$EXA --json "query here"
```

## Options Reference

| Flag                 | Description                                             | Default |
| -------------------- | ------------------------------------------------------- | ------- |
| `-n NUM`             | Number of results                                       | 10      |
| `--text`             | Return full page text (vs highlights)                   | off     |
| `--text-max N`       | Max characters for text                                 | 4000    |
| `--summary "query"`  | Return AI summary focused on query                      | off     |
| `--highlights`       | Return highlights (default content mode)                | on      |
| `--highlights-max N` | Max characters per highlight                            | 4000    |
| `--type TYPE`        | Search type: auto/neural/fast/deep/instant              | auto    |
| `--category CAT`     | Category: news/research paper/tweet/company/people/etc. | none    |
| `--after DATE`       | Published after (YYYY-MM-DD)                            | none    |
| `--before DATE`      | Published before (YYYY-MM-DD)                           | none    |
| `--domain DOMAIN`    | Include domain (repeatable)                             | none    |
| `--exclude DOMAIN`   | Exclude domain (repeatable)                             | none    |
| `--include-text STR` | Must contain this text                                  | none    |
| `--exclude-text STR` | Must not contain this text                              | none    |
| `--answer`           | Return synthesized answer (deep search)                 | off     |
| `--json`             | Raw JSON output                                         | off     |

## Output Format

Default output is human-readable:

```
🔍 Exa Search: "AI agent frameworks"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Title of Result
   https://example.com/article
   Published: 2026-02-25
   > Highlight or summary text here...

2. Another Result
   ...
```

With `--json`, returns raw Exa API response for programmatic use.
