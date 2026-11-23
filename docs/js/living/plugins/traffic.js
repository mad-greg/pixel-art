/**
 * Traffic, ZVV Buses & Cyclists Plugin (Kilchberg v13.0).
 *
 * Thin adapter wrapping docs/js/sim/traffic.js (createTrafficSim) UNCHANGED so all
 * IDM physics, bumper non-overlap clamps, crosswalk yielding, and ?t= determinism
 * remain 100% intact.
 *
 * Preserves strict per-class extraVertPx:
 *   - ZVV buses (161 articulated & 165 rigid): 6.5 (opaque roofs!)
 *   - Cars & Swiss delivery vans: 3.0
 *   - Cyclists & fallback crosswalk walkers: 2.0
 */

import { createTrafficSim } from '../../sim/traffic.js';
import { formatRoadName } from '../../sim/schedule.js';
import {
  draw3DArticulatedBus,
  draw3DBus,
  draw3DCar,
  draw3DCyclist,
  shadeHex,
} from '../../render/vehicles.js';
import { drawMiniPerson } from '../draw.js';

const CW_COATS = ['#c53030', '#2b6cb0', '#2f855a', '#d69e2e', '#6b46c1', '#dd6b20'];
const CW_HAIRS = ['#2d241c', '#5c4028', '#8a6842', '#3a3430', '#b89458'];
const LOD_CAR_COLS = ['#e2e8f0', '#cbd5e1', '#94a3b8', '#475569', '#dc2626', '#2563eb', '#1e293b', '#f59e0b'];

export function createTrafficPlugin() {
  let trafficSim = null;
  let unsubBusSpecs = null;
  let counts = { cars: 0, buses: 0, cyclists: 0 };
  let cachedInspectables = [];

  return {
    id: 'traffic',
    name: 'Kilchberg Traffic, ZVV Buses & Cyclists',
    category: 'transit',
    layers: ['ground_y'],
    priority: 30,
    enabledByDefault: true,

    init(ctx) {
      if (unsubBusSpecs) {
        unsubBusSpecs();
        unsubBusSpecs = null;
      }
      trafficSim = ctx.animData ? createTrafficSim(ctx.animData) : null;
      if (trafficSim && ctx.specs && typeof ctx.specs.getBusRoutes === 'function') {
        trafficSim.setBusRouteSpecs(ctx.specs.getBusRoutes());
        if (typeof ctx.specs.onChange === 'function') {
          unsubBusSpecs = ctx.specs.onChange('bus', () => {
            if (trafficSim) trafficSim.setBusRouteSpecs(ctx.specs.getBusRoutes());
          });
        }
      }
      ctx.shared.trafficSim = trafficSim;
      counts = { cars: 0, buses: 0, cyclists: 0 };
      cachedInspectables = [];
    },

    update(_dt, ctx) {
      if (!trafficSim) return;
      if (ctx.shared.pedSim) {
        trafficSim.setCrosswalkOverrideMode(true);
        if (ctx.shared.pedStats) {
          trafficSim.setExternalPedestrianStats(ctx.shared.pedStats);
        }
        if (typeof ctx.shared.pedSim.getActivePedestrianPositions === 'function') {
          trafficSim.setExternalPedestrians(ctx.shared.pedSim.getActivePedestrianPositions());
        }
      }
      const isLiveMode = !!(ctx.clock && ctx.clock.clockMode !== 'deterministic');
      ctx.shared.lastSimSnapshot = trafficSim.updateToTime(
        ctx.tSec,
        ctx.mode,
        ctx.shared.occupiedCrosswalks || null,
        isLiveMode,
      );
    },

    getDrawables(cam, ctx) {
      if (!trafficSim) return [];

      const { worldW, worldH, wScale, tSec, mode, isNight, isSunset, s, depthMgr } = ctx;
      const hasDepth = !!(depthMgr && depthMgr.hasDepthMap && depthMgr.hasDepthMap());
      const drawables = [];
      const inspectables = [];
      counts = { cars: 0, buses: 0, cyclists: 0 };

      const veh = trafficSim.getDrawableVehicles(worldW, worldH, wScale);
      if (!veh) {
        cachedInspectables = inspectables;
        return drawables;
      }

      // 1. ZVV Buses (extraVertPx = 6.5 strict!)
      for (let i = 0; i < veh.buses.length; i++) {
        const bItem = veh.buses[i];
        if (!hasDepth && bItem.pos.occ) continue;
        counts.buses++;
        const routeNum = bItem.routeNum || '161';
        const roadLabel = formatRoadName(bItem.roadId || bItem.id);
        inspectables.push({
          kind: 'bus',
          id: bItem.id,
          wx: bItem.pos.wx,
          wy: bItem.pos.wy,
          radiusCss: 14,
          title: bItem.tripLabel || `ZVV Bus ${routeNum} · ${roadLabel}`,
          sub: bItem.isDwelling ? 'Dwelling at bus stop (boarding & alighting)' : `In service along ${roadLabel}`,
          specs: [
            ['Line', `ZVV ${routeNum}`],
            ['Status', bItem.isDwelling ? 'Stop Dwell' : (bItem.signals && bItem.signals.braking ? 'Braking' : 'Cruising')],
            ['Vehicle', bItem.type === 'bus_artic' ? 'Articulated 19 m' : 'Standard 12 m'],
            ['Speed', `${Math.round((bItem.speedRatio || 0) * 42)} km/h`],
          ],
        });

        if (s < 0.35) {
          // Lightweight Fit-zoom LOD marker (avoids ~90 offscreen depthMasked readbacks at s < 0.35)
          const isArtic = bItem.type === 'bus_artic';
          drawables.push({
            layer: 'ground_y',
            sortY: bItem.pos.wy,
            depthMasked: false,
            draw(targetCtx, drawCam) {
              const sx = bItem.pos.wx * drawCam.scale + drawCam.offsetX;
              const sy = bItem.pos.wy * drawCam.scale + drawCam.offsetY;
              if (sx < -16 || sx > drawCam.width + 16 || sy < -16 || sy > drawCam.height + 16) return;
              const w = Math.max(3, Math.round((isArtic ? 11 : 8) * s));
              const h = Math.max(2, Math.round(4.5 * s));
              const x0 = Math.round(sx - w * 0.5);
              const y0 = Math.round(sy - h * 0.5);
              targetCtx.fillStyle = isNight ? '#cbd5e1' : '#f8fafc';
              targetCtx.fillRect(x0, y0, w, h);
              targetCtx.fillStyle = '#005ca9';
              targetCtx.fillRect(x0, y0 + h - Math.max(1, Math.round(h * 0.35)), w, Math.max(1, Math.round(h * 0.35)));
            },
          });
        } else {
          let bounds;
          if (bItem.type === 'bus_artic') {
            const hdx = Math.abs(bItem.pFront.wx - bItem.pRear.wx) * 0.5;
            const hdy = Math.abs(bItem.pFront.wy - bItem.pRear.wy) * 0.5;
            const nExtra = isNight ? 32 * wScale : (isSunset ? 18 * wScale : 6 * wScale);
            const yExtra = isNight ? 20 * wScale : (isSunset ? 12 * wScale : 0);
            bounds = {
              ex: hdx + 16 * wScale + nExtra,
              eyUp: hdy + 20 * wScale + yExtra,
              eyDn: hdy + 10 * wScale + yExtra,
            };
          } else {
            const atx = Math.abs(bItem.pos.tx);
            const aty = Math.abs(bItem.pos.ty);
            const nExtra = isNight ? 32 * wScale : (isSunset ? 18 * wScale : 4 * wScale);
            const yExtra = isNight ? 18 * wScale : (isSunset ? 12 * wScale : 0);
            bounds = {
              ex: (atx * 24 + 9) * wScale + nExtra,
              eyUp: (aty * 24 + 16) * wScale + yExtra,
              eyDn: (aty * 24 + 7) * wScale + yExtra,
            };
          }

          drawables.push({
            layer: 'ground_y',
            sortY: bItem.pos.wy,
            depthMasked: true,
            wx: bItem.pos.wx,
            wy: bItem.pos.wy,
            bounds,
            d16: bItem.pos.d16,
            extraVertPx: 6.5,
            draw(targetCtx, drawCam) {
              if (bItem.type === 'bus_artic') {
                draw3DArticulatedBus(
                  targetCtx, drawCam,
                  bItem.pRear, bItem.pMidRear, bItem.pMidFront, bItem.pFront,
                  wScale, mode, tSec, bItem.speedRatio, bItem.isDwelling, bItem.signals,
                );
              } else {
                draw3DBus(
                  targetCtx, drawCam,
                  bItem.pos, wScale, mode, tSec, bItem.speedRatio, bItem.isDwelling, routeNum, bItem.signals,
                );
              }
            },
          });
        }
      }

      // 2. Passenger Cars & Swiss Delivery Vans (extraVertPx = 3.0)
      for (let i = 0; i < veh.cars.length; i++) {
        const cItem = veh.cars[i];
        if (!hasDepth && cItem.pos.occ) continue;
        counts.cars++;
        const sig = cItem.signals || {};
        const isMotorway = !!(cItem.id && cItem.id.includes('motorway'));
        const roadLabel = formatRoadName(cItem.roadId || (isMotorway ? 'a3_motorway' : 'seestrasse'));
        inspectables.push({
          kind: 'car',
          id: cItem.id,
          wx: cItem.pos.wx,
          wy: cItem.pos.wy,
          radiusCss: 10,
          title: cItem.tripLabel || `Local Traffic · ${roadLabel}`,
          sub: sig.isDeliveryStop
            ? 'Curbside delivery pause (hazard flashers)'
            : (sig.braking ? 'Braking / yielding to traffic or zebra crossing' : `En route along ${roadLabel}`),
          specs: [
            ['Type', sig.isDeliveryStop ? 'Delivery Van' : 'Passenger Vehicle'],
            ['Status', sig.isDeliveryStop ? 'Delivery Stop' : (sig.braking ? 'Yielding / Braking' : 'Cruising')],
            ['Speed', `${Math.round((sig.speedRatio || 0) * 50)} km/h`],
            ['Corridor', isMotorway ? 'A3 Motorway' : roadLabel],
          ],
        });

        if (s < 0.35) {
          // Lightweight Fit-zoom LOD marker (skips offscreen depthMasked readbacks at s < 0.35)
          const col = LOD_CAR_COLS[Math.abs(cItem.colorIdx || 0) % LOD_CAR_COLS.length];
          drawables.push({
            layer: 'ground_y',
            sortY: cItem.pos.wy,
            depthMasked: false,
            draw(targetCtx, drawCam) {
              const sx = cItem.pos.wx * drawCam.scale + drawCam.offsetX;
              const sy = cItem.pos.wy * drawCam.scale + drawCam.offsetY;
              if (sx < -12 || sx > drawCam.width + 12 || sy < -12 || sy > drawCam.height + 12) return;
              const w = Math.max(2, Math.round(5.0 * s));
              const h = Math.max(2, Math.round(3.2 * s));
              const x0 = Math.round(sx - w * 0.5);
              const y0 = Math.round(sy - h * 0.5);
              targetCtx.fillStyle = col;
              targetCtx.fillRect(x0, y0, w, h);
              if (isNight || isSunset) {
                targetCtx.fillStyle = isNight ? '#fef08a' : '#fde68a';
                targetCtx.fillRect(Math.round(sx + cItem.pos.tx * w * 0.5), Math.round(sy + cItem.pos.ty * h * 0.5), 1, 1);
              }
            },
          });
        } else {
          const atx = Math.abs(cItem.pos.tx);
          const aty = Math.abs(cItem.pos.ty);
          const nExtra = isNight ? 24 * wScale : (isSunset ? 16 * wScale : 4 * wScale);
          const yExtra = isNight ? 14 * wScale : (isSunset ? 10 * wScale : 2 * wScale);
          const bounds = {
            ex: (atx * 12 + 7) * wScale + nExtra,
            eyUp: (aty * 12 + 11) * wScale + yExtra,
            eyDn: (aty * 12 + 6) * wScale + yExtra,
          };

          drawables.push({
            layer: 'ground_y',
            sortY: cItem.pos.wy,
            depthMasked: true,
            wx: cItem.pos.wx,
            wy: cItem.pos.wy,
            bounds,
            d16: cItem.pos.d16,
            extraVertPx: 3.0,
            draw(targetCtx, drawCam) {
              draw3DCar(targetCtx, drawCam, cItem.pos, cItem.colorIdx, wScale, mode, tSec, cItem.signals);
            },
          });
        }
      }

      // 3. Grade-aware Cyclists & Fallback Crosswalk Walkers (extraVertPx = 2.0)
      if (s >= 0.35) {
        for (let i = 0; i < veh.cyclists.length; i++) {
          const cycItem = veh.cyclists[i];
          if (!hasDepth && cycItem.pos.occ) continue;
          counts.cyclists++;
          inspectables.push({
            kind: 'cyclist',
            id: cycItem.id,
            wx: cycItem.pos.wx,
            wy: cycItem.pos.wy,
            radiusCss: 9,
            title: 'Cyclist · Kilchberg Corridor',
            sub: 'Grade-aware pace rider on Kilchberg road network',
            specs: [
              ['Mode', 'Bicycle'],
              ['Status', 'Active Ride'],
              ['Route', 'Seestrasse / Dorfstrasse'],
              ['Priority', 'Yields at stops & crossings'],
            ],
          });

          const bounds = {
            ex: (isNight ? 14 : 7) * wScale,
            eyUp: 11 * wScale,
            eyDn: (isNight ? 9 : 4) * wScale,
          };

          drawables.push({
            layer: 'ground_y',
            sortY: cycItem.pos.wy,
            depthMasked: true,
            wx: cycItem.pos.wx,
            wy: cycItem.pos.wy,
            bounds,
            d16: cycItem.pos.d16,
            extraVertPx: 2.0,
            draw(targetCtx, drawCam) {
              draw3DCyclist(targetCtx, drawCam, cycItem.pos, cycItem.colorIdx, wScale, mode, tSec);
            },
          });
        }

        // Legacy crosswalk walkers (active only when pedSim override is off)
        for (let i = 0; i < (veh.crosswalkWalkers || []).length; i++) {
          const cwW = veh.crosswalkWalkers[i];
          const coat = shadeHex(CW_COATS[cwW.colorIdx % CW_COATS.length], 1.0, mode);
          const pants = shadeHex('#243040', 1.0, mode);
          const hair = CW_HAIRS[cwW.colorIdx % CW_HAIRS.length];
          drawables.push({
            layer: 'ground_y',
            sortY: cwW.pos.wy,
            depthMasked: true,
            wx: cwW.pos.wx,
            wy: cwW.pos.wy,
            bounds: { ex: 4.5 * wScale, eyUp: 9.5 * wScale, eyDn: 3.5 * wScale },
            d16: cwW.pos.d16,
            extraVertPx: 2.0,
            draw(targetCtx, drawCam) {
              drawMiniPerson(
                targetCtx,
                drawCam.offsetX + cwW.pos.wx * drawCam.scale,
                drawCam.offsetY + cwW.pos.wy * drawCam.scale,
                drawCam.scale * wScale * 0.90,
                coat,
                pants,
                hair,
                isNight,
                cwW.stride,
                null,
                drawCam.width,
                drawCam.height,
              );
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
      if (kind !== 'bus' || !trafficSim) return null;
      return trafficSim.getFollowTarget('bus', ctx.worldW, ctx.worldH);
    },

    getAudioSignals(ctx) {
      if (!trafficSim) return [];
      const veh = trafficSim.getDrawableVehicles(ctx.worldW, ctx.worldH, ctx.wScale);
      if (!veh) return [];
      const invW = 1 / Math.max(1, ctx.worldW);
      const invH = 1 / Math.max(1, ctx.worldH);
      const signals = [];

      for (let i = 0; i < veh.buses.length; i++) {
        const b = veh.buses[i];
        signals.push({
          channel: 'bus',
          u: b.pos.wx * invW,
          v: b.pos.wy * invH,
          weight: b.isDwelling ? 0.25 : (0.35 + 0.65 * (b.speedRatio || 0)),
          brightnessMul: b.isDwelling ? 0.55 : 0.85,
          offscreenRange: 0.35,
          sumMode: 'max',
        });
      }

      for (let i = 0; i < veh.cars.length; i++) {
        const c = veh.cars[i];
        const isMotorway = !!(c.id && c.id.includes('motorway'));
        const spd = (c.signals && typeof c.signals.speedRatio === 'number') ? c.signals.speedRatio : 0.7;
        signals.push({
          channel: isMotorway ? 'traffic' : 'town_traffic',
          u: c.pos.wx * invW,
          v: c.pos.wy * invH,
          weight: Math.max(0.15, spd * (isMotorway ? 0.55 : 0.32)),
          brightnessMul: isMotorway ? 0.9 : 0.75,
          offscreenRange: isMotorway ? 0.40 : 0.30,
          sumMode: 'rms',
        });
      }

      return signals;
    },

    getLivingCounts() {
      return { ...counts };
    },

    getSimStats() {
      return trafficSim ? trafficSim.getStats() : null;
    },

    getTransitSnapshot() {
      return trafficSim ? trafficSim.getTransitSnapshot() : null;
    },

    destroy() {
      if (unsubBusSpecs) {
        unsubBusSpecs();
        unsubBusSpecs = null;
      }
      trafficSim = null;
      cachedInspectables = [];
    },
  };
}
