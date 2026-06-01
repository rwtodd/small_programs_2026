"""Stage 3: Assemble the final .epub using rwt_epub + artifacts from stage 2.

Minimal but real implementation so we can produce an actual inspectable EPUB
from Path_1 + Path_28 (the two hardest chapters) + cover image.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Sequence

from rwt_epub import EpubWriter

from .models import BookMetadata
from .toc import load_toc_json

log = logging.getLogger(__name__)


def run_stage3(
    *,
    workdir: Path | None = None,
    chapters: Sequence[Path] | None = None,
    cover_image: Path | None = None,
    images_dir: Path | None = None,
    title: str = "Test Book",
    author: str = "Unknown",
    year: int = 2026,
    output: Path | None = None,
) -> Path:
    """
    Produce a real EPUB.

    Supports two modes:
    - workdir mode (future full flow)
    - Quick ad-hoc mode (pass explicit chapters + cover + optional images_dir)

    When `images_dir` is provided in ad-hoc mode, we will:
      - Scan the chapter XHTML for <img> tags
      - Add the referenced image files to the EPUB
      - Rewrite the src attributes to the correct EPUB-relative paths
    """
    if output is None:
        output = Path("mwbook_test.epub")

    # Workdir mode support
    if workdir:
        meta_path = workdir / "metadata.json"
        xhtml_dir = workdir / "xhtml"

        if not chapters:
            if xhtml_dir.exists():
                chapters = sorted(xhtml_dir.glob("*.xhtml"))
                if chapters:
                    log.info("Discovered %d chapters from workdir: %s", len(chapters), xhtml_dir)

        # If still no chapters, give a clear actionable error instead of the generic one
        if not chapters:
            if not meta_path.exists():
                raise ValueError(
                    f"No metadata.json found in {workdir}. "
                    "Run with --stages 1 (or --start-from 1) first."
                )
            try:
                meta = BookMetadata.from_json(meta_path)
                expected = [ch.xhtml_filename for ch in meta.chapters]
            except Exception:
                expected = []

            # Extra diagnostics: show what actually exists in downloads/chapters
            chapters_dir = workdir / "downloads" / "chapters"
            existing_sources = []
            if chapters_dir.exists():
                existing_sources = sorted([p.name for p in chapters_dir.iterdir() if p.is_file()])

            msg = (
                f"No XHTML chapters found in {xhtml_dir}.\n"
                f"Expected files (from metadata): {expected}\n\n"
                f"Chapter sources present in {chapters_dir}: {existing_sources}\n\n"
                "To regenerate the XHTML files, run:\n"
                f"  uv run mwbook-to-epub --workdir {workdir} --start-from 2 -v\n\n"
                "Then re-run Stage 3 (or use --start-from 2 again)."
            )
            raise ValueError(msg)

        # Auto-discover images directory if not provided
        if images_dir is None:
            candidate = workdir / "downloads" / "images"
            if candidate.exists():
                images_dir = candidate
            else:
                candidate = workdir / "images"
                if candidate.exists():
                    images_dir = candidate

        # Auto-discover cover from metadata if not provided
        if cover_image is None and meta_path.exists():
            try:
                meta = BookMetadata.from_json(meta_path)
                if meta.cover_image and images_dir:
                    candidate = images_dir / meta.cover_image
                    if candidate.exists():
                        cover_image = candidate
            except Exception:
                pass

    if not chapters:
        raise ValueError("No chapters provided to Stage 3")

    # Try to get cover dimensions
    cover_dims: tuple[int, int] | None = None
    if cover_image and cover_image.exists():
        try:
            out = subprocess.check_output(
                ["magick", "identify", "-format", "%w %h", str(cover_image)],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            w, h = out.split()
            cover_dims = (int(w), int(h))
        except Exception as e:
            log.warning("Could not read cover dimensions with magick: %s", e)

    log.info("Building real EPUB: %s", output)

    with EpubWriter(str(output), title, author, year) as w:
        # Master stylesheet
        css_path = Path(__file__).parent.parent.parent / "data" / "book.css"
        if css_path.exists():
            w.add_stylesheet("book.css", css_path.read_text(encoding="utf-8"))
        else:
            w.add_stylesheet("book.css", "body { font-family: Georgia, serif; line-height: 1.5; }")

        # Cover
        if cover_image and cover_image.exists():
            cover_bytes = cover_image.read_bytes()
            cover_fname = cover_image.name
            if cover_dims:
                w.add_image_content(cover_fname, cover_bytes, is_cover=True, img_dims=cover_dims)
                w.add_fullpage_pic("cover-page", cover_fname)
                w.add_toc_entry("Cover", "cover-page.xhtml", level=1)
                log.info("Added Cover entry to the top of the TOC")
            else:
                w.add_image_content(cover_fname, cover_bytes, is_cover=True)

        # Process chapters (with optional image harvesting + src rewriting)
        image_files_added: set[str] = set()

        for i, chap_path in enumerate(chapters, 1):
            xhtml = chap_path.read_text(encoding="utf-8")
            chap_title = chap_path.stem.replace("_", " ")

            if images_dir:
                xhtml = _harvest_and_rewrite_images(xhtml, images_dir, w, image_files_added)
            else:
                # Even without images_dir, normalize common dev paths to the final EPUB path
                xhtml = re.sub(r'src=["\']\.\./images/([^"\']+)["\']', r'src="../Images/\1"', xhtml, flags=re.I)

            w.add_xhtml_body(chap_path.name, xhtml, title=chap_title)
            log.info("Added chapter %d: %s", i, chap_path.name)

        # Optional custom TOC (produced by Stage 1, editable by user before Stage 3).
        # Uses xhtml filenames so rwt_epub can resolve them directly.
        if workdir:
            toc_path = workdir / "toc.json"
            if toc_path.exists():
                try:
                    toc_entries = load_toc_json(toc_path)
                    for e in toc_entries:
                        w.add_toc_entry(e["title"], e["src"], level=e.get("level", 1))
                    log.info("Applied custom TOC (%d entries, up to level 3)", len(toc_entries))
                except Exception as exc:
                    log.warning("Failed to load/apply %s: %s (proceeding without custom TOC)", toc_path, exc)

    log.info("EPUB successfully written: %s", output)
    return output


def _harvest_and_rewrite_images(
    xhtml: str,
    images_dir: Path,
    epub_writer: "EpubWriter",
    already_added: set[str],
) -> str:
    """Find <img src="..."> in the XHTML, add the files to the EPUB, and rewrite src to ../Images/NAME."""

    def _replace_img(m):
        orig_src = m.group(1)
        # We only care about the filename
        fname = Path(orig_src).name

        # Clean any trailing whitespace and optional self-closing slash from the original attributes
        attrs = m.group(2).rstrip()
        if attrs.endswith('/'):
            attrs = attrs[:-1].rstrip()

        new_tag = f'<img src="../Images/{fname}"{attrs} />'

        if fname in already_added:
            return new_tag

        img_path = images_dir / fname
        if img_path.exists():
            data = img_path.read_bytes()
            epub_writer.add_image_content(fname, data)
            already_added.add(fname)
            log.info("  Added image to EPUB: %s", fname)
            return new_tag
        else:
            log.warning("  Image not found in images_dir: %s", fname)
            return m.group(0)

    # Match <img src="..." ...> (handles both self-closing and non-self-closing originals)
    # and rewrite to correct path + guaranteed self-closing form.
    return re.sub(
        r'<img\s+src=["\']([^"\']+)["\']([^>]*)>',
        _replace_img,
        xhtml,
        flags=re.IGNORECASE
    )
