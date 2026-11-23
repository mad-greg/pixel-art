"""Tier 2 (Python): v13.1 Bridge/Road Junction Continuity, Parapet Seam & Depth-Occlusion Guards (T2.V13_1.B01–B03)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.verify_quality import (
    MAX_BRIDGE_SEAM_CC,
    MAX_BRIDGE_SEAM_PX,
    measure_parapet_white_seam,
    measure_road_centerline_barriers,
)
from tests.lib.assets_helper import (
    DATA_DIR,
    DOCS_DIR,
    TILES_DIR,
    load_manifest,
    load_tile_rgb,
    rec709_luma,
)
from tests.lib.report import parse_cli_args_for_module, run_unittest_module, test_meta

BRIDGE_L2_TILES = (
    (12, 6),  # Dorfstrasse viaduct upper SW T-junction
    (13, 6),  # Dorfstrasse viaduct lower ramp
    (10, 1),  # Gruetstrasse viaduct
    (6, 2),   # Foehrenweg A3 overpass
    (1, 4),   # A3 motorway south / Gheistrasse underpass
    (1, 5),   # A3 motorway south
    (15, 5),  # Bahnhof footbridge & stairs
    (11, 7),  # Dammweg SBB rail bridge
    (19, 4),  # Paradiesstrasse SBB rail bridge
    (24, 2),  # Grenzsteig SBB rail bridge
    (24, 3),  # Grenzsteig SBB rail bridge
)


def _load_animations_json() -> dict:
    p = DATA_DIR / "kilchberg_animations.json"
    if not p.is_file():
        raise FileNotFoundError(f"Missing animations JSON: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


class TestTier2V131Bridges(unittest.TestCase):
    """v13.1 systemic road/bridge/parapet/cliff regression guards (zero scene-cache dependency)."""

    @test_meta("T2.V13_1.B01", "Bridge/viaduct roadway continuity & zero transverse blocking walls")
    def test_01_bridge_roadway_continuity_no_blocking_walls(self) -> None:
        mf = load_manifest("day")
        W, H, ts = int(mf["width"]), int(mf["height"]), int(mf["tileSize"])
        anim = _load_animations_json()
        roads_by_id = {r["id"]: r["pts"] for r in anim.get("roads", [])}

        # Confirm all bridge L2 tiles exist and are non-empty
        for tx, ty in BRIDGE_L2_TILES:
            tp = TILES_DIR / "day" / f"{tx}_{ty}.webp"
            self.assertTrue(tp.is_file(), f"Missing bridge L2 tile day/{tx}_{ty}.webp")
            self.assertGreater(tp.stat().st_size, 1024, f"Bridge L2 tile day/{tx}_{ty}.webp unexpectedly tiny")

        # Check Dorfstrasse viaduct upper SW T-junction (tile 12_6) for transverse blocking walls/cliffs
        t12_6 = load_tile_rgb("day", 12, 6)
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
        self.assertEqual(
            len(barriers),
            0,
            f"Transverse blocking wall/cliff detected across Dorfstrasse viaduct T-junction (day/12_6.webp): {barriers}",
        )

    @test_meta("T2.V13_1.B02", "Zero jagged white inner-parapet seam streaks & diurnal consistency on bridge tiles")
    def test_02_zero_parapet_white_seam_streaks(self) -> None:
        t12_6_day = load_tile_rgb("day", 12, 6)
        roi_day = t12_6_day[390:470, 690:790]
        seam_px, max_cc, total_nw = measure_parapet_white_seam(roi_day)
        self.assertLess(
            seam_px,
            MAX_BRIDGE_SEAM_PX,
            f"Jagged white inner-parapet seam on day/12_6.webp T-junction ROI: seam_px={seam_px} (>= {MAX_BRIDGE_SEAM_PX}, nw={total_nw})",
        )
        self.assertLess(
            max_cc,
            MAX_BRIDGE_SEAM_CC,
            f"Long continuous white inner-parapet ribbon on day/12_6.webp: max_cc={max_cc} (>= {MAX_BRIDGE_SEAM_CC})",
        )

        # Diurnal tonal sanity on sunset & night 12_6.webp
        t12_6_sun = load_tile_rgb("sunset", 12, 6)[390:470, 690:790].astype(np.float32)
        self.assertGreater(
            float(t12_6_sun[:, :, 0].mean()),
            float(t12_6_sun[:, :, 2].mean()) - 8.0,
            "Sunset bridge junction tile 12_6 unexpectedly cold/blue",
        )
        t12_6_ngt = load_tile_rgb("night", 12, 6)[390:470, 690:790]
        ngt_luma = float(rec709_luma(t12_6_ngt).mean())
        self.assertLess(
            ngt_luma,
            95.0,
            f"Night bridge junction tile 12_6 too bright: mean_luma={ngt_luma:.1f}",
        )

    @test_meta("T2.V13_1.B03", "Live vehicle depth-occlusion sanity on Dorfstrasse viaduct T-junction & deck")
    def test_03_bridge_depth_occlusion_sanity(self) -> None:
        depth_p = DOCS_DIR / "assets" / "kilchberg_depth.png"
        self.assertTrue(depth_p.is_file(), f"Missing depth map {depth_p}")
        d_arr = np.asarray(Image.open(depth_p))
        dh, dw = d_arr.shape[:2]
        anim = _load_animations_json()
        roads_by_id = {r["id"]: r["pts"] for r in anim.get("roads", [])}

        # Check Dorfstrasse viaduct T-junction & upper deck samples (occ == 0) have no blocking occluder in front
        unexpected_occ: list[tuple[str, int, int, int]] = []
        windows = (
            ("dorfstrasse_viaduct_dn", 785, 805),
            ("dorfstrasse_viaduct_up", 575, 595),
        )
        for pname, lo, hi in windows:
            pts = roads_by_id.get(pname, [])
            for i in range(max(0, lo), min(len(pts), hi)):
                u, v, occ, d16 = float(pts[i][0]), float(pts[i][1]), int(pts[i][2]), int(pts[i][3])
                if occ:
                    continue
                dx = int(np.clip(round(u * dw), 0, dw - 1))
                dy = int(np.clip(round(v * dh), 0, dh - 1))
                r_ch, g_ch, b_ch = int(d_arr[dy, dx, 0]), int(d_arr[dy, dx, 1]), int(d_arr[dy, dx, 2])
                if b_ch == 255:
                    scene_d16 = (r_ch << 8) | g_ch
                    # Vehicle d16 > scene_d16 + 20 means an occluder sits significantly in front of the car
                    if d16 > scene_d16 + 20:
                        unexpected_occ.append((pname, i, d16, scene_d16))

        self.assertEqual(
            len(unexpected_occ),
            0,
            f"Unexpected blocking depth occluders along Dorfstrasse viaduct T-junction: {unexpected_occ}",
        )


if __name__ == "__main__":
    result_json, verbose = parse_cli_args_for_module(sys.argv[1:])
    sys.exit(
        run_unittest_module(
            sys.modules[__name__],
            tier=2,
            suite_name="tier2_v13_1_bridges",
            result_json_path=result_json,
            verbose=verbose,
        )
    )
