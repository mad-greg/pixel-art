# Test Infrastructure — Kilchberg (ZH) Isometric Pixel-Art Diorama (v8.0 Living-World Simulation Overhaul & Train/Bus Depth-Occlusion Fix)

## 1. Test Philosophy

This E2E testing track implements an **opaque-box, requirement-driven 4-tier automated test suite** derived strictly from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` & `§ Interface Contracts` — **never** from internal Python pipeline functions or private JavaScript variables.

Core principles:
1. **Zero-Install Native Runtime**: Runs directly on the provisioned VM toolchain without `pip install` or `npm install`:
   - **Python 3.11** (`unittest`, `numpy`, `Pillow`, `ffprobe`) for static asset, manifest, tile pyramid, depth-map, JSON schema, audio integrity, pixel-quality, and geometric constraint verification.
   - **Node.js 24** (built-in global `WebSocket` + `fetch` native Chrome DevTools Protocol driver) + **`/usr/bin/chromium`** (`--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage`) against an ephemeral local `node:http` server serving `docs/` (including native ES modules under `docs/js/**/*.js` with `?v=` query-string stripping) for live interactive web app, layout, Retina DPR, animation, spatial audio, and end-user journey verification.
2. **Real User Gestures & Authentic Browser Contracts**:
   - Chromium is launched **without** `--autoplay-policy=no-user-gesture-required`; WebAudio unlocking is exercised through real trusted CDP `Input.dispatchMouseEvent` clicks on `#btn-toggle-sound`, validating genuine production autoplay compliance.
   - External CDN font URLs (`fonts.googleapis.com` / `fonts.gstatic.com`) are blocked via CDP `Network.setBlockedURLs` to verify offline/self-contained resilience (`PROJECT.md § Interface Contracts #3`), while local origin (`127.0.0.1`) enforces zero HTTP `>= 400` application-asset or ES module failures, zero `Runtime.exceptionThrown`, and zero `console.error`.
3. **Anti-Tautology & Honest Pre-v8.0 Failure Semantics**:
   - Every test asserts real user-facing behavior, pixel metrics, geometric invariants, or public contract fields (`document.body.dataset.mode`, `window.__dioramaDebug` including `simStats`, `depthStats`, `livingCounts`, `audioGains`).
   - Against pre-v8.0 (`v7.0`) code, all 70 existing tests continue to pass 100% intact, while new v8.0 tests covering unimplemented requirements (M1 open-air roof occlusion fix & 2× roof opacity, M2 compact `network` multimodal graph schema & DEM/zero-water bounds, M3 native ES module split, deterministic fixed-timestep `?t=` simulation, 1D IDM car-following/bus-dwell queueing & `simStats`, and M4 diurnal activity shift, O–D transit transfers, synced church bells & entity trip inspection) **must fail cleanly with crisp `AssertionError` diagnostics** — never silently skip or pass vacuously.
   - Harness, syntax, import, timeout, or process-leak errors are strictly forbidden in every tier.
4. **Determinism, Speed & Process Hygiene**:
   - Deterministic URL timestamps (`?t=10`, `?t=15`, `?t=22`, `?t=34`, `?t=35`, `?t=46`) enable reproducible frame-motion, roof-opacity, IDM braking/yielding, and church-bell phase assertions.
   - One shared headless Chromium browser per Node runner with isolated incognito `Target.createBrowserContext` tabs keeps every tier `< 30 s` and `--tier all` `< 90 s`.
   - Every local HTTP server, Chromium child process (sharing Node's process group so `os.killpg` terminates Node + Chromium atomically, with `forceClose()` signal teardown & `Browser.close` → `SIGTERM` → `SIGKILL` fallback), and temporary profile directory is torn down in `finally` blocks + signal handlers, leaving zero live orphan processes.

---

## 2. Feature Inventory Mapped to Requirements & Test Tiers

Every requirement from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` (v7.0 baseline + v8.0 F1–F23, Interface Contracts #1–#4, and Global Guardrails) is grouped into **4 Requirement Feature Areas** (`FA1`–`FA4`), covered across **83 total tests** (36 Python + 47 Node CDP):

| Feature Area | `PROJECT.md` / `ORIGINAL_REQUEST.md` Mapping | Tier 1 (Feature Coverage) | Tier 2 (Boundary & Corner Cases) | Tier 3 (Cross-Feature) | Tier 4 (Journeys) |
|---|---|---|---|---|---|
| **FA1: Static Visual Assets, Tile Pyramid, Depth Map, ES Modules & Detail Plates** | v7.0 F4–F14 + v8.0 F1, F2, F7; Contract #1 & #3 (`12331×5444`, `78×3` lossless tiles, `6165×2722` overviews & depth PNG, open-air roof small hits `<2%` trains & `<1%` main roads, `<script type="module" src="app.js?v=...">` synced with `styles.css`, `docs/js/` modules, 6 detail plates, `<=256` SVGA CLUTs, zero floating artifacts, spotless shore, sunset gold, night pools, Lindt 25 cm roof) | `T1.FA1.01`–`T1.FA1.09` (9 tests) | `T2.FA1.01`–`T2.FA1.09` (9 tests) | `T3.01`, `T3.02`, `T3.05`, `T3.09` | Journey 1, Journey 2, Journey 7 |
| **FA2: Geospatial Metadata, Landmarks, Multimodal Network & Guardrails** | v7.0 F3, F15–F17 + v8.0 F3–F6, F19; Contract #2 & #4 (`kilchberg_interactive.json`, `kilchberg_animations.json <650 KB`, backward-compatible `trains`/`roads`/`ships`/`ambient` + `network` schema: `crosswalks`, `junctions`, `feeders`, `footpaths`, `pois`, `extra_sports`, all vertices in `[0,1]` UV with non-spiking `d16`, inside `island_2x` & zero Lake Zurich water intrusion, slow SUP/rowboat speed bounds, zero paragliders/balloons recursively across `docs/`) | `T1.FA2.01`–`T1.FA2.09` (9 tests) | `T2.FA2.01`–`T2.FA2.07` (7 tests) | `T3.02`, `T3.03`, `T3.08` | Journey 2, Journey 3, Journey 4, Journey 7 |
| **FA3: Interactive Web App, Living-World Simulation, Roof Opacity & Cartographic HUD** | v7.0 F18–F25 + v8.0 F2, F7–F19, F21; Contract #1 & #3 (zero JS/404/ES-module errors, lighting presets + `body[data-mode]`, zoom/tiles, landmarks, building click/highlight, address search, detail-plate modal, cinema mode, collapsible sidebar, compass/scale bar, share permalink, postcard export, `window.__dioramaDebug` 13 Contract #5 keys + `simStats`/`livingCounts`/`depthStats`, realistic density bounds, active 1D IDM braking/yielding & non-gridlock, SUP water-mask & diurnal guardrail, cross-tab deterministic `?t=10` vs `?t=15`, diurnal activity shift `day`/`sunset`/`night`, 2× train & bus roof opacity + foreground occlusion, entity trip inspection, Desktop `1280×800` & Mobile `390×844` layout) | `T1.FA3.01`–`T1.FA3.13` (13 tests) | `T2.FA3.01`–`T2.FA3.09` (9 tests) | `T3.01`, `T3.02`, `T3.03`, `T3.05`, `T3.06`, `T3.07`, `T3.08`, `T3.09` | Journey 1, Journey 2, Journey 3, Journey 4, Journey 6, Journey 7 |
| **FA4: Spatial Audio Soundscape, Church Bell Sync & Layer Mixer** | v7.0 F26 + v8.0 F20; Contract #3 & #4 (9 valid MP3 field recordings via `ffprobe`, trusted-gesture AudioContext unlock & 9/9 decode, shore-strict wave attenuation at overview vs near-shore loudness, Day birds vs Night crickets, paused animations still updating spatial audio, mute suspending AudioContext, `simStats.bellPhase` ↔ `audioGains.bells` ringing/silent cycle sync, layer mixer popover) | `T1.FA4.01`–`T1.FA4.05` (5 tests) | `T2.FA4.01`–`T2.FA4.05` (5 tests) | `T3.04`, `T3.10` | Journey 5 |

---

## 3. Test Architecture

```text
tests/
├── run_e2e.py                    # Unified CLI runner (--tier 1|2|3|4|all, --verbose, --json-report, --timeout)
├── lib/
│   ├── __init__.py
│   ├── report.py                 # Unified TestCaseResult / TierResult dataclasses, PASS/FAIL table & JSON summary
│   ├── assets_helper.py          # Cached loaders for docs/data/*.json, WebPs, depth PNG, manifests, ffprobe, RLE components, Lake Zurich 2x mask & depth roof small-hit counter
│   └── cdp_harness.mjs           # Zero-dep Node 24 CDP driver, local docs/ HTTP server (ES modules + ?v=), shared Chromium + isolated incognito contexts, native ROI roof opacity analyzer
├── tier1_assets_data.py          # Tier 1 (Python, 20 tests): FA1 (9), FA2 (9), FA4 static (2)
├── tier1_browser_features.mjs    # Tier 1 (Node CDP, 16 tests): FA3 (13), FA4 live (3)
├── tier2_quality_bounds.py       # Tier 2 (Python, 16 tests): FA1 (9), FA2 (7)
├── tier2_browser_bounds.mjs      # Tier 2 (Node CDP, 14 tests): FA3 (9), FA4 (5)
├── tier3_combinations.mjs        # Tier 3 (Node CDP, 10 tests): pairwise cross-feature suites (T3.01–T3.10)
└── tier4_journeys.mjs            # Tier 4 (Node CDP, 7 tests): real-world end-user application journeys (T4.01–T4.07)
```

### Orchestration & Reporting Protocol
- Command: `.venv/bin/python tests/run_e2e.py --tier <1|2|3|4|all>` (also supports comma-separated lists like `--tier 1,2`, `--verbose`, `--json-report <path>`, `--timeout <sec>`).
- Python test modules run via stdlib `unittest` collected by `tests/lib/report.py`.
- Node CDP test modules receive `--result-json <tmpfile>` (allocated inside a `TemporaryDirectory` owned by `run_e2e.py`) so Chromium wrapper stderr noise never corrupts structured per-test reporting.
- **Exit Code Contract**:
  - `0` iff all requested tiers complete cleanly, total tests executed `> 0`, `failed == 0`, and `errors == 0`.
  - `1` on any assertion failure, runtime error, or missing result file.
  - `124` on tier timeout (after terminating the subprocess group via `os.killpg`).

### Opaque-Box Public Contract Dependencies
- Static files under `docs/assets/`, `docs/data/`, and `docs/js/`:
  - `docs/assets/kilchberg_depth.png`: `6165×2722` RGB (`R/G` 16-bit depth, `B` binary occluder), `0.12 <= occ_frac <= 0.35`, open-air roof small hits `< 2%` trains and `< 1%` main roads.
  - `docs/assets/diorama_day.webp`: opaque-box largest blue 4-connected component (eroded `size=5`, ~2 m shoreline buffer) for zero water intrusion verification.
  - `docs/data/kilchberg_animations.json`: `< 650 KB`, backward-compatible `trains`/`roads`/`ships`/`ambient` plus `network` (`crosswalks`, `junctions`, `feeders`, `footpaths`, `pois`, `extra_sports`).
  - `docs/index.html`: `<script type="module" src="app.js?v=...">` synced with `styles.css?v=...`, zero external CDN scripts, modular ES files under `docs/js/`.
- Public DOM controls (`docs/index.html`) accessed via stable IDs, semantic ARIA/title/placeholder/text locators, and `document.body.dataset.mode`.
- Public URL query parameters: `?mode=`, `?zoom=`, `?u=`, `?v=`, `?pins=`, `?cinema=`, `?follow=`, `?t=`.
- Read-only telemetry accessor (`PROJECT.md § Interface Contracts #3`): `window.__dioramaDebug` (read via `typeof window.__dioramaDebug === 'function' ? window.__dioramaDebug() : window.__dioramaDebug`), exposing all 13 Contract #5 keys (`mode, scale, u, v, dpr, animTime, fps, audioEnabled, audioState, audioGains, activeLandmark, selectedBuilding, searchResultCount`) plus `livingCounts`, `depthStats`, `waterMaskReady`, `followTarget`, and v8.0 `simStats` (`{ vehicles, brakingCount, yieldingCount, pedestrians, boardingCount, activeTrips, bellPhase }`).

---

## 4. Tier 4 — Real-World Application Scenarios (7 End-User Journeys)

1. **Journey 1 — First-Time Visitor Full Tour (`T4.01`)**:
   - Cold desktop boot (`1280×800`, DPR=2) at Overview `Fit` → verify zero JS/asset errors & clean non-clipped layout → switch `Midday` → `Alpenglow` → `Night` verifying `body[data-mode]` and distinct canvas rendering → enter Cinema Mode (`H`) verifying chrome hides & viewport expands → exit Cinema (`Esc`) → trigger Postcard PNG export without errors.
2. **Journey 2 — Lindt HoC & Schooren Seebad Deep-Zoom Inspection (`T4.02`)**:
   - Navigate to Lindt Home of Chocolate & zoom to `2×` (`0.25 m/px` WebP tiles streaming via HTTP 200) → open `01_lindt_home_of_chocolate.webp` (`0.22 m/px` detail plate) → verify modal zoom controls (`1:1`, `2×`, `4×`) and "Fly Here" → pan to Schooren Seebad (`schooren_seebad`), verify live water/SUP animation motion between `?t=10` and `?t=15` and spotless shore assets.
3. **Journey 3 — Commuter Transit Showcase (`T4.03`)**:
   - Inspect Bahnhof Kilchberg (`bahnhof_stockengut`) with Follow Camera cycling `Train` (`sbb_s8_south` double-decker S-Bahn dwelling at Bahnhof platform) → `Boat` (`zsg_ms_helvetia` docking cleanly at Bendlikon Pier `Badweg 1.1` with wake shutoff during dwell) → `Bus` (ZVV bus on smooth curved Dorfstrasse viaduct), verifying high-zoom tile streaming, motion, and zero errors.
4. **Journey 4 — Kilchberg Resident Address Lookup (`T4.04`)**:
   - Use instant address search across `1,887` Kilchberg buildings (query `"Schoorenstrasse 1"` / `"Seestrasse"`) → select result → verify inspector updates (`#insp-title`, `#insp-specs`, `selectedBuilding`) → trigger Share Permalink → open the generated deep-link URL in a **fresh incognito tab** and assert mode, zoom, and `(u, v)` viewport restore accurately.
5. **Journey 5 — Spatial Soundscape Walk (`T4.05`)**:
   - Unlock spatial audio via real trusted click on `#btn-toggle-sound` → verify `AudioContext` `running` & 9/9 MP3s decoded → verify overview wave attenuation vs zoomed Lake Zurich shore waves loudness → pan uphill to wooded ridge verifying virtual tree birds (`birds > 0`) → inspect A3 motorway vs town car channels → switch to `Night` verifying crickets > birds & synced church bells → open audio layer mixer popover, adjust sliders, and mute verifying `AudioContext.state === 'suspended'`.
6. **Journey 6 — Mobile Portrait Explorer (`T4.06`)**:
   - Emulate mobile portrait (`390×844`, DPR=2, `mobile: true`) → verify zero bottom/right viewport clipping & clean responsive layout → switch lighting presets (`day` → `sunset` → `night`) → select a landmark from the tour list → verify smooth rendering and zero JS/network errors.
7. **Journey 7 — Living Kilchberg Commuter & Village Life (`T4.07`)**:
   - Cold live desktop boot (`/?mode=day`, `1280×800`, DPR=2) → navigate to Bahnhof Kilchberg at `2×` verifying active `simStats` (`activeTrips > 0`, `pedestrians > 0`, `vehicles > 0`) → engage `Follow: Train` verifying tile streaming & non-blank canvas → switch to `Follow: Bus` sampling valid `vehicles` and `brakingCount` across dwell/queueing → visit Bendlikon Pier, Lindt HoC (`2×`), and Schooren Seebad (`2×`, `waterMaskReady === true`, `livingCounts.sups >= 2`) → click viewport center during `Follow: Train` to exercise entity trip inspection → verify `#insp-title` populated, zero layout clipping, and zero JS/console/HTTP errors.

---

## 5. Coverage Thresholds & Performance Targets

| Metric | Required Threshold |
|---|---|
| Tier 1 feature coverage | `>= 5` tests per feature area (`FA1`: 9, `FA2`: 9, `FA3`: 13, `FA4`: 5; total **36**) |
| Tier 2 boundary & corner coverage | `>= 5` tests per feature area (`FA1`: 9, `FA2`: 7, `FA3`: 9, `FA4`: 5; total **30**) |
| Tier 3 cross-feature pairwise coverage | **10** pairwise combination suites (`T3.01`–`T3.10`) |
| Tier 4 real-world journeys | **7** end-to-end user journeys (`T4.01`–`T4.07`) |
| Total E2E test suite size | **83 tests** (70 preserved baseline + 13 new v8.0 tests; 36 Python + 47 Node CDP) |
| Per-tier runtime budget | `< 30 s` per tier |
| Full `--tier all` runtime budget | `< 90 s` total wall-clock time |
| Orphan process tolerance | `0` live non-zombie Chromium/Node/HTTP processes after run completion |
| Harness error tolerance | `0` syntax, import, timeout, or uncaught harness exceptions on both pre-v8.0 and v8.0 |
