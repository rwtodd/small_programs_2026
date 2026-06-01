"""Small shared helpers (slugging, magick wrappers, parenthetical stripping per spec, etc.)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def strip_last_parenthetical(title: str) -> str:
    """Remove only the *last* trailing parenthetical group, per review decision.

    "Hello (there) (again)" -> "Hello (there)"
    "Path 1 (32 Paths PFC)" -> "Path 1"
    """
    import re
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


def run_magick_identify(path: Path) -> tuple[int, int] | None:
    """Return (width, height) using `magick identify`, or None on failure."""
    try:
        out = subprocess.check_output(
            ["magick", "identify", "-format", "%w %h", str(path)],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        w, h = out.split()
        return int(w), int(h)
    except Exception:
        return None


def safe_filename(name: str, max_length: int = 25) -> str:
    """
    Produce a very safe filename component.

    - Keeps only ASCII letters and digits.
    - Replaces any other character with underscore.
    - Collapses runs of underscores.
    - Strips leading/trailing underscores.
    - Truncates to `max_length` characters (default 25).

    Intended for chapter XHTML filenames derived from TOC titles.
    The numeric prefix (001_, 002_, ...) is added by the caller and guarantees
    uniqueness even if many titles truncate to the same short slug.
    """
    import re
    # Replace anything that is not A-Z a-z 0-9 with underscore
    name = re.sub(r'[^A-Za-z0-9]+', '_', name)
    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)
    # Strip leading/trailing underscores
    name = name.strip('_')

    # Truncate if necessary
    if len(name) > max_length:
        name = name[:max_length].rstrip('_')
        if not name:
            name = "untitled"

    return name


def convert_to_webp_if_smaller(
    original_path: Path,
    *,
    quality: str = "80%",
) -> tuple[str, bool, int, int, int | None, int | None]:
    """
    Given an original raster image on disk, create a .webp sibling (at the given
    quality) *only if* the WEBP version is strictly smaller.

    - Original file is **never** deleted or overwritten (user requirement).
    - .webp inputs are passed through unchanged.
    - On any magick failure, falls back to the original.

    Returns:
        (chosen_basename, was_converted, orig_size, final_size, width, height)
        chosen_basename is relative to the directory containing the original.
    """
    if not original_path.exists():
        raise FileNotFoundError(original_path)

    suffix = original_path.suffix.lower()
    orig_ext = suffix.lstrip(".")
    if orig_ext == "jpeg":
        orig_ext = "jpg"

    is_already_webp = suffix == ".webp"
    orig_size = original_path.stat().st_size

    try:
        # Get dimensions
        fmt_hint = "webp" if is_already_webp else orig_ext
        id_result = subprocess.run(
            ["magick", "identify", "-format", "%w %h", f"{fmt_hint}:{original_path}"],
            capture_output=True,
            check=True,
            text=True,
        )
        w, h = [int(x) for x in id_result.stdout.strip().split()]

        if is_already_webp:
            return original_path.name, False, orig_size, orig_size, w, h

        # Attempt WEBP conversion in memory
        conv_result = subprocess.run(
            ["magick", "convert", "-quality", quality, f"{orig_ext}:{original_path}", "webp:-"],
            capture_output=True,
            check=True,
        )
        webp_data = conv_result.stdout

        if len(webp_data) > 0 and len(webp_data) < orig_size:
            # WEBP wins — write it next to the original
            webp_path = original_path.with_suffix(".webp")
            webp_path.write_bytes(webp_data)
            final_size = len(webp_data)
            return webp_path.name, True, orig_size, final_size, w, h
        else:
            # Original is smaller or equal — keep it, do not create (or keep stale) webp
            return original_path.name, False, orig_size, orig_size, w, h

    except (subprocess.CalledProcessError, FileNotFoundError, ValueError, IndexError) as e:
        # magick not found, conversion failed, or bad output — safe fallback
        if not isinstance(e, FileNotFoundError):
            # Only log real conversion problems
            import logging
            logging.getLogger(__name__).warning(
                "WEBP conversion failed for %s (%s); using original", original_path.name, e
            )
        return original_path.name, False, orig_size, orig_size, None, None
