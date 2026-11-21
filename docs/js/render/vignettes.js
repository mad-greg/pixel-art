/**
 * Kilchberg living-world vignettes, sports fields, Lake Zurich micro-life,
 * wind-coherent village atmosphere, dusk/night residential living windows,
 * and canonically synced church bell acoustic ripples.
 *
 * Deterministic (zero Math.random()), waterMask-safe, and depth-masked.
 */

import { hashCoords } from '../sim/rng.js';
import {
  evalBellState,
  evalTrainState,
  evalWithStationStop,
  getWindVector,
  samplePathAt,
} from '../sim/schedule.js';
import { drawPixelRectWorld, shadeHex } from './vehicles.js';

// Deterministic pseudo-random helper for sparkling lake glints & fireflies
function hash01(n) {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

// Precomputed park/meadow anchors for nighttime fireflies (real Kilchberg parks & lake meadows)
const FIREFLY_GROVES = [
  [0.24, 0.42], [0.27, 0.34], [0.33, 0.48], [0.39, 0.65],
  [0.44, 0.63], [0.51, 0.56], [0.56, 0.53], [0.64, 0.49],
  [0.71, 0.43], [0.77, 0.37], [0.47, 0.41], [0.35, 0.32],
];

// Exact isometric ground-to-UV projection (azimuth=102 deg, pitch=30 deg, 0.25 m/px on 12331x5444)
const E_TO_U = 0.0000674436;
const N_TO_U = 0.0003172971;
const E_TO_V = 0.0003593489;
const N_TO_V = -0.0000763820;

function fieldAxesUV(field) {
  const ca = Math.cos(field.angle || 0);
  const sa = Math.sin(field.angle || 0);
  const hl = 0.5 * (field.h_m || 30) * 0.84;
  const hw = 0.5 * (field.w_m || 15) * 0.80;
  return {
    halfL: [hl * ca * E_TO_U + hl * sa * N_TO_U, hl * ca * E_TO_V + hl * sa * N_TO_V],
    halfW: [-hw * sa * E_TO_U + hw * ca * N_TO_U, -hw * sa * E_TO_V + hw * ca * N_TO_V],
  };
}

// Cached shoreline wave emitters & streetlamp roads & residential living-window anchors
let cachedShoreStations = null;
let cachedLampRoadsSrc = null;
let cachedLampRoads = null;
let cachedWindowSrc = null;
let cachedLivingWindows = null;

function getLivingWindows(interactiveData) {
  if (!interactiveData || !Array.isArray(interactiveData.buildings)) return [];
  if (cachedWindowSrc === interactiveData && cachedLivingWindows) return cachedLivingWindows;

  const palette = ['#ffd88a', '#ffca72', '#ffe6b3', '#ffd27d', '#ffde99', '#c8dcf8'];
  const list = [];
  for (let i = 0; i < interactiveData.buildings.length; i++) {
    const b = interactiveData.buildings[i];
    if (!b || b.type !== 'Gebaeude Einzelhaus' || (b.h || 0) < 5.0) continue;
    const h0 = hashCoords(b.id || i, 17, 0x51a7);
    if ((h0 % 8) !== 0) continue;

    const nWins = ((h0 >>> 3) % 3 === 0) ? 2 : 1;
    for (let w = 0; w < nWins; w++) {
      const hw = hashCoords(b.id || i, 41 + w * 13, 0x9e37);
      const uNorm = (hw & 0xff) / 255;
      const vNorm = ((hw >>> 8) & 0xff) / 255;
      const pNorm = ((hw >>> 16) & 0xff) / 255;
      const cIdx = ((hw >>> 24) & 0xff) % palette.length;
      const du = (uNorm - 0.5) * 0.00066 + (w === 1 ? 0.00020 : -0.00008);
      const dv = 0.00016 + vNorm * 0.00038;
      list.push({
        u: b.u + du,
        v: b.v + dv,
        col: palette[cIdx],
        period: 48.0 + pNorm * 64.0,
        phase: (uNorm * 6.28318) + w * 1.9,
        sunsetBias: vNorm,
      });
    }
  }
  cachedWindowSrc = interactiveData;
  cachedLivingWindows = list;
  return list;
}

/**
 * Crisp 90s pixel-grid miniature villager/visitor/commuter sprite (accepts targetCtx for depth masking).
 */
export function drawMiniPerson(
  targetCtx,
  sx,
  sy,
  s,
  coatCol,
  pantsCol,
  hairCol,
  isNight,
  stridePhase,
  bagCol = null,
  canvasW = 4096,
  canvasH = 4096,
) {
  const p = Math.max(0.75, s);
  const pad = 16 * p;
  if (sx < -pad || sx > canvasW + pad || sy < -pad || sy > canvasH + pad) return;
  const rx = Math.round(sx);
  const ry = Math.round(sy);
  const step = Math.round(Math.sin(stridePhase) * 0.85 * p);
  targetCtx.fillStyle = isNight ? 'rgba(6,10,20,0.48)' : 'rgba(18,24,32,0.30)';
  targetCtx.fillRect(rx - Math.round(1.4 * p), ry, Math.max(2, Math.round(3.0 * p)), Math.max(1, Math.round(1.1 * p)));
  targetCtx.fillStyle = pantsCol;
  targetCtx.fillRect(rx - Math.round(0.8 * p) + step, ry - Math.round(2.2 * p), Math.max(1, Math.round(0.95 * p)), Math.max(1, Math.round(2.2 * p)));
  targetCtx.fillRect(rx + Math.round(0.1 * p) - step, ry - Math.round(2.2 * p), Math.max(1, Math.round(0.95 * p)), Math.max(1, Math.round(2.2 * p)));
  targetCtx.fillStyle = coatCol;
  targetCtx.fillRect(rx - Math.round(1.0 * p), ry - Math.round(4.6 * p), Math.max(2, Math.round(2.1 * p)), Math.max(2, Math.round(2.5 * p)));
  if (bagCol) {
    targetCtx.fillStyle = bagCol;
    targetCtx.fillRect(rx + Math.round(1.0 * p), ry - Math.round(3.2 * p), Math.max(1, Math.round(1.1 * p)), Math.max(1, Math.round(1.5 * p)));
  }
  targetCtx.fillStyle = isNight ? '#a88c72' : '#ecc29c';
  targetCtx.fillRect(rx - Math.round(0.7 * p), ry - Math.round(5.9 * p), Math.max(1, Math.round(1.4 * p)), Math.max(1, Math.round(1.3 * p)));
  targetCtx.fillStyle = hairCol;
  targetCtx.fillRect(rx - Math.round(0.75 * p), ry - Math.round(6.4 * p), Math.max(1, Math.round(1.5 * p)), Math.max(1, Math.round(0.75 * p)));
}

/**
 * Organic 90s pixel-art shoreline wave arcs rolling inward toward the Kilchberg shore,
 * clipped cleanly against depthMgr.isWaterUV.
 */
export function drawShorelineWaves(ctx, cam, depthMgr, shoreline, worldW, worldH, wScale, tSec, mode) {
  if (!shoreline || shoreline.length < 4) return;

  const { scale, offsetX, offsetY, width: canvasW, height: canvasH } = cam;
  const isNight = mode === 'night';
  const isSunset = mode === 'sunset';
  const s = scale * wScale;

  if (!cachedShoreStations || cachedShoreStations.len !== shoreline.length) {
    const sm = shoreline.map((p, i) => {
      let su = 0; let sv = 0; let cnt = 0;
      for (let k = -3; k <= 3; k++) {
        const j = Math.max(0, Math.min(shoreline.length - 1, i + k));
        su += shoreline[j][0];
        sv += shoreline[j][1];
        cnt++;
      }
      return [su / cnt, sv / cnt];
    });
    const stations = [];
    for (let i = 0; i < sm.length - 1; i++) {
      const a = sm[i];
      const b = sm[i + 1];
      const du = b[0] - a[0];
      const dv = b[1] - a[1];
      const segLen = Math.hypot(du, dv);
      if (segLen < 1e-5) continue;
      if (Math.abs(dv) > Math.abs(du) * 1.45) continue;
      const tx = du / segLen;
      const ty = dv / segLen;
      let nx = -ty;
      let ny = tx;
      if (ny < 0) { nx = -nx; ny = -ny; }
      nx = nx * 0.55 + 0.55 * 0.45;
      ny = ny * 0.55 + 0.83 * 0.45;
      const nm = Math.hypot(nx, ny) || 1;
      nx /= nm; ny /= nm;
      const subSteps = Math.max(1, Math.round(segLen / 0.0055));
      for (let st = 0; st < subSteps; st++) {
        const f = (st + 0.5) / subSteps;
        const idx = stations.length;
        const seed = ((idx * 2654435761) >>> 0) / 4294967296;
        stations.push({
          u: a[0] + du * f,
          v: a[1] + dv * f,
          tx,
          ty,
          nx,
          ny,
          seed,
        });
      }
    }
    cachedShoreStations = { len: shoreline.length, list: stations };
  }
  const stations = cachedShoreStations.list;

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

  ctx.save();
  ctx.lineCap = 'round';

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

      const subRuns = [];
      let curRun = [];
      const N_SUB = 8;
      for (let k = 0; k <= N_SUB; k++) {
        const t = k / N_SUB;
        const omt = 1 - t;
        const pwx = omt * omt * wx0 + 2 * omt * t * wcx + t * t * wx1;
        const pwy = omt * omt * wy0 + 2 * omt * t * wcy + t * t * wy1;
        const ok = depthMgr.isWaterMaskReady()
          ? depthMgr.isWaterUV(pwx / worldW, pwy / worldH)
          : true;
        if (ok) {
          curRun.push([offsetX + pwx * scale, offsetY + pwy * scale]);
        } else {
          if (curRun.length >= 2) subRuns.push(curRun);
          curRun = [];
        }
      }
      if (curRun.length >= 2) subRuns.push(curRun);
      if (subRuns.length === 0) continue;

      const shX = st.nx * 2.1 * s;
      const shY = st.ny * 2.1 * s;
      for (const run of subRuns) {
        ctx.globalAlpha = alpha * 0.65;
        ctx.strokeStyle = troughCol;
        ctx.lineWidth = Math.max(1.1, 1.8 * s);
        ctx.beginPath();
        for (let k = 0; k < run.length; k++) {
          if (k === 0) ctx.moveTo(run[k][0] + shX, run[k][1] + shY);
          else ctx.lineTo(run[k][0] + shX, run[k][1] + shY);
        }
        ctx.stroke();

        ctx.globalAlpha = alpha * (isBreaking ? 0.88 : 0.68);
        ctx.strokeStyle = isBreaking ? foamCol : swellCol;
        ctx.lineWidth = Math.max(1.0, (isBreaking ? 1.9 : 1.35) * s);
        ctx.beginPath();
        for (let k = 0; k < run.length; k++) {
          if (k === 0) ctx.moveTo(run[k][0], run[k][1]);
          else ctx.lineTo(run[k][0], run[k][1]);
        }
        ctx.stroke();

        if (isBreaking && alpha > 0.35 && run.length >= 3) {
          const mid = run[Math.floor(run.length / 2)];
          const pxSz = Math.max(1.2, 1.5 * s);
          ctx.globalAlpha = alpha * 0.9;
          ctx.fillStyle = foamCol;
          ctx.fillRect(Math.round(mid[0] - pxSz * 1.4), Math.round(mid[1] - pxSz * 0.5), Math.round(pxSz * 2.8), Math.max(1, Math.round(pxSz)));
        }
      }
    }
  }
  ctx.restore();
}

/**
 * Ambient village effects: Swiss & Kilchberg waving flags, Lindt Hochkamin steam,
 * village chimney smoke (SW->NE wind-coherent), Dorfbrunnen fountains, and Lake Zurich gulls.
 */
export function drawAmbientEffects(ctx, cam, animData, livingCounts, worldW, worldH, wScale, tSec, mode) {
  if (!animData || !animData.ambient) return;

  const { scale, offsetX, offsetY, width: canvasW, height: canvasH } = cam;
  const isNight = mode === 'night';
  const isSunset = mode === 'sunset';
  const wind = getWindVector(tSec);
  const waveStep = Math.floor(wind.wavePhase) % 4;
  const billow = Math.min(1.25, Math.max(0.75, wind.strength * 1.3));

  for (let fIdx = 0; fIdx < (animData.ambient.swiss_flags || []).length; fIdx++) {
    const fl = animData.ambient.swiss_flags[fIdx];
    const fx = fl.uv[0] * worldW;
    const fy = fl.uv[1] * worldH;
    const fPhase = (waveStep + fIdx) % 4;
    drawPixelRectWorld(ctx, cam, fx, fy - 15 * wScale, 1.5, 16, isNight ? '#8a99b2' : '#d8dce2', wScale);
    drawPixelRectWorld(ctx, cam, fx - 0.3 * wScale, fy - 16 * wScale, 2.1, 1.6, isNight ? '#c8a852' : '#f2ca52', wScale);
    const segY0 = fy - 14.5 * wScale;
    const dy1 = (fPhase === 1 ? -1 : (fPhase === 3 ? 1 : 0)) * billow * wScale;
    const dy2 = (fPhase === 2 ? -1 : (fPhase === 0 ? 1 : 0)) * billow * wScale;
    const redFlag = isNight ? '#9e2828' : '#d62c28';
    const whiteCross = isNight ? '#cfd6e2' : '#f8f6f0';
    drawPixelRectWorld(ctx, cam, fx + 1.5 * wScale, segY0, 3, 6, redFlag, wScale);
    drawPixelRectWorld(ctx, cam, fx + 4.2 * wScale, segY0 + dy1, 3.2, 6, redFlag, wScale);
    drawPixelRectWorld(ctx, cam, fx + 7.2 * wScale, segY0 + dy2, 2.8, 6, redFlag, wScale);
    drawPixelRectWorld(ctx, cam, fx + 4.6 * wScale, segY0 + dy1 + 1.2 * wScale, 1.4, 3.6, whiteCross, wScale);
    drawPixelRectWorld(ctx, cam, fx + 3.4 * wScale, segY0 + dy1 + 2.3 * wScale, 3.8, 1.4, whiteCross, wScale);

    if (fIdx === 3) {
      const kx = fx + 13 * wScale;
      const ky = fy + 2 * wScale;
      const kPhase = (waveStep + 2) % 4;
      const kdy1 = (kPhase === 1 ? -1 : (kPhase === 3 ? 1 : 0)) * billow * wScale;
      const kdy2 = (kPhase === 2 ? -1 : (kPhase === 0 ? 1 : 0)) * billow * wScale;
      drawPixelRectWorld(ctx, cam, kx, ky - 14 * wScale, 1.5, 15, isNight ? '#8a99b2' : '#d8dce2', wScale);
      const kTop = isNight ? '#9c2c2c' : '#cc2e2a';
      const kGold = isNight ? '#b59238' : '#e8be42';
      drawPixelRectWorld(ctx, cam, kx + 1.5 * wScale, ky - 14 * wScale, 3, 3.4, kTop, wScale);
      drawPixelRectWorld(ctx, cam, kx + 4.2 * wScale, ky - 14 * wScale + kdy1, 3.2, 3.4, kTop, wScale);
      drawPixelRectWorld(ctx, cam, kx + 7.2 * wScale, ky - 14 * wScale + kdy2, 2.8, 3.4, kTop, wScale);
      drawPixelRectWorld(ctx, cam, kx + 1.5 * wScale, ky - 10.6 * wScale, 3, 2.6, kGold, wScale);
      drawPixelRectWorld(ctx, cam, kx + 4.2 * wScale, ky - 10.6 * wScale + kdy1, 3.2, 2.6, kGold, wScale);
      drawPixelRectWorld(ctx, cam, kx + 7.2 * wScale, ky - 10.6 * wScale + kdy2, 2.8, 2.6, kGold, wScale);
      drawPixelRectWorld(ctx, cam, kx + 4.8 * wScale, ky - 13.4 * wScale + kdy1, 1.6, 3.8, whiteCross, wScale);
    }
  }

  // Lindt Hochkamin steam plume drifting along unified SW->NE breeze
  if (animData.ambient.chimney_steam) {
    const stUv = animData.ambient.chimney_steam.uv;
    const cxWorld = stUv[0] * worldW;
    const cyWorld = stUv[1] * worldH;
    for (let p = 0; p < 10; p++) {
      const age = (((tSec * 0.28 + p / 10) % 1) + 1) % 1;
      const driftX = age * 34 * wind.wx * wScale + Math.sin(age * 6.5 + p * 1.4) * 2.6 * wScale;
      const riseY = -(3 + age * 44) * wScale + age * 10 * wind.wy * wScale;
      const pxWorld = Math.round(cxWorld + driftX);
      const pyWorld = Math.round(cyWorld + riseY);
      const alpha = (1 - age) * (age < 0.12 ? age / 0.12 : 0.72);
      const sz = 2.6 + age * 7.8;
      const shadeCol = isNight
        ? `rgba(110,126,158,${(alpha * 0.48).toFixed(2)})`
        : (isSunset ? `rgba(218,174,162,${(alpha * 0.62).toFixed(2)})` : `rgba(204,210,220,${(alpha * 0.60).toFixed(2)})`);
      const litCol = isNight
        ? `rgba(154,170,204,${(alpha * 0.56).toFixed(2)})`
        : (isSunset ? `rgba(255,226,200,${(alpha * 0.78).toFixed(2)})` : `rgba(248,248,244,${(alpha * 0.78).toFixed(2)})`);
      drawPixelRectWorld(ctx, cam, pxWorld - sz * 0.48 * wScale, pyWorld - sz * 0.25 * wScale, sz, sz * 0.68, shadeCol, wScale);
      drawPixelRectWorld(ctx, cam, pxWorld - sz * 0.56 * wScale, pyWorld - sz * 0.50 * wScale, sz * 0.82, sz * 0.52, litCol, wScale);
    }
  }

  // Village chimneys (sunset & night) aligned with unified SW->NE breeze
  if ((isSunset || isNight) && (scale * wScale >= 0.22) && animData.ambient.village_chimneys) {
    const chimneys = animData.ambient.village_chimneys;
    for (let ci = 0; ci < chimneys.length; ci++) {
      const c = chimneys[ci];
      const sx = offsetX + c.u * worldW * scale;
      const sy = offsetY + c.v * worldH * scale;
      if (sx < -48 || sx > canvasW + 48 || sy < -48 || sy > canvasH + 48) continue;
      const cxW = c.u * worldW;
      const cyW = c.v * worldH;
      const cPh = c.phase || 0;
      for (let p = 0; p < 4; p++) {
        const age = (((tSec * 0.22 + cPh + p / 4) % 1) + 1) % 1;
        const driftX = age * 15 * wind.wx * wScale + Math.sin(age * 5.2 + p * 1.9 + cPh * 6.28) * 1.5 * wScale;
        const riseY = -(2 + age * 19) * wScale + age * 5 * wind.wy * wScale;
        const sz = 1.4 + age * 3.2;
        const alpha = (1 - age) * (age < 0.15 ? age / 0.15 : 1.0) * (isNight ? 0.36 : 0.44);
        const col = isNight
          ? `rgba(170,188,218,${alpha.toFixed(2)})`
          : `rgba(255,222,196,${alpha.toFixed(2)})`;
        drawPixelRectWorld(ctx, cam, cxW + driftX - sz * 0.5 * wScale, cyW + riseY - sz * 0.4 * wScale, sz, sz * 0.72, col, wScale);
      }
    }
  }

  // Dorfbrunnen village fountains
  if ((scale * wScale >= 0.30) && animData.ambient.fountains) {
    const fts = animData.ambient.fountains;
    const sPx = scale * wScale;
    ctx.save();
    for (let fi = 0; fi < fts.length; fi++) {
      const ft = fts[fi];
      const sx = offsetX + ft.u * worldW * scale;
      const sy = offsetY + ft.v * worldH * scale;
      if (sx < -32 || sx > canvasW + 32 || sy < -32 || sy > canvasH + 32) continue;
      const basinCol = isNight ? '#2d6488' : (isSunset ? '#5aaec4' : '#42b8d8');
      const jetCol = isNight ? '#93c5fd' : (isSunset ? '#ffe4c8' : '#e8fbff');
      const dropCol = isNight ? '#60a5fa' : '#7dd3fc';
      ctx.fillStyle = basinCol;
      ctx.fillRect(Math.round(sx - 2.2 * sPx), Math.round(sy - 1.1 * sPx), Math.max(3, Math.round(4.5 * sPx)), Math.max(2, Math.round(2.4 * sPx)));
      const rPhase = (((tSec * 0.9 + fi * 0.37) % 1) + 1) % 1;
      const rRad = (1.2 + rPhase * 3.2) * sPx;
      ctx.strokeStyle = isNight ? `rgba(147,197,253,${((1 - rPhase) * 0.45).toFixed(2)})` : `rgba(232,251,255,${((1 - rPhase) * 0.65).toFixed(2)})`;
      ctx.lineWidth = Math.max(1.0, 0.9 * sPx);
      ctx.beginPath();
      ctx.ellipse(sx, sy, rRad, rRad * 0.56, 0, 0, Math.PI * 2);
      ctx.stroke();
      const jetH = (3.2 + 0.6 * Math.sin(tSec * 6.5 + fi * 2.1)) * sPx;
      ctx.fillStyle = jetCol;
      ctx.fillRect(Math.round(sx - 0.5 * sPx), Math.round(sy - jetH), Math.max(1, Math.round(1.1 * sPx)), Math.max(2, Math.round(jetH)));
      ctx.fillStyle = dropCol;
      for (let d = 0; d < 3; d++) {
        const dp = (((tSec * 2.4 + fi * 0.4 + d / 3) % 1) + 1) % 1;
        const dx = (d - 1) * (1.2 + dp * 1.4) * sPx;
        const dy = -jetH * (1 - dp * dp) - Math.sin(dp * Math.PI) * 1.4 * sPx;
        const dSz = Math.max(1, Math.round(1.0 * sPx));
        ctx.fillRect(Math.round(sx + dx), Math.round(sy + dy), dSz, dSz);
      }
    }
    ctx.restore();
  }

  // Lake Zurich gulls
  if (!isNight && animData.ambient.gulls) {
    const gullCol = isSunset ? '#ffe6cf' : '#f4f6fa';
    const tipCol = isSunset ? '#b49284' : '#8a94a6';
    for (let gIdx = 0; gIdx < animData.ambient.gulls.length; gIdx++) {
      const g = animData.ambient.gulls[gIdx];
      const spd = g.spd != null ? g.spd : (g.speed != null ? g.speed : 0.4);
      const ph = g.ph != null ? g.ph : (g.phase != null ? g.phase : 0);
      const ang = tSec * spd + ph * Math.PI * 2;
      const baseU = Array.isArray(g.uv) ? g.uv[0] : (g.cx != null ? g.cx : 0.55);
      const baseV = Array.isArray(g.uv) ? g.uv[1] : (g.cy != null ? g.cy : 0.62);
      const rxPx = (g.rx > 1) ? g.rx * wScale : (g.rx || 0.004) * worldW;
      const ryPx = (g.ry > 1) ? g.ry * wScale : (g.ry || 0.004) * worldH;
      const gx = baseU * worldW + Math.cos(ang) * rxPx;
      const gy = baseV * worldH + Math.sin(ang) * ryPx;
      if (!Number.isFinite(gx) || !Number.isFinite(gy)) continue;
      if (livingCounts) livingCounts.gulls++;
      const flap = Math.sin(tSec * 7.5 + gIdx * 1.9);
      const wy = (flap > 0.25 ? -1.4 : (flap < -0.25 ? 1.2 : 0)) * wScale;
      drawPixelRectWorld(ctx, cam, gx - 3.0 * wScale, gy + wy, 1.5, 1.2, tipCol, wScale);
      drawPixelRectWorld(ctx, cam, gx - 1.6 * wScale, gy + wy * 0.4, 1.8, 1.2, gullCol, wScale);
      drawPixelRectWorld(ctx, cam, gx, gy, 1.6, 1.4, gullCol, wScale);
      drawPixelRectWorld(ctx, cam, gx + 1.6 * wScale, gy + wy * 0.4, 1.8, 1.2, gullCol, wScale);
      drawPixelRectWorld(ctx, cam, gx + 3.0 * wScale, gy + wy, 1.5, 1.2, tipCol, wScale);
    }
  }
}

/**
 * Helper to draw a V-shaped surface wake behind a swimming waterfowl (swan or duck).
 */
function drawWaterfowlWake(ctx, sx, sy, vx, vy, px, isNight, scaleMul = 1.0) {
  const vm = Math.hypot(vx, vy) || 1;
  const tx = vx / vm;
  const ty = vy / vm;
  const nx = -ty;
  const ny = tx;
  ctx.fillStyle = isNight ? 'rgba(130, 174, 218, 0.26)' : 'rgba(232, 248, 255, 0.48)';
  for (let k = 1; k <= 2; k++) {
    const back = (2.1 + k * 1.7) * px * scaleMul;
    const spread = (0.7 + k * 0.95) * px * scaleMul;
    const sz = Math.max(1, Math.round((1.4 - k * 0.25) * px * scaleMul));
    const ax = sx - tx * back + nx * spread;
    const ay = sy - ty * back + ny * spread;
    const bx = sx - tx * back - nx * spread;
    const by = sy - ty * back - ny * spread;
    ctx.fillRect(Math.round(ax), Math.round(ay), sz, Math.max(1, Math.round(0.8 * px)));
    ctx.fillRect(Math.round(bx), Math.round(by), sz, Math.max(1, Math.round(0.8 * px)));
  }
}

/**
 * Kilchberg living landmark vignettes, all sports fields (including network.extra_sports),
 * Lake Zurich micro-life (moored boats, swans, ducks, slow SUPs + paddle ripples, slow rowboat/skiff),
 * terrace glows, platform lamps, and nighttime streetlamp glows.
 */
export function drawKilchbergDetails(
  ctx,
  cam,
  depthMgr,
  animData,
  livingCounts,
  worldW,
  worldH,
  wScale,
  tSec,
  mode,
  fixedAnimTime = null,
  opts = {},
) {
  const { scale, offsetX, offsetY, width: canvasW, height: canvasH } = cam;
  const isNight = mode === 'night';
  const isSunset = mode === 'sunset';
  const hasDynamicPeds = !!opts.hasDynamicPeds;
  const s = scale * wScale;
  const toX = (u) => u * worldW * scale + offsetX;
  const toY = (v) => v * worldH * scale + offsetY;
  const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};
  const wind = getWindVector(tSec);

  const padU = Math.max(0.004, 48 / Math.max(1, worldW * scale));
  const padV = Math.max(0.008, 48 / Math.max(1, worldH * scale));
  const visU0 = (-offsetX / Math.max(1, worldW * scale)) - padU;
  const visU1 = ((canvasW - offsetX) / Math.max(1, worldW * scale)) + padU;
  const visV0 = (-offsetY / Math.max(1, worldH * scale)) - padV;
  const visV1 = ((canvasH - offsetY) / Math.max(1, worldH * scale)) + padV;
  const boxInView = (u0, v0, u1, v1) => u1 >= visU0 && u0 <= visU1 && v1 >= visV0 && v0 <= visV1;
  const inView = (x, y, padWorld = 60) => {
    const pad = Math.max(60, padWorld * s);
    return x >= -pad && x <= canvasW + pad && y >= -pad && y <= canvasH + pad;
  };
  const coats = ['#d9382e', '#2563eb', '#0d9488', '#d97706', '#7c3aed', '#e11d48', '#334155', '#16a34a'];
  const hairs = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];
  const walkerBounds = { ex: 4.5 * wScale, eyUp: 9.5 * wScale, eyDn: 3.5 * wScale };

  ctx.save();

  // =========================================================================
  // 1. REFORMIERTE KIRCHE KILCHBERG — Live Swiss Tower Clock + Circling Swifts
  // =========================================================================
  const rkClock = (vig.reformierte_kirche && vig.reformierte_kirche.clock) || [0.29037, 0.31779];
  const rkSpire = (vig.reformierte_kirche && vig.reformierte_kirche.spire) || [0.29037, 0.30554];
  if (boxInView(rkClock[0] - 0.006, rkSpire[1] - 0.008, rkClock[0] + 0.006, rkClock[1] + 0.007)) {
    const cx = toX(rkClock[0]);
    const cy = toY(rkClock[1]);
    let hr; let min; let sec;
    if (fixedAnimTime !== null) {
      hr = 14; min = 20 + Math.floor(fixedAnimTime / 60); sec = fixedAnimTime % 60;
    } else {
      const now = new Date();
      const zh = new Date(now.toLocaleString('en-US', { timeZone: 'Europe/Zurich' }));
      hr = zh.getHours(); min = zh.getMinutes(); sec = zh.getSeconds();
    }
    const rDial = 6.2 * s;
    if (rDial >= 2.2) {
      ctx.fillStyle = isNight ? '#1c2a42' : '#162030';
      ctx.beginPath();
      ctx.arc(cx, cy, rDial, 0, Math.PI * 2);
      ctx.fill();
      if (isNight) {
        ctx.strokeStyle = 'rgba(255,220,120,0.45)';
        ctx.lineWidth = Math.max(1.0, 1.1 * s);
        ctx.stroke();
      }
      const minAng = ((min + sec / 60) / 60) * Math.PI * 2 - Math.PI * 0.5;
      const hrAng = (((hr % 12) + min / 60) / 12) * Math.PI * 2 - Math.PI * 0.5;
      ctx.strokeStyle = isNight ? '#ffe38a' : '#f4cf58';
      ctx.lineCap = 'round';
      ctx.lineWidth = Math.max(1.2, 1.5 * s);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(hrAng) * rDial * 0.56, cy + Math.sin(hrAng) * rDial * 0.56);
      ctx.stroke();
      ctx.lineWidth = Math.max(1.0, 1.15 * s);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(minAng) * rDial * 0.84, cy + Math.sin(minAng) * rDial * 0.84);
      ctx.stroke();
      ctx.fillStyle = '#fff5cc';
      ctx.fillRect(Math.round(cx - 0.7 * s), Math.round(cy - 0.7 * s), Math.max(1.5, Math.round(1.4 * s)), Math.max(1.5, Math.round(1.4 * s)));
    }

    if (!isNight) {
      const spX = toX(rkSpire[0]);
      const spY = toY(rkSpire[1]);
      ctx.fillStyle = isSunset ? '#2e2230' : '#26303d';
      for (let b = 0; b < 4; b++) {
        const ang = tSec * (0.95 + b * 0.13) + b * 1.62;
        const bx = spX + Math.cos(ang) * (16 + b * 5) * s;
        const by = spY + Math.sin(ang) * (7 + b * 2.2) * s;
        const fl = Math.sin(tSec * 12.0 + b * 2.3) > 0 ? -1 : 1;
        const px = Math.max(1, Math.round(1.1 * s));
        ctx.fillRect(Math.round(bx - px * 2), Math.round(by + fl * px * 0.6), px * 2, px);
        ctx.fillRect(Math.round(bx), Math.round(by), px, px);
        ctx.fillRect(Math.round(bx + px), Math.round(by + fl * px * 0.6), px * 2, px);
      }
    }
  }

  // =========================================================================
  // 2. LINDT HOME OF CHOCOLATE — 9m Golden Chocolate Fountain Atrium Shimmer
  // =========================================================================
  const lindtAtrium = (vig.lindt_hoc && vig.lindt_hoc.atrium) || [0.37821, 0.64638];
  const lindtPlaza = (vig.lindt_hoc && vig.lindt_hoc.plaza) || [0.37800, 0.65101];
  if (boxInView(lindtAtrium[0] - 0.007, lindtAtrium[1] - 0.005, lindtAtrium[0] + 0.007, lindtPlaza[1] + 0.008)) {
    const shimmer = 0.76 + 0.24 * Math.sin(tSec * 3.4);
    const arcOffsets = [
      [-0.0018, 0.0004], [-0.0007, -0.0001], [0.0004, -0.0002], [0.0016, 0.0000],
    ];
    for (let i = 0; i < arcOffsets.length; i++) {
      const ax = toX(lindtAtrium[0] + arcOffsets[i][0]);
      const ay = toY(lindtAtrium[1] + arcOffsets[i][1]);
      const pGlow = 0.75 + 0.25 * Math.sin(tSec * 4.2 + i * 1.3);
      const rw = Math.max(3, 5.2 * s);
      const rh = Math.max(2, 3.6 * s);
      ctx.fillStyle = isNight
        ? `rgba(255, 206, 94, ${(0.76 * pGlow).toFixed(2)})`
        : (isSunset ? `rgba(255, 204, 102, ${(0.54 * pGlow).toFixed(2)})` : `rgba(255, 214, 118, ${(0.38 * pGlow).toFixed(2)})`);
      ctx.fillRect(Math.round(ax - rw * 0.5), Math.round(ay - rh * 0.5), Math.round(rw), Math.round(rh));
    }

    const fx = toX(lindtAtrium[0]);
    const fy = toY(lindtAtrium[1]);
    const colW = Math.max(2, 2.8 * s);
    const colH = Math.max(4, 7.5 * s);
    const fAlpha = isNight ? (0.86 * shimmer) : (isSunset ? (0.70 * shimmer) : 0.38);
    ctx.fillStyle = `rgba(245, 168, 24, ${(fAlpha * 0.85).toFixed(2)})`;
    ctx.fillRect(Math.round(fx - colW * 0.5), Math.round(fy - colH * 0.6), Math.round(colW), Math.round(colH));
    for (let k = 0; k < 3; k++) {
      const prog = (((tSec * 1.4 + k / 3) % 1) + 1) % 1;
      const yOff = (prog - 0.55) * 6.5 * s;
      ctx.fillStyle = `rgba(255, 242, 178, ${(fAlpha * (1.0 - Math.abs(prog - 0.5))).toFixed(2)})`;
      ctx.fillRect(Math.round(fx - colW * 0.32), Math.round(fy + yOff), Math.max(1.5, Math.round(colW * 0.65)), Math.max(1.5, Math.round(1.5 * s)));
    }

    if (isNight || isSunset) {
      const gRad = 28 * s;
      const grad = ctx.createRadialGradient(fx, toY(lindtAtrium[1] + 0.0008), 2 * s, fx, toY(lindtAtrium[1] + 0.0034), gRad);
      grad.addColorStop(0, isNight ? `rgba(255, 206, 98, ${(0.38 * shimmer).toFixed(2)})` : `rgba(255, 200, 106, ${(0.24 * shimmer).toFixed(2)})`);
      grad.addColorStop(1, 'rgba(255, 198, 104, 0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.ellipse(fx, toY(lindtAtrium[1] + 0.0034), gRad * 1.28, gRad * 0.74, -0.15, 0, Math.PI * 2);
      ctx.fill();
    }

    // Legacy static Lindt plaza walkers (suppressed when dynamic M4 pedestrians.js is active)
    if (!hasDynamicPeds) {
      const plazaOffsets = [
        { du0: -0.0022, dv0: 0.0000, du1: 0.0020, dv1: -0.0014, spd: 0.08, ph: 0.1, bag: '#e5b93c' },
        { du0: 0.0022, dv0: 0.0014, du1: -0.0016, dv1: -0.0006, spd: 0.07, ph: 0.45, bag: '#d62c28' },
        { du0: -0.0010, dv0: 0.0024, du1: 0.0014, dv1: -0.0024, spd: 0.06, ph: 0.72, bag: '#e5b93c' },
        { du0: -0.0018, dv0: -0.0016, du1: 0.0010, dv1: 0.0018, spd: 0.055, ph: 0.25, bag: null },
        { du0: 0.0012, dv0: -0.0022, du1: -0.0008, dv1: 0.0010, spd: 0.065, ph: 0.88, bag: '#e5b93c' },
      ];
      const nVis = isNight ? 2 : (isSunset ? 4 : plazaOffsets.length);
      for (let i = 0; i < nVis; i++) {
        const w = plazaOffsets[i];
        const p = 0.5 + 0.5 * Math.sin(tSec * w.spd * Math.PI * 2 + w.ph * Math.PI * 2);
        const wu = lindtPlaza[0] + w.du0 + (w.du1 - w.du0) * p;
        const wv = lindtPlaza[1] + w.dv0 + (w.dv1 - w.dv0) * p;
        const wx = wu * worldW;
        const wy = wv * worldH;
        const coat = shadeHex(coats[i % coats.length], 1.0, mode);
        const pants = shadeHex('#263040', 1.0, mode);
        const d16 = depthMgr.evalWalkerD16(wx, wy, 413.9, worldW, worldH, false);
        depthMgr.drawDepthMasked(ctx, cam, wx, wy, walkerBounds, d16, worldW, worldH, (targetCtx) => {
          drawMiniPerson(targetCtx, toX(wu), toY(wv), s, coat, pants, hairs[i % hairs.length], isNight, tSec * 7.5 + i * 1.9, w.bag, canvasW, canvasH);
        }, 2.0);
      }
    }
  }

  // =========================================================================
  // 3. TC KILCHBERG CLAY TENNIS COURTS — 3 Live Animated Matches
  // =========================================================================
  const tcSrc = Array.isArray(vig.tc_kilchberg) && vig.tc_kilchberg.length >= 3
    ? vig.tc_kilchberg
    : [
      { sw: [0.17388, 0.34389], ne: [0.17966, 0.33951], lat: [0.00074, 0.00125] },
      { sw: [0.17697, 0.34873], ne: [0.18262, 0.34423], lat: [0.00076, 0.00123] },
      { sw: [0.16390, 0.35396], ne: [0.16970, 0.34942], lat: [0.00076, 0.00124] },
    ];
  if (!isNight && boxInView(0.156, 0.334, 0.188, 0.362)) {
    const tcMeta = [{ ph: 0.0, freq: 1.55 }, { ph: 1.3, freq: 1.42 }, { ph: 2.1, freq: 1.36 }];
    for (let ci = 0; ci < tcSrc.length; ci++) {
      const c = tcSrc[ci];
      const m = tcMeta[ci % tcMeta.length];
      if (!boxInView(c.sw[0] - 0.003, c.ne[1] - 0.004, c.ne[0] + 0.003, c.sw[1] + 0.004)) continue;

      const cyc = (((tSec * m.freq + m.ph) % 2.0) + 2.0) % 2.0;
      const ballF = cyc < 1.0 ? cyc : (2.0 - cyc);
      const latA = Math.sin(tSec * 0.78 + ci * 2.4) * 0.68;
      const latB = Math.cos(tSec * 0.85 + ci * 1.7) * 0.68;
      const ballLat = latA * (1 - ballF) + latB * ballF;

      const pAx = toX(c.sw[0] + c.lat[0] * latA);
      const pAy = toY(c.sw[1] + c.lat[1] * latA);
      const pBx = toX(c.ne[0] + c.lat[0] * latB);
      const pBy = toY(c.ne[1] + c.lat[1] * latB);
      const whiteKit = isSunset ? '#ffe8d4' : '#f4f7fa';
      const shortCol = ci === 0 ? '#1e3a5f' : (ci === 1 ? '#991b1b' : '#166534');
      drawMiniPerson(ctx, pBx, pBy, s * 0.90, whiteKit, shortCol, hairs[ci % hairs.length], false, tSec * 10.0 + 1.0, null, canvasW, canvasH);
      drawMiniPerson(ctx, pAx, pAy, s * 0.90, whiteKit, '#1e3a5f', hairs[(ci + 2) % hairs.length], false, tSec * 10.0, null, canvasW, canvasH);

      const bu = c.sw[0] + (c.ne[0] - c.sw[0]) * ballF + c.lat[0] * ballLat;
      const bv = c.sw[1] + (c.ne[1] - c.sw[1]) * ballF + c.lat[1] * ballLat;
      const arcH = Math.sin(ballF * Math.PI) * 8.5 * s;
      const bx = toX(bu);
      const by = toY(bv);
      const bSz = Math.max(1.6, 1.8 * s);
      ctx.fillStyle = 'rgba(28, 18, 12, 0.35)';
      ctx.fillRect(Math.round(bx - bSz * 0.4), Math.round(by), Math.max(1.5, Math.round(bSz * 0.8)), Math.max(1, Math.round(bSz * 0.6)));
      ctx.fillStyle = '#d9ff3b';
      ctx.fillRect(Math.round(bx - bSz * 0.5), Math.round(by - arcH - bSz * 0.5), Math.max(2, Math.round(bSz)), Math.max(2, Math.round(bSz)));
    }
  }

  // =========================================================================
  // 3b. SPORTPLATZ HOCHWEID — Live FC Kilchberg Football Match & Night Floodlights
  // =========================================================================
  const spVig = vig.sportplatz_hochweid || {
    center: [0.31377, 0.22953], half_l: [0.01364, -0.00936], half_w: [0.00506, 0.00945],
  };
  const fCU = spVig.center[0];
  const fCV = spVig.center[1];
  if (boxInView(fCU - 0.022, fCV - 0.022, fCU + 0.022, fCV + 0.022)) {
    const fLenU = spVig.half_l[0];
    const fLenV = spVig.half_l[1];
    const fLatU = spVig.half_w[0];
    const fLatV = spVig.half_w[1];
    const fieldUV = (lu, lv) => ({
      u: fCU + lu * fLenU + lv * fLatU,
      v: fCV + lu * fLenV + lv * fLatV,
    });

    if (isNight) {
      const masts = [[-0.58, -1.04], [0.58, -1.04], [-0.58, 1.04], [0.58, 1.04]];
      for (let mi = 0; mi < masts.length; mi++) {
        const p = fieldUV(masts[mi][0], masts[mi][1]);
        const gx = toX(p.u);
        const gy = toY(p.v);
        const rad = 52 * s;
        const grad = ctx.createRadialGradient(gx, gy, 2 * s, gx, gy, rad);
        grad.addColorStop(0, 'rgba(255, 240, 195, 0.26)');
        grad.addColorStop(0.55, 'rgba(255, 224, 155, 0.10)');
        grad.addColorStop(1, 'rgba(255, 210, 120, 0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.ellipse(gx, gy, rad * 1.15, rad * 0.68, -0.32, 0, Math.PI * 2);
        ctx.fill();
      }
    } else {
      const ballAng = tSec * 0.42;
      const ballLU = Math.sin(ballAng) * 0.64 + Math.sin(ballAng * 2.3) * 0.16;
      const ballLV = Math.cos(ballAng * 1.35) * 0.56;
      const blueKit = isSunset ? '#2e64b8' : '#2563eb';
      const redKit = isSunset ? '#c83434' : '#dc2626';
      const gkA = isSunset ? '#e6c238' : '#facc15';
      const gkB = isSunset ? '#58c448' : '#4ade80';

      const players = [
        { lu: -0.92, lv: Math.sin(tSec * 1.4) * 0.14, kit: gkA, shorts: '#1e293b', hi: 0 },
        { lu: 0.92, lv: Math.cos(tSec * 1.3) * 0.14, kit: gkB, shorts: '#1e293b', hi: 1 },
        { lu: -0.52 + ballLU * 0.35 + Math.sin(tSec * 0.9) * 0.08, lv: -0.34 + ballLV * 0.28, kit: blueKit, shorts: '#f8fafc', hi: 2 },
        { lu: -0.45 + ballLU * 0.38 + Math.cos(tSec * 1.1) * 0.09, lv: 0.32 + ballLV * 0.30, kit: blueKit, shorts: '#f8fafc', hi: 3 },
        { lu: ballLU * 0.88 - 0.06, lv: ballLV * 0.86 + Math.sin(tSec * 1.6) * 0.07, kit: blueKit, shorts: '#f8fafc', hi: 4 },
        { lu: 0.18 + ballLU * 0.45 + Math.sin(tSec * 1.2 + 1.0) * 0.11, lv: -0.28 + ballLV * 0.36, kit: blueKit, shorts: '#f8fafc', hi: 0 },
        { lu: 0.26 + ballLU * 0.44 + Math.cos(tSec * 1.0 + 2.0) * 0.10, lv: 0.36 + ballLV * 0.32, kit: blueKit, shorts: '#f8fafc', hi: 1 },
        { lu: 0.52 + ballLU * 0.34 + Math.cos(tSec * 0.95) * 0.08, lv: -0.30 + ballLV * 0.28, kit: redKit, shorts: '#f8fafc', hi: 2 },
        { lu: 0.46 + ballLU * 0.36 + Math.sin(tSec * 1.05) * 0.09, lv: 0.30 + ballLV * 0.30, kit: redKit, shorts: '#f8fafc', hi: 3 },
        { lu: ballLU * 0.86 + 0.07, lv: ballLV * 0.84 + Math.cos(tSec * 1.5) * 0.08, kit: redKit, shorts: '#f8fafc', hi: 4 },
        { lu: -0.18 + ballLU * 0.45 + Math.cos(tSec * 1.15 + 1.4) * 0.10, lv: -0.36 + ballLV * 0.34, kit: redKit, shorts: '#f8fafc', hi: 0 },
        { lu: -0.24 + ballLU * 0.42 + Math.sin(tSec * 1.25 + 2.6) * 0.10, lv: 0.28 + ballLV * 0.34, kit: redKit, shorts: '#f8fafc', hi: 1 },
      ];
      const drawList = players.map((pl, idx) => {
        const p = fieldUV(Math.max(-0.94, Math.min(0.94, pl.lu)), Math.max(-0.88, Math.min(0.88, pl.lv)));
        return { x: toX(p.u), y: toY(p.v), pl, idx };
      });
      drawList.sort((a, b) => a.y - b.y);
      for (let di = 0; di < drawList.length; di++) {
        const d = drawList[di];
        drawMiniPerson(ctx, d.x, d.y, s * 0.88, d.pl.kit, d.pl.shorts, hairs[d.pl.hi % hairs.length], false, tSec * 9.0 + d.idx * 1.3, null, canvasW, canvasH);
      }

      const bp = fieldUV(ballLU, ballLV);
      const fbx = toX(bp.u);
      const fby = toY(bp.v);
      const bounceH = Math.abs(Math.sin(tSec * 3.4)) * 5.2 * s;
      const fbSz = Math.max(1.8, 2.0 * s);
      ctx.fillStyle = 'rgba(20, 32, 18, 0.36)';
      ctx.fillRect(Math.round(fbx - fbSz * 0.4), Math.round(fby), Math.max(1.5, Math.round(fbSz * 0.9)), Math.max(1, Math.round(fbSz * 0.55)));
      ctx.fillStyle = '#f8fafc';
      ctx.fillRect(Math.round(fbx - fbSz * 0.5), Math.round(fby - bounceH - fbSz * 0.5), Math.max(2, Math.round(fbSz)), Math.max(2, Math.round(fbSz)));
    }
  }

  // =========================================================================
  // 3c. ALL 5 EXTRA SPORTS FIELDS (animData.network.extra_sports, Day & Sunset)
  // =========================================================================
  const extraSports = (animData && animData.network && Array.isArray(animData.network.extra_sports))
    ? animData.network.extra_sports
    : [];
  if (!isNight && extraSports.length > 0 && s >= 0.25) {
    const drawSportsActor = (u, v, d16, kit, shorts, hair, stride) => {
      const wx = u * worldW;
      const wy = v * worldH;
      const sx = toX(u);
      const sy = toY(v);
      if (s >= 0.55 && d16) {
        depthMgr.drawDepthMasked(ctx, cam, wx, wy, walkerBounds, d16, worldW, worldH, (targetCtx) => {
          drawMiniPerson(targetCtx, sx, sy, s * 0.86, kit, shorts, hair, false, stride, null, canvasW, canvasH);
        }, 2.0);
      } else {
        drawMiniPerson(ctx, sx, sy, s * 0.86, kit, shorts, hair, false, stride, null, canvasW, canvasH);
      }
    };

    for (let fi = 0; fi < extraSports.length; fi++) {
      const fld = extraSports[fi];
      if (!boxInView(fld.u - 0.018, fld.v - 0.018, fld.u + 0.018, fld.v + 0.018)) continue;
      const { halfL, halfW } = fieldAxesUV(fld);
      const toFieldUV = (lu, lv) => ({
        u: fld.u + lu * halfL[0] + lv * halfW[0],
        v: fld.v + lu * halfL[1] + lv * halfW[1],
      });

      if (fld.kind === 'tennis') {
        const cyc = (((tSec * 1.48 + fi * 0.7) % 2.0) + 2.0) % 2.0;
        const ballF = cyc < 1.0 ? cyc : (2.0 - cyc);
        const latA = Math.sin(tSec * 0.82 + fi * 1.9) * 0.62;
        const latB = Math.cos(tSec * 0.88 + fi * 2.3) * 0.62;
        const pA = toFieldUV(-0.82, latA);
        const pB = toFieldUV(0.82, latB);
        const whiteKit = isSunset ? '#ffe8d4' : '#f4f7fa';
        const actors = [
          { ...pA, shorts: '#1e3a5f', hi: 0, st: tSec * 9.6 },
          { ...pB, shorts: '#991b1b', hi: 2, st: tSec * 9.6 + 1.2 },
        ].sort((a, b) => a.v - b.v);
        for (const a of actors) {
          drawSportsActor(a.u, a.v, fld.d16, whiteKit, a.shorts, hairs[a.hi], a.st);
        }
        const bPos = toFieldUV(-0.82 + 1.64 * ballF, latA * (1 - ballF) + latB * ballF);
        const bx = toX(bPos.u);
        const by = toY(bPos.v);
        const arcH = Math.sin(ballF * Math.PI) * 7.8 * s;
        const bSz = Math.max(1.5, 1.7 * s);
        ctx.fillStyle = 'rgba(28, 18, 12, 0.34)';
        ctx.fillRect(Math.round(bx - bSz * 0.4), Math.round(by), Math.max(1.5, Math.round(bSz * 0.8)), Math.max(1, Math.round(bSz * 0.55)));
        ctx.fillStyle = '#d9ff3b';
        ctx.fillRect(Math.round(bx - bSz * 0.5), Math.round(by - arcH - bSz * 0.5), Math.max(2, Math.round(bSz)), Math.max(2, Math.round(bSz)));
      } else if (fld.kind === 'football') {
        const isUpper = fld.id && fld.id.includes('upper');
        const kitA = shadeHex(isUpper ? '#1e3a8a' : '#0d9488', 1.0, mode);
        const kitB = shadeHex(isUpper ? '#f1f5f9' : '#d97706', 1.0, mode);
        const gkCol = shadeHex('#facc15', 1.0, mode);
        const bAng = tSec * (isUpper ? 0.38 : 0.46) + fi * 1.7;
        const bLU = Math.sin(bAng) * 0.62 + Math.sin(bAng * 2.1) * 0.14;
        const bLV = Math.cos(bAng * 1.28) * 0.52;
        const roster = [
          { lu: -0.88, lv: Math.sin(tSec * 1.3 + fi) * 0.14, kit: gkCol, shorts: '#1e293b', hi: 0 },
          { lu: 0.88, lv: Math.cos(tSec * 1.2 + fi) * 0.14, kit: gkCol, shorts: '#1e293b', hi: 1 },
          { lu: -0.46 + bLU * 0.34, lv: -0.30 + bLV * 0.28 + Math.sin(tSec * 1.1) * 0.08, kit: kitA, shorts: '#1e293b', hi: 2 },
          { lu: -0.36 + bLU * 0.38, lv: 0.32 + bLV * 0.28 + Math.cos(tSec * 1.0) * 0.08, kit: kitA, shorts: '#1e293b', hi: 3 },
          { lu: bLU * 0.84 - 0.08, lv: bLV * 0.82 + Math.sin(tSec * 1.5) * 0.07, kit: kitA, shorts: '#1e293b', hi: 4 },
          { lu: 0.22 + bLU * 0.40, lv: -0.22 + bLV * 0.32 + Math.cos(tSec * 1.2) * 0.09, kit: kitA, shorts: '#1e293b', hi: 0 },
          { lu: 0.46 + bLU * 0.32, lv: -0.28 + bLV * 0.28 + Math.cos(tSec * 0.95) * 0.08, kit: kitB, shorts: '#334155', hi: 1 },
          { lu: 0.38 + bLU * 0.36, lv: 0.30 + bLV * 0.30 + Math.sin(tSec * 1.05) * 0.08, kit: kitB, shorts: '#334155', hi: 2 },
          { lu: bLU * 0.82 + 0.08, lv: bLV * 0.80 + Math.cos(tSec * 1.45) * 0.08, kit: kitB, shorts: '#334155', hi: 3 },
          { lu: -0.20 + bLU * 0.42, lv: 0.22 + bLV * 0.32 + Math.sin(tSec * 1.15) * 0.09, kit: kitB, shorts: '#334155', hi: 4 },
        ];
        const sorted = roster.map((pl, idx) => {
          const p = toFieldUV(Math.max(-0.92, Math.min(0.92, pl.lu)), Math.max(-0.85, Math.min(0.85, pl.lv)));
          return { ...p, pl, idx };
        }).sort((a, b) => a.v - b.v);
        for (const item of sorted) {
          drawSportsActor(item.u, item.v, fld.d16, item.pl.kit, item.pl.shorts, hairs[item.pl.hi % hairs.length], tSec * 8.8 + item.idx * 1.3 + fi);
        }
        const bp = toFieldUV(bLU, bLV);
        const fbx = toX(bp.u);
        const fby = toY(bp.v);
        const bounceH = Math.abs(Math.sin(tSec * 3.2 + fi)) * 4.6 * s;
        const fbSz = Math.max(1.6, 1.9 * s);
        ctx.fillStyle = 'rgba(20, 32, 18, 0.34)';
        ctx.fillRect(Math.round(fbx - fbSz * 0.4), Math.round(fby), Math.max(1.5, Math.round(fbSz * 0.9)), Math.max(1, Math.round(fbSz * 0.5)));
        ctx.fillStyle = '#f8fafc';
        ctx.fillRect(Math.round(fbx - fbSz * 0.5), Math.round(fby - bounceH - fbSz * 0.5), Math.max(2, Math.round(fbSz)), Math.max(2, Math.round(fbSz)));
      } else {
        // Multisport schoolyard / village scrimmage (4 players + orange-white ball)
        const isGem = fld.id && fld.id.includes('gemeindehaus');
        const kitA = shadeHex(isGem ? '#059669' : '#2563eb', 1.0, mode);
        const kitB = shadeHex(isGem ? '#eab308' : '#e11d48', 1.0, mode);
        const bAng = tSec * 0.62 + fi * 2.1;
        const bLU = Math.sin(bAng) * 0.58;
        const bLV = Math.cos(bAng * 1.45) * 0.52;
        const roster = [
          { lu: bLU * 0.72 - 0.18, lv: bLV * 0.65 - 0.16, kit: kitA, hi: 0 },
          { lu: -0.32 + bLU * 0.40, lv: 0.28 + bLV * 0.32, kit: kitA, hi: 2 },
          { lu: bLU * 0.72 + 0.18, lv: bLV * 0.65 + 0.14, kit: kitB, hi: 1 },
          { lu: 0.32 + bLU * 0.40, lv: -0.26 + bLV * 0.32, kit: kitB, hi: 3 },
        ];
        const sorted = roster.map((pl, idx) => {
          const p = toFieldUV(Math.max(-0.88, Math.min(0.88, pl.lu)), Math.max(-0.82, Math.min(0.82, pl.lv)));
          return { ...p, pl, idx };
        }).sort((a, b) => a.v - b.v);
        for (const item of sorted) {
          drawSportsActor(item.u, item.v, fld.d16, item.pl.kit, '#1e293b', hairs[item.pl.hi % hairs.length], tSec * 9.4 + item.idx * 1.7 + fi);
        }
        const bp = toFieldUV(bLU, bLV);
        const bx = toX(bp.u);
        const by = toY(bp.v);
        const bounceH = Math.abs(Math.sin(tSec * 4.6 + fi)) * 4.8 * s;
        const bSz = Math.max(1.5, 1.8 * s);
        ctx.fillStyle = '#fb923c';
        ctx.fillRect(Math.round(bx - bSz * 0.5), Math.round(by - bounceH - bSz * 0.5), Math.max(2, Math.round(bSz)), Math.max(2, Math.round(bSz)));
      }
    }
  }

  // =========================================================================
  // 4. SEEBAD KILCHBERG — Pool Swimmers, Beach Umbrellas, Jetty Bathers & Lake Swimmers
  // =========================================================================
  const seebadPool = (vig.seebad_kilchberg && vig.seebad_kilchberg.pool) || [0.40901, 0.70921];
  const seebadJetty = (vig.seebad_kilchberg && vig.seebad_kilchberg.jetty) || [[0.4126, 0.71361], [0.4216, 0.7232]];
  if (boxInView(seebadPool[0] - 0.010, seebadPool[1] - 0.012, seebadJetty[1][0] + 0.008, seebadJetty[1][1] + 0.010)) {
    const poolX = toX(seebadPool[0]);
    const poolY = toY(seebadPool[1]);
    if (isNight) {
      if (boxInView(seebadPool[0] - 0.005, seebadPool[1] - 0.006, seebadPool[0] + 0.006, seebadPool[1] + 0.007)) {
        const grad = ctx.createRadialGradient(poolX, poolY, 2 * s, poolX, poolY, 22 * s);
        grad.addColorStop(0, 'rgba(64, 228, 240, 0.34)');
        grad.addColorStop(1, 'rgba(32, 160, 200, 0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.ellipse(poolX, poolY, 22 * s, 14 * s, -0.35, 0, Math.PI * 2);
        ctx.fill();
      }
    } else {
      if (boxInView(seebadPool[0] - 0.004, seebadPool[1] - 0.005, seebadPool[0] + 0.005, seebadPool[1] + 0.006)) {
        const swimCaps = ['#f43f5e', '#facc15', '#ffffff'];
        for (let sw = 0; sw < 3; sw++) {
          const prog = 0.5 + 0.5 * Math.sin(tSec * (0.28 + sw * 0.05) + sw * 2.1);
          const su = seebadPool[0] - 0.0019 + prog * 0.0028 + sw * 0.0005;
          const sv = seebadPool[1] - 0.0023 + (1 - prog) * 0.0018 + sw * 0.0013;
          const sx = toX(su);
          const sy = toY(sv);
          const px = Math.max(1.2, 1.3 * s);
          ctx.fillStyle = 'rgba(240, 252, 255, 0.78)';
          ctx.fillRect(Math.round(sx - px * 1.6), Math.round(sy), Math.max(2, Math.round(px * 3.2)), Math.max(1, Math.round(px * 0.85)));
          ctx.fillStyle = swimCaps[sw];
          ctx.fillRect(Math.round(sx - px * 0.5), Math.round(sy - px * 0.7), Math.max(2, Math.round(px * 1.2)), Math.max(2, Math.round(px * 1.1)));
        }
      }

      if (boxInView(0.401, 0.699, 0.409, 0.706)) {
        const umbrellas = [
          { u: 0.4036, v: 0.7018, c1: '#d9382e', c2: '#f4f6f8', dk: '#8f1d18' },
          { u: 0.4052, v: 0.7010, c1: '#2563eb', c2: '#f4f6f8', dk: '#1a3f94' },
          { u: 0.4063, v: 0.7024, c1: '#eab308', c2: '#fef3c7', dk: '#a16207' },
        ];
        for (const um of umbrellas) {
          const ux = Math.round(toX(um.u));
          const uy = Math.round(toY(um.v));
          const p = Math.max(1.0, s);
          const w = (n) => Math.max(1, Math.round(n * p));
          ctx.fillStyle = 'rgba(16, 28, 22, 0.34)';
          ctx.fillRect(ux - w(2), uy + w(1), w(7), w(2));
          ctx.fillStyle = '#5c4028';
          ctx.fillRect(ux, uy - w(2), w(1), w(3));
          ctx.fillStyle = 'rgba(22, 26, 32, 0.82)';
          ctx.fillRect(ux - w(4), uy - w(4), w(9), w(3));
          ctx.fillRect(ux - w(3), uy - w(5), w(7), w(5));
          ctx.fillStyle = shadeHex(um.dk, 1.0, mode);
          ctx.fillRect(ux - w(3), uy - w(2), w(7), w(1.2));
          ctx.fillStyle = shadeHex(um.c1, 1.04, mode);
          ctx.fillRect(ux - w(3), uy - w(4), w(7), w(2.2));
          ctx.fillStyle = shadeHex(um.c2, 1.04, mode);
          ctx.fillRect(ux - w(1), uy - w(4.5), w(3), w(3.2));
          ctx.fillStyle = '#ffffff';
          ctx.fillRect(ux, uy - w(4.5), w(1), w(1));
        }
      }

      if (boxInView(seebadJetty[0][0] - 0.003, seebadJetty[0][1] - 0.003, seebadJetty[1][0] + 0.004, seebadJetty[1][1] + 0.004)) {
        for (let jb = 0; jb < 4; jb++) {
          const f = 0.14 + 0.76 * (0.5 + 0.5 * Math.sin(tSec * (0.11 + jb * 0.03) + jb * 1.7));
          const ju = seebadJetty[0][0] + (seebadJetty[1][0] - seebadJetty[0][0]) * f;
          const jv = seebadJetty[0][1] + (seebadJetty[1][1] - seebadJetty[0][1]) * f;
          drawMiniPerson(ctx, toX(ju), toY(jv), s * 0.92, shadeHex(coats[(jb + 2) % coats.length], 1.0, mode), '#2b4c7e', hairs[jb], false, tSec * 6.5 + jb, null, canvasW, canvasH);
        }
      }

      if (boxInView(0.421, 0.721, 0.432, 0.734)) {
        for (let ls = 0; ls < 2; ls++) {
          const ang = tSec * (0.32 + ls * 0.08) + ls * 3.1;
          const lsu = 0.4275 + Math.cos(ang) * 0.0022;
          const lsv = 0.7272 + Math.sin(ang) * 0.0024;
          if (!depthMgr.isWaterUV(lsu, lsv)) continue;
          const lx = toX(lsu);
          const ly = toY(lsv);
          const px = Math.max(1.2, 1.3 * s);
          ctx.fillStyle = 'rgba(232, 248, 255, 0.68)';
          ctx.fillRect(Math.round(lx - px * 1.8), Math.round(ly), Math.max(2, Math.round(px * 3.6)), Math.max(1, Math.round(px * 0.85)));
          ctx.fillStyle = ls === 0 ? '#fb7185' : '#38bdf8';
          ctx.fillRect(Math.round(lx - px * 0.5), Math.round(ly - px * 0.6), Math.max(2, Math.round(px * 1.2)), Math.max(2, Math.round(px * 1.1)));
        }
      }
    }
  }

  // =========================================================================
  // 5. BENDLIKON ZSG PIER GANGPLANK, MOORED BOATS, SWANS, DUCKS, SUPs & ROWBOAT
  // =========================================================================
  {
    const bpPax = (vig.bendlikon_pier && vig.bendlikon_pier.pax) || [0.58359, 0.57841];
    if (boxInView(bpPax[0] - 0.006, bpPax[1] - 0.006, bpPax[0] + 0.007, bpPax[1] + 0.009)) {
      let shipNear = false;
      let shipDocked = false;
      let dwellProg = 0;
      for (const sh of (animData.ships || [])) {
        if (sh.kind === 'zsg_steamer') {
          const st = evalWithStationStop(tSec, sh.length_m, sh.speed_mps, sh.stop_frac, sh.dwell_sec, sh.phase || 0, 5.0, 6.0);
          if (st.isDwelling) {
            shipDocked = true;
            shipNear = true;
            dwellProg = st.dwellProgress;
          } else if (st.frac >= 0 && Math.abs(st.frac - sh.stop_frac) < 0.04) {
            shipNear = true;
          }
        }
      }

      if (shipDocked) {
        const gpExt = dwellProg < 0.15 ? (dwellProg / 0.15) : (dwellProg > 0.85 ? (1.0 - dwellProg) / 0.15 : 1.0);
        const gpU0 = 0.5846;
        const gpV0 = 0.5805;
        const gpU1 = gpU0 + (0.5856 - gpU0) * gpExt;
        const gpV1 = gpV0 + (0.5844 - gpV0) * gpExt;
        const x0 = toX(gpU0);
        const y0 = toY(gpV0);
        const x1 = toX(gpU1);
        const y1 = toY(gpV1);
        ctx.strokeStyle = isNight ? '#5c4228' : '#8c6239';
        ctx.lineWidth = Math.max(2.2, 3.2 * s);
        ctx.lineCap = 'butt';
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
        ctx.stroke();
        ctx.strokeStyle = isNight ? '#94a3b8' : '#dce2ea';
        ctx.lineWidth = Math.max(0.8, 0.9 * s);
        for (const hOff of [-1.4 * s, 1.4 * s]) {
          ctx.beginPath();
          ctx.moveTo(x0 + hOff, y0 - 1.5 * s);
          ctx.lineTo(x1 + hOff, y1 - 1.5 * s);
          ctx.stroke();
        }
      }

      // Legacy static pier passengers (suppressed when dynamic M4 pedestrians.js is active)
      if (!hasDynamicPeds) {
        const pCount = isNight ? 2 : 5;
        for (let i = 0; i < pCount; i++) {
          let pu;
          let pv;
          let stride = shipNear ? tSec * 7.5 + i : tSec * 1.2 + i;
          if (shipDocked && i < 2 && dwellProg >= 0.18 && dwellProg <= 0.82) {
            const bProg = Math.min(1.0, Math.max(0.0, (dwellProg - 0.18 - i * 0.12) / 0.42));
            pu = 0.5844 + (0.5855 - 0.5844) * bProg;
            pv = 0.5801 + (0.5841 - 0.5801) * bProg;
            stride = tSec * 9.0 + i * 1.5;
          } else {
            const shift = shipNear ? 0.0004 : 0;
            pu = bpPax[0] - 0.00175 + i * 0.00088 + Math.sin(tSec * 0.4 + i * 1.7) * 0.00022 + shift;
            pv = bpPax[1] + 0.00082 - i * 0.00042 + Math.cos(tSec * 0.35 + i * 2.1) * 0.00016 + shift;
          }
          const wx = pu * worldW;
          const wy = pv * worldH;
          const d16 = depthMgr.evalWalkerD16(wx, wy, 407.2, worldW, worldH, true);
          depthMgr.drawDepthMasked(ctx, cam, wx, wy, walkerBounds, d16, worldW, worldH, (targetCtx) => {
            drawMiniPerson(
              targetCtx,
              toX(pu), toY(pv), s * 0.96,
              shadeHex(coats[(i + 1) % coats.length], 1.0, mode),
              shadeHex('#243040', 1.0, mode),
              hairs[i % hairs.length],
              isNight,
              stride,
              i === 1 ? '#b45309' : null,
              canvasW,
              canvasH,
            );
          }, 2.0);
        }
      }
    }

    // 5 Verified Open-Water Moored Sailboats with Wind-Synced Bobbing, Sway & Pennants
    const mooredBoats = [
      { u: 0.5758, v: 0.5835, pen: '#d9382e' },
      { u: 0.5935, v: 0.5675, pen: '#2563eb' },
      { u: 0.4435, v: 0.6995, pen: '#d9382e' },
      { u: 0.4145, v: 0.7315, pen: '#2563eb' },
      { u: 0.4045, v: 0.7395, pen: '#eab308' },
    ];
    for (let idx = 0; idx < mooredBoats.length; idx++) {
      const mb = mooredBoats[idx];
      if (!depthMgr.isWaterUV(mb.u, mb.v)) continue;
      const bx = toX(mb.u);
      const by = toY(mb.v);
      if (!inView(bx, by, 32)) continue;
      const bobPx = Math.sin(tSec * (2.1 + idx * 0.23) + idx * 1.7) * 0.75 * wind.strength * s;
      const swayPx = (wind.wx * 0.65 + Math.sin(tSec * (1.7 + idx * 0.19) + idx * 2.3) * 0.95 * wind.strength) * s;
      const p = Math.max(0.85, s);
      const hy = by + bobPx;

      ctx.strokeStyle = isNight ? 'rgba(130, 175, 224, 0.26)' : 'rgba(226, 246, 255, 0.42)';
      ctx.lineWidth = Math.max(0.8, 0.9 * p);
      ctx.beginPath();
      ctx.ellipse(bx, by + 1.8 * p, 6.4 * p, 2.3 * p, -0.15, 0, Math.PI * 2);
      ctx.stroke();

      ctx.fillStyle = shadeHex('#2c3a48', 0.9, mode);
      ctx.fillRect(Math.round(bx - 5.4 * p), Math.round(hy - 0.8 * p), Math.max(4, Math.round(10.8 * p)), Math.max(2, Math.round(3.6 * p)));
      ctx.fillStyle = shadeHex('#eef2f6', 1.04, mode);
      ctx.fillRect(Math.round(bx - 5.0 * p), Math.round(hy - 1.4 * p), Math.max(4, Math.round(10.0 * p)), Math.max(2, Math.round(3.0 * p)));
      ctx.fillStyle = shadeHex('#26384c', 0.95, mode);
      ctx.fillRect(Math.round(bx - 2.4 * p), Math.round(hy - 0.8 * p), Math.max(2, Math.round(4.4 * p)), Math.max(1.5, Math.round(1.6 * p)));

      const mastTopX = bx + swayPx;
      const mastTopY = hy - 18.0 * p;
      ctx.strokeStyle = shadeHex('#cbd5e1', 1.0, mode);
      ctx.lineWidth = Math.max(1.0, 1.05 * p);
      ctx.beginPath();
      ctx.moveTo(bx, hy - 1.2 * p);
      ctx.lineTo(mastTopX, mastTopY);
      ctx.stroke();
      ctx.strokeStyle = shadeHex('#f8fafc', 1.0, mode);
      ctx.lineWidth = Math.max(1.0, 1.2 * p);
      ctx.beginPath();
      ctx.moveTo(bx + swayPx * 0.25, hy - 5.0 * p);
      ctx.lineTo(bx - 4.8 * p + swayPx * 0.25, hy - 4.2 * p);
      ctx.stroke();

      // Leeward masthead pennant streaming in SW->NE wind direction
      const flutter = Math.sin(wind.wavePhase * 1.2 + idx * 1.9) * 0.9 * p;
      ctx.fillStyle = shadeHex(mb.pen, 1.05, mode);
      ctx.fillRect(Math.round(mastTopX), Math.round(mastTopY + flutter * 0.4), Math.max(2, Math.round(3.4 * p)), Math.max(1, Math.round(1.2 * p)));

      if (isNight) {
        const aSz = Math.max(1.5, 1.6 * p);
        ctx.fillStyle = 'rgba(255, 232, 163, 0.32)';
        ctx.beginPath();
        ctx.arc(mastTopX, mastTopY, Math.max(2.2, 2.8 * p), 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#ffe8a3';
        ctx.fillRect(Math.round(mastTopX - aSz * 0.5), Math.round(mastTopY - aSz * 0.5), Math.round(aSz), Math.round(aSz));
        ctx.fillStyle = 'rgba(255, 224, 140, 0.36)';
        ctx.fillRect(Math.round(bx + swayPx * 0.3 - aSz * 0.5), Math.round(by + 4.0 * p), Math.round(aSz), Math.max(1, Math.round(1.0 * p)));
      }
    }

    // 5 Graceful White Lake Zurich Mute Swans with V-Wake Trails
    const swanLoops = [
      { cu: 0.5960, cv: 0.5915, ru: 0.0042, rv: 0.0036, spd: 0.14, ph: 0.0 },
      { cu: 0.6005, cv: 0.5955, ru: 0.0038, rv: 0.0033, spd: 0.14, ph: 0.35 },
      { cu: 0.4400, cv: 0.7285, ru: 0.0036, rv: 0.0032, spd: 0.16, ph: 1.4 },
      { cu: 0.4440, cv: 0.7315, ru: 0.0034, rv: 0.0030, spd: 0.16, ph: 1.85 },
      { cu: 0.6960, cv: 0.5370, ru: 0.0040, rv: 0.0034, spd: 0.13, ph: 3.1 },
    ];
    for (const sw of swanLoops) {
      const ang = tSec * sw.spd + sw.ph;
      const su = sw.cu + Math.cos(ang) * sw.ru;
      const sv = sw.cv + Math.sin(ang) * sw.rv;
      if (!depthMgr.isWaterUV(su, sv)) continue;
      if (livingCounts) livingCounts.swans++;
      const sx = toX(su);
      const sy = toY(sv);
      if (!inView(sx, sy, 24)) continue;
      const vx = -Math.sin(ang) * sw.ru * worldW;
      const vy = Math.cos(ang) * sw.rv * worldH;
      const dir = vx >= 0 ? 1 : -1;
      const px = Math.max(1.0, 1.15 * s);
      drawWaterfowlWake(ctx, sx, sy, vx, vy, px, isNight, 1.0);
      ctx.fillStyle = isNight ? '#b8c8dc' : (isSunset ? '#fff0de' : '#ffffff');
      ctx.fillRect(Math.round(sx - 1.6 * px), Math.round(sy - 0.6 * px), Math.max(2, Math.round(3.2 * px)), Math.max(1.5, Math.round(1.6 * px)));
      ctx.fillRect(Math.round(sx + dir * 1.1 * px), Math.round(sy - 2.2 * px), Math.max(1, Math.round(1.1 * px)), Math.max(2, Math.round(2.0 * px)));
      ctx.fillStyle = '#f97316';
      ctx.fillRect(Math.round(sx + dir * 2.0 * px), Math.round(sy - 1.9 * px), Math.max(1, Math.round(0.9 * px)), Math.max(1, Math.round(0.7 * px)));
    }

    // 3 Lakeside Mallard Duck Pairs with Gentle V-Wake Trails (Day & Sunset)
    if (!isNight) {
      const duckPairs = [
        { cu: 0.5160, cv: 0.6540, ru: 0.0028, rv: 0.0024, spd: 0.18, ph: 0.4 },
        { cu: 0.6380, cv: 0.5650, ru: 0.0026, rv: 0.0022, spd: 0.16, ph: 2.2 },
        { cu: 0.7700, cv: 0.4700, ru: 0.0030, rv: 0.0025, spd: 0.15, ph: 4.1 },
      ];
      for (const dp of duckPairs) {
        for (let mate = 0; mate < 2; mate++) {
          const ang = tSec * dp.spd + dp.ph - mate * 0.28;
          const du = dp.cu + Math.cos(ang) * dp.ru;
          const dv = dp.cv + Math.sin(ang) * dp.rv;
          if (!depthMgr.isWaterUV(du, dv)) continue;
          if (livingCounts) livingCounts.ducks++;
          const dx = toX(du);
          const dy = toY(dv);
          if (!inView(dx, dy, 18)) continue;
          const vx = -Math.sin(ang) * dp.ru * worldW;
          const vy = Math.cos(ang) * dp.rv * worldH;
          const dir = vx >= 0 ? 1 : -1;
          const px = Math.max(0.9, 1.0 * s);
          drawWaterfowlWake(ctx, dx, dy, vx, vy, px, false, 0.78);
          if (mate === 0) {
            ctx.fillStyle = shadeHex('#78716c', 1.0, mode);
            ctx.fillRect(Math.round(dx - 1.2 * px), Math.round(dy - 0.5 * px), Math.max(2, Math.round(2.5 * px)), Math.max(1.2, Math.round(1.3 * px)));
            ctx.fillStyle = '#f8fafc';
            ctx.fillRect(Math.round(dx + dir * 0.8 * px), Math.round(dy - 1.0 * px), Math.max(1, Math.round(0.9 * px)), Math.max(1, Math.round(0.6 * px)));
            ctx.fillStyle = '#15803d';
            ctx.fillRect(Math.round(dx + dir * 0.9 * px), Math.round(dy - 1.8 * px), Math.max(1, Math.round(1.0 * px)), Math.max(1, Math.round(1.0 * px)));
          } else {
            ctx.fillStyle = shadeHex('#8c6a4a', 1.0, mode);
            ctx.fillRect(Math.round(dx - 1.1 * px), Math.round(dy - 0.5 * px), Math.max(2, Math.round(2.3 * px)), Math.max(1.2, Math.round(1.2 * px)));
            ctx.fillStyle = shadeHex('#6f5238', 1.0, mode);
            ctx.fillRect(Math.round(dx + dir * 0.8 * px), Math.round(dy - 1.5 * px), Math.max(1, Math.round(0.9 * px)), Math.max(1, Math.round(0.9 * px)));
          }
        }
      }
    }

    // 2 Slow Stand-Up Paddleboarders (~1.57-1.72 m/s) with Paddle-Stroke Ripple Rings (Day & Sunset)
    if (!isNight) {
      const sups = [
        { u0: 0.566, v0: 0.610, u1: 0.629, v1: 0.566, spd: 0.0024, ph: 0.15, board: '#38bdf8', shirt: '#f43f5e' },
        { u0: 0.446, v0: 0.730, u1: 0.506, v1: 0.675, spd: 0.0021, ph: 0.62, board: '#fbbf24', shirt: '#0d9488' },
      ];
      for (let i = 0; i < sups.length; i++) {
        const sp = sups[i];
        const phase = tSec * sp.spd * Math.PI * 2 + sp.ph * Math.PI * 2;
        const p = 0.5 + 0.5 * Math.sin(phase);
        const cosP = Math.cos(phase);
        const headingSign = cosP >= 0 ? 1 : -1;
        const speedMag = Math.abs(cosP);
        const su = sp.u0 + (sp.u1 - sp.u0) * p;
        const sv = sp.v0 + (sp.v1 - sp.v0) * p;
        if (!depthMgr.isWaterUV(su, sv)) continue;
        if (livingCounts) livingCounts.sups++;
        const sx = toX(su);
        const sy = toY(sv);
        if (!inView(sx, sy, 30)) continue;

        const rawDx = (sp.u1 - sp.u0) * worldW * scale;
        const rawDy = (sp.v1 - sp.v0) * worldH * scale;
        const len = Math.hypot(rawDx, rawDy) || 1;
        const tx = (rawDx / len) * headingSign;
        const ty = (rawDy / len) * headingSign;
        const ang = Math.atan2(ty, tx);
        const px = Math.max(1.0, 1.15 * s);

        if (speedMag > 0.08) {
          const wakeA = (0.44 * speedMag).toFixed(2);
          ctx.fillStyle = `rgba(232,248,255,${wakeA})`;
          for (let k = 0; k < 2; k++) {
            const dist = (5.2 + k * 2.4) * px;
            const wx = sx - tx * dist;
            const wy = sy - ty * dist;
            const wLen = (2.8 - k * 0.7) * px;
            ctx.fillRect(Math.round(wx - wLen * 0.5), Math.round(wy - 0.5 * px), Math.max(2, Math.round(wLen)), Math.max(1, Math.round(1.0 * px)));
          }
        }

        ctx.save();
        ctx.translate(sx, sy);
        ctx.rotate(ang);
        ctx.fillStyle = shadeHex(sp.board, 1.0, mode);
        ctx.beginPath();
        ctx.moveTo(-3.8 * px, -0.95 * px);
        ctx.lineTo(2.4 * px, -0.95 * px);
        ctx.lineTo(4.2 * px, 0);
        ctx.lineTo(2.4 * px, 0.95 * px);
        ctx.lineTo(-3.8 * px, 0.95 * px);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        drawMiniPerson(ctx, sx, sy - 0.5 * px, s * 0.88, shadeHex(sp.shirt, 1.0, mode), '#1e293b', hairs[i], false, 0, null, canvasW, canvasH);
        const strokePhase = tSec * 1.35 + i * 2.1;
        const stroke = Math.sin(strokePhase);
        const bladeX = sx + tx * (0.9 + stroke * 1.6) * px;
        const bladeY = sy + ty * (0.9 + stroke * 1.6) * px + 1.0 * px;
        ctx.strokeStyle = '#334155';
        ctx.lineWidth = Math.max(1.0, 0.9 * s);
        ctx.beginPath();
        ctx.moveTo(sx + tx * 0.5 * px, sy - 4.0 * px);
        ctx.lineTo(bladeX, bladeY);
        ctx.stroke();

        // Rhythmic paddle-stroke water ripple ring when blade dips
        const dipProg = (((strokePhase / (Math.PI * 2)) % 1) + 1) % 1;
        if (dipProg < 0.55) {
          const rp = dipProg / 0.55;
          const rRad = (1.1 + rp * 3.1) * px;
          ctx.strokeStyle = `rgba(232, 248, 255, ${((1 - rp) * 0.55).toFixed(2)})`;
          ctx.lineWidth = Math.max(0.75, 0.7 * px);
          ctx.beginPath();
          ctx.ellipse(bladeX, bladeY, rRad, rRad * 0.52, 0, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
    }

    // Slow Lakeside Wooden Rowboat / Skiff near Bendlikon-Sulzergut (~1.75 m/s, Day & Sunset, waterMask-strict)
    if (!isNight) {
      const rb = { u0: 0.618, v0: 0.566, u1: 0.678, v1: 0.522, spd: 0.0026, ph: 0.31 };
      const rPhase = tSec * rb.spd * Math.PI * 2 + rb.ph * Math.PI * 2;
      const rp = 0.5 + 0.5 * Math.sin(rPhase);
      const rCos = Math.cos(rPhase);
      const rSign = rCos >= 0 ? 1 : -1;
      const rSpeed = Math.abs(rCos);
      const ru = rb.u0 + (rb.u1 - rb.u0) * rp;
      const rv = rb.v0 + (rb.v1 - rb.v0) * rp;
      if (depthMgr.isWaterUV(ru, rv)) {
        const rx = toX(ru);
        const ry = toY(rv);
        if (inView(rx, ry, 36)) {
          const rawDx = (rb.u1 - rb.u0) * worldW * scale;
          const rawDy = (rb.v1 - rb.v0) * worldH * scale;
          const len = Math.hypot(rawDx, rawDy) || 1;
          const tx = (rawDx / len) * rSign;
          const ty = (rawDy / len) * rSign;
          const nx = -ty;
          const ny = tx;
          const ang = Math.atan2(ty, tx);
          const px = Math.max(1.0, 1.15 * s);

          // Delicate trailing V-wake behind stern
          if (rSpeed > 0.08) {
            ctx.fillStyle = `rgba(232, 248, 255, ${(0.44 * rSpeed).toFixed(2)})`;
            for (let k = 1; k <= 3; k++) {
              const dist = (4.8 + k * 2.5) * px;
              const spr = (0.8 + k * 1.1) * px;
              const sz = Math.max(1.2, Math.round((2.2 - k * 0.4) * px));
              ctx.fillRect(Math.round(rx - tx * dist + nx * spr), Math.round(ry - ty * dist + ny * spr), sz, Math.max(1, Math.round(0.9 * px)));
              ctx.fillRect(Math.round(rx - tx * dist - nx * spr), Math.round(ry - ty * dist - ny * spr), sz, Math.max(1, Math.round(0.9 * px)));
            }
          }

          // Cedar-wood pointed skiff hull + dark gunwale + twin sweeping oars
          const oarCycle = tSec * 1.9;
          const oarAng = Math.sin(oarCycle) * 0.55;
          ctx.save();
          ctx.translate(rx, ry);
          ctx.rotate(ang);
          ctx.fillStyle = shadeHex('#5c3318', 1.0, mode);
          ctx.beginPath();
          ctx.moveTo(6.0 * px, 0);
          ctx.lineTo(2.4 * px, -1.9 * px);
          ctx.lineTo(-4.6 * px, -1.6 * px);
          ctx.lineTo(-5.8 * px, 0);
          ctx.lineTo(-4.6 * px, 1.6 * px);
          ctx.lineTo(2.4 * px, 1.9 * px);
          ctx.closePath();
          ctx.fill();
          ctx.fillStyle = shadeHex('#a3683b', 1.02, mode);
          ctx.beginPath();
          ctx.moveTo(5.0 * px, 0);
          ctx.lineTo(2.0 * px, -1.3 * px);
          ctx.lineTo(-4.0 * px, -1.1 * px);
          ctx.lineTo(-4.8 * px, 0);
          ctx.lineTo(-4.0 * px, 1.1 * px);
          ctx.lineTo(2.0 * px, 1.3 * px);
          ctx.closePath();
          ctx.fill();

          // Twin wooden oars sweeping symmetrically
          ctx.strokeStyle = shadeHex('#d4a373', 1.0, mode);
          ctx.lineWidth = Math.max(0.9, 0.85 * px);
          const oarTipX = (-1.6 + oarAng * 3.8) * px;
          const oarTipY = 5.4 * px;
          ctx.beginPath();
          ctx.moveTo(0, -1.4 * px);
          ctx.lineTo(oarTipX, -oarTipY);
          ctx.moveTo(0, 1.4 * px);
          ctx.lineTo(oarTipX, oarTipY);
          ctx.stroke();

          // Oar-dip splash ripples
          const dipA = Math.max(0, Math.cos(oarCycle));
          if (dipA > 0.25) {
            ctx.strokeStyle = `rgba(232, 248, 255, ${(dipA * 0.52).toFixed(2)})`;
            ctx.lineWidth = Math.max(0.7, 0.65 * px);
            ctx.beginPath();
            ctx.arc(oarTipX, -oarTipY, (1.0 + (1 - dipA) * 1.8) * px, 0, Math.PI * 2);
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(oarTipX, oarTipY, (1.0 + (1 - dipA) * 1.8) * px, 0, Math.PI * 2);
            ctx.stroke();
          }
          ctx.restore();

          // Seated rower torso & head
          drawMiniPerson(ctx, rx, ry - 0.3 * px, s * 0.78, shadeHex('#e2e8f0', 1.0, mode), '#1e3a5f', hairs[1], false, 0, null, canvasW, canvasH);
        }
      }
    }
  }

  // =========================================================================
  // 5b. LEGACY SUNSET JOGGERS (fallback only) & WARM CAFE/TERRACE GLOWS
  // =========================================================================
  if (!hasDynamicPeds && isSunset && animData && animData.roads && scale >= 0.35) {
    const seeRd = animData.roads.find((r) => r.id === 'seestrasse_sb');
    if (seeRd && seeRd.pts && seeRd.pts.length > 10) {
      const joggers = [
        { f0: 0.36, f1: 0.52, spd: 0.0085, ph: 0.1, shirt: '#f97316' },
        { f0: 0.56, f1: 0.72, spd: 0.0078, ph: 0.55, shirt: '#38bdf8' },
        { f0: 0.42, f1: 0.60, spd: 0.0082, ph: 0.82, shirt: '#a3e635' },
      ];
      for (let ji = 0; ji < joggers.length; ji++) {
        const jg = joggers[ji];
        const jp = 0.5 + 0.5 * Math.sin(tSec * jg.spd * Math.PI * 2 + jg.ph * Math.PI * 2);
        const f = jg.f0 + (jg.f1 - jg.f0) * jp;
        const pos = samplePathAt(seeRd.pts, f, worldW, worldH, 3);
        if (!pos) continue;
        const isoY = 0.55;
        const gx = pos.tx;
        const gy = pos.ty / isoY;
        const gm = Math.hypot(gx, gy) || 1;
        const rx = -gy / gm;
        const ry = (gx / gm) * isoY;
        const jWx = pos.wx + rx * 5.6 * wScale;
        const jWy = pos.wy + ry * 5.6 * wScale;
        depthMgr.drawDepthMasked(ctx, cam, jWx, jWy, walkerBounds, pos.d16, worldW, worldH, (targetCtx) => {
          drawMiniPerson(
            targetCtx,
            offsetX + jWx * scale,
            offsetY + jWy * scale,
            s * 0.92,
            shadeHex(jg.shirt, 1.06, mode),
            '#1e293b',
            hairs[ji % hairs.length],
            false,
            tSec * 12.5 + ji * 1.7,
            null,
            canvasW,
            canvasH,
          );
        }, 2.0);
      }
    }
  }

  if (isSunset || isNight) {
    const cfCenter = (vig.cf_meyer_haus && vig.cf_meyer_haus.center) || [0.48102, 0.42361];
    const terraces = [
      { u: 0.5818, v: 0.5768, r: 16 },
      { u: 0.4068, v: 0.7072, r: 15 },
      { u: cfCenter[0], v: cfCenter[1], r: 17 },
    ];
    for (let ti = 0; ti < terraces.length; ti++) {
      const tc = terraces[ti];
      const tx = toX(tc.u);
      const ty = toY(tc.v);
      if (!inView(tx, ty, 36)) continue;
      const rad = tc.r * s;
      const grad = ctx.createRadialGradient(tx, ty, 1.5 * s, tx, ty, rad);
      grad.addColorStop(0, isNight ? 'rgba(255, 198, 112, 0.30)' : 'rgba(255, 198, 112, 0.24)');
      grad.addColorStop(0.55, isNight ? 'rgba(255, 184, 96, 0.12)' : 'rgba(255, 184, 96, 0.09)');
      grad.addColorStop(1, 'rgba(255, 180, 88, 0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.ellipse(tx, ty, rad * 1.15, rad * 0.72, 0, 0, Math.PI * 2);
      ctx.fill();
      if (isSunset && scale >= 0.45) {
        for (let g = 0; g < 2; g++) {
          const gu = tc.u + (g - 0.5) * 0.0011 + Math.sin(tSec * 0.3 + ti + g * 2.1) * 0.0002;
          const gv = tc.v + (g === 0 ? 0.0003 : -0.0002);
          drawMiniPerson(ctx, toX(gu), toY(gv), s * 0.86, shadeHex(coats[(ti * 2 + g) % coats.length], 1.0, mode), '#243040', hairs[(ti + g) % hairs.length], false, tSec * 1.4 + g, null, canvasW, canvasH);
        }
      }
    }
  }

  // =========================================================================
  // 6. BAHNHOF KILCHBERG — Warm Platform Lamps (+ fallback commuters if no pedSim)
  // =========================================================================
  const bhVig = vig.bahnhof_kilchberg || {
    plat_sw: [0.55049, 0.50304],
    plat_ne: [0.56449, 0.49558],
    footbridge: [[0.56281, 0.49120], [0.56679, 0.49719]],
  };
  const platSw = bhVig.plat_sw || [0.55049, 0.50304];
  const platNe = bhVig.plat_ne || [0.56449, 0.49558];
  const bhFb = bhVig.footbridge || [[0.56281, 0.49120], [0.56679, 0.49719]];
  if (boxInView(platSw[0] - 0.005, Math.min(platNe[1], bhFb[0][1]) - 0.004, Math.max(platNe[0], bhFb[1][0]) + 0.005, platSw[1] + 0.006)) {
    if (isNight || isSunset) {
      for (let l = 0; l < 5; l++) {
        const f = l / 4;
        const lu = platSw[0] + f * (platNe[0] - platSw[0]);
        const lv = platSw[1] + f * (platNe[1] - platSw[1]);
        const lx = toX(lu);
        const ly = toY(lv);
        if (!inView(lx, ly, 36)) continue;
        const gr = 14 * s;
        const grad = ctx.createRadialGradient(lx, ly, 1 * s, lx, ly, gr);
        grad.addColorStop(0, isNight ? 'rgba(255, 224, 146, 0.36)' : 'rgba(255, 214, 140, 0.18)');
        grad.addColorStop(1, 'rgba(255, 214, 140, 0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(lx, ly, gr, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    if (!hasDynamicPeds) {
      const nComm = isNight ? 4 : 8;
      const dPlatU = platNe[0] - platSw[0];
      const dPlatV = platNe[1] - platSw[1];
      for (let c = 0; c < nComm; c++) {
        const isSE = c % 2 === 1;
        const baseF = 0.12 + (c / nComm) * 0.78 + Math.sin(tSec * 0.25 + c * 1.9) * 0.04;
        const cu = (isSE ? platSw[0] + 0.0013 : platSw[0] - 0.0003) + baseF * dPlatU;
        const cv = (isSE ? platSw[1] + 0.0020 : platSw[1] + 0.0002) + baseF * dPlatV;
        const wx = cu * worldW;
        const wy = cv * worldH;
        const d16 = depthMgr.evalWalkerD16(wx, wy, 424.6, worldW, worldH, false);
        depthMgr.drawDepthMasked(ctx, cam, wx, wy, walkerBounds, d16, worldW, worldH, (targetCtx) => {
          drawMiniPerson(
            targetCtx,
            toX(cu), toY(cv), s * 0.92,
            shadeHex(coats[(c + 3) % coats.length], 1.0, mode),
            shadeHex('#1e293b', 1.0, mode),
            hairs[c % hairs.length],
            isNight,
            tSec * 3.0 + c * 1.5,
            c % 3 === 0 ? '#334155' : null,
            canvasW,
            canvasH,
          );
        }, 2.0);
      }
      for (let fb = 0; fb < 2; fb++) {
        const pf = 0.5 + 0.5 * Math.sin(tSec * (0.14 + fb * 0.04) + fb * 2.5);
        const fu = bhFb[0][0] + (bhFb[1][0] - bhFb[0][0]) * pf;
        const fv = bhFb[0][1] + (bhFb[1][1] - bhFb[0][1]) * pf;
        const wx = fu * worldW;
        const wy = fv * worldH;
        const d16 = depthMgr.evalWalkerD16(wx, wy, 428.0, worldW, worldH, true);
        depthMgr.drawDepthMasked(ctx, cam, wx, wy, walkerBounds, d16, worldW, worldH, (targetCtx) => {
          drawMiniPerson(targetCtx, toX(fu), toY(fv), s * 0.9, shadeHex(coats[fb + 4], 1.0, mode), '#27303f', hairs[fb + 1], isNight, tSec * 7.5 + fb, null, canvasW, canvasH);
        }, 2.0);
      }
    }
  }

  // =========================================================================
  // 7. NIGHTTIME STREETLAMP GLOWS ALONG 3 MAIN ARTERIES
  // =========================================================================
  if (isNight && animData && animData.roads) {
    if (!cachedLampRoads || cachedLampRoadsSrc !== animData) {
      cachedLampRoadsSrc = animData;
      cachedLampRoads = animData.roads.filter(
        (r) => r.id === 'seestrasse_sb' || r.id === 'dorfstrasse_viaduct_up' || r.id === 'alte_landstrasse_eb',
      );
    }
    for (const rd of cachedLampRoads) {
      const pts = rd.pts || [];
      const step = rd.id === 'seestrasse_sb' ? 28 : 26;
      for (let i = 10; i < pts.length - 10; i += step) {
        const sx = toX(pts[i][0]);
        const sy = toY(pts[i][1]);
        if (!inView(sx, sy, 24)) continue;
        const lr = Math.max(6, 12.5 * s);
        const grad = ctx.createRadialGradient(sx, sy, 0.5, sx, sy, lr);
        grad.addColorStop(0, 'rgba(255, 214, 128, 0.30)');
        grad.addColorStop(0.55, 'rgba(255, 190, 96, 0.11)');
        grad.addColorStop(1, 'rgba(255, 180, 80, 0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.ellipse(sx, sy, lr * 1.15, lr * 0.72, 0, 0, Math.PI * 2);
        ctx.fill();
        if (s >= 0.8) {
          const gSz = Math.max(1.5, Math.round(1.5 * s));
          ctx.fillStyle = 'rgba(255, 236, 176, 0.86)';
          ctx.fillRect(Math.round(sx - gSz * 0.5), Math.round(sy - 3.5 * s), gSz, gSz);
        }
      }
    }
  }

  ctx.restore();
}

/**
 * Open-lake glints, moonlit shimmer, harbor beacons, dual-track SBB signals,
 * canonically synced church bell acoustic ripples, fireflies, soaring Red Kites,
 * dusk/night residential living windows, and SW->NE drifting cloud shadows.
 */
export function drawAtmosphereAndLife(
  ctx,
  cam,
  depthMgr,
  animData,
  interactiveData,
  livingCounts,
  worldW,
  worldH,
  wScale,
  tSec,
  mode,
) {
  const { scale, offsetX, offsetY, width: canvasW, height: canvasH } = cam;
  const isNight = mode === 'night';
  const isSunset = mode === 'sunset';
  const s = scale * wScale;
  const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};
  const wind = getWindVector(tSec);

  ctx.save();

  // A. Open-Lake Sun / Moon Water Glints (waterMask-strict)
  if (depthMgr.isWaterMaskReady()) {
    const glintCol = isNight ? '#cddcf4' : (isSunset ? '#ffe2a8' : '#f4fbff');
    const px = Math.max(1.2, 1.5 * s);
    for (let i = 0; i < 96; i++) {
      const gu = 0.42 + hash01(i * 3.1 + 1) * 0.56;
      const gv = 0.34 + hash01(i * 5.7 + 2) * 0.62;
      if (!depthMgr.isWaterUV(gu, gv)) continue;
      const sx = gu * worldW * scale + offsetX;
      const sy = gv * worldH * scale + offsetY;
      if (sx < -8 || sx > canvasW + 8 || sy < -8 || sy > canvasH + 8) continue;
      const pulse = Math.sin(tSec * (1.8 + hash01(i * 9.3) * 2.2) + i * 2.41);
      if (pulse < 0.52) continue;
      const a = ((pulse - 0.52) / 0.48) * (isNight ? 0.44 : (isSunset ? 0.74 : 0.64));
      ctx.globalAlpha = a;
      ctx.fillStyle = glintCol;
      const rx = Math.round(sx);
      const ry = Math.round(sy);
      ctx.fillRect(rx - Math.round(px), ry, Math.max(2, Math.round(px * 2.4)), Math.max(1, Math.round(px * 0.75)));
      if (pulse > 0.82) {
        ctx.fillRect(rx, ry - Math.round(px * 0.6), Math.max(1, Math.round(px * 0.8)), Math.max(2, Math.round(px * 2.0)));
      }
    }
  }

  // A2. Nighttime Moonlit Water Shimmer Band
  if (isNight && depthMgr.isWaterMaskReady()) {
    ctx.globalAlpha = 1.0;
    for (let i = 0; i < 32; i++) {
      const f = i / 31;
      const spread = (hash01(i * 13.7 + 5) - 0.5) * 0.042;
      const mu = 0.74 - f * 0.18 + spread + Math.sin(tSec * 1.4 + i * 1.7) * 0.0025;
      const mv = 0.54 + f * 0.24 + (hash01(i * 7.3 + 9) - 0.5) * 0.012;
      if (!depthMgr.isWaterUV(mu, mv)) continue;
      const sx = mu * worldW * scale + offsetX;
      const sy = mv * worldH * scale + offsetY;
      if (sx < -24 || sx > canvasW + 24 || sy < -10 || sy > canvasH + 10) continue;
      const pulse = 0.35 + 0.65 * Math.pow(0.5 + 0.5 * Math.sin(tSec * 2.1 + i * 2.3), 2.0);
      const wPx = Math.max(3, Math.round((5.5 + hash01(i * 4.1) * 7.0) * s));
      const hPx = Math.max(1, Math.round(1.3 * s));
      ctx.globalAlpha = pulse * 0.54;
      ctx.fillStyle = (i % 3 === 0) ? '#dbeafe' : '#93c5fd';
      ctx.fillRect(Math.round(sx - wPx * 0.5), Math.round(sy), wPx, hPx);
    }
  }

  // B. Harbor Navigation Beacons (Bendlikon & Seebad)
  ctx.globalAlpha = 1.0;
  if (isNight || isSunset) {
    const bpBeacon = (vig.bendlikon_pier && vig.bendlikon_pier.beacon) || [0.58700, 0.57838];
    const sbBeacon = (vig.seebad_kilchberg && vig.seebad_kilchberg.beacon) || [0.42221, 0.72359];
    const piers = [
      { u: bpBeacon[0], v: bpBeacon[1], col: '#ffb84d', glow: 'rgba(255,184,77,0.32)', freq: 1.4 },
      { u: sbBeacon[0], v: sbBeacon[1], col: '#6ee7b7', glow: 'rgba(110,231,183,0.30)', freq: 1.9 },
    ];
    for (const p of piers) {
      const sx = p.u * worldW * scale + offsetX;
      const sy = p.v * worldH * scale + offsetY;
      if (sx < -32 || sx > canvasW + 32 || sy < -32 || sy > canvasH + 32) continue;
      const blink = 0.45 + 0.55 * Math.pow(0.5 + 0.5 * Math.sin(tSec * p.freq), 2.5);
      const r = Math.max(3.5, 5.5 * s);
      ctx.globalAlpha = (isNight ? 0.85 : 0.48) * blink;
      ctx.fillStyle = p.glow;
      ctx.beginPath();
      ctx.arc(sx, sy, r * 1.9, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = (isNight ? 0.98 : 0.68) * blink;
      ctx.fillStyle = p.col;
      const dot = Math.max(2, Math.round(2.2 * s));
      ctx.fillRect(Math.round(sx - dot * 0.5), Math.round(sy - dot * 0.5), dot, dot);
      if (isNight) {
        for (let k = 1; k <= 4; k++) {
          const waveX = Math.sin(tSec * 3.1 + k * 1.7) * 1.4 * s;
          ctx.globalAlpha = (0.38 - k * 0.07) * blink;
          ctx.fillRect(Math.round(sx + waveX - dot * 0.5), Math.round(sy + k * 2.8 * s), dot, Math.max(1, Math.round(1.2 * s)));
        }
      }
    }
  }

  // C. Dual-Track Bahnhof Kilchberg SBB Typ L/N Railway Signals
  ctx.globalAlpha = 1.0;
  {
    const bhVig = vig.bahnhof_kilchberg || {};
    const nbAnchor = bhVig.signal || [0.56849, 0.49218];
    const platSw = bhVig.plat_sw || [0.55049, 0.50304];
    const sbAnchor = [platSw[0] - 0.0045, platSw[1] + 0.0012];
    const trackSignals = [
      { trId: 'sbb_ic_north', u: nbAnchor[0], v: nbAnchor[1] },
      { trId: 'sbb_s8_south', u: sbAnchor[0], v: sbAnchor[1] },
    ];
    for (const sig of trackSignals) {
      const sx = sig.u * worldW * scale + offsetX;
      const sy = sig.v * worldH * scale + offsetY;
      if (sx <= -24 || sx >= canvasW + 24 || sy <= -24 || sy >= canvasH + 24) continue;
      const tr = (animData.trains || []).find((t) => t.id === sig.trId);
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
      const sigGlow = aspect === 'red' ? 'rgba(255,59,59,0.34)' : (aspect === 'amber' ? 'rgba(251,191,36,0.32)' : 'rgba(34,229,132,0.30)');
      const lensOffY = aspect === 'green' ? -1.4 * s : (aspect === 'amber' ? 0 : 1.4 * s);
      const dot = Math.max(1.8, 1.8 * s);

      ctx.globalAlpha = 0.88;
      ctx.fillStyle = isNight ? '#475569' : '#1e293b';
      ctx.fillRect(Math.round(sx - 0.5 * s), Math.round(sy + 1.5 * s), Math.max(1, Math.round(1.0 * s)), Math.max(3, Math.round(5.0 * s)));
      const hoodW = Math.max(2.6, 2.4 * s);
      const hoodH = Math.max(4.6, 4.8 * s);
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(Math.round(sx - hoodW * 0.5), Math.round(sy - hoodH * 0.5), Math.round(hoodW), Math.round(hoodH));
      ctx.strokeStyle = isNight ? '#64748b' : '#cbd5e1';
      ctx.lineWidth = Math.max(0.6, 0.5 * s);
      ctx.strokeRect(Math.round(sx - hoodW * 0.5), Math.round(sy - hoodH * 0.5), Math.round(hoodW), Math.round(hoodH));

      const ly = sy + lensOffY;
      if (isNight || isSunset) {
        ctx.globalAlpha = isNight ? 0.86 : 0.48;
        ctx.fillStyle = sigGlow;
        ctx.beginPath();
        ctx.arc(sx, ly, dot * 2.6, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = isNight ? 0.98 : 0.90;
      ctx.fillStyle = sigCol;
      ctx.fillRect(Math.round(sx - dot * 0.5), Math.round(ly - dot * 0.5), Math.max(2, Math.round(dot)), Math.max(2, Math.round(dot)));
    }
  }

  // D. Swiss Church Bell Acoustic Ripples (exact unison with schedule.js evalBellState & audio.js)
  ctx.globalAlpha = 1.0;
  const bellSt = evalBellState(tSec, mode);
  if (bellSt.ringing) {
    const bellEnv = bellSt.envelope;
    const spires = [
      (vig.reformierte_kirche && vig.reformierte_kirche.belfry) || [0.29037, 0.31203],
      (vig.st_elisabeth && vig.st_elisabeth.belfry) || [0.41165, 0.32675],
    ];
    ctx.strokeStyle = isSunset ? '#ffd89b' : '#fff3c4';
    ctx.lineWidth = Math.max(1.0, 1.2 * s);
    for (let si = 0; si < spires.length; si++) {
      const sx = spires[si][0] * worldW * scale + offsetX;
      const sy = spires[si][1] * worldH * scale + offsetY;
      if (sx < -80 || sx > canvasW + 80 || sy < -80 || sy > canvasH + 80) continue;
      for (let rIdx = 0; rIdx < 2; rIdx++) {
        const phase = (((bellSt.cycle * 0.48 + rIdx * 0.5 + si * 0.25) % 1) + 1) % 1;
        const rad = (5 + phase * 26) * s;
        ctx.globalAlpha = (1 - phase) * 0.34 * bellEnv;
        ctx.beginPath();
        ctx.ellipse(sx, sy, rad, rad * 0.62, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
  }

  // E. Nighttime Park Fireflies
  ctx.globalAlpha = 1.0;
  if (isNight) {
    const dot = Math.max(1.5, 1.4 * s);
    for (let i = 0; i < 36; i++) {
      const g = FIREFLY_GROVES[i % FIREFLY_GROVES.length];
      const baseU = g[0] + (hash01(i * 4.3 + 7) - 0.5) * 0.045;
      const baseV = g[1] + (hash01(i * 6.1 + 3) - 0.5) * 0.045;
      const fu = baseU + Math.sin(tSec * 0.35 + i * 2.1) * 0.0045;
      const fv = baseV + Math.cos(tSec * 0.42 + i * 1.7) * 0.0038;
      const sx = fu * worldW * scale + offsetX;
      const sy = fv * worldH * scale + offsetY;
      if (sx < -10 || sx > canvasW + 10 || sy < -10 || sy > canvasH + 10) continue;
      const glow = Math.pow(0.5 + 0.5 * Math.sin(tSec * (1.5 + hash01(i * 2.9) * 1.6) + i * 3.7), 3.0);
      if (glow < 0.15) continue;
      ctx.globalAlpha = glow * 0.84;
      ctx.fillStyle = '#ffe57f';
      ctx.fillRect(Math.round(sx), Math.round(sy), Math.max(1.5, Math.round(dot)), Math.max(1.5, Math.round(dot)));
    }
  }

  // E2. 2 Graceful Soaring Red Kites (Rotmilan) circling wooded ridges (Day & Alpenglow)
  ctx.globalAlpha = 1.0;
  if (!isNight) {
    const redKites = [
      { cu: 0.655, cv: 0.285, ru: 0.024, rv: 0.014, spd: 0.16, ph: 0.2 },
      { cu: 0.315, cv: 0.305, ru: 0.022, rv: 0.013, spd: 0.14, ph: 3.6 },
    ];
    for (let ki = 0; ki < redKites.length; ki++) {
      const rk = redKites[ki];
      const ang = tSec * rk.spd + rk.ph;
      const ku = rk.cu + Math.cos(ang) * rk.ru;
      const kv = rk.cv + Math.sin(ang) * rk.rv;
      if (livingCounts) livingCounts.redKites++;
      const sx = ku * worldW * scale + offsetX;
      const sy = kv * worldH * scale + offsetY;
      if (sx < -36 || sx > canvasW + 36 || sy < -36 || sy > canvasH + 36) continue;
      const dx = -Math.sin(ang) * rk.ru * worldW;
      const dy = Math.cos(ang) * rk.rv * worldH;
      const flightAng = Math.atan2(dy, dx);
      const wingBeat = Math.sin(tSec * 2.2 + ki * 2.5) > 0.82 ? Math.sin(tSec * 12.0 + ki) * 1.2 : 0;
      const p = Math.max(0.85, s);

      ctx.save();
      ctx.translate(sx + 8 * p, sy + 14 * p);
      ctx.rotate(flightAng);
      ctx.fillStyle = 'rgba(18, 26, 22, 0.14)';
      ctx.beginPath();
      ctx.moveTo(4.0 * p, 0);
      ctx.lineTo(-0.5 * p, -6.5 * p);
      ctx.lineTo(-2.5 * p, -1.5 * p);
      ctx.lineTo(-5.5 * p, 0);
      ctx.lineTo(-2.5 * p, 1.5 * p);
      ctx.lineTo(-0.5 * p, 6.5 * p);
      ctx.closePath();
      ctx.fill();
      ctx.restore();

      ctx.save();
      ctx.translate(sx, sy);
      ctx.rotate(flightAng);
      const span = (6.8 + wingBeat * 0.4) * p;
      ctx.fillStyle = isSunset ? '#b24b2c' : '#9a3b22';
      ctx.beginPath();
      ctx.moveTo(3.6 * p, 0);
      ctx.lineTo(0.8 * p, -span);
      ctx.lineTo(-2.0 * p, -span * 0.72);
      ctx.lineTo(-1.8 * p, 0);
      ctx.lineTo(-2.0 * p, span * 0.72);
      ctx.lineTo(0.8 * p, span);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = isSunset ? '#c95830' : '#b44524';
      ctx.beginPath();
      ctx.moveTo(-1.4 * p, -0.8 * p);
      ctx.lineTo(-5.6 * p, -2.0 * p);
      ctx.lineTo(-4.0 * p, 0);
      ctx.lineTo(-5.6 * p, 2.0 * p);
      ctx.lineTo(-1.4 * p, 0.8 * p);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = isSunset ? '#f6e0c8' : '#e8d5c0';
      ctx.fillRect(Math.round(-0.4 * p), Math.round(-span * 0.65), Math.max(1.2, Math.round(1.4 * p)), Math.max(1.2, Math.round(1.8 * p)));
      ctx.fillRect(Math.round(-0.4 * p), Math.round(span * 0.45), Math.max(1.2, Math.round(1.4 * p)), Math.max(1.2, Math.round(1.8 * p)));
      ctx.fillStyle = '#1e1b18';
      ctx.fillRect(Math.round(-0.8 * p), Math.round(-span - 0.4 * p), Math.max(1.2, Math.round(1.6 * p)), Math.max(1.2, Math.round(1.6 * p)));
      ctx.fillRect(Math.round(-0.8 * p), Math.round(span - 1.2 * p), Math.max(1.2, Math.round(1.6 * p)), Math.max(1.2, Math.round(1.6 * p)));
      ctx.restore();
    }
  }

  // E3. Subtle Dusk & Night Residential Living Windows (deterministic, viewport-culled)
  if ((isSunset || isNight) && s >= 0.24 && interactiveData) {
    const wins = getLivingWindows(interactiveData);
    const wPx = Math.max(1.5, Math.round(1.8 * s));
    const hPx = Math.max(1.2, Math.round(1.4 * s));
    const thresh = isNight ? -0.35 : 0.22;
    for (let i = 0; i < wins.length; i++) {
      const wn = wins[i];
      if (isSunset && wn.sunsetBias > 0.52) continue;
      const sx = wn.u * worldW * scale + offsetX;
      const sy = wn.v * worldH * scale + offsetY;
      if (sx < -16 || sx > canvasW + 16 || sy < -16 || sy > canvasH + 16) continue;
      const wave = Math.sin((tSec / wn.period) * Math.PI * 2 + wn.phase);
      if (wave < thresh) continue;
      const tNorm = Math.min(1, (wave - thresh) / 0.28);
      const smooth = tNorm * tNorm * (3 - 2 * tNorm);
      const baseAlpha = isNight ? 0.72 : 0.44;
      const alpha = baseAlpha * smooth;
      if (isNight && s >= 1.0) {
        ctx.globalAlpha = alpha * 0.24;
        ctx.fillStyle = wn.col;
        ctx.beginPath();
        ctx.arc(sx, sy, 3.2 * s, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = alpha;
      ctx.fillStyle = wn.col;
      ctx.fillRect(Math.round(sx - wPx * 0.5), Math.round(sy - hPx * 0.5), wPx, hPx);
    }
  }

  // F. Soft Drifting Swiss Cloud Shadows (aligned with unified SW->NE wind vector)
  ctx.globalAlpha = 1.0;
  if (!isNight) {
    const cloudCol = isSunset ? 'rgba(34, 24, 52, 0.062)' : 'rgba(22, 38, 66, 0.052)';
    ctx.fillStyle = cloudCol;
    const windSpeedMul = 0.85 + 0.15 * wind.strength;
    for (let c = 0; c < 6; c++) {
      const cu = (((tSec * 0.0042 * windSpeedMul + c * 0.19 + hash01(c * 11.3) * 0.08) % 1.35) + 1.35) % 1.35 - 0.18;
      const cv = 0.16 + (c % 3) * 0.24 + Math.sin(tSec * 0.05 + c) * 0.03 - cu * 0.24;
      const sx = cu * worldW * scale + offsetX;
      const sy = cv * worldH * scale + offsetY;
      const rx = (340 + (c % 3) * 140) * scale * wScale;
      const ry = rx * 0.42;
      if (sx + rx < 0 || sx - rx > canvasW || sy + ry < 0 || sy - ry > canvasH) continue;
      ctx.beginPath();
      ctx.ellipse(sx, sy, rx, ry, -0.28, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  ctx.restore();
}
