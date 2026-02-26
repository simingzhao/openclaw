#!/usr/bin/env python3
"""小红书内容精修器（Gemini 多类型路由）。"""

import argparse
import json
import os
import sys
from datetime import datetime

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("需要 google-genai: pip install google-genai", file=sys.stderr)
    sys.exit(1)

MODEL_PRIMARY = os.environ.get("REDNOTE_MODEL", "gemini-3.1-pro-preview")
MODEL_FALLBACK = "gemini-3-flash-preview"

CONTENT_TYPES = ["brief", "analysis", "opinion", "tools"]

SYSTEM_PROMPTS = {
    "brief": """你是一个小红书AI日报的内容编辑。你的任务是从AI领域巡逻摘要中，挑选最有价值的新闻，精修成小红书风格卡片文案。

严格输出 JSON，不要输出任何额外文本。格式：
{
  "cover_title": "AI日报 MM.DD",
  "cover_subtitle": "一句话钩子（<=10字）",
  "post_title": "帖子标题（<=20字）",
  "post_body": "帖子正文（<=800字，不含tags）",
  "tags": ["AI", "人工智能", "科技"],
  "items": [
    {
      "title": "卡片标题（<=12字）",
      "body": "核心观点行1\\n核心观点行2\\n---\\n关键数据行1\\n---\\n金句行1"
    }
  ]
}

要求：
1. 只选5-7条最有价值信息。
2. items[].body 使用 --- 分成 3 段（核心观点/关键数据/金句）。
3. 每行短句，口语化、有态度。
4. tags 3-5个且必须包含 AI。""",
    "analysis": """你是小红书深度分析写手。你需要围绕一个最值得讨论的主题做深挖。

严格输出 JSON，不要输出任何额外文本。格式：
{
  "title": "分析标题（<=24字）",
  "key_quote": "核心金句（1句）",
  "sections": [
    {
      "heading": "小节标题",
      "points": ["要点1", "要点2", "要点3"],
      "quote": "该小节金句"
    }
  ],
  "post_body": "完整正文（<=1200字）",
  "tags": ["AI", "人工智能", "趋势"]
}

要求：
1. 只做一个主题深挖，不做新闻拼盘。
2. sections 建议 3-5 个，每节 points 3-5 条。
3. 用事实、数据、观点并重；语言适合小红书阅读。
4. post_body 要有结论性判断。""",
    "opinion": """你是小红书热点评论写手。请输出短、狠、清晰的观点文案。

严格输出 JSON，不要输出任何额外文本。格式：
{
  "title": "观点标题（<=20字）",
  "body": "短评正文（150-350字，锋利但不过激）",
  "tags": ["AI", "观点", "科技"]
}

要求：
1. 只表达一个核心判断。
2. 文风有态度，避免空话套话。
3. 不生成 items，不生成 sections。""",
    "tools": """你是小红书工具评测写手。请输出可直接发布的工具推荐清单。

严格输出 JSON，不要输出任何额外文本。格式：
{
  "title": "工具清单标题（<=24字）",
  "tools": [
    {
      "name": "工具名",
      "description": "核心能力与适用场景（1-2句）",
      "verdict": "一句结论（值不值得用）"
    }
  ],
  "post_body": "正文（<=900字）",
  "tags": ["AI", "工具推荐", "效率"]
}

要求：
1. tools 数量 4-8 个。
2. 结论必须明确，不中庸。
3. 写出使用门槛和适合人群。""",
}


def _build_user_prompt(digest_text: str, date_str: str, content_type: str) -> str:
    guidance = {
        "brief": "请从素材中挑选5-7条最有价值新闻，产出日报卡片内容。",
        "analysis": "请提炼一个值得深挖的主题并完成结构化分析。",
        "opinion": "请针对最有争议的话题写一段短评。",
        "tools": "请挑选最值得推荐的工具并给出明确结论。",
    }
    return (
        f"今天日期：{date_str}\n"
        f"内容类型：{content_type}\n"
        f"任务：{guidance[content_type]}\n\n"
        "素材如下：\n"
        "---\n"
        f"{digest_text}\n"
        "---\n\n"
        "严格按照系统提示要求输出 JSON。确保 JSON 完整可解析，不要截断。"
    )


def _extract_json(text: str) -> str:
    data = text.strip()
    if "```json" in data:
        data = data.split("```json", 1)[1]
        data = data.split("```", 1)[0]
    elif "```" in data:
        data = data.split("```", 1)[1]
        data = data.split("```", 1)[0]
    return data.strip()


def _validate_output(data: dict, content_type: str) -> None:
    required_by_type = {
        "brief": ["items", "post_body"],
        "analysis": ["title", "sections", "key_quote", "post_body"],
        "opinion": ["title", "body", "tags"],
        "tools": ["title", "tools", "post_body", "tags"],
    }

    missing = [k for k in required_by_type[content_type] if k not in data]
    if missing:
        print(f"❌ 输出缺少字段: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    if content_type == "brief":
        if not isinstance(data.get("items"), list) or not data["items"]:
            print("❌ brief 输出 items 为空", file=sys.stderr)
            sys.exit(1)
    elif content_type == "analysis":
        if not isinstance(data.get("sections"), list) or not data["sections"]:
            print("❌ analysis 输出 sections 为空", file=sys.stderr)
            sys.exit(1)
    elif content_type == "tools":
        if not isinstance(data.get("tools"), list) or not data["tools"]:
            print("❌ tools 输出 tools 为空", file=sys.stderr)
            sys.exit(1)


def generate_content(
    digest_text: str,
    date_str: str | None = None,
    content_type: str = "brief",
) -> dict:
    """调用 Gemini 进行多类型内容生成。"""
    if content_type not in CONTENT_TYPES:
        raise ValueError(f"Unsupported content_type: {content_type}")

    if not date_str:
        date_str = datetime.now().strftime("%m.%d")

    client = genai.Client()
    user_prompt = _build_user_prompt(digest_text, date_str, content_type)
    system_prompt = SYSTEM_PROMPTS[content_type]

    model = MODEL_PRIMARY
    response = None

    for attempt_model in [MODEL_PRIMARY, MODEL_FALLBACK]:
        try:
            print(f"🤖 尝试模型: {attempt_model}")
            response = client.models.generate_content(
                model=attempt_model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.7,
                    max_output_tokens=8192,
                ),
            )
            model = attempt_model
            break
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e):
                print(f"⚠️ {attempt_model} 不可用 (503)，尝试 fallback...")
                continue
            raise
    else:
        print("❌ 所有模型都不可用", file=sys.stderr)
        sys.exit(1)

    if response is None or not response.text:
        print("❌ 模型返回为空", file=sys.stderr)
        sys.exit(1)

    print(f"✅ 使用模型: {model}")

    raw = _extract_json(response.text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析失败: {e}", file=sys.stderr)
        print(f"原始输出片段:\n{response.text[:500]}", file=sys.stderr)
        sys.exit(1)

    _validate_output(data, content_type)

    if content_type == "brief":
        print(f"✅ 生成 brief 内容: {len(data.get('items', []))} 条卡片")
    elif content_type == "analysis":
        print(f"✅ 生成 analysis 内容: {len(data.get('sections', []))} 个章节")
    elif content_type == "tools":
        print(f"✅ 生成 tools 内容: {len(data.get('tools', []))} 个工具")
    else:
        print("✅ 生成 opinion 内容")

    return data


def load_digest(path: str) -> str:
    """读取 digest 文件。"""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_latest_digest(workspace: str, source: str = "x") -> tuple[str, str]:
    """从 workspace 加载最新 digest。"""
    today = datetime.now().strftime("%Y-%m-%d")
    date_display = datetime.now().strftime("%m.%d")
    texts = []

    if source in ("x", "both"):
        x_path = os.path.join(workspace, "raw", "x-posts", f"{today}_digest.md")
        if os.path.exists(x_path):
            texts.append(f"## X/Twitter 巡逻\n\n{load_digest(x_path)}")
        else:
            print(f"⚠️ X digest 不存在: {x_path}", file=sys.stderr)

    if source in ("youtube", "both"):
        yt_dir = os.path.join(workspace, "raw", "youtube")
        if os.path.isdir(yt_dir):
            yt_texts = []
            for channel in sorted(os.listdir(yt_dir)):
                sum_dir = os.path.join(yt_dir, channel, "summaries")
                if not os.path.isdir(sum_dir):
                    continue
                for filename in sorted(os.listdir(sum_dir)):
                    if filename.startswith(today) and filename.endswith(".md"):
                        yt_texts.append(load_digest(os.path.join(sum_dir, filename)))
            if yt_texts:
                texts.append("## YouTube 巡逻\n\n" + "\n\n---\n\n".join(yt_texts))

    if not texts:
        print("❌ 没有找到今天的巡逻素材", file=sys.stderr)
        sys.exit(1)

    combined = "\n\n".join(texts)
    if len(combined) > 30000:
        print(f"⚠️ 素材太长（{len(combined)}字），截断至30000字")
        combined = combined[:30000]

    return combined, date_display


def main() -> None:
    parser = argparse.ArgumentParser(description="小红书内容精修器（Gemini 多类型）")
    sub = parser.add_subparsers(dest="command")

    p_file = sub.add_parser("from-file", help="从指定 digest 文件生成")
    p_file.add_argument("--input", "-i", required=True, help="digest 文件路径")
    p_file.add_argument("--date", "-d", help="日期（MM.DD格式）")
    p_file.add_argument("--type", choices=CONTENT_TYPES, default="brief", help="内容类型")
    p_file.add_argument("--output", "-o", help="输出 JSON 路径")

    p_auto = sub.add_parser("auto", help="自动加载最新 digest 生成")
    p_auto.add_argument("--workspace", "-w", default=os.path.expanduser("~/.openclaw/workspace"))
    p_auto.add_argument("--source", "-s", choices=["x", "youtube", "both"], default="both")
    p_auto.add_argument("--date", "-d", help="日期（MM.DD格式）")
    p_auto.add_argument("--type", choices=CONTENT_TYPES, default="brief", help="内容类型")
    p_auto.add_argument("--output", "-o", help="输出 JSON 路径")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "from-file":
        digest_text = load_digest(args.input)
        date_str = args.date or datetime.now().strftime("%m.%d")
    else:
        digest_text, date_str = load_latest_digest(args.workspace, args.source)
        if args.date:
            date_str = args.date

    print(f"📝 素材长度: {len(digest_text)}字")
    print(f"📅 日期: {date_str}")
    print(f"🧩 类型: {args.type}")
    print(f"🤖 模型: {MODEL_PRIMARY} (fallback: {MODEL_FALLBACK})")
    print("⏳ 调用 Gemini 精修中...\n")

    data = generate_content(digest_text, date_str, content_type=args.type)
    output_json = json.dumps(data, ensure_ascii=False, indent=2)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"\n✅ 已保存: {args.output}")
    else:
        print(f"\n{output_json}")


if __name__ == "__main__":
    main()
