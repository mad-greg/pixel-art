"""Master batch renderer for the Kilchberg ZH 90s 3D Isometric Pixel-Art Diorama.

Generates:
1. Ultra-High-Fidelity 0.25 m/px (~12,500 x 5,640 px = 70 Megapixel!) Full-Municipality
   Deep-Zoom Tile Pyramids (docs/assets/tiles/{day,sunset,night}/) + Overview WebPs + PNGs:
   - renders/kilchberg_diorama_day.png      (90s SVGA Crisp Midday)
   - renders/kilchberg_diorama_sunset.png   (Alpenglow Golden Sunset)
   - renders/kilchberg_diorama_night.png    (Zürichsee Lantern & Window-Lit Night)
2. Six Ultra-Fine 0.22 m/px 3D Isometric Landmark Detail Plates:
   - renders/crops/01_lindt_home_of_chocolate.png
   - renders/crops/02_reformierte_kirche_dorf.png
   - renders/crops/03_bendlikon_harbor_pier.png
   - renders/crops/04_bahnhof_kilchberg_weinberg.png
   - renders/crops/05_schooren_seebad.png
   - renders/crops/06_sanatorium_ridge.png
3. Interactive GIS Metadata in docs/data/kilchberg_interactive.json
"""

from __future__ import annotations
import argparse
import json
import time

from .config import CROPS_DIR, DOCS_DIR, IsometricCamera, LANDMARKS, RENDERS_DIR
from .extract_scene import extract_scene
from .pixel_shader import SceneData, render_diorama, render_diorama_tiled_hires

CROP_SPECS = [
    ("lindt_hoc", "01_lindt_home_of_chocolate.png"),
    ("reformierte_kirche", "02_reformierte_kirche_dorf.png"),
    ("bendlikon_pier", "03_bendlikon_harbor_pier.png"),
    ("bahnhof_stockengut", "04_bahnhof_kilchberg_weinberg.png"),
    ("schooren_seebad", "05_schooren_seebad.png"),
    ("sanatorium_ridge", "06_sanatorium_ridge.png"),
]


def render_everything(
    mpp_full: float = 0.25,
    mpp_crop: float = 0.22,
    presets: tuple[str, ...] = ("day", "sunset", "night"),
    skip_crops: bool = False,
) -> None:
    extract_scene(force=False)
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
    CROPS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "data").mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "assets").mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    scene = SceneData()
    print(f"[render] Loaded Kilchberg 3D scene in {time.time() - t0:.1f}s")

    meta_out_p = DOCS_DIR / "data" / "kilchberg_interactive.json"
    for idx_p, pkey in enumerate(presets):
        t_p = time.time()
        need_meta = (pkey == "day") or (idx_p == 0 and not meta_out_p.exists())
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
        )
        if meta:
            meta_out_p.write_text(json.dumps(meta, separators=(",", ":")))
        mf = json.loads((tiles_dir / "manifest.json").read_text())
        print(
            f"[render] Ultra-HD Tiled Diorama ({pkey}): {mf['width']}x{mf['height']} px "
            f"({mf['cols']}x{mf['rows']} tiles @ {mpp_full:.2f} m/px) in {time.time() - t_p:.1f}s"
        )

    if not skip_crops:
        for lm_id, fname in CROP_SPECS:
            lm = next(x for x in LANDMARKS if x["id"] == lm_id)
            r = lm["crop_radius_m"]
            box_lv = (lm["e"] - r, lm["n"] - r * 1.15, lm["e"] + r, lm["n"] + r * 1.15)
            cam_c = IsometricCamera(mpp=mpp_crop)
            t_c = time.time()
            img_c, _ = render_diorama(scene, cam_c, preset_key="day", crop_box_lv95=box_lv, add_frame=True)
            out_c = CROPS_DIR / fname
            img_c.save(out_c, optimize=True)
            img_c.save(DOCS_DIR / "assets" / fname.replace(".png", ".webp"), format="WEBP", lossless=True, method=4)
            print(f"[render] Crop {fname}: {img_c.size[0]}x{img_c.size[1]} @ {mpp_crop:.2f} m/px ({time.time() - t_c:.1f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--presets", nargs="+", default=["day", "sunset", "night"])
    ap.add_argument("--mpp-full", type=float, default=0.25)
    ap.add_argument("--mpp-crop", type=float, default=0.22)
    ap.add_argument("--skip-crops", action="store_true")
    args = ap.parse_args()
    render_everything(
        mpp_full=args.mpp_full,
        mpp_crop=args.mpp_crop,
        presets=tuple(args.presets),
        skip_crops=args.skip_crops,
    )
