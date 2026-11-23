# Project: Kilchberg Pixel-Art Diorama v14 — Moving/Living Layer Redo

## Architecture
Kilchberg v14 replaces stateless, collision-blind moving-layer routines with a **modular, specification-driven, collision-free, real-time-capable simulation engine** layered cleanly on top of the finalized `0.11 m/px` (`27,971 × 12,294`) static diorama tiles (zero static tile re-renders required).

### Core Subsystems & Data Flow
```
KilchbergClock (Europe/Zurich live | manual scrub | deterministic ?t=)
        │
        ▼
SpecRegistry (RailServiceSpec | BusRouteSpec | InhabitantSpec | VesselSpec | SportsScheduleSpec)
        │
        ├──► 2D Spatial Hash Grid (docs/js/sim/spatial.js — 16 m cells, shared by Traffic/Peds & Vessels)
        │
        ├──► Rail Plugin (trains.js + engine.js trackRank-first sort + vehicles.js back-to-front gangways)
        ├──► Traffic & Pedestrians (traffic.js + pedestrians.js: cross-lane IDM, 6 junctions, bidirectional crosswalks, 2D ped/cyclist braking, named inhabitants)
        ├──► Sports Sim (sports_sim.js + sports.js: TennisRallySim 2-arc bounce + SoccerMatchSim possession/pass/shot)
        ├──► Vessel Sim (vessel_sim.js + vessels.js: COLREGs priority, CPA speed yield, water-masked lateral avoidance)
        └──► Seebad, Wildlife, Landmarks, Shoreline, Atmosphere, Audio (single-source-of-truth signals)
```

### Non-Negotiable Guardrails (Carried Forward from v8–v13.1)
1. **Zero static tile re-renders**: Preserve all finalized `0.11 m/px` `day`/`sunset`/`night` WebP tiles and `pipeline/verify_quality.py` (10/10 `[ok]`).
2. **Opaque train & bus roofs**: Preserve `depth.js` `depthSlopeVert` and `extraVertPx` (`trains: 7.5`, `buses: 6.5`, `ships: 6.0`, `cars: 3.0`, `cyclists/peds: 2.0`).
3. **Bahnhof NW board/clock behind passing trains**: Render NW departure board & SBB Mondaine clocks in `'pre_rail'` strictly before `'rail'`.
4. **No paragliders; slow SUPs (`1.5–1.8 m/s`, 0 at night); 4-petal white-flower Kilchberg municipal flag; clock-free St. Elisabeth & Gemeindehaus**.
5. **DEM-exact edge-to-edge roads & footpaths**: Zero roof walking, zero trackbed walking.
6. **60 fps budget**: Single `rAF` loop, zero per-frame radial gradients, zero DOM layout thrash, `updateMs < 50`, `drawMs < 50`.
7. **Shore-strict spatial audio**: Preserve `CHANNEL_MAX_RANGE.lake_waves = 0.042` + `waveZoomGate`.
8. **100% seeded determinism under `?t=`**: Zero `Math.random()`, pixel-identical `?t=<sec>` snapshots, and `/?t=<num>` without `&mode=` locks deterministically to `day` so CI never flakes at night in Zurich.
9. **Backwards-compatible E2E & module contracts**: Preserve `window.__dioramaDebug` (`livingRegistry`, `simStats`, `livingCounts`, `audioGains`, `depthStats`, `frameStats`), `docs/js/sim/{traffic,pedestrians}.js` exports (`T2.SM.03`), and `docs/js/render/vignettes.js` regex anchors (`T2.LET.07`, `T2.LM.01`, `T2.LM.02`).
10. **Zero `localhost` URLs** in any user-facing text.

---

## Feature Inventory
Every Survey feature is assigned a milestone (0 unassigned).

| # | Feature | Description | Milestone | Source |
|---|---|---|---|---|
| F1 | Declarative `SpecRegistry` | Hot-injectable registry for Rail, Bus, Inhabitant, Vessel, and Sports specs with validation & `__dioramaDebug.specs` API | M1 | survey_1, survey_2, survey_3 |
| F2 | Kilchberg Default Data Packs | Declarative specs for SBB S8/S24/IC, ZVV 161/162/163/165, named Kilchberg inhabitants with daily routines, ZSG vessels, and sports schedules | M1 | survey_1, survey_2 |
| F3 | Real-Time `KilchbergClock` & Continuous Diurnal | `Europe/Zurich` live CET/CEST time, solar elevation auto-preset, continuous time-of-day curves, real-time Swiss clock dials, manual scrub & deterministic `?t=` override | M1 | survey_1, survey_3 |
| F4 | Unified 2D Spatial Hash Grid | Fast 16 m cell spatial index (`docs/js/sim/spatial.js`) for O(1) proximity queries across vehicles, pedestrians, cyclists, and vessels | M1 | survey_1, survey_2 |
| F5 | Multi-Key `'rail'` Layer Sorting | Update `LivingEngine` (`engine.js`) to support `(trackRank, sortY)` primary/secondary sorting on `'rail'` | M1 | survey_1 |
| F6 | Glitch-Free Double-Track Train Passing | Assign `trackRank` (Gleis 2 NW = 0, Gleis 1 SE = 1) in `trains.js`, fix back-to-front inter-car gangways in `vehicles.js`, wire `RailServiceSpec` + `KilchbergClock`, preserve `'pre_rail'` board/clocks & opaque roofs | M2 | survey_1, survey_3 |
| F7 | Cross-Lane Shared-Corridor & Junction Traffic | 2D cross-lane IDM across overlapping physical roads (`dorfstrasse_viaduct` ↔ `alte_landstrasse`/`seestrasse`), 6-junction conflict-box reservation (`network.junctions`), feeder-to-main yielding, true 2D `overlapCount`/`clippingCount` | M2 | survey_1, survey_3 |
| F8 | Collision-Free Vehicle–Pedestrian & Cyclist Safety | Bidirectional crosswalk yielding (no `minStopDist` skip, pedestrian curb look-ahead), 2D forward-cone ped/cyclist braking for all vehicles, lateral offset for `walk_feeder` walkers, cyclist-car awareness | M2 | survey_1, survey_3 |
| F9 | Spec-Driven ZVV Buses & Named Inhabitants | Consume `BusRouteSpec` in `traffic.js` and `InhabitantSpec` (named residents with home/work/errand routines & click inspection) in `pedestrians.js`, preserving `T2.SM.03` exports & `simStats` bounds | M2 | survey_1, survey_3 |
| F10 | Realistic Tennis Match State Machine | `TennisRallySim` on 3 TC Kilchberg courts + lakeside court: 2-segment arc with clay bounce + dust puff, `1.25–1.75 s` shots (`14–20 m/s`), rally pauses/serves, `2.5–5.5 m/s` footwork, displacement-driven stride | M3 | survey_2, survey_3 |
| F11 | Realistic Soccer & Multisport State Machine | `SoccerMatchSim` on Hochweid, Brunnenmoos, Hochweid Upper & 2 multisport courts: `<= 6.5 m/s` player cap, 3D ballistic/rolling ball (zero solo circles), possession/dribble/pass/shot/goal-kick state machine | M3 | survey_2, survey_3 |
| F12 | Collision-Free Maritime `VesselSim` & ZSG Specs | Stateful `VesselSim` (`ctx.shared.vesselSim`) with `VesselSpec`, COLREGs priority (`steamer > sailboat > skiff/sup > motorboat`), 15 s CPA speed yield + water-masked lateral avoidance, pier/swimmer/moored-boat exclusion, slow SUPs preserved | M3 | survey_2, survey_3 |
| F13 | Seebad/Wildlife Calibration & Single-Source Audio | Slow open-lake swimmers (`0.75–0.90 m/s`), pool swimmers (`0.85–1.05 m/s`), swans (`0.65–0.85 m/s`), ducks (`0.55–0.75 m/s`), swallows (`~11 m/s`), jetty spacing; `landmarks.js` & `audio.js` read single-source live state while preserving shore-strict `lake_waves` | M3 | survey_2 |
| F14 | App Wiring, Real-Time Kilchberg HUD & v14.0 Sync | Wire `KilchbergClock` & `SpecRegistry` into `app.js`/`living/index.js`, add top-right `.viewport-ui` Live Kilchberg Clock & manual scrub pill (mobile/Cinema safe), expose v14 debug telemetry, bump `ASSET_VER = '14.0'` & `?v=14.0`, capture fresh live screenshots | M4 | survey_1, survey_3 |
| F15 | Opaque-Box v14 E2E Test Suite | Update `TEST_INFRA.md`, update `T2.V13.V04` for `>= 13.0`/`14.0`, add `tests/tier2_v14_simulation.mjs` covering F1–F14, publish `TEST_READY.md` | E2E | survey_3 |
| F16 | Final Milestone Verification & Adversarial Hardening | Phase 1: 100% E2E pass (Tiers 1–4) + `pipeline.verify_quality` (10/10 `[ok]`); Phase 2: Tier 5 adversarial challenger hardening; visual verification screenshots for Sentinel Victory Audit | M5 | survey_1, survey_2, survey_3 |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| M1 | Core Clock, Spec Registry, 2D Spatial Kernel & Rail-Layer Sorting | F1, F2, F3, F4, F5 | none | DONE (5/5 unanimous, Iter 3) |
| E2E | E2E Testing Track (v14 Suite + `TEST_READY.md`) | F15 | none | DONE (5/5 unanimous, 14 suites / 146 tests) |
| M2 | Glitch-Free Trains + Collision-Free Traffic & Modular Inhabitants | F6, F7, F8, F9 | M1 | DONE (5/5 unanimous, Iter 2) |
| M3 | Realistic Sports Physics + Collision-Free Maritime, Wildlife & Audio | F10, F11, F12, F13 | M1 | DONE (5/5 unanimous, Iter 2) |
| M4 | App Integration, Real-Time Kilchberg HUD & Visual Captures | F14 | M2, M3 | DONE (5/5 unanimous, Iter 1, 7 screenshots) |
| M5 | Final Milestone (Tiers 1–4 Pass + Tier 5 Adversarial Hardening) | F16 | M4, E2E | IN_PROGRESS (`d6d47adb`) |

---

## Interface Contracts

### 1. `KilchbergClock` (`docs/js/living/clock.js`)
```js
export function createKilchbergClock(opts = {})
// Returns clock instance:
// - setMode(mode: 'live' | 'manual' | 'deterministic')
// - setManualMinutes(minutesOfDay: number)          // 0..1440
// - setPresetOverride(preset: 'auto' | 'day' | 'sunset' | 'night')
// - setDeterministic(tSec: number, preset: 'day' | 'sunset' | 'night')
// - setSpeedMultiplier(mult: number)                // default 1
// - sample(nowMs: number, tSec: number): ClockSnapshot
//
// ClockSnapshot:
// {
//   clockMode: 'live' | 'manual' | 'deterministic',
//   zurichSecOfDay: number,      // 0..86400
//   hours: number,               // 0..23
//   minutes: number,             // 0..59
//   seconds: number,             // 0..59
//   tzLabel: 'CET' | 'CEST',
//   formattedHHMM: string,       // e.g. '14:22'
//   dayOfWeek: number,           // 0=Sun..6=Sat
//   solarElevationDeg: number,   // Kilchberg 47.324°N, 8.549°E
//   autoPreset: 'day' | 'sunset' | 'night',
//   effectivePreset: 'day' | 'sunset' | 'night',
//   diurnalActivity: {
//     commuterFactor: number,    // 0.1..1.4 (peaks 07:30, 17:45)
//     trafficFactor: number,     // 0.15..1.2
//     pedestrianFactor: number,  // 0.12..1.2
//     leisureFactor: number,     // 0.0..1.2 (daytime lake/sports)
//     nightFactor: number        // 0.0..1.0
//   }
// }
```

### 2. `SpecRegistry` (`docs/js/specs/registry.js`)
```js
export function createSpecRegistry(initialPacks = {})
// Methods:
// - registerRailService(spec) / removeRailService(id) / getRailServices()
// - registerBusRoute(spec) / removeBusRoute(id) / getBusRoutes()
// - registerInhabitant(spec) / removeInhabitant(id) / getInhabitants()
// - registerVessel(spec) / removeVessel(id) / getVessels()
// - registerSportsSchedule(spec) / removeSportsSchedule(id) / getSportsSchedules()
// - onChange(domain, listener) -> unsubscribe()
// - getSummary() -> { rail, bus, inhabitants, vessels, sports }
// Validation throws descriptive Error on missing required fields (`id`, coordinates/routes, etc.).
```

### 3. `SpatialGrid2D` (`docs/js/sim/spatial.js`)
```js
export function createSpatialGrid(cellSizeM = 16)
// Methods (zero-allocation steady-state):
// - clear()
// - insert(id, xM, yM, radiusM, kind, data)
// - queryRadius(xM, yM, radiusM, filterKind?, outArray?) -> Array<Entry>
// - uvToMeters(u, v) -> { xM, yM }   // exact inverse of Kilchberg isometric projection
// - metersToUv(xM, yM) -> { u, v }
```

### 4. `LivingEngine` Multi-Key `'rail'` Sort (`docs/js/living/engine.js`)
- `'rail'` drawables accept optional `trackRank` (number, default `0`) in addition to `sortY`.
- Sorting comparator for `'rail'`: `(a.trackRank ?? 0) - (b.trackRank ?? 0) || (a.sortY || 0) - (b.sortY || 0)`.
- Gleis 2 (NW / back track, larger `d16`) uses `trackRank = 0`; Gleis 1 (SE / front track, smaller `d16`) uses `trackRank = 1`.

### 5. `ctx.shared` Cross-Plugin Contracts (`docs/js/living/context.js`)
- `ctx.clock`: current `ClockSnapshot` from `KilchbergClock`
- `ctx.specs`: active `SpecRegistry` instance
- `ctx.shared.spatialGrid`: shared `SpatialGrid2D`
- `ctx.shared.vesselSim`: active `VesselSim` exposing `getPierDockState(pierId)`, `getTelemetry()`, `getVessels()`
- `ctx.shared.sportsSim`: active `SportsSim` exposing `getTelemetry()`
- `ctx.shared.railTelemetry`: `{ activeTrains, passingNow, trackInterleaveViolations }`

### 6. `window.__dioramaDebug` v14 Telemetry Extensions (Additive Only)
Keep ALL existing v13 keys untouched, and add:
- `window.__dioramaDebug.clock`: current `ClockSnapshot` + `setMode`/`setManualMinutes`/`setPresetOverride`
- `window.__dioramaDebug.specs`: `SpecRegistry` API (`registerInhabitant`, `registerBusRoute`, `registerRailService`, `registerVessel`, `remove*`, `getSummary`)
- `window.__dioramaDebug.simStats.pedVehicleOverlapCount`: number (must be `0`)
- `window.__dioramaDebug.railTelemetry`: `{ activeTrains, passingNow, trackInterleaveViolations }`
- `window.__dioramaDebug.sportsTelemetry`: `{ tennisCourts, soccerPitches, maxSoccerPlayerMps, minTennisShotSec, maxTennisShotSec, tennisBouncesObserved, ballModes }`
- `window.__dioramaDebug.vesselTelemetry`: `{ activeVessels, minPairwiseClearanceM, collisionCount, maxSupSpeedMps }`

---

## Code Layout (Exclusive Ownership per Milestone)
- **M1**:
  - `docs/js/specs/registry.js` (new)
  - `docs/js/specs/sbb_kilchberg.js` (new)
  - `docs/js/specs/zvv_kilchberg.js` (new)
  - `docs/js/specs/inhabitants_kilchberg.js` (new)
  - `docs/js/specs/vessels_kilchberg.js` (new)
  - `docs/js/specs/sports_kilchberg.js` (new)
  - `docs/js/sim/spatial.js` (new)
  - `docs/js/living/clock.js` (new)
  - `docs/js/living/diurnal.js` (update)
  - `docs/js/living/context.js` (update)
  - `docs/js/living/engine.js` (update)
  - `docs/js/living/draw.js` (update)
- **M2**:
  - `docs/js/living/plugins/trains.js` (update)
  - `docs/js/render/vehicles.js` (update — train gangway order only)
  - `docs/js/sim/traffic.js` (update)
  - `docs/js/sim/pedestrians.js` (update)
  - `docs/js/living/plugins/traffic.js` (update)
  - `docs/js/living/plugins/pedestrians.js` (update)
- **M3**:
  - `docs/js/sim/sports_sim.js` (new)
  - `docs/js/living/plugins/sports.js` (update)
  - `docs/js/sim/vessel_sim.js` (new)
  - `docs/js/living/plugins/vessels.js` (update)
  - `docs/js/living/plugins/seebad.js` (update)
  - `docs/js/living/plugins/wildlife.js` (update)
  - `docs/js/living/plugins/landmarks.js` (update)
  - `docs/js/audio.js` (update)
- **M4**:
  - `docs/js/living/index.js` (update)
  - `docs/app.js` (update)
  - `docs/index.html` (update)
  - `docs/styles.css` (update)
- **E2E Track**:
  - `TEST_INFRA.md` (update)
  - `TEST_READY.md` (update)
  - `tests/tier2_v13_vegetation.py` (update `T2.V13.V04` version check)
  - `tests/tier2_v14_simulation.mjs` (new)
  - `tests/run_e2e.py` (register `tier2_v14_simulation.mjs`)
