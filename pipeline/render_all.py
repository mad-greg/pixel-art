"""Master batch renderer for the Kilchberg ZH 3D Isometric Pixel-Art Diorama.

Generates:
1. Full Municipality Floating 3D Isometric Dioramas:
   - renders/kilchberg_diorama_day.png      (Swiss Crisp Midday)
   - renders/kilchberg_diorama_sunset.png   (Alpenglow Golden Sunset)
   - renders/kilchberg_diorama_night.png    (Zürichsee Lantern & Window-Lit Night)
2. Six Ultra-Fine 0.30 m/px 3D Isometric Landmark Detail Plates:
   - renders/crops/01_lindt_home_of_chocolate.png
   - renders/crops/02_reformierte_kirche_dorf.png
   - renders/crops/03_bendlikon_harbor_pier.png
   - renders/crops/04_bahnhof_kilchberg_weinberg.png
   - renders/crops/05_schooren_seebad.png
   - renders/crops/06_sanatorium_ridge.png
3. Interactive GIS Metadata & Web Assets in docs/data/
"""

from __future__ import annotations
import argparse
import json
import time
from PIL import Image

from .config import CROPS_DIR, DOCS_DIR, IsometricCamera, LANDMARKS, RENDERS_DIR
from .extract_scene import extract_scene
from .pixel_shader import SceneData, render_diorama

CROP_SPECS = [
    ("lindt_hoc", "01_lindt_home_of_chocolate.png"),
    ("reformierte_kirche", "02_reformierte_kirche_dorf.png"),
    ("bendlikon_pier", "03_bendlikon_harbor_pier.png"),
    ("bahnhof_stockengut", "04_bahnhof_kilchberg_weinberg.png"),
    ("schooren_seebad", "05_schooren_seebad.png"),
    ("sanatorium_ridge", "06_sanatorium_ridge.png"),
]


def render_everything(mpp_full: float = 0.72, mpp_crop: float = 0.30, presets: tuple[str, ...] = ("day", "sunset", "night")) -> None:
    extract_scene(force=False)
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
    CROPS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "data").mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "assets").mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    scene = SceneData()
    print(f"[render] Loaded Kilchberg 3D scene in {time.time() - t0:.1f}s")

    cam_full = IsometricCamera(mpp=mpp_full)
    hit_metadata = None

    meta_out_p = DOCS_DIR / "data" / "kilchberg_interactive.json"
    for idx_p, pkey in enumerate(presets):
        t_p = time.time()
        need_meta = (pkey == "day") or (idx_p == 0 and not meta_out_p.exists())
        img, meta = render_diorama(
            scene,
            cam_full,
            preset_key=pkey,
            add_frame=True,
            collect_hit_boxes=need_meta,
        )
        if meta:
            hit_metadata = meta
            meta_out_p.write_text(json.dumps(hit_metadata, separators=(",", ":")))
        out_p = RENDERS_DIR / f"kilchberg_diorama_{pkey}.png"
        img.save(out_p, optimize=True)
        print(f"[render] Full diorama ({pkey}): {img.size[0]}x{img.size[1]} -> {out_p.name} ({time.time() - t_p:.1f}s)")

        # Save lossless crisp WebP copy for interactive web explorer
        web_img_p = DOCS_DIR / "assets" / f"diorama_{pkey}.webp"
        img.save(web_img_p, format="WEBP", lossless=True, method=4)

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
        print(f"[render] Crop {fname}: {img_c.size[0]}x{img_c.size[1]} ({time.time() - t_c:.1f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--presets", nargs="+", default=["day", "sunset", "night"])
    args = ap.parse_args()
    render_everything(presets=tuple(args.presets))
