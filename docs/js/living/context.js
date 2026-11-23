/**
 * Zero-allocation reusable per-frame LivingContext builder for Kilchberg v13.0.
 * Shared across all LivingEngine plugins during init, update, draw, and audio ticks.
 */

import { hashString, mulberry32 } from '../sim/rng.js';
import { evalBellState, getWindVector } from '../sim/schedule.js';
import { createSpatialGrid } from '../sim/spatial.js';
import { createDefaultKilchbergRegistry } from '../specs/registry.js';
import { getLivingDiurnalProfile } from './diurnal.js';

const DEFAULT_CAM = {
  scale: 1,
  offsetX: 0,
  offsetY: 0,
  width: 1280,
  height: 800,
  dpr: 1,
};

export function createLivingContext(opts = {}) {
  const safeOpts = (opts && typeof opts === 'object') ? opts : {};
  const ctx = {
    animData: null,
    meta: null,
    depthMgr: null,
    worldW: 27971,
    worldH: 12294,
    mppMaster: 0.11,
    wScale: 0.25 / 0.11,
    resFactor: 0.25 / 0.11,
    tSec: 0,
    dt: 0.016,
    mode: 'day',
    isNight: false,
    isSunset: false,
    fixedAnimTime: null,
    clock: safeOpts.clock || null,
    _clockSource: safeOpts.clockSource || null,
    specs: safeOpts.specs || createDefaultKilchbergRegistry(),
    diurnal: getLivingDiurnalProfile('day'),
    wind: getWindVector(0),
    bell: evalBellState(0, 'day'),
    cam: DEFAULT_CAM,
    s: 1,
    effCssScale: 1,
    detailAlpha: 0,
    plaqueAlpha: 0,
    visU0: 0,
    visU1: 1,
    visV0: 0,
    visV1: 1,
    shared: {
      trafficSim: null,
      pedSim: null,
      lastSimSnapshot: null,
      dwellingStops: null,
      occupiedCrosswalks: null,
      pedStats: null,
      spatialGrid: safeOpts.spatialGrid || createSpatialGrid(16),
      vesselSim: null,
      sportsSim: null,
      railTelemetry: {
        activeTrains: 0,
        passingNow: false,
        trackInterleaveViolations: 0,
      },
    },
    toX(u) {
      return u * ctx.worldW * ctx.cam.scale + ctx.cam.offsetX;
    },
    toY(v) {
      return v * ctx.worldH * ctx.cam.scale + ctx.cam.offsetY;
    },
    inView(sx, sy, padWorld = 48) {
      const pad = Math.max(36, padWorld * ctx.s);
      return sx >= -pad && sx <= ctx.cam.width + pad && sy >= -pad && sy <= ctx.cam.height + pad;
    },
    boxInView(u0, v0, u1, v1) {
      return u1 >= ctx.visU0 && u0 <= ctx.visU1 && v1 >= ctx.visV0 && v0 <= ctx.visV1;
    },
    rngFor(pluginId, salt = 0) {
      return mulberry32(hashString(`${pluginId}:${ctx.mode}:${salt}`));
    },
  };
  return ctx;
}

export function updateContextTime(ctx, tSec, dt, mode, clockSnapshot = undefined) {
  const safeT = Number.isFinite(tSec) ? tSec : 0;
  const safeDt = Number.isFinite(dt) ? dt : 0.016;
  const normMode = (mode === 'night' || mode === 'sunset') ? mode : 'day';
  ctx.tSec = safeT;
  ctx.dt = safeDt;
  ctx.mode = normMode;
  ctx.isNight = normMode === 'night';
  ctx.isSunset = normMode === 'sunset';
  if (clockSnapshot !== undefined) {
    ctx.clock = clockSnapshot;
  } else if (ctx._clockSource && typeof ctx._clockSource.sample === 'function') {
    ctx.clock = ctx._clockSource.sample(Date.now(), safeT);
  }
  ctx.diurnal = getLivingDiurnalProfile(normMode);
  ctx.wind = getWindVector(safeT);
  ctx.bell = evalBellState(safeT, normMode);
}

export function updateContextFrame(ctx, params) {
  const {
    animData = ctx.animData,
    meta = ctx.meta,
    depthMgr = ctx.depthMgr,
    cam = ctx.cam || DEFAULT_CAM,
    worldW = ctx.worldW,
    worldH = ctx.worldH,
    tSec = ctx.tSec,
    dt = ctx.dt,
    mode = ctx.mode,
    fixedAnimTime = ctx.fixedAnimTime,
    clock = undefined,
    specs = undefined,
  } = params;

  ctx.animData = animData;
  ctx.meta = meta;
  ctx.depthMgr = depthMgr;
  if (specs !== undefined) {
    ctx.specs = specs;
  }
  ctx.worldW = worldW > 0 ? worldW : 27971;
  ctx.worldH = worldH > 0 ? worldH : 12294;
  ctx.mppMaster = (animData && typeof animData.mpp === 'number' && animData.mpp > 0) ? animData.mpp : 0.11;
  const masterW = (animData && animData.canvas_width) ? animData.canvas_width : 27971;
  ctx.resFactor = 0.25 / ctx.mppMaster;
  ctx.wScale = (ctx.worldW / Math.max(1, masterW)) * ctx.resFactor;
  ctx.fixedAnimTime = fixedAnimTime;

  updateContextTime(ctx, tSec, dt, mode, clock);

  const safeCam = cam || DEFAULT_CAM;
  ctx.cam = safeCam;
  const scale = safeCam.scale || 1;
  const dpr = Math.max(1, safeCam.dpr || 1);
  ctx.s = scale * ctx.wScale;
  ctx.effCssScale = ctx.s / dpr;
  ctx.detailAlpha = Math.max(0, Math.min(1, (ctx.effCssScale - 1.1) / 0.3));
  ctx.plaqueAlpha = Math.max(0, Math.min(1, (ctx.effCssScale - 1.3) / 0.4));

  const invW = 1 / Math.max(1, ctx.worldW * scale);
  const invH = 1 / Math.max(1, ctx.worldH * scale);
  const padU = Math.max(0.004, 48 * invW);
  const padV = Math.max(0.008, 48 * invH);
  ctx.visU0 = (-safeCam.offsetX * invW) - padU;
  ctx.visU1 = ((safeCam.width - safeCam.offsetX) * invW) + padU;
  ctx.visV0 = (-safeCam.offsetY * invH) - padV;
  ctx.visV1 = ((safeCam.height - safeCam.offsetY) * invH) + padV;

  return ctx;
}

export { updateContextFrame as updateLivingContext };

