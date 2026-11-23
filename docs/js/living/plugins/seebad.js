/**
 * Seebad Kilchberg & Schooren Waterfront Plugin (Kilchberg v13.0).
 *
 * Layers:
 *   - 'water'    (isWaterUV-strict):
 *       * Open-lake swimmers off Seebad jetty with crawl-stroke wake
 *       * Animated 3m Sprungturm diver splash plume + expanding ripple rings + return swim
 *       * Jetty-tip water-lap ripples
 *   - 'ground_y' (depthMasked: true, extraVertPx: 2.0):
 *       * Jetty bathers strolling along wooden pier
 *       * 3m Sprungturm diver walkout & springboard bounce phase
 *   - 'landmark':
 *       * Pool lane swimmers (day/sunset) & luminous aqua pool glow (night)
 *       * 3m Sprungturm diver parabolic air arc
 *       * Colorful lakeside beach umbrellas
 *       * Chez Fritz waterfront pavilion deck string-lights & Schooren kiln courtyard lantern
 *
 * 100% deterministic seeded rendering, cached glow sprites, pure vector/pixel geometry.
 * Counts are reported under livingCounts (seebadDivers, seebadSwimmers), NEVER simStats.pedestrians.
 */

import { shadeHex } from '../../render/vehicles.js';
import {
  blitGlow,
  drawMiniPersonV2,
  drawSplashPlume,
  drawWaterRipples,
} from '../draw.js';

const COATS = ['#d9382e', '#2563eb', '#0d9488', '#d97706', '#7c3aed', '#e11d48'];
const HAIRS = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];
const SWIM_CAPS = ['#f43f5e', '#facc15', '#ffffff'];

const UMBRELLAS = [
  { u: 0.4036, v: 0.7018, c1: '#d9382e', c2: '#f4f6f8', dk: '#8f1d18' },
  { u: 0.4052, v: 0.7010, c1: '#2563eb', c2: '#f4f6f8', dk: '#1a3f94' },
  { u: 0.4063, v: 0.7024, c1: '#eab308', c2: '#fef3c7', dk: '#a16207' },
];

function drawWarmLantern(ctx, x, y, rad, isNight, colorKey = 'amber', coreHex = '#fff0be', alphaMul = 1.0) {
  const r = Math.max(2.5, rad);
  blitGlow(ctx, x, y, r, colorKey, (isNight ? 0.46 : 0.24) * alphaMul);
  const dot = Math.max(1.4, r * 0.20);
  ctx.fillStyle = coreHex;
  ctx.fillRect(Math.round(x - dot * 0.5), Math.round(y - dot * 0.5), Math.max(1, Math.round(dot)), Math.max(1, Math.round(dot)));
}

export function createSeebadPlugin() {
  let counts = { seebadDivers: 0, seebadSwimmers: 0 };
  let cachedInspectables = [];

  return {
    id: 'seebad',
    name: 'Seebad Kilchberg & 3m Sprungturm',
    category: 'water',
    layers: ['water', 'ground_y', 'landmark'],
    priority: 28,
    enabledByDefault: true,

    init() {
      counts = { seebadDivers: 0, seebadSwimmers: 0 };
      cachedInspectables = [];
    },

    getDrawables(cam, ctx) {
      const { animData, depthMgr, worldW, worldH, wScale, tSec, mode, isNight, isSunset, s } = ctx;
      const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};
      const seebadPool = (vig.seebad_kilchberg && vig.seebad_kilchberg.pool) || [0.40901, 0.70921];
      const seebadJetty = (vig.seebad_kilchberg && vig.seebad_kilchberg.jetty) || [[0.4126, 0.71361], [0.4216, 0.7232]];
      const isWater = (u, v) => (!depthMgr || !depthMgr.isWaterMaskReady || !depthMgr.isWaterMaskReady() || depthMgr.isWaterUV(u, v));
      const isStrictWater = (u, v) => (!depthMgr || !depthMgr.isWaterUV || depthMgr.isWaterUV(u, v));
      const walkerBounds = { ex: 4.5 * wScale, eyUp: 9.5 * wScale, eyDn: 3.5 * wScale };

      const drawables = [];
      const inspectables = [];
      counts = { seebadDivers: 0, seebadSwimmers: 0 };

      if (!isNight) {
        counts.seebadDivers = 1;
        counts.seebadSwimmers = 5; // 3 pool lane swimmers + 2 open-lake swimmers
      }

      if (!ctx.boxInView(0.388, 0.672, seebadJetty[1][0] + 0.014, seebadJetty[1][1] + 0.014)) {
        cachedInspectables = inspectables;
        return drawables;
      }

      // ── 1. Pool Glow (night) OR Pool Lane Swimmers + Umbrellas (day & sunset) ──
      if (isNight) {
        if (ctx.boxInView(seebadPool[0] - 0.005, seebadPool[1] - 0.006, seebadPool[0] + 0.006, seebadPool[1] + 0.007)) {
          drawables.push({
            layer: 'landmark',
            sortY: seebadPool[1] * worldH,
            draw(targetCtx) {
              blitGlow(targetCtx, ctx.toX(seebadPool[0]), ctx.toY(seebadPool[1]), 22 * s, '64,228,240', 0.34, 14 * s, -0.35);
            },
          });
        }
      } else {
        // Pool lane swimmers
        if (ctx.boxInView(seebadPool[0] - 0.004, seebadPool[1] - 0.005, seebadPool[0] + 0.005, seebadPool[1] + 0.006)) {
          inspectables.push({
            kind: 'vignette',
            id: 'seebad:pool_swimmers',
            wx: seebadPool[0] * worldW,
            wy: seebadPool[1] * worldH,
            radiusCss: 14,
            title: 'Seebad Kilchberg · Pool Lane Swimmers',
            sub: 'Lap swimmers enjoying the heated lakeside pool at Seebad Kilchberg',
            specs: [
              ['Facility', 'Seebad Kilchberg (Schooren)'],
              ['Activity', '25m Lane Swimming'],
              ['Swimmers', '3 Active Lanes'],
              ['Season', 'Lake & Pool Open'],
            ],
          });

          drawables.push({
            layer: 'landmark',
            sortY: seebadPool[1] * worldH,
            draw(targetCtx) {
              const px = Math.max(1.2, 1.3 * s);
              for (let sw = 0; sw < 3; sw++) {
                // Realistic 0.85–1.05 m/s pool lap swimming
                const prog = 0.5 + 0.5 * Math.sin(tSec * (0.16 + sw * 0.024) + sw * 2.1);
                const su = seebadPool[0] - 0.0019 + prog * 0.0028 + sw * 0.0005;
                const sv = seebadPool[1] - 0.0023 + (1 - prog) * 0.0018 + sw * 0.0013;
                const sx = ctx.toX(su);
                const sy = ctx.toY(sv);
                targetCtx.fillStyle = 'rgba(240, 252, 255, 0.78)';
                targetCtx.fillRect(Math.round(sx - px * 1.6), Math.round(sy), Math.max(2, Math.round(px * 3.2)), Math.max(1, Math.round(px * 0.85)));
                targetCtx.fillStyle = SWIM_CAPS[sw];
                targetCtx.fillRect(Math.round(sx - px * 0.5), Math.round(sy - px * 0.7), Math.max(2, Math.round(px * 1.2)), Math.max(2, Math.round(px * 1.1)));
              }
            },
          });
        }

        // Beach umbrellas on Seebad lawn
        if (ctx.boxInView(0.401, 0.699, 0.409, 0.706)) {
          drawables.push({
            layer: 'landmark',
            sortY: 0.702 * worldH,
            draw(targetCtx) {
              const p = Math.max(1.0, s);
              const w = (n) => Math.max(1, Math.round(n * p));
              for (let i = 0; i < UMBRELLAS.length; i++) {
                const um = UMBRELLAS[i];
                const ux = Math.round(ctx.toX(um.u));
                const uy = Math.round(ctx.toY(um.v));
                targetCtx.fillStyle = 'rgba(16, 28, 22, 0.34)';
                targetCtx.fillRect(ux - w(2), uy + w(1), w(7), w(2));
                targetCtx.fillStyle = '#5c4028';
                targetCtx.fillRect(ux, uy - w(2), w(1), w(3));
                targetCtx.fillStyle = 'rgba(22, 26, 32, 0.82)';
                targetCtx.fillRect(ux - w(4), uy - w(4), w(9), w(3));
                targetCtx.fillRect(ux - w(3), uy - w(5), w(7), w(5));
                targetCtx.fillStyle = shadeHex(um.dk, 1.0, mode);
                targetCtx.fillRect(ux - w(3), uy - w(2), w(7), w(1.2));
                targetCtx.fillStyle = shadeHex(um.c1, 1.04, mode);
                targetCtx.fillRect(ux - w(3), uy - w(4), w(7), w(2.2));
                targetCtx.fillStyle = shadeHex(um.c2, 1.04, mode);
                targetCtx.fillRect(ux - w(1), uy - w(4.5), w(3), w(3.2));
                targetCtx.fillStyle = '#ffffff';
                targetCtx.fillRect(ux, uy - w(4.5), w(1), w(1));
              }
            },
          });
        }

        // Jetty bathers (ground_y, depth-masked, extraVertPx: 2.0)
        if (ctx.boxInView(seebadJetty[0][0] - 0.003, seebadJetty[0][1] - 0.003, seebadJetty[1][0] + 0.004, seebadJetty[1][1] + 0.004)) {
          // Non-overlapping stroll zones along jetty so bathers maintain personal space
          const batherBands = [
            [0.10, 0.24],
            [0.29, 0.43],
            [0.48, 0.62],
            [0.67, 0.80],
          ];
          for (let jb = 0; jb < 4; jb++) {
            const [bMin, bMax] = batherBands[jb];
            const phaseAng = tSec * (0.14 + jb * 0.025) + jb * 1.7;
            const f = bMin + (bMax - bMin) * (0.5 + 0.5 * Math.sin(phaseAng));
            const ju = seebadJetty[0][0] + (seebadJetty[1][0] - seebadJetty[0][0]) * f;
            const jv = seebadJetty[0][1] + (seebadJetty[1][1] - seebadJetty[0][1]) * f;
            const wx = ju * worldW;
            const wy = jv * worldH;
            const d16 = depthMgr && depthMgr.evalWalkerD16
              ? depthMgr.evalWalkerD16(wx, wy, 407.4, worldW, worldH, true)
              : 0;
            const coat = shadeHex(COATS[(jb + 2) % COATS.length], 1.0, mode);
            const hair = HAIRS[jb % HAIRS.length];
            const stride = Math.abs(Math.cos(phaseAng)) > 0.15 ? (tSec * 3.8 + jb) : 0;

            drawables.push({
              layer: 'ground_y',
              sortY: wy,
              depthMasked: true,
              wx,
              wy,
              bounds: walkerBounds,
              d16,
              extraVertPx: 2.0,
              draw(targetCtx) {
                drawMiniPersonV2(targetCtx, ctx.toX(ju), ctx.toY(jv), s * 0.92, {
                  coatCol: coat,
                  pantsCol: '#2b4c7e',
                  hairCol: hair,
                  isNight: false,
                  phase: stride,
                  canvasW: cam.width,
                  canvasH: cam.height,
                });
              },
            });
          }
        }

        // ── 2. Animated 3m Sprungturm Diving-Board Diver ──
        // Cycle: 0..0.28 walkout -> 0.28..0.40 bounce -> 0.40..0.56 parabolic dive -> 0.56..0.78 splash & ripples -> 0.78..1.00 swim back
        const diveCycle = (((tSec / 11.5) % 1) + 1) % 1;
        const boardStartU = seebadJetty[0][0] + (seebadJetty[1][0] - seebadJetty[0][0]) * 0.80;
        const boardStartV = seebadJetty[0][1] + (seebadJetty[1][1] - seebadJetty[0][1]) * 0.80;
        const boardTipU = seebadJetty[1][0];
        const boardTipV = seebadJetty[1][1];
        const splashU = 0.4222;
        const splashV = 0.7235;
        const splashInWater = isWater(splashU, splashV);

        let diverU = boardTipU;
        let diverV = boardTipV;
        let diverStage = 'Preparing on 3m Sprungturm';

        if (diveCycle < 0.28) {
          const p = diveCycle / 0.28;
          diverU = boardStartU + (boardTipU - boardStartU) * p;
          diverV = boardStartV + (boardTipV - boardStartV) * p;
          diverStage = 'Walking out onto 3m diving board';
        } else if (diveCycle < 0.40) {
          diverU = boardTipU;
          diverV = boardTipV;
          diverStage = 'Springboard bounce on 3m Sprungturm';
        } else if (diveCycle < 0.56) {
          const p = (diveCycle - 0.40) / 0.16;
          diverU = boardTipU + (splashU - boardTipU) * p;
          diverV = boardTipV + (splashV - boardTipV) * p;
          diverStage = 'Mid-air dive into Lake Zurich';
        } else if (diveCycle < 0.78) {
          diverU = splashU;
          diverV = splashV;
          diverStage = 'Splashdown in Lake Zurich';
        } else {
          const p = (diveCycle - 0.78) / 0.22;
          diverU = splashU + (boardTipU + 0.0005 - splashU) * p;
          diverV = splashV + (boardTipV + 0.0005 - splashV) * p;
          diverStage = 'Swimming back to Seebad jetty';
        }

        inspectables.push({
          kind: 'vignette',
          id: 'seebad:sprungturm_diver',
          wx: diverU * worldW,
          wy: diverV * worldH,
          radiusCss: 13,
          title: 'Seebad 3m Sprungturm Diver',
          sub: diverStage,
          specs: [
            ['Platform', 'Seebad Kilchberg 3m Sprungturm'],
            ['Phase', diverStage],
            ['Water', 'Lake Zurich (406 m a.s.l.)'],
            ['Safety', 'Open-water diving zone'],
          ],
        });

        if (diveCycle < 0.40) {
          const isBounce = diveCycle >= 0.28;
          const bProg = isBounce ? (diveCycle - 0.28) / 0.12 : 0;
          const bouncePx = isBounce ? Math.abs(Math.sin(bProg * Math.PI * 2)) * 2.2 : 0;
          const wx = diverU * worldW;
          const wy = diverV * worldH;
          const d16 = depthMgr && depthMgr.evalWalkerD16
            ? depthMgr.evalWalkerD16(wx, wy, 409.5, worldW, worldH, true)
            : 0;
          drawables.push({
            layer: 'ground_y',
            sortY: wy,
            depthMasked: true,
            wx,
            wy,
            bounds: walkerBounds,
            d16,
            extraVertPx: 2.0,
            draw(targetCtx) {
              const bx = ctx.toX(diverU);
              const by = ctx.toY(diverV) - (2.4 + bouncePx) * s;
              // Crisp springboard plank tip highlight
              targetCtx.fillStyle = '#e2e8f0';
              targetCtx.fillRect(Math.round(ctx.toX(boardTipU) - 1.2 * s), Math.round(ctx.toY(boardTipV) - 1.8 * s), Math.max(2, Math.round(3.4 * s)), Math.max(1, Math.round(1.0 * s)));
              drawMiniPersonV2(targetCtx, bx, by, s * 0.90, {
                coatCol: shadeHex('#e11d48', 1.0, mode),
                pantsCol: '#0f172a',
                hairCol: '#2d241c',
                isNight: false,
                phase: isBounce ? 0 : tSec * 7.5,
                canvasW: cam.width,
                canvasH: cam.height,
              });
            },
          });
        } else if (diveCycle < 0.56) {
          // Parabolic mid-air dive arc
          const p = (diveCycle - 0.40) / 0.16;
          const arcLiftPx = ((1 - p) * 3.8 + Math.sin(p * Math.PI) * 5.2) * s;
          drawables.push({
            layer: 'landmark',
            sortY: diverV * worldH,
            draw(targetCtx) {
              const dx = ctx.toX(diverU);
              const dy = ctx.toY(diverV) - arcLiftPx;
              const px = Math.max(1.0, s);
              // Subtle shadow on water surface below diver
              if (splashInWater) {
                targetCtx.fillStyle = 'rgba(12, 24, 38, 0.26)';
                targetCtx.beginPath();
                targetCtx.ellipse(dx, ctx.toY(diverV), 1.8 * px, 0.9 * px, 0, 0, Math.PI * 2);
                targetCtx.fill();
              }
              // Compact arched diver silhouette
              targetCtx.save();
              targetCtx.translate(dx, dy);
              targetCtx.rotate(-0.4 + p * 1.9);
              targetCtx.fillStyle = '#ecc29c';
              targetCtx.fillRect(Math.round(-0.7 * px), Math.round(-2.6 * px), Math.max(1, Math.round(1.4 * px)), Math.max(1, Math.round(1.2 * px)));
              targetCtx.fillStyle = shadeHex('#e11d48', 1.0, mode);
              targetCtx.fillRect(Math.round(-0.8 * px), Math.round(-1.4 * px), Math.max(2, Math.round(1.7 * px)), Math.max(2, Math.round(2.3 * px)));
              targetCtx.fillStyle = '#ecc29c';
              targetCtx.fillRect(Math.round(-0.6 * px), Math.round(0.8 * px), Math.max(1, Math.round(1.2 * px)), Math.max(2, Math.round(1.8 * px)));
              targetCtx.restore();
            },
          });
        } else if (diveCycle < 0.78 && splashInWater) {
          // Splash plume + expanding concentric ripple rings (isWaterUV-strict)
          const splashProg = (diveCycle - 0.56) / 0.22;
          drawables.push({
            layer: 'water',
            sortY: splashV * worldH,
            draw(targetCtx) {
              const sx = ctx.toX(splashU);
              const sy = ctx.toY(splashV);
              if (!ctx.inView(sx, sy, 32)) return;
              drawSplashPlume(targetCtx, sx, sy, s, splashProg, {
                isNight: false,
                isSunset,
                scaleMul: 1.15,
                drops: 6,
              });
              drawWaterRipples(targetCtx, sx, sy, s * 1.05, splashProg, {
                count: 3,
                speed: 1.0,
                minR: 1.8,
                maxR: 8.2,
                isNight: false,
                isSunset,
                alpha: 0.62,
              });
            },
          });
        } else if (diveCycle >= 0.78 && isStrictWater(diverU, diverV)) {
          // Return swim to jetty ladder (isWaterUV-strict)
          drawables.push({
            layer: 'water',
            sortY: diverV * worldH,
            draw(targetCtx) {
              const sx = ctx.toX(diverU);
              const sy = ctx.toY(diverV);
              if (!ctx.inView(sx, sy, 24)) return;
              const px = Math.max(1.1, 1.2 * s);
              targetCtx.fillStyle = 'rgba(232, 248, 255, 0.68)';
              targetCtx.fillRect(Math.round(sx - px * 1.5), Math.round(sy), Math.max(2, Math.round(px * 3.0)), Math.max(1, Math.round(px * 0.8)));
              targetCtx.fillStyle = '#e11d48';
              targetCtx.fillRect(Math.round(sx - px * 0.5), Math.round(sy - px * 0.6), Math.max(2, Math.round(px * 1.1)), Math.max(2, Math.round(px * 1.0)));
            },
          });
        }

        // ── 3. Open-Lake Swimmers (isWaterUV-strict) ──
        if (ctx.boxInView(0.421, 0.721, 0.432, 0.734)) {
          for (let ls = 0; ls < 2; ls++) {
            // Realistic 0.75–0.90 m/s open-lake swimming
            const ang = tSec * (0.115 + ls * 0.016) + ls * 3.1;
            const lsu = 0.4275 + Math.cos(ang) * 0.0022;
            const lsv = 0.7272 + Math.sin(ang) * 0.0024;
            if (!isStrictWater(lsu, lsv)) continue;
            const wx = lsu * worldW;
            const wy = lsv * worldH;

            if (ls === 0) {
              inspectables.push({
                kind: 'vignette',
                id: 'seebad:open_lake_swimmer',
                wx,
                wy,
                radiusCss: 10,
                title: 'Open-Lake Swimmer · Seebad Kilchberg',
                sub: 'Swimming in Lake Zurich outside Seebad wooden jetty',
                specs: [
                  ['Location', 'Seebad Kilchberg Bay'],
                  ['Activity', 'Open-Water Lake Swim'],
                  ['Lake Temp', '21 °C (Summer)'],
                  ['Zone', 'Buoyed Swimmer Area'],
                ],
              });
            }

            drawables.push({
              layer: 'water',
              sortY: wy,
              draw(targetCtx) {
                const lx = ctx.toX(lsu);
                const ly = ctx.toY(lsv);
                if (!ctx.inView(lx, ly, 24)) return;
                const px = Math.max(1.2, 1.3 * s);
                drawWaterRipples(targetCtx, lx, ly, px * 0.55, tSec, {
                  count: 2,
                  speed: 0.48,
                  phaseOff: ls * 0.45,
                  minR: 1.2,
                  maxR: 3.6,
                  isNight: false,
                  isSunset,
                  alpha: 0.42,
                });
                targetCtx.fillStyle = 'rgba(232, 248, 255, 0.72)';
                targetCtx.fillRect(Math.round(lx - px * 1.8), Math.round(ly), Math.max(2, Math.round(px * 3.6)), Math.max(1, Math.round(px * 0.85)));
                targetCtx.fillStyle = ls === 0 ? '#fb7185' : '#38bdf8';
                targetCtx.fillRect(Math.round(lx - px * 0.5), Math.round(ly - px * 0.6), Math.max(2, Math.round(px * 1.2)), Math.max(2, Math.round(px * 1.1)));
              },
            });
          }
        }

        // Gentle jetty-tip water-lap ripples (isWaterUV-strict)
        if (s >= 0.30) {
          const tipRipU = seebadJetty[1][0] + 0.0018;
          const tipRipV = seebadJetty[1][1] + 0.0018;
          if (isWater(tipRipU, tipRipV)) {
            drawables.push({
              layer: 'water',
              sortY: tipRipV * worldH,
              draw(targetCtx) {
                const sx = ctx.toX(tipRipU);
                const sy = ctx.toY(tipRipV);
                if (!ctx.inView(sx, sy, 28)) return;
                drawWaterRipples(targetCtx, sx, sy, s, tSec, {
                  count: 2,
                  speed: 0.36,
                  phaseOff: 0.15,
                  minR: 1.6,
                  maxR: 5.5,
                  isNight: false,
                  isSunset,
                });
              },
            });
          }
        }
      }

      // ── 4. Chez Fritz Waterfront Deck String-Lights & Schooren Courtyard Lantern (sunset & night) ──
      if ((isSunset || isNight) && s >= 0.30) {
        drawables.push({
          layer: 'landmark',
          sortY: 0.70 * worldH,
          draw(targetCtx) {
            if (s >= 0.35) {
              for (let cf = 0; cf < 4; cf++) {
                drawWarmLantern(
                  targetCtx,
                  ctx.toX(0.4248 + cf * 0.0007),
                  ctx.toY(0.6932 + cf * 0.0002),
                  4.6 * s,
                  isNight,
                  '255,214,134',
                  '#fff0be',
                  0.85,
                );
              }
            }
            drawWarmLantern(
              targetCtx,
              ctx.toX(seebadPool[0] - 0.0055),
              ctx.toY(seebadPool[1] - 0.0068),
              10.5 * s,
              isNight,
              '255,198,128',
              '#ffe4b5',
              0.92,
            );
          },
        });
      }

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
