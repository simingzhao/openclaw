#!/usr/bin/env python3
"""exa_search.py — Exa API search + content extraction (zero SDK dependencies)."""

import argparse
import json
import os
import sys
import textwrap
import urllib.request

API_URL = "https://api.exa.ai/search"


def main():
    p = argparse.ArgumentParser(description="Search via Exa API")
    p.add_argument("query", help="Search query")
    p.add_argument("-n", "--num", type=int, default=10, help="Number of results (default: 10)")
    p.add_argument("--type", dest="search_type", default="auto",
                   choices=["auto", "neural", "fast", "deep", "instant"],
                   help="Search type (default: auto)")
    p.add_argument("--category", default=None,
                   help="Category: news, research paper, tweet, company, people, etc.")
    p.add_argument("--text", action="store_true", help="Return full page text")
    p.add_argument("--text-max", type=int, default=4000, help="Max chars for text (default: 4000)")
    p.add_argument("--highlights", action="store_true", help="Return highlights (default content)")
    p.add_argument("--highlights-max", type=int, default=4000, help="Max chars per highlight")
    p.add_argument("--summary", default=None, metavar="QUERY",
                   help="Return AI summary focused on this query")
    p.add_argument("--after", default=None, help="Published after (YYYY-MM-DD)")
    p.add_argument("--before", default=None, help="Published before (YYYY-MM-DD)")
    p.add_argument("--domain", action="append", default=[], help="Include domain (repeatable)")
    p.add_argument("--exclude", action="append", default=[], dest="exclude_domains",
                   help="Exclude domain (repeatable)")
    p.add_argument("--include-text", default=None, help="Page must contain this text")
    p.add_argument("--exclude-text", default=None, help="Page must not contain this text")
    p.add_argument("--answer", action="store_true", help="Synthesized answer (deep search)")
    p.add_argument("--json", action="store_true", dest="raw_json", help="Raw JSON output")

    args = p.parse_args()

    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        print("❌ EXA_API_KEY not set. Get one at https://dashboard.exa.ai/api-keys", file=sys.stderr)
        sys.exit(1)

    # Build request body
    body = {
        "query": args.query,
        "type": args.search_type,
        "numResults": args.num,
    }

    if args.category:
        body["category"] = args.category
    if args.answer:
        body["answer"] = True
    if args.after:
        body["startPublishedDate"] = f"{args.after}T00:00:00.000Z"
    if args.before:
        body["endPublishedDate"] = f"{args.before}T00:00:00.000Z"
    if args.domain:
        body["includeDomains"] = args.domain
    if args.exclude_domains:
        body["excludeDomains"] = args.exclude_domains
    if args.include_text:
        body["includeText"] = [args.include_text]
    if args.exclude_text:
        body["excludeText"] = [args.exclude_text]

    # Contents config
    if args.summary:
        body["contents"] = {"summary": {"query": args.summary}}
    elif args.text:
        body["contents"] = {"text": {"maxCharacters": args.text_max}}
    else:
        # Default: highlights
        body["contents"] = {"highlights": {"maxCharacters": args.highlights_max}}

    # Call API
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": api_key,
            "user-agent": "exa-search-skill/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"❌ Exa API error (HTTP {e.code}):", file=sys.stderr)
        print(err_body, file=sys.stderr)
        sys.exit(1)

    # Raw JSON output
    if args.raw_json:
        print(json.dumps(resp_data, indent=2, ensure_ascii=False))
        return

    # Pretty print
    print(f"\n🔍 Exa Search: \"{args.query}\"")
    print("━" * 50)

    answer = resp_data.get("answer")
    if answer:
        print(f"\n💡 Answer:\n{answer}\n")
        print("━" * 50)

    results = resp_data.get("results", [])
    if not results:
        print("\nNo results found.")
        return

    for i, r in enumerate(results, 1):
        title = r.get("title", "Untitled")
        url = r.get("url", "")
        date = (r.get("publishedDate") or "")[:10]

        print(f"\n{i}. {title}")
        print(f"   {url}")
        if date:
            print(f"   Published: {date}")

        # Highlights
        highlights = r.get("highlights", [])
        if highlights:
            for h in highlights[:3]:
                wrapped = textwrap.fill(h, width=78, initial_indent="   > ", subsequent_indent="   > ")
                print(wrapped)

        # Text (if no highlights)
        text = r.get("text", "")
        if text and not highlights:
            snippet = text[:500].replace("\n", " ").strip()
            if len(text) > 500:
                snippet += "..."
            wrapped = textwrap.fill(snippet, width=78, initial_indent="   > ", subsequent_indent="   > ")
            print(wrapped)

        # Summary
        summary = r.get("summary", "")
        if summary:
            wrapped = textwrap.fill(summary, width=78, initial_indent="   📝 ", subsequent_indent="      ")
            print(wrapped)

    print(f"\n━━━ {len(results)} results ━━━\n")


if __name__ == "__main__":
    main()
