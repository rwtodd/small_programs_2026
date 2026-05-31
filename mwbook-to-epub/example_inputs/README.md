# example_inputs/

This directory contains supporting data for development and testing.

**Only `LIST_TESTS/` is committed to the repository.**

All other subdirectories (CHAPTERs/, IMAGEs/, TOCs/, rendered_html/) contain large real book data, images, or reference HTML. They are excluded via `.gitignore` so the repository stays small and the focused regression tests remain easy to run.

## Running the regression tests

The tests in `LIST_TESTS/` are self-contained. You can exercise them directly with the converter, for example:

```bash
uv run python -m mwbook_to_epub.stage2 \
  example_inputs/LIST_TESTS/test007.wikitext \
  --title test007 > /tmp/out.xhtml

diff -u example_inputs/LIST_TESTS/test007.xhtml /tmp/out.xhtml
```

See the project history / LIST_TESTS/ files for the current set of focused list-handling regression tests.
