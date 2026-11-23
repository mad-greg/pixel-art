/**
 * Default Sports Venue Schedule Specifications for Kilchberg (ZH).
 *
 * Venue IDs align with `docs/data/kilchberg_animations.json`:
 *   - `ambient.vignettes.tc_kilchberg` (3 clay courts)
 *   - `ambient.vignettes.sportplatz_hochweid` (main FC Kilchberg pitch)
 *   - `network.extra_sports[]`:
 *       * `sports_lakeside_tennis`
 *       * `sports_hochweid_upper_football`
 *       * `sports_brunnenmoos_football`
 *       * `sports_brunnenmoos_multisport`
 *       * `sports_gemeindehaus_multisport`
 */

export const KILCHBERG_SPORTS_SCHEDULES = Object.freeze([
  Object.freeze({
    id: 'tc_kilchberg_court_0',
    venueId: 'tc_kilchberg',
    courtIndex: 0,
    name: 'TC Kilchberg · Clay Court 1 (Center)',
    sport: 'tennis',
    club: 'TC Kilchberg',
    floodlit: true,
    diurnal: Object.freeze({ day: true, sunset: true, night: true }),
    sessions: Object.freeze([
      Object.freeze({ days: Object.freeze([1, 2, 3, 4, 5]), startMin: 480, endMin: 1260, label: 'Club Singles & Interclub', intensity: 1.0 }),
      Object.freeze({ days: Object.freeze([0, 6]), startMin: 510, endMin: 1200, label: 'Weekend Club Tournament', intensity: 1.0 }),
    ]),
  }),

  Object.freeze({
    id: 'tc_kilchberg_court_1',
    venueId: 'tc_kilchberg',
    courtIndex: 1,
    name: 'TC Kilchberg · Clay Court 2',
    sport: 'tennis',
    club: 'TC Kilchberg',
    floodlit: true,
    diurnal: Object.freeze({ day: true, sunset: true, night: true }),
    sessions: Object.freeze([
      Object.freeze({ days: Object.freeze([1, 2, 3, 4, 5]), startMin: 510, endMin: 1230, label: 'Junior Coaching & Club Play', intensity: 0.95 }),
      Object.freeze({ days: Object.freeze([0, 6]), startMin: 540, endMin: 1170, label: 'Weekend Club Rally', intensity: 0.95 }),
    ]),
  }),

  Object.freeze({
    id: 'tc_kilchberg_court_2',
    venueId: 'tc_kilchberg',
    courtIndex: 2,
    name: 'TC Kilchberg · Clay Court 3',
    sport: 'tennis',
    club: 'TC Kilchberg',
    floodlit: false,
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
    sessions: Object.freeze([
      Object.freeze({ days: Object.freeze([0, 1, 2, 3, 4, 5, 6]), startMin: 540, endMin: 1170, label: 'Daylight Clay Court Play', intensity: 0.9 }),
    ]),
  }),

  Object.freeze({
    id: 'sports_lakeside_tennis',
    venueId: 'sports_lakeside_tennis',
    name: 'Kilchberg Lakeside Clay Court',
    sport: 'tennis',
    club: 'Lakeside Private Court',
    floodlit: false,
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
    sessions: Object.freeze([
      Object.freeze({ days: Object.freeze([0, 1, 2, 3, 4, 5, 6]), startMin: 540, endMin: 1140, label: 'Lakeside Singles Rally', intensity: 0.85 }),
    ]),
  }),

  Object.freeze({
    id: 'sportplatz_hochweid',
    venueId: 'sportplatz_hochweid',
    name: 'Sportplatz Hochweid · Main Pitch',
    sport: 'football',
    club: 'FC Kilchberg-Rüschlikon',
    floodlit: true,
    diurnal: Object.freeze({ day: true, sunset: true, night: true }),
    sessions: Object.freeze([
      Object.freeze({ days: Object.freeze([1, 2, 3, 4, 5]), startMin: 960, endMin: 1290, label: 'FC Kilchberg Evening Training', intensity: 1.0 }),
      Object.freeze({ days: Object.freeze([0, 6]), startMin: 600, endMin: 1140, label: 'Regional League Matchday', intensity: 1.0 }),
    ]),
  }),

  Object.freeze({
    id: 'sports_hochweid_upper_football',
    venueId: 'sports_hochweid_upper_football',
    name: 'Sportanlage Hochweid · Upper Pitch',
    sport: 'football',
    club: 'FC Kilchberg-Rüschlikon',
    floodlit: false,
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
    sessions: Object.freeze([
      Object.freeze({ days: Object.freeze([1, 2, 3, 4, 5]), startMin: 900, endMin: 1170, label: 'Youth Academy Scrimmage', intensity: 0.9 }),
      Object.freeze({ days: Object.freeze([0, 6]), startMin: 600, endMin: 1080, label: 'Junior Matches', intensity: 0.95 }),
    ]),
  }),

  Object.freeze({
    id: 'sports_brunnenmoos_football',
    venueId: 'sports_brunnenmoos_football',
    name: 'Schulhaus Brunnenmoos · Football Field',
    sport: 'football',
    club: 'Schule Kilchberg',
    floodlit: false,
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
    sessions: Object.freeze([
      Object.freeze({ days: Object.freeze([1, 2, 3, 4, 5]), startMin: 540, endMin: 1080, label: 'School PE & After-School Kickabout', intensity: 0.9 }),
      Object.freeze({ days: Object.freeze([0, 6]), startMin: 660, endMin: 1080, label: 'Neighbourhood Match', intensity: 0.85 }),
    ]),
  }),

  Object.freeze({
    id: 'sports_brunnenmoos_multisport',
    venueId: 'sports_brunnenmoos_multisport',
    name: 'Schulhaus Brunnenmoos · Multisport Court',
    sport: 'multisport',
    club: 'Schule Kilchberg',
    floodlit: false,
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
    sessions: Object.freeze([
      Object.freeze({ days: Object.freeze([1, 2, 3, 4, 5]), startMin: 570, endMin: 1080, label: 'Recess & 4v4 Court Games', intensity: 0.9 }),
      Object.freeze({ days: Object.freeze([0, 6]), startMin: 660, endMin: 1050, label: 'Weekend 4v4 Pickup', intensity: 0.8 }),
    ]),
  }),

  Object.freeze({
    id: 'sports_gemeindehaus_multisport',
    venueId: 'sports_gemeindehaus_multisport',
    name: 'Schulhaus Alte Landstrasse · Multisport Court',
    sport: 'multisport',
    club: 'Schule Kilchberg',
    floodlit: false,
    diurnal: Object.freeze({ day: true, sunset: true, night: false }),
    sessions: Object.freeze([
      Object.freeze({ days: Object.freeze([1, 2, 3, 4, 5]), startMin: 570, endMin: 1080, label: 'Village School Recess & Sport', intensity: 0.9 }),
      Object.freeze({ days: Object.freeze([0, 6]), startMin: 660, endMin: 1020, label: 'Weekend Village Court', intensity: 0.8 }),
    ]),
  }),
]);
