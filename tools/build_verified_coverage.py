"""Build an isolated, fail-closed 12-company SEC 10-K corpus.

This is a sidecar: DOES NOT edit existing parser, primary corpus, index, CI,
checkpoints, or evidence. A successful run publishes a versioned corpus and an
atomic pointer. A failed run publishes neither.

Run from the AnalystDesk repository root after Stage 2A is complete.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from typing import Any

# All replacement tickers are DIFFERENT from the original twelve.
# The observed original grouping puts AMZN in commerce/retail.
SECTORS = {
    "technology": ("MSFT", "GOOGL", "AAPL", "META", "NVDA", "ORCL"),
    "commerce_retail": ("WMT", "AMZN", "COST", "TGT", "HD", "LOW"),
}
REPLACEMENTS = {
    "technology": ("ADBE", "CRM", "CSCO", "QCOM", "INTU", "IBM", "TXN", "AMD", "INTC"),
    "commerce_retail": ("BBY", "KR", "TJX", "ROST", "DG", "DLTR", "ULTA", "DKS", "ACI"),
}
ITEMS = frozenset(("1A", "7", "8"))
TICKER_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}\Z")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
SEC_RE = re.compile(r"\Ahttps://(?:www\.)?sec\.gov/Archives/", re.I)


class CoverageError(ValueError):
    """Unsafe or inadequate evidence; no corpus should be published."""


def unique_queue(initial: dict[str, tuple[str, ...]],
                 replacements: dict[str, tuple[str, ...]]) -> None:
    original = [t for v in initial.values() for t in v]
    incoming = [t for v in replacements.values() for t in v]
    for t in original + incoming:
        if not TICKER_RE.fullmatch(t):
            raise CoverageError(f"Invalid ticker: {t!r}")
    if len(set(original + incoming)) != len(original + incoming):
        raise CoverageError("Replacement queue overlaps existing tickers or itself")
    if set(initial) != set(replacements):
        raise CoverageError("Replacement sectors must equal original sectors")


def read_manifest(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(d, dict) for d in data):
        raise CoverageError(f"Expected a JSON list of filing records: {path}")
    return data


def record_accession(record: dict[str, Any]) -> str:
    """Read downloader accession field or recover it from its SEC cache path."""
    for key in ("accession", "accession_number", "accessionNumber"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.replace("-", "")
    path = str(record.get("local_path", "")).replace("\\", "/")
    parts = Path(path).parts
    for part in parts:
        if re.fullmatch(r"\d{18}", part):
            return part
    raise CoverageError("Manifest record lacks an SEC accession identifier")


def grouped_three(records: list[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    current = [dict(x) for x in records if x.get("ticker") == ticker]
    if len(current) != 3:
        raise CoverageError(f"{ticker}: expected exactly three 10-K records, got {len(current)}")
    dates = [x.get("report_date") for x in current]
    if any(not isinstance(d, str) or not DATE_RE.fullmatch(d) for d in dates):
        raise CoverageError(f"{ticker}: invalid reporting dates")
    if len(set(dates)) != 3:
        raise CoverageError(f"{ticker}: reporting dates are not distinct")
    if any(x.get("ticker") != ticker for x in current):
        raise CoverageError(f"{ticker}: manifest ticker mismatch")
    if len({record_accession(x) for x in current}) != 3:
        raise CoverageError(f"{ticker}: duplicate filing accessions")
    return sorted(current, key=lambda x: x["report_date"], reverse=True)


def safe_document_path(record: dict[str, Any], repo_root: Path) -> Path:
    supplied = record.get("local_path")
    if not isinstance(supplied, str) or not supplied.strip():
        raise CoverageError("Missing local_path in SEC manifest")
    normalized = supplied.replace("\\", "/")
    source = Path(normalized)
    if source.is_absolute() or ".." in source.parts:
        raise CoverageError(f"Unsafe document path: {supplied}")
    if source.parts[:2] != ("data", "edgar_cache") or "documents" not in source.parts:
        raise CoverageError(f"Unexpected SEC cache document path: {supplied}")
    full = repo_root / source
    if full.is_symlink() or not full.is_file() or not full.resolve().is_relative_to(repo_root.resolve()):
        raise CoverageError(f"SEC document unavailable or unsafe: {supplied}")
    if full.stat().st_size < 1000:
        raise CoverageError(f"SEC document suspiciously short: {supplied}")
    expected = record.get("sha256") or record.get("document_sha256")
    if expected is not None:
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise CoverageError(f"Invalid SHA256 metadata for {supplied}")
        with full.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual.lower() != expected.lower():
            raise CoverageError(f"SEC SHA256 mismatch: {supplied}")
    return source


def stage_document(record: dict[str, Any], source_root: Path, target_root: Path) -> None:
    """Stage filing HTML AND its downloader provenance sidecar.

    The existing strict parser expects <file>.htm.meta.json alongside HTML.
    A genuinely missing source sidecar remains missing so that parsing rejects
    only the affected company; neither fabricate nor relax provenance checks.
    """
    relative = safe_document_path(record, source_root)
    for rel in (relative, Path(str(relative) + ".meta.json")):
        source = source_root / rel
        if rel != relative and not source.exists() and not source.is_symlink():
            continue  # Parser will fail closed if this filing lacks provenance.
        if (source.is_symlink() or not source.is_file() or
                not source.resolve().is_relative_to(source_root.resolve())):
            raise CoverageError(f"Unsafe SEC document or provenance sidecar: {rel}")
        dest = target_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() or dest.is_symlink():
            if (dest.is_symlink() or not dest.is_file() or
                    dest.read_bytes() != source.read_bytes()):
                raise CoverageError(f"Staged SEC file conflict: {rel}")
            continue
        shutil.copy2(source, dest)


def verify_parser_output(ticker: str, manifest: list[dict[str, Any]],
                         passages: list[dict[str, Any]],
                         summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Structural and provenance checks, not a claim of semantic correctness."""
    if len(summaries) != 3:
        raise CoverageError(f"{ticker}: expected three parser summaries, got {len(summaries)}")
    dates = {x["report_date"] for x in manifest}
    seen_dates: set[str] = set()
    for summary in summaries:
        date = summary.get("report_date")
        if summary.get("ticker") != ticker or date not in dates or date in seen_dates:
            raise CoverageError(f"{ticker}: duplicated or mismatched parser summary date {date}")
        seen_dates.add(date)
        sections = summary.get("sections")
        if not isinstance(sections, dict) or not ITEMS.issubset(sections):
            raise CoverageError(f"{ticker} {date}: missing 1A/7/8 parser sections")
        for item in ITEMS:
            details = sections[item]
            if not isinstance(details, dict) or not isinstance(details.get("characters"), int) or details["characters"] < 200:
                raise CoverageError(f"{ticker} {date}: Item {item} is suspiciously short")
        if not isinstance(summary.get("passage_count"), int) or summary["passage_count"] <= 0:
            raise CoverageError(f"{ticker} {date}: no passages reported")
    if not passages:
        raise CoverageError(f"{ticker}: parser produced zero passages")
    per_date: dict[str, Counter[str]] = defaultdict(Counter)
    ids: set[str] = set()
    accession_by_date = {x["report_date"]: record_accession(x) for x in manifest}
    for p in passages:
        if not isinstance(p, dict) or p.get("ticker") != ticker:
            raise CoverageError(f"{ticker}: cross-company passage contamination")
        date, item = p.get("report_date"), p.get("item")
        if date not in dates or item not in ITEMS:
            raise CoverageError(f"{ticker}: invalid passage date/item {date}/{item}")
        pid = p.get("passage_id")
        if not isinstance(pid, str) or not pid or pid in ids:
            raise CoverageError(f"{ticker}: invalid or duplicated passage_id")
        ids.add(pid)
        txt = p.get("text")
        if not isinstance(txt, str) or len(txt.strip()) < 10 or "\ufffd" in txt:
            raise CoverageError(f"{ticker} {date}: invalid or replacement-character passage")
        url = p.get("source_url")
        if not isinstance(url, str) or not SEC_RE.match(url):
            raise CoverageError(f"{ticker} {date}: passage lacks SEC Archives provenance")
        accession = p.get("accession")
        if accession is not None and str(accession).replace("-", "") != accession_by_date[date]:
            raise CoverageError(f"{ticker} {date}: passage accession mismatch")
        per_date[date][item] += 1
    for date in dates:
        if set(per_date[date]) != ITEMS:
            raise CoverageError(f"{ticker} {date}: no passages for each of Items 1A,7,8")
        expected_n = next(s["passage_count"] for s in summaries if s["report_date"] == date)
        if sum(per_date[date].values()) != expected_n:
            raise CoverageError(f"{ticker} {date}: summary passage count does not match corpus")
    return {"status": "PARSER_VALIDATED", "ticker": ticker,
            "filings": len(dates), "passages": len(passages),
            "sections_per_filing": sorted(ITEMS),
            "report_dates": sorted(dates, reverse=True),
            "note": "Structural/provenance validation only; not human-reviewed financial accuracy"}


def _write_json(path: Path, contents: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contents, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, contents: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for item in contents:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")


def stage_prior_verified_replacement(ticker: str, stage_root: Path,
                                     repo_root: Path) -> int:
    """Reuse identical SEC HTML + metadata from a previously published release.

    The downloader may generate a different .meta.json for the SAME filing
    on a later invocation (e.g. acquisition timestamp). Preserve the earlier
    validated sidecar instead of allowing a conflict at publication.
    Only the currently published, complete, path-confined manifest is trusted.
    The existing downloader STILL performs its ordinary SEC filing selection.
    """
    base = repo_root / "data" / "verified_coverage"
    pointer = base / "current.json"
    if not pointer.exists() and not pointer.is_symlink():
        return 0
    if (pointer.is_symlink() or not pointer.is_file() or
            not pointer.resolve().is_relative_to(repo_root.resolve())):
        raise CoverageError("Unsafe prior verified-coverage pointer")
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise CoverageError(f"Invalid prior verified-coverage pointer: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != "analystdesk-verified-coverage-pointer-v1":
        raise CoverageError("Unrecognized prior verified-coverage pointer")
    name = data.get("manifest")
    if not isinstance(name, str):
        raise CoverageError("Prior verified-coverage manifest missing")
    path = Path(name.replace("\\", "/"))
    if (path.is_absolute() or ".." in path.parts or
            path.parts[:3] != ("data", "verified_coverage", "runs") or
            path.name != "10k_verified_manifest.json"):
        raise CoverageError("Unsafe prior verified-coverage manifest path")
    manifest_path = repo_root / path
    if (manifest_path.is_symlink() or not manifest_path.is_file() or
            not manifest_path.resolve().is_relative_to(repo_root.resolve())):
        raise CoverageError("Prior verified-coverage manifest missing or unsafe")
    records = read_manifest(manifest_path)
    candidates = [r for r in records if r.get("ticker") == ticker]
    if not candidates:
        return 0
    docs = grouped_three(candidates, ticker)
    # Preflight complete 3-filing HTML AND provenance before copying anything.
    for record in docs:
        rel = safe_document_path(record, repo_root)
        meta = repo_root / (str(rel) + ".meta.json")
        if (meta.is_symlink() or not meta.is_file() or
                not meta.resolve().is_relative_to(repo_root.resolve())):
            raise CoverageError(f"Prior accepted SEC sidecar missing or unsafe: {rel}")
    for record in docs:
        stage_document(record, repo_root, stage_root)
    return len(docs)


def download_replacement(ticker: str, stage_root: Path, repo_root: Path) -> list[dict[str, Any]]:
    """Run the existing SEC downloader, with a separate working directory/cache/manifest.

    Existing repo evidence/10k_html_manifest.json is NEVER written by this call.
    """
    cached_periods = stage_prior_verified_replacement(ticker, stage_root, repo_root)
    if cached_periods:
        print(f"  REUSED: {ticker} {cached_periods} previously accepted SEC cache pairs", flush=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(repo_root / "src"), env.get("PYTHONPATH", ""))))
    # Settings may be relative to the working directory. Copy configuration only.
    if (repo_root / "config").is_dir() and not (stage_root / "config").exists():
        shutil.copytree(repo_root / "config", stage_root / "config")
    cmd = [sys.executable, "-m", "analyst_desk.filings_cli", "--tickers", ticker, "--years", "3"]
    result = subprocess.run(cmd, cwd=stage_root, env=env, capture_output=True, text=True,
                            errors="replace", timeout=300)
    log_path = stage_root / "download_logs" / f"{ticker}.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("COMMAND: " + " ".join(cmd) + "\nEXIT: " + str(result.returncode)
                        + "\nSTDOUT:\n" + result.stdout + "\nSTDERR:\n" + result.stderr,
                        encoding="utf-8")
    if result.returncode:
        raise CoverageError(f"{ticker}: SEC downloader failed (exit {result.returncode}); see {log_path}")
    stage_manifest = stage_root / "evidence" / "10k_html_manifest.json"
    if not stage_manifest.is_file():
        raise CoverageError(f"{ticker}: isolated downloader did not produce a manifest; see {log_path}")
    return grouped_three(read_manifest(stage_manifest), ticker)


def standalone_item8_page_number(p: dict[str, Any]) -> bool:
    """Recognize only non-table standalone printed page numbers, e.g. '44.'.

    Does not strip numeric table cells, prose, short risk disclosures, or any
    replacement-character text. Never renumbers/relabels original citations.
    """
    return (p.get("item") == "8" and p.get("is_table") is False
            and isinstance(p.get("text"), str)
            and re.fullmatch(r"[1-9][0-9]{0,2}\.", p["text"].strip()) is not None)


def parse_and_validate(ticker: str, docs: list[dict[str, Any]],
                       stage_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Use the UNMODIFIED project's strict parser (one company at a time)."""
    from analyst_desk.document_parsing import process_manifest
    # File-granular parsing supplies the exact reporting period in rejection logs.
    all_passages: list[dict[str, Any]] = []
    all_summaries: list[dict[str, Any]] = []
    for doc in docs:
        single_manifest = stage_root / "candidate_manifests" / f"{ticker}_{doc['report_date']}.json"
        _write_json(single_manifest, [doc])
        try:
            # document_parsing resolves manifest local_path relative to cwd.
            # Temporarily use the isolated staging root so its cache-root guard
            # checks staged SEC HTML, not the original repository's paths.
            previous_cwd = Path.cwd()
            try:
                os.chdir(stage_root)
                passages, summaries = process_manifest(
                    str(single_manifest),
                    cache_root=str(stage_root / "data" / "edgar_cache"),
                    max_chars=2400,
                )
            finally:
                os.chdir(previous_cwd)
        except Exception as exc:
            raise CoverageError(f"{ticker} {doc['report_date']} failed extraction: {exc}") from exc
        # SEC iXBRL sometimes produces printed page-number-only text blocks
        # (e.g. Google Item 8 '44.'). These are not financial content.
        # Do NOT alter the core parser or drop any other short/invalid text.
        excluded = [p for p in passages if standalone_item8_page_number(p)]
        kept = [p for p in passages if not standalone_item8_page_number(p)]
        if len(summaries) != 1 or summaries[0].get("passage_count") != len(passages):
            raise CoverageError(f"{ticker} {doc['report_date']}: raw parser summary/count mismatch")
        if excluded:
            summaries[0]["original_passage_count"] = len(passages)
            summaries[0]["passage_count"] = len(kept)
            summaries[0]["excluded_pagination_fragment_ids"] = [
                p["passage_id"] for p in excluded
            ]
            summaries[0]["excluded_pagination_fragment_texts"] = [
                p["text"] for p in excluded
            ]
        all_passages.extend(kept)
        all_summaries.extend(summaries)
    result = verify_parser_output(ticker, docs, all_passages, all_summaries)
    removed = [
        {"report_date": s["report_date"],
         "passage_ids": s.get("excluded_pagination_fragment_ids", []),
         "page_labels": s.get("excluded_pagination_fragment_texts", [])}
        for s in all_summaries if s.get("excluded_pagination_fragment_ids")
    ]
    result["excluded_pagination_fragments"] = sum(len(x["passage_ids"]) for x in removed)
    result["pagination_exclusion_audit"] = removed
    return all_passages, all_summaries, result


def _publish_new_docs(staged: list[dict[str, Any]], stage_root: Path, repo_root: Path) -> None:
    """Keep approved candidate HTML and provenance sidecars together in cache."""
    for record in staged:
        rel = safe_document_path(record, stage_root)
        for entry in (rel, Path(str(rel) + ".meta.json")):
            fresh = stage_root / entry
            if (fresh.is_symlink() or not fresh.is_file() or
                    not fresh.resolve().is_relative_to(stage_root.resolve())):
                raise CoverageError(f"Accepted filing lacks safe SEC provenance: {entry}")
            original = repo_root / entry
            if original.exists() or original.is_symlink():
                if (original.is_symlink() or not original.is_file() or
                        original.read_bytes() != fresh.read_bytes()):
                    raise CoverageError(f"Refusing to overwrite existing SEC cache file: {entry}")
                continue
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fresh, original)


def build(repo_root: Path, *, target_per_sector: int = 6,
          initial: dict[str, tuple[str, ...]] | None = None,
          replacements: dict[str, tuple[str, ...]] | None = None) -> dict[str, Any]:
    initial = initial or SECTORS
    replacements = replacements or REPLACEMENTS
    unique_queue(initial, replacements)
    if not 1 <= target_per_sector <= min(len(x) for x in initial.values()):
        raise CoverageError("target-per-sector must be in the available initial range")
    repo_root = repo_root.resolve()
    source_manifest = repo_root / "evidence" / "10k_html_manifest.json"
    source_records = read_manifest(source_manifest)
    baseline = {ticker for names in initial.values() for ticker in names}
    if set(str(x.get("ticker", "")) for x in source_records) != baseline:
        raise CoverageError("Input manifest tickers differ from configured original twelve")
    base = repo_root / "data" / "verified_coverage"
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    stage = base / "_work" / token
    release = base / "runs" / token
    stage.mkdir(parents=True)
    report: dict[str, Any] = {
        "schema": "analystdesk-verified-coverage-v1", "run_id": token,
        "input_manifest": "evidence/10k_html_manifest.json", "target_per_sector": target_per_sector,
        "original_tickers": {k: list(v) for k,v in initial.items()},
        "replacement_queue": {k: list(v) for k,v in replacements.items()},
        "attempts": [], "selection": {}, "status": "IN_PROGRESS",
        "limitations": ["Parsing and structural/provenance checks only; semantic extraction quality requires sampled human review", 
                        "Does not change the primary two-company corpus/index or enable new Chainlit tickers"],
    }
    selected_docs: list[dict[str, Any]] = []
    selected_passages: list[dict[str, Any]] = []
    selected_summaries: list[dict[str, Any]] = []
    newly_downloaded: list[dict[str, Any]] = []
    try:
        print(f"Isolated workspace: {stage}", flush=True)
        # Build an isolated SEC cache that includes the pre-existing 36 HTML documents.
        for record in source_records:
            stage_document(record, repo_root, stage)
        used_tickers = set(baseline)
        passage_ids: set[str] = set()
        for sector, existing in initial.items():
            found: list[str] = []
            trials = list(existing) + list(replacements[sector])
            for ticker in trials:
                if len(found) == target_per_sector:
                    break
                if ticker not in existing:
                    if ticker in used_tickers:
                        raise CoverageError(f"Duplicate or previously used replacement: {ticker}")
                    used_tickers.add(ticker)
                print(f"[{sector}] CHECK {ticker} ({len(found)}/{target_per_sector} accepted)", flush=True)
                record: dict[str, Any] = {"ticker": ticker, "sector": sector, "status": "REJECTED", "source": "original" if ticker in existing else "replacement"}
                try:
                    docs = (grouped_three(source_records, ticker) if ticker in existing else
                            download_replacement(ticker, stage, repo_root))
                    for d in docs:
                        safe_document_path(d, stage)
                    passages, summaries, details = parse_and_validate(ticker, docs, stage)
                    overlap = passage_ids.intersection(x["passage_id"] for x in passages)
                    if overlap:
                        raise CoverageError(f"{ticker}: passage IDs conflict with another company")
                    passage_ids.update(x["passage_id"] for x in passages)
                    found.append(ticker)
                    selected_docs.extend(docs)
                    selected_passages.extend(passages)
                    selected_summaries.extend(summaries)
                    if ticker not in existing:
                        newly_downloaded.extend(docs)
                    record.update(details)
                    print(f"  PASS: {len(passages)} passages, three filing periods", flush=True)
                except Exception as exc:  # One company's failure must not abort replacement search.
                    record["reason"] = f"{type(exc).__name__}: {exc}"[:900]
                    print(f"  EXCLUDED: {record['reason']}", flush=True)
                report["attempts"].append(record)
                _write_json(stage / "selection_audit_progress.json", report)
            report["selection"][sector] = found
            if len(found) < target_per_sector:
                raise CoverageError(f"{sector}: only {len(found)}/{target_per_sector} companies passed; queue exhausted")
        expected_docs = len(initial) * target_per_sector * 3
        if len(selected_docs) != expected_docs or len(selected_summaries) != expected_docs:
            raise CoverageError(f"Incomplete coverage: {len(selected_docs)} filings; expected {expected_docs}")
        for record in selected_docs:
            safe_document_path(record, stage)
        # Copy only accepted new documents to regular cache, without replacing any.
        _publish_new_docs(newly_downloaded, stage, repo_root)
        # Assemble immutable release, publish a pointer only when EVERYTHING succeeds.
        release.mkdir(parents=True, exist_ok=False)
        _write_json(release / "10k_verified_manifest.json", selected_docs)
        _write_jsonl(release / "10k_verified_passages.jsonl", selected_passages)
        _write_json(release / "10k_verified_parse_summary.json", selected_summaries)
        report.update(status="PASS", selected_companies=sum(map(len, report["selection"].values())),
                      selected_filings=len(selected_docs), selected_passages=len(selected_passages),
                      note="PARSER_VALIDATED only; not blanket certification of numerical correctness")
        _write_json(release / "selection_audit.json", report)
        current = base / "current.json"
        ptr_tmp = base / (".current." + token + ".tmp")
        _write_json(ptr_tmp, {"schema": "analystdesk-verified-coverage-pointer-v1",
                              "run_id": token, "release": str(release.relative_to(repo_root)).replace("\\", "/"),
                              "manifest": str((release / "10k_verified_manifest.json").relative_to(repo_root)).replace("\\", "/"),
                              "corpus": str((release / "10k_verified_passages.jsonl").relative_to(repo_root)).replace("\\", "/"),
                              "audit": str((release / "selection_audit.json").relative_to(repo_root)).replace("\\", "/")})
        ptr_tmp.replace(current)
        print(f"SUCCESS: {report['selected_companies']} companies, {len(selected_docs)} filings, {len(selected_passages)} passages", flush=True)
        print(f"Canonical expanded corpus: {release / '10k_verified_passages.jsonl'}", flush=True)
        print(f"Version pointer: {current}", flush=True)
        return report
    except Exception as exc:
        report["status"] = "INCOMPLETE_NOT_PUBLISHED"
        report["failure"] = f"{type(exc).__name__}: {exc}"
        _write_json(stage / "selection_audit_failed.json", report)
        print(f"NOT PUBLISHED: {report['failure']}", file=sys.stderr, flush=True)
        print(f"Diagnostic: {stage / 'selection_audit_failed.json'}", file=sys.stderr, flush=True)
        raise


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Isolated fail-closed SEC 10-K coverage selector")
    p.add_argument("--target-per-sector", type=int, default=6,
                   help="6 gives 12 companies/36 filings; 5 gives 10/30")
    p.add_argument("--repo-root", default=".")
    args = p.parse_args(argv)
    try:
        build(Path(args.repo_root), target_per_sector=args.target_per_sector)
        return 0
    except (CoverageError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
