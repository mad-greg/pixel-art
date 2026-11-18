"""True 3D Isometric Z-Buffered Pixel-Art Shader for Kilchberg ZH.

Combines:
- Carved floating geological & Lake Zurich bathymetric cutaway diorama block
- 0.5m swissALTI3D bare-earth relief + 10cm SWISSIMAGE + swisstopo MVT ground fusion
- Exact 3D LOD2 CityGML triangle rasterization (124,000+ roof & wall triangles)
- Seamless world-space facade window grids (daytime glass reflections & nighttime warm glow)
- Real 0.5m LiDAR shadow mapping, individual pixel-art trees, moored boats, S-Bahn & ZSG steamer
- Ordered 4x4 Bayer dithering, curated stepped pixel-art color ramps & selective outlines (sel-out)
"""

from __future__ import annotations
import json
import math
from dataclasses import dataclass
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
    G_FOOTPATH,
    G_FOREST,
    G_LAKE,
    G_MOTORWAY,
    G_PARK_CEMETERY,
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

# Material IDs
M_BG = 0
M_DROP_SHADOW = 1
M_CUTAWAY_EARTH = 2
M_CUTAWAY_WATER = 3
M_WATER_LAKE = 4
M_WATER_POOL = 5
M_GROUND = 6
M_ROAD = 7
M_RAIL = 8
M_WALL = 9
M_ROOF = 10
M_WINDOW_LIT = 11
M_WINDOW_DAY = 12
M_TREE = 13
M_BOAT = 14
M_VEHICLE = 15

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
    sun_az_deg: float        # Compass bearing FROM which sunlight shines
    sun_alt_deg: float       # Elevation angle above horizon
    sun_rgb: tuple[float, float, float]
    amb_rgb: tuple[float, float, float]
    sky_top_rgb: tuple[int, int, int]
    sky_bot_rgb: tuple[int, int, int]
    is_night: bool = False
    dither_strength: float = 11.0
    color_levels: int = 20   # Per-channel pixel-art quantization steps


PRESETS: dict[str, LightingPreset] = {
    "day": LightingPreset(
        name="Swiss Crisp Midday",
        sun_az_deg=148.0,
        sun_alt_deg=41.0,
        sun_rgb=(1.06, 1.01, 0.92),
        amb_rgb=(0.46, 0.51, 0.60),
        sky_top_rgb=(28, 38, 56),
        sky_bot_rgb=(42, 56, 78),
        is_night=False,
        dither_strength=10.5,
        color_levels=22,
    ),
    "sunset": LightingPreset(
        name="Alpenglow Golden Sunset",
        sun_az_deg=118.0,
        sun_alt_deg=21.0,
        sun_rgb=(1.22, 0.84, 0.56),
        amb_rgb=(0.42, 0.39, 0.55),
        sky_top_rgb=(36, 28, 52),
        sky_bot_rgb=(74, 46, 62),
        is_night=False,
        dither_strength=11.5,
        color_levels=20,
    ),
    "night": LightingPreset(
        name="Zürichsee Lantern Night",
        sun_az_deg=135.0,
        sun_alt_deg=36.0,
        sun_rgb=(0.24, 0.30, 0.48),
        amb_rgb=(0.17, 0.21, 0.35),
        sky_top_rgb=(13, 18, 32),
        sky_bot_rgb=(22, 30, 50),
        is_night=True,
        dither_strength=9.0,
        color_levels=22,
    ),
}


class SceneData:
    """Loaded Kilchberg 0.5m rasters + 3D CityGML meshes + metadata."""

    def __init__(self, cache_dir: Path = RAW_CACHE_DIR):
        s = np.load(cache_dir / "scene_kilchberg_05m.npz")
        self.dem = s["dem"].astype(np.float32)
        self.chm = s["chm"].astype(np.float32)
        self.ortho = s["ortho"]
        self.sem = s["sem"]
        self.diorama_mask = s["diorama_mask"]
        self.kpoly_mask = s["kpoly_mask"]
        self.lake_mask = s["lake_mask"]
        self.bathy_z = s["bathy_z"].astype(np.float32)
        self.tree_e = s["tree_e"]
        self.tree_n = s["tree_n"]
        self.tree_z = s["tree_z"]
        self.tree_h = s["tree_h"]
        self.tree_rad = s["tree_rad"]
        self.tree_rgb = s["tree_rgb"]

        b = np.load(cache_dir / "buildings_kilchberg_3d.npz")
        self.verts = b["verts"]
        self.normals = b["normals"]
        self.bldg_idx = b["bldg_idx"]
        self.surf_type = b["surf_type"]
        self.tri_rgb = b["rgb"]

        meta = json.loads((cache_dir / "buildings_kilchberg_meta.json").read_text())
        self.buildings = meta["buildings"]
        self.boats = meta["boats"]

        # Precompute terrain surface normals (nx, ny, nz) at 0.5m
        # Note: row index increases southward (-N), col index increases eastward (+E)
        dz_drow, dz_dcol = np.gradient(ndimage.gaussian_filter(self.dem, sigma=0.8), GRID_RES)
        nx = -dz_dcol
        ny = dz_drow
        nz = np.ones_like(nx)
        nlen = np.sqrt(nx * nx + ny * ny + nz * nz)
        self.terr_nx = (nx / nlen).astype(np.float32)
        self.terr_ny = (ny / nlen).astype(np.float32)
        self.terr_nz = (nz / nlen).astype(np.float32)


def compute_shadow_grid(scene: SceneData, sun_az_deg: float, sun_alt_deg: float, mask_sub: np.ndarray | None = None) -> np.ndarray:
    """Ray-march 0.5m LiDAR surface (DEM + CHM/buildings) toward sun to produce crisp cast shadows."""
    # Downsample 2x (1.0m) for super-fast, clean pixel-art shadow casting across 95 meters
    h_surf = (scene.dem + scene.chm)[::2, ::2].copy()
    sh = np.zeros_like(h_surf, dtype=np.bool_)
    az = math.radians(sun_az_deg)
    alt = math.radians(sun_alt_deg)
    # Vector toward sun in (col=+E, row=-N) at 1.0m step
    dcol = math.sin(az)
    drow = -math.cos(az)
    dz_per_m = math.tan(alt)

    H2, W2 = h_surf.shape
    for dist in np.linspace(2.0, 88.0, 28):
        sc = int(round(dcol * dist))
        sr = int(round(drow * dist))
        if sc == 0 and sr == 0:
            continue
        r0_src = max(0, sr)
        r1_src = min(H2, H2 + sr)
        c0_src = max(0, sc)
        c1_src = min(W2, W2 + sc)

        r0_dst = r0_src - sr
        r1_dst = r1_src - sr
        c0_dst = c0_src - sc
        c1_dst = c1_src - sc

        blocker = h_surf[r0_src:r1_src, c0_src:c1_src] - dz_per_m * dist
        sh[r0_dst:r1_dst, c0_dst:c1_dst] |= blocker > (h_surf[r0_dst:r1_dst, c0_dst:c1_dst] + 0.65)

    # Upsample back to 0.5m grid
    full_sh = np.repeat(np.repeat(sh, 2, axis=0), 2, axis=1)[:GRID_H, :GRID_W]
    return full_sh


def build_ground_base_rgb(scene: SceneData, r_slice: slice, c_slice: slice) -> np.ndarray:
    """Fuse 10cm SWISSIMAGE DOP10 with official swisstopo semantic topography for rich pixel-art ground."""
    ortho = scene.ortho[r_slice, c_slice].astype(np.float32)
    sem = scene.sem[r_slice, c_slice]
    dem = scene.dem[r_slice, c_slice]
    bathy_z = scene.bathy_z[r_slice, c_slice]
    kpoly = scene.kpoly_mask[r_slice, c_slice]

    H, W = sem.shape
    out = np.empty((H, W, 3), dtype=np.float32)

    # Normalize / brighten dark aerial tree shadows in SWISSIMAGE so ground lawns & patios stay clean
    lum = 0.299 * ortho[:, :, 0] + 0.587 * ortho[:, :, 1] + 0.114 * ortho[:, :, 2]
    lift = np.where(lum < 75.0, 75.0 / np.maximum(lum, 18.0), 1.0)
    lift = np.minimum(lift, 2.1)[:, :, None]
    ortho_lifted = np.clip(ortho * lift, 0, 245)

    # Base meadow / garden / courtyard blend
    # Detect paved courtyards/patios/driveways in SWISSIMAGE (low green-excess, medium-high brightness)
    g_ex = ortho_lifted[:, :, 1] - 0.52 * ortho_lifted[:, :, 0] - 0.48 * ortho_lifted[:, :, 2]
    is_paved = (g_ex < 7.0) & (lum > 88.0)

    grass_curated = np.empty_like(out)
    grass_curated[:, :, 0] = 104.0
    grass_curated[:, :, 1] = 156.0
    grass_curated[:, :, 2] = 78.0
    out[:] = np.where(
        is_paved[:, :, None],
        0.48 * np.array([196.0, 191.0, 180.0]) + 0.52 * ortho_lifted,
        0.54 * grass_curated + 0.46 * ortho_lifted,
    )

    # Forest floor
    m = sem == G_FOREST
    if m.any():
        out[m] = 0.62 * np.array([66.0, 112.0, 58.0]) + 0.38 * ortho_lifted[m]

    # Parks & church cemetery
    m = sem == G_PARK_CEMETERY
    if m.any():
        out[m] = np.where(
            is_paved[m][:, None],
            np.array([208.0, 201.0, 186.0]),
            0.60 * np.array([112.0, 166.0, 86.0]) + 0.40 * ortho_lifted[m],
        )

    # Vineyards (crisscrossed with world-coordinate grapevine row stripes!)
    m = sem == G_VINEYARD
    if m.any():
        rr, cc = np.nonzero(m)
        world_e = E_MIN + (cc + c_slice.start) * GRID_RES
        world_n = N_MAX - (rr + r_slice.start) * GRID_RES
        # Rows oriented downslope (ENE) spaced every 2.2m
        phase = ((world_e * 0.42 + world_n * 0.91) % 2.2) < 1.15
        vine_col = np.where(
            phase[:, None],
            np.array([86.0, 148.0, 62.0]),   # Lush grapevine row
            np.array([164.0, 146.0, 112.0]), # Sunlit vineyard terroir soil
        )
        out[rr, cc] = vine_col

    # Sports pitches & clay/hard tennis courts (keep real red clay or green turf from SWISSIMAGE!)
    m = sem == G_PITCH
    if m.any():
        out[m] = 0.35 * np.array([120.0, 168.0, 96.0]) + 0.65 * ortho_lifted[m]

    # Streams
    m = sem == G_STREAM
    if m.any():
        out[m] = np.array([76.0, 146.0, 168.0])

    # Footpaths & garden steps (warm sandstone/gravel buff)
    m = sem == G_FOOTPATH
    if m.any():
        out[m] = np.array([198.0, 186.0, 164.0])

    # Streets & roads (crisp slate-blue asphalt + subtle edge curbs)
    for code, col in (
        (G_STREET_MINOR, (124.0, 130.0, 140.0)),
        (G_STREET_MAIN, (104.0, 111.0, 123.0)),
        (G_MOTORWAY, (92.0, 100.0, 114.0)),
    ):
        m = sem == code
        if m.any():
            eroded = ndimage.binary_erosion(m, iterations=1)
            curb = m & (~eroded)
            out[m] = np.array(col)
            out[curb] = np.array([178.0, 180.0, 182.0])

    # SBB Seebahn railway ballast & steel rails/sleepers
    m = sem == G_RAILWAY
    if m.any():
        rr, cc = np.nonzero(m)
        we = E_MIN + (cc + c_slice.start) * GRID_RES
        wn = N_MAX - (rr + r_slice.start) * GRID_RES
        tie = ((we * 0.38 + wn * 0.92) % 1.8) < 0.65
        out[rr, cc] = np.where(
            tie[:, None],
            np.array([96.0, 84.0, 76.0]),    # Timber/concrete sleepers + rail
            np.array([142.0, 136.0, 130.0]), # Crushed granite ballast
        )

    # Station platforms & harbor piers
    m = sem == G_PLATFORM_PIER
    if m.any():
        out[m] = np.array([214.0, 208.0, 196.0])

    # Backyard & lido swimming pools (Capri turquoise + crisp white coping)
    m = sem == G_POOL
    if m.any():
        eroded = ndimage.binary_erosion(m, iterations=1)
        coping = m & (~eroded)
        out[m] = np.array([62.0, 196.0, 222.0])
        out[coping] = np.array([236.0, 236.0, 232.0])

    # Lake Zurich (Zürichsee): depth-graded Swiss turquoise shallows -> deep cobalt + pixel wavelets
    m = sem == G_LAKE
    if m.any():
        rr, cc = np.nonzero(m)
        depth_m = np.clip(LAKE_SURFACE_Z - bathy_z[rr, cc], 0.0, 65.0)
        we = E_MIN + (cc + c_slice.start) * GRID_RES
        wn = N_MAX - (rr + r_slice.start) * GRID_RES

        # Shallow emerald-turquoise shelf (0..5m) -> teal (5..18m) -> deep Zürichsee sapphire (>25m)
        t_sh = np.clip(depth_m / 6.5, 0.0, 1.0)[:, None]
        t_dp = np.clip((depth_m - 6.5) / 28.0, 0.0, 1.0)[:, None]
        c_shallow = np.array([74.0, 184.0, 182.0])
        c_mid = np.array([42.0, 128.0, 158.0])
        c_deep = np.array([26.0, 78.0, 124.0])
        w_col = (1.0 - t_sh) * c_shallow + t_sh * ((1.0 - t_dp) * c_mid + t_dp * c_deep)

        # Crisp elongated pixel-art wind ripples & shoreline foam (no circular dots!)
        u_w = we * 0.21 + wn * 0.97
        v_w = -we * 0.97 + wn * 0.21
        wave = np.sin(v_w * 0.55 + np.sin(u_w * 0.08) * 2.4) * np.cos(u_w * 0.09 - v_w * 0.06)
        sparkle = wave > 0.78
        trough = wave < -0.74
        w_col[sparkle] += np.array([22.0, 28.0, 26.0])
        w_col[trough] -= np.array([7.0, 11.0, 9.0])
        shore_foam = depth_m < 0.65
        w_col[shore_foam] = 0.55 * w_col[shore_foam] + 0.45 * np.array([212.0, 236.0, 238.0])
        out[rr, cc] = np.clip(w_col, 0, 255)

    # Subtle municipal boundary accent: slightly cooler muted tone on the 16m collar outside strict Kilchberg
    outside_k = (~kpoly) & (sem != G_LAKE)
    if outside_k.any():
        gray = out[outside_k].mean(axis=1, keepdims=True)
        out[outside_k] = 0.72 * out[outside_k] + 0.28 * gray

    return np.clip(out, 0, 255).astype(np.uint8)


def render_diorama(
    scene: SceneData,
    camera: IsometricCamera,
    preset_key: str = "day",
    crop_box_lv95: tuple[float, float, float, float] | None = None,
    add_frame: bool = True,
    collect_hit_boxes: bool = False,
) -> tuple[Image.Image, dict]:
    """Render either the full carved floating diorama of Kilchberg ZH or an ultra-detail landmark crop."""
    preset = PRESETS[preset_key]

    if crop_box_lv95 is not None:
        e0, n0, e1, n1 = crop_box_lv95
        c0 = max(0, int((e0 - E_MIN) / GRID_RES))
        c1 = min(GRID_W, int(math.ceil((e1 - E_MIN) / GRID_RES)))
        r0 = max(0, int((N_MAX - n1) / GRID_RES))
        r1 = min(GRID_H, int(math.ceil((N_MAX - n0) / GRID_RES)))
        active_mask = np.zeros((GRID_H, GRID_W), dtype=np.bool_)
        active_mask[r0:r1, c0:c1] = True
        use_plinth = True
        plinth_z = max(PLINTH_BASE_Z, float(scene.dem[r0:r1, c0:c1].min()) - 28.0)
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
        use_plinth = True
        plinth_z = PLINTH_BASE_Z

    sub_mask = active_mask[r0:r1, c0:c1]
    sub_dem = scene.dem[r0:r1, c0:c1]
    sub_sem = scene.sem[r0:r1, c0:c1]
    sub_lake = scene.lake_mask[r0:r1, c0:c1]
    sub_bathy = scene.bathy_z[r0:r1, c0:c1]

    # Determine exact canvas bounds from extreme active ground + roof + plinth points
    ar, ac = np.nonzero(sub_mask)
    ae = E_MIN + (ac + c0 + 0.5) * GRID_RES
    an = N_MAX - (ar + r0 + 0.5) * GRID_RES
    az_top = sub_dem[ar, ac] + 48.0
    az_bot = np.full_like(az_top, plinth_z - 6.0)

    px1, py1, _ = camera.project(ae[::8], an[::8], az_top[::8])
    px2, py2, _ = camera.project(ae[::8], an[::8], az_bot[::8])

    pad_x = 90 if add_frame else 28
    pad_top = 125 if add_frame else 28
    pad_bot = 155 if add_frame else 32

    min_x = float(min(px1.min(), px2.min()))
    max_x = float(max(px1.max(), px2.max()))
    min_y = float(min(py1.min(), py2.min()))
    max_y = float(max(py1.max(), py2.max()))

    W = int(math.ceil(max_x - min_x)) + 2 * pad_x
    H = int(math.ceil(max_y - min_y)) + pad_top + pad_bot
    shift_x = -min_x + pad_x
    shift_y = -min_y + pad_top

    # Initialize buffers
    zbuf = np.full((H, W), 1e9, dtype=np.float32)
    rgb_buf = np.zeros((H, W, 3), dtype=np.uint8)
    mat_buf = np.zeros((H, W), dtype=np.uint8)
    obj_buf = np.full((H, W), -1, dtype=np.int32)
    norm_buf = np.zeros((H, W, 3), dtype=np.float32)
    norm_buf[:, :, 2] = 1.0
    shadow_buf = np.zeros((H, W), dtype=np.bool_)

    # Studio gradient backdrop with subtle Bayer pixel dither
    gy = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None]
    bg_top = np.array(preset.sky_top_rgb, dtype=np.float32)
    bg_bot = np.array(preset.sky_bot_rgb, dtype=np.float32)
    bg_grad = (1.0 - gy) * bg_top + gy * bg_bot
    bayer_tiled = np.tile(BAYER_4X4, (H // 4 + 1, W // 4 + 1))[:H, :W]
    rgb_buf[:] = np.clip(bg_grad[:, None, :] + bayer_tiled[:, :, None] * 5.0, 0, 255).astype(np.uint8)

    # Precompute 0.5m LiDAR sun shadow grid
    sun_shadow_grid = compute_shadow_grid(scene, preset.sun_az_deg, preset.sun_alt_deg)
    sub_shadow = sun_shadow_grid[r0:r1, c0:c1]

    # Sun 3D unit vector (pointing TOWARD sun)
    s_az = math.radians(preset.sun_az_deg)
    s_alt = math.radians(preset.sun_alt_deg)
    sun_vec = np.array(
        [math.sin(s_az) * math.cos(s_alt), math.cos(s_az) * math.cos(s_alt), math.sin(s_alt)],
        dtype=np.float32,
    )

    # -------------------------------------------------------------------------
    # STAGE 1: Drop shadow beneath floating island + Carved Cutaway Cliffs
    # -------------------------------------------------------------------------
    if use_plinth:
        # Soft dithered drop shadow cast onto display table 14m below plinth_z
        sh_step = max(1, int(round(camera.mpp / 0.5)))
        sr_idx = ar[::sh_step * 2]
        sc_idx = ac[::sh_step * 2]
        se = E_MIN + (sc_idx + c0 + 0.5) * GRID_RES + 14.0
        sn = N_MAX - (sr_idx + r0 + 0.5) * GRID_RES - 12.0
        sz = np.full_like(se, plinth_z - 12.0)
        sx_p, sy_p, _ = camera.project(se, sn, sz)
        ix = np.round(sx_p + shift_x).astype(np.int32)
        iy = np.round(sy_p + shift_y).astype(np.int32)
        v_sh = (ix >= 1) & (ix < W - 2) & (iy >= 1) & (iy < H - 2)
        ix, iy = ix[v_sh], iy[v_sh]
        for ox in (0, 1):
            for oy in (0, 1):
                # Checkerboard dither at shadow edge
                rgb_buf[iy + oy, ix + ox] = (rgb_buf[iy + oy, ix + ox].astype(np.float32) * 0.62).astype(np.uint8)
                mat_buf[iy + oy, ix + ox] = M_DROP_SHADOW

        # Perimeter cells of sub_mask for vertical cutaway walls
        eroded_m = ndimage.binary_erosion(sub_mask, iterations=2, border_value=0)
        perim = sub_mask & (~eroded_m)
        # Outward horizontal normal of diorama perimeter
        sm_f = ndimage.gaussian_filter(sub_mask.astype(np.float32), sigma=2.0)
        dm_drow, dm_dcol = np.gradient(sm_f)
        out_nx = -dm_dcol
        out_ny = dm_drow

        pr, pc = np.nonzero(perim)
        pe = E_MIN + (pc + c0 + 0.5) * GRID_RES
        pn = N_MAX - (pr + r0 + 0.5) * GRID_RES
        pz_top = sub_dem[pr, pc]
        p_lake = sub_lake[pr, pc]
        p_bathy = np.maximum(sub_bathy[pr, pc], plinth_z + 7.0)
        pnx = out_nx[pr, pc]
        pny = out_ny[pr, pc]
        plen = np.maximum(np.hypot(pnx, pny), 1e-5)
        pnx /= plen
        pny /= plen

        # Sample vertical columns every 0.45 * mpp meters from plinth_z to pz_top
        dz_step = max(0.35, camera.mpp * 0.52)
        max_col_h = float((pz_top - plinth_z).max()) if len(pz_top) else 0.0
        n_zsteps = max(2, int(math.ceil(max_col_h / dz_step)) + 1)

        for zi in range(n_zsteps):
            z_cur = plinth_z + zi * dz_step
            active_c = z_cur <= (pz_top + 0.25)
            if not active_c.any():
                continue
            ce = pe[active_c]
            cn = pn[active_c]
            cz = np.minimum(z_cur, pz_top[active_c])
            cz_top = pz_top[active_c]
            c_islake = p_lake[active_c]
            c_bathy = p_bathy[active_c]
            cnx = pnx[active_c]
            cny = pny[active_c]

            px, py, pdepth = camera.project(ce, cn, cz)
            # Bias cutaway slightly behind top lip so top grass/water lip cleanly caps it
            pdepth = pdepth + 0.35
            ix = np.round(px + shift_x).astype(np.int32)
            iy = np.round(py + shift_y).astype(np.int32)
            valid = (ix >= 0) & (ix < W - 1) & (iy >= 0) & (iy < H - 1)
            if not valid.any():
                continue
            ix, iy, pdepth = ix[valid], iy[valid], pdepth[valid]
            cz, cz_top = cz[valid], cz_top[valid]
            c_islake, c_bathy = c_islake[valid], c_bathy[valid]
            cnx, cny, ce_v = cnx[valid], cny[valid], ce[valid]

            # Geological & Underwater Bathymetry Strata Color
            depth_from_top = cz_top - cz
            above_plinth = cz - plinth_z
            col = np.empty((len(ix), 3), dtype=np.float32)

            # Default: Layered Swiss Upper Freshwater Molasse sandstone & marlstone
            strata_wave = np.sin(cz * 0.65 + ce_v * 0.012)
            col[:] = np.where(
                (strata_wave > 0.15)[:, None],
                np.array([136.0, 125.0, 108.0]),
                np.array([116.0, 106.0, 92.0]),
            )
            # Zimmerberg Würm glacial moraine ochre layer (3.5..18m below surface)
            moraine = (depth_from_top >= 3.2) & (depth_from_top < 18.5) & (~c_islake)
            col[moraine] = np.array([158.0, 134.0, 98.0])
            # Rich dark brown humus topsoil (1.0..3.2m)
            humus = (depth_from_top >= 0.9) & (depth_from_top < 3.2) & (~c_islake)
            col[humus] = np.array([104.0, 78.0, 56.0])
            # Overhanging green grass sod lip (0..0.9m)
            sod = (depth_from_top < 0.9) & (~c_islake)
            col[sod] = np.array([92.0, 144.0, 68.0])

            # Lake Zurich translucent aquarium cutaway column!
            in_water_col = c_islake & (cz >= c_bathy)
            if in_water_col.any():
                w_d = np.clip(LAKE_SURFACE_Z - cz[in_water_col], 0.0, 55.0)
                t_w = np.clip(w_d / 34.0, 0.0, 1.0)[:, None]
                col[in_water_col] = (1.0 - t_w) * np.array([58.0, 166.0, 184.0]) + t_w * np.array([22.0, 68.0, 118.0])
                # Bright surface meniscus line
                surf_lip = w_d < 1.1
                col[in_water_col] = np.where(surf_lip[:, None], np.array([175.0, 232.0, 238.0]), col[in_water_col])

            # Lakebed silt beneath water column
            sub_bed = c_islake & (cz < c_bathy)
            col[sub_bed] = np.array([112.0, 108.0, 98.0])

            # Dark museum base plinth trim at very bottom (0..2.6m above plinth_z)
            plinth_trim = above_plinth < 2.6
            col[plinth_trim] = np.array([54.0, 52.0, 58.0])

            c_mat = np.where(in_water_col, M_CUTAWAY_WATER, M_CUTAWAY_EARTH).astype(np.uint8)
            order = np.argsort(pdepth)[::-1]  # Far-to-near painter's write gated by zbuf
            ix, iy, pdepth = ix[order], iy[order], pdepth[order]
            col, c_mat = col[order], c_mat[order]
            cnx, cny = cnx[order], cny[order]

            for ox in (0, 1):
                tx = ix + ox
                win = pdepth < zbuf[iy, tx]
                # Since multiple points may hit same pixel in one slice, sort guarantees nearest wins if we mask against existing zbuf
                zbuf[iy[win], tx[win]] = pdepth[win]
                rgb_buf[iy[win], tx[win]] = np.clip(col[win], 0, 255).astype(np.uint8)
                mat_buf[iy[win], tx[win]] = c_mat[win]
                obj_buf[iy[win], tx[win]] = 0
                norm_buf[iy[win], tx[win], 0] = cnx[win]
                norm_buf[iy[win], tx[win], 1] = cny[win]
                norm_buf[iy[win], tx[win], 2] = 0.12

    # -------------------------------------------------------------------------
    # STAGE 2: Watertight 0.5m Terrain, Streets, Vineyards, Pools & Lake Surface
    # -------------------------------------------------------------------------
    ground_rgb = build_ground_base_rgb(scene, slice(r0, r1), slice(c0, c1))
    sub_nx = scene.terr_nx[r0:r1, c0:c1]
    sub_ny = scene.terr_ny[r0:r1, c0:c1]
    sub_nz = scene.terr_nz[r0:r1, c0:c1]

    # Sample step matched tightly to camera mpp so every screen pixel gets covered cleanly
    g_step = 1 if camera.mpp <= 0.55 else 1
    gr, gc = np.nonzero(sub_mask[::g_step, ::g_step])
    gr *= g_step
    gc *= g_step

    ge = E_MIN + (gc + c0 + 0.5) * GRID_RES
    gn = N_MAX - (gr + r0 + 0.5) * GRID_RES
    gz = sub_dem[gr, gc]
    gcol = ground_rgb[gr, gc]
    gsem = sub_sem[gr, gc]
    gsh = sub_shadow[gr, gc]
    gnx = sub_nx[gr, gc]
    gny = sub_ny[gr, gc]
    gnz = sub_nz[gr, gc]

    # Flatten water normals for crisp specular shading
    is_w = (gsem == G_LAKE) | (gsem == G_POOL)
    gnx[is_w] = 0.0
    gny[is_w] = 0.0
    gnz[is_w] = 1.0

    gx_p, gy_p, gdepth = camera.project(ge, gn, gz)
    gix = np.round(gx_p + shift_x).astype(np.int32)
    giy = np.round(gy_p + shift_y).astype(np.int32)
    gv = (gix >= 0) & (gix < W - 1) & (giy >= 0) & (giy < H - 1)

    gix, giy, gdepth = gix[gv], giy[gv], gdepth[gv]
    gcol, gsem, gsh = gcol[gv], gsem[gv], gsh[gv]
    gnx, gny, gnz = gnx[gv], gny[gv], gnz[gv]

    gmat = np.full(len(gix), M_GROUND, dtype=np.uint8)
    gmat[gsem == G_LAKE] = M_WATER_LAKE
    gmat[gsem == G_POOL] = M_WATER_POOL
    gmat[np.isin(gsem, [G_STREET_MINOR, G_STREET_MAIN, G_MOTORWAY])] = M_ROAD
    gmat[gsem == G_RAILWAY] = M_RAIL

    order = np.argsort(gdepth)[::-1]
    gix, giy, gdepth = gix[order], giy[order], gdepth[order]
    gcol, gmat, gsh = gcol[order], gmat[order], gsh[order]
    gnx, gny, gnz = gnx[order], gny[order], gnz[order]

    # Splat footprint (2x2 at mpp>=0.5, 3x3 at ultra-close zoom mpp<0.42 so 0.5m cells leave zero pinholes!)
    splat_offsets = ((0, 0), (1, 0), (0, 1), (1, 1)) if camera.mpp >= 0.42 else (
        (0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)
    )
    for ox, oy in splat_offsets:
        tx = np.clip(gix + ox, 0, W - 1)
        ty = np.clip(giy + oy, 0, H - 1)
        d_bias = gdepth + (0.08 if (ox != 0 or oy != 0) else 0.0)
        win = d_bias <= zbuf[ty, tx]
        zbuf[ty[win], tx[win]] = d_bias[win]
        rgb_buf[ty[win], tx[win]] = gcol[win]
        mat_buf[ty[win], tx[win]] = gmat[win]
        obj_buf[ty[win], tx[win]] = 0
        shadow_buf[ty[win], tx[win]] = gsh[win]
        norm_buf[ty[win], tx[win], 0] = gnx[win]
        norm_buf[ty[win], tx[win], 1] = gny[win]
        norm_buf[ty[win], tx[win], 2] = gnz[win]

    # -------------------------------------------------------------------------
    # STAGE 3: True 3D LOD2 Building Triangle Rasterization + Pixel Windows
    # -------------------------------------------------------------------------
    verts = scene.verts
    norms = scene.normals
    bidx = scene.bldg_idx
    stype = scene.surf_type
    trgb = scene.tri_rgb

    if crop_box_lv95 is not None:
        e0, n0, e1, n1 = crop_box_lv95
        tc = verts.mean(axis=1)
        in_crop = (tc[:, 0] >= e0 - 8) & (tc[:, 0] <= e1 + 8) & (tc[:, 1] >= n0 - 8) & (tc[:, 1] <= n1 + 8)
        verts = verts[in_crop]
        norms = norms[in_crop]
        bidx = bidx[in_crop]
        stype = stype[in_crop]
        trgb = trgb[in_crop]

    # Lookup arrays for building ground elevation & seed
    n_bldgs = len(scene.buildings)
    bldg_z0 = np.array([b["z_ground"] for b in scene.buildings], dtype=np.float32)
    bldg_e0 = np.array([b["e"] for b in scene.buildings], dtype=np.float32)
    bldg_n0 = np.array([b["n"] for b in scene.buildings], dtype=np.float32)
    bldg_h = np.array([b["height"] for b in scene.buildings], dtype=np.float32)
    bldg_obj = [b["objektart"] for b in scene.buildings]
    bldg_no_win = np.array(
        [o in ("Flugdach", "Offenes Gebaeude", "Lagertank", "Hochkamin", "Mauer gross") for o in bldg_obj],
        dtype=np.bool_,
    )

    if len(verts) > 0:
        # Project all triangle vertices (N_tri, 3)
        px_v, py_v, pd_v = camera.project(verts[:, :, 0], verts[:, :, 1], verts[:, :, 2])
        px_v += shift_x
        py_v += shift_y

        x_min_t = np.floor(px_v.min(axis=1)).astype(np.int32)
        x_max_t = np.ceil(px_v.max(axis=1)).astype(np.int32)
        y_min_t = np.floor(py_v.min(axis=1)).astype(np.int32)
        y_max_t = np.ceil(py_v.max(axis=1)).astype(np.int32)

        # Keep triangles inside screen bounds with non-degenerate screen area
        dx1 = px_v[:, 1] - px_v[:, 0]
        dy1 = py_v[:, 1] - py_v[:, 0]
        dx2 = px_v[:, 2] - px_v[:, 0]
        dy2 = py_v[:, 2] - py_v[:, 0]
        det = dx1 * dy2 - dx2 * dy1

        vis = (
            (x_max_t >= 0)
            & (x_min_t < W)
            & (y_max_t >= 0)
            & (y_min_t < H)
            & (np.abs(det) > 0.08)
        )

        px_v, py_v, pd_v = px_v[vis], py_v[vis], pd_v[vis]
        verts_v = verts[vis]
        norms_v = norms[vis]
        bidx_v = bidx[vis]
        stype_v = stype[vis]
        trgb_v = trgb[vis]
        det_v = det[vis]
        x_min_t = np.maximum(0, x_min_t[vis])
        x_max_t = np.minimum(W - 1, x_max_t[vis])
        y_min_t = np.maximum(0, y_min_t[vis])
        y_max_t = np.minimum(H - 1, y_max_t[vis])

        # Canonical horizontal wall tangent t_wall = (-ny, nx) with canonical sign so coplanar triangles share seamless window UV!
        qnx = np.round(norms_v[:, 0] * 20.0) / 20.0
        qny = np.round(norms_v[:, 1] * 20.0) / 20.0
        tw_x = -qny
        tw_y = qnx
        tw_len = np.hypot(tw_x, tw_y)
        valid_tw = tw_len > 1e-3
        tw_x = np.where(valid_tw, tw_x / np.maximum(tw_len, 1e-6), 1.0)
        tw_y = np.where(valid_tw, tw_y / np.maximum(tw_len, 1e-6), 0.0)
        flip_sign = (tw_x < -1e-4) | ((np.abs(tw_x) <= 1e-4) & (tw_y < 0))
        tw_x[flip_sign] *= -1.0
        tw_y[flip_sign] *= -1.0

        u_wall_v = (
            (verts_v[:, :, 0] - bldg_e0[bidx_v][:, None]) * tw_x[:, None]
            + (verts_v[:, :, 1] - bldg_n0[bidx_v][:, None]) * tw_y[:, None]
        )

        inv_det = 1.0 / det_v
        bw_t = x_max_t - x_min_t + 1
        bh_t = y_max_t - y_min_t + 1

        def _apply_wall_windows(
            py_f, px_f, tri_i, u_val, z_val, base_col
        ):
            """Paint story-aligned pixel-art windows onto WallSurface fragments."""
            is_wall = stype_v[tri_i] == 0
            if not is_wall.any():
                return base_col, np.where(stype_v[tri_i] == 1, M_ROOF, M_WALL).astype(np.uint8)

            mat_out = np.where(stype_v[tri_i] == 1, M_ROOF, M_WALL).astype(np.uint8)
            col_out = base_col.copy()

            wi = np.nonzero(is_wall)[0]
            bi = bidx_v[tri_i[wi]]
            can_win = (~bldg_no_win[bi]) & (bldg_h[bi] >= 3.0)
            if not can_win.any():
                return col_out, mat_out

            wi = wi[can_win]
            bi = bi[can_win]
            h_rel = z_val[wi] - bldg_z0[bi]
            u_rel = u_val[wi] + 100.0  # Positive offset

            # Story spacing: 3.15m floor-to-floor; bay spacing: 2.75m
            floor_idx = np.floor(h_rel / 3.15).astype(np.int32)
            in_story_z = h_rel - floor_idx * 3.15
            bay_idx = np.floor(u_rel / 2.75).astype(np.int32)
            in_bay_u = u_rel - bay_idx * 2.75

            is_pane = (
                (h_rel >= 1.1)
                & (z_val[wi] <= (bldg_z0[bi] + bldg_h[bi] - 0.85))
                & (in_story_z >= 0.95)
                & (in_story_z <= 2.25)
                & (in_bay_u >= 0.82)
                & (in_bay_u <= 1.92)
            )
            if not is_pane.any():
                return col_out, mat_out

            p_wi = wi[is_pane]
            p_bi = bi[is_pane]
            p_fl = floor_idx[is_pane]
            p_bay = bay_idx[is_pane]
            p_sz = in_story_z[is_pane]

            if preset.is_night:
                # Deterministic cozy Swiss evening occupancy (~58% warm lit windows!)
                hval = ((p_bi.astype(np.int64) * 73856093) ^ (p_fl.astype(np.int64) * 40503) ^ (p_bay.astype(np.int64) * 12289)) & 0xFF
                lit = hval < 148
                # Warm amber vs soft cream-gold interior lamp glow
                warm_alt = (hval & 3) == 0
                lit_col = np.where(
                    warm_alt[:, None],
                    np.array([255, 226, 148], dtype=np.uint8),
                    np.array([255, 194, 98], dtype=np.uint8),
                )
                dark_pane = np.array([34, 46, 68], dtype=np.uint8)
                col_out[p_wi] = np.where(lit[:, None], lit_col, dark_pane)
                mat_out[p_wi] = np.where(lit, M_WINDOW_LIT, M_WINDOW_DAY)
            else:
                # Crisp pixel-art daytime glass reflection (upper pane sky-glint, lower pane deep slate)
                upper = p_sz > 1.72
                col_out[p_wi] = np.where(
                    upper[:, None],
                    np.array([96, 126, 156], dtype=np.uint8),
                    np.array([52, 68, 88], dtype=np.uint8),
                )
                mat_out[p_wi] = M_WINDOW_DAY
            return col_out, mat_out

        # Roof pitched-tile subtle world-space course texture helper
        def _shade_roof_texture(tri_i, z_val, base_col):
            is_pitched_roof = (stype_v[tri_i] == 1) & (norms_v[tri_i, 2] < 0.94)
            if not is_pitched_roof.any():
                return base_col
            col_out = base_col.copy().astype(np.int16)
            ri = np.nonzero(is_pitched_roof)[0]
            # Every 0.85m vertically along pitched roof, subtle 1px tile course shadow/highlight
            course = ((z_val[ri] * 1.35) % 1.0) < 0.28
            col_out[ri[course]] -= 11
            return np.clip(col_out, 0, 255).astype(np.uint8)

        # Fast path A: Vectorized batch rasterization for compact triangles (<= 16x16 px)
        small_mask = (bw_t <= 16) & (bh_t <= 16)
        small_ids = np.nonzero(small_mask)[0]
        large_ids = np.nonzero(~small_mask)[0]

        gx16, gy16 = np.meshgrid(np.arange(16, dtype=np.float32), np.arange(16, dtype=np.float32))
        CHUNK = 6000
        frag_x, frag_y, frag_d, frag_t, frag_u, frag_z = [], [], [], [], [], []

        for s_start in range(0, len(small_ids), CHUNK):
            idx = small_ids[s_start : s_start + CHUNK]
            bx0 = x_min_t[idx][:, None, None]
            by0 = y_min_t[idx][:, None, None]
            px_grid = bx0 + gx16[None, :, :] + 0.5
            py_grid = by0 + gy16[None, :, :] + 0.5

            in_b = (px_grid <= (x_max_t[idx][:, None, None] + 0.5)) & (
                py_grid <= (y_max_t[idx][:, None, None] + 0.5)
            )

            v0x = px_v[idx, 0][:, None, None]
            v0y = py_v[idx, 0][:, None, None]
            v1x = px_v[idx, 1][:, None, None]
            v1y = py_v[idx, 1][:, None, None]
            v2x = px_v[idx, 2][:, None, None]
            v2y = py_v[idx, 2][:, None, None]
            idet = inv_det[idx][:, None, None]

            w1 = ((px_grid - v0x) * (v2y - v0y) - (v2x - v0x) * (py_grid - v0y)) * idet
            w2 = ((v1x - v0x) * (py_grid - v0y) - (px_grid - v0x) * (v1y - v0y)) * idet
            w0 = 1.0 - w1 - w2

            inside = in_b & (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
            kk, yy, xx = np.nonzero(inside)
            if len(kk) == 0:
                continue

            t_global = idx[kk]
            f_px = (x_min_t[t_global] + xx).astype(np.int32)
            f_py = (y_min_t[t_global] + yy).astype(np.int32)
            bw0, bw1, bw2 = w0[kk, yy, xx], w1[kk, yy, xx], w2[kk, yy, xx]

            f_d = bw0 * pd_v[t_global, 0] + bw1 * pd_v[t_global, 1] + bw2 * pd_v[t_global, 2]
            # Early Z-reject against terrain zbuf!
            keep = f_d < (zbuf[f_py, f_px] + 0.05)
            if keep.any():
                t_g = t_global[keep]
                bw0, bw1, bw2 = bw0[keep], bw1[keep], bw2[keep]
                frag_x.append(f_px[keep])
                frag_y.append(f_py[keep])
                frag_d.append(f_d[keep])
                frag_t.append(t_g)
                frag_u.append(bw0 * u_wall_v[t_g, 0] + bw1 * u_wall_v[t_g, 1] + bw2 * u_wall_v[t_g, 2])
                frag_z.append(bw0 * verts_v[t_g, 0, 2] + bw1 * verts_v[t_g, 1, 2] + bw2 * verts_v[t_g, 2, 2])

        # Path B: Exact bounding-box slice rasterizer for larger roof/wall triangles (> 16 px)
        for ti in large_ids:
            x0_i, x1_i = int(x_min_t[ti]), int(x_max_t[ti])
            y0_i, y1_i = int(y_min_t[ti]), int(y_max_t[ti])
            xs = np.arange(x0_i, x1_i + 1, dtype=np.float32) + 0.5
            ys = np.arange(y0_i, y1_i + 1, dtype=np.float32) + 0.5
            px_g, py_g = np.meshgrid(xs, ys)

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
                n_k = int(keep.sum())
                frag_x.append(f_px[keep])
                frag_y.append(f_py[keep])
                frag_d.append(f_d[keep])
                frag_t.append(np.full(n_k, ti, dtype=np.int32))
                frag_u.append(bw0 * u_wall_v[ti, 0] + bw1 * u_wall_v[ti, 1] + bw2 * u_wall_v[ti, 2])
                frag_z.append(bw0 * verts_v[ti, 0, 2] + bw1 * verts_v[ti, 1, 2] + bw2 * verts_v[ti, 2, 2])

        if frag_x:
            fx = np.concatenate(frag_x)
            fy = np.concatenate(frag_y)
            fd = np.concatenate(frag_d)
            ft = np.concatenate(frag_t)
            fu = np.concatenate(frag_u)
            fz = np.concatenate(frag_z)

            # Sort far-to-near so final write per (fy, fx) is strictly minimum depth!
            order = np.argsort(fd)[::-1]
            fx, fy, fd, ft, fu, fz = fx[order], fy[order], fd[order], ft[order], fu[order], fz[order]
            win = fd < zbuf[fy, fx]
            fx, fy, fd, ft, fu, fz = fx[win], fy[win], fd[win], ft[win], fu[win], fz[win]

            f_col = trgb_v[ft]
            f_col = _shade_roof_texture(ft, fz, f_col)
            f_col, f_mat = _apply_wall_windows(fy, fx, ft, fu, fz, f_col)

            zbuf[fy, fx] = fd
            rgb_buf[fy, fx] = f_col
            mat_buf[fy, fx] = f_mat
            obj_buf[fy, fx] = bidx_v[ft] + 1
            norm_buf[fy, fx] = norms_v[ft]
            shadow_buf[fy, fx] = False  # Self-shading handled via exact 3D triangle normal + AO

    # -------------------------------------------------------------------------
    # STAGE 4: Real 0.5m LiDAR Pixel-Art Trees (Deciduous, Cypress & Copper Beech)
    # -------------------------------------------------------------------------
    te, tn, tz, th, trad, trgb_tree = (
        scene.tree_e,
        scene.tree_n,
        scene.tree_z,
        scene.tree_h,
        scene.tree_rad,
        scene.tree_rgb,
    )
    if crop_box_lv95 is not None:
        e0, n0, e1, n1 = crop_box_lv95
        tm = (te >= e0 - 6) & (te <= e1 + 6) & (tn >= n0 - 6) & (tn <= n1 + 6)
        te, tn, tz, th, trad, trgb_tree = te[tm], tn[tm], tz[tm], th[tm], trad[tm], trgb_tree[tm]

    if len(te) > 0:
        # Classify tree foliage palette from SWISSIMAGE crown RGB + crown geometry
        tr_r = trgb_tree[:, 0].astype(np.float32)
        tr_g = trgb_tree[:, 1].astype(np.float32)
        tr_b = trgb_tree[:, 2].astype(np.float32)
        # Copper beech (Blutbuche) in Navillepark/villas: R > G * 1.04 and dark-rich
        is_copper = (tr_r > tr_g * 1.03) & (tr_r > 55) & (tr_g < 95)
        # Conifer / spruce / cypress: dark evergreen or tall-slender
        is_conifer = (~is_copper) & (((tr_g < 68) & (th > 6.5)) | ((th / np.maximum(trad, 1.0)) > 4.2))

        base_foliage = np.empty((len(te), 3), dtype=np.float32)
        # Blend curated vibrant pixel-art foliage with actual SWISSIMAGE canopy variation
        decid_var = ((te * 3.7 + tn * 5.3).astype(np.int32)) % 3
        decid_pal = np.array(
            [
                [76.0, 146.0, 62.0],   # Lush emerald oak/linden
                [92.0, 158.0, 68.0],   # Sunlit beech/maple
                [64.0, 132.0, 66.0],   # Deep chestnut green
            ],
            dtype=np.float32,
        )
        base_foliage[:] = 0.72 * decid_pal[decid_var] + 0.28 * np.clip(trgb_tree.astype(np.float32) * 1.45, 35, 195)
        base_foliage[is_conifer] = np.array([44.0, 96.0, 64.0])
        base_foliage[is_copper] = np.array([128.0, 64.0, 68.0])

        # Project tree crown centers & trunks
        crown_zc = tz + th * 0.62
        tx_p, ty_p, t_depth = camera.project(te, tn, crown_zc)
        tx_base, ty_base, td_base = camera.project(te, tn, tz + 0.8)

        rad_px = np.clip(np.round(trad / camera.mpp).astype(np.int32), 2, 22)
        h_px = np.clip(np.round((th * 0.72 * camera.z_exag) / camera.mpp).astype(np.int32), 3, 40)

        # Sort trees back-to-front for clean pixel-art cluster layering
        t_order = np.argsort(t_depth)[::-1]
        for idx_t in t_order:
            cx_i = int(round(tx_p[idx_t] + shift_x))
            cy_i = int(round(ty_p[idx_t] + shift_y))
            rp = int(rad_px[idx_t])
            hp = int(h_px[idx_t])
            if cx_i + rp < 0 or cx_i - rp >= W or cy_i + hp < 0 or cy_i - hp >= H:
                continue

            # Draw slender trunk pixel(s) at base
            bx_i = int(round(tx_base[idx_t] + shift_x))
            by_i = int(round(ty_base[idx_t] + shift_y))
            trunk_top = max(cy_i, by_i - max(2, hp // 2))
            if 0 <= bx_i < W:
                y_tr0 = max(0, trunk_top)
                y_tr1 = min(H, by_i + 1)
                if y_tr1 > y_tr0:
                    d_tr = float(td_base[idx_t])
                    m_tr = d_tr < zbuf[y_tr0:y_tr1, bx_i]
                    ys_tr = np.arange(y_tr0, y_tr1)[m_tr]
                    zbuf[ys_tr, bx_i] = d_tr
                    rgb_buf[ys_tr, bx_i] = (92, 68, 50)
                    mat_buf[ys_tr, bx_i] = M_TREE
                    obj_buf[ys_tr, bx_i] = 100000 + int(idx_t)
                    norm_buf[ys_tr, bx_i] = (0.4, -0.4, 0.8)

            # Crown bounding box
            rx = max(2, int(rp * 0.68)) if is_conifer[idx_t] else rp
            ry_up = int(hp * 0.62) if is_conifer[idx_t] else max(2, int(rp * 0.88))
            ry_dn = max(2, int(hp * 0.42)) if is_conifer[idx_t] else max(2, int(rp * 0.78))

            x0_c = max(0, cx_i - rx)
            x1_c = min(W - 1, cx_i + rx)
            y0_c = max(0, cy_i - ry_up)
            y1_c = min(H - 1, cy_i + ry_dn)
            if x1_c < x0_c or y1_c < y0_c:
                continue

            yy, xx = np.mgrid[y0_c : y1_c + 1, x0_c : x1_c + 1]
            dx_n = (xx - cx_i) / max(rx, 1.0)
            dy_n = (yy - cy_i) / max(ry_up if is_conifer[idx_t] else rp * 0.85, 1.0)

            if is_conifer[idx_t]:
                # Tiered conical pixel-art cypress/spruce silhouette!
                t_vert = (yy - (cy_i - ry_up)) / max(ry_up + ry_dn, 1.0)
                tier_w = 0.22 + 0.85 * t_vert + 0.14 * np.sin(t_vert * 14.0)
                mask_c = (np.abs(dx_n) <= tier_w) & (t_vert >= 0.0) & (t_vert <= 1.0)
            else:
                # Multi-puff pixel-art leaf cluster silhouette (not a sterile smooth circle!)
                ang = np.arctan2(dy_n, dx_n)
                puff = 1.0 + 0.16 * np.cos(ang * 5.0 + float(idx_t % 7)) + 0.10 * np.sin(ang * 3.0)
                r2 = dx_n * dx_n + (dy_n * 1.08) ** 2
                mask_c = r2 <= (puff * puff)

            if not mask_c.any():
                continue

            # Spherical/puff 3D normal for crisp pixel-art leaf cluster lighting!
            # Remember screen +X is ENE/NNE, screen -Y is UP (+Z)
            e_right, e_depth, _, _ = camera.basis
            snx = dx_n * e_right[0] - 0.35 * e_depth[0]
            sny = dx_n * e_right[1] - 0.35 * e_depth[1]
            snz = np.clip(0.65 - 0.75 * dy_n, -0.35, 1.0)
            # Pixel-art leaf cluster dither texture inside crown
            leaf_tex = (((xx * 3 + yy * 5 + int(idx_t)) % 7) == 0).astype(np.float32) * 0.18
            snz += leaf_tex
            slen = np.sqrt(snx * snx + sny * sny + snz * snz)

            c_depth = float(t_depth[idx_t]) - (1.0 - (dx_n * dx_n + dy_n * dy_n)) * float(trad[idx_t]) * 0.65
            cur_z = zbuf[y0_c : y1_c + 1, x0_c : x1_c + 1]
            win_c = mask_c & (c_depth < cur_z)
            if not win_c.any():
                continue

            cur_z[win_c] = c_depth[win_c]
            rgb_buf[y0_c : y1_c + 1, x0_c : x1_c + 1][win_c] = np.clip(base_foliage[idx_t], 0, 255).astype(np.uint8)
            mat_buf[y0_c : y1_c + 1, x0_c : x1_c + 1][win_c] = M_TREE
            obj_buf[y0_c : y1_c + 1, x0_c : x1_c + 1][win_c] = 100000 + int(idx_t)
            norm_buf[y0_c : y1_c + 1, x0_c : x1_c + 1, 0][win_c] = (snx / slen)[win_c]
            norm_buf[y0_c : y1_c + 1, x0_c : x1_c + 1, 1][win_c] = (sny / slen)[win_c]
            norm_buf[y0_c : y1_c + 1, x0_c : x1_c + 1, 2][win_c] = (snz / slen)[win_c]
            shadow_buf[y0_c : y1_c + 1, x0_c : x1_c + 1][win_c] = False

    # -------------------------------------------------------------------------
    # STAGE 5: Real Moored Lake Zurich Boats + ZSG Steamer + S-Bahn S8 Train
    # -------------------------------------------------------------------------
    _draw_harbor_boats_and_transit(
        scene, camera, preset, shift_x, shift_y, zbuf, rgb_buf, mat_buf, obj_buf, norm_buf, crop_box_lv95
    )

    # -------------------------------------------------------------------------
    # STAGE 6: Master Pixel-Art Lighting, Night Glow, Bayer Dithering & Sel-Out
    # -------------------------------------------------------------------------
    active_px = mat_buf > M_DROP_SHADOW
    ay, ax = np.nonzero(active_px)

    n_xyz = norm_buf[ay, ax]
    ndotl = np.clip(
        n_xyz[:, 0] * sun_vec[0] + n_xyz[:, 1] * sun_vec[1] + n_xyz[:, 2] * sun_vec[2],
        0.0,
        1.0,
    )
    in_sh = shadow_buf[ay, ax]
    ndotl = np.where(in_sh, ndotl * 0.14, ndotl)

    # Quantize diffuse illumination into 5 crisp pixel-art cel/ramp bands!
    ndotl_stepped = np.round(ndotl * 5.0) / 5.0

    amb = np.array(preset.amb_rgb, dtype=np.float32)
    sun_c = np.array(preset.sun_rgb, dtype=np.float32)
    sky_dome = (0.5 + 0.5 * np.clip(n_xyz[:, 2], -1.0, 1.0))[:, None]

    lit_mult = amb[None, :] * (0.72 + 0.38 * sky_dome) + sun_c[None, :] * ndotl_stepped[:, None] * 0.78

    base_f = rgb_buf[ay, ax].astype(np.float32)
    shaded = base_f * lit_mult

    # Water specular shimmer & cutaway water internal glow
    m_here = mat_buf[ay, ax]
    is_lake = m_here == M_WATER_LAKE
    if is_lake.any() and not preset.is_night:
        # Sunlit specular glints on Zürichsee
        spec_band = ((ax[is_lake] * 7 + ay[is_lake] * 13) % 29 == 0)
        spec_col = np.array([65.0, 58.0, 42.0]) if preset_key == "sunset" else np.array([38.0, 44.0, 46.0])
        li = np.nonzero(is_lake)[0]
        shaded[li[spec_band]] += spec_col

    is_cut_w = m_here == M_CUTAWAY_WATER
    if is_cut_w.any():
        # Translucent inner-scattered glow inside the carved water block
        shaded[is_cut_w] = base_f[is_cut_w] * (0.46 if preset.is_night else 0.92)

    # Emissive windows, train/ship cabins & golden night streetlamps!
    if preset.is_night:
        is_emissive = m_here == M_WINDOW_LIT
        shaded[is_emissive] = base_f[is_emissive]  # Pure warm glowing pixel light!

        # Warm sodium/LED streetlamp pools along Kilchberg's streets & station platforms
        is_road = (m_here == M_ROAD) | (m_here == M_RAIL)
        if is_road.any():
            ri = np.nonzero(is_road)[0]
            # Periodic streetlamp pools along screen space
            lamp_pool = (((ax[ri] // 10) * 17 + (ay[ri] // 8) * 31) % 7) == 0
            shaded[ri[lamp_pool]] += np.array([68.0, 48.0, 22.0])

    # Ordered 4x4 Bayer dithering + Crisp Pixel-Art Stepped Color Quantization
    dither_val = bayer_tiled[ay, ax][:, None] * preset.dither_strength
    # Reduce dither on clean architectural walls/windows so facades stay razor-clean
    is_clean = np.isin(m_here, [M_WALL, M_WINDOW_LIT, M_WINDOW_DAY, M_VEHICLE, M_BOAT])
    dither_val[is_clean] *= 0.28

    step_size = 255.0 / preset.color_levels
    quantized = np.round(np.clip(shaded + dither_val, 0.0, 255.0) / step_size) * step_size
    rgb_buf[ay, ax] = np.clip(quantized, 0, 255).astype(np.uint8)

    # Selective Pixel-Art Outlines (sel-out) & Roof Ridge Highlights!
    _apply_pixel_art_outlines(rgb_buf, zbuf, obj_buf, mat_buf, norm_buf, camera.mpp, preset.is_night)

    # Collect interactive screen-space hit boxes for landmarks & buildings if requested
    hit_data = {}
    if collect_hit_boxes:
        hit_data = _extract_interactive_metadata(scene, camera, shift_x, shift_y, W, H)

    img = Image.fromarray(rgb_buf, mode="RGB")
    if add_frame:
        img = _draw_museum_cartouche(img, preset, camera, len(scene.buildings), len(scene.tree_e), crop_box_lv95)

    return img, hit_data


def _draw_harbor_boats_and_transit(
    scene: SceneData,
    camera: IsometricCamera,
    preset: LightingPreset,
    shift_x: float,
    shift_y: float,
    zbuf: np.ndarray,
    rgb_buf: np.ndarray,
    mat_buf: np.ndarray,
    obj_buf: np.ndarray,
    norm_buf: np.ndarray,
    crop_box_lv95: tuple[float, float, float, float] | None,
) -> None:
    """Render real SWISSIMAGE-detected moored sailboats/motorboats, a ZSG Lake Zurich steamer
    off Kilchberg ZH (See) pier, and an SBB S8 double-decker S-Bahn train near Bahnhof Kilchberg."""
    H, W = zbuf.shape

    def _put_box_3d(ce, cn, z0, z1, length_m, width_m, heading_deg, col_rgb, mat_id, oid):
        ang = math.radians(heading_deg)
        ca, sa = math.cos(ang), math.sin(ang)
        step = max(0.28, camera.mpp * 0.45)
        us = np.arange(-length_m * 0.5, length_m * 0.5 + 0.01, step)
        vs = np.arange(-width_m * 0.5, width_m * 0.5 + 0.01, step)
        zs = np.arange(z0, z1 + 0.01, step)
        ug, vg, zg = np.meshgrid(us, vs, zs, indexing="ij")
        pe = ce + ug.ravel() * ca - vg.ravel() * sa
        pn = cn + ug.ravel() * sa + vg.ravel() * ca
        pz = zg.ravel()
        px, py, pd = camera.project(pe, pn, pz)
        ix = np.round(px + shift_x).astype(np.int32)
        iy = np.round(py + shift_y).astype(np.int32)
        v = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
        if not v.any():
            return
        ix, iy, pd = ix[v], iy[v], pd[v]
        # Simple outward normal estimation
        nx_v = np.where(np.abs(zg.ravel()[v] - z1) < step * 0.7, 0.0, ca * 0.5)
        ny_v = np.where(np.abs(zg.ravel()[v] - z1) < step * 0.7, 0.0, sa * 0.5)
        nz_v = np.where(np.abs(zg.ravel()[v] - z1) < step * 0.7, 1.0, 0.55)

        order = np.argsort(pd)[::-1]
        ix, iy, pd = ix[order], iy[order], pd[order]
        nx_v, ny_v, nz_v = nx_v[order], ny_v[order], nz_v[order]
        win = pd < zbuf[iy, ix]
        zbuf[iy[win], ix[win]] = pd[win]
        rgb_buf[iy[win], ix[win]] = col_rgb
        mat_buf[iy[win], ix[win]] = mat_id
        obj_buf[iy[win], ix[win]] = oid
        norm_buf[iy[win], ix[win], 0] = nx_v[win]
        norm_buf[iy[win], ix[win], 1] = ny_v[win]
        norm_buf[iy[win], ix[win], 2] = nz_v[win]

    # 1. Real moored boats in Bendlikon, Schooren & Mönchhof
    for i, boat in enumerate(scene.boats):
        be, bn = boat["e"], boat["n"]
        if crop_box_lv95 is not None:
            e0, n0, e1, n1 = crop_box_lv95
            if not (e0 - 5 <= be <= e1 + 5 and n0 - 5 <= bn <= n1 + 5):
                continue
        L = min(max(boat["length"], 5.2), 12.5)
        W_b = max(2.0, L * 0.31)
        ang = boat["angle"]
        hull_col = (242, 242, 240) if i % 4 != 0 else (58, 92, 138)
        _put_box_3d(be, bn, LAKE_SURFACE_Z + 0.1, LAKE_SURFACE_Z + 1.25, L, W_b, ang, hull_col, M_BOAT, 300000 + i)
        _put_box_3d(be, bn, LAKE_SURFACE_Z + 1.25, LAKE_SURFACE_Z + 2.0, L * 0.38, W_b * 0.68, ang, (215, 226, 236), M_BOAT, 300000 + i)

        # Slender aluminum sailboat mast
        if boat.get("sail", True):
            zs = np.arange(LAKE_SURFACE_Z + 1.8, LAKE_SURFACE_Z + 1.8 + L * 1.15, max(0.35, camera.mpp * 0.5))
            px, py, pd = camera.project(np.full_like(zs, be), np.full_like(zs, bn), zs)
            ix = np.round(px + shift_x).astype(np.int32)
            iy = np.round(py + shift_y).astype(np.int32)
            vm = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
            ix, iy, pd = ix[vm], iy[vm], pd[vm]
            wm = pd < zbuf[iy, ix]
            zbuf[iy[wm], ix[wm]] = pd[wm]
            rgb_buf[iy[wm], ix[wm]] = (226, 228, 232)
            mat_buf[iy[wm], ix[wm]] = M_BOAT
            obj_buf[iy[wm], ix[wm]] = 300000 + i

    # 2. Iconic ZSG Lake Zurich Passenger Ship approaching Kilchberg ZH (See) Pier (E=2684295, N=1241935)
    ship_e, ship_n, ship_ang = 2684305.0, 1241945.0, 152.0
    if crop_box_lv95 is None or (
        crop_box_lv95[0] - 40 <= ship_e <= crop_box_lv95[2] + 40
        and crop_box_lv95[1] - 40 <= ship_n <= crop_box_lv95[3] + 40
    ):
        # V-shaped white foam wake behind ship
        rad_a = math.radians(ship_ang)
        for dist_w in np.linspace(26.0, 95.0, 75):
            spread = (dist_w - 22.0) * 0.24
            for side in (-1.0, 1.0):
                we = ship_e - dist_w * math.cos(rad_a) - side * spread * math.sin(rad_a)
                wn = ship_n - dist_w * math.sin(rad_a) + side * spread * math.cos(rad_a)
                px, py, pd = camera.project(np.array([we]), np.array([wn]), np.array([LAKE_SURFACE_Z + 0.08]))
                ix, iy = int(round(px[0] + shift_x)), int(round(py[0] + shift_y))
                if 0 <= ix < W and 0 <= iy < H and mat_buf[iy, ix] == M_WATER_LAKE:
                    rgb_buf[iy, ix] = (212, 240, 244)
        # Lower hull + two classic white passenger decks + funnel + Swiss red stern flag!
        _put_box_3d(ship_e, ship_n, LAKE_SURFACE_Z + 0.1, LAKE_SURFACE_Z + 2.3, 48.0, 8.6, ship_ang, (244, 245, 246), M_VEHICLE, 400001)
        cabin_col = (255, 214, 122) if preset.is_night else (232, 236, 240)
        cabin_mat = M_WINDOW_LIT if preset.is_night else M_VEHICLE
        _put_box_3d(ship_e, ship_n, LAKE_SURFACE_Z + 2.3, LAKE_SURFACE_Z + 5.0, 36.0, 7.2, ship_ang, cabin_col, cabin_mat, 400001)
        _put_box_3d(ship_e + 3.0 * math.cos(rad_a), ship_n + 3.0 * math.sin(rad_a), LAKE_SURFACE_Z + 5.0, LAKE_SURFACE_Z + 7.4, 22.0, 5.8, ship_ang, (246, 246, 244), M_VEHICLE, 400001)
        # Yellow-buff classic ZSG funnel
        _put_box_3d(ship_e + 1.0 * math.cos(rad_a), ship_n + 1.0 * math.sin(rad_a), LAKE_SURFACE_Z + 7.4, LAKE_SURFACE_Z + 10.2, 3.2, 2.4, ship_ang, (238, 198, 96), M_VEHICLE, 400001)
        # Crisp Swiss red flag at stern
        _put_box_3d(ship_e - 23.5 * math.cos(rad_a), ship_n - 23.5 * math.sin(rad_a), LAKE_SURFACE_Z + 2.8, LAKE_SURFACE_Z + 5.2, 2.2, 1.2, ship_ang, (218, 42, 42), M_VEHICLE, 400001)

    # 3. Zürich S-Bahn Double-Decker Train gliding into Bahnhof Kilchberg (E=2683873, N=1242040)
    tr_e, tr_n, tr_ang = 2683878.0, 1242025.0, 114.0
    if crop_box_lv95 is None or (
        crop_box_lv95[0] - 40 <= tr_e <= crop_box_lv95[2] + 40
        and crop_box_lv95[1] - 40 <= tr_n <= crop_box_lv95[3] + 40
    ):
        r_tr = int(np.clip((N_MAX - tr_n) / GRID_RES, 0, GRID_H - 1))
        c_tr = int(np.clip((tr_e - E_MIN) / GRID_RES, 0, GRID_W - 1))
        z_rail = float(scene.dem[r_tr, c_tr]) + 0.35
        rad_t = math.radians(tr_ang)
        for car_i in (-1.5, -0.5, 0.5, 1.5):
            ce = tr_e + car_i * 25.5 * math.cos(rad_t)
            cn = tr_n + car_i * 25.5 * math.sin(rad_t)
            r_c = int(np.clip((N_MAX - cn) / GRID_RES, 0, GRID_H - 1))
            c_c = int(np.clip((ce - E_MIN) / GRID_RES, 0, GRID_W - 1))
            zc = float(scene.dem[r_c, c_c]) + 0.35
            if car_i == 1.5:
                # Iconic ZVV Re 450 red/blue locomotive!
                _put_box_3d(ce, cn, zc, zc + 4.3, 18.5, 3.0, tr_ang, (206, 48, 48), M_VEHICLE, 400002)
            else:
                # ZVV Blue & White double-decker coach + yellow doors
                body_c = (255, 220, 132) if preset.is_night else (46, 102, 184)
                _put_box_3d(ce, cn, zc, zc + 3.4, 24.2, 3.0, tr_ang, body_c, M_WINDOW_LIT if preset.is_night else M_VEHICLE, 400002)
                _put_box_3d(ce, cn, zc + 3.4, zc + 4.55, 24.2, 2.85, tr_ang, (238, 240, 244), M_VEHICLE, 400002)


def _apply_pixel_art_outlines(
    rgb_buf: np.ndarray,
    zbuf: np.ndarray,
    obj_buf: np.ndarray,
    mat_buf: np.ndarray,
    norm_buf: np.ndarray,
    mpp: float,
    is_night: bool,
) -> None:
    """Apply classic selective pixel-art outlines (sel-out) on object silhouettes and roof creases."""
    # Silhouette detection: foreground pixel whose neighbor has larger depth (> 1.8m) or background (-1)
    dz_right = zbuf[:, 1:] - zbuf[:, :-1]
    dz_down = zbuf[1:, :] - zbuf[:-1, :]
    diff_obj_r = obj_buf[:, 1:] != obj_buf[:, :-1]
    diff_obj_d = obj_buf[1:, :] != obj_buf[:-1, :]

    edge = np.zeros(zbuf.shape, dtype=np.bool_)
    # Mark silhouette on the FOREGROUND pixel (smaller depth)
    fg_left = diff_obj_r & (dz_right > 2.0) & (obj_buf[:, :-1] > 0)
    fg_right = diff_obj_r & (dz_right < -2.0) & (obj_buf[:, 1:] > 0)
    fg_up = diff_obj_d & (dz_down > 2.0) & (obj_buf[:-1, :] > 0)
    fg_dn = diff_obj_d & (dz_down < -2.0) & (obj_buf[1:, :] > 0)

    edge[:, :-1] |= fg_left
    edge[:, 1:] |= fg_right
    edge[:-1, :] |= fg_up
    edge[1:, :] |= fg_dn

    # Outer edge of the carved diorama block against background/drop-shadow
    island_fg = mat_buf > M_DROP_SHADOW
    island_eroded = ndimage.binary_erosion(island_fg, iterations=1, border_value=0)
    island_border = island_fg & (~island_eroded)

    # Sel-out darkens the pixel's own hue (never harsh flat black!)
    if edge.any():
        ey, ex = np.nonzero(edge)
        factor = 0.56 if not is_night else 0.62
        rgb_buf[ey, ex] = (rgb_buf[ey, ex].astype(np.float32) * factor).astype(np.uint8)

    if island_border.any():
        by, bx = np.nonzero(island_border)
        rgb_buf[by, bx] = (rgb_buf[by, bx].astype(np.float32) * 0.42).astype(np.uint8)

    # Crisp 1px sunlit roof-ridge highlight where two roof planes meet at an upward crease
    if not is_night:
        roof_m = mat_buf == M_ROOF
        ndot_up = (
            norm_buf[:-1, :, 0] * norm_buf[1:, :, 0]
            + norm_buf[:-1, :, 1] * norm_buf[1:, :, 1]
            + norm_buf[:-1, :, 2] * norm_buf[1:, :, 2]
        )
        same_bldg = (obj_buf[:-1, :] == obj_buf[1:, :]) & roof_m[:-1, :] & roof_m[1:, :]
        ridge = same_bldg & (ndot_up < 0.86) & (np.abs(zbuf[:-1, :] - zbuf[1:, :]) < 1.6)
        if ridge.any():
            ry, rx = np.nonzero(ridge)
            rgb_buf[ry, rx] = np.clip(rgb_buf[ry, rx].astype(np.int16) + 28, 0, 255).astype(np.uint8)


def _extract_interactive_metadata(
    scene: SceneData,
    camera: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W: int,
    H: int,
) -> dict:
    """Compute exact normalized screen coordinates (0..1) of all landmarks & buildings for the web app."""
    landmarks_out = []
    for lm in LANDMARKS:
        px, py, _ = camera.project(np.array([lm["e"]]), np.array([lm["n"]]), np.array([lm["z"]]))
        sx = float(px[0] + shift_x)
        sy = float(py[0] + shift_y)
        landmarks_out.append({
            **lm,
            "uv": [round(sx / W, 5), round(sy / H, 5)],
            "px": [round(sx, 1), round(sy, 1)],
        })

    be = np.array([b["e"] for b in scene.buildings], dtype=np.float32)
    bn = np.array([b["n"] for b in scene.buildings], dtype=np.float32)
    bz = np.array([0.5 * (b["z_ground"] + b["z_roof"]) for b in scene.buildings], dtype=np.float32)
    bpx, bpy, _ = camera.project(be, bn, bz)
    bsx = bpx + shift_x
    bsy = bpy + shift_y

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
            "trees_lidar": int(len(scene.tree_e)),
            "moored_boats": len(scene.boats),
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
    """Add a clean, classic pixel-art museum plaque, scale bar, and Swiss cross emblem."""
    draw = ImageDraw.Draw(img)
    W, H = img.size

    lg_px = max(18, W // 145)
    sm_px = max(13, W // 225)
    try:
        font_lg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", lg_px)
        font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", sm_px)
    except Exception:
        font_lg = ImageFont.load_default()
        font_sm = ImageFont.load_default()

    # Crisp double-pixel border frame
    border_outer = (88, 98, 118) if not preset.is_night else (58, 72, 102)
    border_inner = (168, 156, 132) if not preset.is_night else (138, 118, 86)
    draw.rectangle([10, 10, W - 11, H - 11], outline=border_outer, width=2)
    draw.rectangle([16, 16, W - 17, H - 17], outline=border_inner, width=1)

    # Pixel-art Swiss shield at top-left sized to span both text lines cleanly
    sw = lg_px + sm_px + 10
    sx0, sy0 = 36, 30
    draw.rectangle([sx0, sy0, sx0 + sw, sy0 + sw], fill=(214, 40, 40), outline=(245, 242, 235), width=2)
    arm_w = max(4, sw // 4)
    arm_l = int(sw * 0.62)
    cx_s, cy_s = sx0 + sw // 2, sy0 + sw // 2
    draw.rectangle([cx_s - arm_w // 2, cy_s - arm_l // 2, cx_s + arm_w // 2, cy_s + arm_l // 2], fill=(250, 250, 248))
    draw.rectangle([cx_s - arm_l // 2, cy_s - arm_w // 2, cx_s + arm_l // 2, cy_s + arm_w // 2], fill=(250, 250, 248))

    title = "KILCHBERG ZH  —  3D ISOMETRIC PIXEL ART DIORAMA"
    sub = (
        f"EPSG:2056 LV95  |  {preset.name.upper()}  |  {camera.mpp:.2f} m/px  |  "
        f"{n_bldgs:,} LOD2 3D BUILDINGS  ·  {n_trees:,} LIDAR TREES  ·  SWISSIMAGE 10 cm  ·  SWISSALTI3D 0.5 m"
    )
    tx = sx0 + sw + 18
    draw.text((tx, sy0), title, fill=(244, 239, 226), font=font_lg)
    draw.text((tx, sy0 + lg_px + 8), sub, fill=(176, 188, 206), font=font_sm)

    # Scale bar at bottom-right
    bar_m = 100 if crop_box_lv95 is not None else 250
    bar_px = int(round(bar_m / camera.mpp))
    bx1 = W - 42
    bx0 = bx1 - bar_px
    by = H - 40
    draw.rectangle([bx0, by - 6, bx1, by], fill=(238, 232, 218), outline=(32, 38, 48), width=1)
    draw.rectangle([bx0, by - 6, bx0 + bar_px // 2, by], fill=(214, 58, 52))
    lbl = f"{bar_m} m (2:1 Isometric)"
    draw.text((bx0, by - 26), lbl, fill=(214, 220, 230), font=font_sm)

    credit = "DATA: © SWISSTOPO (SWISSALTI3D 2026 · SWISSBUILDINGS3D 3.0 2025 · SWISSSURFACE3D · SWISSIMAGE DOP10 2025 · SWISSBATHY3D)"
    draw.text((36, H - 44), credit, fill=(148, 160, 180), font=font_sm)
    return img
