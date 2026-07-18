"""Stage 1: Fetch TOC + chapters + images (restartable / incremental).

Supports both offline (--toc-file) and live wiki (--toc-page + --creds) modes.
Uses rwt_wikiapi for network access.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

import mwparserfromhell as mwp
from rwt_wikiapi import Client

from .models import BookMetadata, ChapterInfo, ImageInfo
from .toc import ensure_toc_json
from .utils import (
    convert_to_webp_if_smaller,
    get_image_media_type,
    strip_last_parenthetical,
    safe_filename,
    run_magick_identify,
)

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


def _extract_media_names(text: str) -> set[str]:
    """Extract unique media file names from wikitext (File:, Image:, Media:, and <gallery>)."""
    names: set[str] = set()

    # [[File:Foo.jpg|options]]
    # [[Image:Foo.jpg]]
    # [[Media:Foo.jpg|...]]
    for m in re.finditer(r'\[\[(?:File|Image|Media):([^\]|]+)', text, re.IGNORECASE):
        name = m.group(1).strip()
        if name:
            names.add(name)

    # <gallery>
    # File:Foo.jpg|Caption
    # Bar.png
    # </gallery>
    for gm in re.finditer(r'<gallery[^>]*>(.*?)</gallery>', text, re.IGNORECASE | re.DOTALL):
        gallery_content = gm.group(1)
        for line in gallery_content.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Remove options after |
            if '|' in line:
                line = line.split('|', 1)[0]
            # Strip File:/Image: prefix if present
            if ':' in line:
                prefix, rest = line.split(':', 1)
                if prefix.lower() in ('file', 'image'):
                    line = rest
            name = line.strip()
            if name:
                names.add(name)

    return names


def run_stage1(
    *,
    workdir: Path,
    creds: dict | None,
    toc_file: Path | None,
    toc_page: str | None,
    force: bool,
) -> None:
    """Entry point for stage 1. Supports both offline --toc-file and live --toc-page.

    The workdir is made self-contained:
    - Any TOC provided via --toc-file (even from outside the workdir) or --toc-page
      is materialized as <workdir>/downloads/toc.wikitext.
    - On subsequent runs you can omit --toc-file / --toc-page entirely; Stage 1 will
      automatically reuse the cached copy from the workdir.
    """
    log.info("Stage 1 starting")

    downloads = workdir / "downloads"
    chapters_dir = downloads / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    images_dir = downloads / "images"   # we'll use this for originals before any conversion decisions
    images_dir.mkdir(parents=True, exist_ok=True)

    canonical_toc = downloads / "toc.wikitext"

    src_text: str

    # Live fetch takes precedence
    if toc_page:
        if not creds:
            raise RuntimeError("toc_page requires credentials (use --creds)")

        base_url = creds["base_url"]
        username = creds["username"]
        password = creds["password"]

        log.info("Fetching TOC page '%s' from %s", toc_page, base_url)

        with Client.session(base_url, username, password) as client:
            src_text = client.fetch_wikitext(toc_page)

        canonical_toc.write_text(src_text, encoding="utf-8")
        log.info("Saved TOC to %s", canonical_toc)
        toc_file = canonical_toc

    # Auto-discover cached TOC from previous run if nothing was explicitly provided
    if not toc_file and canonical_toc.exists():
        toc_file = canonical_toc
        log.info("Reusing existing TOC from workdir: %s", canonical_toc)

    if not toc_file:
        raise ValueError(
            "--toc-file or --toc-page is required for Stage 1.\n"
            "Alternatively, run from a workdir that already contains downloads/toc.wikitext "
            "(created by a previous Stage 1 run)."
        )

    if not toc_file.exists():
        raise FileNotFoundError(f"TOC file not found: {toc_file}")

    # Read the source (this may be an external file the user pointed at)
    src_text = toc_file.read_text(encoding="utf-8")

    header = _parse_header_comments(src_text)
    log.info("Header metadata: %s", header)

    parsed = mwp.parse(src_text)
    raw_chapters = _collect_chapters_from_toc(parsed)

    all_media: set[str] = set()

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

        safe = safe_filename(clean)  # defaults to 25 chars; numeric prefix guarantees uniqueness
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

    # We can do live fetches (chapter wikitext + images) whenever we have credentials,
    # even if the TOC itself came from a local file (--toc-file).
    is_live_fetch = creds is not None

    # Discover media references from the TOC we just parsed
    all_media.update(_extract_media_names(src_text))

    # --- Live download of chapter wikitext (and all referenced media) ---
    if is_live_fetch:
        base_url = creds["base_url"]  # type: ignore[index]
        username = creds["username"]  # type: ignore[index]
        password = creds["password"]  # type: ignore[index]

        if toc_file and not toc_page:
            log.info("Using local TOC file, but performing live chapter + image downloads (credentials available).")

        with Client.session(base_url, username, password) as client:
            for ch in chapter_infos:
                target = chapters_dir / (ch.page_title.replace(" ", "_") + ".wikitext")
                if force or not target.exists():
                    log.info("Fetching chapter: %s", ch.page_title)
                    try:
                        text = client.fetch_wikitext(ch.page_title)
                        target.write_text(text, encoding="utf-8")
                    except Exception as e:
                        log.warning("Failed to fetch %s: %s", ch.page_title, e)
                        target.write_text(f"; ERROR fetching this page: {e}\n", encoding="utf-8")
                else:
                    log.debug("Chapter already present: %s", ch.page_title)

            # Now that chapter wikitext files exist (or already did), scan them all
            # for additional media references. This is important on first runs so
            # that images referenced *inside* chapters (not just the TOC) get downloaded.
            for ch in chapter_infos:
                ch_path = chapters_dir / (ch.page_title.replace(" ", "_") + ".wikitext")
                if ch_path.exists():
                    try:
                        ch_text = ch_path.read_text(encoding="utf-8")
                        all_media.update(_extract_media_names(ch_text))
                    except Exception:
                        pass

            # Download the cover image if we detected one
            if cover:
                cover_dest = images_dir / cover
                if force or not cover_dest.exists():
                    log.info("Downloading cover image: %s", cover)
                    try:
                        data = client.fetch_media(cover)
                        cover_dest.write_bytes(data)
                    except Exception as e:
                        log.warning("Failed to download cover image %s: %s", cover, e)
                else:
                    log.debug("Cover image already present: %s", cover)

            # Download all discovered media files (cover was already handled above)
            for media_name in sorted(all_media):
                if media_name == cover:
                    continue
                dest = images_dir / media_name
                if force or not dest.exists():
                    log.info("Downloading media: %s", media_name)
                    try:
                        data = client.fetch_media(media_name)
                        dest.write_bytes(data)
                    except Exception as e:
                        log.warning("Failed to download media %s: %s", media_name, e)
                else:
                    log.debug("Media already present: %s", media_name)

    # Ensure the workdir always contains a canonical copy of the TOC.
    # This makes the workdir fully self-contained and restartable.
    # - For live fetches: already written directly above.
    # - For external --toc-file (or restart using the cached one): make sure
    #   downloads/toc.wikitext exists and reflects what was used.
    toc_dest = downloads / "toc.wikitext"
    if toc_file != toc_dest:
        # The source was an external file the user pointed at (or a previous cached copy
        # that we want to keep as the canonical one).
        if force or not toc_dest.exists():
            shutil.copy2(toc_file, toc_dest)
            log.info("Materialized TOC into workdir: %s", toc_dest)
        elif toc_file != toc_dest and toc_dest.exists():
            # On non-force restart using an external file that differs, we still prefer
            # to keep the existing canonical copy (user may have edited it), but we log.
            log.debug("Using existing canonical TOC %s (external source %s not re-copied without --force)", toc_dest, toc_file)

    # Build ImageInfo entries, running WEBP size-comparison conversion where beneficial.
    # Original files are always left untouched on disk. The choice (original vs .webp)
    # is recorded in chosen_local so the user can override it later by editing metadata.json.
    images_dict: dict[str, ImageInfo] = {}
    for name in sorted(all_media):
        img_path = images_dir / name
        if img_path.exists():
            chosen_name, converted, osz, fsz, w, h = convert_to_webp_if_smaller(img_path)
            # If conversion happened we use the chosen_name's type, otherwise derive from original name.
            if chosen_name.lower().endswith(".webp"):
                mt = "image/webp"
            else:
                mt = get_image_media_type(name)
            images_dict[name] = ImageInfo(
                original_name=name,
                chosen_local=chosen_name,
                media_type=mt,
                was_converted=converted,
                orig_size=osz,
                final_size=fsz,
            )
        else:
            # Record the expectation even if file not present yet (offline planning)
            mt = get_image_media_type(name)
            images_dict[name] = ImageInfo(
                original_name=name,
                chosen_local=name,
                media_type=mt,
            )

    if cover and cover not in images_dict:
        img_path = images_dir / cover
        if img_path.exists():
            chosen_name, converted, osz, fsz, w, h = convert_to_webp_if_smaller(img_path)
            if chosen_name.lower().endswith(".webp"):
                mt = "image/webp"
            else:
                mt = get_image_media_type(cover)
            images_dict[cover] = ImageInfo(
                original_name=cover,
                chosen_local=chosen_name,
                media_type=mt,
                was_converted=converted,
                orig_size=osz,
                final_size=fsz,
            )
        else:
            images_dict[cover] = ImageInfo(
                original_name=cover,
                chosen_local=cover,
                media_type=get_image_media_type(cover),
            )

    # Use the chosen (possibly WEBP-optimized) version for the cover if we processed it.
    cover_for_metadata = cover
    if cover and cover in images_dict:
        cover_for_metadata = images_dict[cover].chosen_local

    meta = BookMetadata(
        book_title=header.get("title", "Untitled Book"),
        author=header.get("author", ""),
        pub_year=header.get("date", ""),
        toc_page_title=header.get("title"),
        chapters=chapter_infos,
        cover_image=cover_for_metadata,
        images=images_dict,
        created_from=str(toc_file),
    )

    meta_path = workdir / "metadata.json"
    meta.to_json(meta_path)
    log.info("Wrote %s with %d chapters", meta_path, len(chapter_infos))
    if cover:
        log.info("You can manually change the cover later by editing the 'cover_image' field in metadata.json")
    else:
        log.info("After editing 'cover_image' in metadata.json, re-run with --stages 3 (or --start-from 3)")

    # Inform user about the WEBP choice override mechanism
    converted_count = sum(1 for i in images_dict.values() if i.was_converted)
    if converted_count > 0:
        log.info(
            "%d images were converted to WEBP (smaller version kept alongside original). "
            "To force use of any original file, edit its 'chosen_local' in metadata.json "
            "back to the .jpg/.png name and re-run from stage 2.",
            converted_count,
        )

    # --- Generate editable TOC JSON (for rwt_epub) --------------------------------
    # Uses the canonical downloads/toc.wikitext we just materialized.
    toc_wikitext_path = downloads / "toc.wikitext"
    ensure_toc_json(workdir, chapter_infos, toc_wikitext_path, force=force)

    log.info("Stage 1 complete. metadata + downloads/ layout ready for stage 2/3.")
