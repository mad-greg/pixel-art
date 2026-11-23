/**
 * Diurnal visual lighting & living-world activity profiles for Kilchberg v13.0.
 * Wraps schedule.js getDiurnalProfile(mode) with zero-allocation cached lighting
 * and ecological activity multipliers for day, sunset (alpenglow), and night.
 */

import { getDiurnalProfile } from '../sim/schedule.js';

const DIURNAL_CACHE = {
  day: Object.freeze({
    ...getDiurnalProfile('day'),
    isDay: true,
    isSunset: false,
    isNight: false,
    glowAlpha: 0.14,
    shadowAlpha: 0.42,
    waterGlintAlpha: 0.64,
    causticAlpha: 0.38,
    warmTint: 0.0,
    ambientDim: 1.0,
    headlightAlpha: 0.0,
    windowAlpha: 0.0,
    wildlifeActivity: 1.0,
    swimmerActivity: 1.0,
  }),
  sunset: Object.freeze({
    ...getDiurnalProfile('sunset'),
    isDay: false,
    isSunset: true,
    isNight: false,
    glowAlpha: 0.55,
    shadowAlpha: 0.48,
    waterGlintAlpha: 0.74,
    causticAlpha: 0.26,
    warmTint: 0.42,
    ambientDim: 0.86,
    headlightAlpha: 0.14,
    windowAlpha: 0.48,
    wildlifeActivity: 0.78,
    swimmerActivity: 0.45,
  }),
  night: Object.freeze({
    ...getDiurnalProfile('night'),
    isDay: false,
    isSunset: false,
    isNight: true,
    glowAlpha: 0.95,
    shadowAlpha: 0.62,
    waterGlintAlpha: 0.44,
    causticAlpha: 0.0,
    warmTint: 0.18,
    ambientDim: 0.58,
    headlightAlpha: 0.28,
    windowAlpha: 0.88,
    wildlifeActivity: 0.15,
    swimmerActivity: 0.0,
  }),
};

export function getLivingDiurnalProfile(mode = 'day', clockSnapshot = null) {
  if (clockSnapshot && typeof clockSnapshot === 'object' && clockSnapshot.diurnalActivity) {
    return getContinuousDiurnal(clockSnapshot, mode);
  }
  if (mode === 'night') return DIURNAL_CACHE.night;
  if (mode === 'sunset') return DIURNAL_CACHE.sunset;
  return DIURNAL_CACHE.day;
}

/**
 * Continuous diurnal profile modulated by KilchbergClock's smooth time-of-day curves.
 * Falls back cleanly to the discrete cached preset when `clockSnapshot` is absent.
 */
export function getContinuousDiurnal(clockSnapshot, fallbackMode = 'day') {
  if (!clockSnapshot || typeof clockSnapshot !== 'object' || !clockSnapshot.diurnalActivity) {
    return getLivingDiurnalProfile(fallbackMode);
  }
  const preset = clockSnapshot.effectivePreset || fallbackMode || 'day';
  const base = preset === 'night'
    ? DIURNAL_CACHE.night
    : (preset === 'sunset' ? DIURNAL_CACHE.sunset : DIURNAL_CACHE.day);
  const act = clockSnapshot.diurnalActivity;

  const trafficMul = Number.isFinite(act.trafficFactor) ? act.trafficFactor : base.carFactor;
  const pedMul = Number.isFinite(act.pedestrianFactor) ? act.pedestrianFactor : base.pedFactor;
  const leisureMul = Number.isFinite(act.leisureFactor) ? act.leisureFactor : base.swimmerActivity;
  const nightF = Number.isFinite(act.nightFactor) ? act.nightFactor : (base.isNight ? 1 : 0);

  return {
    ...base,
    continuous: true,
    diurnalActivity: act,
    carFactor: Math.max(0.15, Math.min(1.2, trafficMul)),
    pedFactor: Math.max(0.12, Math.min(1.2, pedMul)),
    cyclistFactor: Math.max(0.1, Math.min(1.2, 0.55 * pedMul + 0.45 * leisureMul)),
    crosswalkRate: Math.max(0.15, Math.min(1.2, pedMul)),
    wildlifeActivity: Math.max(0.12, Math.min(1.1, 1.0 - 0.85 * nightF)),
    swimmerActivity: Math.max(0.0, Math.min(1.2, leisureMul)),
    glowAlpha: Math.max(0.14, Math.min(0.95, 0.14 + 0.81 * nightF)),
    headlightAlpha: Math.max(0.0, Math.min(0.28, 0.28 * nightF)),
    windowAlpha: Math.max(0.0, Math.min(0.88, 0.88 * nightF)),
  };
}

export { getDiurnalProfile };

