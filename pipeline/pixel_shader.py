"""V3 Master-Crafted 90s Isometric 3D Pixel-Art Renderer for Kilchberg ZH.

100% geographically exact, distinctly drawn 90s SVGA isometric pixel-art entities:
- Procedural 90s pixel-art ground, mowed Swiss meadows, 3D terraced vineyards, stone plazas,
  asphalt streets with raised sidewalks/curbs, Swiss yellow zebra crosswalks, and SBB Seebahn
  ballast + sleepers + twin steel rails + raised station platforms + steel catenary portals.
- True 3D elevated viaducts & bridges (Dorfstrasse horseshoe viaduct, Bahnhofstrasse bridge,
  concrete support piers, spiral pedestrian stairs, A3 overpasses & rail bridges) with open
  clearance underneath so SBB trains and streets pass cleanly below.
- Procedural 90s pixel-art 3D LOD2 buildings (1,890 buildings, 124,155 triangles) with staggered
  clay/slate roof tiles, crisp flat-roof parapet coping rims & inner shadows, geometric solar PV
  panels, authentic photographed Kilchberg & Lindt facades, and razor-sharp 1px sel-out outlines.
- 14,639 individually sculpted 3D pixel-art trees (multi-puff deciduous crowns, tiered alpine
  conifers, slender cypresses, copper beeches) with timber trunks, 4-tone SVGA leaf shading,
  per-tree 1px sel-out outlines, and neat beveled garden hedges.
"""

from __future__ import annotations
import gc as _gc
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from . import signage as _signage
from .config import (
    E_MAX,
    E_MIN,
    IsometricCamera,
    LAKE_SURFACE_Z,
    LANDMARKS,
    N_MAX,
    N_MIN,
    PLINTH_BASE_Z,
    RAW_CACHE_DIR,
)
from .extract_scene import (
    BR_FOOTBRIDGE,
    BR_MOTORWAY,
    BR_RAIL_BRIDGE,
    BR_ROAD_VIADUCT,
    BR_STEPS,
    G_FOOTPATH,
    G_FOREST,
    G_LAKE,
    G_MOTORWAY,
    G_PARK_CEMETERY,
    G_PARKING,
    G_PITCH,
    G_PLATFORM_PIER,
    G_POOL,
    G_RAILWAY,
    G_STREAM,
    G_STREET_MAIN,
    G_STREET_MINOR,
    G_TERRAIN,
    G_VINEYARD,
    GRID_H,
    GRID_RES,
    GRID_W,
)

ORTHO10_RES = 0.10
ORTHO10_W = int(round((E_MAX - E_MIN) / ORTHO10_RES))
ORTHO10_H = int(round((N_MAX - N_MIN) / ORTHO10_RES))
ORTHO25_RES = 0.25
ORTHO25_W = int(round((E_MAX - E_MIN) / ORTHO25_RES))
ORTHO25_H = int(round((N_MAX - N_MIN) / ORTHO25_RES))

# Material IDs
M_BG = 0
M_DROP_SHADOW = 1
M_CUTAWAY_EARTH = 2
M_CUTAWAY_WATER = 3
M_WATER_LAKE = 4
M_HARBOR_OBJ = 5
M_GROUND = 6
M_WALL = 7
M_ROOF = 8
M_WINDOW_LIT = 9
M_WINDOW_DAY = 10
M_TREE = 11
M_TRUNK = 12
M_BRIDGE = 13
M_RAIL = 14

# Classic 4x4 Bayer ordered dither matrix normalized to [-0.5, +0.5]
BAYER_4X4 = (
    np.array(
        [
            [0, 8, 2, 10],
            [12, 4, 14, 6],
            [3, 11, 1, 9],
            [15, 7, 13, 5],
        ],
        dtype=np.float32,
    )
    / 16.0
    - 0.46875
)


@dataclass(frozen=True)
class LightingPreset:
    name: str
    sun_az_deg: float
    sun_alt_deg: float
    sun_rgb: tuple[float, float, float]
    amb_rgb: tuple[float, float, float]
    sky_top_rgb: tuple[int, int, int]
    sky_bot_rgb: tuple[int, int, int]
    is_night: bool = False
    dither_strength: float = 9.0


PRESETS: dict[str, LightingPreset] = {
    "day": LightingPreset(
        name="90s SVGA Crisp Alpine Midday",
        sun_az_deg=124.0,
        sun_alt_deg=43.0,
        sun_rgb=(1.14, 1.07, 0.94),
        amb_rgb=(0.45, 0.52, 0.68),
        sky_top_rgb=(24, 34, 52),
        sky_bot_rgb=(38, 52, 74),
        is_night=False,
        dither_strength=1.2,
    ),
    "sunset": LightingPreset(
        name="Alpenglow Golden Sunset",
        sun_az_deg=114.0,
        sun_alt_deg=22.0,
        sun_rgb=(1.40, 1.02, 0.56),
        amb_rgb=(0.38, 0.42, 0.58),
        sky_top_rgb=(28, 24, 52),
        sky_bot_rgb=(82, 50, 58),
        is_night=False,
        dither_strength=1.5,
    ),
    "night": LightingPreset(
        name="Zürichsee Lantern Night",
        sun_az_deg=128.0,
        sun_alt_deg=36.0,
        sun_rgb=(0.36, 0.46, 0.72),
        amb_rgb=(0.15, 0.20, 0.35),
        sky_top_rgb=(7, 10, 20),
        sky_bot_rgb=(14, 21, 38),
        is_night=True,
        dither_strength=1.5,
    ),
}

# Verified LV95 landmark registry: key -> (target_e, target_n, max_rad_m, optional_objektart_prefix)
LANDMARK_SPECS: dict[str, tuple[float, float, float, str | None]] = {
    "lindt_hoc":         (2684117.9, 1241416.6, 12.0, "Gebaeude"),
    "lindt_chimney":     (2684156.7, 1241360.1, 10.0, "Hochkamin"),
    "lindt_main":        (2684208.3, 1241374.1, 15.0, "Gebaeude"),
    "lindt_brick_n":     (2684151.2, 1241372.3, 12.0, "Gebaeude"),
    "lindt_brick_s":     (2684158.8, 1241347.4, 12.0, "Gebaeude"),
    "lindt_wing_963":    (2684160.5, 1241331.8, 10.0, "Gebaeude"),
    "lindt_wing_1520":   (2684145.6, 1241443.1, 12.0, "Gebaeude"),
    "lindt_wing_1281":   (2684133.8, 1241478.7, 12.0, "Gebaeude"),
    "lindt_wing_1173":   (2684177.1, 1241416.9, 12.0, "Gebaeude"),
    "lindt_south_1473":  (2684194.7, 1241313.2, 15.0, "Gebaeude"),
    "lindt_south_1720":  (2684156.9, 1241246.3, 15.0, "Gebaeude"),
    "ref_kirche":        (2683406.4, 1241285.4, 12.0, "Sakral"),
    "dorf_barn_1490":    (2683419.9, 1241326.7,  8.0, "Gebaeude"),
    "dorf_barn_1726":    (2683410.4, 1241325.9,  8.0, "Gebaeude"),
    "st_elisabeth_nave": (2683507.1, 1241632.9, 12.0, "Sakral"),
    "st_elisabeth_twr":  (2683480.0, 1241656.0, 10.0, "Sakral"),
    "bendlikon_pier":    (2684061.3, 1242075.6, 10.0, "Flugdach"),
    "bendlikon_pavilion":(2684144.9, 1241896.4, 10.0, "Gebaeude"),
    "bahnhof_station":   (2683867.2, 1242102.6, 12.0, "Gebaeude"),
    "bahnhof_canopy":    (2683844.2, 1242104.6, 12.0, "Flugdach"),
    "gemeindehaus_main": (2683628.9, 1242100.7, 15.0, "Gebaeude"),
    "gemeindehaus_wing": (2683642.5, 1242059.8, 12.0, "Gebaeude"),
    "cf_meyer_haus":     (2683713.8, 1241441.6, 12.0, "Gebaeude"),
    "cf_meyer_pin_villa":(2683707.4, 1241832.5, 12.0, "Gebaeude"),
    "sanatorium_483":    (2683473.3, 1242413.8, 12.0, "Gebaeude"),
    "sanatorium_633":    (2683535.3, 1242471.8, 12.0, "Gebaeude"),
    "sanatorium_521":    (2683498.8, 1242495.3, 15.0, "Gebaeude"),
    "sanatorium_853":    (2683464.1, 1242487.8, 15.0, "Gebaeude"),
    "sanatorium_655":    (2683486.0, 1242383.9, 12.0, "Gebaeude"),
    "sanatorium_81":     (2683524.0, 1242533.0, 10.0, "Gebaeude"),
    "seebad_bathhouse":  (2684278.7, 1241434.4, 12.0, "Gebaeude"),
    "seebad_kiosk":      (2684265.5, 1241439.3,  8.0, "Gebaeude"),
    "seebad_south":      (2684280.7, 1241400.8, 12.0, "Gebaeude"),
    "seebad_boathouse":  (2684304.0, 1241494.9, 10.0, "Flugdach"),
    "villa_naville_1582":(2684228.2, 1241439.9, 10.0, "Gebaeude"),
    "villa_naville_1695":(2684245.7, 1241450.9, 10.0, "Gebaeude"),
    "schooren_981":      (2684240.5, 1241504.6, 12.0, "Gebaeude"),
    "schooren_1823":     (2684261.0, 1241495.3, 12.0, "Gebaeude"),
    # v9.0 Existing-landmark heritage additions
    "gotisch_hus":              (2683454.0, 1241352.0,  6.0, "Gebaeude"),
    "schulhaus_dorfstr":        (2683792.0, 1241880.0, 12.0, "Gebaeude"),
    "chez_fritz":               (2684224.0, 1241531.0,  6.0, "Gebaeude"),
    "chez_fritz_pavilion":      (2684258.0, 1241534.0,  6.0, "Gebaeude"),
    "sanatorium_gh_225":        (2683466.0, 1242355.0, 10.0, "Treibhaus"),
    "sanatorium_gh_886":        (2683497.0, 1242332.0, 10.0, "Treibhaus"),
    # Landmark 9: Mönchhof & Horn
    "moenchhof_hafenbeiz_243":  (2683570.0, 1243005.0,  3.5, "Gebaeude"),
    "moenchhof_hafenbeiz_843":  (2683567.0, 1242998.0,  3.5, "Gebaeude"),
    "moenchhof_villa_727":      (2683533.0, 1243050.0,  7.0, "Gebaeude"),
    "moenchhof_villa_303":      (2683553.0, 1243022.0,  3.0, "Gebaeude"),
    "moenchhof_villa_527":      (2683557.0, 1243017.0,  3.0, "Gebaeude"),
    "moenchhof_villa_890":      (2683520.0, 1243062.0,  7.0, "Gebaeude"),
    "moenchhof_villa_781":      (2683514.0, 1243078.0,  7.0, "Gebaeude"),
    "moenchhof_boat_25":        (2683590.0, 1243016.0,  3.2, "Gebaeude"),
    "moenchhof_boat_825":       (2683596.0, 1243012.0,  3.2, "Gebaeude"),
    # Landmark 10: Sulzergut Park
    "sulzergut_villa_1617":     (2684458.0, 1241153.0, 12.0, "Gebaeude"),
    "sulzergut_villa_1338":     (2684388.0, 1241118.0, 10.0, "Gebaeude"),
    "sulzergut_boat_1169":      (2684432.0, 1241178.0,  6.0, "Gebaeude"),
    "sulzergut_boat_1550":      (2684420.0, 1241186.0,  6.0, "Gebaeude"),
    "sulzergut_boat_1706":      (2684410.0, 1241174.0,  3.0, "Gebaeude"),
    "sulzergut_boat_984":       (2684408.0, 1241180.0,  3.0, "Gebaeude"),
    # Landmark 11: Gemeindehaus & Schulhaus Alte Landstrasse
    "schulhaus_alteland_868":   (2683635.0, 1242018.0, 12.0, "Gebaeude"),
    "schulhaus_alteland_437":   (2683598.0, 1242028.0, 12.0, "Gebaeude"),
    # Landmark 12: Stockengut Farm
    "stockengut_barn_807":      (2683207.0, 1242037.0, 12.0, "Gebaeude"),
    "stockengut_barn_77":       (2683273.0, 1242006.0,  9.0, "Gebaeude"),
    "stockengut_house_279":     (2683269.0, 1242046.0,  8.0, "Gebaeude"),
    "stockengut_house_574":     (2683267.0, 1242027.0,  8.0, "Gebaeude"),
    "stockengut_outb_473":      (2683192.0, 1242076.0, 10.0, "Gebaeude"),
    "stockengut_outb_1037":     (2683190.0, 1241995.0, 10.0, "Gebaeude"),
    "stockengut_silo_1135":     (2683187.0, 1241976.0,  1.5, "Lagertank"),
    "stockengut_silo_1174":     (2683187.0, 1241974.0,  1.5, "Lagertank"),
    "stockengut_gh_1587":       (2683252.0, 1241998.0, 10.0, "Treibhaus"),
    "stockengut_wall_653":      (2683274.0, 1242016.0, 10.0, "Mauer"),
    "stockengut_mutterkuhstall_91": (2683117.0, 1242039.0, 12.0, "Gebaeude"),
    # Landmark 13: Hallenbad Kilchberg (Hochweidstr. 10 = id 1835) & Sporthalle Hochweid (Hochweidstr. 13/13.1 = 1628/1448)
    "hallenbad_main_1835":      (2683207.0, 1241545.0, 15.0, "Gebaeude"),
    "hallenbad_pool_1448":      (2683112.0, 1241399.0, 12.0, "Gebaeude"),
    "hallenbad_entry_1628":     (2683080.0, 1241431.0, 12.0, "Gebaeude"),
    # Landmark 14: Broelberggut & Tempelchen
    "broelberg_manor_979":      (2683775.0, 1241245.0,  9.0, "Gebaeude"),
    "broelberg_gardener_1678":  (2683756.0, 1241236.0,  6.5, "Gebaeude"),
    "broelberg_outb_1332":      (2683744.0, 1241227.0,  6.5, "Gebaeude"),
    "broelberg_tempelchen_1074":(2683733.0, 1241261.0,  7.0, "Gebaeude"),
    # Landmark 15: Villa Spinnergut & TC Kilchberg
    "spinnergut_villa_1601":    (2683473.0, 1240852.0, 10.0, "Gebaeude"),
    "spinnergut_pav_1132":      (2683471.0, 1240828.0,  8.0, "Gebaeude"),
    "tc_clubhouse_1287":        (2683393.0, 1240918.0, 12.0, "Gebaeude"),
    # Landmark 16: Morfanlage & Lakeside Park
    "morfanlage_boat_42":       (2683867.0, 1242409.0,  3.5, "Gebaeude"),
    "morfanlage_boat_379":      (2683867.0, 1242417.0,  3.5, "Gebaeude"),
    "morfanlage_villa_771":     (2683898.0, 1242314.0,  6.0, "Gebaeude"),
    "morfanlage_villa_423":     (2683902.0, 1242297.0,  7.0, "Gebaeude"),
}


def _resolve_landmark_ids(buildings: list[dict]) -> dict[str, int]:
    """Resolve canonical Kilchberg landmark building indices by LV95 proximity (never fragile hardcoded ints)."""
    out: dict[str, int] = {}
    for key, (te, tn, max_r, obj_pref) in LANDMARK_SPECS.items():
        best_idx = -1
        best_d = max_r
        for b in buildings:
            if obj_pref is not None and not str(b.get("objektart", "")).startswith(obj_pref):
                continue
            d = math.hypot(float(b["e"]) - te, float(b["n"]) - tn)
            if d < best_d:
                best_d = d
                best_idx = int(b["idx"])
        out[key] = best_idx
    return out


@lru_cache(maxsize=4)
def build_90s_palette_and_lut(preset_key: str = "day") -> tuple[np.ndarray, np.ndarray]:
    """Construct a curated per-preset 256-color 90s SVGA hardware CLUT calibrated specifically to
    Day (crisp alpine midday), Sunset (honey-apricot alpenglow + cool violet shadows, zero pink),
    and Night (hushed moonlit Prussian-blue/slate-emerald + 32-color warm sodium-amber lantern ramp)."""
    colors: list[np.ndarray] = []

    def add_ramp(c_dark, c_mid, c_light, n):
        c0 = np.array(c_dark, dtype=np.float32)
        c1 = np.array(c_mid, dtype=np.float32)
        c2 = np.array(c_light, dtype=np.float32)
        for i in range(n):
            t = i / max(1, n - 1)
            if t < 0.5:
                u = t * 2.0
                c = (1.0 - u) * c0 + u * c1
            else:
                u = (t - 0.5) * 2.0
                c = (1.0 - u) * c1 + u * c2
            colors.append(np.clip(np.round(c), 0, 255).astype(np.uint8))

    if preset_key == "sunset":
        # 1. Golden-Hour Sunlit Foliage & Cool-Violet Shaded Woods — 44 colors
        add_ramp((18, 30, 22), (54, 84, 38), (138, 148, 58), 12)
        add_ramp((28, 32, 20), (84, 96, 42), (174, 162, 72), 10)
        add_ramp((12, 22, 30), (26, 54, 50), (62, 98, 74), 9)
        add_ramp((14, 20, 28), (34, 56, 42), (72, 96, 56), 8)
        add_ramp((36, 16, 24), (94, 38, 38), (162, 72, 56), 5)

        # 2. Alpenglow Honey-Apricot Plaster, Cream Stucco & Golden Facades (ZERO pink!) — 52 colors
        add_ramp((66, 64, 82), (184, 154, 132), (252, 216, 174), 13)
        add_ramp((62, 48, 42), (176, 134, 94), (246, 196, 136), 11)
        add_ramp((72, 48, 26), (196, 140, 56), (254, 218, 120), 10)
        add_ramp((26, 26, 46), (68, 66, 94), (126, 120, 148), 10)
        add_ramp((36, 24, 22), (96, 64, 46), (164, 116, 80), 8)

        # 3. Deep Burnt-Terracotta Roofs, Brick, Slate & Dusk Glass — 44 colors
        add_ramp((46, 16, 18), (148, 48, 32), (224, 96, 52), 11)
        add_ramp((58, 24, 18), (178, 76, 42), (242, 132, 72), 10)
        add_ramp((20, 20, 34), (78, 72, 84), (156, 142, 140), 10)
        add_ramp((16, 22, 42), (42, 54, 92), (92, 108, 148), 7)
        add_ramp((22, 36, 40), (58, 88, 82), (118, 144, 126), 6)

        # 4. Twilight Asphalt, Warm Molasse Cutaway & Shadows — 34 colors
        add_ramp((18, 18, 30), (66, 62, 76), (164, 146, 134), 12)
        add_ramp((34, 26, 28), (108, 82, 66), (188, 144, 104), 12)
        add_ramp((20, 18, 38), (48, 36, 64), (94, 60, 72), 10)

        # 5. Sunset Lake Zurich (Deep Indigo-Teal -> Warm Peach-Gold Shimmer) — 46 colors
        add_ramp((10, 18, 36), (24, 48, 74), (46, 82, 102), 14)
        add_ramp((22, 40, 46), (52, 86, 84), (114, 136, 118), 12)
        add_ramp((86, 58, 64), (176, 118, 84), (252, 202, 134), 12)
        add_ramp((28, 68, 94), (72, 136, 154), (198, 214, 206), 8)

        # 6. Warm Dusk Windows, Streetlamp Lanterns & Swiss Crest Red — 36 colors
        add_ramp((94, 48, 18), (226, 146, 46), (255, 238, 162), 18)
        add_ramp((54, 32, 26), (148, 92, 48), (234, 174, 98), 10)
        add_ramp((88, 18, 22), (192, 36, 34), (248, 92, 76), 8)

    elif preset_key == "night":
        # 1. Hushed Moonlit Nocturnal Foliage & Meadows (B > G > R slate-emerald/Prussian-blue, ZERO neon green & ZERO muddy brown!) — 36 colors
        add_ramp((12, 20, 24), (24, 38, 42), (46, 66, 68), 12)
        add_ramp((14, 22, 28), (28, 46, 50), (54, 78, 80), 10)
        add_ramp((10, 16, 24), (20, 32, 42), (38, 56, 66), 8)
        add_ramp((18, 24, 22), (48, 58, 48), (94, 102, 74), 6)

        # 2. Moonlit Swiss Architecture, Slate, Asphalt & Sky — 60 colors
        add_ramp((6, 10, 20), (16, 24, 44), (34, 46, 74), 12)
        add_ramp((22, 28, 46), (66, 78, 108), (134, 148, 182), 13)
        add_ramp((24, 26, 38), (64, 68, 86), (118, 122, 138), 11)
        add_ramp((12, 15, 24), (40, 46, 64), (86, 94, 116), 12)
        add_ramp((22, 12, 18), (58, 32, 36), (104, 58, 54), 12)

        # 3. Lush 32-Color Warm Sodium-Amber / Candle-Gold / Cream-White Glow Ramp — 32 colors
        add_ramp((132, 74, 20), (238, 168, 54), (255, 246, 204), 12)
        add_ramp((82, 42, 16), (194, 114, 38), (252, 202, 102), 10)
        add_ramp((34, 32, 42), (102, 74, 52), (186, 136, 78), 10)

        # 4. Warm Lamp-Lit Brick, Ochre & Wood Accents — 28 colors
        add_ramp((46, 20, 20), (126, 52, 38), (198, 96, 62), 10)
        add_ramp((52, 44, 36), (138, 114, 76), (226, 192, 118), 10)
        add_ramp((64, 14, 18), (176, 34, 34), (248, 88, 78), 8)

        # 5. Deep Sapphire-Silver Lake Zurich, Aquarium & Darkened Pools — 48 colors
        add_ramp((6, 12, 26), (16, 32, 58), (32, 58, 92), 14)
        add_ramp((10, 22, 34), (24, 48, 68), (54, 84, 106), 12)
        add_ramp((48, 66, 96), (104, 126, 158), (184, 202, 226), 10)
        add_ramp((28, 30, 42), (88, 74, 58), (176, 136, 78), 6)
        add_ramp((14, 44, 62), (34, 94, 118), (86, 158, 176), 6)

        # 6. Nocturnal Cutaway Geology, Glass, Warm Spill & Moonlit Highlights — 52 colors
        add_ramp((18, 18, 26), (52, 48, 54), (98, 90, 88), 14)
        add_ramp((12, 18, 34), (34, 50, 78), (76, 102, 138), 12)
        add_ramp((46, 42, 56), (118, 96, 84), (206, 166, 118), 10)
        add_ramp((28, 28, 38), (78, 66, 58), (146, 116, 82), 10)
        add_ramp((142, 154, 178), (194, 204, 222), (242, 246, 252), 6)

    else:
        # Day: v12 crisp cel-shaded 256-color Alpine Midday palette (tinyrj.com inspired)
        # 1. Vibrant Cel-Shaded Foliage, Meadows, Sports Turf & Blossoms — 54 colors
        add_ramp((16, 46, 28), (54, 134, 50), (134, 206, 70), 12)
        add_ramp((24, 56, 30), (74, 152, 58), (164, 218, 86), 11)
        add_ramp((14, 36, 30), (34, 84, 56), (86, 148, 96), 9)
        add_ramp((42, 52, 26), (102, 128, 54), (176, 194, 96), 9)
        add_ramp((38, 18, 28), (92, 40, 48), (150, 72, 74), 6)
        add_ramp((124, 72, 82), (218, 162, 174), (252, 232, 238), 7)

        # 2. Brick, Terracotta Roofs, Clay Courts, Slate/Concrete & PV — 52 colors
        add_ramp((44, 16, 14), (136, 48, 36), (192, 76, 54), 8)
        add_ramp((58, 24, 16), (172, 82, 46), (228, 126, 72), 10)
        add_ramp((42, 28, 20), (118, 78, 54), (186, 138, 102), 8)
        add_ramp((22, 28, 36), (108, 118, 130), (246, 248, 250), 11)
        add_ramp((18, 30, 52), (44, 68, 112), (98, 138, 192), 7)
        add_ramp((50, 46, 40), (144, 136, 122), (214, 206, 190), 8)

        # 3. Swiss Plaster Facades, Warm Sand Sidewalks, Ochre, Sage & Cool Blue-Slate Glass — 50 colors
        add_ramp((58, 64, 76), (168, 166, 158), (252, 249, 240), 10)
        add_ramp((62, 52, 40), (172, 156, 128), (240, 226, 194), 9)
        add_ramp((64, 48, 22), (182, 152, 68), (250, 226, 118), 9)
        add_ramp((58, 36, 34), (154, 110, 96), (222, 180, 162), 7)
        add_ramp((26, 48, 42), (76, 126, 108), (160, 196, 174), 7)
        add_ramp((20, 32, 48), (54, 86, 126), (126, 166, 214), 8)

        # 4. Streets, Cool Blue-Slate Asphalt, Ballast & Molasse Geology — 34 colors
        add_ramp((20, 26, 34), (92, 102, 114), (204, 210, 218), 14)
        add_ramp((36, 32, 28), (108, 96, 80), (192, 176, 152), 12)
        add_ramp((26, 22, 22), (76, 58, 44), (138, 120, 96), 8)

        # 5. Lake Zurich Water, Shallows, Pebble Caustics, Foam & Pools — 46 colors
        add_ramp((10, 24, 38), (24, 62, 86), (46, 104, 120), 14)
        add_ramp((26, 52, 48), (58, 112, 98), (126, 182, 164), 14)
        add_ramp((30, 104, 138), (72, 188, 218), (224, 246, 248), 12)
        add_ramp((16, 24, 40), (28, 40, 62), (46, 62, 88), 6)

        # 6. Accents: Swiss Crest Red, Lantern Gold & Harbor Wood — 20 colors
        add_ramp((96, 20, 20), (198, 38, 38), (248, 96, 88), 10)
        add_ramp((92, 62, 22), (206, 154, 58), (254, 234, 154), 10)

    assert len(colors) == 256, f"Expected 256 palette colors for {preset_key}, got {len(colors)}"
    pal = np.array(colors, dtype=np.uint8)

    grid = np.linspace(0, 255, 64, dtype=np.float32)
    rg, gg, bg = np.meshgrid(grid, grid, grid, indexing="ij")
    pts = np.stack([rg.ravel(), gg.ravel(), bg.ravel()], axis=1)
    pal_f = pal.astype(np.float32)

    lut = np.empty(len(pts), dtype=np.uint8)
    STEP = 16384
    for i in range(0, len(pts), STEP):
        sub = pts[i : i + STEP, None, :]
        diff = sub - pal_f[None, :, :]
        dist2 = 2.2 * (diff[:, :, 0] ** 2) + 3.8 * (diff[:, :, 1] ** 2) + 2.5 * (diff[:, :, 2] ** 2)
        lut[i : i + STEP] = np.argmin(dist2, axis=1).astype(np.uint8)

    return pal, lut.reshape((64, 64, 64))


def quantize_to_90s_palette(
    rgb_float: np.ndarray,
    bayer_2d: np.ndarray,
    strength: float,
    preset_key: str = "day",
) -> np.ndarray:
    """Apply ordered 4x4 Bayer dithering and quantize strictly into the curated per-preset 256-color SVGA CLUT."""
    pal, lut = build_90s_palette_and_lut(preset_key)
    H_q, W_q, _ = rgb_float.shape
    out = np.empty((H_q, W_q, 3), dtype=np.uint8)
    s_fac = np.float32(63.0 / 255.0)
    step = 512
    for y0 in range(0, H_q, step):
        y1 = min(H_q, y0 + step)
        dithered = np.clip(rgb_float[y0:y1] + bayer_2d[y0:y1, :, None] * strength, 0.0, 255.0)
        ri = np.round(dithered[:, :, 0] * s_fac).astype(np.int32)
        gi = np.round(dithered[:, :, 1] * s_fac).astype(np.int32)
        bi = np.round(dithered[:, :, 2] * s_fac).astype(np.int32)
        out[y0:y1] = pal[lut[ri, gi, bi]]
    return out


class SceneData:
    """Loaded Kilchberg 0.5m rasters, 3D bridges/viaducts, 25cm parapet masks, 3D LOD2 buildings, sports & trees."""

    def __init__(self, cache_dir: Path = RAW_CACHE_DIR):
        import gc

        s = np.load(cache_dir / "scene_kilchberg_05m.npz")
        self.dem = s["dem"].astype(np.float32)
        self.chm = s["chm"].astype(np.float32)
        ortho_05m = s["ortho"]
        self.sem = s["sem"]
        self.diorama_mask = s["diorama_mask"]
        self.kpoly_mask = s["kpoly_mask"]
        self.lake_mask = s["lake_mask"]
        self.bathy_z = s["bathy_z"].astype(np.float32)

        # V3 vector road/rail/bridge/tree layers (bounded distance/width/angle fields stored as float16 -> saves ~750 MB!)
        self.rail_dist = s["rail_dist"].astype(np.float16)
        self.rail_along = s["rail_along"].astype(np.float32)
        self.road_dist = s["road_dist"].astype(np.float16)
        self.road_along = s["road_along"].astype(np.float32)
        self.road_hw = s["road_hw"].astype(np.float16)
        self.crosswalk_mask = s["crosswalk_mask"] > 0

        self.bridge_cls = s["bridge_cls"]
        self.bridge_z = s["bridge_z"].astype(np.float32)
        self.bridge_sdist = s["bridge_sdist"].astype(np.float16)
        self.bridge_along = s["bridge_along"].astype(np.float32)
        self.bridge_hw = s["bridge_hw"].astype(np.float16)
        self.bridge_ang = s["bridge_ang"].astype(np.float16)
        self.bridge_id = s["bridge_id"]
        self.hedge_mask = s["hedge_mask"] > 0

        # F14: Surface hillside stone staircases (M1 additive keys)
        self.steps_mask = (s["steps_mask"] > 0) if "steps_mask" in s else np.zeros((GRID_H, GRID_W), dtype=np.bool_)
        self.steps_dist = s["steps_dist"].astype(np.float16) if "steps_dist" in s else np.zeros((GRID_H, GRID_W), dtype=np.float16)
        self.steps_ang = s["steps_ang"].astype(np.float16) if "steps_ang" in s else np.zeros((GRID_H, GRID_W), dtype=np.float16)

        self.tree_e = s["tree_e"].astype(np.float32)
        self.tree_n = s["tree_n"].astype(np.float32)
        self.tree_z = s["tree_z"].astype(np.float32)
        self.tree_h = s["tree_h"].astype(np.float32)
        self.tree_rad = s["tree_rad"].astype(np.float32)
        self.tree_species = s["tree_species"].astype(np.uint8)
        s.close()
        del s

        # F14a + v10 + v13 M1B Iter2: Per-tree lake distance, strict dry-land guardrail & smooth shoreline SDF
        dist_lake_05m = ndimage.distance_transform_edt(~self.lake_mask).astype(np.float32) * GRID_RES
        tc_t = np.clip(((self.tree_e - E_MIN) / GRID_RES).astype(np.int32), 0, GRID_W - 1)
        tr_t = np.clip(((N_MAX - self.tree_n) / GRID_RES).astype(np.int32), 0, GRID_H - 1)
        self.tree_dist_lake = dist_lake_05m[tr_t, tc_t].astype(np.float32)
        del dist_lake_05m
        # v13 M1B Iter2: Strict global-LV95 dry-land guardrail (ZERO trees half-submerged in Lake Zurich!)
        dry_land_ok = (~self.lake_mask[tr_t, tc_t]) & (self.tree_dist_lake >= 1.50)
        self.tree_e = self.tree_e[dry_land_ok]
        self.tree_n = self.tree_n[dry_land_ok]
        self.tree_z = self.tree_z[dry_land_ok]
        self.tree_h = self.tree_h[dry_land_ok]
        self.tree_rad = self.tree_rad[dry_land_ok]
        self.tree_species = self.tree_species[dry_land_ok]
        self.tree_dist_lake = self.tree_dist_lake[dry_land_ok]
        tr_t = tr_t[dry_land_ok]
        tc_t = tc_t[dry_land_ok]
        del dry_land_ok
        self.dist_shore_05m = (ndimage.distance_transform_edt(self.lake_mask).astype(np.float32) * GRID_RES).astype(np.float16)
        # v13 M1B Iter2: Smooth world-space shoreline SDF (eliminates 0.5m staircase shore edge globally, 0 seams!)
        self.lake_sdf_05m = ndimage.gaussian_filter(
            self.lake_mask.astype(np.float32), sigma=0.95
        ).astype(np.float16)

        # v13.0: Deterministic geographic 8-species Swiss/Zürichsee botanical assignment (ZERO cache rebuild!)
        # 0: Swiss Oak/Beech, 1: Alpine Spruce/Fir, 2: Silver Birch, 3: Lakeside Weeping Willow,
        # 4: Lombardy Poplar/Cypress, 5: Blossoming Orchard/Cherry, 6: Copper Beech, 7: Swiss Linden/Maple
        self.tree_sem = self.sem[tr_t, tc_t]
        self.tree_road_dist = self.road_dist[tr_t, tc_t].astype(np.float32)
        n_trees_v13 = len(self.tree_e)
        tid_arr = np.arange(n_trees_v13, dtype=np.uint32)
        gx15 = np.floor(self.tree_e / 15.0).astype(np.int64).astype(np.uint32)
        gy15 = np.floor(self.tree_n / 15.0).astype(np.int64).astype(np.uint32)
        h_grove = ((gx15 * np.uint32(73856093)) ^ (gy15 * np.uint32(19349663)) ^ np.uint32(0x9E3779B9)) & np.uint32(0xFFFF)
        h_tree = ((tid_arr * np.uint32(2654435761)) ^ (gx15 * np.uint32(83492791)) ^ np.uint32(0x5A3C)) & np.uint32(0xFFFF)
        u_grove = (h_grove % 1000).astype(np.float32) / 1000.0
        u_tree = (h_tree % 1000).astype(np.float32) / 1000.0
        u_mix = (0.65 * u_grove + 0.35 * u_tree) % 1.0

        sp_orig = self.tree_species
        is_forest_t = self.tree_sem == G_FOREST
        is_park_t = self.tree_sem == G_PARK_CEMETERY
        in_morfanlage_t = (
            (self.tree_e >= 2683870.0) & (self.tree_e <= 2683920.0)
            & (self.tree_n >= 1242334.0) & (self.tree_n <= 1242402.0)
        )
        in_stockengut_t = (
            (self.tree_e >= 2683150.0) & (self.tree_e <= 2683520.0)
            & (self.tree_n >= 1241930.0) & (self.tree_n <= 1242140.0)
        )
        in_kirche_cem_t = (
            (self.tree_e >= 2683375.0) & (self.tree_e <= 2683500.0)
            & (self.tree_n >= 1241053.0) & (self.tree_n <= 1241314.0)
        )

        # Base broadleaf split: 0 (Swiss Oak/Beech) vs 7 (Swiss Linden/Maple)
        sp13 = np.where(
            is_forest_t | (self.tree_rad >= 2.55) | (self.tree_h >= 9.0) | (u_mix < 0.56),
            0,
            7,
        ).astype(np.uint8)
        is_linden_cand = (~is_forest_t) & (sp_orig <= 1) & (self.tree_road_dist < 9.0) & (u_mix >= 0.42)
        sp13[is_linden_cand] = 7

        # 1: Alpine Spruce / Silver Fir (all sp==2 + forest enrichment + upper ridge)
        is_spruce_t = (
            (sp_orig == 2)
            | (is_forest_t & (u_mix < 0.38))
            | ((self.tree_z >= 492.0) & (self.tree_h >= 7.0) & ((h_tree % 5) == 0))
        )
        sp13[is_spruce_t] = 1

        # 2: Silver Birch (lakeside, parks, and medium residential sp==1)
        is_birch_t = (
            (~is_spruce_t)
            & (~is_forest_t)
            & (
                ((self.tree_dist_lake < 65.0) & (u_mix < 0.32))
                | (is_park_t & (u_mix >= 0.55) & (u_mix < 0.76))
                | ((sp_orig == 1) & (self.tree_h >= 4.0) & (self.tree_h <= 13.5) & (u_mix < 0.36))
            )
        )
        sp13[is_birch_t] = 2

        # 3: Lakeside Weeping Willow (dry lakeside park embankment: 2.2m <= dist_lake < 32m, broadleaf, h >= 4.5m)
        is_willow_t = (
            (self.tree_dist_lake >= 2.20)
            & (self.tree_dist_lake < 32.0)
            & (sp_orig <= 1)
            & (self.tree_h >= 4.5)
            & (((h_grove ^ h_tree) % 100) < 32)
        )
        sp13[is_willow_t] = 3

        # 4: Lombardy Poplar / Mediterranean Cypress
        is_cypress_t = (
            (sp_orig == 3)
            | (in_kirche_cem_t & (sp_orig <= 1) & ((h_tree % 6) == 0))
            | ((~is_forest_t) & (self.tree_road_dist < 8.0) & (self.tree_h >= 8.0) & ((h_tree % 18) == 0))
        )
        sp13[is_cypress_t] = 4

        # 5: Blossoming Orchard / Cherry / Magnolia (NEVER in Morfanlage or forest; enriched at Stockengut)
        is_blossom_t = (
            (~is_forest_t)
            & (~in_morfanlage_t)
            & (self.tree_h >= 3.0)
            & (self.tree_h <= 9.5)
            & (
                (sp_orig == 5)
                | (in_stockengut_t & (sp_orig <= 1) & ((h_tree % 100) < 28))
                | ((~in_stockengut_t) & (sp_orig <= 1) & (self.tree_dist_lake >= 32.0) & ((h_tree % 100) < 5))
            )
        )
        sp13[is_blossom_t] = 5

        # 6: Copper Beech (Blutbuche) — stately estate/park specimens, never Morfanlage
        is_copper_t = (
            (~is_forest_t)
            & (~in_morfanlage_t)
            & (
                (sp_orig == 4)
                | ((is_park_t | (self.tree_h >= 13.0)) & (sp_orig <= 1) & ((h_tree % 140) == 0))
            )
        )
        sp13[is_copper_t] = 6
        self.tree_species_v13 = sp13

        ortho10_p = cache_dir / "ortho_10cm.npy"
        if ortho10_p.exists():
            self.ortho_hr = np.load(ortho10_p, mmap_mode="r")
            self.ortho_res = ORTHO10_RES
            self.ortho_w = ORTHO10_W
            self.ortho_h = ORTHO10_H
        else:
            self.ortho_hr = np.load(cache_dir / "ortho_25cm.npy", mmap_mode="r")
            self.ortho_res = ORTHO25_RES
            self.ortho_w = ORTHO25_W
            self.ortho_h = ORTHO25_H
        self.ortho_25cm = self.ortho_hr
        self.roof_edge_25cm = np.load(cache_dir / "roof_edge_step_25cm.npy", mmap_mode="r")
        raw_rmask = np.load(cache_dir / "bldg_roof_mask_05m.npy")
        self.bldg_roof_mask = ndimage.binary_dilation(raw_rmask, iterations=2)

        b = np.load(cache_dir / "buildings_kilchberg_3d.npz")
        self.verts = b["verts"]
        self.normals = b["normals"]
        self.bldg_idx = b["bldg_idx"]
        self.surf_type = b["surf_type"]
        b.close()
        del b

        meta = json.loads((cache_dir / "buildings_kilchberg_meta.json").read_text())
        self.buildings = meta["buildings"]
        self.boats = meta["boats"]
        self.viaduct_piers = meta.get("viaduct_piers", [])
        self.catenary_portals = meta.get("catenary_portals", [])
        self.sports_fields = meta.get("sports_fields", [])
        self.sports_enclosures = meta.get("sports_enclosures", [])

        # F13: Canonical LV95 proximity-resolved landmark building IDs
        self.lm_idx = _resolve_landmark_ids(self.buildings)

        # v12-M1C Fix 2: Smooth residential lawn/park/forest DEM with C1 distance feathering away from
        # hard/protected infrastructure & Lake Zurich shoreline (0.000 m diff on roads/sidewalks/rails/
        # bridges/shoreline, 0 extra permanent RAM, 100% macro-tile seam-free!).
        _prot_dem = (
            np.isin(
                self.sem,
                [
                    G_STREET_MAIN, G_STREET_MINOR, G_MOTORWAY,
                    G_FOOTPATH, G_PARKING, G_RAILWAY, G_PLATFORM_PIER,
                    G_STREAM, G_POOL, G_PITCH, G_VINEYARD,
                ],
            )
            | (self.road_dist <= (self.road_hw + np.float16(0.5)))
            | (self.bridge_cls > 0)
            | self.steps_mask
            | ndimage.binary_dilation(self.lake_mask, iterations=5)  # 2.5 m shoreline buffer
        )
        _dist_prot = ndimage.distance_transform_edt(~_prot_dem).astype(np.float32) * GRID_RES
        _w_sm = np.clip((_dist_prot - 0.5) / 3.5, 0.0, 1.0)
        del _prot_dem, _dist_prot
        _w_sm *= _w_sm * (3.0 - 2.0 * _w_sm)  # C1 Hermite smoothstep: zero curb/shoreline crease!
        _dem_g = ndimage.gaussian_filter(self.dem, sigma=3.5)
        self.dem += _w_sm * np.clip(_dem_g - self.dem, -1.5, 1.5)
        del _w_sm, _dem_g
        # Re-snap land tree bases to smoothed lawn DEM so zero tree trunks float or sink
        _land_t = ~self.lake_mask[tr_t, tc_t]
        self.tree_z = np.where(_land_t, self.dem[tr_t, tc_t], self.tree_z).astype(np.float32)
        del _land_t

        # Precompute 0.5m bare-earth terrain normals (v12-M1C: sigma=2.2 yields silky TinyRJ cel-shaded lawn slopes!)
        dem_sm = ndimage.gaussian_filter(self.dem, sigma=2.2)
        dz_drow, dz_dcol = np.gradient(dem_sm, GRID_RES)
        del dem_sm
        nlen = np.sqrt(dz_dcol * dz_dcol + dz_drow * dz_drow + 1.0)
        self.terr_nx = (-dz_dcol / nlen).astype(np.float16)
        self.terr_ny = (dz_drow / nlen).astype(np.float16)
        self.terr_nz = (1.0 / nlen).astype(np.float16)
        del dz_drow, dz_dcol, nlen

        # v12 Iter2: Retained smoothed bare-earth DEM for wobble-free paved roads, sidewalks, footpaths, parking & platforms
        self.dem_smooth_05m = ndimage.gaussian_filter(self.dem, sigma=1.6).astype(np.float32)

        # v12: Sustained steep cliff mask (morphologically opened s_nz < 0.64 -> kills jagged grassy roadside streaks!)
        raw_cliff = (self.terr_nz < 0.64) & (~self.lake_mask)
        self.steep_cliff_05m = ndimage.binary_opening(raw_cliff, structure=np.ones((3, 3), dtype=bool))
        del raw_cliff

        # v12: Pre-smoothed 0.5m ortho for denoised non-HoC building roofs (frees temporary float32 per channel)
        self.ortho_roof_smooth_05m = np.empty_like(ortho_05m)
        for _ch in range(3):
            _sm_c = ndimage.gaussian_filter(ortho_05m[:, :, _ch].astype(np.float32), sigma=1.6)
            self.ortho_roof_smooth_05m[:, :, _ch] = np.clip(np.round(_sm_c), 0.0, 255.0).astype(np.uint8)
            del _sm_c

        # (v13 M1B Iter2: self.hedge_edt_05m is computed below after systemic bush/path clearance)

        # V6.0/v12: Multi-scale smooth organic alpine meadow variation field (bilinear zoom -> zero 2x2m square steps!)
        rng_m = np.random.default_rng(1350135)
        raw_n = rng_m.standard_normal((GRID_H // 4 + 2, GRID_W // 4 + 2)).astype(np.float32)
        coarse_n = ndimage.gaussian_filter(raw_n, sigma=6.5)
        med_n = ndimage.gaussian_filter(raw_n, sigma=2.0)
        comb_n = 0.65 * coarse_n + 0.35 * med_n
        comb_n = (comb_n - comb_n.mean()) / max(1e-5, comb_n.std())
        self.meadow_noise_05m = ndimage.zoom(comb_n, 4.0, order=1)[:GRID_H, :GRID_W].astype(np.float16)
        del raw_n, coarse_n, med_n, comb_n

        # V6.0/v12: Clean impervious residential courtyard / patio / driveway mask (0.5m) + SDF smoothing
        o_r = ortho_05m[:, :, 0].astype(np.float32)
        o_g = ortho_05m[:, :, 1].astype(np.float32)
        o_b = ortho_05m[:, :, 2].astype(np.float32)
        lum05 = 0.299 * o_r + 0.587 * o_g + 0.114 * o_b
        chroma05 = np.maximum(np.maximum(o_r, o_g), o_b) - np.minimum(np.minimum(o_r, o_g), o_b)
        green_excess05 = o_g - 0.5 * (o_r + o_b)
        near_urban = ndimage.binary_dilation(
            raw_rmask | np.isin(self.sem, [G_STREET_MAIN, G_STREET_MINOR, G_PARKING, G_PLATFORM_PIER]),
            iterations=14,
        )
        raw_pave = (
            near_urban
            & (self.sem == G_TERRAIN)
            & (~self.lake_mask)
            & (lum05 > 142.0)
            & (chroma05 < 20.0)
            & (green_excess05 < 2.5)
        )
        self.yard_pave_mask_05m = ndimage.binary_closing(
            ndimage.binary_opening(raw_pave, structure=np.ones((2, 2), dtype=bool)),
            structure=np.ones((3, 3), dtype=bool),
        )
        self.yard_pave_sdf_05m = ndimage.gaussian_filter(self.yard_pave_mask_05m.astype(np.float32), sigma=1.2).astype(np.float16)
        del near_urban, raw_pave, green_excess05

        # v12 Iter2: World-space SDF masks for smooth footpaths, parking lots, platforms, crosswalks & park gravel
        raw_pg = (
            (self.sem == G_PARK_CEMETERY)
            & (~self.lake_mask)
            & (lum05 > 128.0)
            & ((o_g - o_b) < 9.0)
            & (chroma05 < 20.0)
        )
        clean_pg = ndimage.binary_closing(
            ndimage.binary_opening(raw_pg, structure=np.ones((2, 2), dtype=bool)),
            structure=np.ones((3, 3), dtype=bool),
        )
        self.park_gravel_sdf_05m = ndimage.gaussian_filter(clean_pg.astype(np.float32), sigma=1.1).astype(np.float16)
        del raw_pg, clean_pg

        # v13 M1B Iter2: Bendlikon Pier shore abutment — convert land G_PLATFORM_PIER into G_FOOTPATH (kills grey concrete blob!)
        _e05_row = E_MIN + (np.arange(GRID_W, dtype=np.float32) + 0.5) * GRID_RES
        _n05_col = N_MAX - (np.arange(GRID_H, dtype=np.float32) + 0.5) * GRID_RES
        _bend_gang_r = (_n05_col >= 1242064.0) & (_n05_col <= 1242076.0)
        _bend_gang_c = (_e05_row >= 2684034.0) & (_e05_row <= 2684056.5)
        _bend_gang_box = np.outer(_bend_gang_r, _bend_gang_c)
        self.sem[_bend_gang_box & (~self.lake_mask) & (self.sem == G_PLATFORM_PIER)] = G_FOOTPATH

        self.crosswalk_sdf_05m = ndimage.gaussian_filter(self.crosswalk_mask.astype(np.float32), sigma=0.85).astype(np.float16)
        self.footpath_sdf_05m = ndimage.gaussian_filter((self.sem == G_FOOTPATH).astype(np.float32), sigma=1.1).astype(np.float16)
        self.parking_sdf_05m = ndimage.gaussian_filter((self.sem == G_PARKING).astype(np.float32), sigma=1.2).astype(np.float16)
        self.platform_sdf_05m = ndimage.gaussian_filter(((self.sem == G_PLATFORM_PIER) & (~self.lake_mask)).astype(np.float32), sigma=1.0).astype(np.float16)

        is_pool_m = self.sem == G_POOL
        self.pool_rim_05m = ndimage.binary_dilation(is_pool_m, iterations=1) & (~is_pool_m) & (~self.lake_mask)
        del is_pool_m

        # V6.0: Glitch-free 0.5m rooftop Solar PV mask
        raw_pv05 = (
            raw_rmask
            & (o_b > (o_r + 19.0))
            & (o_b > (o_g + 8.0))
            & (lum05 >= 38.0)
            & (lum05 <= 108.0)
        )
        opened_pv = ndimage.binary_opening(raw_pv05, structure=np.ones((3, 3), dtype=bool))
        lbl_pv, n_pv = ndimage.label(opened_pv)
        if n_pv > 0:
            pv_counts = np.bincount(lbl_pv.ravel())
            keep_pv = pv_counts >= 14
            keep_pv[0] = False
            self.pv_clean_05m = ndimage.binary_closing(keep_pv[lbl_pv], structure=np.ones((2, 2), dtype=bool))
        else:
            self.pv_clean_05m = np.zeros((GRID_H, GRID_W), dtype=np.bool_)
        del raw_rmask, raw_pv05, opened_pv, lbl_pv

        # Clean 0.5m mask of REAL piers & Seebad jetties (v13 M1B: remove noisy point-splat LiDAR moored boats!)
        near_shore = ndimage.binary_dilation(~self.lake_mask, iterations=190)
        open_water = ndimage.binary_erosion(self.lake_mask, iterations=1, border_value=0)
        is_pier = (self.sem == G_PLATFORM_PIER) & self.lake_mask
        rb_diff05 = o_r - o_b
        is_lidar_pier = (
            open_water
            & near_shore
            & (~self.bldg_roof_mask)
            & (self.bathy_z <= (LAKE_SURFACE_Z - 0.50))
            & (self.chm >= 0.45)
            & (self.chm <= 1.38)
            & (lum05 > 112.0)
            & (chroma05 < 16.0)
            & (rb_diff05 <= 10.0)
            & ((o_g - o_r) < 6.0)
        )
        del o_r, o_g, o_b, lum05, chroma05, rb_diff05, near_shore, open_water
        clean_pier = np.zeros_like(is_lidar_pier)
        lbl_p, n_p = ndimage.label(is_lidar_pier & (~is_pier))
        if n_p > 0:
            cnt_p = np.bincount(lbl_p.ravel())
            keep_p = (cnt_p >= 24) & (cnt_p <= 1200)
            keep_p[0] = False
            clean_pier = ndimage.binary_closing(
                keep_p[lbl_p], structure=np.ones((3, 3), dtype=bool)
            ) & self.lake_mask & (~self.bldg_roof_mask)
        del is_lidar_pier, lbl_p
        self.pier_only_mask_05m = (is_pier | clean_pier) & (~_bend_gang_box)
        self.harbor_obj_mask = self.pier_only_mask_05m
        del is_pier, clean_pier, _bend_gang_box, _bend_gang_r, _bend_gang_c, _e05_row, _n05_col

        # v13 M1B Iter2: Systemic bush/hedge clearance from paved paths, roads, plazas, parking & pier approaches
        _paved_clear_base = (
            np.isin(
                self.sem,
                [
                    G_FOOTPATH, G_STREET_MINOR, G_STREET_MAIN, G_MOTORWAY,
                    G_PARKING, G_PLATFORM_PIER, G_RAILWAY, G_POOL, G_PITCH,
                ],
            )
            | (self.road_dist <= (self.road_hw + np.float16(0.5)))
            | self.lake_mask
            | self.pier_only_mask_05m
        )
        _paved_buf_05m = ndimage.binary_dilation(_paved_clear_base, iterations=1)
        _path_pier_buf = ndimage.binary_dilation(
            np.isin(self.sem, [G_FOOTPATH, G_PLATFORM_PIER]) | self.pier_only_mask_05m,
            iterations=2,  # 1.0 m clearance around footpaths & pier/gangway entrances
        )
        _pier_entry_buf = ndimage.binary_dilation(
            (self.sem == G_PLATFORM_PIER) | self.pier_only_mask_05m,
            iterations=3,  # 1.5 m clearance right at pier/gangway approaches
        )
        self.hedge_mask = (
            self.hedge_mask
            & (~_paved_buf_05m)
            & (~_path_pier_buf)
            & (~_pier_entry_buf)
            & (~self.yard_pave_mask_05m)
        )
        # Remove tiny orphan 1-3 cell fragments clipped at path edges so borders stay clean & sculpted
        _lbl_h, _n_h = ndimage.label(self.hedge_mask)
        if _n_h > 0:
            _cnt_h = np.bincount(_lbl_h.ravel())
            _keep_h = _cnt_h >= 4
            _keep_h[0] = False
            self.hedge_mask = _keep_h[_lbl_h]
        del _paved_clear_base, _paved_buf_05m, _path_pier_buf, _pier_entry_buf, _lbl_h
        self.hedge_edt_05m = (
            ndimage.distance_transform_edt(self.hedge_mask).astype(np.float32) * GRID_RES
        ).astype(np.float16)

        # World-space smooth pier SDF & flat per-pier deck height (100% macro-tile seam-safe!)
        self.pier_sdf_05m = ndimage.gaussian_filter(
            self.pier_only_mask_05m.astype(np.float32), sigma=0.75
        ).astype(np.float16)
        pier_h = np.full((GRID_H, GRID_W), 0.88, dtype=np.float32)
        lbl_ph, n_ph = ndimage.label(self.pier_only_mask_05m)
        if n_ph > 0:
            for k_ph in range(1, n_ph + 1):
                mk_ph = lbl_ph == k_ph
                med_h = float(np.clip(np.median(self.chm[mk_ph]), 0.78, 1.12))
                pier_h[mk_ph] = med_h
        # Propagate flat deck height 1 cell into SDF fringe so bilinearly expanded pier edges stay flat
        pier_h_dil = ndimage.maximum_filter(np.where(self.pier_only_mask_05m, pier_h, 0.0), size=3)
        fringe_ph = (~self.pier_only_mask_05m) & (self.pier_sdf_05m >= 0.35) & (pier_h_dil > 0.1)
        pier_h[fringe_ph] = pier_h_dil[fringe_ph]
        self.pier_deck_h_05m = pier_h.astype(np.float16)
        del pier_h, pier_h_dil, fringe_ph, lbl_ph

        # F9: Crisp 1-2px organic shore & pier foam rings (strictly shoreline + real piers, zero removed boats!)
        foam_base = (~self.lake_mask) | self.pier_only_mask_05m
        self.foam_ring1_05m = self.lake_mask & (~self.pier_only_mask_05m) & ndimage.binary_dilation(foam_base, iterations=1)
        self.foam_ring2_05m = (
            self.lake_mask
            & (~self.pier_only_mask_05m)
            & (~self.foam_ring1_05m)
            & ndimage.binary_dilation(foam_base, iterations=3)
        )
        del foam_base
        gc.collect()

        # Precompute per-building 3D pitched-roof geometry, eave height, and clean de-shadowed roof RGB
        nb = len(self.buildings)
        rm = self.surf_type == 1
        r_bidx = self.bldg_idx[rm]
        r_norms = self.normals[rm]
        r_verts = self.verts[rm]

        tot_rtri = np.bincount(r_bidx, minlength=nb)
        pit_rtri = np.bincount(r_bidx[r_norms[:, 2] < 0.93], minlength=nb)
        self.bldg_is_pitched = (pit_rtri / np.maximum(1, tot_rtri)) >= 0.18

        self.bldg_eave_z = np.array([b_item["z_roof"] for b_item in self.buildings], dtype=np.float32)
        self.bldg_sunlit_roof_rgb = np.array([b_item["roof_rgb"] for b_item in self.buildings], dtype=np.float32)

        rcent = r_verts.mean(axis=1)
        rcols = np.clip(((rcent[:, 0] - E_MIN) * (1.0 / GRID_RES)).astype(np.int32), 0, GRID_W - 1)
        rrows = np.clip(((N_MAX - rcent[:, 1]) * (1.0 / GRID_RES)).astype(np.int32), 0, GRID_H - 1)
        rgb_tri = np.asarray(ortho_05m[rrows, rcols], dtype=np.float32)
        dot_ortho = r_norms[:, 0] * 0.25 - r_norms[:, 1] * 0.76 + r_norms[:, 2] * 0.60
        lum_tri = 0.299 * rgb_tri[:, 0] + 0.587 * rgb_tri[:, 1] + 0.114 * rgb_tri[:, 2]
        r_zmin = r_verts[:, :, 2].min(axis=1)

        s_ord = np.argsort(r_bidx, kind="mergesort")
        s_bidx = r_bidx[s_ord]
        s_rgb = rgb_tri[s_ord]
        s_dot = dot_ortho[s_ord]
        s_lum = lum_tri[s_ord]
        s_zmin = r_zmin[s_ord]
        uniq_b, idx_start, counts_b = np.unique(s_bidx, return_index=True, return_counts=True)
        for bi_u, st_u, cnt_u in zip(uniq_b, idx_start, counts_b):
            sl = slice(st_u, st_u + cnt_u)
            self.bldg_eave_z[bi_u] = float(np.percentile(s_zmin[sl], 22))
            vals = s_rgb[sl]
            ds = s_dot[sl]
            lm = s_lum[sl]
            not_leaf = (vals[:, 1] - vals[:, 0]) <= 8.0
            good = (ds > 0.22) & (lm > 48.0) & (lm < 236.0) & not_leaf
            if good.sum() >= max(1, int(0.18 * cnt_u)):
                self.bldg_sunlit_roof_rgb[bi_u] = np.percentile(vals[good], 64, axis=0)
            elif ((ds > 0.22) & (lm > 44.0)).any():
                self.bldg_sunlit_roof_rgb[bi_u] = np.percentile(vals[(ds > 0.22) & (lm > 44.0)], 66, axis=0)
            elif (lm > 42.0).any():
                self.bldg_sunlit_roof_rgb[bi_u] = np.percentile(vals[lm > 42.0], 68, axis=0)

        # Clean up & stylize per-building roof base RGB into jewel-like 90s pixel-art Swiss roof materials
        self.bldg_clean_roof_rgb = np.empty((nb, 3), dtype=np.float32)
        self.bldg_roof_kind = np.zeros(nb, dtype=np.uint8)  # 0=clay_tile, 1=dark_slate, 2=flat_gravel, 3=flat_green, 4=metal
        for i in range(nb):
            rr, rg, rb = self.bldg_sunlit_roof_rgb[i]
            lum_r = 0.299 * rr + 0.587 * rg + 0.114 * rb
            is_pit = bool(self.bldg_is_pitched[i])
            if is_pit:
                if (rr - rb) >= 15.0 and rr >= 98.0:
                    warm = min(1.0, max(0.0, (rr - rg) / 34.0))
                    c_tile = np.array([162.0 + 30.0 * warm, 82.0 + 8.0 * warm, 56.0 - 4.0 * warm], dtype=np.float32)
                    self.bldg_clean_roof_rgb[i] = 0.65 * c_tile + 0.35 * np.clip([rr * 1.08, rg * 0.96, rb * 0.88], 48.0, 214.0)
                    self.bldg_roof_kind[i] = 0
                elif (rr - rb) >= 7.0:
                    c_brn = np.array([136.0, 92.0, 68.0], dtype=np.float32)
                    self.bldg_clean_roof_rgb[i] = 0.55 * c_brn + 0.45 * np.clip([rr * 1.04, rg * 0.96, rb * 0.90], 72.0, 184.0)
                    self.bldg_roof_kind[i] = 0
                else:
                    base_sl = np.clip(lum_r * 0.94, 70.0, 138.0)
                    self.bldg_clean_roof_rgb[i] = [base_sl * 0.99, base_sl * 1.00, base_sl * 1.02]
                    self.bldg_roof_kind[i] = 1
            else:
                if (rg - rr) > 7.0 and (rg - rb) > 9.0:
                    self.bldg_clean_roof_rgb[i] = [106.0, 138.0, 74.0]
                    self.bldg_roof_kind[i] = 3
                elif lum_r > 158.0:
                    v_l = np.clip(lum_r, 158.0, 198.0)
                    self.bldg_clean_roof_rgb[i] = [v_l, v_l * 0.995, v_l * 0.985]
                    self.bldg_roof_kind[i] = 4
                else:
                    v_g = np.clip(lum_r * 1.04, 114.0, 168.0)
                    self.bldg_clean_roof_rgb[i] = [v_g * 1.02, v_g * 1.00, v_g * 0.97]
                    self.bldg_roof_kind[i] = 2

        # F11: Vectorized 4-point per-triangle pitched-roof aerial shadow de-biasing!
        # Lifts shadowed north slopes up toward their building's sunlit reference luminance while preserving
        # 100% of 25cm dormers/Velux/tiles & strictly exempting Lindt HoC and green roofs.
        self.tri_roof_lum_gain = np.ones(len(self.verts), dtype=np.float32)
        self.tri_roof_warm_shift = np.zeros(len(self.verts), dtype=np.float32)
        pit_tri_idx = np.nonzero((self.surf_type == 1) & (self.normals[:, 2] < 0.93))[0]
        if len(pit_tri_idx) > 0:
            pv = self.verts[pit_tri_idx]
            pbi = self.bldg_idx[pit_tri_idx]
            v0, v1, v2 = pv[:, 0, :2], pv[:, 1, :2], pv[:, 2, :2]
            pts4 = np.stack(
                [
                    (v0 + v1 + v2) * (1.0 / 3.0),
                    0.6 * v0 + 0.2 * v1 + 0.2 * v2,
                    0.2 * v0 + 0.6 * v1 + 0.2 * v2,
                    0.2 * v0 + 0.2 * v1 + 0.6 * v2,
                ],
                axis=1,
            )  # (N_pit, 4, 2)
            pc4 = np.clip(((pts4[:, :, 0] - E_MIN) * (1.0 / GRID_RES)).astype(np.int32), 0, GRID_W - 1)
            pr4 = np.clip(((N_MAX - pts4[:, :, 1]) * (1.0 / GRID_RES)).astype(np.int32), 0, GRID_H - 1)
            rgb4 = np.asarray(ortho_05m[pr4, pc4], dtype=np.float32)  # (N_pit, 4, 3)
            del ortho_05m
            lum4 = 0.299 * rgb4[:, :, 0] + 0.587 * rgb4[:, :, 1] + 0.114 * rgb4[:, :, 2]
            not_leaf4 = ~(((rgb4[:, :, 1] - rgb4[:, :, 0]) > 9.0) & ((rgb4[:, :, 1] - rgb4[:, :, 2]) > 7.0))
            lum4_masked = np.where(not_leaf4, lum4, np.nan)
            has_valid4 = not_leaf4.any(axis=1)
            tri_med_lum = np.where(
                has_valid4,
                np.nanmedian(np.where(has_valid4[:, None], lum4_masked, lum4), axis=1),
                lum4[:, 0],
            ).astype(np.float32)

            b_ref_rgb = self.bldg_sunlit_roof_rgb[pbi]
            b_ref_lum = np.maximum(
                62.0,
                0.299 * b_ref_rgb[:, 0] + 0.587 * b_ref_rgb[:, 1] + 0.114 * b_ref_rgb[:, 2],
            )
            ratio = b_ref_lum / np.maximum(tri_med_lum, 24.0)
            sh_weight = np.clip((0.88 - (tri_med_lum / np.maximum(b_ref_lum, 1.0))) / 0.42, 0.0, 1.0)
            gain_raw = 1.0 + sh_weight * (np.clip(ratio, 1.0, 1.88) - 1.0)
            lindt_hoc_id = self.lm_idx.get("lindt_hoc", 1443)
            exempt = (pbi == lindt_hoc_id) | (self.bldg_roof_kind[pbi] == 3)
            gain_raw = np.where(exempt, 1.0, np.clip(gain_raw, 1.0, 1.88))
            self.tri_roof_lum_gain[pit_tri_idx] = gain_raw.astype(np.float32)

            mean_rgb_p = rgb4.mean(axis=1)
            is_blue_clay = (
                (~exempt)
                & (gain_raw > 1.15)
                & (self.bldg_roof_kind[pbi] == 0)
                & (mean_rgb_p[:, 2] > (mean_rgb_p[:, 0] - 4.0))
            )
            warm_w = np.where(is_blue_clay, np.clip((gain_raw - 1.15) * 0.24, 0.0, 0.16), 0.0)
            self.tri_roof_warm_shift[pit_tri_idx] = warm_w.astype(np.float32)
            del pv, pts4, rgb4, lum4, lum4_masked

        # Exact physical horizontal wall spans [wall_u_min, wall_u_max] per (building, 10°-normal-bin)
        b_e0 = np.array([b_item["e"] for b_item in self.buildings], dtype=np.float32)
        b_n0 = np.array([b_item["n"] for b_item in self.buildings], dtype=np.float32)
        ang_raw = np.arctan2(self.normals[:, 1], self.normals[:, 0])
        self.tri_dir_bin = (np.round(ang_raw * (36.0 / (2.0 * math.pi))).astype(np.int32)) % 36
        ang_q = self.tri_dir_bin.astype(np.float32) * (2.0 * math.pi / 36.0)
        self.tri_tw_x = (-np.sin(ang_q)).astype(np.float32)
        self.tri_tw_y = np.cos(ang_q).astype(np.float32)
        self.tri_u_verts = (
            (self.verts[:, :, 0] - b_e0[self.bldg_idx][:, None]) * self.tri_tw_x[:, None]
            + (self.verts[:, :, 1] - b_n0[self.bldg_idx][:, None]) * self.tri_tw_y[:, None]
        ).astype(np.float32)

        n_wkeys = nb * 36
        self.wall_u_min = np.full(n_wkeys, 1e6, dtype=np.float32)
        self.wall_u_max = np.full(n_wkeys, -1e6, dtype=np.float32)
        wm_all = self.surf_type == 0
        w_keys_all = self.bldg_idx[wm_all] * 36 + self.tri_dir_bin[wm_all]
        np.minimum.at(self.wall_u_min, w_keys_all, self.tri_u_verts[wm_all].min(axis=1))
        np.maximum.at(self.wall_u_max, w_keys_all, self.tri_u_verts[wm_all].max(axis=1))

        # F4: Hoist parked cars strictly inside diorama_mask & G_PARKING (~21s/preset speedup, 0 floating sky cars!)
        self.parked_cars: list[tuple[float, float, float, int, float]] = self._precompute_parked_cars()

        # F7: Deterministic 3D streetlamps along main sidewalks, viaducts, Bahnhof platforms & lakeside promenade
        self.lamp_e, self.lamp_n, self.lamp_z, self.lamp_kind = self._precompute_streetlamps()

        # F12/F13: Precompute per-building facade styles & vernacular flags once
        (
            self.bldg_wall_rgb,
            self.bldg_style,
            self.bldg_is_shopfront,
            self.bldg_is_riegelhaus,
        ) = _compute_building_facade_styles(self)
        # v12-M1B: Evict large read-only mmap pages touched during SceneData init to keep 0.11 m/px peak RSS < 4.5 GiB
        _evict_mmap_rss(self.ortho_hr)
        _evict_mmap_rss(self.roof_edge_25cm)

    def _precompute_parked_cars(self) -> list[tuple[float, float, float, int, float]]:
        """Precompute valid parked cars strictly inside diorama_mask & G_PARKING (all 5 points verified)."""
        cars: list[tuple[float, float, float, int, float]] = []
        pk_rows, pk_cols = np.nonzero((self.sem == G_PARKING) & self.diorama_mask)
        if len(pk_rows) == 0:
            return cars
        pk_ang = math.radians(28.5)
        ck, sk = math.cos(pk_ang), math.sin(pk_ang)
        fe_dir, fn_dir = -sk, ck
        se_dir, sn_dir = ck, sk

        p_e_all = E_MIN + (pk_cols.astype(np.float32) + 0.5) * GRID_RES
        p_n_all = N_MAX - (pk_rows.astype(np.float32) + 0.5) * GRID_RES
        ku_all = (p_e_all - E_MIN) * ck + (p_n_all - N_MIN) * sk
        kv_all = -(p_e_all - E_MIN) * sk + (p_n_all - N_MIN) * ck
        iu_min, iu_max = int(math.floor(float(ku_all.min()) / 2.65)), int(math.ceil(float(ku_all.max()) / 2.65))
        iv_min, iv_max = int(math.floor(float(kv_all.min()) / 15.4)), int(math.ceil(float(kv_all.max()) / 15.4))

        for iv in range(iv_min, iv_max + 1):
            for bay_sub, bay_v_off in ((0, 2.45), (1, 7.35)):
                kv_c = iv * 15.4 + bay_v_off
                for iu in range(iu_min, iu_max + 1):
                    kh = ((iu * 73856093) ^ (iv * 19349663) ^ (bay_sub * 83492791)) & 0xFF
                    if (kh % 10) >= 4:
                        continue
                    ku_c = (iu + 0.5) * 2.65
                    pe_k = E_MIN + ku_c * ck - kv_c * sk
                    pn_k = N_MIN + ku_c * sk + kv_c * ck
                    # Apply human parking jitter BEFORE strict 5-point corner check
                    j_l = (((kh >> 3) & 7) - 3.5) * 0.05
                    pe_k += j_l * fe_dir
                    pn_k += j_l * fn_dir
                    ok_bay = True
                    for d_l, d_w in ((0.0, 0.0), (-2.00, -0.86), (-2.00, 0.86), (2.00, -0.86), (2.00, 0.86)):
                        ce_t = pe_k + d_l * fe_dir + d_w * se_dir
                        cn_t = pn_k + d_l * fn_dir + d_w * sn_dir
                        rc_t = int(round((N_MAX - cn_t) * 2.0))
                        cc_t = int(round((ce_t - E_MIN) * 2.0))
                        if not (0 <= rc_t < GRID_H and 0 <= cc_t < GRID_W):
                            ok_bay = False
                            break
                        if (
                            not self.diorama_mask[rc_t, cc_t]
                            or self.sem[rc_t, cc_t] != G_PARKING
                            or float(self.parking_sdf_05m[rc_t, cc_t]) < 0.56
                            or self.bldg_roof_mask[rc_t, cc_t]
                            or self.hedge_mask[rc_t, cc_t]
                        ):
                            ok_bay = False
                            break
                    if not ok_bay:
                        continue
                    rc_c = int(round((N_MAX - pn_k) * 2.0))
                    cc_c = int(round((pe_k - E_MIN) * 2.0))
                    pz_k = float(self.dem_smooth_05m[rc_c, cc_c])
                    facing = 1.0 if (bay_sub == 1) else -1.0
                    cars.append((float(pe_k), float(pn_k), pz_k, int(kh % 9), facing))
        return cars

    def _precompute_streetlamps(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Extract ~206 deterministic sidewalk/viaduct/platform/promenade streetlamps strictly off centerlines."""
        lamps: list[tuple[float, float, float, int]] = []
        cell_sz = 12.0
        grid_bins: dict[tuple[int, int], list[tuple[float, float]]] = {}

        def _try_add(e_v: float, n_v: float, z_v: float, kind: int, min_d: float) -> bool:
            bx = int(math.floor(e_v / cell_sz))
            by = int(math.floor(n_v / cell_sz))
            span = int(math.ceil(min_d / cell_sz))
            min_d2 = min_d * min_d
            for dx in range(-span, span + 1):
                for dy in range(-span, span + 1):
                    for oe, on in grid_bins.get((bx + dx, by + dy), ()):
                        if (e_v - oe) * (e_v - oe) + (n_v - on) * (n_v - on) < min_d2:
                            return False
            grid_bins.setdefault((bx, by), []).append((e_v, n_v))
            lamps.append((e_v, n_v, z_v, kind))
            return True

        # Source 1: Main Streets outer sidewalk band (strictly off roadway centerlines!)
        eff_hw = np.maximum(3.8, self.road_hw)
        sw_band = (
            self.diorama_mask
            & (self.sem == G_STREET_MAIN)
            & (~self.bldg_roof_mask)
            & (~self.lake_mask)
            & (self.bridge_cls == 0)
            & (self.road_dist >= (eff_hw - 1.25))
            & (self.road_dist <= (eff_hw - 0.15))
        )
        sr, sc = np.nonzero(sw_band)
        for r, c in zip(sr[::2], sc[::2]):
            _try_add(E_MIN + (c + 0.5) * GRID_RES, N_MAX - (r + 0.5) * GRID_RES, float(self.dem[r, c]), 0, 19.0)

        # Source 1b: Quartierstrassen / Alte Landstrasse village lanes (G_STREET_MINOR) get sparser lantern posts on the verge
        minor_band = (
            self.diorama_mask
            & (self.sem == G_STREET_MINOR)
            & (~self.bldg_roof_mask)
            & (~self.lake_mask)
            & (self.bridge_cls == 0)
            & (self.road_dist >= 1.35)
            & (self.road_dist <= 2.6)
        )
        mr, mc = np.nonzero(minor_band)
        for r, c in zip(mr[::2], mc[::2]):
            _try_add(E_MIN + (c + 0.5) * GRID_RES, N_MAX - (r + 0.5) * GRID_RES, float(self.dem[r, c]), 0, 24.0)

        # Source 2: Elevated Road Viaduct outer edges
        br_m = (
            self.diorama_mask
            & (self.bridge_cls == BR_ROAD_VIADUCT)
            & (np.abs(self.bridge_sdist) >= (self.bridge_hw - 1.25))
            & (np.abs(self.bridge_sdist) <= (self.bridge_hw - 0.55))
            & ((self.bridge_along % 18.0) < 0.85)
        )
        lbl_br, n_br = ndimage.label(br_m)
        if n_br > 0:
            br_r, br_c = np.nonzero(br_m)
            br_l = lbl_br[br_r, br_c]
            for li_b in range(1, n_br + 1):
                m_i = br_l == li_b
                if not m_i.any():
                    continue
                rm = int(round(float(br_r[m_i].mean())))
                cm = int(round(float(br_c[m_i].mean())))
                _try_add(E_MIN + (cm + 0.5) * GRID_RES, N_MAX - (rm + 0.5) * GRID_RES, float(self.bridge_z[rm, cm]), 1, 15.0)

        # Source 3: Bahnhof Kilchberg SBB Platforms
        plat_m = (
            self.diorama_mask
            & (self.sem == G_PLATFORM_PIER)
            & (~self.lake_mask)
            & (self.rail_dist >= 2.0)
            & (self.rail_dist <= 4.2)
            & ((self.rail_along % 16.0) < 0.85)
        )
        lbl_pl, n_pl = ndimage.label(plat_m)
        if n_pl > 0:
            pl_r, pl_c = np.nonzero(plat_m)
            pl_l = lbl_pl[pl_r, pl_c]
            for li_p in range(1, n_pl + 1):
                m_i = pl_l == li_p
                if not m_i.any():
                    continue
                rm = int(round(float(pl_r[m_i].mean())))
                cm = int(round(float(pl_c[m_i].mean())))
                _try_add(E_MIN + (cm + 0.5) * GRID_RES, N_MAX - (rm + 0.5) * GRID_RES, float(self.dem[rm, cm]) + 0.58, 2, 12.0)

        # Source 4: Bendlikon / Seebad Lakeside Promenade
        near_lake14 = ndimage.binary_dilation(self.lake_mask, iterations=28) & (~self.lake_mask)
        prom_m = (
            self.diorama_mask
            & near_lake14
            & ((self.sem == G_FOOTPATH) | (self.sem == G_PLATFORM_PIER))
            & (~self.bldg_roof_mask)
        )
        pr_l, pc_l = np.nonzero(prom_m)
        for r, c in zip(pr_l[::2], pc_l[::2]):
            _try_add(E_MIN + (c + 0.5) * GRID_RES, N_MAX - (r + 0.5) * GRID_RES, float(self.dem[r, c]), 3, 20.0)

        if not lamps:
            return (
                np.empty(0, dtype=np.float32),
                np.empty(0, dtype=np.float32),
                np.empty(0, dtype=np.float32),
                np.empty(0, dtype=np.uint8),
            )
        arr_e = np.array([x[0] for x in lamps], dtype=np.float32)
        arr_n = np.array([x[1] for x in lamps], dtype=np.float32)
        arr_z = np.array([x[2] for x in lamps], dtype=np.float32)
        arr_k = np.array([x[3] for x in lamps], dtype=np.uint8)
        return arr_e, arr_n, arr_z, arr_k


def condition_90s_albedo(
    rgb_u8: np.ndarray,
    shadow_knee: float = 56.0,
    vibrancy: float = 1.24,
    dehaze: float = 0.0,
) -> np.ndarray:
    """Lift harsh aerial shadows and restore crisp 90s SVGA chroma without shifting neutral greys brown."""
    rgb = rgb_u8.astype(np.float32)
    if dehaze > 0.0:
        veil_w = np.clip((rgb.min(axis=-1, keepdims=True) - 18.0) / 70.0, 0.0, 1.0) * dehaze
        rgb = np.maximum(4.0, rgb - veil_w * np.array([7.5, 8.5, 9.5], dtype=np.float32))
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    target_lum = np.where(
        lum < shadow_knee,
        shadow_knee * ((np.maximum(lum, 6.0) / shadow_knee) ** 0.58),
        lum,
    )
    scale = target_lum / np.maximum(lum, 6.0)
    lifted = rgb * scale[..., None]
    lum2 = (0.299 * lifted[..., 0] + 0.587 * lifted[..., 1] + 0.114 * lifted[..., 2])[..., None]
    chroma = lifted.max(axis=-1, keepdims=True) - lifted.min(axis=-1, keepdims=True)
    vib_eff = np.where(chroma < 12.0, 1.02, vibrancy)
    boosted = lum2 + vib_eff * (lifted - lum2)
    return np.clip(boosted, 0.0, 250.0)


def sample_ortho_25cm(scene: SceneData, e_arr: np.ndarray, n_arr: np.ndarray) -> np.ndarray:
    """Sample native 10 cm (or 25 cm fallback) SWISSIMAGE DOP10 RGB at arbitrary world LV95 (E, N) coordinates."""
    cols = np.clip(((e_arr - E_MIN) * (1.0 / scene.ortho_res)).astype(np.int32), 0, scene.ortho_w - 1)
    rows = np.clip(((N_MAX - n_arr) * (1.0 / scene.ortho_res)).astype(np.int32), 0, scene.ortho_h - 1)
    return np.asarray(scene.ortho_hr[rows, cols])


def sample_roof_edge_25cm(scene: SceneData, e_arr: np.ndarray, n_arr: np.ndarray) -> np.ndarray:
    """Sample exact 25 cm roof parapet step band (1=outer coping, 2=inner shadow, 3..4=interior)."""
    cols = np.clip(((e_arr - E_MIN) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_W - 1)
    rows = np.clip(((N_MAX - n_arr) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_H - 1)
    return np.asarray(scene.roof_edge_25cm[rows, cols])


def _sample_bilinear_05m(
    arr: np.ndarray,
    ge: np.ndarray,
    gn: np.ndarray,
    r0: int = 0,
    c0: int = 0,
    max_jump: float | None = None,
) -> np.ndarray:
    """Fast vectorized bilinear interpolation of a 0.5m continuous grid (full or [r0:r1, c0:c1] slice)."""
    h_a, w_a = arr.shape
    fc = np.clip((ge - E_MIN) * (1.0 / GRID_RES) - 0.5 - c0, 0.0, float(w_a - 1))
    fr = np.clip((N_MAX - gn) * (1.0 / GRID_RES) - 0.5 - r0, 0.0, float(h_a - 1))
    c_lo = np.floor(fc).astype(np.int32)
    r_lo = np.floor(fr).astype(np.int32)
    c_hi = np.minimum(c_lo + 1, w_a - 1)
    r_hi = np.minimum(r_lo + 1, h_a - 1)
    wc = (fc - c_lo).astype(np.float32)
    wr = (fr - r_lo).astype(np.float32)
    v00 = arr[r_lo, c_lo].astype(np.float32)
    v01 = arr[r_lo, c_hi].astype(np.float32)
    v10 = arr[r_hi, c_lo].astype(np.float32)
    v11 = arr[r_hi, c_hi].astype(np.float32)
    out = (v00 * (1.0 - wc) + v01 * wc) * (1.0 - wr) + (v10 * (1.0 - wc) + v11 * wc) * wr
    if max_jump is not None:
        v_max = np.maximum(np.maximum(v00, v01), np.maximum(v10, v11))
        v_min = np.minimum(np.minimum(v00, v01), np.minimum(v10, v11))
        discont = (v_max - v_min) > max_jump
        if discont.any():
            rn = np.clip(np.round(fr[discont]).astype(np.int32), 0, h_a - 1)
            cn = np.clip(np.round(fc[discont]).astype(np.int32), 0, w_a - 1)
            out[discont] = arr[rn, cn].astype(np.float32)
    return out


def _sample_bilinear_rgb_05m(arr_rgb: np.ndarray, ge: np.ndarray, gn: np.ndarray) -> np.ndarray:
    """Fast vectorized bilinear interpolation of a 0.5m RGB (H, W, 3) grid."""
    h_a, w_a, _ = arr_rgb.shape
    fc = np.clip((ge - E_MIN) * (1.0 / GRID_RES) - 0.5, 0.0, float(w_a - 1))
    fr = np.clip((N_MAX - gn) * (1.0 / GRID_RES) - 0.5, 0.0, float(h_a - 1))
    c_lo = np.floor(fc).astype(np.int32)
    r_lo = np.floor(fr).astype(np.int32)
    c_hi = np.minimum(c_lo + 1, w_a - 1)
    r_hi = np.minimum(r_lo + 1, h_a - 1)
    wc = (fc - c_lo).astype(np.float32)[:, None]
    wr = (fr - r_lo).astype(np.float32)[:, None]
    v00 = arr_rgb[r_lo, c_lo].astype(np.float32)
    v01 = arr_rgb[r_lo, c_hi].astype(np.float32)
    v10 = arr_rgb[r_hi, c_lo].astype(np.float32)
    v11 = arr_rgb[r_hi, c_hi].astype(np.float32)
    return (v00 * (1.0 - wc) + v01 * wc) * (1.0 - wr) + (v10 * (1.0 - wc) + v11 * wc) * wr


def compute_shadow_grid(
    scene: SceneData,
    sun_az_deg: float,
    sun_alt_deg: float,
) -> tuple[np.ndarray, np.ndarray]:
    """F8 Multi-Scale 0.5m Near-Field + 1.0m Far-Field LiDAR DSM Shadow Ceiling.

    Returns (sh_ground_05m: bool[H,W], ray_rel_05m: float16[H,W]) where ray_rel_05m stores
    (blocker_ray_z - dem) for dist >= 2.0m so lower building roofs & walls receive authentic
    cast shadows from taller neighbors/towers/trees without self-shadow acne!
    """
    dm_r, dm_c = np.nonzero(scene.diorama_mask)
    rmin = max(0, int(dm_r.min()) - 40)
    rmax = min(GRID_H, int(dm_r.max()) + 180)
    cmin = max(0, int(dm_c.min()) - 40)
    cmax = min(GRID_W, int(dm_c.max()) + 240)

    dem_sub = scene.dem[rmin:rmax, cmin:cmax]
    lake_sub = scene.lake_mask[rmin:rmax, cmin:cmax]
    pier_sub = scene.pier_only_mask_05m[rmin:rmax, cmin:cmax]
    roof_sub = scene.bldg_roof_mask[rmin:rmax, cmin:cmax]
    chm_sub = np.where(lake_sub & (~pier_sub) & (~roof_sub), 0.0, scene.chm[rmin:rmax, cmin:cmax])
    h_sub = np.maximum(dem_sub + chm_sub, scene.bridge_z[rmin:rmax, cmin:cmax])
    H_s, W_s = h_sub.shape

    az = math.radians(sun_az_deg)
    alt = math.radians(sun_alt_deg)
    dcol = math.sin(az)
    drow = -math.cos(az)
    dz_per_m = math.tan(alt)

    # Step dist = 1.0 m (ground-only contact shadow; excluded from ray_z so building parapets never self-shadow!)
    sh_dist1 = np.zeros((H_s, W_s), dtype=np.bool_)
    sc1 = int(round(dcol * (1.0 / GRID_RES)))
    sr1 = int(round(drow * (1.0 / GRID_RES)))
    if sc1 != 0 or sr1 != 0:
        r0s, r1s = max(0, sr1), min(H_s, H_s + sr1)
        c0s, c1s = max(0, sc1), min(W_s, W_s + sc1)
        r0d, r1d = r0s - sr1, r1s - sr1
        c0d, c1d = c0s - sc1, c1s - sc1
        sh_dist1[r0d:r1d, c0d:c1d] = (h_sub[r0s:r1s, c0s:c1s] - np.float32(dz_per_m * 1.0)) > (h_sub[r0d:r1d, c0d:c1d] + 0.55)

    # Near-field 0.5 m exact ray-height ceiling (2m .. 34m) using in-place preallocated tmp buffer
    ray_z = np.full((H_s, W_s), -1e4, dtype=np.float32)
    tmp = np.empty((H_s, W_s), dtype=np.float32)
    near_dists = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34)
    for dist in near_dists:
        sc = int(round(dcol * (dist / GRID_RES)))
        sr = int(round(drow * (dist / GRID_RES)))
        if sc == 0 and sr == 0:
            continue
        r0s, r1s = max(0, sr), min(H_s, H_s + sr)
        c0s, c1s = max(0, sc), min(W_s, W_s + sc)
        if r1s <= r0s or c1s <= c0s:
            continue
        r0d, r1d = r0s - sr, r1s - sr
        c0d, c1d = c0s - sc, c1s - sc
        sl_tmp = tmp[r0d:r1d, c0d:c1d]
        np.subtract(h_sub[r0s:r1s, c0s:c1s], np.float32(dz_per_m * dist), out=sl_tmp)
        np.maximum(ray_z[r0d:r1d, c0d:c1d], sl_tmp, out=ray_z[r0d:r1d, c0d:c1d])
    del tmp

    # Far-field 1.0 m ray-height ceiling (36m .. 116m)
    h10 = h_sub[::2, ::2]
    H10, W10 = h10.shape
    ray10 = np.full((H10, W10), -1e4, dtype=np.float32)
    tmp10 = np.empty((H10, W10), dtype=np.float32)
    for dist in range(36, 118, 4):
        sc = int(round(dcol * dist))
        sr = int(round(drow * dist))
        if sc == 0 and sr == 0:
            continue
        r0s, r1s = max(0, sr), min(H10, H10 + sr)
        c0s, c1s = max(0, sc), min(W10, W10 + sc)
        if r1s <= r0s or c1s <= c0s:
            continue
        r0d, r1d = r0s - sr, r1s - sr
        c0d, c1d = c0s - sc, c1s - sc
        sl_t10 = tmp10[r0d:r1d, c0d:c1d]
        np.subtract(h10[r0s:r1s, c0s:c1s], np.float32(dz_per_m * dist), out=sl_t10)
        np.maximum(ray10[r0d:r1d, c0d:c1d], sl_t10, out=ray10[r0d:r1d, c0d:c1d])
    del tmp10, h10

    ray10_up = np.repeat(np.repeat(ray10, 2, axis=0), 2, axis=1)[:H_s, :W_s]
    np.maximum(ray_z, ray10_up, out=ray_z)
    del ray10, ray10_up

    sh_ground = np.zeros((GRID_H, GRID_W), dtype=np.bool_)
    sh_ground[rmin:rmax, cmin:cmax] = sh_dist1 | (ray_z > (h_sub + 0.55))

    ray_rel = np.full((GRID_H, GRID_W), -100.0, dtype=np.float16)
    ray_rel[rmin:rmax, cmin:cmax] = np.clip(ray_z - dem_sub, -100.0, 200.0).astype(np.float16)

    del sh_dist1, h_sub, ray_z
    return sh_ground, ray_rel


def _compute_building_facade_styles(
    scene: SceneData,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Determine authentic Swiss facade RGB, architectural style code (0..9), shopfront corridor flag,
    and historic Dorf/Lebern Riegelhaus half-timbered flag for all 1,890 Kilchberg buildings."""
    buildings = scene.buildings
    n = len(buildings)
    wall_rgb = np.empty((n, 3), dtype=np.uint8)
    style_code = np.zeros(n, dtype=np.uint8)
    is_shopfront = np.zeros(n, dtype=np.bool_)
    is_riegelhaus = np.zeros(n, dtype=np.bool_)
    lm = scene.lm_idx

    plaster_trad = [
        (214, 210, 200),  # Classic Swiss off-white plaster
        (204, 190, 162),  # Warm Kilchberg sand-cream stucco
        (178, 174, 162),  # Canton Zürich pebble-greige stucco
        (212, 194, 142),  # Historic Zürichsee golden-butter ochre villa
        (198, 160, 148),  # Historic dusty terracotta-rose villa plaster
        (194, 186, 172),  # Warm Jura limestone plaster
        (218, 208, 160),  # Soft pale cream-yellow stucco
        (164, 162, 152),  # Olive-grey Swiss apartment plaster
        (114, 82, 58),    # Sun-weathered Swiss chalet / barn timber
    ]
    modern_pal = [
        (172, 170, 164),  # Fair-faced architectural concrete / Jura stone grey
        (196, 182, 158),  # Warm travertine / sand-limestone terrace apartment
        (212, 210, 204),  # Architectural alabaster off-white
        (188, 156, 136),  # Stepped hillside terracotta-sand apartment masonry
        (152, 146, 136),  # Warm bronze-taupe natural stone modern villa
        (198, 194, 186),  # Pale warm architectural stone
    ]

    sanatorium_ids = {
        lm.get("sanatorium_483", -1),
        lm.get("sanatorium_633", -1),
        lm.get("sanatorium_521", -1),
        lm.get("sanatorium_853", -1),
        lm.get("sanatorium_655", -1),
        lm.get("sanatorium_81", -1),
    } - {-1}
    seebad_ids = {
        lm.get("seebad_bathhouse", -1),
        lm.get("seebad_kiosk", -1),
        lm.get("seebad_south", -1),
    } - {-1}
    gemeindehaus_ids = {
        lm.get("gemeindehaus_main", -1),
        lm.get("gemeindehaus_wing", -1),
        lm.get("schulhaus_alteland_868", -1),
        lm.get("schulhaus_alteland_437", -1),
    } - {-1}
    cf_meyer_ids = {lm.get("cf_meyer_haus", -1)} - {-1}
    barn_ids = {lm.get("dorf_barn_1490", -1), lm.get("dorf_barn_1726", -1)} - {-1}
    hallenbad_main_id = lm.get("hallenbad_main_1835", -1)
    sporthalle_ids = {lm.get("hallenbad_pool_1448", -1), lm.get("hallenbad_entry_1628", -1)} - {-1}
    broelberg_estate_ids = {
        lm.get("broelberg_manor_979", -1),
        lm.get("broelberg_gardener_1678", -1),
        lm.get("broelberg_outb_1332", -1),
    } - {-1}
    spinnergut_ids = {lm.get("spinnergut_villa_1601", -1), lm.get("spinnergut_pav_1132", -1)} - {-1}
    sulzergut_chalet_id = lm.get("sulzergut_villa_1617", -1)
    sulzergut_villa_1338_id = lm.get("sulzergut_villa_1338", -1)
    sulzergut_park_shed_id = lm.get("sulzergut_boat_1169", -1)
    sulzergut_inland_outb_ids = {
        lm.get("sulzergut_boat_1550", -1),
        lm.get("sulzergut_boat_1706", -1),
        lm.get("sulzergut_boat_984", -1),
    } - {-1}
    stockengut_barn_ids = {lm.get("stockengut_barn_807", -1), lm.get("stockengut_mutterkuhstall_91", -1)} - {-1}
    stockengut_barn77_id = lm.get("stockengut_barn_77", -1)
    stockengut_house_ids = {lm.get("stockengut_house_279", -1), lm.get("stockengut_house_574", -1)} - {-1}
    stockengut_hof_id = lm.get("stockengut_outb_473", -1)
    stockengut_poultry_id = lm.get("stockengut_outb_1037", -1)
    lakeside_boat_ids = {
        lm.get("moenchhof_boat_25", -1),
        lm.get("moenchhof_boat_825", -1),
        lm.get("morfanlage_boat_42", -1),
        lm.get("morfanlage_boat_379", -1),
    } - {-1}
    hafenbeiz_ids = {lm.get("moenchhof_hafenbeiz_243", -1), lm.get("moenchhof_hafenbeiz_843", -1)} - {-1}
    moenchhof_villa_ids = {
        lm.get("moenchhof_villa_727", -1),
        lm.get("moenchhof_villa_303", -1),
        lm.get("moenchhof_villa_527", -1),
        lm.get("moenchhof_villa_890", -1),
        lm.get("moenchhof_villa_781", -1),
    } - {-1}
    morfanlage_villa_ids = {lm.get("morfanlage_villa_771", -1), lm.get("morfanlage_villa_423", -1)} - {-1}

    for i, b in enumerate(buildings):
        obj = b["objektart"]
        e, nc = b["e"], b["n"]
        h = b["height"]
        fw, fl = b["footprint_w"], b["footprint_l"]
        area_box = fw * fl
        addr = str(b.get("address", ""))
        nb_name = str(b.get("neighbourhood", ""))
        h_seed = ((i * 73856093) ^ int(round(e * 13.0)) ^ int(round(nc * 29.0))) & 0x7FFFFFFF

        if obj == "Hochkamin":
            wall_rgb[i] = (194, 180, 148)
            style_code[i] = 5
        elif obj == "Lagertank":
            wall_rgb[i] = (186, 192, 200)
            style_code[i] = 8
        elif obj == "Treibhaus":
            wall_rgb[i] = (156, 194, 208)
            style_code[i] = 7
        elif obj in ("Flugdach", "Offenes Gebaeude", "Mauer gross"):
            if i == lm.get("seebad_boathouse", -1):
                wall_rgb[i] = (224, 224, 220)  # Crisp off-white/light-grey Seebad boathouse (Seestrasse 199a)
            else:
                wall_rgb[i] = (164, 158, 146) if obj == "Mauer gross" else (172, 168, 160)
            style_code[i] = 5
        elif obj in ("Sakrales Gebaeude", "Sakraler Turm"):
            if i == lm.get("st_elisabeth_twr", -1):
                wall_rgb[i] = (238, 238, 234)  # Crisp bright white painted concrete crown tower (Studer 1967)
            elif i == lm.get("st_elisabeth_nave", -1):
                wall_rgb[i] = (232, 230, 224)  # Crisp white plaster lower nave walls
            else:
                wall_rgb[i] = (232, 232, 226) if nc < 1241450 else (216, 214, 208)
            style_code[i] = 4
        elif i == lm.get("lindt_hoc", -1):
            wall_rgb[i] = (174, 82, 54)   # Real Keller terracotta/orange-red clinker brick (Christ & Gantenbein)
            style_code[i] = 2
        elif i == lm.get("lindt_brick_n", -1):
            wall_rgb[i] = (216, 206, 178) # Historic buff/cream-brick wing adjacent to HoC
            style_code[i] = 3
        elif i == lm.get("lindt_brick_s", -1):
            wall_rgb[i] = (158, 66, 52)
            style_code[i] = 3
        elif i == lm.get("lindt_wing_963", -1):
            wall_rgb[i] = (174, 148, 126)
            style_code[i] = 3
        elif i == lm.get("lindt_wing_1520", -1):
            wall_rgb[i] = (198, 186, 164)
            style_code[i] = 3
        elif i == lm.get("lindt_wing_1281", -1):
            wall_rgb[i] = (214, 214, 208)
            style_code[i] = 3
        elif i == lm.get("lindt_wing_1173", -1):
            wall_rgb[i] = (188, 184, 174)
            style_code[i] = 3
        elif i in (lm.get("lindt_south_1473", -1), lm.get("lindt_south_1720", -1)):
            wall_rgb[i] = (178, 168, 148)
            style_code[i] = 3
        elif i == lm.get("lindt_main", -1):
            wall_rgb[i] = (220, 216, 204)
            style_code[i] = 3
        elif i == lm.get("bahnhof_station", -1):
            wall_rgb[i] = (178, 180, 148)  # Baumgartner Partner photo-verified blasses Olivgruen stucco
            style_code[i] = 9
        elif i == lm.get("schulhaus_dorfstr", -1):
            wall_rgb[i] = (232, 232, 226)  # Schulhaus Dorfstrasse (Dorfstr. 41) cool off-white Neoclassical plaster
            style_code[i] = 9
        elif i == lm.get("schulhaus_alteland_868", -1):
            wall_rgb[i] = (216, 196, 136)  # Warm golden-ochre stucco (1908 Zollinger)
            style_code[i] = 9
        elif i == lm.get("schulhaus_alteland_437", -1):
            wall_rgb[i] = (206, 204, 198)  # Modern flat-roofed school annex
            style_code[i] = 9
        elif i in gemeindehaus_ids:
            wall_rgb[i] = (214, 206, 178)  # Warm sand-beige Rauputz plaster (Alte Landstrasse 110)
            style_code[i] = 9
        elif i in cf_meyer_ids:
            wall_rgb[i] = (232, 222, 184)  # Luminous pale butter-cream plaster (Alte Landstrasse 170)
            style_code[i] = 9
        elif i in sanatorium_ids:
            if i in (lm.get("sanatorium_633", -1), lm.get("sanatorium_81", -1)):
                wall_rgb[i] = (242, 244, 246)  # Historic Haus A (1890) & Haus C (1867) crisp white plaster
            elif i == lm.get("sanatorium_853", -1):
                wall_rgb[i] = (234, 236, 234)  # 1961-62 Rolf Haessig modernist concrete/white stucco (Haus E/F)
            else:
                wall_rgb[i] = (238, 240, 240)  # Modernist/contemporary crisp off-white (Haus B 1974, Haus D/H 2007-08)
            style_code[i] = 9
        elif i in seebad_ids:
            wall_rgb[i] = (154, 114, 76)   # Warm weathered cedar/larch horizontal slats (Hornberger 2014)
            style_code[i] = 9
        elif i == hallenbad_main_id:
            wall_rgb[i] = (234, 236, 234)  # Crisp white plaster (Hallenbad Kilchberg, Hochweidstr. 10)
            style_code[i] = 9
        elif i in sporthalle_ids:
            wall_rgb[i] = (168, 170, 168)  # Raw exposed Sichtbeton concrete (Sporthalle Hochweid, Hochweidstr. 13)
            style_code[i] = 9
        elif i == lm.get("broelberg_tempelchen_1074", -1):
            wall_rgb[i] = (224, 218, 204)
            style_code[i] = 9
        elif i == lm.get("broelberg_manor_979", -1):
            wall_rgb[i] = (232, 226, 212)  # Clean pale warm ivory stucco (Alte Landstrasse 192)
            style_code[i] = 9
        elif i in broelberg_estate_ids:
            wall_rgb[i] = (228, 222, 206)
            style_code[i] = 9
        elif i in spinnergut_ids:
            wall_rgb[i] = (234, 232, 226)  # Crisp historic off-white lime plaster (Villa Spinnergut 1914)
            style_code[i] = 9
        elif i == lm.get("tc_clubhouse_1287", -1):
            wall_rgb[i] = (176, 86, 56)    # Terracotta-red painted masonry (TC Kilchberg pavilion)
            style_code[i] = 9
        elif i == sulzergut_chalet_id:
            wall_rgb[i] = (108, 72, 52)    # 1900 Swiss chalet dark chestnut-brown upper timber (white GF in B2)
            style_code[i] = 9
        elif i == sulzergut_villa_1338_id:
            wall_rgb[i] = (224, 218, 204)  # 1896 cream-plaster villa across Seestrasse (Seestrasse 240)
            style_code[i] = 9
        elif i == sulzergut_park_shed_id:
            wall_rgb[i] = (112, 84, 62)    # 1850 weathered timber park outbuilding (Seestrasse 237.1)
            style_code[i] = 6
        elif i in sulzergut_inland_outb_ids:
            wall_rgb[i] = (214, 210, 200)  # Light-plaster roadside garages (235.1/233.2) & garden cottage (233.1)
            style_code[i] = 6
        elif i in stockengut_barn_ids:
            wall_rgb[i] = (74, 56, 42)     # Dark espresso weathered vertical timber upper gable
            style_code[i] = 9
        elif i == stockengut_barn77_id:
            wall_rgb[i] = (210, 196, 174)  # Baldernstrasse 88 warm ochre-beige plaster
            style_code[i] = 9
        elif i in stockengut_house_ids:
            wall_rgb[i] = (226, 220, 206) if i == lm.get("stockengut_house_279", -1) else (218, 206, 188)
            style_code[i] = 0
        elif i == stockengut_hof_id:
            wall_rgb[i] = (218, 206, 172)  # Uf Stocken 86.2 (Hofladen wing) cream-yellow masonry
            style_code[i] = 6
        elif i == stockengut_poultry_id:
            wall_rgb[i] = (78, 58, 44)     # Uf Stocken 88.2 dark timber poultry barn
            style_code[i] = 6
        elif i in lakeside_boat_ids:
            wall_rgb[i] = (96, 68, 48)
            style_code[i] = 6
        elif i == lm.get("gotisch_hus", -1):
            wall_rgb[i] = (224, 220, 210)  # Gotisch Hus warm chalky off-white plaster
            style_code[i] = 0
            is_riegelhaus[i] = True
        elif i in hafenbeiz_ids:
            wall_rgb[i] = (220, 212, 196)  # Hafenbeiz aged warm cream-ochre lime plaster
            style_code[i] = 0
            is_riegelhaus[i] = True
        elif i == lm.get("chez_fritz_pavilion", -1):
            wall_rgb[i] = (232, 230, 224)  # Crisp Riviera off-white lakeside restaurant pavilion (Seestrasse 195b)
            style_code[i] = 9
        elif i == lm.get("chez_fritz", -1):
            wall_rgb[i] = (228, 226, 220)  # Seestrasse 195 residential/mixed block
            style_code[i] = 0
        elif i in moenchhof_villa_ids:
            wall_rgb[i] = (218, 208, 178)
            style_code[i] = 0
        elif i in morfanlage_villa_ids:
            wall_rgb[i] = (228, 224, 214)  # Seestrasse 105/107 (1850): warm off-white classical plaster
            style_code[i] = 0
        elif i in (lm.get("villa_naville_1582", -1), lm.get("villa_naville_1695", -1)):
            wall_rgb[i] = (234, 224, 174)  # Pale pastel butter-yellow stucco (Seestrasse 201/201a)
            style_code[i] = 0
        elif i in (lm.get("schooren_981", -1), lm.get("schooren_1823", -1)):
            wall_rgb[i] = (234, 234, 230)  # Crisp porcelain-white historic Schooren plaster
            style_code[i] = 0
        elif i == lm.get("bendlikon_pavilion", -1):
            wall_rgb[i] = (132, 176, 152)  # Photo-verified cool mint-sage Verputz (ZSG Wartehaeuschen)
            style_code[i] = 6
        elif i in barn_ids:
            wall_rgb[i] = (102, 70, 48)
            style_code[i] = 0
        elif h < 4.3 or area_box < 42.0 or min(fw, fl) < 4.3:
            wall_rgb[i] = (122, 88, 62) if (h_seed % 3 == 0) else plaster_trad[h_seed % 6]
            style_code[i] = 6
        elif scene.bldg_is_pitched[i]:
            wall_rgb[i] = plaster_trad[h_seed % len(plaster_trad)]
            style_code[i] = 0
            # Selective historic Dorf / Lebern / Bendlikon Riegelhaus half-timbered farmhouses
            if (
                (nb_name in ("Lebern", "Bendlikon") or addr.startswith("Dorfstrasse"))
                and 7.5 <= h <= 16.5
                and fw >= 8.0
                and (h_seed % 6) == 0
            ):
                is_riegelhaus[i] = True
                wall_rgb[i] = (224, 218, 204)
        else:
            wall_rgb[i] = modern_pal[h_seed % len(modern_pal)]
            style_code[i] = 1

        # Bahnhofstrasse & commercial Seestrasse ground-floor shopfront corridor
        if style_code[i] in (0, 1) and h >= 7.0 and fw >= 8.0:
            if addr.startswith("Bahnhofstrasse") or (addr.startswith("Seestrasse") and 1241750.0 <= nc <= 1242200.0):
                is_shopfront[i] = True

    return wall_rgb, style_code, is_shopfront, is_riegelhaus


def compute_full_canvas_geometry(
    scene: SceneData,
    camera: IsometricCamera,
    crop_box_lv95: tuple[float, float, float, float] | None = None,
    add_frame: bool = True,
) -> tuple[IsometricCamera, np.ndarray, float, int, int, float, float, int, int, int, int]:
    """Compute exact full-canvas dimensions and shifts for full municipality or LV95 crop."""
    if crop_box_lv95 is not None:
        e0, n0, e1, n1 = crop_box_lv95
        c0 = max(0, int((e0 - E_MIN) / GRID_RES))
        c1 = min(GRID_W, int(math.ceil((e1 - E_MIN) / GRID_RES)))
        r0 = max(0, int((N_MAX - n1) / GRID_RES))
        r1 = min(GRID_H, int(math.ceil((N_MAX - n0) / GRID_RES)))
        active_mask = np.zeros((GRID_H, GRID_W), dtype=np.bool_)
        active_mask[r0:r1, c0:c1] = True
        plinth_z = max(PLINTH_BASE_Z, float(scene.dem[r0:r1, c0:c1].min()) - 26.0)
        camera = IsometricCamera(
            azimuth_from_deg=camera.azimuth_from_deg,
            pitch_deg=camera.pitch_deg,
            z_exag=camera.z_exag,
            mpp=camera.mpp,
            center_e=0.5 * (e0 + e1),
            center_n=0.5 * (n0 + n1),
            base_z=plinth_z,
        )
    else:
        r0, r1, c0, c1 = 0, GRID_H, 0, GRID_W
        active_mask = scene.diorama_mask
        plinth_z = PLINTH_BASE_Z

    sub_m_global = active_mask[r0:r1, c0:c1]
    sub_dem_global = scene.dem[r0:r1, c0:c1]
    ar, ac = np.nonzero(sub_m_global)
    ae = E_MIN + (ac + c0 + 0.5) * GRID_RES
    an = N_MAX - (ar + r0 + 0.5) * GRID_RES
    px1, py1, _ = camera.project(ae[::8], an[::8], sub_dem_global[ar[::8], ac[::8]] + 48.0)
    px2, py2, _ = camera.project(ae[::8], an[::8], np.full(len(ae[::8]), plinth_z - 6.0))

    if camera.mpp <= 0.18:
        pad_x = 192 if add_frame else 56
        pad_top = 264 if add_frame else 56
        pad_bot = 312 if add_frame else 64
    else:
        pad_x = 96 if add_frame else 28
        pad_top = 132 if add_frame else 28
        pad_bot = 156 if add_frame else 32

    min_x, max_x = float(min(px1.min(), px2.min())), float(max(px1.max(), px2.max()))
    min_y, max_y = float(min(py1.min(), py2.min())), float(max(py1.max(), py2.max()))
    W_full = int(math.ceil(max_x - min_x)) + 2 * pad_x
    H_full = int(math.ceil(max_y - min_y)) + pad_top + pad_bot
    shift_x_full = -min_x + pad_x
    shift_y_full = -min_y + pad_top
    return camera, active_mask, plinth_z, W_full, H_full, shift_x_full, shift_y_full, r0, r1, c0, c1


def _shade_drawn_ground_90s(
    scene: SceneData,
    ge: np.ndarray,
    gn: np.ndarray,
    gz: np.ndarray,
    gsem: np.ndarray,
    glake: np.ndarray,
    gbathy: np.ndarray,
    gharbor: np.ndarray,
    raw_ortho: np.ndarray,
    rd_dist: np.ndarray,
    rd_along: np.ndarray,
    rd_hw: np.ndarray,
    rl_dist: np.ndarray,
    rl_along: np.ndarray,
    xwalk: np.ndarray,
    gnx: np.ndarray,
    gny: np.ndarray,
    gnz: np.ndarray,
    sub_chm_val: np.ndarray,
    preset_key: str = "day",
    mpp: float = 0.25,
    dist_lake: np.ndarray | None = None,
    gz_smooth: np.ndarray | None = None,
    pier_sdf: np.ndarray | None = None,
    pier_h_val: np.ndarray | None = None,
    lake_sdf: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """V6.0/v10 Museum-Grade 90s Pixel-Art Ground Shader:
    - Organic wildflower Swiss alpine meadows & lush manicured residential garden lawns (ZERO fake mowing stripes,
      ZERO dirty grey concrete soup in shaded yards!)
    - Exact vector FIFA regulation football pitches (alternating mown turf + crisp white markings)
    - Exact vector ITF Roland-Garros clay tennis courts (crisp clay apron + regulation white court lines)
    - Exact vector multi-sport school courts, terraced vineyards, stone-banked Swiss streams, road-aligned parking,
      crisp limestone-coped swimming pools, clean asphalt streets & SBB railway tracks."""
    n_pts = len(ge)
    gcol = np.empty((n_pts, 3), dtype=np.float32)
    gmat = np.full(n_pts, M_GROUND, dtype=np.uint8)
    g_seebad_pool = np.zeros(n_pts, dtype=np.bool_)
    ro = raw_ortho.astype(np.float32)
    lum = 0.299 * ro[:, 0] + 0.587 * ro[:, 1] + 0.114 * ro[:, 2]

    # Deterministic pixel-art micro-pattern coordinates scaled to 1px at camera.mpp!
    tex_scale = 1.0 / max(0.08, float(mpp))
    ix25 = np.floor((ge - E_MIN) * tex_scale).astype(np.int32)
    iy25 = np.floor((gn - N_MIN) * tex_scale).astype(np.int32)
    ix50 = np.floor((ge - E_MIN) * 2.0).astype(np.int32)
    iy50 = np.floor((gn - N_MIN) * 2.0).astype(np.int32)
    p_hash = ((ix25 * 73856093) ^ (iy25 * 19349663)) & 0xFF
    h50 = ((ix50 * 83492791) ^ (iy50 * 40503)) & 0xFF
    wf_hash = ((ix25 * 19349663) ^ (iy25 * 83492791) ^ 0x5A3C) & 0x3FF

    c05 = np.clip(((ge - E_MIN) * 2.0).astype(np.int32), 0, GRID_W - 1)
    r05 = np.clip(((N_MAX - gn) * 2.0).astype(np.int32), 0, GRID_H - 1)
    if mpp <= 0.18:
        m_noise = _sample_bilinear_05m(scene.meadow_noise_05m, ge, gn)
        is_pave = _sample_bilinear_05m(scene.yard_pave_sdf_05m, ge, gn) >= 0.5
        ro_sm = _sample_bilinear_rgb_05m(scene.ortho_roof_smooth_05m, ge, gn)
    else:
        m_noise = scene.meadow_noise_05m[r05, c05].astype(np.float32)
        is_pave = scene.yard_pave_mask_05m[r05, c05]
        ro_sm = scene.ortho_roof_smooth_05m[r05, c05].astype(np.float32)
    is_pool_rim = scene.pool_rim_05m[r05, c05]

    # 1. v12 Clean 3-Band Cel-Shaded Swiss Alpine Meadows & Garden Lawns (ZERO p_hash static!)
    lawn_col = np.where(
        (m_noise > 0.55)[:, None],
        [102.0, 164.0, 66.0],
        np.where((m_noise > -0.35)[:, None], [76.0, 142.0, 56.0], [58.0, 120.0, 48.0]),
    ).astype(np.float32)

    # Occasional tiny alpine wildflowers (golden buttercups & white daisies) in open meadows!
    open_meadow = (gsem == G_TERRAIN) & (~is_pave) & (rd_dist > 5.5)
    daisy = open_meadow & (wf_hash == 17)
    buttercup = open_meadow & (wf_hash == 53)
    if daisy.any():
        lawn_col[daisy] = [238.0, 240.0, 230.0]
    if buttercup.any():
        lawn_col[buttercup] = [240.0, 212.0, 86.0]

    # Deep mossy woodland floor under forests (G_FOREST) — smooth 2-band cel tone
    is_for = gsem == G_FOREST
    if is_for.any():
        lawn_col[is_for] = np.where((m_noise[is_for] > 0.0)[:, None], [52.0, 96.0, 46.0], [40.0, 78.0, 40.0]).astype(np.float32)

    # Manicured park, orchard & cemetery emerald turf with smooth SDF warm limestone gravel walkways + Ref. Kirche headstones
    is_park = gsem == G_PARK_CEMETERY
    if is_park.any():
        if mpp <= 0.18:
            pg_sdf = _sample_bilinear_05m(scene.park_gravel_sdf_05m, ge, gn)
            park_gravel = is_park & (pg_sdf >= 0.50)
        else:
            park_gravel = is_park & (scene.park_gravel_sdf_05m[r05, c05] >= 0.50)
        lawn_col[is_park] = np.where((m_noise[is_park] > 0.15)[:, None], [74.0, 142.0, 58.0], [60.0, 124.0, 50.0]).astype(np.float32)
        lawn_col[park_gravel] = [188.0, 178.0, 158.0]

        # F14c: Reformierte Kirche Cemetery (-10.5 deg aligned 1px limestone headstone rows!)
        in_cem = (
            is_park
            & (~park_gravel)
            & (ge >= 2683375.0)
            & (ge <= 2683500.0)
            & (gn >= 1241053.0)
            & (gn <= 1241314.0)
            & (~scene.bldg_roof_mask[r05, c05])
            & (~scene.hedge_mask[r05, c05])
        )
        if in_cem.any():
            ci_c = np.nonzero(in_cem)[0]
            cth = math.cos(math.radians(-10.5))
            sth = math.sin(math.radians(-10.5))
            cu = (ge[ci_c] - 2683375.0) * cth + (gn[ci_c] - 1241053.0) * sth
            cv = -(ge[ci_c] - 2683375.0) * sth + (gn[ci_c] - 1241053.0) * cth
            gu_id = np.floor(cu / 2.4).astype(np.int32)
            gv_id = np.floor(cv / 3.4).astype(np.int32)
            g_occ = (((gu_id * 73856093) ^ (gv_id * 19349663)) & 3) != 0  # ~75% occupied
            u_m = cu % 2.4
            v_m = cv % 3.4
            is_stone = g_occ & (u_m < 0.42) & (v_m < 0.44)
            is_st_sh = g_occ & (u_m >= 0.42) & (u_m < 0.85) & (v_m < 0.55)
            is_plot = g_occ & (u_m >= 0.08) & (u_m < 1.10) & (v_m >= 0.44) & (v_m < 1.45)
            lawn_col[ci_c[is_plot]] = [46.0, 94.0, 44.0]
            lawn_col[ci_c[is_st_sh]] = [44.0, 86.0, 40.0]
            lawn_col[ci_c[is_stone]] = [214.0, 210.0, 200.0]
            gz[ci_c[is_stone]] += 0.65

    # Clean Jura limestone patios, terraces & paved residential driveways (smooth SDF edges & smoothed warm tone!)
    pave_joint = ((ix25 % 8) == 0) | ((iy25 % 8) == 0)
    is_warm_yard = (ro_sm[:, 0] - ro_sm[:, 2]) > 10.0
    yard_col = np.where(is_warm_yard[:, None], [202.0, 190.0, 168.0], [182.0, 178.0, 170.0]).astype(np.float32)
    yard_col[pave_joint] *= 0.93

    is_lawn = (~is_pave) | is_for | is_park
    gcol[:] = np.where(is_lawn[:, None], lawn_col, yard_col)

    # 1b. v11 Landmark Plazas & Formal Gardens (Enea dark charcoal Schokoladenplatz & Broelberggut parterre)
    in_lindt_plaza = (
        (ge >= 2684106.0) & (ge <= 2684152.0) & (gn >= 1241392.0) & (gn <= 1241436.0)
        & (~glake) & (~scene.bldg_roof_mask[r05, c05]) & (~scene.hedge_mask[r05, c05])
        & (gsem != G_STREET_MAIN) & (gsem != G_RAILWAY)
    )
    if in_lindt_plaza.any():
        lpi = np.nonzero(in_lindt_plaza)[0]
        # Real Enea Schokoladenplatz: dark charcoal-anthracite linear brushed paving flush to HoC entrance
        lp_stripe = (((ge[lpi] * 0.72 + gn[lpi] * 0.69) % 1.6) < 0.22)
        lp_col = np.where(lp_stripe[:, None], [64.0, 66.0, 70.0], [76.0, 78.0, 82.0]).astype(np.float32)
        lp_rad = np.hypot(ge[lpi] - 2684129.0, gn[lpi] - 1241414.0)
        lp_edge = (lp_rad >= 18.5) & (lp_rad <= 19.3)
        lp_col[lp_edge] = [94.0, 96.0, 100.0]
        gcol[lpi] = lp_col
        gz[lpi] += 0.06

    # M3.5 Seebad Kilchberg pebble beach (Kiesstrand) shoreline gravel strip
    in_seebad_beach = (
        (ge >= 2684290.0) & (ge <= 2684326.0) & (gn >= 1241448.0) & (gn <= 1241515.0)
        & (~glake) & (~scene.bldg_roof_mask[r05, c05]) & (gsem == G_TERRAIN) & (gz < 407.6)
    )
    if in_seebad_beach.any():
        sbi = np.nonzero(in_seebad_beach)[0]
        sb_col = np.full((len(sbi), 3), [186.0, 180.0, 168.0], dtype=np.float32)
        sb_col[p_hash[sbi] < 72] *= 0.93
        sb_col[p_hash[sbi] > 184] *= 1.04
        gcol[sbi] = np.clip(sb_col, 0.0, 240.0)

    # v11 Broelberggut arrival gravel courtyard: strictly WEST of Alte Landstrasse (ge <= 2683770.0)
    in_broel_court = (
        (
            ((ge >= 2683746.0) & (ge <= 2683770.0) & (gn >= 1241258.0) & (gn <= 1241284.0))
            | ((ge >= 2683754.0) & (ge <= 2683770.0) & (gn >= 1241228.0) & (gn <= 1241258.0))
        )
        & (~glake) & (~scene.bldg_roof_mask[r05, c05]) & (~scene.hedge_mask[r05, c05])
        & (rd_dist > 2.2)
        & ((gsem == G_TERRAIN) | (gsem == G_PARK_CEMETERY))
    )
    if in_broel_court.any():
        bci = np.nonzero(in_broel_court)[0]
        gcol[bci] = [186.0, 182.0, 172.0]

    # v11 Broelberggut walled parterre garden: real rectangular garden south of 1074
    in_broel_parterre = (
        (ge >= 2683724.0) & (ge <= 2683742.0) & (gn >= 1241242.0) & (gn <= 1241258.0)
        & (~glake) & (~scene.bldg_roof_mask[r05, c05]) & (~scene.hedge_mask[r05, c05])
        & ((gsem == G_TERRAIN) | (gsem == G_PARK_CEMETERY))
    )
    if in_broel_parterre.any():
        bpi = np.nonzero(in_broel_parterre)[0]
        ba = math.radians(-22.0)
        cba, sba = math.cos(ba), math.sin(ba)
        b_de = ge[bpi] - 2683733.0
        b_dn = gn[bpi] - 1241250.0
        bu = b_de * cba + b_dn * sba
        bv = -b_de * sba + b_dn * cba
        in_x_path = (np.abs(bu) <= 0.95) | (np.abs(bv) <= 0.95)
        in_bed_box = (np.abs(bu) >= 1.15) & (np.abs(bu) <= 7.2) & (np.abs(bv) >= 1.15) & (np.abs(bv) <= 5.8)
        on_boxwood = in_bed_box & (
            (np.abs(np.abs(bu) - 1.15) <= 0.60) | (np.abs(np.abs(bu) - 7.2) <= 0.60)
            | (np.abs(np.abs(bv) - 1.15) <= 0.60) | (np.abs(np.abs(bv) - 5.8) <= 0.60)
        )
        gcol[bpi[in_x_path]] = [186.0, 182.0, 172.0]
        if on_boxwood.any():
            bwi = bpi[on_boxwood]
            gcol[bwi] = np.where((p_hash[bwi] < 110)[:, None], [34.0, 72.0, 38.0], [44.0, 88.0, 46.0]).astype(np.float32)
            gz[bwi] += 0.55

    # 2. F14b: Terraced Kilchberg Vineyards (G_VINEYARD + verified real Weinberg / Gmeindsrebberg / Stocken / Böndler slopes!)
    not_obs = (~scene.bldg_roof_mask[r05, c05]) & (~scene.hedge_mask[r05, c05]) & (~glake)
    in_gmeindsreb = (
        (gsem == G_TERRAIN)
        & not_obs
        & (rd_dist > 2.6)
        & (ge >= 2683630.0)
        & (ge <= 2683662.0)
        & (gn >= 1242232.0)
        & (gn <= 1242290.0)
    )
    in_stocken_trellis = (
        (gsem == G_PARK_CEMETERY)
        & not_obs
        & (ge >= 2683417.0)
        & (ge <= 2683508.0)
        & (gn >= 1241951.0)
        & (gn <= 1242118.0)
    )
    in_boendler_trellis = (
        (gsem == G_PARK_CEMETERY)
        & not_obs
        & (ge >= 2683753.0)
        & (ge <= 2683954.0)
        & (gn >= 1240562.0)
        & (gn <= 1240746.0)
    )
    in_bahnhof_weinberg = (
        (gsem == G_TERRAIN)
        & not_obs
        & (rd_dist > 3.5)
        & (rl_dist > 4.5)
        & (
            ((ge >= 2683648.0) & (ge <= 2683670.0) & (gn >= 1242115.0) & (gn <= 1242180.0))
            | ((ge >= 2683900.0) & (ge <= 2683955.0) & (gn >= 1241608.0) & (gn <= 1241698.0))
        )
    )
    is_vin = (gsem == G_VINEYARD) | in_gmeindsreb | in_stocken_trellis | in_boendler_trellis | in_bahnhof_weinberg
    if is_vin.any():
        vi = np.nonzero(is_vin)[0]
        ve_v = ge[vi]
        vn_v = gn[vi]
        is_st_v = in_stocken_trellis[vi]
        is_gm_v = in_gmeindsreb[vi]
        pitch_v = np.where(is_st_v, 2.65, np.where(is_gm_v, 2.05, 2.20))
        u_perp = np.where(is_gm_v, ve_v * 0.995 + vn_v * 0.10, ve_v * 0.955 + vn_v * 0.296)
        v_along = np.where(is_gm_v, -ve_v * 0.10 + vn_v * 0.995, -ve_v * 0.296 + vn_v * 0.955)
        u_row = u_perp % pitch_v
        row_id = np.floor(u_perp / pitch_v)
        on_vine = u_row < 0.85
        vine_sh = (u_row >= 0.85) & (u_row < 1.25)
        # v13.0: Clean cel-shaded tilled-earth furrow + neat mowed-grass alley (ZERO p_hash per-pixel noise!)
        vcol = np.full((len(vi), 3), [112.0, 92.0, 68.0], dtype=np.float32)
        cover_crop = (u_row >= 1.32) & (u_row <= (pitch_v - 0.28))
        vcol[cover_crop] = [86.0, 122.0, 58.0]
        vcol[vine_sh] *= 0.72
        # Smooth deterministic world-space trellised grapevine leaf clusters (3-step cel-shaded)
        clump_v = 0.5 + 0.5 * np.sin(v_along * 2.2 + row_id * 1.7) * np.cos(u_row * 3.2 - 0.6)
        vine_leaf = np.where(
            ((u_row < 0.44) & (clump_v > 0.46))[:, None],
            [86.0, 146.0, 50.0],
            np.where(((u_row < 0.68) & (clump_v > 0.28))[:, None], [58.0, 114.0, 44.0], [36.0, 78.0, 34.0]),
        ).astype(np.float32)
        vcol[on_vine] = vine_leaf[on_vine]
        # Crisp wooden trellis end-posts every 11m
        on_post = ((v_along % 11.0) < 0.38) & (u_row >= 0.22) & (u_row <= 0.62)
        vcol[on_post] = [118.0, 86.0, 56.0]
        # Jura dry-stone terrace retaining walls on sloped vineyard contours (smooth world-space blocks, zero noise)
        on_terrace = ((gnz[vi] < 0.975) & ((gz[vi] % 2.8) < 0.38)) | (is_gm_v & (np.abs(vn_v - 1242258.0) < 0.65))
        if on_terrace.any():
            stone_hi = np.sin(v_along[on_terrace] * 1.4) >= 0.0
            vcol[on_terrace] = np.where(stone_hi[:, None], [168.0, 160.0, 144.0], [146.0, 138.0, 124.0]).astype(np.float32)
        gcol[vi] = vcol
        gz[vi[on_vine & (~on_terrace)]] += 0.95
        gz[vi[on_post & (~on_terrace)]] += 0.30
        gz[vi[on_terrace]] += 0.55

    # 3. MUSEUM-GRADE VECTOR SPORTS FIELDS: Football Pitches, Roland-Garros Tennis Courts & Multi-Sport Courts!
    # First give any fallback G_PITCH cell clean lush turf, then paint exact vector markings for every extracted entity!
    is_pitch_sem = gsem == G_PITCH
    if is_pitch_sem.any():
        gcol[is_pitch_sem] = [66.0, 138.0, 58.0]

    ge_min_b = float(ge.min()) - 8.0
    ge_max_b = float(ge.max()) + 8.0
    gn_min_b = float(gn.min()) - 8.0
    gn_max_b = float(gn.max()) + 8.0

    for sf in scene.sports_fields:
        fe_c, fn_c = float(sf["e"]), float(sf["n"])
        L_f, W_f = float(sf["length"]), float(sf["width"])
        ang = float(sf["angle"])
        kind = sf["kind"]
        rad_max = 0.5 * math.hypot(L_f, W_f) + 6.0
        if fe_c + rad_max < ge_min_b or fe_c - rad_max > ge_max_b or fn_c + rad_max < gn_min_b or fn_c - rad_max > gn_max_b:
            continue

        near = (np.abs(ge - fe_c) <= rad_max) & (np.abs(gn - fn_c) <= rad_max)
        if not near.any():
            continue
        ni = np.nonzero(near)[0]
        de = ge[ni] - fe_c
        dn = gn[ni] - fn_c
        ca, sa = math.cos(ang), math.sin(ang)
        # Local pitch axes: u along length [-L/2, L/2], v along width [-W/2, W/2]
        u = de * ca + dn * sa
        v = -de * sa + dn * ca
        au = np.abs(u)
        av = np.abs(v)

        if kind == "football":
            # Playing field inset cleanly inside MVT polygon (apron ~2.0m; v11: no fabricated 400m athletics track)
            hl = max(28.0, 0.5 * L_f - 2.2)
            hw = max(18.0, 0.5 * W_f - 2.0)

            in_apron = (au <= hl + 2.8) & (av <= hw + 2.6) & (~glake[ni])
            if not in_apron.any():
                continue
            ai = ni[in_apron]
            ua, va, aua, ava = u[in_apron], v[in_apron], au[in_apron], av[in_apron]
            in_play = (aua <= hl) & (ava <= hw)

            # Lush Wimbledon/Swiss stadium alternating mown turf stripes (6.5m bands perpendicular to pitch length!)
            stripe = ((np.floor((ua + hl) / 6.5).astype(np.int32)) & 1) == 0
            fcol = np.full((len(ai), 3), [52.0, 118.0, 48.0], dtype=np.float32)  # Deeper green perimeter apron
            fcol[in_play & (~stripe)] = [58.0, 134.0, 52.0]
            fcol[in_play & stripe] = [74.0, 152.0, 62.0]
            # Subtle crisp pixel turf texture
            fcol[p_hash[ai] < 38] += [5.0, 8.0, 3.0]
            fcol[(p_hash[ai] >= 38) & (p_hash[ai] < 72)] -= [5.0, 7.0, 3.0]

            # Razor-sharp FIFA regulation white pitch markings (lw = 0.36m crisp architectural lines!)
            lw = 0.36
            # Outer touchlines & goal lines
            on_line = (
                ((np.abs(aua - hl) <= lw) & (ava <= hw + lw))
                | ((np.abs(ava - hw) <= lw) & (aua <= hl + lw))
            )
            # Halfway line + Center circle (R = min(9.15m, hw*0.36)) + Center spot
            r_cc = min(9.15, hw * 0.36)
            r_cent = np.hypot(ua, va)
            on_line |= (aua <= lw * 0.9) & (ava <= hw)
            on_line |= np.abs(r_cent - r_cc) <= lw
            on_line |= r_cent <= 0.65

            # Both 18-yard penalty areas & 6-yard goal areas (scaled smoothly for slightly narrower training pitches)
            pen_d = min(16.5, hl * 0.34)
            pen_hw = min(20.16, hw * 0.66)
            goal_d = min(5.5, hl * 0.12)
            goal_hw = min(9.16, hw * 0.32)
            pen_spot_u = hl - min(11.0, pen_d * 0.68)

            # Penalty box lines
            on_line |= (np.abs(aua - (hl - pen_d)) <= lw) & (ava <= pen_hw + lw)
            on_line |= (np.abs(ava - pen_hw) <= lw) & (aua >= hl - pen_d - lw) & (aua <= hl)
            # Goal area (6-yard box) lines
            on_line |= (np.abs(aua - (hl - goal_d)) <= lw) & (ava <= goal_hw + lw)
            on_line |= (np.abs(ava - goal_hw) <= lw) & (aua >= hl - goal_d - lw) & (aua <= hl)
            # Penalty spots + Penalty arcs outside penalty box
            r_pen = np.hypot(aua - pen_spot_u, va)
            on_line |= r_pen <= 0.54
            on_line |= (np.abs(r_pen - r_cc) <= lw) & (aua < (hl - pen_d))
            # Four corner arcs (R = 1.65m)
            r_cor = np.hypot(hl - aua, hw - ava)
            on_line |= in_play & (np.abs(r_cor - 1.65) <= lw)

            fcol[on_line] = [238.0, 240.0, 236.0]
            gcol[ai] = fcol

        elif kind in ("tennis", "tennis_pad"):
            # ITF Regulation Clay Tennis Court: 23.77m x 10.97m playing area inside rich terracotta clay apron!
            hl_c = 11.885
            hw_d = 5.485
            hw_s = 4.115
            u_srv = 6.40
            # Clay runoff apron joins adjacent side-by-side club courts cleanly without narrow grass slivers
            hl_ap = max(hl_c + 2.4, 0.5 * L_f + 1.2)
            hw_ap = max(hw_d + 2.1, 0.5 * W_f + 1.35)
            in_apron = (au <= hl_ap) & (av <= hw_ap) & (~glake[ni])
            if not in_apron.any():
                continue
            ai = ni[in_apron]
            aua, ava = au[in_apron], av[in_apron]
            in_court = (aua <= hl_c) & (ava <= hw_d)

            # Rich Roland-Garros terracotta clay (deeper burnt-clay runoff apron + warm vibrant red-clay court!)
            ccol = np.full((len(ai), 3), [158.0, 74.0, 48.0], dtype=np.float32)
            ccol[in_court] = [188.0, 92.0, 56.0]
            # Subtle swept dusty-clay baseline wear zone
            base_wear = (aua >= (hl_c - 1.5)) & (aua <= (hl_c + 1.2)) & (ava <= hw_d + 0.5)
            ccol[base_wear] = [198.0, 106.0, 68.0]
            # Fine 2-tone pixel-art rolled red-clay grain
            ccol[p_hash[ai] < 52] += [8.0, 5.0, 3.0]
            ccol[(p_hash[ai] >= 52) & (p_hash[ai] < 96)] -= [7.0, 4.0, 3.0]
            # Crisp dark-green perimeter apron border line on baselines
            border_c = (np.abs(aua - hl_ap) <= 0.35)
            ccol[border_c] = [44.0, 86.0, 46.0]

            # Razor-sharp ITF white regulation court lines (lw = 0.32m so every line pops clearly!)
            lw = 0.32
            on_line = (
                # Baselines & doubles sidelines
                ((np.abs(aua - hl_c) <= lw) & (ava <= hw_d + lw))
                | ((np.abs(ava - hw_d) <= lw) & (aua <= hl_c + lw))
                # Singles sidelines
                | ((np.abs(ava - hw_s) <= lw) & (aua <= hl_c))
                # Service lines
                | ((np.abs(aua - u_srv) <= lw) & (ava <= hw_s))
                # Center service line + crisp T-tick
                | ((ava <= lw * 0.90) & (aua <= u_srv + lw))
                # Center baseline hash marks
                | ((ava <= lw * 0.85) & (aua >= hl_c - 0.65) & (aua <= hl_c))
            )
            ccol[on_line] = [242.0, 242.0, 238.0]
            # Subtle dark shadow directly beneath the center tennis net (u ≈ 0)
            net_sh = (aua <= 0.42) & (ava <= hw_d + 0.9)
            ccol[net_sh] *= 0.76
            gcol[ai] = ccol

        elif kind == "multisport":
            # Crisp Swiss red-tartan schoolyard basketball/handball court inside clean slate surround
            hl = max(10.0, 0.5 * L_f - 1.4)
            hw = max(6.5, 0.5 * W_f - 1.2)
            in_apron = (au <= hl + 1.8) & (av <= hw + 1.6) & (~glake[ni])
            if not in_apron.any():
                continue
            ai = ni[in_apron]
            aua, ava = au[in_apron], av[in_apron]
            in_play = (aua <= hl) & (ava <= hw)
            mcol = np.full((len(ai), 3), [104.0, 108.0, 114.0], dtype=np.float32)  # Slate surround
            mcol[in_play] = [164.0, 76.0, 58.0]  # Red-ochre tartan sport surface
            mcol[p_hash[ai] < 48] += [5.0, 4.0, 3.0]
            lw = 0.34
            r_cc = min(3.2, hw * 0.34)
            r_cent = np.hypot(aua, ava)
            on_line = (
                ((np.abs(aua - hl) <= lw) & (ava <= hw + lw))
                | ((np.abs(ava - hw) <= lw) & (aua <= hl + lw))
                | ((aua <= lw * 0.85) & (ava <= hw))
                | (np.abs(r_cent - r_cc) <= lw)
                | (np.abs(np.hypot(hl - aua, ava) - min(5.2, hw * 0.56)) <= lw) & in_play
            )
            mcol[on_line] = [238.0, 240.0, 236.0]
            gcol[ai] = mcol

    # 4. Streams (G_STREAM — Dorfbach): natural mossy stone-banked Swiss alpine brook (no neon cyan!)
    is_str = gsem == G_STREAM
    if is_str.any():
        si = np.nonzero(is_str)[0]
        # Riffle sparkle + cool mossy alpine stream tones
        scol = np.where((p_hash[si] < 85)[:, None], [44.0, 92.0, 104.0], [34.0, 78.0, 92.0]).astype(np.float32)
        scol[p_hash[si] > 236] = [148.0, 188.0, 194.0]  # Tiny 1px white water riffle sparkle
        scol[h50[si] < 32] = [74.0, 98.0, 68.0]         # Mossy pebble bank edge
        gcol[si] = scol
        gz[si] -= 0.25

    # v12 Iter2: Sub-pixel smooth SDF masks for footpaths, parking lots & station platforms (ZERO 0.5m staircases!)
    if mpp <= 0.18:
        fp_sdf = _sample_bilinear_05m(scene.footpath_sdf_05m, ge, gn)
        pk_sdf = _sample_bilinear_05m(scene.parking_sdf_05m, ge, gn)
        pl_sdf = _sample_bilinear_05m(scene.platform_sdf_05m, ge, gn)
        is_fp = (fp_sdf >= 0.50) & (~glake) & (gsem != G_RAILWAY) & (gsem != G_POOL)
        is_pk = (pk_sdf >= 0.50) & (~glake) & (gsem != G_RAILWAY) & (gsem != G_POOL)
        is_pl = (pl_sdf >= 0.50) & (~glake)
    else:
        fp_sdf = pk_sdf = pl_sdf = None
        is_fp = gsem == G_FOOTPATH
        is_pk = gsem == G_PARKING
        is_pl = (gsem == G_PLATFORM_PIER) & (~glake)

    # 5. Footpaths & Garden Walkways (G_FOOTPATH): smooth warm sand-limestone paving + crisp edge trim!
    if is_fp.any():
        fi = np.nonzero(is_fp)[0]
        if gz_smooth is not None:
            gz[fi] = gz_smooth[fi]
        fcol = np.full((len(fi), 3), [196.0, 184.0, 162.0], dtype=np.float32)
        if fp_sdf is not None:
            fp_edge = fp_sdf[fi] < 0.62
            fcol[fp_edge] = [148.0, 138.0, 120.0]
        gcol[fi] = fcol

    # 5a. v11 Morfanlage Weathered Jura-Stone Embankment & Fine-Gravel Promenade (strictly N=1242334..1242402)
    in_morf = (
        (ge >= 2683868.0) & (ge <= 2683930.0) & (gn >= 1242334.0) & (gn <= 1242402.0)
        & (~glake) & (~scene.bldg_roof_mask[r05, c05]) & (~scene.hedge_mask[r05, c05])
        & ((gsem == G_TERRAIN) | (gsem == G_PARK_CEMETERY) | is_fp)
    )
    if in_morf.any():
        mfi = np.nonzero(in_morf)[0]
        mr, mc = r05[mfi], c05[mfi]
        near_l1 = (
            scene.lake_mask[np.clip(mr, 0, GRID_H - 1), np.clip(mc + 1, 0, GRID_W - 1)]
            | scene.lake_mask[np.clip(mr, 0, GRID_H - 1), np.clip(mc + 2, 0, GRID_W - 1)]
            | scene.lake_mask[np.clip(mr - 1, 0, GRID_H - 1), np.clip(mc + 2, 0, GRID_W - 1)]
            | scene.lake_mask[np.clip(mr + 1, 0, GRID_H - 1), np.clip(mc + 2, 0, GRID_W - 1)]
        )
        near_l2 = (
            (~near_l1)
            & (
                scene.lake_mask[np.clip(mr, 0, GRID_H - 1), np.clip(mc + 4, 0, GRID_W - 1)]
                | scene.lake_mask[np.clip(mr, 0, GRID_H - 1), np.clip(mc + 7, 0, GRID_W - 1)]
                | scene.lake_mask[np.clip(mr - 3, 0, GRID_H - 1), np.clip(mc + 5, 0, GRID_W - 1)]
                | scene.lake_mask[np.clip(mr + 3, 0, GRID_H - 1), np.clip(mc + 5, 0, GRID_W - 1)]
            )
        )
        if near_l1.any():
            qi = mfi[near_l1]
            q_joint = ((gn[qi] % 1.25) < 0.16)
            gcol[qi] = np.where(q_joint[:, None], [114.0, 110.0, 102.0], [146.0, 142.0, 132.0]).astype(np.float32)
            gz[qi] += 0.22
        if near_l2.any():
            pi_m = mfi[near_l2]
            gcol[pi_m] = [182.0, 174.0, 158.0]

    # 5b. F14c: Hillside Stone Staircases (M1 steps_mask strictly on smooth footpath & ~glake)
    is_st = scene.steps_mask[r05, c05] & is_fp & (~glake)
    if is_st.any():
        sti = np.nonzero(is_st)[0]
        ang_s = scene.steps_ang[r05[sti], c05[sti]].astype(np.float32)
        dist_s = scene.steps_dist[r05[sti], c05[sti]].astype(np.float32)
        tread_pitch = 0.64
        phase = (ge[sti] * np.cos(ang_s) + gn[sti] * np.sin(ang_s)) % tread_pitch
        on_tread = phase < (tread_pitch * 0.58)
        on_curb = dist_s >= 0.72
        st_col = np.where(on_tread[:, None], [204.0, 196.0, 182.0], [118.0, 112.0, 104.0]).astype(np.float32)
        st_col[on_curb] = [158.0, 152.0, 142.0]
        gcol[sti] = st_col
        gz[sti[on_tread & (~on_curb)]] += 0.10
        gz[sti[on_curb]] += 0.24

    # 6. Parking Lots (G_PARKING): smooth cool-slate asphalt + crisp white bays + smooth dark curb!
    if is_pk.any():
        ki = np.nonzero(is_pk)[0]
        if gz_smooth is not None:
            gz[ki] = gz_smooth[ki]
        kcol = np.full((len(ki), 3), [94.0, 104.0, 116.0], dtype=np.float32)
        pk_ang = math.radians(28.5)
        ck, sk = math.cos(pk_ang), math.sin(pk_ang)
        ku = (ge[ki] - E_MIN) * ck + (gn[ki] - N_MIN) * sk
        kv = -(ge[ki] - E_MIN) * sk + (gn[ki] - N_MIN) * ck
        # Structured 15.4m parking module: 4.8m bay A + 0.2m head stripe + 4.8m bay B + 5.6m clean driving aisle
        kv_m = kv % 15.4
        in_bay = kv_m < 9.8
        head_line = np.abs(kv_m - 4.9) < 0.18
        stall_div = in_bay & ((ku % 2.65) < 0.20)
        end_tick = (np.abs(kv_m) < 0.18) | (np.abs(kv_m - 9.8) < 0.18)
        kcol[stall_div | head_line] = [232.0, 236.0, 240.0]
        kcol[end_tick & ((ku % 2.65) < 0.55)] = [212.0, 216.0, 222.0]
        aisle_mid = (kv_m >= 11.4) & (kv_m <= 13.8)
        kcol[aisle_mid] *= 0.96
        if pk_sdf is not None:
            pk_curb = pk_sdf[ki] < 0.64
            kcol[pk_curb] = [56.0, 64.0, 76.0]
        gcol[ki] = kcol

    # v12: Sub-pixel smooth road boundary using exact continuous rd_dist <= rd_hw (eliminates 4x4 px stair-stepping!)
    can_road = (~glake) & (gsem != G_RAILWAY) & (~is_pl) & (gsem != G_POOL) & (~is_pk) & (gsem != G_STREAM) & (gsem != G_PITCH)
    is_mw_smooth = ((gsem == G_MOTORWAY) & (rd_dist <= (rd_hw + 0.25))) | (can_road & (rd_hw >= 4.85) & (rd_dist <= rd_hw))
    is_main_smooth = can_road & (~is_mw_smooth) & (rd_hw >= 3.85) & (rd_hw < 4.85) & (rd_dist <= rd_hw)
    is_min_smooth = can_road & (~is_mw_smooth) & (~is_main_smooth) & (rd_hw >= 1.50) & (rd_hw < 3.85) & (rd_dist <= rd_hw)

    # 7. Minor Village Streets (G_STREET_MINOR): smooth cool-slate asphalt + warm cream curb/sidewalk + crisp dark curb!
    if is_min_smooth.any():
        mi = np.nonzero(is_min_smooth)[0]
        if gz_smooth is not None:
            gz[mi] = gz_smooth[mi]
        m_d = rd_dist[mi]
        m_hw = np.maximum(1.85, rd_hw[mi])
        mcol = np.full((len(mi), 3), [108.0, 118.0, 130.0], dtype=np.float32)
        has_sw_m = m_hw >= 2.25
        curb_outer = m_d >= (m_hw - 0.20)
        on_sw_m = has_sw_m & (m_d >= (m_hw - 0.72)) & (~curb_outer)
        on_curb_m = np.where(has_sw_m, (m_d >= (m_hw - 0.96)) & (m_d < (m_hw - 0.72)), (m_d >= (m_hw - 0.44)) & (~curb_outer))
        mcol[on_sw_m] = [218.0, 204.0, 178.0]
        mcol[on_curb_m] = [52.0, 60.0, 72.0]
        mcol[curb_outer] = [66.0, 74.0, 84.0]
        gz[mi[on_sw_m]] += 0.14
        gcol[mi] = mcol

    # 8. Main Roads (G_STREET_MAIN): smooth cool blue-slate asphalt + crisp white dashes + warm-cream sidewalks + dark curbs!
    if is_main_smooth.any():
        ai = np.nonzero(is_main_smooth)[0]
        if gz_smooth is not None:
            gz[ai] = gz_smooth[ai]
        a_d = rd_dist[ai]
        a_s = rd_along[ai]
        a_hw = np.maximum(3.85, rd_hw[ai])
        sw_start = a_hw - 1.32

        acol = np.full((len(ai), 3), [100.0, 110.0, 124.0], dtype=np.float32)
        edge_line = np.abs(a_d - (sw_start - 0.44)) < 0.14
        dash_c = (a_d < 0.24) & ((a_s % 5.6) < 2.5)
        acol[edge_line | dash_c] = [242.0, 244.0, 246.0]

        on_curb = (a_d >= (sw_start - 0.26)) & (a_d < sw_start)
        on_sw = (a_d >= sw_start) & (a_d < (a_hw - 0.18))
        sw_outer = a_d >= (a_hw - 0.18)
        acol[on_curb] = [44.0, 52.0, 64.0]
        sw_joint = on_sw & ((a_s % 2.2) < 0.18)
        acol[on_sw] = [224.0, 210.0, 182.0]
        acol[sw_joint] = [202.0, 188.0, 162.0]
        acol[sw_outer] = [56.0, 64.0, 76.0]
        gz[ai[on_sw]] += 0.18
        gcol[ai] = acol

    # 8b. Crisp Geometric Swiss Yellow Zebra Crosswalks on Main Roads!
    is_xw = xwalk & is_main_smooth
    if is_xw.any():
        xi = np.nonzero(is_xw)[0]
        bar = ((rd_dist[xi] % 0.95) < 0.48) & (rd_dist[xi] <= np.maximum(2.0, rd_hw[xi] - 1.45))
        gcol[xi[bar]] = [242.0, 202.0, 60.0]

    # 9. A3 Motorway (G_MOTORWAY): smooth highway asphalt, crisp lane dashes, white shoulders & steel barriers
    if is_mw_smooth.any():
        wi = np.nonzero(is_mw_smooth)[0]
        if gz_smooth is not None:
            gz[wi] = gz_smooth[wi]
        w_d = rd_dist[wi]
        w_s = rd_along[wi]
        w_hw = np.maximum(3.4, rd_hw[wi])
        wcol = np.full((len(wi), 3), [84.0, 94.0, 108.0], dtype=np.float32)
        w_dash = (np.abs(w_d - 1.8) < 0.24) & ((w_s % 6.5) < 2.8)
        w_edge = np.abs(w_d - (w_hw - 0.85)) < 0.24
        w_guard = w_d >= (w_hw - 0.42)
        wcol[w_dash | w_edge] = [240.0, 242.0, 246.0]
        wcol[w_guard] = [164.0, 170.0, 178.0]
        gz[wi[w_guard]] += 0.72
        gcol[wi] = wcol

    # 10. SBB Seebahn Railway (G_RAILWAY): smooth granite ballast, crisp sleepers & twin steel rails (ZERO speckle!)
    is_rl = gsem == G_RAILWAY
    if is_rl.any():
        ri = np.nonzero(is_rl)[0]
        r_d = rl_dist[ri]
        r_s = rl_along[ri]
        rcol = np.full((len(ri), 3), [118.0, 112.0, 104.0], dtype=np.float32)
        rcol[r_d > 2.05] = [94.0, 88.0, 80.0]
        sleeper = (r_d <= 1.22) & ((r_s % 0.85) < 0.30)
        rcol[sleeper] = [66.0, 54.0, 46.0]
        rail_steel = np.abs(r_d - 0.72) <= 0.22
        rcol[rail_steel] = [206.0, 212.0, 220.0]
        gz[ri[rail_steel]] += 0.14
        gcol[ri] = rcol
        gmat[ri] = M_RAIL

    # 11. SBB Station Platforms & Lakeside Stone Piers (G_PLATFORM_PIER): smooth raised concrete + coping + tactile safety edge!
    if is_pl.any():
        pli = np.nonzero(is_pl)[0]
        if gz_smooth is not None:
            gz[pli] = gz_smooth[pli]
        pcol = np.full((len(pli), 3), [178.0, 176.0, 170.0], dtype=np.float32)
        slab = ((ix50[pli] % 3) == 0) | ((iy50[pli] % 3) == 0)
        pcol[slab] = [158.0, 156.0, 150.0]
        tactile = (rl_dist[pli] >= 1.55) & (rl_dist[pli] <= 2.05)
        pcol[tactile] = [236.0, 236.0, 232.0]
        if pl_sdf is not None:
            pl_coping = pl_sdf[pli] < 0.65
            pcol[pl_coping] = [128.0, 126.0, 122.0]
        gcol[pli] = pcol
        gz[pli] += 0.58

    # 12. Crisp Swimming Pools (G_POOL) with white Jura-stone coping rim & Seebad swimming lanes!
    if is_pool_rim.any():
        gcol[is_pool_rim] = [220.0, 218.0, 212.0]
        sb_rim = is_pool_rim & (ge >= 2684235.0) & (ge <= 2684310.0) & (gn >= 1241435.0) & (gn <= 1241525.0)
        if sb_rim.any():
            gz[sb_rim] = np.minimum(gz[sb_rim], 405.85)
        gz[is_pool_rim] += 0.04
        gnx[is_pool_rim], gny[is_pool_rim], gnz[is_pool_rim] = 0.0, 0.0, 1.0
    is_pool = gsem == G_POOL
    if is_pool.any():
        p_i = np.nonzero(is_pool)[0]
        shimmer = ((ix25[p_i] + iy25[p_i]) & 3) == 0
        in_seebad = (ge[p_i] >= 2684235.0) & (ge[p_i] <= 2684310.0) & (gn[p_i] >= 1241435.0) & (gn[p_i] <= 1241525.0)
        if in_seebad.any():
            g_seebad_pool[p_i[in_seebad]] = True
        if preset_key == "night":
            # F7 + v10: Darken all 55 private pools to calm nocturnal slate-navy; exact tagged Seebad pool glow ONLY!
            pcol = np.where(shimmer[:, None], [24.0, 48.0, 68.0], [18.0, 36.0, 54.0]).astype(np.float32)
            if in_seebad.any():
                sb_c = np.where(shimmer[in_seebad, None], [48.0, 126.0, 146.0], [32.0, 92.0, 114.0]).astype(np.float32)
                pcol[in_seebad] = sb_c
                lane = in_seebad & ((((ge[p_i] * 0.85 - gn[p_i] * 0.52) % 2.4) < 0.24))
                pcol[lane] = [22.0, 62.0, 86.0]
        elif preset_key == "sunset":
            pcol = np.where(shimmer[:, None], [86.0, 168.0, 192.0], [48.0, 134.0, 166.0]).astype(np.float32)
            if in_seebad.any():
                lane = in_seebad & ((((ge[p_i] * 0.85 - gn[p_i] * 0.52) % 2.4) < 0.24))
                pcol[lane] = [34.0, 102.0, 138.0]
        else:
            pcol = np.where(shimmer[:, None], [116.0, 218.0, 238.0], [64.0, 186.0, 218.0]).astype(np.float32)
            if in_seebad.any():
                lane = in_seebad & ((((ge[p_i] * 0.85 - gn[p_i] * 0.52) % 2.4) < 0.24))
                pcol[lane] = [42.0, 134.0, 178.0]
        gcol[p_i] = pcol
        gnx[p_i], gny[p_i], gnz[p_i] = 0.0, 0.0, 1.0

    # 13. v13 M1B: Silky-Smooth 4-Band Lake Zurich Bathymetry + Crisp Solid Stone/Timber Pier Decks!
    if glake.any():
        li = np.nonzero(glake)[0]
        is_real_harbor_obj = gharbor[li]

        wi = li[~is_real_harbor_obj]
        if len(wi) > 0:
            depth_m = np.clip(LAKE_SURFACE_Z - gbathy[wi], 0.0, 65.0)
            d_dith = depth_m
            if preset_key == "day":
                c_b0 = np.array([68.0, 136.0, 118.0], dtype=np.float32)  # Sunlit turquoise-emerald shallows
                c_b1 = np.array([46.0, 112.0, 116.0], dtype=np.float32)  # Jade mid-shelf
                c_b2 = np.array([36.0, 92.0, 112.0], dtype=np.float32)   # Alpine teal
                c_b3 = np.array([28.0, 76.0, 108.0], dtype=np.float32)   # Deep sapphire
            elif preset_key == "sunset":
                c_b0 = np.array([62.0, 118.0, 106.0], dtype=np.float32)
                c_b1 = np.array([40.0, 96.0, 104.0], dtype=np.float32)
                c_b2 = np.array([32.0, 88.0, 108.0], dtype=np.float32)
                c_b3 = np.array([20.0, 72.0, 102.0], dtype=np.float32)
            else:
                c_b0 = np.array([46.0, 96.0, 94.0], dtype=np.float32)
                c_b1 = np.array([30.0, 74.0, 90.0], dtype=np.float32)
                c_b2 = np.array([20.0, 56.0, 80.0], dtype=np.float32)
                c_b3 = np.array([14.0, 42.0, 68.0], dtype=np.float32)
            t01 = np.clip(d_dith / 3.0, 0.0, 1.0)[:, None]
            t12 = np.clip((d_dith - 3.0) / 7.5, 0.0, 1.0)[:, None]
            t23 = np.clip((d_dith - 10.5) / 26.0, 0.0, 1.0)[:, None]
            w_col = np.where(
                d_dith[:, None] < 3.0,
                (1.0 - t01) * c_b0 + t01 * c_b1,
                np.where(
                    d_dith[:, None] < 10.5,
                    (1.0 - t12) * c_b1 + t12 * c_b2,
                    (1.0 - t23) * c_b2 + t23 * c_b3,
                ),
            )

            we_w = ge[wi]
            wn_w = gn[wi]

            # Gentle open-water isometric wavelets (strictly deeper water >= 2.2m, ramped smoothly over 2.2..4.0m)
            u_iso = we_w * 0.2079 + wn_w * 0.9781
            v_iso = -we_w * 0.9781 + wn_w * 0.2079
            w_fade = np.clip((depth_m - 2.2) / 1.8, 0.0, 1.0)
            row_id = np.floor(v_iso * 0.75).astype(np.int32)
            u_stag = (u_iso + (row_id & 1) * 3.1) * 0.22
            col_id = np.floor(u_stag).astype(np.int32)
            w_hash = ((col_id * 73856093) ^ (row_id * 19349663)) & 0xFF
            v_frac = (v_iso * 0.75) % 1.0
            dash_u = u_stag % 1.0
            in_dash = v_frac < 0.24
            crest = in_dash & (w_hash < 34) & (dash_u >= 0.14) & (dash_u <= 0.74) & (depth_m >= 2.2)
            trough = (v_frac >= 0.24) & (v_frac < 0.44) & (w_hash < 34) & (dash_u >= 0.18) & (dash_u <= 0.70) & (depth_m >= 2.2)
            crest_sky = (
                np.array([26.0, 40.0, 64.0], dtype=np.float32)
                if preset_key == "night"
                else (np.array([66.0, 118.0, 142.0], dtype=np.float32) if preset_key == "day" else np.array([56.0, 74.0, 96.0], dtype=np.float32))
            )
            if crest.any():
                c_mix = (0.18 * w_fade[crest])[:, None]
                w_col[crest] = (1.0 - c_mix) * w_col[crest] + c_mix * crest_sky
            if trough.any():
                w_col[trough] *= (1.0 - 0.05 * w_fade[trough])[:, None]

            # Clean bilinear shoreline contact rim (tracks smooth lake_sdf >= 0.50 curve with zero 0.5m staircase!)
            if lake_sdf is not None:
                ls_w = lake_sdf[wi]
                f1 = (ls_w >= 0.50) & (ls_w <= 0.72) & (np.sin(u_iso * 0.65 + v_iso * 0.45) > -0.25)
            elif dist_lake is not None:
                ds_w = dist_lake[wi]
                f1 = (ds_w > 0.0) & (ds_w <= 0.45) & (np.sin(u_iso * 0.65 + v_iso * 0.45) > -0.25)
            else:
                r05_w = r05[wi]
                c05_w = c05[wi]
                f1 = scene.foam_ring1_05m[r05_w, c05_w] & (np.sin(u_iso * 0.65 + v_iso * 0.45) > -0.25)
            if f1.any():
                foam_tint = (
                    np.array([84.0, 118.0, 128.0], dtype=np.float32)
                    if preset_key == "night"
                    else (np.array([212.0, 236.0, 232.0], dtype=np.float32) if preset_key == "day" else np.array([176.0, 198.0, 196.0], dtype=np.float32))
                )
                w_col[f1] = 0.62 * w_col[f1] + 0.38 * foam_tint

            # Smooth pier water contact shadow directly from world-space pier_sdf (zero dotted grid!)
            if pier_sdf is not None:
                ps_w = pier_sdf[wi]
                p_sh = (ps_w >= 0.12) & (ps_w < 0.48)
                if p_sh.any():
                    w_col[p_sh] *= 0.84

            gz[wi] = LAKE_SURFACE_Z
            gcol[wi] = np.clip(w_col, 0.0, 250.0)
            gmat[wi] = M_WATER_LAKE
            gnx[wi], gny[wi], gnz[wi] = 0.0, 0.0, 1.0

        bi_h = li[is_real_harbor_obj]
        if len(bi_h) > 0:
            # Flat per-pier deck height & clean global-LV95 planked timber / Swiss quay stone (zero 0.5m LiDAR noise!)
            if pier_h_val is not None:
                gz[bi_h] = LAKE_SURFACE_Z + pier_h_val[bi_h].astype(np.float32)
            else:
                gz[bi_h] = LAKE_SURFACE_Z + 0.90
            pe_h = ge[bi_h]
            pn_h = gn[bi_h]
            is_stone_pier = gsem[bi_h] == G_PLATFORM_PIER
            # Stone quay decks (Bendlikon Pavilion, etc.)
            stone_col = np.full((len(bi_h), 3), [172.0, 168.0, 160.0], dtype=np.float32)
            stone_joint = ((pe_h % 1.2) < 0.08) | ((pn_h % 1.2) < 0.08)
            stone_col[stone_joint] *= 0.90
            # Weathered timber jetties (Seebad Kilchberg & private wooden piers)
            wood_col = np.full((len(bi_h), 3), [174.0, 146.0, 112.0], dtype=np.float32)
            wood_alt = (np.floor(pe_h / 0.55).astype(np.int32) & 1) == 0
            wood_col[wood_alt] *= 0.95
            wood_seam = (pe_h % 0.55) < 0.08
            wood_col[wood_seam] *= 0.86
            gcol[bi_h] = np.where(is_stone_pier[:, None], stone_col, wood_col)
            gmat[bi_h] = M_HARBOR_OBJ
            gnx[bi_h], gny[bi_h], gnz[bi_h] = 0.0, 0.0, 1.0

    return gcol, gmat, gz, g_seebad_pool


def _fill_3d_poly(
    camera: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W: int,
    H: int,
    zbuf: np.ndarray,
    rgb_buf: np.ndarray,
    mat_buf: np.ndarray,
    obj_buf: np.ndarray,
    norm_buf: np.ndarray,
    shadow_buf: np.ndarray,
    pts_3d: list[tuple[float, float, float]],
    col_rgb: tuple[float, float, float] | list[float] | np.ndarray,
    obj_id: int,
    mat_id: int = M_BRIDGE,
    norm: tuple[float, float, float] = (0.0, 0.0, 1.0),
    is_shadow: bool = False,
    shadow_mat_only: int | None = None,
    shadow_mul: float = 0.76,
    z_bias: float = 0.0,
    plank_e_step: float = 0.0,
    plank_col: list[float] | np.ndarray | None = None,
    plank_seam_w: float = 0.09,
    rib_u_step: float = 0.0,
    rib_col: list[float] | np.ndarray | None = None,
    rib_w: float = 0.24,
    edge_frame_w: float = 0.0,
) -> tuple[int, int, int, int, float] | None:
    """Shared exact 2D/3D convex polygon rasterizer with planar z-buffer depth (zero gaps at any mpp!)."""
    nv = len(pts_3d)
    if nv < 3:
        return None
    pe_a = np.array([p[0] for p in pts_3d], dtype=np.float64)
    pn_a = np.array([p[1] for p in pts_3d], dtype=np.float64)
    pz_a = np.array([p[2] for p in pts_3d], dtype=np.float64)
    sx, sy, sd = camera.project(pe_a, pn_a, pz_a)
    sx = sx + shift_x
    sy = sy + shift_y
    sd = sd + z_bias

    x0 = max(0, int(math.floor(float(sx.min()))))
    x1 = min(W - 1, int(math.ceil(float(sx.max()))))
    y0 = max(0, int(math.floor(float(sy.min()))))
    y1 = min(H - 1, int(math.ceil(float(sy.max()))))
    if x0 > x1 or y0 > y1:
        return None

    area2 = 0.0
    for i_e in range(nv):
        j_e = (i_e + 1) % nv
        area2 += (sx[i_e] * sy[j_e] - sx[j_e] * sy[i_e])
    if abs(area2) < 0.02:
        return None
    sgn = 1.0 if area2 > 0.0 else -1.0

    xs_g = np.arange(x0, x1 + 1, dtype=np.float64)
    ys_g = np.arange(y0, y1 + 1, dtype=np.float64)
    gx, gy = np.meshgrid(xs_g, ys_g)
    inside = np.ones(gx.shape, dtype=np.bool_)
    for i_e in range(nv):
        j_e = (i_e + 1) % nv
        ex_e = sx[j_e] - sx[i_e]
        ey_e = sy[j_e] - sy[i_e]
        elen = math.hypot(ex_e, ey_e)
        if elen < 1e-6:
            continue
        cross = (ex_e * (gy - sy[i_e]) - ey_e * (gx - sx[i_e])) * sgn
        inside &= cross >= (-0.08 * elen)
    if not inside.any():
        return None

    ax0, ay0, ad0 = float(sx[0]), float(sy[0]), float(sd[0])
    ax1, ay1, ad1 = float(sx[1]), float(sy[1]), float(sd[1])
    i2 = 3 if nv == 4 else 2
    ax2, ay2, ad2 = float(sx[i2]), float(sy[i2]), float(sd[i2])
    det = (ax1 - ax0) * (ay2 - ay0) - (ax2 - ax0) * (ay1 - ay0)
    if abs(det) < 1e-5 and nv > 3:
        i2 = 2 if i2 == 3 else 3
        ax2, ay2, ad2 = float(sx[i2]), float(sy[i2]), float(sd[i2])
        det = (ax1 - ax0) * (ay2 - ay0) - (ax2 - ax0) * (ay1 - ay0)

    iy_m, ix_m = np.nonzero(inside)
    px_m = x0 + ix_m
    py_m = y0 + iy_m
    w1 = None
    w2 = None
    if abs(det) >= 1e-5:
        inv_det = 1.0 / det
        w1 = ((px_m - ax0) * (ay2 - ay0) - (py_m - ay0) * (ax2 - ax0)) * inv_det
        w2 = ((ax1 - ax0) * (py_m - ay0) - (ay1 - ay0) * (px_m - ax0)) * inv_det
        dd = (ad0 + w1 * (ad1 - ad0) + w2 * (ad2 - ad0)).astype(np.float32)
    else:
        dd = np.full(len(px_m), float(sd.mean()), dtype=np.float32)

    if is_shadow:
        if shadow_mat_only is not None:
            sh_ok = mat_buf[py_m, px_m] == shadow_mat_only
        else:
            sh_ok = (dd < (zbuf[py_m, px_m] + 0.45)) & (obj_buf[py_m, px_m] == 0)
        if sh_ok.any():
            rgb_buf[py_m[sh_ok], px_m[sh_ok]] *= shadow_mul
        return None

    win = dd < zbuf[py_m, px_m]
    if win.any():
        wx, wy, wd = px_m[win], py_m[win], dd[win]
        zbuf[wy, wx] = wd
        if plank_e_step > 0.0 and plank_col is not None and w1 is not None and w2 is not None:
            ew_m = pe_a[0] + w1[win] * (pe_a[1] - pe_a[0]) + w2[win] * (pe_a[i2] - pe_a[0])
            on_seam = (ew_m % plank_e_step) < plank_seam_w
            c_arr = np.where(on_seam[:, None], plank_col, col_rgb).astype(np.float32)
            rgb_buf[wy, wx] = c_arr
        elif (rib_u_step > 0.0 or edge_frame_w > 0.0) and rib_col is not None and w1 is not None and w2 is not None and nv == 4 and i2 == 3:
            # Quad p0->p1 = u-axis, p0->p3 = v-axis (note: for quad [p0, p1, p2, p3], i2=3 gives exact (u, v) in [0,1]^2!)
            u_len = math.sqrt((pe_a[1] - pe_a[0]) ** 2 + (pn_a[1] - pn_a[0]) ** 2 + (pz_a[1] - pz_a[0]) ** 2)
            v_len = math.sqrt((pe_a[3] - pe_a[0]) ** 2 + (pn_a[3] - pn_a[0]) ** 2 + (pz_a[3] - pz_a[0]) ** 2)
            u_m = w1[win] * u_len
            v_m = w2[win] * v_len
            on_rib = np.zeros(len(wx), dtype=np.bool_)
            if rib_u_step > 0.0:
                on_rib |= (u_m % rib_u_step) < rib_w
            if edge_frame_w > 0.0:
                on_rib |= (u_m < edge_frame_w) | (u_m > (u_len - edge_frame_w)) | (v_m < edge_frame_w) | (v_m > (v_len - edge_frame_w))
            rgb_buf[wy, wx] = np.where(on_rib[:, None], rib_col, col_rgb).astype(np.float32)
        else:
            rgb_buf[wy, wx] = col_rgb
        mat_buf[wy, wx] = mat_id
        obj_buf[wy, wx] = obj_id
        norm_buf[wy, wx] = norm
        shadow_buf[wy, wx] = False
    return (x0, y0, x1, y1, float(sd.max()))


def _fill_3d_box(
    camera: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W: int,
    H: int,
    zbuf: np.ndarray,
    rgb_buf: np.ndarray,
    mat_buf: np.ndarray,
    obj_buf: np.ndarray,
    norm_buf: np.ndarray,
    shadow_buf: np.ndarray,
    e0: float,
    e1: float,
    n0: float,
    n1: float,
    z_bot: float,
    z_top: float,
    col_rgb: tuple[float, float, float] | list[float] | np.ndarray,
    obj_id: int,
    mat_id: int = M_BRIDGE,
    top_rgb: tuple[float, float, float] | list[float] | np.ndarray | None = None,
) -> None:
    """Rasterize a solid 3D axis-aligned isometric box (top cap + all 4 vertical faces; z-buffer culls back faces)."""
    if z_top <= z_bot + 0.04:
        return
    c_top = top_rgb if top_rgb is not None else col_rgb
    # Top horizontal cap
    _fill_3d_poly(
        camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
        [(e0, n0, z_top), (e1, n0, z_top), (e1, n1, z_top), (e0, n1, z_top)],
        c_top, obj_id, mat_id=mat_id, norm=(0.0, 0.0, 1.0),
    )
    # 4 vertical faces (z-buffer cleanly selects the 2 camera-facing faces with exact outward normals)
    faces = (
        ([(e1, n0, z_bot), (e1, n1, z_bot), (e1, n1, z_top), (e1, n0, z_top)], (1.0, 0.0, 0.0)),
        ([(e0, n0, z_bot), (e1, n0, z_bot), (e1, n0, z_top), (e0, n0, z_top)], (0.0, -1.0, 0.0)),
        ([(e0, n1, z_bot), (e0, n0, z_bot), (e0, n0, z_top), (e0, n1, z_top)], (-1.0, 0.0, 0.0)),
        ([(e1, n1, z_bot), (e0, n1, z_bot), (e0, n1, z_top), (e1, n1, z_top)], (0.0, 1.0, 0.0)),
    )
    for f_pts, f_norm in faces:
        _fill_3d_poly(
            camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
            f_pts, col_rgb, obj_id, mat_id=mat_id, norm=f_norm,
        )


def _draw_3d_box_column(
    camera: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W: int,
    H: int,
    zbuf: np.ndarray,
    rgb_buf: np.ndarray,
    mat_buf: np.ndarray,
    obj_buf: np.ndarray,
    norm_buf: np.ndarray,
    shadow_buf: np.ndarray,
    e_c: float,
    n_c: float,
    z_bot: float,
    z_top: float,
    half_w: float,
    col_rgb: tuple[float, float, float],
    obj_id: int,
    mat_id: int = M_BRIDGE,
) -> None:
    """Rasterize a solid 3D rectangular pillar/column/box (zero 5-stick split at any half_w or mpp!)."""
    if z_top <= z_bot + 0.08:
        return
    hw = max(float(half_w), camera.mpp * 0.60)
    _fill_3d_box(
        camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
        e_c - hw, e_c + hw, n_c - hw, n_c + hw, z_bot, z_top, col_rgb, obj_id, mat_id=mat_id,
    )


def _render_elevated_bridges_and_rail_portals(
    scene: SceneData,
    camera: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W: int,
    H: int,
    r0: int,
    r1: int,
    c0: int,
    c1: int,
    sub_mask: np.ndarray,
    sub_dem: np.ndarray,
    sub_shadow: np.ndarray,
    zbuf: np.ndarray,
    rgb_buf: np.ndarray,
    mat_buf: np.ndarray,
    obj_buf: np.ndarray,
    norm_buf: np.ndarray,
    shadow_buf: np.ndarray,
    crop_box_lv95: tuple[float, float, float, float] | None,
    active_mask: np.ndarray | None = None,
    is_night: bool = False,
) -> None:
    """STAGE 2.5: Render true 3D elevated viaducts (Dorfstrasse horseshoe viaduct, Bahnhofstrasse bridge,
    A3 overpasses, spiral stairs, rail bridges), concrete support piers, SBB catenary portals & overhead
    wires, and Bahnhof Kilchberg platform canopies, signs & Swiss railway clock!"""
    sub_bcls = scene.bridge_cls[r0:r1, c0:c1]
    sub_bz = scene.bridge_z[r0:r1, c0:c1]
    sub_bsdist = scene.bridge_sdist[r0:r1, c0:c1].astype(np.float32)
    sub_balong = scene.bridge_along[r0:r1, c0:c1]
    sub_bhw = scene.bridge_hw[r0:r1, c0:c1].astype(np.float32)
    sub_bang = scene.bridge_ang[r0:r1, c0:c1].astype(np.float32)
    sub_bid = scene.bridge_id[r0:r1, c0:c1]
    amask = active_mask if active_mask is not None else scene.diorama_mask

    # 1. Concrete Viaduct Support Piers (under Dorfstrasse viaduct & A3 bridges)
    for pier in scene.viaduct_piers:
        pe, pn = pier["e"], pier["n"]
        if crop_box_lv95 is not None:
            if not (crop_box_lv95[0] + 1.0 <= pe <= crop_box_lv95[2] - 1.0 and crop_box_lv95[1] + 1.0 <= pn <= crop_box_lv95[3] - 1.0):
                continue
        rc_p = int(np.clip((N_MAX - pn) / GRID_RES, 0, GRID_H - 1))
        cc_p = int(np.clip((pe - E_MIN) / GRID_RES, 0, GRID_W - 1))
        if not amask[rc_p, cc_p]:
            continue
        off = pier["offset"]
        nx_p, ny_p = pier["nx"], pier["ny"]
        for sgn in (-1.0, 1.0):
            _draw_3d_box_column(
                camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                pe + sgn * off * nx_p, pn + sgn * off * ny_p,
                pier["z_bot"], pier["z_top"],
                half_w=0.52,
                col_rgb=(162.0, 160.0, 154.0),
                obj_id=300000 + pier["bid"],
            )

    # 2. 3D Elevated Bridge Decks, Concrete Box-Girder Fascia & Safety Parapets/Railings!
    bmask = sub_mask & (sub_bcls > 0)
    if bmask.any():
        br05, bc05 = np.nonzero(bmask)
        be05 = E_MIN + (bc05 + c0 + 0.5) * GRID_RES
        bn05 = N_MAX - (br05 + r0 + 0.5) * GRID_RES

        # Sub-sample to 0.125m (4x4) at <=0.16 m/px or 0.25m (2x2) at <=0.36 m/px for silky-smooth viaduct curves!
        if camera.mpp <= 0.16:
            offs_b = (-0.1875, -0.0625, 0.0625, 0.1875)
            br = np.tile(br05, 16)
            bc = np.tile(bc05, 16)
            be = np.concatenate([be05 + de for de in offs_b for _ in offs_b])
            bn = np.concatenate([bn05 + dn for _ in offs_b for dn in offs_b])
            bz = _sample_bilinear_05m(sub_bz, be, bn, r0=r0, c0=c0, max_jump=2.5)
            bsdist = _sample_bilinear_05m(sub_bsdist, be, bn, r0=r0, c0=c0, max_jump=3.0)
            balong = _sample_bilinear_05m(sub_balong, be, bn, r0=r0, c0=c0, max_jump=3.0)
            bhw = _sample_bilinear_05m(sub_bhw, be, bn, r0=r0, c0=c0, max_jump=2.0)
        elif camera.mpp <= 0.36:
            br = np.tile(br05, 4)
            bc = np.tile(bc05, 4)
            be = np.concatenate([be05 - 0.125, be05 + 0.125, be05 - 0.125, be05 + 0.125])
            bn = np.concatenate([bn05 + 0.125, bn05 + 0.125, bn05 - 0.125, bn05 - 0.125])
            bz = sub_bz[br, bc].copy()
            bsdist = sub_bsdist[br, bc]
            balong = sub_balong[br, bc]
            bhw = sub_bhw[br, bc]
        else:
            br, bc, be, bn = br05, bc05, be05, bn05
            bz = sub_bz[br, bc].copy()
            bsdist = sub_bsdist[br, bc]
            balong = sub_balong[br, bc]
            bhw = sub_bhw[br, bc]

        bcls = sub_bcls[br, bc]
        bang = sub_bang[br, bc]
        bid = sub_bid[br, bc].astype(np.int32)
        bsh = sub_shadow[br, bc]

        abs_sd = np.abs(bsdist)
        b_tex_s = 1.0 / max(0.08, float(camera.mpp))
        ix25 = np.floor((be - E_MIN) * b_tex_s).astype(np.int32)
        iy25 = np.floor((bn - N_MIN) * b_tex_s).astype(np.int32)
        ph = ((ix25 * 73856093) ^ (iy25 * 19349663)) & 0xFF

        bcol = np.full((len(be), 3), [90.0, 94.0, 102.0], dtype=np.float32)
        bnx = np.zeros(len(be), dtype=np.float32)
        bny = np.zeros(len(be), dtype=np.float32)
        bnz = np.ones(len(be), dtype=np.float32)

        # Road Viaducts & Motorway Bridges: clean asphalt + dashed centerline + raised concrete sidewalks + steel railings!
        is_rd_br = (bcls == BR_ROAD_VIADUCT) | (bcls == BR_MOTORWAY)
        if is_rd_br.any():
            ri = np.nonzero(is_rd_br)[0]
            sd_r = abs_sd[ri]
            al_r = balong[ri]
            hw_r = bhw[ri]
            sw_in = np.where(hw_r >= 5.0, hw_r - 1.55, hw_r - 1.05)
            rail_in = hw_r - 0.52

            col_r = np.where((ph[ri] < 64)[:, None], [92.0, 96.0, 104.0], [84.0, 88.0, 96.0]).astype(np.float32)
            # Crisp white dashed centerline (only on 2-lane main viaducts/motorways!) & solid white edge lines
            dash = (hw_r >= 4.4) & (sd_r < 0.25) & ((al_r % 5.6) < 2.6)
            edge_l = (hw_r >= 4.4) & (np.abs(sd_r - (sw_in - 0.35)) < 0.22)
            col_r[dash | edge_l] = [230.0, 232.0, 236.0]

            # Raised concrete sidewalks with expansion joints every 2.0m
            on_sw = (sd_r >= sw_in) & (sd_r < rail_in)
            sw_j = on_sw & ((al_r % 2.0) < 0.22)
            col_r[on_sw] = [174.0, 172.0, 166.0]
            col_r[sw_j] = [148.0, 146.0, 140.0]
            bz[ri[on_sw]] += 0.22

            # Outer concrete parapet curb + galvanized steel safety railing!
            on_rail = sd_r >= rail_in
            post = on_rail & ((al_r % 2.2) < 0.45)
            col_r[on_rail] = [194.0, 196.0, 198.0]
            col_r[post] = [132.0, 138.0, 146.0]
            bz[ri[on_rail]] += 1.02
            bcol[ri] = col_r

        # Footbridges & Spiral Viaduct Stairs (BR_FOOTBRIDGE, BR_STEPS)
        is_st = (bcls == BR_STEPS) | (bcls == BR_FOOTBRIDGE)
        if is_st.any():
            si = np.nonzero(is_st)[0]
            sd_s = abs_sd[si]
            al_s = balong[si]
            hw_s = bhw[si]
            col_s = np.full((len(si), 3), [182.0, 180.0, 174.0], dtype=np.float32)
            tread = (bcls[si] == BR_STEPS) & ((al_s % 0.72) < 0.32)
            col_s[tread] = [152.0, 150.0, 146.0]
            s_rail = sd_s >= (hw_s - 0.42)
            col_s[s_rail] = [118.0, 126.0, 136.0]
            bz[si[s_rail]] += 0.92
            bcol[si] = col_s

        # SBB Elevated Rail Bridges over street underpasses (BR_RAIL_BRIDGE)
        is_rb = bcls == BR_RAIL_BRIDGE
        if is_rb.any():
            rbi = np.nonzero(is_rb)[0]
            sd_rb = abs_sd[rbi]
            al_rb = balong[rbi]
            hw_rb = bhw[rbi]
            col_rb = np.where((ph[rbi] < 110)[:, None], [116.0, 108.0, 98.0], [96.0, 88.0, 80.0]).astype(np.float32)
            slp = (sd_rb <= 1.25) & ((al_rb % 0.85) < 0.30)
            col_rb[slp] = [64.0, 52.0, 44.0]
            steel_r = np.abs(sd_rb - 0.72) <= 0.22
            col_rb[steel_r] = [196.0, 202.0, 210.0]
            girder_r = sd_rb >= (hw_rb - 0.50)
            col_rb[girder_r] = [132.0, 138.0, 146.0]
            bz[rbi[girder_r]] += 0.85
            bcol[rbi] = col_rb

        # Project & write bridge deck surface
        px_b, py_b, pd_b = camera.project(be, bn, bz)
        bix = np.round(px_b + shift_x).astype(np.int32)
        biy = np.round(py_b + shift_y).astype(np.int32)
        bv = (bix >= 0) & (bix < W - 1) & (biy >= 0) & (biy < H - 1)
        if bv.any():
            bix, biy, pd_b = bix[bv], biy[bv], pd_b[bv]
            bcol_v, bid_v, bsh_v = bcol[bv], bid[bv], bsh[bv]
            ord_b = np.argsort(pd_b)[::-1]
            bix, biy, pd_b = bix[ord_b], biy[ord_b], pd_b[ord_b]
            bcol_v, bid_v, bsh_v = bcol_v[ord_b], bid_v[ord_b], bsh_v[ord_b]
            for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                tx = np.clip(bix + ox, 0, W - 1)
                ty = np.clip(biy + oy, 0, H - 1)
                db = pd_b + (0.04 if (ox or oy) else 0.0)
                win = db < zbuf[ty, tx]
                zbuf[ty[win], tx[win]] = db[win]
                rgb_buf[ty[win], tx[win]] = bcol_v[win]
                mat_buf[ty[win], tx[win]] = M_BRIDGE
                obj_buf[ty[win], tx[win]] = 300000 + bid_v[win]
                shadow_buf[ty[win], tx[win]] = bsh_v[win]
                norm_buf[ty[win], tx[win], 0] = 0.0
                norm_buf[ty[win], tx[win], 1] = 0.0
                norm_buf[ty[win], tx[win], 2] = 1.0

        # Vertical Concrete Box-Girder Side Fascia along outer bridge edges (resolution-aware tangent sub-sampling -> zero gaps!)
        er_b, ec_b = np.nonzero(bmask & (np.abs(sub_bsdist) >= (sub_bhw - 0.65)))
        if len(er_b) > 0:
            fe_b0 = E_MIN + (ec_b + c0 + 0.5) * GRID_RES
            fn_b0 = N_MAX - (er_b + r0 + 0.5) * GRID_RES
            fz_top0 = sub_bz[er_b, ec_b] + 0.92
            girder_d0 = np.where(sub_bcls[er_b, ec_b] == BR_STEPS, 0.95, 1.45)
            fz_bot0 = np.maximum(sub_dem[er_b, ec_b], sub_bz[er_b, ec_b] - girder_d0)
            f_bid0 = sub_bid[er_b, ec_b].astype(np.int32)
            sgn_sd0 = np.where(sub_bsdist[er_b, ec_b] >= 0.0, 1.0, -1.0)
            f_ang0 = sub_bang[er_b, ec_b]
            ftx0 = np.cos(f_ang0)
            fty0 = np.sin(f_ang0)
            fnx_b0 = (np.sin(f_ang0) * sgn_sd0).astype(np.float32)
            fny_b0 = (-np.cos(f_ang0) * sgn_sd0).astype(np.float32)
            f_is_rail_br0 = sub_bcls[er_b, ec_b] == BR_RAIL_BRIDGE

            n_sub_f = max(2, int(math.ceil(GRID_RES / max(0.06, camera.mpp * 0.70))))
            sub_offs = np.linspace(-0.25, 0.25, n_sub_f, dtype=np.float64)
            fe_b = (fe_b0[:, None] + ftx0[:, None] * sub_offs[None, :]).ravel()
            fn_b = (fn_b0[:, None] + fty0[:, None] * sub_offs[None, :]).ravel()
            fz_top = np.repeat(fz_top0, n_sub_f)
            girder_d = np.repeat(girder_d0, n_sub_f)
            fz_bot = np.repeat(fz_bot0, n_sub_f)
            f_bid = np.repeat(f_bid0, n_sub_f)
            fnx_b = np.repeat(fnx_b0, n_sub_f)
            fny_b = np.repeat(fny_b0, n_sub_f)
            f_is_rail_br = np.repeat(f_is_rail_br0, n_sub_f)

            dz_g = max(0.06, camera.mpp * 0.55)
            max_gh = float((fz_top - fz_bot).max())
            n_gs = max(2, int(math.ceil(max_gh / dz_g)) + 1)
            for gi in range(n_gs):
                zc = fz_top - gi * dz_g
                act = zc >= (fz_bot - 0.08)
                if not act.any():
                    continue
                zc_a = np.maximum(zc[act], fz_bot[act])
                px_g, py_g, pd_g = camera.project(fe_b[act], fn_b[act], zc_a)
                ix_g = np.round(px_g + shift_x).astype(np.int32)
                iy_g = np.round(py_g + shift_y).astype(np.int32)
                vg = (ix_g >= 0) & (ix_g < W - 1) & (iy_g >= 0) & (iy_g < H - 1)
                if not vg.any():
                    continue
                ix_g, iy_g, pd_g = ix_g[vg], iy_g[vg], pd_g[vg]
                ia = np.nonzero(act)[0][vg]
                h_down = fz_top[ia] - zc_a[vg]
                g_col = np.full((len(ia), 3), [172.0, 170.0, 164.0], dtype=np.float32)
                g_col[f_is_rail_br[ia]] = [118.0, 124.0, 134.0]
                g_col[h_down < 0.72] = [196.0, 198.0, 200.0]   # Bright concrete/steel parapet rail
                g_col[h_down > (girder_d[ia] + 0.55)] *= 0.80  # Lower girder shadow lip

                for ox in (0, 1):
                    tx = ix_g + ox
                    win = pd_g < zbuf[iy_g, tx]
                    if win.any():
                        wy, wx = iy_g[win], tx[win]
                        zbuf[wy, wx] = pd_g[win]
                        rgb_buf[wy, wx] = g_col[win]
                        mat_buf[wy, wx] = M_BRIDGE
                        obj_buf[wy, wx] = 300000 + f_bid[ia[win]]
                        norm_buf[wy, wx, 0] = fnx_b[ia[win]]
                        norm_buf[wy, wx, 1] = fny_b[ia[win]]
                        norm_buf[wy, wx, 2] = 0.18
                        shadow_buf[wy, wx] = False

    # 3. 3D SBB Steel Overhead Catenary Portals along the Seebahn Railway!
    for idx_p, cp in enumerate(scene.catenary_portals):
        ce, cn, cz = cp["e"], cp["n"], cp["z"]
        if crop_box_lv95 is not None:
            if not (crop_box_lv95[0] + 2 <= ce <= crop_box_lv95[2] - 2 and crop_box_lv95[1] + 2 <= cn <= crop_box_lv95[3] - 2):
                continue
        nx_c, ny_c, shw = cp["nx"], cp["ny"], cp["span_hw"]
        obj_p = 310000 + idx_p
        # Twin vertical steel H-beam masts
        for sgn in (-1.0, 1.0):
            me = ce + sgn * shw * nx_c
            mn = cn + sgn * shw * ny_c
            zs = np.arange(cz, cz + 6.4, max(0.06, camera.mpp * 0.55), dtype=np.float32)
            px, py, pd = camera.project(np.full_like(zs, me), np.full_like(zs, mn), zs)
            ix, iy = np.round(px + shift_x).astype(np.int32), np.round(py + shift_y).astype(np.int32)
            vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
            ix, iy, pd = ix[vm], iy[vm], pd[vm]
            w_m = pd < zbuf[iy, ix]
            if w_m.any():
                zbuf[iy[w_m], ix[w_m]] = pd[w_m]
                rgb_buf[iy[w_m], ix[w_m]] = [118.0, 126.0, 136.0]
                mat_buf[iy[w_m], ix[w_m]] = M_BRIDGE
                obj_buf[iy[w_m], ix[w_m]] = obj_p
                norm_buf[iy[w_m], ix[w_m]] = [0.4, -0.4, 0.8]
                shadow_buf[iy[w_m], ix[w_m]] = False
        # Overhead horizontal steel truss beam at cz + 6.1m
        ts = np.linspace(-shw, shw, int(round(shw * 2 / max(0.06, camera.mpp * 0.55))) + 1)
        be_t = ce + ts * nx_c
        bn_t = cn + ts * ny_c
        bz_t = np.full_like(ts, cz + 6.1)
        px, py, pd = camera.project(be_t, bn_t, bz_t)
        ix, iy = np.round(px + shift_x).astype(np.int32), np.round(py + shift_y).astype(np.int32)
        vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
        ix, iy, pd = ix[vm], iy[vm], pd[vm]
        w_m = pd < zbuf[iy, ix]
        if w_m.any():
            zbuf[iy[w_m], ix[w_m]] = pd[w_m]
            rgb_buf[iy[w_m], ix[w_m]] = [148.0, 156.0, 166.0]
            mat_buf[iy[w_m], ix[w_m]] = M_BRIDGE
            obj_buf[iy[w_m], ix[w_m]] = obj_p
            norm_buf[iy[w_m], ix[w_m]] = [0.0, 0.0, 1.0]
            shadow_buf[iy[w_m], ix[w_m]] = False

    # 3b. F13: Overhead 1px Steel SBB Catenary Contact & Messenger Wires + Droppers!
    # HARD GAP GUARD (12.0 <= span_m <= 65.0) prevents bridging the 684.1m station/viaduct gap!
    cps = scene.catenary_portals
    wire_step = max(0.05, camera.mpp * 0.55)
    c_wire_col = np.array([120.0, 128.0, 144.0] if is_night else [164.0, 172.0, 182.0], dtype=np.float32)
    m_wire_col = np.array([96.0, 104.0, 120.0] if is_night else [132.0, 140.0, 152.0], dtype=np.float32)
    for i_cp in range(len(cps) - 1):
        p0, p1 = cps[i_cp], cps[i_cp + 1]
        span_m = math.hypot(p1["e"] - p0["e"], p1["n"] - p0["n"])
        if not (12.0 <= span_m <= 65.0):
            continue
        sgn1 = 1.0 if (p0["nx"] * p1["nx"] + p0["ny"] * p1["ny"]) >= 0.0 else -1.0
        n1x, n1y = p1["nx"] * sgn1, p1["ny"] * sgn1
        n_pts = int(math.ceil(span_m / wire_step)) + 1
        t_w = np.linspace(0.0, 1.0, n_pts, dtype=np.float64)
        z_lin = (1.0 - t_w) * float(p0["z"]) + t_w * float(p1["z"])
        z_contact = z_lin + 5.35
        z_mess = z_lin + 6.12 - 0.55 * 4.0 * t_w * (1.0 - t_w)
        obj_w = 310100 + i_cp
        for lat in (-1.65, 1.65):
            e0_w = p0["e"] + lat * p0["nx"]
            n0_w = p0["n"] + lat * p0["ny"]
            e1_w = p1["e"] + lat * n1x
            n1_w = p1["n"] + lat * n1y
            es_w = e0_w + (e1_w - e0_w) * t_w
            ns_w = n0_w + (n1_w - n0_w) * t_w
            cc_w = np.floor((es_w - E_MIN) / GRID_RES).astype(np.int32)
            rr_w = np.floor((N_MAX - ns_w) / GRID_RES).astype(np.int32)
            ok_w = (cc_w >= 0) & (cc_w < GRID_W) & (rr_w >= 0) & (rr_w < GRID_H)
            if crop_box_lv95 is not None:
                ok_w &= (
                    (es_w >= crop_box_lv95[0] + 6.0)
                    & (es_w <= crop_box_lv95[2] - 6.0)
                    & (ns_w >= crop_box_lv95[1] + 6.0)
                    & (ns_w <= crop_box_lv95[3] - 6.0)
                )
            if not ok_w.any():
                continue
            in_am = np.zeros(n_pts, dtype=np.bool_)
            in_am[ok_w] = amask[rr_w[ok_w], cc_w[ok_w]]
            if not in_am.any():
                continue
            es_v, ns_v = es_w[in_am], ns_w[in_am]
            for zs_v, col_v in ((z_contact[in_am], c_wire_col), (z_mess[in_am], m_wire_col)):
                px, py, pd = camera.project(es_v, ns_v, zs_v)
                ix = np.round(px + shift_x).astype(np.int32)
                iy = np.round(py + shift_y).astype(np.int32)
                vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
                if not vm.any():
                    continue
                ix, iy, pd = ix[vm], iy[vm], pd[vm]
                win = pd < zbuf[iy, ix]
                if win.any():
                    zbuf[iy[win], ix[win]] = pd[win]
                    rgb_buf[iy[win], ix[win]] = col_v
                    mat_buf[iy[win], ix[win]] = M_BRIDGE
                    obj_buf[iy[win], ix[win]] = obj_w
                    norm_buf[iy[win], ix[win]] = [0.0, 0.0, 1.0]
                    shadow_buf[iy[win], ix[win]] = False
            # 4 vertical 1px dropper ticks connecting contact and messenger wire
            for td in (0.2, 0.4, 0.6, 0.8):
                ed = e0_w + (e1_w - e0_w) * td
                nd = n0_w + (n1_w - n0_w) * td
                if crop_box_lv95 is not None and not (
                    crop_box_lv95[0] + 6.0 <= ed <= crop_box_lv95[2] - 6.0
                    and crop_box_lv95[1] + 6.0 <= nd <= crop_box_lv95[3] - 6.0
                ):
                    continue
                rc_d = int(np.clip((N_MAX - nd) / GRID_RES, 0, GRID_H - 1))
                cc_d = int(np.clip((ed - E_MIN) / GRID_RES, 0, GRID_W - 1))
                if not amask[rc_d, cc_d]:
                    continue
                z_base_d = (1.0 - td) * float(p0["z"]) + td * float(p1["z"])
                z_hi_d = z_base_d + 6.12 - 0.55 * 4.0 * td * (1.0 - td)
                z_lo_d = z_base_d + 5.35
                zd_s = np.linspace(z_lo_d, z_hi_d, 4)
                px, py, pd = camera.project(np.full_like(zd_s, ed), np.full_like(zd_s, nd), zd_s)
                ix = np.round(px + shift_x).astype(np.int32)
                iy = np.round(py + shift_y).astype(np.int32)
                vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
                if vm.any():
                    ix, iy, pd = ix[vm], iy[vm], pd[vm]
                    win = pd < zbuf[iy, ix]
                    if win.any():
                        zbuf[iy[win], ix[win]] = pd[win]
                        rgb_buf[iy[win], ix[win]] = m_wire_col
                        mat_buf[iy[win], ix[win]] = M_BRIDGE
                        obj_buf[iy[win], ix[win]] = obj_w
                        norm_buf[iy[win], ix[win]] = [0.0, 0.0, 1.0]
                        shadow_buf[iy[win], ix[win]] = False

    # 4. F13: Bahnhof Kilchberg Platform Architecture (West canopy H-columns, un-occluded East glass shelters, backlit SBB signs & Swiss clock!)
    bhf_in_crop = True
    if crop_box_lv95 is not None:
        if crop_box_lv95[2] < 2683820.0 or crop_box_lv95[0] > 2683880.0 or crop_box_lv95[3] < 1242050.0 or crop_box_lv95[1] > 1242160.0:
            bhf_in_crop = False
    if bhf_in_crop:
        def _pt_ok_bhf(ep: float, np_: float, ins: float = 2.0) -> bool:
            if crop_box_lv95 is not None:
                if not (crop_box_lv95[0] + ins <= ep <= crop_box_lv95[2] - ins and crop_box_lv95[1] + ins <= np_ <= crop_box_lv95[3] - ins):
                    return False
            rr_b = int(np.clip((N_MAX - np_) / GRID_RES, 0, GRID_H - 1))
            cc_b = int(np.clip((ep - E_MIN) / GRID_RES, 0, GRID_W - 1))
            return bool(amask[rr_b, cc_b])

        def _draw_bhf_seg(e0, n0, z0, e1, n1, z1, col, mat_c=M_BRIDGE, oid=312004, thick=False):
            step_b = max(0.05, camera.mpp * 0.55)
            dist = math.sqrt((e1 - e0) ** 2 + (n1 - n0) ** 2 + (z1 - z0) ** 2)
            ns = max(2, int(math.ceil(dist / step_b)) + 1)
            t = np.linspace(0.0, 1.0, ns, dtype=np.float64)
            es = e0 + (e1 - e0) * t
            ns_a = n0 + (n1 - n0) * t
            zs = z0 + (z1 - z0) * t
            cc_s = np.floor((es - E_MIN) / GRID_RES).astype(np.int32)
            rr_s = np.floor((N_MAX - ns_a) / GRID_RES).astype(np.int32)
            ok_s = (cc_s >= 0) & (cc_s < GRID_W) & (rr_s >= 0) & (rr_s < GRID_H)
            if crop_box_lv95 is not None:
                ok_s &= (es >= crop_box_lv95[0] + 2.0) & (es <= crop_box_lv95[2] - 2.0) & (ns_a >= crop_box_lv95[1] + 2.0) & (ns_a <= crop_box_lv95[3] - 2.0)
            if not ok_s.any():
                return
            in_a = np.zeros(ns, dtype=np.bool_)
            in_a[ok_s] = amask[rr_s[ok_s], cc_s[ok_s]]
            if not in_a.any():
                return
            px, py, pd = camera.project(es[in_a], ns_a[in_a], zs[in_a])
            ix = np.round(px + shift_x).astype(np.int32)
            iy = np.round(py + shift_y).astype(np.int32)
            vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
            if not vm.any():
                return
            ix, iy, pd = ix[vm], iy[vm], pd[vm]
            for ox, oy in (((0, 0), (1, 0)) if thick else ((0, 0),)):
                tx = np.clip(ix + ox, 0, W - 1)
                ty = np.clip(iy + oy, 0, H - 1)
                win = pd < zbuf[ty, tx]
                if win.any():
                    wy, wx = ty[win], tx[win]
                    zbuf[wy, wx] = pd[win]
                    rgb_buf[wy, wx] = col
                    mat_buf[wy, wx] = mat_c
                    obj_buf[wy, wx] = oid
                    norm_buf[wy, wx] = [0.25, -0.25, 0.93]
                    shadow_buf[wy, wx] = False

        # 4a. West Platform Canopy (idx=17): 9 pairs of crisp galvanized steel H-columns descending from 428.5m to DEM!
        we0, wn0 = 2683853.6, 1242065.1
        we1, wn1 = 2683834.9, 1242144.2
        w_dx, w_dy = we1 - we0, wn1 - wn0
        w_len = math.hypot(w_dx, w_dy)
        wnx, wny = -w_dy / w_len, w_dx / w_len
        for frac in np.linspace(0.04, 0.96, 9):
            ce_p = we0 + w_dx * float(frac)
            cn_p = wn0 + w_dy * float(frac)
            for s_off in (-1.35, 1.35):
                pe_c = ce_p + s_off * wnx
                pn_c = cn_p + s_off * wny
                if not _pt_ok_bhf(pe_c, pn_c):
                    continue
                rr_p = int(np.clip((N_MAX - pn_c) / GRID_RES, 0, GRID_H - 1))
                cc_p = int(np.clip((pe_c - E_MIN) / GRID_RES, 0, GRID_W - 1))
                z_pl = float(scene.dem[rr_p, cc_p]) + 0.55
                _draw_3d_box_column(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    pe_c, pn_c, z_pl, 428.55, 0.16, (128.0, 136.0, 146.0), 312000, M_BRIDGE,
                )

        # 4b. East Platform 3D Steel-and-Glass Shelter Canopy on open unobstructed North East platform
        #     (north of station building idx=670, clear of footbridge & trees, verified G_PLATFORM_PIER & ~bldg_roof_mask!)
        ee0, en0, ee1, en1 = 2683851.2, 1242129.0, 2683846.2, 1242150.5
        hw_s = 1.40
        edx, edy = ee1 - ee0, en1 - en0
        elen = math.hypot(edx, edy)
        eux, euy = edx / elen, edy / elen
        enx, eny = -euy, eux
        for frac in np.linspace(0.08, 0.92, 5):
            pe_c = ee0 + edx * float(frac)
            pn_c = en0 + edy * float(frac)
            if not _pt_ok_bhf(pe_c, pn_c):
                continue
            rr_p = int(np.clip((N_MAX - pn_c) / GRID_RES, 0, GRID_H - 1))
            cc_p = int(np.clip((pe_c - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if scene.bldg_roof_mask[rr_p, cc_p]:
                continue
            z_pl = float(scene.dem[rr_p, cc_p]) + 0.55
            _draw_3d_box_column(
                camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                pe_c, pn_c, z_pl, 427.85, 0.16, (118.0, 126.0, 136.0), 312001, M_BRIDGE,
            )
        # Canopy roof deck (solid 3D polygon: translucent cyan-blue glass panels + galvanized steel ribs, zero gaps!)
        if _pt_ok_bhf(0.5 * (ee0 + ee1), 0.5 * (en0 + en1), ins=1.0):
            canopy_pts = [
                (ee0 - hw_s * enx, en0 - hw_s * eny, 427.88),
                (ee1 - hw_s * enx, en1 - hw_s * eny, 427.88),
                (ee1 + hw_s * enx, en1 + hw_s * eny, 427.88),
                (ee0 + hw_s * enx, en0 + hw_s * eny, 427.88),
            ]
            glass_c = [74.0, 128.0, 168.0] if is_night else [108.0, 184.0, 212.0]
            _fill_3d_poly(
                camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                canopy_pts, glass_c, 312001, mat_id=M_BRIDGE, norm=(0.0, 0.0, 1.0),
                rib_u_step=4.1, rib_col=[172.0, 178.0, 186.0], rib_w=0.28, edge_frame_w=0.22,
            )

        # 4c. 3 Backlit Blue-and-White SBB Platform Signs (KILCHBERG) as solid 3D vertical quads (zero dots!)
        sign_mat = M_WINDOW_LIT if is_night else M_BRIDGE
        sign_spots = (
            (2683850.25, 1242140.1, 427.62),  # North East glass shelter camera-facing east fascia
            (2683853.45, 1242082.5, 428.50),  # West canopy south east-facing fascia
            (2683842.85, 1242127.0, 428.50),  # West canopy north east-facing fascia
        )
        for se_s, sn_s, sz_s in sign_spots:
            if not _pt_ok_bhf(se_s, sn_s):
                continue
            for dz_lo, dz_hi, sc_s in (
                (-0.33, -0.11, [22.0, 64.0, 148.0]),
                (-0.11,  0.11, [244.0, 246.0, 248.0]),
                ( 0.11,  0.33, [22.0, 64.0, 148.0]),
            ):
                s_pts = [
                    (se_s - 1.40 * eux, sn_s - 1.40 * euy, sz_s + dz_lo),
                    (se_s + 1.40 * eux, sn_s + 1.40 * euy, sz_s + dz_lo),
                    (se_s + 1.40 * eux, sn_s + 1.40 * euy, sz_s + dz_hi),
                    (se_s - 1.40 * eux, sn_s - 1.40 * euy, sz_s + dz_hi),
                ]
                _fill_3d_poly(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    s_pts, sc_s, 312002, mat_id=sign_mat, norm=(0.3, -0.3, 0.9), z_bias=-0.35,
                )

        # 4d. Iconic White Round Swiss SBB Railway Station Clocks (1944 Hans Hilfiker, oid in 310192..310193 EXCLUDED from occ_m!)
        #     1) Open South East platform apron + 2) Suspended directly beneath West bahnhof_canopy (id=17)
        for ck_e, ck_n, ck_z, ck_oid, is_susp in (
            (2683861.2, 1242085.2, 427.65, 310192, False),
            (2683850.0, 1242102.0, 427.60, 310193, True),
        ):
            if not _pt_ok_bhf(ck_e, ck_n, ins=2.0):
                continue
            rr_ck = int(np.clip((N_MAX - ck_n) / GRID_RES, 0, GRID_H - 1))
            cc_ck = int(np.clip((ck_e - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if is_susp:
                _draw_3d_box_column(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    ck_e, ck_n, ck_z + 0.35, 428.50, 0.07, (84.0, 90.0, 98.0), ck_oid, M_BRIDGE,
                )
            else:
                z_pl_ck = float(scene.dem[rr_ck, cc_ck]) + 0.55
                _draw_3d_box_column(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    ck_e, ck_n, z_pl_ck, ck_z - 0.55, 0.09, (94.0, 100.0, 108.0), ck_oid, M_BRIDGE,
                )
            px_ck, py_ck, pd_ck = camera.project(np.array([ck_e + 0.18]), np.array([ck_n]), np.array([ck_z]))
            cx_k = int(round(float(px_ck[0] + shift_x)))
            cy_k = int(round(float(py_ck[0] + shift_y)))
            d_k = float(pd_ck[0]) - 0.40
            r_k = max(3, int(round((0.58 if is_susp else 0.68) / camera.mpp)))
            for dy_k in range(-r_k, r_k + 1):
                for dx_k in range(-r_k, r_k + 1):
                    tx_k, ty_k = cx_k + dx_k, cy_k + dy_k
                    if not (0 <= tx_k < W and 0 <= ty_k < H):
                        continue
                    rr2 = dx_k * dx_k + dy_k * dy_k
                    if rr2 > r_k * r_k + 0.5 or d_k >= zbuf[ty_k, tx_k]:
                        continue
                    zbuf[ty_k, tx_k] = d_k
                    if rr2 >= (r_k - 0.75) ** 2:
                        rgb_buf[ty_k, tx_k] = [36.0, 40.0, 46.0]
                        mat_buf[ty_k, tx_k] = M_BRIDGE
                    elif (dx_k == 1 and dy_k == 0) or (r_k >= 3 and dx_k == 2 and dy_k == 0):
                        rgb_buf[ty_k, tx_k] = [224.0, 34.0, 34.0]  # Iconic Swiss red second-hand paddle!
                        mat_buf[ty_k, tx_k] = M_WINDOW_LIT if is_night else M_BRIDGE
                    elif (dx_k == 0 and dy_k <= 0 and dy_k >= -(r_k - 1)) or (dy_k == 0 and dx_k == -1):
                        rgb_buf[ty_k, tx_k] = [24.0, 26.0, 32.0]  # Black clock hands
                        mat_buf[ty_k, tx_k] = M_BRIDGE
                    else:
                        rgb_buf[ty_k, tx_k] = [248.0, 248.0, 244.0]
                        mat_buf[ty_k, tx_k] = M_WINDOW_LIT if is_night else M_BRIDGE
                    obj_buf[ty_k, tx_k] = ck_oid
                    norm_buf[ty_k, tx_k] = [0.25, -0.25, 0.93]
                    shadow_buf[ty_k, tx_k] = False

        # 4d-ii. M3.5 Modern SBB steel-and-glass platform wind shelter along bahnhof_canopy (solid 3D quad, oid=310194 EXCLUDED from occ_m!)
        if _pt_ok_bhf(2683844.5, 1242104.0, ins=2.0):
            ws_pts = [
                (2683844.5, 1242096.0, 422.1),
                (2683844.5, 1242112.0, 422.1),
                (2683844.5, 1242112.0, 425.2),
                (2683844.5, 1242096.0, 425.2),
            ]
            _fill_3d_poly(
                camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                ws_pts, [148.0, 188.0, 210.0], 310194, mat_id=M_BRIDGE, norm=(0.7, 0.0, 0.7), z_bias=-0.15,
                rib_u_step=2.65, rib_col=[86.0, 92.0, 100.0], rib_w=0.22, edge_frame_w=0.26,
            )

        # 4e. v9.0 Bahnhof Kilchberg Fine Platform Furniture, Ticket Machine, Perronanzeiger, Velounterstand & SBB Signals
        wux, wuy = w_dx / w_len, w_dy / w_len
        for b_axis, fracs in (
            ((we0, wn0, w_dx, w_dy, wux, wuy, wnx, wny), (0.30, 0.72)),
            ((ee0, en0, edx, edy, eux, euy, enx, eny), (0.28, 0.72)),
        ):
            a0, b0, adx, ady, aux, auy, anx, any_ = b_axis
            for frac_b in fracs:
                be_p = a0 + adx * frac_b
                bn_p = b0 + ady * frac_b
                if not _pt_ok_bhf(be_p, bn_p, ins=2.0):
                    continue
                rr_b = int(np.clip((N_MAX - bn_p) / GRID_RES, 0, GRID_H - 1))
                cc_b = int(np.clip((be_p - E_MIN) / GRID_RES, 0, GRID_W - 1))
                if scene.bldg_roof_mask[rr_b, cc_b]:
                    continue
                zp_b = float(scene.dem[rr_b, cc_b]) + 0.55
                e0_b, n0_b = be_p - 0.95 * aux, bn_p - 0.95 * auy
                e1_b, n1_b = be_p + 0.95 * aux, bn_p + 0.95 * auy
                _draw_bhf_seg(e0_b, n0_b, zp_b, e0_b, n0_b, zp_b + 0.48, [46.0, 50.0, 58.0], oid=312004)
                _draw_bhf_seg(e1_b, n1_b, zp_b, e1_b, n1_b, zp_b + 0.48, [46.0, 50.0, 58.0], oid=312004)
                _draw_bhf_seg(e0_b, n0_b, zp_b + 0.48, e1_b, n1_b, zp_b + 0.48, [166.0, 118.0, 72.0], oid=312004, thick=True)
                _draw_bhf_seg(e0_b - 0.25 * anx, n0_b - 0.25 * any_, zp_b + 0.88, e1_b - 0.25 * anx, n1_b - 0.25 * any_, zp_b + 0.88, [148.0, 102.0, 62.0], oid=312004)

        # Red SBB Ticket Vending Machine on open station east apron
        tm_e, tm_n = 2683862.5, 1242093.0
        if _pt_ok_bhf(tm_e, tm_n, ins=2.0):
            rr_tm = int(np.clip((N_MAX - tm_n) / GRID_RES, 0, GRID_H - 1))
            cc_tm = int(np.clip((tm_e - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if not scene.bldg_roof_mask[rr_tm, cc_tm]:
                z_tm = float(scene.dem[rr_tm, cc_tm]) + 0.55
                _draw_3d_box_column(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    tm_e, tm_n, z_tm, z_tm + 1.85, 0.35, (214.0, 38.0, 38.0), 312005, M_BRIDGE,
                )
                _draw_bhf_seg(
                    tm_e + 0.36, tm_n - 0.16, z_tm + 1.25, tm_e + 0.36, tm_n + 0.16, z_tm + 1.25,
                    [128.0, 192.0, 236.0] if is_night else [36.0, 52.0, 74.0],
                    mat_c=M_WINDOW_LIT if is_night else M_BRIDGE, oid=312005, thick=True,
                )

        # 2 Suspended Blue-White SBB Departure Indicators (Perronanzeiger)
        for pa_e, pa_n, pa_z, pa_top in (
            (2683847.2, 1242094.0, 427.30, 428.50),
            (2683849.2, 1242138.0, 426.90, 427.85),
        ):
            if not _pt_ok_bhf(pa_e, pa_n, ins=2.0):
                continue
            _draw_bhf_seg(pa_e - 0.55 * enx, pa_n - 0.55 * eny, pa_z + 0.25, pa_e - 0.55 * enx, pa_n - 0.55 * eny, pa_top, [124.0, 130.0, 138.0], oid=312006)
            _draw_bhf_seg(pa_e + 0.55 * enx, pa_n + 0.55 * eny, pa_z + 0.25, pa_e + 0.55 * enx, pa_n + 0.55 * eny, pa_top, [124.0, 130.0, 138.0], oid=312006)
            _draw_bhf_seg(pa_e - 0.75 * enx, pa_n - 0.75 * eny, pa_z + 0.18, pa_e + 0.75 * enx, pa_n + 0.75 * eny, pa_z + 0.18, [24.0, 52.0, 118.0], oid=312006, thick=True)
            _draw_bhf_seg(
                pa_e - 0.65 * enx, pa_n - 0.65 * eny, pa_z, pa_e + 0.65 * enx, pa_n + 0.65 * eny, pa_z,
                [255.0, 224.0, 140.0] if is_night else [242.0, 244.0, 246.0],
                mat_c=M_WINDOW_LIT if is_night else M_BRIDGE, oid=312006,
            )

        # Covered Bicycle Rack (Velounterstand) on Bahnhofplatz SE of station
        ve0, vn0, ve1, vn1 = 2683873.5, 1242086.0, 2683876.5, 1242075.5
        if _pt_ok_bhf(0.5 * (ve0 + ve1), 0.5 * (vn0 + vn1), ins=2.0):
            rr_v = int(np.clip((N_MAX - 0.5 * (vn0 + vn1)) / GRID_RES, 0, GRID_H - 1))
            cc_v = int(np.clip((0.5 * (ve0 + ve1) - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if (not scene.bldg_roof_mask[rr_v, cc_v]) and scene.sem[rr_v, cc_v] != G_STREET_MAIN:
                zv_g = float(scene.dem[rr_v, cc_v])
                vdx, vdy = ve1 - ve0, vn1 - vn0
                vlen = max(1.0, math.hypot(vdx, vdy))
                vnx, vny = -vdy / vlen, vdx / vlen
                for vf in (0.08, 0.36, 0.64, 0.92):
                    pe_v, pn_v = ve0 + vdx * vf, vn0 + vdy * vf
                    if _pt_ok_bhf(pe_v, pn_v, ins=2.0):
                        _draw_3d_box_column(
                            camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                            pe_v, pn_v, zv_g, zv_g + 2.35, 0.10, (142.0, 148.0, 156.0), 312007, M_BRIDGE,
                        )
                velo_pts = [
                    (ve0 - 0.95 * vnx, vn0 - 0.95 * vny, zv_g + 2.38),
                    (ve1 - 0.95 * vnx, vn1 - 0.95 * vny, zv_g + 2.38),
                    (ve1 + 0.75 * vnx, vn1 + 0.75 * vny, zv_g + 2.38),
                    (ve0 + 0.75 * vnx, vn0 + 0.75 * vny, zv_g + 2.38),
                ]
                _fill_3d_poly(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    velo_pts, [120.0, 152.0, 174.0], 312007, mat_id=M_BRIDGE, norm=(0.0, 0.0, 1.0),
                    rib_col=[164.0, 170.0, 178.0], edge_frame_w=0.16,
                )
                bike_cols = ([186.0, 56.0, 52.0], [52.0, 116.0, 176.0], [62.0, 68.0, 76.0], [186.0, 56.0, 52.0], [52.0, 116.0, 176.0])
                for bi_k, bf in enumerate((0.16, 0.32, 0.50, 0.68, 0.84)):
                    be_k, bn_k = ve0 + vdx * bf, vn0 + vdy * bf
                    _draw_bhf_seg(be_k - 0.45 * vnx, bn_k - 0.45 * vny, zv_g + 0.55, be_k + 0.45 * vnx, bn_k + 0.45 * vny, zv_g + 0.55, bike_cols[bi_k], oid=312007)

        # 3D SBB Trackside Signal Masts (oid=310190, 310191 — strictly inside 310000..310199 so EXCLUDED from occ_m!)
        for sig_i, (sge, sgn, s_col) in enumerate((
            (2683851.2, 1242071.4, [56.0, 226.0, 98.0]),   # South platform green aspect
            (2683838.5, 1242148.5, [234.0, 48.0, 48.0]),   # North platform red aspect
        )):
            if not _pt_ok_bhf(sge, sgn, ins=2.0):
                continue
            rr_sg = int(np.clip((N_MAX - sgn) / GRID_RES, 0, GRID_H - 1))
            cc_sg = int(np.clip((sge - E_MIN) / GRID_RES, 0, GRID_W - 1))
            z_sg = float(scene.dem[rr_sg, cc_sg]) + 0.45
            oid_sg = 310190 + sig_i
            _draw_bhf_seg(sge, sgn, z_sg, sge, sgn, z_sg + 5.4, [118.0, 124.0, 132.0], oid=oid_sg)
            _draw_bhf_seg(sge, sgn, z_sg + 4.4, sge, sgn, z_sg + 5.4, [28.0, 32.0, 38.0], oid=oid_sg, thick=True)
            _draw_bhf_seg(
                sge + 0.16, sgn, z_sg + 4.85, sge + 0.16, sgn, z_sg + 5.15,
                s_col, mat_c=M_WINDOW_LIT if is_night else M_BRIDGE, oid=oid_sg, thick=True,
            )


# Verified Reformierte Kirche Cemetery perimeter polygon (12 vertices, MVT)
CEMETERY_POLY_LV95 = [
    (2683453.1, 1241313.7), (2683460.1, 1241280.7), (2683464.5, 1241281.2),
    (2683499.9, 1241103.3), (2683414.1, 1241087.6), (2683419.8, 1241058.1),
    (2683394.7, 1241053.3), (2683375.2, 1241114.1), (2683395.3, 1241183.9),
    (2683374.9, 1241251.2), (2683434.2, 1241248.0), (2683422.4, 1241308.5),
    (2683453.1, 1241313.7),
]


def _render_3d_sports_details(
    scene: SceneData,
    camera: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W: int,
    H: int,
    zbuf: np.ndarray,
    rgb_buf: np.ndarray,
    mat_buf: np.ndarray,
    obj_buf: np.ndarray,
    norm_buf: np.ndarray,
    shadow_buf: np.ndarray,
    is_night: bool,
    crop_box_lv95: tuple[float, float, float, float] | None,
    active_mask: np.ndarray | None = None,
    preset_key: str = "day",
) -> None:
    """STAGE 2.6: Strictly clipped 3D pixel-art sports architecture, enclosures, hoisted parked cars,
    3D sidewalk/viaduct/platform/promenade streetlamps, cemetery stone wall & Swiss micro-props!"""
    mpp = camera.mpp
    step_l = max(0.06, mpp * 0.65)
    step_z = max(0.06, mpp * 0.60)
    amask = active_mask if active_mask is not None else scene.diorama_mask

    def _in_active_world(es_arr: np.ndarray, ns_arr: np.ndarray) -> np.ndarray:
        cc_a = np.floor((es_arr - E_MIN) / GRID_RES).astype(np.int32)
        rr_a = np.floor((N_MAX - ns_arr) / GRID_RES).astype(np.int32)
        ok = (cc_a >= 0) & (cc_a < GRID_W) & (rr_a >= 0) & (rr_a < GRID_H)
        if crop_box_lv95 is not None:
            e0_c, n0_c, e1_c, n1_c = crop_box_lv95
            ok &= (es_arr >= e0_c + 0.5) & (es_arr <= e1_c - 0.5) & (ns_arr >= n0_c + 0.5) & (ns_arr <= n1_c - 0.5)
        res = np.zeros(len(es_arr), dtype=np.bool_)
        if ok.any():
            res[ok] = amask[rr_a[ok], cc_a[ok]]
        return res

    def _draw_3d_seg(e0, n0, z0, e1, n1, z1, col, mat_c=M_BRIDGE, oid=230000, thick=False, dither_mesh=False):
        dist = math.sqrt((e1 - e0) ** 2 + (n1 - n0) ** 2 + (z1 - z0) ** 2)
        ns = max(2, int(math.ceil(dist / step_l)) + 1)
        t = np.linspace(0.0, 1.0, ns, dtype=np.float64)
        es = e0 + (e1 - e0) * t
        ns_a = n0 + (n1 - n0) * t
        zs = z0 + (z1 - z0) * t
        in_w = _in_active_world(es, ns_a)
        if not in_w.any():
            return
        es, ns_a, zs = es[in_w], ns_a[in_w], zs[in_w]
        px, py, pd = camera.project(es, ns_a, zs)
        ix = np.round(px + shift_x).astype(np.int32)
        iy = np.round(py + shift_y).astype(np.int32)
        v = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
        if not v.any():
            return
        ix, iy, pd = ix[v], iy[v], pd[v]
        if dither_mesh:
            keep = ((ix + iy) & 1) == 0
            ix, iy, pd = ix[keep], iy[keep], pd[keep]
            if len(ix) == 0:
                return
        offs = ((0, 0), (1, 0)) if thick else ((0, 0),)
        for ox, oy in offs:
            tx = np.clip(ix + ox, 0, W - 1)
            ty = np.clip(iy + oy, 0, H - 1)
            win = pd < zbuf[ty, tx]
            if win.any():
                wy, wx = ty[win], tx[win]
                zbuf[wy, wx] = pd[win]
                rgb_buf[wy, wx] = col
                mat_buf[wy, wx] = mat_c
                obj_buf[wy, wx] = oid
                norm_buf[wy, wx] = [0.25, -0.25, 0.93]
                shadow_buf[wy, wx] = False

    def _draw_3d_panel(e0, n0, e1, n1, z_bot, z_top, col_body, col_top=None, oid=230100, mesh_only=False):
        hlen = math.hypot(e1 - e0, n1 - n0)
        if hlen < 0.2:
            return
        nh = max(2, int(math.ceil(hlen / step_l)) + 1)
        nv = max(2, int(math.ceil((z_top - z_bot) / step_z)) + 1)
        th = np.linspace(0.0, 1.0, nh, dtype=np.float64)
        tv = np.linspace(0.0, 1.0, nv, dtype=np.float64)
        th_g, tv_g = np.meshgrid(th, tv)
        es = (e0 + (e1 - e0) * th_g).ravel()
        ns_a = (n0 + (n1 - n0) * th_g).ravel()
        zs = (z_bot + (z_top - z_bot) * tv_g).ravel()
        is_top_row = (tv_g >= (1.0 - 1.5 / max(2, nv))).ravel()
        in_w = _in_active_world(es, ns_a)
        if not in_w.any():
            return
        es, ns_a, zs, is_top_row = es[in_w], ns_a[in_w], zs[in_w], is_top_row[in_w]
        px, py, pd = camera.project(es, ns_a, zs)
        ix = np.round(px + shift_x).astype(np.int32)
        iy = np.round(py + shift_y).astype(np.int32)
        v = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
        if not v.any():
            return
        ix, iy, pd, is_top_row = ix[v], iy[v], pd[v], is_top_row[v]
        if mesh_only:
            keep = is_top_row | (((ix + iy) & 1) == 0)
            ix, iy, pd, is_top_row = ix[keep], iy[keep], pd[keep], is_top_row[keep]
            if len(ix) == 0:
                return
        win = pd < zbuf[iy, ix]
        if win.any():
            wy, wx = iy[win], ix[win]
            zbuf[wy, wx] = pd[win]
            if col_top is not None:
                c_arr = np.where(is_top_row[win, None], col_top, col_body).astype(np.float32)
            else:
                c_arr = col_body
            rgb_buf[wy, wx] = c_arr
            mat_buf[wy, wx] = M_BRIDGE
            obj_buf[wy, wx] = oid
            norm_buf[wy, wx] = [0.22, -0.22, 0.94]
            shadow_buf[wy, wx] = False

    def _sample_dem(e_p, n_p):
        cc = int(np.clip((e_p - E_MIN) / GRID_RES, 0, GRID_W - 1))
        rr = int(np.clip((N_MAX - n_p) / GRID_RES, 0, GRID_H - 1))
        return float(scene.dem[rr, cc])

    def _prop_ok(e_p: float, n_p: float, inset: float = 1.5, allow_sidewalk: bool = False) -> bool:
        if crop_box_lv95 is not None:
            if not (crop_box_lv95[0] + inset <= e_p <= crop_box_lv95[2] - inset and crop_box_lv95[1] + inset <= n_p <= crop_box_lv95[3] - inset):
                return False
        cc = int(math.floor((e_p - E_MIN) / GRID_RES))
        rr = int(math.floor((N_MAX - n_p) / GRID_RES))
        if not (0 <= rr < GRID_H and 0 <= cc < GRID_W):
            return False
        if not amask[rr, cc] or not scene.diorama_mask[rr, cc] or scene.lake_mask[rr, cc]:
            return False
        if scene.bldg_roof_mask[rr, cc] or scene.hedge_mask[rr, cc]:
            return False
        if not allow_sidewalk and scene.sem[rr, cc] in (G_STREET_MAIN, G_STREET_MINOR, G_MOTORWAY, G_RAILWAY):
            return False
        return True

    for sf_i, sf in enumerate(scene.sports_fields):
        fe_c, fn_c = float(sf["e"]), float(sf["n"])
        L_f, W_f = float(sf["length"]), float(sf["width"])
        ang = float(sf["angle"])
        kind = sf["kind"]
        if crop_box_lv95 is not None:
            rad_c = 0.5 * math.hypot(L_f, W_f) + 12.0
            if fe_c + rad_c < crop_box_lv95[0] or fe_c - rad_c > crop_box_lv95[2] or fn_c + rad_c < crop_box_lv95[1] or fn_c - rad_c > crop_box_lv95[3]:
                continue
        px_c, py_c, _ = camera.project(np.array([fe_c]), np.array([fn_c]), np.array([float(sf["z"])]))
        r_scr = (0.65 * math.hypot(L_f, W_f)) / mpp + 40.0
        if px_c[0] + shift_x + r_scr < 0 or px_c[0] + shift_x - r_scr > W or py_c[0] + shift_y + r_scr < 0 or py_c[0] + shift_y - r_scr > H:
            continue

        ca, sa = math.cos(ang), math.sin(ang)

        def to_world(u_loc, v_loc):
            e_w = fe_c + u_loc * ca - v_loc * sa
            n_w = fn_c + u_loc * sa + v_loc * ca
            return e_w, n_w, _sample_dem(e_w, n_w)

        if kind in ("tennis", "tennis_pad"):
            e_l, n_l, z_l = to_world(0.0, -6.15)
            e_r, n_r, z_r = to_world(0.0, 6.15)
            z_net = 0.5 * (z_l + z_r)
            _draw_3d_panel(
                e_l, n_l, e_r, n_r, z_net + 0.12, z_net + 1.12,
                col_body=np.array([48.0, 52.0, 58.0], dtype=np.float32),
                col_top=np.array([244.0, 244.0, 240.0], dtype=np.float32),
                oid=231000 + sf_i, mesh_only=True,
            )
            _draw_3d_seg(e_l, n_l, z_l, e_l, n_l, z_l + 1.25, [32.0, 68.0, 42.0], oid=231000 + sf_i, thick=True)
            _draw_3d_seg(e_r, n_r, z_r, e_r, n_r, z_r + 1.25, [32.0, 68.0, 42.0], oid=231000 + sf_i, thick=True)
            eu, nu, zu = to_world(0.0, 6.95)
            _draw_3d_seg(eu, nu, zu, eu, nu, zu + 2.05, [224.0, 224.0, 220.0], oid=231000 + sf_i, thick=True)

            hl_ap = max(14.2, 0.5 * L_f + 1.1)
            hw_ap = max(7.0, 0.5 * W_f + 0.8)
            for sgn_u in (-1.0, 1.0):
                ef0, nf0, zf0 = to_world(sgn_u * hl_ap, -hw_ap)
                ef1, nf1, zf1 = to_world(sgn_u * hl_ap, hw_ap)
                zf_m = 0.5 * (zf0 + zf1)
                _draw_3d_panel(
                    ef0, nf0, ef1, nf1, zf_m, zf_m + 1.75,
                    col_body=np.array([34.0, 74.0, 44.0], dtype=np.float32),
                    col_top=np.array([48.0, 96.0, 56.0], dtype=np.float32),
                    oid=231200 + sf_i, mesh_only=False,
                )
                _draw_3d_panel(
                    ef0, nf0, ef1, nf1, zf_m + 1.75, zf_m + 2.75,
                    col_body=np.array([78.0, 88.0, 84.0], dtype=np.float32),
                    col_top=np.array([116.0, 124.0, 122.0], dtype=np.float32),
                    oid=231200 + sf_i, mesh_only=True,
                )
                for vp in np.linspace(-hw_ap, hw_ap, 4):
                    ep, np_, zp = to_world(sgn_u * hl_ap, float(vp))
                    _draw_3d_seg(ep, np_, zp, ep, np_, zp + 2.8, [64.0, 74.0, 72.0], oid=231200 + sf_i)

        elif kind == "football":
            hl = max(28.0, 0.5 * L_f - 2.2)
            hw = max(18.0, 0.5 * W_f - 2.0)
            goal_hw = 3.66
            goal_h = 2.65
            goal_d = 2.20

            for sgn_u in (-1.0, 1.0):
                u_front = sgn_u * hl
                u_back = sgn_u * (hl + goal_d)
                e_fl, n_fl, z_fl = to_world(u_front, -goal_hw)
                e_fr, n_fr, z_fr = to_world(u_front, goal_hw)
                e_bl, n_bl, z_bl = to_world(u_back, -goal_hw)
                e_br, n_br, z_br = to_world(u_back, goal_hw)
                zg = 0.5 * (z_fl + z_fr)
                white_p = [246.0, 246.0, 242.0]
                net_c = np.array([216.0, 224.0, 220.0], dtype=np.float32)

                _draw_3d_panel(e_bl, n_bl, e_br, n_br, zg, zg + goal_h * 0.88, net_c, white_p, oid=232000 + sf_i, mesh_only=True)
                _draw_3d_panel(e_fl, n_fl, e_bl, n_bl, zg, zg + goal_h * 0.88, net_c, white_p, oid=232000 + sf_i, mesh_only=True)
                _draw_3d_panel(e_fr, n_fr, e_br, n_br, zg, zg + goal_h * 0.88, net_c, white_p, oid=232000 + sf_i, mesh_only=True)
                _draw_3d_seg(e_fl, n_fl, zg, e_fl, n_fl, zg + goal_h, white_p, oid=232000 + sf_i, thick=True)
                _draw_3d_seg(e_fr, n_fr, zg, e_fr, n_fr, zg + goal_h, white_p, oid=232000 + sf_i, thick=True)
                _draw_3d_seg(e_fl, n_fl, zg + goal_h, e_fr, n_fr, zg + goal_h, white_p, oid=232000 + sf_i, thick=True)
                _draw_3d_seg(e_fl, n_fl, zg + goal_h, e_bl, n_bl, zg + goal_h * 0.85, white_p, oid=232000 + sf_i)
                _draw_3d_seg(e_fr, n_fr, zg + goal_h, e_br, n_br, zg + goal_h * 0.85, white_p, oid=232000 + sf_i)
                # v9.0 Top roof net cords so football goals read sharply from high isometric angle
                for f_rn in (0.35, 0.70):
                    erl = e_fl + (e_bl - e_fl) * f_rn
                    nrl = n_fl + (n_bl - n_fl) * f_rn
                    err = e_fr + (e_br - e_fr) * f_rn
                    nrr = n_fr + (n_br - n_fr) * f_rn
                    zrn = zg + goal_h * (1.0 - 0.15 * f_rn)
                    _draw_3d_seg(erl, nrl, zrn, err, nrr, zrn, net_c, oid=232000 + sf_i, dither_mesh=True)

            for sgn_u in (-1.0, 1.0):
                for sgn_v in (-1.0, 1.0):
                    ec, nc, zc = to_world(sgn_u * hl, sgn_v * hw)
                    _draw_3d_seg(ec, nc, zc, ec, nc, zc + 1.65, [234.0, 234.0, 230.0], oid=232100 + sf_i)
                    _draw_3d_seg(ec, nc, zc + 1.35, ec + 0.55, nc, zc + 1.55, [218.0, 42.0, 42.0], oid=232100 + sf_i, thick=True)

            for u_dug in (-10.0, 10.0):
                ed0, nd0, zd0 = to_world(u_dug - 2.6, hw + 2.2)
                ed1, nd1, zd1 = to_world(u_dug + 2.6, hw + 2.2)
                zd_m = 0.5 * (zd0 + zd1)
                _draw_3d_panel(
                    ed0, nd0, ed1, nd1, zd_m, zd_m + 2.1,
                    col_body=np.array([58.0, 82.0, 96.0], dtype=np.float32),
                    col_top=np.array([214.0, 218.0, 222.0], dtype=np.float32),
                    oid=232200 + sf_i,
                )

            if L_f >= 82.0 or (fe_c < 2683300.0 and fn_c < 1241550.0 and L_f >= 70.0):
                lamp_mat = M_WINDOW_LIT if is_night else M_BRIDGE
                lamp_col = [255.0, 240.0, 182.0] if is_night else [228.0, 232.0, 236.0]
                for sgn_u in (-0.62, 0.62):
                    for sgn_v in (-1.0, 1.0):
                        em, nm, zm = to_world(sgn_u * hl, sgn_v * (hw + 3.2))
                        _draw_3d_seg(em, nm, zm, em, nm, zm + 14.5, [138.0, 144.0, 152.0], oid=232300 + sf_i, thick=True)
                        el0, nl0, _ = to_world(sgn_u * hl - 1.2, sgn_v * (hw + 3.2))
                        el1, nl1, _ = to_world(sgn_u * hl + 1.2, sgn_v * (hw + 3.2))
                        _draw_3d_seg(el0, nl0, zm + 14.5, el1, nl1, zm + 14.5, lamp_col, mat_c=lamp_mat, oid=232300 + sf_i, thick=True)
                        _draw_3d_seg(el0, nl0, zm + 13.8, el1, nl1, zm + 13.8, lamp_col, mat_c=lamp_mat, oid=232300 + sf_i)

        elif kind == "multisport":
            hl = max(10.0, 0.5 * L_f - 1.4)
            for sgn_u in (-1.0, 1.0):
                eb, nb, zb = to_world(sgn_u * (hl + 0.4), 0.0)
                _draw_3d_seg(eb, nb, zb, eb, nb, zb + 3.4, [96.0, 102.0, 110.0], oid=233000 + sf_i)
                e0_b, n0_b, _ = to_world(sgn_u * hl, -0.95)
                e1_b, n1_b, _ = to_world(sgn_u * hl, 0.95)
                _draw_3d_panel(e0_b, n0_b, e1_b, n1_b, zb + 2.8, zb + 3.85, np.array([238.0, 240.0, 242.0], dtype=np.float32), oid=233000 + sf_i)

    # 4b. F14c: 3D sports_enclosures Perimeter Windscreen (Tennis Club Kilchberg, strictly clipped!)
    for ei, ring in enumerate(scene.sports_enclosures):
        if len(ring) < 2:
            continue
        for j in range(len(ring) - 1):
            e0_e, n0_e = float(ring[j][0]), float(ring[j][1])
            e1_e, n1_e = float(ring[j + 1][0]), float(ring[j + 1][1])
            seg_l = math.hypot(e1_e - e0_e, n1_e - n0_e)
            if seg_l < 0.5:
                continue
            n_sub = max(1, int(math.ceil(seg_l / 10.0)))
            for ks in range(n_sub):
                f0 = ks / n_sub
                f1 = (ks + 1) / n_sub
                se0 = e0_e + (e1_e - e0_e) * f0
                sn0 = n0_e + (n1_e - n0_e) * f0
                se1 = e0_e + (e1_e - e0_e) * f1
                sn1 = n0_e + (n1_e - n0_e) * f1
                zb_m = 0.5 * (_sample_dem(se0, sn0) + _sample_dem(se1, sn1))
                _draw_3d_panel(
                    se0, sn0, se1, sn1, zb_m, zb_m + 1.75,
                    col_body=np.array([30.0, 68.0, 42.0], dtype=np.float32),
                    col_top=np.array([48.0, 96.0, 56.0], dtype=np.float32),
                    oid=231500 + ei, mesh_only=False,
                )
                _draw_3d_panel(
                    se0, sn0, se1, sn1, zb_m + 1.75, zb_m + 2.80,
                    col_body=np.array([76.0, 86.0, 82.0], dtype=np.float32),
                    col_top=np.array([114.0, 122.0, 120.0], dtype=np.float32),
                    oid=231500 + ei, mesh_only=True,
                )
                z_p0 = _sample_dem(se0, sn0)
                _draw_3d_seg(se0, sn0, z_p0, se0, sn0, z_p0 + 2.85, [62.0, 72.0, 70.0], oid=231500 + ei)

    # 5. Charming Swiss Pasture Details: Grazing Braunvieh & Holstein Cows (strictly clipped!)
    if not is_night:
        cow_herds = [
            (2683312.0, 1242048.0, 0.3, 0), (2683319.0, 1242058.0, 1.1, 1), (2683328.0, 1242044.0, -0.5, 0),
            (2683304.0, 1242068.0, 2.2, 1), (2683336.0, 1242063.0, 0.8, 0), (2683344.0, 1242052.0, -1.2, 1),
            (2683295.0, 1242038.0, 0.2, 0), (2683322.0, 1242078.0, 1.8, 1),
            (2683228.0, 1241690.0, 0.6, 0), (2683236.0, 1241702.0, -0.8, 1), (2683246.0, 1241684.0, 1.4, 0),
            (2683219.0, 1241712.0, 2.1, 1), (2683254.0, 1241706.0, 0.4, 0),
        ]
        for ci, (ce, cn, cang, cbreed) in enumerate(cow_herds):
            if not _prop_ok(ce, cn, inset=1.5):
                continue
            cz = _sample_dem(ce, cn)
            ca_c, sa_c = math.cos(cang), math.sin(cang)
            body_c = [138.0, 96.0, 66.0] if cbreed == 0 else [234.0, 234.0, 228.0]
            spot_c = [212.0, 198.0, 178.0] if cbreed == 0 else [42.0, 42.0, 46.0]
            _draw_3d_seg(ce - 0.8 * ca_c, cn - 0.8 * sa_c, cz + 0.72, ce + 0.8 * ca_c, cn + 0.8 * sa_c, cz + 0.76, body_c, oid=234000 + ci, thick=True)
            _draw_3d_seg(ce - 0.2 * ca_c, cn - 0.2 * sa_c, cz + 0.82, ce + 0.35 * ca_c, cn + 0.35 * sa_c, cz + 0.84, spot_c, oid=234000 + ci)
            _draw_3d_seg(ce + 0.85 * ca_c, cn + 0.85 * sa_c, cz + 0.55, ce + 1.15 * ca_c, cn + 1.15 * sa_c, cz + 0.48, spot_c, oid=234000 + ci)

    # 6. v12 Iter2: Solid Filled 3D Isometric Polygon Parked Cars (ZERO point-splat gaps, crisp dark-ink outline!)
    if scene.parked_cars:
        pk_ang = math.radians(28.5)
        ck, sk = math.cos(pk_ang), math.sin(pk_ang)
        fe_dir, fn_dir = -sk, ck
        se_dir, sn_dir = ck, sk

        def _fill_3d_poly_car(
            pts_3d: list[tuple[float, float, float]],
            col_rgb: list[float] | np.ndarray,
            oid: int,
            norm: tuple[float, float, float] = (0.0, 0.0, 1.0),
            is_shadow: bool = False,
            z_bias: float = 0.0,
        ) -> tuple[int, int, int, int, float] | None:
            """Exact 2D/3D convex polygon scanline/bbox rasterizer with planar z-buffer depth (zero gaps!)."""
            nv = len(pts_3d)
            pe_a = np.array([p[0] for p in pts_3d], dtype=np.float64)
            pn_a = np.array([p[1] for p in pts_3d], dtype=np.float64)
            pz_a = np.array([p[2] for p in pts_3d], dtype=np.float64)
            sx, sy, sd = camera.project(pe_a, pn_a, pz_a)
            sx = sx + shift_x
            sy = sy + shift_y
            sd = sd + z_bias

            x0 = max(0, int(math.floor(float(sx.min()))))
            x1 = min(W - 1, int(math.ceil(float(sx.max()))))
            y0 = max(0, int(math.floor(float(sy.min()))))
            y1 = min(H - 1, int(math.ceil(float(sy.max()))))
            if x0 > x1 or y0 > y1:
                return None

            # Signed 2D area to determine winding & skip degenerate edge-on faces
            area2 = 0.0
            for i_e in range(nv):
                j_e = (i_e + 1) % nv
                area2 += (sx[i_e] * sy[j_e] - sx[j_e] * sy[i_e])
            if abs(area2) < 0.08:
                return None
            sgn = 1.0 if area2 > 0.0 else -1.0

            xs_g = np.arange(x0, x1 + 1, dtype=np.float64)
            ys_g = np.arange(y0, y1 + 1, dtype=np.float64)
            gx, gy = np.meshgrid(xs_g, ys_g)  # (ny, nx)
            inside = np.ones(gx.shape, dtype=np.bool_)
            for i_e in range(nv):
                j_e = (i_e + 1) % nv
                ex_e = sx[j_e] - sx[i_e]
                ey_e = sy[j_e] - sy[i_e]
                elen = math.hypot(ex_e, ey_e)
                if elen < 1e-6:
                    continue
                cross = (ex_e * (gy - sy[i_e]) - ey_e * (gx - sx[i_e])) * sgn
                inside &= cross >= (-0.06 * elen)
            if not inside.any():
                return None

            # Exact planar depth interpolation on the projected polygon
            ax0, ay0, ad0 = float(sx[0]), float(sy[0]), float(sd[0])
            ax1, ay1, ad1 = float(sx[1]), float(sy[1]), float(sd[1])
            ax2, ay2, ad2 = float(sx[2]), float(sy[2]), float(sd[2])
            det = (ax1 - ax0) * (ay2 - ay0) - (ax2 - ax0) * (ay1 - ay0)
            if abs(det) < 1e-5 and nv > 3:
                ax2, ay2, ad2 = float(sx[3]), float(sy[3]), float(sd[3])
                det = (ax1 - ax0) * (ay2 - ay0) - (ax2 - ax0) * (ay1 - ay0)

            iy_m, ix_m = np.nonzero(inside)
            px_m = x0 + ix_m
            py_m = y0 + iy_m
            if abs(det) >= 1e-5:
                inv_det = 1.0 / det
                w1 = ((px_m - ax0) * (ay2 - ay0) - (py_m - ay0) * (ax2 - ax0)) * inv_det
                w2 = ((ax1 - ax0) * (py_m - ay0) - (ay1 - ay0) * (px_m - ax0)) * inv_det
                dd = (ad0 + w1 * (ad1 - ad0) + w2 * (ad2 - ad0)).astype(np.float32)
            else:
                dd = np.full(len(px_m), float(sd.mean()), dtype=np.float32)

            if is_shadow:
                # Soft ground contact shadow: darken asphalt/bay lines without overwriting zbuf/obj_buf
                sh_ok = (dd < (zbuf[py_m, px_m] + 0.45)) & (obj_buf[py_m, px_m] == 0)
                if sh_ok.any():
                    rgb_buf[py_m[sh_ok], px_m[sh_ok]] *= 0.62
                return None

            win = dd < zbuf[py_m, px_m]
            if win.any():
                wx, wy, wd = px_m[win], py_m[win], dd[win]
                zbuf[wy, wx] = wd
                rgb_buf[wy, wx] = col_rgb
                mat_buf[wy, wx] = M_BRIDGE
                obj_buf[wy, wx] = oid
                norm_buf[wy, wx] = norm
                shadow_buf[wy, wx] = False
            return (x0, y0, x1, y1, float(sd.max()))

        # Varied Swiss car palette: (roof/hood top_c, sunlit side_c, shaded end/side_c)
        car_pal = [
            ([232.0, 234.0, 238.0], [186.0, 192.0, 200.0], [148.0, 154.0, 166.0]),  # Alpine White
            ([188.0, 194.0, 204.0], [144.0, 152.0, 164.0], [110.0, 118.0, 132.0]),  # Metallic Silver
            ([88.0, 96.0, 108.0],   [62.0, 68.0, 78.0],    [44.0, 50.0, 60.0]),     # Graphite Slate
            ([54.0, 78.0, 124.0],   [38.0, 56.0, 94.0],    [26.0, 40.0, 72.0]),     # Deep Navy
            ([196.0, 52.0, 54.0],   [152.0, 36.0, 40.0],   [114.0, 26.0, 30.0]),    # Swiss Crimson
            ([192.0, 178.0, 154.0], [150.0, 138.0, 118.0], [116.0, 106.0, 90.0]),   # Warm Champagne
            ([54.0, 104.0, 82.0],   [38.0, 76.0, 60.0],    [26.0, 56.0, 44.0]),     # Forest Green
            ([90.0, 130.0, 166.0],  [64.0, 96.0, 128.0],   [46.0, 72.0, 98.0]),     # Steel Blue
            ([214.0, 168.0, 58.0],  [172.0, 130.0, 40.0],  [134.0, 98.0, 30.0]),    # Mustard Amber
        ]
        outline_col = [18.0, 22.0, 32.0] if (is_night or preset_key == "sunset") else [26.0, 32.0, 40.0]

        for car_seq, (pe_k, pn_k, pz_k, col_idx, facing) in enumerate(scene.parked_cars):
            # Strict 5-point clip against crop_box_lv95 (1.0m inset) & active_mask
            corners_ok = True
            for d_l, d_w in ((0.0, 0.0), (-2.05, -0.90), (-2.05, 0.90), (2.05, -0.90), (2.05, 0.90)):
                ce_t = pe_k + d_l * fe_dir + d_w * se_dir
                cn_t = pn_k + d_l * fn_dir + d_w * sn_dir
                if crop_box_lv95 is not None and not (
                    crop_box_lv95[0] + 1.0 <= ce_t <= crop_box_lv95[2] - 1.0
                    and crop_box_lv95[1] + 1.0 <= cn_t <= crop_box_lv95[3] - 1.0
                ):
                    corners_ok = False
                    break
                rc_t = int(np.clip(round((N_MAX - cn_t) * 2.0), 0, GRID_H - 1))
                cc_t = int(np.clip(round((ce_t - E_MIN) * 2.0), 0, GRID_W - 1))
                if not amask[rc_t, cc_t]:
                    corners_ok = False
                    break
            if not corners_ok:
                continue
            px_k, py_k, _ = camera.project(np.array([pe_k]), np.array([pn_k]), np.array([pz_k]))
            if px_k[0] + shift_x < -28 or px_k[0] + shift_x > W + 28 or py_k[0] + shift_y < -28 or py_k[0] + shift_y > H + 28:
                continue

            # Local car basis: +u = front (facing), +v = right side
            fu_e, fu_n = facing * fe_dir, facing * fn_dir
            rv_e, rv_n = facing * se_dir, facing * sn_dir

            def _cpt(u_l: float, v_l: float, z_l: float) -> tuple[float, float, float]:
                return (pe_k + u_l * fu_e + v_l * rv_e, pn_k + u_l * fu_n + v_l * rv_n, pz_k + z_l)

            top_c, side_c, shade_c = car_pal[col_idx % len(car_pal)]
            roof_hi = [min(246.0, c * 1.06) for c in top_c]
            glass_front = [36.0, 54.0, 74.0]
            glass_side = [32.0, 48.0, 66.0]
            glass_hi = [78.0, 110.0, 140.0]
            wheel_c = [24.0, 28.0, 34.0]
            head_c = [254.0, 242.0, 186.0] if is_night else [246.0, 242.0, 214.0]
            tail_c = [224.0, 44.0, 48.0] if is_night else [196.0, 40.0, 44.0]
            oid_c = 235000 + car_seq

            # 1. Soft dark-cool ground contact shadow beneath car
            _fill_3d_poly_car(
                [
                    (pe_k - 2.10 * fu_e - 0.96 * rv_e + 0.20, pn_k - 2.10 * fu_n - 0.96 * rv_n + 0.12, pz_k + 0.03),
                    (pe_k + 2.10 * fu_e - 0.96 * rv_e + 0.20, pn_k + 2.10 * fu_n - 0.96 * rv_n + 0.12, pz_k + 0.03),
                    (pe_k + 2.10 * fu_e + 0.96 * rv_e + 0.20, pn_k + 2.10 * fu_n + 0.96 * rv_n + 0.12, pz_k + 0.03),
                    (pe_k - 2.10 * fu_e + 0.96 * rv_e + 0.20, pn_k - 2.10 * fu_n + 0.96 * rv_n + 0.12, pz_k + 0.03),
                ],
                [0.0, 0.0, 0.0], oid_c, is_shadow=True,
            )

            hl, hw = 1.92, 0.80
            z0_b, z1_b = 0.16, 0.78
            # Track car screen bbox for crisp 1px dark-ink silhouette outline
            bx0, by0, bx1, by1 = W, H, -1, -1
            car_d_max = -1e9

            def _add_face(pts, col, nrm, zb=0.0):
                nonlocal bx0, by0, bx1, by1, car_d_max
                res = _fill_3d_poly_car(pts, col, oid_c, norm=nrm, z_bias=zb)
                if res is not None:
                    rx0, ry0, rx1, ry1, rd_m = res
                    if rx0 < bx0: bx0 = rx0
                    if ry0 < by0: by0 = ry0
                    if rx1 > bx1: bx1 = rx1
                    if ry1 > by1: by1 = ry1
                    if rd_m > car_d_max: car_d_max = rd_m

            # 2. Lower body 3D box (4 vertical faces + hood/trunk top deck)
            # Left & right body sides
            _add_face([_cpt(-hl, -hw, z0_b), _cpt(hl, -hw, z0_b), _cpt(hl, -hw, z1_b), _cpt(-hl, -hw, z1_b)], side_c, (-rv_e, -rv_n, 0.15))
            _add_face([_cpt(-hl, hw, z0_b), _cpt(hl, hw, z0_b), _cpt(hl, hw, z1_b), _cpt(-hl, hw, z1_b)], shade_c, (rv_e, rv_n, 0.15))
            # Front & rear body ends
            _add_face([_cpt(hl, -hw, z0_b), _cpt(hl, hw, z0_b), _cpt(hl, hw, z1_b), _cpt(hl, -hw, z1_b)], side_c, (fu_e, fu_n, 0.15))
            _add_face([_cpt(-hl, -hw, z0_b), _cpt(-hl, hw, z0_b), _cpt(-hl, hw, z1_b), _cpt(-hl, -hw, z1_b)], shade_c, (-fu_e, -fu_n, 0.15))
            # Hood & trunk top deck
            _add_face([_cpt(-hl, -hw, z1_b), _cpt(hl, -hw, z1_b), _cpt(hl, hw, z1_b), _cpt(-hl, hw, z1_b)], top_c, (0.0, 0.0, 1.0))

            # 3. Dark wheels/wheel-arches on both sides
            for w_sign in (-1.0, 1.0):
                vy_w = w_sign * (hw + 0.03)
                for wu in (-1.16, 1.16):
                    _add_face(
                        [_cpt(wu - 0.34, vy_w, 0.05), _cpt(wu + 0.34, vy_w, 0.05), _cpt(wu + 0.30, vy_w, 0.42), _cpt(wu - 0.30, vy_w, 0.42)],
                        wheel_c, (w_sign * rv_e, w_sign * rv_n, 0.0), zb=-0.04,
                    )

            # 4. Crisp headlights (front) & taillights (rear)
            for l_sign in (-1.0, 1.0):
                v_in, v_out = l_sign * 0.40, l_sign * 0.72
                _add_face(
                    [_cpt(hl + 0.03, v_in, 0.46), _cpt(hl + 0.03, v_out, 0.46), _cpt(hl + 0.03, v_out, 0.68), _cpt(hl + 0.03, v_in, 0.68)],
                    head_c, (fu_e, fu_n, 0.1), zb=-0.05,
                )
                _add_face(
                    [_cpt(-hl - 0.03, v_in, 0.46), _cpt(-hl - 0.03, v_out, 0.46), _cpt(-hl - 0.03, v_out, 0.68), _cpt(-hl - 0.03, v_in, 0.68)],
                    tail_c, (-fu_e, -fu_n, 0.1), zb=-0.05,
                )

            # 5. Upper cabin / greenhouse (tapered windshield, rear glass, side windows, bright roof)
            u_cb0, u_cb1 = -1.18, 0.88
            u_ct0, u_ct1 = -0.90, 0.50
            hw_cb, hw_ct = 0.70, 0.62
            z_ct = 1.34
            # Front sloped windshield + sky-reflection highlight strip
            _add_face([_cpt(u_cb1, -hw_cb, z1_b), _cpt(u_cb1, hw_cb, z1_b), _cpt(u_ct1, hw_ct, z_ct), _cpt(u_ct1, -hw_ct, z_ct)], glass_front, (fu_e * 0.6, fu_n * 0.6, 0.8))
            _add_face([_cpt(u_cb1 + 0.01, -hw_cb * 0.78, z1_b + 0.08), _cpt(u_cb1 + 0.01, -hw_cb * 0.10, z1_b + 0.08), _cpt(u_ct1 + 0.01, -hw_ct * 0.10, z_ct - 0.06), _cpt(u_ct1 + 0.01, -hw_ct * 0.78, z_ct - 0.06)], glass_hi, (fu_e * 0.6, fu_n * 0.6, 0.8), zb=-0.03)
            # Rear sloped window
            _add_face([_cpt(u_cb0, -hw_cb, z1_b), _cpt(u_cb0, hw_cb, z1_b), _cpt(u_ct0, hw_ct, z_ct), _cpt(u_ct0, -hw_ct, z_ct)], glass_side, (-fu_e * 0.6, -fu_n * 0.6, 0.8))
            # Left & right side windows
            _add_face([_cpt(u_cb0, -hw_cb, z1_b), _cpt(u_cb1, -hw_cb, z1_b), _cpt(u_ct1, -hw_ct, z_ct), _cpt(u_ct0, -hw_ct, z_ct)], glass_side, (-rv_e * 0.85, -rv_n * 0.85, 0.5))
            _add_face([_cpt(u_cb0, hw_cb, z1_b), _cpt(u_cb1, hw_cb, z1_b), _cpt(u_ct1, hw_ct, z_ct), _cpt(u_ct0, hw_ct, z_ct)], glass_side, (rv_e * 0.85, rv_n * 0.85, 0.5))
            # Cabin roof top
            _add_face([_cpt(u_ct0, -hw_ct, z_ct), _cpt(u_ct1, -hw_ct, z_ct), _cpt(u_ct1, hw_ct, z_ct), _cpt(u_ct0, hw_ct, z_ct)], roof_hi, (0.0, 0.0, 1.0))

            # 6. Crisp 1px dark-ink silhouette outline around the solid car (tinyrj.com style!)
            if bx0 <= bx1 and by0 <= by1:
                ox0 = max(0, bx0 - 1)
                oy0 = max(0, by0 - 1)
                ox1 = min(W, bx1 + 2)
                oy1 = min(H, by1 + 2)
                sub_obj = obj_buf[oy0:oy1, ox0:ox1]
                car_m = sub_obj == oid_c
                if car_m.any():
                    ring = ndimage.binary_dilation(car_m) & (~car_m)
                    # Only ink pixels that are ground/behind this car (never overwrite trees/buildings in front!)
                    sub_z = zbuf[oy0:oy1, ox0:ox1]
                    ring_ok = ring & (sub_obj == 0) & (sub_z >= (car_d_max - 1.5))
                    if ring_ok.any():
                        rgb_buf[oy0:oy1, ox0:ox1][ring_ok] = outline_col

    # 7. F7: Deterministic 3D Sidewalk/Viaduct/Platform/Promenade Streetlamps (1px slender poles + lantern bulbs!)
    if len(scene.lamp_e) > 0:
        for li_s in range(len(scene.lamp_e)):
            le_s = float(scene.lamp_e[li_s])
            ln_s = float(scene.lamp_n[li_s])
            lz_s = float(scene.lamp_z[li_s])
            lk_s = int(scene.lamp_kind[li_s])
            if crop_box_lv95 is not None and not (
                crop_box_lv95[0] + 1.5 <= le_s <= crop_box_lv95[2] - 1.5
                and crop_box_lv95[1] + 1.5 <= ln_s <= crop_box_lv95[3] - 1.5
            ):
                continue
            rc_l = int(np.clip((N_MAX - ln_s) / GRID_RES, 0, GRID_H - 1))
            cc_l = int(np.clip((le_s - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if not amask[rc_l, cc_l]:
                continue
            h_pole = 4.8 if lk_s in (0, 1) else (4.2 if lk_s == 2 else 3.6)
            _draw_3d_seg(le_s, ln_s, lz_s, le_s, ln_s, lz_s + h_pole, [84.0, 90.0, 98.0], mat_c=M_BRIDGE, oid=238000 + li_s, thick=False)
            px_h, py_h, pd_h = camera.project(np.array([le_s]), np.array([ln_s]), np.array([lz_s + h_pole]))
            hx = int(round(float(px_h[0] + shift_x)))
            hy = int(round(float(py_h[0] + shift_y)))
            hd = float(pd_h[0]) - 0.12
            if preset_key == "night":
                head_offs = ((0, 0), (1, 0), (0, -1), (1, -1))
                h_col, h_mat = [255.0, 232.0, 148.0], M_WINDOW_LIT
            elif preset_key == "sunset":
                head_offs = ((0, 0), (1, 0))
                h_col, h_mat = [252.0, 208.0, 118.0], M_WINDOW_LIT
            else:
                head_offs = ((0, 0), (1, 0))
                h_col, h_mat = [186.0, 192.0, 198.0], M_BRIDGE
            for ox_h, oy_h in head_offs:
                tx_h, ty_h = hx + ox_h, hy + oy_h
                if 0 <= tx_h < W and 0 <= ty_h < H and hd < zbuf[ty_h, tx_h]:
                    zbuf[ty_h, tx_h] = hd
                    rgb_buf[ty_h, tx_h] = h_col
                    mat_buf[ty_h, tx_h] = h_mat
                    obj_buf[ty_h, tx_h] = 238000 + li_s
                    norm_buf[ty_h, tx_h] = [0.0, 0.0, 1.0]
                    shadow_buf[ty_h, tx_h] = False

    # 8. F14c: Reformierte Kirche Cemetery Jura-Stone Perimeter Wall (strictly clipped, skipping road/footpath gates!)
    for j in range(len(CEMETERY_POLY_LV95) - 1):
        ce0, cn0 = CEMETERY_POLY_LV95[j]
        ce1, cn1 = CEMETERY_POLY_LV95[j + 1]
        seg_l = math.hypot(ce1 - ce0, cn1 - cn0)
        n_sub = max(1, int(math.ceil(seg_l / 6.0)))
        for ks in range(n_sub):
            f0, f1 = ks / n_sub, (ks + 1) / n_sub
            se0, sn0 = ce0 + (ce1 - ce0) * f0, cn0 + (cn1 - cn0) * f0
            se1, sn1 = ce0 + (ce1 - ce0) * f1, cn0 + (cn1 - cn0) * f1
            me, mn = 0.5 * (se0 + se1), 0.5 * (sn0 + sn1)
            rc_m = int(np.clip((N_MAX - mn) / GRID_RES, 0, GRID_H - 1))
            cc_m = int(np.clip((me - E_MIN) / GRID_RES, 0, GRID_W - 1))
            # Skip vehicle/pedestrian entrance gates where road or footpath crosses wall
            if scene.sem[rc_m, cc_m] in (G_STREET_MAIN, G_STREET_MINOR, G_FOOTPATH) or scene.bldg_roof_mask[rc_m, cc_m]:
                continue
            zb_w = 0.5 * (_sample_dem(se0, sn0) + _sample_dem(se1, sn1))
            _draw_3d_panel(
                se0, sn0, se1, sn1, zb_w, zb_w + 1.15,
                col_body=np.array([134.0, 130.0, 122.0], dtype=np.float32),
                col_top=np.array([168.0, 164.0, 156.0], dtype=np.float32),
                oid=236000, mesh_only=False,
            )

    # 9. F14c: Deterministic Swiss Micro-Props (ZVV Bus Shelters, Lakeside Promenade Benches, Pasture Fences & Hay Bales!)
    # 9a. 5 Verified Sidewalk ZVV Bus Shelters (strictly off road centerlines, glowing ceiling strip at Night!)
    zvv_shelters = (
        (2684042.8, 1241842.8, -78.1),  # Bendlikon
        (2683878.2, 1242113.2, -77.8),  # Bahnhof Kilchberg
        (2684106.8, 1241506.2,  21.7),  # Lindt & Sprüngli
        (2684269.2, 1241357.8, -48.5),  # Schooren
        (2683402.2, 1241316.2, -179.2), # Kirche
    )
    for bi_z, (be_z, bn_z, bang_deg) in enumerate(zvv_shelters):
        if not _prop_ok(be_z, bn_z, inset=2.0, allow_sidewalk=True):
            continue
        bz_z = _sample_dem(be_z, bn_z)
        rad_z = math.radians(bang_deg)
        ux_z, uy_z = math.cos(rad_z), math.sin(rad_z)
        vx_z, vy_z = -uy_z, ux_z
        oid_z = 237000 + bi_z
        # Anthracite steel posts + glazed back panel + cantilevered flat roof + interior bench
        e_l, n_l = be_z - 1.65 * ux_z, bn_z - 1.65 * uy_z
        e_r, n_r = be_z + 1.65 * ux_z, bn_z + 1.65 * uy_z
        _draw_3d_panel(e_l, n_l, e_r, n_r, bz_z + 0.15, bz_z + 2.25, np.array([118.0, 148.0, 168.0], dtype=np.float32), oid=oid_z, mesh_only=True)
        _draw_3d_seg(e_l, n_l, bz_z, e_l, n_l, bz_z + 2.35, [52.0, 56.0, 64.0], oid=oid_z, thick=True)
        _draw_3d_seg(e_r, n_r, bz_z, e_r, n_r, bz_z + 2.35, [52.0, 56.0, 64.0], oid=oid_z, thick=True)
        # Cantilevered solid roof deck quad (zero slatted-bar gaps!)
        zvv_roof_pts = [
            (e_l - 0.35 * vx_z, n_l - 0.35 * vy_z, bz_z + 2.36),
            (e_r - 0.35 * vx_z, n_r - 0.35 * vy_z, bz_z + 2.36),
            (e_r + 0.85 * vx_z, n_r + 0.85 * vy_z, bz_z + 2.36),
            (e_l + 0.85 * vx_z, n_l + 0.85 * vy_z, bz_z + 2.36),
        ]
        _fill_3d_poly(
            camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
            zvv_roof_pts, [66.0, 72.0, 80.0], oid_z, mat_id=M_BRIDGE, norm=(0.0, 0.0, 1.0),
            rib_col=[162.0, 168.0, 174.0], edge_frame_w=0.14,
        )
        # Warm interior timber bench
        _draw_3d_seg(e_l + 0.35 * vx_z + 0.3 * ux_z, n_l + 0.35 * vy_z + 0.3 * uy_z, bz_z + 0.50, e_r + 0.35 * vx_z - 0.3 * ux_z, n_r + 0.35 * vy_z - 0.3 * uy_z, bz_z + 0.50, [146.0, 104.0, 68.0], oid=oid_z, thick=True)
        # Iconic ZVV blue/white bus-stop pole sign
        pe_z, pn_z = e_r + 0.45 * ux_z + 0.35 * vx_z, n_r + 0.45 * uy_z + 0.35 * vy_z
        _draw_3d_seg(pe_z, pn_z, bz_z, pe_z, pn_z, bz_z + 2.15, [132.0, 138.0, 146.0], oid=oid_z)
        _draw_3d_seg(pe_z, pn_z, bz_z + 2.15, pe_z, pn_z, bz_z + 2.55, [26.0, 94.0, 174.0], oid=oid_z, thick=True)
        _draw_3d_seg(pe_z, pn_z, bz_z + 2.55, pe_z, pn_z, bz_z + 2.75, [240.0, 242.0, 244.0], oid=oid_z, thick=True)
        # Night glowing ceiling strip
        if is_night:
            _draw_3d_seg(e_l + 0.35 * vx_z + 0.25 * ux_z, n_l + 0.35 * vy_z + 0.25 * uy_z, bz_z + 2.18, e_r + 0.35 * vx_z - 0.25 * ux_z, n_r + 0.35 * vy_z - 0.25 * uy_z, bz_z + 2.18, [255.0, 224.0, 152.0], mat_c=M_WINDOW_LIT, oid=oid_z, thick=True)

    # 9b. 20 Lakeside Promenade Wooden Benches facing ESE toward Lake Zurich (incl. Morfanlage)
    prom_benches = (
        (2684017.2, 1242062.8), (2684024.8, 1242058.8), (2684040.8, 1242048.2),
        (2684199.2, 1241656.2), (2684221.8, 1241627.8), (2684222.8, 1241589.8),
        (2684286.2, 1241488.2), (2684304.8, 1241471.2), (2684312.2, 1241454.2),
        (2684465.2, 1241192.8), (2684484.8, 1241167.8), (2684494.8, 1241138.8),
        (2683610.2, 1243038.8), (2683613.2, 1242993.2), (2683639.2, 1242982.8),
        (2683882.0, 1242396.0), (2683892.0, 1242376.0), (2683904.0, 1242352.0),
        (2683914.0, 1242332.0), (2683922.0, 1242306.0),
    )
    b_ux, b_uy = math.cos(math.radians(-65.0)), math.sin(math.radians(-65.0))
    for bi_b, (be_b, bn_b) in enumerate(prom_benches):
        if not _prop_ok(be_b, bn_b, inset=2.0):
            continue
        bz_b = _sample_dem(be_b, bn_b)
        oid_b = 237200 + bi_b
        e0_b, n0_b = be_b - 0.95 * b_ux, bn_b - 0.95 * b_uy
        e1_b, n1_b = be_b + 0.95 * b_ux, bn_b + 0.95 * b_uy
        _draw_3d_seg(e0_b, n0_b, bz_b, e0_b, n0_b, bz_b + 0.48, [44.0, 48.0, 54.0], oid=oid_b)
        _draw_3d_seg(e1_b, n1_b, bz_b, e1_b, n1_b, bz_b + 0.48, [44.0, 48.0, 54.0], oid=oid_b)
        _draw_3d_seg(e0_b, n0_b, bz_b + 0.48, e1_b, n1_b, bz_b + 0.48, [168.0, 118.0, 72.0], oid=oid_b, thick=True)
        _draw_3d_seg(e0_b - 0.25 * b_uy, n0_b + 0.25 * b_ux, bz_b + 0.88, e1_b - 0.25 * b_uy, n1_b + 0.25 * b_ux, bz_b + 0.88, [150.0, 102.0, 62.0], oid=oid_b)

    # 9c. Upper Meadow Swiss Wooden Pasture Fences & Golden Round Hay Bales (02_kirche, 06_sanatorium, 10_stockengut)
    pasture_fences = (
        (2683512.0, 1241180.0, 2683584.0, 1241215.0),
        (2683512.0, 1241180.0, 2683508.0, 1241248.0),
        (2683372.0, 1242395.0, 2683432.0, 1242388.0),
        (2683175.0, 1242050.0, 2683225.0, 1242095.0),
        (2683225.0, 1242095.0, 2683285.0, 1242075.0),
        (2683165.0, 1241980.0, 2683180.0, 1242045.0),
    )
    for fi_p, (fe0, fn0, fe1, fn1) in enumerate(pasture_fences):
        flen = math.hypot(fe1 - fe0, fn1 - fn0)
        n_posts = max(2, int(round(flen / 3.2)))
        oid_f = 237400 + fi_p
        for kp in range(n_posts):
            t0 = kp / n_posts
            t1 = (kp + 1) / n_posts
            pe0, pn0 = fe0 + (fe1 - fe0) * t0, fn0 + (fn1 - fn0) * t0
            pe1, pn1 = fe0 + (fe1 - fe0) * t1, fn0 + (fn1 - fn0) * t1
            if not (_prop_ok(pe0, pn0, inset=2.0) and _prop_ok(pe1, pn1, inset=2.0)):
                continue
            z0_p, z1_p = _sample_dem(pe0, pn0), _sample_dem(pe1, pn1)
            _draw_3d_seg(pe0, pn0, z0_p, pe0, pn0, z0_p + 1.15, [112.0, 86.0, 62.0], oid=oid_f)
            _draw_3d_seg(pe0, pn0, z0_p + 0.55, pe1, pn1, z1_p + 0.55, [132.0, 104.0, 76.0], oid=oid_f)
            _draw_3d_seg(pe0, pn0, z0_p + 1.05, pe1, pn1, z1_p + 1.05, [138.0, 110.0, 80.0], oid=oid_f)

    hay_bales = (
        (2683535.0, 1241240.0), (2683546.0, 1241226.0), (2683558.0, 1241248.0),
        (2683524.0, 1241205.0), (2683572.0, 1241195.0),
        (2683392.0, 1242422.0), (2683404.0, 1242434.0), (2683448.0, 1242425.0),
    )
    for hi_b, (he_b, hn_b) in enumerate(hay_bales):
        if not _prop_ok(he_b, hn_b, inset=2.0):
            continue
        hz_b = _sample_dem(he_b, hn_b)
        oid_h = 237600 + hi_b
        # Solid 3D cylindrical round hay bale (shadow disc + 12-gon cylindrical wall + sunlit straw top!)
        ang_h = np.linspace(0.0, 2.0 * math.pi, 12, endpoint=False)
        cos_h, sin_h = np.cos(ang_h), np.sin(ang_h)
        sh_pts = [(he_b + 0.82 * float(cos_h[k]), hn_b + 0.82 * float(sin_h[k]), hz_b + 0.03) for k in range(12)]
        _fill_3d_poly(
            camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
            sh_pts, [42.0, 62.0, 34.0], oid_h, mat_id=M_BRIDGE, is_shadow=True, shadow_mul=0.72,
        )
        for k in range(12):
            k2 = (k + 1) % 12
            c0, s0 = float(cos_h[k]), float(sin_h[k])
            c1, s1 = float(cos_h[k2]), float(sin_h[k2])
            nx_h, ny_h = 0.5 * (c0 + c1), 0.5 * (s0 + s1)
            side_pts = [
                (he_b + 0.70 * c0, hn_b + 0.70 * s0, hz_b + 0.05),
                (he_b + 0.70 * c1, hn_b + 0.70 * s1, hz_b + 0.05),
                (he_b + 0.68 * c1, hn_b + 0.68 * s1, hz_b + 1.22),
                (he_b + 0.68 * c0, hn_b + 0.68 * s0, hz_b + 1.22),
            ]
            _fill_3d_poly(
                camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                side_pts, [196.0, 162.0, 86.0], oid_h, mat_id=M_BRIDGE, norm=(nx_h, ny_h, 0.18),
            )
        top_pts = [(he_b + 0.68 * float(cos_h[k]), hn_b + 0.68 * float(sin_h[k]), hz_b + 1.24) for k in range(12)]
        _fill_3d_poly(
            camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
            top_pts, [228.0, 198.0, 118.0], oid_h, mat_id=M_BRIDGE, norm=(0.0, 0.0, 1.0),
        )

    # 9d. v9.0 Museum-Grade Village, Civic & Estate 3D Props (all strictly _prop_ok(..., inset=2.0)!)
    # 1. Lindt Forecourt: granite bollards (oid=244910), boxwood planters (237700..237703), golden entrance totem (244911)
    for kb in range(6):
        tb = kb / 5.0
        be_l = 2684136.0 + 6.0 * tb
        bn_l = 1241404.0 + 20.0 * tb
        if _prop_ok(be_l, bn_l, inset=2.0, allow_sidewalk=True):
            zl = _sample_dem(be_l, bn_l)
            _draw_3d_seg(be_l, bn_l, zl, be_l, bn_l, zl + 0.85, [154.0, 152.0, 146.0], oid=244910)
            _draw_3d_seg(be_l, bn_l, zl + 0.85, be_l, bn_l, zl + 0.98, [214.0, 212.0, 206.0], oid=244910)
    for pi_l, (pe_l, pn_l) in enumerate(((2684131.0, 1241407.0), (2684133.0, 1241417.0), (2684126.0, 1241402.0), (2684130.0, 1241424.0))):
        if _prop_ok(pe_l, pn_l, inset=2.0, allow_sidewalk=True):
            zp_l = _sample_dem(pe_l, pn_l)
            _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, pe_l, pn_l, zp_l, zp_l + 0.65, 0.45, (186.0, 178.0, 164.0), 237700 + pi_l, M_BRIDGE)
            _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, pe_l, pn_l, zp_l + 0.65, zp_l + 1.25, 0.40, (46.0, 98.0, 48.0), 237700 + pi_l, M_BRIDGE)
    if _prop_ok(2684139.0, 1241413.5, inset=2.0, allow_sidewalk=True):
        zt_l = _sample_dem(2684139.0, 1241413.5)
        _draw_3d_seg(2684139.0, 1241413.5, zt_l, 2684139.0, 1241413.5, zt_l + 3.2, [54.0, 46.0, 42.0], oid=244911, thick=True)
        _draw_3d_seg(2684139.0, 1241413.5, zt_l + 2.0, 2684139.0, 1241413.5, zt_l + 2.9, [236.0, 192.0, 68.0], mat_c=M_WINDOW_LIT if is_night else M_BRIDGE, oid=244911, thick=True)
    # M3.5 Enea-landscaped Schokoladenplatz Jura-stone benches & NE café parasols
    for bni_l, (bne_l, bnn_l) in enumerate(((2684134.5, 1241404.0), (2684137.0, 1241419.5), (2684129.0, 1241428.0))):
        if _prop_ok(bne_l, bnn_l, inset=2.0, allow_sidewalk=True):
            zbn_l = _sample_dem(bne_l, bnn_l)
            _draw_3d_seg(bne_l - 0.9, bnn_l - 0.3, zbn_l + 0.45, bne_l + 0.9, bnn_l + 0.3, zbn_l + 0.45, [204.0, 198.0, 186.0], oid=237705 + bni_l, thick=True)
    if not is_night:
        for upe_l, upn_l in ((2684124.5, 1241427.0), (2684127.5, 1241430.5)):
            if _prop_ok(upe_l, upn_l, inset=2.0, allow_sidewalk=True):
                zup_l = _sample_dem(upe_l, upn_l)
                _draw_3d_seg(upe_l, upn_l, zup_l, upe_l, upn_l, zup_l + 2.15, [82.0, 80.0, 76.0], oid=244912)
                _draw_3d_seg(upe_l - 1.0, upn_l, zup_l + 2.15, upe_l + 1.0, upn_l, zup_l + 2.15, [236.0, 230.0, 216.0], oid=237708, thick=True)
                _draw_3d_seg(upe_l, upn_l - 1.0, zup_l + 2.15, upe_l, upn_l + 1.0, zup_l + 2.15, [236.0, 230.0, 216.0], oid=237708, thick=True)

    # 2. Reformierte Kirche & Cemetery: stone gate pillars, cypress spires, 3D Dorfbrunnen, Thomas Mann/C.F. Meyer memorial
    for gi_c, (ge_c, gn_c) in enumerate(((2683438.0, 1241305.0), (2683442.0, 1241306.0), (2683463.0, 1241276.0), (2683464.0, 1241272.0))):
        if _prop_ok(ge_c, gn_c, inset=2.0, allow_sidewalk=True):
            zg_c = _sample_dem(ge_c, gn_c)
            _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, ge_c, gn_c, zg_c, zg_c + 1.65, 0.35, (186.0, 178.0, 164.0), 237720 + gi_c, M_BRIDGE)
            _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, ge_c, gn_c, zg_c + 1.65, zg_c + 1.88, 0.40, (214.0, 208.0, 196.0), 237720 + gi_c, M_BRIDGE)
    for cy_i, (cy_e, cy_n) in enumerate(((2683424.0, 1241256.0), (2683436.0, 1241242.0), (2683420.0, 1241205.0), (2683442.0, 1241195.0), (2683418.0, 1241152.0), (2683445.0, 1241145.0))):
        if _prop_ok(cy_e, cy_n, inset=2.0):
            zcy = _sample_dem(cy_e, cy_n)
            _draw_3d_seg(cy_e, cy_n, zcy, cy_e, cy_n, zcy + 3.2, [34.0, 68.0, 42.0], oid=237724 + cy_i, thick=True)
            _draw_3d_seg(cy_e, cy_n, zcy + 2.8, cy_e, cy_n, zcy + 4.8, [46.0, 86.0, 52.0], oid=237724 + cy_i)
    if _prop_ok(2683436.0, 1241298.0, inset=2.0, allow_sidewalk=True):
        zdb = _sample_dem(2683436.0, 1241298.0)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683436.0, 1241298.0, zdb, zdb + 0.85, 0.95, (178.0, 172.0, 162.0), 237730, M_BRIDGE)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683436.0, 1241298.0, zdb + 0.72, zdb + 0.88, 0.72, (66.0, 152.0, 176.0), 237730, M_BRIDGE)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683436.0, 1241298.0, zdb + 0.85, zdb + 2.15, 0.22, (194.0, 188.0, 176.0), 237730, M_BRIDGE)
    if _prop_ok(2683434.0, 1241222.0, inset=2.0):
        zmm = _sample_dem(2683434.0, 1241222.0)
        # C.F. Meyer tall dark-granite obelisk beside south church wall
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683434.0, 1241222.0, zmm, zmm + 1.65, 0.34, (56.0, 58.0, 62.0), 237731, M_BRIDGE)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683434.0, 1241222.0, zmm + 1.65, zmm + 2.05, 0.22, (74.0, 76.0, 82.0), 237731, M_BRIDGE)
        _draw_3d_seg(2683434.34, 1241222.0, zmm + 0.65, 2683434.34, 1241222.0, zmm + 1.15, [196.0, 192.0, 182.0], oid=237731)
    if _prop_ok(2683428.0, 1241236.0, inset=2.0):
        ztm = _sample_dem(2683428.0, 1241236.0)
        # M3.5 Distinct Thomas Mann family grave: light-granite ledger slab + dark upright headstone + boxwood border
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683428.0, 1241236.0, ztm, ztm + 0.32, 0.85, (212.0, 208.0, 200.0), 237732, M_BRIDGE)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683427.3, 1241236.0, ztm + 0.25, ztm + 1.15, 0.28, (64.0, 66.0, 72.0), 237732, M_BRIDGE)
        _draw_3d_seg(2683427.1, 1241235.0, ztm + 0.22, 2683428.9, 1241235.0, ztm + 0.22, [44.0, 88.0, 48.0], oid=237732, thick=True)

    # 3. Navillepark terraced stone wall & fountain + Sanatorium Park balustrade, pergola & benches
    if _prop_ok(2684252.0, 1241432.0, inset=2.0) and _prop_ok(2684260.0, 1241456.0, inset=2.0):
        znv = 0.5 * (_sample_dem(2684252.0, 1241432.0) + _sample_dem(2684260.0, 1241456.0))
        _draw_3d_panel(2684252.0, 1241432.0, 2684260.0, 1241456.0, znv, znv + 1.2, np.array([174.0, 168.0, 156.0], dtype=np.float32), np.array([212.0, 206.0, 194.0], dtype=np.float32), oid=237740)
    if _prop_ok(2684242.0, 1241428.0, inset=2.0):
        znf = _sample_dem(2684242.0, 1241428.0)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2684242.0, 1241428.0, znf, znf + 0.72, 0.85, (186.0, 180.0, 168.0), 237741, M_BRIDGE)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2684242.0, 1241428.0, znf + 0.62, znf + 0.76, 0.62, (66.0, 154.0, 178.0), 237741, M_BRIDGE)
    if _prop_ok(2683546.0, 1242455.0, inset=2.0) and _prop_ok(2683552.0, 1242486.0, inset=2.0):
        zsn = 0.5 * (_sample_dem(2683546.0, 1242455.0) + _sample_dem(2683552.0, 1242486.0))
        _draw_3d_panel(2683546.0, 1242455.0, 2683552.0, 1242486.0, zsn, zsn + 1.05, np.array([186.0, 180.0, 168.0], dtype=np.float32), np.array([224.0, 220.0, 210.0], dtype=np.float32), oid=237746)
    if _prop_ok(2683514.0, 1242442.0, inset=2.0):
        zpg = _sample_dem(2683514.0, 1242442.0)
        for de_p, dn_p in ((-1.8, -1.2), (1.8, -1.2), (-1.8, 1.2), (1.8, 1.2)):
            _draw_3d_seg(2683514.0 + de_p, 1242442.0 + dn_p, zpg, 2683514.0 + de_p, 1242442.0 + dn_p, zpg + 2.6, [118.0, 84.0, 56.0], oid=237747, thick=True)
        for dn_b in (-1.2, -0.4, 0.4, 1.2):
            _draw_3d_seg(2683514.0 - 1.9, 1242442.0 + dn_b, zpg + 2.6, 2683514.0 + 1.9, 1242442.0 + dn_b, zpg + 2.6, [132.0, 96.0, 64.0], oid=237747)
    for sb_i, (sbe, sbn) in enumerate(((2683518.0, 1242458.0), (2683490.0, 1242432.0), (2683505.0, 1242402.0), (2683476.0, 1242462.0))):
        if _prop_ok(sbe, sbn, inset=2.0):
            zsb = _sample_dem(sbe, sbn)
            _draw_3d_seg(sbe - 0.85, sbn - 0.35, zsb + 0.48, sbe + 0.85, sbn + 0.35, zsb + 0.48, [46.0, 96.0, 62.0], oid=237748 + sb_i, thick=True)
    # M3.5 Sanatorium Portier-Loge entrance gate pillars + signboard (oid=244957 excluded) & historic Sodbrunnen wellhead
    for ple_s, pln_s in ((2683556.5, 1242456.0), (2683559.5, 1242460.0)):
        if _prop_ok(ple_s, pln_s, inset=2.0, allow_sidewalk=True):
            zpl_s = _sample_dem(ple_s, pln_s)
            _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, ple_s, pln_s, zpl_s, zpl_s + 1.9, 0.35, (206.0, 200.0, 188.0), 237752, M_BRIDGE)
    if _prop_ok(2683558.0, 1242458.0, inset=2.0, allow_sidewalk=True):
        zps_s = _sample_dem(2683558.0, 1242458.0)
        _draw_3d_seg(2683557.2, 1242457.0, zps_s + 1.45, 2683558.8, 1242459.0, zps_s + 1.45, [34.0, 74.0, 52.0], oid=244957, thick=True)
        _draw_3d_seg(2683557.4, 1242457.3, zps_s + 1.52, 2683558.6, 1242458.7, zps_s + 1.52, [236.0, 198.0, 88.0], oid=244957)
    if _prop_ok(2683486.0, 1242402.0, inset=2.0):
        zsd_s = _sample_dem(2683486.0, 1242402.0)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683486.0, 1242402.0, zsd_s, zsd_s + 0.95, 0.72, (178.0, 172.0, 160.0), 237753, M_BRIDGE)
        _draw_3d_seg(2683485.4, 1242402.0, zsd_s + 0.95, 2683485.4, 1242402.0, zsd_s + 2.15, [52.0, 56.0, 62.0], oid=244957)
        _draw_3d_seg(2683486.6, 1242402.0, zsd_s + 0.95, 2683486.6, 1242402.0, zsd_s + 2.15, [52.0, 56.0, 62.0], oid=244957)
        _draw_3d_seg(2683485.4, 1242402.0, zsd_s + 2.15, 2683486.6, 1242402.0, zsd_s + 2.15, [52.0, 56.0, 62.0], oid=244957)
    # M3.5 St. Elisabeth SE forecourt terraced white concrete steps
    if _prop_ok(2683520.0, 1241625.0, inset=2.0, allow_sidewalk=True):
        zse_f = _sample_dem(2683520.0, 1241625.0)
        for st_e in range(3):
            _draw_3d_seg(2683518.5 + st_e * 0.5, 1241622.5, zse_f + 0.22 * (3 - st_e), 2683520.5 + st_e * 0.5, 1241627.5, zse_f + 0.22 * (3 - st_e), [224.0, 222.0, 216.0], oid=237756, thick=True)

    # 4. C.F. Meyer-Haus (Alte Landstrasse 170): rustic dark-grey fieldstone garden retaining wall, wrought-iron gate, pergola & fountain
    if _prop_ok(2683724.0, 1241428.0, inset=2.0) and _prop_ok(2683730.0, 1241454.0, inset=2.0):
        zcm1 = _sample_dem(2683726.0, 1241434.0)
        zcm2 = _sample_dem(2683728.5, 1241448.0)
        _draw_3d_panel(2683724.0, 1241428.0, 2683726.8, 1241439.5, zcm1, zcm1 + 1.25, np.array([128.0, 124.0, 116.0], dtype=np.float32), np.array([176.0, 172.0, 162.0], dtype=np.float32), oid=237760)
        _draw_3d_panel(2683727.4, 1241442.2, 2683730.0, 1241454.0, zcm2, zcm2 + 1.25, np.array([128.0, 124.0, 116.0], dtype=np.float32), np.array([176.0, 172.0, 162.0], dtype=np.float32), oid=237760)
        for gp_e, gp_n in ((2683726.8, 1241439.5), (2683727.4, 1241442.2)):
            zgp = _sample_dem(gp_e, gp_n)
            _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, gp_e, gp_n, zgp, zgp + 1.75, 0.30, (156.0, 152.0, 144.0), 237761, M_BRIDGE)
        _draw_3d_seg(2683726.8, 1241439.5, zcm1 + 1.35, 2683727.4, 1241442.2, zcm2 + 1.35, [44.0, 48.0, 54.0], oid=237762)
        _draw_3d_seg(2683726.8, 1241439.5, zcm1 + 0.65, 2683727.4, 1241442.2, zcm2 + 0.65, [44.0, 48.0, 54.0], oid=237762)
    if _prop_ok(2683702.0, 1241426.0, inset=2.0):
        zcp = _sample_dem(2683702.0, 1241426.0)
        for de_p, dn_p in ((-1.6, -1.1), (1.6, -1.1), (-1.6, 1.1), (1.6, 1.1)):
            _draw_3d_seg(2683702.0 + de_p, 1241426.0 + dn_p, zcp, 2683702.0 + de_p, 1241426.0 + dn_p, zcp + 2.5, [112.0, 80.0, 54.0], oid=237763)
        for dn_b in (-1.0, 0.0, 1.0):
            _draw_3d_seg(2683700.3, 1241426.0 + dn_b, zcp + 2.55, 2683703.7, 1241426.0 + dn_b, zcp + 2.55, [54.0, 108.0, 52.0], oid=237763, thick=True)
    if _prop_ok(2683720.0, 1241434.0, inset=2.0):
        zcf = _sample_dem(2683720.0, 1241434.0)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683720.0, 1241434.0, zcf, zcf + 0.72, 0.78, (186.0, 180.0, 168.0), 237764, M_BRIDGE)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683720.0, 1241434.0, zcf + 0.62, zcf + 0.76, 0.54, (68.0, 152.0, 178.0), 237764, M_BRIDGE)
        # M3.5 Auf Brunnen carved stone spring spout column
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683719.6, 1241434.0, zcf + 0.72, zcf + 1.55, 0.18, (204.0, 198.0, 186.0), 237764, M_BRIDGE)

    # 5. Gemeindehaus Forecourt: formal limestone steps + dual 3D flagpoles (oid=244900, 244901 EXCLUDED from occ_m!)
    if _prop_ok(2683642.0, 1242099.0, inset=2.0, allow_sidewalk=True):
        zgs = _sample_dem(2683642.0, 1242099.0)
        for step_k in range(3):
            off_s = step_k * 0.55
            _draw_3d_seg(2683640.0 + off_s, 1242094.0, zgs + 0.25 * (3 - step_k), 2683644.0 + off_s, 1242104.0, zgs + 0.25 * (3 - step_k), [194.0, 188.0, 176.0], oid=237780, thick=True)
    for fp_i, (fpe, fpn, is_swiss) in enumerate(((2683646.0, 1242086.0, True), (2683648.5, 1242091.0, False))):
        if _prop_ok(fpe, fpn, inset=2.0, allow_sidewalk=True):
            zfp = _sample_dem(fpe, fpn)
            oid_fp = 244900 + fp_i
            _draw_3d_seg(fpe, fpn, zfp, fpe, fpn, zfp + 7.5, [218.0, 222.0, 226.0], oid=oid_fp)
            if is_swiss:
                _draw_3d_seg(fpe, fpn, zfp + 6.7, fpe + 1.25, fpn + 0.4, zfp + 6.9, [218.0, 38.0, 38.0], oid=oid_fp, thick=True)
                _draw_3d_seg(fpe + 0.45, fpn + 0.14, zfp + 6.8, fpe + 0.78, fpn + 0.24, zfp + 6.84, [246.0, 246.0, 242.0], oid=oid_fp)
            else:
                # M3.5 Authentic Kilchberg Wappen flag: azure #1a5fb4 + 4-petal white flower + gold center
                _draw_3d_seg(fpe, fpn, zfp + 6.75, fpe + 1.25, fpn + 0.4, zfp + 6.95, [26.0, 95.0, 180.0], oid=oid_fp, thick=True)
                _draw_3d_seg(fpe + 0.40, fpn + 0.13, zfp + 6.84, fpe + 0.85, fpn + 0.27, zfp + 6.88, [244.0, 246.0, 248.0], oid=oid_fp)
                _draw_3d_seg(fpe + 0.58, fpn + 0.18, zfp + 6.85, fpe + 0.66, fpn + 0.21, zfp + 6.87, [242.0, 196.0, 48.0], oid=oid_fp)

    # 6. Stockengut: stone courtyard wall, Hofladen farm stand + crates & horned Swiss Grauvieh cattle
    if _prop_ok(2683226.0, 1242016.0, inset=2.0) and _prop_ok(2683254.0, 1242018.0, inset=2.0):
        zsw = 0.5 * (_sample_dem(2683226.0, 1242016.0) + _sample_dem(2683254.0, 1242018.0))
        _draw_3d_panel(2683226.0, 1242016.0, 2683254.0, 1242018.0, zsw, zsw + 1.15, np.array([170.0, 164.0, 152.0], dtype=np.float32), np.array([208.0, 202.0, 190.0], dtype=np.float32), oid=237790)
    if _prop_ok(2683222.0, 1242024.0, inset=2.0):
        zhl = _sample_dem(2683222.0, 1242024.0)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683222.0, 1242024.0, zhl, zhl + 1.25, 0.95, (146.0, 102.0, 66.0), 237791, M_BRIDGE)
        _draw_3d_seg(2683221.0, 1242023.0, zhl + 2.25, 2683223.2, 1242025.0, zhl + 2.25, [82.0, 60.0, 44.0], oid=237792, thick=True)
        _draw_3d_seg(2683221.3, 1242023.3, zhl + 2.32, 2683222.9, 1242024.7, zhl + 2.32, [114.0, 84.0, 58.0], oid=237792)
        # Wooden Hofladen produce crates with apples
        for cr_e, cr_n, cr_top in ((2683223.8, 1242023.2, (198.0, 54.0, 46.0)), (2683224.5, 1242024.1, (92.0, 146.0, 62.0))):
            if _prop_ok(cr_e, cr_n, inset=2.0):
                zcr_s = _sample_dem(cr_e, cr_n)
                _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, cr_e, cr_n, zcr_s, zcr_s + 0.45, 0.34, (156.0, 114.0, 68.0), 237793, M_BRIDGE)
                _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, cr_e, cr_n, zcr_s + 0.45, zcr_s + 0.58, 0.28, cr_top, 237793, M_BRIDGE)
    # M3.5 Grazing horned Swiss Grauvieh cattle (silvery-grey/taupe) on open upland meadow NW of Stockengut
    if not is_night:
        for gv_e, gv_n in ((2683162.0, 1242094.0), (2683154.0, 1242102.0), (2683170.0, 1242106.0), (2683148.0, 1242092.0)):
            if _prop_ok(gv_e, gv_n, inset=2.0):
                zgv = _sample_dem(gv_e, gv_n)
                _draw_3d_seg(gv_e - 0.65, gv_n - 0.15, zgv + 0.85, gv_e + 0.65, gv_n + 0.15, zgv + 0.85, [155.0, 150.0, 142.0], oid=237794, thick=True)
                _draw_3d_seg(gv_e - 0.5, gv_n - 0.12, zgv, gv_e - 0.5, gv_n - 0.12, zgv + 0.72, [110.0, 105.0, 98.0], oid=237794)
                _draw_3d_seg(gv_e + 0.5, gv_n + 0.12, zgv, gv_e + 0.5, gv_n + 0.12, zgv + 0.72, [110.0, 105.0, 98.0], oid=237794)
                _draw_3d_seg(gv_e + 0.65, gv_n + 0.15, zgv + 1.05, gv_e + 0.85, gv_n + 0.25, zgv + 1.20, [224.0, 220.0, 210.0], oid=237794)

    # 7. v11 Broelberggut south-garden round fountain, KGS-13500465 6-column colonnade pergola & walled-garden boxwoods
    if _prop_ok(2683770.0, 1241223.0, inset=1.5):
        zbf = _sample_dem(2683770.0, 1241223.0)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683770.0, 1241223.0, zbf, zbf + 0.45, 1.35, (192.0, 188.0, 178.0), 237800, M_BRIDGE)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683770.0, 1241223.0, zbf + 0.36, zbf + 0.48, 1.05, (86.0, 132.0, 152.0), 237800, M_BRIDGE)
    if _prop_ok(2683775.5, 1241196.6, inset=1.5):
        zbp = _sample_dem(2683775.5, 1241196.6)
        _draw_3d_panel(2683773.2, 1241193.8, 2683777.8, 1241199.4, zbp, zbp + 1.20, np.array([168.0, 162.0, 150.0], dtype=np.float32), np.array([186.0, 182.0, 172.0], dtype=np.float32), oid=237802)
        for de_c in (-1.4, 0.0, 1.4):
            for dn_c in (-1.6, 1.6):
                _draw_3d_seg(2683775.5 + de_c, 1241196.6 + dn_c, zbp + 1.20, 2683775.5 + de_c, 1241196.6 + dn_c, zbp + 4.00, [162.0, 160.0, 152.0], oid=244960, thick=True)
        for dn_b in (-1.6, 0.0, 1.6):
            _draw_3d_seg(2683773.8, 1241196.6 + dn_b, zbp + 4.05, 2683777.2, 1241196.6 + dn_b, zbp + 4.05, [92.0, 108.0, 86.0], oid=244960, thick=True)
    for bhe, bhn in ((2683731.0, 1241251.0), (2683736.0, 1241248.0)):
        if _prop_ok(bhe, bhn, inset=2.0):
            zbh = _sample_dem(bhe, bhn)
            _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, bhe, bhn, zbh, zbh + 0.65, 1.05, (46.0, 86.0, 48.0), 237801, M_BRIDGE)

    # 8. v11 Hallenbad Kilchberg outdoor cold-plunge pool (Hochweidstr. 10 wellness terrace) & Sportanlage Hochweid floodlight masts
    if _prop_ok(2683226.0, 1241556.0, inset=2.0):
        zhp = _sample_dem(2683226.0, 1241556.0)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683226.0, 1241556.0, zhp, zhp + 0.45, 1.75, (194.0, 196.0, 194.0), 237805, M_BRIDGE)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, 2683226.0, 1241556.0, zhp + 0.36, zhp + 0.48, 1.42, (76.0, 168.0, 182.0), 237805, M_WINDOW_LIT if (is_night or preset_key == "sunset") else M_BRIDGE)
    for fl_i, (fle, fln) in enumerate(((2683138.0, 1241482.0), (2683194.0, 1241492.0), (2683148.0, 1241428.0), (2683204.0, 1241438.0))):
        if _prop_ok(fle, fln, inset=2.0):
            zfl = _sample_dem(fle, fln)
            oid_fl = 244940 + fl_i
            _draw_3d_seg(fle, fln, zfl, fle, fln, zfl + 14.0, [74.0, 80.0, 88.0], oid=oid_fl)
            _draw_3d_seg(fle - 0.85, fln, zfl + 14.0, fle + 0.85, fln, zfl + 14.0, [252.0, 246.0, 218.0], mat_c=M_WINDOW_LIT if (is_night or preset_key == "sunset") else M_BRIDGE, oid=oid_fl, thick=True)

    # 9. v11 TC Kilchberg court-side emerald-green parasols & 2 all-weather LED court floodlights (oid=244946..244948 excluded!)
    if not is_night:
        for tpi, (tpe, tpn, tp_c) in enumerate(((2683398.0, 1240907.0, [30.0, 140.0, 76.0]), (2683384.0, 1240904.0, [34.0, 148.0, 82.0]))):
            if _prop_ok(tpe, tpn, inset=2.0):
                ztp = _sample_dem(tpe, tpn)
                _draw_3d_seg(tpe, tpn, ztp, tpe, tpn, ztp + 2.1, [88.0, 76.0, 62.0], oid=244946)
                _draw_3d_seg(tpe - 1.1, tpn, ztp + 2.15, tpe + 1.1, tpn, ztp + 2.15, tp_c, oid=237808, thick=True)
                _draw_3d_seg(tpe, tpn - 1.1, ztp + 2.15, tpe, tpn + 1.1, ztp + 2.15, tp_c, oid=237808, thick=True)
    for tfl_i, (tfle, tfln) in enumerate(((2683404.0, 1240864.0), (2683424.0, 1240868.0))):
        if _prop_ok(tfle, tfln, inset=2.0):
            ztfl = _sample_dem(tfle, tfln)
            oid_tfl = 244947 + tfl_i
            _draw_3d_seg(tfle, tfln, ztfl, tfle, tfln, ztfl + 8.5, [76.0, 82.0, 90.0], oid=oid_tfl)
            _draw_3d_seg(tfle - 0.55, tfln, ztfl + 8.5, tfle + 0.55, tfln, ztfl + 8.5, [252.0, 248.0, 226.0], mat_c=M_WINDOW_LIT if (is_night or preset_key == "sunset") else M_BRIDGE, oid=oid_tfl, thick=True)


def _render_3d_harbor_and_boats(
    scene: SceneData,
    camera: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W: int,
    H: int,
    r0: int,
    r1: int,
    c0: int,
    c1: int,
    sub_mask: np.ndarray,
    zbuf: np.ndarray,
    rgb_buf: np.ndarray,
    mat_buf: np.ndarray,
    obj_buf: np.ndarray,
    norm_buf: np.ndarray,
    shadow_buf: np.ndarray,
    is_night: bool,
    crop_box_lv95: tuple[float, float, float, float] | None,
    active_mask: np.ndarray | None = None,
) -> None:
    """STAGE 2.7 (F10 + F13): Crisp 3D timber pier pilings/bollards/railings/swim ladders + water contact
    shadows, all 40 clean open-water moored boats (sailboats & Boesch wooden motorboats), and Seebad beach props!"""
    amask = active_mask if active_mask is not None else scene.diorama_mask
    mpp = camera.mpp
    step_l = max(0.06, mpp * 0.65)

    def _draw_harbor_seg(e0, n0, z0, e1, n1, z1, col, mat_c=M_HARBOR_OBJ, oid=255100, thick=False):
        dist = math.sqrt((e1 - e0) ** 2 + (n1 - n0) ** 2 + (z1 - z0) ** 2)
        ns = max(2, int(math.ceil(dist / step_l)) + 1)
        t = np.linspace(0.0, 1.0, ns, dtype=np.float64)
        es = e0 + (e1 - e0) * t
        ns_a = n0 + (n1 - n0) * t
        zs = z0 + (z1 - z0) * t
        cc = np.floor((es - E_MIN) / GRID_RES).astype(np.int32)
        rr = np.floor((N_MAX - ns_a) / GRID_RES).astype(np.int32)
        ok = (cc >= 0) & (cc < GRID_W) & (rr >= 0) & (rr < GRID_H)
        if crop_box_lv95 is not None:
            ok &= (es >= crop_box_lv95[0] + 1.0) & (es <= crop_box_lv95[2] - 1.0) & (ns_a >= crop_box_lv95[1] + 1.0) & (ns_a <= crop_box_lv95[3] - 1.0)
        if not ok.any():
            return
        in_am = np.zeros(ns, dtype=np.bool_)
        in_am[ok] = amask[rr[ok], cc[ok]]
        if not in_am.any():
            return
        px, py, pd = camera.project(es[in_am], ns_a[in_am], zs[in_am])
        ix = np.round(px + shift_x).astype(np.int32)
        iy = np.round(py + shift_y).astype(np.int32)
        vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
        if not vm.any():
            return
        ix, iy, pd = ix[vm], iy[vm], pd[vm]
        offs = ((0, 0), (1, 0)) if thick else ((0, 0),)
        for ox, oy in offs:
            tx = np.clip(ix + ox, 0, W - 1)
            ty = np.clip(iy + oy, 0, H - 1)
            win = pd < zbuf[ty, tx]
            if win.any():
                wy, wx = ty[win], tx[win]
                zbuf[wy, wx] = pd[win]
                rgb_buf[wy, wx] = col
                mat_buf[wy, wx] = mat_c
                obj_buf[wy, wx] = oid
                norm_buf[wy, wx] = [0.25, -0.25, 0.93]
                shadow_buf[wy, wx] = False

    # -------------------------------------------------------------------------
    # Part A: 3D Timber Pier Pilings & Handcrafted Solid Pier Decks
    # (Smooth pier water contact shadows are now computed directly in Stage 2 via pier_sdf!)
    # -------------------------------------------------------------------------
    sub_lake = scene.lake_mask[r0:r1, c0:c1]
    sub_pier = sub_mask & scene.pier_only_mask_05m[r0:r1, c0:c1] & sub_lake
    if sub_pier.any():
        # 3D Timber Pilings & Mooring Bollards spaced every 3.0m along pier edges (excluding Bendlikon handcrafted pier box)
        pier_edge = sub_pier & (~ndimage.binary_erosion(sub_pier, structure=np.ones((3, 3), dtype=bool)))
        er_p, ec_p = np.nonzero(pier_edge)
        if len(er_p) > 0:
            gr_e = er_p + r0
            gc_e = ec_p + c0
            keep_pil = ((gr_e % 6) == 0) & ((gc_e % 2) == 0)
            keep_pil |= ((gc_e % 6) == 0) & ((gr_e % 2) == 0)
            for rr_p, cc_p in zip(gr_e[keep_pil], gc_e[keep_pil]):
                ep = E_MIN + (cc_p + 0.5) * GRID_RES
                np_ = N_MAX - (rr_p + 0.5) * GRID_RES
                if 2684035.0 <= ep <= 2684072.0 and 1242060.0 <= np_ <= 1242090.0:
                    continue
                if crop_box_lv95 is not None and not (
                    crop_box_lv95[0] + 1.5 <= ep <= crop_box_lv95[2] - 1.5
                    and crop_box_lv95[1] + 1.5 <= np_ <= crop_box_lv95[3] - 1.5
                ):
                    continue
                z_deck = LAKE_SURFACE_Z + float(scene.pier_deck_h_05m[rr_p, cc_p])
                _draw_3d_box_column(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    ep, np_, LAKE_SURFACE_Z - 0.15, z_deck + 0.35, 0.16, (88.0, 70.0, 52.0), 255000, M_HARBOR_OBJ,
                )

    # Bendlikon ZSG Steamer Pier (Badweg 1.1) handcrafted fenders, solid planked gangway, railings & corner lantern!
    def _in_box_am(ep: float, np_: float, ins: float = 1.5) -> bool:
        if crop_box_lv95 is not None and not (
            crop_box_lv95[0] + ins <= ep <= crop_box_lv95[2] - ins
            and crop_box_lv95[1] + ins <= np_ <= crop_box_lv95[3] - ins
        ):
            return False
        rr_t = int(np.clip((N_MAX - np_) / GRID_RES, 0, GRID_H - 1))
        cc_t = int(np.clip((ep - E_MIN) / GRID_RES, 0, GRID_W - 1))
        return bool(amask[rr_t, cc_t])

    bend_in_view = _in_box_am(2684061.0, 1242076.0, ins=0.5) or _in_box_am(2684046.0, 1242070.0, ins=0.5)
    if bend_in_view:
        # 6 heavy lake-side timber fender pilings with white safety caps (leaving 3.5m steamer boarding gap)
        for fe_f, fn_f in (
            (2684069.6, 1242065.0), (2684069.8, 1242070.0), (2684069.8, 1242078.8),
            (2684069.6, 1242085.6), (2684056.5, 1242064.6), (2684056.5, 1242086.2),
        ):
            if _in_box_am(fe_f, fn_f):
                _draw_3d_box_column(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    fe_f, fn_f, 405.8, 408.55, 0.24, (78.0, 62.0, 46.0), 255200, M_HARBOR_OBJ,
                )
                _draw_3d_box_column(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    fe_f, fn_f, 408.55, 408.85, 0.25, (226.0, 224.0, 218.0), 255200, M_HARBOR_OBJ,
                )
        # Solid 3D isometric weathered-timber approach walkway deck (Steg) — zero wire-cage grid holes!
        ge0, ge1 = 2684036.8, 2684055.3
        gn0, gn1 = 1242065.6, 1242074.7
        gz_bot, gz_top = 407.18, 407.72
        # 0. Flush warm-stone shore threshold sill meeting the paved footpath cleanly (zero grey concrete blob!)
        se0, se1 = 2684035.8, 2684036.9
        sn0, sn1 = 1242065.6, 1242068.2
        sz_top = 407.56
        for sf_pts, sf_n in (
            ([(se0, sn0, gz_bot), (se1, sn0, gz_bot), (se1, sn0, sz_top), (se0, sn0, sz_top)], (0.0, -1.0, 0.0)),
            ([(se0, sn1, gz_bot), (se0, sn0, gz_bot), (se0, sn0, sz_top), (se0, sn1, sz_top)], (-1.0, 0.0, 0.0)),
        ):
            _fill_3d_poly(
                camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                sf_pts, [142.0, 138.0, 128.0], 255201, mat_id=M_HARBOR_OBJ, norm=sf_n,
            )
        _fill_3d_poly(
            camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
            [(se0, sn0, sz_top), (se1, sn0, sz_top), (se1, sn1, sz_top), (se0, sn1, sz_top)],
            [176.0, 170.0, 158.0], 255201, mat_id=M_HARBOR_OBJ, norm=(0.0, 0.0, 1.0),
        )
        # 1. Soft water contact shadow directly beneath gangway
        _fill_3d_poly(
            camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
            [(ge0, gn0 - 0.5, LAKE_SURFACE_Z + 0.02), (ge1, gn0 - 0.5, LAKE_SURFACE_Z + 0.02),
             (ge1, gn1 + 0.5, LAKE_SURFACE_Z + 0.02), (ge0, gn1 + 0.5, LAKE_SURFACE_Z + 0.02)],
            [0.0, 0.0, 0.0], 255201, mat_id=M_HARBOR_OBJ, is_shadow=True, shadow_mat_only=M_WATER_LAKE, shadow_mul=0.76,
        )
        # 2. 4 pairs of solid timber support pilings beneath gangway
        for pe_st in (2684040.5, 2684045.0, 2684049.5, 2684053.8):
            for pn_st in (1242066.0, 1242074.3):
                if _in_box_am(pe_st, pn_st, ins=0.5):
                    _draw_3d_box_column(
                        camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                        pe_st, pn_st, LAKE_SURFACE_Z - 0.15, 407.25, 0.18, (82.0, 66.0, 50.0), 255200, M_HARBOR_OBJ,
                    )
        # 3. Solid vertical timber side fascia beams
        for f_pts, f_col, f_n in (
            ([(ge0, gn0, gz_bot), (ge1, gn0, gz_bot), (ge1, gn0, gz_top), (ge0, gn0, gz_top)], [102.0, 86.0, 68.0], (0.0, -1.0, 0.0)),
            ([(ge1, gn0, gz_bot), (ge1, gn1, gz_bot), (ge1, gn1, gz_top), (ge1, gn0, gz_top)], [118.0, 100.0, 80.0], (1.0, 0.0, 0.0)),
            ([(ge0, gn1, gz_bot), (ge0, gn0, gz_bot), (ge0, gn0, gz_top), (ge0, gn1, gz_top)], [118.0, 100.0, 80.0], (-1.0, 0.0, 0.0)),
            ([(ge1, gn1, gz_bot), (ge0, gn1, gz_bot), (ge0, gn1, gz_top), (ge1, gn1, gz_top)], [102.0, 86.0, 68.0], (0.0, 1.0, 0.0)),
        ):
            _fill_3d_poly(
                camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                f_pts, f_col, 255201, mat_id=M_HARBOR_OBJ, norm=f_n,
            )
        # 4. Solid planked top timber deck (global LV95 plank seams, zero grid gaps!)
        _fill_3d_poly(
            camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
            [(ge0, gn0, gz_top), (ge1, gn0, gz_top), (ge1, gn1, gz_top), (ge0, gn1, gz_top)],
            [166.0, 146.0, 118.0], 255201, mat_id=M_HARBOR_OBJ, norm=(0.0, 0.0, 1.0),
            plank_e_step=0.65, plank_col=[138.0, 120.0, 96.0], plank_seam_w=0.09,
        )
        # 5. Crisp 1px galvanized safety railings on thin-pole oid=244957 (excluded from fat Stage 5 outlines!)
        for rn_r in (1242065.6, 1242074.7):
            _draw_harbor_seg(2684037.1, rn_r, 408.55, 2684055.0, rn_r, 408.55, [178.0, 184.0, 190.0], oid=244957)
            for re_p in np.linspace(2684037.5, 2684054.5, 6):
                _draw_harbor_seg(float(re_p), rn_r, 407.68, float(re_p), rn_r, 408.55, [142.0, 148.0, 156.0], oid=244957)
        # Warm corner pier lantern globe at SE corner
        if _in_box_am(2684068.8, 1242066.0):
            _draw_harbor_seg(2684068.8, 1242066.0, 407.8, 2684068.8, 1242066.0, 410.4, [72.0, 76.0, 84.0], oid=255202)
            px_l, py_l, pd_l = camera.project(np.array([2684068.8]), np.array([1242066.0]), np.array([410.45]))
            lx_p, ly_p = int(round(float(px_l[0] + shift_x))), int(round(float(py_l[0] + shift_y)))
            for ox_l, oy_l in ((0, 0), (1, 0), (0, -1), (1, -1)):
                tx_l, ty_l = lx_p + ox_l, ly_p + oy_l
                if 0 <= tx_l < W and 0 <= ty_l < H and (float(pd_l[0]) - 0.15) < zbuf[ty_l, tx_l]:
                    zbuf[ty_l, tx_l] = float(pd_l[0]) - 0.15
                    rgb_buf[ty_l, tx_l] = [255.0, 222.0, 138.0] if is_night else [234.0, 236.0, 232.0]
                    mat_buf[ty_l, tx_l] = M_WINDOW_LIT if is_night else M_HARBOR_OBJ
                    obj_buf[ty_l, tx_l] = 255202
        # v11: ZVV info pylon, timetable board, lifebuoy, bench & hinged gangplank (roof-clipping stripe & buried pillars removed)
        if _in_box_am(2684054.5, 1242073.5, ins=2.0):
            _draw_harbor_seg(2684054.5, 1242073.5, 407.7, 2684054.5, 1242073.5, 409.9, [22.0, 72.0, 154.0], oid=244955, thick=True)
            _draw_harbor_seg(2684054.5, 1242073.5, 409.45, 2684054.5, 1242073.5, 409.85, [244.0, 246.0, 248.0], mat_c=M_WINDOW_LIT if is_night else M_HARBOR_OBJ, oid=244955, thick=True)
        if _in_box_am(2684056.2, 1242071.0, ins=2.0):
            _draw_harbor_seg(2684056.2, 1242071.0, 407.7, 2684056.2, 1242071.0, 409.5, [24.0, 56.0, 124.0], oid=255204, thick=True)
            _draw_harbor_seg(2684056.3, 1242071.0, 408.35, 2684056.3, 1242071.0, 409.15, [244.0, 246.0, 248.0], mat_c=M_WINDOW_LIT if is_night else M_HARBOR_OBJ, oid=255204)
        if _in_box_am(2684052.5, 1242065.5, ins=2.0):
            px_b, py_b, pd_b = camera.project(np.array([2684052.5]), np.array([1242065.5]), np.array([408.25]))
            bx_p, by_p = int(round(float(px_b[0] + shift_x))), int(round(float(py_b[0] + shift_y)))
            db = float(pd_b[0]) - 0.15
            for ox_b, oy_b, cb_rgb in (
                (-1, 0, [234.0, 94.0, 34.0]), (1, 0, [234.0, 94.0, 34.0]),
                (0, -1, [244.0, 244.0, 240.0]), (0, 1, [244.0, 244.0, 240.0]),
            ):
                tx_b, ty_b = bx_p + ox_b, by_p + oy_b
                if 0 <= tx_b < W and 0 <= ty_b < H and db < zbuf[ty_b, tx_b]:
                    zbuf[ty_b, tx_b] = db
                    rgb_buf[ty_b, tx_b] = cb_rgb
                    mat_buf[ty_b, tx_b] = M_HARBOR_OBJ
                    obj_buf[ty_b, tx_b] = 255205
        if _in_box_am(2684059.0, 1242075.5, ins=2.0):
            _draw_harbor_seg(2684059.0, 1242073.5, 408.20, 2684059.0, 1242077.5, 408.20, [166.0, 118.0, 72.0], oid=255206, thick=True)
        if _in_box_am(2684069.8, 1242074.4, ins=2.0):
            _draw_harbor_seg(2684068.5, 1242074.4, 407.85, 2684071.2, 1242074.4, 407.25, [168.0, 174.0, 182.0], oid=255207, thick=True)
            _draw_harbor_seg(2684068.5, 1242073.9, 408.45, 2684071.2, 1242073.9, 407.85, [196.0, 202.0, 210.0], oid=255207)
            _draw_harbor_seg(2684068.5, 1242074.9, 408.45, 2684071.2, 1242074.9, 407.85, [196.0, 202.0, 210.0], oid=255207)

    # Bendlikon Pavilion (real ZSG Schiffstation Kilchberg-Bendlikon, Seestrasse 157.1):
    # harbor stone steps, twin bright-blue ZSG timetable boards, silver station sign post, railings & east boarding ramps
    if _in_box_am(2684152.0, 1241898.0, ins=2.0):
        for sk_p in range(3):
            _draw_harbor_seg(2684150.5 + sk_p * 0.55, 1241896.5, 407.1 - sk_p * 0.35, 2684150.5 + sk_p * 0.55, 1241899.5, 407.1 - sk_p * 0.35, [192.0, 186.0, 174.0], oid=255210, thick=True)
        # Silver tubular ZSG station sign post with blue header + white destination strips
        _draw_harbor_seg(2684151.8, 1241897.8, 406.9, 2684151.8, 1241897.8, 409.5, [204.0, 210.0, 216.0], oid=244955)
        _draw_harbor_seg(2684151.8, 1241897.6, 409.05, 2684151.8, 1241898.0, 409.45, [22.0, 84.0, 160.0], mat_c=M_WINDOW_LIT if is_night else M_HARBOR_OBJ, oid=244955, thick=True)
        _draw_harbor_seg(2684151.8, 1241897.6, 408.35, 2684151.8, 1241898.0, 408.95, [242.0, 244.0, 246.0], mat_c=M_WINDOW_LIT if is_night else M_HARBOR_OBJ, oid=244955, thick=True)
        # Two bright ZSG-blue freestanding timetable/info boards in front of pavilion
        for tbe, tbn in ((2684153.0, 1241898.3), (2684154.6, 1241898.8)):
            _draw_harbor_seg(tbe, tbn, 406.9, tbe, tbn, 408.65, [196.0, 202.0, 208.0], oid=255211)
            _draw_harbor_seg(tbe - 0.5, tbn, 407.45, tbe + 0.5, tbn, 408.55, [26.0, 112.0, 198.0], mat_c=M_WINDOW_LIT if is_night else M_HARBOR_OBJ, oid=255211, thick=True)
        # Galvanized silver tubular railings along concrete ZSG pier edges
        _draw_harbor_seg(2684150.0, 1241894.0, 407.95, 2684172.0, 1241901.5, 407.95, [186.0, 192.0, 198.0], oid=255212)
        _draw_harbor_seg(2684152.0, 1241902.5, 407.95, 2684173.5, 1241910.0, 407.95, [186.0, 192.0, 198.0], oid=255212)
        # Twin hinged boarding ramps at east concrete pier tip
        for rpe, rpn in ((2684172.5, 1241904.5), (2684174.0, 1241909.5)):
            _draw_harbor_seg(rpe, rpn, 407.6, rpe + 2.4, rpn + 0.8, 407.0, [168.0, 174.0, 182.0], oid=255213, thick=True)

    # Seebad Kilchberg 3 Wooden Jetties: stainless swim ladders + south diving board + v9.0 Floss swim raft & buoy line!
    seebad_jetties = (
        (2684329.5, 1241522.0, 406.70),  # North jetty tip
        (2684344.2, 1241499.0, 406.80),  # Center jetty tip
        (2684330.2, 1241470.0, 406.95),  # South swim jetty tip
    )
    for ji_s, (je_t, jn_t, jz_t) in enumerate(seebad_jetties):
        if not _in_box_am(je_t, jn_t):
            continue
        oid_j = 255300 + ji_s
        for dn_l in (-0.28, 0.28):
            _draw_harbor_seg(je_t, jn_t + dn_l, LAKE_SURFACE_Z - 0.10, je_t, jn_t + dn_l, jz_t + 0.85, [206.0, 212.0, 220.0], oid=oid_j)
        _draw_harbor_seg(je_t, jn_t - 0.28, jz_t + 0.32, je_t, jn_t + 0.28, jz_t + 0.32, [206.0, 212.0, 220.0], oid=oid_j)
        _draw_harbor_seg(je_t, jn_t - 0.28, jz_t + 0.72, je_t, jn_t + 0.28, jz_t + 0.72, [206.0, 212.0, 220.0], oid=oid_j)
        if ji_s == 2 and _in_box_am(je_t, jn_t - 1.2, ins=2.0):
            # M3.5 3D 3m Sprungturm diving tower (1m & 3m platforms, ladder, white tubular railings, oid=244956 excluded from occ_m!)
            for dn_sp in (-0.42, 0.42):
                _draw_harbor_seg(je_t - 0.5, jn_t - 1.2 + dn_sp, jz_t, je_t - 0.5, jn_t - 1.2 + dn_sp, jz_t + 3.15, [236.0, 240.0, 244.0], oid=244956)
                _draw_harbor_seg(je_t - 0.5, jn_t - 1.2 + dn_sp, jz_t + 2.95, je_t + 0.5, jn_t - 1.2 + dn_sp, jz_t + 3.85, [236.0, 240.0, 244.0], oid=244956)
            for rung_k in range(1, 7):
                zr_sp = jz_t + rung_k * 0.45
                _draw_harbor_seg(je_t - 0.5, jn_t - 1.62, zr_sp, je_t - 0.5, jn_t - 0.78, zr_sp, [224.0, 228.0, 234.0], oid=244956)
            _draw_harbor_seg(je_t - 0.5, jn_t - 1.2, jz_t + 1.05, je_t + 1.0, jn_t - 1.2, jz_t + 1.10, [244.0, 242.0, 236.0], oid=244956, thick=True)
            _draw_harbor_seg(je_t - 0.5, jn_t - 1.2, jz_t + 2.95, je_t + 1.3, jn_t - 1.2, jz_t + 3.02, [244.0, 242.0, 236.0], oid=244956, thick=True)

    # Floating wooden swim raft (Floss) offshore at Seebad — solid 3D polygon deck box (zero 15x15 point-splat gaps!)
    fl_e, fl_n = 2684356.0, 1241484.0
    if _in_box_am(fl_e, fl_n, ins=2.5):
        rr_f = int(np.clip((N_MAX - fl_n) / GRID_RES, 0, GRID_H - 1))
        cc_f = int(np.clip((fl_e - E_MIN) / GRID_RES, 0, GRID_W - 1))
        if scene.lake_mask[rr_f, cc_f]:
            fe0, fe1 = fl_e - 1.7, fl_e + 1.7
            fn0, fn1 = fl_n - 1.7, fl_n + 1.7
            fz0, fz1 = LAKE_SURFACE_Z + 0.02, LAKE_SURFACE_Z + 0.30
            _fill_3d_poly(
                camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                [(fe0 - 0.3, fn0 - 0.3, LAKE_SURFACE_Z + 0.01), (fe1 + 0.3, fn0 - 0.3, LAKE_SURFACE_Z + 0.01),
                 (fe1 + 0.3, fn1 + 0.3, LAKE_SURFACE_Z + 0.01), (fe0 - 0.3, fn1 + 0.3, LAKE_SURFACE_Z + 0.01)],
                [0.0, 0.0, 0.0], 255310, mat_id=M_HARBOR_OBJ, is_shadow=True, shadow_mat_only=M_WATER_LAKE, shadow_mul=0.76,
            )
            for f_pts, f_n in (
                ([(fe0, fn0, fz0), (fe1, fn0, fz0), (fe1, fn0, fz1), (fe0, fn0, fz1)], (0.0, -1.0, 0.0)),
                ([(fe1, fn0, fz0), (fe1, fn1, fz0), (fe1, fn1, fz1), (fe1, fn0, fz1)], (1.0, 0.0, 0.0)),
                ([(fe0, fn1, fz0), (fe0, fn0, fz0), (fe0, fn0, fz1), (fe0, fn1, fz1)], (-1.0, 0.0, 0.0)),
                ([(fe1, fn1, fz0), (fe0, fn1, fz0), (fe0, fn1, fz1), (fe1, fn1, fz1)], (0.0, 1.0, 0.0)),
            ):
                _fill_3d_poly(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    f_pts, [124.0, 96.0, 64.0], 255310, mat_id=M_HARBOR_OBJ, norm=f_n,
                )
            _fill_3d_poly(
                camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                [(fe0, fn0, fz1), (fe1, fn0, fz1), (fe1, fn1, fz1), (fe0, fn1, fz1)],
                [184.0, 148.0, 102.0], 255310, mat_id=M_HARBOR_OBJ, norm=(0.0, 0.0, 1.0),
                plank_e_step=0.55, plank_col=[144.0, 112.0, 74.0], plank_seam_w=0.09,
            )
            _draw_harbor_seg(fl_e - 1.7, fl_n - 0.3, LAKE_SURFACE_Z, fl_e - 1.7, fl_n - 0.3, LAKE_SURFACE_Z + 0.95, [206.0, 212.0, 220.0], oid=244958)
            _draw_harbor_seg(fl_e - 1.7, fl_n + 0.3, LAKE_SURFACE_Z, fl_e - 1.7, fl_n + 0.3, LAKE_SURFACE_Z + 0.95, [206.0, 212.0, 220.0], oid=244958)

    # Red-white swim-zone buoy line offshore at Seebad
    buoy_pts = (
        (2684338.0, 1241526.0), (2684350.0, 1241516.0), (2684360.0, 1241504.0),
        (2684364.0, 1241492.0), (2684360.0, 1241478.0), (2684352.0, 1241465.0),
        (2684340.0, 1241454.0),
    )
    for bi_y, (bye, byn) in enumerate(buoy_pts):
        if not _in_box_am(bye, byn, ins=2.0):
            continue
        rr_y = int(np.clip((N_MAX - byn) / GRID_RES, 0, GRID_H - 1))
        cc_y = int(np.clip((bye - E_MIN) / GRID_RES, 0, GRID_W - 1))
        if scene.lake_mask[rr_y, cc_y]:
            bcol_y = [226.0, 48.0, 48.0] if (bi_y % 2 == 0) else [242.0, 242.0, 238.0]
            _draw_harbor_seg(bye, byn, LAKE_SURFACE_Z + 0.05, bye, byn, LAKE_SURFACE_Z + 0.25, bcol_y, oid=255311, thick=True)

    # Mönchhof & Horn, Sulzergut & Morfanlage lakeside slipways, balustrade, bathing steps & lantern bollards
    # Mönchhof slipways & seawall steps
    if _in_box_am(2683597.0, 1243018.0, ins=2.0):
        for dn_s in (-0.8, 0.8):
            _draw_harbor_seg(2683593.0, 1243016.0 + dn_s, 406.5, 2683601.0, 1243020.0 + dn_s, LAKE_SURFACE_Z - 0.1, [122.0, 92.0, 62.0], oid=255406, thick=True)
    if _in_box_am(2683584.0, 1242994.0, ins=2.0):
        for sk_m in range(3):
            _draw_harbor_seg(2683583.0 + sk_m * 0.5, 1242992.5, 407.1 - sk_m * 0.35, 2683583.0 + sk_m * 0.5, 1242995.5, 407.1 - sk_m * 0.35, [190.0, 184.0, 172.0], oid=255407, thick=True)
    for lb_i, (lbe, lbn) in enumerate(((2683578.0, 1242992.0), (2683586.0, 1243004.0), (2683598.0, 1243024.0), (2683570.0, 1243028.0), (2683556.0, 1243046.0), (2683542.0, 1243064.0))):
        if _in_box_am(lbe, lbn, ins=2.0):
            rr_lb = int(np.clip((N_MAX - lbn) / GRID_RES, 0, GRID_H - 1))
            cc_lb = int(np.clip((lbe - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if (not scene.lake_mask[rr_lb, cc_lb]) and (not scene.bldg_roof_mask[rr_lb, cc_lb]):
                zlb = float(scene.dem[rr_lb, cc_lb])
                _draw_harbor_seg(lbe, lbn, zlb, lbe, lbn, zlb + 0.95, [52.0, 56.0, 62.0], oid=244920 + lb_i)
                _draw_harbor_seg(lbe, lbn, zlb + 0.95, lbe, lbn, zlb + 1.18, [255.0, 224.0, 142.0] if is_night else [232.0, 234.0, 228.0], mat_c=M_WINDOW_LIT if is_night else M_HARBOR_OBJ, oid=244920 + lb_i, thick=True)
    # v11 Mönchhof am See lakeside beer-garden natural straw/thatch parasols (SE of boat_825) & mooring bollards
    if not is_night:
        for pe_m, pn_m in ((2683599.5, 1243006.0), (2683601.5, 1243002.0), (2683603.5, 1242998.0), (2683605.0, 1242994.0)):
            if _in_box_am(pe_m, pn_m, ins=2.0):
                rr_pm = int(np.clip((N_MAX - pn_m) / GRID_RES, 0, GRID_H - 1))
                cc_pm = int(np.clip((pe_m - E_MIN) / GRID_RES, 0, GRID_W - 1))
                if (not scene.lake_mask[rr_pm, cc_pm]) and (not scene.bldg_roof_mask[rr_pm, cc_pm]):
                    zpm = float(scene.dem[rr_pm, cc_pm])
                    _draw_harbor_seg(pe_m, pn_m, zpm, pe_m, pn_m, zpm + 2.1, [112.0, 82.0, 56.0], oid=244926)
                    _draw_harbor_seg(pe_m - 1.2, pn_m, zpm + 2.15, pe_m + 1.2, pn_m, zpm + 2.15, [198.0, 174.0, 124.0], oid=255408, thick=True)
                    _draw_harbor_seg(pe_m, pn_m - 1.2, zpm + 2.15, pe_m, pn_m + 1.2, zpm + 2.15, [198.0, 174.0, 124.0], oid=255408, thick=True)
    for mbe, mbn in ((2683586.0, 1242996.0), (2683589.5, 1243001.5), (2683593.0, 1243007.0), (2683596.5, 1243012.5)):
        if _in_box_am(mbe, mbn, ins=2.0):
            rr_mb = int(np.clip((N_MAX - mbn) / GRID_RES, 0, GRID_H - 1))
            cc_mb = int(np.clip((mbe - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if not scene.bldg_roof_mask[rr_mb, cc_mb]:
                zmb = max(LAKE_SURFACE_Z + 0.35, float(scene.dem[rr_mb, cc_mb]))
                _draw_harbor_seg(mbe, mbn, zmb, mbe, mbn, zmb + 0.65, [56.0, 60.0, 66.0], oid=244927, thick=True)

    # v11 Sulzergut Park: northern curved stone lakeside seawall, kleine Steintreppe bathing steps, park benches & 2 subtle path lamps
    for (we0, wn0, we1, wn1) in (
        (2684468.5, 1241199.0, 2684474.5, 1241190.0),
        (2684474.5, 1241190.0, 2684478.0, 1241182.5),
    ):
        if _in_box_am(0.5 * (we0 + we1), 0.5 * (wn0 + wn1), ins=2.0):
            _draw_harbor_seg(we0, wn0, 407.15, we1, wn1, 407.15, [174.0, 170.0, 162.0], oid=255424, thick=True)
            _draw_harbor_seg(we0, wn0, 406.75, we1, wn1, 406.75, [138.0, 134.0, 126.0], oid=255424)
    if _in_box_am(2684479.5, 1241180.0, ins=2.0):
        for st_sz in range(3):
            z_st_sz = 407.05 - st_sz * 0.36
            _draw_harbor_seg(
                2684478.6 + st_sz * 0.55, 1241178.7, z_st_sz,
                2684478.6 + st_sz * 0.55, 1241181.3, z_st_sz,
                [202.0, 196.0, 184.0], oid=255425, thick=True,
            )
    for bze, bzn in ((2684474.5, 1241172.0), (2684488.5, 1241143.5), (2684447.0, 1241184.5)):
        if _in_box_am(bze, bzn, ins=2.0):
            rr_bz = int(np.clip((N_MAX - bzn) / GRID_RES, 0, GRID_H - 1))
            cc_bz = int(np.clip((bze - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if (not scene.lake_mask[rr_bz, cc_bz]) and (not scene.bldg_roof_mask[rr_bz, cc_bz]):
                zbz = float(scene.dem[rr_bz, cc_bz])
                _draw_harbor_seg(bze - 0.85, bzn - 0.3, zbz + 0.48, bze + 0.85, bzn + 0.3, zbz + 0.48, [144.0, 106.0, 68.0], oid=255426, thick=True)
    for ml_i, (mle, mln) in enumerate(((2684448.0, 1241152.0), (2684473.0, 1241173.0))):
        if _in_box_am(mle, mln, ins=2.0):
            rr_ml = int(np.clip((N_MAX - mln) / GRID_RES, 0, GRID_H - 1))
            cc_ml = int(np.clip((mle - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if (not scene.lake_mask[rr_ml, cc_ml]) and (not scene.bldg_roof_mask[rr_ml, cc_ml]):
                zml = float(scene.dem[rr_ml, cc_ml])
                _draw_harbor_seg(mle, mln, zml, mle, mln, zml + 1.15, [54.0, 58.0, 64.0], oid=244930 + ml_i)
                _draw_harbor_seg(mle, mln, zml + 1.15, mle, mln, zml + 1.38, [255.0, 224.0, 142.0] if is_night else [232.0, 234.0, 228.0], mat_c=M_WINDOW_LIT if is_night else M_HARBOR_OBJ, oid=244930 + ml_i, thick=True)

    # v11 Morfanlage boathouse slipway, weathered stone quay coping, 5 OSM benches & relocated bathing ladders
    if _in_box_am(2683877.0, 1242414.0, ins=2.0):
        _draw_harbor_seg(2683872.0, 1242411.4, 406.5, 2683882.0, 1242415.4, LAKE_SURFACE_Z - 0.1, [120.0, 90.0, 60.0], oid=255440, thick=True)
        _draw_harbor_seg(2683872.0, 1242412.6, 406.5, 2683882.0, 1242416.6, LAKE_SURFACE_Z - 0.1, [120.0, 90.0, 60.0], oid=255440, thick=True)
    if _in_box_am(2683892.0, 1242396.0, ins=2.0) and _in_box_am(2683912.0, 1242336.0, ins=2.0):
        _draw_harbor_seg(2683892.0, 1242396.0, 407.25, 2683912.0, 1242336.0, 407.25, [158.0, 154.0, 144.0], oid=255444, thick=True)
        _draw_harbor_seg(2683892.0, 1242396.0, 406.85, 2683912.0, 1242336.0, 406.85, [124.0, 120.0, 112.0], oid=255444)
    for mfe, mfn in (
        (2683893.8, 1242388.1),  # NE shore
        (2683898.7, 1242366.5),  # E shore
        (2683905.0, 1242350.4),  # SE shore
        (2683888.8, 1242396.7),  # N loop
        (2683876.4, 1242380.4),  # NW loop
    ):
        if _in_box_am(mfe, mfn, ins=2.0):
            rr_mf = int(np.clip((N_MAX - mfn) / GRID_RES, 0, GRID_H - 1))
            cc_mf = int(np.clip((mfe - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if (not scene.lake_mask[rr_mf, cc_mf]) and (not scene.bldg_roof_mask[rr_mf, cc_mf]):
                zmf = float(scene.dem[rr_mf, cc_mf])
                _draw_harbor_seg(mfe - 0.8, mfn - 0.35, zmf + 0.48, mfe + 0.8, mfn + 0.35, zmf + 0.48, [138.0, 104.0, 72.0], oid=255445, thick=True)
                _draw_harbor_seg(mfe - 0.8, mfn - 0.35, zmf + 0.82, mfe + 0.8, mfn + 0.35, zmf + 0.82, [92.0, 74.0, 56.0], oid=255445)
    for bs_i, (bse, bsn) in enumerate(((2683904.5, 1242362.0), (2683899.5, 1242384.0))):
        if _in_box_am(bse, bsn, ins=2.0):
            for dn_b in (-0.32, 0.32):
                _draw_harbor_seg(bse, bsn + dn_b, LAKE_SURFACE_Z - 0.1, bse, bsn + dn_b, 407.6, [184.0, 190.0, 196.0], oid=255441 + bs_i)
            _draw_harbor_seg(bse, bsn - 0.32, 406.8, bse, bsn + 0.32, 406.8, [142.0, 108.0, 76.0], oid=255441 + bs_i, thick=True)
            _draw_harbor_seg(bse, bsn - 0.32, 407.2, bse, bsn + 0.32, 407.2, [142.0, 108.0, 76.0], oid=255441 + bs_i, thick=True)

    # -------------------------------------------------------------------------
    # Part B (v13 M1B): Point-splatted baked moored boats removed cleanly —
    # live docs/js/living/plugins/vessels.js renders crisp moored sailboats with
    # wind-synced pennants & night anchor lights over spotless Lake Zurich water!
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Part C: F13 Seebad Kilchberg Beach Umbrellas & Striped Towels (Day & Sunset ONLY!)
    # -------------------------------------------------------------------------
    if not is_night:
        sb_in_crop = True
        if crop_box_lv95 is not None:
            if crop_box_lv95[2] < 2684274.0 or crop_box_lv95[0] > 2684322.0 or crop_box_lv95[3] < 1241400.0 or crop_box_lv95[1] > 1241488.0:
                sb_in_crop = False
        if sb_in_crop:
            umb_spots = (
                (2684284.0, 1241468.0, 0), (2684292.0, 1241462.0, 1), (2684301.0, 1241455.0, 2),
                (2684287.0, 1241451.0, 3), (2684297.0, 1241443.0, 0), (2684307.0, 1241447.0, 1),
                (2684289.0, 1241432.0, 2), (2684299.0, 1241425.0, 3), (2684310.0, 1241434.0, 0),
                (2684294.0, 1241416.0, 1), (2684304.0, 1241412.0, 2), (2684285.0, 1241418.0, 3),
                (2684306.0, 1241464.0, 0), (2684295.0, 1241474.0, 1),
            )
            umb_cols = (
                [214.0, 52.0, 52.0],   # Swiss red
                [56.0, 146.0, 208.0],  # Sky blue
                [238.0, 198.0, 62.0],  # Sunshine yellow
                [66.0, 174.0, 148.0],  # Mint teal
            )
            for ui_s, (ue_s, un_s, uc_i) in enumerate(umb_spots):
                if not _in_box_am(ue_s, un_s, ins=2.0):
                    continue
                rr_u = int(np.clip((N_MAX - un_s) / GRID_RES, 0, GRID_H - 1))
                cc_u = int(np.clip((ue_s - E_MIN) / GRID_RES, 0, GRID_W - 1))
                if scene.sem[rr_u, cc_u] != G_TERRAIN or scene.lake_mask[rr_u, cc_u] or scene.bldg_roof_mask[rr_u, cc_u]:
                    continue
                uz = float(scene.dem[rr_u, cc_u])
                oid_u = 256000 + ui_s
                # Striped beach towel laid flat beside umbrella
                _draw_harbor_seg(ue_s + 0.9, un_s - 0.6, uz + 0.08, ue_s + 2.2, un_s - 0.2, uz + 0.08, umb_cols[(uc_i + 1) % 4], oid=oid_u, thick=True)
                _draw_harbor_seg(ue_s + 1.3, un_s - 0.5, uz + 0.10, ue_s + 1.8, un_s - 0.3, uz + 0.10, [242.0, 242.0, 236.0], oid=oid_u)
                # Umbrella pole + 2-3px colorful dome canopy
                _draw_harbor_seg(ue_s, un_s, uz, ue_s, un_s, uz + 1.8, [72.0, 76.0, 82.0], oid=oid_u)
                px_u, py_u, pd_u = camera.project(np.array([ue_s]), np.array([un_s]), np.array([uz + 1.85]))
                ux_p, uy_p = int(round(float(px_u[0] + shift_x))), int(round(float(py_u[0] + shift_y)))
                du = float(pd_u[0]) - 0.10
                for dy_u in (-1, 0, 1):
                    for dx_u in (-2, -1, 0, 1, 2):
                        if abs(dx_u) + abs(dy_u) * 2 > 2:
                            continue
                        tx_u, ty_u = ux_p + dx_u, uy_p + dy_u
                        if 0 <= tx_u < W and 0 <= ty_u < H and du < zbuf[ty_u, tx_u]:
                            zbuf[ty_u, tx_u] = du
                            rgb_buf[ty_u, tx_u] = [244.0, 242.0, 236.0] if ((dx_u + dy_u) & 1) else umb_cols[uc_i]
                            mat_buf[ty_u, tx_u] = M_HARBOR_OBJ
                            obj_buf[ty_u, tx_u] = oid_u
                            norm_buf[ty_u, tx_u] = [0.15, -0.15, 0.97]
                            shadow_buf[ty_u, tx_u] = False

            # v9.0 Seebad wooden sun-loungers & outdoor shower/lifeguard post
            for lg_i, (lge, lgn) in enumerate(((2684304.0, 1241484.0), (2684308.0, 1241481.0), (2684312.0, 1241489.0), (2684306.0, 1241493.0), (2684314.0, 1241480.0))):
                if not _in_box_am(lge, lgn, ins=2.0):
                    continue
                rr_lg = int(np.clip((N_MAX - lgn) / GRID_RES, 0, GRID_H - 1))
                cc_lg = int(np.clip((lge - E_MIN) / GRID_RES, 0, GRID_W - 1))
                if scene.lake_mask[rr_lg, cc_lg] or scene.bldg_roof_mask[rr_lg, cc_lg]:
                    continue
                zlg = float(scene.dem[rr_lg, cc_lg])
                _draw_harbor_seg(lge - 0.85, lgn - 0.25, zlg + 0.30, lge + 0.85, lgn + 0.25, zlg + 0.30, [176.0, 132.0, 82.0], oid=255312 + lg_i, thick=True)
                _draw_harbor_seg(lge - 0.85, lgn - 0.25, zlg + 0.45, lge - 0.45, lgn - 0.12, zlg + 0.62, [242.0, 242.0, 238.0], oid=255312 + lg_i)
            if _in_box_am(2684318.0, 1241488.0, ins=2.0):
                rr_sh = int(np.clip((N_MAX - 1241488.0) / GRID_RES, 0, GRID_H - 1))
                cc_sh = int(np.clip((2684318.0 - E_MIN) / GRID_RES, 0, GRID_W - 1))
                if (not scene.lake_mask[rr_sh, cc_sh]) and (not scene.bldg_roof_mask[rr_sh, cc_sh]):
                    zsh = float(scene.dem[rr_sh, cc_sh])
                    _draw_harbor_seg(2684318.0, 1241488.0, zsh, 2684318.0, 1241488.0, zsh + 2.4, [206.0, 212.0, 220.0], oid=255320)
                    _draw_harbor_seg(2684318.0, 1241488.0, zsh + 1.9, 2684318.0, 1241488.0, zsh + 2.35, [224.0, 48.0, 48.0], oid=255320, thick=True)

            # v11 Seebad Kiosk white square parasols + Chez Fritz (1660) 1960s Riviera cream/forest-green terrace parasols
            for tp_i, (tpe, tpn, tp_a, tp_b) in enumerate((
                (2684274.0, 1241446.0, [242.0, 242.0, 238.0], [234.0, 234.0, 230.0]),
                (2684279.0, 1241450.0, [242.0, 242.0, 238.0], [234.0, 234.0, 230.0]),
                (2684266.0, 1241536.0, [242.0, 238.0, 228.0], [58.0, 90.0, 68.0]),
                (2684270.0, 1241539.0, [242.0, 238.0, 228.0], [58.0, 90.0, 68.0]),
                (2684263.0, 1241541.0, [242.0, 238.0, 228.0], [58.0, 90.0, 68.0]),
            )):
                if not _in_box_am(tpe, tpn, ins=2.0):
                    continue
                rr_tp = int(np.clip((N_MAX - tpn) / GRID_RES, 0, GRID_H - 1))
                cc_tp = int(np.clip((tpe - E_MIN) / GRID_RES, 0, GRID_W - 1))
                if scene.lake_mask[rr_tp, cc_tp] or scene.bldg_roof_mask[rr_tp, cc_tp]:
                    continue
                ztp = float(scene.dem[rr_tp, cc_tp])
                _draw_harbor_seg(tpe, tpn, ztp, tpe, tpn, ztp + 2.0, [74.0, 76.0, 80.0], oid=255325 + tp_i)
                px_t, py_t, pd_t = camera.project(np.array([tpe]), np.array([tpn]), np.array([ztp + 2.05]))
                tx_0, ty_0, dt_0 = int(round(float(px_t[0] + shift_x))), int(round(float(py_t[0] + shift_y))), float(pd_t[0]) - 0.12
                for dy_t in (-1, 0, 1):
                    for dx_t in (-2, -1, 0, 1, 2):
                        if abs(dx_t) + abs(dy_t) * 2 <= 2:
                            tx_p, ty_p = tx_0 + dx_t, ty_0 + dy_t
                            if 0 <= tx_p < W and 0 <= ty_p < H and dt_0 < zbuf[ty_p, tx_p]:
                                zbuf[ty_p, tx_p] = dt_0
                                rgb_buf[ty_p, tx_p] = tp_a if ((dx_t + dy_t) & 1) else tp_b
                                mat_buf[ty_p, tx_p] = M_HARBOR_OBJ
                                obj_buf[ty_p, tx_p] = 255325 + tp_i

        # v11 Mönchhof am See lakeside terrace mint-green café tables (SE of boat_825, off Seestrasse asphalt!)
        for mp_i, (mpe, mpn) in enumerate((
            (2683598.0, 1243003.5),
            (2683600.0, 1242999.5),
            (2683602.0, 1242995.5),
            (2683596.5, 1243008.0),
        )):
            if not _in_box_am(mpe, mpn, ins=2.0):
                continue
            rr_mp = int(np.clip((N_MAX - mpn) / GRID_RES, 0, GRID_H - 1))
            cc_mp = int(np.clip((mpe - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if scene.lake_mask[rr_mp, cc_mp] or scene.bldg_roof_mask[rr_mp, cc_mp]:
                continue
            zmp = float(scene.dem[rr_mp, cc_mp])
            _draw_harbor_seg(mpe - 0.45, mpn, zmp + 0.72, mpe + 0.45, mpn, zmp + 0.72, [158.0, 196.0, 190.0], oid=255400 + mp_i, thick=True)


def _render_sculpted_pixel_art_trees_and_hedges(
    scene: SceneData,
    camera: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W: int,
    H: int,
    r0: int,
    r1: int,
    c0: int,
    c1: int,
    sub_mask: np.ndarray,
    sub_dem: np.ndarray,
    sub_chm: np.ndarray,
    sub_shadow: np.ndarray,
    zbuf: np.ndarray,
    rgb_buf: np.ndarray,
    mat_buf: np.ndarray,
    obj_buf: np.ndarray,
    norm_buf: np.ndarray,
    shadow_buf: np.ndarray,
    sun_vec: np.ndarray,
    crop_box_lv95: tuple[float, float, float, float] | None,
    is_night: bool = False,
) -> None:
    """STAGE 4 (v7.0 F14a): Painterly 90s pixel-art 3D trees with 3 distinct deciduous silhouettes
    (Wide-Spreading Swiss Oak, Airy Multi-Cluster Birch/Linden, Cascading Weeping Lakeside Willow),
    tiered Alpine Spruce, Mediterranean Cemetery Cypresses, sunlit top-left rim highlights,
    cool-teal shaded undersides, and beveled garden boxwood hedges!"""
    # -------------------------------------------------------------------------
    # 4A. v13.0 Varied Botanical Bushes & Hedges:
    #     (a) Clipped Swiss Boxwood / Yew Garden Hedges (crisp bevelled trapezoid + subtle leaf-notch edge)
    #     (b) Flowering Garden Shrubs (Hydrangea / Rose / Rhododendron 2x2-3x3 cel clusters on leafy mound)
    #     (c) Woodland Bramble / Understory Thickets (irregular mossy/fern profile near G_FOREST)
    #     (d) Strictly Land-Side Lakeside Reeds / Sedge Tufts (0.6..2.8m from shore, spotless water!)
    # -------------------------------------------------------------------------
    sub_hedge = sub_mask & scene.hedge_mask[r0:r1, c0:c1]
    if sub_hedge.any():
        # Seam-invariant 8m forest proximity mask using 16-cell padded slice
        fp_r0 = max(0, r0 - 16)
        fp_r1 = min(GRID_H, r1 + 16)
        fp_c0 = max(0, c0 - 16)
        fp_c1 = min(GRID_W, c1 + 16)
        sub_for_pad = scene.sem[fp_r0:fp_r1, fp_c0:fp_c1] == G_FOREST
        if sub_for_pad.any():
            near_forest_sub = ndimage.binary_dilation(sub_for_pad, iterations=14)[
                (r0 - fp_r0) : (r1 - fp_r0), (c0 - fp_c0) : (c1 - fp_c0)
            ]
        else:
            near_forest_sub = np.zeros((r1 - r0, c1 - c0), dtype=np.bool_)

        hr0, hc0 = np.nonzero(sub_hedge)
        he0 = E_MIN + (hc0 + c0 + 0.5) * GRID_RES
        hn0 = N_MAX - (hr0 + r0 + 0.5) * GRID_RES
        if camera.mpp <= 0.16:
            hr = np.tile(hr0, 4)
            hc = np.tile(hc0, 4)
            he = np.concatenate([he0 - 0.125, he0 + 0.125, he0 - 0.125, he0 + 0.125])
            hn = np.concatenate([hn0 + 0.125, hn0 + 0.125, hn0 - 0.125, hn0 - 0.125])
            edt_h = _sample_bilinear_05m(scene.hedge_edt_05m[r0:r1, c0:c1], he, hn, r0=r0, c0=c0)
            mn_h = _sample_bilinear_05m(scene.meadow_noise_05m[r0:r1, c0:c1], he, hn, r0=r0, c0=c0)
        else:
            hr, hc, he, hn = hr0, hc0, he0, hn0
            edt_h = scene.hedge_edt_05m[r0:r1, c0:c1][hr, hc].astype(np.float32)
            mn_h = scene.meadow_noise_05m[r0:r1, c0:c1][hr, hc].astype(np.float32)

        hz_base = sub_dem[hr, hc]
        h_sem = scene.sem[r0:r1, c0:c1][hr, hc]
        h_near_for = near_forest_sub[hr, hc] | (h_sem == G_FOREST)
        in_morf_h = (he >= 2683870.0) & (he <= 2683920.0) & (hn >= 1242334.0) & (hn <= 1242402.0)

        # Deterministic 4m world-grid hash so entire shrub clumps get coherent botanical type & flower color
        hx4 = np.floor(he / 4.0).astype(np.int64).astype(np.uint32)
        hy4 = np.floor(hn / 4.0).astype(np.int64).astype(np.uint32)
        h_clump = ((hx4 * np.uint32(73856093)) ^ (hy4 * np.uint32(19349663)) ^ np.uint32(0x4B1D)) & np.uint32(0xFF)

        # Type classification: (c) Woodland bramble, (b) Flowering garden shrub (~16%), (a) Clipped Swiss boxwood
        is_bramble = h_near_for
        is_flower_shrub = (~is_bramble) & (~in_morf_h) & ((h_clump % 6) == 0)
        is_boxwood = (~is_bramble) & (~is_flower_shrub)

        # v13 M1B Iter2: World-LV95 aperiodic 3-4 px leafy cluster field (organic foliage texture, 100% seam-safe!)
        b_tuft = (
            0.55 * np.sin(he * 11.4 + hn * 7.8)
            + 0.45 * np.cos(he * 7.2 - hn * 12.1)
        ).astype(np.float32)

        # Height profiles per botanical hedge type
        raw_chm_h = np.clip(sub_chm[hr, hc], 0.85, 1.90)
        # (a) Clipped Swiss boxwood: crisp architectural bevelled trapezoid + subtle 0.7m leaf-notch edge
        notch_box = 0.06 * np.sin(he * 8.2 + hn * 6.4) + 0.03 * b_tuft
        bevel_box = np.clip((edt_h + notch_box) / 0.35, 0.0, 1.0)
        hh_box = np.clip(raw_chm_h, 0.90, 1.75) * (0.42 + 0.58 * bevel_box)
        # (b) Flowering shrub: organic scalloped leafy mound
        edge_fl = np.clip(edt_h / 0.75, 0.0, 1.0)
        hh_fl = np.clip(raw_chm_h, 0.85, 1.65) * np.sqrt(0.32 + 0.68 * edge_fl) * (0.90 + 0.12 * np.sin(he * 2.6) * np.cos(hn * 2.6) + 0.06 * b_tuft)
        # (c) Woodland bramble: irregular undulating mossy thicket
        hh_bram = raw_chm_h * np.sqrt(0.28 + 0.72 * edge_fl) * (0.76 + 0.28 * np.sin(he * 1.45) * np.cos(hn * 1.45) + 0.08 * b_tuft)

        hh = np.where(is_bramble, hh_bram, np.where(is_flower_shrub, hh_fl, hh_box)).astype(np.float32)

        # Per-type cel-shaded palettes with organic 3-4 px leaf-tuft modulation
        tuft_mul = (1.0 + 0.11 * b_tuft)[:, None]
        # Default (a) Clipped Boxwood / Yew
        h_top_col = np.clip(
            np.where(
                (mn_h > 0.18)[:, None],
                [108.0, 170.0, 60.0],
                [84.0, 146.0, 52.0],
            ).astype(np.float32) * tuft_mul,
            18.0, 240.0,
        )
        h_mid_col = np.clip(np.full((len(hr), 3), [52.0, 114.0, 44.0], dtype=np.float32) * (1.0 + 0.08 * b_tuft)[:, None], 14.0, 220.0)
        h_base_col = np.full((len(hr), 3), [26.0, 68.0, 34.0], dtype=np.float32)

        # (c) Woodland bramble / fern understory
        if is_bramble.any():
            fern_hi = (np.sin(he[is_bramble] * 1.8 - hn[is_bramble] * 1.5) > 0.22)
            h_top_col[is_bramble] = np.clip(
                np.where(
                    fern_hi[:, None], [108.0, 148.0, 50.0], [72.0, 126.0, 46.0]
                ).astype(np.float32) * tuft_mul[is_bramble],
                16.0, 230.0,
            )
            h_mid_col[is_bramble] = np.clip(
                np.array([40.0, 90.0, 38.0], dtype=np.float32) * (1.0 + 0.08 * b_tuft[is_bramble])[:, None],
                12.0, 210.0,
            )
            h_base_col[is_bramble] = [20.0, 56.0, 30.0]

        # (b) Flowering garden shrubs: dark-emerald leafy mound + harmonious multi-tone organic flower bouquets (NO polka-dots!)
        if is_flower_shrub.any():
            h_top_col[is_flower_shrub] = np.clip(
                np.array([62.0, 128.0, 48.0], dtype=np.float32) * tuft_mul[is_flower_shrub], 16.0, 235.0
            )
            h_mid_col[is_flower_shrub] = np.clip(
                np.array([40.0, 96.0, 42.0], dtype=np.float32) * (1.0 + 0.08 * b_tuft[is_flower_shrub])[:, None], 14.0, 210.0
            )
            h_base_col[is_flower_shrub] = [22.0, 62.0, 32.0]

            fe_f = he[is_flower_shrub]
            fn_f = hn[is_flower_shrub]
            fx_c = np.floor(fe_f / 1.35)
            fy_c = np.floor(fn_f / 1.35)
            fcx = (fx_c + 0.5) * 1.35 + 0.24 * np.sin(fx_c * 3.1 + fy_c * 2.3)
            fcy = (fy_c + 0.5) * 1.35 + 0.24 * np.cos(fx_c * 2.7 - fy_c * 3.7)
            dist_fl = np.hypot(fe_f - fcx, fn_f - fcy)
            b_fl_t = b_tuft[is_flower_shrub]
            # Soft multi-petal bouquet cluster (0.30..0.44m organic patch on upper sunlit interior, never scattered dots!)
            on_bloom = (dist_fl < (0.34 + 0.08 * b_fl_t)) & (edt_h[is_flower_shrub] > 0.22)
            if on_bloom.any():
                pal_sel = (h_clump[is_flower_shrub] >> 2) % 3
                is_hi_fl = b_fl_t > 0.12
                # 0: soft garden rose-pink, 1: hydrangea periwinkle-blue, 2: warm cream-blossom (never harsh pure white!)
                fl_rose = np.where(is_hi_fl[:, None], [236.0, 186.0, 198.0], [216.0, 146.0, 166.0])
                fl_hyd = np.where(is_hi_fl[:, None], [172.0, 196.0, 228.0], [132.0, 162.0, 206.0])
                fl_crm = np.where(is_hi_fl[:, None], [232.0, 222.0, 192.0], [216.0, 204.0, 174.0])
                fl_col = np.where(
                    (pal_sel == 0)[:, None],
                    fl_rose,
                    np.where((pal_sel == 1)[:, None], fl_hyd, fl_crm),
                ).astype(np.float32)
                idx_fs = np.nonzero(is_flower_shrub)[0]
                h_top_col[idx_fs[on_bloom]] = fl_col[on_bloom]

        h_oid = np.full(len(hr), 190000, dtype=np.int32)

        if camera.mpp <= 0.16:
            hedge_slices = (
                (0.22, h_base_col, 0.56, ((0, 0), (1, 0), (0, 1), (1, 1))),
                (0.50, h_mid_col, 0.72, ((0, 0), (1, 0), (0, 1), (1, 1))),
                (0.76, h_mid_col * 1.10, 0.86, ((0, 0), (1, 0), (0, 1), (1, 1))),
                (0.92, h_top_col * 0.93, 0.94, ((0, 0), (1, 0), (0, 1))),
                (1.00, h_top_col, 0.99, ((0, 0), (1, 0))),
            )
        else:
            hedge_slices = (
                (0.30, h_base_col, 0.58, ((0, 0), (1, 0), (0, 1), (1, 1))),
                (0.66, h_mid_col, 0.76, ((0, 0), (1, 0), (0, 1), (1, 1))),
                (1.00, h_top_col, 0.98, ((0, 0), (1, 0))),
            )
        for frac_z, col_arr, nz_v, rad_offs in hedge_slices:
            zc = hz_base + hh * frac_z
            px, py, pd = camera.project(he, hn, zc)
            ix = np.round(px + shift_x).astype(np.int32)
            iy = np.round(py + shift_y).astype(np.int32)
            vh = (ix >= 0) & (ix < W - 2) & (iy >= 0) & (iy < H - 2)
            if not vh.any():
                continue
            ix, iy, pd = ix[vh], iy[vh], pd[vh]
            col_use = col_arr[vh]
            oid_use = h_oid[vh]
            sh_use = sub_shadow[hr[vh], hc[vh]]
            ord_h = np.argsort(pd)[::-1]
            ix, iy, pd = ix[ord_h], iy[ord_h], pd[ord_h]
            col_use, oid_use, sh_use = col_use[ord_h], oid_use[ord_h], sh_use[ord_h]
            for ox, oy in rad_offs:
                tx, ty = ix + ox, iy + oy
                db = pd + (0.04 if (ox or oy) else 0.0)
                win = db < zbuf[ty, tx]
                zbuf[ty[win], tx[win]] = db[win]
                rgb_buf[ty[win], tx[win]] = col_use[win]
                mat_buf[ty[win], tx[win]] = M_TREE
                obj_buf[ty[win], tx[win]] = oid_use[win]
                shadow_buf[ty[win], tx[win]] = sh_use[win]
                norm_buf[ty[win], tx[win], 0] = 0.0 if nz_v > 0.9 else 0.25
                norm_buf[ty[win], tx[win], 1] = 0.0 if nz_v > 0.9 else -0.25
                norm_buf[ty[win], tx[win], 2] = nz_v

    # (d) Strictly Land-Side Lakeside Reeds / Sedge Tufts (0.6m <= dist_lake <= 2.8m, ZERO water/pier/Seebad bleed!)
    lp_r0 = max(0, r0 - 10)
    lp_r1 = min(GRID_H, r1 + 10)
    lp_c0 = max(0, c0 - 10)
    lp_c1 = min(GRID_W, c1 + 10)
    sub_lake_pad = scene.lake_mask[lp_r0:lp_r1, lp_c0:lp_c1]
    if sub_lake_pad.any():
        dist_lk_sub = (
            ndimage.distance_transform_edt(~sub_lake_pad).astype(np.float32) * GRID_RES
        )[(r0 - lp_r0) : (r1 - lp_r0), (c0 - lp_c0) : (c1 - lp_c0)]
        sub_sem_r = scene.sem[r0:r1, c0:c1]
        reed_cand = (
            sub_mask
            & (~scene.lake_mask[r0:r1, c0:c1])
            & (dist_lk_sub >= 0.70)
            & (dist_lk_sub <= 2.75)
            & ((sub_sem_r == G_TERRAIN) | (sub_sem_r == G_PARK_CEMETERY))
            & (~scene.bldg_roof_mask[r0:r1, c0:c1])
            & (~scene.hedge_mask[r0:r1, c0:c1])
            & (scene.road_dist[r0:r1, c0:c1] > (scene.road_hw[r0:r1, c0:c1] + np.float16(1.2)))
        )
        if reed_cand.any():
            rr_r, rc_r = np.nonzero(reed_cand)
            re_r = E_MIN + (rc_r + c0 + 0.5) * GRID_RES
            rn_r = N_MAX - (rr_r + r0 + 0.5) * GRID_RES
            # Exclude Seebad Kilchberg swimming beach/concrete apron & Bendlikon Schifflände stone pier apron
            excl_apron = (
                ((re_r >= 2684160.0) & (re_r <= 2684295.0) & (rn_r >= 1241200.0) & (rn_r <= 1241435.0))
                | ((re_r >= 2684000.0) & (re_r <= 2684165.0) & (rn_r >= 1241650.0) & (rn_r <= 1241835.0))
            )
            # Sparse deterministic pockets (~18% of natural embankment via 6m world-grid hash)
            rx6 = np.floor(re_r / 6.0).astype(np.int64).astype(np.uint32)
            ry6 = np.floor(rn_r / 6.0).astype(np.int64).astype(np.uint32)
            r_pkt = ((rx6 * np.uint32(73856093)) ^ (ry6 * np.uint32(19349663)) ^ np.uint32(0x2F5A)) & np.uint32(0xFF)
            # Keep clean ~18% natural shore pockets, spaced cleanly
            r_cell_h = ((np.floor(re_r * 2.0).astype(np.int64).astype(np.uint32) * np.uint32(2654435761)) ^ (np.floor(rn_r * 2.0).astype(np.int64).astype(np.uint32) * np.uint32(83492791))) & np.uint32(0xFF)
            keep_reed = (~excl_apron) & ((r_pkt % 100) < 22) & ((r_cell_h % 5) < 2)
            if keep_reed.any():
                rr_r, rc_r = rr_r[keep_reed], rc_r[keep_reed]
                re_r, rn_r = re_r[keep_reed], rn_r[keep_reed]
                rz_r = sub_dem[rr_r, rc_r]
                rh_r = 0.58 + 0.36 * ((r_cell_h[keep_reed] & 15).astype(np.float32) / 15.0)
                rsh_r = sub_shadow[rr_r, rc_r]
                # 3 vertical stacked tufted sedge blade levels: base olive -> mid reed -> golden-ochre tip
                reed_levels = (
                    (0.28, np.array([58.0, 96.0, 44.0], dtype=np.float32)),
                    (0.66, np.array([82.0, 122.0, 54.0], dtype=np.float32)),
                    (1.00, np.array([164.0, 150.0, 78.0], dtype=np.float32)),
                )
                for frac_z, r_rgb in reed_levels:
                    px_rd, py_rd, pd_rd = camera.project(re_r, rn_r, rz_r + rh_r * frac_z)
                    ix_rd = np.round(px_rd + shift_x).astype(np.int32)
                    iy_rd = np.round(py_rd + shift_y).astype(np.int32)
                    vrd = (ix_rd >= 0) & (ix_rd < W - 2) & (iy_rd >= 0) & (iy_rd < H - 1)
                    if not vrd.any():
                        continue
                    ix_rd, iy_rd, pd_rd = ix_rd[vrd], iy_rd[vrd], pd_rd[vrd]
                    sh_rd = rsh_r[vrd]
                    # 2px-wide clean vertical sedge blade tuft
                    for ox in (0, 1):
                        tx, ty = ix_rd + ox, iy_rd
                        win = pd_rd < zbuf[ty, tx]
                        if win.any():
                            zbuf[ty[win], tx[win]] = pd_rd[win]
                            rgb_buf[ty[win], tx[win]] = r_rgb * (1.0 if ox == 0 else 0.86)
                            mat_buf[ty[win], tx[win]] = M_TREE
                            obj_buf[ty[win], tx[win]] = 191000
                            shadow_buf[ty[win], tx[win]] = sh_rd[win]
                            norm_buf[ty[win], tx[win], 0] = 0.15
                            norm_buf[ty[win], tx[win], 1] = -0.15
                            norm_buf[ty[win], tx[win], 2] = 0.96

    # -------------------------------------------------------------------------
    # 4B. v13.0 All 16,000+ Realistic Botanical Pixel-Art 3D Trees (8 Swiss/Zürichsee Species!)
    #     0: Swiss Oak/Beech | 1: Alpine Spruce/Fir | 2: Silver Birch | 3: Lakeside Weeping Willow
    #     4: Lombardy Poplar/Cypress | 5: Blossoming Orchard/Cherry | 6: Copper Beech | 7: Swiss Linden/Maple
    # -------------------------------------------------------------------------
    te = scene.tree_e
    tn = scene.tree_n
    tz = scene.tree_z
    th = scene.tree_h
    trad = scene.tree_rad
    tsp = scene.tree_species_v13
    t_ids = np.arange(len(te), dtype=np.int32)

    if crop_box_lv95 is not None:
        e0, n0, e1, n1 = crop_box_lv95
        keep = (te >= e0 + 1.5) & (te <= e1 - 1.5) & (tn >= n0 + 1.5) & (tn <= n1 - 1.5)
        te, tn, tz, th, trad, tsp, t_ids = (
            te[keep], tn[keep], tz[keep], th[keep], trad[keep], tsp[keep], t_ids[keep]
        )

    if len(te) == 0:
        return

    px_base, py_base, pd_base = camera.project(te, tn, tz)
    px_top, py_top, _ = camera.project(te, tn, tz + th)
    r_px_est = np.minimum(52.0, (trad * 1.40 / camera.mpp) + 10.0)
    in_vp = (
        (px_base + shift_x + r_px_est >= -6.0)
        & (px_base + shift_x - r_px_est <= W + 6.0)
        & (py_base + shift_y + 12.0 >= -6.0)
        & (py_top + shift_y - r_px_est <= H + 6.0)
    )
    if not in_vp.any():
        return

    te, tn, tz, th, trad, tsp, t_ids = (
        te[in_vp], tn[in_vp], tz[in_vp], th[in_vp], trad[in_vp], tsp[in_vp], t_ids[in_vp]
    )
    px_base = px_base[in_vp] + shift_x
    py_base = py_base[in_vp] + shift_y
    px_top = px_top[in_vp] + shift_x
    py_top = py_top[in_vp] + shift_y
    pd_base = pd_base[in_vp]

    t_ord = np.argsort(pd_base)[::-1]
    te, tn, tz, th, trad, tsp, t_ids = (
        te[t_ord], tn[t_ord], tz[t_ord], th[t_ord], trad[t_ord], tsp[t_ord], t_ids[t_ord]
    )
    px_base, py_base, py_top, pd_base = px_base[t_ord], py_base[t_ord], py_top[t_ord], pd_base[t_ord]

    # v13.0 Botanical 5-Tone Cel-Shaded Foliage Ramps for all 8 Swiss/Zürichsee Species
    SPECIES_RAMPS = np.array(
        [
            # 0: Swiss Oak / Beech (deep pine-ink -> rich forest -> vibrant emerald -> olive-emerald -> bright sunlit tip)
            [[18.0, 52.0, 34.0], [34.0, 92.0, 42.0], [58.0, 138.0, 48.0], [96.0, 174.0, 58.0], [136.0, 204.0, 72.0]],
            # 1: Alpine Spruce / Silver Fir (deep alpine blue-spruce -> dark fir -> mountain spruce -> sunlit blue-green needles)
            [[14.0, 40.0, 38.0], [24.0, 66.0, 50.0], [40.0, 98.0, 62.0], [62.0, 132.0, 76.0], [90.0, 160.0, 92.0]],
            # 2: Silver Birch (fresh light-emerald / yellow-green feathery birch foliage)
            [[28.0, 72.0, 40.0], [48.0, 118.0, 48.0], [84.0, 168.0, 56.0], [128.0, 198.0, 68.0], [172.0, 218.0, 86.0]],
            # 3: Lakeside Weeping Willow (silvery-sage cascading Zürichsee willow)
            [[22.0, 62.0, 44.0], [40.0, 98.0, 58.0], [70.0, 140.0, 74.0], [108.0, 176.0, 92.0], [148.0, 206.0, 116.0]],
            # 4: Lombardy Poplar / Mediterranean Cypress (deep sculptural cypress emerald)
            [[14.0, 42.0, 32.0], [26.0, 68.0, 42.0], [44.0, 102.0, 54.0], [68.0, 136.0, 66.0], [96.0, 166.0, 80.0]],
            # 5: Blossoming Orchard / Cherry / Magnolia (dusty rose -> warm pink -> sunlit creamy-white petals)
            [[122.0, 72.0, 88.0], [172.0, 114.0, 128.0], [212.0, 156.0, 170.0], [238.0, 202.0, 212.0], [252.0, 236.0, 240.0]],
            # 6: Copper Beech / Blutbuche (deep aubergine-plum -> rich burgundy -> warm bronze-copper)
            [[40.0, 20.0, 32.0], [66.0, 32.0, 42.0], [98.0, 46.0, 50.0], [130.0, 64.0, 60.0], [164.0, 88.0, 74.0]],
            # 7: Swiss Linden / Maple (warm sunlit olive-emerald upright broadleaf)
            [[24.0, 68.0, 38.0], [44.0, 108.0, 46.0], [74.0, 154.0, 52.0], [116.0, 188.0, 64.0], [156.0, 214.0, 78.0]],
        ],
        dtype=np.float32,
    )

    # Precompute screen-space lighting vector (top-left sunlit rim in isometric camera!)
    e_right, e_depth, sp_c, cp_c = camera.basis
    sx_l = float(sun_vec[0] * e_right[0] + sun_vec[1] * e_right[1])
    sd_l = float(sun_vec[0] * e_depth[0] + sun_vec[1] * e_depth[1])
    sz_l = float(sun_vec[2])
    sy_up_l = sp_c * sd_l + cp_c * sz_l
    scam_l = -cp_c * sd_l + sp_c * sz_l
    l_mag = max(1e-5, math.sqrt(sx_l * sx_l + sy_up_l * sy_up_l + scam_l * scam_l))
    lx_s, ly_s, lz_s = sx_l / l_mag, sy_up_l / l_mag, scam_l / l_mag

    mpp = camera.mpp
    z_px_per_m = (cp_c * camera.z_exag) / mpp
    px_s_tr = 0.25 / max(0.08, mpp)

    def _draw_branch_seg(
        x_a: float, y_a: float, x_b: float, y_b: float,
        half_w: int, d_br: float, col_lit: np.ndarray, col_sh: np.ndarray, oid_b: int,
    ) -> None:
        """Rasterize a crisp tapered woody branch fork segment into zbuf/rgb_buf (100% tree-relative)."""
        steps = max(2, int(math.ceil(max(abs(x_b - x_a), abs(y_b - y_a)) * 1.4)))
        for st_i in range(steps + 1):
            t_f = st_i / steps
            bx = int(round(x_a + (x_b - x_a) * t_f))
            by = int(round(y_a + (y_b - y_a) * t_f))
            if by < 0 or by >= H:
                continue
            hw_cur = half_w if t_f < 0.55 else max(0, half_w - 1)
            for ox in range(-hw_cur, hw_cur + 1):
                px_b = bx + ox
                if 0 <= px_b < W and d_br < zbuf[by, px_b]:
                    zbuf[by, px_b] = d_br
                    rgb_buf[by, px_b] = col_lit if ox <= 0 else col_sh
                    mat_buf[by, px_b] = M_TRUNK
                    obj_buf[by, px_b] = oid_b
                    norm_buf[by, px_b] = [0.45, -0.45, 0.40]
                    shadow_buf[by, px_b] = False

    def _leaf_tuft_field(
        dx_a: np.ndarray, dy_a: np.ndarray, s1_i: int, s2_i: int, scale_px: float = 3.0,
    ) -> np.ndarray:
        """Aperiodic tree-relative 2-4 px coherent leaf-tuft cluster field in [-1, +1].
        ZERO 1x1 speckle, ZERO Bayer checkerboard, ZERO periodic 2D grid, 100% macro-tile seam-invariant!"""
        k0 = (2.0 * math.pi) / max(1.8, scale_px)
        ang0 = (s1_i & 255) * 0.02454369
        c0, sn0 = math.cos(ang0), math.sin(ang0)
        c1, sn1 = math.cos(ang0 + 1.13), math.sin(ang0 + 1.13)
        c2, sn2 = math.cos(ang0 + 2.29), math.sin(ang0 + 2.29)
        p0 = ((s1_i >> 8) & 255) * 0.02454369
        p1 = (s2_i & 255) * 0.02454369
        p2 = ((s2_i >> 8) & 255) * 0.02454369
        u0 = (dx_a * c0 + dy_a * sn0) * k0 + p0
        u1 = (dx_a * c1 + dy_a * sn1) * (k0 * 0.87) + p1
        u2 = (dx_a * c2 + dy_a * sn2) * (k0 * 1.16) + p2
        raw = 0.42 * np.sin(u0) + 0.34 * np.cos(u1) + 0.24 * np.sin(u2)
        return np.tanh(1.55 * raw).astype(np.float32)

    for i in range(len(te)):
        sp = int(tsp[i])
        tid = int(t_ids[i])
        oid = 100000 + tid
        h_m = float(th[i])
        r_m = float(trad[i])
        cx0 = float(px_base[i])
        cy0 = float(py_base[i])
        d0 = float(pd_base[i])

        # Deterministic per-tree variation seeds
        s0 = ((tid * 73856093) ^ 0x5A5A) & 0xFFFF
        s1 = ((tid * 19349663) ^ 0xA53C) & 0xFFFF
        s2 = ((tid * 83492791) ^ 0x3C71) & 0xFFFF
        w_var = 0.88 + 0.24 * ((s0 & 255) / 255.0)
        h_var = 0.90 + 0.20 * (((s0 >> 8) & 255) / 255.0)

        # Species proportions — CRITICAL GUARD: clamp r_px so outer boughs + scallops stay <= 52 px (< guard_x = 56 px)!
        if sp == 1:  # Alpine Spruce / Silver Fir
            r_px = min(38.0, max(3.4, (r_m * 1.12 * w_var) / mpp))
            h_px = max(10.0, min(h_m * z_px_per_m * h_var, r_px * 3.65))
            trunk_h_px = max(2.4, h_px * (0.18 + 0.05 * ((s1 & 7) / 7.0)))
            crown_ry = max(4.0, 0.5 * (h_px - trunk_h_px))
        elif sp == 4:  # Lombardy Poplar / Mediterranean Cypress
            r_px = min(22.0, max(2.8, (min(r_m, 2.1) * 0.98 * w_var) / mpp))
            h_px = max(10.0, min(h_m * z_px_per_m * h_var * 1.08, r_px * 4.25))
            trunk_h_px = max(1.8, h_px * 0.13)
            crown_ry = max(4.2, 0.5 * (h_px - trunk_h_px))
        elif sp == 3:  # Lakeside Weeping Willow (tall gnarled trunk + airy dome + delicate hanging tendrils!)
            r_px = min(38.0, max(4.5, (r_m * 1.22 * w_var) / mpp))
            h_px = max(9.0, min(h_m * z_px_per_m * h_var, r_px * 2.45))
            trunk_h_px = max(3.6, h_px * 0.34)
            crown_ry = max(3.8, min(h_px * 0.44, r_px * 0.78))
        elif sp == 2:  # Silver Birch (slender, taller airy crown)
            r_px = min(36.0, max(3.6, (r_m * 1.12 * w_var) / mpp))
            h_px = max(8.5, min(h_m * z_px_per_m * h_var * 1.06, r_px * 2.95))
            crown_ry = max(4.0, min(h_px * 0.48, r_px * 1.06))
            trunk_h_px = max(3.4, h_px - crown_ry * 1.66)
        elif sp == 7:  # Swiss Linden / Maple (upright oval-dome broadleaf)
            r_px = min(39.0, max(3.8, (r_m * 1.16 * w_var) / mpp))
            h_px = max(8.0, min(h_m * z_px_per_m * h_var, r_px * 2.75))
            crown_ry = max(4.0, min(h_px * 0.52, r_px * (0.92 + 0.16 * (((s1 >> 8) & 15) / 15.0))))
            trunk_h_px = max(3.0, h_px - crown_ry * 1.72)
        elif sp == 5:  # Blossoming Orchard / Cherry / Magnolia (compact open-vase)
            r_px = min(34.0, max(3.6, (r_m * 1.18 * w_var) / mpp))
            h_px = max(7.0, min(h_m * z_px_per_m * h_var, r_px * 2.35))
            crown_ry = max(3.4, min(h_px * 0.48, r_px * 0.86))
            trunk_h_px = max(2.6, h_px - crown_ry * 1.72)
        else:  # 0: Swiss Oak / Beech & 6: Copper Beech (wide-spreading majestic broadleaf)
            r_px = min(40.0, max(4.0, (r_m * 1.25 * w_var) / mpp))
            h_px = max(7.5, min(h_m * z_px_per_m * h_var, r_px * 2.60))
            oak_ry_fac = 0.72 + 0.16 * (((s1 >> 8) & 15) / 15.0)
            crown_ry = max(3.5, min(h_px * 0.50, r_px * oak_ry_fac))
            trunk_h_px = max(2.6, h_px - crown_ry * 1.76)

        # 0. Clean Solid Oval Cool-Tinted Canopy Contact Shadow (ZERO checkerboard dither ring!)
        sh_rx = int(math.ceil(r_px * (0.76 if sp in (1, 4) else 0.90)))
        sh_ry = max(2, int(math.ceil(r_px * (0.34 if sp in (1, 4) else 0.42))))
        sx0 = max(0, int(round(cx0 - sh_rx * 0.75)))
        sx1 = min(W - 1, int(round(cx0 + sh_rx * 1.10)))
        sy0 = max(0, int(round(cy0 - sh_ry * 0.65)))
        sy1 = min(H - 1, int(round(cy0 + sh_ry * 0.85)))
        if sx1 >= sx0 and sy1 >= sy0:
            sxs = np.arange(sx0, sx1 + 1, dtype=np.float32)
            sys = np.arange(sy0, sy1 + 1, dtype=np.float32)
            sgx, sgy = np.meshgrid(sxs, sys)
            sr2 = ((sgx - (cx0 + r_px * 0.18)) / max(1.5, sh_rx)) ** 2 + ((sgy - (cy0 + 0.5)) / max(1.2, sh_ry)) ** 2
            in_sh = (sr2 <= 0.86) & (mat_buf[sy0 : sy1 + 1, sx0 : sx1 + 1] == M_GROUND) & (zbuf[sy0 : sy1 + 1, sx0 : sx1 + 1] > (d0 - 3.5))
            if in_sh.any():
                rgb_buf[sy0 : sy1 + 1, sx0 : sx1 + 1][in_sh] *= np.array([0.74, 0.78, 0.86], dtype=np.float32)

        crown_bot_y = cy0 - trunk_h_px
        crown_top_y = crown_bot_y - crown_ry * 2.0
        crown_cy = 0.5 * (crown_bot_y + crown_top_y)

        # Compute tight screen bounding box (clamped <= 52 px < guard_x=56 px!)
        pad_x = min(52, int(math.ceil(r_px * 1.28)) + 2)
        x0_b = max(0, int(math.floor(cx0)) - pad_x)
        x1_b = min(W - 1, int(math.ceil(cx0)) + pad_x)
        y0_b = max(0, int(math.floor(crown_top_y)) - 4)
        y1_b = min(H - 1, int(math.ceil(cy0)) + 1) if sp == 3 else min(H - 1, int(math.ceil(crown_bot_y)) + 2)
        if x1_b < x0_b or y1_b < y0_b:
            continue

        xs = np.arange(x0_b, x1_b + 1, dtype=np.float32)
        ys = np.arange(y0_b, y1_b + 1, dtype=np.float32)
        gx, gy = np.meshgrid(xs, ys)
        dx = gx - cx0
        dy_c = gy - crown_cy
        v_h = (crown_bot_y - gy) / max(1.0, (crown_bot_y - crown_top_y))

        ramp = SPECIES_RAMPS[sp].copy()
        hue_shift = (((s2 & 31) / 31.0) - 0.5) * 0.12
        if abs(hue_shift) > 0.01:
            ramp = np.clip(ramp * np.array([1.0 + hue_shift * 0.75, 1.0 + hue_shift * 0.45, 1.0 - hue_shift * 0.4], dtype=np.float32), 8.0, 252.0)
        if not is_night and sp not in (5, 6):
            ramp[4] = np.clip(ramp[4] + np.array([9.0, 7.0, -3.0], dtype=np.float32), 8.0, 252.0)
            ramp[0] = np.clip(ramp[0] * np.array([0.92, 0.94, 0.96], dtype=np.float32), 10.0, 252.0)

        # ---------------------------------------------------------------------
        # PASS A: Compact Shaded Lower-Core Recess (shrunk so sky & branches peek cleanly through upper/mid crown!)
        # Skipped for airy Silver Birch (sp==2) and Weeping Willow (sp==3) so real air gaps frame the trunk & boughs!
        # ---------------------------------------------------------------------
        if sp in (0, 5, 6, 7) and r_px >= 6.0:
            ux_bk = dx / max(1.5, r_px * 0.58)
            uy_bk = (dy_c - 0.24 * crown_ry) / max(1.5, crown_ry * 0.52)
            th_bk = np.arctan2(uy_bk, ux_bk)
            sc_bk = 1.0 + 0.12 * np.cos(5.0 * th_bk + (s1 & 15) * 0.4)
            in_bk = (np.sqrt(ux_bk * ux_bk + uy_bk * uy_bk) / sc_bk) < 1.0
            if in_bk.any():
                d_bk = d0 + 0.18
                sub_z_bk = zbuf[y0_b : y1_b + 1, x0_b : x1_b + 1]
                win_bk = in_bk & (d_bk < sub_z_bk)
                if win_bk.any():
                    wy_bk, wx_bk = np.nonzero(win_bk)
                    gy_bk, gx_bk = y0_b + wy_bk, x0_b + wx_bk
                    zbuf[gy_bk, gx_bk] = d_bk
                    bk_col = np.array([34.0, 74.0, 34.0], dtype=np.float32) if sp == 5 else (ramp[0] * 0.90)
                    rgb_buf[gy_bk, gx_bk] = bk_col
                    mat_buf[gy_bk, gx_bk] = M_TREE
                    obj_buf[gy_bk, gx_bk] = oid
                    norm_buf[gy_bk, gx_bk] = [0.15, -0.10, 0.88]
                    shadow_buf[gy_bk, gx_bk] = False

        # ---------------------------------------------------------------------
        # PASS B: Tapered Woody Trunk, Root Flare & Angled Y-Forked Primary Limbs (depth d0 + 0.05..0.08)
        # ---------------------------------------------------------------------
        tx_i = int(round(cx0))
        ty_bot = int(round(cy0)) + 1
        if sp == 1:
            # Alpine Spruce: visible dark reddish-brown trunk peeking between shaggy drooping boughs
            fork_y = cy0 - h_px * 0.78
            tw_half = max(1, int(round(0.85 * px_s_tr))) if r_px >= (7.0 * px_s_tr) else (1 if px_s_tr >= 1.5 else 0)
            bark_lit = np.array([88.0, 56.0, 40.0], dtype=np.float32)
            bark_mid = np.array([70.0, 44.0, 32.0], dtype=np.float32)
            bark_sh = np.array([46.0, 30.0, 22.0], dtype=np.float32)
            lenticel_col = bark_sh
        elif sp == 3:
            # Weeping Willow: sturdy gnarled warm grey-brown trunk visible beneath arching fronds
            fork_y = crown_bot_y - crown_ry * 0.22
            tw_half = max(1, int(round(1.15 * px_s_tr))) if r_px >= (6.0 * px_s_tr) else 1
            bark_lit = np.array([102.0, 82.0, 62.0], dtype=np.float32)
            bark_mid = np.array([80.0, 64.0, 48.0], dtype=np.float32)
            bark_sh = np.array([52.0, 42.0, 32.0], dtype=np.float32)
            lenticel_col = bark_sh
        elif sp == 2:
            fork_y = crown_bot_y - crown_ry * 0.30
            tw_half = 1 if r_px >= (5.5 * px_s_tr) else 0
            bark_lit = np.array([218.0, 214.0, 206.0], dtype=np.float32)
            bark_mid = np.array([188.0, 184.0, 178.0], dtype=np.float32)
            bark_sh = np.array([154.0, 152.0, 148.0], dtype=np.float32)
            lenticel_col = np.array([52.0, 48.0, 46.0], dtype=np.float32)
        elif sp == 5:
            fork_y = crown_bot_y - crown_ry * 0.28
            tw_half = max(1, int(round(0.85 * px_s_tr))) if r_px >= (6.5 * px_s_tr) else (1 if px_s_tr >= 1.5 else 0)
            bark_lit = np.array([86.0, 56.0, 42.0], dtype=np.float32)
            bark_mid = np.array([72.0, 46.0, 34.0], dtype=np.float32)
            bark_sh = np.array([50.0, 32.0, 24.0], dtype=np.float32)
            lenticel_col = bark_sh
        else:
            fork_y = crown_bot_y - crown_ry * (0.28 if sp in (0, 6, 7) else 0.15)
            tw_half = max(1, int(round(1.0 * px_s_tr))) if r_px >= (6.5 * px_s_tr) else (1 if px_s_tr >= 1.5 else 0)
            bark_lit = np.array([96.0, 68.0, 46.0], dtype=np.float32)
            bark_mid = np.array([82.0, 56.0, 38.0], dtype=np.float32)
            bark_sh = np.array([54.0, 36.0, 24.0], dtype=np.float32)
            lenticel_col = bark_sh

        ty_top = int(round(fork_y))
        y_lo_t = max(0, ty_top)
        y_hi_t = min(H - 1, ty_bot)
        d_tr = d0 + (0.05 if sp == 3 else 0.08)
        if sp in (2, 3) and y_hi_t >= y_lo_t:
            # Organic gently curved/leaning trunk for Silver Birch & gnarled Weeping Willow
            lean_dir = 1.0 if ((s1 & 1) == 0) else -1.0
            lean_amp = (1.4 if sp == 2 else 1.8) * lean_dir
            t_span = max(1.0, float(ty_bot - ty_top))
            for py_t in range(y_lo_t, y_hi_t + 1):
                t_up = np.clip((ty_bot - py_t) / t_span, 0.0, 1.0)
                x_c_t = int(round(cx0 + math.sin(t_up * math.pi * 0.85) * lean_amp))
                hw_row = tw_half if (t_up < 0.72 or sp == 2) else max(0, tw_half - 1)
                for ox_t in range(-hw_row, hw_row + 1):
                    px_t = x_c_t + ox_t
                    if 0 <= px_t < W and d_tr < zbuf[py_t, px_t]:
                        zbuf[py_t, px_t] = d_tr
                        c_b = bark_lit if ox_t < 0 else (bark_sh if ox_t > 0 else bark_mid)
                        if sp == 2 and ox_t == hw_row and (((int(round(cy0 - py_t)) + (s1 & 3)) % 5) == 0):
                            c_b = lenticel_col
                        rgb_buf[py_t, px_t] = c_b
                        mat_buf[py_t, px_t] = M_TRUNK
                        obj_buf[py_t, px_t] = oid
                        norm_buf[py_t, px_t] = [0.5, -0.5, 0.35]
                        shadow_buf[py_t, px_t] = False
        elif y_hi_t >= y_lo_t:
            x_lo_t = max(0, tx_i - tw_half)
            x_hi_t = min(W - 1, tx_i + tw_half)
            if x_hi_t >= x_lo_t:
                sl_z = zbuf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1]
                w_tr = d_tr < sl_z
                if w_tr.any():
                    sl_z[w_tr] = d_tr
                    tw_w = x_hi_t - x_lo_t + 1
                    th_h = y_hi_t - y_lo_t + 1
                    if tw_half >= 1:
                        bx_rel = np.arange(x_lo_t, x_hi_t + 1, dtype=np.float32) - tx_i
                        b_col = np.where(
                            (bx_rel < 0)[:, None], bark_lit, np.where((bx_rel > 0)[:, None], bark_sh, bark_mid)
                        ).astype(np.float32)
                        b_patch = np.broadcast_to(b_col[None, :, :], (th_h, tw_w, 3)).copy()
                    else:
                        b_patch = np.broadcast_to(bark_lit[None, None, :], (th_h, tw_w, 3)).copy()
                    rgb_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = b_patch[w_tr]
                    mat_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = M_TRUNK
                    obj_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = oid
                    norm_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = [0.5, -0.5, 0.35]
                    shadow_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = False

        # Crisp 1px root flare at tree base when high-res
        if px_s_tr >= 1.5 and 0 <= ty_bot < H:
            for fx_off in (-(tw_half + 1), tw_half + 1):
                fx_p = tx_i + fx_off
                if 0 <= fx_p < W and (d0 + 0.12) < zbuf[ty_bot, fx_p]:
                    zbuf[ty_bot, fx_p] = d0 + 0.12
                    rgb_buf[ty_bot, fx_p] = bark_sh
                    mat_buf[ty_bot, fx_p] = M_TRUNK
                    obj_buf[ty_bot, fx_p] = oid
                    norm_buf[ty_bot, fx_p] = [0.4, -0.4, 0.5]
                    shadow_buf[ty_bot, fx_p] = False

        # Angled primary woody Y-fork branch limbs reaching into the crown interior!
        if sp in (0, 2, 3, 5, 6, 7) and r_px >= 5.5:
            br_hw = 1 if (r_px >= 13.0 and sp != 2) else 0
            f_y0 = fork_y + crown_ry * 0.14
            tilt_b = (((s2 >> 4) & 7) / 7.0 - 0.5) * 0.18
            if sp == 3:
                # Gnarled Weeping Willow: 3-4 wide-arching primary boughs peeking cleanly through hanging tendrils!
                lean_w = (1.8 if ((s1 & 1) == 0) else -1.8) * 0.7
                fx_w = cx0 + lean_w
                _draw_branch_seg(fx_w, f_y0, fx_w - r_px * 0.56, crown_cy - crown_ry * 0.16, br_hw, d_tr, bark_lit, bark_sh, oid)
                _draw_branch_seg(fx_w, f_y0, fx_w + r_px * 0.54, crown_cy - crown_ry * 0.12, br_hw, d_tr, bark_lit, bark_sh, oid)
                _draw_branch_seg(fx_w, f_y0 - crown_ry * 0.10, fx_w - r_px * 0.20, crown_cy - crown_ry * 0.44, 0, d_tr, bark_lit, bark_sh, oid)
                if r_px >= 10.0:
                    _draw_branch_seg(fx_w, f_y0 - crown_ry * 0.08, fx_w + r_px * 0.24, crown_cy - crown_ry * 0.40, 0, d_tr, bark_lit, bark_sh, oid)
            elif sp == 2:
                # Delicate upward V-forked pale birch limbs reaching high through airy crown gaps
                lean_b = (1.4 if ((s1 & 1) == 0) else -1.4) * 0.65
                fx_b = cx0 + lean_b
                _draw_branch_seg(fx_b, f_y0, fx_b - r_px * (0.44 + tilt_b), crown_cy - crown_ry * 0.40, 0, d_tr, bark_lit, bark_sh, oid)
                _draw_branch_seg(fx_b, f_y0, fx_b + r_px * (0.42 - tilt_b), crown_cy - crown_ry * 0.36, 0, d_tr, bark_lit, bark_sh, oid)
                _draw_branch_seg(fx_b, f_y0 - crown_ry * 0.15, fx_b + r_px * tilt_b, crown_cy - crown_ry * 0.60, 0, d_tr, bark_lit, bark_sh, oid)
            elif sp == 5:
                # Wide-angled open-vase orchard cherry branch forks
                _draw_branch_seg(cx0, f_y0, cx0 - r_px * 0.54, crown_cy - crown_ry * 0.12, br_hw, d_tr, bark_lit, bark_sh, oid)
                _draw_branch_seg(cx0, f_y0, cx0 + r_px * 0.52, crown_cy - crown_ry * 0.08, br_hw, d_tr, bark_lit, bark_sh, oid)
                _draw_branch_seg(cx0, f_y0 - crown_ry * 0.10, cx0 - r_px * 0.14, crown_cy - crown_ry * 0.42, 0, d_tr, bark_lit, bark_sh, oid)
            else:
                # Asymmetric Y-forked primary limbs for Oak, Copper Beech, Linden
                _draw_branch_seg(cx0, f_y0, cx0 - r_px * (0.48 + tilt_b), crown_cy - crown_ry * 0.18, br_hw, d_tr, bark_lit, bark_sh, oid)
                _draw_branch_seg(cx0, f_y0, cx0 + r_px * (0.46 - tilt_b), crown_cy - crown_ry * 0.14, br_hw, d_tr, bark_lit, bark_sh, oid)
                if r_px >= 12.0:
                    _draw_branch_seg(cx0, f_y0 - crown_ry * 0.12, cx0 + r_px * (0.16 + tilt_b), crown_cy - crown_ry * 0.46, 0, d_tr, bark_lit, bark_sh, oid)

        # ---------------------------------------------------------------------
        # PASS C: Studio Ghibli / 90s Isometric Botanical Foliage (aperiodic 2-4 px leaf-tufts, ZERO clipart/cabbage/play-doh!)
        # ---------------------------------------------------------------------
        blossom_leaf_mask = None

        if sp == 1:
            # 1. ALPINE SPRUCE / SILVER FIR: 6-9 irregular asymmetric drooping multi-bough tiers + shaggy 2-4px needle fingers!
            tuft_f = _leaf_tuft_field(dx, dy_c, s1, s2, scale_px=2.6)
            n_tiers = 9 if h_px >= 38.0 else (7 if h_px >= 22.0 else 6)
            c_h_span = max(2.0, crown_bot_y - crown_top_y)
            best_z = np.full(gx.shape, -1.0, dtype=np.float32)
            best_nx = np.zeros(gx.shape, dtype=np.float32)
            best_ny = np.zeros(gx.shape, dtype=np.float32)
            best_bias = np.zeros(gx.shape, dtype=np.float32)

            for k_t in range(n_tiers):
                hk = ((tid * 1664525 + k_t * 1013904223) ^ s1) & 0xFFFF
                v_base = (k_t + 0.35) / float(n_tiers)
                v_jit = (((hk & 15) / 15.0) - 0.5) * (0.20 / float(n_tiers))
                v_t = min(0.92, max(0.03, v_base + v_jit))
                y_tier = crown_bot_y - v_t * c_h_span
                tier_h = max(2.2, (c_h_span / float(n_tiers)) * (1.28 - 0.24 * v_t))
                cx_t = ((((hk >> 4) & 15) / 15.0) - 0.5) * 0.16 * r_px
                reach_l = 0.84 + 0.32 * (((hk >> 8) & 15) / 15.0)
                reach_r = 0.84 + 0.32 * (((hk >> 12) & 15) / 15.0)
                w_env = max(1.6, r_px * (1.06 - 0.86 * (v_t ** 0.88)))

                # 3 to 5 overlapping drooping needle-bough sub-lobes per tier (outer tips curve downward!)
                if w_env >= 9.0:
                    sub_boughs = (
                        (-0.62 * reach_l, 0.24, 0.44 * reach_l, 0.72, 0.16),
                        (-0.28 * reach_l, 0.08, 0.42, 0.78, 0.20),
                        (0.02, -0.02, 0.44, 0.80, 0.14),
                        (0.30 * reach_r, 0.10, 0.42, 0.78, -0.04),
                        (0.60 * reach_r, 0.26, 0.44 * reach_r, 0.72, -0.18),
                    )
                else:
                    sub_boughs = (
                        (-0.46 * reach_l, 0.18, 0.52 * reach_l, 0.76, 0.16),
                        (0.0, 0.0, 0.52, 0.82, 0.12),
                        (0.46 * reach_r, 0.20, 0.52 * reach_r, 0.76, -0.14),
                    )
                for b_u, b_dy, b_rx_f, b_ry_f, b_lit in sub_boughs:
                    bx_c = cx_t + b_u * w_env
                    by_c = y_tier + b_dy * tier_h
                    brx = max(1.3, b_rx_f * w_env)
                    bry = max(1.3, b_ry_f * tier_h)
                    ux = (dx - bx_c) / brx
                    # Drooping spruce bough curve: outer tips dip downward (+0.18 * tier_h * u^2)
                    dy_droop = (dy_c - (by_c - crown_cy)) - 0.18 * tier_h * (ux * ux)
                    uy = dy_droop / bry
                    r_eff = np.sqrt(ux * ux + uy * uy) - 0.14 * tuft_f
                    in_b = r_eff < 1.0
                    if not in_b.any():
                        continue
                    lz = np.sqrt(np.maximum(0.0, 1.0 - np.minimum(1.0, r_eff * r_eff))) * (0.85 + 0.15 * v_t)
                    better = in_b & (lz > best_z)
                    best_z[better] = lz[better]
                    best_nx[better] = np.clip((dx[better] - cx_t) / max(1.5, w_env), -1.0, 1.0)
                    best_ny[better] = np.clip(-uy[better] * 0.7 + 0.22, -0.9, 0.9)
                    # Deep blue-spruce under-bough shadow on underside of each drooping tier!
                    under_sh = np.where(uy[better] > 0.26, -0.38, np.where(uy[better] < -0.18, 0.24, 0.0))
                    best_bias[better] = b_lit + under_sh

            # Narrow windswept organic leader spire at apex (v_h > 0.84)
            lead_lean = ((((s2 >> 4) & 7) / 7.0) - 0.5) * 2.4
            v_c = np.clip(v_h, 0.0, 1.0)
            in_lead = (v_h >= 0.84) & (v_h <= 1.06) & (np.abs(dx - lead_lean * np.clip((v_h - 0.84) / 0.22, 0.0, 1.0)) <= np.maximum(0.9, (1.06 - v_h) * r_px * 0.55 + 0.35 * tuft_f))
            if in_lead.any():
                use_ld = in_lead & (best_z < 0.45)
                best_z[use_ld] = 0.65
                best_nx[use_ld] = -0.25
                best_ny[use_ld] = 0.55
                best_bias[use_ld] = 0.16

            inside = best_z > 0.12
            if not inside.any():
                continue
            nz_n = np.maximum(0.14, best_z)
            nd_s = best_nx * lx_s + best_ny * ly_s + nz_n * lz_s + best_bias + 0.26 * tuft_f
            d_surf = d0 - nz_n * (r_m * 0.78) - v_c * (h_m * 0.45 * sp_c)

        elif sp == 4:
            # 4. LOMBARDY POPLAR / MEDITERRANEAN CYPRESS: Asymmetric stacked-tuft columnar flame + 2-4px tufted silhouette!
            tuft_f = _leaf_tuft_field(dx, dy_c, s1, s2, scale_px=2.6)
            in_v = (v_h >= -0.02) & (v_h <= 1.05)
            v_c = np.clip(v_h, 0.0, 1.0)
            n_tufts = 7.0 if h_px >= 24.0 else 5.0
            tuft_ph = (v_c * n_tufts) % 1.0
            tuft_idx = np.floor(v_c * n_tufts)
            lean_c = ((((s1 >> 6) & 7) / 7.0) - 0.5) * 2.0 * (v_c ** 1.2)
            flame = np.sin(np.power(np.clip(v_c, 0.01, 0.995), 0.68) * math.pi)
            tuft_mod = 0.86 + 0.16 * np.sin(tuft_ph * math.pi) + 0.08 * np.cos(tuft_idx * 2.1 + (s1 & 7))
            half_w_y = np.maximum(1.1, r_px * (0.20 + 0.84 * flame) * tuft_mod + 0.13 * r_px * tuft_f)
            nx_n = (dx - lean_c) / half_w_y
            inside = in_v & (np.abs(nx_n) <= 1.0)
            if not inside.any():
                continue
            nz_n = np.sqrt(np.maximum(0.08, 1.0 - np.minimum(0.98, nx_n * nx_n)))
            ny_n = (v_c - 0.42) * 0.65 + (0.25 - 0.45 * tuft_ph)
            axial_sh = np.where(nx_n > 0.16, -0.34, np.where(nx_n < -0.18, 0.24, 0.0))
            nd_s = nx_n * lx_s + ny_n * ly_s + nz_n * lz_s + axial_sh + 0.24 * tuft_f
            d_surf = d0 - nz_n * (r_m * 0.74) - v_c * (h_m * 0.45 * sp_c)

        elif sp == 3:
            # 3. LAKESIDE WEEPING WILLOW: Airy asymmetrical leaf-tuft dome + discrete wispy hanging leaf tendrils!
            # ZERO solid striped green cabbage bucket! Visible gnarled trunk + 30-45% air gaps + tips <= cy0 - 1.5!
            tuft_f = _leaf_tuft_field(dx, dy_c, s1, s2, scale_px=2.8)
            jx1 = (((s1 & 15) / 15.0) - 0.5) * 0.22 * r_px
            jy1 = ((((s1 >> 4) & 15) / 15.0) - 0.5) * 0.14 * crown_ry
            asym_w = ((((s2 >> 6) & 15) / 15.0) - 0.5) * 0.18 * r_px
            # 7 asymmetrical uneven-sized upper-crown leaf-tuft lobes arching over the forked boughs
            w_lobes = (
                (asym_w * 0.35 + jx1 * 0.30, -0.56 * crown_ry + jy1 * 0.35, 0.50 * r_px, 0.38 * crown_ry, 6.0, 0.14, 0.4, 0.26),
                (-0.46 * r_px + jx1 * 0.20, -0.32 * crown_ry, 0.44 * r_px, 0.36 * crown_ry, 5.0, 0.15, 1.9, 0.20),
                (0.46 * r_px - jx1 * 0.20, -0.28 * crown_ry, 0.42 * r_px, 0.36 * crown_ry, 5.0, 0.15, 3.1, 0.10),
                (-0.72 * r_px + jx1 * 0.15, -0.06 * crown_ry, 0.34 * r_px, 0.34 * crown_ry, 5.0, 0.16, 4.2, 0.12),
                (0.70 * r_px - jx1 * 0.15, -0.02 * crown_ry, 0.34 * r_px, 0.34 * crown_ry, 5.0, 0.16, 5.1, -0.04),
                (-0.18 * r_px + asym_w * 0.2, -0.14 * crown_ry, 0.42 * r_px, 0.34 * crown_ry, 6.0, 0.14, 2.5, 0.14),
                (0.24 * r_px + asym_w * 0.2, -0.12 * crown_ry, 0.40 * r_px, 0.34 * crown_ry, 6.0, 0.14, 5.7, 0.02),
            )
            best_z = np.full(gx.shape, -1.0, dtype=np.float32)
            best_nx = np.zeros(gx.shape, dtype=np.float32)
            best_ny = np.zeros(gx.shape, dtype=np.float32)
            best_wbias = np.zeros(gx.shape, dtype=np.float32)
            ph_seed = (s2 & 15) * 0.4
            for l_ox, l_oy, l_rx, l_ry, k_f, amp, ph_o, l_b in w_lobes:
                ux = (dx - l_ox) / max(1.4, l_rx)
                uy = (dy_c - l_oy) / max(1.4, l_ry)
                th_l = np.arctan2(uy, ux)
                sc_l = 1.0 + amp * (0.62 * np.cos(k_f * th_l + ph_o + ph_seed) + 0.38 * np.sin((k_f + 2.0) * th_l + ph_o))
                r_eff = np.sqrt(ux * ux + uy * uy) / sc_l - 0.11 * tuft_f
                in_l = r_eff < 1.0
                if not in_l.any():
                    continue
                lz = np.sqrt(np.maximum(0.0, 1.0 - np.minimum(1.0, r_eff * r_eff)))
                better = in_l & (lz > best_z)
                best_z[better] = lz[better]
                best_nx[better] = ux[better]
                best_ny[better] = -uy[better]
                best_wbias[better] = l_b

            # 9-16 discrete wispy hanging weeping frond strands with 30-35% genuine open air gaps!
            # Sparser near center |u_s| < 0.20 so the gnarled trunk & arched boughs clearly show through!
            n_strands = int(np.clip(round(r_px * 0.48), 9, 16))
            y_tip_max = cy0 - 1.5  # STRICT CLAMP: tendrils NEVER hang below trunk base into water!
            in_strand_any = np.zeros(gx.shape, dtype=np.bool_)
            strand_z = np.full(gx.shape, -1.0, dtype=np.float32)
            strand_nd = np.zeros(gx.shape, dtype=np.float32)

            for k_s in range(n_strands):
                hs = ((tid * 2246822519 + k_s * 3266489917) ^ s2) & 0xFFFF
                u_lin = -0.95 + (1.90 * (k_s + 0.5)) / float(n_strands)
                u_jit = (((hs & 15) / 15.0) - 0.5) * (1.1 / float(n_strands))
                u_s = float(np.clip(u_lin + u_jit, -0.96, 0.96))
                # Leave natural arched window near center so gnarled trunk & Y-fork boughs remain visible
                if abs(u_s) < 0.20 and ((hs >> 4) % 3) != 0:
                    continue
                x_start = u_s * r_px * 0.96
                y_start = crown_cy - 0.16 * crown_ry + 0.24 * crown_ry * (u_s * u_s)
                avail_drop = max(2.2, y_tip_max - y_start)
                # Outer tendrils drape lower (72-94%), inner tendrils shorter (48-70%)
                len_frac = (0.72 + 0.22 * (((hs >> 6) & 15) / 15.0)) if abs(u_s) >= 0.28 else (0.48 + 0.22 * (((hs >> 6) & 15) / 15.0))
                y_tip = min(y_tip_max, y_start + avail_drop * len_frac)
                drop_h = max(1.5, y_tip - y_start)
                t_s = (gy - y_start) / drop_h
                in_y_s = (t_s >= 0.0) & (t_s <= 1.0)
                if not in_y_s.any():
                    continue
                # Gentle outward-then-downward parabolic sway
                sway_x = u_s * 0.16 * r_px + ((((hs >> 10) & 7) / 7.0) - 0.5) * 1.4
                x_curve = x_start + sway_x * np.sin(np.clip(t_s, 0.0, 1.0) * math.pi * 0.85)
                # Graceful 1.8-2.8 px fronds tapering to 1.0-1.4 px feathered tips, beaded by leaf tufts
                w_base = 0.92 + 0.52 * (((hs >> 13) & 7) / 7.0)
                w_strand = np.maximum(0.55, w_base * (1.0 - 0.44 * np.clip(t_s, 0.0, 1.0)) + 0.26 * tuft_f)
                on_s = in_y_s & (np.abs(dx - x_curve) <= w_strand)
                if not on_s.any():
                    continue
                # Outer/front strands slightly closer in depth than inner strands
                z_s = float(0.45 + 0.40 * math.sqrt(max(0.05, 1.0 - u_s * u_s * 0.85)))
                better_s = on_s & (z_s > strand_z)
                in_strand_any |= on_s
                strand_z[better_s] = z_s
                # Sunlit silvery-sage on top-left fronds -> cool shaded sage-teal on inner/right fronds
                s_lit = u_s * lx_s * 0.78 + (1.0 - t_s[better_s]) * 0.48 + 0.24 * tuft_f[better_s] + 0.08 - 0.12 * (1.0 - abs(u_s))
                strand_nd[better_s] = s_lit

            in_dome = best_z > 0.16
            inside = in_dome | in_strand_any
            if not inside.any():
                continue
            nz_n = np.where(in_dome & (best_z >= strand_z), np.maximum(0.16, best_z), np.maximum(0.16, strand_z))
            dome_nd = best_nx * lx_s + best_ny * ly_s + np.maximum(0.16, best_z) * lz_s + best_wbias + 0.22 * tuft_f
            rim_hi = in_dome & (best_z < 0.62) & ((best_nx * lx_s + best_ny * ly_s) > 0.26) & (v_h > 0.42)
            dome_nd = np.where(rim_hi, dome_nd + 0.22, dome_nd)
            nd_s = np.where(in_dome & (best_z >= strand_z), dome_nd, strand_nd)
            # Keep hanging fronds in front of back-recess, but allow front-facing gnarled trunk to peek through gaps
            d_surf = np.where(
                in_dome & (best_z >= strand_z),
                d0 - nz_n * (r_m * 0.80) - np.clip(v_h, 0.0, 1.0) * (h_m * 0.40 * sp_c),
                d0 - nz_n * (r_m * 0.45) - np.clip(v_h, 0.0, 1.0) * (h_m * 0.22 * sp_c),
            )

        else:
            # BROADLEAF SPECIES (0: Oak/Beech, 2: Silver Birch, 5: Blossoming Orchard, 6: Copper Beech, 7: Linden/Maple)
            # Studio Ghibli 2-4px aperiodic leaf-tuft clusters + asymmetric multi-bough silhouettes!
            tuft_scale = 2.5 if sp in (2, 5) else 3.0
            tuft_f = _leaf_tuft_field(dx, dy_c, s1, s2, scale_px=tuft_scale)
            jx1 = (((s1 & 15) / 15.0) - 0.5) * 0.24 * r_px
            jy1 = ((((s1 >> 4) & 15) / 15.0) - 0.5) * 0.16 * crown_ry
            jx2 = ((((s1 >> 8) & 15) / 15.0) - 0.5) * 0.22 * r_px
            jy2 = ((((s1 >> 12) & 15) / 15.0) - 0.5) * 0.16 * crown_ry
            asym = ((((s2 >> 6) & 15) / 15.0) - 0.5) * 0.22 * r_px
            ph_s = (s2 & 15) * 0.42

            if sp == 2:
                # 2. SILVER BIRCH: 8 smaller airy feathery leaf sprays (pale curved trunk & V-forks peek cleanly through!)
                lobes = (
                    (asym * 0.45 + jx1 * 0.35, -0.62 * crown_ry + jy1 * 0.25, 0.33 * r_px, 0.29 * crown_ry, 5.0, 0.18, 0.2, 0.24),
                    (-0.48 * r_px + jx2 * 0.25, -0.34 * crown_ry + jy2 * 0.25, 0.32 * r_px, 0.28 * crown_ry, 5.0, 0.18, 1.5, 0.18),
                    (0.46 * r_px + jx1 * 0.25, -0.26 * crown_ry - jy1 * 0.25, 0.31 * r_px, 0.28 * crown_ry, 5.0, 0.18, 2.8, 0.10),
                    (-0.16 * r_px + asym * 0.22, -0.10 * crown_ry, 0.34 * r_px, 0.27 * crown_ry, 5.0, 0.17, 4.1, 0.08),
                    (0.24 * r_px + asym * 0.18, 0.02 * crown_ry + jy1 * 0.2, 0.30 * r_px, 0.26 * crown_ry, 5.0, 0.18, 2.1, -0.02),
                    (-0.56 * r_px + jx1 * 0.20, 0.08 * crown_ry + jy2 * 0.2, 0.28 * r_px, 0.25 * crown_ry, 5.0, 0.18, 3.6, 0.00),
                    (-0.36 * r_px + jx2 * 0.20, 0.34 * crown_ry, 0.29 * r_px, 0.24 * crown_ry, 5.0, 0.18, 5.2, -0.18),
                    (0.38 * r_px + jx1 * 0.20, 0.30 * crown_ry, 0.29 * r_px, 0.24 * crown_ry, 5.0, 0.18, 0.9, -0.22),
                )
            elif sp == 5:
                # 5. BLOSSOMING ORCHARD / CHERRY: 8 airy dappled blossom clusters with open lower V-crotch
                lobes = (
                    (asym * 0.45 + jx1 * 0.3, -0.52 * crown_ry + jy1 * 0.25, 0.40 * r_px, 0.34 * crown_ry, 6.0, 0.16, 0.5, 0.24),
                    (-0.50 * r_px + jx2 * 0.25, -0.26 * crown_ry + jy2 * 0.25, 0.38 * r_px, 0.33 * crown_ry, 6.0, 0.16, 1.8, 0.18),
                    (0.48 * r_px + jx1 * 0.25, -0.20 * crown_ry - jy1 * 0.25, 0.38 * r_px, 0.33 * crown_ry, 6.0, 0.16, 3.1, 0.08),
                    (-0.18 * r_px + asym * 0.2, -0.08 * crown_ry, 0.40 * r_px, 0.34 * crown_ry, 6.0, 0.15, 4.4, 0.10),
                    (0.24 * r_px + asym * 0.2, -0.02 * crown_ry, 0.38 * r_px, 0.32 * crown_ry, 6.0, 0.15, 2.3, 0.00),
                    (-0.62 * r_px + jx1 * 0.2, 0.08 * crown_ry, 0.34 * r_px, 0.30 * crown_ry, 5.0, 0.16, 3.7, -0.04),
                    (-0.44 * r_px + jx2 * 0.2, 0.28 * crown_ry, 0.35 * r_px, 0.28 * crown_ry, 5.0, 0.16, 5.5, -0.22),
                    (0.46 * r_px + jx1 * 0.2, 0.26 * crown_ry, 0.35 * r_px, 0.28 * crown_ry, 5.0, 0.16, 1.1, -0.24),
                )
            elif sp == 7:
                # 7. SWISS LINDEN / MAPLE: 9 asymmetric upright oval-dome leaf-tuft boughs
                lobes = (
                    (asym * 0.38 + jx1 * 0.28, -0.60 * crown_ry + jy1 * 0.25, 0.42 * r_px, 0.36 * crown_ry, 6.0, 0.15, 0.3, 0.26),
                    (-0.44 * r_px + jx2 * 0.25, -0.36 * crown_ry + jy2 * 0.25, 0.40 * r_px, 0.36 * crown_ry, 6.0, 0.15, 1.7, 0.20),
                    (0.44 * r_px + jx1 * 0.25, -0.28 * crown_ry - jy1 * 0.25, 0.39 * r_px, 0.35 * crown_ry, 6.0, 0.15, 3.0, 0.10),
                    (-0.14 * r_px + asym * 0.22, -0.14 * crown_ry, 0.44 * r_px, 0.38 * crown_ry, 6.0, 0.14, 4.3, 0.12),
                    (0.22 * r_px + asym * 0.18, -0.04 * crown_ry, 0.42 * r_px, 0.36 * crown_ry, 6.0, 0.14, 1.4, 0.00),
                    (-0.54 * r_px + jx1 * 0.2, 0.12 * crown_ry, 0.38 * r_px, 0.33 * crown_ry, 5.0, 0.15, 5.4, -0.04),
                    (0.52 * r_px - jx2 * 0.2, 0.16 * crown_ry, 0.38 * r_px, 0.33 * crown_ry, 5.0, 0.15, 0.8, -0.12),
                    (-0.36 * r_px + jx2 * 0.18, 0.36 * crown_ry, 0.35 * r_px, 0.28 * crown_ry, 5.0, 0.15, 2.2, -0.22),
                    (0.36 * r_px + jx1 * 0.18, 0.36 * crown_ry, 0.35 * r_px, 0.28 * crown_ry, 5.0, 0.15, 3.7, -0.24),
                )
            else:
                # 0. SWISS OAK / BEECH & 6. COPPER BEECH: 10 asymmetric varied-radius boughs + clear lower V-crotch for gnarled Y-fork!
                lobes = (
                    (asym * 0.48 + jx1 * 0.30, -0.56 * crown_ry + jy1 * 0.25, 0.44 * r_px, 0.36 * crown_ry, 6.0, 0.15, 0.4, 0.26),
                    (-0.46 * r_px + jx2 * 0.28, -0.34 * crown_ry + jy2 * 0.25, 0.44 * r_px, 0.38 * crown_ry, 6.0, 0.15, 1.7, 0.20),
                    (0.46 * r_px + jx1 * 0.28, -0.24 * crown_ry - jy1 * 0.25, 0.42 * r_px, 0.36 * crown_ry, 6.0, 0.15, 3.0, 0.12),
                    (-0.68 * r_px + jx1 * 0.20, 0.02 * crown_ry + jy2 * 0.20, 0.38 * r_px, 0.34 * crown_ry, 6.0, 0.16, 4.2, 0.06),
                    (0.66 * r_px - jx2 * 0.20, 0.08 * crown_ry + jy1 * 0.20, 0.38 * r_px, 0.34 * crown_ry, 6.0, 0.16, 5.4, -0.06),
                    (-0.18 * r_px + asym * 0.25, -0.14 * crown_ry, 0.44 * r_px, 0.36 * crown_ry, 6.0, 0.14, 1.1, 0.14),
                    (0.24 * r_px + asym * 0.20, -0.04 * crown_ry, 0.42 * r_px, 0.36 * crown_ry, 6.0, 0.14, 2.8, 0.02),
                    (-0.46 * r_px + jx2 * 0.20, 0.30 * crown_ry, 0.36 * r_px, 0.28 * crown_ry, 5.0, 0.16, 2.5, -0.22),
                    (0.44 * r_px + jx1 * 0.20, 0.32 * crown_ry, 0.36 * r_px, 0.28 * crown_ry, 5.0, 0.16, 3.9, -0.26),
                    (-0.08 * r_px + jx1 * 0.16, 0.18 * crown_ry, 0.34 * r_px, 0.26 * crown_ry, 5.0, 0.15, 4.9, -0.10),
                )

            best_z = np.full(gx.shape, -1.0, dtype=np.float32)
            best_nx = np.zeros(gx.shape, dtype=np.float32)
            best_ny = np.zeros(gx.shape, dtype=np.float32)
            best_lobe_bias = np.zeros(gx.shape, dtype=np.float32)
            for l_ox, l_oy, l_rx, l_ry, k_f, amp, ph_o, l_bias in lobes:
                ux = (dx - l_ox) / max(1.4, l_rx)
                uy = (dy_c - l_oy) / max(1.4, l_ry)
                th_l = np.arctan2(uy, ux)
                sc_l = 1.0 + amp * (0.62 * np.cos(k_f * th_l + ph_o + ph_s) + 0.38 * np.sin((k_f + 2.0) * th_l + ph_o * 1.3))
                # Organic 2-4 px leaf-tuft silhouette break-up (kills smooth vector/play-doh outline!)
                r_eff = np.sqrt(ux * ux + uy * uy) / sc_l - 0.11 * tuft_f
                in_l = r_eff < 1.0
                if not in_l.any():
                    continue
                lz = np.sqrt(np.maximum(0.0, 1.0 - np.minimum(1.0, r_eff * r_eff)))
                better = in_l & (lz > best_z)
                best_z[better] = lz[better]
                best_nx[better] = ux[better]
                best_ny[better] = -uy[better]
                best_lobe_bias[better] = l_bias

            inside = best_z > (0.22 if sp == 2 else 0.15)
            if not inside.any():
                continue
            nz_n = best_z
            # Dappled Studio Ghibli leaf-cluster shading (2-4 px coherent sunlit/shaded leaf tufts!)
            nd_s = best_nx * lx_s + best_ny * ly_s + nz_n * lz_s + best_lobe_bias + 0.22 * tuft_f
            rim_hi = inside & (best_z < 0.60) & ((best_nx * lx_s + best_ny * ly_s) > 0.26) & (v_h > 0.38)
            nd_s = np.where(rim_hi, nd_s + 0.24, nd_s)
            nd_s = nd_s - np.clip(0.38 - v_h, 0.0, 0.38) * 0.64
            d_surf = d0 - nz_n * (r_m * 0.82) - np.clip(v_h, 0.0, 1.0) * (h_m * 0.42 * sp_c)
            if sp == 5:
                blossom_leaf_mask = inside & (v_h < 0.40) & (nd_s < 0.24)

        # Clean 5-step cel-shaded tone ramp (tones 0..4)
        tone_idx = np.clip(np.floor((nd_s + 0.12) * 3.05).astype(np.int32), 0, 4)

        sub_z = zbuf[y0_b : y1_b + 1, x0_b : x1_b + 1]
        win = inside & (d_surf < sub_z)
        if not win.any():
            continue

        wy, wx = np.nonzero(win)
        gy_w = y0_b + wy
        gx_w = x0_b + wx
        zbuf[gy_w, gx_w] = d_surf[wy, wx]
        col_out = ramp[tone_idx[wy, wx]]
        # Blossoming orchard: fresh orchard-green leaf tufts tucked under blossom clusters!
        if blossom_leaf_mask is not None:
            is_bl_leaf = blossom_leaf_mask[wy, wx]
            if is_bl_leaf.any():
                col_out = col_out.copy()
                col_out[is_bl_leaf] = np.where(
                    (tone_idx[wy, wx][is_bl_leaf] == 0)[:, None],
                    [42.0, 92.0, 40.0],
                    [58.0, 122.0, 48.0],
                ).astype(np.float32)
        rgb_buf[gy_w, gx_w] = col_out
        mat_buf[gy_w, gx_w] = M_TREE
        obj_buf[gy_w, gx_w] = oid
        norm_buf[gy_w, gx_w, 0] = 0.18
        norm_buf[gy_w, gx_w, 1] = -0.14
        norm_buf[gy_w, gx_w, 2] = 0.96
        shadow_buf[gy_w, gx_w] = False


def render_diorama(
    scene: SceneData,
    camera: IsometricCamera,
    preset_key: str = "day",
    crop_box_lv95: tuple[float, float, float, float] | None = None,
    add_frame: bool = True,
    collect_hit_boxes: bool = False,
    viewport_win: tuple[int, int, int, int] | None = None,
    sun_shadow_override: tuple[np.ndarray, np.ndarray] | np.ndarray | None = None,
    out_depth_buf: dict | None = None,
    plate_title: str | None = None,
    plate_subtitle: str | None = None,
) -> tuple[Image.Image, dict]:
    """Render 100% data-accurate, distinctly drawn 3D isometric 90s pixel-art diorama."""
    preset = PRESETS[preset_key]
    (
        camera,
        active_mask,
        plinth_z,
        W_full,
        H_full,
        shift_x_full,
        shift_y_full,
        r0_g,
        r1_g,
        c0_g,
        c1_g,
    ) = compute_full_canvas_geometry(scene, camera, crop_box_lv95, add_frame)

    if viewport_win is not None:
        vx0, vy0, vx1, vy1 = viewport_win
        W = vx1 - vx0
        H = vy1 - vy0
        shift_x = shift_x_full - vx0
        shift_y = shift_y_full - vy0

        cr_idx, cc_idx = np.meshgrid(
            np.arange(r0_g, r1_g, 8, dtype=np.int32),
            np.arange(c0_g, c1_g, 8, dtype=np.int32),
            indexing="ij",
        )
        ce_g = E_MIN + (cc_idx + 0.5) * GRID_RES
        cn_g = N_MAX - (cr_idx + 0.5) * GRID_RES
        cz_lo = scene.dem[cr_idx, cc_idx] - 4.0
        cz_hi = np.maximum(scene.dem[cr_idx, cc_idx] + scene.chm[cr_idx, cc_idx], scene.bridge_z[cr_idx, cc_idx]) + 36.0
        px_lo, py_lo, _ = camera.project(ce_g, cn_g, cz_lo)
        px_hi, py_hi, _ = camera.project(ce_g, cn_g, cz_hi)
        sx_min = np.minimum(px_lo, px_hi) + shift_x
        sx_max = np.maximum(px_lo, px_hi) + shift_x
        sy_min = np.minimum(py_lo, py_hi) + shift_y
        sy_max = np.maximum(py_lo, py_hi) + shift_y
        hit_coarse = (sx_max >= -48) & (sx_min <= W + 48) & (sy_max >= -64) & (sy_min <= H + 64) & active_mask[cr_idx, cc_idx]
        if hit_coarse.any():
            hr, hc = np.nonzero(hit_coarse)
            r0 = max(r0_g, int(cr_idx[hr.min(), 0]) - 24)
            r1 = min(r1_g, int(cr_idx[hr.max(), 0]) + 32)
            c0 = max(c0_g, int(cc_idx[0, hc.min()]) - 24)
            c1 = min(c1_g, int(cc_idx[0, hc.max()]) + 32)
        else:
            r0, r1, c0, c1 = r0_g, r0_g + 1, c0_g, c0_g + 1
    else:
        vx0, vy0 = 0, 0
        W, H = W_full, H_full
        shift_x, shift_y = shift_x_full, shift_y_full
        r0, r1, c0, c1 = r0_g, r1_g, c0_g, c1_g

    sub_mask = active_mask[r0:r1, c0:c1]
    sub_dem = scene.dem[r0:r1, c0:c1]
    sub_chm = scene.chm[r0:r1, c0:c1]
    sub_sem = scene.sem[r0:r1, c0:c1]
    sub_lake = scene.lake_mask[r0:r1, c0:c1]
    sub_bathy = scene.bathy_z[r0:r1, c0:c1]
    sub_kpoly = scene.kpoly_mask[r0:r1, c0:c1]
    sub_harbor = scene.harbor_obj_mask[r0:r1, c0:c1]

    zbuf = np.full((H, W), 1e9, dtype=np.float32)
    rgb_buf = np.zeros((H, W, 3), dtype=np.float32)
    mat_buf = np.zeros((H, W), dtype=np.uint8)
    obj_buf = np.full((H, W), -1, dtype=np.int32)
    norm_buf = np.zeros((H, W, 3), dtype=np.float32)
    norm_buf[:, :, 2] = 1.0
    shadow_buf = np.zeros((H, W), dtype=np.bool_)

    gy = (np.arange(vy0, vy0 + H, dtype=np.float32) / max(1, H_full - 1))[:, None]
    bg_grad = (1.0 - gy) * np.array(preset.sky_top_rgb) + gy * np.array(preset.sky_bot_rgb)
    bayer_tiled = BAYER_4X4[
        (np.arange(vy0, vy0 + H)[:, None]) % 4,
        (np.arange(vx0, vx0 + W)[None, :]) % 4,
    ]
    rgb_buf[:] = bg_grad[:, None, :]

    if sun_shadow_override is not None:
        if isinstance(sun_shadow_override, tuple):
            sun_shadow_grid, ray_rel_05m = sun_shadow_override
        else:
            sun_shadow_grid, ray_rel_05m = sun_shadow_override, None
    else:
        sun_shadow_grid, ray_rel_05m = compute_shadow_grid(scene, preset.sun_az_deg, preset.sun_alt_deg)
    sub_shadow = sun_shadow_grid[r0:r1, c0:c1]

    s_az = math.radians(preset.sun_az_deg)
    s_alt = math.radians(preset.sun_alt_deg)
    sun_vec = np.array(
        [math.sin(s_az) * math.cos(s_alt), math.cos(s_az) * math.cos(s_alt), math.sin(s_alt)],
        dtype=np.float32,
    )

    # -------------------------------------------------------------------------
    # STAGE 1 (F5): Drop Shadow + Museum-Grade Swiss Molasse & Aquarium Cutaway
    # -------------------------------------------------------------------------
    glob_m = active_mask[r0_g:r1_g, c0_g:c1_g]
    ar_g, ac_g = np.nonzero(glob_m)
    sr_idx, sc_idx = ar_g[::2], ac_g[::2]
    se = E_MIN + (sc_idx + c0_g + 0.5) * GRID_RES + 14.0
    sn = N_MAX - (sr_idx + r0_g + 0.5) * GRID_RES - 12.0
    sx_p, sy_p, _ = camera.project(se, sn, np.full_like(se, plinth_z - 11.0))
    ix_s = np.round(sx_p + shift_x).astype(np.int32)
    iy_s = np.round(sy_p + shift_y).astype(np.int32)
    sh_r_max = max(1, int(round(2.0 * (0.25 / max(0.08, camera.mpp))))) if camera.mpp <= 0.36 else 1
    vs = (ix_s >= 1) & (ix_s < W - sh_r_max - 1) & (iy_s >= 1) & (iy_s < H - sh_r_max - 1)
    ix_s, iy_s = ix_s[vs], iy_s[vs]
    sh_rad = tuple(range(sh_r_max + 1))
    for ox in sh_rad:
        for oy in sh_rad:
            rgb_buf[iy_s + oy, ix_s + ox] = bg_grad[iy_s + oy, :] * 0.58
            mat_buf[iy_s + oy, ix_s + ox] = M_DROP_SHADOW

    eroded_m = ndimage.binary_erosion(glob_m, iterations=2, border_value=0)
    perim = glob_m & (~eroded_m)
    # Smooth perimeter normals (sigma=3.5) eliminate vertical facet moire along curved cliffs
    sm_f = ndimage.gaussian_filter(glob_m.astype(np.float32), sigma=3.5)
    dm_drow, dm_dcol = np.gradient(sm_f)
    out_nx, out_ny = -dm_dcol, dm_drow

    pr, pc = np.nonzero(perim)
    pe = E_MIN + (pc + c0_g + 0.5) * GRID_RES
    pn = N_MAX - (pr + r0_g + 0.5) * GRID_RES
    pz_top = scene.dem[r0_g:r1_g, c0_g:c1_g][pr, pc]
    p_lake = scene.lake_mask[r0_g:r1_g, c0_g:c1_g][pr, pc]
    p_bathy = np.maximum(scene.bathy_z[r0_g:r1_g, c0_g:c1_g][pr, pc], plinth_z + 7.0)
    pnx, pny = out_nx[pr, pc], out_ny[pr, pc]
    plen = np.maximum(np.hypot(pnx, pny), 1e-5)
    pnx /= plen
    pny /= plen

    if viewport_win is not None and len(pe) > 0:
        px_p0, _, _ = camera.project(pe, pn, np.full_like(pe, plinth_z))
        keep_p = ((px_p0 + shift_x) >= -14.0) & ((px_p0 + shift_x) <= (W + 14.0))
        pe, pn, pz_top = pe[keep_p], pn[keep_p], pz_top[keep_p]
        p_lake, p_bathy = p_lake[keep_p], p_bathy[keep_p]
        pnx, pny = pnx[keep_p], pny[keep_p]

    # Scaled horizontal tangent sub-sampling at <=0.36 m/px eliminates vertical column moire!
    if camera.mpp <= 0.36 and len(pe) > 0:
        n_tan = max(2, int(round(0.50 / max(0.08, camera.mpp))))
        tan_offs = np.linspace(-0.25 * (1.0 - 1.0 / n_tan), 0.25 * (1.0 - 1.0 / n_tan), n_tan)
        tx_u = -pny
        ty_u = pnx
        pe = np.concatenate([pe + tx_u * off for off in tan_offs])
        pn = np.concatenate([pn + ty_u * off for off in tan_offs])
        pz_top = np.tile(pz_top, n_tan)
        p_lake = np.tile(p_lake, n_tan)
        p_bathy = np.tile(p_bathy, n_tan)
        pnx = np.tile(pnx, n_tan)
        pny = np.tile(pny, n_tan)

    dz_step = max(0.08, camera.mpp * 0.45)
    max_col_h = float((pz_top - plinth_z).max()) if len(pz_top) else 0.0
    n_zsteps = max(2, int(math.ceil(max_col_h / dz_step)) + 1)
    cut_ox_list = (0, 1)

    for zi in range(n_zsteps):
        z_cur = plinth_z + zi * dz_step
        act = z_cur <= (pz_top + 0.25)
        if not act.any():
            continue
        ce, cn = pe[act], pn[act]
        cz = np.minimum(z_cur, pz_top[act])
        cz_top = pz_top[act]
        c_islake, c_bathy = p_lake[act], p_bathy[act]
        cnx_v, cny_v = pnx[act], pny[act]

        px, py, pdepth = camera.project(ce, cn, cz)
        pdepth += 0.35
        ix = np.round(px + shift_x).astype(np.int32)
        iy = np.round(py + shift_y).astype(np.int32)
        v = (ix >= 1) & (ix < W - 2) & (iy >= 0) & (iy < H - 2)
        if not v.any():
            continue
        ix, iy, pdepth = ix[v], iy[v], pdepth[v]
        cz, cz_top = cz[v], cz_top[v]
        c_islake, c_bathy = c_islake[v], c_bathy[v]
        cnx_v, cny_v, ce_v, cn_v = cnx_v[v], cny_v[v], ce[v], cn[v]

        depth_from_top = cz_top - cz
        above_plinth = cz - plinth_z
        col = np.empty((len(ix), 3), dtype=np.float32)

        # Deterministic world-space geological micro-hash
        gh = (
            (np.floor(ce_v * 2.0).astype(np.int32) * 73856093)
            ^ (np.floor(cn_v * 2.0).astype(np.int32) * 19349663)
            ^ (np.floor(cz * 2.5).astype(np.int32) * 83492791)
        ) & 0xFF

        # 1. Continuous Swiss Upper Freshwater Molasse Sandstone & Nagelfluh Bedrock for ALL columns
        # (NEVER overwrite below c_bathy with flat grey -> eliminates detail-plate vertical notches!)
        geo_warp = (
            3.2 * np.sin(ce_v * 0.0055 + cn_v * 0.0031)
            + 1.6 * np.cos(ce_v * 0.013 - cn_v * 0.0095)
            + 0.7 * np.sin(ce_v * 0.031 + cn_v * 0.024)
        )
        z_bed = cz + geo_warp
        bed_val = 0.50 * np.sin(z_bed * 0.28) + 0.30 * np.sin(z_bed * 0.71 + 1.3) + 0.20 * np.cos(z_bed * 1.45 - 0.6)
        bed_dith = bed_val + ((gh.astype(np.float32) / 255.0) - 0.5) * 0.14
        col[:] = [114.0, 110.0, 102.0]  # Cool grey-taupe marl
        col[bed_dith > 0.18] = [146.0, 132.0, 110.0]   # Warm buff Molasse sandstone
        col[bed_dith > 0.52] = [158.0, 138.0, 104.0]   # Weathered ochre sandstone
        col[bed_dith < -0.34] = [94.0, 88.0, 80.0]     # Deep shale-silt bed
        col[gh < 22] *= 0.92                            # Subtle natural sandstone mineral flecks

        # Distinguish genuine deep Lake Zurich water from ultra-thin 2-40cm shore coves (notch fix!)
        has_real_water = c_islake & ((LAKE_SURFACE_Z - c_bathy) >= 0.45)
        is_land_col = ~has_real_water

        # 2. Dithered Wurm Glacial Moraine Gravel with Nagelfluh cobbles/pebbles (3.0 .. 12.0m)
        moraine_bot = 11.8 + ((gh.astype(np.float32) / 255.0) - 0.5) * 3.0
        topsoil_bot = 2.6 + 0.6 * np.sin(ce_v * 0.18 + cn_v * 0.15)
        in_moraine = is_land_col & (depth_from_top >= topsoil_bot) & (depth_from_top < moraine_bot)
        if in_moraine.any():
            col[in_moraine] = [156.0, 136.0, 102.0]
            col[in_moraine & (gh < 34)] = [184.0, 176.0, 158.0]   # Limestone cobbles
            col[in_moraine & (gh > 224)] = [96.0, 92.0, 86.0]     # Dark alpine granite pebbles

        # 3. Rich Dark Humus Topsoil & Overhanging Lush Grass Turf Lip
        turf_bot = 0.85 + 0.35 * np.sin(ce_v * 0.35 + cn_v * 0.28)
        in_humus = is_land_col & (depth_from_top >= turf_bot) & (depth_from_top < topsoil_bot)
        if in_humus.any():
            col[in_humus] = [92.0, 68.0, 48.0]
            col[in_humus & (gh < 70)] = [76.0, 56.0, 40.0]
        in_turf = is_land_col & (depth_from_top < turf_bot)
        if in_turf.any():
            col[in_turf] = [74.0, 128.0, 54.0]
            col[in_turf & (depth_from_top > (turf_bot - 0.25))] = [54.0, 96.0, 42.0]

        # 4. Tactile 1.6m Pebble & Silt Lakebed Lining directly below c_bathy (flows into Molasse below!)
        in_bed_lining = has_real_water & (cz < c_bathy) & ((c_bathy - cz) <= 1.6)
        if in_bed_lining.any():
            col[in_bed_lining] = [128.0, 122.0, 108.0]
            col[in_bed_lining & (gh < 75)] = [98.0, 94.0, 86.0]
            col[in_bed_lining & (gh > 192)] = [148.0, 140.0, 124.0]

        # 5. Lake Zurich Translucent Aquarium Cutaway Glass Face (meniscus rim + diagonal caustic sheen!)
        in_w = has_real_water & (cz >= c_bathy)
        if in_w.any():
            w_d = np.clip(LAKE_SURFACE_Z - cz[in_w], 0.0, 55.0)
            t_w1 = np.clip(w_d / 12.0, 0.0, 1.0)[:, None]
            t_w2 = np.clip((w_d - 12.0) / 30.0, 0.0, 1.0)[:, None]
            w_aq = (1.0 - t_w1) * np.array([56.0, 132.0, 126.0], dtype=np.float32) + t_w1 * (
                (1.0 - t_w2) * np.array([30.0, 88.0, 104.0], dtype=np.float32)
                + t_w2 * np.array([16.0, 46.0, 72.0], dtype=np.float32)
            )
            # Subtle diagonal acrylic glass sheen & underwater caustic rays
            sheen_m = ((ce_v[in_w] * 0.18 + cn_v[in_w] * 0.18 + cz[in_w] * 0.75) % 24.0) < 3.2
            sheen_att = np.exp(-w_d / 14.0)
            if sheen_m.any():
                w_aq[sheen_m] += sheen_att[sheen_m, None] * np.array([14.0, 20.0, 18.0], dtype=np.float32)
            # Bottom lakebed turquoise-sand interface glow
            near_bed = (cz[in_w] - c_bathy[in_w]) < 1.2
            if near_bed.any():
                w_aq[near_bed] = 0.65 * w_aq[near_bed] + 0.35 * np.array([48.0, 92.0, 86.0], dtype=np.float32)
            # Crisp meniscus surface rim & bright surface glint
            w_aq = np.where((w_d < 0.75)[:, None], [162.0, 214.0, 212.0], w_aq)
            w_aq = np.where((w_d < 0.28)[:, None], [208.0, 236.0, 234.0], w_aq)
            col[in_w] = np.clip(w_aq, 0.0, 250.0)

        # 6. Bevelled Dark-Slate Museum Base Plinth (frames the entire diorama like an architectural model!)
        col[(above_plinth >= 2.4) & (above_plinth < 3.2)] = [64.0, 68.0, 78.0]
        col[above_plinth < 2.4] = [42.0, 44.0, 52.0]

        c_mat = np.where(in_w, M_CUTAWAY_WATER, M_CUTAWAY_EARTH).astype(np.uint8)
        order = np.argsort(pdepth)[::-1]
        ix, iy, pdepth = ix[order], iy[order], pdepth[order]
        col, c_mat, cnx_v, cny_v = col[order], c_mat[order], cnx_v[order], cny_v[order]

        for ox in cut_ox_list:
            for oy in (0, 1):
                tx = ix + ox
                ty = iy + oy
                db = pdepth + 0.04 * (abs(ox) + oy)
                win = db < zbuf[ty, tx]
                zbuf[ty[win], tx[win]] = db[win]
                rgb_buf[ty[win], tx[win]] = col[win]
                mat_buf[ty[win], tx[win]] = c_mat[win]
                obj_buf[ty[win], tx[win]] = 0
                norm_buf[ty[win], tx[win], 0] = cnx_v[win]
                norm_buf[ty[win], tx[win], 1] = cny_v[win]
                norm_buf[ty[win], tx[win], 2] = 0.12

    # Free all Stage 1 full-municipality intermediates (~700-850 MiB Anon) before Stage 2
    del glob_m, ar_g, ac_g, sr_idx, sc_idx, se, sn, sx_p, sy_p, ix_s, iy_s, vs
    del eroded_m, perim, sm_f, dm_drow, dm_dcol, out_nx, out_ny
    del pr, pc, pe, pn, pz_top, p_lake, p_bathy, pnx, pny
    _gc.collect()

    # -------------------------------------------------------------------------
    # STAGE 2: 100% Drawn 90s Pixel-Art Ground, Fields, Streets, Crosswalks & SBB Rail!
    # -------------------------------------------------------------------------
    ground_sub_res = 0.125 if camera.mpp <= 0.16 else (0.25 if camera.mpp <= 0.36 else 0.50)
    if sub_mask.any():
        gr05, gc05 = np.nonzero(sub_mask)
        ge05 = E_MIN + (gc05 + c0 + 0.5) * GRID_RES
        gn05 = N_MAX - (gr05 + r0 + 0.5) * GRID_RES
        px05, py05, _ = camera.project(ge05, gn05, sub_dem[gr05, gc05])
        in_w05 = (
            ((px05 + shift_x) >= -12.0)
            & ((px05 + shift_x) <= (W + 12.0))
            & ((py05 + shift_y) >= -36.0)
            & ((py05 + shift_y) <= (H + 18.0))
        )
        gr05, gc05 = gr05[in_w05], gc05[in_w05]
        ge05, gn05 = ge05[in_w05], gn05[in_w05]

        if len(gr05) > 0:
            chunk_05 = 32768 if ground_sub_res == 0.125 else 131072
            for chunk_idx, g_off in enumerate(range(0, len(gr05), chunk_05)):
                gr05_c = gr05[g_off : g_off + chunk_05]
                gc05_c = gc05[g_off : g_off + chunk_05]
                ge05_c = ge05[g_off : g_off + chunk_05]
                gn05_c = gn05[g_off : g_off + chunk_05]
                if ground_sub_res == 0.125:
                    offs_g = (-0.1875, -0.0625, 0.0625, 0.1875)
                    gr = np.tile(gr05_c, 16)
                    gc = np.tile(gc05_c, 16)
                    ge = np.concatenate([ge05_c + de for de in offs_g for _ in offs_g])
                    gn = np.concatenate([gn05_c + dn for _ in offs_g for dn in offs_g])
                elif ground_sub_res == 0.25:
                    gr = np.tile(gr05_c, 4)
                    gc = np.tile(gc05_c, 4)
                    ge = np.concatenate([ge05_c - 0.125, ge05_c + 0.125, ge05_c - 0.125, ge05_c + 0.125])
                    gn = np.concatenate([gn05_c + 0.125, gn05_c + 0.125, gn05_c - 0.125, gn05_c - 0.125])
                else:
                    gr, gc, ge, gn = gr05_c, gc05_c, ge05_c, gn05_c

                gsem = sub_sem[gr, gc]
                glake = sub_lake[gr, gc]
                gkpoly = sub_kpoly[gr, gc]
                gharbor = sub_harbor[gr, gc]
                gsh = sub_shadow[gr, gc]
                gcliff = scene.steep_cliff_05m[r0:r1, c0:c1][gr, gc]
                xwalk = scene.crosswalk_mask[r0:r1, c0:c1][gr, gc]

                if ground_sub_res == 0.125:
                    gz = _sample_bilinear_05m(sub_dem, ge, gn, r0=r0, c0=c0)
                    gz_sm = _sample_bilinear_05m(scene.dem_smooth_05m[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0)
                    gbathy = _sample_bilinear_05m(sub_bathy, ge, gn, r0=r0, c0=c0)
                    gnx = _sample_bilinear_05m(scene.terr_nx[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0)
                    gny = _sample_bilinear_05m(scene.terr_ny[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0)
                    gnz = _sample_bilinear_05m(scene.terr_nz[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0)
                    rd_dist = _sample_bilinear_05m(scene.road_dist[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0, max_jump=4.0)
                    rd_along = _sample_bilinear_05m(scene.road_along[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0, max_jump=3.0)
                    rd_hw = _sample_bilinear_05m(scene.road_hw[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0, max_jump=3.5)
                    rl_dist = _sample_bilinear_05m(scene.rail_dist[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0, max_jump=4.0)
                    rl_along = _sample_bilinear_05m(scene.rail_along[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0, max_jump=3.0)
                    xwalk = _sample_bilinear_05m(scene.crosswalk_sdf_05m[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0) >= 0.5
                    dist_lake_v = _sample_bilinear_05m(scene.dist_shore_05m[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0)
                    lake_sdf_v = _sample_bilinear_05m(scene.lake_sdf_05m[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0)
                    glake = (lake_sdf_v >= 0.50) & (gsem != G_POOL)
                    pier_sdf_v = _sample_bilinear_05m(scene.pier_sdf_05m[r0:r1, c0:c1], ge, gn, r0=r0, c0=c0)
                    gharbor = glake & (pier_sdf_v >= 0.48)
                    pier_h_v = scene.pier_deck_h_05m[r0:r1, c0:c1][gr, gc]
                else:
                    gz = sub_dem[gr, gc].copy()
                    gz_sm = None
                    gbathy = sub_bathy[gr, gc]
                    gnx = scene.terr_nx[r0:r1, c0:c1][gr, gc].astype(np.float32)
                    gny = scene.terr_ny[r0:r1, c0:c1][gr, gc].astype(np.float32)
                    gnz = scene.terr_nz[r0:r1, c0:c1][gr, gc].astype(np.float32)
                    rd_dist = scene.road_dist[r0:r1, c0:c1][gr, gc].astype(np.float32)
                    rd_along = scene.road_along[r0:r1, c0:c1][gr, gc]
                    rd_hw = scene.road_hw[r0:r1, c0:c1][gr, gc].astype(np.float32)
                    rl_dist = scene.rail_dist[r0:r1, c0:c1][gr, gc].astype(np.float32)
                    rl_along = scene.rail_along[r0:r1, c0:c1][gr, gc]
                    dist_lake_v = None
                    lake_sdf_v = None
                    pier_sdf_v = None
                    pier_h_v = None

                raw_ortho = sample_ortho_25cm(scene, ge, gn)
                gcol, gmat, gz, g_seebad_pool = _shade_drawn_ground_90s(
                    scene, ge, gn, gz, gsem, glake, gbathy, gharbor, raw_ortho,
                    rd_dist, rd_along, rd_hw, rl_dist, rl_along, xwalk,
                    gnx, gny, gnz, sub_chm[gr, gc],
                    preset_key=preset_key,
                    mpp=camera.mpp,
                    dist_lake=dist_lake_v,
                    gz_smooth=gz_sm,
                    pier_sdf=pier_sdf_v,
                    pier_h_val=pier_h_v,
                    lake_sdf=lake_sdf_v,
                )

                out_k = (~gkpoly) & (~glake)
                if out_k.any():
                    gr_m = gcol[out_k].mean(axis=1, keepdims=True)
                    gcol[out_k] = 0.78 * gcol[out_k] + 0.22 * gr_m

                gx_p, gy_p, gdepth = camera.project(ge, gn, gz)
                gix = np.round(gx_p + shift_x).astype(np.int32)
                giy = np.round(gy_p + shift_y).astype(np.int32)
                gv = (gix >= 0) & (gix < W - 1) & (giy >= 0) & (giy < H - 1)

                if gv.any():
                    gix, giy, gdepth = gix[gv], giy[gv], gdepth[gv]
                    gcol, gmat, gsh, glake_v = gcol[gv], gmat[gv], gsh[gv], glake[gv]
                    gcliff_v = gcliff[gv]
                    g_sb_v = g_seebad_pool[gv]
                    gnx, gny, gnz = gnx[gv], gny[gv], gnz[gv]
                    gz_v = gz[gv]
                    gsem_v = gsem[gv]
                    lake_sdf_gv = lake_sdf_v[gv] if lake_sdf_v is not None else None

                    order = np.argsort(gdepth)[::-1]
                    gix, giy, gdepth = gix[order], giy[order], gdepth[order]
                    gcol, gmat, gsh, glake_v = gcol[order], gmat[order], gsh[order], glake_v[order]
                    gcliff_v = gcliff_v[order]
                    g_sb_v = g_sb_v[order]
                    gnx, gny, gnz = gnx[order], gny[order], gnz[order]
                    gz_v = gz_v[order]
                    gsem_v = gsem_v[order]
                    if lake_sdf_gv is not None:
                        lake_sdf_gv = lake_sdf_gv[order]

                    for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                        tx = np.clip(gix + ox, 0, W - 1)
                        ty = np.clip(giy + oy, 0, H - 1)
                        d_b = gdepth + (0.08 if (ox or oy) else 0.0)
                        win = d_b <= zbuf[ty, tx]
                        zbuf[ty[win], tx[win]] = d_b[win]
                        rgb_buf[ty[win], tx[win]] = gcol[win]
                        mat_buf[ty[win], tx[win]] = gmat[win]
                        obj_buf[ty[win], tx[win]] = np.where(g_sb_v[win], 259999, np.where(gmat[win] == M_HARBOR_OBJ, 250000, 0))
                        shadow_buf[ty[win], tx[win]] = gsh[win]
                        norm_buf[ty[win], tx[win], 0] = gnx[win]
                        norm_buf[ty[win], tx[win], 1] = gny[win]
                        norm_buf[ty[win], tx[win], 2] = gnz[win]

                    # v13 M1B: Solid vertical pier skirt extrusion down to waterline (gives all Seebad jetties & piers crisp 3D thickness!)
                    is_pier_px = gmat == M_HARBOR_OBJ
                    if is_pier_px.any():
                        pi_s = np.nonzero(is_pier_px)[0]
                        p_ix = gix[pi_s]
                        p_iy = giy[pi_s]
                        p_d = gdepth[pi_s]
                        p_col = (gcol[pi_s] * 0.68).astype(np.float32)
                        skirt_px = max(4, int(round(0.90 / max(0.08, camera.mpp))))
                        for oy_sk in range(1, skirt_px + 1):
                            ty_sk = p_iy + oy_sk
                            v_sk = ty_sk < H
                            if not v_sk.any():
                                continue
                            d_sk = p_d[v_sk] + 0.02 * oy_sk
                            for ox_sk in (0, 1):
                                tx_sk = np.clip(p_ix[v_sk] + ox_sk, 0, W - 1)
                                win_sk = d_sk < zbuf[ty_sk[v_sk], tx_sk]
                                if win_sk.any():
                                    wy_sk, wx_sk = ty_sk[v_sk][win_sk], tx_sk[win_sk]
                                    zbuf[wy_sk, wx_sk] = d_sk[win_sk]
                                    rgb_buf[wy_sk, wx_sk] = p_col[v_sk][win_sk]
                                    mat_buf[wy_sk, wx_sk] = M_HARBOR_OBJ
                                    obj_buf[wy_sk, wx_sk] = 250000
                                    shadow_buf[wy_sk, wx_sk] = False
                                    norm_buf[wy_sk, wx_sk, 0] = 0.40
                                    norm_buf[wy_sk, wx_sk, 1] = -0.40
                                    norm_buf[wy_sk, wx_sk, 2] = 0.82

                    # v13 M1B Iter2: Systemic Continuous Shoreline Bank Skirt (kills 100% of dark 0.5m M_BG shoreline holes!)
                    if lake_sdf_gv is not None:
                        is_shore_lip = (~glake_v) & (lake_sdf_gv >= 0.08) & (gz_v > (LAKE_SURFACE_Z + 0.05))
                    else:
                        is_shore_lip = np.zeros(len(gix), dtype=np.bool_)
                    if is_shore_lip.any():
                        sh_i = np.nonzero(is_shore_lip)[0]
                        sh_ix = gix[sh_i]
                        sh_iy = giy[sh_i]
                        sh_d = gdepth[sh_i]
                        sh_sh = gsh[sh_i]
                        sh_paved = np.isin(
                            gsem_v[sh_i],
                            [G_FOOTPATH, G_PLATFORM_PIER, G_STREET_MAIN, G_STREET_MINOR, G_PARKING],
                        )
                        sh_base_col = (gcol[sh_i] * 0.80).astype(np.float32)
                        max_sh_px = max(14, int(round(2.6 / max(0.08, camera.mpp))))
                        drop_px = np.clip(
                            np.ceil((gz_v[sh_i] - LAKE_SURFACE_Z) * 0.90 / max(0.08, camera.mpp)).astype(np.int32) + 2,
                            2,
                            max_sh_px,
                        )
                        earth_olive = np.array([74.0, 96.0, 58.0], dtype=np.float32)
                        for oy_sk in range(1, max_sh_px + 1):
                            act_sh = drop_px >= oy_sk
                            if not act_sh.any():
                                continue
                            ai_sh = np.nonzero(act_sh)[0]
                            ty_sk = sh_iy[ai_sh] + oy_sk
                            v_sk = ty_sk < H
                            if not v_sk.any():
                                continue
                            ai_sh = ai_sh[v_sk]
                            ty_sk = ty_sk[v_sk]
                            d_sk = sh_d[ai_sh] + 0.03 + 0.015 * oy_sk
                            t_blend = min(0.55, 0.08 * oy_sk)
                            nat_col = (1.0 - t_blend) * sh_base_col[ai_sh] + t_blend * earth_olive
                            stone_c = np.array([166.0, 162.0, 152.0] if oy_sk <= 2 else [138.0, 134.0, 124.0], dtype=np.float32)
                            col_sk = np.where(sh_paved[ai_sh][:, None], stone_c, nat_col).astype(np.float32)
                            for ox_sk in (0, 1):
                                tx_sk = np.clip(sh_ix[ai_sh] + ox_sk, 0, W - 1)
                                win_sk = d_sk < zbuf[ty_sk, tx_sk]
                                if win_sk.any():
                                    wy_sk, wx_sk = ty_sk[win_sk], tx_sk[win_sk]
                                    zbuf[wy_sk, wx_sk] = d_sk[win_sk]
                                    rgb_buf[wy_sk, wx_sk] = col_sk[win_sk]
                                    mat_buf[wy_sk, wx_sk] = M_GROUND
                                    obj_buf[wy_sk, wx_sk] = 0
                                    shadow_buf[wy_sk, wx_sk] = sh_sh[ai_sh][win_sk]
                                    norm_buf[wy_sk, wx_sk, 0] = 0.0
                                    norm_buf[wy_sk, wx_sk, 1] = 0.0
                                    norm_buf[wy_sk, wx_sk, 2] = 0.92

                    # F14c + v12: Ashlar Jura-Stone Retaining Walls ONLY on sustained cliffs (gcliff_v & s_nz < 0.64),
                    # eliminating jagged white/grey retaining-wall streaks on grassy roadside embankments!
                    steep = (gnz < 0.88) & (~glake_v) & (~is_shore_lip)
                    if steep.any():
                        si = np.nonzero(steep)[0]
                        s_ix = gix[si]
                        s_iy = giy[si]
                        s_d = gdepth[si]
                        s_sh = gsh[si]
                        s_nx, s_ny, s_nz = gnx[si], gny[si], gnz[si]
                        is_rwall = gcliff_v[si] & (s_nz < 0.64)
                        s_col = np.where(is_rwall[:, None], [164.0, 158.0, 146.0], gcol[si] * 0.90).astype(np.float32)
                        rw_scale = 0.25 / max(0.08, camera.mpp)
                        rw_max_oy = max(10, int(round(10 * rw_scale)))
                        max_drop = np.clip(np.round((1.0 - s_nz) * 24.0 * rw_scale).astype(np.int32), 2, rw_max_oy)
                        c_step = max(3, int(round(3 * rw_scale)))
                        for oy in range(2, rw_max_oy + 1):
                            act = max_drop >= oy
                            if not act.any():
                                continue
                            ai = np.nonzero(act)[0]
                            course_id = (oy - 2) // c_step
                            is_h_mortar = ((oy - 2) % c_step) == (c_step - 1)
                            for ox in (0, 1):
                                tx = np.clip(s_ix[ai] + ox, 0, W - 1)
                                ty = np.clip(s_iy[ai] + oy, 0, H - 1)
                                d_b = s_d[ai] + 0.16 + oy * 0.03
                                win = d_b <= zbuf[ty, tx]
                                if win.any():
                                    wy, wx = ty[win], tx[win]
                                    w_ai = ai[win]
                                    zbuf[wy, wx] = d_b[win]
                                    c_out = s_col[w_ai].copy()
                                    rw_w = is_rwall[w_ai]
                                    if rw_w.any():
                                        # Global x/y coordinates for seamless staggered ashlar blocks across macro-tiles!
                                        gwx = wx[rw_w] + vx0
                                        gwy = wy[rw_w] + vy0
                                        if oy == 2:
                                            c_out[rw_w] = [188.0, 182.0, 170.0]  # Sunlit dressed Jura-limestone coping slab
                                        else:
                                            blk_x = gwx + (course_id & 1) * 3
                                            is_v_mortar = (blk_x % 6) == 0
                                            bhash = (((blk_x // 6) * 73856093) ^ (course_id * 19349663) ^ (gwy // 12)) & 31
                                            c_rw = c_out[rw_w] + ((bhash.astype(np.float32) - 16.0) * 0.65)[:, None]
                                            if is_h_mortar:
                                                c_rw *= 0.78
                                            else:
                                                c_rw[is_v_mortar] *= 0.78
                                            c_out[rw_w] = np.clip(c_rw, 24.0, 235.0)
                                        # Sparse trailing green ivy clusters draping from top coping cap (oy in 2..5)
                                        if oy <= 5:
                                            ivy_h = (((wx + vx0) >> 1) * 83492791 ^ ((s_iy[w_ai] + vy0) >> 2) * 19349663) & 255
                                            is_ivy = rw_w & (ivy_h < 16) & (oy <= (2 + (ivy_h & 3)))
                                            if is_ivy.any():
                                                c_out[is_ivy] = [68.0, 122.0, 52.0] if oy == 2 else ([44.0, 86.0, 38.0] if oy >= 4 else [52.0, 98.0, 44.0])
                                    rgb_buf[wy, wx] = c_out
                                    mat_buf[wy, wx] = M_GROUND
                                    obj_buf[wy, wx] = 0
                                    shadow_buf[wy, wx] = np.where(rw_w, False, s_sh[w_ai])
                                    norm_buf[wy, wx, 0] = s_nx[w_ai]
                                    norm_buf[wy, wx, 1] = s_ny[w_ai]
                                    norm_buf[wy, wx, 2] = np.maximum(0.58, s_nz[w_ai])
                if (chunk_idx & 7) == 7:
                    _evict_mmap_rss(scene.ortho_hr)
            _evict_mmap_rss(scene.ortho_hr)

    # -------------------------------------------------------------------------
    # STAGE 2.5: True 3D Elevated Viaducts, Piers, SBB Catenary Wires & Bahnhof Canopies!
    # -------------------------------------------------------------------------
    _render_elevated_bridges_and_rail_portals(
        scene, camera, shift_x, shift_y, W, H, r0, r1, c0, c1,
        sub_mask, sub_dem, sub_shadow,
        zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
        crop_box_lv95,
        active_mask=active_mask,
        is_night=preset.is_night,
    )

    # -------------------------------------------------------------------------
    # STAGE 2.6: Clipped 3D Sports, Enclosures, Parked Cars, Streetlamps & Micro-Props!
    # -------------------------------------------------------------------------
    _render_3d_sports_details(
        scene, camera, shift_x, shift_y, W, H,
        zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
        preset.is_night, crop_box_lv95,
        active_mask=active_mask,
        preset_key=preset_key,
    )

    # -------------------------------------------------------------------------
    # STAGE 2.7: Crisp 3D Timber Piers, Moored Boats (40 open-water) & Seebad Beach Props!
    # -------------------------------------------------------------------------
    _render_3d_harbor_and_boats(
        scene, camera, shift_x, shift_y, W, H, r0, r1, c0, c1,
        sub_mask, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
        preset.is_night, crop_box_lv95,
        active_mask=active_mask,
    )

    # -------------------------------------------------------------------------
    # STAGE 3: All 1,890 Real 3D LOD2 Buildings — F7/F8/F11/F12/F13 Master Craft!
    # -------------------------------------------------------------------------
    verts = scene.verts
    norms = scene.normals
    bidx = scene.bldg_idx
    stype = scene.surf_type
    t_dir_bin = scene.tri_dir_bin
    t_tw_x = scene.tri_tw_x
    t_tw_y = scene.tri_tw_y
    t_u_verts = scene.tri_u_verts
    orig_tri_idx = np.arange(len(verts), dtype=np.int32)

    bldg_z0 = np.array([b["z_ground"] for b in scene.buildings], dtype=np.float32)
    bldg_z1 = np.array([b["z_roof"] for b in scene.buildings], dtype=np.float32)
    bldg_e0 = np.array([b["e"] for b in scene.buildings], dtype=np.float32)
    bldg_n0 = np.array([b["n"] for b in scene.buildings], dtype=np.float32)
    bldg_fw = np.array([b["footprint_w"] for b in scene.buildings], dtype=np.float32)
    bldg_wall_rgb = scene.bldg_wall_rgb
    bldg_style = scene.bldg_style
    bldg_is_shopfront = scene.bldg_is_shopfront
    bldg_is_riegelhaus = scene.bldg_is_riegelhaus
    bldg_is_mauer = np.array([b["objektart"] == "Mauer gross" for b in scene.buildings], dtype=np.bool_)
    lm = scene.lm_idx

    id_lindt_hoc = lm.get("lindt_hoc", -1)
    id_lindt_chim = lm.get("lindt_chimney", -1)
    id_lindt_main = lm.get("lindt_main", -1)
    id_lindt_s1473 = lm.get("lindt_south_1473", -1)
    id_lindt_s1720 = lm.get("lindt_south_1720", -1)
    id_ref_kirche = lm.get("ref_kirche", -1)
    id_st_el_twr = lm.get("st_elisabeth_twr", -1)
    id_st_el_nave = lm.get("st_elisabeth_nave", -1)
    id_bend_pier = lm.get("bendlikon_pier", -1)
    id_bend_pav = lm.get("bendlikon_pavilion", -1)
    id_barn_1490 = lm.get("dorf_barn_1490", -1)
    id_barn_1726 = lm.get("dorf_barn_1726", -1)
    id_nav_1582 = lm.get("villa_naville_1582", -1)
    id_nav_1695 = lm.get("villa_naville_1695", -1)
    id_sch_981 = lm.get("schooren_981", -1)
    id_sch_1823 = lm.get("schooren_1823", -1)
    id_bhf_stn = lm.get("bahnhof_station", -1)
    id_gem_main = lm.get("gemeindehaus_main", -1)
    id_gem_wing = lm.get("gemeindehaus_wing", -1)
    id_cfm_1033 = lm.get("cf_meyer_haus", -1)
    id_cfm_1722 = lm.get("cf_meyer_pin_villa", -1)
    san_ids_arr = np.array(
        [lm.get(k, -1) for k in ("sanatorium_483", "sanatorium_633", "sanatorium_521", "sanatorium_853", "sanatorium_655", "sanatorium_81")],
        dtype=np.int32,
    )
    seebad_ids_arr = np.array(
        [lm.get(k, -1) for k in ("seebad_bathhouse", "seebad_kiosk", "seebad_south")],
        dtype=np.int32,
    )
    id_lindt_brick_n = lm.get("lindt_brick_n", -1)
    id_lindt_brick_s = lm.get("lindt_brick_s", -1)
    id_gotisch_hus = lm.get("gotisch_hus", -1)
    id_schul_dorf = lm.get("schulhaus_dorfstr", -1)
    id_chez_fritz = lm.get("chez_fritz", -1)
    id_chez_fritz_pav = lm.get("chez_fritz_pavilion", -1)
    id_schul_al_868 = lm.get("schulhaus_alteland_868", -1)
    id_schul_al_437 = lm.get("schulhaus_alteland_437", -1)
    id_hb_main = lm.get("hallenbad_main_1835", -1)
    id_hb_pool = lm.get("hallenbad_pool_1448", -1)
    id_hb_entry = lm.get("hallenbad_entry_1628", -1)
    id_broel_manor = lm.get("broelberg_manor_979", -1)
    id_broel_temp = lm.get("broelberg_tempelchen_1074", -1)
    id_spin_villa = lm.get("spinnergut_villa_1601", -1)
    id_spin_pav = lm.get("spinnergut_pav_1132", -1)
    id_tc_club = lm.get("tc_clubhouse_1287", -1)
    id_stock_807 = lm.get("stockengut_barn_807", -1)
    id_stock_91 = lm.get("stockengut_mutterkuhstall_91", -1)
    id_stock_77 = lm.get("stockengut_barn_77", -1)
    id_stock_silo_1 = lm.get("stockengut_silo_1135", -1)
    id_stock_silo_2 = lm.get("stockengut_silo_1174", -1)
    id_san_gh_225 = lm.get("sanatorium_gh_225", -1)
    id_san_gh_886 = lm.get("sanatorium_gh_886", -1)
    id_san_633 = lm.get("sanatorium_633", -1)
    id_san_521 = lm.get("sanatorium_521", -1)
    id_san_81 = lm.get("sanatorium_81", -1)
    id_hafenbeiz_243 = lm.get("moenchhof_hafenbeiz_243", -1)
    hafenbeiz_ids_arr = np.array([id_hafenbeiz_243, lm.get("moenchhof_hafenbeiz_843", -1)], dtype=np.int32)
    moenchhof_villas_arr = np.array(
        [lm.get(k, -1) for k in ("moenchhof_villa_727", "moenchhof_villa_303", "moenchhof_villa_527", "moenchhof_villa_890", "moenchhof_villa_781")],
        dtype=np.int32,
    )
    morfanlage_villas_arr = np.array([lm.get("morfanlage_villa_771", -1), lm.get("morfanlage_villa_423", -1)], dtype=np.int32)
    id_mh_bar = lm.get("moenchhof_boat_825", -1)
    lakeside_boats_arr = np.array(
        [lm.get(k, -1) for k in (
            "moenchhof_boat_25", "moenchhof_boat_825", "morfanlage_boat_42", "morfanlage_boat_379",
        )],
        dtype=np.int32,
    )
    id_sulzergut_chalet = lm.get("sulzergut_villa_1617", -1)
    id_sulzergut_1338 = lm.get("sulzergut_villa_1338", -1)
    broel_outb_arr = np.array([lm.get("broelberg_gardener_1678", -1), lm.get("broelberg_outb_1332", -1)], dtype=np.int32)
    stock_barns_arr = np.array([id_stock_807, id_stock_91], dtype=np.int32)
    stock_houses_arr = np.array([lm.get("stockengut_house_279", -1), lm.get("stockengut_house_574", -1)], dtype=np.int32)
    stock_roof_arr = np.array(
        [id_stock_77, lm.get("stockengut_house_279", -1), lm.get("stockengut_house_574", -1)],
        dtype=np.int32,
    )  # M3.5: id_stock_807 excluded to strictly preserve its real DOP10 solar-panel barn roof!
    gem_all_arr = np.array([id_gem_main, id_gem_wing, id_schul_al_868, id_schul_al_437], dtype=np.int32)
    san_hist_arr = np.array([id_san_633, id_san_81], dtype=np.int32)
    san_mod_arr = np.array([id_san_521, lm.get("sanatorium_483", -1), lm.get("sanatorium_853", -1), lm.get("sanatorium_655", -1)], dtype=np.int32)

    if crop_box_lv95 is not None:
        e0, n0, e1, n1 = crop_box_lv95
        be_tri, bn_tri = bldg_e0[bidx], bldg_n0[bidx]
        in_crop = (be_tri >= e0 + 2) & (be_tri <= e1 - 2) & (bn_tri >= n0 + 2) & (bn_tri <= n1 - 2)
        verts, norms, bidx, stype = verts[in_crop], norms[in_crop], bidx[in_crop], stype[in_crop]
        t_dir_bin = t_dir_bin[in_crop]
        t_tw_x, t_tw_y = t_tw_x[in_crop], t_tw_y[in_crop]
        t_u_verts = t_u_verts[in_crop]
        orig_tri_idx = orig_tri_idx[in_crop]

    if len(verts) > 0:
        px_v, py_v, pd_v = camera.project(verts[:, :, 0], verts[:, :, 1], verts[:, :, 2])
        px_v += shift_x
        py_v += shift_y

        x_min_t = np.floor(px_v.min(axis=1)).astype(np.int32)
        x_max_t = np.ceil(px_v.max(axis=1)).astype(np.int32)
        y_min_t = np.floor(py_v.min(axis=1)).astype(np.int32)
        y_max_t = np.ceil(py_v.max(axis=1)).astype(np.int32)

        dx1, dy1 = px_v[:, 1] - px_v[:, 0], py_v[:, 1] - py_v[:, 0]
        dx2, dy2 = px_v[:, 2] - px_v[:, 0], py_v[:, 2] - py_v[:, 0]
        det = dx1 * dy2 - dx2 * dy1

        vis = (x_max_t >= 0) & (x_min_t < W) & (y_max_t >= 0) & (y_min_t < H) & (np.abs(det) > 0.06)
        px_v, py_v, pd_v = px_v[vis], py_v[vis], pd_v[vis]
        verts_v, norms_v, bidx_v, stype_v = verts[vis], norms[vis], bidx[vis], stype[vis]
        dir_bin_v = t_dir_bin[vis]
        tw_x_v, tw_y_v = t_tw_x[vis], t_tw_y[vis]
        u_wall_v = t_u_verts[vis]
        orig_tri_v = orig_tri_idx[vis]
        inv_det = 1.0 / det[vis]
        x_min_t = np.maximum(0, x_min_t[vis])
        x_max_t = np.minimum(W - 1, x_max_t[vis])
        y_min_t = np.maximum(0, y_min_t[vis])
        y_max_t = np.minimum(H - 1, y_max_t[vis])

        bw_t = x_max_t - x_min_t + 1
        bh_t = y_max_t - y_min_t + 1
        small_ids = np.nonzero((bw_t <= 16) & (bh_t <= 16))[0]
        large_ids = np.nonzero((bw_t > 16) | (bh_t > 16))[0]

        gx16, gy16 = np.meshgrid(np.arange(16, dtype=np.float32), np.arange(16, dtype=np.float32))
        frag_x, frag_y, frag_d, frag_t, frag_e, frag_n, frag_z, frag_u = [], [], [], [], [], [], [], []

        for s_start in range(0, len(small_ids), 5500):
            idx = small_ids[s_start : s_start + 5500]
            bx0 = x_min_t[idx][:, None, None]
            by0 = y_min_t[idx][:, None, None]
            px_g = bx0 + gx16[None, :, :] + 0.5
            py_g = by0 + gy16[None, :, :] + 0.5
            in_b = (px_g <= (x_max_t[idx][:, None, None] + 0.5)) & (py_g <= (y_max_t[idx][:, None, None] + 0.5))

            v0x, v0y = px_v[idx, 0][:, None, None], py_v[idx, 0][:, None, None]
            v1x, v1y = px_v[idx, 1][:, None, None], py_v[idx, 1][:, None, None]
            v2x, v2y = px_v[idx, 2][:, None, None], py_v[idx, 2][:, None, None]
            idet = inv_det[idx][:, None, None]

            w1 = ((px_g - v0x) * (v2y - v0y) - (v2x - v0x) * (py_g - v0y)) * idet
            w2 = ((v1x - v0x) * (py_g - v0y) - (px_g - v0x) * (v1y - v0y)) * idet
            w0 = 1.0 - w1 - w2

            inside = in_b & (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
            kk, yy, xx = np.nonzero(inside)
            if len(kk) == 0:
                continue
            tg = idx[kk]
            f_px = (x_min_t[tg] + xx).astype(np.int32)
            f_py = (y_min_t[tg] + yy).astype(np.int32)
            bw0, bw1, bw2 = w0[kk, yy, xx], w1[kk, yy, xx], w2[kk, yy, xx]
            f_d = bw0 * pd_v[tg, 0] + bw1 * pd_v[tg, 1] + bw2 * pd_v[tg, 2]

            keep = f_d < (zbuf[f_py, f_px] + 0.05)
            if keep.any():
                tg = tg[keep]
                bw0, bw1, bw2 = bw0[keep], bw1[keep], bw2[keep]
                frag_x.append(f_px[keep])
                frag_y.append(f_py[keep])
                frag_d.append(f_d[keep])
                frag_t.append(tg)
                frag_e.append(bw0 * verts_v[tg, 0, 0] + bw1 * verts_v[tg, 1, 0] + bw2 * verts_v[tg, 2, 0])
                frag_n.append(bw0 * verts_v[tg, 0, 1] + bw1 * verts_v[tg, 1, 1] + bw2 * verts_v[tg, 2, 1])
                frag_z.append(bw0 * verts_v[tg, 0, 2] + bw1 * verts_v[tg, 1, 2] + bw2 * verts_v[tg, 2, 2])
                frag_u.append(bw0 * u_wall_v[tg, 0] + bw1 * u_wall_v[tg, 1] + bw2 * u_wall_v[tg, 2])

        for ti in large_ids:
            x0_i, x1_i = int(x_min_t[ti]), int(x_max_t[ti])
            y0_i, y1_i = int(y_min_t[ti]), int(y_max_t[ti])
            px_g, py_g = np.meshgrid(
                np.arange(x0_i, x1_i + 1, dtype=np.float32) + 0.5,
                np.arange(y0_i, y1_i + 1, dtype=np.float32) + 0.5,
            )
            v0x, v0y = px_v[ti, 0], py_v[ti, 0]
            v1x, v1y = px_v[ti, 1], py_v[ti, 1]
            v2x, v2y = px_v[ti, 2], py_v[ti, 2]
            idet = inv_det[ti]

            w1 = ((px_g - v0x) * (v2y - v0y) - (v2x - v0x) * (py_g - v0y)) * idet
            w2 = ((v1x - v0x) * (py_g - v0y) - (px_g - v0x) * (v1y - v0y)) * idet
            w0 = 1.0 - w1 - w2

            inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
            yy, xx = np.nonzero(inside)
            if len(yy) == 0:
                continue
            f_px = (x0_i + xx).astype(np.int32)
            f_py = (y0_i + yy).astype(np.int32)
            bw0, bw1, bw2 = w0[yy, xx], w1[yy, xx], w2[yy, xx]
            f_d = bw0 * pd_v[ti, 0] + bw1 * pd_v[ti, 1] + bw2 * pd_v[ti, 2]
            keep = f_d < (zbuf[f_py, f_px] + 0.05)
            if keep.any():
                bw0, bw1, bw2 = bw0[keep], bw1[keep], bw2[keep]
                nk = int(keep.sum())
                frag_x.append(f_px[keep])
                frag_y.append(f_py[keep])
                frag_d.append(f_d[keep])
                frag_t.append(np.full(nk, ti, dtype=np.int32))
                frag_e.append(bw0 * verts_v[ti, 0, 0] + bw1 * verts_v[ti, 1, 0] + bw2 * verts_v[ti, 2, 0])
                frag_n.append(bw0 * verts_v[ti, 0, 1] + bw1 * verts_v[ti, 1, 1] + bw2 * verts_v[ti, 2, 1])
                frag_z.append(bw0 * verts_v[ti, 0, 2] + bw1 * verts_v[ti, 1, 2] + bw2 * verts_v[ti, 2, 2])
                frag_u.append(bw0 * u_wall_v[ti, 0] + bw1 * u_wall_v[ti, 1] + bw2 * u_wall_v[ti, 2])

        if frag_x:
            fx = np.concatenate(frag_x)
            fy = np.concatenate(frag_y)
            fd = np.concatenate(frag_d)
            ft = np.concatenate(frag_t)
            fe = np.concatenate(frag_e)
            fn = np.concatenate(frag_n)
            fz = np.concatenate(frag_z)
            fu = np.concatenate(frag_u)
            del frag_x, frag_y, frag_d, frag_t, frag_e, frag_n, frag_z, frag_u

            order = np.argsort(fd)[::-1]
            fx, fy, fd, ft = fx[order], fy[order], fd[order], ft[order]
            fe, fn, fz, fu = fe[order], fn[order], fz[order], fu[order]

            win = fd < zbuf[fy, fx]
            fx, fy, fd, ft = fx[win], fy[win], fd[win], ft[win]
            fe, fn, fz, fu = fe[win], fn[win], fz[win], fu[win]

            bi = bidx_v[ft]
            st_f = stype_v[ft]
            f_col = np.empty((len(fx), 3), dtype=np.float32)
            f_mat = np.where(st_f == 1, M_ROOF, M_WALL).astype(np.uint8)
            f_norm = norms_v[ft].copy()
            f_no_parapet = np.zeros(len(fx), dtype=bool)

            # -----------------------------------------------------------------
            # A. ROOF PIXELS (F11 + F12): De-Biased 25cm SWISSIMAGE Roofs, Intact Lindt HoC & PV,
            #    Glare Clamping, Domed Aluminum Silo Caps & Translucent Glass Greenhouses!
            # -----------------------------------------------------------------
            rm = st_f == 1
            if rm.any():
                r_ft = ft[rm]
                r_bi = bi[rm]
                r_norms = norms_v[r_ft]
                r_sty = bldg_style[r_bi]
                re_r, rn_r, rz_r, ru_r = fe[rm], fn[rm], fz[rm], fu[rm]

                r_clean = scene.bldg_clean_roof_rgb[r_bi].copy()
                r_kind = scene.bldg_roof_kind[r_bi]
                pitched = r_norms[:, 2] < 0.93

                # Verified rooftop Solar PV mask (SACRED GUARDRAIL — untouched!)
                pv_c05 = np.clip(((re_r - E_MIN) * 2.0).astype(np.int32), 0, GRID_W - 1)
                pv_r05 = np.clip(((N_MAX - rn_r) * 2.0).astype(np.int32), 0, GRID_H - 1)
                is_pv = scene.pv_clean_05m[pv_r05, pv_c05]

                # v12: Sample denoised smooth 0.5m ortho on non-HoC roofs, while preserving native 10 cm DOP10 on Lindt HoC & Solar PV!
                raw_r25 = _sample_bilinear_rgb_05m(scene.ortho_roof_smooth_05m, re_r, rn_r)
                keep_hr_roof = (r_bi == id_lindt_hoc) | is_pv | (r_bi == id_st_el_nave)
                if keep_hr_roof.any():
                    raw_r25[keep_hr_roof] = sample_ortho_25cm(scene, re_r[keep_hr_roof], rn_r[keep_hr_roof]).astype(np.float32)
                sat_r = condition_90s_albedo(raw_r25, shadow_knee=66.0, vibrancy=1.18)

                # F11: Per-triangle pitched-roof aerial shadow de-biasing (preserves 100% of 25cm dormers/Velux/tiles;
                # Lindt HoC & green roofs have tri_roof_lum_gain == 1.0!)
                r_orig = orig_tri_v[r_ft]
                r_gain = scene.tri_roof_lum_gain[r_orig]
                r_warm = scene.tri_roof_warm_shift[r_orig]
                sat_r = np.clip(sat_r * r_gain[:, None], 0.0, 248.0)
                has_warm = r_warm > 0.005
                if has_warm.any():
                    ww = r_warm[has_warm]
                    sat_r[has_warm, 0] = np.minimum(248.0, sat_r[has_warm, 0] * (1.0 + 0.45 * ww))
                    sat_r[has_warm, 1] = np.minimum(248.0, sat_r[has_warm, 1] * (1.0 + 0.10 * ww))
                    sat_r[has_warm, 2] = np.maximum(16.0, sat_r[has_warm, 2] * (1.0 - 0.35 * ww))

                sat_lum = 0.299 * sat_r[:, 0] + 0.587 * sat_r[:, 1] + 0.114 * sat_r[:, 2]
                ref_rgb = scene.bldg_sunlit_roof_rgb[r_bi]
                ref_lum = np.maximum(58.0, 0.299 * ref_rgb[:, 0] + 0.587 * ref_rgb[:, 1] + 0.114 * ref_rgb[:, 2])

                # F11: Soft-clamp overexposed specular glare spikes (>228) on non-white roofs (exempting Lindt HoC & PV!)
                glare = (sat_lum > 228.0) & (ref_lum < 195.0) & (r_bi != id_lindt_hoc) & (~is_pv)
                if glare.any():
                    g_lum = sat_lum[glare]
                    g_scale = (228.0 + 0.22 * (g_lum - 228.0)) / g_lum
                    sat_r[glare] *= g_scale[:, None]
                    sat_lum[glare] = 228.0 + 0.22 * (g_lum - 228.0)

                # Guard ONLY against overhanging green tree canopies on non-green roofs & true pitch-black shadows
                is_overhang_leaf = (r_kind != 3) & (r_bi != id_lindt_hoc) & ((sat_r[:, 1] - sat_r[:, 0]) > 10.0) & ((sat_r[:, 1] - sat_r[:, 2]) > 8.0)
                is_deep_aerial_sh = (sat_lum < (0.40 * ref_lum)) & (~is_pv) & (r_bi != id_lindt_hoc)

                # v12: Stylized denoised non-HoC roofs (base_w=0.30 flat, 0.18 pitched), keeping Lindt HoC strictly at 0.95!
                base_w = np.where(r_bi == id_lindt_hoc, 0.95, np.where(pitched, 0.18, 0.30)).astype(np.float32)
                sat_w = np.where(is_overhang_leaf, 0.0, np.where(is_deep_aerial_sh, 0.15, base_w))[:, None]
                r_alb = sat_w * sat_r + (1.0 - sat_w) * r_clean

                # 1. Pitched Roofs: Clean crisp parallel terracotta/slate tile-ridge grooves & dark eave trim!
                #    v11: Exempt St. Elisabeth nave (standing-seam copper) & bell tower (white board-formed concrete legs/crown!)
                pitched_tiled = pitched & (r_bi != id_st_el_nave) & (r_bi != id_st_el_twr)
                if pitched_tiled.any():
                    pi_r = np.nonzero(pitched_tiled)[0]
                    rz_p = rz_r[pi_r]
                    ru_p = ru_r[pi_r]
                    rb_p = r_bi[pi_r]
                    course_f = rz_p * 1.80
                    course_idx = np.floor(course_f).astype(np.int32)
                    in_course = course_f - course_idx
                    u_f = ru_p * 2.05 + (course_idx & 1) * 0.5
                    u_tile = u_f - np.floor(u_f)

                    hi_res_rf = camera.mpp <= 0.16
                    r_alb[pi_r[in_course < (0.22 if hi_res_rf else 0.24)]] *= (0.78 if hi_res_rf else 0.85)
                    r_alb[pi_r[(in_course >= 0.76) & (in_course < 0.94)]] = np.minimum(
                        246.0, r_alb[pi_r[(in_course >= 0.76) & (in_course < 0.94)]] * (1.08 if hi_res_rf else 1.05)
                    )
                    r_alb[pi_r[u_tile < (0.11 if hi_res_rf else 0.12)]] *= (0.90 if hi_res_rf else 0.94)
                    eave_d = rz_p - scene.bldg_eave_z[rb_p]
                    r_alb[pi_r[(eave_d >= -0.25) & (eave_d < (0.44 if hi_res_rf else 0.36))]] *= (0.70 if hi_res_rf else 0.78)

                # 2. Flat Roofs: Keep Lindt HoC subtle parapet coping untouched; non-HoC flat roofs
                #    receive pixel-exact screen-space parapets right after Stage 3 (zero 25cm staircase gaps!).
                flat = ~pitched
                if flat.any():
                    fi_r = np.nonzero(flat)[0]
                    is_lhoc_f = r_bi[fi_r] == id_lindt_hoc
                    if is_lhoc_f.any():
                        lh_idx = fi_r[is_lhoc_f]
                        est_lh = sample_roof_edge_25cm(scene, re_r[lh_idx], rn_r[lh_idx])
                        lhoc_c = est_lh == 1
                        if lhoc_c.any():
                            r_alb[lh_idx[lhoc_c]] = np.clip(
                                r_alb[lh_idx[lhoc_c]] * 0.45 + np.array([124.0, 122.0, 118.0]), 140.0, 232.0
                            )

                # 3. Crisp Rooftop Solar PV Grid Overlay strictly on morphologically verified PV arrays (SACRED!)
                if is_pv.any():
                    pvi = np.nonzero(is_pv)[0]
                    pv_grid = (((re_r[pvi] * 0.90) % 1.0) < 0.10) | (((rn_r[pvi] * 0.90) % 1.0) < 0.10)
                    r_alb[pvi] = 0.35 * r_alb[pvi] + 0.65 * np.array([32.0, 54.0, 96.0], dtype=np.float32)
                    r_alb[pvi[pv_grid]] = [166.0, 176.0, 190.0]

                # 4. F12: Special Objektart Roof Overrides (Lagertank aluminum domes & Treibhaus glass roofs!)
                r_is_silo = r_sty == 8
                if r_is_silo.any():
                    si_r = np.nonzero(r_is_silo)[0]
                    s_bi = r_bi[si_r]
                    rad_n = np.hypot(re_r[si_r] - bldg_e0[s_bi], rn_r[si_r] - bldg_n0[s_bi]) / np.maximum(1.2, 0.5 * bldg_fw[s_bi])
                    rad_c = np.clip(rad_n, 0.0, 1.0)[:, None]
                    dome_c = (1.0 - rad_c) * np.array([224.0, 228.0, 234.0], dtype=np.float32) + rad_c * np.array([164.0, 170.0, 178.0], dtype=np.float32)
                    dome_c[rad_n > 0.86] = [116.0, 122.0, 130.0]
                    # v9.0 Lindt cocoa silo perimeter safety guardrail ring
                    is_tall_silo = (bldg_z1[s_bi] - bldg_z0[s_bi]) >= 14.0
                    in_guard = is_tall_silo & (rad_n >= 0.80) & (rad_n <= 0.90)
                    if in_guard.any():
                        az_s = np.arctan2(rn_r[si_r[in_guard]] - bldg_n0[s_bi[in_guard]], re_r[si_r[in_guard]] - bldg_e0[s_bi[in_guard]])
                        g_post = ((az_s * 6.0) % 1.0) < 0.35
                        dome_c[in_guard] = np.where(g_post[:, None], [218.0, 224.0, 232.0], [96.0, 102.0, 110.0])
                    # v11 Stockengut galvanized silver-grey metallic farm silo conical domes
                    is_st_silo = (s_bi == id_stock_silo_1) | (s_bi == id_stock_silo_2)
                    if is_st_silo.any():
                        rc_st = rad_c[is_st_silo]
                        dome_c[is_st_silo] = (1.0 - rc_st) * np.array([188.0, 194.0, 200.0], dtype=np.float32) + rc_st * np.array([138.0, 144.0, 152.0], dtype=np.float32)
                    r_alb[si_r] = dome_c

                r_is_gh = r_sty == 7
                if r_is_gh.any():
                    gi_r = np.nonzero(r_is_gh)[0]
                    gh_h = ((np.floor(re_r[gi_r] * 1.5).astype(np.int32) * 73856093) ^ (np.floor(rn_r[gi_r] * 1.5).astype(np.int32) * 19349663)) & 15
                    glass_base = np.array([78.0, 108.0, 136.0] if preset.is_night else [156.0, 198.0, 212.0], dtype=np.float32)
                    bot_green = np.array([46.0, 74.0, 56.0] if preset.is_night else [82.0, 134.0, 78.0], dtype=np.float32)
                    g_rf = np.where((gh_h < 7)[:, None], 0.65 * glass_base + 0.35 * bot_green, glass_base).astype(np.float32)
                    mull_r = (((re_r[gi_r] % 1.65) < 0.16) | ((rn_r[gi_r] % 1.65) < 0.16))
                    g_rf[mull_r] = [164.0, 172.0, 182.0] if preset.is_night else [226.0, 230.0, 234.0]
                    r_alb[gi_r] = g_rf

                # v11 Landmark roof refinements (strictly r_bi != id_lindt_hoc!)
                # (Hallenbad & Sporthalle flat-roof parapet overrides are applied cleanly in the post-Stage-3 screen-space pass)
                # v11 St. Elisabeth standing-seam weathered copper roof (dark bronze-brown skirt -> muted green-olive patina saddle)
                # Preserve real 10cm DOP10 pale-blue glazed Oberlicht ridge skylight!
                r_is_sel = (r_bi == id_st_el_nave) & (r_bi != id_lindt_hoc)
                if r_is_sel.any():
                    seli = np.nonzero(r_is_sel)[0]
                    sel_sat = sat_r[seli]
                    sel_lum = sat_lum[seli]
                    is_sky = (sel_lum > 118.0) | ((sel_sat[:, 2] - sel_sat[:, 0]) > 10.0)
                    cop_i = seli[~is_sky]
                    if len(cop_i) > 0:
                        t_pat = np.clip((rz_r[cop_i] - 489.5) / 10.5, 0.0, 1.0)[:, None]
                        cop_col = (1.0 - t_pat) * np.array([84.0, 76.0, 64.0], dtype=np.float32) + t_pat * np.array([98.0, 108.0, 92.0], dtype=np.float32)
                        r_alb[cop_i] = 0.45 * r_alb[cop_i] + 0.55 * cop_col
                        # Fine vertical/radial standing-seam copper ribs (0.65m spacing)
                        seam_f = (ru_r[cop_i] * 1.55) % 1.0
                        r_alb[cop_i[seam_f < 0.14]] *= 0.84
                        r_alb[cop_i[(seam_f >= 0.14) & (seam_f < 0.26)]] = np.minimum(240.0, r_alb[cop_i[(seam_f >= 0.14) & (seam_f < 0.26)]] * 1.07)
                    sky_i = seli[is_sky]
                    if len(sky_i) > 0:
                        if preset.is_night or preset_key == "sunset":
                            r_alb[sky_i] = 0.55 * r_alb[sky_i] + 0.45 * np.array([232.0, 202.0, 134.0], dtype=np.float32)
                        else:
                            r_alb[sky_i] = 0.65 * r_alb[sky_i] + 0.35 * np.array([178.0, 204.0, 222.0], dtype=np.float32)
                # v11 St. Elisabeth bell tower (idx=1254): sloped concrete legs & crown tips are surf_type==1 (M_ROOF);
                # style as crisp bright white painted board-formed concrete matching inner shaft!
                m_se_twr_r = (r_bi == id_st_el_twr) & (r_bi != id_lindt_hoc)
                if m_se_twr_r.any():
                    twr_i = np.nonzero(m_se_twr_r)[0]
                    r_alb[twr_i] = np.array([238.0, 238.0, 234.0], dtype=np.float32)
                    r_alb[twr_i[((rz_r[twr_i] % 3.0) < 0.10)]] *= 0.95
                r_is_stf = np.isin(r_bi, stock_roof_arr) & pitched & (r_bi != id_lindt_hoc)
                if r_is_stf.any():
                    r_alb[r_is_stf] = np.clip(r_alb[r_is_stf] * np.array([1.06, 0.99, 0.94], dtype=np.float32), 0.0, 244.0)
                r_is_rk = (r_bi == id_ref_kirche) & (r_bi != id_lindt_hoc)
                if r_is_rk.any():
                    r_alb[r_is_rk] = np.clip(r_alb[r_is_rk] * np.array([0.88, 0.86, 0.86], dtype=np.float32), 0.0, 240.0)

                f_col[rm] = r_alb
                f_no_parapet[rm] = is_pv | r_is_silo | r_is_gh | (r_bi == id_lindt_hoc)

            # -----------------------------------------------------------------
            # B. WALL PIXELS (F7 + F12 + F13): Rich Swiss Vernacular Facades, Silos, Greenhouses & Landmarks!
            # -----------------------------------------------------------------
            wm = st_f == 0
            if wm.any():
                wi = np.nonzero(wm)[0]
                w_ft = ft[wi]
                w_bi = bi[wi]
                w_sty = bldg_style[w_bi]
                w_base = bldg_wall_rgb[w_bi].astype(np.float32)
                w_e = fe[wi]
                w_n = fn[wi]
                w_z = fz[wi]
                w_u = fu[wi]
                h_rel = w_z - bldg_z0[w_bi]
                top_dist = bldg_z1[w_bi] - w_z
                eave_z = scene.bldg_eave_z[w_bi]

                # v12-M1C Fix 1: Exact local smoothed terrain elevation at every wall fragment
                w_local_dem = _sample_bilinear_05m(scene.dem, w_e, w_n)
                h_above_gnd = w_z - w_local_dem
                PLINTH_H = 0.80  # Clean Swiss Sockel height above local ground (m)

                w_dbin = dir_bin_v[w_ft]
                w_key = w_bi * 36 + w_dbin
                u_min_w = scene.wall_u_min[w_key]
                u_max_w = scene.wall_u_max[w_key]
                wall_len = np.maximum(0.5, u_max_w - u_min_w)
                u_local = w_u - u_min_w
                d_center = w_u - 0.5 * (u_min_w + u_max_w)
                edge_dist = np.minimum(u_local, wall_len - u_local)

                # v12: Clean smooth cel-shaded plaster facades (removed wh_tex per-pixel static!)

                # Crisp ashlar stone foundation plinth + water-table bevel, deep roof eave shadow, heritage corner quoins!
                w_base[h_rel < 0.75] *= 0.78
                w_base[(h_rel >= 0.72) & (h_rel < 0.85)] = np.minimum(246.0, w_base[(h_rel >= 0.72) & (h_rel < 0.85)] * 1.07)
                w_base[(top_dist > 0.0) & (top_dist < 0.62)] *= 0.74
                w_base[(edge_dist < 0.28) & (wall_len > 3.2)] *= 0.92
                if camera.mpp <= 0.16:
                    # Dressed stone corner quoins on traditional heritage buildings (w_sty == 0)
                    q_course = np.floor(h_rel * 1.65).astype(np.int32)
                    q_w = np.where((q_course & 1) == 0, 0.44, 0.26)
                    is_quoin = (w_sty == 0) & (wall_len > 4.8) & (h_above_gnd >= (PLINTH_H + 0.04)) & (top_dist >= 0.62) & (edge_dist < q_w)
                    if is_quoin.any():
                        q_joint = ((h_rel[is_quoin] * 1.65) % 1.0) < 0.14
                        q_c = np.clip(w_base[is_quoin] * 0.72 + np.array([62.0, 58.0, 52.0], dtype=np.float32), 90.0, 236.0)
                        q_c[q_joint] *= 0.82
                        w_base[is_quoin] = q_c

                # Buff-brick Lindt smokestack (43.6m Hochkamin) + v9.0 iron tension rings & climbing ladder
                is_chimney = w_bi == id_lindt_chim
                if is_chimney.any():
                    ch_i = np.nonzero(is_chimney)[0]
                    ch_course = ((w_z[ch_i] * 1.4) % 1.0) < 0.25
                    w_base[ch_i[ch_course]] *= 0.93
                    ch_ring = (h_rel[ch_i] > 3.0) & (top_dist[ch_i] > 1.8) & ((h_rel[ch_i] % 4.5) < 0.24)
                    w_base[ch_i[ch_ring]] = [64.0, 62.0, 60.0]
                    ch_lad_zone = (norms_v[w_ft[ch_i], 0] > 0.35) & (np.abs(d_center[ch_i]) <= 0.32) & (h_rel[ch_i] >= 2.0) & (top_dist[ch_i] >= 1.6)
                    ch_lad = ch_lad_zone & ((np.abs(d_center[ch_i]) >= 0.20) | ((h_rel[ch_i] % 0.65) < 0.14))
                    w_base[ch_i[ch_lad]] = [58.0, 62.0, 68.0]
                    ch_cap = top_dist[ch_i] < 1.55
                    w_base[ch_i[ch_cap]] = [86.0, 82.0, 78.0]

                # F12: Mauer gross (Jura-stone ashlar retaining wall!)
                is_mauer = bldg_is_mauer[w_bi]
                if is_mauer.any():
                    ma_i = np.nonzero(is_mauer)[0]
                    ma_c = np.floor(w_z[ma_i] * 2.2).astype(np.int32)
                    ma_hm = ((w_z[ma_i] * 2.2) % 1.0) < 0.18
                    ma_vm = ((u_local[ma_i] + (ma_c & 1) * 0.55) % 1.10) < 0.14
                    w_base[ma_i] = [164.0, 158.0, 146.0]
                    w_base[ma_i[ma_hm | ma_vm]] *= 0.80

                # v11: Bendlikon Pier / Badweg 1.1 boathouse-shelter walls (weathered cedar planks, boat-bay recesses & timber deck rim)
                is_bpier = w_bi == id_bend_pier
                if is_bpier.any():
                    bpi = np.nonzero(is_bpier)[0]
                    bph = h_rel[bpi]
                    bpu = u_local[bpi]
                    bptd = top_dist[bpi]
                    w_base[bpi] = [104.0, 84.0, 66.0]
                    w_base[bpi[(bpu % 0.42) < 0.09]] *= 0.84
                    bp_open = (bph >= 0.35) & (bph <= 2.05) & (edge_dist[bpi] >= 0.85) & ((bpu % 3.2) > 0.45)
                    w_base[bpi[bp_open]] = [38.0, 44.0, 52.0]
                    w_base[bpi[bph < 0.38]] = [168.0, 154.0, 134.0]
                    w_base[bpi[bptd < 0.28]] = [58.0, 62.0, 68.0]

                # F12: Lagertank Cylindrical Silos (style 8 — 6 Lindt cocoa silos + Stocken reservoir + farm silos!)
                is_silo = w_sty == 8
                if is_silo.any():
                    sl_i = np.nonzero(is_silo)[0]
                    s_bi = w_bi[sl_i]
                    cx_s = w_e[sl_i] - bldg_e0[s_bi]
                    cy_s = w_n[sl_i] - bldg_n0[s_bi]
                    clen = np.maximum(1e-4, np.hypot(cx_s, cy_s))
                    cx_s /= clen
                    cy_s /= clen
                    # Overwrite faceted CityGML normal with silky cylindrical radial normal!
                    f_norm[wi[sl_i], 0] = cx_s
                    f_norm[wi[sl_i], 1] = cy_s
                    f_norm[wi[sl_i], 2] = 0.08
                    cyl_dot = np.maximum(0.0, cx_s * sun_vec[0] + cy_s * sun_vec[1])
                    spec = (cyl_dot ** 5) * 44.0
                    s_col = np.full((len(sl_i), 3), [182.0, 188.0, 196.0], dtype=np.float32) + spec[:, None]
                    is_st_s = (s_bi == id_stock_silo_1) | (s_bi == id_stock_silo_2)
                    if is_st_s.any():
                        s_col[is_st_s] = np.array([184.0, 190.0, 196.0], dtype=np.float32) + spec[is_st_s, None]
                        s_col[is_st_s & ((h_rel[sl_i] % 1.8) < 0.14)] *= 0.78
                    s_col[(~is_st_s) & ((h_rel[sl_i] % 2.5) < 0.16)] *= 0.84      # Horizontal bolted steel rings
                    s_col[h_rel[sl_i] < 0.90] = [118.0, 122.0, 128.0]  # Galvanized base plinth
                    s_col[top_dist[sl_i] < 0.42] = [132.0, 138.0, 146.0]
                    # v9.0 Tall Lindt cocoa silos: top safety guardrail band & vertical service ladder
                    is_tall_sw = (bldg_z1[s_bi] - bldg_z0[s_bi]) >= 14.0
                    in_gr_w = is_tall_sw & (top_dist[sl_i] < 0.78)
                    if in_gr_w.any():
                        gp_w = (((np.arctan2(cy_s[in_gr_w], cx_s[in_gr_w]) * 6.0) % 1.0) < 0.25) | (top_dist[sl_i[in_gr_w]] < 0.22)
                        s_col[in_gr_w] = np.where(gp_w[:, None], [214.0, 220.0, 228.0], [92.0, 98.0, 106.0])
                    in_lad_s = is_tall_sw & (cx_s > 0.78) & (np.abs(cy_s) < 0.22) & (h_rel[sl_i] >= 1.2)
                    lad_s_px = in_lad_s & ((np.abs(cy_s) >= 0.14) | ((h_rel[sl_i] % 0.65) < 0.15))
                    s_col[lad_s_px] = [74.0, 80.0, 88.0]
                    w_base[sl_i] = np.clip(s_col, 24.0, 248.0)

                # F12: Treibhaus Glass Greenhouses (style 7 — Langholzweg 70g/70h & Uf Stocken!)
                is_gh_w = w_sty == 7
                if is_gh_w.any():
                    gh_i = np.nonzero(is_gh_w)[0]
                    gh_bi = w_bi[gh_i]
                    gh_h = h_rel[gh_i]
                    gh_u = u_local[gh_i]
                    is_knee = gh_h < 0.72
                    is_mull = ((gh_u % 1.65) < 0.16) | ((gh_h % 1.45) < 0.14)
                    is_transom = np.abs(gh_h - 2.4) < 0.14
                    g_col_w = np.full(
                        (len(gh_i), 3),
                        [64.0, 92.0, 118.0] if preset.is_night else [146.0, 190.0, 206.0],
                        dtype=np.float32,
                    )
                    # Interior botanical greenery visible through lower glass bays
                    gh_noise = ((np.floor(gh_u * 2.5).astype(np.int32) * 73856093) ^ (np.floor(gh_h * 3.0).astype(np.int32) * 19349663)) & 15
                    in_fol = (~is_knee) & (gh_h <= 2.35) & (gh_noise < 9)
                    g_col_w[in_fol] = [44.0, 74.0, 54.0] if preset.is_night else [86.0, 134.0, 88.0]
                    # v9.0 Soft warm conservatory lantern glow on Sanatorium greenhouses at Sunset/Night
                    is_san_gh = ((gh_bi == id_san_gh_225) | (gh_bi == id_san_gh_886)) & (~is_knee) & (~is_mull) & (~is_transom)
                    if (preset.is_night or preset_key == "sunset") and is_san_gh.any():
                        g_col_w[is_san_gh] = [142.0, 154.0, 118.0]
                        f_mat[wi[gh_i[is_san_gh]]] = M_WINDOW_LIT
                    g_col_w[is_mull] = [156.0, 164.0, 174.0] if preset.is_night else [222.0, 228.0, 232.0]
                    is_san_mull = ((gh_bi == id_san_gh_225) | (gh_bi == id_san_gh_886)) & (is_mull | is_transom)
                    if (not preset.is_night) and is_san_mull.any():
                        g_col_w[is_san_mull] = [236.0, 242.0, 244.0]  # Crisp white Sanatorium Treibhaus glass ribs
                    g_col_w[is_transom] = [184.0, 190.0, 196.0] if preset.is_night else [234.0, 236.0, 238.0]
                    g_col_w[is_knee] = [168.0, 166.0, 160.0]
                    w_base[gh_i] = g_col_w
                    f_mat[wi[gh_i[(~is_knee) & (~is_mull) & (~is_transom) & (~(is_san_gh & (preset.is_night or preset_key == "sunset")))]]] = M_WINDOW_DAY

                # B1. Lindt Home of Chocolate (style 2 — wall pixels ONLY; id=1443 DOP10 roof is 100% untouched!)
                is_hoc = w_sty == 2
                if is_hoc.any():
                    hi_l = np.nonzero(is_hoc)[0]
                    le, ln, lz, lh = w_e[hi_l], w_n[hi_l], w_z[hi_l], h_rel[hi_l]
                    lu = u_local[hi_l]
                    in_white_curve = (le >= 2684107.5) & (ln >= 1241401.5) & (ln <= 1241437.2)
                    # Glossy white glazed ceramic brick (Koninklijke Tichelaar Makkum, Christ & Gantenbein 2020)
                    w_base[hi_l[in_white_curve]] = [246.0, 248.0, 246.0]
                    sun_glaze = in_white_curve & (le >= 2684122.0) & (ln <= 1241422.0)
                    w_base[hi_l[sun_glaze]] = [252.0, 252.0, 250.0]
                    w_course = in_white_curve & (((lz * 1.8) % 1.0) < 0.16)
                    w_base[hi_l[w_course]] *= 0.97
                    # Horizontal fluted/ribbed ceramic band behind the gold lettering (Christ & Gantenbein)
                    w_flute = in_white_curve & (top_dist[hi_l] >= 1.8) & (top_dist[hi_l] <= 7.8) & (((lz * 3.2) % 1.0) < 0.32)
                    w_base[hi_l[w_flute]] *= 0.94

                    brick_m = ~in_white_curve
                    bcourse = brick_m & (((lz * 2.4) % 1.0) < 0.24)
                    bpier = brick_m & (lh > 4.2) & (((lu % 4.6) < 0.45))
                    w_base[hi_l[bcourse]] *= 0.91
                    w_base[hi_l[bpier]] *= 0.93

                    arc_u = np.where(
                        in_white_curve,
                        (np.arctan2(ln - 1241418.0, le - 2684122.0) + math.pi) * 13.5,
                        lu,
                    )
                    lt_d = top_dist[hi_l]
                    # v9.1: HoC lettering is baked via pipeline/signage.py (SIGNS registry) after all facade detail.

                    plaza_glass = (
                        ((in_white_curve & (lh >= 0.35) & (lh <= 5.4)) | (brick_m & (le >= 2684118.0) & (lh >= 0.45) & (lh <= 3.8)))
                        & (((arc_u % 4.2) >= 0.85) & ((arc_u % 4.2) <= 3.35))
                    )
                    # v11: Real high horizontal ribbon window strip on terracotta brick wing
                    brick_office_win = (
                        brick_m
                        & (lh >= 13.0)
                        & (lh <= 16.0)
                        & (((lu + 0.5) % 1.8) >= 0.24)
                        & (edge_dist[hi_l] >= 2.2)
                    )
                    hoc_win = plaza_glass | brick_office_win
                    if hoc_win.any():
                        hw_idx = hi_l[hoc_win]
                        if preset.is_night:
                            w_base[hw_idx] = [255.0, 222.0, 138.0]
                            f_mat[wi[hw_idx]] = M_WINDOW_LIT
                        elif preset_key == "sunset":
                            is_pg = plaza_glass[hoc_win]
                            w_base[hw_idx] = np.where(is_pg[:, None], [252.0, 212.0, 126.0], [64.0, 68.0, 92.0])
                            f_mat[wi[hw_idx]] = np.where(is_pg, M_WINDOW_LIT, M_WINDOW_DAY)
                        else:
                            w_base[hw_idx] = [48.0, 68.0, 92.0]
                            f_mat[wi[hw_idx]] = M_WINDOW_DAY
                    # v11 Lindt HoC rotunda warm golden interior chocolate-fountain glow & slim WHITE vertical mullions
                    rot_fountain = plaza_glass & in_white_curve & (lh >= 0.8) & (lh <= 4.8)
                    if rot_fountain.any():
                        rf_idx = hi_l[rot_fountain]
                        if preset.is_night or preset_key == "sunset":
                            w_base[rf_idx] = [255.0, 212.0, 108.0]
                            f_mat[wi[rf_idx]] = M_WINDOW_LIT
                        else:
                            in_cent_atr = (arc_u[rot_fountain] >= 10.0) & (arc_u[rot_fountain] <= 20.0)
                            w_base[rf_idx[in_cent_atr]] = [148.0, 120.0, 74.0]
                    rot_mull = plaza_glass & in_white_curve & (((arc_u % 1.4) < 0.16) | (np.abs(lh - 4.8) < 0.16))
                    if rot_mull.any():
                        rm_idx = hi_l[rot_mull]
                        w_base[rm_idx] = [232.0, 234.0, 232.0]
                        f_mat[wi[rm_idx]] = M_WALL

                # B1b. Main Seestrasse 204 Lindt & Sprüngli Complex + 1899 brick wing dentil cornice & factory wall clock
                is_1642 = w_bi == id_lindt_main
                if is_1642.any():
                    m_i = np.nonzero(is_1642)[0]
                    me, mn, mz, mh = w_e[m_i], w_n[m_i], w_z[m_i], h_rel[m_i]
                    mu = u_local[m_i]
                    mtd = top_dist[m_i]

                    wing_poly = mn >= 1241403.0
                    if wing_poly.any():
                        pi = m_i[wing_poly]
                        ph = mh[wing_poly]
                        pu = mu[wing_poly]
                        pz = mz[wing_poly]
                        ptd = mtd[wing_poly]
                        pedg = edge_dist[pi]
                        pcol = np.full((len(pi), 3), [158.0, 66.0, 50.0], dtype=np.float32)
                        brick_line = ((pz * 2.2) % 1.0) < 0.22
                        pcol[brick_line] *= 0.90
                        pilaster_l = (pu % 4.2) < 0.58
                        string_c = ((ph % 4.1) < 0.34) & (ph >= 3.8)
                        arch_lintel = ((ph % 4.1) >= 2.85) & ((ph % 4.1) <= 3.15) & ((pu % 4.2) >= 0.85) & ((pu % 4.2) <= 3.35)
                        pcol[pilaster_l | string_c | arch_lintel] = [212.0, 196.0, 158.0]
                        pcol[ph < 4.2] = [148.0, 144.0, 136.0]
                        pcol[(ph >= 15.8) & (ph < 16.9)] = [216.0, 200.0, 162.0]
                        # v9.0 Brick dentil cornice & steel loading-dock canopy
                        dentil_p = (ptd < 0.95) & (ptd >= 0.40) & ((np.floor(pu * 2.5).astype(np.int32) & 1) == 0)
                        pcol[dentil_p] = [216.0, 200.0, 162.0]
                        pcol[(ph >= 3.55) & (ph <= 4.05) & (pedg >= 1.2)] = [66.0, 72.0, 80.0]
                        pcol[(ph >= 3.25) & (ph < 3.55) & (pedg >= 1.2)] *= 0.72
                        w_base[pi] = pcol

                    wing_mid = (mn >= 1241362.0) & (mn < 1241403.0)
                    if wing_mid.any():
                        mi_b = m_i[wing_mid]
                        mh_b = mh[wing_mid]
                        mtd_b = mtd[wing_mid]
                        me_b = me[wing_mid]
                        mu_b = mu[wing_mid]
                        bcol = np.full((len(mi_b), 3), [220.0, 216.0, 204.0], dtype=np.float32)
                        bcol[mh_b < 1.6] = [140.0, 138.0, 134.0]
                        gsign_b = (me_b >= 2684208.0) & (mtd_b <= 1.25) & (((mu_b * 1.3) % 1.0) >= 0.30)
                        bcol[gsign_b] = [224.0, 188.0, 78.0]
                        w_base[mi_b] = bcol

                    wing_twr = (mn >= 1241342.0) & (mn < 1241362.0) & (me >= 2684225.0)
                    if wing_twr.any():
                        ti_c = m_i[wing_twr]
                        th_c = mh[wing_twr]
                        tu_c = mu[wing_twr]
                        ttd_c = mtd[wing_twr]
                        tcol = np.full((len(ti_c), 3), [224.0, 220.0, 210.0], dtype=np.float32)
                        tcol[th_c < 1.6] = [138.0, 136.0, 132.0]
                        recess = (th_c >= 6.0) & (th_c <= 19.5) & (((tu_c % 4.4) >= 0.8) & ((tu_c % 4.4) <= 3.6))
                        tcol[recess] = [206.0, 202.0, 192.0]
                        crest = (ttd_c <= 1.6) & (np.abs(d_center[ti_c]) <= 3.6)
                        tcol[crest] = [228.0, 190.0, 76.0]
                        # v11 Single modest Lindt Factory circular wall clock below gilded crest (r <= 1.05 m)
                        ux_fc = d_center[ti_c]
                        uz_fc = th_c - 18.2
                        r_fc = np.hypot(ux_fc, uz_fc)
                        on_fc = r_fc <= 1.05
                        if on_fc.any():
                            tcol[on_fc] = [28.0, 34.0, 46.0]
                            d_hr_f = np.abs(ux_fc * 0.57 + uz_fc * 0.82)
                            al_hr_f = -ux_fc * 0.82 + uz_fc * 0.57
                            h_hr_f = on_fc & (d_hr_f <= 0.11) & (al_hr_f >= -0.06) & (al_hr_f <= 0.56)
                            d_mn_f = np.abs(-ux_fc * 0.50 + uz_fc * 0.866)
                            al_mn_f = ux_fc * 0.866 + uz_fc * 0.50
                            h_mn_f = on_fc & (d_mn_f <= 0.09) & (al_mn_f >= -0.06) & (al_mn_f <= 0.74)
                            fc_gold = on_fc & ((r_fc >= 0.82) | (r_fc <= 0.14) | h_hr_f | h_mn_f)
                            tcol[fc_gold] = [232.0, 192.0, 76.0]
                            if preset.is_night or preset_key == "sunset":
                                f_mat[wi[ti_c[fc_gold]]] = M_WINDOW_LIT
                        w_base[ti_c] = tcol

                    wing_south = (mn < 1241342.0) | ((mn < 1241362.0) & (me < 2684225.0))
                    if wing_south.any():
                        si_d = m_i[wing_south]
                        sh_d = mh[wing_south]
                        su_d = mu[wing_south]
                        std_d = mtd[wing_south]
                        se_d = me[wing_south]
                        scol = np.full((len(si_d), 3), [196.0, 190.0, 178.0], dtype=np.float32)
                        in_fl = (sh_d % 4.1) / 4.1
                        is_frame = ((su_d % 3.8) < 0.48) | (in_fl < 0.12)
                        is_buff_brick = (~is_frame) & (in_fl >= 0.12) & (in_fl < 0.28)
                        scol[is_buff_brick] = [178.0, 156.0, 118.0]
                        scol[is_frame] = [156.0, 150.0, 140.0]
                        slat_d = (~is_frame) & (~is_buff_brick) & (((sh_d * 3.2) % 1.0) < 0.35)
                        scol[slat_d] *= 0.94
                        gsign_d = (se_d >= 2684245.0) & (std_d <= 1.25) & (((su_d * 1.3) % 1.0) >= 0.30)
                        scol[gsign_d] = [224.0, 188.0, 78.0]
                        w_base[si_d] = scol

                is_south_prod = (w_bi == id_lindt_s1473) | (w_bi == id_lindt_s1720)
                if is_south_prod.any():
                    sp_i = np.nonzero(is_south_prod)[0]
                    sp_h = h_rel[sp_i]
                    sp_fl = (sp_h % 4.1) / 4.1
                    sp_fr = ((u_local[sp_i] % 3.8) < 0.48) | (sp_fl < 0.12)
                    sp_bb = (~sp_fr) & (sp_fl >= 0.12) & (sp_fl < 0.28)
                    sp_sl = (~sp_fr) & (~sp_bb) & (((sp_h * 3.2) % 1.0) < 0.35)
                    w_base[sp_i] = [196.0, 190.0, 178.0]
                    w_base[sp_i[sp_sl]] *= 0.94
                    w_base[sp_i[sp_bb]] = [178.0, 156.0, 118.0]
                    w_base[sp_i[sp_fr]] = [156.0, 150.0, 140.0]

                # B2. Churches & Bell Towers (style 4)
                is_sacred = w_sty == 4
                if is_sacred.any():
                    si_l = np.nonzero(is_sacred)[0]
                    s_bi = w_bi[si_l]
                    se_w, sn_w, sz_w, sh_w = w_e[si_l], w_n[si_l], w_z[si_l], h_rel[si_l]
                    s_ft = w_ft[si_l]
                    s_edg = edge_dist[si_l]
                    s_dc = d_center[si_l]
                    s_ul = u_local[si_l]

                    # v11 Reformierte Kirche Kilchberg (1240 Romanesque stone tower + white late-Gothic nave & polygonal choir)
                    rk_tower = (s_bi == id_ref_kirche) & ((sz_w >= 520.5) | ((se_w >= 2683409.0) & (sn_w >= 1241284.0)))
                    if rk_tower.any():
                        rt_i = np.nonzero(rk_tower)[0]
                        rt_glob = si_l[rt_i]
                        tx_t = tw_x_v[s_ft[rt_i]]
                        ty_t = tw_y_v[s_ft[rt_i]]
                        d_tc = (se_w[rt_i] - 2683413.0) * tx_t + (sn_w[rt_i] - 1241287.7) * ty_t
                        z_t = sz_w[rt_i]
                        t_edg = s_edg[rt_i]

                        # Exposed unplastered grey-brown fieldstone/rubble masonry (Bruchsteinmauerwerk)
                        st_row = np.floor(z_t * 2.6).astype(np.int32)
                        st_col = np.floor((d_tc + 10.0) * 1.9 + (st_row & 1) * 0.5).astype(np.int32)
                        st_h = ((st_row * 73856093) ^ (st_col * 19349663) ^ (s_ft[rt_i].astype(np.int32) * 83492791)) & 15
                        stone_rgb = np.full((len(rt_i), 3), [122.0, 118.0, 110.0], dtype=np.float32)
                        stone_rgb[st_h < 4] = [94.0, 90.0, 84.0]
                        stone_rgb[(st_h >= 4) & (st_h < 7)] = [134.0, 118.0, 100.0]
                        stone_rgb[st_h >= 13] = [146.0, 142.0, 134.0]
                        mortar = ((z_t * 2.6) % 1.0) < 0.14
                        stone_rgb[mortar] = [142.0, 138.0, 130.0]

                        # Dressed warm-grey sandstone corner quoins (Eckquader)
                        t_quoin = t_edg < 0.55
                        q_alt = (np.floor(z_t * 1.35).astype(np.int32) & 1) == 0
                        stone_rgb[t_quoin] = np.where(q_alt[t_quoin, None], [146.0, 142.0, 132.0], [134.0, 130.0, 122.0])

                        # Two horizontal projecting stone stringcourses (Geschossgesimse) + eaves cornice
                        string_c = (np.abs(z_t - 519.2) <= 0.18) | (np.abs(z_t - 527.6) <= 0.18) | (z_t >= 534.5)
                        stone_rgb[string_c] = [152.0, 148.0, 138.0]
                        string_sh = ((z_t >= 518.82) & (z_t < 519.02)) | ((z_t >= 527.22) & (z_t < 527.42))
                        stone_rgb[string_sh] *= 0.72

                        # Single narrow recessed Romanesque slit window on mid-shaft
                        slit = (np.abs(d_tc) <= 0.18) & (z_t >= 522.0) & (z_t <= 523.8)
                        stone_rgb[slit] = [44.0, 44.0, 48.0]
                        w_base[rt_glob] = stone_rgb

                        # Authentic Kilchberg Tower Clock Ring (dark charcoal-slate, gilded Roman numerals & hands,
                        # NO fat outer yellow halo) with integrated central arched belfry opening (Schalloeffnung) inside!
                        dz_ck = z_t - 531.6
                        r_ck = np.hypot(d_tc, dz_ck)
                        on_clock = r_ck <= 1.82
                        if on_clock.any():
                            ck_sub = np.nonzero(on_clock)[0]
                            ck_g = rt_glob[ck_sub]
                            rc = r_ck[ck_sub]
                            ux = d_tc[ck_sub]
                            uz = dz_ck[ck_sub]

                            dial_col = np.full((len(ck_sub), 3), [42.0, 46.0, 52.0], dtype=np.float32)
                            in_belfry_rect = (np.abs(ux) <= 0.56) & (uz >= -1.05) & (uz <= 0.35)
                            in_belfry_arch = (uz > 0.35) & (uz <= 0.92) & (((ux / 0.56) ** 2 + ((uz - 0.35) / 0.57) ** 2) <= 1.0)
                            in_belfry = in_belfry_rect | in_belfry_arch
                            belfry_mull = in_belfry & (np.abs(ux) <= 0.08)
                            dial_col[in_belfry] = [28.0, 30.0, 34.0]
                            dial_col[belfry_mull] = [118.0, 114.0, 108.0]

                            thin_rim = (rc >= 1.72) & (rc <= 1.82)
                            ang_ck = np.arctan2(uz, ux)
                            roman_ticks = (rc >= 1.24) & (rc <= 1.66) & (np.abs(((ang_ck * 6.0 / math.pi) + 0.5) % 1.0 - 0.5) < 0.14)
                            d_hr = np.abs(ux * 0.57 + uz * 0.82)
                            along_hr = -ux * 0.82 + uz * 0.57
                            hand_hr = (d_hr <= 0.16) & (along_hr >= -0.15) & (along_hr <= 1.05)
                            d_mn = np.abs(-ux * 0.50 + uz * 0.866)
                            along_mn = ux * 0.866 + uz * 0.50
                            hand_mn = (d_mn <= 0.13) & (along_mn >= -0.15) & (along_mn <= 1.42)
                            hub = rc <= 0.20

                            is_gold_num = roman_ticks
                            is_gold_hand = hand_hr | hand_mn | hub
                            dial_col[thin_rim] = [128.0, 112.0, 68.0]
                            dial_col[is_gold_num] = [238.0, 196.0, 68.0]
                            dial_col[is_gold_hand] = [246.0, 206.0, 76.0]
                            w_base[ck_g] = dial_col
                            if preset.is_night or preset_key == "sunset":
                                f_mat[wi[ck_g[is_gold_num | is_gold_hand]]] = M_WINDOW_LIT

                    rk_nave = (s_bi == id_ref_kirche) & (~rk_tower)
                    if rk_nave.any():
                        rn_i = np.nonzero(rk_nave)[0]
                        rn_glob = si_l[rn_i]
                        # Smooth bright white plaster with pale warm-grey plinth (NO exterior buttresses!)
                        rk_plinth = sh_w[rn_i] <= 0.75
                        w_base[rn_glob[rk_plinth]] = [178.0, 176.0, 170.0]
                        rk_portal = (s_edg[rn_i] >= 1.4) & (np.abs(s_dc[rn_i]) <= 1.20) & (sz_w[rn_i] >= 510.2) & (sz_w[rn_i] <= 513.1)
                        if rk_portal.any():
                            rp_g = rn_glob[rk_portal]
                            in_door_rk = (np.abs(s_dc[rn_i[rk_portal]]) <= 0.82) & (sz_w[rn_i[rk_portal]] <= 512.7)
                            w_base[rp_g] = np.where(in_door_rk[:, None], [78.0, 48.0, 38.0], [154.0, 148.0, 138.0])
                        nu = (s_ul[rn_i] % 4.8) - 2.4
                        nz_w = sz_w[rn_i]
                        in_nb = s_edg[rn_i] >= 1.2
                        lancet_outer = in_nb & (
                            ((np.abs(nu) <= 0.78) & (nz_w >= 513.2) & (nz_w <= 518.2))
                            | ((nz_w > 518.2) & (nz_w <= 519.45) & (((nu / 0.78) ** 2 + ((nz_w - 518.2) / 1.20) ** 2) <= 1.0))
                        )
                        lancet_inner = in_nb & (
                            ((np.abs(nu) <= 0.56) & (nz_w >= 513.4) & (nz_w <= 518.2))
                            | ((nz_w > 518.2) & (nz_w <= 519.2) & (((nu / 0.56) ** 2 + ((nz_w - 518.2) / 0.98) ** 2) <= 1.0))
                        )
                        if lancet_outer.any():
                            w_base[rn_glob[lancet_outer & (~lancet_inner)]] = [164.0, 154.0, 136.0]
                        if lancet_inner.any():
                            lg_idx = rn_glob[lancet_inner]
                            l_nu = nu[lancet_inner]
                            l_nz = nz_w[lancet_inner]
                            is_lead = (np.abs(l_nu) < 0.06) | (np.abs(l_nz - 516.0) < 0.09)
                            if preset.is_night or preset_key == "sunset":
                                j_hash = (np.floor(l_nz * 2.2).astype(np.int32) + np.floor(s_ul[rn_i[lancet_inner]] * 0.5).astype(np.int32)) % 3
                                j_col = np.where(
                                    (j_hash == 0)[:, None], [238.0, 194.0, 112.0],
                                    np.where((j_hash == 1)[:, None], [218.0, 168.0, 92.0], [168.0, 186.0, 214.0]),
                                ).astype(np.float32)
                                w_base[lg_idx] = np.where(is_lead[:, None], [84.0, 82.0, 78.0], j_col)
                                f_mat[wi[lg_idx[~is_lead]]] = M_WINDOW_LIT
                            else:
                                w_base[lg_idx] = np.where(is_lead[:, None], [96.0, 94.0, 88.0], [52.0, 62.0, 72.0])
                                f_mat[wi[lg_idx[~is_lead]]] = M_WINDOW_DAY

                    # v11 Real-life André M. Studer 1967 St. Elisabeth white painted concrete crown tower (NO clock!)
                    st_el_tower = s_bi == id_st_el_twr
                    if st_el_tower.any():
                        et_i = np.nonzero(st_el_tower)[0]
                        et_glob = si_l[et_i]
                        edc = s_dc[et_i]
                        ez = sz_w[et_i]
                        # Subtle vertical board-form concrete fluting & faint horizontal pour joints (pure white crown tips!)
                        w_base[et_glob[((ez % 3.0) < 0.10)]] *= 0.95
                        v_flute = (np.abs(edc * 2.8) % 1.0) < 0.14
                        w_base[et_glob[v_flute]] *= 0.96
                        # Recessed central belfry chamber (Glockenstube): dark weathered brown horizontal louvers
                        in_belfry = (ez >= 501.0) & (ez <= 511.5) & (np.abs(edc) <= 0.72)
                        if in_belfry.any():
                            bf_g = et_glob[in_belfry]
                            bf_z = ez[in_belfry]
                            slat_sh = ((bf_z * 2.6) % 1.0) < 0.42
                            w_base[bf_g] = np.where(slat_sh[:, None], [34.0, 26.0, 20.0], [64.0, 50.0, 38.0])

                    st_el_nave = (s_bi == id_st_el_nave) & (s_edg >= 1.8)
                    if st_el_nave.any():
                        en_i = np.nonzero(st_el_nave)[0]
                        en_glob = si_l[en_i]
                        en_td = top_dist[si_l[en_i]]
                        # v11 Real-life white plaster lower walls articulated by exposed grey-white concrete piers
                        pier_m = ((s_ul[en_i] % 2.8) < 0.38) & (en_td >= 0.20)
                        w_base[en_glob[pier_m]] = [176.0, 174.0, 168.0]
                        # Recessed bronze entrance portal on lower wall
                        en_port = (np.abs(s_dc[en_i]) <= 1.8) & (sh_w[en_i] >= 0.15) & (sh_w[en_i] <= 3.0)
                        if en_port.any():
                            ep_g = en_glob[en_port]
                            in_bd = (np.abs(s_dc[en_i[en_port]]) <= 1.25) & (sh_w[en_i[en_port]] <= 2.6)
                            w_base[ep_g] = np.where(in_bd[:, None], [72.0, 58.0, 46.0], [164.0, 162.0, 156.0])
                        # Under-eave horizontal clerestory window band & Fra Roberto Pasotti stained glass
                        clere = (en_td >= 0.25) & (en_td <= 1.65) & ((s_ul[en_i] % 2.8) >= 0.38)
                        if clere.any():
                            cg_idx = en_glob[clere]
                            c_bay = np.floor(s_ul[en_i[clere]] / 2.8).astype(np.int32) % 4
                            sg_full = np.where(
                                (c_bay == 0)[:, None], [54.0, 116.0, 216.0],
                                np.where(
                                    (c_bay == 1)[:, None], [216.0, 58.0, 66.0],
                                    np.where((c_bay == 2)[:, None], [248.0, 196.0, 74.0], [56.0, 158.0, 104.0]),
                                ),
                            ).astype(np.float32)
                            if preset.is_night or preset_key == "sunset":
                                w_base[cg_idx] = sg_full
                                f_mat[wi[cg_idx]] = M_WINDOW_LIT
                            else:
                                w_base[cg_idx] = 0.45 * sg_full + 0.55 * np.array([38.0, 42.0, 46.0], dtype=np.float32)
                                f_mat[wi[cg_idx]] = M_WINDOW_DAY

                # B2b. F13 Bespoke Civic & Historic Landmarks (style 9: Bahnhof, Gemeindehaus, C.F. Meyer, Sanatorium, Seebad!)
                is_civic = w_sty == 9
                if is_civic.any():
                    ci_l = np.nonzero(is_civic)[0]
                    c_bi = w_bi[ci_l]
                    c_h = h_rel[ci_l]
                    c_z = w_z[ci_l]
                    c_td = top_dist[ci_l]
                    c_ul = u_local[ci_l]
                    c_dc = d_center[ci_l]
                    c_edg = edge_dist[ci_l]
                    c_wl = wall_len[ci_l]
                    c_eave = eave_z[ci_l]
                    c_nx = norms_v[w_ft[ci_l], 0]

                    # 1. Bahnhof Kilchberg SBB Heritage Station Building (idx=670, Baumgartner + Partner 2018)
                    m_bhf = c_bi == id_bhf_stn
                    if m_bhf.any():
                        bi_b = ci_l[m_bhf]
                        bh_b, bu_b, be_b, btd_b = c_h[m_bhf], c_ul[m_bhf], c_edg[m_bhf], c_td[m_bhf]
                        # Smooth light-grey concrete plinth (no fake stone quoins on smooth olive stucco)
                        w_base[bi_b[bh_b < 0.95]] = [152.0, 148.0, 140.0]
                        # Crisp white stepped roof cornice + thin dark-slate fascia (uses top_dist, not low annex eave_z!)
                        w_base[bi_b[btd_b < 0.55]] = [232.0, 230.0, 222.0]
                        w_base[bi_b[btd_b < 0.18]] = [62.0, 58.0, 54.0]
                        # Modern ground-floor blonde-wood vertical slatted annex under low canopy
                        annex_b = (bh_b >= 0.95) & (bh_b <= 3.3) & (btd_b <= 1.2)
                        if annex_b.any():
                            an_i = bi_b[annex_b]
                            slat_on = ((bu_b[annex_b] * 5.0) % 1.0) < 0.55
                            w_base[an_i] = np.where(slat_on[:, None], [224.0, 206.0, 168.0], [44.0, 38.0, 32.0]).astype(np.float32)
                        # Upper-floor white window surrounds & deep burgundy-red aluminum louvered shutters (using btd_b >= 0.75!)
                        up_band = (bh_b >= 4.2) & (btd_b >= 0.75) & (be_b >= 0.75)
                        up_surr = up_band & (((bh_b - 4.35) % 3.1) <= 1.85) & (((bu_b % 3.2) >= 0.72) & ((bu_b % 3.2) <= 2.28))
                        w_base[bi_b[up_surr]] = [236.0, 234.0, 226.0]
                        up_shut = (
                            up_band & (be_b >= 0.65)
                            & (((bh_b - 4.45) % 3.1) <= 1.65)
                            & ((((bu_b % 3.2) >= 0.38) & ((bu_b % 3.2) < 0.84)) | (((bu_b % 3.2) > 2.16) & ((bu_b % 3.2) <= 2.62)))
                        )
                        if up_shut.any():
                            us_i = bi_b[up_shut]
                            us_c = np.full((len(us_i), 3), [126.0, 40.0, 46.0], dtype=np.float32)
                            us_c[((bh_b[up_shut] * 5.0) % 1.0) < 0.28] *= 0.82
                            w_base[us_i] = us_c
                        # Ground-floor burgundy-red framed glass doors + upper casement windows with white mullions
                        gf_frame = (bh_b >= 0.95) & (bh_b <= 3.15) & (btd_b > 1.2) & (be_b >= 0.9) & (((bu_b % 3.4) >= 0.55) & ((bu_b % 3.4) <= 2.65))
                        w_base[bi_b[gf_frame]] = [122.0, 38.0, 44.0]
                        gf_arch = (bh_b >= 1.10) & (bh_b <= 3.00) & (btd_b > 1.2) & (be_b >= 1.05) & (((bu_b % 3.4) >= 0.72) & ((bu_b % 3.4) <= 2.48))
                        up_win = up_band & (be_b >= 0.95) & (((bh_b - 4.45) % 3.1) <= 1.65) & (((bu_b % 3.2) >= 0.86) & ((bu_b % 3.2) <= 2.14))
                        b_win = gf_arch | up_win
                        if b_win.any():
                            bw_g = bi_b[b_win]
                            bmull = np.abs((bu_b[b_win] % 3.2) - 1.50) < 0.08
                            if preset.is_night or (preset_key == "sunset" and gf_arch.any()):
                                lit_b = np.full(len(bw_g), preset.is_night, dtype=np.bool_) | gf_arch[b_win]
                                bw_col = np.where(lit_b[:, None], [255.0, 224.0, 144.0], [46.0, 62.0, 84.0]).astype(np.float32)
                                bw_col[bmull] = [236.0, 234.0, 226.0]
                                w_base[bw_g] = bw_col
                                f_mat[wi[bw_g]] = np.where(lit_b & (~bmull), M_WINDOW_LIT, M_WINDOW_DAY)
                            else:
                                bw_col = np.full((len(bw_g), 3), [52.0, 74.0, 98.0], dtype=np.float32)
                                bw_col[bmull] = [236.0, 234.0, 226.0]
                                w_base[bw_g] = bw_col
                                f_mat[wi[bw_g[~bmull]]] = M_WINDOW_DAY

                    # 1b. Schulhaus Dorfstrasse (id=1486, Dorfstrasse 41 — 19th-c. Neoclassical Primarschulhaus)
                    m_sd = c_bi == id_schul_dorf
                    if m_sd.any():
                        bi_sd = ci_l[m_sd]
                        sdh, sdu, sde, sdtd, sddc = c_h[m_sd], c_ul[m_sd], c_edg[m_sd], c_td[m_sd], c_dc[m_sd]
                        w_base[bi_sd[sdh < 3.6]] = [176.0, 174.0, 168.0]
                        sd_quoin = (sdh < 3.7) & (sde < 0.62) & ((np.floor(c_z[m_sd] * 2.2).astype(np.int32) & 1) == 0)
                        w_base[bi_sd[sd_quoin]] = [148.0, 146.0, 142.0]
                        sd_belt = ((sdh >= 3.55) & (sdh <= 3.85)) | ((sdh >= 7.10) & (sdh <= 7.35)) | (sdtd < 0.65)
                        w_base[bi_sd[sd_belt]] = [146.0, 146.0, 142.0]
                        sd_psurr = (sdh >= 0.15) & (sdh <= 3.15) & (np.abs(sddc) <= 1.45)
                        w_base[bi_sd[sd_psurr]] = [156.0, 154.0, 148.0]
                        sd_port = (sdh >= 0.2) & (sdh <= 2.95) & (np.abs(sddc) <= 1.10)
                        w_base[bi_sd[sd_port]] = [128.0, 142.0, 134.0]
                        sd_wsurr = (sdh >= 3.95) & (sdtd >= 0.95) & (sde >= 0.95) & (((sdh - 4.1) % 3.5) <= 2.20) & (((sdu % 3.4) >= 0.62) & ((sdu % 3.4) <= 2.48))
                        w_base[bi_sd[sd_wsurr]] = [142.0, 142.0, 138.0]
                        sd_win = (sdh >= 4.10) & (sdtd >= 1.10) & (sde >= 1.10) & (((sdh - 4.1) % 3.5) <= 1.98) & (((sdu % 3.4) >= 0.78) & ((sdu % 3.4) <= 2.32))
                        if sd_win.any():
                            sw_sd = bi_sd[sd_win]
                            smull = (np.abs((sdu[sd_win] % 3.4) - 1.55) < 0.08) | (np.abs(((sdh[sd_win] - 4.1) % 3.5) - 1.15) < 0.08)
                            scol_sd = np.full((len(sw_sd), 3), [255.0, 218.0, 130.0] if preset.is_night else [48.0, 72.0, 98.0], dtype=np.float32)
                            scol_sd[smull] = [242.0, 242.0, 238.0]
                            w_base[sw_sd] = scol_sd
                            f_mat[wi[sw_sd[~smull]]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY

                    # 2. v11 Gemeindehaus (856, 60) & Schulhaus Alte Landstrasse (868, 437) — NO facade clocks, NO wall shields!
                    m_gem = np.isin(c_bi, gem_all_arr)
                    if m_gem.any():
                        bi_g = ci_l[m_gem]
                        g_bi = c_bi[m_gem]
                        gh_g, gu_g, ge_g, gtd_g, gdc_g = c_h[m_gem], c_ul[m_gem], c_edg[m_gem], c_td[m_gem], c_dc[m_gem]
                        is_sal868 = g_bi == id_schul_al_868
                        is_gh_main = (g_bi == id_gem_main) | (g_bi == id_gem_wing)
                        # Schulhaus Alte Landstrasse (868): cool-grey rusticated granite base & corner quoins
                        sal_stone = is_sal868 & ((gh_g < 3.8) | (ge_g < 0.72))
                        w_base[bi_g[sal_stone]] = [152.0, 150.0, 146.0]
                        w_base[bi_g[sal_stone & ((gh_g % 0.55) < 0.08)]] *= 0.86
                        # Gemeindehaus (856/60): warm light-stone plaster plinth, belt course & oxidized copper eaves gutter
                        w_base[bi_g[is_gh_main & (gh_g < 3.5)]] = [196.0, 190.0, 176.0]
                        w_base[bi_g[is_gh_main & (gh_g >= 3.40) & (gh_g <= 3.65)]] = [218.0, 212.0, 198.0]
                        w_base[bi_g[is_gh_main & (gtd_g < 0.35)]] = [92.0, 134.0, 118.0]
                        w_base[bi_g[(~is_gh_main) & (gtd_g < 0.55)]] = [226.0, 220.0, 206.0]
                        # Entrance portico stone framing
                        g_port = (np.abs(gdc_g) <= 1.65) & (gh_g <= 3.6) & ((np.abs(gdc_g) >= 1.25) | (gh_g >= 3.15))
                        w_base[bi_g[g_port & is_gh_main]] = [138.0, 128.0, 114.0]
                        w_base[bi_g[g_port & is_sal868]] = [152.0, 150.0, 146.0]
                        # Olive-green louvered shutters on Gemeindehaus; dark forest-green blinds on Schulhaus 868
                        civ_band = (gh_g >= 4.4) & (gtd_g >= 1.4) & (ge_g >= 0.85) & (((gh_g - 4.4) % 3.4) <= 1.85)
                        u_g34 = gu_g % 3.4
                        g_shut = civ_band & (((u_g34 >= 0.42) & (u_g34 < 0.85)) | ((u_g34 > 2.25) & (u_g34 <= 2.68)))
                        w_base[bi_g[g_shut & (g_bi == id_gem_main)]] = [92.0, 108.0, 66.0]
                        w_base[bi_g[g_shut & is_sal868]] = [72.0, 102.0, 82.0]
                        arcade = (gh_g >= 0.35) & (gh_g <= 3.0) & (ge_g >= 1.5) & (((gu_g % 4.0) >= 0.9) & ((gu_g % 4.0) <= 2.9))
                        civ_w = civ_band & (ge_g >= 1.2) & ((u_g34 >= 0.85) & (u_g34 <= 2.25))
                        g_win = arcade | civ_w
                        if g_win.any():
                            gw_g = bi_g[g_win]
                            gmull = civ_w[g_win] & ((np.abs((gu_g[g_win] % 3.4) - 1.55) < 0.08) | (np.abs(((gh_g[g_win] - 4.4) % 3.4) - 0.92) < 0.08))
                            if preset.is_night:
                                occ_g = ((np.floor(gu_g[g_win] / 3.4).astype(np.int32) * 7 + np.floor(gh_g[g_win] / 3.4).astype(np.int32) * 13 + g_bi[g_win]) % 8) < 3
                                gcol_w = np.where(occ_g[:, None], [255.0, 218.0, 130.0], [24.0, 34.0, 48.0]).astype(np.float32)
                            else:
                                occ_g = np.zeros(len(gw_g), dtype=np.bool_)
                                gcol_w = np.full((len(gw_g), 3), [44.0, 64.0, 88.0], dtype=np.float32)
                            gcol_w[gmull] = [238.0, 238.0, 234.0]
                            w_base[gw_g] = gcol_w
                            f_mat[wi[gw_g[~gmull & occ_g]]] = M_WINDOW_LIT
                            f_mat[wi[gw_g[~gmull & (~occ_g)]]] = M_WINDOW_DAY

                    # 3. v11 C.F. Meyer-Haus (Alte Landstrasse 170 ONLY — exact world-Z anchored to street 489.65m & main eave 495.98m)
                    m_cfm = c_bi == id_cfm_1033
                    if m_cfm.any():
                        bi_m = ci_l[m_cfm]
                        mz_m, mu_m, me_m, mdc_m = c_z[m_cfm], c_ul[m_cfm], c_edg[m_cfm], c_dc[m_cfm]
                        mnx_m = c_nx[m_cfm]
                        is_east_gable = mnx_m > 0.45

                        plinth_m = mz_m <= 490.85
                        w_base[bi_m[plinth_m]] = [196.0, 194.0, 186.0]
                        plinth_lip = (mz_m > 490.78) & (mz_m <= 490.90)
                        w_base[bi_m[plinth_lip]] = [178.0, 176.0, 168.0]

                        long_m = (~is_east_gable) & (me_m >= 0.9) & (mz_m >= 490.95) & (mz_m <= 495.55)
                        l_bay = (mu_m % 2.90) - 1.45
                        l_z_win = ((mz_m >= 491.05) & (mz_m <= 492.55)) | ((mz_m >= 493.55) & (mz_m <= 495.20))
                        l_trim = long_m & l_z_win & (np.abs(l_bay) <= 0.62)
                        l_frame = long_m & l_z_win & (np.abs(l_bay) <= 0.54)
                        l_pane = long_m & (
                            ((mz_m >= 491.18) & (mz_m <= 492.42)) | ((mz_m >= 493.68) & (mz_m <= 495.07))
                        ) & (np.abs(l_bay) <= 0.46)
                        l_shut = long_m & l_z_win & (np.abs(l_bay) > 0.56) & (np.abs(l_bay) <= 0.96)

                        eg_gf = is_east_gable & (mz_m >= 491.05) & (mz_m <= 492.55) & (np.abs(np.abs(mdc_m) - 3.65) <= 1.05)
                        eg_gf_dx = np.abs(np.abs(mdc_m) - 3.65)
                        eg_1f_side = is_east_gable & (mz_m >= 493.55) & (mz_m <= 495.20) & (np.abs(np.abs(mdc_m) - 3.65) <= 1.05)
                        eg_1f_mid = is_east_gable & (mz_m >= 493.20) & (mz_m <= 495.25) & (np.abs(mdc_m) <= 1.15)
                        eg_att_mid = is_east_gable & (mz_m >= 496.55) & (mz_m <= 498.10) & (np.abs(mdc_m) <= 1.30)
                        eg_att_side = is_east_gable & (mz_m >= 496.55) & (mz_m <= 498.00) & (np.abs(np.abs(mdc_m) - 2.65) <= 0.85)
                        eg_att_dx = np.abs(np.abs(mdc_m) - 2.65)
                        eg_peak = is_east_gable & (mz_m >= 499.30) & (mz_m <= 500.20) & (np.abs(mdc_m) >= 0.12) & (np.abs(mdc_m) <= 0.88)

                        e_trim = (
                            (eg_gf & (eg_gf_dx <= 0.62))
                            | (eg_1f_side & (eg_gf_dx <= 0.62))
                            | (eg_1f_mid & (np.abs(mdc_m) <= 0.64))
                            | (eg_att_mid & (np.abs(mdc_m) <= 0.90))
                            | (eg_att_side & (eg_att_dx <= 0.45))
                            | eg_peak
                        )
                        e_frame = (
                            (eg_gf & (eg_gf_dx <= 0.54))
                            | (eg_1f_side & (eg_gf_dx <= 0.54))
                            | (eg_1f_mid & (np.abs(mdc_m) <= 0.56))
                            | (eg_att_mid & (np.abs(mdc_m) <= 0.82))
                            | (eg_att_side & (eg_att_dx <= 0.38))
                        )
                        e_pane = (
                            (eg_gf & (mz_m >= 491.18) & (mz_m <= 492.42) & (eg_gf_dx <= 0.46))
                            | (eg_1f_side & (mz_m >= 493.68) & (mz_m <= 495.07) & (eg_gf_dx <= 0.46))
                            | (eg_1f_mid & (mz_m >= 493.35) & (mz_m <= 495.12) & (np.abs(mdc_m) <= 0.46))
                            | (eg_att_mid & (mz_m >= 496.68) & (mz_m <= 497.96) & (np.abs(mdc_m) <= 0.72) & (np.abs(mdc_m) >= 0.08))
                            | (eg_att_side & (mz_m >= 496.68) & (mz_m <= 497.86) & (eg_att_dx <= 0.30))
                            | (eg_peak & (mz_m >= 499.42) & (mz_m <= 500.08) & (np.abs(mdc_m) >= 0.22) & (np.abs(mdc_m) <= 0.76))
                        )
                        e_shut = (
                            (eg_gf & (eg_gf_dx > 0.56) & (eg_gf_dx <= 0.96))
                            | (eg_1f_side & (eg_gf_dx > 0.56) & (eg_gf_dx <= 0.96))
                            | (eg_1f_mid & (np.abs(mdc_m) > 0.58) & (np.abs(mdc_m) <= 1.05))
                            | (eg_att_mid & (np.abs(mdc_m) > 0.84) & (np.abs(mdc_m) <= 1.26))
                            | (eg_att_side & (eg_att_dx > 0.40) & (eg_att_dx <= 0.80))
                        )

                        m_trim = l_trim | e_trim
                        m_frame = l_frame | e_frame
                        m_pane = l_pane | e_pane
                        m_shut = l_shut | e_shut

                        w_base[bi_m[m_trim]] = [66.0, 112.0, 84.0]
                        w_base[bi_m[m_frame]] = [238.0, 240.0, 236.0]
                        if m_shut.any():
                            ms_i = bi_m[m_shut]
                            ms_c = np.full((len(ms_i), 3), [54.0, 102.0, 76.0], dtype=np.float32)
                            ms_c[(mz_m[m_shut] % 0.20) < 0.06] *= 0.80
                            w_base[ms_i] = ms_c
                        if m_pane.any():
                            mp_g = bi_m[m_pane]
                            w_base[mp_g] = [255.0, 218.0, 130.0] if preset.is_night else [46.0, 68.0, 94.0]
                            f_mat[wi[mp_g]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY

                        # East gable flush spruce-green entrance door + small grey sandstone memorial plaque above
                        door_frame = is_east_gable & (mz_m >= 489.65) & (mz_m <= 492.22) & (np.abs(mdc_m) <= 0.72)
                        w_base[bi_m[door_frame]] = [186.0, 182.0, 172.0]
                        door_m = is_east_gable & (mz_m >= 489.70) & (mz_m <= 492.12) & (np.abs(mdc_m) <= 0.60)
                        w_base[bi_m[door_m]] = [64.0, 110.0, 84.0]
                        door_transom = is_east_gable & (mz_m >= 491.75) & (mz_m <= 492.05) & (np.abs(mdc_m) <= 0.48)
                        if door_transom.any():
                            dt_i = bi_m[door_transom]
                            w_base[dt_i] = [255.0, 222.0, 140.0] if preset.is_night else [224.0, 230.0, 232.0]
                            if preset.is_night:
                                f_mat[wi[dt_i]] = M_WINDOW_LIT
                        plaque_b = is_east_gable & (mz_m >= 492.26) & (mz_m <= 492.96) & (np.abs(mdc_m) <= 0.56)
                        w_base[bi_m[plaque_b]] = [142.0, 138.0, 130.0]
                        plaque_in = is_east_gable & (mz_m >= 492.34) & (mz_m <= 492.88) & (np.abs(mdc_m) <= 0.48)
                        w_base[bi_m[plaque_in]] = [168.0, 164.0, 156.0]

                        # East 1st-floor cantilevered wrought-iron balcony directly above door & plaque
                        balc_slab = is_east_gable & (mz_m >= 493.02) & (mz_m <= 493.22) & (np.abs(mdc_m) <= 1.35)
                        w_base[bi_m[balc_slab]] = [172.0, 170.0, 164.0]
                        balc_rail = is_east_gable & (mz_m > 493.22) & (mz_m <= 494.12) & (np.abs(mdc_m) <= 1.35) & (
                            (mz_m >= 494.00) | (np.abs(mdc_m) >= 1.24) | (((mdc_m + 1.35) % 0.28) < 0.08)
                        )
                        w_base[bi_m[balc_rail]] = [42.0, 46.0, 52.0]

                    # 4. v11 Sanatorium Kilchberg (est. 1867): Two-branch Historic (Haus A 633 & Haus C 81) vs Modernist (521, 483, 853, 655)
                    m_san = np.isin(c_bi, san_ids_arr)
                    if m_san.any():
                        bi_s = ci_l[m_san]
                        s_bi_m = c_bi[m_san]
                        sh_s, su_s, se_s, std_s, sdc_s = c_h[m_san], c_ul[m_san], c_edg[m_san], c_td[m_san], c_dc[m_san]
                        m_san_hist = np.isin(s_bi_m, san_hist_arr)
                        # Branch A: Historic white plaster + cornflower-blue louvered shutters (Haus A 633 & Haus C 81)
                        if m_san_hist.any():
                            hi_s = bi_s[m_san_hist]
                            hbi = s_bi_m[m_san_hist]
                            hh, hu, he, htd, hdc = sh_s[m_san_hist], su_s[m_san_hist], se_s[m_san_hist], std_s[m_san_hist], sdc_s[m_san_hist]
                            is_hc = hbi == id_san_81
                            plinth_h = (is_hc & (hh < 2.8)) | ((~is_hc) & (hh < 1.6))
                            w_base[hi_s[plinth_h]] = [208.0, 212.0, 216.0]
                            trim_h = ((hh >= 2.8) & ((hh % 3.4) < 0.24)) | (he < 0.55)
                            w_base[hi_s[trim_h]] = [214.0, 218.0, 222.0]
                            h_fl = np.floor(hh / 3.4).astype(np.int32)
                            h_inz = (hh - h_fl * 3.4) / 3.4
                            h_bay = (hu % 3.2) - 1.6
                            h_val = (he >= 0.85) & (htd >= 0.95) & ((h_fl >= 1) | (hh >= 2.6))
                            # Cornflower-blue louvered shutters
                            h_shut = h_val & (np.abs(h_bay) >= 0.56) & (np.abs(h_bay) <= 1.05) & (h_inz >= 0.24) & (h_inz <= 0.80)
                            if h_shut.any():
                                sh_idx = hi_s[h_shut]
                                sh_c = np.where(is_hc[h_shut, None], [86.0, 140.0, 204.0], [104.0, 148.0, 202.0]).astype(np.float32)
                                sh_c[(hh[h_shut] % 0.24) < 0.07] *= 0.86
                                w_base[sh_idx] = sh_c
                            # Crisp white window frames + glass
                            h_fr = h_val & (np.abs(h_bay) <= 0.56) & (h_inz >= 0.22) & (h_inz <= 0.82)
                            w_base[hi_s[h_fr]] = [244.0, 246.0, 248.0]
                            h_win = h_val & (np.abs(h_bay) <= 0.46) & (h_inz >= 0.28) & (h_inz <= 0.76)
                            if h_win.any():
                                hw_g = hi_s[h_win]
                                if preset.is_night:
                                    lit_h = (((np.floor(hu[h_win] / 3.2).astype(np.int32) ^ h_fl[h_win]) & 1) == 0)
                                    w_base[hw_g] = np.where(lit_h[:, None], [255.0, 220.0, 134.0], [34.0, 48.0, 72.0])
                                    f_mat[wi[hw_g]] = np.where(lit_h, M_WINDOW_LIT, M_WINDOW_DAY)
                                else:
                                    w_base[hw_g] = [56.0, 74.0, 94.0]
                                    f_mat[wi[hw_g]] = M_WINDOW_DAY
                            # Warm amber-oak entrance door on Haus C (81)
                            w_base[hi_s[is_hc & (hh < 2.5) & (np.abs(hdc) <= 0.75)]] = [168.0, 108.0, 52.0]
                        # Branch B: Modernist/Contemporary clinic wings (Haus B 521, Haus D 483, Haus E/F 853, Haus H 655)
                        m_san_mod = ~m_san_hist
                        if m_san_mod.any():
                            mi_s = bi_s[m_san_mod]
                            mbi = s_bi_m[m_san_mod]
                            mh, mu, me, mtd = sh_s[m_san_mod], su_s[m_san_mod], se_s[m_san_mod], std_s[m_san_mod]
                            w_base[mi_s[mtd < 0.35]] = [224.0, 226.0, 226.0]
                            w_base[mi_s[(mh >= 3.0) & ((mh % 3.3) < 0.14)]] = [216.0, 218.0, 218.0]
                            # Haus B (521) continuous ground/terrace ribbon glazing
                            hb_rib = (mbi == id_san_521) & (mh >= 0.5) & (mh <= 2.8) & (me >= 0.8)
                            if hb_rib.any():
                                hr_i = mi_s[hb_rib]
                                hr_mull = (mu[hb_rib] % 2.0) < 0.14
                                hr_col = [255.0, 222.0, 138.0] if (preset.is_night or preset_key == "sunset") else [52.0, 68.0, 86.0]
                                w_base[hr_i] = np.where(hr_mull[:, None], [168.0, 174.0, 180.0], hr_col)
                                f_mat[wi[hr_i[~hr_mull]]] = M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WINDOW_DAY
                            # Clean flush modern upper windows with thin dark-grey aluminum frames & light-grey blind header
                            m_fl = np.floor(mh / 3.3).astype(np.int32)
                            m_inz = (mh - m_fl * 3.3) / 3.3
                            m_bay = (mu % 3.6) - 1.8
                            m_val = (me >= 0.9) & (mtd >= 0.8) & (mh >= 3.2) & (np.abs(m_bay) <= 0.78) & (m_inz >= 0.28) & (m_inz <= 0.80)
                            w_base[mi_s[m_val]] = [64.0, 70.0, 78.0]
                            w_base[mi_s[m_val & (np.abs(m_bay) <= 0.68) & (m_inz >= 0.68)]] = [192.0, 196.0, 200.0]
                            m_win = m_val & (np.abs(m_bay) <= 0.68) & (m_inz >= 0.32) & (m_inz < 0.68)
                            if m_win.any():
                                mw_g = mi_s[m_win]
                                if preset.is_night:
                                    lit_m = (((np.floor(mu[m_win] / 3.6).astype(np.int32) ^ m_fl[m_win]) & 1) == 0)
                                    w_base[mw_g] = np.where(lit_m[:, None], [255.0, 222.0, 138.0], [34.0, 48.0, 72.0])
                                    f_mat[wi[mw_g]] = np.where(lit_m, M_WINDOW_LIT, M_WINDOW_DAY)
                                else:
                                    w_base[mw_g] = [54.0, 72.0, 92.0]
                                    f_mat[wi[mw_g]] = M_WINDOW_DAY

                    # 5. v11 Seebad Kilchberg 1968 Concrete-Wave & 2014 Hornberger Timber-Slat Bathhouse + Glass Kiosk
                    m_sb = np.isin(c_bi, seebad_ids_arr)
                    if m_sb.any():
                        bi_sb = ci_l[m_sb]
                        sb_bi = c_bi[m_sb]
                        sbh, sbu, sbtd = c_h[m_sb], c_ul[m_sb], c_td[m_sb]
                        is_kiosk = sb_bi == lm.get("seebad_kiosk", -1)
                        slat_gap = (~is_kiosk) & ((sbh % 0.30) < 0.09)
                        w_base[bi_sb[slat_gap]] *= 0.76
                        door_seam = (~is_kiosk) & (sbh >= 0.10) & (sbh <= 2.20) & (((sbu % 2.6) < 0.08) | (np.abs((sbu % 2.6) - 1.15) < 0.07))
                        w_base[bi_sb[door_seam]] *= 0.72
                        w_base[bi_sb[sbtd < 0.65]] = [182.0, 182.0, 178.0]
                        kiosk_gl = is_kiosk & (sbh >= 0.25) & (sbtd >= 0.65)
                        if kiosk_gl.any():
                            kg_i = bi_sb[kiosk_gl]
                            kg_mull = ((sbu[kiosk_gl] % 1.45) < 0.14) | (sbh[kiosk_gl] < 0.42)
                            kg_col = [255.0, 212.0, 126.0] if (preset.is_night or preset_key == "sunset") else [54.0, 78.0, 96.0]
                            w_base[kg_i] = np.where(kg_mull[:, None], [44.0, 48.0, 54.0], kg_col)
                            f_mat[wi[kg_i[kg_mull]]] = M_WALL
                            f_mat[wi[kg_i[~kg_mull]]] = M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WINDOW_DAY

                    # 5b. v11 Chez Fritz Lakeside Restaurant Pavilion (id=1660, Seestrasse 195b): panoramic glazing + Riviera awning
                    m_cfp = c_bi == id_chez_fritz_pav
                    if m_cfp.any():
                        bi_cfp = ci_l[m_cfp]
                        cfh, cfu, cftd = c_h[m_cfp], c_ul[m_cfp], c_td[m_cfp]
                        w_base[bi_cfp[cftd < 0.60]] = [236.0, 234.0, 228.0]
                        cf_gl = (cfh >= 0.45) & (cfh <= 3.30) & (cftd >= 0.60)
                        if cf_gl.any():
                            cg_i = bi_cfp[cf_gl]
                            cg_mull = ((cfu[cf_gl] % 1.50) < 0.14) | (cfh[cf_gl] < 0.65)
                            cg_col = [255.0, 214.0, 124.0] if (preset.is_night or preset_key == "sunset") else [62.0, 88.0, 108.0]
                            w_base[cg_i] = np.where(cg_mull[:, None], [48.0, 52.0, 58.0], cg_col)
                            f_mat[wi[cg_i[cg_mull]]] = M_WALL
                            f_mat[wi[cg_i[~cg_mull]]] = M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WINDOW_DAY
                        cf_awn = (cfh >= 2.85) & (cfh <= 3.35) & (cftd >= 0.60)
                        if cf_awn.any():
                            ca_i = bi_cfp[cf_awn]
                            ca_str = (np.floor(cfu[cf_awn] * 3.0).astype(np.int32) & 1) == 0
                            w_base[ca_i] = np.where(ca_str[:, None], [242.0, 238.0, 228.0], [58.0, 90.0, 68.0])
                            f_mat[wi[ca_i]] = M_WALL

                    # 6a. v11 Real Hallenbad Kilchberg (Hochweidstr. 10, id=1835): crisp white plaster + black-grid panoramic glass
                    m_hb_real = c_bi == id_hb_main
                    if m_hb_real.any():
                        bi_hbr = ci_l[m_hb_real]
                        hbr_h, hbr_u, hbr_e, hbr_td = c_h[m_hb_real], c_ul[m_hb_real], c_edg[m_hb_real], c_td[m_hb_real]
                        w_base[bi_hbr[hbr_h < 1.2]] = [188.0, 190.0, 188.0]
                        w_base[bi_hbr[hbr_td < 0.78]] = [238.0, 240.0, 238.0]
                        w_base[bi_hbr[(hbr_td >= 0.78) & (hbr_td < 1.02)]] = [44.0, 48.0, 52.0]
                        hbr_glass = (hbr_h >= 1.5) & (hbr_h <= 7.8) & (hbr_e >= 1.2)
                        if hbr_glass.any():
                            hg_i = bi_hbr[hbr_glass]
                            hb_mull = (
                                ((hbr_u[hbr_glass] % 2.1) < 0.18)
                                | (((hbr_h[hbr_glass] - 1.5) % 1.55) < 0.14)
                            )
                            glass_c = (
                                [218.0, 232.0, 224.0] if preset.is_night
                                else ([204.0, 214.0, 206.0] if preset_key == "sunset" else [62.0, 114.0, 128.0])
                            )
                            w_base[hg_i] = np.where(hb_mull[:, None], [34.0, 38.0, 42.0], glass_c)
                            f_mat[wi[hg_i[~hb_mull]]] = M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WINDOW_DAY

                    # 6b. v11 Sporthalle Hochweid (Hochweidstr. 13/13.1, id=1628 & id=1448): raw grey Sichtbeton concrete + dark clerestory
                    m_sh = (c_bi == id_hb_pool) | (c_bi == id_hb_entry)
                    if m_sh.any():
                        bi_sh = ci_l[m_sh]
                        sh_h, sh_u, sh_e, sh_td = c_h[m_sh], c_ul[m_sh], c_edg[m_sh], c_td[m_sh]
                        w_base[bi_sh[(sh_h % 1.4) < 0.10]] *= 0.92
                        w_base[bi_sh[sh_h < 0.9]] = [144.0, 146.0, 144.0]
                        w_base[bi_sh[sh_td < 0.45]] = [184.0, 186.0, 184.0]
                        sh_win = (sh_h >= 2.2) & (sh_h <= 4.4) & (sh_e >= 1.4)
                        if sh_win.any():
                            sw_i = bi_sh[sh_win]
                            sh_mull = (sh_u[sh_win] % 3.2) < 0.24
                            sw_c = [236.0, 212.0, 148.0] if preset.is_night else [44.0, 50.0, 56.0]
                            w_base[sw_i] = np.where(sh_mull[:, None], [156.0, 158.0, 156.0], sw_c)
                            f_mat[wi[sw_i[~sh_mull]]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY

                    # 7. v11 Broelberggut Estate (979, 1678, 1332) & Walled-Garden House (1074)
                    m_br = (c_bi == id_broel_manor) | np.isin(c_bi, broel_outb_arr) | (c_bi == id_broel_temp)
                    if m_br.any():
                        bi_br = ci_l[m_br]
                        br_bi = c_bi[m_br]
                        brh, bru, bre, brtd, brdc = c_h[m_br], c_ul[m_br], c_edg[m_br], c_td[m_br], c_dc[m_br]
                        is_tmp = br_bi == id_broel_temp
                        is_man = ~is_tmp
                        w_base[bi_br[is_man & (brh < 1.35)]] = [188.0, 180.0, 164.0]
                        w_base[bi_br[is_man & ((bre < 0.55) | ((brh >= 3.2) & (brh <= 3.55)))]] = [206.0, 200.0, 184.0]
                        br_fl = (brh % 3.4) / 3.4
                        br_bay = (bru % 3.6) - 1.8
                        br_val = is_man & (bre >= 1.0) & (brtd >= 1.0) & (brh >= 0.8)
                        w_base[bi_br[br_val & (br_fl >= 0.26) & (br_fl <= 0.80) & (np.abs(br_bay) <= 0.68)]] = [206.0, 200.0, 184.0]
                        w_base[bi_br[br_val & (br_fl >= 0.28) & (br_fl <= 0.78) & (np.abs(br_bay) <= 0.60)]] = [234.0, 232.0, 226.0]
                        w_base[bi_br[br_val & (br_fl >= 0.30) & (br_fl <= 0.76) & (np.abs(br_bay) > 0.60) & (np.abs(br_bay) <= 0.96)]] = [64.0, 70.0, 52.0]
                        br_pane = br_val & (br_fl >= 0.30) & (br_fl <= 0.76) & (np.abs(br_bay) <= 0.54)
                        if br_pane.any():
                            bp_i = bi_br[br_pane]
                            if preset.is_night or preset_key == "sunset":
                                fl_idx = np.floor(brh[br_pane] / 3.4).astype(np.int32)
                                bay_idx = np.floor(bru[br_pane] / 3.6).astype(np.int32)
                                win_h = ((br_bi[br_pane] * 73 + fl_idx * 31 + bay_idx * 17) & 0xFF)
                                lit_m = win_h < (120 if preset.is_night else 105)
                                w_base[bp_i] = np.where(lit_m[:, None], [252.0, 214.0, 126.0], [26.0, 34.0, 48.0]).astype(np.float32)
                                f_mat[wi[bp_i[lit_m]]] = M_WINDOW_LIT
                                f_mat[wi[bp_i[~lit_m]]] = M_WINDOW_DAY
                            else:
                                w_base[bp_i] = [48.0, 66.0, 88.0]
                                f_mat[wi[bp_i]] = M_WINDOW_DAY
                        w_base[bi_br[is_man & (brh >= 0.15) & (brh <= 2.9) & (np.abs(brdc) <= 0.88)]] = [78.0, 54.0, 38.0]
                        # Manor 2nd-upper-floor central black wrought-iron balcony on stone corbel slab
                        is_br_m = br_bi == id_broel_manor
                        w_base[bi_br[is_br_m & (brh >= 6.55) & (brh <= 6.85) & (np.abs(brdc) <= 1.35)]] = [196.0, 190.0, 176.0]
                        br_bal = is_br_m & (brh > 6.85) & (brh <= 7.75) & (np.abs(brdc) <= 1.35) & (
                            (brh >= 7.62) | (np.abs(brdc) >= 1.24) | (((brdc + 1.35) % 0.25) < 0.08)
                        )
                        w_base[bi_br[br_bal]] = [38.0, 40.0, 44.0]
                        # Walled-garden house (1074): simple cornice & modest unlit window
                        w_base[bi_br[is_tmp & (brtd < 0.55)]] = [208.0, 202.0, 188.0]
                        tmp_fd = is_tmp & (brh >= 0.5) & (brh <= 2.4) & (np.abs(brdc) <= 0.65)
                        if tmp_fd.any():
                            tf_i = bi_br[tmp_fd]
                            w_base[tf_i] = [30.0, 40.0, 54.0] if (preset.is_night or preset_key == "sunset") else [52.0, 72.0, 94.0]
                            f_mat[wi[tf_i]] = M_WINDOW_DAY

                    # 8. v11 Villa Spinnergut (1914 off-white + turquoise shutters) & TC Kilchberg Terracotta Pavilion (1287)
                    m_sp = (c_bi == id_spin_villa) | (c_bi == id_spin_pav) | (c_bi == id_tc_club)
                    if m_sp.any():
                        bi_sp = ci_l[m_sp]
                        sp_bi = c_bi[m_sp]
                        sph, spu, spe, sptd, spdc = c_h[m_sp], c_ul[m_sp], c_edg[m_sp], c_td[m_sp], c_dc[m_sp]
                        is_tc = sp_bi == id_tc_club
                        is_sv = ~is_tc
                        w_base[bi_sp[is_sv & (sph < 3.2)]] = [162.0, 160.0, 154.0]
                        w_base[bi_sp[is_sv & ((spe < 0.45) | (sptd < 0.65))]] = [174.0, 172.0, 166.0]
                        w_base[bi_sp[is_sv & (np.abs(spdc) <= 1.8) & (sph <= 4.2) & ((np.abs(spdc) >= 1.3) | (sph >= 3.5))]] = [184.0, 182.0, 176.0]
                        sp_win_v = is_sv & (spe >= 0.85) & (sptd >= 1.0) & (sph >= 1.2) & (((sph - 1.2) % 3.5) <= 1.85)
                        sp_u36 = spu % 3.6
                        sp_shut = sp_win_v & (((sp_u36 >= 0.45) & (sp_u36 < 0.90)) | ((sp_u36 > 2.30) & (sp_u36 <= 2.75)))
                        if sp_shut.any():
                            sh_i = bi_sp[sp_shut]
                            sh_louver = ((sph[sp_shut] % 0.22) < 0.08)
                            w_base[sh_i] = np.where(sh_louver[:, None], [54.0, 142.0, 136.0], [68.0, 168.0, 160.0])
                        sp_sill = is_sv & (spe >= 0.85) & (sptd >= 0.9) & (sph >= 1.0) & (((sph - 1.0) % 3.5) < 0.22) & ((sp_u36 >= 0.82) & (sp_u36 <= 2.38))
                        w_base[bi_sp[sp_sill]] = [170.0, 168.0, 162.0]
                        sp_win = sp_win_v & (sp_u36 >= 0.90) & (sp_u36 <= 2.30)
                        if sp_win.any():
                            sw_sp = bi_sp[sp_win]
                            sw_mull = (np.abs(sp_u36[sp_win] - 1.60) < 0.09) | (np.abs(((sph[sp_win] - 1.2) % 3.5) - 0.92) < 0.09)
                            w_base[sw_sp] = np.where(
                                sw_mull[:, None],
                                [234.0, 234.0, 230.0],
                                [255.0, 220.0, 134.0] if preset.is_night else [46.0, 68.0, 94.0],
                            )
                            f_mat[wi[sw_sp[~sw_mull]]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY
                        sp_cons = (sp_bi == id_spin_villa) & (c_nx[m_sp] > 0.35) & (sph >= 0.85) & (sph <= 3.35) & (np.abs(spdc) <= 2.4)
                        if sp_cons.any():
                            sc_i = bi_sp[sp_cons]
                            sc_mull = ((spu[sp_cons] % 1.15) < 0.14) | (np.abs(sph[sp_cons] - 2.15) < 0.12)
                            w_base[sc_i] = np.where(sc_mull[:, None], [236.0, 234.0, 226.0], [255.0, 220.0, 134.0] if (preset.is_night or preset_key == "sunset") else [66.0, 98.0, 122.0])
                            f_mat[wi[sc_i[~sc_mull]]] = M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WINDOW_DAY
                        # TC Kilchberg octagonal pavilion clubhouse: terracotta masonry + bold white overhanging fascia + veranda glazing
                        w_base[bi_sp[is_tc & (sptd < 0.65)]] = [238.0, 240.0, 238.0]
                        w_base[bi_sp[is_tc & (sptd >= 0.65) & (sptd < 1.05)]] *= 0.58
                        w_base[bi_sp[is_tc & (spe < 0.25) & (sptd >= 0.65)]] = [226.0, 228.0, 224.0]
                        tc_win = is_tc & (sph >= 0.65) & (sph <= 2.85) & (sptd >= 1.05) & (spe >= 0.45) & (((spu % 2.4) >= 0.22) & ((spu % 2.4) <= 2.18))
                        if tc_win.any():
                            tw_tc = bi_sp[tc_win]
                            w_base[tw_tc] = [255.0, 218.0, 130.0] if (preset.is_night or preset_key == "sunset") else [42.0, 56.0, 68.0]
                            f_mat[wi[tw_tc]] = M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WINDOW_DAY

                    # 9a. v11 Villa Sulzergut (1617, Seestrasse 237, built 1900): Authentic Swiss Chalet!
                    m_sz_ch = c_bi == id_sulzergut_chalet
                    if m_sz_ch.any():
                        bi_sz = ci_l[m_sz_ch]
                        szh, szu, sze, sztd, szdc = c_h[m_sz_ch], c_ul[m_sz_ch], c_edg[m_sz_ch], c_td[m_sz_ch], c_dc[m_sz_ch]
                        w_base[bi_sz[(szh >= 0.85) & (szh < 3.4)]] = [224.0, 220.0, 212.0]
                        w_base[bi_sz[szh < 0.85]] = [178.0, 174.0, 166.0]
                        erker_m = (szh >= 0.85) & (szh < 3.35) & (np.abs(szdc) <= 1.65)
                        w_base[bi_sz[erker_m]] = [104.0, 66.0, 48.0]
                        w_base[bi_sz[(szh >= 3.25) & (szh <= 3.55) & (np.abs(szdc) <= 1.85)]] = [98.0, 118.0, 102.0]
                        w_base[bi_sz[(szh >= 3.4) & ((szh % 0.42) < 0.08)]] *= 0.82
                        w_base[bi_sz[sztd < 0.55]] = [68.0, 44.0, 32.0]
                        bal_m = (szh >= 3.4) & (szh <= 4.35) & (sze >= 0.6)
                        w_base[bi_sz[bal_m]] = [112.0, 74.0, 52.0]
                        w_base[bi_sz[bal_m & ((szu % 0.34) < 0.10)]] = [76.0, 50.0, 36.0]
                        sz_fl = (szh % 3.3) / 3.3
                        sz_bay = (szu % 3.2) - 1.6
                        sz_val = (sze >= 0.9) & (sztd >= 0.85) & (szh >= 1.1)
                        w_base[bi_sz[sz_val & (sz_fl >= 0.28) & (sz_fl <= 0.78) & (np.abs(sz_bay) <= 0.62)]] = [236.0, 234.0, 228.0]
                        w_base[bi_sz[sz_val & (szh >= 3.4) & (sz_fl >= 0.30) & (sz_fl <= 0.76) & (np.abs(sz_bay) > 0.58) & (np.abs(sz_bay) <= 0.92)]] = [116.0, 128.0, 110.0]
                        sz_pane = sz_val & (sz_fl >= 0.32) & (sz_fl <= 0.74) & (np.abs(sz_bay) <= 0.48)
                        if sz_pane.any():
                            sp_sz = bi_sz[sz_pane]
                            w_base[sp_sz] = [255.0, 218.0, 130.0] if preset.is_night else [44.0, 62.0, 82.0]
                            f_mat[wi[sp_sz]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY

                    # 9b. Seestrasse 240 (1338, built 1896, across Seestrasse): Traditional cream-plaster villa
                    m_sz_1338 = c_bi == id_sulzergut_1338
                    if m_sz_1338.any():
                        bi_s2 = ci_l[m_sz_1338]
                        s2h, s2u, s2e, s2td = c_h[m_sz_1338], c_ul[m_sz_1338], c_edg[m_sz_1338], c_td[m_sz_1338]
                        w_base[bi_s2[(s2e < 0.45) | ((s2h >= 2.9) & ((s2h % 3.3) < 0.22))]] = [212.0, 206.0, 192.0]
                        s2_fl = (s2h % 3.3) / 3.3
                        s2_bay = (s2u % 3.5) - 1.75
                        s2_val = (s2e >= 1.0) & (s2td >= 1.0) & (s2h >= 0.8)
                        w_base[bi_s2[s2_val & (s2_fl >= 0.28) & (s2_fl <= 0.78) & (np.abs(s2_bay) <= 0.64)]] = [234.0, 230.0, 220.0]
                        w_base[bi_s2[s2_val & (s2_fl >= 0.30) & (s2_fl <= 0.76) & (np.abs(s2_bay) > 0.58) & (np.abs(s2_bay) <= 0.90)]] = [64.0, 92.0, 68.0]
                        s2_pane = s2_val & (s2_fl >= 0.30) & (s2_fl <= 0.76) & (np.abs(s2_bay) <= 0.52)
                        if s2_pane.any():
                            sp_s2 = bi_s2[s2_pane]
                            w_base[sp_s2] = [255.0, 220.0, 132.0] if preset.is_night else [46.0, 68.0, 94.0]
                            f_mat[wi[sp_s2]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY

                    # 10a. v11 Stockengut Two-Tone Hilltop Barns (barn_807 & mutterkuhstall_91): cream-yellow brick lower + dark espresso timber upper
                    m_st = np.isin(c_bi, stock_barns_arr)
                    if m_st.any():
                        bi_st = ci_l[m_st]
                        stz, stu, stdc, steave = c_z[m_st], c_ul[m_st], c_dc[m_st], c_eave[m_st]
                        d_eave = steave - stz
                        # Lower story (below eave - 0.6m, resilient to sloped DEM burial): pale cream-yellow Kalksandstein masonry + terracotta surrounds + dark espresso barn doors
                        low_st = d_eave > 0.6
                        w_base[bi_st[low_st]] = [218.0, 206.0, 172.0]
                        w_base[bi_st[low_st & ((stz % 0.45) < 0.06)]] *= 0.94
                        st_surr = low_st & (d_eave >= 1.15) & (d_eave <= 4.6) & (np.abs(stdc) <= 2.15)
                        w_base[bi_st[st_surr]] = [182.0, 118.0, 96.0]
                        b_door_st = low_st & (d_eave >= 1.45) & (d_eave <= 4.6) & (np.abs(stdc) <= 1.85)
                        w_base[bi_st[b_door_st]] = [56.0, 40.0, 30.0]
                        # Upper gable (above eave - 0.6m): dark weathered vertical timber board-and-batten + central hayloft bay
                        up_st = ~low_st
                        w_base[bi_st[up_st & ((stu % 0.44) < 0.10)]] *= 0.80
                        w_base[bi_st[(d_eave <= 0.0) & (d_eave >= -2.2) & (np.abs(stdc) <= 1.0)]] = [54.0, 40.0, 30.0]
                        w_base[bi_st[stz >= (steave - 0.15)]] = [58.0, 42.0, 32.0]

                    # 10b. v11 Baldernstrasse 88 (stockengut_barn_77): warm ochre-beige plaster + arched reddish-brown barn door
                    m_st77 = c_bi == id_stock_77
                    if m_st77.any():
                        bi_77 = ci_l[m_st77]
                        h77, dc77 = c_h[m_st77], c_dc[m_st77]
                        d77 = (h77 >= 0.1) & (h77 <= 3.4) & (np.abs(dc77) <= 1.6)
                        w_base[bi_77[d77]] = [118.0, 62.0, 46.0]

                # B3. Small Outbuildings, Boathouses, Garages & Bendlikon Pavilion (style 6)
                is_outb = w_sty == 6
                if is_outb.any():
                    oi = np.nonzero(is_outb)[0]
                    o_bi = w_bi[oi]
                    odc = d_center[oi]
                    oh = h_rel[oi]
                    oz = w_z[oi]
                    oeave = eave_z[oi]
                    owlen = wall_len[oi]
                    odb = w_dbin[oi]
                    # v11 Bendlikon Pavilion (Seestrasse 157.1, ZSG Wartehaeuschen): white ENE gable + Kilchberg Wappen,
                    # grey stone portico pillars on ENE, and dark-framed 4x4 multi-pane window on SSE side
                    is_bpav = o_bi == id_bend_pav
                    if is_bpav.any():
                        bpi_p = oi[is_bpav]
                        bph_p, bpz_p, bpeave_p, bpdc_p, bpnx_p, bpul_p = (
                            oh[is_bpav], oz[is_bpav], oeave[is_bpav], odc[is_bpav], norms_v[w_ft[bpi_p], 0], u_local[bpi_p]
                        )
                        is_ene_p = bpnx_p > 0.45
                        # Crisp white plastered ENE lake-facing gable triangle
                        w_base[bpi_p[is_ene_p & (bpz_p > (bpeave_p - 0.25))]] = [232.0, 232.0, 228.0]
                        # Kilchberg Wappen badge (blue shield + white cross/flower) centered in upper ENE gable
                        in_wap = is_ene_p & (bpz_p >= (bpeave_p + 0.15)) & (bpz_p <= (bpeave_p + 0.95)) & (np.abs(bpdc_p) <= 0.38)
                        w_base[bpi_p[in_wap]] = [26.0, 88.0, 168.0]
                        w_base[bpi_p[in_wap & (np.abs(bpdc_p) <= 0.14) & (np.abs(bpz_p - (bpeave_p + 0.55)) <= 0.16)]] = [242.0, 244.0, 246.0]
                        # ENE open sheltered portico arcade: 4 grey sandstone pillars flanking recessed waiting area
                        ene_arc = is_ene_p & (bph_p >= 0.15) & (bph_p <= 2.45) & (np.abs(bpdc_p) <= 2.35)
                        ene_pil = is_ene_p & (bph_p >= 0.05) & (bph_p <= 2.55) & (
                            (np.abs(np.abs(bpdc_p) - 2.20) <= 0.22) | (np.abs(np.abs(bpdc_p) - 0.78) <= 0.20)
                        )
                        w_base[bpi_p[ene_arc]] = [248.0, 206.0, 124.0] if (preset.is_night or preset_key == "sunset") else [54.0, 62.0, 66.0]
                        if (preset.is_night or preset_key == "sunset") and (ene_arc & (~ene_pil)).any():
                            f_mat[wi[bpi_p[ene_arc & (~ene_pil)]]] = M_WINDOW_LIT
                        w_base[bpi_p[ene_pil]] = [178.0, 178.0, 174.0]
                        # SSE side wall: single dark-framed 4x4 multi-pane window
                        sse_win = (~is_ene_p) & (bph_p >= 0.95) & (bph_p <= 2.15) & (np.abs(bpdc_p) <= 0.78)
                        if sse_win.any():
                            sw_i = bpi_p[sse_win]
                            sw_mull = (np.abs((bpdc_p[sse_win] % 0.40) - 0.20) < 0.04) | (np.abs(((bph_p[sse_win] - 0.95) % 0.32) - 0.16) < 0.04)
                            sw_col = [255.0, 214.0, 122.0] if (preset.is_night or preset_key == "sunset") else [48.0, 66.0, 84.0]
                            w_base[sw_i] = np.where(sw_mull[:, None], [44.0, 48.0, 52.0], sw_col)
                            f_mat[wi[sw_i[~sw_mull]]] = M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WINDOW_DAY

                    # v11 Lakeside Boathouses (Mönchhof, Morfanlage): walnut siding + Mönchhof am See open glass bar pavilion (825)
                    is_lboat = np.isin(o_bi, lakeside_boats_arr)
                    if is_lboat.any():
                        lbi = oi[is_lboat]
                        lb_bi = o_bi[is_lboat]
                        lbh, lbu, lbdc, lbtd = oh[is_lboat], u_local[lbi], odc[is_lboat], top_dist[lbi]
                        w_base[lbi[(lbu % 0.45) < 0.10]] *= 0.82
                        w_base[lbi[lbtd < 0.42]] = [234.0, 232.0, 226.0]
                        w_base[lbi[(lbh >= 0.1) & (lbh <= 2.45) & (np.abs(lbdc) <= 1.35)]] = [46.0, 34.0, 26.0]
                        # Mönchhof am See lakeside bar pavilion (moenchhof_boat_825): pale fascia + wide glazed bar doors
                        is_mh_b = lb_bi == id_mh_bar
                        if is_mh_b.any():
                            w_base[lbi[is_mh_b & (lbtd < 0.48)]] = [226.0, 228.0, 224.0]
                            mh_gl = is_mh_b & (lbh >= 0.20) & (lbh <= 2.55) & (np.abs(lbdc) <= 3.6)
                            if mh_gl.any():
                                mgi = lbi[mh_gl]
                                mg_mull = (lbu[mh_gl] % 1.20) < 0.12
                                mg_c = [255.0, 206.0, 118.0] if (preset.is_night or preset_key == "sunset") else [66.0, 88.0, 106.0]
                                w_base[mgi] = np.where(mg_mull[:, None], [54.0, 58.0, 64.0], mg_c)
                                f_mat[wi[mgi[~mg_mull]]] = M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WINDOW_DAY
                        lb_loft = (~is_mh_b) & (lbh >= 2.8) & (lbh <= 3.7) & (np.abs(lbdc) <= 0.42)
                        if lb_loft.any():
                            w_base[lbi[lb_loft]] = [255.0, 216.0, 124.0] if preset.is_night else [52.0, 72.0, 94.0]
                            f_mat[wi[lbi[lb_loft]]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY

                    reg_outb = (o_bi != id_bend_pav) & (~is_lboat)
                    o_hgnd = h_above_gnd[oi]
                    is_door_face = reg_outb & (((o_bi + odb) % 3) == 0) & (owlen >= 3.2)
                    gdoor = is_door_face & (np.abs(odc) <= 1.05) & (oh >= 0.08) & (oh <= 2.25) & (o_hgnd >= 0.0)
                    tiny_w = (
                        reg_outb
                        & (~is_door_face)
                        & (owlen >= 3.6)
                        & (np.abs(odc) <= 0.45)
                        & (oh >= 1.15)
                        & (oh <= 2.05)
                        & ((bldg_z0[o_bi] + 1.15) >= (w_local_dem[oi] + PLINTH_H + 0.05))
                    )
                    w_base[oi[gdoor]] = [92.0, 64.0, 44.0]
                    w_base[oi[tiny_w]] = [52.0, 68.0, 88.0]

                # B4. Residential Houses (0), Modern Villas (1) & Lindt Campus Wings (3) — F7 + F12 Vernacular Craft!
                is_res = (w_sty == 0) | (w_sty == 1) | (w_sty == 3)
                if is_res.any():
                    ri_l = np.nonzero(is_res)[0]
                    r_sty = w_sty[ri_l]
                    r_bi_w = w_bi[ri_l]
                    r_db = w_dbin[ri_l]
                    r_h = h_rel[ri_l]
                    r_z = w_z[ri_l]
                    r_n = w_n[ri_l]
                    r_e = w_e[ri_l]
                    r_eave = eave_z[ri_l]
                    r_wlen = wall_len[ri_l]
                    r_uloc = u_local[ri_l]
                    r_dc = d_center[ri_l]
                    r_edg = edge_dist[ri_l]
                    r_h_gnd = h_above_gnd[ri_l]
                    r_twx = tw_x_v[w_ft[ri_l]]
                    r_twy = tw_y_v[w_ft[ri_l]]
                    is_barn = (r_bi_w == id_barn_1490) | (r_bi_w == id_barn_1726)

                    slab_line = (r_sty == 1) & (r_wlen >= 9.0) & (r_h >= 2.8) & (r_h_gnd >= (PLINTH_H + 0.15)) & (((r_h % 3.15) < 0.24))
                    w_base[ri_l[slab_line]] *= 0.85

                    pilaster = (r_sty == 3) & (~((r_bi_w == id_lindt_main) & (r_n < 1241362.0))) & (r_bi_w != id_lindt_s1473) & (r_bi_w != id_lindt_s1720) & ((r_uloc % 10.5) < 0.55)
                    w_base[ri_l[pilaster]] = np.minimum(242.0, w_base[ri_l[pilaster]] * 1.05)

                    fl_h = np.where(r_sty == 3, 4.10, np.where(r_sty == 1, 3.15, 3.05))
                    bay_w = np.where(r_sty == 3, 3.60, np.where(r_sty == 1, 4.55, 3.85))

                    fl_idx = np.floor(r_h / fl_h).astype(np.int32)
                    in_z = (r_h - fl_idx * fl_h) / fl_h

                    n_bays = np.maximum(1, np.floor((r_wlen - 2.1) / bay_w).astype(np.int32))
                    grid_span = n_bays.astype(np.float32) * bay_w
                    u_start = 0.5 * (r_wlen - grid_span)
                    u_in_grid = r_uloc - u_start
                    bay_idx = np.floor(u_in_grid / bay_w).astype(np.int32)
                    bay_center_offset = u_in_grid - (bay_idx.astype(np.float32) + 0.5) * bay_w

                    # F12: Selective Riegelhaus half-timbered historic Dorf/Lebern farmhouses + v9.0 Hafenbeiz red Riegelhaus!
                    is_rieg = bldg_is_riegelhaus[r_bi_w]
                    if is_rieg.any():
                        r_horiz = (in_z < 0.08) | (np.abs(in_z - 0.30) < 0.05) | (np.abs(in_z - 0.78) < 0.05)
                        r_vert = (np.abs(bay_center_offset) > (bay_w * 0.44)) | (r_edg < 0.34)
                        r_diag = (r_edg < 1.35) & (np.abs((r_edg - 0.35) - (in_z * fl_h * 0.45)) < 0.14)
                        is_hbz = np.isin(r_bi_w, hafenbeiz_ids_arr)
                        is_ghus = r_bi_w == id_gotisch_hus
                        w_base[ri_l[is_rieg & (~is_hbz) & (~is_ghus) & (r_horiz | r_vert)]] = [84.0, 54.0, 38.0]
                        w_base[ri_l[is_rieg & (~is_hbz) & (~is_ghus) & r_diag]] = [88.0, 58.0, 40.0]
                        w_base[ri_l[is_rieg & is_ghus & (r_horiz | r_vert | r_diag)]] = [72.0, 54.0, 42.0]  # Gotisch Hus weathered oak Fachwerk
                        w_base[ri_l[is_rieg & is_ghus & (r_z > (r_eave + 0.3))]] = [126.0, 94.0, 62.0]       # Gotisch Hus honey-timber gable
                        w_base[ri_l[is_rieg & is_hbz & (r_horiz | r_vert | r_diag)]] = [128.0, 44.0, 38.0]  # Hafenbeiz weathered oxblood-red Riegelhaus

                    # v9.0 1899 Lindt Brick Wings (988, 1539): brick dentil cornice & steel loading-dock canopy
                    is_brick_ns_r = (r_bi_w == id_lindt_brick_n) | (r_bi_w == id_lindt_brick_s)
                    if is_brick_ns_r.any():
                        bns_td = top_dist[ri_l]
                        dentil_ns = is_brick_ns_r & (bns_td < 0.95) & (bns_td >= 0.40) & ((np.floor(r_uloc * 2.5).astype(np.int32) & 1) == 0)
                        w_base[ri_l[dentil_ns]] = [216.0, 200.0, 162.0]
                        w_base[ri_l[is_brick_ns_r & (r_h >= 3.55) & (r_h <= 4.05) & (r_edg >= 1.2)]] = [66.0, 72.0, 80.0]
                        w_base[ri_l[is_brick_ns_r & (r_h >= 3.25) & (r_h < 3.55) & (r_edg >= 1.2)]] *= 0.72

                    # v9.0 Dorf Barns (1490, 1726): board-and-batten timber siding, double barn doors & hayloft shutters
                    if is_barn.any():
                        w_base[ri_l[is_barn & ((r_uloc % 0.48) < 0.10)]] *= 0.84
                        w_base[ri_l[is_barn & (fl_idx == 0) & (np.abs(r_dc) <= 1.55) & (r_h >= 0.1) & (r_h <= 2.9)]] = [74.0, 48.0, 34.0]
                        w_base[ri_l[is_barn & (fl_idx == 1) & (np.abs(r_dc) <= 0.85) & (in_z >= 0.25) & (in_z <= 0.78)]] = [62.0, 42.0, 30.0]

                    # v9.0 Villa Naville (1582, 1695), Schooren Porcelain Quarter (981, 1823), Chez Fritz (1598) & Lakeside Villas
                    is_nav_w = (r_bi_w == id_nav_1582) | (r_bi_w == id_nav_1695)
                    if is_nav_w.any():
                        w_base[ri_l[is_nav_w & (r_h >= 2.8) & ((r_h % 3.05) < 0.24)]] = [236.0, 232.0, 222.0]
                        w_base[ri_l[is_nav_w & (fl_idx == 0) & (np.abs(r_dc) <= 1.35) & (r_h <= 3.1)]] = [228.0, 222.0, 208.0]
                    is_sch_w = (r_bi_w == id_sch_981) | (r_bi_w == id_sch_1823)
                    if is_sch_w.any():
                        w_base[ri_l[is_sch_w & (r_edg < 0.52) & ((np.floor(r_z * 1.4).astype(np.int32) & 1) == 0)]] = [198.0, 192.0, 180.0]
                        w_base[ri_l[is_sch_w & (fl_idx == 0) & (np.abs(r_dc) <= 1.65) & (r_h >= 2.55) & (r_h <= 2.95)]] = [226.0, 222.0, 212.0]
                        w_base[ri_l[is_sch_w & (fl_idx == 0) & (np.abs(r_dc) <= 1.35) & (r_h >= 0.1) & (r_h <= 2.65)]] = [78.0, 56.0, 42.0]
                    is_lvilla = np.isin(r_bi_w, moenchhof_villas_arr) | np.isin(r_bi_w, morfanlage_villas_arr)
                    if is_lvilla.any():
                        w_base[ri_l[is_lvilla & (r_h >= 2.8) & ((r_h % 3.05) < 0.20)]] = [226.0, 222.0, 212.0]

                    # F12: Dark walnut Swiss timber gable bargeboards on pitched style 0 gables!
                    z_gable_roof = bldg_z1[r_bi_w] - (bldg_z1[r_bi_w] - r_eave) * np.clip(np.abs(r_dc) / np.maximum(1.0, 0.5 * r_wlen), 0.0, 1.0)
                    on_barge = (
                        (r_sty == 0)
                        & (~is_sch_w)
                        & (~np.isin(r_bi_w, morfanlage_villas_arr))
                        & (r_wlen >= 5.2)
                        & ((bldg_z1[r_bi_w] - r_eave) >= 1.8)
                        & (r_z >= (r_eave - 0.15))
                        & (np.abs(z_gable_roof - r_z) <= 0.36)
                    )
                    if on_barge.any():
                        w_base[ri_l[on_barge]] = [78.0, 54.0, 38.0]

                    z_ceil = np.where(r_sty == 0, np.minimum(r_eave - 0.35, bldg_z1[r_bi_w] - 0.75), bldg_z1[r_bi_w] - 0.75)
                    in_grid_bounds = (
                        (r_wlen >= 3.5)
                        & (r_edg >= 1.15)
                        & (bay_idx >= 0)
                        & (bay_idx < n_bays)
                        & (r_z <= z_ceil)
                        & (r_h >= 0.85)
                    )

                    wall_hash = ((r_bi_w.astype(np.int64) * 2654435761) ^ (r_db.astype(np.int64) * 40503)) & 0xFF
                    bay_hash = ((r_bi_w.astype(np.int64) * 73856093) ^ (r_db.astype(np.int64) * 19349663) ^ (bay_idx.astype(np.int64) * 83492791)) & 0xFF

                    blank_narrow_wall = (r_wlen < 5.8) & ((wall_hash % 3) == 0) & (r_sty != 3)
                    solid_pier_bay = (
                        ((r_sty == 0) & (n_bays >= 3) & ((bay_hash % 4) == 1))
                        | ((r_sty == 1) & (n_bays >= 2) & ((bay_hash % 4) == 2))
                        | ((r_sty == 3) & ((bay_idx % 5) == 4) & (r_bi_w != id_lindt_s1473))
                    )

                    blind_tower_shaft = (r_bi_w == id_lindt_main) & (r_n >= 1241342.0) & (r_n < 1241362.0) & (r_e >= 2684225.0) & (r_h >= 5.2) & (r_h <= 19.8)
                    south_blind_floor = (
                        (((r_bi_w == id_lindt_main) & (r_n < 1241342.0)) | (r_bi_w == id_lindt_s1473) | (r_bi_w == id_lindt_s1720))
                        & (r_h >= 4.2)
                        & ((bldg_z1[r_bi_w] - r_z) > 4.4)
                    )

                    is_shop_gf = bldg_is_shopfront[r_bi_w] & (fl_idx == 0) & (r_wlen >= 6.5) & (r_edg >= 0.90)

                    is_door_bay = (r_sty == 0) & (fl_idx == 0) & (~is_shop_gf) & (bay_idx == (n_bays // 2)) & ((wall_hash % 2) == 0)
                    front_door = (
                        in_grid_bounds
                        & (~blank_narrow_wall)
                        & is_door_bay
                        & (np.abs(bay_center_offset) <= 0.56)
                        & (r_h >= 0.12)
                        & (r_h <= 2.22)
                        & (r_h_gnd >= 0.0)
                    )
                    if front_door.any():
                        w_base[ri_l[front_door]] = [92.0, 62.0, 42.0]

                    skip_gf_win = (r_sty == 0) & (fl_idx == 0) & (~is_shop_gf) & (((bay_hash >> 3) % 3) == 0)

                    half_w = np.where(
                        r_sty == 0,
                        0.56,
                        np.where(
                            r_sty == 3,
                            0.74,
                            np.where((bay_hash & 1) == 0, 0.94, 0.56),
                        ),
                    )
                    z_lo = np.where((r_sty == 1) & ((bay_hash & 1) == 0), 0.18, np.where(r_sty == 3, 0.36, 0.32))
                    z_hi = np.where(r_sty == 3, 0.82, 0.74)

                    # v12-M1C Fix 1: Whole-bay local-DEM clearance (zero stubby half-windows or vertically sliced windows!)
                    bay_ce = r_e - bay_center_offset * r_twx
                    bay_cn = r_n - bay_center_offset * r_twy
                    bay_span = np.where(r_sty == 0, half_w + 0.38, half_w + 0.18)
                    dem_bay_c = _sample_bilinear_05m(scene.dem, bay_ce, bay_cn)
                    dem_bay_l = _sample_bilinear_05m(scene.dem, bay_ce - bay_span * r_twx, bay_cn - bay_span * r_twy)
                    dem_bay_r = _sample_bilinear_05m(scene.dem, bay_ce + bay_span * r_twx, bay_cn + bay_span * r_twy)
                    bay_dem_max = np.maximum(dem_bay_c, np.maximum(dem_bay_l, dem_bay_r))
                    win_sill_z = bldg_z0[r_bi_w] + (fl_idx.astype(np.float32) + z_lo) * fl_h
                    above_plinth_win = (r_sty == 3) | (win_sill_z >= (bay_dem_max + PLINTH_H + 0.05))

                    active_bay = (
                        in_grid_bounds
                        & (~blank_narrow_wall)
                        & (~solid_pier_bay)
                        & (~is_door_bay)
                        & (~skip_gf_win)
                        & (~blind_tower_shaft)
                        & (~south_blind_floor)
                        & (~is_shop_gf)
                        & above_plinth_win
                    )

                    # F12: Modern Swiss Apartments (style 1) — Recessed Dark Balconies / Loggias with Glass/Steel Balustrades!
                    balc_bot_z = bldg_z0[r_bi_w] + (fl_idx.astype(np.float32) + 0.06) * fl_h
                    is_balc_bay = (
                        (r_sty == 1)
                        & (r_wlen >= 8.5)
                        & (fl_idx >= 1)
                        & active_bay
                        & (((bay_hash >> 2) % 3) == 0)
                        & (balc_bot_z >= (bay_dem_max + PLINTH_H + 0.10))
                    )
                    in_balc = is_balc_bay & (np.abs(bay_center_offset) <= np.minimum(1.38, 0.40 * bay_w)) & (in_z >= 0.06) & (in_z <= 0.80)
                    if in_balc.any():
                        bi_bl = ri_l[in_balc]
                        bz_bl = in_z[in_balc]
                        bco_bl = np.abs(bay_center_offset[in_balc])
                        bh_bl = bay_hash[in_balc]
                        # Upper recessed dark loggia interior + ceiling shadow
                        is_loggia = bz_bl >= 0.40
                        bl_c = np.full((len(bi_bl), 3), [64.0, 68.0, 76.0], dtype=np.float32)
                        bl_c[bz_bl > 0.72] = [44.0, 48.0, 56.0]
                        # Lower translucent laminated glass or bronze rail balustrade + steel handrail & posts
                        is_glass_bal = ~is_loggia
                        bl_c[is_glass_bal] = np.where(((bh_bl[is_glass_bal] & 1) == 0)[:, None], [114.0, 138.0, 158.0], [92.0, 86.0, 80.0])
                        bl_c[is_glass_bal & ((bco_bl > 1.24) | (bco_bl < 0.07))] = [144.0, 150.0, 158.0]
                        bl_c[(bz_bl >= 0.36) & (bz_bl <= 0.41)] = [206.0, 212.0, 218.0]
                        w_base[bi_bl] = bl_c

                    is_pane = (active_bay & (~is_balc_bay) & (in_z >= z_lo) & (in_z <= z_hi) & (np.abs(bay_center_offset) <= half_w)) | (
                        is_balc_bay & (in_z >= 0.42) & (in_z <= 0.74) & (np.abs(bay_center_offset) <= 0.75)
                    )

                    in_gable_peak = (
                        (r_sty == 0)
                        & (r_wlen >= 6.4)
                        & (r_z > (r_eave + 0.65))
                        & (r_z < (bldg_z1[r_bi_w] - 1.15))
                        & ((bldg_z1[r_bi_w] - r_eave) >= 2.6)
                        & (np.abs(r_dc) <= 0.50)
                        & (np.abs(r_z - (0.52 * r_eave + 0.48 * bldg_z1[r_bi_w])) <= 0.55)
                        & (r_h_gnd >= (PLINTH_H + 0.40))
                    )
                    is_pane |= in_gable_peak

                    # F12: Stone/White Gewande Window Surrounds on Traditional Swiss Houses (BEFORE shutters/panes!)
                    is_gewaende = (
                        (r_sty == 0)
                        & active_bay
                        & (~is_barn)
                        & (in_z >= (z_lo - 0.06))
                        & (in_z <= (z_hi + 0.06))
                        & (np.abs(bay_center_offset) <= (half_w + 0.13))
                        & (~is_pane)
                    )
                    if is_gewaende.any():
                        w_base[ri_l[is_gewaende]] = [226.0, 222.0, 212.0]

                    # Horizontal floor stringcourses / belt-courses on multi-story Swiss villas & apartments
                    if camera.mpp <= 0.16:
                        is_string = (r_sty <= 1) & (fl_idx >= 1) & (r_wlen >= 5.0) & (~is_barn) & (~is_balc_bay) & (r_z <= z_ceil) & (r_h_gnd >= (PLINTH_H + 0.15)) & (in_z < 0.055)
                        if is_string.any():
                            str_top = is_string & (in_z >= 0.025)
                            str_sh = is_string & (in_z < 0.025)
                            w_base[ri_l[str_top]] = np.minimum(244.0, w_base[ri_l[str_top]] * 1.07)
                            w_base[ri_l[str_sh]] *= 0.86

                    is_shutter = (
                        (r_sty == 0)
                        & active_bay
                        & (r_bi_w != id_sch_981)
                        & (r_bi_w != id_sch_1823)
                        & (~is_barn)
                        & (in_z >= z_lo)
                        & (in_z <= z_hi)
                        & (np.abs(bay_center_offset) > (half_w + 0.03))
                        & (np.abs(bay_center_offset) <= (half_w + 0.38))
                    )
                    if is_shutter.any():
                        sh_g = ri_l[is_shutter]
                        sb_id = r_bi_w[is_shutter]
                        sh_mode = sb_id % 6
                        is_nav_sh = (sb_id == id_nav_1582) | (sb_id == id_nav_1695)
                        is_gh_sh = sb_id == id_gotisch_hus
                        is_hbz_sh = np.isin(sb_id, hafenbeiz_ids_arr)
                        is_stock_sh = np.isin(sb_id, stock_houses_arr)
                        is_morf_sh = np.isin(sb_id, morfanlage_villas_arr)
                        sh_col = np.select(
                            [is_nav_sh, is_gh_sh, is_hbz_sh, is_stock_sh, is_morf_sh, sh_mode == 0, sh_mode == 1, sh_mode == 2, sh_mode == 3, sh_mode == 4],
                            [186.0, 82.0, 42.0, 44.0, 46.0, 46.0, 62.0, 68.0, 126.0, 92.0],
                            default=52.0,
                        )
                        sh_col_g = np.select(
                            [is_nav_sh, is_gh_sh, is_hbz_sh, is_stock_sh, is_morf_sh, sh_mode == 0, sh_mode == 1, sh_mode == 2, sh_mode == 3, sh_mode == 4],
                            [188.0, 108.0, 86.0, 82.0, 86.0, 86.0, 104.0, 124.0, 48.0, 66.0],
                            default=94.0,
                        )
                        sh_col_b = np.select(
                            [is_nav_sh, is_gh_sh, is_hbz_sh, is_stock_sh, is_morf_sh, sh_mode == 0, sh_mode == 1, sh_mode == 2, sh_mode == 3, sh_mode == 4],
                            [186.0, 86.0, 58.0, 54.0, 58.0, 58.0, 162.0, 110.0, 46.0, 46.0],
                            default=68.0,
                        )
                        sh_rgb = np.stack([sh_col, sh_col_g, sh_col_b], axis=1)
                        if camera.mpp <= 0.16:
                            louver = ((r_z[is_shutter] * 4.6) % 1.0) < 0.34
                            sh_rgb[louver] *= 0.80
                        w_base[sh_g] = sh_rgb

                    # Projecting sunlit windowsill + crisp cast shadow beneath sill + top head lintel shadow
                    is_sill = active_bay & (~is_balc_bay) & (in_z >= (z_lo - 0.08)) & (in_z < z_lo) & (np.abs(bay_center_offset) <= (half_w + 0.14))
                    w_base[ri_l[is_sill]] = np.minimum(248.0, w_base[ri_l[is_sill]] * 1.15)
                    if camera.mpp <= 0.16:
                        is_sill_sh = active_bay & (~is_balc_bay) & (in_z >= (z_lo - 0.13)) & (in_z < (z_lo - 0.08)) & (np.abs(bay_center_offset) <= (half_w + 0.12))
                        w_base[ri_l[is_sill_sh]] *= 0.68
                    is_head_drop = active_bay & (~is_balc_bay) & (in_z > z_hi) & (in_z <= (z_hi + 0.06)) & (np.abs(bay_center_offset) <= (half_w + 0.06))
                    w_base[ri_l[is_head_drop]] *= 0.70

                    # F12: ~25% Swiss Red & Pink Geranium Window Boxes on Traditional Village Windowsills!
                    has_flowerbox = (r_sty == 0) & active_bay & (~is_barn) & ((bay_hash & 3) == 0) & (fl_idx >= 0)
                    in_fbox = has_flowerbox & (in_z >= (z_lo - 0.10)) & (in_z <= (z_lo + 0.04)) & (np.abs(bay_center_offset) <= (half_w * 0.88))
                    if in_fbox.any():
                        fi_b = ri_l[in_fbox]
                        f_hash = ((np.floor(r_uloc[in_fbox] * 5.0).astype(np.int32) * 73856093) ^ (np.floor(r_z[in_fbox] * 6.0).astype(np.int32) * 19349663)) & 15
                        fb_col = np.full((len(fi_b), 3), [52.0, 110.0, 48.0], dtype=np.float32)
                        fb_col[f_hash < 5] = [214.0, 48.0, 52.0]
                        fb_col[(f_hash >= 5) & (f_hash < 8)] = [226.0, 96.0, 122.0]
                        fb_col[in_z[in_fbox] < (z_lo[in_fbox] - 0.05)] = [124.0, 72.0, 46.0]
                        w_base[fi_b] = fb_col

                    if is_pane.any():
                        p_sub = np.nonzero(is_pane)[0]
                        p_local = ri_l[p_sub]
                        p_global = wi[p_local]
                        p_bi = r_bi_w[p_sub]
                        p_fl = fl_idx[p_sub]
                        p_bay = bay_idx[p_sub]
                        p_inz = in_z[p_sub]
                        p_bco = bay_center_offset[p_sub]
                        p_zlo = z_lo[p_sub]
                        p_zhi = z_hi[p_sub]
                        p_hw = half_w[p_sub]
                        p_sty = r_sty[p_sub]
                        hval = ((p_bi.astype(np.int64) * 73856093) ^ (p_fl.astype(np.int64) * 40503) ^ (p_bay.astype(np.int64) * 12289)) & 0xFF
                        is_brick_munt = (p_sty == 3) & ((p_bi == id_lindt_brick_n) | (p_bi == id_lindt_brick_s) | ((p_bi == id_lindt_main) & (r_n[p_sub] >= 1241403.0)))
                        bm_grid = is_brick_munt & (
                            (np.abs(p_inz - 0.52) < 0.04) | (np.abs(p_inz - 0.68) < 0.04)
                            | (np.abs(p_bco) < 0.07) | (np.abs(np.abs(p_bco) - 0.36) < 0.05)
                        )
                        is_tavern_lit = np.isin(p_bi, hafenbeiz_ids_arr) & (p_fl <= 2)
                        hi_res_w = camera.mpp <= 0.16
                        win_reveal = hi_res_w & ((np.abs(p_bco) >= (p_hw - 0.065)) | (p_inz <= (p_zlo + 0.045)))
                        mullion = (np.abs(p_bco) < (0.06 if hi_res_w else 0.08)) | (hi_res_w & (np.abs(p_inz - (0.5 * (p_zlo + p_zhi))) < 0.032))

                        if preset.is_night:
                            lit = (hval < 138) | is_tavern_lit
                            warm_alt = (hval & 3) == 0
                            v_norm = np.clip((p_inz - p_zlo) / np.maximum(0.15, p_zhi - p_zlo), 0.0, 1.0)
                            int_grad = (1.06 - 0.24 * v_norm)[:, None]
                            lit_c = np.where(warm_alt[:, None], [255.0, 228.0, 148.0], [255.0, 192.0, 92.0]) * int_grad
                            pane_c = np.where(lit[:, None], np.clip(lit_c, 0.0, 255.0), [28.0, 40.0, 62.0]).astype(np.float32)
                            if hi_res_w:
                                pane_c[mullion & lit] *= 0.62
                                pane_c[win_reveal] *= 0.58
                            pane_c[bm_grid] = [98.0, 82.0, 62.0]
                            w_base[p_local] = pane_c
                            f_mat[p_global] = np.where(lit & (~bm_grid) & (~win_reveal), M_WINDOW_LIT, M_WINDOW_DAY)
                        elif preset_key == "sunset":
                            lit_dusk = (hval < 52) | is_tavern_lit
                            upper_glint = (p_inz - p_bco * 0.28) > 0.56 if hi_res_w else (p_inz > 0.56)
                            pane_c = np.where(upper_glint[:, None], [118.0, 104.0, 124.0], [34.0, 42.0, 64.0]).astype(np.float32)
                            pane_c[p_inz > (p_zhi - 0.07)] *= 0.54
                            pane_c[mullion] = [204.0, 194.0, 180.0]
                            if hi_res_w:
                                pane_c[win_reveal] = [36.0, 34.0, 44.0]
                            pane_c[lit_dusk & (~win_reveal)] = [255.0, 206.0, 114.0]
                            pane_c[bm_grid] = [164.0, 154.0, 144.0]
                            w_base[p_local] = pane_c
                            f_mat[p_global] = np.where(lit_dusk & (~bm_grid) & (~win_reveal), M_WINDOW_LIT, M_WINDOW_DAY)
                        else:
                            # v12: Crisp tinyrj.com deep blue-slate panes (#1E3548-#20374A) + sharp light mullions!
                            upper_glint = (p_inz - p_bco * 0.30) > 0.56 if hi_res_w else (p_inz > 0.56)
                            pane_c = np.where(upper_glint[:, None], [68.0, 104.0, 136.0], [30.0, 53.0, 72.0]).astype(np.float32)
                            pane_c[p_inz > (p_zhi - 0.07)] *= 0.54
                            pane_c[mullion] = [216.0, 214.0, 206.0]
                            if hi_res_w:
                                pane_c[win_reveal] = [28.0, 36.0, 46.0]
                            pane_c[bm_grid] = [186.0, 182.0, 174.0]
                            w_base[p_local] = pane_c
                            f_mat[p_global] = M_WINDOW_DAY

                    # v11 Lakeside Villa wrought-iron balcony balustrades (Villa Naville has no dark iron balconies; Chez Fritz 1598 awning removed)
                    is_balc_v = is_lvilla & (fl_idx >= 1) & active_bay & (in_z >= 0.08) & (in_z <= 0.32) & (np.abs(bay_center_offset) <= 0.92)
                    if is_balc_v.any():
                        w_base[ri_l[is_balc_v]] = [56.0, 60.0, 68.0]
                    # v11 Hafenbeiz (id=243) above-DEM ground-floor east-facing glass Wintergarten conservatory (strictly AFTER is_pane!)
                    r_nx_w = norms_v[w_ft[ri_l], 0]
                    is_hbz_wg = (r_bi_w == id_hafenbeiz_243) & (r_nx_w > 0.35) & (r_h >= 3.05) & (r_h <= 5.75) & (r_edg >= 0.85)
                    if is_hbz_wg.any():
                        wgi = ri_l[is_hbz_wg]
                        wg_mull = ((r_uloc[is_hbz_wg] % 1.35) < 0.14) | (np.abs(r_h[is_hbz_wg] - 5.60) < 0.14) | (r_h[is_hbz_wg] < 3.40)
                        wg_glass = [255.0, 208.0, 118.0] if (preset.is_night or preset_key == "sunset") else [68.0, 96.0, 112.0]
                        w_base[wgi] = np.where(wg_mull[:, None], [68.0, 74.0, 70.0], wg_glass)
                        f_mat[wi[wgi[wg_mull]]] = M_WALL
                        f_mat[wi[wgi[~wg_mull]]] = M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WINDOW_DAY

                    # F12: Sunlit Striped Swiss Sonnenstoren Sun Awnings on style 1 (Day & Sunset ONLY!)
                    if not preset.is_night:
                        r_norm_w = norms_v[w_ft[ri_l]]
                        sunlit_face = (r_norm_w[:, 0] * 0.75 - r_norm_w[:, 1] * 0.65) > 0.15
                        has_awning = (r_sty == 1) & active_bay & (fl_idx >= 1) & ((bay_hash % 5) == 0) & sunlit_face
                        in_awn = has_awning & (in_z >= 0.68) & (in_z <= 0.84) & (np.abs(bay_center_offset) <= (half_w + 0.25))
                        if in_awn.any():
                            ai_w = ri_l[in_awn]
                            ab_id = r_bi_w[in_awn] % 3
                            str_w = (np.floor(r_uloc[in_awn] * 3.8).astype(np.int32) & 1) == 0
                            a_col = np.select(
                                [ab_id == 0, ab_id == 1],
                                [216.0, 56.0],
                                default=188.0,
                            )
                            a_col_g = np.select(
                                [ab_id == 0, ab_id == 1],
                                [168.0, 114.0],
                                default=76.0,
                            )
                            a_col_b = np.select(
                                [ab_id == 0, ab_id == 1],
                                [58.0, 70.0],
                                default=54.0,
                            )
                            awn_rgb = np.stack([a_col, a_col_g, a_col_b], axis=1)
                            w_base[ai_w] = np.where(str_w[:, None], [236.0, 232.0, 220.0], awn_rgb)
                            f_mat[wi[ai_w]] = M_WALL
                        in_awn_sh = has_awning & (in_z >= 0.62) & (in_z < 0.68) & (np.abs(bay_center_offset) <= (half_w + 0.22))
                        if in_awn_sh.any():
                            w_base[ri_l[in_awn_sh]] *= 0.68

                    # F12: Bahnhofstrasse & Commercial Seestrasse Ground-Floor Glazed Shopfronts + Cafe Awnings!
                    shop_area = is_shop_gf & (r_h >= 0.22) & (r_h <= 2.95) & (r_h_gnd >= 0.0)
                    if shop_area.any():
                        si_s = np.nonzero(shop_area)[0]
                        sh_u = r_uloc[si_s]
                        sh_h = r_h[si_s]
                        sh_bi = r_bi_w[si_s]
                        in_disp = ((sh_u % 3.6) >= 0.35) & ((sh_u % 3.6) <= 3.25) & (sh_h >= 0.45) & (sh_h <= 2.55)
                        if in_disp.any():
                            di_l = ri_l[si_s[in_disp]]
                            if preset.is_night:
                                w_base[di_l] = [255.0, 224.0, 148.0]
                                f_mat[wi[di_l]] = M_WINDOW_LIT
                            elif preset_key == "sunset":
                                w_base[di_l] = [242.0, 196.0, 116.0]
                                f_mat[wi[di_l]] = M_WINDOW_LIT
                            else:
                                low_m = sh_h[in_disp] < 1.45
                                w_base[di_l] = np.where(low_m[:, None], [86.0, 78.0, 66.0], [44.0, 62.0, 82.0])
                                f_mat[wi[di_l]] = M_WINDOW_DAY
                        in_cafe_awn = (sh_h > 2.55) & (sh_h <= 2.95)
                        if in_cafe_awn.any():
                            ca_l = ri_l[si_s[in_cafe_awn]]
                            ca_str = (np.floor(sh_u[in_cafe_awn] * 3.5).astype(np.int32) & 1) == 0
                            ca_alt = (sh_bi[in_cafe_awn] & 1) == 0
                            ca_base = np.where(ca_alt[:, None], [164.0, 52.0, 54.0], [48.0, 102.0, 64.0])
                            w_base[ca_l] = np.where(ca_str[:, None], [236.0, 230.0, 216.0], ca_base)
                            f_mat[wi[ca_l]] = M_WALL

                # v12-M1C Fix 1: Clean Swiss Stone/Concrete Foundation Plinth (Sockel) from local_dem to local_dem + PLINTH_H
                # Strictly scoped to regular residential/modern/outbuilding walls — ZERO impact on landmarks or signage!
                is_plinth_bldg = (
                    ((w_sty == 0) | (w_sty == 1) | (w_sty == 6))
                    & (~is_chimney)
                    & (~is_mauer)
                    & (w_bi != id_bend_pier)
                    & (w_bi != id_bend_pav)
                    & (~np.isin(w_bi, lakeside_boats_arr))
                    & (w_bi != id_hafenbeiz_243)
                    & (w_bi != id_barn_1490)
                    & (w_bi != id_barn_1726)
                    & (~bldg_is_shopfront[w_bi])
                )
                in_plinth_zone = is_plinth_bldg & (h_above_gnd < (PLINTH_H + 0.06))
                if in_plinth_zone.any():
                    pl_i = np.nonzero(in_plinth_zone)[0]
                    pl_h = h_above_gnd[pl_i]
                    pl_sty = w_sty[pl_i]
                    # Clean cel-shaded Swiss limestone (sty 0) / architectural concrete (sty 1, 6) albedo
                    pl_col = np.where(
                        (pl_sty == 0)[:, None],
                        np.array([168.0, 165.0, 158.0], dtype=np.float32),
                        np.array([158.0, 160.0, 162.0], dtype=np.float32),
                    )
                    # Subtle 1-2 px horizontal water-table trim (Sockelgesims) at top of plinth
                    is_cap = pl_h >= (PLINTH_H - 0.04)  # [0.76, 0.86] m (~1 px sunlit drip-ledge)
                    is_cap_sh = (pl_h >= (PLINTH_H - 0.14)) & (~is_cap)  # [0.66, 0.76] m (~1 px under-ledge shadow)
                    cap_col = np.where(
                        (pl_sty == 0)[:, None],
                        np.array([196.0, 194.0, 188.0], dtype=np.float32),
                        np.array([188.0, 190.0, 192.0], dtype=np.float32),
                    )
                    pl_col[is_cap] = cap_col[is_cap]
                    pl_col[is_cap_sh] *= 0.86
                    # Subtle ground-contact AO band right at local_dem ([0.0, 0.18] m, ~1.5 px)
                    pl_col[pl_h < 0.18] *= 0.82
                    w_base[pl_i] = pl_col
                    f_mat[wi[pl_i]] = M_WALL

                # v9.1: real-typeface lettering baked into the facade plane (see pipeline/signage.py)
                if not hasattr(scene, "_signs_resolved"):
                    scene._signs_resolved = _signage.resolve_signs(scene, camera.azimuth_from_deg)
                _signage.bake_signs(
                    scene._signs_resolved, w_bi, w_dbin, w_e, w_n, w_z,
                    w_base, f_mat, wi, M_WINDOW_LIT, preset_key, preset.is_night,
                )
                if not hasattr(scene, "_clocks_resolved"):
                    scene._clocks_resolved = _signage.resolve_clocks(scene, camera.azimuth_from_deg)
                _signage.bake_clocks(
                    scene._clocks_resolved, w_bi, w_dbin, w_e, w_n, w_z,
                    w_base, f_mat, wi, M_WINDOW_LIT, preset_key, preset.is_night,
                )
                f_col[wi] = w_base

            zbuf[fy, fx] = fd
            rgb_buf[fy, fx] = f_col
            mat_buf[fy, fx] = f_mat
            obj_buf[fy, fx] = bi + 1
            norm_buf[fy, fx] = f_norm

            # F8/v12-M1B: NEVER apply noisy 0.5 m LiDAR DSM/CHM ray_rel_05m shadows to building fragments
            # (eliminates 100% of vertical comb streaks, ragged dark-grey blotches & 1px speckles on facades/balconies!).
            # Buildings receive crisp 4-step directional cel-shading from LOD2 normals + smooth Contact AO;
            # ground/roads/lawns retain 100% of crisp sh_ground_05m cast shadows.
            shadow_buf[fy, fx] = False

            # v12-M1B: Pixel-exact, gap-free, same-building screen-space flat-roof parapet coping & inner shadow
            # (replaces noisy 25 cm nearest-neighbor roof_edge_25cm speckles; immune to ortho_roof_smooth_05m grass bleed!)
            no_parapet_buf = np.zeros((H, W), dtype=bool)
            no_parapet_buf[fy, fx] = f_no_parapet
            flat_rf_geom = (mat_buf == M_ROOF) & (norm_buf[:, :, 2] >= 0.93) & (obj_buf > 0) & (obj_buf < 100000)
            if flat_rf_geom.any():
                def _erode_same_bldg(mask: np.ndarray) -> np.ndarray:
                    same_h = mask[:, :-1] & mask[:, 1:] & (obj_buf[:, :-1] == obj_buf[:, 1:])
                    same_v = mask[:-1, :] & mask[1:, :] & (obj_buf[:-1, :] == obj_buf[1:, :])
                    inner = mask.copy()
                    inner[:, 1:] &= same_h
                    inner[:, :-1] &= same_h
                    inner[1:, :] &= same_v
                    inner[:-1, :] &= same_v
                    return inner

                inner1 = _erode_same_bldg(flat_rf_geom)
                inner2 = _erode_same_bldg(inner1)
                if camera.mpp <= 0.16:
                    inner3 = _erode_same_bldg(inner2)
                    coping_px = flat_rf_geom & (~inner2) & (~no_parapet_buf)
                    parapet_sh = inner2 & (~inner3) & (~no_parapet_buf)
                    del inner3
                else:
                    coping_px = flat_rf_geom & (~inner1) & (~no_parapet_buf)
                    parapet_sh = inner1 & (~inner2) & (~no_parapet_buf)

                if coping_px.any():
                    c_base = scene.bldg_clean_roof_rgb[obj_buf[coping_px] - 1]
                    rgb_buf[coping_px] = np.clip(
                        c_base * 0.25 + np.array([156.0, 154.0, 148.0], dtype=np.float32),
                        174.0,
                        232.0,
                    )
                    if id_hb_main >= 0:
                        hb_c = coping_px & (obj_buf == (id_hb_main + 1))
                        if hb_c.any():
                            rgb_buf[hb_c] = [232.0, 234.0, 232.0]
                    if id_hb_pool >= 0 or id_hb_entry >= 0:
                        sh_c = coping_px & (
                            ((obj_buf == (id_hb_pool + 1)) if id_hb_pool >= 0 else False)
                            | ((obj_buf == (id_hb_entry + 1)) if id_hb_entry >= 0 else False)
                        )
                        if sh_c.any():
                            rgb_buf[sh_c] = [174.0, 176.0, 174.0]
                if parapet_sh.any():
                    rgb_buf[parapet_sh] *= 0.80
                del inner1, inner2, coping_px, parapet_sh
            del no_parapet_buf, flat_rf_geom

    # Slender 1px corner pillars for open Flugdach canopies (strictly active_mask clipped!)
    for b in scene.buildings:
        if b["objektart"] in ("Flugdach", "Offenes Gebaeude"):
            be_c, bn_c = b["e"], b["n"]
            if crop_box_lv95 is not None:
                if not (crop_box_lv95[0] + 2 <= be_c <= crop_box_lv95[2] - 2 and crop_box_lv95[1] + 2 <= bn_c <= crop_box_lv95[3] - 2):
                    continue
            rc_fl = int(np.clip((N_MAX - bn_c) / GRID_RES, 0, GRID_H - 1))
            cc_fl = int(np.clip((be_c - E_MIN) / GRID_RES, 0, GRID_W - 1))
            if not active_mask[rc_fl, cc_fl]:
                continue
            hw = b["footprint_w"] * 0.38
            hl = b["footprint_l"] * 0.38
            for sx_o in (-hw, hw):
                for sy_o in (-hl, hl):
                    zs = np.arange(b["z_ground"], b["z_roof"] - 0.2, max(0.06, camera.mpp * 0.55))
                    if len(zs) == 0:
                        continue
                    px, py, pd = camera.project(np.full_like(zs, be_c + sx_o), np.full_like(zs, bn_c + sy_o), zs)
                    ix, iy = np.round(px + shift_x).astype(np.int32), np.round(py + shift_y).astype(np.int32)
                    vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
                    ix, iy, pd = ix[vm], iy[vm], pd[vm]
                    w_m = pd < zbuf[iy, ix]
                    zbuf[iy[w_m], ix[w_m]] = pd[w_m]
                    rgb_buf[iy[w_m], ix[w_m]] = [82.0, 86.0, 94.0]
                    mat_buf[iy[w_m], ix[w_m]] = M_WALL
                    obj_buf[iy[w_m], ix[w_m]] = b["idx"] + 1

    # F12: Overhead stainless-steel cocoa transfer pipes connecting the 6 adjacent Lindt silos!
    silo_list = [b for b in scene.buildings if b["objektart"] == "Lagertank" and b["footprint_w"] <= 6.0 and b["height"] >= 14.0]
    for ia_s in range(len(silo_list)):
        sa = silo_list[ia_s]
        if crop_box_lv95 is not None and not (
            crop_box_lv95[0] + 2 <= sa["e"] <= crop_box_lv95[2] - 2 and crop_box_lv95[1] + 2 <= sa["n"] <= crop_box_lv95[3] - 2
        ):
            continue
        for ib_s in range(ia_s + 1, len(silo_list)):
            sb = silo_list[ib_s]
            dist_s = math.hypot(sa["e"] - sb["e"], sa["n"] - sb["n"])
            if dist_s <= 5.5:
                z_pipe = min(sa["z_roof"], sb["z_roof"]) + 0.45
                ns_p = max(4, int(math.ceil(dist_s / max(0.06, camera.mpp * 0.55))) + 1)
                tp = np.linspace(0.0, 1.0, ns_p)
                pe_p = sa["e"] + (sb["e"] - sa["e"]) * tp
                pn_p = sa["n"] + (sb["n"] - sa["n"]) * tp
                px, py, pd = camera.project(pe_p, pn_p, np.full_like(pe_p, z_pipe))
                ix, iy = np.round(px + shift_x).astype(np.int32), np.round(py + shift_y).astype(np.int32)
                vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
                if vm.any():
                    ix, iy, pd = ix[vm], iy[vm], pd[vm]
                    win = pd < zbuf[iy, ix]
                    if win.any():
                        zbuf[iy[win], ix[win]] = pd[win]
                        rgb_buf[iy[win], ix[win]] = [194.0, 200.0, 208.0]
                        mat_buf[iy[win], ix[win]] = M_WALL
                        obj_buf[iy[win], ix[win]] = sa["idx"] + 1
                        norm_buf[iy[win], ix[win]] = [0.25, -0.25, 0.93]
                        shadow_buf[iy[win], ix[win]] = False
        # v9.0 Circular brushed-steel safety guardrail ring atop each tall Lindt cocoa silo (resolution-aware!)
        rc_sa = int(np.clip((N_MAX - sa["n"]) / GRID_RES, 0, GRID_H - 1))
        cc_sa = int(np.clip((sa["e"] - E_MIN) / GRID_RES, 0, GRID_W - 1))
        if active_mask[rc_sa, cc_sa]:
            r_gr = min(2.4, sa["footprint_w"] * 0.44)
            z_gr = sa["z_roof"] + 0.95
            n_gr = max(24, int(math.ceil(2.0 * math.pi * r_gr / max(0.06, camera.mpp * 0.55))) + 1)
            ang_gr = np.linspace(0.0, 2.0 * math.pi, n_gr)
            es_gr = sa["e"] + r_gr * np.cos(ang_gr)
            ns_gr = sa["n"] + r_gr * np.sin(ang_gr)
            px_g, py_g, pd_g = camera.project(es_gr, ns_gr, np.full_like(es_gr, z_gr))
            ix_g, iy_g = np.round(px_g + shift_x).astype(np.int32), np.round(py_g + shift_y).astype(np.int32)
            vm_g = (ix_g >= 0) & (ix_g < W) & (iy_g >= 0) & (iy_g < H)
            if vm_g.any():
                ix_g, iy_g, pd_g = ix_g[vm_g], iy_g[vm_g], pd_g[vm_g]
                win_g = pd_g < zbuf[iy_g, ix_g]
                if win_g.any():
                    zbuf[iy_g[win_g], ix_g[win_g]] = pd_g[win_g]
                    rgb_buf[iy_g[win_g], ix_g[win_g]] = [178.0, 184.0, 192.0]
                    mat_buf[iy_g[win_g], ix_g[win_g]] = M_WALL
                    obj_buf[iy_g[win_g], ix_g[win_g]] = sa["idx"] + 1
                    norm_buf[iy_g[win_g], ix_g[win_g]] = [0.25, -0.25, 0.93]
                    shadow_buf[iy_g[win_g], ix_g[win_g]] = False

    # F11: 3D Rooftop Brick Chimneys with Twin Terracotta Pots & LiDAR-Verified Flat-Roof Superstructures!
    for b in scene.buildings:
        bi_r = b["idx"]
        obj_r = b["objektart"]
        if obj_r in ("Hochkamin", "Lagertank", "Treibhaus", "Flugdach", "Offenes Gebaeude", "Mauer gross", "Sakraler Turm"):
            continue
        if bi_r == id_lindt_hoc:
            continue
        be_c, bn_c = b["e"], b["n"]
        if crop_box_lv95 is not None:
            if not (crop_box_lv95[0] + 2 <= be_c <= crop_box_lv95[2] - 2 and crop_box_lv95[1] + 2 <= bn_c <= crop_box_lv95[3] - 2):
                continue
        fw, fl = b["footprint_w"], b["footprint_l"]
        if fw < 6.0 or fl < 6.0:
            continue
        px_r, py_r, _ = camera.project(np.array([be_c]), np.array([bn_c]), np.array([b["z_roof"]]))
        if px_r[0] + shift_x < -20 or px_r[0] + shift_x > W + 20 or py_r[0] + shift_y < -20 or py_r[0] + shift_y > H + 20:
            continue

        b_seed = ((bi_r * 73856093) ^ 0x5A3C) & 0xFF
        if scene.bldg_is_pitched[bi_r] and (b_seed % 5) < 2 and obj_r != "Sakrales Gebaeude":
            off_e = (((b_seed & 7) / 7.0) - 0.5) * min(2.4, fw * 0.24)
            off_n = ((((b_seed >> 3) & 7) / 7.0) - 0.5) * min(2.4, fl * 0.24)
            ch_e, ch_n = be_c + off_e, bn_c + off_n
            if crop_box_lv95 is not None:
                if not (crop_box_lv95[0] + 2.0 <= ch_e <= crop_box_lv95[2] - 2.0 and crop_box_lv95[1] + 2.0 <= ch_n <= crop_box_lv95[3] - 2.0):
                    continue
            r_ch = int(np.floor((N_MAX - ch_n) / GRID_RES))
            c_ch = int(np.floor((ch_e - E_MIN) / GRID_RES))
            if not (2 <= r_ch < GRID_H - 2 and 2 <= c_ch < GRID_W - 2):
                continue
            # Strictly require >= 1.0 m interior containment inside both real roof footprint and active mask!
            if not (
                scene.bldg_roof_mask[r_ch - 2 : r_ch + 3, c_ch - 2 : c_ch + 3].all()
                and active_mask[r_ch - 2 : r_ch + 3, c_ch - 2 : c_ch + 3].all()
            ):
                continue
            z_lidar_ch = float(scene.dem[r_ch, c_ch] + scene.chm[r_ch, c_ch])
            if z_lidar_ch < b["z_ground"] + 2.2:
                continue
            z_top_ch = min(b["z_roof"] + 0.95, z_lidar_ch + 1.35)
            z_bot_ch = max(
                b["z_ground"] + 1.5,
                min(z_lidar_ch - 1.5, b["z_ground"] + 0.50 * (b["z_roof"] - b["z_ground"])),
            )
            ch_col = (152.0, 96.0, 76.0) if (b_seed & 1) == 0 else (168.0, 162.0, 152.0)
            _draw_3d_box_column(
                camera, shift_x, shift_y, W, H,
                zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                ch_e, ch_n, z_bot_ch, z_top_ch,
                0.38, ch_col, bi_r + 1, M_WALL,
            )
            _draw_3d_box_column(
                camera, shift_x, shift_y, W, H,
                zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                ch_e, ch_n, z_top_ch - 0.15, z_top_ch + 0.14,
                0.45, (74.0, 74.0, 78.0), bi_r + 1, M_WALL,
            )
            # Twin terracotta chimney pots atop the dark slate cap!
            for pe_o, pn_o in ((-0.18, -0.10), (0.18, 0.10)):
                _draw_3d_box_column(
                    camera, shift_x, shift_y, W, H,
                    zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    ch_e + pe_o, ch_n + pn_o, z_top_ch + 0.10, z_top_ch + 0.46,
                    0.11, (176.0, 96.0, 64.0), bi_r + 1, M_WALL,
                )
        elif (not scene.bldg_is_pitched[bi_r]) and fw >= 12.0 and fl >= 12.0:
            # F11: LiDAR-verified flat-roof HVAC / elevator penthouse superstructures (NEVER covering PV or skylights!)
            rc_b = int(np.clip((N_MAX - bn_c) / GRID_RES, 0, GRID_H - 1))
            cc_b = int(np.clip((be_c - E_MIN) / GRID_RES, 0, GRID_W - 1))
            rad = max(2, int(min(fw, fl) * 0.34 / GRID_RES))
            r_lo, r_hi = max(0, rc_b - rad), min(GRID_H, rc_b + rad + 1)
            c_lo, c_hi = max(0, cc_b - rad), min(GRID_W, cc_b + rad + 1)
            if r_hi <= r_lo + 2 or c_hi <= c_lo + 2:
                continue
            z_rf = float(b["z_roof"])
            diff = (scene.dem[r_lo:r_hi, c_lo:c_hi] + scene.chm[r_lo:r_hi, c_lo:c_hi]) - z_rf
            n_bump = int((diff >= 0.75).sum())
            if n_bump < 3 or float(diff.max()) > 6.5:
                continue
            diff_sm = ndimage.uniform_filter(diff, size=3)
            pk_flat = int(np.argmax(diff_sm))
            rp_l, cp_l = divmod(pk_flat, diff_sm.shape[1])
            rp, cp = r_lo + rp_l, c_lo + cp_l
            diff_pk = float(diff[rp_l, cp_l])
            if diff_pk < 0.75:
                continue
            if not (1 <= rp < GRID_H - 1 and 1 <= cp < GRID_W - 1):
                continue
            if not (
                scene.bldg_roof_mask[rp - 1 : rp + 2, cp - 1 : cp + 2].all()
                and active_mask[rp - 1 : rp + 2, cp - 1 : cp + 2].all()
            ):
                continue
            # Suppress over verified solar PV arrays!
            if scene.pv_clean_05m[max(0, rp - 1) : min(GRID_H, rp + 2), max(0, cp - 1) : min(GRID_W, cp + 2)].any():
                continue
            ep = E_MIN + (cp + 0.5) * GRID_RES
            np_c = N_MAX - (rp + 0.5) * GRID_RES
            if crop_box_lv95 is not None:
                if not (crop_box_lv95[0] + 2.0 <= ep <= crop_box_lv95[2] - 2.0 and crop_box_lv95[1] + 2.0 <= np_c <= crop_box_lv95[3] - 2.0):
                    continue
            # Suppress over bright white or blue-tinted DOP10 skylights/atriums!
            c_hr = int(np.clip((ep - E_MIN) / scene.ortho_res, 1, scene.ortho_w - 2))
            r_hr = int(np.clip((N_MAX - np_c) / scene.ortho_res, 1, scene.ortho_h - 2))
            patch25 = np.asarray(scene.ortho_hr[r_hr - 1 : r_hr + 2, c_hr - 1 : c_hr + 2], dtype=np.float32)
            mean_rgb = patch25.mean(axis=(0, 1))
            mean_lum = float(0.299 * mean_rgb[0] + 0.587 * mean_rgb[1] + 0.114 * mean_rgb[2])
            if mean_lum > 186.0 or (float(mean_rgb[2]) - float(mean_rgb[0])) > 10.0:
                continue
            h_box = float(np.clip(diff_pk, 0.85, 2.25))
            hw_box = float(np.clip(0.65 + 0.18 * math.sqrt(n_bump), 0.85, 1.55))
            _draw_3d_box_column(
                camera, shift_x, shift_y, W, H,
                zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                ep, np_c, z_rf - 0.15, z_rf + h_box,
                hw_box, (164.0, 168.0, 174.0), bi_r + 1, M_WALL,
            )
            # Subtle mechanical top fan square
            _draw_3d_box_column(
                camera, shift_x, shift_y, W, H,
                zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                ep, np_c, z_rf + h_box - 0.05, z_rf + h_box + 0.16,
                hw_box * 0.55, (122.0, 126.0, 134.0), bi_r + 1, M_WALL,
            )

    # v9.0 Landmark 3D Rooftop Finials & Heimatstil Roof-Ridge Bell Cupolas (strictly crop_box_lv95 inset >= 2.0m + active_mask!)
    def _draw_finial_seg(fe0, fn0, fz0, fe1, fn1, fz1, fcol, fmat=M_WALL, foid=244950, thick=False):
        if crop_box_lv95 is not None:
            if not (
                crop_box_lv95[0] + 2.0 <= min(fe0, fe1) and max(fe0, fe1) <= crop_box_lv95[2] - 2.0
                and crop_box_lv95[1] + 2.0 <= min(fn0, fn1) and max(fn0, fn1) <= crop_box_lv95[3] - 2.0
            ):
                return
        rf0 = int(np.clip((N_MAX - 0.5 * (fn0 + fn1)) / GRID_RES, 0, GRID_H - 1))
        cf0 = int(np.clip((0.5 * (fe0 + fe1) - E_MIN) / GRID_RES, 0, GRID_W - 1))
        if not active_mask[rf0, cf0]:
            return
        dist_f = math.sqrt((fe1 - fe0) ** 2 + (fn1 - fn0) ** 2 + (fz1 - fz0) ** 2)
        ns_f = max(2, int(math.ceil(dist_f / max(0.14, camera.mpp * 0.55))) + 1)
        tf = np.linspace(0.0, 1.0, ns_f, dtype=np.float64)
        px_f, py_f, pd_f = camera.project(fe0 + (fe1 - fe0) * tf, fn0 + (fn1 - fn0) * tf, fz0 + (fz1 - fz0) * tf)
        ix_f, iy_f = np.round(px_f + shift_x).astype(np.int32), np.round(py_f + shift_y).astype(np.int32)
        vm_f = (ix_f >= 0) & (ix_f < W) & (iy_f >= 0) & (iy_f < H)
        if not vm_f.any():
            return
        ix_f, iy_f, pd_f = ix_f[vm_f], iy_f[vm_f], pd_f[vm_f]
        for ox, oy in (((0, 0), (1, 0)) if thick else ((0, 0),)):
            tx, ty = np.clip(ix_f + ox, 0, W - 1), np.clip(iy_f + oy, 0, H - 1)
            win_f = pd_f < zbuf[ty, tx]
            if win_f.any():
                zbuf[ty[win_f], tx[win_f]] = pd_f[win_f]
                rgb_buf[ty[win_f], tx[win_f]] = fcol
                mat_buf[ty[win_f], tx[win_f]] = fmat
                obj_buf[ty[win_f], tx[win_f]] = foid
                norm_buf[ty[win_f], tx[win_f]] = [0.25, -0.25, 0.93]
                shadow_buf[ty[win_f], tx[win_f]] = False

    # 1. v11 Reformierte Kirche Spire Finial: verdigris copper cap + gold orb + iron rod + Zürich blue-white flaglet + gold star
    if id_ref_kirche >= 0:
        b_rk = scene.buildings[id_ref_kirche]
        rk_e, rk_n, rk_z0 = 2683413.0, 1241287.7, float(b_rk["z_roof"])
        g_mat = M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WALL
        _draw_finial_seg(rk_e, rk_n, rk_z0 - 0.5, rk_e, rk_n, rk_z0 + 0.4, [118.0, 152.0, 138.0], fmat=M_WALL, foid=244950, thick=True)
        _draw_finial_seg(rk_e, rk_n, rk_z0 + 0.4, rk_e, rk_n, rk_z0 + 0.9, [242.0, 200.0, 74.0], fmat=g_mat, foid=244950, thick=True)
        _draw_finial_seg(rk_e, rk_n, rk_z0 + 0.9, rk_e, rk_n, rk_z0 + 2.8, [68.0, 70.0, 74.0], fmat=M_WALL, foid=244950)
        _draw_finial_seg(rk_e, rk_n + 0.05, rk_z0 + 1.85, rk_e, rk_n + 0.72, rk_z0 + 1.85, [238.0, 240.0, 244.0], fmat=M_WALL, foid=244950, thick=True)
        _draw_finial_seg(rk_e, rk_n + 0.05, rk_z0 + 1.62, rk_e, rk_n + 0.65, rk_z0 + 1.62, [58.0, 118.0, 186.0], fmat=M_WALL, foid=244950)
        _draw_finial_seg(rk_e, rk_n, rk_z0 + 2.75, rk_e, rk_n, rk_z0 + 3.10, [246.0, 210.0, 84.0], fmat=g_mat, foid=244950, thick=True)

    # 2. v11 Kath. Kirche St. Elisabeth Slender Metallic Cross atop NAVE copper roof apex (NOT on white crown tower!)
    if id_st_el_nave >= 0:
        se_e, se_n, se_z0 = 2683518.25, 1241628.38, 504.59
        _draw_finial_seg(se_e, se_n, se_z0 - 0.1, se_e, se_n, se_z0 + 2.4, [214.0, 212.0, 206.0], foid=244951, thick=True)
        _draw_finial_seg(se_e, se_n - 0.65, se_z0 + 1.75, se_e, se_n + 0.65, se_z0 + 1.75, [214.0, 212.0, 206.0], foid=244951)

    # 3. Lindt Smokestack Slender Lightning Rod Finial (oid=244952, excluded from occ_m)
    if id_lindt_chim >= 0:
        b_lc = scene.buildings[id_lindt_chim]
        lc_e, lc_n, lc_z0 = float(b_lc["e"]), float(b_lc["n"]), float(b_lc["z_roof"])
        _draw_finial_seg(lc_e, lc_n, lc_z0 - 0.2, lc_e, lc_n, lc_z0 + 2.1, [184.0, 152.0, 118.0], foid=244952)
        _draw_finial_seg(lc_e, lc_n, lc_z0 + 2.1, lc_e, lc_n, lc_z0 + 2.6, [224.0, 228.0, 232.0], foid=244952)

    # 4. v11 Schulhaus Alte Landstrasse (868) ONLY Roof-Ridge Bell Cupola (Dachreiter) — Gemeindehaus 856 has NO cupola!
    for b_cup_id in (id_schul_al_868,):
        if b_cup_id < 0:
            continue
        b_cup = scene.buildings[b_cup_id]
        ce_u, cn_u, cz_u = float(b_cup["e"]), float(b_cup["n"]), float(b_cup["z_roof"])
        if crop_box_lv95 is not None and not (
            crop_box_lv95[0] + 2.0 <= ce_u <= crop_box_lv95[2] - 2.0
            and crop_box_lv95[1] + 2.0 <= cn_u <= crop_box_lv95[3] - 2.0
        ):
            continue
        rc_u = int(np.clip((N_MAX - cn_u) / GRID_RES, 0, GRID_H - 1))
        cc_u = int(np.clip((ce_u - E_MIN) / GRID_RES, 0, GRID_W - 1))
        if not active_mask[rc_u, cc_u]:
            continue
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, ce_u, cn_u, cz_u - 0.6, cz_u + 1.6, 0.95, (92.0, 62.0, 52.0), b_cup_id + 1, M_WALL)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, ce_u + 0.55, cn_u, cz_u + 0.3, cz_u + 1.3, 0.35, (36.0, 38.0, 44.0), b_cup_id + 1, M_WALL)
        _draw_finial_seg(ce_u + 0.58, cn_u, cz_u + 0.72, ce_u + 0.58, cn_u, cz_u + 0.98, [216.0, 196.0, 128.0], fmat=M_WINDOW_LIT if (preset.is_night or preset_key == "sunset") else M_WALL, foid=244953)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, ce_u, cn_u, cz_u + 1.6, cz_u + 2.3, 1.05, (106.0, 162.0, 142.0), b_cup_id + 1, M_WALL)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, ce_u, cn_u, cz_u + 2.3, cz_u + 3.0, 0.55, (106.0, 162.0, 142.0), b_cup_id + 1, M_WALL)
        _draw_3d_box_column(camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf, ce_u, cn_u, cz_u + 3.0, cz_u + 3.45, 0.22, (106.0, 162.0, 142.0), b_cup_id + 1, M_WALL)
        _draw_finial_seg(ce_u, cn_u, cz_u + 3.4, ce_u, cn_u, cz_u + 4.2, [156.0, 196.0, 180.0], foid=244953)

    _evict_mmap_rss(scene.ortho_hr)
    _evict_mmap_rss(scene.roof_edge_25cm)

    # -------------------------------------------------------------------------
    # STAGE 4: Sculpted 90s Pixel-Art 3D Trees & Trimmed Garden Hedges!
    # -------------------------------------------------------------------------
    _render_sculpted_pixel_art_trees_and_hedges(
        scene, camera, shift_x, shift_y, W, H, r0, r1, c0, c1,
        sub_mask, sub_dem, sub_chm, sub_shadow,
        zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
        sun_vec, crop_box_lv95,
        is_night=preset.is_night,
    )

    # -------------------------------------------------------------------------
    # STAGE 5 (F5-F9): Stepped Lighting + Uplighting + Contact AO + Streetlamp Pools +
    #                  Window Halos + Shoreline Reflections + Shimmer + Sel-Out + 256-Color CLUT
    # -------------------------------------------------------------------------
    active_px = mat_buf > M_DROP_SHADOW
    ay, ax = np.nonzero(active_px)

    if len(ay) > 0:
        n_xyz = norm_buf[ay, ax]
        m_here = mat_buf[ay, ax]
        ndotl = np.clip(
            n_xyz[:, 0] * sun_vec[0] + n_xyz[:, 1] * sun_vec[1] + n_xyz[:, 2] * sun_vec[2],
            0.0,
            1.0,
        )
        # F8/v12: Crisp 4-step cel-shaded lighting with punchy warm-sun vs cool-blue shadow contrast!
        sh_fac = np.where((m_here == M_ROOF) | (m_here == M_WALL), 0.22, 0.14).astype(np.float32)
        ndotl = np.where(shadow_buf[ay, ax], ndotl * sh_fac, ndotl)
        ndotl_step = np.round(ndotl * 3.0) / 3.0

        amb = np.array(preset.amb_rgb, dtype=np.float32)
        sun_c = np.array(preset.sun_rgb, dtype=np.float32)
        sky_dome = (0.5 + 0.5 * np.clip(n_xyz[:, 2], -1.0, 1.0))[:, None]
        lit_mult = amb[None, :] * (0.72 + 0.28 * sky_dome) + sun_c[None, :] * ndotl_step[:, None] * 0.72

        base_f = rgb_buf[ay, ax]
        shaded = base_f * lit_mult

        # F5: Preset-adapted Lake Zurich Aquarium Cutaway Water
        is_cut_w = m_here == M_CUTAWAY_WATER
        if is_cut_w.any():
            if preset_key == "night":
                shaded[is_cut_w] = base_f[is_cut_w] * np.array([0.36, 0.44, 0.62], dtype=np.float32)
            elif preset_key == "sunset":
                shaded[is_cut_w] = base_f[is_cut_w] * np.array([1.02, 0.86, 0.84], dtype=np.float32)
            else:
                shaded[is_cut_w] = base_f[is_cut_w] * 0.94

        # F6: Physically accurate scotopic Night Purkinje shift (attenuates Red, keeps Green softly muted, lifts Blue -> moonlit slate-emerald/Prussian-blue, ZERO muddy brown & ZERO neon green!)
        if preset.is_night:
            is_veg_or_g = (m_here == M_GROUND) | (m_here == M_TREE)
            if is_veg_or_g.any():
                sv = shaded[is_veg_or_g]
                lum_v = (0.299 * sv[:, 0] + 0.587 * sv[:, 1] + 0.114 * sv[:, 2])[:, None]
                sv = lum_v + 0.42 * (sv - lum_v)
                sv[:, 0] *= 0.80
                sv[:, 1] *= 0.92
                sv[:, 2] *= 1.15
                shaded[is_veg_or_g] = sv
            # v13.0: Gently attenuate pale silver-birch M_TRUNK at night (~0.62) so trunks stay moonlit, never neon white
            is_trunk_n = m_here == M_TRUNK
            if is_trunk_n.any():
                st = shaded[is_trunk_n]
                lum_t = 0.299 * st[:, 0] + 0.587 * st[:, 1] + 0.114 * st[:, 2]
                pale_att = np.where(lum_t > 60.0, 0.62, 0.85)[:, None].astype(np.float32)
                st *= pale_att
                st[:, 0] *= 0.88
                st[:, 2] *= 1.12
                shaded[is_trunk_n] = st

        # F7: Emissive lit windows, shopfronts, signs & streetlamp globes (Night full, Sunset dusk warm!)
        is_emissive = m_here == M_WINDOW_LIT
        if is_emissive.any():
            if preset.is_night:
                shaded[is_emissive] = base_f[is_emissive]
            elif preset_key == "sunset":
                shaded[is_emissive] = 0.88 * base_f[is_emissive] + 0.12 * shaded[is_emissive]

        rgb_buf[ay, ax] = np.clip(shaded, 0.0, 255.0)

    # F7 + v10: Exact tagged underwater turquoise-teal glow on Seebad Kilchberg pool ONLY at Night (ZERO lawn/shore bleed!)
    if preset.is_night:
        is_sb_pool = obj_buf == 259999
        if is_sb_pool.any():
            rgb_buf[is_sb_pool] = np.clip(
                rgb_buf[is_sb_pool] * np.array([1.25, 1.85, 1.75], dtype=np.float32),
                0.0,
                255.0,
            )

    # F7: Architectural Landmark Uplighting (Night full, Sunset 0.25x) via exact obj_buf!
    if preset_key in ("night", "sunset"):
        up_scale = 1.0 if preset.is_night else 0.25
        up_targets = (
            (id_ref_kirche,   np.array([112.0, 78.0, 34.0], dtype=np.float32), 0.55),
            (id_lindt_hoc,    np.array([118.0, 84.0, 38.0], dtype=np.float32), 0.42),
            (id_lindt_chim,   np.array([98.0,  66.0, 28.0], dtype=np.float32), 0.50),
            (id_st_el_twr,    np.array([78.0,  82.0, 86.0], dtype=np.float32), 0.35),
            (id_bhf_stn,      np.array([76.0,  52.0, 22.0], dtype=np.float32), 0.35),
            # v11 heritage & civic uplighting (photo-balanced night ambiance)
            (id_gem_main,     np.array([96.0,  68.0, 30.0], dtype=np.float32), 0.45),
            (id_schul_al_868, np.array([84.0,  60.0, 26.0], dtype=np.float32), 0.36),
            (id_cfm_1033,     np.array([96.0,  68.0, 30.0], dtype=np.float32), 0.44),
            (lm.get("sanatorium_633", -1), np.array([76.0, 70.0, 58.0], dtype=np.float32), 0.28),
            (lm.get("sanatorium_81", -1),  np.array([76.0, 70.0, 58.0], dtype=np.float32), 0.28),
            (lm.get("sanatorium_521", -1), np.array([72.0, 68.0, 58.0], dtype=np.float32), 0.26),
            (lm.get("sanatorium_483", -1), np.array([70.0, 66.0, 56.0], dtype=np.float32), 0.24),
            (id_hb_main,      np.array([58.0,  86.0, 92.0], dtype=np.float32), 0.36),
            (lm.get("moenchhof_hafenbeiz_243", -1), np.array([68.0, 46.0, 20.0], dtype=np.float32), 0.18),
            (lm.get("moenchhof_hafenbeiz_843", -1), np.array([68.0, 46.0, 20.0], dtype=np.float32), 0.15),
            (id_broel_manor,  np.array([82.0,  60.0, 30.0], dtype=np.float32), 0.28),
            (id_spin_villa,   np.array([84.0,  60.0, 26.0], dtype=np.float32), 0.36),
        )
        for bid_u, tint_u, strength_u in up_targets:
            if bid_u < 0:
                continue
            m_u = (obj_buf == (bid_u + 1)) & ((mat_buf == M_WALL) | (mat_buf == M_ROOF))
            if not m_u.any():
                continue
            uy, ux = np.nonzero(m_u)
            y_bot_u = float(uy.max())
            y_span_u = max(8.0, y_bot_u - float(uy.min()))
            # Warm upward wash strongest near facade base/mid, tapering gracefully up the spire/parapet
            t_up = np.clip(1.0 - 0.58 * ((y_bot_u - uy.astype(np.float32)) / y_span_u), 0.32, 1.0)
            fac_u = t_up * (strength_u * up_scale)
            rgb_buf[uy, ux] = np.clip(rgb_buf[uy, ux] + fac_u[:, None] * tint_u[None, :], 0.0, 255.0)

    # F8 + v10: Fast Vectorized zbuf Screen-Space Contact Ambient Occlusion scaled by px_scale!
    px_scale = 0.25 / max(0.08, float(camera.mpp))
    s_ao = max(1, int(round(px_scale)))
    occ_sum = np.zeros((H, W), dtype=np.float32)
    z_valid = zbuf < 1e8
    ao_taps = [
        (-1 * s_ao, 0, 1.0), (1 * s_ao, 0, 1.0), (0, -1 * s_ao, 1.0), (0, 1 * s_ao, 1.0),
        (-2 * s_ao, -1 * s_ao, 0.5), (-2 * s_ao, 1 * s_ao, 0.5), (2 * s_ao, -1 * s_ao, 0.5), (2 * s_ao, 1 * s_ao, 0.5),
    ]
    if px_scale >= 1.5:
        ao_taps.extend([
            (-3 * s_ao, 0, 0.35), (3 * s_ao, 0, 0.35), (0, -3 * s_ao, 0.35), (0, 3 * s_ao, 0.35),
        ])
    ao_norm_div = 6.9 if px_scale >= 1.5 else 5.5
    for dy_ao, dx_ao, w_ao in ao_taps:
        sy0_a, sy1_a = max(0, dy_ao), min(H, H + dy_ao)
        sx0_a, sx1_a = max(0, dx_ao), min(W, W + dx_ao)
        dy0_a, dy1_a = sy0_a - dy_ao, sy1_a - dy_ao
        dx0_a, dx1_a = sx0_a - dx_ao, sx1_a - dx_ao
        dz_ao = zbuf[dy0_a:dy1_a, dx0_a:dx1_a] - zbuf[sy0_a:sy1_a, sx0_a:sx1_a]
        hit_ao = (
            z_valid[dy0_a:dy1_a, dx0_a:dx1_a]
            & z_valid[sy0_a:sy1_a, sx0_a:sx1_a]
            & (dz_ao > 0.35)
            & (dz_ao < 5.5)
        )
        occ_sum[dy0_a:dy1_a, dx0_a:dx1_a] += np.where(hit_ao, w_ao * (1.0 - dz_ao / 5.5), 0.0)
    ao_recv = (mat_buf == M_GROUND) | (mat_buf == M_WALL) | (mat_buf == M_ROOF) | (mat_buf == M_BRIDGE)
    ao_str = 0.14 if preset.is_night else 0.18
    ao_fac = 1.0 - np.clip(occ_sum / ao_norm_div, 0.0, 1.0) * ao_str
    rgb_buf[ao_recv] *= ao_fac[ao_recv, None]
    del occ_sum, ao_fac, z_valid

    # F7 + v10: World-Projected Warm Sodium-Amber Streetlamp Ground Pools + Lantern-Head Air Bloom (scaled by px_scale!)
    if preset_key in ("night", "sunset") and len(scene.lamp_e) > 0:
        pool_scale = 1.0 if preset.is_night else 0.32
        px_lb, py_lb, pd_lb = camera.project(scene.lamp_e, scene.lamp_n, scene.lamp_z)
        sx_lb = px_lb + shift_x
        sy_lb = py_lb + shift_y
        vp_m_l = 28.0 * px_scale
        in_lvp = (sx_lb >= -vp_m_l) & (sx_lb <= W + vp_m_l) & (sy_lb >= -vp_m_l) & (sy_lb <= H + vp_m_l)
        if in_lvp.any():
            li_vp = np.nonzero(in_lvp)[0]
            pool_tint = np.array([174.0, 108.0, 36.0], dtype=np.float32) * pool_scale * (1.15 if preset.is_night else 1.0)
            bloom_tint = np.array([166.0, 112.0, 42.0], dtype=np.float32) * pool_scale
            for idx_l in li_vp:
                le_i = float(scene.lamp_e[idx_l])
                ln_i = float(scene.lamp_n[idx_l])
                lz_i = float(scene.lamp_z[idx_l])
                lk_i = int(scene.lamp_kind[idx_l])
                if crop_box_lv95 is not None and not (
                    crop_box_lv95[0] + 1.5 <= le_i <= crop_box_lv95[2] - 1.5
                    and crop_box_lv95[1] + 1.5 <= ln_i <= crop_box_lv95[3] - 1.5
                ):
                    continue
                rc_l = int(np.clip((N_MAX - ln_i) / GRID_RES, 0, GRID_H - 1))
                cc_l = int(np.clip((le_i - E_MIN) / GRID_RES, 0, GRID_W - 1))
                if not active_mask[rc_l, cc_l]:
                    continue
                cx_l = float(sx_lb[idx_l])
                cy_l = float(sy_lb[idx_l])
                d_l = float(pd_lb[idx_l])
                rx_p = ((26.0 if lk_i in (0, 1) else 21.0) if preset.is_night else (20.0 if lk_i in (0, 1) else 16.0)) * px_scale
                ry_p = rx_p * 0.52
                x0_p = max(0, int(math.floor(cx_l - rx_p)))
                x1_p = min(W, int(math.ceil(cx_l + rx_p)) + 1)
                y0_p = max(0, int(math.floor(cy_l - ry_p)))
                y1_p = min(H, int(math.ceil(cy_l + ry_p)) + 1)
                if x1_p > x0_p and y1_p > y0_p:
                    gx_p, gy_p = np.meshgrid(
                        np.arange(x0_p, x1_p, dtype=np.float32) - cx_l,
                        np.arange(y0_p, y1_p, dtype=np.float32) - cy_l,
                    )
                    r2_p = (gx_p / rx_p) ** 2 + (gy_p / ry_p) ** 2
                    sub_m_p = mat_buf[y0_p:y1_p, x0_p:x1_p]
                    sub_z_p = zbuf[y0_p:y1_p, x0_p:x1_p]
                    ok_p = (
                        (r2_p < 1.0)
                        & ((sub_m_p == M_GROUND) | (sub_m_p == M_BRIDGE) | (sub_m_p == M_RAIL) | (sub_m_p == M_WALL))
                        & (np.abs(sub_z_p - d_l) < 10.5)
                    )
                    if ok_p.any():
                        w_p = (1.0 - r2_p[ok_p]) ** 1.65
                        sub_rgb_p = rgb_buf[y0_p:y1_p, x0_p:x1_p]
                        sub_rgb_p[ok_p] = np.clip(sub_rgb_p[ok_p] + w_p[:, None] * pool_tint[None, :], 0.0, 255.0)
                # Soft warm air bloom around lantern head itself (scaled by px_scale!)
                h_pole = 4.8 if lk_i in (0, 1) else (4.2 if lk_i == 2 else 3.6)
                px_h, py_h, pd_h = camera.project(np.array([le_i]), np.array([ln_i]), np.array([lz_i + h_pole]))
                hx_f, hy_f, hd_f = float(px_h[0] + shift_x), float(py_h[0] + shift_y), float(pd_h[0])
                hi_x, hi_y = int(round(hx_f)), int(round(hy_f))
                if 0 <= hi_x < W and 0 <= hi_y < H and zbuf[hi_y, hi_x] >= (hd_f - 1.5):
                    rb_h = max(4, int(round(6.0 * px_scale)))
                    bx0, bx1 = max(0, hi_x - rb_h), min(W, hi_x + rb_h + 1)
                    by0, by1 = max(0, hi_y - rb_h), min(H, hi_y + rb_h + 1)
                    gx_b, gy_b = np.meshgrid(
                        np.arange(bx0, bx1, dtype=np.float32) - hx_f,
                        np.arange(by0, by1, dtype=np.float32) - hy_f,
                    )
                    r2_b = (gx_b * gx_b + gy_b * gy_b) / float(rb_h * rb_h)
                    sub_mb = mat_buf[by0:by1, bx0:bx1]
                    ok_b = (r2_b < 1.0) & (sub_mb > M_DROP_SHADOW) & (sub_mb != M_WINDOW_LIT)
                    if ok_b.any():
                        w_b = (1.0 - r2_b[ok_b]) ** 2.0
                        sub_rb = rgb_buf[by0:by1, bx0:bx1]
                        sub_rb[ok_b] = np.clip(sub_rb[ok_b] + w_b[:, None] * bloom_tint[None, :], 0.0, 255.0)

    # F7: Subtle Warm Window-Spill Glow Halos on Surrounding Facades & Ground (scaled by px_scale!)
    if preset_key in ("night", "sunset"):
        lit_mask = mat_buf == M_WINDOW_LIT
        if lit_mask.any():
            halo = ndimage.gaussian_filter(lit_mask.astype(np.float32), sigma=1.75 * px_scale, truncate=3.0)
            halo_scale = 1.0 if preset.is_night else 0.38
            spill_ok = (mat_buf > M_DROP_SHADOW) & (~lit_mask) & (mat_buf != M_WATER_LAKE) & (halo > 0.018)
            if spill_ok.any():
                sy_h, sx_h = np.nonzero(spill_ok)
                hv = np.minimum(0.55, halo[sy_h, sx_h]) * halo_scale
                rgb_buf[sy_h, sx_h, 0] = np.minimum(255.0, rgb_buf[sy_h, sx_h, 0] + hv * 172.0)
                rgb_buf[sy_h, sx_h, 1] = np.minimum(255.0, rgb_buf[sy_h, sx_h, 1] + hv * 106.0)
                rgb_buf[sy_h, sx_h, 2] = np.minimum(255.0, rgb_buf[sy_h, sx_h, 2] + hv * 32.0)
            del halo

    # F9: Seam-Free Inverted Screen-Space Shoreline Reflections + Solar/Lunar Specular Shimmer on Lake Zurich!
    is_water_s5 = mat_buf == M_WATER_LAKE
    if is_water_s5.any():
        can_refl = (
            (mat_buf == M_GROUND)
            | (mat_buf == M_WALL)
            | (mat_buf == M_ROOF)
            | (mat_buf == M_WINDOW_LIT)
            | (mat_buf == M_WINDOW_DAY)
            | (mat_buf == M_TREE)
            | (mat_buf == M_TRUNK)
            | (mat_buf == M_BRIDGE)
            | (mat_buf == M_HARBOR_OBJ)
        )
        row_idx = np.arange(H, dtype=np.int32)[:, None]
        shore_seed = np.where(can_refl, row_idx, -1000)
        y_shore = np.maximum.accumulate(shore_seed, axis=0)
        d_below = row_idx - y_shore
        D_MAX_REFL = max(14, int(round(28.0 * px_scale)))
        in_refl = is_water_s5 & (d_below >= 1) & (d_below <= D_MAX_REFL)
        if in_refl.any():
            ry, rx = np.nonzero(in_refl)
            db = d_below[ry, rx]
            ys = y_shore[ry, rx]
            y_src = np.clip(ys - np.round(db * 0.85).astype(np.int32), 0, H - 1)
            # Global coordinates (ry + vy0, rx + vx0) guarantee 0 macro-tile seams!
            gy_r = ry + vy0
            gx_r = rx + vx0
            rip = (np.sin(gy_r * 0.55 + gx_r * 0.14) * 1.4).astype(np.int32)
            x_src = np.clip(rx + rip, 0, W - 1)
            src_ok = can_refl[y_src, x_src]
            if src_ok.any():
                ry, rx, db = ry[src_ok], rx[src_ok], db[src_ok]
                gy_r, gx_r = gy_r[src_ok], gx_r[src_ok]
                y_src, x_src = y_src[src_ok], x_src[src_ok]
                src_col = rgb_buf[y_src, x_src]
                src_is_lit = mat_buf[y_src, x_src] == M_WINDOW_LIT
                t_fade = (1.0 - db.astype(np.float32) / float(D_MAX_REFL + 1)) ** 1.35
                rip_mod = np.where(((gy_r + (gx_r >> 2)) & 1) == 0, 1.0, 0.72).astype(np.float32)
                base_a = 0.28 if preset_key == "day" else (0.42 if preset_key == "sunset" else 0.44)
                alpha = np.where(src_is_lit, np.minimum(0.75, t_fade * 0.78), t_fade * base_a) * rip_mod
                if preset_key == "sunset":
                    src_col = src_col * np.array([1.08, 0.96, 0.86], dtype=np.float32)
                elif preset_key == "night":
                    src_col = np.where(
                        src_is_lit[:, None],
                        src_col * np.array([1.05, 0.88, 0.65], dtype=np.float32),
                        src_col * np.array([0.82, 0.88, 1.05], dtype=np.float32),
                    )
                rgb_buf[ry, rx] = np.clip((1.0 - alpha[:, None]) * rgb_buf[ry, rx] + alpha[:, None] * src_col, 0.0, 255.0)
        del shore_seed, y_shore, d_below

        # Solar / Lunar Specular Shimmer Path (100% global coordinates -> 0 seams!)
        wy_s, wx_s = np.nonzero(is_water_s5)
        gx_w = wx_s + vx0
        gy_w = wy_s + vy0
        gx_n = gx_w.astype(np.float32) / float(max(1, W_full))
        gy_n = gy_w.astype(np.float32) / float(max(1, H_full))
        corridor = np.exp(-((((gx_n - 0.56) + (gy_n - 0.62) * 0.45) / 0.24) ** 2))
        s_hash = (((gx_w >> 1) * 73856093) ^ (gy_w * 19349663)) & 0xFF
        if preset_key == "sunset":
            sheen = corridor[:, None] * np.array([28.0, 14.0, 4.0], dtype=np.float32)
            spk = (corridor > 0.22) & (s_hash < 28) & ((gx_w & 1) == 0)
            rgb_buf[wy_s, wx_s] = np.clip(rgb_buf[wy_s, wx_s] + sheen, 0.0, 255.0)
            if spk.any():
                rgb_buf[wy_s[spk], wx_s[spk]] = np.clip(
                    rgb_buf[wy_s[spk], wx_s[spk]] + corridor[spk, None] * np.array([96.0, 58.0, 18.0], dtype=np.float32),
                    0.0,
                    255.0,
                )
        elif preset_key == "night":
            sheen = corridor[:, None] * np.array([12.0, 16.0, 26.0], dtype=np.float32)
            spk = (corridor > 0.22) & (s_hash < 20) & ((gx_w & 1) == 0)
            rgb_buf[wy_s, wx_s] = np.clip(rgb_buf[wy_s, wx_s] + sheen, 0.0, 255.0)
            if spk.any():
                rgb_buf[wy_s[spk], wx_s[spk]] = np.clip(
                    rgb_buf[wy_s[spk], wx_s[spk]] + corridor[spk, None] * np.array([62.0, 74.0, 96.0], dtype=np.float32),
                    0.0,
                    255.0,
                )
        # Day: no static specular speckle on the lake; the live app.js lake-glint layer animates sun glitter,
        # and baked bright pixels read as floating islands in open water.

    _apply_pixel_art_outlines_float(rgb_buf, zbuf, obj_buf, mat_buf, norm_buf, preset.is_night, preset_key=preset_key)

    # v12: ZERO 4x4 Bayer dithering on ALL solid surfaces! Subtle <= 1.5 dither strictly on sky/lake gradients.
    dither_map = np.zeros_like(bayer_tiled)
    grad_m = (mat_buf == M_BG) | (mat_buf == M_WATER_LAKE)
    dither_map[grad_m] = bayer_tiled[grad_m]

    final_u8 = quantize_to_90s_palette(rgb_buf, dither_map, preset.dither_strength, preset_key=preset_key)

    hit_data = {}
    if collect_hit_boxes and viewport_win is None:
        hit_data = _extract_interactive_metadata(scene, camera, shift_x_full, shift_y_full, W_full, H_full)

    img = Image.fromarray(final_u8, mode="RGB")
    if add_frame and viewport_win is None:
        img = _draw_museum_cartouche(
            img, preset, camera, len(scene.buildings), len(scene.tree_e), crop_box_lv95,
            plate_title=plate_title, plate_subtitle=plate_subtitle,
        )

    if out_depth_buf is not None:
        out_depth_buf["zbuf"] = zbuf
        out_depth_buf["mat_buf"] = mat_buf
        out_depth_buf["obj_buf"] = obj_buf

    return img, hit_data


def _apply_pixel_art_outlines_float(
    rgb_buf: np.ndarray,
    zbuf: np.ndarray,
    obj_buf: np.ndarray,
    mat_buf: np.ndarray,
    norm_buf: np.ndarray,
    is_night: bool,
    preset_key: str = "day",
) -> None:
    """v12 Crisp Dark-Ink Outlines (tinyrj.com benchmark):
    - Dark charcoal-ink silhouettes on buildings, bridges & harbor objects
    - Building wall-corner & roof-facet crease lines (dot(n1, n2) < 0.72, never touching flat signage!)
    - Crisp deep-forest tree outlines + sunlit top-left bevels."""
    dz_r = zbuf[:, 1:] - zbuf[:, :-1]
    dz_d = zbuf[1:, :] - zbuf[:-1, :]
    diff_r = obj_buf[:, 1:] != obj_buf[:, :-1]
    diff_d = obj_buf[1:, :] != obj_buf[:-1, :]

    is_thin_pole = ((obj_buf >= 238000) & (obj_buf < 250000)) | ((obj_buf >= 310000) & (obj_buf < 310200))
    is_bldg_or_br = ((mat_buf == M_WALL) | (mat_buf == M_ROOF) | (mat_buf == M_BRIDGE) | (mat_buf == M_HARBOR_OBJ)) & (~is_thin_pole)
    is_tree_m = mat_buf == M_TREE

    bldg_edge = np.zeros(zbuf.shape, dtype=np.bool_)
    bldg_edge[:, :-1] |= diff_r & (dz_r > 0.65) & is_bldg_or_br[:, :-1]
    bldg_edge[:, 1:] |= diff_r & (dz_r < -0.65) & is_bldg_or_br[:, 1:]
    bldg_edge[:-1, :] |= diff_d & (dz_d > 0.65) & is_bldg_or_br[:-1, :]
    bldg_edge[1:, :] |= diff_d & (dz_d < -0.65) & is_bldg_or_br[1:, :]

    eave_d = (obj_buf[:-1, :] == obj_buf[1:, :]) & (mat_buf[:-1, :] == M_ROOF) & (mat_buf[1:, :] == M_WALL)
    bldg_edge[:-1, :] |= eave_d

    # v12: Building wall-corner & roof-facet crease lines (same building, sharp normal jump dot < 0.72, protects windows & flat signage!)
    is_bldg_solid = (mat_buf == M_WALL) | (mat_buf == M_ROOF)
    same_b_r = (obj_buf[:, :-1] == obj_buf[:, 1:]) & (obj_buf[:, :-1] > 0) & (obj_buf[:, :-1] < 100000) & is_bldg_solid[:, :-1] & is_bldg_solid[:, 1:]
    same_b_d = (obj_buf[:-1, :] == obj_buf[1:, :]) & (obj_buf[:-1, :] > 0) & (obj_buf[:-1, :] < 100000) & is_bldg_solid[:-1, :] & is_bldg_solid[1:, :]
    ndot_r = (
        norm_buf[:, :-1, 0] * norm_buf[:, 1:, 0]
        + norm_buf[:, :-1, 1] * norm_buf[:, 1:, 1]
        + norm_buf[:, :-1, 2] * norm_buf[:, 1:, 2]
    )
    ndot_d = (
        norm_buf[:-1, :, 0] * norm_buf[1:, :, 0]
        + norm_buf[:-1, :, 1] * norm_buf[1:, :, 1]
        + norm_buf[:-1, :, 2] * norm_buf[1:, :, 2]
    )
    bldg_crease = np.zeros(zbuf.shape, dtype=np.bool_)
    bldg_crease[:, :-1] |= same_b_r & (ndot_r < 0.72) & (np.abs(dz_r) < 1.8)
    bldg_crease[:-1, :] |= same_b_d & (ndot_d < 0.72) & (np.abs(dz_d) < 1.8)
    bldg_crease &= ~bldg_edge

    # Split tree outlines: interior forest canopy overlap (obj >= 100000 on both sides) vs world silhouette!
    both_trees_r = (obj_buf[:, :-1] >= 100000) & (obj_buf[:, 1:] >= 100000) & (obj_buf[:, :-1] < 200000) & (obj_buf[:, 1:] < 200000)
    both_trees_d = (obj_buf[:-1, :] >= 100000) & (obj_buf[1:, :] >= 100000) & (obj_buf[:-1, :] < 200000) & (obj_buf[1:, :] < 200000)

    tree_world_sun = np.zeros(zbuf.shape, dtype=np.bool_)
    tree_world_sh = np.zeros(zbuf.shape, dtype=np.bool_)
    tree_world_sh[:, :-1] |= diff_r & (~both_trees_r) & (dz_r > 0.95) & is_tree_m[:, :-1]
    tree_world_sun[:, 1:] |= diff_r & (~both_trees_r) & (dz_r < -0.95) & is_tree_m[:, 1:]
    tree_world_sh[:-1, :] |= diff_d & (~both_trees_d) & (dz_d > 0.95) & is_tree_m[:-1, :]
    tree_world_sun[1:, :] |= diff_d & (~both_trees_d) & (dz_d < -0.95) & is_tree_m[1:, :]
    tree_world_sun &= ~tree_world_sh
    tree_world_edge = tree_world_sh | tree_world_sun

    tree_inner_edge = np.zeros(zbuf.shape, dtype=np.bool_)
    tree_inner_edge[:, :-1] |= diff_r & both_trees_r & (dz_r > 1.35) & is_tree_m[:, :-1]
    tree_inner_edge[:, 1:] |= diff_r & both_trees_r & (dz_r < -1.35) & is_tree_m[:, 1:]
    tree_inner_edge[:-1, :] |= diff_d & both_trees_d & (dz_d > 1.35) & is_tree_m[:-1, :]
    tree_inner_edge[1:, :] |= diff_d & both_trees_d & (dz_d < -1.35) & is_tree_m[1:, :]
    tree_inner_edge &= ~tree_world_edge

    if bldg_edge.any():
        ey, ex = np.nonzero(bldg_edge)
        if is_night:
            rgb_buf[ey, ex] *= 0.52
        elif preset_key == "sunset":
            rgb_buf[ey, ex] *= np.array([0.38, 0.34, 0.44], dtype=np.float32)
        else:
            sky_adj = ndimage.binary_dilation(mat_buf == M_BG, iterations=1)
            is_soft_e = (mat_buf[ey, ex] == M_BRIDGE) | sky_adj[ey, ex]
            e_mult = np.where(is_soft_e[:, None], [0.54, 0.56, 0.64], [0.36, 0.38, 0.45]).astype(np.float32)
            rgb_buf[ey, ex] *= e_mult
    if bldg_crease.any():
        cy_b, cx_b = np.nonzero(bldg_crease)
        if is_night:
            rgb_buf[cy_b, cx_b] *= 0.60
        else:
            rgb_buf[cy_b, cx_b] *= np.array([0.46, 0.48, 0.56], dtype=np.float32)
    # v13 M1B Iter2: Softer hue-shifted botanical sel-out for foliage (NEVER harsh near-black cartoon rings!)
    if tree_world_sh.any():
        ty, tx = np.nonzero(tree_world_sh)
        c_sh = rgb_buf[ty, tx]
        if is_night:
            rgb_buf[ty, tx] = 0.66 * c_sh + 0.34 * np.array([12.0, 24.0, 30.0], dtype=np.float32)
        else:
            is_red_fol = c_sh[:, 0] > c_sh[:, 1]
            sel_tint = np.where(is_red_fol[:, None], [42.0, 22.0, 30.0], [18.0, 46.0, 28.0]).astype(np.float32)
            rgb_buf[ty, tx] = 0.58 * c_sh + 0.42 * sel_tint
    if tree_world_sun.any():
        ty_s, tx_s = np.nonzero(tree_world_sun)
        rgb_buf[ty_s, tx_s] *= np.array([0.76, 0.84, 0.70], dtype=np.float32) if not is_night else 0.78
    if tree_inner_edge.any():
        iy_t, ix_t = np.nonzero(tree_inner_edge)
        rgb_buf[iy_t, ix_t] *= np.array([0.78, 0.86, 0.76], dtype=np.float32) if not is_night else 0.80

    island_fg = mat_buf > M_DROP_SHADOW
    island_border = (
        island_fg
        & (~ndimage.binary_erosion(island_fg, iterations=1, border_value=0))
        & (~bldg_edge)
        & (~tree_world_edge)
        & (~is_thin_pole)
    )
    if island_border.any():
        by, bx = np.nonzero(island_border)
        rgb_buf[by, bx] *= 0.46

    if not is_night:
        # 1px sunlit warm bevel highlight along sun-facing building roof-eave & top-left edges
        bldg_sun_bevel = np.zeros(zbuf.shape, dtype=np.bool_)
        bldg_sun_bevel[1:, :] |= diff_d & (dz_d < -0.65) & (mat_buf[1:, :] == M_ROOF)
        bldg_sun_bevel[:, 1:] |= diff_r & (dz_r < -0.65) & (mat_buf[:, 1:] == M_ROOF)
        bldg_sun_bevel &= ~bldg_edge
        if bldg_sun_bevel.any():
            by_b, bx_b = np.nonzero(bldg_sun_bevel)
            rim_add = np.array([26.0, 20.0, 10.0], dtype=np.float32) if preset_key == "sunset" else np.array([20.0, 18.0, 14.0], dtype=np.float32)
            rgb_buf[by_b, bx_b] = np.minimum(255.0, rgb_buf[by_b, bx_b] + rim_add)

        roof_m = mat_buf == M_ROOF
        same_b = (obj_buf[:-1, :] == obj_buf[1:, :]) & roof_m[:-1, :] & roof_m[1:, :]
        ridge = same_b & (ndot_d < 0.86) & (np.abs(dz_d) < 1.6)
        if ridge.any():
            ry, rx = np.nonzero(ridge)
            rgb_buf[ry, rx] = np.minimum(255.0, rgb_buf[ry, rx] + 24.0)


def _extract_interactive_metadata(
    scene: SceneData,
    camera: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W: int,
    H: int,
) -> dict:
    landmarks_out = []
    for lm in LANDMARKS:
        px, py, _ = camera.project(np.array([lm["e"]]), np.array([lm["n"]]), np.array([lm["z"]]))
        sx, sy = float(px[0] + shift_x), float(py[0] + shift_y)
        landmarks_out.append({
            **lm,
            "uv": [round(sx / W, 5), round(sy / H, 5)],
            "px": [round(sx, 1), round(sy, 1)],
        })

    be = np.array([b["e"] for b in scene.buildings], dtype=np.float32)
    bn = np.array([b["n"] for b in scene.buildings], dtype=np.float32)
    bz = np.array([0.5 * (b["z_ground"] + b["z_roof"]) for b in scene.buildings], dtype=np.float32)
    bpx, bpy, _ = camera.project(be, bn, bz)
    bsx, bsy = bpx + shift_x, bpy + shift_y

    buildings_compact = []
    for i, b in enumerate(scene.buildings):
        if not b["in_kilchberg"] and b["height"] < 8.0:
            continue
        buildings_compact.append({
            "id": b["idx"],
            "u": round(float(bsx[i]) / W, 5),
            "v": round(float(bsy[i]) / H, 5),
            "addr": b.get("address", ""),
            "nb": b.get("neighbourhood", "Kilchberg"),
            "type": b["objektart"],
            "e": int(round(b["e"])),
            "n": int(round(b["n"])),
            "zg": b["z_ground"],
            "zr": b["z_roof"],
            "h": b["height"],
            "rgb": b["roof_rgb"],
        })

    return {
        "canvas_width": W,
        "canvas_height": H,
        "camera": {
            "azimuth_from_deg": camera.azimuth_from_deg,
            "pitch_deg": camera.pitch_deg,
            "mpp": camera.mpp,
            "z_exag": camera.z_exag,
        },
        "stats": {
            "buildings_total": len(scene.buildings),
            "buildings_kilchberg": sum(1 for b in scene.buildings if b["in_kilchberg"]),
            "triangles_3d": int(len(scene.verts)),
            "trees_3d": int(len(scene.tree_e)),
            "palette_colors": 256,
            "ortho_res_cm": int(round(scene.ortho_res * 100)),
            "lidar_res_cm": 50,
            "elevation_min_m": 405.95,
            "elevation_max_m": round(float(scene.dem[scene.kpoly_mask].max()), 1),
        },
        "landmarks": landmarks_out,
        "buildings": buildings_compact,
    }


def _draw_museum_cartouche(
    img: Image.Image,
    preset: LightingPreset,
    camera: IsometricCamera,
    n_bldgs: int,
    n_trees: int,
    crop_box_lv95: tuple[float, float, float, float] | None,
    plate_title: str | None = None,
    plate_subtitle: str | None = None,
) -> Image.Image:
    draw = ImageDraw.Draw(img)
    W, H = img.size
    cs = 2.0 if (W >= 18000 or (crop_box_lv95 is not None and camera.mpp <= 0.16)) else 1.0

    lg_px = int(round(min(38, max(18, (W / cs) // 180)) * cs))
    sm_px = int(round(min(24, max(13, (W / cs) // 290)) * cs))
    xs_px = max(int(round(11 * cs)), sm_px - int(round(2 * cs)))
    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", lg_px)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", sm_px)
        font_xs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", xs_px)
    except Exception:
        font_lg = ImageFont.load_default()
        font_sm = ImageFont.load_default()
        font_xs = font_sm

    b_out = int(round(10 * cs))
    b_in = int(round(16 * cs))
    bw_out = max(2, int(round(2 * cs)))
    bw_in = max(1, int(round(1 * cs)))
    border_outer = (88, 98, 118) if not preset.is_night else (58, 72, 102)
    border_inner = (182, 166, 134) if not preset.is_night else (148, 126, 88)
    draw.rectangle([b_out, b_out, W - b_out - 1, H - b_out - 1], outline=border_outer, width=bw_out)
    draw.rectangle([b_in, b_in, W - b_in - 1, H - b_in - 1], outline=border_inner, width=bw_in)

    # F13: Brass Corner Registration L-Brackets & Diamond Center Dots
    tick = int(round((18 if (W / cs) >= 4000 else 12) * cs))
    d_off = int(round(6 * cs))
    d_rad = max(2, int(round(2 * cs)))
    for (cx_c, cy_c, sx_c, sy_c) in (
        (b_in, b_in, 1, 1), (W - b_in - 1, b_in, -1, 1), (b_in, H - b_in - 1, 1, -1), (W - b_in - 1, H - b_in - 1, -1, -1)
    ):
        draw.line([(cx_c, cy_c), (cx_c + sx_c * tick, cy_c)], fill=border_inner, width=bw_out)
        draw.line([(cx_c, cy_c), (cx_c, cy_c + sy_c * tick)], fill=border_inner, width=bw_out)
        dx_d, dy_d = cx_c + sx_c * d_off, cy_c + sy_c * d_off
        draw.polygon([(dx_d, dy_d - d_rad), (dx_d + d_rad, dy_d), (dx_d, dy_d + d_rad), (dx_d - d_rad, dy_d)], fill=border_inner)

    sw = lg_px + sm_px + int(round(10 * cs))
    sx0, sy0 = int(round(36 * cs)), int(round(30 * cs))
    draw.rectangle([sx0, sy0, sx0 + sw, sy0 + sw], fill=(208, 38, 38), outline=(246, 243, 236), width=bw_out)
    arm_w = max(4, sw // 4)
    arm_l = int(sw * 0.62)
    cx_s, cy_s = sx0 + sw // 2, sy0 + sw // 2
    draw.rectangle([cx_s - arm_w // 2, cy_s - arm_l // 2, cx_s + arm_w // 2, cy_s + arm_l // 2], fill=(250, 250, 248))
    draw.rectangle([cx_s - arm_l // 2, cy_s - arm_w // 2, cx_s + arm_l // 2, cy_s + arm_w // 2], fill=(250, 250, 248))

    title = plate_title if plate_title else "KILCHBERG ZH  —  90s 3D ISOMETRIC PIXEL ART DIORAMA"
    mpp_lbl = f"{camera.mpp:.3f}".rstrip("0").rstrip(".")
    if plate_subtitle:
        sub = f"{plate_subtitle}  |  {preset.name.upper()}  |  {mpp_lbl} m/px  |  256-COLOR SVGA"
    else:
        sub = (
            f"256-COLOR SVGA PALETTE  |  {preset.name.upper()}  |  {mpp_lbl} m/px  |  "
            f"{n_bldgs:,} LOD2 3D BUILDINGS  ·  {n_trees:,} 3D TREES  ·  SWISSTOPO GIS"
        )
    tx = sx0 + sw + int(round(18 * cs))
    draw.text((tx, sy0), title, fill=(246, 241, 228), font=font_lg)
    draw.text((tx, sy0 + lg_px + int(round(8 * cs))), sub, fill=(176, 188, 206), font=font_sm)

    # F13: Exact Projected Isometric Compass Rose (upper-right margin) showing true North & ESE -> WNW sightline!
    r_cr = int(round((34 if (W / cs) >= 5000 else 24) * cs))
    cr_x = W - int(round(46 * cs)) - r_cr
    cr_y = int(round(32 * cs)) + r_cr
    p0x, p0y, _ = camera.project(np.array([0.0]), np.array([0.0]), np.array([0.0]))
    pnx_c, pny_c, _ = camera.project(np.array([0.0]), np.array([10.0]), np.array([0.0]))
    pex_c, pey_c, _ = camera.project(np.array([10.0]), np.array([0.0]), np.array([0.0]))
    vnx, vny = float(pnx_c[0] - p0x[0]), float(pny_c[0] - p0y[0])
    vn_len = max(1e-5, math.hypot(vnx, vny))
    vnx, vny = vnx / vn_len, vny / vn_len
    vex, vey = float(pex_c[0] - p0x[0]), float(pey_c[0] - p0y[0])
    ve_len = max(1e-5, math.hypot(vex, vey))
    vex, vey = vex / ve_len, vey / ve_len
    draw.ellipse([cr_x - r_cr, cr_y - r_cr, cr_x + r_cr, cr_y + r_cr], outline=border_inner, width=bw_in)
    draw.line(
        [(cr_x - vex * r_cr * 0.72, cr_y - vey * r_cr * 0.72), (cr_x + vex * r_cr * 0.72, cr_y + vey * r_cr * 0.72)],
        fill=(146, 156, 174), width=bw_in,
    )
    draw.line([(cr_x, cr_y), (cr_x - vnx * r_cr * 0.72, cr_y - vny * r_cr * 0.72)], fill=(196, 192, 182), width=bw_out)
    tip_x, tip_y = cr_x + vnx * r_cr * 0.92, cr_y + vny * r_cr * 0.92
    perp_x, perp_y = -vny * 4.5 * cs, vnx * 4.5 * cs
    draw.polygon(
        [(tip_x, tip_y), (cr_x + perp_x, cr_y + perp_y), (cr_x - perp_x, cr_y - perp_y)],
        fill=(216, 48, 44), outline=(246, 241, 228),
    )
    draw.text((int(tip_x + vnx * 7 * cs - 4 * cs), int(tip_y + vny * 7 * cs - 7 * cs)), "N", fill=(246, 241, 228), font=font_xs)
    draw.text((cr_x - r_cr - int(round(14 * cs)), cr_y + r_cr + int(round(5 * cs))), "ESE → WNW", fill=(168, 178, 196), font=font_xs)

    # 4-segment alternating Swiss Scale Bar with 0 / mid / max ticks
    bar_m = 100 if crop_box_lv95 is not None else 250
    bar_px = int(round(bar_m / camera.mpp))
    bx1 = W - int(round(42 * cs))
    bx0 = bx1 - bar_px
    by = H - int(round(40 * cs))
    bar_h = int(round(7 * cs))
    seg_w = bar_px / 4.0
    for si_b in range(4):
        sx_a = int(round(bx0 + si_b * seg_w))
        sx_b = int(round(bx0 + (si_b + 1) * seg_w))
        c_seg = (208, 48, 44) if (si_b % 2 == 0) else (238, 232, 218)
        draw.rectangle([sx_a, by - bar_h, sx_b, by], fill=c_seg, outline=(32, 38, 48), width=bw_in)
    lbl_y = by - int(round(26 * cs))
    draw.text((bx0, lbl_y), "0", fill=(214, 220, 230), font=font_sm)
    mid_txt = f"{bar_m // 2}"
    draw.text((bx0 + bar_px // 2 - len(mid_txt) * (sm_px // 4), lbl_y), mid_txt, fill=(214, 220, 230), font=font_sm)
    end_txt = f"{bar_m} m"
    draw.text((bx1 - len(end_txt) * (sm_px * 6 // 10), lbl_y), end_txt, fill=(214, 220, 230), font=font_sm)

    credit = "DATA: © SWISSTOPO (SWISSALTI3D 2026 · SWISSBUILDINGS3D 3.0 2025 · SWISSSURFACE3D 0.5m · SWISSIMAGE DOP10 2025 · SWISSBATHY3D)"
    draw.text((int(round(36 * cs)), H - int(round(44 * cs))), credit, fill=(148, 160, 180), font=font_sm)
    return img


def _draw_museum_cartouche_memmap(
    full_rgb: np.ndarray,
    preset: LightingPreset,
    camera: IsometricCamera,
    n_bldgs: int,
    n_trees: int,
) -> None:
    """Draw the museum cartouche directly onto the 4 border strips of a large np.memmap canvas
    without ever copying the full 268 MP canvas into RAM / PIL!"""
    H, W, _ = full_rgb.shape
    cs = 2.0 if W >= 18000 else 1.0
    b_out = int(round(10 * cs))
    b_in = int(round(16 * cs))
    bw_out = max(2, int(round(2 * cs)))
    bw_in = max(1, int(round(1 * cs)))
    border_outer = np.array((88, 98, 118) if not preset.is_night else (58, 72, 102), dtype=np.uint8)
    border_inner = np.array((182, 166, 134) if not preset.is_night else (148, 126, 88), dtype=np.uint8)

    # 1. Outer & inner frame lines directly on memmap slices (zero RAM copy!)
    full_rgb[b_out : b_out + bw_out, b_out : W - b_out] = border_outer
    full_rgb[H - b_out - bw_out : H - b_out, b_out : W - b_out] = border_outer
    full_rgb[b_out : H - b_out, b_out : b_out + bw_out] = border_outer
    full_rgb[b_out : H - b_out, W - b_out - bw_out : W - b_out] = border_outer

    full_rgb[b_in : b_in + bw_in, b_in : W - b_in] = border_inner
    full_rgb[H - b_in - bw_in : H - b_in, b_in : W - b_in] = border_inner
    full_rgb[b_in : H - b_in, b_in : b_in + bw_in] = border_inner
    full_rgb[b_in : H - b_in, W - b_in - bw_in : W - b_in] = border_inner

    # 2. Top strip (header, Swiss flag badge, compass rose, top L-brackets)
    top_h = min(H, int(round(260 * cs)))
    top_im = Image.fromarray(np.array(full_rgb[:top_h, :]), mode="RGB")
    td = ImageDraw.Draw(top_im)
    lg_px = int(round(min(38, max(18, (W / cs) // 180)) * cs))
    sm_px = int(round(min(24, max(13, (W / cs) // 290)) * cs))
    xs_px = max(int(round(11 * cs)), sm_px - int(round(2 * cs)))
    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", lg_px)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", sm_px)
        font_xs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", xs_px)
    except Exception:
        font_lg = ImageFont.load_default()
        font_sm = ImageFont.load_default()
        font_xs = font_sm

    b_in_t = tuple(int(v) for v in border_inner)
    tick = int(round((18 if (W / cs) >= 4000 else 12) * cs))
    d_off = int(round(6 * cs))
    d_rad = max(2, int(round(2 * cs)))
    for (cx_c, cy_c, sx_c, sy_c) in ((b_in, b_in, 1, 1), (W - b_in - 1, b_in, -1, 1)):
        td.line([(cx_c, cy_c), (cx_c + sx_c * tick, cy_c)], fill=b_in_t, width=bw_out)
        td.line([(cx_c, cy_c), (cx_c, cy_c + sy_c * tick)], fill=b_in_t, width=bw_out)
        dx_d, dy_d = cx_c + sx_c * d_off, cy_c + sy_c * d_off
        td.polygon([(dx_d, dy_d - d_rad), (dx_d + d_rad, dy_d), (dx_d, dy_d + d_rad), (dx_d - d_rad, dy_d)], fill=b_in_t)

    sw = lg_px + sm_px + int(round(10 * cs))
    sx0, sy0 = int(round(36 * cs)), int(round(30 * cs))
    td.rectangle([sx0, sy0, sx0 + sw, sy0 + sw], fill=(208, 38, 38), outline=(246, 243, 236), width=bw_out)
    arm_w = max(4, sw // 4)
    arm_l = int(sw * 0.62)
    cx_s, cy_s = sx0 + sw // 2, sy0 + sw // 2
    td.rectangle([cx_s - arm_w // 2, cy_s - arm_l // 2, cx_s + arm_w // 2, cy_s + arm_l // 2], fill=(250, 250, 248))
    td.rectangle([cx_s - arm_l // 2, cy_s - arm_w // 2, cx_s + arm_l // 2, cy_s + arm_w // 2], fill=(250, 250, 248))

    mpp_lbl = f"{camera.mpp:.3f}".rstrip("0").rstrip(".")
    title = "KILCHBERG ZH  —  90s 3D ISOMETRIC PIXEL ART DIORAMA"
    sub = (
        f"256-COLOR SVGA PALETTE  |  {preset.name.upper()}  |  {mpp_lbl} m/px  |  "
        f"{n_bldgs:,} LOD2 3D BUILDINGS  ·  {n_trees:,} 3D TREES  ·  SWISSTOPO GIS"
    )
    tx = sx0 + sw + int(round(18 * cs))
    td.text((tx, sy0), title, fill=(246, 241, 228), font=font_lg)
    td.text((tx, sy0 + lg_px + int(round(8 * cs))), sub, fill=(176, 188, 206), font=font_sm)

    r_cr = int(round((34 if (W / cs) >= 5000 else 24) * cs))
    cr_x = W - int(round(46 * cs)) - r_cr
    cr_y = int(round(32 * cs)) + r_cr
    p0x, p0y, _ = camera.project(np.array([0.0]), np.array([0.0]), np.array([0.0]))
    pnx_c, pny_c, _ = camera.project(np.array([0.0]), np.array([10.0]), np.array([0.0]))
    pex_c, pey_c, _ = camera.project(np.array([10.0]), np.array([0.0]), np.array([0.0]))
    vnx, vny = float(pnx_c[0] - p0x[0]), float(pny_c[0] - p0y[0])
    vn_len = max(1e-5, math.hypot(vnx, vny))
    vnx, vny = vnx / vn_len, vny / vn_len
    vex, vey = float(pex_c[0] - p0x[0]), float(pey_c[0] - p0y[0])
    ve_len = max(1e-5, math.hypot(vex, vey))
    vex, vey = vex / ve_len, vey / ve_len
    td.ellipse([cr_x - r_cr, cr_y - r_cr, cr_x + r_cr, cr_y + r_cr], outline=b_in_t, width=bw_in)
    td.line(
        [(cr_x - vex * r_cr * 0.72, cr_y - vey * r_cr * 0.72), (cr_x + vex * r_cr * 0.72, cr_y + vey * r_cr * 0.72)],
        fill=(146, 156, 174), width=bw_in,
    )
    td.line([(cr_x, cr_y), (cr_x - vnx * r_cr * 0.72, cr_y - vny * r_cr * 0.72)], fill=(196, 192, 182), width=bw_out)
    tip_x, tip_y = cr_x + vnx * r_cr * 0.92, cr_y + vny * r_cr * 0.92
    perp_x, perp_y = -vny * 4.5 * cs, vnx * 4.5 * cs
    td.polygon(
        [(tip_x, tip_y), (cr_x + perp_x, cr_y + perp_y), (cr_x - perp_x, cr_y - perp_y)],
        fill=(216, 48, 44), outline=(246, 241, 228),
    )
    td.text((int(tip_x + vnx * 7 * cs - 4 * cs), int(tip_y + vny * 7 * cs - 7 * cs)), "N", fill=(246, 241, 228), font=font_xs)
    td.text((cr_x - r_cr - int(round(14 * cs)), cr_y + r_cr + int(round(5 * cs))), "ESE → WNW", fill=(168, 178, 196), font=font_xs)
    full_rgb[:top_h, :] = np.asarray(top_im)
    del top_im

    # 3. Bottom strip (scale bar, credit, bottom L-brackets)
    bot_h = min(H, int(round(160 * cs)))
    bot_y0 = H - bot_h
    bot_im = Image.fromarray(np.array(full_rgb[bot_y0:, :]), mode="RGB")
    bd = ImageDraw.Draw(bot_im)
    for (cx_c, cy_c, sx_c, sy_c) in ((b_in, bot_h - b_in - 1, 1, -1), (W - b_in - 1, bot_h - b_in - 1, -1, -1)):
        bd.line([(cx_c, cy_c), (cx_c + sx_c * tick, cy_c)], fill=b_in_t, width=bw_out)
        bd.line([(cx_c, cy_c), (cx_c, cy_c + sy_c * tick)], fill=b_in_t, width=bw_out)
        dx_d, dy_d = cx_c + sx_c * d_off, cy_c + sy_c * d_off
        bd.polygon([(dx_d, dy_d - d_rad), (dx_d + d_rad, dy_d), (dx_d, dy_d + d_rad), (dx_d - d_rad, dy_d)], fill=b_in_t)

    bar_m = 250
    bar_px = int(round(bar_m / camera.mpp))
    bx1 = W - int(round(42 * cs))
    bx0 = bx1 - bar_px
    by = bot_h - int(round(40 * cs))
    bar_h = int(round(7 * cs))
    seg_w = bar_px / 4.0
    for si_b in range(4):
        sx_a = int(round(bx0 + si_b * seg_w))
        sx_b = int(round(bx0 + (si_b + 1) * seg_w))
        c_seg = (208, 48, 44) if (si_b % 2 == 0) else (238, 232, 218)
        bd.rectangle([sx_a, by - bar_h, sx_b, by], fill=c_seg, outline=(32, 38, 48), width=bw_in)
    lbl_y = by - int(round(26 * cs))
    bd.text((bx0, lbl_y), "0", fill=(214, 220, 230), font=font_sm)
    mid_txt = f"{bar_m // 2}"
    bd.text((bx0 + bar_px // 2 - len(mid_txt) * (sm_px // 4), lbl_y), mid_txt, fill=(214, 220, 230), font=font_sm)
    end_txt = f"{bar_m} m"
    bd.text((bx1 - len(end_txt) * (sm_px * 6 // 10), lbl_y), end_txt, fill=(214, 220, 230), font=font_sm)
    credit = "DATA: © SWISSTOPO (SWISSALTI3D 2026 · SWISSBUILDINGS3D 3.0 2025 · SWISSSURFACE3D 0.5m · SWISSIMAGE DOP10 2025 · SWISSBATHY3D)"
    bd.text((int(round(36 * cs)), bot_h - int(round(44 * cs))), credit, fill=(148, 160, 180), font=font_sm)
    full_rgb[bot_y0:, :] = np.asarray(bot_im)
    del bot_im


def render_diorama_tiled_hires(
    scene: SceneData,
    mpp: float,
    preset_key: str,
    tiles_dir: Path,
    overview_webp_path: Path,
    full_png_path: Path,
    tile_size: int = 1024,
    collect_hit_boxes: bool = False,
    depth_only: bool = False,
    macro_rows: tuple[int, int] | None = None,
    finalize_tiles: bool = True,
    finalize_only: bool = False,
) -> dict:
    """Render ultra-high-resolution (343.9 MP at 0.11 m/px) full municipality via /tmp np.memmap
    in memory-safe seamless macro-tiles, supporting split --macro-rows bands + --finalize-tiles,
    streaming 2-level WebP tile pyramid (L1 0.22 m/px + L2 0.11 m/px), streaming 0.44 m/px overview,
    and DEPTH_DS=4 (0.44 m/px) 16-bit depth map."""
    import gc

    preset = PRESETS[preset_key]
    cam = IsometricCamera(mpp=mpp)
    (
        cam,
        active_mask,
        plinth_z,
        W_full,
        H_full,
        shift_x_full,
        shift_y_full,
        *_,
    ) = compute_full_canvas_geometry(scene, cam, None, True)

    # Export 0.44 m/px (6992x3073 @ 0.11 m/px) 16-bit 3D Depth & Occluder Map during 'day' pass
    DEPTH_DS = max(2, int(0.50 / mpp))
    DEPTH_MIN = -2400.0
    DEPTH_MAX = 2400.0
    dw_f = W_full // DEPTH_DS
    dh_f = H_full // DEPTH_DS
    save_depth = (preset_key == "day") or depth_only

    RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    full_mmap_p = RAW_CACHE_DIR / f"_tmp_full_{preset_key}.mmap"
    depth_mmap_p = RAW_CACHE_DIR / "_tmp_depth.mmap"

    exp_full_bytes = int(H_full) * int(W_full) * 3
    exp_depth_bytes = int(dh_f) * int(dw_f) * 3

    is_first_band = (macro_rows is None and not finalize_only) or (macro_rows is not None and macro_rows[0] == 0)

    full_rgb = None
    if not depth_only:
        need_create_full = (not full_mmap_p.exists()) or (full_mmap_p.stat().st_size != exp_full_bytes) or is_first_band
        if finalize_only:
            assert full_mmap_p.exists() and full_mmap_p.stat().st_size == exp_full_bytes, (
                f"Cannot --finalize-tiles: missing or wrong-size memmap {full_mmap_p} (expected {exp_full_bytes} bytes)"
            )
            full_rgb = np.memmap(full_mmap_p, dtype=np.uint8, mode="r+", shape=(H_full, W_full, 3))
        else:
            mode_f = "w+" if need_create_full else "r+"
            full_rgb = np.memmap(full_mmap_p, dtype=np.uint8, mode=mode_f, shape=(H_full, W_full, 3))

    depth_rgb = None
    if save_depth:
        need_create_d = (not depth_mmap_p.exists()) or (depth_mmap_p.stat().st_size != exp_depth_bytes) or is_first_band
        if finalize_only:
            if depth_mmap_p.exists() and depth_mmap_p.stat().st_size == exp_depth_bytes:
                depth_rgb = np.memmap(depth_mmap_p, dtype=np.uint8, mode="r+", shape=(dh_f, dw_f, 3))
        else:
            mode_d = "w+" if need_create_d else "r+"
            depth_rgb = np.memmap(depth_mmap_p, dtype=np.uint8, mode=mode_d, shape=(dh_f, dw_f, 3))
            if mode_d == "w+":
                depth_rgb[:, :, 0] = 255
                depth_rgb[:, :, 1] = 255
                depth_rgb[:, :, 2] = 0

    if mpp <= 0.18:
        nx_macro, ny_macro = 16, 8
        guard_x, guard_y = 56, 128
    else:
        nx_macro, ny_macro = 6, 3
        guard_x, guard_y = 24, 56

    if not finalize_only:
        sun_sh = compute_shadow_grid(scene, preset.sun_az_deg, preset.sun_alt_deg)

        # Coarse projected diorama occupancy mask (256-px cells) for lossless empty-sky macro-tile fast-path!
        ar_occ, ac_occ = np.nonzero(active_mask)
        ae_occ = E_MIN + (ac_occ[::8] + 0.5) * GRID_RES
        an_occ = N_MAX - (ar_occ[::8] + 0.5) * GRID_RES
        z_occ = scene.dem[ar_occ[::8], ac_occ[::8]]
        px_hi, py_hi, _ = cam.project(ae_occ, an_occ, z_occ + 52.0)
        px_lo, py_lo, _ = cam.project(ae_occ + 14.0, an_occ - 12.0, np.full_like(ae_occ, plinth_z - 12.0))
        all_px = np.concatenate([px_hi, px_lo]) + shift_x_full
        all_py = np.concatenate([py_hi, py_lo]) + shift_y_full
        del ar_occ, ac_occ, ae_occ, an_occ, z_occ, px_hi, py_hi, px_lo, py_lo

        r_start = 0 if macro_rows is None else max(0, int(macro_rows[0]))
        r_end = ny_macro if macro_rows is None else min(ny_macro, int(macro_rows[1]))
        occ_thresh = (DEPTH_DS * DEPTH_DS) // 2

        for my in range(r_start, r_end):
            y0 = (my * H_full) // ny_macro
            y1 = ((my + 1) * H_full) // ny_macro
            for mx in range(nx_macro):
                x0 = (mx * W_full) // nx_macro
                x1 = ((mx + 1) * W_full) // nx_macro

                wx0 = max(0, x0 - guard_x)
                wy0 = max(0, y0 - guard_y)
                wx1 = min(W_full, x1 + guard_x)
                wy1 = min(H_full, y1 + guard_y)

                # Empty-sky fast-path: strictly outside projected diorama + generous 220px margin -> fill sky directly!
                sky_pad = 220.0
                has_geo = bool(
                    ((all_px >= (wx0 - sky_pad)) & (all_px <= (wx1 + sky_pad))
                     & (all_py >= (wy0 - sky_pad)) & (all_py <= (wy1 + sky_pad))).any()
                )
                if not has_geo:
                    if not depth_only:
                        th_s, tw_s = y1 - y0, x1 - x0
                        gy_s = (np.arange(y0, y1, dtype=np.float32) / max(1, H_full - 1))[:, None]
                        bg_s = (1.0 - gy_s) * np.array(preset.sky_top_rgb, dtype=np.float32) + gy_s * np.array(preset.sky_bot_rgb, dtype=np.float32)
                        sky_rgb = np.broadcast_to(bg_s[:, None, :], (th_s, tw_s, 3)).copy()
                        bayer_s = BAYER_4X4[(np.arange(y0, y1)[:, None]) % 4, (np.arange(x0, x1)[None, :]) % 4] * 0.42
                        full_rgb[y0:y1, x0:x1] = quantize_to_90s_palette(sky_rgb, bayer_s, preset.dither_strength, preset_key=preset_key)
                        del sky_rgb, bayer_s
                    continue

                dbuf = {} if save_depth else None
                sub_img, _ = render_diorama(
                    scene,
                    cam,
                    preset_key=preset_key,
                    crop_box_lv95=None,
                    add_frame=True,
                    collect_hit_boxes=False,
                    viewport_win=(wx0, wy0, wx1, wy1),
                    sun_shadow_override=sun_sh,
                    out_depth_buf=dbuf,
                )
                if not depth_only:
                    sub_arr = np.asarray(sub_img)
                    full_rgb[y0:y1, x0:x1] = sub_arr[(y0 - wy0) : (y1 - wy0), (x0 - wx0) : (x1 - wx0)]
                    del sub_arr

                if save_depth and depth_rgb is not None and dbuf:
                    sz = dbuf["zbuf"]
                    sm = dbuf["mat_buf"]
                    so = dbuf["obj_buf"]
                    dy0 = y0 // DEPTH_DS
                    dy1 = min(dh_f, (y1 + DEPTH_DS - 1) // DEPTH_DS)
                    dx0 = x0 // DEPTH_DS
                    dx1 = min(dw_f, (x1 + DEPTH_DS - 1) // DEPTH_DS)
                    if dy1 > dy0 and dx1 > dx0:
                        ly0 = dy0 * DEPTH_DS - wy0
                        ly1 = dy1 * DEPTH_DS - wy0
                        lx0 = dx0 * DEPTH_DS - wx0
                        lx1 = dx1 * DEPTH_DS - wx0
                        if ly0 >= 0 and lx0 >= 0 and ly1 <= sz.shape[0] and lx1 <= sz.shape[1]:
                            z_blk = sz[ly0:ly1, lx0:lx1].reshape(dy1 - dy0, DEPTH_DS, dx1 - dx0, DEPTH_DS)
                            m_blk = sm[ly0:ly1, lx0:lx1].reshape(dy1 - dy0, DEPTH_DS, dx1 - dx0, DEPTH_DS)
                            o_blk = so[ly0:ly1, lx0:lx1].reshape(dy1 - dy0, DEPTH_DS, dx1 - dx0, DEPTH_DS)
                            is_thin_overhead = (
                                ((o_blk >= 310000) & (o_blk < 310200))  # SBB catenary portals, wires & droppers
                                | ((o_blk >= 238000) & (o_blk < 245000))  # 1px streetlamp poles & heads (1,582 lamps)
                            )
                            occ_m = (
                                (
                                    (m_blk == M_WALL)
                                    | (m_blk == M_ROOF)
                                    | (m_blk == M_WINDOW_DAY)
                                    | (m_blk == M_WINDOW_LIT)
                                    | (m_blk == M_TREE)
                                    | (m_blk == M_TRUNK)
                                    | (m_blk == M_BRIDGE)
                                    | (m_blk == M_HARBOR_OBJ)
                                )
                                & (~is_thin_overhead)
                            )
                            occ_cnt = occ_m.sum(axis=(1, 3))
                            has_occ = occ_cnt >= occ_thresh
                            if has_occ.any():
                                z_masked = np.where(occ_m, z_blk, 1e9)
                                d_min_blk = z_masked.min(axis=(1, 3))
                                v16 = np.clip(
                                    np.round((d_min_blk - DEPTH_MIN) / (DEPTH_MAX - DEPTH_MIN) * 65535.0),
                                    0,
                                    65535,
                                ).astype(np.uint16)
                                sub_dr = depth_rgb[dy0:dy1, dx0:dx1]
                                sub_dr[has_occ, 0] = (v16[has_occ] >> 8).astype(np.uint8)
                                sub_dr[has_occ, 1] = (v16[has_occ] & 0xFF).astype(np.uint8)
                                sub_dr[has_occ, 2] = 255
                    del dbuf

                del sub_img
                gc.collect()
                _evict_mmap_rss(scene.ortho_hr)
                _evict_mmap_rss(scene.roof_edge_25cm)
                if full_rgb is not None:
                    full_rgb.flush()
                    _evict_mmap_rss(full_rgb)
                if depth_rgb is not None:
                    depth_rgb.flush()
                    _evict_mmap_rss(depth_rgb)
        del sun_sh, all_px, all_py
        gc.collect()

    if not finalize_tiles and not depth_only:
        if full_rgb is not None:
            full_rgb.flush()
            del full_rgb
        if depth_rgb is not None:
            depth_rgb.flush()
            del depth_rgb
        gc.collect()
        return {}

    if save_depth and depth_rgb is not None:
        depth_path = overview_webp_path.parent / "kilchberg_depth.png"
        depth_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.array(depth_rgb), mode="RGB").save(depth_path, optimize=True)
        print(f"[render] Saved 16-bit 3D Depth & Occluder Map -> {depth_path} ({dw_f}x{dh_f}, DEPTH_DS={DEPTH_DS})")
        del depth_rgb
    if depth_only:
        gc.collect()
        return {}

    assert full_rgb is not None
    # Draw museum cartouche directly onto the memmap border strips (zero 268 MP RAM copy!)
    _draw_museum_cartouche_memmap(full_rgb, preset, cam, len(scene.buildings), len(scene.tree_e))
    full_rgb.flush()

    # Export L2 full-res tiles (e.g. 0.11 m/px, 28x13) directly from memmap slices
    tiles_dir.mkdir(parents=True, exist_ok=True)
    cols = int(math.ceil(W_full / tile_size))
    rows = int(math.ceil(H_full / tile_size))
    for r in range(rows):
        ty0 = r * tile_size
        ty1 = min(H_full, ty0 + tile_size)
        for c in range(cols):
            tx0 = c * tile_size
            tx1 = min(W_full, tx0 + tile_size)
            tile_im = Image.fromarray(np.array(full_rgb[ty0:ty1, tx0:tx1]), mode="RGB")
            tile_im.save(tiles_dir / f"{c}_{r}.webp", format="WEBP", lossless=True, method=4)

    # Export L1 mid-res pyramid tiles (0.22 m/px, 14x7) by streaming 2*tile_size row bands!
    z1_meta = None
    if mpp <= 0.18:
        z1_dir = tiles_dir / "z1"
        z1_dir.mkdir(parents=True, exist_ok=True)
        z1_w = W_full // 2
        z1_h = H_full // 2
        z1_cols = int(math.ceil(z1_w / tile_size))
        z1_rows = int(math.ceil(z1_h / tile_size))
        for zr in range(z1_rows):
            zy0 = zr * tile_size
            zy1 = min(z1_h, zy0 + tile_size)
            sy0 = zy0 * 2
            sy1 = min(H_full, zy1 * 2)
            band_ds = _downsample_z1_band_svga(
                np.array(full_rgb[sy0:sy1, : z1_w * 2]), z1_w, zy1 - zy0, preset_key
            )
            for zc in range(z1_cols):
                zx0 = zc * tile_size
                zx1 = min(z1_w, zx0 + tile_size)
                band_ds.crop((zx0, 0, zx1, zy1 - zy0)).save(
                    z1_dir / f"{zc}_{zr}.webp", format="WEBP", lossless=True, method=4
                )
            del band_ds
        z1_meta = {
            "width": z1_w,
            "height": z1_h,
            "mpp": round(mpp * 2.0, 4),
            "tileSize": tile_size,
            "cols": z1_cols,
            "rows": z1_rows,
            "path": "z1",
        }

    manifest = {
        "width": W_full,
        "height": H_full,
        "tileSize": tile_size,
        "cols": cols,
        "rows": rows,
        "mpp": mpp,
        "preset": preset_key,
        "depthMin": DEPTH_MIN,
        "depthMax": DEPTH_MAX,
        "macroCols": nx_macro,
        "macroRows": ny_macro,
    }
    if z1_meta is not None:
        manifest["z1"] = z1_meta
    (tiles_dir / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))

    # Stream 0.44 m/px overview (6992x3073 @ 0.11 m/px) by row-band downsampling (zero full-canvas RAM copy!)
    ov_ds = max(2, int(0.50 / mpp))
    ov_w = W_full // ov_ds
    ov_h = H_full // ov_ds
    ov_arr = np.empty((ov_h, ov_w, 3), dtype=np.uint8)
    band_ov_rows = 256
    for oy0 in range(0, ov_h, band_ov_rows):
        oy1 = min(ov_h, oy0 + band_ov_rows)
        sy0 = oy0 * ov_ds
        sy1 = min(H_full, oy1 * ov_ds)
        b_im = Image.fromarray(np.array(full_rgb[sy0:sy1, : ov_w * ov_ds]), mode="RGB")
        b_ds = b_im.resize((ov_w, oy1 - oy0), resample=Image.Resampling.LANCZOS)
        ov_arr[oy0:oy1, :, :] = np.asarray(b_ds)
        del b_im, b_ds

    ov_img = Image.fromarray(ov_arr, mode="RGB")
    del ov_arr
    overview_webp_path.parent.mkdir(parents=True, exist_ok=True)
    ov_img.save(overview_webp_path, format="WEBP", quality=98, method=4)
    full_png_path.parent.mkdir(parents=True, exist_ok=True)
    ov_img.save(full_png_path, optimize=True)
    del ov_img

    hit_data = {}
    if collect_hit_boxes:
        hit_data = _extract_interactive_metadata(scene, cam, shift_x_full, shift_y_full, W_full, H_full)

    del full_rgb
    gc.collect()
    return hit_data


def render_diorama_crop_tiled(
    scene: SceneData,
    camera: IsometricCamera,
    preset_key: str = "day",
    crop_box_lv95: tuple[float, float, float, float] | None = None,
    add_frame: bool = True,
    sun_shadow_override: tuple[np.ndarray, np.ndarray] | None = None,
    plate_title: str | None = None,
    plate_subtitle: str | None = None,
) -> Image.Image:
    """Memory-safe seamless 2x2 windowed renderer for ultra-high-res 0.11 m/px detail plates (~20+ MP)
    so peak RAM stays well below 4.0 GiB on 7 GiB / 0-swap VMs."""
    import gc

    preset = PRESETS[preset_key]
    cam, _, _, W_full, H_full, *_ = compute_full_canvas_geometry(scene, camera, crop_box_lv95, add_frame)
    if W_full * H_full <= 6_500_000:
        img_c, _ = render_diorama(
            scene,
            cam,
            preset_key=preset_key,
            crop_box_lv95=crop_box_lv95,
            add_frame=add_frame,
            sun_shadow_override=sun_shadow_override,
            plate_title=plate_title,
            plate_subtitle=plate_subtitle,
        )
        return img_c

    nx, ny = 2, 2
    guard_x = 48 if cam.mpp <= 0.18 else 24
    guard_y = 112 if cam.mpp <= 0.18 else 56
    canvas = np.empty((H_full, W_full, 3), dtype=np.uint8)
    for my in range(ny):
        y0 = (my * H_full) // ny
        y1 = ((my + 1) * H_full) // ny
        for mx in range(nx):
            x0 = (mx * W_full) // nx
            x1 = ((mx + 1) * W_full) // nx
            wx0 = max(0, x0 - guard_x)
            wy0 = max(0, y0 - guard_y)
            wx1 = min(W_full, x1 + guard_x)
            wy1 = min(H_full, y1 + guard_y)
            sub_img, _ = render_diorama(
                scene,
                cam,
                preset_key=preset_key,
                crop_box_lv95=crop_box_lv95,
                add_frame=add_frame,
                collect_hit_boxes=False,
                viewport_win=(wx0, wy0, wx1, wy1),
                sun_shadow_override=sun_shadow_override,
            )
            sub_arr = np.asarray(sub_img)
            canvas[y0:y1, x0:x1] = sub_arr[(y0 - wy0) : (y1 - wy0), (x0 - wx0) : (x1 - wx0)]
            del sub_arr, sub_img
            gc.collect()
            _evict_mmap_rss(scene.ortho_hr)
            _evict_mmap_rss(scene.roof_edge_25cm)

    img = Image.fromarray(canvas, mode="RGB")
    del canvas
    gc.collect()
    if add_frame:
        img = _draw_museum_cartouche(
            img, preset, cam, len(scene.buildings), len(scene.tree_e), crop_box_lv95,
            plate_title=plate_title, plate_subtitle=plate_subtitle,
        )
    return img


def _downsample_z1_band_svga(
    band_rgb: np.ndarray, out_w: int, out_h: int, preset_key: str
) -> Image.Image:
    """Downsample a 2x L2 band to L1 (z1) using BOX filtering + stateless global 160-color SVGA LUT snapping.
    The 160-color subset is selected deterministically from the preset's 256-color SVGA palette alone
    (zero image/band-histogram dependence), guaranteeing identical RGB -> SVGA mapping across all row bands
    (zero horizontal band seams), strictly <= 160 <= 256 preset SVGA colors, and compact < 500 KB VP8L tiles."""
    cache = getattr(_downsample_z1_band_svga, "_lut_cache", None)
    if cache is None:
        cache = {}
        _downsample_z1_band_svga._lut_cache = cache
    if preset_key not in cache:
        pal, _ = build_90s_palette_and_lut(preset_key)
        p = pal.astype(np.int32)
        n = len(p)
        k = min(160, n)
        selected = [0]
        d = p - p[0]
        min_d = 2 * d[:, 0] ** 2 + 4 * d[:, 1] ** 2 + 3 * d[:, 2] ** 2
        for _ in range(1, k):
            nxt = int(np.argmax(min_d))
            selected.append(nxt)
            d = p - p[nxt]
            dist = 2 * d[:, 0] ** 2 + 4 * d[:, 1] ** 2 + 3 * d[:, 2] ** 2
            min_d = np.minimum(min_d, dist)
        sub_pal = np.ascontiguousarray(pal[selected], dtype=np.uint8)
        sp = sub_pal.astype(np.int32)
        g = np.arange(64, dtype=np.int32) * 4 + 2
        R, G, B = np.meshgrid(g, g, g, indexing="ij")
        pts = np.stack([R, G, B], axis=-1).reshape(-1, 3)
        idx = np.empty(pts.shape[0], dtype=np.uint8)
        for i in range(0, pts.shape[0], 8192):
            diff = pts[i : i + 8192, None, :] - sp[None, :, :]
            dist = 2 * diff[..., 0] ** 2 + 4 * diff[..., 1] ** 2 + 3 * diff[..., 2] ** 2
            idx[i : i + 8192] = np.argmin(dist, axis=1)
        cache[preset_key] = (sub_pal, idx.reshape(64, 64, 64))
    sub_pal, sub_lut = cache[preset_key]
    box_im = Image.fromarray(band_rgb, mode="RGB").resize((out_w, out_h), resample=Image.Resampling.BOX)
    arr = np.asarray(box_im, dtype=np.uint8)
    svga_rgb = sub_pal[sub_lut[arr[..., 0] >> 2, arr[..., 1] >> 2, arr[..., 2] >> 2]]
    return Image.fromarray(svga_rgb, mode="RGB")


def _evict_mmap_rss(arr: np.ndarray | None) -> None:
    """Release clean file-backed mmap pages from process page tables (Linux MADV_DONTNEED) to keep Peak RSS low."""
    if arr is None:
        return
    mm = getattr(arr, "_mmap", None)
    if mm is None and getattr(arr, "base", None) is not None:
        mm = getattr(arr.base, "_mmap", None)
    if mm is not None and hasattr(mm, "madvise"):
        try:
            import mmap as _mmap
            mm.madvise(_mmap.MADV_DONTNEED)
        except Exception:
            pass
