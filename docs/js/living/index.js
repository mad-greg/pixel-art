// Kilchberg v14 Living Layer Runtime Facade & Barrel Exports
// Wires LivingEngine + default plugins + KilchbergClock + SpecRegistry + SpatialGrid2D.

import { createLivingEngine, LAYER_ORDER } from './engine.js';
import { registerDefaultPlugins } from './plugins/index.js';
import { createKilchbergClock } from './clock.js';
import { createSpecRegistry, createDefaultKilchbergRegistry } from '../specs/registry.js';
import { createSpatialGrid } from '../sim/spatial.js';

export {
  createLivingEngine,
  LAYER_ORDER,
  registerDefaultPlugins,
  createKilchbergClock,
  createSpecRegistry,
  createDefaultKilchbergRegistry,
  createSpatialGrid,
};

const DEFAULT_RAIL_TELEMETRY = Object.freeze({
  activeTrains: 0,
  passingNow: false,
  trackInterleaveViolations: 0,
});

const DEFAULT_SPORTS_TELEMETRY = Object.freeze({
  tennisCourts: 0,
  soccerPitches: 0,
  maxSoccerPlayerMps: 0,
  minTennisShotSec: 0,
  maxTennisShotSec: 0,
  tennisBouncesObserved: 0,
  ballModes: [],
});

const DEFAULT_VESSEL_TELEMETRY = Object.freeze({
  activeVessels: 0,
  minPairwiseClearanceM: 0,
  collisionCount: 0,
  maxSupSpeedMps: 0,
});

/**
 * Bootstrap a fully wired Kilchberg v14 living runtime.
 * @param {object} [opts]
 * @param {object} [opts.specs]       Optional pre-built SpecRegistry
 * @param {object} [opts.clock]       Optional pre-built KilchbergClock
 * @param {object} [opts.clockOpts]   Options passed to createKilchbergClock()
 * @param {object} [opts.spatialGrid] Optional pre-built SpatialGrid2D
 * @param {number} [opts.initialTSec] Initial simulation time in seconds (default 0)
 */
export function createKilchbergLivingRuntime(opts = {}) {
  const safeOpts = (opts && typeof opts === 'object') ? opts : {};
  const engine = registerDefaultPlugins(createLivingEngine());
  const specs = safeOpts.specs || createDefaultKilchbergRegistry();
  const clock = safeOpts.clock || createKilchbergClock(safeOpts.clockOpts || {});
  const spatialGrid = safeOpts.spatialGrid || createSpatialGrid(16);
  const initialTSec = Number.isFinite(safeOpts.initialTSec) ? safeOpts.initialTSec : 0;

  if (engine && engine._ctx) {
    engine._ctx.specs = specs;
    engine._ctx._clockSource = clock;
    if (!engine._ctx.shared || typeof engine._ctx.shared !== 'object') {
      engine._ctx.shared = {};
    }
    engine._ctx.shared.spatialGrid = spatialGrid;
    engine._ctx.clock = clock.sample(Date.now(), initialTSec);
  }

  function getClockSnapshot(tSec = 0) {
    const safeT = Number.isFinite(tSec) ? tSec : 0;
    if (engine && engine._ctx && engine._ctx.clock) {
      return engine._ctx.clock;
    }
    return clock.sample(Date.now(), safeT);
  }

  function getSpecs() {
    return specs;
  }

  function getRailTelemetry() {
    const rt = engine && engine._ctx && engine._ctx.shared && engine._ctx.shared.railTelemetry;
    if (rt && typeof rt === 'object') {
      return {
        activeTrains: Number(rt.activeTrains) || 0,
        passingNow: Boolean(rt.passingNow),
        trackInterleaveViolations: Number(rt.trackInterleaveViolations) || 0,
      };
    }
    return { ...DEFAULT_RAIL_TELEMETRY };
  }

  function getSportsTelemetry() {
    const sSim = engine && engine._ctx && engine._ctx.shared && engine._ctx.shared.sportsSim;
    if (sSim && typeof sSim.getTelemetry === 'function') {
      const raw = sSim.getTelemetry();
      const rawModes = raw && raw.ballModes;
      const ballModes = Array.isArray(rawModes)
        ? rawModes.slice()
        : (rawModes && typeof rawModes === 'object' ? Object.values(rawModes) : []);
      return {
        ...DEFAULT_SPORTS_TELEMETRY,
        ...raw,
        ballModes,
      };
    }
    return { ...DEFAULT_SPORTS_TELEMETRY, ballModes: [] };
  }

  function getVesselTelemetry() {
    const vSim = engine && engine._ctx && engine._ctx.shared && engine._ctx.shared.vesselSim;
    if (vSim && typeof vSim.getTelemetry === 'function') {
      return vSim.getTelemetry();
    }
    return { ...DEFAULT_VESSEL_TELEMETRY };
  }

  /**
   * Deterministically warm up coupled simulations (pedestrians <-> traffic) in 0.5 s steps
   * up to targetTSec so crosswalk yielding and vehicle/pedestrian avoidance co-evolve cleanly.
   */
  function warmupToTime(targetTSec, mode) {
    const safeTarget = Number.isFinite(targetTSec) ? Math.max(0, targetTSec) : 0;
    const stepSec = 0.5;
    if (safeTarget > stepSec) {
      const startSec = safeTarget > 120 ? (safeTarget - 30) : stepSec;
      for (let t = startSec; t < safeTarget - 1e-6; t += stepSec) {
        engine.update(t, stepSec, mode);
      }
    }
    engine.update(safeTarget, 0.016, mode);
  }

  return {
    engine,
    clock,
    specs,
    spatialGrid,
    warmupToTime,
    getClockSnapshot,
    getSpecs,
    getRailTelemetry,
    getSportsTelemetry,
    getVesselTelemetry,
  };
}
