# Project: Kilchberg (ZH) Isometric Pixel-Art Diorama — World-Class Overhaul (v7.0)

## Architecture
A 100% geographically accurate 90s 3D isometric pixel-art diorama of Kilchberg (ZH), Switzerland (`BFS #0135`), built from official `swisstopo` datasets (`swissALTI3D` 0.5m DEM, `swissSURFACE3D` 0.5m LiDAR, `SWISSIMAGE DOP10` 10cm orthophotos, `swissBUILDINGS3D 3.0` 1,890 LOD2 buildings / 124,155 triangles, `swissBATHY3D`, and `ch.swisstopo.base.vt` MVT vector tiles).

```
swisstopo APIs ──▶ pipeline/fetch_data.py ──▶ /tmp/kilchberg-cache/
                                                     │
                   pipeline/extract_scene.py ◀───────┘
                            │ (0.5m DEM/DSM/sem/bridge_z/boats/trees/buildings, 0.25m ortho)
              ┌─────────────┴─────────────────────────┐
              ▼                                       ▼
   pipeline/pixel_shader.py                pipeline/export_animations.py
   pipeline/render_all.py                  (unified edge-to-edge roads,
              │                             ZSG steamer, SBB rail, bus stops,
              │                             shoreline, vignettes, chimneys)
              ▼                                       ▼
   docs/assets/{diorama_*.webp,            docs/data/kilchberg_animations.json
     tiles/{day,sunset,night}/78 WebPs,
     01..06_*.webp, kilchberg_depth.png}
   docs/data/kilchberg_interactive.json
              └─────────────┬─────────────────────────┘
                            ▼
        docs/{index.html, styles.css, app.js} + docs/assets/audio/*.mp3
        (HiDPI tiled canvas, depth-masked living world, Swiss cartographic HUD,
         9-channel spatial WebAudio mixer, deployed to GitHub Pages)
```

### Non-Negotiable User Guardrails (from `ORIGINAL_REQUEST.md`)
1. **NO paragliders** (or balloons/gliders — removed as "a bit over the top").
2. **SUP paddlers move at realistic slow speed** (~1.5–1.7 m/s, strictly on open water, properly oriented with wake behind board).
3. **Exact 0.5m DEM edge-to-edge roads** for all moving vehicles, cyclists, and pedestrians (no mid-town vanishing, no off-road shortcuts, no hairpin kinks).
4. **Real 25cm satellite textures on roofs** (especially Lindt Home of Chocolate `id=1443` at `base_w=0.95`), avoiding aerial shadow glitches and false blue PV static (`pv_clean_05m` morphological filter preserved).
5. **Spotless Lake Zurich shoreline** (no tan winter reed blotches — preserve strict `harbor_obj_mask` chroma/bathy filters), keeping Seebad wooden jetties and Bendlikon pier crisp.
6. **Smooth Bendlikon/Dorfstrasse viaduct approaches** (no road bump — preserve `extract_scene.py:829–851` perpendicular-only clearance & 9.0m cubic smoothstep taper) and **strictly flat SBB railway bridges** (preserve `extract_scene.py:819–821` `z_prof = z_lin`).
7. **Spatial audio fidelity**: quiet lake waves heard ONLY near shore (strongly attenuated at overview zoom), town cars buzzing vs. A3 motorway cars passing-by, virtual tree bird chirps, synced church bells.
8. **Split renders within ~10 min command timeout**: run `day sunset --skip-crops --skip-animations`, then `night --skip-animations` (and unified `export_animations.py` separately or after cache rebuild).
9. **Git hygiene**: `.agents/` must be ignored in `.gitignore` and never committed; no source/tests/data inside `.agents/teamwork/`.

---

## Feature Inventory
Every feature identified during Step 0 Survey (Explorers 1, 2, 3) is assigned to a milestone (none unassigned).

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Environment & Geospatial Dependencies Bootstrap | Install missing `requirements.txt` packages (`scipy`, `rasterio`, `shapely`, `pyproj`, `mapbox-vector-tile`, `requests`) in a reproducible Python environment and rebuild `/tmp/kilchberg-cache/` via `fetch_data.py` + `extract_scene.py`. | M1 | survey_1, survey_2, survey_3 |
| F2 | Git Hygiene (`.agents/` Ignore) | Add `.agents/` to `.gitignore` so coordination metadata is never accidentally committed to git. | M1 | survey_3 |
| F3 | Canonical Bendlikon Pier LV95 & Surface Steps Extraction | Align `bendlikon_pier` landmark in `pipeline/config.py` to real ZSG Schiffssteg (`Badweg 1.1`, `E=2684061, N=1242076`) and preserve MVT surface `subclass=="steps"` in `extract_scene.py` without touching bridge/viaduct elevation logic. | M1 | survey_1, survey_2 |
| F4 | Fix Floating Sky Parked Cars & Cropped Sports Props + Precompute Hoist | Filter parked cars strictly against `diorama_mask` & `active_mask`, clip all 3D sports segments/panels against `crop_box_lv95` & `active_mask`, and hoist parking stall precomputation into `SceneData` (~15–25s/preset speedup). | M2 | survey_1 |
| F5 | Museum-Grade Geological & Aquarium Cutaway | Replace mechanical `sin()` zebra strata with layered Swiss Molasse/Nagelfluh geology, fix detail-plate bottom cutaway vertical notch artifacts, and add Lake Zurich aquarium glass sheen & pebble bed. | M2 | survey_1 |
| F6 | Per-Preset Curated 256-Color SVGA CLUTs (`day`, `sunset`, `night`) | Parameterize `build_90s_palette_and_lut(preset_key)` with dedicated Day, Sunset (honey-apricot gold + cool violet shadows — eliminates bubblegum-pink plaster), and Night (moonlit Prussian-blue/slate-emerald + 32-color warm lantern amber ramp) palettes. | M2 | survey_1 |
| F7 | Cozy Night & Sunset Lighting System | Deterministic 3D streetlamp poles + warm radial ground light pools along main streets/viaduct/Bahnhof/promenade, warm window-spill glow halos, architectural landmark uplighting (Ref. Kirche, Lindt atrium/chimney, St. Elisabeth, Bahnhof), darkened nocturnal pools, ~20% warm dusk windows at Sunset, and wider macro-tile `guard` padding (zero tile seams). | M2 | survey_1 |
| F8 | Multi-Scale 0.5m Cast Shadows + Building/Roof Shadowing + Contact AO | Upgrade `compute_shadow_grid` to 0.5m near-field + 1.0m far-field, allow shadows on lower roofs/walls (with self-shadow bias), and add fast vectorized `zbuf` screen-space contact AO in Stage 5. | M2 | survey_1 |
| F9 | Master-Crafted Pixel-Art Lake Zurich Water & Shoreline Reflections | Isometric wavelets, procedural shallow pebble caustics (strictly preserving reed-exclusion filters), crisp shore/pier foam curls, subtle inverted shoreline water reflections (gorgeous at Sunset/Night), and solar/lunar shimmer path. | M2 | survey_1 |
| F10 | Render Moored Boats (`scene.boats`) & 3D Timber Piers | Render already-extracted `scene.boats` (3D sailboats with masts & classic wooden motorboats strictly inside `lake_mask & diorama_mask`) and upgrade Bendlikon ZSG Pier & Seebad jetties with 3D pilings, railings, swim ladders & water contact shadows. | M2 | survey_1 |
| F11 | Pitched-Roof Aerial Shadow De-Biasing & LiDAR-Verified Rooftops | Per-facet pitched-roof illumination normalization (preserving 100% 25cm detail & Lindt HoC `base_w=0.95` & `pv_clean_05m`), glare highlight clamping, LiDAR-verified rooftop superstructures & twin terracotta chimney pots. | M2 | survey_1 |
| F12 | Swiss Vernacular Facade Craftsmanship & Special `Objektart` Styling | Window lintel shadows, stone *Gewände* surrounds, geranium window boxes, recessed apartment balconies/loggias with balustrades, striped Swiss sun awnings (*Sonnenstoren*), timber gable bargeboards, selective *Riegelhaus* framing, Bahnhofstrasse/Seestrasse shopfronts, cylindrical Lindt `Lagertank` cocoa silos, and `Treibhaus` glass greenhouses. | M2 | survey_1 |
| F13 | Bespoke Handcrafted Landmark Upgrades & Catenary Wires | Robust LV95 landmark matching + custom craft for Bahnhof Kilchberg (3D glass platform canopies, SBB signs, station clock, 1px overhead steel catenary wires connecting `catenary_portals`), C.F. Meyer-Haus, Gemeindehaus, Sanatorium Kilchberg, Seebad Kilchberg bathhouse & beach umbrellas/towels, plus cartouche polish on plates `01`–`06`. | M2 | survey_1 |
| F14 | Painterly Botanical Foliage & Micro-Landscape Storytelling | 3 deciduous tree silhouettes (incl. weeping lakeside willows), sunlit rim highlights, softer forest inter-tree outlines; vineyard tilled furrows/trellis posts/dry-stone walls; Ref. Kirche cemetery limestone headstones/wall/cypresses; ashlar Jura-stone retaining walls; hillside stone stairs; ZVV bus shelters, promenade benches, pasture fences/hay bales, and `sports_enclosures` windscreens. | M2 | survey_1 |
| F15 | Unified Reproducible `export_animations.py` Pipeline | Integrate edge-to-edge road generation (retiring external scratch `build_swisstopo_edge_roads.py`), `ambient.shoreline` extraction from `lake_mask & diorama_mask`, full occlusion computation on all routes (incl. Alte Landstrasse), and LV95-projected vignette/chimney/fountain anchors directly into `pipeline/export_animations.py`. | M3 | survey_2 |
| F16 | Fix Dorfstrasse Viaduct Routing & Smooth Junction Fillets | Route `dorfstrasse_viaduct_up`/`dn` strictly along the real curved Dorfstrasse horseshoe viaduct over SBB tracks with bilinear `bridge_z` sampling and smooth Bezier/Hermite junction fillets (eliminating off-road shortcut & 157°/178° hairpin kinks). | M3 | survey_2 |
| F17 | Fix ZSG Steamer Bendlikon Pier Docking & Edge-to-Edge Lake Path + VBZ Bus Stops | Re-target `zsg_ms_helvetia` to real Bendlikon Pier (`Badweg 1.1`), extend start/end to NE/SW aquarium water cut-edges, fix Bendlikon flag UV, fix `ambient.gulls` schema, and add real Kilchberg VBZ/ZVV bus stop fractions (`stops`) on bus routes. | M3 | survey_2 |
| F18 | Fix Living-World Critical Bugs (`sbb_dpz`, `evalWithStationStop`, `gulls`, `swans`, `SUP` orientation) | Restore double-decker SBB KISS/DPZ renderer (`kind === 'sbb_dpz' \|\| kind === 'sbb_kiss'`), fix `evalWithStationStop()` exact-stop math & `isDocked` wake shutoff, fix `ambient.gulls` coordinates, keep all 5 swans strictly inside `waterMask`, flip SUP board/wake on return leg while preserving realistic slow speed. | M4 | survey_2, survey_3 |
| F19 | Depth-Masking Fast-Path Optimization & High-Zoom Accuracy Fix | Bounding-box pre-check against `depthPixels` before `getImageData` (-60–80% GPU readbacks), fix depth slope (`4.2 -> 5.91` with clamped vertical roof bias), remove `1024px` high-zoom cutoff (`>=5×`), add zoom LOD culling for `<1 px` cyclists/peds, and depth-mask ships & key vignette walkers. | M4 | survey_2, survey_3 |
| F20 | Upgraded Swiss Living Fleet, VBZ Bus Stops, ZSG Paddle Steamer & Dual-Track SBB Signals | Pixel-crisp Swiss vehicle fleet (articulated VBZ Line 161 bus, ZVV bus with window mullions/wheels/LED sign/stop dwells, Post/Lindt/Migros/Coop/estate/compact/rare emergency vehicles, night taillight asphalt bloom), ZSG paddle-steamer side-wheel foam/funnel wisp/nav lights/gangplank pause, moored sailboat bobbing, dual-track SBB `Typ L/N` signals + train tail LEDs + door blinkers, village chimney wisps/fountains/natural wildlife (ducks, red kites — ZERO paragliders), expanded Follow Camera (`Train`/`Boat`/`Bus`), dead sprite code cleanup. | M4 | survey_2 |
| F21 | True Diurnal Living-World Choreography (Midday / Alpenglow / Night) | Reduce night road traffic ~55%, pedestrians ~75%, cyclists ~80% (with crisp white front + blinking red rear lights), moor/hide recreational sailboats at night, add Sunset golden-hour village chimney wisps & Lindt golden chocolate fountain atrium shimmer, warm streetlamp pools along all main streets (incl. fixed Dorfstrasse & Alte Landstrasse). | M4 | survey_2 |
| F22 | Fix Topbar/Workspace Flex Layout + Collapsible Sidebar & Mobile Responsiveness | Replace hardcoded `calc(100vh - 62px)` with flex-column layout (`min-height: 0`), permanently eliminating the `29px` bottom HUD/minimap clipping at `1280×800` and mobile widths; add collapsible inspector drawer (`Tab`/`I`) and clean Swiss-cartographic topbar grouping. | M5 | survey_3 |
| F23 | HiDPI/Retina DPR Canvas Scaling & 60 FPS Render-Loop Optimization | Scale main canvas, modal canvas, minimap, and 6× loupe by `Math.min(devicePixelRatio, 2)` with integer-snapped crisp pixel art; cache `220×106` minimap thumbnail per preset, dirty-check DOM pin transforms (`translate3d`), cache Zurich `Intl.DateTimeFormat`, pre-filter night lamp roads. | M5 | survey_3 |
| F24 | Silky Camera Kinematics, Mood-Reactive Backdrop & Crossfade Transitions | Cubic ease-out `flyToLandmark()` & zoom buttons, gentle drag momentum/inertia, double-click zoom, `body[data-mode="day\|sunset\|night"]` atmospheric backdrop + smooth preset crossfade. | M5 | survey_3 |
| F25 | Swiss Cartographic Heirloom HUD, Building Highlight, Address Search, Guided Tour & Share/Postcard Export | Dynamic metric scale bar (`0.25 m/px`), subtle NW/N isometric compass rose (`az 102°`), live cursor LV95/elevation readout, aspect-corrected building hover/click highlight reticle + roof color swatch, instant search across 1,887 Kilchberg addresses + 10 landmarks, active `.lm-item` state + Prev/Next/Auto-Tour stepper, upgraded detail-plate modal (`lmId` "Fly Here", pinch-zoom, zoom readout, `4×`), Shareable Permalink copy button, Swiss Postcard PNG exporter, `?` shortcuts modal, synced `?v=7.0` versioning & accurate elevation stat (`406.0 m – 550.5 m spire`). | M5 | survey_3 |
| F26 | Spatial Audio Bugfixes, Shore-Strict Attenuation, Motorway Doppler & Layer Mixer | Fix 12s visual/audio church bell desync, decouple `updateSoundscape()` from paused animations, fix L1/L2 stereo pan centroid math, strongly attenuate shoreline waves & local traffic below `scale < 0.65` (so quiet lake waves are strictly heard near shore), `audioCtx.suspend()` on mute, subtle A3 motorway passing-by doppler `playbackRate` modulation, tasteful ZSG pier departure horn, and compact collapsible audio layer mixer popover (`Master`, `Nature`, `Traffic`, `Rail & Lake`, `Church Bells`). | M5 | survey_2, survey_3 |
| F27 | 4-Tier Opaque-Box E2E Test Suite + Tier 5 Adversarial Hardening | Requirement-driven automated 4-tier test suite (Python `unittest`+`numpy`+`Pillow`+`ffprobe` + Node 24 native CDP with Chromium 156) covering assets, pixel quality, constraints, live browser UX/layout/audio/animations, plus Final Milestone Tier 1–4 pass and Tier 5 white-box adversarial coverage hardening. | M6 (+ E2E Track) | survey_3 |

---

## Milestones

| # | Name | Scope | Dependencies | Status | Sub-Orch Conv ID |
|---|------|-------|-------------|--------|------------------|
| M1 | Environment Bootstrap, Cache Rebuild & Hygiene | F1, F2, F3 | none | DONE (`.venv`, `/tmp/kilchberg-cache/`, `.gitignore`, `config.py`, `extract_scene.py` steps) | `02e6956a8b765dd2b696db39761e082c` |
| M2 | Pixel-Art Shader, Lighting, Water, Architecture, Landmarks & Re-Render | F4–F14 | M1 | DONE (`pixel_shader.py` + `day`/`sunset`/`night` + 6 plates synced, `verify_quality` 11/11 `[ok]`) | `a2e8d2e166f39f4e838a4dff6ad62147` |
| M3 | Unified Living-World Data Pipeline & Edge-to-Edge Path Engineering | F15–F17 | M1 | DONE (`export_animations.py`, `kilchberg_animations.json`, 5/5 Gate PASS, T1.FA2 8/8 PASS) | `11c494f168e5d3a0c02a72254c0dc5a2` |
| M4 | Living-World Engine, Depth Occlusion & Diurnal Choreography | F18–F21 | M3 | DONE (5/5 Gate PASS, APPROVE/CLEAN) | `e99d266e85758be1dea6f2418a368b0c` |
| M5 | Swiss Cartographic UI/UX, HiDPI/Perf, Camera & Spatial Audio Overhaul | F22–F26 | M2, M4 | DONE (APPROVE/CLEAN + flakiness fix) | `orchestrator_2` |
| M6 | Final Milestone: Full 70-Test E2E Pass, Verification & Publish | F27 | M5, TEST_READY.md | IN_PROGRESS (70/70 E2E PASS, 11/11 `[ok]`, `reviewer_final` APPROVE; publishing to `origin main`) | `orchestrator_3` |
| E2E | E2E Testing Track (Parallel Opaque-Box 4-Tier Test Suite) | `TEST_INFRA.md`, `tests/**`, `TEST_READY.md` | none | DONE (70 tests across Tiers 1–4, 63.1s, 5/5 Gate PASS, `TEST_READY.md` published) | `c60b80fb237dc68df8008099f1e2d6e3` |

---

## Interface Contracts

### 1. Python Environment Contract (`M1` ↔ `M2`, `M3`, `M6`)
- Verified `PYTHON_BIN = /home/antigravity/mad-greg/pixel-art/.venv/bin/python` (`Python 3.11.2`, all 21 `requirements.txt` packages installed via `uv`).
- `/tmp/kilchberg-cache/` (`1.5G`) contains the full verified swisstopo cache (`scene_kilchberg_05m.npz` with additive `steps_mask`/`steps_dist`/`steps_along`/`steps_ang`, `buildings_kilchberg_3d.npz`, `ortho_25cm.npy`, `roof_edge_step_25cm.npy`, `bldg_roof_mask_05m.npy`, `buildings_kilchberg_meta.json` with `surface_steps`, 44 GeoTIFFs, 2 CityGML zips, 6 MVT `.pbf` tiles; `1,890` buildings with Lindt HoC `idx=1443`, `16,046` trees, `47` boats, `34` catenary portals, `98` staircases).

### 2. Camera, Canvas & Depth Map Contract (`M1`/`M2` ↔ `M3`, `M4`, `M5`, `E2E`)
- `IsometricCamera`: `azimuth_from_deg = 102.0`, `pitch_deg = 30.0`, `z_exag = 1.16`, `mpp = 0.25`.
- Master canvas: `12331 × 5444` (`13 × 6 = 78` lossless WebP tiles of `1024 px` per preset in `docs/assets/tiles/{day,sunset,night}/` with `manifest.json`).
- Overviews: `docs/assets/diorama_{day,sunset,night}.webp` (`6165 × 2722`).
- Depth map: `docs/assets/kilchberg_depth.png` (`6165 × 2722`, `DEPTH_MIN = -2400.0`, `DEPTH_MAX = 2400.0`, `R = d16 >> 8`, `G = d16 & 0xFF`, `B = 255` for occluder materials).
- Detail plates: 6 WebPs `docs/assets/01_*.webp` – `06_*.webp` (`0.22 m/px`, `>= 2000 × 1400`).
- Canonical Bendlikon ZSG Steamer Pier (`bendlikon_pier`): `E = 2684061.0, N = 1242076.0` (`Badweg 1.1`, Schiffssteg Kilchberg ZH See).

### 3. Interactive Metadata Contract (`M2` ↔ `M5`, `E2E`)
- `docs/data/kilchberg_interactive.json`:
  - `canvas_width: 12331`, `canvas_height: 5444`, `camera: {...}`, `stats: {buildings_total, buildings_kilchberg, triangles_3d, trees_3d, palette_colors: 256, ortho_res_cm: 25, lidar_res_cm: 50, elevation_min_m, elevation_max_m}`
  - `landmarks`: 10 entries with `{id, name, subtitle, description, e, n, z, u, v, zoom, crop}` (with `bendlikon_pier` aligned to `Badweg 1.1`).
  - `buildings`: `>= 1850` entries with `{id, u, v, addr, nb, type, e, n, zg, zr, h, rgb}`.

### 4. Animation Data Contract (`M3` ↔ `M4`, `M5`, `E2E`)
- `docs/data/kilchberg_animations.json`:
  - `canvas_width: 12331`, `canvas_height: 5444`, `mpp: 0.25`, `depth_min: -2400.0`, `depth_max: 2400.0`.
  - `trains`: `sbb_s8_south` (`kind: "sbb_dpz"`, 4 cars, `stop_frac` at Bahnhof Kilchberg platform center), `sbb_ic_north` (`kind: "sbb_ic"`, 4 cars, `stop_frac` at Bahnhof platform center); `pts: [[u, v, occ, d16], ...]`.
  - `roads`: 8 edge-to-edge routes (`seestrasse_sb`, `seestrasse_nb`, `dorfstrasse_viaduct_up`, `dorfstrasse_viaduct_dn`, `a3_motorway_0`, `a3_motorway_1`, `alte_landstrasse_eb`, `alte_landstrasse_wb`), each with `pts: [[u, v, occ, d16], ...]`, `speed_mps`, `car_count`, `bus_count`, optional `stops: [frac, ...]` for VBZ/ZVV bus dwells, zero kinks `> 45°`, 100% on real 0.5m DEM/bridge roadbeds.
  - `ships`: `zsg_ms_helvetia` (`kind: "zsg_steamer"`, open edge-to-edge lake path, `stop_frac` at `Badweg 1.1`, `dwell_sec`), `sailboat_1..3`, `boesch_runabout`.
  - `ambient`:
    - `chimney_steam`: `{name, uv: [u, v]}`
    - `village_chimneys`: `[{u, v, phase}, ...]` (8–10 cozy hillside/Dorf chimneys)
    - `fountains`: `[{u, v, name}, ...]` (2–3 village *Dorfbrunnen*)
    - `swiss_flags`: 4 entries `[{name, uv: [u, v]}, ...]` (Bendlikon Pier flag at `Badweg 1.1`)
    - `gulls`: `[{uv: [u, v], rx, ry, spd, ph}, ...]` (pixel radii `rx, ry`; parsed cleanly by `app.js`)
    - `shoreline`: `[[u, v], ...]` (`>= 80` ordered coastal points along Kilchberg shoreline)
    - `vignettes` (optional/additive LV95-projected anchors for landmarks so `app.js` stays aligned).

### 5. Frontend DOM & Test Telemetry Contract (`M4`/`M5` ↔ `E2E`)
- `docs/index.html` served statically over HTTP with zero external CDN dependencies required for core functionality.
- Lighting modes toggled via buttons/URL `?mode=day|sunset|night`, reflecting `document.body.dataset.mode` (`day`, `sunset`, `night`).
- Deterministic URL params preserved: `?mode=`, `?zoom=`, `?u=`, `?v=`, `?pins=`, `?cinema=`, `?follow=`, `?t=` (fixed animation timestamp for deterministic visual tests).
- Read-only telemetry accessor `window.__dioramaDebug` (non-intrusive, read-only state snapshot: `{ mode, scale, u, v, dpr, animTime, fps, audioEnabled, audioState, audioGains, activeLandmark, selectedBuilding, searchResultCount }`) exposed cleanly for opaque-box/E2E verification without altering production UX.

---

## Code Layout
```
/home/antigravity/mad-greg/pixel-art/
├── .gitignore                      # Must include .agents/ (M1)
├── requirements.txt                # Geospatial + imaging Python dependencies
├── PROJECT.md                      # This living project architecture & milestone ledger
├── TEST_INFRA.md                   # E2E Testing Track methodology & inventory (E2E)
├── TEST_READY.md                   # E2E Testing Track completion signal (E2E)
├── pipeline/
│   ├── config.py                   # LV95 bounds, IsometricCamera, LANDMARKS (M1)
│   ├── fetch_data.py               # Swisstopo dataset downloader
│   ├── extract_scene.py            # 0.5m DEM/DSM/buildings/trees/bridges/steps (M1)
│   ├── pixel_shader.py             # 3D isometric SVGA pixel-art shader (M2)
│   ├── render_all.py               # Split-friendly batch renderer & tile slicer (M2)
│   ├── export_animations.py        # Unified edge-to-edge animation exporter (M3)
│   └── verify_quality.py           # Quick pipeline sanity assertions (M2)
├── docs/                           # GitHub Pages deployment root
│   ├── index.html                  # Swiss cartographic HUD shell (M5)
│   ├── styles.css                  # Flex layout, mood backdrops, heirloom styling (M5)
│   ├── app.js                      # Living-world engine (M4) + UI/Camera/Audio (M5)
│   ├── assets/
│   │   ├── diorama_{day,sunset,night}.webp
│   │   ├── kilchberg_depth.png
│   │   ├── 01_*.webp .. 06_*.webp
│   │   ├── tiles/{day,sunset,night}/{manifest.json, c_r.webp}
│   │   └── audio/*.mp3
│   └── data/
│       ├── kilchberg_interactive.json
│       └── kilchberg_animations.json
├── renders/                        # Full-res archival PNG renders
└── tests/                          # 4-tier automated E2E test suite (E2E Track)
```
