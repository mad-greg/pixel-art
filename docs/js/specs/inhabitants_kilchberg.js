/**
 * Default Named Kilchberg Inhabitant Specifications (20 authentic Swiss residents).
 *
 * Every `home.poiId` and local `targetPoi` references a real POI ID in
 * `docs/data/kilchberg_animations.json` (`network.pois[]`).
 * Routine intervals use minutes-of-day (`startMin..endMin` in `0..1440`).
 */

export const KILCHBERG_INHABITANTS = Object.freeze([
  Object.freeze({
    id: 'inhab_anna_meier',
    name: 'Anna Meier',
    role: 'Architect · Zürich HB Commuter',
    home: Object.freeze({ poiId: 'poi_res_bendlikon', label: 'Quartier Bendlikon' }),
    workplace: Object.freeze({ poiId: 'zurich_hb_via_s8', label: 'Zürich HB (via S8)' }),
    appearance: Object.freeze({ coat: '#1e3a5f', pants: '#27272a', hair: '#5c4028', bag: '#92400e' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 430, activity: 'home', targetPoi: 'poi_res_bendlikon', transport: 'walk' }),
      Object.freeze({ startMin: 430, endMin: 470, activity: 'commute_rail', targetPoi: 'poi_bahnhof', transport: 'sbb_s8' }),
      Object.freeze({ startMin: 470, endMin: 1035, activity: 'work', targetPoi: 'poi_bahnhof', transport: 'sbb_s8' }),
      Object.freeze({ startMin: 1035, endMin: 1080, activity: 'commute_rail', targetPoi: 'poi_res_bendlikon', transport: 'walk' }),
      Object.freeze({ startMin: 1080, endMin: 1170, activity: 'promenade_walk', targetPoi: 'poi_morfanlage', transport: 'walk' }),
      Object.freeze({ startMin: 1170, endMin: 1440, activity: 'home', targetPoi: 'poi_res_bendlikon', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_lukas_keller',
    name: 'Lukas Keller',
    role: 'Maître Chocolatier · Lindt & Sprüngli',
    home: Object.freeze({ poiId: 'poi_res_schooren', label: 'Quartier Schooren' }),
    workplace: Object.freeze({ poiId: 'poi_lindt_plaza', label: 'Lindt Home of Chocolate' }),
    appearance: Object.freeze({ coat: '#78350f', pants: '#1f2937', hair: '#3a3430', bag: '#d97706' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 410, activity: 'home', targetPoi: 'poi_res_schooren', transport: 'walk' }),
      Object.freeze({ startMin: 410, endMin: 720, activity: 'work', targetPoi: 'poi_lindt_plaza', transport: 'walk' }),
      Object.freeze({ startMin: 720, endMin: 780, activity: 'cafe', targetPoi: 'poi_bendlikon_pier', transport: 'walk' }),
      Object.freeze({ startMin: 780, endMin: 1020, activity: 'work', targetPoi: 'poi_lindt_plaza', transport: 'walk' }),
      Object.freeze({ startMin: 1020, endMin: 1110, activity: 'seebad', targetPoi: 'poi_seebad', transport: 'walk' }),
      Object.freeze({ startMin: 1110, endMin: 1440, activity: 'home', targetPoi: 'poi_res_schooren', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_clara_huber',
    name: 'Clara Huber',
    role: 'Primary Teacher · Schulhaus Dorfstrasse',
    home: Object.freeze({ poiId: 'poi_res_schwelle', label: 'Quartier Schwelle' }),
    workplace: Object.freeze({ poiId: 'poi_schulhaus_dorf', label: 'Schulhaus Dorfstrasse' }),
    appearance: Object.freeze({ coat: '#0d9488', pants: '#334155', hair: '#8a6842', bag: '#b45309' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 445, activity: 'home', targetPoi: 'poi_res_schwelle', transport: 'walk' }),
      Object.freeze({ startMin: 445, endMin: 730, activity: 'work', targetPoi: 'poi_schulhaus_dorf', transport: 'walk' }),
      Object.freeze({ startMin: 730, endMin: 800, activity: 'errand_village', targetPoi: 'poi_gemeindehaus', transport: 'walk' }),
      Object.freeze({ startMin: 800, endMin: 980, activity: 'work', targetPoi: 'poi_schulhaus_dorf', transport: 'walk' }),
      Object.freeze({ startMin: 980, endMin: 1060, activity: 'cafe', targetPoi: 'poi_fountain_cf_meyer', transport: 'walk' }),
      Object.freeze({ startMin: 1060, endMin: 1440, activity: 'home', targetPoi: 'poi_res_schwelle', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_matteo_schmid',
    name: 'Matteo Schmid',
    role: 'Student · Campus Kilchberg',
    home: Object.freeze({ poiId: 'poi_res_boendler', label: 'Quartier Böndler' }),
    workplace: Object.freeze({ poiId: 'poi_campus_kilchberg', label: 'Campus Kilchberg' }),
    appearance: Object.freeze({ coat: '#2563eb', pants: '#1e293b', hair: '#2d241c', bag: '#dc2626' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 460, activity: 'home', targetPoi: 'poi_res_boendler', transport: 'walk' }),
      Object.freeze({ startMin: 460, endMin: 720, activity: 'school', targetPoi: 'poi_campus_kilchberg', transport: 'bike' }),
      Object.freeze({ startMin: 720, endMin: 800, activity: 'errand_lindt', targetPoi: 'poi_lindt_plaza', transport: 'walk' }),
      Object.freeze({ startMin: 800, endMin: 945, activity: 'school', targetPoi: 'poi_campus_kilchberg', transport: 'walk' }),
      Object.freeze({ startMin: 945, endMin: 1065, activity: 'seebad', targetPoi: 'poi_seebad', transport: 'bike' }),
      Object.freeze({ startMin: 1065, endMin: 1440, activity: 'home', targetPoi: 'poi_res_boendler', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_helena_brunner',
    name: 'Helena Brunner',
    role: 'Senior Nurse · Sanatorium Kilchberg',
    home: Object.freeze({ poiId: 'poi_res_moenchhof', label: 'Quartier Mönchhof' }),
    workplace: Object.freeze({ poiId: 'poi_sanatorium', label: 'Sanatorium Kilchberg' }),
    appearance: Object.freeze({ coat: '#e2e8f0', pants: '#334155', hair: '#b89458', bag: '#475569' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 400, activity: 'home', targetPoi: 'poi_res_moenchhof', transport: 'walk' }),
      Object.freeze({ startMin: 400, endMin: 430, activity: 'commute_bus', targetPoi: 'poi_bus_sanatorium', transport: 'bus_165' }),
      Object.freeze({ startMin: 430, endMin: 960, activity: 'work', targetPoi: 'poi_sanatorium', transport: 'walk' }),
      Object.freeze({ startMin: 960, endMin: 1040, activity: 'promenade_walk', targetPoi: 'poi_sulzergut', transport: 'walk' }),
      Object.freeze({ startMin: 1040, endMin: 1440, activity: 'home', targetPoi: 'poi_res_moenchhof', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_reto_zimmermann',
    name: 'Reto Zimmermann',
    role: 'Municipal Clerk · Gemeindehaus Kilchberg',
    home: Object.freeze({ poiId: 'poi_res_horn', label: 'Quartier Horn' }),
    workplace: Object.freeze({ poiId: 'poi_gemeindehaus', label: 'Gemeindehaus Kilchberg' }),
    appearance: Object.freeze({ coat: '#475569', pants: '#1f2937', hair: '#5c4028', hat: '#334155' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 455, activity: 'home', targetPoi: 'poi_res_horn', transport: 'walk' }),
      Object.freeze({ startMin: 455, endMin: 725, activity: 'work', targetPoi: 'poi_gemeindehaus', transport: 'bus_162' }),
      Object.freeze({ startMin: 725, endMin: 790, activity: 'cafe', targetPoi: 'poi_fountain_kirche', transport: 'walk' }),
      Object.freeze({ startMin: 790, endMin: 1050, activity: 'work', targetPoi: 'poi_gemeindehaus', transport: 'walk' }),
      Object.freeze({ startMin: 1050, endMin: 1140, activity: 'promenade_walk', targetPoi: 'poi_navillepark', transport: 'walk' }),
      Object.freeze({ startMin: 1140, endMin: 1440, activity: 'home', targetPoi: 'poi_res_horn', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_sophie_steiner',
    name: 'Sophie Steiner',
    role: 'Financial Analyst · Bürkliplatz Commuter',
    home: Object.freeze({ poiId: 'poi_res_schooren', label: 'Quartier Schooren' }),
    workplace: Object.freeze({ poiId: 'zurich_via_161', label: 'Zürich Bürkliplatz (via Bus 161)' }),
    appearance: Object.freeze({ coat: '#9f1239', pants: '#18181b', hair: '#2d241c', bag: '#1e293b' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 440, activity: 'home', targetPoi: 'poi_res_schooren', transport: 'walk' }),
      Object.freeze({ startMin: 440, endMin: 485, activity: 'commute_bus', targetPoi: 'poi_bus_schooren', transport: 'bus_161' }),
      Object.freeze({ startMin: 485, endMin: 1050, activity: 'work', targetPoi: 'poi_bus_schooren', transport: 'bus_161' }),
      Object.freeze({ startMin: 1050, endMin: 1130, activity: 'errand_lindt', targetPoi: 'poi_lindt_plaza', transport: 'walk' }),
      Object.freeze({ startMin: 1130, endMin: 1440, activity: 'home', targetPoi: 'poi_res_schooren', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_walter_moser',
    name: 'Walter Moser',
    role: 'Retired Watchmaker & Dog Walker',
    home: Object.freeze({ poiId: 'poi_res_stocken', label: 'Quartier Stocken' }),
    workplace: Object.freeze({ poiId: 'poi_morfanlage', label: 'Morfanlage Lakeside Park' }),
    appearance: Object.freeze({ coat: '#65a30d', pants: '#44403c', hair: '#cbd5e1', hat: '#78350f', dog: '#b45309' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 420, activity: 'home', targetPoi: 'poi_res_stocken', transport: 'walk' }),
      Object.freeze({ startMin: 420, endMin: 540, activity: 'dog_walk', targetPoi: 'poi_morfanlage', transport: 'walk' }),
      Object.freeze({ startMin: 540, endMin: 660, activity: 'cafe', targetPoi: 'poi_fountain_kirche', transport: 'walk' }),
      Object.freeze({ startMin: 660, endMin: 900, activity: 'home', targetPoi: 'poi_res_stocken', transport: 'walk' }),
      Object.freeze({ startMin: 900, endMin: 1080, activity: 'dog_walk', targetPoi: 'poi_sulzergut', transport: 'walk' }),
      Object.freeze({ startMin: 1080, endMin: 1440, activity: 'home', targetPoi: 'poi_res_stocken', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_nina_baumann',
    name: 'Nina Baumann',
    role: 'Lake Swimmer & Physiotherapist',
    home: Object.freeze({ poiId: 'poi_res_bendlikon', label: 'Quartier Bendlikon' }),
    workplace: Object.freeze({ poiId: 'poi_sanatorium', label: 'Sanatorium Kilchberg' }),
    appearance: Object.freeze({ coat: '#0284c7', pants: '#334155', hair: '#b89458', bag: '#0ea5e9' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 415, activity: 'home', targetPoi: 'poi_res_bendlikon', transport: 'walk' }),
      Object.freeze({ startMin: 415, endMin: 500, activity: 'seebad', targetPoi: 'poi_seebad', transport: 'walk' }),
      Object.freeze({ startMin: 500, endMin: 990, activity: 'work', targetPoi: 'poi_sanatorium', transport: 'bus_165' }),
      Object.freeze({ startMin: 990, endMin: 1110, activity: 'seebad', targetPoi: 'poi_seebad', transport: 'walk' }),
      Object.freeze({ startMin: 1110, endMin: 1440, activity: 'home', targetPoi: 'poi_res_bendlikon', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_fabian_graf',
    name: 'Fabian Graf',
    role: 'Software Engineer · Zürich HB Commuter',
    home: Object.freeze({ poiId: 'poi_res_im_breitloo', label: 'Quartier Im Breitloo' }),
    workplace: Object.freeze({ poiId: 'zurich_hb_via_s8', label: 'Zürich HB (via S24)' }),
    appearance: Object.freeze({ coat: '#334155', pants: '#1e293b', hair: '#3a3430', bag: '#0f172a' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 465, activity: 'home', targetPoi: 'poi_res_im_breitloo', transport: 'walk' }),
      Object.freeze({ startMin: 465, endMin: 510, activity: 'commute_rail', targetPoi: 'poi_bahnhof', transport: 'sbb_s8' }),
      Object.freeze({ startMin: 510, endMin: 1070, activity: 'work', targetPoi: 'poi_bahnhof', transport: 'sbb_s8' }),
      Object.freeze({ startMin: 1070, endMin: 1150, activity: 'sports', targetPoi: 'poi_schulhaus_brunnenmoos', transport: 'walk' }),
      Object.freeze({ startMin: 1150, endMin: 1440, activity: 'home', targetPoi: 'poi_res_im_breitloo', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_elena_widmer',
    name: 'Elena Widmer',
    role: 'Museum Guide · Lindt Home of Chocolate',
    home: Object.freeze({ poiId: 'poi_res_lebern', label: 'Quartier Lebern' }),
    workplace: Object.freeze({ poiId: 'poi_lindt_plaza', label: 'Lindt Home of Chocolate' }),
    appearance: Object.freeze({ coat: '#d97706', pants: '#27272a', hair: '#5c4028', bag: '#f59e0b' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 510, activity: 'home', targetPoi: 'poi_res_lebern', transport: 'walk' }),
      Object.freeze({ startMin: 510, endMin: 550, activity: 'commute_bus', targetPoi: 'poi_bus_lindt', transport: 'bus_165' }),
      Object.freeze({ startMin: 550, endMin: 1060, activity: 'work', targetPoi: 'poi_lindt_plaza', transport: 'walk' }),
      Object.freeze({ startMin: 1060, endMin: 1140, activity: 'promenade_walk', targetPoi: 'poi_bendlikon_pier', transport: 'walk' }),
      Object.freeze({ startMin: 1140, endMin: 1440, activity: 'home', targetPoi: 'poi_res_lebern', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_martin_frei',
    name: 'Martin Frei',
    role: 'Church Organist · Reformierte Kirche',
    home: Object.freeze({ poiId: 'poi_res_schwelle', label: 'Quartier Schwelle' }),
    workplace: Object.freeze({ poiId: 'poi_kirche', label: 'Reformierte Kirche Kilchberg' }),
    appearance: Object.freeze({ coat: '#1e293b', pants: '#18181b', hair: '#94a3b8', hat: '#1e293b' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 480, activity: 'home', targetPoi: 'poi_res_schwelle', transport: 'walk' }),
      Object.freeze({ startMin: 480, endMin: 720, activity: 'church', targetPoi: 'poi_kirche', transport: 'walk' }),
      Object.freeze({ startMin: 720, endMin: 810, activity: 'cafe', targetPoi: 'poi_fountain_kirche', transport: 'walk' }),
      Object.freeze({ startMin: 810, endMin: 1020, activity: 'church', targetPoi: 'poi_st_elisabeth', transport: 'walk' }),
      Object.freeze({ startMin: 1020, endMin: 1110, activity: 'promenade_walk', targetPoi: 'poi_fountain_cf_meyer', transport: 'walk' }),
      Object.freeze({ startMin: 1110, endMin: 1440, activity: 'home', targetPoi: 'poi_res_schwelle', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_lea_weber',
    name: 'Lea Weber',
    role: 'Pupil · Schulhaus Alte Landstrasse',
    home: Object.freeze({ poiId: 'poi_res_boendler', label: 'Quartier Böndler' }),
    workplace: Object.freeze({ poiId: 'poi_schulhaus_alte_landstr', label: 'Schulhaus Alte Landstrasse' }),
    appearance: Object.freeze({ coat: '#ec4899', pants: '#334155', hair: '#8a6842', bag: '#7c3aed' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 465, activity: 'home', targetPoi: 'poi_res_boendler', transport: 'walk' }),
      Object.freeze({ startMin: 465, endMin: 715, activity: 'school', targetPoi: 'poi_schulhaus_alte_landstr', transport: 'walk' }),
      Object.freeze({ startMin: 715, endMin: 810, activity: 'home', targetPoi: 'poi_res_boendler', transport: 'walk' }),
      Object.freeze({ startMin: 810, endMin: 950, activity: 'school', targetPoi: 'poi_schulhaus_alte_landstr', transport: 'walk' }),
      Object.freeze({ startMin: 950, endMin: 1050, activity: 'sports', targetPoi: 'poi_gemeindehaus', transport: 'walk' }),
      Object.freeze({ startMin: 1050, endMin: 1440, activity: 'home', targetPoi: 'poi_res_boendler', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_thomas_bucher',
    name: 'Thomas Bucher',
    role: 'Harbor Master · Bendlikon Pier',
    home: Object.freeze({ poiId: 'poi_res_moenchhof', label: 'Quartier Mönchhof' }),
    workplace: Object.freeze({ poiId: 'poi_bendlikon_pier', label: 'Bendlikon Pier (ZSG)' }),
    appearance: Object.freeze({ coat: '#1d4ed8', pants: '#1e293b', hair: '#5c4028', hat: '#1e3a8a' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 450, activity: 'home', targetPoi: 'poi_res_moenchhof', transport: 'walk' }),
      Object.freeze({ startMin: 450, endMin: 750, activity: 'work', targetPoi: 'poi_bendlikon_pier', transport: 'walk' }),
      Object.freeze({ startMin: 750, endMin: 830, activity: 'cafe', targetPoi: 'poi_morfanlage', transport: 'walk' }),
      Object.freeze({ startMin: 830, endMin: 1120, activity: 'work', targetPoi: 'poi_bendlikon_pier', transport: 'walk' }),
      Object.freeze({ startMin: 1120, endMin: 1440, activity: 'home', targetPoi: 'poi_res_moenchhof', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_mirjam_hofer',
    name: 'Mirjam Hofer',
    role: 'Tennis Coach · TC Kilchberg',
    home: Object.freeze({ poiId: 'poi_res_stocken', label: 'Quartier Stocken' }),
    workplace: Object.freeze({ poiId: 'poi_schulhaus_brunnenmoos', label: 'TC Kilchberg / Hochweid' }),
    appearance: Object.freeze({ coat: '#f8fafc', pants: '#0f172a', hair: '#b89458', bag: '#16a34a' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 480, activity: 'home', targetPoi: 'poi_res_stocken', transport: 'walk' }),
      Object.freeze({ startMin: 480, endMin: 720, activity: 'sports', targetPoi: 'poi_schulhaus_brunnenmoos', transport: 'walk' }),
      Object.freeze({ startMin: 720, endMin: 840, activity: 'errand_village', targetPoi: 'poi_gemeindehaus', transport: 'walk' }),
      Object.freeze({ startMin: 840, endMin: 1140, activity: 'sports', targetPoi: 'poi_schulhaus_brunnenmoos', transport: 'walk' }),
      Object.freeze({ startMin: 1140, endMin: 1440, activity: 'home', targetPoi: 'poi_res_stocken', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_daniel_wyss',
    name: 'Daniel Wyss',
    role: 'Doctor · Zürich University Hospital Commuter',
    home: Object.freeze({ poiId: 'poi_res_horn', label: 'Quartier Horn' }),
    workplace: Object.freeze({ poiId: 'zurich_hb_via_s8', label: 'Zürich HB (via S8)' }),
    appearance: Object.freeze({ coat: '#0f766e', pants: '#1f2937', hair: '#2d241c', bag: '#334155' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 410, activity: 'home', targetPoi: 'poi_res_horn', transport: 'walk' }),
      Object.freeze({ startMin: 410, endMin: 455, activity: 'commute_rail', targetPoi: 'poi_bahnhof', transport: 'sbb_s8' }),
      Object.freeze({ startMin: 455, endMin: 1080, activity: 'work', targetPoi: 'poi_bahnhof', transport: 'sbb_s8' }),
      Object.freeze({ startMin: 1080, endMin: 1170, activity: 'promenade_walk', targetPoi: 'poi_fountain_bahnhof', transport: 'walk' }),
      Object.freeze({ startMin: 1170, endMin: 1440, activity: 'home', targetPoi: 'poi_res_horn', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_sarah_fischer',
    name: 'Sarah Fischer',
    role: 'Botanist & Dog Owner · Navillepark',
    home: Object.freeze({ poiId: 'poi_res_bendlikon', label: 'Quartier Bendlikon' }),
    workplace: Object.freeze({ poiId: 'poi_navillepark', label: 'Navillepark & Sulzergut' }),
    appearance: Object.freeze({ coat: '#7c3aed', pants: '#334155', hair: '#8a6842', dog: '#475569' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 450, activity: 'home', targetPoi: 'poi_res_bendlikon', transport: 'walk' }),
      Object.freeze({ startMin: 450, endMin: 570, activity: 'dog_walk', targetPoi: 'poi_navillepark', transport: 'walk' }),
      Object.freeze({ startMin: 570, endMin: 810, activity: 'work', targetPoi: 'poi_sulzergut', transport: 'walk' }),
      Object.freeze({ startMin: 810, endMin: 930, activity: 'errand_lindt', targetPoi: 'poi_lindt_plaza', transport: 'walk' }),
      Object.freeze({ startMin: 930, endMin: 1110, activity: 'dog_walk', targetPoi: 'poi_morfanlage', transport: 'walk' }),
      Object.freeze({ startMin: 1110, endMin: 1440, activity: 'home', targetPoi: 'poi_res_bendlikon', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_marco_berger',
    name: 'Marco Berger',
    role: 'Artisan Baker · Dorfplatz',
    home: Object.freeze({ poiId: 'poi_res_lebern', label: 'Quartier Lebern' }),
    workplace: Object.freeze({ poiId: 'poi_fountain_kirche', label: 'Dorfplatz Bäckerei' }),
    appearance: Object.freeze({ coat: '#ca8a04', pants: '#27272a', hair: '#3a3430', bag: '#78350f' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 330, activity: 'home', targetPoi: 'poi_res_lebern', transport: 'walk' }),
      Object.freeze({ startMin: 330, endMin: 780, activity: 'work', targetPoi: 'poi_fountain_kirche', transport: 'walk' }),
      Object.freeze({ startMin: 780, endMin: 900, activity: 'promenade_walk', targetPoi: 'poi_seebad', transport: 'walk' }),
      Object.freeze({ startMin: 900, endMin: 1050, activity: 'errand_village', targetPoi: 'poi_gemeindehaus', transport: 'walk' }),
      Object.freeze({ startMin: 1050, endMin: 1440, activity: 'home', targetPoi: 'poi_res_lebern', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_katrin_roth',
    name: 'Katrin Roth',
    role: 'Historian · C.F. Meyer-Haus',
    home: Object.freeze({ poiId: 'poi_res_im_breitloo', label: 'Quartier Im Breitloo' }),
    workplace: Object.freeze({ poiId: 'poi_fountain_cf_meyer', label: 'C.F. Meyer-Haus' }),
    appearance: Object.freeze({ coat: '#be123c', pants: '#334155', hair: '#5c4028', bag: '#7f1d1d' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 510, activity: 'home', targetPoi: 'poi_res_im_breitloo', transport: 'walk' }),
      Object.freeze({ startMin: 510, endMin: 740, activity: 'work', targetPoi: 'poi_fountain_cf_meyer', transport: 'walk' }),
      Object.freeze({ startMin: 740, endMin: 820, activity: 'cafe', targetPoi: 'poi_gemeindehaus', transport: 'walk' }),
      Object.freeze({ startMin: 820, endMin: 1040, activity: 'work', targetPoi: 'poi_fountain_cf_meyer', transport: 'walk' }),
      Object.freeze({ startMin: 1040, endMin: 1120, activity: 'church', targetPoi: 'poi_kirche', transport: 'walk' }),
      Object.freeze({ startMin: 1120, endMin: 1440, activity: 'home', targetPoi: 'poi_res_im_breitloo', transport: 'walk' }),
    ]),
  }),

  Object.freeze({
    id: 'inhab_jonas_suter',
    name: 'Jonas Suter',
    role: 'Rowing Club Member & Commuter',
    home: Object.freeze({ poiId: 'poi_res_moenchhof', label: 'Quartier Mönchhof' }),
    workplace: Object.freeze({ poiId: 'zurich_via_161', label: 'Zürich Enge (via Bus 161)' }),
    appearance: Object.freeze({ coat: '#15803d', pants: '#1e293b', hair: '#2d241c', bag: '#166534' }),
    routine: Object.freeze([
      Object.freeze({ startMin: 0, endMin: 400, activity: 'home', targetPoi: 'poi_res_moenchhof', transport: 'walk' }),
      Object.freeze({ startMin: 400, endMin: 470, activity: 'promenade_walk', targetPoi: 'poi_sulzergut', transport: 'walk' }),
      Object.freeze({ startMin: 470, endMin: 510, activity: 'commute_bus', targetPoi: 'poi_bus_paradies', transport: 'bus_161' }),
      Object.freeze({ startMin: 510, endMin: 1060, activity: 'work', targetPoi: 'poi_bus_paradies', transport: 'bus_161' }),
      Object.freeze({ startMin: 1060, endMin: 1150, activity: 'seebad', targetPoi: 'poi_bendlikon_pier', transport: 'walk' }),
      Object.freeze({ startMin: 1150, endMin: 1440, activity: 'home', targetPoi: 'poi_res_moenchhof', transport: 'walk' }),
    ]),
  }),
]);
