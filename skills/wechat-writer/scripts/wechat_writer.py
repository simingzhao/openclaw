#!/usr/bin/env python3
"""
WeChat Writer - 高质量微信公众号文章写作pipeline

6阶段流程：TOPICS → PLAN → RESEARCH → WRITE → REVIEW → DE-AI
"""

import argparse
import json
import os
import sys
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Gemini SDK
try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Error: google-genai not installed. Run: pip install google-genai", file=sys.stderr)
    sys.exit(1)

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
PROMPTS_DIR = SCRIPT_DIR / "prompts"
PERSONAS_DIR = SCRIPT_DIR.parent / "personas"

# Model configuration
MODELS = {
    "topics": {"model": "gemini-3-flash-preview", "thinking": None},
    "plan": {"model": "gemini-3-pro-preview", "thinking": "high"},
    "research": {"model": "gemini-3-flash-preview", "thinking": None, "grounding": True},
    "write": {"model": "gemini-3-pro-preview", "thinking": None},
    "review": {"model": "gemini-3-pro-preview", "thinking": "high"},
    "deai": {"model": "gemini-3-pro-preview", "thinking": "high"},
}

# iCloud sync path
ICLOUD_ARTICLES_PATH = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/OpenClaw_Vault/Articles"

# ============================================================================
# Gemini Client
# ============================================================================

def get_client():
    """Get Gemini client."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    return genai.Client(api_key=api_key)


def call_gemini(
    prompt: str,
    stage: str,
    system_instruction: Optional[str] = None,
    max_retries: int = 3
) -> str:
    """Call Gemini API with stage-specific configuration."""
    client = get_client()
    config = MODELS[stage]
    model = config["model"]
    
    # Build generation config
    gen_config = {}
    if config.get("thinking"):
        gen_config["thinking_config"] = types.ThinkingConfig(
            thinkingBudget=10000 if config["thinking"] == "high" else 5000
        )
    
    # Build tools for grounding
    tools = None
    if config.get("grounding"):
        tools = [types.Tool(google_search=types.GoogleSearch())]
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=tools,
                    **gen_config
                )
            )
            
            # Extract text from response
            text_parts = []
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    text_parts.append(part.text)
            
            return "\n".join(text_parts)
            
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Retry {attempt + 1}/{max_retries}: {e}", file=sys.stderr)
                import time
                time.sleep(2 ** attempt)
            else:
                raise


def load_prompt(name: str) -> str:
    """Load prompt template."""
    prompt_file = PROMPTS_DIR / f"{name}.md"
    if prompt_file.exists():
        return prompt_file.read_text()
    return ""


def load_persona(name: str = "default") -> dict:
    """Load persona configuration."""
    persona_file = PERSONAS_DIR / f"{name}.yaml"
    if persona_file.exists():
        try:
            import yaml
            return yaml.safe_load(persona_file.read_text())
        except ImportError:
            # Fallback: return default persona without yaml
            return {
                "name": "思明的AI观察",
                "tone": "务实、有态度、偶尔调皮",
                "avoid": ["首先", "其次", "值得注意的是", "综上所述"],
                "prefer": ["直接给结论", "敢下判断", "适当吐槽"]
            }
    return {}


# ============================================================================
# Scout Scanner
# ============================================================================

def scan_scout_workspace(
    scout_workspace: Path,
    date_range_days: int = 3,
    topic_hint: Optional[str] = None
) -> dict:
    """Scan Scout workspace for relevant materials."""
    
    source_pack = {
        "scanned_at": datetime.now().isoformat(),
        "scout_workspace": str(scout_workspace),
        "date_range_days": date_range_days,
        "reports": [],
        "tweets": [],
        "videos": [],
        "articles": [],
        "notes": [],
    }
    
    cutoff_date = datetime.now() - timedelta(days=date_range_days)
    
    # Scan reports
    reports_dir = scout_workspace / "reports"
    if reports_dir.exists():
        for f in reports_dir.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime >= cutoff_date:
                    content = f.read_text()
                    source_pack["reports"].append({
                        "path": str(f.relative_to(scout_workspace)),
                        "filename": f.name,
                        "modified": mtime.isoformat(),
                        "content": content[:5000],  # Truncate for context
                    })
            except Exception as e:
                print(f"Warning: Could not read {f}: {e}", file=sys.stderr)
    
    # Scan X posts
    x_dir = scout_workspace / "raw" / "x-posts"
    if x_dir.exists():
        for f in x_dir.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime >= cutoff_date:
                    content = f.read_text()
                    source_pack["tweets"].append({
                        "path": str(f.relative_to(scout_workspace)),
                        "filename": f.name,
                        "modified": mtime.isoformat(),
                        "content": content[:8000],
                    })
            except Exception as e:
                print(f"Warning: Could not read {f}: {e}", file=sys.stderr)
    
    # Scan YouTube summaries
    yt_dir = scout_workspace / "raw" / "youtube"
    if yt_dir.exists():
        for f in yt_dir.rglob("*.md"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime >= cutoff_date:
                    content = f.read_text()
                    source_pack["videos"].append({
                        "path": str(f.relative_to(scout_workspace)),
                        "filename": f.name,
                        "modified": mtime.isoformat(),
                        "content": content[:5000],
                    })
            except Exception as e:
                print(f"Warning: Could not read {f}: {e}", file=sys.stderr)
    
    # Scan articles
    articles_dir = scout_workspace / "raw" / "articles"
    if articles_dir.exists():
        for f in articles_dir.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime >= cutoff_date:
                    content = f.read_text()
                    source_pack["articles"].append({
                        "path": str(f.relative_to(scout_workspace)),
                        "filename": f.name,
                        "modified": mtime.isoformat(),
                        "content": content[:5000],
                    })
            except Exception as e:
                print(f"Warning: Could not read {f}: {e}", file=sys.stderr)
    
    # Scan notes
    notes_dir = scout_workspace / "notes"
    if notes_dir.exists():
        for f in notes_dir.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime >= cutoff_date:
                    content = f.read_text()
                    source_pack["notes"].append({
                        "path": str(f.relative_to(scout_workspace)),
                        "filename": f.name,
                        "modified": mtime.isoformat(),
                        "content": content[:3000],
                    })
            except Exception as e:
                print(f"Warning: Could not read {f}: {e}", file=sys.stderr)
    
    return source_pack


# ============================================================================
# Pipeline Stages
# ============================================================================

def stage_topics(source_pack: dict, count: int = 5) -> dict:
    """Generate topic suggestions based on Scout materials."""
    
    # Always use inline template to avoid formatting issues
    prompt_template = None
    if not prompt_template:
        prompt_template = """基于以下Scout情报，生成{count}个微信公众号文章选题建议。

## Scout情报

### X/Twitter热点
{tweets}

### 视频摘要
{videos}

### 博客文章
{articles}

### 情报报告
{reports}

## 要求

1. 每个选题需要有足够的素材支撑
2. 选择有热度、有争议或有实用价值的话题
3. 给出独特的切入角度，不要泛泛而谈

## 输出格式（JSON）

输出一个JSON对象，包含topics数组，每个topic包含：id, title, angle, heat, scout_support, key_sources, why_good
"""
    
    # Format source materials
    tweets_text = "\n\n".join([
        f"### {t['filename']}\n{t['content'][:2000]}"
        for t in source_pack.get("tweets", [])[:5]
    ]) or "无"
    
    videos_text = "\n\n".join([
        f"### {v['filename']}\n{v['content'][:1500]}"
        for v in source_pack.get("videos", [])[:5]
    ]) or "无"
    
    articles_text = "\n\n".join([
        f"### {a['filename']}\n{a['content'][:1500]}"
        for a in source_pack.get("articles", [])[:5]
    ]) or "无"
    
    reports_text = "\n\n".join([
        f"### {r['filename']}\n{r['content'][:2000]}"
        for r in source_pack.get("reports", [])[:3]
    ]) or "无"
    
    prompt = prompt_template.format(
        count=count,
        tweets=tweets_text,
        videos=videos_text,
        articles=articles_text,
        reports=reports_text,
    )
    
    print("📋 Generating topic suggestions...", file=sys.stderr)
    response = call_gemini(prompt, "topics")
    
    # Extract JSON from response
    json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    
    # Try parsing the whole response as JSON
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"topics": [], "raw_response": response}


def stage_plan(workdir: Path, topic: str) -> dict:
    """Generate article plan/outline."""
    
    source_pack_file = workdir / "source_pack.json"
    if not source_pack_file.exists():
        print("Error: source_pack.json not found. Run 'init' first.", file=sys.stderr)
        sys.exit(1)
    
    source_pack = json.loads(source_pack_file.read_text())
    
    # Always use inline template
    prompt_template = None
    if not prompt_template:
        prompt_template = """你是一位资深的内容策划，为微信公众号策划文章框架。

## 文章主题
{topic}

## 可用素材（来自Scout情报）
{source_summary}

## 任务

为这篇文章制定详细的写作计划：
1. 确定文章的核心主旨和独特角度
2. 设计3-5个主要sections
3. 为每个section标注要使用的Scout素材
4. 列出需要额外调研的问题

## 输出格式

输出JSON对象，包含：title, subtitle, core_message, angle, target_length, sections数组（每个section有heading, purpose, key_points, research_needed）, research_questions数组
"""
    
    # Summarize sources
    source_summary = f"""
### X/Twitter ({len(source_pack.get('tweets', []))}条)
{chr(10).join([t['filename'] for t in source_pack.get('tweets', [])[:10]])}

### 视频摘要 ({len(source_pack.get('videos', []))}个)
{chr(10).join([v['filename'] for v in source_pack.get('videos', [])[:10]])}

### 博客文章 ({len(source_pack.get('articles', []))}篇)
{chr(10).join([a['filename'] for a in source_pack.get('articles', [])[:10]])}

### 情报报告 ({len(source_pack.get('reports', []))}份)
{chr(10).join([r['filename'] for r in source_pack.get('reports', [])[:5]])}
"""
    
    prompt = prompt_template.format(
        topic=topic,
        source_summary=source_summary,
    )
    
    print("📝 Planning article structure...", file=sys.stderr)
    response = call_gemini(prompt, "plan")
    
    # Extract JSON
    json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"raw_response": response}


def stage_research(workdir: Path) -> dict:
    """Conduct additional research based on plan."""
    
    plan_file = workdir / "plan.json"
    if not plan_file.exists():
        print("Error: plan.json not found. Run 'plan' first.", file=sys.stderr)
        sys.exit(1)
    
    plan = json.loads(plan_file.read_text())
    
    # Collect research questions
    questions = plan.get("research_questions", [])
    for section in plan.get("sections", []):
        questions.extend(section.get("research_needed", []))
    
    if not questions:
        print("✅ No additional research needed.", file=sys.stderr)
        return {"research_items": [], "note": "No research needed"}
    
    prompt = f"""你是一位专业的研究员。请针对以下问题进行调研，使用Google Search获取最新信息。

## 调研问题
{chr(10).join([f'{i+1}. {q}' for i, q in enumerate(questions)])}

## 要求
1. 搜索最新、可靠的信息来源
2. 提取关键数据和引用
3. 记录来源URL

## 输出格式（JSON）

```json
{{
  "research_items": [
    {{
      "question": "问题",
      "findings": "调研结果",
      "sources": [
        {{"title": "来源标题", "url": "URL"}}
      ],
      "key_quotes": ["可引用的原文"]
    }}
  ]
}}
```
"""
    
    print("🔍 Researching...", file=sys.stderr)
    response = call_gemini(prompt, "research")
    
    # Extract JSON
    json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"research_items": [], "raw_response": response}


def stage_write(workdir: Path) -> str:
    """Write the article draft."""
    
    # Load all materials
    source_pack = json.loads((workdir / "source_pack.json").read_text())
    plan = json.loads((workdir / "plan.json").read_text())
    
    research_file = workdir / "research.json"
    research = json.loads(research_file.read_text()) if research_file.exists() else {}
    
    prompt_template = load_prompt("write")
    if not prompt_template:
        prompt_template = """你是一位优秀的科技内容创作者，为微信公众号写文章。

## 文章计划
{plan}

## Scout素材（必须引用）
{sources}

## 补充调研
{research}

## 写作要求

1. **严格按照plan的sections结构写作**
2. **必须引用Scout素材中的内容**，格式如：「正如@xxx指出...」「根据xxx报道...」
3. 篇幅：{target_length}
4. 开头要吸引人，不要「随着AI的发展...」
5. 中间有料：数据、案例、对比
6. 结尾有观点，不是总结

## 输出

直接输出Markdown格式的文章，不要包含代码块标记。
"""
    
    # Format sources for the prompt
    sources_text = ""
    for tweet in source_pack.get("tweets", [])[:3]:
        sources_text += f"\n### {tweet['filename']}\n{tweet['content'][:2000]}\n"
    for video in source_pack.get("videos", [])[:2]:
        sources_text += f"\n### {video['filename']}\n{video['content'][:1500]}\n"
    for article in source_pack.get("articles", [])[:2]:
        sources_text += f"\n### {article['filename']}\n{article['content'][:1500]}\n"
    
    prompt = prompt_template.format(
        plan=json.dumps(plan, ensure_ascii=False, indent=2),
        sources=sources_text or "无Scout素材",
        research=json.dumps(research, ensure_ascii=False, indent=2),
        target_length=plan.get("target_length", "2000-3000字"),
    )
    
    print("✍️ Writing draft...", file=sys.stderr)
    response = call_gemini(prompt, "write")
    
    return response


def stage_review(workdir: Path) -> dict:
    """Review the draft for quality."""
    
    draft_file = workdir / "draft.md"
    if not draft_file.exists():
        print("Error: draft.md not found. Run 'write' first.", file=sys.stderr)
        sys.exit(1)
    
    draft = draft_file.read_text()
    plan = json.loads((workdir / "plan.json").read_text())
    
    prompt = f"""你是一位严格的内容审核编辑，请审核这篇文章。

## 文章计划
{json.dumps(plan, ensure_ascii=False, indent=2)}

## 文章草稿
{draft}

## 审核维度

1. **逻辑连贯性**：段落之间是否有逻辑断层？
2. **事实准确性**：有没有明显的事实错误或夸大？
3. **结构完整性**：是否覆盖了plan中的所有要点？
4. **观点鲜明度**：有没有明确的作者观点？
5. **素材引用**：是否有效利用了Scout素材？

## 输出格式（JSON）

```json
{{
  "overall_score": 8,
  "issues": [
    {{
      "severity": "high|medium|low",
      "location": "第几段/哪个section",
      "issue": "问题描述",
      "suggestion": "修改建议"
    }}
  ],
  "strengths": ["亮点1", "亮点2"],
  "recommendation": "通过/需要修改/重写"
}}
```
"""
    
    print("🔎 Reviewing draft...", file=sys.stderr)
    response = call_gemini(prompt, "review")
    
    # Extract JSON
    json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"raw_response": response}


def stage_deai(workdir: Path, persona_name: str = "default") -> str:
    """Remove AI-ish writing style, make it authentic."""
    
    draft_file = workdir / "draft.md"
    if not draft_file.exists():
        print("Error: draft.md not found.", file=sys.stderr)
        sys.exit(1)
    
    draft = draft_file.read_text()
    
    review_file = workdir / "review.json"
    review = json.loads(review_file.read_text()) if review_file.exists() else {}
    
    persona = load_persona(persona_name)
    
    prompt_template = load_prompt("deai")
    if not prompt_template:
        prompt_template = """你是一位资深的内容编辑，专门负责让AI写的文章变得更有人味。

## 原文
{draft}

## 审核反馈
{review}

## 公众号人设
{persona}

## 去AI化任务

AI文章的典型问题：
- "首先...其次...最后..." → 删除，自然过渡
- "值得注意的是" → 删除，或改成"有个坑"
- "综上所述" → 不需要，读者会自己总结
- "这是一个重要的里程碑" → "这事儿挺大的"
- 每段都太工整 → 有些段落可以很短，就一句话
- 没有个人观点 → 加入"我觉得..."、吐槽、态度

## 具体要求

1. 删除所有过渡词和套话
2. 加入作者的主观判断和吐槽
3. 用口语化表达替换书面语
4. 让开头更抓人
5. 结尾要有态度，不是总结
6. 保持核心内容不变，只改表达方式

## 输出

直接输出修改后的Markdown文章，不要包含代码块标记。
"""
    
    prompt = prompt_template.format(
        draft=draft,
        review=json.dumps(review, ensure_ascii=False, indent=2),
        persona=json.dumps(persona, ensure_ascii=False, indent=2) if persona else "务实、有态度、偶尔调皮",
    )
    
    print("🎨 De-AI processing...", file=sys.stderr)
    response = call_gemini(prompt, "deai")
    
    return response


# ============================================================================
# Sync to iCloud
# ============================================================================

def sync_to_icloud(workdir: Path):
    """Sync article workdir to iCloud Obsidian."""
    
    target_dir = ICLOUD_ARTICLES_PATH / workdir.name
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Sync files
    subprocess.run([
        "rsync", "-av", "--delete",
        f"{workdir}/",
        f"{target_dir}/"
    ], check=True)
    
    print(f"☁️ Synced to: {target_dir}", file=sys.stderr)
    return target_dir


# ============================================================================
# CLI Commands
# ============================================================================

def cmd_init(args):
    """Initialize article and generate topics."""
    
    scout_workspace = Path(args.scout_workspace).expanduser()
    output_dir = Path(args.output).expanduser()
    
    # Parse date range
    date_range_days = 3
    if args.date_range:
        if args.date_range.endswith('d'):
            date_range_days = int(args.date_range[:-1])
        else:
            date_range_days = int(args.date_range)
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Scan Scout workspace
    print(f"📡 Scanning Scout workspace: {scout_workspace}", file=sys.stderr)
    source_pack = scan_scout_workspace(scout_workspace, date_range_days)
    
    # Save source pack
    source_pack_file = output_dir / "source_pack.json"
    source_pack_file.write_text(json.dumps(source_pack, ensure_ascii=False, indent=2))
    print(f"✅ Saved: {source_pack_file}", file=sys.stderr)
    
    # Generate topics
    topics = stage_topics(source_pack, count=args.count or 5)
    
    # Save topics
    topics_file = output_dir / "topics.json"
    topics_file.write_text(json.dumps(topics, ensure_ascii=False, indent=2))
    print(f"✅ Saved: {topics_file}", file=sys.stderr)
    
    # Print topics
    print("\n" + "="*60)
    print("📋 选题建议")
    print("="*60)
    for topic in topics.get("topics", []):
        print(f"\n{topic.get('id', '?')}. {topic.get('title', 'Unknown')}")
        print(f"   角度: {topic.get('angle', 'N/A')}")
        print(f"   热度: {topic.get('heat', 'N/A')}")
        print(f"   素材: tweets={topic.get('scout_support', {}).get('tweets', 0)}, "
              f"videos={topic.get('scout_support', {}).get('videos', 0)}, "
              f"articles={topic.get('scout_support', {}).get('articles', 0)}")
        print(f"   理由: {topic.get('why_good', 'N/A')}")


def cmd_run(args):
    """Run full pipeline for selected topic."""
    
    workdir = Path(args.workdir).expanduser()
    topic = args.topic
    
    if not workdir.exists():
        print(f"Error: Workdir not found: {workdir}", file=sys.stderr)
        sys.exit(1)
    
    # PLAN
    print("\n" + "="*60)
    print("📝 Stage 1: PLAN")
    print("="*60)
    plan = stage_plan(workdir, topic)
    plan_file = workdir / "plan.json"
    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print(f"✅ Saved: {plan_file}")
    
    # RESEARCH
    print("\n" + "="*60)
    print("🔍 Stage 2: RESEARCH")
    print("="*60)
    research = stage_research(workdir)
    research_file = workdir / "research.json"
    research_file.write_text(json.dumps(research, ensure_ascii=False, indent=2))
    print(f"✅ Saved: {research_file}")
    
    # WRITE
    print("\n" + "="*60)
    print("✍️ Stage 3: WRITE")
    print("="*60)
    draft = stage_write(workdir)
    draft_file = workdir / "draft.md"
    draft_file.write_text(draft)
    print(f"✅ Saved: {draft_file}")
    
    # REVIEW
    print("\n" + "="*60)
    print("🔎 Stage 4: REVIEW")
    print("="*60)
    review = stage_review(workdir)
    review_file = workdir / "review.json"
    review_file.write_text(json.dumps(review, ensure_ascii=False, indent=2))
    print(f"✅ Saved: {review_file}")
    print(f"   Score: {review.get('overall_score', 'N/A')}/10")
    print(f"   Recommendation: {review.get('recommendation', 'N/A')}")
    
    # DE-AI
    print("\n" + "="*60)
    print("🎨 Stage 5: DE-AI")
    print("="*60)
    final = stage_deai(workdir, args.persona or "default")
    final_file = workdir / "final.md"
    final_file.write_text(final)
    print(f"✅ Saved: {final_file}")
    
    # Sync to iCloud
    print("\n" + "="*60)
    print("☁️ Syncing to iCloud Obsidian")
    print("="*60)
    icloud_path = sync_to_icloud(workdir)
    
    print("\n" + "="*60)
    print("🎉 DONE!")
    print("="*60)
    print(f"\n📁 Local: {workdir}")
    print(f"☁️ iCloud: {icloud_path}")
    print(f"\n👉 Review at: {icloud_path / 'final.md'}")


def cmd_single_stage(args, stage_name: str):
    """Run a single stage."""
    workdir = Path(args.workdir).expanduser()
    
    if stage_name == "plan":
        result = stage_plan(workdir, args.topic)
        (workdir / "plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    elif stage_name == "research":
        result = stage_research(workdir)
        (workdir / "research.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    elif stage_name == "write":
        result = stage_write(workdir)
        (workdir / "draft.md").write_text(result)
    elif stage_name == "review":
        result = stage_review(workdir)
        (workdir / "review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    elif stage_name == "deai":
        result = stage_deai(workdir, getattr(args, 'persona', 'default'))
        (workdir / "final.md").write_text(result)
    
    print(f"✅ {stage_name} completed")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="WeChat Writer - 高质量公众号文章写作pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # init command
    init_parser = subparsers.add_parser("init", help="初始化文章，扫描Scout生成选题")
    init_parser.add_argument("--scout-workspace", required=True, help="Scout workspace路径")
    init_parser.add_argument("--date-range", default="3d", help="扫描日期范围，如3d")
    init_parser.add_argument("--count", type=int, default=5, help="生成选题数量")
    init_parser.add_argument("--output", required=True, help="输出目录")
    
    # run command
    run_parser = subparsers.add_parser("run", help="执行完整写作pipeline")
    run_parser.add_argument("--workdir", required=True, help="文章工作目录")
    run_parser.add_argument("--topic", required=True, help="选定的文章主题")
    run_parser.add_argument("--persona", default="default", help="公众号人设配置")
    
    # Single stage commands
    for stage in ["plan", "research", "write", "review", "deai"]:
        stage_parser = subparsers.add_parser(stage, help=f"单独执行{stage}阶段")
        stage_parser.add_argument("--workdir", required=True, help="文章工作目录")
        if stage == "plan":
            stage_parser.add_argument("--topic", required=True, help="文章主题")
        if stage == "deai":
            stage_parser.add_argument("--persona", default="default", help="人设配置")
    
    args = parser.parse_args()
    
    if args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        cmd_single_stage(args, args.command)


if __name__ == "__main__":
    main()
