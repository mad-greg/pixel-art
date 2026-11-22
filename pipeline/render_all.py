"""Master batch renderer for the Kilchberg ZH 90s 3D Isometric Pixel-Art Diorama.

Generates:
1. Ultra-High-Fidelity 0.25 m/px (~12,500 x 5,640 px = 70 Megapixel!) Full-Municipality
   Deep-Zoom Tile Pyramids (docs/assets/tiles/{day,sunset,night}/) + Overview WebPs + PNGs:
   - renders/kilchberg_diorama_day.png      (90s SVGA Crisp Midday)
   - renders/kilchberg_diorama_sunset.png   (Alpenglow Golden Sunset)
   - renders/kilchberg_diorama_night.png    (Zürichsee Lantern & Window-Lit Night)
2. Ten Ultra-Fine 0.22 m/px 3D Isometric Landmark Detail Plates:
   - renders/crops/01_lindt_home_of_chocolate.png
   - renders/crops/02_reformierte_kirche_dorf.png
   - renders/crops/03_bendlikon_harbor_pier.png
   - renders/crops/04_bahnhof_kilchberg_weinberg.png
   - renders/crops/05_schooren_seebad.png
   - renders/crops/06_sanatorium_ridge.png
   - renders/crops/07_st_elisabeth_church.png
   - renders/crops/08_cf_meyer_haus.png
   - renders/crops/09_gemeindehaus_alte_landstrasse.png
   - renders/crops/10_stockengut_ridge_farm.png
3. Interactive GIS Metadata in docs/data/kilchberg_interactive.json
"""

from __future__ import annotations
import argparse
import json
import time

from .config import CROPS_DIR, DOCS_DIR, IsometricCamera, LANDMARKS, RENDERS_DIR
from .export_animations import export_animations
from .extract_scene import extract_scene
from .pixel_shader import SceneData, render_diorama, render_diorama_crop_tiled, render_diorama_tiled_hires

CROP_SPECS = [
    ("lindt_hoc", "01_lindt_home_of_chocolate.png"),
    ("reformierte_kirche", "02_reformierte_kirche_dorf.png"),
    ("bendlikon_pier", "03_bendlikon_harbor_pier.png"),
    ("bahnhof_stockengut", "04_bahnhof_kilchberg_weinberg.png"),
    ("schooren_seebad", "05_schooren_seebad.png"),
    ("sanatorium_ridge", "06_sanatorium_ridge.png"),
    ("st_elisabeth", "07_st_elisabeth_church.png"),
    ("cf_meyer_haus", "08_cf_meyer_haus.png"),
    ("gemeindehaus_alte_landstr", "09_gemeindehaus_alte_landstrasse.png"),
    ("stockengut_farm", "10_stockengut_ridge_farm.png"),
]


PLATE_CARTOUCHE_META: dict[str, tuple[str, str]] = {
    "lindt_hoc": (
        "PLATE I  —  LINDT HOME OF CHOCOLATE & 1899 FACTORY CAMPUS",
        "SEESTRASSE 204 · SCHOOREN · 6 COCOA SILOS & 43.6m SMOKESTACK",
    ),
    "reformierte_kirche": (
        "PLATE II  —  REFORMIERTE KIRCHE KILCHBERG & HISTORIC DORF",
        "13TH-C. HILLTOP SPIRE · CEMETERY · DORFSTRASSE HORSESHOE VIADUCT",
    ),
    "bendlikon_pier": (
        "PLATE III  —  BENDLIKON HARBOR, ZSG STEAMER PIER & PAVILION",
        "LAKE ZURICH PROMENADE · MOORED FLEET · TIMBER JETTIES",
    ),
    "bahnhof_stockengut": (
        "PLATE IV  —  BAHNHOF KILCHBERG, VIADUCT & WEINBERG",
        "SBB SEEBAHN CATENARY · PLATFORM CANOPIES · SCHULHAUS DORFSTRASSE",
    ),
    "schooren_seebad": (
        "PLATE V  —  SEEBAD KILCHBERG & SCHOOREN LAKESIDE VILLAS",
        "TIMBER BADI BATHHOUSE · THREE SWIM JETTIES · VILLA NAVILLE",
    ),
    "sanatorium_ridge": (
        "PLATE VI  —  SANATORIUM KILCHBERG & STOCKEN RIDGE",
        "EST. 1867 · HISTORIC HAUS A & C · GUSTAV AMMANN PARK · TREIBHÄUSER",
    ),
    "st_elisabeth": (
        "PLATE VII  —  KATHOLISCHE KIRCHE ST. ELISABETH & BRUNNENMOOS",
        "30.1m FREESTANDING CAMPANILE · STAINED-GLASS CLERESTORY · KGS-NR. 12594",
    ),
    "cf_meyer_haus": (
        "PLATE VIII  —  CONRAD FERDINAND MEYER-HAUS (KGS-NR. 7525)",
        "ALTE LANDSTRASSE 170 · POET'S COUNTRY ESTATE · LITERARY MUSEUM & GARDEN",
    ),
    "gemeindehaus_alte_landstr": (
        "PLATE IX  —  GEMEINDEHAUS & SCHULHAUS ALTE LANDSTRASSE",
        "1930s HEIMATSTIL CIVIC CORE · BELL CUPOLA · TOWN HALL FORECOURT",
    ),
    "stockengut_farm": (
        "PLATE X  —  STOCKENGUT (GUTSBETRIEB UF-STOCKEN)",
        "507m MUNICIPAL HILLTOP FARMSTEAD · TWIN SILOS · GLASSHOUSE & PASTURES",
    ),
}


def render_everything(
    mpp_full: float = 0.125,
    mpp_crop: float = 0.11,
    presets: tuple[str, ...] = ("day", "sunset", "night"),
    skip_crops: bool = False,
    skip_animations: bool = False,
    skip_full: bool = False,
    crops: tuple[str, ...] | None = None,
    crop_preset: str = "day",
    depth_only: bool = False,
    macro_rows: tuple[int, int] | None = None,
    finalize_tiles: bool = False,
    crop_out_dir: str | None = None,
) -> None:
    from pathlib import Path

    extract_scene(force=False)
    if crop_out_dir is None:
        RENDERS_DIR.mkdir(parents=True, exist_ok=True)
        CROPS_DIR.mkdir(parents=True, exist_ok=True)
        (DOCS_DIR / "data").mkdir(parents=True, exist_ok=True)
        (DOCS_DIR / "assets").mkdir(parents=True, exist_ok=True)
    else:
        Path(crop_out_dir).mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    scene = SceneData()
    print(f"[render] Loaded Kilchberg 3D scene in {time.time() - t0:.1f}s")

    if depth_only:
        t_p = time.time()
        render_diorama_tiled_hires(
            scene,
            mpp=mpp_full,
            preset_key="day",
            tiles_dir=DOCS_DIR / "assets" / "tiles" / "day",
            overview_webp_path=DOCS_DIR / "assets" / "diorama_day.webp",
            full_png_path=RENDERS_DIR / "kilchberg_diorama_day.png",
            tile_size=1024,
            collect_hit_boxes=False,
            depth_only=True,
        )
        print(f"[render] Depth-only pass complete in {time.time() - t_p:.1f}s")
        return

    meta_out_p = DOCS_DIR / "data" / "kilchberg_interactive.json"
    if not skip_full:
        do_finalize = finalize_tiles or (macro_rows is None)
        finalize_only = finalize_tiles and (macro_rows is None)
        for idx_p, pkey in enumerate(presets):
            t_p = time.time()
            need_meta = do_finalize and ((pkey == "day") or (idx_p == 0 and not meta_out_p.exists()))
            tiles_dir = DOCS_DIR / "assets" / "tiles" / pkey
            ov_webp = DOCS_DIR / "assets" / f"diorama_{pkey}.webp"
            out_png = RENDERS_DIR / f"kilchberg_diorama_{pkey}.png"

            meta = render_diorama_tiled_hires(
                scene,
                mpp=mpp_full,
                preset_key=pkey,
                tiles_dir=tiles_dir,
                overview_webp_path=ov_webp,
                full_png_path=out_png,
                tile_size=1024,
                collect_hit_boxes=need_meta,
                macro_rows=macro_rows,
                finalize_tiles=do_finalize,
                finalize_only=finalize_only,
            )
            if do_finalize:
                if meta:
                    meta_out_p.write_text(json.dumps(meta, separators=(",", ":")))
                mf = json.loads((tiles_dir / "manifest.json").read_text())
                print(
                    f"[render] Ultra-HD Tiled Diorama ({pkey}): {mf['width']}x{mf['height']} px "
                    f"({mf['cols']}x{mf['rows']} tiles @ {mpp_full:.3f} m/px) in {time.time() - t_p:.1f}s"
                )
            else:
                print(
                    f"[render] Macro-row band {macro_rows} ({pkey}) @ {mpp_full:.3f} m/px "
                    f"streamed to /tmp memmap in {time.time() - t_p:.1f}s"
                )

    if not skip_crops:
        import gc
        from .pixel_shader import PRESETS, compute_shadow_grid

        crop_filter = set(crops) if crops else None
        p_c = PRESETS[crop_preset]
        crop_sh = compute_shadow_grid(scene, p_c.sun_az_deg, p_c.sun_alt_deg)
        out_dir_override = Path(crop_out_dir) if crop_out_dir else None
        for lm_id, fname in CROP_SPECS:
            if crop_filter is not None and lm_id not in crop_filter:
                continue
            lm = next(x for x in LANDMARKS if x["id"] == lm_id)
            r = lm["crop_radius_m"]
            box_lv = (lm["e"] - r, lm["n"] - r * 1.15, lm["e"] + r, lm["n"] + r * 1.15)
            cam_c = IsometricCamera(mpp=mpp_crop)
            t_c = time.time()
            p_title, p_sub = PLATE_CARTOUCHE_META.get(lm_id, (None, None))
            img_c = render_diorama_crop_tiled(
                scene,
                cam_c,
                preset_key=crop_preset,
                crop_box_lv95=box_lv,
                add_frame=True,
                sun_shadow_override=crop_sh,
                plate_title=p_title,
                plate_subtitle=p_sub,
            )
            if out_dir_override is not None:
                img_c.save(out_dir_override / fname.replace(".png", ".webp"), format="WEBP", lossless=True, method=4)
            else:
                out_c = CROPS_DIR / fname
                img_c.save(out_c, optimize=True)
                img_c.save(DOCS_DIR / "assets" / fname.replace(".png", ".webp"), format="WEBP", lossless=True, method=4)
            print(f"[render] Crop {fname} ({crop_preset}): {img_c.size[0]}x{img_c.size[1]} @ {mpp_crop:.2f} m/px ({time.time() - t_c:.1f}s)")
            del img_c
            gc.collect()
        del crop_sh
        gc.collect()

    if not skip_animations:
        export_animations(mpp_full=mpp_full)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--presets", nargs="+", default=["day", "sunset", "night"])
    ap.add_argument("--mpp-full", type=float, default=0.125)
    ap.add_argument("--mpp-crop", type=float, default=0.11)
    ap.add_argument("--skip-crops", action="store_true")
    ap.add_argument("--skip-animations", action="store_true")
    ap.add_argument("--skip-full", action="store_true")
    ap.add_argument("--crops", nargs="+", default=None)
    ap.add_argument("--crop-preset", choices=["day", "sunset", "night"], default="day")
    ap.add_argument("--depth-only", action="store_true")
    ap.add_argument("--macro-rows", nargs=2, type=int, default=None, metavar=("START", "END"))
    ap.add_argument("--finalize-tiles", action="store_true")
    ap.add_argument("--crop-out-dir", type=str, default=None)
    args = ap.parse_args()
    render_everything(
        mpp_full=args.mpp_full,
        mpp_crop=args.mpp_crop,
        presets=tuple(args.presets),
        skip_crops=args.skip_crops,
        skip_animations=args.skip_animations,
        skip_full=args.skip_full,
        crops=tuple(args.crops) if args.crops else None,
        crop_preset=args.crop_preset,
        depth_only=args.depth_only,
        macro_rows=tuple(args.macro_rows) if args.macro_rows else None,
        finalize_tiles=args.finalize_tiles,
        crop_out_dir=args.crop_out_dir,
    )
