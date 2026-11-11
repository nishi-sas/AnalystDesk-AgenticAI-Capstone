# Phase 6D-3 Windows SQLite cleanup hotfix

Two direct sqlite3.connect(...) context managers committed transactions without explicitly closing database file handles. On Windows, TemporaryDirectory cleanup can raise WinError 32 while deleting isolated.sqlite3.

This hotfix only replaces `src/analyst_desk/phase6d3_security.py`: both direct SQLite contexts now use `contextlib.closing` plus SQLite transactional context, guaranteeing handle close before temporary directory cleanup. `PortalService` remains untouched; no change to approval, signing, or publication policies.

From AnalystDesk root (Conda Analystdesk active):

```bat
copy src\analyst_desk\phase6d3_security.py src\analyst_desk\phase6d3_security_pre_winfix.py.bak
python -m pytest -v tests/test_phase6d3_security.py tests/test_phase6d4_acceptance.py > evidence\104a_phase6d3_targeted_retry.txt 2>&1
powershell -NoProfile -Command "Get-Content -Tail 12 'evidence\104a_phase6d3_targeted_retry.txt'"
python -m pytest -v > evidence\105a_phase6d3_full_regression_retry.txt 2>&1
powershell -NoProfile -Command "Get-Content -Tail 12 'evidence\105a_phase6d3_full_regression_retry.txt'"
```

Expected Windows: 34 targeted and 636 overall passed. Run security audit and acceptance only after these pass. Avoid copying real secrets into evidence files.
