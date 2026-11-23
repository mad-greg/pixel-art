/**
 * Modular 8-Layer Living Layer Engine for Kilchberg Pixel-Art Diorama v13.0.
 *
 * Orchestrates declarative LivingPlugin modules across an 8-layer painter's pipeline:
 *   water_fx -> water -> ground_y (unified Y-sort) -> pre_rail -> rail -> landmark -> air -> overlay
 *
 * Telemetry (`updateMs`, `drawMs`) uses performance.now() strictly for diagnostics
 * and NEVER feeds into simulation state or PRNG seeds.
 */

import { createLivingContext, updateContextFrame, updateContextTime } from './context.js';

export const LAYER_ORDER = Object.freeze([
  'water_fx',
  'water',
  'ground_y',
  'pre_rail',
  'rail',
  'landmark',
  'air',
  'overlay',
]);

const SORTED_LAYERS = new Set(['water', 'ground_y', 'rail']);

const STANDARD_LIVING_KEYS = [
  'ships',
  'cars',
  'buses',
  'cyclists',
  'roadPeds',
  'busStopCommuters',
  'trains',
  'gulls',
  'swans',
  'sups',
  'ducks',
  'redKites',
];

function nowMs() {
  return (typeof performance !== 'undefined' && typeof performance.now === 'function')
    ? performance.now()
    : 0;
}

export class LivingEngine {
  constructor() {
    this._plugins = [];
    this._pluginMap = new Map();
    this._enabledMap = new Map();
    this._regSeq = 0;
    this._initialized = false;
    this._ctx = createLivingContext();

    this._buckets = {};
    for (let i = 0; i < LAYER_ORDER.length; i++) {
      this._buckets[LAYER_ORDER[i]] = [];
    }

    this._inspectables = [];
    this._livingCounts = {};
    this._resetLivingCounts();
    this._perPluginCounts = {};
    this._drawablesCount = 0;
    this._updateMs = 0;
    this._drawMs = 0;
  }

  _resetLivingCounts() {
    for (const k of Object.keys(this._livingCounts)) {
      delete this._livingCounts[k];
    }
    for (let i = 0; i < STANDARD_LIVING_KEYS.length; i++) {
      this._livingCounts[STANDARD_LIVING_KEYS[i]] = 0;
    }
  }

  _sortPlugins() {
    this._plugins.sort((a, b) => {
      const pa = Number.isFinite(a.priority) ? a.priority : 50;
      const pb = Number.isFinite(b.priority) ? b.priority : 50;
      if (pa !== pb) return pa - pb;
      return (a._regOrder || 0) - (b._regOrder || 0);
    });
  }

  register(plugin) {
    if (!plugin || typeof plugin.id !== 'string' || !plugin.id.trim()) {
      throw new Error('LivingEngine.register: plugin must have a non-empty string id');
    }
    const id = plugin.id;
    if (this._pluginMap.has(id)) {
      this.unregister(id);
    }
    const entry = {
      ...plugin,
      priority: Number.isFinite(plugin.priority) ? plugin.priority : 50,
      layers: Array.isArray(plugin.layers) ? plugin.layers.slice() : [],
      _regOrder: this._regSeq++,
    };
    this._plugins.push(entry);
    this._pluginMap.set(id, entry);
    this._enabledMap.set(id, plugin.enabledByDefault !== false);
    this._sortPlugins();

    if (this._initialized && typeof entry.init === 'function') {
      entry.init(this._ctx);
    }
    return this;
  }

  unregister(id) {
    const existing = this._pluginMap.get(id);
    if (!existing) return false;
    if (typeof existing.destroy === 'function') {
      existing.destroy();
    }
    this._pluginMap.delete(id);
    this._enabledMap.delete(id);
    const idx = this._plugins.indexOf(existing);
    if (idx >= 0) this._plugins.splice(idx, 1);
    delete this._perPluginCounts[id];
    return true;
  }

  setEnabled(id, enabled) {
    if (!this._pluginMap.has(id)) return false;
    this._enabledMap.set(id, !!enabled);
    return true;
  }

  isEnabled(id) {
    return !!this._enabledMap.get(id);
  }

  listPlugins() {
    return this._plugins.map((p) => ({
      id: p.id,
      name: p.name || p.id,
      category: p.category || 'misc',
      layers: p.layers.slice(),
      priority: p.priority,
      enabled: !!this._enabledMap.get(p.id),
    }));
  }

  init(animData, meta, depthMgr) {
    this._ctx.animData = animData || null;
    this._ctx.meta = meta || null;
    this._ctx.depthMgr = depthMgr || null;
    if (animData) {
      this._ctx.worldW = animData.canvas_width || this._ctx.worldW;
      this._ctx.worldH = animData.canvas_height || this._ctx.worldH;
      this._ctx.mppMaster = typeof animData.mpp === 'number' ? animData.mpp : this._ctx.mppMaster;
      this._ctx.resFactor = 0.25 / this._ctx.mppMaster;
      this._ctx.wScale = this._ctx.resFactor;
    }
    this._initialized = true;
    for (let i = 0; i < this._plugins.length; i++) {
      const p = this._plugins[i];
      if (typeof p.init === 'function') {
        p.init(this._ctx);
      }
    }
  }

  update(tSec, dt, mode) {
    const t0 = nowMs();
    updateContextTime(this._ctx, tSec, dt, mode);

    // Deterministic cross-plugin ordering: pedestrians -> traffic -> remaining plugins
    const pedPlugin = this._pluginMap.get('pedestrians');
    const trafficPlugin = this._pluginMap.get('traffic');

    if (pedPlugin && this._enabledMap.get('pedestrians') && typeof pedPlugin.update === 'function') {
      pedPlugin.update(this._ctx.dt, this._ctx);
    }
    if (trafficPlugin && this._enabledMap.get('traffic') && typeof trafficPlugin.update === 'function') {
      trafficPlugin.update(this._ctx.dt, this._ctx);
    }
    for (let i = 0; i < this._plugins.length; i++) {
      const p = this._plugins[i];
      if (p.id === 'pedestrians' || p.id === 'traffic') continue;
      if (!this._enabledMap.get(p.id)) continue;
      if (typeof p.update === 'function') {
        p.update(this._ctx.dt, this._ctx);
      }
    }

    this._updateMs = nowMs() - t0;
  }

  draw(ctx, cam, worldW, worldH, tSec, mode, fixedAnimTime = null) {
    const t0 = nowMs();
    updateContextFrame(this._ctx, {
      cam,
      worldW,
      worldH,
      tSec,
      mode,
      fixedAnimTime,
    });

    const depthMgr = this._ctx.depthMgr;
    if (depthMgr && typeof depthMgr.resetDepthStats === 'function') {
      depthMgr.resetDepthStats();
    }

    for (let li = 0; li < LAYER_ORDER.length; li++) {
      this._buckets[LAYER_ORDER[li]].length = 0;
    }
    this._inspectables.length = 0;
    this._resetLivingCounts();
    this._perPluginCounts = {};

    let totalDrawables = 0;
    for (let i = 0; i < this._plugins.length; i++) {
      const p = this._plugins[i];
      if (!this._enabledMap.get(p.id)) continue;

      if (typeof p.getDrawables === 'function') {
        const list = p.getDrawables(cam, this._ctx);
        if (list && list.length > 0) {
          for (let j = 0; j < list.length; j++) {
            const d = list[j];
            if (!d || typeof d.draw !== 'function') continue;
            const bucket = this._buckets[d.layer];
            if (!bucket) continue;
            d._priority = p.priority;
            bucket.push(d);
            totalDrawables++;
          }
        }
      }

      if (typeof p.getInspectables === 'function') {
        const ins = p.getInspectables(this._ctx);
        if (ins && ins.length > 0) {
          for (let j = 0; j < ins.length; j++) {
            this._inspectables.push(ins[j]);
          }
        }
      }

      if (typeof p.getLivingCounts === 'function') {
        const counts = p.getLivingCounts(this._ctx);
        if (counts && typeof counts === 'object') {
          this._perPluginCounts[p.id] = { ...counts };
          for (const k of Object.keys(counts)) {
            const val = counts[k];
            if (typeof val === 'number' && Number.isFinite(val)) {
              this._livingCounts[k] = (this._livingCounts[k] || 0) + val;
            }
          }
        }
      }
    }

    const canDepthMask = !!(depthMgr && typeof depthMgr.drawDepthMasked === 'function');

    for (let li = 0; li < LAYER_ORDER.length; li++) {
      const layer = LAYER_ORDER[li];
      const bucket = this._buckets[layer];
      if (bucket.length === 0) continue;

      if (SORTED_LAYERS.has(layer) && bucket.length > 1) {
        if (layer === 'rail') {
          bucket.sort((a, b) => {
            const tr = (a.trackRank ?? 0) - (b.trackRank ?? 0);
            if (tr !== 0) return tr;
            const sy = (a.sortY || 0) - (b.sortY || 0);
            if (sy !== 0) return sy;
            return (a._priority || 0) - (b._priority || 0);
          });
        } else {
          bucket.sort((a, b) => {
            const sy = (a.sortY || 0) - (b.sortY || 0);
            if (sy !== 0) return sy;
            return (a._priority || 0) - (b._priority || 0);
          });
        }
      }

      if (layer === 'rail' && this._ctx && this._ctx.shared && this._ctx.shared.railTelemetry) {
        let violations = 0;
        let maxRankSeen = -Infinity;
        for (let j = 0; j < bucket.length; j++) {
          const r = bucket[j].trackRank ?? 0;
          if (r < maxRankSeen) violations++;
          if (r > maxRankSeen) maxRankSeen = r;
        }
        this._ctx.shared.railTelemetry.trackInterleaveViolations = violations;
      }

      for (let j = 0; j < bucket.length; j++) {
        const d = bucket[j];
        if (d.depthMasked && canDepthMask) {
          depthMgr.drawDepthMasked(
            ctx,
            cam,
            d.wx,
            d.wy,
            d.bounds,
            d.d16,
            worldW,
            worldH,
            (targetCtx) => d.draw(targetCtx, cam, this._ctx),
            d.extraVertPx != null ? d.extraVertPx : 4.0,
          );
        } else {
          d.draw(ctx, cam, this._ctx);
        }
      }
    }

    this._drawablesCount = totalDrawables;
    this._drawMs = nowMs() - t0;
  }

  hitTest(clientX, clientY, viewportRect, cam, wasFollowing) {
    if (!cam || !viewportRect || this._inspectables.length === 0) return null;
    const dpr = Math.max(1, cam.dpr || 1);
    const effCssScale = (cam.scale * this._ctx.wScale) / dpr;
    if (!wasFollowing && effCssScale < 0.85) return null;

    const clickX = clientX - viewportRect.left;
    const clickY = clientY - viewportRect.top;
    let best = null;
    let bestDist = Infinity;

    for (let i = 0; i < this._inspectables.length; i++) {
      const ent = this._inspectables[i];
      const sx = (cam.offsetX + ent.wx * cam.scale) / dpr;
      const sy = (cam.offsetY + ent.wy * cam.scale) / dpr;
      const dist = Math.hypot(sx - clickX, sy - clickY);
      const isFollowedKind = wasFollowing && ent.kind === wasFollowing;
      const maxR = isFollowedKind ? Math.max(ent.radiusCss || 12, 32) : (ent.radiusCss || 12);
      if (dist <= maxR && dist < bestDist) {
        bestDist = dist;
        best = ent;
      }
    }
    return best;
  }

  getFollowTarget(kind, worldW, worldH) {
    if (!kind) return null;
    if (worldW > 0) this._ctx.worldW = worldW;
    if (worldH > 0) this._ctx.worldH = worldH;
    for (let i = 0; i < this._plugins.length; i++) {
      const p = this._plugins[i];
      if (!this._enabledMap.get(p.id)) continue;
      if (typeof p.getFollowTarget === 'function') {
        const pos = p.getFollowTarget(kind, this._ctx);
        if (pos && Number.isFinite(pos.wx) && Number.isFinite(pos.wy)) {
          return pos;
        }
      }
    }
    return null;
  }

  getAudioSignals(worldW, worldH, tSec, mode) {
    if (worldW > 0) this._ctx.worldW = worldW;
    if (worldH > 0) this._ctx.worldH = worldH;
    updateContextTime(this._ctx, tSec, this._ctx.dt, mode);

    const out = [];
    for (let i = 0; i < this._plugins.length; i++) {
      const p = this._plugins[i];
      if (!this._enabledMap.get(p.id)) continue;
      if (typeof p.getAudioSignals === 'function') {
        const sigs = p.getAudioSignals(this._ctx);
        if (sigs && sigs.length > 0) {
          for (let j = 0; j < sigs.length; j++) {
            out.push(sigs[j]);
          }
        }
      }
    }
    return out;
  }

  getSimStats() {
    const trafficPlugin = this._pluginMap.get('traffic');
    const pedPlugin = this._pluginMap.get('pedestrians');
    const tStats = (trafficPlugin && typeof trafficPlugin.getSimStats === 'function')
      ? trafficPlugin.getSimStats()
      : (this._ctx.shared.trafficSim ? this._ctx.shared.trafficSim.getStats() : null);
    const pStats = (pedPlugin && typeof pedPlugin.getSimStats === 'function')
      ? pedPlugin.getSimStats()
      : (this._ctx.shared.pedSim ? this._ctx.shared.pedSim.getStats() : null);

    const base = {
      vehicles: 0,
      brakingCount: 0,
      yieldingCount: 0,
      pedestrians: 0,
      boardingCount: 0,
      activeTrips: 0,
      bellPhase: this._ctx.bell ? this._ctx.bell.bellPhase : 0,
      minBusGapM: Infinity,
      clippingCount: 0,
      overlapCount: 0,
      cyclists: 0,
    };
    if (tStats) Object.assign(base, tStats);
    if (pStats) {
      base.pedestrians = pStats.pedestrians;
      base.boardingCount = pStats.boardingCount;
      base.activeTrips = pStats.activeTrips;
    }
    base.bellPhase = this._ctx.bell ? this._ctx.bell.bellPhase : 0;
    return base;
  }

  getLivingCounts() {
    return { ...this._livingCounts };
  }

  getEngineStats() {
    const pluginIds = [];
    const enabledPlugins = [];
    for (let i = 0; i < this._plugins.length; i++) {
      const id = this._plugins[i].id;
      pluginIds.push(id);
      if (this._enabledMap.get(id)) enabledPlugins.push(id);
    }
    return {
      pluginCount: this._plugins.length,
      enabledCount: enabledPlugins.length,
      pluginIds,
      enabledPlugins,
      drawablesCount: this._drawablesCount,
      inspectablesCount: this._inspectables.length,
      updateMs: Math.round(this._updateMs * 1000) / 1000,
      drawMs: Math.round(this._drawMs * 1000) / 1000,
      perPluginCounts: { ...this._perPluginCounts },
    };
  }
}

export function createLivingEngine() {
  return new LivingEngine();
}
