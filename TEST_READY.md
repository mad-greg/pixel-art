# TEST_READY — Kilchberg v9.0 Opaque-Box E2E Suite

**Status:** **READY** (Verified & Audited — 97 Opaque-Box E2E Tests across Tiers 1–4)
**Date:** 2026-11-21
**Owner:** E2E Testing Track (`e2e_orch_v9`)
**Suite Specification:** [TEST_INFRA.md](TEST_INFRA.md)

---

## 1. Readiness Summary
- **Total Tests:** **97** (41 Python `unittest` + 56 Node raw-CDP browser tests)
  - **88 / 88 existing v8.0 baseline tests preserved 100% intact** (zero deleted, skipped, or weakened assertions; only `T1.FA2.01` and `T1.FA3.04` relaxed from `== 10` → `>= 10` while strictly enforcing `0..9` `REQUIRED_LANDMARK_IDS` order; `T1.FA2.07` `ambient.swiss_flags == 4` and `DETAIL_PLATES` `01..06` remain untouched; verified line-by-line by Forensic Auditor).
  - **+9 new Kilchberg v9.0 opaque-box tests** (+5 Python, +4 Node CDP) covering every v9.0 requirement in `ORIGINAL_REQUEST.md` and `PROJECT.md § Feature Inventory` & `§ Interface Contracts` strictly via public interfaces:
    - **Tier 1 Python (+3):** `T1.FA1.10` (10 detail plates `01..10_*.webp` lossless `VP8L` RGB `>=2000×1400` `<=256` colors), `T1.FA2.10` (`>=16` landmarks, `0..9` preserved, 6 new IDs, `cf_meyer_haus <= 35 m` LV95 of `Alte Landstrasse 170`), `T1.FA2.11` (`ambient.vignettes` anchors for `sanatorium_ridge`, `moenchhof_horn`, `sulzergut_park` + 6 new landmarks in `[0,1]` UV, `< 650 KB`).
    - **Tier 1 Browser (+1):** `T1.FA3.14` (sidebar `>= 16` `.lm-item` stops, dynamic `${N} STOPS` tag, `#crop-gallery` `>= 10` `.crop-thumb` plates with `01..06` preserved at `0..5`, plate #7 modal opens & closes cleanly with zero errors).
    - **Tier 2 Python (+2):** `T2.FA1.10` (zero floating sky clusters + `std_luma >= 20` & `entropy >= 2.5` across plates `07..10`), `T2.FA2.08` (all 16 landmarks inside `island_2x`, pairwise `duv >= 0.045`, `cf_meyer_haus` vignette & fountain aligned `<= 0.02` UV).
    - **Tier 2 Browser (+1):** `T2.FA3.10` (zoom-aware overview `Fit` pin decluttering with zero severe overlap, zoomed-in & active pin visibility, desktop `1280×800` & mobile `390×844` zero layout clipping).
    - **Tier 3 Browser (+1):** `T3.11` (`?landmark=gemeindehaus_alte_landstr` & `?landmark=cf_meyer_haus` deep-link boot + `[`/`]` keyboard landmark cycling).
    - **Tier 4 Browser (+1):** `T4.13` (Journey 8 — Kilchberg Heritage & New Landmarks Tour across `cf_meyer_haus` + 6 new landmarks, new plate `08`/`09` "Fly Here", tile streaming, zero clipping, zero errors; numbered `T4.13` because `T4.08`–`T4.12` already exist from v8.0 Tier 5 hardening).

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

## 3. Verified Snapshot at Publication
Independent verification by Primary Reviewer (`e2e_rev_1`, `.venv/bin/python tests/run_e2e.py --tier all --verbose`):
- **Syntax checks (`py_compile` + `node --check`):** exit `0` (`SYNTAX_OK`)
- **Initial v8.0 baseline check (Writer 1, pre-M1 plates):** `97 tests | 88 PASSED | 9 FAILED | 0 ERRORS | 0 TIMEOUTS`
- **Primary Reviewer full run (after M1 wrote plates `07..10_*.webp`):** `97 tests | 89 PASSED | 8 FAILED | 0 ERRORS | 0 TIMEOUTS | 178.79 s`
  - **Baseline Regression Check:** **88 / 88 PASS** (0 regressions)
  - **Already Passing (1 / 9):** `T1.FA1.10` (all 10 detail plates lossless `VP8L` RGB `>=2000×1400` `<=256` colors)
  - **Active Quality Gate Catch on M1 Plate 08:** `T2.FA1.10` caught `2 != 1 : 08_cf_meyer_haus.webp has 1 floating sky clusters`
  - **Remaining v9.0 Tests Gating M2, M3 & M4 (7 / 9 — cleanly failing with `AssertionError`):**
    - `T1.FA2.10` — 16 landmarks + authentic `cf_meyer_haus` LV95 (gates M2)
    - `T1.FA2.11` — `ambient.vignettes` 9 new/un-vignetted anchors + `< 650 KB` (gates M2)
    - `T2.FA2.08` — 16 landmarks `island_2x` + `duv >= 0.045` + `cf_meyer_haus` vignette/fountain alignment (gates M2)
    - `T1.FA3.14` — Sidebar `>= 16` stops, dynamic stop-count badge, 10-plate gallery & plate #7 modal (gates M3)
    - `T2.FA3.10` — Zoom-aware overview pin decluttering, active-pin visibility & desktop/mobile zero clipping (gates M3)
    - `T3.11` — `?landmark=` deep-link boot & `[`/`]` keyboard landmark cycling (gates M3)
    - `T4.13` — Journey 8: Kilchberg Heritage & New Landmarks Tour (gates M3/M4)
- **Orphan Process Check:** `ZERO_LIVE` (zero remaining Chromium or Node processes)

## 4. Verification Sign-Off
- **Forensic Auditor (`e2e_aud_1`):** `CLEAN` (intermediate track audit, sub-scope `tests/*`, `TEST_INFRA.md`, `TEST_READY.md`)
- **Primary Reviewer (`e2e_rev_1`):** `APPROVE`
- **Secondary Reviewer (`e2e_rev_2`):** `APPROVE`
- **Python Challenger (`e2e_chal_1`):** `CONFIRMED` (36/36 empirical probes in isolated `mktemp -d`: `count_unique_rgb_colors`, `extract_vignette_uv_anchors`, 5/5 positive synthetic v9.0 PASS, 14/14 fault-injection catches)
- **Browser Challenger (`e2e_chal_2`):** `CONFIRMED` (7/7 `severePinOverlap` probes + 4/4 verbatim CDP PASS on synthetic v9.0 `docs/` fixture + 5/5 fault-injection clean `AssertionError` FAIL in isolated `mktemp -d`)
