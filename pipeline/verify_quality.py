"""Automated verification checks for all Kilchberg ZH pixel-art renders, tile pyramids, and GIS metadata."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image

from .config import DOCS_DIR, RENDERS_DIR


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


MAX_TILE_BYTES = 500_000
MAX_DOCS_MB = 300.0
MAX_STIPPLE_ALT_Y = 0.14
MAX_STIPPLE_CHK_FLAT = 5.0


def verify_all(skip_stipple: bool = False) -> None:
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Verify Kilchberg 0.11 m/px diorama quality, tile sizes, seams, and anti-stipple smoothness.")
    ap.add_argument("--skip-stipple", action="store_true", help="Skip anti-stipple check on legacy tiles before full render.")
    args = ap.parse_args()
    verify_all(skip_stipple=args.skip_stipple)
