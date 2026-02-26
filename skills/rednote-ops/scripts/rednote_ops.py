#!/usr/bin/env python3
"""
小红书操作 CLI — 基于 xiaohongshu-mcp。

发布、搜索、互动、数据拉取、账号管理 — 所有平台操作。
"""

import argparse
import json
import os
import sys
import time
import uuid

try:
    import requests
except ImportError:
    print("需要 requests: pip install requests", file=sys.stderr)
    sys.exit(1)

MCP_URL = os.environ.get("REDNOTE_MCP_URL", "http://localhost:18060/mcp")
MAX_TITLE_LEN = 20
MAX_CONTENT_LEN = 950

_session_id = None


# ─── MCP 底层 ───────────────────────────────────────────────

def _init():
    """初始化 MCP session。"""
    global _session_id
    if _session_id is not None:
        return
    payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "rednote-ops", "version": "1.0.0"},
        },
        "id": "init-" + str(uuid.uuid4()),
    }
    try:
        resp = requests.post(MCP_URL, json=payload, timeout=15)
        resp.raise_for_status()
        _session_id = resp.headers.get("Mcp-Session-Id", "")
        headers = {"Content-Type": "application/json"}
        if _session_id:
            headers["Mcp-Session-Id"] = _session_id
        requests.post(MCP_URL, json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }, headers=headers, timeout=5)
        time.sleep(0.3)
    except requests.ConnectionError:
        print(f"❌ 无法连接 MCP ({MCP_URL})。确认 xiaohongshu-mcp 已启动。", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ MCP初始化失败: {e}", file=sys.stderr)
        sys.exit(1)


def call(method: str, params: dict | None = None) -> dict:
    """调用 MCP tool。"""
    _init()
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": method, "arguments": params or {}},
        "id": str(uuid.uuid4()),
    }
    headers = {"Content-Type": "application/json"}
    if _session_id:
        headers["Mcp-Session-Id"] = _session_id
    try:
        resp = requests.post(MCP_URL, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return {"error": data["error"]}
        return data.get("result", data)
    except requests.ConnectionError:
        return {"error": f"MCP连接断开 ({MCP_URL})"}
    except Exception as e:
        return {"error": str(e)}


def _validate(title: str, content: str) -> tuple[str, str]:
    """校验标题/正文长度。"""
    if len(title) > MAX_TITLE_LEN:
        print(f"⚠️ 标题截断 ({len(title)}→{MAX_TITLE_LEN}): {title[:MAX_TITLE_LEN]}", file=sys.stderr)
        title = title[:MAX_TITLE_LEN]
    if len(content) > MAX_CONTENT_LEN:
        print(f"⚠️ 正文截断 ({len(content)}→{MAX_CONTENT_LEN})", file=sys.stderr)
        content = content[:MAX_CONTENT_LEN - 3] + "..."
    return title, content


def _out(data):
    """输出 JSON。"""
    print(json.dumps(data, indent=2, ensure_ascii=False))


# ─── 账号 ──────────────────────────────────────────────────

def cmd_status(_args):
    _out(call("check_login_status"))

def cmd_qrcode(_args):
    _out(call("get_login_qrcode"))

def cmd_logout(_args):
    _out(call("delete_cookies"))


# ─── 发布 ──────────────────────────────────────────────────

def cmd_publish(args):
    title, content = _validate(args.title, args.content)
    params = {"title": title, "content": content, "images": args.images or []}
    if args.tags:
        params["tags"] = args.tags
    if args.schedule:
        params["schedule_at"] = args.schedule
    _out(call("publish_content", params))

def cmd_publish_video(args):
    title, content = _validate(args.title, args.content)
    params = {"title": title, "content": content, "video": args.video}
    if args.tags:
        params["tags"] = args.tags
    if args.schedule:
        params["schedule_at"] = args.schedule
    _out(call("publish_with_video", params))

def cmd_publish_draft(args):
    """从 content.json 草稿发布。"""
    with open(args.draft, "r", encoding="utf-8") as f:
        data = json.load(f)

    title = data.get("post_title", "")
    content = data.get("post_body", "")
    tags = data.get("tags", [])
    images = data.get("card_paths", [])

    # 如果 card_paths 里是相对路径，基于 draft 目录解析
    draft_dir = os.path.dirname(os.path.abspath(args.draft))
    resolved = []
    for img in images:
        if not os.path.isabs(img):
            img = os.path.join(draft_dir, img)
        resolved.append(img)

    title, content = _validate(title, content)
    params = {"title": title, "content": content, "images": resolved}
    if tags:
        params["tags"] = tags
    if args.schedule:
        params["schedule_at"] = args.schedule

    print(f"📤 发布草稿: {title}", file=sys.stderr)
    print(f"   正文 {len(content)}字 | 图片 {len(resolved)}张 | 标签 {tags}", file=sys.stderr)
    _out(call("publish_content", params))


# ─── 搜索/浏览 ────────────────────────────────────────────

def cmd_search(args):
    params = {"keyword": args.keyword}
    if any([args.sort, args.time, args.note_type]):
        filters = {}
        if args.sort:
            filters["sort_by"] = args.sort
        if args.time:
            filters["publish_time"] = args.time
        if args.note_type:
            filters["note_type"] = args.note_type
        params["filters"] = filters
    _out(call("search_feeds", params))

def cmd_feeds(_args):
    _out(call("list_feeds"))

def cmd_detail(args):
    params = {"feed_id": args.feed_id, "xsec_token": args.xsec_token}
    if args.all_comments:
        params["load_all_comments"] = True
        if args.limit:
            params["limit"] = args.limit
        if args.with_replies:
            params["click_more_replies"] = True
    _out(call("get_feed_detail", params))

def cmd_profile(args):
    _out(call("user_profile", {"user_id": args.user_id, "xsec_token": args.xsec_token}))


# ─── 互动 ──────────────────────────────────────────────────

def cmd_like(args):
    params = {"feed_id": args.feed_id, "xsec_token": args.xsec_token}
    if args.undo:
        params["unlike"] = True
    _out(call("like_feed", params))

def cmd_favorite(args):
    params = {"feed_id": args.feed_id, "xsec_token": args.xsec_token}
    if args.undo:
        params["unfavorite"] = True
    _out(call("favorite_feed", params))

def cmd_comment(args):
    _out(call("post_comment_to_feed", {
        "feed_id": args.feed_id,
        "xsec_token": args.xsec_token,
        "content": args.content,
    }))

def cmd_reply(args):
    params = {
        "feed_id": args.feed_id,
        "xsec_token": args.xsec_token,
        "content": args.content,
    }
    if args.comment_id:
        params["comment_id"] = args.comment_id
    if args.user_id:
        params["user_id"] = args.user_id
    _out(call("reply_comment_in_feed", params))


# ─── CLI ───────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="小红书操作 CLI — 发布/搜索/互动/数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command")

    # ── 账号 ──
    sub.add_parser("status", help="检查登录状态")
    sub.add_parser("qrcode", help="获取登录二维码")
    sub.add_parser("logout", help="清除cookies重新登录")

    # ── 发布 ──
    pp = sub.add_parser("publish", help="发布图文")
    pp.add_argument("--title", required=True)
    pp.add_argument("--content", required=True)
    pp.add_argument("--images", nargs="+", default=[])
    pp.add_argument("--tags", nargs="+")
    pp.add_argument("--schedule", help="定时发布 ISO8601 (如 2026-02-26T10:00:00+08:00)")

    pp = sub.add_parser("publish-video", help="发布视频")
    pp.add_argument("--title", required=True)
    pp.add_argument("--content", required=True)
    pp.add_argument("--video", required=True)
    pp.add_argument("--tags", nargs="+")
    pp.add_argument("--schedule")

    pp = sub.add_parser("publish-draft", help="从content.json草稿发布")
    pp.add_argument("--draft", required=True, help="content.json路径")
    pp.add_argument("--schedule")

    # ── 搜索/浏览 ──
    pp = sub.add_parser("search", help="搜索")
    pp.add_argument("keyword")
    pp.add_argument("--sort", choices=["综合", "最新", "最多点赞", "最多评论", "最多收藏"])
    pp.add_argument("--time", choices=["不限", "一天内", "一周内", "半年内"])
    pp.add_argument("--note-type", choices=["不限", "视频", "图文"])

    sub.add_parser("feeds", help="推荐流")

    pp = sub.add_parser("detail", help="帖子详情+评论")
    pp.add_argument("feed_id")
    pp.add_argument("xsec_token")
    pp.add_argument("--all-comments", action="store_true", help="加载全部评论")
    pp.add_argument("--limit", type=int, help="评论数量上限")
    pp.add_argument("--with-replies", action="store_true", help="展开二级回复")

    pp = sub.add_parser("profile", help="用户主页")
    pp.add_argument("user_id")
    pp.add_argument("xsec_token")

    # ── 互动 ──
    pp = sub.add_parser("like", help="点赞")
    pp.add_argument("feed_id")
    pp.add_argument("xsec_token")
    pp.add_argument("--undo", action="store_true", help="取消点赞")

    pp = sub.add_parser("favorite", help="收藏")
    pp.add_argument("feed_id")
    pp.add_argument("xsec_token")
    pp.add_argument("--undo", action="store_true", help="取消收藏")

    pp = sub.add_parser("comment", help="评论帖子")
    pp.add_argument("feed_id")
    pp.add_argument("xsec_token")
    pp.add_argument("content")

    pp = sub.add_parser("reply", help="回复评论")
    pp.add_argument("feed_id")
    pp.add_argument("xsec_token")
    pp.add_argument("content")
    pp.add_argument("--comment-id", help="目标评论ID")
    pp.add_argument("--user-id", help="目标评论用户ID")

    args = p.parse_args()
    if not args.command:
        p.print_help()
        sys.exit(1)

    cmds = {
        "status": cmd_status, "qrcode": cmd_qrcode, "logout": cmd_logout,
        "publish": cmd_publish, "publish-video": cmd_publish_video,
        "publish-draft": cmd_publish_draft,
        "search": cmd_search, "feeds": cmd_feeds,
        "detail": cmd_detail, "profile": cmd_profile,
        "like": cmd_like, "favorite": cmd_favorite,
        "comment": cmd_comment, "reply": cmd_reply,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
