#!/usr/bin/env python3
"""小红书 Writer 主流程（仅写作与制图，不负责发布）。"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

# 路径常量
WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
DRAFTS_DIR = os.path.expanduser("~/.openclaw/workspace-rednote-ops/content/drafts")
ICLOUD_DIR = os.path.expanduser(
    "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/OpenClaw_Vault/Rednote"
)

STYLE_CHOICES = ["typography-card", "notes-app", "text-only"]
TYPE_CHOICES = ["brief", "analysis", "opinion", "tools"]

# 导入兄弟模块
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from content_gen import generate_content, load_digest, load_latest_digest
from card_gen import generate_cards


def slugify(text: str) -> str:
    raw = (text or "").strip().lower()
    raw = re.sub(r"[\s_/|]+", "-", raw)
    raw = re.sub(r"[^a-z0-9\u4e00-\u9fff\-]", "", raw)
    raw = re.sub(r"-+", "-", raw).strip("-")
    return raw or "untitled"


def resolve_date_for_dir(date_str: str | None = None) -> str:
    if not date_str:
        return datetime.now().strftime("%Y-%m-%d")

    s = date_str.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s

    m = re.match(r"^(\d{2})[.\-/](\d{2})$", s)
    if m:
        return f"{datetime.now().year}-{m.group(1)}-{m.group(2)}"

    return datetime.now().strftime("%Y-%m-%d")


def get_title_for_dir(data: dict) -> str:
    return (
        data.get("post_title")
        or data.get("cover_title")
        or data.get("title")
        or "rednote-draft"
    )


def make_output_dir(title: str, date_str: str | None = None) -> str:
    date_part = resolve_date_for_dir(date_str)
    dir_name = f"{date_part}_{slugify(title)}"
    out_dir = os.path.join(DRAFTS_DIR, dir_name)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def save_content_files(out_dir: str, data: dict) -> tuple[str, str]:
    """保存内容元数据（content.json + content.txt）。"""
    json_path = os.path.join(out_dir, "content.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    txt_path = os.path.join(out_dir, "content.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"标题: {get_title_for_dir(data)}\n")
        if data.get("cover_title") or data.get("cover_subtitle"):
            f.write(f"封面: {data.get('cover_title', '')} | {data.get('cover_subtitle', '')}\n")
        if data.get("post_title"):
            f.write(f"帖子标题: {data.get('post_title')}\n")
        if data.get("tags"):
            f.write(f"Tags: {', '.join(data.get('tags', []))}\n")

        f.write(f"\n{'=' * 50}\n正文:\n{'=' * 50}\n\n")
        if data.get("post_body"):
            f.write(data.get("post_body", ""))
        elif data.get("body"):
            f.write(data.get("body", ""))

        items = data.get("items") or []
        sections = data.get("sections") or []
        tools = data.get("tools") or []

        if items:
            f.write(f"\n\n{'=' * 50}\n卡片项:\n{'=' * 50}\n\n")
            for i, item in enumerate(items, 1):
                f.write(f"[{i}] {item.get('title', '')}\n")
                f.write(f"{item.get('body', '')}\n\n")

        if sections:
            f.write(f"\n\n{'=' * 50}\n章节:\n{'=' * 50}\n\n")
            for i, sec in enumerate(sections, 1):
                f.write(f"[{i}] {sec.get('heading', '')}\n")
                for point in sec.get("points", []):
                    f.write(f"- {point}\n")
                if sec.get("quote"):
                    f.write(f"  金句: {sec.get('quote')}\n")
                f.write("\n")

        if tools:
            f.write(f"\n\n{'=' * 50}\n工具:\n{'=' * 50}\n\n")
            for i, tool in enumerate(tools, 1):
                f.write(f"[{i}] {tool.get('name', '')}\n")
                if tool.get("description"):
                    f.write(f"  说明: {tool.get('description')}\n")
                if tool.get("verdict"):
                    f.write(f"  结论: {tool.get('verdict')}\n")
                f.write("\n")

    print(f"💾 内容JSON: {json_path}")
    print(f"💾 内容文本: {txt_path}")
    return json_path, txt_path


def save_meta(
    out_dir: str,
    style_id: str,
    content_type: str,
    card_count: int,
) -> str:
    meta = {
        "style_id": style_id,
        "content_type": content_type,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "card_count": card_count,
    }
    meta_path = os.path.join(out_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"💾 元信息: {meta_path}")
    return meta_path


def sync_to_icloud(out_dir: str) -> None:
    """同步到 iCloud Obsidian Vault。"""
    os.makedirs(ICLOUD_DIR, exist_ok=True)
    dir_name = os.path.basename(out_dir)
    dest = os.path.join(ICLOUD_DIR, dir_name)

    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(out_dir, dest)
    print(f"☁️ iCloud同步: {dest}")


def pipeline_daily_brief(args):
    """日报完整 Pipeline: 素材 -> content_gen -> card_gen -> save。"""
    print("=" * 60)
    print("📡 Step 1: 加载巡逻素材")
    print("=" * 60)

    if args.input:
        digest_text = load_digest(args.input)
        date_str = args.date or datetime.now().strftime("%m.%d")
    else:
        digest_text, date_str = load_latest_digest(args.workspace, args.source)
        if args.date:
            date_str = args.date

    print(f"✅ 素材长度: {len(digest_text)}字\n")

    print("=" * 60)
    print("🤖 Step 2: Gemini 精修内容")
    print("=" * 60)

    data = generate_content(digest_text, date_str, content_type=args.type)
    print()

    print("=" * 60)
    print("🎨 Step 3: 生成卡片")
    print("=" * 60)

    out_dir = make_output_dir(get_title_for_dir(data), date_str)
    cards_dir = os.path.join(out_dir, "cards")
    card_paths = generate_cards(style_id=args.style, content_data=data, output_dir=cards_dir)
    data["card_paths"] = card_paths
    print(f"✅ 共 {len(card_paths)} 张卡片\n")

    print("=" * 60)
    print("💾 Step 4: 保存内容")
    print("=" * 60)

    save_content_files(out_dir, data)
    save_meta(out_dir, args.style, args.type, len(card_paths))
    print()

    print("=" * 60)
    print("☁️ Step 5: iCloud 同步")
    print("=" * 60)

    sync_to_icloud(out_dir)
    print(f"\n📂 输出目录: {out_dir}")
    return out_dir, data


def pipeline_from_json(args):
    """从已有 content.json 生成卡片并保存到草稿目录。"""
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    out_dir = make_output_dir(get_title_for_dir(data), args.date)
    cards_dir = os.path.join(out_dir, "cards")
    card_paths = generate_cards(style_id=args.style, content_data=data, output_dir=cards_dir)

    data["card_paths"] = card_paths
    save_content_files(out_dir, data)
    save_meta(out_dir, args.style, args.type, len(card_paths))
    sync_to_icloud(out_dir)

    print(f"\n📂 输出目录: {out_dir}")
    return out_dir, data


def main():
    parser = argparse.ArgumentParser(description="小红书 Writer Pipeline（写作+制图）")
    sub = parser.add_subparsers(dest="command")

    # daily-brief
    p_daily = sub.add_parser("daily-brief", help="日报完整 Pipeline")
    p_daily.add_argument("--workspace", "-w", default=WORKSPACE)
    p_daily.add_argument("--source", "-s", choices=["x", "youtube", "both"], default="both")
    p_daily.add_argument("--input", "-i", help="手动指定 digest 文件（覆盖 auto 模式）")
    p_daily.add_argument("--date", "-d", help="日期（MM.DD 或 YYYY-MM-DD）")
    p_daily.add_argument("--style", choices=STYLE_CHOICES, default="typography-card")
    p_daily.add_argument("--type", choices=TYPE_CHOICES, default="brief")

    # from-json
    p_json = sub.add_parser("from-json", help="从已有 content.json 生成卡片")
    p_json.add_argument("--input", "-i", required=True, help="content.json 路径")
    p_json.add_argument("--date", "-d", help="日期（MM.DD 或 YYYY-MM-DD）")
    p_json.add_argument("--style", choices=STYLE_CHOICES, default="typography-card")
    p_json.add_argument("--type", choices=TYPE_CHOICES, default="brief")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "daily-brief":
        pipeline_daily_brief(args)
    elif args.command == "from-json":
        pipeline_from_json(args)


if __name__ == "__main__":
    main()
