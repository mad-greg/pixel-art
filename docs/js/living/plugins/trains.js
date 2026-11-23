/**
 * Trains & SBB Seebahn Rail Plugin (Kilchberg v13.0).
 *
 * Layers:
 *   - 'pre_rail': Bahnhof Kilchberg NW platform departure board & SBB Mondaine clocks
 *                 (strictly drawn BEFORE trains so passing trains naturally occlude them)
 *   - 'rail':     SBB S8/S24 KISS/DPZ & IC multi-carriage trains (extraVertPx = 7.5, opaque roofs!)
 *   - 'landmark': Dual-track SBB Typ L/N railway signals reacting to train proximity
 */

import { evalTrainState, samplePathAt } from '../../sim/schedule.js';
import { draw3DTrainUnit } from '../../render/vehicles.js';
import { blitGlow, drawSwissClockDial } from '../draw.js';

export function createTrainsPlugin() {
  let activeTrainCount = 0;
  let cachedInspectables = [];

  return {
    id: 'trains',
    name: 'SBB Seebahn Trains & Signals',
    category: 'transit',
    layers: ['pre_rail', 'rail', 'landmark'],
    priority: 40,
    enabledByDefault: true,

    init() {
      activeTrainCount = 0;
      cachedInspectables = [];
    },

    getDrawables(cam, ctx) {
      const animData = ctx.animData;
      if (!animData) return [];

      const drawables = [];
      const inspectables = [];
      activeTrainCount = 0;

      const { worldW, worldH, wScale, tSec, mode, isNight, isSunset, s, detailAlpha, depthMgr } = ctx;
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
              drawSwissClockDial(targetCtx, ckX, by, 2.6 * s, tSec, { mode, style: 'sbb', s, detailAlpha });
            }
            if (detailAlpha > 0.01) {
              const scX = ctx.toX(0.5772);
              const scY = ctx.toY(0.4902);
              if (ctx.inView(scX, scY, 20)) {
                drawSwissClockDial(targetCtx, scX, scY, 3.6 * s, tSec, { mode, style: 'sbb', s, detailAlpha });
              }
            }
            targetCtx.restore();
          },
        });
      }

      // 2. Rail: SBB Seebahn multi-carriage trains (extraVertPx = 7.5 strict!)
      const trains = animData.trains || [];
      for (let ti = 0; ti < trains.length; ti++) {
        const tr = trains[ti];
        const trSt = evalTrainState(tr, tSec);
        const headFrac = trSt.headFrac;
        if (headFrac < 0 || headFrac > 1.12) continue;

        const coachPitchFrac = 19.5 / tr.length_m;
        const bodyLenFrac = 18.1 / tr.length_m;
        const nCars = tr.carriages || 4;
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

        const units = [];
        for (let cIdx = 0; cIdx < nCars; cIdx++) {
          const u = carSamples[cIdx];
          if (!u) continue;
          const nxt = (cIdx < nCars - 1) ? carSamples[cIdx + 1] : null;
          units.push({
            ...u,
            nextRear: nxt ? nxt.pRear : null,
            nextFront: nxt ? nxt.pFront : null,
          });
        }

        if (units.length > 0) {
          activeTrainCount++;
          const isS8 = tr.id === 'sbb_s8_south';
          const trainMeta = {
            kind: 'train',
            id: tr.id,
            radiusCss: 18,
            title: isS8 ? 'SBB S8 · Seebahn Southbound' : 'SBB S24 / IC · Seebahn Northbound',
            sub: trSt.isDwelling
              ? 'Boarding at Bahnhof Kilchberg'
              : (isS8 ? 'Zürich HB → Kilchberg → Pfäffikon SZ' : 'Thalwil → Kilchberg → Zürich HB'),
            specs: [
              ['Service', isS8 ? 'SBB S8 Double-Decker' : 'SBB S24 / IC'],
              ['Status', trSt.isDwelling ? 'Station Dwell · Doors Open' : 'Cruising'],
              ['Speed', `${Math.round((tr.speed_mps || 20) * trSt.speedRatio * 3.6)} km/h`],
              ['Track', isS8 ? 'Gleis 2 (Seebahn)' : 'Gleis 1 (Seebahn)'],
            ],
          };
          if (trSt.midFrac >= 0 && trSt.midFrac <= 1) {
            const midPos = samplePathAt(tr.pts, trSt.midFrac, worldW, worldH, 2);
            if (midPos) {
              inspectables.push({ ...trainMeta, wx: midPos.wx, wy: midPos.wy });
            }
          }
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
            const trKind = tr.kind;
            const isDwelling = trSt.isDwelling;
            const dwellProgress = trSt.dwellProgress;

            drawables.push({
              layer: 'rail',
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
            });
          }
        }
      }

      // 3. Landmark: Dual-Track Bahnhof Kilchberg SBB Typ L/N Railway Signals
      const nbAnchor = bh.signal || [0.56849, 0.49218];
      const sbAnchor = [platSw[0] - 0.0045, platSw[1] + 0.0012];
      const trackSignals = [
        { trId: 'sbb_ic_north', u: nbAnchor[0], v: nbAnchor[1] },
        { trId: 'sbb_s8_south', u: sbAnchor[0], v: sbAnchor[1] },
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

            const tr = trains.find((t) => t.id === sig.trId);
            let aspect = 'green';
            if (tr) {
              const st = evalTrainState(tr, tSec);
              const mf = st.midFrac;
              if (st.isDwelling || (mf >= tr.stop_frac - 0.035 && mf <= tr.stop_frac + 0.085)) {
                aspect = 'red';
              } else if (mf > tr.stop_frac + 0.085 && mf <= tr.stop_frac + 0.135) {
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
      const trains = ctx.animData.trains;
      for (let i = 0; i < trains.length; i++) {
        const tr = trains[i];
        const st = evalTrainState(tr, ctx.tSec);
        if (st.midFrac >= 0.02 && st.midFrac <= 0.98) {
          const pos = samplePathAt(tr.pts, st.midFrac, ctx.worldW, ctx.worldH, 2);
          if (pos) return { wx: pos.wx, wy: pos.wy };
        }
      }
      // Fallback to Bahnhof Kilchberg platform when trains are momentarily offscreen
      if (trains.length > 0 && trains[0].pts && trains[0].pts.length >= 2) {
        const sf = trains[0].stop_frac != null ? trains[0].stop_frac : 0.5;
        const pos = samplePathAt(trains[0].pts, sf, ctx.worldW, ctx.worldH, 2);
        if (pos) return { wx: pos.wx, wy: pos.wy };
      }
      return null;
    },

    getAudioSignals(ctx) {
      if (!ctx.animData || !ctx.animData.trains) return [];
      const signals = [];
      const trains = ctx.animData.trains;
      for (let i = 0; i < trains.length; i++) {
        const tr = trains[i];
        const st = evalTrainState(tr, ctx.tSec);
        if (st.midFrac < 0 || st.midFrac > 1) continue;
        const pos = samplePathAt(tr.pts, st.midFrac, ctx.worldW, ctx.worldH, 2);
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
  };
}
