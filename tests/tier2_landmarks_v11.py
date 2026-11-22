"""Tier 2 (Python): v11 photo-verified landmark photo-realism regression tests (T2.LM.01–T2.LM.05)."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from typing import Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline import config, signage
from tests.lib.assets_helper import ALL_LANDMARK_IDS_V9, crop_landmark_meter_box
from tests.lib.report import parse_cli_args_for_module, run_unittest_module, test_meta

VIGNETTES_JS = REPO_ROOT / "docs" / "js" / "render" / "vignettes.js"


def _strip_js_comments(src: str) -> str:
    """Strip /* ... */ and // ... comments from JS source for clean call inspection."""
    no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", no_block)


def _extract_balanced_block(src: str, start_idx: int) -> str:
    """Extract a brace-balanced {...} block starting at or after start_idx, skipping JS strings and comments."""
    n = len(src)
    open_idx = -1
    depth = 0
    in_str: str | None = None
    in_line_comment = False
    in_block_comment = False
    esc = False
    i = start_idx
    while i < n:
        ch = src[i]
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and i + 1 < n and src[i + 1] == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_str is not None:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
            i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in ("'", '"', "`"):
            in_str = ch
        elif ch == "{":
            if depth == 0:
                open_idx = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and open_idx >= 0:
                    return src[open_idx : i + 1]
        i += 1
    return ""


def _extract_call_args(src: str, fn_name: str) -> list[str]:
    """Extract balanced argument strings for every call to fn_name(...) in comment-stripped JS code."""
    calls: list[str] = []
    n = len(src)
    for m in re.finditer(rf"\b{re.escape(fn_name)}\s*\(", src):
        open_idx = m.end() - 1
        depth = 0
        in_str: str | None = None
        esc = False
        for i in range(open_idx, n):
            ch = src[i]
            if in_str is not None:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == in_str:
                    in_str = None
                continue
            if ch in ("'", '"', "`"):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    calls.append(src[open_idx + 1 : i])
                    break
    return calls


def _clock_entry_matches(entry: dict, targets: Iterable[str]) -> list[str]:
    """Return any target IDs/stems referenced by a signage.CLOCKS entry (case-insensitive)."""
    found: list[str] = []
    str_vals = [str(v).lower() for v in entry.values() if isinstance(v, str)]
    bldg_or_key = {str(entry.get("key", "")).lower(), str(entry.get("bldg", "")).lower()}
    for t in targets:
        tl = t.lower()
        if tl in bldg_or_key or any(tl in sv for sv in str_vals):
            found.append(t)
    return found


class TestLandmarksV11PhotoRealism(unittest.TestCase):
    @test_meta("T2.LM.01", "St. Elisabeth has zero clocks in signage.CLOCKS and zero live clock in vignettes.js")
    def test_01_st_elisabeth_no_clocks(self) -> None:
        # 1. Zero clocks in pipeline/signage.py CLOCKS
        bad_clocks = [
            c for c in signage.CLOCKS
            if _clock_entry_matches(c, ("st_elisabeth_twr", "st_elisabeth"))
        ]
        self.assertEqual(
            bad_clocks,
            [],
            f"St. Elisabeth must have ZERO entries in signage.CLOCKS (found {bad_clocks})",
        )

        # 2. Zero live clock in docs/js/render/vignettes.js St. Elisabeth vignette block
        src = VIGNETTES_JS.read_text(encoding="utf-8")
        anchor = re.search(r"//\s*8a\.\s*Katholische Kirche St\.\s*Elisabeth", src)
        self.assertIsNotNone(anchor, "Could not locate St. Elisabeth (8a) vignette block in vignettes.js")
        block = _extract_balanced_block(src, anchor.end())
        self.assertTrue(block and "st_elisabeth" in block, "Failed to extract balanced St. Elisabeth vignette block")
        code_only = _strip_js_comments(block)
        clock_calls = re.findall(r"\bdrawSwissClockDial\s*\(", code_only)
        self.assertEqual(
            len(clock_calls),
            0,
            f"St. Elisabeth vignette block in vignettes.js must have ZERO drawSwissClockDial calls (found {len(clock_calls)})",
        )

    @test_meta("T2.LM.02", "Gemeindehaus has zero clocks in signage.CLOCKS and zero duplicate rooftop flag in vignettes.js")
    def test_02_gemeindehaus_no_clock_and_no_duplicate_flag(self) -> None:
        # 1. Zero clocks in pipeline/signage.py CLOCKS
        bad_clocks = [
            c for c in signage.CLOCKS
            if _clock_entry_matches(c, ("gemeindehaus_main", "gemeindehaus"))
        ]
        self.assertEqual(
            bad_clocks,
            [],
            f"Gemeindehaus must have ZERO entries in signage.CLOCKS (found {bad_clocks})",
        )

        src = VIGNETTES_JS.read_text(encoding="utf-8")

        # 2. Verify fIdx === 3 is skipped in drawAmbientEffects (no duplicate rooftop flag pair)
        amb_match = re.search(r"export\s+function\s+drawAmbientEffects\s*\(", src)
        self.assertIsNotNone(amb_match, "Could not locate drawAmbientEffects in vignettes.js")
        amb_block = _extract_balanced_block(src, amb_match.end())
        self.assertTrue(amb_block, "Failed to extract balanced drawAmbientEffects body")
        amb_code = _strip_js_comments(amb_block)

        self.assertIsNotNone(
            re.search(r"if\s*\(\s*fIdx\s*===\s*3\s*\)\s*\{?\s*continue\s*;?\s*\}?", amb_code),
            "drawAmbientEffects must skip duplicate rooftop anchor fIdx === 3 via 'if (fIdx === 3) continue;'",
        )
        # Ensure legacy rooftop fIdx === 3 kilchberg flag draw is gone
        self.assertIsNone(
            re.search(r"if\s*\(\s*fIdx\s*===\s*3\s*\)\s*\{[^}]*drawSwissOrMuniFlag", amb_code, flags=re.S),
            "Legacy duplicate rooftop flag draw for fIdx === 3 must be removed from drawAmbientEffects",
        )

        # 3. Preserve the 4-petal white-flower Kilchberg municipal flag renderer in drawSwissOrMuniFlag (comment-stripped)
        flag_fn_match = re.search(r"function\s+drawSwissOrMuniFlag\s*\(", src)
        self.assertIsNotNone(flag_fn_match, "Could not locate drawSwissOrMuniFlag in vignettes.js")
        flag_fn_block = _extract_balanced_block(src, flag_fn_match.end())
        flag_code = _strip_js_comments(flag_fn_block)
        self.assertRegex(
            flag_code,
            r"kind\s*===\s*['\"]kilchberg['\"]",
            "Active 'kilchberg' branch in drawSwissOrMuniFlag must be preserved",
        )
        self.assertIn("petalDist", flag_code, "4-petal white-flower Kilchberg municipal flag renderer must be preserved")
        self.assertIn("kGold", flag_code, "Gold flower center in Kilchberg municipal flag renderer must be preserved")
        self.assertIn("ctx.arc(", flag_code, "Circular petal/center ctx.arc() drawing in drawSwissOrMuniFlag must be preserved")

        # 4. Preserve the ground forecourt Swiss + Kilchberg flag pair & verify ZERO live Gemeindehaus clock in block 8e
        gh_anchor = re.search(r"//\s*8e\.\s*Gemeindehaus", src)
        self.assertIsNotNone(gh_anchor, "Could not locate Gemeindehaus (8e) vignette block in vignettes.js")
        gh_block = _extract_balanced_block(src, gh_anchor.end())
        gh_code = _strip_js_comments(gh_block)
        self.assertRegex(
            gh_code,
            r"drawSwissOrMuniFlag\([^)]*['\"]swiss['\"]\s*\)",
            "Gemeindehaus forecourt Swiss flag must be preserved",
        )
        self.assertRegex(
            gh_code,
            r"drawSwissOrMuniFlag\([^)]*['\"]kilchberg['\"]\s*\)",
            "Gemeindehaus forecourt Kilchberg municipal flag must be preserved",
        )
        gh_clock_calls = _extract_call_args(gh_code, "drawSwissClockDial")
        gh_center_clocks = [c for c in gh_clock_calls if "ghCenter" in c]
        self.assertEqual(
            gh_center_clocks,
            [],
            f"Gemeindehaus (ghCenter) must have ZERO live drawSwissClockDial calls in block 8e (found {gh_center_clocks})",
        )
        for call_args in gh_clock_calls:
            self.assertIn(
                "ghSchul",
                call_args,
                f"Any drawSwissClockDial call in block 8e must target ghSchul (Schulhaus Dachreiter), not Gemeindehaus (got: {call_args!r})",
            )

    @test_meta("T2.LM.03", "Reconciled clock inventory: signage.CLOCKS has zero phantom or duplicate clocks")
    def test_03_reconciled_clock_inventory(self) -> None:
        forbidden = (
            "st_elisabeth",
            "gemeindehaus",
            "lindt",
            "ref_kirche",
            "reformierte",
            "bahnhof",
        )
        offenders = []
        for entry in signage.CLOCKS:
            hits = _clock_entry_matches(entry, forbidden)
            if hits:
                offenders.append((hits, entry))
        self.assertEqual(
            offenders,
            [],
            f"signage.CLOCKS contains phantom/duplicate v10 clocks that must be removed: {offenders}",
        )

    @test_meta("T2.LM.04", "Master tiles St. Elisabeth bell tower is bright neutral white concrete with zero clock dial")
    def test_04_st_elisabeth_plate_white_concrete_no_clock(self) -> None:
        # 1. Bell tower concrete shaft ROI (upper + mid exposed concrete shaft) on day master tiles
        shaft = crop_landmark_meter_box("day", "st_elisabeth", 13.83, -19.02, 17.13, -5.73).astype(np.float32)
        sr, sg, sb = shaft[..., 0], shaft[..., 1], shaft[..., 2]
        slum = shaft.mean(axis=2)

        # Isolate exposed concrete pixels (exclude green foliage & dark recessed belfry louvers)
        concrete_mask = (~(sg > sr + 15.0)) & (slum >= 100.0)
        self.assertGreaterEqual(
            int(concrete_mask.sum()),
            100,
            f"Insufficient exposed concrete pixels in St. Elisabeth tower shaft ROI ({int(concrete_mask.sum())})",
        )
        conc_lum = slum[concrete_mask]
        p90_lum = float(np.percentile(conc_lum, 90))
        bright_frac = float((conc_lum >= 168.0).mean())
        self.assertGreaterEqual(
            p90_lum,
            172.0,
            f"St. Elisabeth tower concrete p90 luminance {p90_lum:.1f} < 172.0 (expected bright white concrete, not dull grey-beige)",
        )
        self.assertGreaterEqual(
            bright_frac,
            0.10,
            f"St. Elisabeth tower bright concrete fraction (>=168) is {bright_frac:.3f} < 0.10",
        )

        # Verify neutral white concrete (low warm-beige yellow chroma: mean(R) - mean(B) small)
        bright_px = shaft[concrete_mask & (slum >= 160.0)]
        rb_diff = float(bright_px[:, 0].mean() - bright_px[:, 2].mean())
        self.assertLessEqual(
            rb_diff,
            10.0,
            f"St. Elisabeth tower concrete has warm-beige chroma mean(R)-mean(B)={rb_diff:.1f} > 10.0",
        )
        self.assertLessEqual(
            abs(rb_diff),
            14.0,
            f"St. Elisabeth tower concrete is not neutral white (|mean(R)-mean(B)|={abs(rb_diff):.1f} > 14.0)",
        )

        # 2. Pure-white upper crown check (cleanly above v11 in_belfry dark louvers)
        crown_roi = crop_landmark_meter_box("day", "st_elisabeth", 14.59, -21.95, 16.37, -20.19).astype(np.float32)
        dlum = crown_roi.mean(axis=2)

        very_dark = dlum < 55.0
        dark_px = int(very_dark.sum())
        dark_frac = float(very_dark.mean())
        self.assertLessEqual(
            dark_px,
            4,
            f"Dark slot/clock dial detected on St. Elisabeth upper tower crown ({dark_px} dark px, {dark_frac * 100:.1f}%)",
        )
        self.assertLess(
            dark_frac,
            0.015,
            f"Dark slot/clock dial fraction on St. Elisabeth upper tower crown too high ({dark_frac * 100:.1f}% >= 1.5%)",
        )

        # 3. Zero gold clock-ring/hands pixels across the FULL tower (crown + shaft)
        tower_full = crop_landmark_meter_box("day", "st_elisabeth", 13.83, -21.95, 17.13, -5.73).astype(np.float32)
        tr, tg, tb = tower_full[..., 0], tower_full[..., 1], tower_full[..., 2]
        gold_ring = (tr > 130.0) & (tg > 100.0) & (tb < 80.0) & ((tr - tb) > 55.0)
        self.assertLessEqual(
            int(gold_ring.sum()),
            2,
            f"Gold clock ring/hands pixels detected on St. Elisabeth bell tower ({int(gold_ring.sum())} px)",
        )

    @test_meta("T2.LM.05", "Photo-verified v11 landmark metadata and coordinates in pipeline/config.py")
    def test_05_config_landmark_metadata_and_coords(self) -> None:
        ids = tuple(lm["id"] for lm in config.LANDMARKS)
        self.assertEqual(
            ids,
            ALL_LANDMARK_IDS_V9,
            "All 16 landmark IDs and their exact order must be preserved in pipeline/config.py",
        )
        by_id = {lm["id"]: lm for lm in config.LANDMARKS}

        # Broelberggut elevation fix: 468.0 -> 496.0 (>= 490)
        broel_z = float(by_id["broelberggut_estate"]["z"])
        self.assertGreaterEqual(
            broel_z,
            490.0,
            f"broelberggut_estate z={broel_z} < 490.0 (must fix v10 468.0 elevation bug)",
        )

        # Sanatorium Kilchberg founding year: 1867 (not 1906)
        san_sub = str(by_id["sanatorium_ridge"]["subtitle"])
        self.assertIn("1867", san_sub, f"sanatorium_ridge subtitle must reference 1867 (got: {san_sub!r})")
        self.assertNotIn("1906", san_sub, f"sanatorium_ridge subtitle must not reference 1906 (got: {san_sub!r})")

        # Villa Spinnergut & TC Kilchberg court count: six (not three)
        tc_sub = str(by_id["villa_spinnergut_tc"]["subtitle"]).lower()
        self.assertIn("six", tc_sub, f"villa_spinnergut_tc subtitle must reference 'six' courts (got: {tc_sub!r})")
        self.assertNotIn("three", tc_sub, f"villa_spinnergut_tc subtitle must not reference 'three' courts (got: {tc_sub!r})")

        # Hallenbad Hochweid: no fabricated 400m athletics track
        hb_sub = str(by_id["hallenbad_hochweid"]["subtitle"])
        self.assertIsNone(
            re.search(r"400\s*m\s+athletics\s+track", hb_sub, flags=re.I),
            f"hallenbad_hochweid subtitle must not claim a 400m athletics track (got: {hb_sub!r})",
        )


if __name__ == "__main__":
    result_json, verbose = parse_cli_args_for_module(sys.argv[1:])
    sys.exit(
        run_unittest_module(
            sys.modules[__name__],
            tier=2,
            suite_name="tier2_landmarks_v11",
            result_json_path=result_json,
            verbose=verbose,
        )
    )
