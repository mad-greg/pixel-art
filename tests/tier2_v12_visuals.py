"""Tier 2 (Python): v12 Visual-Polish, Anti-Stipple Smoothness, VP8L Tile-Size & Guardrail Suite (T2.V12.01–T2.V12.05)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.lib.assets_helper import (
    ASSETS_DIR,
    DOCS_DIR,
    LINDT_HOC_ID,
    OBSOLETE_DETAIL_PLATES,
    OBSOLETE_DETAIL_PLATE_STEMS,
    PRESETS,
    RENDERS_CROPS_DIR,
    TILES_DIR,
    count_unique_rgb_colors,
    crop_landmark_meter_box,
    crop_master_rgb,
    entropy_32b,
    load_interactive_json,
    load_manifest,
    load_tile_rgb,
    rec709_luma,
    webp_encoding_type,
)
from tests.lib.report import parse_cli_args_for_module, run_unittest_module, test_meta

MAX_TILE_BYTES = 500 * 1024
MAX_DOCS_BYTES = 300 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 90 * 1024 * 1024


class TestTier2V12VisualPolish(unittest.TestCase):
    """v12 graphics, texture smoothing, lossless VP8L budget, and guardrail verification."""

    @test_meta("T2.V12.01", "Strict <500 KB lossless VP8L guard across all L2 and z1 tiles (day/sunset/night)")
    def test_01_strict_500kb_lossless_vp8l_tiles(self) -> None:
        missing = []
        empty = []
        oversized = []
        non_vp8l = []
        summary_parts = []
        total_checked = 0

        for preset in PRESETS:
            manifest = load_manifest(preset)
            preset_dir = TILES_DIR / preset

            # L2 tiles
            l2_cols, l2_rows = int(manifest["cols"]), int(manifest["rows"])
            l2_max = 0
            for r in range(l2_rows):
                for c in range(l2_cols):
                    tp = preset_dir / f"{c}_{r}.webp"
                    total_checked += 1
                    if not tp.is_file():
                        missing.append(f"{preset}/{c}_{r}.webp")
                        continue
                    sz = tp.stat().st_size
                    if sz <= 0:
                        empty.append(f"{preset}/{c}_{r}.webp")
                        continue
                    if sz > l2_max:
                        l2_max = sz
                    if sz >= MAX_TILE_BYTES:
                        oversized.append(f"{preset}/{c}_{r}.webp ({sz / 1024:.1f} KB)")
                    enc = webp_encoding_type(tp)
                    if enc != "VP8L":
                        non_vp8l.append(f"{preset}/{c}_{r}.webp ({enc})")

            # z1 tiles
            z1_meta = manifest.get("z1")
            self.assertIsInstance(z1_meta, dict, f"{preset}/manifest.json missing z1 pyramid metadata")
            z1_dir = preset_dir / str(z1_meta.get("path", "z1"))
            z1_cols, z1_rows = int(z1_meta["cols"]), int(z1_meta["rows"])
            z1_max = 0
            for r in range(z1_rows):
                for c in range(z1_cols):
                    tp = z1_dir / f"{c}_{r}.webp"
                    total_checked += 1
                    if not tp.is_file():
                        missing.append(f"{preset}/z1/{c}_{r}.webp")
                        continue
                    sz = tp.stat().st_size
                    if sz <= 0:
                        empty.append(f"{preset}/z1/{c}_{r}.webp")
                        continue
                    if sz > z1_max:
                        z1_max = sz
                    if sz >= MAX_TILE_BYTES:
                        oversized.append(f"{preset}/z1/{c}_{r}.webp ({sz / 1024:.1f} KB)")
                    enc = webp_encoding_type(tp)
                    if enc != "VP8L":
                        non_vp8l.append(f"{preset}/z1/{c}_{r}.webp ({enc})")

            summary_parts.append(f"{preset}: L2_max={l2_max / 1024:.1f}KB, z1_max={z1_max / 1024:.1f}KB")

        self.assertGreater(total_checked, 0, "No tiles checked under docs/assets/tiles/")
        self.assertEqual(missing, [], f"Missing pyramid tiles ({len(missing)}): {', '.join(missing[:6])}")
        self.assertEqual(empty, [], f"Empty 0-byte tiles ({len(empty)}): {', '.join(empty[:6])}")
        self.assertEqual(
            non_vp8l,
            [],
            f"Non-lossless (non-VP8L) tiles detected ({len(non_vp8l)}): {', '.join(non_vp8l[:6])}",
        )
        self.assertEqual(
            oversized,
            [],
            f"Tiles >= 500 KB ({len(oversized)}; {'; '.join(summary_parts)}): {', '.join(oversized[:6])}",
        )

    @test_meta("T2.V12.02", "Total docs/ disk footprint strictly <300 MB (zero files >90 MB)")
    def test_02_docs_footprint_under_300mb(self) -> None:
        total_bytes = 0
        file_count = 0
        huge_files = []
        for fp in DOCS_DIR.rglob("*"):
            if fp.is_file():
                sz = fp.stat().st_size
                total_bytes += sz
                file_count += 1
                if sz > MAX_SINGLE_FILE_BYTES:
                    huge_files.append(f"{fp.relative_to(DOCS_DIR)} ({sz / (1024 * 1024):.1f} MB)")

        total_mb = total_bytes / (1024 * 1024)
        self.assertGreater(file_count, 100, f"Unexpectedly few files under docs/ ({file_count})")
        self.assertEqual(
            huge_files,
            [],
            f"Files under docs/ exceed 90 MB GitHub limit: {', '.join(huge_files)}",
        )
        self.assertLess(
            total_bytes,
            MAX_DOCS_BYTES,
            f"Total docs/ disk footprint {total_mb:.2f} MB >= 300.00 MB limit ({file_count} files)",
        )

    @test_meta("T2.V12.03", "Anti-stipple / zero-Bayer-checkerboard smoothness on interior day tiles with crisp edge floor")
    def test_03_anti_stipple_zero_bayer_smoothness(self) -> None:
        m_day = load_manifest("day")
        cols_n, rows_n = int(m_day["cols"]), int(m_day["rows"])
        cx, cy = cols_n // 2, rows_n // 2
        sample_tiles = (
            (max(0, cx - 2), cy),
            (max(0, cx - 1), cy),
            (cx, cy),
            (min(cols_n - 1, cx + 1), cy),
            (max(0, cx - 1), max(0, cy - 1)),
            (cx, max(0, cy - 1)),
        )

        cb_means = []
        cb_ge4_fracs = []
        edge_grads = []
        strong_edge_fracs = []
        per_tile_diag = []

        for c, r in sample_tiles:
            arr = load_tile_rgb("day", c, r)
            luma = rec709_luma(arr)

            # 2x2 alternating-sign checkerboard kernel: |I(y,x) - I(y,x+1) - I(y+1,x) + I(y+1,x+1)|
            cb = np.abs(luma[:-1, :-1] - luma[:-1, 1:] - luma[1:, :-1] + luma[1:, 1:])

            # Low-pass 2x2 block mean gradient isolates smooth/flat regions (excluding sharp architectural edges)
            blk = 0.25 * (luma[:-1, :-1] + luma[:-1, 1:] + luma[1:, :-1] + luma[1:, 1:])
            bgx = np.abs(blk[:, 2:] - blk[:, :-2])
            bgy = np.abs(blk[2:, :] - blk[:-2, :])
            bg = np.maximum(bgx[1:-1, :], bgy[:, 1:-1])
            cb_inner = cb[1:-1, 1:-1]
            smooth = bg < 12.0

            self.assertGreater(
                float(smooth.mean()),
                0.20,
                f"Interior day tile ({c},{r}) has too few smooth-region pixels ({smooth.mean():.2f})",
            )

            cb_mean = float(cb_inner[smooth].mean())
            cb_ge4 = float((cb_inner[smooth] >= 4.0).mean())

            gx = np.abs(luma[:-1, 1:] - luma[:-1, :-1])
            gy = np.abs(luma[1:, :-1] - luma[:-1, :-1])
            e_grad = 0.5 * (float(gx.mean()) + float(gy.mean()))
            s_edge = float((np.maximum(gx, gy) >= 18.0).mean())

            cb_means.append(cb_mean)
            cb_ge4_fracs.append(cb_ge4)
            edge_grads.append(e_grad)
            strong_edge_fracs.append(s_edge)
            per_tile_diag.append(f"({c},{r}):cb={cb_mean:.2f},ge4={cb_ge4 * 100:.1f}%,eg={e_grad:.2f}")

        mean_cb = float(np.mean(cb_means))
        max_cb = float(np.max(cb_means))
        mean_ge4 = float(np.mean(cb_ge4_fracs))
        mean_eg = float(np.mean(edge_grads))
        mean_se = float(np.mean(strong_edge_fracs))
        diag_str = " | ".join(per_tile_diag)

        # Calibrated against v11 baseline (cb=12.3-14.1, ge4=56.7-63.3%) vs tinyrj ref (cb=3.05, ge4=24.0%)
        self.assertLess(
            mean_cb,
            6.5,
            f"Interior day tiles exhibit excessive Bayer/stipple checkerboard energy: mean_cb={mean_cb:.2f} >= 6.50 ({diag_str})",
        )
        self.assertLess(
            max_cb,
            8.0,
            f"Peak interior day tile checkerboard energy too high: max_cb={max_cb:.2f} >= 8.00 ({diag_str})",
        )
        self.assertLess(
            mean_ge4,
            0.35,
            f"Smooth-region stipple pixel fraction (cb>=4) too high: {mean_ge4 * 100:.1f}% >= 35.0% ({diag_str})",
        )

        # Edge-preservation floor: prevents a blurred/washed-out image from falsely passing anti-stipple
        self.assertGreaterEqual(
            mean_eg,
            4.5,
            f"Interior day tiles architectural edge gradient too low (blurred/washed-out): mean_eg={mean_eg:.2f} < 4.50 ({diag_str})",
        )
        self.assertGreaterEqual(
            mean_se,
            0.08,
            f"Interior day tiles strong-edge fraction (>=18 luma) too low: {mean_se * 100:.1f}% < 8.0% ({diag_str})",
        )

    @staticmethod
    def _load_macro_strip_v(
        preset: str,
        mf: dict,
        x_seam: int,
        y0: int,
        y1: int,
        cache: dict[tuple[int, int], np.ndarray],
    ) -> np.ndarray:
        """Load 4-px-wide vertical strip [x_seam-2 : x_seam+2, y0:y1] across enclosing tiles."""
        ts = int(mf.get("tileSize", 1024))
        out = np.zeros((y1 - y0, 4, 3), dtype=np.float32)
        xs = (x_seam - 2, x_seam - 1, x_seam, x_seam + 1)
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
                    cache[key] = load_tile_rgb(preset, tc, tr)
                out[gy_cur - y0 : gy_end - y0, xi, :] = cache[key][ly0:ly1, lx, :].astype(np.float32)
                gy_cur = gy_end
        return out

    @staticmethod
    def _load_macro_strip_h(
        preset: str,
        mf: dict,
        y_seam: int,
        x0: int,
        x1: int,
        cache: dict[tuple[int, int], np.ndarray],
    ) -> np.ndarray:
        """Load 4-px-tall horizontal strip [y_seam-2 : y_seam+2, x0:x1] across enclosing tiles."""
        ts = int(mf.get("tileSize", 1024))
        out = np.zeros((4, x1 - x0, 3), dtype=np.float32)
        ys = (y_seam - 2, y_seam - 1, y_seam, y_seam + 1)
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
                    cache[key] = load_tile_rgb(preset, tc, tr)
                out[yi, gx_cur - x0 : gx_end - x0, :] = cache[key][ly, lx0:lx1, :].astype(np.float32)
                gx_cur = gx_end
        return out

    @test_meta("T2.V12.04", "256-color SVGA budget per interior tile & true macro-tile seam ratio <1.35 (day/sunset/night)")
    def test_04_svga_256_color_budget_and_seam_ratio(self) -> None:
        for preset in PRESETS:
            mf = load_manifest(preset)
            cols_n, rows_n = int(mf["cols"]), int(mf["rows"])
            wf, hf = int(mf["width"]), int(mf["height"])
            nx_m = int(mf.get("macroCols", 12))
            ny_m = int(mf.get("macroRows", 6))
            self.assertGreater(nx_m, 1, f"{preset}/manifest.json macroCols must be > 1 (got {nx_m})")
            self.assertGreater(ny_m, 1, f"{preset}/manifest.json macroRows must be > 1 (got {ny_m})")

            cx, cy = cols_n // 2, rows_n // 2
            c_lo = max(0, cx - 1)
            c_hi = min(cols_n - 1, cx + 1)
            r_lo = max(0, cy - 1)
            interior_tiles = ((c_lo, cy), (cx, cy), (c_hi, cy), (cx, r_lo))

            tile_cache: dict[tuple[int, int], np.ndarray] = {}

            # 1. Strict <= 256 unique RGB colors per interior tile
            for c, r in interior_tiles:
                arr = load_tile_rgb(preset, c, r)
                tile_cache[(c, r)] = arr
                n_uniq = count_unique_rgb_colors(arr)
                self.assertLessEqual(
                    n_uniq,
                    256,
                    f"{preset} interior tile ({c},{r}) exceeds 256-color SVGA budget: {n_uniq} unique RGB colors",
                )

            # 2. True macro-tile render seam ratio < 1.35 along exact (W*k)//macroCols and (H*k)//macroRows
            y_pad = 440 if hf >= 9000 else 220
            x_pad = 440 if wf >= 18000 else 220
            checked_v = 0
            checked_h = 0

            for k in range(1, nx_m):
                xs = (wf * k) // nx_m
                st = self._load_macro_strip_v(preset, mf, xs, y_pad, hf - y_pad, tile_cache)
                d_seam = float(np.abs(st[:, 2, :] - st[:, 1, :]).mean())
                d_ctrl = 0.5 * (
                    float(np.abs(st[:, 1, :] - st[:, 0, :]).mean())
                    + float(np.abs(st[:, 3, :] - st[:, 2, :]).mean())
                )
                if d_ctrl > 0.5:
                    ratio = d_seam / d_ctrl
                    checked_v += 1
                    self.assertLess(
                        ratio,
                        1.35,
                        f"Vertical macro-tile seam ratio >= 1.35 in {preset} at x={xs} (k={k}/{nx_m}): ratio={ratio:.3f}",
                    )

            for k in range(1, ny_m):
                ys = (hf * k) // ny_m
                st = self._load_macro_strip_h(preset, mf, ys, x_pad, wf - x_pad, tile_cache)
                d_seam = float(np.abs(st[2, :, :] - st[1, :, :]).mean())
                d_ctrl = 0.5 * (
                    float(np.abs(st[1, :, :] - st[0, :, :]).mean())
                    + float(np.abs(st[3, :, :] - st[2, :, :]).mean())
                )
                if d_ctrl > 0.5:
                    ratio = d_seam / d_ctrl
                    checked_h += 1
                    self.assertLess(
                        ratio,
                        1.35,
                        f"Horizontal macro-tile seam ratio >= 1.35 in {preset} at y={ys} (k={k}/{ny_m}): ratio={ratio:.3f}",
                    )

            self.assertGreater(
                checked_v,
                0,
                f"No vertical macro-tile seams evaluated in {preset}",
            )
            self.assertGreater(
                checked_h,
                0,
                f"No horizontal macro-tile seams evaluated in {preset}",
            )

    @test_meta("T2.V12.05", "v12 guardrails: zero obsolete plates, 0.11 m/px master, Lindt HoC roof & St. Elisabeth white tower no clock")
    def test_05_v12_guardrails_plates_lindt_st_elisabeth(self) -> None:
        # 1. Zero obsolete separate detail plates remain in docs/assets/ or renders/crops/, and master is <= 0.115 m/px
        leftover_docs = sorted(
            {
                p.name
                for p in list(ASSETS_DIR.glob("0[1-9]_*.webp")) + list(ASSETS_DIR.glob("10_*.webp"))
                if p.is_file()
            }
            | {fname for fname in OBSOLETE_DETAIL_PLATES if (ASSETS_DIR / fname).is_file()}
        )
        self.assertEqual(
            leftover_docs,
            [],
            f"Obsolete separate detail plates still exist in docs/assets/: {', '.join(leftover_docs)}",
        )

        leftover_crops: list[str] = []
        if RENDERS_CROPS_DIR.is_dir():
            leftover_crops = sorted(
                {
                    p.name
                    for p in list(RENDERS_CROPS_DIR.glob("0[1-9]_*.png")) + list(RENDERS_CROPS_DIR.glob("10_*.png"))
                    if p.is_file()
                }
                | {f"{stem}.png" for stem in OBSOLETE_DETAIL_PLATE_STEMS if (RENDERS_CROPS_DIR / f"{stem}.png").is_file()}
            )
        self.assertEqual(
            leftover_crops,
            [],
            f"Obsolete detail plate PNGs still exist in renders/crops/: {', '.join(leftover_crops)}",
        )

        m_day = load_manifest("day")
        cw, ch = int(m_day["width"]), int(m_day["height"])
        mpp = float(m_day.get("mpp", 999.0))
        self.assertLessEqual(mpp, 0.115, f"day manifest mpp={mpp} > 0.115 (0.11 m/px master required)")

        # 2. Lindt Home of Chocolate authentic DOP10 roof preserved directly on master L2 tiles (multi-tile stitch)
        inter = load_interactive_json()
        lindt = next((b for b in inter.get("buildings", []) if b.get("id") == LINDT_HOC_ID), None)
        self.assertIsNotNone(lindt, f"Lindt HoC id={LINDT_HOC_ID} missing from kilchberg_interactive.json")
        rad = max(16, int(round(32 * (0.25 / mpp))))
        px = float(lindt["u"]) * cw
        py = float(lindt["v"]) * ch
        t_patch = crop_master_rgb("day", px - rad, py - rad, px + rad, py + rad)
        t_luma = rec709_luma(t_patch)
        self.assertGreaterEqual(
            float(np.std(t_luma)),
            18.0,
            f"Lindt HoC master roof std_luma={float(np.std(t_luma)):.2f} < 18.0",
        )
        self.assertGreaterEqual(
            entropy_32b(t_luma),
            1.8,
            f"Lindt HoC master roof entropy={entropy_32b(t_luma):.2f} < 1.8",
        )
        self.assertGreaterEqual(
            count_unique_rgb_colors(t_patch),
            12,
            "Lindt HoC master roof unique colors < 12",
        )

        rad_wide = max(32, int(round(16.0 / mpp)))
        w_patch = crop_master_rgb("day", px - rad_wide, py - rad_wide, px + rad_wide, py + rad_wide)
        w_luma = rec709_luma(w_patch)
        self.assertGreaterEqual(
            float(np.std(w_luma)),
            22.0,
            f"Lindt HoC wide master patch std_luma={float(np.std(w_luma)):.2f} < 22.0 (authentic roof lost)",
        )
        self.assertGreaterEqual(
            entropy_32b(w_luma),
            2.5,
            f"Lindt HoC wide master patch entropy={entropy_32b(w_luma):.2f} < 2.5 (authentic roof flattened)",
        )

        # 3. St. Elisabeth white-concrete bell tower with NO clock preserved directly on day master tiles
        shaft = crop_landmark_meter_box("day", "st_elisabeth", 13.83, -19.02, 17.13, -5.73).astype(np.float32)
        slum = shaft.mean(axis=2)
        concrete_mask = (~(shaft[..., 1] > shaft[..., 0] + 15.0)) & (slum >= 100.0)
        self.assertGreaterEqual(
            int(concrete_mask.sum()),
            100,
            f"St. Elisabeth shaft ROI has insufficient exposed concrete pixels ({int(concrete_mask.sum())})",
        )
        conc_lum = slum[concrete_mask]
        p90_lum = float(np.percentile(conc_lum, 90))
        bright_frac = float((conc_lum >= 168.0).mean())
        self.assertGreaterEqual(
            p90_lum,
            172.0,
            f"St. Elisabeth tower concrete p90_lum={p90_lum:.1f} < 172.0 (expected bright white concrete)",
        )
        self.assertGreaterEqual(
            bright_frac,
            0.10,
            f"St. Elisabeth tower bright concrete fraction={bright_frac:.3f} < 0.10",
        )
        bright_px = shaft[concrete_mask & (slum >= 160.0)]
        rb_diff = float(bright_px[:, 0].mean() - bright_px[:, 2].mean())
        self.assertLessEqual(
            rb_diff,
            10.0,
            f"St. Elisabeth tower concrete warm-beige chroma mean(R)-mean(B)={rb_diff:.1f} > 10.0",
        )

        crown = crop_landmark_meter_box("day", "st_elisabeth", 14.59, -21.95, 16.37, -20.19).astype(np.float32)
        very_dark = crown.mean(axis=2) < 55.0
        self.assertLessEqual(
            int(very_dark.sum()),
            4,
            f"Dark clock/slot detected on St. Elisabeth upper tower crown ({int(very_dark.sum())} dark px)",
        )
        self.assertLess(
            float(very_dark.mean()),
            0.015,
            f"Dark clock/slot fraction on St. Elisabeth upper tower crown {float(very_dark.mean()) * 100:.1f}% >= 1.5%",
        )

        tower_full = crop_landmark_meter_box("day", "st_elisabeth", 13.83, -21.95, 17.13, -5.73).astype(np.float32)
        gold_ring = (
            (tower_full[..., 0] > 130.0)
            & (tower_full[..., 1] > 100.0)
            & (tower_full[..., 2] < 80.0)
            & ((tower_full[..., 0] - tower_full[..., 2]) > 55.0)
        )
        self.assertLessEqual(
            int(gold_ring.sum()),
            2,
            f"Gold clock ring/hands detected on St. Elisabeth tower ({int(gold_ring.sum())} px)",
        )


if __name__ == "__main__":
    result_json, verbose = parse_cli_args_for_module(sys.argv[1:])
    sys.exit(
        run_unittest_module(
            sys.modules[__name__],
            tier=2,
            suite_name="tier2_v12_visuals",
            result_json_path=result_json,
            verbose=verbose,
        )
    )
