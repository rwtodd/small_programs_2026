"""Dataclasses for the persistent metadata that makes stages restartable."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ConversionContext:
    """Lightweight context passed to the wikitext converter.

    This lives here (instead of stage2) to avoid circular imports with templates.py.
    """

    # Set of page titles (original, with underscores or spaces) that belong to this book.
    book_pages: set[str] = field(default_factory=set)

    # Rich mappings from the authoritative ChapterInfo list (populated in run_stage2).
    # These let us emit the nice TOC-derived <h1> and turn [[Wiki Page Title]] into
    # correct <a href="003_Nice_Title.xhtml"> links for internal book pages.
    page_to_xhtml: dict[str, str] = field(default_factory=dict)   # page_title → "003_Foo.xhtml"
    page_to_display: dict[str, str] = field(default_factory=dict) # page_title → "Foo (nice TOC title)"

    # Mapping from original File: name → chosen filename to use in the EPUB
    image_map: dict[str, str] = field(default_factory=dict)

    # Where to find the actual image files (dev against example_inputs/IMAGEs or real workdir/images/)
    images_root: Path | None = None

    # The workdir we are operating on (optional)
    workdir: Path | None = None

    # Whether to emit an <h1> with the cleaned chapter title
    emit_title_h1: bool = True

    # Explicit cover image filename (takes precedence over other logic).
    # This is how we support easy manual recovery when Stage 1 is uncertain.
    cover_image: str | None = None


@dataclass
class ImageInfo:
    """One unique image discovered during stage 1."""

    original_name: str  # e.g. "CaseTolFig00015.jpg" (normalized)
    chosen_local: str   # e.g. "CaseTolFig00015.webp" or ".jpg" if webp was bigger
    media_type: str     # from rwt_epub.EpubWriter.media_type
    was_converted: bool = False
    orig_size: int = 0
    final_size: int = 0


@dataclass
class ChapterInfo:
    """One chapter (wiki page) in reading order."""

    page_title: str          # exact title as stored on the wiki / in TOC
    display_title: str       # after parenthetical stripping for h1
    xhtml_filename: str      # e.g. "001_Path_1.xhtml" (padded for sort order)
    order: int               # 0-based position in spine after cover


@dataclass
class BookMetadata:
    """Everything needed to restart any stage without re-fetching."""

    book_title: str
    author: str = ""
    pub_year: int | str = ""
    language: str = "en"
    cover_image: str | None = None
    """The filename (in the images directory) to use as the book's cover.

    This is the single source of truth. If Stage 1 cannot confidently pick one,
    it will leave this as null and log clear recovery instructions.
    You can (and should) manually edit this field in metadata.json between
    stages when the TOC is ambiguous. Stage 3 will use whatever value is here.
    """
    chapters: list[ChapterInfo] = field(default_factory=list)
    images: dict[str, ImageInfo] = field(default_factory=dict)  # key = original_name
    toc_page_title: str | None = None
    created_from: str = "toc-file or toc-page"

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = asdict(self)
        # images dict needs special handling because keys are the original names
        data["images"] = {k: asdict(v) for k, v in self.images.items()}
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, path: Path) -> BookMetadata:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        imgs = {k: ImageInfo(**v) for k, v in data.pop("images", {}).items()}
        chaps = [ChapterInfo(**c) for c in data.pop("chapters", [])]
        return cls(**data, chapters=chaps, images=imgs)
