/**
 * Deterministic Fixed-Timestep O-D Pedestrian, Transit-Transfer & Micro-Archetype Engine.
 *
 * Features:
 *  - Fixed dt = 0.05 s (20 Hz) with deterministic cold-start warmup matching traffic.js
 *  - Zero Math.random() (100% seeded mulberry32 from rng.js)
 *  - Bahnhof Kilchberg S8/S24 pre-arrival gathering, platform boarding & alighting dispersal
 *  - ZVV Bus 161/165 stop queueing, boarding during bus dwell & alighting dispersal
 *  - Bendlikon ZSG Pier passenger flow across gangplank (zero teleporting)
 *  - Lindt Home of Chocolate visitors (approach -> plaza admire -> exit with Lindt bags)
 *  - Swiss zebra crosswalk curb-wait & crossing driving traffic.js car yielding
 *  - Human micro-archetypes (dog walkers, strollers, couples, joggers, schoolkids, Seebad bathers)
 *  - 3-5 s social pauses at Dorfbrunnen fountains, lakefront benches, and harbor railing
 *  - Diurnal density curve (night < sunset < day) & zoom-independent simStats telemetry
 */

import { createRng } from './rng.js';
import {
  evalBusScheduleState,
  evalShipState,
  evalTrainState,
  formatRoadName,
  getDiurnalProfile,
  samplePathAt,
} from './schedule.js';
import { shadeHex } from '../render/vehicles.js';
import { drawMiniPerson } from '../render/vignettes.js';

export const PED_FIXED_DT = 0.05;
const MAX_SIM_TIME = 1e9;
const MIN_BUS_TRANSIT_SEC = 8.0;

const COAT_PALETTE = [
  '#c53030', '#2b6cb0', '#2f855a', '#d69e2e',
  '#6b46c1', '#dd6b20', '#334155', '#2c7a7b',
  '#b83280', '#4a5568', '#1e40af', '#0f766e',
];
const JOGGER_TOPS = ['#ef4444', '#06b6d4', '#eab308', '#10b981', '#f97316', '#38bdf8'];
const SCHOOL_BAGS = ['#ef4444', '#3b82f6', '#eab308', '#10b981', '#ec4899', '#8b5cf6'];
const HAIR_PALETTE = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];
const DOG_COLORS = ['#9c6b3b', '#4a3728', '#d4b483', '#2d2d2d', '#b87a4b'];
const PANTS_COLORS = ['#1e293b', '#263040', '#334155', '#1f2937', '#2b3a4a'];

const ROLE_COUNTS = {
  day: {
    rail_commuter: 19,
    bus_rider: 24,
    pier_pax: 10,
    lindt_visitor: 12,
    crosswalk_commuter: 12,
    dog_walker: 7,
    stroller_parent: 5,
    couple: 7,
    jogger: 6,
    schoolkid: 9,
    seebad_bather: 7,
    village_walker: 18,
  },
  sunset: {
    rail_commuter: 17,
    bus_rider: 20,
    pier_pax: 8,
    lindt_visitor: 8,
    crosswalk_commuter: 9,
    dog_walker: 6,
    stroller_parent: 3,
    couple: 8,
    jogger: 7,
    schoolkid: 2,
    seebad_bather: 3,
    village_walker: 12,
  },
  night: {
    rail_commuter: 8,
    bus_rider: 8,
    pier_pax: 4,
    lindt_visitor: 2,
    crosswalk_commuter: 4,
    dog_walker: 2,
    stroller_parent: 0,
    couple: 2,
    jogger: 0,
    schoolkid: 0,
    seebad_bather: 0,
    village_walker: 8,
  },
};

const INITIAL_IN_TRANSIT = {
  day: { rail: 4, pier: 3 },
  sunset: { rail: 3, pier: 2 },
  night: { rail: 2, pier: 1 },
};

function clamp(x, lo, hi) {
  return x < lo ? lo : (x > hi ? hi : x);
}

function normModeName(mode) {
  return (mode === 'night' || mode === 'sunset') ? mode : 'day';
}

function getActiveBusCountForMode(rd, mode) {
  const base = rd.bus_count != null ? rd.bus_count : (rd.has_bus ? 1 : 0);
  if (base <= 0) return 0;
  if (mode === 'night') return 1;
  if (mode === 'sunset' && (rd.id === 'dorfstrasse_viaduct_up' || rd.id === 'dorfstrasse_viaduct_dn')) {
    return Math.min(base, 1);
  }
  return base;
}

/**
 * Render a single pedestrian entity (including micro-archetype details: dog on leash,
 * stroller, walking partner, Lindt bag, backpack, jogger stride) onto targetCtx.
 */
export function drawPedestrianEntity(targetCtx, cam, item, wScale, mode, _tSec) {
  const { scale, offsetX, offsetY, width: canvasW, height: canvasH } = cam;
  const isNight = mode === 'night';
  const sBase = scale * wScale * (item.role === 'schoolkid' ? 0.82 : 0.92);
  const sx = offsetX + item.pos.wx * scale;
  const sy = offsetY + item.pos.wy * scale;
  const pad = 28 * Math.max(0.8, sBase);
  if (sx < -pad || sx > canvasW + pad || sy < -pad || sy > canvasH + pad) return;

  const tx = item.pos.tx || 1;
  const ty = item.pos.ty || 0;
  const tMag = Math.hypot(tx, ty) || 1;
  const ux = tx / tMag;
  const uy = ty / tMag;
  const px = Math.max(0.75, sBase);

  const coat = shadeHex(item.coatCol, 1.0, mode);
  const pants = shadeHex(item.pantsCol, 1.0, mode);

  // Walking couple: draw back partner first for clean depth ordering
  if (item.partnerCoat) {
    const latX = -uy * 2.5 * px;
    const latY = ux * 1.45 * px;
    const pSx = sx + latX;
    const pSy = sy + latY;
    const partnerCoat = shadeHex(item.partnerCoat, 1.0, mode);
    if (latY < 0) {
      drawMiniPerson(targetCtx, pSx, pSy, sBase * 0.96, partnerCoat, pants, item.partnerHair || item.hairCol, isNight, item.stridePhase + 0.35, null, canvasW, canvasH);
      drawMiniPerson(targetCtx, sx, sy, sBase, coat, pants, item.hairCol, isNight, item.stridePhase, item.bagCol, canvasW, canvasH);
    } else {
      drawMiniPerson(targetCtx, sx, sy, sBase, coat, pants, item.hairCol, isNight, item.stridePhase, item.bagCol, canvasW, canvasH);
      drawMiniPerson(targetCtx, pSx, pSy, sBase * 0.96, partnerCoat, pants, item.partnerHair || item.hairCol, isNight, item.stridePhase + 0.35, null, canvasW, canvasH);
    }
    return;
  }

  // Primary person
  drawMiniPerson(targetCtx, sx, sy, sBase, coat, pants, item.hairCol, isNight, item.stridePhase, item.bagCol, canvasW, canvasH);

  // Dog walker: subtle leash + tiny animated trotting dog ahead
  if (item.hasDog) {
    const dogX = sx + ux * 3.1 * px;
    const dogY = sy + uy * 2.0 * px;
    const trot = Math.abs(Math.sin(item.stridePhase * 1.45)) * 0.65 * px;
    const tailWag = Math.sin(item.stridePhase * 2.8) * 0.7 * px;
    targetCtx.strokeStyle = isNight ? 'rgba(180,192,210,0.45)' : 'rgba(60,52,44,0.55)';
    targetCtx.lineWidth = Math.max(0.7, 0.65 * px);
    targetCtx.beginPath();
    targetCtx.moveTo(sx + ux * 0.8 * px, sy - 2.6 * px);
    targetCtx.lineTo(dogX, dogY - 1.1 * px);
    targetCtx.stroke();

    const dogCol = shadeHex(item.dogCol || '#9c6b3b', 1.0, mode);
    targetCtx.fillStyle = isNight ? 'rgba(6,10,20,0.38)' : 'rgba(18,24,32,0.24)';
    targetCtx.fillRect(Math.round(dogX - 1.2 * px), Math.round(dogY + 0.2 * px), Math.max(2, Math.round(2.4 * px)), Math.max(1, Math.round(0.9 * px)));
    targetCtx.fillStyle = dogCol;
    targetCtx.fillRect(Math.round(dogX - 1.1 * px), Math.round(dogY - 1.4 * px - trot), Math.max(2, Math.round(2.3 * px)), Math.max(1.2, Math.round(1.3 * px)));
    targetCtx.fillRect(Math.round(dogX + ux * 1.0 * px - 0.5 * px), Math.round(dogY - 2.0 * px - trot), Math.max(1, Math.round(1.0 * px)), Math.max(1, Math.round(1.0 * px)));
    targetCtx.fillRect(Math.round(dogX - ux * 1.2 * px), Math.round(dogY - 1.9 * px - trot + tailWag * 0.4), Math.max(1, Math.round(0.8 * px)), Math.max(1, Math.round(0.8 * px)));
  }

  // Parent with stroller: compact pixel stroller pushed ahead
  if (item.hasStroller) {
    const stX = sx + ux * 2.5 * px;
    const stY = sy + uy * 1.6 * px;
    targetCtx.strokeStyle = isNight ? '#64748b' : '#334155';
    targetCtx.lineWidth = Math.max(0.8, 0.7 * px);
    targetCtx.beginPath();
    targetCtx.moveTo(sx + ux * 0.7 * px, sy - 3.2 * px);
    targetCtx.lineTo(stX, stY - 2.2 * px);
    targetCtx.stroke();
    targetCtx.fillStyle = shadeHex('#1e3a5f', 1.0, mode);
    targetCtx.fillRect(Math.round(stX - 1.2 * px), Math.round(stY - 3.0 * px), Math.max(2, Math.round(2.6 * px)), Math.max(2, Math.round(2.0 * px)));
    targetCtx.fillStyle = shadeHex('#cbd5e1', 1.0, mode);
    targetCtx.fillRect(Math.round(stX - 0.9 * px), Math.round(stY - 2.6 * px), Math.max(1.5, Math.round(1.6 * px)), Math.max(1, Math.round(0.9 * px)));
    targetCtx.fillStyle = '#0f172a';
    const wSz = Math.max(1, Math.round(0.85 * px));
    targetCtx.fillRect(Math.round(stX - 1.1 * px), Math.round(stY - 0.6 * px), wSz, wSz);
    targetCtx.fillRect(Math.round(stX + 0.5 * px), Math.round(stY - 0.6 * px), wSz, wSz);
  }
}

export function createPedestrianSim(animData) {
  const masterW = (animData && animData.canvas_width) || 12331;
  const masterH = (animData && animData.canvas_height) || 5444;
  const depthMin = (animData && typeof animData.depth_min === 'number') ? animData.depth_min : -2400.0;
  const depthMax = (animData && typeof animData.depth_max === 'number') ? animData.depth_max : 2400.0;
  const mppMaster = (animData && typeof animData.mpp === 'number') ? animData.mpp : 0.25;
  const depthSlopeGround = mppMaster * Math.sqrt(3) * (65535.0 / Math.max(1.0, depthMax - depthMin));
  const network = (animData && animData.network) || {};
  const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};
  const roads = (animData && animData.roads) || [];
  const trains = (animData && animData.trains) || [];
  const ships = (animData && animData.ships) || [];

  const poisList = Array.isArray(network.pois) ? network.pois : [];
  const poiById = new Map();
  for (const p of poisList) poiById.set(p.id, p);

  // Build undirected footpath graph + all-pairs shortest-path next-hop table
  const footpaths = Array.isArray(network.footpaths) ? network.footpaths : [];
  const adj = new Map();
  const edgeById = new Map();
  const fpNodes = new Set();

  for (const fp of footpaths) {
    if (!fp || !Array.isArray(fp.pts) || fp.pts.length < 2) continue;
    const lenM = Math.max(10, fp.length_m || 120);
    edgeById.set(fp.id, fp);
    fpNodes.add(fp.from_poi);
    fpNodes.add(fp.to_poi);
    if (!adj.has(fp.from_poi)) adj.set(fp.from_poi, []);
    if (!adj.has(fp.to_poi)) adj.set(fp.to_poi, []);
    adj.get(fp.from_poi).push({ edgeId: fp.id, toNode: fp.to_poi, pts: fp.pts, lengthM: lenM, forward: true, kind: fp.kind || 'village' });
    adj.get(fp.to_poi).push({ edgeId: fp.id, toNode: fp.from_poi, pts: fp.pts, lengthM: lenM, forward: false, kind: fp.kind || 'village' });
  }

  const fpNodeList = Array.from(fpNodes);
  const nextHop = new Map();

  for (const src of fpNodeList) {
    const dist = new Map();
    const firstStep = new Map();
    const visited = new Set();
    dist.set(src, 0);
    while (visited.size < fpNodeList.length) {
      let best = null;
      let bestD = Infinity;
      for (const [k, d] of dist.entries()) {
        if (!visited.has(k) && d < bestD) {
          bestD = d;
          best = k;
        }
      }
      if (!best) break;
      visited.add(best);
      const edges = adj.get(best) || [];
      for (const e of edges) {
        const nd = bestD + e.lengthM;
        if (nd < (dist.get(e.toNode) ?? Infinity)) {
          dist.set(e.toNode, nd);
          firstStep.set(e.toNode, best === src ? e : firstStep.get(best));
        }
      }
    }
    for (const dst of fpNodeList) {
      if (dst !== src && firstStep.has(dst)) {
        nextHop.set(`${src}|${dst}`, firstStep.get(dst));
      }
    }
  }

  function findFootpathRoute(fromId, toId) {
    if (!fromId || !toId || fromId === toId) return [];
    const steps = [];
    let cur = fromId;
    let guard = 0;
    while (cur !== toId && guard < 20) {
      const step = nextHop.get(`${cur}|${toId}`);
      if (!step) return [];
      steps.push(step);
      cur = step.toNode;
      guard++;
    }
    return cur === toId ? steps : [];
  }

  // Feeder street polylines (respecting entryAtStart polarity)
  const feeders = (Array.isArray(network.feeders) ? network.feeders : [])
    .filter((f) => f && Array.isArray(f.pts) && f.pts.length >= 2)
    .map((f) => {
      const road = roads.find((r) => r.id === f.connects_road);
      let entryAtStart = true;
      if (road && road.pts && road.pts.length >= 2 && typeof f.connects_frac === 'number') {
        const jPos = samplePathAt(road.pts, clamp(f.connects_frac, 0, 1), masterW, masterH, 2);
        if (jPos) {
          const p0 = f.pts[0];
          const p1 = f.pts[f.pts.length - 1];
          const d0 = Math.hypot(p0[0] * masterW - jPos.wx, p0[1] * masterH - jPos.wy);
          const d1 = Math.hypot(p1[0] * masterW - jPos.wx, p1[1] * masterH - jPos.wy);
          entryAtStart = d0 <= d1;
        }
      }
      return {
        id: f.id,
        name: f.name || f.id,
        kind: f.kind || 'residential',
        pts: f.pts,
        lengthM: Math.max(25, f.length_m || 140),
        poiId: f.poi_id || null,
        entryAtStart,
      };
    });
  const feederById = new Map();
  for (const fd of feeders) feederById.set(fd.id, fd);

  // Non-motorway road sidewalks (with safe inland lateral offset on Seestrasse)
  const sidewalkRoads = roads.filter((r) => r && r.kind !== 'motorway' && Array.isArray(r.pts) && r.pts.length >= 4);

  // Crosswalk bindings (all 8 Swiss zebra crossings)
  const crosswalks = (Array.isArray(network.crosswalks) ? network.crosswalks : [])
    .filter((c) => c && c.id && Number.isFinite(c.u) && Number.isFinite(c.v));
  const cwById = new Map();
  for (const cw of crosswalks) cwById.set(cw.id, cw);

  // Bus-stop POI <-> traffic.js dwellingStops ("roadId:stopIdx") mapping
  const busPois = poisList.filter((p) => p.kind === 'bus_stop' || (p.id && p.id.startsWith('poi_bus_')));
  const stopKeyToPoi = new Map();
  const poiToStopKeys = new Map();
  const poiCurbGeo = new Map();

  for (const rd of roads) {
    if (!Array.isArray(rd.stops) || rd.stops.length === 0 || !rd.pts || rd.pts.length < 2) continue;
    const isMain = rd.kind === 'seestrasse';
    for (let sIdx = 0; sIdx < rd.stops.length; sIdx++) {
      const pos = samplePathAt(rd.pts, rd.stops[sIdx], masterW, masterH, 3);
      if (!pos) continue;
      let bestPoi = null;
      let bestDist = 42;
      for (const bp of busPois) {
        const d = Math.hypot(bp.u * masterW - pos.wx, bp.v * masterH - pos.wy);
        if (d < bestDist) {
          bestDist = d;
          bestPoi = bp;
        }
      }
      if (!bestPoi) continue;
      const stopKey = `${rd.id}:${sIdx}`;
      stopKeyToPoi.set(stopKey, bestPoi.id);
      if (!poiToStopKeys.has(bestPoi.id)) poiToStopKeys.set(bestPoi.id, []);
      poiToStopKeys.get(bestPoi.id).push(stopKey);

      if (!poiCurbGeo.has(bestPoi.id)) {
        const isLakeLane = isMain && rd.id === 'seestrasse_nb';
        let rx;
        let ry;
        if (isMain) {
          // True screen-space perpendicular matches the projected Seestrasse lane separation
          const tm = Math.hypot(pos.tx, pos.ty) || 1;
          rx = -pos.ty / tm;
          ry = pos.tx / tm;
          // Point strictly outward from Seestrasse centerline: inland (up-left) for SB, lakeward (down-right) for NB
          if ((!isLakeLane && ry > 0) || (isLakeLane && ry < 0)) {
            rx = -rx;
            ry = -ry;
          }
        } else {
          const isoY = 0.55;
          const gx = pos.tx;
          const gy = pos.ty / isoY;
          const gm = Math.hypot(gx, gy) || 1;
          rx = -gy / gm;
          ry = (gx / gm) * isoY;
        }
        const swRoadIdx = sidewalkRoads.indexOf(rd);
        const rdLenM = Math.max(20, rd.length_m || 400);
        const baseD16 = pos.d16 || bestPoi.d16 || 30000;
        const curbD16 = isMain ? clamp(baseD16 + (isLakeLane ? -38 : 38), 1, 65534) : baseD16;
        poiCurbGeo.set(bestPoi.id, {
          u: pos.wx / masterW,
          v: pos.wy / masterH,
          d16: curbD16,
          tx: pos.tx,
          ty: pos.ty,
          rx,
          ry,
          isMain,
          roadIdx: swRoadIdx >= 0 ? swRoadIdx : 0,
          roadDistM: clamp(rd.stops[sIdx] * rdLenM, Math.min(10, rdLenM * 0.1), Math.max(11, rdLenM - Math.min(10, rdLenM * 0.1))),
          roadName: formatRoadName(rd),
          routeLabel: isMain ? 'Bus 161' : 'Bus 165',
          stopName: bestPoi.name || bestPoi.id,
        });
      }
    }
  }
  const activeBusPoiIds = Array.from(poiCurbGeo.keys());
  const fpBusPoiIds = activeBusPoiIds.filter((id) => fpNodes.has(id));

  // Landmark anchors
  const bhVig = vig.bahnhof_kilchberg || {
    plat_sw: [0.55049, 0.50304],
    plat_ne: [0.56449, 0.49558],
    footbridge: [[0.56281, 0.49120], [0.56679, 0.49719]],
  };
  const platSw = bhVig.plat_sw || [0.55049, 0.50304];
  const platNe = bhVig.plat_ne || [0.56449, 0.49558];
  const bhFb = bhVig.footbridge || [[0.56281, 0.49120], [0.56679, 0.49719]];

  const bpPax = (vig.bendlikon_pier && vig.bendlikon_pier.pax) || [0.58359, 0.57841];
  const pierHeadPoi = poiById.get('poi_bendlikon_pier') || { u: 0.57942, v: 0.57238, d16: 29749 };
  const gangplankLand = [bpPax[0], bpPax[1]];
  const gangplankBoat = [0.5855, 0.5841];

  const lindtPlaza = (vig.lindt_hoc && vig.lindt_hoc.plaza) || [0.37800, 0.65101];

  // Social pause anchors (3 Dorfbrunnen fountains + 2 lakefront benches + Bendlikon harbor railing)
  const socialAnchors = [];
  const rawFountains = (animData && animData.ambient && animData.ambient.fountains) || [];
  for (const ft of rawFountains) {
    if (Number.isFinite(ft.u) && Number.isFinite(ft.v)) {
      socialAnchors.push({ u: ft.u, v: ft.v, label: 'Dorfbrunnen Fountain' });
    }
  }
  for (const fpId of ['fp_pier_morfanlage', 'fp_bendlikon_lindt']) {
    const fp = edgeById.get(fpId);
    if (fp && fp.pts.length >= 3) {
      const mid = fp.pts[Math.floor(fp.pts.length * 0.5)];
      socialAnchors.push({ u: mid[0], v: mid[1], label: 'Lakefront Bench' });
    }
  }
  socialAnchors.push({ u: pierHeadPoi.u, v: pierHeadPoi.v, label: 'Bendlikon Harbor Railing' });

  // Curated route POI pools per archetype
  const PROMENADE_POIS = ['poi_morfanlage', 'poi_bendlikon_pier', 'poi_bus_bendlikon', 'poi_lindt_plaza', 'poi_bus_lindt', 'poi_seebad', 'poi_bus_schooren']
    .filter((id) => fpNodes.has(id));
  const SCHOOL_POIS = ['poi_bahnhof', 'poi_schulhaus_dorf', 'poi_bus_schwelle', 'poi_schulhaus_brunnenmoos', 'poi_kirche']
    .filter((id) => fpNodes.has(id));
  const DOG_POIS = ['poi_morfanlage', 'poi_bendlikon_pier', 'poi_bus_bendlikon', 'poi_lindt_plaza', 'poi_gemeindehaus', 'poi_sanatorium', 'poi_schulhaus_brunnenmoos', 'poi_kirche']
    .filter((id) => fpNodes.has(id));
  const BAHNHOF_APPROACH_POIS = ['poi_bus_bendlikon', 'poi_bendlikon_pier', 'poi_schulhaus_dorf', 'poi_bus_schwelle']
    .filter((id) => fpNodes.has(id));
  const PIER_APPROACH_POIS = ['poi_bahnhof', 'poi_bus_bendlikon', 'poi_morfanlage']
    .filter((id) => fpNodes.has(id));
  const LINDT_APPROACH_POIS = ['poi_bus_lindt', 'poi_bus_bendlikon', 'poi_seebad']
    .filter((id) => fpNodes.has(id));

  // Simulation state
  let initialized = false;
  let currentMode = 'day';
  let simTime = 0;
  let subStepRem = 0;
  let lastTargetT = 0;
  let rng = createRng('kilchberg-ped-v8:day:0');
  let agents = [];
  let occupiedCrosswalks = new Set();
  const prevTrainDwelling = new Map();
  const prevStopDwelling = new Map();
  let prevShipDocked = false;

  function sampleEdgeAt(edge, distM) {
    const frac = clamp(distM / Math.max(1, edge.lengthM), 0.002, 0.998);
    const rawFrac = edge.forward ? frac : (1.0 - frac);
    const pos = samplePathAt(edge.pts, rawFrac, masterW, masterH, 2);
    if (!pos) return null;
    return {
      u: pos.wx / masterW,
      v: pos.wy / masterH,
      d16: pos.d16 || 30000,
      tx: edge.forward ? pos.tx : -pos.tx,
      ty: edge.forward ? pos.ty : -pos.ty,
    };
  }

  function sampleSidewalkAt(rd, distM, dir) {
    const L = Math.max(20, rd.length_m || 400);
    const frac = clamp(distM / L, 0.004, 0.996);
    const pos = samplePathAt(rd.pts, frac, masterW, masterH, 3);
    if (!pos) return null;
    const isMain = rd.kind === 'seestrasse';
    const isLakeLane = isMain && rd.id === 'seestrasse_nb';
    let rx;
    let ry;
    if (isMain) {
      // True screen-space perpendicular matches the projected Seestrasse lane separation
      const tm = Math.hypot(pos.tx, pos.ty) || 1;
      rx = -pos.ty / tm;
      ry = pos.tx / tm;
      // Offset strictly outward from Seestrasse centerline: inland for SB, lakeward for NB
      if ((!isLakeLane && ry > 0) || (isLakeLane && ry < 0)) {
        rx = -rx;
        ry = -ry;
      }
    } else {
      const isoY = 0.55;
      const gx = pos.tx;
      const gy = pos.ty / isoY;
      const gm = Math.hypot(gx, gy) || 1;
      rx = -gy / gm;
      ry = (gx / gm) * isoY;
    }
    const latPx = isMain ? 6.2 : 2.8;
    const wx = pos.wx + rx * latPx;
    const wy = pos.wy + ry * latPx;
    const baseD16 = pos.d16 || 30000;
    const swD16 = clamp(Math.round(baseD16 - (wy - pos.wy) * depthSlopeGround), 1, 65534);
    return {
      u: clamp(wx / masterW, 0.002, 0.998),
      v: clamp(wy / masterH, 0.002, 0.998),
      d16: swD16,
      tx: pos.tx * dir,
      ty: pos.ty * dir,
    };
  }

  function sampleFeederAt(fd, distM, outbound) {
    const frac = clamp(distM / Math.max(1, fd.lengthM), 0.01, 0.99);
    const rawFrac = (outbound ? fd.entryAtStart : !fd.entryAtStart) ? frac : (1.0 - frac);
    const pos = samplePathAt(fd.pts, rawFrac, masterW, masterH, 2);
    if (!pos) return null;
    const movingInc = outbound ? fd.entryAtStart : !fd.entryAtStart;
    return {
      u: clamp(pos.wx / masterW, 0.002, 0.998),
      v: clamp(pos.wy / masterH, 0.002, 0.998),
      d16: pos.d16 || 30000,
      tx: movingInc ? pos.tx : -pos.tx,
      ty: movingInc ? pos.ty : -pos.ty,
    };
  }

  function samplePlatformPos(isSE, platFrac, doorShift = 0) {
    const dU = platNe[0] - platSw[0];
    const dV = platNe[1] - platSw[1];
    // NW platform (k=-0.3) sits NW of Gleis 2; SE platform (k=+2.0) sits SE of Gleis 1.
    // Never place commuters in the trackbed between Gleis 2 and Gleis 1!
    const baseU = isSE ? (platSw[0] + 0.0021 - doorShift * 0.00025) : (platSw[0] - 0.0003 + doorShift * 0.00025);
    const baseV = isSE ? (platSw[1] + 0.0031 - doorShift * 0.00035) : (platSw[1] - 0.0003 + doorShift * 0.00035);
    return {
      u: baseU + platFrac * dU,
      v: baseV + platFrac * dV,
      zGnd: 424.6,
      tx: dU * masterW,
      ty: dV * masterH,
    };
  }

  function sampleFootbridgePos(frac) {
    const f = clamp(frac, 0, 1);
    return {
      u: bhFb[0][0] + (bhFb[1][0] - bhFb[0][0]) * f,
      v: bhFb[0][1] + (bhFb[1][1] - bhFb[0][1]) * f,
      zGnd: 428.0,
      tx: (bhFb[1][0] - bhFb[0][0]) * masterW,
      ty: (bhFb[1][1] - bhFb[0][1]) * masterH,
    };
  }

  function samplePierDeckPos(frac) {
    const f = clamp(frac, 0, 1);
    return {
      u: pierHeadPoi.u + (bpPax[0] - pierHeadPoi.u) * f,
      v: pierHeadPoi.v + (bpPax[1] - pierHeadPoi.v) * f,
      zGnd: 407.2,
      tx: (bpPax[0] - pierHeadPoi.u) * masterW,
      ty: (bpPax[1] - pierHeadPoi.v) * masterH,
    };
  }

  function sampleGangplankPos(frac) {
    const f = clamp(frac, 0, 1);
    return {
      u: gangplankLand[0] + (gangplankBoat[0] - gangplankLand[0]) * f,
      v: gangplankLand[1] + (gangplankBoat[1] - gangplankLand[1]) * f,
      zGnd: 407.2,
      tx: (gangplankBoat[0] - gangplankLand[0]) * masterW,
      ty: (gangplankBoat[1] - gangplankLand[1]) * masterH,
    };
  }

  function poiLabel(id) {
    const p = poiById.get(id);
    return (p && p.name) ? p.name : (id || 'Kilchberg');
  }

  function assignFootpathTrip(ag, fromPoi, toPoi, labelPrefix) {
    const route = findFootpathRoute(fromPoi, toPoi);
    if (route.length === 0) return false;
    ag.edgeList = route;
    ag.edgeIdx = 0;
    ag.edgeDistM = 0;
    ag.state = 'walk_edge';
    ag.onElevatedDeck = false;
    ag.zGnd = null;
    ag.originPoi = fromPoi;
    ag.destPoi = toPoi;
    ag.originName = poiLabel(fromPoi);
    ag.destName = poiLabel(toPoi);
    ag.tripLabel = `${labelPrefix} → ${ag.destName}`;
    const p = sampleEdgeAt(route[0], 0);
    if (p) {
      ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty;
    }
    return true;
  }

  function finishConnector(ag) {
    const nxt = ag.connNext;
    ag.connNext = null;
    if (!nxt) {
      ag.state = 'walk_edge';
      return;
    }
    if (nxt.type === 'queue_rail') {
      ag.state = 'queue_rail';
      ag.onElevatedDeck = false;
      const p = samplePlatformPos(ag.platIsSE, ag.platFrac, 0);
      ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.tx = p.tx; ag.ty = p.ty;
      if (nxt.tripLabel) ag.tripLabel = nxt.tripLabel;
    } else if (nxt.type === 'walk_footbridge') {
      ag.state = 'walk_footbridge';
      ag.fbFrac = nxt.fbFrac;
      ag.fbDir = nxt.fbDir;
      ag.onElevatedDeck = true;
      const p = sampleFootbridgePos(ag.fbFrac);
      ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.tx = p.tx * ag.fbDir; ag.ty = p.ty * ag.fbDir;
      if (nxt.tripLabel) ag.tripLabel = nxt.tripLabel;
    } else if (nxt.type === 'walk_edge') {
      assignFootpathTrip(ag, nxt.fromPoi, nxt.toPoi, nxt.labelPrefix);
    } else if (nxt.type === 'plaza_admire') {
      ag.state = 'plaza_admire';
      ag.stateTimer = nxt.stateTimer;
      ag.onElevatedDeck = false;
      ag.zGnd = 413.9;
      if (nxt.tripLabel) ag.tripLabel = nxt.tripLabel;
    } else if (nxt.type === 'queue_bus') {
      ag.state = 'queue_bus';
      ag.onElevatedDeck = false;
      ag.zGnd = null;
      ag.d16 = nxt.d16 || ag.d16;
      if (nxt.tripLabel) ag.tripLabel = nxt.tripLabel;
    } else if (nxt.type === 'walk_pier_deck') {
      ag.state = 'walk_pier_deck';
      ag.pierFrac = nxt.pierFrac;
      ag.pierDir = nxt.pierDir;
      ag.boardingPier = false;
      ag.onElevatedDeck = true;
      const p = samplePierDeckPos(ag.pierFrac);
      ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.tx = p.tx * ag.pierDir; ag.ty = p.ty * ag.pierDir;
      if (nxt.tripLabel) ag.tripLabel = nxt.tripLabel;
    }
  }

  const u16PerM = 65535.0 / Math.max(1.0, depthMax - depthMin);
  const depthC0 = (0 - depthMin) * u16PerM + depthSlopeGround * 2927.412592;
  const depthSlopeZ = 2.0 * 1.16 * u16PerM;
  function evalEstD16(u, v, zGnd) {
    const wyM = v * masterH;
    return clamp(Math.round(depthC0 - depthSlopeGround * wyM - depthSlopeZ * ((zGnd != null ? zGnd : 413.9) - 348.0) - 10), 1, 65534);
  }

  function startConnectorWalk(ag, targetU, targetV, targetD16, targetZGnd, onElevated, nextAction, tripLabel) {
    const distPx = Math.hypot((targetU - ag.u) * masterW, (targetV - ag.v) * masterH);
    const resolvedEndD16 = targetD16 != null ? targetD16 : evalEstD16(targetU, targetV, targetZGnd);
    ag.connNext = nextAction;
    if (distPx < 3.0) {
      ag.u = targetU;
      ag.v = targetV;
      ag.d16 = resolvedEndD16;
      ag.zGnd = targetZGnd;
      ag.onElevatedDeck = !!onElevated;
      finishConnector(ag);
      return;
    }
    const startD16 = ag.zGnd != null ? evalEstD16(ag.u, ag.v, ag.zGnd) : (ag.d16 || evalEstD16(ag.u, ag.v, null));
    ag.state = 'walk_connector';
    ag.connStartU = ag.u;
    ag.connStartV = ag.v;
    ag.connEndU = targetU;
    ag.connEndV = targetV;
    ag.connStartD16 = startD16;
    ag.connEndD16 = resolvedEndD16;
    ag.connStartZGnd = ag.zGnd;
    ag.connEndZGnd = targetZGnd;
    ag.connProgress = 0;
    ag.connLenM = Math.max(0.6, distPx * 0.28);
    ag.onElevatedDeck = !!onElevated;
    ag.tx = (targetU - ag.u) * masterW;
    ag.ty = (targetV - ag.v) * masterH;
    if (tripLabel) ag.tripLabel = tripLabel;
  }

  function startFootpathTripSmooth(ag, fromPoi, toPoi, labelPrefix) {
    const route = findFootpathRoute(fromPoi, toPoi);
    if (route.length === 0) return false;
    const p0 = sampleEdgeAt(route[0], 0);
    if (!p0) return false;
    const distPx = Math.hypot((p0.u - ag.u) * masterW, (p0.v - ag.v) * masterH);
    if (distPx < 8.0) {
      return assignFootpathTrip(ag, fromPoi, toPoi, labelPrefix);
    }
    // Snap directly to footpath start if separated across a station building (> 22 px)
    // so commuters never walk through building roofs on a straight-line connector.
    if (distPx > 22.0 && fromPoi === 'poi_bahnhof') {
      ag.u = p0.u;
      ag.v = p0.v;
      ag.d16 = p0.d16;
      ag.zGnd = null;
      ag.onElevatedDeck = false;
      return assignFootpathTrip(ag, fromPoi, toPoi, labelPrefix);
    }
    startConnectorWalk(
      ag,
      p0.u,
      p0.v,
      p0.d16,
      null,
      false,
      { type: 'walk_edge', fromPoi, toPoi, labelPrefix },
      `${labelPrefix} → ${poiLabel(toPoi)}`,
    );
    return true;
  }

  function makeBaseAgent(idx, role, arng) {
    const isJogger = role === 'jogger';
    const isSchool = role === 'schoolkid';
    const isStroller = role === 'stroller_parent';
    const isDog = role === 'dog_walker';
    const isCouple = role === 'couple';
    const speedMps = isJogger
      ? arng.range(2.55, 2.95)
      : (isStroller ? arng.range(0.95, 1.15)
        : (isDog ? arng.range(1.05, 1.25)
          : (role === 'rail_commuter' || role === 'bus_rider' ? arng.range(1.42, 1.65) : arng.range(1.20, 1.45))));

    return {
      id: `ped:${idx}`,
      role,
      state: 'walk_edge',
      u: 0.5,
      v: 0.5,
      d16: 30000,
      tx: 1,
      ty: 0,
      zGnd: null,
      onElevatedDeck: false,
      edgeList: [],
      edgeIdx: 0,
      edgeDistM: 0,
      roadIdx: 0,
      roadDistM: 0,
      roadDir: 1,
      feederId: null,
      feederDistM: 0,
      feederOutbound: true,
      speedMps,
      stateTimer: 0,
      pauseCooldown: arng.range(2.0, 10.0),
      resumeState: 'walk_edge',
      targetTrainId: null,
      platIsSE: false,
      platFrac: 0.5,
      fbFrac: 0,
      fbDir: 1,
      pierFrac: 0,
      pierDir: 1,
      boardingPier: false,
      gpFrac: 0,
      gpDir: 1,
      connStartU: 0.5,
      connStartV: 0.5,
      connEndU: 0.5,
      connEndV: 0.5,
      connStartD16: 30000,
      connEndD16: 30000,
      connStartZGnd: null,
      connEndZGnd: null,
      connProgress: 0,
      connLenM: 1,
      connNext: null,
      targetStopPoiId: null,
      stopSlot: 0,
      targetCwId: null,
      cwDir: 1,
      cwProgress: 0,
      coatCol: isJogger ? arng.pick(JOGGER_TOPS) : arng.pick(COAT_PALETTE),
      pantsCol: arng.pick(PANTS_COLORS),
      hairCol: arng.pick(HAIR_PALETTE),
      bagCol: isSchool
        ? arng.pick(SCHOOL_BAGS)
        : (role === 'rail_commuter' && arng.chance(0.45) ? '#334155' : (role === 'seebad_bather' && arng.chance(0.6) ? '#38bdf8' : null)),
      hasDog: isDog,
      dogCol: isDog ? arng.pick(DOG_COLORS) : null,
      hasStroller: isStroller,
      partnerCoat: isCouple ? arng.pick(COAT_PALETTE) : null,
      partnerHair: isCouple ? arng.pick(HAIR_PALETTE) : null,
      stridePhase: arng.range(0, Math.PI * 2),
      originPoi: null,
      destPoi: null,
      originName: 'Kilchberg',
      destName: 'Kilchberg',
      tripLabel: 'Villager · Kilchberg',
      transitStartT: -100,
      seedOffset: idx * 1.37,
    };
  }

  function updateCrosswalkPosition(ag, cw) {
    const p = ag.state === 'crossing_cw' ? ag.cwProgress : 0;
    const isSeestrasse = typeof cw.road_id === 'string' && cw.road_id.startsWith('seestrasse');
    const baseWx = cw.u * masterW;
    const baseWy = cw.v * masterH;
    let wx;
    let wy;
    if (isSeestrasse) {
      const nMag = Math.hypot(cw.nx, cw.ny) || 1;
      const ux = cw.nx / nMag;
      const uy = cw.ny / nMag;
      const spanPx = (p - 0.5) * 18.0 * ag.cwDir;
      wx = baseWx + ux * spanPx;
      wy = baseWy + uy * spanPx;
      ag.tx = ux * ag.cwDir;
      ag.ty = uy * ag.cwDir;
    } else {
      const spanPx = (p - 0.5) * 11.5 * ag.cwDir;
      wx = baseWx + cw.nx * spanPx;
      wy = baseWy + cw.ny * spanPx * 0.55;
      ag.tx = cw.nx * ag.cwDir;
      ag.ty = cw.ny * 0.55 * ag.cwDir;
    }
    ag.u = clamp(wx / masterW, 0.002, 0.998);
    ag.v = clamp(wy / masterH, 0.002, 0.998);
    ag.d16 = clamp(Math.round((cw.d16 || 30000) - (wy - baseWy) * depthSlopeGround), 1, 65534);
  }

  function resetState(mode, tStart) {
    currentMode = normModeName(mode);
    simTime = tStart;
    subStepRem = 0;
    lastTargetT = tStart;
    rng = createRng(`kilchberg-ped-v8:${currentMode}:${Math.round(tStart * 100)}`);
    agents = [];
    occupiedCrosswalks = new Set();
    prevTrainDwelling.clear();
    prevStopDwelling.clear();
    prevShipDocked = false;

    const counts = ROLE_COUNTS[currentMode] || ROLE_COUNTS.day;
    const initTransit = INITIAL_IN_TRANSIT[currentMode] || INITIAL_IN_TRANSIT.day;
    let nextId = 0;

    // 1. Bahnhof Kilchberg Commuters
    const visibleRailCount = Math.max(1, counts.rail_commuter - initTransit.rail);
    for (let i = 0; i < counts.rail_commuter; i++) {
      const arng = rng.fork(`rail:${i}`);
      const ag = makeBaseAgent(nextId++, 'rail_commuter', arng);
      const isSE = i % 2 === 1;
      ag.platIsSE = isSE;
      ag.targetTrainId = isSE ? 'sbb_s8_south' : 'sbb_ic_north';
      ag.platFrac = 0.14 + ((i % visibleRailCount) / Math.max(1, visibleRailCount)) * 0.72;
      if (i >= visibleRailCount) {
        ag.state = 'in_transit';
        ag.stateTimer = 0;
        ag.originName = isSE ? 'Zürich HB' : 'Thalwil';
        ag.destName = 'Bahnhof Kilchberg';
        ag.tripLabel = isSE ? 'Aboard SBB S8 → Bahnhof Kilchberg' : 'Aboard SBB S24 → Bahnhof Kilchberg';
      } else if (i < Math.ceil(visibleRailCount * 0.5)) {
        ag.state = 'queue_rail';
        const p = samplePlatformPos(isSE, ag.platFrac, 0);
        ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.tx = p.tx; ag.ty = p.ty;
        ag.originName = 'Kilchberg Dorf';
        ag.destName = isSE ? 'Zürich HB (S8)' : 'Pfäffikon SZ (S24)';
        ag.tripLabel = isSE ? 'Commuter → Bahnhof Kilchberg (S8)' : 'Commuter → Bahnhof Kilchberg (S24)';
      } else if (i % 4 === 0) {
        ag.state = 'walk_footbridge';
        ag.fbFrac = arng.range(0.1, 0.9);
        ag.fbDir = arng.chance(0.5) ? 1 : -1;
        ag.onElevatedDeck = true;
        const p = sampleFootbridgePos(ag.fbFrac);
        ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.tx = p.tx * ag.fbDir; ag.ty = p.ty * ag.fbDir;
        ag.originName = 'Bahnhofstrasse';
        ag.destName = 'Bahnhof Kilchberg Platform';
        ag.tripLabel = 'Commuter → Bahnhof Footbridge';
      } else {
        const startPoi = arng.pick(BAHNHOF_APPROACH_POIS) || 'poi_bus_bendlikon';
        if (assignFootpathTrip(ag, startPoi, 'poi_bahnhof', 'Commuter')) {
          ag.edgeDistM = arng.range(0, ag.edgeList[0].lengthM * 0.85);
          const p = sampleEdgeAt(ag.edgeList[0], ag.edgeDistM);
          if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
        }
      }
      agents.push(ag);
    }

    // 2. ZVV Bus Riders & Stop Queues (Lines 161 & 165)
    for (let i = 0; i < counts.bus_rider; i++) {
      const arng = rng.fork(`bus:${i}`);
      const ag = makeBaseAgent(nextId++, 'bus_rider', arng);
      const stopPoi = activeBusPoiIds.length > 0 ? activeBusPoiIds[i % activeBusPoiIds.length] : null;
      ag.targetStopPoiId = stopPoi;
      ag.stopSlot = Math.floor(i / Math.max(1, activeBusPoiIds.length));
      if (stopPoi && i < Math.min(activeBusPoiIds.length * 2, Math.ceil(counts.bus_rider * 0.55))) {
        const geo = poiCurbGeo.get(stopPoi);
        ag.state = 'queue_bus';
        const along = ((ag.stopSlot % 3) - 1) * 3.8;
        const lat = geo.isMain ? 6.2 : 5.0;
        ag.u = clamp(geo.u + (geo.rx * lat + geo.tx * along) / masterW, 0.002, 0.998);
        ag.v = clamp(geo.v + (geo.ry * lat + geo.ty * along) / masterH, 0.002, 0.998);
        ag.d16 = geo.d16;
        ag.tx = geo.tx; ag.ty = geo.ty;
        ag.originName = geo.stopName;
        ag.destName = `${geo.routeLabel} Corridor`;
        ag.tripLabel = `Rider → ${geo.routeLabel} (${geo.stopName})`;
      } else if (fpBusPoiIds.length >= 2) {
        const dst = arng.pick(fpBusPoiIds);
        const src = arng.pick(fpNodeList.filter((id) => id !== dst)) || fpBusPoiIds[0];
        ag.targetStopPoiId = dst;
        if (assignFootpathTrip(ag, src, dst, 'Bus Rider')) {
          ag.edgeDistM = arng.range(0, ag.edgeList[0].lengthM * 0.9);
          const p = sampleEdgeAt(ag.edgeList[0], ag.edgeDistM);
          if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
        }
      }
      agents.push(ag);
    }

    // 3. Bendlikon ZSG Pier Passengers
    const visiblePierCount = Math.max(1, counts.pier_pax - initTransit.pier);
    for (let i = 0; i < counts.pier_pax; i++) {
      const arng = rng.fork(`pier:${i}`);
      const ag = makeBaseAgent(nextId++, 'pier_pax', arng);
      if (i >= visiblePierCount) {
        ag.state = 'in_transit';
        ag.stateTimer = 0;
        ag.originName = 'Zürich Bürkliplatz';
        ag.destName = 'Bendlikon ZSG Pier';
        ag.tripLabel = 'Aboard ZSG MS Helvetia → Bendlikon Pier';
      } else if (i < Math.ceil(visiblePierCount * 0.5)) {
        ag.state = 'queue_pier';
        ag.pierFrac = 0.84 + (i % 4) * 0.04;
        const p = samplePierDeckPos(ag.pierFrac);
        ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.onElevatedDeck = true;
        ag.originName = 'Badweg';
        ag.destName = 'ZSG MS Helvetia';
        ag.tripLabel = 'Passenger → ZSG MS Helvetia';
      } else if (i % 2 === 0 && feederById.has('feeder_badweg')) {
        const fd = feederById.get('feeder_badweg');
        ag.state = 'walk_feeder';
        ag.feederId = fd.id;
        ag.feederOutbound = true;
        ag.feederDistM = arng.range(5, fd.lengthM * 0.85);
        const p = sampleFeederAt(fd, ag.feederDistM, ag.feederOutbound);
        if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
        ag.originName = 'Seestrasse';
        ag.destName = 'Bendlikon ZSG Pier';
        ag.tripLabel = 'Passenger → Bendlikon ZSG Pier';
      } else {
        const src = arng.pick(PIER_APPROACH_POIS) || 'poi_bus_bendlikon';
        if (assignFootpathTrip(ag, src, 'poi_bendlikon_pier', 'Pier Passenger')) {
          ag.edgeDistM = arng.range(0, ag.edgeList[0].lengthM * 0.85);
          const p = sampleEdgeAt(ag.edgeList[0], ag.edgeDistM);
          if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
        }
      }
      agents.push(ag);
    }

    // 4. Lindt Home of Chocolate Visitors
    for (let i = 0; i < counts.lindt_visitor; i++) {
      const arng = rng.fork(`lindt:${i}`);
      const ag = makeBaseAgent(nextId++, 'lindt_visitor', arng);
      if (i < Math.ceil(counts.lindt_visitor * 0.42)) {
        ag.state = 'plaza_admire';
        ag.stateTimer = arng.range(1.5, 5.5);
        ag.u = lindtPlaza[0] + arng.range(-0.0017, 0.0017);
        ag.v = lindtPlaza[1] + arng.range(-0.0013, 0.0013);
        ag.zGnd = 413.9;
        ag.bagCol = arng.chance(0.55) ? (arng.chance(0.6) ? '#e5b93c' : '#d62c28') : null;
        ag.originName = 'Bus Lindt & Sprüngli';
        ag.destName = 'Lindt Home of Chocolate';
        ag.tripLabel = 'Visitor · Lindt Home of Chocolate Plaza';
      } else if (i % 2 === 0) {
        const src = arng.pick(LINDT_APPROACH_POIS) || 'poi_bus_lindt';
        ag.bagCol = null;
        if (assignFootpathTrip(ag, src, 'poi_lindt_plaza', 'Lindt Visitor')) {
          ag.edgeDistM = arng.range(0, ag.edgeList[0].lengthM * 0.85);
          const p = sampleEdgeAt(ag.edgeList[0], ag.edgeDistM);
          if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
        }
      } else {
        const dst = arng.pick(LINDT_APPROACH_POIS) || 'poi_bus_lindt';
        ag.bagCol = arng.chance(0.6) ? '#e5b93c' : '#d62c28';
        if (assignFootpathTrip(ag, 'poi_lindt_plaza', dst, 'Lindt Visitor')) {
          ag.edgeDistM = arng.range(0, ag.edgeList[0].lengthM * 0.85);
          const p = sampleEdgeAt(ag.edgeList[0], ag.edgeDistM);
          if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
        }
      }
      agents.push(ag);
    }

    // 5. Swiss Zebra Crosswalk Commuters (staggered across all 8 crosswalks)
    for (let i = 0; i < counts.crosswalk_commuter; i++) {
      const arng = rng.fork(`cw:${i}`);
      const ag = makeBaseAgent(nextId++, 'crosswalk_commuter', arng);
      if (crosswalks.length > 0) {
        const cw = crosswalks[i % crosswalks.length];
        ag.targetCwId = cw.id;
        ag.cwDir = (i % 2 === 0) ? 1 : -1;
        const phaseSlot = i % 4;
        if (phaseSlot === 0) {
          ag.state = 'crossing_cw';
          ag.cwProgress = arng.range(0.15, 0.72);
        } else if (phaseSlot === 1) {
          ag.state = 'curb_wait';
          ag.stateTimer = arng.range(0.2, 0.75);
        } else {
          ag.state = 'cw_stroll';
          ag.stateTimer = arng.range(1.2, 5.5);
          ag.cwProgress = 0;
        }
        ag.originName = cw.name || 'Kilchberg';
        ag.destName = cw.name || 'Crosswalk';
        ag.tripLabel = `Crossing Zebra · ${cw.name || cw.id}`;
        updateCrosswalkPosition(ag, cw);
      }
      agents.push(ag);
    }

    // 6. Dog Walkers, Parents with Strollers, Walking Couples, Joggers, Schoolkids, Seebad Bathers
    const spawnFootpathArchetype = (role, count, pool, labelPrefix) => {
      for (let i = 0; i < count; i++) {
        const arng = rng.fork(`${role}:${i}`);
        const ag = makeBaseAgent(nextId++, role, arng);
        const srcPool = pool.length >= 2 ? pool : fpNodeList;
        const src = srcPool[i % srcPool.length];
        const dstCandidates = srcPool.filter((id) => id !== src);
        const dst = arng.pick(dstCandidates) || fpNodeList[(i + 1) % fpNodeList.length];
        if (assignFootpathTrip(ag, src, dst, labelPrefix)) {
          ag.edgeDistM = arng.range(0, ag.edgeList[0].lengthM * 0.92);
          const p = sampleEdgeAt(ag.edgeList[0], ag.edgeDistM);
          if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
        }
        agents.push(ag);
      }
    };

    spawnFootpathArchetype('dog_walker', counts.dog_walker, DOG_POIS, 'Dog Walker');
    spawnFootpathArchetype('stroller_parent', counts.stroller_parent, PROMENADE_POIS, 'Family Stroll');
    spawnFootpathArchetype('couple', counts.couple, PROMENADE_POIS, 'Evening Walk');
    spawnFootpathArchetype('jogger', counts.jogger, PROMENADE_POIS, 'Lakefront Jogger');
    spawnFootpathArchetype('schoolkid', counts.schoolkid, SCHOOL_POIS, 'Schoolkid');
    spawnFootpathArchetype('seebad_bather', counts.seebad_bather, ['poi_seebad', 'poi_bus_schooren', 'poi_bus_lindt', 'poi_lindt_plaza'].filter((id) => fpNodes.has(id)), 'Seebad Bather');

    // 7. Village / Residential Feeder / Sidewalk Walkers
    for (let i = 0; i < counts.village_walker; i++) {
      const arng = rng.fork(`vill:${i}`);
      const ag = makeBaseAgent(nextId++, 'village_walker', arng);
      if (feeders.length > 0 && i % 3 === 0) {
        const fd = feeders[i % feeders.length];
        ag.state = 'walk_feeder';
        ag.feederId = fd.id;
        ag.feederOutbound = arng.chance(0.5);
        ag.feederDistM = arng.range(5, fd.lengthM * 0.9);
        ag.originName = fd.name;
        ag.destName = 'Kilchberg Dorf';
        ag.tripLabel = `Villager · ${fd.name}`;
        const p = sampleFeederAt(fd, ag.feederDistM, ag.feederOutbound);
        if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
      } else if (sidewalkRoads.length > 0 && i % 3 === 1) {
        const rIdx = i % sidewalkRoads.length;
        const rd = sidewalkRoads[rIdx];
        ag.state = 'walk_sidewalk';
        ag.roadIdx = rIdx;
        ag.roadDir = arng.chance(0.5) ? 1 : -1;
        ag.roadDistM = arng.range(10, Math.max(20, (rd.length_m || 400) - 10));
        ag.originName = formatRoadName(rd);
        ag.destName = 'Kilchberg Village';
        ag.tripLabel = `Stroll · ${formatRoadName(rd)}`;
        const p = sampleSidewalkAt(rd, ag.roadDistM, ag.roadDir);
        if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
      } else if (fpNodeList.length >= 2) {
        const src = fpNodeList[i % fpNodeList.length];
        const dst = arng.pick(fpNodeList.filter((id) => id !== src)) || fpNodeList[0];
        if (assignFootpathTrip(ag, src, dst, 'Villager')) {
          ag.edgeDistM = arng.range(0, ag.edgeList[0].lengthM * 0.9);
          const p = sampleEdgeAt(ag.edgeList[0], ag.edgeDistM);
          if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
        }
      }
      agents.push(ag);
    }

    initialized = true;
  }

  function buildTransitContext(tSec, transitSnapshot) {
    if (transitSnapshot && transitSnapshot.trains && transitSnapshot.ships && transitSnapshot.dwellingStops) {
      return transitSnapshot;
    }
    const trList = trains.map((tr) => ({
      id: tr.id,
      kind: tr.kind,
      state: evalTrainState(tr, tSec),
    }));
    const shList = ships.map((sh) => ({
      id: sh.id,
      kind: sh.kind,
      state: evalShipState(sh, tSec, currentMode),
    }));
    const dwellStops = new Set();
    for (const rd of roads) {
      const busCount = getActiveBusCountForMode(rd, currentMode);
      if (busCount <= 0 || !Array.isArray(rd.stops) || rd.stops.length === 0) continue;
      for (let bIdx = 0; bIdx < busCount; bIdx++) {
        const st = evalBusScheduleState(rd, bIdx, tSec, busCount);
        if (st.isDwelling && st.stopIdx >= 0) {
          dwellStops.add(`${rd.id}:${st.stopIdx}`);
        }
      }
    }
    return { tSec, mode: currentMode, trains: trList, ships: shList, dwellingStops: dwellStops };
  }

  function maybeTriggerSocialPause(ag) {
    if (ag.pauseCooldown > 0) return false;
    if (ag.role === 'jogger' || ag.role === 'rail_commuter' || ag.role === 'crosswalk_commuter') return false;
    for (let i = 0; i < socialAnchors.length; i++) {
      const sa = socialAnchors[i];
      const dPx = Math.hypot((ag.u - sa.u) * masterW, (ag.v - sa.v) * masterH);
      if (dPx < 14.0 && rng.chance(0.28)) {
        ag.resumeState = ag.state;
        ag.state = 'social_pause';
        ag.stateTimer = rng.range(3.0, 5.0);
        ag.pauseCooldown = rng.range(24.0, 42.0);
        ag.tripLabel = `Pause · ${sa.label}`;
        return true;
      }
    }
    return false;
  }

  function step(dt, transitSnapshot) {
    simTime += dt;
    const tCtx = buildTransitContext(simTime, transitSnapshot);
    occupiedCrosswalks = new Set();

    const trainStateById = new Map();
    for (const tr of tCtx.trains) trainStateById.set(tr.id, tr.state);

    let steamerState = null;
    for (const sh of tCtx.ships) {
      if (sh.kind === 'zsg_steamer' || sh.id === 'zsg_ms_helvetia') {
        steamerState = sh.state;
        break;
      }
    }

    const dwellingBusPois = new Set();
    for (const key of tCtx.dwellingStops) {
      const poiId = stopKeyToPoi.get(key);
      if (poiId) dwellingBusPois.add(poiId);
    }

    // Trigger alighting wave when an SBB train opens doors at Bahnhof Kilchberg
    for (const [trId, trSt] of trainStateById.entries()) {
      const wasDwell = prevTrainDwelling.get(trId) || false;
      const nowAlight = trSt.isDwelling && trSt.dwellProgress >= 0.10;
      if (nowAlight && !wasDwell) {
        prevTrainDwelling.set(trId, true);
        let spawned = 0;
        const maxAlight = currentMode === 'night' ? 2 : 4;
        for (const ag of agents) {
          if (spawned >= maxAlight) break;
          if (ag.role === 'rail_commuter' && ag.state === 'in_transit') {
            ag.state = 'alighting';
            ag.stateTimer = 0.95;
            ag.targetTrainId = trId;
            ag.platIsSE = trId === 'sbb_s8_south';
            ag.platFrac = 0.22 + (spawned * 0.17);
            const p = samplePlatformPos(ag.platIsSE, ag.platFrac, 0.8);
            ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.onElevatedDeck = false;
            ag.tripLabel = ag.platIsSE ? 'Alighting S8 → Bendlikon' : 'Alighting S24 → Dorfstrasse';
            spawned++;
          }
        }
      } else if (!trSt.isDwelling) {
        prevTrainDwelling.set(trId, false);
      }
    }

    // Trigger alighting wave when ZSG MS Helvetia docks at Bendlikon Pier
    const steamerDocked = !!(steamerState && steamerState.isDocked);
    if (steamerDocked && !prevShipDocked && steamerState.dwellProgress >= 0.12) {
      prevShipDocked = true;
      let spawned = 0;
      const maxPax = currentMode === 'night' ? 1 : 3;
      for (const ag of agents) {
        if (spawned >= maxPax) break;
        if (ag.role === 'pier_pax' && ag.state === 'in_transit') {
          ag.state = 'walk_gangplank';
          ag.gpFrac = 0.98 - spawned * 0.14;
          ag.gpDir = -1;
          ag.onElevatedDeck = true;
          const p = sampleGangplankPos(ag.gpFrac);
          ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.tx = -p.tx; ag.ty = -p.ty;
          ag.tripLabel = 'ZSG Steamer → Seestrasse Promenade';
          spawned++;
        }
      }
    } else if (!steamerDocked) {
      prevShipDocked = false;
    }

    // Trigger alighting wave when a ZVV bus dwells at a stop
    for (const poiId of dwellingBusPois) {
      if (!prevStopDwelling.get(poiId)) {
        prevStopDwelling.set(poiId, true);
        const geo = poiCurbGeo.get(poiId);
        if (geo) {
          for (const ag of agents) {
            if (
              ag.role === 'bus_rider'
              && ag.state === 'in_transit'
              && (simTime - (ag.transitStartT ?? -100)) >= MIN_BUS_TRANSIT_SEC
            ) {
              ag.state = 'alighting';
              ag.stateTimer = 0.85;
              ag.targetStopPoiId = poiId;
              const lat = (geo.isMain ? 5.2 : 4.2);
              ag.u = clamp(geo.u + (geo.rx * lat) / masterW, 0.002, 0.998);
              ag.v = clamp(geo.v + (geo.ry * lat) / masterH, 0.002, 0.998);
              ag.d16 = geo.d16;
              ag.tx = geo.tx; ag.ty = geo.ty;
              ag.tripLabel = `${geo.routeLabel} Alighting · ${geo.stopName}`;
              break;
            }
          }
        }
      }
    }
    for (const [poiId] of prevStopDwelling.entries()) {
      if (!dwellingBusPois.has(poiId)) prevStopDwelling.set(poiId, false);
    }

    // Advance every pedestrian agent
    for (let i = 0; i < agents.length; i++) {
      const ag = agents[i];
      if (ag.pauseCooldown > 0) ag.pauseCooldown = Math.max(0, ag.pauseCooldown - dt);

      if (ag.state === 'in_transit') {
        // Rail commuters and pier passengers remain genuinely aboard trains / MS Helvetia
        // until the next Bahnhof Kilchberg dwell or Bendlikon Pier dock triggers alighting.
        if (ag.role === 'bus_rider') {
          ag.stateTimer -= dt;
          if (ag.stateTimer <= 0) {
            const dst = rng.pick(fpBusPoiIds) || activeBusPoiIds[0];
            const src = rng.pick(fpNodeList.filter((id) => id !== dst)) || fpNodeList[0];
            ag.targetStopPoiId = dst;
            if (!assignFootpathTrip(ag, src, dst, 'Bus Rider')) {
              ag.state = 'queue_bus';
            }
          }
        }
        continue;
      }

      if (ag.state === 'walk_connector') {
        ag.connProgress += (ag.speedMps / Math.max(0.5, ag.connLenM)) * dt;
        ag.stridePhase += dt * (ag.speedMps * 5.2);
        const f = clamp(ag.connProgress, 0, 1);
        ag.u = ag.connStartU + (ag.connEndU - ag.connStartU) * f;
        ag.v = ag.connStartV + (ag.connEndV - ag.connStartV) * f;
        ag.d16 = ag.connStartD16 + (ag.connEndD16 - ag.connStartD16) * f;
        if (ag.connStartZGnd != null && ag.connEndZGnd != null) {
          ag.zGnd = ag.connStartZGnd + (ag.connEndZGnd - ag.connStartZGnd) * f;
        } else {
          ag.zGnd = null;
        }
        if (ag.connProgress >= 1.0) {
          finishConnector(ag);
        }
        continue;
      }

      if (ag.state === 'social_pause') {
        ag.stateTimer -= dt;
        ag.stridePhase += dt * 1.1;
        if (ag.stateTimer <= 0) {
          ag.state = ag.resumeState || 'walk_edge';
        }
        continue;
      }

      if (ag.state === 'plaza_admire') {
        ag.stateTimer -= dt;
        ag.stridePhase += dt * 1.4;
        if (ag.stateTimer <= 0) {
          ag.bagCol = rng.chance(0.6) ? '#e5b93c' : '#d62c28';
          const dst = rng.pick(LINDT_APPROACH_POIS) || 'poi_bus_lindt';
          startFootpathTripSmooth(ag, 'poi_lindt_plaza', dst, 'Lindt Visitor');
        }
        continue;
      }

      if (ag.state === 'queue_rail') {
        const trSt = trainStateById.get(ag.targetTrainId);
        const approaching = trSt && trSt.secUntilArrival <= 16;
        ag.stridePhase += dt * (approaching ? 3.2 : 1.1);
        const p = samplePlatformPos(ag.platIsSE, ag.platFrac + Math.sin(simTime * 0.3 + ag.seedOffset) * 0.015, approaching ? 0.35 : 0);
        ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.onElevatedDeck = false;
        if (trSt && trSt.isDwelling && trSt.dwellProgress < 0.70) {
          ag.state = 'boarding';
          ag.stateTimer = 1.4;
          ag.tripLabel = ag.platIsSE ? 'Boarding SBB S8 → Zürich' : 'Boarding SBB S24 → Thalwil';
        }
        continue;
      }

      if (ag.state === 'boarding') {
        ag.stateTimer -= dt;
        ag.stridePhase += dt * 7.8;
        if (ag.role === 'rail_commuter') {
          const p = samplePlatformPos(ag.platIsSE, ag.platFrac, 1.0);
          ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd;
        } else if (ag.role === 'bus_rider' && ag.targetStopPoiId) {
          const geo = poiCurbGeo.get(ag.targetStopPoiId);
          if (geo) {
            const lat = (geo.isMain ? 4.8 : 3.8);
            ag.u = clamp(geo.u + (geo.rx * lat) / masterW, 0.002, 0.998);
            ag.v = clamp(geo.v + (geo.ry * lat) / masterH, 0.002, 0.998);
          }
        }
        if (ag.stateTimer <= 0) {
          ag.state = 'in_transit';
          ag.transitStartT = simTime;
          ag.stateTimer = ag.role === 'bus_rider' ? rng.range(12.0, 20.0) : 0;
        }
        continue;
      }

      if (ag.state === 'alighting') {
        ag.stateTimer -= dt;
        ag.stridePhase += dt * 7.2;
        if (ag.stateTimer <= 0) {
          if (ag.role === 'rail_commuter') {
            if (!ag.platIsSE) {
              const fbStart = sampleFootbridgePos(0.0);
              startConnectorWalk(
                ag,
                fbStart.u,
                fbStart.v,
                null,
                fbStart.zGnd,
                false,
                { type: 'walk_footbridge', fbFrac: 0.0, fbDir: 1, tripLabel: 'Alighting S24 → Bahnhof Footbridge' },
                'Alighting S24 → Bahnhof Footbridge',
              );
            } else {
              const dst = rng.pick(BAHNHOF_APPROACH_POIS) || 'poi_bus_bendlikon';
              startFootpathTripSmooth(ag, 'poi_bahnhof', dst, 'Alighting S8');
            }
          } else if (ag.role === 'bus_rider') {
            if (ag.targetStopPoiId && fpNodes.has(ag.targetStopPoiId)) {
              const src = ag.targetStopPoiId;
              const dstCandidates = ['poi_lindt_plaza', 'poi_seebad', 'poi_gemeindehaus', 'poi_sanatorium', 'poi_schulhaus_dorf', 'poi_kirche']
                .filter((id) => fpNodes.has(id) && id !== src);
              const dst = rng.pick(dstCandidates) || fpNodeList[0];
              startFootpathTripSmooth(ag, src, dst, 'Bus Rider');
            } else {
              const geo = ag.targetStopPoiId ? poiCurbGeo.get(ag.targetStopPoiId) : null;
              const rIdx = geo ? geo.roadIdx : 0;
              const rd = sidewalkRoads[rIdx];
              if (rd) {
                ag.state = 'walk_sidewalk';
                ag.roadIdx = rIdx;
                ag.roadDistM = geo ? geo.roadDistM : Math.min(20, (rd.length_m || 200) * 0.5);
                ag.roadDir = rng.chance(0.5) ? 1 : -1;
                ag.onElevatedDeck = false;
                ag.zGnd = null;
                ag.originName = geo ? geo.stopName : formatRoadName(rd);
                ag.destName = 'Kilchberg Village';
                ag.tripLabel = `Bus Rider → ${formatRoadName(rd)}`;
                const p = sampleSidewalkAt(rd, ag.roadDistM, ag.roadDir);
                if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
              }
            }
          }
        }
        continue;
      }

      if (ag.state === 'walk_footbridge') {
        ag.fbFrac += ag.fbDir * (ag.speedMps / 42.0) * dt;
        ag.stridePhase += dt * 7.5;
        ag.onElevatedDeck = true;
        const p = sampleFootbridgePos(ag.fbFrac);
        ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.tx = p.tx * ag.fbDir; ag.ty = p.ty * ag.fbDir;
        if (ag.fbFrac >= 1.0) {
          ag.onElevatedDeck = false;
          const dst = rng.pick(BAHNHOF_APPROACH_POIS) || 'poi_bus_bendlikon';
          startFootpathTripSmooth(ag, 'poi_bahnhof', dst, 'Commuter');
        } else if (ag.fbFrac <= 0.0) {
          ag.onElevatedDeck = false;
          ag.platIsSE = false;
          ag.targetTrainId = 'sbb_ic_north';
          const platTarget = samplePlatformPos(false, ag.platFrac, 0);
          startConnectorWalk(
            ag,
            platTarget.u,
            platTarget.v,
            null,
            platTarget.zGnd,
            false,
            { type: 'queue_rail', tripLabel: 'Commuter → Bahnhof Kilchberg (S24)' },
            'Commuter → Bahnhof Kilchberg (S24)',
          );
        }
        continue;
      }

      if (ag.state === 'queue_bus') {
        ag.stridePhase += dt * 1.2;
        if (ag.targetStopPoiId && dwellingBusPois.has(ag.targetStopPoiId)) {
          const geo = poiCurbGeo.get(ag.targetStopPoiId);
          ag.state = 'boarding';
          ag.stateTimer = 1.6;
          ag.tripLabel = geo ? `Boarding ${geo.routeLabel} · ${geo.stopName}` : 'Boarding ZVV Bus';
        }
        continue;
      }

      if (ag.state === 'queue_pier') {
        ag.stridePhase += dt * (steamerDocked ? 4.0 : 1.2);
        const p = samplePierDeckPos(ag.pierFrac);
        ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.onElevatedDeck = true;
        if (steamerDocked && steamerState.dwellProgress >= 0.08 && steamerState.dwellProgress <= 0.82) {
          ag.state = 'walk_pier_deck';
          ag.pierDir = 1;
          ag.boardingPier = true;
          ag.tripLabel = 'Boarding ZSG MS Helvetia';
        }
        continue;
      }

      if (ag.state === 'walk_pier_deck') {
        ag.pierFrac += ag.pierDir * (ag.speedMps / 16.0) * dt;
        ag.stridePhase += dt * 7.4;
        ag.onElevatedDeck = true;
        const p = samplePierDeckPos(ag.pierFrac);
        ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.tx = p.tx * ag.pierDir; ag.ty = p.ty * ag.pierDir;
        if (ag.pierDir > 0) {
          if (ag.boardingPier) {
            if (!steamerDocked) {
              ag.boardingPier = false;
              ag.pierFrac = clamp(ag.pierFrac, 0.84, 0.96);
              ag.state = 'queue_pier';
              ag.tripLabel = 'Passenger → ZSG MS Helvetia';
            } else if (ag.pierFrac >= 1.0) {
              ag.boardingPier = false;
              ag.state = 'walk_gangplank';
              ag.gpFrac = 0.0;
              ag.gpDir = 1;
              const gp = sampleGangplankPos(0.0);
              ag.u = gp.u; ag.v = gp.v; ag.zGnd = gp.zGnd; ag.tx = gp.tx; ag.ty = gp.ty;
              ag.tripLabel = 'Boarding ZSG MS Helvetia';
            }
          } else if (ag.pierFrac >= 0.90) {
            ag.state = 'queue_pier';
            ag.tripLabel = 'Passenger → ZSG MS Helvetia';
          }
        } else if (ag.pierDir < 0 && ag.pierFrac <= 0.0) {
          ag.onElevatedDeck = false;
          ag.zGnd = null;
          if (feederById.has('feeder_badweg') && rng.chance(0.45)) {
            const fd = feederById.get('feeder_badweg');
            ag.state = 'walk_feeder';
            ag.feederId = fd.id;
            ag.feederOutbound = false;
            ag.feederDistM = 0;
            const fp = sampleFeederAt(fd, 0, false);
            if (fp) { ag.u = fp.u; ag.v = fp.v; ag.d16 = fp.d16; ag.tx = fp.tx; ag.ty = fp.ty; }
            ag.tripLabel = 'ZSG Steamer → Badweg / Seestrasse';
          } else {
            const dst = rng.pick(PIER_APPROACH_POIS) || 'poi_bus_bendlikon';
            startFootpathTripSmooth(ag, 'poi_bendlikon_pier', dst, 'ZSG Steamer');
          }
        }
        continue;
      }

      if (ag.state === 'walk_gangplank') {
        ag.gpFrac += ag.gpDir * (ag.speedMps / 7.2) * dt;
        ag.stridePhase += dt * 8.6;
        ag.onElevatedDeck = true;
        const p = sampleGangplankPos(ag.gpFrac);
        ag.u = p.u; ag.v = p.v; ag.zGnd = p.zGnd; ag.tx = p.tx * ag.gpDir; ag.ty = p.ty * ag.gpDir;
        if (ag.gpDir > 0 && ag.gpFrac >= 1.0) {
          ag.state = 'in_transit';
          ag.stateTimer = 0;
        } else if (ag.gpDir < 0 && ag.gpFrac <= 0.0) {
          ag.state = 'walk_pier_deck';
          ag.pierFrac = 1.0;
          ag.pierDir = -1;
          ag.boardingPier = false;
          const dp = samplePierDeckPos(1.0);
          ag.u = dp.u; ag.v = dp.v; ag.zGnd = dp.zGnd; ag.tx = -dp.tx; ag.ty = -dp.ty;
          ag.tripLabel = 'ZSG Steamer → Bendlikon Pier';
        }
        continue;
      }

      if (ag.state === 'cw_stroll') {
        const cw = cwById.get(ag.targetCwId);
        ag.stateTimer -= dt;
        ag.stridePhase += dt * 3.8;
        if (cw) updateCrosswalkPosition(ag, cw);
        if (ag.stateTimer <= 0 && cw) {
          ag.state = 'curb_wait';
          ag.stateTimer = 0.8;
          ag.tripLabel = `Waiting at Zebra · ${cw.name || cw.id}`;
        }
        continue;
      }

      if (ag.state === 'curb_wait') {
        const cw = cwById.get(ag.targetCwId);
        ag.stateTimer -= dt;
        ag.stridePhase += dt * 1.4;
        if (cw) {
          updateCrosswalkPosition(ag, cw);
          if (ag.stateTimer <= 0.52) occupiedCrosswalks.add(cw.id);
        }
        if (ag.stateTimer <= 0 && cw) {
          ag.state = 'crossing_cw';
          ag.cwProgress = 0;
          ag.tripLabel = `Crossing Zebra · ${cw.name || cw.id}`;
          occupiedCrosswalks.add(cw.id);
        }
        continue;
      }

      if (ag.state === 'crossing_cw') {
        const cw = cwById.get(ag.targetCwId);
        ag.cwProgress += (ag.speedMps / 4.8) * dt;
        ag.stridePhase += dt * 7.6;
        if (cw) {
          occupiedCrosswalks.add(cw.id);
          updateCrosswalkPosition(ag, cw);
        }
        if (ag.cwProgress >= 1.0) {
          ag.cwDir = -ag.cwDir;
          ag.cwProgress = 0;
          ag.state = 'cw_stroll';
          ag.stateTimer = rng.range(3.5, 9.0);
        }
        continue;
      }

      if (ag.state === 'walk_feeder') {
        const fd = feederById.get(ag.feederId);
        if (!fd) {
          ag.state = 'walk_edge';
          continue;
        }
        ag.feederDistM += ag.speedMps * dt;
        ag.stridePhase += dt * (ag.speedMps * 5.2);
        const p = sampleFeederAt(fd, ag.feederDistM, ag.feederOutbound);
        if (p) {
          ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty;
        }
        if (ag.feederDistM >= fd.lengthM) {
          if (ag.role === 'pier_pax' && ag.feederOutbound) {
            ag.state = 'walk_pier_deck';
            ag.pierFrac = 0.0;
            ag.pierDir = 1;
            ag.boardingPier = false;
            ag.onElevatedDeck = true;
            const dp = samplePierDeckPos(0.0);
            ag.u = dp.u; ag.v = dp.v; ag.zGnd = dp.zGnd; ag.tx = dp.tx; ag.ty = dp.ty;
            ag.tripLabel = 'Passenger → Bendlikon ZSG Pier';
          } else {
            ag.feederOutbound = !ag.feederOutbound;
            ag.feederDistM = 0;
          }
        }
        continue;
      }

      if (ag.state === 'walk_sidewalk') {
        const rd = sidewalkRoads[ag.roadIdx];
        if (!rd) continue;
        ag.roadDistM += ag.roadDir * ag.speedMps * dt;
        const L = Math.max(20, rd.length_m || 400);
        const minD = Math.min(10, L * 0.1);
        const maxD = Math.max(minD + 1, L - minD);
        if (ag.roadDistM <= minD) {
          ag.roadDistM = minD;
          ag.roadDir = 1;
        } else if (ag.roadDistM >= maxD) {
          ag.roadDistM = maxD;
          ag.roadDir = -1;
        }
        ag.stridePhase += dt * (ag.speedMps * 5.2);
        const p = sampleSidewalkAt(rd, ag.roadDistM, ag.roadDir);
        if (p) {
          ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty;
        }
        maybeTriggerSocialPause(ag);
        continue;
      }

      if (ag.state === 'walk_edge') {
        if (!ag.edgeList || ag.edgeIdx >= ag.edgeList.length) {
          const curPoi = ag.destPoi || fpNodeList[0];
          if (ag.role === 'rail_commuter' && curPoi === 'poi_bahnhof') {
            if (!ag.platIsSE) {
              const fbEnd = sampleFootbridgePos(1.0);
              startConnectorWalk(
                ag,
                fbEnd.u,
                fbEnd.v,
                null,
                fbEnd.zGnd,
                false,
                { type: 'walk_footbridge', fbFrac: 1.0, fbDir: -1, tripLabel: 'Commuter → Bahnhof Footbridge' },
                'Commuter → Bahnhof Footbridge',
              );
            } else {
              const platTarget = samplePlatformPos(true, ag.platFrac, 0);
              startConnectorWalk(
                ag,
                platTarget.u,
                platTarget.v,
                null,
                platTarget.zGnd,
                false,
                { type: 'queue_rail', tripLabel: 'Commuter → Bahnhof Kilchberg (S8)' },
                'Commuter → Bahnhof Kilchberg (S8)',
              );
            }
            continue;
          }
          if (ag.role === 'bus_rider' && curPoi === ag.targetStopPoiId && poiCurbGeo.has(curPoi)) {
            const geo = poiCurbGeo.get(curPoi);
            const lat = geo.isMain ? 6.2 : 3.2;
            const targetU = clamp(geo.u + (geo.rx * lat) / masterW, 0.002, 0.998);
            const targetV = clamp(geo.v + (geo.ry * lat) / masterH, 0.002, 0.998);
            const curbD16 = clamp(Math.round(geo.d16 - geo.ry * lat * depthSlopeGround), 1, 65534);
            startConnectorWalk(
              ag,
              targetU,
              targetV,
              curbD16,
              null,
              false,
              { type: 'queue_bus', d16: curbD16, tripLabel: `Rider → ${geo.routeLabel} (${geo.stopName})` },
              `Rider → ${geo.routeLabel} (${geo.stopName})`,
            );
            continue;
          }
          if (ag.role === 'pier_pax' && curPoi === 'poi_bendlikon_pier') {
            const dp = samplePierDeckPos(0.0);
            startConnectorWalk(
              ag,
              dp.u,
              dp.v,
              null,
              dp.zGnd,
              false,
              { type: 'walk_pier_deck', pierFrac: 0.0, pierDir: 1, tripLabel: 'Passenger → Bendlikon ZSG Pier' },
              'Passenger → Bendlikon ZSG Pier',
            );
            continue;
          }
          if (ag.role === 'lindt_visitor' && curPoi === 'poi_lindt_plaza') {
            const targetU = lindtPlaza[0] + rng.range(-0.0017, 0.0017);
            const targetV = lindtPlaza[1] + rng.range(-0.0013, 0.0013);
            startConnectorWalk(
              ag,
              targetU,
              targetV,
              null,
              413.9,
              false,
              { type: 'plaza_admire', stateTimer: rng.range(3.5, 6.0), tripLabel: 'Admiring Lindt Chocolate Fountain' },
              'Lindt Visitor → Plaza Fountain',
            );
            continue;
          }

          let nextPool = fpNodeList;
          let prefix = 'Villager';
          if (ag.role === 'rail_commuter') {
            nextPool = ['poi_bahnhof'];
            prefix = 'Commuter';
          } else if (ag.role === 'bus_rider') {
            nextPool = fpBusPoiIds.length > 0 ? fpBusPoiIds : fpNodeList;
            prefix = 'Bus Rider';
          } else if (ag.role === 'pier_pax') {
            nextPool = ['poi_bendlikon_pier'];
            prefix = 'Pier Passenger';
          } else if (ag.role === 'lindt_visitor') {
            nextPool = ['poi_lindt_plaza'];
            ag.bagCol = null;
            prefix = 'Lindt Visitor';
          } else if (ag.role === 'dog_walker') {
            nextPool = DOG_POIS;
            prefix = 'Dog Walker';
          } else if (ag.role === 'stroller_parent') {
            nextPool = PROMENADE_POIS;
            prefix = 'Family Stroll';
          } else if (ag.role === 'couple') {
            nextPool = PROMENADE_POIS;
            prefix = 'Evening Walk';
          } else if (ag.role === 'jogger') {
            nextPool = PROMENADE_POIS;
            prefix = 'Lakefront Jogger';
          } else if (ag.role === 'schoolkid') {
            nextPool = SCHOOL_POIS;
            prefix = 'Schoolkid';
          } else if (ag.role === 'seebad_bather') {
            nextPool = ['poi_seebad', 'poi_bus_schooren', 'poi_bus_lindt'].filter((id) => fpNodes.has(id));
            prefix = 'Seebad Bather';
          }

          const cands = nextPool.filter((id) => id !== curPoi);
          const nextDst = rng.pick(cands.length > 0 ? cands : fpNodeList.filter((id) => id !== curPoi));
          if (ag.role === 'bus_rider' && nextDst) ag.targetStopPoiId = nextDst;
          if (nextDst) assignFootpathTrip(ag, curPoi, nextDst, prefix);
          continue;
        }

        const edge = ag.edgeList[ag.edgeIdx];
        ag.edgeDistM += ag.speedMps * dt;
        ag.stridePhase += dt * (ag.role === 'jogger' ? 12.2 : ag.speedMps * 5.2);
        if (ag.edgeDistM >= edge.lengthM) {
          ag.edgeDistM -= edge.lengthM;
          ag.edgeIdx++;
          if (ag.edgeIdx < ag.edgeList.length) {
            const p = sampleEdgeAt(ag.edgeList[ag.edgeIdx], ag.edgeDistM);
            if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
          }
        } else {
          const p = sampleEdgeAt(edge, ag.edgeDistM);
          if (p) { ag.u = p.u; ag.v = p.v; ag.d16 = p.d16; ag.tx = p.tx; ag.ty = p.ty; }
          maybeTriggerSocialPause(ag);
        }
      }
    }
  }

  function updateToTime(tSec, mode = 'day', transitSnapshot = null) {
    const safeT = Number.isFinite(tSec) ? Math.max(0, Math.min(MAX_SIM_TIME, tSec)) : 0;
    const normMode = normModeName(mode);

    const needReset = !initialized
      || normMode !== currentMode
      || safeT < simTime - 1e-6
      || (safeT - simTime) > 2.0;

    if (needReset) {
      const tStart = safeT <= 60 ? 0 : Math.floor(safeT - 60);
      resetState(normMode, tStart);
      let guard = 0;
      while (simTime + PED_FIXED_DT <= safeT + 1e-9 && guard < 2400) {
        step(PED_FIXED_DT, null);
        guard++;
      }
    } else {
      let guard = 0;
      while (simTime + PED_FIXED_DT <= safeT + 1e-9 && guard < 80) {
        step(PED_FIXED_DT, transitSnapshot);
        guard++;
      }
    }
    subStepRem = Math.max(0, Math.min(PED_FIXED_DT, safeT - simTime));
    lastTargetT = safeT;
    return {
      occupiedCrosswalks: getOccupiedCrosswalks(),
      stats: getStats(),
    };
  }

  function getOccupiedCrosswalks() {
    return new Set(occupiedCrosswalks);
  }

  function getStats() {
    let pedestrians = 0;
    let boardingCount = 0;
    let activeTrips = 0;
    for (let i = 0; i < agents.length; i++) {
      const ag = agents[i];
      if (ag.state === 'in_transit') continue;
      pedestrians += ag.role === 'couple' ? 2 : 1;
      if (ag.state === 'boarding' || ag.state === 'alighting' || ag.state === 'walk_gangplank') {
        boardingCount++;
      }
      if (
        ag.state === 'walk_edge' || ag.state === 'walk_sidewalk' || ag.state === 'walk_feeder'
        || ag.state === 'walk_connector'
        || ag.state === 'walk_footbridge' || ag.state === 'walk_pier_deck' || ag.state === 'walk_gangplank'
        || ag.state === 'queue_rail' || ag.state === 'queue_bus' || ag.state === 'queue_pier'
        || ag.state === 'boarding' || ag.state === 'alighting' || ag.state === 'crossing_cw'
        || ag.state === 'curb_wait'
      ) {
        activeTrips++;
      }
    }
    const prof = getDiurnalProfile(currentMode);
    void prof;
    return { pedestrians, boardingCount, activeTrips };
  }

  function getDrawablePedestrians(worldW, worldH, wScale, cam, depthMgr) {
    if (!cam || cam.scale < 0.35) return [];
    const { scale, offsetX, offsetY, width: canvasW, height: canvasH } = cam;
    const padU = Math.max(0.005, 48 / Math.max(1, worldW * scale));
    const padV = Math.max(0.010, 48 / Math.max(1, worldH * scale));
    const visU0 = (-offsetX / Math.max(1, worldW * scale)) - padU;
    const visU1 = ((canvasW - offsetX) / Math.max(1, worldW * scale)) + padU;
    const visV0 = (-offsetY / Math.max(1, worldH * scale)) - padV;
    const visV1 = ((canvasH - offsetY) / Math.max(1, worldH * scale)) + padV;

    const out = [];
    for (let i = 0; i < agents.length; i++) {
      const ag = agents[i];
      if (ag.state === 'in_transit') continue;
      if (ag.u < visU0 || ag.u > visU1 || ag.v < visV0 || ag.v > visV1) continue;
      const wx = ag.u * worldW;
      const wy = ag.v * worldH;
      let d16 = ag.d16;
      if (ag.zGnd != null && depthMgr) {
        d16 = depthMgr.evalWalkerD16(wx, wy, ag.zGnd, worldW, worldH, !!ag.onElevatedDeck);
      }
      const wide = ag.hasDog || ag.hasStroller || !!ag.partnerCoat;
      out.push({
        type: 'ped_sim',
        id: ag.id,
        role: ag.role,
        state: ag.state,
        pos: { wx, wy, tx: ag.tx, ty: ag.ty, d16 },
        bounds: {
          ex: (wide ? 7.5 : 4.5) * wScale,
          eyUp: 9.5 * wScale,
          eyDn: 3.5 * wScale,
        },
        coatCol: ag.coatCol,
        pantsCol: ag.pantsCol,
        hairCol: ag.hairCol,
        bagCol: ag.bagCol,
        hasDog: ag.hasDog,
        dogCol: ag.dogCol,
        hasStroller: ag.hasStroller,
        partnerCoat: ag.partnerCoat,
        partnerHair: ag.partnerHair,
        stridePhase: ag.stridePhase,
        tripLabel: ag.tripLabel,
        originName: ag.originName,
        destName: ag.destName,
      });
    }
    return out;
  }

  function getInspectablePedestrians(worldW, worldH) {
    const out = [];
    for (let i = 0; i < agents.length; i++) {
      const ag = agents[i];
      if (ag.state === 'in_transit') continue;
      out.push({
        id: ag.id,
        wx: ag.u * worldW,
        wy: ag.v * worldH,
        u: ag.u,
        v: ag.v,
        role: ag.role,
        state: ag.state,
        tripLabel: ag.tripLabel,
        originName: ag.originName,
        destName: ag.destName,
      });
    }
    return out;
  }

  return {
    updateToTime,
    getOccupiedCrosswalks,
    getStats,
    getDrawablePedestrians,
    getInspectablePedestrians,
  };
}
