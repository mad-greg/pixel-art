# Test Infrastructure — Kilchberg (ZH) Isometric Pixel-Art Diorama (v11 Landmark Photo-Realism Pass)

## 1. Test Philosophy

This E2E testing track implements an **opaque-box, requirement-driven 4-tier automated test suite** derived strictly from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` & `§ Interface Contracts` — **never** from internal Python pipeline functions or private JavaScript variables.

Core principles:
1. **Zero-Install Native Runtime**: Runs directly on the provisioned VM toolchain without `pip install` or `npm install`:
   - **Python 3.11** (`unittest`, `numpy`, `Pillow`, `ffprobe`, `concurrent.futures.ThreadPoolExecutor`) for static asset, manifest, 2-level tile pyramid (`z1` + `L2`), depth-map, detail-plate, JSON schema, audio integrity, pixel-quality, sharpness/anti-upscale, lettering orientation/legibility, footprint budget, and geometric constraint verification.
   - **Node.js 24** (built-in global `WebSocket` + `fetch` native Chrome DevTools Protocol driver) + **`/usr/bin/chromium`** (`--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage`) against an ephemeral local `node:http` server serving `docs/` (including native ES modules under `docs/js/**/*.js` with `?v=` query-string stripping) for live interactive web app, layout, Retina DPR, overview pin decluttering, tile-streaming bounds, 2× sprite physical scale & roof opacity, inspector fidelity/scale-bar accuracy, deep-link/keyboard navigation, animation, spatial audio, and end-user journey verification.
2. **Real User Gestures & Authentic Browser Contracts**:
   - Chromium is launched **without** `--autoplay-policy=no-user-gesture-required`; WebAudio unlocking is exercised through real trusted CDP `Input.dispatchMouseEvent` clicks on `#btn-toggle-sound`, validating genuine production autoplay compliance.
   - External CDN font URLs (`fonts.googleapis.com` / `fonts.gstatic.com`) are blocked via CDP `Network.setBlockedURLs` to verify offline/self-contained resilience, while local origin (`127.0.0.1`) enforces zero HTTP `>= 400` application-asset or ES module failures, zero `Runtime.exceptionThrown`, and zero `console.error`.
3. **100% Baseline Preservation & v11 Photo-Realism Synchronization**:
   - All **110** existing v10 baseline tests (**51 Python** including the 7 lettering tests `T2.LET.01`–`T2.LET.07` + **59 Node CDP**) are preserved 100% intact with zero deleted, skipped, or weakened guardrail assertions (`T2.LET.02` & `T2.LET.05` synchronized with photo-verified v11 signage truth: no fictional `seebad_bathhouse` / `st_elisabeth_nave` signs, metallic gold `"LINDT & SPRÜNGLI"` instead of red).
   - **+5 new opaque-box v11 landmark photo-realism regression tests** (`T2.LM.01`–`T2.LM.05` in `tests/tier2_landmarks_v11.py`) bring the total suite to **115 tests** (**56 Python** + **59 Node CDP**).
   - Every v11-gating test checks preconditions cleanly and asserts real user-facing behavior, pixel metrics, clock/flag/signage contracts, or landmark metadata — failing cleanly with crisp `AssertionError` diagnostics against pre-v11 code/assets with zero syntax, import, `FileNotFoundError`, `KeyError`, timeout, or process-leak errors.
4. **Determinism, Speed & Process Hygiene**:
   - Deterministic URL timestamps (`?t=10`, `?t=14`, `?t=15`, `?t=22`, `?t=26`, `?t=34`, `?t=35`, `?t=46`, `?t=48`) enable reproducible frame-motion, roof-opacity, 2× sprite scale, IDM braking/yielding, deep-link, and church-bell phase assertions.
   - Parallel WebP tile decoding (`ThreadPoolExecutor(max_workers=8)`) in `T1.FA1.03` validates all L2 + `z1` pyramid tiles across 3 lighting presets in `< 5 s`.
   - One shared headless Chromium browser per Node runner with isolated incognito `Target.createBrowserContext` tabs and per-suite timeout `120 s` keeps `--tier all` clean and deterministic.
   - Every local HTTP server, Chromium child process (sharing Node's process group so `os.killpg` terminates Node + Chromium atomically), and temporary profile directory is torn down in `finally` blocks + signal handlers, leaving zero live orphan processes.

---

## 2. Feature Inventory Mapped to Requirements & Test Tiers

Every requirement from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` (#1–#21, Interface Contracts #1–#3, and Global Guardrails) is grouped into **4 Requirement Feature Areas** (`FA1`–`FA4`), covered across **115 total tests** (**56 Python** + **59 Node CDP**):

| Feature Area | `PROJECT.md` / `ORIGINAL_REQUEST.md` Mapping | Tier 1 (Feature Coverage) | Tier 2 (Boundary & Corner Cases) | Tier 3 (Cross-Feature) | Tier 4 (Journeys & Hardening) |
|---|---|---|---|---|---|
| **FA1: Static Visual Assets, 2-Level Tile Pyramid, Depth Map, ES Modules, 10 High-Res Plates, Baked Lettering & v11 Photo-Realism** | v7.0–v10 assets + v11 M2a–M4; Contract #1, #2 & #3 (`>=24000×10600`, `<=0.125 m/px`, `1024 px` lossless `VP8L` L2 + `z1` mid-res pyramid tiles, `diorama_{mode}.webp` == `kilchberg_depth.png` parity, open-air roof small hits `<2%` trains & `<1%` main roads, `<script type="module" src="app.js?v=...">` synced with `styles.css`, **10 detail plates `01..10_*.webp`** lossless `VP8L` RGB `>=3200×2200` `<=256` SVGA colors, high-frequency sharpness & anti-2×-NN-upscale check, `<300 MB` `docs/` & `<500 KB`/tile budget, spotless shore, sunset gold, night pools, Lindt 10 cm DOP10 roof, metallic-gold baked isometric lettering `T2.LET.01`–`T2.LET.07`, v11 St. Elisabeth white concrete / zero-clock, Gemeindehaus zero-clock / single forecourt flag pair, reconciled `signage.CLOCKS` & photo-verified `config.py` metadata `T2.LM.01`–`T2.LM.05`) | `T1.FA1.01`–`T1.FA1.11` (11 tests) | `T2.FA1.01`–`T2.FA1.12` (12 tests) + `T2.LET.01`–`T2.LET.07` (7 tests) + `T2.LM.01`–`T2.LM.05` (5 tests) | `T3.01`, `T3.02`, `T3.05`, `T3.09`, `T3.12` | `T4.01`, `T4.02`, `T4.07`, `T4.13` |
| **FA2: Geospatial Metadata, 16 Landmarks, Authentic `cf_meyer_haus`, `shift_y`, Vignettes & Multimodal Network** | v7.0–v9.4 data + v10 F9; Contract #1, #2 & #3 (`kilchberg_interactive.json` & `kilchberg_animations.json` parity with `manifest.json`, finite positive `shift_y`, `>=16` landmarks preserving `0..9` + 6 v9.0 IDs, `cf_meyer_haus` `<=35 m` LV95 of `E=2683714, N=1241442`, all 16 inside `island_2x` with pairwise `duv>=0.045`, `<650 KB` animations JSON, `ambient.swiss_flags == 4`, `ambient.vignettes` in `[0,1]` UV, `network` DEM/zero-water bounds, slow SUPs, zero paragliders/balloons) | `T1.FA2.01`–`T1.FA2.11` (11 tests) | `T2.FA2.01`–`T2.FA2.08` (8 tests) | `T3.02`, `T3.03`, `T3.08`, `T3.11`, `T3.12` | `T4.02`, `T4.03`, `T4.04`, `T4.07`, `T4.13` |
| **FA3: Interactive Web App, 2-Level Tile Pyramid, 2× Live Sprites, Inspector Fidelity & Living-World Simulation** | v7.0–v9.4 UI/sim + v10 F11–F12; Contract #1, #2 & #3 (zero JS/404/ES-module errors, lighting presets, zoom/tiles, `0` L2 tiles at `Fit` & bounded `<=48` L2 tiles on `1:1` zoom-in, `>=16` sidebar stops, `>=10` `#crop-gallery` plates, zoom-aware overview pin decluttering, `?landmark=<id>` deep-link & `[`/`]` cycling, 2× live sprite physical scale & zero roof perforation at `zoom=1` & `zoom=2`, `#spec-fidelity` `12.5 cm/px` & metric scale bar halving `1:1 → 2×`, `window.__dioramaDebug` telemetry, IDM/SUP/roof-opacity, Desktop `1280×800` & Mobile `390×844` zero clipping) | `T1.FA3.01`–`T1.FA3.14` (14 tests) | `T2.FA3.01`–`T2.FA3.11` (11 tests) | `T3.01`–`T3.03`, `T3.05`–`T3.09`, `T3.11`–`T3.13` | `T4.01`–`T4.04`, `T4.06`–`T4.13` |
| **FA4: Spatial Audio Soundscape, Church Bell Sync & Layer Mixer** | v7.0–v9.4 audio + v10 F11 `wScale` alignment (9 valid MP3 field recordings via `ffprobe`, trusted-gesture AudioContext unlock & 9/9 decode, shore-strict wave attenuation, Day birds vs Night crickets, paused animations audio updates, mute suspending AudioContext, `simStats.bellPhase` ↔ `audioGains.bells` sync, layer mixer popover) | `T1.FA4.01`–`T1.FA4.05` (5 tests) | `T2.FA4.01`–`T2.FA4.05` (5 tests) | `T3.04`, `T3.10` | `T4.05` |

---

## 3. Test Architecture

```text
tests/
├── run_e2e.py                    # Unified CLI runner (--tier 1|2|3|4|all, --verbose, --json-report, --timeout)
├── lib/
│   ├── __init__.py
│   ├── report.py                 # Unified TestCaseResult / TierResult dataclasses, PASS/FAIL table & JSON summary
│   ├── assets_helper.py          # Metadata-driven cached loaders (get_canvas_dims, get_overview_dims, get_master_mpp, plate_cartouche_margins, clear_caches), WebPs, depth PNG, manifests, ffprobe, RLE components, Lake Zurich 2x mask, RGB color counter & vignette UV extractor
│   └── cdp_harness.mjs           # Zero-dep Node 24 CDP driver, local docs/ HTTP server (ES modules + ?v=), shared Chromium + isolated incognito contexts, native ROI roof opacity analyzer
├── tier1_assets_data.py          # Tier 1 (Python, 24 tests): FA1 (11), FA2 (11), FA4 static (2)
├── tier1_browser_features.mjs    # Tier 1 (Node CDP, 17 tests): FA3 (14), FA4 live (3)
├── tier2_quality_bounds.py       # Tier 2 (Python, 20 tests): FA1 (12), FA2 (8)
├── tier2_lettering.py            # Tier 2 (Python, 7 tests): Baked isometric signage typography, projection, plate 01 metallic-gold angle & no-overlay guard (T2.LET.01–T2.LET.07)
├── tier2_landmarks_v11.py        # Tier 2 (Python, 5 tests): v11 landmark photo-realism regressions — St. Elisabeth white concrete/no-clock, Gemeindehaus no-clock/no-dup-flag, reconciled CLOCKS & config metadata (T2.LM.01–T2.LM.05)
├── tier2_browser_bounds.mjs      # Tier 2 (Node CDP, 16 tests): FA3 (11), FA4 (5)
├── tier3_combinations.mjs        # Tier 3 (Node CDP, 13 tests): pairwise cross-feature suites (T3.01–T3.13)
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
  - `docs/assets/tiles/{day,sunset,night}/manifest.json`: `width >= 24000`, `height >= 10600`, `mpp <= 0.125`, `tileSize == 1024`, `cols == ceil(width / tileSize)`, `rows == ceil(height / tileSize)`, plus consistent `z1` mid-res pyramid metadata (`width // 2`, `height // 2`, `mpp ≈ 0.25`, `path == "z1"`).
  - `docs/assets/tiles/{mode}/{c}_{r}.webp` & `z1/{c}_{r}.webp`: lossless `VP8L`, exact edge dims, `<= 256` SVGA colors, `< 500 KB` each, genuine fine detail (no 2× nearest-neighbor upscaling).
  - `docs/assets/01..10_*.webp`: 10 high-res `0.11 m/px` detail plates (`VP8L` RGB, `>= 3200×2200`, body `<= 256` colors, zero floating sky clusters, `std_luma >= 20`, `entropy >= 2.5`).
  - `docs/assets/kilchberg_depth.png`: matches `diorama_day.webp` dims (`~6165×2722`), `< 10 MB`, `0.12 <= occ_frac <= 0.35`, open-air roof small hits `< 2%` trains and `< 1%` main roads.
  - `docs/data/kilchberg_interactive.json` & `docs/data/kilchberg_animations.json`: agree with `manifest.json` on `canvas_width`, `canvas_height`, and `mpp`; `kilchberg_animations.json` `< 650 KB` with finite positive `shift_y`.
  - `docs/` total footprint `< 300 MB`, zero individual files `> 90 MB`.
- Public DOM controls (`docs/index.html`) accessed via stable IDs (`#spec-fidelity`, `#scale-bar-label`, `#scale-bar-line`, `#btn-zoom-1x`, `#btn-zoom-2x`, `#btn-zoom-4x`, `#btn-zoom-fit`, etc.), semantic ARIA/title/placeholder/text locators, `data-lm-id`, `.tour-section .mono-tag`, `#pins-layer .lm-pin`, and `document.body.dataset.mode`.
- Public URL query parameters: `?mode=`, `?zoom=`, `?u=`, `?v=`, `?pins=`, `?cinema=`, `?follow=`, `?t=`, `?landmark=`.
- Read-only telemetry accessor: `window.__dioramaDebug` exposing all Contract #5 keys plus `livingCounts`, `depthStats`, `waterMaskReady`, `followTarget`, and `simStats`.

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
9. **Journey 8 — Kilchberg Heritage & New Landmarks Tour (`T4.13`)**: Cold desktop boot (`1280×800`, DPR=2) → tour fixed `cf_meyer_haus` and all 6 v9.0 landmarks → verify non-blank canvas & HTTP 200 tile streaming → open new detail plate (`08`/`09`) and click `#btn-modal-fly` ("Fly Here") → verify modal closes, `activeLandmark` transitions, zero desktop clipping, and zero JS/console/HTTP errors.

---

## 5. Coverage Thresholds & Performance Targets

| Metric | Required Threshold |
|---|---|
| Tier 1 feature coverage | `>= 5` tests per feature area (`FA1`: 11, `FA2`: 11, `FA3`: 14, `FA4`: 5; total **41**) |
| Tier 2 boundary & corner coverage | `>= 5` tests per feature area (`FA1`: 12 + `LET`: 7 + `LM`: 5 = 24, `FA2`: 8, `FA3`: 11, `FA4`: 5; total **48**) |
| Tier 3 cross-feature pairwise coverage | **13** pairwise combination suites (`T3.01`–`T3.13`) |
| Tier 4 real-world journeys & hardening | **13** suites (`T4.01`–`T4.13`: 8 end-user journeys + 5 hardening tests) |
| Total E2E test suite size | **115 tests** (110 preserved v10 baseline [51 Python incl. 7 `T2.LET.*` + 59 Node CDP] + 5 new v11 landmark photo-realism tests; **56 Python + 59 Node CDP**) |
| Per-suite timeout budget | `120 s` per suite (`tests/run_e2e.py --timeout 120`) |
| Orphan process tolerance | `0` live non-zombie Chromium/Node/HTTP processes after run completion |
| Harness error tolerance | `0` syntax, import, timeout, or uncaught harness exceptions on both pre-v11 and v11 |
