# Project: Kilchberg Living-World Simulation Overhaul & Train/Bus Depth-Occlusion Fix (v8.0)

## Architecture
Kilchberg is a static GitHub Pages 2:1 isometric pixel-art diorama (`docs/`, 12,331×5,444 master @ 0.25 m/px) backed by a Python swisstopo LiDAR/MVT/DOP10 rendering and data-export pipeline (`pipeline/`), verified by `pipeline.verify_quality` (11 checks) and a 4-tier opaque-box E2E suite (`tests/run_e2e.py`, 70+ tests via Python `unittest` + Node raw CDP).

- **Pipeline (`pipeline/`)**:
  - `pixel_shader.py` + `render_all.py`: Generates 3 lighting presets (`day`, `sunset`, `night`), 234 lossless WebP tiles, 6 detail plates, and `docs/assets/kilchberg_depth.png` (2× downsampled 16-bit depth + binary occluder mask).
  - `export_animations.py`: Samples exact 0.5 m swisstopo DEM + bridge elevations (`scene_kilchberg_05m.npz`, `buildings_kilchberg_meta.json`, `mvt/*.pbf`) to export `docs/data/kilchberg_animations.json` (backward-compatible `trains`, `roads`, `ships`, `ambient` + new compact `network` multimodal graph).
- **Frontend (`docs/`)**:
  - Native ES modules (zero build step, GitHub Pages & `cdp_harness.mjs` compatible):
    - `docs/index.html`: `<script type="module" src="app.js?v=8.0">` synced with `styles.css?v=8.0`.
    - `docs/app.js`: Thin orchestrator (DOM, camera/zoom/pan/tiles, minimap/loupe/modal/search/permalink/postcard, animation loop, `window.__dioramaDebug`).
    - `docs/js/sim/rng.js`: Deterministic seeded PRNG (`mulberry32` + coordinate/entity hash) guaranteeing pixel-identical `?t=` snapshots (`meanAbsDiff < 1.0`).
    - `docs/js/sim/schedule.js`: Unified SBB S8/S24, ZVV 161/165, ZSG MS Helvetia schedules, diurnal activity curves (`day`/`sunset`/`night`), and unified SW→NE wind vector.
    - `docs/js/sim/traffic.js`: Fixed-timestep (`1/20s`, deterministic warmup for `?t=`) 1D IDM-lite car-following, bus-dwell queueing, brake lights/blinkers/headlights, crosswalk yielding, residential feeder/delivery trips, and cyclist pace groups.
    - `docs/js/sim/pedestrians.js`: Fixed-timestep deterministic O–D pedestrian/commuter engine (Bahnhof Kilchberg pulse, ZVV bus-stop boarding/alighting, Bendlikon ZSG pier boarding/alighting, Lindt HoC visitors with bags, Swiss zebra crosswalks, dog walkers, strollers, couples, joggers, schoolkids, fountain/bench social pauses).
    - `docs/js/render/depth.js`: Height-aware `drawDepthMasked()` (`depthSlopeVert = depthSlopeGround / 3.0`), `evalWalkerD16()`, depth-map loader & `waterMask`.
    - `docs/js/render/vehicles.js`: Procedural 3D isometric vehicle/train/bus/cyclist/boat renderers with dynamic brake lights, turn/hazard blinkers, headlight cones, and wakes.
    - `docs/js/render/vignettes.js`: Landmarks, sports fields, lake micro-life (slow SUPs + ripples, rowboat/skiff, swans/ducks), dusk/night living windows, wind-coherent flags/smoke/clouds, and synced church bell ripples.
    - `docs/js/audio.js`: 9-channel shore-strict spatial soundscape engine coupled to simulation state and church bell phase.

## Code Layout & Write Ownership
| Path | Owner Milestone | Notes |
|------|----------------|-------|
| `pipeline/pixel_shader.py`, `pipeline/render_all.py`, `docs/assets/kilchberg_depth.png` | M1 | Depth-map occluder fix (`obj_buf` export, exclude `M_RAIL` + catenary `310000..310199` + streetlamp poles `238000..238999`, `occ_cnt >= 2`) + fast regeneration |
| `pipeline/export_animations.py`, `docs/data/kilchberg_animations.json` | M2 | Backward-compatible multimodal `network` export (<600 KB total) on exact 0.5 m DEM |
| `docs/index.html`, `docs/styles.css`, `docs/app.js`, `docs/js/sim/{rng,schedule,traffic}.js`, `docs/js/render/{depth,vehicles}.js` | M3 | ES module split (`?v=8.0`), height-aware `drawDepthMasked` preserved in `depth.js`, deterministic IDM traffic & lighting |
| `docs/js/sim/pedestrians.js`, `docs/js/render/vignettes.js`, `docs/js/audio.js`, `docs/app.js` (wiring) | M4 | Purposeful O–D pedestrians, transit transfers, living micro-life, synced church bells, state-coupled shore-strict audio |
| `tests/*`, `TEST_INFRA.md`, `TEST_READY.md` | E2E Testing Track | Opaque-box 4-tier E2E suite (preserves all 70 existing tests + adds v8.0 tests) |

## Feature Inventory
Every Survey feature is assigned to a milestone (none unassigned):

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Depth-map occluder fix | Export `obj_buf` in `pixel_shader.py`, remove `M_RAIL`, exclude catenary `310000..310199` & streetlamp poles `238000..238999`, require `occ_cnt >= 2`, regenerate `kilchberg_depth.png` (<10 min) | M1 | ORIGINAL_REQUEST, survey_1 |
| 2 | Runtime vertical roof extrusion depth test | Replace `upClamp = 0` in `drawDepthMasked()` with `depthSlopeVert = depthSlopeGround / 3.0` capped to excess roof height (`7.5` trains, `6.5` buses, `3.0` cars, `2.0` walkers, `6.0` ships), mirrored in 3-way pre-check | M1 (initial) → M3 (`depth.js`) | ORIGINAL_REQUEST, survey_1 |
| 3 | Multimodal road & feeder-street graph | Export junctions (Bendlikon, Mönchhof, Bahnhofplatz, Schooren/Lindt, Dorfplatz/Kirche) & feeder streets (`Bahnhofstrasse`, `Stockenstrasse`, `Schoorenstrasse`, `Paradiesstrasse`, `Weinbergstrasse`, `Breitloostrasse`, `Kirchenweg`, `Badweg`) clipped to `diorama_mask` on 0.5 m DEM | M2 | survey_2 |
| 4 | Swiss zebra crosswalks | Export 6–8 authentic zebra-crossing anchors mapped onto exact road `frac` positions (Bendlikon, Lindt, Bahnhof, Gemeindehaus, Schulhaus Dorfstrasse, Seebad) | M2 | survey_2, survey_3 |
| 5 | Pedestrian footpath & promenade graph | Export DEM-sampled `footway`/`path` network connecting Bahnhof, Bendlikon Pier, Seestrasse Promenade, Lindt Plaza, Seebad, schools, Reformierte Kirche, Sanatorium Park | M2 | survey_2 |
| 6 | Typed POI, residential & sports anchors | Export typed POIs, neighbourhood residential clusters, and additional sports fields from `buildings_kilchberg_meta.json` (`sports_fields[16]`) while keeping `kilchberg_animations.json` <600 KB and 100% backward-compatible | M2 | survey_2 |
| 7 | Native ES module architecture | Split `docs/app.js` into native ES modules under `docs/js/` with `<script type="module" src="app.js?v=8.0">` synced with `styles.css?v=8.0`, preserving `window.__dioramaDebug` (all 13 Contract #5 keys) | M3 | survey_3 |
| 8 | Deterministic fixed-timestep kernel | Seeded PRNG (`rng.js`) + `1/20s` fixed-dt stepper with fast-forward warmup for `?t=` so `?t=10` is pixel-identical (`meanAbsDiff < 1.0`) and `?t=10` vs `?t=15` shows clear motion | M3 | survey_2, survey_3 |
| 9 | 1D IDM-lite car-following & bus-dwell queueing | Realistic density (~65–80 cars, 10 buses); safe headway; smooth braking behind dwelling ZVV buses (zero clipping!) and slower vehicles; junction yielding & local feeder-street/delivery trips | M3 | ORIGINAL_REQUEST, survey_2, survey_3 |
| 10 | Dynamic vehicle lighting & signals | Red brake lights on braking/stopped vehicles, amber turn/hazard blinkers on buses pulling into/out of stops & delivery vans, headlight cones (Alpenglow/Night) dimming when queued | M3 | survey_3 |
| 11 | Crosswalk vehicle yielding | Approaching cars smoothly brake (showing brake lights) to yield when pedestrians occupy/approach zebra crossings, then resume | M3 | survey_2, survey_3 |
| 12 | Authentic cyclist pace groups | 1–2 rider pace groups, slower uphill on Dorfstrasse viaduct, faster downhill, yielding cleanly at bus stops/crosswalks without clipping | M3 | survey_3 |
| 13 | Transit-coupled Bahnhof Kilchberg pulse | Pre-arrival gathering via footbridge & Bahnhofstrasse, visible boarding into open S8/S24 doors, alighting commuter dispersal onto footbridge/Dorfstrasse/Bendlikon | M4 | ORIGINAL_REQUEST, survey_2, survey_3 |
| 14 | ZVV Bus-stop boarding & alighting lifecycle | Sidewalk walkers peel off to queue at named Line 161/165 stops, board during dwell, and alighting riders step out and walk toward nearby landmarks/homes | M4 | ORIGINAL_REQUEST, survey_2, survey_3 |
| 15 | Bendlikon ZSG Pier passenger flow | Passengers walk down Badweg to queue, board & alight across gangplank during MS Helvetia dwell, and alighting visitors walk inland onto Badweg/Seestrasse (no teleporting) | M4 | survey_2, survey_3 |
| 16 | Lindt HoC visitors & delivery vans | Visitors walk from bus stop/Seestrasse into Lindt plaza, pause to admire/photo, exit carrying golden-red Lindt bags; occasional Lindt/Post vans pause at curb with hazard flashers | M4 | survey_2, survey_3 |
| 17 | Purposeful human micro-archetypes | Dog walkers (tiny animated dog on leash), parents with strollers, walking couples, lakefront joggers (day & sunset), schoolkids near schools, Seebad bathers, brief 3–5s social pauses at fountains/benches/harbor railing | M4 | ORIGINAL_REQUEST, survey_2, survey_3 |
| 18 | Diurnal mode-aware activity curve | Distinct realistic activity rhythms across Midday (`day`), Alpenglow (`sunset`), and Night (`night`) | M4 | survey_2, survey_3 |
| 19 | Lake Zurich & village micro-life | Slow SUPs (~1.6 m/s) with paddle-stroke ripples, slow lakeside rowboat/skiff near Bendlikon/Sulzergut, swan/duck wakes, additional active sports fields, subtle dusk/night living windows, unified SW→NE wind vector (flags, steam, smoke, sails, clouds) | M4 | ORIGINAL_REQUEST, survey_2, survey_3 |
| 20 | Church bell audio/visual sync & state-coupled spatial audio | Fix 12 s church bell visual/audio phase offset; extract `docs/js/audio.js`; modulate traffic/bus/train/boat subtly from sim state while preserving all 9 MP3s, shore-strict `lake_waves`, and `Live: Off` audio updates | M4 | survey_2, survey_3 |
| 21 | Subtle entity trip inspection | Clicking a moving vehicle/pedestrian or cycling Follow shows a clean trip/route readout (e.g., "Commuter → Bahnhof Kilchberg") without cluttering UI or breaking layout bounds | M4 | survey_2 |
| 22 | Extended 4-tier E2E test suite | Preserve 70/70 existing tests and add opaque-box tests for roof occlusion fix, `network` DEM grounding, car-following/bus non-clipping, crosswalks, transit transfers, micro-life, determinism, and audio sync | E2E Track | survey_1, survey_3 |
| 23 | Full E2E pass (Tiers 1–4) & Tier 5 adversarial hardening | Pass 100% of E2E suite + 11/11 `pipeline.verify_quality` + visual screenshot verification + Tier 5 white-box adversarial hardening | M5 | Project Pattern |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Depth Occlusion & Opacity Fix | Fix `pixel_shader.py` `occ_m`/`obj_buf`/`occ_cnt>=2`, regenerate `kilchberg_depth.png`, fix `drawDepthMasked()` vertical extrusion in `docs/app.js` | none | DONE (`0.00%/1.30%` train hits, `0.00-0.81%` road hits, 5/5 PASS, Auditor CLEAN) |
| M2 | Kilchberg Multimodal Graph Export | Extend `pipeline/export_animations.py` with compact DEM-sampled `network` (junctions, feeder streets, crosswalks, footpaths, POIs, extra sports fields) | none | DONE (`330.24 KiB`, 0 water/DEM errors, 1 connected footpath graph, 5/5 PASS, Auditor CLEAN) |
| M3 | Modular Architecture & Deterministic Traffic Engine | Refactor `docs/app.js` into ES modules (`?v=8.0`), build `rng.js`, `schedule.js`, `traffic.js` (1D IDM, bus-dwell queueing, brake/turn/headlights, crosswalk yielding, cyclists), `depth.js`, `vehicles.js` | M1, M2 | DONE (83/83 E2E PASS, 0 clips, 10/10 buses cycling, 0.27ms/step, 5/5 PASS, Auditor CLEAN) |
| M4 | Purposeful Pedestrians, Transit Transfers, Micro-Life & Audio | Build `pedestrians.js` (Bahnhof/bus/pier/Lindt/crosswalks/archetypes), `vignettes.js` (sports, rowboat, living windows, wind, synced bells), `audio.js`, subtle trip inspection | M3 | DONE (83/83 E2E PASS, 0 teleports, 0 water hits, exact bell sync, 5/5 PASS, Auditor CLEAN) |
| E2E | E2E Testing Track | Extend `tests/` (Tiers 1–4) for all v8.0 features while keeping 70/70 existing tests intact; publish `TEST_INFRA.md` & `TEST_READY.md` | none (parallel) | DONE (83 tests, 70/70 baseline + 4 M1/M2 PASS, TEST_READY.md published, 5/5 PASS, Auditor CLEAN) |
| M5 | Final Milestone (Tiers 1–4 + Tier 5 Hardening) | Phase 1: 100% E2E pass + `verify_quality` 11/11 + visual check; Phase 2: Tier 5 white-box Challenger hardening | M4, E2E | DONE (88/88 E2E PASS, 11/11 verify_quality, 7 Tier-5 bugs fixed + 5 regression tests, Whole-Project Auditor CLEAN, 5/5 PASS) |

## Interface Contracts

### 1. Depth Map (`docs/assets/kilchberg_depth.png`) ↔ `docs/js/render/depth.js`
- Dimensions: `6165 × 2722` (2× downsampled from `12331 × 5444`).
- Encoding: `R = v16 >> 8`, `G = v16 & 0xFF` (`DEPTH_MIN = -2400.0`, `DEPTH_MAX = 2400.0`), `B = 255` iff `has_occ` (`occ_cnt >= 2`, excluding `M_RAIL`, catenary `310000..310199`, and streetlamp poles `238000..238999`), else `B = 0, R = G = 255`.
- Invariants: `0.12 <= occ_frac <= 0.35`, `n_occ > 100,000`, zero exterior sky occluders, open-air roof small hits (`<=45 u16`) `< 2%` on S8/IC trains and `< 1%` on Seestrasse/Viaduct/Alte Landstrasse.
- `drawDepthMasked(ctx, sprite, wx, wy, vehD16, ..., extraVertPx)`:
  - `depthSlopeVert = depthSlopeGround / 3.0`
  - `evalRowD16(dyW) = dyW >= 0 ? vehD16 - dyW * depthSlopeGround : vehD16 - Math.min(-dyW, extraVertPx) * depthSlopeVert`
  - `extraVertPx`: trains `7.5`, buses `6.5`, ships `6.0`, cars `3.0`, cyclists/walkers `2.0`.
  - 3-way pre-check mirrors `evalRowD16` identically (`rowMinD16 = Math.min(dTop, dBot)`, `rowMaxD16 = (rawTop <= 0 && rawBot >= 0) ? vehD16 : Math.max(dTop, dBot)`).

### 2. Multimodal Network (`docs/data/kilchberg_animations.json`)
- Existing top-level keys (`trains[2]`, `roads[8]`, `ships[5]`, `ambient`) MUST remain 100% schema-compatible with `T1.FA2.04–07` and `T2.FA2.01–06`.
- New optional top-level key `network` (total JSON file size `< 650 KB`):
  - `network.crosswalks`: array of `{ id, name, road_id, frac, u, v, d16, nx, ny }` (6–8 Swiss zebra crossings).
  - `network.junctions`: array of `{ id, name, u, v, d16, links: [{ road_id, frac }] }`.
  - `network.feeders`: array of `{ id, name, kind, length_m, pts: [[u, v, occ, d16], ...], connects_road, connects_frac, poi_id? }`.
  - `network.footpaths`: array of `{ id, name, kind, length_m, pts: [[u, v, occ, d16], ...], from_poi, to_poi }`.
  - `network.pois`: array of `{ id, name, kind, u, v, d16, road_id?, road_frac? }` (Bahnhof, bus stops, Bendlikon Pier, Lindt HoC, Seebad, schools, Kirche, Sanatorium, parks, fountains).
  - `network.extra_sports`: array of `{ id, kind, u, v, d16, w_m, h_m, angle }` (selected from `sports_fields[16]`).
- Every point in `network` MUST satisfy `0 <= u <= 1`, `0 <= v <= 1`, `d16` non-spiking, and be inside `diorama_mask` and outside `lake_mask`.

### 3. Simulation & ES Modules (`docs/js/*`)
- `docs/index.html`: `<script type="module" src="app.js?v=8.0"></script>` and `<link rel="stylesheet" href="styles.css?v=8.0">`. Zero external CDN `<script>` tags.
- Determinism Contract: `sim.updateToTime(tSec, mode)` MUST be a pure deterministic function of `(tSec, mode)` — when `?t=X` is passed, fast-forward deterministically from `max(0, tSec - 60)` (or `0`) at `dt = 0.05s` using seeded PRNG so `?t=10` produces `meanAbsDiff < 1.0` across repeated frames and clear delta vs `?t=15`.
- `window.__dioramaDebug` Contract #5: MUST preserve all 13 required keys (`mode, scale, u, v, dpr, animTime, fps, audioEnabled, audioState, audioGains, activeLandmark, selectedBuilding, searchResultCount`) plus `livingCounts`, `depthStats`, and new `simStats` (`{ vehicles, brakingCount, yieldingCount, pedestrians, boardingCount, activeTrips, bellPhase }`).

### 4. Global Kilchberg Guardrails (Zero Tolerance)
- Zero occurrences of `paraglider`, `hot-air`, `balloon`, or `glider` (case-insensitive) anywhere in `docs/`.
- SUP paddlers stay slow (~1.5–1.8 m/s).
- All vehicles, cyclists, and pedestrians stay on exact 0.5 m DEM roads/footpaths (no water intrusion, no mid-town vanishing).
- Preserve authentic 25 cm DOP10 roofs (esp. Lindt Home of Chocolate `#1443`), spotless Lake Zurich shoreline, smooth Bendlikon/Dorfstrasse viaduct, flat SBB rail bridges, `<= 256` SVGA tile colors, and shore-strict spatial audio (`lake_waves` shore >2.5× overview, >3× inland, updating even when `Live: Off`).
- Never output `localhost` URLs. Keep long render commands under ~10 min. Keep `.venv`, `tests/run_e2e.py`, and `pipeline.verify_quality` passing.
