"""Tier 2 (Python): v13.0 Botanical Vegetation Diversity, Anti-Stipple, Diurnal Fidelity & Asset Budget (T2.V13.V01–T2.V13.V04)."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.lib.assets_helper import (
    DATA_DIR,
    DOCS_DIR,
    PRESETS,
    TILES_DIR,
    count_unique_rgb_colors,
    crop_landmark_meter_box,
    get_landmark_uv,
    load_interactive_json,
    load_manifest,
    load_tile_rgb,
    rec709_luma,
    webp_encoding_type,
)
from tests.lib.report import parse_cli_args_for_module, run_unittest_module, test_meta

MAX_TILE_BYTES = 500_000
MAX_DOCS_BYTES = 300 * 1024 * 1024
MAX_ANIM_JSON_BYTES = 650 * 1024

WOODED_ZONES = (
    "sanatorium_ridge",
    "morfanlage_promenade",
    "reformierte_kirche",
    "stockengut_farm",
)

DIURNAL_VEG_ZONES = (
    "sanatorium_ridge",
    "morfanlage_promenade",
    "reformierte_kirche",
)


def _foliage_mask_day(rgb: np.ndarray) -> np.ndarray:
    """Return boolean mask of day foliage pixels (G > R + 6 and G > B + 6)."""
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    return (g > r + 6) & (g > b + 6)


def _measure_tile_alt_y(rgb: np.ndarray) -> float:
    """Exact vertical-alternation anti-stipple metric matching pipeline/verify_quality.py."""
    roi_f = rgb.astype(np.float32)
    lum = 0.299 * roi_f[:, :, 0] + 0.587 * roi_f[:, :, 1] + 0.114 * roi_f[:, :, 2]
    dy = lum[1:, :] - lum[:-1, :]
    alt_y = (
        (dy[:-1, :] * dy[1:, :] < 0.0)
        & (np.abs(dy[:-1, :]) > 1.5)
        & (np.abs(dy[1:, :]) > 1.5)
        & (np.abs(dy[:-1, :]) < 35.0)
        & (np.abs(dy[1:, :]) < 35.0)
    )
    return float(alt_y.mean())


def _measure_tile_cb_and_edges(rgb: np.ndarray) -> tuple[float, float, float, float]:
    """Exact 2x2 smooth-region checkerboard metric & edge richness matching tier2_v12_visuals.py."""
    luma = rec709_luma(rgb)
    cb = np.abs(luma[:-1, :-1] - luma[:-1, 1:] - luma[1:, :-1] + luma[1:, 1:])
    blk = 0.25 * (luma[:-1, :-1] + luma[:-1, 1:] + luma[1:, :-1] + luma[1:, 1:])
    bgx = np.abs(blk[:, 2:] - blk[:, :-2])
    bgy = np.abs(blk[2:, :] - blk[:-2, :])
    bg = np.maximum(bgx[1:-1, :], bgy[:, 1:-1])
    cb_inner = cb[1:-1, 1:-1]
    smooth = bg < 12.0
    smooth_frac = float(smooth.mean())
    cb_mean = float(cb_inner[smooth].mean()) if smooth.any() else 0.0

    gx = np.abs(luma[:-1, 1:] - luma[:-1, :-1])
    gy = np.abs(luma[1:, :-1] - luma[:-1, :-1])
    e_grad = 0.5 * (float(gx.mean()) + float(gy.mean()))
    s_edge = float((np.maximum(gx, gy) >= 18.0).mean())
    return cb_mean, smooth_frac, e_grad, s_edge


class TestTier2V13Vegetation(unittest.TestCase):
    """v13.0 realistic botanical vegetation diversity, anti-stipple, diurnal fidelity & asset budget."""

    @test_meta("T2.V13.V01", "Botanical species palette diversity across wooded/park/lakeside zones")
    def test_01_botanical_species_palette_diversity(self) -> None:
        foliage_pixels_list: list[np.ndarray] = []
        per_zone_counts: list[str] = []

        for lm_id in WOODED_ZONES:
            crop = crop_landmark_meter_box("day", lm_id, -35.0, -35.0, 35.0, 35.0)
            fmask = _foliage_mask_day(crop)
            fpx = crop[fmask]
            foliage_pixels_list.append(fpx)
            per_zone_counts.append(f"{lm_id}:{fpx.shape[0]}")

        foliage_rgb = np.concatenate(foliage_pixels_list, axis=0)
        self.assertGreaterEqual(
            foliage_rgb.shape[0],
            10_000,
            f"Insufficient foliage pixels across wooded zones ({', '.join(per_zone_counts)})",
        )

        packed = (
            (foliage_rgb[:, 0].astype(np.uint32) << 16)
            | (foliage_rgb[:, 1].astype(np.uint32) << 8)
            | foliage_rgb[:, 2].astype(np.uint32)
        )
        unique_foliage_colors = int(np.unique(packed).size)

        f_f32 = foliage_rgb.astype(np.float32)
        luma = 0.2126 * f_f32[:, 0] + 0.7152 * f_f32[:, 1] + 0.0722 * f_f32[:, 2]
        p25, p75 = np.percentile(luma, [25.0, 75.0])
        luma_iqr = float(p75 - p25)

        rb_diff = f_f32[:, 0] - f_f32[:, 2]
        rb_p10, rb_p90 = np.percentile(rb_diff, [10.0, 90.0])
        rb_spread = float(rb_p90 - rb_p10)

        dark_conifer_frac = float(((luma < 75.0) & (rb_diff < 12.0)).mean())
        bright_decid_frac = float((luma > 125.0).mean())

        diag = (
            f"uniq={unique_foliage_colors}, iqr={luma_iqr:.1f}, rb_spread={rb_spread:.1f}, "
            f"dark_conifer={dark_conifer_frac * 100:.1f}%, bright_decid={bright_decid_frac * 100:.1f}% "
            f"({', '.join(per_zone_counts)})"
        )

        self.assertGreaterEqual(
            unique_foliage_colors,
            10,
            f"Foliage palette lacks multi-species diversity: unique_foliage_colors={unique_foliage_colors} < 10 ({diag})",
        )
        self.assertGreaterEqual(
            luma_iqr,
            22.0,
            f"Foliage luminance IQR too narrow (uniform bubble shading): iqr={luma_iqr:.1f} < 22.0 ({diag})",
        )
        self.assertGreaterEqual(
            rb_spread,
            18.0,
            f"Foliage R-B hue spread too narrow (missing conifer vs sunlit deciduous separation): rb_spread={rb_spread:.1f} < 18.0 ({diag})",
        )
        self.assertGreaterEqual(
            dark_conifer_frac,
            0.02,
            f"Dark cool conifer foliage underrepresented: {dark_conifer_frac * 100:.2f}% < 2.0% ({diag})",
        )
        self.assertGreaterEqual(
            bright_decid_frac,
            0.02,
            f"Bright sunlit deciduous/willow/birch highlights underrepresented: {bright_decid_frac * 100:.2f}% < 2.0% ({diag})",
        )

    @test_meta("T2.V13.V02", "Anti-bubble & anti-stipple compliance on foliage-heavy day L2 tiles")
    def test_02_anti_bubble_and_anti_stipple_compliance(self) -> None:
        m_day = load_manifest("day")
        wf, hf = int(m_day["width"]), int(m_day["height"])
        ts = int(m_day.get("tileSize", 1024))
        cols_n, rows_n = int(m_day["cols"]), int(m_day["rows"])

        lms = load_interactive_json().get("landmarks", [])
        lm_by_id = {lm.get("id"): lm for lm in lms}

        tile_coords: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for lm_id in WOODED_ZONES:
            lm = lm_by_id.get(lm_id)
            self.assertIsNotNone(lm, f"Missing landmark '{lm_id}' in kilchberg_interactive.json")
            u, v = get_landmark_uv(lm)
            c = max(0, min(cols_n - 1, int(u * wf) // ts))
            r = max(0, min(rows_n - 1, int(v * hf) // ts))
            if (c, r) not in seen:
                seen.add((c, r))
                tile_coords.append((c, r))

        self.assertGreaterEqual(len(tile_coords), 3, f"Expected >=3 distinct foliage-heavy tiles, got {tile_coords}")

        cb_means: list[float] = []
        edge_grads: list[float] = []
        strong_edges: list[float] = []
        diags: list[str] = []

        for c, r in tile_coords:
            arr = load_tile_rgb("day", c, r)
            n_uniq = count_unique_rgb_colors(arr)
            self.assertLessEqual(
                n_uniq,
                256,
                f"Foliage-heavy day tile ({c},{r}) exceeds 256-color SVGA CLUT budget: {n_uniq} unique RGBs",
            )

            alt_y = _measure_tile_alt_y(arr)
            cb_mean, smooth_frac, e_grad, s_edge = _measure_tile_cb_and_edges(arr)
            self.assertGreater(
                smooth_frac,
                0.15,
                f"Foliage-heavy day tile ({c},{r}) has too few smooth-region pixels ({smooth_frac:.2f})",
            )
            self.assertLess(
                alt_y,
                0.14,
                f"Foliage-heavy day tile ({c},{r}) failed anti-stipple alt_y={alt_y:.4f} >= 0.14",
            )
            self.assertLess(
                cb_mean,
                8.0,
                f"Foliage-heavy day tile ({c},{r}) peak checkerboard cb_mean={cb_mean:.2f} >= 8.0",
            )

            cb_means.append(cb_mean)
            edge_grads.append(e_grad)
            strong_edges.append(s_edge)
            diags.append(f"({c},{r}):cb={cb_mean:.2f},alt_y={alt_y:.4f},eg={e_grad:.2f},uniq={n_uniq}")

        mean_cb = float(np.mean(cb_means))
        mean_eg = float(np.mean(edge_grads))
        mean_se = float(np.mean(strong_edges))
        diag_str = " | ".join(diags)

        self.assertLess(
            mean_cb,
            6.5,
            f"Foliage-heavy day tiles exceed checkerboard smoothness limit: mean_cb={mean_cb:.2f} >= 6.50 ({diag_str})",
        )
        self.assertGreaterEqual(
            mean_eg,
            4.0,
            f"Foliage-heavy day tiles edge richness too low (blurry/melted silhouettes): mean_eg={mean_eg:.2f} < 4.0 ({diag_str})",
        )
        self.assertGreaterEqual(
            mean_se,
            0.06,
            f"Foliage-heavy day tiles strong-edge fraction too low: {mean_se * 100:.1f}% < 6.0% ({diag_str})",
        )

    @test_meta("T2.V13.V03", "Diurnal vegetation fidelity across sunset (warm, no pink cast) and night (deep nocturnal green)")
    def test_03_diurnal_vegetation_fidelity(self) -> None:
        day_fpx_list: list[np.ndarray] = []
        sunset_fpx_list: list[np.ndarray] = []
        night_fpx_list: list[np.ndarray] = []

        for lm_id in DIURNAL_VEG_ZONES:
            day_crop = crop_landmark_meter_box("day", lm_id, -30.0, -30.0, 30.0, 30.0)
            sunset_crop = crop_landmark_meter_box("sunset", lm_id, -30.0, -30.0, 30.0, 30.0)
            night_crop = crop_landmark_meter_box("night", lm_id, -30.0, -30.0, 30.0, 30.0)
            self.assertEqual(day_crop.shape, sunset_crop.shape, f"Shape mismatch day vs sunset at {lm_id}")
            self.assertEqual(day_crop.shape, night_crop.shape, f"Shape mismatch day vs night at {lm_id}")

            fmask = _foliage_mask_day(day_crop)
            day_fpx_list.append(day_crop[fmask].astype(np.float32))
            sunset_fpx_list.append(sunset_crop[fmask].astype(np.float32))
            night_fpx_list.append(night_crop[fmask].astype(np.float32))

        day_f = np.concatenate(day_fpx_list, axis=0)
        sun_f = np.concatenate(sunset_fpx_list, axis=0)
        nit_f = np.concatenate(night_fpx_list, axis=0)
        self.assertGreaterEqual(day_f.shape[0], 5_000, f"Insufficient foliage pixels ({day_f.shape[0]}) for diurnal check")

        # 1. Sunset: warms relative to day (higher R-B) without pink/magenta cast
        day_rb = float((day_f[:, 0] - day_f[:, 2]).mean())
        sun_rb = float((sun_f[:, 0] - sun_f[:, 2]).mean())
        sun_mean_r = float(sun_f[:, 0].mean())
        sun_mean_g = float(sun_f[:, 1].mean())
        sun_mean_b = float(sun_f[:, 2].mean())
        sun_magenta_p90 = float(np.percentile(np.minimum(sun_f[:, 0], sun_f[:, 2]) - sun_f[:, 1], 90.0))

        self.assertGreater(
            sun_rb,
            day_rb + 5.0,
            f"Sunset foliage did not warm vs day: sunset(R-B)={sun_rb:.2f} <= day(R-B)+5 ({day_rb + 5.0:.2f})",
        )
        self.assertGreater(
            sun_mean_g,
            sun_mean_b,
            f"Sunset foliage exhibits pink/magenta cast: mean G={sun_mean_g:.1f} <= mean B={sun_mean_b:.1f} (R={sun_mean_r:.1f})",
        )
        self.assertLess(
            sun_magenta_p90,
            5.0,
            f"Sunset foliage exhibits magenta excess p90(min(R,B)-G)={sun_magenta_p90:.2f} >= 5.0",
        )

        # 2. Night: deep nocturnal green, no neon green, no muddy brown/black collapse
        nit_green_exc = nit_f[:, 1] - np.maximum(nit_f[:, 0], nit_f[:, 2])
        nit_p95_ge = float(np.percentile(nit_green_exc, 95.0))
        nit_mean_r = float(nit_f[:, 0].mean())
        nit_mean_g = float(nit_f[:, 1].mean())
        nit_luma = 0.2126 * nit_f[:, 0] + 0.7152 * nit_f[:, 1] + 0.0722 * nit_f[:, 2]
        nit_mean_luma = float(nit_luma.mean())
        nit_std_luma = float(nit_luma.std())

        self.assertLess(
            nit_p95_ge,
            18.0,
            f"Night foliage exhibits neon-green excess: p95(G-max(R,B))={nit_p95_ge:.2f} >= 18.0",
        )
        self.assertGreaterEqual(
            nit_mean_g,
            nit_mean_r,
            f"Night foliage collapsed into muddy brown: mean G={nit_mean_g:.2f} < mean R={nit_mean_r:.2f}",
        )
        self.assertTrue(
            12.0 <= nit_mean_luma <= 75.0,
            f"Night foliage mean luminance out of nocturnal range [12, 75]: {nit_mean_luma:.2f}",
        )
        self.assertGreaterEqual(
            nit_std_luma,
            4.0,
            f"Night foliage collapsed to flat black/monotone: std_luma={nit_std_luma:.2f} < 4.0",
        )

    @test_meta("T2.V13.V04", "v13+ asset budget (<500 KB VP8L tiles, <300 MB docs/, <650 KB animations) & ASSET_VER >= 13.0 sync")
    def test_04_v13_asset_budget_and_cache_bust_integrity(self) -> None:
        # 1. Cache-bust version checks in docs/app.js and docs/index.html (accepts 13.0, 14.0, ...)
        app_js_path = DOCS_DIR / "app.js"
        index_html_path = DOCS_DIR / "index.html"
        self.assertTrue(app_js_path.is_file(), "Missing docs/app.js")
        self.assertTrue(index_html_path.is_file(), "Missing docs/index.html")

        app_js = app_js_path.read_text(encoding="utf-8")
        index_html = index_html_path.read_text(encoding="utf-8")

        m_asset = re.search(r"""ASSET_VER\s*=\s*['"](\d+(?:\.\d+)*)['"]""", app_js)
        m_css = re.search(r"""styles\.css\?v=(\d+(?:\.\d+)*)(?=['"&])""", index_html)
        m_app = re.search(r"""app\.js\?v=(\d+(?:\.\d+)*)(?=['"&])""", index_html)

        self.assertIsNotNone(m_asset, "docs/app.js must declare ASSET_VER = '<major>.<minor>'")
        self.assertIsNotNone(m_css, "docs/index.html must reference styles.css?v=<version>")
        self.assertIsNotNone(m_app, "docs/index.html must reference app.js?v=<version>")

        asset_ver = m_asset.group(1)
        css_ver = m_css.group(1)
        app_ver = m_app.group(1)

        self.assertEqual(
            asset_ver,
            css_ver,
            f"Version mismatch between docs/app.js ASSET_VER='{asset_ver}' and docs/index.html styles.css?v={css_ver}",
        )
        self.assertEqual(
            asset_ver,
            app_ver,
            f"Version mismatch between docs/app.js ASSET_VER='{asset_ver}' and docs/index.html app.js?v={app_ver}",
        )
        major_ver = int(asset_ver.split(".")[0])
        self.assertGreaterEqual(
            major_ver,
            13,
            f"Expected ASSET_VER major version >= 13 (e.g. '13.0' or '14.0'), got '{asset_ver}'",
        )

        # 2. All L2 and z1 tiles across day/sunset/night strictly < 500,000 bytes and lossless VP8L
        missing: list[str] = []
        oversized: list[str] = []
        non_vp8l: list[str] = []
        total_checked = 0

        for preset in PRESETS:
            manifest = load_manifest(preset)
            preset_dir = TILES_DIR / preset
            for r in range(int(manifest["rows"])):
                for c in range(int(manifest["cols"])):
                    tp = preset_dir / f"{c}_{r}.webp"
                    total_checked += 1
                    if not tp.is_file():
                        missing.append(f"{preset}/{c}_{r}.webp")
                        continue
                    sz = tp.stat().st_size
                    if sz <= 0 or sz >= MAX_TILE_BYTES:
                        oversized.append(f"{preset}/{c}_{r}.webp ({sz / 1000:.1f} KB)")
                    enc = webp_encoding_type(tp)
                    if enc != "VP8L":
                        non_vp8l.append(f"{preset}/{c}_{r}.webp ({enc})")

            z1_meta = manifest.get("z1")
            self.assertIsInstance(z1_meta, dict, f"{preset}/manifest.json missing z1 metadata")
            z1_dir = preset_dir / str(z1_meta.get("path", "z1"))
            for r in range(int(z1_meta["rows"])):
                for c in range(int(z1_meta["cols"])):
                    tp = z1_dir / f"{c}_{r}.webp"
                    total_checked += 1
                    if not tp.is_file():
                        missing.append(f"{preset}/z1/{c}_{r}.webp")
                        continue
                    sz = tp.stat().st_size
                    if sz <= 0 or sz >= MAX_TILE_BYTES:
                        oversized.append(f"{preset}/z1/{c}_{r}.webp ({sz / 1000:.1f} KB)")
                    enc = webp_encoding_type(tp)
                    if enc != "VP8L":
                        non_vp8l.append(f"{preset}/z1/{c}_{r}.webp ({enc})")

        self.assertGreater(total_checked, 0, "No pyramid tiles checked")
        self.assertEqual(missing, [], f"Missing pyramid tiles ({len(missing)}): {', '.join(missing[:6])}")
        self.assertEqual(non_vp8l, [], f"Non-VP8L tiles ({len(non_vp8l)}): {', '.join(non_vp8l[:6])}")
        self.assertEqual(oversized, [], f"Tiles >= 500,000 bytes ({len(oversized)}): {', '.join(oversized[:6])}")

        # 3. Total docs/ directory size < 300 MB
        docs_bytes = sum(fp.stat().st_size for fp in DOCS_DIR.rglob("*") if fp.is_file())
        self.assertLess(
            docs_bytes,
            MAX_DOCS_BYTES,
            f"docs/ total size {docs_bytes / (1024 * 1024):.2f} MB >= 300.00 MB limit",
        )

        # 4. docs/data/kilchberg_animations.json exists and < 650 KB
        anim_path = DATA_DIR / "kilchberg_animations.json"
        self.assertTrue(anim_path.is_file(), "Missing docs/data/kilchberg_animations.json")
        anim_bytes = anim_path.stat().st_size
        self.assertLess(
            anim_bytes,
            MAX_ANIM_JSON_BYTES,
            f"kilchberg_animations.json size {anim_bytes / 1024:.1f} KB >= 650.0 KB limit",
        )


if __name__ == "__main__":
    result_json, verbose = parse_cli_args_for_module(sys.argv[1:])
    sys.exit(
        run_unittest_module(
            sys.modules[__name__],
            tier=2,
            suite_name="tier2_v13_vegetation",
            result_json_path=result_json,
            verbose=verbose,
        )
    )
