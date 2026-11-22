"""Master batch renderer for the Kilchberg ZH 90s 3D Isometric Pixel-Art Diorama.

Generates:
1. Ultra-High-Fidelity 0.11 m/px (27,971 x 12,294 px = 343.9 Megapixel!) Full-Municipality
   2-Level Deep-Zoom Tile Pyramids (L1 0.22 m/px + L2 0.11 m/px in docs/assets/tiles/{day,sunset,night}/)
   + 0.44 m/px Overview WebPs + PNGs + 16-bit 3D Depth & Occluder Map:
   - renders/kilchberg_diorama_day.png      (90s SVGA Crisp Midday)
   - renders/kilchberg_diorama_sunset.png   (Alpenglow Golden Sunset)
   - renders/kilchberg_diorama_night.png    (Zürichsee Lantern & Window-Lit Night)
2. Interactive GIS Metadata in docs/data/kilchberg_interactive.json
3. Living-World Animation Paths in docs/data/kilchberg_animations.json

(Separate landmark detail plates are retired now that the entire municipality renders at 0.11 m/px.
Use --debug-crop <landmark_id> ... for ad-hoc /tmp verification crops.)
"""

from __future__ import annotations
import argparse
import json
import time
from pathlib import Path

from .config import DOCS_DIR, IsometricCamera, LANDMARKS, RENDERS_DIR
from .export_animations import export_animations
from .extract_scene import extract_scene
from .pixel_shader import SceneData, render_diorama_crop_tiled, render_diorama_tiled_hires


def render_everything(
    mpp_full: float = 0.11,
    presets: tuple[str, ...] = ("day", "sunset", "night"),
    skip_crops: bool = True,
    skip_animations: bool = False,
    skip_full: bool = False,
    depth_only: bool = False,
    macro_rows: tuple[int, int] | None = None,
    finalize_tiles: bool = False,
    debug_crops: tuple[str, ...] | None = None,
    debug_crop_dir: str = "/tmp/v12_m1b_verify",
    debug_crop_preset: str = "day",
    debug_crop_mpp: float = 0.11,
) -> None:
    _ = skip_crops  # Retained as a no-op for CLI backwards compatibility.

    extract_scene(force=False)
    if not skip_full or depth_only:
        RENDERS_DIR.mkdir(parents=True, exist_ok=True)
        (DOCS_DIR / "data").mkdir(parents=True, exist_ok=True)
        (DOCS_DIR / "assets").mkdir(parents=True, exist_ok=True)
    if debug_crops:
        Path(debug_crop_dir).mkdir(parents=True, exist_ok=True)

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

    if debug_crops:
        import gc
        from .pixel_shader import PRESETS, compute_shadow_grid

        lm_by_id = {x["id"]: x for x in LANDMARKS}
        p_c = PRESETS[debug_crop_preset]
        crop_sh = compute_shadow_grid(scene, p_c.sun_az_deg, p_c.sun_alt_deg)
        out_dir = Path(debug_crop_dir)
        for lm_id in debug_crops:
            if lm_id not in lm_by_id:
                raise ValueError(f"Unknown landmark id '{lm_id}'. Valid: {sorted(lm_by_id)}")
            lm = lm_by_id[lm_id]
            r = lm["crop_radius_m"]
            box_lv = (lm["e"] - r, lm["n"] - r * 1.15, lm["e"] + r, lm["n"] + r * 1.15)
            cam_c = IsometricCamera(mpp=debug_crop_mpp)
            t_c = time.time()
            img_c = render_diorama_crop_tiled(
                scene,
                cam_c,
                preset_key=debug_crop_preset,
                crop_box_lv95=box_lv,
                add_frame=False,
                sun_shadow_override=crop_sh,
            )
            out_p = out_dir / f"{lm_id}_{debug_crop_preset}.png"
            img_c.save(out_p, optimize=True)
            print(
                f"[render] Debug crop {out_p}: {img_c.size[0]}x{img_c.size[1]} "
                f"@ {debug_crop_mpp:.2f} m/px ({time.time() - t_c:.1f}s)"
            )
            del img_c
            gc.collect()
        del crop_sh
        gc.collect()

    if not skip_animations:
        export_animations(mpp_full=mpp_full)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--presets", nargs="+", default=["day", "sunset", "night"])
    ap.add_argument("--mpp-full", type=float, default=0.11)
    ap.add_argument("--skip-crops", action="store_true", help="No-op retained for CLI backwards compatibility (detail plates are retired).")
    ap.add_argument("--skip-animations", action="store_true")
    ap.add_argument("--skip-full", action="store_true")
    ap.add_argument("--depth-only", action="store_true")
    ap.add_argument("--macro-rows", nargs=2, type=int, default=None, metavar=("START", "END"))
    ap.add_argument("--finalize-tiles", action="store_true")
    ap.add_argument("--debug-crop", nargs="+", default=None, help="Opt-in dev/verification landmark IDs to render to --debug-crop-dir.")
    ap.add_argument("--debug-crop-dir", type=str, default="/tmp/v12_m1b_verify")
    ap.add_argument("--debug-crop-preset", choices=["day", "sunset", "night"], default="day")
    ap.add_argument("--debug-crop-mpp", type=float, default=0.11)
    args = ap.parse_args()
    render_everything(
        mpp_full=args.mpp_full,
        presets=tuple(args.presets),
        skip_crops=args.skip_crops,
        skip_animations=args.skip_animations,
        skip_full=args.skip_full,
        depth_only=args.depth_only,
        macro_rows=tuple(args.macro_rows) if args.macro_rows else None,
        finalize_tiles=args.finalize_tiles,
        debug_crops=tuple(args.debug_crop) if args.debug_crop else None,
        debug_crop_dir=args.debug_crop_dir,
        debug_crop_preset=args.debug_crop_preset,
        debug_crop_mpp=args.debug_crop_mpp,
    )
