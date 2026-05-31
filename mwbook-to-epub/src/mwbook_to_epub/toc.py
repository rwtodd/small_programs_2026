"""TOC generation and loading for mwbook-to-epub.

Produces (and consumes) a JSON file compatible with the format used by
cbz_to_epub + rwt_epub, but using "src" (xhtml filename) instead of "page"
(integer spine position).

The generated file lives in the workdir as `toc.json` and can be hand-edited
before Stage 3. It supports up to 3 levels of nesting.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ChapterInfo

log = logging.getLogger(__name__)


@dataclass
class _TocNode:
    """Internal tree node used while parsing wiki list structure."""
    title: str
    src: str | None = None
    level: int = 1
    children: list["_TocNode"] = field(default_factory=list)


def _find_first_src(node: _TocNode) -> str | None:
    """Depth-first search for the first leaf that has a src (xhtml filename)."""
    if node.src:
        return node.src
    for child in node.children:
        s = _find_first_src(child)
        if s:
            return s
    return None


def _flatten_tree(node: _TocNode, out: list[dict[str, Any]]) -> None:
    """Pre-order flatten, filling in src for header nodes from their first descendant."""
    if node.title == "__ROOT__":
        for ch in node.children:
            _flatten_tree(ch, out)
        return

    src = node.src
    if src is None and node.children:
        src = _find_first_src(node)

    if src:
        out.append({
            "title": node.title,
            "src": src,
            "level": max(1, min(3, node.level)),
        })

    for ch in node.children:
        _flatten_tree(ch, out)


def generate_toc_json(
    toc_wikitext: str,
    chapters: list[ChapterInfo],
) -> list[dict[str, Any]]:
    """
    Parse a wiki TOC page (wikitext) that uses * / # lists (possibly with
    plain-text section headers like "Paths" / "Appendices") and turn it into
    the flat level-list format expected by rwt_epub (via add_toc_entry).

    - Uses the authoritative xhtml_filename from the ChapterInfo list.
    - Plain "* Header" lines (no wikilink) become level-N entries whose "src"
      points at the first real chapter under them.
    - Caps nesting at level 3.
    - Always produces at least a flat list (one entry per chapter) as fallback.
    """
    if not chapters:
        return []

    page_to_xhtml: dict[str, str] = {c.page_title: c.xhtml_filename for c in chapters}
    # Also allow lookup by the display title (some hand-written TOCs might use it)
    display_to_xhtml: dict[str, str] = {c.display_title: c.xhtml_filename for c in chapters}

    root = _TocNode(title="__ROOT__", level=0)
    stack: list[_TocNode] = [root]

    lines = toc_wikitext.splitlines()

    for raw_line in lines:
        line = raw_line.rstrip()
        if not line or not line.lstrip().startswith(("*", "#")):
            continue

        m = re.match(r"^(\s*)([*#]+)\s*(.*)$", line)
        if not m:
            continue

        _, markers, content = m.groups()
        depth = len(markers)

        # Look for a wikilink anywhere on the (trimmed) content
        lm = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", content)
        if lm:
            target = lm.group(1).strip()
            disp = (lm.group(2) or target).strip()

            xhtml = page_to_xhtml.get(target) or display_to_xhtml.get(target)
            if not xhtml:
                # Try stripping parenthetical the way stage1 sometimes does
                clean_target = re.sub(r"\s*\([^)]*\)\s*$", "", target).strip()
                xhtml = page_to_xhtml.get(clean_target) or display_to_xhtml.get(clean_target)
            if not xhtml:
                continue

            node = _TocNode(title=disp, src=xhtml, level=depth)

            # Climb to the proper parent
            while stack and stack[-1].level >= depth:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            # Leaves are not pushed; only containers (headers) stay on stack
        else:
            # Plain text header, e.g. "* Paths" or "* Appendices"
            header_title = content.strip()
            if not header_title:
                continue

            node = _TocNode(title=header_title, src=None, level=depth)

            while stack and stack[-1].level >= depth:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            stack.append(node)  # headers can receive children

    # Flatten (pre-order) into the rwt_epub friendly list form
    result: list[dict[str, Any]] = []
    _flatten_tree(root, result)

    # Fallback: if the fancy parser produced nothing (unusual TOC format),
    # emit a simple flat list using the chapter order we already have.
    if not result:
        for ch in chapters:
            result.append({
                "title": ch.display_title,
                "src": ch.xhtml_filename,
                "level": 1,
            })

    return result


def load_toc_json(path: Path) -> list[dict[str, Any]]:
    """
    Load and lightly validate a toc.json file.

    Expected shape (mirrors cbz_to_epub style but with "src" filename instead of "page"):

        [
          {"title": "Chapter 1", "src": "001_Chapter_1.xhtml", "level": 1},
          {"title": "Section A", "src": "004_Section_A.xhtml", "level": 2},
          ...
        ]

    "level" is optional (defaults to 1). "src" (or "file"/"target") must be an xhtml filename.
    Returns the list ready to be passed to EpubWriter.add_toc_entry(title, src, level=...).
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.error("TOC file not found: %s", path)
        raise
    except json.JSONDecodeError as e:
        log.error("Invalid JSON in TOC file %s: %s", path, e)
        raise

    if not isinstance(data, list):
        raise ValueError("TOC file must contain a JSON array of entries")

    toc: list[dict[str, Any]] = []
    for i, entry in enumerate(data, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"TOC entry #{i} must be an object")
        if "title" not in entry:
            raise ValueError(f"TOC entry #{i} must have a 'title' key")

        title = str(entry["title"]).strip()
        if not title:
            raise ValueError(f"TOC entry #{i}: 'title' must be a non-empty string")

        # Accept several key names for the xhtml target for user convenience
        src = entry.get("src") or entry.get("file") or entry.get("target") or entry.get("href")
        if not src or not isinstance(src, str):
            raise ValueError(f"TOC entry #{i} must have 'src' (xhtml filename)")

        src = src.strip()
        if not src.lower().endswith(".xhtml"):
            # be friendly: allow bare stem
            src = src + ".xhtml" if not src.endswith(".xhtml") else src

        level = int(entry.get("level", 1))
        if not (1 <= level <= 3):
            raise ValueError(f"TOC entry #{i}: 'level' must be 1, 2, or 3")

        toc.append({"title": title, "src": src, "level": level})

    # Validate monotonic level increases (same rule as rwt_epub)
    prev_level = 0
    for i, e in enumerate(toc, 1):
        if e["level"] > prev_level + 1:
            raise ValueError(
                f"TOC entry #{i}: level jumped from {prev_level} to {e['level']} "
                "(max jump is +1 between consecutive entries)"
            )
        prev_level = e["level"]

    return toc


def write_default_flat_toc(
    path: Path,
    chapters: list[ChapterInfo],
) -> None:
    """Write a simple flat (all level 1) toc.json as a safe fallback."""
    data = [
        {"title": ch.display_title, "src": ch.xhtml_filename, "level": 1}
        for ch in chapters
    ]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_toc_json(
    workdir: Path,
    chapters: list[ChapterInfo],
    toc_wikitext_path: Path | None = None,
    force: bool = False,
) -> Path:
    """
    Ensure <workdir>/toc.json exists.

    - If it already exists and not force, do nothing.
    - Otherwise try to generate a nice nested version from the original wiki
      TOC wikitext. Fall back to a flat list using the ChapterInfo we already have.
    - This function is intentionally idempotent and safe to call from both
      Stage 1 (after first download) and Stage 2 (on --start-from 2 restarts).
    """
    toc_json_path = workdir / "toc.json"
    if toc_json_path.exists() and not force:
        return toc_json_path

    generated = False
    if toc_wikitext_path and toc_wikitext_path.exists():
        try:
            toc_text = toc_wikitext_path.read_text(encoding="utf-8")
            toc_list = generate_toc_json(toc_text, chapters)
            toc_json_path.write_text(
                json.dumps(toc_list, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            log.info("Generated %s (%d entries)", toc_json_path, len(toc_list))
            generated = True
        except Exception as e:
            log.warning("Could not generate structured toc.json from %s: %s", toc_wikitext_path, e)

    if not generated:
        write_default_flat_toc(toc_json_path, chapters)
        log.info("Wrote flat fallback %s", toc_json_path)

    return toc_json_path
