#!/usr/bin/env python3
"""
sense_scan.py — 探子的自动化Sense扫描器

独立脚本，不走Opus。直接调用：
  - 小红书搜索（rednote_ops MCP）
  - Exa Search API
  - Scout workspace digest（本地文件）

注意：X数据由小黑仔的x-ops独占采集，通过shared-knowledge共享，不在此处重复采集。

然后用 Gemini 做结构化分析，输出 JSON + Markdown 报告。

用法：
  $VENV sense_scan.py                          # 全量扫描
  $VENV sense_scan.py --sources rednote        # 只扫小红书
  $VENV sense_scan.py --sources rednote,exa    # 小红书+Exa
  $VENV sense_scan.py --keywords "AI赚钱,Vibe Coding"  # 自定义关键词
  $VENV sense_scan.py --skip-analysis          # 只拉数据，不调Gemini
  $VENV sense_scan.py --output /path/to/out    # 自定义输出目录
"""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# ── Gemini ──
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# ── Requests (for MCP + X API) ──
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── Shared Knowledge Hub ──
SHARED_KNOWLEDGE_DIR = Path(os.environ.get(
    "SHARED_KNOWLEDGE_DIR",
    os.path.expanduser("~/.openclaw/shared-knowledge"),
))
sys.path.insert(0, str(SHARED_KNOWLEDGE_DIR))
try:
    from lib.keywords import KeywordManager
    from lib.index import KnowledgeIndex
    from lib.topics import TopicTracker
    HAS_SHARED_KNOWLEDGE = True
except ImportError:
    HAS_SHARED_KNOWLEDGE = False


# ═══════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════

MODEL_PRIMARY = os.environ.get("SENSE_MODEL", "gemini-3.1-pro-preview")
MODEL_FALLBACK = "gemini-3-flash-preview"

MCP_URL = os.environ.get("REDNOTE_MCP_URL", "http://localhost:18060/mcp")

WORKSPACE = Path(os.environ.get(
    "REDNOTE_WORKSPACE",
    os.path.expanduser("~/.openclaw/workspace-rednote-ops"),
))

SCOUT_WORKSPACE = Path(os.environ.get(
    "SCOUT_WORKSPACE",
    os.path.expanduser("~/.openclaw/workspace"),
))

EXA_SCRIPT = Path(os.environ.get(
    "EXA_SCRIPT",
    os.path.expanduser("~/Desktop/openclaw/skills/exa-search/scripts/exa_search.py"),
))

# X scanning removed — now handled by x-ops skill via shared-knowledge

# 默认搜索关键词 — 按 strategy.json topics 对齐
DEFAULT_KEYWORDS_REDNOTE = [
    "AI副业", "AI赚钱", "AI一人公司", "超级个体",
    "Vibe Coding", "Vibe Marketing", "Claude赚钱",
    "AI跨境电商", "AI自动化", "Cursor教程",
]

DEFAULT_KEYWORDS_EXA = [
    "AI side hustle 2026",
    "vibe coding making money",
    "AI solopreneur",
    "Claude AI monetization",
    "AI one person company",
]

# DEFAULT_KEYWORDS_X removed — x-ops handles X keywords via shared-knowledge

TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_DISPLAY = datetime.now().strftime("%m.%d")


# ═══════════════════════════════════════════════════════════════
# MCP 小红书搜索
# ═══════════════════════════════════════════════════════════════

_mcp_session_id = None


def _mcp_init():
    global _mcp_session_id
    if _mcp_session_id is not None:
        return
    if not HAS_REQUESTS:
        print("⚠️ requests 未安装，跳过小红书搜索", file=sys.stderr)
        return
    payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "sense-scan", "version": "1.0.0"},
        },
        "id": "init-" + str(uuid.uuid4()),
    }
    try:
        resp = requests.post(MCP_URL, json=payload, timeout=15)
        resp.raise_for_status()
        _mcp_session_id = resp.headers.get("Mcp-Session-Id", "")
        headers = {"Content-Type": "application/json"}
        if _mcp_session_id:
            headers["Mcp-Session-Id"] = _mcp_session_id
        requests.post(MCP_URL, json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }, headers=headers, timeout=5)
        time.sleep(0.3)
    except requests.ConnectionError:
        print(f"⚠️ MCP 不可用 ({MCP_URL})，跳过小红书搜索", file=sys.stderr)
        _mcp_session_id = "__unavailable__"
    except Exception as e:
        print(f"⚠️ MCP 初始化失败: {e}，跳过小红书搜索", file=sys.stderr)
        _mcp_session_id = "__unavailable__"


def _mcp_call(method: str, params: dict | None = None, timeout: int = 60) -> dict | None:
    _mcp_init()
    if _mcp_session_id == "__unavailable__":
        return None
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": method, "arguments": params or {}},
        "id": str(uuid.uuid4()),
    }
    headers = {"Content-Type": "application/json"}
    if _mcp_session_id:
        headers["Mcp-Session-Id"] = _mcp_session_id
    try:
        resp = requests.post(MCP_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        # MCP返回204表示超时/无内容
        if resp.status_code == 204 or not resp.content:
            print(f"⚠️ MCP返回空 ({method}): status={resp.status_code}", file=sys.stderr)
            return None
        data = resp.json()
        if "error" in data:
            return None
        return data.get("result", data)
    except requests.Timeout:
        print(f"⚠️ MCP超时 ({method}): {timeout}s", file=sys.stderr)
        return None
    except Exception as e:
        print(f"⚠️ MCP调用失败 ({method}): {e}", file=sys.stderr)
        return None


def scan_rednote(keywords: list[str]) -> list[dict]:
    """搜索小红书，返回结构化结果列表。搜索失败时自动fallback到推荐流。"""
    print(f"\n🔴 小红书扫描 — {len(keywords)} 个关键词", file=sys.stderr)
    all_results = []
    search_ok = False

    for i, kw in enumerate(keywords):
        print(f"  🔍 搜索: {kw}", file=sys.stderr)
        # 搜索用15秒短超时，快速失败
        result = _mcp_call("search_feeds", {
            "keyword": kw,
            "filters": {"sort_by": "最多点赞", "note_type": "图文"},
        }, timeout=20)
        if result:
            items = _extract_mcp_items(result, kw)
            all_results.extend(items)
            print(f"    ✅ 找到 {len(items)} 条", file=sys.stderr)
            search_ok = True
        else:
            print(f"    ❌ 无结果（可能被反爬）", file=sys.stderr)
            # 第一个关键词就失败，说明搜索整体挂了，跳过后续关键词
            if i == 0 and not search_ok:
                print(f"  ⚠️ 搜索似乎不可用，跳过剩余关键词，尝试推荐流fallback", file=sys.stderr)
                break

        time.sleep(1)  # 避免MCP速率限制

    # 搜索全挂时，fallback到推荐流
    if not all_results:
        print(f"  🔄 搜索无结果，fallback到推荐流...", file=sys.stderr)
        feeds_result = _mcp_call("list_feeds", timeout=30)
        if feeds_result:
            items = _extract_mcp_items(feeds_result, "推荐流")
            all_results.extend(items)
            print(f"    ✅ 推荐流获取 {len(items)} 条", file=sys.stderr)
        else:
            print(f"    ❌ 推荐流也失败了", file=sys.stderr)

    return all_results


def _extract_mcp_items(result: dict, keyword: str) -> list[dict]:
    """从 MCP search_feeds 返回中提取结构化数据。
    
    MCP 返回 content[].text 是一个大 JSON 字符串（feeds 列表）。
    我们把它解析成精简结构，只保留 Gemini 需要的字段，大幅减少 token。
    """
    items = []
    content_list = result.get("content", [])
    for c in content_list:
        text = c.get("text", "")
        if not text:
            continue
        # 尝试解析为 JSON
        try:
            data = json.loads(text) if isinstance(text, str) else text
        except (json.JSONDecodeError, TypeError):
            # 不是JSON，直接存原文（截断）
            items.append({
                "source": "rednote",
                "keyword": keyword,
                "raw_text": text[:2000],
            })
            continue

        # 提取 feeds 列表
        feeds = data.get("feeds", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        parsed_feeds = []
        for feed in feeds:
            card = feed.get("noteCard", {})
            interact = card.get("interactInfo", {})
            user = card.get("user", {})
            parsed_feeds.append({
                "title": card.get("displayTitle", ""),
                "author": user.get("nickname", ""),
                "likes": interact.get("likedCount", "0"),
                "collects": interact.get("collectedCount", "0"),
                "comments": interact.get("commentCount", "0"),
                "shares": interact.get("sharedCount", "0"),
                "type": card.get("type", ""),
                "feed_id": feed.get("id", ""),
            })

        if parsed_feeds:
            items.append({
                "source": "rednote",
                "keyword": keyword,
                "feeds": parsed_feeds,
            })
        else:
            # fallback: 存原文截断
            items.append({
                "source": "rednote",
                "keyword": keyword,
                "raw_text": text[:2000],
            })

    return items


# ═══════════════════════════════════════════════════════════════
# Exa Search
# ═══════════════════════════════════════════════════════════════

def scan_exa(keywords: list[str]) -> list[dict]:
    """调用 Exa Search 脚本，返回精简结构化结果（节省Gemini token）。"""
    print(f"\n🟢 Exa Search — {len(keywords)} 个关键词", file=sys.stderr)
    all_results = []

    for kw in keywords:
        print(f"  🔍 搜索: {kw}", file=sys.stderr)
        try:
            proc = subprocess.run(
                ["python3", str(EXA_SCRIPT), kw, "--summary", kw, "--json", "-n", "5"],
                capture_output=True, text=True, timeout=45,
                env={**os.environ},
            )
            if proc.returncode == 0 and proc.stdout.strip():
                try:
                    raw = json.loads(proc.stdout)
                    # 提取精简格式：只要 title + url + 前600字的text + summary
                    results_raw = raw.get("results", raw) if isinstance(raw, dict) else raw
                    compact = []
                    for r in (results_raw if isinstance(results_raw, list) else []):
                        title = r.get("title", "")
                        url = r.get("url", "")
                        text = (r.get("text") or r.get("summary") or "")[:600]
                        published = r.get("publishedDate", "")[:10]
                        compact.append({
                            "title": title,
                            "url": url,
                            "date": published,
                            "snippet": text,
                        })
                    if compact:
                        all_results.append({
                            "source": "exa",
                            "keyword": kw,
                            "articles": compact,
                        })
                        print(f"    ✅ {len(compact)} 篇文章", file=sys.stderr)
                    else:
                        print(f"    ❌ 解析为空", file=sys.stderr)
                except json.JSONDecodeError:
                    # 非JSON → 存原始文本（exa --summary无--json时的纯文本输出）
                    text = proc.stdout.strip()[:4000]
                    all_results.append({"source": "exa", "keyword": kw, "raw_text": text})
                    print(f"    ✅ 纯文本输出", file=sys.stderr)
            else:
                err = (proc.stdout or proc.stderr).strip()
                if err:
                    print(f"    ❌ {err[:150]}", file=sys.stderr)
                else:
                    print(f"    ❌ 无输出", file=sys.stderr)
        except subprocess.TimeoutExpired:
            print(f"    ⏰ 超时 (45s)", file=sys.stderr)
        except Exception as e:
            print(f"    ❌ 错误: {e}", file=sys.stderr)

    return all_results


# X API scanning removed — now handled by x-ops skill
# X data available via shared-knowledge: index.search(query, channel="x")


# ═══════════════════════════════════════════════════════════════
# Scout Workspace（本地文件）
# ═══════════════════════════════════════════════════════════════

def scan_scout() -> list[dict]:
    """读取小黑仔的巡逻成果。"""
    print(f"\n🐾 Scout Workspace", file=sys.stderr)
    results = []

    # X data now via shared-knowledge (x-ops writes to vector index)
    # Read latest X intel from shared-knowledge if available
    if HAS_SHARED_KNOWLEDGE:
        try:
            _sk_data = SHARED_KNOWLEDGE_DIR / "data"
            _db_path = _sk_data / "vector-index" / "knowledge.db"
            if _db_path.exists():
                from lib.index import KnowledgeIndex
                _idx = KnowledgeIndex(str(_db_path))
                x_results = _idx.search("AI trends", channel="x", top_k=10, date_from=TODAY)
                _idx.close()
                if x_results:
                    x_text = "\n\n".join(
                        f"- @{r.get('metadata',{}).get('author_username','?')}: {r['text'][:300]}"
                        for r in x_results
                    )[:8000]
                    results.append({
                        "source": "scout-x",
                        "raw_text": x_text,
                    })
                    print(f"  ✅ X data from shared-knowledge: {len(x_results)} chunks", file=sys.stderr)
                else:
                    print(f"  ⚠️ shared-knowledge无今日X数据", file=sys.stderr)
        except Exception as e:
            print(f"  ⚠️ shared-knowledge X读取失败: {e}", file=sys.stderr)

    # YouTube summaries
    yt_dir = SCOUT_WORKSPACE / "raw" / "youtube"
    if yt_dir.is_dir():
        yt_texts = []
        for channel_dir in sorted(yt_dir.iterdir()):
            sum_dir = channel_dir / "summaries"
            if not sum_dir.is_dir():
                continue
            for f in sorted(sum_dir.iterdir()):
                if f.name.startswith(TODAY) and f.suffix == ".md":
                    yt_texts.append(f.read_text(encoding="utf-8")[:4000])
        if yt_texts:
            combined = "\n\n---\n\n".join(yt_texts)[:8000]
            results.append({
                "source": "scout-yt",
                "raw_text": combined,
            })
            print(f"  ✅ YouTube summaries: {len(yt_texts)} 篇", file=sys.stderr)
        else:
            print(f"  ⚠️ 今日无YouTube摘要", file=sys.stderr)
    else:
        print(f"  ⚠️ YouTube目录不存在", file=sys.stderr)

    return results


# ═══════════════════════════════════════════════════════════════
# Gemini 分析
# ═══════════════════════════════════════════════════════════════

ANALYSIS_SYSTEM_PROMPT = """你是「探子」—— 一个独立运营小红书AI内容账号的AI媒体人。

你的任务是分析多源信息扫描结果，产出一份**结构化Sense报告**，供后续内容决策使用。

## 你的账号定位
- 平台：小红书
- 领域：AI赚钱/超级个体 — 教普通人怎么通过AI搞钱
- 核心Topics：Claude变现、Vibe Coding变现、AI一人公司、Vibe Marketing、OpenClaw实战

## 分析要求

### 1. 趋势信号（trends）
从所有信源中提炼 5-10 个最强信号，每个信号需要：
- signal: 一句话描述（≤30字）
- strength: hot/warm/emerging
- sources: 在哪些信源出现过
- evidence: 具体数据证据（赞/藏/播放量等）
- china_feasible: 中国大陆是否可行（true/false/partial）
- topic_match: 匹配我们哪个 Topic（claude-monetization/vibe-coding/ai-one-person-company/vibe-marketing/openclaw-practical/new）

### 2. 高赞帖分析（top_posts）
从小红书搜索结果中挑出互动最高的 10 条帖子：
- title: 标题
- likes/collects/comments: 互动数据（尽量提取，没有写0）
- keyword: 搜索关键词
- content_type: tutorial/case_study/methodology/tool_resource/overview_opinion
- hook_analysis: 标题为什么吸引人（1句话）
- angle: 可借鉴的角度

### 3. 选题建议（topic_suggestions）
基于以上分析，推荐 5 个具体选题：
- title: 建议标题（≤20字，符合小红书风格）
- topic_id: 匹配的Topic
- content_type: tutorial/case_study/methodology/tool_resource/overview_opinion  
- reasoning: 为什么值得写（1-2句）
- priority: high/medium/low
- reference_material: 可参考的素材来源

### 4. 风格观察（style_observations）
如果在高赞帖中观察到视觉风格趋势：
- observation: 观察到什么
- implication: 对我们的启示

### 5. 关键词热度（keyword_heatmap）
每个搜索关键词的热度评估：
- keyword: 关键词
- heat: 🔥🔥🔥/🔥🔥/🔥/❄️
- trend: rising/stable/declining
- note: 备注

## 输出格式
严格输出 JSON，不要输出任何额外文本。结构：
{
  "scan_date": "YYYY-MM-DD",
  "scan_time": "HH:MM",
  "sources_scanned": ["rednote", "exa", ...],
  "trends": [...],
  "top_posts": [...],
  "topic_suggestions": [...],
  "style_observations": [...],
  "keyword_heatmap": [...],
  "executive_summary": "3-5句话总结今天的信号全景"
}

## 重要
- 数据要准确，不编造互动数字
- 中国大陆可行性筛选是硬标准 — 不可行的方向直接标注，不推荐为选题
- 选题标题必须符合小红书风格：具体数字+可操作+好奇心缺口
- 不涉及任何政治敏感话题"""


def analyze_with_gemini(raw_data: list[dict]) -> dict | None:
    """用 Gemini 分析原始扫描数据，返回结构化报告。"""
    if not HAS_GENAI:
        print("❌ google-genai 未安装，无法分析", file=sys.stderr)
        return None

    # 组装素材文本（精简格式，节省 Gemini token）
    material_parts = []
    for item in raw_data:
        source = item.get("source", "unknown")
        keyword = item.get("keyword", "")
        header = f"## [{source}]"
        if keyword:
            header += f" 关键词: {keyword}"

        if "feeds" in item:
            # 小红书结构化数据 — 紧凑列表格式
            lines = [header]
            for f in item["feeds"]:
                lines.append(
                    f"- 「{f['title']}」 @{f['author']} | "
                    f"赞{f['likes']} 藏{f['collects']} 评{f['comments']}"
                )
            material_parts.append("\n".join(lines))
        elif "articles" in item:
            # Exa精简文章格式
            lines = [header]
            for a in item["articles"]:
                snippet = a.get("snippet", "").replace("\n", " ")[:300]
                lines.append(f"- [{a.get('date','')}] {a.get('title','')}")
                if snippet:
                    lines.append(f"  > {snippet}")
            material_parts.append("\n".join(lines))
        elif "raw_text" in item:
            material_parts.append(f"{header}\n{item['raw_text'][:4000]}")

    combined_material = "\n\n---\n\n".join(material_parts)

    # 截断防止超长
    MAX_MATERIAL = 80000
    if len(combined_material) > MAX_MATERIAL:
        print(f"⚠️ 素材过长 ({len(combined_material)}字)，截断至 {MAX_MATERIAL}", file=sys.stderr)
        combined_material = combined_material[:MAX_MATERIAL]

    # 附加关键词提取指令
    kw_extraction_prompt = ""
    if HAS_SHARED_KNOWLEDGE:
        _kw_path = SHARED_KNOWLEDGE_DIR / "data" / "keywords.json"
        if _kw_path.exists():
            try:
                _km_for_prompt = KeywordManager(str(_kw_path))
                existing_rn = ", ".join(_km_for_prompt.get("rednote"))
                existing_exa = ", ".join(_km_for_prompt.get("exa"))
                kw_extraction_prompt = (
                    f"\n\n## 额外任务：提取新兴关键词\n"
                    f"当前小红书词库: {existing_rn}\n"
                    f"当前Exa词库: {existing_exa}\n\n"
                    f"请在JSON输出中额外添加一个 \"new_keywords\" 字段：\n"
                    f'{{"new_keywords": {{\n'
                    f'  "rednote": ["中文新词1", "中文新词2", ...],\n'
                    f'  "exa": ["english new term 1", "english new term 2", ...]\n'
                    f'}}}}\n'
                    f"要求：\n"
                    f"- 每个渠道3-5个新词\n"
                    f"- 必须是当前词库中**没有的**\n"
                    f"- 在扫描结果中出现频率高或增长趋势明显\n"
                    f"- 与赛道(跨境电商/Vibe Coding/外贸/猎头/AI赚钱)相关\n"
                    f"- 小红书给中文词，Exa给英文词"
                )
            except Exception:
                pass

    user_prompt = (
        f"今天日期：{TODAY}\n"
        f"扫描时间：{datetime.now().strftime('%H:%M')} PST\n\n"
        f"以下是多源扫描的原始数据，请分析并产出结构化Sense报告：\n\n"
        f"{combined_material}\n\n"
        f"{kw_extraction_prompt}\n\n"
        f"严格按系统提示的JSON格式输出。确保JSON完整可解析。"
    )

    print(f"\n🧠 Gemini 分析中... (素材 {len(combined_material)} 字)", file=sys.stderr)

    client = genai.Client()

    for model in [MODEL_PRIMARY, MODEL_FALLBACK]:
        try:
            print(f"  🤖 尝试: {model}", file=sys.stderr)
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=ANALYSIS_SYSTEM_PROMPT,
                    temperature=0.4,  # 分析任务用低温度
                    max_output_tokens=16384,
                ),
            )
            if response and response.text:
                print(f"  ✅ 分析完成 ({model})", file=sys.stderr)
                return _parse_analysis(response.text, model)
        except Exception as e:
            if "503" in str(e) or "UNAVAILABLE" in str(e) or "429" in str(e):
                print(f"  ⚠️ {model} 不可用: {e}", file=sys.stderr)
                continue
            print(f"  ❌ {model} 错误: {e}", file=sys.stderr)
            continue

    print("❌ 所有模型都不可用", file=sys.stderr)
    return None


def _parse_analysis(text: str, model: str) -> dict | None:
    """从 Gemini 响应中解析 JSON。"""
    raw = text.strip()
    if "```json" in raw:
        raw = raw.split("```json", 1)[1]
        raw = raw.split("```", 1)[0]
    elif "```" in raw:
        raw = raw.split("```", 1)[1]
        raw = raw.split("```", 1)[0]
    raw = raw.strip()

    try:
        data = json.loads(raw)
        data["_model_used"] = model
        return data
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析失败: {e}", file=sys.stderr)
        print(f"  原始片段: {text[:500]}", file=sys.stderr)
        return None


# ═══════════════════════════════════════════════════════════════
# 输出
# ═══════════════════════════════════════════════════════════════

def save_outputs(raw_data: list[dict], analysis: dict | None, output_dir: Path):
    """保存扫描结果：raw JSON + 分析 JSON + Markdown 报告。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M")

    # 1. 原始数据
    raw_path = output_dir / f"{TODAY}_{timestamp}_raw.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    print(f"\n📁 原始数据: {raw_path}", file=sys.stderr)

    # 2. 分析结果 JSON
    if analysis:
        analysis_path = output_dir / f"{TODAY}_{timestamp}_analysis.json"
        with open(analysis_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        print(f"📁 分析结果: {analysis_path}", file=sys.stderr)

        # 3. Markdown 报告（供人阅读 + 写入 trends）
        md_path = output_dir / f"{TODAY}_{timestamp}_report.md"
        md_content = _render_markdown(analysis)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"📁 Markdown: {md_path}", file=sys.stderr)

        # 4. 同步到 knowledge/trends/
        trends_dir = WORKSPACE / "knowledge" / "trends"
        trends_dir.mkdir(parents=True, exist_ok=True)
        trends_path = trends_dir / f"{TODAY}.md"
        # 如果已存在，追加；否则新建
        mode = "a" if trends_path.exists() else "w"
        with open(trends_path, mode, encoding="utf-8") as f:
            if mode == "a":
                f.write(f"\n\n---\n\n# 补充扫描 ({timestamp})\n\n")
            f.write(md_content)
        print(f"📁 趋势记录: {trends_path}", file=sys.stderr)

    # 5. 最新分析的快捷引用（latest.json）
    if analysis:
        latest_path = output_dir / "latest.json"
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        print(f"📁 Latest: {latest_path}", file=sys.stderr)

    # 6. 同步到 shared-knowledge/data/raw/ (按channel分目录)
    _sync_raw_to_shared_knowledge(raw_data, analysis, timestamp)


def _sync_raw_to_shared_knowledge(raw_data: list[dict], analysis: dict | None, timestamp: str):
    """将raw数据按channel拆分写入 shared-knowledge/data/raw/"""
    sk_raw = Path(os.path.expanduser("~/.openclaw/shared-knowledge/data/raw"))
    sk_digest = Path(os.path.expanduser("~/.openclaw/shared-knowledge/data/digest"))

    for item in raw_data:
        src = item.get("source", "")
        if src == "rednote":
            keyword = item.get("keyword", "unknown")
            feeds = item.get("feeds", [])
            if not feeds:
                continue
            out_items = []
            for feed in feeds:
                out_items.append({
                    "keyword": keyword,
                    "title": feed.get("title") or feed.get("display_title", ""),
                    "author": feed.get("author", ""),
                    "likes": feed.get("likes", 0),
                    "collects": feed.get("collects", 0),
                    "comments": feed.get("comments", 0),
                    "shares": feed.get("shares", 0),
                    "type": feed.get("type", ""),
                    "feed_id": feed.get("feed_id", ""),
                    "xsec_token": feed.get("xsec_token", ""),
                    "scan_date": TODAY,
                    "scan_time": timestamp,
                })
            out_dir = sk_raw / "rednote" / TODAY
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"{TODAY}_{timestamp}_raw.json"
            # 追加模式：如果文件已存在，合并
            existing = []
            if out_file.exists():
                try:
                    existing = json.loads(out_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            existing.extend(out_items)
            out_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

        elif src == "exa":
            keyword = item.get("keyword", "unknown")
            articles = item.get("articles", [])
            if not articles:
                continue
            out_items = []
            for article in articles:
                out_items.append({
                    "keyword": keyword,
                    "title": article.get("title", ""),
                    "url": article.get("url", ""),
                    "date": article.get("date", ""),
                    "snippet": article.get("snippet", ""),
                    "scan_date": TODAY,
                    "scan_time": timestamp,
                })
            out_dir = sk_raw / "exa" / TODAY
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"{TODAY}_{timestamp}_raw.json"
            existing = []
            if out_file.exists():
                try:
                    existing = json.loads(out_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            existing.extend(out_items)
            out_file.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")

    # 分析报告写入digest/scans/
    if analysis:
        scans_dir = sk_digest / "scans"
        scans_dir.mkdir(parents=True, exist_ok=True)
        report_path = scans_dir / f"{TODAY}_{timestamp}_report.md"
        if not report_path.exists():
            report_path.write_text(_render_markdown(analysis), encoding="utf-8")

        # 趋势日志写入digest/daily/
        daily_dir = sk_digest / "daily"
        daily_dir.mkdir(parents=True, exist_ok=True)
        daily_path = daily_dir / f"{TODAY}.md"
        md_content = _render_markdown(analysis)
        mode = "a" if daily_path.exists() else "w"
        with open(daily_path, mode, encoding="utf-8") as f:
            if mode == "a":
                f.write(f"\n\n---\n\n# 补充扫描 ({timestamp})\n\n")
            f.write(md_content)


def _render_markdown(analysis: dict) -> str:
    """将分析 JSON 渲染为可读 Markdown。"""
    lines = []
    lines.append(f"# Sense 扫描报告 — {analysis.get('scan_date', TODAY)}")
    lines.append(f"\n扫描时间：{analysis.get('scan_time', '??:??')} PST")
    lines.append(f"信源：{', '.join(analysis.get('sources_scanned', []))}")
    model = analysis.get('_model_used', 'unknown')
    lines.append(f"分析模型：{model}")

    # Executive Summary
    summary = analysis.get("executive_summary", "")
    if summary:
        lines.append(f"\n## 📋 总结\n\n{summary}")

    # Trends
    trends = analysis.get("trends", [])
    if trends:
        lines.append("\n## 🔥 趋势信号\n")
        lines.append("| # | 信号 | 强度 | 来源 | 中国可行 | Topic |")
        lines.append("|---|------|------|------|----------|-------|")
        for i, t in enumerate(trends, 1):
            signal = t.get("signal", "?")
            strength = t.get("strength", "?")
            sources = ", ".join(t.get("sources", []))
            cf = t.get("china_feasible")
            feasible = "✅" if cf is True or cf == "true" or cf == True else ("⚠️" if cf == "partial" or cf == "partly" else "❌")
            topic = t.get("topic_match", "?")
            lines.append(f"| {i} | {signal} | {strength} | {sources} | {feasible} | {topic} |")
        lines.append("")
        for t in trends:
            evidence = t.get("evidence", "")
            if evidence:
                lines.append(f"- **{t.get('signal', '?')}**: {evidence}")

    # Top Posts
    top_posts = analysis.get("top_posts", [])
    if top_posts:
        lines.append("\n## 📊 高赞帖分析\n")
        lines.append("| # | 标题 | 赞/藏/评 | 类型 | 钩子分析 |")
        lines.append("|---|------|----------|------|----------|")
        for i, p in enumerate(top_posts, 1):
            title = p.get("title", "?")[:25]
            likes = p.get("likes", 0)
            collects = p.get("collects", 0)
            comments = p.get("comments", 0)
            ct = p.get("content_type", "?")
            hook = p.get("hook_analysis", "")[:30]
            lines.append(f"| {i} | {title} | {likes}/{collects}/{comments} | {ct} | {hook} |")

    # Topic Suggestions
    suggestions = analysis.get("topic_suggestions", [])
    if suggestions:
        lines.append("\n## 💡 选题建议\n")
        for i, s in enumerate(suggestions, 1):
            title = s.get("title", "?")
            topic = s.get("topic_id", "?")
            priority = s.get("priority", "?")
            reasoning = s.get("reasoning", "")
            ct = s.get("content_type", "?")
            lines.append(f"### {i}. 「{title}」")
            lines.append(f"- Topic: {topic} | 类型: {ct} | 优先级: {priority}")
            lines.append(f"- 理由: {reasoning}")
            ref = s.get("reference_material", "")
            if ref:
                lines.append(f"- 参考: {ref}")
            lines.append("")

    # Style Observations
    style_obs = analysis.get("style_observations", [])
    if style_obs:
        lines.append("\n## 🎨 风格观察\n")
        for obs in style_obs:
            lines.append(f"- **{obs.get('observation', '?')}** → {obs.get('implication', '')}")

    # Keyword Heatmap
    heatmap = analysis.get("keyword_heatmap", [])
    if heatmap:
        lines.append("\n## 🌡️ 关键词热度\n")
        lines.append("| 关键词 | 热度 | 趋势 | 备注 |")
        lines.append("|--------|------|------|------|")
        for kw in heatmap:
            lines.append(f"| {kw.get('keyword', '?')} | {kw.get('heat', '?')} | {kw.get('trend', '?')} | {kw.get('note', '')} |")

    lines.append(f"\n---\n*自动生成 — sense_scan.py | {model}*")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# Shared Knowledge 回写
# ═══════════════════════════════════════════════════════════════

def _sync_shared_knowledge(raw_data: list[dict], analysis: dict, km: "KeywordManager | None", sources: set[str]):
    """分析完成后，回写到共享知识库：关键词进化 + 向量入库 + 话题更新。"""
    print(f"\n📚 回写 Shared Knowledge...", file=sys.stderr)
    sk_data = SHARED_KNOWLEDGE_DIR / "data"

    # ── 1. 关键词进化 ──
    new_keywords = analysis.get("new_keywords", {})
    if km and new_keywords:
        for channel_key, words in new_keywords.items():
            if isinstance(words, list) and words:
                word_dicts = [{"keyword": w, "source": f"sense:{TODAY}"} for w in words if isinstance(w, str) and w.strip()]
                if word_dicts:
                    km.evolve(channel_key, word_dicts)
                    print(f"  🔑 {channel_key} +{len(word_dicts)} 新词: {', '.join(w['keyword'] for w in word_dicts[:5])}", file=sys.stderr)

        # 记录命中/未命中
        for item in raw_data:
            keyword = item.get("keyword", "")
            if not keyword:
                continue
            source = item.get("source", "")
            channel = "rednote" if source == "rednote" else ("exa" if source == "exa" else "")
            if not channel:
                continue
            has_content = bool(item.get("feeds") or item.get("articles") or item.get("raw_text"))
            if has_content:
                km.record_hit(channel, keyword)
            else:
                km.record_miss(channel, keyword)

        km.gc()
        km.save()
        print(f"  ✅ 关键词词库已更新", file=sys.stderr)
    elif not new_keywords:
        print(f"  ⚠️ Gemini未返回new_keywords，跳过关键词进化", file=sys.stderr)

    # ── 2. 向量入库 ──
    try:
        db_path = sk_data / "vector-index" / "knowledge.db"
        index = KnowledgeIndex(str(db_path))
        chunks_added = 0

        # 小红书帖子
        for item in raw_data:
            if item.get("source") != "rednote":
                continue
            keyword = item.get("keyword", "")
            for feed in item.get("feeds", []):
                title = feed.get("title", "")
                if not title:
                    continue
                text = f"{title} | 作者:{feed.get('author','')} | 赞:{feed.get('likes',0)} 藏:{feed.get('collects',0)}"
                try:
                    index.add(
                        source="sense_scan",
                        channel="rednote",
                        date=TODAY,
                        title=title,
                        text=text,
                        metadata={
                            "keyword": keyword,
                            "likes": feed.get("likes", "0"),
                            "collects": feed.get("collects", "0"),
                            "feed_id": feed.get("feed_id", ""),
                        },
                        tags=["rednote-search"],
                    )
                    chunks_added += 1
                except Exception as e:
                    print(f"  ⚠️ 入库失败: {e}", file=sys.stderr)

        # Exa文章
        for item in raw_data:
            if item.get("source") != "exa":
                continue
            keyword = item.get("keyword", "")
            for article in item.get("articles", []):
                title = article.get("title", "")
                snippet = article.get("snippet", "")
                if not (title or snippet):
                    continue
                text = f"{title}\n{snippet}" if snippet else title
                try:
                    index.add(
                        source="sense_scan",
                        channel="exa",
                        date=article.get("date", TODAY) or TODAY,
                        title=title,
                        text=text,
                        metadata={
                            "keyword": keyword,
                            "url": article.get("url", ""),
                        },
                        tags=["exa-search"],
                    )
                    chunks_added += 1
                except Exception as e:
                    print(f"  ⚠️ 入库失败: {e}", file=sys.stderr)

        index.close()
        print(f"  📦 向量库 +{chunks_added} chunks", file=sys.stderr)
    except Exception as e:
        print(f"  ❌ 向量入库失败: {e}", file=sys.stderr)

    # ── 3. 话题追踪 ──
    try:
        topics_path = sk_data / "topics.json"
        tracker = TopicTracker(str(topics_path))

        # 从分析结果的trends提取话题
        for trend in analysis.get("trends", []):
            signal = trend.get("signal", "")
            if not signal:
                continue
            # 生成topic_key
            topic_key = signal.lower().replace(" ", "-").replace("，", "-").replace("：", "-")[:40]
            topic_key = "".join(c for c in topic_key if c.isalnum() or c == "-")

            # 判断渠道
            trend_sources = trend.get("sources", [])
            for src in trend_sources:
                channel = ""
                if "rednote" in src.lower() or "小红书" in src.lower():
                    channel = "rednote"
                elif "exa" in src.lower():
                    channel = "exa"
                elif "scout" in src.lower() or "x" in src.lower() or "twitter" in src.lower():
                    channel = "x"
                elif "youtube" in src.lower() or "yt" in src.lower():
                    channel = "youtube"
                if channel:
                    tracker.upsert(topic_key, channel, {
                        "display_name": signal,
                        "mentions": 1,
                        "last_seen": TODAY,
                        "related_track": trend.get("topic_match", ""),
                    })

        tracker.save()
        all_topics = tracker.data.get("topics", {})
        active_count = sum(1 for t in all_topics.values() if t.get("status") == "active")
        print(f"  📋 话题追踪: {len(all_topics)} 总计, {active_count} active", file=sys.stderr)
    except Exception as e:
        print(f"  ❌ 话题追踪失败: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="探子 Sense 扫描器 — 多源信息采集 + Gemini分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sources", default="all",
        help="数据源（逗号分隔）：rednote,exa,scout,all（默认all）。X已移至x-ops。",
    )
    parser.add_argument(
        "--keywords", default="",
        help="自定义小红书关键词（逗号分隔，覆盖默认）",
    )
    parser.add_argument(
        "--keywords-exa", default="",
        help="自定义Exa关键词（逗号分隔）",
    )
    # --keywords-x removed: X scanning now handled by x-ops skill
    parser.add_argument(
        "--skip-analysis", action="store_true",
        help="只拉数据，不调Gemini分析",
    )
    parser.add_argument(
        "--output", "-o", default="",
        help="输出目录（默认 workspace/sense/）",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="最后输出分析JSON到stdout",
    )

    args = parser.parse_args()

    # 解析 sources
    sources = set()
    if args.sources == "all":
        sources = {"rednote", "exa", "scout"}
    else:
        sources = {s.strip() for s in args.sources.split(",")}

    # 解析关键词 — 优先从 shared-knowledge 动态词库读取
    _km = None
    if HAS_SHARED_KNOWLEDGE and not args.keywords and not args.keywords_exa:
        _kw_path = SHARED_KNOWLEDGE_DIR / "data" / "keywords.json"
        if _kw_path.exists():
            try:
                _km = KeywordManager(str(_kw_path))
                print(f"📚 使用 shared-knowledge 动态词库: {_kw_path}", file=sys.stderr)
            except Exception as e:
                print(f"⚠️ 读取动态词库失败: {e}，使用默认关键词", file=sys.stderr)

    if args.keywords:
        kw_rednote = [k.strip() for k in args.keywords.split(",") if k.strip()]
    elif _km:
        kw_rednote = _km.get("rednote")
        print(f"  🔴 rednote 关键词 ({len(kw_rednote)}): {', '.join(kw_rednote[:8])}{'...' if len(kw_rednote) > 8 else ''}", file=sys.stderr)
    else:
        kw_rednote = DEFAULT_KEYWORDS_REDNOTE

    if args.keywords_exa:
        kw_exa = [k.strip() for k in args.keywords_exa.split(",") if k.strip()]
    elif _km:
        kw_exa = _km.get("exa")
        print(f"  🟢 exa 关键词 ({len(kw_exa)}): {', '.join(kw_exa[:5])}{'...' if len(kw_exa) > 5 else ''}", file=sys.stderr)
    else:
        kw_exa = DEFAULT_KEYWORDS_EXA

    output_dir = Path(args.output) if args.output else WORKSPACE / "sense"

    print(f"═══ 探子 Sense 扫描 ═══", file=sys.stderr)
    print(f"日期: {TODAY}", file=sys.stderr)
    print(f"信源: {', '.join(sorted(sources))}", file=sys.stderr)
    print(f"输出: {output_dir}", file=sys.stderr)

    # ── 数据采集 ──
    all_raw = []

    if "scout" in sources:
        all_raw.extend(scan_scout())

    if "rednote" in sources:
        all_raw.extend(scan_rednote(kw_rednote))

    if "exa" in sources:
        all_raw.extend(scan_exa(kw_exa))

    if not all_raw:
        print("\n❌ 所有信源均无数据", file=sys.stderr)
        sys.exit(1)

    print(f"\n📊 总计采集 {len(all_raw)} 条数据", file=sys.stderr)

    # ── Gemini 分析 ──
    analysis = None
    if not args.skip_analysis:
        analysis = analyze_with_gemini(all_raw)
        if analysis:
            print(f"\n✅ 分析完成", file=sys.stderr)
            # stdout JSON 输出
            if args.json:
                print(json.dumps(analysis, ensure_ascii=False, indent=2))
        else:
            print(f"\n⚠️ 分析失败，仅保存原始数据", file=sys.stderr)

    # ── Shared Knowledge 回写 ──
    if HAS_SHARED_KNOWLEDGE and analysis:
        _sync_shared_knowledge(all_raw, analysis, _km, sources)

    # ── 保存 ──
    save_outputs(all_raw, analysis, output_dir)

    print(f"\n═══ 扫描完成 ═══", file=sys.stderr)


if __name__ == "__main__":
    main()
