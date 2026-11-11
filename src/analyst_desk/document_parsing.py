"""Stage 2B: auditable 10-K section parsing, preserving tables as row-aware text.

The document is untrusted. We never execute its HTML, JS, or XBRL. Missing or
ambiguous Item boundaries raise an explicit error instead of fabricating passages.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, Tag

TARGET_ITEMS = ("1A", "7", "8")
ITEM_TITLES = {
    "1A": ("risk factors",),
    "1B": ("unresolved staff comments",),
    "1C": ("cybersecurity",),
    "2": ("properties",),
    "3": ("legal proceedings",),
    "4": ("mine safety",),
    "5": ("market for registrant", "market for the registrant"),
    "6": ("reserved", "selected financial data"),
    "7": ("management",),
    "7A": ("quantitative",),
    "8": ("financial statements",),
    "9": ("changes in",),
    "9A": ("controls and procedures", "controls"),
    "9B": ("other information",),
    "9C": ("disclosure regarding",),
}
_ITEM = re.compile(r"^item\s*(1a|1b|1c|2|3|4|5|6|7a|7|8|9a|9b|9c|9)\s*[.:\-–—]?\s*(.*)$", re.I)
_WS = re.compile(r"\s+")
_BLOCK_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div", "table")


class DocumentParseError(RuntimeError):
    """The requested SEC filing cannot be parsed with trustworthy boundaries."""


@dataclass(frozen=True)
class Block:
    kind: str  # text or table
    text: str
    position: int


def clean(text: str) -> str:
    return _WS.sub(" ", text.replace("\u200b", " ").replace("\ufeff", " ")).strip()


def _table_markdown(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue  # do not duplicate nested tables
        cells = tr.find_all(("td", "th"), recursive=False)
        if not cells:
            continue
        values = [clean(c.get_text(" ", strip=True)).replace("|", "\\|") for c in cells]
        if any(values):
            rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


def html_blocks(raw_html: bytes) -> list[Block]:
    if not raw_html.strip():
        raise DocumentParseError("Empty SEC HTML")
    soup = BeautifulSoup(raw_html, "lxml")
    for tag in list(soup.find_all(("script", "style", "noscript", "ix:header", "ix:hidden", "ix:resources"))):
        tag.decompose()
    # Hidden ixbrl containers are not visible filing content.
    for tag in list(soup.find_all(style=True)):
        # Decomposing a hidden ancestor invalidates nested tags in this snapshot.
        if tag.attrs is None:
            continue
        style = str(tag.get("style", "")).replace(" ", "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            tag.decompose()
    root = soup.body or soup
    blocks: list[Block] = []
    for tag in root.find_all(_BLOCK_TAGS):
        if tag.name == "table":
            if tag.find_parent("table") is not None:
                continue
            text = _table_markdown(tag)
            if text:
                blocks.append(Block("table", text, len(blocks)))
            continue
        if tag.find_parent("table") is not None:
            continue
        if tag.name in ("div", "li") and tag.find(_BLOCK_TAGS):
            continue
        if tag.name == "p" and tag.find(("p", "div", "table")):
            continue
        text = clean(tag.get_text(" ", strip=True))
        if text:
            blocks.append(Block("text", text, len(blocks)))
    if not blocks:
        raise DocumentParseError("No visible text blocks extracted from filing")
    return blocks


def _title_key(text: str) -> str:
    """Compare only letter/digit sequences; SEC iXBRL may split words visually."""
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _starts_with_item_title(item: str, text: str) -> bool:
    key = _title_key(text)
    return bool(key) and any(key.startswith(_title_key(title))
                             for title in ITEM_TITLES[item])


def heading_item(text: str) -> str | None:
    """Recognise an explicit Item code AND known title; never trust naked codes."""
    t = clean(text)
    if len(t) > 180:
        return None
    match = _ITEM.match(t)
    if not match:
        return None
    item, tail = match.groups()
    item = item.upper()
    return item if _starts_with_item_title(item, tail) else None


def _split_heading_item(blocks: list[Block], i: int) -> str | None:
    """Recognise only an isolated Item code followed immediately by its title.

    The SEC sometimes renders ITEM 8 and FINANCIAL STATEMENTS as separate
    HTML blocks. No free-form fuzzy matching or cross-document guesswork.
    """
    block = blocks[i]
    if block.kind != "text" or len(block.text) > 30:
        return None
    match = re.fullmatch(r"item\s*(1a|1b|1c|2|3|4|5|6|7a|7|8|9a|9b|9c|9)\s*[.:-]?",
                         clean(block.text), flags=re.I)
    if not match:
        return None
    item = match.group(1).upper()
    following = []
    for next_block in blocks[i + 1:i + 3]:
        if next_block.kind != "text" or len(next_block.text) > 140:
            break
        # Require matching at the very start; never scan narrative text.
        following.append(next_block.text)
        if _starts_with_item_title(item, " ".join(following)):
            return item
    return None


def heading_candidates(blocks: list[Block]) -> list[tuple[int, str]]:
    """Get filing section boundaries from explicit item/title pairs."""
    matches = []
    for i, block in enumerate(blocks):
        if block.kind != "text":
            continue
        item = heading_item(block.text) or _split_heading_item(blocks, i)
        if item:
            # Both a standalone code and a following full heading can match.
            # Keep the full heading if they are immediate neighbours.
            if matches and matches[-1][1] == item and matches[-1][0] == i - 1:
                matches[-1] = (i, item)
            else:
                matches.append((i, item))
    return matches


def find_sections(blocks: list[Block], min_chars: int = 120) -> dict[str, tuple[int, int]]:
    candidates = heading_candidates(blocks)
    sections = {}
    for wanted in TARGET_ITEMS:
        choices = []
        for j, (start, item) in enumerate(candidates):
            if item != wanted:
                continue
            stop = candidates[j + 1][0] if j + 1 < len(candidates) else len(blocks)
            chars = sum(len(x.text) for x in blocks[start + 1:stop])
            if chars >= min_chars:
                choices.append((chars, start, stop))
        if not choices:
            raise DocumentParseError(f"Missing or empty Item {wanted}; refuses guessed section boundaries")
        # A TOC item usually has almost no document content before the next heading.
        chars, start, stop = max(choices)
        sections[wanted] = (start + 1, stop)
    if not (sections["1A"][0] < sections["7"][0] < sections["8"][0]):
        raise DocumentParseError("Selected Item 1A/7/8 boundaries are out of document order")
    return sections


def _split_large(text: str, max_chars: int) -> Iterable[str]:
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars + 1)
        if cut < max_chars // 2:
            cut = max_chars
        yield text[:cut].strip()
        text = text[cut:].strip()
    if text:
        yield text


def passages_from_html(raw_html: bytes, meta: dict, *, max_chars: int = 2400,
                       min_section_chars: int = 120) -> tuple[list[dict], dict]:
    if max_chars < 500:
        raise ValueError("max_chars must be >= 500")
    for field in ("ticker", "accession", "report_date", "filing_date", "url", "sha256"):
        if not meta.get(field):
            raise DocumentParseError(f"Missing required provenance field: {field}")
    actual_hash = hashlib.sha256(raw_html).hexdigest()
    if actual_hash != meta["sha256"]:
        raise DocumentParseError("HTML SHA256 mismatch against manifest; refusing tampered source")
    blocks = html_blocks(raw_html)
    bounds = find_sections(blocks, min_chars=min_section_chars)
    passages: list[dict] = []
    stats = {}
    for item in TARGET_ITEMS:
        start, stop = bounds[item]
        item_blocks = blocks[start:stop]
        stats[item] = {"blocks": len(item_blocks), "characters": sum(len(b.text) for b in item_blocks),
                       "tables": sum(b.kind == "table" for b in item_blocks)}
        sequence = 0
        pending: list[str] = []
        first_block: int | None = None
        last_block: int | None = None

        def emit(text: str, kind: str, first: int, last: int) -> None:
            nonlocal sequence
            sequence += 1
            passage_id = f"{meta['ticker']}_{meta['report_date']}_Item{item}_{sequence:05d}"
            passages.append({"passage_id": passage_id, "ticker": meta["ticker"],
                             "accession": meta["accession"], "filing_date": meta["filing_date"],
                             "report_date": meta["report_date"], "item": item,
                             "source_url": meta["url"], "source_sha256": actual_hash,
                             "kind": kind, "is_table": kind == "table",
                             "start_block": first, "end_block": last, "text": text})

        def flush() -> None:
            nonlocal pending, first_block, last_block
            if pending:
                emit("\n\n".join(pending), "text", first_block, last_block)
                pending = []
                first_block = None
                last_block = None

        for b in item_blocks:
            if b.kind == "table":
                flush()
                # Keep every table intact; Stage 2C may partition rows and carry the table ID.
                emit(b.text, "table", b.position, b.position)
                continue
            for part in _split_large(b.text, max_chars):
                if pending and sum(len(p) + 2 for p in pending) + len(part) > max_chars:
                    flush()
                if first_block is None:
                    first_block = b.position
                pending.append(part)
                last_block = b.position
        flush()
        if not any(p["item"] == item for p in passages):
            raise DocumentParseError(f"Item {item} produced no passages")
    return passages, {"source_sha256": actual_hash, "total_blocks": len(blocks),
                      "sections": stats, "passage_count": len(passages),
                      "table_passages": sum(p["is_table"] for p in passages)}


def process_manifest(manifest_path: str | Path, *, cache_root: str | Path = "data/edgar_cache",
                     max_chars: int = 2400) -> tuple[list[dict], list[dict]]:
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, list) or not manifest:
        raise DocumentParseError("Manifest must contain at least one filing record")
    allowed_root = Path(cache_root).resolve()
    output, summaries = [], []
    seen = set()
    for meta in manifest:
        path = Path(meta["local_path"]).resolve()
        if not path.is_relative_to(allowed_root):
            raise DocumentParseError(f"Manifest path escapes SEC cache: {path}")
        if str(path) in seen:
            raise DocumentParseError(f"Duplicate source document: {path}")
        seen.add(str(path))
        sidecar = path.with_name(path.name + ".meta.json")
        if not sidecar.is_file():
            raise DocumentParseError(f"Provenance sidecar missing: {sidecar}")
        original_meta = json.loads(sidecar.read_text(encoding="utf-8"))
        if any(meta.get(key) != original_meta.get(key)
               for key in ("accession", "ticker", "sha256", "url", "report_date", "filing_date")):
            raise DocumentParseError(f"Manifest and provenance sidecar disagree: {path}")
        raw = path.read_bytes()
        passages, summary = passages_from_html(raw, meta, max_chars=max_chars)
        output.extend(passages)
        summaries.append({"ticker": meta["ticker"], "accession": meta["accession"],
                          "report_date": meta["report_date"], "source_url": meta["url"], **summary})
    return output, summaries
