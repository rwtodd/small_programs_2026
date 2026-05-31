"""CLI entrypoint for mwbook-to-epub."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Sequence

from . import __version__


def _read_credentials(path: str) -> dict[str, str]:
    """Load wiki credentials JSON (same format as wiki-xfer / rwt_wikiapi)."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f) or {}
    except FileNotFoundError:
        sys.exit(f"Credentials file not found: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in credentials file: {e}")

    base_url = raw.get("base_url") or raw.get("url")
    username = raw.get("username") or raw.get("uname")
    password = raw.get("password") or raw.get("pw")

    if not (base_url and username and password):
        sys.exit(
            'Credentials file must contain "base_url" (or "url"), '
            '"username" (or "uname"), and "password" (or "pw")'
        )
    return {"base_url": base_url, "username": username, "password": password}


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mwbook-to-epub",
        description="Convert a MediaWiki book (TOC page + chapters in wikitext) to EPUB 3.3",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    parser.add_argument(
        "-c",
        "--creds",
        default="wiki_creds.json",
        help="JSON credentials file for the wiki (default: wiki_creds.json)",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Persistent working directory for restartable stages (default: derived from book title)",
    )
    parser.add_argument(
        "--toc-file",
        type=Path,
        help="Local wikitext file containing the book's TOC page (for offline use)",
    )
    parser.add_argument(
        "--toc-page",
        help="Page title on the wiki to use as the TOC (will be fetched via API)",
    )
    parser.add_argument(
        "--stages",
        default="1,2,3",
        help="Comma-separated list of stages to run (1=fetch, 2=convert, 3=epub). Default: all",
    )
    parser.add_argument(
        "--start-from",
        type=int,
        choices=[1, 2, 3],
        help="Shortcut: run this stage and all later ones (equivalent to --stages N,2,3 etc.)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if files already exist in the workdir",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=None,
        help="Output .epub filename (default: derived from book title in workdir)",
    )

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    log = logging.getLogger("mwbook_to_epub")

    # Resolve which stages to run
    if args.start_from:
        stages = list(range(args.start_from, 4))
    else:
        stages = sorted({int(s.strip()) for s in args.stages.split(",") if s.strip()})

    log.info("mwbook-to-epub %s starting (stages=%s)", __version__, stages)

    if args.toc_file and args.toc_page:
        parser.error("--toc-file and --toc-page are mutually exclusive")

    creds = None
    needs_creds = bool(args.toc_page) or (1 in stages and not args.toc_file)
    if needs_creds:
        creds = _read_credentials(args.creds)
        log.debug("Credentials loaded for %s", creds["base_url"])

    workdir = args.workdir or Path.cwd() / "mwbook_work"
    workdir.mkdir(parents=True, exist_ok=True)
    log.info("Workdir: %s", workdir)

    # Dispatch to stages (they are responsible for being restartable / incremental)
    from . import stage1, stage2, stage3

    if 1 in stages:
        stage1.run_stage1(
            workdir=workdir,
            creds=creds,
            toc_file=args.toc_file,
            toc_page=args.toc_page,
            force=args.force,
        )
    if 2 in stages:
        stage2.run_stage2(workdir=workdir, force=args.force)
    if 3 in stages:
        out = stage3.run_stage3(workdir=workdir, output=Path(args.output) if args.output else None)
        log.info("EPUB written: %s", out)

    log.info("All requested stages complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
