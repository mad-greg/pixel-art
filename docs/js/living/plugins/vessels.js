/**
 * Lake Zurich Vessels & Watercraft Plugin (Kilchberg v14.0).
 *
 * Layer: 'water' (Y-sorted, 100% isWaterUV-strict for micro-craft):
 *   - Consumes unified stateful `VesselSim` (`docs/js/sim/vessel_sim.js`) with
 *     COLREGs priority, 15 s CPA speed yielding, water-masked lateral avoidance,
 *     and static/swimmer exclusion zones.
 *   - Publishes `ctx.shared.vesselSim` for `landmarks.js` (Bendlikon Pier gangplank),
 *     `wildlife.js` (swan/duck vessel avoidance), and `audio.js` (single-source boat audio).
 *   - Preserves opaque ship depth masking (`extraVertPx = 6.0` in `drawShipEntity`),
 *     5 moored sailboats, 2 slow SUPs (~1.6 m/s, >= 2 in day, 0 at night), and rowing skiff.
 *
 * ALL vessels are inspectable via getInspectables().
 */

import { drawShipEntity, shadeHex } from '../../render/vehicles.js';
import { createVesselSim, MOORED_BOATS } from '../../sim/vessel_sim.js';
import { blitGlow, drawMiniPersonV2, drawWaterRipples } from '../draw.js';

export function createVesselsPlugin() {
  let counts = { ships: 0, sups: 0 };
  let cachedInspectables = [];
  let vesselSim = null;
  let boundAnimData = null;

  function ensureSim(ctx) {
    if (!vesselSim || boundAnimData !== ctx.animData) {
      vesselSim = createVesselSim(ctx.animData, ctx.specs);
      boundAnimData = ctx.animData;
    }
    if (ctx.shared) {
      ctx.shared.vesselSim = vesselSim;
    }
    vesselSim.updateToTime(ctx.tSec, ctx.mode, ctx.depthMgr, ctx.clock, ctx.specs);
    return vesselSim;
  }

  return {
    id: 'vessels',
    name: 'Lake Zurich Fleet, Moored Boats, SUPs & Skiff',
    category: 'water',
    layers: ['water'],
    priority: 20,
    enabledByDefault: true,

    init(ctx) {
      counts = { ships: 0, sups: 0 };
      cachedInspectables = [];
      if (ctx) {
        vesselSim = createVesselSim(ctx.animData, ctx.specs);
        boundAnimData = ctx.animData;
        if (ctx.shared) {
          ctx.shared.vesselSim = vesselSim;
        }
      }
    },

    update(_dt, ctx) {
      if (!ctx) return;
      ensureSim(ctx);
    },

    getDrawables(cam, ctx) {
      const sim = ensureSim(ctx);
      const { worldW, worldH, wScale, tSec, mode, isNight, isSunset, s, wind, depthMgr } = ctx;
      const isWater = (u, v) => (!depthMgr || !depthMgr.isWaterUV || depthMgr.isWaterUV(u, v));

      const drawables = [];
      const inspectables = [];
      counts = { ships: 0, sups: 0 };

      const activeVessels = sim.getVessels();
      let supIndex = 0;

      // 1. Active Lake Zurich Fleet + SUPs + Skiff from stateful VesselSim
      for (let vi = 0; vi < activeVessels.length; vi++) {
        const v = activeVessels[vi];
        if (!v.visible) continue;

        if (v.animShip) {
          counts.ships++;
          const wx = v.u * worldW;
          const wy = v.v * worldH;
          const isSteamer = v.kind === 'zsg_steamer';
          const isMotor = v.kind === 'motorboat';

          inspectables.push({
            kind: 'boat',
            id: v.id,
            wx,
            wy,
            radiusCss: isSteamer ? 18 : 13,
            title: isSteamer ? 'ZSG MS Helvetia → Bendlikon Pier' : (v.name || 'Lake Zurich Vessel'),
            sub: isSteamer
              ? (v.isDocked ? 'Docked at Bendlikon Pier (gangplank deployed)' : 'Cruising Lake Zurich shoreline')
              : (isMotor ? 'Boesch mahogany runabout on Lake Zurich' : 'Tacking sailboat on Lake Zurich'),
            specs: [
              ['Service', isSteamer ? 'ZSG Zürichsee' : (isMotor ? 'Boesch Runabout' : 'Private Sailboat')],
              ['Status', v.isDocked ? 'Docked · Boarding' : 'Underway'],
              ['Route', isSteamer ? 'Zürich Bürkliplatz – Bendlikon – Thalwil' : 'Lake Zurich'],
              ['Speed', `${Math.round(v.speedMps * 3.6)} km/h`],
            ],
          });

          const shipForDraw = (Math.abs(v.latOffsetM) >= 0.05 && v.renderShip) ? v.renderShip : v.animShip;
          const stSnap = {
            visible: true,
            frac: v.frac,
            speedRatio: v.speedRatio,
            isDocked: v.isDocked,
            dwellProgress: v.dwellProg,
          };
          const sIdx = v.sIdx;

          drawables.push({
            layer: 'water',
            sortY: wy,
            depthMasked: false, // drawShipEntity invokes depthMgr.drawDepthMasked(..., 6.0) internally
            draw(targetCtx, drawCam) {
              drawShipEntity(targetCtx, depthMgr, drawCam, shipForDraw, stSnap, sIdx, worldW, worldH, wScale, mode, tSec);
            },
          });
        } else if (v.kind === 'sup') {
          if (isNight || !isWater(v.u, v.v)) continue;
          counts.sups++;
          const mySupIdx = supIndex++;
          const su = v.u;
          const sv = v.v;
          const wx = su * worldW;
          const wy = sv * worldH;
          const speedMag = Math.min(1, v.speedRatio);
          const boardCol = (v.appearance && v.appearance.board) || (mySupIdx === 0 ? '#38bdf8' : '#fbbf24');
          const shirtCol = (v.appearance && v.appearance.shirt) || (mySupIdx === 0 ? '#f43f5e' : '#0d9488');
          const hairCol = (v.appearance && v.appearance.hair) || '#2d241c';
          const dirX = v.dirX;
          const dirY = v.dirY;

          inspectables.push({
            kind: 'boat',
            id: v.id,
            wx,
            wy,
            radiusCss: 10,
            title: v.name,
            sub: 'Gliding at a relaxed paddle pace across Lake Zurich',
            specs: [
              ['Craft', 'Stand-Up Paddleboard'],
              ['Pace', `${Math.max(0.4, v.speedMps).toFixed(1)} m/s`],
              ['Waters', 'Kilchberg Shoreline'],
              ['Time', isSunset ? 'Alpenglow Paddle' : 'Daytime Session'],
            ],
          });

          drawables.push({
            layer: 'water',
            sortY: wy,
            draw(targetCtx, drawCam) {
              const sx = ctx.toX(su);
              const sy = ctx.toY(sv);
              if (!ctx.inView(sx, sy, 30)) return;

              // Project ground-meter heading into screen tangent
              const du = 0.0000674436 * dirX + 0.0003172971 * dirY;
              const dv = 0.0003593489 * dirX - 0.0000763820 * dirY;
              const rawDx = du * worldW * drawCam.scale;
              const rawDy = dv * worldH * drawCam.scale;
              const len = Math.hypot(rawDx, rawDy) || 1;
              const tx = rawDx / len;
              const ty = rawDy / len;
              const ang = Math.atan2(ty, tx);
              const px = Math.max(1.0, 1.15 * s);

              if (speedMag > 0.08) {
                targetCtx.fillStyle = `rgba(232,248,255,${(0.44 * speedMag).toFixed(2)})`;
                for (let k = 0; k < 2; k++) {
                  const dist = (5.2 + k * 2.4) * px;
                  const wxP = sx - tx * dist;
                  const wyP = sy - ty * dist;
                  const wLen = (2.8 - k * 0.7) * px;
                  targetCtx.fillRect(Math.round(wxP - wLen * 0.5), Math.round(wyP - 0.5 * px), Math.max(2, Math.round(wLen)), Math.max(1, Math.round(1.0 * px)));
                }
              }

              targetCtx.save();
              targetCtx.translate(sx, sy);
              targetCtx.rotate(ang);
              targetCtx.fillStyle = shadeHex(boardCol, 1.0, mode);
              targetCtx.beginPath();
              targetCtx.moveTo(-3.8 * px, -0.95 * px);
              targetCtx.lineTo(2.4 * px, -0.95 * px);
              targetCtx.lineTo(4.2 * px, 0);
              targetCtx.lineTo(2.4 * px, 0.95 * px);
              targetCtx.lineTo(-3.8 * px, 0.95 * px);
              targetCtx.closePath();
              targetCtx.fill();
              targetCtx.restore();

              drawMiniPersonV2(targetCtx, sx, sy - 0.5 * px, s * 0.88, {
                coatCol: shadeHex(shirtCol, 1.0, mode),
                pantsCol: '#1e293b',
                hairCol,
                isNight: false,
                phase: 0,
                canvasW: drawCam.width,
                canvasH: drawCam.height,
              });

              const strokePhase = tSec * 1.35 + mySupIdx * 2.1;
              const stroke = Math.sin(strokePhase);
              const bladeX = sx + tx * (0.9 + stroke * 1.6) * px;
              const bladeY = sy + ty * (0.9 + stroke * 1.6) * px + 1.0 * px;
              targetCtx.strokeStyle = '#334155';
              targetCtx.lineWidth = Math.max(1.0, 0.9 * s);
              targetCtx.beginPath();
              targetCtx.moveTo(sx + tx * 0.5 * px, sy - 4.0 * px);
              targetCtx.lineTo(bladeX, bladeY);
              targetCtx.stroke();

              const dipProg = (((strokePhase / (Math.PI * 2)) % 1) + 1) % 1;
              if (dipProg < 0.60) {
                drawWaterRipples(targetCtx, bladeX, bladeY, px * 0.55, dipProg, {
                  count: 2,
                  speed: 1.0,
                  minR: 1.2,
                  maxR: 4.5,
                  isNight: false,
                  isSunset,
                  alpha: 0.54,
                });
              }
            },
          });
        } else if (v.kind === 'skiff') {
          if (isNight || !isWater(v.u, v.v)) continue;
          const ru = v.u;
          const rv = v.v;
          const wx = ru * worldW;
          const wy = rv * worldH;
          const rSpeed = Math.min(1, v.speedRatio);
          const dirX = v.dirX;
          const dirY = v.dirY;

          inspectables.push({
            kind: 'boat',
            id: v.id,
            wx,
            wy,
            radiusCss: 11,
            title: v.name,
            sub: 'Cedar-wood rowing skiff sweeping past Sulzergut',
            specs: [
              ['Craft', 'Wooden Rowing Skiff'],
              ['Pace', `${Math.max(0.4, v.speedMps).toFixed(1)} m/s`],
              ['Propulsion', 'Twin Sculling Oars'],
              ['Waters', 'Bendlikon – Sulzergut'],
            ],
          });

          drawables.push({
            layer: 'water',
            sortY: wy,
            draw(targetCtx, drawCam) {
              const rx = ctx.toX(ru);
              const ry = ctx.toY(rv);
              if (!ctx.inView(rx, ry, 36)) return;

              const du = 0.0000674436 * dirX + 0.0003172971 * dirY;
              const dv = 0.0003593489 * dirX - 0.0000763820 * dirY;
              const rawDx = du * worldW * drawCam.scale;
              const rawDy = dv * worldH * drawCam.scale;
              const len = Math.hypot(rawDx, rawDy) || 1;
              const tx = rawDx / len;
              const ty = rawDy / len;
              const nx = -ty;
              const ny = tx;
              const ang = Math.atan2(ty, tx);
              const px = Math.max(1.0, 1.15 * s);

              if (rSpeed > 0.08) {
                targetCtx.fillStyle = `rgba(232, 248, 255, ${(0.44 * rSpeed).toFixed(2)})`;
                for (let k = 1; k <= 3; k++) {
                  const dist = (4.8 + k * 2.5) * px;
                  const spr = (0.8 + k * 1.1) * px;
                  const sz = Math.max(1.2, Math.round((2.2 - k * 0.4) * px));
                  targetCtx.fillRect(Math.round(rx - tx * dist + nx * spr), Math.round(ry - ty * dist + ny * spr), sz, Math.max(1, Math.round(0.9 * px)));
                  targetCtx.fillRect(Math.round(rx - tx * dist - nx * spr), Math.round(ry - ty * dist - ny * spr), sz, Math.max(1, Math.round(0.9 * px)));
                }
              }

              const oarCycle = tSec * 1.9;
              const oarAng = Math.sin(oarCycle) * 0.55;
              targetCtx.save();
              targetCtx.translate(rx, ry);
              targetCtx.rotate(ang);

              targetCtx.fillStyle = shadeHex('#5c3318', 1.0, mode);
              targetCtx.beginPath();
              targetCtx.moveTo(6.0 * px, 0);
              targetCtx.lineTo(2.4 * px, -1.9 * px);
              targetCtx.lineTo(-4.6 * px, -1.6 * px);
              targetCtx.lineTo(-5.8 * px, 0);
              targetCtx.lineTo(-4.6 * px, 1.6 * px);
              targetCtx.lineTo(2.4 * px, 1.9 * px);
              targetCtx.closePath();
              targetCtx.fill();

              targetCtx.fillStyle = shadeHex('#a3683b', 1.02, mode);
              targetCtx.beginPath();
              targetCtx.moveTo(5.0 * px, 0);
              targetCtx.lineTo(2.0 * px, -1.3 * px);
              targetCtx.lineTo(-4.0 * px, -1.1 * px);
              targetCtx.lineTo(-4.8 * px, 0);
              targetCtx.lineTo(-4.0 * px, 1.1 * px);
              targetCtx.lineTo(2.0 * px, 1.3 * px);
              targetCtx.closePath();
              targetCtx.fill();

              targetCtx.strokeStyle = shadeHex('#d4a373', 1.0, mode);
              targetCtx.lineWidth = Math.max(0.9, 0.85 * px);
              const oarTipX = (-1.6 + oarAng * 3.8) * px;
              const oarTipY = 5.4 * px;
              targetCtx.beginPath();
              targetCtx.moveTo(0, -1.4 * px);
              targetCtx.lineTo(oarTipX, -oarTipY);
              targetCtx.moveTo(0, 1.4 * px);
              targetCtx.lineTo(oarTipX, oarTipY);
              targetCtx.stroke();
              targetCtx.restore();

              drawMiniPersonV2(targetCtx, rx, ry - 0.6 * px, s * 0.72, {
                coatCol: shadeHex('#f8fafc', 1.0, mode),
                pantsCol: '#1e3a5f',
                hairCol: '#3a3430',
                isNight: false,
                phase: 0,
                canvasW: drawCam.width,
                canvasH: drawCam.height,
              });
            },
          });
        }
      }

      // 2. Moored Sailboats with Wind-Synced Pennants & Night Anchor Lights
      for (let idx = 0; idx < MOORED_BOATS.length; idx++) {
        const mb = MOORED_BOATS[idx];
        if (!isWater(mb.u, mb.v)) continue;
        const wx = mb.u * worldW;
        const wy = mb.v * worldH;

        inspectables.push({
          kind: 'boat',
          id: mb.id,
          wx,
          wy,
          radiusCss: 11,
          title: mb.name,
          sub: isNight ? 'Moored at anchor with masthead anchor light' : 'Moored sailboat bobbing in Lake Zurich breeze',
          specs: [
            ['Class', 'Moored Keelboat'],
            ['Status', isNight ? 'At Anchor · Lit' : 'Moored'],
            ['Wind', `${Math.round(wind.strength * 14)} km/h SW`],
            ['Waters', 'Lake Zurich'],
          ],
        });

        drawables.push({
          layer: 'water',
          sortY: wy,
          draw(targetCtx) {
            const bx = ctx.toX(mb.u);
            const by = ctx.toY(mb.v);
            if (!ctx.inView(bx, by, 32)) return;

            const bobPx = Math.sin(tSec * (2.1 + idx * 0.23) + idx * 1.7) * 0.75 * wind.strength * s;
            const swayPx = (wind.wx * 0.65 + Math.sin(tSec * (1.7 + idx * 0.19) + idx * 2.3) * 0.95 * wind.strength) * s;
            const p = Math.max(0.85, s);
            const hy = by + bobPx;

            targetCtx.save();
            targetCtx.strokeStyle = isNight ? 'rgba(130, 175, 224, 0.26)' : 'rgba(226, 246, 255, 0.42)';
            targetCtx.lineWidth = Math.max(0.8, 0.9 * p);
            targetCtx.beginPath();
            targetCtx.ellipse(bx, by + 1.8 * p, 6.4 * p, 2.3 * p, -0.15, 0, Math.PI * 2);
            targetCtx.stroke();

            targetCtx.fillStyle = shadeHex('#2c3a48', 0.9, mode);
            targetCtx.fillRect(Math.round(bx - 5.4 * p), Math.round(hy - 0.8 * p), Math.max(4, Math.round(10.8 * p)), Math.max(2, Math.round(3.6 * p)));
            targetCtx.fillStyle = shadeHex('#eef2f6', 1.04, mode);
            targetCtx.fillRect(Math.round(bx - 5.0 * p), Math.round(hy - 1.4 * p), Math.max(4, Math.round(10.0 * p)), Math.max(2, Math.round(3.0 * p)));
            targetCtx.fillStyle = shadeHex('#26384c', 0.95, mode);
            targetCtx.fillRect(Math.round(bx - 2.4 * p), Math.round(hy - 0.8 * p), Math.max(2, Math.round(4.4 * p)), Math.max(1.5, Math.round(1.6 * p)));

            const mastTopX = bx + swayPx;
            const mastTopY = hy - 18.0 * p;
            targetCtx.strokeStyle = shadeHex('#cbd5e1', 1.0, mode);
            targetCtx.lineWidth = Math.max(1.0, 1.05 * p);
            targetCtx.beginPath();
            targetCtx.moveTo(bx, hy - 1.2 * p);
            targetCtx.lineTo(mastTopX, mastTopY);
            targetCtx.stroke();

            targetCtx.strokeStyle = shadeHex('#f8fafc', 1.0, mode);
            targetCtx.lineWidth = Math.max(1.0, 1.2 * p);
            targetCtx.beginPath();
            targetCtx.moveTo(bx + swayPx * 0.25, hy - 5.0 * p);
            targetCtx.lineTo(bx - 4.8 * p + swayPx * 0.25, hy - 4.2 * p);
            targetCtx.stroke();

            const flutter = Math.sin(wind.wavePhase * 1.2 + idx * 1.9) * 0.9 * p;
            targetCtx.fillStyle = shadeHex(mb.pen, 1.05, mode);
            targetCtx.fillRect(Math.round(mastTopX), Math.round(mastTopY + flutter * 0.4), Math.max(2, Math.round(3.4 * p)), Math.max(1, Math.round(1.2 * p)));

            if (isNight) {
              const aSz = Math.max(1.5, 1.6 * p);
              blitGlow(targetCtx, mastTopX, mastTopY, Math.max(2.6, 3.6 * p), 'warm', 0.45);
              targetCtx.fillStyle = '#ffe8a3';
              targetCtx.fillRect(Math.round(mastTopX - aSz * 0.5), Math.round(mastTopY - aSz * 0.5), Math.round(aSz), Math.round(aSz));
              targetCtx.fillStyle = 'rgba(255, 224, 140, 0.36)';
              targetCtx.fillRect(Math.round(bx + swayPx * 0.3 - aSz * 0.5), Math.round(by + 4.0 * p), Math.round(aSz), Math.max(1, Math.round(1.0 * p)));
            }
            targetCtx.restore();
          },
        });
      }

      cachedInspectables = inspectables;
      return drawables;
    },

    getInspectables() {
      return cachedInspectables;
    },

    getFollowTarget(kind, ctx) {
      if (kind !== 'boat' || !ctx) return null;
      const sim = ensureSim(ctx);
      const list = sim.getVessels();
      // Prefer ZSG MS Helvetia steamer first
      for (let i = 0; i < list.length; i++) {
        if (list[i].kind === 'zsg_steamer' && list[i].visible) {
          return { wx: list[i].u * ctx.worldW, wy: list[i].v * ctx.worldH };
        }
      }
      for (let i = 0; i < list.length; i++) {
        if (list[i].animShip && list[i].visible) {
          return { wx: list[i].u * ctx.worldW, wy: list[i].v * ctx.worldH };
        }
      }
      return null;
    },

    getAudioSignals(ctx) {
      if (!ctx) return [];
      const sim = ensureSim(ctx);
      const list = sim.getVessels();
      const signals = [];
      for (let i = 0; i < list.length; i++) {
        const v = list[i];
        if (!v.visible) continue;
        const isSteamer = v.kind === 'zsg_steamer';
        const isMotor = v.kind === 'motorboat';
        if (!isSteamer && !isMotor) continue;
        signals.push({
          channel: 'boat',
          u: v.u,
          v: v.v,
          weight: v.isDocked ? 0.22 : (isSteamer ? (0.45 + 0.55 * v.speedRatio) : 0.42 * v.speedRatio),
          brightnessMul: isSteamer ? 0.80 : 0.95,
          offscreenRange: 0.35,
          sumMode: 'max',
        });
      }
      return signals;
    },

    getLivingCounts() {
      return { ...counts };
    },

    getCounts() {
      return { ...counts };
    },
  };
}
