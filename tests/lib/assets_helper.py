"""Cached static asset, pixel-quality, and geometric helpers (stdlib + numpy + Pillow + ffprobe)."""

from __future__ import annotations

import functools
import json
import math
import struct
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
ASSETS_DIR = DOCS_DIR / "assets"
DATA_DIR = DOCS_DIR / "data"
AUDIO_DIR = ASSETS_DIR / "audio"
TILES_DIR = ASSETS_DIR / "tiles"

PRESETS = ("day", "sunset", "night")

DETAIL_PLATES = (
    "01_lindt_home_of_chocolate.webp",
    "02_reformierte_kirche_dorf.webp",
    "03_bendlikon_harbor_pier.webp",
    "04_bahnhof_kilchberg_weinberg.webp",
    "05_schooren_seebad.webp",
    "06_sanatorium_ridge.webp",
)

AUDIO_FILES = (
    "bells.mp3",
    "birds.mp3",
    "boat.mp3",
    "bus.mp3",
    "crickets.mp3",
    "lake_waves.mp3",
    "town_traffic.mp3",
    "traffic.mp3",
    "train.mp3",
)

REQUIRED_LANDMARK_IDS = (
    "lindt_hoc",
    "reformierte_kirche",
    "bendlikon_pier",
    "bahnhof_stockengut",
    "schooren_seebad",
    "sanatorium_ridge",
    "st_elisabeth",
    "cf_meyer_haus",
    "moenchhof_horn",
    "sulzergut_park",
)

REQUIRED_ROAD_IDS = (
    "seestrasse_sb",
    "seestrasse_nb",
    "dorfstrasse_viaduct_up",
    "dorfstrasse_viaduct_dn",
    "a3_motorway_0",
    "a3_motorway_1",
    "alte_landstrasse_eb",
    "alte_landstrasse_wb",
)

CANVAS_W = 12331
CANVAS_H = 5444
OVERVIEW_W = 6165
OVERVIEW_H = 2722

BADWEG_LV95 = (2684061.0, 1242076.0)
BADWEG_UV = (0.58400, 0.57963)
BAHNHOF_PLATFORM_UV = (0.5617, 0.5006)
LINDT_HOC_ID = 1443
BADWEG_PIER_ID = 4


@functools.lru_cache(maxsize=4)
def load_interactive_json() -> Dict[str, Any]:
    path = DATA_DIR / "kilchberg_interactive.json"
    return json.loads(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=4)
def load_animations_json() -> Dict[str, Any]:
    path = DATA_DIR / "kilchberg_animations.json"
    return json.loads(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=8)
def load_manifest(preset: str) -> Dict[str, Any]:
    path = TILES_DIR / preset / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=4)
def load_overview_rgb(preset: str) -> np.ndarray:
    path = ASSETS_DIR / f"diorama_{preset}.webp"
    with Image.open(path) as im:
        im.load()
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


@functools.lru_cache(maxsize=2)
def load_depth_rgb() -> np.ndarray:
    path = ASSETS_DIR / "kilchberg_depth.png"
    with Image.open(path) as im:
        im.load()
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


@functools.lru_cache(maxsize=8)
def load_plate_rgb(filename: str) -> np.ndarray:
    path = ASSETS_DIR / filename
    with Image.open(path) as im:
        im.load()
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


@functools.lru_cache(maxsize=32)
def load_tile_rgb(preset: str, col: int, row: int) -> np.ndarray:
    path = TILES_DIR / preset / f"{col}_{row}.webp"
    with Image.open(path) as im:
        im.load()
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def webp_encoding_type(path: Path) -> str:
    """Return 'VP8L' (lossless), 'VP8 ' (lossy), or 'UNKNOWN' from WebP RIFF container."""
    data = path.read_bytes()
    if len(data) < 16 or data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
        return "UNKNOWN"
    first_tag = data[12:16].decode("ascii", errors="replace")
    if first_tag in ("VP8L", "VP8 "):
        return first_tag
    if first_tag == "VP8X":
        offset = 12
        while offset + 8 <= len(data):
            tag = data[offset : offset + 4].decode("ascii", errors="replace")
            chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
            if tag in ("VP8L", "VP8 "):
                return tag
            offset += 8 + chunk_size + (chunk_size & 1)
    return first_tag


@functools.lru_cache(maxsize=16)
def ffprobe_audio(filename: str) -> Dict[str, Any]:
    path = AUDIO_DIR / filename
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {filename}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def get_landmark_uv(lm: Dict[str, Any]) -> Tuple[float, float]:
    if "uv" in lm and isinstance(lm["uv"], (list, tuple)) and len(lm["uv"]) >= 2:
        return float(lm["uv"][0]), float(lm["uv"][1])
    return float(lm["u"]), float(lm["v"])


def rec709_luma(rgb: np.ndarray) -> np.ndarray:
    arr = rgb.astype(np.float32)
    return 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]


def entropy_32b(luma_patch: np.ndarray) -> float:
    hist, _ = np.histogram(luma_patch.ravel(), bins=32, range=(0.0, 256.0))
    total = float(hist.sum())
    if total <= 0:
        return 0.0
    p = hist[hist > 0].astype(np.float64) / total
    return float(-(p * np.log2(p)).sum())


def signed_hsv_hue_deg(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute signed HSV hue in degrees in [-180, 180] for RGB arrays in [0, 255]."""
    rf = r.astype(np.float64) / 255.0
    gf = g.astype(np.float64) / 255.0
    bf = b.astype(np.float64) / 255.0
    cmax = np.maximum(np.maximum(rf, gf), bf)
    cmin = np.minimum(np.minimum(rf, gf), bf)
    delta = cmax - cmin
    hue = np.zeros_like(cmax)
    nz = delta > 1e-9
    rmask = nz & (cmax == rf)
    gmask = nz & (cmax == gf) & ~rmask
    bmask = nz & ~rmask & ~gmask
    hue[rmask] = 60.0 * (((gf[rmask] - bf[rmask]) / delta[rmask]) % 6.0)
    hue[gmask] = 60.0 * (((bf[gmask] - rf[gmask]) / delta[gmask]) + 2.0)
    hue[bmask] = 60.0 * (((rf[bmask] - gf[bmask]) / delta[bmask]) + 4.0)
    hue = np.where(hue > 180.0, hue - 360.0, hue)
    return hue


def compute_sky_reference(arr: np.ndarray) -> np.ndarray:
    """Per-row median sky RGB (uint8) from left/right margins [24:44] and [W-44:W-24]."""
    w = arr.shape[1]
    strips = np.concatenate([arr[:, 24:44, :], arr[:, w - 44 : w - 24, :]], axis=1)
    return np.rint(np.median(strips, axis=1)).astype(np.uint8)


def max_channel_abs_diff_u8(arr: np.ndarray, row_ref: np.ndarray) -> np.ndarray:
    """Memory-efficient uint8 max-channel absolute diff against per-row RGB reference."""
    ref = row_ref[:, None, :]
    r0, r1 = arr[..., 0], ref[..., 0]
    diff = np.maximum(r0, r1) - np.minimum(r0, r1)
    g0, g1 = arr[..., 1], ref[..., 1]
    np.maximum(diff, np.maximum(g0, g1) - np.minimum(g0, g1), out=diff)
    b0, b1 = arr[..., 2], ref[..., 2]
    np.maximum(diff, np.maximum(b0, b1) - np.minimum(b0, b1), out=diff)
    return diff


def compute_non_sky_mask(
    arr: np.ndarray,
    tol: int = 18,
    margin_top: int = 90,
    margin_bot: int = 60,
    margin_lr: int = 24,
) -> np.ndarray:
    """Boolean mask of interior non-sky pixels with frame/cartouche margins masked out."""
    row_ref = compute_sky_reference(arr)
    diff = max_channel_abs_diff_u8(arr, row_ref)
    mask = diff > int(tol)
    if margin_top > 0:
        mask[:margin_top, :] = False
    if margin_bot > 0:
        mask[-margin_bot:, :] = False
    if margin_lr > 0:
        mask[:, :margin_lr] = False
        mask[:, -margin_lr:] = False
    return mask


def pool2x_max(mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    h2 = (h // 2) * 2
    w2 = (w // 2) * 2
    return mask[:h2, :w2].reshape(h2 // 2, 2, w2 // 2, 2).any(axis=(1, 3))


def _separable_box_morph(mask: np.ndarray, size: int, is_erode: bool) -> np.ndarray:
    """Fast separable 1D sliding-window box erosion/dilation matching PIL MinFilter/MaxFilter."""
    if size <= 1:
        return mask.copy()
    r = size // 2
    win = 2 * r + 1
    h, w = mask.shape

    # Horizontal pass (edge-replicated padding matches PIL MinFilter/MaxFilter)
    hp = np.pad(mask, ((0, 0), (r, r)), mode="edge")
    cs_h = np.empty((h, w + win), dtype=np.int32)
    cs_h[:, 0] = 0
    np.cumsum(hp, axis=1, dtype=np.int32, out=cs_h[:, 1:])
    h_sum = cs_h[:, win:] - cs_h[:, :-win]
    h_res = (h_sum == win) if is_erode else (h_sum > 0)

    # Vertical pass
    vp = np.pad(h_res, ((r, r), (0, 0)), mode="edge")
    cs_v = np.empty((h + win, w), dtype=np.int32)
    cs_v[0, :] = 0
    np.cumsum(vp, axis=0, dtype=np.int32, out=cs_v[1:, :])
    v_sum = cs_v[win:, :] - cs_v[:-win, :]
    return (v_sum == win) if is_erode else (v_sum > 0)


def dilate_mask_pil(mask: np.ndarray, size: int = 5) -> np.ndarray:
    return _separable_box_morph(mask, size=size, is_erode=False)


def erode_mask_pil(mask: np.ndarray, size: int = 5) -> np.ndarray:
    return _separable_box_morph(mask, size=size, is_erode=True)


def rle_connected_components_4(mask: np.ndarray) -> Tuple[List[Dict[str, Any]], List[Tuple[int, int, int, int]], List[int]]:
    """Pure-Python/numpy RLE 4-connected components (no scipy).

    Returns (components_sorted_by_area_desc, runs[(y, x0, x1, run_idx)], parent_array).
    """
    h, w = mask.shape
    parent: List[int] = []

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    row_runs: List[List[Tuple[int, int, int]]] = []
    all_runs: List[Tuple[int, int, int, int]] = []

    # Fast vectorized edge detection per row
    padded = np.zeros((h, w + 2), dtype=np.int8)
    padded[:, 1:-1] = mask.astype(np.int8)
    diffs = np.diff(padded, axis=1)

    for y in range(h):
        starts = np.flatnonzero(diffs[y] == 1)
        if starts.size == 0:
            row_runs.append([])
            continue
        ends = np.flatnonzero(diffs[y] == -1)
        cur: List[Tuple[int, int, int]] = []
        for s_val, e_val in zip(starts.tolist(), ends.tolist()):
            rid = len(parent)
            parent.append(rid)
            cur.append((s_val, e_val, rid))
            all_runs.append((y, s_val, e_val, rid))
        row_runs.append(cur)

        if y > 0:
            prev = row_runs[y - 1]
            if prev:
                i = 0
                j = 0
                lp = len(prev)
                lc = len(cur)
                while i < lp and j < lc:
                    ps, pe, prid = prev[i]
                    cs, ce, crid = cur[j]
                    if pe <= cs:
                        i += 1
                    elif ce <= ps:
                        j += 1
                    else:
                        union(prid, crid)
                        if pe < ce:
                            i += 1
                        else:
                            j += 1

    stats: Dict[int, List[int]] = {}
    for y, s_val, e_val, rid in all_runs:
        root = find(rid)
        length = e_val - s_val
        entry = stats.get(root)
        if entry is None:
            stats[root] = [length, s_val, y, e_val, y + 1]
        else:
            entry[0] += length
            if s_val < entry[1]:
                entry[1] = s_val
            if y < entry[2]:
                entry[2] = y
            if e_val > entry[3]:
                entry[3] = e_val
            if y + 1 > entry[4]:
                entry[4] = y + 1

    # Flatten parents
    for idx in range(len(parent)):
        parent[idx] = find(idx)

    comps = [
        {
            "root": root,
            "area": vals[0],
            "bbox": (vals[1], vals[2], vals[3], vals[4]),
        }
        for root, vals in stats.items()
    ]
    comps.sort(key=lambda c: c["area"], reverse=True)
    return comps, all_runs, parent


def _attach_raw_areas(
    comps: List[Dict[str, Any]],
    runs: List[Tuple[int, int, int, int]],
    parent: List[int],
    pooled: np.ndarray,
) -> List[Dict[str, Any]]:
    """Compute pre-dilation raw pixel count inside each dilated connected component."""
    h, w = pooled.shape
    row_cs = np.empty((h, w + 1), dtype=np.int32)
    row_cs[:, 0] = 0
    np.cumsum(pooled, axis=1, dtype=np.int32, out=row_cs[:, 1:])

    raw_counts: Dict[int, int] = {}
    for y, x0, x1, rid in runs:
        cnt = int(row_cs[y, x1] - row_cs[y, x0])
        if cnt:
            root = parent[rid]
            raw_counts[root] = raw_counts.get(root, 0) + cnt

    for c in comps:
        c["raw_area"] = raw_counts.get(c["root"], 0)
    return comps


def filter_dilated_components(
    pooled: np.ndarray,
    dilate_size: int = 5,
    min_raw_2x: int = 5,
    min_dilated_2x: int = 45,
) -> List[Dict[str, Any]]:
    """Dilate pooled 2x mask, find 4-connected components, and filter by BOTH raw & dilated areas."""
    dilated = dilate_mask_pil(pooled, size=dilate_size)
    comps, runs, parent = rle_connected_components_4(dilated)
    _attach_raw_areas(comps, runs, parent, pooled)
    return [
        c
        for c in comps
        if c["raw_area"] >= min_raw_2x and c["area"] >= min_dilated_2x
    ]


def find_interior_components(
    arr: np.ndarray,
    tol: int = 18,
    margin_top: int = 90,
    margin_bot: int = 60,
    margin_lr: int = 24,
    min_raw_2x: int = 5,
    min_dilated_2x: int = 45,
) -> List[Dict[str, Any]]:
    """Detect non-sky connected components at 2x pooled + 5x5 dilation with pre-dilation raw area guard."""
    non_sky = compute_non_sky_mask(
        arr,
        tol=tol,
        margin_top=margin_top,
        margin_bot=margin_bot,
        margin_lr=margin_lr,
    )
    pooled = pool2x_max(non_sky)
    return filter_dilated_components(
        pooled,
        dilate_size=5,
        min_raw_2x=min_raw_2x,
        min_dilated_2x=min_dilated_2x,
    )


@functools.lru_cache(maxsize=2)
def get_day_island_and_exterior_masks() -> Dict[str, Any]:
    """Derive canonical island, exterior-sky masks & cached day components from diorama_day.webp.

    Returns dict with:
      - 'island_full': (2722, 6165) bool main diorama island mask
      - 'island_2x': (1361, 3082) bool main island at 2x pooled (~1.0 m/px)
      - 'ext_sky_2x': (1361, 3082) bool exterior sky (connected to image border)
      - 'ext_sky_eroded_full': (2722, 6165) bool exterior sky eroded by ~12 overview px outside island
      - 'day_components': filtered connected components (raw_area >= 5, area >= 45) for T2.FA1.04 reuse
    """
    day = load_overview_rgb("day")
    h, w = day.shape[:2]
    non_sky = compute_non_sky_mask(day, tol=18, margin_top=90, margin_bot=60, margin_lr=24)
    pooled = pool2x_max(non_sky)
    dilated = dilate_mask_pil(pooled, size=5)
    comps, runs, parent = rle_connected_components_4(dilated)
    _attach_raw_areas(comps, runs, parent, pooled)
    day_components = [c for c in comps if c["raw_area"] >= 5 and c["area"] >= 45]
    main_root = comps[0]["root"]

    island_2x = np.zeros(pooled.shape, dtype=bool)
    for y, x0, x1, rid in runs:
        if parent[rid] == main_root:
            island_2x[y, x0:x1] = True

    # Exterior sky at 2x: components of (~island_2x) that touch the border
    not_island = ~island_2x
    sky_comps, sky_runs, sky_parent = rle_connected_components_4(not_island)
    h2, w2 = island_2x.shape
    border_roots = set()
    for c in sky_comps:
        x0, y0, x1, y1 = c["bbox"]
        if x0 == 0 or y0 == 0 or x1 >= w2 or y1 >= h2:
            border_roots.add(c["root"])

    ext_sky_2x = np.zeros_like(island_2x)
    for y, x0, x1, rid in sky_runs:
        if sky_parent[rid] in border_roots:
            ext_sky_2x[y, x0:x1] = True

    # Upsample island_2x to full overview size and intersect with non_sky for crisp island pixels
    island_up = np.asarray(
        Image.fromarray(island_2x.astype(np.uint8) * 255, mode="L").resize((w, h), Image.NEAREST),
        dtype=np.uint8,
    ) > 0
    island_full = island_up & non_sky

    # Eroded exterior sky (~12 overview px = 6 px at 2x -> 13x13 box erosion)
    ext_sky_eroded_2x = erode_mask_pil(ext_sky_2x, size=13)
    ext_sky_eroded_full = np.asarray(
        Image.fromarray(ext_sky_eroded_2x.astype(np.uint8) * 255, mode="L").resize((w, h), Image.NEAREST),
        dtype=np.uint8,
    ) > 0
    # Mask frame/cartouche margins on exterior sky check
    ext_sky_eroded_full[:90, :] = False
    ext_sky_eroded_full[-60:, :] = False
    ext_sky_eroded_full[:, :24] = False
    ext_sky_eroded_full[:, -24:] = False

    return {
        "island_full": island_full,
        "island_2x": island_2x,
        "ext_sky_2x": ext_sky_2x,
        "ext_sky_eroded_full": ext_sky_eroded_full,
        "day_components": day_components,
    }


@functools.lru_cache(maxsize=2)
def get_lake_zurich_mask_2x() -> Dict[str, np.ndarray]:
    """Opaque-box Lake Zurich water mask (2x pooled overview) from diorama_day.webp.

    Finds the largest blue 4-connected component inside the diorama island and
    returns both the raw 2x mask and an eroded (~2 m interior buffer, size=5)
    mask so shoreline boardwalks/piers never false-fail while offshore water
    intrusions are caught cleanly.
    """
    day = load_overview_rgb("day")
    island_full = get_day_island_and_exterior_masks()["island_full"]
    r = day[..., 0].astype(np.int16)
    g = day[..., 1].astype(np.int16)
    b = day[..., 2].astype(np.int16)
    blue = (b > r + 15) & (g > r + 10) & island_full

    h, w = blue.shape
    blue_2x = blue[: (h // 2) * 2, : (w // 2) * 2].reshape(h // 2, 2, w // 2, 2).all(axis=(1, 3))
    comps, runs, parent = rle_connected_components_4(blue_2x)

    lake_2x = np.zeros_like(blue_2x, dtype=np.bool_)
    if comps:
        lake_root = comps[0]["root"]
        for y, x0, x1, rid in runs:
            if parent[rid] == lake_root:
                lake_2x[y, x0:x1] = True

    lake_eroded_2x = erode_mask_pil(lake_2x, size=5)
    return {
        "lake_2x": lake_2x,
        "lake_eroded_2x": lake_eroded_2x,
    }


def count_depth_roof_small_hits(
    pts: List[List[float]],
    b_occ: np.ndarray,
    d16_map: np.ndarray,
    dy_lo: int,
    dy_hi: int,
    max_delta: int = 45,
) -> Tuple[int, int]:
    """Count open-air (occ==0) roof-band centerline samples with small occluder hits.

    A small positive delta (0 < veh_d16 - scene_d16 <= max_delta) directly above
    an open-air rail/road centerline indicates overhead wire/pole occluder pixels
    punching holes across tall vehicle roofs.
    """
    h, w = b_occ.shape
    small_hits = 0
    total = 0
    for p in pts:
        if len(p) < 4:
            continue
        u, v, occ, vd16 = float(p[0]), float(p[1]), int(p[2]), int(round(float(p[3])))
        if occ:
            continue
        x = int(round(u * (w - 1)))
        y = int(round(v * (h - 1)))
        y0 = max(0, y - dy_hi)
        y1 = max(0, y - dy_lo + 1)
        if 0 <= x < w and y0 < y1:
            total += 1
            col_occ = b_occ[y0:y1, x]
            if np.any(col_occ):
                dd = vd16 - d16_map[y0:y1, x][col_occ].astype(np.int32)
                if np.any((dd > 0) & (dd <= max_delta)):
                    small_hits += 1
    return small_hits, total


def distance_to_exterior_sky_m(u: float, v: float) -> float:
    """Euclidean distance in meters from normalized (u, v) to exterior sky (~1.0 m/px accuracy)."""
    masks = get_day_island_and_exterior_masks()
    ext = masks["ext_sky_2x"]
    h2, w2 = ext.shape
    cx = int(round(u * (w2 - 1)))
    cy = int(round(v * (h2 - 1)))
    cx = max(0, min(w2 - 1, cx))
    cy = max(0, min(h2 - 1, cy))
    if ext[cy, cx]:
        return 0.0

    # 1 pixel at 2x pooled overview = 4 full-canvas pixels = 4 * 0.25m = 1.0 m
    for rad in (60, 180, 400, 1200):
        y0 = max(0, cy - rad)
        y1 = min(h2, cy + rad + 1)
        x0 = max(0, cx - rad)
        x1 = min(w2, cx + rad + 1)
        sub = ext[y0:y1, x0:x1]
        ys, xs = np.nonzero(sub)
        if ys.size > 0:
            dy = (ys + y0) - cy
            dx = (xs + x0) - cx
            return float(np.sqrt(np.min(dx * dx + dy * dy)))
    return float("inf")


def pixel_turn_angles_deg(
    pts: List[List[float]],
    width: int = CANVAS_W,
    height: int = CANVAS_H,
) -> Tuple[float, int, int]:
    """Compute consecutive segment turn angles in full pixel space (du*W, dv*H).

    Returns (max_angle_deg, count_gt_45, count_gt_90).
    """
    if len(pts) < 3:
        return 0.0, 0, 0

    coords = np.array([[p[0] * width, p[1] * height] for p in pts], dtype=np.float64)
    vecs = np.diff(coords, axis=0)
    norms = np.hypot(vecs[:, 0], vecs[:, 1])
    # Filter degenerate near-zero segments
    valid = norms > 1e-4
    vecs = vecs[valid]
    norms = norms[valid]
    if len(vecs) < 2:
        return 0.0, 0, 0

    unit = vecs / norms[:, None]
    dots = np.sum(unit[:-1] * unit[1:], axis=1)
    dots = np.clip(dots, -1.0, 1.0)
    angles = np.degrees(np.arccos(dots))
    max_ang = float(np.max(angles))
    gt45 = int(np.sum(angles > 45.0))
    gt90 = int(np.sum(angles > 90.0))
    return max_ang, gt45, gt90


def uv_pixel_distance(uv1: Tuple[float, float], uv2: Tuple[float, float]) -> float:
    return math.hypot((uv1[0] - uv2[0]) * CANVAS_W, (uv1[1] - uv2[1]) * CANVAS_H)
