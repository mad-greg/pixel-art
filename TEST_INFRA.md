# Test Infrastructure — Kilchberg (ZH) Isometric Diorama (v14 Moving/Living Layer Redo)

## 1. Test Philosophy & Architecture

This E2E testing track implements an **opaque-box, requirement-driven 4-tier automated test suite** derived strictly from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` (F1–F16) & `§ Interface Contracts` — **never** from private implementation details.

### Core Runtime & Zero-Dependency Architecture
1. **Zero-Install Native Toolchain** (runs directly on the provisioned VM without `pip install` or `npm install`):
   - **Python 3.11 (`.venv/bin/python`)**: `unittest`, `numpy`, `Pillow`, `ffprobe`, `concurrent.futures.ThreadPoolExecutor` — verifies static assets, `0.11 m/px` (`27,971 × 12,294`) tile manifests, 2-level lossless VP8L tile pyramids (`364 × 3` L2 + `98 × 3` `z1` at `0.22 m/px`), botanical species foliage diversity & diurnal fidelity, v13.1 bridge/road junction continuity & parapet white-seam guards, anti-stipple / zero-Bayer smoothness, 256-color SVGA budgets, macro-tile seams, `< 500 KB` tile size & `< 300 MB` `docs/` footprint budgets, `ASSET_VER >= 13.0` sync (`13.0` / `14.0`), depth map, zero obsolete detail plates, direct master-tile landmark crops (`crop_master_rgb` / `crop_landmark_meter_box`), baked isometric lettering, v11/v12/v13 guardrails, JSON schemas, audio files, and DEM geometric bounds.
   - **Node.js 24 + `/usr/bin/chromium` (`tests/lib/cdp_harness.mjs`)**: Zero-dependency raw Chrome DevTools Protocol driver using built-in global `WebSocket` and `node:http` serving `docs/` on an ephemeral loopback socket (`127.0.0.1:0`, proper MIME types, ES module `?v=` query stripping). Launches one shared headless Chromium process per suite (`--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage`) with isolated incognito `Target.createBrowserContext({ disposeOnDetach: true })` tabs and trusted `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent` gestures.
   - **Unified CLI Runner (`tests/run_e2e.py`)**: Orchestrates all 4 tiers (`--tier 1|2|3|4|all`, `--list`, `--verbose`, `--json-report`, `--timeout 120`), running Python and Node suites within each tier concurrently with atomic process-group cleanup (`os.killpg` on timeout) and strict exit codes (`0` = all pass, `1` = failure/error, `124` = timeout).
2. **100% Baseline Preservation + v14 Simulation Suite (146 Total)**:
   - All **138** v13.1 baseline test IDs (**68 Python** + **70 Node CDP** across 13 suites, including v13.1 `tier2_v13_1_bridges.py`) are preserved 100% intact. `T2.V13.V04` in `tests/tier2_v13_vegetation.py` validates matching `ASSET_VER`, `styles.css?v=X`, and `app.js?v=X` with major version `>= 13` (passing cleanly for both `13.0` and `14.0`).
   - **+8 new v14 Moving/Living Layer Simulation CDP tests** (`tests/tier2_v14_simulation.mjs`: `T2.V14.01`–`T2.V14.08`) verify the v14 opaque-box contracts across Features F1–F14:
     - `T2.V14.01`: Glitch-free double-track train passing (`window.__dioramaDebug.railTelemetry`, `trackInterleaveViolations === 0`, active `trains`/`landmarks` pre-rail ordering, opaque 2× train roofs via `depthStats` + `analyzeVehicleRoofOpacity`).
     - `T2.V14.02`: Zero vehicle-vehicle & vehicle-pedestrian collisions (`simStats.overlapCount === 0`, `clippingCount === 0`, `pedVehicleOverlapCount === 0` across `?t=10,22,34,46`) plus active bus displacement proving zero gridlock.
     - `T2.V14.03`: Realistic Tennis rally physics (`sportsTelemetry.tennisCourts >= 4`, `minTennisShotSec >= 1.0`, `maxTennisShotSec <= 2.4`, `tennisBouncesObserved >= 1`).
     - `T2.V14.04`: Realistic Soccer player speed & ball kinematics (`sportsTelemetry.soccerPitches >= 3`, `0 < maxSoccerPlayerMps <= 7.0`, non-empty `ballModes`).
     - `T2.V14.05`: Collision-free maritime vessels & slow SUPs (`vesselTelemetry.activeVessels >= 3`, `collisionCount === 0`, `minPairwiseClearanceM > 0`, `0 < maxSupSpeedMps <= 2.0`, night `livingCounts.sups === 0`).
     - `T2.V14.06`: Modular Spec Injection API (`window.__dioramaDebug.specs`: `getSummary`, dynamic `registerInhabitant` + `registerBusRoute`, live rAF ticking, `removeInhabitant` + `removeBusRoute` restoration, and validation `Error` on missing `id`).
     - `T2.V14.07`: Real-Time Kilchberg Clock & Deterministic Override (`window.__dioramaDebug.clock` CET/CEST, `hours`/`minutes`/`solarElevationDeg`/`formattedHHMM`/`diurnalActivity`, top-right HUD non-overlap on desktop `1280×800`, Cinema mode hide, mobile `390×844` topbar & viewport safety, and `/?t=10` deterministic `day` lock with `maxDiff === 0`).
     - `T2.V14.08`: Guardrails & 60fps Budget (`livingRegistry.updateMs < 50`, `drawMs < 50`, zero paragliders, shore-strict inland `audioGains.lake_waves <= 0.05`, zero console/page errors).
   - **Grand Total:** **146 opaque-box E2E tests** (**68 Python** + **78 Node CDP**) across **14 suites**.

```text
tests/
├── run_e2e.py                    # Unified 4-tier CLI runner (14 suites, 146 tests)
├── lib/
│   ├── __init__.py
│   ├── report.py                 # TestCaseResult / TierResult dataclasses, summary table & JSON report
│   ├── assets_helper.py          # Cached metadata-driven loaders, VP8L header check, RLE components, RGB counter
│   └── cdp_harness.mjs           # Zero-dep Node 24 CDP driver, ephemeral docs/ server, isolated incognito tabs
├── tier1_assets_data.py          # Tier 1 (Python, 24 tests): Static assets, manifests, depth, JSON, MP3s
├── tier1_browser_features.mjs    # Tier 1 (Node CDP, 17 tests): Desktop boot, UI controls, __dioramaDebug, audio
├── tier2_quality_bounds.py       # Tier 2 (Python, 20 tests): Diurnal luma, CLUTs, seams, water, lighting, DEM bounds
├── tier2_lettering.py            # Tier 2 (Python, 7 tests): Baked pipeline/signage.py typography & no-overlay guard
├── tier2_landmarks_v11.py        # Tier 2 (Python, 5 tests): v11 St. Elisabeth, Gemeindehaus, CLOCKS & config guardrails
├── tier2_v12_visuals.py          # Tier 2 (Python, 5 tests): v12 <500KB VP8L, <300MB docs/, anti-stipple, SVGA/seams, 0.11m/px guardrails
├── tier2_v13_vegetation.py       # Tier 2 (Python, 4 tests): v13 botanical diversity, anti-bubble/stipple, diurnal foliage, v13+ budget & version sync
├── tier2_v13_1_bridges.py        # Tier 2 (Python, 3 tests): v13.1 bridge/road junction continuity & parapet white-seam guards
├── tier2_browser_bounds.mjs      # Tier 2 (Node CDP, 16 tests): Layout/Retina/zoom/IDM/SUP/pins/T2.FA3.11 tiles/audio bounds
├── tier2_smoothness.mjs          # Tier 2 (Node CDP, 5 tests): v12 inertial pan, smooth wheel zoom, sub-50ms interp, CSS transform pins, frameStats
├── tier2_v13_living.mjs          # Tier 2 (Node CDP, 6 tests): v13 LivingEngine registry, ?t= determinism, diurnal life, inspectables/audio, 60fps budget, extensibility
├── tier2_v14_simulation.mjs      # Tier 2 (Node CDP, 8 tests): v14 rail passing, 0 collisions, tennis/soccer physics, COLREGs vessels, SpecRegistry, KilchbergClock, guardrails
├── tier3_combinations.mjs        # Tier 3 (Node CDP, 13 tests): Pairwise cross-feature suites (T3.01–T3.13)
└── tier4_journeys.mjs            # Tier 4 (Node CDP, 13 tests): 8 end-user journeys (T4.01–T4.07, T4.13) + 5 hardening tests (T4.08–T4.12)
```

---

## 2. Complete v14 Feature Inventory Coverage Matrix (`PROJECT.md` Features F1–F16)

Every single feature in `PROJECT.md § Feature Inventory` is mapped to concrete automated E2E tests and/or pipeline gates:

| # | `PROJECT.md` Feature | Milestone | Automated E2E Test IDs & Suites |
|---|---|---|---|
| F1 | Declarative `SpecRegistry` (`__dioramaDebug.specs`) | M1 | **`T2.V14.06`** (`tier2_v14_simulation.mjs`) |
| F2 | Kilchberg Default Data Packs (SBB, ZVV, Inhabitants, Vessels, Sports) | M1 | **`T2.V14.01`**, **`T2.V14.05`**, **`T2.V14.06`** (`tier2_v14_simulation.mjs`), `T2.V13.L01` (`tier2_v13_living.mjs`) |
| F3 | Real-Time `KilchbergClock` & Continuous Diurnal | M1 | **`T2.V14.07`** (`tier2_v14_simulation.mjs`), `T2.V13.L02`, `T2.V13.L03` (`tier2_v13_living.mjs`), `T3.07`, `T3.08` (`tier3_combinations.mjs`) |
| F4 | Unified 2D Spatial Hash Grid (`docs/js/sim/spatial.js`) | M1 | **`T2.V14.02`**, **`T2.V14.05`**, **`T2.V14.08`** (`tier2_v14_simulation.mjs`) |
| F5 | Multi-Key `'rail'` Layer Sorting (`engine.js`) | M1 | **`T2.V14.01`** (`tier2_v14_simulation.mjs`), `T2.V13.L01`, `T2.V13.L06` (`tier2_v13_living.mjs`) |
| F6 | Glitch-Free Double-Track Train Passing | M2 | **`T2.V14.01`** (`tier2_v14_simulation.mjs`), `T3.09` (`tier3_combinations.mjs`), `T4.11` (`tier4_journeys.mjs`) |
| F7 | Cross-Lane Shared-Corridor & Junction Traffic | M2 | **`T2.V14.02`** (`tier2_v14_simulation.mjs`), `T2.FA3.07`, `T2.FA3.08` (`tier2_browser_bounds.mjs`), `T2.SM.03` (`tier2_smoothness.mjs`) |
| F8 | Collision-Free Vehicle–Pedestrian & Cyclist Safety | M2 | **`T2.V14.02`** (`tier2_v14_simulation.mjs`), `T2.FA3.07`, `T2.FA3.08` (`tier2_browser_bounds.mjs`), `T2.SM.03` (`tier2_smoothness.mjs`) |
| F9 | Spec-Driven ZVV Buses & Named Inhabitants | M2 | **`T2.V14.06`** (`tier2_v14_simulation.mjs`), `T2.SM.03` (`tier2_smoothness.mjs`), `T2.V13.L04` (`tier2_v13_living.mjs`), `T4.10` (`tier4_journeys.mjs`) |
| F10 | Realistic Tennis Match State Machine | M3 | **`T2.V14.03`** (`tier2_v14_simulation.mjs`) |
| F11 | Realistic Soccer & Multisport State Machine | M3 | **`T2.V14.04`** (`tier2_v14_simulation.mjs`) |
| F12 | Collision-Free Maritime `VesselSim` & ZSG Specs | M3 | **`T2.V14.05`** (`tier2_v14_simulation.mjs`), `T2.FA3.09` (`tier2_browser_bounds.mjs`), `T2.V13.L03` (`tier2_v13_living.mjs`) |
| F13 | Seebad/Wildlife Calibration & Single-Source Audio | M3 | **`T2.V14.05`**, **`T2.V14.08`** (`tier2_v14_simulation.mjs`), `T2.V13.L04` (`tier2_v13_living.mjs`), `T3.10` (`tier3_combinations.mjs`) |
| F14 | App Wiring, Real-Time Kilchberg HUD & v14.0 Sync | M4 | **`T2.V14.07`**, **`T2.V14.08`** (`tier2_v14_simulation.mjs`), **`T2.V13.V04`** (`tier2_v13_vegetation.py`), `T2.FA3.01` (`tier2_browser_bounds.mjs`), `T4.12` (`tier4_journeys.mjs`) |
| F15 | Opaque-Box v14 E2E Test Suite | E2E | All 14 suites registered in `tests/run_e2e.py` (**146 total tests**: 68 Python + 78 Node CDP) |
| F16 | Final Milestone Verification & Adversarial Hardening | M5 | Full `--tier all` run (146/146 PASS) + `pipeline.verify_quality` (10/10 `[ok]`) + Tier 5 adversarial audit + Victory Audit |

---

## 3. 4-Tier Testing Methodology (+ Tier 5 White-Box Hardening Reference)

| Tier | Purpose | Suites & Counts |
|---|---|---|
| **Tier 1 — Smoke & Feature Coverage** | Fast verification that every static asset, manifest, tile pyramid, depth map, JSON schema, audio track, and interactive browser feature boots and operates cleanly with zero errors. | `tier1_assets_data.py` (24) + `tier1_browser_features.mjs` (17) = **41 tests** |
| **Tier 2 — Bounds, Quality, Smoothness, Living, Vegetation, Bridges & v14 Simulation** | Mathematical and perceptual invariants: diurnal luminance, CLUTs, tile seams, floating sky clusters, lake/sunset/night lighting, Lindt roof, baked lettering, v11 landmark photo-realism, v12 anti-stipple / `< 500 KB` VP8L / `< 300 MB` `docs/`, v13 botanical vegetation diversity / anti-bubble / diurnal fidelity / `ASSET_VER >= 13.0` sync, v13.1 bridge junctions & parapets, v12 camera inertia / smooth wheel zoom / sub-50ms interpolation / compositor pins / `frameStats`, v13 modular LivingEngine lifecycle / determinism / diurnal adaptation / inspectables & shore-strict audio / 60fps budget / dynamic extensibility, **v14 double-track rail sorting, zero vehicle/pedestrian collisions, tennis & soccer physics, COLREGs maritime separation, SpecRegistry injection, real-time Europe/Zurich Kilchberg clock & HUD, and 60fps guardrails**, and layout/Retina/IDM/SUP/tile-streaming/audio bounds. | `tier2_quality_bounds.py` (20) + `tier2_lettering.py` (7) + `tier2_landmarks_v11.py` (5) + `tier2_v12_visuals.py` (5) + `tier2_v13_vegetation.py` (4) + `tier2_v13_1_bridges.py` (3) + `tier2_browser_bounds.mjs` (16) + `tier2_smoothness.mjs` (5) + `tier2_v13_living.mjs` (6) + **`tier2_v14_simulation.mjs` (8)** = **79 tests** |
| **Tier 3 — Cross-Feature Combinations** | Pairwise feature interactions: lighting × living world, zoom/tiles × follow camera, search × inspector × direct landmark fly-to, lighting × audio, deep-link × `?t=` round-trip, Cinema/Sidebar × resize, deterministic `?t=10` identity (`T3.07`), diurnal shift, `0.11 m/px` train/bus roof opacity (`T3.09`, `T3.12`), bell sync, `?landmark=` & `[/]`, `11 cm/px` scale bar (`T3.13`). | `tier3_combinations.mjs` = **13 tests** |
| **Tier 4 — End-User Journeys & Hardening** | 8 full end-to-end user journeys (`T4.01`–`T4.07`, `T4.13`) + 5 regression hardening checks (`T4.08`–`T4.12`: rAF non-multiplication, extreme `?t=`, bus advancement, train click hygiene, mobile topbar overflow). | `tier4_journeys.mjs` = **13 tests** |
| **Tier 5 — White-Box Adversarial Hardening (M5 Reference)** | Post-green adversarial audit inspecting implemented `docs/js/specs/*`, `docs/js/sim/*`, `docs/js/living/*`, `docs/app.js`, and edge cases, adding targeted regression tests for any discovered gap. | Executed in M5 after Tiers 1–4 reach 146/146 PASS |

---

## 4. v14 Opaque-Box Telemetry & UI Contracts

All v14 tests interact strictly through documented public/debug interfaces (`PROJECT.md § Interface Contracts`):
- `window.__dioramaDebug.railTelemetry`: `{ activeTrains, passingNow, trackInterleaveViolations }`
- `window.__dioramaDebug.simStats`: existing v13 fields + `overlapCount`, `clippingCount`, `pedVehicleOverlapCount`
- `window.__dioramaDebug.sportsTelemetry`: `{ tennisCourts, soccerPitches, maxSoccerPlayerMps, minTennisShotSec, maxTennisShotSec, tennisBouncesObserved, ballModes }`
- `window.__dioramaDebug.vesselTelemetry`: `{ activeVessels, minPairwiseClearanceM, collisionCount, maxSupSpeedMps }`
- `window.__dioramaDebug.specs`: `{ getSummary, registerInhabitant, removeInhabitant, registerBusRoute, removeBusRoute, registerRailService, registerVessel }`
- `window.__dioramaDebug.clock`: `{ clockMode, tzLabel, hours, minutes, seconds, formattedHHMM, solarElevationDeg, autoPreset, effectivePreset, diurnalActivity }`
- Top-right `.viewport-ui` Kilchberg Clock HUD (visible on desktop `1280×800` & mobile `390×844` without overlapping `#hud-coords`/`.nav-overlay` or overflowing `.topbar`, and hidden in Cinema mode).

---

## 5. Canonical Runner Commands & Execution Budgets

```bash
# List all 14 registered suites across Tiers 1–4
.venv/bin/python tests/run_e2e.py --list

# Run v14 simulation suite directly
node tests/tier2_v14_simulation.mjs --verbose

# Run Tier 2 or full 4-tier E2E suite (146 tests)
.venv/bin/python tests/run_e2e.py --tier 2 --verbose
.venv/bin/python tests/run_e2e.py --tier all --verbose

# Run static pipeline quality gate (10/10 [ok])
.venv/bin/python -m pipeline.verify_quality
```

| Metric | Required Threshold |
|---|---|
| Tier 1 feature coverage | **41 tests** (`tier1_assets_data.py`: 24, `tier1_browser_features.mjs`: 17) |
| Tier 2 bounds, quality, smoothness, living, vegetation, bridges & v14 sim | **79 tests** (`quality_bounds`: 20, `lettering`: 7, `landmarks_v11`: 5, `v12_visuals`: 5, `v13_vegetation`: 4, `v13_1_bridges`: 3, `browser_bounds`: 16, `smoothness`: 5, `v13_living`: 6, **`v14_simulation`: 8**) |
| Tier 3 cross-feature pairwise coverage | **13 tests** (`tier3_combinations.mjs`) |
| Tier 4 real-world journeys & hardening | **13 tests** (`tier4_journeys.mjs`) |
| **Total E2E suite size** | **146 tests** (**68 Python** + **78 Node CDP**) across **14 suites** |
| Per-suite timeout budget | `120 s` (`tests/run_e2e.py --timeout 120`) |
| Orphan process tolerance | `0` live Chromium/Node/HTTP processes after run completion |
