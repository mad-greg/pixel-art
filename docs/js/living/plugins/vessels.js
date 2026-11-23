/**
 * Lake Zurich Vessels & Watercraft Plugin (Kilchberg v13.0).
 *
 * Layer: 'water' (Y-sorted, 100% isWaterUV-strict for micro-craft):
 *   - Active fleet from animData.ships: ZSG MS Helvetia paddle steamer, tacking sailboats,
 *     Boesch mahogany runabout (rendered via upgraded drawShipEntity with extraVertPx = 6.0)
 *   - 5 moored sailboats with wind-synced pennants & night anchor lights
 *   - 2 slow realistic Stand-Up Paddleboarders (~1.6 m/s, sups >= 2 in day, 0 at night)
 *     with dip-and-pull paddle strokes & expanding ripple rings
 *   - Wooden rowing skiff near Bendlikon–Sulzergut with twin sweeping oars
 *
 * ALL vessels are inspectable via getInspectables().
 */

import { evalShipState, samplePathAt } from '../../sim/schedule.js';
import { drawShipEntity, shadeHex } from '../../render/vehicles.js';
import { blitGlow, drawMiniPersonV2, drawWaterRipples } from '../draw.js';

const MOORED_BOATS = [
  { id: 'moored:bendlikon_1', name: 'Moored Sailboat · Bendlikon Buoy', u: 0.5758, v: 0.5835, pen: '#d9382e' },
  { id: 'moored:bendlikon_2', name: 'Moored Sailboat · Schifflände Bay', u: 0.5935, v: 0.5675, pen: '#2563eb' },
  { id: 'moored:seebad_1', name: 'Moored Sailboat · Schooren Mooring', u: 0.4435, v: 0.6995, pen: '#d9382e' },
  { id: 'moored:seebad_2', name: 'Moored Sailboat · Seebad South', u: 0.4145, v: 0.7315, pen: '#2563eb' },
  { id: 'moored:seebad_3', name: 'Moored Sailboat · Rüschlikon Border', u: 0.4045, v: 0.7395, pen: '#eab308' },
];

// Slow realistic SUP routes (~1.57–1.72 m/s, waterMask-strict)
const SUP_ROUTES = [
  { id: 'sup:bendlikon', name: 'SUP Paddler · Bendlikon Bay', u0: 0.566, v0: 0.610, u1: 0.629, v1: 0.566, spd: 0.0024, ph: 0.15, board: '#38bdf8', shirt: '#f43f5e', hair: '#2d241c' },
  { id: 'sup:seebad', name: 'SUP Paddler · Seebad Shallows', u0: 0.446, v0: 0.730, u1: 0.506, v1: 0.675, spd: 0.0021, ph: 0.62, board: '#fbbf24', shirt: '#0d9488', hair: '#5c4028' },
];

const SKIFF_ROUTE = {
  id: 'skiff:sulzergut',
  name: 'Wooden Rowing Skiff · Lake Zurich',
  u0: 0.618,
  v0: 0.566,
  u1: 0.678,
  v1: 0.522,
  spd: 0.0026,
  ph: 0.31,
};

export function createVesselsPlugin() {
  let counts = { ships: 0, sups: 0 };
  let cachedInspectables = [];

  return {
    id: 'vessels',
    name: 'Lake Zurich Fleet, Moored Boats, SUPs & Skiff',
    category: 'water',
    layers: ['water'],
    priority: 20,
    enabledByDefault: true,

    init() {
      counts = { ships: 0, sups: 0 };
      cachedInspectables = [];
    },

    getDrawables(cam, ctx) {
      const animData = ctx.animData;
      const { worldW, worldH, wScale, tSec, mode, isNight, isSunset, s, wind, depthMgr } = ctx;
      const isWater = (u, v) => (!depthMgr || !depthMgr.isWaterUV || depthMgr.isWaterUV(u, v));

      const drawables = [];
      const inspectables = [];
      counts = { ships: 0, sups: 0 };

      // 1. Active Lake Zurich Fleet (ZSG MS Helvetia, Sailboats, Boesch Runabout)
      const ships = (animData && animData.ships) || [];
      for (let sIdx = 0; sIdx < ships.length; sIdx++) {
        const ship = ships[sIdx];
        const st = evalShipState(ship, tSec, mode);
        if (!st.visible || st.frac < 0 || st.frac > 1) continue;
        const pos = samplePathAt(ship.pts, st.frac, worldW, worldH, 3);
        if (!pos) continue;

        counts.ships++;
        const isSteamer = ship.kind === 'zsg_steamer';
        const isMotor = ship.kind === 'motorboat';
        inspectables.push({
          kind: 'boat',
          id: ship.id || `ship:${sIdx}`,
          wx: pos.wx,
          wy: pos.wy,
          radiusCss: isSteamer ? 18 : 13,
          title: isSteamer ? 'ZSG MS Helvetia → Bendlikon Pier' : (ship.name || 'Lake Zurich Vessel'),
          sub: isSteamer
            ? (st.isDocked ? 'Docked at Bendlikon Pier (gangplank deployed)' : 'Cruising Lake Zurich shoreline')
            : (isMotor ? 'Boesch mahogany runabout on Lake Zurich' : 'Tacking sailboat on Lake Zurich'),
          specs: [
            ['Service', isSteamer ? 'ZSG Zürichsee' : (isMotor ? 'Boesch Runabout' : 'Private Sailboat')],
            ['Status', st.isDocked ? 'Docked · Boarding' : 'Underway'],
            ['Route', isSteamer ? 'Zürich Bürkliplatz – Bendlikon – Thalwil' : 'Lake Zurich'],
            ['Speed', `${Math.round((ship.speed_mps || 5) * st.speedRatio * 3.6)} km/h`],
          ],
        });

        drawables.push({
          layer: 'water',
          sortY: pos.wy,
          depthMasked: false, // drawShipEntity invokes depthMgr.drawDepthMasked(..., 6.0) internally
          draw(targetCtx, drawCam) {
            drawShipEntity(targetCtx, depthMgr, drawCam, ship, st, sIdx, worldW, worldH, wScale, mode, tSec);
          },
        });
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

            // Wind-synced masthead pennant
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

      // 3. Slow Realistic SUP Paddlers (~1.6 m/s, Day & Sunset ONLY — 0 at night!)
      if (!isNight) {
        for (let i = 0; i < SUP_ROUTES.length; i++) {
          const sp = SUP_ROUTES[i];
          const phase = tSec * sp.spd * Math.PI * 2 + sp.ph * Math.PI * 2;
          const frac = 0.5 + 0.5 * Math.sin(phase);
          const cosP = Math.cos(phase);
          const headingSign = cosP >= 0 ? 1 : -1;
          const speedMag = Math.abs(cosP);
          const su = sp.u0 + (sp.u1 - sp.u0) * frac;
          const sv = sp.v0 + (sp.v1 - sp.v0) * frac;
          if (!isWater(su, sv)) continue;

          counts.sups++;
          const wx = su * worldW;
          const wy = sv * worldH;

          inspectables.push({
            kind: 'boat',
            id: sp.id,
            wx,
            wy,
            radiusCss: 10,
            title: sp.name,
            sub: 'Gliding at a relaxed paddle pace across Lake Zurich',
            specs: [
              ['Craft', 'Stand-Up Paddleboard'],
              ['Pace', `${(1.6 * Math.max(0.25, speedMag)).toFixed(1)} m/s`],
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

              const rawDx = (sp.u1 - sp.u0) * worldW * drawCam.scale;
              const rawDy = (sp.v1 - sp.v0) * worldH * drawCam.scale;
              const len = Math.hypot(rawDx, rawDy) || 1;
              const tx = (rawDx / len) * headingSign;
              const ty = (rawDy / len) * headingSign;
              const ang = Math.atan2(ty, tx);
              const px = Math.max(1.0, 1.15 * s);

              // Trailing gentle wake
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

              // Pointed SUP board
              targetCtx.save();
              targetCtx.translate(sx, sy);
              targetCtx.rotate(ang);
              targetCtx.fillStyle = shadeHex(sp.board, 1.0, mode);
              targetCtx.beginPath();
              targetCtx.moveTo(-3.8 * px, -0.95 * px);
              targetCtx.lineTo(2.4 * px, -0.95 * px);
              targetCtx.lineTo(4.2 * px, 0);
              targetCtx.lineTo(2.4 * px, 0.95 * px);
              targetCtx.lineTo(-3.8 * px, 0.95 * px);
              targetCtx.closePath();
              targetCtx.fill();
              targetCtx.restore();

              // Standing paddler
              drawMiniPersonV2(targetCtx, sx, sy - 0.5 * px, s * 0.88, {
                coatCol: shadeHex(sp.shirt, 1.0, mode),
                pantsCol: '#1e293b',
                hairCol: sp.hair,
                isNight: false,
                phase: 0,
                canvasW: drawCam.width,
                canvasH: drawCam.height,
              });

              // Smooth dip-and-pull paddle stroke + expanding ripple rings
              const strokePhase = tSec * 1.35 + i * 2.1;
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
        }
      }

      // 4. Slow Wooden Rowing Skiff near Bendlikon–Sulzergut (Day & Sunset, waterMask-strict)
      if (!isNight) {
        const rb = SKIFF_ROUTE;
        const rPhase = tSec * rb.spd * Math.PI * 2 + rb.ph * Math.PI * 2;
        const rp = 0.5 + 0.5 * Math.sin(rPhase);
        const rCos = Math.cos(rPhase);
        const rSign = rCos >= 0 ? 1 : -1;
        const rSpeed = Math.abs(rCos);
        const ru = rb.u0 + (rb.u1 - rb.u0) * rp;
        const rv = rb.v0 + (rb.v1 - rb.v0) * rp;

        if (isWater(ru, rv)) {
          const wx = ru * worldW;
          const wy = rv * worldH;

          inspectables.push({
            kind: 'boat',
            id: rb.id,
            wx,
            wy,
            radiusCss: 11,
            title: rb.name,
            sub: 'Cedar-wood rowing skiff sweeping past Sulzergut',
            specs: [
              ['Craft', 'Wooden Rowing Skiff'],
              ['Pace', `${(1.75 * Math.max(0.25, rSpeed)).toFixed(1)} m/s`],
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

              const rawDx = (rb.u1 - rb.u0) * worldW * drawCam.scale;
              const rawDy = (rb.v1 - rb.v0) * worldH * drawCam.scale;
              const len = Math.hypot(rawDx, rawDy) || 1;
              const tx = (rawDx / len) * rSign;
              const ty = (rawDy / len) * rSign;
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

              // Seated rower
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

      cachedInspectables = inspectables;
      return drawables;
    },

    getInspectables() {
      return cachedInspectables;
    },

    getFollowTarget(kind, ctx) {
      if (kind !== 'boat' || !ctx.animData || !ctx.animData.ships) return null;
      const ships = ctx.animData.ships;
      // Prefer ZSG MS Helvetia steamer first
      for (let i = 0; i < ships.length; i++) {
        const ship = ships[i];
        const st = evalShipState(ship, ctx.tSec, ctx.mode);
        if (st.visible && st.frac >= 0 && st.frac <= 1) {
          const pos = samplePathAt(ship.pts, st.frac, ctx.worldW, ctx.worldH, 2);
          if (pos) return { wx: pos.wx, wy: pos.wy };
        }
      }
      return null;
    },

    getAudioSignals(ctx) {
      if (!ctx.animData || !ctx.animData.ships) return [];
      const signals = [];
      const ships = ctx.animData.ships;
      for (let i = 0; i < ships.length; i++) {
        const ship = ships[i];
        const st = evalShipState(ship, ctx.tSec, ctx.mode);
        if (!st.visible || st.frac < 0 || st.frac > 1) continue;
        const pos = samplePathAt(ship.pts, st.frac, ctx.worldW, ctx.worldH, 2);
        if (!pos) continue;
        const isSteamer = ship.kind === 'zsg_steamer';
        const isMotor = ship.kind === 'motorboat';
        if (!isSteamer && !isMotor) continue;
        signals.push({
          channel: 'boat',
          u: pos.wx / Math.max(1, ctx.worldW),
          v: pos.wy / Math.max(1, ctx.worldH),
          weight: st.isDocked ? 0.22 : (isSteamer ? (0.45 + 0.55 * st.speedRatio) : 0.42 * st.speedRatio),
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
  };
}
