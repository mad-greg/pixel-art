/**
 * Real-Time Europe/Zurich KilchbergClock & Continuous Diurnal Curves (v14).
 *
 * Supports three clock modes:
 *   1. 'live': real Europe/Zurich CET/CEST time via Intl.DateTimeFormat,
 *      astronomical solar elevation for Kilchberg (47.324°N, 8.549°E),
 *      automatic day/sunset/night preset selection, and continuous diurnal activity.
 *   2. 'manual': user-scrubbed minutes-of-day (0..1440) with optional speed multiplier.
 *   3. 'deterministic': zero wall-clock dependency (`?t=<sec>`), anchored to canonical
 *      preset times (day 14:22, sunset 19:42, night 22:15) + `tSec`.
 */

export const KILCHBERG_LAT_DEG = 47.324;
export const KILCHBERG_LON_DEG = 8.549;

const MAX_DATE_MS = 8.64e15;

const PRESET_ANCHOR_SEC = Object.freeze({
  day: 14 * 3600 + 22 * 60,
  sunset: 19 * 3600 + 42 * 60,
  night: 22 * 3600 + 15 * 60,
});

const WEEKDAY_MAP = Object.freeze({
  Sun: 0,
  Mon: 1,
  Tue: 2,
  Wed: 3,
  Thu: 4,
  Fri: 5,
  Sat: 6,
});

const MONTH_CUM_DAYS = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];

const ZURICH_FMT = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Europe/Zurich',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
  timeZoneName: 'short',
});

function safeMod(val, mod) {
  if (typeof val !== 'number' || !Number.isFinite(val)) return 0;
  const r = val % mod;
  const wrapped = r < 0 ? r + mod : r;
  // Guard against floating-point edge where wrapped === mod
  return wrapped >= mod ? 0 : wrapped;
}

function clamp(val, lo, hi) {
  return val < lo ? lo : (val > hi ? hi : val);
}

function pad2(n) {
  return n < 10 ? `0${n}` : `${n}`;
}

function isLeapYear(y) {
  return (y % 4 === 0 && y % 100 !== 0) || (y % 400 === 0);
}

function wrapHourDist(h, center) {
  const d = Math.abs(h - center);
  return d <= 12 ? d : 24 - d;
}

function gauss(h, center, sigma) {
  const d = wrapHourDist(h, center);
  return Math.exp(-(d * d) / (2 * sigma * sigma));
}

function smoothstep(edge0, edge1, x) {
  const t = clamp((x - edge0) / (edge1 - edge0), 0, 1);
  return t * t * (3 - 2 * t);
}

/**
 * Extract genuine DST-aware Europe/Zurich time components from a UTC epoch timestamp.
 */
export function getZurichTimeParts(nowMs = Date.now()) {
  const safeMs = (typeof nowMs === 'number' && Number.isFinite(nowMs) && Math.abs(nowMs) <= MAX_DATE_MS)
    ? nowMs
    : Date.now();
  let date = new Date(safeMs);
  if (Number.isNaN(date.getTime())) {
    date = new Date(Date.now());
  }
  const parts = ZURICH_FMT.formatToParts(date);

  let year = 2026;
  let month = 6;
  let day = 21;
  let dayOfWeek = 3;
  let hours = 14;
  let minutes = 22;
  let seconds = 0;
  let tzRaw = 'CET';

  for (let i = 0; i < parts.length; i++) {
    const p = parts[i];
    if (p.type === 'year') year = parseInt(p.value, 10) || year;
    else if (p.type === 'month') month = parseInt(p.value, 10) || month;
    else if (p.type === 'day') day = parseInt(p.value, 10) || day;
    else if (p.type === 'weekday') dayOfWeek = WEEKDAY_MAP[p.value] ?? dayOfWeek;
    else if (p.type === 'hour') hours = parseInt(p.value, 10) % 24;
    else if (p.type === 'minute') minutes = parseInt(p.value, 10) % 60;
    else if (p.type === 'second') seconds = parseInt(p.value, 10) % 60;
    else if (p.type === 'timeZoneName') tzRaw = p.value;
  }

  const leapBonus = (month > 2 && isLeapYear(year)) ? 1 : 0;
  const dayOfYear = (MONTH_CUM_DAYS[clamp(month, 1, 12)] || 0) + day + leapBonus;

  // Determine CET (UTC+1) vs CEST (UTC+2) robustly across ICU/Node locales
  let tzLabel = 'CET';
  if (tzRaw === 'CEST' || tzRaw.includes('+2') || tzRaw.includes('GMT+2')) {
    tzLabel = 'CEST';
  } else if (tzRaw === 'CET' || tzRaw.includes('+1') || tzRaw.includes('GMT+1')) {
    tzLabel = 'CET';
  } else {
    const utcH = date.getUTCHours();
    const diff = ((hours - utcH) % 24 + 24) % 24;
    tzLabel = diff === 2 ? 'CEST' : 'CET';
  }

  const utcHours = date.getUTCHours()
    + date.getUTCMinutes() / 60
    + date.getUTCSeconds() / 3600
    + date.getUTCMilliseconds() / 3600000;

  const zurichSecOfDay = hours * 3600 + minutes * 60 + seconds + (date.getUTCMilliseconds() / 1000);

  return {
    year,
    month,
    day,
    dayOfYear,
    dayOfWeek,
    hours,
    minutes,
    seconds,
    zurichSecOfDay: safeMod(zurichSecOfDay, 86400),
    tzLabel,
    utcHours,
  };
}

/**
 * Compute astronomical solar elevation angle (degrees) using NOAA/Spencer equations.
 * Defaults to Kilchberg, ZH (47.324°N, 8.549°E).
 */
export function computeSolarElevationDeg(
  dayOfYear,
  utcHours,
  latDeg = KILCHBERG_LAT_DEG,
  lonDeg = KILCHBERG_LON_DEG,
) {
  const doy = (typeof dayOfYear === 'number' && Number.isFinite(dayOfYear)) ? clamp(dayOfYear, 1, 366) : 172;
  const utcH = safeMod(utcHours, 24);
  const safeLat = (typeof latDeg === 'number' && Number.isFinite(latDeg)) ? clamp(latDeg, -90, 90) : KILCHBERG_LAT_DEG;
  const safeLon = (typeof lonDeg === 'number' && Number.isFinite(lonDeg)) ? clamp(lonDeg, -180, 180) : KILCHBERG_LON_DEG;
  const latRad = (safeLat * Math.PI) / 180;

  const gamma = ((2 * Math.PI) / 365) * (doy - 1 + (utcH - 12) / 24);
  const eqTime = 229.18 * (
    0.000075
    + 0.001868 * Math.cos(gamma)
    - 0.032077 * Math.sin(gamma)
    - 0.014615 * Math.cos(2 * gamma)
    - 0.040849 * Math.sin(2 * gamma)
  );
  const decl = 0.006918
    - 0.399912 * Math.cos(gamma)
    + 0.070257 * Math.sin(gamma)
    - 0.006758 * Math.cos(2 * gamma)
    + 0.000907 * Math.sin(2 * gamma)
    - 0.002697 * Math.cos(3 * gamma)
    + 0.001480 * Math.sin(3 * gamma);

  const trueSolarMin = safeMod(utcH * 60 + eqTime + 4 * safeLon, 1440);
  const hourAngleRad = ((trueSolarMin / 4 - 180) * Math.PI) / 180;

  const sinElev = Math.sin(latRad) * Math.sin(decl)
    + Math.cos(latRad) * Math.cos(decl) * Math.cos(hourAngleRad);
  return Math.asin(clamp(sinElev, -1, 1)) * (180 / Math.PI);
}

/**
 * Compute smooth, bounded continuous diurnal activity multipliers for Kilchberg.
 */
export function computeDiurnalActivity(zurichSecOfDay, dayOfWeek = 3) {
  const sec = safeMod(zurichSecOfDay, 86400);
  const h = sec / 3600;
  const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;

  // Commuter peaks around 07:30 and 17:45 (slightly gentler on weekends)
  const amRush = gauss(h, 7.5, 1.35);
  const pmRush = gauss(h, 17.75, 1.55);
  const middayBase = gauss(h, 12.75, 3.2) * 0.42;
  const rushWeight = isWeekend ? 0.55 : 1.0;
  const commuterFactor = clamp(0.12 + rushWeight * (1.22 * amRush + 1.18 * pmRush) + middayBase, 0.1, 1.4);

  // Road traffic: quiet overnight, strong morning/evening peaks, steady daytime
  const dayPlate = smoothstep(5.2, 8.0, h) * (1 - smoothstep(19.5, 23.0, h));
  const trafficRaw = 0.17 + 0.68 * dayPlate + 0.32 * rushWeight * Math.max(amRush, pmRush);
  const trafficFactor = clamp(trafficRaw, 0.15, 1.2);

  // Pedestrians: active morning through golden-hour promenade, quiet late night
  const pedDay = smoothstep(6.0, 9.0, h) * (1 - smoothstep(20.0, 23.2, h));
  const lunchStroll = gauss(h, 12.5, 1.6) * 0.24;
  const evePromenade = gauss(h, 18.2, 1.8) * 0.22;
  const pedestrianFactor = clamp(0.14 + 0.76 * pedDay + lunchStroll + evePromenade, 0.12, 1.2);

  // Leisure (Seebad, SUPs, lakeside sports): zero late night, peaks warm afternoon
  const leisureEnvelope = smoothstep(6.8, 9.5, h) * (1 - smoothstep(19.8, 21.8, h));
  const afternoonPeak = gauss(h, 15.2, 3.0) * 0.42;
  const weekendBoost = isWeekend ? 1.12 : 1.0;
  const leisureFactor = clamp((0.76 * leisureEnvelope + afternoonPeak * leisureEnvelope) * weekendBoost, 0.0, 1.2);

  // Night darkness factor: 0 in full day, smooth rise through dusk, 1 overnight
  const duskRise = smoothstep(18.5, 21.4, h);
  const dawnFall = 1 - smoothstep(5.0, 7.6, h);
  const nightFactor = clamp(Math.max(duskRise, dawnFall), 0.0, 1.0);

  return {
    commuterFactor: Math.round(commuterFactor * 1000) / 1000,
    trafficFactor: Math.round(trafficFactor * 1000) / 1000,
    pedestrianFactor: Math.round(pedestrianFactor * 1000) / 1000,
    leisureFactor: Math.round(leisureFactor * 1000) / 1000,
    nightFactor: Math.round(nightFactor * 1000) / 1000,
  };
}

function presetFromSolarElevation(elevDeg) {
  if (elevDeg > 6.0) return 'day';
  if (elevDeg >= -4.0) return 'sunset';
  return 'night';
}

function normalizePreset(p, fallback = 'day') {
  return (p === 'day' || p === 'sunset' || p === 'night') ? p : fallback;
}

export function createKilchbergClock(opts = {}) {
  const safeOpts = (opts && typeof opts === 'object') ? opts : {};
  let clockMode = (safeOpts.mode === 'live' || safeOpts.mode === 'manual' || safeOpts.mode === 'deterministic')
    ? safeOpts.mode
    : 'deterministic';
  let manualMinutes = (typeof safeOpts.manualMinutes === 'number' && Number.isFinite(safeOpts.manualMinutes))
    ? safeMod(safeOpts.manualMinutes, 1440)
    : (14 * 60 + 22);
  let manualAnchorTSec = null;
  let lastSampleTSec = null;
  let presetOverride = (safeOpts.presetOverride === 'day' || safeOpts.presetOverride === 'sunset' || safeOpts.presetOverride === 'night')
    ? safeOpts.presetOverride
    : 'auto';
  let detPreset = normalizePreset(safeOpts.preset, 'day');
  let detBaseTSec = (typeof safeOpts.tSec === 'number' && Number.isFinite(safeOpts.tSec)) ? safeOpts.tSec : 0;
  let speedMultiplier = (typeof safeOpts.speedMultiplier === 'number' && Number.isFinite(safeOpts.speedMultiplier) && safeOpts.speedMultiplier >= 0)
    ? safeOpts.speedMultiplier
    : 1;

  return {
    setMode(mode) {
      if (mode === 'live' || mode === 'manual' || mode === 'deterministic') {
        clockMode = mode;
        if (mode === 'manual') {
          manualAnchorTSec = null;
          lastSampleTSec = null;
        }
      }
      return clockMode;
    },

    setManualMinutes(minutesOfDay) {
      if (typeof minutesOfDay === 'number' && Number.isFinite(minutesOfDay)) {
        manualMinutes = safeMod(minutesOfDay, 1440);
        manualAnchorTSec = null;
        lastSampleTSec = null;
      }
      return manualMinutes;
    },

    setPresetOverride(preset) {
      if (preset === 'auto' || preset === 'day' || preset === 'sunset' || preset === 'night') {
        presetOverride = preset;
      }
      return presetOverride;
    },

    setDeterministic(tSec, preset = 'day') {
      clockMode = 'deterministic';
      detBaseTSec = (typeof tSec === 'number' && Number.isFinite(tSec)) ? tSec : 0;
      detPreset = normalizePreset(preset, 'day');
      return { clockMode, detBaseTSec, detPreset };
    },

    setSpeedMultiplier(mult) {
      if (typeof mult === 'number' && Number.isFinite(mult) && mult >= 0) {
        if (clockMode === 'manual' && manualAnchorTSec !== null && lastSampleTSec !== null) {
          const elapsedSec = (lastSampleTSec - manualAnchorTSec) * speedMultiplier;
          manualMinutes = safeMod(manualMinutes + elapsedSec / 60, 1440);
          manualAnchorTSec = lastSampleTSec;
        }
        speedMultiplier = mult;
      }
      return speedMultiplier;
    },

    sample(nowMs, tSec) {
      let zurichSecOfDay = 0;
      let dayOfWeek = 3;
      let tzLabel = 'CEST';
      let dayOfYear = 172;
      let utcHours = 12;
      let solarElevationDeg = 45;
      let autoPreset = 'day';
      let effectivePreset = 'day';

      if (clockMode === 'live') {
        const parts = getZurichTimeParts(nowMs);
        zurichSecOfDay = parts.zurichSecOfDay;
        dayOfWeek = parts.dayOfWeek;
        tzLabel = parts.tzLabel;
        dayOfYear = parts.dayOfYear;
        utcHours = parts.utcHours;
        solarElevationDeg = computeSolarElevationDeg(dayOfYear, utcHours, KILCHBERG_LAT_DEG, KILCHBERG_LON_DEG);
        autoPreset = presetFromSolarElevation(solarElevationDeg);
        effectivePreset = presetOverride !== 'auto' ? presetOverride : autoPreset;
      } else if (clockMode === 'manual') {
        const safeT = (typeof tSec === 'number' && Number.isFinite(tSec)) ? tSec : 0;
        if (manualAnchorTSec === null) {
          manualAnchorTSec = safeT;
        }
        lastSampleTSec = safeT;
        const elapsed = (safeT - manualAnchorTSec) * speedMultiplier;
        zurichSecOfDay = safeMod(manualMinutes * 60 + elapsed, 86400);
        dayOfWeek = 3;
        tzLabel = 'CEST';
        dayOfYear = 172;
        utcHours = safeMod(zurichSecOfDay / 3600 - 2, 24);
        solarElevationDeg = computeSolarElevationDeg(dayOfYear, utcHours, KILCHBERG_LAT_DEG, KILCHBERG_LON_DEG);
        autoPreset = presetFromSolarElevation(solarElevationDeg);
        effectivePreset = presetOverride !== 'auto' ? presetOverride : autoPreset;
      } else {
        // 'deterministic' mode: zero wall-clock dependency
        const anchorPreset = presetOverride !== 'auto' ? presetOverride : detPreset;
        const baseSec = PRESET_ANCHOR_SEC[anchorPreset] ?? PRESET_ANCHOR_SEC.day;
        const safeT = (typeof tSec === 'number' && Number.isFinite(tSec)) ? tSec : detBaseTSec;
        zurichSecOfDay = safeMod(baseSec + safeT * speedMultiplier, 86400);
        dayOfWeek = 3;
        tzLabel = 'CEST';
        dayOfYear = 172;
        utcHours = safeMod(zurichSecOfDay / 3600 - 2, 24);
        solarElevationDeg = computeSolarElevationDeg(dayOfYear, utcHours, KILCHBERG_LAT_DEG, KILCHBERG_LON_DEG);
        autoPreset = presetFromSolarElevation(solarElevationDeg);
        effectivePreset = anchorPreset;
      }

      const wholeSec = Math.floor(zurichSecOfDay);
      const hours = Math.floor(wholeSec / 3600) % 24;
      const minutes = Math.floor((wholeSec % 3600) / 60) % 60;
      const seconds = wholeSec % 60;
      const formattedHHMM = `${pad2(hours)}:${pad2(minutes)}`;
      const diurnalActivity = computeDiurnalActivity(zurichSecOfDay, dayOfWeek);

      return {
        clockMode,
        zurichSecOfDay,
        hours,
        minutes,
        seconds,
        tzLabel,
        formattedHHMM,
        dayOfWeek,
        solarElevationDeg: Math.round(solarElevationDeg * 100) / 100,
        autoPreset,
        effectivePreset,
        diurnalActivity,
      };
    },
  };
}
