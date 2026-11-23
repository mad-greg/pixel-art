/**
 * Kilchberg Sports Courts & Fields Plugin (Kilchberg v14.0).
 *
 * Consumes stateful physics simulations from `docs/js/sim/sports_sim.js`:
 *   - TennisRallySim (F10): 2-segment ballistic arcs with clay ground bounce +
 *     clay dust puff, 1.25–1.75 s club shots, rally pauses & serves, 2.5–5.5 m/s
 *     footwork, displacement-driven leg stride.
 *   - SoccerMatchSim (F11): Real 3D ball kinematics (gravity, grass drag, damped
 *     bounce — zero autonomous Lissajous circling), possession/pass/shot/goal-kick
 *     state machine, <= 6.5 m/s hard player speed cap, displacement-driven stride.
 *
 * Publishes `ctx.shared.sportsSim` for telemetry & E2E verification.
 * 100% deterministic (zero Math.random()), cached glow sprites, pure vector/pixel geometry.
 * Counts reported under livingCounts (sportsPlayers, sportsSpectators), NEVER simStats.pedestrians.
 */

import { shadeHex } from '../../render/vehicles.js';
import { createSportsSim } from '../../sim/sports_sim.js';
import { blitGlow, drawMiniPersonV2 } from '../draw.js';

const HAIRS = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];
const SPEC_COATS = ['#334155', '#0d9488', '#d97706', '#64748b', '#7c3aed', '#2563eb'];

// Exact isometric ground-to-UV projection (azimuth=102 deg, pitch=30 deg)
const E_TO_U = 0.0000674436;
const N_TO_U = 0.0003172971;
const E_TO_V = 0.0003593489;
const N_TO_V = -0.0000763820;

// Isometric vertical lift per meter (cos(30 deg) / 0.25 m/px ≈ 3.46 px/m at wScale=1)
const Z_METERS_TO_PX = 3.4;

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
  if (id.includes('brunnenmoos') && fld.kind === 'football') return 'Schulhaus Brunnenmoos · Football Field';
  if (id.includes('brunnenmoos')) return 'Schulhaus Brunnenmoos · Multisport Court';
  if (fld.kind === 'tennis') return `Kilchberg Clay Tennis Court #${idx + 1}`;
  if (fld.kind === 'football') return `Kilchberg Community Football Pitch #${idx + 1}`;
  return `Kilchberg Village Sports Court #${idx + 1}`;
}

export function createSportsPlugin() {
  let counts = { sportsPlayers: 0, sportsSpectators: 0 };
  let cachedInspectables = [];
  let sportsSim = null;
  let boundAnimData = null;

  function ensureSim(ctx) {
    if (!sportsSim || boundAnimData !== ctx.animData) {
      sportsSim = createSportsSim(ctx.animData, ctx.specs);
      boundAnimData = ctx.animData;
    }
    if (ctx.shared) {
      ctx.shared.sportsSim = sportsSim;
    }
    sportsSim.updateToTime(ctx.tSec, ctx.mode, ctx.clock, ctx.specs);
    return sportsSim;
  }

  return {
    id: 'sports',
    name: 'TC Kilchberg Tennis, Sportplatz Hochweid & Village Sports',
    category: 'people',
    layers: ['ground_y', 'landmark'],
    priority: 32,
    enabledByDefault: true,

    init(ctx) {
      counts = { sportsPlayers: 0, sportsSpectators: 0 };
      cachedInspectables = [];
      if (ctx) {
        sportsSim = createSportsSim(ctx.animData, ctx.specs);
        boundAnimData = ctx.animData;
        if (ctx.shared) {
          ctx.shared.sportsSim = sportsSim;
        }
      }
    },

    update(_dt, ctx) {
      if (!ctx) return;
      ensureSim(ctx);
    },

    getDrawables(cam, ctx) {
      const sim = ensureSim(ctx);
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

      // Helper to map court-local (lu in [-1, 1], lv in [-1, 1]) on a TC court to (u, v)
      const tcCourtUV = (c, lu, lv) => {
        const f = 0.5 * (lu + 1.0);
        return {
          u: c.sw[0] + (c.ne[0] - c.sw[0]) * f + c.lat[0] * lv,
          v: c.sw[1] + (c.ne[1] - c.sw[1]) * f + c.lat[1] * lv,
        };
      };

      // =====================================================================
      // 1. TC KILCHBERG CLAY TENNIS COURTS (3 Courts + Umpire + Spectators + Night LEDs)
      // =====================================================================
      const tcSrc = Array.isArray(vig.tc_kilchberg) && vig.tc_kilchberg.length >= 3
        ? vig.tc_kilchberg
        : [
          { sw: [0.17328, 0.34316], ne: [0.17907, 0.33876], lat: [0.00074, 0.00126] },
          { sw: [0.17637, 0.34803], ne: [0.18205, 0.34351], lat: [0.00076, 0.00124] },
          { sw: [0.16329, 0.35330], ne: [0.16909, 0.34874], lat: [0.00075, 0.00124] },
        ];

      let activeTcCourts = 0;
      for (let ci = 0; ci < tcSrc.length; ci++) {
        if (!isNight && sim.isVenueActive(`tc_kilchberg_court_${ci}`)) activeTcCourts++;
      }
      if (activeTcCourts > 0) {
        counts.sportsPlayers += activeTcCourts * 2;
        if (sim.isVenueActive('tc_kilchberg_court_0')) counts.sportsSpectators += 3;
      }

      if (ctx.boxInView(0.156, 0.334, 0.188, 0.362)) {
        if (isNight) {
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
          const whiteKit = isSunset ? '#ffe8d4' : '#f4f7fa';

          if (activeTcCourts > 0) {
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
          }

          for (let ci = 0; ci < tcSrc.length; ci++) {
            const courtId = `tc_kilchberg_court_${ci}`;
            if (!sim.isVenueActive(courtId)) continue;
            const c = tcSrc[ci];
            if (!ctx.boxInView(c.sw[0] - 0.003, c.ne[1] - 0.004, c.ne[0] + 0.003, c.sw[1] + 0.004)) continue;

            const courtSim = sim.getTennisCourt(courtId);
            if (!courtSim) continue;

            const plA = courtSim.players[0];
            const plB = courtSim.players[1];
            const posA = tcCourtUV(c, plA.x / courtSim.halfLenM, plA.y / courtSim.halfWidthM);
            const posB = tcCourtUV(c, plB.x / courtSim.halfLenM, plB.y / courtSim.halfWidthM);

            const shortCol = ci === 0 ? '#1e3a5f' : (ci === 1 ? '#991b1b' : '#166534');
            const d16B = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(posB.u * worldW, posB.v * worldH, 476.0, worldW, worldH, false) : 0;
            const d16A = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(posA.u * worldW, posA.v * worldH, 476.0, worldW, worldH, false) : 0;

            pushPerson(posB.u, posB.v, d16B, 0.90, whiteKit, shortCol, HAIRS[ci % HAIRS.length], plB.stridePhase, { isWaving: plB.swingTimer > 0 });
            pushPerson(posA.u, posA.v, d16A, 0.90, whiteKit, '#1e3a5f', HAIRS[(ci + 2) % HAIRS.length], plA.stridePhase, { isWaving: plA.swingTimer > 0 });

            // Court-side umpire & spectators on Court 1
            if (ci === 0 && s >= 0.45) {
              const midU = (c.sw[0] + c.ne[0]) * 0.5 + c.lat[0] * 1.38;
              const midV = (c.sw[1] + c.ne[1]) * 0.5 + c.lat[1] * 1.38;
              const d16U = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(midU * worldW, midV * worldH, 476.5, worldW, worldH, false) : 0;
              pushPerson(midU, midV, d16U, 0.84, shadeHex('#1e293b', 1.0, mode), '#334155', HAIRS[3], 0, { hatCol: '#f8fafc' });

              for (let sp = 0; sp < 2; sp++) {
                const su = midU + (sp === 0 ? -0.0011 : 0.0011);
                const sv = midV + (sp === 0 ? 0.0008 : -0.0008);
                const d16S = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(su * worldW, sv * worldH, 476.0, worldW, worldH, false) : 0;
                pushPerson(su, sv, d16S, 0.82, shadeHex(SPEC_COATS[sp], 1.0, mode), '#243040', HAIRS[(sp + 1) % HAIRS.length], 0, { isChatting: true });
              }
            }

            // Tennis ball + 2-segment arc + clay dust puff + rally trail on landmark layer
            const ballSnap = {
              lu: courtSim.ball.lu,
              lv: courtSim.ball.lv,
              z: courtSim.ball.z,
              visible: courtSim.ball.visible,
            };
            const trailSnap = [
              { lu: courtSim.trail[0].lu, lv: courtSim.trail[0].lv, z: courtSim.trail[0].z, active: courtSim.trail[0].active },
              { lu: courtSim.trail[1].lu, lv: courtSim.trail[1].lv, z: courtSim.trail[1].z, active: courtSim.trail[1].active },
              { lu: courtSim.trail[2].lu, lv: courtSim.trail[2].lv, z: courtSim.trail[2].z, active: courtSim.trail[2].active },
            ];
            const dustSnap = courtSim.dust.active
              ? { lu: courtSim.dust.lu, lv: courtSim.dust.lv, prog: courtSim.dust.age / courtSim.dust.maxAge }
              : null;

            drawables.push({
              layer: 'landmark',
              sortY: Math.max(posA.v, posB.v) * worldH,
              draw(targetCtx) {
                const bSz = Math.max(1.6, 1.8 * s);

                // Clay dust puff at bounce point
                if (dustSnap) {
                  const dp = tcCourtUV(c, dustSnap.lu, dustSnap.lv);
                  const dx = ctx.toX(dp.u);
                  const dy = ctx.toY(dp.v);
                  const fade = Math.max(0, 1 - dustSnap.prog);
                  const rad = (1.2 + dustSnap.prog * 2.8) * s;
                  targetCtx.fillStyle = `rgba(218, 134, 88, ${(0.52 * fade).toFixed(2)})`;
                  targetCtx.fillRect(Math.round(dx - rad), Math.round(dy - rad * 0.45), Math.max(2, Math.round(rad * 2)), Math.max(1, Math.round(rad * 0.9)));
                }

                if (!ballSnap.visible) return;

                // Rally trail dots
                for (let tr = 2; tr >= 0; tr--) {
                  const pt = trailSnap[tr];
                  if (!pt.active) continue;
                  const tp = tcCourtUV(c, pt.lu, pt.lv);
                  const tArc = pt.z * Z_METERS_TO_PX * s;
                  const trSz = Math.max(1, Math.round(bSz * (0.72 - tr * 0.14)));
                  targetCtx.fillStyle = `rgba(217, 255, 59, ${(0.38 - tr * 0.10).toFixed(2)})`;
                  targetCtx.fillRect(Math.round(ctx.toX(tp.u) - trSz * 0.5), Math.round(ctx.toY(tp.v) - tArc - trSz * 0.5), trSz, trSz);
                }

                const bp = tcCourtUV(c, ballSnap.lu, ballSnap.lv);
                const arcH = ballSnap.z * Z_METERS_TO_PX * s;
                const bx = ctx.toX(bp.u);
                const by = ctx.toY(bp.v);
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
        center: [0.31344, 0.22808],
        half_l: [0.01366, -0.00941],
        half_w: [0.00507, 0.00951],
      };
      const fCU = spVig.center[0];
      const fCV = spVig.center[1];
      const hochweidActive = !isNight && sim.isVenueActive('sportplatz_hochweid');
      if (hochweidActive) {
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
        } else if (hochweidActive) {
          const pitchSim = sim.getSoccerPitch('sportplatz_hochweid');
          if (pitchSim) {
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

            const blueKit = isSunset ? '#2e64b8' : '#2563eb';
            const redKit = isSunset ? '#c83434' : '#dc2626';
            const gkA = isSunset ? '#e6c238' : '#facc15';
            const gkB = isSunset ? '#58c448' : '#4ade80';

            for (let idx = 0; idx < pitchSim.players.length; idx++) {
              const pl = pitchSim.players[idx];
              const p = fieldUV(pl.lu, pl.lv);
              const d16 = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(p.u * worldW, p.v * worldH, 488.0, worldW, worldH, false) : 0;
              const kit = pl.role === 'gk' ? (pl.team === 0 ? gkA : gkB) : (pl.team === 0 ? blueKit : redKit);
              const shorts = pl.role === 'gk' ? '#1e293b' : '#f8fafc';
              pushPerson(p.u, p.v, d16, 0.88, kit, shorts, HAIRS[idx % HAIRS.length], pl.stridePhase);
            }

            // Sideline linesman + 3 spectators
            if (s >= 0.42) {
              const lmLU = Math.max(-0.75, Math.min(0.75, pitchSim.ball.lu * 0.72));
              const lmPos = fieldUV(lmLU, -1.08);
              const d16Lm = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(lmPos.u * worldW, lmPos.v * worldH, 488.0, worldW, worldH, false) : 0;
              pushPerson(lmPos.u, lmPos.v, d16Lm, 0.84, '#111827', '#0f172a', HAIRS[0], Math.abs(pitchSim.ball.x) * 0.5, { isWaving: pitchSim.mode === 'GOAL_CELEBRATION' });

              const fanLUs = [-0.36, -0.08, 0.28];
              for (let fi = 0; fi < fanLUs.length; fi++) {
                const fp = fieldUV(fanLUs[fi], 1.12);
                const d16F = depthMgr && depthMgr.evalWalkerD16 ? depthMgr.evalWalkerD16(fp.u * worldW, fp.v * worldH, 488.0, worldW, worldH, false) : 0;
                pushPerson(fp.u, fp.v, d16F, 0.84, shadeHex(SPEC_COATS[(fi + 2) % SPEC_COATS.length], 1.0, mode), '#243040', HAIRS[(fi + 2) % HAIRS.length], 0, { isChatting: true });
              }
            }

            // Football + crisp motion trail (real 3D height z)
            const fbSnap = { lu: pitchSim.ball.lu, lv: pitchSim.ball.lv, z: pitchSim.ball.z };
            const fbTrail = [
              { lu: pitchSim.trail[0].lu, lv: pitchSim.trail[0].lv, z: pitchSim.trail[0].z, active: pitchSim.trail[0].active },
              { lu: pitchSim.trail[1].lu, lv: pitchSim.trail[1].lv, z: pitchSim.trail[1].z, active: pitchSim.trail[1].active },
            ];
            drawables.push({
              layer: 'landmark',
              sortY: fCV * worldH,
              draw(targetCtx) {
                const fbSz = Math.max(1.8, 2.0 * s);
                for (let tr = 1; tr >= 0; tr--) {
                  const pt = fbTrail[tr];
                  if (!pt.active) continue;
                  const tp = fieldUV(pt.lu, pt.lv);
                  const tBounce = pt.z * Z_METERS_TO_PX * s;
                  const trSz = Math.max(1, Math.round(fbSz * (0.72 - tr * 0.18)));
                  targetCtx.fillStyle = `rgba(248, 250, 252, ${(0.34 - tr * 0.12).toFixed(2)})`;
                  targetCtx.fillRect(Math.round(ctx.toX(tp.u) - trSz * 0.5), Math.round(ctx.toY(tp.v) - tBounce - trSz * 0.5), trSz, trSz);
                }
                const bp = fieldUV(fbSnap.lu, fbSnap.lv);
                const fbx = ctx.toX(bp.u);
                const fby = ctx.toY(bp.v);
                const bounceH = fbSnap.z * Z_METERS_TO_PX * s;
                targetCtx.fillStyle = 'rgba(20, 32, 18, 0.36)';
                targetCtx.fillRect(Math.round(fbx - fbSz * 0.4), Math.round(fby), Math.max(1.5, Math.round(fbSz * 0.9)), Math.max(1, Math.round(fbSz * 0.55)));
                targetCtx.fillStyle = '#f8fafc';
                targetCtx.fillRect(Math.round(fbx - fbSz * 0.5), Math.round(fby - bounceH - fbSz * 0.5), Math.max(2, Math.round(fbSz)), Math.max(2, Math.round(fbSz)));
              },
            });
          }
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
          const fid = fld.id || `extra_sport_${fi}`;
          if (!sim.isVenueActive(fid)) continue;
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
            const courtSim = sim.getTennisCourt(fid);
            if (!courtSim) continue;
            const plA = courtSim.players[0];
            const plB = courtSim.players[1];
            const pA = toFieldUV(plA.x / courtSim.halfLenM, plA.y / courtSim.halfWidthM);
            const pB = toFieldUV(plB.x / courtSim.halfLenM, plB.y / courtSim.halfWidthM);
            const whiteKit = isSunset ? '#ffe8d4' : '#f4f7fa';
            pushPerson(pA.u, pA.v, fld.d16, 0.86, whiteKit, '#1e3a5f', HAIRS[0], plA.stridePhase, { isWaving: plA.swingTimer > 0 });
            pushPerson(pB.u, pB.v, fld.d16, 0.86, whiteKit, '#991b1b', HAIRS[2], plB.stridePhase, { isWaving: plB.swingTimer > 0 });

            const ballSnap = { lu: courtSim.ball.lu, lv: courtSim.ball.lv, z: courtSim.ball.z, visible: courtSim.ball.visible };
            const trailSnap = [
              { lu: courtSim.trail[0].lu, lv: courtSim.trail[0].lv, z: courtSim.trail[0].z, active: courtSim.trail[0].active },
              { lu: courtSim.trail[1].lu, lv: courtSim.trail[1].lv, z: courtSim.trail[1].z, active: courtSim.trail[1].active },
            ];
            const dustSnap = courtSim.dust.active
              ? { lu: courtSim.dust.lu, lv: courtSim.dust.lv, prog: courtSim.dust.age / courtSim.dust.maxAge }
              : null;

            drawables.push({
              layer: 'landmark',
              sortY: fld.v * worldH,
              draw(targetCtx) {
                const bSz = Math.max(1.5, 1.7 * s);
                if (dustSnap) {
                  const dp = toFieldUV(dustSnap.lu, dustSnap.lv);
                  const dx = ctx.toX(dp.u);
                  const dy = ctx.toY(dp.v);
                  const fade = Math.max(0, 1 - dustSnap.prog);
                  const rad = (1.1 + dustSnap.prog * 2.5) * s;
                  targetCtx.fillStyle = `rgba(218, 134, 88, ${(0.50 * fade).toFixed(2)})`;
                  targetCtx.fillRect(Math.round(dx - rad), Math.round(dy - rad * 0.45), Math.max(2, Math.round(rad * 2)), Math.max(1, Math.round(rad * 0.9)));
                }
                if (!ballSnap.visible) return;
                for (let tr = 1; tr >= 0; tr--) {
                  const pt = trailSnap[tr];
                  if (!pt.active) continue;
                  const tp = toFieldUV(pt.lu, pt.lv);
                  const tArc = pt.z * Z_METERS_TO_PX * s;
                  const trSz = Math.max(1, Math.round(bSz * (0.74 - tr * 0.16)));
                  targetCtx.fillStyle = `rgba(217, 255, 59, ${(0.36 - tr * 0.11).toFixed(2)})`;
                  targetCtx.fillRect(Math.round(ctx.toX(tp.u) - trSz * 0.5), Math.round(ctx.toY(tp.v) - tArc - trSz * 0.5), trSz, trSz);
                }
                const bPos = toFieldUV(ballSnap.lu, ballSnap.lv);
                const bx = ctx.toX(bPos.u);
                const by = ctx.toY(bPos.v);
                const arcH = ballSnap.z * Z_METERS_TO_PX * s;
                targetCtx.fillStyle = 'rgba(28, 18, 12, 0.34)';
                targetCtx.fillRect(Math.round(bx - bSz * 0.4), Math.round(by), Math.max(1.5, Math.round(bSz * 0.8)), Math.max(1, Math.round(bSz * 0.55)));
                targetCtx.fillStyle = '#d9ff3b';
                targetCtx.fillRect(Math.round(bx - bSz * 0.5), Math.round(by - arcH - bSz * 0.5), Math.max(2, Math.round(bSz)), Math.max(2, Math.round(bSz)));
              },
            });
          } else if (fld.kind === 'football') {
            const pitchSim = sim.getSoccerPitch(fid);
            if (!pitchSim) continue;
            const isUpper = fld.id && fld.id.includes('upper');
            const kitA = shadeHex(isUpper ? '#1e3a8a' : '#0d9488', 1.0, mode);
            const kitB = shadeHex(isUpper ? '#f1f5f9' : '#d97706', 1.0, mode);
            const gkCol = shadeHex('#facc15', 1.0, mode);

            for (let idx = 0; idx < pitchSim.players.length; idx++) {
              const pl = pitchSim.players[idx];
              const p = toFieldUV(pl.lu, pl.lv);
              const kit = pl.role === 'gk' ? gkCol : (pl.team === 0 ? kitA : kitB);
              const shorts = pl.team === 0 ? '#1e293b' : '#334155';
              pushPerson(p.u, p.v, fld.d16, 0.86, kit, shorts, HAIRS[idx % HAIRS.length], pl.stridePhase);
            }
            const fbSnap = { lu: pitchSim.ball.lu, lv: pitchSim.ball.lv, z: pitchSim.ball.z };
            drawables.push({
              layer: 'landmark',
              sortY: fld.v * worldH,
              draw(targetCtx) {
                const bp = toFieldUV(fbSnap.lu, fbSnap.lv);
                const fbx = ctx.toX(bp.u);
                const fby = ctx.toY(bp.v);
                const bounceH = fbSnap.z * Z_METERS_TO_PX * s;
                const fbSz = Math.max(1.6, 1.9 * s);
                targetCtx.fillStyle = 'rgba(20, 32, 18, 0.34)';
                targetCtx.fillRect(Math.round(fbx - fbSz * 0.4), Math.round(fby), Math.max(1.5, Math.round(fbSz * 0.9)), Math.max(1, Math.round(fbSz * 0.5)));
                targetCtx.fillStyle = '#f8fafc';
                targetCtx.fillRect(Math.round(fbx - fbSz * 0.5), Math.round(fby - bounceH - fbSz * 0.5), Math.max(2, Math.round(fbSz)), Math.max(2, Math.round(fbSz)));
              },
            });
          } else {
            const pitchSim = sim.getSoccerPitch(fid);
            if (!pitchSim) continue;
            const isGem = fld.id && fld.id.includes('gemeindehaus');
            const kitA = shadeHex(isGem ? '#059669' : '#2563eb', 1.0, mode);
            const kitB = shadeHex(isGem ? '#eab308' : '#e11d48', 1.0, mode);

            for (let idx = 0; idx < pitchSim.players.length; idx++) {
              const pl = pitchSim.players[idx];
              const p = toFieldUV(pl.lu, pl.lv);
              const kit = pl.team === 0 ? kitA : kitB;
              pushPerson(p.u, p.v, fld.d16, 0.86, kit, '#1e293b', HAIRS[idx % HAIRS.length], pl.stridePhase);
            }
            const bSnap = { lu: pitchSim.ball.lu, lv: pitchSim.ball.lv, z: pitchSim.ball.z };
            drawables.push({
              layer: 'landmark',
              sortY: fld.v * worldH,
              draw(targetCtx) {
                const bp = toFieldUV(bSnap.lu, bSnap.lv);
                const bx = ctx.toX(bp.u);
                const by = ctx.toY(bp.v);
                const bounceH = bSnap.z * Z_METERS_TO_PX * s;
                const bSz = Math.max(1.5, 1.8 * s);
                targetCtx.fillStyle = 'rgba(20, 32, 18, 0.32)';
                targetCtx.fillRect(Math.round(bx - bSz * 0.4), Math.round(by), Math.max(1.5, Math.round(bSz * 0.8)), Math.max(1, Math.round(bSz * 0.5)));
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

    getCounts() {
      return { ...counts };
    },
  };
}
