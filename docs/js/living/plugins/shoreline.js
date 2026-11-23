/**
 * Lake Zurich Shoreline Waves, Sunlit Shallow-Water Caustics & Glints Plugin (Kilchberg v13.0).
 *
 * Layer: 'water_fx' (100% depthMgr.isWaterUV-strict, zero land bleed, zero per-frame array allocations).
 */

import { hashCoords } from '../../sim/rng.js';

const N_WAVE_SUB = 8;
const waveBufX = new Float64Array(N_WAVE_SUB + 1);
const waveBufY = new Float64Array(N_WAVE_SUB + 1);
const waveRunStart = new Int32Array(N_WAVE_SUB + 1);
const waveRunLen = new Int32Array(N_WAVE_SUB + 1);

function det01(a, b) {
  return hashCoords(a, b, 0x2c1b3c6d) / 4294967296;
}

function buildShoreStations(shoreline) {
  const n = shoreline.length;
  const smU = new Float64Array(n);
  const smV = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let su = 0;
    let sv = 0;
    let cnt = 0;
    for (let k = -3; k <= 3; k++) {
      const j = Math.max(0, Math.min(n - 1, i + k));
      su += shoreline[j][0];
      sv += shoreline[j][1];
      cnt++;
    }
    smU[i] = su / cnt;
    smV[i] = sv / cnt;
  }

  const stations = [];
  for (let i = 0; i < n - 1; i++) {
    const du = smU[i + 1] - smU[i];
    const dv = smV[i + 1] - smV[i];
    const segLen = Math.hypot(du, dv);
    if (segLen < 1e-5) continue;
    if (Math.abs(dv) > Math.abs(du) * 1.45) continue;
    const tx = du / segLen;
    const ty = dv / segLen;
    let nx = -ty;
    let ny = tx;
    if (ny < 0) {
      nx = -nx;
      ny = -ny;
    }
    nx = nx * 0.55 + 0.55 * 0.45;
    ny = ny * 0.55 + 0.83 * 0.45;
    const nm = Math.hypot(nx, ny) || 1;
    nx /= nm;
    ny /= nm;

    const subSteps = Math.max(1, Math.round(segLen / 0.0055));
    for (let st = 0; st < subSteps; st++) {
      const f = (st + 0.5) / subSteps;
      const idx = stations.length;
      const seed = ((idx * 2654435761) >>> 0) / 4294967296;
      stations.push({
        u: smU[i] + du * f,
        v: smV[i] + dv * f,
        tx,
        ty,
        nx,
        ny,
        seed,
      });
    }
  }
  return stations;
}

// Shallow-water sunlit caustic patches near Bendlikon Pier, Seebad & lakeside coves
const CAUSTIC_ZONES = [
  { u: 0.586, v: 0.585, ru: 0.028, rv: 0.018, count: 14 }, // Bendlikon Pier shallows
  { u: 0.428, v: 0.726, ru: 0.026, rv: 0.018, count: 14 }, // Seebad Kilchberg cove
  { u: 0.678, v: 0.525, ru: 0.024, rv: 0.016, count: 10 }, // Morfanlage / Sulzergut shallows
];

export function createShorelinePlugin() {
  let cachedLen = 0;
  let stations = [];

  return {
    id: 'shoreline',
    name: 'Lake Zurich Shoreline Waves, Caustics & Glints',
    category: 'water',
    layers: ['water_fx'],
    priority: 10,
    enabledByDefault: true,

    init(ctx) {
      const sh = ctx.animData && ctx.animData.ambient && ctx.animData.ambient.shoreline;
      if (sh && sh.length >= 4) {
        cachedLen = sh.length;
        stations = buildShoreStations(sh);
      } else {
        cachedLen = 0;
        stations = [];
      }
    },

    getDrawables(cam, ctx) {
      const sh = ctx.animData && ctx.animData.ambient && ctx.animData.ambient.shoreline;
      if (sh && sh.length >= 4 && sh.length !== cachedLen) {
        cachedLen = sh.length;
        stations = buildShoreStations(sh);
      }
      if (stations.length === 0) return [];

      const { worldW, worldH, wScale, tSec, isNight, isSunset, s, diurnal, depthMgr } = ctx;
      const { scale, offsetX, offsetY, width: canvasW, height: canvasH } = cam;
      const waterReady = !!(depthMgr && depthMgr.isWaterMaskReady && depthMgr.isWaterMaskReady());
      const checkWater = (u, v) => (!waterReady || depthMgr.isWaterUV(u, v));

      return [{
        layer: 'water_fx',
        sortY: 0,
        draw(targetCtx) {
          targetCtx.save();

          // 1. Sunlit Shallow-Water Caustics (day & sunset, strictly waterMask-guarded)
          if (!isNight && s >= 0.45 && diurnal.causticAlpha > 0.02) {
            const cRgb = isSunset ? '255, 224, 152' : '156, 246, 236';
            const cHiRgb = isSunset ? '255, 244, 206' : '226, 254, 255';
            targetCtx.lineWidth = Math.max(0.8, 0.9 * s);
            for (let zi = 0; zi < CAUSTIC_ZONES.length; zi++) {
              const z = CAUSTIC_ZONES[zi];
              if (!ctx.boxInView(z.u - z.ru, z.v - z.rv, z.u + z.ru, z.v + z.rv)) continue;
              for (let ci = 0; ci < z.count; ci++) {
                const r0 = det01(zi * 31 + ci, 11);
                const r1 = det01(zi * 31 + ci, 23);
                const r2 = det01(zi * 31 + ci, 37);
                const driftU = Math.sin(tSec * (0.65 + r2 * 0.5) + ci * 1.7 + zi) * 0.0018;
                const driftV = Math.cos(tSec * (0.55 + r0 * 0.4) + ci * 2.3) * 0.0012;
                const cu = z.u + (r0 - 0.5) * 2 * z.ru + driftU;
                const cv = z.v + (r1 - 0.5) * 2 * z.rv + driftV;
                if (!checkWater(cu, cv)) continue;
                const sx = ctx.toX(cu);
                const sy = ctx.toY(cv);
                if (!ctx.inView(sx, sy, 24)) continue;

                const shimmer = 0.35 + 0.65 * Math.pow(0.5 + 0.5 * Math.sin(tSec * (1.8 + r2 * 1.4) + ci * 2.1), 2.0);
                const alpha = diurnal.causticAlpha * shimmer;
                const rx = (2.8 + r2 * 3.4) * s;
                const ry = rx * 0.46;

                targetCtx.strokeStyle = `rgba(${cRgb}, ${(alpha * 0.72).toFixed(2)})`;
                targetCtx.beginPath();
                targetCtx.moveTo(sx - rx, sy);
                targetCtx.lineTo(sx, sy - ry);
                targetCtx.lineTo(sx + rx, sy);
                targetCtx.lineTo(sx, sy + ry);
                targetCtx.closePath();
                targetCtx.stroke();

                if (shimmer > 0.72) {
                  const dot = Math.max(1.2, 1.35 * s);
                  targetCtx.fillStyle = `rgba(${cHiRgb}, ${(alpha * 0.85).toFixed(2)})`;
                  targetCtx.fillRect(Math.round(sx - dot * 0.5), Math.round(sy - dot * 0.5), Math.round(dot), Math.max(1, Math.round(dot * 0.7)));
                }
              }
            }
          }

          // 2. Organic Shoreline Waves rolling inward toward the Kilchberg shore (zero per-frame allocs)
          const troughCol = isNight
            ? 'rgba(8, 22, 48, 0.30)'
            : (isSunset ? 'rgba(38, 30, 56, 0.24)' : 'rgba(12, 58, 78, 0.24)');
          const swellCol = isNight
            ? 'rgba(124, 170, 226, 0.44)'
            : (isSunset ? 'rgba(255, 198, 134, 0.48)' : 'rgba(176, 232, 240, 0.50)');
          const foamCol = isNight
            ? 'rgba(198, 226, 255, 0.66)'
            : (isSunset ? 'rgba(255, 234, 188, 0.72)' : 'rgba(242, 253, 255, 0.78)');

          const cycleSec = 5.6;
          const nWaves = 3;
          const maxDistWorld = 48.0 * wScale;
          const minDistWorld = 4.0 * wScale;

          targetCtx.lineCap = 'round';
          for (let i = 0; i < stations.length; i++) {
            const st = stations[i];
            const baseSx = offsetX + st.u * worldW * scale;
            const baseSy = offsetY + st.v * worldH * scale;
            if (baseSx < -90 || baseSx > canvasW + 90 || baseSy < -90 || baseSy > canvasH + 90) continue;

            const tanX = st.tx * worldW;
            const tanY = st.ty * worldH;
            const tanM = Math.hypot(tanX, tanY) || 1;
            const ux = tanX / tanM;
            const uy = tanY / tanM;

            for (let w = 0; w < nWaves; w++) {
              const phaseOff = (w / nWaves) + Math.sin(i * 0.42 + w * 1.9) * 0.08 + (st.seed - 0.5) * 0.07;
              const p = (((tSec / cycleSec) + phaseOff) % 1 + 1) % 1;
              const alpha = p < 0.20 ? (p / 0.20) : (p > 0.80 ? ((1.0 - p) / 0.20) : 1.0);
              if (alpha <= 0.05) continue;

              const eased = 1.0 - Math.pow(1.0 - p, 1.35);
              const dist = maxDistWorld * (1.0 - eased) + minDistWorld * eased;
              const wx = st.u * worldW + st.nx * dist;
              const wy = st.v * worldH + st.ny * dist;

              const isBreaking = p > 0.66;
              const halfLenW = (15.0 + st.seed * 12.0) * (0.65 + 0.35 * Math.sin(p * Math.PI)) * wScale;
              const bowW = -2.2 * wScale;
              const wx0 = wx - ux * halfLenW;
              const wy0 = wy - uy * halfLenW;
              const wx1 = wx + ux * halfLenW;
              const wy1 = wy + uy * halfLenW;
              const wcx = wx + st.nx * bowW;
              const wcy = wy + st.ny * bowW;

              let runCount = 0;
              let curStart = 0;
              let curLen = 0;
              for (let k = 0; k <= N_WAVE_SUB; k++) {
                const t = k / N_WAVE_SUB;
                const omt = 1 - t;
                const pwx = omt * omt * wx0 + 2 * omt * t * wcx + t * t * wx1;
                const pwy = omt * omt * wy0 + 2 * omt * t * wcy + t * t * wy1;
                if (checkWater(pwx / worldW, pwy / worldH)) {
                  if (curLen === 0) curStart = k;
                  waveBufX[k] = offsetX + pwx * scale;
                  waveBufY[k] = offsetY + pwy * scale;
                  curLen++;
                } else {
                  if (curLen >= 2) {
                    waveRunStart[runCount] = curStart;
                    waveRunLen[runCount] = curLen;
                    runCount++;
                  }
                  curLen = 0;
                }
              }
              if (curLen >= 2) {
                waveRunStart[runCount] = curStart;
                waveRunLen[runCount] = curLen;
                runCount++;
              }
              if (runCount === 0) continue;

              const shX = st.nx * 2.1 * s;
              const shY = st.ny * 2.1 * s;
              for (let ri = 0; ri < runCount; ri++) {
                const rStart = waveRunStart[ri];
                const rLen = waveRunLen[ri];
                targetCtx.globalAlpha = alpha * 0.65;
                targetCtx.strokeStyle = troughCol;
                targetCtx.lineWidth = Math.max(1.1, 1.8 * s);
                targetCtx.beginPath();
                for (let k = 0; k < rLen; k++) {
                  const idx = rStart + k;
                  if (k === 0) targetCtx.moveTo(waveBufX[idx] + shX, waveBufY[idx] + shY);
                  else targetCtx.lineTo(waveBufX[idx] + shX, waveBufY[idx] + shY);
                }
                targetCtx.stroke();

                targetCtx.globalAlpha = alpha * (isBreaking ? 0.88 : 0.68);
                targetCtx.strokeStyle = isBreaking ? foamCol : swellCol;
                targetCtx.lineWidth = Math.max(1.0, (isBreaking ? 1.9 : 1.35) * s);
                targetCtx.beginPath();
                for (let k = 0; k < rLen; k++) {
                  const idx = rStart + k;
                  if (k === 0) targetCtx.moveTo(waveBufX[idx], waveBufY[idx]);
                  else targetCtx.lineTo(waveBufX[idx], waveBufY[idx]);
                }
                targetCtx.stroke();

                if (isBreaking && alpha > 0.35 && rLen >= 3) {
                  const midIdx = rStart + Math.floor(rLen / 2);
                  const pxSz = Math.max(1.2, 1.5 * s);
                  targetCtx.globalAlpha = alpha * 0.9;
                  targetCtx.fillStyle = foamCol;
                  targetCtx.fillRect(
                    Math.round(waveBufX[midIdx] - pxSz * 1.4),
                    Math.round(waveBufY[midIdx] - pxSz * 0.5),
                    Math.round(pxSz * 2.8),
                    Math.max(1, Math.round(pxSz)),
                  );
                }
              }
            }
          }

          // 3. Sparkling Open-Lake Solar Glints (waterMask-strict)
          if (waterReady) {
            const glintCol = isNight ? '#cddcf4' : (isSunset ? '#ffe2a8' : '#f4fbff');
            const px = Math.max(1.2, 1.5 * s);
            targetCtx.fillStyle = glintCol;
            for (let i = 0; i < 96; i++) {
              const gu = 0.42 + det01(i, 101) * 0.56;
              const gv = 0.34 + det01(i, 202) * 0.62;
              if (!depthMgr.isWaterUV(gu, gv)) continue;
              const sx = ctx.toX(gu);
              const sy = ctx.toY(gv);
              if (sx < -8 || sx > canvasW + 8 || sy < -8 || sy > canvasH + 8) continue;
              const pulse = Math.sin(tSec * (1.8 + det01(i, 303) * 2.2) + i * 2.41);
              if (pulse < 0.52) continue;
              targetCtx.globalAlpha = ((pulse - 0.52) / 0.48) * diurnal.waterGlintAlpha;
              const rx = Math.round(sx);
              const ry = Math.round(sy);
              targetCtx.fillRect(rx - Math.round(px), ry, Math.max(2, Math.round(px * 2.4)), Math.max(1, Math.round(px * 0.75)));
              if (pulse > 0.82) {
                targetCtx.fillRect(rx, ry - Math.round(px * 0.6), Math.max(1, Math.round(px * 0.8)), Math.max(2, Math.round(px * 2.0)));
              }
            }

            // 4. Nighttime Moonlit Water Shimmer Band
            if (isNight) {
              for (let i = 0; i < 32; i++) {
                const f = i / 31;
                const spread = (det01(i, 404) - 0.5) * 0.042;
                const mu = 0.74 - f * 0.18 + spread + Math.sin(tSec * 1.4 + i * 1.7) * 0.0025;
                const mv = 0.54 + f * 0.24 + (det01(i, 505) - 0.5) * 0.012;
                if (!depthMgr.isWaterUV(mu, mv)) continue;
                const sx = ctx.toX(mu);
                const sy = ctx.toY(mv);
                if (sx < -24 || sx > canvasW + 24 || sy < -10 || sy > canvasH + 10) continue;
                const pulse = 0.35 + 0.65 * Math.pow(0.5 + 0.5 * Math.sin(tSec * 2.1 + i * 2.3), 2.0);
                const wPx = Math.max(3, Math.round((5.5 + det01(i, 606) * 7.0) * s));
                const hPx = Math.max(1, Math.round(1.3 * s));
                targetCtx.globalAlpha = pulse * 0.54;
                targetCtx.fillStyle = (i % 3 === 0) ? '#dbeafe' : '#93c5fd';
                targetCtx.fillRect(Math.round(sx - wPx * 0.5), Math.round(sy), wPx, hPx);
              }
            }
          }

          targetCtx.restore();
        },
      }];
    },

    getAudioSignals(ctx) {
      if (stations.length === 0) return [];
      const signals = [];
      const step = Math.max(1, Math.floor(stations.length / 8));
      for (let i = 0; i < stations.length; i += step) {
        const st = stations[i];
        signals.push({
          channel: 'lake_waves',
          u: st.u,
          v: st.v,
          weight: ctx.isNight ? 0.55 : 0.85,
          brightnessMul: ctx.isNight ? 0.65 : 0.90,
          offscreenRange: 0.18,
          sumMode: 'max',
        });
      }
      return signals;
    },
  };
}
