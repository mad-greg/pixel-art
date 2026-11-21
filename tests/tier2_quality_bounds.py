"""Tier 2 (Python): Pixel-Quality, Palette, Floating-Artifact, Water, Lighting & Geometric Bounds."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.lib.assets_helper import (
    CANVAS_H,
    CANVAS_W,
    DETAIL_PLATES,
    LINDT_HOC_ID,
    OVERVIEW_H,
    OVERVIEW_W,
    PRESETS,
    REQUIRED_ROAD_IDS,
    compute_sky_reference,
    distance_to_exterior_sky_m,
    entropy_32b,
    filter_dilated_components,
    find_interior_components,
    get_day_island_and_exterior_masks,
    get_lake_zurich_mask_2x,
    get_landmark_uv,
    load_animations_json,
    load_depth_rgb,
    load_interactive_json,
    load_manifest,
    load_overview_rgb,
    load_plate_rgb,
    load_tile_rgb,
    max_channel_abs_diff_u8,
    pixel_turn_angles_deg,
    pool2x_max,
    rec709_luma,
    signed_hsv_hue_deg,
)
from tests.lib.report import parse_cli_args_for_module, run_unittest_module, test_meta


class TestTier2FA1PixelQuality(unittest.TestCase):
    """FA1 Boundary & Corner Cases: Luminance, CLUTs, Seams, Artifacts, Water, Lighting, Roofs."""

    @test_meta("T2.FA1.01", "Strict diurnal luminance ordering night < sunset < day (gap > 8)")
    def test_01_diurnal_luminance_ordering(self) -> None:
        masks = get_day_island_and_exterior_masks()
        island = masks["island_full"]

        full_means = {}
        island_means = {}
        weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)
        for preset in PRESETS:
            arr = load_overview_rgb(preset)
            # Exact linearity of expectation avoids allocating 200MB float32 luma buffer
            full_means[preset] = float(np.dot(arr.mean(axis=(0, 1)), weights))
            island_means[preset] = float(np.dot(arr[island].mean(axis=0), weights))

        self.assertGreater(
            full_means["day"],
            full_means["sunset"] + 8.0,
            f"Full overview luma day ({full_means['day']:.2f}) not > sunset ({full_means['sunset']:.2f}) + 8",
        )
        self.assertGreater(
            full_means["sunset"],
            full_means["night"] + 8.0,
            f"Full overview luma sunset ({full_means['sunset']:.2f}) not > night ({full_means['night']:.2f}) + 8",
        )
        self.assertGreater(
            island_means["day"],
            island_means["sunset"] + 8.0,
            f"Island luma day ({island_means['day']:.2f}) not > sunset ({island_means['sunset']:.2f}) + 8",
        )
        self.assertGreater(
            island_means["sunset"],
            island_means["night"] + 8.0,
            f"Island luma sunset ({island_means['sunset']:.2f}) not > night ({island_means['night']:.2f}) + 8",
        )
        self.assertTrue(
            75.0 <= island_means["day"] <= 145.0,
            f"Day island luma {island_means['day']:.2f} outside [75, 145]",
        )
        self.assertTrue(
            20.0 <= island_means["night"] <= 65.0,
            f"Night island luma {island_means['night']:.2f} outside [20, 65]",
        )

    @test_meta("T2.FA1.02", "Per-preset curated 256-color CLUTs (night>=120, overlap<0.70)")
    def test_02_per_preset_cluts(self) -> None:
        sample_tiles = ((4, 3), (5, 2), (6, 3), (5, 3))
        palettes = {}
        for preset in PRESETS:
            cols = []
            for c, r in sample_tiles:
                arr = load_tile_rgb(preset, c, r)
                packed = (
                    (arr[..., 0].astype(np.uint32) << 16)
                    | (arr[..., 1].astype(np.uint32) << 8)
                    | arr[..., 2].astype(np.uint32)
                )
                cols.append(np.unique(packed))
            pal = set(np.unique(np.concatenate(cols)).tolist())
            self.assertLessEqual(len(pal), 256, f"{preset} central tile union has {len(pal)} > 256 colors")
            palettes[preset] = pal

        self.assertGreaterEqual(
            len(palettes["night"]),
            120,
            f"Night preset palette under-utilized: {len(palettes['night'])} < 120 colors (F6)",
        )
        ov_ds = len(palettes["day"] & palettes["sunset"]) / max(1, min(len(palettes["day"]), len(palettes["sunset"])))
        ov_dn = len(palettes["day"] & palettes["night"]) / max(1, min(len(palettes["day"]), len(palettes["night"])))
        self.assertLess(
            ov_ds,
            0.70,
            f"day/sunset CLUT overlap {ov_ds:.3f} >= 0.70 (shared palette instead of per-preset CLUT; F6)",
        )
        self.assertLess(
            ov_dn,
            0.70,
            f"day/night CLUT overlap {ov_dn:.3f} >= 0.70 (shared palette instead of per-preset CLUT; F6)",
        )

    @test_meta("T2.FA1.03", "Tile seam continuity (boundary_MAD / interior_MAD < 1.35)")
    def test_03_tile_seam_continuity(self) -> None:
        horiz_pairs = [((4, 3), (5, 3)), ((5, 2), (6, 2))]
        vert_pairs = [((5, 2), (5, 3)), ((6, 2), (6, 3))]

        for preset in ("day", "night"):
            for (c1, r1), (c2, r2) in horiz_pairs:
                a = load_tile_rgb(preset, c1, r1).astype(np.float32)
                b = load_tile_rgb(preset, c2, r2).astype(np.float32)
                b_mad = float(np.mean(np.abs(a[:, -1, :] - b[:, 0, :])))
                i_mad = 0.5 * (
                    float(np.mean(np.abs(a[:, -2, :] - a[:, -1, :])))
                    + float(np.mean(np.abs(b[:, 0, :] - b[:, 1, :])))
                )
                ratio = b_mad / max(i_mad, 1.0)
                self.assertLess(
                    ratio,
                    1.35,
                    f"Horizontal tile seam spike in {preset} {c1}_{r1}|{c2}_{r2}: ratio={ratio:.2f}",
                )

            for (c1, r1), (c2, r2) in vert_pairs:
                a = load_tile_rgb(preset, c1, r1).astype(np.float32)
                b = load_tile_rgb(preset, c2, r2).astype(np.float32)
                b_mad = float(np.mean(np.abs(a[-1, :, :] - b[0, :, :])))
                i_mad = 0.5 * (
                    float(np.mean(np.abs(a[-2, :, :] - a[-1, :, :])))
                    + float(np.mean(np.abs(b[0, :, :] - b[1, :, :])))
                )
                ratio = b_mad / max(i_mad, 1.0)
                self.assertLess(
                    ratio,
                    1.35,
                    f"Vertical tile seam spike in {preset} {c1}_{r1}|{c2}_{r2}: ratio={ratio:.2f}",
                )

    @test_meta("T2.FA1.04", "Zero floating sky parked cars in day/sunset/night overviews & depth")
    def test_04_zero_floating_sky_cars(self) -> None:
        masks = get_day_island_and_exterior_masks()

        # Reuse cached day component scan from get_day_island_and_exterior_masks()
        day_comps = masks["day_components"]
        self.assertEqual(
            len(day_comps),
            1,
            f"diorama_day.webp has {len(day_comps) - 1} floating sky clusters outside main island (F4)",
        )

        sunset = load_overview_rgb("sunset")
        sunset_comps = find_interior_components(
            sunset,
            tol=18,
            margin_top=90,
            margin_bot=60,
            margin_lr=24,
            min_raw_2x=5,
            min_dilated_2x=45,
        )
        self.assertEqual(
            len(sunset_comps),
            1,
            f"diorama_sunset.webp has {len(sunset_comps) - 1} floating sky clusters outside main island (F4)",
        )

        ext_sky = masks["ext_sky_eroded_full"]

        depth = load_depth_rgb()
        floating_depth_px = int(np.sum((depth[..., 2] == 255) & ext_sky))
        self.assertEqual(
            floating_depth_px,
            0,
            f"kilchberg_depth.png has {floating_depth_px} floating occluder pixels in exterior sky (F4)",
        )

        night = load_overview_rgb("night")
        n_ref = compute_sky_reference(night)
        n_diff = max_channel_abs_diff_u8(night, n_ref)
        n_floating = (n_diff > 28) & ext_sky
        n_big = filter_dilated_components(
            pool2x_max(n_floating),
            dilate_size=5,
            min_raw_2x=5,
            min_dilated_2x=45,
        )
        self.assertEqual(
            len(n_big),
            0,
            f"diorama_night.webp has {len(n_big)} floating bright clusters in exterior sky (F4)",
        )

    @test_meta("T2.FA1.05", "Zero floating cropped sports props across all 6 detail plates")
    def test_05_zero_floating_plate_props(self) -> None:
        bad = []
        for fname in DETAIL_PLATES:
            arr = load_plate_rgb(fname)
            comps = find_interior_components(
                arr,
                tol=18,
                margin_top=110,
                margin_bot=90,
                margin_lr=24,
                min_raw_2x=4,
                min_dilated_2x=45,
            )
            if len(comps) != 1:
                bad.append(f"{fname} ({len(comps) - 1} floating clusters)")
        self.assertEqual(bad, [], f"Floating cropped props found in detail plates (F4): {', '.join(bad)}")

    @test_meta("T2.FA1.06", "Spotless Lake Zurich open water & near-shore (zero reed blotches)")
    def test_06_spotless_lake_water(self) -> None:
        day = load_overview_rgb("day")
        anim = load_animations_json()

        def is_tan(rgb: np.ndarray) -> np.ndarray:
            r = rgb[..., 0].astype(np.int16)
            g = rgb[..., 1].astype(np.int16)
            b = rgb[..., 2].astype(np.int16)
            return (r - b > 15) & (r >= g - 5) & (g - b > 8) & (r > 75) & (r < 210)

        def is_blue_water(rgb: np.ndarray) -> np.ndarray:
            r = rgb[..., 0].astype(np.int16)
            g = rgb[..., 1].astype(np.int16)
            b = rgb[..., 2].astype(np.int16)
            return (b > r + 15) & (g > r + 10)

        # Open water patches along ship paths
        water_pixels = []
        for ship in anim.get("ships", []):
            pts = ship.get("pts", [])
            step = max(1, len(pts) // 80)
            for p in pts[::step]:
                cx = int(round(p[0] * (OVERVIEW_W - 1)))
                cy = int(round(p[1] * (OVERVIEW_H - 1)))
                if 3 <= cx < OVERVIEW_W - 3 and 3 <= cy < OVERVIEW_H - 3:
                    water_pixels.append(day[cy - 2 : cy + 3, cx - 2 : cx + 3, :].reshape(-1, 3))
        open_rgb = np.concatenate(water_pixels, axis=0)
        open_tan = float(np.mean(is_tan(open_rgb)))
        open_blue = float(np.mean(is_blue_water(open_rgb)))
        self.assertLess(open_tan, 0.01, f"Open water tan_frac {open_tan:.4f} >= 0.01")
        self.assertGreater(open_blue, 0.85, f"Open water blue_water_frac {open_blue:.4f} <= 0.85")

        # Near-shore water (+6..+18 overview px lakeside of shoreline toward lake center)
        shore = anim.get("ambient", {}).get("shoreline", [])
        self.assertGreaterEqual(len(shore), 40)
        lake_center_x = 0.65 * OVERVIEW_W
        lake_center_y = 0.72 * OVERVIEW_H
        near_pixels = []
        for i in range(len(shore)):
            sx = shore[i][0] * (OVERVIEW_W - 1)
            sy = shore[i][1] * (OVERVIEW_H - 1)
            if 0 < i < len(shore) - 1:
                tx = (shore[i + 1][0] - shore[i - 1][0]) * OVERVIEW_W
                ty = (shore[i + 1][1] - shore[i - 1][1]) * OVERVIEW_H
            elif i == 0:
                tx = (shore[1][0] - shore[0][0]) * OVERVIEW_W
                ty = (shore[1][1] - shore[0][1]) * OVERVIEW_H
            else:
                tx = (shore[-1][0] - shore[-2][0]) * OVERVIEW_W
                ty = (shore[-1][1] - shore[-2][1]) * OVERVIEW_H
            nlen = math.hypot(tx, ty)
            if nlen < 1e-6:
                continue
            # Perpendicular normal oriented toward Lake Zurich center
            nx, ny = -ty / nlen, tx / nlen
            if nx * (lake_center_x - sx) + ny * (lake_center_y - sy) < 0:
                nx, ny = -nx, -ny
            for dist in (8, 12, 16):
                px = int(round(sx + nx * dist))
                py = int(round(sy + ny * dist))
                if 2 <= px < OVERVIEW_W - 2 and 2 <= py < OVERVIEW_H - 2:
                    near_pixels.append(day[py - 1 : py + 2, px - 1 : px + 2, :].reshape(-1, 3))

        near_rgb = np.concatenate(near_pixels, axis=0)
        near_tan = float(np.mean(is_tan(near_rgb)))
        self.assertLess(near_tan, 0.03, f"Near-shore water tan/reed blotch fraction {near_tan:.4f} >= 0.03 (Guardrail #5)")

    @test_meta("T2.FA1.07", "Sunset golden honey-apricot white plaster (no pink cast)")
    def test_07_sunset_golden_plaster(self) -> None:
        day = load_overview_rgb("day")
        sunset = load_overview_rgb("sunset")
        bldgs = load_interactive_json().get("buildings", [])

        day_samples = []
        sun_samples = []
        for b in bldgs[::2]:
            cx = int(round(float(b["u"]) * (OVERVIEW_W - 1)))
            cy = int(round(float(b["v"]) * (OVERVIEW_H - 1)))
            if 6 <= cx < OVERVIEW_W - 6 and 2 <= cy < OVERVIEW_H - 14:
                day_samples.append(day[cy : cy + 12, cx - 5 : cx + 5, :].reshape(-1, 3))
                sun_samples.append(sunset[cy : cy + 12, cx - 5 : cx + 5, :].reshape(-1, 3))

        d_rgb = np.concatenate(day_samples, axis=0)
        s_rgb = np.concatenate(sun_samples, axis=0)
        d_luma = rec709_luma(d_rgb)
        d_sat = d_rgb.max(axis=1).astype(np.int16) - d_rgb.min(axis=1).astype(np.int16)
        plaster_mask = (d_luma > 140.0) & (d_sat < 35)
        self.assertGreater(int(np.sum(plaster_mask)), 1000, "Insufficient white plaster pixels sampled")

        sp_all = s_rgb[plaster_mask]
        s_luma = rec709_luma(sp_all)
        # Filter to sunlit sunset plaster (s_luma > 120) so F6 cool violet cast shadows are never penalized
        sp = sp_all[s_luma > 120.0].astype(np.float64)
        self.assertGreater(len(sp), 500, f"Insufficient sunlit sunset plaster pixels sampled ({len(sp)})")

        mean_r, mean_g, mean_b = float(sp[:, 0].mean()), float(sp[:, 1].mean()), float(sp[:, 2].mean())
        mean_gb = mean_g - mean_b
        # Bubblegum-pink requires R >= B (never matching F6 cool violet shadows where B > R > G)
        pink_frac = float(
            np.mean((sp[:, 0] > sp[:, 1] + 5.0) & (sp[:, 2] >= sp[:, 1] - 5.0) & (sp[:, 0] >= sp[:, 2]))
        )
        hues = signed_hsv_hue_deg(sp[:, 0], sp[:, 1], sp[:, 2])
        med_hue = float(np.median(hues))

        self.assertTrue(
            mean_r > mean_g > mean_b,
            f"Sunset plaster not warm ordered R>G>B: ({mean_r:.1f}, {mean_g:.1f}, {mean_b:.1f})",
        )
        self.assertGreaterEqual(
            mean_gb,
            16.0,
            f"Sunset plaster G-B={mean_gb:.1f} < 16.0 (pinkish cast; F6)",
        )
        self.assertLess(
            pink_frac,
            0.06,
            f"Sunset plaster pink_frac={pink_frac:.3f} >= 0.06 (bubblegum-pink cast; F6)",
        )
        self.assertTrue(
            19.0 <= med_hue <= 45.0,
            f"Sunset plaster median hue={med_hue:.1f} deg outside golden [19, 45] deg (F6)",
        )

    @test_meta("T2.FA1.08", "Night cozy streetlamp & window warm amber pools along streets")
    def test_08_night_warm_streetlamp_pools(self) -> None:
        night = load_overview_rgb("night")
        island = get_day_island_and_exterior_masks()["island_full"]

        r = night[..., 0].astype(np.int16)
        g = night[..., 1].astype(np.int16)
        b = night[..., 2].astype(np.int16)
        warm = (r > 120) & (r > g + 10) & (g > b + 20)

        island_warm_frac = float(np.mean(warm[island]))
        self.assertGreaterEqual(
            island_warm_frac,
            0.0025,
            f"Night island warm amber pixel fraction {island_warm_frac * 100:.3f}% < 0.25% (F7)",
        )

        roads = {rd["id"]: rd for rd in load_animations_json().get("roads", [])}
        for rid in ("seestrasse_sb", "dorfstrasse_viaduct_up", "alte_landstrasse_eb"):
            rd = roads[rid]
            band_mask = np.zeros((OVERVIEW_H, OVERVIEW_W), dtype=bool)
            for p in rd["pts"][::2]:
                cx = int(round(p[0] * (OVERVIEW_W - 1)))
                cy = int(round(p[1] * (OVERVIEW_H - 1)))
                y0, y1 = max(0, cy - 6), min(OVERVIEW_H, cy + 7)
                x0, x1 = max(0, cx - 6), min(OVERVIEW_W, cx + 7)
                band_mask[y0:y1, x0:x1] = True
            street_warm = float(np.mean(warm[band_mask]))
            self.assertGreaterEqual(
                street_warm,
                0.005,
                f"Night warm streetlamp pool fraction along {rid} is {street_warm * 100:.3f}% < 0.50% (F7)",
            )

    @test_meta("T2.FA1.09", "Guardrail #4: Lindt HoC id=1443 25cm roof texture variance/entropy")
    def test_09_lindt_25cm_roof_texture(self) -> None:
        # Dynamically derive Lindt HoC (id=1443) tile (col, row) and local (tx, ty) from interactive metadata
        inter = load_interactive_json()
        lindt = next((b for b in inter.get("buildings", []) if b.get("id") == LINDT_HOC_ID), None)
        self.assertIsNotNone(lindt, f"Lindt HoC building id={LINDT_HOC_ID} missing from kilchberg_interactive.json")
        manifest = load_manifest("day")
        tile_sz = int(manifest.get("tileSize", 1024))
        px = float(lindt["u"]) * CANVAS_W
        py = float(lindt["v"]) * CANVAS_H
        col = int(px // tile_sz)
        row = int(py // tile_sz)
        tile = load_tile_rgb("day", col, row)
        th, tw = tile.shape[:2]
        tx = max(32, min(tw - 32, int(round(px - col * tile_sz))))
        ty = max(32, min(th - 32, int(round(py - row * tile_sz))))
        patch = tile[ty - 32 : ty + 32, tx - 32 : tx + 32, :]
        luma = rec709_luma(patch)
        std_l = float(np.std(luma))
        ent = entropy_32b(luma)
        packed = (
            (patch[..., 0].astype(np.uint32) << 16)
            | (patch[..., 1].astype(np.uint32) << 8)
            | patch[..., 2].astype(np.uint32)
        )
        uniq = int(np.unique(packed).size)
        self.assertGreaterEqual(std_l, 18.0, f"Lindt tile ({col},{row}) roof std_luma={std_l:.2f} < 18.0")
        self.assertGreaterEqual(ent, 1.8, f"Lindt tile ({col},{row}) roof entropy={ent:.2f} < 1.8")
        self.assertGreaterEqual(uniq, 12, f"Lindt tile ({col},{row}) roof uniq_colors={uniq} < 12")

        # Detail plate 01 center 160x160 patch
        plate = load_plate_rgb("01_lindt_home_of_chocolate.webp")
        cy, cx = plate.shape[0] // 2, plate.shape[1] // 2
        pp = plate[cy - 80 : cy + 80, cx - 80 : cx + 80, :]
        p_luma = rec709_luma(pp)
        self.assertGreaterEqual(float(np.std(p_luma)), 25.0, "Plate 01 Lindt center std_luma < 25.0")
        self.assertGreaterEqual(entropy_32b(p_luma), 2.8, "Plate 01 Lindt center entropy < 2.8")


class TestTier2FA2GeospatialBounds(unittest.TestCase):
    """FA2 Boundary & Corner Cases: Road Kinks, Occlusion, Edge-to-Edge, Geometry Bounds."""

    @test_meta("T2.FA2.01", "Zero road kinks > 45 deg in pixel space across all 8 roads")
    def test_01_zero_road_kinks(self) -> None:
        roads = {rd["id"]: rd for rd in load_animations_json().get("roads", [])}
        violations = []
        for rid in REQUIRED_ROAD_IDS:
            max_ang, gt45, gt90 = pixel_turn_angles_deg(roads[rid]["pts"], CANVAS_W, CANVAS_H)
            if gt45 > 0 or max_ang > 45.0:
                violations.append(f"{rid} (max={max_ang:.1f} deg, >45={gt45}, >90={gt90})")
        self.assertEqual(
            violations,
            [],
            f"Road kinks > 45 deg detected in pixel space (F16): {'; '.join(violations)}",
        )

    @test_meta("T2.FA2.02", "Full occlusion computed on all 8 roads (incl. Alte Landstrasse)")
    def test_02_all_roads_have_occlusion(self) -> None:
        roads = {rd["id"]: rd for rd in load_animations_json().get("roads", [])}
        zero_occ = []
        for rid in REQUIRED_ROAD_IDS:
            occ_cnt = sum(1 for p in roads[rid]["pts"] if len(p) >= 3 and p[2])
            if occ_cnt == 0:
                zero_occ.append(rid)
        self.assertEqual(
            zero_occ,
            [],
            f"Roads missing depth occlusion computation (occ==0; F15): {', '.join(zero_occ)}",
        )

    @test_meta("T2.FA2.03", "Edge-to-edge road endpoints within cutaway/back-edge distance bounds")
    def test_03_edge_to_edge_endpoints(self) -> None:
        roads = {rd["id"]: rd for rd in load_animations_json().get("roads", [])}
        bad = []
        for rid in REQUIRED_ROAD_IDS:
            pts = roads[rid]["pts"]
            d_start = distance_to_exterior_sky_m(pts[0][0], pts[0][1])
            d_end = distance_to_exterior_sky_m(pts[-1][0], pts[-1][1])
            if d_start > 150.0 or d_end > 150.0:
                bad.append(f"{rid} (start={d_start:.1f}m, end={d_end:.1f}m > 150m)")
            if min(d_start, d_end) > 35.0:
                bad.append(f"{rid} (min_edge={min(d_start, d_end):.1f}m > 35m back-edge)")
        self.assertEqual(bad, [], f"Roads not truly edge-to-edge (Guardrail #3): {'; '.join(bad)}")

    @test_meta("T2.FA2.04", "All buildings satisfy valid elevation, UV & Kilchberg LV95 bounds")
    def test_04_building_geometry_bounds(self) -> None:
        bldgs = load_interactive_json().get("buildings", [])
        self.assertGreaterEqual(len(bldgs), 1850)
        bad = []
        for b in bldgs:
            zg = float(b["zg"])
            zr = float(b["zr"])
            h = float(b["h"])
            u = float(b["u"])
            v = float(b["v"])
            e = float(b["e"])
            n = float(b["n"])
            if not (zg <= zr + 0.1 and h >= 0.0):
                bad.append(f"id={b['id']} bad elev zg={zg}, zr={zr}, h={h}")
            elif not (0.02 <= u <= 0.98 and 0.02 <= v <= 0.95):
                bad.append(f"id={b['id']} bad UV ({u:.4f},{v:.4f})")
            elif not (2682000.0 <= e <= 2686000.0 and 1240000.0 <= n <= 1244500.0):
                bad.append(f"id={b['id']} bad LV95 ({e},{n})")
            if len(bad) >= 5:
                break
        self.assertEqual(bad, [], f"Invalid building geometry bounds: {'; '.join(bad)}")

    @test_meta("T2.FA2.05", "All train, road & ship paths stay in [0,1] UV with valid non-spiking d16")
    def test_05_ship_train_uv_and_depth_bounds(self) -> None:
        anim = load_animations_json()
        for group_name in ("trains", "roads", "ships"):
            items = anim.get(group_name, [])
            self.assertGreater(len(items), 0, f"Animation group '{group_name}' is empty")
            for item in items:
                pts = item.get("pts", [])
                self.assertGreater(len(pts), 20, f"{group_name}/{item['id']} too short")
                prev_d16 = None
                for i, p in enumerate(pts):
                    self.assertGreaterEqual(
                        len(p),
                        4,
                        f"{group_name}/{item['id']}[{i}] missing [u, v, occ, d16] 4-tuple (len={len(p)})",
                    )
                    u, v = float(p[0]), float(p[1])
                    self.assertTrue(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0, f"{item['id']}[{i}] UV out of [0,1]")
                    d16 = float(p[3])
                    self.assertTrue(
                        math.isfinite(d16) and 1.0 <= d16 <= 65534.0,
                        f"{group_name}/{item['id']}[{i}] bad d16={d16}",
                    )
                    if prev_d16 is not None and not item.get("closed"):
                        self.assertLess(
                            abs(d16 - prev_d16),
                            8000.0,
                            f"{group_name}/{item['id']}[{i}] abrupt d16 spike {prev_d16}->{d16} (Guardrail #6)",
                        )
                    prev_d16 = d16

    @test_meta("T2.FA2.06", "Landmarks inside diorama island & realistic vessel speed bounds")
    def test_06_landmarks_inside_island_and_boat_speeds(self) -> None:
        island_2x = get_day_island_and_exterior_masks()["island_2x"]
        h2, w2 = island_2x.shape
        for lm in load_interactive_json().get("landmarks", []):
            u, v = get_landmark_uv(lm)
            x2 = int(round(u * (w2 - 1)))
            y2 = int(round(v * (h2 - 1)))
            self.assertTrue(
                bool(island_2x[y2, x2]),
                f"Landmark {lm['id']} UV ({u:.4f}, {v:.4f}) falls outside diorama island mask",
            )

        for ship in load_animations_json().get("ships", []):
            spd = float(ship.get("speed_mps", 0))
            kind = str(ship.get("kind", ""))
            if "sail" in kind or "sail" in ship.get("id", ""):
                self.assertTrue(1.0 <= spd <= 5.0, f"{ship['id']} sailboat speed {spd} m/s unrealistic")
            elif kind == "zsg_steamer":
                self.assertTrue(4.0 <= spd <= 10.0, f"{ship['id']} steamer speed {spd} m/s unrealistic")
            elif any(k in kind.lower() or k in str(ship.get("id", "")).lower() for k in ("sup", "paddle", "rowboat", "skiff")):
                self.assertTrue(0.5 <= spd <= 2.5, f"{ship['id']} slow watercraft speed {spd} m/s unrealistic (Guardrail #2)")
            else:
                self.assertTrue(1.0 <= spd <= 12.0, f"{ship['id']} speed {spd} m/s unrealistic")

    @test_meta("T2.FA2.07", "Network graph UV [0,1], non-spiking d16, island & zero water intrusion")
    def test_07_network_dem_and_zero_water_intrusion(self) -> None:
        anim = load_animations_json()
        net = anim.get("network")
        self.assertIsInstance(
            net,
            dict,
            "kilchberg_animations.json missing 'network' object (v8.0 Contract #2)",
        )

        island_2x = get_day_island_and_exterior_masks()["island_2x"]
        lake_eroded_2x = get_lake_zurich_mask_2x()["lake_eroded_2x"]
        h2, w2 = island_2x.shape

        violations: list[str] = []

        def _check_pt(label: str, u: float, v: float, d16: float) -> None:
            if len(violations) >= 10:
                return
            if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
                violations.append(f"{label}: UV ({u:.4f}, {v:.4f}) out of [0,1]")
                return
            if not (math.isfinite(d16) and 1.0 <= d16 <= 65534.0):
                violations.append(f"{label}: invalid d16={d16}")
                return
            x2 = int(round(u * (w2 - 1)))
            y2 = int(round(v * (h2 - 1)))
            if not bool(island_2x[y2, x2]):
                violations.append(f"{label}: UV ({u:.4f}, {v:.4f}) falls outside diorama island mask")
                return
            if bool(lake_eroded_2x[y2, x2]):
                violations.append(f"{label}: UV ({u:.4f}, {v:.4f}) intrudes into Lake Zurich water mask")

        for col in ("crosswalks", "junctions", "pois", "extra_sports"):
            for item in net.get(col, []):
                if len(violations) >= 10:
                    break
                _check_pt(
                    f"{col}/{item.get('id', '?')}",
                    float(item["u"]),
                    float(item["v"]),
                    float(item["d16"]),
                )

        for col in ("feeders", "footpaths"):
            for item in net.get(col, []):
                if len(violations) >= 10:
                    break
                pts = item.get("pts", [])
                self.assertGreaterEqual(len(pts), 2, f"{col}/{item.get('id', '?')} has <2 vertices")
                prev_d16 = None
                for i, p in enumerate(pts):
                    if len(violations) >= 10:
                        break
                    u, v, d16 = float(p[0]), float(p[1]), float(p[3])
                    _check_pt(f"{col}/{item.get('id', '?')}[{i}]", u, v, d16)
                    if prev_d16 is not None and abs(d16 - prev_d16) >= 8000.0:
                        violations.append(
                            f"{col}/{item.get('id', '?')}[{i}]: abrupt d16 spike {prev_d16}->{d16}"
                        )
                    prev_d16 = d16

        self.assertEqual(
            violations,
            [],
            f"Network graph DEM/water/UV violations: {'; '.join(violations)}",
        )


if __name__ == "__main__":
    result_json, verbose = parse_cli_args_for_module(sys.argv[1:])
    sys.exit(
        run_unittest_module(
            sys.modules[__name__],
            tier=2,
            suite_name="tier2_quality_bounds",
            result_json_path=result_json,
            verbose=verbose,
        )
    )
