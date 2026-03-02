#!/usr/bin/env python3
"""
de_ai.py — 去AI味模块

用 Gemini 把 AI 生成的小红书文案改写成真人口语化风格。
支持通过 --writing-style 参数传入不同的热帖写作风格。

用法：
  # 从 content.json 去AI味
  $VENV de_ai.py --input content.json --output content_deai.json

  # 指定写作风格
  $VENV de_ai.py --input content.json --writing-style 闺蜜唠嗑

  # 从 stdin 读取正文文本，只输出改写后的正文
  echo "正文内容" | $VENV de_ai.py --text-only

  # 列出可用写作风格
  $VENV de_ai.py --list-styles
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("❌ 需要 google-genai: pip install google-genai", file=sys.stderr)
    sys.exit(1)

MODEL_PRIMARY = os.environ.get("DEAI_MODEL", "gemini-3.1-pro-preview")
MODEL_FALLBACK = "gemini-3-flash-preview"

SCRIPT_DIR = Path(__file__).parent
STYLES_PATH = SCRIPT_DIR.parent.parent.parent.parent / ".openclaw" / "workspace-rednote-ops" / "knowledge" / "styles" / "writing-styles.json"
# fallback: 相对于 workspace
STYLES_PATH_ALT = Path(os.path.expanduser("~/.openclaw/workspace-rednote-ops/knowledge/styles/writing-styles.json"))


# ═══════════════════════════════════════════════════════════════
# 写作风格加载
# ═══════════════════════════════════════════════════════════════

def load_writing_styles() -> dict:
    """加载写作风格库。"""
    for p in [STYLES_PATH, STYLES_PATH_ALT]:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    return {"styles": []}


def get_style_prompt(style_id: str | None) -> str:
    """获取指定风格的 prompt 片段。如果未指定或找不到，返回默认。"""
    if not style_id:
        return _DEFAULT_STYLE_PROMPT

    lib = load_writing_styles()
    for s in lib.get("styles", []):
        if s["id"] == style_id or s.get("name") == style_id:
            return s.get("prompt", _DEFAULT_STYLE_PROMPT)

    print(f"⚠️ 未找到写作风格 '{style_id}'，使用默认风格", file=sys.stderr)
    return _DEFAULT_STYLE_PROMPT


_DEFAULT_STYLE_PROMPT = """写作风格要求：
- 像跟朋友在奶茶店聊天一样说话
- 短句为主，一句话不超过20个字
- 多用"说白了""讲真""你想想""举个栗子"这种口头禅
- 可以用网络流行语但别硬凹
- 偶尔自嘲，偶尔毒舌，但不要刻薄"""


# ═══════════════════════════════════════════════════════════════
# 本土化规则
# ═══════════════════════════════════════════════════════════════

LOCALIZATION_RULES = """
## 本土化规则（死规则，必须遵守）

1. **IM工具替换**：
   - WhatsApp → 企业微信/微信
   - Telegram → 钉钉/飞书
   - Discord → 飞书/钉钉群
   - Slack → 飞书/钉钉
   - iMessage → 微信
   - 如果泛指多平台，说"微信、钉钉、飞书"
   
2. **产品/服务替换**：
   - Google → 百度（搜索场景）/ Google（技术场景可保留但要加注）
   - Gmail → 邮箱
   - Google Docs → 腾讯文档/飞书文档
   - Notion → 飞书多维表格/语雀
   - 如果是开发者工具（GitHub/VS Code等），可以保留
   
3. **AI产品可以保留原名的**：
   - ChatGPT、Claude、Gemini、OpenClaw — 这些是核心内容，保留
   - Anthropic、OpenAI — 公司名可以提
   
4. **货币**：
   - $xxx → 人民币xxx元 或 保留美元但加"约合人民币xxx"
   - 也可以用"月入过万""月入五位数"这种模糊但有冲击力的说法

5. **绝不能出现的**：
   - VPN/翻墙/梯子相关暗示
   - 任何政治敏感话题
   - "在国内不能用"这类表述（换成正面说"用XX替代"）

6. **结尾引导规则**：
   - 如果原文末尾有"评论区扣【xxx】，我私信你"这类钩子 → 必须改成讨论引导
   - 改成类似："你们觉得呢？评论区聊聊👇" / "你试过吗？效果怎么样？" / "觉得有用记得点赞关注🔥"
   - 不要出现任何"私信""扣关键词""发你""送你"的字眼
"""


# ═══════════════════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════════════════

def build_system_prompt(style_prompt: str) -> str:
    return f"""你是一个小红书文案改写专家。你的任务是把AI生成的文案改写成真人写的、口语化的、接地气的风格。

## 核心原则
1. **去掉一切AI味** — 不要"首先/其次/最后"，不要"值得注意的是"，不要"总的来说"，不要"在当今xxx背景下"
2. **去掉一切官腔** — 不要"赋能""矩阵""生态""抓手""颗粒度""底层逻辑"
3. **去掉一切空话** — 每句话必须有信息量，删掉所有废话和过渡句
4. **保持原文信息量** — 改风格不改内容，关键数据、步骤、观点全部保留
5. **保持原文结构** — 段落划分、emoji使用、钩子部分保持一致

## 视角规则（非常重要）
- **默认用客观分析视角**，像一个有判断力的观察者/分析师在拆解，不要动不动就"我试了""我踩过坑""说实话我当初也…"
- 可以偶尔带一句个人判断（"这个我觉得靠谱""这个有点悬"），但不要通篇都是第一人称经历
- 用数据、案例、逻辑说话，而不是"我的亲身经历"
- 如果原文本身就是第一人称日记体（比如"搞钱日记"风格），可以适度保留，但也不要每段都"我我我"

{style_prompt}

{LOCALIZATION_RULES}

## 输出要求
- 如果输入是 JSON，输出也必须是 JSON，只改 post_body、post_title、cover_title 三个字段
- 如果输入是纯文本，输出改写后的纯文本
- post_title 改写后仍然 ≤ 20字
- post_body 改写后仍然 600-950字
- **严格输出改写结果，不要输出解释或评论**"""


# ═══════════════════════════════════════════════════════════════
# Gemini 调用
# ═══════════════════════════════════════════════════════════════

def call_gemini(system_prompt: str, user_prompt: str) -> str | None:
    """调用 Gemini 进行去AI味改写。"""
    client = genai.Client()

    for model in [MODEL_PRIMARY, MODEL_FALLBACK]:
        try:
            print(f"  🤖 de-AI模型: {model}", file=sys.stderr)
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.8,  # 稍高温度，鼓励更自然的表达
                    max_output_tokens=8192,
                ),
            )
            if response and response.text:
                print(f"  ✅ de-AI完成 ({model})", file=sys.stderr)
                return response.text
        except Exception as e:
            if any(k in str(e) for k in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED"]):
                print(f"  ⚠️ {model} 不可用: {e}", file=sys.stderr)
                continue
            print(f"  ❌ {model} 错误: {e}", file=sys.stderr)
            continue

    print("❌ 所有模型都不可用", file=sys.stderr)
    return None


def _extract_json(text: str) -> str:
    """从 Gemini 输出中提取 JSON。"""
    raw = text.strip()
    if "```json" in raw:
        raw = raw.split("```json", 1)[1]
        raw = raw.split("```", 1)[0]
    elif "```" in raw:
        raw = raw.split("```", 1)[1]
        raw = raw.split("```", 1)[0]
    return raw.strip()


def _fix_json_newlines(raw: str) -> str:
    """修复 JSON string value 中的真实换行。"""
    result = []
    in_string = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == '\\' and in_string and i + 1 < len(raw):
            result.append(ch)
            result.append(raw[i + 1])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
        elif ch == '\n' and in_string:
            result.append('\\n')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


# ═══════════════════════════════════════════════════════════════
# 主逻辑
# ═══════════════════════════════════════════════════════════════

def de_ai_content_json(content: dict, style_id: str | None = None) -> dict:
    """对 content.json 进行去AI味改写。"""
    style_prompt = get_style_prompt(style_id)
    system_prompt = build_system_prompt(style_prompt)

    # 提取需要改写的字段
    fields_to_rewrite = {
        "post_title": content.get("post_title", ""),
        "post_body": content.get("post_body", ""),
        "cover_title": content.get("cover_title", ""),
    }

    user_prompt = f"""请改写以下小红书帖子的三个文本字段。只输出 JSON，包含改写后的 post_title、post_body、cover_title。

原始内容：
```json
{json.dumps(fields_to_rewrite, ensure_ascii=False, indent=2)}
```

要求：
1. post_title 改写后 ≤ 20字
2. post_body 改写后 600-950字
3. cover_title 保持 \\n 换行格式，每行 ≤ 12字
4. 只输出 JSON，不要其他文字"""

    raw = call_gemini(system_prompt, user_prompt)
    if not raw:
        print("❌ de-AI 改写失败", file=sys.stderr)
        return content

    json_str = _extract_json(raw)
    try:
        rewritten = json.loads(json_str)
    except json.JSONDecodeError:
        fixed = _fix_json_newlines(json_str)
        try:
            rewritten = json.loads(fixed)
        except json.JSONDecodeError as e:
            print(f"❌ de-AI JSON解析失败: {e}", file=sys.stderr)
            return content

    # 合并改写结果
    result = content.copy()
    if "post_title" in rewritten:
        new_title = rewritten["post_title"]
        if len(new_title) <= 20:
            result["post_title"] = new_title
        else:
            print(f"  ⚠️ de-AI标题过长({len(new_title)}字)，保留原标题", file=sys.stderr)

    if "post_body" in rewritten:
        new_body = rewritten["post_body"]
        if len(new_body) < 300:
            print(f"  ⚠️ de-AI正文过短({len(new_body)}字)，保留原正文", file=sys.stderr)
        else:
            # 超950字时截断到最后一个完整段落
            if len(new_body) > 950:
                cut = new_body[:950]
                last_nl = cut.rfind("\n")
                if last_nl > 600:
                    new_body = cut[:last_nl].rstrip()
                else:
                    new_body = cut.rstrip()
                print(f"  🔧 正文截断: {len(rewritten['post_body'])}→{len(new_body)}字", file=sys.stderr)
            result["post_body"] = new_body

    if "cover_title" in rewritten:
        result["cover_title"] = rewritten["cover_title"]

    return result


def de_ai_text(text: str, style_id: str | None = None) -> str:
    """对纯文本进行去AI味改写。"""
    style_prompt = get_style_prompt(style_id)
    system_prompt = build_system_prompt(style_prompt)

    user_prompt = f"""请改写以下小红书正文，去掉AI味，变得口语化接地气。只输出改写后的正文，不要其他文字。

原文：
{text}"""

    raw = call_gemini(system_prompt, user_prompt)
    return raw.strip() if raw else text


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="小红书文案去AI味模块")
    parser.add_argument("--input", "-i", help="content.json 路径")
    parser.add_argument("--output", "-o", help="输出路径（默认覆盖原文件）")
    parser.add_argument("--writing-style", "-s", help="写作风格ID或名称")
    parser.add_argument("--text-only", action="store_true", help="纯文本模式（从stdin读取）")
    parser.add_argument("--list-styles", action="store_true", help="列出可用写作风格")
    parser.add_argument("--dry-run", action="store_true", help="只输出不保存")

    args = parser.parse_args()

    if args.list_styles:
        lib = load_writing_styles()
        styles = lib.get("styles", [])
        if not styles:
            print("❌ 没有找到写作风格库，请先创建 writing-styles.json")
            return
        print(f"📝 可用写作风格 ({len(styles)} 个):\n")
        for s in styles:
            print(f"  {s['id']:20s}  {s.get('name', '')}  — {s.get('description', '')}")
        return

    if args.text_only:
        text = sys.stdin.read()
        result = de_ai_text(text, style_id=args.writing_style)
        print(result)
        return

    if not args.input:
        parser.print_help()
        sys.exit(1)

    # JSON 模式
    with open(args.input, "r", encoding="utf-8") as f:
        content = json.load(f)

    print(f"📝 原始标题: {content.get('post_title', '?')}", file=sys.stderr)
    print(f"📝 原始正文: {len(content.get('post_body', ''))}字", file=sys.stderr)
    print(f"🎨 写作风格: {args.writing_style or '默认'}", file=sys.stderr)

    result = de_ai_content_json(content, style_id=args.writing_style)

    new_title = result.get("post_title", "")
    new_body = result.get("post_body", "")
    print(f"\n✅ 改写标题: {new_title} ({len(new_title)}字)", file=sys.stderr)
    print(f"✅ 改写正文: {len(new_body)}字", file=sys.stderr)

    output_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.dry_run:
        print(output_json)
        return

    out_path = args.output or args.input
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output_json)
    print(f"💾 已保存: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
