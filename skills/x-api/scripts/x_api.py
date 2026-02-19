#!/usr/bin/env python3
"""X API v2 CLI — search posts, fetch content/stats, publish, reply, like, repost, follow, and more."""

import argparse
import json
import os
import sys

BASE_URL = "https://api.x.com/2"

TWEET_FIELDS = "author_id,created_at,public_metrics,entities,conversation_id,referenced_tweets,lang,text"
USER_FIELDS = "id,name,username,description,public_metrics,profile_image_url,verified,created_at"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def get_oauth1_session():
    """Return a requests session authenticated with OAuth 1.0a."""
    api_key = os.environ.get("X_API_KEY")
    api_secret = os.environ.get("X_API_SECRET")
    access_token = os.environ.get("X_ACCESS_TOKEN")
    access_token_secret = os.environ.get("X_ACCESS_TOKEN_SECRET")

    missing = []
    if not api_key:
        missing.append("X_API_KEY")
    if not api_secret:
        missing.append("X_API_SECRET")
    if not access_token:
        missing.append("X_ACCESS_TOKEN")
    if not access_token_secret:
        missing.append("X_ACCESS_TOKEN_SECRET")
    if missing:
        print(f"Error: missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    try:
        from requests_oauthlib import OAuth1Session
    except ImportError:
        print(
            "Error: requests-oauthlib not installed. Run:\n"
            "  skills/x-api/.venv/bin/pip install requests requests-oauthlib",
            file=sys.stderr,
        )
        sys.exit(1)

    return OAuth1Session(
        api_key,
        client_secret=api_secret,
        resource_owner_key=access_token,
        resource_owner_secret=access_token_secret,
    )


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def api_get(session, path, params=None):
    """GET request to the X API v2."""
    url = f"{BASE_URL}{path}"
    resp = session.get(url, params=params)
    return _handle_response(resp)


def api_post(session, path, payload=None):
    """POST request to the X API v2 (JSON body)."""
    url = f"{BASE_URL}{path}"
    resp = session.post(url, json=payload)
    return _handle_response(resp)


def api_delete(session, path):
    """DELETE request to the X API v2."""
    url = f"{BASE_URL}{path}"
    resp = session.delete(url)
    return _handle_response(resp)


def _handle_response(resp):
    """Parse response, exit on errors."""
    try:
        data = resp.json()
    except Exception:
        print(f"Error: HTTP {resp.status_code} — {resp.text}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code not in (200, 201):
        _print_api_errors(data, resp.status_code)
        sys.exit(1)

    return data


def _print_api_errors(data, status_code):
    """Print API error details to stderr."""
    if "errors" in data:
        for err in data["errors"]:
            msg = err.get("message") or err.get("detail") or err.get("title", "Unknown error")
            print(f"Error [{status_code}]: {msg}", file=sys.stderr)
    elif "detail" in data:
        print(f"Error [{status_code}]: {data['detail']}", file=sys.stderr)
    elif "title" in data:
        print(f"Error [{status_code}]: {data['title']}", file=sys.stderr)
    else:
        print(f"Error [{status_code}]: {json.dumps(data)}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Cached authenticated user ID
# ---------------------------------------------------------------------------

_cached_me_id = None


def get_my_user_id(session):
    """Fetch and cache the authenticated user's numeric ID."""
    global _cached_me_id
    if _cached_me_id is not None:
        return _cached_me_id
    data = api_get(session, "/users/me")
    _cached_me_id = data["data"]["id"]
    return _cached_me_id


def resolve_username_to_id(session, username):
    """Resolve a @username (without the @) to a numeric user ID."""
    username = username.lstrip("@")
    data = api_get(session, f"/users/by/username/{username}", params={"user.fields": USER_FIELDS})
    return data["data"]["id"]


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def output(data, human=False, formatter=None):
    """Print data as JSON or human-readable."""
    if human and formatter:
        formatter(data)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def format_tweet(tweet):
    """Human-readable single tweet."""
    pm = tweet.get("public_metrics", {})
    author = tweet.get("author_id", "?")
    print(f"@{tweet.get('username', author)} — {tweet.get('created_at', '')}")
    print(tweet.get("text", ""))
    print(
        f"  Likes: {pm.get('like_count', 0)}  "
        f"Reposts: {pm.get('retweet_count', 0)}  "
        f"Replies: {pm.get('reply_count', 0)}  "
        f"Views: {pm.get('impression_count', 0)}  "
        f"Bookmarks: {pm.get('bookmark_count', 0)}"
    )
    print(f"  ID: {tweet.get('id', '?')}")
    print()


def format_tweets(data):
    """Human-readable tweet list."""
    tweets = data.get("data", [])
    if not tweets:
        print("No posts found.")
        return
    # Build author map from includes
    users = {}
    for u in data.get("includes", {}).get("users", []):
        users[u["id"]] = u.get("username", u["id"])
    for t in tweets:
        t["username"] = users.get(t.get("author_id", ""), t.get("author_id", "?"))
        format_tweet(t)
    meta = data.get("meta", {})
    if "result_count" in meta:
        print(f"--- {meta['result_count']} result(s) ---")


def format_user(data):
    """Human-readable user profile."""
    u = data.get("data", data)
    pm = u.get("public_metrics", {})
    print(f"@{u.get('username', '?')} — {u.get('name', '')}")
    if u.get("description"):
        print(f"  {u['description']}")
    print(
        f"  Followers: {pm.get('followers_count', 0)}  "
        f"Following: {pm.get('following_count', 0)}  "
        f"Posts: {pm.get('tweet_count', 0)}"
    )
    print(f"  Verified: {u.get('verified', False)}  Created: {u.get('created_at', '?')}")
    print(f"  ID: {u.get('id', '?')}")
    print()


def format_trends(data):
    """Human-readable trends list."""
    trends = data.get("data", [])
    if not trends:
        print("No trends found.")
        return
    for i, t in enumerate(trends, 1):
        count = t.get("tweet_count")
        count_str = f" ({count:,} posts)" if count else ""
        print(f"  {i}. {t.get('trend_name', '?')}{count_str}")
    print()


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_me(args):
    session = get_oauth1_session()
    data = api_get(session, "/users/me", params={"user.fields": USER_FIELDS})
    output(data, args.human, format_user)


def cmd_search(args):
    session = get_oauth1_session()
    params = {
        "query": args.query,
        "max_results": args.max_results,
        "tweet.fields": TWEET_FIELDS,
        "expansions": "author_id",
        "user.fields": "id,username",
    }
    if args.sort_order:
        params["sort_order"] = args.sort_order
    data = api_get(session, "/tweets/search/recent", params=params)
    output(data, args.human, format_tweets)


def cmd_trending(args):
    session = get_oauth1_session()
    params = {"trend.fields": "trend_name,tweet_count"}
    if args.max_trends:
        params["max_trends"] = args.max_trends
    data = api_get(session, f"/trends/by/woeid/{args.woeid}", params=params)
    output(data, args.human, format_trends)


def cmd_get_post(args):
    session = get_oauth1_session()
    params = {
        "tweet.fields": TWEET_FIELDS,
        "expansions": "author_id",
        "user.fields": "id,username",
    }
    data = api_get(session, f"/tweets/{args.tweet_id}", params=params)
    if args.human:
        tweet = data.get("data", {})
        users = {}
        for u in data.get("includes", {}).get("users", []):
            users[u["id"]] = u.get("username", u["id"])
        tweet["username"] = users.get(tweet.get("author_id", ""), tweet.get("author_id", "?"))
        format_tweet(tweet)
    else:
        output(data)


def cmd_get_user(args):
    session = get_oauth1_session()
    username = args.username.lstrip("@")
    data = api_get(session, f"/users/by/username/{username}", params={"user.fields": USER_FIELDS})
    output(data, args.human, format_user)


def cmd_user_posts(args):
    session = get_oauth1_session()
    user_id = resolve_username_to_id(session, args.username)
    params = {
        "max_results": args.max_results,
        "tweet.fields": TWEET_FIELDS,
        "expansions": "author_id",
        "user.fields": "id,username",
    }
    if args.exclude:
        params["exclude"] = ",".join(args.exclude)
    data = api_get(session, f"/users/{user_id}/tweets", params=params)
    output(data, args.human, format_tweets)


def cmd_post(args):
    session = get_oauth1_session()
    payload = {"text": args.text}
    data = api_post(session, "/tweets", payload)
    if args.human:
        d = data.get("data", {})
        print(f"Posted! ID: {d.get('id', '?')}")
        print(f"Text: {d.get('text', '')}")
    else:
        output(data)


def cmd_reply(args):
    session = get_oauth1_session()
    payload = {
        "text": args.text,
        "reply": {"in_reply_to_tweet_id": args.tweet_id},
    }
    data = api_post(session, "/tweets", payload)
    if args.human:
        d = data.get("data", {})
        print(f"Replied! ID: {d.get('id', '?')}")
        print(f"Text: {d.get('text', '')}")
    else:
        output(data)


def cmd_like(args):
    session = get_oauth1_session()
    my_id = get_my_user_id(session)
    payload = {"tweet_id": args.tweet_id}
    data = api_post(session, f"/users/{my_id}/likes", payload)
    if args.human:
        liked = data.get("data", {}).get("liked", False)
        print(f"Liked: {liked}")
    else:
        output(data)


def cmd_repost(args):
    session = get_oauth1_session()
    my_id = get_my_user_id(session)
    payload = {"tweet_id": args.tweet_id}
    data = api_post(session, f"/users/{my_id}/retweets", payload)
    if args.human:
        retweeted = data.get("data", {}).get("retweeted", False)
        print(f"Reposted: {retweeted}")
    else:
        output(data)


def cmd_follow(args):
    session = get_oauth1_session()
    my_id = get_my_user_id(session)
    target_id = resolve_username_to_id(session, args.username)
    payload = {"target_user_id": target_id}
    data = api_post(session, f"/users/{my_id}/following", payload)
    if args.human:
        following = data.get("data", {}).get("following", False)
        pending = data.get("data", {}).get("pending_follow", False)
        if pending:
            print(f"Follow request sent to @{args.username.lstrip('@')} (pending approval)")
        else:
            print(f"Following @{args.username.lstrip('@')}: {following}")
    else:
        output(data)


def cmd_following(args):
    """Get list of accounts a user is following."""
    session = get_oauth1_session()
    user_id = resolve_username_to_id(session, args.username)
    params = {
        "max_results": args.max_results,
        "user.fields": USER_FIELDS,
    }
    all_users = []
    pagination_token = None
    
    while True:
        if pagination_token:
            params["pagination_token"] = pagination_token
        data = api_get(session, f"/users/{user_id}/following", params=params)
        users = data.get("data", [])
        all_users.extend(users)
        
        # Check for more pages
        meta = data.get("meta", {})
        pagination_token = meta.get("next_token")
        
        # Stop if no more pages or reached limit
        if not pagination_token or len(all_users) >= args.max_results:
            break
    
    # Trim to max_results
    all_users = all_users[:args.max_results]
    
    result = {"data": all_users, "meta": {"result_count": len(all_users)}}
    
    if args.human:
        format_following(result, args.min_followers)
    else:
        # Filter by min_followers if specified
        if args.min_followers:
            filtered = [u for u in all_users 
                       if u.get("public_metrics", {}).get("followers_count", 0) >= args.min_followers]
            result = {"data": filtered, "meta": {"result_count": len(filtered)}}
        output(result)


def format_following(data, min_followers=None):
    """Human-readable following list."""
    users = data.get("data", [])
    if not users:
        print("No following found.")
        return
    
    # Sort by followers count
    users_sorted = sorted(users, 
                         key=lambda u: u.get("public_metrics", {}).get("followers_count", 0), 
                         reverse=True)
    
    # Filter by min_followers if specified
    if min_followers:
        users_sorted = [u for u in users_sorted 
                       if u.get("public_metrics", {}).get("followers_count", 0) >= min_followers]
    
    print(f"Following ({len(users_sorted)} accounts):\n")
    for u in users_sorted:
        pm = u.get("public_metrics", {})
        followers = pm.get("followers_count", 0)
        print(f"  @{u.get('username', '?'):20} | {followers:>10,} followers | {u.get('name', '')}")
    print()


def cmd_thread(args):
    """Fetch a full thread/conversation by searching for conversation_id."""
    session = get_oauth1_session()

    # First get the tweet to find its conversation_id and author
    tweet_data = api_get(session, f"/tweets/{args.tweet_id}", params={
        "tweet.fields": TWEET_FIELDS,
        "expansions": "author_id",
        "user.fields": "id,username",
    })
    tweet = tweet_data.get("data", {})
    conv_id = tweet.get("conversation_id", args.tweet_id)
    author_id = tweet.get("author_id", "")

    # Resolve author username from includes
    author_username = author_id
    for u in tweet_data.get("includes", {}).get("users", []):
        if u["id"] == author_id:
            author_username = u.get("username", author_id)
            break

    # Search for all tweets in this conversation from the same author
    query = f"conversation_id:{conv_id} from:{author_username} -is:retweet"
    params = {
        "query": query,
        "max_results": args.max_results,
        "tweet.fields": TWEET_FIELDS,
        "expansions": "author_id",
        "user.fields": "id,username",
        "sort_order": "recency",
    }
    search_data = api_get(session, "/tweets/search/recent", params=params)
    thread_tweets = search_data.get("data", [])

    # Include the original conversation starter if not in results
    existing_ids = {t["id"] for t in thread_tweets}
    if conv_id not in existing_ids:
        # Fetch the conversation starter
        starter_data = api_get(session, f"/tweets/{conv_id}", params={
            "tweet.fields": TWEET_FIELDS,
            "expansions": "author_id",
            "user.fields": "id,username",
        })
        starter = starter_data.get("data")
        if starter:
            thread_tweets.append(starter)

    # Sort by ID (chronological)
    thread_tweets.sort(key=lambda t: int(t.get("id", "0")))

    result = {
        "data": thread_tweets,
        "meta": {
            "conversation_id": conv_id,
            "author": author_username,
            "thread_length": len(thread_tweets),
        },
        "includes": search_data.get("includes", tweet_data.get("includes", {})),
    }

    if args.human:
        print(f"🧵 Thread by @{author_username} ({len(thread_tweets)} tweets)")
        print(f"   conversation_id: {conv_id}\n")
        users = {}
        for u in result.get("includes", {}).get("users", []):
            users[u["id"]] = u.get("username", u["id"])
        for i, t in enumerate(thread_tweets, 1):
            t["username"] = users.get(t.get("author_id", ""), author_username)
            print(f"  [{i}/{len(thread_tweets)}]")
            format_tweet(t)
    else:
        output(result)


def cmd_delete(args):
    session = get_oauth1_session()
    data = api_delete(session, f"/tweets/{args.tweet_id}")
    if args.human:
        deleted = data.get("data", {}).get("deleted", False)
        print(f"Deleted: {deleted}")
    else:
        output(data)


# ---------------------------------------------------------------------------
# CLI setup
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="X API v2 CLI — interact with your X (Twitter) account",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--human", action="store_true", help="Human-readable output instead of JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # me
    sub = subparsers.add_parser("me", help="Get authenticated user profile")
    sub.set_defaults(func=cmd_me)

    # search
    sub = subparsers.add_parser("search", help="Search recent posts")
    sub.add_argument("query", help="Search query (supports X search operators)")
    sub.add_argument("--max-results", type=int, default=10, help="Max results (10-100, default: 10)")
    sub.add_argument("--sort-order", choices=["recency", "relevancy"], help="Sort order")
    sub.set_defaults(func=cmd_search)

    # trending
    sub = subparsers.add_parser("trending", help="Get trending topics by WOEID")
    sub.add_argument("woeid", type=int, help="WOEID (1=Worldwide, 23424977=US, 23424856=Japan, 23424975=UK)")
    sub.add_argument("--max-trends", type=int, default=20, help="Max trends (1-50, default: 20)")
    sub.set_defaults(func=cmd_trending)

    # get-post
    sub = subparsers.add_parser("get-post", help="Fetch a post by ID with metrics")
    sub.add_argument("tweet_id", help="Post/tweet ID")
    sub.set_defaults(func=cmd_get_post)

    # get-user
    sub = subparsers.add_parser("get-user", help="Look up a user by username")
    sub.add_argument("username", help="Username (with or without @)")
    sub.set_defaults(func=cmd_get_user)

    # user-posts
    sub = subparsers.add_parser("user-posts", help="Get a user's recent posts")
    sub.add_argument("username", help="Username (with or without @)")
    sub.add_argument("--max-results", type=int, default=10, help="Max results (5-100, default: 10)")
    sub.add_argument("--exclude", nargs="+", choices=["replies", "retweets"], help="Exclude post types")
    sub.set_defaults(func=cmd_user_posts)

    # post
    sub = subparsers.add_parser("post", help="Publish a new post")
    sub.add_argument("text", help="Post text")
    sub.set_defaults(func=cmd_post)

    # reply
    sub = subparsers.add_parser("reply", help="Reply to a post")
    sub.add_argument("tweet_id", help="Post ID to reply to")
    sub.add_argument("text", help="Reply text")
    sub.set_defaults(func=cmd_reply)

    # like
    sub = subparsers.add_parser("like", help="Like a post")
    sub.add_argument("tweet_id", help="Post ID to like")
    sub.set_defaults(func=cmd_like)

    # repost
    sub = subparsers.add_parser("repost", help="Repost/retweet a post")
    sub.add_argument("tweet_id", help="Post ID to repost")
    sub.set_defaults(func=cmd_repost)

    # follow
    sub = subparsers.add_parser("follow", help="Follow a user")
    sub.add_argument("username", help="Username to follow (with or without @)")
    sub.set_defaults(func=cmd_follow)

    # following
    sub = subparsers.add_parser("following", help="Get list of accounts a user is following")
    sub.add_argument("username", help="Username (with or without @)")
    sub.add_argument("--max-results", type=int, default=100, help="Max results (default: 100)")
    sub.add_argument("--min-followers", type=int, help="Filter by minimum follower count")
    sub.set_defaults(func=cmd_following)

    # thread
    sub = subparsers.add_parser("thread", help="Fetch a full thread by any tweet ID in it")
    sub.add_argument("tweet_id", help="Any tweet ID in the thread")
    sub.add_argument("--max-results", type=int, default=100, help="Max tweets to fetch (default: 100)")
    sub.set_defaults(func=cmd_thread)

    # delete
    sub = subparsers.add_parser("delete", help="Delete a post")
    sub.add_argument("tweet_id", help="Post ID to delete")
    sub.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
