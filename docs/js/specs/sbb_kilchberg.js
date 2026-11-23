/**
 * Default SBB Rail Service Specifications for Kilchberg (ZH) — Linksufrige Zürichseebahn.
 *
 * Track geometry aligns with `docs/data/kilchberg_animations.json` `trains[]`:
 *   - Gleis 2 (NW / landward / back track, trackRank: 0): `animTrackId: 'sbb_s8_south'` (NE -> SW)
 *   - Gleis 1 (SE / lakeward / front track, trackRank: 1): `animTrackId: 'sbb_ic_north'` (SW -> NE)
 *
 * Each service includes both real-style Europe/Zurich clock-minute timetables
 * (`timetable`) and deterministic periodic parameters (`periodicFallback`) for `?t=` mode.
 */

export const SBB_KILCHBERG_SERVICES = Object.freeze([
  Object.freeze({
    id: 'sbb_s8_south',
    line: 'S8',
    operator: 'SBB',
    name: 'SBB S8 · Pfäffikon SZ',
    direction: 'southbound',
    origin: 'Winterthur · Zürich HB',
    destination: 'Pfäffikon SZ',
    trackId: 'gleis_2_nw',
    trackRank: 0,
    animTrackId: 'sbb_s8_south',
    rollingStock: 'dpz',
    carriages: 4,
    stops: Object.freeze([
      Object.freeze({
        stationId: 'bahnhof_kilchberg',
        poiId: 'poi_bahnhof',
        name: 'Bahnhof Kilchberg · Gleis 2',
        frac: 0.5475,
        dwellSec: 4.5,
      }),
    ]),
    timetable: Object.freeze({
      mode: 'clock_minutes',
      minutesPastHour: Object.freeze([12, 42]),
      firstHour: 5,
      lastHour: 24,
    }),
    periodicFallback: Object.freeze({
      mode: 'periodic',
      periodSec: 138,
      phase: 0.12,
      speedMps: 18.5,
    }),
  }),

  Object.freeze({
    id: 'sbb_s8_north',
    line: 'S8',
    operator: 'SBB',
    name: 'SBB S8 · Zürich HB / Winterthur',
    direction: 'northbound',
    origin: 'Pfäffikon SZ',
    destination: 'Zürich HB · Winterthur',
    trackId: 'gleis_1_se',
    trackRank: 1,
    animTrackId: 'sbb_ic_north',
    rollingStock: 'dpz',
    carriages: 4,
    stops: Object.freeze([
      Object.freeze({
        stationId: 'bahnhof_kilchberg',
        poiId: 'poi_bahnhof',
        name: 'Bahnhof Kilchberg · Gleis 1',
        frac: 0.4520,
        dwellSec: 4.0,
      }),
    ]),
    timetable: Object.freeze({
      mode: 'clock_minutes',
      minutesPastHour: Object.freeze([17, 47]),
      firstHour: 5,
      lastHour: 24,
    }),
    periodicFallback: Object.freeze({
      mode: 'periodic',
      periodSec: 146,
      phase: 0.36,
      speedMps: 18.5,
    }),
  }),

  Object.freeze({
    id: 'sbb_s24_south',
    line: 'S24',
    operator: 'SBB',
    name: 'SBB S24 · Zug',
    direction: 'southbound',
    origin: 'Thayngen · Zürich HB',
    destination: 'Zug',
    trackId: 'gleis_2_nw',
    trackRank: 0,
    animTrackId: 'sbb_s8_south',
    rollingStock: 'kiss',
    carriages: 4,
    stops: Object.freeze([
      Object.freeze({
        stationId: 'bahnhof_kilchberg',
        poiId: 'poi_bahnhof',
        name: 'Bahnhof Kilchberg · Gleis 2',
        frac: 0.5475,
        dwellSec: 4.5,
      }),
    ]),
    timetable: Object.freeze({
      mode: 'clock_minutes',
      minutesPastHour: Object.freeze([27, 57]),
      firstHour: 5,
      lastHour: 24,
    }),
    periodicFallback: Object.freeze({
      mode: 'periodic',
      periodSec: 152,
      phase: 0.62,
      speedMps: 18.5,
    }),
  }),

  Object.freeze({
    id: 'sbb_s24_north',
    line: 'S24',
    operator: 'SBB',
    name: 'SBB S24 · Zürich HB / Flughafen',
    direction: 'northbound',
    origin: 'Zug',
    destination: 'Zürich HB · Flughafen',
    trackId: 'gleis_1_se',
    trackRank: 1,
    animTrackId: 'sbb_ic_north',
    rollingStock: 'kiss',
    carriages: 4,
    stops: Object.freeze([
      Object.freeze({
        stationId: 'bahnhof_kilchberg',
        poiId: 'poi_bahnhof',
        name: 'Bahnhof Kilchberg · Gleis 1',
        frac: 0.4520,
        dwellSec: 4.0,
      }),
    ]),
    timetable: Object.freeze({
      mode: 'clock_minutes',
      minutesPastHour: Object.freeze([2, 32]),
      firstHour: 5,
      lastHour: 24,
    }),
    periodicFallback: Object.freeze({
      mode: 'periodic',
      periodSec: 158,
      phase: 0.84,
      speedMps: 18.5,
    }),
  }),

  Object.freeze({
    id: 'sbb_ic_north',
    line: 'IC',
    operator: 'SBB',
    name: 'SBB IC3 · Zürich HB (Express)',
    direction: 'northbound',
    origin: 'Chur',
    destination: 'Zürich HB',
    trackId: 'gleis_1_se',
    trackRank: 1,
    animTrackId: 'sbb_ic_north',
    rollingStock: 'ic',
    carriages: 4,
    stops: Object.freeze([]),
    timetable: Object.freeze({
      mode: 'clock_minutes',
      minutesPastHour: Object.freeze([21, 51]),
      firstHour: 6,
      lastHour: 23,
    }),
    periodicFallback: Object.freeze({
      mode: 'periodic',
      periodSec: 122,
      phase: 0.58,
      speedMps: 21.0,
    }),
  }),

  Object.freeze({
    id: 'sbb_ic_south',
    line: 'IC',
    operator: 'SBB',
    name: 'SBB IC3 · Chur (Express)',
    direction: 'southbound',
    origin: 'Zürich HB',
    destination: 'Chur',
    trackId: 'gleis_2_nw',
    trackRank: 0,
    animTrackId: 'sbb_s8_south',
    rollingStock: 'ic',
    carriages: 4,
    stops: Object.freeze([]),
    timetable: Object.freeze({
      mode: 'clock_minutes',
      minutesPastHour: Object.freeze([8, 38]),
      firstHour: 6,
      lastHour: 23,
    }),
    periodicFallback: Object.freeze({
      mode: 'periodic',
      periodSec: 130,
      phase: 0.91,
      speedMps: 21.0,
    }),
  }),
]);
