/**
 * Purposeful Pedestrians & Named Kilchberg Inhabitants Plugin (Kilchberg v14.0).
 *
 * Wraps docs/js/sim/pedestrians.js (createPedestrianSim) with SpecRegistry hot-sync
 * for named Kilchberg residents (`InhabitantSpec`), KilchbergClock routine awareness,
 * and rich click inspection while preserving all T2.SM.03 / T2.FA3.07 invariants.
 */

import { createPedestrianSim, drawPedestrianEntity } from '../../sim/pedestrians.js';

export function createPedestriansPlugin() {
  let pedSim = null;
  let unsubInhabSpecs = null;
  let counts = { roadPeds: 0, busStopCommuters: 0 };
  let cachedInspectables = [];

  return {
    id: 'pedestrians',
    name: 'Purposeful Kilchberg Pedestrians',
    category: 'people',
    layers: ['ground_y'],
    priority: 35,
    enabledByDefault: true,

    init(ctx) {
      if (unsubInhabSpecs) {
        unsubInhabSpecs();
        unsubInhabSpecs = null;
      }
      pedSim = ctx.animData ? createPedestrianSim(ctx.animData) : null;
      if (pedSim && ctx.specs && typeof ctx.specs.getInhabitants === 'function') {
        pedSim.setInhabitantSpecs(ctx.specs.getInhabitants());
        if (typeof ctx.specs.onChange === 'function') {
          unsubInhabSpecs = ctx.specs.onChange('inhabitants', () => {
            if (pedSim) pedSim.setInhabitantSpecs(ctx.specs.getInhabitants());
          });
        }
      }
      ctx.shared.pedSim = pedSim;
      counts = { roadPeds: 0, busStopCommuters: 0 };
      cachedInspectables = [];
    },

    update(_dt, ctx) {
      if (!pedSim) return;
      if (typeof pedSim.setClockSnapshot === 'function') {
        pedSim.setClockSnapshot(ctx.clock || null);
      }
      const liveSnap = (ctx.shared.lastSimSnapshot && ctx.shared.lastSimSnapshot.mode === ctx.mode)
        ? ctx.shared.lastSimSnapshot
        : null;
      const isLiveMode = !!(ctx.clock && ctx.clock.clockMode !== 'deterministic');
      pedSim.updateToTime(ctx.tSec, ctx.mode, liveSnap, isLiveMode);
      ctx.shared.occupiedCrosswalks = pedSim.getOccupiedCrosswalks();
      ctx.shared.pedStats = pedSim.getStats();
    },

    getDrawables(cam, ctx) {
      if (!pedSim || ctx.s < 0.35) {
        counts = { roadPeds: 0, busStopCommuters: 0 };
        cachedInspectables = [];
        return [];
      }

      const { worldW, worldH, wScale, tSec, mode, depthMgr } = ctx;
      const pedItems = pedSim.getDrawablePedestrians(worldW, worldH, wScale, cam, depthMgr);
      const drawables = [];
      const inspectables = [];
      counts = { roadPeds: 0, busStopCommuters: 0 };

      for (let i = 0; i < pedItems.length; i++) {
        const pItem = pedItems[i];
        if (
          pItem.role === 'bus_rider'
          && (pItem.state === 'queue_bus' || pItem.state === 'boarding' || pItem.state === 'alighting')
        ) {
          counts.busStopCommuters++;
        } else {
          counts.roadPeds++;
        }

        const isInhab = !!pItem.inhabitantName;
        inspectables.push({
          kind: 'pedestrian',
          id: pItem.id,
          inhabitantId: pItem.inhabitantId || null,
          wx: pItem.pos.wx,
          wy: pItem.pos.wy,
          radiusCss: 8,
          title: isInhab ? pItem.inhabitantName : (pItem.tripLabel || 'Villager · Kilchberg'),
          sub: isInhab
            ? `${pItem.inhabitantRole || 'Kilchberg Resident'} · ${pItem.activityLabel || pItem.state.replace(/_/g, ' ')}`
            : `Purposeful Footpath Trip · ${pItem.state.replace(/_/g, ' ')}`,
          specs: isInhab
            ? [
                ['Resident', pItem.inhabitantName],
                ['Home', pItem.homeLabel || pItem.originName || 'Kilchberg'],
                ['Activity', pItem.activityLabel || 'Walking'],
                ['Destination', pItem.destName || 'Kilchberg'],
              ]
            : [
                ['Origin', pItem.originName || 'Kilchberg'],
                ['Destination', pItem.destName || 'Kilchberg'],
                ['Role', pItem.role.replace(/_/g, ' ')],
                ['Status', pItem.state.replace(/_/g, ' ')],
              ],
        });

        const bounds = pItem.bounds || { ex: 4.5 * wScale, eyUp: 9.5 * wScale, eyDn: 3.5 * wScale };
        drawables.push({
          layer: 'ground_y',
          sortY: pItem.pos.wy,
          depthMasked: true,
          wx: pItem.pos.wx,
          wy: pItem.pos.wy,
          bounds,
          d16: pItem.pos.d16,
          extraVertPx: 2.0,
          draw(targetCtx, drawCam) {
            drawPedestrianEntity(targetCtx, drawCam, pItem, wScale, mode, tSec);
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

    getSimStats() {
      return pedSim ? pedSim.getStats() : null;
    },

    destroy() {
      if (unsubInhabSpecs) {
        unsubInhabSpecs();
        unsubInhabSpecs = null;
      }
      pedSim = null;
      cachedInspectables = [];
    },
  };
}
