/**
 * Kilchberg Collision-Free Maritime Simulation Engine (v14 — F12).
 *
 * Unified stateful VesselSim published on `ctx.shared.vesselSim`:
 *   - Consumes `VesselSpec` from `SpecRegistry.getVessels()` with graceful fallback
 *     to `animData.ships` + default SUP/skiff patrol routes.
 *   - Authentic Lake Zurich COLREGs priority hierarchy:
 *       1 = zsg_steamer (Kursschiff, absolute right-of-way)
 *       2 = sailboat
 *       3 = skiff / sup (slow SUPs strictly 1.5–1.8 m/s, >= 2 in day, 0 at night)
 *       4 = motorboat (boesch_runabout)
 *   - 2-Tier Avoidance using M1's `createSpatialGrid(16)`, `uvToMeters`, `metersToUv`:
 *       Tier 1: 15 s CPA longitudinal speed yielding
 *       Tier 2: Water-mask-validated smooth lateral starboard offset
 *   - Static & swimmer exclusion zones (Bendlikon Pier, Seebad jetty/swimmers, 5 moored boats).
 *   - Single source of truth for Bendlikon Pier gangplank (`getPierDockState('bendlikon')`),
 *     wildlife avoidance (`getVessels()`), and spatial boat audio.
 *
 * 100% deterministic (zero Math.random()), extreme-timestamp safe (?t=-5, 1e16, NaN).
 */

import { evalWithStationStop } from './schedule.js';
import { createSpatialGrid, metersToUv, uvToMeters } from './spatial.js';

const PERIOD_SEC = 1800.0;
const FIXED_DT = 0.1;

export const MOORED_BOATS = Object.freeze([
  Object.freeze({ id: 'moored:bendlikon_1', name: 'Moored Sailboat · Bendlikon Buoy', u: 0.5758, v: 0.5835, pen: '#d9382e' }),
  Object.freeze({ id: 'moored:bendlikon_2', name: 'Moored Sailboat · Schifflände Bay', u: 0.5935, v: 0.5675, pen: '#2563eb' }),
  Object.freeze({ id: 'moored:seebad_1', name: 'Moored Sailboat · Schooren Mooring', u: 0.4435, v: 0.6995, pen: '#d9382e' }),
  Object.freeze({ id: 'moored:seebad_2', name: 'Moored Sailboat · Seebad South', u: 0.4145, v: 0.7315, pen: '#2563eb' }),
  Object.freeze({ id: 'moored:seebad_3', name: 'Moored Sailboat · Rüschlikon Border', u: 0.4045, v: 0.7395, pen: '#eab308' }),
]);

const DEFAULT_PATROL_SPECS = [
  {
    id: 'skiff:sulzergut',
    name: 'Wooden Rowing Skiff · Lake Zurich',
    kind: 'skiff',
    animShipId: null,
    priorityClass: 3,
    hullLengthM: 5.8,
    hullBeamM: 1.0,
    maxSpeedMps: 1.8,
    closed: false,
    schedule: { mode: 'patrol', u0: 0.618, v0: 0.566, u1: 0.678, v1: 0.522, spd: 0.0026, ph: 0.31 },
    diurnal: { day: true, sunset: true, night: false },
  },
  {
    id: 'sup:bendlikon',
    name: 'SUP Paddler · Bendlikon Bay',
    kind: 'sup',
    animShipId: null,
    priorityClass: 3,
    hullLengthM: 3.4,
    hullBeamM: 0.85,
    maxSpeedMps: 1.6,
    closed: false,
    schedule: { mode: 'patrol', u0: 0.566, v0: 0.610, u1: 0.629, v1: 0.566, spd: 0.0024, ph: 0.15 },
    appearance: { board: '#38bdf8', shirt: '#f43f5e', hair: '#2d241c' },
    diurnal: { day: true, sunset: true, night: false },
  },
  {
    id: 'sup:seebad',
    name: 'SUP Paddler · Seebad Shallows',
    kind: 'sup',
    animShipId: null,
    priorityClass: 3,
    hullLengthM: 3.4,
    hullBeamM: 0.85,
    maxSpeedMps: 1.6,
    closed: false,
    schedule: { mode: 'patrol', u0: 0.446, v0: 0.730, u1: 0.506, v1: 0.675, spd: 0.0021, ph: 0.62 },
    appearance: { board: '#fbbf24', shirt: '#0d9488', hair: '#5c4028' },
    diurnal: { day: true, sunset: true, night: false },
  },
];

// Static & swimmer exclusion zones in meters
function buildExclusionZones() {
  const zones = [];
  const addZone = (id, u, v, radiusM, exemptKinds = []) => {
    const m = uvToMeters(u, v);
    zones.push({ id, u, v, xM: m.xM, yM: m.yM, radiusM, exemptKinds });
  };
  // Bendlikon Pier abutment & berth (exempt zsg_steamer which docks there)
  addZone('bendlikon_pier', 0.5852, 0.5796, 16.0, ['zsg_steamer']);
  // Seebad Kilchberg jetty & buoyed open-lake swimmer area
  addZone('seebad_swimmers', 0.4255, 0.7258, 24.0, []);
  // All 5 moored sailboats
  for (let i = 0; i < MOORED_BOATS.length; i++) {
    const mb = MOORED_BOATS[i];
    addZone(mb.id, mb.u, mb.v, 10.0, ['zsg_steamer']);
  }
  return zones;
}

const EXCLUSION_ZONES = buildExclusionZones();

function clamp(v, lo, hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

function normalizeTimeSec(tSec) {
  if (typeof tSec !== 'number' || !Number.isFinite(tSec)) return 0;
  const r = tSec % PERIOD_SEC;
  return r < 0 ? r + PERIOD_SEC : r;
}

function defaultPriorityForKind(kind) {
  if (kind === 'zsg_steamer') return 1;
  if (kind === 'sailboat') return 2;
  if (kind === 'skiff' || kind === 'sup') return 3;
  return 4;
}

function defaultHullForKind(kind) {
  if (kind === 'zsg_steamer') return { len: 50.0, beam: 12.0 };
  if (kind === 'sailboat') return { len: 9.2, beam: 3.0 };
  if (kind === 'motorboat') return { len: 7.2, beam: 2.4 };
  if (kind === 'skiff') return { len: 5.8, beam: 1.0 };
  return { len: 3.4, beam: 0.85 };
}

function samplePolylineUV(pts, frac, closed) {
  const n = pts ? pts.length : 0;
  if (n < 2) return null;
  const f = closed ? (((frac % 1) + 1) % 1) : clamp(frac, 0, 1);
  const fIdx = f * (n - 1);
  const i0 = Math.min(n - 2, Math.max(0, Math.floor(fIdx)));
  const t = fIdx - i0;
  const p0 = pts[i0];
  const p1 = pts[i0 + 1];
  const u = p0[0] + (p1[0] - p0[0]) * t;
  const v = p0[1] + (p1[1] - p0[1]) * t;

  const ia = Math.max(0, i0 - 3);
  const ib = Math.min(n - 1, i0 + 4);
  const mA = uvToMeters(pts[ia][0], pts[ia][1]);
  const mB = uvToMeters(pts[ib][0], pts[ib][1]);
  let dx = mB.xM - mA.xM;
  let dy = mB.yM - mA.yM;
  const dLen = Math.hypot(dx, dy);
  if (dLen > 1e-4) {
    dx /= dLen;
    dy /= dLen;
  } else {
    dx = 1;
    dy = 0;
  }
  const mPos = uvToMeters(u, v);
  return { u, v, xM: mPos.xM, yM: mPos.yM, dirX: dx, dirY: dy };
}

function isHullInWater(xM, yM, dirX, dirY, hullLenM, hullBeamM, depthMgr) {
  if (!depthMgr || typeof depthMgr.isWaterUV !== 'function') return true;
  if (typeof depthMgr.isWaterMaskReady === 'function' && !depthMgr.isWaterMaskReady()) return true;
  const halfL = Math.min(18, hullLenM * 0.42);
  const halfB = Math.min(5, hullBeamM * 0.5);
  const nx = dirY;
  const ny = -dirX;
  const checks = [
    [xM, yM],
    [xM + dirX * halfL, yM + dirY * halfL],
    [xM - dirX * halfL, yM - dirY * halfL],
    [xM + nx * halfB, yM + ny * halfB],
    [xM - nx * halfB, yM - ny * halfB],
  ];
  for (let i = 0; i < checks.length; i++) {
    const uv = metersToUv(checks[i][0], checks[i][1]);
    if (!depthMgr.isWaterUV(uv.u, uv.v)) return false;
  }
  return true;
}

function isClearOfExclusions(xM, yM, radiusM, kind) {
  for (let i = 0; i < EXCLUSION_ZONES.length; i++) {
    const z = EXCLUSION_ZONES[i];
    if (z.exemptKinds.includes(kind)) continue;
    const d = Math.hypot(xM - z.xM, yM - z.yM);
    if (d < z.radiusM + radiusM) return false;
  }
  return true;
}

export function createVesselSim(animData, specs = null) {
  const spatialGrid = createSpatialGrid(16);
  const queryBuf = [];

  const shipById = new Map();
  const animShips = (animData && Array.isArray(animData.ships)) ? animData.ships : [];
  for (let i = 0; i < animShips.length; i++) {
    const s = animShips[i];
    shipById.set(s.id || `ship:${i}`, { ship: s, sIdx: i });
  }

  let vessels = [];
  let prevXM = new Float64Array(0);
  let prevYM = new Float64Array(0);
  let lastTNorm = null;
  let lastMode = 'day';
  let specVersionKey = '';

  // Cumulative telemetry across simulation run
  let minPairwiseClearanceM = Infinity;
  let collisionCount = 0;
  let maxSupSpeedMps = 0;

  function buildVesselList(activeSpecs) {
    const specList = (activeSpecs && typeof activeSpecs.getVessels === 'function')
      ? activeSpecs.getVessels()
      : null;

    const rawSpecs = [];
    if (Array.isArray(specList) && specList.length > 0) {
      for (let i = 0; i < specList.length; i++) {
        rawSpecs.push(specList[i]);
      }
    } else {
      for (let i = 0; i < animShips.length; i++) {
        const s = animShips[i];
        const hull = defaultHullForKind(s.kind);
        rawSpecs.push({
          id: s.id || `ship:${i}`,
          name: s.name || s.id || `Vessel ${i + 1}`,
          kind: s.kind || 'sailboat',
          animShipId: s.id || `ship:${i}`,
          priorityClass: defaultPriorityForKind(s.kind),
          hullLengthM: hull.len,
          hullBeamM: hull.beam,
          maxSpeedMps: s.speed_mps || 3.0,
          closed: !!s.closed,
          schedule: s.stop_frac != null
            ? { mode: 'timetable', stops: [{ pierId: 'bendlikon', frac: s.stop_frac, dwellSec: s.dwell_sec || 5.5 }] }
            : { mode: 'loop', phase: s.phase || 0 },
          periodicFallback: { mode: 'periodic', phase: s.phase || 0, speedMps: s.speed_mps || 6.8 },
          diurnal: { day: true, sunset: true, night: s.kind === 'zsg_steamer' },
        });
      }
      for (let i = 0; i < DEFAULT_PATROL_SPECS.length; i++) {
        rawSpecs.push(DEFAULT_PATROL_SPECS[i]);
      }
    }

    vessels = [];
    for (let i = 0; i < rawSpecs.length; i++) {
      const sp = rawSpecs[i];
      const shipEntry = sp.animShipId ? shipById.get(sp.animShipId) : null;
      const animShip = shipEntry ? shipEntry.ship : null;
      const sIdx = shipEntry ? shipEntry.sIdx : i;
      const hull = defaultHullForKind(sp.kind);
      const hullLengthM = sp.hullLengthM || hull.len;
      const hullBeamM = sp.hullBeamM || hull.beam;
      // Effective bounding radius for collision-free separation
      const hullRadiusM = sp.kind === 'zsg_steamer'
        ? hullLengthM * 0.36
        : Math.max(hullBeamM * 0.6, hullLengthM * 0.35);

      let patrolLenM = 200;
      let patrolP0 = null;
      let patrolP1 = null;
      if (sp.schedule && sp.schedule.mode === 'patrol') {
        patrolP0 = uvToMeters(sp.schedule.u0, sp.schedule.v0);
        patrolP1 = uvToMeters(sp.schedule.u1, sp.schedule.v1);
        patrolLenM = Math.max(20, Math.hypot(patrolP1.xM - patrolP0.xM, patrolP1.yM - patrolP0.yM));
      }

      // Pre-allocated shifted pts buffer for drawShipEntity when laterally offset
      let renderPts = null;
      let renderShip = null;
      if (animShip && Array.isArray(animShip.pts)) {
        renderPts = animShip.pts.map((pt) => pt.slice());
        renderShip = { ...animShip, pts: renderPts };
      }

      const stopInfo = (sp.schedule && Array.isArray(sp.schedule.stops) && sp.schedule.stops[0]) || null;
      const basePhase = (sp.periodicFallback && sp.periodicFallback.phase != null)
        ? sp.periodicFallback.phase
        : ((sp.schedule && sp.schedule.phase != null) ? sp.schedule.phase : ((animShip && animShip.phase) || 0));

      vessels.push({
        id: sp.id,
        name: sp.name || sp.id,
        kind: sp.kind || 'sailboat',
        priorityClass: sp.priorityClass != null ? sp.priorityClass : defaultPriorityForKind(sp.kind),
        hullLengthM,
        hullBeamM,
        hullRadiusM,
        maxSpeedMps: sp.kind === 'sup'
          ? clamp(sp.maxSpeedMps || 1.6, 1.4, 1.75)
          : (sp.maxSpeedMps || (animShip && animShip.speed_mps) || 3.0),
        closed: sp.closed != null ? !!sp.closed : !!(animShip && animShip.closed),
        schedule: sp.schedule || { mode: 'loop', phase: basePhase },
        stopFrac: stopInfo ? stopInfo.frac : (animShip ? animShip.stop_frac : null),
        dwellSec: stopInfo ? stopInfo.dwellSec : (animShip ? animShip.dwell_sec : 5.5),
        pierId: stopInfo ? stopInfo.pierId : (sp.kind === 'zsg_steamer' ? 'bendlikon' : null),
        basePhase,
        diurnal: sp.diurnal || { day: true, sunset: true, night: sp.kind === 'zsg_steamer' },
        appearance: sp.appearance || null,
        animShip,
        sIdx,
        renderPts,
        renderShip,
        routeLenM: (animShip && animShip.length_m) ? animShip.length_m : patrolLenM,
        patrolP0,
        patrolP1,
        // Mutable simulation state
        visible: false,
        frac: basePhase,
        patrolDir: 1,
        speedMps: 0,
        speedRatio: 0,
        speedFactor: 1.0,
        latOffsetM: 0,
        targetLatOffsetM: 0,
        latOffsetU: 0,
        latOffsetV: 0,
        u: 0,
        v: 0,
        xM: 0,
        yM: 0,
        dirX: 1,
        dirY: 0,
        vxM: 0,
        vyM: 0,
        heading: 0,
        isDocked: false,
        dwellProg: 0,
        approaching: false,
      });
    }
    prevXM = new Float64Array(vessels.length);
    prevYM = new Float64Array(vessels.length);
  }

  function isActiveInMode(v, mode) {
    if (mode === 'night') {
      if (v.kind === 'sup' || v.kind === 'skiff') return false;
      return !!(v.diurnal && v.diurnal.night);
    }
    if (mode === 'sunset') {
      return !v.diurnal || v.diurnal.sunset !== false;
    }
    return !v.diurnal || v.diurnal.day !== false;
  }

  function resetState(mode) {
    minPairwiseClearanceM = Infinity;
    collisionCount = 0;
    maxSupSpeedMps = 0;

    for (let i = 0; i < vessels.length; i++) {
      const v = vessels[i];
      v.speedFactor = 1.0;
      v.latOffsetM = 0;
      v.targetLatOffsetM = 0;
      v.latOffsetU = 0;
      v.latOffsetV = 0;
      v.isDocked = false;
      v.dwellProg = 0;
      v.approaching = false;

      if (v.schedule && v.schedule.mode === 'patrol') {
        const ph = ((v.schedule.ph || 0) % 1 + 1) % 1;
        // Start patrol at smooth interior phase
        v.frac = 0.5 + 0.45 * Math.sin(ph * Math.PI * 2);
        v.patrolDir = Math.cos(ph * Math.PI * 2) >= 0 ? 1 : -1;
      } else {
        v.frac = ((v.basePhase || 0) % 1 + 1) % 1;
        v.patrolDir = 1;
      }
      v.visible = isActiveInMode(v, mode);
      v.speedMps = v.visible ? v.maxSpeedMps : 0;
      v.speedRatio = v.visible ? 1.0 : 0;
      syncVesselGeometry(v, 0);
      if (v.visible && v.kind === 'sup' && v.speedMps > maxSupSpeedMps) {
        maxSupSpeedMps = v.speedMps;
      }
    }
    // Compute initial pairwise clearance at t = 0
    for (let i = 0; i < vessels.length; i++) {
      const a = vessels[i];
      if (!a.visible) continue;
      for (let j = i + 1; j < vessels.length; j++) {
        const b = vessels[j];
        if (!b.visible) continue;
        const clearance = Math.hypot(b.xM - a.xM, b.yM - a.yM) - (a.hullRadiusM + b.hullRadiusM);
        if (clearance < minPairwiseClearanceM) minPairwiseClearanceM = clearance;
      }
    }
  }

  function syncVesselGeometry(v, tCur) {
    let baseX = 0;
    let baseY = 0;
    let dirX = 1;
    let dirY = 0;

    if (v.kind === 'zsg_steamer' && v.animShip && v.animShip.pts) {
      const st = evalWithStationStop(tCur, v.routeLenM, v.maxSpeedMps, v.stopFrac, v.dwellSec, v.basePhase, 5.0, 6.0);
      v.visible = v.visible && st.frac >= 0 && st.frac <= 1;
      v.frac = st.frac;
      v.speedRatio = st.speedRatio;
      v.speedMps = v.maxSpeedMps * st.speedRatio;
      v.isDocked = st.isDwelling;
      v.dwellProg = st.dwellProgress;
      v.approaching = !st.isDwelling && v.stopFrac != null && st.frac >= v.stopFrac - 0.08 && st.frac < v.stopFrac;
      if (!v.visible) return;
      const sample = samplePolylineUV(v.animShip.pts, v.frac, false);
      if (!sample) { v.visible = false; return; }
      baseX = sample.xM;
      baseY = sample.yM;
      dirX = sample.dirX;
      dirY = sample.dirY;
    } else if (v.animShip && v.animShip.pts) {
      const sample = samplePolylineUV(v.animShip.pts, v.frac, v.closed);
      if (!sample) { v.visible = false; return; }
      baseX = sample.xM;
      baseY = sample.yM;
      dirX = sample.dirX;
      dirY = sample.dirY;
    } else if (v.patrolP0 && v.patrolP1) {
      const f = clamp(v.frac, 0, 1);
      baseX = v.patrolP0.xM + (v.patrolP1.xM - v.patrolP0.xM) * f;
      baseY = v.patrolP0.yM + (v.patrolP1.yM - v.patrolP0.yM) * f;
      const dx = (v.patrolP1.xM - v.patrolP0.xM) * v.patrolDir;
      const dy = (v.patrolP1.yM - v.patrolP0.yM) * v.patrolDir;
      const dLen = Math.hypot(dx, dy) || 1;
      dirX = dx / dLen;
      dirY = dy / dLen;
    } else {
      v.visible = false;
      return;
    }

    // Starboard normal (right of travel direction in ground meters)
    const starX = dirY;
    const starY = -dirX;
    const xM = baseX + starX * v.latOffsetM;
    const yM = baseY + starY * v.latOffsetM;
    const uv = metersToUv(xM, yM);
    const baseUv = metersToUv(baseX, baseY);

    v.xM = xM;
    v.yM = yM;
    v.u = uv.u;
    v.v = uv.v;
    v.latOffsetU = uv.u - baseUv.u;
    v.latOffsetV = uv.v - baseUv.v;
    v.dirX = dirX;
    v.dirY = dirY;
    v.heading = Math.atan2(dirY, dirX);
    v.vxM = dirX * v.speedMps;
    v.vyM = dirY * v.speedMps;
  }

  function updateRenderPts(v) {
    if (!v.animShip || !v.renderPts) return;
    const orig = v.animShip.pts;
    const n = orig.length;
    if (Math.abs(v.latOffsetM) < 0.05) return;
    const du = v.latOffsetU;
    const dv = v.latOffsetV;
    const centerIdx = Math.floor(clamp(v.frac, 0, 1) * (n - 1));
    for (let k = -24; k <= 8; k++) {
      const idx = v.closed ? (((centerIdx + k) % n) + n) % n : clamp(centerIdx + k, 0, n - 1);
      v.renderPts[idx][0] = orig[idx][0] + du;
      v.renderPts[idx][1] = orig[idx][1] + dv;
    }
  }

  function shouldYield(a, b) {
    if (b.priorityClass < a.priorityClass) return true;
    if (b.priorityClass > a.priorityClass) return false;
    return b.id < a.id;
  }

  function stepSim(dt, tCur, mode, depthMgr) {
    // 1. Update ZSG steamer (priority 1) and active flags, then index all active vessels in spatialGrid
    spatialGrid.clear();
    for (let i = 0; i < vessels.length; i++) {
      const v = vessels[i];
      v.visible = isActiveInMode(v, mode);
      if (v.kind === 'zsg_steamer') {
        syncVesselGeometry(v, tCur);
      } else if (v.visible) {
        syncVesselGeometry(v, tCur);
      }
      if (v.visible) {
        spatialGrid.insert(v.id, v.xM, v.yM, v.hullRadiusM, 'vessel', v);
      }
    }

    // Snapshot pre-step world positions for speed-capped Step 3 and honest post-step SUP telemetry
    for (let i = 0; i < vessels.length; i++) {
      prevXM[i] = vessels[i].xM;
      prevYM[i] = vessels[i].yM;
    }

    // 2. Evaluate 2-Tier COLREGs avoidance + static exclusion zones for all non-steamer vessels
    for (let i = 0; i < vessels.length; i++) {
      const a = vessels[i];
      if (!a.visible || a.kind === 'zsg_steamer') continue;

      let desiredSpeedFactor = 1.0;
      let desiredLatM = 0.0;
      let urgentThreat = false;
      let hasThreat = false;
      let holdOffset = false;

      // Query nearby vessels within 96 m via 16 m spatial grid + include ZSG steamer for 260 m lookahead
      const nearby = spatialGrid.queryRadius(a.xM, a.yM, 96.0, 'vessel', queryBuf);
      for (let si = 0; si < vessels.length; si++) {
        const sv = vessels[si];
        if (sv.visible && sv.kind === 'zsg_steamer' && sv !== a) {
          let found = false;
          for (let k = 0; k < nearby.length; k++) {
            if (nearby[k].data === sv) { found = true; break; }
          }
          if (!found && Math.hypot(sv.xM - a.xM, sv.yM - a.yM) <= 260.0) {
            nearby.push({ data: sv });
          }
        }
      }
      for (let j = 0; j < nearby.length; j++) {
        const b = nearby[j].data;
        if (!b || b === a || !b.visible) continue;
        if (!shouldYield(a, b)) continue;

        const rx = b.xM - a.xM;
        const ry = b.yM - a.yM;
        const curDist = Math.hypot(rx, ry);
        const rvx = b.vxM - a.vxM;
        const rvy = b.vyM - a.vyM;
        const rvSq = rvx * rvx + rvy * rvy;
        const horizon = b.priorityClass === 1 ? 38.0 : 15.0;
        const tCpa = rvSq > 1e-4 ? clamp(-(rx * rvx + ry * rvy) / rvSq, 0, horizon) : 0;
        const cpaX = rx + rvx * tCpa;
        const cpaY = ry + rvy * tCpa;
        const cpaDist = Math.hypot(cpaX, cpaY);
        const bCpaX = b.xM + b.vxM * tCpa;
        const bCpaY = b.yM + b.vyM * tCpa;
        const aCpaX = a.xM + a.vxM * tCpa;
        const aCpaY = a.yM + a.vyM * tCpa;

        const margin = b.priorityClass === 1 ? 22.0 : 14.0;
        const safeClearance = a.hullRadiusM + b.hullRadiusM + margin;

        if (cpaDist < safeClearance || curDist < safeClearance) {
          hasThreat = true;
          const ahead = rx * a.dirX + ry * a.dirY;
          // Tier 1: Longitudinal CPA speed yielding
          if (ahead > -b.hullRadiusM * 0.8) {
            const closeness = clamp(Math.min(cpaDist, curDist) / safeClearance, 0, 1);
            const yieldFactor = closeness < 0.72 ? 0.0 : (0.15 + 0.55 * ((closeness - 0.72) / 0.28));
            if (yieldFactor < desiredSpeedFactor) desiredSpeedFactor = yieldFactor;
          }

          // Tier 2: CPA-relative, incremental, water-mask-validated lateral avoidance
          const starX = a.dirY;
          const starY = -a.dirX;
          const cpaStar = (bCpaX - aCpaX) * starX + (bCpaY - aCpaY) * starY;
          const curStar = rx * starX + ry * starY;
          const refStar = Math.abs(cpaStar) > 1.0 ? cpaStar : curStar;
          const awaySign = refStar >= 0 ? -1 : 1;
          const dirOrder = [awaySign, -awaySign];
          const baseClear = Math.min(cpaDist, curDist);
          const deficit = Math.max(6.0, (safeClearance - baseClear) + 8.0);
          const stepFracs = [1.0, 0.6, 0.3];

          let chosenOff = a.latOffsetM;
          let bestScore = baseClear;
          for (let di = 0; di < dirOrder.length; di++) {
            const sign = dirOrder[di];
            for (let fi = 0; fi < stepFracs.length; fi++) {
              const candOff = clamp(a.latOffsetM + sign * deficit * stepFracs[fi], -48.0, 48.0);
              const dOff = candOff - a.latOffsetM;
              const candX = a.xM + starX * dOff;
              const candY = a.yM + starY * dOff;
              if (!isHullInWater(candX, candY, a.dirX, a.dirY, a.hullLengthM, a.hullBeamM, depthMgr)) continue;
              if (!isClearOfExclusions(candX, candY, a.hullRadiusM, a.kind)) continue;
              const candCurDist = Math.hypot(b.xM - candX, b.yM - candY);
              const candCpaDist = Math.hypot(bCpaX - (aCpaX + starX * dOff), bCpaY - (aCpaY + starY * dOff));
              const score = Math.min(candCurDist, candCpaDist);
              if (score > bestScore + 0.25) {
                bestScore = score;
                chosenOff = candOff;
                break; // Found best water-safe step in this direction
              }
            }
          }
          if (bestScore > baseClear + 0.25) {
            desiredLatM = chosenOff;
            urgentThreat = true;
          } else {
            holdOffset = true;
          }
        } else if (cpaDist < safeClearance + 14.0 || curDist < safeClearance + 14.0) {
          holdOffset = true;
        }
      }

      if (!hasThreat && holdOffset) {
        desiredLatM = a.latOffsetM;
      }

      // Static & swimmer exclusion zone avoidance
      for (let zi = 0; zi < EXCLUSION_ZONES.length; zi++) {
        const z = EXCLUSION_ZONES[zi];
        if (z.exemptKinds.includes(a.kind)) continue;
        const dx = a.xM - z.xM;
        const dy = a.yM - z.yM;
        const dist = Math.hypot(dx, dy);
        const minClear = z.radiusM + a.hullRadiusM + 4.0;
        if (dist < minClear) {
          const starX = a.dirY;
          const starY = -a.dirX;
          const pushSign = (dx * starX + dy * starY) >= 0 ? 1 : -1;
          const pushMag = (minClear - dist) + 4.0;
          const candOff = clamp(a.latOffsetM + pushSign * pushMag, -26.0, 26.0);
          const dOff = candOff - a.latOffsetM;
          const candX = a.xM + starX * dOff;
          const candY = a.yM + starY * dOff;
          if (isHullInWater(candX, candY, a.dirX, a.dirY, a.hullLengthM, a.hullBeamM, depthMgr)) {
            desiredLatM = candOff;
          }
        }
      }

      // Smoothly slew speedFactor and latOffsetM
      const speedSlew = desiredSpeedFactor < a.speedFactor ? 1.8 : 0.9;
      const sfDelta = desiredSpeedFactor - a.speedFactor;
      a.speedFactor += clamp(sfDelta, -speedSlew * dt, speedSlew * dt);
      a.speedFactor = clamp(a.speedFactor, 0.0, 1.0);

      // Lateral slew speed (SUPs strictly limited so total speed <= 1.8 m/s)
      const maxLatRate = a.kind === 'sup' ? 1.45 : (urgentThreat ? 2.8 : 1.5);
      const latDelta = desiredLatM - a.latOffsetM;
      const prevLat = a.latOffsetM;
      const nextLat = a.latOffsetM + clamp(latDelta, -maxLatRate * dt, maxLatRate * dt);
      const starX = a.dirY;
      const starY = -a.dirX;
      const testX = a.xM + starX * (nextLat - a.latOffsetM);
      const testY = a.yM + starY * (nextLat - a.latOffsetM);
      if (isHullInWater(testX, testY, a.dirX, a.dirY, a.hullLengthM, a.hullBeamM, depthMgr)) {
        a.latOffsetM = nextLat;
      }

      // Compute longitudinal speed (keeping SUP total ground speed <= 1.75 m/s)
      const latSpeedUsed = Math.abs(a.latOffsetM - prevLat) / Math.max(1e-4, dt);
      let lonSpeed = a.maxSpeedMps * a.speedFactor;
      if (a.kind === 'sup') {
        const maxLon = Math.sqrt(Math.max(0, 1.75 * 1.75 - latSpeedUsed * latSpeedUsed));
        lonSpeed = Math.min(lonSpeed, maxLon);
      }
      a.speedMps = lonSpeed;
      a.speedRatio = a.maxSpeedMps > 0 ? clamp(lonSpeed / a.maxSpeedMps, 0, 1) : 0;

      // Advance along route
      const dFrac = (lonSpeed * dt) / Math.max(1.0, a.routeLenM);
      if (a.schedule && a.schedule.mode === 'patrol') {
        a.frac += a.patrolDir * dFrac;
        if (a.frac >= 0.98) {
          a.frac = 0.98;
          a.patrolDir = -1;
          // Preserve world-space lateral position when starboard flips sign
          a.latOffsetM = -a.latOffsetM;
        } else if (a.frac <= 0.02) {
          a.frac = 0.02;
          a.patrolDir = 1;
          a.latOffsetM = -a.latOffsetM;
        }
      } else if (a.closed) {
        a.frac = (((a.frac + dFrac) % 1) + 1) % 1;
      } else {
        a.frac = (((a.frac + dFrac) % 1) + 1) % 1;
      }

      syncVesselGeometry(a, tCur);
    }

    // 3. Speed-capped post-step separation guard + pairwise clearance telemetry
    for (let i = 0; i < vessels.length; i++) {
      const a = vessels[i];
      if (!a.visible) continue;
      for (let j = i + 1; j < vessels.length; j++) {
        const b = vessels[j];
        if (!b.visible) continue;
        const dx = b.xM - a.xM;
        const dy = b.yM - a.yM;
        let dist = Math.hypot(dx, dy);
        const minHullSum = a.hullRadiusM + b.hullRadiusM;

        // If still closer than minHullSum + 2.5 m, gently push the yielding vessel laterally within its dt speed budget
        if (dist < minHullSum + 2.5) {
          const yielderIdx = shouldYield(a, b) ? i : j;
          const yielder = vessels[yielderIdx];
          const standOn = yielder === a ? b : a;
          const maxAllowedSpd = yielder.kind === 'sup' ? 1.75 : (yielder.maxSpeedMps + 2.8);
          const alreadyMoved = Math.hypot(yielder.xM - prevXM[yielderIdx], yielder.yM - prevYM[yielderIdx]);
          const maxExtra = Math.max(0, maxAllowedSpd * dt - alreadyMoved);
          const needed = Math.min((minHullSum + 6.0) - dist, maxExtra);
          if (needed > 1e-4) {
            const awayX = yielder.xM - standOn.xM;
            const awayY = yielder.yM - standOn.yM;
            const starX = yielder.dirY;
            const starY = -yielder.dirX;
            const pushSign = (awayX * starX + awayY * starY) >= 0 ? 1 : -1;
            const candLat = clamp(yielder.latOffsetM + pushSign * needed, -48.0, 48.0);
            const dLat = candLat - yielder.latOffsetM;
            const candX = yielder.xM + starX * dLat;
            const candY = yielder.yM + starY * dLat;
            if (isHullInWater(candX, candY, yielder.dirX, yielder.dirY, yielder.hullLengthM, yielder.hullBeamM, depthMgr)) {
              yielder.latOffsetM = candLat;
              syncVesselGeometry(yielder, tCur);
              dist = Math.hypot(b.xM - a.xM, b.yM - a.yM);
            }
          }
        }

        const clearance = dist - minHullSum;
        if (clearance < minPairwiseClearanceM) {
          minPairwiseClearanceM = clearance;
        }
        if (clearance <= 0) {
          collisionCount++;
        }
      }
    }

    // 4. Honest post-step SUP ground-speed telemetry (matches independent finite-difference)
    for (let i = 0; i < vessels.length; i++) {
      const v = vessels[i];
      if (!v.visible || v.kind !== 'sup') continue;
      const groundSpd = Math.hypot(v.xM - prevXM[i], v.yM - prevYM[i]) / Math.max(1e-4, dt);
      if (groundSpd > maxSupSpeedMps) maxSupSpeedMps = groundSpd;
    }
  }

  buildVesselList(specs);

  function updateToTime(tSec, mode = 'day', depthMgr = null, clockSnapshot = null, activeSpecs = specs) {
    // Rebuild if SpecRegistry vessels list changed (e.g. hot-injection)
    const specList = (activeSpecs && typeof activeSpecs.getVessels === 'function')
      ? activeSpecs.getVessels()
      : null;
    const nextKey = specList ? specList.map((s) => s.id).join('|') : 'default';
    if (nextKey !== specVersionKey) {
      specVersionKey = nextKey;
      buildVesselList(activeSpecs);
      lastTNorm = null;
    }

    const normMode = (mode === 'night' || mode === 'sunset') ? mode : 'day';
    const tNorm = normalizeTimeSec(tSec);

    if (lastTNorm !== null && normMode === lastMode && Math.abs(tNorm - lastTNorm) < 1e-6) {
      return;
    }

    const isLiveMode = !!(clockSnapshot && clockSnapshot.clockMode !== 'deterministic');
    const delta = (lastTNorm !== null && normMode === lastMode) ? (tNorm - lastTNorm) : -1;
    if (isLiveMode && lastTNorm !== null && normMode === lastMode && delta > 0) {
      let cur = lastTNorm;
      let rem = Math.min(delta, 0.10);
      while (rem > FIXED_DT) {
        cur += FIXED_DT;
        stepSim(FIXED_DT, cur, normMode, depthMgr);
        rem -= FIXED_DT;
      }
      if (rem > 1e-5) {
        stepSim(rem, cur + rem, normMode, depthMgr);
      }
    } else if (lastTNorm === null || normMode !== lastMode || delta < 0 || delta > 1.0) {
      // Cold-start, mode switch, or time jump: deterministic fixed-step replay
      // For large jumps (> 30 s), deterministically place vessels at tStart = tNorm - 30
      // and run 30 s of full stateful COLREGs avoidance so extreme timestamps stay < 15 ms.
      lastMode = normMode;
      resetState(normMode);
      const tStart = tNorm > 30.0 ? (tNorm - 30.0) : 0;
      if (tStart > 0) {
        for (let i = 0; i < vessels.length; i++) {
          const v = vessels[i];
          if (!v.visible || v.kind === 'zsg_steamer') continue;
          const distM = v.maxSpeedMps * tStart;
          const dFrac = distM / Math.max(1.0, v.routeLenM);
          if (v.schedule && v.schedule.mode === 'patrol') {
            const span = 0.96;
            const raw = (v.frac - 0.02) + v.patrolDir * dFrac;
            const cycle = ((raw % (2 * span)) + (2 * span)) % (2 * span);
            if (cycle <= span) {
              v.frac = 0.02 + cycle;
              v.patrolDir = 1;
            } else {
              v.frac = 0.98 - (cycle - span);
              v.patrolDir = -1;
            }
          } else {
            v.frac = (((v.frac + dFrac) % 1) + 1) % 1;
          }
          syncVesselGeometry(v, tStart);
        }
      }
      const warmDt = tStart > 0 ? 0.2 : FIXED_DT;
      let cur = tStart;
      while (cur + warmDt <= tNorm) {
        cur += warmDt;
        stepSim(warmDt, cur, normMode, depthMgr);
      }
      const rem = tNorm - cur;
      if (rem > 1e-5) {
        stepSim(rem, tNorm, normMode, depthMgr);
      }
    } else if (delta > 0) {
      let cur = lastTNorm;
      let rem = delta;
      while (rem > FIXED_DT) {
        cur += FIXED_DT;
        stepSim(FIXED_DT, cur, normMode, depthMgr);
        rem -= FIXED_DT;
      }
      if (rem > 1e-5) {
        stepSim(rem, tNorm, normMode, depthMgr);
      }
    }

    lastTNorm = tNorm;
    lastMode = normMode;

    for (let i = 0; i < vessels.length; i++) {
      if (vessels[i].visible) {
        updateRenderPts(vessels[i]);
      }
    }
  }

  function getVessels() {
    const active = [];
    for (let i = 0; i < vessels.length; i++) {
      if (vessels[i].visible) active.push(vessels[i]);
    }
    return active;
  }

  function getPierDockState(pierId = 'bendlikon') {
    for (let i = 0; i < vessels.length; i++) {
      const v = vessels[i];
      if (!v.visible || v.kind !== 'zsg_steamer') continue;
      if (v.pierId && v.pierId !== pierId) continue;
      return {
        docked: !!v.isDocked,
        dwellProg: v.dwellProg || 0,
        vesselId: v.isDocked || v.approaching ? v.id : null,
        approaching: !!v.approaching,
      };
    }
    return { docked: false, dwellProg: 0, vesselId: null, approaching: false };
  }

  function getTelemetry() {
    let activeVessels = 0;
    for (let i = 0; i < vessels.length; i++) {
      if (vessels[i].visible) activeVessels++;
    }
    return {
      activeVessels,
      minPairwiseClearanceM: Number((Number.isFinite(minPairwiseClearanceM) ? minPairwiseClearanceM : 999).toFixed(2)),
      collisionCount,
      maxSupSpeedMps: Number(maxSupSpeedMps.toFixed(3)),
    };
  }

  return {
    updateToTime,
    getVessels,
    getPierDockState,
    getTelemetry,
  };
}
