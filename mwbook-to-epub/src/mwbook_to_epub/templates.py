"""Handlers for the known custom templates (BibleVerse, Hebrew text, etc.).

All functions are pure and return XHTML fragments (or "").
Per spec + review: BibleVerse must render as plain text, never a hyperlink.
"""

from __future__ import annotations

import html
import re
from typing import Any

from .models import ConversionContext  # avoid circular import


def render_template(name: str, params: dict[str, str], ctx: ConversionContext | None = None) -> str:
    """Dispatch to the correct handler for a template name (case-insensitive)."""
    key = re.sub(r'[\s_]+', '', name).lower()
    handler = TEMPLATE_HANDLERS.get(key)
    if handler is None:
        return ""
    return handler(params, ctx=ctx)


# ------------------------------------------------------------------ #
# Individual template implementations
# ------------------------------------------------------------------ #

def handle_bible_verse(params: dict[str, str], ctx: ConversionContext | None = None) -> str:
    """BibleVerse → plain text only (never a link)."""
    if "3" in params:
        return html.escape(params["3"])
    book = params.get("1", "").strip()
    verse = params.get("2", "").strip()
    if book and verse:
        return html.escape(f"{book}:{verse}")
    return html.escape(book or verse or "")


def handle_hebrew_text(params: dict[str, str], ctx: ConversionContext | None = None) -> str:
    """{{Hebrew text|...}} → only the CSS class, no inline style (user preference for EPUB)."""
    text = params.get("1") or params.get("2") or ""
    return f'<span class="hebrew-text">{text}</span>'


def handle_center(params: dict[str, str], ctx: ConversionContext | None = None) -> str:
    content = params.get("1", "")
    return f'<div class="center">{content}</div>'


def handle_jesus_text(params: dict[str, str], ctx: ConversionContext | None = None) -> str:
    text = params.get("1", "")
    return f'<span class="rwtjesustxt">{html.escape(text)}</span>'


def handle_smallcaps(params: dict[str, str], ctx: ConversionContext | None = None) -> str:
    text = params.get("1", "")
    return f'<span style="font-variant: small-caps">{html.escape(text)}</span>'


def handle_strong_hebrew(params: dict[str, str], ctx: ConversionContext | None = None) -> str:
    num = params.get("1", "")
    label = params.get("2") or f"Strong's {num}"
    return html.escape(label)


def handle_inline_fraction(params: dict[str, str], ctx: ConversionContext | None = None) -> str:
    whole = params.get("wn") or params.get("1") or ""
    num = params.get("2") or params.get("1") or ""
    den = params.get("3") or params.get("2") or ""

    if "wn" in params and "2" not in params:
        num = params.get("1", "")
        den = params.get("2", "")

    parts = []
    if whole:
        parts.append(f"{whole}&#x202f;")
    parts.append(f'<sup style="vertical-align:text-top; font-size:80%">{html.escape(num)}</sup>')
    parts.append("/")
    parts.append(f'<sub style="vertical-align:text-bottom; font-size:80%">{html.escape(den)}</sub>')
    return "".join(parts)


def handle_clear(params: dict[str, str], ctx: ConversionContext | None = None) -> str:
    side = params.get("1", "both")
    return f'<div style="clear:{html.escape(side)};"></div>'


# Registry
TEMPLATE_HANDLERS: dict[str, Any] = {
    "bibleverse": handle_bible_verse,
    "hebrewtext": handle_hebrew_text,
    "hebrew_text": handle_hebrew_text,
    "center": handle_center,
    "jesustext": handle_jesus_text,
    "jesus_text": handle_jesus_text,
    "smallcaps": handle_smallcaps,
    "stronghebrew": handle_strong_hebrew,
    "inlinefraction": handle_inline_fraction,
    "inline_fraction": handle_inline_fraction,
    "clear": handle_clear,
}
