"""Tier 1 (Python): Static Visual Assets, Geospatial Schemas, Guardrails & Audio Media Integrity."""

from __future__ import annotations

import concurrent.futures
import math
import re
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.lib.assets_helper import (
    ALL_DETAIL_PLATES_V9,
    ASSETS_DIR,
    AUDIO_DIR,
    AUDIO_FILES,
    BADWEG_LV95,
    BADWEG_PIER_ID,
    BADWEG_UV,
    BAHNHOF_PLATFORM_UV,
    CANVAS_H,
    CANVAS_W,
    CF_MEYER_HAUS_LV95,
    DATA_DIR,
    DETAIL_PLATES,
    DOCS_DIR,
    LINDT_HOC_ID,
    NEW_LANDMARK_IDS_V9,
    OVERVIEW_H,
    OVERVIEW_W,
    PRESETS,
    REQUIRED_LANDMARK_IDS,
    REQUIRED_ROAD_IDS,
    REQUIRED_VIGNETTE_KEYS_V9,
    TILES_DIR,
    count_depth_roof_small_hits,
    count_unique_rgb_colors,
    distance_to_exterior_sky_m,
    extract_vignette_uv_anchors,
    ffprobe_audio,
    get_landmark_uv,
    get_overview_dims,
    load_animations_json,
    load_depth_rgb,
    load_interactive_json,
    load_manifest,
    load_overview_rgb,
    load_plate_rgb,
    load_tile_rgb,
    plate_cartouche_margins,
    uv_pixel_distance,
    webp_encoding_type,
)
from tests.lib.report import parse_cli_args_for_module, run_unittest_module, test_meta


class TestTier1FA1Assets(unittest.TestCase):
    """FA1: Static Visual Assets, Tile Pyramid, Depth Map & Detail Plates."""

    @test_meta("T1.FA1.01", "Overviews diorama_{day,sunset,night}.webp match consistent RGB dims >=6165x2722")
    def test_01_overviews(self) -> None:
        ow, oh = get_overview_dims()
        self.assertGreaterEqual(ow, OVERVIEW_W, f"Day overview width {ow} < {OVERVIEW_W}")
        self.assertGreaterEqual(oh, OVERVIEW_H, f"Day overview height {oh} < {OVERVIEW_H}")
        for preset in PRESETS:
            p = ASSETS_DIR / f"diorama_{preset}.webp"
            self.assertTrue(p.is_file(), f"Missing overview file: {p}")
            size_bytes = p.stat().st_size
            self.assertGreater(size_bytes, 500_000, f"{p.name} too small ({size_bytes} bytes)")
            with Image.open(p) as im:
                self.assertEqual(
                    im.size,
                    (ow, oh),
                    f"{p.name} size {im.size} != ({ow}, {oh})",
                )
                self.assertEqual(im.mode, "RGB", f"{p.name} mode {im.mode} != RGB")

    @test_meta("T1.FA1.02", "Tile manifests >=24000x10600, <=0.125mpp, 1024px tiles & consistent z1 pyramid")
    def test_02_tile_manifests(self) -> None:
        ref_sig = None
        for preset in PRESETS:
            m = load_manifest(preset)
            w = int(m.get("width", 0))
            h = int(m.get("height", 0))
            ts = int(m.get("tileSize", 0))
            cols = int(m.get("cols", 0))
            rows = int(m.get("rows", 0))
            mpp = float(m.get("mpp", 999.0))

            self.assertGreaterEqual(w, 24000, f"{preset} manifest width {w} < 24000 (v10 >=2x)")
            self.assertGreaterEqual(h, 10600, f"{preset} manifest height {h} < 10600 (v10 >=2x)")
            self.assertLessEqual(mpp, 0.125, f"{preset} manifest mpp {mpp} > 0.125 (v10 >=2x)")
            self.assertGreater(mpp, 0.0, f"{preset} manifest mpp {mpp} <= 0")
            self.assertEqual(ts, 1024, f"{preset} manifest tileSize {ts} != 1024")
            self.assertEqual(cols, math.ceil(w / ts), f"{preset} manifest cols {cols} != ceil({w}/{ts})")
            self.assertEqual(rows, math.ceil(h / ts), f"{preset} manifest rows {rows} != ceil({h}/{ts})")
            self.assertAlmostEqual(float(m.get("depthMin", 0)), -2400.0, places=2)
            self.assertAlmostEqual(float(m.get("depthMax", 0)), 2400.0, places=2)
            self.assertEqual(m.get("preset"), preset, f"{preset} manifest preset field mismatch")

            sig = (w, h, ts, cols, rows, round(mpp, 6))
            if ref_sig is None:
                ref_sig = sig
            else:
                self.assertEqual(sig, ref_sig, f"{preset} manifest dims/mpp {sig} != day {ref_sig}")

            z1 = m.get("z1")
            self.assertIsInstance(z1, dict, f"{preset} manifest missing 'z1' mid-res pyramid metadata")
            z1_w = int(z1.get("width", 0))
            z1_h = int(z1.get("height", 0))
            z1_ts = int(z1.get("tileSize", 0))
            z1_cols = int(z1.get("cols", 0))
            z1_rows = int(z1.get("rows", 0))
            z1_mpp = float(z1.get("mpp", 0.0))
            self.assertEqual(z1_w, w // 2, f"{preset} z1.width {z1_w} != {w // 2}")
            self.assertEqual(z1_h, h // 2, f"{preset} z1.height {z1_h} != {h // 2}")
            self.assertAlmostEqual(z1_mpp, 0.25, places=2, msg=f"{preset} z1.mpp {z1_mpp} != ~0.25")
            self.assertEqual(z1_ts, 1024, f"{preset} z1.tileSize {z1_ts} != 1024")
            self.assertEqual(z1_cols, math.ceil(z1_w / z1_ts), f"{preset} z1.cols {z1_cols} != ceil({z1_w}/{z1_ts})")
            self.assertEqual(z1_rows, math.ceil(z1_h / z1_ts), f"{preset} z1.rows {z1_rows} != ceil({z1_h}/{z1_ts})")
            self.assertEqual(z1.get("path"), "z1", f"{preset} z1.path {z1.get('path')!r} != 'z1'")

    @test_meta("T1.FA1.03", "All lossless VP8L WebP tiles (L2 + optional z1 pyramid) decode with exact edge dims")
    def test_03_all_234_tiles(self) -> None:
        l2_tasks = []
        z1_tasks = []
        expected_l2 = 0
        expected_z1 = 0

        for preset in PRESETS:
            m = load_manifest(preset)
            W = int(m["width"])
            H = int(m["height"])
            ts = int(m["tileSize"])
            cols = int(m["cols"])
            rows = int(m["rows"])
            tdir = TILES_DIR / preset
            expected_l2 += cols * rows
            for c in range(cols):
                exp_w = ts if c < cols - 1 else (W - (cols - 1) * ts)
                for r in range(rows):
                    exp_h = ts if r < rows - 1 else (H - (rows - 1) * ts)
                    l2_tasks.append((f"{preset}/{c}_{r}.webp", tdir / f"{c}_{r}.webp", exp_w, exp_h))

            z1 = m.get("z1")
            if isinstance(z1, dict):
                z1_w = int(z1["width"])
                z1_h = int(z1["height"])
                z1_ts = int(z1.get("tileSize", 1024))
                z1_cols = int(z1["cols"])
                z1_rows = int(z1["rows"])
                z1_dir = tdir / str(z1.get("path", "z1"))
                expected_z1 += z1_cols * z1_rows
                for c in range(z1_cols):
                    exp_w = z1_ts if c < z1_cols - 1 else (z1_w - (z1_cols - 1) * z1_ts)
                    for r in range(z1_rows):
                        exp_h = z1_ts if r < z1_rows - 1 else (z1_h - (z1_rows - 1) * z1_ts)
                        z1_tasks.append((f"{preset}/z1/{c}_{r}.webp", z1_dir / f"{c}_{r}.webp", exp_w, exp_h))

        def _verify_tile(task: tuple[str, Path, int, int]) -> str | None:
            label, tp, exp_w, exp_h = task
            if not tp.is_file():
                return f"Missing tile: {label}"
            enc = webp_encoding_type(tp)
            if enc != "VP8L":
                return f"Tile {label} is {enc}, expected lossless VP8L"
            with Image.open(tp) as im:
                if im.size != (exp_w, exp_h):
                    return f"Tile {label} size {im.size} != ({exp_w}, {exp_h})"
                im.load()
            return None

        all_tasks = l2_tasks + z1_tasks
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            errors = [err for err in pool.map(_verify_tile, all_tasks) if err is not None]

        self.assertEqual(errors, [], f"Tile validation failures ({len(errors)}): {'; '.join(errors[:5])}")
        self.assertEqual(len(l2_tasks), expected_l2)
        if expected_z1 > 0:
            self.assertEqual(len(z1_tasks), expected_z1)

    @test_meta("T1.FA1.04", "Depth PNG matches day overview dims & exact (B==255)<=>(d16<65535) invariant")
    def test_04_depth_map(self) -> None:
        p = ASSETS_DIR / "kilchberg_depth.png"
        self.assertTrue(p.is_file(), "Missing docs/assets/kilchberg_depth.png")
        arr = load_depth_rgb()
        exp_shape = load_overview_rgb("day").shape
        self.assertEqual(arr.shape, exp_shape, f"Unexpected depth shape {arr.shape} != day overview {exp_shape}")

        b_vals = set(np.unique(arr[..., 2]).tolist())
        self.assertTrue(b_vals.issubset({0, 255}), f"Depth B channel has non-binary values: {b_vals}")

        d16 = (arr[..., 0].astype(np.uint16) << 8) | arr[..., 1].astype(np.uint16)
        b_occ = arr[..., 2] == 255
        d_occ = d16 < 65535
        mismatches = int(np.sum(b_occ != d_occ))
        self.assertEqual(mismatches, 0, f"Depth invariant (B==255)<=>(d16<65535) failed on {mismatches} pixels")

        occ_frac = float(np.mean(b_occ))
        self.assertGreaterEqual(occ_frac, 0.12, f"Occluder fraction {occ_frac:.4f} < 0.12")
        self.assertLessEqual(occ_frac, 0.35, f"Occluder fraction {occ_frac:.4f} > 0.35")

        valid_d16 = d16[b_occ]
        self.assertGreater(int(valid_d16.min()), 0, "Found d16==0 inside occluder mask")
        self.assertGreaterEqual(int(valid_d16.min()), 10000, f"Valid d16 min {valid_d16.min()} suspiciously low")
        self.assertLessEqual(int(valid_d16.max()), 55000, f"Valid d16 max {valid_d16.max()} suspiciously high")

    @test_meta("T1.FA1.05", "All 6 detail plates 01..06_*.webp lossless VP8L >= 2000x1400")
    def test_05_detail_plates(self) -> None:
        for fname in DETAIL_PLATES:
            p = ASSETS_DIR / fname
            self.assertTrue(p.is_file(), f"Missing detail plate: {fname}")
            enc = webp_encoding_type(p)
            self.assertEqual(enc, "VP8L", f"Detail plate {fname} is {enc}, expected lossless VP8L")
            with Image.open(p) as im:
                w, h = im.size
                self.assertEqual(im.mode, "RGB", f"{fname} mode {im.mode} != RGB")
                self.assertGreaterEqual(w, 2000, f"{fname} width {w} < 2000")
                self.assertGreaterEqual(h, 1400, f"{fname} height {h} < 1400")
                im.load()

    @test_meta("T1.FA1.06", "Lossless tiles & detail-plate bodies strictly <= 256 SVGA colors")
    def test_06_svga_256_color_budget(self) -> None:
        m_day = load_manifest("day")
        cols, rows = int(m_day["cols"]), int(m_day["rows"])
        cx, cy = cols // 2, rows // 2
        sample_tiles = (
            (max(0, cx - 1), cy),
            (cx, max(0, cy - 1)),
            (min(cols - 1, cx + 1), cy),
            (cx, cy),
        )

        def _unique_packed_u32(arr: np.ndarray) -> np.ndarray:
            # Fast O(N) RGB->uint32 packing + 1D np.unique on strided/contiguous uint32
            packed = (
                (arr[..., 0].astype(np.uint32) << 16)
                | (arr[..., 1].astype(np.uint32) << 8)
                | arr[..., 2].astype(np.uint32)
            ).ravel()
            # Use 24-bit boolean LUT bitmap when N is large (>500k pixels) for O(N) unique
            if packed.size >= 500_000:
                lut = np.zeros(1 << 24, dtype=np.bool_)
                lut[packed] = True
                return np.flatnonzero(lut).astype(np.uint32)
            return np.unique(packed)

        def _check_preset(preset: str) -> tuple[str, list[tuple[int, int, int]], int]:
            tile_counts = []
            uniques = []
            for c, r in sample_tiles:
                u = _unique_packed_u32(load_tile_rgb(preset, c, r))
                tile_counts.append((c, r, int(u.size)))
                uniques.append(u)
            n_union = int(np.unique(np.concatenate(uniques)).size)
            return preset, tile_counts, n_union

        def _check_plate(fname: str) -> tuple[str, int]:
            arr = load_plate_rgb(fname)
            mt, mb, mlr = plate_cartouche_margins(arr)
            body = arr[mt:-mb, mlr:-mlr, :]
            return fname, int(_unique_packed_u32(body).size)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            preset_results = list(pool.map(_check_preset, PRESETS))
            plate_results = list(pool.map(_check_plate, DETAIL_PLATES))

        for preset, tile_counts, n_union in preset_results:
            for c, r, n_tile in tile_counts:
                self.assertLessEqual(n_tile, 256, f"Tile {preset}/{c}_{r}.webp has {n_tile} > 256 colors")
            self.assertLessEqual(n_union, 256, f"Preset '{preset}' tile union has {n_union} > 256 colors")

        for fname, n_body in plate_results:
            self.assertLessEqual(n_body, 256, f"Detail plate {fname} body has {n_body} > 256 colors")

    @test_meta("T1.FA1.07", "index.html asset versions synced, zero CDN scripts, 550.5m stat")
    def test_07_index_html_contract(self) -> None:
        html = (DOCS_DIR / "index.html").read_text(encoding="utf-8")

        # No external CDN <script> tags required for core functionality
        ext_scripts = re.findall(r'<script[^>]+src=["\'](https?:)?//[^"\']+["\']', html, flags=re.IGNORECASE)
        self.assertEqual(ext_scripts, [], f"External CDN scripts found in index.html: {ext_scripts}")

        css_m = re.search(r'styles\.css\?v=([0-9A-Za-z._-]+)', html)
        js_m = re.search(r'app\.js\?v=([0-9A-Za-z._-]+)', html)
        self.assertIsNotNone(css_m, "styles.css missing ?v= version query parameter")
        self.assertIsNotNone(js_m, "app.js missing ?v= version query parameter")
        self.assertEqual(
            css_m.group(1),
            js_m.group(1),
            f"Asset version mismatch in docs/index.html: styles.css?v={css_m.group(1)} vs app.js?v={js_m.group(1)}",
        )
        self.assertIn(
            "550.5",
            html,
            "docs/index.html elevation stat not updated to 550.5 m spire (F25)",
        )

    @test_meta("T1.FA1.08", "Depth map open-air roof small hits <2% trains, <1% main roads")
    def test_08_depth_open_air_roof_hits(self) -> None:
        arr = load_depth_rgb()
        b_occ = arr[..., 2] == 255
        d16_map = (arr[..., 0].astype(np.uint16) << 8) | arr[..., 1].astype(np.uint16)

        occ_frac = float(np.mean(b_occ))
        self.assertGreaterEqual(occ_frac, 0.12, f"Occluder fraction {occ_frac:.4f} < 0.12")
        self.assertLessEqual(occ_frac, 0.35, f"Occluder fraction {occ_frac:.4f} > 0.35")
        self.assertGreater(int(np.sum(b_occ)), 100_000, "Depth occluder pixel count <= 100,000")

        anim = load_animations_json()
        trains_by_id = {t["id"]: t for t in anim.get("trains", [])}
        roads_by_id = {r["id"]: r for r in anim.get("roads", [])}

        violations = []
        for tid in ("sbb_s8_south", "sbb_ic_north"):
            self.assertIn(tid, trains_by_id, f"Missing train corridor '{tid}' in kilchberg_animations.json")
            hits, total = count_depth_roof_small_hits(
                trains_by_id[tid].get("pts", []), b_occ, d16_map, dy_lo=4, dy_hi=8, max_delta=45
            )
            self.assertGreater(total, 0, f"Train '{tid}' has 0 open-air samples")
            frac = hits / total
            if frac >= 0.02:
                violations.append(f"train/{tid}: {hits}/{total} ({frac * 100:.2f}% >= 2.0%)")

        main_roads = (
            "seestrasse_sb",
            "seestrasse_nb",
            "dorfstrasse_viaduct_up",
            "dorfstrasse_viaduct_dn",
            "alte_landstrasse_eb",
            "alte_landstrasse_wb",
        )
        for rid in main_roads:
            self.assertIn(rid, roads_by_id, f"Missing main road '{rid}' in kilchberg_animations.json")
            hits, total = count_depth_roof_small_hits(
                roads_by_id[rid].get("pts", []), b_occ, d16_map, dy_lo=3, dy_hi=7, max_delta=45
            )
            self.assertGreater(total, 0, f"Road '{rid}' has 0 open-air samples")
            frac = hits / total
            if frac >= 0.01:
                violations.append(f"road/{rid}: {hits}/{total} ({frac * 100:.2f}% >= 1.0%)")

        self.assertEqual(
            violations,
            [],
            f"Open-air roof small occluder hits exceed v8.0 Contract #1 limits: {'; '.join(violations)}",
        )

    @test_meta("T1.FA1.09", "index.html ES module app.js, synced ?v=, zero CDN scripts")
    def test_09_es_module_contract(self) -> None:
        html = (DOCS_DIR / "index.html").read_text(encoding="utf-8")

        ext_scripts = re.findall(r'<script[^>]+src=["\'](https?:)?//[^"\']+["\']', html, flags=re.IGNORECASE)
        self.assertEqual(ext_scripts, [], f"External CDN scripts found in index.html: {ext_scripts}")

        mod_m = re.search(
            r'<script\b(?=[^>]*\btype=["\']module["\'])(?=[^>]*\bsrc=["\']app\.js\?v=([0-9A-Za-z._-]+)["\'])[^>]*>',
            html,
            flags=re.IGNORECASE,
        )
        self.assertIsNotNone(
            mod_m,
            'docs/index.html missing <script type="module" src="app.js?v=..."> (v8.0 Contract #3)',
        )

        css_m = re.search(r'styles\.css\?v=([0-9A-Za-z._-]+)', html)
        self.assertIsNotNone(css_m, "styles.css missing ?v= version query parameter")
        self.assertEqual(
            css_m.group(1),
            mod_m.group(1),
            f"ES module version mismatch: styles.css?v={css_m.group(1)} vs app.js?v={mod_m.group(1)}",
        )

        js_dir = DOCS_DIR / "js"
        self.assertTrue(js_dir.is_dir(), "Missing docs/js/ ES module directory (v8.0 Contract #3)")
        js_modules = list(js_dir.rglob("*.js"))
        self.assertGreaterEqual(
            len(js_modules),
            3,
            f"Expected >=3 ES modules under docs/js/, found {len(js_modules)}",
        )

    @test_meta("T1.FA1.10", "All 10 detail plates 01..10_*.webp lossless VP8L >=2000x1400 <=256 colors")
    def test_10_all_10_detail_plates_v9(self) -> None:
        for fname in ALL_DETAIL_PLATES_V9:
            p = ASSETS_DIR / fname
            self.assertTrue(p.is_file(), f"Missing detail plate: {fname}")
            self.assertEqual(webp_encoding_type(p), "VP8L", f"{fname} must be lossless VP8L")
            with Image.open(p) as im:
                self.assertEqual(im.mode, "RGB", f"{fname} mode {im.mode} != RGB")
                w, h = im.size
                self.assertGreaterEqual(w, 2000, f"{fname} width {w} < 2000")
                self.assertGreaterEqual(h, 1400, f"{fname} height {h} < 1400")
            arr = load_plate_rgb(fname)
            mt, mb, mlr = plate_cartouche_margins(arr)
            body = arr[mt:-mb, mlr:-mlr, :]
            n_colors = count_unique_rgb_colors(body)
            self.assertLessEqual(
                n_colors,
                256,
                f"Detail plate {fname} body has {n_colors} colors > 256 SVGA cap",
            )

    @test_meta("T1.FA1.11", "v10 >=2x resolution contract (<=0.125mpp, JSON/manifest parity, shift_y & 10 >=3200x2200 plates)")
    def test_11_v10_resolution_contract(self) -> None:
        m_day = load_manifest("day")
        day_w = int(m_day.get("width", 0))
        day_h = int(m_day.get("height", 0))
        day_mpp = float(m_day.get("mpp", 999.0))
        self.assertLessEqual(day_mpp, 0.125, f"day manifest mpp {day_mpp} > 0.125 (v10 >=2x)")
        self.assertGreaterEqual(day_w, 24000, f"day manifest width {day_w} < 24000")
        self.assertGreaterEqual(day_h, 10600, f"day manifest height {day_h} < 10600")

        for preset in PRESETS:
            m = load_manifest(preset)
            self.assertEqual(int(m.get("width", 0)), day_w, f"{preset} manifest width != day {day_w}")
            self.assertEqual(int(m.get("height", 0)), day_h, f"{preset} manifest height != day {day_h}")
            self.assertAlmostEqual(float(m.get("mpp", 0.0)), day_mpp, places=5, msg=f"{preset} mpp != day {day_mpp}")

        inter = load_interactive_json()
        self.assertEqual(int(inter.get("canvas_width", 0)), day_w, "kilchberg_interactive.json canvas_width != manifest")
        self.assertEqual(int(inter.get("canvas_height", 0)), day_h, "kilchberg_interactive.json canvas_height != manifest")
        self.assertAlmostEqual(
            float(inter.get("camera", {}).get("mpp", 0.0)),
            day_mpp,
            places=5,
            msg="kilchberg_interactive.json camera.mpp != manifest",
        )

        anim = load_animations_json()
        self.assertEqual(int(anim.get("canvas_width", 0)), day_w, "kilchberg_animations.json canvas_width != manifest")
        self.assertEqual(int(anim.get("canvas_height", 0)), day_h, "kilchberg_animations.json canvas_height != manifest")
        self.assertAlmostEqual(
            float(anim.get("mpp", 0.0)),
            day_mpp,
            places=5,
            msg="kilchberg_animations.json mpp != manifest",
        )
        shift_y = anim.get("shift_y")
        self.assertIsInstance(shift_y, (int, float), "kilchberg_animations.json missing numeric 'shift_y' (v10 Contract #2)")
        self.assertFalse(isinstance(shift_y, bool), "kilchberg_animations.json shift_y must not be bool")
        self.assertTrue(
            math.isfinite(float(shift_y)) and float(shift_y) > 0.0,
            f"kilchberg_animations.json shift_y={shift_y!r} must be finite and > 0",
        )

        for fname in ALL_DETAIL_PLATES_V9:
            p = ASSETS_DIR / fname
            self.assertTrue(p.is_file(), f"Missing detail plate: {fname}")
            self.assertEqual(webp_encoding_type(p), "VP8L", f"{fname} must be lossless VP8L")
            with Image.open(p) as im:
                self.assertEqual(im.mode, "RGB", f"{fname} mode {im.mode} != RGB")
                w, h = im.size
                self.assertGreaterEqual(w, 3200, f"v10 plate {fname} width {w} < 3200")
                self.assertGreaterEqual(h, 2200, f"v10 plate {fname} height {h} < 2200")
            arr = load_plate_rgb(fname)
            mt, mb, mlr = plate_cartouche_margins(arr)
            body = arr[mt:-mb, mlr:-mlr, :]
            n_colors = count_unique_rgb_colors(body)
            self.assertLessEqual(
                n_colors,
                256,
                f"v10 detail plate {fname} body has {n_colors} colors > 256 SVGA cap",
            )


class TestTier1FA2GeospatialData(unittest.TestCase):
    """FA2: Geospatial Metadata, Landmarks, Living-World Routes & Guardrails."""

    @test_meta("T1.FA2.01", "kilchberg_interactive.json schema, >=24000x10600, <=0.125mpp & >=10 landmarks (0..9 preserved)")
    def test_01_interactive_schema(self) -> None:
        data = load_interactive_json()
        w = int(data.get("canvas_width", 0))
        h = int(data.get("canvas_height", 0))
        self.assertGreaterEqual(w, 24000, f"interactive canvas_width {w} < 24000 (v10 >=2x)")
        self.assertGreaterEqual(h, 10600, f"interactive canvas_height {h} < 10600 (v10 >=2x)")

        cam = data.get("camera", {})
        self.assertAlmostEqual(float(cam.get("azimuth_from_deg", 0)), 102.0, places=2)
        self.assertAlmostEqual(float(cam.get("pitch_deg", 0)), 30.0, places=2)
        self.assertLessEqual(float(cam.get("mpp", 999.0)), 0.125, f"interactive camera.mpp {cam.get('mpp')} > 0.125")
        self.assertGreater(float(cam.get("mpp", 0.0)), 0.0, "interactive camera.mpp <= 0")
        self.assertAlmostEqual(float(cam.get("z_exag", 0)), 1.16, places=3)

        lms = data.get("landmarks", [])
        self.assertGreaterEqual(len(lms), 10, f"Expected >=10 landmarks, got {len(lms)}")
        self.assertEqual(
            [lm.get("id") for lm in lms[:10]],
            list(REQUIRED_LANDMARK_IDS),
            "Original 10 REQUIRED_LANDMARK_IDS must be preserved at indices 0..9",
        )
        by_id = {lm["id"]: lm for lm in lms}
        for lid in REQUIRED_LANDMARK_IDS:
            self.assertIn(lid, by_id, f"Missing required landmark ID: {lid}")
            lm = by_id[lid]
            u, v = get_landmark_uv(lm)
            self.assertTrue(0.05 <= u <= 0.95 and 0.05 <= v <= 0.95, f"Landmark {lid} UV out of range: {(u, v)}")
            if "px" in lm:
                px, py = float(lm["px"][0]), float(lm["px"][1])
                self.assertAlmostEqual(px, u * w, delta=2.5, msg=f"Landmark {lid} px[0] inconsistent with u")
                self.assertAlmostEqual(py, v * h, delta=2.5, msg=f"Landmark {lid} px[1] inconsistent with v")

    @test_meta("T1.FA2.02", "bendlikon_pier landmark aligned to real ZSG Badweg 1.1")
    def test_02_bendlikon_pier_alignment(self) -> None:
        data = load_interactive_json()
        pier = next((lm for lm in data.get("landmarks", []) if lm.get("id") == "bendlikon_pier"), None)
        self.assertIsNotNone(pier, "bendlikon_pier landmark missing")
        de = abs(float(pier["e"]) - BADWEG_LV95[0])
        dn = abs(float(pier["n"]) - BADWEG_LV95[1])
        self.assertLessEqual(
            de,
            15.0,
            f"bendlikon_pier E={pier['e']} off by {de:.1f}m from Badweg 1.1 ({BADWEG_LV95[0]})",
        )
        self.assertLessEqual(
            dn,
            15.0,
            f"bendlikon_pier N={pier['n']} off by {dn:.1f}m from Badweg 1.1 ({BADWEG_LV95[1]})",
        )
        u, v = get_landmark_uv(pier)
        self.assertLessEqual(abs(u - BADWEG_UV[0]), 0.015, f"bendlikon_pier u={u:.5f} off from Badweg 1.1")
        self.assertLessEqual(abs(v - BADWEG_UV[1]), 0.015, f"bendlikon_pier v={v:.5f} off from Badweg 1.1")

    @test_meta("T1.FA2.03", ">=1850 buildings with 100% addr + Lindt #1443 & Badweg #4")
    def test_03_buildings_catalog(self) -> None:
        data = load_interactive_json()
        bldgs = data.get("buildings", [])
        self.assertGreaterEqual(len(bldgs), 1850, f"Expected >=1850 buildings, got {len(bldgs)}")

        empty_addr = [b.get("id") for b in bldgs if not str(b.get("addr", "")).strip()]
        self.assertEqual(len(empty_addr), 0, f"{len(empty_addr)} buildings have empty addr")

        by_id = {b["id"]: b for b in bldgs}
        self.assertIn(LINDT_HOC_ID, by_id, f"Lindt HoC building id={LINDT_HOC_ID} missing")
        lindt = by_id[LINDT_HOC_ID]
        self.assertIn("Schoorenstrasse", lindt["addr"], f"Unexpected Lindt addr: {lindt['addr']}")

        self.assertIn(BADWEG_PIER_ID, by_id, f"Bendlikon Pier building id={BADWEG_PIER_ID} missing")
        badweg = by_id[BADWEG_PIER_ID]
        self.assertIn("Badweg 1.1", badweg["addr"], f"Unexpected Badweg pier addr: {badweg['addr']}")

    @test_meta("T1.FA2.04", "SBB trains sbb_s8_south (sbb_dpz) & sbb_ic_north + Bahnhof stop")
    def test_04_sbb_trains(self) -> None:
        anim = load_animations_json()
        trains = {t["id"]: t for t in anim.get("trains", [])}
        self.assertIn("sbb_s8_south", trains, "Missing sbb_s8_south train")
        self.assertIn("sbb_ic_north", trains, "Missing sbb_ic_north train")
        self.assertEqual(trains["sbb_s8_south"].get("kind"), "sbb_dpz")
        self.assertEqual(trains["sbb_ic_north"].get("kind"), "sbb_ic")

        for tid in ("sbb_s8_south", "sbb_ic_north"):
            tr = trains[tid]
            pts = tr.get("pts", [])
            self.assertGreaterEqual(len(pts), 200, f"{tid} has too few points ({len(pts)})")
            self.assertEqual(len(pts[0]), 4, f"{tid} pts must be 4-tuples [u, v, occ, d16]")
            occ_cnt = sum(1 for p in pts if p[2])
            self.assertGreater(occ_cnt, 0, f"{tid} has 0 occluded points")
            sf = float(tr.get("stop_frac", -1))
            self.assertTrue(0.2 < sf < 0.8, f"{tid} stop_frac {sf} out of (0.2, 0.8)")
            idx = min(len(pts) - 1, max(0, int(round(sf * (len(pts) - 1)))))
            dist_px = uv_pixel_distance((pts[idx][0], pts[idx][1]), BAHNHOF_PLATFORM_UV)
            self.assertLessEqual(
                dist_px,
                120.0,
                f"{tid} stop point is {dist_px:.1f} px from Bahnhof Kilchberg platform (max 120 px)",
            )

    @test_meta("T1.FA2.05", "All 8 edge-to-edge roads valid lengths & bus routes have stops")
    def test_05_roads_and_bus_stops(self) -> None:
        anim = load_animations_json()
        roads = {r["id"]: r for r in anim.get("roads", [])}
        min_lengths = {
            "seestrasse_sb": 2200.0,
            "seestrasse_nb": 2200.0,
            "dorfstrasse_viaduct_up": 2400.0,
            "dorfstrasse_viaduct_dn": 2400.0,
            "alte_landstrasse_eb": 2200.0,
            "alte_landstrasse_wb": 2200.0,
            "a3_motorway_0": 850.0,
            "a3_motorway_1": 850.0,
        }
        bus_routes_checked = 0
        for rid in REQUIRED_ROAD_IDS:
            self.assertIn(rid, roads, f"Missing required road route: {rid}")
            rd = roads[rid]
            pts = rd.get("pts", [])
            self.assertGreaterEqual(len(pts), 200, f"{rid} has only {len(pts)} pts (< 200)")
            length_m = float(rd.get("length_m", 0))
            self.assertGreaterEqual(
                length_m,
                min_lengths[rid],
                f"{rid} length {length_m:.1f}m < {min_lengths[rid]}m",
            )
            has_bus = bool(rd.get("has_bus")) or int(rd.get("bus_count", 0)) > 0
            if has_bus:
                bus_routes_checked += 1
                stops = rd.get("stops")
                self.assertIsInstance(stops, list, f"Bus route {rid} missing 'stops' array (F17)")
                self.assertGreater(len(stops), 0, f"Bus route {rid} has empty 'stops' array (F17)")
                for sf in stops:
                    self.assertTrue(0.05 < float(sf) < 0.95, f"Bus route {rid} stop {sf} outside (0.05, 0.95)")
        self.assertGreater(bus_routes_checked, 0, "No bus routes found in kilchberg_animations.json")

    @test_meta("T1.FA2.06", "ZSG steamer docks near Badweg 1.1, edge-to-edge path & fleet")
    def test_06_zsg_steamer_and_lake_fleet(self) -> None:
        anim = load_animations_json()
        ships = {s["id"]: s for s in anim.get("ships", [])}
        self.assertIn("zsg_ms_helvetia", ships, "Missing zsg_ms_helvetia")
        steamer = ships["zsg_ms_helvetia"]
        self.assertEqual(steamer.get("kind"), "zsg_steamer")
        self.assertFalse(bool(steamer.get("closed", False)), "zsg_ms_helvetia must be an open edge-to-edge path")
        self.assertGreaterEqual(float(steamer.get("dwell_sec", 0)), 3.0, "Steamer dwell_sec < 3.0s")

        pts = steamer.get("pts", [])
        self.assertGreaterEqual(len(pts), 200)
        sf = float(steamer.get("stop_frac", -1))
        self.assertTrue(0.1 < sf < 0.9, f"Steamer stop_frac {sf} out of range")
        idx = min(len(pts) - 1, max(0, int(round(sf * (len(pts) - 1)))))
        dock_dist_px = uv_pixel_distance((pts[idx][0], pts[idx][1]), BADWEG_UV)
        self.assertLessEqual(
            dock_dist_px,
            250.0,
            f"zsg_ms_helvetia docks {dock_dist_px:.1f} px from Badweg 1.1 (max 250 px; F17)",
        )

        start_edge_m = distance_to_exterior_sky_m(pts[0][0], pts[0][1])
        end_edge_m = distance_to_exterior_sky_m(pts[-1][0], pts[-1][1])
        self.assertLess(
            start_edge_m,
            100.0,
            f"zsg_ms_helvetia start is {start_edge_m:.1f}m inland from lake cut-edge (max 100m; F17)",
        )
        self.assertLess(
            end_edge_m,
            100.0,
            f"zsg_ms_helvetia end is {end_edge_m:.1f}m inland from lake cut-edge (max 100m; F17)",
        )

        for sid in ("sailboat_1", "sailboat_2", "sailboat_3", "boesch_runabout"):
            self.assertIn(sid, ships, f"Missing lake vessel {sid}")
            self.assertTrue(bool(ships[sid].get("closed")), f"{sid} must be a closed loop")

    @test_meta("T1.FA2.07", "Ambient steam, 4 flags (Bendlikon aligned), gulls, shore, chimneys")
    def test_07_ambient_elements(self) -> None:
        anim = load_animations_json()
        amb = anim.get("ambient", {})

        steam = amb.get("chimney_steam", {})
        self.assertIn("uv", steam, "ambient.chimney_steam missing uv")
        self.assertEqual(len(steam["uv"]), 2)

        flags = amb.get("swiss_flags", [])
        self.assertEqual(len(flags), 4, f"Expected 4 swiss_flags, got {len(flags)}")
        bend_flag = next((f for f in flags if "bendlikon" in str(f.get("name", "")).lower()), None)
        self.assertIsNotNone(bend_flag, "Bendlikon Pier swiss_flag missing")
        flag_dist = uv_pixel_distance((bend_flag["uv"][0], bend_flag["uv"][1]), BADWEG_UV)
        self.assertLessEqual(
            flag_dist,
            150.0,
            f"Bendlikon Pier flag is {flag_dist:.1f} px from Badweg 1.1 (max 150 px; F17)",
        )

        gulls = amb.get("gulls", [])
        self.assertGreaterEqual(len(gulls), 3, f"Expected >=3 gulls, got {len(gulls)}")
        for g in gulls:
            self.assertIn("uv", g, "Gull entry missing uv")
            self.assertGreater(float(g.get("rx", 0)), 0)
            self.assertGreater(float(g.get("ry", 0)), 0)

        shore = amb.get("shoreline", [])
        self.assertGreaterEqual(len(shore), 80, f"Expected >=80 shoreline pts, got {len(shore)}")

        vchim = amb.get("village_chimneys")
        self.assertIsInstance(vchim, list, "ambient.village_chimneys missing (F15/F20)")
        self.assertGreaterEqual(len(vchim), 6, f"Expected >=6 village_chimneys, got {len(vchim)}")

        fountains = amb.get("fountains")
        self.assertIsInstance(fountains, list, "ambient.fountains missing (F15/F20)")
        self.assertGreaterEqual(len(fountains), 2, f"Expected >=2 fountains, got {len(fountains)}")

    @test_meta("T1.FA2.08", "Guardrail #1: Zero paraglider/balloon/glider terms across docs/")
    def test_08_zero_prohibited_terms(self) -> None:
        pattern = re.compile(r"paraglider|hot-air|balloon|glider", re.IGNORECASE)
        hits = []
        for ext in ("*.html", "*.js", "*.css", "*.json"):
            for fp in DOCS_DIR.rglob(ext):
                txt = fp.read_text(encoding="utf-8", errors="ignore")
                m = pattern.search(txt)
                if m:
                    hits.append(f"{fp.relative_to(DOCS_DIR)}: '{m.group(0)}'")
        self.assertEqual(hits, [], f"Prohibited aerial terms found in docs/: {hits}")

    @test_meta("T1.FA2.09", "kilchberg_animations.json network schema & compact size <650KB")
    def test_09_multimodal_network_schema(self) -> None:
        anim_path = DATA_DIR / "kilchberg_animations.json"
        self.assertTrue(anim_path.is_file(), f"Missing {anim_path}")
        size_bytes = anim_path.stat().st_size
        self.assertLess(
            size_bytes,
            650 * 1024,
            f"kilchberg_animations.json size {size_bytes} bytes >= 650 KB limit (Contract #2)",
        )

        anim = load_animations_json()
        net = anim.get("network")
        self.assertIsInstance(
            net,
            dict,
            "kilchberg_animations.json missing 'network' object (v8.0 Contract #2)",
        )

        # 1. crosswalks
        crosswalks = net.get("crosswalks")
        self.assertIsInstance(crosswalks, list, "network.crosswalks must be a list")
        self.assertGreaterEqual(len(crosswalks), 6, f"Expected >=6 crosswalks, got {len(crosswalks)}")
        for cw in crosswalks:
            for k in ("id", "name", "road_id", "frac", "u", "v", "d16", "nx", "ny"):
                self.assertIn(k, cw, f"crosswalk {cw.get('id')} missing key '{k}'")
            self.assertIn(cw["road_id"], REQUIRED_ROAD_IDS, f"crosswalk {cw['id']} unknown road_id '{cw['road_id']}'")
            frac = float(cw["frac"])
            self.assertTrue(0.0 < frac < 1.0, f"crosswalk {cw['id']} frac={frac} not in (0, 1)")

        # 2. junctions
        junctions = net.get("junctions")
        self.assertIsInstance(junctions, list, "network.junctions must be a list")
        self.assertGreaterEqual(len(junctions), 4, f"Expected >=4 junctions, got {len(junctions)}")
        for jc in junctions:
            for k in ("id", "name", "u", "v", "d16", "links"):
                self.assertIn(k, jc, f"junction {jc.get('id')} missing key '{k}'")
            links = jc["links"]
            self.assertIsInstance(links, list, f"junction {jc['id']} links must be a list")
            self.assertGreaterEqual(len(links), 1, f"junction {jc['id']} has empty links")
            for lnk in links:
                self.assertIn("road_id", lnk, f"junction {jc['id']} link missing road_id")
                self.assertIn("frac", lnk, f"junction {jc['id']} link missing frac")

        # 3. feeders
        feeders = net.get("feeders")
        self.assertIsInstance(feeders, list, "network.feeders must be a list")
        self.assertGreaterEqual(len(feeders), 4, f"Expected >=4 feeders, got {len(feeders)}")
        for fd in feeders:
            for k in ("id", "name", "kind", "length_m", "pts", "connects_road", "connects_frac"):
                self.assertIn(k, fd, f"feeder {fd.get('id')} missing key '{k}'")
            self.assertGreater(float(fd["length_m"]), 0.0, f"feeder {fd['id']} length_m <= 0")
            self.assertIn(fd["connects_road"], REQUIRED_ROAD_IDS, f"feeder {fd['id']} unknown connects_road '{fd['connects_road']}'")
            pts = fd["pts"]
            self.assertIsInstance(pts, list, f"feeder {fd['id']} pts must be a list")
            self.assertGreaterEqual(len(pts), 5, f"feeder {fd['id']} has <5 pts")
            self.assertGreaterEqual(len(pts[0]), 4, f"feeder {fd['id']} pt missing [u,v,occ,d16]")

        # 4. footpaths
        footpaths = net.get("footpaths")
        self.assertIsInstance(footpaths, list, "network.footpaths must be a list")
        self.assertGreaterEqual(len(footpaths), 4, f"Expected >=4 footpaths, got {len(footpaths)}")
        for fp in footpaths:
            for k in ("id", "name", "kind", "length_m", "pts", "from_poi", "to_poi"):
                self.assertIn(k, fp, f"footpath {fp.get('id')} missing key '{k}'")
            self.assertGreater(float(fp["length_m"]), 0.0, f"footpath {fp['id']} length_m <= 0")
            pts = fp["pts"]
            self.assertIsInstance(pts, list, f"footpath {fp['id']} pts must be a list")
            self.assertGreaterEqual(len(pts), 5, f"footpath {fp['id']} has <5 pts")
            self.assertGreaterEqual(len(pts[0]), 4, f"footpath {fp['id']} pt missing [u,v,occ,d16]")

        # 5. pois
        pois = net.get("pois")
        self.assertIsInstance(pois, list, "network.pois must be a list")
        self.assertGreaterEqual(len(pois), 8, f"Expected >=8 POIs, got {len(pois)}")
        for poi in pois:
            for k in ("id", "name", "kind", "u", "v", "d16"):
                self.assertIn(k, poi, f"poi {poi.get('id')} missing key '{k}'")

        # 6. extra_sports
        extra_sports = net.get("extra_sports")
        self.assertIsInstance(extra_sports, list, "network.extra_sports must be a list")
        self.assertGreaterEqual(len(extra_sports), 1, f"Expected >=1 extra_sports, got {len(extra_sports)}")
        for sp in extra_sports:
            for k in ("id", "kind", "u", "v", "d16", "w_m", "h_m", "angle"):
                self.assertIn(k, sp, f"extra_sports {sp.get('id')} missing key '{k}'")
            self.assertGreater(float(sp["w_m"]), 0.0, f"extra_sports {sp['id']} w_m <= 0")
            self.assertGreater(float(sp["h_m"]), 0.0, f"extra_sports {sp['id']} h_m <= 0")

    @test_meta("T1.FA2.10", "v9.0 >=16 landmarks, 0..9 preserved, 6 new IDs & cf_meyer_haus <=35m LV95")
    def test_10_v9_16_landmarks_and_cf_meyer_haus(self) -> None:
        data = load_interactive_json()
        w = int(data.get("canvas_width", CANVAS_W))
        h = int(data.get("canvas_height", CANVAS_H))
        lms = data.get("landmarks", [])
        self.assertGreaterEqual(len(lms), 16, f"Expected >=16 landmarks, got {len(lms)}")
        self.assertEqual(
            [lm.get("id") for lm in lms[:10]],
            list(REQUIRED_LANDMARK_IDS),
            "Original 10 REQUIRED_LANDMARK_IDS must be preserved at indices 0..9",
        )
        by_id = {lm["id"]: lm for lm in lms if "id" in lm}
        for lid in NEW_LANDMARK_IDS_V9:
            self.assertIn(lid, by_id, f"Missing v9.0 landmark ID: {lid}")
            lm = by_id[lid]
            u, v = get_landmark_uv(lm)
            self.assertTrue(
                0.05 <= u <= 0.95 and 0.05 <= v <= 0.95,
                f"v9.0 landmark {lid} UV out of [0.05, 0.95]: {(u, v)}",
            )
            if "px" in lm:
                px, py = float(lm["px"][0]), float(lm["px"][1])
                self.assertAlmostEqual(px, u * w, delta=2.5, msg=f"Landmark {lid} px[0] inconsistent with u")
                self.assertAlmostEqual(py, v * h, delta=2.5, msg=f"Landmark {lid} px[1] inconsistent with v")

        cf = by_id.get("cf_meyer_haus")
        self.assertIsNotNone(cf, "cf_meyer_haus landmark missing")
        self.assertIn("e", cf, "cf_meyer_haus missing LV95 easting 'e'")
        self.assertIn("n", cf, "cf_meyer_haus missing LV95 northing 'n'")
        dist_m = math.hypot(float(cf["e"]) - CF_MEYER_HAUS_LV95[0], float(cf["n"]) - CF_MEYER_HAUS_LV95[1])
        self.assertLessEqual(
            dist_m,
            35.0,
            f"cf_meyer_haus LV95 ({cf['e']}, {cf['n']}) is {dist_m:.1f} m from Alte Landstrasse 170 {CF_MEYER_HAUS_LV95} (>35m)",
        )

    @test_meta("T1.FA2.11", "v9.0 ambient.vignettes covers all 9 new/un-vignetted landmarks in [0,1] UV & <650KB")
    def test_11_v9_vignette_anchors_and_size(self) -> None:
        anim_path = DATA_DIR / "kilchberg_animations.json"
        self.assertTrue(anim_path.is_file(), "Missing docs/data/kilchberg_animations.json")
        sz = anim_path.stat().st_size
        self.assertLess(sz, 650 * 1024, f"kilchberg_animations.json size {sz} >= 650 KB")

        vigs = load_animations_json().get("ambient", {}).get("vignettes")
        self.assertIsInstance(vigs, dict, "ambient.vignettes must be a dict")
        for key in REQUIRED_VIGNETTE_KEYS_V9:
            self.assertIn(key, vigs, f"Missing ambient.vignettes['{key}']")
            anchors = extract_vignette_uv_anchors(vigs[key], prefix=key)
            self.assertGreater(len(anchors), 0, f"ambient.vignettes['{key}'] has no valid UV anchors")
            for label, u, v in anchors:
                self.assertTrue(
                    0.0 <= u <= 1.0 and 0.0 <= v <= 1.0,
                    f"Vignette anchor {label} UV ({u}, {v}) out of [0, 1]",
                )


class TestTier1FA4AudioStatic(unittest.TestCase):
    """FA4 (Static): Audio MP3 Files Existence & ffprobe Stream Integrity."""

    @test_meta("T1.FA4.01", "All 9 spatial audio MP3 files exist and are non-empty")
    def test_01_audio_files_exist(self) -> None:
        for fname in AUDIO_FILES:
            p = AUDIO_DIR / fname
            self.assertTrue(p.is_file(), f"Missing audio file: docs/assets/audio/{fname}")
            sz = p.stat().st_size
            self.assertGreater(sz, 50_000, f"Audio file {fname} unexpectedly small ({sz} bytes)")

    @test_meta("T1.FA4.02", "ffprobe validates all 9 MP3s (codec, rate, channels, >=10s)")
    def test_02_ffprobe_all_audio(self) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            probed = list(zip(AUDIO_FILES, pool.map(ffprobe_audio, AUDIO_FILES)))

        for fname, info in probed:
            streams = info.get("streams", [])
            self.assertGreater(len(streams), 0, f"No streams found in {fname}")
            st = streams[0]
            fmt = info.get("format", {})
            self.assertEqual(st.get("codec_name"), "mp3", f"{fname} codec {st.get('codec_name')} != mp3")
            sr = int(st.get("sample_rate", 0))
            self.assertGreaterEqual(sr, 22050, f"{fname} sample_rate {sr} < 22050")
            ch = int(st.get("channels", 0))
            self.assertIn(ch, (1, 2), f"{fname} channels {ch} not in (1, 2)")
            dur = float(fmt.get("duration") or st.get("duration") or 0.0)
            self.assertGreaterEqual(dur, 10.0, f"{fname} duration {dur:.2f}s < 10.0s")
            br = int(fmt.get("bit_rate") or st.get("bit_rate") or 0)
            self.assertGreater(br, 0, f"{fname} bit_rate must be > 0")


if __name__ == "__main__":
    result_json, verbose = parse_cli_args_for_module(sys.argv[1:])
    sys.exit(
        run_unittest_module(
            sys.modules[__name__],
            tier=1,
            suite_name="tier1_assets_data",
            result_json_path=result_json,
            verbose=verbose,
        )
    )
