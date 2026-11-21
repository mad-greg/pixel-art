# Test Infrastructure — Kilchberg (ZH) Isometric Pixel-Art Diorama (v9.0 Museum-Grade Landmark Polish & Expansion)

## 1. Test Philosophy

This E2E testing track implements an **opaque-box, requirement-driven 4-tier automated test suite** derived strictly from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` & `§ Interface Contracts` — **never** from internal Python pipeline functions or private JavaScript variables.

Core principles:
1. **Zero-Install Native Runtime**: Runs directly on the provisioned VM toolchain without `pip install` or `npm install`:
   - **Python 3.11** (`unittest`, `numpy`, `Pillow`, `ffprobe`) for static asset, manifest, tile pyramid, depth-map, detail-plate, JSON schema, audio integrity, pixel-quality, and geometric constraint verification.
   - **Node.js 24** (built-in global `WebSocket` + `fetch` native Chrome DevTools Protocol driver) + **`/usr/bin/chromium`** (`--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage`) against an ephemeral local `node:http` server serving `docs/` (including native ES modules under `docs/js/**/*.js` with `?v=` query-string stripping) for live interactive web app, layout, Retina DPR, overview pin decluttering, deep-link/keyboard navigation, animation, spatial audio, and end-user journey verification.
2. **Real User Gestures & Authentic Browser Contracts**:
   - Chromium is launched **without** `--autoplay-policy=no-user-gesture-required`; WebAudio unlocking is exercised through real trusted CDP `Input.dispatchMouseEvent` clicks on `#btn-toggle-sound`, validating genuine production autoplay compliance.
   - External CDN font URLs (`fonts.googleapis.com` / `fonts.gstatic.com`) are blocked via CDP `Network.setBlockedURLs` to verify offline/self-contained resilience (`PROJECT.md § Interface Contracts #4`), while local origin (`127.0.0.1`) enforces zero HTTP `>= 400` application-asset or ES module failures, zero `Runtime.exceptionThrown`, and zero `console.error`.
3. **100% Baseline Preservation & Honest Pre-v9.0 Failure Semantics**:
   - All **88** pre-existing v8.0 tests (70 v7.0 baseline + 13 v8.0 living-world + 5 Tier 5 hardening tests `T4.08`–`T4.12`) are preserved 100% intact. Only the two hardcoded `== 10` landmark-count checks (`T1.FA2.01` and `T1.FA3.04`) were relaxed to `>= 10` while strictly enforcing that the original 10 `REQUIRED_LANDMARK_IDS` remain at indices `0..9`. `T1.FA2.07` (`ambient.swiss_flags == 4`) and `DETAIL_PLATES` (`01..06_*.webp`) remain strictly untouched.
   - Every new v9.0 test checks preconditions cleanly and asserts real user-facing behavior, pixel metrics, geometric invariants, or public contract fields — failing cleanly with crisp `AssertionError` diagnostics against pre-v9.0 (`v8.0`) `docs/` with zero syntax, import, `FileNotFoundError`, `KeyError`, timeout, or process-leak errors.
4. **Determinism, Speed & Process Hygiene**:
   - Deterministic URL timestamps (`?t=10`, `?t=15`, `?t=22`, `?t=34`, `?t=35`, `?t=46`, `?t=48`) enable reproducible frame-motion, roof-opacity, IDM braking/yielding, deep-link, and church-bell phase assertions.
   - One shared headless Chromium browser per Node runner with isolated incognito `Target.createBrowserContext` tabs and per-suite timeout `120 s` keeps `--tier all` clean and deterministic.
   - Every local HTTP server, Chromium child process (sharing Node's process group so `os.killpg` terminates Node + Chromium atomically, with `forceClose()` signal teardown & `Browser.close` → `SIGTERM` → `SIGKILL` fallback), and temporary profile directory is torn down in `finally` blocks + signal handlers, leaving zero live orphan processes.

---

## 2. Feature Inventory Mapped to Requirements & Test Tiers

Every requirement from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` (v7.0/v8.0 baseline + v9.0 Features #1–#21, Interface Contracts #1–#4, and Global Guardrails) is grouped into **4 Requirement Feature Areas** (`FA1`–`FA4`), covered across **97 total tests** (41 Python + 56 Node CDP):

| Feature Area | `PROJECT.md` / `ORIGINAL_REQUEST.md` Mapping | Tier 1 (Feature Coverage) | Tier 2 (Boundary & Corner Cases) | Tier 3 (Cross-Feature) | Tier 4 (Journeys & Hardening) |
|---|---|---|---|---|---|
| **FA1: Static Visual Assets, Tile Pyramid, Depth Map, ES Modules & 10 Detail Plates** | v7.0/v8.0 assets + v9.0 F4–F16; Contract #2 & #4 (`12331×5444`, `78×3` lossless tiles, `6165×2722` overviews & depth PNG, open-air roof small hits `<2%` trains & `<1%` main roads, `<script type="module" src="app.js?v=...">` synced with `styles.css`, `docs/js/` modules, **10 detail plates `01..10_*.webp`** lossless `VP8L` RGB `>=2000×1400` `<=256` SVGA CLUTs, zero floating sky clusters + visual richness `std_luma>=20` & `entropy>=2.5`, spotless shore, sunset gold, night pools, Lindt 25 cm DOP10 roof) | `T1.FA1.01`–`T1.FA1.10` (10 tests) | `T2.FA1.01`–`T2.FA1.10` (10 tests) | `T3.01`, `T3.02`, `T3.05`, `T3.09` | `T4.01`, `T4.02`, `T4.07`, `T4.13` |
| **FA2: Geospatial Metadata, 16 Landmarks, Authentic `cf_meyer_haus`, Vignettes & Multimodal Network** | v7.0/v8.0 data + v9.0 F2, F3, F17; Contract #1, #3 & #4 (`kilchberg_interactive.json` `>=16` landmarks preserving `0..9` + 6 new Tier-1 IDs, `cf_meyer_haus` `<=35 m` LV95 of `E=2683714, N=1241442`, all 16 inside `island_2x` with pairwise `duv>=0.045`, `kilchberg_animations.json <650 KB`, `ambient.swiss_flags == 4`, `ambient.vignettes` covering `sanatorium_ridge`, `moenchhof_horn`, `sulzergut_park` + 6 new landmarks in `[0,1]` UV, `cf_meyer_haus` vignette & fountain aligned `<=0.02` UV, `network` DEM/zero-water bounds, slow SUPs, zero paragliders/balloons) | `T1.FA2.01`–`T1.FA2.11` (11 tests) | `T2.FA2.01`–`T2.FA2.08` (8 tests) | `T3.02`, `T3.03`, `T3.08`, `T3.11` | `T4.02`, `T4.03`, `T4.04`, `T4.07`, `T4.13` |
| **FA3: Interactive Web App, 16-Landmark UX, Pin Decluttering, Deep-Links & Living-World Simulation** | v7.0/v8.0 UI/sim + v9.0 F18, F19; Contract #1, #2 & #4 (zero JS/404/ES-module errors, lighting presets, zoom/tiles, `>=16` sidebar stops with dynamic `${N} STOPS` tag, `>=10` `#crop-gallery` plates with `01..06` preserved at `0..5` & `07..10` modal open, zoom-aware overview pin decluttering at `cssScale < 0.7` with zero severe overlap & active-pin persistence, `?landmark=<id>` deep-link boot & `[`/`]` keyboard landmark cycling, `window.__dioramaDebug` Contract #5 + `simStats`/`livingCounts`/`depthStats`, IDM/SUP/roof-opacity, Desktop `1280×800` & Mobile `390×844` zero clipping) | `T1.FA3.01`–`T1.FA3.14` (14 tests) | `T2.FA3.01`–`T2.FA3.10` (10 tests) | `T3.01`–`T3.03`, `T3.05`–`T3.09`, `T3.11` | `T4.01`–`T4.04`, `T4.06`–`T4.13` |
| **FA4: Spatial Audio Soundscape, Church Bell Sync & Layer Mixer** | v7.0/v8.0 audio; Contract #3 & #4 (9 valid MP3 field recordings via `ffprobe`, trusted-gesture AudioContext unlock & 9/9 decode, shore-strict wave attenuation, Day birds vs Night crickets, paused animations audio updates, mute suspending AudioContext, `simStats.bellPhase` ↔ `audioGains.bells` sync, layer mixer popover) | `T1.FA4.01`–`T1.FA4.05` (5 tests) | `T2.FA4.01`–`T2.FA4.05` (5 tests) | `T3.04`, `T3.10` | `T4.05` |

---

## 3. Test Architecture

```text
tests/
├── run_e2e.py                    # Unified CLI runner (--tier 1|2|3|4|all, --verbose, --json-report, --timeout)
├── lib/
│   ├── __init__.py
│   ├── report.py                 # Unified TestCaseResult / TierResult dataclasses, PASS/FAIL table & JSON summary
│   ├── assets_helper.py          # Cached loaders for docs/data/*.json, WebPs (10 plates), depth PNG, manifests, ffprobe, RLE components, Lake Zurich 2x mask, RGB color counter & vignette UV extractor
│   └── cdp_harness.mjs           # Zero-dep Node 24 CDP driver, local docs/ HTTP server (ES modules + ?v=), shared Chromium + isolated incognito contexts, native ROI roof opacity analyzer
├── tier1_assets_data.py          # Tier 1 (Python, 23 tests): FA1 (10), FA2 (11), FA4 static (2)
├── tier1_browser_features.mjs    # Tier 1 (Node CDP, 17 tests): FA3 (14), FA4 live (3)
├── tier2_quality_bounds.py       # Tier 2 (Python, 18 tests): FA1 (10), FA2 (8)
├── tier2_browser_bounds.mjs      # Tier 2 (Node CDP, 15 tests): FA3 (10), FA4 (5)
├── tier3_combinations.mjs        # Tier 3 (Node CDP, 11 tests): pairwise cross-feature suites (T3.01–T3.11)
└── tier4_journeys.mjs            # Tier 4 (Node CDP, 13 tests): 8 end-user journeys (T4.01–T4.07, T4.13) + 5 Tier 5 hardening tests (T4.08–T4.12)
```

### Orchestration & Reporting Protocol
- Command: `.venv/bin/python tests/run_e2e.py --tier <1|2|3|4|all>` (supports comma-separated lists like `--tier 1,2`, `--verbose`, `--json-report <path>`, `--timeout <sec>`).
- Python test modules run via stdlib `unittest` collected by `tests/lib/report.py`.
- Node CDP test modules receive `--result-json <tmpfile>` (allocated inside a `TemporaryDirectory` owned by `run_e2e.py`) so Chromium wrapper stderr noise never corrupts structured per-test reporting.
- **Exit Code Contract**:
  - `0` iff all requested tiers complete cleanly, total tests executed `> 0`, `failed == 0`, and `errors == 0`.
  - `1` on any assertion failure, runtime error, or missing result file.
  - `124` on tier timeout (after terminating the subprocess group via `os.killpg`).

### Opaque-Box Public Contract Dependencies
- Static files under `docs/assets/`, `docs/data/`, and `docs/js/`:
  - `docs/assets/01..10_*.webp`: 10 high-res `0.22 m/px` detail plates (`VP8L` RGB, `>= 2000×1400`, body `<= 256` colors, zero floating sky clusters, `std_luma >= 20`, `entropy >= 2.5`).
  - `docs/assets/kilchberg_depth.png`: `6165×2722` RGB (`R/G` 16-bit depth, `B` binary occluder), `0.12 <= occ_frac <= 0.35`, open-air roof small hits `< 2%` trains and `< 1%` main roads.
  - `docs/data/kilchberg_interactive.json`: `>= 16` landmarks (`0..9` preserved + 6 new Tier-1 IDs), `cf_meyer_haus` `<= 35 m` LV95 of `E=2683714, N=1241442`, all inside `island_2x` with pairwise `duv >= 0.045`.
  - `docs/data/kilchberg_animations.json`: `< 650 KB`, `ambient.swiss_flags` length `4`, `ambient.vignettes` covering all 9 newly/previously un-vignetted landmarks in `[0, 1]` UV, `cf_meyer_haus` vignette & fountain aligned `<= 0.02` UV.
  - `docs/index.html`: `<script type="module" src="app.js?v=...">` synced with `styles.css?v=...`, zero external CDN scripts, modular ES files under `docs/js/`.
- Public DOM controls (`docs/index.html`) accessed via stable IDs, semantic ARIA/title/placeholder/text locators, `data-lm-id`, `.tour-section .mono-tag`, `#pins-layer .lm-pin`, and `document.body.dataset.mode`.
- Public URL query parameters: `?mode=`, `?zoom=`, `?u=`, `?v=`, `?pins=`, `?cinema=`, `?follow=`, `?t=`, `?landmark=`.
- Read-only telemetry accessor: `window.__dioramaDebug` (read via `typeof window.__dioramaDebug === 'function' ? window.__dioramaDebug() : window.__dioramaDebug`), exposing all 13 Contract #5 keys plus `livingCounts`, `depthStats`, `waterMaskReady`, `followTarget`, and `simStats`.

---

## 4. Tier 4 — Real-World Application Scenarios (8 End-User Journeys + 5 Hardening Tests)

1. **Journey 1 — First-Time Visitor Full Tour (`T4.01`)**: Cold desktop boot (`1280×800`, DPR=2) → lighting modes → Cinema Mode (`H`/`Esc`) → Postcard PNG export.
2. **Journey 2 — Lindt HoC & Schooren Seebad Deep-Zoom Inspection (`T4.02`)**: Lindt HoC `2×` tiles → Plate 01 modal → Schooren Seebad live water/SUP motion.
3. **Journey 3 — Commuter Transit Showcase (`T4.03`)**: Bahnhof Kilchberg → Follow Train, Boat, Bus with high-zoom tile streaming.
4. **Journey 4 — Kilchberg Resident Address Lookup (`T4.04`)**: Instant address search → inspector update → Share Permalink → fresh incognito tab restore.
5. **Journey 5 — Spatial Soundscape Walk (`T4.05`)**: Trusted audio unlock → 9/9 MP3 decode → shore vs ridge waves → Night crickets & bells → mixer & mute.
6. **Journey 6 — Mobile Portrait Explorer (`T4.06`)**: Mobile `390×844` DPR=2 zero clipping → lighting presets → landmark selection.
7. **Journey 7 — Living Kilchberg Commuter & Village Life (`T4.07`)**: `simStats` live activity → Follow Train/Bus → Pier/Lindt/Seebad → entity trip inspection.
8. **Tier 5 Hardening (`T4.08`–`T4.12`)**: rAF loop stability on `Live` toggles, extreme `?t=` bounds, ZVV bus cold-load advancement, Follow Train selection & clean vehicle titles, mobile `.topbar` zero horizontal overflow.
9. **Journey 8 — Kilchberg Heritage & New Landmarks Tour (`T4.13`)**: Cold desktop boot (`1280×800`, DPR=2) → tour fixed `cf_meyer_haus` and all 6 new Tier-1 landmarks (`gemeindehaus_alte_landstr`, `stockengut_farm`, `hallenbad_hochweid`, `broelberggut_estate`, `villa_spinnergut_tc`, `morfanlage_promenade`) → verify non-blank canvas & HTTP 200 tile streaming → open new detail plate (`08_cf_meyer_haus.webp` or `09_gemeindehaus_alte_landstrasse.webp`) and click `#btn-modal-fly` ("Fly Here") → verify modal closes, `activeLandmark` transitions, zero desktop clipping, and zero JS/console/HTTP errors.

---

## 5. Coverage Thresholds & Performance Targets

| Metric | Required Threshold |
|---|---|
| Tier 1 feature coverage | `>= 5` tests per feature area (`FA1`: 10, `FA2`: 11, `FA3`: 14, `FA4`: 5; total **40**) |
| Tier 2 boundary & corner coverage | `>= 5` tests per feature area (`FA1`: 10, `FA2`: 8, `FA3`: 10, `FA4`: 5; total **33**) |
| Tier 3 cross-feature pairwise coverage | **11** pairwise combination suites (`T3.01`–`T3.11`) |
| Tier 4 real-world journeys & hardening | **13** suites (`T4.01`–`T4.13`: 8 end-user journeys + 5 hardening tests) |
| Total E2E test suite size | **97 tests** (88 preserved v8.0 baseline + 9 new v9.0 tests; 41 Python + 56 Node CDP) |
| Per-suite timeout budget | `120 s` per suite (`tests/run_e2e.py --timeout 120`) |
| Orphan process tolerance | `0` live non-zombie Chromium/Node/HTTP processes after run completion |
| Harness error tolerance | `0` syntax, import, timeout, or uncaught harness exceptions on both pre-v9.0 and v9.0 |
