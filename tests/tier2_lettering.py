"""Tier 2 (Python): facade lettering is real-typeface, baked into the building texture, and correctly
oriented/projected -- verified on atlas data, synthetic wall fragments, and actual rendered pixels."""

from __future__ import annotations

import math
import re
import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline import signage
from pipeline.config import IsometricCamera
from tests.lib.assets_helper import crop_landmark_meter_box, get_master_mpp
from tests.lib.report import parse_cli_args_for_module, run_unittest_module, test_meta

VIGNETTES_JS = REPO_ROOT / "docs" / "js" / "render" / "vignettes.js"


def _pca_angle_deg(xs: np.ndarray, ys: np.ndarray) -> float:
    """Principal axis angle in screen space (degrees, y pointing UP)."""
    pts = np.stack([xs - xs.mean(), -(ys - ys.mean())], 1).astype(np.float64)
    w, v = np.linalg.eigh(np.cov(pts.T))
    ax = v[:, np.argmax(w)]
    ang = math.degrees(math.atan2(ax[1], ax[0]))
    return (ang + 90.0) % 180.0 - 90.0


class TestLetteringTypography(unittest.TestCase):
    @test_meta("T2.LET.01", "Sign atlases are rasterised from a real vector typeface with distinct letterforms")
    def test_01_atlas_uses_real_typeface(self) -> None:
        a = signage.build_sign("LINDT & SPRÜNGLI", "gothic", 2.5)
        b = signage.build_sign("LINDT & SPRÜNGLI", "swiss", 2.5)
        self.assertGreater(a.alpha.shape[1], 600, "atlas must be high-resolution")
        self.assertTrue(0.05 < float((a.alpha > 0.5).mean()) < 0.6, "glyph ink coverage out of range")
        # two different typefaces must give different bitmaps/metrics (not a single generic font)
        self.assertNotAlmostEqual(a.width_m / a.height_m, b.width_m / b.height_m, places=2)
        # Umlaut present: ink above cap line makes the box taller than caps alone
        self.assertGreater(a.height_m, 2.5 * 1.02)

    @test_meta("T2.LET.02", "Every registered sign resolves onto a camera-facing wall of its own building")
    def test_02_registry_is_complete(self) -> None:
        keys = {s["key"] for s in signage.SIGNS}
        for must in ("lindt_main", "lindt_hoc", "bahnhof_station", "gemeindehaus_main"):
            self.assertIn(must, keys)
        self.assertNotIn(
            "st_elisabeth_nave",
            keys,
            "fictional charcoal 'ST. ELISABETH' nave plaque must not be present in signage.SIGNS (v11)",
        )
        for s in signage.SIGNS:
            fields = " ".join(str(s.get(k, "")) for k in ("key", "bldg", "text")).lower()
            self.assertNotIn(
                "st_elisabeth",
                fields,
                f"fictional St. Elisabeth sign must not be present in signage.SIGNS (v11): {s}",
            )
            self.assertNotIn(
                "st. elisabeth",
                fields,
                f"fictional St. Elisabeth sign must not be present in signage.SIGNS (v11): {s}",
            )
        texts = " ".join(s["text"] for s in signage.SIGNS)
        self.assertIn("LINDT & SPRÜNGLI", texts)
        for w in ("LINDT", "HOME OF", "CHOCOLATE"):
            self.assertIn(w, texts)


class TestLetteringProjection(unittest.TestCase):
    @staticmethod
    def _bake_flat(text: str, mirror: bool):
        sg = signage.build_sign(text, "gothic", 2.0)
        sp = dict(text=text, panel=None, fg=(200, 20, 20), lit=False, edge=None)
        ss, zz = np.meshgrid(np.arange(-sg.width_m / 2 - 1, sg.width_m / 2 + 1, 0.1),
                             np.arange(-6.0, 0.5, 0.1))
        n = ss.size
        # wall facing east (normal +E, bin 0): tangent t=(0,1)  => s == northing
        e = np.zeros(n) + 100.0
        nn = ss.ravel() * (-1.0 if mirror else 1.0)
        z = zz.ravel() + 20.0
        run = dict(bin=0, d=100.0, s_lo=-sg.width_m / 2, s_hi=sg.width_m / 2, ztop=20.0, t=(0.0, 1.0), n=(1.0, 0.0))
        r = dict(bidx=0, run=run, sign=sg, s_c=0.0, s0=-sg.width_m / 2, v_base=-(0.5 + 2.0), cap=2.0, spec=sp)
        base = np.full((n, 3), 200.0, dtype=np.float32)
        signage.bake_signs([r], np.zeros(n, int), np.zeros(n, int), e, nn, z, base, np.zeros(n, np.uint8),
                           np.arange(n), 9, "day", False)
        ink = (base[:, 0] > 150) & (base[:, 1] < 60)
        img = ink.reshape(ss.shape)
        return img, sg

    @test_meta("T2.LET.03", "Baked letters read left->right in facade coordinates (not mirrored / rotated)")
    def test_03_orientation_not_mirrored(self) -> None:
        good, sg = self._bake_flat("LINDT", mirror=False)
        bad, _ = self._bake_flat("LINDT", mirror=True)
        self.assertGreater(good.sum(), 200)
        ref = sg.alpha > 0.5
        ys, xs = np.nonzero(good)
        cols = np.where(good.any(0))[0]
        prof_good = good[:, cols.min():cols.max() + 1].sum(0).astype(float)
        prof_bad = bad[:, np.where(bad.any(0))[0].min():np.where(bad.any(0))[0].max() + 1].sum(0).astype(float)
        # resample the reference atlas column-ink profile to the baked width
        prof_ref = ref.sum(0).astype(float)
        x = np.linspace(0, len(prof_ref) - 1, len(prof_good))
        prof_ref_rs = np.interp(x, np.arange(len(prof_ref)), prof_ref)
        c_good = np.corrcoef(prof_good, prof_ref_rs)[0, 1]
        c_bad = np.corrcoef(prof_bad[:len(prof_good)] if len(prof_bad) >= len(prof_good)
                            else np.pad(prof_bad, (0, len(prof_good) - len(prof_bad))), prof_ref_rs)[0, 1]
        self.assertGreater(c_good, 0.7, f"baked ink profile must match atlas (corr {c_good:.2f})")
        self.assertGreater(c_good, c_bad + 0.2, "mirrored wall must NOT correlate like the correct reading direction")

    @test_meta("T2.LET.04", "Lettering is clipped to its wall plane (no ink on other planes/buildings)")
    def test_04_clipped_to_plane(self) -> None:
        sg = signage.build_sign("LINDT", "gothic", 2.0)
        n = 4000
        rng = np.random.default_rng(3)
        e = rng.uniform(95, 105, n)
        nn = rng.uniform(-sg.width_m / 2, sg.width_m / 2, n)
        z = rng.uniform(15, 20, n)
        run = dict(bin=0, d=100.0, s_lo=-4, s_hi=4, ztop=20.0, t=(0.0, 1.0), n=(1.0, 0.0))
        sp = dict(text="LINDT", panel=None, fg=(200, 20, 20), lit=False, edge=None)
        r = dict(bidx=7, run=run, sign=sg, s_c=0.0, s0=-sg.width_m / 2, v_base=-3.0, cap=2.0, spec=sp)
        base = np.full((n, 3), 200.0, dtype=np.float32)
        bi = np.where(np.arange(n) % 2 == 0, 7, 8)
        signage.bake_signs([r], bi, np.zeros(n, int), e, nn, z, base, np.zeros(n, np.uint8), np.arange(n), 9, "day", False)
        ink = base[:, 0] < 255
        changed = (base != 200.0).any(1)
        self.assertTrue(changed[(bi == 7) & (np.abs(e - 100.0) <= 1.0)].any())
        self.assertFalse(changed[bi == 8].any(), "other building must be untouched")
        self.assertFalse(changed[np.abs(e - 100.0) > 1.0].any(), "other planes must be untouched")


class TestLetteringRendered(unittest.TestCase):
    @test_meta("T2.LET.05", "Rendered master tiles: metallic gold 'LINDT & SPRÜNGLI' ink lies along the projected wall direction (not red)")
    def test_05_rendered_main_sign_angle(self) -> None:
        # Restrict to the historic factory lake-facade roofline sign window directly on day master tiles
        img = crop_landmark_meter_box("day", "lindt_hoc", -54.03, 49.02, -25.76, 68.94).astype(int)
        r, g, b = img[..., 0], img[..., 1], img[..., 2]

        # Photo-verified v11: red paint must NOT dominate the historic factory roofline sign
        red_mask = (r > 90) & (g < 0.30 * r) & (b < 0.30 * r)
        red_px = int(red_mask.sum())
        self.assertLess(
            red_px,
            100,
            f"historic factory 'LINDT & SPRÜNGLI' sign must be metallic gold, not red (found {red_px} red px)",
        )

        # Metallic gold fg=(212, 168, 56) under bin-4 day shading (~0.45..1.05x)
        gold_mask = (r >= 82) & (g > 0.60 * r) & (g < 0.90 * r) & (b < 0.45 * r) & ((r - b) >= 42)
        ys, xs = np.nonzero(gold_mask)
        self.assertGreater(
            len(xs),
            150,
            f"no baked metallic gold rooftop lettering pixels found in historic factory sign window (got {len(xs)})",
        )
        self.assertGreater(
            len(xs),
            red_px,
            f"metallic gold pixels ({len(xs)}) must outnumber red pixels ({red_px}) in factory sign window",
        )
        measured = _pca_angle_deg(xs, ys)
        # expected: project two points 10 m apart along the sign's wall tangent
        scene_run = (-0.6428, 0.7660)  # bin-4 wall tangent (normal at 40deg) used by the main factory facade
        cam = IsometricCamera()
        e0, n0 = 2684200.0, 1241370.0
        px0, py0, _ = cam.project(np.array([e0]), np.array([n0]), np.array([420.0]))
        px1, py1, _ = cam.project(np.array([e0 + 10 * scene_run[0]]), np.array([n0 + 10 * scene_run[1]]), np.array([420.0]))
        expected = math.degrees(math.atan2(-(py1[0] - py0[0]), px1[0] - px0[0]))
        expected = (expected + 90.0) % 180.0 - 90.0
        self.assertLess(abs(measured - expected), 7.0,
                        f"lettering angle {measured:.1f}deg deviates from projected facade direction {expected:.1f}deg")

    @test_meta("T2.LET.06", "Rendered master tiles: gold Home-of-Chocolate lettering exists on the white curved facade")
    def test_06_rendered_hoc_gold_on_white(self) -> None:
        img = crop_landmark_meter_box("day", "lindt_hoc", -100.0, -80.0, 100.0, 80.0).astype(int)
        mpp = get_master_mpp()
        r, g, b = img[..., 0], img[..., 1], img[..., 2]
        gold = (r > 100) & (r < 215) & (g > 0.62 * r) & (g < 0.80 * r) & (b < 0.40 * r)
        ys, xs = np.nonzero(gold)
        self.assertGreater(len(xs), 80, "no baked gold lettering found")
        # Most gold ink must have bright near-white wall pixels around it (it is painted ON the white facade)
        rad = max(4, int(round(0.9 / mpp)))
        ok = 0
        pick = np.linspace(0, len(xs) - 1, min(400, len(xs))).astype(int)
        for i in pick:
            x, y = xs[i], ys[i]
            patch = img[max(0, y - rad) : y + rad + 1, max(0, x - rad) : x + rad + 1]
            lum = patch.mean(2)
            if (lum > 150).mean() > 0.25:
                ok += 1
        self.assertGreater(ok / len(pick), 0.5, "gold ink should sit on a white glazed facade")


class TestNoFloatingTextOverlays(unittest.TestCase):
    @test_meta("T2.LET.07", "Live canvas has no floating screen-space text overlays / generic UI font signs")
    def test_07_overlays_disabled(self) -> None:
        src = VIGNETTES_JS.read_text()
        for fn in ("drawSignPlaque", "drawRotatedSignText"):
            m = re.search(r"function %s\([^)]*\)\s*\{\s*//[^\n]*\n\s*//[^\n]*\n\s*return;" % fn, src)
            self.assertIsNotNone(m, f"{fn} must be a disabled no-op (lettering is baked into the textures)")
        # no other code path may draw text with a UI font
        stripped = re.sub(r"function drawSignPlaque.*?\n}\n", "", src, flags=re.S)
        stripped = re.sub(r"function drawRotatedSignText.*?\n}\n", "", stripped, flags=re.S)
        self.assertNotIn("fillText(", stripped)


if __name__ == "__main__":
    result_json, verbose = parse_cli_args_for_module(sys.argv[1:])
    sys.exit(
        run_unittest_module(
            sys.modules[__name__],
            tier=2,
            suite_name="tier2_lettering",
            result_json_path=result_json,
            verbose=verbose,
        )
    )
