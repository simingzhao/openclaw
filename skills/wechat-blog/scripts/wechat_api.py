#!/usr/bin/env python3
"""
微信公众号 API 封装脚本

环境变量:
    WECHAT_APPID: 公众号 AppID
    WECHAT_APPSECRET: 公众号 AppSecret

使用示例:
    python wechat_api.py token
    python wechat_api.py upload-cover cover.jpg
    python wechat_api.py draft-add --title "标题" --content "<p>内容</p>" --thumb-media-id xxx
    python wechat_api.py draft-list --human
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import requests

# Token 缓存文件路径
TOKEN_CACHE_FILE = Path.home() / ".wechat_token.json"

# API 端点
API_BASE = "https://api.weixin.qq.com/cgi-bin"
ENDPOINTS = {
    "token": f"{API_BASE}/token",
    "upload_material": f"{API_BASE}/material/add_material",
    "upload_image": f"{API_BASE}/media/uploadimg",
    "draft_add": f"{API_BASE}/draft/add",
    "draft_batchget": f"{API_BASE}/draft/batchget",
    "draft_get": f"{API_BASE}/draft/get",
    "draft_update": f"{API_BASE}/draft/update",
    "draft_delete": f"{API_BASE}/draft/delete",
    "publish_submit": f"{API_BASE}/freepublish/submit",
    "publish_get": f"{API_BASE}/freepublish/get",
    "publish_batchget": f"{API_BASE}/freepublish/batchget",
}


def get_credentials() -> tuple[str, str]:
    """从环境变量获取 AppID 和 AppSecret"""
    appid = os.environ.get("WECHAT_APPID")
    appsecret = os.environ.get("WECHAT_APPSECRET")
    
    if not appid or not appsecret:
        print("错误: 请设置环境变量 WECHAT_APPID 和 WECHAT_APPSECRET", file=sys.stderr)
        sys.exit(1)
    
    return appid, appsecret


def load_token_cache() -> Optional[dict]:
    """加载缓存的 token"""
    if not TOKEN_CACHE_FILE.exists():
        return None
    
    try:
        with open(TOKEN_CACHE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_token_cache(token: str, expires_at: float) -> None:
    """保存 token 到缓存"""
    cache = {
        "access_token": token,
        "expires_at": expires_at
    }
    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def get_access_token(force_refresh: bool = False) -> str:
    """
    获取 access_token（自动缓存，过期前10分钟刷新）
    
    Args:
        force_refresh: 强制刷新 token
    
    Returns:
        access_token 字符串
    """
    # 检查缓存
    if not force_refresh:
        cache = load_token_cache()
        if cache:
            # 过期前 10 分钟刷新
            if cache.get("expires_at", 0) > time.time() + 600:
                return cache["access_token"]
    
    # 请求新 token
    appid, appsecret = get_credentials()
    
    resp = requests.get(ENDPOINTS["token"], params={
        "grant_type": "client_credential",
        "appid": appid,
        "secret": appsecret
    })
    
    data = resp.json()
    
    if "errcode" in data and data["errcode"] != 0:
        print(f"错误: {data.get('errmsg', '未知错误')} (errcode: {data['errcode']})", file=sys.stderr)
        sys.exit(1)
    
    token = data["access_token"]
    expires_in = data.get("expires_in", 7200)
    expires_at = time.time() + expires_in
    
    # 保存缓存
    save_token_cache(token, expires_at)
    
    return token


def check_response(data: dict) -> dict:
    """检查 API 响应，如有错误则退出"""
    if "errcode" in data and data["errcode"] != 0:
        print(f"错误: {data.get('errmsg', '未知错误')} (errcode: {data['errcode']})", file=sys.stderr)
        sys.exit(1)
    return data


def output_result(data: Any, human: bool = False) -> None:
    """输出结果"""
    if human:
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    print(f"{key}:")
                    print(json.dumps(value, ensure_ascii=False, indent=2))
                else:
                    print(f"{key}: {value}")
        elif isinstance(data, list):
            for i, item in enumerate(data):
                print(f"[{i}] {json.dumps(item, ensure_ascii=False)}")
        else:
            print(data)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


# ============ Token 命令 ============

def cmd_token(args: argparse.Namespace) -> None:
    """获取并显示当前 access_token"""
    token = get_access_token()
    
    cache = load_token_cache()
    expires_at = cache.get("expires_at", 0) if cache else 0
    remaining = max(0, int(expires_at - time.time()))
    
    result = {
        "access_token": token,
        "expires_in": remaining,
        "expires_at": expires_at
    }
    
    if args.human:
        print(f"Access Token: {token[:20]}...{token[-10:]}")
        print(f"剩余有效期: {remaining // 60} 分钟 {remaining % 60} 秒")
    else:
        output_result(result)


# ============ 素材上传命令 ============

def cmd_upload_cover(args: argparse.Namespace) -> None:
    """上传永久素材（封面图）"""
    image_path = Path(args.image_path)
    
    if not image_path.exists():
        print(f"错误: 文件不存在: {image_path}", file=sys.stderr)
        sys.exit(1)
    
    token = get_access_token()
    
    with open(image_path, "rb") as f:
        files = {"media": (image_path.name, f, "image/jpeg")}
        resp = requests.post(
            ENDPOINTS["upload_material"],
            params={"access_token": token, "type": "image"},
            files=files
        )
    
    data = check_response(resp.json())
    
    if args.human:
        print(f"media_id: {data.get('media_id')}")
        print(f"url: {data.get('url')}")
    else:
        output_result(data)


def cmd_upload_image(args: argparse.Namespace) -> None:
    """上传图文消息图片"""
    image_path = Path(args.image_path)
    
    if not image_path.exists():
        print(f"错误: 文件不存在: {image_path}", file=sys.stderr)
        sys.exit(1)
    
    token = get_access_token()
    
    with open(image_path, "rb") as f:
        files = {"media": (image_path.name, f, "image/jpeg")}
        resp = requests.post(
            ENDPOINTS["upload_image"],
            params={"access_token": token},
            files=files
        )
    
    data = check_response(resp.json())
    
    if args.human:
        print(f"url: {data.get('url')}")
    else:
        output_result(data)


# ============ 草稿管理命令 ============

def cmd_draft_add(args: argparse.Namespace) -> None:
    """创建草稿"""
    token = get_access_token()
    
    if args.json_file:
        # 从 JSON 文件读取
        json_path = Path(args.json_file)
        if not json_path.exists():
            print(f"错误: 文件不存在: {json_path}", file=sys.stderr)
            sys.exit(1)
        
        with open(json_path, "r") as f:
            payload = json.load(f)
    else:
        # 从命令行参数构建
        if not args.title or not args.content or not args.thumb_media_id:
            print("错误: 需要提供 --title, --content 和 --thumb-media-id，或者提供 JSON 文件", file=sys.stderr)
            sys.exit(1)
        
        article = {
            "title": args.title,
            "content": args.content,
            "thumb_media_id": args.thumb_media_id,
        }
        
        if args.author:
            article["author"] = args.author
        if args.digest:
            article["digest"] = args.digest
        if args.content_source_url:
            article["content_source_url"] = args.content_source_url
        if args.need_open_comment is not None:
            article["need_open_comment"] = 1 if args.need_open_comment else 0
        if args.only_fans_can_comment is not None:
            article["only_fans_can_comment"] = 1 if args.only_fans_can_comment else 0
        
        payload = {"articles": [article]}
    
    resp = requests.post(
        ENDPOINTS["draft_add"],
        params={"access_token": token},
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={"Content-Type": "application/json; charset=utf-8"}
    )
    
    data = check_response(resp.json())
    
    if args.human:
        print(f"草稿创建成功！")
        print(f"media_id: {data.get('media_id')}")
    else:
        output_result(data)


def cmd_draft_list(args: argparse.Namespace) -> None:
    """列出所有草稿"""
    token = get_access_token()
    
    payload = {
        "offset": args.offset,
        "count": args.count,
        "no_content": 1 if args.no_content else 0
    }
    
    resp = requests.post(
        ENDPOINTS["draft_batchget"],
        params={"access_token": token},
        json=payload
    )
    
    data = check_response(resp.json())
    
    if args.human:
        print(f"共 {data.get('total_count', 0)} 篇草稿")
        print("-" * 50)
        for i, item in enumerate(data.get("item", [])):
            content = item.get("content", {})
            news = content.get("news_item", [{}])[0] if content.get("news_item") else {}
            print(f"[{i + 1}] {news.get('title', '无标题')}")
            print(f"    media_id: {item.get('media_id')}")
            print(f"    更新时间: {item.get('update_time')}")
            print()
    else:
        output_result(data)


def cmd_draft_get(args: argparse.Namespace) -> None:
    """获取草稿详情"""
    token = get_access_token()
    
    resp = requests.post(
        ENDPOINTS["draft_get"],
        params={"access_token": token},
        json={"media_id": args.media_id}
    )
    
    data = check_response(resp.json())
    
    if args.human:
        news_items = data.get("news_item", [])
        for i, article in enumerate(news_items):
            print(f"=== 文章 {i + 1} ===")
            print(f"标题: {article.get('title')}")
            print(f"作者: {article.get('author', '无')}")
            print(f"摘要: {article.get('digest', '无')}")
            print(f"封面 media_id: {article.get('thumb_media_id')}")
            print()
    else:
        output_result(data)


def cmd_draft_update(args: argparse.Namespace) -> None:
    """更新草稿"""
    token = get_access_token()
    
    articles = {}
    if args.title:
        articles["title"] = args.title
    if args.content:
        articles["content"] = args.content
    if args.thumb_media_id:
        articles["thumb_media_id"] = args.thumb_media_id
    if args.author:
        articles["author"] = args.author
    if args.digest:
        articles["digest"] = args.digest
    
    if not articles:
        print("错误: 至少需要提供一个更新字段", file=sys.stderr)
        sys.exit(1)
    
    payload = {
        "media_id": args.media_id,
        "index": args.index,
        "articles": articles
    }
    
    resp = requests.post(
        ENDPOINTS["draft_update"],
        params={"access_token": token},
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={"Content-Type": "application/json; charset=utf-8"}
    )
    
    data = check_response(resp.json())
    
    if args.human:
        print("草稿更新成功！")
    else:
        output_result(data)


def cmd_draft_delete(args: argparse.Namespace) -> None:
    """删除草稿"""
    token = get_access_token()
    
    resp = requests.post(
        ENDPOINTS["draft_delete"],
        params={"access_token": token},
        json={"media_id": args.media_id}
    )
    
    data = check_response(resp.json())
    
    if args.human:
        print("草稿删除成功！")
    else:
        output_result(data)


# ============ 发布管理命令 ============

def cmd_publish(args: argparse.Namespace) -> None:
    """发布草稿"""
    token = get_access_token()
    
    resp = requests.post(
        ENDPOINTS["publish_submit"],
        params={"access_token": token},
        json={"media_id": args.media_id}
    )
    
    data = check_response(resp.json())
    
    if args.human:
        print("发布任务已提交！")
        print(f"publish_id: {data.get('publish_id')}")
    else:
        output_result(data)


def cmd_publish_status(args: argparse.Namespace) -> None:
    """查询发布状态"""
    token = get_access_token()
    
    resp = requests.post(
        ENDPOINTS["publish_get"],
        params={"access_token": token},
        json={"publish_id": args.publish_id}
    )
    
    data = check_response(resp.json())
    
    if args.human:
        status_map = {0: "发布成功", 1: "发布中", 2: "发布失败", 3: "已删除"}
        status = data.get("publish_status", -1)
        print(f"发布状态: {status_map.get(status, '未知')}")
        if data.get("article_id"):
            print(f"article_id: {data.get('article_id')}")
        if data.get("article_detail"):
            print(f"文章详情: {json.dumps(data['article_detail'], ensure_ascii=False)}")
    else:
        output_result(data)


def cmd_article_list(args: argparse.Namespace) -> None:
    """获取已发布文章列表"""
    token = get_access_token()
    
    payload = {
        "offset": args.offset,
        "count": args.count,
        "no_content": 1 if args.no_content else 0
    }
    
    resp = requests.post(
        ENDPOINTS["publish_batchget"],
        params={"access_token": token},
        json=payload
    )
    
    data = check_response(resp.json())
    
    if args.human:
        print(f"共 {data.get('total_count', 0)} 篇已发布文章")
        print("-" * 50)
        for i, item in enumerate(data.get("item", [])):
            content = item.get("content", {})
            news = content.get("news_item", [{}])[0] if content.get("news_item") else {}
            print(f"[{i + 1}] {news.get('title', '无标题')}")
            print(f"    article_id: {item.get('article_id')}")
            print(f"    更新时间: {item.get('update_time')}")
            if news.get("url"):
                print(f"    链接: {news.get('url')}")
            print()
    else:
        output_result(data)


def main():
    parser = argparse.ArgumentParser(
        description="微信公众号 API 命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--human", "-H", action="store_true", help="人类可读格式输出")
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # token 命令
    parser_token = subparsers.add_parser("token", help="获取 access_token")
    parser_token.set_defaults(func=cmd_token)
    
    # upload-cover 命令
    parser_upload_cover = subparsers.add_parser("upload-cover", help="上传永久素材（封面图）")
    parser_upload_cover.add_argument("image_path", help="图片文件路径")
    parser_upload_cover.set_defaults(func=cmd_upload_cover)
    
    # upload-image 命令
    parser_upload_image = subparsers.add_parser("upload-image", help="上传图文消息图片")
    parser_upload_image.add_argument("image_path", help="图片文件路径")
    parser_upload_image.set_defaults(func=cmd_upload_image)
    
    # draft-add 命令
    parser_draft_add = subparsers.add_parser("draft-add", help="创建草稿")
    parser_draft_add.add_argument("json_file", nargs="?", help="包含草稿内容的 JSON 文件")
    parser_draft_add.add_argument("--title", help="文章标题")
    parser_draft_add.add_argument("--content", help="文章内容 (HTML)")
    parser_draft_add.add_argument("--thumb-media-id", help="封面图 media_id")
    parser_draft_add.add_argument("--author", help="作者")
    parser_draft_add.add_argument("--digest", help="摘要")
    parser_draft_add.add_argument("--content-source-url", help="原文链接")
    parser_draft_add.add_argument("--need-open-comment", type=int, choices=[0, 1], help="是否开启评论")
    parser_draft_add.add_argument("--only-fans-can-comment", type=int, choices=[0, 1], help="是否仅粉丝可评论")
    parser_draft_add.set_defaults(func=cmd_draft_add)
    
    # draft-list 命令
    parser_draft_list = subparsers.add_parser("draft-list", help="列出所有草稿")
    parser_draft_list.add_argument("--offset", type=int, default=0, help="起始位置")
    parser_draft_list.add_argument("--count", type=int, default=20, help="获取数量 (最大20)")
    parser_draft_list.add_argument("--no-content", action="store_true", help="不返回内容")
    parser_draft_list.set_defaults(func=cmd_draft_list)
    
    # draft-get 命令
    parser_draft_get = subparsers.add_parser("draft-get", help="获取草稿详情")
    parser_draft_get.add_argument("media_id", help="草稿 media_id")
    parser_draft_get.set_defaults(func=cmd_draft_get)
    
    # draft-update 命令
    parser_draft_update = subparsers.add_parser("draft-update", help="更新草稿")
    parser_draft_update.add_argument("media_id", help="草稿 media_id")
    parser_draft_update.add_argument("--index", type=int, default=0, help="文章索引 (默认0)")
    parser_draft_update.add_argument("--title", help="新标题")
    parser_draft_update.add_argument("--content", help="新内容 (HTML)")
    parser_draft_update.add_argument("--thumb-media-id", help="新封面图 media_id")
    parser_draft_update.add_argument("--author", help="新作者")
    parser_draft_update.add_argument("--digest", help="新摘要")
    parser_draft_update.set_defaults(func=cmd_draft_update)
    
    # draft-delete 命令
    parser_draft_delete = subparsers.add_parser("draft-delete", help="删除草稿")
    parser_draft_delete.add_argument("media_id", help="草稿 media_id")
    parser_draft_delete.set_defaults(func=cmd_draft_delete)
    
    # publish 命令
    parser_publish = subparsers.add_parser("publish", help="发布草稿")
    parser_publish.add_argument("media_id", help="草稿 media_id")
    parser_publish.set_defaults(func=cmd_publish)
    
    # publish-status 命令
    parser_publish_status = subparsers.add_parser("publish-status", help="查询发布状态")
    parser_publish_status.add_argument("publish_id", help="发布任务 ID")
    parser_publish_status.set_defaults(func=cmd_publish_status)
    
    # article-list 命令
    parser_article_list = subparsers.add_parser("article-list", help="获取已发布文章列表")
    parser_article_list.add_argument("--offset", type=int, default=0, help="起始位置")
    parser_article_list.add_argument("--count", type=int, default=20, help="获取数量 (最大20)")
    parser_article_list.add_argument("--no-content", action="store_true", help="不返回内容")
    parser_article_list.set_defaults(func=cmd_article_list)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
