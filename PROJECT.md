# Project: Kilchberg (ZH) v11 Landmark Photo-Realism Pass

## Architecture
Kilchberg v11 builds on the v10.0 `0.125 m/px` (`24,661 × 10,888`, 2-level `1024 px` lossless VP8L tile pyramid, 10 `0.11 m/px` detail plates, 16 landmarks, 15/15 `verify_quality` `[ok]`, 110/110 E2E) baseline by executing a dedicated **one-agent-per-landmark** photo-realism audit and implementation across all 16 landmarks in `pipeline/config.py`.

Each of the 16 landmarks receives its own dedicated research & visual-comparison agent that inspects:
1. Current v10.0 raw `0.125 m/px` L2 tile crops (`day` + `night`), live 3× browser screenshots (`vignettes.js` overlays composited), and existing `0.11 m/px` detail plates (where available).
2. Real-life photographic & architectural references (Wikipedia/Wikimedia Commons, Swiss Denkmalpflege, municipal/building sources, and native 10 cm SWISSIMAGE DOP10 roof ortho).
3. Exact current styling across all 4 code layers: `pipeline/config.py`, `pipeline/pixel_shader.py`, `pipeline/signage.py`, and `docs/js/render/vignettes.js`.

Key confirmed issues already surfaced in Step 0 Survey (`survey_v11_1..3`):
- **St. Elisabeth (`st_elisabeth`)**: Has **THREE** stacked inaccurate clocks (`pixel_shader.py:6426–6448`, `signage.py:345`, `vignettes.js:2243`), warm beige `(198,192,180)` base walls, and a speculative `"ST. ELISABETH"` nave sign (`signage.py:170`) — real tower has **NO clock** and distinct real-life colors/materials.
- **Duplicate/conflicting baked clocks & signage**: `ref_kirche` (`pixel_shader.py:6340–6372` dark/gold vs `signage.py:344` white dial vs `vignettes.js:885`), `lindt_main` (`pixel_shader.py:6255–6270` vs `signage.py:341` vs `vignettes.js:1111`, plus 3D gold rooftop strokes `7616–7635` vs red wall sign `signage.py:143`), `gemeindehaus_main` (`pixel_shader.py:6616–6626` vs `signage.py:343` vs `vignettes.js:2430`), `schulhaus_alteland_868` (`pixel_shader.py:6616–6626` vs `vignettes.js:2431`), and duplicate Swiss+Kilchberg flag pairs near Gemeindehaus (`vignettes.js:609–611` & `2413–2414`).
- **All 16 landmarks** audited individually for authentic colors, materials, roof/wall tones, tower design, clocks (presence/absence), windows/shutters, signage, plazas, and surroundings.

## Code Layout & Write Ownership
| Path | Owner Milestone | Notes |
|------|----------------|-------|
| `/tmp/v11_baseline_views/*`, `/tmp/kilchberg-cache/*` | M1 | Ephemeral baseline visual crops (16 raw L2 day/night + 16 live 3× day) and rebuilt `/tmp/kilchberg-cache/` (`fetch_data` + `extract_scene` + `ortho_10cm.npy`) |
| `.agents/teamwork/lm_01_*` .. `.agents/teamwork/lm_16_*` | M2a–M2d | 16 dedicated per-landmark photo-realism research & correction specs (read-only on repo) |
| `pipeline/pixel_shader.py`, `pipeline/signage.py`, `pipeline/config.py`, `docs/js/render/vignettes.js` | M3 | Coordinated photo-realism implementation for all 16 landmarks + fast visual crop previews (all 16 landmarks) |
| `docs/assets/*`, `docs/data/kilchberg_interactive.json`, `docs/data/kilchberg_animations.json`, `docs/index.html`, `docs/styles.css`, `docs/app.js`, `renders/*` | M4 | Split `--macro-rows` full renders (`day`/`sunset`/`night`, `< 10 min`, `< 4.5 GiB` RSS), 10 `0.11 m/px` plates, animations export, `?v=11.0` cache-bust, `verify_quality` 15/15 `[ok]`, `docs/ < 300 MB`, VP8L tiles `< 500 KB` |
| `tests/*`, `TEST_INFRA.md`, `TEST_READY.md` | E2E Track | Preserve all 110 baseline v10 tests & guardrails + add v11 landmark photo-realism regression tests (e.g. St. Elisabeth no-clock, verified landmark accuracy) |
| Final verification, Tier 5 hardening, commit/push & GH Pages `"built"` | M5 | Tiers 1–4 100% E2E + `verify_quality` + visual inspection of all 16 updated landmarks → Tier 5 white-box Challenger → Whole-Project Forensic Audit `CLEAN` → deploy |

## Feature Inventory
Every Survey feature and all 16 landmarks are assigned a milestone (none unassigned):

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Baseline 16-landmark visual capture & `/tmp/kilchberg-cache/` rebuild | Capture 16 raw L2 crops (`day`/`night`) + 16 live 3× CDP screenshots to `/tmp/v11_baseline_views/`; rebuild `/tmp/kilchberg-cache/` (`fetch_data` + `extract_scene`) | M1 | survey_v11_3 |
| 2 | Landmark 1 (`lindt_hoc`) dedicated photo-realism audit | Dedicated agent: Lindt HoC curved white glazed ceramic/red brick/gold lettering + Schokoladenplatz + Historic Factory rooftop lettering, wall clock, chimney | M2a | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 3 | Landmark 2 (`reformierte_kirche`) dedicated photo-realism audit | Dedicated agent: Reformierte Kirche plaster, tower clock (reconcile white baked vs dark/gold), spire/Wetterhahn, cemetery, Gotisch Hus | M2a | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 4 | Landmark 3 (`bendlikon_pier`) dedicated photo-realism audit | Dedicated agent: Bendlikon ZSG pier canopy, signage placement (`bendlikon_pavilion` vs pier), pavilion colors, harbor props | M2a | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 5 | Landmark 4 (`bahnhof_stockengut`) dedicated photo-realism audit | Dedicated agent: Bahnhof olive stucco/red shutters/SBB clock/NW board, Schulhaus Dorfstrasse, Dorfstrasse viaduct | M2a | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 6 | Landmark 5 (`schooren_seebad`) dedicated photo-realism audit | Dedicated agent: Seebad cedar bathhouse, signage, pool, Sprungturm/Floss, Chez Fritz, Villa Naville, Schooren porcelain quarter | M2b | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 7 | Landmark 6 (`sanatorium_ridge`) dedicated photo-realism audit | Dedicated agent: Sanatorium Kilchberg pavilion wings, facades, colors, verandas, greenhouses, park | M2b | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 8 | Landmark 7 (`st_elisabeth`) dedicated photo-realism audit | Dedicated agent (PRIORITY): Real colors/materials of nave & tower, **REMOVE all 3 inaccurate tower clocks** (`pixel_shader.py`, `signage.py:345`, `vignettes.js:2243`), audit nave sign & stained glass | M2b | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 9 | Landmark 8 (`cf_meyer_haus`) dedicated photo-realism audit | Dedicated agent: C.F. Meyer-Haus exact stucco/shutter/roof tones, balcony, portal, garden, Auf Brunnen fountain | M2b | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 10 | Landmark 9 (`moenchhof_horn`) dedicated photo-realism audit | Dedicated agent: Hafenbeiz Riegelhaus red Fachwerk, Wintergarten, signage, boathouses, northern shore villas | M2c | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 11 | Landmark 10 (`sulzergut_park`) dedicated photo-realism audit | Dedicated agent: Sulzergut villas, chalet boathouses, kleine Steintreppe, lakeside park | M2c | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 12 | Landmark 11 (`gemeindehaus_alte_landstr`) dedicated photo-realism audit | Dedicated agent: Gemeindehaus & Schulhaus Alte Landstrasse colors, cupolas, clocks (reconcile duplicates/verify existence), duplicate flag pairs, Kilchberg 4-petal Wappen | M2c | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 13 | Landmark 12 (`stockengut_farm`) dedicated photo-realism audit | Dedicated agent: Stockengut barns (preserve DOP10 solar PV on barn 807), Hofladen, silos, Grauvieh cattle, signage | M2c | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 14 | Landmark 13 (`hallenbad_hochweid`) dedicated photo-realism audit | Dedicated agent: Hallenbad 1970s concrete/glass facade, signage, cold-plunge, Hochweid athletics track & football pitch | M2d | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 15 | Landmark 14 (`broelberggut_estate`) dedicated photo-realism audit | Dedicated agent: Broelberggut manor, Parkpavillon/Tempelchen roof/color/finial, formal parterre garden | M2d | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 16 | Landmark 15 (`villa_spinnergut_tc`) dedicated photo-realism audit | Dedicated agent: Villa Spinnergut neo-baroque facade/conservatory, TC Kilchberg clubhouse & clay courts | M2d | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 17 | Landmark 16 (`morfanlage_promenade`) dedicated photo-realism audit | Dedicated agent: Morfanlage lakeside park, boathouses, Seestrasse villas, Jura-limestone quay & promenade | M2d | ORIGINAL_REQUEST, survey_v11_1, survey_v11_2 |
| 18 | Coordinated photo-realism implementation & fast visual crop preview | Apply all 16 verified correction specs across `pixel_shader.py`, `signage.py`, `config.py`, `vignettes.js`; render fast preview crops for all 16 landmarks & verify via full gate | M3 | ORIGINAL_REQUEST, M2a–M2d |
| 19 | Split full-resolution re-render (`0.125 m/px` + 2-level pyramid + 10 plates + `?v=11.0`) | Split `--macro-rows` (`0 2`, `2 4`, `4 6`, `--finalize-tiles`) for `day`/`sunset`/`night` (`< 10 min`, `< 4.5 GiB` RSS), 10 `0.11 m/px` plates, `export_animations`, `?v=11.0`, `verify_quality` 15/15 `[ok]`, `docs/ < 300 MB`, VP8L tiles `< 500 KB` | M4 | ORIGINAL_REQUEST, survey_v11_3 |
| 20 | E2E v11 landmark photo-realism regression tests | Preserve all 110 baseline tests + add opaque-box v11 landmark photo-realism tests (St. Elisabeth no-clock, reconciled clocks/signage, etc.); update `TEST_INFRA.md` & `TEST_READY.md` | E2E Track | ORIGINAL_REQUEST, survey_v11_3 |
| 21 | Final Milestone: Tiers 1–4 E2E + Visual Inspection of All 16 Landmarks + Tier 5 + Deploy | 100% E2E + `verify_quality` + visual inspection of all 16 updated landmarks → Tier 5 white-box Challenger → Whole-Project Forensic Audit `CLEAN` → commit, push `origin main`, GH Pages `"built"`, ready for Victory Audit | M5 | ORIGINAL_REQUEST, Project Pattern |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Baseline Visual Capture & Cache Rebuild | Capture 16 raw L2 crops (`day`/`night`) + 16 live 3× CDP screenshots to `/tmp/v11_baseline_views/`; rebuild `/tmp/kilchberg-cache/` (`fetch_data` + `extract_scene`) | none | DONE (48/48 PNGs, 3.0G cache + 1.8G ortho_10cm.npy) |
| M2a | Dedicated Landmark Agents 1–4 | 4 parallel dedicated agents (`lindt_hoc`, `reformierte_kirche`, `bendlikon_pier`, `bahnhof_stockengut`) | M1 | DONE (4/4 photo-verified specs) |
| M2b | Dedicated Landmark Agents 5–8 | 4 parallel dedicated agents (`schooren_seebad`, `sanatorium_ridge`, `st_elisabeth`, `cf_meyer_haus`) | M1 | DONE (4/4 photo-verified specs, incl. St. Elisabeth) |
| M2c | Dedicated Landmark Agents 9–12 | 4 parallel dedicated agents (`moenchhof_horn`, `sulzergut_park`, `gemeindehaus_alte_landstr`, `stockengut_farm`) | M1 | DONE (4/4 photo-verified specs) |
| M2d | Dedicated Landmark Agents 13–16 | 4 parallel dedicated agents (`hallenbad_hochweid`, `broelberggut_estate`, `villa_spinnergut_tc`, `morfanlage_promenade`) | M1 | DONE (4/4 photo-verified specs) |
| E2E | E2E Testing Track (v11 Photo-Realism Tests) | Add v11 landmark photo-realism regression tests (preserving all 110 baseline tests & guardrails), publish `TEST_READY.md` | M2a–M2d | DONE (115 tests: 110 baseline + 5 v11 `T2.LM.01-05`, 5/5 PASS, Auditor CLEAN, `TEST_READY.md` published) |
| M3 | Coordinated Photo-Realism Implementation & Preview | Apply all 16 landmark specs to `pixel_shader.py`, `signage.py`, `config.py`, `vignettes.js`; fast preview crops + full verification gate + checkpoint commit | M2a–M2d | DONE (5/5 PASS Wave 2, Auditor CLEAN, 17 preview crops verified, local commit `e8eb843`) |
| M4 | Split Full-Resolution Re-Render & `?v=11.0` | Split `--macro-rows` full renders (`day`/`sunset`/`night`), 10 `0.11 m/px` plates, animations, `?v=11.0`, `verify_quality` 15/15 `[ok]`, `docs/ < 300 MB`, VP8L tiles `< 500 KB` + checkpoint commit | M3 | DONE (15/15 verify_quality, 89/89 Tier 1-2 E2E, docs=208M, max tile 488.6 KB, Auditor CLEAN, local commit `c67a695`) |
| M5 | Final Milestone (Tiers 1–4 + Visual Review + Tier 5 + Deploy) | 100% E2E + `verify_quality` + visual inspection of all 16 updated landmarks → Tier 5 white-box Challenger → Whole-Project Forensic Audit `CLEAN` → commit, push `origin main`, GH Pages `"built"` | M4, E2E | DONE (115/115 E2E, 15/15 verify_quality, Wave 2 APPROVED, deployed to `origin main`) |

## Interface Contracts

### 1. Master Resolution, Tile Pyramid & Manifest (`pipeline/pixel_shader.py` → `docs/assets/tiles/{mode}/manifest.json` → `docs/app.js`)
- Preserve v10 contract 100%: `mpp = 0.125`, `width = 24,661`, `height = 10,888`, `tileSize = 1024`, L2 `25×11` + L1 `z1` `13×6` lossless `VP8L` tiles (`<= 256` SVGA colors, every tile `< 500 KiB = 512,000 B`), `0.50 m/px` overview, `DEPTH_DS = 4` (`kilchberg_depth.png` == `diorama_day.webp`), 10 `0.11 m/px` detail plates (`>= 3200×2200`, `<= 256` colors, zero floating sky clusters).

### 2. Landmark & Signage Contracts (`pipeline/config.py`, `pipeline/signage.py`, `docs/js/render/vignettes.js`)
- Preserve all 16 landmark IDs & order in `pipeline/config.py`.
- Preserve `signage.build_sign` API and the 5 required `signage.SIGNS` keys (`lindt_main`, `lindt_hoc`, `bahnhof_station`, `seebad_bathhouse`, `gemeindehaus_main`) unless E2E is explicitly updated with strong photographic justification.
- Preserve zero `fillText(` in `docs/js/render/vignettes.js` (keep `drawSignPlaque` & `drawRotatedSignText` disabled no-ops — all signage baked in `pipeline/signage.py`).
- Preserve all 9 `REQUIRED_VIGNETTE_KEYS_V9` in `kilchberg_animations.json` and `cf_meyer_haus` anchor/fountain alignment.
- **St. Elisabeth (`st_elisabeth`)**: ZERO clocks on `st_elisabeth_twr` across `pipeline/pixel_shader.py`, `pipeline/signage.py`, and `docs/js/render/vignettes.js`.

### 3. Global Kilchberg Guardrails & Size Budget (Zero Tolerance)
- `docs/` total size `< 300 MB`; every WebP tile `< 500 KiB` (`512,000 B`); `kilchberg_animations.json < 650 KB`; zero files `> 90 MB`.
- Zero `paraglider`/`hot-air`/`balloon`/`glider` anywhere in `docs/`.
- Slow SUP paddlers (~1.6 m/s); exact 0.5 m DEM roads edge-to-edge (no off-road drift, no walking on roofs or train tracks).
- Authentic 10 cm SWISSIMAGE DOP10 satellite roof textures (especially Lindt HoC `id=1443` `base_w=0.95` and Stockengut barn `807` solar PV).
- Baked isometric landmark lettering & clocks (`pipeline/signage.py` — no floating screen-space UI font overlays), 4-petal white-flower Kilchberg municipal flag, Bahnhof NW info board/clock behind passing trains, opaque train & bus roofs, spotless Lake Zurich shoreline, smooth Bendlikon/Dorfstrasse viaduct, flat SBB rail bridges, deterministic simulation, shore-strict 9-channel spatial audio.
- Never output `localhost` URLs. Split long renders strictly `< 10 min` and `< 4.5 GiB` RSS per command.
