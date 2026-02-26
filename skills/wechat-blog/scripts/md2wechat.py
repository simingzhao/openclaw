#!/usr/bin/env python3
"""
md2wechat.py - Convert Markdown to WeChat-compatible HTML with inline styles.

Usage:
    python md2wechat.py input.md -o output.html
    python md2wechat.py input.md --style modern
    cat article.md | python md2wechat.py -
"""

import argparse
import sys
import re
import html
from typing import Optional

try:
    import markdown
    from markdown.extensions import tables, fenced_code, nl2br
except ImportError:
    print("Error: markdown library not found. Install with: pip install markdown")
    sys.exit(1)


# Style presets
STYLE_PRESETS = {
    "modern": {
        "name": "Modern",
        "description": "简洁现代风格，绿色强调色",
        "body": "font-size: 16px; line-height: 1.8; color: #333; margin-bottom: 16px;",
        "h1": "font-size: 24px; font-weight: bold; margin: 24px 0 16px; color: #1a1a1a;",
        "h2": "font-size: 20px; font-weight: bold; margin: 20px 0 12px; color: #1a1a1a; border-bottom: 1px solid #eee; padding-bottom: 8px;",
        "h3": "font-size: 18px; font-weight: bold; margin: 16px 0 10px; color: #1a1a1a;",
        "h4": "font-size: 16px; font-weight: bold; margin: 14px 0 8px; color: #1a1a1a;",
        "strong": "color: #1a1a1a;",
        "em": "font-style: italic;",
        "code_inline": "background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 14px; color: #c7254e;",
        "code_block": "background: #1e1e1e; color: #d4d4d4; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 14px; line-height: 1.5;",
        "blockquote": "border-left: 4px solid #10b981; padding: 12px 16px; margin: 16px 0; background: #f0fdf4; color: #166534;",
        "ul": "margin: 16px 0; padding-left: 24px;",
        "ol": "margin: 16px 0; padding-left: 24px;",
        "li": "margin: 8px 0; line-height: 1.8;",
        "a": "color: #2563eb; text-decoration: none;",
        "hr": "border: none; border-top: 1px solid #e5e5e5; margin: 24px 0;",
        "img": "max-width: 100%; height: auto; border-radius: 8px; margin: 16px 0;",
        "table": "width: 100%; border-collapse: collapse; margin: 16px 0;",
        "th": "background: #f5f5f5; padding: 12px; border: 1px solid #e5e5e5; font-weight: bold; text-align: left;",
        "td": "padding: 12px; border: 1px solid #e5e5e5;",
        "del": "text-decoration: line-through; color: #999;",
        "task_checked": "color: #10b981;",
        "task_unchecked": "color: #999;",
    },
    "tech": {
        "name": "Tech",
        "description": "深色代码块，蓝色强调色，适合技术文章",
        "body": "font-size: 16px; line-height: 1.8; color: #333; margin-bottom: 16px;",
        "h1": "font-size: 24px; font-weight: bold; margin: 24px 0 16px; color: #1e3a5f;",
        "h2": "font-size: 20px; font-weight: bold; margin: 20px 0 12px; color: #1e3a5f; border-bottom: 2px solid #3b82f6; padding-bottom: 8px;",
        "h3": "font-size: 18px; font-weight: bold; margin: 16px 0 10px; color: #1e3a5f;",
        "h4": "font-size: 16px; font-weight: bold; margin: 14px 0 8px; color: #1e3a5f;",
        "strong": "color: #1e3a5f;",
        "em": "font-style: italic;",
        "code_inline": "background: #1e293b; padding: 2px 6px; border-radius: 3px; font-size: 14px; color: #38bdf8;",
        "code_block": "background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 14px; line-height: 1.5; border: 1px solid #334155;",
        "blockquote": "border-left: 4px solid #3b82f6; padding: 12px 16px; margin: 16px 0; background: #eff6ff; color: #1e40af;",
        "ul": "margin: 16px 0; padding-left: 24px;",
        "ol": "margin: 16px 0; padding-left: 24px;",
        "li": "margin: 8px 0; line-height: 1.8;",
        "a": "color: #3b82f6; text-decoration: none;",
        "hr": "border: none; border-top: 2px solid #e5e5e5; margin: 24px 0;",
        "img": "max-width: 100%; height: auto; border-radius: 8px; margin: 16px 0; border: 1px solid #e5e5e5;",
        "table": "width: 100%; border-collapse: collapse; margin: 16px 0;",
        "th": "background: #1e293b; color: #fff; padding: 12px; border: 1px solid #334155; font-weight: bold; text-align: left;",
        "td": "padding: 12px; border: 1px solid #e5e5e5;",
        "del": "text-decoration: line-through; color: #999;",
        "task_checked": "color: #3b82f6;",
        "task_unchecked": "color: #999;",
    },
    "elegant": {
        "name": "Elegant",
        "description": "暖色调，衬线感，适合深度内容",
        "body": "font-size: 16px; line-height: 2; color: #4a4a4a; margin-bottom: 18px;",
        "h1": "font-size: 26px; font-weight: bold; margin: 28px 0 18px; color: #8b4513;",
        "h2": "font-size: 22px; font-weight: bold; margin: 24px 0 14px; color: #8b4513; border-bottom: 1px solid #deb887; padding-bottom: 10px;",
        "h3": "font-size: 18px; font-weight: bold; margin: 18px 0 12px; color: #8b4513;",
        "h4": "font-size: 16px; font-weight: bold; margin: 16px 0 10px; color: #8b4513;",
        "strong": "color: #8b4513;",
        "em": "font-style: italic; color: #666;",
        "code_inline": "background: #fdf6e3; padding: 2px 6px; border-radius: 3px; font-size: 14px; color: #b58900;",
        "code_block": "background: #fdf6e3; color: #657b83; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 14px; line-height: 1.6; border: 1px solid #eee8d5;",
        "blockquote": "border-left: 4px solid #deb887; padding: 14px 18px; margin: 18px 0; background: #fffaf0; color: #8b4513; font-style: italic;",
        "ul": "margin: 18px 0; padding-left: 28px;",
        "ol": "margin: 18px 0; padding-left: 28px;",
        "li": "margin: 10px 0; line-height: 2;",
        "a": "color: #cd853f; text-decoration: none; border-bottom: 1px dotted #cd853f;",
        "hr": "border: none; border-top: 1px solid #deb887; margin: 28px 0;",
        "img": "max-width: 100%; height: auto; border-radius: 4px; margin: 18px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.1);",
        "table": "width: 100%; border-collapse: collapse; margin: 18px 0;",
        "th": "background: #fdf6e3; padding: 14px; border: 1px solid #deb887; font-weight: bold; text-align: left; color: #8b4513;",
        "td": "padding: 14px; border: 1px solid #eee8d5;",
        "del": "text-decoration: line-through; color: #aaa;",
        "task_checked": "color: #8b4513;",
        "task_unchecked": "color: #aaa;",
    },
}


class WeChatHTMLPostprocessor:
    """Post-process HTML to add inline styles for WeChat compatibility."""

    def __init__(self, style: str = "modern"):
        self.styles = STYLE_PRESETS.get(style, STYLE_PRESETS["modern"])

    def process(self, html_content: str) -> str:
        """Process HTML and add inline styles."""
        # Process elements in order (from most specific to least specific)
        html_content = self._process_code_blocks(html_content)
        html_content = self._process_inline_code(html_content)
        html_content = self._process_headings(html_content)
        html_content = self._process_paragraphs(html_content)
        html_content = self._process_strong(html_content)
        html_content = self._process_em(html_content)
        html_content = self._process_blockquotes(html_content)
        html_content = self._process_lists(html_content)
        html_content = self._process_links(html_content)
        html_content = self._process_images(html_content)
        html_content = self._process_hr(html_content)
        html_content = self._process_tables(html_content)
        html_content = self._process_del(html_content)
        html_content = self._process_task_lists(html_content)

        return html_content

    def _process_code_blocks(self, content: str) -> str:
        """Process code blocks (pre + code)."""
        # Match <pre><code>...</code></pre> patterns
        pattern = r'<pre><code(?:\s+class="[^"]*")?>(.*?)</code></pre>'
        
        def replace_code_block(match):
            code_content = match.group(1)
            return f'<pre style="{self.styles["code_block"]}"><code>{code_content}</code></pre>'
        
        return re.sub(pattern, replace_code_block, content, flags=re.DOTALL)

    def _process_inline_code(self, content: str) -> str:
        """Process inline code (not inside pre)."""
        # Match <code> that is NOT inside <pre>
        # First, temporarily replace pre blocks
        pre_blocks = []
        def save_pre(match):
            pre_blocks.append(match.group(0))
            return f"__PRE_BLOCK_{len(pre_blocks) - 1}__"
        
        content = re.sub(r'<pre[^>]*>.*?</pre>', save_pre, content, flags=re.DOTALL)
        
        # Now process inline code
        content = re.sub(
            r'<code>([^<]+)</code>',
            f'<code style="{self.styles["code_inline"]}">\\1</code>',
            content
        )
        
        # Restore pre blocks
        for i, block in enumerate(pre_blocks):
            content = content.replace(f"__PRE_BLOCK_{i}__", block)
        
        return content

    def _process_headings(self, content: str) -> str:
        """Process h1-h4 headings."""
        for i in range(1, 5):
            style_key = f"h{i}"
            if style_key in self.styles:
                content = re.sub(
                    rf'<h{i}>([^<]*)</h{i}>',
                    f'<h{i} style="{self.styles[style_key]}">\\1</h{i}>',
                    content
                )
        return content

    def _process_paragraphs(self, content: str) -> str:
        """Process paragraphs."""
        return re.sub(
            r'<p>',
            f'<p style="{self.styles["body"]}">',
            content
        )

    def _process_strong(self, content: str) -> str:
        """Process bold text."""
        return re.sub(
            r'<strong>',
            f'<strong style="{self.styles["strong"]}">',
            content
        )

    def _process_em(self, content: str) -> str:
        """Process italic text."""
        return re.sub(
            r'<em>',
            f'<em style="{self.styles["em"]}">',
            content
        )

    def _process_blockquotes(self, content: str) -> str:
        """Process blockquotes."""
        return re.sub(
            r'<blockquote>',
            f'<blockquote style="{self.styles["blockquote"]}">',
            content
        )

    def _process_lists(self, content: str) -> str:
        """Process ul and ol lists."""
        content = re.sub(
            r'<ul>',
            f'<ul style="{self.styles["ul"]}">',
            content
        )
        content = re.sub(
            r'<ol>',
            f'<ol style="{self.styles["ol"]}">',
            content
        )
        content = re.sub(
            r'<li>',
            f'<li style="{self.styles["li"]}">',
            content
        )
        return content

    def _process_links(self, content: str) -> str:
        """Process links."""
        return re.sub(
            r'<a href="([^"]+)">',
            f'<a href="\\1" style="{self.styles["a"]}">',
            content
        )

    def _process_images(self, content: str) -> str:
        """Process images."""
        # Handle various img tag formats from markdown
        def replace_img(match):
            full_tag = match.group(0)
            # Extract src and alt
            src_match = re.search(r'src="([^"]+)"', full_tag)
            alt_match = re.search(r'alt="([^"]*)"', full_tag)
            src = src_match.group(1) if src_match else ""
            alt = alt_match.group(1) if alt_match else ""
            return f'<img src="{src}" alt="{alt}" style="{self.styles["img"]}" data-width="100%">'
        
        return re.sub(r'<img[^>]+/?>', replace_img, content)

    def _process_hr(self, content: str) -> str:
        """Process horizontal rules."""
        return re.sub(
            r'<hr\s*/?>',
            f'<hr style="{self.styles["hr"]}">',
            content
        )

    def _process_tables(self, content: str) -> str:
        """Process tables."""
        content = re.sub(
            r'<table>',
            f'<table style="{self.styles["table"]}">',
            content
        )
        content = re.sub(
            r'<th>',
            f'<th style="{self.styles["th"]}">',
            content
        )
        content = re.sub(
            r'<td>',
            f'<td style="{self.styles["td"]}">',
            content
        )
        return content

    def _process_del(self, content: str) -> str:
        """Process strikethrough text."""
        return re.sub(
            r'<del>',
            f'<del style="{self.styles["del"]}">',
            content
        )

    def _process_task_lists(self, content: str) -> str:
        """Process task list items (GFM style)."""
        # Convert [ ] and [x] in list items
        content = re.sub(
            r'<li([^>]*)>\s*\[\s*\]',
            f'<li\\1><span style="{self.styles["task_unchecked"]}">☐</span>',
            content
        )
        content = re.sub(
            r'<li([^>]*)>\s*\[x\]',
            f'<li\\1><span style="{self.styles["task_checked"]}">☑</span>',
            content,
            flags=re.IGNORECASE
        )
        return content


def convert_markdown_to_wechat(
    md_content: str,
    style: str = "modern"
) -> str:
    """
    Convert Markdown content to WeChat-compatible HTML.
    
    Args:
        md_content: Markdown source text
        style: Style preset name (modern, tech, elegant)
    
    Returns:
        HTML string with inline styles
    """
    # Configure markdown extensions for GFM support
    # NOTE: nl2br removed — it converts list-item continuation newlines to <br>,
    # causing broken bullet point formatting in WeChat.
    extensions = [
        'tables',           # GFM tables
        'fenced_code',      # Fenced code blocks
        'sane_lists',       # Better list handling
        'md_in_html',       # Markdown inside HTML
    ]
    
    # Pre-process: convert ~~text~~ to <del>text</del> (GFM strikethrough)
    md_content = re.sub(r'~~(.+?)~~', r'<del>\1</del>', md_content)
    
    # Convert Markdown to HTML
    md = markdown.Markdown(extensions=extensions)
    html_content = md.convert(md_content)
    
    # Post-process to add inline styles
    processor = WeChatHTMLPostprocessor(style=style)
    styled_html = processor.process(html_content)
    
    # Wrap in a container section
    wrapper_style = STYLE_PRESETS.get(style, STYLE_PRESETS["modern"])["body"]
    final_html = f'<section style="{wrapper_style}">\n{styled_html}\n</section>'
    
    return final_html


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Convert Markdown to WeChat-compatible HTML with inline styles.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python md2wechat.py input.md -o output.html
    python md2wechat.py input.md --style tech
    cat article.md | python md2wechat.py -
    
Style presets:
    modern  - 简洁现代风格，绿色强调色 (default)
    tech    - 深色代码块，蓝色强调色，适合技术文章
    elegant - 暖色调，衬线感，适合深度内容
        """
    )
    
    parser.add_argument(
        "input",
        nargs="?",
        help="Input Markdown file path, or '-' for stdin"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output HTML file path (default: stdout)"
    )
    parser.add_argument(
        "-s", "--style",
        default="modern",
        choices=["modern", "tech", "elegant", "minimal"],
        help="Style preset (default: modern)"
    )
    parser.add_argument(
        "--list-styles",
        action="store_true",
        help="List available style presets and exit"
    )
    
    args = parser.parse_args()
    
    # List styles if requested
    if args.list_styles:
        print("Available style presets:\n")
        for name, preset in STYLE_PRESETS.items():
            print(f"  {name:10} - {preset['description']}")
        sys.exit(0)
    
    # Check input is provided
    if not args.input:
        parser.error("the following arguments are required: input")
    
    # Read input
    if args.input == "-":
        md_content = sys.stdin.read()
    else:
        try:
            with open(args.input, "r", encoding="utf-8") as f:
                md_content = f.read()
        except FileNotFoundError:
            print(f"Error: File not found: {args.input}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            sys.exit(1)
    
    # Convert
    html_output = convert_markdown_to_wechat(md_content, style=args.style)
    
    # Write output
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(html_output)
            print(f"✓ Converted to {args.output} (style: {args.style})")
        except Exception as e:
            print(f"Error writing file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(html_output)


if __name__ == "__main__":
    main()
