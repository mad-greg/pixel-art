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
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

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
        sun_rgb=(1.04, 1.00, 0.94),
        amb_rgb=(0.53, 0.56, 0.62),
        sky_top_rgb=(24, 34, 52),
        sky_bot_rgb=(38, 52, 74),
        is_night=False,
        dither_strength=7.5,
    ),
    "sunset": LightingPreset(
        name="Alpenglow Golden Sunset",
        sun_az_deg=114.0,
        sun_alt_deg=22.0,
        sun_rgb=(1.38, 1.00, 0.54),
        amb_rgb=(0.39, 0.42, 0.56),
        sky_top_rgb=(28, 24, 52),
        sky_bot_rgb=(82, 50, 58),
        is_night=False,
        dither_strength=8.0,
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
        dither_strength=7.0,
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
    "seebad_bathhouse":  (2684278.7, 1241434.4, 12.0, "Gebaeude"),
    "seebad_kiosk":      (2684265.5, 1241439.3,  8.0, "Gebaeude"),
    "seebad_south":      (2684280.7, 1241400.8, 12.0, "Gebaeude"),
    "seebad_boathouse":  (2684304.0, 1241494.9, 10.0, "Flugdach"),
    "villa_naville_1582":(2684228.2, 1241439.9, 10.0, "Gebaeude"),
    "villa_naville_1695":(2684245.7, 1241450.9, 10.0, "Gebaeude"),
    "schooren_981":      (2684240.5, 1241504.6, 12.0, "Gebaeude"),
    "schooren_1823":     (2684261.0, 1241495.3, 12.0, "Gebaeude"),
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
        # Day: Dedicated crisp 256-color Alpine Midday palette
        # 1. Alpine Foliage, Meadows, Sports Turf & Blossoms — 54 colors
        add_ramp((14, 34, 22), (44, 102, 46), (126, 190, 78), 12)
        add_ramp((20, 42, 24), (62, 126, 52), (156, 208, 92), 11)
        add_ramp((14, 34, 30), (32, 76, 56), (80, 138, 94), 9)
        add_ramp((38, 46, 24), (94, 118, 52), (168, 184, 92), 9)
        add_ramp((36, 18, 26), (88, 38, 46), (144, 68, 72), 6)
        add_ramp((124, 72, 82), (218, 162, 174), (252, 232, 238), 7)

        # 2. Brick, Terracotta Roofs, Clay Courts, Slate/Concrete & PV — 52 colors
        add_ramp((44, 16, 14), (132, 46, 36), (186, 72, 52), 8)
        add_ramp((54, 24, 16), (162, 78, 48), (222, 122, 74), 10)
        add_ramp((40, 26, 18), (112, 74, 52), (180, 132, 98), 8)
        add_ramp((20, 22, 26), (104, 106, 110), (244, 246, 248), 11)
        add_ramp((18, 28, 50), (42, 64, 108), (94, 134, 188), 7)
        add_ramp((48, 44, 38), (136, 128, 114), (204, 196, 180), 8)

        # 3. Swiss Plaster Facades, Ochre, Dusty Rose, Sage & Shutters — 50 colors
        add_ramp((54, 54, 58), (160, 158, 152), (250, 248, 242), 10)
        add_ramp((54, 44, 32), (154, 138, 110), (230, 216, 186), 9)
        add_ramp((64, 48, 22), (178, 148, 68), (248, 224, 118), 9)
        add_ramp((58, 36, 34), (152, 108, 94), (218, 176, 158), 7)
        add_ramp((26, 48, 42), (76, 124, 108), (158, 192, 172), 7)
        add_ramp((18, 26, 40), (54, 84, 126), (126, 164, 212), 8)

        # 4. Streets, Asphalt, Ballast & Molasse/Nagelfluh Geology — 34 colors
        add_ramp((18, 20, 26), (78, 82, 90), (196, 198, 202), 14)
        add_ramp((34, 30, 26), (102, 90, 74), (184, 168, 144), 12)
        add_ramp((26, 22, 22), (74, 56, 42), (134, 116, 92), 8)

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
    dithered = np.clip(rgb_float + bayer_2d[:, :, None] * strength, 0.0, 255.0)
    ri = np.round(dithered[:, :, 0] * (63.0 / 255.0)).astype(np.int32)
    gi = np.round(dithered[:, :, 1] * (63.0 / 255.0)).astype(np.int32)
    bi = np.round(dithered[:, :, 2] * (63.0 / 255.0)).astype(np.int32)
    idx = lut[ri, gi, bi]
    return pal[idx]


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

        # F14a: Per-tree distance to Lake Zurich for weeping lakeside willows (free temporary EDT immediately!)
        dist_lake_05m = ndimage.distance_transform_edt(~self.lake_mask).astype(np.float32) * GRID_RES
        tc_t = np.clip(((self.tree_e - E_MIN) / GRID_RES).astype(np.int32), 0, GRID_W - 1)
        tr_t = np.clip(((N_MAX - self.tree_n) / GRID_RES).astype(np.int32), 0, GRID_H - 1)
        self.tree_dist_lake = dist_lake_05m[tr_t, tc_t].astype(np.float32)
        del dist_lake_05m

        self.ortho_25cm = np.load(cache_dir / "ortho_25cm.npy", mmap_mode="r")
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

        # Precompute 0.5m bare-earth terrain normals (stored as float16 -> saves 156 MB!)
        dem_sm = ndimage.gaussian_filter(self.dem, sigma=0.75)
        dz_drow, dz_dcol = np.gradient(dem_sm, GRID_RES)
        del dem_sm
        nlen = np.sqrt(dz_dcol * dz_dcol + dz_drow * dz_drow + 1.0)
        self.terr_nx = (-dz_dcol / nlen).astype(np.float16)
        self.terr_ny = (dz_drow / nlen).astype(np.float16)
        self.terr_nz = (1.0 / nlen).astype(np.float16)
        del dz_drow, dz_dcol, nlen

        # V6.0: Multi-scale smooth organic alpine meadow variation field (stored as float16 -> saves 52 MB!)
        rng_m = np.random.default_rng(1350135)
        raw_n = rng_m.standard_normal((GRID_H // 4 + 2, GRID_W // 4 + 2)).astype(np.float32)
        coarse_n = ndimage.gaussian_filter(raw_n, sigma=6.5)
        med_n = ndimage.gaussian_filter(raw_n, sigma=2.0)
        comb_n = 0.65 * coarse_n + 0.35 * med_n
        comb_n = (comb_n - comb_n.mean()) / max(1e-5, comb_n.std())
        self.meadow_noise_05m = np.repeat(np.repeat(comb_n, 4, axis=0), 4, axis=1)[:GRID_H, :GRID_W].astype(np.float16)
        del raw_n, coarse_n, med_n, comb_n

        # V6.0: Clean impervious residential courtyard / patio / driveway mask (0.5m)
        o_r = ortho_05m[:, :, 0].astype(np.float32)
        o_g = ortho_05m[:, :, 1].astype(np.float32)
        o_b = ortho_05m[:, :, 2].astype(np.float32)
        del ortho_05m
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
            & (lum05 > 128.0)
            & (chroma05 < 22.0)
            & (green_excess05 < 3.0)
        )
        self.yard_pave_mask_05m = ndimage.binary_closing(
            ndimage.binary_opening(raw_pave, structure=np.ones((2, 2), dtype=bool)),
            structure=np.ones((3, 3), dtype=bool),
        )
        del near_urban, raw_pave, green_excess05

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

        # Clean 0.5m mask of REAL moored boats, piers & Seebad jetties (100% bit-identical to v6.2!)
        near_shore = ndimage.binary_dilation(~self.lake_mask, iterations=190)
        open_water = ndimage.binary_erosion(self.lake_mask, iterations=1, border_value=0)
        deep_harbor = ndimage.binary_erosion(self.lake_mask, iterations=4, border_value=0) & (self.bathy_z <= (LAKE_SURFACE_Z - 1.5))
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
        is_moored_boat = (
            deep_harbor
            & near_shore
            & (~self.bldg_roof_mask)
            & (self.chm >= 0.45)
            & (self.chm <= 3.6)
            & (lum05 > 152.0)
            & (chroma05 < 18.0)
            & (rb_diff05 <= 10.0)
        )
        del o_r, o_g, o_b, lum05, chroma05, rb_diff05, near_shore, open_water, deep_harbor
        clean_pier = np.zeros_like(is_lidar_pier)
        lbl_p, n_p = ndimage.label(is_lidar_pier & (~is_pier))
        if n_p > 0:
            cnt_p = np.bincount(lbl_p.ravel())
            keep_p = (cnt_p >= 6) & (cnt_p <= 1200)
            keep_p[0] = False
            clean_pier = keep_p[lbl_p]
        del is_lidar_pier, lbl_p
        clean_boat = np.zeros_like(is_moored_boat)
        lbl_b, n_b = ndimage.label(is_moored_boat & (~is_pier) & (~clean_pier))
        if n_b > 0:
            cnt_b = np.bincount(lbl_b.ravel())
            keep_b = (cnt_b >= 4) & (cnt_b <= 180)
            keep_b[0] = False
            clean_boat = keep_b[lbl_b]
        del is_moored_boat, lbl_b
        self.harbor_obj_mask = is_pier | clean_pier | clean_boat
        self.pier_only_mask_05m = is_pier | clean_pier
        del is_pier, clean_pier, clean_boat

        # F9: Crisp 1-2px organic shore & pier foam rings (0 extra float arrays!)
        foam_base = (~self.lake_mask) | self.harbor_obj_mask
        self.foam_ring1_05m = self.lake_mask & (~self.harbor_obj_mask) & ndimage.binary_dilation(foam_base, iterations=1)
        self.foam_ring2_05m = (
            self.lake_mask
            & (~self.harbor_obj_mask)
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
        rcols = np.clip(((rcent[:, 0] - E_MIN) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_W - 1)
        rrows = np.clip(((N_MAX - rcent[:, 1]) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_H - 1)
        rgb_tri = np.asarray(self.ortho_25cm[rrows, rcols], dtype=np.float32)
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
            pc4 = np.clip(((pts4[:, :, 0] - E_MIN) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_W - 1)
            pr4 = np.clip(((N_MAX - pts4[:, :, 1]) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_H - 1)
            rgb4 = np.asarray(self.ortho_25cm[pr4, pc4], dtype=np.float32)  # (N_pit, 4, 3)
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
                    if (kh % 9) >= 5:
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
                            or self.bldg_roof_mask[rc_t, cc_t]
                            or self.hedge_mask[rc_t, cc_t]
                        ):
                            ok_bay = False
                            break
                    if not ok_bay:
                        continue
                    rc_c = int(round((N_MAX - pn_k) * 2.0))
                    cc_c = int(round((pe_k - E_MIN) * 2.0))
                    pz_k = float(self.dem[rc_c, cc_c])
                    facing = 1.0 if (bay_sub == 1) else -1.0
                    cars.append((float(pe_k), float(pn_k), pz_k, int(kh % 7), facing))
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
    """Sample exact 25 cm SWISSIMAGE DOP10 RGB at arbitrary world LV95 (E, N) coordinates."""
    cols = np.clip(((e_arr - E_MIN) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_W - 1)
    rows = np.clip(((N_MAX - n_arr) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_H - 1)
    return np.asarray(scene.ortho_25cm[rows, cols])


def sample_roof_edge_25cm(scene: SceneData, e_arr: np.ndarray, n_arr: np.ndarray) -> np.ndarray:
    """Sample exact 25 cm roof parapet step band (1=outer coping, 2=inner shadow, 3..4=interior)."""
    cols = np.clip(((e_arr - E_MIN) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_W - 1)
    rows = np.clip(((N_MAX - n_arr) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_H - 1)
    return np.asarray(scene.roof_edge_25cm[rows, cols])


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
    h_sub = np.maximum(dem_sub + scene.chm[rmin:rmax, cmin:cmax], scene.bridge_z[rmin:rmax, cmin:cmax])
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
    } - {-1}
    seebad_ids = {
        lm.get("seebad_bathhouse", -1),
        lm.get("seebad_kiosk", -1),
        lm.get("seebad_south", -1),
    } - {-1}
    gemeindehaus_ids = {lm.get("gemeindehaus_main", -1), lm.get("gemeindehaus_wing", -1)} - {-1}
    cf_meyer_ids = {lm.get("cf_meyer_haus", -1), lm.get("cf_meyer_pin_villa", -1)} - {-1}
    barn_ids = {lm.get("dorf_barn_1490", -1), lm.get("dorf_barn_1726", -1)} - {-1}

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
            wall_rgb[i] = (164, 158, 146) if obj == "Mauer gross" else (172, 168, 160)
            style_code[i] = 5
        elif obj in ("Sakrales Gebaeude", "Sakraler Turm"):
            wall_rgb[i] = (228, 224, 214) if nc < 1241450 else (198, 192, 180)
            style_code[i] = 4
        elif i == lm.get("lindt_hoc", -1):
            wall_rgb[i] = (154, 58, 46)
            style_code[i] = 2
        elif i in (lm.get("lindt_brick_n", -1), lm.get("lindt_brick_s", -1)):
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
            wall_rgb[i] = (208, 206, 198)
            style_code[i] = 3
        elif i == lm.get("bahnhof_station", -1):
            wall_rgb[i] = (216, 204, 180)
            style_code[i] = 9
        elif i in gemeindehaus_ids:
            wall_rgb[i] = (224, 218, 204)
            style_code[i] = 9
        elif i in cf_meyer_ids:
            wall_rgb[i] = (224, 210, 168)
            style_code[i] = 9
        elif i in sanatorium_ids:
            wall_rgb[i] = (220, 212, 192) if (i % 2 == 0) else (210, 202, 186)
            style_code[i] = 9
        elif i in seebad_ids:
            wall_rgb[i] = (184, 148, 108)
            style_code[i] = 9
        elif i in (lm.get("villa_naville_1582", -1), lm.get("villa_naville_1695", -1)):
            wall_rgb[i] = (220, 212, 156)
            style_code[i] = 0
        elif i in (lm.get("schooren_981", -1), lm.get("schooren_1823", -1)):
            wall_rgb[i] = (218, 220, 222)
            style_code[i] = 0
        elif i == lm.get("bendlikon_pavilion", -1):
            wall_rgb[i] = (140, 174, 156)
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
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """V6.0 Museum-Grade 90s Pixel-Art Ground Shader:
    - Organic wildflower Swiss alpine meadows & lush manicured residential garden lawns (ZERO fake mowing stripes,
      ZERO dirty grey concrete soup in shaded yards!)
    - Exact vector FIFA regulation football pitches (alternating mown turf + crisp white markings)
    - Exact vector ITF Roland-Garros clay tennis courts (crisp clay apron + regulation white court lines)
    - Exact vector multi-sport school courts, terraced vineyards, stone-banked Swiss streams, road-aligned parking,
      crisp limestone-coped swimming pools, clean asphalt streets & SBB railway tracks."""
    n_pts = len(ge)
    gcol = np.empty((n_pts, 3), dtype=np.float32)
    gmat = np.full(n_pts, M_GROUND, dtype=np.uint8)
    ro = raw_ortho.astype(np.float32)
    lum = 0.299 * ro[:, 0] + 0.587 * ro[:, 1] + 0.114 * ro[:, 2]

    # Deterministic pixel-art micro-pattern coordinates (0.25m & 0.5m)
    ix25 = np.floor((ge - E_MIN) * 4.0).astype(np.int32)
    iy25 = np.floor((gn - N_MIN) * 4.0).astype(np.int32)
    ix50 = ix25 >> 1
    iy50 = iy25 >> 1
    p_hash = ((ix25 * 73856093) ^ (iy25 * 19349663)) & 0xFF
    h50 = ((ix50 * 83492791) ^ (iy50 * 40503)) & 0xFF
    wf_hash = ((ix25 * 19349663) ^ (iy25 * 83492791) ^ 0x5A3C) & 0x3FF

    c05 = np.clip(((ge - E_MIN) * 2.0).astype(np.int32), 0, GRID_W - 1)
    r05 = np.clip(((N_MAX - gn) * 2.0).astype(np.int32), 0, GRID_H - 1)
    m_noise = scene.meadow_noise_05m[r05, c05].astype(np.float32)
    is_pave = scene.yard_pave_mask_05m[r05, c05]
    is_pool_rim = scene.pool_rim_05m[r05, c05]

    # 1. Organic Swiss Alpine Meadows, Residential Garden Lawns & Clean Limestone Courtyards:
    # Multi-tone rolling organic pasture variation (NO artificial parallel mowing stripes!)
    # Warm sunlit clover patches, rich mid emerald meadow, and cool valley sage grass
    t_meadow = np.clip(0.5 + 0.34 * m_noise, 0.0, 1.0)[:, None]
    lawn_col = (1.0 - t_meadow) * np.array([62.0, 118.0, 48.0], dtype=np.float32) + t_meadow * np.array([92.0, 148.0, 62.0], dtype=np.float32)
    # Subtle warm upland sage tint on sunlit hillside pastures
    warm_patch = m_noise > 0.72
    if warm_patch.any():
        lawn_col[warm_patch] += np.array([10.0, 8.0, -4.0], dtype=np.float32)
    # Crisp 90s pixel-art grass blade tufts (micro-texture without noisy grain)
    tuft = p_hash < 46
    dark_tuft = (p_hash >= 46) & (p_hash < 86)
    lawn_col[tuft] += np.array([11.0, 15.0, 5.0], dtype=np.float32)
    lawn_col[dark_tuft] -= np.array([9.0, 13.0, 5.0], dtype=np.float32)

    # Occasional tiny alpine wildflowers (golden buttercups & white daisies) in open meadows!
    open_meadow = (gsem == G_TERRAIN) & (~is_pave) & (rd_dist > 5.5)
    daisy = open_meadow & (wf_hash == 17)
    buttercup = open_meadow & (wf_hash == 53)
    if daisy.any():
        lawn_col[daisy] = [232.0, 234.0, 224.0]
    if buttercup.any():
        lawn_col[buttercup] = [234.0, 206.0, 82.0]

    # Deep mossy woodland floor under forests (G_FOREST)
    is_for = gsem == G_FOREST
    if is_for.any():
        f_moss = h50[is_for]
        f_c = np.where((f_moss < 90)[:, None], [44.0, 80.0, 40.0], [56.0, 96.0, 48.0]).astype(np.float32)
        f_c[p_hash[is_for] < 36] -= [6.0, 10.0, 4.0]
        lawn_col[is_for] = f_c

    # Manicured park, orchard & cemetery emerald turf with neat warm limestone gravel walkways + Ref. Kirche headstones
    is_park = gsem == G_PARK_CEMETERY
    if is_park.any():
        park_gravel = is_park & (lum > 124.0) & ((ro[:, 1] - ro[:, 2]) < 9.0) & ((ro.max(axis=1) - ro.min(axis=1)) < 20.0)
        lawn_col[is_park] = np.where((p_hash[is_park] < 54)[:, None], [70.0, 134.0, 56.0], [60.0, 120.0, 50.0])
        lawn_col[park_gravel] = np.where((p_hash[park_gravel] < 90)[:, None], [182.0, 172.0, 154.0], [168.0, 158.0, 142.0])

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

    # Clean Jura limestone patios, terraces & paved residential driveways (ONLY true paved areas near buildings/streets!)
    pave_joint = ((ix25 % 5) == 0) | ((iy25 % 5) == 0)
    is_warm_yard = (ro[:, 0] - ro[:, 2]) > 10.0
    yard_col = np.where(is_warm_yard[:, None], [174.0, 164.0, 148.0], [158.0, 156.0, 150.0]).astype(np.float32)
    yard_col[pave_joint] *= 0.91
    yard_col[p_hash < 36] *= 1.04

    is_lawn = (~is_pave) | is_for | is_park
    gcol[:] = np.where(is_lawn[:, None], lawn_col, yard_col)

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
        on_vine = u_row < 0.85
        vine_sh = (u_row >= 0.85) & (u_row < 1.25)
        # Tilled dark-loam furrows + narrow green cover-crop strip between rows
        vcol = np.where((p_hash[vi] < 110)[:, None], [102.0, 82.0, 60.0], [118.0, 96.0, 70.0]).astype(np.float32)
        cover_crop = (u_row >= 1.35) & (u_row <= (pitch_v - 0.30)) & (p_hash[vi] < 145)
        vcol[cover_crop] = [84.0, 114.0, 58.0]
        vcol[vine_sh] *= 0.72
        # 3-tone leafy grapevine trellis rows
        ph_v = p_hash[vi]
        vine_leaf = np.where(
            (ph_v < 78)[:, None],
            [78.0, 138.0, 48.0],
            np.where((ph_v < 180)[:, None], [56.0, 110.0, 42.0], [40.0, 82.0, 34.0]),
        ).astype(np.float32)
        vcol[on_vine] = vine_leaf[on_vine]
        # Wooden trellis end-posts every 11m
        on_post = ((v_along % 11.0) < 0.35) & (u_row >= 0.22) & (u_row <= 0.62)
        vcol[on_post] = [118.0, 86.0, 56.0]
        # Jura dry-stone terrace retaining walls on sloped vineyard contours
        on_terrace = ((gnz[vi] < 0.975) & ((gz[vi] % 2.8) < 0.38)) | (is_gm_v & (np.abs(vn_v - 1242258.0) < 0.65))
        if on_terrace.any():
            vcol[on_terrace] = np.where((ph_v[on_terrace] < 95)[:, None], [142.0, 134.0, 120.0], [170.0, 162.0, 146.0])
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
            # Playing field inset cleanly inside MVT polygon (apron ~2.0m)
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
                # Center service line
                | ((ava <= lw * 0.85) & (aua <= u_srv))
                # Center baseline hash marks
                | ((ava <= lw * 0.8) & (aua >= hl_c - 0.65) & (aua <= hl_c))
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

    # 5. Footpaths & Garden Walkways (G_FOOTPATH): crisp warm Jura limestone gravel
    is_fp = gsem == G_FOOTPATH
    if is_fp.any():
        fi = np.nonzero(is_fp)[0]
        fcol = np.where((p_hash[fi] < 95)[:, None], [174.0, 166.0, 150.0], [158.0, 150.0, 136.0]).astype(np.float32)
        gcol[fi] = fcol

    # 5b. F14c: Hillside Stone Staircases (M1 steps_mask strictly on G_FOOTPATH & ~glake)
    is_st = scene.steps_mask[r05, c05] & (gsem == G_FOOTPATH) & (~glake)
    if is_st.any():
        sti = np.nonzero(is_st)[0]
        ang_s = scene.steps_ang[r05[sti], c05[sti]].astype(np.float32)
        dist_s = scene.steps_dist[r05[sti], c05[sti]].astype(np.float32)
        tread_pitch = 0.64
        phase = (ge[sti] * np.cos(ang_s) + gn[sti] * np.sin(ang_s)) % tread_pitch
        on_tread = phase < (tread_pitch * 0.58)
        on_curb = dist_s >= 0.72
        st_col = np.where(on_tread[:, None], [198.0, 192.0, 180.0], [118.0, 112.0, 104.0]).astype(np.float32)
        st_col[on_curb] = [158.0, 152.0, 142.0]
        st_col[p_hash[sti] < 48] *= 0.95
        gcol[sti] = st_col
        gz[sti[on_tread & (~on_curb)]] += 0.10
        gz[sti[on_curb]] += 0.24

    # 6. Parking Lots (G_PARKING): smooth Swiss slate asphalt + crisp double-row white parking bays & driving aisles!
    is_pk = gsem == G_PARKING
    if is_pk.any():
        ki = np.nonzero(is_pk)[0]
        kcol = np.where((p_hash[ki] < 55)[:, None], [86.0, 90.0, 97.0], [80.0, 84.0, 91.0]).astype(np.float32)
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
        kcol[stall_div | head_line] = [212.0, 214.0, 218.0]
        kcol[end_tick & ((ku % 2.65) < 0.55)] = [194.0, 196.0, 200.0]
        # Subtle worn tire sheen along the center of open driving aisles
        aisle_mid = (kv_m >= 11.4) & (kv_m <= 13.8)
        kcol[aisle_mid] *= 0.94
        gcol[ki] = kcol

    # 7. Minor Village Streets (G_STREET_MINOR): clean 90s pixel-art slate asphalt + crisp 1px granite curb!
    is_min = gsem == G_STREET_MINOR
    if is_min.any():
        mi = np.nonzero(is_min)[0]
        m_d = rd_dist[mi]
        m_hw = np.maximum(2.0, rd_hw[mi])
        mcol = np.where((p_hash[mi] < 65)[:, None], [94.0, 98.0, 106.0], [86.0, 90.0, 98.0]).astype(np.float32)
        curb_m = m_d >= (m_hw - 0.42)
        mcol[curb_m] = [158.0, 156.0, 150.0]
        gutter_m = (m_d >= (m_hw - 0.72)) & (~curb_m)
        mcol[gutter_m] = [68.0, 72.0, 80.0]
        gcol[mi] = mcol

    # 8. Main Roads (G_STREET_MAIN — Seestrasse, Dorfstrasse, Bahnhofstrasse, Alte Landstrasse):
    is_main = gsem == G_STREET_MAIN
    if is_main.any():
        ai = np.nonzero(is_main)[0]
        a_d = rd_dist[ai]
        a_s = rd_along[ai]
        a_hw = np.maximum(3.8, rd_hw[ai])
        sw_start = a_hw - 1.32

        acol = np.where((p_hash[ai] < 62)[:, None], [88.0, 92.0, 100.0], [80.0, 84.0, 92.0]).astype(np.float32)
        lane_mid = np.abs(a_d - 1.55) < 0.55
        acol[lane_mid] *= 0.94

        dash_c = (a_d < 0.26) & ((a_s % 5.6) < 2.5)
        acol[dash_c] = [230.0, 232.0, 236.0]

        on_curb = (a_d >= (sw_start - 0.30)) & (a_d < sw_start)
        on_sw = a_d >= sw_start
        acol[on_curb] = [60.0, 64.0, 72.0]
        sw_joint = on_sw & ((a_s % 1.6) < 0.22)
        acol[on_sw] = [170.0, 166.0, 158.0]
        acol[sw_joint] = [142.0, 138.0, 132.0]
        gz[ai[on_sw]] += 0.18
        gcol[ai] = acol

    # 8b. Crisp Geometric Swiss Yellow Zebra Crosswalks on Main Roads!
    is_xw = xwalk & (gsem == G_STREET_MAIN)
    if is_xw.any():
        xi = np.nonzero(is_xw)[0]
        bar = ((rd_dist[xi] % 0.95) < 0.48) & (rd_dist[xi] <= np.maximum(2.0, rd_hw[xi] - 1.45))
        gcol[xi[bar]] = [238.0, 198.0, 58.0]

    # 9. A3 Motorway (G_MOTORWAY): dark highway asphalt, double dashed lane lines, white shoulders & steel barriers
    is_mw = gsem == G_MOTORWAY
    if is_mw.any():
        wi = np.nonzero(is_mw)[0]
        w_d = rd_dist[wi]
        w_s = rd_along[wi]
        w_hw = np.maximum(3.4, rd_hw[wi])
        wcol = np.where((p_hash[wi] < 55)[:, None], [74.0, 78.0, 86.0], [68.0, 72.0, 80.0]).astype(np.float32)
        w_dash = (np.abs(w_d - 1.8) < 0.24) & ((w_s % 6.5) < 2.8)
        w_edge = np.abs(w_d - (w_hw - 0.85)) < 0.25
        w_guard = w_d >= (w_hw - 0.42)
        wcol[w_dash | w_edge] = [232.0, 234.0, 238.0]
        wcol[w_guard] = [158.0, 164.0, 172.0]
        gz[wi[w_guard]] += 0.72
        gcol[wi] = wcol

    # 10. SBB Seebahn Railway (G_RAILWAY): crushed granite ballast, perpendicular sleepers & twin steel rails!
    is_rl = gsem == G_RAILWAY
    if is_rl.any():
        ri = np.nonzero(is_rl)[0]
        r_d = rl_dist[ri]
        r_s = rl_along[ri]
        rcol = np.where((p_hash[ri] < 115)[:, None], [116.0, 108.0, 98.0], [96.0, 88.0, 80.0]).astype(np.float32)
        rcol[r_d > 2.05] = [84.0, 78.0, 70.0]
        sleeper = (r_d <= 1.22) & ((r_s % 0.85) < 0.30)
        rcol[sleeper] = [64.0, 52.0, 44.0]
        rail_steel = np.abs(r_d - 0.72) <= 0.22
        rcol[rail_steel] = [200.0, 206.0, 214.0]
        gz[ri[rail_steel]] += 0.14
        gcol[ri] = rcol
        gmat[ri] = M_RAIL

    # 11. SBB Station Platforms & Lakeside Stone Piers (G_PLATFORM_PIER): raised concrete + tactile safety edge!
    is_pl = (gsem == G_PLATFORM_PIER) & (~glake)
    if is_pl.any():
        pli = np.nonzero(is_pl)[0]
        pcol = np.full((len(pli), 3), [178.0, 176.0, 170.0], dtype=np.float32)
        slab = ((ix50[pli] % 3) == 0) | ((iy50[pli] % 3) == 0)
        pcol[slab] = [158.0, 156.0, 150.0]
        tactile = (rl_dist[pli] >= 1.55) & (rl_dist[pli] <= 2.05)
        pcol[tactile] = [236.0, 236.0, 232.0]
        gcol[pli] = pcol
        gz[pli] += 0.58

    # 12. Crisp Swimming Pools (G_POOL) with white Jura-stone coping rim & Seebad swimming lanes!
    if is_pool_rim.any():
        gcol[is_pool_rim] = [220.0, 218.0, 212.0]
        gz[is_pool_rim] += 0.14
    is_pool = gsem == G_POOL
    if is_pool.any():
        p_i = np.nonzero(is_pool)[0]
        shimmer = ((ix25[p_i] + iy25[p_i]) & 3) == 0
        in_seebad = (ge[p_i] >= 2684235.0) & (ge[p_i] <= 2684310.0) & (gn[p_i] >= 1241435.0) & (gn[p_i] <= 1241525.0)
        if preset_key == "night":
            # F7: Darken all 55 private pools to calm nocturnal slate-navy; tasteful turquoise underwater glow at Seebad ONLY!
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

    # 13. F9: Master-Crafted Pixel-Art Lake Zurich (bathymetry + pebble caustics + isometric wavelets + shore/pier foam curls!)
    if glake.any():
        li = np.nonzero(glake)[0]
        is_real_harbor_obj = gharbor[li]

        wi = li[~is_real_harbor_obj]
        if len(wi) > 0:
            depth_m = np.clip(LAKE_SURFACE_Z - gbathy[wi], 0.0, 65.0)
            t_sh = np.clip(depth_m / 6.0, 0.0, 1.0)[:, None]
            t_dp = np.clip((depth_m - 6.0) / 30.0, 0.0, 1.0)[:, None]
            mid_w = np.array([38.0, 96.0, 110.0], dtype=np.float32) if preset_key == "day" else np.array([34.0, 86.0, 100.0], dtype=np.float32)
            deep_w = np.array([32.0, 84.0, 108.0], dtype=np.float32) if preset_key == "day" else np.array([18.0, 52.0, 80.0], dtype=np.float32)
            w_col = (1.0 - t_sh) * np.array([64.0, 126.0, 112.0], dtype=np.float32) + t_sh * (
                (1.0 - t_dp) * mid_w + t_dp * deep_w
            )
            # Clamp shallow ortho redness so zero winter shoreline reed tint ever leaks into shallow water!
            shallow_tint = np.clip((4.5 - depth_m) / 4.5, 0.0, 1.0)[:, None] * 0.14
            ortho_w = np.clip(raw_ortho[wi].astype(np.float32) * 1.12, 24.0, 165.0)
            ortho_w[:, 0] = np.minimum(ortho_w[:, 0], ortho_w[:, 1] * 0.92)
            w_col = (1.0 - shallow_tint) * w_col + shallow_tint * ortho_w

            we_w = ge[wi]
            wn_w = gn[wi]
            # Procedural shallow pebble caustics (0.5m .. 3.0m)
            c_w = np.clip(1.0 - np.abs(depth_m - 1.45) / 1.45, 0.0, 1.0) * (depth_m >= 0.40) * (depth_m <= 3.2)
            if (c_w > 0.15).any():
                c_u = we_w * 0.85 + wn_w * 0.42
                c_v = -we_w * 0.42 + wn_w * 0.85
                caust = np.abs(
                    np.sin(c_u * 1.15 + np.sin(c_v * 0.95) * 0.8) * np.cos(c_v * 1.10 - np.cos(c_u * 0.85) * 0.7)
                )
                on_caust = (c_w > 0.15) & (caust > 0.68)
                peb_dark = (c_w > 0.25) & (p_hash[wi] < 38)
                w_col[on_caust] += c_w[on_caust, None] * np.array([22.0, 34.0, 26.0], dtype=np.float32)
                w_col[peb_dark] -= c_w[peb_dark, None] * np.array([10.0, 14.0, 10.0], dtype=np.float32)

            # Isometric 2:1 pixel-art wavelets aligned horizontally in camera screen space
            u_iso = we_w * 0.2079 + wn_w * 0.9781
            v_iso = -we_w * 0.9781 + wn_w * 0.2079
            row_id = np.floor(v_iso * 0.75).astype(np.int32)
            u_stag = (u_iso + (row_id & 1) * 3.1) * 0.22
            col_id = np.floor(u_stag).astype(np.int32)
            w_hash = ((col_id * 73856093) ^ (row_id * 19349663)) & 0xFF
            v_frac = (v_iso * 0.75) % 1.0
            dash_u = u_stag % 1.0
            in_dash = v_frac < 0.26
            crest = in_dash & (w_hash < 28) & (dash_u >= 0.15) & (dash_u <= 0.72) & (depth_m >= 0.65)
            trough = (v_frac >= 0.26) & (v_frac < 0.46) & (w_hash < 28) & (dash_u >= 0.20) & (dash_u <= 0.68) & (depth_m >= 0.65)
            # Ripple crests mirror a hint of the overcast-blue sky (Fresnel) and troughs sit slightly deeper;
            # both stay close to the lake body colour so open water reads as one calm surface with
            # no detached bright/dark speckle islands.
            crest_sky = (
                np.array([22.0, 34.0, 56.0], dtype=np.float32)
                if preset_key == "night"
                else (np.array([52.0, 96.0, 122.0], dtype=np.float32) if preset_key == "day" else np.array([40.0, 60.0, 82.0], dtype=np.float32))
            )
            w_col[crest] = 0.72 * w_col[crest] + 0.28 * crest_sky
            w_col[trough] *= 0.94

            # Crisp 1-2px organic broken shore & pier foam curls
            r05_w = r05[wi]
            c05_w = c05[wi]
            f1 = scene.foam_ring1_05m[r05_w, c05_w] & (np.sin(u_iso * 0.65 + v_iso * 0.45) > -0.35)
            f2 = scene.foam_ring2_05m[r05_w, c05_w] & (p_hash[wi] < 48) & (np.sin(u_iso * 0.80) > 0.20)
            if f1.any():
                w_col[f1] = 0.45 * w_col[f1] + 0.55 * np.array([218.0, 240.0, 236.0], dtype=np.float32)
            if f2.any():
                w_col[f2] = 0.70 * w_col[f2] + 0.30 * np.array([196.0, 230.0, 226.0], dtype=np.float32)

            gcol[wi] = np.clip(w_col, 0.0, 250.0)
            gmat[wi] = M_WATER_LAKE
            gnx[wi], gny[wi], gnz[wi] = 0.0, 0.0, 1.0

        bi_h = li[is_real_harbor_obj]
        if len(bi_h) > 0:
            real_h = np.clip(sub_chm_val[bi_h], 0.65, 3.6)
            gz[bi_h] = LAKE_SURFACE_Z + real_h
            raw_h = raw_ortho[bi_h].astype(np.float32)
            hlum = 0.299 * raw_h[:, 0] + 0.587 * raw_h[:, 1] + 0.114 * raw_h[:, 2]
            is_wpier = (gsem[bi_h] == G_PLATFORM_PIER) | (hlum < 176.0)
            hcol = condition_90s_albedo(raw_ortho[bi_h], shadow_knee=74.0, vibrancy=1.16)
            # Crisp warm timber pier planks & stone jetties!
            plank = ((ix25[bi_h[is_wpier]] + iy25[bi_h[is_wpier]]) % 3) == 0
            warm_wood = (raw_h[is_wpier, 0] - raw_h[is_wpier, 2]) > 8.0
            pier_base = np.where(warm_wood[:, None], [176.0, 154.0, 124.0], [170.0, 166.0, 158.0]).astype(np.float32)
            pier_base[plank] *= 0.87
            hcol[is_wpier] = 0.72 * pier_base + 0.28 * hcol[is_wpier]
            # Bright sunlit white moored sailboat & motorboat hulls!
            is_boat = ~is_wpier
            if is_boat.any():
                hcol[is_boat] = np.clip(hcol[is_boat] * 1.06 + 8.0, 185.0, 242.0)
            gcol[bi_h] = hcol
            gmat[bi_h] = M_HARBOR_OBJ
            gnx[bi_h], gny[bi_h], gnz[bi_h] = 0.15, -0.15, 0.97

    return gcol, gmat, gz


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
    """Rasterize a crisp vertical 3D rectangular pillar/mast (viaduct pier or SBB catenary mast)."""
    if z_top <= z_bot + 0.1:
        return
    step_z = max(0.22, camera.mpp * 0.52)
    zs = np.arange(z_bot, z_top + 0.05, step_z, dtype=np.float32)
    if len(zs) == 0:
        return
    # Sample 4 perimeter faces of the square column
    offs = [
        (half_w, 0.0, 1.0, 0.0),
        (0.0, half_w, 0.0, 1.0),
        (-half_w, 0.0, -1.0, 0.0),
        (0.0, -half_w, 0.0, -1.0),
        (0.0, 0.0, 0.6, -0.6),
    ]
    for oe, on, nx_v, ny_v in offs:
        px, py, pd = camera.project(np.full_like(zs, e_c + oe), np.full_like(zs, n_c + on), zs)
        ix = np.round(px + shift_x).astype(np.int32)
        iy = np.round(py + shift_y).astype(np.int32)
        vm = (ix >= 0) & (ix < W - 1) & (iy >= 0) & (iy < H - 1)
        if not vm.any():
            continue
        ix, iy, pd = ix[vm], iy[vm], pd[vm]
        for ox in (0, 1):
            tx = ix + ox
            w_m = pd < zbuf[iy, tx]
            if w_m.any():
                wy, wx = iy[w_m], tx[w_m]
                zbuf[wy, wx] = pd[w_m]
                rgb_buf[wy, wx] = col_rgb
                mat_buf[wy, wx] = mat_id
                obj_buf[wy, wx] = obj_id
                norm_buf[wy, wx, 0] = nx_v
                norm_buf[wy, wx, 1] = ny_v
                norm_buf[wy, wx, 2] = 0.25
                shadow_buf[wy, wx] = False


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

        # Sub-sample to 0.25m for silky-smooth curves along the Dorfstrasse horseshoe viaduct!
        if camera.mpp <= 0.36:
            br = np.tile(br05, 4)
            bc = np.tile(bc05, 4)
            be = np.concatenate([be05 - 0.125, be05 + 0.125, be05 - 0.125, be05 + 0.125])
            bn = np.concatenate([bn05 + 0.125, bn05 + 0.125, bn05 - 0.125, bn05 - 0.125])
        else:
            br, bc, be, bn = br05, bc05, be05, bn05

        bz = sub_bz[br, bc].copy()
        bcls = sub_bcls[br, bc]
        bsdist = sub_bsdist[br, bc]
        balong = sub_balong[br, bc]
        bhw = sub_bhw[br, bc]
        bang = sub_bang[br, bc]
        bid = sub_bid[br, bc].astype(np.int32)
        bsh = sub_shadow[br, bc]

        abs_sd = np.abs(bsdist)
        ix25 = np.floor((be - E_MIN) * 4.0).astype(np.int32)
        iy25 = np.floor((bn - N_MIN) * 4.0).astype(np.int32)
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

        # Vertical Concrete Box-Girder Side Fascia along outer bridge edges (leaving open air beneath!)
        er_b, ec_b = np.nonzero(bmask & (np.abs(sub_bsdist) >= (sub_bhw - 0.65)))
        if len(er_b) > 0:
            fe_b = E_MIN + (ec_b + c0 + 0.5) * GRID_RES
            fn_b = N_MAX - (er_b + r0 + 0.5) * GRID_RES
            fz_top = sub_bz[er_b, ec_b] + 0.92
            girder_d = np.where(sub_bcls[er_b, ec_b] == BR_STEPS, 0.95, 1.45)
            fz_bot = np.maximum(sub_dem[er_b, ec_b], sub_bz[er_b, ec_b] - girder_d)
            f_bid = sub_bid[er_b, ec_b].astype(np.int32)
            # Outward normal from centerline tangent + sign of bsdist
            sgn_sd = np.where(sub_bsdist[er_b, ec_b] >= 0.0, 1.0, -1.0)
            f_ang = sub_bang[er_b, ec_b]
            fnx_b = (np.sin(f_ang) * sgn_sd).astype(np.float32)
            fny_b = (-np.cos(f_ang) * sgn_sd).astype(np.float32)
            f_is_rail_br = sub_bcls[er_b, ec_b] == BR_RAIL_BRIDGE

            dz_g = max(0.22, camera.mpp * 0.50)
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
                # Top railing band vs main concrete girder fascia vs dark shadow bevel at soffit
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
            zs = np.arange(cz, cz + 6.4, max(0.28, camera.mpp * 0.55), dtype=np.float32)
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
        ts = np.linspace(-shw, shw, int(round(shw * 2 / max(0.25, camera.mpp * 0.6))) + 1)
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
    wire_step = max(0.18, camera.mpp * 0.65)
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
                    (es_w >= crop_box_lv95[0] + 1.5)
                    & (es_w <= crop_box_lv95[2] - 1.5)
                    & (ns_w >= crop_box_lv95[1] + 1.5)
                    & (ns_w <= crop_box_lv95[3] - 1.5)
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
                    crop_box_lv95[0] + 1.5 <= ed <= crop_box_lv95[2] - 1.5
                    and crop_box_lv95[1] + 1.5 <= nd <= crop_box_lv95[3] - 1.5
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
        def _pt_ok_bhf(ep: float, np_: float) -> bool:
            if crop_box_lv95 is not None:
                if not (crop_box_lv95[0] + 1.5 <= ep <= crop_box_lv95[2] - 1.5 and crop_box_lv95[1] + 1.5 <= np_ <= crop_box_lv95[3] - 1.5):
                    return False
            rr_b = int(np.clip((N_MAX - np_) / GRID_RES, 0, GRID_H - 1))
            cc_b = int(np.clip((ep - E_MIN) / GRID_RES, 0, GRID_W - 1))
            return bool(amask[rr_b, cc_b])

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
        # Canopy roof deck (translucent cyan-blue glass panels + galvanized steel ribs)
        nu_c = int(round(elen / 0.22)) + 1
        nv_c = int(round((2.0 * hw_s) / 0.22)) + 1
        us_c = np.linspace(0.0, elen, nu_c, dtype=np.float32)
        vs_c = np.linspace(-hw_s, hw_s, nv_c, dtype=np.float32)
        uu_c, vv_c = np.meshgrid(us_c, vs_c, indexing="ij")
        uf_c, vf_c = uu_c.ravel(), vv_c.ravel()
        ce_d = ee0 + uf_c * eux + vf_c * enx
        cn_d = en0 + uf_c * euy + vf_c * eny
        cz_d = np.full_like(ce_d, 427.88)
        cc_d = np.floor((ce_d - E_MIN) / GRID_RES).astype(np.int32)
        rr_d = np.floor((N_MAX - cn_d) / GRID_RES).astype(np.int32)
        ok_d = (cc_d >= 0) & (cc_d < GRID_W) & (rr_d >= 0) & (rr_d < GRID_H)
        if crop_box_lv95 is not None:
            ok_d &= (ce_d >= crop_box_lv95[0] + 1.0) & (ce_d <= crop_box_lv95[2] - 1.0) & (cn_d >= crop_box_lv95[1] + 1.0) & (cn_d <= crop_box_lv95[3] - 1.0)
        if ok_d.any():
            ok_d[ok_d] &= amask[rr_d[ok_d], cc_d[ok_d]] & (~scene.bldg_roof_mask[rr_d[ok_d], cc_d[ok_d]])
        if ok_d.any():
            px, py, pd = camera.project(ce_d[ok_d], cn_d[ok_d], cz_d[ok_d])
            ix = np.round(px + shift_x).astype(np.int32)
            iy = np.round(py + shift_y).astype(np.int32)
            vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
            if vm.any():
                ix, iy, pd = ix[vm], iy[vm], pd[vm]
                uf_v, vf_v = uf_c[ok_d][vm], vf_c[ok_d][vm]
                is_rib = (np.abs(vf_v) >= (hw_s - 0.22)) | ((uf_v % 4.1) < 0.28)
                c_deck = np.where(
                    is_rib[:, None],
                    [172.0, 178.0, 186.0],
                    [74.0, 128.0, 168.0] if is_night else [108.0, 184.0, 212.0],
                ).astype(np.float32)
                win = pd < zbuf[iy, ix]
                if win.any():
                    zbuf[iy[win], ix[win]] = pd[win]
                    rgb_buf[iy[win], ix[win]] = c_deck[win]
                    mat_buf[iy[win], ix[win]] = M_BRIDGE
                    obj_buf[iy[win], ix[win]] = 312001
                    norm_buf[iy[win], ix[win]] = [0.0, 0.0, 1.0]
                    shadow_buf[iy[win], ix[win]] = False

        # 4c. 3 Backlit Blue-and-White SBB Platform Signs (KILCHBERG) on camera-facing east fascias
        #     (1 on North East glass shelter east fascia + 2 on West canopy idx=17 east fascia, 100% unoccluded!)
        sign_mat = M_WINDOW_LIT if is_night else M_BRIDGE
        sign_spots = (
            (2683850.25, 1242140.1, 427.62),  # North East glass shelter camera-facing east fascia
            (2683853.45, 1242082.5, 428.50),  # West canopy south east-facing fascia
            (2683842.85, 1242127.0, 428.50),  # West canopy north east-facing fascia
        )
        for se_s, sn_s, sz_s in sign_spots:
            if not _pt_ok_bhf(se_s, sn_s):
                continue
            for dz_s, sc_s in (
                (-0.22, [22.0, 64.0, 148.0]),
                (0.00,  [244.0, 246.0, 248.0]),
                (0.22,  [22.0, 64.0, 148.0]),
            ):
                ts_s = np.linspace(-1.40, 1.40, 15)
                px, py, pd = camera.project(se_s + ts_s * eux, sn_s + ts_s * euy, np.full_like(ts_s, sz_s + dz_s))
                ix = np.round(px + shift_x).astype(np.int32)
                iy = np.round(py + shift_y).astype(np.int32)
                vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
                if vm.any():
                    ix, iy, pd = ix[vm], iy[vm], pd[vm] - 0.35
                    win = pd < zbuf[iy, ix]
                    if win.any():
                        zbuf[iy[win], ix[win]] = pd[win]
                        rgb_buf[iy[win], ix[win]] = sc_s
                        mat_buf[iy[win], ix[win]] = sign_mat
                        obj_buf[iy[win], ix[win]] = 312002
                        norm_buf[iy[win], ix[win]] = [0.3, -0.3, 0.9]
                        shadow_buf[iy[win], ix[win]] = False

        # 4d. Iconic White Round Swiss SBB Railway Station Clock with bright red second-hand paddle dot!
        #     Placed on unobstructed open South East platform apron (clear of idx=670, overpass & trees)
        ck_e, ck_n, ck_z = 2683861.2, 1242085.2, 427.65
        if _pt_ok_bhf(ck_e, ck_n):
            rr_ck = int(np.clip((N_MAX - ck_n) / GRID_RES, 0, GRID_H - 1))
            cc_ck = int(np.clip((ck_e - E_MIN) / GRID_RES, 0, GRID_W - 1))
            z_pl_ck = float(scene.dem[rr_ck, cc_ck]) + 0.55
            _draw_3d_box_column(
                camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                ck_e, ck_n, z_pl_ck, ck_z - 0.55, 0.09, (94.0, 100.0, 108.0), 312003, M_BRIDGE,
            )
            px_ck, py_ck, pd_ck = camera.project(np.array([ck_e + 0.18]), np.array([ck_n]), np.array([ck_z]))
            cx_k = int(round(float(px_ck[0] + shift_x)))
            cy_k = int(round(float(py_ck[0] + shift_y)))
            d_k = float(pd_ck[0]) - 0.40
            r_k = max(3, int(round(0.68 / camera.mpp)))
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
                    obj_buf[ty_k, tx_k] = 312003
                    norm_buf[ty_k, tx_k] = [0.25, -0.25, 0.93]
                    shadow_buf[ty_k, tx_k] = False


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
    step_l = max(0.18, mpp * 0.65)
    step_z = max(0.18, mpp * 0.60)
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

            if L_f >= 92.0:
                lamp_mat = M_WINDOW_LIT if is_night else M_BRIDGE
                lamp_col = [255.0, 240.0, 182.0] if is_night else [228.0, 232.0, 236.0]
                for sgn_u in (-0.62, 0.62):
                    for sgn_v in (-1.0, 1.0):
                        em, nm, zm = to_world(sgn_u * hl, sgn_v * (hw + 3.2))
                        _draw_3d_seg(em, nm, zm, em, nm, zm + 14.5, [138.0, 144.0, 152.0], oid=232300 + sf_i, thick=True)
                        el0, nl0, _ = to_world(sgn_u * hl - 1.1, sgn_v * (hw + 3.2))
                        el1, nl1, _ = to_world(sgn_u * hl + 1.1, sgn_v * (hw + 3.2))
                        _draw_3d_seg(el0, nl0, zm + 14.5, el1, nl1, zm + 14.5, lamp_col, mat_c=lamp_mat, oid=232300 + sf_i, thick=True)

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

    # 6. F4: Hoisted 3D Oriented Isometric Pixel-Art Parked Cars (0 floating sky cars, ~21s/preset faster!)
    if scene.parked_cars:
        pk_ang = math.radians(28.5)
        ck, sk = math.cos(pk_ang), math.sin(pk_ang)
        fe_dir, fn_dir = -sk, ck
        se_dir, sn_dir = ck, sk

        def _fill_3d_quad_car(e_c, n_c, hl, hw, z_val, col_rgb, oid, norm=(0.0, 0.0, 1.0)):
            nu = max(3, int(round(2.0 * hl / 0.22)))
            nv = max(2, int(round(2.0 * hw / 0.22)))
            us_q = np.linspace(-hl, hl, nu, dtype=np.float32)
            vs_q = np.linspace(-hw, hw, nv, dtype=np.float32)
            uu, vv = np.meshgrid(us_q, vs_q, indexing="ij")
            uf, vf = uu.ravel(), vv.ravel()
            eq = e_c + uf * fe_dir + vf * se_dir
            nq = n_c + uf * fn_dir + vf * sn_dir
            in_w = _in_active_world(eq, nq)
            if not in_w.any():
                return
            eq, nq = eq[in_w], nq[in_w]
            zq = np.full_like(eq, z_val)
            px, py, dd = camera.project(eq, nq, zq)
            ix = np.round(px + shift_x).astype(np.int32)
            iy = np.round(py + shift_y).astype(np.int32)
            valid = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
            if not valid.any():
                return
            ix, iy, dd = ix[valid], iy[valid], dd[valid]
            win = dd < zbuf[iy, ix]
            if win.any():
                wx, wy, wd = ix[win], iy[win], dd[win]
                zbuf[wy, wx] = wd
                rgb_buf[wy, wx] = col_rgb
                mat_buf[wy, wx] = M_BRIDGE
                obj_buf[wy, wx] = oid
                norm_buf[wy, wx] = norm
                shadow_buf[wy, wx] = False

        car_pal = [
            ([224.0, 226.0, 230.0], [168.0, 172.0, 178.0]),
            ([182.0, 188.0, 196.0], [128.0, 134.0, 144.0]),
            ([68.0, 74.0, 82.0],    [44.0, 48.0, 56.0]),
            ([48.0, 68.0, 108.0],   [32.0, 46.0, 78.0]),
            ([176.0, 46.0, 46.0],   [126.0, 30.0, 32.0]),
            ([166.0, 156.0, 138.0], [118.0, 110.0, 96.0]),
            ([44.0, 88.0, 66.0],    [28.0, 60.0, 44.0]),
        ]

        for car_seq, (pe_k, pn_k, pz_k, col_idx, facing) in enumerate(scene.parked_cars):
            # Strict 4-corner clip against crop_box_lv95 (1.0m inset) & active_mask
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
            if px_k[0] + shift_x < -16 or px_k[0] + shift_x > W + 16 or py_k[0] + shift_y < -16 or py_k[0] + shift_y > H + 16:
                continue

            top_c, side_c = car_pal[col_idx % len(car_pal)]
            oid_c = 235000 + car_seq
            _fill_3d_quad_car(pe_k, pn_k, 2.05, 0.90, pz_k + 0.06, [36.0, 40.0, 46.0], oid_c)
            _fill_3d_quad_car(pe_k, pn_k, 1.98, 0.84, pz_k + 0.36, side_c, oid_c, norm=(0.55, -0.45, 0.70))
            _fill_3d_quad_car(pe_k, pn_k, 1.98, 0.84, pz_k + 0.62, side_c, oid_c, norm=(0.55, -0.45, 0.70))
            _fill_3d_quad_car(pe_k, pn_k, 1.94, 0.82, pz_k + 0.84, top_c, oid_c, norm=(0.0, 0.0, 1.0))
            glass_c = [48.0, 68.0, 92.0]
            _fill_3d_quad_car(pe_k - 0.12 * fe_dir, pn_k - 0.12 * fn_dir, 1.12, 0.72, pz_k + 1.06, glass_c, oid_c, norm=(0.3, -0.3, 0.9))
            _fill_3d_quad_car(pe_k - 0.12 * fe_dir, pn_k - 0.12 * fn_dir, 1.04, 0.70, pz_k + 1.24, glass_c, oid_c, norm=(0.3, -0.3, 0.9))
            roof_hi = [min(244.0, c * 1.06) for c in top_c]
            _fill_3d_quad_car(pe_k - 0.16 * fe_dir, pn_k - 0.16 * fn_dir, 0.82, 0.66, pz_k + 1.38, roof_hi, oid_c, norm=(0.0, 0.0, 1.0))
            _fill_3d_quad_car(pe_k + facing * 1.88 * fe_dir, pn_k + facing * 1.88 * fn_dir, 0.12, 0.68, pz_k + 0.78, [232.0, 236.0, 224.0], oid_c)
            _fill_3d_quad_car(pe_k - facing * 1.88 * fe_dir, pn_k - facing * 1.88 * fn_dir, 0.12, 0.68, pz_k + 0.78, [188.0, 42.0, 42.0], oid_c)

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
                col_body=np.array([154.0, 148.0, 136.0], dtype=np.float32),
                col_top=np.array([196.0, 190.0, 178.0], dtype=np.float32),
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
        # Cantilevered roof deck (3 parallel strips)
        for rv in (-0.35, 0.25, 0.85):
            _draw_3d_seg(e_l + rv * vx_z, n_l + rv * vy_z, bz_z + 2.35, e_r + rv * vx_z, n_r + rv * vy_z, bz_z + 2.35, [66.0, 72.0, 80.0], oid=oid_z, thick=True)
        _draw_3d_seg(e_l + 0.85 * vx_z, n_l + 0.85 * vy_z, bz_z + 2.40, e_r + 0.85 * vx_z, n_r + 0.85 * vy_z, bz_z + 2.40, [162.0, 168.0, 174.0], oid=oid_z)
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

    # 9b. 15 Lakeside Promenade Wooden Benches facing ESE toward Lake Zurich
    prom_benches = (
        (2684017.2, 1242062.8), (2684024.8, 1242058.8), (2684040.8, 1242048.2),
        (2684199.2, 1241656.2), (2684221.8, 1241627.8), (2684222.8, 1241589.8),
        (2684286.2, 1241488.2), (2684304.8, 1241471.2), (2684312.2, 1241454.2),
        (2684465.2, 1241192.8), (2684484.8, 1241167.8), (2684494.8, 1241138.8),
        (2683610.2, 1243038.8), (2683613.2, 1242993.2), (2683639.2, 1242982.8),
    )
    b_ux, b_uy = math.cos(math.radians(-65.0)), math.sin(math.radians(-65.0))
    for bi_b, (be_b, bn_b) in enumerate(prom_benches):
        if not _prop_ok(be_b, bn_b, inset=1.5):
            continue
        bz_b = _sample_dem(be_b, bn_b)
        oid_b = 237200 + bi_b
        e0_b, n0_b = be_b - 0.95 * b_ux, bn_b - 0.95 * b_uy
        e1_b, n1_b = be_b + 0.95 * b_ux, bn_b + 0.95 * b_uy
        _draw_3d_seg(e0_b, n0_b, bz_b, e0_b, n0_b, bz_b + 0.48, [44.0, 48.0, 54.0], oid=oid_b)
        _draw_3d_seg(e1_b, n1_b, bz_b, e1_b, n1_b, bz_b + 0.48, [44.0, 48.0, 54.0], oid=oid_b)
        _draw_3d_seg(e0_b, n0_b, bz_b + 0.48, e1_b, n1_b, bz_b + 0.48, [168.0, 118.0, 72.0], oid=oid_b, thick=True)
        _draw_3d_seg(e0_b - 0.25 * b_uy, n0_b + 0.25 * b_ux, bz_b + 0.88, e1_b - 0.25 * b_uy, n1_b + 0.25 * b_ux, bz_b + 0.88, [150.0, 102.0, 62.0], oid=oid_b)

    # 9c. Upper Meadow Swiss Wooden Pasture Fences & Golden Round Hay Bales (02_kirche & 06_sanatorium)
    pasture_fences = (
        (2683512.0, 1241180.0, 2683584.0, 1241215.0),
        (2683512.0, 1241180.0, 2683508.0, 1241248.0),
        (2683372.0, 1242395.0, 2683432.0, 1242388.0),
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
        # Stacked pixel-art round hay bale (shadow base + warm straw body + sunlit spiral top)
        for z_off, rad_b, c_b in (
            (0.05, 0.78, [42.0, 62.0, 34.0]),
            (0.32, 0.70, [168.0, 134.0, 68.0]),
            (0.68, 0.70, [208.0, 174.0, 96.0]),
            (1.02, 0.66, [208.0, 174.0, 96.0]),
            (1.24, 0.58, [232.0, 204.0, 124.0]),
        ):
            ang_h = np.linspace(0.0, 2.0 * math.pi, 10, endpoint=False)
            es_h = np.concatenate([[he_b], he_b + rad_b * np.cos(ang_h)])
            ns_h = np.concatenate([[hn_b], hn_b + rad_b * np.sin(ang_h)])
            zs_h = np.full_like(es_h, hz_b + z_off)
            px, py, pd = camera.project(es_h, ns_h, zs_h)
            ix = np.round(px + shift_x).astype(np.int32)
            iy = np.round(py + shift_y).astype(np.int32)
            vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
            if vm.any():
                ix, iy, pd = ix[vm], iy[vm], pd[vm]
                win = pd < zbuf[iy, ix]
                if win.any():
                    zbuf[iy[win], ix[win]] = pd[win]
                    rgb_buf[iy[win], ix[win]] = c_b
                    mat_buf[iy[win], ix[win]] = M_BRIDGE
                    obj_buf[iy[win], ix[win]] = oid_h
                    norm_buf[iy[win], ix[win]] = [0.25, -0.25, 0.93]
                    shadow_buf[iy[win], ix[win]] = False


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
    step_l = max(0.18, mpp * 0.65)

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
    # Part A: 3D Timber Pier Pilings, Water Contact Shadows & Handcrafted Pier Accents
    # -------------------------------------------------------------------------
    sub_lake = scene.lake_mask[r0:r1, c0:c1]
    sub_pier = sub_mask & scene.pier_only_mask_05m[r0:r1, c0:c1] & sub_lake
    if sub_pier.any():
        # Crisp water contact shadow directly around every timber pier / jetty edge
        pier_halo = ndimage.binary_dilation(sub_pier, iterations=2) & (~sub_pier) & sub_lake
        if pier_halo.any():
            hr, hc = np.nonzero(pier_halo)
            he = E_MIN + (hc + c0 + 0.5) * GRID_RES
            hn = N_MAX - (hr + r0 + 0.5) * GRID_RES
            px, py, _ = camera.project(he, hn, np.full_like(he, LAKE_SURFACE_Z + 0.02))
            ix = np.round(px + shift_x).astype(np.int32)
            iy = np.round(py + shift_y).astype(np.int32)
            vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
            if vm.any():
                ix, iy = ix[vm], iy[vm]
                is_w = mat_buf[iy, ix] == M_WATER_LAKE
                if is_w.any():
                    rgb_buf[iy[is_w], ix[is_w]] *= 0.78

        # 3D Timber Pilings & Mooring Bollards spaced every 3.0m along pier edges
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
                if crop_box_lv95 is not None and not (
                    crop_box_lv95[0] + 1.5 <= ep <= crop_box_lv95[2] - 1.5
                    and crop_box_lv95[1] + 1.5 <= np_ <= crop_box_lv95[3] - 1.5
                ):
                    continue
                z_deck = LAKE_SURFACE_Z + float(np.clip(scene.chm[rr_p, cc_p], 0.70, 1.45))
                _draw_3d_box_column(
                    camera, shift_x, shift_y, W, H, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                    ep, np_, LAKE_SURFACE_Z - 0.15, z_deck + 0.35, 0.16, (88.0, 70.0, 52.0), 255000, M_HARBOR_OBJ,
                )

    # Bendlikon ZSG Steamer Pier (Badweg 1.1) handcrafted fenders, railings & corner lantern!
    def _in_box_am(ep: float, np_: float, ins: float = 1.5) -> bool:
        if crop_box_lv95 is not None and not (
            crop_box_lv95[0] + ins <= ep <= crop_box_lv95[2] - ins
            and crop_box_lv95[1] + ins <= np_ <= crop_box_lv95[3] - ins
        ):
            return False
        rr_t = int(np.clip((N_MAX - np_) / GRID_RES, 0, GRID_H - 1))
        cc_t = int(np.clip((ep - E_MIN) / GRID_RES, 0, GRID_W - 1))
        return bool(amask[rr_t, cc_t])

    if _in_box_am(2684061.0, 1242076.0, ins=0.5):
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
        # Galvanized safety railings along both approach edges
        for rn_r in (1242065.5, 1242074.8):
            _draw_harbor_seg(2684038.5, rn_r, 408.55, 2684055.0, rn_r, 408.55, [178.0, 184.0, 190.0], oid=255201)
            for re_p in np.linspace(2684039.0, 2684054.5, 6):
                _draw_harbor_seg(float(re_p), rn_r, 407.60, float(re_p), rn_r, 408.55, [142.0, 148.0, 156.0], oid=255201)
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

    # Seebad Kilchberg 3 Wooden Jetties: stainless swim ladders + south diving board!
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
        if ji_s == 2:
            # Tiny classic diving board plank on south swim jetty!
            _draw_harbor_seg(je_t - 0.6, jn_t - 1.2, jz_t + 0.55, je_t + 1.6, jn_t - 1.2, jz_t + 0.62, [226.0, 222.0, 212.0], oid=oid_j, thick=True)

    # -------------------------------------------------------------------------
    # Part B: 3D Isometric Moored Boats (40 clean open-water sailboats & Boesch motorboats!)
    # -------------------------------------------------------------------------
    b_step = max(0.18, mpp * 0.72)
    for idx_b, boat in enumerate(scene.boats):
        be = float(boat["e"])
        bn = float(boat["n"])
        if crop_box_lv95 is not None and not (
            crop_box_lv95[0] + 4.0 <= be <= crop_box_lv95[2] - 4.0
            and crop_box_lv95[1] + 4.0 <= bn <= crop_box_lv95[3] - 4.0
        ):
            continue
        rb = int(math.floor((N_MAX - bn) / GRID_RES))
        cb = int(math.floor((be - E_MIN) / GRID_RES))
        if not (0 <= rb < GRID_H and 0 <= cb < GRID_W):
            continue
        # Strictly exclude any false-positive boat overlapping roofs, piers, land, or outside active_mask!
        if (
            not scene.lake_mask[rb, cb]
            or not amask[rb, cb]
            or scene.bldg_roof_mask[rb, cb]
            or scene.pier_only_mask_05m[rb, cb]
        ):
            continue
        px_c, py_c, _ = camera.project(np.array([be]), np.array([bn]), np.array([LAKE_SURFACE_Z]))
        if px_c[0] + shift_x < -36 or px_c[0] + shift_x > W + 36 or py_c[0] + shift_y < -48 or py_c[0] + shift_y > H + 36:
            continue

        L_b = float(np.clip(boat["length"], 3.8, 10.8))
        half_l = 0.5 * L_b
        half_w = float(np.clip(L_b * 0.175, 0.80, 1.55))
        ang_b = math.radians(float(boat["angle"]))
        ue, un = math.cos(ang_b), math.sin(ang_b)
        ve, vn = -un, ue
        is_sail = bool(boat["sail"])
        oid_b = 260000 + idx_b

        # Tapered hull local (s, t) grid
        ns_b = max(5, int(round(L_b / b_step)) + 1)
        nt_b = max(4, int(round(2.0 * half_w / b_step)) + 1)
        ss = np.linspace(-half_l, half_l, ns_b, dtype=np.float32)
        tt = np.linspace(-half_w, half_w, nt_b, dtype=np.float32)
        sg, tg = np.meshgrid(ss, tt, indexing="ij")
        sf_b, tf_b = sg.ravel(), tg.ravel()
        w_s = np.where(
            sf_b > (0.25 * half_l),
            half_w * np.sqrt(np.clip(1.0 - ((sf_b - 0.25 * half_l) / max(0.1, 0.75 * half_l)) ** 2, 0.0, 1.0)),
            np.where(
                sf_b < (-0.55 * half_l),
                half_w * (0.78 + 0.22 * (sf_b + half_l) / max(0.1, 0.45 * half_l)),
                half_w,
            ),
        )
        in_hull = np.abs(tf_b) <= np.maximum(0.14, w_s)
        if not in_hull.any():
            continue
        sf_h, tf_h, ws_h = sf_b[in_hull], tf_b[in_hull], w_s[in_hull]
        eh = be + sf_h * ue + tf_h * ve
        nh = bn + sf_h * un + tf_h * vn
        sheer = np.clip((sf_h - 0.15 * half_l) / max(0.5, 0.85 * half_l), 0.0, 1.0) * 0.14

        # 1. Grounded dark water contact shadow directly beneath hull
        px_s, py_s, _ = camera.project(eh + 0.35, nh - 0.35, np.full_like(eh, LAKE_SURFACE_Z + 0.01))
        ix_s = np.round(px_s + shift_x).astype(np.int32)
        iy_s = np.round(py_s + shift_y).astype(np.int32)
        vs_b = (ix_s >= 0) & (ix_s < W) & (iy_s >= 0) & (iy_s < H)
        if vs_b.any():
            ix_s, iy_s = ix_s[vs_b], iy_s[vs_b]
            is_w_s = mat_buf[iy_s, ix_s] == M_WATER_LAKE
            if is_w_s.any():
                rgb_buf[iy_s[is_w_s], ix_s[is_w_s]] *= 0.74

        # 2. Hull freeboard layers (waterline navy boot-stripe + crisp white gelcoat freeboard)
        for zl_off, hull_c in (
            (0.14, np.array([42.0, 62.0, 92.0], dtype=np.float32)),
            (0.42, np.array([228.0, 226.0, 220.0], dtype=np.float32)),
            (0.68, np.array([238.0, 236.0, 230.0], dtype=np.float32)),
        ):
            px, py, pd = camera.project(eh, nh, LAKE_SURFACE_Z + zl_off + sheer)
            ix = np.round(px + shift_x).astype(np.int32)
            iy = np.round(py + shift_y).astype(np.int32)
            vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
            if not vm.any():
                continue
            ix, iy, pd = ix[vm], iy[vm], pd[vm]
            win = pd < zbuf[iy, ix]
            if win.any():
                zbuf[iy[win], ix[win]] = pd[win]
                rgb_buf[iy[win], ix[win]] = hull_c
                mat_buf[iy[win], ix[win]] = M_HARBOR_OBJ
                obj_buf[iy[win], ix[win]] = oid_b
                norm_buf[iy[win], ix[win]] = [0.35, -0.35, 0.86]
                shadow_buf[iy[win], ix[win]] = False

        # 3. Deck, cockpit, cabin / windscreen
        if is_sail:
            deck_c = np.full((len(sf_h), 3), [240.0, 238.0, 232.0], dtype=np.float32)
            z_deck = LAKE_SURFACE_Z + 0.74 + sheer
            in_cockpit = (sf_h >= -0.62 * half_l) & (sf_h <= 0.05 * half_l) & (np.abs(tf_h) <= 0.58 * ws_h)
            in_cabin = (sf_h > 0.05 * half_l) & (sf_h <= 0.42 * half_l) & (np.abs(tf_h) <= 0.56 * ws_h)
            deck_c[in_cockpit] = [148.0, 102.0, 62.0] if (idx_b & 1) else [44.0, 64.0, 92.0]
            deck_c[in_cabin] = [244.0, 242.0, 236.0]
            z_deck[in_cabin] += 0.30
            # Tiny dark cabin porthole pixels
            porthole = in_cabin & (np.abs(tf_h) > 0.38 * ws_h) & (np.abs(sf_h - 0.24 * half_l) < 0.22)
            deck_c[porthole] = [46.0, 62.0, 82.0]
        else:
            # Classic Boesch varnished mahogany vs white Lake Zurich day-cruiser
            z_deck = LAKE_SURFACE_Z + 0.72 + sheer
            if (idx_b % 2) == 0:
                deck_c = np.full((len(sf_h), 3), [146.0, 82.0, 44.0], dtype=np.float32)
                seam = (sf_h > 0.15 * half_l) & (np.abs(tf_h) < 0.14)
                deck_c[seam] = [228.0, 216.0, 194.0]
            else:
                deck_c = np.full((len(sf_h), 3), [236.0, 234.0, 228.0], dtype=np.float32)
                stripe_c = [46.0, 74.0, 118.0] if ((idx_b >> 1) & 1) == 0 else [154.0, 48.0, 52.0]
                sheer_edge = np.abs(tf_h) > (0.78 * ws_h)
                deck_c[sheer_edge] = stripe_c
            in_cockpit = (sf_h >= -0.68 * half_l) & (sf_h <= 0.12 * half_l) & (np.abs(tf_h) <= 0.65 * ws_h)
            deck_c[in_cockpit] = [218.0, 208.0, 188.0]
            windscreen = (np.abs(sf_h - 0.16 * half_l) <= 0.22) & (np.abs(tf_h) <= 0.70 * ws_h)
            deck_c[windscreen] = [62.0, 92.0, 120.0]
            z_deck[windscreen] += 0.32

        px, py, pd = camera.project(eh, nh, z_deck)
        ix = np.round(px + shift_x).astype(np.int32)
        iy = np.round(py + shift_y).astype(np.int32)
        vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
        if vm.any():
            ix, iy, pd, dc_v = ix[vm], iy[vm], pd[vm], deck_c[vm]
            win = pd < zbuf[iy, ix]
            if win.any():
                zbuf[iy[win], ix[win]] = pd[win]
                rgb_buf[iy[win], ix[win]] = dc_v[win]
                mat_buf[iy[win], ix[win]] = M_HARBOR_OBJ
                obj_buf[iy[win], ix[win]] = oid_b
                norm_buf[iy[win], ix[win]] = [0.0, 0.0, 1.0]
                shadow_buf[iy[win], ix[win]] = False

        # 4. Sailboat 1px aluminum mast + furled boom + subtle water reflection
        if is_sail:
            me = be + 0.10 * half_l * ue
            mn = bn + 0.10 * half_l * un
            mast_h = float(np.clip(L_b * 0.92, 5.2, 8.8))
            _draw_harbor_seg(me, mn, LAKE_SURFACE_Z + 0.90, me, mn, LAKE_SURFACE_Z + 0.90 + mast_h, [186.0, 192.0, 200.0], oid=oid_b)
            boom_c = [48.0, 76.0, 126.0] if (idx_b % 3 == 0) else [232.0, 226.0, 212.0]
            _draw_harbor_seg(me, mn, LAKE_SURFACE_Z + 1.85, me - 0.52 * half_l * ue, mn - 0.52 * half_l * un, LAKE_SURFACE_Z + 1.85, boom_c, oid=oid_b, thick=True)
            # Subtle mast water reflection downward along +Y
            px_m, py_m, _ = camera.project(np.array([me]), np.array([mn]), np.array([LAKE_SURFACE_Z + 0.15]))
            mx0 = int(round(float(px_m[0] + shift_x)))
            my0 = int(round(float(py_m[0] + shift_y)))
            r_len = min(18, int(round((mast_h / mpp) * 0.45)))
            for dy_r in range(2, r_len):
                ry_m = my0 + dy_r
                rx_m = mx0 + int(round(math.sin(ry_m * 0.7)))
                if 0 <= ry_m < H and 0 <= rx_m < W and mat_buf[ry_m, rx_m] == M_WATER_LAKE:
                    rgb_buf[ry_m, rx_m] = 0.78 * rgb_buf[ry_m, rx_m] + 0.22 * np.array([195.0, 202.0, 210.0], dtype=np.float32)

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
    # 4A. Sculpted 3D Beveled Boxwood Hedges & Flowering Garden Bushes
    # -------------------------------------------------------------------------
    sub_hedge = sub_mask & scene.hedge_mask[r0:r1, c0:c1]
    if sub_hedge.any():
        hr, hc = np.nonzero(sub_hedge)
        he = E_MIN + (hc + c0 + 0.5) * GRID_RES
        hn = N_MAX - (hr + r0 + 0.5) * GRID_RES
        hz_base = sub_dem[hr, hc]
        hh = np.clip(sub_chm[hr, hc], 0.95, 2.05)
        h_hash = (((hc + c0) * 73856093) ^ ((hr + r0) * 19349663)) & 0xFF
        h_top_col = np.where(
            (h_hash < 72)[:, None],
            [82.0, 134.0, 56.0],
            np.where((h_hash < 176)[:, None], [58.0, 108.0, 46.0], [42.0, 86.0, 38.0]),
        ).astype(np.float32)
        is_rose = (h_hash == 251)
        is_lav = (h_hash == 253)
        h_top_col[is_rose] = [226.0, 152.0, 166.0]
        h_top_col[is_lav] = [214.0, 198.0, 146.0]
        h_side_col = h_top_col * 0.72
        h_base_col = h_top_col * 0.54
        h_oid = np.full(len(hr), 190000, dtype=np.int32)

        for frac_z, col_arr, nz_v, rad_offs in (
            (0.25, h_base_col, 0.55, ((0, 0), (1, 0), (0, 1), (1, 1))),
            (0.55, h_side_col, 0.70, ((0, 0), (1, 0), (0, 1), (1, 1))),
            (0.84, h_side_col * 1.12, 0.85, ((0, 0), (1, 0), (0, 1))),
            (1.00, h_top_col, 0.98, ((0, 0), (1, 0))),
        ):
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
                norm_buf[ty[win], tx[win], 0] = 0.0 if nz_v > 0.9 else 0.35
                norm_buf[ty[win], tx[win], 1] = 0.0 if nz_v > 0.9 else -0.35
                norm_buf[ty[win], tx[win], 2] = nz_v

    # -------------------------------------------------------------------------
    # 4B. All 16,000+ Individual Hand-Crafted 90s Pixel-Art 3D Trees!
    # -------------------------------------------------------------------------
    te = scene.tree_e
    tn = scene.tree_n
    tz = scene.tree_z
    th = scene.tree_h
    trad = scene.tree_rad
    tsp = scene.tree_species
    tdist_l = scene.tree_dist_lake
    t_ids = np.arange(len(te), dtype=np.int32)

    if crop_box_lv95 is not None:
        e0, n0, e1, n1 = crop_box_lv95
        keep = (te >= e0 + 1.5) & (te <= e1 - 1.5) & (tn >= n0 + 1.5) & (tn <= n1 - 1.5)
        te, tn, tz, th, trad, tsp, tdist_l, t_ids = (
            te[keep], tn[keep], tz[keep], th[keep], trad[keep], tsp[keep], tdist_l[keep], t_ids[keep]
        )

    if len(te) == 0:
        return

    px_base, py_base, pd_base = camera.project(te, tn, tz)
    px_top, py_top, _ = camera.project(te, tn, tz + th)
    r_px_est = (trad * 1.48 / camera.mpp) + 12.0
    in_vp = (
        (px_base + shift_x + r_px_est >= -6.0)
        & (px_base + shift_x - r_px_est <= W + 6.0)
        & (py_base + shift_y + 12.0 >= -6.0)
        & (py_top + shift_y - r_px_est <= H + 6.0)
    )
    if not in_vp.any():
        return

    te, tn, tz, th, trad, tsp, tdist_l, t_ids = (
        te[in_vp], tn[in_vp], tz[in_vp], th[in_vp], trad[in_vp], tsp[in_vp], tdist_l[in_vp], t_ids[in_vp]
    )
    px_base = px_base[in_vp] + shift_x
    py_base = py_base[in_vp] + shift_y
    px_top = px_top[in_vp] + shift_x
    py_top = py_top[in_vp] + shift_y
    pd_base = pd_base[in_vp]

    t_ord = np.argsort(pd_base)[::-1]
    te, tn, tz, th, trad, tsp, tdist_l, t_ids = (
        te[t_ord], tn[t_ord], tz[t_ord], th[t_ord], trad[t_ord], tsp[t_ord], tdist_l[t_ord], t_ids[t_ord]
    )
    px_base, py_base, py_top, pd_base = px_base[t_ord], py_base[t_ord], py_top[t_ord], pd_base[t_ord]

    # 7 Botanical 5-Tone Painterly 90s Pixel-Art Foliage Ramps with cool-teal shaded undersides!
    SPECIES_RAMPS = np.array(
        [
            # 0: Wide-Spreading Swiss Oak / Beech (cool-teal underside -> rich emerald -> sunlit crown)
            [[10.0, 34.0, 30.0], [20.0, 54.0, 40.0], [40.0, 88.0, 42.0], [66.0, 122.0, 50.0], [98.0, 152.0, 62.0]],
            # 1: Airy Linden / Birch / Fruit Orchard (cool-sage underside -> golden-apple sunlit tips)
            [[14.0, 42.0, 32.0], [28.0, 70.0, 44.0], [56.0, 110.0, 44.0], [88.0, 144.0, 56.0], [126.0, 176.0, 70.0]],
            # 2: Alpine Spruce / Silver Fir (cool mountain blue-green needles)
            [[10.0, 28.0, 28.0], [18.0, 46.0, 42.0], [32.0, 72.0, 52.0], [48.0, 96.0, 66.0], [68.0, 122.0, 80.0]],
            # 3: Slender Mediterranean / Cemetery Cypress (deep rich cypress emerald)
            [[10.0, 28.0, 22.0], [18.0, 46.0, 32.0], [28.0, 68.0, 42.0], [44.0, 92.0, 54.0], [64.0, 116.0, 66.0]],
            # 4: Stately Estate Copper Beech (deep aubergine-plum -> warm bronze-burgundy)
            [[32.0, 16.0, 26.0], [54.0, 26.0, 34.0], [82.0, 38.0, 42.0], [112.0, 54.0, 54.0], [142.0, 74.0, 68.0]],
            # 5: Spring Cherry / Apple Blossom Tree (dusty rose -> sunlit creamy-white petals)
            [[114.0, 66.0, 82.0], [164.0, 106.0, 120.0], [206.0, 150.0, 164.0], [234.0, 196.0, 206.0], [250.0, 232.0, 236.0]],
            # 6: Weeping Lakeside Willow (silvery-sage cascading Zürichsee willow)
            [[14.0, 42.0, 34.0], [28.0, 68.0, 46.0], [52.0, 106.0, 62.0], [86.0, 144.0, 80.0], [128.0, 178.0, 102.0]],
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

    for i in range(len(te)):
        sp_k = min(5, int(tsp[i]))
        tid = int(t_ids[i])
        oid = 100000 + tid
        te_i = float(te[i])
        tn_i = float(tn[i])
        h_m = float(th[i])
        r_m = float(trad[i])
        cx0 = float(px_base[i])
        cy0 = float(py_base[i])
        d0 = float(pd_base[i])

        # F14c: Reclassify ~10 deterministic existing Reformierte Kirche Cemetery trees to slender dark cypresses!
        if (
            sp_k == 0
            and 2683375.0 <= te_i <= 2683500.0
            and 1241053.0 <= tn_i <= 1241314.0
            and (tid % 11) == 0
        ):
            sp_k = 3

        is_willow = (sp_k in (0, 1)) and (float(tdist_l[i]) < 25.0) and ((tid % 5) < 2)
        is_oak = (not is_willow) and (sp_k == 0 or (sp_k == 1 and r_m >= 3.2 and (tid & 1) == 0))

        # Deterministic per-tree variation seeds
        s0 = ((tid * 73856093) ^ 0x5A5A) & 0xFFFF
        s1 = ((tid * 19349663) ^ 0xA53C) & 0xFFFF
        s2 = ((tid * 83492791) ^ 0x3C71) & 0xFFFF
        w_var = 0.88 + 0.24 * ((s0 & 255) / 255.0)
        h_var = 0.90 + 0.20 * (((s0 >> 8) & 255) / 255.0)

        if is_willow:
            r_px = max(4.0, (r_m * 1.32 * w_var) / mpp)
            h_px = max(8.0, min(h_m * z_px_per_m * h_var, r_px * 2.45))
            crown_ry = max(3.8, min(h_px * 0.56, r_px * 0.98))
            trunk_h_px = max(1.6, h_px * 0.16)
        elif sp_k in (0, 1, 4, 5):
            if is_oak:
                r_px = max(3.8, (r_m * 1.30 * w_var) / mpp)
                h_px = max(7.0, min(h_m * z_px_per_m * h_var, r_px * 2.45))
                crown_ry = max(3.2, min(h_px * 0.42, r_px * 0.80))
                trunk_h_px = max(2.4, h_px - crown_ry * 1.88)
            else:
                r_px = max(3.4, (r_m * 1.15 * w_var) / mpp)
                h_px = max(7.5, min(h_m * z_px_per_m * h_var, r_px * 2.75))
                crown_ry = max(3.8, min(h_px * 0.52, r_px * 1.04))
                trunk_h_px = max(2.8, h_px - crown_ry * 1.75)
        else:
            r_px = max(3.0, (r_m * 1.06 * w_var) / mpp)
            h_px = max(8.5, min(h_m * z_px_per_m * h_var, r_px * 3.9))
            trunk_h_px = max(1.8, h_px * 0.14)
            crown_ry = max(3.4, 0.5 * (h_px - trunk_h_px))

        # 0. Soft Grounded Canopy Contact Shadow directly on ground beneath tree!
        sh_rx = int(math.ceil(r_px * 0.88))
        sh_ry = max(2, int(math.ceil(r_px * 0.40)))
        sx0 = max(0, int(round(cx0 - sh_rx * 0.75)))
        sx1 = min(W - 1, int(round(cx0 + sh_rx * 1.10)))
        sy0 = max(0, int(round(cy0 - sh_ry * 0.65)))
        sy1 = min(H - 1, int(round(cy0 + sh_ry * 0.85)))
        if sx1 >= sx0 and sy1 >= sy0:
            sxs = np.arange(sx0, sx1 + 1, dtype=np.float32)
            sys = np.arange(sy0, sy1 + 1, dtype=np.float32)
            sgx, sgy = np.meshgrid(sxs, sys)
            sr2 = ((sgx - (cx0 + r_px * 0.16)) / max(1.5, sh_rx)) ** 2 + ((sgy - (cy0 + 0.5)) / max(1.2, sh_ry)) ** 2
            in_sh = (sr2 <= 1.0) & (mat_buf[sy0 : sy1 + 1, sx0 : sx1 + 1] == M_GROUND) & (zbuf[sy0 : sy1 + 1, sx0 : sx1 + 1] > (d0 - 3.5))
            outer_sh = in_sh & (sr2 > 0.58)
            dith_keep = (((sgx.astype(np.int32) + sgy.astype(np.int32)) & 1) == 0)
            apply_sh = (in_sh & (~outer_sh)) | (outer_sh & dith_keep)
            if apply_sh.any():
                rgb_buf[sy0 : sy1 + 1, sx0 : sx1 + 1][apply_sh] *= 0.80

        # 1. Crisp timber trunk extending cleanly into the crown interior (ZERO trunk-to-canopy gap!)
        crown_bot_y = cy0 - trunk_h_px
        crown_top_y = crown_bot_y - crown_ry * 2.0
        crown_cy = 0.5 * (crown_bot_y + crown_top_y)

        tx_i = int(round(cx0))
        ty_bot = int(round(cy0)) + 1
        ty_top = int(round(crown_cy))
        tw_half = 1 if r_px >= 6.8 else 0
        y_lo_t = max(0, ty_top)
        y_hi_t = min(H - 1, ty_bot)
        x_lo_t = max(0, tx_i - tw_half)
        x_hi_t = min(W - 1, tx_i + tw_half)
        if y_hi_t >= y_lo_t and x_hi_t >= x_lo_t:
            sl_z = zbuf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1]
            d_tr = d0 + 0.14
            w_tr = d_tr < sl_z
            if w_tr.any():
                sl_z[w_tr] = d_tr
                bark_c = [176.0, 170.0, 158.0] if (sp_k == 1 and (not is_willow) and (s2 & 3) < 2) else [86.0, 60.0, 40.0]
                rgb_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = bark_c
                mat_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = M_TRUNK
                obj_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = oid
                norm_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = [0.5, -0.5, 0.35]
                shadow_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = False

        # 2. Compute tight screen bounding box for sculpted 3D crown
        pad_x = int(math.ceil(r_px * 1.38)) + 2

        x0_b = max(0, int(math.floor(cx0)) - pad_x)
        x1_b = min(W - 1, int(math.ceil(cx0)) + pad_x)
        y0_b = max(0, int(math.floor(crown_top_y)) - 4)
        y1_b = min(H - 1, int(math.ceil(cy0)) + 1) if is_willow else min(H - 1, int(math.ceil(crown_bot_y)) + 2)
        if x1_b < x0_b or y1_b < y0_b:
            continue

        xs = np.arange(x0_b, x1_b + 1, dtype=np.float32)
        ys = np.arange(y0_b, y1_b + 1, dtype=np.float32)
        gx, gy = np.meshgrid(xs, ys)
        dx = gx - cx0
        v_h = (crown_bot_y - gy) / max(1.0, (crown_bot_y - crown_top_y))

        ramp = SPECIES_RAMPS[6 if is_willow else sp_k].copy()
        hue_shift = (((s2 & 31) / 31.0) - 0.5) * 0.14
        if abs(hue_shift) > 0.01:
            ramp = np.clip(ramp * np.array([1.0 + hue_shift * 0.8, 1.0 + hue_shift * 0.5, 1.0 - hue_shift * 0.4], dtype=np.float32), 8.0, 252.0)
        if not is_night and sp_k not in (4, 5):
            # Subtle warm golden sunlit tip nudge on tone 4 for crisp directional rim highlights
            ramp[4] = np.clip(ramp[4] + np.array([8.0, 6.0, -4.0], dtype=np.float32), 8.0, 252.0)

        ix = gx.astype(np.uint32)
        iy = gy.astype(np.uint32)
        cx2 = ix >> np.uint32(1)
        cy2 = iy >> np.uint32(1)
        h2 = cx2 * np.uint32(374761393) + cy2 * np.uint32(668265263) + np.uint32((tid * 1442695041) & 0xFFFFFFFF)
        h2 = (h2 ^ (h2 >> np.uint32(13))) * np.uint32(1274126177)
        h2 = h2 ^ (h2 >> np.uint32(16))
        clump_2x2 = (h2 & np.uint32(255)).astype(np.float32) * (1.0 / 255.0) - 0.5

        h1 = ix * np.uint32(1597334677) + iy * np.uint32(3812015801) + np.uint32((tid * 2654435761) & 0xFFFFFFFF)
        h1 = (h1 ^ (h1 >> np.uint32(13))) * np.uint32(1274126177)
        h1 = h1 ^ (h1 >> np.uint32(16))
        micro_1x1 = (h1 & np.uint32(255)).astype(np.float32) * (1.0 / 255.0) - 0.5

        bayer_t = BAYER_4X4[iy & np.uint32(3), ix & np.uint32(3)]

        if sp_k == 2:
            in_v = (v_h >= -0.04) & (v_h <= 1.05)
            v_c = np.clip(v_h, 0.0, 1.0)
            n_tiers = 5.0 if h_px >= 14.0 else 4.0
            t_ph = (v_c * n_tiers) % 1.0
            tier_wave = 0.62 + 0.44 * ((1.0 - t_ph) ** 0.85)
            half_w_y = np.maximum(0.85, r_px * (1.02 - 0.90 * v_c) * tier_wave)
            edge_n = clump_2x2 * 1.45 + micro_1x1 * 0.85
            nx_n = dx / np.maximum(1.0, half_w_y + edge_n)
            inside = in_v & (np.abs(nx_n) <= 1.0)
            if not inside.any():
                continue
            nz_n = np.sqrt(np.maximum(0.05, 1.0 - np.minimum(0.98, nx_n * nx_n)))
            ny_n = 0.25 + 0.48 * v_c - 0.34 * t_ph
            tier_sh = np.where(t_ph > 0.72, -0.32, np.where(t_ph < 0.22, 0.16, 0.0))
            nd_s = nx_n * lx_s + ny_n * ly_s + nz_n * lz_s + tier_sh + clump_2x2 * 0.46 + micro_1x1 * 0.22 + bayer_t * 0.18
            d_surf = d0 - nz_n * (r_m * 0.78) - v_c * (h_m * 0.45 * sp_c)

        elif sp_k == 3:
            in_v = (v_h >= -0.02) & (v_h <= 1.05)
            v_c = np.clip(v_h, 0.0, 1.0)
            flame = np.sin(np.power(v_c, 0.70) * math.pi)
            half_w_y = np.maximum(0.85, r_px * (0.24 + 0.86 * flame) + clump_2x2 * 0.9 + micro_1x1 * 0.65)
            nx_n = dx / half_w_y
            inside = in_v & (np.abs(nx_n) <= 1.0)
            if not inside.any():
                continue
            nz_n = np.sqrt(np.maximum(0.05, 1.0 - np.minimum(0.98, nx_n * nx_n)))
            ny_n = (v_c - 0.45) * 0.8
            nd_s = nx_n * lx_s + ny_n * ly_s + nz_n * lz_s + clump_2x2 * 0.42 + micro_1x1 * 0.18 + bayer_t * 0.18
            d_surf = d0 - nz_n * (r_m * 0.75) - v_c * (h_m * 0.45 * sp_c)

        elif is_willow:
            # 1. WEEPING LAKESIDE WILLOW: 5 soft upper dome lobes + cascading vertical frond curtain!
            dy_c = gy - crown_cy
            jx1 = (((s1 & 15) / 15.0) - 0.5) * 0.28 * r_px
            jy1 = ((((s1 >> 4) & 15) / 15.0) - 0.5) * 0.18 * crown_ry
            w_lobes = (
                (jx1 * 0.4, -0.42 * crown_ry + jy1 * 0.5, 0.56 * r_px, 0.44 * crown_ry),
                (-0.44 * r_px + jx1 * 0.3, -0.26 * crown_ry, 0.48 * r_px, 0.42 * crown_ry),
                (0.44 * r_px - jx1 * 0.3, -0.24 * crown_ry, 0.48 * r_px, 0.42 * crown_ry),
                (-0.22 * r_px, -0.10 * crown_ry, 0.52 * r_px, 0.40 * crown_ry),
                (0.24 * r_px, -0.08 * crown_ry, 0.52 * r_px, 0.40 * crown_ry),
            )
            best_z = np.full(gx.shape, -1.0, dtype=np.float32)
            best_nx = np.zeros(gx.shape, dtype=np.float32)
            best_ny = np.zeros(gx.shape, dtype=np.float32)
            for l_ox, l_oy, l_rx, l_ry in w_lobes:
                ux = (dx - l_ox) / max(1.4, l_rx)
                uy = (dy_c - l_oy) / max(1.4, l_ry)
                r2 = ux * ux + uy * uy
                in_l = r2 < 1.0
                if not in_l.any():
                    continue
                lz = np.sqrt(np.maximum(0.0, 1.0 - np.minimum(1.0, r2)))
                better = in_l & (lz > best_z)
                best_z[better] = lz[better]
                best_nx[better] = ux[better]
                best_ny[better] = -uy[better]

            # Cascading vertical weeping frond curtain draping below crown center!
            strand_wave = np.sin(gx * 1.45 + (s1 & 15) * 0.4) * 0.5 + 0.5
            w_curt = r_px * (0.98 - 0.18 * np.clip(dy_c / max(1.0, crown_ry), 0.0, 1.3))
            y_end = crown_bot_y + (0.20 + 0.42 * strand_wave + clump_2x2 * 0.25) * crown_ry
            in_curt = (dy_c > (-0.05 * crown_ry)) & (gy <= y_end) & (np.abs(dx) <= np.maximum(1.2, w_curt))
            curt_nx = np.clip(dx / np.maximum(1.5, w_curt), -0.98, 0.98)
            curt_z = np.sqrt(np.maximum(0.08, 1.0 - curt_nx * curt_nx)) * 0.85
            use_curt = in_curt & (curt_z > best_z)
            best_z[use_curt] = curt_z[use_curt]
            best_nx[use_curt] = curt_nx[use_curt]
            best_ny[use_curt] = -0.25

            rim_thresh = 0.14 + clump_2x2 * 0.22 + micro_1x1 * 0.14
            inside = (best_z > np.maximum(0.0, rim_thresh)) | (in_curt & (strand_wave > 0.24))
            if not inside.any():
                continue
            nz_n = np.maximum(0.15, best_z)
            nd_s = best_nx * lx_s + best_ny * ly_s + nz_n * lz_s
            nd_s += np.where(in_curt, (strand_wave - 0.5) * 0.34, 0.0)
            rim_hi = inside & (best_z < 0.56) & ((best_nx * lx_s + best_ny * ly_s) > 0.34) & (v_h > 0.45)
            nd_s = np.where(rim_hi, nd_s + 0.26, nd_s)
            nd_s = nd_s + clump_2x2 * 0.44 + micro_1x1 * 0.22 + bayer_t * 0.18 - np.clip(0.38 - v_h, 0.0, 0.42) * 0.54
            d_surf = d0 - nz_n * (r_m * 0.80) - np.clip(v_h, 0.0, 1.0) * (h_m * 0.40 * sp_c)

        else:
            dy_c = gy - crown_cy
            jx1 = (((s1 & 15) / 15.0) - 0.5) * 0.36 * r_px
            jy1 = ((((s1 >> 4) & 15) / 15.0) - 0.5) * 0.24 * crown_ry
            jx2 = ((((s1 >> 8) & 15) / 15.0) - 0.5) * 0.34 * r_px
            jy2 = ((((s1 >> 12) & 15) / 15.0) - 0.5) * 0.24 * crown_ry
            asym = ((((s2 >> 6) & 15) / 15.0) - 0.5) * 0.26 * r_px

            if is_oak:
                # 2. WIDE-SPREADING SWISS OAK / BEECH: 11 asymmetric bough clusters, broad sunlit cap!
                lobes = (
                    (asym * 0.6 + jx1 * 0.3, -0.38 * crown_ry + jy1 * 0.4, 0.54 * r_px, 0.44 * crown_ry),
                    (-0.46 * r_px + jx2 * 0.4, -0.32 * crown_ry + jy2 * 0.4, 0.46 * r_px, 0.40 * crown_ry),
                    (0.46 * r_px + jx1 * 0.4, -0.28 * crown_ry - jy1 * 0.4, 0.46 * r_px, 0.40 * crown_ry),
                    (-0.72 * r_px + jx1 * 0.3, 0.04 * crown_ry + jy2 * 0.4, 0.44 * r_px, 0.40 * crown_ry),
                    (0.70 * r_px - jx2 * 0.3, 0.08 * crown_ry + jy1 * 0.4, 0.44 * r_px, 0.40 * crown_ry),
                    (-0.28 * r_px + asym * 0.3, -0.06 * crown_ry, 0.52 * r_px, 0.46 * crown_ry),
                    (0.28 * r_px + asym * 0.3, -0.04 * crown_ry, 0.52 * r_px, 0.46 * crown_ry),
                    (-0.48 * r_px + jx2 * 0.3, 0.34 * crown_ry, 0.44 * r_px, 0.38 * crown_ry),
                    (0.48 * r_px + jx1 * 0.3, 0.32 * crown_ry, 0.44 * r_px, 0.38 * crown_ry),
                    (-0.14 * r_px, 0.46 * crown_ry + jy2 * 0.25, 0.46 * r_px, 0.38 * crown_ry),
                    (0.18 * r_px, 0.44 * crown_ry + jy1 * 0.25, 0.44 * r_px, 0.38 * crown_ry),
                )
                n_upper, n_lower_start = 3, 7
                bias_hi, bias_lo = 0.16, -0.20
                rim_thresh = 0.14 + clump_2x2 * 0.24 + micro_1x1 * 0.14
            else:
                # 3. AIRY MULTI-CLUSTER BIRCH / LINDEN / ORCHARD / BLOSSOM: 9 dappled leaf puffs seated naturally atop trunk!
                lobes = (
                    (asym * 0.5 + jx1 * 0.4, -0.50 * crown_ry + jy1 * 0.4, 0.40 * r_px, 0.38 * crown_ry),
                    (-0.42 * r_px + jx2 * 0.4, -0.34 * crown_ry + jy2 * 0.4, 0.38 * r_px, 0.36 * crown_ry),
                    (0.40 * r_px + jx1 * 0.4, -0.30 * crown_ry - jy1 * 0.4, 0.38 * r_px, 0.36 * crown_ry),
                    (-0.50 * r_px + jx1 * 0.25, 0.06 * crown_ry + jy2 * 0.4, 0.40 * r_px, 0.38 * crown_ry),
                    (0.48 * r_px - jx2 * 0.25, 0.10 * crown_ry + jy1 * 0.4, 0.40 * r_px, 0.38 * crown_ry),
                    (0.02 * r_px + asym * 0.35, -0.04 * crown_ry, 0.45 * r_px, 0.44 * crown_ry),
                    (-0.26 * r_px + jx2 * 0.3, 0.44 * crown_ry, 0.40 * r_px, 0.36 * crown_ry),
                    (0.26 * r_px + jx1 * 0.3, 0.42 * crown_ry, 0.40 * r_px, 0.36 * crown_ry),
                    (0.0, 0.38 * crown_ry, 0.36 * r_px, 0.34 * crown_ry),
                )
                n_upper, n_lower_start = 3, 6
                bias_hi, bias_lo = 0.14, -0.16
                rim_thresh = 0.18 + clump_2x2 * 0.26 + micro_1x1 * 0.14

            best_z = np.full(gx.shape, -1.0, dtype=np.float32)
            best_nx = np.zeros(gx.shape, dtype=np.float32)
            best_ny = np.zeros(gx.shape, dtype=np.float32)
            best_lobe_bias = np.zeros(gx.shape, dtype=np.float32)
            for l_idx, (l_ox, l_oy, l_rx, l_ry) in enumerate(lobes):
                ux = (dx - l_ox) / max(1.4, l_rx)
                uy = (dy_c - l_oy) / max(1.4, l_ry)
                r2 = ux * ux + uy * uy
                in_l = r2 < 1.0
                if not in_l.any():
                    continue
                lz = np.sqrt(np.maximum(0.0, 1.0 - np.minimum(1.0, r2)))
                better = in_l & (lz > best_z)
                best_z[better] = lz[better]
                best_nx[better] = ux[better]
                best_ny[better] = -uy[better]
                best_lobe_bias[better] = bias_hi if l_idx < n_upper else (bias_lo if l_idx >= n_lower_start else 0.0)

            inside = best_z > np.maximum(0.0, rim_thresh)
            if not inside.any():
                continue
            nz_n = best_z
            nd_s = best_nx * lx_s + best_ny * ly_s + nz_n * lz_s + best_lobe_bias
            # Directional top-left sunlit rim highlight!
            rim_hi = inside & (best_z < 0.56) & ((best_nx * lx_s + best_ny * ly_s) > 0.34) & (v_h > 0.45)
            nd_s = np.where(rim_hi, nd_s + 0.28, nd_s)
            leaf_tex = clump_2x2 * 0.56 + micro_1x1 * 0.24 + bayer_t * 0.18
            nd_s = nd_s + leaf_tex - np.clip(0.38 - v_h, 0.0, 0.38) * 0.68
            d_surf = d0 - nz_n * (r_m * 0.82) - np.clip(v_h, 0.0, 1.0) * (h_m * 0.42 * sp_c)

        tone_idx = np.clip(np.floor((nd_s + 0.06) * 3.10).astype(np.int32), 0, 4)

        sub_z = zbuf[y0_b : y1_b + 1, x0_b : x1_b + 1]
        win = inside & (d_surf < sub_z)
        if not win.any():
            continue

        wy, wx = np.nonzero(win)
        gy_w = y0_b + wy
        gx_w = x0_b + wx
        zbuf[gy_w, gx_w] = d_surf[wy, wx]
        rgb_buf[gy_w, gx_w] = ramp[tone_idx[wy, wx]]
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
    vs = (ix_s >= 1) & (ix_s < W - 3) & (iy_s >= 1) & (iy_s < H - 3)
    ix_s, iy_s = ix_s[vs], iy_s[vs]
    sh_rad = (0, 1, 2) if camera.mpp <= 0.36 else (0, 1)
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

    # 2x horizontal tangent sub-sampling at <=0.36 m/px eliminates vertical column moire!
    if camera.mpp <= 0.36 and len(pe) > 0:
        tx_p = -pny * 0.125
        ty_p = pnx * 0.125
        pe = np.concatenate([pe - tx_p, pe + tx_p])
        pn = np.concatenate([pn - ty_p, pn + ty_p])
        pz_top = np.tile(pz_top, 2)
        p_lake = np.tile(p_lake, 2)
        p_bathy = np.tile(p_bathy, 2)
        pnx = np.tile(pnx, 2)
        pny = np.tile(pny, 2)

    dz_step = max(0.20, camera.mpp * 0.45)
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

    # -------------------------------------------------------------------------
    # STAGE 2: 100% Drawn 90s Pixel-Art Ground, Fields, Streets, Crosswalks & SBB Rail!
    # -------------------------------------------------------------------------
    ground_sub_res = 0.25 if camera.mpp <= 0.36 else 0.50
    if sub_mask.any():
        gr05, gc05 = np.nonzero(sub_mask)
        ge05 = E_MIN + (gc05 + c0 + 0.5) * GRID_RES
        gn05 = N_MAX - (gr05 + r0 + 0.5) * GRID_RES
        px05, py05, _ = camera.project(ge05, gn05, sub_dem[gr05, gc05])
        in_w05 = (
            ((px05 + shift_x) >= -8.0)
            & ((px05 + shift_x) <= (W + 8.0))
            & ((py05 + shift_y) >= -24.0)
            & ((py05 + shift_y) <= (H + 12.0))
        )
        gr05, gc05 = gr05[in_w05], gc05[in_w05]
        ge05, gn05 = ge05[in_w05], gn05[in_w05]

        if len(gr05) > 0:
            if ground_sub_res == 0.25:
                gr = np.tile(gr05, 4)
                gc = np.tile(gc05, 4)
                ge = np.concatenate([ge05 - 0.125, ge05 + 0.125, ge05 - 0.125, ge05 + 0.125])
                gn = np.concatenate([gn05 + 0.125, gn05 + 0.125, gn05 - 0.125, gn05 - 0.125])
            else:
                gr, gc, ge, gn = gr05, gc05, ge05, gn05
        else:
            gr = gc = np.empty(0, dtype=np.int32)
            ge = gn = np.empty(0, dtype=np.float64)

    if sub_mask.any() and len(gr) > 0:
        gz = sub_dem[gr, gc].copy()
        gsem = sub_sem[gr, gc]
        glake = sub_lake[gr, gc]
        gbathy = sub_bathy[gr, gc]
        gkpoly = sub_kpoly[gr, gc]
        gharbor = sub_harbor[gr, gc]
        gsh = sub_shadow[gr, gc]
        gnx = scene.terr_nx[r0:r1, c0:c1][gr, gc].astype(np.float32)
        gny = scene.terr_ny[r0:r1, c0:c1][gr, gc].astype(np.float32)
        gnz = scene.terr_nz[r0:r1, c0:c1][gr, gc].astype(np.float32)

        rd_dist = scene.road_dist[r0:r1, c0:c1][gr, gc].astype(np.float32)
        rd_along = scene.road_along[r0:r1, c0:c1][gr, gc]
        rd_hw = scene.road_hw[r0:r1, c0:c1][gr, gc].astype(np.float32)
        rl_dist = scene.rail_dist[r0:r1, c0:c1][gr, gc].astype(np.float32)
        rl_along = scene.rail_along[r0:r1, c0:c1][gr, gc]
        xwalk = scene.crosswalk_mask[r0:r1, c0:c1][gr, gc]

        raw_ortho = sample_ortho_25cm(scene, ge, gn)
        gcol, gmat, gz = _shade_drawn_ground_90s(
            scene, ge, gn, gz, gsem, glake, gbathy, gharbor, raw_ortho,
            rd_dist, rd_along, rd_hw, rl_dist, rl_along, xwalk,
            gnx, gny, gnz, sub_chm[gr, gc],
            preset_key=preset_key,
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
            gnx, gny, gnz = gnx[gv], gny[gv], gnz[gv]

            order = np.argsort(gdepth)[::-1]
            gix, giy, gdepth = gix[order], giy[order], gdepth[order]
            gcol, gmat, gsh, glake_v = gcol[order], gmat[order], gsh[order], glake_v[order]
            gnx, gny, gnz = gnx[order], gny[order], gnz[order]

            for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                tx = np.clip(gix + ox, 0, W - 1)
                ty = np.clip(giy + oy, 0, H - 1)
                d_b = gdepth + (0.08 if (ox or oy) else 0.0)
                win = d_b <= zbuf[ty, tx]
                zbuf[ty[win], tx[win]] = d_b[win]
                rgb_buf[ty[win], tx[win]] = gcol[win]
                mat_buf[ty[win], tx[win]] = gmat[win]
                obj_buf[ty[win], tx[win]] = np.where(gmat[win] == M_HARBOR_OBJ, 250000, 0)
                shadow_buf[ty[win], tx[win]] = gsh[win]
                norm_buf[ty[win], tx[win], 0] = gnx[win]
                norm_buf[ty[win], tx[win], 1] = gny[win]
                norm_buf[ty[win], tx[win], 2] = gnz[win]

            # F14c: Staggered Ashlar Jura-Stone Retaining Walls with Coping Cap & Trailing Ivy (exclude lake!)
            steep = (gnz < 0.88) & (~glake_v)
            if steep.any():
                si = np.nonzero(steep)[0]
                s_ix = gix[si]
                s_iy = giy[si]
                s_d = gdepth[si]
                s_sh = gsh[si]
                s_nx, s_ny, s_nz = gnx[si], gny[si], gnz[si]
                is_rwall = s_nz < 0.72
                s_col = np.where(is_rwall[:, None], [158.0, 152.0, 140.0], gcol[si] * 0.88).astype(np.float32)
                max_drop = np.clip(np.round((1.0 - s_nz) * 24.0).astype(np.int32), 2, 10)
                for oy in range(2, 11):
                    act = max_drop >= oy
                    if not act.any():
                        continue
                    ai = np.nonzero(act)[0]
                    course_id = (oy - 2) // 3
                    is_h_mortar = ((oy - 2) % 3) == 2
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
        [lm.get(k, -1) for k in ("sanatorium_483", "sanatorium_633", "sanatorium_521", "sanatorium_853", "sanatorium_655")],
        dtype=np.int32,
    )
    seebad_ids_arr = np.array(
        [lm.get(k, -1) for k in ("seebad_bathhouse", "seebad_kiosk", "seebad_south")],
        dtype=np.int32,
    )

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

                # Sample TRUE 25 cm SWISSIMAGE DOP10 satellite roof texture!
                raw_r25 = sample_ortho_25cm(scene, re_r, rn_r)
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

                # Blend authentic satellite texture (Lindt HoC strictly preserved at base_w = 0.95!)
                base_w = np.where(r_bi == id_lindt_hoc, 0.95, np.where(pitched, 0.72, 0.88)).astype(np.float32)
                sat_w = np.where(is_overhang_leaf, 0.0, np.where(is_deep_aerial_sh, 0.25, base_w))[:, None]
                r_alb = sat_w * sat_r + (1.0 - sat_w) * r_clean

                # 1. Pitched Roofs: Subtle crisp 90s pixel-art clay/slate tile course overlap relief & dark eave line!
                if pitched.any():
                    pi_r = np.nonzero(pitched)[0]
                    rz_p = rz_r[pi_r]
                    ru_p = ru_r[pi_r]
                    rb_p = r_bi[pi_r]
                    course_f = rz_p * 1.80
                    course_idx = np.floor(course_f).astype(np.int32)
                    in_course = course_f - course_idx
                    u_f = ru_p * 2.05 + (course_idx & 1) * 0.5
                    u_tile = u_f - np.floor(u_f)

                    r_alb[pi_r[in_course < 0.24]] *= 0.87
                    r_alb[pi_r[(in_course >= 0.76) & (in_course < 0.94)]] = np.minimum(
                        244.0, r_alb[pi_r[(in_course >= 0.76) & (in_course < 0.94)]] * 1.045
                    )
                    r_alb[pi_r[u_tile < 0.12]] *= 0.95
                    eave_d = rz_p - scene.bldg_eave_z[rb_p]
                    r_alb[pi_r[(eave_d >= -0.25) & (eave_d < 0.36)]] *= 0.82

                # 2. Flat Roofs (including Lindt Home of Chocolate's EXACT real satellite roof!)
                flat = ~pitched
                if flat.any():
                    fi_r = np.nonzero(flat)[0]
                    est = sample_roof_edge_25cm(scene, re_r[fi_r], rn_r[fi_r])
                    is_coping = est == 1
                    is_p_sh = est == 2
                    r_alb[fi_r[is_coping]] = np.clip(
                        r_alb[fi_r[is_coping]] * 0.45 + np.array([124.0, 122.0, 118.0]), 140.0, 232.0
                    )
                    r_alb[fi_r[is_p_sh]] *= 0.80

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

                f_col[rm] = r_alb

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

                w_dbin = dir_bin_v[w_ft]
                w_key = w_bi * 36 + w_dbin
                u_min_w = scene.wall_u_min[w_key]
                u_max_w = scene.wall_u_max[w_key]
                wall_len = np.maximum(0.5, u_max_w - u_min_w)
                u_local = w_u - u_min_w
                d_center = w_u - 0.5 * (u_min_w + u_max_w)
                edge_dist = np.minimum(u_local, wall_len - u_local)

                # Subtle tactile plaster / stone masonry micro-texture
                wh_tex = ((np.floor(w_u * 3.0).astype(np.int32) * 73856093) ^ (np.floor(w_z * 3.0).astype(np.int32) * 19349663)) & 31
                w_base[wh_tex < 6] *= 0.97
                w_base[wh_tex > 26] = np.minimum(246.0, w_base[wh_tex > 26] * 1.025)

                # Crisp stone foundation plinth, deep roof eave shadow, and subtle vertical corner shade!
                w_base[h_rel < 0.65] *= 0.82
                w_base[(top_dist > 0.0) & (top_dist < 0.50)] *= 0.78
                w_base[(edge_dist < 0.28) & (wall_len > 3.2)] *= 0.92

                # Buff-brick Lindt smokestack (43.6m Hochkamin)
                is_chimney = w_bi == id_lindt_chim
                if is_chimney.any():
                    ch_i = np.nonzero(is_chimney)[0]
                    ch_course = ((w_z[ch_i] * 1.4) % 1.0) < 0.25
                    w_base[ch_i[ch_course]] *= 0.93
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
                    s_col[(h_rel[sl_i] % 2.5) < 0.16] *= 0.84      # Horizontal bolted steel rings
                    s_col[h_rel[sl_i] < 0.90] = [118.0, 122.0, 128.0]  # Galvanized base plinth
                    s_col[top_dist[sl_i] < 0.42] = [132.0, 138.0, 146.0]
                    w_base[sl_i] = np.clip(s_col, 24.0, 248.0)

                # F12: Treibhaus Glass Greenhouses (style 7 — Langholzweg 70g/70h & Uf Stocken!)
                is_gh_w = w_sty == 7
                if is_gh_w.any():
                    gh_i = np.nonzero(is_gh_w)[0]
                    gh_h = h_rel[gh_i]
                    gh_u = u_local[gh_i]
                    is_knee = gh_h < 0.72
                    is_mull = ((gh_u % 1.65) < 0.16) | ((gh_h % 1.45) < 0.14)
                    g_col_w = np.full(
                        (len(gh_i), 3),
                        [64.0, 92.0, 118.0] if preset.is_night else [146.0, 190.0, 206.0],
                        dtype=np.float32,
                    )
                    # Interior botanical greenery visible through lower glass bays
                    gh_noise = ((np.floor(gh_u * 2.5).astype(np.int32) * 73856093) ^ (np.floor(gh_h * 3.0).astype(np.int32) * 19349663)) & 15
                    in_fol = (~is_knee) & (gh_h <= 2.35) & (gh_noise < 9)
                    g_col_w[in_fol] = [44.0, 74.0, 54.0] if preset.is_night else [86.0, 134.0, 88.0]
                    g_col_w[is_mull] = [156.0, 164.0, 174.0] if preset.is_night else [222.0, 228.0, 232.0]
                    g_col_w[is_knee] = [168.0, 166.0, 160.0]
                    w_base[gh_i] = g_col_w
                    f_mat[wi[gh_i[(~is_knee) & (~is_mull)]]] = M_WINDOW_DAY

                # B1. Lindt Home of Chocolate (style 2)
                is_hoc = w_sty == 2
                if is_hoc.any():
                    hi_l = np.nonzero(is_hoc)[0]
                    le, ln, lz, lh = w_e[hi_l], w_n[hi_l], w_z[hi_l], h_rel[hi_l]
                    lu = u_local[hi_l]
                    in_white_curve = (le >= 2684107.5) & (ln >= 1241401.5) & (ln <= 1241437.2)
                    w_base[hi_l[in_white_curve]] = [238.0, 236.0, 230.0]
                    w_course = in_white_curve & (((lz * 1.8) % 1.0) < 0.16)
                    w_base[hi_l[w_course]] *= 0.96

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
                    gold_frieze = (
                        in_white_curve
                        & (lt_d >= 0.70)
                        & (lt_d <= 1.95)
                        & (((arc_u * 1.45) % 1.0) >= 0.28)
                        & (arc_u >= 3.5)
                    )
                    if gold_frieze.any():
                        gf_idx = hi_l[gold_frieze]
                        w_base[gf_idx] = [228.0, 188.0, 74.0]
                        if preset.is_night or preset_key == "sunset":
                            f_mat[wi[gf_idx]] = M_WINDOW_LIT

                    plaza_glass = (
                        ((in_white_curve & (lh >= 0.35) & (lh <= 5.4)) | (brick_m & (le >= 2684118.0) & (lh >= 0.45) & (lh <= 3.8)))
                        & (((arc_u % 4.2) >= 0.85) & ((arc_u % 4.2) <= 3.35))
                    )
                    brick_office_win = (
                        brick_m
                        & (lh >= 6.2)
                        & (lh <= 18.6)
                        & (((lh - 6.2) % 4.2) <= 2.1)
                        & (((lu + 1.8) % 6.8) <= 1.05)
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

                # B1b. Main Seestrasse 204 Lindt & Sprüngli Complex
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
                        pcol = np.full((len(pi), 3), [158.0, 66.0, 50.0], dtype=np.float32)
                        brick_line = ((pz * 2.2) % 1.0) < 0.22
                        pcol[brick_line] *= 0.90
                        pilaster_l = (pu % 4.2) < 0.58
                        string_c = ((ph % 4.1) < 0.34) & (ph >= 3.8)
                        pcol[pilaster_l | string_c] = [212.0, 196.0, 158.0]
                        pcol[ph < 4.2] = [148.0, 144.0, 136.0]
                        pcol[(ph >= 15.8) & (ph < 16.9)] = [216.0, 200.0, 162.0]
                        w_base[pi] = pcol

                    wing_mid = (mn >= 1241362.0) & (mn < 1241403.0)
                    if wing_mid.any():
                        mi_b = m_i[wing_mid]
                        mh_b = mh[wing_mid]
                        mtd_b = mtd[wing_mid]
                        me_b = me[wing_mid]
                        mu_b = mu[wing_mid]
                        bcol = np.full((len(mi_b), 3), [208.0, 206.0, 198.0], dtype=np.float32)
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
                        tcol = np.full((len(ti_c), 3), [212.0, 210.0, 202.0], dtype=np.float32)
                        tcol[th_c < 1.6] = [138.0, 136.0, 132.0]
                        recess = (th_c >= 6.0) & (th_c <= 19.5) & (((tu_c % 4.4) >= 0.8) & ((tu_c % 4.4) <= 3.6))
                        tcol[recess] = [196.0, 194.0, 186.0]
                        crest = (ttd_c <= 1.6) & (np.abs(d_center[ti_c]) <= 3.6)
                        tcol[crest] = [228.0, 190.0, 76.0]
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

                    quoin = (s_bi == id_ref_kirche) & (s_edg < 0.52) & (((np.floor(sz_w * 1.3).astype(np.int32)) % 2) == 0)
                    w_base[si_l[quoin]] = [196.0, 184.0, 164.0]

                    rk_tower = (s_bi == id_ref_kirche) & (se_w >= 2683407.6)
                    if rk_tower.any():
                        rt_i = np.nonzero(rk_tower)[0]
                        rt_glob = si_l[rt_i]
                        tx_t = tw_x_v[s_ft[rt_i]]
                        ty_t = tw_y_v[s_ft[rt_i]]
                        d_tc = (se_w[rt_i] - 2683413.0) * tx_t + (sn_w[rt_i] - 1241287.7) * ty_t
                        z_t = sz_w[rt_i]

                        du_pair = np.abs(d_tc) - 1.05
                        in_louver_rect = (np.abs(du_pair) <= 0.58) & (z_t >= 524.8) & (z_t <= 527.8)
                        in_louver_arch = (z_t > 527.8) & (z_t <= 528.65) & (((du_pair / 0.58) ** 2 + ((z_t - 527.8) / 0.82) ** 2) <= 1.0)
                        louver = in_louver_rect | in_louver_arch
                        if louver.any():
                            lv_g = rt_glob[louver]
                            slat = ((z_t[louver] * 3.5) % 1.0) < 0.45
                            w_base[lv_g] = np.where(slat[:, None], [58.0, 48.0, 42.0], [34.0, 30.0, 32.0])

                        slit = (np.abs(d_tc) <= 0.20) & (z_t >= 518.2) & (z_t <= 520.6)
                        w_base[rt_glob[slit]] = [46.0, 48.0, 56.0]

                        dz_ck = z_t - 531.7
                        r_ck = np.hypot(d_tc, dz_ck)
                        on_clock = r_ck <= 2.22
                        if on_clock.any():
                            ck_sub = np.nonzero(on_clock)[0]
                            ck_g = rt_glob[ck_sub]
                            rc = r_ck[ck_sub]
                            ux = d_tc[ck_sub]
                            uz = dz_ck[ck_sub]

                            dial_col = np.full((len(ck_sub), 3), 24.0, dtype=np.float32)
                            dial_col[:, 1] = 28.0
                            dial_col[:, 2] = 38.0

                            gold_rim = (rc >= 1.72) & (rc <= 2.22)
                            inner_ring = (rc >= 1.38) & (rc <= 1.50)
                            d_hr = np.abs(ux * 0.57 + uz * 0.82)
                            along_hr = -ux * 0.82 + uz * 0.57
                            hand_hr = (d_hr <= 0.22) & (along_hr >= -0.15) & (along_hr <= 1.18)

                            d_mn = np.abs(-ux * 0.50 + uz * 0.866)
                            along_mn = ux * 0.866 + uz * 0.50
                            hand_mn = (d_mn <= 0.18) & (along_mn >= -0.15) & (along_mn <= 1.58)

                            hub = rc <= 0.28
                            is_gold = gold_rim | inner_ring | hand_hr | hand_mn | hub
                            dial_col[is_gold] = [238.0, 196.0, 76.0]
                            w_base[ck_g] = dial_col
                            if preset.is_night or preset_key == "sunset":
                                f_mat[wi[ck_g[is_gold]]] = M_WINDOW_LIT

                    rk_nave = (s_bi == id_ref_kirche) & (se_w < 2683407.6) & (s_edg >= 1.6)
                    if rk_nave.any():
                        rn_i = np.nonzero(rk_nave)[0]
                        rn_glob = si_l[rn_i]
                        nu = (s_ul[rn_i] % 4.8) - 2.4
                        nz_w = sz_w[rn_i]
                        lancet_body = (np.abs(nu) <= 0.64) & (nz_w >= 513.4) & (nz_w <= 518.2)
                        lancet_arch = (nz_w > 518.2) & (nz_w <= 519.3) & (((nu / 0.64) ** 2 + ((nz_w - 518.2) / 1.05) ** 2) <= 1.0)
                        lancet = lancet_body | lancet_arch
                        if lancet.any():
                            lg_idx = rn_glob[lancet]
                            if preset.is_night:
                                w_base[lg_idx] = [255.0, 214.0, 118.0]
                                f_mat[wi[lg_idx]] = M_WINDOW_LIT
                            elif preset_key == "sunset":
                                w_base[lg_idx] = [248.0, 198.0, 108.0]
                                f_mat[wi[lg_idx]] = M_WINDOW_LIT
                            else:
                                w_base[lg_idx] = [48.0, 68.0, 92.0]
                                f_mat[wi[lg_idx]] = M_WINDOW_DAY

                    st_el_tower = s_bi == id_st_el_twr
                    if st_el_tower.any():
                        et_i = np.nonzero(st_el_tower)[0]
                        et_glob = si_l[et_i]
                        edc = s_dc[et_i]
                        ez = sz_w[et_i]
                        bslot = (np.abs(np.abs(edc) - 0.55) <= 0.24) & (ez >= 510.2) & (ez <= 516.4)
                        w_base[et_glob[bslot]] = [42.0, 44.0, 50.0]
                        r_ec = np.hypot(edc, ez - 507.6)
                        w_base[et_glob[(r_ec <= 1.25) & (r_ec >= 0.90)]] = [228.0, 188.0, 74.0]
                        w_base[et_glob[r_ec < 0.90]] = [30.0, 34.0, 44.0]

                    st_el_nave = (s_bi == id_st_el_nave) & (s_edg >= 1.8)
                    if st_el_nave.any():
                        en_i = np.nonzero(st_el_nave)[0]
                        en_glob = si_l[en_i]
                        clere = (sh_w[en_i] >= 9.5) & (sh_w[en_i] <= 12.2) & (((s_ul[en_i] % 2.8) >= 0.45))
                        if clere.any():
                            cg_idx = en_glob[clere]
                            w_base[cg_idx] = [255.0, 218.0, 128.0] if preset.is_night else [58.0, 82.0, 108.0]
                            f_mat[wi[cg_idx]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY

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

                    # 1. Bahnhof Kilchberg SBB Heritage Station Building (idx=670)
                    m_bhf = c_bi == id_bhf_stn
                    if m_bhf.any():
                        bi_b = ci_l[m_bhf]
                        bh_b, bu_b, be_b = c_h[m_bhf], c_ul[m_bhf], c_edg[m_bhf]
                        w_base[bi_b[bh_b < 1.2]] = [168.0, 164.0, 154.0]
                        quoin_b = (be_b < 0.48) & ((np.floor(c_z[m_bhf] * 1.4).astype(np.int32) & 1) == 0)
                        w_base[bi_b[quoin_b]] = [194.0, 186.0, 170.0]
                        # Blue-and-white SBB station fascia board at h_rel in [3.4, 4.1]
                        fascia_b = (bh_b >= 3.4) & (bh_b <= 4.1) & (be_b >= 0.8)
                        w_base[bi_b[fascia_b]] = [26.0, 72.0, 148.0]
                        w_base[bi_b[fascia_b & (bh_b >= 3.62) & (bh_b <= 3.88) & (((bu_b * 1.4) % 1.0) >= 0.25)]] = [244.0, 244.0, 240.0]
                        # Arched ground-floor station waiting-room portals + upper windows
                        gf_arch = (bh_b >= 0.65) & (bh_b <= 3.05) & (be_b >= 1.1) & (((bu_b % 3.4) >= 0.65) & ((bu_b % 3.4) <= 2.55))
                        up_win = (bh_b >= 4.9) & (c_z[m_bhf] <= (c_eave[m_bhf] - 0.5)) & (be_b >= 1.1) & (((bh_b - 4.9) % 3.2) <= 1.65) & (((bu_b % 3.2) >= 0.85) & ((bu_b % 3.2) <= 2.15))
                        b_win = gf_arch | up_win
                        if b_win.any():
                            bw_g = bi_b[b_win]
                            if preset.is_night or (preset_key == "sunset" and gf_arch.any()):
                                lit_b = np.full(len(bw_g), preset.is_night, dtype=np.bool_) | gf_arch[b_win]
                                w_base[bw_g] = np.where(lit_b[:, None], [255.0, 224.0, 144.0], [46.0, 62.0, 84.0])
                                f_mat[wi[bw_g]] = np.where(lit_b, M_WINDOW_LIT, M_WINDOW_DAY)
                            else:
                                w_base[bw_g] = [44.0, 66.0, 92.0]
                                f_mat[wi[bw_g]] = M_WINDOW_DAY

                    # 2. Gemeindehaus Kilchberg (Alte Landstrasse 110 / 110a)
                    m_gem = (c_bi == id_gem_main) | (c_bi == id_gem_wing)
                    if m_gem.any():
                        bi_g = ci_l[m_gem]
                        gh_g, gu_g, ge_g, gtd_g, gdc_g = c_h[m_gem], c_ul[m_gem], c_edg[m_gem], c_td[m_gem], c_dc[m_gem]
                        w_base[bi_g[gh_g < 3.6]] = [184.0, 178.0, 166.0]  # Rusticated Jura-stone arcade plinth
                        w_base[bi_g[gtd_g < 0.75]] = [236.0, 232.0, 222.0]  # Bold civic cornice
                        arcade = (gh_g >= 0.35) & (gh_g <= 3.0) & (ge_g >= 1.5) & (((gu_g % 4.0) >= 0.9) & ((gu_g % 4.0) <= 2.9))
                        civ_w = (gh_g >= 4.4) & (gtd_g >= 1.4) & (ge_g >= 1.2) & (((gh_g - 4.4) % 3.4) <= 1.85) & (((gu_g % 3.4) >= 0.85) & ((gu_g % 3.4) <= 2.25))
                        g_win = arcade | civ_w
                        if g_win.any():
                            gw_g = bi_g[g_win]
                            w_base[gw_g] = [255.0, 218.0, 130.0] if preset.is_night else [44.0, 64.0, 88.0]
                            f_mat[wi[gw_g]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY
                        # Subtle Swiss red-and-white civic crest banner flanking main entry
                        crest_g = (c_bi[m_gem] == id_gem_main) & (np.abs(gdc_g) <= 0.75) & (gh_g >= 3.8) & (gh_g <= 5.6)
                        if crest_g.any():
                            cg_i = bi_g[crest_g]
                            w_base[cg_i] = [208.0, 38.0, 38.0]
                            cross_g = (np.abs(gdc_g[crest_g]) <= 0.22) & (gh_g[crest_g] >= 4.35) & (gh_g[crest_g] <= 5.05)
                            w_base[cg_i[cross_g]] = [246.0, 246.0, 242.0]

                    # 3. C.F. Meyer-Haus (Alte Landstrasse 170 + pin villa)
                    m_cfm = (c_bi == id_cfm_1033) | (c_bi == id_cfm_1722)
                    if m_cfm.any():
                        bi_m = ci_l[m_cfm]
                        mh_m, mu_m, me_m, mdc_m = c_h[m_cfm], c_ul[m_cfm], c_edg[m_cfm], c_dc[m_cfm]
                        quoin_m = (me_m < 0.48) | (((mh_m % 3.15) < 0.22) & (mh_m > 2.8))
                        w_base[bi_m[quoin_m]] = [212.0, 204.0, 188.0]
                        m_in_fl = (mh_m % 3.15) / 3.15
                        m_bay = (mu_m % 3.6) - 1.8
                        m_valid = (me_m >= 1.0) & (c_z[m_cfm] <= (c_eave[m_cfm] - 0.35)) & (mh_m >= 0.8)
                        m_gew = m_valid & (m_in_fl >= 0.26) & (m_in_fl <= 0.80) & (np.abs(m_bay) <= 0.68)
                        m_shut = m_valid & (m_in_fl >= 0.30) & (m_in_fl <= 0.76) & (np.abs(m_bay) > 0.60) & (np.abs(m_bay) <= 0.96)
                        m_pane = m_valid & (m_in_fl >= 0.30) & (m_in_fl <= 0.76) & (np.abs(m_bay) <= 0.56)
                        w_base[bi_m[m_gew]] = [232.0, 228.0, 218.0]
                        w_base[bi_m[m_shut]] = [46.0, 94.0, 62.0]  # Deep forest-green louvered shutters
                        if m_pane.any():
                            mp_g = bi_m[m_pane]
                            w_base[mp_g] = [255.0, 218.0, 130.0] if preset.is_night else [46.0, 68.0, 94.0]
                            f_mat[wi[mp_g]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY
                        portal_m = (mh_m >= 0.15) & (mh_m <= 2.55) & (np.abs(mdc_m) <= 0.72)
                        w_base[bi_m[portal_m]] = [82.0, 54.0, 38.0]

                    # 4. Sanatorium Kilchberg (Historic 1906 Pavilion Hospital Campus — Plate 06 Hero!)
                    m_san = np.isin(c_bi, san_ids_arr)
                    if m_san.any():
                        bi_s = ci_l[m_san]
                        sh_s, su_s, se_s, snx_s = c_h[m_san], c_ul[m_san], c_edg[m_san], c_nx[m_san]
                        w_base[bi_s[sh_s < 3.2]] = [174.0, 168.0, 156.0]  # Rusticated stone ground base
                        belt_s = (sh_s >= 3.0) & ((sh_s % 3.6) < 0.32)
                        w_base[bi_s[belt_s]] = [234.0, 230.0, 218.0]
                        # East/lake-facing sunlit patient verandas & loggias with wrought-iron balustrades!
                        s_fl = np.floor(sh_s / 3.6).astype(np.int32)
                        s_inz = (sh_s - s_fl * 3.6) / 3.6
                        s_bay = (su_s % 4.0) - 2.0
                        veranda = (snx_s > 0.45) & (s_fl >= 1) & (se_s >= 1.2) & (c_td[m_san] >= 1.2) & (np.abs(s_bay) <= 1.45)
                        v_rec = veranda & (s_inz >= 0.38) & (s_inz <= 0.82)
                        v_bal = veranda & (s_inz >= 0.10) & (s_inz < 0.38)
                        w_base[bi_s[v_rec]] = [86.0, 82.0, 78.0]
                        w_base[bi_s[v_bal]] = [58.0, 62.0, 68.0]  # Wrought-iron balustrade
                        s_win = (se_s >= 1.1) & (c_td[m_san] >= 1.2) & (s_inz >= 0.32) & (s_inz <= 0.78) & (np.abs(s_bay) <= 0.62)
                        if s_win.any():
                            sw_g = bi_s[s_win]
                            s_lit = preset.is_night and (((np.floor(su_s[s_win] / 4.0).astype(np.int32) + s_fl[s_win]) & 1) == 0)
                            if preset.is_night:
                                lit_m_s = (((np.floor(su_s[s_win] / 4.0).astype(np.int32) ^ s_fl[s_win]) & 1) == 0)
                                w_base[sw_g] = np.where(lit_m_s[:, None], [255.0, 220.0, 134.0], [34.0, 48.0, 72.0])
                                f_mat[wi[sw_g]] = np.where(lit_m_s, M_WINDOW_LIT, M_WINDOW_DAY)
                            else:
                                w_base[sw_g] = [48.0, 70.0, 96.0]
                                f_mat[wi[sw_g]] = M_WINDOW_DAY

                    # 5. Seebad Kilchberg Timber Badi Bathhouse & Kiosk (Plate 05 Hero!)
                    m_sb = np.isin(c_bi, seebad_ids_arr)
                    if m_sb.any():
                        bi_sb = ci_l[m_sb]
                        sbh, sbu, sbtd = c_h[m_sb], c_ul[m_sb], c_td[m_sb]
                        # Warm honey-cedar horizontal wood boards + crisp white fascia eaves
                        board_g = ((sbh % 0.45) < 0.10)
                        w_base[bi_sb[board_g]] *= 0.85
                        w_base[bi_sb[sbtd < 0.55]] = [238.0, 236.0, 230.0]
                        # Lakeside turquoise changing-cabin doors every 2.6m
                        cab_door = (sbh >= 0.15) & (sbh <= 2.15) & ((sbu % 2.6) >= 0.75) & ((sbu % 2.6) <= 1.75)
                        w_base[bi_sb[cab_door]] = [58.0, 128.0, 158.0]
                        # Striped blue-and-white kiosk sun awning
                        kiosk_aw = (c_bi[m_sb] == lm.get("seebad_kiosk", -1)) & (sbh >= 2.25) & (sbh <= 2.80)
                        if kiosk_aw.any():
                            ka_i = bi_sb[kiosk_aw]
                            k_str = (np.floor(sbu[kiosk_aw] * 3.5).astype(np.int32) & 1) == 0
                            w_base[ka_i] = np.where(k_str[:, None], [242.0, 242.0, 238.0], [42.0, 106.0, 168.0])

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
                    bend_gable = (o_bi == id_bend_pav) & (oz > (oeave - 0.15))
                    w_base[oi[bend_gable]] = [224.0, 222.0, 216.0]
                    bend_win = (o_bi == id_bend_pav) & (oz <= (oeave - 0.35)) & (oh >= 1.0) & (oh <= 3.1) & (np.abs(odc) <= 2.2)
                    w_base[oi[bend_win]] = [56.0, 78.0, 98.0]

                    reg_outb = o_bi != id_bend_pav
                    is_door_face = reg_outb & (((o_bi + odb) % 3) == 0) & (owlen >= 3.2)
                    gdoor = is_door_face & (np.abs(odc) <= 1.05) & (oh >= 0.08) & (oh <= 2.25)
                    tiny_w = reg_outb & (~is_door_face) & (owlen >= 3.6) & (np.abs(odc) <= 0.45) & (oh >= 1.15) & (oh <= 2.05)
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
                    is_barn = (r_bi_w == id_barn_1490) | (r_bi_w == id_barn_1726)

                    slab_line = (r_sty == 1) & (r_wlen >= 9.0) & (r_h >= 2.8) & (((r_h % 3.15) < 0.24))
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

                    # F12: Selective Riegelhaus half-timbered historic Dorf/Lebern farmhouses (BEFORE windows!)
                    is_rieg = bldg_is_riegelhaus[r_bi_w]
                    if is_rieg.any():
                        r_horiz = (in_z < 0.08) | (np.abs(in_z - 0.30) < 0.05) | (np.abs(in_z - 0.78) < 0.05)
                        r_vert = (np.abs(bay_center_offset) > (bay_w * 0.44)) | (r_edg < 0.34)
                        r_diag = (r_edg < 1.35) & (np.abs((r_edg - 0.35) - (in_z * fl_h * 0.45)) < 0.14)
                        w_base[ri_l[is_rieg & (r_horiz | r_vert)]] = [84.0, 54.0, 38.0]
                        w_base[ri_l[is_rieg & r_diag]] = [88.0, 58.0, 40.0]

                    # F12: Dark walnut Swiss timber gable bargeboards on pitched style 0 gables!
                    z_gable_roof = bldg_z1[r_bi_w] - (bldg_z1[r_bi_w] - r_eave) * np.clip(np.abs(r_dc) / np.maximum(1.0, 0.5 * r_wlen), 0.0, 1.0)
                    on_barge = (r_sty == 0) & (r_wlen >= 5.2) & ((bldg_z1[r_bi_w] - r_eave) >= 1.8) & (r_z >= (r_eave - 0.15)) & (np.abs(z_gable_roof - r_z) <= 0.36)
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

                    active_bay = (
                        in_grid_bounds
                        & (~blank_narrow_wall)
                        & (~solid_pier_bay)
                        & (~is_door_bay)
                        & (~skip_gf_win)
                        & (~blind_tower_shaft)
                        & (~south_blind_floor)
                        & (~is_shop_gf)
                    )

                    # F12: Modern Swiss Apartments (style 1) — Recessed Dark Balconies / Loggias with Glass/Steel Balustrades!
                    is_balc_bay = (r_sty == 1) & (r_wlen >= 8.5) & (fl_idx >= 1) & active_bay & (((bay_hash >> 2) % 3) == 0)
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
                        sh_col = np.select(
                            [(sb_id == id_nav_1582) | (sb_id == id_nav_1695), sh_mode == 0, sh_mode == 1, sh_mode == 2, sh_mode == 3, sh_mode == 4],
                            [166.0, 46.0, 62.0, 68.0, 126.0, 92.0],
                            default=52.0,
                        )
                        sh_col_g = np.select(
                            [(sb_id == id_nav_1582) | (sb_id == id_nav_1695), sh_mode == 0, sh_mode == 1, sh_mode == 2, sh_mode == 3, sh_mode == 4],
                            [180.0, 86.0, 104.0, 124.0, 48.0, 66.0],
                            default=94.0,
                        )
                        sh_col_b = np.select(
                            [(sb_id == id_nav_1582) | (sb_id == id_nav_1695), sh_mode == 0, sh_mode == 1, sh_mode == 2, sh_mode == 3, sh_mode == 4],
                            [198.0, 58.0, 162.0, 110.0, 46.0, 46.0],
                            default=68.0,
                        )
                        w_base[sh_g] = np.stack([sh_col, sh_col_g, sh_col_b], axis=1)

                    # Window sill & subtle top head drop shadow
                    is_sill = active_bay & (~is_balc_bay) & (in_z >= (z_lo - 0.08)) & (in_z < z_lo) & (np.abs(bay_center_offset) <= (half_w + 0.14))
                    w_base[ri_l[is_sill]] = np.minimum(242.0, w_base[ri_l[is_sill]] * 1.10)
                    is_head_drop = active_bay & (~is_balc_bay) & (in_z > z_hi) & (in_z <= (z_hi + 0.05)) & (np.abs(bay_center_offset) <= (half_w + 0.05))
                    w_base[ri_l[is_head_drop]] *= 0.80

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
                        p_zhi = z_hi[p_sub]
                        hval = ((p_bi.astype(np.int64) * 73856093) ^ (p_fl.astype(np.int64) * 40503) ^ (p_bay.astype(np.int64) * 12289)) & 0xFF

                        if preset.is_night:
                            lit = hval < 138
                            warm_alt = (hval & 3) == 0
                            lit_c = np.where(warm_alt[:, None], [255.0, 228.0, 148.0], [255.0, 192.0, 92.0])
                            w_base[p_local] = np.where(lit[:, None], lit_c, [30.0, 42.0, 64.0])
                            f_mat[p_global] = np.where(lit, M_WINDOW_LIT, M_WINDOW_DAY)
                        elif preset_key == "sunset":
                            # F7: ~20% warm cozy dusk windows at Sunset (hval < 52)!
                            lit_dusk = hval < 52
                            mullion = np.abs(p_bco) < 0.08
                            upper_glint = p_inz > 0.56
                            pane_c = np.where(upper_glint[:, None], [118.0, 102.0, 118.0], [44.0, 46.0, 68.0]).astype(np.float32)
                            pane_c[p_inz > (p_zhi - 0.07)] *= 0.62  # Recessed upper window lintel shadow
                            pane_c[mullion] = [184.0, 174.0, 162.0]
                            pane_c[lit_dusk] = [255.0, 206.0, 114.0]
                            w_base[p_local] = pane_c
                            f_mat[p_global] = np.where(lit_dusk, M_WINDOW_LIT, M_WINDOW_DAY)
                        else:
                            mullion = np.abs(p_bco) < 0.08
                            upper_glint = p_inz > 0.56
                            pane_c = np.where(upper_glint[:, None], [78.0, 108.0, 138.0], [38.0, 52.0, 72.0]).astype(np.float32)
                            pane_c[p_inz > (p_zhi - 0.07)] *= 0.62  # Recessed upper window lintel shadow
                            pane_c[mullion] = [188.0, 184.0, 176.0]
                            w_base[p_local] = pane_c
                            f_mat[p_global] = M_WINDOW_DAY

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
                    shop_area = is_shop_gf & (r_h >= 0.22) & (r_h <= 2.95)
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

                f_col[wi] = w_base

            zbuf[fy, fx] = fd
            rgb_buf[fy, fx] = f_col
            mat_buf[fy, fx] = f_mat
            obj_buf[fy, fx] = bi + 1
            norm_buf[fy, fx] = f_norm

            # F8: Authentic cast-shadow receiving on building roofs & walls from taller neighbors/towers/trees!
            if ray_rel_05m is not None:
                bc05 = np.clip(((fe - E_MIN) * 2.0).astype(np.int32), 0, GRID_W - 1)
                br05 = np.clip(((N_MAX - fn) * 2.0).astype(np.int32), 0, GRID_H - 1)
                blocker_z = scene.dem[br05, bc05] + ray_rel_05m[br05, bc05].astype(np.float32)
                shadow_buf[fy, fx] = (blocker_z > (fz + 1.8)) & (f_mat != M_WINDOW_LIT)
            else:
                shadow_buf[fy, fx] = False

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
                    zs = np.arange(b["z_ground"], b["z_roof"] - 0.2, max(0.3, camera.mpp * 0.5))
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
                ns_p = max(4, int(math.ceil(dist_s / max(0.18, camera.mpp * 0.65))) + 1)
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
            # Suppress over bright white or blue-tinted 25cm skylights/atriums!
            c25 = int(np.clip((ep - E_MIN) / ORTHO25_RES, 1, ORTHO25_W - 2))
            r25 = int(np.clip((N_MAX - np_c) / ORTHO25_RES, 1, ORTHO25_H - 2))
            patch25 = np.asarray(scene.ortho_25cm[r25 - 1 : r25 + 2, c25 - 1 : c25 + 2], dtype=np.float32)
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
        # F8: Building roof/wall cast shadows use 0.24 ambient-bounce factor; ground uses 0.14
        sh_fac = np.where((m_here == M_ROOF) | (m_here == M_WALL), 0.24, 0.14).astype(np.float32)
        ndotl = np.where(shadow_buf[ay, ax], ndotl * sh_fac, ndotl)
        ndotl_step = np.round(ndotl * 6.0) / 6.0

        amb = np.array(preset.amb_rgb, dtype=np.float32)
        sun_c = np.array(preset.sun_rgb, dtype=np.float32)
        sky_dome = (0.5 + 0.5 * np.clip(n_xyz[:, 2], -1.0, 1.0))[:, None]
        lit_mult = amb[None, :] * (0.72 + 0.28 * sky_dome) + sun_c[None, :] * ndotl_step[:, None] * 0.67

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

        # F7: Emissive lit windows, shopfronts, signs & streetlamp globes (Night full, Sunset dusk warm!)
        is_emissive = m_here == M_WINDOW_LIT
        if is_emissive.any():
            if preset.is_night:
                shaded[is_emissive] = base_f[is_emissive]
            elif preset_key == "sunset":
                shaded[is_emissive] = 0.88 * base_f[is_emissive] + 0.12 * shaded[is_emissive]

        rgb_buf[ay, ax] = np.clip(shaded, 0.0, 255.0)

    # F7: Subtle underwater turquoise-teal glow on Seebad Kilchberg pool ONLY at Night!
    if preset.is_night:
        sb_c_e = np.array([2684235.0, 2684310.0, 2684235.0, 2684310.0])
        sb_c_n = np.array([1241435.0, 1241435.0, 1241525.0, 1241525.0])
        spx, spy, _ = camera.project(sb_c_e, sb_c_n, np.full(4, 407.5))
        sb_x0 = max(0, int(math.floor(float(spx.min() + shift_x))) - 2)
        sb_x1 = min(W, int(math.ceil(float(spx.max() + shift_x))) + 2)
        sb_y0 = max(0, int(math.floor(float(spy.min() + shift_y))) - 2)
        sb_y1 = min(H, int(math.ceil(float(spy.max() + shift_y))) + 2)
        if sb_x1 > sb_x0 and sb_y1 > sb_y0:
            sub_rgb_sb = rgb_buf[sb_y0:sb_y1, sb_x0:sb_x1]
            sub_m_sb = mat_buf[sb_y0:sb_y1, sb_x0:sb_x1]
            is_sb_pool = (sub_m_sb == M_GROUND) & (sub_rgb_sb[:, :, 2] > (sub_rgb_sb[:, :, 0] + 10.0)) & (sub_rgb_sb[:, :, 1] > (sub_rgb_sb[:, :, 0] + 8.0))
            if is_sb_pool.any():
                sub_rgb_sb[is_sb_pool] = np.clip(sub_rgb_sb[is_sb_pool] * np.array([1.25, 1.85, 1.75], dtype=np.float32), 0.0, 255.0)

    # F7: Architectural Landmark Uplighting (Night full, Sunset 0.25x) via exact obj_buf!
    if preset_key in ("night", "sunset"):
        up_scale = 1.0 if preset.is_night else 0.25
        up_targets = (
            (id_ref_kirche,  np.array([112.0, 78.0, 34.0], dtype=np.float32), 0.55),
            (id_lindt_hoc,   np.array([118.0, 84.0, 38.0], dtype=np.float32), 0.42),
            (id_lindt_chim,  np.array([98.0,  66.0, 28.0], dtype=np.float32), 0.50),
            (id_st_el_twr,   np.array([94.0,  64.0, 28.0], dtype=np.float32), 0.45),
            (id_bhf_stn,     np.array([76.0,  52.0, 22.0], dtype=np.float32), 0.35),
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

    # F8: Fast Vectorized zbuf Screen-Space Contact Ambient Occlusion (0.35m < dz < 5.5m, ZERO sky halos!)
    occ_sum = np.zeros((H, W), dtype=np.float32)
    z_valid = zbuf < 1e8
    for dy_ao, dx_ao, w_ao in (
        (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
        (-2, -1, 0.5), (-2, 1, 0.5), (2, -1, 0.5), (2, 1, 0.5),
    ):
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
    ao_str = 0.11 if preset.is_night else 0.14
    ao_fac = 1.0 - np.clip(occ_sum / 5.5, 0.0, 1.0) * ao_str
    rgb_buf[ao_recv] *= ao_fac[ao_recv, None]
    del occ_sum, ao_fac, z_valid

    # F7: World-Projected Warm Sodium-Amber Streetlamp Ground Pools + Lantern-Head Air Bloom (Night & Sunset!)
    if preset_key in ("night", "sunset") and len(scene.lamp_e) > 0:
        pool_scale = 1.0 if preset.is_night else 0.32
        px_lb, py_lb, pd_lb = camera.project(scene.lamp_e, scene.lamp_n, scene.lamp_z)
        sx_lb = px_lb + shift_x
        sy_lb = py_lb + shift_y
        in_lvp = (sx_lb >= -28.0) & (sx_lb <= W + 28.0) & (sy_lb >= -28.0) & (sy_lb <= H + 28.0)
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
                rx_p = (26.0 if lk_i in (0, 1) else 21.0) if preset.is_night else (20.0 if lk_i in (0, 1) else 16.0)
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
                # Soft 6px warm air bloom around lantern head itself (only when lantern bulb is unoccluded!)
                h_pole = 4.8 if lk_i in (0, 1) else (4.2 if lk_i == 2 else 3.6)
                px_h, py_h, pd_h = camera.project(np.array([le_i]), np.array([ln_i]), np.array([lz_i + h_pole]))
                hx_f, hy_f, hd_f = float(px_h[0] + shift_x), float(py_h[0] + shift_y), float(pd_h[0])
                hi_x, hi_y = int(round(hx_f)), int(round(hy_f))
                if 0 <= hi_x < W and 0 <= hi_y < H and zbuf[hi_y, hi_x] >= (hd_f - 1.5):
                    rb_h = 6
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

    # F7: Subtle Warm Window-Spill Glow Halos on Surrounding Facades & Ground (Night full, Sunset 0.38x!)
    if preset_key in ("night", "sunset"):
        lit_mask = mat_buf == M_WINDOW_LIT
        if lit_mask.any():
            halo = ndimage.gaussian_filter(lit_mask.astype(np.float32), sigma=1.75, truncate=3.0)
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
        D_MAX_REFL = 28
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

    _apply_pixel_art_outlines_float(rgb_buf, zbuf, obj_buf, mat_buf, norm_buf, preset.is_night)

    dither_map = bayer_tiled.copy()
    clean_m = np.isin(mat_buf, [M_WALL, M_WINDOW_LIT, M_WINDOW_DAY, M_BG, M_TREE, M_BRIDGE])
    dither_map[clean_m] *= 0.28

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
) -> None:
    """Apply refined 1px 90s selective pixel-art outlines (sel-out) on buildings, viaducts, trees & roof ridges.
    F14a: Splits tree outlines into crisp tree-against-world edges vs softer interior overlapping forest edges!"""
    dz_r = zbuf[:, 1:] - zbuf[:, :-1]
    dz_d = zbuf[1:, :] - zbuf[:-1, :]
    diff_r = obj_buf[:, 1:] != obj_buf[:, :-1]
    diff_d = obj_buf[1:, :] != obj_buf[:-1, :]

    is_bldg_or_br = (mat_buf == M_WALL) | (mat_buf == M_ROOF) | (mat_buf == M_BRIDGE) | (mat_buf == M_HARBOR_OBJ)
    is_tree_m = mat_buf == M_TREE

    bldg_edge = np.zeros(zbuf.shape, dtype=np.bool_)
    bldg_edge[:, :-1] |= diff_r & (dz_r > 0.65) & is_bldg_or_br[:, :-1]
    bldg_edge[:, 1:] |= diff_r & (dz_r < -0.65) & is_bldg_or_br[:, 1:]
    bldg_edge[:-1, :] |= diff_d & (dz_d > 0.65) & is_bldg_or_br[:-1, :]
    bldg_edge[1:, :] |= diff_d & (dz_d < -0.65) & is_bldg_or_br[1:, :]

    eave_d = (obj_buf[:-1, :] == obj_buf[1:, :]) & (mat_buf[:-1, :] == M_ROOF) & (mat_buf[1:, :] == M_WALL)
    bldg_edge[:-1, :] |= eave_d

    # Split tree outlines: interior forest canopy overlap (obj >= 100000 on both sides) vs world silhouette!
    both_trees_r = (obj_buf[:, :-1] >= 100000) & (obj_buf[:, 1:] >= 100000) & (obj_buf[:, :-1] < 200000) & (obj_buf[:, 1:] < 200000)
    both_trees_d = (obj_buf[:-1, :] >= 100000) & (obj_buf[1:, :] >= 100000) & (obj_buf[:-1, :] < 200000) & (obj_buf[1:, :] < 200000)

    tree_world_edge = np.zeros(zbuf.shape, dtype=np.bool_)
    tree_world_edge[:, :-1] |= diff_r & (~both_trees_r) & (dz_r > 0.95) & is_tree_m[:, :-1]
    tree_world_edge[:, 1:] |= diff_r & (~both_trees_r) & (dz_r < -0.95) & is_tree_m[:, 1:]
    tree_world_edge[:-1, :] |= diff_d & (~both_trees_d) & (dz_d > 0.95) & is_tree_m[:-1, :]
    tree_world_edge[1:, :] |= diff_d & (~both_trees_d) & (dz_d < -0.95) & is_tree_m[1:, :]

    tree_inner_edge = np.zeros(zbuf.shape, dtype=np.bool_)
    tree_inner_edge[:, :-1] |= diff_r & both_trees_r & (dz_r > 1.35) & is_tree_m[:, :-1]
    tree_inner_edge[:, 1:] |= diff_r & both_trees_r & (dz_r < -1.35) & is_tree_m[:, 1:]
    tree_inner_edge[:-1, :] |= diff_d & both_trees_d & (dz_d > 1.35) & is_tree_m[:-1, :]
    tree_inner_edge[1:, :] |= diff_d & both_trees_d & (dz_d < -1.35) & is_tree_m[1:, :]
    tree_inner_edge &= ~tree_world_edge

    if bldg_edge.any():
        ey, ex = np.nonzero(bldg_edge)
        rgb_buf[ey, ex] *= 0.58 if not is_night else 0.62
    if tree_world_edge.any():
        ty, tx = np.nonzero(tree_world_edge)
        rgb_buf[ty, tx] *= np.array([0.64, 0.72, 0.70], dtype=np.float32) if not is_night else 0.72
    if tree_inner_edge.any():
        iy_t, ix_t = np.nonzero(tree_inner_edge)
        rgb_buf[iy_t, ix_t] *= np.array([0.82, 0.87, 0.85], dtype=np.float32) if not is_night else 0.86

    island_fg = mat_buf > M_DROP_SHADOW
    island_border = island_fg & (~ndimage.binary_erosion(island_fg, iterations=1, border_value=0))
    if island_border.any():
        by, bx = np.nonzero(island_border)
        rgb_buf[by, bx] *= 0.44

    if not is_night:
        roof_m = mat_buf == M_ROOF
        ndot = (
            norm_buf[:-1, :, 0] * norm_buf[1:, :, 0]
            + norm_buf[:-1, :, 1] * norm_buf[1:, :, 1]
            + norm_buf[:-1, :, 2] * norm_buf[1:, :, 2]
        )
        same_b = (obj_buf[:-1, :] == obj_buf[1:, :]) & roof_m[:-1, :] & roof_m[1:, :]
        ridge = same_b & (ndot < 0.86) & (np.abs(zbuf[:-1, :] - zbuf[1:, :]) < 1.6)
        if ridge.any():
            ry, rx = np.nonzero(ridge)
            rgb_buf[ry, rx] = np.minimum(255.0, rgb_buf[ry, rx] + 28.0)


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
            "ortho_res_cm": 25,
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

    lg_px = min(38, max(18, W // 180))
    sm_px = min(24, max(13, W // 290))
    xs_px = max(11, sm_px - 2)
    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", lg_px)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", sm_px)
        font_xs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", xs_px)
    except Exception:
        font_lg = ImageFont.load_default()
        font_sm = ImageFont.load_default()
        font_xs = font_sm

    border_outer = (88, 98, 118) if not preset.is_night else (58, 72, 102)
    border_inner = (182, 166, 134) if not preset.is_night else (148, 126, 88)
    draw.rectangle([10, 10, W - 11, H - 11], outline=border_outer, width=2)
    draw.rectangle([16, 16, W - 17, H - 17], outline=border_inner, width=1)

    # F13: Brass Corner Registration L-Brackets & Diamond Center Dots
    tick = 18 if W >= 4000 else 12
    for (cx_c, cy_c, sx_c, sy_c) in (
        (16, 16, 1, 1), (W - 17, 16, -1, 1), (16, H - 17, 1, -1), (W - 17, H - 17, -1, -1)
    ):
        draw.line([(cx_c, cy_c), (cx_c + sx_c * tick, cy_c)], fill=border_inner, width=2)
        draw.line([(cx_c, cy_c), (cx_c, cy_c + sy_c * tick)], fill=border_inner, width=2)
        dx_d, dy_d = cx_c + sx_c * 6, cy_c + sy_c * 6
        draw.polygon([(dx_d, dy_d - 2), (dx_d + 2, dy_d), (dx_d, dy_d + 2), (dx_d - 2, dy_d)], fill=border_inner)

    sw = lg_px + sm_px + 10
    sx0, sy0 = 36, 30
    draw.rectangle([sx0, sy0, sx0 + sw, sy0 + sw], fill=(208, 38, 38), outline=(246, 243, 236), width=2)
    arm_w = max(4, sw // 4)
    arm_l = int(sw * 0.62)
    cx_s, cy_s = sx0 + sw // 2, sy0 + sw // 2
    draw.rectangle([cx_s - arm_w // 2, cy_s - arm_l // 2, cx_s + arm_w // 2, cy_s + arm_l // 2], fill=(250, 250, 248))
    draw.rectangle([cx_s - arm_l // 2, cy_s - arm_w // 2, cx_s + arm_l // 2, cy_s + arm_w // 2], fill=(250, 250, 248))

    title = plate_title if plate_title else "KILCHBERG ZH  —  90s 3D ISOMETRIC PIXEL ART DIORAMA"
    if plate_subtitle:
        sub = f"{plate_subtitle}  |  {preset.name.upper()}  |  {camera.mpp:.2f} m/px  |  256-COLOR SVGA"
    else:
        sub = (
            f"256-COLOR SVGA PALETTE  |  {preset.name.upper()}  |  {camera.mpp:.2f} m/px  |  "
            f"{n_bldgs:,} LOD2 3D BUILDINGS  ·  {n_trees:,} 3D TREES  ·  SWISSTOPO GIS"
        )
    tx = sx0 + sw + 18
    draw.text((tx, sy0), title, fill=(246, 241, 228), font=font_lg)
    draw.text((tx, sy0 + lg_px + 8), sub, fill=(176, 188, 206), font=font_sm)

    # F13: Exact Projected Isometric Compass Rose (upper-right margin) showing true North & ESE -> WNW sightline!
    r_cr = 34 if W >= 5000 else 24
    cr_x = W - 46 - r_cr
    cr_y = 32 + r_cr
    # Project unit North (0, +1) and unit East (+1, 0) through camera.project() for exact geometric bearing!
    p0x, p0y, _ = camera.project(np.array([0.0]), np.array([0.0]), np.array([0.0]))
    pnx_c, pny_c, _ = camera.project(np.array([0.0]), np.array([10.0]), np.array([0.0]))
    pex_c, pey_c, _ = camera.project(np.array([10.0]), np.array([0.0]), np.array([0.0]))
    vnx, vny = float(pnx_c[0] - p0x[0]), float(pny_c[0] - p0y[0])
    vn_len = max(1e-5, math.hypot(vnx, vny))
    vnx, vny = vnx / vn_len, vny / vn_len
    vex, vey = float(pex_c[0] - p0x[0]), float(pey_c[0] - p0y[0])
    ve_len = max(1e-5, math.hypot(vex, vey))
    vex, vey = vex / ve_len, vey / ve_len
    draw.ellipse([cr_x - r_cr, cr_y - r_cr, cr_x + r_cr, cr_y + r_cr], outline=border_inner, width=1)
    # Subtle East-West cross axis
    draw.line(
        [(cr_x - vex * r_cr * 0.72, cr_y - vey * r_cr * 0.72), (cr_x + vex * r_cr * 0.72, cr_y + vey * r_cr * 0.72)],
        fill=(146, 156, 174), width=1,
    )
    # South tail (ivory) & bold North arrowhead (Swiss crimson!)
    draw.line([(cr_x, cr_y), (cr_x - vnx * r_cr * 0.72, cr_y - vny * r_cr * 0.72)], fill=(196, 192, 182), width=2)
    tip_x, tip_y = cr_x + vnx * r_cr * 0.92, cr_y + vny * r_cr * 0.92
    perp_x, perp_y = -vny * 4.5, vnx * 4.5
    draw.polygon(
        [(tip_x, tip_y), (cr_x + perp_x, cr_y + perp_y), (cr_x - perp_x, cr_y - perp_y)],
        fill=(216, 48, 44), outline=(246, 241, 228),
    )
    draw.text((int(tip_x + vnx * 7 - 4), int(tip_y + vny * 7 - 7)), "N", fill=(246, 241, 228), font=font_xs)
    draw.text((cr_x - r_cr - 14, cr_y + r_cr + 5), "ESE → WNW", fill=(168, 178, 196), font=font_xs)

    # 4-segment alternating Swiss Scale Bar with 0 / mid / max ticks
    bar_m = 100 if crop_box_lv95 is not None else 250
    bar_px = int(round(bar_m / camera.mpp))
    bx1 = W - 42
    bx0 = bx1 - bar_px
    by = H - 40
    seg_w = bar_px / 4.0
    for si_b in range(4):
        sx_a = int(round(bx0 + si_b * seg_w))
        sx_b = int(round(bx0 + (si_b + 1) * seg_w))
        c_seg = (208, 48, 44) if (si_b % 2 == 0) else (238, 232, 218)
        draw.rectangle([sx_a, by - 7, sx_b, by], fill=c_seg, outline=(32, 38, 48), width=1)
    lbl_y = by - 26
    draw.text((bx0, lbl_y), "0", fill=(214, 220, 230), font=font_sm)
    mid_txt = f"{bar_m // 2}"
    draw.text((bx0 + bar_px // 2 - len(mid_txt) * (sm_px // 4), lbl_y), mid_txt, fill=(214, 220, 230), font=font_sm)
    end_txt = f"{bar_m} m"
    draw.text((bx1 - len(end_txt) * (sm_px * 6 // 10), lbl_y), end_txt, fill=(214, 220, 230), font=font_sm)

    credit = "DATA: © SWISSTOPO (SWISSALTI3D 2026 · SWISSBUILDINGS3D 3.0 2025 · SWISSSURFACE3D 0.5m · SWISSIMAGE DOP10 2025 · SWISSBATHY3D)"
    draw.text((36, H - 44), credit, fill=(148, 160, 180), font=font_sm)
    return img


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
) -> dict:
    """Render ultra-high-resolution (~70 MP at 0.25 m/px) full municipality in memory-safe
    seamless screen windows, slice lossless 1024x1024 WebP tiles for deep-zoom web streaming,
    and save overview WebP + GitHub-friendly full PNG."""
    import gc

    preset = PRESETS[preset_key]
    cam = IsometricCamera(mpp=mpp)
    (
        cam,
        _,
        _,
        W_full,
        H_full,
        shift_x_full,
        shift_y_full,
        *_,
    ) = compute_full_canvas_geometry(scene, cam, None, True)

    sun_sh = compute_shadow_grid(scene, preset.sun_az_deg, preset.sun_alt_deg)
    full_rgb = None if depth_only else np.empty((H_full, W_full, 3), dtype=np.uint8)

    # Export 1/2-res (0.5 m/px -> 6165x2722!) 16-bit 3D Depth & Occluder Map during 'day' pass
    # (geometry is identical across day/sunset/night!) for pixel-exact partial vehicle occlusion!
    DEPTH_DS = 2
    DEPTH_MIN = -2400.0
    DEPTH_MAX = 2400.0
    save_depth = (preset_key == "day") or depth_only
    if save_depth:
        dw_f = W_full // DEPTH_DS
        dh_f = H_full // DEPTH_DS
        depth_rgb = np.zeros((dh_f, dw_f, 3), dtype=np.uint8)
        depth_rgb[:, :, 0] = 255
        depth_rgb[:, :, 1] = 255

    # F7/F8/F9: Asymmetric guard padding (guard_x=24, guard_y=56) guarantees ZERO macro-tile seams
    # across 20px streetlamp pools, 10px Gaussian halos, 2px contact AO, and 28+24=52px shoreline reflections!
    nx_macro, ny_macro = 6, 3
    guard_x, guard_y = 24, 56
    for my in range(ny_macro):
        y0 = (my * H_full) // ny_macro
        y1 = ((my + 1) * H_full) // ny_macro
        for mx in range(nx_macro):
            x0 = (mx * W_full) // nx_macro
            x1 = ((mx + 1) * W_full) // nx_macro

            wx0 = max(0, x0 - guard_x)
            wy0 = max(0, y0 - guard_y)
            wx1 = min(W_full, x1 + guard_x)
            wy1 = min(H_full, y1 + guard_y)

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

            if save_depth and dbuf:
                # Sample exact 3D occluder depth at 1/2 resolution for this macro window
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
                    has_occ = occ_cnt >= 2
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

    if save_depth:
        depth_path = overview_webp_path.parent / "kilchberg_depth.png"
        Image.fromarray(depth_rgb, mode="RGB").save(depth_path, optimize=True)
        print(f"[render] Saved 16-bit 3D Depth & Occluder Map -> {depth_path} ({dw_f}x{dh_f})")
        del depth_rgb
    if depth_only:
        gc.collect()
        return {}

    master_img = Image.fromarray(full_rgb, mode="RGB")
    del full_rgb
    gc.collect()

    master_img = _draw_museum_cartouche(master_img, preset, cam, len(scene.buildings), len(scene.tree_e), None)

    tiles_dir.mkdir(parents=True, exist_ok=True)
    cols = int(math.ceil(W_full / tile_size))
    rows = int(math.ceil(H_full / tile_size))
    for r in range(rows):
        ty0 = r * tile_size
        ty1 = min(H_full, ty0 + tile_size)
        for c in range(cols):
            tx0 = c * tile_size
            tx1 = min(W_full, tx0 + tile_size)
            tile_im = master_img.crop((tx0, ty0, tx1, ty1))
            tile_im.save(tiles_dir / f"{c}_{r}.webp", format="WEBP", lossless=True, method=4)

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
    }
    (tiles_dir / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))

    ov_w = W_full // 2
    ov_h = H_full // 2
    ov_img = master_img.resize((ov_w, ov_h), resample=Image.Resampling.LANCZOS)
    ov_img.save(overview_webp_path, format="WEBP", quality=94, method=4)

    ov_img.save(full_png_path, optimize=True)

    hit_data = {}
    if collect_hit_boxes:
        hit_data = _extract_interactive_metadata(scene, cam, shift_x_full, shift_y_full, W_full, H_full)

    del master_img, ov_img
    gc.collect()
    return hit_data
