/**
 * Default ZVV Bus Route Specifications for Kilchberg (ZH).
 *
 * Every `roadId`, stop `frac`, and `poiId` matches `docs/data/kilchberg_animations.json`.
 * Covers ZVV lines 161 (Seestrasse), 165 (Seestrasse -> Dorfstrasse viaduct -> Alte Landstrasse),
 * and extensible village lines 162 & 163 (Alte Landstrasse).
 */

export const ZVV_KILCHBERG_ROUTES = Object.freeze([
  Object.freeze({
    id: 'zvv_161_sb',
    line: '161',
    operator: 'ZVV',
    name: 'ZVV Bus 161 · Kilchberg, Schlimberg (Seestrasse SB)',
    direction: 'southbound',
    vehicleType: 'bus_artic',
    corridorSegments: Object.freeze([
      Object.freeze({ roadId: 'seestrasse_sb', fromFrac: 0.0, toFrac: 1.0 }),
    ]),
    stops: Object.freeze([
      Object.freeze({ stopId: 'stop_161_sb_paradies', poiId: 'poi_bus_paradies', roadId: 'seestrasse_sb', frac: 0.3313, name: 'Paradiesstrasse (Mönchhof)', dwellSec: 5.0 }),
      Object.freeze({ stopId: 'stop_161_sb_bendlikon', poiId: 'poi_bus_bendlikon', roadId: 'seestrasse_sb', frac: 0.6522, name: 'Bendlikon', dwellSec: 6.0 }),
      Object.freeze({ stopId: 'stop_161_sb_lindt', poiId: 'poi_bus_lindt', roadId: 'seestrasse_sb', frac: 0.7825, name: 'Lindt & Sprüngli', dwellSec: 6.5 }),
      Object.freeze({ stopId: 'stop_161_sb_schooren', poiId: 'poi_bus_schooren', roadId: 'seestrasse_sb', frac: 0.8753, name: 'Schooren', dwellSec: 5.0 }),
    ]),
    timetable: Object.freeze({
      minutesPastHour: Object.freeze([4, 19, 34, 49]),
      peakHeadwayMin: 7.5,
      offPeakHeadwayMin: 15,
      nightActive: true,
    }),
  }),

  Object.freeze({
    id: 'zvv_161_nb',
    line: '161',
    operator: 'ZVV',
    name: 'ZVV Bus 161 · Zürich, Bürkliplatz (Seestrasse NB)',
    direction: 'northbound',
    vehicleType: 'bus_artic',
    corridorSegments: Object.freeze([
      Object.freeze({ roadId: 'seestrasse_nb', fromFrac: 0.0, toFrac: 1.0 }),
    ]),
    stops: Object.freeze([
      Object.freeze({ stopId: 'stop_161_nb_schooren', poiId: 'poi_bus_schooren', roadId: 'seestrasse_nb', frac: 0.1251, name: 'Schooren', dwellSec: 5.0 }),
      Object.freeze({ stopId: 'stop_161_nb_lindt', poiId: 'poi_bus_lindt', roadId: 'seestrasse_nb', frac: 0.2175, name: 'Lindt & Sprüngli', dwellSec: 6.5 }),
      Object.freeze({ stopId: 'stop_161_nb_bendlikon', poiId: 'poi_bus_bendlikon', roadId: 'seestrasse_nb', frac: 0.3473, name: 'Bendlikon', dwellSec: 6.0 }),
      Object.freeze({ stopId: 'stop_161_nb_paradies', poiId: 'poi_bus_paradies', roadId: 'seestrasse_nb', frac: 0.6680, name: 'Paradiesstrasse (Mönchhof)', dwellSec: 5.0 }),
    ]),
    timetable: Object.freeze({
      minutesPastHour: Object.freeze([11, 26, 41, 56]),
      peakHeadwayMin: 7.5,
      offPeakHeadwayMin: 15,
      nightActive: true,
    }),
  }),

  Object.freeze({
    id: 'zvv_165_up',
    line: '165',
    operator: 'ZVV',
    name: 'ZVV Bus 165 · Zürich, Bürkliplatz (via Dorfstrasse Viaduct)',
    direction: 'uphill',
    vehicleType: 'bus_artic',
    corridorSegments: Object.freeze([
      Object.freeze({ roadId: 'dorfstrasse_viaduct_up', fromFrac: 0.0, toFrac: 1.0 }),
    ]),
    stops: Object.freeze([
      Object.freeze({ stopId: 'stop_165_up_schooren', poiId: 'poi_bus_schooren', roadId: 'dorfstrasse_viaduct_up', frac: 0.1106, name: 'Schooren', dwellSec: 4.5 }),
      Object.freeze({ stopId: 'stop_165_up_lindt', poiId: 'poi_bus_lindt', roadId: 'dorfstrasse_viaduct_up', frac: 0.1922, name: 'Lindt & Sprüngli', dwellSec: 6.0 }),
      Object.freeze({ stopId: 'stop_165_up_bendlikon', poiId: 'poi_bus_bendlikon', roadId: 'dorfstrasse_viaduct_up', frac: 0.3069, name: 'Bendlikon', dwellSec: 5.5 }),
      Object.freeze({ stopId: 'stop_165_up_schulhaus', poiId: 'poi_bus_schulhaus_dorf', roadId: 'dorfstrasse_viaduct_up', frac: 0.4664, name: 'Schulhaus Dorfstrasse', dwellSec: 5.0 }),
      Object.freeze({ stopId: 'stop_165_up_sanatorium', poiId: 'poi_bus_sanatorium', roadId: 'dorfstrasse_viaduct_up', frac: 0.6927, name: 'Sanatorium', dwellSec: 5.0 }),
      Object.freeze({ stopId: 'stop_165_up_paradiessteig', poiId: 'poi_bus_paradiessteig', roadId: 'dorfstrasse_viaduct_up', frac: 0.8060, name: 'Paradiessteig', dwellSec: 4.5 }),
      Object.freeze({ stopId: 'stop_165_up_hornhalden', poiId: 'poi_bus_hornhalden', roadId: 'dorfstrasse_viaduct_up', frac: 0.9019, name: 'Hornhaldenstrasse', dwellSec: 4.5 }),
    ]),
    timetable: Object.freeze({
      minutesPastHour: Object.freeze([7, 22, 37, 52]),
      peakHeadwayMin: 10,
      offPeakHeadwayMin: 15,
      nightActive: true,
    }),
  }),

  Object.freeze({
    id: 'zvv_165_dn',
    line: '165',
    operator: 'ZVV',
    name: 'ZVV Bus 165 · Rüschlikon, Park im Grüene (via Dorfstrasse Viaduct)',
    direction: 'downhill',
    vehicleType: 'bus_artic',
    corridorSegments: Object.freeze([
      Object.freeze({ roadId: 'dorfstrasse_viaduct_dn', fromFrac: 0.0, toFrac: 1.0 }),
    ]),
    stops: Object.freeze([
      Object.freeze({ stopId: 'stop_165_dn_hornhalden', poiId: 'poi_bus_hornhalden', roadId: 'dorfstrasse_viaduct_dn', frac: 0.0973, name: 'Hornhaldenstrasse', dwellSec: 4.5 }),
      Object.freeze({ stopId: 'stop_165_dn_paradiessteig', poiId: 'poi_bus_paradiessteig', roadId: 'dorfstrasse_viaduct_dn', frac: 0.1928, name: 'Paradiessteig', dwellSec: 4.5 }),
      Object.freeze({ stopId: 'stop_165_dn_sanatorium', poiId: 'poi_bus_sanatorium', roadId: 'dorfstrasse_viaduct_dn', frac: 0.3066, name: 'Sanatorium', dwellSec: 5.0 }),
      Object.freeze({ stopId: 'stop_165_dn_schulhaus', poiId: 'poi_bus_schulhaus_dorf', roadId: 'dorfstrasse_viaduct_dn', frac: 0.5333, name: 'Schulhaus Dorfstrasse', dwellSec: 5.0 }),
      Object.freeze({ stopId: 'stop_165_dn_bendlikon', poiId: 'poi_bus_bendlikon', roadId: 'dorfstrasse_viaduct_dn', frac: 0.6928, name: 'Bendlikon', dwellSec: 5.5 }),
      Object.freeze({ stopId: 'stop_165_dn_lindt', poiId: 'poi_bus_lindt', roadId: 'dorfstrasse_viaduct_dn', frac: 0.8078, name: 'Lindt & Sprüngli', dwellSec: 6.0 }),
      Object.freeze({ stopId: 'stop_165_dn_schooren', poiId: 'poi_bus_schooren', roadId: 'dorfstrasse_viaduct_dn', frac: 0.8898, name: 'Schooren', dwellSec: 4.5 }),
    ]),
    timetable: Object.freeze({
      minutesPastHour: Object.freeze([14, 29, 44, 59]),
      peakHeadwayMin: 10,
      offPeakHeadwayMin: 15,
      nightActive: true,
    }),
  }),

  Object.freeze({
    id: 'zvv_162_eb',
    line: '162',
    operator: 'ZVV',
    name: 'ZVV Bus 162 · Kilchberg, Dorf / Alte Landstrasse EB',
    direction: 'eastbound',
    vehicleType: 'bus_rigid',
    corridorSegments: Object.freeze([
      Object.freeze({ roadId: 'alte_landstrasse_eb', fromFrac: 0.0, toFrac: 1.0 }),
    ]),
    stops: Object.freeze([
      Object.freeze({ stopId: 'stop_162_eb_schwelle', poiId: 'poi_bus_schwelle', roadId: 'alte_landstrasse_eb', frac: 0.3947, name: 'Schwelle (Kilchberg Dorf)', dwellSec: 5.0 }),
      Object.freeze({ stopId: 'stop_162_eb_gemeindehaus', poiId: 'poi_bus_gemeindehaus', roadId: 'alte_landstrasse_eb', frac: 0.5521, name: 'Gemeindehaus', dwellSec: 5.5 }),
      Object.freeze({ stopId: 'stop_162_eb_sanatorium', poiId: 'poi_bus_sanatorium', roadId: 'alte_landstrasse_eb', frac: 0.6469, name: 'Sanatorium', dwellSec: 5.0 }),
      Object.freeze({ stopId: 'stop_162_eb_paradiessteig', poiId: 'poi_bus_paradiessteig', roadId: 'alte_landstrasse_eb', frac: 0.7772, name: 'Paradiessteig', dwellSec: 4.5 }),
      Object.freeze({ stopId: 'stop_162_eb_hornhalden', poiId: 'poi_bus_hornhalden', roadId: 'alte_landstrasse_eb', frac: 0.8873, name: 'Hornhaldenstrasse', dwellSec: 4.5 }),
    ]),
    timetable: Object.freeze({
      minutesPastHour: Object.freeze([9, 39]),
      peakHeadwayMin: 15,
      offPeakHeadwayMin: 30,
      nightActive: false,
    }),
  }),

  Object.freeze({
    id: 'zvv_163_wb',
    line: '163',
    operator: 'ZVV',
    name: 'ZVV Bus 163 · Kilchberg, Schwelle / Alte Landstrasse WB',
    direction: 'westbound',
    vehicleType: 'bus_rigid',
    corridorSegments: Object.freeze([
      Object.freeze({ roadId: 'alte_landstrasse_wb', fromFrac: 0.0, toFrac: 1.0 }),
    ]),
    stops: Object.freeze([
      Object.freeze({ stopId: 'stop_163_wb_hornhalden', poiId: 'poi_bus_hornhalden', roadId: 'alte_landstrasse_wb', frac: 0.1120, name: 'Hornhaldenstrasse', dwellSec: 4.5 }),
      Object.freeze({ stopId: 'stop_163_wb_paradiessteig', poiId: 'poi_bus_paradiessteig', roadId: 'alte_landstrasse_wb', frac: 0.2218, name: 'Paradiessteig', dwellSec: 4.5 }),
      Object.freeze({ stopId: 'stop_163_wb_sanatorium', poiId: 'poi_bus_sanatorium', roadId: 'alte_landstrasse_wb', frac: 0.3525, name: 'Sanatorium', dwellSec: 5.0 }),
      Object.freeze({ stopId: 'stop_163_wb_gemeindehaus', poiId: 'poi_bus_gemeindehaus', roadId: 'alte_landstrasse_wb', frac: 0.4472, name: 'Gemeindehaus', dwellSec: 5.5 }),
      Object.freeze({ stopId: 'stop_163_wb_schwelle', poiId: 'poi_bus_schwelle', roadId: 'alte_landstrasse_wb', frac: 0.6047, name: 'Schwelle (Kilchberg Dorf)', dwellSec: 5.0 }),
    ]),
    timetable: Object.freeze({
      minutesPastHour: Object.freeze([24, 54]),
      peakHeadwayMin: 15,
      offPeakHeadwayMin: 30,
      nightActive: false,
    }),
  }),
]);
