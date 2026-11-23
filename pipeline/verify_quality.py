"""Automated verification checks for all Kilchberg ZH pixel-art renders, tile pyramids, and GIS metadata."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

from .config import DOCS_DIR, RAW_CACHE_DIR, RENDERS_DIR


def _load_canvas_strip_v(tdir: "Path", mf: dict, x_seam: int, y0: int, y1: int) -> np.ndarray:
    """Load a 4-pixel-wide vertical strip [x_seam-2 : x_seam+2, y0:y1] across 1024px WebP tiles."""
    ts = int(mf["tileSize"])
    out = np.zeros((y1 - y0, 4, 3), dtype=np.float32)
    xs = [x_seam - 2, x_seam - 1, x_seam, x_seam + 1]
    cache: dict[tuple[int, int], np.ndarray] = {}
    for xi, gx in enumerate(xs):
        tc = gx // ts
        lx = gx % ts
        gy_cur = y0
        while gy_cur < y1:
            tr = gy_cur // ts
            ly0 = gy_cur % ts
            gy_end = min(y1, (tr + 1) * ts)
            ly1 = ly0 + (gy_end - gy_cur)
            key = (tc, tr)
            if key not in cache:
                cache[key] = np.asarray(Image.open(tdir / f"{tc}_{tr}.webp"), dtype=np.float32)
            out[gy_cur - y0 : gy_end - y0, xi, :] = cache[key][ly0:ly1, lx, :]
            gy_cur = gy_end
    return out


def _load_canvas_strip_h(tdir: "Path", mf: dict, y_seam: int, x0: int, x1: int) -> np.ndarray:
    """Load a 4-pixel-tall horizontal strip [y_seam-2 : y_seam+2, x0:x1] across 1024px WebP tiles."""
    ts = int(mf["tileSize"])
    out = np.zeros((4, x1 - x0, 3), dtype=np.float32)
    ys = [y_seam - 2, y_seam - 1, y_seam, y_seam + 1]
    cache: dict[tuple[int, int], np.ndarray] = {}
    for yi, gy in enumerate(ys):
        tr = gy // ts
        ly = gy % ts
        gx_cur = x0
        while gx_cur < x1:
            tc = gx_cur // ts
            lx0 = gx_cur % ts
            gx_end = min(x1, (tc + 1) * ts)
            lx1 = lx0 + (gx_end - gx_cur)
            key = (tc, tr)
            if key not in cache:
                cache[key] = np.asarray(Image.open(tdir / f"{tc}_{tr}.webp"), dtype=np.float32)
            out[yi, gx_cur - x0 : gx_end - x0, :] = cache[key][ly, lx0:lx1, :]
            gx_cur = gx_end
    return out


def _measure_anti_stipple(img_path: Path) -> tuple[float, float, int]:
    """Measure high-frequency Bayer/checkerboard stipple energy and interior unique colors.

    Returns (alt_y, chk_flat, n_uniq_interior):
      - alt_y: fraction of interior pixels with vertical alternating-sign luminance oscillation (1.5 < |dy| < 35)
      - chk_flat: mean 2x2 checkerboard response |I00 + I11 - I01 - I10| on non-edge pixels (|dx|,|dy| < 28)
      - n_uniq_interior: unique RGB colors inside the rendered tile
    """
    roi = np.asarray(Image.open(img_path).convert("RGB"))
    packed = (
        (roi[:, :, 0].astype(np.uint32) << 16)
        | (roi[:, :, 1].astype(np.uint32) << 8)
        | roi[:, :, 2].astype(np.uint32)
    )
    n_uniq = int(len(np.unique(packed)))
    roi_f = roi.astype(np.float32)
    lum = 0.299 * roi_f[:, :, 0] + 0.587 * roi_f[:, :, 1] + 0.114 * roi_f[:, :, 2]
    dy = lum[1:, :] - lum[:-1, :]
    alt_y = (
        (dy[:-1, :] * dy[1:, :] < 0.0)
        & (np.abs(dy[:-1, :]) > 1.5)
        & (np.abs(dy[1:, :]) > 1.5)
        & (np.abs(dy[:-1, :]) < 35.0)
        & (np.abs(dy[1:, :]) < 35.0)
    )
    chk = np.abs(lum[:-1, :-1] + lum[1:, 1:] - lum[:-1, 1:] - lum[1:, :-1])
    flat = (np.abs(lum[:-1, 1:] - lum[:-1, :-1]) < 28.0) & (np.abs(lum[1:, :-1] - lum[:-1, :-1]) < 28.0)
    chk_flat = float(chk[flat].mean()) if flat.any() else 0.0
    return float(alt_y.mean()), chk_flat, n_uniq


def check_botanical_diversity(img_rgb: np.ndarray) -> tuple[int, float, int]:
    """Measure botanical foliage color richness and tonal luminance IQR on a day RGB image/tile.

    Foliage pixels are defined as green-dominant pixels (G > R + 6 and G > B + 6).
    Returns (unique_foliage_colors, foliage_lum_iqr, n_foliage_px).
    """
    arr = np.asarray(img_rgb, dtype=np.uint8)
    r16 = arr[:, :, 0].astype(np.int16)
    g16 = arr[:, :, 1].astype(np.int16)
    b16 = arr[:, :, 2].astype(np.int16)
    fol = (g16 > (r16 + 6)) & (g16 > (b16 + 6))
    n_fol = int(fol.sum())
    if n_fol < 100:
        return 0, 0.0, n_fol
    packed_f = (
        (arr[fol, 0].astype(np.uint32) << 16)
        | (arr[fol, 1].astype(np.uint32) << 8)
        | arr[fol, 2].astype(np.uint32)
    )
    n_uniq_fol = int(len(np.unique(packed_f)))
    rf = arr[fol, 0].astype(np.float32)
    gf = arr[fol, 1].astype(np.float32)
    bf = arr[fol, 2].astype(np.float32)
    lum = 0.299 * rf + 0.587 * gf + 0.114 * bf
    iqr = float(np.percentile(lum, 75) - np.percentile(lum, 25))
    return n_uniq_fol, iqr, n_fol


def measure_grid_hole_and_speckle(img_rgb: np.ndarray) -> tuple[float, float, float]:
    """Measure periodic wire-cage/waffle grid-hole energy and point-splat speckle/clump density.

    Hardened v13 M1B Iter2 guard (zero angular blind spots):
      - max_waffle_score: peak 32x32 (stride 16) 2D FFT crossing-wavevector ratio with 3x3 peak energy
        integration in the 3.5..6.5 px (0.5 m @ 0.11 m/px) band, pairing peak1 anywhere in [0, 180) deg
        with peak2 at 45..135 deg separation (eliminates the old [85, 95] deg blind spot).
      - peak_speckle: max of (a) peak 32x32 density of strictly isolated 1px high-contrast speckles and
        (b) Lake Zurich water-context 2D high-frequency clump/hole density (catches 2-4px point-splatted
        moored boats and wire-cage decks over water without false-tripping clean piers/buildings).
      - global_speckle: global fraction of strictly isolated high-contrast 1px speckles.
    """
    arr = np.asarray(img_rgb, dtype=np.float32)
    r_c, g_c, b_c = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    lum = 0.299 * r_c + 0.587 * g_c + 0.114 * b_c
    h, w = lum.shape

    # 1a. Strictly isolated 1px high-contrast speckle detection (clean 1px outlines/lines have >=2 collinear neighbors -> 0.0)
    med3 = ndimage.median_filter(lum, size=3)
    diff_med = np.abs(lum - med3)
    n_agree = np.zeros_like(lum, dtype=np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            shifted = np.roll(np.roll(lum, dy, axis=0), dx, axis=1)
            n_agree += (np.abs(shifted - med3) < 14.0).astype(np.uint8)
    speckle_mask = (diff_med > 28.0) & (n_agree >= 7)
    speckle_mask[:2, :] = False
    speckle_mask[-2:, :] = False
    speckle_mask[:, :2] = False
    speckle_mask[:, -2:] = False
    peak_1px = float(
        ndimage.uniform_filter(speckle_mask.astype(np.float32), size=32, mode="constant").max()
    ) if (h >= 32 and w >= 32) else float(speckle_mask.mean())
    global_speckle = float(speckle_mask.mean())

    # 1b. 2D high-contrast bipolar hole/spike & sign-reversal fields
    med5 = ndimage.median_filter(lum, size=5)
    hi_px = ((lum - med5) > 22.0).astype(np.float32)
    lo_px = ((med5 - lum) > 22.0).astype(np.float32)
    win_u = min(32, h, w)
    d_hi = ndimage.uniform_filter(hi_px, size=win_u, mode="constant")
    d_lo = ndimage.uniform_filter(lo_px, size=win_u, mode="constant")
    bipole_map = np.sqrt(d_hi * d_lo)

    # Water-context 2D clump/speckle detector (catches 2-4px point-splatted moored boats & wire-cage decks over Lake Zurich!)
    # Excludes bright cyan swimming pools (G>155 or B>145) and dark diorama sky borders (G<62)
    is_water = (
        (g_c > (r_c + 12.0))
        & (b_c > (r_c + 12.0))
        & (g_c >= 62.0) & (g_c <= 155.0)
        & (b_c >= 75.0) & (b_c <= 145.0)
        & (r_c <= 85.0)
    )
    peak_wclump = 0.0
    if is_water.any() and h >= 32 and w >= 32:
        w_frac64 = ndimage.uniform_filter(is_water.astype(np.float32), size=min(64, h, w), mode="constant")
        dx1 = lum[:, 1:] - lum[:, :-1]
        dy1 = lum[1:, :] - lum[:-1, :]
        dx2 = lum[:, 2:] - lum[:, :-2]
        dy2 = lum[2:, :] - lum[:-2, :]
        alt_x = np.zeros_like(lum, dtype=np.float32)
        alt_y = np.zeros_like(lum, dtype=np.float32)
        alt_x[:, 1:-1] = (
            (dx1[:, :-1] * dx1[:, 1:] < 0.0) & (np.abs(dx1[:, :-1]) > 18.0) & (np.abs(dx1[:, 1:]) > 18.0)
        ).astype(np.float32)
        alt_y[1:-1, :] = (
            (dy1[:-1, :] * dy1[1:, :] < 0.0) & (np.abs(dy1[:-1, :]) > 18.0) & (np.abs(dy1[1:, :]) > 18.0)
        ).astype(np.float32)
        alt_x[:, 2:-2] = np.maximum(
            alt_x[:, 2:-2],
            ((dx2[:, :-2] * dx2[:, 2:] < 0.0) & (np.abs(dx2[:, :-2]) > 22.0) & (np.abs(dx2[:, 2:]) > 22.0)).astype(np.float32),
        )
        alt_y[2:-2, :] = np.maximum(
            alt_y[2:-2, :],
            ((dy2[:-2, :] * dy2[2:, :] < 0.0) & (np.abs(dy2[:-2, :]) > 22.0) & (np.abs(dy2[2:, :]) > 22.0)).astype(np.float32),
        )
        alt_2d_map = np.sqrt(
            ndimage.uniform_filter(alt_x, size=32, mode="constant")
            * ndimage.uniform_filter(alt_y, size=32, mode="constant")
        )
        # Bipolar grid/boat clutter over water (e.g. real Bendlikon wire-cage & moored boat static)
        w_bip = np.where(w_frac64 >= 0.45, np.minimum(bipole_map, alt_2d_map), 0.0)
        # Unipolar bright/dark point-splat static on open water (e.g. white boat dots on flat teal water)
        d_dev = np.maximum(d_hi, d_lo)
        w_uni = np.where(w_frac64 >= 0.55, np.minimum(d_dev, alt_2d_map), 0.0)
        peak_wclump = float(max(w_bip.max(), w_uni.max()))

    peak_speckle = max(peak_1px, peak_wclump * 0.78)

    # 2. Zero-blind-spot 32x32 stride-16 2D FFT crossing-wavevector waffle score (3x3 peak energy, 3.5..6.5 px band)
    max_waffle = 0.0
    if h >= 32 and w >= 32:
        hann1d = np.hanning(32).astype(np.float32)
        hann2d = np.outer(hann1d, hann1d)
        fy, fx = np.meshgrid(np.arange(-16, 16, dtype=np.float32), np.arange(-16, 16, dtype=np.float32), indexing="ij")
        rad = np.hypot(fx, fy)
        ang = (np.degrees(np.arctan2(fy, fx)) + 180.0) % 180.0
        ac_mask = rad >= 2.0
        half_plane = (fy > 0) | ((fy == 0) & (fx > 0))
        band = half_plane & (rad >= 4.9) & (rad <= 9.2)
        b_ys, b_xs = np.nonzero(band)
        b_angs = ang[b_ys, b_xs]
        w_frac32 = ndimage.uniform_filter(is_water.astype(np.float32), size=32, mode="constant") if is_water.any() else np.zeros((h, w), dtype=np.float32)

        for y0 in range(0, h - 31, 16):
            for x0 in range(0, w - 31, 16):
                bp = float(bipole_map[y0 + 16, x0 + 16])
                dev = float(max(d_hi[y0 + 16, x0 + 16], d_lo[y0 + 16, x0 + 16]))
                wf_c = float(w_frac32[y0 + 16, x0 + 16])
                # Require genuine high-contrast 2D holes/bars (either bipolar >= 0.16, or water-grid bar dev >= 0.20)
                if bp < 0.16 and not (wf_c >= 0.35 and dev >= 0.20):
                    continue
                patch = lum[y0 : y0 + 32, x0 : x0 + 32]
                if float(patch.std()) < 16.0:
                    continue
                p_win = (patch - float(patch.mean())) * hann2d
                F = np.abs(np.fft.fftshift(np.fft.fft2(p_win))) ** 2
                ac_tot = float(F[ac_mask].sum()) + 1e-6
                F3 = ndimage.uniform_filter(F, size=3, mode="constant") * 9.0
                vals = F3[b_ys, b_xs] / ac_tot
                i1 = int(np.argmax(vals))
                p1 = float(vals[i1])
                if p1 < 0.02:
                    continue
                a1 = float(b_angs[i1])
                da = np.abs(b_angs - a1)
                sep = np.minimum(da, 180.0 - da)
                orth = (sep >= 45.0) & (sep <= 135.0)
                if not orth.any():
                    continue
                p2 = float(vals[orth].max())
                strength = max(bp, dev if wf_c >= 0.35 else 0.0)
                score = ((p1 * p2) ** 0.5) * min(1.5, strength / 0.22)
                if score > max_waffle:
                    max_waffle = score

    return float(max_waffle), float(peak_speckle), float(global_speckle)


def check_grid_hole_and_speckle_guard(img_rgb: np.ndarray, label: str = "image") -> tuple[float, float, float]:
    """Assert that an RGB tile/crop is free of wire-cage waffle grid holes and point-splat speckle/clump clouds."""
    max_waffle, peak_speckle, global_speckle = measure_grid_hole_and_speckle(img_rgb)
    assert max_waffle < MAX_WAFFLE_SCORE, (
        f"Wire-cage / waffle grid-hole artifact detected in {label}: "
        f"max_waffle={max_waffle:.4f} (limit <{MAX_WAFFLE_SCORE})"
    )
    assert peak_speckle < MAX_PEAK_SPECKLE, (
        f"Localized point-splat speckle/clump cloud detected in {label}: "
        f"peak_speckle={peak_speckle:.4f} (limit <{MAX_PEAK_SPECKLE})"
    )
    assert global_speckle < MAX_GLOBAL_SPECKLE, (
        f"Excessive global 1px speckle noise detected in {label}: "
        f"global_speckle={global_speckle:.4f} (limit <{MAX_GLOBAL_SPECKLE})"
    )
    return max_waffle, peak_speckle, global_speckle


MAX_TILE_BYTES = 500_000
MAX_DOCS_MB = 300.0
MAX_STIPPLE_ALT_Y = 0.14
MAX_STIPPLE_CHK_FLAT = 5.0
MIN_BOTANICAL_FOLIAGE_COLORS = 10
MIN_BOTANICAL_FOLIAGE_IQR = 22.0
MAX_WAFFLE_SCORE = 0.090
MAX_PEAK_SPECKLE = 0.115
MAX_GLOBAL_SPECKLE = 0.012
MAX_BRIDGE_SEAM_PX = 40
MAX_BRIDGE_SEAM_CC = 18


def measure_parapet_white_seam(roi_rgb: np.ndarray) -> tuple[int, int, int]:
    """Measure jagged near-white inner-parapet seam streaks adjacent to grey bridge stone.

    Returns (seam_px, max_cc, total_near_white):
      - seam_px: count of neutral near-white pixels (lum > 210, sat < 20) within 2px of grey parapet stone
      - max_cc: largest 8-connected component size of seam_px
      - total_near_white: total neutral near-white pixels in the ROI
    """
    f = roi_rgb.astype(np.float32)
    lum = 0.299 * f[:, :, 0] + 0.587 * f[:, :, 1] + 0.114 * f[:, :, 2]
    sat = f.max(axis=2) - f.min(axis=2)
    nw = (lum > 210.0) & (sat < 20.0)
    stone = (lum >= 110.0) & (lum <= 195.0) & (sat < 20.0)
    adj_stone = ndimage.binary_dilation(stone, iterations=2)
    seam_px = nw & adj_stone
    lbl, n = ndimage.label(seam_px, structure=np.ones((3, 3), dtype=np.int32))
    max_cc = int(max(((lbl == i).sum() for i in range(1, n + 1)), default=0))
    return int(seam_px.sum()), max_cc, int(nw.sum())


def measure_road_centerline_barriers(
    tile_rgb: np.ndarray,
    tx: int,
    ty: int,
    tile_size: int,
    master_w: int,
    master_h: int,
    road_paths: dict[str, list],
    path_names: tuple[str, ...] = ("dorfstrasse_viaduct_up", "dorfstrasse_viaduct_dn"),
    idx_window: dict[str, tuple[int, int]] | None = None,
) -> list[tuple[str, int, int, int, float, float, float]]:
    """Detect transverse grey stone barricades / steep cliffs cutting across animated road centerlines.

    Samples 5x5 patches along unobstructed (occ==0) road centerline points falling on tile (tx, ty).
    A transverse grey barricade/cliff produces high luma (>130), high local contrast (std>35),
    and low saturation (<20) right across the asphalt roadway.
    """
    hits: list[tuple[str, int, int, int, float, float, float]] = []
    th, tw = tile_rgb.shape[:2]
    for pname in path_names:
        pts = road_paths.get(pname, [])
        lo, hi = idx_window.get(pname, (0, len(pts))) if idx_window else (0, len(pts))
        for i in range(max(0, lo), min(len(pts), hi)):
            pt = pts[i]
            u, v = float(pt[0]), float(pt[1])
            occ = int(pt[2]) if len(pt) > 2 else 0
            if occ:
                continue
            gx = int(round(u * master_w))
            gy = int(round(v * master_h))
            if (gx // tile_size) != tx or (gy // tile_size) != ty:
                continue
            lx = gx - tx * tile_size
            ly = gy - ty * tile_size
            if lx < 3 or lx >= (tw - 3) or ly < 3 or ly >= (th - 3):
                continue
            patch = tile_rgb[ly - 2 : ly + 3, lx - 2 : lx + 3].astype(np.float32)
            lum = 0.299 * patch[:, :, 0] + 0.587 * patch[:, :, 1] + 0.114 * patch[:, :, 2]
            sat = patch.max(axis=2) - patch.min(axis=2)
            lm, ls, sm = float(lum.mean()), float(lum.std()), float(sat.mean())
            if lm > 130.0 and ls > 35.0 and sm < 20.0:
                hits.append((pname, i, lx, ly, round(lm, 1), round(ls, 1), round(sm, 1)))
    return hits


def check_bridge_junctions_and_parapets(
    day_tdir: Path | None = None,
    anim_path: Path | None = None,
    check_scene_cache: bool = True,
) -> str:
    """10th quality guard (v13.1): Verify zero blocking walls across bridge/road junctions,
    zero jagged white inner-parapet streaks, and zero <20-cell detached bridge fragments."""
    day_tdir = day_tdir or (DOCS_DIR / "assets" / "tiles" / "day")
    anim_path = anim_path or (DOCS_DIR / "data" / "kilchberg_animations.json")
    mf = json.loads((day_tdir / "manifest.json").read_text())
    W, H, ts = int(mf["width"]), int(mf["height"]), int(mf["tileSize"])
    anim = json.loads(anim_path.read_text())
    roads_by_id = {r["id"]: r["pts"] for r in anim.get("roads", [])}

    # 10a: Centerline barrier guard on Dorfstrasse viaduct upper T-junction (tile 12_6, idx 785..805 & 575..595)
    t12_6_p = day_tdir / "12_6.webp"
    assert t12_6_p.exists(), f"Missing bridge junction tile {t12_6_p}"
    t12_6 = np.asarray(Image.open(t12_6_p).convert("RGB"))
    barriers = measure_road_centerline_barriers(
        t12_6,
        tx=12,
        ty=6,
        tile_size=ts,
        master_w=W,
        master_h=H,
        road_paths=roads_by_id,
        path_names=("dorfstrasse_viaduct_up", "dorfstrasse_viaduct_dn"),
        idx_window={"dorfstrasse_viaduct_dn": (785, 805), "dorfstrasse_viaduct_up": (575, 595)},
    )
    assert len(barriers) == 0, (
        f"Transverse blocking wall/cliff detected across Dorfstrasse viaduct T-junction (day/12_6.webp): {barriers}"
    )

    # 10b: Parapet white-seam ribbon guard on Dorfstrasse T-junction ROI (y=390..470, x=690..790)
    roi_12_6 = t12_6[390:470, 690:790]
    seam_px, max_cc, total_nw = measure_parapet_white_seam(roi_12_6)
    assert seam_px < MAX_BRIDGE_SEAM_PX and max_cc < MAX_BRIDGE_SEAM_CC, (
        f"Jagged white inner-parapet seam detected on day/12_6.webp T-junction ROI: "
        f"seam_px={seam_px} (limit <{MAX_BRIDGE_SEAM_PX}), max_cc={max_cc} (limit <{MAX_BRIDGE_SEAM_CC}), nw={total_nw}"
    )

    # 10c: Optional scene-level detached fragment check when scene_kilchberg_05m.npz is available
    scene_note = ""
    scene_npz = RAW_CACHE_DIR / "scene_kilchberg_05m.npz"
    if check_scene_cache and scene_npz.exists():
        from .pixel_shader import SceneData

        sc = SceneData(RAW_CACHE_DIR)
        lbl, ncomp = ndimage.label(sc.bridge_cls > 0, structure=np.ones((3, 3), dtype=np.int32))
        n_small = sum(1 for i in range(1, ncomp + 1) if int((lbl == i).sum()) < 20)
        assert n_small == 0, f"SceneData left {n_small} detached <20-cell bridge fragments (expected 0)"
        scene_note = f", scene_br_comps={ncomp}(small=0)"

    return f"12_6(barriers=0, seam_px={seam_px}, max_cc={max_cc}{scene_note})"


def verify_all(skip_stipple: bool = False, skip_grid_guard: bool = False, skip_bridge_guard: bool = False) -> None:
    mf_day = None
    for mode in ("day", "sunset", "night"):
        p = RENDERS_DIR / f"kilchberg_diorama_{mode}.png"
        assert p.exists(), f"Missing {p}"
        img = Image.open(p)
        w, h = img.size
        assert w >= 5500 and h >= 2500, f"Unexpected dimensions for {p.name}: {w}x{h}"
        arr = np.asarray(img)
        std = float(arr.std())
        min_std = 18.0 if mode == "night" else 28.0
        assert std > min_std, f"Low visual contrast ({std:.1f}) in {p.name}"

        wp = DOCS_DIR / "assets" / f"diorama_{mode}.webp"
        assert wp.exists() and wp.stat().st_size > 100_000, f"Missing/empty web overview {wp}"

        tdir = DOCS_DIR / "assets" / "tiles" / mode
        mf_p = tdir / "manifest.json"
        assert mf_p.exists(), f"Missing tile manifest {mf_p}"
        mf = json.loads(mf_p.read_text())
        if mode == "day":
            mf_day = mf
        assert mf["width"] >= 26000 and mf["height"] >= 11500 and float(mf["mpp"]) <= 0.115, (
            f"Expected >=26k x 11.5k @ <=0.115 m/px tiled canvas, got {mf}"
        )
        n_tiles = mf["cols"] * mf["rows"]
        existing_tiles = list(tdir.glob("*.webp"))
        assert len(existing_tiles) == n_tiles, f"Expected {n_tiles} tiles in {tdir}, found {len(existing_tiles)}"
        max_l2_bytes = max((tp.stat().st_size for tp in existing_tiles), default=0)
        assert max_l2_bytes < MAX_TILE_BYTES, (
            f"Lossless VP8L L2 tile exceeded 500 KB in {mode}: max={max_l2_bytes/1e3:.1f} KB"
        )
        tiles_mb = sum(tp.stat().st_size for tp in existing_tiles) / 1e6

        max_z1_bytes = 0
        if "z1" in mf:
            z1 = mf["z1"]
            z1_dir = tdir / z1.get("path", "z1")
            z1_expected = int(z1["cols"]) * int(z1["rows"])
            z1_existing = list(z1_dir.glob("*.webp")) if z1_dir.exists() else []
            assert len(z1_existing) == z1_expected, (
                f"Expected {z1_expected} z1 tiles in {z1_dir}, found {len(z1_existing)}"
            )
            max_z1_bytes = max((tp.stat().st_size for tp in z1_existing), default=0)
            assert max_z1_bytes < MAX_TILE_BYTES, (
                f"Lossless VP8L z1 tile exceeded 500 KB in {mode}: max={max_z1_bytes/1e3:.1f} KB"
            )
            tiles_mb += sum(tp.stat().st_size for tp in z1_existing) / 1e6

        # F6: Strict <= 256-color SVGA hardware CLUT verification on dynamic interior center tiles
        cx, cy = int(mf["cols"]) // 2, int(mf["rows"]) // 2
        for tile_name in (f"{cx}_{cy}.webp", f"{max(0, cx - 1)}_{cy}.webp"):
            tp_chk = tdir / tile_name
            if tp_chk.exists():
                t_arr = np.asarray(Image.open(tp_chk).convert("RGB"))
                packed = (t_arr[:, :, 0].astype(np.uint32) << 16) | (t_arr[:, :, 1].astype(np.uint32) << 8) | t_arr[:, :, 2].astype(np.uint32)
                n_uniq = int(len(np.unique(packed)))
                assert n_uniq <= 256, f"SVGA palette exceeded 256 colors ({n_uniq}) in {mode}/{tile_name}"

        # v12: Anti-stipple smoothness guard on interior center tile across all 3 presets (day, sunset, night)
        stipple_note = ""
        if not skip_stipple:
            tp_chk_st = tdir / f"{max(0, cx - 2)}_{cy}.webp"
            if not tp_chk_st.exists():
                tp_chk_st = tdir / f"{cx}_{cy}.webp"
            alt_y_t, chk_flat_t, _ = _measure_anti_stipple(tp_chk_st)
            assert alt_y_t < MAX_STIPPLE_ALT_Y and chk_flat_t < MAX_STIPPLE_CHK_FLAT, (
                f"Anti-stipple smoothness failed on {mode}/{tp_chk_st.name}: "
                f"alt_y={alt_y_t:.4f} (limit <{MAX_STIPPLE_ALT_Y}), chk_flat={chk_flat_t:.2f} (limit <{MAX_STIPPLE_CHK_FLAT})"
            )
            stipple_note = f", tile_alt_y={alt_y_t:.4f}, tile_chk={chk_flat_t:.2f}"

        # F7/F8/F9: Zero macro-tile seam check along exact macroCols x macroRows macro boundaries!
        Wf, Hf = int(mf["width"]), int(mf["height"])
        nx_m = int(mf.get("macroCols", 6))
        ny_m = int(mf.get("macroRows", 3))
        y_pad_seam = 440 if Hf >= 9000 else 220
        x_pad_seam = 440 if Wf >= 18000 else 220
        max_ratio = 0.0
        for k in range(1, nx_m):
            xs = (Wf * k) // nx_m
            st = _load_canvas_strip_v(tdir, mf, xs, y_pad_seam, Hf - y_pad_seam)
            d_seam = float(np.abs(st[:, 2, :] - st[:, 1, :]).mean())
            d_ctrl = 0.5 * (float(np.abs(st[:, 1, :] - st[:, 0, :]).mean()) + float(np.abs(st[:, 3, :] - st[:, 2, :]).mean()))
            if d_ctrl > 0.5:
                max_ratio = max(max_ratio, d_seam / d_ctrl)
        for k in range(1, ny_m):
            ys = (Hf * k) // ny_m
            st = _load_canvas_strip_h(tdir, mf, ys, x_pad_seam, Wf - x_pad_seam)
            d_seam = float(np.abs(st[2, :, :] - st[1, :, :]).mean())
            d_ctrl = 0.5 * (float(np.abs(st[1, :, :] - st[0, :, :]).mean()) + float(np.abs(st[3, :, :] - st[2, :, :]).mean()))
            if d_ctrl > 0.5:
                max_ratio = max(max_ratio, d_seam / d_ctrl)
        assert max_ratio < 1.35, f"Macro-tile seam detected in {mode}: max jump ratio = {max_ratio:.3f} (>= 1.35)"

        # F6/F7: Preset-specific color fidelity guards
        if mode == "sunset":
            inner = arr[100:-80, 100:-100].astype(np.float32)
            bright = inner[:, :, 0] > 160.0
            if bright.any():
                mean_g = float(inner[bright, 1].mean())
                mean_b = float(inner[bright, 2].mean())
                assert mean_g > mean_b, f"Sunset pink cast detected: mean G={mean_g:.1f} <= B={mean_b:.1f}"
        elif mode == "night":
            inner = arr[100:-80, 100:-100].astype(np.float32)
            green_exc = inner[:, :, 1] - np.maximum(inner[:, :, 0], inner[:, :, 2])
            p95_ge = float(np.percentile(green_exc, 95))
            assert p95_ge < 18.0, f"Night neon-green vegetation detected: p95(G-max(R,B)) = {p95_ge:.1f}"
            lum_n = 0.299 * inner[:, :, 0] + 0.587 * inner[:, :, 1] + 0.114 * inner[:, :, 2]
            dark_land = (lum_n >= 20.0) & (lum_n <= 62.0) & ((inner[:, :, 0] - inner[:, :, 2]) < 8.0) & (inner[:, :, 2] < 88.0)
            if dark_land.any():
                mean_r_n = float(inner[dark_land, 0].mean())
                mean_g_n = float(inner[dark_land, 1].mean())
                assert mean_g_n >= mean_r_n, (
                    f"Night nocturnal meadows collapsed into muddy brown/mauve: mean G={mean_g_n:.2f} < mean R={mean_r_n:.2f}"
                )
            n_warm = int(((inner[:, :, 0] > 180.0) & (inner[:, :, 1] > 120.0) & (inner[:, :, 2] < 140.0)).sum())
            assert n_warm >= 500, f"Expected >=500 warm emissive pixels in night overview, got {n_warm}"

        print(
            f"[ok] {mode}: master={mf['width']}x{mf['height']} px ({mf['mpp']} m/px), "
            f"{n_tiles} tiles ({tiles_mb:.2f} MB, max_l2={max_l2_bytes/1e3:.1f} KB, max_z1={max_z1_bytes/1e3:.1f} KB), "
            f"png={w}x{h} ({p.stat().st_size/1e6:.2f} MB), max_seam_ratio={max_ratio:.2f}x{stipple_note}"
        )

    # v12: Strict < 300 MB total docs/ directory size guard
    docs_bytes = sum(fp.stat().st_size for fp in DOCS_DIR.rglob("*") if fp.is_file())
    docs_mb = docs_bytes / 1e6
    assert docs_mb < MAX_DOCS_MB, f"docs/ directory exceeded {MAX_DOCS_MB:.0f} MB limit: {docs_mb:.2f} MB"
    print(f"[ok] docs/ size: {docs_mb:.2f} MB (< {MAX_DOCS_MB:.0f} MB limit)")

    # Depth map check (required for live web viewer occlusion)
    depth_p = DOCS_DIR / "assets" / "kilchberg_depth.png"
    assert depth_p.exists(), f"Missing 16-bit depth map {depth_p}"
    d_img = Image.open(depth_p)
    assert mf_day is not None
    exp_dsize = Image.open(DOCS_DIR / "assets" / "diorama_day.webp").size
    assert d_img.size == exp_dsize, f"Expected depth map {exp_dsize}, got {d_img.size}"
    d_arr = np.asarray(d_img)
    n_occ = int((d_arr[:, :, 2] == 255).sum())
    assert n_occ > 100_000, f"Expected >100k occluder pixels in kilchberg_depth.png, got {n_occ}"
    print(f"[ok] depth map: {d_img.size[0]}x{d_img.size[1]}, {n_occ:,} occluder pixels")

    # v12-M1B: Confirm all obsolete separate detail-plate WebPs (01_*.webp..10_*.webp) are removed
    obsolete_plates = sorted(
        p.name for p in (DOCS_DIR / "assets").glob("[0-9][0-9]_*.webp")
    )
    assert len(obsolete_plates) == 0, f"Obsolete detail-plate WebPs still present in docs/assets/: {obsolete_plates}"
    print("[ok] obsolete detail plates: 0 remaining in docs/assets/")

    meta_p = DOCS_DIR / "data" / "kilchberg_interactive.json"
    assert meta_p.exists(), "Missing interactive metadata JSON"
    meta = json.loads(meta_p.read_text())
    assert len(meta["landmarks"]) >= 16, f"Expected >=16 landmarks, got {len(meta['landmarks'])}"
    assert len(meta["buildings"]) >= 1800, f"Expected >=1800 interactive buildings, got {len(meta['buildings'])}"
    print(f"[ok] interactive metadata: {len(meta['landmarks'])} landmarks, {len(meta['buildings'])} clickable 3D buildings")

    # v13.0: Botanical vegetation species diversity check on foliage-rich day L2 tiles
    day_tdir = DOCS_DIR / "assets" / "tiles" / "day"
    bot_candidates = ("18_5.webp", "7_3.webp", "14_2.webp", "6_2.webp", "10_7.webp")
    bot_checked = []
    for tname in bot_candidates:
        tp = day_tdir / tname
        if not tp.exists():
            continue
        t_rgb = np.asarray(Image.open(tp).convert("RGB"))
        n_fol_c, fol_iqr, n_fol_px = check_botanical_diversity(t_rgb)
        if n_fol_px >= 20_000:
            assert n_fol_c >= MIN_BOTANICAL_FOLIAGE_COLORS, (
                f"Low botanical foliage diversity on day/{tname}: {n_fol_c} colors (< {MIN_BOTANICAL_FOLIAGE_COLORS})"
            )
            assert fol_iqr >= MIN_BOTANICAL_FOLIAGE_IQR, (
                f"Flat botanical foliage luminance on day/{tname}: IQR={fol_iqr:.1f} (< {MIN_BOTANICAL_FOLIAGE_IQR})"
            )
            bot_checked.append(f"{tname}({n_fol_c}c,IQR={fol_iqr:.1f})")
    assert len(bot_checked) >= 1, "No foliage-rich day tiles found for botanical diversity check"
    print(f"[ok] botanical diversity: {', '.join(bot_checked)}")

    # v13.0 M1B: Automated wire-cage grid-hole & point-splat speckle guard on systemic harbor/bridge/shoreline day L2 tiles
    if not skip_grid_guard:
        guard_tiles = ("15_6.webp", "11_8.webp", "23_3.webp", "15_5.webp", "8_9.webp")
        guard_checked = []
        for tname in guard_tiles:
            tp = day_tdir / tname
            if not tp.exists():
                continue
            t_rgb = np.asarray(Image.open(tp).convert("RGB"))
            mw, ps, gs = check_grid_hole_and_speckle_guard(t_rgb, label=f"day/{tname}")
            guard_checked.append(f"{tname}(w={mw:.3f},ps={ps:.3f})")
        assert len(guard_checked) >= 1, "No systemic harbor/bridge day tiles found for grid-hole & speckle guard"
        print(f"[ok] grid-hole & speckle guard: {', '.join(guard_checked)}")


    # v13.1: 10th guard — Bridge/road junction continuity, zero blocking walls & zero white inner-parapet seams
    if not skip_bridge_guard:
        br_summary = check_bridge_junctions_and_parapets(day_tdir=day_tdir)
        print(f"[ok] bridge junctions & parapets guard: {br_summary}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Verify Kilchberg 0.11 m/px diorama quality, tile sizes, seams, and anti-stipple smoothness.")
    ap.add_argument("--skip-stipple", action="store_true", help="Skip anti-stipple check on legacy tiles before full render.")
    ap.add_argument("--skip-grid-guard", action="store_true", help="Skip wire-cage grid-hole & speckle guard on pre-M3B legacy tiles.")
    ap.add_argument("--skip-bridge-guard", action="store_true", help="Skip v13.1 bridge junction & parapet guard on pre-v13.1 legacy tiles.")
    args = ap.parse_args()
    verify_all(skip_stipple=args.skip_stipple, skip_grid_guard=args.skip_grid_guard, skip_bridge_guard=args.skip_bridge_guard)
