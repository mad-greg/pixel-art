# Test Infrastructure — Kilchberg (ZH) Isometric Diorama (v13.0 Modular Living Layer & Botanical Vegetation Overhaul)

## 1. Test Philosophy & Architecture

This E2E testing track implements an **opaque-box, requirement-driven 4-tier automated test suite** derived strictly from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` (#1–#12) & `§ Interface Contracts` — **never** from private implementation details.

### Core Runtime & Zero-Dependency Architecture
1. **Zero-Install Native Toolchain** (runs directly on the provisioned VM without `pip install` or `npm install`):
   - **Python 3.11 (`.venv/bin/python`)**: `unittest`, `numpy`, `Pillow`, `ffprobe`, `concurrent.futures.ThreadPoolExecutor` — verifies static assets, `0.11 m/px` (`27,971 × 12,294`) tile manifests, 2-level lossless VP8L tile pyramids (`364 × 3` L2 + `98 × 3` `z1` at `0.22 m/px`), botanical species foliage diversity & diurnal fidelity, anti-stipple / zero-Bayer smoothness, 256-color SVGA budgets, macro-tile seams, `< 500 KB` tile size & `< 300 MB` `docs/` footprint budgets, depth map, zero obsolete detail plates, direct master-tile landmark crops (`crop_master_rgb` / `crop_landmark_meter_box`), baked isometric lettering, v11/v12/v13 guardrails, JSON schemas, audio files, and DEM geometric bounds.
   - **Node.js 24 + `/usr/bin/chromium` (`tests/lib/cdp_harness.mjs`)**: Zero-dependency raw Chrome DevTools Protocol driver using built-in global `WebSocket` and `node:http` serving `docs/` on an ephemeral loopback socket (`127.0.0.1:0`, proper MIME types, ES module `?v=` query stripping). Launches one shared headless Chromium process per suite (`--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage`) with isolated incognito `Target.createBrowserContext({ disposeOnDetach: true })` tabs and trusted `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent` gestures.
   - **Unified CLI Runner (`tests/run_e2e.py`)**: Orchestrates all 4 tiers (`--tier 1|2|3|4|all`, `--list`, `--verbose`, `--json-report`, `--timeout 120`), running Python and Node suites within each tier concurrently with atomic process-group cleanup (`os.killpg` on timeout) and strict exit codes (`0` = all pass, `1` = failure/error, `124` = timeout).
2. **100% Baseline Preservation + v13.0 Living Layer & Botanical Vegetation Suites (135 Total)**:
   - All **125** v12.0 baseline test IDs (**61 Python** + **64 Node CDP**) are preserved 100% intact.
   - **+6 new v13.0 Modular Living Layer CDP tests** (`tests/tier2_v13_living.mjs`: `T2.V13.L01`–`T2.V13.L06`) verify the `window.__dioramaDebug.livingRegistry` plugin lifecycle (`>= 10` unique plugins, finite timings, drawables/inspectables/perPluginCounts), strict `?t=10` determinism & `?t=15` advancement across all living plugins, diurnal living adaptation (`day` / `sunset` / `night` SUPs, pedestrians, traffic, active plugins), living inspectables human-readable titles & shore-strict spatial `audioGains`, 60fps frame budget & zero rAF multiplication under pan/zoom + Live Off/On, and dynamic `register`/`unregister` plugin extensibility.
   - **+4 new v13.0 Botanical Vegetation Python tests** (`tests/tier2_v13_vegetation.py`: `T2.V13.V01`–`T2.V13.V04`) verify multi-species botanical foliage palette diversity (dark conifer + mid deciduous + sunlit willow/birch/orchard spread, `>= 10` foliage RGBs, luminance IQR `>= 22.0`, `R-B` hue spread `>= 18.0`), anti-bubble & anti-stipple compliance (`mean_cb < 6.5`, `alt_y < 0.14`, `<= 256` colors, crisp silhouette edge floor), diurnal vegetation fidelity (`sunset` warmth without pink cast, `night` deep nocturnal green without neon or muddy collapse), and v13.0 asset budget & cache-bust integrity (`ASSET_VER = '13.0'`, `?v=13.0`, `< 500 KB` VP8L tiles, `docs/ < 300 MB`, `kilchberg_animations.json < 650 KB`).
   - **Grand Total:** **135 opaque-box E2E tests** (**65 Python** + **70 Node CDP**) across **12 suites**.

```text
tests/
├── run_e2e.py                    # Unified 4-tier CLI runner (12 suites, 135 tests)
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
├── tier2_v13_vegetation.py       # Tier 2 (Python, 4 tests): v13 botanical diversity, anti-bubble/stipple, diurnal foliage, v13 budget & cache-bust
├── tier2_browser_bounds.mjs      # Tier 2 (Node CDP, 16 tests): Layout/Retina/zoom/IDM/SUP/pins/T2.FA3.11 tiles/audio bounds
├── tier2_smoothness.mjs          # Tier 2 (Node CDP, 5 tests): v12 inertial pan, smooth wheel zoom, sub-50ms interp, CSS transform pins, frameStats
├── tier2_v13_living.mjs          # Tier 2 (Node CDP, 6 tests): v13 LivingEngine registry, ?t= determinism, diurnal life, inspectables/audio, 60fps budget, extensibility
├── tier3_combinations.mjs        # Tier 3 (Node CDP, 13 tests): Pairwise cross-feature suites (T3.01–T3.13)
└── tier4_journeys.mjs            # Tier 4 (Node CDP, 13 tests): 8 end-user journeys (T4.01–T4.07, T4.13) + 5 hardening tests (T4.08–T4.12)
```

---

## 2. Complete v13.0 Feature Inventory Coverage Matrix (`PROJECT.md` Features #1–#12)

Every single feature in `PROJECT.md § Feature Inventory` is mapped to concrete automated E2E tests and/or pipeline gates:

| # | `PROJECT.md` Feature | Milestone | Automated E2E Test IDs & Suites |
|---|---|---|---|
| 1 | Persistent cache symlink & zero-rebuild `tree_species_v13` | M1 | **`T2.V13.V01`** (`tier2_v13_vegetation.py`), `T1.FA1.01`–`T1.FA1.06` (`tier1_assets_data.py`) |
| 2 | 8 Swiss/Zürichsee botanical tree species | M1 | **`T2.V13.V01`**, **`T2.V13.V02`**, **`T2.V13.V03`** (`tier2_v13_vegetation.py`), `T2.V12.03`, `T2.V12.04` (`tier2_v12_visuals.py`) |
| 3 | 4 botanical bush/hedge types & cel-shaded vineyards | M1 | **`T2.V13.V01`**, **`T2.V13.V02`**, **`T2.V13.V03`** (`tier2_v13_vegetation.py`), `T2.FA1.05` (`tier2_quality_bounds.py` spotless lake) |
| 4 | Mandatory 1:1 botanical crop visual verification & `verify_quality.py` v13 checks | M1 | **`T2.V13.V01`–`T2.V13.V04`** (`tier2_v13_vegetation.py`) + `.venv/bin/python -m pipeline.verify_quality` |
| 5 | Modular `LivingEngine` core (`docs/js/living/`) | M2A | **`T2.V13.L01`**, **`T2.V13.L02`**, **`T2.V13.L05`**, **`T2.V13.L06`** (`tier2_v13_living.mjs`) |
| 6 | Uplevelled Transit & Street Life plugins (`trains`, `traffic`, `pedestrians`) | M2A | **`T2.V13.L01`–`T2.V13.L05`** (`tier2_v13_living.mjs`), `T2.SM.03` (`tier2_smoothness.mjs`), `T2.FA3.07`, `T2.FA3.08` (`tier2_browser_bounds.mjs`), `T3.09`, `T3.12` (`tier3_combinations.mjs`), `T4.10`, `T4.11` (`tier4_journeys.mjs`) |
| 7 | Uplevelled Lake Zurich & Wildlife plugins (`shoreline`, `vessels`, `wildlife`) | M2A | **`T2.V13.L01`–`T2.V13.L04`** (`tier2_v13_living.mjs`), `T2.FA3.09` (`tier2_browser_bounds.mjs`), `T2.FA2.08` (`tier2_quality_bounds.py`) |
| 8 | Uplevelled Seebad, Sports, Landmarks & Atmosphere plugins (`seebad`, `sports`, `landmarks`, `atmosphere`) | M2B | **`T2.V13.L01`–`T2.V13.L05`** (`tier2_v13_living.mjs`), `T2.LET.07` (`tier2_lettering.py`), `T2.LM.01`, `T2.LM.02` (`tier2_landmarks_v11.py`), `T3.10` (`tier3_combinations.mjs`) |
| 9 | Viewer & Audio integration (`app.js`, `audio.js`, `index.html`, `vignettes.js` anchors, `ASSET_VER = '13.0'`) | M2B | **`T2.V13.L01`–`T2.V13.L06`** (`tier2_v13_living.mjs`), **`T2.V13.V04`** (`tier2_v13_vegetation.py`), `T1.FA3.12`, `T1.FA3.13`, `T1.FA4.03`–`T1.FA4.05` (`tier1_browser_features.mjs`), `T2.FA4.01`–`T2.FA4.05` (`tier2_browser_bounds.mjs`) |
| 10 | Full `0.11 m/px` 3-preset botanical world render & quality gate | M3 | **`T2.V13.V01`–`T2.V13.V04`** (`tier2_v13_vegetation.py`), `T2.V12.01`–`T2.V12.05` (`tier2_v12_visuals.py`), `T1.FA1.01`–`T1.FA1.11` (`tier1_assets_data.py`), `T2.FA1.01`–`T2.FA1.12` (`tier2_quality_bounds.py`) |
| 11 | Requirement-driven v13.0 E2E suites (`tier2_v13_living.mjs`, `tier2_v13_vegetation.py`, `run_e2e.py`, `TEST_INFRA.md`, `TEST_READY.md`) | E2E | All 12 suites registered in `tests/run_e2e.py` (**135 total tests**: 65 Python + 70 Node CDP) |
| 12 | Final 100% E2E pass (135/135) + Tier 5 Hardening + Preview Captures + Publish | M4 | Full `--tier all` run (135/135 PASS) + Tier 5 adversarial audit + GitHub Pages `"built"` check |

---

## 3. 4-Tier Testing Methodology (+ Tier 5 White-Box Hardening Reference)

| Tier | Purpose | Suites & Counts |
|---|---|---|
| **Tier 1 — Smoke & Feature Coverage** | Fast verification that every static asset, manifest, tile pyramid, depth map, JSON schema, audio track, and interactive browser feature boots and operates cleanly with zero errors. | `tier1_assets_data.py` (24) + `tier1_browser_features.mjs` (17) = **41 tests** |
| **Tier 2 — Bounds, Quality, Smoothness, Living Layer & Botanical Vegetation** | Mathematical and perceptual invariants: diurnal luminance, CLUTs, tile seams, floating sky clusters, lake/sunset/night lighting, Lindt roof, baked lettering, v11 landmark photo-realism, v12 anti-stipple / `< 500 KB` VP8L / `< 300 MB` `docs/`, **v13 botanical vegetation diversity / anti-bubble / diurnal fidelity / `ASSET_VER=13.0` budget**, v12 camera inertia / smooth wheel zoom / sub-50ms interpolation / compositor pins / `frameStats`, **v13 modular LivingEngine lifecycle / determinism / diurnal adaptation / inspectables & shore-strict audio / 60fps budget / dynamic extensibility**, and layout/Retina/IDM/SUP/tile-streaming/audio bounds. | `tier2_quality_bounds.py` (20) + `tier2_lettering.py` (7) + `tier2_landmarks_v11.py` (5) + `tier2_v12_visuals.py` (5) + **`tier2_v13_vegetation.py` (4)** + `tier2_browser_bounds.mjs` (16) + `tier2_smoothness.mjs` (5) + **`tier2_v13_living.mjs` (6)** = **68 tests** |
| **Tier 3 — Cross-Feature Combinations** | Pairwise feature interactions: lighting × living world, zoom/tiles × follow camera, search × inspector × direct landmark fly-to, lighting × audio, deep-link × `?t=` round-trip, Cinema/Sidebar × resize, deterministic `?t=10` identity (`T3.07`), diurnal shift, `0.11 m/px` train/bus roof opacity (`T3.09`, `T3.12`), bell sync, `?landmark=` & `[/]`, `11 cm/px` scale bar (`T3.13`). | `tier3_combinations.mjs` = **13 tests** |
| **Tier 4 — End-User Journeys & Hardening** | 8 full end-to-end user journeys (`T4.01`–`T4.07`, `T4.13`) + 5 regression hardening checks (`T4.08`–`T4.12`: rAF non-multiplication, extreme `?t=`, bus advancement, train click hygiene, mobile topbar overflow). | `tier4_journeys.mjs` = **13 tests** |
| **Tier 5 — White-Box Adversarial Hardening (M4 Reference)** | Post-green adversarial audit inspecting implemented `docs/js/living/*`, `pipeline/pixel_shader.py`, `camera.js`, `tiles.js`, `depth.js`, and edge cases, adding targeted regression tests for any discovered gap. | Executed in M4 after Tiers 1–4 reach 135/135 PASS |

---

## 4. Zero-Flake Headless Chromium Guidelines

Headless Chromium in CI runs CPU software rendering (SwiftShader / Skia) where wall-clock FPS fluctuates with host CPU load. Every browser test in `tests/tier2_v13_living.mjs`, `tests/tier2_smoothness.mjs`, and the wider suite obeys these strict anti-flake rules:

1. **Never assert hardcoded FPS floors (e.g., `fps >= 58`)** in headless software mode. Instead, assert **structural and relative smoothness invariants**:
   - Bounded JS frame budget on living-layer hooks (`livingRegistry.updateMs` and `livingRegistry.drawMs` finite in `[0, 50)`), single-loop rAF non-multiplication on Live Off/On toggles, and bounded tile LRU cache (`frameStats.tileCacheSize <= 128`).
   - Inertial coasting displacement after `pointerup`, multi-frame smooth wheel zoom with focal-point UV invariance, compositor-only `.lm-pin` transforms, and sub-50ms interpolation.
2. **Sequential `dpr=2` Tab Discipline**: Open and close `dpr=2` tabs sequentially (at most one active at a time in determinism/diurnal probes) to keep memory and CPU deterministic under software rendering.
3. **Deterministic `?t=` Contract**: All living plugins use deterministic seeded PRNG (`rngFor`) and bypass non-deterministic timers when `?t=` is supplied, so sequential two-tab `?t=10` captures produce `maxDiff === 0` byte-identical canvases and identical `livingRegistry.perPluginCounts` + `simStats`.
4. **Offline Resilience & Strict Error Accounting**: External font CDNs are blocked via `Network.setBlockedURLs`; zero same-origin HTTP `>= 400`, zero `Network.loadingFailed`, zero `Runtime.exceptionThrown`, and zero `console.error` are permitted.
5. **Clean Diagnostic Failure Messages**: Every assertion emits measured values alongside expected bounds, enabling immediate triage without guesswork.
6. **Atomic Teardown**: All temporary browser profiles, ephemeral HTTP servers, and Chromium child processes are torn down in `finally` blocks and signal handlers, leaving `0` live orphan processes.

---

## 5. Coverage Thresholds & Execution Budgets

| Metric | Required Threshold |
|---|---|
| Tier 1 feature coverage | **41 tests** (`tier1_assets_data.py`: 24, `tier1_browser_features.mjs`: 17) |
| Tier 2 bounds, quality, smoothness, living & vegetation | **68 tests** (`quality_bounds`: 20, `lettering`: 7, `landmarks_v11`: 5, `v12_visuals`: 5, **`v13_vegetation`: 4**, `browser_bounds`: 16, `smoothness`: 5, **`v13_living`: 6**) |
| Tier 3 cross-feature pairwise coverage | **13 tests** (`tier3_combinations.mjs`) |
| Tier 4 real-world journeys & hardening | **13 tests** (`tier4_journeys.mjs`) |
| **Total E2E suite size** | **135 tests** (**65 Python** + **70 Node CDP**) |
| Per-suite timeout budget | `120 s` (`tests/run_e2e.py --timeout 120`) |
| Orphan process tolerance | `0` live Chromium/Node/HTTP processes after run completion |
