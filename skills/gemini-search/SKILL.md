---
name: gemini-search
description: Search the web using Gemini 3 Flash grounded with Google Search. Use for real-time news, current events, policy updates, recent announcements, fact-checking, or any query requiring up-to-date web information. Preferred over Brave Search for comprehensive research with AI synthesis.
---

# Gemini Search

Web search powered by Gemini 3 Flash with Google Search grounding. Returns AI-synthesized answers with real-time web data.

## When to Use

- Current news and events
- Policy updates and government announcements
- Recent product releases or company news
- Fact-checking claims against current sources
- Research requiring multiple web sources synthesized
- Any query where "as of today" matters

## Usage

```bash
# Set skill directory
SKILL_DIR="/Users/simingzhao/Desktop/openclaw/skills/gemini-search"

# Basic search (requires GEMINI_API_KEY env var)
$SKILL_DIR/.venv/bin/python3 $SKILL_DIR/scripts/search.py "query"

# With high thinking (for complex research)
$SKILL_DIR/.venv/bin/python3 $SKILL_DIR/scripts/search.py "query" --thinking high

# With URL context
$SKILL_DIR/.venv/bin/python3 $SKILL_DIR/scripts/search.py "summarize this" --url https://example.com/article
```

## Options

| Flag         | Values                 | Default | Description                  |
| ------------ | ---------------------- | ------- | ---------------------------- |
| `--thinking` | off, low, medium, high | low     | Reasoning depth              |
| `--url`      | URL                    | -       | Add URL context (repeatable) |

## Examples

```bash
# Latest AI news
"What AI models were released this week?"

# Policy research
"China's latest semiconductor export regulations 2026" --thinking high

# Company news
"OpenAI announcements February 2026"

# Analyze specific URL
"Explain this policy" --url https://gov.example/policy.pdf
```

## Notes

- Results include Google Search grounding (real-time web data)
- Higher thinking levels = more thorough analysis but slower
- Use `--url` to include specific sources in the analysis
