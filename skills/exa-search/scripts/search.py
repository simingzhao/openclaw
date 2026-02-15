#!/usr/bin/env python3
"""CLI helper for Exa Search API."""

import argparse
import html
import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request
from urllib.parse import urlparse


API_URL = "https://api.exa.ai/search"
USER_AGENT = "openclaw-exa-search/1.0 (+https://github.com/openclaw/openclaw)"
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "are",
    "was",
    "were",
    "has",
    "have",
    "had",
    "about",
    "into",
    "over",
    "under",
    "latest",
    "news",
}
BOILERPLATE_PHRASES = (
    "skip to content",
    "skip to main content",
    "watch live",
    "search submit",
    "subscribe",
    "newsletter",
    "privacy policy",
    "terms of use",
    "cookie",
    "all rights reserved",
    "home",
    "latest",
    "reviews",
    "videos",
    "features",
    "edition",
    "follow us",
    "search submit",
    "site search",
    "mega menu",
    "desktop logo",
    "mobile logo",
)
HUB_PATH_KEYWORDS = (
    "/category/",
    "/categories/",
    "/topic/",
    "/topics/",
    "/tag/",
    "/tags/",
    "/section/",
    "/sections/",
    "/search",
    "/news/",
)
NAV_WORDS = {
    "home",
    "topics",
    "latest",
    "reviews",
    "videos",
    "features",
    "subscribe",
    "newsletter",
    "menu",
    "search",
    "edition",
    "watch",
    "live",
    "privacy",
    "terms",
    "logo",
    "toggle",
    "submit",
    "desktop",
    "mobile",
    "topic",
    "topics",
}
ARTICLE_HINT_RE = re.compile(r"/(20\d{2})/(0[1-9]|1[0-2])/")
VERB_HINTS = {
    "is",
    "are",
    "was",
    "were",
    "has",
    "have",
    "had",
    "will",
    "said",
    "says",
    "show",
    "shows",
    "announced",
    "announces",
    "launched",
    "launches",
    "built",
    "builds",
    "using",
    "includes",
    "include",
    "can",
    "could",
    "may",
    "might",
}


def _read_query(cli_query: str | None) -> str:
    if cli_query:
        return cli_query.strip()

    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    return ""


def _compact(text: str, limit: int) -> str:
    squashed = " ".join(text.split())
    if limit <= 0 or len(squashed) <= limit:
        return squashed
    if limit <= 3:
        return squashed[:limit]
    return squashed[: limit - 3] + "..."


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", text.lower())


def _query_terms(query: str) -> set[str]:
    return {token for token in _tokenize(query) if len(token) >= 3 and token not in STOPWORDS}


def _clean_text(text: str) -> str:
    cleaned = html.unescape(text)
    cleaned = re.sub(r"!\[[^\]]*\]", " ", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\[[^\]]+\]", " ", cleaned)
    cleaned = cleaned.replace("[", " ").replace("]", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _split_candidates(text: str) -> list[str]:
    normalized = text.replace("###", ". ").replace("##", ". ").replace("#", ". ")
    chunks = re.split(r"(?:\s*[|*•]\s+|\.\s+|!\s+|\?\s+|;\s+)", normalized)
    return [chunk.strip(" -:\t\r\n") for chunk in chunks if chunk.strip()]


def _is_boilerplate(candidate: str) -> bool:
    lower = candidate.lower()
    if len(lower) < 40:
        return True
    hits = sum(1 for phrase in BOILERPLATE_PHRASES if phrase in lower)
    if hits >= 2:
        return True
    if len(_tokenize(lower)) <= 6:
        return True
    return False


def _noise_score(text: str) -> float:
    lower = text.lower()
    tokens = _tokenize(lower)
    if not tokens:
        return 1.0
    nav_hits = sum(1 for token in tokens if token in NAV_WORDS)
    bracket_hits = lower.count("[") + lower.count("]") + lower.count("#")
    return nav_hits / len(tokens) + min(bracket_hits, 8) * 0.04


def _is_usable_snippet(candidate: str) -> bool:
    lower = candidate.lower()
    words = _tokenize(lower)
    if len(candidate.strip()) < 40:
        return False
    if len(words) < 8:
        return False
    if _noise_score(candidate) > 0.34:
        return False
    if sum(1 for phrase in BOILERPLATE_PHRASES if phrase in lower) >= 2:
        return False
    if sum(1 for word in words if word in {"logo", "menu", "toggle", "submit", "topics"}) >= 2:
        return False
    if not any(word in VERB_HINTS for word in words):
        return False
    return True


def _score_candidate(candidate: str, q_terms: set[str]) -> float:
    words = _tokenize(candidate)
    if not words:
        return -1e9
    lower = candidate.lower()
    overlap = sum(1 for term in q_terms if term in lower)
    boilerplate_hits = sum(1 for phrase in BOILERPLATE_PHRASES if phrase in lower)
    return overlap * 6 + min(len(words), 40) * 0.3 - boilerplate_hits * 4


def _best_text_fragment(text: str, query: str, preview_chars: int) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""

    candidates = _split_candidates(cleaned)
    q_terms = _query_terms(query)

    scored: list[tuple[float, str]] = []
    for candidate in candidates:
        if _is_boilerplate(candidate):
            continue
        if not _is_usable_snippet(candidate):
            continue
        scored.append((_score_candidate(candidate, q_terms), candidate))

    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        return _compact(scored[0][1], preview_chars)

    for candidate in candidates:
        if len(candidate) >= 50 and _is_usable_snippet(candidate):
            return _compact(candidate, preview_chars)

    if _is_usable_snippet(cleaned):
        return _compact(cleaned, preview_chars)
    return ""


def _polish_snippet(snippet: str) -> str:
    cleaned = snippet.strip()
    cleaned = re.sub(
        r"^(?:[A-Za-z][A-Za-z0-9&'-]*\s+){0,8}Follow\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:")
    return cleaned


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search the web using Exa Search API")
    parser.add_argument(
        "query",
        nargs="?",
        help="Search query (or read from stdin if omitted)",
    )
    parser.add_argument(
        "--type",
        choices=["auto", "neural", "fast", "deep", "instant"],
        default="auto",
        help="Search mode (default: auto)",
    )
    parser.add_argument(
        "--num-results",
        type=int,
        default=10,
        help="Number of results to request (1-100, default: 10)",
    )
    parser.add_argument("--category", help="Optional Exa category filter")
    parser.add_argument(
        "--user-location",
        help="Optional user location as two-letter country code (e.g. US)",
    )
    parser.add_argument(
        "--include-domain",
        action="append",
        default=[],
        help="Restrict to this domain (repeatable)",
    )
    parser.add_argument(
        "--exclude-domain",
        action="append",
        default=[],
        help="Exclude this domain (repeatable)",
    )
    parser.add_argument(
        "--additional-query",
        action="append",
        default=[],
        help="Additional deep-search query variation (repeatable, requires --type deep)",
    )
    parser.add_argument(
        "--start-crawl-date",
        help="ISO-8601 lower bound for crawl date",
    )
    parser.add_argument(
        "--end-crawl-date",
        help="ISO-8601 upper bound for crawl date",
    )
    parser.add_argument(
        "--start-published-date",
        help="ISO-8601 lower bound for published date",
    )
    parser.add_argument(
        "--end-published-date",
        help="ISO-8601 upper bound for published date",
    )
    parser.add_argument(
        "--text",
        dest="text_enabled",
        action="store_true",
        default=True,
        help="Enable text extraction (default)",
    )
    parser.add_argument(
        "--no-text",
        dest="text_enabled",
        action="store_false",
        help="Disable text extraction",
    )
    parser.add_argument(
        "--max-text-chars",
        type=int,
        default=2500,
        help="Max extracted text characters per result when text is enabled (default: 2500)",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=360,
        help="Max snippet characters shown in human output (default: 360)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact digest of top results",
    )
    parser.add_argument(
        "--summary-items",
        type=int,
        default=5,
        help="Number of top results to include in summary mode (default: 5)",
    )
    parser.add_argument(
        "--summary-preview-chars",
        type=int,
        default=700,
        help="Max snippet characters per result in summary mode (default: 700)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30)",
    )
    parser.add_argument("--json", action="store_true", help="Output full JSON response")
    return parser.parse_args()


def _build_payload(args: argparse.Namespace, query: str) -> dict:
    payload: dict[str, object] = {
        "query": query,
        "type": args.type,
        "numResults": args.num_results,
    }

    if args.category:
        payload["category"] = args.category
    if args.user_location:
        payload["userLocation"] = args.user_location.upper()
    if args.include_domain:
        payload["includeDomains"] = args.include_domain
    if args.exclude_domain:
        payload["excludeDomains"] = args.exclude_domain
    if args.start_crawl_date:
        payload["startCrawlDate"] = args.start_crawl_date
    if args.end_crawl_date:
        payload["endCrawlDate"] = args.end_crawl_date
    if args.start_published_date:
        payload["startPublishedDate"] = args.start_published_date
    if args.end_published_date:
        payload["endPublishedDate"] = args.end_published_date

    if args.additional_query:
        if args.type != "deep":
            raise ValueError("--additional-query requires --type deep")
        payload["additionalQueries"] = args.additional_query

    if args.text_enabled:
        if args.max_text_chars <= 0:
            payload["contents"] = {"text": True}
        else:
            payload["contents"] = {"text": {"maxCharacters": args.max_text_chars}}

    return payload


def _call_exa(payload: dict, api_key: str, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": api_key,
            "Authorization": f"Bearer {api_key}",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset("utf-8")
            raw = response.read().decode(charset)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        detail = error_body
        try:
            parsed = json.loads(error_body)
            detail = json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
        if exc.code == 403 and ("Cloudflare" in error_body or "Access denied" in error_body):
            detail = (
                f"{detail}\n"
                "Hint: Cloudflare blocked the request before normal API auth. "
                "Confirm EXA_API_KEY is a real secret key from dashboard.exa.ai/api-keys "
                "(not a key ID), then test with curl from the same machine."
            )
        raise RuntimeError(f"Exa API error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error while reaching Exa API: {exc.reason}") from exc

    try:
        parsed_response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Exa API returned non-JSON response") from exc

    if not isinstance(parsed_response, dict):
        raise RuntimeError("Unexpected Exa API response shape")

    return parsed_response


def _render_human(data: dict, preview_chars: int) -> None:
    request_id = data.get("requestId")
    if request_id:
        print(f"requestId: {request_id}")

    search_type = data.get("searchType")
    if search_type:
        print(f"searchType: {search_type}")

    results = data.get("results")
    if not isinstance(results, list):
        print("No results field in response.")
        return

    print(f"results: {len(results)}")
    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue

        title = item.get("title") or "(untitled)"
        url = item.get("url") or "(no url)"
        print(f"\n[{index}] {title}")
        print(f"URL: {url}")

        published_date = item.get("publishedDate")
        if published_date:
            print(f"Published: {published_date}")

        author = item.get("author")
        if author:
            print(f"Author: {author}")

        score = item.get("score")
        if score is not None:
            print(f"Score: {score}")

        text = item.get("text")
        if isinstance(text, str) and text.strip():
            snippet = _compact(text, preview_chars)
            print("Snippet:")
            print(textwrap.fill(snippet, width=100, initial_indent="  ", subsequent_indent="  "))

        highlights = item.get("highlights")
        if isinstance(highlights, list) and highlights:
            highlight = highlights[0]
            if isinstance(highlight, str) and highlight.strip():
                clipped = _compact(highlight, preview_chars)
                print("Highlight:")
                print(textwrap.fill(clipped, width=100, initial_indent="  ", subsequent_indent="  "))


def _extract_best_snippet(item: dict, query: str, preview_chars: int) -> str:
    highlights = item.get("highlights")
    if isinstance(highlights, list):
        for highlight in highlights:
            if isinstance(highlight, str) and highlight.strip():
                snippet = _best_text_fragment(highlight, query=query, preview_chars=preview_chars)
                if snippet:
                    polished = _polish_snippet(snippet)
                    if _is_usable_snippet(polished):
                        return polished

    text = item.get("text")
    if isinstance(text, str) and text.strip():
        snippet = _best_text_fragment(text, query=query, preview_chars=preview_chars)
        if snippet:
            polished = _polish_snippet(snippet)
            if _is_usable_snippet(polished):
                return polished

    return ""


def _extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
    except ValueError:
        return ""
    if netloc.startswith("www."):
        return netloc[4:]
    return netloc


def _is_hub_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return True
    path = parsed.path.lower().rstrip("/")
    if not path or path == "":
        return True
    if any(keyword in path for keyword in HUB_PATH_KEYWORDS):
        return True
    if path.endswith("/news") or path.endswith("/ai"):
        return True
    return False


def _result_quality_score(item: dict, index: int, q_terms: set[str]) -> float:
    score = 100 - index * 2.5
    url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    published_date = item.get("publishedDate")
    content_score = item.get("score")
    if isinstance(content_score, (int, float)):
        score += float(content_score) * 10
    if published_date:
        score += 8
    if url and ARTICLE_HINT_RE.search(url):
        score += 10
    if _is_hub_url(url):
        score -= 16
    merged = f"{title} {url}".lower()
    score += sum(1 for term in q_terms if term in merged) * 1.5
    if "reddit.com" in url:
        score -= 6
    return score


def _render_summary(
    data: dict,
    query: str,
    summary_items: int,
    preview_chars: int,
    summary_preview_chars: int,
) -> None:
    results = data.get("results")
    if not isinstance(results, list) or not results:
        print("No results.")
        return

    takeaways: list[str] = []
    typed_results = [item for item in results if isinstance(item, dict)]
    q_terms = _query_terms(query)
    indexed_results = list(enumerate(typed_results))
    ranked = sorted(
        indexed_results,
        key=lambda pair: _result_quality_score(pair[1], pair[0], q_terms),
        reverse=True,
    )
    ranked_items = [item for _, item in ranked]
    preferred: list[dict] = []
    fallback: list[dict] = []
    for item in ranked_items:
        url = str(item.get("url") or "")
        if _is_hub_url(url) and not item.get("publishedDate"):
            fallback.append(item)
        else:
            preferred.append(item)

    top_results = (preferred + fallback)[:summary_items]
    if not top_results:
        print("No results.")
        return

    for item in top_results[:3]:
        title = str(item.get("title") or "(untitled)")
        snippet = _extract_best_snippet(item, query=query, preview_chars=max(120, summary_preview_chars // 3))
        if snippet:
            takeaways.append(f"- {title}: {snippet}")
        else:
            takeaways.append(f"- {title}")

    print("Key takeaways:")
    for takeaway in takeaways:
        print(takeaway)

    print("\nTop results:")
    for index, item in enumerate(top_results, start=1):
        title = str(item.get("title") or "(untitled)")
        url = str(item.get("url") or "(no url)")
        domain = _extract_domain(url)
        snippet = _extract_best_snippet(item, query=query, preview_chars=summary_preview_chars)

        heading = f"{index}. {title}"
        if domain:
            heading += f" ({domain})"
        print(heading)
        print(f"   {url}")
        published_date = item.get("publishedDate")
        if published_date:
            print(f"   Published: {published_date}")
        if snippet:
            print(
                textwrap.fill(
                    _compact(snippet, summary_preview_chars),
                    width=100,
                    initial_indent="   ",
                    subsequent_indent="   ",
                )
            )
        else:
            print("   (no clean snippet extracted)")


def main() -> int:
    args = _parse_args()

    if args.num_results < 1 or args.num_results > 100:
        print("Error: --num-results must be between 1 and 100", file=sys.stderr)
        return 2
    if args.summary_items < 1:
        print("Error: --summary-items must be >= 1", file=sys.stderr)
        return 2
    if args.summary_preview_chars < 80:
        print("Error: --summary-preview-chars must be >= 80", file=sys.stderr)
        return 2

    query = _read_query(args.query)
    if not query:
        print("Error: no query provided", file=sys.stderr)
        return 2

    api_key = (os.environ.get("EXA_API_KEY") or "").strip()
    if not api_key:
        print("Error: EXA_API_KEY not set", file=sys.stderr)
        return 2

    try:
        payload = _build_payload(args, query)
        response = _call_exa(payload, api_key=api_key, timeout=args.timeout)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(response, indent=2, ensure_ascii=False))
    elif args.summary:
        _render_summary(
            response,
            query=query,
            summary_items=args.summary_items,
            preview_chars=args.preview_chars,
            summary_preview_chars=args.summary_preview_chars,
        )
    else:
        _render_human(response, preview_chars=args.preview_chars)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
