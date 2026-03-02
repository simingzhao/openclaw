#!/usr/bin/env python3
"""X sense scanner: search + Gemini analysis + shared-knowledge sync."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# -- Gemini --
try:
    from google import genai
    from google.genai import types

    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# -- Shared Knowledge Hub --
SHARED_KNOWLEDGE_DIR = Path(
    os.environ.get(
        "SHARED_KNOWLEDGE_DIR",
        os.path.expanduser("~/.openclaw/shared-knowledge"),
    )
)
sys.path.insert(0, str(SHARED_KNOWLEDGE_DIR))
try:
    from lib.keywords import KeywordManager
    from lib.index import KnowledgeIndex
    from lib.topics import TopicTracker

    HAS_SHARED_KNOWLEDGE = True
except ImportError:
    HAS_SHARED_KNOWLEDGE = False

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from x_api import XClient

MODEL_PRIMARY = os.environ.get("SENSE_MODEL", "gemini-3.1-pro-preview")
MODEL_FALLBACK = "gemini-3-flash-preview"

WORKSPACE = Path(
    os.environ.get(
        "X_OPS_WORKSPACE",
        os.path.expanduser("~/.openclaw/workspace"),
    )
)
SHARED_KNOWLEDGE_DATA = Path(
    os.environ.get(
        "SHARED_KNOWLEDGE_DATA_DIR",
        os.path.expanduser("~/.openclaw/shared-knowledge/data"),
    )
)
OUTPUT_DIR = SHARED_KNOWLEDGE_DATA / "raw" / "x"

DEFAULT_KEYWORDS_X = [
    "AI agents",
    "Claude Code",
    "vibe coding",
    "AI product",
]

EXCLUDE_KEYWORDS = [
    "crypto",
    "bitcoin",
    "ethereum",
    "NFT",
    "web3",
    "defi",
    "token",
    "airdrop",
    "memecoin",
    "$BTC",
    "$ETH",
    "$SOL",
    "$CLD",
    "$LAM",
    "$GSD",
    "giveaway",
    "follow and rt",
    "dm me",
    "on-chain",
    "onchain",
    "blockchain",
    "DAO",
    "solana",
    "algorand",
    "x402",
    "micropayment",
    "DeFi",
    "staking",
    "validator",
    "swarmocracy",
    "tokenomics",
    "mint",
    "whitelist",
    "presale",
    "farming",
    "yield",
]

STATE_FILE = "state.json"

ANALYSIS_SYSTEM_PROMPT = """你是 AI 情报分析师，负责从 X/Twitter 数据中提取 AI 行业动态。

## 绝对排除（红线）
以下内容必须完全忽略，不得出现在任何输出字段中（trends/top_tweets/topic_clusters/new_keywords/executive_summary）：
- 所有 crypto/区块链/Web3/DeFi/NFT 相关内容
- 代币（$XXX）、链上治理（DAO/swarmocracy）、去中心化计算/存储（除非纯AI推理场景）
- x402协议、机器间支付/微支付、agent钱包、链上结算
- 具体项目：DataHaven、PhalaNetwork、Aethir、ActionModelAI、ClawDAO 等 crypto 项目
如果某条推文的核心叙事是 crypto/Web3，即使提到了 AI，也必须跳过。

## 分析要求

### 1. 趋势信号（trends）
提炼 5-10 个最强信号：
- signal: 一句话描述（≤40字）
- strength: hot/warm/emerging
- evidence: 具体数据（互动量、多人提到等）
- category: model_release/product_launch/technique/industry/funding/opinion/open_source

### 2. 关键推文（top_tweets）
挑出互动最高的 10 条：
- text: 推文内容（前200字）
- author: @username
- likes/retweets/replies: 互动数据
- category: 同上
- insight: 为什么这条值得关注（1句话）

### 3. 主题聚类（topic_clusters）
把推文按主题聚类，每个cluster：
- topic: 主题名
- tweet_count: 相关推文数
- key_points: 3-5个要点
- sentiment: positive/negative/mixed/neutral

### 4. 关键词建议
在JSON中添加 "new_keywords" 字段：
{"new_keywords": {"x": ["english term 1", "english term 2", ...]}}
要求：
- 3-5个新英文关键词/短语
- 当前词库中没有的
- 在本次扫描中频繁出现或明显趋势上升
- 与AI/tech行业相关
- 适合作为X搜索query

### 输出格式
严格JSON，结构：
{
  "scan_date": "YYYY-MM-DD",
  "scan_time": "HH:MM",
  "total_tweets_analyzed": N,
  "trends": [...],
  "top_tweets": [...],
  "topic_clusters": [...],
  "new_keywords": {"x": [...]},
  "executive_summary": "3-5句话总结"
}
"""


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_state(output_dir: Path) -> dict[str, Any]:
    state_path = output_dir / STATE_FILE
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"seen_posts": []}
    return {"seen_posts": []}


def save_state(output_dir: Path, seen_posts: set[str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / STATE_FILE
    state = {"seen_posts": list(seen_posts)[-500:]}
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def matches_exclude(text: str, exclude_keywords: list[str] | None = None) -> bool:
    keywords = exclude_keywords or EXCLUDE_KEYWORDS
    text_lower = (text or "").lower()
    return any(keyword.lower() in text_lower for keyword in keywords)


def filter_excluded_tweets(tweets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    excluded = 0
    for tweet in tweets:
        if matches_exclude(str(tweet.get("text", ""))):
            excluded += 1
            continue
        kept.append(tweet)
    return kept, excluded


def dedup_tweets(tweets: list[dict[str, Any]], seen_posts: set[str]) -> tuple[list[dict[str, Any]], set[str], int]:
    kept: list[dict[str, Any]] = []
    next_seen = set(seen_posts)
    dropped = 0
    for tweet in tweets:
        tweet_id = str(tweet.get("id", "")).strip()
        if not tweet_id:
            dropped += 1
            continue
        if tweet_id in next_seen:
            dropped += 1
            continue
        kept.append(tweet)
        next_seen.add(tweet_id)
    return kept, next_seen, dropped


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", value).strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    return slug[:64] or "x-topic"


def _parse_keywords_arg(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _compact_tweets_for_prompt(tweets: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for tweet in tweets:
        metrics = tweet.get("metrics", {})
        likes = _to_int(metrics.get("like_count"), 0)
        retweets = _to_int(metrics.get("retweet_count"), 0)
        replies = _to_int(metrics.get("reply_count"), 0)
        author = tweet.get("author_username", "unknown")
        created = str(tweet.get("created_at", ""))[:19]
        keyword = tweet.get("keyword", "")
        text = str(tweet.get("text", "")).replace("\n", " ").strip()
        text = text[:280]

        lines.append(
            f"- [{keyword}] @{author} {created} | ❤ {likes} 🔁 {retweets} 💬 {replies}"
        )
        lines.append(f"  {text}")

    combined = "\n".join(lines)
    max_len = 90000
    if len(combined) > max_len:
        combined = combined[:max_len]
    return combined


def _parse_analysis(text: str, model: str) -> dict[str, Any] | None:
    raw = text.strip()
    if "```json" in raw:
        raw = raw.split("```json", 1)[1]
        raw = raw.split("```", 1)[0]
    elif "```" in raw:
        raw = raw.split("```", 1)[1]
        raw = raw.split("```", 1)[0]
    raw = raw.strip()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"warning: failed to parse Gemini JSON: {exc}", file=sys.stderr)
        print(f"warning: response snippet: {text[:500]}", file=sys.stderr)
        return None

    payload["_model_used"] = model
    return payload


def analyze_with_gemini(tweets: list[dict[str, Any]], current_keywords: list[str]) -> dict[str, Any] | None:
    if not HAS_GENAI:
        print("warning: google-genai is not installed, skip analysis", file=sys.stderr)
        return None

    if not tweets:
        print("warning: no tweets available for analysis", file=sys.stderr)
        return None

    prompt_material = _compact_tweets_for_prompt(tweets)
    existing_keywords = ", ".join(current_keywords)

    user_prompt = (
        f"今天日期：{datetime.now().strftime('%Y-%m-%d')}\n"
        f"扫描时间：{datetime.now().strftime('%H:%M')}\n\n"
        f"当前 x 词库：{existing_keywords}\n\n"
        "以下是本次扫描的推文数据，请按系统要求输出严格 JSON：\n\n"
        f"{prompt_material}\n"
    )

    client = genai.Client()
    for model in [MODEL_PRIMARY, MODEL_FALLBACK]:
        try:
            print(f"analysis model: {model}", file=sys.stderr)
            response = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=ANALYSIS_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=16384,
                ),
            )
            if response and response.text:
                parsed = _parse_analysis(response.text, model)
                if parsed:
                    return parsed
        except Exception as exc:
            message = str(exc)
            if "503" in message or "UNAVAILABLE" in message or "429" in message:
                print(f"warning: model unavailable {model}: {exc}", file=sys.stderr)
                continue
            print(f"warning: model failed {model}: {exc}", file=sys.stderr)
            continue

    print("warning: all Gemini models failed", file=sys.stderr)
    return None


def _render_markdown(analysis: dict[str, Any]) -> str:
    date_str = analysis.get("scan_date", datetime.now().strftime("%Y-%m-%d"))
    time_str = analysis.get("scan_time", datetime.now().strftime("%H:%M"))
    model = analysis.get("_model_used", "unknown")

    lines = [
        f"# X Sense Scan Report - {date_str}",
        "",
        f"Scan time: {time_str}",
        f"Model: {model}",
    ]

    summary = analysis.get("executive_summary", "")
    if summary:
        lines.extend(["", "## Executive Summary", "", str(summary)])

    trends = analysis.get("trends", [])
    if isinstance(trends, list) and trends:
        lines.extend(["", "## Trends", "", "| # | Signal | Strength | Category | Evidence |", "|---|---|---|---|---|"])
        for idx, trend in enumerate(trends, 1):
            lines.append(
                "| {idx} | {signal} | {strength} | {category} | {evidence} |".format(
                    idx=idx,
                    signal=str(trend.get("signal", "")).replace("|", " "),
                    strength=str(trend.get("strength", "")),
                    category=str(trend.get("category", "")),
                    evidence=str(trend.get("evidence", "")).replace("|", " "),
                )
            )

    top_tweets = analysis.get("top_tweets", [])
    if isinstance(top_tweets, list) and top_tweets:
        lines.extend(["", "## Top Tweets", ""])
        for idx, tweet in enumerate(top_tweets, 1):
            lines.append(f"### {idx}. @{tweet.get('author', 'unknown')}")
            lines.append(str(tweet.get("text", "")))
            lines.append(
                "likes={likes} retweets={retweets} replies={replies} | {category}".format(
                    likes=tweet.get("likes", 0),
                    retweets=tweet.get("retweets", 0),
                    replies=tweet.get("replies", 0),
                    category=tweet.get("category", ""),
                )
            )
            insight = tweet.get("insight", "")
            if insight:
                lines.append(f"insight: {insight}")
            lines.append("")

    clusters = analysis.get("topic_clusters", [])
    if isinstance(clusters, list) and clusters:
        lines.extend(["", "## Topic Clusters", ""])
        for cluster in clusters:
            lines.append(
                "- **{topic}** ({count}) sentiment={sentiment}".format(
                    topic=cluster.get("topic", "unknown"),
                    count=cluster.get("tweet_count", 0),
                    sentiment=cluster.get("sentiment", "unknown"),
                )
            )
            key_points = cluster.get("key_points", [])
            if isinstance(key_points, list):
                for point in key_points[:5]:
                    lines.append(f"  - {point}")

    new_keywords = analysis.get("new_keywords", {}).get("x", [])
    if isinstance(new_keywords, list) and new_keywords:
        lines.extend(["", "## New Keywords", "", ", ".join(str(item) for item in new_keywords)])

    lines.extend(["", "---", f"auto-generated by sense_scan.py | {model}"])
    return "\n".join(lines)


def save_outputs(raw_data: dict[str, Any], analysis: dict[str, Any] | None, output_dir: Path) -> dict[str, Path]:
    now = datetime.now()
    date_part = now.strftime("%Y-%m-%d")
    time_part = now.strftime("%H%M")

    # Organize by date subdirectory
    day_dir = output_dir / date_part
    day_dir.mkdir(parents=True, exist_ok=True)

    raw_path = day_dir / f"{date_part}_{time_part}_raw.json"
    raw_path.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"raw saved: {raw_path}", file=sys.stderr)

    paths: dict[str, Path] = {"raw": raw_path}

    if analysis is not None:
        analysis_path = day_dir / f"{date_part}_{time_part}_analysis.json"
        analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"analysis saved: {analysis_path}", file=sys.stderr)

        report_path = day_dir / f"{date_part}_{time_part}_report.md"
        report_path.write_text(_render_markdown(analysis), encoding="utf-8")
        print(f"report saved: {report_path}", file=sys.stderr)

        latest_path = output_dir / "latest.json"
        latest_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"latest saved: {latest_path}", file=sys.stderr)

        paths["analysis"] = analysis_path
        paths["report"] = report_path
        paths["latest"] = latest_path

    return paths


def _sync_shared_knowledge(
    tweets: list[dict[str, Any]],
    analysis: dict[str, Any] | None,
    keywords_used: list[str],
    km: KeywordManager | None,
) -> None:
    if not HAS_SHARED_KNOWLEDGE:
        return

    sk_data = SHARED_KNOWLEDGE_DIR / "data"

    # 1) keyword evolution
    if km is not None and analysis is not None:
        raw_new = analysis.get("new_keywords", {}).get("x", [])
        if isinstance(raw_new, list) and raw_new:
            new_words = [
                {"keyword": str(item).strip(), "source": f"x_ops_sense:{datetime.now().strftime('%Y-%m-%d')}"}
                for item in raw_new
                if str(item).strip()
            ]
            if new_words:
                km.evolve("x", new_words)
                km.gc()
                km.save()
                print(f"shared-knowledge keywords evolved: +{len(new_words)}", file=sys.stderr)

    # 2) vector indexing
    try:
        db_path = sk_data / "vector-index" / "knowledge.db"
        index = KnowledgeIndex(str(db_path))
        added = 0
        for tweet in tweets:
            text = str(tweet.get("text", "")).strip()
            if not text:
                continue
            created = str(tweet.get("created_at", ""))
            date_str = created[:10] if len(created) >= 10 else datetime.now().strftime("%Y-%m-%d")
            title = text[:80]
            metadata = {
                "tweet_id": tweet.get("id", ""),
                "url": tweet.get("url", ""),
                "author_username": tweet.get("author_username", ""),
                "author_name": tweet.get("author_name", ""),
                "keyword": tweet.get("keyword", ""),
                "metrics": tweet.get("metrics", {}),
            }
            try:
                index.add(
                    source="x_ops_sense",
                    channel="x",
                    date=date_str,
                    title=title,
                    text=text,
                    metadata=metadata,
                    tags=["x", "x-sense"],
                )
                added += 1
            except Exception as exc:
                print(f"warning: index add failed: {exc}", file=sys.stderr)
        index.close()
        print(f"shared-knowledge indexed chunks: {added}", file=sys.stderr)
    except Exception as exc:
        print(f"warning: shared-knowledge indexing failed: {exc}", file=sys.stderr)

    # 3) topic tracking from analysis
    if analysis is None:
        return

    try:
        tracker = TopicTracker(str(sk_data / "topics.json"))
        today = datetime.now().strftime("%Y-%m-%d")
        clusters = analysis.get("topic_clusters", [])
        if isinstance(clusters, list):
            for cluster in clusters:
                topic = str(cluster.get("topic", "")).strip()
                if not topic:
                    continue
                tracker.upsert(
                    _slugify(topic),
                    "x",
                    {
                        "display_name": topic,
                        "mentions": _to_int(cluster.get("tweet_count"), 0),
                        "keywords_used": keywords_used,
                        "last_seen": today,
                        "notes": f"sentiment={cluster.get('sentiment', 'unknown')}",
                    },
                )
        tracker.save()
        print("shared-knowledge topics updated", file=sys.stderr)
    except Exception as exc:
        print(f"warning: topic tracking failed: {exc}", file=sys.stderr)


def _record_keyword_outcomes(km: KeywordManager | None, per_keyword_counts: dict[str, int]) -> None:
    if km is None:
        return
    for keyword, count in per_keyword_counts.items():
        try:
            if count > 0:
                km.record_hit("x", keyword)
            else:
                km.record_miss("x", keyword)
        except Exception as exc:
            print(f"warning: keyword stats update failed for '{keyword}': {exc}", file=sys.stderr)
    try:
        km.gc()
        km.save()
    except Exception as exc:
        print(f"warning: keyword manager save failed: {exc}", file=sys.stderr)


def scan_x(
    client: XClient,
    keywords: list[str],
    max_per_keyword: int,
    seen_posts: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], dict[str, int], int, int]:
    per_keyword_raw: list[dict[str, Any]] = []
    all_kept: list[dict[str, Any]] = []
    next_seen = set(seen_posts)
    counts: dict[str, int] = {}
    excluded_total = 0
    dedup_total = 0

    for keyword in keywords:
        print(f"searching keyword: {keyword}", file=sys.stderr)
        tweets = client.search_recent(keyword, max_results=max_per_keyword, sort_order="relevancy")
        counts[keyword] = len(tweets)

        per_keyword_raw.append(
            {
                "keyword": keyword,
                "count": len(tweets),
                "tweets": tweets,
            }
        )

        kept, excluded = filter_excluded_tweets(tweets)
        deduped, next_seen, dedup_dropped = dedup_tweets(kept, next_seen)
        excluded_total += excluded
        dedup_total += dedup_dropped

        for tweet in deduped:
            tweet["keyword"] = keyword
            all_kept.append(tweet)

        print(
            f"  found={len(tweets)} kept={len(deduped)} excluded={excluded} dedup={dedup_dropped}",
            file=sys.stderr,
        )

    return per_keyword_raw, all_kept, next_seen, counts, excluded_total, dedup_total


def main() -> int:
    parser = argparse.ArgumentParser(description="X sense scanner")
    parser.add_argument(
        "--keywords",
        default="",
        help="Override keywords, comma separated",
    )
    parser.add_argument(
        "--skip-analysis",
        action="store_true",
        help="Only search X, skip Gemini analysis",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print analysis JSON to stdout",
    )
    parser.add_argument(
        "--max-per-keyword",
        type=int,
        default=10,
        help="Max search results per keyword",
    )

    args = parser.parse_args()

    output_dir = Path(args.output).expanduser() if args.output else OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    km: KeywordManager | None = None
    keywords: list[str] = []

    if args.keywords:
        keywords = _parse_keywords_arg(args.keywords)
        print(f"keywords source: cli ({len(keywords)})", file=sys.stderr)
    elif HAS_SHARED_KNOWLEDGE:
        kw_path = SHARED_KNOWLEDGE_DIR / "data" / "keywords.json"
        if kw_path.exists():
            try:
                km = KeywordManager(str(kw_path))
                keywords = km.get("x")
                print(f"keywords source: shared-knowledge ({len(keywords)})", file=sys.stderr)
            except Exception as exc:
                print(f"warning: failed to load shared keywords: {exc}", file=sys.stderr)

    if not keywords:
        keywords = list(DEFAULT_KEYWORDS_X)
        print(f"keywords source: default ({len(keywords)})", file=sys.stderr)

    if args.max_per_keyword < 1:
        print("error: --max-per-keyword must be >= 1", file=sys.stderr)
        return 1

    try:
        client = XClient()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    state = load_state(output_dir)
    seen_posts = {str(item) for item in state.get("seen_posts", []) if str(item).strip()}

    print("=== x-ops sense scan ===", file=sys.stderr)
    print(f"date: {datetime.now().strftime('%Y-%m-%d')}", file=sys.stderr)
    print(f"output: {output_dir}", file=sys.stderr)
    print(f"keywords: {', '.join(keywords)}", file=sys.stderr)

    raw_per_keyword, tweets, next_seen, counts, excluded_total, dedup_total = scan_x(
        client=client,
        keywords=keywords,
        max_per_keyword=args.max_per_keyword,
        seen_posts=seen_posts,
    )

    _record_keyword_outcomes(km, counts)
    save_state(output_dir, next_seen)

    raw_data = {
        "scan_date": datetime.now().strftime("%Y-%m-%d"),
        "scan_time": datetime.now().strftime("%H:%M"),
        "keywords": keywords,
        "max_per_keyword": args.max_per_keyword,
        "total_tweets_after_filter": len(tweets),
        "excluded_count": excluded_total,
        "dedup_dropped": dedup_total,
        "results": raw_per_keyword,
    }

    analysis: dict[str, Any] | None = None
    if not args.skip_analysis:
        analysis = analyze_with_gemini(tweets, keywords)
        if analysis is None:
            print("warning: analysis skipped/failed", file=sys.stderr)
    else:
        print("analysis skipped by --skip-analysis", file=sys.stderr)

    _sync_shared_knowledge(tweets, analysis, keywords, km)
    save_outputs(raw_data, analysis, output_dir)

    if args.json:
        print(json.dumps(analysis or {}, ensure_ascii=False, indent=2))

    print("=== scan complete ===", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
