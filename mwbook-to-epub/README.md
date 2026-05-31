# mwbook-to-epub

Convert a book that lives as wikitext pages on a MediaWiki site into a clean EPUB 3.3 file.

## Quick start (once implemented)

```bash
# 1. Create a creds file (same format as wiki-xfer)
cat > wiki_creds.json <<EOF
{
  "base_url": "https://yourwiki.example.com/w",
  "username": "you",
  "password": "secret"
}
EOF

# 2. Run all stages from a live TOC page (creates ./32paths_work/)
uv run mwbook-to-epub --toc-page "32 Paths of Wisdom (PF Case)" -c wiki_creds.json --workdir 32paths_work

# 3. Later: tweak a template handler or a .wikitext file, then restart from stage 2
uv run mwbook-to-epub --workdir 32paths_work --start-from 2
```

The workdir is deliberately left behind so you can iterate on the hard part (stage 2) without re-downloading anything.

See `program_spec.md` for the full rules (templates, image handling, arrow removal, collapsible tables, etc.).

## Workdir layout (after a run)

```
32paths_work/
├── metadata.json          # chapters in order, image manifest, book info, cover choice
├── downloads/
│   ├── toc.wikitext
│   └── chapters/
│       ├── 32_Paths_of_Wisdom_(PF_Case).wikitext
│       └── Path_1_(32_Paths_PFC).wikitext
├── images/
│   ├── originals/
│   └── (chosen .webp or .jpg files, deduped)
├── xhtml/
│   ├── 001_Path_1.xhtml
│   └── ...
├── styles/
│   └── book.css           # master stylesheet (edit + re-run stage 3)
├── logs/
└── 32_Paths_of_Wisdom.epub
```

## Restartability (the whole point)

- Delete `xhtml/` + the .epub → re-run `--start-from 2`
- Hand-edit a generated .xhtml or `styles/book.css` → re-run `--stages 3`
- Edit a raw .wikitext in `downloads/` → re-run from 2
- Only stage 1 ever talks to the network (and it skips anything already present unless `--force`)

## Implementation status

This is under active development following the plan in the session notes. The first vertical slice (offline TOC parsing + skeleton CLI + one chapter through to a minimal EPUB) is the current focus.

## Cover Image Recovery (Important for Restartability)

Stage 1 tries to pick a cover using these rules (in order):
1. Any image whose filename or caption contains "cover" (case-insensitive).
2. The first right/center thumbnail that appears early in the TOC (good heuristic when there's a nice title-page image).
3. First image of any kind (weak fallback).

If it cannot find any image, or if it picks the wrong one, **you do not need to re-run Stage 1**.

Just edit `metadata.json` in your workdir and set:

```json
"cover_image": "ExactFilenameFromYourImagesDir.jpg"
```

Then run `--stages 3` (or `--start-from 3`). The value in `metadata.json` is the single source of truth for the cover from that point forward.

This was deliberately designed so ambiguous TOCs are easy to correct without losing all your downloaded chapters and images.
