# TEST_READY — Kilchberg v11 Landmark Photo-Realism Opaque-Box E2E Suite

**Status:** **READY** (Verified — 115 Opaque-Box E2E Tests across Tiers 1–4)
**Date:** 2026-11-22
**Owner:** E2E Testing Track (`e2e_v11_writer_2`, Iteration 2 — Challenger 1 & 2 Calibration/Hardening Pass)
**Suite Specification:** [TEST_INFRA.md](TEST_INFRA.md)

---

## 1. Readiness Summary
- **Total Tests:** **115** (**56** Python `unittest` + **59** Node raw-CDP browser tests)
  - **110 / 110 existing v10 baseline tests preserved 100% intact** (51 Python including the 7 lettering tests `T2.LET.01`–`T2.LET.07` + 59 Node CDP; zero deleted, skipped, or weakened guardrail assertions).
  - **2 existing lettering tests synchronized with photo-verified v11 truth (`tests/tier2_lettering.py`):**
    - `T2.LET.02`: Preserves required `signage.SIGNS` keys `lindt_main`, `lindt_hoc`, `bahnhof_station`, `gemeindehaus_main` (drops deleted fictional `seebad_bathhouse`), forbids any `signage.SIGNS` entry whose `key`, `bldg`, or `text` references `st_elisabeth` or `st. elisabeth` (case-insensitive, plus exact `st_elisabeth_nave`), and preserves `"LINDT & SPRÜNGLI"`, `"LINDT"`, `"HOME OF"`, `"CHOCOLATE"` text assertions.
    - `T2.LET.05`: Verifies photo-accurate **metallic gold** `"LINDT & SPRÜNGLI"` lettering (`fg=(212, 168, 56)` under bin-4 day shading) aligned within `7.0°` of bin-4 wall tangent `(-0.6428, 0.7660)` inside the calibrated historic factory sign window (`x=[0.4120, 0.4580], y=[0.5850, 0.6320]`, ≥24 px margin around sign, excluding yellow penthouse wall so v10 background `gold_px = 63 < 150`) on `01_lindt_home_of_chocolate.webp`, and asserts red-paint pixels (`< 100`) no longer dominate that window.
  - **+5 new Kilchberg v11 landmark photo-realism regression tests (`tests/tier2_landmarks_v11.py`, registered in `tests/run_e2e.py` under Tier 2):**
    - `T2.LM.01`: St. Elisabeth (`st_elisabeth_twr`) has **ZERO clocks** in `signage.CLOCKS` (case-insensitive) AND **ZERO live clock** (`drawSwissClockDial`) inside the St. Elisabeth (`8a`) vignette block in `docs/js/render/vignettes.js` (extracted with comment-aware `_extract_balanced_block`).
    - `T2.LM.02`: Gemeindehaus (`gemeindehaus_main`) has **ZERO clocks** in `signage.CLOCKS`, **ZERO live `ghCenter` clock** in block `8e` (any `drawSwissClockDial` call in block `8e` must target `ghSchul`, never `ghCenter`), AND **ZERO duplicate rooftop flag** in `docs/js/render/vignettes.js` (`fIdx === 3` skipped via `if (fIdx === 3) {? continue ;? }?` in `drawAmbientEffects`, while preserving the comment-stripped active `kilchberg` 4-petal white-flower renderer `petalDist`/`kGold`/`ctx.arc(` in `drawSwissOrMuniFlag` and the forecourt Swiss + Kilchberg flag pair).
    - `T2.LM.03`: Reconciled `signage.CLOCKS` inventory — zero phantom/duplicate clocks matching any of the 6 case-insensitive landmark stems (`st_elisabeth`, `gemeindehaus`, `lindt`, `ref_kirche`, `reformierte`, `bahnhof`) across key/`bldg`/entry values.
    - `T2.LM.04`: Visual photo-realism pixel check on `docs/assets/07_st_elisabeth_church.webp` — bell tower exposed concrete shaft ROI (`x=[0.5270, 0.5335], y=[0.4340, 0.4680]`) is bright neutral white concrete (`p90_lum >= 172.0`, bright fraction `>= 0.10`, low warm-beige yellow chroma `mean(R) - mean(B) <= 10.0`), upper crown ROI (`x=[0.5285, 0.5320], y=[0.4265, 0.4310]`, cleanly above v11 `in_belfry` louvers) has zero dark slot/clock dial (`<= 4` dark px, `< 1.5%`), and full-tower ROI (`x=[0.5270, 0.5335], y=[0.4265, 0.4680]`) has zero gold clock-ring/hands pixels (`<= 2`).
    - `T2.LM.05`: Photo-verified `pipeline/config.py` landmark metadata & coordinates — exact 16 landmark IDs & order preserved, `broelberggut_estate` `z >= 490.0`, `sanatorium_ridge` subtitle contains `1867` (not `1906`), `villa_spinnergut_tc` subtitle contains `six` (not `three`), and `hallenbad_hochweid` subtitle does not claim a `400 m athletics track`.

## 2. Canonical Execution Command
```bash
cd /home/antigravity/mad-greg/pixel-art && .venv/bin/python tests/run_e2e.py --tier all --verbose
```

Targeted tier runs:
```bash
cd /home/antigravity/mad-greg/pixel-art && .venv/bin/python tests/run_e2e.py --tier 1 --verbose
cd /home/antigravity/mad-greg/pixel-art && .venv/bin/python tests/run_e2e.py --tier 2 --verbose
cd /home/antigravity/mad-greg/pixel-art && .venv/bin/python tests/run_e2e.py --tier 3 --verbose
cd /home/antigravity/mad-greg/pixel-art && .venv/bin/python tests/run_e2e.py --tier 4 --verbose
```

## 3. Verified Tier 1 & Tier 2 Snapshot (Iteration 2 — Pre-M4 v10 Rendered Plates + M3 Code Applied)
Verified via syntax checks + `.venv/bin/python tests/run_e2e.py --tier 1 --verbose` + `.venv/bin/python tests/run_e2e.py --tier 2 --verbose`:
- **Syntax checks (`py_compile` + `node --check`):** exit `0` (`SYNTAX_OK`)
- **Tier 1 (`--tier 1 --verbose`):** `41 tests | 41 PASSED | 0 FAILED | 0 ERRORS | 32.62 s`
  - `tier1_assets_data`: 24 PASSED, 0 FAILED, 0 ERRORS (26.21 s)
  - `tier1_browser_features`: 17 PASSED, 0 FAILED, 0 ERRORS (32.55 s)
- **Tier 2 (`--tier 2 --verbose`):** `48 tests | 46 PASSED | 2 FAILED | 0 ERRORS | 45.67 s`
  - `tier2_quality_bounds`: 20 PASSED, 0 FAILED, 0 ERRORS (21.88 s)
  - `tier2_lettering`: 6 PASSED, 1 FAILED (`T2.LET.05`), 0 ERRORS (1.73 s)
  - `tier2_landmarks_v11`: 4 PASSED, 1 FAILED (`T2.LM.04`), 0 ERRORS (0.43 s)
  - `tier2_browser_bounds`: 16 PASSED, 0 FAILED, 0 ERRORS (43.09 s)
- **2 Clean `AssertionError` Failures Gating M4 Full Re-Render (Zero Errors / Zero Timeouts):**
  1. `T2.LET.05` — `1528 not less than 100 : historic factory 'LINDT & SPRÜNGLI' sign must be metallic gold, not red (found 1528 red px)` (tightened ROI also verified on v10: `gold_px = 63 < 150`; gates M4 re-render of `01_lindt_home_of_chocolate.webp`)
  2. `T2.LM.04` — `163.3333282470703 not greater than or equal to 172.0 : St. Elisabeth tower concrete p90 luminance 163.3 < 172.0 (expected bright white concrete, not dull grey-beige)` (calibrated ROIs also verified on v10: `cy1=0.4310` catches `42` dark px / `16.4%`, and full-tower `gold_ring = 6 > 2`; gates M4 re-render of `07_st_elisabeth_church.webp`)
- **Code-Contract & Mutation-Probe Verification (`T2.LET.02`, `T2.LM.01`, `T2.LM.02`, `T2.LM.03`, `T2.LM.05`):** All 5 code-level v11 assertions verified cleanly against M3's updated `pipeline/signage.py`, `pipeline/config.py`, and `docs/js/render/vignettes.js` with `0` errors, and all 7 Challenger 1 & 2 findings verified via independent in-memory probes.
- **Orphan Process Check:** `0` live Chromium/Node processes remaining.
