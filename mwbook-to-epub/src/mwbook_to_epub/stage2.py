"""Stage 2: Wikitext → clean EPUB XHTML (the restartable core the user cares most about).

This module contains the WikitextConverter, which is the heart of the tool.
It is deliberately designed to be callable in isolation (given a chapter wikitext
+ context about the book) so you can tweak conversion rules and re-run just
stage 2 against an existing workdir or even raw files + the IMAGEs directory.
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path

import mwparserfromhell as mwp
from mwparserfromhell.nodes import (
    Node,
    Text,
    Wikilink,
    Template,
    Tag,
    Heading,
    ExternalLink,
)

from .models import ConversionContext, BookMetadata
from .templates import TEMPLATE_HANDLERS, render_template
from .toc import ensure_toc_json
from .utils import strip_last_parenthetical, safe_filename

log = logging.getLogger(__name__)


# Pre-compiled regexes for cheap pre-processing (do these before feeding to mwparser)
ARROW_NAV_RE = re.compile(
    r'^\s*&rarr;\s*\[\[[^\]]+\]\]\s*&rarr;\s*$', re.MULTILINE | re.IGNORECASE
)
CATEGORY_RE = re.compile(r'\[\[\s*Category:[^\]]+\]\]\s*$', re.MULTILINE | re.IGNORECASE)


class WikitextConverter:
    """Best-effort wikitext → EPUB-friendly XHTML converter.

    Designed for restartability: you can instantiate this, point it at raw
    wikitext + an images directory, and get usable .xhtml fragments without
    a full workdir.
    """

    def __init__(self, ctx: ConversionContext | None = None):
        self.ctx = ctx or ConversionContext()
        self._uses_rwt_qa = False  # set during render if we emit any rwt-qa collapsible divs

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def convert(self, wikitext: str, page_title: str) -> str:
        """Convert one chapter's wikitext into an XHTML body fragment.

        Returns the inner content suitable for <body>...</body> (or for
        rwt_epub's add_xhtml_body).
        """
        self._uses_rwt_qa = False

        # 1. Strip junk (arrow navigation paragraphs, [[Category:...]] lines, Generic Nav templates)
        #    while the wikitext still contains the raw markup these regexes look for.
        #    MUST run before _pre_expand_templates_and_links, because link simplification
        #    turns [[Target|Display]] into plain Display text and destroys the patterns.
        wikitext = self._preprocess(wikitext)

        # 2. Early pre-expansion of known templates (esp. Hebrew text) and wikilinks.
        #    Removes inner | from templates and links before table parsing and other
        #    structural work. This is the key enabler for reliable pipe tables.
        wikitext = self._pre_expand_templates_and_links(wikitext)

        # 3. Cite handling (benefits from templates already expanded inside <ref> bodies)
        wikitext = self._preprocess_cite(wikitext)

        # 4. (The old "cleaned" variable is no longer needed; the result of the three
        #    pre-steps above is what we parse.)
        cleaned = wikitext

        # 2. Parse
        parsed = mwp.parse(cleaned)

        # 3. Render
        parts: list[str] = []

        if self.ctx.emit_title_h1:
            # Prefer the nice display_title from the TOC (via metadata) when available.
            # Falls back to cleaning the raw page_title (for ad-hoc runs without full ctx).
            display = self.ctx.page_to_display.get(page_title)
            if not display:
                display = strip_last_parenthetical(page_title.replace("_", " "))
            parts.append(f"<h1>{html.escape(display)}</h1>\n")

        # === During-render structural list builder ===
        # Walk the nodes *as mwparserfromhell actually emits them* and emit
        # correct <ul>/<ol>/<dl> structures directly. This is the reliable path.
        # mwp produces:
        #   * / #  -> Tag(tag='li') with str(node) == '*' or '#', + following Text content
        #   ; / :  -> Tag(tag='dt') / Tag(tag='dd'), + following Text
        i = 0
        nodes = list(parsed.nodes)
        n = len(nodes)

        while i < n:
            node = nodes[i]

            if isinstance(node, Tag):
                marker = str(node).strip()
                tag_name = str(getattr(node, "tag", "")).lower()

                # Bullet / numbered list run (including nested * containing #)
                if marker in ("*", "#") or (tag_name == "li" and marker in ("*", "#")):
                    list_html, i, rem = self._collect_list(nodes, i)
                    if list_html:
                        parts.append(list_html)
                    if rem:
                        # Emit the split-off paragraph text after the list so the
                        # later paragraph wrapper can turn it into a proper <p>.
                        parts.append("\n\n" + rem)
                    continue

                # Definition list run (; : dt dd)
                if marker in (";", ":") or tag_name in ("dt", "dd"):
                    dl_html, i, rem = self._collect_definition_list(nodes, i)
                    if dl_html:
                        parts.append(dl_html)
                    if rem:
                        parts.append("\n\n" + rem)
                    continue

            # Normal / non-list content
            parts.append(self._render(node))
            i += 1

        body = "".join(parts).strip()

        # Ensure content immediately after a heading is treated as a new block
        # for paragraph wrapping / list recognition. This prevents text or lists
        # right after <h1> from being glued to the heading line and left unwrapped.
        body = re.sub(r'(</h[1-6]>)\n(?!\n)', r'\1\n\n', body)

        # Light post-clean (safe)
        body = re.sub(r"\n{3,}", "\n\n", body)

        # === Proper paragraph wrapping ===
        # Split on blank lines and treat complete <figure> / list / dl blocks as hard separators.
        # This prevents the splitter from mangling content *inside* lists or turning list
        # HTML into paragraph text.
        def _wrap_paragraphs(text: str) -> str:
            figure_placeholder = '\x00FIGURE\x00'
            list_placeholder = '\x00LIST\x00'
            figures = []
            lists = []

            def _extract_figure(m):
                figures.append(m.group(0))
                return figure_placeholder + str(len(figures)-1) + figure_placeholder

            def _extract_list(m):
                lists.append(m.group(0))
                return list_placeholder + str(len(lists)-1) + list_placeholder

            text = re.sub(r'<figure\b[^>]*>.*?</figure>', _extract_figure, text, flags=re.DOTALL | re.IGNORECASE)
            # Protect complete lists and definition lists so their internal newlines and
            # structure are never touched by the blank-line paragraph logic.
            text = re.sub(r'<(?:ul|ol|dl)\b[^>]*>.*?</(?:ul|ol|dl)>', _extract_list, text, flags=re.DOTALL | re.IGNORECASE)

            blocks = re.split(r'\n\s*\n+', text.strip())
            wrapped = []
            block_starts = ('<h1', '<h2', '<h3', '<h4', '<table', '<ul', '<ol', '<dl', '<blockquote', '<div', '<pre', '<figure')

            for block in blocks:
                b = block.strip()
                if not b:
                    continue

                def _restore(m):
                    idx = int(m.group(1))
                    return figures[idx]
                b = re.sub(figure_placeholder + r'(\d+)' + figure_placeholder, _restore, b)

                def _restore_list(m):
                    idx = int(m.group(1))
                    return lists[idx]
                b = re.sub(list_placeholder + r'(\d+)' + list_placeholder, _restore_list, b)

                lower = b.lower()
                if any(lower.startswith(tag) for tag in block_starts):
                    wrapped.append(b)
                else:
                    b = re.sub(r'\s*\n\s*', ' ', b)
                    wrapped.append(f"<p>{b}</p>")

            return "\n\n".join(wrapped)

        body = _wrap_paragraphs(body)

        # All list structure is now produced by the during-render collectors
        # (_collect_list using prefix+stack, _collect_definition_list).
        # No post-processing list repairs remain.

        # Safety net: expand any remaining literal {{BibleVerse|...}} that didn't get caught
        # (can happen inside blockquotes or other complex structures)
        def _expand_bibleverse(m):
            book = m.group(1).strip()
            verse = m.group(2).strip()
            label = m.group(3).strip() if m.group(3) else f"{book}:{verse}"
            return html.escape(label)

        body = re.sub(
            r'\{\{\s*BibleVerse\s*\|\s*([^|]+)\|\s*([^|}|]+)(?:\|([^}]+))?\s*\}\}',
            _expand_bibleverse,
            body,
            flags=re.IGNORECASE
        )

        # Final safety net for entity double-escaping (run early)
        body = re.sub(r'&amp;(#\w+;|\w+;)', r'&\1', body)

        # Ultimate normalization pass for entities
        body = self._normalize_entities(body)

        # Last-chance demotion for any wiki links that slipped through
        def _demote_remaining_wikilinks(m):
            target = m.group(1).strip()
            display = m.group(2).strip() if m.group(2) else target
            log.warning("Final demotion of unresolved wiki link: [[%s]]", target)
            return html.escape(display)

        body = re.sub(
            r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]',
            _demote_remaining_wikilinks,
            body
        )

        # Fix common bad nesting from paragraph wrapping (e.g. </blockquote></p>)
        body = re.sub(r'(</(blockquote|div|table|ul|ol|dl|figure)>)(\s*</p>)', r'\3\1', body, flags=re.IGNORECASE)

        # Unescape raw HTML tags that got turned into entities (both named and numeric forms).
        # This is the main cause of mangled output in files that contain raw HTML from old EPUB imports.
        def _unescape_html_tags(m):
            tag = m.group(1)
            attrs = m.group(2) or ''
            is_self_closing = bool(m.group(3))
            slash = ' /' if is_self_closing else ''
            return f"<{tag}{attrs}{slash}>"

        # Controlled final recovery pass for raw HTML tags.
        # We are deliberately conservative here to avoid turning literal
        # "<" or "&" (that should stay escaped) back into raw characters.

        # First, do a limited unescape only on things that look like they could be tags
        def _safe_unescape(m):
            candidate = m.group(0)
            # Only unescape if it looks like a plausible tag (word characters after < or &lt;)
            if re.match(r'^(?:&lt;|&#60;|&#x3C;)\s*/?\w', candidate, re.I):
                return html.unescape(candidate)
            return candidate

        body = re.sub(r'(?:&lt;|&#60;|&#x3C;).*?(?:&gt;|&#62;|&#x3E;)', _safe_unescape, body, flags=re.IGNORECASE)

        # Then apply our existing tag recovery (which is now safer because of the above filter)
        body = re.sub(
            r'(?:&lt;|&#60;|&#x3C;)(/?\w+)([^&]*?)(/?)(?:&gt;|&#62;|&#x3E;)',
            _unescape_html_tags,
            body,
            flags=re.IGNORECASE
        )

        # Final safety sweep: escape any remaining dangerous characters that are not inside tags
        # This catches literal < and & that should have been escaped (e.g. "6<h spell" or raw &amp;)
        def _escape_stray_chars(text):
            # This is a simplified pass — for full correctness we'd need a real HTML parser,
            # but this helps catch the obvious cases the user reported.
            result = []
            i = 0
            while i < len(text):
                if text[i] == '<':
                    # Check if this starts a tag
                    if re.match(r'<\s*/?\w', text[i:]):
                        # Looks like a tag start — copy until we find >
                        j = text.find('>', i)
                        if j != -1:
                            result.append(text[i:j+1])
                            i = j + 1
                            continue
                    # Not a tag — escape it
                    result.append('&lt;')
                    i += 1
                elif text[i] == '&':
                    # Check if this is already an entity
                    if re.match(r'&\w+;|&#\d+;|&#x[0-9a-fA-F]+;', text[i:]):
                        # Copy the entity
                        j = text.find(';', i)
                        if j != -1:
                            result.append(text[i:j+1])
                            i = j + 1
                            continue
                    # Not an entity — escape it
                    result.append('&amp;')
                    i += 1
                else:
                    result.append(text[i])
                    i += 1
            return ''.join(result)

        body = _escape_stray_chars(body)

        # Final aggressive repair for any double-escaped numeric or named entities.
        # This catches cases like &amp;#x05d7; that can be produced when mwparserfromhell
        # splits injected HTML (from early template expansion) into per-character nodes
        # inside <span class="hebrew-text"> etc., especially in the cite reference path.
        # Must run after _escape_stray_chars (which can re-damage entities it doesn't perfectly recognize).
        body = re.sub(r'&amp;#(x[0-9a-fA-F]+|\d+);', r'&#\1;', body)
        body = re.sub(r'&amp;(#\w+;|\w+;)', r'&\1', body)

        # One last normalize pass so any &times; (or other entities we added to the
        # map) that were repaired from &amp;times; form get converted to numeric.
        body = self._normalize_entities(body)

        # Final whitespace normalization to match the exact style of the LIST_TESTS
        # expectations: single blank line between top-level blocks, no blank line
        # immediately after <h1> (or other headings) when the next content is a block.
        body = re.sub(r'\n{3,}', '\n\n', body)
        body = re.sub(r'(</h[1-6]>)\n\n(<[a-z/])', r'\1\n\2', body, flags=re.IGNORECASE)

        # If this chapter used any rwt-qa collapsible sections, inject the tiny
        # show/hide script into the body fragment (it will end up in <body> of
        # the wrapped XHTML). We only do this for chapters that actually need it.
        if getattr(self, '_uses_rwt_qa', False):
            script = '''<script>
function rwtShowHide(element) {
    element.classList.toggle('rwtShown');
}
</script>
'''
            body = script + body
            self._uses_rwt_qa = False

        return body

    # ------------------------------------------------------------------ #
    # Pre-processing
    # ------------------------------------------------------------------ #

    def _preprocess(self, text: str) -> str:
        """Remove things that have no place in an EPUB chapter."""
        # Remove the classic "→ [[Next Chapter]] →" nav lines (and the category line)
        text = ARROW_NAV_RE.sub("", text)
        text = CATEGORY_RE.sub("", text)

        # Remove the Generic WikiBook Nav template entirely (and any *Nav at top)
        text = re.sub(
            r"\{\{\s*Generic WikiBook Nav[^}]*\}\}\s*",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(
            r"^\s*\{\{\s*[^}]+\bNav\b[^}]*\}\}\s*",
            "",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        # New rule requested by user: Remove "arrow navigation" paragraphs.
        # These are paragraphs that begin and end with &larr; or &rarr; (or the HTML entities)
        # and contain a wikilink. They were used for "back to previous / next chapter" navigation.
        # We remove the entire paragraph and log it.
        arrow_nav_para = re.compile(
            r'^\s*(?:&larr;|&rarr;|&#x2190;|&#x2192;)\s*'
            r'\[\[[^\]]+\]\]'
            r'.*?'
            r'(?:&larr;|&rarr;|&#x2190;|&#x2192;)\s*$',
            re.MULTILINE | re.DOTALL | re.IGNORECASE
        )

        def _remove_arrow_nav(m):
            para = m.group(0).strip()
            # Log at WARNING level so it is very visible
            log.warning("Removed wiki navigation paragraph: %s", para[:120])
            return ""

        text = arrow_nav_para.sub(_remove_arrow_nav, text)

        return text

    def _pre_expand_templates_and_links(self, text: str) -> str:
        """
        Early expansion of *templates* to remove internal vertical bars.

        Done before structural parsing (especially tables). We deliberately
        leave wikilinks alone here so that normal body [[Internal Page|text]]
        nodes survive and can be turned into real <a href="correct-numbered.xhtml">
        links using the metadata mappings.  Only templates (the main source of
        | inside table cells) are expanded globally.
        """
        if not text or '{{' not in text:
            return text

        def expand_template(m):
            full = m.group(0)
            name = m.group(1).strip().lower().replace(' ', '').replace('_', '')
            params_str = m.group(2)

            params = {}
            pos_idx = 1
            for p in re.split(r'\s*\|\s*', params_str):
                if not p:
                    continue
                if '=' in p:
                    k, v = p.split('=', 1)
                    params[k.strip().lower()] = v.strip()
                else:
                    params[str(pos_idx)] = p.strip()
                    pos_idx += 1

            try:
                rendered = render_template(name, params, ctx=self.ctx)
                return rendered
            except Exception:
                return full

        text = re.sub(r'\{\{\s*([^\|\}]+?)\s*\|(.*?)\}\}', expand_template, text, flags=re.DOTALL)
        return text

    def _preprocess_cite(self, text: str) -> str:
        """
        Support for MediaWiki Cite extension in two common styles:

        1. Named references (original style, used in 32 Paths book and test011):
           - <ref name="foo">content</ref> or <ref name="foo"/>
           - Definitions collected from inside <references>...</references>

        2. Anonymous inline references (used in "A Depth of Beginning"):
           - <ref>content here</ref>  (text lives at the citation site)
           - Triggered by a bare <references/> (self-closing) at the bottom.

        Both styles produce the same <sup class="reference"> links and
        <ol class="references"> list at the end. A given page is not expected
        to mix the two styles.
        """
        if "<ref" not in text.lower() and "<references" not in text.lower():
            return text

        # --- Named reference support (old style) ---
        ref_defs: dict[str, str] = {}
        ref_order: list[str] = []   # for named refs from <references> block

        def extract_named_defs(m):
            inner = m.group(1) or ""
            for rm in re.finditer(r'<ref\s+name=["\']([^"\']+)["\']\s*>(.*?)</ref>', inner, re.I | re.DOTALL):
                name = rm.group(1).strip()
                content = rm.group(2).strip()
                if name and name not in ref_defs:
                    ref_defs[name] = content
                    ref_order.append(name)
            return ""

        text = re.sub(r'<references[^>]*>(.*?)</references\s*>', extract_named_defs, text, flags=re.I | re.DOTALL)

        # --- Anonymous inline ref support (new style) ---
        # Collect <ref>content</ref> that have no name= attribute.
        anon_contents: list[str] = []
        anon_id_map: dict[int, str] = {}   # occurrence index -> synthetic name

        def collect_anonymous_refs(m):
            content = m.group(1).strip()
            idx = len(anon_contents)
            anon_contents.append(content)
            synthetic_name = f"ref{idx + 1}"
            anon_id_map[idx] = synthetic_name
            # Leave a marker so we can replace it in the next step
            return f'__ANON_REF_{idx}__'

        text = re.sub(r'<ref\s*>(.*?)</ref>', collect_anonymous_refs, text, flags=re.I | re.DOTALL)

        # --- Replace all reference call sites with superscript links ---
        cite_num: dict[str, int] = {}
        counter = 0

        def make_sup(name: str, is_anon: bool = False) -> str:
            nonlocal counter
            if name not in cite_num:
                counter += 1
                cite_num[name] = counter
            num = cite_num[name]
            if is_anon:
                # Use simpler ids for anonymous refs
                return f'<sup id="cite_ref-{name}-{num}" class="reference"><a href="#cite_note-{name}-{num}">[{num}]</a></sup>'
            else:
                return f'<sup id="cite_ref-{name}_{num}-0" class="reference"><a href="#cite_note-{name}-{num}">[{num}]</a></sup>'

        def replace_named_ref(m):
            name = m.group(1).strip()
            return make_sup(name, is_anon=False)

        text = re.sub(r'<ref\s+name=["\']([^"\']+)["\']\s*/?\s*>', replace_named_ref, text, flags=re.I)

        # Now turn the anonymous markers into real sups
        def replace_anon_marker(m):
            idx = int(m.group(1))
            synthetic_name = anon_id_map.get(idx, f"ref{idx+1}")
            return make_sup(synthetic_name, is_anon=True)

        text = re.sub(r'__ANON_REF_(\d+)__', replace_anon_marker, text)

        # --- Emit the references list ---
        # Priority: if we saw any anonymous refs, emit them when we see <references/>
        # Otherwise fall back to the classic named-defs-in-block behavior.

        if anon_contents:
            # New anonymous style: look for bare <references/>
            def emit_anon_list(m):
                notes = []
                has_notes_heading = (
                    re.search(r'<h2[^>]*>\s*Notes\s*</h2>', text, re.I) or
                    re.search(r'^==\s*Notes\s*==', text, re.M | re.I)
                )
                if not has_notes_heading:
                    notes.append('<h2>  Notes  </h2>')
                notes.append('<ol class="references">')
                for idx, content in enumerate(anon_contents):
                    num = idx + 1
                    synthetic_name = anon_id_map.get(idx, f"ref{num}")
                    try:
                        rendered = "".join(self._render(n) for n in mwp.parse(content).nodes)
                    except Exception:
                        rendered = html.escape(content)
                    notes.append(
                        f'<li id="cite_note-{synthetic_name}-{num}">'
                        f'<a href="#cite_ref-{synthetic_name}-{num}">↑</a> {rendered}</li>'
                    )
                notes.append('</ol>')
                return "\n".join(notes)

            text = re.sub(r'<references\s*/\s*>', emit_anon_list, text, flags=re.I)

        elif ref_defs:
            # Classic named style (from <references> block)
            notes = []
            has_notes_heading = (
                re.search(r'<h2[^>]*>\s*Notes\s*</h2>', text, re.I) or
                re.search(r'^==\s*Notes\s*==', text, re.M | re.I)
            )
            if not has_notes_heading:
                notes.append('<h2>  Notes  </h2>')
            notes.append('<ol class="references">')
            for idx, name in enumerate(ref_order, 1):
                raw = ref_defs.get(name, "")
                try:
                    rendered = "".join(self._render(n) for n in mwp.parse(raw).nodes)
                except Exception:
                    rendered = html.escape(raw)
                notes.append(f'<li id="cite_note-{name}-{idx}"><a href="#cite_ref-{name}_{idx}-0">↑</a> {rendered}</li>')
            notes.append('</ol>')
            text = text.rstrip() + "\n\n" + "\n".join(notes) + "\n"

        return text

    # ------------------------------------------------------------------ #
    # Core recursive renderer
    # ------------------------------------------------------------------ #

    def _render(self, node: Node) -> str:
        """Dispatch to the right renderer for this node."""
        if isinstance(node, Text):
            return self._render_text(node)
        if isinstance(node, Wikilink):
            return self._render_wikilink(node)
        if isinstance(node, Template):
            return self._render_template(node)
        if isinstance(node, Tag):
            return self._render_tag(node)
        if isinstance(node, Heading):
            return self._render_heading(node)
        if isinstance(node, ExternalLink):
            return self._render_external_link(node)

        # Basic list / list item support (mwparserfromhell often gives us Tag nodes for these)
        if isinstance(node, Tag):
            tag_name = str(node.tag).lower()
            if tag_name in ("ul", "ol"):
                inner = "".join(self._render(n) for n in getattr(node, "contents", []))
                return f"<{tag_name}>{inner}</{tag_name}>"
            if tag_name == "li":
                raw = "".join(self._render(n) for n in getattr(node, "contents", []))
                text = re.sub(r'^\s*[*#]\s*', '', raw)
                return f"<li>{text}</li>"
            if tag_name in ("dl", "dt", "dd"):
                inner = "".join(self._render(n) for n in getattr(node, "contents", []))
                return f"<{tag_name}>{inner}</{tag_name}>"

        # Fallback for other containers
        if hasattr(node, "contents"):
            try:
                return "".join(self._render(n) for n in node.contents.nodes)  # type: ignore[attr-defined]
            except Exception:
                pass

        # Last resort
        return html.escape(str(node))

    def _render_text(self, node: Text) -> str:
        """Safely escape genuine text content for XHTML.

        We are conservative here:
        - Only Text nodes should reach this function.
        - We always produce valid escaped output for <, >, &, and ".
        - We do NOT try to "recover" tags here — that responsibility belongs to
          the Tag rendering path and the final cleanup pass.
        """
        raw = str(node)

        # Normalize known named entities to numeric (safer for strict XHTML)
        raw = self._normalize_entities(raw)

        # Protect any entities that are already correctly formed
        protected = re.sub(r'(&[#\w]+;)', lambda m: f'\x00ENT{m.group(1)}\x00', raw)

        # Standard safe escaping
        escaped = html.escape(protected, quote=True)

        # Restore protected entities
        return re.sub(r'\x00ENT(&[#\w]+;)\x00', r'\1', escaped)

    # ------------------------------------------------------------------ #
    # Wikilinks (the most important case for images + internal links)
    # ------------------------------------------------------------------ #

    def _render_wikilink(self, node: Wikilink) -> str:
        title = str(node.title).strip()
        text_part = str(node.text).strip() if node.text else ""

        lower_title = title.lower()

        # --- IMAGE / FILE / MEDIA wikilinks ---
        if lower_title.startswith(("file:", "image:", "media:")):
            return self._render_file_wikilink(title, text_part)

        # --- Normal wikilink ---
        # Decide if this is an internal book link
        target = title.replace(" ", "_")
        display = text_part or title.replace("_", " ")

        if self._is_internal_link(target):
            # We will later map this to the correct xhtml filename.
            # For now we use a placeholder href that stage 3 or a post-pass can fix,
            # or we can look it up if we have the chapter list with filenames.
            href = self._guess_xhtml_filename(target)
            return f'<a href="{href}">{html.escape(display)}</a>'

        # Not in the book → plain text (and log it so the user can review)
        log.warning("Demoting external wiki link to plain text: [[%s]]", title)
        return html.escape(display)

    def _render_file_wikilink(self, title: str, options_str: str) -> str:
        """Turn [[File:Foo.jpg|thumb|right|Caption]] into <figure>...</figure>."""
        # Normalize the filename (strip File: prefix)
        filename = title.split(":", 1)[1] if ":" in title else title
        filename = filename.strip()

        # Parse options
        opts = [o.strip() for o in options_str.split("|") if o.strip()] if options_str else []

        # Last option that is not a known keyword/size is usually the caption
        caption = ""
        position = "center"
        size = ""
        is_thumb = False

        known_keywords = {"thumb", "thumbnail", "frame", "frameless", "upright"}

        for opt in opts:
            opt_lower = opt.lower()
            if opt_lower in known_keywords or opt_lower.startswith("upright"):
                if "thumb" in opt_lower:
                    is_thumb = True
                continue
            if opt_lower in ("left", "right", "center", "none"):
                position = opt_lower
                continue
            if re.match(r"^\d+px$", opt) or re.match(r"^\d+x\d+px$", opt):
                size = opt
                continue
            # Everything else is caption (or part of it)
            if caption:
                caption += " | " + opt
            else:
                caption = opt

        # Resolve to the actual file we will use in the EPUB
        chosen = self.ctx.image_map.get(filename, filename)

        # For development against the raw IMAGEs directory, allow the converter
        # to find the file even if it hasn't been "chosen + renamed" yet.
        img_src = self._resolve_image_src(chosen, filename)

        # Build the figure
        classes = ["book-image"]
        if position == "right":
            classes.append("img-right")
        elif position == "left":
            classes.append("img-left")
        else:
            classes.append("img-center")

        if is_thumb:
            classes.append("thumb")

        fig_class = " ".join(classes)
        style = ""
        if size and "px" in size:
            # Very crude inline width for now; real control is in CSS
            w = size.replace("px", "").split("x")[0]
            style = f' style="max-width:{w}px"'

        img = f'<img src="{img_src}" alt="{html.escape(caption or filename)}"{style} />'

        if caption:
            cap = f"<figcaption>{html.escape(caption)}</figcaption>"
        else:
            cap = ""

        # Always ensure a paragraph break after a figure so that following
        # text (common when images are right next to paragraph start in wikitext)
        # doesn't get merged incorrectly during post-processing.
        return f'<figure class="{fig_class}">\n  {img}\n  {cap}\n</figure>\n\n'

    def _resolve_image_src(self, chosen_name: str, original_name: str) -> str:
        """Return the src= value we will put in the XHTML.

        During development against example_inputs/IMAGEs we return a relative
        path that will work when the generated xhtml is viewed next to the images.
        In a real workdir this will become the OEBPS/Images/ path the epub lib expects.
        """
        if self.ctx.images_root and (self.ctx.images_root / chosen_name).exists():
            # For easy manual inspection during development
            return f"../images/{chosen_name}"  # or just the filename; adjust as needed

        # Fallback: assume the final EPUB layout
        return f"../Images/{chosen_name}"

    def _is_internal_link(self, target: str) -> bool:
        """Is this wikilink target one of the pages that belong to the book?"""
        if self.ctx.page_to_xhtml:
            # Exact match on the authoritative page titles from metadata
            t = target.strip()
            if t in self.ctx.page_to_xhtml:
                return True
            t2 = t.replace("_", " ")
            if t2 in self.ctx.page_to_xhtml:
                return True
            t3 = t.replace(" ", "_")
            if t3 in self.ctx.page_to_xhtml:
                return True
            return False
        if not self.ctx.book_pages:
            return False
        # Fallback for ad-hoc runs
        candidates = {target, target.replace("_", " "), target.replace(" ", "_")}
        return bool(candidates & self.ctx.book_pages)

    def _guess_xhtml_filename(self, target: str) -> str:
        """Return the final xhtml filename for an internal book link, using the
        exact names that Stage 1 computed from the TOC (the numbered + nice-title
        versions the user likes). Falls back to a slugified guess for unknown pages.
        """
        t = target.strip()
        # Direct lookup in the authoritative map (preferred)
        if self.ctx.page_to_xhtml:
            for cand in (t, t.replace("_", " "), t.replace(" ", "_")):
                if cand in self.ctx.page_to_xhtml:
                    return self.ctx.page_to_xhtml[cand]

        # Old fallback behavior (used when running without full metadata context)
        clean = strip_last_parenthetical(t.replace("_", " "))
        # Use a longer limit here because there is no numeric prefix to guarantee uniqueness
        slug = safe_filename(clean, max_length=60)
        return f"{slug}.xhtml"

    # ------------------------------------------------------------------ #
    # Templates
    # ------------------------------------------------------------------ #

    def _render_template(self, node: Template) -> str:
        name = str(node.name).strip().lower()

        # Special fast path for anything ending in "Nav" (already partially stripped,
        # but be defensive)
        if name.endswith("nav"):
            return ""

        params: dict[str, str] = {}
        for p in node.params:
            key = str(p.name).strip() if p.name else ""
            val = str(p.value).strip()
            if key:
                params[key] = val
            else:
                # Positional parameters
                idx = len([k for k in params if k.isdigit()]) + 1
                params[str(idx)] = val

        # Also support the common "1", "2", "3" style that some templates use
        if not params:
            for i, p in enumerate(node.params, 1):
                params[str(i)] = str(p.value).strip()

        try:
            return render_template(name, params, ctx=self.ctx)
        except Exception as e:
            log.warning("Template handler failed for {{%s}}: %s", name, e)
            return ""

    # ------------------------------------------------------------------ #
    # Raw HTML tags (<sup>, tables, gallery, div, span, q, etc.)
    # ------------------------------------------------------------------ #

    def _render_tag(self, node: Tag) -> str:
        tag = str(node.tag).lower()

        # Self-closing tags
        if node.self_closing:
            attrs = self._render_attrs(node.attributes)
            return f"<{tag}{attrs} />"

        # Gallery is special
        if tag == "gallery":
            return self._render_gallery(node)

        # Table handling (including mw-collapsible)
        if tag == "table":
            return self._render_table(node)

        # Generic container / inline tags we want to keep
        attrs = self._render_attrs(node.attributes)

        # Special handling for collapsible tables / divs (mw-collapsible)
        cls = ""
        if node.has("class"):
            try:
                cls = str(node.get("class").value or "")
            except Exception:
                cls = ""
        if "mw-collapsible" in cls:
            # Turn it into the rwt-qa pattern the user likes for EPUB
            self._uses_rwt_qa = True
            inner = "".join(self._render(n) for n in getattr(node, "contents", []))
            return f'<div class="rwt-qa" onclick="rwtShowHide(this)">{inner}</div>'

        # Recurse into children
        inner = "".join(self._render(n) for n in getattr(node, "contents", []))
        return f"<{tag}{attrs}>{inner}</{tag}>"

    def _render_attrs(self, attributes) -> str:
        """Robustly turn mwparserfromhell attribute objects (or raw strings) into HTML."""
        if not attributes:
            return ""
        out = []
        for attr in attributes:
            if isinstance(attr, str):
                # Sometimes we get raw strings like ' class="wikitable"'
                out.append(attr.strip())
                continue
            try:
                name = str(attr.name).strip()
                if getattr(attr, "value", None) is None:
                    out.append(name)
                else:
                    val = html.escape(str(attr.value).strip())
                    out.append(f'{name}="{val}"')
            except Exception:
                continue
        return " " + " ".join(out) if out else ""

    def _render_gallery(self, node: Tag) -> str:
        """Render a <gallery> as a simple centered vertical stack of images."""
        contents = str(node.contents or "").strip()
        lines = [l.strip() for l in contents.splitlines() if l.strip()]

        figures = []
        for line in lines:
            # Lines look like: File:Foo.svg|Caption or just File:Foo.svg
            if "|" in line:
                fname, cap = line.split("|", 1)
            else:
                fname, cap = line, ""
            fname = fname.strip()
            if fname.lower().startswith("file:"):
                fname = fname.split(":", 1)[1].strip()

            chosen = self.ctx.image_map.get(fname, fname)
            src = self._resolve_image_src(chosen, fname)
            cap_html = f"<figcaption>{html.escape(cap)}</figcaption>" if cap else ""
            figures.append(
                f'<figure class="img-center img-gallery">\n'
                f'  <img src="{src}" alt="{html.escape(cap or fname)}" />\n'
                f"  {cap_html}\n"
                f"</figure>"
            )

        return '<div class="image-gallery">\n' + "\n".join(figures) + "\n</div>\n\n"

    def _render_table(self, node: Tag) -> str:
        """Improved table rendering.

        For wikitext pipe tables (most common in these books), we do a proper
        lightweight parse so we get clean <tr><td rowspan=...> with templates
        expanded inside cells.
        """
        attrs = self._render_attrs(node.attributes)

        # Get the raw source inside the table tag
        contents = getattr(node, "contents", None)
        table_source = str(contents) if contents else ""

        # Simplify any remaining wikilinks *inside the table only*. This removes
        # | from [[Target|Display]] so the pipe-table cell parser isn't confused,
        # while leaving normal body wikilinks intact for proper internal linking.
        def _simplify_links_in_fragment(s: str) -> str:
            def simp(m):
                tgt = m.group(1).strip()
                disp = m.group(2).strip() if m.group(2) else tgt.replace("_", " ")
                return disp
            return re.sub(r'\[\[([^\|\]]+?)(?:\|([^\]]+?))?\]\]', simp, s)

        table_source = _simplify_links_in_fragment(table_source)

        cls = ""
        if node.has("class"):
            try:
                cls = str(node.get("class").value or "")
            except Exception:
                cls = ""

        # Skip obvious infobox/nav tables at the top of pages
        if "infobox" in cls.lower():
            return ""

        # Handle 1-row, 1-column "mw-collapsible" tables by converting to rwt-qa div
        # (as specified for hint boxes etc. in KQ3 and similar books). Multi-cell
        # collapsible tables are left as normal tables.
        if "mw-collapsible" in cls.lower():
            looks_like_pipe_table = (
                "wikitable" in cls.lower()
                or re.search(r'^\s*\|[-}]', table_source, re.MULTILINE)
                or "||" in table_source[:200]
            )
            if looks_like_pipe_table:
                table_html = self._render_pipe_table(table_source, base_attrs=attrs)
            else:
                raw_inner = "".join(self._render(n) for n in getattr(node, "contents", []))
                table_html = f"<table{attrs}>{raw_inner}</table>"

            # Count cells in the rendered output (only data cells, not captions)
            import re as _re
            cells = _re.findall(r'<t[dh]\b[^>]*>.*?</t[dh]>', table_html, _re.DOTALL | _re.IGNORECASE)
            if len(cells) <= 1:
                # 1-cell (or empty) collapsible -> rwt-qa interactive div
                self._uses_rwt_qa = True
                cell_match = _re.search(r'<t[dh]\b[^>]*>(.*?)</t[dh]>', table_html, _re.DOTALL | _re.IGNORECASE)
                inner = cell_match.group(1).strip() if cell_match else table_html
                # Per the documented conversion, wrap the (table cell) content in <p>
                # so that the existing .rwt-qa > p CSS rules apply.
                return f'<div class="rwt-qa" onclick="rwtShowHide(this)"><p>{inner}</p></div>'
            else:
                # Multi-cell collapsible table: return as-is (normal table)
                return table_html

        # If this looks like a classic wikitext pipe table, use the good parser.
        # (The opening "{|" line is often absorbed into the Tag attributes,
        # so we look for wikitable class or typical pipe markers in the content.)
        looks_like_pipe_table = (
            "wikitable" in cls.lower()
            or re.search(r'^\s*\|[-}]', table_source, re.MULTILINE)
            or "||" in table_source[:200]
        )
        if looks_like_pipe_table:
            return self._render_pipe_table(table_source, base_attrs=attrs)

        # Fallback for HTML-written tables or weird cases
        raw_inner = "".join(self._render(n) for n in getattr(node, "contents", []))
        return f"<table{attrs}>{raw_inner}</table>"

    def _render_pipe_table(self, source: str, base_attrs: str = "") -> str:
        """Lightweight but effective parser for wikitext pipe tables.

        Row boundaries are trivial: a MediaWiki table always uses |- between rows.
        We accumulate cells into the current row until we see |- (flush + new row)
        or |} (flush + end). No column-count heuristics, no early flushes.
        The only real ambiguity is attributes | content splitting on cell lines.
        """
        lines = source.splitlines()
        rows_html: list[str] = []
        current_row_cells: list[str] = []
        caption_html = ""

        def flush_row():
            nonlocal current_row_cells
            if current_row_cells:
                rows_html.append("<tr>" + "".join(current_row_cells) + "</tr>")
            current_row_cells = []

        def _ws_only(s: str) -> bool:
            return not s or all(c.isspace() for c in s)

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i].rstrip()
            deindented = line.lstrip()

            if deindented.startswith("{|"):
                i += 1
                continue
            if deindented.startswith("|}"):
                flush_row()
                break

            # Table caption: |+ Caption text (can contain templates)
            if deindented.startswith("|+"):
                cap_text = deindented[2:].strip()
                try:
                    cap_rendered = "".join(self._render(n) for n in mwp.parse(cap_text).nodes)
                except Exception:
                    cap_rendered = html.escape(cap_text)
                caption_html = f"<caption>{cap_rendered}</caption>\n"
                i += 1
                continue

            if deindented.startswith("|-"):
                flush_row()
                i += 1
                continue

            if deindented.startswith(("|", "!")):
                is_header = deindented.startswith("!")
                # Everything after the opening | or ! (preserve ws for ws-only blank cells)
                after_leader = deindented[1:]
                if is_header:
                    after_leader = after_leader.replace('!!', '||')

                cell_specs = re.split(r'\|\|', after_leader)

                for raw_spec in cell_specs:
                    if _ws_only(raw_spec):
                        # Blank cell written as |   or |  &nbsp; or |  \xa0 etc. (one-cell-per-line style)
                        current_row_cells.append(self._parse_pipe_cell("", is_header=is_header))
                        continue

                    # Hand the spec (with its internal | for attrs if present) to the cell parser.
                    # After early template/link expansion, any | here is either structural || (already split)
                    # or the attrs | content separator the user described.
                    spec = raw_spec.strip()
                    current_row_cells.append(self._parse_pipe_cell(spec, is_header=is_header))

                i += 1
                continue

            i += 1

        flush_row()

        table_content = "\n".join(rows_html)
        return f"<table{base_attrs}>\n{caption_html}<tbody>\n{table_content}\n</tbody>\n</table>"

    def _parse_pipe_cell(self, cell_spec: str, is_header: bool = False) -> str:
        """
        Parse one cell spec (plain content, or "attributes | content" per MediaWiki).

        This is the single place that resolves the only real ambiguity the user
        identified: attribute prefix before the | vs. plain cell text.
        After _pre_expand_templates_and_links, remaining | are reliable signals.
        """
        spec = (cell_spec or "").strip()
        attrs_part = ""
        content_part = spec

        if '|' in spec:
            protected = re.sub(r'\[\[[^\]]+\]\]', lambda m: '\x00LINK\x00' + m.group(0) + '\x00', spec)
            if '|' in protected:
                left, right = protected.split('|', 1)
                left_c = left.replace('\x00LINK\x00', '').replace('\x00', '').strip()
                right_c = right.replace('\x00LINK\x00', '').replace('\x00', '').strip()
                # The decision: left side is attributes iff it has = or a known table attr keyword.
                # This correctly handles: colspan="4" | text , rowspan="2" | text , and bare | content.
                if '=' in left_c or re.search(r'(?i)^\s*(rowspan|colspan|scope|class|style|align|valign|id|headers)\b', left_c):
                    attrs_part = left_c
                    content_part = right_c

        rowspan = ""
        colspan = ""
        if attrs_part:
            rs = re.search(r'rowspan\s*=\s*["\']?(\d+)', attrs_part, re.I)
            if rs:
                rowspan = f' rowspan="{rs.group(1)}"'
            cs = re.search(r'colspan\s*=\s*["\']?(\d+)', attrs_part, re.I)
            if cs:
                colspan = f' colspan="{cs.group(1)}"'

        tag = "th" if is_header else "td"

        clean = self._clean_cell_garbage_raw(content_part)
        clean = self._normalize_entities(clean)
        clean = html.unescape(clean)

        if not clean or all(c.isspace() for c in clean):
            rendered = "&#160;"
        else:
            try:
                parsed_cell = mwp.parse(clean)
                rendered = "".join(self._render(n) for n in parsed_cell.nodes)
            except Exception as e:
                log.debug("Cell parse failed: %s", e)
                rendered = html.escape(clean)

        # Final safety: any cell whose rendered content is empty or nbsp must be &#160;
        if not rendered or not rendered.strip() or rendered.strip() in ('&nbsp;', ' ', '\xa0', '&#160;'):
            rendered = '&#160;'

        return f"<{tag}{rowspan}{colspan}>{rendered}</{tag}>"

    def _clean_cell_garbage(self, html_fragment: str) -> str:
        """Remove or simplify some of the ugly HTML trash that leaked into the wikitext (post-render version)."""
        html_fragment = re.sub(r'<p class="mw-empty-elt">\s*</p>', '', html_fragment)
        html_fragment = re.sub(r'<p class="calibre\d*">', '<span class="calibre-garbage">', html_fragment)
        html_fragment = re.sub(r'</p>', '</span>', html_fragment)
        html_fragment = re.sub(r'</?p[^>]*>', '', html_fragment)
        return html_fragment

    def _clean_cell_garbage_raw(self, wikitext: str) -> str:
        """Remove known HTML garbage from the raw wikitext *before* mwparserfromhell sees it."""
        # These were pasted in from an old EPUB and pollute the table cells
        wikitext = re.sub(r'</?p[^>]*class=["\']?(?:mw-empty-elt|calibre\d*)["\']?[^>]*>', '', wikitext, flags=re.I)
        wikitext = re.sub(r'</?p>', '', wikitext)
        # Collapse multiple spaces that sometimes appear
        wikitext = re.sub(r' {2,}', ' ', wikitext)
        return wikitext

    # ------------------------------------------------------------------ #
    # Entity normalization (critical for strict XHTML in EPUB)
    # ------------------------------------------------------------------ #

    _ENTITY_MAP = {
        '&nbsp;': '&#160;',
        '&hellip;': '&#8230;',
        '&mdash;': '&#8212;',
        '&ndash;': '&#8211;',
        '&larr;': '&#8592;',
        '&rarr;': '&#8594;',
        '&quot;': '&#34;',
        '&apos;': '&#39;',
        '&lt;': '&#60;',
        '&gt;': '&#62;',
        # Common ones that leak from wikitext
        '&laquo;': '&#171;',
        '&raquo;': '&#187;',
        '&times;': '&#215;',
        '&oacute;': '&#243;',
        '&Oacute;': '&#211;',
        # Curly quotes (very common in imported wikitext)
        '&lsquo;': '&#8216;',
        '&rsquo;': '&#8217;',
        '&ldquo;': '&#8220;',
        '&rdquo;': '&#8221;',
    }

    def _normalize_entities(self, text: str) -> str:
        """Convert named entities to numeric references.

        Strict XHTML (as used in EPUB) does not define &nbsp;, &hellip;, etc.
        We convert the common ones we see in the wikitext to numeric form.
        Already-numeric entities and the 5 XML predefined ones are left alone
        (or normalized to numeric for maximum compatibility).
        """
        if not text:
            return text

        # Replace known named entities with numeric equivalents
        for named, numeric in self._ENTITY_MAP.items():
            text = text.replace(named, numeric)

        # Also handle the case where html.escape or previous passes left &amp;nbsp; etc.
        for named, numeric in self._ENTITY_MAP.items():
            text = text.replace('&amp;' + named[1:], numeric)

        return text

    # ------------------------------------------------------------------ #
    # Other node types
    # ------------------------------------------------------------------ #

    def _render_heading(self, node: Heading) -> str:
        level = node.level
        text = "".join(self._render(n) for n in node.title.nodes)
        # We could generate ids for TOC linking later
        return f"<h{level}>{text}</h{level}>\n"

    def _render_external_link(self, node: ExternalLink) -> str:
        url = str(node.url)
        text = "".join(self._render(n) for n in (node.title.nodes if node.title else []))
        if not text:
            text = url
        return f'<a href="{html.escape(url)}">{text}</a>'

    # ------------------------------------------------------------------ #
    # During-render list collectors (the reliable path for * # ; : )
    # ------------------------------------------------------------------ #

    def _collect_list(self, nodes: list, start: int) -> tuple[str, int, str]:
        """Proper two-phase list builder for arbitrary nesting (the long-term fix).

        Phase 1 (linear): Collect a flat list of (prefix, content) where prefix
        is the full string of leading markers for that logical list item
        (e.g. "*", "*#", "**", "*#*", etc.). Handles the flattened li+Text
        representation from mwparserfromhell and the \n\n "next paragraph after
        list" splitting.

        Phase 2 (stack): Turn the flat list into correctly nested <ul>/<ol> HTML
        using a standard prefix stack. This supports arbitrary depth and
        arbitrary mixing of * and # (and will extend naturally to more if needed).
        """
        if start >= len(nodes):
            return "", start, ""

        first = nodes[start]
        if not isinstance(first, Tag):
            return "", start, ""

        # Determine the top-level container from the very first marker
        first_marker = str(first).strip()
        if first_marker not in ("*", "#"):
            first_marker = "*" if "*" in str(first) else "#"
        top_container = "ul" if first_marker == "*" else "ol"

        flat: list[tuple[str, str]] = []   # (prefix, content_html)
        i = start
        n = len(nodes)
        remainder = ""

        # ---------- Phase 1: Linear collection with full prefix ----------
        while i < n:
            nd = nodes[i]
            if not isinstance(nd, Tag):
                break
            m = str(nd).strip()
            if m not in ("*", "#"):
                break

            # Collect the full run of consecutive li markers → this is the prefix
            prefix_chars = []
            while i < n and isinstance(nodes[i], Tag):
                mm = str(nodes[i]).strip()
                if mm not in ("*", "#"):
                    break
                prefix_chars.append(mm)
                i += 1

            prefix = "".join(prefix_chars)

            # Now collect content until next list marker run or major block
            content_parts: list[str] = []
            while i < n:
                nd2 = nodes[i]
                if isinstance(nd2, Tag):
                    m2 = str(nd2).strip()
                    if m2 in ("*", "#"):
                        break
                    if m2 in ("h1", "h2", "h3", "h4", "table", "dl"):
                        break
                if isinstance(nd2, Text) and "\n\n" in str(nd2):
                    # Paragraph after this list item (or after the whole list)
                    full = str(nd2)
                    before, after = full.split("\n\n", 1)
                    if before.strip():
                        content_parts.append(self._render_text(Text(before)))
                    if after.strip():
                        remainder = self._render_text(Text(after))
                    i += 1
                    break
                content_parts.append(self._render(nd2))
                i += 1

            content = "".join(content_parts).strip()
            if prefix:
                flat.append((prefix, content))

            if remainder:
                break

        if not flat:
            return "", start, remainder

        # ---------- Phase 2: Stack-based emission ----------
        # stack entries: (prefix, container_tag, list_of_li_html_strings)
        stack: list[tuple[str, str, list[str]]] = []

        def _close_top() -> str:
            if not stack:
                return ""
            pref, cont, lis = stack.pop()
            if not lis:
                return ""
            inner = "\n".join(lis)
            return f"<{cont}>\n{inner}\n</{cont}>"

        result_parts: list[str] = []

        for prefix, content in flat:
            # Close any lists that are no longer prefixes of the current item
            while stack and not prefix.startswith(stack[-1][0]):
                closed = _close_top()
                if closed:
                    # Attach closed sublist to the last <li> of the new top (if any)
                    if stack:
                        _, _, top_lis = stack[-1]
                        if top_lis:
                            last = top_lis[-1]
                            if last.endswith("</li>"):
                                top_lis[-1] = last[:-5] + "\n" + closed + "</li>"
                            else:
                                top_lis[-1] = last + "\n" + closed
                    else:
                        result_parts.append(closed)

            # Open new nested lists for the additional prefix characters
            if not stack or prefix != stack[-1][0]:
                # Determine which new levels to open
                current_depth = len(stack[-1][0]) if stack else 0
                for depth in range(current_depth, len(prefix)):
                    ch = prefix[depth]
                    cont = "ul" if ch == "*" else "ol"
                    stack.append((prefix[:depth+1], cont, []))

            # Add this item to the current innermost list
            if stack:
                stack[-1][2].append(f"<li>{content}</li>")

        # Close all remaining open lists
        while stack:
            closed = _close_top()
            if closed:
                result_parts.append(closed)

        # Produce reasonably pretty output (newlines between major list levels)
        html = "\n".join(result_parts)

        # Ensure we have the outer container (in case of weird prefix situations)
        if html and not (html.strip().startswith("<ul") or html.strip().startswith("<ol")):
            html = f"<{top_container}>\n{html}\n</{top_container}>"

        return html, i, remainder

    def _collect_definition_list(self, nodes: list, start: int) -> tuple[str, int, str]:
        """Collect a run of definition list entries (dt/dd from ; : syntax).

        Supports multiple : defs after one ; term (the multi-def case).
        Emits one clean <dl>. Uses compact <dt>...</dt><dd>...</dd> form
        on one line when there is exactly one def (to match LIST_TESTS style).
        """
        if start >= len(nodes):
            return "", start, ""

        entries: list[tuple[str, list[str]]] = []
        i = start
        n = len(nodes)
        remainder = ""

        while i < n:
            nd = nodes[i]
            if not isinstance(nd, Tag):
                break
            m = str(nd).strip()
            tag_name = str(getattr(nd, "tag", "")).lower()
            if m not in (";", ":") and tag_name not in ("dt", "dd"):
                break

            if m == ":" or tag_name == "dd":
                i += 1
                def_parts: list[str] = []
                while i < n:
                    nd4 = nodes[i]
                    if isinstance(nd4, Tag):
                        m4 = str(nd4).strip()
                        if m4 in (";", ":") or str(getattr(nd4, "tag", "")).lower() in ("dt", "dd"):
                            break
                    if isinstance(nd4, Text) and "\n\n" in str(nd4):
                        # Stop swallowing the next paragraph after a bare indented dd line
                        full = str(nd4)
                        before, after = full.split("\n\n", 1)
                        if before.strip():
                            def_parts.append(self._render_text(Text(before)))
                        if after.strip():
                            remainder = self._render_text(Text(after))
                        i += 1
                        break
                    def_parts.append(self._render(nd4))
                    i += 1
                d = "".join(def_parts).strip()
                if d and entries:
                    last_term, last_defs = entries[-1]
                    last_defs.append(d)
                    entries[-1] = (last_term, last_defs)
                elif d:
                    entries.append(("", [d]))
                # If we split off a following paragraph after this bare dd, finish this <dl> run now
                if remainder:
                    break
                continue

            # New term (dt / ;)
            i += 1
            term_parts: list[str] = []
            while i < n:
                nd2 = nodes[i]
                if isinstance(nd2, Tag):
                    m2 = str(nd2).strip()
                    tg2 = str(getattr(nd2, "tag", "")).lower()
                    if m2 in (";", ":") or tg2 in ("dt", "dd"):
                        break
                    if tg2 in ("h1", "h2", "h3", "table", "ul", "ol", "dl"):
                        break
                term_parts.append(self._render(nd2))
                i += 1
            term = "".join(term_parts).strip()

            defs: list[str] = []
            while i < n:
                nd3 = nodes[i]
                if not isinstance(nd3, Tag):
                    break
                m3 = str(nd3).strip()
                tg3 = str(getattr(nd3, "tag", "")).lower()
                if m3 not in (":", ";") and tg3 not in ("dd", "dt"):
                    break
                if m3 == ";" or tg3 == "dt":
                    break
                i += 1
                def_parts: list[str] = []
                while i < n:
                    nd4 = nodes[i]
                    if isinstance(nd4, Tag):
                        m4 = str(nd4).strip()
                        if m4 in (";", ":") or str(getattr(nd4, "tag", "")).lower() in ("dt", "dd"):
                            break
                        if str(getattr(nd4, "tag", "")).lower() in ("h1", "h2", "h3", "table", "ul", "ol", "dl"):
                            break
                    if isinstance(nd4, Text) and "\n\n" in str(nd4):
                        # Same swallowing protection as for bullet lists — return remainder
                        full = str(nd4)
                        before, after = full.split("\n\n", 1)
                        if before.strip():
                            def_parts.append(self._render_text(Text(before)))
                        if after.strip():
                            remainder = self._render_text(Text(after))
                        i += 1
                        break
                    def_parts.append(self._render(nd4))
                    i += 1
                d = "".join(def_parts).strip()
                if d:
                    defs.append(d)

            if term or defs:
                entries.append((term, defs))

        if not entries:
            return "", start, ""

        out = ["<dl>"]
        for term, defs in entries:
            if term:
                if len(defs) == 1:
                    out.append(f"<dt>{term}</dt><dd>{defs[0]}</dd>")
                else:
                    out.append(f"<dt>{term}</dt>")
                    for d in defs:
                        out.append(f"<dd>{d}</dd>")
            else:
                for d in defs:
                    out.append(f"<dd>{d}</dd>")
        out.append("</dl>")
        return "\n".join(out), i, remainder

    # ------------------------------------------------------------------ #
    # Convenience / development helpers
    # ------------------------------------------------------------------ #

    def convert_file(self, path: Path, page_title: str | None = None) -> str:
        """Handy for ad-hoc testing against the example files."""
        text = path.read_text(encoding="utf-8")
        title = page_title or path.stem
        return self.convert(text, title)


def run_stage2(*, workdir: Path, force: bool = False) -> None:
    """Convert downloaded chapter wikitext into clean XHTML.

    This is the real implementation used when running with a workdir.
    It reads metadata.json, converts every chapter's wikitext from
    downloads/chapters/, and writes the results to xhtml/.
    """
    log.info("Stage 2: Converting wikitext → XHTML")

    meta_path = workdir / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"metadata.json not found in {workdir}. "
            "You must run Stage 1 first (or --start-from 1)."
        )

    meta = BookMetadata.from_json(meta_path)

    downloads = workdir / "downloads"
    chapters_dir = downloads / "chapters"
    xhtml_dir = workdir / "xhtml"
    xhtml_dir.mkdir(parents=True, exist_ok=True)

    images_root = downloads / "images"
    if not images_root.exists():
        images_root = None

    page_to_xhtml = {ch.page_title: ch.xhtml_filename for ch in meta.chapters}
    page_to_display = {ch.page_title: ch.display_title for ch in meta.chapters}

    # Build the map from original wiki image name → the chosen file (webp or original)
    # that stage 2 should emit in <img src> and <figure> markup.
    image_map = {
        orig_name: info.chosen_local
        for orig_name, info in meta.images.items()
    }

    ctx = ConversionContext(
        book_pages=set(page_to_xhtml.keys()),
        page_to_xhtml=page_to_xhtml,
        page_to_display=page_to_display,
        image_map=image_map,
        images_root=images_root,
        workdir=workdir,
        emit_title_h1=True,
        cover_image=meta.cover_image,
    )
    conv = WikitextConverter(ctx)

    converted = 0
    skipped = 0

    for ch in meta.chapters:
        # Stage 1 stores chapters as page_title with spaces → underscores
        wikitext_name = ch.page_title.replace(" ", "_") + ".wikitext"
        wikitext_path = chapters_dir / wikitext_name

        out_path = xhtml_dir / ch.xhtml_filename

        if not force and out_path.exists():
            log.info("  Skipping (already exists): %s", ch.xhtml_filename)
            skipped += 1
            continue

        if not wikitext_path.exists():
            log.warning("  Missing source wikitext for %s (looked for %s)",
                        ch.page_title, wikitext_name)
            skipped += 1
            continue

        log.info("  Converting: %s → %s", ch.page_title, ch.xhtml_filename)
        try:
            xhtml = conv.convert_file(wikitext_path, ch.page_title)
            out_path.write_text(xhtml, encoding="utf-8")
            converted += 1
        except Exception as e:
            log.exception("  FAILED to convert %s: %s", ch.page_title, e)
            skipped += 1

    log.info("Stage 2 complete: %d chapters converted, %d skipped", converted, skipped)

    if converted == 0:
        log.error(
            "Stage 2 produced ZERO XHTML files!\n"
            "  - Looked for source wikitext in: %s\n"
            "  - Expected naming: page_title with spaces → underscores + .wikitext\n"
            "  - Output directory: %s\n"
            "Check the warnings above and the contents of the chapters directory.",
            chapters_dir, xhtml_dir
        )

    # Ensure an editable toc.json exists for Stage 3 (even on --start-from 2 restarts).
    toc_wikitext_path = downloads / "toc.wikitext"
    ensure_toc_json(workdir, meta.chapters, toc_wikitext_path, force=force)


# ---------------------------------------------------------------------- #
# Quick manual test / development entry point
# ---------------------------------------------------------------------- #

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("chapter", help="Path to a .wikitext chapter file")
    ap.add_argument("--images", default="example_inputs/IMAGEs", help="Directory containing the images")
    ap.add_argument("--title", help="Override chapter title for the <h1>")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO)

    ctx = ConversionContext(
        images_root=Path(args.images),
        # For ad-hoc runs we don't have the book_pages set, so most internal links
        # will be demoted. That's fine for visual inspection of one chapter.
    )
    conv = WikitextConverter(ctx)

    xhtml = conv.convert_file(Path(args.chapter), args.title)
    print(xhtml)

