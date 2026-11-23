/**
 * Default Lake Zurich Vessel & Watercraft Specifications for Kilchberg (ZH).
 *
 * Aligns with `docs/data/kilchberg_animations.json` `ships[]` and local micro-craft
 * in `docs/js/living/plugins/vessels.js`.
 *
 * COLREGs / Swiss Binnenschifffahrtsverordnung priorityClass:
 *   1 = zsg_steamer (Kursschiff, highest right-of-way)
 *   2 = sailboat (under sail)
 *   3 = skiff / sup (muscle-powered; SUPs strictly slow ~1.6 m/s and 0 at night)
 *   4 = motorboat (yields to Kursschiff, sailboats, skiffs, SUPs)
 */

export const KILCHBERG_VESSELS = Object.freeze([
  Object.freeze({
    id: 'zsg_ms_helvetia',
    name: 'ZSG MS Helvetia · Lake Zurich Steamer',
    kind: 'zsg_steamer',
    animShipId: 'zsg_ms_helvetia',
    priorityClass: 1,
    hullLengthM: 50.0,
    hullBeamM: 12.0,
    maxSpeedMps: 6.8,
    closed: false,
    schedule: Object.freeze({
      mode: 'timetable',
      minutesPastHour: Object.freeze([15, 45]),
      firstHour: 9,
      lastHour: 20,
      stops: Object.freeze([
        Object.freeze({
          pierId: 'bendlikon',
          poiId: 'poi_bendlikon_pier',
          name: 'Kilchberg ZH (See) · Bendlikon Pier',
          frac: 0.5327,
          dwellSec: 5.5,
        }),
      ]),
    }),
    periodicFallback: Object.freeze({
      mode: 'periodic',
      phase: 0.22,
      speedMps: 6.8,
    }),
    diurnal: Object.freeze({ day: true, sunset: true, night: true }),
  }),

  Object.freeze({
    id: 'sailboat_1',
    name: 'Lake Zurich Sailboat · Bendlikon Tack',
    kind: 'sailboat',
    animShipId: 'sailboat_1',
    priorityClass: 2,
    hullLengthM: 9.5,
    hullBeamM: 3.1,
    maxSpeedMps: 3.1,
    closed: true,
    schedule: Object.freeze({ mode: 'loop', phase: 0.05 }),
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
  }),

  Object.freeze({
    id: 'sailboat_2',
    name: 'Lake Zurich Sailboat · North Reach',
    kind: 'sailboat',
    animShipId: 'sailboat_2',
    priorityClass: 2,
    hullLengthM: 9.2,
    hullBeamM: 3.0,
    maxSpeedMps: 2.8,
    closed: true,
    schedule: Object.freeze({ mode: 'loop', phase: 0.42 }),
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
  }),

  Object.freeze({
    id: 'sailboat_3',
    name: 'Lake Zurich Sailboat · Seebad Bay',
    kind: 'sailboat',
    animShipId: 'sailboat_3',
    priorityClass: 2,
    hullLengthM: 9.0,
    hullBeamM: 3.0,
    maxSpeedMps: 2.9,
    closed: true,
    schedule: Object.freeze({ mode: 'loop', phase: 0.71 }),
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
  }),

  Object.freeze({
    id: 'boesch_runabout',
    name: 'Boesch Mahogany Runabout · Kilchberg Yard',
    kind: 'motorboat',
    animShipId: 'boesch_runabout',
    priorityClass: 4,
    hullLengthM: 7.2,
    hullBeamM: 2.4,
    maxSpeedMps: 7.4,
    closed: true,
    schedule: Object.freeze({ mode: 'loop', phase: 0.33 }),
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
  }),

  Object.freeze({
    id: 'skiff:sulzergut',
    name: 'Wooden Rowing Skiff · Lake Zurich',
    kind: 'skiff',
    animShipId: null,
    priorityClass: 3,
    hullLengthM: 5.8,
    hullBeamM: 1.0,
    maxSpeedMps: 1.8,
    closed: false,
    schedule: Object.freeze({
      mode: 'patrol',
      u0: 0.618,
      v0: 0.566,
      u1: 0.678,
      v1: 0.522,
      spd: 0.0026,
      ph: 0.31,
    }),
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
  }),

  Object.freeze({
    id: 'sup:bendlikon',
    name: 'SUP Paddler · Bendlikon Bay',
    kind: 'sup',
    animShipId: null,
    priorityClass: 3,
    hullLengthM: 3.4,
    hullBeamM: 0.85,
    maxSpeedMps: 1.6,
    closed: false,
    schedule: Object.freeze({
      mode: 'patrol',
      u0: 0.566,
      v0: 0.610,
      u1: 0.629,
      v1: 0.566,
      spd: 0.0024,
      ph: 0.15,
    }),
    appearance: Object.freeze({ board: '#38bdf8', shirt: '#f43f5e', hair: '#2d241c' }),
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
  }),

  Object.freeze({
    id: 'sup:seebad',
    name: 'SUP Paddler · Seebad Shallows',
    kind: 'sup',
    animShipId: null,
    priorityClass: 3,
    hullLengthM: 3.4,
    hullBeamM: 0.85,
    maxSpeedMps: 1.6,
    closed: false,
    schedule: Object.freeze({
      mode: 'patrol',
      u0: 0.446,
      v0: 0.730,
      u1: 0.506,
      v1: 0.675,
      spd: 0.0021,
      ph: 0.62,
    }),
    appearance: Object.freeze({ board: '#fbbf24', shirt: '#0d9488', hair: '#5c4028' }),
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
  }),
]);
