# Project: Kilchberg (ZH) Museum-Grade Landmark Polish & Expansion (v9.0)

## Architecture
Kilchberg is a static GitHub Pages 2:1 isometric pixel-art diorama (`docs/`, 12,331×5,444 master @ 0.25 m/px) backed by a Python swisstopo LiDAR/MVT/DOP10 rendering and data-export pipeline (`pipeline/`), verified by `pipeline.verify_quality` and a 4-tier opaque-box E2E suite (`tests/run_e2e.py`, 88+ tests via Python `unittest` + Node raw CDP).

- **Pipeline (`pipeline/`)**:
  - `config.py`: LV95 domain, `IsometricCamera`, and `LANDMARKS` (expanded from 10 → 16 curated Kilchberg landmarks; original 10 strictly preserved at indices `0..9`; `cf_meyer_haus` fixed from 388 m north to real Swiss KGS-Nr. 7525 `Alte Landstrasse 170`).
  - `fetch_data.py` + `extract_scene.py`: Rebuilds ephemeral `/tmp/kilchberg-cache/` (`scene_kilchberg_05m.npz`, `buildings_kilchberg_meta.json`, CityGML/MVT/GeoTIFFs).
  - `pixel_shader.py`: Master 3D orthographic pixel-art renderer (`LANDMARK_SPECS` resolved by LV95 proximity for all 16 landmarks, facade/roof/prop/uplighting polish, strictly preserving authentic 25 cm SWISSIMAGE DOP10 roof on Lindt HoC `id=1443`).
  - `render_all.py`: Split-safe CLI batch orchestrator (`day`, `sunset`, `night`, 234 lossless WebP tiles, `kilchberg_depth.png`, `kilchberg_interactive.json`, and 10 high-res 0.22 m/px detail plates `01..10_*.webp` in `CROP_SPECS`/`PLATE_CARTOUCHE_META`).
  - `export_animations.py`: Exports `docs/data/kilchberg_animations.json` (`< 650 KB`, backward-compatible `trains`/`roads`/`ships`/`ambient`/`network`; `ambient.swiss_flags` kept at length 4; aligned `cf_meyer_haus` vignette/fountain; rich `ambient.vignettes` anchors for all 16 landmarks).
  - `verify_quality.py`: Automated `[ok]` checks across all 3 presets, depth map, all 10 detail plates, and interactive JSON (`len(landmarks) >= 16`).
- **Frontend (`docs/`)**:
  - Native ES modules (`?v=9.0` synced across `index.html`, `styles.css`, `app.js`):
    - `docs/index.html` & `docs/styles.css`: Dynamic landmark stop count badge, 10-plate gallery, zero desktop/mobile layout clipping.
    - `docs/app.js`: 10-plate `CROPS` array (preserving `01..06` at indices `0..5`), zoom-aware overview pin decluttering in `updatePins()`, `?landmark=<id>` deep-link boot, `[`/`]` prev/next landmark keyboard navigation, preserving all 13 `window.__dioramaDebug` Contract #5 keys + `livingCounts`/`depthStats`/`simStats`.
    - `docs/js/render/vignettes.js`: Deterministic, viewport-culled, `isWaterUV`-strict live micro-details covering all 16 landmarks (polishing 7 existing + adding 3 previously un-vignetted landmarks + adding all 6 new landmarks).

## Code Layout & Write Ownership
| Path | Owner Milestone | Notes |
|------|----------------|-------|
| `pipeline/config.py`, `pipeline/pixel_shader.py`, `pipeline/render_all.py`, `pipeline/verify_quality.py` | M1 | Cache rebuild, 16 landmarks (`0..9` preserved + 6 new), `cf_meyer_haus` fix, fine-detail 3D/shader polish across all 16 landmarks, 10 detail plates, `verify_quality` update |
| `pipeline/export_animations.py`, `docs/assets/*`, `docs/data/kilchberg_interactive.json`, `docs/data/kilchberg_animations.json`, `renders/*` | M2 | Vignette anchor updates (`swiss_flags` kept at 4, `cf_meyer_haus` realigned, 16 landmark vignettes), split renders (`day`, `sunset`, `night`, crops + animations, each `< 10 min`), `verify_quality` 100% `[ok]` |
| `docs/index.html`, `docs/styles.css`, `docs/app.js`, `docs/js/render/vignettes.js` | M3 | `?v=9.0`, dynamic stop count, 10-plate gallery, overview pin decluttering, `?landmark=` deep-link, `[`/`]` shortcuts, live micro-details for all 16 landmarks |
| `tests/*`, `TEST_INFRA.md`, `TEST_READY.md` | E2E Track | Preserve all 88 existing tests (relaxing only `== 10` → `>= 10` in `T1.FA2.01`/`T1.FA3.04`) + add Tier 1–4 v9.0 opaque-box tests |
| Final verification, Tier 5 hardening, git commit/push & GH Pages `"built"` | M4 | Phase 1 (Tiers 1–4 E2E 100% + `verify_quality` 100%) → Phase 2 (Tier 5 white-box Challenger) → Whole-Project Audit → deploy |

## Feature Inventory
Every Survey feature from `survey_1`, `survey_2`, and `survey_3` is assigned to a milestone (none unassigned):

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Ephemeral cache rebuild | Rebuild `/tmp/kilchberg-cache/` via `.venv/bin/python -m pipeline.fetch_data` and `.venv/bin/python -m pipeline.extract_scene` | M1 | ORIGINAL_REQUEST, survey_1 |
| 2 | `cf_meyer_haus` coordinate fix | Move `cf_meyer_haus` (index 7) 388 m south to real Swiss KGS-Nr. 7525 `Alte Landstrasse 170` (`E=2683714, N=1241442`, `id=1033`) and realign its vignette & fountain | M1 (config/shader) + M2 (animations) | survey_1, survey_2 |
| 3 | Decouple `bahnhof_stockengut` & add 6 Tier-1 new landmarks | Keep original 10 landmark IDs at indices `0..9`; refocus `bahnhof_stockengut` on Bahnhof/Viaduct/Schulhaus Dorfstrasse; append 6 island-verified landmarks (`10..15`): `gemeindehaus_alte_landstr`, `stockengut_farm`, `hallenbad_hochweid`, `broelberggut_estate`, `villa_spinnergut_tc`, `morfanlage_promenade` (16 total) | M1 | ORIGINAL_REQUEST, survey_2, survey_3 |
| 4 | Lindt HoC & Factory fine-detail polish | Curved rotunda dark vertical glazing mullions, recessed entrance doors, warm interior fountain glow, forecourt Jura-stone paving/bollards/planters/totem; smokestack climbing ladder/tension rings/lightning rod; 1899 brick wing arched window muntins/dentil cornices/loading canopies; cocoa silo safety guardrails & service ladder — keeping `id=1443` DOP10 roof 100% untouched | M1 | survey_1, survey_2 |
| 5 | Reformierte Kirche, Cemetery & Gotisch Hus polish | 3D gilded spire cross/Wetterhahn finial, Gothic nave buttresses/portal/stained-glass tracery, cemetery stone gate pillars/cypresses/Dorfbrunnen basin/Thomas Mann & C.F. Meyer memorial marker, Gotisch Hus (`1675`) timber-frame detailing, barn doors & hayloft shutters | M1 | survey_1, survey_2 |
| 6 | Bendlikon Pier & Harbor fine-detail polish | Blue-white ZSG `KILCHBERG ZH (SEE)` pier fascia sign, timetable board, orange-white lifebuoy ring, canopy bench, hinged gangplank; Bendlikon Pavilion veranda trim/quay steps/café parasols/lantern glow | M1 | survey_1, survey_2 |
| 7 | Bahnhof Kilchberg & Schulhaus Dorfstrasse polish | SBB platform benches, red ticket machine, blue-white Perronanzeiger, covered Velounterstand, 3D SBB trackside signal masts, station window mullions/bargeboards, Schulhaus Dorfstrasse (`1709`) facade detailing | M1 | survey_1, survey_2 |
| 8 | Schooren Seebad, Villa Naville & Chez Fritz polish | Floating wooden swim raft (Floss), red-white swim-zone buoy line, sun-loungers, lifeguard/shower post; Villa Naville stone belt courses/wrought-iron balconies/portico/terraced park walls; Schooren porcelain quarter quoins/arched portals; Chez Fritz (`1598`) awning | M1 | survey_1, survey_2 |
| 9 | Sanatorium Kilchberg & Greenhouses polish | Add to `up_targets` night/sunset uplighting; classical pedimented porte-cochère, stone window surrounds, roof eave brackets, glass conservatory detailing on `Treibhaus` `225`/`886`, park balustrade/pergola/benches | M1 | survey_1, survey_2 |
| 10 | Kath. Kirche St. Elisabeth fine-detail polish | 3D slender metallic cross atop 30.1 m bell tower (`518.0 m`), clock hands on tower dial, concrete formwork seam bands, recessed nave portal, amber/cobalt/crimson stained-glass clerestory glow, forecourt steps | M1 | survey_1, survey_2 |
| 11 | C.F. Meyer-Haus (`1033`) fine-detail polish | Add to `up_targets` night/sunset uplighting; carved stone portal pediment, terracotta geranium window boxes, garden stone retaining wall/wrought-iron gate/pergola/fountain at real `Alte Landstrasse 170` | M1 | survey_1, survey_2 |
| 12 | Mönchhof & Horn (`moenchhof_horn`) fine-detail polish | Register Hafenbeiz & Mönchhof am See (`243`/`843`, iconic red half-timbered Riegelhaus), lakeside villas (`727/303/527/890/781`), and boathouses (`25/825`) in `LANDMARK_SPECS` with timber doors/slipways, beer-garden parasols, seawall steps, lantern bollards | M1 | survey_1, survey_2 |
| 13 | Sulzergut Park (`sulzergut_park`) fine-detail polish | Register Villa Sulzergut (`1617/1338`) and lakeside boathouses (`1169/1550/1706/984`) in `LANDMARK_SPECS` with walnut boathouse siding/arched boat bays/slipways, neoclassical manor quoins/shutters/garden terrace, stone park balustrade | M1 | survey_1, survey_2 |
| 14 | 6 New Landmarks 3D/shader detailing | Bespoke `LANDMARK_SPECS` & 3D props for: (11) Gemeindehaus & Schulhaus Alte Landstrasse (uplighting, bell cupola/clock dormer, stone steps, dual flagpoles), (12) Stockengut farm (barn gables, twin silos `1135/1174`, greenhouse `1587`, stone wall `653`, Hofladen/fences), (13) Hallenbad & Sportanlage Hochweid (aquamarine-glowing clerestory pool hall, cantilevered roof, red-ochre 400 m track/pitches), (14) Broelberggut & Tempelchen (KGS-12593 manor, octagonal whitewashed pavilion `1074`, parterre hedges/carriage court), (15) Villa Spinnergut & TC Kilchberg (1914 neo-baroque villa `1601`, clay courts & clubhouse `1287`), (16) Morfanlage & Lakeside Park (dressed limestone quay wall, boathouses `42/379`, bathing steps/benches) | M1 | survey_2 |
| 15 | 10 High-Res Detail Plates (`01..10_*.webp`) | Keep Plates `01..06` unchanged at indices `0..5`; add 4 museum plates in `CROP_SPECS`/`PLATE_CARTOUCHE_META`: `07_st_elisabeth_church`, `08_cf_meyer_haus`, `09_gemeindehaus_alte_landstrasse`, `10_stockengut_ridge_farm` (`0.22 m/px`, `>= 2000×1400`, `<= 256` colors, zero floating sky pixels) | M1 (config) + M2 (render) | survey_1, survey_2, survey_3 |
| 16 | `verify_quality.py` update & split full re-render | Update `verify_quality.py:224` (`>= 16` landmarks); run split renders (`day`, `sunset`, `night`, crops + animations — each `< 10 min`) and verify 100% `[ok]` (SVGA `<= 256` colors, macro-seam `< 1.35`, depth map, zero floating sky pixels) | M1 (`verify_quality`) + M2 (renders) | ORIGINAL_REQUEST, survey_1, survey_3 |
| 17 | Animation vignette anchors & `swiss_flags` compatibility | Update `pipeline/export_animations.py` with realigned `cf_meyer_haus` vignette/fountain, new `ambient.vignettes` anchors for `sanatorium_ridge`, `moenchhof_horn`, `sulzergut_park` & all 6 new landmarks, keeping `ambient.swiss_flags` at length 4 and JSON `< 650 KB` | M2 | survey_2, survey_3 |
| 18 | Frontend 16-landmark UX, 10-plate gallery & deep-links | Sync `?v=9.0`; dynamic `${meta.landmarks.length} STOPS` badge; 10-plate `CROPS` array (`01..06` preserved at `0..5`); zoom-aware overview pin decluttering in `updatePins()`; `?landmark=<id>` deep-link boot & `[`/`]` prev/next landmark keyboard shortcuts | M3 | survey_3 |
| 19 | Live micro-details & vignettes for all 16 landmarks | Polish 7 existing vignettes in `docs/js/render/vignettes.js` (facade uplights, stained-glass glow, pier lanterns/water-lap, SBB station clock, diving ripples) and add deterministic `isWaterUV`-strict vignettes for `sanatorium_ridge`, `moenchhof_horn`, `sulzergut_park`, and all 6 new landmarks | M3 | survey_2, survey_3 |
| 20 | Extended 4-tier E2E test suite (v9.0) | Preserve all 88 existing tests (relaxing only `== 10` → `>= 10` in `T1.FA2.01` & `T1.FA3.04`); add opaque-box tests for 16 landmarks, `cf_meyer_haus` authentic location, 10 detail plates, `?landmark=` deep-link, overview pin decluttering, dynamic stop count, and v9.0 landmark tour | E2E Track | survey_3 |
| 21 | Final E2E pass, Tier 5 hardening, commit/push & GH Pages `"built"` | Pass 100% E2E (Tiers 1–4) + `verify_quality` 100% `[ok]` + Tier 5 white-box Challenger hardening + Whole-Project Forensic Audit `CLEAN` + commit, push `origin main`, verify GitHub Pages `"built"` | M4 | ORIGINAL_REQUEST, Project Pattern |
| 22 | Photo-verified real-world signature details (Dual 3D + Live Canvas) | Multi-source Wikipedia/Wikimedia/web photographic research across all 16 landmarks (e.g., Lindt & Sprüngli rooftop illuminated `"LINDT & SPRÜNGLI"` letters & factory wall clocks, `"LINDT HOME OF CHOCOLATE"` curved travertine facade lettering & Schokoladenplatz front plaza, plus photo-verified signature lettering/clocks/architectural elements on all other 14 landmarks), reflected in BOTH `pipeline/pixel_shader.py` (re-rendered split `< 10 min` + visual plate inspection) AND crisp 2×–4× zoom live canvas overlays in `docs/js/render/vignettes.js` | M3.5 | ORIGINAL_REQUEST (2026-11-21T05:12:09Z) |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Pipeline Landmark Config, 3D Detail Polish & 10-Plate Specs | Rebuild `/tmp/kilchberg-cache/`, fix `cf_meyer_haus`, add 6 Tier-1 landmarks (16 total), polish fine 3D/shader detail on all 16 landmarks, add Plates `07..10`, update `verify_quality.py`, verify via fast crop renders | none | DONE (16 landmarks, 82/82 LANDMARK_SPECS, 10 lossless plates `221..251` colors, 0 floating sky clusters, Lindt roof `std=42.44`, 5/5 PASS, Auditor CLEAN) |
| M2 | Split Full Renders, Vignette Anchors & Asset Publication | Update `pipeline/export_animations.py` (realign `cf_meyer_haus`, add vignette anchors, keep `swiss_flags==4`), run split `day`/`sunset`/`night`/crops+animations renders (`< 10 min` each), verify `pipeline.verify_quality` 100% `[ok]` | M1 | DONE (15/15 verify_quality `[ok]`, 41/41 Python E2E OK, 234/234 tiles, 10/10 plates, 331.42 KiB JSON, 5/5 PASS, Auditor CLEAN) |
| M3 | Frontend Landmark UX, 10-Plate Gallery & Live Vignettes | Update `docs/index.html`, `docs/styles.css`, `docs/app.js`, `docs/js/render/vignettes.js` (`?v=9.0`, dynamic stop badge, 10 plates, overview pin decluttering, `?landmark=` deep-link, `[`/`]` keys, live vignettes for all 16 landmarks) | M2 | DONE (97/97 E2E PASS, 0.0000 determinism, 5/5 PASS, Auditor CLEAN) |
| M3.5 | Photo-Verified Landmark Signature Details (Dual 3D + Live Canvas + Re-Render) | Apply multi-source Wikipedia/Wikimedia photo research for all 16 landmarks to BOTH `pipeline/pixel_shader.py` (rooftop `"LINDT & SPRÜNGLI"` letters, factory wall clocks, `"LINDT HOME OF CHOCOLATE"` facade lettering, Schokoladenplatz, plus all 14 other landmarks — keeping Lindt `#1443` DOP10 roof untouched) AND crisp 2×–4× zoom live canvas overlays in `docs/js/render/vignettes.js`; split re-render (`day`/`sunset`/`night`/10 plates), visual verification & 15/15 `verify_quality` + 97/97 E2E | M3, photo_research_1..3 | IN_PROGRESS |
| E2E | E2E Testing Track (v9.0) | Update `tests/` (preserve 88 existing tests + add Tier 1–4 v9.0 landmark/plate/UX tests), publish updated `TEST_INFRA.md` & `TEST_READY.md` | none (parallel) | DONE (97 tests: 88/88 baseline + 9 new v9.0, 5/5 PASS, Auditor CLEAN, TEST_READY.md published) |
| M4 | Final Milestone (Tiers 1–4 + Tier 5 Hardening + Deploy) | Phase 1: 100% E2E pass + `verify_quality` + visual check; Phase 2: Tier 5 white-box Challenger hardening; Whole-Project Audit `CLEAN`; commit, push `origin main`, verify GitHub Pages `"built"` | M3.5, E2E | PLANNED |

## Interface Contracts

### 1. Landmark Registry (`pipeline/config.py` → `docs/data/kilchberg_interactive.json` → `docs/app.js`)
- Total landmarks: **16** (`len(meta["landmarks"]) == 16`).
- **Strict Index Preservation (`0..9`)**:
  - `0: lindt_hoc`, `1: reformierte_kirche`, `2: bendlikon_pier`, `3: bahnhof_stockengut`, `4: schooren_seebad`, `5: sanatorium_ridge`, `6: st_elisabeth`, `7: cf_meyer_haus` (fixed to `E=2683714, N=1241442`), `8: moenchhof_horn`, `9: sulzergut_park`.
- **Appended Tier-1 Landmarks (`10..15`)**:
  - `10: gemeindehaus_alte_landstr` (`E=2683630, N=1242075, Z=455`)
  - `11: stockengut_farm` (`E=2683207, N=1242037, Z=507`)
  - `12: hallenbad_hochweid` (`E=2683140, N=1241415, Z=515`)
  - `13: broelberggut_estate` (`E=2683775, N=1241245, Z=468`)
  - `14: villa_spinnergut_tc` (`E=2683440, N=1240875, Z=502`)
  - `15: morfanlage_promenade` (`E=2683885, N=1242360, Z=408`)
- Every landmark MUST have `0.05 <= u, v <= 0.95`, `(px)` consistent with `(u*12331, v*5444)` within `2.0 px`, and `(u, v)` strictly inside `island_2x`.
- `cf_meyer_haus` MUST resolve within `35 m` LV95 of `Alte Landstrasse 170` (`E=2683714, N=1241442`).
- `LANDMARK_SPECS` in `pixel_shader.py` MUST resolve buildings via LV95 proximity (`_resolve_landmark_ids`), never brittle raw IDs alone.

### 2. Detail Plates (`pipeline/render_all.py` → `docs/assets/` → `docs/app.js`)
- Total detail plates: **10** (`0.22 m/px`, lossless `VP8L` RGB, `>= 2000×1400`, body `<= 256` SVGA colors, zero floating sky clusters).
- **Strict Index Preservation (`0..5`)**:
  - `01_lindt_home_of_chocolate.webp` (`lindt_hoc`)
  - `02_reformierte_kirche_dorf.webp` (`reformierte_kirche`)
  - `03_bendlikon_harbor_pier.webp` (`bendlikon_pier`)
  - `04_bahnhof_kilchberg_weinberg.webp` (`bahnhof_stockengut`)
  - `05_schooren_seebad.webp` (`schooren_seebad`)
  - `06_sanatorium_ridge.webp` (`sanatorium_ridge`)
- **Appended Plates (`6..9`)**:
  - `07_st_elisabeth_church.webp` (`st_elisabeth`)
  - `08_cf_meyer_haus.webp` (`cf_meyer_haus`)
  - `09_gemeindehaus_alte_landstrasse.webp` (`gemeindehaus_alte_landstr`)
  - `10_stockengut_ridge_farm.webp` (`stockengut_farm`)

### 3. Animations & Vignettes (`pipeline/export_animations.py` → `docs/data/kilchberg_animations.json` → `docs/js/render/vignettes.js`)
- Total file size `< 650 KB`.
- Preserve 100% backward compatibility on `trains[2]`, `roads[8]`, `ships[5]`, `network`, and `ambient.swiss_flags` (length **4** — place any additional landmark flags under `ambient.vignettes.<id>`).
- `ambient.vignettes` includes realigned `cf_meyer_haus` plus anchors for `sanatorium_ridge`, `moenchhof_horn`, `sulzergut_park`, and all 6 new landmarks (`gemeindehaus_alte_landstr`, `stockengut_farm`, `hallenbad_hochweid`, `broelberggut_estate`, `villa_spinnergut_tc`, `morfanlage_promenade`).
- All vignette water elements strictly obey `isWaterUV`; all animations are deterministic (zero `Math.random()`).

### 4. Frontend & Global Kilchberg Guardrails (Zero Tolerance)
- `docs/index.html`: `<script type="module" src="app.js?v=9.0"></script>` synced with `styles.css?v=9.0` and `ASSET_VER = '9.0'`. Zero external CDN `<script>` tags.
- `window.__dioramaDebug` preserves all 13 Contract #5 keys + `livingCounts`, `depthStats`, `simStats`, `waterMaskReady`, `followTarget`.
- `?landmark=<id>` URL parameter boots directly to the specified landmark (setting `activeLandmark`).
- Overview pin decluttering (`cssScale() < 0.7`) prevents overlapping `.lm-pin` labels while revealing all 16 pins at `cssScale() >= 0.7` (and always showing the active landmark pin).
- **Zero-tolerance guardrails**:
  - Zero `paraglider`/`hot-air`/`balloon`/`glider` anywhere in `docs/`.
  - Slow SUP paddlers (~1.5–1.8 m/s).
  - Exact 0.5 m DEM roads edge-to-edge (no off-road drift, no water intrusion).
  - Authentic 25 cm SWISSIMAGE DOP10 roof on Lindt Home of Chocolate (`id=1443`) 100% untouched.
  - Spotless Lake Zurich shoreline, smooth Bendlikon/Dorfstrasse viaduct, flat SBB rail bridges, opaque train & bus roofs (`kilchberg_depth.png` open-air roof small hits `< 2%` trains / `< 1%` main roads; any new thin 1px poles/crosses near roads/rails excluded from `occ_m`), `<= 256` SVGA tile colors, macro-seam `< 1.35`, and shore-strict 9-channel spatial audio mix.
  - Never output `localhost` URLs. Split long renders strictly `< 10 min` per command.
