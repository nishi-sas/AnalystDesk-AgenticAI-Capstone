"""Stage 3C: read verified annual SEC facts; execute approved math in a child Python process.

The worker uses Python -I -S and accepts only two allowlisted operations, never code.
Process separation + timeout is not a hardened operating-system sandbox.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from analyst_desk.edgar_service import EdgarFactsService

_TICKER = re.compile(r"[A-Z][A-Z0-9.-]{0,9}\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


class InvalidRequest(ValueError):
    pass


class WorkerFailure(RuntimeError):
    pass


def _validate(ticker: str, day: str) -> tuple[str, str]:
    if not isinstance(ticker, str) or not _TICKER.fullmatch(ticker.strip().upper()):
        raise InvalidRequest("Invalid ticker")
    if not isinstance(day, str) or not _DATE.fullmatch(day):
        raise InvalidRequest("Invalid YYYY-MM-DD report date")
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise InvalidRequest("Invalid calendar date") from exc
    return ticker.strip().upper(), day


class CalculationService:
    def __init__(self, cache_dir: str | Path = "data/edgar_cache", *,
                 edgar: EdgarFactsService | None = None, timeout_seconds: float = 8.0,
                 worker_path: str | Path | None = None):
        self.edgar = edgar if edgar is not None else EdgarFactsService(cache_dir, offline=True)
        if not self.edgar.offline:
            raise InvalidRequest("Calculation service requires offline EDGAR cache")
        self.timeout_seconds = timeout_seconds
        self.worker_path = Path(worker_path) if worker_path else Path(__file__).with_name("calc_worker.py")

    def _wrap(self, operation):
        begun = time.perf_counter()
        try:
            data = operation()
            return {"ok": True, "data": data, "error_code": None, "error_message": None,
                    "elapsed_ms": round((time.perf_counter() - begun) * 1000, 2)}
        except InvalidRequest as exc:
            code, message = "INVALID_ARGUMENT", str(exc)
        except WorkerFailure as exc:
            code, message = "WORKER_FAILURE", str(exc)
        except Exception:
            code, message = "INTERNAL_ERROR", "Calculation service failed; inspect server logs"
        return {"ok": False, "data": None, "error_code": code,
                "error_message": message, "elapsed_ms": round((time.perf_counter() - begun) * 1000, 2)}

    def _verified(self, ticker: str, day: str, metric: str) -> dict:
        response = self.edgar.get_annual_fact(ticker, day, metric, years=3)
        if not response["ok"]:
            code = response.get("error_code") or "SEC_DATA_ERROR"
            if code in {"NOT_FOUND", "FACT_UNAVAILABLE", "INVALID_ARGUMENT", "SOURCE_INTEGRITY_ERROR", "SEC_DATA_ERROR"}:
                raise WorkerFailure("Verified annual SEC fact unavailable: " + code)
            raise WorkerFailure("SEC fact service returned an error")
        return response["data"]["fact"]

    def _run(self, operation: str, a: dict, b: dict) -> dict:
        request = json.dumps({"operation": operation, "a": a, "b": b}, separators=(",", ":"))
        if len(request.encode("utf-8")) > 128 * 1024:
            raise InvalidRequest("Calculation request too large")
        # -I ignores PYTHONPATH and user site; -S prevents importing site; fixed trusted file.
        # Minimal environment avoids passing API keys/SEC contact details to the child.
        env = {k: v for k, v in os.environ.items() if k in ("SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TMP", "TEMP")}
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(self.worker_path.resolve())],
                input=request, text=True, encoding="utf-8", capture_output=True,
                timeout=self.timeout_seconds, check=False, env=env,
            )
        except (subprocess.TimeoutExpired, OSError):
            raise WorkerFailure("Calculation worker timed out or could not launch") from None
        if completed.returncode != 0 or len(completed.stdout) > 65536:
            raise WorkerFailure("Calculation worker exited unexpectedly")
        try:
            data = json.loads(completed.stdout)
        except (ValueError, TypeError):
            raise WorkerFailure("Calculation worker returned invalid JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
            raise WorkerFailure("Calculation worker response malformed")
        if not data["ok"]:
            # Only allow worker's fixed rejection codes, not arbitrary tool output.
            if data.get("error_code") == "CALCULATION_REJECTED":
                raise InvalidRequest(str(data.get("error_message", "Invalid facts"))[:200])
            raise WorkerFailure("Calculation worker refused request")
        if not isinstance(data.get("data"), dict):
            raise WorkerFailure("Calculation worker returned no result")
        return {**data["data"], "execution": {"python_isolated_mode": True,
                  "separate_process": True, "arbitrary_code_allowed": False,
                  "os_hardened_sandbox": False}, "source_verified_by": "EDGAR_SHA256_URL_SIDECARS"}

    def calculate_operating_margin(self, ticker: str, report_date: str) -> dict:
        """Compute margin using exactly matched annual revenue and operating income."""
        def work():
            tick, day = _validate(ticker, report_date)
            operating = self._verified(tick, day, "operating_income")
            revenue = self._verified(tick, day, "revenue")
            return self._run("operating_margin", operating, revenue)
        return self._wrap(work)

    def calculate_revenue_growth(self, ticker: str, current_report_date: str,
                                 prior_report_date: str) -> dict:
        """Compute YoY revenue growth for adjacent, nonoverlapping annual SEC periods."""
        def work():
            tick, day = _validate(ticker, current_report_date)
            _, prior = _validate(tick, prior_report_date)
            current = self._verified(tick, day, "revenue")
            prior_fact = self._verified(tick, prior, "revenue")
            return self._run("revenue_growth_yoy", current, prior_fact)
        return self._wrap(work)

    def calc_status(self) -> dict:
        """Describe operational controls; no reads or subprocess calls."""
        return self._wrap(lambda: {
            "allowed_operations": ["operating_margin", "revenue_growth_yoy"],
            "offline_verified_source": self.edgar.offline,
            "python_isolated_mode": True, "subprocess_timeout_seconds": self.timeout_seconds,
            "arbitrary_code_allowed": False,
            "os_hardened_sandbox": False,
            "note": "This is fixed-formula subprocess isolation, not an OS/container security boundary",
        })
