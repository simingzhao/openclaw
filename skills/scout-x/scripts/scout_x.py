#!/usr/bin/env python3
"""
Scout X Patrol - Scout专用的X/Twitter巡逻脚本
智能调度搜索，最小化API成本
"""

import os
import sys
import json
import yaml
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

# 路径配置
WORKSPACE = Path(os.path.expanduser("~/.openclaw/workspace-scout"))
WATCHLIST_PATH = WORKSPACE / "sources" / "x-watchlist.yaml"
RAW_DIR = WORKSPACE / "raw" / "x-posts"
X_API_SCRIPT = Path(os.path.expanduser("~/Desktop/openclaw/skills/x-api/scripts/x_api.py"))
X_API_VENV = Path(os.path.expanduser("~/Desktop/openclaw/skills/x-api/.venv/bin/python3"))


def load_config():
    """加载配置文件"""
    if not WATCHLIST_PATH.exists():
        print(f"Error: Config not found at {WATCHLIST_PATH}", file=sys.stderr)
        sys.exit(1)
    with open(WATCHLIST_PATH, 'r') as f:
        return yaml.safe_load(f)


def save_config(config):
    """保存配置文件"""
    with open(WATCHLIST_PATH, 'w') as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def call_x_api(*args):
    """调用x-api脚本"""
    cmd = [str(X_API_VENV), str(X_API_SCRIPT)] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"X API error: {result.stderr}", file=sys.stderr)
            return None
        return json.loads(result.stdout) if result.stdout.strip() else None
    except subprocess.TimeoutExpired:
        print("X API timeout", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        print(f"X API invalid JSON: {result.stdout}", file=sys.stderr)
        return None


def search_keywords(config, force_all=False):
    """搜索关键词"""
    keywords = config.get('keywords', {})
    schedule = config.get('schedule', {})
    
    # Core关键词每次都搜
    to_search = list(keywords.get('core', []))
    
    # Trending关键词轮询
    trending = keywords.get('trending', [])
    if trending and not force_all:
        per_run = schedule.get('keywords_per_run', 3)
        idx = schedule.get('keyword_index', 0)
        
        # 取出本次要搜的
        selected = []
        for i in range(per_run):
            if trending:
                selected.append(trending[(idx + i) % len(trending)])
        to_search.extend(selected)
        
        # 更新轮询位置
        schedule['keyword_index'] = (idx + per_run) % len(trending) if trending else 0
    elif force_all:
        to_search.extend(trending)
    
    results = []
    seen = set(config.get('seen_posts', []))
    
    for kw in to_search:
        print(f"🔍 Searching: {kw}")
        data = call_x_api('search', kw, '--max-results', '10')
        if data and 'data' in data:
            for post in data['data']:
                post_id = post.get('id')
                if post_id and post_id not in seen:
                    results.append({
                        'id': post_id,
                        'text': post.get('text', ''),
                        'author_id': post.get('author_id', ''),
                        'source': f'keyword:{kw}',
                        'metrics': post.get('public_metrics', {})
                    })
                    seen.add(post_id)
    
    # 更新seen_posts（保留最近500个）
    config['seen_posts'] = list(seen)[-500:]
    
    return results


def fetch_accounts(config, force_all=False):
    """获取追踪账号的帖子"""
    accounts = config.get('accounts', {})
    schedule = config.get('schedule', {})
    
    # Tier1每次都查
    to_fetch = list(accounts.get('tier1', []))
    
    # Tier2和discovered轮询
    tier2 = accounts.get('tier2', []) + accounts.get('discovered', [])
    if tier2 and not force_all:
        per_run = schedule.get('accounts_per_run', 4)
        idx = schedule.get('account_index', 0)
        
        selected = []
        for i in range(per_run):
            if tier2:
                selected.append(tier2[(idx + i) % len(tier2)])
        to_fetch.extend(selected)
        
        schedule['account_index'] = (idx + per_run) % len(tier2) if tier2 else 0
    elif force_all:
        to_fetch.extend(tier2)
    
    results = []
    seen = set(config.get('seen_posts', []))
    
    for account in to_fetch:
        print(f"👤 Fetching: @{account}")
        data = call_x_api('user-posts', account, '--max-results', '5')
        if data and 'data' in data:
            for post in data['data']:
                post_id = post.get('id')
                if post_id and post_id not in seen:
                    results.append({
                        'id': post_id,
                        'text': post.get('text', ''),
                        'author': account,
                        'source': f'account:@{account}',
                        'metrics': post.get('public_metrics', {})
                    })
                    seen.add(post_id)
    
    config['seen_posts'] = list(seen)[-500:]
    
    return results


def save_results(results, patrol_type="patrol"):
    """保存结果到raw/x-posts/"""
    if not results:
        print("No new posts to save")
        return
    
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H:%M")
    filename = RAW_DIR / f"{date_str}_{patrol_type}.md"
    
    # 追加模式
    mode = 'a' if filename.exists() else 'w'
    
    with open(filename, mode) as f:
        if mode == 'w':
            f.write(f"# X Patrol - {date_str}\n\n")
        
        f.write(f"\n## {time_str} ({len(results)} posts)\n\n")
        
        for post in results:
            metrics = post.get('metrics', {})
            likes = metrics.get('like_count', 0)
            retweets = metrics.get('retweet_count', 0)
            
            f.write(f"### [{post.get('source', 'unknown')}]\n")
            if post.get('author'):
                f.write(f"**@{post['author']}**\n\n")
            f.write(f"{post.get('text', '')}\n\n")
            f.write(f"📊 Likes: {likes} | RT: {retweets} | ID: {post.get('id', '')}\n\n")
            f.write("---\n\n")
    
    print(f"✅ Saved {len(results)} posts to {filename}")


def check_discovery(results, config):
    """检查是否有值得追踪的新账号"""
    discovery = config.get('discovery', {})
    if not discovery.get('enabled', True):
        return
    
    min_likes = discovery.get('min_likes', 1000)
    min_retweets = discovery.get('min_retweets', 200)
    max_discovered = discovery.get('max_discovered', 20)
    
    existing = set(
        config.get('accounts', {}).get('tier1', []) +
        config.get('accounts', {}).get('tier2', []) +
        config.get('accounts', {}).get('discovered', [])
    )
    
    discovered = config.setdefault('accounts', {}).setdefault('discovered', [])
    
    for post in results:
        metrics = post.get('metrics', {})
        likes = metrics.get('like_count', 0)
        retweets = metrics.get('retweet_count', 0)
        author = post.get('author') or post.get('author_id')
        
        if author and author not in existing:
            if likes >= min_likes or retweets >= min_retweets:
                print(f"🆕 Discovered high-engagement account: @{author}")
                discovered.append(author)
                existing.add(author)
    
    # 限制discovered列表大小
    if len(discovered) > max_discovered:
        config['accounts']['discovered'] = discovered[-max_discovered:]


def cmd_patrol(args, config):
    """执行巡逻"""
    print("🚀 Starting X patrol...")
    
    # 搜索关键词
    kw_results = search_keywords(config)
    
    # 获取账号帖子
    acc_results = fetch_accounts(config)
    
    all_results = kw_results + acc_results
    
    # 保存结果
    save_results(all_results)
    
    # 检查新发现
    check_discovery(all_results, config)
    
    # 更新时间戳
    config['schedule']['last_run'] = datetime.now().isoformat()
    save_config(config)
    
    print(f"\n📊 Patrol complete: {len(all_results)} new posts")
    return all_results


def cmd_status(args, config):
    """显示配置状态"""
    keywords = config.get('keywords', {})
    accounts = config.get('accounts', {})
    schedule = config.get('schedule', {})
    
    print("═" * 50)
    print("Scout X Watchlist Status")
    print("═" * 50)
    print(f"\n📝 Keywords:")
    print(f"   Core: {len(keywords.get('core', []))} items")
    print(f"   Trending: {len(keywords.get('trending', []))} items")
    print(f"   Next index: {schedule.get('keyword_index', 0)}")
    
    print(f"\n👥 Accounts:")
    print(f"   Tier1: {len(accounts.get('tier1', []))} accounts")
    print(f"   Tier2: {len(accounts.get('tier2', []))} accounts")
    print(f"   Discovered: {len(accounts.get('discovered', []))} accounts")
    print(f"   Next index: {schedule.get('account_index', 0)}")
    
    print(f"\n⏰ Last run: {schedule.get('last_run', 'Never')}")
    print(f"📦 Seen posts: {len(config.get('seen_posts', []))}")


def cmd_add_keyword(args, config):
    """添加关键词"""
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
    """添加账号"""
    tier = args.tier or 'tier2'
    account = args.account.lstrip('@')
    
    accounts = config.setdefault('accounts', {})
    tier_list = accounts.setdefault(tier, [])
    
    if account not in tier_list:
        tier_list.append(account)
        save_config(config)
        print(f"✅ Added @{account} to {tier}")
    else:
        print(f"Already exists: @{account} in {tier}")


def main():
    parser = argparse.ArgumentParser(description="Scout X Patrol")
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # patrol
    patrol_parser = subparsers.add_parser('patrol', help='Run full patrol')
    
    # keywords
    kw_parser = subparsers.add_parser('keywords', help='Search keywords only')
    
    # accounts
    acc_parser = subparsers.add_parser('accounts', help='Fetch accounts only')
    
    # status
    status_parser = subparsers.add_parser('status', help='Show config status')
    
    # add-keyword
    add_kw_parser = subparsers.add_parser('add-keyword', help='Add a keyword')
    add_kw_parser.add_argument('keyword', help='Keyword to add')
    add_kw_parser.add_argument('--tier', choices=['core', 'trending'], default='trending')
    
    # add-account
    add_acc_parser = subparsers.add_parser('add-account', help='Add an account')
    add_acc_parser.add_argument('account', help='Account to add')
    add_acc_parser.add_argument('--tier', choices=['tier1', 'tier2', 'discovered'], default='tier2')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    config = load_config()
    
    if args.command == 'patrol':
        cmd_patrol(args, config)
    elif args.command == 'keywords':
        results = search_keywords(config)
        save_results(results, 'keywords')
        save_config(config)
    elif args.command == 'accounts':
        results = fetch_accounts(config)
        save_results(results, 'accounts')
        save_config(config)
    elif args.command == 'status':
        cmd_status(args, config)
    elif args.command == 'add-keyword':
        cmd_add_keyword(args, config)
    elif args.command == 'add-account':
        cmd_add_account(args, config)


if __name__ == '__main__':
    main()
