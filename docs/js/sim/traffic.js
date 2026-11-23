/**
 * Deterministic fixed-timestep (dt = 0.05 s) Kilchberg traffic, transit & cyclist simulation kernel (v14.0).
 *
 * Features:
 *   - 2D Spatial Hash Grid (16 m cells, ground-plane meters) across all vehicles, feeders, cyclists & pedestrians
 *   - Cross-lane shared-corridor IDM car-following & 2D bumper clearance clamp (zero overlaps on shared asphalt)
 *   - 6-Junction conflict-box reservation (`network.junctions`) + feeder-to-main junction yielding
 *   - Bidirectional crosswalk yielding (zero `minStopDist` skip blind spot)
 *   - 2D forward-cone pedestrian & cyclist braking for all non-motorway vehicles & feeder vans
 *   - Spec-driven ZVV buses (`BusRouteSpec` hot-injectable via `setBusRouteSpecs`)
 *   - True 2D OBB `overlapCount`, `clippingCount`, and `pedVehicleOverlapCount` telemetry
 *   - 100% deterministic seeded PRNG (zero Math.random()), backwards-compatible with T2.SM.03 standalone calls
 */

import { createRng } from './rng.js';
import { createSpatialGrid, metersToUv, uvToMeters } from './spatial.js';
import {
  evalBellState,
  evalBusScheduleState,
  evalShipState,
  evalTrainState,
  formatRoadName,
  getDiurnalProfile,
  getWindVector,
  samplePathAt,
} from './schedule.js';

export const FIXED_DT = 0.05; // 20 Hz fixed simulation step
const MAX_SIM_TIME = 1e9;

function clamp(v, lo, hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

function roadKindPriority(kind) {
  if (kind === 'seestrasse') return 3;
  if (kind === 'village') return 2;
  if (kind === 'viaduct') return 1;
  return 0;
}

function isVanColorIdx(colorIdx) {
  const isEmergency = (colorIdx % 29 === 17);
  const isPostVan = !isEmergency && (colorIdx % 11 === 4);
  const isLindtVan = !isEmergency && !isPostVan && (colorIdx % 13 === 7);
  const isMigrosVan = !isEmergency && !isPostVan && !isLindtVan && (colorIdx % 17 === 9);
  const isCoopVan = !isEmergency && !isPostVan && !isLindtVan && !isMigrosVan && (colorIdx % 19 === 11);
  const isCamper = !isEmergency && !isPostVan && !isLindtVan && !isMigrosVan && !isCoopVan && (colorIdx % 15 === 3);
  return isEmergency || isPostVan || isLindtVan || isMigrosVan || isCoopVan || isCamper;
}

function vehicleLabelForColor(colorIdx, roadName) {
  if (colorIdx % 29 === 17) {
    return (Math.floor(colorIdx / 29) % 2 === 1) ? 'Swiss Ambulance' : 'Feuerwehr Kilchberg';
  }
  if (colorIdx % 11 === 4) return 'Die Post Delivery Van';
  if (colorIdx % 13 === 7) return 'Lindt & Sprüngli Van';
  if (colorIdx % 17 === 9) return 'Migros Delivery Van';
  if (colorIdx % 19 === 11) return 'Coop Delivery Van';
  if (colorIdx % 15 === 3) return 'Alpine Camper';
  return roadName ? `Local Car · ${roadName}` : 'Local Car';
}

function closestFracOnPts(pts, targetU, targetV, masterW, masterH) {
  const n = pts ? pts.length : 0;
  if (n < 2) return { frac: 0, distPx: Infinity };
  let bestDist2 = Infinity;
  let bestFrac = 0;
  const tx = targetU * masterW;
  const ty = targetV * masterH;
  for (let i = 0; i < n - 1; i++) {
    const ax = pts[i][0] * masterW;
    const ay = pts[i][1] * masterH;
    const bx = pts[i + 1][0] * masterW;
    const by = pts[i + 1][1] * masterH;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    let t = 0;
    if (len2 > 1e-9) {
      t = clamp(((tx - ax) * dx + (ty - ay) * dy) / len2, 0, 1);
    }
    const px = ax + dx * t;
    const py = ay + dy * t;
    const d2 = (px - tx) * (px - tx) + (py - ty) * (py - ty);
    if (d2 < bestDist2) {
      bestDist2 = d2;
      bestFrac = (i + t) / (n - 1);
    }
  }
  return { frac: bestFrac, distPx: Math.sqrt(bestDist2) };
}

function activeBusCountForRoad(rd, busMode) {
  const base = rd.bus_count != null ? rd.bus_count : (rd.has_bus ? 1 : 0);
  if (base <= 0) return 0;
  if (busMode === 'night') return 1;
  if (busMode === 'sunset' && rd.kind === 'viaduct') return Math.min(1, base);
  return base;
}

const _tmpM0 = { xM: 0, yM: 0 };
const _tmpM1 = { xM: 0, yM: 0 };

function samplePtsMeters(pts, frac, invertDir, out) {
  const n = pts ? pts.length : 0;
  if (n < 2) return false;
  const f = clamp(frac, 0, 1);
  const fIdx = f * (n - 1);
  const i0 = Math.min(n - 2, Math.floor(fIdx));
  const t = fIdx - i0;
  const p0 = pts[i0];
  const p1 = pts[i0 + 1];
  const u = p0[0] + (p1[0] - p0[0]) * t;
  const v = p0[1] + (p1[1] - p0[1]) * t;
  uvToMeters(u, v, out);
  out.u = u;
  out.vCoord = v;

  const t0 = pts[Math.max(0, i0 - 1)];
  const t1 = pts[Math.min(n - 1, i0 + 2)];
  uvToMeters(t0[0], t0[1], _tmpM0);
  uvToMeters(t1[0], t1[1], _tmpM1);
  let dx = _tmpM1.xM - _tmpM0.xM;
  let dy = _tmpM1.yM - _tmpM0.yM;
  const mag = Math.hypot(dx, dy) || 1;
  dx /= mag;
  dy /= mag;
  if (invertDir) {
    dx = -dx;
    dy = -dy;
  }
  out.txM = dx;
  out.tyM = dy;
  return true;
}

/**
 * Check true 2D oriented bounding-box / capsule overlap between two vehicles in ground-plane meters.
 * Handles narrow opposing lanes cleanly (e.g. Dorfstrasse viaduct 1.26 m opposing separation)
 * while strictly catching all same-direction, cross-corridor, feeder, and junction T-bone overlaps.
 */
function checkVehicleOBBOverlap(a, b) {
  if (a.isMotorway !== b.isMotorway) return null; // Grade-separated A3 motorway
  const dx = b.xM - a.xM;
  const dy = b.yM - a.yM;
  const maxR = 0.5 * (a.lengthM + b.lengthM) + 2.5;
  if (dx * dx + dy * dy > maxR * maxR) return null;

  const dot = a.txM * b.txM + a.tyM * b.tyM;
  const fwdA = dx * a.txM + dy * a.tyM;
  const latA = Math.abs(-dx * a.tyM + dy * a.txM);

  // Opposing lanes on narrow roadways (e.g. horseshoe viaduct 1.26 m centerline separation)
  if (dot < -0.5) {
    const halfLenSum = 0.5 * (a.lengthM + b.lengthM) - 0.5;
    if (Math.abs(fwdA) < halfLenSum && latA < 0.85) {
      return { fwdA, latA, depth: halfLenSum - Math.abs(fwdA) };
    }
    return null;
  }

  // Same-direction or crossing/T-bone: SAT on both vehicle axes
  const halfLenA = 0.5 * a.lengthM;
  const halfLenB = 0.5 * b.lengthM;
  const halfWidA = 0.92;
  const halfWidB = 0.92;
  const absCos = Math.abs(dot);
  const absSin = Math.abs(a.txM * b.tyM - a.tyM * b.txM);

  // Project onto A's forward & lateral axes (exact zero-tolerance SAT)
  const rFwdA = halfLenA + halfLenB * absCos + halfWidB * absSin;
  if (Math.abs(fwdA) >= rFwdA) return null;
  const rLatA = halfWidA + halfLenB * absSin + halfWidB * absCos;
  if (latA >= rLatA) return null;

  // Project onto B's forward & lateral axes (exact zero-tolerance SAT)
  const fwdB = -dx * b.txM - dy * b.tyM;
  const latB = Math.abs(dx * b.tyM - dy * b.txM);
  const rFwdB = halfLenB + halfLenA * absCos + halfWidA * absSin;
  if (Math.abs(fwdB) >= rFwdB) return null;
  const rLatB = halfWidB + halfLenA * absSin + halfWidA * absCos;
  if (latB >= rLatB) return null;

  return { fwdA, latA, depth: Math.min(rFwdA - Math.abs(fwdA), rFwdB - Math.abs(fwdB)) };
}

export function createTrafficSim(animData) {
  const masterW = (animData && animData.canvas_width) ? animData.canvas_width : 28024;
  const masterH = (animData && animData.canvas_height) ? animData.canvas_height : 12373;
  const mppMaster = (animData && typeof animData.mpp === 'number') ? animData.mpp : 0.11;
  const resFactor = 0.25 / mppMaster;
  const roads = (animData && Array.isArray(animData.roads)) ? animData.roads : [];
  const trains = (animData && Array.isArray(animData.trains)) ? animData.trains : [];
  const ships = (animData && Array.isArray(animData.ships)) ? animData.ships : [];
  const network = (animData && animData.network) ? animData.network : {};
  const rawCrosswalks = Array.isArray(network.crosswalks) ? network.crosswalks : [];
  const rawFeeders = Array.isArray(network.feeders) ? network.feeders : [];
  const rawJunctions = Array.isArray(network.junctions) ? network.junctions : [];

  const roadById = new Map();
  roads.forEach((rd, idx) => roadById.set(rd.id, { rd, idx }));

  // Pre-bind every crosswalk to ALL non-motorway lanes passing within < 34 ref px
  // (guarantees bidirectional coverage on both opposing lanes + shared lakefront corridor)
  const laneCrosswalks = new Map(); // roadId -> Array<{ cwIdx, cwId, sM, frac }>
  roads.forEach((rd) => laneCrosswalks.set(rd.id, []));

  const crosswalkDefs = rawCrosswalks.map((cw, cwIdx) => {
    const bindings = [];
    for (const rd of roads) {
      if (rd.kind === 'motorway') continue;
      const proj = closestFracOnPts(rd.pts, cw.u, cw.v, masterW, masterH);
      if (proj.distPx < 34.0 * resFactor) {
        const sM = proj.frac * rd.length_m;
        const binding = { cwIdx, cwId: cw.id, roadId: rd.id, frac: proj.frac, sM };
        bindings.push(binding);
        laneCrosswalks.get(rd.id).push(binding);
      }
    }
    const mPos = uvToMeters(cw.u, cw.v);
    return {
      idx: cwIdx,
      id: cw.id,
      name: cw.name || cw.id,
      u: cw.u,
      v: cw.v,
      xM: mPos.xM,
      yM: mPos.yM,
      d16: cw.d16 || 0,
      nx: Number.isFinite(cw.nx) ? cw.nx : 0.707,
      ny: Number.isFinite(cw.ny) ? cw.ny : 0.707,
      bindings,
      period: 16.0 + (cwIdx % 4) * 1.8 + Math.floor(cwIdx / 4) * 0.9,
      phaseOffset: (cwIdx * 3.17) % 16.0,
    };
  });

  // Pre-bind all 6 network junctions (`network.junctions`) with priority ranks
  const laneJunctions = new Map(); // roadId -> Array<{ juncIdx, sM, priority, roadKind }>
  roads.forEach((rd) => laneJunctions.set(rd.id, []));

  const junctionDefs = rawJunctions.map((jc, jIdx) => {
    const mPos = uvToMeters(jc.u, jc.v);
    const links = [];
    const rawLinks = Array.isArray(jc.links) ? jc.links : [];
    for (let i = 0; i < rawLinks.length; i++) {
      const lk = rawLinks[i];
      const info = roadById.get(lk.road_id);
      if (!info || info.rd.kind === 'motorway') continue;
      const sM = clamp(lk.frac || 0, 0, 1) * info.rd.length_m;
      const priority = roadKindPriority(info.rd.kind);
      const entry = {
        juncIdx: jIdx,
        roadId: lk.road_id,
        roadKind: info.rd.kind,
        frac: lk.frac,
        sM,
        priority,
      };
      links.push(entry);
      laneJunctions.get(lk.road_id).push(entry);
    }
    return {
      idx: jIdx,
      id: jc.id,
      name: jc.name || jc.id,
      u: jc.u,
      v: jc.v,
      xM: mPos.xM,
      yM: mPos.yM,
      links,
      // Runtime conflict-box reservation state
      holderId: null,
      holderRoadId: null,
      holderRoadKind: null,
      holderTxM: 0,
      holderTyM: 0,
      holderXM: 0,
      holderYM: 0,
      holdTime: 0,
    };
  });

  // Pre-compute feeder entry ends & main-road connection points in ground-plane meters
  const feederDefs = rawFeeders.map((fd, idx) => {
    const pts = fd.pts || [];
    let entryAtStart = true;
    let connXM = 0;
    let connYM = 0;
    const conn = roadById.get(fd.connects_road);
    if (conn && pts.length >= 2) {
      const roadPt = samplePathAt(conn.rd.pts, clamp(fd.connects_frac || 0, 0, 1), masterW, masterH, 2);
      if (roadPt) {
        const dStart = Math.hypot(pts[0][0] * masterW - roadPt.wx, pts[0][1] * masterH - roadPt.wy);
        const dEnd = Math.hypot(pts[pts.length - 1][0] * masterW - roadPt.wx, pts[pts.length - 1][1] * masterH - roadPt.wy);
        entryAtStart = dStart <= dEnd;
        const cm = uvToMeters(roadPt.wx / masterW, roadPt.wy / masterH);
        connXM = cm.xM;
        connYM = cm.yM;
      }
    }
    return {
      idx,
      id: fd.id,
      name: fd.name || fd.id,
      kind: fd.kind || 'residential',
      lengthM: Math.max(25, fd.length_m || 80),
      pts,
      connectsRoad: fd.connects_road,
      connectsFrac: fd.connects_frac || 0,
      connXM,
      connYM,
      poiId: fd.poi_id || null,
      entryAtStart,
    };
  });

  // 2D Spatial Hash Grid (16 m cells, zero-allocation steady-state)
  const spatialGrid = createSpatialGrid(16);
  const queryBuf = [];

  // Simulation runtime state
  let initialized = false;
  let currentMode = 'day';
  let simTime = 0;
  let subStepRem = 0;
  let lastTargetT = 0;
  let lanes = [];
  let laneById = new Map();
  let feederVehicles = [];
  let cyclists = [];
  let crosswalkStates = [];
  let dwellingStops = new Set();

  // Optional v14 Spec & External Hooks
  let busRouteSpecs = null; // Array<BusRouteSpec> | null
  let useExternalCrosswalks = false;
  const externalCrosswalkMap = new Map();
  let externalPedStats = null;
  let externalPedestrians = null; // Array<{ id, u, v, state, onElevatedDeck }>

  // Cached telemetry updated after every step / query
  let stats = {
    vehicles: 0,
    brakingCount: 0,
    yieldingCount: 0,
    pedestrians: 0,
    boardingCount: 0,
    activeTrips: 0,
    bellPhase: 0,
    minBusGapM: 999,
    clippingCount: 0,
    overlapCount: 0,
    pedVehicleOverlapCount: 0,
    cyclists: 0,
  };

  function computeBaselinePedestrianCount(mode) {
    const profile = getDiurnalProfile(mode);
    const nonMotorwayCount = roads.filter((r) => r.kind !== 'motorway').length;
    const sidewalkBase = Math.round((nonMotorwayCount * 10 + 12) * profile.pedFactor);
    const stopBase = mode === 'night' ? 6 : (mode === 'sunset' ? 14 : 18);
    let cwWalkers = 0;
    for (let i = 0; i < crosswalkStates.length; i++) {
      if (crosswalkStates[i].occupied) cwWalkers += crosswalkStates[i].walkerCount || 1;
    }
    return Math.max(mode === 'night' ? 10 : 40, sidewalkBase + stopBase + cwWalkers);
  }

  function updateVehicleMeters(v, rd) {
    const L = rd.length_m;
    const frac = (((v.s % L) + L) % L) / L;
    samplePtsMeters(rd.pts, frac, false, v);
  }

  function updateFeederMeters(fv) {
    const fd = feederDefs[fv.feederIdx];
    if (!fd || fd.pts.length < 2) return;
    const rawFrac = fd.entryAtStart ? fv.distFrac : (1.0 - fv.distFrac);
    const movingInc = (fv.state === 'outbound_feeder' || fv.state === 'curb_pause')
      ? fd.entryAtStart
      : !fd.entryAtStart;
    samplePtsMeters(fd.pts, clamp(rawFrac, 0.01, 0.99), !movingInc, fv);
  }

  function updateCyclistMeters(cyc, rd) {
    const L = rd.length_m;
    const frac = (((cyc.s % L) + L) % L) / L;
    samplePtsMeters(rd.pts, frac, false, cyc);
    // Offset cyclists onto right-hand Swiss bike-lane shoulder (starboard normal: tyM, -txM)
    const shoulderM = (rd.kind === 'seestrasse' ? 1.85 : 1.75) + (cyc.latOffset || 0) * 0.25;
    cyc.xM += cyc.tyM * shoulderM;
    cyc.yM -= cyc.txM * shoulderM;
  }

  function rebuildSpatialGrid(includePedsAndCyclists) {
    spatialGrid.clear();
    for (let li = 0; li < lanes.length; li++) {
      const lane = lanes[li];
      const vehs = lane.vehicles;
      for (let i = 0; i < vehs.length; i++) {
        const v = vehs[i];
        spatialGrid.insert(v.id, v.xM, v.yM, 0.5 * v.lengthM + 1.5, 'veh', v);
      }
    }
    for (let i = 0; i < feederVehicles.length; i++) {
      const fv = feederVehicles[i];
      spatialGrid.insert(fv.id, fv.xM, fv.yM, 0.5 * fv.lengthM + 1.5, 'veh', fv);
    }
    if (includePedsAndCyclists) {
      for (let i = 0; i < cyclists.length; i++) {
        const cyc = cyclists[i];
        spatialGrid.insert(cyc.id, cyc.xM, cyc.yM, 1.0, 'cyclist', cyc);
      }
      if (Array.isArray(externalPedestrians)) {
        for (let i = 0; i < externalPedestrians.length; i++) {
          const p = externalPedestrians[i];
          if (!p || p.onElevatedDeck) continue;
          if (
            p.state === 'in_transit' || p.state === 'boarding' || p.state === 'alighting'
            || p.state === 'queue_rail' || p.state === 'walk_footbridge'
            || p.state === 'queue_pier' || p.state === 'walk_pier_deck' || p.state === 'walk_gangplank'
          ) {
            continue;
          }
          const pm = uvToMeters(p.u, p.v);
          spatialGrid.insert(p.id, pm.xM, pm.yM, 0.65, 'ped', { id: p.id, xM: pm.xM, yM: pm.yM, state: p.state });
        }
      } else if (!useExternalCrosswalks) {
        for (let i = 0; i < crosswalkDefs.length; i++) {
          const def = crosswalkDefs[i];
          const st = crosswalkStates[i];
          if (!st || !st.occupied) continue;
          spatialGrid.insert(`cw_ped:${def.id}`, def.xM, def.yM, 1.2, 'ped', { id: `cw_ped:${def.id}`, xM: def.xM, yM: def.yM, state: 'crossing_cw' });
        }
      }
    }
  }

  function makeBusEntity(rd, laneStopsM, bIdx, activeBuses, tStart, profile, spec) {
    const isArtic = spec
      ? (spec.vehicleType === 'bus_artic')
      : (rd.kind === 'seestrasse');
    const routeNum = (spec && spec.line) ? String(spec.line) : (rd.kind === 'seestrasse' ? '161' : '165');
    const schedSt = evalBusScheduleState(rd, bIdx, tStart, Math.max(1, activeBuses));
    const startFrac = (schedSt.frac >= 0.01 && schedSt.frac <= 0.99)
      ? schedSt.frac
      : (((rd.phase || 0) + bIdx / Math.max(1, activeBuses)) % 1 + 1) % 1;
    const startS = clamp(startFrac * rd.length_m, 10, rd.length_m - 10);
    const vFree = Math.max(2.0, rd.speed_mps * 0.88 * profile.speedFactor);

    let stopsM = laneStopsM;
    if (spec && Array.isArray(spec.stops) && spec.stops.length > 0) {
      const specStops = spec.stops
        .filter((st) => (!st.roadId || st.roadId === rd.id) && typeof st.frac === 'number' && st.frac > 0.01 && st.frac < 0.99)
        .map((st, sIdx) => ({
          idx: sIdx,
          frac: st.frac,
          sM: st.frac * rd.length_m,
          dwellSec: (typeof st.dwellSec === 'number' && st.dwellSec > 0) ? Math.min(6.5, st.dwellSec) : 3.2,
        }))
        .sort((a, b) => a.sM - b.sM);
      if (specStops.length > 0) stopsM = specStops;
    }

    let nextStopIdx = 0;
    for (let k = 0; k < stopsM.length; k++) {
      if (stopsM[k].sM > startS + 2.0) {
        nextStopIdx = k;
        break;
      }
      if (k === stopsM.length - 1) nextStopIdx = 0;
    }

    const busLabel = (spec && spec.name)
      ? (spec.name.includes('ZVV') ? spec.name : `ZVV Bus ${routeNum} · ${spec.name}`)
      : `ZVV Bus ${routeNum} · ${formatRoadName(rd)}`;

    const veh = {
      id: spec ? `bus:${spec.id}:${bIdx}` : `bus:${rd.id}:${bIdx}`,
      specId: spec ? spec.id : null,
      specSig: spec ? busRouteSpecSignature(spec) : null,
      kind: isArtic ? 'bus_artic' : 'bus',
      routeNum,
      busIdx: bIdx,
      roadId: rd.id,
      roadKind: rd.kind,
      priority: roadKindPriority(rd.kind),
      isMotorway: rd.kind === 'motorway',
      isFeeder: false,
      s: startS,
      v: schedSt.isDwelling ? 0 : vFree * Math.max(0.2, schedSt.speedRatio),
      a: 0,
      v0: vFree,
      lengthM: isArtic ? 19.0 : 12.0,
      aMax: isArtic ? 1.3 : 1.4,
      bComf: isArtic ? 2.4 : 2.5,
      bEmerg: 5.8,
      s0: isArtic ? 8.5 : 8.0,
      T: 1.5,
      stopsM,
      nextStopIdx,
      dwellTimer: schedSt.isDwelling ? Math.max(0.4, 3.2 * (1 - schedSt.dwellProgress)) : 0,
      departBlinkerTimer: 0,
      stopCooldown: 0,
      isDwelling: schedSt.isDwelling,
      dwellingStopIdx: schedSt.isDwelling ? schedSt.stopIdx : -1,
      pullInFrac: schedSt.isDwelling ? 1.0 : (1.0 - schedSt.speedRatio),
      braking: schedSt.isDwelling,
      yielding: false,
      blinker: schedSt.isDwelling ? 'hazard' : 'none',
      headlightDim: 1.0,
      tripLabel: busLabel,
      xM: 0,
      yM: 0,
      txM: 1,
      tyM: 0,
      u: 0.5,
      vCoord: 0.5,
      _pedHardStop: false,
    };
    updateVehicleMeters(veh, rd);
    return veh;
  }

  function findClearSOnLane(lane, desiredS, lengthM) {
    const L = lane.rd.length_m;
    let s = ((desiredS % L) + L) % L;
    const minNeed = lane.isMotorway ? 14.0 : 9.0;
    for (let tries = 0; tries < 24; tries++) {
      let conflict = false;
      for (let i = 0; i < lane.vehicles.length; i++) {
        const other = lane.vehicles[i];
        let d = Math.abs(s - other.s);
        d = Math.min(d, L - d);
        if (d < 0.5 * (lengthM + other.lengthM) + minNeed) {
          s = (s + 0.5 * (lengthM + other.lengthM) + minNeed + 4.0) % L;
          conflict = true;
          break;
        }
      }
      if (!conflict) break;
    }
    return s;
  }

  function resolve2DOverlapsPostStep() {
    for (let pass = 0; pass < 4; pass++) {
      // Refresh positions
      for (let li = 0; li < lanes.length; li++) {
        const lane = lanes[li];
        if (lane.isMotorway) continue;
        for (let i = 0; i < lane.vehicles.length; i++) {
          updateVehicleMeters(lane.vehicles[i], lane.rd);
        }
      }
      for (let i = 0; i < feederVehicles.length; i++) {
        updateFeederMeters(feederVehicles[i]);
      }
      rebuildSpatialGrid(false);

      let anyPushed = false;
      for (let li = 0; li < lanes.length; li++) {
        const lane = lanes[li];
        if (lane.isMotorway) continue;
        const L = lane.rd.length_m;
        const vehs = lane.vehicles;
        for (let i = 0; i < vehs.length; i++) {
          const me = vehs[i];
          spatialGrid.queryRadius(me.xM, me.yM, me.lengthM + 12.0, 'veh', queryBuf);
          for (let q = 0; q < queryBuf.length; q++) {
            const other = queryBuf[q].data;
            if (!other || other === me || other.roadId === me.roadId || other.isMotorway) continue;
            const ov = checkVehicleOBBOverlap(me, other);
            if (!ov) continue;

            // Decide which vehicle should back up:
            // 1. If other is a feeder van, feeder yields (not main road) unless me is behind feeder
            // 2. If other is ahead of me (fwdA > 0.2), me backs up
            // 3. Otherwise lower priority (or tie-break by id) backs up
            let meShouldBackUp = false;
            if (other.isFeeder) {
              meShouldBackUp = false;
            } else if (ov.fwdA > 0.25) {
              meShouldBackUp = true;
            } else if (ov.fwdA < -0.25) {
              meShouldBackUp = false;
            } else if (me.priority !== other.priority) {
              meShouldBackUp = me.priority < other.priority;
            } else {
              meShouldBackUp = me.id > other.id;
            }

            if (meShouldBackUp) {
              const pushM = Math.max(1.5, ov.depth + 1.25);
              me.s = (((me.s - pushM) % L) + L) % L;
              me.v = Math.min(me.v, other.v * 0.6);
              if (me.v < 0.1) me.v = 0;
              me.yielding = true;
              me.braking = true;
              updateVehicleMeters(me, lane.rd);
              anyPushed = true;
            }
          }
        }
      }

      // Re-enforce 1D same-lane bumper clearance if any vehicle was pushed back
      if (anyPushed) {
        for (let li = 0; li < lanes.length; li++) {
          const lane = lanes[li];
          if (lane.isMotorway || lane.vehicles.length < 2) continue;
          const L = lane.rd.length_m;
          const vehs = lane.vehicles;
          vehs.sort((a, b) => a.s - b.s);
          const N = vehs.length;
          for (let i = N - 1; i >= 0; i--) {
            const me = vehs[i];
            const j = (i + 1) % N;
            const leader = vehs[j];
            const rawDs = j > i ? (leader.s - me.s) : (L - me.s + leader.s);
            const minCenter = 0.5 * (leader.lengthM + me.lengthM) + 2.5;
            if (rawDs < minCenter) {
              me.s = (((me.s - (minCenter - rawDs)) % L) + L) % L;
              me.v = Math.min(me.v, leader.v * 0.8);
              if (me.v < 0.1) me.v = 0;
              updateVehicleMeters(me, lane.rd);
            }
          }
        }
      }

      // Feeder van 2D clearance clamp (against other vehicles AND pedestrians)
      rebuildSpatialGrid(true);
      for (let i = 0; i < feederVehicles.length; i++) {
        const fv = feederVehicles[i];
        const fd = feederDefs[fv.feederIdx];
        if (!fd) continue;
        spatialGrid.queryRadius(fv.xM, fv.yM, 14.0, 'veh', queryBuf);
        for (let q = 0; q < queryBuf.length; q++) {
          const other = queryBuf[q].data;
          if (!other || other === fv || other.isMotorway) continue;
          const ov = checkVehicleOBBOverlap(fv, other);
          if (!ov) continue;
          const pushFrac = Math.max(0.03, (ov.depth + 1.5) / Math.max(25, fd.lengthM));
          const minFeederFrac = Math.max(0.08, 8.5 / Math.max(25, fd.lengthM));
          fv.distFrac = clamp(fv.distFrac + pushFrac, minFeederFrac, 0.92);
          fv.v = 0;
          fv.braking = true;
          fv.yielding = true;
          updateFeederMeters(fv);
          anyPushed = true;
        }
        spatialGrid.queryRadius(fv.xM, fv.yM, 0.5 * fv.lengthM + 2.2, 'ped', queryBuf);
        for (let q = 0; q < queryBuf.length; q++) {
          const ped = queryBuf[q].data;
          if (!ped) continue;
          const dx = ped.xM - fv.xM;
          const dy = ped.yM - fv.yM;
          const fwd = dx * fv.txM + dy * fv.tyM;
          const lat = Math.abs(-dx * fv.tyM + dy * fv.txM);
          if (Math.abs(fwd) < 0.5 * fv.lengthM + 0.5 && lat < 1.35) {
            const origFrac = fv.distFrac;
            const stepM = 0.5 * fv.lengthM + Math.abs(fwd) + 1.8;
            const deltaFrac = stepM / Math.max(15, fd.lengthM);
            const minFeederFrac = Math.max(0.08, 8.5 / Math.max(25, fd.lengthM));
            // Prefer backing away from the main-road junction (+deltaFrac, +2*deltaFrac) before moving toward it (-deltaFrac)
            const cands = [
              clamp(origFrac + deltaFrac, minFeederFrac, 0.92),
              clamp(origFrac + 2 * deltaFrac, minFeederFrac, 0.92),
              clamp(origFrac - deltaFrac, minFeederFrac, 0.92),
              clamp(origFrac - 2 * deltaFrac, minFeederFrac, 0.92),
            ];
            let bestFrac = cands[0];
            let bestClear = false;
            for (let ci = 0; ci < cands.length; ci++) {
              fv.distFrac = cands[ci];
              updateFeederMeters(fv);
              let allClear = true;
              for (let pq = 0; pq < queryBuf.length; pq++) {
                const otherPed = queryBuf[pq].data;
                if (!otherPed) continue;
                const cdx = otherPed.xM - fv.xM;
                const cdy = otherPed.yM - fv.yM;
                const cfwd = Math.abs(cdx * fv.txM + cdy * fv.tyM);
                const clat = Math.abs(-cdx * fv.tyM + cdy * fv.txM);
                if (cfwd < 0.5 * fv.lengthM + 0.5 && clat < 1.35) {
                  allClear = false;
                  break;
                }
              }
              if (allClear) {
                bestFrac = cands[ci];
                bestClear = true;
                break;
              }
            }
            fv.distFrac = bestClear ? bestFrac : cands[0];
            fv.v = 0;
            fv.braking = true;
            fv.yielding = true;
            updateFeederMeters(fv);
            anyPushed = true;
            break;
          }
        }
      }

      // Main-lane 2D pedestrian clearance guard (prevents transient wrap/push-back overlaps)
      for (let li = 0; li < lanes.length; li++) {
        const lane = lanes[li];
        if (lane.isMotorway) continue;
        const L = lane.rd.length_m;
        const vehs = lane.vehicles;
        for (let i = 0; i < vehs.length; i++) {
          const me = vehs[i];
          spatialGrid.queryRadius(me.xM, me.yM, 0.5 * me.lengthM + 2.0, 'ped', queryBuf);
          for (let q = 0; q < queryBuf.length; q++) {
            const ped = queryBuf[q].data;
            if (!ped) continue;
            const dx = ped.xM - me.xM;
            const dy = ped.yM - me.yM;
            const fwd = dx * me.txM + dy * me.tyM;
            const lat = Math.abs(-dx * me.tyM + dy * me.txM);
            if (Math.abs(fwd) < 0.5 * me.lengthM + 0.15 && lat < 0.98) {
              if (fwd >= 0) {
                const backM = (0.5 * me.lengthM + 0.35) - fwd;
                me.s = (((me.s - backM) % L) + L) % L;
              } else {
                const fwdM = (0.5 * me.lengthM + 0.35) + fwd;
                me.s = (((me.s + fwdM) % L) + L) % L;
              }
              me.v = 0;
              me.braking = true;
              me.yielding = true;
              updateVehicleMeters(me, lane.rd);
              anyPushed = true;
              break;
            }
          }
        }
      }

      if (!anyPushed) break;

      // Re-enforce 1D same-lane non-overlap clamp after any 2D push-back
      for (let li = 0; li < lanes.length; li++) {
        const lane = lanes[li];
        if (lane.isMotorway) continue;
        const L = lane.rd.length_m;
        const vehs = lane.vehicles;
        const N = vehs.length;
        if (N <= 1) continue;
        vehs.sort((a, b) => a.s - b.s);
        const minHardGap = 4.5;
        for (let i = N - 1; i >= 0; i--) {
          const me = vehs[i];
          const j = (i + 1) % N;
          const leader = vehs[j];
          const rawDs = j > i ? (leader.s - me.s) : (L - me.s + leader.s);
          const minCenter = 0.5 * (leader.lengthM + me.lengthM) + minHardGap;
          if (rawDs < minCenter) {
            me.s = (((me.s - (minCenter - rawDs)) % L) + L) % L;
            me.v = Math.min(me.v, leader.v * 0.9);
            if (me.v < 0.05) me.v = 0;
          }
        }
        vehs.sort((a, b) => a.s - b.s);
      }
    }
  }

  function resetState(mode, tStart) {
    currentMode = mode;
    simTime = tStart;
    subStepRem = 0;
    const profile = getDiurnalProfile(mode);
    const rootRng = createRng(`kilchberg-sim-v8:${mode}:${Math.round(tStart * 100)}`);

    for (let i = 0; i < junctionDefs.length; i++) {
      junctionDefs[i].holderId = null;
      junctionDefs[i].holderRoadId = null;
      junctionDefs[i].holderRoadKind = null;
      junctionDefs[i].holdTime = 0;
    }

    crosswalkStates = crosswalkDefs.map((cw) => ({
      id: cw.id,
      occupied: false,
      progress: 0,
      walkerCount: 1,
      dir: (cw.idx % 2 === 0) ? 1 : -1,
    }));

    // Group busRouteSpecs by resolved roadId (scanning all corridorSegments + graceful fallback)
    const specsByRoad = new Map();
    if (Array.isArray(busRouteSpecs) && busRouteSpecs.length > 0) {
      const defaultRoad = roadById.has('seestrasse_sb')
        ? 'seestrasse_sb'
        : ((roads.find((r) => r.kind !== 'motorway' && activeBusCountForRoad(r, 'day') > 0) || roads.find((r) => r.kind !== 'motorway') || roads[0] || {}).id || null);
      for (let i = 0; i < busRouteSpecs.length; i++) {
        const sp = busRouteSpecs[i];
        let targetRoadId = null;
        if (Array.isArray(sp.corridorSegments)) {
          for (let si = 0; si < sp.corridorSegments.length; si++) {
            const seg = sp.corridorSegments[si];
            if (seg && seg.roadId && roadById.has(seg.roadId)) {
              targetRoadId = seg.roadId;
              break;
            }
          }
        }
        if (!targetRoadId) targetRoadId = defaultRoad;
        if (!targetRoadId) continue;
        if (!specsByRoad.has(targetRoadId)) specsByRoad.set(targetRoadId, []);
        specsByRoad.get(targetRoadId).push(sp);
      }
    }

    laneById = new Map();
    lanes = roads.map((rd, rIdx) => {
      const laneRng = rootRng.fork(`lane:${rd.id}`);
      const isMotorway = rd.kind === 'motorway';
      const isLine161 = rd.kind === 'seestrasse';
      const rawCars = rd.car_count || 4;
      const activeCars = Math.max(
        isMotorway ? 4 : 2,
        Math.round(rawCars * profile.carFactor),
      );
      const stopsM = (rd.stops || [])
        .filter((f) => typeof f === 'number' && f > 0.01 && f < 0.99)
        .map((f, sIdx) => ({ idx: sIdx, frac: f, sM: f * rd.length_m, dwellSec: 3.2 }))
        .sort((a, b) => a.sM - b.sM);

      const vehicles = [];
      const laneObj = {
        rd,
        rIdx,
        isMotorway,
        isLine161,
        priority: roadKindPriority(rd.kind),
        stopsM,
        crosswalks: laneCrosswalks.get(rd.id) || [],
        junctions: laneJunctions.get(rd.id) || [],
        vehicles,
      };

      // 1. Seed ZVV buses (spec-driven if busRouteSpecs is active, else legacy animData.roads)
      if (Array.isArray(busRouteSpecs) && busRouteSpecs.length > 0) {
        const rSpecs = specsByRoad.get(rd.id) || [];
        for (let si = 0; si < rSpecs.length; si++) {
          const sp = rSpecs[si];
          const tt = sp.timetable || {};
          if (profile.busMode === 'night' && tt.nightActive === false) continue;
          const nBuses = activeBusCountForRoad(rd, profile.busMode) || 1;
          for (let bIdx = 0; bIdx < nBuses; bIdx++) {
            const bus = makeBusEntity(rd, stopsM, bIdx, nBuses, tStart, profile, sp);
            bus.s = findClearSOnLane(laneObj, bus.s, bus.lengthM);
            updateVehicleMeters(bus, rd);
            vehicles.push(bus);
          }
        }
      } else {
        const activeBuses = activeBusCountForRoad(rd, profile.busMode);
        for (let bIdx = 0; bIdx < activeBuses; bIdx++) {
          const bus = makeBusEntity(rd, stopsM, bIdx, activeBuses, tStart, profile, null);
          vehicles.push(bus);
        }
      }

      // 2. Seed cars & vans with guaranteed safe initial spacing around buses
      const spacing = rd.length_m / Math.max(1, activeCars);
      const busCountOnLane = vehicles.length;
      for (let cIdx = 0; cIdx < activeCars; cIdx++) {
        const colorIdx = (busCountOnLane + cIdx) + rIdx * 3;
        const isVan = isVanColorIdx(colorIdx);
        const lenM = isVan ? 5.8 : 4.6;
        const jitterM = laneRng.range(-spacing * 0.22, spacing * 0.22);
        let s = (((((rd.phase || 0) * rd.length_m) + (cIdx + 0.35) * spacing + jitterM) % rd.length_m) + rd.length_m) % rd.length_m;
        s = findClearSOnLane(laneObj, s, lenM);

        const speedVar = laneRng.range(0.88, 1.08);
        const baseRoadSpeed = rd.speed_mps * (busCountOnLane > 0 ? 0.90 : 0.98);
        const v0 = Math.max(3.5, baseRoadSpeed * speedVar * profile.speedFactor);
        const car = {
          id: `car:${rd.id}:${cIdx}`,
          kind: isVan ? 'van' : 'car',
          colorIdx,
          roadId: rd.id,
          roadKind: rd.kind,
          priority: roadKindPriority(rd.kind),
          isMotorway,
          isFeeder: false,
          s,
          v: v0 * 0.82,
          a: 0,
          v0,
          lengthM: lenM,
          aMax: isVan ? 1.9 : 2.1,
          bComf: 2.8,
          bEmerg: 6.5,
          s0: isMotorway ? 18.0 : 8.0,
          T: isMotorway ? 1.6 : 1.4,
          isDwelling: false,
          braking: false,
          yielding: false,
          blinker: 'none',
          headlightDim: 1.0,
          tripLabel: vehicleLabelForColor(colorIdx, formatRoadName(rd)),
          xM: 0,
          yM: 0,
          txM: 1,
          tyM: 0,
          u: 0.5,
          vCoord: 0.5,
          _pedHardStop: false,
        };
        updateVehicleMeters(car, rd);
        vehicles.push(car);
      }

      vehicles.sort((a, b) => a.s - b.s);
      laneById.set(rd.id, laneObj);
      return laneObj;
    });

    // 3. Seed feeder-street local trips & Swiss delivery vans
    feederVehicles = [];
    if (feederDefs.length > 0) {
      const fRng = rootRng.fork('feeders');
      const nFeed = Math.min(profile.feederCount, feederDefs.length);
      const schoorenIdx = feederDefs.findIndex((f) => f.id === 'feeder_schoorenstrasse');
      const assignedFeeders = [];
      if (schoorenIdx >= 0) assignedFeeders.push(schoorenIdx);
      for (let i = 0; i < feederDefs.length && assignedFeeders.length < nFeed; i++) {
        if (!assignedFeeders.includes(i)) assignedFeeders.push(i);
      }
      const deliveryColors = [7, 4, 9, 11, 0, 2];
      const nightColors = [0, 2, 5, 6];

      for (let i = 0; i < assignedFeeders.length; i++) {
        const fIdx = assignedFeeders[i];
        const fd = feederDefs[fIdx];
        const colorIdx = profile.deliveryActive
          ? deliveryColors[i % deliveryColors.length]
          : nightColors[i % nightColors.length];
        const curbFrac = fRng.range(0.48, 0.80);
        const startPhase = fRng.next();
        let state = 'outbound_feeder';
        let distFrac = 0.10;
        let timer = 0;
        if (startPhase < 0.35) {
          state = 'outbound_feeder';
          distFrac = fRng.range(0.10, curbFrac * 0.9);
        } else if (startPhase < 0.65) {
          state = 'curb_pause';
          distFrac = curbFrac;
          timer = fRng.range(2.0, 8.0);
        } else if (startPhase < 0.90) {
          state = 'inbound_feeder';
          distFrac = fRng.range(0.14, curbFrac);
        } else {
          state = 'junction_wait';
          distFrac = 0.08;
          timer = fRng.range(0.6, 2.2);
        }
        const fv = {
          id: `feeder:${fd.id}:${i}`,
          feederIdx: fIdx,
          roadId: fd.id,
          roadKind: 'feeder',
          priority: 0,
          isMotorway: false,
          isFeeder: true,
          lengthM: 5.4,
          colorIdx,
          state,
          distFrac,
          curbFrac,
          timer,
          waitElapsed: 0,
          speedMps: 5.6 * profile.speedFactor,
          v: (state === 'curb_pause' || state === 'junction_wait') ? 0 : 5.6 * profile.speedFactor,
          braking: (state === 'curb_pause' || state === 'junction_wait'),
          yielding: state === 'junction_wait',
          blinker: state === 'curb_pause' ? 'hazard' : 'none',
          headlightDim: 1.0,
          tripLabel: `${vehicleLabelForColor(colorIdx, fd.name)} → ${fd.name}`,
          xM: 0,
          yM: 0,
          txM: 1,
          tyM: 0,
          u: 0.5,
          vCoord: 0.5,
        };
        updateFeederMeters(fv);
        feederVehicles.push(fv);
      }
    }

    // 4. Seed grade-aware cyclist pace groups (non-motorway roads only)
    cyclists = [];
    const cRng = rootRng.fork('cyclists');
    for (const lane of lanes) {
      if (lane.isMotorway) continue;
      const baseCount = lane.rd.kind === 'seestrasse' ? 7 : 6;
      const targetCount = Math.max(1, Math.round(baseCount * profile.cyclistFactor));
      let created = 0;
      let groupIdx = 0;
      while (created < targetCount) {
        const groupSize = (targetCount - created >= 2 && cRng.chance(0.55)) ? 2 : 1;
        const baseS = ((((lane.rd.phase || 0) * 0.7 + (groupIdx + 0.35) / Math.max(1, Math.ceil(targetCount / 1.5))) % 1) + 1) % 1 * lane.rd.length_m;
        const vBase = cRng.range(4.8, 5.6);
        for (let m = 0; m < groupSize; m++) {
          const s = ((baseS - m * 3.2) % lane.rd.length_m + lane.rd.length_m) % lane.rd.length_m;
          const cyc = {
            id: `cyc:${lane.rd.id}:${created}`,
            laneIdx: lane.rIdx,
            roadId: lane.rd.id,
            s,
            v: vBase,
            vBase,
            latOffset: m === 0 ? 0 : 0.35,
            colorIdx: created + lane.rIdx * 5,
            yielding: false,
            xM: 0,
            yM: 0,
            txM: 1,
            tyM: 0,
          };
          updateCyclistMeters(cyc, lane.rd);
          cyclists.push(cyc);
          created++;
        }
        groupIdx++;
      }
    }

    // Resolve any initial cross-corridor spawn overlaps across shared physical roads
    resolve2DOverlapsPostStep();
    initialized = true;
    recomputeStats(tStart);
  }

  function updateCrosswalkOccupancy(tNow) {
    const profile = getDiurnalProfile(currentMode);
    for (let i = 0; i < crosswalkDefs.length; i++) {
      const def = crosswalkDefs[i];
      const st = crosswalkStates[i];
      if (useExternalCrosswalks) {
        const occ = !!externalCrosswalkMap.get(def.id);
        st.occupied = occ;
        st.progress = occ ? ((tNow * 0.25 + i * 0.17) % 1) : 0;
        st.walkerCount = occ ? 1 : 0;
      } else {
        const effPeriod = def.period / Math.max(0.22, profile.crosswalkRate);
        const cyc = (((tNow + def.phaseOffset) % effPeriod) + effPeriod) % effPeriod;
        const activeDur = 4.5;
        if (cyc < activeDur) {
          st.occupied = true;
          st.progress = cyc / activeDur;
          st.walkerCount = (i % 3 === 0 && currentMode === 'day') ? 2 : 1;
        } else {
          st.occupied = false;
          st.progress = 0;
          st.walkerCount = 0;
        }
      }
    }
  }

  function updateJunctionReservations(dt) {
    const R_HOLD_EXIT = 13.5;
    const R_BOX = 10.0;
    for (let ji = 0; ji < junctionDefs.length; ji++) {
      const jc = junctionDefs[ji];
      if (jc.holderId) {
        jc.holdTime += dt;
        // Find holder in spatialGrid near junction
        spatialGrid.queryRadius(jc.xM, jc.yM, R_HOLD_EXIT + 6.0, 'veh', queryBuf);
        let holderVeh = null;
        for (let q = 0; q < queryBuf.length; q++) {
          if (queryBuf[q].id === jc.holderId) {
            holderVeh = queryBuf[q].data;
            break;
          }
        }
        if (!holderVeh) {
          jc.holderId = null;
          jc.holderRoadId = null;
          jc.holdTime = 0;
        } else {
          const dist = Math.hypot(holderVeh.xM - jc.xM, holderVeh.yM - jc.yM);
          jc.holderXM = holderVeh.xM;
          jc.holderYM = holderVeh.yM;
          jc.holderTxM = holderVeh.txM;
          jc.holderTyM = holderVeh.tyM;
          if (dist > R_HOLD_EXIT || (jc.holdTime > 5.0 && holderVeh.v < 0.25)) {
            jc.holderId = null;
            jc.holderRoadId = null;
            jc.holdTime = 0;
          }
        }
      }

      if (!jc.holderId) {
        spatialGrid.queryRadius(jc.xM, jc.yM, R_BOX, 'veh', queryBuf);
        let bestVeh = null;
        let bestScore = -Infinity;
        for (let q = 0; q < queryBuf.length; q++) {
          const v = queryBuf[q].data;
          if (!v || v.isMotorway) continue;
          const dist = Math.hypot(v.xM - jc.xM, v.yM - jc.yM);
          if (dist > R_BOX) continue;
          const score = v.priority * 10 - dist;
          if (score > bestScore) {
            bestScore = score;
            bestVeh = v;
          }
        }
        if (bestVeh) {
          jc.holderId = bestVeh.id;
          jc.holderRoadId = bestVeh.roadId;
          jc.holderRoadKind = bestVeh.roadKind;
          jc.holderXM = bestVeh.xM;
          jc.holderYM = bestVeh.yM;
          jc.holderTxM = bestVeh.txM;
          jc.holderTyM = bestVeh.tyM;
          jc.holdTime = 0;
        }
      }
    }
  }

  function step(dt, externalCrosswalkOcc) {
    simTime += dt;
    if (externalCrosswalkOcc) {
      useExternalCrosswalks = true;
      externalCrosswalkMap.clear();
      if (externalCrosswalkOcc instanceof Set) {
        for (const id of externalCrosswalkOcc) externalCrosswalkMap.set(id, true);
      } else if (externalCrosswalkOcc instanceof Map) {
        for (const [k, v] of externalCrosswalkOcc.entries()) externalCrosswalkMap.set(k, !!v);
      } else if (typeof externalCrosswalkOcc === 'object') {
        for (const k of Object.keys(externalCrosswalkOcc)) externalCrosswalkMap.set(k, !!externalCrosswalkOcc[k]);
      }
    }

    updateCrosswalkOccupancy(simTime);
    dwellingStops.clear();

    // Update ground-plane 2D positions and populate unified 2D spatial grid
    for (let li = 0; li < lanes.length; li++) {
      const lane = lanes[li];
      for (let i = 0; i < lane.vehicles.length; i++) {
        updateVehicleMeters(lane.vehicles[i], lane.rd);
      }
    }
    for (let i = 0; i < feederVehicles.length; i++) {
      updateFeederMeters(feederVehicles[i]);
    }
    for (let i = 0; i < cyclists.length; i++) {
      const cyc = cyclists[i];
      const lane = lanes[cyc.laneIdx];
      if (lane) updateCyclistMeters(cyc, lane.rd);
    }
    rebuildSpatialGrid(true);
    updateJunctionReservations(dt);

    // 1. Step all main road lanes (1D + 2D cross-corridor IDM + 6 junctions + bidirectional crosswalks + 2D ped/cyclist cone)
    for (const lane of lanes) {
      const L = lane.rd.length_m;
      const vehs = lane.vehicles;
      const N = vehs.length;
      if (N === 0) continue;

      vehs.sort((a, b) => a.s - b.s);

      const nextA = new Float64Array(N);
      for (let i = 0; i < N; i++) {
        const me = vehs[i];
        const isBus = me.kind === 'bus' || me.kind === 'bus_artic';

        if (me.stopCooldown > 0) me.stopCooldown = Math.max(0, me.stopCooldown - dt);
        if (me.departBlinkerTimer > 0) me.departBlinkerTimer = Math.max(0, me.departBlinkerTimer - dt);

        me.yielding = false;
        me.blinker = 'none';
        me._pedHardStop = false;

        // Bus currently dwelling at a ZVV stop
        if (isBus && me.isDwelling) {
          me.dwellTimer -= dt;
          me.v = 0;
          me.a = 0;
          me.braking = true;
          me.blinker = 'hazard';
          me.pullInFrac = Math.min(1.0, me.pullInFrac + dt * 1.4);
          if (me.dwellingStopIdx >= 0) {
            dwellingStops.add(`${lane.rd.id}:${me.dwellingStopIdx}`);
          }
          const stopsArr = me.stopsM || lane.stopsM;
          if (me.dwellTimer <= 0) {
            me.isDwelling = false;
            me.dwellingStopIdx = -1;
            me.stopCooldown = 4.0;
            me.departBlinkerTimer = 2.2;
            if (stopsArr.length > 0) {
              me.nextStopIdx = (me.nextStopIdx + 1) % stopsArr.length;
            }
          }
          nextA[i] = 0;
          continue;
        }

        // Same-lane 1D IDM leader lookup
        const j = (i + 1) % N;
        const leader = vehs[j];
        let rawDs = j > i ? (leader.s - me.s) : (L - me.s + leader.s);
        if (N === 1) rawDs = 9999;
        const gap = rawDs - 0.5 * (leader.lengthM + me.lengthM);

        let aIDM;
        if (N === 1 || rawDs > 160.0) {
          aIDM = me.aMax * (1.0 - Math.pow(me.v / me.v0, 4));
        } else {
          const dv = me.v - leader.v;
          const sStar = me.s0 + Math.max(
            0,
            me.v * me.T + (me.v * dv) / (2.0 * Math.sqrt(me.aMax * me.bComf)),
          );
          const effGap = Math.max(0.5, gap);
          aIDM = me.aMax * (1.0 - Math.pow(me.v / me.v0, 4) - Math.pow(sStar / effGap, 2));
        }

        let aFinal = aIDM;

        // Virtual obstacle 1: Bus scheduled stop approach
        const busStops = isBus ? (me.stopsM || lane.stopsM) : null;
        if (isBus && busStops.length > 0 && me.stopCooldown <= 0) {
          const stopObj = busStops[me.nextStopIdx % busStops.length];
          let dStop = stopObj.sM - me.s;
          if (dStop < -L * 0.5) dStop += L;
          if (dStop >= -1.0 && dStop <= 48.0) {
            if (dStop <= 1.2 || (dStop <= 2.4 && me.v < 0.35)) {
              me.isDwelling = true;
              me.dwellTimer = stopObj.dwellSec || 3.2;
              me.dwellingStopIdx = stopObj.idx;
              me.v = 0;
              me.a = 0;
              me.braking = true;
              me.blinker = 'hazard';
              dwellingStops.add(`${lane.rd.id}:${stopObj.idx}`);
              nextA[i] = 0;
              continue;
            }
            const sStarStop = 0.4 + Math.max(0, me.v * 1.1 + (me.v * me.v) / (2.0 * Math.sqrt(me.aMax * me.bComf)));
            const aStop = me.aMax * (1.0 - Math.pow(me.v / me.v0, 4) - Math.pow(sStarStop / Math.max(0.5, dStop), 2));
            if (aStop < aFinal) aFinal = aStop;
            if (dStop < 35.0) {
              me.blinker = 'right';
              me.pullInFrac = Math.min(1.0, me.pullInFrac + dt * 0.7);
            }
          } else {
            me.pullInFrac = Math.max(0.0, me.pullInFrac - dt * 0.8);
          }
        } else if (isBus) {
          me.pullInFrac = Math.max(0.0, me.pullInFrac - dt * 0.8);
        }

        if (isBus && me.departBlinkerTimer > 0 && me.blinker === 'none') {
          me.blinker = 'left';
        }

        // Virtual obstacle 2: Bidirectional occupied zebra crosswalks (NO minStopDist skip blind spot!)
        if (!lane.isMotorway && lane.crosswalks.length > 0) {
          for (let k = 0; k < lane.crosswalks.length; k++) {
            const cwBind = lane.crosswalks[k];
            const cwSt = crosswalkStates[cwBind.cwIdx];
            if (!cwSt || !cwSt.occupied) continue;
            let dCw = cwBind.sM - (me.s + 0.5 * me.lengthM) - 3.6;
            if (dCw < -L * 0.5) dCw += L;
            if (dCw > -0.4 && dCw < 40.0) {
              let aCw;
              if (dCw <= 1.5) {
                aCw = -me.bEmerg;
                if (dCw <= 0.9 && me.v < 1.5) {
                  me._pedHardStop = true;
                }
              } else {
                const sStarCw = 2.4 + Math.max(0, me.v * 1.2 + (me.v * me.v) / (2.0 * Math.sqrt(me.aMax * me.bComf)));
                aCw = me.aMax * (1.0 - Math.pow(me.v / me.v0, 4) - Math.pow(sStarCw / Math.max(0.5, dCw), 2));
              }
              if (aCw < aFinal - 0.1) {
                aFinal = aCw;
                me.yielding = true;
              }
            }
          }
        }

        // Virtual obstacle 3: 6-Junction Conflict-Box Reservation
        if (!lane.isMotorway && lane.junctions.length > 0) {
          for (let k = 0; k < lane.junctions.length; k++) {
            const jLink = lane.junctions[k];
            const jc = junctionDefs[jLink.juncIdx];
            if (!jc) continue;
            let dJunc = jLink.sM - (me.s + 0.5 * me.lengthM) - 10.5;
            if (dJunc < -L * 0.5) dJunc += L;
            if (dJunc > -1.0 && dJunc < 32.0) {
              if (jc.holderId && jc.holderId !== me.id && jc.holderRoadId !== me.roadId) {
                // Check if holder is on a conflicting stream (not a parallel opposing lane with clearance)
                const hDot = me.txM * jc.holderTxM + me.tyM * jc.holderTyM;
                const hLat = Math.abs(-(jc.holderXM - me.xM) * me.tyM + (jc.holderYM - me.yM) * me.txM);
                const isOpposingParallel = hDot < -0.6 && hLat > 2.0 && jc.holderRoadKind === lane.rd.kind;
                if (!isOpposingParallel) {
                  let aJunc;
                  if (dJunc <= 1.2) {
                    aJunc = -me.bEmerg;
                  } else {
                    const sStarJ = 1.8 + Math.max(0, me.v * 1.1 + (me.v * me.v) / (2.0 * Math.sqrt(me.aMax * me.bComf)));
                    aJunc = me.aMax * (1.0 - Math.pow(me.v / me.v0, 4) - Math.pow(sStarJ / Math.max(0.5, dJunc), 2));
                  }
                  if (aJunc < aFinal) {
                    aFinal = aJunc;
                    me.yielding = true;
                  }
                }
              } else if (!jc.holderId && dJunc <= 2.5) {
                jc.holderId = me.id;
                jc.holderRoadId = me.roadId;
                jc.holderRoadKind = lane.rd.kind;
                jc.holderXM = me.xM;
                jc.holderYM = me.yM;
                jc.holderTxM = me.txM;
                jc.holderTyM = me.tyM;
                jc.holdTime = 0;
              }
            }
          }
        }

        // Virtual obstacle 4: 2D Cross-Lane Shared-Corridor & Crossing Vehicle Yielding
        if (!lane.isMotorway) {
          spatialGrid.queryRadius(me.xM, me.yM, 40.0, 'veh', queryBuf);
          for (let q = 0; q < queryBuf.length; q++) {
            const other = queryBuf[q].data;
            if (!other || other === me || other.roadId === me.roadId || other.isMotorway) continue;
            const dx = other.xM - me.xM;
            const dy = other.yM - me.yM;
            const fwd = dx * me.txM + dy * me.tyM;
            if (fwd <= 0) continue;
            const lat = Math.abs(-dx * me.tyM + dy * me.txM);
            const dot = me.txM * other.txM + me.tyM * other.tyM;

            if (dot > 0.65 && lat < 2.6) {
              // Same-direction shared-corridor virtual IDM leader
              const crossGap = fwd - 0.5 * (me.lengthM + other.lengthM);
              let aCross;
              if (crossGap <= 2.4) {
                aCross = -me.bEmerg;
              } else {
                const dv = me.v - other.v;
                const s0Cross = Math.max(me.s0, 6.5);
                const sStarC = s0Cross + Math.max(
                  0,
                  me.v * me.T + (me.v * dv) / (2.0 * Math.sqrt(me.aMax * me.bComf)),
                );
                aCross = me.aMax * (1.0 - Math.pow(me.v / me.v0, 4) - Math.pow(sStarC / Math.max(0.5, crossGap), 2));
              }
              if (aCross < aFinal) {
                aFinal = aCross;
                if (aCross < -0.4) me.yielding = true;
              }
            } else if (dot >= -0.45 && dot <= 0.65 && lat < 3.4 && fwd < 0.5 * me.lengthM + 18.0) {
              // Crossing / merging vehicle ahead in our forward path
              const shouldYieldToOther = (other.priority > me.priority)
                || (other.priority === me.priority && fwd > 2.0 && !other.isFeeder);
              if (shouldYieldToOther) {
                const crossGap = fwd - 0.5 * me.lengthM - 2.2;
                let aCross;
                if (crossGap <= 1.4) {
                  aCross = -me.bEmerg;
                } else {
                  const sStarC = 1.6 + Math.max(0, me.v * 1.1 + (me.v * me.v) / (2.0 * Math.sqrt(me.aMax * me.bComf)));
                  aCross = me.aMax * (1.0 - Math.pow(me.v / me.v0, 4) - Math.pow(sStarC / Math.max(0.5, crossGap), 2));
                }
                if (aCross < aFinal) {
                  aFinal = aCross;
                  me.yielding = true;
                }
              }
            }
          }

          // Virtual obstacle 5: 2D Forward-Cone Pedestrian Braking (roadway-encroaching peds only; ignore off-curb sidewalk/bus-stop peds)
          spatialGrid.queryRadius(me.xM, me.yM, 0.5 * me.lengthM + 15.0, 'ped', queryBuf);
          for (let q = 0; q < queryBuf.length; q++) {
            const ped = queryBuf[q].data;
            if (!ped) continue;
            const pSt = ped.state;
            const dx = ped.xM - me.xM;
            const dy = ped.yM - me.yM;
            const fwd = dx * me.txM + dy * me.tyM;
            const lat = Math.abs(-dx * me.tyM + dy * me.txM);
            // Generous 1.35 m lateral yield for active zebra-crossing peds; tight 0.96 m lane-body check for other peds so sidewalk/footpath walkers never stall traffic
            const latThresh = pSt === 'crossing_cw' ? 1.35 : 0.96;
            if (lat >= latThresh) continue;
            const isAheadOfBumper = fwd > 0.5 * me.lengthM - 0.3;
            const isActiveInPath = pSt === 'crossing_cw' && fwd > -0.5 * me.lengthM + 0.5;
            if ((isAheadOfBumper || isActiveInPath) && fwd < 0.5 * me.lengthM + 14.0) {
              const distAhead = fwd - 0.5 * me.lengthM;
              let aPed;
              if (distAhead <= 1.8 && isAheadOfBumper) {
                aPed = -me.bEmerg;
                me._pedHardStop = true;
              } else {
                const sStarP = 1.6 + Math.max(0, me.v * 1.0 + (me.v * me.v) / (2.0 * Math.sqrt(me.aMax * me.bComf)));
                aPed = me.aMax * (1.0 - Math.pow(me.v / me.v0, 4) - Math.pow(sStarP / Math.max(0.4, distAhead - 0.9), 2));
              }
              if (aPed < aFinal) {
                aFinal = aPed;
                me.yielding = true;
              }
            }
          }

          // Virtual obstacle 6: 2D Forward-Cone Cyclist Awareness (yields when cyclist enters vehicle corridor, e.g. junctions/cross-corridors)
          spatialGrid.queryRadius(me.xM, me.yM, 0.5 * me.lengthM + 15.0, 'cyclist', queryBuf);
          for (let q = 0; q < queryBuf.length; q++) {
            const cyc = queryBuf[q].data;
            if (!cyc) continue;
            const dx = cyc.xM - me.xM;
            const dy = cyc.yM - me.yM;
            const fwd = dx * me.txM + dy * me.tyM;
            const lat = Math.abs(-dx * me.tyM + dy * me.txM);
            if (fwd > 0.5 * me.lengthM - 0.2 && fwd < 0.5 * me.lengthM + 14.0 && lat < 1.45) {
              const distAhead = fwd - 0.5 * me.lengthM - 0.9;
              let aCyc;
              if (distAhead <= 1.3 && lat < 1.25) {
                aCyc = -me.bEmerg;
                me._pedHardStop = true;
              } else {
                const dot = me.txM * cyc.txM + me.tyM * cyc.tyM;
                const dv = dot > 0.5 ? (me.v - cyc.v) : me.v;
                const sStarCy = 2.6 + Math.max(0, me.v * 1.0 + (me.v * dv) / (2.0 * Math.sqrt(me.aMax * me.bComf)));
                aCyc = me.aMax * (1.0 - Math.pow(me.v / me.v0, 4) - Math.pow(sStarCy / Math.max(0.45, distAhead), 2));
              }
              if (aCyc < aFinal) {
                aFinal = aCyc;
                if (aCyc < -0.4) me.yielding = true;
              }
            }
          }
        }

        nextA[i] = clamp(aFinal, -me.bEmerg, me.aMax);
      }

      // Integrate velocities & positions
      for (let i = 0; i < N; i++) {
        const me = vehs[i];
        if ((me.kind === 'bus' || me.kind === 'bus_artic') && me.isDwelling) continue;
        me.a = nextA[i];
        me.v = clamp(me.v + me.a * dt, 0, me.v0);
        if (me._pedHardStop) {
          me.v = 0;
        }
        me.s += me.v * dt;
      }

      // Hard non-overlap 1D bumper clamp (reverse order from front to back)
      const minHardGap = lane.isMotorway ? 10.0 : 4.5;
      for (let pass = 0; pass < 2; pass++) {
        for (let i = N - 1; i >= 0; i--) {
          const me = vehs[i];
          const j = (i + 1) % N;
          if (N === 1) continue;
          const leader = vehs[j];
          const rawDs = j > i ? (leader.s - me.s) : (L - me.s + leader.s);
          const minCenter = 0.5 * (leader.lengthM + me.lengthM) + minHardGap;
          if (rawDs < minCenter) {
            const push = minCenter - rawDs;
            me.s -= push;
            me.v = Math.min(me.v, leader.v * 0.9);
            if (me.v < 0.05) me.v = 0;
          }
        }
      }

      // Wrap positions into [0, L) & update signal telemetry
      for (let i = 0; i < N; i++) {
        const me = vehs[i];
        me.s = ((me.s % L) + L) % L;
      }
      vehs.sort((a, b) => a.s - b.s);

      for (let i = 0; i < N; i++) {
        const me = vehs[i];
        const isBus = me.kind === 'bus' || me.kind === 'bus_artic';
        const j = (i + 1) % N;
        const leader = vehs[j];
        const rawDs = N > 1 ? (j > i ? (leader.s - me.s) : (L - me.s + leader.s)) : 9999;
        const gap = rawDs - 0.5 * (leader.lengthM + me.lengthM);

        if (isBus && me.isDwelling) {
          me.braking = true;
        } else {
          me.braking = (me.a < -0.45) || (me.v < 0.8 && (me.yielding || gap < me.s0 * 1.45));
        }

        const targetDim = (gap < 18.0 && me.v < me.v0 * 0.55) ? 0.35 : 1.0;
        me.headlightDim += (targetDim - me.headlightDim) * Math.min(1.0, dt * 4.0);
      }
    }

    // 2. Step feeder-street local trips & delivery vans (with 2D ped & main-road junction yielding!)
    for (let i = 0; i < feederVehicles.length; i++) {
      const fv = feederVehicles[i];
      const fd = feederDefs[fv.feederIdx];
      if (!fd) continue;
      const dFracDt = fv.speedMps / fd.lengthM;
      fv.braking = false;
      fv.yielding = false;
      fv.blinker = 'none';

      // Check forward cone for pedestrians or vehicles when moving
      let blockedAhead = false;
      if (fv.state === 'outbound_feeder' || fv.state === 'inbound_feeder') {
        spatialGrid.queryRadius(fv.xM, fv.yM, 12.0, 'ped', queryBuf);
        for (let q = 0; q < queryBuf.length; q++) {
          const ped = queryBuf[q].data;
          if (!ped) continue;
          const pSt = ped.state;
          if (
            pSt === 'walk_sidewalk' || pSt === 'queue_bus' || pSt === 'curb_wait'
            || pSt === 'cw_stroll' || pSt === 'social_pause' || pSt === 'linger'
            || pSt === 'sit_cafe' || pSt === 'park_stroll' || pSt === 'seebad_stroll'
          ) {
            continue;
          }
          const dx = ped.xM - fv.xM;
          const dy = ped.yM - fv.yM;
          const fwd = dx * fv.txM + dy * fv.tyM;
          const lat = Math.abs(-dx * fv.tyM + dy * fv.txM);
          if (fwd > 0 && fwd < 8.5 && lat < 1.35) {
            blockedAhead = true;
            break;
          }
        }
        if (!blockedAhead) {
          spatialGrid.queryRadius(fv.xM, fv.yM, 14.0, 'veh', queryBuf);
          for (let q = 0; q < queryBuf.length; q++) {
            const other = queryBuf[q].data;
            if (!other || other === fv || other.isMotorway) continue;
            const dx = other.xM - fv.xM;
            const dy = other.yM - fv.yM;
            const fwd = dx * fv.txM + dy * fv.tyM;
            const lat = Math.abs(-dx * fv.tyM + dy * fv.txM);
            if (fwd > 0 && fwd < 0.5 * (fv.lengthM + other.lengthM) + 4.5 && lat < 2.6) {
              blockedAhead = true;
              break;
            }
          }
        }
      }

      if (blockedAhead) {
        fv.v = 0;
        fv.braking = true;
        fv.yielding = true;
        continue;
      }

      if (fv.state === 'outbound_feeder') {
        fv.v = fv.speedMps;
        fv.distFrac += dFracDt * dt;
        if (fv.distFrac >= fv.curbFrac - 0.08) {
          fv.blinker = 'right';
          fv.braking = true;
        }
        if (fv.distFrac >= fv.curbFrac) {
          fv.distFrac = fv.curbFrac;
          fv.state = 'curb_pause';
          fv.timer = 6.5 + (i % 4) * 0.85;
          fv.v = 0;
          fv.braking = true;
          fv.blinker = 'hazard';
        }
      } else if (fv.state === 'curb_pause') {
        fv.v = 0;
        fv.braking = true;
        fv.blinker = 'hazard';
        fv.timer -= dt;
        if (fv.timer <= 0) {
          fv.state = 'inbound_feeder';
        }
      } else if (fv.state === 'inbound_feeder') {
        fv.v = fv.speedMps;
        fv.distFrac -= dFracDt * dt;
        if (fv.distFrac <= 20.0 / fd.lengthM) {
          fv.blinker = 'right';
          fv.braking = true;
        }
        const stopLineFrac = Math.max(0.08, 8.5 / fd.lengthM);
        if (fv.distFrac <= stopLineFrac) {
          fv.distFrac = stopLineFrac;
          fv.state = 'junction_wait';
          fv.timer = 1.6 + (i % 3) * 0.45;
          fv.waitElapsed = 0;
          fv.v = 0;
          fv.braking = true;
          fv.yielding = true;
          fv.blinker = 'right';
        }
      } else {
        fv.v = 0;
        fv.braking = true;
        fv.yielding = true;
        fv.blinker = 'right';
        fv.timer -= dt;
        fv.waitElapsed = (fv.waitElapsed || 0) + dt;
        if (fv.timer <= 0) {
          // Check main-road junction clearance before departing
          let mainRoadBusy = false;
          if (fv.waitElapsed < 6.0) {
            spatialGrid.queryRadius(fd.connXM, fd.connYM, 16.0, 'veh', queryBuf);
            for (let q = 0; q < queryBuf.length; q++) {
              const other = queryBuf[q].data;
              if (other && other !== fv && !other.isFeeder && !other.isMotorway) {
                mainRoadBusy = true;
                break;
              }
            }
          }
          if (!mainRoadBusy) {
            fv.state = 'outbound_feeder';
            fv.waitElapsed = 0;
          }
        }
      }
    }

    // Enforce 2D cross-corridor & junction minimum bumper clearance
    resolve2DOverlapsPostStep();

    // 3. Step grade-aware cyclist pace groups (yielding to cars, buses, cyclists & crosswalks)
    for (let i = 0; i < cyclists.length; i++) {
      const cyc = cyclists[i];
      const lane = lanes[cyc.laneIdx];
      if (!lane) continue;
      const L = lane.rd.length_m;
      const frac = cyc.s / L;

      let vTarget = cyc.vBase;
      if (lane.rd.id === 'dorfstrasse_viaduct_up' && frac >= 0.32 && frac <= 0.66) {
        vTarget = cyc.vBase * 0.58;
      } else if (lane.rd.id === 'dorfstrasse_viaduct_dn' && frac >= 0.34 && frac <= 0.68) {
        vTarget = cyc.vBase * 1.38;
      } else if (lane.rd.id === 'alte_landstrasse_eb' && frac < 0.40) {
        vTarget = cyc.vBase * 0.86;
      } else if (lane.rd.id === 'alte_landstrasse_wb' && frac > 0.60) {
        vTarget = cyc.vBase * 1.10;
      }

      let mustYield = false;
      // Yield behind ALL vehicles (buses, cars, vans) on same lane
      for (const v of lane.vehicles) {
        const rearS = v.s - 0.5 * v.lengthM;
        let d = rearS - cyc.s;
        if (d < -L * 0.5) d += L;
        if (d > L * 0.5) d -= L;
        const isBus = v.kind === 'bus' || v.kind === 'bus_artic';
        if (isBus && (v.isDwelling || v.pullInFrac > 0.05)) {
          if (d > -2.5 && d < 20.0) {
            if (d <= 5.5) {
              vTarget = 0;
              mustYield = true;
            } else {
              vTarget = Math.min(vTarget, Math.max(0, (d - 4.5) * 0.55));
              mustYield = true;
            }
          }
        } else if (d > 0 && d < 14.0 && v.v < cyc.v + 0.5) {
          vTarget = d <= 3.5 ? 0 : Math.min(vTarget, Math.max(0, v.v * 0.9));
          mustYield = true;
        }
      }
      // Yield behind other cyclists ahead on same lane
      for (let oi = 0; oi < cyclists.length; oi++) {
        if (oi === i) continue;
        const other = cyclists[oi];
        if (other.laneIdx !== cyc.laneIdx) continue;
        let d = other.s - cyc.s;
        if (d < -L * 0.5) d += L;
        if (d > L * 0.5) d -= L;
        if (d > 0 && d < 5.0) {
          vTarget = d <= 2.2 ? Math.min(vTarget, other.v * 0.8) : Math.min(vTarget, other.v);
          mustYield = true;
        }
      }
      // Yield at occupied crosswalks
      for (const cwBind of lane.crosswalks) {
        const cwSt = crosswalkStates[cwBind.cwIdx];
        if (!cwSt || !cwSt.occupied) continue;
        let d = cwBind.sM - cyc.s - 2.5;
        if (d < -L * 0.5) d += L;
        if (d > -0.5 && d < 12.0) {
          vTarget = d <= 2.5 ? 0 : Math.min(vTarget, d * 0.5);
          mustYield = true;
        }
      }

      // Yield to any 2D vehicle occupying our forward path (junctions, cross-corridors, pulling-in buses)
      spatialGrid.queryRadius(cyc.xM, cyc.yM, 14.0, 'veh', queryBuf);
      for (let q = 0; q < queryBuf.length; q++) {
        const veh = queryBuf[q].data;
        if (!veh || veh.isMotorway) continue;
        const dx = veh.xM - cyc.xM;
        const dy = veh.yM - cyc.yM;
        const fwd = dx * cyc.txM + dy * cyc.tyM;
        const lat = Math.abs(-dx * cyc.tyM + dy * cyc.txM);
        const halfL = 0.5 * veh.lengthM;
        if (fwd > -halfL - 0.5 && fwd < halfL + 6.0 && lat < 1.45) {
          vTarget = fwd < halfL + 2.5 ? 0 : Math.min(vTarget, Math.max(0, (fwd - halfL - 1.5) * 0.8));
          mustYield = true;
        }
      }

      cyc.yielding = mustYield;
      const accel = vTarget > cyc.v ? 1.6 : (mustYield ? 6.0 : 3.4);
      if (vTarget > cyc.v) cyc.v = Math.min(vTarget, cyc.v + accel * dt);
      else cyc.v = Math.max(vTarget, cyc.v - accel * dt);

      const prevS = cyc.s;
      cyc.s = (((cyc.s + cyc.v * dt) % L) + L) % L;
      updateCyclistMeters(cyc, lane.rd);

      // Hard 2D OBB non-overlap guard between cyclist and all non-motorway vehicles
      spatialGrid.queryRadius(cyc.xM, cyc.yM, 12.0, 'veh', queryBuf);
      for (let q = 0; q < queryBuf.length; q++) {
        const veh = queryBuf[q].data;
        if (!veh || veh.isMotorway) continue;
        const dx = cyc.xM - veh.xM;
        const dy = cyc.yM - veh.yM;
        const fwd = Math.abs(dx * veh.txM + dy * veh.tyM);
        const lat = Math.abs(-dx * veh.tyM + dy * veh.txM);
        if (fwd < 0.5 * veh.lengthM + 0.55 && lat < 1.25) {
          // Hold behind or step back out of vehicle OBB
          cyc.s = prevS;
          cyc.v = 0;
          cyc.yielding = true;
          updateCyclistMeters(cyc, lane.rd);
          const dx2 = cyc.xM - veh.xM;
          const dy2 = cyc.yM - veh.yM;
          if (Math.abs(dx2 * veh.txM + dy2 * veh.tyM) < 0.5 * veh.lengthM + 0.45 && Math.abs(-dx2 * veh.tyM + dy2 * veh.txM) < 1.20) {
            cyc.s = (((cyc.s - 2.0) % L) + L) % L;
            updateCyclistMeters(cyc, lane.rd);
          }
          break;
        }
      }
    }
  }

  function recomputeStats(tNow) {
    let totalVehicles = 0;
    let brakingCount = 0;
    let yieldingCount = 0;
    let busCount = 0;
    let clippingCount = 0;
    let overlapCount = 0;
    let pedVehicleOverlapCount = 0;
    let cyclistVehicleOverlapCount = 0;
    let minBusGapM = 999;

    // Refresh 2D meter coordinates for true 2D overlap telemetry
    for (let li = 0; li < lanes.length; li++) {
      const lane = lanes[li];
      for (let i = 0; i < lane.vehicles.length; i++) {
        updateVehicleMeters(lane.vehicles[i], lane.rd);
      }
    }
    for (let i = 0; i < feederVehicles.length; i++) {
      updateFeederMeters(feederVehicles[i]);
    }
    for (let i = 0; i < cyclists.length; i++) {
      const cyc = cyclists[i];
      const lane = lanes[cyc.laneIdx];
      if (lane) updateCyclistMeters(cyc, lane.rd);
    }
    rebuildSpatialGrid(true);

    const countedPairs = new Set();

    for (const lane of lanes) {
      const L = lane.rd.length_m;
      const vehs = lane.vehicles;
      const N = vehs.length;
      for (let i = 0; i < N; i++) {
        const v = vehs[i];
        totalVehicles++;
        const isBus = v.kind === 'bus' || v.kind === 'bus_artic';
        if (isBus) busCount++;
        if (v.braking) brakingCount++;
        if (v.yielding) yieldingCount++;

        // 1D same-lane gap & bus clearance check
        if (N > 1) {
          const j = (i + 1) % N;
          const leader = vehs[j];
          const rawDs = j > i ? (leader.s - v.s) : (L - v.s + leader.s);
          const gap = rawDs - 0.5 * (leader.lengthM + v.lengthM);
          if (gap < 0.0) {
            const key = v.id < leader.id ? `${v.id}|${leader.id}` : `${leader.id}|${v.id}`;
            if (!countedPairs.has(key)) {
              countedPairs.add(key);
              overlapCount++;
            }
          }
          if (leader.kind === 'bus' || leader.kind === 'bus_artic') {
            if (gap < minBusGapM) minBusGapM = gap;
            if (gap < 1.0) clippingCount++;
          }
        }

        // True 2D cross-corridor / junction / feeder OBB overlap check
        if (!lane.isMotorway) {
          spatialGrid.queryRadius(v.xM, v.yM, v.lengthM + 10.0, 'veh', queryBuf);
          for (let q = 0; q < queryBuf.length; q++) {
            const other = queryBuf[q].data;
            if (!other || other === v || other.roadId === v.roadId || other.isMotorway) continue;
            const key = v.id < other.id ? `${v.id}|${other.id}` : `${other.id}|${v.id}`;
            if (countedPairs.has(key)) continue;
            if (checkVehicleOBBOverlap(v, other)) {
              countedPairs.add(key);
              overlapCount++;
              if (isBus || other.kind === 'bus' || other.kind === 'bus_artic') {
                clippingCount++;
              }
            }
          }

          // True 2D vehicle–pedestrian overlap check
          spatialGrid.queryRadius(v.xM, v.yM, 0.5 * v.lengthM + 2.0, 'ped', queryBuf);
          for (let q = 0; q < queryBuf.length; q++) {
            const ped = queryBuf[q].data;
            if (!ped) continue;
            const dx = ped.xM - v.xM;
            const dy = ped.yM - v.yM;
            const fwd = Math.abs(dx * v.txM + dy * v.tyM);
            const lat = Math.abs(-dx * v.tyM + dy * v.txM);
            if (fwd < 0.5 * v.lengthM + 0.1 && lat < 0.95) {
              pedVehicleOverlapCount++;
            }
          }

          // True 2D vehicle–cyclist OBB overlap check
          spatialGrid.queryRadius(v.xM, v.yM, 0.5 * v.lengthM + 2.5, 'cyclist', queryBuf);
          for (let q = 0; q < queryBuf.length; q++) {
            const cyc = queryBuf[q].data;
            if (!cyc) continue;
            const dx = cyc.xM - v.xM;
            const dy = cyc.yM - v.yM;
            const fwd = Math.abs(dx * v.txM + dy * v.tyM);
            const lat = Math.abs(-dx * v.tyM + dy * v.txM);
            if (fwd < 0.5 * v.lengthM + 0.35 && lat < 1.15) {
              cyclistVehicleOverlapCount++;
            }
          }
        }
      }
    }

    for (const fv of feederVehicles) {
      totalVehicles++;
      if (fv.braking) brakingCount++;
      if (fv.yielding) yieldingCount++;

      // Feeder-vs-pedestrian 2D overlap check
      spatialGrid.queryRadius(fv.xM, fv.yM, 0.5 * fv.lengthM + 2.0, 'ped', queryBuf);
      for (let q = 0; q < queryBuf.length; q++) {
        const ped = queryBuf[q].data;
        if (!ped) continue;
        const dx = ped.xM - fv.xM;
        const dy = ped.yM - fv.yM;
        const fwd = Math.abs(dx * fv.txM + dy * fv.tyM);
        const lat = Math.abs(-dx * fv.tyM + dy * fv.txM);
        if (fwd < 0.5 * fv.lengthM + 0.1 && lat < 0.95) {
          pedVehicleOverlapCount++;
        }
      }
    }

    let activeTrainTrips = 0;
    for (const tr of trains) {
      const st = evalTrainState(tr, tNow);
      if (st.headFrac >= 0 && st.headFrac <= 1.12) activeTrainTrips++;
    }
    let activeShipTrips = 0;
    for (const sh of ships) {
      const st = evalShipState(sh, tNow, currentMode);
      if (st.visible) activeShipTrips++;
    }

    const bell = evalBellState(tNow, currentMode);
    const baselinePeds = computeBaselinePedestrianCount(currentMode);
    const baselineBoarding = dwellingStops.size * (currentMode === 'night' ? 1 : 2);
    const baselineTrips = busCount + activeTrainTrips + activeShipTrips + feederVehicles.length + Math.min(20, Math.round(baselinePeds * 0.25));

    stats = {
      vehicles: totalVehicles,
      brakingCount,
      yieldingCount,
      pedestrians: (externalPedStats && Number.isFinite(externalPedStats.pedestrians))
        ? externalPedStats.pedestrians
        : baselinePeds,
      boardingCount: (externalPedStats && Number.isFinite(externalPedStats.boardingCount))
        ? externalPedStats.boardingCount
        : baselineBoarding,
      activeTrips: (externalPedStats && Number.isFinite(externalPedStats.activeTrips))
        ? Math.max(busCount + feederVehicles.length, externalPedStats.activeTrips)
        : baselineTrips,
      bellPhase: bell.bellPhase,
      minBusGapM: Number(minBusGapM.toFixed(2)),
      clippingCount,
      overlapCount,
      pedVehicleOverlapCount,
      cyclistVehicleOverlapCount,
      cyclists: cyclists.length,
    };
  }

  function updateToTime(tSec, mode = 'day', externalCrosswalkOcc = null, liveMode = false) {
    const safeT = Number.isFinite(tSec) ? Math.max(0, Math.min(MAX_SIM_TIME, tSec)) : 0;
    const normMode = (mode === 'sunset' || mode === 'night') ? mode : 'day';

    const canLiveCatchup = !!(liveMode && initialized && normMode === currentMode && safeT >= simTime - 1e-6);
    const needReset = !initialized
      || normMode !== currentMode
      || safeT < simTime - 1e-6
      || (!canLiveCatchup && (safeT - simTime) > 2.0);

    if (needReset) {
      const tStart = safeT <= 60 ? 0 : Math.floor(safeT - 60);
      const prevUseExternal = useExternalCrosswalks;
      resetState(normMode, tStart);
      let guard = 0;
      while (simTime + FIXED_DT <= safeT + 1e-9 && guard < 2400) {
        if (safeT - simTime > 2.0) {
          useExternalCrosswalks = false;
          step(FIXED_DT, null);
        } else {
          useExternalCrosswalks = prevUseExternal;
          step(FIXED_DT, externalCrosswalkOcc);
        }
        guard++;
      }
      useExternalCrosswalks = prevUseExternal || !!externalCrosswalkOcc;
    } else if (canLiveCatchup) {
      let guard = 0;
      while (simTime + FIXED_DT <= safeT + 1e-9 && guard < 2) {
        step(FIXED_DT, externalCrosswalkOcc);
        guard++;
      }
      if (safeT - simTime > 0.10) {
        simTime = safeT;
      }
    } else {
      let guard = 0;
      while (simTime + FIXED_DT <= safeT + 1e-9 && guard < 80) {
        step(FIXED_DT, externalCrosswalkOcc);
        guard++;
      }
    }

    subStepRem = Math.max(0, Math.min(FIXED_DT, safeT - simTime));
    lastTargetT = safeT;
    recomputeStats(safeT);
    return getTransitSnapshot();
  }

  function getStats() {
    return { ...stats };
  }

  function getActiveVehiclePositions() {
    const out = [];
    for (let li = 0; li < lanes.length; li++) {
      const lane = lanes[li];
      if (lane.isMotorway) continue;
      const vehs = lane.vehicles;
      for (let i = 0; i < vehs.length; i++) {
        const v = vehs[i];
        out.push({
          id: v.id,
          xM: v.xM,
          yM: v.yM,
          txM: v.txM,
          tyM: v.tyM,
          v: v.v,
          lengthM: v.lengthM,
        });
      }
    }
    for (let i = 0; i < feederVehicles.length; i++) {
      const fv = feederVehicles[i];
      out.push({
        id: fv.id,
        xM: fv.xM,
        yM: fv.yM,
        txM: fv.txM,
        tyM: fv.tyM,
        v: fv.v,
        lengthM: fv.lengthM,
      });
    }
    return out;
  }

  function getTransitSnapshot() {
    const tNow = lastTargetT;
    const trainSnaps = trains.map((tr) => ({
      id: tr.id,
      kind: tr.kind,
      state: evalTrainState(tr, tNow),
    }));
    const shipSnaps = ships.map((sh) => ({
      id: sh.id,
      kind: sh.kind,
      state: evalShipState(sh, tNow, currentMode),
    }));
    const busSnaps = [];
    for (const lane of lanes) {
      for (const v of lane.vehicles) {
        if (v.kind === 'bus' || v.kind === 'bus_artic') {
          busSnaps.push({
            id: v.id,
            specId: v.specId || null,
            roadId: v.roadId,
            routeNum: v.routeNum,
            frac: v.s / lane.rd.length_m,
            speedRatio: v.v / Math.max(0.1, v.v0),
            isDwelling: v.isDwelling,
            dwellingStopIdx: v.dwellingStopIdx,
            braking: v.braking,
            blinker: v.blinker,
          });
        }
      }
    }
    return {
      tSec: tNow,
      mode: currentMode,
      trains: trainSnaps,
      buses: busSnaps,
      ships: shipSnaps,
      dwellingStops: new Set(dwellingStops),
      crosswalks: crosswalkStates.map((c) => ({ ...c })),
      vehiclePositions: getActiveVehiclePositions(),
      wind: getWindVector(tNow),
      bell: evalBellState(tNow, currentMode),
      stats: getStats(),
    };
  }

  function getDrawableVehicles(worldW, worldH, wScale) {
    const buses = [];
    const cars = [];
    const drawCyclists = [];
    const crosswalkWalkers = [];

    const shiftRight = (p, px) => {
      if (!p || Math.abs(px) < 0.01) return p;
      const isoY = 0.55;
      const gx = p.tx;
      const gy = p.ty / isoY;
      const gm = Math.hypot(gx, gy) || 1;
      const rx = -gy / gm;
      const ry = (gx / gm) * isoY;
      return { ...p, wx: p.wx + rx * px, wy: p.wy + ry * px };
    };

    for (const lane of lanes) {
      const rd = lane.rd;
      const L = rd.length_m;
      for (const v of lane.vehicles) {
        const sVis = (((v.s + v.v * subStepRem) % L) + L) % L;
        const frac = sVis / L;
        if (frac < 0.001 || frac > 0.999) continue;

        const signals = {
          braking: v.braking,
          blinker: v.blinker,
          headlightDim: v.headlightDim,
          isDwelling: v.isDwelling,
          speedRatio: v.v / Math.max(0.1, v.v0),
          isDeliveryStop: false,
        };

        if (v.kind === 'bus_artic') {
          const pullPx = v.pullInFrac * 2.0 * wScale;
          const fFront = frac + 9.5 / L;
          const fMidFront = fFront - 10.2 / L;
          const fMidRear = fFront - 11.8 / L;
          const fRear = fFront - 19.0 / L;
          if (fFront <= 0.999 && fRear >= 0.001) {
            const pFront = shiftRight(samplePathAt(rd.pts, fFront, worldW, worldH, 3), pullPx);
            const pMidFront = shiftRight(samplePathAt(rd.pts, fMidFront, worldW, worldH, 3), pullPx);
            const pMidRear = shiftRight(samplePathAt(rd.pts, fMidRear, worldW, worldH, 3), pullPx);
            const pRear = shiftRight(samplePathAt(rd.pts, fRear, worldW, worldH, 3), pullPx);
            if (pFront && pMidFront && pMidRear && pRear) {
              buses.push({
                type: 'bus_artic',
                id: v.id,
                specId: v.specId || null,
                roadId: v.roadId,
                pos: {
                  wx: (pFront.wx + pRear.wx) * 0.5,
                  wy: (pFront.wy + pRear.wy) * 0.5,
                  tx: pFront.tx,
                  ty: pFront.ty,
                  occ: pFront.occ && pRear.occ,
                  d16: Math.round((pFront.d16 + pRear.d16) * 0.5),
                },
                pRear,
                pMidRear,
                pMidFront,
                pFront,
                routeNum: v.routeNum || '161',
                speedRatio: signals.speedRatio,
                isDwelling: v.isDwelling,
                signals,
                tripLabel: v.tripLabel,
              });
              continue;
            }
          }
          const pos = shiftRight(samplePathAt(rd.pts, frac, worldW, worldH, 3), pullPx);
          if (pos) {
            buses.push({
              type: 'bus',
              id: v.id,
              specId: v.specId || null,
              roadId: v.roadId,
              pos,
              routeNum: v.routeNum || '161',
              speedRatio: signals.speedRatio,
              isDwelling: v.isDwelling,
              signals,
              tripLabel: v.tripLabel,
            });
          }
        } else if (v.kind === 'bus') {
          const pullPx = v.pullInFrac * 2.0 * wScale;
          const pos = shiftRight(samplePathAt(rd.pts, frac, worldW, worldH, 3), pullPx);
          if (pos) {
            buses.push({
              type: 'bus',
              id: v.id,
              specId: v.specId || null,
              roadId: v.roadId,
              pos,
              routeNum: v.routeNum,
              speedRatio: signals.speedRatio,
              isDwelling: v.isDwelling,
              signals,
              tripLabel: v.tripLabel,
            });
          }
        } else {
          const pos = samplePathAt(rd.pts, frac, worldW, worldH, 3);
          if (pos) {
            cars.push({
              type: 'car',
              id: v.id,
              roadId: v.roadId,
              pos,
              colorIdx: v.colorIdx,
              signals,
              tripLabel: v.tripLabel,
            });
          }
        }
      }
    }

    for (const fv of feederVehicles) {
      const fd = feederDefs[fv.feederIdx];
      if (!fd || fd.pts.length < 2) continue;
      const dirSign = fv.state === 'outbound_feeder' ? 1 : (fv.state === 'inbound_feeder' ? -1 : 0);
      const visDistFrac = clamp(
        fv.distFrac + dirSign * (fv.v / Math.max(1, fd.lengthM)) * subStepRem,
        0.01,
        0.99,
      );
      const rawFrac = fd.entryAtStart ? visDistFrac : (1.0 - visDistFrac);
      const clampedFrac = clamp(rawFrac, 0.01, 0.99);
      const pos = samplePathAt(fd.pts, clampedFrac, worldW, worldH, 2);
      if (!pos) continue;
      const movingIncreasing = (fv.state === 'outbound_feeder' || fv.state === 'curb_pause')
        ? fd.entryAtStart
        : !fd.entryAtStart;
      const orientedPos = movingIncreasing
        ? pos
        : { ...pos, tx: -pos.tx, ty: -pos.ty };
      cars.push({
        type: 'car',
        id: fv.id,
        roadId: fd.id,
        pos: orientedPos,
        colorIdx: fv.colorIdx,
        signals: {
          braking: fv.braking,
          blinker: fv.blinker,
          headlightDim: fv.headlightDim,
          isDwelling: fv.state === 'curb_pause',
          speedRatio: fv.v / Math.max(0.1, fv.speedMps),
          isDeliveryStop: fv.state === 'curb_pause',
        },
        tripLabel: fv.tripLabel,
      });
    }

    const _cycVisM = { xM: 0, yM: 0, txM: 1, tyM: 0 };
    const _cycVisUv = { u: 0, v: 0 };
    for (const cyc of cyclists) {
      const lane = lanes[cyc.laneIdx];
      if (!lane) continue;
      const L = lane.rd.length_m;
      const sVis = (((cyc.s + cyc.v * subStepRem) % L) + L) % L;
      const frac = sVis / L;
      if (frac < 0.001 || frac > 0.999) continue;
      const base = samplePathAt(lane.rd.pts, frac, worldW, worldH, 3);
      if (!base) continue;
      samplePtsMeters(lane.rd.pts, frac, false, _cycVisM);
      const shoulderM = (lane.rd.kind === 'seestrasse' ? 1.85 : 1.75) + (cyc.latOffset || 0) * 0.25;
      metersToUv(_cycVisM.xM + _cycVisM.tyM * shoulderM, _cycVisM.yM - _cycVisM.txM * shoulderM, _cycVisUv);
      drawCyclists.push({
        type: 'cyclist',
        id: cyc.id,
        pos: { ...base, wx: _cycVisUv.u * worldW, wy: _cycVisUv.v * worldH },
        colorIdx: cyc.colorIdx,
      });
    }

    if (!useExternalCrosswalks) {
      for (let i = 0; i < crosswalkDefs.length; i++) {
        const def = crosswalkDefs[i];
        const st = crosswalkStates[i];
        if (!st || !st.occupied) continue;
        const count = st.walkerCount || 1;
        for (let k = 0; k < count; k++) {
          const p = clamp(st.progress + (k === 1 ? -0.14 : 0), 0, 1);
          const span = (p - 0.5) * 15.0 * st.dir * wScale;
          const along = (k === 1 ? 2.4 : 0) * wScale;
          const wx = def.u * worldW + def.nx * span - def.ny * along;
          const wy = def.v * worldH + def.ny * span * 0.55 + def.nx * along * 0.55;
          crosswalkWalkers.push({
            type: 'crosswalk_walker',
            pos: { wx, wy, d16: def.d16 },
            colorIdx: i * 3 + k,
            stride: lastTargetT * 7.2 + i * 1.9 + k * 2.1,
          });
        }
      }
    }

    return {
      buses,
      cars,
      cyclists: drawCyclists,
      crosswalkWalkers,
      dwellingStops: new Set(dwellingStops),
    };
  }

  function getFollowTarget(kind, worldW, worldH) {
    const tSec = lastTargetT;
    if (kind === 'train' && trains.length > 0) {
      const primary = trains.find((t) => t.id === 'sbb_s8_south') || trains[0];
      const ordered = primary ? [primary, ...trains.filter((t) => t !== primary)] : trains;
      for (const tr of ordered) {
        const st = evalTrainState(tr, tSec);
        if (st.midFrac > 0.04 && st.midFrac < 0.96) {
          const pos = samplePathAt(tr.pts, st.midFrac, worldW, worldH, 2);
          if (pos) return pos;
        }
      }
      if (primary) {
        const st = evalTrainState(primary, tSec);
        const clamped = clamp(st.midFrac >= 0 ? st.midFrac : (primary.stop_frac || 0.5), 0.02, 0.98);
        return samplePathAt(primary.pts, clamped, worldW, worldH, 2);
      }
    } else if (kind === 'boat' && ships.length > 0) {
      const b = ships.find((x) => x.id === 'zsg_ms_helvetia' || x.kind === 'zsg_steamer') || ships[0];
      if (b) {
        const st = evalShipState(b, tSec, currentMode);
        const f = clamp(st.frac >= 0 ? st.frac : 0.02, 0.02, 0.98);
        return samplePathAt(b.pts, f, worldW, worldH, 2);
      }
    } else if (kind === 'bus' && lanes.length > 0) {
      const viaductLane = lanes.find((l) => l.rd.id === 'dorfstrasse_viaduct_up' && l.vehicles.some((v) => v.kind === 'bus' || v.kind === 'bus_artic'))
        || lanes.find((l) => l.vehicles.some((v) => v.kind === 'bus' || v.kind === 'bus_artic'));
      if (viaductLane) {
        const buses = viaductLane.vehicles.filter((v) => v.kind === 'bus' || v.kind === 'bus_artic');
        buses.sort((a, b) => a.busIdx - b.busIdx);
        const chosen = buses.find((b) => {
          const f = b.s / viaductLane.rd.length_m;
          return f > 0.05 && f < 0.95;
        }) || buses[0];
        if (chosen) {
          const L = viaductLane.rd.length_m;
          const sVis = (((chosen.s + chosen.v * subStepRem) % L) + L) % L;
          const f = clamp(sVis / L, 0.01, 0.99);
          return samplePathAt(viaductLane.rd.pts, f, worldW, worldH, 2);
        }
      }
    }
    return null;
  }

  function busRouteSpecSignature(sp) {
    if (!sp) return '';
    return JSON.stringify({
      id: sp.id || null,
      line: sp.line || null,
      name: sp.name || null,
      label: sp.label || null,
      vehicleType: sp.vehicleType || null,
      corridorSegments: sp.corridorSegments || null,
      stops: sp.stops || null,
      timetable: sp.timetable || null,
    });
  }

  function resolveLaneForBusSpec(sp) {
    if (sp && Array.isArray(sp.corridorSegments)) {
      for (let i = 0; i < sp.corridorSegments.length; i++) {
        const seg = sp.corridorSegments[i];
        if (seg && seg.roadId && laneById.has(seg.roadId)) {
          return laneById.get(seg.roadId);
        }
      }
    }
    return laneById.get('seestrasse_sb')
      || lanes.find((l) => !l.isMotorway && activeBusCountForRoad(l.rd, 'day') > 0)
      || lanes.find((l) => !l.isMotorway)
      || lanes[0]
      || null;
  }

  function setBusRouteSpecs(specs) {
    busRouteSpecs = Array.isArray(specs) ? specs.slice() : null;
    if (!initialized) return;

    // Hot-sync buses without disrupting existing cars/cyclists!
    const profile = getDiurnalProfile(currentMode);
    const hasSpecs = Array.isArray(busRouteSpecs) && busRouteSpecs.length > 0;
    const specSigById = new Map();
    if (busRouteSpecs) {
      for (let i = 0; i < busRouteSpecs.length; i++) {
        const sp = busRouteSpecs[i];
        if (sp && sp.id) specSigById.set(sp.id, busRouteSpecSignature(sp));
      }
    }

    // 1. Remove buses whose specId was removed, overwritten in-place, or superseded (legacy specId === null)
    for (let li = 0; li < lanes.length; li++) {
      const lane = lanes[li];
      for (let i = lane.vehicles.length - 1; i >= 0; i--) {
        const v = lane.vehicles[i];
        if (v.kind !== 'bus' && v.kind !== 'bus_artic') continue;
        if (hasSpecs && !v.specId) {
          lane.vehicles.splice(i, 1);
        } else if (v.specId && (!specSigById.has(v.specId) || v.specSig !== specSigById.get(v.specId))) {
          lane.vehicles.splice(i, 1);
        }
      }
    }

    // 2. Spawn buses for newly added or overwritten specs
    if (busRouteSpecs) {
      const existingSpecIds = new Set();
      for (let li = 0; li < lanes.length; li++) {
        const vehs = lanes[li].vehicles;
        for (let i = 0; i < vehs.length; i++) {
          if (vehs[i].specId) existingSpecIds.add(vehs[i].specId);
        }
      }

      for (let si = 0; si < busRouteSpecs.length; si++) {
        const sp = busRouteSpecs[si];
        if (!sp || !sp.id || existingSpecIds.has(sp.id)) continue;
        const tt = sp.timetable || {};
        if (profile.busMode === 'night' && tt.nightActive === false) continue;
        const lane = resolveLaneForBusSpec(sp);
        if (!lane) continue;
        const nBuses = Math.max(1, activeBusCountForRoad(lane.rd, profile.busMode) || 1);
        for (let bIdx = 0; bIdx < nBuses; bIdx++) {
          const bus = makeBusEntity(lane.rd, lane.stopsM, bIdx, nBuses, simTime, profile, sp);
          bus.s = findClearSOnLane(lane, bus.s, bus.lengthM);
          updateVehicleMeters(bus, lane.rd);
          lane.vehicles.push(bus);
        }
        lane.vehicles.sort((a, b) => a.s - b.s);
      }
    }

    resolve2DOverlapsPostStep();
    recomputeStats(lastTargetT);
  }

  function setExternalPedestrians(pedList) {
    externalPedestrians = Array.isArray(pedList) ? pedList : null;
  }

  function setExternalCrosswalkState(cwId, occupied) {
    useExternalCrosswalks = true;
    externalCrosswalkMap.set(cwId, !!occupied);
  }

  function setCrosswalkOverrideMode(useExternal) {
    useExternalCrosswalks = !!useExternal;
  }

  function setExternalPedestrianStats(pedStats) {
    externalPedStats = pedStats || null;
  }

  return {
    updateToTime,
    getStats,
    getTransitSnapshot,
    getDrawableVehicles,
    getFollowTarget,
    setExternalCrosswalkState,
    setCrosswalkOverrideMode,
    setExternalPedestrianStats,
    setBusRouteSpecs,
    setExternalPedestrians,
    getActiveVehiclePositions,
    getSpatialGrid() {
      return spatialGrid;
    },
  };
}
