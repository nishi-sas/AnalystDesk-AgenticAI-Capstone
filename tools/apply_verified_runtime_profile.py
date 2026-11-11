"""Fail-closed, idempotent, anchored installation of the opt-in verified profile."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "src" / "analyst_desk"


def transform(path: Path, anchor: str, replacement: str, signature: str) -> tuple[bool, str]:
    raw = path.read_text(encoding="utf-8")
    if signature in raw:
        return False, raw
    if raw.count(anchor) != 1:
        raise RuntimeError(f"Unexpected code structure in {path.name}; no files changed")
    return True, raw.replace(anchor, replacement)


def main() -> None:
    helper = BASE / "verified_runtime_profile.py"
    if not helper.is_file():
        raise RuntimeError("Extract ZIP into project root before running this installer")
    stage4a = BASE / "stage4a_config.py"
    stage4b = BASE / "stage4b_cli.py"
    a_anchor = "return PlannerSettings(model=model, base_url=base_url, token_budget=budget, allowed_tickers=tuple(dict.fromkeys(tickers)))"
    a_replacement = ("from .verified_runtime_profile import permitted_company_tickers\n"
                     "    company_allowlist = permitted_company_tickers(root, tuple(dict.fromkeys(tickers)))\n"
                     "    return PlannerSettings(model=model, base_url=base_url, token_budget=budget, allowed_tickers=company_allowlist)")
    b_anchor = "kb = FilingsKnowledgeBase(self.root / 'data' / 'parsed' / '10k_passages.jsonl', self.root / 'data' / 'retrieval_index')"
    b_replacement = ("from .verified_runtime_profile import knowledge_base_paths\n"
                     "            corpus_path, index_path = knowledge_base_paths(self.root)\n"
                     "            kb = FilingsKnowledgeBase(corpus_path, index_path)")
    patches = [
        (stage4a, a_anchor, a_replacement, "company_allowlist = permitted_company_tickers("),
        (stage4b, b_anchor, b_replacement, "corpus_path, index_path = knowledge_base_paths("),
    ]
    planned = [(path, *transform(path, anchor, replacement, sig)) for path, anchor, replacement, sig in patches]
    # Preflight every backup destination before making any mutation.
    for path, needs_patch, _ in planned:
        backup = path.with_name(path.name + ".before_verified_runtime_profile.bak")
        if needs_patch and backup.exists():
            raise RuntimeError(f"Backup already exists: {backup}; no overwrite permitted")
    for path, needs_patch, content in planned:
        if not needs_patch:
            print(f"Already installed: {path.relative_to(ROOT)}")
            continue
        backup = path.with_name(path.name + ".before_verified_runtime_profile.bak")
        backup.write_bytes(path.read_bytes())
        path.write_text(content, encoding="utf-8")
        print(f"Patched: {path.relative_to(ROOT)} | backup: {backup.relative_to(ROOT)}")
    print("Opt-in only. No env variable set: original MSFT/GOOGL runtime remains unchanged.")


if __name__ == "__main__":
    main()
