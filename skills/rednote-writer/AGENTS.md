# Refactoring Task: rednote-writer

## Context

This is a Xiaohongshu (RedNote) content writing skill. It generates content + card images for posting.

Publishing to the platform is now handled by a separate `rednote-ops` skill. This skill should ONLY handle writing: text generation → card rendering → save to drafts.

## What to do

### 1. DELETE `scripts/mcp_client.py`

- All MCP operations moved to rednote-ops. Remove this file entirely.

### 2. REFACTOR `scripts/rednote_writer.py` — Pipeline orchestrator

**Remove:**

- `from mcp_client import ...` import
- `--publish` CLI argument
- `publish_to_rednote()` function
- Any reference to MCP

**Change:**

- Output directory: change from `~/.openclaw/workspace/articles/rednote/` to `~/.openclaw/workspace-rednote-ops/content/drafts/`
- Output dir naming: use `{date}_{slug}` format (e.g. `2026-02-25_vibe-coding`) where slug comes from the title
- Add `--style` argument (choices: typography-card, notes-app, text-only; default: typography-card)
- Add `--type` argument (choices: brief, analysis, opinion, tools; default: brief)
- Pass style to card_gen, pass type to content_gen
- Save a `meta.json` alongside content.json with: style_id, content_type, created_at, card_count

**Keep:**

- `daily-brief` command (素材 → content_gen → card_gen → save)
- `from-json` command (existing content.json → card_gen → save)
- iCloud sync
- content.json + content.txt generation

### 3. REFACTOR `scripts/card_gen.py` — Multi-style card engine

**Replace the entire file** with a new multi-style card renderer. The new card_gen.py should:

**Architecture:**

```python
def generate_cards(style_id: str, content_data: dict, output_dir: str) -> list[str]:
    """Main entry point. Dispatches to style-specific renderer."""
    renderers = {
        "typography-card": render_typography_cards,
        "notes-app": render_notes_app_cards,
        "text-only": render_text_only_cover,
    }
    renderer = renderers.get(style_id, render_typography_cards)
    return renderer(content_data, output_dir)
```

**Style 1: `typography-card` (极简知识卡)**

- Port from existing `note_card_gen.py` code (Pillow-based)
- Warm cream background (#F5F0E8)
- Brown text (#8B4513 title, #6B3A0A body)
- Large serif-style title at top
- Metadata line (word count + reading time)
- Clean paragraphs with generous line spacing
- Thin divider lines between sections
- Size: 1080×1440 (3:4)
- Font: STHeiti Medium for titles, STHeiti Light for body (macOS system fonts)

**Style 2: `notes-app` (备忘录截图风)**

- NEW renderer, simulate iOS Notes app
- Pure white background (#FFFFFF)
- Dark gray text (#333333)
- Top bar: "< 备忘录" in amber/gold (#D4A000) with share and more icons
- Very large font (48-56px for body text)
- Key terms highlighted with yellow (#FFE066) or green (#90EE90) background
- Minimal: only 3-5 lines per card, big and scannable
- Size: 1080×1440 (3:4)

**Style 3: `text-only` (纯文字帖)**

- Generate ONLY a cover card (one single image)
- Simple clean design: white or light background, bold title, subtle branding
- The actual post content will be in the text body (not images)
- Size: 1080×1440 (3:4)

**All renderers must:**

- Return list of file paths (PNG)
- First image is always the cover (00_cover.png)
- Use Pillow only, NO API calls
- Handle Chinese text perfectly with system fonts
- Accept content_data dict (same schema as content.json)

**CLI:**

```bash
# Batch from JSON
python3 card_gen.py batch -i content.json -o ./cards/ --style typography-card

# Single card
python3 card_gen.py card --style notes-app -t "标题" -b "内容" -o card.png

# Cover only
python3 card_gen.py cover --style text-only -t "标题" -s "副标题" -o cover.png
```

### 4. MERGE `scripts/note_card_gen.py` into card_gen.py

- Move the Pillow rendering code into card_gen.py as the `typography-card` renderer
- Then DELETE note_card_gen.py

### 5. UPDATE `scripts/content_gen.py` — Multi-type content generation

**Add `--type` parameter:**

- `brief` (default): Current behavior — pick 5-7 items from digest, generate cards + post
- `analysis`: Single topic deep dive — output has `title`, `sections[]` (each with heading + points + quote), `key_quote`, `post_body`
- `opinion`: Short hot take — output has `title`, `body` (short, punchy text), `tags`. No items/cards needed.
- `tools`: Tool recommendation list — output has `title`, `tools[]` (each with name + description + verdict), `post_body`, `tags`

Each type needs its own SYSTEM_PROMPT tailored for that content format.

**Keep the same Gemini API calling logic** (primary + fallback model). Just add the type routing.

### 6. UPDATE `SKILL.md`

Rewrite the SKILL.md frontmatter and body to reflect:

- Description: Content writing + card generation for Xiaohongshu. No publishing (use rednote-ops for that).
- Document all CLI commands with the new --style and --type parameters
- Document output format (content package in drafts/)
- Remove all MCP references

## Important constraints

- All card rendering must use Pillow ONLY (no API calls for image generation)
- macOS system fonts: `/System/Library/Fonts/STHeiti Medium.ttc` and `/System/Library/Fonts/STHeiti Light.ttc`
- Card size: 1080×1440 (3:4 aspect ratio)
- Chinese text must render perfectly
- Keep the existing venv and dependencies (Pillow, google-genai, requests)
- Don't create test files or README files
