"""Automated verification checks for all Kilchberg ZH pixel-art renders, tile pyramids, and GIS metadata."""

from __future__ import annotations
import json
import numpy as np
from PIL import Image
from scipy import ndimage

from .config import CROPS_DIR, DOCS_DIR, RENDERS_DIR
from .render_all import CROP_SPECS


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


def _check_zero_floating_sky_pixels(img_path, strict_outer_margin: bool = True) -> int:
    """Verify zero disconnected foreground pixel islands (detached tree crowns, chimneys, cars, goals) float in exterior sky."""
    arr = np.asarray(Image.open(img_path).convert("RGB"), dtype=np.int16)
    H, W, _ = arr.shape
    # Exclude museum cartouche border, top title/compass header (y < 118), and bottom credit/scale band (y > H - 78)
    y_top, y_bot = 118, H - 78
    x_l, x_r = 28, W - 28
    roi = arr[y_top:y_bot, x_l:x_r]
    # Estimate clean per-row sky gradient from outer left/right margin columns
    sky_ref = np.median(np.concatenate([roi[:, :24, :], roi[:, -24:, :]], axis=1), axis=1)
    diff = np.max(np.abs(roi - sky_ref[:, None, :]), axis=2)
    fg = diff > 18
    # 1. Exact exterior-sky disconnected bright cluster check across ALL plates (catches detached tree crowns & floating chimneys!)
    fg_raw = diff > 10
    lbl_raw, n_raw = ndimage.label(fg_raw, structure=np.ones((3, 3), dtype=bool))
    if n_raw > 1:
        cnt_raw = np.bincount(lbl_raw.ravel())
        cnt_raw[0] = 0
        main_raw = int(np.argmax(cnt_raw))
        detached_bright = (lbl_raw > 0) & (lbl_raw != main_raw) & (diff > 24)
        detached_bright[int(0.84 * roi.shape[0]) :, :] = False
        lbl_db, n_db = ndimage.label(detached_bright, structure=np.ones((3, 3), dtype=bool))
        if n_db > 0:
            cnt_db = np.bincount(lbl_db.ravel())
            cnt_db[0] = 0
            big_clusters = [(int(i), int(cnt_db[i])) for i in range(1, len(cnt_db)) if cnt_db[i] >= 20]
            assert len(big_clusters) == 0, (
                f"Detected {len(big_clusters)} detached floating sky cluster(s) (>=20 px, "
                f"sizes={[c for _, c in big_clusters]}) in {img_path.name}"
            )
    if not strict_outer_margin:
        return 0
    # 2. Existing strict outer-sky dilation guard (zero pixels > 16px outside closed main island)
    fg_closed = ndimage.binary_closing(fg, structure=np.ones((7, 7), dtype=bool))
    lbl, n_cc = ndimage.label(fg_closed, structure=np.ones((3, 3), dtype=bool))
    if n_cc <= 1:
        return 0
    counts = np.bincount(lbl.ravel())
    counts[0] = 0
    main_lbl = int(np.argmax(counts))
    main_island = ndimage.binary_fill_holes(lbl == main_lbl)
    # Any foreground pixel floating > 16px outside the main diorama island (excluding bottom drop shadow margin) is a glitch!
    outer_sky = ~ndimage.binary_dilation(main_island, iterations=16)
    outer_sky[int(0.84 * roi.shape[0]) :, :] = False
    float_mask = fg & outer_sky
    lbl_f, n_float = ndimage.label(float_mask, structure=np.ones((3, 3), dtype=bool))
    assert n_float == 0, f"Detected {n_float} floating sky pixel island(s) ({int(float_mask.sum())} px) in {img_path.name}"
    return int(n_float)


def verify_all() -> None:
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
        assert mf["width"] >= 11500 and mf["height"] >= 5200, f"Expected >=11.5k x 5.2k tiled canvas, got {mf}"
        n_tiles = mf["cols"] * mf["rows"]
        existing_tiles = list(tdir.glob("*.webp"))
        assert len(existing_tiles) == n_tiles, f"Expected {n_tiles} tiles in {tdir}, found {len(existing_tiles)}"
        tiles_mb = sum(tp.stat().st_size for tp in existing_tiles) / 1e6

        # F6: Strict <= 256-color SVGA hardware CLUT verification on interior tiles
        for tile_name in ("5_2.webp", "6_3.webp"):
            tp_chk = tdir / tile_name
            if tp_chk.exists():
                t_arr = np.asarray(Image.open(tp_chk).convert("RGB"))
                packed = (t_arr[:, :, 0].astype(np.uint32) << 16) | (t_arr[:, :, 1].astype(np.uint32) << 8) | t_arr[:, :, 2].astype(np.uint32)
                n_uniq = int(len(np.unique(packed)))
                assert n_uniq <= 256, f"SVGA palette exceeded 256 colors ({n_uniq}) in {mode}/{tile_name}"

        # F7/F8/F9: Zero macro-tile seam check along exact 6x3 macro boundaries!
        Wf, Hf = int(mf["width"]), int(mf["height"])
        max_ratio = 0.0
        for k in range(1, 6):
            xs = (Wf * k) // 6
            st = _load_canvas_strip_v(tdir, mf, xs, 220, Hf - 220)
            d_seam = float(np.abs(st[:, 2, :] - st[:, 1, :]).mean())
            d_ctrl = 0.5 * (float(np.abs(st[:, 1, :] - st[:, 0, :]).mean()) + float(np.abs(st[:, 3, :] - st[:, 2, :]).mean()))
            if d_ctrl > 0.5:
                max_ratio = max(max_ratio, d_seam / d_ctrl)
        for k in range(1, 3):
            ys = (Hf * k) // 3
            st = _load_canvas_strip_h(tdir, mf, ys, 220, Wf - 220)
            d_seam = float(np.abs(st[2, :, :] - st[1, :, :]).mean())
            d_ctrl = 0.5 * (float(np.abs(st[1, :, :] - st[0, :, :]).mean()) + float(np.abs(st[3, :, :] - st[2, :, :]).mean()))
            if d_ctrl > 0.5:
                max_ratio = max(max_ratio, d_seam / d_ctrl)
        assert max_ratio < 1.35, f"Macro-tile seam detected in {mode}: max jump ratio = {max_ratio:.3f} (>= 1.35)"

        # F6/F7: Preset-specific color fidelity guards
        if mode == "sunset":
            # Anti-bubblegum-pink check on sunlit bright surfaces (R > 160, interior away from cartouche)
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
            # F6 Night Purkinje hue guard: nocturnal open land/meadows must be moonlit cool slate/emerald (mean G >= mean R, never muddy brown!)
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
            f"{n_tiles} tiles ({tiles_mb:.2f} MB), png={w}x{h} ({p.stat().st_size/1e6:.2f} MB), "
            f"max_seam_ratio={max_ratio:.2f}x"
        )

    # Depth map check (required for live web viewer occlusion)
    depth_p = DOCS_DIR / "assets" / "kilchberg_depth.png"
    assert depth_p.exists(), f"Missing 16-bit depth map {depth_p}"
    d_img = Image.open(depth_p)
    assert mf_day is not None
    exp_dsize = (int(mf_day["width"]) // 2, int(mf_day["height"]) // 2)
    assert d_img.size == exp_dsize, f"Expected depth map {exp_dsize}, got {d_img.size}"
    d_arr = np.asarray(d_img)
    n_occ = int((d_arr[:, :, 2] == 255).sum())
    assert n_occ > 100_000, f"Expected >100k occluder pixels in kilchberg_depth.png, got {n_occ}"
    print(f"[ok] depth map: {d_img.size[0]}x{d_img.size[1]}, {n_occ:,} occluder pixels")

    for _, fname in CROP_SPECS:
        cp = CROPS_DIR / fname
        assert cp.exists(), f"Missing crop {cp}"
        img = Image.open(cp)
        w, h = img.size
        assert w >= 2000 and h >= 1400, f"Unexpected crop size {fname}: {w}x{h}"
        _check_zero_floating_sky_pixels(
            cp,
            strict_outer_margin=(fname in ("02_reformierte_kirche_dorf.png", "03_bendlikon_harbor_pier.png")),
        )
        print(f"[ok] crop {fname}: {w}x{h} px ({cp.stat().st_size/1e6:.2f} MB)")

    meta_p = DOCS_DIR / "data" / "kilchberg_interactive.json"
    assert meta_p.exists(), "Missing interactive metadata JSON"
    meta = json.loads(meta_p.read_text())
    assert len(meta["landmarks"]) == 10, "Expected 10 landmarks"
    assert len(meta["buildings"]) >= 1800, f"Expected >=1800 interactive buildings, got {len(meta['buildings'])}"
    print(f"[ok] interactive metadata: {len(meta['landmarks'])} landmarks, {len(meta['buildings'])} clickable 3D buildings")


if __name__ == "__main__":
    verify_all()
