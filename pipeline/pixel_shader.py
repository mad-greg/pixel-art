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
        sun_rgb=(1.14, 0.77, 0.50),
        amb_rgb=(0.42, 0.39, 0.53),
        sky_top_rgb=(34, 26, 48),
        sky_bot_rgb=(70, 44, 60),
        is_night=False,
        dither_strength=8.5,
    ),
    "night": LightingPreset(
        name="Zürichsee Lantern Night",
        sun_az_deg=128.0,
        sun_alt_deg=36.0,
        sun_rgb=(0.32, 0.40, 0.62),
        amb_rgb=(0.23, 0.28, 0.45),
        sky_top_rgb=(12, 17, 30),
        sky_bot_rgb=(20, 28, 48),
        is_night=True,
        dither_strength=7.5,
    ),
}


@lru_cache(maxsize=1)
def build_90s_palette_and_lut() -> tuple[np.ndarray, np.ndarray]:
    """Construct a luminous curated 256-color 90s SVGA isometric city-builder palette calibrated to
    Swiss architecture, Roland-Garros clay courts, lush alpine meadows, botanical trees & Zürichsee."""
    colors = []

    def add_ramp(c_dark, c_mid, c_light, n):
        c0 = np.array(c_dark, dtype=np.float32)
        c1 = np.array(c_mid, dtype=np.float32)
        c2 = np.array(c_light, dtype=np.float32)
        for i in range(n):
            t = i / max(1, n - 1)
            if t < 0.5:
                u = t * 2.0
                c = (1 - u) * c0 + u * c1
            else:
                u = (t - 0.5) * 2.0
                c = (1 - u) * c1 + u * c2
            colors.append(np.clip(np.round(c), 0, 255).astype(np.uint8))

    # 1. Lush 90s Pixel-Art Swiss Foliage, Stadium Turf, Meadows & Blossoms — 48 colors
    add_ramp((14, 34, 22), (44, 102, 46), (126, 190, 78), 11)   # Deep emerald oak / stadium turf
    add_ramp((20, 42, 24), (62, 126, 52), (156, 208, 92), 10)   # Sunlit meadow / linden / bright grass
    add_ramp((14, 34, 30), (32, 76, 56), (80, 138, 94), 8)      # Alpine spruce / fir / dark yew hedges
    add_ramp((38, 46, 24), (94, 118, 52), (168, 184, 92), 8)    # Warm sage upland meadow, sedum & vineyards
    add_ramp((36, 18, 26), (88, 38, 46), (144, 68, 72), 5)      # Refined estate copper beech (Blutbuche)
    add_ramp((124, 72, 82), (218, 162, 174), (252, 232, 238), 6)# Spring cherry & apple tree blossoms

    # 2. Clinker Brick, Clay Roofs, Roland-Garros Tennis Clay, Neutral Concrete & PV — 50 colors
    add_ramp((44, 16, 14), (132, 46, 36), (186, 72, 52), 8)     # Deep Swiss ziegelrot clinker & 1899 red brick
    add_ramp((54, 24, 16), (162, 78, 48), (222, 122, 74), 9)    # Classic Swiss terracotta clay roof & tennis clay
    add_ramp((40, 26, 18), (112, 74, 52), (180, 132, 98), 8)    # Weathered brown clay tile & dark barn timber
    add_ramp((22, 24, 28), (102, 104, 108), (236, 238, 240), 10)# Pure neutral slate / concrete / white pitch lines
    add_ramp((18, 28, 50), (42, 64, 108), (94, 134, 188), 7)    # Crisp rooftop solar PV arrays & skylights
    add_ramp((48, 44, 38), (136, 128, 114), (202, 194, 178), 8) # Pebble-greige stucco & Jura limestone pavers

    # 3. Swiss Plaster Facades, Butter-Ochre, Dusty Rose, Sage Green & Shutters — 48 colors
    add_ramp((54, 52, 54), (158, 154, 146), (246, 244, 238), 9) # Glazed white brick, alabaster & off-white plaster
    add_ramp((54, 44, 32), (154, 138, 110), (228, 214, 184), 9) # Warm travertine, sand & cream stucco
    add_ramp((64, 48, 22), (176, 146, 68), (246, 220, 116), 9)  # Butter-yellow villas, wildflowers, gold & crosswalks
    add_ramp((58, 36, 34), (152, 108, 94), (218, 176, 158), 7)  # Historic dusty rose / terracotta-salmon stucco
    add_ramp((26, 48, 42), (76, 124, 108), (158, 192, 172), 6)  # Sage/pistachio pavilion, copper patina & teal shutters
    add_ramp((18, 26, 40), (54, 84, 126), (122, 160, 208), 8)   # Window glass & cornflower/dove-blue Swiss shutters

    # 4. Streets, Asphalt, Courtyards, Railway Ballast & Cutaway Strata — 26 colors
    add_ramp((18, 20, 26), (78, 82, 90), (194, 196, 200), 14)    # Asphalt -> concrete -> crisp markings
    add_ramp((34, 30, 26), (98, 88, 74), (176, 162, 140), 12)    # Molasse sandstone, gravel & ballast

    # 5. Authentic Alpine Lake Zurich (Zürichsee jade-emerald -> deep alpine blue-teal) + Pools — 38 colors
    add_ramp((12, 24, 34), (24, 62, 82), (44, 102, 114), 13)     # Deep alpine Zürichsee blue-teal
    add_ramp((28, 52, 48), (56, 108, 96), (118, 172, 154), 13)   # Nearshore Zürichsee jade-olive & shallows
    add_ramp((32, 104, 138), (68, 184, 214), (196, 242, 248), 12)# Crystal swimming pools & shore foam

    # 6. Sunset Alpenglow, Night Twilight, Lantern Golds & Swiss Crest Red — 46 colors
    add_ramp((12, 16, 30), (34, 42, 68), (76, 88, 126), 12)      # Night indigo shadows & backdrop
    add_ramp((34, 24, 46), (86, 52, 68), (178, 104, 88), 12)     # Sunset violet-rose alpenglow
    add_ramp((92, 58, 24), (212, 148, 54), (255, 238, 166), 12)  # Lit amber/gold windows & lamps
    add_ramp((96, 20, 20), (196, 38, 38), (248, 96, 88), 10)     # Swiss crest red & harbor buoys

    pal = np.array(colors[:256], dtype=np.uint8)
    assert len(pal) == 256, f"Expected 256 palette colors, got {len(pal)}"

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


def quantize_to_90s_palette(rgb_float: np.ndarray, bayer_2d: np.ndarray, strength: float) -> np.ndarray:
    """Apply ordered 4x4 Bayer dithering and quantize strictly into the 256-color 90s SVGA palette."""
    pal, lut = build_90s_palette_and_lut()
    dithered = np.clip(rgb_float + bayer_2d[:, :, None] * strength, 0.0, 255.0)
    ri = np.round(dithered[:, :, 0] * (63.0 / 255.0)).astype(np.int32)
    gi = np.round(dithered[:, :, 1] * (63.0 / 255.0)).astype(np.int32)
    bi = np.round(dithered[:, :, 2] * (63.0 / 255.0)).astype(np.int32)
    idx = lut[ri, gi, bi]
    return pal[idx]


class SceneData:
    """Loaded Kilchberg 0.5m rasters, 3D bridges/viaducts, 25cm parapet masks, 3D LOD2 buildings, sports & trees."""

    def __init__(self, cache_dir: Path = RAW_CACHE_DIR):
        s = np.load(cache_dir / "scene_kilchberg_05m.npz")
        self.dem = s["dem"].astype(np.float32)
        self.chm = s["chm"].astype(np.float32)
        self.ortho_05m = s["ortho"]
        self.sem = s["sem"]
        self.diorama_mask = s["diorama_mask"]
        self.kpoly_mask = s["kpoly_mask"]
        self.lake_mask = s["lake_mask"]
        self.bathy_z = s["bathy_z"].astype(np.float32)

        # V3 vector road/rail/bridge/tree layers
        self.rail_dist = s["rail_dist"].astype(np.float32)
        self.rail_along = s["rail_along"].astype(np.float32)
        self.rail_ang = s["rail_ang"].astype(np.float32)
        self.road_dist = s["road_dist"].astype(np.float32)
        self.road_along = s["road_along"].astype(np.float32)
        self.road_hw = s["road_hw"].astype(np.float32)
        self.road_ang = s["road_ang"].astype(np.float32)
        self.crosswalk_mask = s["crosswalk_mask"] > 0

        self.bridge_cls = s["bridge_cls"]
        self.bridge_z = s["bridge_z"].astype(np.float32)
        self.bridge_sdist = s["bridge_sdist"].astype(np.float32)
        self.bridge_along = s["bridge_along"].astype(np.float32)
        self.bridge_hw = s["bridge_hw"].astype(np.float32)
        self.bridge_ang = s["bridge_ang"].astype(np.float32)
        self.bridge_id = s["bridge_id"]
        self.hedge_mask = s["hedge_mask"] > 0

        self.tree_e = s["tree_e"].astype(np.float32)
        self.tree_n = s["tree_n"].astype(np.float32)
        self.tree_z = s["tree_z"].astype(np.float32)
        self.tree_h = s["tree_h"].astype(np.float32)
        self.tree_rad = s["tree_rad"].astype(np.float32)
        self.tree_species = s["tree_species"].astype(np.uint8)

        self.ortho_25cm = np.load(cache_dir / "ortho_25cm.npy", mmap_mode="r")
        self.roof_edge_25cm = np.load(cache_dir / "roof_edge_step_25cm.npy", mmap_mode="r")
        raw_rmask = np.load(cache_dir / "bldg_roof_mask_05m.npy")
        self.bldg_roof_mask = ndimage.binary_dilation(raw_rmask, iterations=2)

        b = np.load(cache_dir / "buildings_kilchberg_3d.npz")
        self.verts = b["verts"]
        self.normals = b["normals"]
        self.bldg_idx = b["bldg_idx"]
        self.surf_type = b["surf_type"]

        meta = json.loads((cache_dir / "buildings_kilchberg_meta.json").read_text())
        self.buildings = meta["buildings"]
        self.boats = meta["boats"]
        self.viaduct_piers = meta.get("viaduct_piers", [])
        self.catenary_portals = meta.get("catenary_portals", [])
        self.sports_fields = meta.get("sports_fields", [])
        self.sports_enclosures = meta.get("sports_enclosures", [])

        # Precompute 0.5m bare-earth terrain normals
        dz_drow, dz_dcol = np.gradient(ndimage.gaussian_filter(self.dem, sigma=0.75), GRID_RES)
        nx, ny, nz = -dz_dcol, dz_drow, np.ones_like(dz_dcol)
        nlen = np.sqrt(nx * nx + ny * ny + nz * nz)
        self.terr_nx = (nx / nlen).astype(np.float32)
        self.terr_ny = (ny / nlen).astype(np.float32)
        self.terr_nz = (nz / nlen).astype(np.float32)

        # V6.0: Multi-scale smooth organic alpine meadow variation field (kills artificial mowing stripes!)
        rng_m = np.random.default_rng(1350135)
        raw_n = rng_m.standard_normal((GRID_H // 4 + 2, GRID_W // 4 + 2)).astype(np.float32)
        coarse_n = ndimage.gaussian_filter(raw_n, sigma=6.5)
        med_n = ndimage.gaussian_filter(raw_n, sigma=2.0)
        comb_n = 0.65 * coarse_n + 0.35 * med_n
        comb_n = (comb_n - comb_n.mean()) / max(1e-5, comb_n.std())
        self.meadow_noise_05m = np.repeat(np.repeat(comb_n, 4, axis=0), 4, axis=1)[:GRID_H, :GRID_W].astype(np.float32)

        # V6.0: Clean impervious residential courtyard / patio / driveway mask (0.5m)
        # Strictly requires proximity to buildings or streets AND bright neutral-grey concrete/stone
        # so shaded garden lawns & open Swiss meadows NEVER turn into dirty grey concrete soup!
        o_f = self.ortho_05m.astype(np.float32)
        lum05 = 0.299 * o_f[:, :, 0] + 0.587 * o_f[:, :, 1] + 0.114 * o_f[:, :, 2]
        chroma05 = o_f.max(axis=2) - o_f.min(axis=2)
        green_excess05 = o_f[:, :, 1] - 0.5 * (o_f[:, :, 0] + o_f[:, :, 2])
        near_urban = ndimage.binary_dilation(
            raw_rmask | np.isin(self.sem, [G_STREET_MAIN, G_STREET_MINOR, G_PARKING, G_PLATFORM_PIER]),
            iterations=14,  # within 7m of buildings or streets
        )
        raw_pave = (
            near_urban
            & (self.sem == G_TERRAIN)
            & (~self.lake_mask)
            & (lum05 > 128.0)
            & (chroma05 < 22.0)
            & (green_excess05 < 3.0)
        )
        # Smooth out noisy 1px gravel/shadow speckles into crisp clean paved patios & drives
        self.yard_pave_mask_05m = ndimage.binary_closing(
            ndimage.binary_opening(raw_pave, structure=np.ones((2, 2), dtype=bool)),
            structure=np.ones((3, 3), dtype=bool),
        )

        # V6.0: Crisp 0.5m white stone pool coping rim around every swimming pool
        is_pool_m = self.sem == G_POOL
        self.pool_rim_05m = ndimage.binary_dilation(is_pool_m, iterations=1) & (~is_pool_m) & (~self.lake_mask)

        # V6.0: Glitch-free 0.5m rooftop Solar PV mask (morphologically verified sunlit panels ONLY —
        # eliminates 100% of blue shadow static speckles on roofs!)
        raw_pv05 = (
            raw_rmask
            & (o_f[:, :, 2] > (o_f[:, :, 0] + 19.0))
            & (o_f[:, :, 2] > (o_f[:, :, 1] + 8.0))
            & (lum05 >= 38.0)
            & (lum05 <= 108.0)
        )
        opened_pv = ndimage.binary_opening(raw_pv05, structure=np.ones((3, 3), dtype=bool))
        lbl_pv, n_pv = ndimage.label(opened_pv)
        if n_pv > 0:
            pv_counts = np.bincount(lbl_pv.ravel())
            keep_pv = pv_counts >= 14  # >= 3.5 m^2 contiguous genuine PV array
            keep_pv[0] = False
            self.pv_clean_05m = ndimage.binary_closing(keep_pv[lbl_pv], structure=np.ones((2, 2), dtype=bool))
        else:
            self.pv_clean_05m = np.zeros((GRID_H, GRID_W), dtype=np.bool_)

        # Clean 0.5m mask of REAL moored boats, piers & Seebad rafts (strictly nearshore so open lake stays spotless!)
        bg_lum05 = ndimage.uniform_filter(lum05, size=29)
        near_shore = ndimage.binary_dilation(~self.lake_mask, iterations=190)  # within 95 m of shore
        open_water = ndimage.binary_erosion(self.lake_mask, iterations=1, border_value=0)
        is_pier = (self.sem == G_PLATFORM_PIER) & self.lake_mask
        is_lidar_obj = (
            open_water
            & near_shore
            & (~self.bldg_roof_mask)
            & (self.chm >= 0.45)
            & (self.chm <= 4.2)
            & (lum05 > 82.0)
            & ((o_f[:, :, 1] - o_f[:, :, 0]) < 8.0)
        )
        is_bright_float = (
            ndimage.binary_erosion(self.lake_mask, iterations=2, border_value=0)
            & near_shore
            & (~self.bldg_roof_mask)
            & (self.chm <= 4.2)
            & (lum05 > 114.0)
            & ((lum05 - bg_lum05) > 26.0)
            & ((o_f[:, :, 1] - o_f[:, :, 0]) < 10.0)
        )
        cand_float = (is_lidar_obj | is_bright_float) & (~is_pier)
        lbl_f, n_f = ndimage.label(cand_float)
        clean_float = np.zeros_like(cand_float)
        if n_f > 0:
            counts = np.bincount(lbl_f.ravel())
            valid_lbl = (counts >= 3) & (counts <= 1800)
            valid_lbl[0] = False
            clean_float = valid_lbl[lbl_f]
        self.harbor_obj_mask = is_pier | clean_float

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
                    # Rich jewel-like Swiss terracotta clay tile
                    warm = min(1.0, max(0.0, (rr - rg) / 34.0))
                    c_tile = np.array([162.0 + 30.0 * warm, 82.0 + 8.0 * warm, 56.0 - 4.0 * warm], dtype=np.float32)
                    self.bldg_clean_roof_rgb[i] = 0.65 * c_tile + 0.35 * np.clip([rr * 1.08, rg * 0.96, rb * 0.88], 48.0, 214.0)
                    self.bldg_roof_kind[i] = 0
                elif (rr - rb) >= 7.0:
                    # Warm weathered sienna-brown Swiss clay tile
                    c_brn = np.array([136.0, 92.0, 68.0], dtype=np.float32)
                    self.bldg_clean_roof_rgb[i] = 0.55 * c_brn + 0.45 * np.clip([rr * 1.04, rg * 0.96, rb * 0.90], 72.0, 184.0)
                    self.bldg_roof_kind[i] = 0
                else:
                    # Crisp alpine charcoal / slate tile (strictly neutral — zero accidental blue cast!)
                    base_sl = np.clip(lum_r * 0.94, 70.0, 138.0)
                    self.bldg_clean_roof_rgb[i] = [base_sl * 0.99, base_sl * 1.00, base_sl * 1.02]
                    self.bldg_roof_kind[i] = 1
            else:
                if (rg - rr) > 7.0 and (rg - rb) > 9.0:
                    # Lush sedum extensive green flat roof
                    self.bldg_clean_roof_rgb[i] = [106.0, 138.0, 74.0]
                    self.bldg_roof_kind[i] = 3
                elif lum_r > 158.0:
                    # Crisp light concrete / silver membrane flat roof
                    v_l = np.clip(lum_r, 158.0, 198.0)
                    self.bldg_clean_roof_rgb[i] = [v_l, v_l * 0.995, v_l * 0.985]
                    self.bldg_roof_kind[i] = 4
                else:
                    # Clean warm-neutral Swiss washed-pebble gravel flat roof
                    v_g = np.clip(lum_r * 1.04, 114.0, 168.0)
                    self.bldg_clean_roof_rgb[i] = [v_g * 1.02, v_g * 1.00, v_g * 0.97]
                    self.bldg_roof_kind[i] = 2

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


def compute_shadow_grid(scene: SceneData, sun_az_deg: float, sun_alt_deg: float) -> np.ndarray:
    """Ray-march 0.5m LiDAR DSM (real 3D buildings, elevated viaducts & trees) for crisp cast shadows."""
    h_surf = np.maximum(scene.dem + scene.chm, scene.bridge_z)[::2, ::2].copy()
    sh = np.zeros_like(h_surf, dtype=np.bool_)
    az = math.radians(sun_az_deg)
    alt = math.radians(sun_alt_deg)
    dcol = math.sin(az)
    drow = -math.cos(az)
    dz_per_m = math.tan(alt)

    H2, W2 = h_surf.shape
    for dist in np.linspace(2.0, 92.0, 30):
        sc = int(round(dcol * dist))
        sr = int(round(drow * dist))
        if sc == 0 and sr == 0:
            continue
        r0_src, r1_src = max(0, sr), min(H2, H2 + sr)
        c0_src, c1_src = max(0, sc), min(W2, W2 + sc)
        r0_dst, r1_dst = r0_src - sr, r1_src - sr
        c0_dst, c1_dst = c0_src - sc, c1_src - sc

        blocker = h_surf[r0_src:r1_src, c0_src:c1_src] - dz_per_m * dist
        sh[r0_dst:r1_dst, c0_dst:c1_dst] |= blocker > (h_surf[r0_dst:r1_dst, c0_dst:c1_dst] + 0.65)

    return np.repeat(np.repeat(sh, 2, axis=0), 2, axis=1)[:GRID_H, :GRID_W]


def _compute_building_facade_styles(scene: SceneData) -> tuple[np.ndarray, np.ndarray]:
    """Determine authentic Swiss facade RGB and architectural style code for each of the 1,890 buildings,
    verified against ground-level photographs of Lindt & Sprüngli, Schooren, Bendlikon & Kilchberg village."""
    buildings = scene.buildings
    n = len(buildings)
    wall_rgb = np.empty((n, 3), dtype=np.uint8)
    style_code = np.zeros(n, dtype=np.uint8)

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

    for i, b in enumerate(buildings):
        obj = b["objektart"]
        e, nc = b["e"], b["n"]
        h = b["height"]
        area_box = b["footprint_w"] * b["footprint_l"]
        h_seed = ((i * 73856093) ^ int(round(e * 13.0)) ^ int(round(nc * 29.0))) & 0x7FFFFFFF

        if obj == "Hochkamin":
            wall_rgb[i] = (194, 180, 148)
            style_code[i] = 5
        elif obj == "Lagertank":
            wall_rgb[i] = (196, 198, 202)
            style_code[i] = 5
        elif obj in ("Flugdach", "Offenes Gebaeude", "Mauer gross"):
            wall_rgb[i] = (172, 168, 160)
            style_code[i] = 5
        elif obj == "Treibhaus":
            wall_rgb[i] = (166, 198, 210)
            style_code[i] = 6
        elif obj in ("Sakrales Gebaeude", "Sakraler Turm"):
            if nc < 1241450:
                wall_rgb[i] = (228, 224, 214)
            else:
                wall_rgb[i] = (198, 192, 180)
            style_code[i] = 4
        elif i == 1443:
            wall_rgb[i] = (154, 58, 46)
            style_code[i] = 2
        elif i in (988, 1539):
            wall_rgb[i] = (158, 66, 52)
            style_code[i] = 3
        elif i == 963:
            wall_rgb[i] = (174, 148, 126)
            style_code[i] = 3
        elif i == 1520:
            wall_rgb[i] = (198, 186, 164)
            style_code[i] = 3
        elif i == 1281:
            wall_rgb[i] = (214, 214, 208)
            style_code[i] = 3
        elif i == 1173:
            wall_rgb[i] = (188, 184, 174)
            style_code[i] = 3
        elif i in (1473, 1720):
            wall_rgb[i] = (178, 168, 148)
            style_code[i] = 3
        elif i == 1642:
            wall_rgb[i] = (208, 206, 198)
            style_code[i] = 3
        elif i in (1582, 1695):
            wall_rgb[i] = (220, 212, 156)
            style_code[i] = 0
        elif i in (981, 1823):
            wall_rgb[i] = (218, 220, 222)
            style_code[i] = 0
        elif i == 1402:
            wall_rgb[i] = (140, 174, 156)
            style_code[i] = 6
        elif i in (1490, 1726):
            wall_rgb[i] = (102, 70, 48)
            style_code[i] = 0
        elif h < 4.3 or area_box < 42.0 or min(b["footprint_w"], b["footprint_l"]) < 4.3:
            wall_rgb[i] = (122, 88, 62) if (h_seed % 3 == 0) else plaster_trad[h_seed % 6]
            style_code[i] = 6
        elif scene.bldg_is_pitched[i]:
            wall_rgb[i] = plaster_trad[h_seed % len(plaster_trad)]
            style_code[i] = 0
        else:
            wall_rgb[i] = modern_pal[h_seed % len(modern_pal)]
            style_code[i] = 1

    return wall_rgb, style_code


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
    m_noise = scene.meadow_noise_05m[r05, c05]
    is_pave = scene.yard_pave_mask_05m[r05, c05]
    is_pool_rim = scene.pool_rim_05m[r05, c05]
    rd_ang = scene.road_ang[r05, c05]

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

    # Manicured park, orchard & cemetery emerald turf with neat warm limestone gravel walkways
    is_park = gsem == G_PARK_CEMETERY
    if is_park.any():
        park_gravel = is_park & (lum > 124.0) & ((ro[:, 1] - ro[:, 2]) < 9.0) & ((ro.max(axis=1) - ro.min(axis=1)) < 20.0)
        lawn_col[is_park] = np.where((p_hash[is_park] < 54)[:, None], [70.0, 134.0, 56.0], [60.0, 120.0, 50.0])
        lawn_col[park_gravel] = np.where((p_hash[park_gravel] < 90)[:, None], [182.0, 172.0, 154.0], [168.0, 158.0, 142.0])

    # Clean Jura limestone patios, terraces & paved residential driveways (ONLY true paved areas near buildings/streets!)
    pave_joint = ((ix25 % 5) == 0) | ((iy25 % 5) == 0)
    is_warm_yard = (ro[:, 0] - ro[:, 2]) > 10.0
    yard_col = np.where(is_warm_yard[:, None], [174.0, 164.0, 148.0], [158.0, 156.0, 150.0]).astype(np.float32)
    yard_col[pave_joint] *= 0.91
    yard_col[p_hash < 36] *= 1.04

    is_lawn = (~is_pave) | is_for | is_park
    gcol[:] = np.where(is_lawn[:, None], lawn_col, yard_col)

    # 2. Terraced Kilchberg Vineyards (G_VINEYARD): warm tilled loam + crisp 3D grapevine trellis rows!
    is_vin = gsem == G_VINEYARD
    if is_vin.any():
        vi = np.nonzero(is_vin)[0]
        u_row = (ge[vi] * 0.94 + gn[vi] * 0.34) % 2.15
        on_vine = u_row < 0.84
        vine_sh = (u_row >= 0.84) & (u_row < 1.18)
        vcol = np.full((len(vi), 3), [138.0, 118.0, 88.0], dtype=np.float32)
        vcol[p_hash[vi] < 92] = [108.0, 130.0, 68.0]  # Green grass cover-crop between trellis rows
        vcol[vine_sh] *= 0.78  # Crisp dark trellis under-shadow
        vine_leaf = np.where((p_hash[vi] < 110)[:, None], [74.0, 138.0, 50.0], [52.0, 108.0, 40.0])
        vcol[on_vine] = vine_leaf[on_vine]
        gcol[vi] = vcol
        gz[vi[on_vine]] += 0.90

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

    # 6. Parking Lots (G_PARKING): clean slate asphalt + neat bay lines aligned to adjacent street angle!
    is_pk = gsem == G_PARKING
    if is_pk.any():
        ki = np.nonzero(is_pk)[0]
        kcol = np.where((p_hash[ki] < 70)[:, None], [94.0, 98.0, 106.0], [86.0, 90.0, 98.0]).astype(np.float32)
        ka = rd_ang[ki]
        ck, sk = np.cos(ka), np.sin(ka)
        ku = (ge[ki] - E_MIN) * ck + (gn[ki] - N_MIN) * sk
        kv = -(ge[ki] - E_MIN) * sk + (gn[ki] - N_MIN) * ck
        # Clean aligned parking bays with central driving aisle
        in_bay_band = (kv % 11.5) < 4.6
        bay_line = in_bay_band & (((ku % 2.65) < 0.20) | ((kv % 11.5) < 0.20))
        kcol[bay_line] = [196.0, 198.0, 202.0]
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
        pcol = np.where(shimmer[:, None], [116.0, 218.0, 238.0], [64.0, 186.0, 218.0]).astype(np.float32)
        # Subtle turquoise lane dividers on Seebad Kilchberg pool (E≈2684240..2684305, N≈1241440..1241520)
        in_seebad = (ge[p_i] >= 2684235.0) & (ge[p_i] <= 2684310.0) & (gn[p_i] >= 1241435.0) & (gn[p_i] <= 1241525.0)
        if in_seebad.any():
            lane = in_seebad & ((((ge[p_i] * 0.85 - gn[p_i] * 0.52) % 2.4) < 0.24))
            pcol[lane] = [42.0, 134.0, 178.0]
        gcol[p_i] = pcol
        gnx[p_i], gny[p_i], gnz[p_i] = 0.0, 0.0, 1.0

    # 13. Lake Zurich (Zürichsee): authentic alpine jade-emerald shallows -> deep glacial teal-blue + crisp timber piers & moored boats!
    if glake.any():
        li = np.nonzero(glake)[0]
        is_real_harbor_obj = gharbor[li]

        wi = li[~is_real_harbor_obj]
        if len(wi) > 0:
            depth_m = np.clip(LAKE_SURFACE_Z - gbathy[wi], 0.0, 65.0)
            t_sh = np.clip(depth_m / 6.0, 0.0, 1.0)[:, None]
            t_dp = np.clip((depth_m - 6.0) / 30.0, 0.0, 1.0)[:, None]
            w_col = (1.0 - t_sh) * np.array([68.0, 122.0, 106.0]) + t_sh * (
                (1.0 - t_dp) * np.array([38.0, 88.0, 98.0]) + t_dp * np.array([24.0, 60.0, 84.0])
            )
            shallow_tint = np.clip((4.5 - depth_m) / 4.5, 0.0, 1.0)[:, None] * 0.22
            ortho_w = np.clip(raw_ortho[wi].astype(np.float32) * 1.14, 24.0, 165.0)
            w_col = (1.0 - shallow_tint) * w_col + shallow_tint * ortho_w

            shore_f = depth_m < 0.50
            w_col[shore_f] = 0.65 * w_col[shore_f] + 0.35 * np.array([182.0, 216.0, 208.0])
            gcol[wi] = w_col
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
) -> None:
    """STAGE 2.5: Render true 3D elevated viaducts (Dorfstrasse horseshoe viaduct, Bahnhofstrasse bridge,
    A3 overpasses, spiral stairs, rail bridges), concrete support piers, and SBB catenary portals!"""
    sub_bcls = scene.bridge_cls[r0:r1, c0:c1]
    sub_bz = scene.bridge_z[r0:r1, c0:c1]
    sub_bsdist = scene.bridge_sdist[r0:r1, c0:c1]
    sub_balong = scene.bridge_along[r0:r1, c0:c1]
    sub_bhw = scene.bridge_hw[r0:r1, c0:c1]
    sub_bang = scene.bridge_ang[r0:r1, c0:c1]
    sub_bid = scene.bridge_id[r0:r1, c0:c1]

    # 1. Concrete Viaduct Support Piers (under Dorfstrasse viaduct & A3 bridges)
    for pier in scene.viaduct_piers:
        pe, pn = pier["e"], pier["n"]
        if crop_box_lv95 is not None:
            if not (crop_box_lv95[0] - 4 <= pe <= crop_box_lv95[2] + 4 and crop_box_lv95[1] - 4 <= pn <= crop_box_lv95[3] + 4):
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
) -> None:
    """STAGE 2.6: True 3D pixel-art sports architecture:
    - Tennis nets (posts, white headband tape, dithered mesh), umpire chairs & dark-green perimeter windscreens
    - Football goals (white posts, crossbars, rear stanchions & netted frames), corner flags, dugouts & floodlights
    - Multi-sport court basketball hoops."""
    mpp = camera.mpp
    step_l = max(0.18, mpp * 0.65)
    step_z = max(0.18, mpp * 0.60)

    def _draw_3d_seg(e0, n0, z0, e1, n1, z1, col, mat_c=M_BRIDGE, oid=230000, thick=False, dither_mesh=False):
        dist = math.sqrt((e1 - e0) ** 2 + (n1 - n0) ** 2 + (z1 - z0) ** 2)
        ns = max(2, int(math.ceil(dist / step_l)) + 1)
        t = np.linspace(0.0, 1.0, ns, dtype=np.float64)
        es = e0 + (e1 - e0) * t
        ns_a = n0 + (n1 - n0) * t
        zs = z0 + (z1 - z0) * t
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

    for sf_i, sf in enumerate(scene.sports_fields):
        fe_c, fn_c = float(sf["e"]), float(sf["n"])
        L_f, W_f = float(sf["length"]), float(sf["width"])
        ang = float(sf["angle"])
        kind = sf["kind"]
        if crop_box_lv95 is not None:
            rad_c = 0.5 * math.hypot(L_f, W_f) + 12.0
            if fe_c + rad_c < crop_box_lv95[0] or fe_c - rad_c > crop_box_lv95[2] or fn_c + rad_c < crop_box_lv95[1] or fn_c - rad_c > crop_box_lv95[3]:
                continue
        # Quick screen-space viewport cull
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
            # 1. Crisp 3D Tennis Net (posts at v=+-6.2m, white headband at h=1.08m, dark-grey dithered mesh!)
            e_l, n_l, z_l = to_world(0.0, -6.15)
            e_r, n_r, z_r = to_world(0.0, 6.15)
            z_net = 0.5 * (z_l + z_r)
            _draw_3d_panel(
                e_l, n_l, e_r, n_r, z_net + 0.12, z_net + 1.12,
                col_body=np.array([48.0, 52.0, 58.0], dtype=np.float32),
                col_top=np.array([244.0, 244.0, 240.0], dtype=np.float32),
                oid=231000 + sf_i, mesh_only=True,
            )
            # Dark-green steel net posts
            _draw_3d_seg(e_l, n_l, z_l, e_l, n_l, z_l + 1.25, [32.0, 68.0, 42.0], oid=231000 + sf_i, thick=True)
            _draw_3d_seg(e_r, n_r, z_r, e_r, n_r, z_r + 1.25, [32.0, 68.0, 42.0], oid=231000 + sf_i, thick=True)
            # Crisp white umpire chair beside one net post
            eu, nu, zu = to_world(0.0, 6.95)
            _draw_3d_seg(eu, nu, zu, eu, nu, zu + 2.05, [224.0, 224.0, 220.0], oid=231000 + sf_i, thick=True)

            # 2. Dark-green windscreen back-fence along both baselines of the court surround!
            hl_ap = max(14.2, 0.5 * L_f + 1.1)
            hw_ap = max(7.0, 0.5 * W_f + 0.8)
            for sgn_u in (-1.0, 1.0):
                ef0, nf0, zf0 = to_world(sgn_u * hl_ap, -hw_ap)
                ef1, nf1, zf1 = to_world(sgn_u * hl_ap, hw_ap)
                zf_m = 0.5 * (zf0 + zf1)
                # Bottom 1.75m solid dark-green privacy windscreen
                _draw_3d_panel(
                    ef0, nf0, ef1, nf1, zf_m, zf_m + 1.75,
                    col_body=np.array([34.0, 74.0, 44.0], dtype=np.float32),
                    col_top=np.array([48.0, 96.0, 56.0], dtype=np.float32),
                    oid=231200 + sf_i, mesh_only=False,
                )
                # Top chain-link mesh up to 2.7m + steel posts
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

            # 1. TRUE 3D WHITE FOOTBALL GOALS WITH NETS AT BOTH ENDS!
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

                # Back net & side nets (dithered translucent white mesh!)
                _draw_3d_panel(e_bl, n_bl, e_br, n_br, zg, zg + goal_h * 0.88, net_c, white_p, oid=232000 + sf_i, mesh_only=True)
                _draw_3d_panel(e_fl, n_fl, e_bl, n_bl, zg, zg + goal_h * 0.88, net_c, white_p, oid=232000 + sf_i, mesh_only=True)
                _draw_3d_panel(e_fr, n_fr, e_br, n_br, zg, zg + goal_h * 0.88, net_c, white_p, oid=232000 + sf_i, mesh_only=True)
                # Crisp white twin posts, crossbar & top roof depth bars
                _draw_3d_seg(e_fl, n_fl, zg, e_fl, n_fl, zg + goal_h, white_p, oid=232000 + sf_i, thick=True)
                _draw_3d_seg(e_fr, n_fr, zg, e_fr, n_fr, zg + goal_h, white_p, oid=232000 + sf_i, thick=True)
                _draw_3d_seg(e_fl, n_fl, zg + goal_h, e_fr, n_fr, zg + goal_h, white_p, oid=232000 + sf_i, thick=True)
                _draw_3d_seg(e_fl, n_fl, zg + goal_h, e_bl, n_bl, zg + goal_h * 0.85, white_p, oid=232000 + sf_i)
                _draw_3d_seg(e_fr, n_fr, zg + goal_h, e_br, n_br, zg + goal_h * 0.85, white_p, oid=232000 + sf_i)

            # 2. Four Swiss red corner flags!
            for sgn_u in (-1.0, 1.0):
                for sgn_v in (-1.0, 1.0):
                    ec, nc, zc = to_world(sgn_u * hl, sgn_v * hw)
                    _draw_3d_seg(ec, nc, zc, ec, nc, zc + 1.65, [234.0, 234.0, 230.0], oid=232100 + sf_i)
                    _draw_3d_seg(ec, nc, zc + 1.35, ec + 0.55, nc, zc + 1.55, [218.0, 42.0, 42.0], oid=232100 + sf_i, thick=True)

            # 3. Team bench dugouts along the touchline!
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

            # 4. Tall stadium floodlight masts around main pitches (glowing warm gold in night mode!)
            if L_f >= 92.0:
                lamp_mat = M_WINDOW_LIT if is_night else M_BRIDGE
                lamp_col = [255.0, 240.0, 182.0] if is_night else [228.0, 232.0, 236.0]
                for sgn_u in (-0.62, 0.62):
                    for sgn_v in (-1.0, 1.0):
                        em, nm, zm = to_world(sgn_u * hl, sgn_v * (hw + 3.2))
                        _draw_3d_seg(em, nm, zm, em, nm, zm + 14.5, [138.0, 144.0, 152.0], oid=232300 + sf_i, thick=True)
                        # Floodlight crossbar lamp bank at top of mast
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

    # 5. Charming Swiss Pasture Details: Grazing Braunvieh & Holstein Cows in Kilchberg's Upper Farm Meadows!
    if not is_night:
        cow_herds = [
            # Upper farm pasture beside the historic red-roofed farmstead (Brunnenmoos / Stocken ridge)
            (2683312.0, 1242048.0, 0.3, 0), (2683319.0, 1242058.0, 1.1, 1), (2683328.0, 1242044.0, -0.5, 0),
            (2683304.0, 1242068.0, 2.2, 1), (2683336.0, 1242063.0, 0.8, 0), (2683344.0, 1242052.0, -1.2, 1),
            (2683295.0, 1242038.0, 0.2, 0), (2683322.0, 1242078.0, 1.8, 1),
            # Upper sunlit meadow near Sportplatz Hochweid / ridge footpath
            (2683228.0, 1241690.0, 0.6, 0), (2683236.0, 1241702.0, -0.8, 1), (2683246.0, 1241684.0, 1.4, 0),
            (2683219.0, 1241712.0, 2.1, 1), (2683254.0, 1241706.0, 0.4, 0),
        ]
        for ci, (ce, cn, cang, cbreed) in enumerate(cow_herds):
            if crop_box_lv95 is not None and not (crop_box_lv95[0] <= ce <= crop_box_lv95[2] and crop_box_lv95[1] <= cn <= crop_box_lv95[3]):
                continue
            cz = _sample_dem(ce, cn)
            ca_c, sa_c = math.cos(cang), math.sin(cang)
            body_c = [138.0, 96.0, 66.0] if cbreed == 0 else [234.0, 234.0, 228.0]
            spot_c = [212.0, 198.0, 178.0] if cbreed == 0 else [42.0, 42.0, 46.0]
            # Crisp 3D miniature cow torso + head
            _draw_3d_seg(ce - 0.8 * ca_c, cn - 0.8 * sa_c, cz + 0.72, ce + 0.8 * ca_c, cn + 0.8 * sa_c, cz + 0.76, body_c, oid=234000 + ci, thick=True)
            _draw_3d_seg(ce - 0.2 * ca_c, cn - 0.2 * sa_c, cz + 0.82, ce + 0.35 * ca_c, cn + 0.35 * sa_c, cz + 0.84, spot_c, oid=234000 + ci)
            _draw_3d_seg(ce + 0.85 * ca_c, cn + 0.85 * sa_c, cz + 0.55, ce + 1.15 * ca_c, cn + 1.15 * sa_c, cz + 0.48, spot_c, oid=234000 + ci)

    # 6. Crisp Static 90s Pixel-Art Parked Cars neatly aligned inside Parking Lots (Lindt, Bahnhof, Village)!
    pk_rows, pk_cols = np.nonzero(scene.sem == G_PARKING)
    if len(pk_rows) > 0:
        # Subsample onto a clean 4.5m x 6.5m deterministic grid strictly inside G_PARKING
        sel_pk = ((pk_rows % 9) == 4) & ((pk_cols % 11) == 5)
        pr_s, pc_s = pk_rows[sel_pk], pk_cols[sel_pk]
        car_pal = [
            [218.0, 220.0, 224.0],  # Swiss silver/white
            [52.0, 64.0, 86.0],     # Dark navy
            [176.0, 44.0, 44.0],    # Swiss red
            [74.0, 78.0, 84.0],     # Anthracite metallic
            [184.0, 174.0, 152.0],  # Warm champagne
            [44.0, 88.0, 68.0],     # Alpine dark green
        ]
        for pi_k in range(len(pr_s)):
            rr_k, cc_k = int(pr_s[pi_k]), int(pc_s[pi_k])
            kh = ((rr_k * 73856093) ^ (cc_k * 19349663)) & 0xFF
            if (kh % 3) == 0:  # ~66% parking lot occupancy looks super authentic!
                continue
            pe_k = E_MIN + (cc_k + 0.5) * GRID_RES
            pn_k = N_MAX - (rr_k + 0.5) * GRID_RES
            if crop_box_lv95 is not None and not (crop_box_lv95[0] <= pe_k <= crop_box_lv95[2] and crop_box_lv95[1] <= pn_k <= crop_box_lv95[3]):
                continue
            # Quick screen cull
            px_k, py_k, _ = camera.project(np.array([pe_k]), np.array([pn_k]), np.array([float(scene.dem[rr_k, cc_k])]))
            if px_k[0] + shift_x < -12 or px_k[0] + shift_x > W + 12 or py_k[0] + shift_y < -12 or py_k[0] + shift_y > H + 12:
                continue
            pz_k = float(scene.dem[rr_k, cc_k])
            ang_k = float(scene.road_ang[rr_k, cc_k]) + (math.pi * 0.5)
            ck, sk = math.cos(ang_k), math.sin(ang_k)
            ccol = car_pal[kh % len(car_pal)]
            # Lower car body + upper cabin/windshield!
            _draw_3d_seg(pe_k - 1.65 * ck, pn_k - 1.65 * sk, pz_k + 0.55, pe_k + 1.65 * ck, pn_k + 1.65 * sk, pz_k + 0.55, ccol, oid=235000 + pi_k, thick=True)
            _draw_3d_seg(pe_k - 1.65 * ck, pn_k - 1.65 * sk, pz_k + 0.92, pe_k + 1.65 * ck, pn_k + 1.65 * sk, pz_k + 0.92, ccol, oid=235000 + pi_k, thick=True)
            _draw_3d_seg(pe_k - 0.85 * ck, pn_k - 0.85 * sk, pz_k + 1.32, pe_k + 0.85 * ck, pn_k + 0.85 * sk, pz_k + 1.32, [68.0, 92.0, 118.0], oid=235000 + pi_k, thick=True)


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
) -> None:
    """STAGE 4 (V6.0): Hand-crafted 90s pixel-art 3D trees (6 distinct botanical archetypes,
    randomized asymmetric multi-cluster leaf crowns, 5-tone leaf dithering & grounded canopy shadows)
    plus sculpted beveled garden boxwood hedges & flowering shrubs!"""
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
        # Rich 3-tone leafy privet/boxwood top + subtle garden rose/hydrangea blossoms!
        h_top_col = np.where(
            (h_hash < 72)[:, None],
            [82.0, 134.0, 56.0],
            np.where((h_hash < 176)[:, None], [58.0, 108.0, 46.0], [42.0, 86.0, 38.0]),
        ).astype(np.float32)
        # Occasional delicate garden blossoms on residential hedges
        is_rose = (h_hash == 251)
        is_lav = (h_hash == 253)
        h_top_col[is_rose] = [226.0, 152.0, 166.0]
        h_top_col[is_lav] = [214.0, 198.0, 146.0]
        h_side_col = h_top_col * 0.72
        h_base_col = h_top_col * 0.54
        h_oid = np.full(len(hr), 190000, dtype=np.int32)

        # Render 4 sculpted height tiers (grounded dark base -> leafy mid sides -> sunlit rounded crown)
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
    t_ids = np.arange(len(te), dtype=np.int32)

    if crop_box_lv95 is not None:
        e0, n0, e1, n1 = crop_box_lv95
        keep = (te >= e0 + 1.5) & (te <= e1 - 1.5) & (tn >= n0 + 1.5) & (tn <= n1 - 1.5)
        te, tn, tz, th, trad, tsp, t_ids = te[keep], tn[keep], tz[keep], th[keep], trad[keep], tsp[keep], t_ids[keep]

    if len(te) == 0:
        return

    px_base, py_base, pd_base = camera.project(te, tn, tz)
    px_top, py_top, _ = camera.project(te, tn, tz + th)
    r_px_est = (trad * 1.45 / camera.mpp) + 12.0
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

    # 6 Botanical 5-Tone Painterly 90s Pixel-Art Foliage Ramps:
    # [0=deep_under_shadow, 1=cool_mid_shade, 2=rich_mid_leaf, 3=sunlit_leaf, 4=crisp_sun_tip]
    SPECIES_RAMPS = np.array(
        [
            # 0: Majestic Swiss Oak / Beech (rich deep forest emerald -> warm sunlit tips)
            [[14.0, 36.0, 24.0], [24.0, 58.0, 32.0], [40.0, 88.0, 40.0], [64.0, 120.0, 50.0], [94.0, 148.0, 62.0]],
            # 1: Sunlit Linden / Birch / Fruit Orchard (warm olive -> golden-apple leaf clusters)
            [[20.0, 46.0, 24.0], [34.0, 76.0, 34.0], [56.0, 110.0, 44.0], [86.0, 142.0, 56.0], [122.0, 172.0, 70.0]],
            # 2: Alpine Spruce / Silver Fir (cool mountain blue-green needles)
            [[12.0, 30.0, 26.0], [20.0, 48.0, 40.0], [32.0, 72.0, 52.0], [48.0, 96.0, 66.0], [68.0, 122.0, 80.0]],
            # 3: Slender Cypress / Lombardy Poplar (refined Mediterranean-Zürichsee green)
            [[16.0, 36.0, 26.0], [26.0, 60.0, 38.0], [40.0, 86.0, 50.0], [60.0, 114.0, 62.0], [86.0, 140.0, 74.0]],
            # 4: Stately Estate Copper Beech (refined deep aubergine-plum -> warm bronze-burgundy)
            [[34.0, 18.0, 24.0], [56.0, 26.0, 32.0], [82.0, 38.0, 42.0], [112.0, 54.0, 54.0], [142.0, 74.0, 68.0]],
            # 5: Spring Cherry / Apple Blossom Tree (dusty rose shadow -> soft pink -> sunlit creamy-white petals!)
            [[116.0, 68.0, 80.0], [164.0, 106.0, 120.0], [206.0, 150.0, 164.0], [234.0, 196.0, 206.0], [250.0, 232.0, 236.0]],
        ],
        dtype=np.float32,
    )

    # Precompute screen-space lighting vector
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
        h_m = float(th[i])
        r_m = float(trad[i])
        cx0 = float(px_base[i])
        cy0 = float(py_base[i])
        d0 = float(pd_base[i])

        # Deterministic per-tree variation seeds (NO two trees share the same silhouette!)
        s0 = ((tid * 73856093) ^ 0x5A5A) & 0xFFFF
        s1 = ((tid * 19349663) ^ 0xA53C) & 0xFFFF
        s2 = ((tid * 83492791) ^ 0x3C71) & 0xFFFF
        w_var = 0.88 + 0.24 * ((s0 & 255) / 255.0)
        h_var = 0.90 + 0.20 * (((s0 >> 8) & 255) / 255.0)

        if sp_k in (0, 1, 4, 5):
            r_px = max(3.6, (r_m * 1.24 * w_var) / mpp)
            h_px = max(7.0, min(h_m * z_px_per_m * h_var, r_px * 2.55))
            crown_ry = max(3.4, min(h_px * 0.45, r_px * 0.92))
            trunk_h_px = max(2.4, h_px - crown_ry * 1.88)
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
            # Soft dithered edge on outer ring of contact shadow
            outer_sh = in_sh & (sr2 > 0.58)
            dith_keep = (((sgx.astype(np.int32) + sgy.astype(np.int32)) & 1) == 0)
            apply_sh = (in_sh & (~outer_sh)) | (outer_sh & dith_keep)
            if apply_sh.any():
                rgb_buf[sy0 : sy1 + 1, sx0 : sx1 + 1][apply_sh] *= 0.80

        # 1. Crisp warm timber trunk (+ subtle root flare & visible Y-fork on taller broadleaf trees)
        tx_i = int(round(cx0))
        ty_bot = int(round(cy0))
        ty_top = int(round(cy0 - trunk_h_px - 2.5))
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
                bark_c = [152.0, 144.0, 132.0] if (sp_k == 1 and (s2 & 3) == 0) else [86.0, 60.0, 40.0]
                rgb_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = bark_c
                mat_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = M_TRUNK
                obj_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = oid
                norm_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = [0.5, -0.5, 0.35]
                shadow_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = False

        # 2. Compute tight screen bounding box for this tree's sculpted 3D crown
        crown_bot_y = cy0 - trunk_h_px
        crown_top_y = crown_bot_y - crown_ry * 2.0
        crown_cy = 0.5 * (crown_bot_y + crown_top_y)
        pad_x = int(math.ceil(r_px * 1.35)) + 2

        x0_b = max(0, int(math.floor(cx0)) - pad_x)
        x1_b = min(W - 1, int(math.ceil(cx0)) + pad_x)
        y0_b = max(0, int(math.floor(crown_top_y)) - 4)
        y1_b = min(H - 1, int(math.ceil(crown_bot_y)) + 2)
        if x1_b < x0_b or y1_b < y0_b:
            continue

        xs = np.arange(x0_b, x1_b + 1, dtype=np.float32)
        ys = np.arange(y0_b, y1_b + 1, dtype=np.float32)
        gx, gy = np.meshgrid(xs, ys)
        dx = gx - cx0
        v_h = (crown_bot_y - gy) / max(1.0, (crown_bot_y - crown_top_y))

        # Slight deterministic per-tree brightness/hue shift so adjacent forest trees read as individuals!
        ramp = SPECIES_RAMPS[sp_k]
        hue_shift = (((s2 & 31) / 31.0) - 0.5) * 0.14
        if abs(hue_shift) > 0.01:
            ramp = np.clip(ramp * np.array([1.0 + hue_shift * 0.8, 1.0 + hue_shift * 0.5, 1.0 - hue_shift * 0.4], dtype=np.float32), 8.0, 252.0)

        # True non-periodic 2D spatial hashes for crisp 90s pixel-art leaf-cluster stippling!
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
            # ALPINE SPRUCE / SILVER FIR: 5 distinct scalloped drooping conifer bough tiers!
            in_v = (v_h >= -0.04) & (v_h <= 1.05)
            v_c = np.clip(v_h, 0.0, 1.0)
            n_tiers = 5.0 if h_px >= 14.0 else 4.0
            t_ph = (v_c * n_tiers) % 1.0
            # Scalloped bough flare at bottom of each tier + drooping outer tips
            tier_wave = 0.62 + 0.44 * ((1.0 - t_ph) ** 0.85)
            half_w_y = np.maximum(0.85, r_px * (1.02 - 0.90 * v_c) * tier_wave)
            edge_n = clump_2x2 * 1.45 + micro_1x1 * 0.85
            nx_n = dx / np.maximum(1.0, half_w_y + edge_n)
            inside = in_v & (np.abs(nx_n) <= 1.0)
            if not inside.any():
                continue
            nz_n = np.sqrt(np.maximum(0.05, 1.0 - np.minimum(0.98, nx_n * nx_n)))
            ny_n = 0.25 + 0.48 * v_c - 0.34 * t_ph
            # Crisp dark shadow tucked underneath each overlapping pine bough tier
            tier_sh = np.where(t_ph > 0.72, -0.32, np.where(t_ph < 0.22, 0.16, 0.0))
            nd_s = nx_n * lx_s + ny_n * ly_s + nz_n * lz_s + tier_sh + clump_2x2 * 0.46 + micro_1x1 * 0.22 + bayer_t * 0.18
            d_surf = d0 - nz_n * (r_m * 0.78) - v_c * (h_m * 0.45 * sp_c)

        elif sp_k == 3:
            # SLENDER CYPRESS / LOMBARDY POPLAR: Feathery asymmetric spire!
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

        else:
            # BROADLEAF DECIDUOUS & SPRING BLOSSOM (Oak, Beech, Linden, Copper Beech, Cherry Blossom):
            # Per-tree randomized asymmetric 9-cluster organic leafy bough canopy (ZERO cloned broccoli balls!)
            dy_c = gy - crown_cy
            jx1 = (((s1 & 15) / 15.0) - 0.5) * 0.36 * r_px
            jy1 = ((((s1 >> 4) & 15) / 15.0) - 0.5) * 0.24 * crown_ry
            jx2 = ((((s1 >> 8) & 15) / 15.0) - 0.5) * 0.34 * r_px
            jy2 = ((((s1 >> 12) & 15) / 15.0) - 0.5) * 0.24 * crown_ry
            asym = ((((s2 >> 6) & 15) / 15.0) - 0.5) * 0.26 * r_px

            lobes = (
                # Upper sunlit bough clusters
                (asym * 0.6 + jx1 * 0.4, -0.44 * crown_ry + jy1 * 0.5, 0.52 * r_px, 0.46 * crown_ry),
                (-0.42 * r_px + jx2 * 0.5, -0.34 * crown_ry + jy2 * 0.5, 0.46 * r_px, 0.42 * crown_ry),
                (0.42 * r_px + jx1 * 0.5, -0.28 * crown_ry - jy1 * 0.4, 0.46 * r_px, 0.42 * crown_ry),
                # Mid-crown spreading leafy boughs
                (-0.62 * r_px + jx1 * 0.3, 0.08 * crown_ry + jy2 * 0.5, 0.48 * r_px, 0.44 * crown_ry),
                (0.60 * r_px - jx2 * 0.3, 0.12 * crown_ry + jy1 * 0.4, 0.48 * r_px, 0.44 * crown_ry),
                (0.04 * r_px + asym * 0.4, -0.08 * crown_ry, 0.58 * r_px, 0.52 * crown_ry),
                # Lower shaded bough skirt (slightly irregular so bottom doesn't look cut with scissors)
                (-0.32 * r_px + jx2 * 0.4, 0.34 * crown_ry, 0.46 * r_px, 0.38 * crown_ry),
                (0.32 * r_px + jx1 * 0.4, 0.32 * crown_ry, 0.46 * r_px, 0.38 * crown_ry),
                (0.0, 0.40 * crown_ry + jy2 * 0.3, 0.48 * r_px, 0.36 * crown_ry),
            )
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
                # Subtle self-shadowing depth between upper vs lower overlapping leaf boughs!
                best_lobe_bias[better] = 0.14 if l_idx < 3 else (-0.16 if l_idx >= 6 else 0.0)

            # Organic nibbled leafy perimeter silhouette (breaks smooth circles into crisp pixel foliage!)
            rim_thresh = 0.14 + clump_2x2 * 0.24 + micro_1x1 * 0.14
            inside = best_z > np.maximum(0.0, rim_thresh)
            if not inside.any():
                continue
            nz_n = best_z
            nd_s = best_nx * lx_s + best_ny * ly_s + nz_n * lz_s + best_lobe_bias
            # Crisp 90s pixel-art leaf-cluster texture (stronger clump stipple kills smooth airbrush look!)
            leaf_tex = clump_2x2 * 0.56 + micro_1x1 * 0.24 + bayer_t * 0.18
            nd_s = nd_s + leaf_tex - np.clip(0.34 - v_h, 0.0, 0.36) * 0.58
            d_surf = d0 - nz_n * (r_m * 0.82) - np.clip(v_h, 0.0, 1.0) * (h_m * 0.42 * sp_c)

        # Quantize lighting into all 5 crisp hand-drawn 90s botanical pixel-art leaf tones
        # (deep emerald & mid-green dominate; tone 4 sparks only on sunlit outer leaf tips!)
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
    sun_shadow_override: np.ndarray | None = None,
    out_depth_buf: dict | None = None,
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

    sun_shadow_grid = sun_shadow_override if sun_shadow_override is not None else compute_shadow_grid(scene, preset.sun_az_deg, preset.sun_alt_deg)
    sub_shadow = sun_shadow_grid[r0:r1, c0:c1]

    s_az = math.radians(preset.sun_az_deg)
    s_alt = math.radians(preset.sun_alt_deg)
    sun_vec = np.array(
        [math.sin(s_az) * math.cos(s_alt), math.cos(s_az) * math.cos(s_alt), math.sin(s_alt)],
        dtype=np.float32,
    )

    # -------------------------------------------------------------------------
    # STAGE 1: Drop Shadow + Carved Geological & Lake Zurich Aquarium Cutaway
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
    sm_f = ndimage.gaussian_filter(glob_m.astype(np.float32), sigma=2.0)
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
        keep_p = ((px_p0 + shift_x) >= -12.0) & ((px_p0 + shift_x) <= (W + 12.0))
        pe, pn, pz_top = pe[keep_p], pn[keep_p], pz_top[keep_p]
        p_lake, p_bathy = p_lake[keep_p], p_bathy[keep_p]
        pnx, pny = pnx[keep_p], pny[keep_p]

    dz_step = max(0.20, camera.mpp * 0.45)
    max_col_h = float((pz_top - plinth_z).max()) if len(pz_top) else 0.0
    n_zsteps = max(2, int(math.ceil(max_col_h / dz_step)) + 1)
    cut_ox_list = (-1, 0, 1) if camera.mpp <= 0.38 else (0, 1)

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
        cnx_v, cny_v, ce_v = cnx_v[v], cny_v[v], ce[v]

        depth_from_top = cz_top - cz
        above_plinth = cz - plinth_z
        col = np.empty((len(ix), 3), dtype=np.float32)

        strata_wave = np.sin(cz * 0.65 + ce_v * 0.012)
        col[:] = np.where((strata_wave > 0.15)[:, None], [138.0, 126.0, 108.0], [116.0, 106.0, 90.0])
        col[(depth_from_top >= 3.2) & (depth_from_top < 18.5) & (~c_islake)] = [160.0, 134.0, 96.0]
        col[(depth_from_top >= 0.9) & (depth_from_top < 3.2) & (~c_islake)] = [102.0, 76.0, 54.0]
        col[(depth_from_top < 0.9) & (~c_islake)] = [88.0, 142.0, 64.0]

        in_w = c_islake & (cz >= c_bathy)
        if in_w.any():
            w_d = np.clip(LAKE_SURFACE_Z - cz[in_w], 0.0, 55.0)
            t_w = np.clip(w_d / 34.0, 0.0, 1.0)[:, None]
            col[in_w] = (1.0 - t_w) * np.array([58.0, 128.0, 118.0]) + t_w * np.array([22.0, 58.0, 78.0])
            col[in_w] = np.where((w_d < 0.95)[:, None], [168.0, 214.0, 208.0], col[in_w])

        col[c_islake & (cz < c_bathy)] = [110.0, 106.0, 96.0]
        col[above_plinth < 2.6] = [50.0, 48.0, 56.0]

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
        gnx = scene.terr_nx[r0:r1, c0:c1][gr, gc].copy()
        gny = scene.terr_ny[r0:r1, c0:c1][gr, gc].copy()
        gnz = scene.terr_nz[r0:r1, c0:c1][gr, gc].copy()

        rd_dist = scene.road_dist[r0:r1, c0:c1][gr, gc]
        rd_along = scene.road_along[r0:r1, c0:c1][gr, gc]
        rd_hw = scene.road_hw[r0:r1, c0:c1][gr, gc]
        rl_dist = scene.rail_dist[r0:r1, c0:c1][gr, gc]
        rl_along = scene.rail_along[r0:r1, c0:c1][gr, gc]
        xwalk = scene.crosswalk_mask[r0:r1, c0:c1][gr, gc]

        raw_ortho = sample_ortho_25cm(scene, ge, gn)
        gcol, gmat, gz = _shade_drawn_ground_90s(
            scene, ge, gn, gz, gsem, glake, gbathy, gharbor, raw_ortho,
            rd_dist, rd_along, rd_hw, rl_dist, rl_along, xwalk,
            gnx, gny, gnz, sub_chm[gr, gc],
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
            gcol, gmat, gsh = gcol[gv], gmat[gv], gsh[gv]
            gnx, gny, gnz = gnx[gv], gny[gv], gnz[gv]

            order = np.argsort(gdepth)[::-1]
            gix, giy, gdepth = gix[order], giy[order], gdepth[order]
            gcol, gmat, gsh = gcol[order], gmat[order], gsh[order]
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

            # Fill vertical screen gaps on steep Swiss hillside retaining walls & embankments!
            steep = gnz < 0.88
            if steep.any():
                si = np.nonzero(steep)[0]
                s_ix = gix[si]
                s_iy = giy[si]
                s_d = gdepth[si]
                s_sh = gsh[si]
                s_nx, s_ny, s_nz = gnx[si], gny[si], gnz[si]
                # Steep retaining wall (>44°) -> warm Swiss Jura-limestone ashlar masonry; moderate bank -> shaded terrain
                is_rwall = s_nz < 0.72
                s_col = np.where(is_rwall[:, None], [156.0, 150.0, 138.0], gcol[si] * 0.88).astype(np.float32)
                max_drop = np.clip(np.round((1.0 - s_nz) * 24.0).astype(np.int32), 2, 10)
                for oy in range(2, 11):
                    act = max_drop >= oy
                    if not act.any():
                        continue
                    ai = np.nonzero(act)[0]
                    # Subtle horizontal stone mortar course every 3px on retaining walls
                    course_mul = 0.88 if (oy % 3 == 0) else 1.0
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
                                c_out[rw_w] *= course_mul
                            rgb_buf[wy, wx] = c_out
                            mat_buf[wy, wx] = M_GROUND
                            obj_buf[wy, wx] = 0
                            shadow_buf[wy, wx] = np.where(rw_w, False, s_sh[w_ai])
                            norm_buf[wy, wx, 0] = s_nx[w_ai]
                            norm_buf[wy, wx, 1] = s_ny[w_ai]
                            norm_buf[wy, wx, 2] = np.maximum(0.58, s_nz[w_ai])

    # -------------------------------------------------------------------------
    # STAGE 2.5: True 3D Elevated Viaducts (Dorfstrasse!), Piers & SBB Catenary Portals!
    # -------------------------------------------------------------------------
    _render_elevated_bridges_and_rail_portals(
        scene, camera, shift_x, shift_y, W, H, r0, r1, c0, c1,
        sub_mask, sub_dem, sub_shadow,
        zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
        crop_box_lv95,
    )

    # -------------------------------------------------------------------------
    # STAGE 2.6: True 3D Sports Architecture (Tennis Nets/Fences, Football Goals/Floodlights!)
    # -------------------------------------------------------------------------
    _render_3d_sports_details(
        scene, camera, shift_x, shift_y, W, H,
        zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
        preset.is_night, crop_box_lv95,
    )

    # -------------------------------------------------------------------------
    # STAGE 3: All 1,890 Real 3D LOD2 Buildings — Drawn 90s Roofs & Authentic Facades!
    # -------------------------------------------------------------------------
    verts = scene.verts
    norms = scene.normals
    bidx = scene.bldg_idx
    stype = scene.surf_type
    t_dir_bin = scene.tri_dir_bin
    t_tw_x = scene.tri_tw_x
    t_tw_y = scene.tri_tw_y
    t_u_verts = scene.tri_u_verts

    bldg_z0 = np.array([b["z_ground"] for b in scene.buildings], dtype=np.float32)
    bldg_z1 = np.array([b["z_roof"] for b in scene.buildings], dtype=np.float32)
    bldg_e0 = np.array([b["e"] for b in scene.buildings], dtype=np.float32)
    bldg_n0 = np.array([b["n"] for b in scene.buildings], dtype=np.float32)
    bldg_wall_rgb, bldg_style = _compute_building_facade_styles(scene)

    if crop_box_lv95 is not None:
        e0, n0, e1, n1 = crop_box_lv95
        be_tri, bn_tri = bldg_e0[bidx], bldg_n0[bidx]
        in_crop = (be_tri >= e0 + 2) & (be_tri <= e1 - 2) & (bn_tri >= n0 + 2) & (bn_tri <= n1 - 2)
        verts, norms, bidx, stype = verts[in_crop], norms[in_crop], bidx[in_crop], stype[in_crop]
        t_dir_bin = t_dir_bin[in_crop]
        t_tw_x, t_tw_y = t_tw_x[in_crop], t_tw_y[in_crop]
        t_u_verts = t_u_verts[in_crop]

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

            # -----------------------------------------------------------------
            # A. ROOF PIXELS (V6.0): Jewel-Like 90s Pixel-Art Roofs, Zero Blue Shadow Static!
            # -----------------------------------------------------------------
            rm = st_f == 1
            if rm.any():
                r_ft = ft[rm]
                r_bi = bi[rm]
                r_norms = norms_v[r_ft]
                re_r, rn_r, rz_r, ru_r = fe[rm], fn[rm], fz[rm], fu[rm]

                r_alb = scene.bldg_clean_roof_rgb[r_bi].copy()
                r_kind = scene.bldg_roof_kind[r_bi]
                pitched = r_norms[:, 2] < 0.93

                # 1. Pitched Roofs: Crisp overlapping Swiss clay/slate tile courses with sunlit top lip & dark overlap!
                if pitched.any():
                    pi_r = np.nonzero(pitched)[0]
                    rz_p = rz_r[pi_r]
                    ru_p = ru_r[pi_r]
                    rb_p = r_bi[pi_r]
                    course_f = rz_p * 1.80
                    course_idx = np.floor(course_f).astype(np.int32)
                    in_course = course_f - course_idx
                    u_f = ru_p * 2.05 + (course_idx & 1) * 0.5
                    u_idx = np.floor(u_f).astype(np.int32)
                    u_tile = u_f - u_idx

                    # Organic per-tile warm/cool tonal variation (real kiln-fired Swiss clay tiles!)
                    t_hash = ((course_idx * 73856093) ^ (u_idx * 19349663) ^ (rb_p * 40503)) & 15
                    t_var = ((t_hash.astype(np.float32) / 15.0) - 0.5) * 16.0
                    is_clay = r_kind[pi_r] == 0
                    r_alb[pi_r] = np.clip(
                        r_alb[pi_r] + np.where(is_clay[:, None], t_var[:, None] * np.array([1.15, 0.85, 0.65]), t_var[:, None] * 0.65),
                        28.0, 238.0,
                    )
                    # Crisp 1px dark under-lap shadow + sunlit top ridge lip on each overlapping tile row!
                    r_alb[pi_r[in_course < 0.25]] *= 0.80
                    r_alb[pi_r[(in_course >= 0.76) & (in_course < 0.94)]] = np.minimum(242.0, r_alb[pi_r[(in_course >= 0.76) & (in_course < 0.94)]] * 1.07)
                    # Subtle vertical tile side seam
                    r_alb[pi_r[u_tile < 0.14]] *= 0.92
                    # Crisp dark eave shadow band along bottom edge of pitched roof
                    eave_d = rz_p - scene.bldg_eave_z[rb_p]
                    r_alb[pi_r[(eave_d >= -0.25) & (eave_d < 0.38)]] *= 0.80

                    # Crisp Velux roof skylights cleanly placed (1-2 per roof) on ~35% of medium pitched Swiss houses (NOT barns!)
                    bldg_fw_arr = np.array([b["footprint_w"] for b in scene.buildings], dtype=np.float32)
                    bldg_fl_arr = np.array([b["footprint_l"] for b in scene.buildings], dtype=np.float32)
                    r_mid_z = 0.52 * scene.bldg_eave_z[rb_p] + 0.48 * bldg_z1[rb_p]
                    has_sky = (
                        ((rb_p % 3) == 1)
                        & ((bldg_z1[rb_p] - scene.bldg_eave_z[rb_p]) >= 2.2)
                        & (bldg_fw_arr[rb_p] <= 22.0)
                        & (bldg_fl_arr[rb_p] <= 22.0)
                        & (rb_p != 1715)
                    )
                    # Place 1-2 skylights neatly near roof center (|ru_p| <= 3.6m)
                    sky_u = np.where((rb_p & 1) == 0, ru_p, np.abs(ru_p) - 2.15)
                    sky_dz = rz_p - r_mid_z
                    in_sky_frame = has_sky & (np.abs(sky_u) <= 0.68) & (np.abs(sky_dz) <= 0.56) & (eave_d >= 0.9)
                    in_sky_glass = has_sky & (np.abs(sky_u) <= 0.50) & (np.abs(sky_dz) <= 0.40) & (eave_d >= 0.9)
                    if in_sky_frame.any():
                        r_alb[pi_r[in_sky_frame]] = [176.0, 180.0, 184.0]
                        r_alb[pi_r[in_sky_glass]] = [58.0, 84.0, 118.0] if not preset.is_night else [242.0, 196.0, 108.0]

                # 2. Flat Roofs: Clean limestone parapet coping + inner shadow + gravel ballast / lush sedum eco-roof!
                flat = ~pitched
                if flat.any():
                    fi_r = np.nonzero(flat)[0]
                    est = sample_roof_edge_25cm(scene, re_r[fi_r], rn_r[fi_r])
                    rx25 = np.floor((re_r[fi_r] - E_MIN) * 4.0).astype(np.int32)
                    ry25 = np.floor((rn_r[fi_r] - N_MIN) * 4.0).astype(np.int32)
                    rhash = ((rx25 * 73856093) ^ (ry25 * 19349663)) & 0xFF
                    is_eco = r_kind[fi_r] == 3
                    # Gravel ballast interior: subtle crisp pebble stipple + clean architectural expansion seams
                    r_alb[fi_r[(~is_eco) & (rhash < 64)]] *= 0.94
                    r_alb[fi_r[(~is_eco) & (rhash >= 192)]] *= 1.04
                    f_seam = (~is_eco) & (est >= 3) & ((((re_r[fi_r] * 0.85 - rn_r[fi_r] * 0.52) % 8.5) < 0.28))
                    r_alb[fi_r[f_seam]] *= 0.90
                    # Sedum extensive green roof: lush multi-tone moss/sedum + neat gravel drainage rim near parapet!
                    eco_drain = is_eco & (est == 3)
                    r_alb[fi_r[is_eco & (rhash < 85)]] *= 0.87
                    r_alb[fi_r[is_eco & (rhash >= 175)]] *= 1.10
                    r_alb[fi_r[eco_drain]] = [148.0, 146.0, 140.0]

                    # Lindt Home of Chocolate (bi == 1443): Iconic 4 oval/rectangular glass atrium skylights!
                    is_hoc_roof = r_bi[fi_r] == 1443
                    if is_hoc_roof.any():
                        hi_rf = np.nonzero(is_hoc_roof)[0]
                        he_r, hn_r = re_r[fi_r[hi_rf]], rn_r[fi_r[hi_rf]]
                        # Local roof axis along Lindt HoC building (angled ~-22 deg from North)
                        ang_h = math.radians(-22.0)
                        uh = (he_r - 2684094.0) * math.cos(ang_h) + (hn_r - 1241434.0) * math.sin(ang_h)
                        vh = -(he_r - 2684094.0) * math.sin(ang_h) + (hn_r - 1241434.0) * math.cos(ang_h)
                        on_sky_f = np.zeros(len(hi_rf), dtype=np.bool_)
                        on_sky_g = np.zeros(len(hi_rf), dtype=np.bool_)
                        for v_c in (-18.0, -6.0, 6.0, 18.0):
                            on_sky_f |= (np.abs(uh) <= 4.4) & (np.abs(vh - v_c) <= 3.6)
                            on_sky_g |= (np.abs(uh) <= 3.7) & (np.abs(vh - v_c) <= 2.9)
                        if on_sky_f.any():
                            r_alb[fi_r[hi_rf[on_sky_f]]] = [212.0, 214.0, 216.0]
                            r_alb[fi_r[hi_rf[on_sky_g]]] = [64.0, 96.0, 134.0] if not preset.is_night else [248.0, 208.0, 118.0]

                    # Outer 0.50m crisp light-limestone/aluminum parapet coping rim & inner drop shadow!
                    is_coping = est == 1
                    is_p_sh = est == 2
                    r_alb[fi_r[is_coping]] = np.clip(r_alb[fi_r[is_coping]] * 0.35 + np.array([144.0, 142.0, 138.0]), 146.0, 228.0)
                    r_alb[fi_r[is_p_sh]] *= 0.76

                # 3. Glitch-Free Architectural Rooftop Solar PV Arrays (strictly from morphologically verified pv_clean_05m!
                # ZERO blue shadow static noise anywhere on roofs!)
                pv_c05 = np.clip(((re_r - E_MIN) * 2.0).astype(np.int32), 0, GRID_W - 1)
                pv_r05 = np.clip(((N_MAX - rn_r) * 2.0).astype(np.int32), 0, GRID_H - 1)
                is_pv = scene.pv_clean_05m[pv_r05, pv_c05]
                if is_pv.any():
                    pvi = np.nonzero(is_pv)[0]
                    # Crisp deep-navy solar panels with clean 1px silver aluminum module grid!
                    pv_grid = (((re_r[pvi] * 0.90) % 1.0) < 0.10) | (((rn_r[pvi] * 0.90) % 1.0) < 0.10)
                    r_alb[pvi] = [32.0, 54.0, 96.0]
                    r_alb[pvi[pv_grid]] = [166.0, 176.0, 190.0]

                f_col[rm] = r_alb

            # -----------------------------------------------------------------
            # B. WALL PIXELS: Rich Tactile Swiss Stucco, Shutters, Balconies & Landmarks!
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

                # Subtle tactile plaster / stone masonry micro-texture (kills flat untextured wall boxes!)
                wh_tex = ((np.floor(w_u * 3.0).astype(np.int32) * 73856093) ^ (np.floor(w_z * 3.0).astype(np.int32) * 19349663)) & 31
                w_base[wh_tex < 6] *= 0.97
                w_base[wh_tex > 26] = np.minimum(246.0, w_base[wh_tex > 26] * 1.025)

                # Crisp stone foundation plinth, deep roof eave shadow, and subtle vertical corner shade!
                w_base[h_rel < 0.65] *= 0.82
                w_base[(top_dist > 0.0) & (top_dist < 0.50)] *= 0.78
                w_base[(edge_dist < 0.28) & (wall_len > 3.2)] *= 0.92

                # Buff-brick Lindt smokestack (bi == 1773)
                is_chimney = w_bi == 1773
                if is_chimney.any():
                    ch_i = np.nonzero(is_chimney)[0]
                    ch_course = ((w_z[ch_i] * 1.4) % 1.0) < 0.25
                    w_base[ch_i[ch_course]] *= 0.93
                    ch_cap = top_dist[ch_i] < 1.55
                    w_base[ch_i[ch_cap]] = [86.0, 82.0, 78.0]

                # B1. Lindt Home of Chocolate (Building 1443, style 2)
                is_hoc = w_sty == 2
                if is_hoc.any():
                    hi_l = np.nonzero(is_hoc)[0]
                    le, ln, lz, lh = w_e[hi_l], w_n[hi_l], w_z[hi_l], h_rel[hi_l]
                    lu = u_local[hi_l]
                    in_white_curve = (le >= 2684107.5) & (ln >= 1241401.5) & (ln <= 1241437.2)
                    w_base[hi_l[in_white_curve]] = [238.0, 236.0, 230.0]
                    # Subtle horizontal glazed white brick courses on curved atrium!
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
                        if preset.is_night:
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
                        else:
                            w_base[hw_idx] = [48.0, 68.0, 92.0]
                            f_mat[wi[hw_idx]] = M_WINDOW_DAY

                # B1b. Main Seestrasse 204 Lindt & Sprüngli Complex (Building 1642, 1473, 1720)
                is_1642 = w_bi == 1642
                if is_1642.any():
                    m_i = np.nonzero(is_1642)[0]
                    me, mn, mz, mh = w_e[m_i], w_n[m_i], w_z[m_i], h_rel[m_i]
                    mu = u_local[m_i]
                    mtd = top_dist[m_i]

                    # Clean stately 1899 red clinker-brick wing with limestone pilasters & cornice (no noisy checker spam!)
                    wing_poly = mn >= 1241403.0
                    if wing_poly.any():
                        pi = m_i[wing_poly]
                        ph = mh[wing_poly]
                        pu = mu[wing_poly]
                        pz = mz[wing_poly]
                        pcol = np.full((len(pi), 3), [158.0, 66.0, 50.0], dtype=np.float32)
                        brick_line = ((pz * 2.2) % 1.0) < 0.22
                        pcol[brick_line] *= 0.90
                        # Clean vertical limestone pilasters every 4.2m + crisp horizontal stringcourse per floor
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

                is_south_prod = (w_bi == 1473) | (w_bi == 1720)
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

                    quoin = (s_bi == 1715) & (s_edg < 0.52) & (((np.floor(sz_w * 1.3).astype(np.int32)) % 2) == 0)
                    w_base[si_l[quoin]] = [196.0, 184.0, 164.0]

                    rk_tower = (s_bi == 1715) & (se_w >= 2683407.6)
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
                            if preset.is_night:
                                f_mat[wi[ck_g[is_gold]]] = M_WINDOW_LIT

                    rk_nave = (s_bi == 1715) & (se_w < 2683407.6) & (s_edg >= 1.6)
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
                            else:
                                w_base[lg_idx] = [48.0, 68.0, 92.0]
                                f_mat[wi[lg_idx]] = M_WINDOW_DAY

                    st_el_tower = s_bi == 1254
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

                    st_el_nave = (s_bi == 1309) & (s_edg >= 1.8)
                    if st_el_nave.any():
                        en_i = np.nonzero(st_el_nave)[0]
                        en_glob = si_l[en_i]
                        clere = (sh_w[en_i] >= 9.5) & (sh_w[en_i] <= 12.2) & (((s_ul[en_i] % 2.8) >= 0.45))
                        if clere.any():
                            cg_idx = en_glob[clere]
                            w_base[cg_idx] = [255.0, 218.0, 128.0] if preset.is_night else [58.0, 82.0, 108.0]
                            f_mat[wi[cg_idx]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY

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
                    bend_gable = (o_bi == 1402) & (oz > (oeave - 0.15))
                    w_base[oi[bend_gable]] = [224.0, 222.0, 216.0]
                    bend_win = (o_bi == 1402) & (oz <= (oeave - 0.35)) & (oh >= 1.0) & (oh <= 3.1) & (np.abs(odc) <= 2.2)
                    w_base[oi[bend_win]] = [56.0, 78.0, 98.0]

                    reg_outb = o_bi != 1402
                    is_door_face = reg_outb & (((o_bi + odb) % 3) == 0) & (owlen >= 3.2)
                    gdoor = is_door_face & (np.abs(odc) <= 1.05) & (oh >= 0.08) & (oh <= 2.25)
                    tiny_w = reg_outb & (~is_door_face) & (owlen >= 3.6) & (np.abs(odc) <= 0.45) & (oh >= 1.15) & (oh <= 2.05)
                    w_base[oi[gdoor]] = [92.0, 64.0, 44.0]
                    w_base[oi[tiny_w]] = [52.0, 68.0, 88.0]

                # B4. Residential Houses (0), Modern Villas (1) & Lindt Campus Wings (3)
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

                    slab_line = (r_sty == 1) & (r_wlen >= 9.0) & (r_h >= 2.8) & (((r_h % 3.15) < 0.24))
                    w_base[ri_l[slab_line]] *= 0.85

                    pilaster = (r_sty == 3) & (~((r_bi_w == 1642) & (r_n < 1241362.0))) & (r_bi_w != 1473) & (r_bi_w != 1720) & ((r_uloc % 10.5) < 0.55)
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
                        | ((r_sty == 3) & ((bay_idx % 5) == 4) & (r_bi_w != 1473))
                    )

                    blind_tower_shaft = (r_bi_w == 1642) & (r_n >= 1241342.0) & (r_n < 1241362.0) & (r_e >= 2684225.0) & (r_h >= 5.2) & (r_h <= 19.8)
                    south_blind_floor = (
                        (((r_bi_w == 1642) & (r_n < 1241342.0)) | (r_bi_w == 1473) | (r_bi_w == 1720))
                        & (r_h >= 4.2)
                        & ((bldg_z1[r_bi_w] - r_z) > 4.4)
                    )

                    is_door_bay = (r_sty == 0) & (fl_idx == 0) & (bay_idx == (n_bays // 2)) & ((wall_hash % 2) == 0)
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

                    skip_gf_win = (r_sty == 0) & (fl_idx == 0) & (((bay_hash >> 3) % 3) == 0)

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
                    )
                    is_pane = active_bay & (in_z >= z_lo) & (in_z <= z_hi) & (np.abs(bay_center_offset) <= half_w)

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

                    is_shutter = (
                        (r_sty == 0)
                        & active_bay
                        & (r_bi_w != 981)
                        & (r_bi_w != 1823)
                        & (r_bi_w != 1490)
                        & (r_bi_w != 1726)
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
                            [(sb_id == 1582) | (sb_id == 1695), sh_mode == 0, sh_mode == 1, sh_mode == 2, sh_mode == 3, sh_mode == 4],
                            [166.0, 46.0, 62.0, 68.0, 126.0, 92.0],
                            default=52.0,
                        )
                        sh_col_g = np.select(
                            [(sb_id == 1582) | (sb_id == 1695), sh_mode == 0, sh_mode == 1, sh_mode == 2, sh_mode == 3, sh_mode == 4],
                            [180.0, 86.0, 104.0, 124.0, 48.0, 66.0],
                            default=94.0,
                        )
                        sh_col_b = np.select(
                            [(sb_id == 1582) | (sb_id == 1695), sh_mode == 0, sh_mode == 1, sh_mode == 2, sh_mode == 3, sh_mode == 4],
                            [198.0, 58.0, 162.0, 110.0, 46.0, 46.0],
                            default=68.0,
                        )
                        w_base[sh_g] = np.stack([sh_col, sh_col_g, sh_col_b], axis=1)

                    is_sill = active_bay & (in_z >= (z_lo - 0.08)) & (in_z < z_lo) & (np.abs(bay_center_offset) <= (half_w + 0.14))
                    w_base[ri_l[is_sill]] = np.minimum(242.0, w_base[ri_l[is_sill]] * 1.10)

                    if is_pane.any():
                        p_sub = np.nonzero(is_pane)[0]
                        p_local = ri_l[p_sub]
                        p_global = wi[p_local]
                        p_bi = r_bi_w[p_sub]
                        p_fl = fl_idx[p_sub]
                        p_bay = bay_idx[p_sub]
                        p_inz = in_z[p_sub]
                        p_bco = bay_center_offset[p_sub]

                        if preset.is_night:
                            hval = ((p_bi.astype(np.int64) * 73856093) ^ (p_fl.astype(np.int64) * 40503) ^ (p_bay.astype(np.int64) * 12289)) & 0xFF
                            lit = hval < 138
                            warm_alt = (hval & 3) == 0
                            lit_c = np.where(warm_alt[:, None], [255.0, 228.0, 148.0], [255.0, 192.0, 92.0])
                            w_base[p_local] = np.where(lit[:, None], lit_c, [30.0, 42.0, 64.0])
                            f_mat[p_global] = np.where(lit, M_WINDOW_LIT, M_WINDOW_DAY)
                        else:
                            mullion = np.abs(p_bco) < 0.08
                            upper_glint = p_inz > 0.56
                            pane_c = np.where(upper_glint[:, None], [78.0, 108.0, 138.0], [38.0, 52.0, 72.0])
                            pane_c[mullion] = [188.0, 184.0, 176.0]
                            w_base[p_local] = pane_c
                            f_mat[p_global] = M_WINDOW_DAY

                f_col[wi] = w_base

            zbuf[fy, fx] = fd
            rgb_buf[fy, fx] = f_col
            mat_buf[fy, fx] = f_mat
            obj_buf[fy, fx] = bi + 1
            norm_buf[fy, fx] = norms_v[ft]
            shadow_buf[fy, fx] = False

    # Slender 1px corner pillars for open Flugdach canopies
    for b in scene.buildings:
        if b["objektart"] in ("Flugdach", "Offenes Gebaeude"):
            be_c, bn_c = b["e"], b["n"]
            if crop_box_lv95 is not None:
                if not (crop_box_lv95[0] + 2 <= be_c <= crop_box_lv95[2] - 2 and crop_box_lv95[1] + 2 <= bn_c <= crop_box_lv95[3] - 2):
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

    # 3D Pixel-Art Rooftop Brick Chimneys (pitched Swiss houses) & Architectural HVAC/Skylight Boxes (flat roofs)!
    for b in scene.buildings:
        bi_r = b["idx"]
        obj_r = b["objektart"]
        if obj_r in ("Hochkamin", "Lagertank", "Flugdach", "Offenes Gebaeude", "Mauer gross", "Sakraler Turm"):
            continue
        be_c, bn_c = b["e"], b["n"]
        if crop_box_lv95 is not None:
            if not (crop_box_lv95[0] + 2 <= be_c <= crop_box_lv95[2] - 2 and crop_box_lv95[1] + 2 <= bn_c <= crop_box_lv95[3] - 2):
                continue
        fw, fl = b["footprint_w"], b["footprint_l"]
        if fw < 6.0 or fl < 6.0:
            continue
        # Quick screen-space cull
        px_r, py_r, _ = camera.project(np.array([be_c]), np.array([bn_c]), np.array([b["z_roof"]]))
        if px_r[0] + shift_x < -20 or px_r[0] + shift_x > W + 20 or py_r[0] + shift_y < -20 or py_r[0] + shift_y > H + 20:
            continue

        b_seed = ((bi_r * 73856093) ^ 0x5A3C) & 0xFF
        if scene.bldg_is_pitched[bi_r] and (b_seed % 5) < 2 and obj_r != "Sakrales Gebaeude":
            # Crisp Swiss terracotta/stone chimney stack protruding just beside the roof ridge!
            off_e = (((b_seed & 7) / 7.0) - 0.5) * min(2.4, fw * 0.24)
            off_n = ((((b_seed >> 3) & 7) / 7.0) - 0.5) * min(2.4, fl * 0.24)
            z_top_ch = b["z_roof"] + 0.95
            z_bot_ch = max(b["z_ground"] + 2.0, b["z_roof"] - 1.4)
            ch_col = (152.0, 96.0, 76.0) if (b_seed & 1) == 0 else (168.0, 162.0, 152.0)
            _draw_3d_box_column(
                camera, shift_x, shift_y, W, H,
                zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                be_c + off_e, bn_c + off_n, z_bot_ch, z_top_ch,
                0.38, ch_col, bi_r + 1, M_WALL,
            )
            # Crisp dark chimney cap rim at top
            _draw_3d_box_column(
                camera, shift_x, shift_y, W, H,
                zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                be_c + off_e, bn_c + off_n, z_top_ch - 0.15, z_top_ch + 0.14,
                0.45, (74.0, 74.0, 78.0), bi_r + 1, M_WALL,
            )
        elif (not scene.bldg_is_pitched[bi_r]) and fw >= 12.0 and fl >= 12.0 and (b_seed % 3) != 0:
            # Clean silver-grey rooftop HVAC / elevator penthouse unit on larger flat roofs!
            off_e = (((b_seed & 7) / 7.0) - 0.5) * min(4.0, fw * 0.22)
            off_n = ((((b_seed >> 3) & 7) / 7.0) - 0.5) * min(4.0, fl * 0.22)
            z_rf = b["z_roof"]
            _draw_3d_box_column(
                camera, shift_x, shift_y, W, H,
                zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
                be_c + off_e, bn_c + off_n, z_rf - 0.2, z_rf + 1.05,
                1.15, (166.0, 168.0, 172.0), bi_r + 1, M_WALL,
            )

    # -------------------------------------------------------------------------
    # STAGE 4: Sculpted 90s Pixel-Art 3D Trees & Trimmed Garden Hedges!
    # -------------------------------------------------------------------------
    _render_sculpted_pixel_art_trees_and_hedges(
        scene, camera, shift_x, shift_y, W, H, r0, r1, c0, c1,
        sub_mask, sub_dem, sub_chm, sub_shadow,
        zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, shadow_buf,
        sun_vec, crop_box_lv95,
    )

    # -------------------------------------------------------------------------
    # STAGE 5: Physically Normalized 90s Stepped Lighting + Sel-Out + 256-Color Dither
    # -------------------------------------------------------------------------
    active_px = mat_buf > M_DROP_SHADOW
    ay, ax = np.nonzero(active_px)

    if len(ay) > 0:
        n_xyz = norm_buf[ay, ax]
        ndotl = np.clip(
            n_xyz[:, 0] * sun_vec[0] + n_xyz[:, 1] * sun_vec[1] + n_xyz[:, 2] * sun_vec[2],
            0.0,
            1.0,
        )
        ndotl = np.where(shadow_buf[ay, ax], ndotl * 0.14, ndotl)
        ndotl_step = np.round(ndotl * 6.0) / 6.0

        amb = np.array(preset.amb_rgb, dtype=np.float32)
        sun_c = np.array(preset.sun_rgb, dtype=np.float32)
        sky_dome = (0.5 + 0.5 * np.clip(n_xyz[:, 2], -1.0, 1.0))[:, None]
        lit_mult = amb[None, :] * (0.72 + 0.28 * sky_dome) + sun_c[None, :] * ndotl_step[:, None] * 0.67

        base_f = rgb_buf[ay, ax]
        shaded = base_f * lit_mult

        m_here = mat_buf[ay, ax]
        is_cut_w = m_here == M_CUTAWAY_WATER
        if is_cut_w.any():
            shaded[is_cut_w] = base_f[is_cut_w] * (0.48 if preset.is_night else 0.94)

        if preset.is_night:
            is_emissive = m_here == M_WINDOW_LIT
            shaded[is_emissive] = base_f[is_emissive]

        rgb_buf[ay, ax] = np.clip(shaded, 0.0, 255.0)

    _apply_pixel_art_outlines_float(rgb_buf, zbuf, obj_buf, mat_buf, norm_buf, preset.is_night)

    dither_map = bayer_tiled.copy()
    clean_m = np.isin(mat_buf, [M_WALL, M_WINDOW_LIT, M_WINDOW_DAY, M_BG, M_TREE, M_BRIDGE])
    dither_map[clean_m] *= 0.28

    final_u8 = quantize_to_90s_palette(rgb_buf, dither_map, preset.dither_strength)

    hit_data = {}
    if collect_hit_boxes and viewport_win is None:
        hit_data = _extract_interactive_metadata(scene, camera, shift_x_full, shift_y_full, W_full, H_full)

    img = Image.fromarray(final_u8, mode="RGB")
    if add_frame and viewport_win is None:
        img = _draw_museum_cartouche(img, preset, camera, len(scene.buildings), len(scene.tree_e), crop_box_lv95)

    if out_depth_buf is not None:
        out_depth_buf["zbuf"] = zbuf
        out_depth_buf["mat_buf"] = mat_buf

    return img, hit_data


def _apply_pixel_art_outlines_float(
    rgb_buf: np.ndarray,
    zbuf: np.ndarray,
    obj_buf: np.ndarray,
    mat_buf: np.ndarray,
    norm_buf: np.ndarray,
    is_night: bool,
) -> None:
    """Apply refined 1px 90s selective pixel-art outlines (sel-out) on buildings, viaducts, trees & roof ridges."""
    dz_r = zbuf[:, 1:] - zbuf[:, :-1]
    dz_d = zbuf[1:, :] - zbuf[:-1, :]
    diff_r = obj_buf[:, 1:] != obj_buf[:, :-1]
    diff_d = obj_buf[1:, :] != obj_buf[:-1, :]

    is_bldg_or_br = (mat_buf == M_WALL) | (mat_buf == M_ROOF) | (mat_buf == M_BRIDGE) | (mat_buf == M_HARBOR_OBJ)
    is_tree_m = mat_buf == M_TREE

    # Crisp 0.65m silhouette threshold for buildings & viaducts, 0.95m for individual 3D trees!
    bldg_edge = np.zeros(zbuf.shape, dtype=np.bool_)
    bldg_edge[:, :-1] |= diff_r & (dz_r > 0.65) & is_bldg_or_br[:, :-1]
    bldg_edge[:, 1:] |= diff_r & (dz_r < -0.65) & is_bldg_or_br[:, 1:]
    bldg_edge[:-1, :] |= diff_d & (dz_d > 0.65) & is_bldg_or_br[:-1, :]
    bldg_edge[1:, :] |= diff_d & (dz_d < -0.65) & is_bldg_or_br[1:, :]

    # Crisp roof-to-wall eave seam on the same building!
    eave_d = (obj_buf[:-1, :] == obj_buf[1:, :]) & (mat_buf[:-1, :] == M_ROOF) & (mat_buf[1:, :] == M_WALL)
    bldg_edge[:-1, :] |= eave_d

    tree_edge = np.zeros(zbuf.shape, dtype=np.bool_)
    tree_edge[:, :-1] |= diff_r & (dz_r > 0.95) & is_tree_m[:, :-1]
    tree_edge[:, 1:] |= diff_r & (dz_r < -0.95) & is_tree_m[:, 1:]
    tree_edge[:-1, :] |= diff_d & (dz_d > 0.95) & is_tree_m[:-1, :]
    tree_edge[1:, :] |= diff_d & (dz_d < -0.95) & is_tree_m[1:, :]

    if bldg_edge.any():
        ey, ex = np.nonzero(bldg_edge)
        rgb_buf[ey, ex] *= 0.58 if not is_night else 0.62
    if tree_edge.any():
        ty, tx = np.nonzero(tree_edge)
        # Soft botanical dark-green sel-out (kills heavy black cartoon circles around canopies!)
        rgb_buf[ty, tx] *= np.array([0.70, 0.76, 0.72], dtype=np.float32) if not is_night else 0.74

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
) -> Image.Image:
    draw = ImageDraw.Draw(img)
    W, H = img.size

    lg_px = min(38, max(18, W // 180))
    sm_px = min(24, max(13, W // 290))
    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", lg_px)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", sm_px)
    except Exception:
        font_lg = ImageFont.load_default()
        font_sm = ImageFont.load_default()

    border_outer = (88, 98, 118) if not preset.is_night else (58, 72, 102)
    border_inner = (168, 156, 132) if not preset.is_night else (138, 118, 86)
    draw.rectangle([10, 10, W - 11, H - 11], outline=border_outer, width=2)
    draw.rectangle([16, 16, W - 17, H - 17], outline=border_inner, width=1)

    sw = lg_px + sm_px + 10
    sx0, sy0 = 36, 30
    draw.rectangle([sx0, sy0, sx0 + sw, sy0 + sw], fill=(208, 38, 38), outline=(246, 243, 236), width=2)
    arm_w = max(4, sw // 4)
    arm_l = int(sw * 0.62)
    cx_s, cy_s = sx0 + sw // 2, sy0 + sw // 2
    draw.rectangle([cx_s - arm_w // 2, cy_s - arm_l // 2, cx_s + arm_w // 2, cy_s + arm_l // 2], fill=(250, 250, 248))
    draw.rectangle([cx_s - arm_l // 2, cy_s - arm_w // 2, cx_s + arm_l // 2, cy_s + arm_w // 2], fill=(250, 250, 248))

    title = "KILCHBERG ZH  —  90s 3D ISOMETRIC PIXEL ART DIORAMA"
    sub = (
        f"256-COLOR SVGA PALETTE  |  {preset.name.upper()}  |  {camera.mpp:.2f} m/px  |  "
        f"{n_bldgs:,} LOD2 3D BUILDINGS  ·  {n_trees:,} 3D TREES  ·  SWISSTOPO GIS"
    )
    tx = sx0 + sw + 18
    draw.text((tx, sy0), title, fill=(246, 241, 228), font=font_lg)
    draw.text((tx, sy0 + lg_px + 8), sub, fill=(176, 188, 206), font=font_sm)

    bar_m = 100 if crop_box_lv95 is not None else 250
    bar_px = int(round(bar_m / camera.mpp))
    bx1 = W - 42
    bx0 = bx1 - bar_px
    by = H - 40
    draw.rectangle([bx0, by - 6, bx1, by], fill=(238, 232, 218), outline=(32, 38, 48), width=1)
    draw.rectangle([bx0, by - 6, bx0 + bar_px // 2, by], fill=(208, 48, 44))
    draw.text((bx0, by - 26), f"{bar_m} m (2:1 Isometric)", fill=(214, 220, 230), font=font_sm)

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
    full_rgb = np.empty((H_full, W_full, 3), dtype=np.uint8)

    # Export 1/2-res (0.5 m/px -> 6165x2722!) 16-bit 3D Depth & Occluder Map during 'day' pass
    # (geometry is identical across day/sunset/night!) for pixel-exact partial vehicle occlusion!
    DEPTH_DS = 2
    DEPTH_MIN = -2400.0
    DEPTH_MAX = 2400.0
    save_depth = preset_key == "day"
    if save_depth:
        dw_f = W_full // DEPTH_DS
        dh_f = H_full // DEPTH_DS
        depth_rgb = np.zeros((dh_f, dw_f, 3), dtype=np.uint8)
        depth_rgb[:, :, 0] = 255
        depth_rgb[:, :, 1] = 255

    nx_macro, ny_macro = 6, 3
    guard = 6
    for my in range(ny_macro):
        y0 = (my * H_full) // ny_macro
        y1 = ((my + 1) * H_full) // ny_macro
        for mx in range(nx_macro):
            x0 = (mx * W_full) // nx_macro
            x1 = ((mx + 1) * W_full) // nx_macro

            wx0 = max(0, x0 - guard)
            wy0 = max(0, y0 - guard)
            wx1 = min(W_full, x1 + guard)
            wy1 = min(H_full, y1 + guard)

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
            sub_arr = np.asarray(sub_img)
            full_rgb[y0:y1, x0:x1] = sub_arr[(y0 - wy0) : (y1 - wy0), (x0 - wx0) : (x1 - wx0)]

            if save_depth and dbuf:
                # Sample exact 3D occluder depth at 1/4 resolution for this macro window
                sz = dbuf["zbuf"]
                sm = dbuf["mat_buf"]
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
                    occ_m = (
                        (m_blk == M_WALL)
                        | (m_blk == M_ROOF)
                        | (m_blk == M_WINDOW_DAY)
                        | (m_blk == M_WINDOW_LIT)
                        | (m_blk == M_TREE)
                        | (m_blk == M_TRUNK)
                        | (m_blk == M_BRIDGE)
                        | (m_blk == M_RAIL)
                        | (m_blk == M_HARBOR_OBJ)
                    )
                    occ_cnt = occ_m.sum(axis=(1, 3))
                    has_occ = occ_cnt >= 1
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

            del sub_img, sub_arr
            gc.collect()

    if save_depth:
        depth_path = overview_webp_path.parent / "kilchberg_depth.png"
        Image.fromarray(depth_rgb, mode="RGB").save(depth_path, optimize=True)
        print(f"[render] Saved 16-bit 3D Depth & Occluder Map -> {depth_path} ({dw_f}x{dh_f})")
        del depth_rgb

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
