/**
 * Village Atmosphere, Fountains, Vineyards, Laundry, Living Windows & Night Sky Plugin (Kilchberg v13.0).
 *
 * Layers:
 *   - 'ground_y' (depthMasked: true, extraVertPx: 2.0):
 *       * Terraced vineyard workers tending Alte Landstrasse slopes (day & sunset, inspectable)
 *       * Shimmering Dorfbrunnen village fountains (water arcs + concentric ripples)
 *   - 'air':
 *       * Swiss flags (skipping fIdx === 3 Gemeindehaus duplicate)
 *       * Lindt Hochkamin steam plume (SW->NE wind-coherent)
 *       * Village chimney smoke curls (sunset & night)
 *       * Fluttering wind-synced Swiss village laundry lines (day & sunset)
 *       * Nighttime park fireflies across 12 Kilchberg groves
 *   - 'overlay':
 *       * Upgraded living apartment windows (warm amber + subtle flickering blue-white TV glow + curtains)
 *       * Nighttime streetlamp glows along 3 main arteries + orbiting streetlamp moths
 *       * Harbor navigation beacons (Bendlikon Pier & Seebad)
 *       * SW->NE drifting Swiss cloud shadows (day & sunset)
 *
 * 100% deterministic seeded rendering, cached glow sprites, pure vector/pixel geometry.
 * Counts reported under livingCounts (vineyardWorkers, fireflies, laundryLines), NEVER simStats.pedestrians.
 */

import { hashCoords } from '../../sim/rng.js';
import { drawPixelRectWorld, shadeHex } from '../../render/vehicles.js';
import {
  blitGlow,
  drawMiniPersonV2,
  drawSmokePuffs,
  drawSwissOrMuniFlag,
  drawWaterRipples,
} from '../draw.js';

function hash01(n) {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

const FIREFLY_GROVES = [
  [0.24, 0.42], [0.27, 0.34], [0.33, 0.48], [0.39, 0.65],
  [0.44, 0.63], [0.51, 0.56], [0.56, 0.53], [0.64, 0.49],
  [0.71, 0.43], [0.77, 0.37], [0.47, 0.41], [0.35, 0.32],
];

// Terraced vineyard workers on sunny Alte Landstrasse / Schooren slopes (day & sunset)
const VINEYARD_WORKERS = [
  { id: 'vineyard:alte_landstrasse_1', u0: 0.4680, v0: 0.4380, u1: 0.4735, v1: 0.4342, spd: 0.045, ph: 0.12, coat: '#4d7c0f', hat: '#d6b87c' },
  { id: 'vineyard:alte_landstrasse_2', u0: 0.4750, v0: 0.4415, u1: 0.4805, v1: 0.4378, spd: 0.038, ph: 0.56, coat: '#b45309', hat: '#e2c98d' },
  { id: 'vineyard:schooren_slope', u0: 0.3910, v0: 0.5620, u1: 0.3960, v1: 0.5585, spd: 0.042, ph: 0.81, coat: '#2563eb', hat: '#d6b87c' },
];

// Charming wind-synced Swiss village garden laundry lines (day & sunset)
const LAUNDRY_LINES = [
  { u0: 0.5190, v0: 0.3940, u1: 0.5228, v1: 0.3924, cols: ['#f8fafc', '#93c5fd', '#fca5a5', '#fef3c7'] },
  { u0: 0.4540, v0: 0.4650, u1: 0.4576, v1: 0.4634, cols: ['#ffffff', '#cbd5e1', '#86efac', '#f8fafc'] },
  { u0: 0.5980, v0: 0.3620, u1: 0.6016, v1: 0.3604, cols: ['#fef9c3', '#f8fafc', '#bfdbfe', '#fda4af'] },
];

export function createAtmospherePlugin() {
  let cachedLampRoadsSrc = null;
  let cachedLampRoads = null;
  let cachedWindowSrc = null;
  let cachedLivingWindows = null;
  let counts = { vineyardWorkers: 0, fireflies: 0, laundryLines: 0 };
  let cachedInspectables = [];

  function getLivingWindows(meta) {
    if (!meta || !Array.isArray(meta.buildings)) return [];
    if (cachedWindowSrc === meta && cachedLivingWindows) return cachedLivingWindows;

    const palette = ['#ffd88a', '#ffca72', '#ffe6b3', '#ffd27d', '#ffde99', '#c8dcf8'];
    const list = [];
    for (let i = 0; i < meta.buildings.length; i++) {
      const b = meta.buildings[i];
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
        const isTv = cIdx === 5 || ((hw >>> 20) & 0x07) === 0;
        const hasCurtain = ((hw >>> 12) & 0x03) === 0;
        const du = (uNorm - 0.5) * 0.00066 + (w === 1 ? 0.00020 : -0.00008);
        const dv = 0.00016 + vNorm * 0.00038;
        list.push({
          u: b.u + du,
          v: b.v + dv,
          col: isTv ? '#c4dfff' : palette[cIdx],
          isTv,
          hasCurtain,
          period: 48.0 + pNorm * 64.0,
          phase: (uNorm * 6.28318) + w * 1.9,
          sunsetBias: vNorm,
        });
      }
    }
    cachedWindowSrc = meta;
    cachedLivingWindows = list;
    return list;
  }

  return {
    id: 'atmosphere',
    name: 'Village Atmosphere, Fountains, Vineyards, Living Windows & Night Sky',
    category: 'atmosphere',
    layers: ['ground_y', 'air', 'overlay'],
    priority: 50,
    enabledByDefault: true,

    init(ctx) {
      cachedLampRoadsSrc = null;
      cachedLampRoads = null;
      cachedWindowSrc = null;
      cachedLivingWindows = null;
      if (ctx && ctx.meta) getLivingWindows(ctx.meta);
      counts = { vineyardWorkers: 0, fireflies: 0, laundryLines: 0 };
      cachedInspectables = [];
    },

    getDrawables(cam, ctx) {
      const { animData, meta, depthMgr, worldW, worldH, wScale, tSec, mode, isNight, isSunset, s, wind } = ctx;
      const amb = (animData && animData.ambient) || {};
      const vig = amb.vignettes || {};
      const walkerBounds = { ex: 4.5 * wScale, eyUp: 9.5 * wScale, eyDn: 3.5 * wScale };

      const drawables = [];
      const inspectables = [];
      counts = {
        vineyardWorkers: isNight ? 0 : VINEYARD_WORKERS.length,
        fireflies: isNight ? 36 : 0,
        laundryLines: isNight ? 0 : LAUNDRY_LINES.length,
      };

      // ── 1. GROUND_Y: Terraced Vineyard Workers (Day & Sunset, depth-masked, inspectable) ──
      if (!isNight && s >= 0.35) {
        for (let vi = 0; vi < VINEYARD_WORKERS.length; vi++) {
          const vw = VINEYARD_WORKERS[vi];
          const p = 0.5 + 0.5 * Math.sin(tSec * vw.spd * Math.PI * 2 + vw.ph * Math.PI * 2);
          const u = vw.u0 + (vw.u1 - vw.u0) * p;
          const v = vw.v0 + (vw.v1 - vw.v0) * p;
          const wx = u * worldW;
          const wy = v * worldH;

          inspectables.push({
            kind: 'vignette',
            id: vw.id,
            wx,
            wy,
            radiusCss: 10,
            title: 'Kilchberg Vineyard Tender · Terraced Slopes',
            sub: 'Tending sunlit Zürichsee vine rows along Alte Landstrasse',
            specs: [
              ['Activity', 'Vineyard Care & Pruning'],
              ['Slope', 'Alte Landstrasse Terraces'],
              ['Varietal', 'Riesling-Silvaner & Räuschling'],
              ['Exposure', 'SE Lake Zurich Hillside'],
            ],
          });

          if (!ctx.boxInView(u - 0.004, v - 0.004, u + 0.004, v + 0.004)) continue;
          const d16 = depthMgr && depthMgr.evalWalkerD16
            ? depthMgr.evalWalkerD16(wx, wy, 448.0, worldW, worldH, false)
            : 0;
          const coat = shadeHex(vw.coat, 1.0, mode);
          const hat = shadeHex(vw.hat, 1.0, mode);
          drawables.push({
            layer: 'ground_y',
            sortY: wy,
            depthMasked: !!(depthMgr && d16),
            wx,
            wy,
            bounds: walkerBounds,
            d16,
            extraVertPx: 2.0,
            draw(targetCtx) {
              drawMiniPersonV2(targetCtx, ctx.toX(u), ctx.toY(v), s * 0.88, {
                coatCol: coat,
                pantsCol: '#334155',
                hairCol: '#3a3430',
                hatCol: hat,
                bagCol: '#854d0e',
                isNight: false,
                phase: tSec * 3.8 + vi * 2.1,
                canvasW: cam.width,
                canvasH: cam.height,
              });
            },
          });
        }
      }

      // ── 2. GROUND_Y / AIR: Shimmering Dorfbrunnen Village Fountains ──
      if (s >= 0.30 && Array.isArray(amb.fountains) && amb.fountains.length > 0) {
        drawables.push({
          layer: 'air',
          sortY: 0.45 * worldH,
          draw(targetCtx) {
            const fts = amb.fountains;
            targetCtx.save();
            for (let fi = 0; fi < fts.length; fi++) {
              const ft = fts[fi];
              const sx = ctx.toX(ft.u);
              const sy = ctx.toY(ft.v);
              if (!ctx.inView(sx, sy, 32)) continue;
              const basinCol = isNight ? '#2d6488' : (isSunset ? '#5aaec4' : '#42b8d8');
              const jetCol = isNight ? '#93c5fd' : (isSunset ? '#ffe4c8' : '#e8fbff');
              const dropCol = isNight ? '#60a5fa' : '#7dd3fc';
              targetCtx.fillStyle = basinCol;
              targetCtx.fillRect(Math.round(sx - 2.2 * s), Math.round(sy - 1.1 * s), Math.max(3, Math.round(4.5 * s)), Math.max(2, Math.round(2.4 * s)));
              drawWaterRipples(targetCtx, sx, sy, s, tSec, {
                count: 2,
                speed: 0.85,
                phaseOff: fi * 0.37,
                minR: 1.1,
                maxR: 3.4,
                isNight,
                isSunset,
                alpha: isNight ? 0.45 : 0.65,
              });
              const jetH = (3.2 + 0.6 * Math.sin(tSec * 6.5 + fi * 2.1)) * s;
              targetCtx.fillStyle = jetCol;
              targetCtx.fillRect(Math.round(sx - 0.5 * s), Math.round(sy - jetH), Math.max(1, Math.round(1.1 * s)), Math.max(2, Math.round(jetH)));
              targetCtx.fillStyle = dropCol;
              for (let d = 0; d < 3; d++) {
                const dp = (((tSec * 2.4 + fi * 0.4 + d / 3) % 1) + 1) % 1;
                const dx = (d - 1) * (1.2 + dp * 1.4) * s;
                const dy = -jetH * (1 - dp * dp) - Math.sin(dp * Math.PI) * 1.4 * s;
                const dSz = Math.max(1, Math.round(1.0 * s));
                targetCtx.fillRect(Math.round(sx + dx), Math.round(sy + dy), dSz, dSz);
              }
            }
            targetCtx.restore();
          },
        });
      }

      // ── 3. AIR: Swiss Flags (skipping fIdx === 3 Gemeindehaus duplicate), Hochkamin Steam, Village Chimneys, Laundry Lines & Fireflies ──
      drawables.push({
        layer: 'air',
        sortY: 0.5 * worldH,
        draw(targetCtx) {
          // 3a. Swiss flags (skip fIdx === 3; Gemeindehaus dual flags render in landmarks.js)
          const flags = amb.swiss_flags || [];
          for (let fIdx = 0; fIdx < flags.length; fIdx++) {
            if (fIdx === 3) continue;
            const fl = flags[fIdx];
            const fx = ctx.toX(fl.uv[0]);
            const fy = ctx.toY(fl.uv[1]);
            if (!ctx.inView(fx, fy, 36)) continue;
            drawSwissOrMuniFlag(targetCtx, fx, fy, s, tSec, wind, 'swiss', { isNight, phaseIdx: fIdx });
          }

          // 3b. Lindt Hochkamin steam plume drifting along unified SW->NE breeze
          if (amb.chimney_steam) {
            const stUv = amb.chimney_steam.uv;
            const cxWorld = stUv[0] * worldW;
            const cyWorld = stUv[1] * worldH;
            if (ctx.inView(ctx.toX(stUv[0]), ctx.toY(stUv[1]), 96)) {
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
                drawPixelRectWorld(targetCtx, cam, pxWorld - sz * 0.48 * wScale, pyWorld - sz * 0.25 * wScale, sz, sz * 0.68, shadeCol, wScale);
                drawPixelRectWorld(targetCtx, cam, pxWorld - sz * 0.56 * wScale, pyWorld - sz * 0.50 * wScale, sz * 0.82, sz * 0.52, litCol, wScale);
              }
            }
          }

          // 3c. Village chimney smoke curls (sunset & night)
          if ((isSunset || isNight) && s >= 0.22 && Array.isArray(amb.village_chimneys)) {
            const chimneys = amb.village_chimneys;
            for (let ci = 0; ci < chimneys.length; ci++) {
              const c = chimneys[ci];
              const sx = ctx.toX(c.u);
              const sy = ctx.toY(c.v);
              if (!ctx.inView(sx, sy, 48)) continue;
              drawSmokePuffs(targetCtx, sx, sy, s, tSec, wind, {
                count: 4,
                rate: 0.22,
                phaseOff: c.phase || 0,
                drift: 15,
                rise: 19,
                baseSz: 1.4,
                growSz: 3.2,
                isNight,
                isSunset,
                alpha: isNight ? 0.36 : 0.44,
              });
            }
          }

          // 3d. New v13.0 Fluttering Wind-Synced Village Laundry Lines (day & sunset)
          if (!isNight && s >= 0.55) {
            for (let li = 0; li < LAUNDRY_LINES.length; li++) {
              const ln = LAUNDRY_LINES[li];
              const x0 = ctx.toX(ln.u0);
              const y0 = ctx.toY(ln.v0);
              const x1 = ctx.toX(ln.u1);
              const y1 = ctx.toY(ln.v1);
              if (!ctx.inView(x0, y0, 32) && !ctx.inView(x1, y1, 32)) continue;
              const sag = 1.6 * s;
              targetCtx.strokeStyle = 'rgba(71, 85, 105, 0.58)';
              targetCtx.lineWidth = Math.max(0.7, 0.45 * s);
              targetCtx.beginPath();
              targetCtx.moveTo(x0, y0 - 2.2 * s);
              targetCtx.quadraticCurveTo(0.5 * (x0 + x1), 0.5 * (y0 + y1) - 2.2 * s + sag, x1, y1 - 2.2 * s);
              targetCtx.stroke();

              for (let ci = 0; ci < ln.cols.length; ci++) {
                const ft = (ci + 0.65) / (ln.cols.length + 0.3);
                const omt = 1 - ft;
                const gx = omt * omt * x0 + 2 * omt * ft * (0.5 * (x0 + x1)) + ft * ft * x1;
                const gy = omt * omt * (y0 - 2.2 * s) + 2 * omt * ft * (0.5 * (y0 + y1) - 2.2 * s + sag) + ft * ft * (y1 - 2.2 * s);
                const sway = Math.sin(wind.wavePhase * 1.15 + li * 1.9 + ci * 1.3) * 0.9 * wind.strength * s;
                const gw = Math.max(1.5, Math.round(1.6 * s));
                const gh = Math.max(2, Math.round(2.1 * s));
                targetCtx.fillStyle = shadeHex(ln.cols[ci], 1.0, mode);
                targetCtx.fillRect(Math.round(gx + sway * 0.4 - gw * 0.5), Math.round(gy), gw, gh);
              }
            }
          }

          // 3e. Nighttime Park Fireflies
          if (isNight) {
            const dot = Math.max(1.5, 1.4 * s);
            targetCtx.save();
            for (let i = 0; i < 36; i++) {
              const g = FIREFLY_GROVES[i % FIREFLY_GROVES.length];
              const baseU = g[0] + (hash01(i * 4.3 + 7) - 0.5) * 0.045;
              const baseV = g[1] + (hash01(i * 6.1 + 3) - 0.5) * 0.045;
              const fu = baseU + Math.sin(tSec * 0.35 + i * 2.1) * 0.0045;
              const fv = baseV + Math.cos(tSec * 0.42 + i * 1.7) * 0.0038;
              const sx = ctx.toX(fu);
              const sy = ctx.toY(fv);
              if (!ctx.inView(sx, sy, 12)) continue;
              const glow = Math.pow(0.5 + 0.5 * Math.sin(tSec * (1.5 + hash01(i * 2.9) * 1.6) + i * 3.7), 3.0);
              if (glow < 0.15) continue;
              targetCtx.globalAlpha = glow * 0.84;
              targetCtx.fillStyle = '#ffe57f';
              targetCtx.fillRect(Math.round(sx), Math.round(sy), Math.max(1.5, Math.round(dot)), Math.max(1.5, Math.round(dot)));
            }
            targetCtx.restore();
          }
        },
      });

      // ── 4. OVERLAY: Streetlamps + Orbiting Moths, Harbor Beacons, Upgraded Living Windows, Cloud Shadows ──
      drawables.push({
        layer: 'overlay',
        sortY: 0,
        draw(targetCtx) {
          targetCtx.save();

          // 4a. Nighttime Streetlamp Glows + Orbiting Moths along 3 main arteries
          if (isNight && animData && Array.isArray(animData.roads)) {
            if (!cachedLampRoads || cachedLampRoadsSrc !== animData) {
              cachedLampRoadsSrc = animData;
              cachedLampRoads = animData.roads.filter(
                (r) => r.id === 'seestrasse_sb' || r.id === 'dorfstrasse_viaduct_up' || r.id === 'alte_landstrasse_eb',
              );
            }
            for (let ri = 0; ri < cachedLampRoads.length; ri++) {
              const rd = cachedLampRoads[ri];
              const pts = rd.pts || [];
              const step = rd.id === 'seestrasse_sb' ? 28 : 26;
              for (let i = 10; i < pts.length - 10; i += step) {
                const sx = ctx.toX(pts[i][0]);
                const sy = ctx.toY(pts[i][1]);
                if (!ctx.inView(sx, sy, 28)) continue;
                const lr = Math.max(6, 12.5 * s);
                blitGlow(targetCtx, sx, sy, lr * 1.15, '255,208,120', 0.30, lr * 0.72);
                if (s >= 0.8) {
                  const gSz = Math.max(1.5, Math.round(1.5 * s));
                  targetCtx.fillStyle = 'rgba(255, 236, 176, 0.86)';
                  targetCtx.fillRect(Math.round(sx - gSz * 0.5), Math.round(sy - 3.5 * s), gSz, gSz);
                  // New v13.0 tiny orbiting streetlamp moths
                  const mSz = Math.max(1, Math.round(0.75 * s));
                  targetCtx.fillStyle = 'rgba(248, 244, 224, 0.72)';
                  for (let m = 0; m < 2; m++) {
                    const mAng = tSec * (3.6 + m * 1.7) + i * 0.9 + ri * 2.1;
                    const mx = sx + Math.cos(mAng) * (2.2 + m * 1.1) * s;
                    const my = sy - 3.4 * s + Math.sin(mAng * 1.4) * (1.2 + m * 0.6) * s;
                    targetCtx.fillRect(Math.round(mx), Math.round(my), mSz, mSz);
                  }
                }
              }
            }
          }

          // 4b. Harbor Navigation Beacons (Bendlikon & Seebad)
          if (isNight || isSunset) {
            const bpBeacon = (vig.bendlikon_pier && vig.bendlikon_pier.beacon) || [0.58700, 0.57838];
            const sbBeacon = (vig.seebad_kilchberg && vig.seebad_kilchberg.beacon) || [0.42221, 0.72359];
            const piers = [
              { u: bpBeacon[0], v: bpBeacon[1], col: '#ffb84d', glow: '255,184,77', freq: 1.4 },
              { u: sbBeacon[0], v: sbBeacon[1], col: '#6ee7b7', glow: '110,231,183', freq: 1.9 },
            ];
            for (let pi = 0; pi < piers.length; pi++) {
              const p = piers[pi];
              const sx = ctx.toX(p.u);
              const sy = ctx.toY(p.v);
              if (!ctx.inView(sx, sy, 32)) continue;
              const blink = 0.45 + 0.55 * Math.pow(0.5 + 0.5 * Math.sin(tSec * p.freq), 2.5);
              const r = Math.max(3.5, 5.5 * s);
              blitGlow(targetCtx, sx, sy, r * 2.0, p.glow, (isNight ? 0.52 : 0.28) * blink);
              targetCtx.globalAlpha = (isNight ? 0.98 : 0.68) * blink;
              targetCtx.fillStyle = p.col;
              const dot = Math.max(2, Math.round(2.2 * s));
              targetCtx.fillRect(Math.round(sx - dot * 0.5), Math.round(sy - dot * 0.5), dot, dot);
              if (isNight) {
                for (let k = 1; k <= 4; k++) {
                  const waveX = Math.sin(tSec * 3.1 + k * 1.7) * 1.4 * s;
                  targetCtx.globalAlpha = (0.38 - k * 0.07) * blink;
                  targetCtx.fillRect(Math.round(sx + waveX - dot * 0.5), Math.round(sy + k * 2.8 * s), dot, Math.max(1, Math.round(1.2 * s)));
                }
              }
            }
            targetCtx.globalAlpha = 1.0;
          }

          // 4c. Upgraded Dusk & Night Residential Living Windows (warm amber + subtle flickering TV glow + curtains)
          if ((isSunset || isNight) && s >= 0.24 && meta) {
            const wins = getLivingWindows(meta);
            const wPx = Math.max(1.5, Math.round(1.8 * s));
            const hPx = Math.max(1.2, Math.round(1.4 * s));
            const thresh = isNight ? -0.35 : 0.22;
            for (let i = 0; i < wins.length; i++) {
              const wn = wins[i];
              if (isSunset && wn.sunsetBias > 0.52) continue;
              const sx = ctx.toX(wn.u);
              const sy = ctx.toY(wn.v);
              if (!ctx.inView(sx, sy, 16)) continue;
              const wave = Math.sin((tSec / wn.period) * Math.PI * 2 + wn.phase);
              if (wave < thresh) continue;
              const tNorm = Math.min(1, (wave - thresh) / 0.28);
              const smooth = tNorm * tNorm * (3 - 2 * tNorm);
              const tvFlicker = wn.isTv ? (0.74 + 0.26 * Math.sin(tSec * 9.5 + i * 3.7) * Math.cos(tSec * 4.1 + i)) : 1.0;
              const baseAlpha = isNight ? 0.72 : 0.44;
              const alpha = baseAlpha * smooth * tvFlicker;
              if (isNight && s >= 1.0) {
                blitGlow(targetCtx, sx, sy, 3.4 * s, wn.isTv ? '180,218,255' : '255,214,132', alpha * 0.26);
              }
              targetCtx.globalAlpha = alpha;
              targetCtx.fillStyle = wn.col;
              const rx = Math.round(sx - wPx * 0.5);
              const ry = Math.round(sy - hPx * 0.5);
              targetCtx.fillRect(rx, ry, wPx, hPx);
              // Delicate curtain silhouette along upper-left edge when zoomed in
              if (wn.hasCurtain && s >= 1.0 && wPx >= 3) {
                targetCtx.globalAlpha = alpha * 0.55;
                targetCtx.fillStyle = '#1e293b';
                targetCtx.fillRect(rx, ry, Math.max(1, Math.round(wPx * 0.34)), hPx);
              }
            }
            targetCtx.globalAlpha = 1.0;
          }

          // 4d. Soft Drifting Swiss Cloud Shadows (SW->NE wind-aligned, day & sunset)
          if (!isNight) {
            targetCtx.fillStyle = isSunset ? 'rgba(34, 24, 52, 0.062)' : 'rgba(22, 38, 66, 0.052)';
            const windSpeedMul = 0.85 + 0.15 * wind.strength;
            for (let c = 0; c < 6; c++) {
              const cu = (((tSec * 0.0042 * windSpeedMul + c * 0.19 + hash01(c * 11.3) * 0.08) % 1.35) + 1.35) % 1.35 - 0.18;
              const cv = 0.16 + (c % 3) * 0.24 + Math.sin(tSec * 0.05 + c) * 0.03 - cu * 0.24;
              const sx = ctx.toX(cu);
              const sy = ctx.toY(cv);
              const rx = (340 + (c % 3) * 140) * s;
              const ry = rx * 0.42;
              if (sx + rx < 0 || sx - rx > cam.width || sy + ry < 0 || sy - ry > cam.height) continue;
              targetCtx.beginPath();
              targetCtx.ellipse(sx, sy, rx, ry, -0.28, 0, Math.PI * 2);
              targetCtx.fill();
            }
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

    getLivingCounts() {
      return { ...counts };
    },
  };
}
