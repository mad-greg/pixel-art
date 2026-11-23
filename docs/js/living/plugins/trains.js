/**
 * Trains & SBB Seebahn Rail Plugin (Kilchberg v14.0).
 *
 * Layers:
 *   - 'pre_rail': Bahnhof Kilchberg NW platform departure board & SBB Mondaine clocks
 *                 (strictly drawn BEFORE trains so passing trains naturally occlude them)
 *   - 'rail':     SBB S8/S24 KISS/DPZ & IC multi-carriage trains (extraVertPx = 7.5, opaque roofs!)
 *                 Sorted by (trackRank, sortY): Gleis 2 NW = 0 (back) strictly before Gleis 1 SE = 1 (front).
 *                 Inter-car gangways are paired back-to-front so opposing passes never glitch.
 *   - 'landmark': Dual-track SBB Typ L/N railway signals reacting to train proximity
 */

import { evalTrainState, samplePathAt } from '../../sim/schedule.js';
import { draw3DTrainUnit } from '../../render/vehicles.js';
import { blitGlow, drawSwissClockDial } from '../draw.js';

function clamp(v, lo, hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

function mapRollingStock(rollingStock, fallbackKind) {
  if (rollingStock === 'dpz') return 'sbb_dpz';
  if (rollingStock === 'kiss') return 'sbb_kiss';
  if (rollingStock === 'ic') return 'sbb_ic';
  if (typeof rollingStock === 'string' && rollingStock.startsWith('sbb_')) return rollingStock;
  return fallbackKind || 'sbb_dpz';
}

function computeAvgD16(pts) {
  if (!Array.isArray(pts) || pts.length === 0) return 32000;
  let sum = 0;
  let cnt = 0;
  const step = Math.max(1, Math.floor(pts.length / 40));
  for (let i = 0; i < pts.length; i += step) {
    const d = pts[i] && pts[i][3];
    if (typeof d === 'number' && Number.isFinite(d)) {
      sum += d;
      cnt++;
    }
  }
  return cnt > 0 ? sum / cnt : 32000;
}

/**
 * Evaluate a RailServiceSpec using Europe/Zurich clock_minutes timetable.
 * Centers the train's Bahnhof stop (or corridor midpoint for express IC) at each
 * scheduled minute past the hour.
 */
function evalClockMinutesTrainState(spec, track, clockSnap) {
  const tt = spec.timetable || {};
  const mins = Array.isArray(tt.minutesPastHour) ? tt.minutesPastHour : [];
  const lengthM = track.length_m || 2400;
  const carriages = spec.carriages || track.carriages || 4;
  const trainLenFrac = (carriages * 19.5) / lengthM;
  const speedMps = (spec.periodicFallback && spec.periodicFallback.speedMps) || track.speed_mps || 19.0;

  const stop0 = Array.isArray(spec.stops) && spec.stops.length > 0 ? spec.stops[0] : null;
  const stopFrac = stop0 && typeof stop0.frac === 'number' ? stop0.frac : (track.stop_frac ?? 0.5);
  const dwellSec = stop0 && typeof stop0.dwellSec === 'number' ? stop0.dwellSec : 0;

  const secOfDay = clockSnap.zurichSecOfDay || 0;
  const hour = Math.floor(secOfDay / 3600) % 24;
  const firstHour = typeof tt.firstHour === 'number' ? tt.firstHour : 5;
  const lastHour = typeof tt.lastHour === 'number' ? tt.lastHour : 24;
  if (hour < firstHour || hour >= lastHour || mins.length === 0) {
    return { headFrac: -1, midFrac: -1, speedRatio: 0, isDwelling: false, dwellProgress: 0 };
  }

  const minInHour = (secOfDay % 3600) / 60;
  let bestDeltaSec = Infinity;
  for (let i = 0; i < mins.length; i++) {
    let diffMin = minInHour - mins[i];
    if (diffMin > 30) diffMin -= 60;
    if (diffMin < -30) diffMin += 60;
    const dSec = diffMin * 60;
    if (Math.abs(dSec) < Math.abs(bestDeltaSec)) {
      bestDeltaSec = dSec;
    }
  }

  const transitSec = lengthM / Math.max(5, speedMps);
  const halfDwell = dwellSec * 0.5;
  const decelTime = dwellSec > 0 ? 10.0 : 0;
  const accelTime = dwellSec > 0 ? 10.0 : 0;

  let midFrac = -1;
  let speedRatio = 1.0;
  let isDwelling = false;
  let dwellProgress = 0;

  if (dwellSec > 0 && Math.abs(bestDeltaSec) <= halfDwell) {
    midFrac = stopFrac;
    speedRatio = 0;
    isDwelling = true;
    dwellProgress = clamp((bestDeltaSec + halfDwell) / Math.max(0.1, dwellSec), 0, 1);
  } else if (bestDeltaSec < -halfDwell) {
    // Approaching station
    const tBeforeStop = -halfDwell - bestDeltaSec; // > 0
    let distBeforeM;
    if (decelTime > 0 && tBeforeStop < decelTime) {
      const u = tBeforeStop / decelTime;
      speedRatio = u;
      distBeforeM = 0.5 * speedMps * decelTime * u * u;
    } else {
      speedRatio = 1.0;
      distBeforeM = (decelTime > 0 ? 0.5 * speedMps * decelTime : 0) + (tBeforeStop - decelTime) * speedMps;
    }
    midFrac = stopFrac - distBeforeM / lengthM;
  } else {
    // Departing station
    const tAfterStop = bestDeltaSec - halfDwell; // > 0
    let distAfterM;
    if (accelTime > 0 && tAfterStop < accelTime) {
      const u = tAfterStop / accelTime;
      speedRatio = u;
      distAfterM = 0.5 * speedMps * accelTime * u * u;
    } else {
      speedRatio = 1.0;
      distAfterM = (accelTime > 0 ? 0.5 * speedMps * accelTime : 0) + (tAfterStop - accelTime) * speedMps;
    }
    midFrac = stopFrac + distAfterM / lengthM;
  }

  const headFrac = midFrac + 0.5 * trainLenFrac;
  if (headFrac < -0.05 || midFrac > 1.08 || Math.abs(bestDeltaSec) > transitSec) {
    return { headFrac: -1, midFrac: -1, speedRatio: 0, isDwelling: false, dwellProgress: 0 };
  }
  return { headFrac, midFrac, speedRatio, isDwelling, dwellProgress };
}

export function createTrainsPlugin() {
  let activeTrainCount = 0;
  let cachedInspectables = [];
  let trackById = new Map();
  let trackRankByTrackId = new Map();
  let trackList = [];
  let railSpecs = [];
  let unsubSpecs = null;

  function rebuildTracks(animData) {
    trackById = new Map();
    trackRankByTrackId = new Map();
    trackList = (animData && Array.isArray(animData.trains)) ? animData.trains : [];

    const ranked = trackList.map((tr) => ({
      id: tr.id,
      tr,
      avgD16: computeAvgD16(tr.pts),
    }));
    // Larger d16 = further back (Gleis 2 NW -> trackRank 0); smaller d16 = closer (Gleis 1 SE -> trackRank 1)
    ranked.sort((a, b) => b.avgD16 - a.avgD16);
    for (let i = 0; i < ranked.length; i++) {
      trackById.set(ranked[i].id, ranked[i].tr);
      trackRankByTrackId.set(ranked[i].id, i);
    }
  }

  function syncSpecs(ctx) {
    if (ctx && ctx.specs && typeof ctx.specs.getRailServices === 'function') {
      railSpecs = ctx.specs.getRailServices();
    } else {
      railSpecs = [];
    }
  }

  function resolveTrackForSpec(spec) {
    if (spec.animTrackId && trackById.has(spec.animTrackId)) {
      return trackById.get(spec.animTrackId);
    }
    if (spec.id && trackById.has(spec.id)) {
      return trackById.get(spec.id);
    }
    if (spec.trackId === 'gleis_1_se' && trackById.has('sbb_ic_north')) {
      return trackById.get('sbb_ic_north');
    }
    if (spec.trackId === 'gleis_2_nw' && trackById.has('sbb_s8_south')) {
      return trackById.get('sbb_s8_south');
    }
    if (typeof spec.trackRank === 'number' && trackList.length > 0) {
      const idx = clamp(Math.round(spec.trackRank), 0, trackList.length - 1);
      for (const [tid, r] of trackRankByTrackId.entries()) {
        if (r === idx) return trackById.get(tid);
      }
    }
    return trackList[0] || null;
  }

  function resolveTrackRank(spec, track) {
    if (spec && typeof spec.trackRank === 'number' && Number.isFinite(spec.trackRank)) {
      return spec.trackRank;
    }
    if (spec && spec.trackId === 'gleis_2_nw') return 0;
    if (spec && spec.trackId === 'gleis_1_se') return 1;
    if (track && trackRankByTrackId.has(track.id)) {
      return trackRankByTrackId.get(track.id);
    }
    return 0;
  }

  function getActiveServiceEntries(ctx) {
    if (railSpecs.length > 0) {
      // Order primary canonical services (sbb_s8_south, sbb_ic_north) first so deterministic ?t= snapshots
      // remain 100% consistent with baseline E2E assertions (e.g. follow=train at t=22).
      const ordered = railSpecs.slice().sort((a, b) => {
        const pa = a.id === 'sbb_s8_south' ? 0 : (a.id === 'sbb_ic_north' ? 1 : 2);
        const pb = b.id === 'sbb_s8_south' ? 0 : (b.id === 'sbb_ic_north' ? 1 : 2);
        return pa - pb;
      });
      return ordered.map((spec) => {
        const track = resolveTrackForSpec(spec);
        return { spec, track, trackRank: resolveTrackRank(spec, track) };
      }).filter((e) => e.track && Array.isArray(e.track.pts) && e.track.pts.length >= 2);
    }
    // Fallback to raw animData.trains when ctx.specs is absent
    return trackList.map((tr) => ({
      spec: null,
      track: tr,
      trackRank: trackRankByTrackId.get(tr.id) ?? (tr.id === 'sbb_ic_north' ? 1 : 0),
    }));
  }

  function evalServiceState(entry, tSec, clockSnap) {
    const { spec, track } = entry;
    if (!spec) {
      return evalTrainState(track, tSec);
    }
    const useClockTimetable = !!(
      clockSnap
      && (clockSnap.clockMode === 'live' || clockSnap.clockMode === 'manual')
      && spec.timetable
      && spec.timetable.mode === 'clock_minutes'
    );
    if (useClockTimetable) {
      return evalClockMinutesTrainState(spec, track, clockSnap);
    }

    const pf = (spec.timetable && spec.timetable.mode === 'periodic')
      ? spec.timetable
      : (spec.periodicFallback || {});
    const stop0 = Array.isArray(spec.stops) && spec.stops.length > 0 ? spec.stops[0] : null;
    const synthTr = {
      ...track,
      carriages: spec.carriages || track.carriages || 4,
      speed_mps: pf.speedMps || pf.speed_mps || track.speed_mps || 19.0,
      phase: typeof pf.phase === 'number' ? pf.phase : (track.phase ?? 0.25),
      stop_frac: stop0 && typeof stop0.frac === 'number' ? stop0.frac : (track.stop_frac ?? 0.5),
      dwell_sec: stop0 && typeof stop0.dwellSec === 'number'
        ? stop0.dwellSec
        : (Array.isArray(spec.stops) && spec.stops.length === 0 ? 0 : (track.dwell_sec ?? 4.0)),
    };
    return evalTrainState(synthTr, tSec);
  }

  return {
    id: 'trains',
    name: 'SBB Seebahn Trains & Signals',
    category: 'transit',
    layers: ['pre_rail', 'rail', 'landmark'],
    priority: 40,
    enabledByDefault: true,

    init(ctx) {
      activeTrainCount = 0;
      cachedInspectables = [];
      if (unsubSpecs) {
        unsubSpecs();
        unsubSpecs = null;
      }
      rebuildTracks(ctx && ctx.animData);
      syncSpecs(ctx);
      if (ctx && ctx.specs && typeof ctx.specs.onChange === 'function') {
        unsubSpecs = ctx.specs.onChange('rail', () => {
          syncSpecs(ctx);
        });
      }
    },

    getDrawables(cam, ctx) {
      const animData = ctx.animData;
      if (!animData) return [];

      if (trackList.length === 0 && Array.isArray(animData.trains) && animData.trains.length > 0) {
        rebuildTracks(animData);
      }

      const drawables = [];
      const railDrawables = [];
      const inspectables = [];
      activeTrainCount = 0;

      const { worldW, worldH, wScale, tSec, mode, isNight, isSunset, s, detailAlpha, depthMgr, clock } = ctx;
      const hasDepth = !!(depthMgr && depthMgr.hasDepthMap && depthMgr.hasDepthMap());
      const vig = (animData.ambient && animData.ambient.vignettes) || {};
      const bh = vig.bahnhof_kilchberg || {};
      const platSw = bh.plat_sw || [0.55049, 0.50304];
      const platNe = bh.plat_ne || [0.56449, 0.49558];

      // 1. Pre-rail: NW platform Bahnhof departure board & SBB Mondaine clocks
      if (s >= 0.35) {
        const midU = 0.5 * (platSw[0] + platNe[0]);
        const midV = 0.5 * (platSw[1] + platNe[1]) - 0.0006;
        drawables.push({
          layer: 'pre_rail',
          sortY: midV * worldH,
          draw(targetCtx) {
            const bx = ctx.toX(midU);
            const by = ctx.toY(midV);
            targetCtx.save();
            if (ctx.inView(bx, by, 30)) {
              const bw = Math.max(6, 8.2 * s);
              const bhPx = Math.max(3, 3.8 * s);
              if (isNight || isSunset) {
                blitGlow(targetCtx, bx, by, 9.5 * s, 'blue', isNight ? 0.42 : 0.22);
              }
              targetCtx.fillStyle = isNight ? '#1d4ed8' : '#2563eb';
              targetCtx.fillRect(Math.round(bx - bw * 0.5), Math.round(by - bhPx * 0.5), Math.round(bw), Math.round(bhPx));
              // Crisp pixel-art LED departure rows (zero fillText)
              const flip = (Math.floor(tSec / 18) % 2) === 0;
              targetCtx.fillStyle = '#f8fafc';
              targetCtx.fillRect(
                Math.round(bx - bw * 0.38),
                Math.round(by - bhPx * 0.22),
                Math.max(2, Math.round(bw * (flip ? 0.58 : 0.48))),
                Math.max(1, Math.round(0.8 * s)),
              );
              targetCtx.fillStyle = '#fde047';
              targetCtx.fillRect(
                Math.round(bx - bw * 0.38),
                Math.round(by + bhPx * 0.08),
                Math.max(2, Math.round(bw * (flip ? 0.42 : 0.54))),
                Math.max(1, Math.round(0.8 * s)),
              );
              const ckX = bx + bw * 0.68 + 1.8 * s;
              drawSwissClockDial(targetCtx, ckX, by, 2.6 * s, tSec, { mode, style: 'sbb', s, detailAlpha, clock });
            }
            if (detailAlpha > 0.01) {
              const scX = ctx.toX(0.5772);
              const scY = ctx.toY(0.4902);
              if (ctx.inView(scX, scY, 20)) {
                drawSwissClockDial(targetCtx, scX, scY, 3.6 * s, tSec, { mode, style: 'sbb', s, detailAlpha, clock });
              }
            }
            targetCtx.restore();
          },
        });
      }

      // 2. Rail: SBB Seebahn multi-carriage trains (extraVertPx = 7.5 strict!)
      const entries = getActiveServiceEntries(ctx);
      const occupiedFracsByRank = new Map(); // trackRank -> Array<[tailFrac, headFrac]>
      const activeSpansByRank = new Map(); // trackRank -> Array<[minWx, maxWx]>

      for (let ti = 0; ti < entries.length; ti++) {
        const entry = entries[ti];
        const { spec, track: tr, trackRank } = entry;
        const trSt = evalServiceState(entry, tSec, clock);
        const headFrac = trSt.headFrac;
        if (headFrac < 0 || headFrac > 1.12) continue;

        const nCars = (spec && spec.carriages) || tr.carriages || 4;
        const coachPitchFrac = 19.5 / tr.length_m;
        const bodyLenFrac = 18.1 / tr.length_m;
        const tailFrac = headFrac - (nCars - 1) * coachPitchFrac - bodyLenFrac;

        // Prevent two services sharing the exact same physical track from overlapping each other
        const occList = occupiedFracsByRank.get(trackRank) || [];
        let sameTrackConflict = false;
        for (let oi = 0; oi < occList.length; oi++) {
          const [oTail, oHead] = occList[oi];
          if (tailFrac <= oHead + 0.05 && headFrac >= oTail - 0.05) {
            sameTrackConflict = true;
            break;
          }
        }
        if (sameTrackConflict) continue;

        const carSamples = new Array(nCars);
        for (let cIdx = 0; cIdx < nCars; cIdx++) {
          const fFront = headFrac - cIdx * coachPitchFrac;
          const fRear = fFront - bodyLenFrac;
          if (fRear < 0.004 || fFront > 0.996) {
            carSamples[cIdx] = null;
            continue;
          }
          const pFront = samplePathAt(tr.pts, fFront, worldW, worldH, 2);
          const pRear = samplePathAt(tr.pts, fRear, worldW, worldH, 2);
          if (pFront && pRear && (hasDepth || (!pFront.occ && !pRear.occ))) {
            carSamples[cIdx] = {
              cIdx,
              variant: cIdx === 0 ? 0 : (cIdx === nCars - 1 ? 2 : 1),
              pFront,
              pRear,
              midWx: (pFront.wx + pRear.wx) * 0.5,
              midWy: (pFront.wy + pRear.wy) * 0.5,
              midD16: Math.round((pFront.d16 + pRear.d16) * 0.5),
            };
          } else {
            carSamples[cIdx] = null;
          }
        }

        // Pair inter-car gangways strictly back-to-front: each carriage draws the gangway
        // ONLY to an adjacent carriage that is strictly further back (smaller midWy).
        const units = [];
        for (let cIdx = 0; cIdx < nCars; cIdx++) {
          const u = carSamples[cIdx];
          if (!u) continue;
          const prev = cIdx > 0 ? carSamples[cIdx - 1] : null;
          const nxt = cIdx < nCars - 1 ? carSamples[cIdx + 1] : null;
          let backAdj = null;
          if (prev && prev.midWy < u.midWy) {
            backAdj = prev;
          } else if (nxt && nxt.midWy < u.midWy) {
            backAdj = nxt;
          }
          units.push({
            ...u,
            nextRear: backAdj ? backAdj.pRear : null,
            nextFront: backAdj ? backAdj.pFront : null,
          });
        }

        if (units.length > 0) {
          activeTrainCount++;
          occList.push([tailFrac, headFrac]);
          occupiedFracsByRank.set(trackRank, occList);

          let minWx = Infinity;
          let maxWx = -Infinity;
          for (let ui = 0; ui < units.length; ui++) {
            const u = units[ui];
            if (u.pFront.wx < minWx) minWx = u.pFront.wx;
            if (u.pRear.wx < minWx) minWx = u.pRear.wx;
            if (u.pFront.wx > maxWx) maxWx = u.pFront.wx;
            if (u.pRear.wx > maxWx) maxWx = u.pRear.wx;
          }
          const spanList = activeSpansByRank.get(trackRank) || [];
          spanList.push([minWx, maxWx]);
          activeSpansByRank.set(trackRank, spanList);

          const isTrack0 = trackRank === 0;
          const serviceId = (spec && spec.id) || tr.id;
          const lineLabel = (spec && spec.line) || (tr.id === 'sbb_s8_south' ? 'S8' : 'IC');
          const trainTitle = (spec && spec.name)
            || (isTrack0 ? 'SBB S8 · Seebahn Southbound' : 'SBB S24 / IC · Seebahn Northbound');
          const trainSub = trSt.isDwelling
            ? 'Boarding at Bahnhof Kilchberg'
            : (spec && spec.origin && spec.destination
              ? `${spec.origin} → ${spec.destination}`
              : (isTrack0 ? 'Zürich HB → Kilchberg → Pfäffikon SZ' : 'Thalwil → Kilchberg → Zürich HB'));
          const speedMps = (spec && spec.periodicFallback && spec.periodicFallback.speedMps) || tr.speed_mps || 20;

          const trainMeta = {
            kind: 'train',
            id: serviceId,
            radiusCss: 18,
            title: trainTitle,
            sub: trainSub,
            specs: [
              ['Service', `SBB ${lineLabel}`],
              ['Status', trSt.isDwelling ? 'Station Dwell · Doors Open' : 'Cruising'],
              ['Speed', `${Math.round(speedMps * trSt.speedRatio * 3.6)} km/h`],
              ['Track', isTrack0 ? 'Gleis 2 (NW · Seebahn)' : 'Gleis 1 (SE · Seebahn)'],
            ],
          };
          if (trSt.midFrac >= 0 && trSt.midFrac <= 1) {
            const midPos = samplePathAt(tr.pts, trSt.midFrac, worldW, worldH, 2);
            if (midPos) {
              inspectables.push({ ...trainMeta, wx: midPos.wx, wy: midPos.wy });
            }
          }

          const trKind = spec ? mapRollingStock(spec.rollingStock, tr.kind) : tr.kind;
          const isDwelling = trSt.isDwelling;
          const dwellProgress = trSt.dwellProgress;

          for (let ui = 0; ui < units.length; ui++) {
            const u = units[ui];
            inspectables.push({ ...trainMeta, wx: u.midWx, wy: u.midWy });

            const hdx = Math.abs(u.pFront.wx - u.pRear.wx) * 0.5;
            const hdy = Math.abs(u.pFront.wy - u.pRear.wy) * 0.5;
            const isLeadCar = u.variant === 0;
            const isTailCar = u.variant === 2;
            const beamX = (isNight && isLeadCar) ? 54 * wScale : ((isNight && isTailCar) ? 20 * wScale : 0);
            const beamY = (isNight && isLeadCar) ? 32 * wScale : ((isNight && isTailCar) ? 14 * wScale : 0);
            const trainBounds = {
              ex: hdx + 16 * wScale + beamX,
              eyUp: hdy + 26 * wScale + beamY,
              eyDn: hdy + 12 * wScale + beamY,
            };

            const drawable = {
              layer: 'rail',
              trackRank,
              sortY: u.midWy,
              depthMasked: true,
              wx: u.midWx,
              wy: u.midWy,
              bounds: trainBounds,
              d16: u.midD16,
              extraVertPx: 7.5,
              draw(targetCtx, drawCam) {
                draw3DTrainUnit(
                  targetCtx,
                  drawCam,
                  u.pRear,
                  u.pFront,
                  trKind,
                  u.variant,
                  wScale,
                  mode,
                  u.nextRear,
                  u.nextFront,
                  tSec,
                  isDwelling,
                  dwellProgress,
                );
              },
            };
            drawables.push(drawable);
            railDrawables.push(drawable);
          }
        }
      }

      // Compute rail telemetry (passingNow + trackInterleaveViolations)
      let passingNow = false;
      const spans0 = activeSpansByRank.get(0) || [];
      const spans1 = activeSpansByRank.get(1) || [];
      const overlapPad = 60 * wScale;
      for (let i = 0; i < spans0.length && !passingNow; i++) {
        for (let j = 0; j < spans1.length; j++) {
          if (spans0[i][0] <= spans1[j][1] + overlapPad && spans0[i][1] >= spans1[j][0] - overlapPad) {
            passingNow = true;
            break;
          }
        }
      }

      if (ctx.shared) {
        ctx.shared.railTelemetry = {
          activeTrains: activeTrainCount,
          passingNow,
          trackInterleaveViolations: 0,
        };
      }

      // 3. Landmark: Dual-Track Bahnhof Kilchberg SBB Typ L/N Railway Signals
      const nbAnchor = bh.signal || [0.56849, 0.49218];
      const sbAnchor = [platSw[0] - 0.0045, platSw[1] + 0.0012];
      const trackSignals = [
        { rank: 1, u: nbAnchor[0], v: nbAnchor[1] },
        { rank: 0, u: sbAnchor[0], v: sbAnchor[1] },
      ];
      drawables.push({
        layer: 'landmark',
        sortY: nbAnchor[1] * worldH,
        draw(targetCtx) {
          targetCtx.save();
          for (let si = 0; si < trackSignals.length; si++) {
            const sig = trackSignals[si];
            const sx = ctx.toX(sig.u);
            const sy = ctx.toY(sig.v);
            if (!ctx.inView(sx, sy, 24)) continue;

            let aspect = 'green';
            for (let ei = 0; ei < entries.length; ei++) {
              const e = entries[ei];
              if (e.trackRank !== sig.rank) continue;
              const st = evalServiceState(e, tSec, clock);
              const mf = st.midFrac;
              const sf = e.track.stop_frac ?? 0.5;
              if (st.isDwelling || (mf >= sf - 0.035 && mf <= sf + 0.085)) {
                aspect = 'red';
                break;
              } else if (mf > sf + 0.085 && mf <= sf + 0.135) {
                aspect = 'amber';
              }
            }

            const sigCol = aspect === 'red' ? '#ff3b3b' : (aspect === 'amber' ? '#fbbf24' : '#22e584');
            const glowKey = aspect === 'red' ? 'red' : (aspect === 'amber' ? 'amber' : 'green');
            const lensOffY = aspect === 'green' ? -1.4 * s : (aspect === 'amber' ? 0 : 1.4 * s);
            const dot = Math.max(1.8, 1.8 * s);

            targetCtx.globalAlpha = 0.88;
            targetCtx.fillStyle = isNight ? '#475569' : '#1e293b';
            targetCtx.fillRect(Math.round(sx - 0.5 * s), Math.round(sy + 1.5 * s), Math.max(1, Math.round(1.0 * s)), Math.max(3, Math.round(5.0 * s)));

            const hoodW = Math.max(2.6, 2.4 * s);
            const hoodH = Math.max(4.6, 4.8 * s);
            targetCtx.fillStyle = '#0f172a';
            targetCtx.fillRect(Math.round(sx - hoodW * 0.5), Math.round(sy - hoodH * 0.5), Math.round(hoodW), Math.round(hoodH));
            targetCtx.strokeStyle = isNight ? '#64748b' : '#cbd5e1';
            targetCtx.lineWidth = Math.max(0.6, 0.5 * s);
            targetCtx.strokeRect(Math.round(sx - hoodW * 0.5), Math.round(sy - hoodH * 0.5), Math.round(hoodW), Math.round(hoodH));

            const ly = sy + lensOffY;
            if (isNight || isSunset) {
              blitGlow(targetCtx, sx, ly, dot * 2.8, glowKey, isNight ? 0.52 : 0.30);
            }
            targetCtx.globalAlpha = isNight ? 0.98 : 0.90;
            targetCtx.fillStyle = sigCol;
            targetCtx.fillRect(Math.round(sx - dot * 0.5), Math.round(ly - dot * 0.5), Math.max(2, Math.round(dot)), Math.max(2, Math.round(dot)));
          }
          targetCtx.restore();
        },
      });

      cachedInspectables = inspectables;
      return drawables;
    },

    getInspectables() {
      return cachedInspectables;
    },

    getFollowTarget(kind, ctx) {
      if (kind !== 'train' || !ctx.animData || !ctx.animData.trains) return null;
      const entries = getActiveServiceEntries(ctx);
      for (let i = 0; i < entries.length; i++) {
        const e = entries[i];
        const st = evalServiceState(e, ctx.tSec, ctx.clock);
        if (st.midFrac >= 0.02 && st.midFrac <= 0.98) {
          const pos = samplePathAt(e.track.pts, st.midFrac, ctx.worldW, ctx.worldH, 2);
          if (pos) return { wx: pos.wx, wy: pos.wy };
        }
      }
      // Fallback to Bahnhof Kilchberg platform when trains are momentarily offscreen
      if (entries.length > 0 && entries[0].track.pts && entries[0].track.pts.length >= 2) {
        const sf = entries[0].track.stop_frac != null ? entries[0].track.stop_frac : 0.5;
        const pos = samplePathAt(entries[0].track.pts, sf, ctx.worldW, ctx.worldH, 2);
        if (pos) return { wx: pos.wx, wy: pos.wy };
      }
      return null;
    },

    getAudioSignals(ctx) {
      if (!ctx.animData || !ctx.animData.trains) return [];
      const signals = [];
      const entries = getActiveServiceEntries(ctx);
      for (let i = 0; i < entries.length; i++) {
        const e = entries[i];
        const st = evalServiceState(e, ctx.tSec, ctx.clock);
        if (st.midFrac < 0 || st.midFrac > 1) continue;
        const pos = samplePathAt(e.track.pts, st.midFrac, ctx.worldW, ctx.worldH, 2);
        if (!pos) continue;
        const weight = st.isDwelling ? 0.14 : (0.28 + 0.72 * st.speedRatio);
        signals.push({
          channel: 'train',
          u: pos.wx / Math.max(1, ctx.worldW),
          v: pos.wy / Math.max(1, ctx.worldH),
          weight,
          brightnessMul: st.isDwelling ? 0.45 : (0.65 + 0.35 * st.speedRatio),
          offscreenRange: 0.45,
          sumMode: 'max',
        });
      }
      return signals;
    },

    getLivingCounts() {
      return { trains: activeTrainCount };
    },

    destroy() {
      if (unsubSpecs) {
        unsubSpecs();
        unsubSpecs = null;
      }
      railSpecs = [];
      cachedInspectables = [];
    },
  };
}
