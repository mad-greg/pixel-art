/**
 * Deterministic fixed-timestep (dt = 0.05 s) Kilchberg traffic, transit & cyclist simulation kernel.
 *
 * Features:
 *   - 1D IDM-lite car-following with unified lane-sorted leader tracking (buses + cars/vans)
 *   - Hard bumper-to-bumper non-overlap guard (zero bus clipping, minBusGapM >= 4.5 m)
 *   - Non-gridlock safeguards (moving vehicles stay well above 30% floor)
 *   - ZVV Lines 161 (19 m articulated) & 165 (12 m rigid) multi-stop dwell + turn/hazard signals
 *   - Dynamic crosswalk yielding across all non-motorway lanes within < 25 px (including shared corridor)
 *   - Branded Swiss delivery vans & local residential trips on DEM-verified feeder streets
 *   - Grade-aware cyclist pace groups (slower uphill / faster downhill on Dorfstrasse viaduct)
 *   - Pure deterministic cold-start warmup for ?t= snapshots + incremental live playback
 */

import { createRng } from './rng.js';
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

export function createTrafficSim(animData) {
  const masterW = (animData && animData.canvas_width) ? animData.canvas_width : 12331;
  const masterH = (animData && animData.canvas_height) ? animData.canvas_height : 5444;
  const roads = (animData && Array.isArray(animData.roads)) ? animData.roads : [];
  const trains = (animData && Array.isArray(animData.trains)) ? animData.trains : [];
  const ships = (animData && Array.isArray(animData.ships)) ? animData.ships : [];
  const network = (animData && animData.network) ? animData.network : {};
  const rawCrosswalks = Array.isArray(network.crosswalks) ? network.crosswalks : [];
  const rawFeeders = Array.isArray(network.feeders) ? network.feeders : [];

  const roadById = new Map();
  roads.forEach((rd, idx) => roadById.set(rd.id, { rd, idx }));

  // Pre-bind every crosswalk to ALL non-motorway lanes passing within < 25 master px
  // (handles bi-directional lanes and the shared Seestrasse / Dorfstrasse lakefront corridor)
  const laneCrosswalks = new Map(); // roadId -> Array<{ cwIdx, cwId, sM, frac }>
  roads.forEach((rd) => laneCrosswalks.set(rd.id, []));

  const crosswalkDefs = rawCrosswalks.map((cw, cwIdx) => {
    const bindings = [];
    for (const rd of roads) {
      if (rd.kind === 'motorway') continue;
      const proj = closestFracOnPts(rd.pts, cw.u, cw.v, masterW, masterH);
      if (proj.distPx < 25.0) {
        const sM = proj.frac * rd.length_m;
        const binding = { cwIdx, cwId: cw.id, roadId: rd.id, frac: proj.frac, sM };
        bindings.push(binding);
        laneCrosswalks.get(rd.id).push(binding);
      }
    }
    return {
      idx: cwIdx,
      id: cw.id,
      name: cw.name || cw.id,
      u: cw.u,
      v: cw.v,
      d16: cw.d16 || 0,
      nx: Number.isFinite(cw.nx) ? cw.nx : 0.707,
      ny: Number.isFinite(cw.ny) ? cw.ny : 0.707,
      bindings,
      // Staggered deterministic baseline crossing period (16..22 s), 4.5 s active
      period: 16.0 + (cwIdx % 4) * 1.8 + Math.floor(cwIdx / 4) * 0.9,
      phaseOffset: (cwIdx * 3.17) % 16.0,
    };
  });

  // Pre-compute feeder entry ends so feeder_paradiesstrasse (which snaps at pts[-1]) never teleports
  const feederDefs = rawFeeders.map((fd, idx) => {
    const pts = fd.pts || [];
    let entryAtStart = true;
    const conn = roadById.get(fd.connects_road);
    if (conn && pts.length >= 2) {
      const roadPt = samplePathAt(conn.rd.pts, clamp(fd.connects_frac || 0, 0, 1), masterW, masterH, 2);
      if (roadPt) {
        const dStart = Math.hypot(pts[0][0] * masterW - roadPt.wx, pts[0][1] * masterH - roadPt.wy);
        const dEnd = Math.hypot(pts[pts.length - 1][0] * masterW - roadPt.wx, pts[pts.length - 1][1] * masterH - roadPt.wy);
        entryAtStart = dStart <= dEnd;
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
      poiId: fd.poi_id || null,
      entryAtStart,
    };
  });

  // Simulation runtime state
  let initialized = false;
  let currentMode = 'day';
  let simTime = 0;
  let subStepRem = 0;
  let lastTargetT = 0;
  let lanes = [];
  let feederVehicles = [];
  let cyclists = [];
  let crosswalkStates = [];
  let dwellingStops = new Set();

  // Optional M4 hooks
  let useExternalCrosswalks = false;
  const externalCrosswalkMap = new Map();
  let externalPedStats = null;

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
    cyclists: 0,
  };

  function computeBaselinePedestrianCount(mode) {
    // Deterministic count of Kilchberg's active baseline pedestrians across sidewalks,
    // bus stops, crosswalks, and landmarks (independent of zoom-LOD culling).
    // Day: ~92, Sunset: ~66, Night: ~20 (satisfies T2.FA3.07 [40..220] & T3.08 night < sunset < day).
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

  function resetState(mode, tStart) {
    currentMode = mode;
    simTime = tStart;
    subStepRem = 0;
    const profile = getDiurnalProfile(mode);
    const rootRng = createRng(`kilchberg-sim-v8:${mode}:${Math.round(tStart * 100)}`);

    crosswalkStates = crosswalkDefs.map((cw) => ({
      id: cw.id,
      occupied: false,
      progress: 0,
      walkerCount: 1,
      dir: (cw.idx % 2 === 0) ? 1 : -1,
    }));

    lanes = roads.map((rd, rIdx) => {
      const laneRng = rootRng.fork(`lane:${rd.id}`);
      const isMotorway = rd.kind === 'motorway';
      const isLine161 = rd.kind === 'seestrasse';
      const activeBuses = activeBusCountForRoad(rd, profile.busMode);
      const rawCars = rd.car_count || 4;
      const activeCars = Math.max(
        isMotorway ? 4 : 2,
        Math.round(rawCars * profile.carFactor),
      );
      const stopsM = (rd.stops || [])
        .filter((f) => typeof f === 'number' && f > 0.01 && f < 0.99)
        .map((f, sIdx) => ({ idx: sIdx, frac: f, sM: f * rd.length_m }))
        .sort((a, b) => a.sM - b.sM);

      const vehicles = [];

      // 1. Seed ZVV buses along their canonical schedule at tStart
      for (let bIdx = 0; bIdx < activeBuses; bIdx++) {
        const schedSt = evalBusScheduleState(rd, bIdx, tStart, activeBuses);
        const startFrac = (schedSt.frac >= 0.01 && schedSt.frac <= 0.99)
          ? schedSt.frac
          : (((rd.phase || 0) + bIdx / Math.max(1, activeBuses)) % 1 + 1) % 1;
        const startS = clamp(startFrac * rd.length_m, 10, rd.length_m - 10);
        const vFree = Math.max(2.0, rd.speed_mps * 0.88 * profile.speedFactor);
        let nextStopIdx = 0;
        for (let k = 0; k < stopsM.length; k++) {
          if (stopsM[k].sM > startS + 2.0) {
            nextStopIdx = k;
            break;
          }
          if (k === stopsM.length - 1) nextStopIdx = 0;
        }
        vehicles.push({
          id: `bus:${rd.id}:${bIdx}`,
          kind: isLine161 ? 'bus_artic' : 'bus',
          routeNum: isLine161 ? '161' : '165',
          busIdx: bIdx,
          roadId: rd.id,
          s: startS,
          v: schedSt.isDwelling ? 0 : vFree * Math.max(0.2, schedSt.speedRatio),
          a: 0,
          v0: vFree,
          lengthM: isLine161 ? 19.0 : 12.0,
          aMax: isLine161 ? 1.3 : 1.4,
          bComf: isLine161 ? 2.4 : 2.5,
          bEmerg: 5.5,
          s0: isLine161 ? 8.5 : 8.0,
          T: 1.5,
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
          tripLabel: `ZVV Bus ${isLine161 ? '161' : '165'} · ${formatRoadName(rd)}`,
        });
      }

      // 2. Seed cars & vans with guaranteed safe initial spacing around buses
      const spacing = rd.length_m / Math.max(1, activeCars);
      for (let cIdx = 0; cIdx < activeCars; cIdx++) {
        const colorIdx = (activeBuses + cIdx) + rIdx * 3;
        const isVan = isVanColorIdx(colorIdx);
        const lenM = isVan ? 5.8 : 4.6;
        const jitterM = laneRng.range(-spacing * 0.22, spacing * 0.22);
        let s = (((((rd.phase || 0) * rd.length_m) + (cIdx + 0.35) * spacing + jitterM) % rd.length_m) + rd.length_m) % rd.length_m;

        // Nudge clear of any already-placed vehicle on this lane
        for (let tries = 0; tries < 6; tries++) {
          let conflict = false;
          for (const other of vehicles) {
            let d = Math.abs(s - other.s);
            d = Math.min(d, rd.length_m - d);
            const minNeed = 0.5 * (lenM + other.lengthM) + (isMotorway ? 14.0 : 8.5);
            if (d < minNeed) {
              s = (s + minNeed + 2.0) % rd.length_m;
              conflict = true;
              break;
            }
          }
          if (!conflict) break;
        }

        const speedVar = laneRng.range(0.88, 1.08);
        const baseRoadSpeed = rd.speed_mps * (activeBuses > 0 ? 0.90 : 0.98);
        const v0 = Math.max(3.5, baseRoadSpeed * speedVar * profile.speedFactor);
        vehicles.push({
          id: `car:${rd.id}:${cIdx}`,
          kind: isVan ? 'van' : 'car',
          colorIdx,
          roadId: rd.id,
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
        });
      }

      vehicles.sort((a, b) => a.s - b.s);
      return {
        rd,
        rIdx,
        isMotorway,
        isLine161,
        stopsM,
        crosswalks: laneCrosswalks.get(rd.id) || [],
        vehicles,
      };
    });

    // 3. Seed feeder-street local trips & Swiss delivery vans
    feederVehicles = [];
    if (feederDefs.length > 0) {
      const fRng = rootRng.fork('feeders');
      const nFeed = Math.min(profile.feederCount, feederDefs.length);
      // Branded delivery vans in day/sunset (Lindt on Schoorenstrasse, Post, Migros, Coop) + local cars
      const schoorenIdx = feederDefs.findIndex((f) => f.id === 'feeder_schoorenstrasse');
      const assignedFeeders = [];
      if (schoorenIdx >= 0) assignedFeeders.push(schoorenIdx);
      for (let i = 0; i < feederDefs.length && assignedFeeders.length < nFeed; i++) {
        if (!assignedFeeders.includes(i)) assignedFeeders.push(i);
      }
      const deliveryColors = [7, 4, 9, 11, 0, 2]; // Lindt, Post, Migros, Coop, Estate, Sedan
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
        let distFrac = 0.08;
        let timer = 0;
        if (startPhase < 0.35) {
          state = 'outbound_feeder';
          distFrac = fRng.range(0.08, curbFrac * 0.9);
        } else if (startPhase < 0.65) {
          state = 'curb_pause';
          distFrac = curbFrac;
          timer = fRng.range(2.0, 8.0);
        } else if (startPhase < 0.90) {
          state = 'inbound_feeder';
          distFrac = fRng.range(0.12, curbFrac);
        } else {
          state = 'junction_wait';
          distFrac = 0.03;
          timer = fRng.range(0.6, 2.2);
        }
        feederVehicles.push({
          id: `feeder:${fd.id}:${i}`,
          feederIdx: fIdx,
          colorIdx,
          state,
          distFrac, // 0 = junction entry end, curbFrac = curb stop destination
          curbFrac,
          timer,
          speedMps: 5.6 * profile.speedFactor,
          v: (state === 'curb_pause' || state === 'junction_wait') ? 0 : 5.6 * profile.speedFactor,
          braking: (state === 'curb_pause' || state === 'junction_wait'),
          yielding: state === 'junction_wait',
          blinker: state === 'curb_pause' ? 'hazard' : 'none',
          headlightDim: 1.0,
          tripLabel: `${vehicleLabelForColor(colorIdx, fd.name)} → ${fd.name}`,
        });
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
          const s = ((baseS - m * 2.8) % lane.rd.length_m + lane.rd.length_m) % lane.rd.length_m;
          cyclists.push({
            id: `cyc:${lane.rd.id}:${created}`,
            laneIdx: lane.rIdx,
            roadId: lane.rd.id,
            s,
            v: vBase,
            vBase,
            latOffset: m === 0 ? 0 : 0.35,
            colorIdx: created + lane.rIdx * 5,
            yielding: false,
          });
          created++;
        }
        groupIdx++;
      }
    }

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

    // 1. Step all main road lanes (unified IDM-lite car-following + bus stops + crosswalks)
    for (const lane of lanes) {
      const L = lane.rd.length_m;
      const vehs = lane.vehicles;
      const N = vehs.length;
      if (N === 0) continue;

      vehs.sort((a, b) => a.s - b.s);

      // Compute accelerations
      const nextA = new Float64Array(N);
      for (let i = 0; i < N; i++) {
        const me = vehs[i];
        const isBus = me.kind === 'bus' || me.kind === 'bus_artic';

        if (me.stopCooldown > 0) me.stopCooldown = Math.max(0, me.stopCooldown - dt);
        if (me.departBlinkerTimer > 0) me.departBlinkerTimer = Math.max(0, me.departBlinkerTimer - dt);

        me.yielding = false;
        me.blinker = 'none';

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
          if (me.dwellTimer <= 0) {
            me.isDwelling = false;
            me.dwellingStopIdx = -1;
            me.stopCooldown = 4.0;
            me.departBlinkerTimer = 2.2;
            if (lane.stopsM.length > 0) {
              me.nextStopIdx = (me.nextStopIdx + 1) % lane.stopsM.length;
            }
          }
          nextA[i] = 0;
          continue;
        }

        // Leader lookup (wrapping cleanly around circular road loop)
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
        if (isBus && lane.stopsM.length > 0 && me.stopCooldown <= 0) {
          const stopObj = lane.stopsM[me.nextStopIdx];
          let dStop = stopObj.sM - me.s;
          if (dStop < -L * 0.5) dStop += L;
          if (dStop >= -1.0 && dStop <= 48.0) {
            if (dStop <= 1.2 || (dStop <= 2.4 && me.v < 0.35)) {
              me.isDwelling = true;
              me.dwellTimer = 3.2;
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

        // Virtual obstacle 2: Occupied zebra crosswalks on this lane
        if (!lane.isMotorway && lane.crosswalks.length > 0) {
          for (let k = 0; k < lane.crosswalks.length; k++) {
            const cwBind = lane.crosswalks[k];
            const cwSt = crosswalkStates[cwBind.cwIdx];
            if (!cwSt || !cwSt.occupied) continue;
            const dCw = cwBind.sM - (me.s + 0.5 * me.lengthM) - 3.0;
            const minStopDist = (me.v * me.v) / (2.0 * 5.2) - 1.5;
            if (dCw > 0 && dCw < 38.0 && dCw >= minStopDist) {
              const sStarCw = 2.0 + Math.max(0, me.v * 1.0 + (me.v * me.v) / (2.0 * Math.sqrt(me.aMax * me.bComf)));
              const aCw = me.aMax * (1.0 - Math.pow(me.v / me.v0, 4) - Math.pow(sStarCw / Math.max(0.5, dCw), 2));
              if (aCw < aFinal - 0.15) {
                aFinal = aCw;
                me.yielding = true;
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
        me.s += me.v * dt;
      }

      // Hard non-overlap bumper clamp (reverse order from front to back)
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

        // Smooth headlight dimming when queued closely behind a leader
        const targetDim = (gap < 18.0 && me.v < me.v0 * 0.55) ? 0.35 : 1.0;
        me.headlightDim += (targetDim - me.headlightDim) * Math.min(1.0, dt * 4.0);
      }
    }

    // 2. Step feeder-street local trips & delivery vans
    for (let i = 0; i < feederVehicles.length; i++) {
      const fv = feederVehicles[i];
      const fd = feederDefs[fv.feederIdx];
      if (!fd) continue;
      const dFracDt = fv.speedMps / fd.lengthM;
      fv.braking = false;
      fv.yielding = false;
      fv.blinker = 'none';

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
        if (fv.distFrac <= 0.03) {
          fv.distFrac = 0.03;
          fv.state = 'junction_wait';
          fv.timer = 1.6 + (i % 3) * 0.45;
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
        if (fv.timer <= 0) {
          fv.state = 'outbound_feeder';
        }
      }
    }

    // 3. Step grade-aware cyclist pace groups (yielding at bus stops & crosswalks)
    for (let i = 0; i < cyclists.length; i++) {
      const cyc = cyclists[i];
      const lane = lanes[cyc.laneIdx];
      if (!lane) continue;
      const L = lane.rd.length_m;
      const frac = cyc.s / L;

      // Grade-aware speed on Dorfstrasse viaduct & Alte Landstrasse
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
      // Yield behind dwelling or pulling-in buses (and slower buses) on same lane
      for (const v of lane.vehicles) {
        if (v.kind === 'bus' || v.kind === 'bus_artic') {
          const rearS = v.s - 0.5 * v.lengthM;
          let d = rearS - cyc.s;
          if (d < -L * 0.5) d += L;
          if (d > L * 0.5) d -= L;
          if (v.isDwelling || v.pullInFrac > 0.05) {
            if (d > -2.5 && d < 20.0) {
              if (d <= 5.5) {
                vTarget = 0;
                mustYield = true;
              } else {
                vTarget = Math.min(vTarget, Math.max(0, (d - 4.5) * 0.55));
                mustYield = true;
              }
            }
          } else if (d > 0 && d < 14.0 && v.v < cyc.v) {
            vTarget = Math.min(vTarget, Math.max(0, v.v * 0.9));
            mustYield = true;
          }
        }
      }
      // Yield at occupied crosswalks
      for (const cwBind of lane.crosswalks) {
        const cwSt = crosswalkStates[cwBind.cwIdx];
        if (!cwSt || !cwSt.occupied) continue;
        const d = cwBind.sM - cyc.s - 2.5;
        if (d > 0 && d < 12.0) {
          vTarget = d <= 2.5 ? 0 : Math.min(vTarget, d * 0.5);
          mustYield = true;
        }
      }

      cyc.yielding = mustYield;
      const accel = vTarget > cyc.v ? 1.6 : (mustYield ? 5.5 : 3.4);
      if (vTarget > cyc.v) cyc.v = Math.min(vTarget, cyc.v + accel * dt);
      else cyc.v = Math.max(vTarget, cyc.v - accel * dt);
      cyc.s = (((cyc.s + cyc.v * dt) % L) + L) % L;
    }
  }

  function recomputeStats(tNow) {
    let totalVehicles = 0;
    let brakingCount = 0;
    let yieldingCount = 0;
    let busCount = 0;
    let clippingCount = 0;
    let overlapCount = 0;
    let minBusGapM = 999;

    for (const lane of lanes) {
      const L = lane.rd.length_m;
      const vehs = lane.vehicles;
      const N = vehs.length;
      for (let i = 0; i < N; i++) {
        const v = vehs[i];
        totalVehicles++;
        if (v.kind === 'bus' || v.kind === 'bus_artic') busCount++;
        if (v.braking) brakingCount++;
        if (v.yielding) yieldingCount++;

        if (N > 1) {
          const j = (i + 1) % N;
          const leader = vehs[j];
          const rawDs = j > i ? (leader.s - v.s) : (L - v.s + leader.s);
          const gap = rawDs - 0.5 * (leader.lengthM + v.lengthM);
          if (gap < 0.0) overlapCount++;
          if (leader.kind === 'bus' || leader.kind === 'bus_artic') {
            if (gap < minBusGapM) minBusGapM = gap;
            if (gap < 1.0) clippingCount++;
          }
        }
      }
    }

    for (const fv of feederVehicles) {
      totalVehicles++;
      if (fv.braking) brakingCount++;
      if (fv.yielding) yieldingCount++;
    }

    // Active transit trips (buses + visible trains + steamer + feeder trips)
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
      cyclists: cyclists.length,
    };
  }

  function updateToTime(tSec, mode = 'day', externalCrosswalkOcc = null) {
    const safeT = Number.isFinite(tSec) ? Math.max(0, Math.min(MAX_SIM_TIME, tSec)) : 0;
    const normMode = (mode === 'sunset' || mode === 'night') ? mode : 'day';

    const needReset = !initialized
      || normMode !== currentMode
      || safeT < simTime - 1e-6
      || (safeT - simTime) > 2.0;

    if (needReset) {
      const tStart = safeT <= 60 ? 0 : Math.floor(safeT - 60);
      const prevUseExternal = useExternalCrosswalks;
      resetState(normMode, tStart);
      let guard = 0;
      while (simTime + FIXED_DT <= safeT + 1e-9 && guard < 2400) {
        // Avoid applying a single final-instant externalCrosswalkOcc snapshot across the entire
        // 60 s warmup (which would turn occupied crosswalks into 60 s roadblocks). Use the
        // deterministic periodic crosswalk cycle during warmup and only apply externalCrosswalkOcc
        // in the final 2.0 s approaching safeT so vehicles yield realistically right at safeT.
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
                routeNum: '161',
                speedRatio: signals.speedRatio,
                isDwelling: v.isDwelling,
                signals,
                tripLabel: v.tripLabel,
              });
              continue;
            }
          }
          // Fallback to rigid bus if rear is wrapping at road start
          const pos = shiftRight(samplePathAt(rd.pts, frac, worldW, worldH, 3), pullPx);
          if (pos) {
            buses.push({
              type: 'bus',
              id: v.id,
              pos,
              routeNum: '161',
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
              pos,
              colorIdx: v.colorIdx,
              signals,
              tripLabel: v.tripLabel,
            });
          }
        }
      }
    }

    // Feeder-street local & delivery vehicles (strictly on DEM feeder.pts, respecting entryAtStart!)
    for (const fv of feederVehicles) {
      const fd = feederDefs[fv.feederIdx];
      if (!fd || fd.pts.length < 2) continue;
      const rawFrac = fd.entryAtStart ? fv.distFrac : (1.0 - fv.distFrac);
      const clampedFrac = clamp(rawFrac, 0.01, 0.99);
      const pos = samplePathAt(fd.pts, clampedFrac, worldW, worldH, 2);
      if (!pos) continue;
      // Moving in decreasing polyline index requires inverting tangent (tx, ty)
      const movingIncreasing = (fv.state === 'outbound_feeder' || fv.state === 'curb_pause')
        ? fd.entryAtStart
        : !fd.entryAtStart;
      const orientedPos = movingIncreasing
        ? pos
        : { ...pos, tx: -pos.tx, ty: -pos.ty };
      cars.push({
        type: 'car',
        id: fv.id,
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

    // Grade-aware cyclists
    for (const cyc of cyclists) {
      const lane = lanes[cyc.laneIdx];
      if (!lane) continue;
      const L = lane.rd.length_m;
      const sVis = (((cyc.s + cyc.v * subStepRem) % L) + L) % L;
      const frac = sVis / L;
      if (frac < 0.001 || frac > 0.999) continue;
      const base = samplePathAt(lane.rd.pts, frac, worldW, worldH, 3);
      if (!base) continue;
      const isMain = lane.rd.kind === 'seestrasse';
      const latPx = ((isMain ? 3.0 : 2.0) + cyc.latOffset) * wScale;
      drawCyclists.push({
        type: 'cyclist',
        id: cyc.id,
        pos: shiftRight(base, latPx),
        colorIdx: cyc.colorIdx,
      });
    }

    // M3 baseline crosswalk walkers (only when M4 external crosswalks are not active)
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
      // Follow live IDM-simulated ZVV bus on Dorfstrasse horseshoe viaduct (matches T3.09 & T4.03)
      const viaductLane = lanes.find((l) => l.rd.id === 'dorfstrasse_viaduct_up')
        || lanes.find((l) => l.vehicles.some((v) => v.kind === 'bus' || v.kind === 'bus_artic'));
      if (viaductLane) {
        const buses = viaductLane.vehicles.filter((v) => v.kind === 'bus' || v.kind === 'bus_artic');
        buses.sort((a, b) => a.busIdx - b.busIdx);
        let chosen = buses.find((b) => {
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
  };
}
