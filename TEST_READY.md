# TEST_READY — Kilchberg v8.0 Opaque-Box E2E Suite

**Status:** **READY** (Verified & Audited — 83 Opaque-Box E2E Tests across Tiers 1–4)
**Date:** 2026-11-20
**Owner:** E2E Testing Track (`e2e_orch_1`)
**Suite Specification:** [TEST_INFRA.md](TEST_INFRA.md)

---

## 1. Readiness Summary
- **Total Tests:** **83** (36 Python `unittest` + 47 Node raw-CDP browser tests)
  - **70 / 70 existing v7.0 baseline tests preserved 100% intact** (zero deleted, skipped, or weakened assertions; verified line-by-line by Forensic Auditor).
  - **+13 new Kilchberg v8.0 opaque-box tests** (+4 Python, +9 Node CDP) covering every feature in `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` strictly via public interfaces (`docs/assets/kilchberg_depth.png`, `docs/data/kilchberg_animations.json`, `docs/index.html`, `docs/**/*.js`, browser canvas/DOM, `window.__dioramaDebug` Contract #5 + `livingCounts` + `depthStats` + `simStats`).
- **Runner Hardening:** Default per-suite `--timeout` in `tests/run_e2e.py` raised to `120 s` to accommodate the expanded Tier 2/3/4 browser suites without timeouts.

## 2. Canonical Execution Command
```bash
cd /home/antigravity/mad-greg/pixel-art && .venv/bin/python tests/run_e2e.py --tier all --verbose
```

Targeted tier runs:
```bash
cd /home/antigravity/mad-greg/pixel-art && .venv/bin/python tests/run_e2e.py --tier 1 --verbose
cd /home/antigravity/mad-greg/pixel-art && .venv/bin/python tests/run_e2e.py --tier 2 --verbose
cd /home/antigravity/mad-greg/pixel-art && .venv/bin/python tests/run_e2e.py --tier 3 --verbose
cd /home/antigravity/mad-greg/pixel-art && .venv/bin/python tests/run_e2e.py --tier 4 --verbose
```

## 3. Verified Snapshot at Publication (M1 & M2 Landed; M3 & M4 Pending)
Independent verification by `e2e_reviewer_3` (`tests/run_e2e.py --tier all --verbose`):
- **Syntax checks (`py_compile` + `node --check`):** `SYNTAX_OK` (exit `0`)
- **Total:** `83 tests | 74 PASSED | 9 FAILED | 0 ERRORS | 0 TIMEOUTS`
- **Baseline Regression Check:** **70 / 70 PASS** (0 regressions)
- **New v8.0 Tests Already Passing (4 / 13):**
  - `T1.FA1.08` — Depth map open-air roof small hits (`< 2%` trains, `< 1%` main roads) & `0.12 <= occ_frac <= 0.35` (PASS against M1)
  - `T1.FA2.09` — `kilchberg_animations.json` `< 650 KB` & Contract #2 `network` schema (PASS against M2)
  - `T2.FA2.07` — `network` UV `[0,1]`, non-spiking `d16`, inside `island_2x`, zero Lake Zurich water intrusion (PASS against M2)
  - `T2.FA3.09` — SUP `waterMaskReady` & realistic diurnal count guardrail (PASS)
- **Remaining v8.0 Tests Ready to Gate M3 & M4 (9 / 13 — cleanly failing with `AssertionError` until M3/M4 land):**
  - `T1.FA1.09` — ES module `<script type="module" src="app.js?v=...">`, synced `?v=`, `docs/js/` modules (gates M3)
  - `T1.FA3.13` — `window.__dioramaDebug.simStats` schema + Contract #5 + zero ES module 404s (gates M3)
  - `T2.FA3.07` — Realistic daytime vehicle/pedestrian density bounds via `simStats` (gates M3/M4)
  - `T2.FA3.08` — Active 1D IDM car-following / bus-dwell braking & non-gridlock invariant (gates M3)
  - `T3.07` — Cross-tab deterministic `?t=10` canvas + `simStats` identity vs `?t=15` motion delta (gates M3)
  - `T3.08` — Diurnal activity shift across `day` / `sunset` / `night` (gates M3/M4)
  - `T3.09` — 2× zoom `?follow=train` & `?follow=bus` roof opacity (`holeFrac < 0.06`) + foreground occlusion (gates M1/M3 runtime `drawDepthMasked`, currently catching `bus holeFrac=6.64%`)
  - `T3.10` — Church bell `bellPhase` ↔ `audioGains.bells` sync + `Live: Off` spatial audio updates (gates M4)
  - `T4.07` — Journey 7: Living Kilchberg commuter & village life (Bahnhof, Follow Train/Bus, Pier/Lindt/Seebad, entity trip inspection, zero layout clipping) (gates M4)

## 4. Verification Sign-Off
- **Forensic Auditor (`e2e_auditor_2`):** `CLEAN`
- **Primary Reviewer (`e2e_reviewer_3`):** `APPROVE`
- **Secondary Reviewer (`e2e_reviewer_4`):** `APPROVE`
- **Python Challenger (`e2e_challenger_3`):** `CONFIRMED` (empirically verified `get_lake_zurich_mask_2x()` + 16/16 synthetic failure-injection probes on `T2.FA2.07`)
- **Browser Challenger (`e2e_challenger_4`):** `CONFIRMED` (empirically verified `analyzeVehicleRoofOpacity()` catches 2–4px vertical/horizontal/diagonal cutouts with 0.00% false positives on clean roofs and `>= 10px` foreground occluders, and verified `T4.07` flake elimination)
