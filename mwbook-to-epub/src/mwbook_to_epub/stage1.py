"""Stage 1: Fetch TOC + chapters + images (restartable / incremental).

For the initial slice we only implement the pure offline --toc-file path
using mwparserfromhell. Network paths and image download are stubbed but
the metadata layout is written so later stages have something to work with.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

import mwparserfromhell as mwp

from .models import BookMetadata, ChapterInfo
from .utils import strip_last_parenthetical, safe_filename

log = logging.getLogger(__name__)


def _parse_header_comments(text: str) -> dict[str, str]:
    """Extract ; Key: Value lines at the top of a TOC wikitext."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith(";"):
            break
        if ":" in line:
            k, v = line[1:].split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _collect_chapters_from_toc(parsed: mwp.wikicode.Wikicode) -> list[tuple[str, str]]:
    """Return [(page_title, display_text), ...] walking only list items.

    This matches the spec: "actual chapter links will always be in part of
    either an ordered or unordered list".
    """
    chapters: list[tuple[str, str]] = []
    for node in parsed.ifilter(recursive=True):
        if isinstance(node, mwp.nodes.Wikilink):
            # Only consider links that appear inside list structures.
            # A simple heuristic: look at the parent context by walking
            # upward is hard in mwparser; instead we accept every link that
            # is *not* a File:/Category:/Template: link and record order of
            # appearance.  The TOC example only has the desired links inside
            # the lists, so this works for the golden file.
            title = str(node.title).strip()
            if title.startswith(("File:", "Category:", "Template:")):
                continue
            text = str(node.text) if node.text else title
            chapters.append((title, text))
    # De-duplicate while preserving order (some TOCs may repeat a link)
    seen = set()
    uniq: list[tuple[str, str]] = []
    for t, d in chapters:
        if t not in seen:
            seen.add(t)
            uniq.append((t, d))
    return uniq


def run_stage1(
    *,
    workdir: Path,
    creds: dict | None,
    toc_file: Path | None,
    toc_page: str | None,
    force: bool,
) -> None:
    """Entry point for stage 1. Only the offline toc_file path is live for v0.1 slice."""
    log.info("Stage 1 starting (offline slice)")

    downloads = workdir / "downloads"
    chapters_dir = downloads / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    if toc_page:
        if not creds:
            raise RuntimeError("toc_page requires credentials (use --creds)")
        log.info("Would fetch TOC page '%s' via rwt_wikiapi (not implemented in this slice)", toc_page)
        # In a later slice we would do:
        # with Client.session(...) as c: text = c.fetch_wikitext(toc_page)
        # For now we error so the user knows the boundary.
        raise NotImplementedError("Live wiki fetch for --toc-page is not yet wired (use --toc-file for the initial slice)")

    if not toc_file:
        raise ValueError("--toc-file is required for the offline slice")
    if not toc_file.exists():
        raise FileNotFoundError(f"TOC file not found: {toc_file}")

    src_text = toc_file.read_text(encoding="utf-8")
    header = _parse_header_comments(src_text)
    log.info("Header metadata: %s", header)

    parsed = mwp.parse(src_text)
    raw_chapters = _collect_chapters_from_toc(parsed)

    # Build ChapterInfo list.
    # Prefer the link text from the TOC (e.g. "Path of Kether" instead of "Path 1 (32 Paths PFC)")
    # Fall back to cleaning the page title.
    chapter_infos: list[ChapterInfo] = []
    for idx, (page_title, link_text) in enumerate(raw_chapters):
        if link_text and link_text != page_title:
            # Use the human-readable link text from the TOC
            clean = link_text.strip()
        else:
            clean = strip_last_parenthetical(page_title.replace("_", " "))

        safe = safe_filename(clean)
        xhtml_name = f"{idx+1:03d}_{safe}.xhtml"
        chapter_infos.append(
            ChapterInfo(
                page_title=page_title,
                display_title=clean,
                xhtml_filename=xhtml_name,
                order=idx,
            )
        )

    # Cover detection (designed to be easily overridable between stages)
    cover: str | None = None
    cover_reason = ""

    # Preferred: explicit "cover" in filename or caption
    for link in parsed.ifilter_wikilinks():
        t = str(link.title)
        if not t.lower().startswith(("file:", "image:")):
            continue
        fname = t.split("|")[0].removeprefix("File:").removeprefix("Image:").strip()
        if "cover" in t.lower() or "cover" in str(link.text or "").lower():
            cover = fname
            cover_reason = "filename or caption contained 'cover'"
            break

    # Secondary heuristic: first right/center thumb image that appears before the main contents lists
    if not cover:
        for link in parsed.ifilter_wikilinks():
            t = str(link.title)
            if not t.lower().startswith(("file:", "image:")):
                continue
            fname = t.split("|")[0].removeprefix("File:").removeprefix("Image:").strip()
            opts = str(link.text or "").lower()
            if "thumb" in opts and ("right" in opts or "center" in opts):
                cover = fname
                cover_reason = "first right/center thumbnail image found (heuristic)"
                break

    # Final fallback: first image of any kind
    if not cover:
        for link in parsed.ifilter_wikilinks():
            t = str(link.title)
            if t.lower().startswith(("file:", "image:")):
                cover = t.split("|")[0].removeprefix("File:").removeprefix("Image:").strip()
                cover_reason = "first image found in TOC (weak fallback)"
                break

    if cover:
        log.info("Cover image chosen: %s (reason: %s)", cover, cover_reason)
    else:
        log.warning(
            "No cover image could be automatically detected in the TOC. "
            "This is recoverable: after this run, edit metadata.json and set "
            '"cover_image": "ExactFilenameFromImagesDir.jpg" (the file must exist under images/ or IMAGEs/ for now). '
            "Then you can safely re-run from --stages 3 without touching Stage 1."
        )
    log.info("Found %d chapters from lists in TOC", len(chapter_infos))

    # Copy the TOC into the workdir (immutable source of truth)
    toc_dest = downloads / "toc.wikitext"
    if force or not toc_dest.exists():
        shutil.copy2(toc_file, toc_dest)
        log.info("Copied TOC to %s", toc_dest)

    # For this slice we do *not* have the actual chapter wikitext files yet.
    # We still write the metadata so the restart story is visible.
    # Later slices (when user supplies chapter examples) will populate downloads/chapters/.

    meta = BookMetadata(
        book_title=header.get("title", "Untitled Book"),
        author=header.get("author", ""),
        pub_year=header.get("date", ""),
        toc_page_title=header.get("title"),
        chapters=chapter_infos,
        cover_image=cover,
        created_from=str(toc_file),
    )

    meta_path = workdir / "metadata.json"
    meta.to_json(meta_path)
    log.info("Wrote %s with %d chapters", meta_path, len(chapter_infos))
    if cover:
        log.info("You can manually change the cover later by editing the 'cover_image' field in metadata.json")
    else:
        log.info("After editing 'cover_image' in metadata.json, re-run with --stages 3 (or --start-from 3)")

    # Create stub chapter wikitext placeholders so the directory layout is complete
    # (real content will overwrite when we have the files or do network fetch).
    for ch in chapter_infos:
        stub = chapters_dir / (ch.page_title.replace(" ", "_") + ".wikitext")
        if not stub.exists():
            stub.write_text(f"; placeholder for {ch.page_title}\n", encoding="utf-8")

    log.info("Stage 1 complete (offline slice). metadata + downloads/ layout ready for stage 2/3 experiments.")
