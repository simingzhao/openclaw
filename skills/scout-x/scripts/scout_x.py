#!/usr/bin/env python3
"""
Scout X Patrol - Scout专用的X/Twitter巡逻脚本
智能调度搜索，最小化API成本，自维护watchlist
"""

import os
import sys
import json
import yaml
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# ── paths ──────────────────────────────────────────────────────
WORKSPACE = Path(os.environ.get("SCOUT_WORKSPACE", os.path.expanduser("~/.openclaw/workspace")))
WATCHLIST_PATH = WORKSPACE / "sources" / "x-watchlist.yaml"
STATE_PATH = WORKSPACE / "sources" / "x-patrol-state.json"
METRICS_PATH = WORKSPACE / "sources" / "x-watchlist-metrics.json"
RAW_DIR = WORKSPACE / "raw" / "x-posts"
X_API_SCRIPT = Path(os.path.expanduser("~/Desktop/openclaw/skills/x-api/scripts/x_api.py"))
X_API_VENV = Path(os.path.expanduser("~/Desktop/openclaw/skills/x-api/.venv/bin/python3"))


# ── config, state & metrics ────────────────────────────────────
def load_config():
    if not WATCHLIST_PATH.exists():
        print(f"Error: Config not found at {WATCHLIST_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(WATCHLIST_PATH, 'r') as f:
        return yaml.safe_load(f)


def save_config(config):
    with open(WATCHLIST_PATH, 'w') as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_state():
    if STATE_PATH.exists():
        with open(STATE_PATH, 'r') as f:
            return json.load(f)
    return {"keyword_index": 0, "account_index": 0, "seen_posts": [], "last_run": None}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, 'w') as f:
        json.dump(state, f, indent=2)


def load_metrics():
    """加载watchlist质量指标"""
    if METRICS_PATH.exists():
        with open(METRICS_PATH, 'r') as f:
            return json.load(f)
    return {"accounts": {}, "keywords": {}, "last_maintain": None}


def save_metrics(metrics):
    with open(METRICS_PATH, 'w') as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)


# ── helpers ────────────────────────────────────────────────────
def call_x_api(*args, timeout=60):
    """调用x-api脚本，返回parsed JSON或None"""
    cmd = [str(X_API_VENV), str(X_API_SCRIPT)] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            err = result.stderr.strip()
            if err:
                print(f"  ⚠ X API error: {err[:200]}", file=sys.stderr)
            return None
        return json.loads(result.stdout) if result.stdout.strip() else None
    except subprocess.TimeoutExpired:
        print("  ⚠ X API timeout", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        return None


def call_x_api_user_by_id(user_id: str) -> dict | None:
    """通过X API的/users/:id端点解析用户ID为用户名。
    使用x_api.py的OAuth session，直接调用API。"""
    # Build a small inline script that reuses x_api's session
    script = f"""
import sys
sys.path.insert(0, '{X_API_SCRIPT.parent}')
from x_api import get_oauth1_session, api_get
import json
session = get_oauth1_session()
data = api_get(session, '/users/{user_id}', params={{'user.fields': 'id,username,name,description,public_metrics'}})
if data and 'data' in data:
    print(json.dumps(data['data']))
"""
    try:
        result = subprocess.run(
            [str(X_API_VENV), '-c', script],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def collect_tier2_accounts(accounts: dict) -> list:
    """收集所有tier2_*子组的账号"""
    result = []
    for key, val in accounts.items():
        if key.startswith("tier2") and isinstance(val, list):
            result.extend(val)
    return result


def find_account_tier(accounts: dict, username: str) -> str | None:
    """找到账号所在的tier"""
    for key, val in accounts.items():
        if isinstance(val, list) and username in val:
            return key
    return None


def matches_exclude(text: str, exclude_keywords: list) -> bool:
    if not exclude_keywords:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in exclude_keywords)


def format_post(post: dict) -> str:
    metrics = post.get('metrics', {})
    likes = metrics.get('like_count', 0)
    rts = metrics.get('retweet_count', 0)
    views = metrics.get('impression_count', 0)
    source = post.get('source', '')
    author = post.get('author', '')
    text = post.get('text', '').strip()
    pid = post.get('id', '')
    thread = post.get('thread')

    lines = []
    header = f"### {source}"
    if author:
        header += f" — @{author}"
    if thread:
        header += f" 🧵 ({thread['length']} tweets)"
    lines.append(header)
    lines.append("")

    if thread:
        # Render full thread
        for i, t in enumerate(thread.get('tweets', []), 1):
            lines.append(f"**[{i}/{thread['length']}]**")
            lines.append(t.get('text', '').strip())
            lines.append("")
    else:
        lines.append(text)
        lines.append("")

    stats = f"❤️ {likes}  🔁 {rts}"
    if views:
        stats += f"  👁 {views}"
    stats += f"  | ID: {pid}"
    if thread:
        stats += f"  | conv: {thread.get('conversation_id', '')}"
    lines.append(stats)
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def fetch_thread(conversation_id: str, author: str) -> dict | None:
    """拉取完整thread内容"""
    data = call_x_api('thread', conversation_id, '--max-results', '100')
    if not data or 'data' not in data:
        return None
    tweets = data['data']
    if len(tweets) <= 1:
        return None  # 不是真正的thread
    return {
        'conversation_id': data.get('meta', {}).get('conversation_id', conversation_id),
        'author': data.get('meta', {}).get('author', author),
        'length': len(tweets),
        'tweets': tweets,
    }


# ── metrics tracking ──────────────────────────────────────────
def update_account_metrics(metrics: dict, account: str, posts: list):
    """更新账号的质量指标"""
    am = metrics.setdefault("accounts", {}).setdefault(account, {
        "total_posts": 0,
        "total_likes": 0,
        "total_rts": 0,
        "hits": 0,        # 被patrol抓到的次数
        "misses": 0,       # 没抓到新内容的次数
        "last_seen": None,
        "avg_engagement": 0,
    })
    if posts:
        am["hits"] += 1
        am["last_seen"] = datetime.now().isoformat()
        for p in posts:
            m = p.get("metrics", {})
            am["total_posts"] += 1
            am["total_likes"] += m.get("like_count", 0)
            am["total_rts"] += m.get("retweet_count", 0)
        if am["total_posts"] > 0:
            am["avg_engagement"] = round(
                (am["total_likes"] + am["total_rts"] * 3) / am["total_posts"]
            )
    else:
        am["misses"] += 1


def update_keyword_metrics(metrics: dict, keyword: str, posts: list):
    """更新关键词的质量指标"""
    km = metrics.setdefault("keywords", {}).setdefault(keyword, {
        "searches": 0,
        "total_results": 0,
        "total_likes": 0,
        "avg_results": 0,
        "avg_engagement": 0,
        "last_searched": None,
    })
    km["searches"] += 1
    km["last_searched"] = datetime.now().isoformat()
    km["total_results"] += len(posts)
    for p in posts:
        km["total_likes"] += p.get("metrics", {}).get("like_count", 0)
    if km["searches"] > 0:
        km["avg_results"] = round(km["total_results"] / km["searches"], 1)
    if km["total_results"] > 0:
        km["avg_engagement"] = round(km["total_likes"] / km["total_results"])


# ── core patrol logic ──────────────────────────────────────────
def search_keywords(config, state, metrics=None, force_all=False):
    keywords = config.get('keywords', {})
    schedule = config.get('schedule', {})
    exclude = config.get('filters', {}).get('exclude_keywords', [])

    to_search = list(keywords.get('core', []))

    trending = keywords.get('trending', [])
    if trending and not force_all:
        per_run = schedule.get('keywords_per_run', 3)
        idx = state.get('keyword_index', 0)
        for i in range(per_run):
            to_search.append(trending[(idx + i) % len(trending)])
        state['keyword_index'] = (idx + per_run) % len(trending)
    elif force_all:
        to_search.extend(trending)

    seen = set(state.get('seen_posts', []))
    results = []

    for kw in to_search:
        print(f"🔍 Searching: {kw}")
        query = f"{kw} -is:retweet lang:en"
        data = call_x_api('search', query, '--max-results', '10', '--sort-order', 'relevancy')
        kw_posts = []
        if data and 'data' in data:
            for post in data['data']:
                pid = post.get('id')
                if not pid or pid in seen:
                    continue
                text = post.get('text', '')
                if matches_exclude(text, exclude):
                    continue
                p = {
                    'id': pid,
                    'text': text,
                    'author': post.get('author_id', ''),
                    'source': f'keyword:{kw}',
                    'metrics': post.get('public_metrics', {})
                }
                kw_posts.append(p)
                results.append(p)
                seen.add(pid)
        if metrics is not None:
            update_keyword_metrics(metrics, kw, kw_posts)

    state['seen_posts'] = list(seen)[-500:]
    return results


def fetch_accounts(config, state, metrics=None, force_all=False):
    accounts = config.get('accounts', {})
    schedule = config.get('schedule', {})
    exclude = config.get('filters', {}).get('exclude_keywords', [])

    to_fetch = list(accounts.get('tier1', []))

    tier2_all = collect_tier2_accounts(accounts)
    if tier2_all and not force_all:
        per_run = schedule.get('accounts_per_run', 6)
        idx = state.get('account_index', 0)
        for i in range(per_run):
            to_fetch.append(tier2_all[(idx + i) % len(tier2_all)])
        state['account_index'] = (idx + per_run) % len(tier2_all)
    elif force_all:
        to_fetch.extend(tier2_all)

    seen = set(state.get('seen_posts', []))
    results = []

    seen_convs = set()  # 已拉取的 conversation_id，避免重复拉thread

    for account in to_fetch:
        print(f"👤 Fetching: @{account}")
        data = call_x_api('user-posts', account, '--max-results', '5', '--exclude', 'replies', 'retweets')
        acc_posts = []
        if data and 'data' in data:
            for post in data['data']:
                pid = post.get('id')
                if not pid or pid in seen:
                    continue
                text = post.get('text', '')
                if matches_exclude(text, exclude):
                    continue

                conv_id = post.get('conversation_id')
                p = {
                    'id': pid,
                    'text': text,
                    'author': account,
                    'source': 'account',
                    'metrics': post.get('public_metrics', {})
                }

                # 检测thread: conversation_id == post id 说明是thread starter
                # referenced_tweets 有 replied_to 自己 说明是thread continuation
                refs = post.get('referenced_tweets', [])
                is_thread_part = conv_id and conv_id == pid and any(
                    r.get('type') == 'replied_to' for r in refs
                )
                # 更简单的判断：如果 conversation_id == id，这可能是thread头
                # 我们直接尝试拉取，如果只有1条就不是thread
                if conv_id and conv_id not in seen_convs:
                    seen_convs.add(conv_id)
                    thread = fetch_thread(conv_id, account)
                    if thread:
                        p['thread'] = thread
                        # 把thread里所有tweet id加入seen
                        for t in thread.get('tweets', []):
                            seen.add(t.get('id', ''))
                        print(f"  🧵 Thread detected: {thread['length']} tweets")

                acc_posts.append(p)
                results.append(p)
                seen.add(pid)
        if metrics is not None:
            update_account_metrics(metrics, account, acc_posts)

    state['seen_posts'] = list(seen)[-500:]
    return results


def check_discovery(results, config):
    discovery = config.get('discovery', {})
    if not discovery.get('enabled', True):
        return

    min_likes = discovery.get('min_likes', 1000)
    min_rts = discovery.get('min_retweets', 200)
    max_disc = discovery.get('max_discovered', 20)

    all_known = set()
    for key, val in config.get('accounts', {}).items():
        if isinstance(val, list):
            all_known.update(str(v) for v in val)

    discovered = config.setdefault('accounts', {}).setdefault('discovered', [])

    for post in results:
        m = post.get('metrics', {})
        author = post.get('author') or post.get('author_id')
        if not author or str(author) in all_known:
            continue
        if m.get('like_count', 0) >= min_likes or m.get('retweet_count', 0) >= min_rts:
            print(f"🆕 Discovered: {author}")
            discovered.append(str(author))
            all_known.add(str(author))

    if len(discovered) > max_disc:
        config['accounts']['discovered'] = discovered[-max_disc:]


# ── output ─────────────────────────────────────────────────────
def save_results(results, patrol_type="patrol"):
    if not results:
        print("No new posts to save")
        return None

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H:%M")
    filepath = RAW_DIR / f"{date_str}_{patrol_type}.md"

    mode = 'a' if filepath.exists() else 'w'
    with open(filepath, mode) as f:
        if mode == 'w':
            f.write(f"# X Patrol - {date_str}\n\n")
        f.write(f"\n## {time_str} — {len(results)} posts\n\n")
        for post in results:
            f.write(format_post(post))

    print(f"✅ Saved {len(results)} posts → {filepath.name}")
    return str(filepath)


def print_json_summary(results):
    summary = {
        "total": len(results),
        "timestamp": datetime.now().isoformat(),
        "top_posts": sorted(results, key=lambda p: p.get('metrics', {}).get('like_count', 0), reverse=True)[:10],
    }
    for p in summary["top_posts"]:
        p['text'] = p['text'][:280]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


# ── watchlist maintenance ──────────────────────────────────────
def cmd_maintain(args, config):
    """分析watchlist质量，生成维护建议并可选自动执行"""
    metrics = load_metrics()
    am = metrics.get("accounts", {})
    km = metrics.get("keywords", {})

    if not am and not km:
        print("⚠ 没有指标数据（需要跑几次patrol积累）。跳过质量分析，执行ID解析...\n")

    report = {
        "timestamp": datetime.now().isoformat(),
        "actions_taken": [],
        "suggestions": [],
    }

    accounts = config.get('accounts', {})
    all_tier2 = collect_tier2_accounts(accounts)

    # ── 1. 识别低效账号 ──
    print("\n📊 账号质量分析:")
    dead_accounts = []
    low_quality = []
    stars = []

    for acct, data in am.items():
        total = data.get("hits", 0) + data.get("misses", 0)
        if total < 2:
            continue  # 数据不够

        hit_rate = data["hits"] / total if total > 0 else 0
        avg_eng = data.get("avg_engagement", 0)
        tier = find_account_tier(accounts, acct)

        if data["misses"] >= 5 and hit_rate < 0.2:
            dead_accounts.append((acct, tier, hit_rate, data["misses"]))
        elif avg_eng < 10 and total >= 3 and tier and tier != "tier1":
            low_quality.append((acct, tier, avg_eng, total))
        elif avg_eng > 500 and tier and tier.startswith("tier2"):
            stars.append((acct, tier, avg_eng))

    if dead_accounts:
        print(f"\n  💀 沉默账号 ({len(dead_accounts)}):")
        for acct, tier, hr, misses in dead_accounts:
            print(f"     @{acct} [{tier}] — 命中率 {hr:.0%}, 连续失败 {misses}次")
            report["suggestions"].append({
                "action": "remove",
                "target": acct,
                "tier": tier,
                "reason": f"hit_rate={hr:.0%}, misses={misses}"
            })

    if low_quality:
        print(f"\n  📉 低互动账号 ({len(low_quality)}):")
        for acct, tier, eng, total in sorted(low_quality, key=lambda x: x[2]):
            print(f"     @{acct} [{tier}] — 平均互动 {eng}, 采样 {total}次")
            report["suggestions"].append({
                "action": "consider_remove",
                "target": acct,
                "tier": tier,
                "reason": f"avg_engagement={eng}"
            })

    if stars:
        print(f"\n  ⭐ 高质量账号 (可考虑升tier1):")
        for acct, tier, eng in sorted(stars, key=lambda x: -x[2]):
            print(f"     @{acct} [{tier}] — 平均互动 {eng}")
            report["suggestions"].append({
                "action": "promote",
                "target": acct,
                "from_tier": tier,
                "to_tier": "tier1",
                "reason": f"avg_engagement={eng}"
            })

    # ── 2. 识别低效关键词 ──
    print("\n📝 关键词质量分析:")
    bad_keywords = []
    good_keywords = []

    for kw, data in km.items():
        if data.get("searches", 0) < 2:
            continue
        avg_res = data.get("avg_results", 0)
        avg_eng = data.get("avg_engagement", 0)

        if avg_res < 1:
            bad_keywords.append((kw, avg_res, avg_eng))
        elif avg_eng > 200:
            good_keywords.append((kw, avg_res, avg_eng))

    if bad_keywords:
        print(f"\n  🚫 低产关键词:")
        for kw, res, eng in bad_keywords:
            print(f"     '{kw}' — 平均结果 {res}, 平均互动 {eng}")
            report["suggestions"].append({
                "action": "consider_remove_keyword",
                "target": kw,
                "reason": f"avg_results={res}"
            })

    if good_keywords:
        print(f"\n  ✅ 高质量关键词:")
        for kw, res, eng in sorted(good_keywords, key=lambda x: -x[2]):
            print(f"     '{kw}' — 平均结果 {res}, 平均互动 {eng}")

    # ── 3. Discovered → 解析用户名 ──
    discovered = accounts.get('discovered', [])
    id_entries = [d for d in discovered if d.isdigit()]
    if id_entries:
        print(f"\n  🔍 解析 {len(id_entries)} 个 discovered user IDs...")
        resolved = 0
        for uid in id_entries[:5]:  # 每次最多解析5个，控制API调用
            # get-user expects username, so use get-post trick: look up via user-posts
            # Actually, use the X API /users/:id endpoint via a direct call
            data = call_x_api_user_by_id(uid)
            if data:
                username = data.get('username')
                if username:
                    idx = discovered.index(uid)
                    discovered[idx] = username
                    resolved += 1
                    print(f"     {uid} → @{username}")
                    report["actions_taken"].append({
                        "action": "resolved_id",
                        "from": uid,
                        "to": username
                    })
        if resolved:
            save_config(config)
            print(f"  ✅ 解析了 {resolved} 个用户ID")

    # ── 4. 自动清理（--apply 模式）──
    if args.apply:
        removed = 0
        # 只自动删除confirmed dead accounts (非tier1)
        for acct, tier, hr, misses in dead_accounts:
            if tier and tier != "tier1" and tier != "discovered":
                tier_list = accounts.get(tier, [])
                if acct in tier_list:
                    tier_list.remove(acct)
                    removed += 1
                    print(f"  🗑 Removed @{acct} from {tier}")
                    report["actions_taken"].append({
                        "action": "removed",
                        "target": acct,
                        "tier": tier
                    })
        if removed:
            save_config(config)
            print(f"\n✅ 自动清理了 {removed} 个沉默账号")
    else:
        if dead_accounts or low_quality:
            print(f"\n💡 运行 `maintain --apply` 自动清理沉默账号")

    # ── 5. 保存维护报告 ──
    metrics["last_maintain"] = datetime.now().isoformat()
    save_metrics(metrics)

    # 输出JSON报告（供agent消费）
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return report


def cmd_health(args, config):
    """快速健康检查 — 输出JSON供agent决策"""
    metrics = load_metrics()
    state = load_state()
    accounts = config.get('accounts', {})
    keywords = config.get('keywords', {})
    tier2_all = collect_tier2_accounts(accounts)

    # 计算覆盖率
    am = metrics.get("accounts", {})
    tracked = set()
    for key, val in accounts.items():
        if isinstance(val, list):
            tracked.update(val)

    covered = set(am.keys()) & tracked
    coverage = len(covered) / len(tracked) if tracked else 0

    # 计算平均质量
    engagements = [v.get("avg_engagement", 0) for v in am.values() if v.get("total_posts", 0) > 0]
    avg_quality = sum(engagements) / len(engagements) if engagements else 0

    # 发现未追踪的高互动ID
    discovered = accounts.get("discovered", [])
    unresolved_ids = [d for d in discovered if d.isdigit()]

    health = {
        "total_accounts": len(tracked),
        "tier1": len(accounts.get("tier1", [])),
        "tier2_pool": len(tier2_all),
        "discovered": len(discovered),
        "unresolved_ids": len(unresolved_ids),
        "total_keywords": len(keywords.get("core", [])) + len(keywords.get("trending", [])),
        "data_coverage": round(coverage, 2),
        "avg_engagement": round(avg_quality),
        "seen_posts": len(state.get("seen_posts", [])),
        "last_run": state.get("last_run"),
        "last_maintain": metrics.get("last_maintain"),
        "needs_maintain": metrics.get("last_maintain") is None or (
            datetime.now() - datetime.fromisoformat(metrics["last_maintain"])
        ).days >= 3 if metrics.get("last_maintain") else True,
    }

    print(json.dumps(health, ensure_ascii=False, indent=2))
    return health


# ── commands ───────────────────────────────────────────────────
def cmd_patrol(args, config):
    state = load_state()
    metrics = load_metrics()
    print("🚀 Starting X patrol...\n")

    kw_results = search_keywords(config, state, metrics)
    acc_results = fetch_accounts(config, state, metrics)
    all_results = kw_results + acc_results

    filepath = save_results(all_results)
    check_discovery(all_results, config)

    state['last_run'] = datetime.now().isoformat()
    save_state(state)
    save_config(config)
    save_metrics(metrics)

    print(f"\n📊 Patrol complete: {len(all_results)} new posts")
    print(f"   Keywords: {len(kw_results)} | Accounts: {len(acc_results)}")

    if args.json:
        print_json_summary(all_results)

    return all_results


def cmd_keywords(args, config):
    state = load_state()
    metrics = load_metrics()
    results = search_keywords(config, state, metrics, force_all=args.all)
    save_results(results, 'keywords')
    save_state(state)
    save_metrics(metrics)
    if args.json:
        print_json_summary(results)


def cmd_accounts(args, config):
    state = load_state()
    metrics = load_metrics()
    results = fetch_accounts(config, state, metrics, force_all=args.all)
    save_results(results, 'accounts')
    save_state(state)
    save_metrics(metrics)
    if args.json:
        print_json_summary(results)


def cmd_search(args, config):
    print(f"🔍 Searching: {args.query}")
    data = call_x_api('search', args.query, '--max-results', str(args.max_results), '--sort-order', 'relevancy')
    if not data or 'data' not in data:
        print("No results")
        return

    results = []
    for post in data['data']:
        results.append({
            'id': post.get('id', ''),
            'text': post.get('text', ''),
            'author': post.get('author_id', ''),
            'source': f'search:{args.query}',
            'metrics': post.get('public_metrics', {})
        })

    save_results(results, 'search')
    if args.json:
        print_json_summary(results)


def cmd_status(args, config):
    state = load_state()
    metrics = load_metrics()
    keywords = config.get('keywords', {})
    accounts = config.get('accounts', {})
    schedule = config.get('schedule', {})
    tier2_all = collect_tier2_accounts(accounts)
    am = metrics.get("accounts", {})

    print("═" * 50)
    print("Scout X Watchlist Status")
    print("═" * 50)

    print(f"\n📝 Keywords:")
    core = keywords.get('core', [])
    trending = keywords.get('trending', [])
    print(f"   Core ({len(core)}): {', '.join(core[:5])}{'...' if len(core)>5 else ''}")
    print(f"   Trending ({len(trending)}): next index {state.get('keyword_index', 0)}")

    print(f"\n👥 Accounts:")
    t1 = accounts.get('tier1', [])
    print(f"   Tier1 ({len(t1)}): {', '.join(t1[:5])}{'...' if len(t1)>5 else ''}")
    for key, val in accounts.items():
        if key.startswith("tier2") and isinstance(val, list):
            print(f"   {key} ({len(val)})")
    disc = accounts.get('discovered', [])
    unresolved = [d for d in disc if d.isdigit()]
    print(f"   Discovered ({len(disc)}, {len(unresolved)} unresolved IDs)")
    print(f"   Total tier2 pool: {len(tier2_all)} | next index {state.get('account_index', 0)}")

    print(f"\n⏰ Last run: {state.get('last_run', 'Never')}")
    print(f"🔧 Last maintain: {metrics.get('last_maintain', 'Never')}")
    print(f"📦 Seen posts: {len(state.get('seen_posts', []))}")
    print(f"🔄 Per run: {schedule.get('keywords_per_run', 3)} keywords, {schedule.get('accounts_per_run', 6)} accounts")

    # Top accounts by engagement
    if am:
        ranked = sorted(
            [(k, v) for k, v in am.items() if v.get("total_posts", 0) > 0],
            key=lambda x: -x[1].get("avg_engagement", 0)
        )[:5]
        if ranked:
            print(f"\n🏆 Top accounts (by engagement):")
            for acct, data in ranked:
                print(f"   @{acct} — avg {data['avg_engagement']}, {data['total_posts']} posts")

    exclude = config.get('filters', {}).get('exclude_keywords', [])
    if exclude:
        print(f"\n🚫 Exclude filters: {len(exclude)} keywords")


def cmd_add_keyword(args, config):
    tier = args.tier or 'trending'
    kw = args.keyword
    keywords = config.setdefault('keywords', {})
    tier_list = keywords.setdefault(tier, [])
    if kw not in tier_list:
        tier_list.append(kw)
        save_config(config)
        print(f"✅ Added '{kw}' to {tier}")
    else:
        print(f"Already exists: '{kw}' in {tier}")


def cmd_add_account(args, config):
    tier = args.tier or 'tier2_builders'
    account = args.account.lstrip('@')
    accounts = config.setdefault('accounts', {})
    tier_list = accounts.setdefault(tier, [])
    if account not in tier_list:
        tier_list.append(account)
        save_config(config)
        print(f"✅ Added @{account} to {tier}")
    else:
        print(f"Already exists: @{account} in {tier}")


def cmd_remove_keyword(args, config):
    kw = args.keyword
    for tier, items in config.get('keywords', {}).items():
        if isinstance(items, list) and kw in items:
            items.remove(kw)
            save_config(config)
            print(f"✅ Removed '{kw}' from {tier}")
            return
    print(f"Not found: '{kw}'")


def cmd_remove_account(args, config):
    account = args.account.lstrip('@')
    for tier, items in config.get('accounts', {}).items():
        if isinstance(items, list) and account in items:
            items.remove(account)
            save_config(config)
            print(f"✅ Removed @{account} from {tier}")
            return
    print(f"Not found: @{account}")


# ── main ───────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Scout X Patrol")
    parser.add_argument('--json', action='store_true', help='Output JSON summary to stdout')
    subparsers = parser.add_subparsers(dest='command')

    subparsers.add_parser('patrol', help='Run full patrol')

    kw_p = subparsers.add_parser('keywords', help='Search keywords only')
    kw_p.add_argument('--all', action='store_true', help='Search ALL keywords')

    acc_p = subparsers.add_parser('accounts', help='Fetch accounts only')
    acc_p.add_argument('--all', action='store_true', help='Fetch ALL accounts')

    search_p = subparsers.add_parser('search', help='Ad-hoc search (no state change)')
    search_p.add_argument('query')
    search_p.add_argument('--max-results', type=int, default=20)

    subparsers.add_parser('status', help='Show config status')

    maintain_p = subparsers.add_parser('maintain', help='Analyze watchlist quality & auto-maintain')
    maintain_p.add_argument('--apply', action='store_true', help='Auto-remove dead accounts')

    subparsers.add_parser('health', help='Quick health check (JSON output for agent)')

    add_kw = subparsers.add_parser('add-keyword', help='Add a keyword')
    add_kw.add_argument('keyword')
    add_kw.add_argument('--tier', choices=['core', 'trending'], default='trending')

    add_acc = subparsers.add_parser('add-account', help='Add an account')
    add_acc.add_argument('account')
    add_acc.add_argument('--tier', default='tier2_builders')

    rm_kw = subparsers.add_parser('remove-keyword', help='Remove a keyword')
    rm_kw.add_argument('keyword')

    rm_acc = subparsers.add_parser('remove-account', help='Remove an account')
    rm_acc.add_argument('account')

    subparsers.add_parser('migrate-state', help='Migrate state from watchlist YAML to JSON')

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = load_config()

    # One-time migration
    if args.command == 'migrate-state' or (not STATE_PATH.exists() and 'seen_posts' in config):
        state = {
            "keyword_index": config.get('schedule', {}).pop('keyword_index', 0),
            "account_index": config.get('schedule', {}).pop('account_index', 0),
            "seen_posts": config.pop('seen_posts', []),
            "last_run": config.get('schedule', {}).pop('last_run', None),
        }
        save_state(state)
        save_config(config)
        print("✅ Migrated state → x-patrol-state.json")
        if args.command == 'migrate-state':
            return

    commands = {
        'patrol': cmd_patrol,
        'keywords': cmd_keywords,
        'accounts': cmd_accounts,
        'search': cmd_search,
        'status': cmd_status,
        'maintain': cmd_maintain,
        'health': cmd_health,
        'add-keyword': cmd_add_keyword,
        'add-account': cmd_add_account,
        'remove-keyword': cmd_remove_keyword,
        'remove-account': cmd_remove_account,
    }

    fn = commands.get(args.command)
    if fn:
        fn(args, config)


if __name__ == '__main__':
    main()
