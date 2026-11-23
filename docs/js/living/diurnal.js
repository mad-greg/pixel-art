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

export function getLivingDiurnalProfile(mode = 'day') {
  if (mode === 'night') return DIURNAL_CACHE.night;
  if (mode === 'sunset') return DIURNAL_CACHE.sunset;
  return DIURNAL_CACHE.day;
}

export { getDiurnalProfile };
