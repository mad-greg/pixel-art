# TEST_READY — Kilchberg v10 Opaque-Box E2E Suite

**Status:** **READY** (Verified — 110 Opaque-Box E2E Tests across Tiers 1–4)
**Date:** 2026-11-21
**Owner:** E2E Testing Track (`e2e_v10_writer_2` — Iteration 2)
**Suite Specification:** [TEST_INFRA.md](TEST_INFRA.md)

---

## 1. Readiness Summary
- **Total Tests:** **110** (**51** Python `unittest` + **59** Node raw-CDP browser tests)
  - **104 / 104 existing v9.4 baseline tests preserved 100% intact** (48 Python including the 7 lettering tests `T2.LET.01`–`T2.LET.07` + 56 Node CDP; zero deleted, skipped, or weakened guardrail assertions).
  - **Metadata-driven v10 alignment** in `tests/lib/assets_helper.py` (`get_canvas_dims()`, `get_overview_dims()`, `get_master_mpp()`, `plate_cartouche_margins()`, `clear_caches()`, meter-consistent `distance_to_exterior_sky_m` and `uv_pixel_distance`) and Python tests (`T1.FA1.01–04,06,10,11`, `T1.FA2.01,10`, `T2.FA1.02–03,05–10`, `T2.FA2.01`, `T2.LET.05–06`) including parallel `ThreadPoolExecutor` decoding for all L2 + `z1` pyramid tiles in `T1.FA1.03` and `cs=1`/`cs=2` cartouche-scaled plate margins across all 5 plate checks.
  - **+6 new Kilchberg v10 opaque-box tests** (+3 Python, +3 Node CDP) covering every v10 requirement in `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` & `§ Interface Contracts` strictly via public interfaces:
    - **Tier 1 Python (+1):** `T1.FA1.11` (≥2× resolution contract: `manifest.mpp <= 0.125`, `width >= 24000`, `height >= 10600` across all 3 presets, `kilchberg_interactive.json` & `kilchberg_animations.json` parity, finite positive `shift_y`, and all 10 detail plates `>= 3200×2200` lossless `VP8L` RGB `<= 256` colors).
    - **Tier 2 Python (+2):**
      - `T2.FA1.11` (high-frequency sharpness & genuine ≥2× detail on central `0.125 m/px` tiles: 1px luma gradient energy + anti-2×-nearest-neighbor-upscale 2×2 block duplication ratio check).
      - `T2.FA1.12` (GitHub Pages & asset footprint budget guard: `docs/ < 300 MB`, every tile `< 500 KB`, `kilchberg_animations.json < 650 KB`, `kilchberg_depth.png < 10 MB`, zero files `> 90 MB`).
    - **Tier 2 Browser (+1):** `T2.FA3.11` (overview `Fit` fetches `0` high-res L2 tiles on `1280×800@2x`, bounded `1..48` L2 tile fetches on `1:1` zoom-in, non-blank RGB variance across `Fit → 1:1 → 2× → 4×`, zero JS/console/HTTP errors).
    - **Tier 3 Browser (+2):**
      - `T3.12` (2× resolution live sprite physical-scale & depth-alignment check on SBB train and ZVV bus at `zoom=1` [settled via `zoom=2` + `#btn-zoom-1x`] and `zoom=2`, asserting both lower and upper `dbg.scale` bounds `[zoom*0.9, zoom*1.15]`, guarding against `wScale` 50% shrink and verifying `< 6%` roof perforation).
      - `T3.13` (inspector `#spec-fidelity` reports `12.5 cm/px` — not `25` or rounded `13 cm/px` — and metric scale bar `#scale-bar-label` / `#scale-bar-line` reports `~0.125 m/CSS-px` at `1:1` and halves cleanly from `1:1` to `2×`).

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

## 3. Verified Snapshot on Pre-M2/M3 (v9.4) Baseline Assets
Verified via `.venv/bin/python tests/run_e2e.py --tier all --verbose`:
- **Syntax checks (`py_compile` + `node --check`):** exit `0` (`SYNTAX_OK`)
- **Full Suite Summary:** `110 tests | 102 PASSED | 8 FAILED | 0 ERRORS | 0 TIMEOUTS | 196.74 s`
  - **Tier 1 Python (`tier1_assets_data`):** 21 PASSED, 3 FAILED (`T1.FA1.02`, `T1.FA1.11`, `T1.FA2.01`), 0 ERRORS (10.73 s)
  - **Tier 1 Browser (`tier1_browser_features`):** 17 PASSED, 0 FAILED, 0 ERRORS (19.68 s)
  - **Tier 2 Python (`tier2_quality_bounds`):** 18 PASSED, 2 FAILED (`T2.FA1.11`, `T2.FA1.12`), 0 ERRORS (11.30 s)
  - **Tier 2 Lettering (`tier2_lettering`):** 7 PASSED, 0 FAILED, 0 ERRORS (0.75 s)
  - **Tier 2 Browser (`tier2_browser_bounds`):** 15 PASSED, 1 FAILED (`T2.FA3.11`), 0 ERRORS (36.11 s)
  - **Tier 3 Browser (`tier3_combinations`):** 11 PASSED, 2 FAILED (`T3.12`, `T3.13`), 0 ERRORS (71.54 s)
  - **Tier 4 Browser (`tier4_journeys`):** 13 PASSED, 0 FAILED, 0 ERRORS (68.12 s)
- **Baseline Preservation Check:** All **102 / 102** non-v10-gating baseline tests pass (including `T1.FA1.03` parallel tile decoding and `T2.LET.01`–`T2.LET.07` fractional lettering coordinates).
- **8 Clean `AssertionError` Failures Gating M2 & M3:**
  1. `T1.FA1.02` — `day manifest width 12331 < 24000 (v10 >=2x)` (gates M2)
  2. `T1.FA1.11` — `day manifest mpp 0.25 > 0.125 (v10 >=2x)` (gates M2)
  3. `T1.FA2.01` — `interactive canvas_width 12331 < 24000 (v10 >=2x)` (gates M2)
  4. `T2.FA1.11` — `day manifest mpp=0.25 > 0.125 (v10 >=2x required)` (gates M2)
  5. `T2.FA1.12` — catches v9.4 dense tiles exceeding `< 500 KB` budget (`day/9_1.webp 524.4 KB`, etc.) (gates M2 tile compactness)
  6. `T2.FA3.11` — catches v9.4 cold-boot `Fit` race fetching `12` L2 tiles while `!ov` is loading (gates M3 2-level pyramid / overview boot guard)
  7. `T3.12` — `Expected v10 manifest.mpp <= 0.125 for 2x sprite scale check, got 0.25` (gates M2/M3)
  8. `T3.13` — `Expected #spec-fidelity to report '12.5 cm/px', got '25 cm/px · 12,331×5,444'` (gates M3)
- **Orphan Process Check:** `0` live Chromium/Node processes remaining.
