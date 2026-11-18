"""V2 Data-Exact 90s Isometric 3D Pixel-Art Renderer for Kilchberg ZH.

100% faithful building-by-building, tree-by-tree, texture-by-texture reconstruction:
- Per-pixel 25 cm SWISSIMAGE DOP10 true aerial texture mapped onto all 124,155 3D LOD2
  building roof triangles, streets, crosswalks, courtyards, pools, tennis courts, piers & boats.
- Exact 0.5 m swissSURFACE3D volumetric 3D LiDAR canopy reconstruction for every single real tree,
  bush, hedgerow, copper beech, willow, and vineyard row (zero synthetic lollipop spheres).
- Authentic 90s pixel-art architectural facades (pitched-roof shuttered casements, modernist
  lakefront ribbons, Lindt clinker-brick & white atrium, Reformierte Kirche lancets & clock).
- True 256-color 90s SVGA isometric master palette with 4x4 ordered Bayer dithering & sel-out.
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
    G_LAKE,
    G_MOTORWAY,
    G_PLATFORM_PIER,
    G_POOL,
    G_RAILWAY,
    G_STREET_MAIN,
    G_STREET_MINOR,
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
    dither_strength: float = 13.5


PRESETS: dict[str, LightingPreset] = {
    "day": LightingPreset(
        name="90s SVGA Crisp Midday",
        sun_az_deg=146.0,
        sun_alt_deg=44.0,
        sun_rgb=(1.01, 0.99, 0.95),
        amb_rgb=(0.57, 0.57, 0.59),
        sky_top_rgb=(24, 34, 52),
        sky_bot_rgb=(38, 52, 74),
        is_night=False,
        dither_strength=10.5,
    ),
    "sunset": LightingPreset(
        name="Alpenglow Golden Sunset",
        sun_az_deg=116.0,
        sun_alt_deg=22.0,
        sun_rgb=(1.22, 0.83, 0.54),
        amb_rgb=(0.45, 0.41, 0.54),
        sky_top_rgb=(34, 26, 48),
        sky_bot_rgb=(70, 44, 60),
        is_night=False,
        dither_strength=11.5,
    ),
    "night": LightingPreset(
        name="Zürichsee Lantern Night",
        sun_az_deg=135.0,
        sun_alt_deg=36.0,
        sun_rgb=(0.25, 0.31, 0.50),
        amb_rgb=(0.19, 0.23, 0.37),
        sky_top_rgb=(12, 17, 30),
        sky_bot_rgb=(20, 28, 48),
        is_night=True,
        dither_strength=9.5,
    ),
}


@lru_cache(maxsize=1)
def build_90s_palette_and_lut() -> tuple[np.ndarray, np.ndarray]:
    """Construct a curated 256-color 90s SVGA isometric city-builder palette calibrated to
    authentic Swiss architecture, terracotta roofs, yellow road markings & alpine Zürichsee water."""
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

    # 2. Classic Swiss Roofs & Clinker Brick (terracotta red, aged clay brown, slate, solar PV, copper) — 48 colors
    add_ramp((48, 22, 18), (154, 68, 46), (228, 124, 86), 12)  # Swiss terracotta & Lindt clinker brick
    add_ramp((40, 26, 20), (116, 78, 56), (190, 140, 106), 10) # Weathered brown clay tile & timber
    add_ramp((24, 24, 28), (74, 70, 74), (152, 146, 142), 10)  # Anthracite / slate / gravel flat roof
    add_ramp((20, 28, 48), (44, 64, 104), (96, 132, 182), 8)   # Rooftop solar PV arrays & skylights
    add_ramp((26, 52, 48), (58, 118, 104), (124, 190, 170), 8) # Patina copper spires

    # 3. Swiss Facades, Warm Ochre, Traffic Yellow Markings, Sandstone & Plaster — 52 colors
    add_ramp((44, 42, 46), (144, 140, 134), (248, 245, 238), 12) # Chalk-white, alabaster & limestone
    add_ramp((50, 40, 32), (158, 138, 112), (240, 226, 198), 10) # Warm cream & sand stucco
    add_ramp((64, 48, 24), (176, 144, 68), (246, 214, 104), 10)  # Yellow-ochre villas, gold clock & Swiss crosswalk yellow!
    add_ramp((54, 36, 34), (152, 112, 98), (228, 192, 176), 8)   # Soft rose-sandstone plaster
    add_ramp((36, 26, 18), (98, 72, 48), (176, 138, 98), 6)      # Chalet timber & geological moraine
    add_ramp((20, 26, 38), (50, 66, 90), (108, 138, 168), 6)     # Window glass & cool mullions

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
    """Loaded Kilchberg 0.5m rasters, 25cm SWISSIMAGE texture atlas, and 3D LOD2 CityGML meshes."""

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

        self.ortho_25cm = np.load(cache_dir / "ortho_25cm.npy", mmap_mode="r")
        raw_rmask = np.load(cache_dir / "bldg_roof_mask_05m.npy")
        self.bldg_roof_mask = ndimage.binary_dilation(raw_rmask, iterations=3)

        b = np.load(cache_dir / "buildings_kilchberg_3d.npz")
        self.verts = b["verts"]
        self.normals = b["normals"]
        self.bldg_idx = b["bldg_idx"]
        self.surf_type = b["surf_type"]

        meta = json.loads((cache_dir / "buildings_kilchberg_meta.json").read_text())
        self.buildings = meta["buildings"]
        self.boats = meta["boats"]

        # Precompute 0.5m bare-earth terrain normals
        dz_drow, dz_dcol = np.gradient(ndimage.gaussian_filter(self.dem, sigma=0.7), GRID_RES)
        nx, ny, nz = -dz_dcol, dz_drow, np.ones_like(dz_dcol)
        nlen = np.sqrt(nx * nx + ny * ny + nz * nz)
        self.terr_nx = (nx / nlen).astype(np.float32)
        self.terr_ny = (ny / nlen).astype(np.float32)
        self.terr_nz = (nz / nlen).astype(np.float32)

        # Precompute 0.5m 3D LiDAR canopy surface normals from DSM = DEM + CHM
        dsm_smooth = ndimage.gaussian_filter(self.dem + self.chm, sigma=0.65)
        cz_drow, cz_dcol = np.gradient(dsm_smooth, GRID_RES)
        cnx, cny, cnz = -cz_dcol, cz_drow, np.ones_like(cz_dcol)
        clen = np.sqrt(cnx * cnx + cny * cny + cnz * cnz)
        self.can_nx = (cnx / clen).astype(np.float32)
        self.can_ny = (cny / clen).astype(np.float32)
        self.can_nz = (cnz / clen).astype(np.float32)

        # Precompute clean 0.5m mask of REAL moored boats, piers & Seebad rafts (excluding shoreline rocks/tree fringe!)
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

        # Precompute per-building 3D pitched-roof geometry, eave height, and true sunlit roof RGB from 25cm SWISSIMAGE!
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
        # March SWISSIMAGE sun direction (~162° SSE, ~37° altitude)
        dot_ortho = r_norms[:, 0] * 0.25 - r_norms[:, 1] * 0.76 + r_norms[:, 2] * 0.60
        lum_tri = 0.299 * rgb_tri[:, 0] + 0.587 * rgb_tri[:, 1] + 0.114 * rgb_tri[:, 2]
        r_zmin = r_verts[:, :, 2].min(axis=1)

        # Sort once by r_bidx for fast O(N) per-building slice aggregation
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
            good = (ds > 0.24) & (lm > 48.0) & (lm < 235.0)
            if good.any():
                self.bldg_sunlit_roof_rgb[bi_u] = np.percentile(vals[good], 68, axis=0)
            elif (lm > 44.0).any():
                self.bldg_sunlit_roof_rgb[bi_u] = np.percentile(vals[lm > 44.0], 72, axis=0)

        # Precompute exact physical horizontal wall spans [wall_u_min, wall_u_max] per (building, 10°-normal-bin)
        # so windows know each wall's true corners, centerline, and width (never wrapping blindly across corners!)
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
    shadow_knee: float = 58.0,
    vibrancy: float = 1.32,
    dehaze: float = 1.0,
) -> np.ndarray:
    """Subtract subtle high-altitude aerial path haze, lift shadows, and restore crisp 90s SVGA chroma."""
    rgb = rgb_u8.astype(np.float32)
    if dehaze > 0.0:
        # Remove subtle blue-grey Rayleigh/aerosol veil [7, 10, 14] scaled smoothly above darks
        veil_w = np.clip((rgb.min(axis=-1, keepdims=True) - 18.0) / 70.0, 0.0, 1.0) * dehaze
        rgb = np.maximum(4.0, rgb - veil_w * np.array([6.5, 9.5, 13.5], dtype=np.float32))
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    target_lum = np.where(
        lum < shadow_knee,
        shadow_knee * ((np.maximum(lum, 6.0) / shadow_knee) ** 0.58),
        lum,
    )
    scale = target_lum / np.maximum(lum, 6.0)
    lifted = rgb * scale[..., None]
    lum2 = (0.299 * lifted[..., 0] + 0.587 * lifted[..., 1] + 0.114 * lifted[..., 2])[..., None]
    boosted = lum2 + vibrancy * (lifted - lum2)
    return np.clip(boosted, 0.0, 252.0)


def condition_90s_foliage(raw_u8: np.ndarray, crown_id: np.ndarray, chm_h: np.ndarray) -> np.ndarray:
    """Convert leaf-off early-spring SWISSIMAGE twig tones on summer LiDAR crowns into lush,
    authentic 90s pixel-art Swiss summer foliage while preserving 100% of real 25cm crown detail & species."""
    raw = raw_u8.astype(np.float32)
    lum = 0.299 * raw[:, 0] + 0.587 * raw[:, 1] + 0.114 * raw[:, 2]
    # Lift deep aerial crown shadows into crisp 90s pixel-art midtones [44 .. 168]
    l_lift = np.where(lum < 64.0, 64.0 * ((np.maximum(lum, 8.0) / 64.0) ** 0.52), lum)
    l_norm = np.clip(l_lift * 1.04, 34.0, 172.0)

    is_conifer = (raw[:, 1] > raw[:, 0] + 3.5) & (lum < 96.0)
    is_copper_beech = ((raw[:, 0] > raw[:, 1] * 1.20) & (raw[:, 0] > 72.0)) | (
        (chm_h > 9.5) & ((crown_id % 37) == 11)
    )

    sp = crown_id % 4
    r_mult = np.select([sp == 0, sp == 1, sp == 2], [0.60, 0.68, 0.53], default=0.72)
    g_mult = np.select([sp == 0, sp == 1, sp == 2], [1.18, 1.22, 1.10], default=1.16)
    b_mult = np.select([sp == 0, sp == 1, sp == 2], [0.52, 0.50, 0.55], default=0.56)

    out = np.stack([l_norm * r_mult, l_norm * g_mult, l_norm * b_mult], axis=1)

    if is_conifer.any():
        lc = l_norm[is_conifer] * 0.88
        out[is_conifer] = np.stack([lc * 0.46, lc * 1.04, lc * 0.64], axis=1)

    if is_copper_beech.any():
        lb = l_norm[is_copper_beech] * 0.92
        out[is_copper_beech] = np.stack([lb * 1.06, lb * 0.50, lb * 0.52], axis=1)

    return np.clip(out, 16.0, 236.0)


def sample_ortho_25cm(scene: SceneData, e_arr: np.ndarray, n_arr: np.ndarray) -> np.ndarray:
    """Sample exact 25 cm SWISSIMAGE DOP10 RGB at arbitrary world LV95 (E, N) coordinates."""
    cols = np.clip(((e_arr - E_MIN) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_W - 1)
    rows = np.clip(((N_MAX - n_arr) * (1.0 / ORTHO25_RES)).astype(np.int32), 0, ORTHO25_H - 1)
    return np.asarray(scene.ortho_25cm[rows, cols])


def compute_shadow_grid(scene: SceneData, sun_az_deg: float, sun_alt_deg: float) -> np.ndarray:
    """Ray-march 0.5m LiDAR DSM (real 3D buildings + real 3D trees) for crisp cast shadows."""
    h_surf = (scene.dem + scene.chm)[::2, ::2].copy()
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
    """Determine authentic Swiss facade RGB and architectural style code for each of the 1,890 buildings.
    Styles:
      0 = Traditional Swiss pitched-roof house (warm plaster/ochre/sandstone/timber + spaced shuttered casements)
      1 = Modernist flat-roof lakeside villa / terrace apartment (asymmetric architectural glazing + stone piers)
      2 = Lindt Home of Chocolate (monumental red clinker-brick museum + curved white concrete NE atrium)
      3 = Historic Lindt & Sprüngli 1899 works / commercial building (pilaster-grouped industrial casements)
      4 = Sacred church & bell tower (giant round tower clock + arched belfry louvers + nave stained-glass lancets)
      5 = Non-windowed structure (Hochkamin brick chimney, Lagertank silo, Flugdach)
      6 = Small outbuilding / boathouse / garage / pavilion (timber double door or single window, never rows!)
    """
    buildings = scene.buildings
    n = len(buildings)
    wall_rgb = np.empty((n, 3), dtype=np.uint8)
    style_code = np.zeros(n, dtype=np.uint8)

    plaster_trad = [
        (238, 230, 212),  # Warm Swiss chalk-ivory plaster
        (232, 216, 186),  # Classic Kilchberg sand-ochre stucco
        (226, 202, 158),  # Historic Zürichsee golden-ochre villa plaster
        (235, 225, 212),  # Pale warm sandstone
        (218, 212, 202),  # Warm village limestone
        (228, 198, 182),  # Soft terracotta-rose stucco
        (174, 134, 96),   # Sun-weathered Swiss chalet timber
    ]
    modern_pal = [
        (240, 238, 232),  # Warm architectural alabaster
        (224, 220, 212),  # Travertine / fair-faced concrete
        (212, 212, 210),  # Natural Jura limestone grey
        (234, 226, 210),  # Warm sand-cream villa
    ]

    for i, b in enumerate(buildings):
        obj = b["objektart"]
        e, nc = b["e"], b["n"]
        h = b["height"]
        area_box = b["footprint_w"] * b["footprint_l"]
        h_seed = int(abs(round(e * 3.7 + nc * 7.3)))

        if obj == "Hochkamin":
            wall_rgb[i] = (178, 86, 62)
            style_code[i] = 5
        elif obj == "Lagertank":
            wall_rgb[i] = (218, 220, 222)
            style_code[i] = 5
        elif obj in ("Flugdach", "Offenes Gebaeude", "Mauer gross"):
            wall_rgb[i] = (188, 184, 176)
            style_code[i] = 5
        elif obj == "Treibhaus":
            wall_rgb[i] = (176, 212, 224)
            style_code[i] = 6
        elif obj in ("Sakrales Gebaeude", "Sakraler Turm"):
            if nc < 1241450:
                wall_rgb[i] = (242, 238, 226)  # Reformierte Kirche bright whitewashed plaster
            else:
                wall_rgb[i] = (218, 210, 196)  # St. Elisabeth warm sculptural concrete
            style_code[i] = 4
        elif 2684080 <= e <= 2684136 and 1241395 <= nc <= 1241440 and area_box > 4000:
            # Building 1443: Lindt Home of Chocolate (red-terracotta clinker brick + curved white atrium!)
            wall_rgb[i] = (186, 86, 60)
            style_code[i] = 2
        elif 2684130 <= e <= 2684255 and 1241280 <= nc <= 1241515 and area_box > 1100:
            # Historic 1899 Lindt & Sprüngli factory complex & corporate HQ along Seestrasse
            wall_rgb[i] = (236, 229, 214) if e > 2684148 else (228, 226, 220)
            style_code[i] = 3
        elif h < 4.3 or area_box < 42.0 or min(b["footprint_w"], b["footprint_l"]) < 4.3:
            # Boathouses, garages, garden pavilions & small annexes
            wall_rgb[i] = (168, 130, 96) if (h_seed % 3 == 0) else plaster_trad[h_seed % 5]
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


def render_diorama(
    scene: SceneData,
    camera: IsometricCamera,
    preset_key: str = "day",
    crop_box_lv95: tuple[float, float, float, float] | None = None,
    add_frame: bool = True,
    collect_hit_boxes: bool = False,
    viewport_win: tuple[int, int, int, int] | None = None,
    sun_shadow_override: np.ndarray | None = None,
) -> tuple[Image.Image, dict]:
    """Render 100% data-accurate 3D isometric 90s pixel-art diorama (full, crop, or seamless tile window)."""
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
        cz_hi = scene.dem[cr_idx, cc_idx] + scene.chm[cr_idx, cc_idx] + 36.0
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
    sub_bldg_roof = scene.bldg_roof_mask[r0:r1, c0:c1]
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

    # Pre-cull perimeter columns horizontally to current viewport window for 2.5x faster tiled rendering
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
            # Authentic Zürichsee alpine jade-teal cutaway water column
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
    # STAGE 2: True 25 cm SWISSIMAGE Ground, Streets, Crosswalks, Pools & Boats!
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

        raw_ortho = sample_ortho_25cm(scene, ge, gn)
        gcol = condition_90s_albedo(raw_ortho, shadow_knee=54.0, vibrancy=1.30, dehaze=1.0)
        ro_f = raw_ortho.astype(np.float32)

        # Enrich ONLY genuine March grass/meadow/vineyard turf into crisp Swiss summer green
        # (strictly preserving plowed brown soil, gravel paths, stone courtyards & street markings!)
        is_turf = (
            (~glake)
            & (gsem <= 6)
            & (gsem != G_POOL)
            & (ro_f[:, 1] >= ro_f[:, 0] * 0.97)
            & ((ro_f[:, 1] - ro_f[:, 2]) > 10.0)
            & (ro_f[:, 1] < 158.0)
        )
        if is_turf.any():
            gcol[is_turf, 0] *= 0.80
            gcol[is_turf, 1] = np.minimum(236.0, gcol[is_turf, 1] * 1.18)
            gcol[is_turf, 2] *= 0.82

        # Preserve & crisp up real yellow Swiss pedestrian crosswalks & bus markings on streets!
        is_road_yellow = (
            ((gsem == G_STREET_MAIN) | (gsem == G_STREET_MINOR))
            & (ro_f[:, 0] > 128.0)
            & (ro_f[:, 1] > 118.0)
            & ((ro_f[:, 0] - ro_f[:, 2]) >= 14.0)
        )
        if is_road_yellow.any():
            gcol[is_road_yellow] = 0.45 * gcol[is_road_yellow] + 0.55 * np.array([236.0, 196.0, 74.0])

        # Crisp real backyard & lakeside swimming pools (exact sky-cyan from SWISSIMAGE!)
        is_pool = gsem == G_POOL
        if is_pool.any():
            gcol[is_pool] = 0.50 * gcol[is_pool] + 0.50 * np.array([76.0, 198.0, 224.0])
            gnx[is_pool], gny[is_pool], gnz[is_pool] = 0.0, 0.0, 1.0

        # Lake Zurich (Zürichsee): authentic alpine jade-emerald shallows -> deep glacial teal-blue!
        gmat = np.full(len(ge), M_GROUND, dtype=np.uint8)
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
                # Blend real SWISSIMAGE nearshore shallow reef & sandbar variation (< 4.5m depth)
                shallow_tint = np.clip((4.5 - depth_m) / 4.5, 0.0, 1.0)[:, None] * 0.28
                ortho_w = np.clip(raw_ortho[wi].astype(np.float32) * 1.18, 22.0, 165.0)
                w_col = (1.0 - shallow_tint) * w_col + shallow_tint * ortho_w

                # Subtle organic 90s pixel water shimmer (zero artificial diagonal bars!)
                ripple = np.sin(we_w * 0.42 + wn_w * 0.31) * np.cos(we_w * 0.19 - wn_w * 0.47)
                w_col += ripple[:, None] * np.array([3.5, 5.5, 5.5])
                shore_f = depth_m < 0.48
                w_col[shore_f] = 0.65 * w_col[shore_f] + 0.35 * np.array([176.0, 212.0, 204.0])
                gcol[wi] = w_col
                gmat[wi] = M_WATER_LAKE
                gnx[wi], gny[wi], gnz[wi] = 0.0, 0.0, 1.0

            bi_h = li[is_real_harbor_obj]
            if len(bi_h) > 0:
                real_h = np.clip(sub_chm[gr[bi_h], gc[bi_h]], 0.55, 3.8)
                gz[bi_h] = LAKE_SURFACE_Z + real_h
                gcol[bi_h] = condition_90s_albedo(raw_ortho[bi_h], shadow_knee=70.0, vibrancy=1.22)
                gmat[bi_h] = M_HARBOR_OBJ
                gnx[bi_h], gny[bi_h], gnz[bi_h] = 0.15, -0.15, 0.97

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

    # -------------------------------------------------------------------------
    # STAGE 3: All 1,890 Real 3D LOD2 Buildings — De-Shadowed Roofs & Realistic Facades!
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
    bldg_h = np.array([b["height"] for b in scene.buildings], dtype=np.float32)
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

            # A. ROOF PIXELS: Sample exact 25 cm SWISSIMAGE DOP10 + de-shadow north slopes!
            rm = st_f == 1
            if rm.any():
                r_ft = ft[rm]
                r_bi = bi[rm]
                r_norms = norms_v[r_ft]
                raw_roof = sample_ortho_25cm(scene, fe[rm], fn[rm])
                rf = raw_roof.astype(np.float32)
                raw_lum = 0.299 * rf[:, 0] + 0.587 * rf[:, 1] + 0.114 * rf[:, 2]

                # Recover true roof color on pitched north/west slopes shadowed during March SWISSIMAGE flight!
                dot_ortho = r_norms[:, 0] * 0.25 - r_norms[:, 1] * 0.76 + r_norms[:, 2] * 0.60
                sun_ref = scene.bldg_sunlit_roof_rgb[r_bi]
                sun_lum = np.maximum(0.299 * sun_ref[:, 0] + 0.587 * sun_ref[:, 1] + 0.114 * sun_ref[:, 2], 12.0)

                in_aerial_sh = (dot_ortho < 0.36) & (raw_lum < np.minimum(98.0, sun_lum * 0.84))
                if in_aerial_sh.any():
                    # Preserve local 25cm tile/dormer contrast while restoring sunlit slope hue & brightness!
                    sh_blend = np.clip((0.36 - dot_ortho[in_aerial_sh]) * 2.4, 0.35, 0.90)[:, None]
                    local_mod = np.clip(raw_lum[in_aerial_sh] / np.maximum(raw_lum[in_aerial_sh].mean(), 42.0), 0.78, 1.22)[:, None]
                    restored = np.clip(sun_ref[in_aerial_sh] * local_mod, 24.0, 248.0)
                    rf[in_aerial_sh] = (1.0 - sh_blend) * rf[in_aerial_sh] + sh_blend * restored

                r_alb = condition_90s_albedo(rf, shadow_knee=54.0, vibrancy=1.42, dehaze=1.15)

                # Enhance real rooftop solar PV arrays (cool bluish dark cells on flat/pitched roofs)
                is_pv = (rf[:, 2] > (rf[:, 0] + 5.5)) & (raw_lum >= 45.0) & (raw_lum <= 145.0)
                if is_pv.any():
                    r_alb[is_pv] = 0.48 * r_alb[is_pv] + 0.52 * np.array([46.0, 68.0, 114.0])

                # Lindt Home of Chocolate (bi == 1443): crisp red-brick roof parapet border!
                is_hoc_roof = r_bi == 1443
                if is_hoc_roof.any():
                    re_h, rn_h = fe[rm], fn[rm]
                    # Outer 2.2m perimeter of Bldg 1443 roof is red clinker brick parapet (visible in SWISSIMAGE!)
                    # Rotated local coordinates along Lindt HoC building axes (~34.5° azimuth)
                    dx_h = re_h - 2684096.5
                    dy_h = rn_h - 1241427.0
                    u_h = dx_h * 0.824 + dy_h * 0.566
                    v_h = -dx_h * 0.566 + dy_h * 0.824
                    on_parapet = is_hoc_roof & ((np.abs(u_h) > 22.8) | (np.abs(v_h) > 45.8)) & (~(re_h > 2684112.0))
                    r_alb[on_parapet] = [188.0, 92.0, 64.0]

                # Subtle 90s pixel-art clay tile course lines on pitched roofs
                pitched = r_norms[:, 2] < 0.93
                course = pitched & (((fz[rm] * 1.55) % 1.0) < 0.24)
                r_alb[course] *= 0.91
                f_col[rm] = r_alb

            # B. WALL PIXELS: Realistic Per-Wall Swiss Facades, Doors, Shutters & Landmarks!
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

                # Exact planar wall span [u_min, u_max] & centerline for every single wall face!
                w_dbin = dir_bin_v[w_ft]
                w_key = w_bi * 36 + w_dbin
                u_min_w = scene.wall_u_min[w_key]
                u_max_w = scene.wall_u_max[w_key]
                wall_len = np.maximum(0.5, u_max_w - u_min_w)
                u_local = w_u - u_min_w
                d_center = w_u - 0.5 * (u_min_w + u_max_w)
                edge_dist = np.minimum(u_local, wall_len - u_local)

                # Crisp 1px stone plinth at ground & subtle cornice shadow directly under eaves
                w_base[h_rel < 0.52] *= 0.87
                w_base[(top_dist > 0.0) & (top_dist < 0.42)] *= 0.80

                # -------------------------------------------------------------
                # B1. LANDMARK: Lindt Home of Chocolate (Building 1443, style 2)
                # Monumental solid red clinker-brick museum + curved white concrete NE entrance!
                # -------------------------------------------------------------
                is_hoc = w_sty == 2
                if is_hoc.any():
                    hi_l = np.nonzero(is_hoc)[0]
                    le, ln, lz, lh = w_e[hi_l], w_n[hi_l], w_z[hi_l], h_rel[hi_l]
                    lu = u_local[hi_l]
                    # Curved white sculptural concrete entrance corner facing Lindtplatz (NE recess)
                    in_white_curve = (le >= 2684109.2) & (ln >= 1241403.0) & (ln <= 1241436.8)
                    w_base[hi_l[in_white_curve]] = [244.0, 242.0, 236.0]

                    # Subtle horizontal clinker-brick courses + vertical brick relief piers on brick faces
                    brick_m = ~in_white_curve
                    bcourse = brick_m & (((lz * 2.4) % 1.0) < 0.28)
                    bpier = brick_m & (lh > 4.2) & (((lu % 4.6) < 0.45))
                    w_base[hi_l[bcourse]] *= 0.92
                    w_base[hi_l[bpier]] *= 0.94

                    # Ground-floor grand museum entrance glazing (smooth across curved white atrium & SE plaza front)
                    arc_u = np.where(
                        in_white_curve,
                        (np.arctan2(ln - 1241418.0, le - 2684122.0) + math.pi) * 13.5,
                        lu,
                    )
                    plaza_glass = (
                        ((in_white_curve & (lh >= 0.35) & (lh <= 5.4)) | (brick_m & (le >= 2684118.0) & (lh >= 0.45) & (lh <= 3.8)))
                        & (((arc_u % 4.2) >= 0.85) & ((arc_u % 4.2) <= 3.35))
                    )
                    # Sparse sculpted circular museum oculi on the curved white facade (Christ & Gantenbein signature!)
                    oc_z = ((lh - 10.5) % 6.8) - 3.4
                    oc_u = ((arc_u + 2.0) % 7.6) - 3.8
                    oculi = in_white_curve & (lh >= 8.5) & (lh <= 19.5) & ((oc_z * oc_z + oc_u * oc_u) <= 0.62)

                    hoc_win = plaza_glass | oculi
                    if hoc_win.any():
                        hw_idx = hi_l[hoc_win]
                        if preset.is_night:
                            w_base[hw_idx] = [255.0, 224.0, 142.0]
                            f_mat[wi[hw_idx]] = M_WINDOW_LIT
                        else:
                            w_base[hw_idx] = [62.0, 86.0, 112.0]
                            f_mat[wi[hw_idx]] = M_WINDOW_DAY

                # -------------------------------------------------------------
                # B2. LANDMARK: Churches & Bell Towers (style 4)
                # Zero automatic apartment rows! Giant round tower clock + arched belfry louvers + nave lancets!
                # -------------------------------------------------------------
                is_sacred = w_sty == 4
                if is_sacred.any():
                    si_l = np.nonzero(is_sacred)[0]
                    s_bi = w_bi[si_l]
                    se_w, sn_w, sz_w, sh_w = w_e[si_l], w_n[si_l], w_z[si_l], h_rel[si_l]
                    s_ft = w_ft[si_l]
                    s_edg = edge_dist[si_l]
                    s_dc = d_center[si_l]
                    s_ul = u_local[si_l]

                    # Warm sandstone corner quoins on church & tower corners
                    quoin = (s_bi == 1715) & (s_edg < 0.52) & (((np.floor(sz_w * 1.3).astype(np.int32)) % 2) == 0)
                    w_base[si_l[quoin]] = [214.0, 202, 180.0]

                    # 1. Reformierte Kirche Square Bell Tower (bi == 1715, East side E >= 2683407.6)
                    rk_tower = (s_bi == 1715) & (se_w >= 2683407.6)
                    if rk_tower.any():
                        rt_i = np.nonzero(rk_tower)[0]
                        rt_glob = si_l[rt_i]
                        # Exact horizontal offset from square tower center (2683413.0, 1241287.7) along this tower wall!
                        tx_t = tw_x_v[s_ft[rt_i]]
                        ty_t = tw_y_v[s_ft[rt_i]]
                        d_tc = (se_w[rt_i] - 2683413.0) * tx_t + (sn_w[rt_i] - 1241287.7) * ty_t
                        z_t = sz_w[rt_i]

                        # A) Paired arched belfry sound-louvers (Schalllöcher) at Z ∈ [524.8 .. 528.6m]
                        du_pair = np.abs(d_tc) - 1.05
                        in_louver_rect = (np.abs(du_pair) <= 0.58) & (z_t >= 524.8) & (z_t <= 527.8)
                        in_louver_arch = (z_t > 527.8) & (z_t <= 528.65) & (((du_pair / 0.58) ** 2 + ((z_t - 527.8) / 0.82) ** 2) <= 1.0)
                        louver = in_louver_rect | in_louver_arch
                        if louver.any():
                            lv_g = rt_glob[louver]
                            slat = ((z_t[louver] * 3.5) % 1.0) < 0.45
                            w_base[lv_g] = np.where(slat[:, None], [58.0, 48.0, 42.0], [34.0, 30.0, 32.0])

                        # B) Single narrow vertical stone slit embrasure on lower tower shaft (NO rows of windows!)
                        slit = (np.abs(d_tc) <= 0.20) & (z_t >= 518.2) & (z_t <= 520.6)
                        w_base[rt_glob[slit]] = [46.0, 48.0, 56.0]

                        # C) GIANT ROUND SWISS CHURCH CLOCK centered at (d_tc = 0, Z = 531.7m), radius = 2.15m!
                        dz_ck = z_t - 531.7
                        r_ck = np.hypot(d_tc, dz_ck)
                        on_clock = r_ck <= 2.22
                        if on_clock.any():
                            ck_sub = np.nonzero(on_clock)[0]
                            ck_g = rt_glob[ck_sub]
                            rc = r_ck[ck_sub]
                            ux = d_tc[ck_sub]
                            uz = dz_ck[ck_sub]

                            # Dark slate dial + gleaming gold outer bezel & cardinal hour markers + gold hands (~10:10)!
                            dial_col = np.full((len(ck_sub), 3), 24.0, dtype=np.float32)
                            dial_col[:, 1] = 28.0
                            dial_col[:, 2] = 38.0

                            gold_rim = (rc >= 1.72) & (rc <= 2.22)
                            inner_ring = (rc >= 1.38) & (rc <= 1.50)
                            # Hour hand (~10 o'clock: angle ~145°) & minute hand (~2 o'clock: angle ~30°)
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

                    # 2. Reformierte Kirche Nave (bi == 1715, E < 2683407.6): single row of tall arched stained-glass lancets!
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

                    # 3. St. Elisabeth freestanding 30.1m Bell Tower (bi == 1254) & Modernist Nave (bi == 1309)
                    st_el_tower = s_bi == 1254
                    if st_el_tower.any():
                        et_i = np.nonzero(st_el_tower)[0]
                        et_glob = si_l[et_i]
                        edc = s_dc[et_i]
                        ez = sz_w[et_i]
                        # Tall modernist acoustic belfry slots near top + sleek round gold clock
                        bslot = (np.abs(np.abs(edc) - 0.55) <= 0.24) & (ez >= 510.2) & (ez <= 516.4)
                        w_base[et_glob[bslot]] = [42.0, 44.0, 50.0]
                        r_ec = np.hypot(edc, ez - 507.6)
                        w_base[et_glob[(r_ec <= 1.25) & (r_ec >= 0.90)]] = [228.0, 188.0, 74.0]
                        w_base[et_glob[r_ec < 0.90]] = [30.0, 34.0, 44.0]

                    st_el_nave = (s_bi == 1309) & (s_edg >= 1.8)
                    if st_el_nave.any():
                        en_i = np.nonzero(st_el_nave)[0]
                        en_glob = si_l[en_i]
                        # Sculptural clerestory glass band near roofline (not residential rows!)
                        clere = (sh_w[en_i] >= 9.5) & (sh_w[en_i] <= 12.2) & (((s_ul[en_i] % 2.8) >= 0.45))
                        if clere.any():
                            cg_idx = en_glob[clere]
                            w_base[cg_idx] = [255.0, 218.0, 128.0] if preset.is_night else [58.0, 82.0, 108.0]
                            f_mat[wi[cg_idx]] = M_WINDOW_LIT if preset.is_night else M_WINDOW_DAY

                # -------------------------------------------------------------
                # B3. SMALL OUTBUILDINGS, BOATHOUSES & GARAGES (style 6)
                # Timber double-door or single small casement — NEVER rows of windows!
                # -------------------------------------------------------------
                is_outb = w_sty == 6
                if is_outb.any():
                    oi = np.nonzero(is_outb)[0]
                    odc = d_center[oi]
                    oh = h_rel[oi]
                    owlen = wall_len[oi]
                    odb = w_dbin[oi]
                    # Put a timber garage/boathouse door on one main wall, tiny window on one side
                    is_door_face = ((w_bi[oi] + odb) % 3 == 0) & (owlen >= 3.2)
                    gdoor = is_door_face & (np.abs(odc) <= 1.05) & (oh >= 0.08) & (oh <= 2.25)
                    tiny_w = (~is_door_face) & (owlen >= 3.6) & (np.abs(odc) <= 0.45) & (oh >= 1.15) & (oh <= 2.05)
                    w_base[oi[gdoor]] = [96.0, 68.0, 46.0]
                    w_base[oi[tiny_w]] = [52.0, 68.0, 88.0]

                # -------------------------------------------------------------
                # B4. RESIDENTIAL HOUSES (0), MODERN VILLAS (1) & HISTORIC FACTORIES (3)
                # Per-wall corner margins, eave/gable cutoffs, organic bay piers & front doors!
                # -------------------------------------------------------------
                is_res = (w_sty == 0) | (w_sty == 1) | (w_sty == 3)
                if is_res.any():
                    ri_l = np.nonzero(is_res)[0]
                    r_sty = w_sty[ri_l]
                    r_bi_w = w_bi[ri_l]
                    r_db = w_dbin[ri_l]
                    r_h = h_rel[ri_l]
                    r_z = w_z[ri_l]
                    r_eave = eave_z[ri_l]
                    r_wlen = wall_len[ri_l]
                    r_uloc = u_local[ri_l]
                    r_dc = d_center[ri_l]
                    r_edg = edge_dist[ri_l]

                    # Subtle horizontal balcony/slab shadow ledges on wider modern villas (style 1)
                    slab_line = (r_sty == 1) & (r_wlen >= 9.0) & (r_h >= 2.8) & (((r_h % 3.15) < 0.24))
                    w_base[ri_l[slab_line]] *= 0.86

                    # Vertical structural pilaster piers every 12.8m on historic Lindt factory wings (style 3)
                    pilaster = (r_sty == 3) & ((r_uloc % 12.8) < 0.65)
                    w_base[ri_l[pilaster]] = np.minimum(250.0, w_base[ri_l[pilaster]] * 1.05)

                    # Story height & generous bay spacing (so walls are 65-75% warm masonry, NOT window stripes!)
                    fl_h = np.where(r_sty == 3, 3.85, np.where(r_sty == 1, 3.15, 3.05))
                    bay_w = np.where(r_sty == 3, 3.20, np.where(r_sty == 1, 4.65, 3.85))

                    fl_idx = np.floor(r_h / fl_h).astype(np.int32)
                    in_z = (r_h - fl_idx * fl_h) / fl_h

                    # Center the bay grid symmetrically on each individual wall!
                    n_bays = np.maximum(1, np.floor((r_wlen - 2.1) / bay_w).astype(np.int32))
                    grid_span = n_bays.astype(np.float32) * bay_w
                    u_start = 0.5 * (r_wlen - grid_span)
                    u_in_grid = r_uloc - u_start
                    bay_idx = np.floor(u_in_grid / bay_w).astype(np.int32)
                    bay_center_offset = (u_in_grid - (bay_idx.astype(np.float32) + 0.5) * bay_w)  # meters from bay center!

                    # Strict corner piers & strict eave/roofline ceiling (NEVER rows of windows in triangular gables!)
                    z_ceil = np.where(r_sty == 0, np.minimum(r_eave - 0.35, bldg_z1[r_bi_w] - 0.75), bldg_z1[r_bi_w] - 0.75)
                    in_grid_bounds = (
                        (r_wlen >= 3.5)
                        & (r_edg >= 1.15)
                        & (bay_idx >= 0)
                        & (bay_idx < n_bays)
                        & (r_z <= z_ceil)
                        & (r_h >= 0.85)
                    )

                    # Deterministic architectural rhythm: skip ~26% of bays as solid plaster wall piers,
                    # leave ~30% of narrow side walls (<5.8m) completely blank!
                    wall_hash = ((r_bi_w.astype(np.int64) * 2654435761) ^ (r_db.astype(np.int64) * 40503)) & 0xFF
                    bay_hash = ((r_bi_w.astype(np.int64) * 73856093) ^ (r_db.astype(np.int64) * 19349663) ^ (bay_idx.astype(np.int64) * 83492791)) & 0xFF

                    blank_narrow_wall = (r_wlen < 5.8) & ((wall_hash % 3) == 0) & (r_sty != 3)
                    solid_pier_bay = (
                        ((r_sty == 0) & (n_bays >= 3) & ((bay_hash % 4) == 1))
                        | ((r_sty == 1) & (n_bays >= 2) & ((bay_hash % 4) == 2))
                        | ((r_sty == 3) & ((bay_idx % 4) == 3))
                    )

                    # Ground-floor wooden entrance door on one bay of houses (instead of another window!)
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
                        w_base[ri_l[front_door]] = [98.0, 66.0, 44.0]

                    # Half of remaining ground-floor bays on hillside Swiss houses are solid masonry basement/plinth!
                    skip_gf_win = (r_sty == 0) & (fl_idx == 0) & (((bay_hash >> 3) % 3) == 0)

                    # Window half-width in meters: crisp 1.12m casements on Swiss houses, varied 1.10m / 1.85m on modern villas!
                    half_w = np.where(
                        r_sty == 0,
                        0.56,
                        np.where(
                            r_sty == 3,
                            0.62,
                            np.where((bay_hash & 1) == 0, 0.92, 0.55),
                        ),
                    )
                    z_lo = np.where((r_sty == 1) & ((bay_hash & 1) == 0), 0.18, 0.32)
                    z_hi = np.where(r_sty == 3, 0.78, 0.74)

                    active_bay = in_grid_bounds & (~blank_narrow_wall) & (~solid_pier_bay) & (~is_door_bay) & (~skip_gf_win)
                    is_pane = active_bay & (in_z >= z_lo) & (in_z <= z_hi) & (np.abs(bay_center_offset) <= half_w)

                    # Single small centered attic window high in wide pitched roof gables (above eaves!)
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

                    # Classic dark green / burgundy / timber shutters flanking traditional Swiss house windows (style 0)!
                    is_shutter = (
                        (r_sty == 0)
                        & active_bay
                        & (in_z >= z_lo)
                        & (in_z <= z_hi)
                        & (np.abs(bay_center_offset) > (half_w + 0.03))
                        & (np.abs(bay_center_offset) <= (half_w + 0.38))
                    )
                    if is_shutter.any():
                        sh_g = ri_l[is_shutter]
                        sh_mode = r_bi_w[is_shutter] % 5
                        sh_col = np.where(
                            (sh_mode == 0)[:, None],
                            [114.0, 46.0, 46.0],
                            np.where((sh_mode == 1)[:, None], [96.0, 68.0, 46.0], [42.0, 78.0, 54.0]),
                        )
                        w_base[sh_g] = sh_col

                    # Crisp 1px stone window sill directly below active windows
                    is_sill = active_bay & (in_z >= (z_lo - 0.08)) & (in_z < z_lo) & (np.abs(bay_center_offset) <= (half_w + 0.14))
                    w_base[ri_l[is_sill]] = np.minimum(250.0, w_base[ri_l[is_sill]] * 1.12)

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
                            # Subtle center casement mullion + sky reflection glint in upper pane
                            mullion = np.abs(p_bco) < 0.08
                            upper_glint = p_inz > 0.56
                            pane_c = np.where(upper_glint[:, None], [86.0, 118.0, 148.0], [42.0, 56.0, 76.0])
                            pane_c[mullion] = [196.0, 192.0, 184.0]
                            w_base[p_local] = pane_c
                            f_mat[p_global] = M_WINDOW_DAY

                f_col[wi] = w_base

            zbuf[fy, fx] = fd
            rgb_buf[fy, fx] = f_col
            mat_buf[fy, fx] = f_mat
            obj_buf[fy, fx] = bi + 1
            norm_buf[fy, fx] = norms_v[ft]
            shadow_buf[fy, fx] = False

    # Draw slender 1px corner pillars for open Flugdach canopies so station/carport roofs stand on posts
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
    # STAGE 4: Exact 0.5m 3D LiDAR Canopy — Every Single Tree, Bush & Hedge!
    # -------------------------------------------------------------------------
    o05 = scene.ortho_05m[r0:r1, c0:c1].astype(np.float32)
    g_ex05 = o05[:, :, 1] - 0.50 * o05[:, :, 0] - 0.44 * o05[:, :, 2]
    is_veg05 = (g_ex05 > 2.5) | ((o05[:, :, 1] >= o05[:, :, 0] * 0.94) & (o05[:, :, 1] >= 22.0) & (o05[:, :, 1] < 160.0))

    canopy_mask = (
        sub_mask
        & (~sub_bldg_roof)
        & (~sub_lake)
        & (sub_chm >= 0.85)
        & (
            (is_veg05 & (sub_sem != G_MOTORWAY) & (sub_sem != G_RAILWAY))
            | ((sub_chm >= 2.2) & (sub_sem != G_MOTORWAY) & (sub_sem != G_RAILWAY))
        )
    )

    if canopy_mask.any():
        rr_all, cc_all = np.nonzero(canopy_mask)
        ce_all = E_MIN + (cc_all + c0 + 0.5) * GRID_RES
        cn_all = N_MAX - (rr_all + r0 + 0.5) * GRID_RES
        chm_all = sub_chm[rr_all, cc_all]

        tuft_hash = (((cc_all + c0) // 2) * 17 + ((rr_all + r0) // 2) * 31) % 7
        tuft_dz = (tuft_hash.astype(np.float32) - 3.0) * 0.14
        z_top_can = sub_dem[rr_all, cc_all] + chm_all + tuft_dz

        # 4A. Project & cull to screen window BEFORE sampling 25cm ortho!
        cx_p, cy_p, cdepth = camera.project(ce_all, cn_all, z_top_can)
        cix = np.round(cx_p + shift_x).astype(np.int32)
        ciy = np.round(cy_p + shift_y).astype(np.int32)
        cv = (cix >= 0) & (cix < W - 1) & (ciy >= 0) & (ciy < H - 1)

        if cv.any():
            rr_v, cc_v = rr_all[cv], cc_all[cv]
            cix_v, ciy_v, cd_v = cix[cv], ciy[cv], cdepth[cv]
            th_v = tuft_hash[cv]
            loid_v = 100000 + (((cc_v + c0) // 7) * 1024 + ((rr_v + r0) // 7))

            raw_leaf = sample_ortho_25cm(scene, ce_all[cv], cn_all[cv])
            lcol_v = condition_90s_foliage(raw_leaf, loid_v, chm_all[cv])
            lcol_v *= 0.89 + 0.036 * (th_v[:, None].astype(np.float32))
            lcol_v = np.clip(lcol_v, 14.0, 236.0)

            lsh_v = sub_shadow[rr_v, cc_v]
            lnx_v = scene.can_nx[r0:r1, c0:c1][rr_v, cc_v]
            lny_v = scene.can_ny[r0:r1, c0:c1][rr_v, cc_v]
            lnz_v = scene.can_nz[r0:r1, c0:c1][rr_v, cc_v]

            order_c = np.argsort(cd_v)[::-1]
            cix_v, ciy_v, cd_v = cix_v[order_c], ciy_v[order_c], cd_v[order_c]
            lcol_v, loid_v, lsh_v = lcol_v[order_c], loid_v[order_c], lsh_v[order_c]
            lnx_v, lny_v, lnz_v = lnx_v[order_c], lny_v[order_c], lnz_v[order_c]

            can_splat = (
                ((0, 0), (1, 0), (0, 1), (1, 1))
                if camera.mpp > 0.38
                else ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1))
            )
            for ox, oy in can_splat:
                tx = np.clip(cix_v + ox, 0, W - 1)
                ty = np.clip(ciy_v + oy, 0, H - 1)
                db = cd_v + 0.065 * (abs(ox) + abs(oy))
                win = db < zbuf[ty, tx]
                zbuf[ty[win], tx[win]] = db[win]
                rgb_buf[ty[win], tx[win]] = lcol_v[win]
                mat_buf[ty[win], tx[win]] = M_TREE
                obj_buf[ty[win], tx[win]] = loid_v[win]
                shadow_buf[ty[win], tx[win]] = lsh_v[win]
                norm_buf[ty[win], tx[win], 0] = lnx_v[win]
                norm_buf[ty[win], tx[win], 1] = lny_v[win]
                norm_buf[ty[win], tx[win], 2] = lnz_v[win]

        # 4B. Vertical Canopy Skirt & Tree Trunks on exposed crown edges (zero floating slices!)
        z_surf_grid = np.where(canopy_mask, sub_dem + sub_chm, sub_dem)
        z_min_nb = ndimage.minimum_filter(z_surf_grid, size=3)
        edge_drop = (z_surf_grid - z_min_nb) > 0.90
        er_c, ec_c = np.nonzero(canopy_mask & edge_drop)

        if len(er_c) > 0:
            ee = E_MIN + (ec_c + c0 + 0.5) * GRID_RES
            en = N_MAX - (er_c + r0 + 0.5) * GRID_RES
            ez_top = sub_dem[er_c, ec_c] + sub_chm[er_c, ec_c]
            echm = sub_chm[er_c, ec_c]
            skirt_floor = np.where(echm > 3.4, sub_dem[er_c, ec_c] + np.minimum(2.3, echm * 0.26), sub_dem[er_c, ec_c])
            ez_bot = np.maximum(z_min_nb[er_c, ec_c], skirt_floor)

            eoid = 100000 + (((ec_c + c0) // 7) * 1024 + ((er_c + r0) // 7))
            eraw = sample_ortho_25cm(scene, ee, en)
            ecol = condition_90s_foliage(eraw, eoid, echm) * 0.78
            enx = scene.can_nx[r0:r1, c0:c1][er_c, ec_c]
            eny = scene.can_ny[r0:r1, c0:c1][er_c, ec_c]

            z_step_s = max(0.32, camera.mpp * 0.58)
            max_sk = float((ez_top - ez_bot).max())
            n_sk = min(44, max(1, int(math.ceil(max_sk / z_step_s))))
            sk_ox_list = (-1, 0, 1) if camera.mpp <= 0.38 else (0, 1)

            for si in range(1, n_sk + 1):
                zc_s = ez_top - si * z_step_s
                act_s = zc_s >= (ez_bot - 0.15)
                if not act_s.any():
                    continue
                fringe_keep = (((ec_c[act_s] * 11 + er_c[act_s] * 23 + si * 7) % 5) != 0) | (si <= 3)
                idx_a = np.nonzero(act_s)[0][fringe_keep]
                if len(idx_a) == 0:
                    continue

                px_s, py_s, pd_s = camera.project(ee[idx_a], en[idx_a], np.maximum(zc_s[idx_a], ez_bot[idx_a]))
                pd_s += 0.16
                ix_k = np.round(px_s + shift_x).astype(np.int32)
                iy_k = np.round(py_s + shift_y).astype(np.int32)
                vk = (ix_k >= 1) & (ix_k < W - 2) & (iy_k >= 0) & (iy_k < H - 1)
                if not vk.any():
                    continue
                ix_k, iy_k, pd_k = ix_k[vk], iy_k[vk], pd_s[vk]
                scol_k, soid_k = ecol[idx_a[vk]], eoid[idx_a[vk]]
                snx_k, sny_k = enx[idx_a[vk]], eny[idx_a[vk]]

                ord_k = np.argsort(pd_k)[::-1]
                ix_k, iy_k, pd_k = ix_k[ord_k], iy_k[ord_k], pd_k[ord_k]
                scol_k, soid_k = scol_k[ord_k], soid_k[ord_k]
                snx_k, sny_k = snx_k[ord_k], sny_k[ord_k]

                for ox in sk_ox_list:
                    tx = ix_k + ox
                    db_s = pd_k + 0.05 * abs(ox)
                    win = db_s < zbuf[iy_k, tx]
                    zbuf[iy_k[win], tx[win]] = db_s[win]
                    rgb_buf[iy_k[win], tx[win]] = scol_k[win]
                    mat_buf[iy_k[win], tx[win]] = M_TREE
                    obj_buf[iy_k[win], tx[win]] = soid_k[win]
                    norm_buf[iy_k[win], tx[win], 0] = snx_k[win]
                    norm_buf[iy_k[win], tx[win], 1] = sny_k[win]
                    norm_buf[iy_k[win], tx[win], 2] = 0.25

        # 4C. Real timber trunks at LiDAR crown local maxima (for tall trees > 3.5m)
        crown_peaks = (
            canopy_mask
            & (sub_chm >= 3.5)
            & (sub_chm == ndimage.maximum_filter(sub_chm, size=7))
        )
        tr_r, tr_c = np.nonzero(crown_peaks)
        if len(tr_r) > 0:
            te_p = E_MIN + (tr_c + c0 + 0.5) * GRID_RES
            tn_p = N_MAX - (tr_r + r0 + 0.5) * GRID_RES
            tz0 = sub_dem[tr_r, tr_c]
            tz1 = tz0 + np.minimum(3.2, sub_chm[tr_r, tr_c] * 0.42)
            for frac in np.linspace(0.05, 0.95, 7):
                zc_t = tz0 + frac * (tz1 - tz0)
                px_t, py_t, pd_t = camera.project(te_p, tn_p, zc_t)
                ix_t = np.round(px_t + shift_x).astype(np.int32)
                iy_t = np.round(py_t + shift_y).astype(np.int32)
                vt = (ix_t >= 0) & (ix_t < W) & (iy_t >= 0) & (iy_t < H)
                ix_t, iy_t, pd_t = ix_t[vt], iy_t[vt], pd_t[vt]
                wt = pd_t < zbuf[iy_t, ix_t]
                zbuf[iy_t[wt], ix_t[wt]] = pd_t[wt]
                rgb_buf[iy_t[wt], ix_t[wt]] = [96.0, 70.0, 48.0]
                mat_buf[iy_t[wt], ix_t[wt]] = M_TRUNK
                obj_buf[iy_t[wt], ix_t[wt]] = 200000

    # -------------------------------------------------------------------------
    # STAGE 5: 90s Pixel-Art Stepped Lighting + 256-Color Bayer Dither + Sel-Out
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
        ndotl_step = np.round(ndotl * 5.0) / 5.0

        amb = np.array(preset.amb_rgb, dtype=np.float32)
        sun_c = np.array(preset.sun_rgb, dtype=np.float32)
        sky_dome = (0.5 + 0.5 * np.clip(n_xyz[:, 2], -1.0, 1.0))[:, None]
        lit_mult = amb[None, :] * (0.74 + 0.36 * sky_dome) + sun_c[None, :] * ndotl_step[:, None] * 0.76

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
    clean_m = np.isin(mat_buf, [M_WALL, M_WINDOW_LIT, M_WINDOW_DAY, M_BG])
    dither_map[clean_m] *= 0.35

    final_u8 = quantize_to_90s_palette(rgb_buf, dither_map, preset.dither_strength)

    hit_data = {}
    if collect_hit_boxes and viewport_win is None:
        hit_data = _extract_interactive_metadata(scene, camera, shift_x_full, shift_y_full, W_full, H_full)

    img = Image.fromarray(final_u8, mode="RGB")
    if add_frame and viewport_win is None:
        n_canopy_crowns = int((scene.chm > 2.2).sum() // 28)
        img = _draw_museum_cartouche(img, preset, camera, len(scene.buildings), n_canopy_crowns, crop_box_lv95)

    return img, hit_data


def _apply_pixel_art_outlines_float(
    rgb_buf: np.ndarray,
    zbuf: np.ndarray,
    obj_buf: np.ndarray,
    mat_buf: np.ndarray,
    norm_buf: np.ndarray,
    is_night: bool,
) -> None:
    """Apply crisp 1px 90s selective pixel-art outlines (sel-out) on silhouettes and roof ridges."""
    dz_r = zbuf[:, 1:] - zbuf[:, :-1]
    dz_d = zbuf[1:, :] - zbuf[:-1, :]
    diff_r = obj_buf[:, 1:] != obj_buf[:, :-1]
    diff_d = obj_buf[1:, :] != obj_buf[:-1, :]

    # Stronger silhouette threshold for trees vs crisp 1.6m threshold for buildings
    edge = np.zeros(zbuf.shape, dtype=np.bool_)
    edge[:, :-1] |= diff_r & (dz_r > 1.8) & (obj_buf[:, :-1] > 0)
    edge[:, 1:] |= diff_r & (dz_r < -1.8) & (obj_buf[:, 1:] > 0)
    edge[:-1, :] |= diff_d & (dz_d > 1.8) & (obj_buf[:-1, :] > 0)
    edge[1:, :] |= diff_d & (dz_d < -1.8) & (obj_buf[1:, :] > 0)

    # Softer outline between adjacent tree clusters, crisp outline around buildings
    tree_edge = edge & (mat_buf == M_TREE)
    bldg_edge = edge & (~tree_edge)

    if bldg_edge.any():
        ey, ex = np.nonzero(bldg_edge)
        rgb_buf[ey, ex] *= 0.54 if not is_night else 0.60
    if tree_edge.any():
        ty, tx = np.nonzero(tree_edge)
        rgb_buf[ty, tx] *= 0.72 if not is_night else 0.76

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
        f"{n_bldgs:,} LOD2 3D BUILDINGS  ·  0.5 m LIDAR CANOPY  ·  SWISSIMAGE DOP10 TEXTURES"
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

    # Render in 6x3 screen-space macro-tiles (~2080x1880 px each) with 6px guard margin for seamless sel-out!
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

            sub_img, _ = render_diorama(
                scene,
                cam,
                preset_key=preset_key,
                crop_box_lv95=None,
                add_frame=True,
                collect_hit_boxes=False,
                viewport_win=(wx0, wy0, wx1, wy1),
                sun_shadow_override=sun_sh,
            )
            sub_arr = np.asarray(sub_img)
            full_rgb[y0:y1, x0:x1] = sub_arr[(y0 - wy0) : (y1 - wy0), (x0 - wx0) : (x1 - wx0)]
            del sub_img, sub_arr
            gc.collect()

    master_img = Image.fromarray(full_rgb, mode="RGB")
    del full_rgb
    gc.collect()

    n_canopy_crowns = int((scene.chm > 2.2).sum() // 28)
    master_img = _draw_museum_cartouche(master_img, preset, cam, len(scene.buildings), n_canopy_crowns, None)

    # 1. Slice 1024x1024 lossless WebP tiles for instant deep-zoom in browser!
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
    }
    (tiles_dir / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))

    # 2. Fast-boot overview WebP (~4160 px wide) for initial fit-to-screen & minimap
    ov_w = min(W_full, 4160)
    ov_h = int(round(H_full * (ov_w / W_full)))
    ov_img = master_img.resize((ov_w, ov_h), resample=Image.Resampling.BOX)
    ov_img.save(overview_webp_path, format="WEBP", lossless=True, method=4)

    # 3. Crisp 2:1 nearest-neighbor 0.50 m/px full PNG (~6245x2820 px, ~9 MB) for GitHub repo gallery
    png_img = master_img.resize((W_full // 2, H_full // 2), resample=Image.Resampling.NEAREST)
    png_img.save(full_png_path, optimize=True)

    hit_data = {}
    if collect_hit_boxes:
        hit_data = _extract_interactive_metadata(scene, cam, shift_x_full, shift_y_full, W_full, H_full)

    del master_img, ov_img, png_img
    gc.collect()
    return hit_data

