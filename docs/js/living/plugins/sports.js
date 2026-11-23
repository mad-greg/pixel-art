/**
 * Kilchberg Sports Courts & Fields Plugin (Kilchberg v13.0).
 *
 * Layers:
 *   - 'ground_y' (depthMasked: true, extraVertPx: 2.0):
 *       * TC Kilchberg 3 clay tennis courts: live players + umpire + sideline spectators
 *       * Sportplatz Hochweid FC Kilchberg match: 12 players + sideline spectators & linesman
 *       * All 5 animData.network.extra_sports fields (tennis, football, multisport scrimmage)
 *   - 'landmark':
 *       * Animated tennis & football balls with crisp multi-dot rally trails
 *       * Night floodlight beams (Sportplatz Hochweid 4 masts + TC Kilchberg 2 all-weather courts)
 *         rendered via cached blitGlow sprites
 *
 * 100% deterministic seeded rendering, cached glow sprites, pure vector/pixel geometry.
 * Counts reported under livingCounts (sportsPlayers, sportsSpectators), NEVER simStats.pedestrians.
 */

import { shadeHex } from '../../render/vehicles.js';
import { blitGlow, drawMiniPersonV2 } from '../draw.js';

const HAIRS = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];
const SPEC_COATS = ['#334155', '#0d9488', '#d97706', '#64748b', '#7c3aed', '#2563eb'];

// Exact isometric ground-to-UV projection (azimuth=102 deg, pitch=30 deg)
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

function humanizeSportsFieldName(fld, idx) {
  const id = String(fld.id || '').toLowerCase();
  if (id.includes('gemeindehaus')) return 'Schulhaus Alte Landstrasse · Multisport Court';
  if (id.includes('upper')) return 'Sportanlage Hochweid · Upper Pitch';
  if (fld.kind === 'tennis') return `Kilchberg Clay Tennis Court #${idx + 1}`;
  if (fld.kind === 'football') return `Kilchberg Community Football Pitch #${idx + 1}`;
  return `Kilchberg Village Sports Court #${idx + 1}`;
}

export function createSportsPlugin() {
  let counts = { sportsPlayers: 0, sportsSpectators: 0 };
  let cachedInspectables = [];

  return {
    id: 'sports',
    name: 'TC Kilchberg Tennis, Sportplatz Hochweid & Village Sports',
    category: 'people',
    layers: ['ground_y', 'landmark'],
    priority: 32,
    enabledByDefault: true,

    init() {
      counts = { sportsPlayers: 0, sportsSpectators: 0 };
      cachedInspectables = [];
    },

    getDrawables(cam, ctx) {
      const { animData, depthMgr, worldW, worldH, wScale, tSec, mode, isNight, isSunset, s } = ctx;
      const vig = (animData && animData.ambient && animData.ambient.vignettes) || {};
      const walkerBounds = { ex: 4.5 * wScale, eyUp: 9.5 * wScale, eyDn: 3.5 * wScale };

      const drawables = [];
      const inspectables = [];
      counts = { sportsPlayers: 0, sportsSpectators: 0 };

      const pushPerson = (u, v, d16, scaleMul, coat, pants, hair, phase, opts = {}) => {
        const wx = u * worldW;
        const wy = v * worldH;
        const useMask = !!(depthMgr && d16);
        drawables.push({
          layer: 'ground_y',
          sortY: wy,
          depthMasked: useMask,
          wx,
          wy,
          bounds: walkerBounds,
          d16: d16 || 0,
          extraVertPx: 2.0,
          draw(targetCtx) {
            drawMiniPersonV2(targetCtx, ctx.toX(u), ctx.toY(v), s * scaleMul, {
              coatCol: coat,
              pantsCol: pants,
              hairCol: hair,
              isNight: false,
              phase,
              hatCol: opts.hatCol || null,
              isWaving: !!opts.isWaving,
              isChatting: !!opts.isChatting,
              canvasW: cam.width,
              canvasH: cam.height,
            });
          },
        });
      };

      // =====================================================================
      // 1. TC KILCHBERG CLAY TENNIS COURTS (3 Courts + Umpire + Spectators + Night LEDs)
      // =====================================================================
      const tcSrc = Array.isArray(vig.tc_kilchberg) && vig.tc_kilchberg.length >= 3
        ? vig.tc_kilchberg
        : [
          { sw: [0.17388, 0.34389], ne: [0.17966, 0.33951], lat: [0.00074, 0.00125] },
          { sw: [0.17697, 0.34873], ne: [0.18262, 0.34423], lat: [0.00076, 0.00123] },
          { sw: [0.16390, 0.35396], ne: [0.16970, 0.34942], lat: [0.00076, 0.00124] },
        ];

      if (!isNight) {
        counts.sportsPlayers += tcSrc.length * 2;
        counts.sportsSpectators += 3;
      }

      if (ctx.boxInView(0.156, 0.334, 0.188, 0.362)) {
        if (isNight) {
          // Subtle evening LED floodlight pools on 2 all-weather TC clay courts
          drawables.push({
            layer: 'landmark',
            sortY: 0.345 * worldH,
            draw(targetCtx) {
              for (let ci = 0; ci < Math.min(2, tcSrc.length); ci++) {
                const tc = tcSrc[ci];
                if (!tc) continue;
                const hasCenter = Array.isArray(tc.c) && tc.c.length >= 2;
                const hasBounds = Array.isArray(tc.sw) && tc.sw.length >= 2 && Array.isArray(tc.ne) && tc.ne.length >= 2;
                if (!hasCenter && !hasBounds) continue;
                const cx = hasCenter ? tc.c[0] : (tc.sw[0] + tc.ne[0]) * 0.5;
                const cy = hasCenter ? tc.c[1] : (tc.sw[1] + tc.ne[1]) * 0.5;
                blitGlow(targetCtx, ctx.toX(cx), ctx.toY(cy), 16 * s, '248,250,252', 0.24, 11 * s, -0.2);
              }
            },
          });
        } else {
          const tcMeta = [{ ph: 0.0, freq: 1.55 }, { ph: 1.3, freq: 1.42 }, { ph: 2.1, freq: 1.36 }];
          const whiteKit = isSunset ? '#ffe8d4' : '#f4f7fa';

          inspectables.push({
            kind: 'sport',
            id: 'sports:tc_kilchberg',
            wx: ((tcSrc[0].sw[0] + tcSrc[0].ne[0]) * 0.5) * worldW,
            wy: ((tcSrc[0].sw[1] + tcSrc[0].ne[1]) * 0.5) * worldH,
            radiusCss: 15,
            title: 'TC Kilchberg · Clay Court Tennis Match',
            sub: 'Live singles rallies across 3 clay courts at Villa Spinnergut',
            specs: [
              ['Club', 'Tennisclub Kilchberg'],
              ['Surface', 'Red Clay (3 Active Courts)'],
              ['Activity', 'Live Singles Rallies'],
              ['Spectators', 'Umpire & Sideline Guests'],
            ],
          });

          for (let ci = 0; ci < tcSrc.length; ci++) {
            const c = tcSrc[ci];
            const m = tcMeta[ci % tcMeta.length];
            if (!ctx.boxInView(c.sw[0] - 0.003, c.ne[1] - 0.004, c.ne[0] + 0.003, c.sw[1] + 0.004)) continue;

            const cyc = (((tSec * m.freq + m.ph) % 2.0) + 2.0) % 2.0;
            const ballF = cyc < 1.0 ? cyc : (2.0 - cyc);
            const latA = Math.sin(tSec * 0.78 + ci * 2.4) * 0.68;
            const latB = Math.cos(tSec * 0.85 + ci * 1.7) * 0.68;

            const uA = c.sw[0] + c.lat[0] * latA;
            const vA = c.sw[1] + c.lat[1] * latA;
            const uB = c.ne[0] + c.lat[0] * latB;
            const vB = c.ne[1] + c.lat[1] * latB;
            const shortCol = ci === 0 ? '#1e3a5f' : (ci === 1 ? '#991b1b' : '#166534');
            const d16B = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(uB * worldW, vB * worldH, 476.0, worldW, worldH, false) : 0;
            const d16A = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(uA * worldW, vA * worldH, 476.0, worldW, worldH, false) : 0;

            pushPerson(uB, vB, d16B, 0.90, whiteKit, shortCol, HAIRS[ci % HAIRS.length], tSec * 10.0 + 1.0);
            pushPerson(uA, vA, d16A, 0.90, whiteKit, '#1e3a5f', HAIRS[(ci + 2) % HAIRS.length], tSec * 10.0);

            // Subtle court-side umpire & spectator on Court 1
            if (ci === 0 && s >= 0.45) {
              const midU = (c.sw[0] + c.ne[0]) * 0.5 + c.lat[0] * 1.38;
              const midV = (c.sw[1] + c.ne[1]) * 0.5 + c.lat[1] * 1.38;
              const d16U = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(midU * worldW, midV * worldH, 476.5, worldW, worldH, false) : 0;
              pushPerson(midU, midV, d16U, 0.84, shadeHex('#1e293b', 1.0, mode), '#334155', HAIRS[3], 0, { hatCol: '#f8fafc' });

              for (let sp = 0; sp < 2; sp++) {
                const su = midU + (sp === 0 ? -0.0011 : 0.0011);
                const sv = midV + (sp === 0 ? 0.0008 : -0.0008);
                const d16S = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(su * worldW, sv * worldH, 476.0, worldW, worldH, false) : 0;
                pushPerson(su, sv, d16S, 0.82, shadeHex(SPEC_COATS[sp], 1.0, mode), '#243040', HAIRS[(sp + 1) % HAIRS.length], tSec * 1.2 + sp, { isChatting: true });
              }
            }

            // Ball + crisp 3-dot rally trail on landmark layer
            drawables.push({
              layer: 'landmark',
              sortY: Math.max(vA, vB) * worldH,
              draw(targetCtx) {
                const dirSign = cyc < 1.0 ? -1 : 1;
                const bSz = Math.max(1.6, 1.8 * s);
                // Rally trail dots behind ball
                for (let tr = 3; tr >= 1; tr--) {
                  const tf = Math.max(0, Math.min(1, ballF + dirSign * tr * 0.065));
                  const tLat = latA * (1 - tf) + latB * tf;
                  const tu = c.sw[0] + (c.ne[0] - c.sw[0]) * tf + c.lat[0] * tLat;
                  const tv = c.sw[1] + (c.ne[1] - c.sw[1]) * tf + c.lat[1] * tLat;
                  const tArc = Math.sin(tf * Math.PI) * 8.5 * s;
                  const trSz = Math.max(1, Math.round(bSz * (0.78 - tr * 0.14)));
                  targetCtx.fillStyle = `rgba(217, 255, 59, ${(0.42 - tr * 0.10).toFixed(2)})`;
                  targetCtx.fillRect(Math.round(ctx.toX(tu) - trSz * 0.5), Math.round(ctx.toY(tv) - tArc - trSz * 0.5), trSz, trSz);
                }

                const ballLat = latA * (1 - ballF) + latB * ballF;
                const bu = c.sw[0] + (c.ne[0] - c.sw[0]) * ballF + c.lat[0] * ballLat;
                const bv = c.sw[1] + (c.ne[1] - c.sw[1]) * ballF + c.lat[1] * ballLat;
                const arcH = Math.sin(ballF * Math.PI) * 8.5 * s;
                const bx = ctx.toX(bu);
                const by = ctx.toY(bv);
                targetCtx.fillStyle = 'rgba(28, 18, 12, 0.35)';
                targetCtx.fillRect(Math.round(bx - bSz * 0.4), Math.round(by), Math.max(1.5, Math.round(bSz * 0.8)), Math.max(1, Math.round(bSz * 0.6)));
                targetCtx.fillStyle = '#d9ff3b';
                targetCtx.fillRect(Math.round(bx - bSz * 0.5), Math.round(by - arcH - bSz * 0.5), Math.max(2, Math.round(bSz)), Math.max(2, Math.round(bSz)));
              },
            });
          }
        }
      }

      // =====================================================================
      // 2. SPORTPLATZ HOCHWEID — Live FC Kilchberg Match, Sideline Fans & Night Floodlights
      // =====================================================================
      const spVig = vig.sportplatz_hochweid || {
        center: [0.31377, 0.22953],
        half_l: [0.01364, -0.00936],
        half_w: [0.00506, 0.00945],
      };
      const fCU = spVig.center[0];
      const fCV = spVig.center[1];
      if (!isNight) {
        counts.sportsPlayers += 12;
        counts.sportsSpectators += 4;
      }

      if (ctx.boxInView(fCU - 0.022, fCV - 0.022, fCU + 0.022, fCV + 0.022)) {
        const fLenU = spVig.half_l[0];
        const fLenV = spVig.half_l[1];
        const fLatU = spVig.half_w[0];
        const fLatV = spVig.half_w[1];
        const fieldUV = (lu, lv) => ({
          u: fCU + lu * fLenU + lv * fLatU,
          v: fCV + lu * fLenV + lv * fLatV,
        });

        if (isNight) {
          drawables.push({
            layer: 'landmark',
            sortY: fCV * worldH,
            draw(targetCtx) {
              const masts = [[-0.58, -1.04], [0.58, -1.04], [-0.58, 1.04], [0.58, 1.04]];
              const rad = 52 * s;
              for (let mi = 0; mi < masts.length; mi++) {
                const p = fieldUV(masts[mi][0], masts[mi][1]);
                blitGlow(targetCtx, ctx.toX(p.u), ctx.toY(p.v), rad * 1.15, '255,234,178', 0.26, rad * 0.68, -0.32);
              }
            },
          });
        } else {
          inspectables.push({
            kind: 'sport',
            id: 'sports:sportplatz_hochweid',
            wx: fCU * worldW,
            wy: fCV * worldH,
            radiusCss: 18,
            title: 'Sportplatz Hochweid · FC Kilchberg Match',
            sub: 'Live village football match with sideline spectators & linesman',
            specs: [
              ['Club', 'FC Kilchberg-Rüschlikon'],
              ['Pitch', 'Sportanlage Hochweid Main'],
              ['Players', '12 Active + Linesman'],
              ['Lighting', '4 Night Floodlight Masts'],
            ],
          });

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

          for (let idx = 0; idx < players.length; idx++) {
            const pl = players[idx];
            const p = fieldUV(Math.max(-0.94, Math.min(0.94, pl.lu)), Math.max(-0.88, Math.min(0.88, pl.lv)));
            const d16 = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(p.u * worldW, p.v * worldH, 488.0, worldW, worldH, false) : 0;
            pushPerson(p.u, p.v, d16, 0.88, pl.kit, pl.shorts, HAIRS[pl.hi % HAIRS.length], tSec * 9.0 + idx * 1.3);
          }

          // Sideline linesman + 3 spectators
          if (s >= 0.42) {
            const lmPos = fieldUV(Math.max(-0.75, Math.min(0.75, ballLU * 0.72)), -1.08);
            const d16Lm = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(lmPos.u * worldW, lmPos.v * worldH, 488.0, worldW, worldH, false) : 0;
            pushPerson(lmPos.u, lmPos.v, d16Lm, 0.84, '#111827', '#0f172a', HAIRS[0], tSec * 6.5, { isWaving: Math.abs(ballLU) > 0.55 });

            const fanLUs = [-0.36, -0.08, 0.28];
            for (let fi = 0; fi < fanLUs.length; fi++) {
              const fp = fieldUV(fanLUs[fi], 1.12);
              const d16F = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(fp.u * worldW, fp.v * worldH, 488.0, worldW, worldH, false) : 0;
              pushPerson(fp.u, fp.v, d16F, 0.84, shadeHex(SPEC_COATS[(fi + 2) % SPEC_COATS.length], 1.0, mode), '#243040', HAIRS[(fi + 2) % HAIRS.length], tSec * 1.1 + fi, { isChatting: true });
            }
          }

          // Football + crisp motion trail
          drawables.push({
            layer: 'landmark',
            sortY: fCV * worldH,
            draw(targetCtx) {
              const fbSz = Math.max(1.8, 2.0 * s);
              for (let tr = 2; tr >= 1; tr--) {
                const pAng = (tSec - tr * 0.14) * 0.42;
                const pLU = Math.sin(pAng) * 0.64 + Math.sin(pAng * 2.3) * 0.16;
                const pLV = Math.cos(pAng * 1.35) * 0.56;
                const tp = fieldUV(pLU, pLV);
                const tBounce = Math.abs(Math.sin((tSec - tr * 0.14) * 3.4)) * 5.2 * s;
                const trSz = Math.max(1, Math.round(fbSz * (0.75 - tr * 0.18)));
                targetCtx.fillStyle = `rgba(248, 250, 252, ${(0.36 - tr * 0.10).toFixed(2)})`;
                targetCtx.fillRect(Math.round(ctx.toX(tp.u) - trSz * 0.5), Math.round(ctx.toY(tp.v) - tBounce - trSz * 0.5), trSz, trSz);
              }
              const bp = fieldUV(ballLU, ballLV);
              const fbx = ctx.toX(bp.u);
              const fby = ctx.toY(bp.v);
              const bounceH = Math.abs(Math.sin(tSec * 3.4)) * 5.2 * s;
              targetCtx.fillStyle = 'rgba(20, 32, 18, 0.36)';
              targetCtx.fillRect(Math.round(fbx - fbSz * 0.4), Math.round(fby), Math.max(1.5, Math.round(fbSz * 0.9)), Math.max(1, Math.round(fbSz * 0.55)));
              targetCtx.fillStyle = '#f8fafc';
              targetCtx.fillRect(Math.round(fbx - fbSz * 0.5), Math.round(fby - bounceH - fbSz * 0.5), Math.max(2, Math.round(fbSz)), Math.max(2, Math.round(fbSz)));
            },
          });
        }
      }

      // =====================================================================
      // 3. ALL 5 EXTRA SPORTS FIELDS (animData.network.extra_sports, Day & Sunset)
      // =====================================================================
      const extraSports = (animData && animData.network && Array.isArray(animData.network.extra_sports))
        ? animData.network.extra_sports
        : [];
      if (!isNight && extraSports.length > 0) {
        for (let fi = 0; fi < extraSports.length; fi++) {
          const fld = extraSports[fi];
          counts.sportsPlayers += fld.kind === 'tennis' ? 2 : (fld.kind === 'football' ? 10 : 4);
          if (s < 0.25) continue;
          if (!ctx.boxInView(fld.u - 0.018, fld.v - 0.018, fld.u + 0.018, fld.v + 0.018)) continue;

          const { halfL, halfW } = fieldAxesUV(fld);
          const toFieldUV = (lu, lv) => ({
            u: fld.u + lu * halfL[0] + lv * halfW[0],
            v: fld.v + lu * halfL[1] + lv * halfW[1],
          });

          inspectables.push({
            kind: 'sport',
            id: `sports:extra_${fi}`,
            wx: fld.u * worldW,
            wy: fld.v * worldH,
            radiusCss: 14,
            title: humanizeSportsFieldName(fld, fi),
            sub: fld.kind === 'tennis' ? 'Live village tennis rally' : (fld.kind === 'football' ? 'Local training scrimmage' : 'Schoolyard multisport game'),
            specs: [
              ['Sport', fld.kind === 'tennis' ? 'Tennis' : (fld.kind === 'football' ? 'Football' : 'Multisport')],
              ['Activity', 'Live Match'],
              ['Location', 'Kilchberg ZH'],
            ],
          });

          if (fld.kind === 'tennis') {
            const cyc = (((tSec * 1.48 + fi * 0.7) % 2.0) + 2.0) % 2.0;
            const ballF = cyc < 1.0 ? cyc : (2.0 - cyc);
            const latA = Math.sin(tSec * 0.82 + fi * 1.9) * 0.62;
            const latB = Math.cos(tSec * 0.88 + fi * 2.3) * 0.62;
            const pA = toFieldUV(-0.82, latA);
            const pB = toFieldUV(0.82, latB);
            const whiteKit = isSunset ? '#ffe8d4' : '#f4f7fa';
            pushPerson(pA.u, pA.v, fld.d16, 0.86, whiteKit, '#1e3a5f', HAIRS[0], tSec * 9.6);
            pushPerson(pB.u, pB.v, fld.d16, 0.86, whiteKit, '#991b1b', HAIRS[2], tSec * 9.6 + 1.2);

            drawables.push({
              layer: 'landmark',
              sortY: fld.v * worldH,
              draw(targetCtx) {
                const dirSign = cyc < 1.0 ? -1 : 1;
                const bSz = Math.max(1.5, 1.7 * s);
                for (let tr = 2; tr >= 1; tr--) {
                  const tf = Math.max(0, Math.min(1, ballF + dirSign * tr * 0.07));
                  const tp = toFieldUV(-0.82 + 1.64 * tf, latA * (1 - tf) + latB * tf);
                  const tArc = Math.sin(tf * Math.PI) * 7.8 * s;
                  const trSz = Math.max(1, Math.round(bSz * (0.76 - tr * 0.16)));
                  targetCtx.fillStyle = `rgba(217, 255, 59, ${(0.38 - tr * 0.11).toFixed(2)})`;
                  targetCtx.fillRect(Math.round(ctx.toX(tp.u) - trSz * 0.5), Math.round(ctx.toY(tp.v) - tArc - trSz * 0.5), trSz, trSz);
                }
                const bPos = toFieldUV(-0.82 + 1.64 * ballF, latA * (1 - ballF) + latB * ballF);
                const bx = ctx.toX(bPos.u);
                const by = ctx.toY(bPos.v);
                const arcH = Math.sin(ballF * Math.PI) * 7.8 * s;
                targetCtx.fillStyle = 'rgba(28, 18, 12, 0.34)';
                targetCtx.fillRect(Math.round(bx - bSz * 0.4), Math.round(by), Math.max(1.5, Math.round(bSz * 0.8)), Math.max(1, Math.round(bSz * 0.55)));
                targetCtx.fillStyle = '#d9ff3b';
                targetCtx.fillRect(Math.round(bx - bSz * 0.5), Math.round(by - arcH - bSz * 0.5), Math.max(2, Math.round(bSz)), Math.max(2, Math.round(bSz)));
              },
            });
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
            for (let idx = 0; idx < roster.length; idx++) {
              const pl = roster[idx];
              const p = toFieldUV(Math.max(-0.92, Math.min(0.92, pl.lu)), Math.max(-0.85, Math.min(0.85, pl.lv)));
              pushPerson(p.u, p.v, fld.d16, 0.86, pl.kit, pl.shorts, HAIRS[pl.hi % HAIRS.length], tSec * 8.8 + idx * 1.3 + fi);
            }
            drawables.push({
              layer: 'landmark',
              sortY: fld.v * worldH,
              draw(targetCtx) {
                const bp = toFieldUV(bLU, bLV);
                const fbx = ctx.toX(bp.u);
                const fby = ctx.toY(bp.v);
                const bounceH = Math.abs(Math.sin(tSec * 3.2 + fi)) * 4.6 * s;
                const fbSz = Math.max(1.6, 1.9 * s);
                targetCtx.fillStyle = 'rgba(20, 32, 18, 0.34)';
                targetCtx.fillRect(Math.round(fbx - fbSz * 0.4), Math.round(fby), Math.max(1.5, Math.round(fbSz * 0.9)), Math.max(1, Math.round(fbSz * 0.5)));
                targetCtx.fillStyle = '#f8fafc';
                targetCtx.fillRect(Math.round(fbx - fbSz * 0.5), Math.round(fby - bounceH - fbSz * 0.5), Math.max(2, Math.round(fbSz)), Math.max(2, Math.round(fbSz)));
              },
            });
          } else {
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
            for (let idx = 0; idx < roster.length; idx++) {
              const pl = roster[idx];
              const p = toFieldUV(Math.max(-0.88, Math.min(0.88, pl.lu)), Math.max(-0.82, Math.min(0.82, pl.lv)));
              pushPerson(p.u, p.v, fld.d16, 0.86, pl.kit, '#1e293b', HAIRS[pl.hi % HAIRS.length], tSec * 9.4 + idx * 1.7 + fi);
            }
            drawables.push({
              layer: 'landmark',
              sortY: fld.v * worldH,
              draw(targetCtx) {
                const bp = toFieldUV(bLU, bLV);
                const bx = ctx.toX(bp.u);
                const by = ctx.toY(bp.v);
                const bounceH = Math.abs(Math.sin(tSec * 4.6 + fi)) * 4.8 * s;
                const bSz = Math.max(1.5, 1.8 * s);
                targetCtx.fillStyle = '#fb923c';
                targetCtx.fillRect(Math.round(bx - bSz * 0.5), Math.round(by - bounceH - bSz * 0.5), Math.max(2, Math.round(bSz)), Math.max(2, Math.round(bSz)));
              },
            });
          }
        }
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
