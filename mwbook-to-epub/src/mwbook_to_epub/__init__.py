"""mwbook-to-epub: Convert MediaWiki books (wikitext) to EPUB 3.3.

Stages are restartable via on-disk workdir artifacts so that stage 2 (the
wikitext-to-XHTML conversion) can be re-run after tweaks without any
re-downloads.
"""

__version__ = "0.1.0"
