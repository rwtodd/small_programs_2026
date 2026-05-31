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


def safe_filename(name: str) -> str:
    """Make a safe filename component (no :, /, \, etc. — good for EPUB and filesystems)."""
    import re
    name = re.sub(r'[:/\\?*"<>\|]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name.replace(' ', '_')


# TODO: magick convert + size-compare helper, safe_slug, etc.
