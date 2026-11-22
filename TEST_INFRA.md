# Test Infrastructure — Kilchberg (ZH) Isometric Diorama (v12 Graphics, Textures & 60fps Smoothness Overhaul)

## 1. Test Philosophy & Architecture

This E2E testing track implements an **opaque-box, requirement-driven 4-tier automated test suite** derived strictly from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` (#1–#15) & `§ Interface Contracts` — **never** from private implementation details.

### Core Runtime & Zero-Dependency Architecture
1. **Zero-Install Native Toolchain** (runs directly on the provisioned VM without `pip install` or `npm install`):
   - **Python 3.11 (`.venv/bin/python`)**: `unittest`, `numpy`, `Pillow`, `ffprobe`, `concurrent.futures.ThreadPoolExecutor` — verifies static assets, `0.11 m/px` (`~28,024 × 12,373`) tile manifests, 2-level lossless VP8L tile pyramids (`364 × 3` L2 + `98 × 3` `z1` at `0.22 m/px`), anti-stipple / zero-Bayer smoothness, 256-color SVGA budgets, macro-tile seams, `< 500 KB` tile size & `< 300 MB` `docs/` footprint budgets, depth map, zero obsolete detail plates, direct master-tile landmark crops (`crop_master_rgb` / `crop_landmark_meter_box`), baked isometric lettering, v11/v12 landmark guardrails, JSON schemas, audio files, and DEM geometric bounds.
   - **Node.js 24 + `/usr/bin/chromium` (`tests/lib/cdp_harness.mjs`)**: Zero-dependency raw Chrome DevTools Protocol driver using built-in global `WebSocket` and `node:http` serving `docs/` on an ephemeral loopback socket (`127.0.0.1:0`, proper MIME types, ES module `?v=` query stripping). Launches one shared headless Chromium process per suite (`--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage`) with isolated incognito `Target.createBrowserContext({ disposeOnDetach: true })` tabs and trusted `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent` gestures.
   - **Unified CLI Runner (`tests/run_e2e.py`)**: Orchestrates all 4 tiers (`--tier 1|2|3|4|all`, `--verbose`, `--json-report`, `--timeout 120`), running Python and Node suites within each tier concurrently with atomic process-group cleanup (`os.killpg` on timeout) and strict exit codes (`0` = all pass, `1` = failure/error, `124` = timeout).
2. **100% Baseline Preservation + v12 `0.11 m/px` Full-Diorama Alignment (125 Total)**:
   - All **115** baseline test IDs (**56 Python** + **59 Node CDP**) are preserved 100% intact, with legacy detail-plate/modal tests repurposed into negative obsolete-plate assertions and direct `0.11 m/px` master-tile / live fly-to checks.
   - **+5 new v12 Smoothness CDP tests** (`tests/tier2_smoothness.mjs`: `T2.SM.01`–`T2.SM.05`) verify inertial pan glide, focal-point-locked smooth wheel zoom, sub-50ms pedestrian/vehicle interpolation + `?t=10` determinism, compositor-only `.lm-pin` CSS transform positioning, and `window.__dioramaDebug.frameStats` telemetry across multi-tile pans.
   - **+5 new v12 Visual-Polish Python tests** (`tests/tier2_v12_visuals.py`: `T2.V12.01`–`T2.V12.05`) verify strict `< 500 KB` lossless VP8L across all L2 (`364 × 3`) & `z1` (`98 × 3`) tiles, `< 300 MB` `docs/` footprint, calibrated anti-stipple / zero-Bayer-checkerboard smoothness with architectural edge preservation, 256-color SVGA budget + `< 1.35` seam ratio, and v12 guardrail preservation (zero obsolete detail plates, `0.11 m/px` master resolution, Lindt Home of Chocolate authentic roof, and St. Elisabeth clock-free white concrete tower cropped directly from master tiles).
   - **Grand Total:** **125 opaque-box E2E tests** (**61 Python** + **64 Node CDP**) across **10 suites**.

```text
tests/
├── run_e2e.py                    # Unified 4-tier CLI runner (10 suites, 125 tests)
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
├── tier2_browser_bounds.mjs      # Tier 2 (Node CDP, 16 tests): Layout/Retina/zoom/IDM/SUP/pins/T2.FA3.11 tiles/audio bounds
├── tier2_smoothness.mjs          # Tier 2 (Node CDP, 5 tests): v12 inertial pan, smooth wheel zoom, sub-50ms interp, CSS transform pins, frameStats
├── tier3_combinations.mjs        # Tier 3 (Node CDP, 13 tests): Pairwise cross-feature suites (T3.01–T3.13)
└── tier4_journeys.mjs            # Tier 4 (Node CDP, 13 tests): 8 end-user journeys (T4.01–T4.07, T4.13) + 5 hardening tests (T4.08–T4.12)
```

---

## 2. Complete v12 Feature Inventory Coverage Matrix (`PROJECT.md` Features #1–#15)

Every single feature in `PROJECT.md § Feature Inventory` is mapped to concrete automated E2E tests and/or pipeline gates:

| # | `PROJECT.md` Feature | Milestone | Automated E2E Test IDs & Suites |
|---|---|---|---|
| 1 | Rebuild ephemeral swisstopo cache (`fetch_data` + `extract_scene` hedge smoothing) | M1 | `T1.FA1.01`–`T1.FA1.06`, `T1.FA2.01`–`T1.FA2.11` (`tier1_assets_data.py`), `T2.FA2.01`–`T2.FA2.08` (`tier2_quality_bounds.py`) |
| 2 | Zero Bayer dithering & cel-shaded 256-color palettes | M1 | **`T2.V12.03`**, **`T2.V12.04`** (`tier2_v12_visuals.py`), `T2.FA1.01`, `T2.FA1.02`, `T2.FA1.07`, `T2.FA1.08` (`tier2_quality_bounds.py`) |
| 3 | Denoised & stylized building roofs + crisp windows (preserving Lindt HoC, PV, 16 landmarks, St. Elisabeth clock-free tower, `signage.py`) | M1 | **`T2.V12.03`**, **`T2.V12.05`** (`tier2_v12_visuals.py`), `T2.FA1.09`, `T2.FA1.11` (`tier2_quality_bounds.py`), `T2.LET.01`–`T2.LET.07` (`tier2_lettering.py`), `T2.LM.01`–`T2.LM.05` (`tier2_landmarks_v11.py`) |
| 4 | Smooth sub-pixel roads, sidewalks, curbs, yards & DEM slopes | M1 | **`T2.V12.03`** (`tier2_v12_visuals.py`), `T2.FA2.01`–`T2.FA2.05` (`tier2_quality_bounds.py`) |
| 5 | Rounded multi-lobe cloud trees & pillow hedges | M1 | **`T2.V12.03`**, **`T2.V12.04`** (`tier2_v12_visuals.py`), `T2.FA1.06`, `T2.FA1.11` (`tier2_quality_bounds.py`) |
| 6 | Crisp dark-ink outlines & punchy 4-step cel lighting | M1 | **`T2.V12.03`** (edge-preservation floor), **`T2.V12.04`** (`tier2_v12_visuals.py`), `T2.FA1.01`, `T2.FA1.11` (`tier2_quality_bounds.py`) |
| 7 | Backend quality gate upgrades (`pipeline/verify_quality.py`) | M1 | **`T2.V12.01`**, **`T2.V12.02`**, **`T2.V12.03`**, **`T2.V12.04`**, **`T2.V12.05`** (`tier2_v12_visuals.py`) + `.venv/bin/python -m pipeline.verify_quality` |
| 8 | Unified 60fps rAF loop & HiDPI cap (`dpr = min(2, devicePixelRatio)`, `{ alpha: false }`) | M2 | **`T2.SM.03`**, **`T2.SM.05`** (`tier2_smoothness.mjs`), `T2.FA3.02` (`tier2_browser_bounds.mjs`), `T4.08` (`tier4_journeys.mjs`) |
| 9 | Smooth camera kinematics (`docs/js/camera.js`: inertial drag, focal-locked smooth wheel zoom, flyTo, held keys, `< 950 ms` settle) | M2 | **`T2.SM.01`**, **`T2.SM.02`** (`tier2_smoothness.mjs`), `T1.FA3.03`, `T1.FA3.04` (`tier1_browser_features.mjs`), `T2.FA3.04` (`tier2_browser_bounds.mjs`), `T3.02`, `T3.07`, `T3.11` (`tier3_combinations.mjs`) |
| 10 | Async `ImageBitmap` tile streamer (`docs/js/tiles.js`: bounded `MAX_INFLIGHT=8`, LRU `<=128`, 0 L2 at Fit, `?t=` crossfade bypass) | M2 | **`T2.SM.03`**, **`T2.SM.05`** (`tier2_smoothness.mjs`), `T2.FA3.11` (`tier2_browser_bounds.mjs`), `T1.FA3.03` (`tier1_browser_features.mjs`), `T3.07` (`tier3_combinations.mjs`) |
| 11 | Fast depth masking, glow-sprite vignettes, compositor-only pins/HUD & `frameStats` | M2 | **`T2.SM.04`**, **`T2.SM.05`** (`tier2_smoothness.mjs`), `T1.FA3.12`, `T1.FA3.13` (`tier1_browser_features.mjs`), `T3.09`, `T3.12` (`tier3_combinations.mjs`), `T4.01`–`T4.07` (`tier4_journeys.mjs`) |
| 12 | 60fps sub-step interpolation for pedestrians & feeder vans (100% deterministic `?t=`) | M2 | **`T2.SM.03`** (`tier2_smoothness.mjs`), `T2.FA3.07`, `T2.FA3.08` (`tier2_browser_bounds.mjs`), `T3.07`, `T3.08` (`tier3_combinations.mjs`), `T4.07`, `T4.10` (`tier4_journeys.mjs`) |
| 13 | Full v12 `0.11 m/px` 3-preset tile pyramid (`364 × 3` L2 + `98 × 3` `z1`), zero separate detail plates (`ASSET_VER = 12.0`) | M3B | **`T2.V12.01`–`T2.V12.05`** (`tier2_v12_visuals.py`), `T1.FA1.01`–`T1.FA1.11` (`tier1_assets_data.py`), `T2.FA1.01`–`T2.FA1.12` (`tier2_quality_bounds.py`) |
| 14 | Requirement-driven v12 E2E tests (`TEST_INFRA.md`, `tier2_smoothness.mjs`, `tier2_v12_visuals.py`, `0.11 m/px` & no-plate updates, `TEST_READY.md`) | E2E / E2E-B | All 10 suites registered in `tests/run_e2e.py` (**125 total tests**: 61 Python + 64 Node CDP) |
| 15 | Final 100% E2E pass (Tiers 1–4) + Tier 5 White-Box Adversarial Hardening + Publish | M4 | Full `--tier all` run (125/125 PASS) + Tier 5 adversarial probes + GitHub Pages `"built"` check |

---

## 3. 4-Tier Testing Methodology (+ Tier 5 White-Box Hardening Reference)

| Tier | Purpose | Suites & Counts |
|---|---|---|
| **Tier 1 — Smoke & Feature Coverage** | Fast verification that every static asset, manifest, tile pyramid, depth map, JSON schema, audio track, and interactive browser feature boots and operates cleanly with zero errors. | `tier1_assets_data.py` (24) + `tier1_browser_features.mjs` (17) = **41 tests** |
| **Tier 2 — Bounds, Quality, Smoothness & Visual Polish** | Mathematical and perceptual invariants: diurnal luminance, CLUTs, tile seams, floating sky clusters, lake/sunset/night lighting, Lindt roof, baked lettering, v11 landmark photo-realism, **v12 anti-stipple / `< 500 KB` VP8L / `< 300 MB` `docs/`**, **v12 camera inertia / smooth wheel zoom / sub-50ms interpolation / compositor pins / `frameStats`**, layout/Retina/IDM/SUP/tile-streaming & spatial audio bounds. | `tier2_quality_bounds.py` (20) + `tier2_lettering.py` (7) + `tier2_landmarks_v11.py` (5) + **`tier2_v12_visuals.py` (5)** + `tier2_browser_bounds.mjs` (16) + **`tier2_smoothness.mjs` (5)** = **58 tests** |
| **Tier 3 — Cross-Feature Combinations** | Pairwise feature interactions: lighting × living world, zoom/tiles × follow camera, search × inspector × direct landmark fly-to (no detail-plate modal), lighting × audio, deep-link × `?t=` round-trip, Cinema/Sidebar × resize, deterministic `?t=10` identity (`T3.07`), diurnal shift, `0.11 m/px` train/bus roof opacity (`T3.09`, `T3.12`), bell sync, `?landmark=` & `[/]`, `11 cm/px` scale bar (`T3.13`). | `tier3_combinations.mjs` = **13 tests** |
| **Tier 4 — End-User Journeys & Hardening** | 8 full end-to-end user journeys (`T4.01`–`T4.07`, `T4.13`: desktop tour, Lindt/Seebad deep zoom, commuter follow, resident address lookup, spatial soundscape walk, mobile portrait, living Kilchberg, heritage tour) + 5 regression hardening checks (`T4.08`–`T4.12`: rAF non-multiplication, extreme `?t=`, bus advancement, train click hygiene, mobile topbar overflow). | `tier4_journeys.mjs` = **13 tests** |
| **Tier 5 — White-Box Adversarial Hardening (M4 Reference)** | Post-green adversarial audit inspecting implemented `camera.js`, `tiles.js`, `depth.js`, `pixel_shader.py`, and edge cases (rapid resize during inertia, tab blur held-key release, LRU `ImageBitmap.close()` under heavy pan, `?t=` crossfade bypass, seam guard-band edge cases) and adding targeted regression tests for any discovered gap. | Executed in M4 after Tiers 1–4 reach 125/125 PASS |

---

## 4. Zero-Flake Headless Chromium Guidelines

Headless Chromium in CI runs CPU software rendering (SwiftShader / Skia) where wall-clock FPS fluctuates with host CPU load. Every browser test in `tests/tier2_smoothness.mjs` and the wider suite obeys these strict anti-flake rules:

1. **Never assert hardcoded FPS floors (e.g., `fps >= 58`)** in headless software mode. Instead, assert **structural and relative smoothness invariants**:
   - Inertial coasting displacement after `pointerup` captured synchronously via a one-shot in-page `pointerup` listener (`coastDist > 0.0005` in the exact drag direction, `dot > 0`, checked at both 120 ms and settled rest).
   - Multi-frame scale interpolation during wheel zoom (`>= 2` distinct intermediate `scale` samples strictly between initial and settled scale) paired with focal-point world UV invariance (`< 0.0025` UV).
   - Deterministic 3-part sub-50ms interpolation & determinism check (`T2.SM.03`): (Part A) full-viewport `160×100` canvas diff between `?t=10.005` and `?t=10.040` inside the exact same 50 ms `FIXED_DT` bucket (`Math.floor(t * 20) === 200`, `maxDiff > 0 && changedFrac > 0`); (Part B) direct in-page `pedestrians.js` + `traffic.js` sub-50ms interpolation check at `t=2.005` vs `t=2.040` (bucket `40`, asserting `>= 5` pedestrians AND `>= 5` vehicles advance); and (Part C) sequential two-tab `?t=10` byte-identical determinism (`maxDiff === 0`, closing each `dpr=2` tab before opening the next).
   - Compositor-only `.lm-pin` positioning (`getComputedStyle(el).transform` starts with `matrix(` / `matrix3d(` with zero `style.left`/`style.top` mutations).
   - Bounded tile cache (`frameStats.tileCacheSize <= 128`), clean inflight drain (`tileInflight === 0`), and finite non-negative `frameStats` telemetry.
2. **Bounded Camera Settle (`waitForCameraSettled()` `< 950 ms`)**: All camera inertia and smooth wheel springs must reach rest well inside the `950 ms` budget (`settleMs = 140`, `du/dv < 0.0008`, `ds < 0.015`).
3. **Deterministic `?t=` Contract**: Any animation/tile crossfade or camera spring must bypass cleanly when `?t=` (`fixedAnimTime !== null`) is supplied so `T2.SM.03` Part C (sequential two-tab `?t=10` capture) and `T3.07` produce byte-identical canvas snapshots (`maxDiff === 0`).
4. **Offline Resilience & Strict Error Accounting**: External font CDNs are blocked via `Network.setBlockedURLs`; zero same-origin HTTP `>= 400`, zero `Network.loadingFailed`, zero `Runtime.exceptionThrown`, and zero `console.error` are permitted.
5. **Clean Diagnostic Failure Messages**: Every assertion emits measured values alongside expected bounds (e.g., `mean_cb=13.34 >= 6.50`, `coastDist=0.000000 <= 0.0005`), enabling immediate triage without guesswork.
6. **Atomic Teardown**: All temporary browser profiles, ephemeral HTTP servers, and Chromium child processes are torn down in `finally` blocks and signal handlers, leaving `0` live orphan processes.

---

## 5. Coverage Thresholds & Execution Budgets

| Metric | Required Threshold |
|---|---|
| Tier 1 feature coverage | **41 tests** (`tier1_assets_data.py`: 24, `tier1_browser_features.mjs`: 17) |
| Tier 2 bounds, quality, smoothness & visual polish | **58 tests** (`quality_bounds`: 20, `lettering`: 7, `landmarks_v11`: 5, **`v12_visuals`: 5**, `browser_bounds`: 16, **`smoothness`: 5**) |
| Tier 3 cross-feature pairwise coverage | **13 tests** (`tier3_combinations.mjs`) |
| Tier 4 real-world journeys & hardening | **13 tests** (`tier4_journeys.mjs`) |
| **Total E2E suite size** | **125 tests** (**61 Python** + **64 Node CDP**) |
| Per-suite timeout budget | `120 s` (`tests/run_e2e.py --timeout 120`) |
| Orphan process tolerance | `0` live Chromium/Node/HTTP processes after run completion |
