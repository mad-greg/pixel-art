# TEST_READY — Kilchberg v13.0 Modular Living Layer & Botanical Vegetation Opaque-Box E2E Suite

**Status:** **READY** (Verified — 135 Opaque-Box E2E Tests across 12 Suites in Tiers 1–4)
**Date:** 2026-11-22
**Owner:** E2E Testing Track (Feature 11 / Milestone E2E)
**Suite Specification:** [TEST_INFRA.md](TEST_INFRA.md)

---

## 1. Readiness Summary
- **Total Tests:** **135** (**65** Python `unittest` + **70** Node raw-CDP browser tests) across **12** suites registered in `tests/run_e2e.py`:
  - **125 / 125 v12.0 baseline test IDs preserved 100% intact** (**61 Python** + **64 Node CDP**).
  - **+6 new v13.0 Modular Living Layer CDP tests (`tests/tier2_v13_living.mjs`, registered in Tier 2):**
    - `T2.V13.L01`: Modular Living Registry & plugin lifecycle — asserts `window.__dioramaDebug.livingRegistry` exposes `pluginCount >= 10`, unique non-empty `pluginIds` (`length === pluginCount`), `enabledPlugins.length >= 10`, finite non-negative `updateMs`/`drawMs`, integer `drawablesCount > 0`, integer `inspectablesCount > 0`, non-empty `perPluginCounts` keyed only by registered plugin IDs (each value a non-negative integer or plain object of finite non-negative numbers), and zero errors.
    - `T2.V13.L02`: Deterministic `?t=` across all living plugins — opens two sequential fresh `?mode=day&zoom=2&landmark=bendlikon_pier&t=10` tabs, asserts byte-identical canvas (`maxDiff === 0`), identical `livingRegistry.perPluginCounts`, and identical `simStats` (`vehicles`, `pedestrians`, `activeTrips`, `bellPhase`); opens a third tab at `?t=15` and asserts canvas advances cleanly (`maxDiff > 0 && changedFrac > 0`).
    - `T2.V13.L03`: Diurnal living adaptation (`day` / `sunset` / `night`) — asserts daytime `livingCounts.sups >= 2` and active outdoor plugins, night `livingCounts.sups === 0`, strict diurnal pedestrian ordering (`night < sunset < day` with `night >= 2`), calm night traffic (`night.vehicles <= day.vehicles`), and active warm night plugins (`drawablesCount > 0`, `enabledPlugins.length >= 10`).
    - `T2.V13.L04`: Living inspectables & audio signals integration — asserts `livingRegistry.inspectablesCount > 0` at `bendlikon_pier`, verifies clicking live entities (`follow=train`, `follow=bus`) sets non-empty `window.__dioramaDebug.selectedEntity` via `hitTest()` and populates `#insp-title` with human-readable titles (zero raw snake_case IDs or road fragments), and verifies all 9 `audioGains` channels are finite in `[0, 1]` with shore-strict `lake_waves` (`bendlikon_pier > 2.5× sanatorium_ridge`).
    - `T2.V13.L05`: 60fps frame budget & zero-jank under pan/zoom — performs multi-tile drags and wheel zoom at `bahnhof_stockengut` (live mode), asserts `frameStats.rafActive === true`, `tileCacheSize <= 128`, `livingRegistry.updateMs` & `drawMs` finite in `[0, 50)`, and toggles Live Off/On repeatedly verifying zero rAF loop multiplication and zero errors.
    - `T2.V13.L06`: Dynamic plugin extensibility contract — opens live mode (`/?mode=day&zoom=2`), verifies `livingRegistry.register` / `unregister` / `setEnabled` functions, dynamically registers a mock plugin (`__test_ext_probe__`), asserts `pluginCount` increments by 1 and lifecycle hooks (`init`, `update`, `getDrawables`, and drawable `draw`) execute cleanly on subsequent rAF ticks, then calls `unregister` and asserts exact restoration to baseline with zero errors.
  - **+4 new v13.0 Botanical Vegetation Python tests (`tests/tier2_v13_vegetation.py`, registered in Tier 2):**
    - `T2.V13.V01`: Botanical species palette diversity — crops `sanatorium_ridge`, `morfanlage_promenade`, `reformierte_kirche`, and `stockengut_farm` from `day` `0.11 m/px` master tiles, extracts foliage pixels (`G > R + 6` & `G > B + 6`), and asserts `unique_foliage_colors >= 10`, foliage luminance IQR `>= 22.0`, `R - B` hue spread `>= 18.0`, dark cool conifer presence `>= 2.0%`, and bright sunlit deciduous/willow/birch highlight presence `>= 2.0%`.
    - `T2.V13.V02`: Anti-bubble & anti-stipple compliance — inspects foliage-heavy `day` L2 tiles covering wooded/park/lakeside zones and asserts `mean_cb < 6.5` (2×2 smooth-region checkerboard), per-tile `alt_y < 0.14` (vertical alternation), `<= 256` unique RGB colors per tile (SVGA CLUT), and crisp botanical silhouette edge richness (`mean_eg >= 4.0`, `strong_edge >= 6.0%`).
    - `T2.V13.V03`: Diurnal vegetation fidelity (`sunset` & `night`) — compares exact day-masked foliage pixels across `sanatorium_ridge`, `morfanlage_promenade`, and `reformierte_kirche`: sunset warms relative to day (`sunset(R-B) > day(R-B) + 5.0`) without pink/magenta cast (`mean(G) > mean(B)`, `p90(min(R,B)-G) < 5.0`); night stays deep nocturnal green (`p95(G-max(R,B)) < 18.0`, `mean(G) >= mean(R)`, `mean(luma)` in `[12, 75]`, `std(luma) >= 4.0`).
    - `T2.V13.V04`: v13.0 asset budget & cache-bust integrity — asserts `ASSET_VER = '13.0'` in `docs/app.js`, `?v=13.0` on `styles.css` and `app.js` in `docs/index.html`, ALL L2 and `z1` `.webp` tiles across `day`/`sunset`/`night` `< 500,000` bytes and lossless `VP8L`, total `docs/` size `< 300 MB`, and `docs/data/kilchberg_animations.json < 650 KB`.

---

## 2. Canonical Execution Commands

List all 12 registered suites:
```bash
.venv/bin/python tests/run_e2e.py --list
```

Run individual new v13.0 suites:
```bash
.venv/bin/python tests/tier2_v13_vegetation.py --verbose
node tests/tier2_v13_living.mjs --verbose
```

Run Tier 2 or full 4-tier E2E suite via unified runner:
```bash
.venv/bin/python tests/run_e2e.py --tier 2 --verbose
.venv/bin/python tests/run_e2e.py --tier all --verbose
```

---

## 3. Pre-Implementation Dry-Run Verification (Zero Syntax/Import/Harness Errors)

Verified against current `v12.0` baseline before M2B/M3 merge:
1. **Syntax & Suite Discovery:**
   - `node --check tests/tier2_v13_living.mjs` → exit `0`
   - `.venv/bin/python -m py_compile tests/tier2_v13_vegetation.py tests/run_e2e.py` → exit `0`
   - `.venv/bin/python tests/run_e2e.py --list` → lists all 12 suites across Tiers 1–4 including `tier2_v13_vegetation` and `tier2_v13_living` in Tier 2.
2. **Dry-Run Execution (`tests/tier2_v13_vegetation.py`):**
   - `4 tests | 3 PASSED (T2.V13.V01–V03) | 1 EXPECTED PRE-V13 FAIL (T2.V13.V04: ASSET_VER = '13.0') | 0 ERRORS` (`0.60 s`).
3. **Dry-Run Execution (`tests/tier2_v13_living.mjs`):**
   - `6 tests | 0 PASSED | 6 EXPECTED PRE-V13 FAIL (T2.V13.L01–L06: window.__dioramaDebug.livingRegistry missing) | 0 ERRORS` (`~23.5 s`).

---

## 4. Feature 11 / E2E Track Coverage Checklist
- [x] `tests/tier2_v13_living.mjs` authored with 6 opaque-box CDP tests (`T2.V13.L01`–`T2.V13.L06`)
- [x] `tests/tier2_v13_vegetation.py` authored with 4 opaque-box Python tests (`T2.V13.V01`–`T2.V13.V04`)
- [x] `tests/run_e2e.py` registers both new Tier 2 suites (12 suites, 135 total tests) + `--list` discovery flag
- [x] `TEST_INFRA.md` updated for v13.0 (135 total tests)
- [x] `TEST_READY.md` published with dry-run verification results
- [x] Zero forbidden local-host URLs in any test file or documentation
