# Test Infrastructure — Kilchberg (ZH) Isometric Pixel-Art Diorama (v7.0 Overhaul)

## 1. Test Philosophy

This E2E testing track implements an **opaque-box, requirement-driven 4-tier automated test suite** derived strictly from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` & `§ Interface Contracts` — **never** from internal Python pipeline functions or private JavaScript variables.

Core principles:
1. **Zero-Install Native Runtime**: Runs directly on the provisioned VM toolchain without `pip install` or `npm install`:
   - **Python 3.11** (`unittest`, `numpy`, `Pillow`, `ffprobe`) for static asset, manifest, tile pyramid, depth-map, JSON schema, audio integrity, pixel-quality, and geometric constraint verification.
   - **Node.js 24** (built-in global `WebSocket` + `fetch` native Chrome DevTools Protocol driver) + **`/usr/bin/chromium`** (`--headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage`) against an ephemeral local `node:http` server serving `docs/` for live interactive web app, layout, Retina DPR, animation, spatial audio, and end-user journey verification.
2. **Real User Gestures & Authentic Browser Contracts**:
   - Chromium is launched **without** `--autoplay-policy=no-user-gesture-required`; WebAudio unlocking is exercised through real trusted CDP `Input.dispatchMouseEvent` clicks on `#btn-toggle-sound`, validating genuine production autoplay compliance.
   - External CDN font URLs (`fonts.googleapis.com` / `fonts.gstatic.com`) are blocked via CDP `Network.setBlockedURLs` to verify offline/self-contained resilience (`PROJECT.md § Interface Contracts #5`), while local origin (`127.0.0.1`) enforces zero HTTP `>= 400` application-asset failures, zero `Runtime.exceptionThrown`, and zero `console.error`.
3. **Anti-Tautology & Honest Pre-Overhaul Failure Semantics**:
   - Every test asserts real user-facing behavior, pixel metrics, geometric invariants, or public contract fields (`document.body.dataset.mode`, `window.__dioramaDebug`).
   - Against pre-overhaul `v6.2` code, tests covering unimplemented `v7.0` requirements (e.g., Bendlikon pier `Badweg 1.1` alignment, floating sky cars/sports props removal, per-preset CLUTs, night streetlamp pools, road kink removal, flex layout clipping fix, Retina DPR scaling, address search, collapsible sidebar, `window.__dioramaDebug`, spatial audio invariants) **must fail cleanly with crisp assertion diagnostics** — never silently skip or pass vacuously.
   - Harness, syntax, import, timeout, or process-leak errors are strictly forbidden in every tier.
4. **Determinism, Speed & Process Hygiene**:
   - Deterministic URL timestamps (`?t=10`, `?t=15`) enable reproducible frame-motion and visual assertions.
   - One shared headless Chromium browser per Node runner with isolated incognito `Target.createBrowserContext` tabs keeps every tier `< 30 s` and `--tier all` `< 90 s`.
   - Every local HTTP server, Chromium child process (sharing Node's process group so `os.killpg` terminates Node + Chromium atomically, with `forceClose()` signal teardown & `Browser.close` → `SIGTERM` → `SIGKILL` fallback), and temporary profile directory is torn down in `finally` blocks + signal handlers, leaving zero live orphan processes.

---

## 2. Feature Inventory Mapped to Requirements & Test Tiers

Every requirement from `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` (F3–F26, Guardrails #1–#7, Interface Contracts #2–#5) is grouped into **4 Requirement Feature Areas** (`FA1`–`FA4`), each covered by `>= 5` tests in Tier 1 and `>= 5` boundary/corner tests in Tier 2, plus pairwise combinations in Tier 3 and end-user journeys in Tier 4.

| Feature Area | `PROJECT.md` / `ORIGINAL_REQUEST.md` Mapping | Tier 1 (Feature Coverage) | Tier 2 (Boundary & Corner Cases) | Tier 3 (Cross-Feature) | Tier 4 (Journeys) |
|---|---|---|---|---|---|
| **FA1: Static Visual Assets, Tile Pyramid, Depth Map & Detail Plates** | F4–F14; Guardrails #4, #5; Contract #2 (`12331×5444`, `78×3` lossless tiles, `6165×2722` overviews & depth PNG, 6 `0.22 m/px` plates, 256-color SVGA CLUTs, zero floating artifacts, spotless shore, sunset gold, night pools, Lindt 25 cm roof) | `T1.FA1.01`–`T1.FA1.07` (7 tests) | `T2.FA1.01`–`T2.FA1.09` (9 tests) | `T3.01`, `T3.02`, `T3.05` | Journey 1, Journey 2 |
| **FA2: Geospatial Metadata, Landmarks, Living-World Routes & Guardrails** | F3, F15–F17; Guardrails #1, #2, #3, #6; Contracts #3–#4 (`kilchberg_interactive.json`, `kilchberg_animations.json`, 10 landmarks + Bendlikon pier `Badweg 1.1`, `>=1850` addressed buildings, SBB trains, 8 edge-to-edge roads, bus stops, ZSG steamer, zero paragliders/balloons) | `T1.FA2.01`–`T1.FA2.08` (8 tests) | `T2.FA2.01`–`T2.FA2.06` (6 tests) | `T3.02`, `T3.03` | Journey 2, Journey 3, Journey 4 |
| **FA3: Interactive Web App, Lighting, Camera, Cartographic HUD & Sharing** | F18–F25; Contract #5 (zero JS/404 errors, lighting presets + `body[data-mode]`, zoom/tiles, landmarks, building click/highlight, address search, detail-plate modal + "Fly Here", cinema mode, collapsible sidebar, compass/scale bar, share permalink, postcard export, `window.__dioramaDebug`, Desktop `1280×800` DPR=2 & Mobile `390×844` layout) | `T1.FA3.01`–`T1.FA3.12` (12 tests) | `T2.FA3.01`–`T2.FA3.06` (6 tests) | `T3.01`, `T3.02`, `T3.03`, `T3.05`, `T3.06` | Journey 1, Journey 2, Journey 3, Journey 4, Journey 6 |
| **FA4: Spatial Audio Soundscape & Layer Mixer** | F26; Guardrail #7; Contract #5 (9 valid MP3 field recordings via `ffprobe`, trusted-gesture AudioContext unlock & 9/9 decode, shore-strict wave attenuation at overview vs near-shore loudness, Day birds vs Night crickets, paused animations still updating spatial audio, mute suspending AudioContext, bell audio/visual sync, layer mixer popover) | `T1.FA4.01`–`T1.FA4.05` (5 tests) | `T2.FA4.01`–`T2.FA4.05` (5 tests) | `T3.04` | Journey 5 |

---

## 3. Test Architecture

```text
tests/
├── run_e2e.py                    # Unified CLI runner (--tier 1|2|3|4|all, --verbose, --json-report, --timeout)
├── lib/
│   ├── __init__.py
│   ├── report.py                 # Unified TestCaseResult / TierResult dataclasses, PASS/FAIL table & JSON summary
│   ├── assets_helper.py          # Cached loaders for docs/data/*.json, WebPs, depth PNG, manifests, ffprobe & pure-numpy RLE connected components
│   └── cdp_harness.mjs           # Zero-dep Node 24 CDP driver, local docs/ HTTP server, shared Chromium + isolated incognito contexts, clean teardown
├── tier1_assets_data.py          # Tier 1 (Python): FA1, FA2, FA4 static asset, schema, audio & guardrail tests
├── tier1_browser_features.mjs    # Tier 1 (Node CDP): FA3 & FA4 live browser feature coverage tests
├── tier2_quality_bounds.py       # Tier 2 (Python): FA1 & FA2 pixel-quality, CLUT, floating-artifact, shoreline, plaster, night-pool, roof & kink bounds
├── tier2_browser_bounds.mjs      # Tier 2 (Node CDP): FA3 & FA4 viewport overflow/DPR, extreme zoom, empty search, malformed URL, audio boundary invariants
├── tier3_combinations.mjs        # Tier 3 (Node CDP): 6 pairwise cross-feature combination suites
└── tier4_journeys.mjs            # Tier 4 (Node CDP): 6 real-world end-user application journeys
```

### Orchestration & Reporting Protocol
- Command: `python3 tests/run_e2e.py --tier <1|2|3|4|all>` (also supports comma-separated lists like `--tier 1,2`, `--verbose`, `--json-report <path>`, `--timeout <sec>`).
- Python test modules run via stdlib `unittest` collected by `tests/lib/report.py`.
- Node CDP test modules receive `--result-json <tmpfile>` (allocated inside a `TemporaryDirectory` owned by `run_e2e.py`) so Chromium wrapper stderr noise never corrupts structured per-test reporting.
- **Exit Code Contract**:
  - `0` iff all requested tiers complete cleanly, total tests executed `> 0`, `failed == 0`, and `errors == 0`.
  - `1` on any assertion failure, runtime error, or missing result file.
  - `124` on tier timeout (after terminating the subprocess group via `os.killpg`).

### Opaque-Box Public Contract Dependencies
- Static files under `docs/assets/` and `docs/data/`.
- Public DOM controls (`docs/index.html`) accessed via stable IDs, semantic ARIA/title/placeholder/text locators, and `document.body.dataset.mode`.
- Public URL query parameters: `?mode=`, `?zoom=`, `?u=`, `?v=`, `?pins=`, `?cinema=`, `?follow=`, `?t=`.
- Read-only telemetry accessor (`PROJECT.md § Interface Contracts #5`): `window.__dioramaDebug` (read via `typeof window.__dioramaDebug === 'function' ? window.__dioramaDebug() : window.__dioramaDebug`), exposing `{ mode, scale, u, v, dpr, animTime, fps, audioEnabled, audioState, audioGains, activeLandmark, selectedBuilding, searchResultCount }`, where `audioGains` maps the spatial audio track keys (`lake_waves`, `birds`, `crickets`, `traffic`, `town_traffic`, `train`, `bells`, plus optional `boat`, `bus`) to non-negative finite numbers (either normalized levels or raw `GainNode.gain.value`).

---

## 4. Tier 4 — Real-World Application Scenarios (6 End-User Journeys)

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

---

## 5. Coverage Thresholds & Performance Targets

| Metric | Required Threshold |
|---|---|
| Tier 1 feature coverage | `>= 5` tests per feature area (`FA1`: 7, `FA2`: 8, `FA3`: 12, `FA4`: 5; total `>= 32`) |
| Tier 2 boundary & corner coverage | `>= 5` tests per feature area (`FA1`: 9, `FA2`: 6, `FA3`: 6, `FA4`: 5; total `>= 26`) |
| Tier 3 cross-feature pairwise coverage | `>= 6` pairwise combination suites covering all 6 interaction pairs |
| Tier 4 real-world journeys | `>= 6` end-to-end user journeys (`T4.01`–`T4.06`) |
| Per-tier runtime budget | `< 30 s` per tier |
| Full `--tier all` runtime budget | `< 90 s` total wall-clock time |
| Orphan process tolerance | `0` live non-zombie Chromium/Node/HTTP processes after run completion |
| Harness error tolerance | `0` syntax, import, timeout, or uncaught harness exceptions on both `v6.2` and `v7.0` |
