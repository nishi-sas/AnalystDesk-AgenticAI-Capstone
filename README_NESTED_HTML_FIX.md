# AnalystDesk Stage 2B — Nested hidden HTML fix

Issue: `html_blocks` snapshots `soup.find_all(style=True)` and decomposes
hidden ancestors. BeautifulSoup sets `attrs=None` on decomposed descendants,
so the subsequent `tag.get("style")` raises AttributeError.

The patch adds a guard for invalidated tags, without changing the parser's
normal visible-text or table handling. Existing source is backed up before
patching. Run from the **AnalystDesk** project root:

```
python tools\apply_nested_hidden_html_fix.py
python -m pytest -q tests\test_nested_hidden_html.py tests\test_document_parsing.py tests\test_heading_variants.py
python -m pytest -q
```

After tests pass, rerun the 36-file parser using its separate output and summary
paths. The original two-company corpus remains untouched.

No change to SEC downloads, checkpoints, model calls, or Docker containers.
