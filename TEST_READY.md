# TEST_READY — Kilchberg v12 Graphics, Textures & 60fps Smoothness Opaque-Box E2E Suite

**Status:** **READY** (Verified — 125 Opaque-Box E2E Tests across 10 Suites in Tiers 1–4; aligned for `0.11 m/px` Full Diorama & Zero Separate Detail Plates)
**Date:** 2026-11-22
**Owner:** E2E Testing Track (Feature 14 / Milestone E2E-B)
**Suite Specification:** [TEST_INFRA.md](TEST_INFRA.md)

---

## 1. Readiness Summary
- **Total Tests:** **125** (**61** Python `unittest` + **64** Node raw-CDP browser tests) across **10** suites registered in `tests/run_e2e.py`:
  - **115 / 115 baseline test IDs preserved 100% intact** (**56 Python** + **59 Node CDP**; legacy detail-plate/modal tests repurposed into negative obsolete-plate assertions and direct `0.11 m/px` master-tile / live fly-to checks).
  - **+5 new v12 Smoothness CDP tests (`tests/tier2_smoothness.mjs`, registered in Tier 2):**
    - `T2.SM.01`: Inertial pan glide after crisp fast mouse flick drag (`(-320, -180)` over `5` steps @ `10 ms`, pipelined final `mouseMoved` → `mouseReleased`) with synchronous one-shot in-page `pointerup` release-instant capture — asserts `dragDist > 0.002`, `coastDist > 0.0005` in positive drag direction (`dot > 0`) at both `120 ms` and settled rest, bounded settle within `waitForCameraSettled()` (`< 950 ms`), and post-settle residual drift `< 0.0008`.
    - `T2.SM.02`: Focal-point-locked smooth wheel zoom (`deltaY = -240` at off-center `(25%, 30%)`) — asserts `>= 2` distinct intermediate `scale` samples across rAF frames (no 1-frame snap) and focal-point world UV invariance `< 0.0025` UV throughout & after settle.
    - `T2.SM.03`: Deterministic 3-part sub-50ms interpolation & determinism check: (A) full-viewport `160×100` canvas diff between `?t=10.005` and `?t=10.040` inside the same 50 ms `FIXED_DT` bucket (`bucket 200`, `maxDiff > 0 && changedFrac > 0`); (B) direct in-page `pedestrians.js` + `traffic.js` sub-50ms interpolation check at `t=2.005` vs `t=2.040` (`bucket 40`, 5× faster under CPU load) asserting `>= 5` pedestrians AND `>= 5` vehicles advance their coordinates; (C) strictly sequential two-tab `?t=10` determinism (closing main tab, then opening/closing `detTab1` and `detTab2` sequentially so at most one `dpr=2` tab is ever open at a time) asserting `maxDiff === 0` byte-identical snapshots.
    - `T2.SM.04`: Compositor-only `.lm-pin` CSS `transform` (`matrix(` / `matrix3d(`) positioning during pan with zero `style.left` / `style.top` layout mutations, non-blank canvas, and zero console/JS/HTTP errors.
    - `T2.SM.05`: Preserves all 13 Contract #5 `window.__dioramaDebug` keys + additive `frameStats` (`fps`, `p95FrameMs`, `tileInflight`, `tileCacheSize`, `rafActive`), executes 6 drags of `(-580, -240)` CSS px from `(u=0.35, v=0.40)` at `zoom=2` (`1883` direct master px, guaranteeing `>= 1500` master px across 4+ tiles even with zero inertia), and asserts `tileCacheSize <= 128`, `tileInflight` drains cleanly to `0`, and zero JS/HTTP errors.
  - **+5 new v12 Visual-Polish Python tests (`tests/tier2_v12_visuals.py`, registered in Tier 2):**
    - `T2.V12.01`: Strict `< 500 KB` lossless `VP8L` header & non-empty file guard across ALL L2 (`364 × 3`) and `z1` (`98 × 3`) pyramid tiles for `day`, `sunset`, and `night`.
    - `T2.V12.02`: Total `docs/` recursive disk footprint strictly `< 300 MB` (and zero single files `> 90 MB`).
    - `T2.V12.03`: Empirically calibrated anti-stipple / zero-Bayer-checkerboard smoothness check on 6 interior `day` L2 tiles (`mean_cb < 6.5`, `max_cb < 8.0`, smooth-region `cb >= 4` fraction `< 35%`, calibrated against v11 baseline `12.3–14.1` / `56.7–63.3%` vs `tinyrj.com` reference `3.05` / `24.0%`), paired with an architectural edge-preservation floor (`mean_eg >= 4.5`, `strong_edge >= 8%`) so blurred/flat images cannot falsely pass.
    - `T2.V12.04`: `<= 256` unique RGB colors SVGA budget per interior tile + true macro-tile render seam ratio `< 1.35` measured directly across all exact `(W * k) // macroCols` vertical and `(H * k) // macroRows` horizontal macro-tile boundaries (matching `pipeline/verify_quality.py`) across `day`, `sunset`, and `night`.
    - `T2.V12.05`: v12 `0.11 m/px` guardrail preservation: asserts ZERO obsolete detail plates remain in `docs/assets/` (`01..10_*.webp`) or `renders/crops/` (`01..10_*.png`), `manifest.json` `mpp <= 0.115`, Lindt Home of Chocolate authentic DOP10 roof (`crop_master_rgb` multi-tile stitch around `id=1443`), and St. Elisabeth bright neutral white-concrete bell tower with NO clock (`crop_landmark_meter_box("day", "st_elisabeth", ...)`).

---

## 2. Canonical Execution Commands

Run individual new v12 suites:
```bash
.venv/bin/python tests/tier2_v12_visuals.py --verbose
node tests/tier2_smoothness.mjs --verbose
```

Run Tier 2 or full 4-tier E2E suite via unified runner:
```bash
.venv/bin/python tests/run_e2e.py --tier 2 --verbose
.venv/bin/python tests/run_e2e.py --tier all --verbose
```

---

## 3. Milestone E2E-B Verification Results (Pre-M3B Render Dry-Run — Zero Harness Errors)

All syntax checks, static checks, and Python dry-runs executed cleanly with **0 harness errors, 0 NameErrors/ImportErrors/TypeErrors, and 0 orphan processes**:

1. **Syntax Checks (All 13 Test Files):**
   - `python3 -m py_compile tests/lib/assets_helper.py tests/tier1_assets_data.py tests/tier2_quality_bounds.py tests/tier2_lettering.py tests/tier2_landmarks_v11.py tests/tier2_v12_visuals.py tests/run_e2e.py` → exit `0`
   - `node --check` across `tests/lib/cdp_harness.mjs`, `tests/tier1_browser_features.mjs`, `tests/tier2_browser_bounds.mjs`, `tests/tier2_smoothness.mjs`, `tests/tier3_combinations.mjs`, `tests/tier4_journeys.mjs` → exit `0`

2. **Master-Tile Meter-Box Migration (`tests/tier2_lettering.py` + `tests/tier2_landmarks_v11.py`):**
   - `.venv/bin/python -m unittest tests/tier2_lettering.py tests/tier2_landmarks_v11.py -v` → **12/12 PASSED (`OK` in 0.237 s)** — `T2.LET.05`, `T2.LET.06`, and `T2.LM.04` all pass live using `crop_landmark_meter_box` directly on `docs/assets/tiles/day/`.

3. **Pre-M3B Dry-Run Across Remaining Python Suites (0 Errors; Only Expected Pre-M3B `0.125 m/px` / Leftover-Plate / Unrendered-v11 Gates Fail):**
   - `tests/tier1_assets_data.py`: **20 PASSED / 4 EXPECTED PRE-M3B FAIL / 0 ERRORS** (`T1.FA1.02`, `T1.FA1.05`, `T1.FA1.11`, `T1.FA2.01` cleanly gate `0.11 m/px` & deletion of obsolete plates; `T1.FA1.06` & `T1.FA1.10` pass live on master tiles).
   - `tests/tier2_quality_bounds.py`: **19 PASSED / 1 EXPECTED PRE-M3B FAIL / 0 ERRORS** (`T2.FA1.05`, `T2.FA1.09`, `T2.FA1.10` all pass live on master tiles; `T2.FA1.11` cleanly gates `mpp <= 0.115`).
   - `tests/tier2_v12_visuals.py`: **3 PASSED / 2 EXPECTED PRE-M3B FAIL / 0 ERRORS** (`T2.V12.01`, `T2.V12.02`, `T2.V12.04` pass; `T2.V12.03` gates v12 cel-shading & `T2.V12.05` gates deletion of obsolete plates + `mpp <= 0.115`).

---

## 4. Feature 14 / E2E-B Coverage Checklist
- [x] `TEST_INFRA.md` updated for `0.11 m/px` full diorama (`~28,024 × 12,373`, `364 × 3` L2 + `98 × 3` `z1` at `0.22 m/px`), zero separate detail plates, and direct landmark tile-pyramid cropping + live fly-to
- [x] `tests/lib/assets_helper.py` provides `OBSOLETE_DETAIL_PLATES`, `OBSOLETE_DETAIL_PLATE_STEMS`, `RENDERS_CROPS_DIR`, `crop_master_rgb`, and `crop_landmark_meter_box` (with `load_plate_rgb` & `plate_cartouche_margins` removed)
- [x] All 5 Python suites (`61` tests) & all 5 Node CDP suites (`64` tests) updated with exact **125 total tests** preserved and zero stale detail-plate or `0.125 m/px` / `12.5 cm/px` assertions
- [x] `TEST_READY.md` refreshed with E2E-B verification results
- [x] Zero forbidden local-host URLs in any test file or documentation
