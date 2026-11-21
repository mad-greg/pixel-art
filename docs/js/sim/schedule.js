/**
 * Unified transit schedules (SBB S8/IC, ZVV 161/165, ZSG MS Helvetia),
 * diurnal activity curves (day/sunset/night), unified SW->NE wind vector,
 * and canonical church bell phase (52 s cycle, 20 s ringing window).
 */

export const BELL_PERIOD_SEC = 52.0;
export const BELL_RING_SEC = 20.0;

const stopScheduleCache = new Map();

export function buildStopSchedule(lengthM, speedMps, stops, dwellSec, rampSec = 5.0, offscreenSec = 6.0) {
  const v = Math.max(0.5, speedMps) / Math.max(1.0, lengthM);
  const pause = Math.max(0, dwellSec || 0);
  const ramp = Math.max(0.1, rampSec || 5.0);
  const offSec = Math.max(0, offscreenSec || 0);
  const validStops = (Array.isArray(stops) ? stops : (stops != null ? [stops] : []))
    .filter((s) => typeof s === 'number' && !Number.isNaN(s) && s > 0.001 && s < 0.999)
    .sort((a, b) => a - b);

  const segs = [];
  let tCur = 0;
  let sCur = 0;

  if (validStops.length === 0 || pause <= 0) {
    const dur = 1.0 / v;
    segs.push({ t0: 0, t1: dur, type: 'cruise', s0: 0, s1: 1, stopIdx: -1 });
    tCur = dur;
  } else {
    const K = validStops.length;
    for (let k = 0; k < K; k++) {
      const sk = validStops[k];
      const gapBefore = k === 0 ? sk : 0.5 * (sk - validStops[k - 1]);
      const gapAfter = k === K - 1 ? (1.0 - sk) : 0.5 * (validStops[k + 1] - sk);
      const dsDecel = Math.min(0.5 * v * ramp, 0.9 * gapBefore);
      const tauDecel = dsDecel > 1e-9 ? (2.0 * dsDecel) / v : 0;
      const dsAccel = Math.min(0.5 * v * ramp, 0.9 * gapAfter);
      const tauAccel = dsAccel > 1e-9 ? (2.0 * dsAccel) / v : 0;

      const sDecelStart = Math.max(sCur, sk - dsDecel);
      if (sDecelStart > sCur + 1e-9) {
        const dur = (sDecelStart - sCur) / v;
        segs.push({ t0: tCur, t1: tCur + dur, type: 'cruise', s0: sCur, s1: sDecelStart, stopIdx: -1 });
        tCur += dur;
        sCur = sDecelStart;
      }
      if (tauDecel > 1e-9 && sk > sCur + 1e-9) {
        segs.push({ t0: tCur, t1: tCur + tauDecel, type: 'decel', s0: sCur, s1: sk, stopIdx: k });
        tCur += tauDecel;
        sCur = sk;
      }
      segs.push({ t0: tCur, t1: tCur + pause, type: 'dwell', s0: sk, s1: sk, stopIdx: k });
      tCur += pause;
      if (tauAccel > 1e-9) {
        const sAccelEnd = Math.min(1.0, sk + dsAccel);
        segs.push({ t0: tCur, t1: tCur + tauAccel, type: 'accel', s0: sk, s1: sAccelEnd, stopIdx: k });
        tCur += tauAccel;
        sCur = sAccelEnd;
      }
    }
    if (1.0 > sCur + 1e-9) {
      const dur = (1.0 - sCur) / v;
      segs.push({ t0: tCur, t1: tCur + dur, type: 'cruise', s0: sCur, s1: 1.0, stopIdx: -1 });
      tCur += dur;
    }
  }

  return { segs, activeSec: tCur, cycleSec: tCur + offSec };
}

export function evalStopSchedule(sched, tSec, phase = 0) {
  const cycle = sched.cycleSec;
  if (!(cycle > 0)) {
    return {
      frac: -1,
      speedRatio: 0,
      isDwelling: false,
      stopIdx: -1,
      dwellProgress: 0,
      phaseType: 'offscreen',
      segRemaining: 0,
    };
  }
  const safeT = Number.isFinite(tSec) ? tSec : 0;
  const localT = (((safeT + phase * cycle) % cycle) + cycle) % cycle;
  if (localT > sched.activeSec) {
    return {
      frac: -1,
      speedRatio: 0,
      isDwelling: false,
      stopIdx: -1,
      dwellProgress: 0,
      phaseType: 'offscreen',
      segRemaining: cycle - localT,
    };
  }
  const segs = sched.segs;
  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i];
    if (localT <= seg.t1 || i === segs.length - 1) {
      const dur = Math.max(1e-9, seg.t1 - seg.t0);
      const u = Math.max(0, Math.min(1, (localT - seg.t0) / dur));
      const segRemaining = Math.max(0, seg.t1 - localT);
      if (seg.type === 'cruise') {
        return {
          frac: seg.s0 + (seg.s1 - seg.s0) * u,
          speedRatio: 1.0,
          isDwelling: false,
          stopIdx: -1,
          dwellProgress: 0,
          phaseType: 'cruise',
          segRemaining,
        };
      }
      if (seg.type === 'decel') {
        return {
          frac: seg.s0 + (seg.s1 - seg.s0) * (2.0 * u - u * u),
          speedRatio: 1.0 - u,
          isDwelling: false,
          stopIdx: seg.stopIdx,
          dwellProgress: 0,
          phaseType: 'decel',
          segRemaining,
        };
      }
      if (seg.type === 'dwell') {
        return {
          frac: seg.s0,
          speedRatio: 0.0,
          isDwelling: true,
          stopIdx: seg.stopIdx,
          dwellProgress: u,
          phaseType: 'dwell',
          segRemaining,
        };
      }
      return {
        frac: seg.s0 + (seg.s1 - seg.s0) * (u * u),
        speedRatio: u,
        isDwelling: false,
        stopIdx: seg.stopIdx,
        dwellProgress: 0,
        phaseType: 'accel',
        segRemaining,
      };
    }
  }
  return {
    frac: 1.0,
    speedRatio: 1.0,
    isDwelling: false,
    stopIdx: -1,
    dwellProgress: 0,
    phaseType: 'cruise',
    segRemaining: 0,
  };
}

export function evalWithStationStop(tSec, lengthM, speedMps, stopFracOrStops, dwellSec, phase = 0, rampSec = 5.0, offscreenSec = 6.0) {
  const stopsKey = Array.isArray(stopFracOrStops)
    ? stopFracOrStops.join(',')
    : (stopFracOrStops != null ? String(stopFracOrStops) : '');
  const key = `${lengthM}|${speedMps}|${stopsKey}|${dwellSec || 0}|${rampSec}|${offscreenSec}`;
  let sched = stopScheduleCache.get(key);
  if (!sched) {
    sched = buildStopSchedule(lengthM, speedMps, stopFracOrStops, dwellSec, rampSec, offscreenSec);
    if (stopScheduleCache.size > 256) stopScheduleCache.clear();
    stopScheduleCache.set(key, sched);
  }
  return evalStopSchedule(sched, tSec, phase || 0);
}

export function evalTrainState(tr, tSec) {
  const nCars = tr.carriages || 4;
  const trainLenM = (nCars - 1) * 19.5 + 18.1; // 76.6 m for 4-car consist
  const halfTrainM = trainLenM * 0.5;          // 38.3 m half-consist
  const effLenM = tr.length_m + trainLenM;
  if (!tr._stopSched) {
    const rawStopFrac = tr.stop_frac != null
      ? (tr.stop_frac * tr.length_m + halfTrainM) / effLenM
      : null;
    tr._stopSched = buildStopSchedule(
      effLenM,
      tr.speed_mps,
      rawStopFrac != null ? [rawStopFrac] : [],
      tr.dwell_sec || 0,
      5.0,
      6.0,
    );
  }
  const st = evalStopSchedule(tr._stopSched, tSec, tr.phase || 0);
  // Compute seconds until next Bahnhof dwell start (for M4 commuter gathering pulse)
  let secUntilArrival = Infinity;
  const dwellSeg = tr._stopSched.segs.find((sg) => sg.type === 'dwell');
  if (dwellSeg) {
    const cycle = tr._stopSched.cycleSec;
    const safeT = Number.isFinite(tSec) ? tSec : 0;
    const localT = (((safeT + (tr.phase || 0) * cycle) % cycle) + cycle) % cycle;
    if (localT < dwellSeg.t0) {
      secUntilArrival = dwellSeg.t0 - localT;
    } else if (localT <= dwellSeg.t1) {
      secUntilArrival = 0;
    } else {
      secUntilArrival = cycle - localT + dwellSeg.t0;
    }
  }
  if (st.frac < 0) {
    return {
      headFrac: -1,
      midFrac: -1,
      speedRatio: 0,
      isDwelling: false,
      stopIdx: -1,
      dwellProgress: 0,
      phaseType: 'offscreen',
      secUntilArrival,
    };
  }
  const headFrac = st.frac * (effLenM / tr.length_m);
  const midFrac = headFrac - halfTrainM / tr.length_m;
  return {
    headFrac,
    midFrac,
    speedRatio: st.speedRatio,
    isDwelling: st.isDwelling,
    stopIdx: st.stopIdx,
    dwellProgress: st.dwellProgress,
    phaseType: st.phaseType,
    secUntilArrival,
  };
}

export function evalBusScheduleState(rd, bIdx, tSec, activeBusCount = null) {
  const busCount = Math.max(
    1,
    activeBusCount != null ? activeBusCount : (rd.bus_count != null ? rd.bus_count : (rd.has_bus ? 1 : 0)),
  );
  const laneSpeed = Math.max(1.0, rd.speed_mps * 0.88);
  if (!rd._busSched) {
    rd._busSched = buildStopSchedule(rd.length_m, laneSpeed, rd.stops || [], 3.2, 3.0, 0.0);
  }
  const phase = (rd.phase || 0) + bIdx / busCount;
  return evalStopSchedule(rd._busSched, tSec, phase);
}

export function evalShipState(ship, tSec, mode = 'day') {
  const safeT = Number.isFinite(tSec) ? tSec : 0;
  const visible = !(mode === 'night' && ship.kind !== 'zsg_steamer');
  if (!visible) {
    return {
      visible: false,
      frac: -1,
      speedRatio: 0,
      isDocked: false,
      dwellProgress: 0,
      phaseType: 'offscreen',
    };
  }
  if (ship.closed) {
    const cyc = ship.length_m / Math.max(0.5, ship.speed_mps);
    const frac = (((safeT / cyc) + (ship.phase || 0)) % 1 + 1) % 1;
    return {
      visible: true,
      frac,
      speedRatio: 1.0,
      isDocked: false,
      dwellProgress: 0,
      phaseType: 'cruise',
    };
  }
  const st = evalWithStationStop(safeT, ship.length_m, ship.speed_mps, ship.stop_frac, ship.dwell_sec, ship.phase || 0, 5.0, 6.0);
  return {
    visible: st.frac >= 0 && st.frac <= 1,
    frac: st.frac,
    speedRatio: st.speedRatio,
    isDocked: st.isDwelling,
    dwellProgress: st.dwellProgress,
    phaseType: st.phaseType,
  };
}

export function samplePathAt(pts, frac, worldW, worldH, tanWin = 3) {
  const n = pts ? pts.length : 0;
  if (n < 2 || frac < 0 || frac > 1) return null;
  const fIdx = frac * (n - 1);
  const i0 = Math.min(n - 2, Math.max(0, Math.floor(fIdx)));
  const t = fIdx - i0;
  const p0 = pts[i0];
  const p1 = pts[i0 + 1];
  const wx = (p0[0] + (p1[0] - p0[0]) * t) * worldW;
  const wy = (p0[1] + (p1[1] - p0[1]) * t) * worldH;

  const ia = Math.max(0, i0 - tanWin);
  const ib = Math.min(n - 1, i0 + 1 + tanWin);
  let dx = (pts[ib][0] - pts[ia][0]) * worldW;
  let dy = (pts[ib][1] - pts[ia][1]) * worldH;
  const mag = Math.hypot(dx, dy) || 1;
  dx /= mag;
  dy /= mag;
  const occ = (t < 0.5 ? p0[2] : p1[2]) === 1;
  const d16 = p0.length > 3 && p1.length > 3
    ? Math.round(p0[3] + (p1[3] - p0[3]) * t)
    : 0;
  return { wx, wy, tx: dx, ty: dy, occ, d16 };
}

export function getDiurnalProfile(mode = 'day') {
  if (mode === 'night') {
    return {
      mode: 'night',
      carFactor: 0.44,
      feederCount: 2,
      busMode: 'night',      // 1 bus per bus road -> 6 buses total
      cyclistFactor: 0.25,   // ~10 cyclists
      pedFactor: 0.22,
      speedFactor: 1.04,
      crosswalkRate: 0.22,
      deliveryActive: false,
    };
  }
  if (mode === 'sunset') {
    return {
      mode: 'sunset',
      carFactor: 0.78,
      feederCount: 4,
      busMode: 'sunset',     // cap viaduct to 1/dir -> 8 buses total
      cyclistFactor: 0.62,   // ~24 cyclists
      pedFactor: 0.74,
      speedFactor: 0.96,
      crosswalkRate: 0.78,
      deliveryActive: true,
    };
  }
  return {
    mode: 'day',
    carFactor: 1.0,
    feederCount: 6,
    busMode: 'day',          // full 10 buses (2,2,2,2,1,1)
    cyclistFactor: 1.0,      // ~38 cyclists
    pedFactor: 1.0,
    speedFactor: 1.0,
    crosswalkRate: 1.0,
    deliveryActive: true,
  };
}

/**
 * Unified gentle SW->NE Lake Zurich breeze vector shared by flags, chimney steam,
 * village smoke, sails, and drifting clouds.
 */
export function getWindVector(tSec) {
  const safeT = Number.isFinite(tSec) ? tSec : 0;
  const gust = 1.0 + 0.16 * Math.sin(safeT * 0.37) + 0.08 * Math.sin(safeT * 0.91 + 1.4);
  return {
    wx: 0.96 * gust,
    wy: -0.28 * gust,
    strength: 0.72 * gust,
    wavePhase: safeT * 5.0,
  };
}

/**
 * Canonical Swiss church bell phase (Reformierte Kirche & St. Elisabeth).
 * 52 s cycle, ringing during [0, 20) s in day and sunset; silent at night.
 */
export function evalBellState(tSec, mode = 'day') {
  const safeT = Number.isFinite(tSec) ? tSec : 0;
  const cycle = ((safeT % BELL_PERIOD_SEC) + BELL_PERIOD_SEC) % BELL_PERIOD_SEC;
  const bellPhase = cycle / BELL_PERIOD_SEC;
  const isNight = mode === 'night';
  const ringing = !isNight && cycle < BELL_RING_SEC;
  let envelope = 0;
  if (ringing) {
    envelope = cycle < 2.2
      ? cycle / 2.2
      : (cycle > 17.0 ? (BELL_RING_SEC - cycle) / 3.0 : 1.0);
  }
  return { bellPhase, cycle, ringing, envelope };
}

/**
 * Format a road object or raw snake-case road ID into a clean human-readable
 * Kilchberg street name for inspector titles and trip labels.
 */
export function formatRoadName(rdOrId) {
  if (!rdOrId) return 'Kilchberg';
  if (typeof rdOrId === 'object' && rdOrId.name) return rdOrId.name;
  const id = String(typeof rdOrId === 'object' ? (rdOrId.id || '') : rdOrId);
  if (!id) return 'Kilchberg';
  if (id.startsWith('dorfstrasse_viaduct')) return 'Dorfstrasse Viaduct';
  if (id.startsWith('seestrasse')) return 'Seestrasse';
  if (id.startsWith('alte_landstrasse')) return 'Alte Landstrasse';
  if (id.startsWith('a3_motorway')) return 'A3 Motorway';
  return id
    .replace(/_(nb|sb|eb|wb|up|dn|north|south|east|west|\d+)$/i, '')
    .split('_')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ') || 'Kilchberg';
}

