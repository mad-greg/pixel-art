# TEST_READY — E2E Testing Track Signal (4-Tier Opaque-Box Suite Ready)

**Status:** READY FOR FINAL MILESTONE (`M6`) EXECUTION  
**Published:** 2026-11-20  
**Methodology & Inventory:** [`TEST_INFRA.md`](./TEST_INFRA.md)  
**Unified Runner:** `python3 tests/run_e2e.py --tier <1|2|3|4|all>`

---

## 1. Suite Inventory (11 Files, 70 Tests Across 4 Tiers)

| File | Tier | Coverage | Test Count |
|---|---|---|---:|
| `tests/run_e2e.py` | Runner | Unified CLI (`--tier 1\|2\|3\|4\|all\|1,2`, `--verbose`, `--json-report`, `--timeout`), exit `0`/`1`/`124`, atomic `os.killpg` teardown | — |
| `tests/lib/report.py` | Lib | `TestCaseResult` / `TierResult`, `StructuredTestResult` (skips fail closed as `ERROR`), summary table & JSON report writer | — |
| `tests/lib/assets_helper.py` | Lib | Zero-`scipy` `numpy`+`Pillow`+`ffprobe` loaders, `uint8` sky diffs, separable NumPy morphology, RLE 4-connected components, pixel-space road turn angles | — |
| `tests/lib/cdp_harness.mjs` | Lib | Zero-dep Node 24 native `WebSocket` CDP driver for `/usr/bin/chromium` (no `--autoplay-policy` bypass; real trusted clicks; offline font CDN blocking; shared Chromium + isolated incognito contexts; `waitForCameraSettled()`; fast `forceClose()` teardown) | — |
| `tests/tier1_assets_data.py` | Tier 1 | FA1 (7) + FA2 (8) + FA4 static (2): manifests, 234 lossless tiles, overviews, depth map, 6 plates, SVGA `<= 256` colors, interactive & animations schemas, Bendlikon `Badweg 1.1`, zero paragliders, 9 MP3s (`ffprobe`) | 17 |
| `tests/tier1_browser_features.mjs` | Tier 1 | FA3 (12) + FA4 live (3): clean boot (0 JS/404 errors), lighting + `body[data-mode]`, zoom/tiles, landmarks, building click, address search, detail-plate modal + "Fly Here", Cinema (`H`/`Esc`), collapsible sidebar, compass/scale bar, share/postcard, `window.__dioramaDebug`, trusted audio unlock & layer mixer | 15 |
| `tests/tier2_quality_bounds.py` | Tier 2 | FA1 (9) + FA2 (6): diurnal luminance ordering, per-preset CLUTs, tile seams, zero floating sky cars & depth occluders, zero floating plate sports props, spotless Lake Zurich shore, Sunset golden non-pink plaster (preserving F6 cool violet shadows), Night warm lantern pools, Lindt HoC 25 cm roof variance, zero road kinks `> 45°`, full road occlusion, endpoint/vessel/building bounds | 15 |
| `tests/tier2_browser_bounds.mjs` | Tier 2 | FA3 (6) + FA4 (5): Desktop `1280×800` DPR=2 zero clipping/overlap & Retina backing store, Mobile `390×844` zero clipping, extreme zoom `Fit..8×`, empty search, malformed URL fallback, shore-strict wave attenuation vs overview/inland, paused-animation spatial audio updates, mute suspending `AudioContext`, rapid toggle stability | 11 |
| `tests/tier3_combinations.mjs` | Tier 3 | 6 pairwise cross-feature suites (`T3.01`–`T3.06`): Lighting×Diurnal, Zoom/Tiles×Occlusion×Follow (`Train`/`Boat`/`Bus`), Search/Fly-To×Inspector×Modal "Fly Here", Lighting×Spatial Audio, URL Deep-Link×`?t=`×Permalink Round-Trip, Cinema/Sidebar×Resize/Minimap | 6 |
| `tests/tier4_journeys.mjs` | Tier 4 | 6 real-world end-user journeys (`T4.01`–`T4.06`): Visitor Full Tour, Lindt HoC & Schooren Seebad Deep-Zoom, Commuter Transit Showcase, Resident Address Lookup, Spatial Soundscape Walk, Mobile Portrait Explorer | 6 |
| **Total** | **Tiers 1–4** | **FA1 (`7+9`), FA2 (`8+6`), FA3 (`12+6`), FA4 (`5+5`), 6 Pairs, 6 Journeys** | **70** |

---

## 2. Independent Verification Gate Evidence (Iteration 2 — Unanimous PASS)

All 5 independent Verification Wave agents passed strictly:

| Agent | Role | Verdict | Key Verified Evidence |
|---|---|---|---|
| `e2e_auditor_iter2` | Forensic Integrity Auditor (Intermediate Track Audit) | **CLEAN** | 0 integrity violations, 0 tautologies/skips, strict opaque-box design, zero unauthorized edits outside `TEST_INFRA.md` & `tests/**`, zero code/data in `.agents/teamwork/`. |
| `e2e_rev1_iter2` | Primary Reviewer | **APPROVE** | Uncontended `python3 tests/run_e2e.py --tier all`: **`63.11 s`** (`< 90 s` budget), all 4 tiers `< 30 s` (T1 `14.9 s`, T2 `14.4 s`, T3 `19.25 s`, T4 `14.50 s`), **70 tests \| 28 PASSED \| 42 FAILED \| 0 ERRORS** (live M3 animations flipped 5 tests PASS & caught an `sbb_ic_north` stop-point bug!), `0` orphan Chromium processes / temp dirs. |
| `e2e_rev2_iter2` | Secondary Reviewer | **APPROVE** | Independent Tier 3 (`19.28 s`), Tier 4 (`23.46 s`), Tier 1 `--json-report` schema validated, `--timeout 3` clean `exit=124` with `0` leaks, full M4/M5 F24 easing & raw-GainNode compatibility verified. |
| `e2e_chal1_iter2` | Python Assets & Quality Challenger | **CONFIRMED** | Zero `scipy` imports; `0` pixel mismatches vs brute-force/`float32`; synthetic F6 cool-violet shadows pass `T2.FA1.07`; `1×1` specks ignored while `10×10` & all `v6.2` floating cars/sports props caught; dynamic Lindt tile lookup & unconditional 4-tuple road `d16` checks verified. |
| `e2e_chal2_iter2` | Browser CDP & Process Hygiene Challenger | **CONFIRMED** | **12 / 12** forced-timeout stress probes (`0.1 s`–`4.5 s` across Tiers 1–3) exited `124` with `0` live Chromium orphans and `0` leaked temp dirs; malformed percent-encoding returns HTTP `400`; `_closePromise` & `openTab()` cleanup verified; zero vacuous `if (dbg)` guards. |

---

## 3. Running the Suite (For M6 / Integration Verification)

```bash
# Run all 4 tiers (~60–65 s uncontended, exit 0 when all 70 tests pass on complete v7.0)
python3 tests/run_e2e.py --tier all --verbose

# Run individual tiers (< 25 s each)
python3 tests/run_e2e.py --tier 1
python3 tests/run_e2e.py --tier 2
python3 tests/run_e2e.py --tier 3
python3 tests/run_e2e.py --tier 4

# Emit machine-readable JSON summary
python3 tests/run_e2e.py --tier all --json-report /tmp/e2e_report.json
```

> **Note for M4/M5 Integrators:** Ensure `docs/app.js` exposes the `PROJECT.md § Interface Contracts #5` read-only telemetry accessor `window.__dioramaDebug` (object or getter function) with `{ mode, scale, u, v, dpr, animTime, fps, audioEnabled, audioState, audioGains, activeLandmark, selectedBuilding, searchResultCount }` (where `audioGains` maps `lake_waves`, `birds`, `crickets`, `traffic`, `town_traffic`, `train`, `bells`) and sets `document.body.dataset.mode` (`day` | `sunset` | `night`).
