#!/usr/bin/env python3
"""Gemini 3 Flash grounded search with Google Search and URL context."""

import argparse
import os
import sys

def main():
    parser = argparse.ArgumentParser(
        description="Search the web using Gemini 3 Flash grounded with Google Search"
    )
    parser.add_argument("query", nargs="?", help="Search query (or read from stdin if not provided)")
    parser.add_argument("--thinking", choices=["off", "low", "medium", "high"], default="low",
                        help="Thinking level (default: low)")
    parser.add_argument("--url", action="append", dest="urls", default=[],
                        help="Additional URLs to include as context (can be used multiple times)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON response")
    args = parser.parse_args()

    # Get query from args or stdin
    if args.query:
        query = args.query
    elif not sys.stdin.isatty():
        query = sys.stdin.read().strip()
    else:
        parser.print_help()
        sys.exit(1)

    if not query:
        print("Error: No query provided", file=sys.stderr)
        sys.exit(1)

    # Check for API key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Error: google-genai not installed. Run: pip install google-genai", file=sys.stderr)
        sys.exit(1)

    # Initialize client
    client = genai.Client(api_key=api_key)
    model = "gemini-3-flash-preview"

    # Build content
    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=query)],
        ),
    ]

    # Build tools - always include Google Search, optionally add URL context
    tools = [
        types.Tool(google_search=types.GoogleSearch()),
    ]
    
    # Add URL context if URLs provided
    if args.urls:
        tools.append(types.Tool(url_context=types.UrlContext()))
        # Append URLs to the query
        url_context = "\n\nAlso consider these URLs for context:\n" + "\n".join(f"- {url}" for url in args.urls)
        contents[0].parts[0] = types.Part.from_text(text=query + url_context)

    # Map thinking level
    thinking_map = {
        "off": None,
        "low": "LOW",
        "medium": "MEDIUM",
        "high": "HIGH"
    }
    
    thinking_config = None
    if args.thinking != "off":
        thinking_config = types.ThinkingConfig(thinking_level=thinking_map[args.thinking])

    # Generate config
    config_kwargs = {"tools": tools}
    if thinking_config:
        config_kwargs["thinking_config"] = thinking_config
    
    generate_content_config = types.GenerateContentConfig(**config_kwargs)

    # Stream response
    try:
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
        ):
            if chunk.text:
                print(chunk.text, end="", flush=True)
        print()  # Final newline
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
