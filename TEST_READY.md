# TEST_READY — Kilchberg v14 Moving/Living Layer Redo Opaque-Box E2E Suite

**Status:** **READY** (Verified — 146 Opaque-Box E2E Tests across 14 Suites in Tiers 1–4)
**Date:** 2026-11-23
**Owner:** E2E Testing Track (Feature F15 / Milestone E2E)
**Suite Specification:** [TEST_INFRA.md](TEST_INFRA.md)

---

## 1. Readiness Summary
- **Total Tests:** **146** (**68** Python `unittest` + **78** Node raw-CDP browser tests) across **14** suites registered in `tests/run_e2e.py`:
  - **138 / 138 v13.1 baseline test IDs preserved 100% intact** (**68 Python** + **70 Node CDP** across 13 suites, including `tier2_v13_1_bridges.py`).
  - **`T2.V13.V04` forward-compatible version sync (`tests/tier2_v13_vegetation.py`):** Updated `T2.V13.V04` to parse `ASSET_VER` in `docs/app.js`, `styles.css?v=X` in `docs/index.html`, and `app.js?v=X` in `docs/index.html` (with trailing `(?=['"&])` delimiter boundaries to reject malformed suffixes), asserting all three match identically with major version `>= 13` (passes cleanly on both pre-M4 `13.0` and post-M4 `14.0`). `T2.V13.V01`–`T2.V13.V03` remain untouched.
  - **+8 new v14 Moving/Living Layer Simulation CDP tests (`tests/tier2_v14_simulation.mjs`, registered in Tier 2):**
    - `T2.V14.01`: Glitch-free double-track train passing — samples multiple `?t=` frames (`10, 22, 34, 46`) at Bahnhof Kilchberg (`zoom=2`), asserts `window.__dioramaDebug.railTelemetry` (`activeTrains >= 0` with `max >= 1`, `typeof passingNow === 'boolean'`, `trackInterleaveViolations === 0`), verifies `trains` + `landmarks` plugins remain enabled (pre-rail NW board/clock ordering), and verifies opaque 2× train roofs via `depthStats` + `analyzeVehicleRoofOpacity` (`vehPixels >= 120`, `holeFrac < 0.06`).
    - `T2.V14.02`: Zero vehicle-vehicle & vehicle-pedestrian collisions — across `day` `?t=10, 22, 34, 46`, asserts `simStats.vehicles >= 40`, `simStats.overlapCount === 0`, `simStats.clippingCount === 0`, and `simStats.pedVehicleOverlapCount === 0`; verifies active traffic motion (no gridlock) via followed bus (`followTarget === 'bus'`, finite `u`/`v`) displacement between `?t=22` and `?t=34` (`dist > 0.002`).
    - `T2.V14.03`: Realistic Tennis rally physics — forces midday manual clock (`14:00`) when `clock.setMode`/`setManualMinutes` are present, polls up to `3500 ms` for `tennisBouncesObserved >= 1` at TC Kilchberg (`villa_spinnergut_tc`), and asserts `sportsTelemetry.tennisCourts >= 4`, `minTennisShotSec >= 1.0`, `maxTennisShotSec <= 2.4`, `minTennisShotSec <= maxTennisShotSec`, and finite `tennisBouncesObserved >= 1`.
    - `T2.V14.04`: Realistic Soccer player speed & ball kinematics — forces midday manual clock (`14:00`) when `clock.setMode`/`setManualMinutes` are present, steps live simulation at `hallenbad_hochweid`, and asserts `sportsTelemetry.soccerPitches >= 3`, `0 < maxSoccerPlayerMps <= 7.0`, and non-empty string array `sportsTelemetry.ballModes`.
    - `T2.V14.05`: Collision-free maritime vessels & slow SUPs — across `day` `?t=10, 22, 34, 46` at `bendlikon_pier`, asserts `vesselTelemetry.activeVessels >= 3`, `collisionCount === 0`, `minPairwiseClearanceM > 0`, and `0 < maxSupSpeedMps <= 2.0`; asserts `?mode=night&t=10` has `livingCounts.sups === 0`.
    - `T2.V14.06`: Modular Spec Injection API (`__dioramaDebug.specs`) — verifies `getSummary`, `registerInhabitant`, `removeInhabitant`, `registerBusRoute`, `removeBusRoute`, `registerRailService`, `registerVessel`; dynamically clones registered specs from `getInhabitants()[0]` / `getBusRoutes()[0]` (with schema-compatible fallback literals), registers custom `InhabitantSpec` and `BusRouteSpec`, verifies counts increment by `+1`, ticks 4 rAF frames with zero errors, removes both and verifies exact restoration to baseline, and verifies missing-`id` invalid specs throw `Error`.
    - `T2.V14.07`: Real-Time Kilchberg Clock & Deterministic Override — on live `/` (desktop `1280×800`), asserts `window.__dioramaDebug.clock` (`clockMode === 'live'`, `tzLabel` `'CET'|'CEST'`, integer `hours` `0..23`, `minutes` `0..59`, `solarElevationDeg` in `[-90, 90]`, `formattedHHMM` `/^\d{2}:\d{2}$/`, numeric `diurnalActivity` factors), verifies top-right clock HUD is visible inside viewport, does not overlap `#hud-coords` or `.nav-overlay`, hides cleanly in Cinema mode, does not overflow `.topbar` or clip on mobile (`390×844`), and verifies `/?t=10` (without `&mode=`) locks `clock.clockMode === 'deterministic'`, `clock.effectivePreset === 'day'`, `body[data-mode="day"]`, and produces byte-identical frames across two loads (`maxDiff === 0`).
    - `T2.V14.08`: Guardrails & 60fps Budget — verifies `livingRegistry.updateMs` & `drawMs` in `[0, 50)`, zero paragliders (`livingCounts.paragliders` `0` or `undefined`), shore-strict inland `audioGains.lake_waves <= 0.05`, and zero `console.error` / JS exceptions / HTTP errors.

---

## 2. Canonical Execution Commands

List all 14 registered suites:
```bash
.venv/bin/python tests/run_e2e.py --list
```

Run v14 simulation suite & vegetation compatibility suite:
```bash
.venv/bin/python tests/tier2_v13_vegetation.py --verbose
node tests/tier2_v14_simulation.mjs --verbose
```

Run Tier 2 or full 4-tier E2E suite via unified runner:
```bash
.venv/bin/python tests/run_e2e.py --tier 2 --verbose
.venv/bin/python tests/run_e2e.py --tier all --verbose
```

---

## 3. Pre-Implementation Dry-Run Verification (Against v13.1 Baseline)

Executed directly on the current v13.1 (`ASSET_VER = '13.0'`) codebase before M1–M4 land:
1. **Syntax & Compilation Checks:**
   - `node --check tests/tier2_v14_simulation.mjs` → exit `0`
   - `.venv/bin/python -m py_compile tests/run_e2e.py tests/tier2_v13_vegetation.py` → exit `0`
2. **Suite Registration Discovery (`.venv/bin/python tests/run_e2e.py --list`):**
   - Exit `0`; lists all **14 suites** across Tiers 1–4, including `tier2_v14_simulation (node tests/tier2_v14_simulation.mjs)` in Tier 2.
3. **Version Compatibility Verification (`.venv/bin/python tests/tier2_v13_vegetation.py --verbose`):**
   - Exit `0`; `4 tests | 4 PASSED | 0 FAILED | 0 ERRORS` (`2.50 s`), confirming `T2.V13.V04` passes cleanly on `ASSET_VER = '13.0'` and will pass cleanly on `ASSET_VER = '14.0'`.
4. **v14 Suite Dry-Run (`node tests/tier2_v14_simulation.mjs --verbose`):**
   - Clean execution with **0 syntax/import/harness errors** and clean CDP teardown:
   - **1 PASSED:** `T2.V14.08` (Guardrails & 60fps budget — `5169 ms`)
   - **7 EXPECTED PRE-V14 FAILS** (structured assertion messages against un-upgraded v13.1 baseline until M1–M4 land):
     - `T2.V14.01`: `t=10: window.__dioramaDebug.railTelemetry missing or not an object (got undefined)`
     - `T2.V14.02`: `t=10: simStats.pedVehicleOverlapCount must be a number === 0, got undefined`
     - `T2.V14.03`: `window.__dioramaDebug.sportsTelemetry missing or not an object (got undefined)`
     - `T2.V14.04`: `window.__dioramaDebug.sportsTelemetry missing or not an object (got undefined)`
     - `T2.V14.05`: `t=10: window.__dioramaDebug.vesselTelemetry missing or not an object (got undefined)`
     - `T2.V14.06`: `window.__dioramaDebug.specs missing`
     - `T2.V14.07`: `Live desktop: window.__dioramaDebug.clock missing or not an object (got undefined)`

---

## 4. Feature F15 / E2E Track Coverage Checklist
- [x] `tests/tier2_v13_vegetation.py`: `T2.V13.V04` updated to accept matching `ASSET_VER` / `styles.css?v=` / `app.js?v=` with major version `>= 13` (`13.0`, `14.0`, ...)
- [x] `tests/tier2_v14_simulation.mjs`: 8 opaque-box CDP tests (`T2.V14.01`–`T2.V14.08`) covering Features F1–F14
- [x] `tests/run_e2e.py`: `tier2_v14_simulation.mjs` registered in Tier 2 (14 suites, 146 total tests)
- [x] `TEST_INFRA.md`: Updated for Kilchberg v14 (14 suites, 146 tests, F1–F16 matrix, v14 contracts)
- [x] `TEST_READY.md`: Published with exact test IDs, commands, and dry-run verification results
- [x] Zero forbidden local-host URLs in any documentation
