"""Apply an additive, idempotent SEC historical submissions fallback to EdgarClient.

No downloader, research, or filing data is changed. Original source is backed up.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPLACEMENT = '''    def annual_filings(self, ticker: str, years: int = 3) -> list:
        """Return the newest distinct annual 10-Ks, consulting SEC history if needed.

        The SEC /submissions/CIK....json recent table covers a rolling window.
        Older records are in filings.files pages. Fetch only as many history
        pages as needed, using the existing cache-first/rate-limited _json.
        """
        from analyst_desk.contracts import Filing

        if type(years) is not int or years < 1:
            raise EdgarError("years must be a positive integer")
        cik, company = self.ticker_to_cik(ticker)
        payload = self.submissions(cik)
        filings_group = payload.get("filings", {})
        if not isinstance(filings_group, dict):
            raise EdgarError("Invalid SEC submissions filings object")
        company_name = payload.get("name") or company
        keys = ("form", "accessionNumber", "filingDate", "reportDate", "primaryDocument")

        def read_rows(table: dict) -> list[Filing]:
            if not isinstance(table, dict):
                raise EdgarError("Invalid SEC submissions columnar table")
            forms = table.get("form", [])
            if not isinstance(forms, list):
                raise EdgarError("Invalid SEC submissions form column")
            found = []
            for idx, form in enumerate(forms):
                # Exactly 10-K: amendments are not separate annual reports.
                if form != "10-K":
                    continue
                try:
                    row = {key: table[key][idx] for key in keys}
                except (IndexError, KeyError, TypeError):
                    continue
                if not all(isinstance(row[key], str) and row[key].strip() for key in keys):
                    continue
                found.append(Filing(
                    ticker=ticker.upper(), cik=cik, company=company_name,
                    accession=row["accessionNumber"],
                    filing_date=row["filingDate"], report_date=row["reportDate"],
                    primary_document=row["primaryDocument"],
                ))
            return found

        records = read_rows(filings_group.get("recent", {}))

        def newest_unique() -> list[Filing]:
            records.sort(key=lambda v: (v.report_date, v.filing_date, v.accession), reverse=True)
            unique = {}
            for filing in records:
                unique.setdefault(filing.report_date, filing)
            return list(unique.values())[:years]

        result = newest_unique()
        if len(result) < years:
            pages = filings_group.get("files", [])
            if not isinstance(pages, list):
                raise EdgarError("Invalid SEC historical submissions index")
            # Prefer the newest historical page if several are advertised.
            pages = sorted(pages, key=lambda p: str(p.get("filingTo", "")) if isinstance(p, dict) else "", reverse=True)
            for page in pages:
                name = page.get("name") if isinstance(page, dict) else None
                # Allow only a historical SEC page for this *same* CIK;
                # never turn untrusted JSON into a URL or local filesystem path.
                if not isinstance(name, str) or re.fullmatch(
                    rf"CIK{cik:010d}-submissions-[0-9]+[.]json", name
                ) is None:
                    raise EdgarError("Invalid SEC historical submissions filename")
                history = self._json(
                    f"{DATA_URL}/submissions/{name}",
                    self.cache_dir / "submissions" / name,
                )
                records.extend(read_rows(history))
                result = newest_unique()
                if len(result) >= years:
                    break
        if len(result) < years:
            raise EdgarError(
                f"Only {len(result)} usable 10-K fiscal years for {ticker}; requested {years}. "
                "Recent and available historical SEC submission pages were checked."
            )
        return result
'''


def main() -> None:
    source = Path('src/analyst_desk/sec_client.py')
    if not source.is_file():
        raise SystemExit(f'Run from AnalystDesk project root; missing {source}')
    contents = source.read_text(encoding='utf-8')
    if 'newest distinct annual 10-Ks, consulting SEC history if needed' in contents:
        print('Historical submissions fix already applied; no changes made')
        return
    tree = ast.parse(contents)
    klasses = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'EdgarClient']
    if len(klasses) != 1:
        raise SystemExit('Expected precisely one EdgarClient class; refusing to modify')
    methods = [node for node in klasses[0].body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'annual_filings']
    if len(methods) != 1:
        raise SystemExit('Expected precisely one annual_filings method; refusing to modify')
    if 'import re\n' not in contents or 'DATA_URL =' not in contents:
        raise SystemExit('Expected SEC client dependencies missing; refusing to modify')
    method = methods[0]
    lines = contents.splitlines(keepends=True)
    old_block = ''.join(lines[method.lineno - 1: method.end_lineno])
    if 'filings.sort(' not in old_block or 'submissions(cik)' not in old_block:
        raise SystemExit('Unknown annual_filings implementation; refusing to modify')
    updated = ''.join(lines[:method.lineno - 1]) + REPLACEMENT.rstrip('\n') + '\n' + ''.join(lines[method.end_lineno:])
    ast.parse(updated)
    backup = source.with_suffix('.py.before_sec_history_fix.bak')
    if backup.exists():
        raise SystemExit(f'Backup already exists at {backup}; refusing to overwrite')
    backup.write_text(contents, encoding='utf-8')
    source.write_text(updated, encoding='utf-8')
    print(f'Historical fallback applied to {source}; original preserved as {backup}')
    print('No checkpoint, filing HTML, downloader, or cache content was altered')


if __name__ == '__main__':
    main()
