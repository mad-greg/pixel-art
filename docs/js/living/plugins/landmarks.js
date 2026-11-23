/**
 * Kilchberg Photo-Accurate 16-Landmark Vignettes Plugin (Kilchberg v13.0).
 *
 * Layers:
 *   - 'landmark': All 16 authentic Kilchberg landmark micro-vignettes:
 *       * Reformierte Kirche (tower clock, gilded Wetterhahn, stained-glass lancets, memorial candles)
 *       * Katholische Kirche St. Elisabeth (clock-free white concrete campanile uplight — ZERO clock!)
 *       * Lindt Home of Chocolate (9m golden chocolate fountain + warm chocolate-aroma steam wisps + Schokoladenplatz)
 *       * Lindt & Sprüngli historic factory (rooftop gold glow + modest wall clock)
 *       * Bendlikon ZSG Pier (animated gangplank, swaying festoon lanterns, piling ripples, vitrine)
 *       * C.F. Meyer-Haus (Arbeitszimmer study glow, gate/pergola lanterns, courtyard fountain)
 *       * Bahnhof Kilchberg (warm platform lamps & station windows)
 *       * Sanatorium Kilchberg (conservatory glints, Haus A veranda sconces, pergola/greenhouse glows)
 *       * Mönchhof & Horn (Hafenbeiz, swaying catenary Lichterketten, straw parasols, ripples)
 *       * Sulzergut Park (Swiss chalet villa glow, path lantern, Steintreppe ripples)
 *       * Gemeindehaus & Schulhaus Alte Landstrasse (dual Swiss + 4-petal Kilchberg flag, Schulhaus cupola clock, ZERO ghCenter clock)
 *       * Stockengut Ridge Farm (greenhouse/silo glints, Hofladen/barn lanterns)
 *       * Hallenbad Kilchberg (warm-ivory/aqua pool-hall glow & water-reflection shimmer)
 *       * Brölberggut Estate (manor courtyard & Tempelchen lanterns)
 *       * Villa Spinnergut & TC Kilchberg (conservatory glow & tennis-green parasols)
 *       * Morfanlage & Lakeside Park (boathouse lanterns & weeping-willow water ripples)
 *       * Warm café & terrace glows
 *   - 'air':
 *       * Church bell acoustic ripples synced to ctx.bell (evalBellState)
 *       * Warm chocolate-aroma steam wisps rising from Lindt Home of Chocolate
 *
 * Emits 'bells' audio signals synced to ctx.bell.
 * 100% deterministic seeded rendering, cached glow sprites, pure vector/pixel geometry.
 */

import { evalWithStationStop } from '../../sim/schedule.js';
import { shadeHex } from '../../render/vehicles.js';
import {
  blitGlow,
  drawMiniPersonV2,
  drawSmokePuffs,
  drawSwissClockDial,
  drawSwissOrMuniFlag,
  drawWaterRipples,
} from '../draw.js';

const COATS = ['#d9382e', '#2563eb', '#0d9488', '#d97706', '#7c3aed', '#e11d48'];
const HAIRS = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];

function drawLanternGlow(ctx, x, y, rad, isNight, colorKey = 'amber', coreHex = '#fff0be', alphaMul = 1.0) {
  const r = Math.max(2.5, rad);
  blitGlow(ctx, x, y, r, colorKey, (isNight ? 0.44 : 0.24) * alphaMul);
  const dot = Math.max(1.4, r * 0.20);
  ctx.fillStyle = coreHex;
  ctx.fillRect(Math.round(x - dot * 0.5), Math.round(y - dot * 0.5), Math.max(1, Math.round(dot)), Math.max(1, Math.round(dot)));
}

export function createLandmarksPlugin() {
  let cachedInspectables = [];

  return {
    id: 'landmarks',
    name: 'Kilchberg 16 Photo-Accurate Landmark Vignettes',
    category: 'landmarks',
    layers: ['landmark', 'air'],
    priority: 40,
    enabledByDefault: true,

    init() {
      cachedInspectables = [];
    },

    getDrawables(cam, ctx) {
      const {
        animData,
        depthMgr,
        worldW,
        worldH,
        tSec,
        mode,
        isNight,
        isSunset,
        s,
        detailAlpha,
        plaqueAlpha,
        wind,
        bell,
      } = ctx;
      const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};
      const isWater = (u, v) => (!depthMgr || !depthMgr.isWaterMaskReady || !depthMgr.isWaterMaskReady() || depthMgr.isWaterUV(u, v));

      const drawables = [];
      const inspectables = [];

      // ── 1. REFORMIERTE KIRCHE KILCHBERG ──
      const rkClock = (vig.reformierte_kirche && vig.reformierte_kirche.clock) || [0.29037, 0.31779];
      const rkSpire = (vig.reformierte_kirche && vig.reformierte_kirche.spire) || [0.29037, 0.30554];
      if (ctx.boxInView(rkClock[0] - 0.006, rkSpire[1] - 0.008, rkClock[0] + 0.007, rkClock[1] + 0.009)) {
        inspectables.push({
          kind: 'vignette',
          id: 'landmark:reformierte_kirche_clock',
          wx: rkClock[0] * worldW,
          wy: rkClock[1] * worldH,
          radiusCss: 14,
          title: 'Reformierte Kirche Kilchberg · Tower Clock',
          sub: bell && bell.ringing ? 'Church bells ringing across Kilchberg ridge' : 'Historic Swiss hilltop parish church (550.5 m spire)',
          specs: [
            ['Landmark', 'Reformierte Kirche Kilchberg'],
            ['Bells', bell && bell.ringing ? 'Ringing (Acoustic Pulse)' : 'Silent'],
            ['Spire', 'Gilded Wetterhahn Weathervane'],
            ['Heritage', 'Thomas Mann & C.F. Meyer Memorials'],
          ],
        });

        drawables.push({
          layer: 'landmark',
          sortY: rkClock[1] * worldH,
          draw(targetCtx) {
            const cx = ctx.toX(rkClock[0]);
            const cy = ctx.toY(rkClock[1]);
            const rDial = 5.4 * s;
            if (rDial >= 2.2) {
              drawSwissClockDial(targetCtx, cx, cy, rDial, tSec, { mode, style: 'church', s, detailAlpha, clock: ctx.clock });
            }
            if (!isNight) {
              const spX = ctx.toX(rkSpire[0]);
              const spY = ctx.toY(rkSpire[1]);
              const wGlint = Math.pow(0.5 + 0.5 * Math.sin(tSec * 1.9 + 0.5), 5);
              if (detailAlpha > 0.01 && wGlint > 0.20) {
                targetCtx.fillStyle = `rgba(255, 248, 196, ${(0.85 * wGlint * detailAlpha).toFixed(2)})`;
                const gs = Math.max(2, Math.round(2.4 * s));
                targetCtx.fillRect(Math.round(spX - gs * 0.5), Math.round(spY - gs * 0.5), gs, gs);
              }
            }
            if ((isSunset || isNight) && s >= 0.32) {
              const lancetCols = [
                { rgb: '251,191,36', hex: '#fde68a' },
                { rgb: '248,113,113', hex: '#fecaca' },
                { rgb: '96,165,250', hex: '#bfdbfe' },
              ];
              for (let li = 0; li < lancetCols.length; li++) {
                const lx = ctx.toX(rkClock[0] + 0.0014 + li * 0.0011);
                const ly = ctx.toY(rkClock[1] + 0.0030 + li * 0.0005);
                const flick = 0.86 + 0.14 * Math.sin(tSec * 2.4 + li * 1.7);
                const rw = Math.max(1.8, 2.2 * s);
                const rh = Math.max(3.5, 4.8 * s);
                blitGlow(targetCtx, lx, ly, 7.5 * s, lancetCols[li].rgb, (isNight ? 0.44 : 0.26) * flick);
                targetCtx.fillStyle = lancetCols[li].hex;
                targetCtx.fillRect(Math.round(lx - rw * 0.5), Math.round(ly - rh * 0.5), Math.round(rw), Math.round(rh));
              }
              if (s >= 0.35) {
                drawLanternGlow(targetCtx, ctx.toX(rkClock[0] + 0.0036), ctx.toY(rkClock[1] + 0.0062), 8.0 * s, isNight);
                drawLanternGlow(targetCtx, ctx.toX(rkClock[0] + 0.0050), ctx.toY(rkClock[1] + 0.0054), 8.0 * s, isNight);
              }
              if (plaqueAlpha > 0.01) {
                const cFlick = 0.80 + 0.20 * Math.sin(tSec * 5.2);
                drawLanternGlow(targetCtx, ctx.toX(0.2918), ctx.toY(0.3238), 3.8 * s * cFlick, isNight, '255,207,112', '#ffcf70', 0.85 * plaqueAlpha);
                drawLanternGlow(targetCtx, ctx.toX(0.2925), ctx.toY(0.3228), 3.8 * s * cFlick, isNight, '255,207,112', '#ffcf70', 0.85 * plaqueAlpha);
              }
            }
            if (plaqueAlpha > 0.01) {
              const dfGl = 0.5 + 0.5 * Math.sin(tSec * 3.4);
              targetCtx.fillStyle = `rgba(218, 246, 255, ${(0.65 * dfGl * plaqueAlpha).toFixed(2)})`;
              const dfSz = Math.max(1.5, Math.round(1.6 * s));
              targetCtx.fillRect(Math.round(ctx.toX(0.2932) - dfSz * 0.5), Math.round(ctx.toY(0.3188) - dfSz * 0.5), dfSz, dfSz);
            }
          },
        });
      }

      // ── 1b. SWISS CHURCH BELL ACOUSTIC RIPPLES (Air layer, synced to ctx.bell) ──
      if (bell && bell.ringing) {
        const seBelfry = (vig.st_elisabeth && vig.st_elisabeth.belfry) || [0.41165, 0.32675];
        const spires = [rkClock, seBelfry];
        drawables.push({
          layer: 'air',
          sortY: 0.32 * worldH,
          draw(targetCtx) {
            targetCtx.save();
            targetCtx.strokeStyle = isSunset ? '#ffd89b' : '#fff3c4';
            targetCtx.lineWidth = Math.max(1.0, 1.2 * s);
            for (let si = 0; si < spires.length; si++) {
              const sx = ctx.toX(spires[si][0]);
              const sy = ctx.toY(spires[si][1]);
              if (!ctx.inView(sx, sy, 80)) continue;
              for (let rIdx = 0; rIdx < 2; rIdx++) {
                const phase = (((bell.cycle * 0.48 + rIdx * 0.5 + si * 0.25) % 1) + 1) % 1;
                const rad = (5 + phase * 26) * s;
                targetCtx.globalAlpha = (1 - phase) * 0.34 * bell.envelope;
                targetCtx.beginPath();
                targetCtx.ellipse(sx, sy, rad, rad * 0.62, 0, 0, Math.PI * 2);
                targetCtx.stroke();
              }
            }
            targetCtx.restore();
          },
        });
      }

      // ── 2. KATHOLISCHE KIRCHE ST. ELISABETH (STRICTLY CLOCK-FREE WHITE CAMPANILE UPLIGHT) ──
      const seBelfry = (vig.st_elisabeth && vig.st_elisabeth.belfry) || [0.41165, 0.32675];
      const seApex = (vig.st_elisabeth && vig.st_elisabeth.apex) || [0.41165, 0.32232];
      if ((isSunset || isNight) && s >= 0.28 && ctx.boxInView(seBelfry[0] - 0.010, seApex[1] - 0.006, seBelfry[0] + 0.008, seBelfry[1] + 0.024)) {
        drawables.push({
          layer: 'landmark',
          sortY: seBelfry[1] * worldH,
          draw(targetCtx) {
            const bx = ctx.toX(seBelfry[0]);
            const by = ctx.toY(seBelfry[1]);
            const ax = ctx.toX(seApex[0]);
            const ay = ctx.toY(seApex[1]);
            const midY = 0.5 * (by + ay);
            const hSpan = Math.max(8, (by - ay) * 0.72 + 7 * s);
            blitGlow(targetCtx, bx, midY + 1.5 * s, Math.max(4.5, 4.8 * s), '252,240,212', isNight ? 0.34 : 0.18, hSpan);
            drawLanternGlow(targetCtx, ax, ay, 3.6 * s, isNight, '252,242,216', '#fef9e7', 0.68);
          },
        });
      }

      // ── 3. LINDT HOME OF CHOCOLATE — 9m Golden Chocolate Fountain + Warm Chocolate-Aroma Steam Wisps + Schokoladenplatz ──
      const lindtAtrium = (vig.lindt_hoc && vig.lindt_hoc.atrium) || [0.37821, 0.64638];
      const lindtPlaza = (vig.lindt_hoc && vig.lindt_hoc.plaza) || [0.37800, 0.65101];
      if (ctx.boxInView(lindtAtrium[0] - 0.007, lindtAtrium[1] - 0.005, lindtAtrium[0] + 0.007, lindtPlaza[1] + 0.008)) {
        inspectables.push({
          kind: 'vignette',
          id: 'landmark:lindt_chocolate_fountain',
          wx: lindtAtrium[0] * worldW,
          wy: lindtAtrium[1] * worldH,
          radiusCss: 16,
          title: 'Lindt Home of Chocolate · 9m Fountain',
          sub: 'World-famous 9.3m golden chocolate fountain & Schokoladenplatz',
          specs: [
            ['Architecture', 'Christ & Gantenbein (2020)'],
            ['Atrium', '9.3m Flowing Chocolate Fountain'],
            ['Plaza', 'Schokoladenplatz Café & Seating'],
            ['Location', 'Schokoladenplatz 1, Kilchberg'],
          ],
        });

        drawables.push({
          layer: 'landmark',
          sortY: lindtAtrium[1] * worldH,
          draw(targetCtx) {
            const shimmer = 0.76 + 0.24 * Math.sin(tSec * 3.4);
            const arcOffsets = [
              [-0.0018, 0.0004], [-0.0007, -0.0001], [0.0004, -0.0002], [0.0016, 0.0000],
            ];
            for (let i = 0; i < arcOffsets.length; i++) {
              const ax = ctx.toX(lindtAtrium[0] + arcOffsets[i][0]);
              const ay = ctx.toY(lindtAtrium[1] + arcOffsets[i][1]);
              const pGlow = 0.75 + 0.25 * Math.sin(tSec * 4.2 + i * 1.3);
              const rw = Math.max(3, 5.2 * s);
              const rh = Math.max(2, 3.6 * s);
              targetCtx.fillStyle = isNight
                ? `rgba(255, 206, 94, ${(0.76 * pGlow).toFixed(2)})`
                : (isSunset ? `rgba(255, 204, 102, ${(0.54 * pGlow).toFixed(2)})` : `rgba(255, 214, 118, ${(0.38 * pGlow).toFixed(2)})`);
              targetCtx.fillRect(Math.round(ax - rw * 0.5), Math.round(ay - rh * 0.5), Math.round(rw), Math.round(rh));
            }

            const fx = ctx.toX(lindtAtrium[0]);
            const fy = ctx.toY(lindtAtrium[1]);
            const colW = Math.max(2, 2.8 * s);
            const colH = Math.max(4, 7.5 * s);
            const fAlpha = isNight ? (0.86 * shimmer) : (isSunset ? (0.70 * shimmer) : 0.38);
            targetCtx.fillStyle = `rgba(245, 168, 24, ${(fAlpha * 0.85).toFixed(2)})`;
            targetCtx.fillRect(Math.round(fx - colW * 0.5), Math.round(fy - colH * 0.6), Math.round(colW), Math.round(colH));
            for (let k = 0; k < 3; k++) {
              const prog = (((tSec * 1.4 + k / 3) % 1) + 1) % 1;
              const yOff = (prog - 0.55) * 6.5 * s;
              targetCtx.fillStyle = `rgba(255, 242, 178, ${(fAlpha * (1.0 - Math.abs(prog - 0.5))).toFixed(2)})`;
              targetCtx.fillRect(Math.round(fx - colW * 0.32), Math.round(fy + yOff), Math.max(1.5, Math.round(colW * 0.65)), Math.max(1.5, Math.round(1.5 * s)));
            }

            if (isNight || isSunset) {
              const gRad = 28 * s;
              blitGlow(targetCtx, fx, ctx.toY(lindtAtrium[1] + 0.0034), gRad * 1.28, isNight ? '255,206,98' : '255,200,106', (isNight ? 0.38 : 0.24) * shimmer, gRad * 0.74, -0.15);
            }

            if ((isSunset || isNight) && s >= 0.30) {
              const uplightDu = [-0.0022, -0.0008, 0.0008, 0.0022];
              for (let ui = 0; ui < uplightDu.length; ui++) {
                const ux = ctx.toX(lindtAtrium[0] + uplightDu[ui]);
                const uy = ctx.toY(lindtAtrium[1] + 0.0016);
                const coneH = 9.5 * s;
                blitGlow(targetCtx, ux, uy - coneH * 0.35, 4.2 * s, isNight ? '255,218,126' : '255,210,122', isNight ? 0.40 : 0.24, coneH * 0.75);
              }
              const ex = ctx.toX(lindtPlaza[0]);
              const ey = ctx.toY(lindtPlaza[1] - 0.0018);
              const cw = Math.max(6, 12 * s);
              const ch = Math.max(1.5, 2.0 * s);
              targetCtx.fillStyle = isNight ? 'rgba(255, 232, 168, 0.82)' : 'rgba(255, 224, 152, 0.54)';
              targetCtx.fillRect(Math.round(ex - cw * 0.5), Math.round(ey - ch * 0.5), Math.round(cw), Math.round(ch));
            }

            if (!isNight && s >= 0.35) {
              for (let gi = 0; gi < 2; gi++) {
                const pulse = Math.pow(0.5 + 0.5 * Math.sin(tSec * 1.1 + gi * 2.4), 4);
                if (pulse < 0.15) continue;
                const gx = ctx.toX(lindtAtrium[0] + (gi === 0 ? -0.0013 : 0.0013));
                const gy = ctx.toY(lindtAtrium[1] + 0.0007);
                const gw = Math.max(1.5, 1.8 * s);
                const gh = Math.max(3, 5.2 * s);
                targetCtx.fillStyle = `rgba(255, 250, 232, ${(0.55 * pulse).toFixed(2)})`;
                targetCtx.fillRect(Math.round(gx - gw * 0.5), Math.round(gy - gh * 0.5), Math.round(gw), Math.round(gh));
              }
            }

            if (detailAlpha > 0.01) {
              const wGl = 0.65 + 0.35 * Math.sin(tSec * 4.6);
              targetCtx.fillStyle = `rgba(255, 248, 200, ${(0.88 * wGl * detailAlpha).toFixed(2)})`;
              targetCtx.fillRect(Math.round(fx - 1.1 * s), Math.round(fy - colH * 0.65), Math.max(2, Math.round(2.2 * s)), Math.max(2, Math.round(1.6 * s)));

              const benches = [[0.3772, 0.6502], [0.3786, 0.6512], [0.3798, 0.6505]];
              targetCtx.fillStyle = isNight ? '#5a4838' : '#9c7858';
              for (let bi = 0; bi < benches.length; bi++) {
                const bx = ctx.toX(benches[bi][0]);
                const by = ctx.toY(benches[bi][1]);
                targetCtx.fillRect(Math.round(bx - 1.8 * s), Math.round(by - 0.6 * s), Math.max(3, Math.round(3.6 * s)), Math.max(1.5, Math.round(1.2 * s)));
              }
              if (!isNight) {
                const parasols = [[0.3796, 0.6494], [0.3806, 0.6502]];
                for (let pi = 0; pi < parasols.length; pi++) {
                  const px = ctx.toX(parasols[pi][0]);
                  const py = ctx.toY(parasols[pi][1]);
                  targetCtx.fillStyle = 'rgba(24, 28, 32, 0.28)';
                  targetCtx.beginPath();
                  targetCtx.ellipse(px + 0.8 * s, py + 1.0 * s, 2.8 * s, 1.6 * s, 0, 0, Math.PI * 2);
                  targetCtx.fill();
                  targetCtx.fillStyle = '#efe9dc';
                  targetCtx.beginPath();
                  targetCtx.ellipse(px, py, 2.6 * s, 1.5 * s, 0, 0, Math.PI * 2);
                  targetCtx.fill();
                }
              }
            }
          },
        });

        // New v13.0 warm chocolate-aroma steam wisps gently drifting off Schokoladenplatz / atrium
        if (!isNight && s >= 0.45) {
          drawables.push({
            layer: 'air',
            sortY: lindtAtrium[1] * worldH,
            draw(targetCtx) {
              drawSmokePuffs(targetCtx, ctx.toX(lindtAtrium[0]), ctx.toY(lindtAtrium[1] - 0.0012), s * 0.72, tSec, wind, {
                count: 4,
                rate: 0.22,
                phaseOff: 0.17,
                drift: 11,
                rise: 15,
                baseSz: 1.4,
                growSz: 2.6,
                isNight: false,
                isSunset,
                alpha: 0.30,
                colRgb: isSunset ? '255, 224, 178' : '255, 240, 206',
              });
            },
          });
        }
      }

      // ── 4. LINDT & SPRÜNGLI HISTORIC FACTORY (id=1642) ──
      if (ctx.boxInView(0.364, 0.664, 0.382, 0.688)) {
        drawables.push({
          layer: 'landmark',
          sortY: 0.675 * worldH,
          draw(targetCtx) {
            if (isNight || isSunset) {
              drawLanternGlow(targetCtx, ctx.toX(0.3738), ctx.toY(0.6710), 14.0 * s, isNight, '255,214,102', '#ffe89c', 0.35);
            }
            if (detailAlpha > 0.01) {
              drawSwissClockDial(targetCtx, ctx.toX(0.3692), ctx.toY(0.6805), 2.4 * s, tSec, { mode, style: 'civic', s, detailAlpha, clock: ctx.clock });
            }
          },
        });
      }

      // ── 5. BENDLIKON ZSG PIER (Gangplank, Festoon Lights, Piling Ripples, Vitrine) ──
      const bpPax = (vig.bendlikon_pier && vig.bendlikon_pier.pax) || [0.58359, 0.57841];
      if (ctx.boxInView(bpPax[0] - 0.006, bpPax[1] - 0.006, bpPax[0] + 0.007, bpPax[1] + 0.009)) {
        let shipDocked = false;
        let dwellProg = 0;
        const vesselSim = ctx.shared && ctx.shared.vesselSim;
        if (vesselSim && typeof vesselSim.getPierDockState === 'function') {
          const dockSt = vesselSim.getPierDockState('bendlikon');
          shipDocked = !!(dockSt && dockSt.docked);
          dwellProg = (dockSt && Number.isFinite(dockSt.dwellProg)) ? dockSt.dwellProg : 0;
        } else {
          for (const sh of ((animData && animData.ships) || [])) {
            if (sh.kind === 'zsg_steamer') {
              const st = evalWithStationStop(tSec, sh.length_m, sh.speed_mps, sh.stop_frac, sh.dwell_sec, sh.phase || 0, 5.0, 6.0);
              if (st.isDwelling) {
                shipDocked = true;
                dwellProg = st.dwellProgress;
              }
            }
          }
        }
        const bpPier = (vig.bendlikon_pier && vig.bendlikon_pier.pier) || [0.5841, 0.57859];
        const bpBeacon = (vig.bendlikon_pier && vig.bendlikon_pier.beacon) || [0.587, 0.57838];

        drawables.push({
          layer: 'landmark',
          sortY: bpPier[1] * worldH,
          draw(targetCtx) {
            if (shipDocked) {
              const gpExt = dwellProg < 0.15 ? (dwellProg / 0.15) : (dwellProg > 0.85 ? (1.0 - dwellProg) / 0.15 : 1.0);
              const gpU0 = 0.5846;
              const gpV0 = 0.5805;
              const gpU1 = gpU0 + (0.5856 - gpU0) * gpExt;
              const gpV1 = gpV0 + (0.5844 - gpV0) * gpExt;
              const x0 = ctx.toX(gpU0);
              const y0 = ctx.toY(gpV0);
              const x1 = ctx.toX(gpU1);
              const y1 = ctx.toY(gpV1);
              targetCtx.strokeStyle = isNight ? '#5c4228' : '#8c6239';
              targetCtx.lineWidth = Math.max(2.2, 3.2 * s);
              targetCtx.lineCap = 'butt';
              targetCtx.beginPath();
              targetCtx.moveTo(x0, y0);
              targetCtx.lineTo(x1, y1);
              targetCtx.stroke();
              targetCtx.strokeStyle = isNight ? '#94a3b8' : '#dce2ea';
              targetCtx.lineWidth = Math.max(0.8, 0.9 * s);
              for (const hOff of [-1.4 * s, 1.4 * s]) {
                targetCtx.beginPath();
                targetCtx.moveTo(x0 + hOff, y0 - 1.5 * s);
                targetCtx.lineTo(x1 + hOff, y1 - 1.5 * s);
                targetCtx.stroke();
              }
            }

            if ((isSunset || isNight) && s >= 0.30) {
              for (let bi = 0; bi < 5; bi++) {
                const f = bi / 4;
                const sway = Math.sin(wind.wavePhase * 0.6 + bi) * 0.4 * s;
                const bx = ctx.toX(bpPier[0] + (bpBeacon[0] - bpPier[0]) * f) + sway;
                const by = ctx.toY(bpPier[1] + (bpBeacon[1] - bpPier[1]) * f) - 2.2 * s;
                drawLanternGlow(targetCtx, bx, by, 5.2 * s, isNight, '255,214,132', '#fff0b8', 0.88);
              }
            }
            if (s >= 0.32) {
              for (let pk = 0; pk < 3; pk++) {
                const pu = bpPier[0] + 0.0008 + pk * 0.0010;
                const pv = bpPier[1] + 0.0018 + pk * 0.0004;
                if (!isWater(pu, pv)) continue;
                drawWaterRipples(targetCtx, ctx.toX(pu), ctx.toY(pv), s * 0.85, tSec, {
                  count: 2,
                  speed: 0.34,
                  phaseOff: pk * 0.31,
                  minR: 1.5,
                  maxR: 4.8,
                  isNight,
                  isSunset,
                });
              }
            }
            if (detailAlpha > 0.01 && (isSunset || isNight)) {
              drawLanternGlow(targetCtx, ctx.toX(0.5836), ctx.toY(0.5789), 4.5 * s, isNight, '255,240,178', '#fffbeb', 0.88 * detailAlpha);
            }
            if ((isSunset || isNight) && isWater(bpPier[0] + 0.0016, bpPier[1] + 0.0024)) {
              const rx = ctx.toX(bpPier[0] + 0.0016);
              const ry = ctx.toY(bpPier[1] + 0.0024);
              const sh = 0.72 + 0.28 * Math.sin(tSec * 2.9);
              targetCtx.fillStyle = `rgba(255, 220, 140, ${((isNight ? 0.28 : 0.16) * sh).toFixed(2)})`;
              targetCtx.fillRect(Math.round(rx - 1.4 * s), Math.round(ry - 1.0 * s), Math.max(2, Math.round(2.8 * s)), Math.max(4, Math.round(6.0 * s)));
            }
          },
        });
      }

      // ── 6. WARM CAFÉ / TERRACE GLOWS (Bendlikon, Seebad, C.F. Meyer) ──
      const cfVig = vig.cf_meyer_haus || {};
      const cfCenter = cfVig.center || [0.35953, 0.44168];
      if (isSunset || isNight) {
        const terraces = [
          { u: 0.5818, v: 0.5768, r: 16 },
          { u: 0.4068, v: 0.7072, r: 15 },
          { u: cfCenter[0], v: cfCenter[1], r: 17 },
        ];
        for (let ti = 0; ti < terraces.length; ti++) {
          const tc = terraces[ti];
          if (!ctx.boxInView(tc.u - 0.005, tc.v - 0.005, tc.u + 0.005, tc.v + 0.005)) continue;
          drawables.push({
            layer: 'landmark',
            sortY: tc.v * worldH,
            draw(targetCtx) {
              const tx = ctx.toX(tc.u);
              const ty = ctx.toY(tc.v);
              const rad = tc.r * s;
              blitGlow(targetCtx, tx, ty, rad * 1.15, '255,198,112', isNight ? 0.30 : 0.24, rad * 0.72);
              if (isSunset && s >= 0.45) {
                for (let g = 0; g < 2; g++) {
                  const gu = tc.u + (g - 0.5) * 0.0011 + Math.sin(tSec * 0.3 + ti + g * 2.1) * 0.0002;
                  const gv = tc.v + (g === 0 ? 0.0003 : -0.0002);
                  drawMiniPersonV2(targetCtx, ctx.toX(gu), ctx.toY(gv), s * 0.86, {
                    coatCol: shadeHex(COATS[(ti * 2 + g) % COATS.length], 1.0, mode),
                    pantsCol: '#243040',
                    hairCol: HAIRS[(ti + g) % HAIRS.length],
                    isNight: false,
                    phase: tSec * 1.4 + g,
                    isChatting: true,
                    canvasW: cam.width,
                    canvasH: cam.height,
                  });
                }
              }
            },
          });
        }
      }

      // ── 7. C.F. MEYER-HAUS ──
      const cfFountain = cfVig.fountain || [0.3574, 0.4461];
      const cfPergola = cfVig.pergola || [0.35365, 0.43968];
      const cfGate = cfVig.gate || [0.36007, 0.44773];
      if (ctx.boxInView(cfPergola[0] - 0.005, cfPergola[1] - 0.005, cfGate[0] + 0.005, cfGate[1] + 0.005)) {
        drawables.push({
          layer: 'landmark',
          sortY: cfCenter[1] * worldH,
          draw(targetCtx) {
            if ((isSunset || isNight) && s >= 0.30) {
              const lampPulse = 0.90 + 0.10 * Math.sin(tSec * 1.8);
              const wDu = [-0.0006, 0.0005];
              for (let wi = 0; wi < wDu.length; wi++) {
                const wx = ctx.toX(cfCenter[0] + wDu[wi]);
                const wy = ctx.toY(cfCenter[1] - 0.0004);
                const ww = Math.max(2, 2.8 * s);
                const wh = Math.max(2.5, 3.4 * s);
                targetCtx.fillStyle = `rgba(255, 222, 144, ${((isNight ? 0.84 : 0.56) * lampPulse).toFixed(2)})`;
                targetCtx.fillRect(Math.round(wx - ww * 0.5), Math.round(wy - wh * 0.5), Math.round(ww), Math.round(wh));
              }
              if (detailAlpha > 0.01) {
                const sx = ctx.toX(cfCenter[0]);
                const sy = ctx.toY(cfCenter[1] - 0.0006);
                drawLanternGlow(targetCtx, sx, sy, 6.2 * s, isNight, '255,226,150', '#fff4cc', 0.86 * detailAlpha);
                targetCtx.fillStyle = 'rgba(54, 42, 34, 0.65)';
                targetCtx.fillRect(Math.round(sx - 0.35 * s), Math.round(sy - 1.5 * s), Math.max(1, Math.round(0.7 * s)), Math.max(2, Math.round(3.0 * s)));
              }
              drawLanternGlow(targetCtx, ctx.toX(cfGate[0]), ctx.toY(cfGate[1]), 7.5 * s, isNight);
              drawLanternGlow(targetCtx, ctx.toX(cfPergola[0]), ctx.toY(cfPergola[1]), 8.5 * s, isNight, '255,206,132', '#ffe9b8');
            }
            if (s >= 0.34) {
              const gl = 0.5 + 0.5 * Math.sin(tSec * 3.1);
              const fx = ctx.toX(cfFountain[0]);
              const fy = ctx.toY(cfFountain[1]);
              const sz = Math.max(1.5, 1.8 * s);
              targetCtx.fillStyle = isNight
                ? `rgba(186, 230, 253, ${(0.45 * gl).toFixed(2)})`
                : `rgba(232, 248, 255, ${(0.62 * gl).toFixed(2)})`;
              targetCtx.fillRect(Math.round(fx - sz * 0.5), Math.round(fy - sz * 0.5), Math.round(sz), Math.round(sz));
            }
          },
        });
      }

      // ── 8. BAHNHOF KILCHBERG (Warm Platform Lamps & Station House Windows) ──
      const bhVig = vig.bahnhof_kilchberg || { plat_sw: [0.55049, 0.50304], plat_ne: [0.56449, 0.49558] };
      const platSw = bhVig.plat_sw || [0.55049, 0.50304];
      const platNe = bhVig.plat_ne || [0.56449, 0.49558];
      if ((isNight || isSunset) && ctx.boxInView(platSw[0] - 0.005, platNe[1] - 0.006, Math.max(platNe[0], 0.583) + 0.004, platSw[1] + 0.006)) {
        drawables.push({
          layer: 'landmark',
          sortY: platSw[1] * worldH,
          draw(targetCtx) {
            for (let l = 0; l < 5; l++) {
              const f = l / 4;
              const lx = ctx.toX(platSw[0] + f * (platNe[0] - platSw[0]));
              const ly = ctx.toY(platSw[1] + f * (platNe[1] - platSw[1]));
              if (!ctx.inView(lx, ly, 36)) continue;
              blitGlow(targetCtx, lx, ly, 14 * s, isNight ? '255,224,146' : '255,214,140', isNight ? 0.36 : 0.18);
            }
            if (s >= 0.32) {
              for (let swi = 0; swi < 3; swi++) {
                const sx = ctx.toX(platSw[0] - 0.0012 + swi * 0.0012);
                const sy = ctx.toY(platSw[1] - 0.0016 - swi * 0.0005);
                const ww = Math.max(2, 2.6 * s);
                const wh = Math.max(2.2, 3.0 * s);
                targetCtx.fillStyle = isNight ? 'rgba(255, 224, 146, 0.78)' : 'rgba(255, 214, 140, 0.48)';
                targetCtx.fillRect(Math.round(sx - ww * 0.5), Math.round(sy - wh * 0.5), Math.round(ww), Math.round(wh));
              }
            }
          },
        });
      }

      // ── 9. SANATORIUM KILCHBERG ──
      const srVig = vig.sanatorium_ridge || {};
      const srPav = srVig.pavilion || [0.67423, 0.30878];
      const srPerg = srVig.pergola || [0.66334, 0.30145];
      const srGh = Array.isArray(srVig.greenhouses) && srVig.greenhouses.length >= 2
        ? srVig.greenhouses
        : [[0.6325, 0.28051], [0.62729, 0.29552]];
      if (s >= 0.28 && ctx.boxInView(0.620, 0.274, 0.682, 0.318)) {
        drawables.push({
          layer: 'landmark',
          sortY: srPav[1] * worldH,
          draw(targetCtx) {
            if (!isNight) {
              for (let gi = 0; gi < srGh.length; gi++) {
                const pulse = Math.pow(0.5 + 0.5 * Math.sin(tSec * 1.4 + gi * 2.3), 3);
                if (pulse < 0.14) continue;
                const gx = ctx.toX(srGh[gi][0]);
                const gy = ctx.toY(srGh[gi][1]);
                const gw = Math.max(3, 5.4 * s);
                const gh = Math.max(1.5, 2.2 * s);
                targetCtx.fillStyle = `rgba(244, 252, 255, ${(0.58 * pulse).toFixed(2)})`;
                targetCtx.fillRect(Math.round(gx - gw * 0.5), Math.round(gy - gh * 0.5), Math.round(gw), Math.round(gh));
              }
            }
            if (isSunset || isNight) {
              drawLanternGlow(targetCtx, ctx.toX(srPav[0]), ctx.toY(srPav[1]), 14.0 * s, isNight, '255,218,144', '#fff0c4');
              const sconceDu = [-0.0018, -0.0006, 0.0006, 0.0018];
              for (let si = 0; si < sconceDu.length; si++) {
                drawLanternGlow(targetCtx, ctx.toX(srPav[0] + sconceDu[si]), ctx.toY(srPav[1] + sconceDu[si] * 0.35), 4.8 * s, isNight);
              }
              drawLanternGlow(targetCtx, ctx.toX(srPerg[0] - 0.0014), ctx.toY(srPerg[1] + 0.0005), 7.5 * s, isNight);
              drawLanternGlow(targetCtx, ctx.toX(srPerg[0] + 0.0014), ctx.toY(srPerg[1] - 0.0005), 7.5 * s, isNight);
              for (let gi = 0; gi < srGh.length; gi++) {
                drawLanternGlow(targetCtx, ctx.toX(srGh[gi][0]), ctx.toY(srGh[gi][1]), 9.0 * s, isNight, '255,230,168', '#fef3c7', 0.62);
              }
            }
          },
        });
      }

      // ── 10. MÖNCHHOF & HORN (Hafenbeiz, Swaying Catenary Lichterketten, Straw Parasols) ──
      const mhVig = vig.moenchhof_horn || {};
      const mhBeiz = mhVig.hafenbeiz || [0.84576, 0.32859];
      const mhTerr = mhVig.terrace || [0.8485, 0.3430];
      const mhBh = mhVig.boathouse || [0.85059, 0.33823];
      const mhWater = mhVig.water || [0.85493, 0.34786];
      if (s >= 0.28 && ctx.boxInView(0.838, 0.320, 0.864, 0.356)) {
        drawables.push({
          layer: 'landmark',
          sortY: mhTerr[1] * worldH,
          draw(targetCtx) {
            if (isSunset || isNight) {
              drawLanternGlow(targetCtx, ctx.toX(mhBeiz[0]), ctx.toY(mhBeiz[1]), 11.0 * s, isNight, '255,204,124', '#ffe8b2');
              const x0 = ctx.toX(mhTerr[0] - 0.0022);
              const y0 = ctx.toY(mhTerr[1] - 0.0008);
              const x1 = ctx.toX(mhTerr[0] + 0.0022);
              const y1 = ctx.toY(mhTerr[1] + 0.0006);
              const sag = (1.8 + 0.35 * Math.sin(wind.wavePhase * 0.7)) * s;
              targetCtx.strokeStyle = 'rgba(42, 36, 30, 0.65)';
              targetCtx.lineWidth = Math.max(0.7, 0.45 * s);
              targetCtx.beginPath();
              targetCtx.moveTo(x0, y0);
              targetCtx.quadraticCurveTo(0.5 * (x0 + x1), 0.5 * (y0 + y1) + sag * 2, x1, y1);
              targetCtx.stroke();
              for (let fi = 0; fi < 7; fi++) {
                const ft = fi / 6;
                const omt = 1 - ft;
                const fx = omt * omt * x0 + 2 * omt * ft * (0.5 * (x0 + x1)) + ft * ft * x1;
                const fy = omt * omt * y0 + 2 * omt * ft * (0.5 * (y0 + y1) + sag * 2) + ft * ft * y1;
                drawLanternGlow(targetCtx, fx, fy, 4.6 * s, isNight, '255,216,122', '#ffd87a', 0.88);
              }
              drawLanternGlow(targetCtx, ctx.toX(mhBh[0]), ctx.toY(mhBh[1]), 7.8 * s, isNight);
              if (isWater(mhWater[0], mhWater[1])) {
                const rx = ctx.toX(mhWater[0]);
                const ry = ctx.toY(mhWater[1]);
                const sh = 0.72 + 0.28 * Math.sin(tSec * 2.8);
                targetCtx.fillStyle = `rgba(255, 216, 138, ${((isNight ? 0.28 : 0.16) * sh).toFixed(2)})`;
                targetCtx.fillRect(Math.round(rx - 1.5 * s), Math.round(ry - 1.0 * s), Math.max(2, Math.round(3.0 * s)), Math.max(4, Math.round(6.5 * s)));
              }
            }
            if (detailAlpha > 0.01 && !isNight) {
              for (let pi = 0; pi < 3; pi++) {
                const px = ctx.toX(mhTerr[0] - 0.0012 + pi * 0.0012);
                const py = ctx.toY(mhTerr[1] - 0.0003 + (pi % 2) * 0.0008);
                targetCtx.fillStyle = '#c6ae7c';
                targetCtx.beginPath();
                targetCtx.ellipse(px, py, 2.4 * s, 1.4 * s, 0, 0, Math.PI * 2);
                targetCtx.fill();
              }
            }
            if (isWater(mhWater[0], mhWater[1])) {
              drawWaterRipples(targetCtx, ctx.toX(mhWater[0]), ctx.toY(mhWater[1]), s, tSec, {
                count: 2,
                speed: 0.34,
                phaseOff: 0.22,
                minR: 1.5,
                maxR: 5.2,
                isNight,
                isSunset,
              });
            }
          },
        });
      }

      // ── 11. SULZERGUT PARK ──
      const sgVig = vig.sulzergut_park || {};
      const sgVilla = sgVig.villa || [0.31801, 0.78779];
      const sgPathLamp = (Array.isArray(sgVig.boathouses) && sgVig.boathouses.length >= 1)
        ? sgVig.boathouses[0]
        : [0.32419, 0.78018];
      const sgWater = sgVig.water || [0.33532, 0.79519];
      if (s >= 0.28 && ctx.boxInView(0.310, 0.764, 0.344, 0.804)) {
        drawables.push({
          layer: 'landmark',
          sortY: sgVilla[1] * worldH,
          draw(targetCtx) {
            if (isSunset || isNight) {
              drawLanternGlow(targetCtx, ctx.toX(sgVilla[0]), ctx.toY(sgVilla[1]), 12.0 * s, isNight, '255,214,136', '#ffedb8');
              drawLanternGlow(targetCtx, ctx.toX(sgPathLamp[0]), ctx.toY(sgPathLamp[1]), 6.0 * s, isNight);
              const refU = sgPathLamp[0] + 0.0014;
              const refV = sgPathLamp[1] + 0.0022;
              if (isWater(refU, refV)) {
                const shb = 0.72 + 0.28 * Math.sin(tSec * 2.4);
                targetCtx.fillStyle = `rgba(255, 214, 136, ${((isNight ? 0.24 : 0.14) * shb).toFixed(2)})`;
                targetCtx.fillRect(Math.round(ctx.toX(refU) - 1.1 * s), Math.round(ctx.toY(refV) - 0.8 * s), Math.max(2, Math.round(2.2 * s)), Math.max(3, Math.round(5.0 * s)));
              }
              if (isWater(sgWater[0], sgWater[1])) {
                const sh = 0.74 + 0.26 * Math.sin(tSec * 2.5 + 1.1);
                targetCtx.fillStyle = `rgba(255, 214, 136, ${((isNight ? 0.24 : 0.14) * sh).toFixed(2)})`;
                targetCtx.fillRect(Math.round(ctx.toX(sgWater[0]) - 1.4 * s), Math.round(ctx.toY(sgWater[1]) - 1.0 * s), Math.max(2, Math.round(2.8 * s)), Math.max(4, Math.round(6.0 * s)));
              }
            }
            if (isWater(sgWater[0], sgWater[1])) {
              drawWaterRipples(targetCtx, ctx.toX(sgWater[0]), ctx.toY(sgWater[1]), s, tSec, {
                count: 2,
                speed: 0.34,
                phaseOff: 0.48,
                isNight,
                isSunset,
              });
            }
            if (isWater(0.3278, 0.7860)) {
              drawWaterRipples(targetCtx, ctx.toX(0.3278), ctx.toY(0.7860), s * 0.85, tSec, {
                count: 2,
                speed: 0.34,
                phaseOff: 0.12,
                isNight,
                isSunset,
              });
            }
          },
        });
      }

      // ── 12. GEMEINDEHAUS & SCHULHAUS ALTE LANDSTRASSE (Dual Swiss + 4-Petal Kilchberg Flag, ZERO ghCenter Clock) ──
      const ghVig = vig.gemeindehaus_alte_landstr || {};
      const ghCenter = ghVig.center || [0.5628, 0.36729];
      const ghFlagSwiss = ghVig.flag_swiss || [0.55929, 0.3772];
      const ghFlagMuni = ghVig.flag_muni || [0.56104, 0.37876];
      const ghSchul = ghVig.schulhaus || [0.53697, 0.37511];
      if (ctx.boxInView(0.530, 0.350, 0.570, 0.386)) {
        drawables.push({
          layer: 'landmark',
          sortY: ghCenter[1] * worldH,
          draw(targetCtx) {
            drawSwissOrMuniFlag(targetCtx, ctx.toX(ghFlagSwiss[0]), ctx.toY(ghFlagSwiss[1]), s, tSec, wind, 'swiss', { isNight, phaseIdx: 1 });
            drawSwissOrMuniFlag(targetCtx, ctx.toX(ghFlagMuni[0]), ctx.toY(ghFlagMuni[1]), s, tSec, wind, 'kilchberg', { isNight, phaseIdx: 3 });

            if ((isSunset || isNight) && s >= 0.28) {
              drawLanternGlow(targetCtx, ctx.toX(ghCenter[0]), ctx.toY(ghCenter[1]), 13.0 * s, isNight, '255,222,148', '#fff2c6');
              for (let ci = 0; ci < 3; ci++) {
                const sx = ctx.toX(ghSchul[0] - 0.0014 + ci * 0.0014);
                const sy = ctx.toY(ghSchul[1] + (ci - 1) * 0.0004);
                const ww = Math.max(2, 2.8 * s);
                const wh = Math.max(2.2, 3.0 * s);
                targetCtx.fillStyle = isNight ? 'rgba(255, 224, 146, 0.78)' : 'rgba(255, 214, 140, 0.48)';
                targetCtx.fillRect(Math.round(sx - ww * 0.5), Math.round(sy - wh * 0.5), Math.round(ww), Math.round(wh));
              }
            }
            // Schulhaus Alte Landstrasse (120) Dachreiter cupola clock (Gemeindehaus 110 has NO clock)
            if (detailAlpha > 0.01) {
              drawSwissClockDial(targetCtx, ctx.toX(ghSchul[0]), ctx.toY(ghSchul[1] - 0.0182), 2.2 * s, tSec, { mode, style: 'civic', s, detailAlpha, clock: ctx.clock });
            }
          },
        });
      }

      // ── 13. STOCKENGUT RIDGE FARM (Glints & Lanterns; Grauvieh cattle live in wildlife.js) ──
      const sfVig = vig.stockengut_farm || {};
      const sfBarn = sfVig.barn || [0.51413, 0.20132];
      const sfHof = sfVig.hofladen || [0.51102, 0.2083];
      const sfSilos = sfVig.silos || [0.49311, 0.19621];
      const sfGh = sfVig.greenhouse || [0.50479, 0.22103];
      if (s >= 0.28 && ctx.boxInView(0.484, 0.170, 0.542, 0.230)) {
        drawables.push({
          layer: 'landmark',
          sortY: sfBarn[1] * worldH,
          draw(targetCtx) {
            if (!isNight) {
              const gPulse = Math.pow(0.5 + 0.5 * Math.sin(tSec * 1.3 + 0.8), 3);
              if (gPulse >= 0.14) {
                const gx = ctx.toX(sfGh[0]);
                const gy = ctx.toY(sfGh[1]);
                targetCtx.fillStyle = `rgba(244, 252, 255, ${(0.54 * gPulse).toFixed(2)})`;
                targetCtx.fillRect(Math.round(gx - 2.4 * s), Math.round(gy - 1.0 * s), Math.max(3, Math.round(4.8 * s)), Math.max(1.5, Math.round(2.0 * s)));
              }
              const sPulse = Math.pow(0.5 + 0.5 * Math.sin(tSec * 0.9 + 2.1), 4);
              if (sPulse >= 0.18) {
                const sx = ctx.toX(sfSilos[0]);
                const sy = ctx.toY(sfSilos[1]);
                targetCtx.fillStyle = `rgba(248, 250, 252, ${(0.52 * sPulse).toFixed(2)})`;
                targetCtx.fillRect(Math.round(sx - 1.2 * s), Math.round(sy - 3.2 * s), Math.max(1.5, Math.round(1.6 * s)), Math.max(3, Math.round(4.4 * s)));
              }
            }
            if (isSunset || isNight) {
              drawLanternGlow(targetCtx, ctx.toX(sfHof[0]), ctx.toY(sfHof[1]), 9.5 * s, isNight, '255,210,134', '#ffebb8');
              drawLanternGlow(targetCtx, ctx.toX(sfBarn[0]), ctx.toY(sfBarn[1]), 10.5 * s, isNight, '255,198,118', '#ffe4ad', 0.72);
              drawLanternGlow(targetCtx, ctx.toX(sfGh[0]), ctx.toY(sfGh[1]), 7.8 * s, isNight, '255,228,162', '#fef3c7', 0.55);
            }
          },
        });
      }

      // ── 14. HALLENBAD KILCHBERG & SPORTANLAGE HOCHWEID ──
      const hhVig = vig.hallenbad_hochweid || {};
      const hhPool = hhVig.pool_hall || [0.35797, 0.23771];
      const hhEntry = hhVig.entry || [0.3472, 0.2335];
      if (s >= 0.28 && ctx.boxInView(0.298, 0.196, 0.372, 0.256)) {
        drawables.push({
          layer: 'landmark',
          sortY: hhPool[1] * worldH,
          draw(targetCtx) {
            const px = ctx.toX(hhPool[0]);
            const py = ctx.toY(hhPool[1]);
            const aqPulse = 0.84 + 0.16 * Math.sin(tSec * 2.6);
            const pw = Math.max(7, 13.5 * s);
            const ph = Math.max(2, 3.0 * s);
            if (isSunset || isNight) {
              const aRad = 18 * s;
              blitGlow(targetCtx, px, py, aRad * 1.25, '210,236,232', (isNight ? 0.38 : 0.22) * aqPulse, aRad * 0.72, -0.18);
            }
            targetCtx.fillStyle = isNight
              ? `rgba(232, 240, 228, ${(0.55 * aqPulse).toFixed(2)})`
              : (isSunset ? `rgba(216, 228, 220, ${(0.38 * aqPulse).toFixed(2)})` : `rgba(112, 186, 198, ${(0.18 * aqPulse).toFixed(2)})`);
            targetCtx.fillRect(Math.round(px - pw * 0.5), Math.round(py - ph * 0.5), Math.round(pw), Math.round(ph));
            for (let ci = 0; ci < 4; ci++) {
              const drift = (((tSec * 0.24 + ci * 0.25) % 1) + 1) % 1;
              const cx = px - pw * 0.42 + drift * pw * 0.84;
              const cAlpha = Math.sin(drift * Math.PI) * (isNight ? 0.46 : 0.32);
              targetCtx.fillStyle = `rgba(210, 244, 246, ${cAlpha.toFixed(2)})`;
              targetCtx.fillRect(Math.round(cx), Math.round(py - ph * 0.38), Math.max(1.5, Math.round(1.4 * s)), Math.max(1.5, Math.round(ph * 0.76)));
            }
            if (isSunset || isNight) {
              drawLanternGlow(targetCtx, ctx.toX(hhEntry[0]), ctx.toY(hhEntry[1]), 9.0 * s, isNight);
            }
          },
        });
      }

      // ── 15. BRÖLBERGGUT ESTATE ──
      const bbVig = vig.broelberggut_estate || {};
      const bbManor = bbVig.manor || [0.30114, 0.48014];
      const bbTemp = bbVig.tempelchen || [0.30338, 0.46359];
      if ((isSunset || isNight) && s >= 0.28 && ctx.boxInView(0.294, 0.456, 0.312, 0.494)) {
        drawables.push({
          layer: 'landmark',
          sortY: bbManor[1] * worldH,
          draw(targetCtx) {
            drawLanternGlow(targetCtx, ctx.toX(bbManor[0]), ctx.toY(bbManor[1]), 9.5 * s, isNight, '255,218,144', '#fff0c2');
            drawLanternGlow(targetCtx, ctx.toX(bbTemp[0]), ctx.toY(bbTemp[1]), 5.5 * s, isNight, '255,217,132', '#ffd984', 0.65);
          },
        });
      }

      // ── 16. VILLA SPINNERGUT & TC KILCHBERG CLUBHOUSE ──
      const vsVig = vig.villa_spinnergut_tc || {};
      const vsVilla = vsVig.villa || [0.15607, 0.3854];
      const vsPav = vsVig.pavilion || [0.14832, 0.38804];
      const vsClub = vsVig.clubhouse || [0.17162, 0.35526];
      if (s >= 0.28 && ctx.boxInView(0.142, 0.348, 0.178, 0.396)) {
        drawables.push({
          layer: 'landmark',
          sortY: vsVilla[1] * worldH,
          draw(targetCtx) {
            if (!isNight) {
              const vPulse = Math.pow(0.5 + 0.5 * Math.sin(tSec * 1.05 + 0.4), 4);
              if (vPulse >= 0.18) {
                const vx = ctx.toX(vsVilla[0]);
                const vy = ctx.toY(vsVilla[1]);
                targetCtx.fillStyle = `rgba(255, 250, 234, ${(0.52 * vPulse).toFixed(2)})`;
                targetCtx.fillRect(Math.round(vx - 1.8 * s), Math.round(vy - 1.2 * s), Math.max(2, Math.round(3.6 * s)), Math.max(1.5, Math.round(2.4 * s)));
              }
              if (detailAlpha > 0.01) {
                const pCols = ['#1e8c4c', '#249854'];
                for (let pi = 0; pi < 2; pi++) {
                  targetCtx.fillStyle = pCols[pi];
                  targetCtx.beginPath();
                  targetCtx.ellipse(ctx.toX(vsClub[0] - 0.0008 + pi * 0.0016), ctx.toY(vsClub[1] + 0.0012), 2.3 * s, 1.4 * s, 0, 0, Math.PI * 2);
                  targetCtx.fill();
                }
              }
            }
            if (isSunset || isNight) {
              drawLanternGlow(targetCtx, ctx.toX(vsVilla[0]), ctx.toY(vsVilla[1]), 13.0 * s, isNight, '255,214,138', '#ffedb8');
              for (let cb = -1; cb <= 1; cb++) {
                targetCtx.fillStyle = isNight ? 'rgba(255, 216, 136, 0.80)' : 'rgba(255, 216, 136, 0.48)';
                targetCtx.fillRect(Math.round(ctx.toX(vsVilla[0] + cb * 0.0005) - 0.9 * s), Math.round(ctx.toY(vsVilla[1] + 0.0006) - 1.4 * s), Math.max(1.5, Math.round(1.8 * s)), Math.max(2, Math.round(2.8 * s)));
              }
              drawLanternGlow(targetCtx, ctx.toX(vsPav[0]), ctx.toY(vsPav[1]), 8.0 * s, isNight);
              drawLanternGlow(targetCtx, ctx.toX(vsClub[0]), ctx.toY(vsClub[1]), 10.5 * s, isNight, '255,224,148', '#fff0c4');
            }
          },
        });
      }

      // ── 17. MORFANLAGE & LAKESIDE PARK ──
      const maVig = vig.morfanlage_promenade || {};
      const maBh = Array.isArray(maVig.boathouses) && maVig.boathouses.length >= 2
        ? maVig.boathouses
        : [[0.67922, 0.48396], [0.67668, 0.48457]];
      const maWater = maVig.water || [0.66879, 0.50459];
      if (s >= 0.28 && ctx.boxInView(0.654, 0.478, 0.686, 0.512)) {
        drawables.push({
          layer: 'landmark',
          sortY: maWater[1] * worldH,
          draw(targetCtx) {
            if (isSunset || isNight) {
              for (let hi = 0; hi < maBh.length; hi++) {
                drawLanternGlow(targetCtx, ctx.toX(maBh[hi][0]), ctx.toY(maBh[hi][1]), 5.2 * s, isNight);
              }
              if (isWater(maWater[0], maWater[1])) {
                const sh = 0.72 + 0.28 * Math.sin(tSec * 2.6 + 2.0);
                targetCtx.fillStyle = `rgba(255, 218, 140, ${((isNight ? 0.26 : 0.14) * sh).toFixed(2)})`;
                targetCtx.fillRect(Math.round(ctx.toX(maWater[0]) - 1.4 * s), Math.round(ctx.toY(maWater[1]) - 1.0 * s), Math.max(2, Math.round(2.8 * s)), Math.max(4, Math.round(6.0 * s)));
              }
            }
            if (isWater(maWater[0], maWater[1])) {
              drawWaterRipples(targetCtx, ctx.toX(maWater[0]), ctx.toY(maWater[1]), s, tSec, {
                count: 2,
                speed: 0.34,
                phaseOff: 0.67,
                isNight,
                isSunset,
              });
            }
            const willowPts = [[0.6648, 0.5024], [0.6688, 0.5046], [0.6732, 0.4998]];
            for (let wi = 0; wi < willowPts.length; wi++) {
              if (!isWater(willowPts[wi][0], willowPts[wi][1])) continue;
              drawWaterRipples(targetCtx, ctx.toX(willowPts[wi][0]), ctx.toY(willowPts[wi][1]), s * 0.72, tSec, {
                count: 2,
                speed: 0.34,
                phaseOff: 0.19 + wi * 0.29,
                isNight,
                isSunset,
              });
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
      const { animData, bell, isNight, isSunset } = ctx;
      if (isNight || !bell || bell.envelope <= 0.01) return [];
      const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};
      const rk = (vig.reformierte_kirche && vig.reformierte_kirche.belfry) || [0.29272, 0.3162];
      const se = (vig.st_elisabeth && vig.st_elisabeth.belfry) || [0.40667, 0.3425];
      const weight = bell.envelope * (isSunset ? 1.0 : 0.85);
      return [
        { channel: 'bells', u: rk[0], v: rk[1], weight, offscreenRange: 0.28, sumMode: 'max' },
        { channel: 'bells', u: se[0], v: se[1], weight, offscreenRange: 0.28, sumMode: 'max' },
      ];
    },

    getLivingCounts() {
      return { landmarkVignettes: 16 };
    },
  };
}
