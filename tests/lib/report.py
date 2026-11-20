"""Unified structured reporting and unittest runner for the 4-tier E2E suite."""

from __future__ import annotations

import json
import sys
import time
import unittest
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional


@dataclass
class TestCaseResult:
    id: str
    name: str
    status: str  # "PASS" | "FAIL" | "ERROR"
    duration_ms: float
    message: str = ""


@dataclass
class TierResult:
    tier: int
    suite: str
    elapsed_ms: float
    tests: List[TestCaseResult] = field(default_factory=list)
    timed_out: bool = False
    runner_error: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for t in self.tests if t.status == "FAIL")

    @property
    def errors(self) -> int:
        return sum(1 for t in self.tests if t.status == "ERROR")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "suite": self.suite,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "timed_out": self.timed_out,
            "runner_error": self.runner_error,
            "tests": [asdict(t) for t in self.tests],
        }


def test_meta(test_id: str, title: str) -> Callable:
    """Attach canonical test ID and human-readable name to a unittest method."""

    def decorator(fn: Callable) -> Callable:
        fn._e2e_id = test_id
        fn._e2e_title = title
        return fn

    return decorator


def _extract_test_meta(test: unittest.TestCase) -> tuple[str, str]:
    method_name = getattr(test, "_testMethodName", "")
    method = getattr(test, method_name, None) if method_name else None
    tid = getattr(method, "_e2e_id", None)
    title = getattr(method, "_e2e_title", None)
    if tid and title:
        return tid, title
    return method_name or test.id(), test.shortDescription() or method_name or test.id()


def _concise_failure(err: tuple) -> str:
    exc_type, exc_value, _tb = err
    if exc_type is AssertionError:
        msg = str(exc_value).strip()
        return msg.splitlines()[0] if msg else "Assertion failed"
    name = exc_type.__name__ if exc_type else "Error"
    msg = str(exc_value).strip()
    first = msg.splitlines()[0] if msg else ""
    return f"{name}: {first}" if first else name


class StructuredTestResult(unittest.TestResult):
    """Collects per-test TestCaseResult records with exact timing."""

    def __init__(self, verbose: bool = False) -> None:
        super().__init__()
        self.verbose = verbose
        self.records: List[TestCaseResult] = []
        self._starts: dict[str, float] = {}

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        self._starts[test.id()] = time.perf_counter()

    def _finish(self, test: unittest.TestCase, status: str, message: str = "") -> None:
        t0 = self._starts.pop(test.id(), time.perf_counter())
        dur_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        tid, title = _extract_test_meta(test)
        rec = TestCaseResult(id=tid, name=title, status=status, duration_ms=dur_ms, message=message)
        self.records.append(rec)
        if self.verbose:
            badge = f"[{status:<4}]"
            suffix = f" — {message}" if message else ""
            print(f"  {badge} {tid:<10} {title} ({dur_ms:.0f} ms){suffix}", flush=True)

    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        self._finish(test, "PASS")

    def addFailure(self, test: unittest.TestCase, err: tuple) -> None:
        super().addFailure(test, err)
        self._finish(test, "FAIL", _concise_failure(err))

    def addError(self, test: unittest.TestCase, err: tuple) -> None:
        super().addError(test, err)
        self._finish(test, "ERROR", _concise_failure(err))

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        # Skipping silently is disallowed by our integrity policy; treat as ERROR.
        super().addSkip(test, reason)
        self._finish(test, "ERROR", f"Unexpected skip: {reason}")


def run_unittest_module(
    module: Any,
    tier: int,
    suite_name: str,
    result_json_path: Optional[str] = None,
    verbose: bool = False,
) -> int:
    """Run all unittest.TestCase classes in `module`, optionally writing JSON report."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(module)
    res = StructuredTestResult(verbose=verbose)
    t0 = time.perf_counter()
    suite.run(res)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # Catch module/class setUp errors recorded in res.errors without matching test
    if res.errors and len(res.records) < len(res.errors):
        for test_obj, tb_str in res.errors:
            first_line = tb_str.strip().splitlines()[-1] if tb_str.strip() else "Setup error"
            res.records.append(
                TestCaseResult(
                    id=str(test_obj),
                    name="setup_error",
                    status="ERROR",
                    duration_ms=0.0,
                    message=first_line,
                )
            )

    tier_res = TierResult(
        tier=tier,
        suite=suite_name,
        elapsed_ms=elapsed_ms,
        tests=res.records,
    )

    if result_json_path:
        out_path = Path(result_json_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(tier_res.to_dict(), indent=2), encoding="utf-8")
    else:
        print(format_summary_table([tier_res], elapsed_ms))

    if len(tier_res.tests) == 0 or tier_res.failed > 0 or tier_res.errors > 0:
        return 1
    return 0


def format_summary_table(tier_results: List[TierResult], total_elapsed_ms: float) -> str:
    """Render a crisp ASCII summary table across all executed tiers."""
    lines: List[str] = []
    sep = "=" * 96
    sub = "-" * 96
    lines.append(sep)
    lines.append("KILCHBERG (ZH) DIORAMA — 4-TIER OPAQUE-BOX E2E TEST REPORT")
    lines.append(sep)

    total_pass = 0
    total_fail = 0
    total_err = 0

    for tr in tier_results:
        lines.append(
            f"\n[Tier {tr.tier}] {tr.suite}  "
            f"({tr.passed} passed, {tr.failed} failed, {tr.errors} errors | {tr.elapsed_ms / 1000.0:.2f} s)"
        )
        lines.append(sub)
        if tr.timed_out:
            lines.append(f"  [TIMEOUT] Suite exceeded timeout limit: {tr.runner_error}")
        elif tr.runner_error and not tr.tests:
            lines.append(f"  [ERROR  ] Runner failure: {tr.runner_error}")

        for tc in tr.tests:
            badge = {"PASS": "PASS", "FAIL": "FAIL", "ERROR": "ERR "}.get(tc.status, tc.status[:4])
            dur = f"{tc.duration_ms:6.0f}ms"
            lines.append(f"  [{badge}] {tc.id:<10} {tc.name:<56} {dur}")
            if tc.message and tc.status != "PASS":
                msg = tc.message if len(tc.message) <= 180 else tc.message[:177] + "..."
                lines.append(f"         -> {msg}")

        total_pass += tr.passed
        total_fail += tr.failed
        total_err += tr.errors

    total_run = total_pass + total_fail + total_err
    lines.append("\n" + sep)
    lines.append(
        f"TOTAL: {total_run} tests | {total_pass} PASSED | {total_fail} FAILED | {total_err} ERRORS | "
        f"Wall-clock: {total_elapsed_ms / 1000.0:.2f} s"
    )
    lines.append(sep)
    return "\n".join(lines)


def write_full_json_report(
    path: str,
    tier_results: List[TierResult],
    total_elapsed_ms: float,
    exit_code: int,
) -> None:
    payload = {
        "exit_code": exit_code,
        "total_elapsed_ms": round(total_elapsed_ms, 1),
        "total_tests": sum(len(t.tests) for t in tier_results),
        "total_passed": sum(t.passed for t in tier_results),
        "total_failed": sum(t.failed for t in tier_results),
        "total_errors": sum(t.errors for t in tier_results),
        "suites": [t.to_dict() for t in tier_results],
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_cli_args_for_module(argv: List[str]) -> tuple[Optional[str], bool]:
    result_json = None
    verbose = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--result-json" and i + 1 < len(argv):
            result_json = argv[i + 1]
            i += 2
        elif arg in ("--verbose", "-v"):
            verbose = True
            i += 1
        else:
            i += 1
    return result_json, verbose
