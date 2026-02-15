#!/usr/bin/env python3
"""Multi-purpose Gemini helper for downstream agent tasks."""

import argparse
import json
import mimetypes
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_TEXT_MODEL = "gemini-3-flash-preview"
DEFAULT_GROUNDED_MODEL = "gemini-3-pro-preview"
DEFAULT_IMAGE_MODEL = "gemini-3-pro-image-preview"
FALLBACK_IMAGE_MODEL = "gemini-2.5-flash-image-preview"

TEXT_MODES = {"qa", "summarize", "grounded-qa"}
THINKING_LEVELS = {
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Gemini runner for QA, summarization, grounded QA, "
            "and image generation/editing."
        )
    )
    parser.add_argument("query", nargs="?", help="Prompt/query (or read from stdin if omitted)")
    parser.add_argument(
        "--mode",
        choices=["qa", "summarize", "grounded-qa", "image"],
        default="qa",
        help="Task mode (default: qa)",
    )
    parser.add_argument(
        "--thinking",
        choices=["off", "low", "medium", "high"],
        default="low",
        help="Gemini thinking level for text modes (default: low)",
    )
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        default=[],
        help="URL context (repeatable). Enables URL Context tool.",
    )
    parser.add_argument(
        "--input-file",
        help="Input text file for qa/summarize modes.",
    )
    parser.add_argument(
        "--text-model",
        default=DEFAULT_TEXT_MODEL,
        help=f"Text model for qa/summarize (default: {DEFAULT_TEXT_MODEL}).",
    )
    parser.add_argument(
        "--grounded-model",
        default=DEFAULT_GROUNDED_MODEL,
        help=(
            "Model for grounded-qa mode "
            f"(default: {DEFAULT_GROUNDED_MODEL})."
        ),
    )
    parser.add_argument(
        "--image-model",
        default=DEFAULT_IMAGE_MODEL,
        help=f"Image model for image mode (default: {DEFAULT_IMAGE_MODEL}).",
    )
    parser.add_argument(
        "-i",
        "--input-image",
        action="append",
        dest="input_images",
        default=[],
        help="Input image path for image edit/composition mode (repeatable).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output image path for image mode (default: /tmp/gemini-image-<timestamp>.png).",
    )
    parser.add_argument(
        "--image-size",
        choices=["1K", "2K", "4K"],
        help="Optional image size for image mode.",
    )
    parser.add_argument(
        "--show-sources",
        dest="show_sources",
        action="store_true",
        default=True,
        help="Print grounding sources for grounded-qa mode (default: on).",
    )
    parser.add_argument(
        "--no-sources",
        dest="show_sources",
        action="store_false",
        help="Disable source printing for grounded-qa mode.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser.parse_args()


def _read_stdin() -> str:
    if sys.stdin.isatty():
        return ""
    # Check if stdin has data available (non-blocking)
    import select
    if not select.select([sys.stdin], [], [], 0.0)[0]:
        return ""
    return sys.stdin.read().strip()


def _read_text_file(path: str | None) -> str:
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        print(f"Error: Failed to read --input-file '{path}': {exc}", file=sys.stderr)
        sys.exit(1)


def _require_api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    return api_key


def _import_sdk():
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print(
            "Error: google-genai not installed. Run: python3 -m pip install google-genai",
            file=sys.stderr,
        )
        sys.exit(1)
    return genai, types


def _build_thinking_config(types: Any, thinking: str) -> Any | None:
    if thinking == "off":
        return None
    return types.ThinkingConfig(thinking_level=THINKING_LEVELS[thinking])


def _append_url_context(prompt: str, urls: list[str]) -> str:
    if not urls:
        return prompt
    lines = "\n".join(f"- {url}" for url in urls)
    return (
        f"{prompt}\n\nUse these URLs as context when relevant:\n{lines}"
    )


def _build_prompt(mode: str, query: str, source_text: str) -> str:
    if mode == "qa":
        if source_text:
            return (
                "Answer the user request using ONLY the source content.\n"
                "If the source is insufficient, say exactly what is missing.\n"
                f"Request:\n{query}\n\n"
                f"Source content:\n{source_text}"
            )
        return query

    if mode == "grounded-qa":
        return query

    if mode == "summarize":
        if source_text:
            focus = query or "key points, decisions, and action items"
            return (
                "Summarize the source content.\n"
                f"Focus: {focus}\n\n"
                f"Source content:\n{source_text}"
            )
        return f"Summarize this content:\n{query}"

    raise ValueError(f"Unsupported mode: {mode}")


def _iter_response_parts(response: Any):
    parts = getattr(response, "parts", None)
    if parts:
        for part in parts:
            yield part
        return
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content and getattr(content, "parts", None):
            for part in content.parts:
                yield part


def _extract_grounding_sources(response: Any) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    seen_uris: set[str] = set()
    for candidate in getattr(response, "candidates", []) or []:
        grounding = getattr(candidate, "grounding_metadata", None)
        chunks = getattr(grounding, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web is None:
                continue
            uri = getattr(web, "uri", None)
            title = getattr(web, "title", None) or "Untitled"
            if not uri or uri in seen_uris:
                continue
            seen_uris.add(uri)
            sources.append({"title": title, "uri": uri})
    return sources


def _response_to_dict(response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "to_json_dict"):
        return response.to_json_dict()
    text = getattr(response, "text", "")
    return {"text": text}


def _run_text_mode(client: Any, types: Any, args: argparse.Namespace, query: str, source_text: str):
    model = args.grounded_model if args.mode == "grounded-qa" else args.text_model
    prompt = _build_prompt(args.mode, query, source_text)
    prompt = _append_url_context(prompt, args.urls)

    tools = []
    if args.mode == "grounded-qa":
        tools.append(types.Tool(google_search=types.GoogleSearch()))
    if args.urls:
        tools.append(types.Tool(url_context=types.UrlContext()))

    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt)],
    )
    config_kwargs: dict[str, Any] = {}
    if tools:
        config_kwargs["tools"] = tools

    thinking_config = _build_thinking_config(types, args.thinking)
    if thinking_config:
        config_kwargs["thinking_config"] = thinking_config

    config = types.GenerateContentConfig(**config_kwargs)
    response = client.models.generate_content(
        model=model,
        contents=[content],
        config=config,
    )

    sources = _extract_grounding_sources(response) if args.mode == "grounded-qa" else []

    if args.json:
        payload = _response_to_dict(response)
        if sources:
            payload["sources"] = sources
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    text = (getattr(response, "text", "") or "").strip()
    if text:
        print(text)

    if args.mode == "grounded-qa" and args.show_sources and sources:
        print("\nSources:")
        for idx, item in enumerate(sources, start=1):
            print(f"{idx}. {item['title']} - {item['uri']}")


def _guess_mime_type(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    return mime_type or "image/png"


def _default_image_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(f"/tmp/gemini-image-{timestamp}.png")


def _build_image_content(types: Any, prompt: str, input_images: list[str]):
    parts = []
    for image_path in input_images:
        path = Path(image_path)
        if not path.exists():
            print(f"Error: Input image not found: {image_path}", file=sys.stderr)
            sys.exit(1)
        data = path.read_bytes()
        parts.append(types.Part.from_bytes(data=data, mime_type=_guess_mime_type(path)))
    parts.append(types.Part.from_text(text=prompt))
    return types.Content(role="user", parts=parts)


def _extract_first_image_bytes(response: Any) -> bytes | None:
    for part in _iter_response_parts(response):
        inline_data = getattr(part, "inline_data", None)
        if inline_data is None:
            continue
        data = getattr(inline_data, "data", None)
        if data:
            return data
    return None


def _collect_text_parts(response: Any) -> list[str]:
    texts: list[str] = []
    for part in _iter_response_parts(response):
        text = getattr(part, "text", None)
        if text:
            texts.append(text.strip())
    return [text for text in texts if text]


def _run_image_mode(client: Any, types: Any, args: argparse.Namespace, prompt: str):
    if not prompt:
        print("Error: image mode requires a prompt query", file=sys.stderr)
        sys.exit(1)

    model = args.image_model
    output_path = Path(args.output) if args.output else _default_image_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    content = _build_image_content(types, prompt, args.input_images)

    config_kwargs: dict[str, Any] = {
        "response_modalities": ["TEXT", "IMAGE"],
    }
    if args.image_size:
        config_kwargs["image_config"] = types.ImageConfig(image_size=args.image_size)
    config = types.GenerateContentConfig(**config_kwargs)

    try:
        response = client.models.generate_content(
            model=model,
            contents=[content],
            config=config,
        )
    except Exception as exc:
        # The docs currently reference both stable and preview image model names.
        if model == DEFAULT_IMAGE_MODEL and "model" in str(exc).lower():
            response = client.models.generate_content(
                model=FALLBACK_IMAGE_MODEL,
                contents=[content],
                config=config,
            )
            model = FALLBACK_IMAGE_MODEL
        else:
            raise

    image_bytes = _extract_first_image_bytes(response)
    if image_bytes is None:
        print("Error: No image returned by Gemini", file=sys.stderr)
        sys.exit(1)

    output_path.write_bytes(image_bytes)

    text_parts = _collect_text_parts(response)
    if args.json:
        payload = {
            "mode": "image",
            "model": model,
            "output_path": str(output_path.resolve()),
            "input_images": len(args.input_images),
            "text": text_parts,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    for text in text_parts:
        print(text)

    full_path = str(output_path.resolve())
    print(f"Image saved: {full_path}")
    print(f"MEDIA: {full_path}")


def _resolve_inputs(args: argparse.Namespace) -> tuple[str, str]:
    query = (args.query or "").strip()
    stdin_text = _read_stdin()
    source_text = _read_text_file(args.input_file)

    if args.mode == "summarize" and stdin_text and not source_text:
        source_text = stdin_text
    elif args.mode == "qa" and stdin_text and query and not source_text:
        source_text = stdin_text
    elif not query and stdin_text:
        query = stdin_text

    if args.mode in {"qa", "grounded-qa", "image"} and not query:
        print("Error: query/prompt is required for this mode", file=sys.stderr)
        sys.exit(1)

    if args.mode == "summarize" and not query and not source_text:
        print("Error: summarize mode needs query text or --input-file/stdin source text", file=sys.stderr)
        sys.exit(1)

    return query, source_text


def main():
    args = _parse_args()
    query, source_text = _resolve_inputs(args)
    api_key = _require_api_key()
    genai, types = _import_sdk()
    client = genai.Client(api_key=api_key)

    try:
        if args.mode in TEXT_MODES:
            _run_text_mode(client, types, args, query, source_text)
        else:
            _run_image_mode(client, types, args, query)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
