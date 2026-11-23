/**
 * Swiss & Lake Zurich Wildlife Plugin (Kilchberg v13.0).
 *
 * Layers:
 *   - 'water'    (isWaterUV-strict):
 *       * Mute Swans (Höckerschwan) + 1–2 trailing fluffy cygnets + foraging head-dip + ripples
 *       * Mallard duck pairs (Stockente) with periodic tip-up diving ripples
 *       * Wading Grey Heron (Graureiher) stalking the Morfanlage / Sulzergut reed edge
 *   - 'ground_y' (depthMasked: true, extraVertPx: 2.0):
 *       * Stockengut horned Rhätisches Grauvieh cattle with tail flick & grazing head-bob
 *   - 'air':
 *       * Gliding Lake Gulls (Lachmöwe)
 *       * Darting Barn Swallows (Rauchschwalben) skimming meadows & shoreline
 *       * Soaring Red Kites (Rotmilan) with forked rufous tail & ground shadow
 *       * Bell-triggered flocking church pigeons (Stadttauben) circling Reformierte Kirche belfry
 *
 * All wildlife is inspectable via getInspectables().
 */

import { drawPixelRectWorld, shadeHex } from '../../render/vehicles.js';
import { drawWaterRipples } from '../draw.js';

const SWAN_LOOPS = [
  { id: 'swan:bendlikon_1', cu: 0.5960, cv: 0.5915, ru: 0.0042, rv: 0.0036, spd: 0.14, ph: 0.0, cygnets: 2 },
  { id: 'swan:bendlikon_2', cu: 0.6005, cv: 0.5955, ru: 0.0038, rv: 0.0033, spd: 0.14, ph: 0.35, cygnets: 0 },
  { id: 'swan:seebad_1', cu: 0.4400, cv: 0.7285, ru: 0.0036, rv: 0.0032, spd: 0.16, ph: 1.4, cygnets: 1 },
  { id: 'swan:seebad_2', cu: 0.4440, cv: 0.7315, ru: 0.0034, rv: 0.0030, spd: 0.16, ph: 1.85, cygnets: 0 },
  { id: 'swan:sulzergut', cu: 0.6960, cv: 0.5370, ru: 0.0040, rv: 0.0034, spd: 0.13, ph: 3.1, cygnets: 1 },
];

const DUCK_PAIRS = [
  { id: 'duck:schooren', cu: 0.5160, cv: 0.6540, ru: 0.0028, rv: 0.0024, spd: 0.18, ph: 0.4 },
  { id: 'duck:bendlikon', cu: 0.6380, cv: 0.5650, ru: 0.0026, rv: 0.0022, spd: 0.16, ph: 2.2 },
  { id: 'duck:morfanlage', cu: 0.7700, cv: 0.4700, ru: 0.0030, rv: 0.0025, spd: 0.15, ph: 4.1 },
];

const HERON_SPOT = {
  id: 'heron:morfanlage',
  u: 0.6905,
  v: 0.5210,
};

const COW_OFFSETS = [
  [0.0094, -0.0233],
  [0.0119, -0.0273],
  [0.0154, -0.0238],
  [0.0189, -0.0263],
  [0.0219, -0.0218],
];

const COW_COATS = [
  ['#9b948a', '#6e6860'], // silvery-grey Rhätisches Grauvieh
  ['#7d7063', '#544a41'], // warm taupe-brown Grauvieh
  ['#dad6ce', '#a8a298'], // pale silver-white calf
  ['#969086', '#69635b'], // classic silver-grey cow
  ['#4a423d', '#2e2926'], // dark charcoal-brown cow
];

const RED_KITES = [
  { id: 'kite:ridge_east', cu: 0.655, cv: 0.285, ru: 0.024, rv: 0.014, spd: 0.16, ph: 0.2 },
  { id: 'kite:ridge_west', cu: 0.315, cv: 0.305, ru: 0.022, rv: 0.013, spd: 0.14, ph: 3.6 },
];

const SWALLOW_LOOPS = [
  { id: 'swallow:meadow_1', cu: 0.528, cv: 0.215, ru: 0.014, rv: 0.009, spd: 0.62, ph: 0.4 },
  { id: 'swallow:meadow_2', cu: 0.534, cv: 0.222, ru: 0.012, rv: 0.008, spd: 0.70, ph: 2.3 },
  { id: 'swallow:shore_1', cu: 0.585, cv: 0.562, ru: 0.015, rv: 0.008, spd: 0.66, ph: 1.1 },
  { id: 'swallow:shore_2', cu: 0.452, cv: 0.695, ru: 0.013, rv: 0.009, spd: 0.58, ph: 4.0 },
];

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

export function createWildlifePlugin() {
  let counts = {
    swans: 0,
    ducks: 0,
    gulls: 0,
    redKites: 0,
    herons: 0,
    swallows: 0,
    pigeons: 0,
    cattle: 0,
  };
  let cachedInspectables = [];

  return {
    id: 'wildlife',
    name: 'Swiss & Lake Zurich Wildlife',
    category: 'nature',
    layers: ['water', 'ground_y', 'air'],
    priority: 25,
    enabledByDefault: true,

    init() {
      counts = { swans: 0, ducks: 0, gulls: 0, redKites: 0, herons: 0, swallows: 0, pigeons: 0, cattle: 0 };
      cachedInspectables = [];
    },

    getDrawables(cam, ctx) {
      const { worldW, worldH, wScale, tSec, mode, isNight, isSunset, s, bell, depthMgr, animData } = ctx;
      const isWater = (u, v) => (!depthMgr || !depthMgr.isWaterUV || depthMgr.isWaterUV(u, v));
      const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};

      const drawables = [];
      const inspectables = [];
      counts = { swans: 0, ducks: 0, gulls: 0, redKites: 0, herons: 0, swallows: 0, pigeons: 0, cattle: 0 };

      // 1. WATER: Mute Swans (Höckerschwan) + trailing fluffy cygnets + foraging head-dip
      for (let i = 0; i < SWAN_LOOPS.length; i++) {
        const sw = SWAN_LOOPS[i];
        const ang = tSec * sw.spd + sw.ph;
        const su = sw.cu + Math.cos(ang) * sw.ru;
        const sv = sw.cv + Math.sin(ang) * sw.rv;
        if (!isWater(su, sv)) continue;
        counts.swans++;

        const wx = su * worldW;
        const wy = sv * worldH;
        const vx = -Math.sin(ang) * sw.ru * worldW;
        const vy = Math.cos(ang) * sw.rv * worldH;

        // Periodic deterministic foraging head-dip
        const dipCycle = (((tSec * 0.12 + i * 0.37) % 1) + 1) % 1;
        const isDipping = !isNight && dipCycle < 0.14;

        inspectables.push({
          kind: 'wildlife',
          id: sw.id,
          wx,
          wy,
          radiusCss: 10,
          title: sw.cygnets > 0 ? 'Höckerschwan Family · Lake Zurich' : 'Höckerschwan (Mute Swan)',
          sub: isDipping ? 'Foraging along Lake Zurich shallows' : (sw.cygnets > 0 ? `Gliding with ${sw.cygnets} fluffy cygnet${sw.cygnets > 1 ? 's' : ''}` : 'Gliding gracefully on Lake Zurich'),
          specs: [
            ['Species', 'Cygnus olor (Höckerschwan)'],
            ['Behavior', isDipping ? 'Foraging Head-Dip' : 'Cruising'],
            ['Brood', sw.cygnets > 0 ? `${sw.cygnets} Cygnet${sw.cygnets > 1 ? 's' : ''}` : 'Adult'],
            ['Habitat', 'Lake Zurich'],
          ],
        });

        drawables.push({
          layer: 'water',
          sortY: wy,
          draw(targetCtx) {
            const sx = ctx.toX(su);
            const sy = ctx.toY(sv);
            if (!ctx.inView(sx, sy, 28)) return;
            const dir = vx >= 0 ? 1 : -1;
            const px = Math.max(1.0, 1.15 * s);

            drawWaterfowlWake(targetCtx, sx, sy, vx, vy, px, isNight, 1.0);
            if (isDipping) {
              drawWaterRipples(targetCtx, sx + dir * 1.8 * px, sy + 0.4 * px, px * 0.55, dipCycle / 0.14, {
                count: 2,
                speed: 1.0,
                minR: 1.0,
                maxR: 3.8,
                isNight,
                isSunset,
                alpha: 0.52,
              });
            }

            // Swan body, neck & orange bill
            targetCtx.fillStyle = isNight ? '#b8c8dc' : (isSunset ? '#fff0de' : '#ffffff');
            targetCtx.fillRect(Math.round(sx - 1.6 * px), Math.round(sy - 0.6 * px), Math.max(2, Math.round(3.2 * px)), Math.max(1.5, Math.round(1.6 * px)));
            if (isDipping) {
              // Neck dipped down into water
              targetCtx.fillRect(Math.round(sx + dir * 1.3 * px), Math.round(sy - 0.5 * px), Math.max(1, Math.round(1.0 * px)), Math.max(1, Math.round(1.3 * px)));
            } else {
              targetCtx.fillRect(Math.round(sx + dir * 1.1 * px), Math.round(sy - 2.2 * px), Math.max(1, Math.round(1.1 * px)), Math.max(2, Math.round(2.0 * px)));
              targetCtx.fillStyle = '#f97316';
              targetCtx.fillRect(Math.round(sx + dir * 2.0 * px), Math.round(sy - 1.9 * px), Math.max(1, Math.round(0.9 * px)), Math.max(1, Math.round(0.7 * px)));
            }

            // 1–2 trailing fluffy grey-cream cygnets
            if (sw.cygnets > 0 && !isNight) {
              for (let c = 1; c <= sw.cygnets; c++) {
                const cAng = ang - c * 0.19;
                const cu = sw.cu + Math.cos(cAng) * sw.ru;
                const cv = sw.cv + Math.sin(cAng) * sw.rv;
                if (!isWater(cu, cv)) continue;
                const cx = ctx.toX(cu);
                const cy = ctx.toY(cv);
                targetCtx.fillStyle = isSunset ? '#dfd4c4' : '#d6d3cd';
                targetCtx.fillRect(Math.round(cx - 0.9 * px), Math.round(cy - 0.5 * px), Math.max(1, Math.round(1.8 * px)), Math.max(1, Math.round(1.1 * px)));
                targetCtx.fillStyle = '#a8a29e';
                targetCtx.fillRect(Math.round(cx + dir * 0.5 * px), Math.round(cy - 1.1 * px), Math.max(1, Math.round(0.7 * px)), Math.max(1, Math.round(0.8 * px)));
              }
            }
          },
        });
      }

      // 2. WATER: Mallard Duck Pairs (Stockente) with periodic tip-up diving ripples (Day & Sunset)
      if (!isNight) {
        for (let di = 0; di < DUCK_PAIRS.length; di++) {
          const dp = DUCK_PAIRS[di];
          for (let mate = 0; mate < 2; mate++) {
            const ang = tSec * dp.spd + dp.ph - mate * 0.28;
            const du = dp.cu + Math.cos(ang) * dp.ru;
            const dv = dp.cv + Math.sin(ang) * dp.rv;
            if (!isWater(du, dv)) continue;
            counts.ducks++;

            const wx = du * worldW;
            const wy = dv * worldH;
            const vx = -Math.sin(ang) * dp.ru * worldW;
            const vy = Math.cos(ang) * dp.rv * worldH;
            const diveCycle = (((tSec * 0.15 + di * 0.31 + mate * 0.52) % 1) + 1) % 1;
            const isTipUp = diveCycle < 0.15;

            if (mate === 0) {
              inspectables.push({
                kind: 'wildlife',
                id: dp.id,
                wx,
                wy,
                radiusCss: 9,
                title: 'Stockente Pair (Mallard Ducks)',
                sub: isTipUp ? 'Dabbling & tipping up in shallow water' : 'Swimming together along Kilchberg shore',
                specs: [
                  ['Species', 'Anas platyrhynchos (Stockente)'],
                  ['Group', 'Bonded Pair'],
                  ['Behavior', isTipUp ? 'Tip-Up Dabbling' : 'Foraging Swim'],
                  ['Habitat', 'Lake Zurich'],
                ],
              });
            }

            drawables.push({
              layer: 'water',
              sortY: wy,
              draw(targetCtx) {
                const dx = ctx.toX(du);
                const dy = ctx.toY(dv);
                if (!ctx.inView(dx, dy, 18)) return;
                const dir = vx >= 0 ? 1 : -1;
                const px = Math.max(0.9, 1.0 * s);

                if (isTipUp) {
                  drawWaterRipples(targetCtx, dx, dy, px * 0.5, diveCycle / 0.15, {
                    count: 2,
                    speed: 1.0,
                    minR: 0.9,
                    maxR: 3.4,
                    isNight: false,
                    isSunset,
                    alpha: 0.56,
                  });
                  // Tipped-up tail feathers above surface
                  targetCtx.fillStyle = mate === 0 ? '#e7e5e4' : '#8c6a4a';
                  targetCtx.fillRect(Math.round(dx - 0.8 * px), Math.round(dy - 1.3 * px), Math.max(1, Math.round(1.6 * px)), Math.max(1, Math.round(1.4 * px)));
                  return;
                }

                drawWaterfowlWake(targetCtx, dx, dy, vx, vy, px, false, 0.78);
                if (mate === 0) {
                  targetCtx.fillStyle = shadeHex('#78716c', 1.0, mode);
                  targetCtx.fillRect(Math.round(dx - 1.2 * px), Math.round(dy - 0.5 * px), Math.max(2, Math.round(2.5 * px)), Math.max(1.2, Math.round(1.3 * px)));
                  targetCtx.fillStyle = '#f8fafc';
                  targetCtx.fillRect(Math.round(dx + dir * 0.8 * px), Math.round(dy - 1.0 * px), Math.max(1, Math.round(0.9 * px)), Math.max(1, Math.round(0.6 * px)));
                  targetCtx.fillStyle = '#15803d';
                  targetCtx.fillRect(Math.round(dx + dir * 0.9 * px), Math.round(dy - 1.8 * px), Math.max(1, Math.round(1.0 * px)), Math.max(1, Math.round(1.0 * px)));
                } else {
                  targetCtx.fillStyle = shadeHex('#8c6a4a', 1.0, mode);
                  targetCtx.fillRect(Math.round(dx - 1.1 * px), Math.round(dy - 0.5 * px), Math.max(2, Math.round(2.3 * px)), Math.max(1.2, Math.round(1.2 * px)));
                  targetCtx.fillStyle = shadeHex('#6f5238', 1.0, mode);
                  targetCtx.fillRect(Math.round(dx + dir * 0.8 * px), Math.round(dy - 1.5 * px), Math.max(1, Math.round(0.9 * px)), Math.max(1, Math.round(0.9 * px)));
                }
              },
            });
          }
        }
      }

      // 3. WATER: Wading Grey Heron (Graureiher) at Morfanlage / Sulzergut reed edge (Day & Sunset, isWaterUV-strict)
      if (!isNight) {
        const stalkU = HERON_SPOT.u + Math.sin(tSec * 0.09) * 0.0014;
        const stalkV = HERON_SPOT.v + Math.cos(tSec * 0.07) * 0.0009;
        if (isWater(stalkU, stalkV)) {
          counts.herons = 1;
          const wx = stalkU * worldW;
          const wy = stalkV * worldH;
          const strikeCycle = (((tSec * 0.11 + 0.4) % 1) + 1) % 1;
          const striking = strikeCycle < 0.08;

          inspectables.push({
            kind: 'wildlife',
            id: HERON_SPOT.id,
            wx,
            wy,
            radiusCss: 10,
            title: 'Graureiher (Grey Heron) · Morfanlage',
            sub: striking ? 'Darting beak toward shallow-water minnows' : 'Patiently stalking along the reed shallows',
            specs: [
              ['Species', 'Ardea cinerea (Graureiher)'],
              ['Behavior', striking ? 'Quick Strike' : 'Still Stalking'],
              ['Location', 'Morfanlage / Sulzergut'],
              ['Habitat', 'Shoreline Shallows'],
            ],
          });

          drawables.push({
            layer: 'water',
            sortY: wy,
            draw(targetCtx) {
              const hx = ctx.toX(stalkU);
              const hy = ctx.toY(stalkV);
              if (!ctx.inView(hx, hy, 22)) return;
              const px = Math.max(0.9, 1.05 * s);

              drawWaterRipples(targetCtx, hx, hy + 0.5 * px, px * 0.5, tSec, {
                count: 1,
                speed: 0.35,
                minR: 1.0,
                maxR: 3.0,
                isNight: false,
                isSunset,
                alpha: 0.40,
              });

              // Stilted legs
              targetCtx.fillStyle = '#475569';
              targetCtx.fillRect(Math.round(hx - 0.4 * px), Math.round(hy - 2.0 * px), Math.max(1, Math.round(0.5 * px)), Math.max(2, Math.round(2.3 * px)));
              targetCtx.fillRect(Math.round(hx + 0.4 * px), Math.round(hy - 2.0 * px), Math.max(1, Math.round(0.5 * px)), Math.max(2, Math.round(2.3 * px)));
              // Slate-grey body & pale S-neck
              targetCtx.fillStyle = shadeHex('#94a3b8', 1.0, mode);
              targetCtx.fillRect(Math.round(hx - 1.4 * px), Math.round(hy - 3.6 * px), Math.max(2, Math.round(2.8 * px)), Math.max(1.5, Math.round(1.8 * px)));
              const neckFwd = striking ? 1.5 * px : 0.6 * px;
              const neckTop = striking ? -3.4 * px : -5.4 * px;
              targetCtx.fillStyle = shadeHex('#e2e8f0', 1.0, mode);
              targetCtx.fillRect(Math.round(hx + neckFwd), Math.round(hy + neckTop), Math.max(1, Math.round(0.9 * px)), Math.max(2, Math.round(2.4 * px)));
              // Dark crown plume & yellow bill
              targetCtx.fillStyle = '#1e293b';
              targetCtx.fillRect(Math.round(hx + neckFwd - 0.4 * px), Math.round(hy + neckTop - 0.4 * px), Math.max(1, Math.round(1.0 * px)), Math.max(1, Math.round(0.6 * px)));
              targetCtx.fillStyle = '#eab308';
              targetCtx.fillRect(Math.round(hx + neckFwd + 0.8 * px), Math.round(hy + neckTop + 0.2 * px), Math.max(1, Math.round(1.4 * px)), Math.max(1, Math.round(0.5 * px)));
            },
          });
        }
      }

      // 4. GROUND_Y: Stockengut Horned Rhätisches Grauvieh Cattle (Day & Sunset, depthMasked)
      if (!isNight) {
        const sfVig = vig.stockengut_farm || {};
        const sfBarn = sfVig.barn || [0.51413, 0.20132];
        for (let ci = 0; ci < COW_OFFSETS.length; ci++) {
          const cu = sfBarn[0] + COW_OFFSETS[ci][0];
          const cv = sfBarn[1] + COW_OFFSETS[ci][1];
          const wx = cu * worldW;
          const wy = cv * worldH;
          counts.cattle++;

          inspectables.push({
            kind: 'wildlife',
            id: `cattle:stockengut_${ci}`,
            wx,
            wy,
            radiusCss: 9,
            title: 'Rhätisches Grauvieh · Stockengut',
            sub: 'Heritage Swiss mountain cattle grazing on Stockengut Ridge',
            specs: [
              ['Breed', 'Rhätisches Grauvieh'],
              ['Farm', 'Stockengut Kilchberg'],
              ['Behavior', 'Pasture Grazing'],
              ['Status', 'ProSpecieRara Heritage'],
            ],
          });

          if (s >= 0.40) {
            const d16 = (depthMgr && depthMgr.evalWalkerD16)
              ? depthMgr.evalWalkerD16(wx, wy, 488.0, worldW, worldH, false)
              : 0;
            drawables.push({
              layer: 'ground_y',
              sortY: wy,
              depthMasked: true,
              wx,
              wy,
              bounds: { ex: 6.5 * wScale, eyUp: 6.0 * wScale, eyDn: 4.5 * wScale },
              d16,
              extraVertPx: 2.0,
              draw(targetCtx) {
                const cx = ctx.toX(cu);
                const cy = ctx.toY(cv);
                if (!ctx.inView(cx, cy, 18)) return;
                const bob = Math.sin(tSec * 0.7 + ci * 1.9) * 0.55 * s;
                const tailFlick = Math.sin(tSec * 3.1 + ci * 2.4) > 0.72 ? Math.sin(tSec * 14.0 + ci) * 0.9 * s : 0;
                const bw = Math.max(3, Math.round(3.8 * s));
                const bh = Math.max(2, Math.round(2.0 * s));

                // Ground contact shadow
                targetCtx.fillStyle = 'rgba(18, 24, 32, 0.24)';
                targetCtx.fillRect(Math.round(cx - bw * 0.45), Math.round(cy + bh * 0.45), Math.max(2, Math.round(bw * 0.95)), Math.max(1, Math.round(0.8 * s)));
                // Legs & underbelly
                targetCtx.fillStyle = shadeHex(COW_COATS[ci][1], 1.0, mode);
                targetCtx.fillRect(Math.round(cx - bw * 0.4), Math.round(cy + bh * 0.25), Math.max(1, Math.round(bw * 0.8)), Math.max(1, Math.round(bh * 0.55)));
                // Tail with deterministic flick
                targetCtx.fillRect(Math.round(cx - bw * 0.62), Math.round(cy - bh * 0.15 + tailFlick), Math.max(1, Math.round(0.7 * s)), Math.max(1, Math.round(1.2 * s)));
                // Coat body
                targetCtx.fillStyle = shadeHex(COW_COATS[ci][0], 1.0, mode);
                targetCtx.fillRect(Math.round(cx - bw * 0.5), Math.round(cy - bh * 0.5), bw, bh);
                // Head & curved pale horns
                targetCtx.fillStyle = '#3c3834';
                targetCtx.fillRect(Math.round(cx + bw * 0.45), Math.round(cy - bh * 0.22 + bob), Math.max(1.5, Math.round(1.25 * s)), Math.max(1.5, Math.round(1.25 * s)));
                targetCtx.fillStyle = '#e8e2d4';
                targetCtx.fillRect(Math.round(cx + bw * 0.5), Math.round(cy - bh * 0.62 + bob), Math.max(1.5, Math.round(1.15 * s)), Math.max(1, Math.round(0.6 * s)));
              },
            });
          }
        }
      }

      // 5. AIR: Gliding Lake Gulls (Lachmöwe, Day & Sunset)
      if (!isNight && animData && animData.ambient && animData.ambient.gulls) {
        const gulls = animData.ambient.gulls;
        const gullCol = isSunset ? '#ffe6cf' : '#f4f6fa';
        const tipCol = isSunset ? '#b49284' : '#8a94a6';
        for (let gIdx = 0; gIdx < gulls.length; gIdx++) {
          const g = gulls[gIdx];
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
          counts.gulls++;

          inspectables.push({
            kind: 'wildlife',
            id: `gull:${gIdx}`,
            wx: gx,
            wy: gy,
            radiusCss: 10,
            title: 'Lachmöwe (Black-Headed Gull)',
            sub: 'Gliding on Lake Zurich lake breeze',
            specs: [
              ['Species', 'Chroicocephalus ridibundus'],
              ['Flight', 'Coastal Thermal Glide'],
              ['Airspace', 'Lake Zurich Shoreline'],
              ['Time', isSunset ? 'Alpenglow' : 'Daytime'],
            ],
          });

          drawables.push({
            layer: 'air',
            sortY: gy,
            draw(targetCtx, drawCam) {
              const flap = Math.sin(tSec * 7.5 + gIdx * 1.9);
              const wyOff = (flap > 0.25 ? -1.4 : (flap < -0.25 ? 1.2 : 0)) * wScale;
              drawPixelRectWorld(targetCtx, drawCam, gx - 3.0 * wScale, gy + wyOff, 1.5, 1.2, tipCol, wScale);
              drawPixelRectWorld(targetCtx, drawCam, gx - 1.6 * wScale, gy + wyOff * 0.4, 1.8, 1.2, gullCol, wScale);
              drawPixelRectWorld(targetCtx, drawCam, gx, gy, 1.6, 1.4, gullCol, wScale);
              drawPixelRectWorld(targetCtx, drawCam, gx + 1.6 * wScale, gy + wyOff * 0.4, 1.8, 1.2, gullCol, wScale);
              drawPixelRectWorld(targetCtx, drawCam, gx + 3.0 * wScale, gy + wyOff, 1.5, 1.2, tipCol, wScale);
            },
          });
        }
      }

      // 6. AIR: Darting Barn Swallows (Rauchschwalben) skimming meadows & shoreline (Day & Sunset)
      if (!isNight) {
        for (let si = 0; si < SWALLOW_LOOPS.length; si++) {
          const sl = SWALLOW_LOOPS[si];
          const tA = tSec * sl.spd + sl.ph;
          // Figure-eight swoop path
          const su = sl.cu + Math.sin(tA) * sl.ru;
          const sv = sl.cv + Math.sin(tA * 2.0) * sl.rv * 0.6;
          const wx = su * worldW;
          const wy = sv * worldH;
          counts.swallows++;

          inspectables.push({
            kind: 'wildlife',
            id: sl.id,
            wx,
            wy,
            radiusCss: 9,
            title: 'Rauchschwalbe (Barn Swallow)',
            sub: 'Darting swiftly over Kilchberg meadows & lakeside',
            specs: [
              ['Species', 'Hirundo rustica (Rauchschwalbe)'],
              ['Flight', 'Agile Figure-Eight Skim'],
              ['Diet', 'Aerial Insects'],
              ['Season', 'Summer Resident'],
            ],
          });

          drawables.push({
            layer: 'air',
            sortY: wy,
            draw(targetCtx) {
              const sx = ctx.toX(su);
              const sy = ctx.toY(sv);
              if (!ctx.inView(sx, sy, 18)) return;
              const dx = Math.cos(tA) * sl.ru * worldW;
              const dy = Math.cos(tA * 2.0) * 2.0 * sl.rv * 0.6 * worldH;
              const fAng = Math.atan2(dy, dx);
              const flap = Math.sin(tSec * 18.0 + si * 2.7) * 1.1;
              const p = Math.max(0.75, s * 0.82);

              targetCtx.save();
              targetCtx.translate(sx, sy);
              targetCtx.rotate(fAng);
              targetCtx.fillStyle = '#1e3a5f';
              targetCtx.beginPath();
              targetCtx.moveTo(2.4 * p, 0);
              targetCtx.lineTo(-0.4 * p, -(3.4 + flap) * p);
              targetCtx.lineTo(-1.2 * p, -0.7 * p);
              targetCtx.lineTo(-3.2 * p, -1.0 * p);
              targetCtx.lineTo(-2.0 * p, 0);
              targetCtx.lineTo(-3.2 * p, 1.0 * p);
              targetCtx.lineTo(-1.2 * p, 0.7 * p);
              targetCtx.lineTo(-0.4 * p, (3.4 + flap) * p);
              targetCtx.closePath();
              targetCtx.fill();
              targetCtx.fillStyle = '#f8fafc';
              targetCtx.fillRect(Math.round(-0.6 * p), Math.round(-0.5 * p), Math.max(1, Math.round(1.6 * p)), Math.max(1, Math.round(1.0 * p)));
              targetCtx.restore();
            },
          });
        }
      }

      // 7. AIR: Soaring Red Kites (Rotmilan) with forked rufous tail (Day & Sunset)
      if (!isNight) {
        for (let ki = 0; ki < RED_KITES.length; ki++) {
          const rk = RED_KITES[ki];
          const ang = tSec * rk.spd + rk.ph;
          const ku = rk.cu + Math.cos(ang) * rk.ru;
          const kv = rk.cv + Math.sin(ang) * rk.rv;
          const wx = ku * worldW;
          const wy = kv * worldH;
          counts.redKites++;

          inspectables.push({
            kind: 'wildlife',
            id: rk.id,
            wx,
            wy,
            radiusCss: 13,
            title: 'Rotmilan (Red Kite)',
            sub: 'Soaring on warm thermals above Kilchberg ridge',
            specs: [
              ['Species', 'Milvus milvus (Rotmilan)'],
              ['Wingspan', '1.75 m · Forked Tail'],
              ['Flight', 'Thermal Soaring'],
              ['Status', 'Swiss Ridge Raptor'],
            ],
          });

          drawables.push({
            layer: 'air',
            sortY: wy,
            draw(targetCtx) {
              const sx = ctx.toX(ku);
              const sy = ctx.toY(kv);
              if (!ctx.inView(sx, sy, 36)) return;
              const dx = -Math.sin(ang) * rk.ru * worldW;
              const dy = Math.cos(ang) * rk.rv * worldH;
              const flightAng = Math.atan2(dy, dx);
              const wingBeat = Math.sin(tSec * 2.2 + ki * 2.5) > 0.82 ? Math.sin(tSec * 12.0 + ki) * 1.2 : 0;
              const p = Math.max(0.85, s);

              // Ground shadow offset below soaring bird
              targetCtx.save();
              targetCtx.translate(sx + 8 * p, sy + 14 * p);
              targetCtx.rotate(flightAng);
              targetCtx.fillStyle = 'rgba(18, 26, 22, 0.14)';
              targetCtx.beginPath();
              targetCtx.moveTo(4.0 * p, 0);
              targetCtx.lineTo(-0.5 * p, -6.5 * p);
              targetCtx.lineTo(-2.5 * p, -1.5 * p);
              targetCtx.lineTo(-5.5 * p, 0);
              targetCtx.lineTo(-2.5 * p, 1.5 * p);
              targetCtx.lineTo(-0.5 * p, 6.5 * p);
              targetCtx.closePath();
              targetCtx.fill();
              targetCtx.restore();

              // Soaring Red Kite silhouette with rufous wings & forked tail
              targetCtx.save();
              targetCtx.translate(sx, sy);
              targetCtx.rotate(flightAng);
              targetCtx.fillStyle = isSunset ? '#b44824' : '#9a3b1e';
              targetCtx.beginPath();
              targetCtx.moveTo(4.4 * p, 0);
              targetCtx.lineTo(0.2 * p, -(6.8 + wingBeat) * p);
              targetCtx.lineTo(-1.8 * p, -(5.4 + wingBeat * 0.7) * p);
              targetCtx.lineTo(-2.2 * p, -1.3 * p);
              targetCtx.lineTo(-6.2 * p, -2.0 * p);
              targetCtx.lineTo(-4.4 * p, 0);
              targetCtx.lineTo(-6.2 * p, 2.0 * p);
              targetCtx.lineTo(-2.2 * p, 1.3 * p);
              targetCtx.lineTo(-1.8 * p, (5.4 + wingBeat * 0.7) * p);
              targetCtx.lineTo(0.2 * p, (6.8 + wingBeat) * p);
              targetCtx.closePath();
              targetCtx.fill();

              // Pale primary wing windows & dark wingtips
              targetCtx.fillStyle = '#f5ebd8';
              targetCtx.fillRect(Math.round(-0.8 * p), Math.round(-4.6 * p), Math.max(1, Math.round(1.6 * p)), Math.max(1, Math.round(1.6 * p)));
              targetCtx.fillRect(Math.round(-0.8 * p), Math.round(3.0 * p), Math.max(1, Math.round(1.6 * p)), Math.max(1, Math.round(1.6 * p)));
              targetCtx.fillStyle = '#1e1b18';
              targetCtx.fillRect(Math.round(-1.2 * p), Math.round(-6.8 * p), Math.max(1, Math.round(1.5 * p)), Math.max(1, Math.round(1.4 * p)));
              targetCtx.fillRect(Math.round(-1.2 * p), Math.round(5.4 * p), Math.max(1, Math.round(1.5 * p)), Math.max(1, Math.round(1.4 * p)));
              targetCtx.restore();
            },
          });
        }
      }

      // 8. AIR: Bell-Triggered Flocking Church Pigeons (Stadttauben) circling Reformierte Kirche belfry
      if (!isNight && bell && bell.ringing && bell.envelope > 0.05) {
        const spire = (vig.reformierte_kirche && vig.reformierte_kirche.clock) || [0.29038, 0.31779];
        const flockCount = 6;
        const spreadFactor = Math.min(1.0, bell.cycle / 4.5);
        const radiusU = (0.0022 + spreadFactor * 0.0115);
        const radiusV = (0.0016 + spreadFactor * 0.0075);

        const flockWx = spire[0] * worldW;
        const flockWy = spire[1] * worldH;
        counts.pigeons = flockCount;

        inspectables.push({
          kind: 'wildlife',
          id: 'pigeons:reformierte_kirche',
          wx: flockWx,
          wy: flockWy,
          radiusCss: 14,
          title: 'Stadttauben Flock · Reformierte Kirche',
          sub: 'Startled by the church bells, circling the historic spire',
          specs: [
            ['Species', 'Columba livia (Church Pigeons)'],
            ['Flock Size', `${flockCount} Birds`],
            ['Trigger', 'Reformierte Kirche Bells Ringing'],
            ['Location', 'Kirchhügel Spire'],
          ],
        });

        drawables.push({
          layer: 'air',
          sortY: flockWy,
          draw(targetCtx) {
            const p = Math.max(0.8, s * 0.85);
            for (let pi = 0; pi < flockCount; pi++) {
              const ang = bell.cycle * (1.25 + (pi % 3) * 0.16) + (pi / flockCount) * Math.PI * 2;
              const rMul = 0.75 + (pi % 3) * 0.18;
              const pu = spire[0] + Math.cos(ang) * radiusU * rMul;
              const pv = spire[1] + Math.sin(ang) * radiusV * rMul - 0.0012 * spreadFactor;
              const sx = ctx.toX(pu);
              const sy = ctx.toY(pv);
              if (!ctx.inView(sx, sy, 16)) continue;

              const flap = Math.sin(tSec * 16.0 + pi * 1.9);
              const wingY = flap > 0 ? -1.1 * p : 0.8 * p;
              targetCtx.fillStyle = (pi % 2 === 0) ? '#e2e8f0' : '#94a3b8';
              targetCtx.fillRect(Math.round(sx - 1.8 * p), Math.round(sy + wingY), Math.max(1, Math.round(1.5 * p)), Math.max(1, Math.round(0.9 * p)));
              targetCtx.fillRect(Math.round(sx - 0.5 * p), Math.round(sy), Math.max(1, Math.round(1.2 * p)), Math.max(1, Math.round(1.0 * p)));
              targetCtx.fillRect(Math.round(sx + 0.5 * p), Math.round(sy + wingY), Math.max(1, Math.round(1.5 * p)), Math.max(1, Math.round(0.9 * p)));
            }
          },
        });
      }

      cachedInspectables = inspectables;
      return drawables;
    },

    getInspectables() {
      return cachedInspectables;
    },

    getAudioSignals(ctx) {
      if (ctx.isNight) return [];
      const weight = ctx.isSunset ? 0.55 : 0.85;
      return [
        { channel: 'birds', u: 0.56, v: 0.58, weight, brightnessMul: 0.9, offscreenRange: 0.35, sumMode: 'max' },
        { channel: 'birds', u: 0.32, v: 0.31, weight: weight * 0.85, brightnessMul: 0.85, offscreenRange: 0.35, sumMode: 'max' },
        { channel: 'birds', u: 0.65, v: 0.29, weight: weight * 0.85, brightnessMul: 0.85, offscreenRange: 0.35, sumMode: 'max' },
      ];
    },

    getLivingCounts() {
      return { ...counts };
    },
  };
}
