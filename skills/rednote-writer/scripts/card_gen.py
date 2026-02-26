#!/usr/bin/env python3
"""Multi-style Xiaohongshu card renderer (Pillow only)."""

import argparse
import json
import os
import re
import sys
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

CARD_W, CARD_H = 1080, 1440
FONT_TITLE_PATH = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_BODY_PATH = "/System/Library/Fonts/STHeiti Light.ttc"

STYLE_CHOICES = ["typography-card", "notes-app", "text-only", "hook-cover"]


def _font(size: int, title: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_TITLE_PATH if title else FONT_BODY_PATH
    if not os.path.exists(path):
        raise FileNotFoundError(f"Required font not found: {path}")
    return ImageFont.truetype(path, size)


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def _text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    if not text:
        return 0
    box = font.getbbox(text)
    return box[2] - box[0]


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Wrap text respecting English word boundaries.
    
    Chinese characters can break anywhere; ASCII words stay intact.
    Post-process: merge orphan last lines (≤3 chars) into previous line
    if the result still fits.
    """
    lines: list[str] = []
    for paragraph in (text or "").split("\n"):
        p = paragraph.strip()
        if not p:
            lines.append("")
            continue
        # Tokenize: split into Chinese chars and English/number words
        tokens: list[str] = []
        buf = ""
        for ch in p:
            if ord(ch) < 128 and ch != ' ':
                # ASCII (part of English word or number)
                buf += ch
            else:
                if buf:
                    tokens.append(buf)
                    buf = ""
                if ch == ' ':
                    # Space between words — attach to previous token or skip
                    if tokens:
                        tokens[-1] += ' '
                    continue
                tokens.append(ch)
        if buf:
            tokens.append(buf)

        para_lines: list[str] = []
        current = ""
        for token in tokens:
            candidate = current + token
            if _text_width(candidate, font) <= max_width:
                current = candidate
            else:
                if current:
                    para_lines.append(current.rstrip())
                current = token
        if current:
            para_lines.append(current.rstrip())

        # Anti-orphan: if last line is very short (≤3 chars or only punctuation),
        # try to merge with previous line
        if len(para_lines) >= 2:
            last = para_lines[-1].strip()
            # Merge if last line is ≤3 chars, or is only punctuation
            is_orphan = len(last) <= 3 or all(c in '。，！？；：""''」】）》' for c in last)
            if is_orphan:
                merged = para_lines[-2].rstrip() + last
                if _text_width(merged, font) <= max_width:
                    para_lines[-2] = merged
                    para_lines.pop()
                else:
                    # Can't merge — try to pull one char from previous line
                    prev = para_lines[-2].rstrip()
                    if len(prev) > 4:
                        para_lines[-2] = prev[:-1]
                        para_lines[-1] = prev[-1] + last

        lines.extend(para_lines)
    return lines


def _save(img: Image.Image, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


def _split_sections(text: str) -> list[list[str]]:
    raw_parts = [part.strip() for part in (text or "").split("---")]
    sections: list[list[str]] = []
    for part in raw_parts:
        lines = [ln.strip() for ln in part.splitlines() if ln.strip()]
        if lines:
            sections.append(lines)
    if not sections:
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        if lines:
            sections.append(lines)
    return sections


def _flatten_sections(sections: list[list[str]]) -> list[str]:
    lines: list[str] = []
    for sec in sections:
        lines.extend(sec)
    return lines


def _count_words_and_minutes(content_data: dict) -> tuple[int, int]:
    combined = []
    for key in ["post_body", "body", "key_quote", "title", "cover_title", "cover_subtitle"]:
        if content_data.get(key):
            combined.append(str(content_data[key]))

    for item in content_data.get("items", []) or []:
        combined.append(item.get("title", ""))
        combined.append(item.get("body", ""))

    for sec in content_data.get("sections", []) or []:
        combined.append(sec.get("heading", ""))
        combined.extend(sec.get("points", []) or [])
        combined.append(sec.get("quote", ""))

    for tool in content_data.get("tools", []) or []:
        combined.append(tool.get("name", ""))
        combined.append(tool.get("description", ""))
        combined.append(tool.get("verdict", ""))

    text = "\n".join(combined)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z0-9_]+", text))
    words = cjk + latin
    minutes = max(1, round(words / 280))
    return words, minutes


def _get_title(content_data: dict) -> str:
    return (
        content_data.get("cover_title")
        or content_data.get("title")
        or content_data.get("post_title")
        or "小红书内容草稿"
    )


def _get_subtitle(content_data: dict) -> str:
    if content_data.get("cover_subtitle"):
        return content_data["cover_subtitle"]
    if content_data.get("key_quote"):
        return content_data["key_quote"]
    if content_data.get("post_title") and content_data.get("post_title") != _get_title(content_data):
        return content_data["post_title"]
    tags = content_data.get("tags", []) or []
    if tags:
        return "#" + " #".join(tags[:4])
    return datetime.now().strftime("%Y-%m-%d")


def _collect_blocks(content_data: dict) -> list[dict]:
    blocks: list[dict] = []

    items = content_data.get("items") or []
    for idx, item in enumerate(items, 1):
        body = item.get("body", "")
        blocks.append(
            {
                "index": idx,
                "title": item.get("title") or f"要点 {idx}",
                "sections": _split_sections(body),
                "quote": "",
            }
        )

    sections = content_data.get("sections") or []
    if sections and not blocks:
        for idx, sec in enumerate(sections, 1):
            section_lines = [str(p).strip() for p in (sec.get("points") or []) if str(p).strip()]
            card_sections = [section_lines] if section_lines else []
            quote = str(sec.get("quote") or "").strip()
            if quote:
                card_sections.append([quote])
            blocks.append(
                {
                    "index": idx,
                    "title": sec.get("heading") or f"章节 {idx}",
                    "sections": card_sections,
                    "quote": quote,
                }
            )

    tools = content_data.get("tools") or []
    if tools and not blocks:
        for idx, tool in enumerate(tools, 1):
            lines = []
            desc = str(tool.get("description") or "").strip()
            verdict = str(tool.get("verdict") or "").strip()
            if desc:
                lines.append(desc)
            if verdict:
                lines.append(f"结论：{verdict}")
            blocks.append(
                {
                    "index": idx,
                    "title": tool.get("name") or f"工具 {idx}",
                    "sections": [lines] if lines else [],
                    "quote": "",
                }
            )

    # opinion 型内容默认仅封面，避免生成多卡
    return blocks


def _draw_divider(draw: ImageDraw.ImageDraw, y: int, color: tuple[int, int, int], x1: int = 84, x2: int = CARD_W - 84) -> None:
    draw.line((x1, y, x2, y), fill=color, width=2)


def render_typography_cover(content_data: dict, output_path: str) -> str:
    bg = _hex("F5F0E8")
    title_color = _hex("8B4513")
    body_color = _hex("6B3A0A")
    muted = _hex("9A6A3A")
    divider_color = _hex("D5BFA7")
    accent = _hex("C4923A")

    img = Image.new("RGB", (CARD_W, CARD_H), bg)
    draw = ImageDraw.Draw(img)

    margin = 84
    width = CARD_W - margin * 2

    title = _get_title(content_data)
    subtitle = _get_subtitle(content_data)

    blocks = _collect_blocks(content_data)
    preview_titles = [b["title"] for b in blocks[:6]]
    has_list = bool(preview_titles)

    # Use narrower width to force title into more lines → fills more vertical space
    title_width = int(width * 0.85)

    # Poster-style: large title that fills 40-60% of the card
    for title_size in [160, 140, 120, 100]:
        title_font = _font(title_size, title=True)
        title_lines = _wrap_text(title, title_font, title_width)
        # Want 2-4 lines to fill space; shrink if >4
        if len(title_lines) <= 4:
            # Avoid orphan (single short word/char on last line)
            if len(title_lines) <= 1:
                break
            last = title_lines[-1].strip()
            if len(last) > 2:
                break
    title_line_h = int(title_size * 1.35)

    subtitle_font = _font(56, title=False)
    list_font = _font(46, title=False)
    subtitle_lines = _wrap_text(subtitle, subtitle_font, width)

    # Draw decorative accent bar at top
    draw.rectangle((0, 0, CARD_W, 10), fill=accent)

    # Start from generous top margin
    y = 160

    # Title — big and dominant, left-aligned
    for line in title_lines:
        draw.text((margin, y), line, fill=title_color, font=title_font)
        y += title_line_h

    # Decorative short divider after title
    y += 40
    _draw_divider(draw, y, divider_color, margin, margin + 200)
    y += 50

    # Subtitle — medium size
    for line in subtitle_lines:
        draw.text((margin, y), line, fill=body_color, font=subtitle_font)
        y += 72

    # List items if available
    if has_list:
        y += 40
        _draw_divider(draw, y, divider_color, margin, CARD_W - margin)
        y += 40
        for item in preview_titles:
            for wrapped in _wrap_text(f"• {item}", list_font, width):
                draw.text((margin, y), wrapped, fill=body_color, font=list_font)
                y += 66
            y += 16
            if y > CARD_H - 160:
                break

    # Bottom brand zone — consistent with content cards
    brand_zone_top = max(y + 50, CARD_H - 220)
    draw.rectangle((0, brand_zone_top, CARD_W, CARD_H), fill=accent)
    brand_font_cover = _font(36, title=True)
    brand_text = "探子 · AI观察笔记"
    bw = _text_width(brand_text, brand_font_cover)
    draw.text(((CARD_W - bw) // 2, brand_zone_top + (CARD_H - brand_zone_top - 48) // 2),
              brand_text, fill=_hex("FFFFFF"), font=brand_font_cover)

    return _save(img, output_path)


def render_typography_single_card(title: str, body: str, output_path: str) -> str:
    block = {
        "title": title or "正文",
        "sections": _split_sections(body),
        "quote": "",
    }
    img = _render_typography_content_block(block, index=1, total=1)
    return _save(img, output_path)


def _render_typography_content_block(block: dict, index: int = 0, total: int = 0) -> Image.Image:
    bg = _hex("F5F0E8")
    title_color = _hex("8B4513")
    body_color = _hex("6B3A0A")
    muted = _hex("9A6A3A")
    divider = _hex("D5BFA7")
    accent = _hex("C4923A")
    quote_bg = _hex("EDE5D8")

    img = Image.new("RGB", (CARD_W, CARD_H), bg)
    draw = ImageDraw.Draw(img)

    margin = 84
    width = CARD_W - margin * 2
    y = 100

    # (page indicator is in the bottom brand zone)

    # Title — large, use full width for content cards (narrower only for cover)
    for title_size in [110, 96, 84, 72]:
        title_font = _font(title_size, title=True)
        title_lines = _wrap_text(block.get("title", ""), title_font, width)
        if len(title_lines) <= 3:
            if len(title_lines) <= 1:
                break
            last = title_lines[-1].strip()
            if len(last) > 2:
                break
    title_line_h = int(title_size * 1.3)

    body_font = _font(60, title=False)
    quote_font = _font(50, title=True)

    for line in title_lines:
        draw.text((margin, y), line, fill=title_color, font=title_font)
        y += title_line_h

    # Short divider
    y += 20
    _draw_divider(draw, y, divider, margin, margin + 200)
    y += 44

    # Body sections
    sections = block.get("sections") or []
    # Separate last section as quote if it's short (1 line)
    quote_text = ""
    body_sections = sections
    if len(sections) >= 2:
        last_sec = sections[-1]
        if len(last_sec) == 1 and len(last_sec[0]) <= 30:
            quote_text = last_sec[0]
            body_sections = sections[:-1]

    for sec_idx, section in enumerate(body_sections, 1):
        for line in section:
            for wrapped in _wrap_text(line, body_font, width):
                draw.text((margin, y), wrapped, fill=body_color, font=body_font)
                y += 86
                if y > CARD_H - 300:
                    break
            y += 24  # generous gap between lines
            if y > CARD_H - 300:
                break

        if y > CARD_H - 300:
            break
        y += 20
        if sec_idx < len(body_sections):
            _draw_divider(draw, y, divider, margin, CARD_W - margin)
            y += 36

    # Pull-quote — placed right after body text
    if quote_text:
        y += 40
        qpad = 28
        quote_lines = _wrap_text(f"「{quote_text}」", quote_font, width - qpad * 2)
        qh = len(quote_lines) * 68 + qpad * 2
        draw.rounded_rectangle(
            (margin, y, CARD_W - margin, y + qh),
            radius=16, fill=quote_bg
        )
        qy = y + qpad
        for line in quote_lines:
            draw.text((margin + qpad, qy), line, fill=title_color, font=quote_font)
            qy += 68
        y = qy + qpad

    # Bottom brand zone — fills remaining space with accent color
    # Zone starts after content with moderate gap, minimum height 220px
    brand_zone_top = min(y + 50, CARD_H - 220)
    brand_zone_top = max(brand_zone_top, CARD_H // 2)  # at least half the card for content
    draw.rectangle((0, brand_zone_top, CARD_W, CARD_H), fill=accent)
    # Brand text centered in zone
    brand_font = _font(36, title=True)
    brand_text = "探子 · AI观察笔记"
    bw = _text_width(brand_text, brand_font)
    draw.text(((CARD_W - bw) // 2, brand_zone_top + 60), brand_text,
              fill=_hex("FFFFFF"), font=brand_font)
    # Page indicator
    if index > 0 and total > 0:
        page_font = _font(80, title=True)
        page_text = f"{index}/{total}"
        pw = _text_width(page_text, page_font)
        draw.text(((CARD_W - pw) // 2, brand_zone_top + 120), page_text,
                  fill=_hex("FFFFFF"), font=page_font)

    return img


def render_typography_cards(content_data: dict, output_dir: str) -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    paths: list[str] = []

    cover_path = os.path.join(output_dir, "00_cover.png")
    paths.append(render_typography_cover(content_data, cover_path))

    blocks = _collect_blocks(content_data)
    total = len(blocks)
    for idx, block in enumerate(blocks, 1):
        path = os.path.join(output_dir, f"{idx:02d}.png")
        img = _render_typography_content_block(block, index=idx, total=total)
        paths.append(_save(img, path))

    return paths


def _draw_notes_top_bar(draw: ImageDraw.ImageDraw) -> None:
    gold = _hex("D4A000")
    white = _hex("FFFFFF")

    draw.rectangle((0, 0, CARD_W, 152), fill=white)
    draw.text((48, 56), "< 备忘录", fill=gold, font=_font(38, title=False))

    # Share icon (box + arrow)
    ix = CARD_W - 190
    iy = 52
    draw.rectangle((ix, iy + 20, ix + 46, iy + 66), outline=gold, width=4)
    draw.line((ix + 23, iy - 2, ix + 23, iy + 28), fill=gold, width=4)
    draw.polygon(
        [(ix + 23, iy - 14), (ix + 11, iy + 2), (ix + 35, iy + 2)],
        fill=gold,
    )

    # More icon (three dots)
    mx = CARD_W - 78
    my = 86
    for i in range(3):
        x = mx + i * 16
        draw.ellipse((x, my, x + 8, my + 8), fill=gold)


def _pick_highlight_term(line: str) -> str:
    stop_words = {"今天", "这个", "我们", "他们", "已经", "可以", "然后", "因为", "所以"}
    patterns = [
        r"[A-Za-z][A-Za-z0-9\-+]{1,14}",
        r"\d+(?:\.\d+)?%?",
        r"[\u4e00-\u9fff]{2,6}",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, line):
            if match in stop_words:
                continue
            return match
    return ""


def _draw_highlighted_line(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    line: str,
    font: ImageFont.FreeTypeFont,
    text_color: tuple[int, int, int],
    highlight_color: tuple[int, int, int],
    max_width: int,
) -> int:
    wrapped = _wrap_text(line, font, max_width)
    current_y = y
    for wrapped_line in wrapped:
        term = _pick_highlight_term(wrapped_line)
        if not term:
            draw.text((x, current_y), wrapped_line, fill=text_color, font=font)
            current_y += 72
            continue

        idx = wrapped_line.find(term)
        prefix = wrapped_line[:idx]
        suffix = wrapped_line[idx + len(term) :]

        px = x
        if prefix:
            draw.text((px, current_y), prefix, fill=text_color, font=font)
            px += _text_width(prefix, font)

        tw = _text_width(term, font)
        draw.rounded_rectangle((px - 4, current_y - 4, px + tw + 4, current_y + 60), radius=8, fill=highlight_color)
        draw.text((px, current_y), term, fill=text_color, font=font)
        px += tw

        if suffix:
            draw.text((px, current_y), suffix, fill=text_color, font=font)

        current_y += 72

    return current_y


def _render_notes_cover(content_data: dict) -> Image.Image:
    bg = _hex("FFFFFF")
    text_color = _hex("333333")
    muted = _hex("777777")
    light_gray = _hex("E9E9E9")

    img = Image.new("RGB", (CARD_W, CARD_H), bg)
    draw = ImageDraw.Draw(img)

    _draw_notes_top_bar(draw)

    margin = 70
    width = CARD_W - margin * 2

    blocks = _collect_blocks(content_data)
    preview = [b["title"] for b in blocks[:5]]
    has_list = bool(preview)

    title = _get_title(content_data)
    subtitle = _get_subtitle(content_data)

    # Use narrower width for title to force more lines
    title_width = int(width * 0.88)

    # Big poster-style title — aim for 2-4 lines
    for title_size in [150, 130, 110, 96, 80]:
        title_font = _font(title_size, title=True)
        title_lines = _wrap_text(title, title_font, title_width)
        if len(title_lines) <= 4:
            if len(title_lines) <= 1:
                break
            last = title_lines[-1].strip()
            if len(last) > 2:
                break
    title_line_h = int(title_size * 1.35)

    subtitle_font = _font(52, title=False)
    body_font = _font(48, title=False)
    footer_font = _font(28, title=False)
    subtitle_lines = _wrap_text(subtitle, subtitle_font, width)

    # Fixed layout below top bar
    y = 210

    # Title
    for line in title_lines:
        draw.text((margin, y), line, fill=text_color, font=title_font)
        y += title_line_h

    # Divider
    y += 36
    draw.line((margin, y, CARD_W - margin, y), fill=light_gray, width=2)
    y += 40

    # Subtitle
    for line in subtitle_lines:
        draw.text((margin, y), line, fill=muted, font=subtitle_font)
        y += 68

    if has_list:
        y += 36
        body_line_h = 70
        body_gap = 18
        for item in preview:
            if y > CARD_H - 160:
                break
            for wrapped in _wrap_text(f"• {item}", body_font, width):
                draw.text((margin, y), wrapped, fill=text_color, font=body_font)
                y += body_line_h
            y += body_gap
    else:
        y += 20
        now_str = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        draw.text((margin, y), now_str, fill=_hex("BBBBBB"), font=_font(34, title=False))

    # Footer
    draw.text((margin, CARD_H - 84), "探子 · AI观察笔记", fill=muted, font=footer_font)
    return img


def _render_notes_content_block(block: dict, index: int) -> Image.Image:
    bg = _hex("FFFFFF")
    text_color = _hex("333333")
    muted = _hex("666666")
    yellow = _hex("FFE066")
    green = _hex("90EE90")

    img = Image.new("RGB", (CARD_W, CARD_H), bg)
    draw = ImageDraw.Draw(img)

    _draw_notes_top_bar(draw)

    margin = 70
    width = CARD_W - margin * 2
    y = 210

    # Bigger fonts for content cards
    title_font = _font(88, title=True)
    body_font = _font(56, title=False)

    # Title with index
    title_text = f"{index:02d} · {block.get('title', '')}"
    for line in _wrap_text(title_text, title_font, width):
        draw.text((margin, y), line, fill=text_color, font=title_font)
        y += 110

    y += 10
    draw.line((margin, y, CARD_W - margin, y), fill=_hex("E9E9E9"), width=3)
    y += 40

    lines = [ln for ln in _flatten_sections(block.get("sections") or []) if ln.strip()]
    lines = lines[:6]

    if not lines:
        lines = ["本卡片无额外内容", "请查看正文文案"]

    for idx, line in enumerate(lines):
        color = yellow if idx % 2 == 0 else green
        y = _draw_highlighted_line(draw, margin, y, line, body_font, text_color, color, width)
        y += 8  # extra gap between lines
        if y > CARD_H - 140:
            break

    draw.text((margin, CARD_H - 84), "探子 · AI观察笔记", fill=muted, font=_font(28, title=False))
    return img


def render_notes_app_cards(content_data: dict, output_dir: str) -> list[str]:
    os.makedirs(output_dir, exist_ok=True)
    paths: list[str] = []

    cover_path = os.path.join(output_dir, "00_cover.png")
    paths.append(_save(_render_notes_cover(content_data), cover_path))

    blocks = _collect_blocks(content_data)
    for idx, block in enumerate(blocks, 1):
        path = os.path.join(output_dir, f"{idx:02d}.png")
        paths.append(_save(_render_notes_content_block(block, idx), path))

    return paths


def render_text_only_cover(content_data: dict, output_dir: str) -> list[str]:
    os.makedirs(output_dir, exist_ok=True)

    top = _hex("F5F6F2")
    bottom = _hex("E2E6EC")

    img = Image.new("RGB", (CARD_W, CARD_H), top)
    draw = ImageDraw.Draw(img)

    # Soft vertical gradient
    for y in range(CARD_H):
        ratio = y / (CARD_H - 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, CARD_W, y), fill=color)

    margin = 90
    width = CARD_W - margin * 2

    brand_font = _font(30, title=False)

    title = _get_title(content_data)
    subtitle = _get_subtitle(content_data)

    # Use narrower width to force more title lines
    title_width = int(width * 0.82)

    # Big poster title — aim for 2-4 lines
    for title_size in [160, 140, 120, 100]:
        title_font = _font(title_size, title=True)
        title_lines = _wrap_text(title, title_font, title_width)
        if len(title_lines) <= 4:
            if len(title_lines) <= 1:
                break
            last = title_lines[-1].strip()
            if len(last) > 2:
                break
    title_line_h = int(title_size * 1.4)

    subtitle_font = _font(56, title=False)
    subtitle_lines = _wrap_text(subtitle, subtitle_font, width)

    # Fixed top-down layout
    y = 240

    # Decorative short accent line
    draw.line((margin, y - 50, margin + 100, y - 50), fill=_hex("A0A8B0"), width=4)

    # Title — bold, fills the canvas
    for line in title_lines:
        draw.text((margin, y), line, fill=_hex("1A1A1A"), font=title_font)
        y += title_line_h

    # Generous gap
    y += 60

    # Subtitle — also bigger
    for line in subtitle_lines:
        draw.text((margin, y), line, fill=_hex("555555"), font=subtitle_font)
        y += 72

    # Footer
    draw.line((margin, CARD_H - 180, CARD_W - margin, CARD_H - 180), fill=_hex("C8CCD2"), width=2)
    draw.text((margin, CARD_H - 136), "探子 · AI观察笔记", fill=_hex("999999"), font=brand_font)

    cover_path = os.path.join(output_dir, "00_cover.png")
    return [_save(img, cover_path)]


def _tokenize_cover_lines(text: str) -> list[str]:
    """Split cover_title by explicit newlines. Each line is rendered separately."""
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def _find_highlight_word(line: str) -> str | None:
    """Find the most highlight-worthy word in a line.

    Priority: dollar amounts > English brand names (3+ chars) > large numbers.
    Skip tiny words like 'AI' (too small to highlight effectively).
    """
    # Dollar amounts first (most impactful)
    for m in re.finditer(r"\$[\d,.]+[KkMm]?", line):
        return m.group()
    # English brand names (3+ chars to avoid tiny highlights like "AI")
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9+#.]{2,20}", line):
        word = m.group()
        if word[0].isupper() or word.isupper():
            return word
    # Plain large numbers (3+ digits)
    for m in re.finditer(r"\d[\d,.]{2,}", line):
        return m.group()
    return None


def render_hook_cover(content_data: dict, output_path: str) -> str:
    """Render a hook-style cover: big bold text, one highlight, decorative quotes.

    Inspired by high-performing XHS covers: minimal, bold, curiosity-driven.
    """
    # Colors
    bg = _hex("F5F0E8")
    text_color = (45, 42, 38)  # #2D2A26 warm charcoal
    quote_color = (168, 184, 156)  # #A8B89C sage green
    highlight_bg = (166, 222, 120)  # #A6DE78 vivid lime — visible at thumbnail
    footer_color = (170, 165, 155)

    img = Image.new("RGB", (CARD_W, CARD_H), bg)
    draw = ImageDraw.Draw(img)

    margin = 90
    title = _get_title(content_data)
    lines = _tokenize_cover_lines(title)
    if not lines:
        lines = [title]

    # --- Determine font size ---
    # Must fit: 1) vertically in 40-65% of card  2) horizontally within margins
    target_top = int(CARD_H * 0.15)
    target_bottom = int(CARD_H * 0.68)
    available_h = target_bottom - target_top
    max_text_w = CARD_W - margin * 2  # usable width
    n_lines = len(lines)

    chosen_size = 100
    for size in [150, 140, 130, 120, 110, 100, 90, 80]:
        test_font = _font(size, title=True)
        line_h = int(size * 1.55)
        total_h = n_lines * line_h
        # Check vertical fit
        if total_h > available_h:
            continue
        # Check horizontal fit: every line must fit within margins
        all_fit = True
        for ln in lines:
            if _text_width(ln, test_font) > max_text_w:
                all_fit = False
                break
        if all_fit:
            chosen_size = size
            break

    title_font = _font(chosen_size, title=True)
    line_h = int(chosen_size * 1.55)

    # Vertically center text in the card (true center, slightly above for optical balance)
    total_text_h = n_lines * line_h
    # Place center of text block at 46% of card height
    y_start = int(CARD_H * 0.46) - total_text_h // 2
    y_start = max(int(CARD_H * 0.15), y_start)  # floor at 15%

    # --- Draw decorative opening quote mark (above first line) ---
    quote_font = _font(72, title=False)
    draw.text((margin - 10, y_start - 80), "\u201c", fill=quote_color, font=quote_font)

    # --- Draw each line with optional highlight ---
    # Track if we've highlighted one word already
    highlighted = False
    y = y_start

    for line in lines:
        hw = None
        if not highlighted:
            hw = _find_highlight_word(line)

        if hw:
            highlighted = True
            # Find position of highlight word
            idx = line.find(hw)
            prefix = line[:idx]
            suffix = line[idx + len(hw):]

            x = margin
            # Draw prefix
            if prefix:
                draw.text((x, y), prefix, fill=text_color, font=title_font)
                x += _text_width(prefix, title_font)

            # Draw highlight background — covers bottom 45% of text height
            hw_width = _text_width(hw, title_font)
            pad_x = 10
            hl_top = y + int(chosen_size * 0.45)
            hl_bottom = y + int(chosen_size * 1.08)
            draw.rounded_rectangle(
                (x - pad_x, hl_top, x + hw_width + pad_x, hl_bottom),
                radius=6,
                fill=highlight_bg,
            )
            # Draw highlight word
            draw.text((x, y), hw, fill=text_color, font=title_font)
            x += hw_width

            # Draw suffix
            if suffix:
                draw.text((x, y), suffix, fill=text_color, font=title_font)
        else:
            draw.text((margin, y), line, fill=text_color, font=title_font)

        y += line_h

    # --- Draw decorative closing dash ---
    dash_y = y + 15
    dash_x = margin + _text_width(lines[-1] if lines else "", title_font) + 30
    dash_x = min(dash_x, CARD_W - margin - 60)
    draw.line((dash_x, dash_y, dash_x + 50, dash_y), fill=quote_color, width=3)

    # --- Footer ---
    footer_font = _font(28, title=False)
    draw.text((margin, CARD_H - 90), "探子 · AI观察笔记", fill=footer_color, font=footer_font)

    return _save(img, output_path)


def render_hook_cover_cards(content_data: dict, output_dir: str) -> list[str]:
    """Hook-cover style only generates a single cover image."""
    os.makedirs(output_dir, exist_ok=True)
    cover_path = os.path.join(output_dir, "00_cover.png")
    render_hook_cover(content_data, cover_path)
    return [cover_path]


def render_text_only_cover_card(title: str, subtitle: str, output_path: str) -> str:
    data = {"title": title, "cover_subtitle": subtitle}
    tmp_dir = os.path.dirname(output_path) or "."
    generated = render_text_only_cover(data, tmp_dir)
    # rename/move generated cover into requested output path if needed
    src = generated[0]
    if os.path.abspath(src) != os.path.abspath(output_path):
        os.replace(src, output_path)
    return output_path


def render_typography_cards_from_data(content_data: dict, output_dir: str) -> list[str]:
    return render_typography_cards(content_data, output_dir)


def render_notes_app_cards_from_data(content_data: dict, output_dir: str) -> list[str]:
    return render_notes_app_cards(content_data, output_dir)


def generate_cards(style_id: str, content_data: dict, output_dir: str) -> list[str]:
    """Main entry point. Dispatches to style-specific renderer."""
    renderers = {
        "typography-card": render_typography_cards,
        "notes-app": render_notes_app_cards,
        "text-only": render_text_only_cover,
        "hook-cover": render_hook_cover_cards,
    }
    renderer = renderers.get(style_id, render_typography_cards)
    return renderer(content_data, output_dir)


def generate_cards_from_data(content_data: dict, output_dir: str, style_id: str = "typography-card") -> list[str]:
    return generate_cards(style_id=style_id, content_data=content_data, output_dir=output_dir)


def generate_cards_from_json(json_path: str, output_dir: str, style_id: str = "typography-card") -> list[str]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return generate_cards(style_id=style_id, content_data=data, output_dir=output_dir)


def generate_card(style_id: str, title: str, body: str, output_path: str) -> str:
    if style_id == "text-only":
        return render_text_only_cover_card(title, "", output_path)
    if style_id == "notes-app":
        block = {"title": title, "sections": _split_sections(body)}
        img = _render_notes_content_block(block, 1)
        return _save(img, output_path)

    return render_typography_single_card(title=title, body=body, output_path=output_path)


def generate_cover(style_id: str, title: str, subtitle: str, output_path: str) -> str:
    data = {"cover_title": title, "cover_subtitle": subtitle}
    if style_id == "hook-cover":
        return render_hook_cover(data, output_path)
    if style_id == "notes-app":
        return _save(_render_notes_cover(data), output_path)
    if style_id == "text-only":
        return render_text_only_cover_card(title, subtitle, output_path)
    return render_typography_cover(data, output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-style RedNote card renderer")
    sub = parser.add_subparsers(dest="command")

    p_batch = sub.add_parser("batch", help="Batch generate cards from content.json")
    p_batch.add_argument("-i", "--input", required=True, help="Path to content.json")
    p_batch.add_argument("-o", "--output-dir", required=True, help="Output card directory")
    p_batch.add_argument("--style", choices=STYLE_CHOICES, default="typography-card")

    p_card = sub.add_parser("card", help="Generate one card")
    p_card.add_argument("--style", choices=STYLE_CHOICES, default="typography-card")
    p_card.add_argument("-t", "--title", required=True)
    p_card.add_argument("-b", "--body", required=True)
    p_card.add_argument("-o", "--output", required=True)

    p_cover = sub.add_parser("cover", help="Generate one cover")
    p_cover.add_argument("--style", choices=STYLE_CHOICES, default="typography-card")
    p_cover.add_argument("-t", "--title", required=True)
    p_cover.add_argument("-s", "--subtitle", default="")
    p_cover.add_argument("-o", "--output", required=True)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "batch":
        paths = generate_cards_from_json(args.input, args.output_dir, style_id=args.style)
        print(json.dumps(paths, ensure_ascii=False, indent=2))
        return

    if args.command == "card":
        path = generate_card(args.style, args.title, args.body, args.output)
        print(path)
        return

    if args.command == "cover":
        path = generate_cover(args.style, args.title, args.subtitle, args.output)
        print(path)


if __name__ == "__main__":
    main()
