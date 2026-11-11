# AnalystDesk — Presentation scope and phased format support

## Suggested slide title

**Reliable-by-Design SEC Coverage: Validated Formats First**

## Slide content (copy/paste)

> **Current scope:** AnalystDesk analyses SEC Form 10-K disclosures only when its parser can reliably extract and validate Items 1A (Risk Factors), 7 (MD&A) and 8 (Financial Statements) for each required reporting period. Unsupported filing layouts are excluded rather than interpreted through guessed section boundaries.
>
> **Coverage strategy:** The ingestion pipeline automatically replaces a company whose annual filings fail validation with a previously unused candidate from the same sector. A company is admitted only after three annual filings pass the structural and provenance checks.
>
> **Future extension:** Support for alternative SEC filing layouts—including financial statements incorporated by cross-reference—will be introduced incrementally, with filing-specific parsers, regression tests and evaluation before adding new companies to the supported universe.

## Presenter notes (brief)

The prototype prioritizes evidence integrity over universal document compatibility. For example, Oracle's FY2025 10-K uses an Item 8 cross-reference to Part IV; the current parser correctly fails rather than assuming the financial-statement boundaries. We document such exclusions, choose another eligible company, and preserve the evaluation baseline. Structural parser validation is not identical to a human-reviewed financial audit; broader semantic QA is planned.

## One-sentence interface disclaimer

*AnalystDesk supports SEC filings that pass validated section-extraction and provenance checks; unsupported layouts are excluded, and additional formats will be added through phased validation.*
