#!/usr/bin/env python3
"""Unified CLI runner for the Kilchberg (ZH) diorama 4-tier opaque-box E2E test suite.

Usage:
  python3 tests/run_e2e.py --tier 1
  python3 tests/run_e2e.py --tier 1,2 --verbose
  python3 tests/run_e2e.py --tier all --json-report /tmp/e2e_report.json --timeout 120

Exit codes:
  0   All requested tiers executed cleanly, total tests > 0, 0 failures, 0 errors.
  1   Any test failure, runtime error, or missing structured result output.
  124 Any suite exceeded --timeout (subprocess group killed via os.killpg).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.lib.report import (
    TestCaseResult,
    TierResult,
    format_summary_table,
    write_full_json_report,
)

# Ordered suite registry per tier: (tier_num, suite_name, runtime_cmd_prefix, script_rel_path)
TIER_SUITES: dict[int, List[Tuple[str, List[str], Path]]] = {
    1: [
        ("tier1_assets_data", [sys.executable], REPO_ROOT / "tests" / "tier1_assets_data.py"),
        ("tier1_browser_features", ["node"], REPO_ROOT / "tests" / "tier1_browser_features.mjs"),
    ],
    2: [
        ("tier2_quality_bounds", [sys.executable], REPO_ROOT / "tests" / "tier2_quality_bounds.py"),
        ("tier2_lettering", [sys.executable], REPO_ROOT / "tests" / "tier2_lettering.py"),
        ("tier2_landmarks_v11", [sys.executable], REPO_ROOT / "tests" / "tier2_landmarks_v11.py"),
        ("tier2_v12_visuals", [sys.executable], REPO_ROOT / "tests" / "tier2_v12_visuals.py"),
        ("tier2_v13_vegetation", [sys.executable], REPO_ROOT / "tests" / "tier2_v13_vegetation.py"),
        ("tier2_browser_bounds", ["node"], REPO_ROOT / "tests" / "tier2_browser_bounds.mjs"),
        ("tier2_smoothness", ["node"], REPO_ROOT / "tests" / "tier2_smoothness.mjs"),
        ("tier2_v13_living", ["node"], REPO_ROOT / "tests" / "tier2_v13_living.mjs"),
    ],
    3: [
        ("tier3_combinations", ["node"], REPO_ROOT / "tests" / "tier3_combinations.mjs"),
    ],
    4: [
        ("tier4_journeys", ["node"], REPO_ROOT / "tests" / "tier4_journeys.mjs"),
    ],
}


def parse_tiers(spec: str) -> List[int]:
    spec_norm = spec.strip().lower()
    if spec_norm == "all":
        return [1, 2, 3, 4]
    tiers: List[int] = []
    for part in spec_norm.split(","):
        part = part.strip()
        if not part:
            continue
        if part not in ("1", "2", "3", "4"):
            raise ValueError(f"Unsupported tier '{part}'. Expected 1, 2, 3, 4, or all.")
        val = int(part)
        if val not in tiers:
            tiers.append(val)
    if not tiers:
        raise ValueError("No valid tiers specified.")
    return tiers


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    # Unconditionally sweep the process group with SIGKILL so zero child/Chromium processes survive
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def run_suite_subprocess(
    tier: int,
    suite_name: str,
    cmd_prefix: List[str],
    script_path: Path,
    tmp_dir: Path,
    timeout_sec: float,
    verbose: bool,
    buffer_output: bool = False,
) -> Tuple[TierResult, str]:
    result_file = tmp_dir / f"tier{tier}_{suite_name}.json"
    cmd = [*cmd_prefix, str(script_path), "--result-json", str(result_file)]
    if verbose:
        cmd.append("--verbose")
        if not buffer_output:
            print(f"\n>>> Running [Tier {tier}] {suite_name} ...", flush=True)

    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=None if (verbose and not buffer_output) else subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    timed_out = False
    stdout_txt = ""
    stderr_txt = ""
    try:
        stdout_txt, stderr_txt = proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(proc)
        try:
            stdout_txt, stderr_txt = proc.communicate(timeout=2.0)
        except Exception:
            pass

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    captured = stdout_txt or ""

    if timed_out:
        return (
            TierResult(
                tier=tier,
                suite=suite_name,
                elapsed_ms=elapsed_ms,
                tests=[],
                timed_out=True,
                runner_error=f"Exceeded {timeout_sec:.0f}s timeout; subprocess group terminated.",
            ),
            captured,
        )

    if not result_file.is_file():
        err_detail = (stderr_txt or stdout_txt or f"Exit code {proc.returncode}").strip()
        first_err = err_detail.splitlines()[-1] if err_detail else f"Exit code {proc.returncode}"
        return (
            TierResult(
                tier=tier,
                suite=suite_name,
                elapsed_ms=elapsed_ms,
                tests=[
                    TestCaseResult(
                        id=f"T{tier}.RUNNER",
                        name=f"{suite_name}_missing_result_json",
                        status="ERROR",
                        duration_ms=round(elapsed_ms, 1),
                        message=f"No result JSON emitted (rc={proc.returncode}): {first_err}",
                    )
                ],
                runner_error=first_err,
            ),
            captured,
        )

    try:
        data = json.loads(result_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return (
            TierResult(
                tier=tier,
                suite=suite_name,
                elapsed_ms=elapsed_ms,
                tests=[
                    TestCaseResult(
                        id=f"T{tier}.RUNNER",
                        name=f"{suite_name}_invalid_result_json",
                        status="ERROR",
                        duration_ms=round(elapsed_ms, 1),
                        message=f"Corrupt result JSON: {exc}",
                    )
                ],
                runner_error=str(exc),
            ),
            captured,
        )

    tests = [
        TestCaseResult(
            id=str(t.get("id", "")),
            name=str(t.get("name", "")),
            status=str(t.get("status", "ERROR")),
            duration_ms=float(t.get("duration_ms", 0.0)),
            message=str(t.get("message", "")),
        )
        for t in data.get("tests", [])
    ]
    return (
        TierResult(
            tier=tier,
            suite=suite_name,
            elapsed_ms=float(data.get("elapsed_ms", elapsed_ms)),
            tests=tests,
            timed_out=False,
            runner_error=str(data.get("runner_error", "")),
        ),
        captured,
    )


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Kilchberg (ZH) Isometric Pixel-Art Diorama 4-Tier Opaque-Box E2E Runner"
    )
    parser.add_argument(
        "--tier",
        default="all",
        help="Tier(s) to run: 1, 2, 3, 4, comma-separated (e.g. 1,2), or 'all' (default: all)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Stream per-test results live as each suite executes",
    )
    parser.add_argument(
        "--json-report",
        default=None,
        help="Optional path to write full machine-readable JSON test report",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-suite timeout in seconds before killing subprocess group (default: 120)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List registered test suites for the selected tier(s) and exit 0",
    )
    args = parser.parse_args(argv)

    try:
        selected_tiers = parse_tiers(args.tier)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.list:
        for tier in selected_tiers:
            for suite_name, cmd_prefix, script_path in TIER_SUITES[tier]:
                runtime = Path(cmd_prefix[0]).name
                rel = script_path.relative_to(REPO_ROOT)
                print(f"Tier {tier}: {suite_name} ({runtime} {rel})")
        return 0

    t_all0 = time.perf_counter()
    results: List[TierResult] = []
    any_timeout = False

    with tempfile.TemporaryDirectory(prefix="kilchberg_e2e_results_") as tmp:
        tmp_dir = Path(tmp)
        for tier in selected_tiers:
            suites = TIER_SUITES[tier]
            if len(suites) <= 1:
                for suite_name, cmd_prefix, script_path in suites:
                    tr, _ = run_suite_subprocess(
                        tier=tier,
                        suite_name=suite_name,
                        cmd_prefix=cmd_prefix,
                        script_path=script_path,
                        tmp_dir=tmp_dir,
                        timeout_sec=args.timeout,
                        verbose=args.verbose,
                        buffer_output=False,
                    )
                    results.append(tr)
                    if tr.timed_out:
                        any_timeout = True
            else:
                # Run Python and Node suites within the tier concurrently while preserving deterministic order
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        (
                            suite_name,
                            pool.submit(
                                run_suite_subprocess,
                                tier,
                                suite_name,
                                cmd_prefix,
                                script_path,
                                tmp_dir,
                                args.timeout,
                                args.verbose,
                                True,
                            ),
                        )
                        for suite_name, cmd_prefix, script_path in suites
                    ]
                    for suite_name, fut in futures:
                        tr, captured = fut.result()
                        if args.verbose:
                            print(f"\n>>> Running [Tier {tier}] {suite_name} ...", flush=True)
                            if captured:
                                print(captured, end="" if captured.endswith("\n") else "\n", flush=True)
                        results.append(tr)
                        if tr.timed_out:
                            any_timeout = True

    total_elapsed_ms = (time.perf_counter() - t_all0) * 1000.0
    print(format_summary_table(results, total_elapsed_ms))

    total_tests = sum(len(r.tests) for r in results)
    total_failed = sum(r.failed for r in results)
    total_errors = sum(r.errors for r in results)
    any_runner_err = any(bool(r.runner_error) for r in results)

    if any_timeout:
        exit_code = 124
    elif total_tests > 0 and total_failed == 0 and total_errors == 0 and not any_runner_err:
        exit_code = 0
    else:
        exit_code = 1

    if args.json_report:
        write_full_json_report(args.json_report, results, total_elapsed_ms, exit_code)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
