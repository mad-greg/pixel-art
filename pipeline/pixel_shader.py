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
        name="90s SVGA Crisp Midday",
        sun_az_deg=124.0,
        sun_alt_deg=43.0,
        sun_rgb=(1.00, 0.99, 0.96),
        amb_rgb=(0.54, 0.55, 0.58),
        sky_top_rgb=(24, 34, 52),
        sky_bot_rgb=(38, 52, 74),
        is_night=False,
        dither_strength=8.0,
    ),
    "sunset": LightingPreset(
        name="Alpenglow Golden Sunset",
        sun_az_deg=114.0,
        sun_alt_deg=22.0,
        sun_rgb=(1.12, 0.76, 0.50),
        amb_rgb=(0.42, 0.39, 0.52),
        sky_top_rgb=(34, 26, 48),
        sky_bot_rgb=(70, 44, 60),
        is_night=False,
        dither_strength=9.0,
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
        dither_strength=8.0,
    ),
}


@lru_cache(maxsize=1)
def build_90s_palette_and_lut() -> tuple[np.ndarray, np.ndarray]:
    """Construct a curated 256-color 90s SVGA isometric city-builder palette calibrated to
    authentic Swiss architecture, clinker brick, neutral concrete, terracotta roofs & Zürichsee water."""
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

    # 1. Lush 90s Pixel-Art Swiss Foliage Greens (emerald, oak, sunlit lime, conifer, sedum, copper beech) — 40 colors
    add_ramp((14, 32, 20), (42, 96, 44), (118, 184, 76), 10)
    add_ramp((18, 38, 26), (56, 116, 52), (146, 204, 90), 9)
    add_ramp((16, 36, 30), (34, 78, 56), (82, 142, 96), 7)     # Conifers / dark yew hedges
    add_ramp((34, 40, 22), (88, 108, 48), (158, 176, 88), 8)   # Sedum green roofs, vineyards & dry meadow
    add_ramp((34, 18, 24), (96, 44, 48), (162, 82, 78), 6)     # Copper beech (Blutbuche)

    # 2. Clinker Brick, Swiss Clay Roofs, Neutral Gravel/Concrete & Taupe-Greige Facades — 48 colors
    add_ramp((42, 16, 16), (124, 44, 36), (178, 68, 54), 8)     # Deep Swiss ziegelrot clinker & 1899 red brick
    add_ramp((52, 24, 18), (148, 72, 46), (212, 114, 74), 8)    # Classic Swiss terracotta clay roof tiles
    add_ramp((38, 26, 20), (106, 72, 52), (176, 130, 98), 8)    # Weathered brown clay tile & dark barn timber
    add_ramp((24, 26, 30), (96, 98, 102), (218, 220, 224), 8)   # Neutral anthracite / concrete / silver flat roof
    add_ramp((20, 28, 48), (44, 64, 104), (96, 132, 182), 8)    # Rooftop solar PV arrays & skylights
    add_ramp((46, 44, 40), (132, 126, 114), (196, 190, 176), 8) # Pebble-greige stucco & Lindt concrete frame

    # 3. Swiss Plaster Facades, Butter-Ochre, Dusty Rose, Sage Green & Shutters — 52 colors
    add_ramp((52, 52, 56), (154, 152, 146), (242, 240, 234), 10)# Glazed white brick, alabaster & off-white plaster
    add_ramp((52, 42, 32), (150, 134, 108), (224, 210, 182), 10)# Warm travertine, sand & cream stucco
    add_ramp((62, 48, 22), (172, 144, 68), (242, 216, 112), 10) # Butter-yellow villas, buff brick, gold & crosswalks
    add_ramp((56, 36, 34), (148, 106, 94), (214, 172, 156), 8)  # Historic dusty rose / terracotta-salmon stucco
    add_ramp((26, 48, 42), (76, 124, 108), (158, 192, 172), 6)  # Sage/pistachio pavilion, copper patina & teal shutters
    add_ramp((18, 26, 40), (54, 82, 124), (118, 156, 204), 8)   # Window glass & cornflower/dove-blue Swiss shutters

    # 4. Streets, Asphalt, Courtyards, Railway Ballast & Cutaway Strata — 26 colors
    add_ramp((18, 20, 26), (78, 82, 90), (194, 196, 200), 14)    # Asphalt -> concrete -> white markings
    add_ramp((34, 30, 26), (96, 86, 74), (172, 158, 138), 12)    # Molasse sandstone, gravel & ballast

    # 5. Authentic Alpine Lake Zurich (Zürichsee jade-emerald -> deep alpine blue-teal) + Pools — 42 colors
    add_ramp((12, 24, 34), (24, 62, 82), (44, 102, 114), 14)     # Deep alpine Zürichsee blue-teal
    add_ramp((28, 52, 48), (56, 108, 96), (118, 172, 154), 14)   # Nearshore Zürichsee jade-olive & shallows
    add_ramp((32, 104, 138), (68, 184, 214), (196, 242, 248), 14)# Crystal backyard pools & shore foam

    # 6. Sunset Alpenglow, Night Twilight, Lantern Golds & Swiss Crest Red — 48 colors
    add_ramp((12, 16, 30), (34, 42, 68), (76, 88, 126), 12)      # Night indigo shadows & backdrop
    add_ramp((34, 24, 46), (86, 52, 68), (178, 104, 88), 12)     # Sunset violet-rose alpenglow
    add_ramp((92, 58, 24), (212, 148, 54), (255, 238, 166), 14)  # Lit amber/gold windows & lamps
    add_ramp((96, 20, 20), (196, 38, 38), (248, 96, 88), 10)     # Swiss crest red & harbor buoys

    pal = np.array(colors[:256], dtype=np.uint8)
    assert len(pal) == 256

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
    """Loaded Kilchberg 0.5m rasters, 3D bridges/viaducts, 25cm parapet masks, 3D LOD2 buildings & trees."""

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

        # Precompute 0.5m bare-earth terrain normals
        dz_drow, dz_dcol = np.gradient(ndimage.gaussian_filter(self.dem, sigma=0.75), GRID_RES)
        nx, ny, nz = -dz_dcol, dz_drow, np.ones_like(dz_dcol)
        nlen = np.sqrt(nx * nx + ny * ny + nz * nz)
        self.terr_nx = (nx / nlen).astype(np.float32)
        self.terr_ny = (ny / nlen).astype(np.float32)
        self.terr_nz = (nz / nlen).astype(np.float32)

        # Clean 0.5m mask of REAL moored boats, piers & Seebad rafts
        o_f = self.ortho_05m.astype(np.float32)
        lum05 = 0.299 * o_f[:, :, 0] + 0.587 * o_f[:, :, 1] + 0.114 * o_f[:, :, 2]
        bg_lum05 = ndimage.uniform_filter(lum05, size=29)
        open_water = ndimage.binary_erosion(self.lake_mask, iterations=3, border_value=0)
        is_pier = self.sem == G_PLATFORM_PIER
        is_lidar_obj = open_water & (self.chm >= 0.55) & (lum05 > 88.0) & ((o_f[:, :, 1] - o_f[:, :, 0]) < 8.0)
        is_bright_float = open_water & (lum05 > 106.0) & ((lum05 - bg_lum05) > 24.0)
        cand_float = (is_lidar_obj | is_bright_float) & (~is_pier)
        lbl_f, n_f = ndimage.label(cand_float)
        clean_float = np.zeros_like(cand_float)
        if n_f > 0:
            counts = np.bincount(lbl_f.ravel())
            valid_lbl = (counts >= 2) & (counts <= 1040)
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
            # Filter out overhanging green tree leaves unless building is genuinely a green eco-roof
            not_leaf = (vals[:, 1] - vals[:, 0]) <= 8.0
            good = (ds > 0.22) & (lm > 48.0) & (lm < 236.0) & not_leaf
            if good.sum() >= max(1, int(0.18 * cnt_u)):
                self.bldg_sunlit_roof_rgb[bi_u] = np.percentile(vals[good], 64, axis=0)
            elif ((ds > 0.22) & (lm > 44.0)).any():
                self.bldg_sunlit_roof_rgb[bi_u] = np.percentile(vals[(ds > 0.22) & (lm > 44.0)], 66, axis=0)
            elif (lm > 42.0).any():
                self.bldg_sunlit_roof_rgb[bi_u] = np.percentile(vals[lm > 42.0], 68, axis=0)

        # Clean up & stylize per-building roof base RGB into authentic 90s pixel-art roof materials
        self.bldg_clean_roof_rgb = np.empty((nb, 3), dtype=np.float32)
        self.bldg_roof_kind = np.zeros(nb, dtype=np.uint8)  # 0=clay_tile, 1=dark_slate, 2=flat_gravel, 3=flat_green, 4=metal
        for i in range(nb):
            rr, rg, rb = self.bldg_sunlit_roof_rgb[i]
            lum_r = 0.299 * rr + 0.587 * rg + 0.114 * rb
            is_pit = bool(self.bldg_is_pitched[i])
            if is_pit:
                if (rr - rb) >= 16.0 and rr >= 105.0:
                    # Rich Swiss terracotta / red-brown clay tile
                    warm = min(1.0, max(0.0, (rr - rg) / 36.0))
                    c_tile = np.array([154.0 + 30.0 * warm, 86.0 + 6.0 * warm, 62.0 - 4.0 * warm], dtype=np.float32)
                    self.bldg_clean_roof_rgb[i] = 0.58 * c_tile + 0.42 * np.clip([rr * 1.06, rg * 0.98, rb * 0.92], 50.0, 212.0)
                    self.bldg_roof_kind[i] = 0
                elif (rr - rb) >= 8.0:
                    # Weathered warm-brown clay tile
                    self.bldg_clean_roof_rgb[i] = np.clip([rr * 1.04, rg * 0.98, rb * 0.94], 76.0, 186.0)
                    self.bldg_roof_kind[i] = 0
                else:
                    # Dark alpine slate / anthracite tile (or copper-patina church spire)
                    base_sl = np.clip(lum_r * 0.96, 68.0, 146.0)
                    self.bldg_clean_roof_rgb[i] = [base_sl * 0.97, base_sl * 0.99, base_sl * 1.04]
                    self.bldg_roof_kind[i] = 1
            else:
                if (rg - rr) > 7.5 and (rg - rb) > 10.0:
                    # Sedum extensive green flat roof
                    self.bldg_clean_roof_rgb[i] = [104.0, 134.0, 74.0]
                    self.bldg_roof_kind[i] = 3
                elif lum_r > 158.0:
                    # Crisp light concrete / silver membrane flat roof
                    v_l = np.clip(lum_r, 156.0, 198.0)
                    self.bldg_clean_roof_rgb[i] = [v_l, v_l * 0.995, v_l * 0.985]
                    self.bldg_roof_kind[i] = 4
                else:
                    # Neutral Swiss washed-pebble gravel flat roof
                    v_g = np.clip(lum_r * 1.02, 108.0, 166.0)
                    self.bldg_clean_roof_rgb[i] = [v_g * 1.01, v_g * 1.00, v_g * 0.98]
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
    """Synthesize 100% crisp, distinctly drawn 90s pixel-art ground, mowed meadows, terraced vineyards,
    clean asphalt streets with sidewalks & zebra crosswalks, SBB railway ballast/sleepers/rails & lake."""
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

    # 1. Default open land (G_TERRAIN, G_PARK_CEMETERY, G_FOREST):
    # Distinguish grass/lawn/meadow from stone courtyards, plazas & gravel drives using SWISSIMAGE!
    is_lawn = ((ro[:, 1] >= ro[:, 0] * 0.95) & ((ro[:, 1] - ro[:, 2]) > 7.5)) | (gsem == G_FOREST) | (gsem == G_PARK_CEMETERY)
    # Lush 90s pixel-art Swiss meadow / lawn with subtle mowed stripes & organic grass tufts!
    mow_stripe = (((np.floor((ge * 0.92 - gn * 0.39) * 0.18).astype(np.int32)) & 1) == 0) & (gsem != G_FOREST)
    tuft = (p_hash < 42)
    dark_tuft = (p_hash >= 42) & (p_hash < 74)
    lawn_col = np.full((n_pts, 3), [74.0, 128.0, 56.0], dtype=np.float32)
    lawn_col[mow_stripe] = [84.0, 140.0, 62.0]
    lawn_col[tuft] += [12.0, 16.0, 6.0]
    lawn_col[dark_tuft] -= [10.0, 14.0, 6.0]
    # Richer mossy forest floor under woodland
    is_for = gsem == G_FOREST
    if is_for.any():
        lawn_col[is_for] = np.where((h50[is_for] < 96)[:, None], [46.0, 82.0, 42.0], [56.0, 96.0, 48.0])
    # Manicured park / cemetery emerald turf with crisp warm gravel walkways
    is_park = gsem == G_PARK_CEMETERY
    if is_park.any():
        park_gravel = is_park & (lum > 112.0) & ((ro[:, 1] - ro[:, 2]) < 11.0)
        lawn_col[is_park] = np.where((p_hash[is_park] < 50)[:, None], [72.0, 134.0, 58.0], [64.0, 122.0, 52.0])
        lawn_col[park_gravel] = [174.0, 164.0, 146.0]

    # Clean stone courtyards, gravel yards & village plazas (non-lawn G_TERRAIN)
    pave_joint = ((ix25 % 4) == 0) | ((iy25 % 4) == 0)
    is_warm_yard = (ro[:, 0] - ro[:, 2]) > 14.0
    yard_col = np.where(is_warm_yard[:, None], [164.0, 152.0, 134.0], [148.0, 148.0, 146.0]).astype(np.float32)
    yard_col[pave_joint] *= 0.92
    yard_col[p_hash < 38] *= 1.05

    gcol[:] = np.where(is_lawn[:, None], lawn_col, yard_col)

    # 2. Terraced Kilchberg Vineyards (G_VINEYARD): warm soil + crisp 3D grapevine trellis rows!
    is_vin = gsem == G_VINEYARD
    if is_vin.any():
        vi = np.nonzero(is_vin)[0]
        # Rows run roughly perpendicular to hillside slope (N-S / NNW-SSE) every 2.0m
        u_row = (ge[vi] * 0.94 + gn[vi] * 0.34) % 2.1
        on_vine = u_row < 0.82
        vcol = np.full((len(vi), 3), [132.0, 114.0, 88.0], dtype=np.float32)  # Warm vineyard soil/grass aisle
        vcol[p_hash[vi] < 80] = [104.0, 126.0, 68.0]  # Grass strip between vine rows
        vine_leaf = np.where((p_hash[vi] < 110)[:, None], [76.0, 136.0, 52.0], [56.0, 108.0, 42.0])
        vcol[on_vine] = vine_leaf[on_vine]
        gcol[vi] = vcol
        gz[vi[on_vine]] += 0.85

    # 3. Sports Pitches & Tennis Courts (G_PITCH)
    is_pitch = gsem == G_PITCH
    if is_pitch.any():
        pi = np.nonzero(is_pitch)[0]
        is_clay_court = (ro[pi, 0] > ro[pi, 1] * 1.12) & (ro[pi, 0] > 95.0)
        pcol = np.full((len(pi), 3), [66.0, 138.0, 62.0], dtype=np.float32)
        p_stripe = ((np.floor((ge[pi] * 0.90 + gn[pi] * 0.44) * 0.22).astype(np.int32)) & 1) == 0
        pcol[p_stripe] = [78.0, 152.0, 70.0]
        pcol[is_clay_court] = [176.0, 96.0, 68.0]
        # Crisp white court / pitch line markings where ortho shows bright line
        bright_line = lum[pi] > 168.0
        pcol[bright_line] = [232.0, 232.0, 228.0]
        gcol[pi] = pcol

    # 4. Streams (G_STREAM)
    is_str = gsem == G_STREAM
    if is_str.any():
        gcol[is_str] = [56.0, 116.0, 128.0]

    # 5. Footpaths & Garden Walkways (G_FOOTPATH): crisp warm limestone gravel + 1px dark edge
    is_fp = gsem == G_FOOTPATH
    if is_fp.any():
        fi = np.nonzero(is_fp)[0]
        fcol = np.where((p_hash[fi] < 95)[:, None], [166.0, 158.0, 144.0], [152.0, 144.0, 132.0]).astype(np.float32)
        gcol[fi] = fcol

    # 6. Parking Lots (G_PARKING): clean slate asphalt + neat white bay lines
    is_pk = gsem == G_PARKING
    if is_pk.any():
        ki = np.nonzero(is_pk)[0]
        kcol = np.where((p_hash[ki] < 70)[:, None], [96.0, 100.0, 108.0], [88.0, 92.0, 100.0]).astype(np.float32)
        bay_line = (((ge[ki] % 2.6) < 0.16) & ((gn[ki] % 5.4) < 4.2))
        kcol[bay_line] = [186.0, 188.0, 192.0]
        gcol[ki] = kcol

    # 7. Minor Village Streets (G_STREET_MINOR): clean 90s pixel-art slate asphalt + crisp 1px granite curb!
    is_min = gsem == G_STREET_MINOR
    if is_min.any():
        mi = np.nonzero(is_min)[0]
        m_d = rd_dist[mi]
        m_hw = np.maximum(2.0, rd_hw[mi])
        mcol = np.where((p_hash[mi] < 65)[:, None], [96.0, 100.0, 108.0], [88.0, 92.0, 100.0]).astype(np.float32)
        curb_m = m_d >= (m_hw - 0.42)
        mcol[curb_m] = [148.0, 148.0, 146.0]
        gutter_m = (m_d >= (m_hw - 0.72)) & (~curb_m)
        mcol[gutter_m] = [70.0, 74.0, 82.0]
        gcol[mi] = mcol

    # 8. Main Roads (G_STREET_MAIN — Seestrasse, Dorfstrasse, Bahnhofstrasse, Alte Landstrasse):
    # Clean slate asphalt, raised granite sidewalks, 1px curbs, dashed white centerlines & Swiss yellow crosswalks!
    is_main = gsem == G_STREET_MAIN
    if is_main.any():
        ai = np.nonzero(is_main)[0]
        a_d = rd_dist[ai]
        a_s = rd_along[ai]
        a_hw = np.maximum(3.8, rd_hw[ai])
        sw_start = a_hw - 1.32

        acol = np.where((p_hash[ai] < 62)[:, None], [90.0, 94.0, 102.0], [82.0, 86.0, 94.0]).astype(np.float32)
        # Subtle asphalt tire-wear track shading
        lane_mid = np.abs(a_d - 1.55) < 0.55
        acol[lane_mid] *= 0.94

        # Crisp white dashed centerline!
        dash_c = (a_d < 0.26) & ((a_s % 5.6) < 2.5)
        acol[dash_c] = [226.0, 228.0, 232.0]

        # Crisp dark gutter + raised light-stone sidewalk with 1.5m paving joints!
        on_curb = (a_d >= (sw_start - 0.30)) & (a_d < sw_start)
        on_sw = a_d >= sw_start
        acol[on_curb] = [62.0, 66.0, 74.0]
        sw_joint = on_sw & ((a_s % 1.6) < 0.22)
        acol[on_sw] = [164.0, 162.0, 156.0]
        acol[sw_joint] = [138.0, 136.0, 132.0]
        gz[ai[on_sw]] += 0.18
        gcol[ai] = acol

    # 8b. Crisp Geometric Swiss Yellow Zebra Crosswalks on Main Roads (Seestrasse, Dorfstrasse, Alte Landstrasse)!
    is_xw = xwalk & (gsem == G_STREET_MAIN)
    if is_xw.any():
        xi = np.nonzero(is_xw)[0]
        # Crisp parallel yellow bars perpendicular to road centerline!
        bar = ((rd_dist[xi] % 0.95) < 0.48) & (rd_dist[xi] <= np.maximum(2.0, rd_hw[xi] - 1.45))
        gcol[xi[bar]] = [236.0, 194.0, 56.0]

    # 9. A3 Motorway (G_MOTORWAY): dark highway asphalt, double dashed lane lines, white shoulders & steel barriers
    is_mw = gsem == G_MOTORWAY
    if is_mw.any():
        wi = np.nonzero(is_mw)[0]
        w_d = rd_dist[wi]
        w_s = rd_along[wi]
        w_hw = np.maximum(3.4, rd_hw[wi])
        wcol = np.where((p_hash[wi] < 55)[:, None], [74.0, 78.0, 86.0], [68.0, 72.0, 80.0]).astype(np.float32)
        # Lane dashes & solid shoulder edge lines
        w_dash = (np.abs(w_d - 1.8) < 0.24) & ((w_s % 6.5) < 2.8)
        w_edge = np.abs(w_d - (w_hw - 0.85)) < 0.25
        w_guard = w_d >= (w_hw - 0.42)
        wcol[w_dash | w_edge] = [228.0, 230.0, 234.0]
        wcol[w_guard] = [154.0, 160.0, 168.0]
        gz[wi[w_guard]] += 0.72
        gcol[wi] = wcol

    # 10. SBB Seebahn Railway (G_RAILWAY): crushed granite ballast, perpendicular sleepers & twin steel rails!
    is_rl = gsem == G_RAILWAY
    if is_rl.any():
        ri = np.nonzero(is_rl)[0]
        r_d = rl_dist[ri]
        r_s = rl_along[ri]
        # Dithered crushed-stone grey-brown granite ballast
        rcol = np.where((p_hash[ri] < 115)[:, None], [116.0, 108.0, 98.0], [96.0, 88.0, 80.0]).astype(np.float32)
        rcol[r_d > 2.05] = [84.0, 78.0, 70.0]  # Ballast embankment shoulder

        # Dark timber/concrete cross-sleepers every 0.85m
        sleeper = (r_d <= 1.22) & ((r_s % 0.85) < 0.30)
        rcol[sleeper] = [64.0, 52.0, 44.0]

        # Twin gleaming parallel steel rails at standard Swiss gauge (+-0.72m from track centerline!)
        rail_steel = np.abs(r_d - 0.72) <= 0.22
        rcol[rail_steel] = [196.0, 202.0, 210.0]
        gz[ri[rail_steel]] += 0.14
        gcol[ri] = rcol
        gmat[ri] = M_RAIL

    # 11. SBB Station Platforms & Lakeside Stone Piers (G_PLATFORM_PIER): raised concrete + tactile safety edge!
    is_pl = (gsem == G_PLATFORM_PIER) & (~glake)
    if is_pl.any():
        pli = np.nonzero(is_pl)[0]
        pcol = np.full((len(pli), 3), [176.0, 174.0, 168.0], dtype=np.float32)
        # Paving slab joints
        slab = ((ix50[pli] % 3) == 0) | ((iy50[pli] % 3) == 0)
        pcol[slab] = [156.0, 154.0, 148.0]
        # Crisp white safety edge stripe facing the railway tracks
        tactile = (rl_dist[pli] >= 1.55) & (rl_dist[pli] <= 2.05)
        pcol[tactile] = [232.0, 232.0, 228.0]
        gcol[pli] = pcol
        gz[pli] += 0.58

    # 12. Crisp Backyard & Lakeside Swimming Pools (G_POOL) with white coping rim
    is_pool = gsem == G_POOL
    if is_pool.any():
        p_i = np.nonzero(is_pool)[0]
        shimmer = ((ix25[p_i] + iy25[p_i]) & 3) == 0
        pcol = np.where(shimmer[:, None], [108.0, 214.0, 236.0], [66.0, 186.0, 216.0]).astype(np.float32)
        gcol[p_i] = pcol
        gnx[p_i], gny[p_i], gnz[p_i] = 0.0, 0.0, 1.0

    # 13. Lake Zurich (Zürichsee): authentic alpine jade-emerald shallows -> deep glacial teal-blue + real boats/piers!
    if glake.any():
        li = np.nonzero(glake)[0]
        is_real_harbor_obj = gharbor[li]

        wi = li[~is_real_harbor_obj]
        if len(wi) > 0:
            depth_m = np.clip(LAKE_SURFACE_Z - gbathy[wi], 0.0, 65.0)
            we_w, wn_w = ge[wi], gn[wi]
            t_sh = np.clip(depth_m / 6.0, 0.0, 1.0)[:, None]
            t_dp = np.clip((depth_m - 6.0) / 30.0, 0.0, 1.0)[:, None]
            w_col = (1.0 - t_sh) * np.array([68.0, 118.0, 102.0]) + t_sh * (
                (1.0 - t_dp) * np.array([38.0, 86.0, 96.0]) + t_dp * np.array([24.0, 60.0, 82.0])
            )
            shallow_tint = np.clip((4.5 - depth_m) / 4.5, 0.0, 1.0)[:, None] * 0.24
            ortho_w = np.clip(raw_ortho[wi].astype(np.float32) * 1.15, 22.0, 165.0)
            w_col = (1.0 - shallow_tint) * w_col + shallow_tint * ortho_w

            ripple = np.sin(we_w * 0.42 + wn_w * 0.31) * np.cos(we_w * 0.19 - wn_w * 0.47)
            w_col += ripple[:, None] * np.array([3.5, 5.5, 5.5])
            shore_f = depth_m < 0.48
            w_col[shore_f] = 0.65 * w_col[shore_f] + 0.35 * np.array([176.0, 212.0, 204.0])
            gcol[wi] = w_col
            gmat[wi] = M_WATER_LAKE
            gnx[wi], gny[wi], gnz[wi] = 0.0, 0.0, 1.0

        bi_h = li[is_real_harbor_obj]
        if len(bi_h) > 0:
            real_h = np.clip(sub_chm_val[bi_h], 0.55, 3.6)
            gz[bi_h] = LAKE_SURFACE_Z + real_h
            is_wpier = gsem[bi_h] == G_PLATFORM_PIER
            hcol = condition_90s_albedo(raw_ortho[bi_h], shadow_knee=70.0, vibrancy=1.18)
            hcol[is_wpier] = np.where((p_hash[bi_h[is_wpier]] < 90)[:, None], [164.0, 154.0, 136.0], [148.0, 138.0, 122.0])
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
    """STAGE 4: Render 100% distinctly drawn 90s pixel-art 3D trees (14,639 real LiDAR trees)
    and neat trimmed garden hedges — zero blurry aerial photo blobs!"""
    # -------------------------------------------------------------------------
    # 4A. Neat Beveled 90s Pixel-Art Garden Hedges (hedge_mask)
    # -------------------------------------------------------------------------
    sub_hedge_raw = sub_mask & scene.hedge_mask[r0:r1, c0:c1]
    # Drop tiny noisy 1px roadside flecks so only genuine trimmed garden hedges render cleanly!
    sub_hedge = ndimage.binary_opening(sub_hedge_raw, structure=np.ones((2, 2), dtype=bool))
    if sub_hedge.any():
        hr, hc = np.nonzero(sub_hedge)
        he = E_MIN + (hc + c0 + 0.5) * GRID_RES
        hn = N_MAX - (hr + r0 + 0.5) * GRID_RES
        hz_base = sub_dem[hr, hc]
        hh = np.clip(sub_chm[hr, hc], 0.90, 1.95)
        h_hash = ((hc + c0) * 19 + (hr + r0) * 37) & 0xF
        # 3-tone crisp privet / boxwood hedge leaf clusters (natural botanical emerald)
        h_top_col = np.where(
            (h_hash < 5)[:, None],
            [68.0, 114.0, 50.0],
            np.where((h_hash < 11)[:, None], [52.0, 96.0, 42.0], [38.0, 76.0, 34.0]),
        ).astype(np.float32)
        h_side_col = h_top_col * 0.78
        # Single shared OID for all hedges so sel-out outlines only appear on outer boundary!
        h_oid = np.full(len(hr), 190000, dtype=np.int32)

        for frac_z, is_top in ((0.40, False), (0.74, False), (1.0, True)):
            zc = hz_base + hh * frac_z
            px, py, pd = camera.project(he, hn, zc)
            ix = np.round(px + shift_x).astype(np.int32)
            iy = np.round(py + shift_y).astype(np.int32)
            vh = (ix >= 0) & (ix < W - 1) & (iy >= 0) & (iy < H - 1)
            if not vh.any():
                continue
            ix, iy, pd = ix[vh], iy[vh], pd[vh]
            col_use = h_top_col[vh] if is_top else h_side_col[vh]
            oid_use = h_oid[vh]
            sh_use = sub_shadow[hr[vh], hc[vh]]
            ord_h = np.argsort(pd)[::-1]
            ix, iy, pd = ix[ord_h], iy[ord_h], pd[ord_h]
            col_use, oid_use, sh_use = col_use[ord_h], oid_use[ord_h], sh_use[ord_h]
            for ox, oy in ((0, 0), (1, 0), (0, 1)):
                tx, ty = ix + ox, iy + oy
                db = pd + (0.04 if (ox or oy) else 0.0)
                win = db < zbuf[ty, tx]
                zbuf[ty[win], tx[win]] = db[win]
                rgb_buf[ty[win], tx[win]] = col_use[win]
                mat_buf[ty[win], tx[win]] = M_TREE
                obj_buf[ty[win], tx[win]] = oid_use[win]
                shadow_buf[ty[win], tx[win]] = sh_use[win]
                norm_buf[ty[win], tx[win], 0] = 0.0 if is_top else 0.45
                norm_buf[ty[win], tx[win], 1] = 0.0 if is_top else -0.45
                norm_buf[ty[win], tx[win], 2] = 0.96 if is_top else 0.65

    # -------------------------------------------------------------------------
    # 4B. All 14,639 Individual Real 3D Pixel-Art Trees!
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

    # Screen-space frustum cull for fast tiled rendering
    px_base, py_base, pd_base = camera.project(te, tn, tz)
    px_top, py_top, _ = camera.project(te, tn, tz + th)
    r_px_est = (trad * 1.35 / camera.mpp) + 10.0
    in_vp = (
        (px_base + shift_x + r_px_est >= -6.0)
        & (px_base + shift_x - r_px_est <= W + 6.0)
        & (py_base + shift_y + 10.0 >= -6.0)
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

    # Sort trees back-to-front by camera depth
    t_ord = np.argsort(pd_base)[::-1]
    te, tn, tz, th, trad, tsp, t_ids = (
        te[t_ord], tn[t_ord], tz[t_ord], th[t_ord], trad[t_ord], tsp[t_ord], t_ids[t_ord]
    )
    px_base, py_base, py_top, pd_base = px_base[t_ord], py_base[t_ord], py_top[t_ord], pd_base[t_ord]

    # Species 4-tone natural botanical SVGA pixel-art foliage ramps: [deep_shadow, mid_shade, sunlit_mid, highlight]
    # Calibrated for Stage 5 sun lighting so greens look rich, painterly & organic (never neon lime!)
    SPECIES_RAMPS = np.array(
        [
            # 0: Deep Swiss Oak / Beech (rich forest emerald)
            [[18.0, 44.0, 24.0], [32.0, 72.0, 34.0], [52.0, 102.0, 44.0], [78.0, 132.0, 56.0]],
            # 1: Sunlit Linden / Maple / Meadow Tree (warm olive-emerald)
            [[24.0, 52.0, 26.0], [42.0, 86.0, 36.0], [66.0, 118.0, 48.0], [98.0, 148.0, 62.0]],
            # 2: Alpine Conifer (Spruce / Silver Fir — cool pine blue-green)
            [[14.0, 34.0, 28.0], [24.0, 56.0, 42.0], [38.0, 80.0, 56.0], [58.0, 106.0, 72.0]],
            # 3: Slender Cypress / Lombardy Poplar
            [[18.0, 40.0, 28.0], [30.0, 66.0, 40.0], [46.0, 92.0, 52.0], [70.0, 118.0, 66.0]],
            # 4: Copper Beech (Blutbuche — deep burgundy-plum)
            [[38.0, 18.0, 22.0], [66.0, 30.0, 34.0], [98.0, 46.0, 46.0], [132.0, 70.0, 64.0]],
        ],
        dtype=np.float32,
    )

    # Precompute screen-space lighting vector (from sun_vec projected onto screen +X, -Y, and front-normal +Z)
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

    # Render each individual tree with natural billowing 90s pixel-art proportions & per-tree obj_buf ID!
    for i in range(len(te)):
        sp_k = int(tsp[i])
        tid = int(t_ids[i])
        oid = 100000 + tid
        h_m = float(th[i])
        r_m = float(trad[i])
        cx0 = float(px_base[i])
        cy0 = float(py_base[i])
        d0 = float(pd_base[i])

        # Natural botanical proportions: broadleaf trees have wide rounded crowns (never vertical pickles!)
        if sp_k in (0, 1, 4):
            r_px = max(3.6, (r_m * 1.24) / mpp)
            h_px = max(7.0, min(h_m * z_px_per_m, r_px * 2.55))
            crown_ry = max(3.4, min(h_px * 0.44, r_px * 0.94))
            trunk_h_px = max(2.2, h_px - crown_ry * 1.92)
        else:
            r_px = max(3.0, (r_m * 1.05) / mpp)
            h_px = max(8.0, min(h_m * z_px_per_m, r_px * 3.8))
            trunk_h_px = max(1.8, h_px * 0.14)
            crown_ry = max(3.2, 0.5 * (h_px - trunk_h_px))

        # 1. Draw crisp dark timber trunk beneath crown
        tx_i = int(round(cx0))
        ty_bot = int(round(cy0))
        ty_top = int(round(cy0 - trunk_h_px - 2.0))
        tw_half = 1 if r_px >= 7.5 else 0
        y_lo_t = max(0, ty_top)
        y_hi_t = min(H - 1, ty_bot)
        x_lo_t = max(0, tx_i - tw_half)
        x_hi_t = min(W - 1, tx_i + tw_half)
        if y_hi_t >= y_lo_t and x_hi_t >= x_lo_t:
            sl_z = zbuf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1]
            d_tr = d0 + 0.15
            w_tr = d_tr < sl_z
            if w_tr.any():
                sl_z[w_tr] = d_tr
                rgb_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = [84.0, 58.0, 38.0]
                mat_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = M_TRUNK
                obj_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = oid
                norm_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = [0.5, -0.5, 0.35]
                shadow_buf[y_lo_t : y_hi_t + 1, x_lo_t : x_hi_t + 1][w_tr] = False

        # 2. Compute tight screen bounding box for this tree's sculpted 3D crown
        crown_bot_y = cy0 - trunk_h_px
        crown_top_y = crown_bot_y - crown_ry * 2.0
        crown_cy = 0.5 * (crown_bot_y + crown_top_y)
        pad_x = int(math.ceil(r_px * 1.25)) + 1

        x0_b = max(0, int(math.floor(cx0)) - pad_x)
        x1_b = min(W - 1, int(math.ceil(cx0)) + pad_x)
        y0_b = max(0, int(math.floor(crown_top_y)) - 3)
        y1_b = min(H - 1, int(math.ceil(crown_bot_y)) + 2)
        if x1_b < x0_b or y1_b < y0_b:
            continue

        xs = np.arange(x0_b, x1_b + 1, dtype=np.float32)
        ys = np.arange(y0_b, y1_b + 1, dtype=np.float32)
        gx, gy = np.meshgrid(xs, ys)
        dx = gx - cx0
        v_h = (crown_bot_y - gy) / max(1.0, (crown_bot_y - crown_top_y))

        # Deterministic per-tree silhouette & slight hue variation
        s1 = ((tid * 73856093) ^ 0x5A5A) & 0xFF
        jitter_x = ((s1 / 255.0) - 0.5) * 0.32 * r_px
        ramp = SPECIES_RAMPS[sp_k]

        # True non-periodic 2D spatial hashes (uint32 avalanche mixing — ZERO diagonal stripes!)
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
            # ALPINE SPRUCE / FIR CONIFER: 4 stacked scalloped conical pine tiers with organic pine needles!
            in_v = (v_h >= -0.04) & (v_h <= 1.04)
            v_c = np.clip(v_h, 0.0, 1.0)
            tier_wave = 0.74 + 0.32 * (1.0 - ((v_c * 4.0) % 1.0))
            half_w_y = np.maximum(0.9, r_px * (1.0 - 0.88 * v_c) * tier_wave)
            edge_n = clump_2x2 * 1.15 + micro_1x1 * 0.65
            nx_n = dx / np.maximum(1.0, half_w_y + edge_n)
            inside = in_v & (np.abs(nx_n) <= 1.0)
            if not inside.any():
                continue
            nz_n = np.sqrt(np.maximum(0.05, 1.0 - np.minimum(0.98, nx_n * nx_n)))
            ny_n = 0.28 + 0.45 * v_c - 0.28 * (((v_c * 4.0) % 1.0))
            tier_sh = np.where(((v_c * 4.0) % 1.0) < 0.26, -0.26, 0.0)
            nd_s = nx_n * lx_s + ny_n * ly_s + nz_n * lz_s + tier_sh + clump_2x2 * 0.34 + micro_1x1 * 0.16 + bayer_t * 0.22
            d_surf = d0 - nz_n * (r_m * 0.78) - v_c * (h_m * 0.45 * sp_c)

        elif sp_k == 3:
            # SLENDER CYPRESS / LOMBARDY POPLAR: Crisp tall flame-shaped spire with leafy edge texture!
            in_v = (v_h >= -0.02) & (v_h <= 1.04)
            v_c = np.clip(v_h, 0.0, 1.0)
            flame = np.sin(np.power(v_c, 0.72) * math.pi)
            half_w_y = np.maximum(0.9, r_px * (0.28 + 0.85 * flame) + micro_1x1 * 0.6)
            nx_n = dx / half_w_y
            inside = in_v & (np.abs(nx_n) <= 1.0)
            if not inside.any():
                continue
            nz_n = np.sqrt(np.maximum(0.05, 1.0 - np.minimum(0.98, nx_n * nx_n)))
            ny_n = (v_c - 0.45) * 0.8
            nd_s = nx_n * lx_s + ny_n * ly_s + nz_n * lz_s + clump_2x2 * 0.32 + micro_1x1 * 0.14 + bayer_t * 0.20
            d_surf = d0 - nz_n * (r_m * 0.75) - v_c * (h_m * 0.45 * sp_c)

        else:
            # BROADLEAF DECIDUOUS (Oak, Beech, Linden, Maple, Copper Beech):
            # Wide, billowing 6-puff 90s pixel-art leaf canopy with organic leaf-cluster stipple & nibbled rim!
            dy_c = gy - crown_cy
            lobes = (
                (0.0, -0.22 * crown_ry, 0.68 * r_px, 0.66 * crown_ry),
                (-0.52 * r_px + jitter_x * 0.35, 0.14 * crown_ry, 0.60 * r_px, 0.56 * crown_ry),
                (0.52 * r_px + jitter_x * 0.35, 0.12 * crown_ry, 0.60 * r_px, 0.56 * crown_ry),
                (-0.32 * r_px, -0.44 * crown_ry, 0.52 * r_px, 0.48 * crown_ry),
                (0.30 * r_px, -0.38 * crown_ry, 0.50 * r_px, 0.46 * crown_ry),
                (0.06 * r_px, 0.32 * crown_ry, 0.62 * r_px, 0.48 * crown_ry),
            )
            best_z = np.full(gx.shape, -1.0, dtype=np.float32)
            best_nx = np.zeros(gx.shape, dtype=np.float32)
            best_ny = np.zeros(gx.shape, dtype=np.float32)
            for l_ox, l_oy, l_rx, l_ry in lobes:
                ux = (dx - l_ox) / max(1.5, l_rx)
                uy = (dy_c - l_oy) / max(1.5, l_ry)
                r2 = ux * ux + uy * uy
                in_l = r2 < 1.0
                if not in_l.any():
                    continue
                lz = np.sqrt(np.maximum(0.0, 1.0 - np.minimum(1.0, r2)))
                better = in_l & (lz > best_z)
                best_z[better] = lz[better]
                best_nx[better] = ux[better]
                best_ny[better] = -uy[better]

            # Organic nibbled outer foliage rim so silhouettes look leafy instead of smooth ovals
            rim_thresh = 0.08 + clump_2x2 * 0.16 + micro_1x1 * 0.10
            inside = best_z > np.maximum(0.0, rim_thresh)
            if not inside.any():
                continue
            nz_n = best_z
            nd_s = best_nx * lx_s + best_ny * ly_s + nz_n * lz_s
            # Organic 2x2 leaf clusters + 1x1 leaf highlights + 4x4 Bayer ordered dither (breaks concentric rings!)
            leaf_tex = clump_2x2 * 0.44 + micro_1x1 * 0.18 + bayer_t * 0.24
            nd_s = nd_s + leaf_tex - np.clip(0.32 - v_h, 0.0, 0.35) * 0.52
            d_surf = d0 - nz_n * (r_m * 0.82) - np.clip(v_h, 0.0, 1.0) * (h_m * 0.42 * sp_c)

        # Quantize lighting into all 4 crisp hand-drawn 90s pixel-art leaf tones!
        tone_idx = np.clip(np.floor((nd_s + 0.04) * 2.85).astype(np.int32), 0, 3)

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
        norm_buf[gy_w, gx_w, 0] = 0.20
        norm_buf[gy_w, gx_w, 1] = -0.15
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
                # Steep retaining wall (>44°) -> warm Swiss limestone masonry; moderate bank -> shaded terrain
                is_rwall = s_nz < 0.72
                s_col = np.where(is_rwall[:, None], [146.0, 142.0, 134.0], gcol[si] * 0.86).astype(np.float32)
                max_drop = np.clip(np.round((1.0 - s_nz) * 24.0).astype(np.int32), 2, 10)
                for oy in range(2, 11):
                    act = max_drop >= oy
                    if not act.any():
                        continue
                    ai = np.nonzero(act)[0]
                    for ox in (0, 1):
                        tx = np.clip(s_ix[ai] + ox, 0, W - 1)
                        ty = np.clip(s_iy[ai] + oy, 0, H - 1)
                        # Slight positive depth bias so skirt only fills true gaps behind foreground terrain
                        d_b = s_d[ai] + 0.16 + oy * 0.03
                        win = d_b <= zbuf[ty, tx]
                        if win.any():
                            wy, wx = ty[win], tx[win]
                            zbuf[wy, wx] = d_b[win]
                            rgb_buf[wy, wx] = s_col[ai[win]]
                            mat_buf[wy, wx] = M_GROUND
                            obj_buf[wy, wx] = 0
                            shadow_buf[wy, wx] = s_sh[ai[win]]
                            norm_buf[wy, wx, 0] = s_nx[ai[win]]
                            norm_buf[wy, wx, 1] = s_ny[ai[win]]
                            norm_buf[wy, wx, 2] = np.maximum(0.45, s_nz[ai[win]])

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
            # A. ROOF PIXELS: 100% Drawn 90s Pixel-Art Roofs (Clay Tiles, Flat Parapets & PV!)
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

                # 1. Pitched Roofs: Crisp staggered 90s pixel-art clay/slate tile courses!
                if pitched.any():
                    pi_r = np.nonzero(pitched)[0]
                    course_idx = np.floor(rz_r[pi_r] * 1.65).astype(np.int32)
                    in_course = (rz_r[pi_r] * 1.65) - course_idx
                    u_tile = (ru_r[pi_r] * 1.85 + (course_idx & 1) * 0.5) % 1.0
                    # Subtle per-tile tonal variation + crisp horizontal course shadow + vertical seam
                    t_var = (((course_idx * 17 + np.floor(ru_r[pi_r] * 1.85).astype(np.int32) * 31) & 7) - 3.5) * 2.2
                    r_alb[pi_r] = np.clip(r_alb[pi_r] + t_var[:, None], 28.0, 236.0)
                    r_alb[pi_r[in_course < 0.24]] *= 0.86
                    r_alb[pi_r[u_tile < 0.16]] *= 0.93
                    # Crisp eave shadow at bottom edge of pitched roof
                    eave_d = rz_r[pi_r] - scene.bldg_eave_z[r_bi[pi_r]]
                    r_alb[pi_r[(eave_d >= -0.2) & (eave_d < 0.35)]] *= 0.85

                # 2. Flat Roofs: Crisp perimeter parapet coping rim + inner shadow + clean gravel/green surface!
                flat = ~pitched
                if flat.any():
                    fi_r = np.nonzero(flat)[0]
                    est = sample_roof_edge_25cm(scene, re_r[fi_r], rn_r[fi_r])
                    rx25 = np.floor((re_r[fi_r] - E_MIN) * 4.0).astype(np.int32)
                    ry25 = np.floor((rn_r[fi_r] - N_MIN) * 4.0).astype(np.int32)
                    rhash = ((rx25 * 73856093) ^ (ry25 * 19349663)) & 0xFF
                    # Subtle 2-tone pixel gravel / sedum texture on flat interior
                    is_eco = r_kind[fi_r] == 3
                    r_alb[fi_r[(~is_eco) & (rhash < 72)]] *= 0.95
                    r_alb[fi_r[(~is_eco) & (rhash >= 188)]] *= 1.04
                    r_alb[fi_r[is_eco & (rhash < 85)]] *= 0.88
                    r_alb[fi_r[is_eco & (rhash >= 175)]] *= 1.10

                    # Outer 0.50m crisp concrete/metal parapet coping rim & inner drop shadow!
                    is_coping = est == 1
                    is_p_sh = est == 2
                    r_alb[fi_r[is_coping]] = np.clip(r_alb[fi_r[is_coping]] * 0.45 + np.array([124.0, 124.0, 122.0]), 120.0, 224.0)
                    r_alb[fi_r[is_p_sh]] *= 0.78

                # 3. Crisp Geometric Rooftop Solar PV Arrays (detected from 25cm SWISSIMAGE deep-blue PV panels!)
                raw_roof = sample_ortho_25cm(scene, re_r, rn_r).astype(np.float32)
                raw_lum = 0.299 * raw_roof[:, 0] + 0.587 * raw_roof[:, 1] + 0.114 * raw_roof[:, 2]
                is_pv = (
                    (raw_roof[:, 2] > (raw_roof[:, 0] + 14.0))
                    & (raw_roof[:, 2] > (raw_roof[:, 1] + 5.0))
                    & (raw_lum >= 32.0)
                    & (raw_lum <= 116.0)
                )
                if is_pv.any():
                    pvi = np.nonzero(is_pv)[0]
                    # Draw crisp dark-blue PV cells with 1px silver aluminum panel grid!
                    pv_grid = (((re_r[pvi] * 0.95) % 1.0) < 0.11) | (((rn_r[pvi] * 0.95) % 1.0) < 0.11)
                    r_alb[pvi] = [30.0, 52.0, 96.0]
                    r_alb[pvi[pv_grid]] = [162.0, 174.0, 190.0]

                f_col[rm] = r_alb

            # -----------------------------------------------------------------
            # B. WALL PIXELS: Realistic Per-Wall Swiss Facades, Doors, Shutters & Landmarks!
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

                # Crisp stone plinth at ground, cornice shadow under eaves, and subtle corner bevel!
                w_base[h_rel < 0.55] *= 0.84
                w_base[(top_dist > 0.0) & (top_dist < 0.42)] *= 0.80
                w_base[(edge_dist < 0.28) & (wall_len > 3.2)] *= 0.93

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
                    w_base[hi_l[in_white_curve]] = [236.0, 234.0, 228.0]

                    brick_m = ~in_white_curve
                    bcourse = brick_m & (((lz * 2.4) % 1.0) < 0.28)
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
                        & (lt_d >= 0.65)
                        & (lt_d <= 2.05)
                        & (((arc_u * 1.45) % 1.0) >= 0.28)
                        & (arc_u >= 3.5)
                    )
                    if gold_frieze.any():
                        gf_idx = hi_l[gold_frieze]
                        w_base[gf_idx] = [224.0, 184.0, 74.0]
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
                            w_base[hw_idx] = [52.0, 72.0, 96.0]
                            f_mat[wi[hw_idx]] = M_WINDOW_DAY

                # B1b. Main Seestrasse 204 Lindt & Sprüngli Complex (Building 1642, 1473, 1720)
                is_1642 = w_bi == 1642
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
                        pcol = np.full((len(pi), 3), [162.0, 68.0, 52.0], dtype=np.float32)
                        yellow_band = (((pz * 0.95) % 1.0) < 0.34) | ((pu % 3.6) < 0.72)
                        pcol[yellow_band] = [214.0, 190.0, 138.0]
                        pcol[ph < 4.5] = [146.0, 142.0, 134.0]
                        frieze_z = (ph >= 15.0) & (ph < 16.8)
                        checker = (((np.floor(pu * 1.4) + np.floor(pz * 1.4)).astype(np.int32)) & 1) == 0
                        pcol[frieze_z] = np.where(checker[frieze_z, None], [218.0, 192.0, 134.0], [156.0, 62.0, 48.0])
                        pcol[(ph >= 16.8) & (ph < 17.5)] = [92.0, 78.0, 70.0]
                        pcol[(ph >= 17.5) & ((pu % 3.2) < 0.55)] = [216.0, 212.0, 202.0]
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
    dither_map[clean_m] *= 0.30

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
    """Apply crisp 1px 90s selective pixel-art outlines (sel-out) on buildings, viaducts, trees & roof ridges."""
    dz_r = zbuf[:, 1:] - zbuf[:, :-1]
    dz_d = zbuf[1:, :] - zbuf[:-1, :]
    diff_r = obj_buf[:, 1:] != obj_buf[:, :-1]
    diff_d = obj_buf[1:, :] != obj_buf[:-1, :]

    is_bldg_or_br = (mat_buf == M_WALL) | (mat_buf == M_ROOF) | (mat_buf == M_BRIDGE) | (mat_buf == M_HARBOR_OBJ)
    is_tree_m = mat_buf == M_TREE

    # Crisp 0.65m silhouette threshold for buildings & viaducts, 0.85m for individual 3D trees!
    bldg_edge = np.zeros(zbuf.shape, dtype=np.bool_)
    bldg_edge[:, :-1] |= diff_r & (dz_r > 0.65) & is_bldg_or_br[:, :-1]
    bldg_edge[:, 1:] |= diff_r & (dz_r < -0.65) & is_bldg_or_br[:, 1:]
    bldg_edge[:-1, :] |= diff_d & (dz_d > 0.65) & is_bldg_or_br[:-1, :]
    bldg_edge[1:, :] |= diff_d & (dz_d < -0.65) & is_bldg_or_br[1:, :]

    # Crisp roof-to-wall eave seam on the same building!
    eave_d = (obj_buf[:-1, :] == obj_buf[1:, :]) & (mat_buf[:-1, :] == M_ROOF) & (mat_buf[1:, :] == M_WALL)
    bldg_edge[:-1, :] |= eave_d

    tree_edge = np.zeros(zbuf.shape, dtype=np.bool_)
    tree_edge[:, :-1] |= diff_r & (dz_r > 0.85) & is_tree_m[:, :-1]
    tree_edge[:, 1:] |= diff_r & (dz_r < -0.85) & is_tree_m[:, 1:]
    tree_edge[:-1, :] |= diff_d & (dz_d > 0.85) & is_tree_m[:-1, :]
    tree_edge[1:, :] |= diff_d & (dz_d < -0.85) & is_tree_m[1:, :]

    if bldg_edge.any():
        ey, ex = np.nonzero(bldg_edge)
        rgb_buf[ey, ex] *= 0.50 if not is_night else 0.58
    if tree_edge.any():
        ty, tx = np.nonzero(tree_edge)
        rgb_buf[ty, tx] *= 0.58 if not is_night else 0.66

    island_fg = mat_buf > M_DROP_SHADOW
    island_border = island_fg & (~ndimage.binary_erosion(island_fg, iterations=1, border_value=0))
    if island_border.any():
        by, bx = np.nonzero(island_border)
        rgb_buf[by, bx] *= 0.42

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
                dy0 = (y0 + DEPTH_DS - 1) // DEPTH_DS
                dy1 = min(dh_f, y1 // DEPTH_DS)
                dx0 = (x0 + DEPTH_DS - 1) // DEPTH_DS
                dx1 = min(dw_f, x1 // DEPTH_DS)
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
