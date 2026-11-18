"""Automated verification checks for all Kilchberg ZH pixel-art renders, tile pyramids, and GIS metadata."""

from __future__ import annotations
import json
import numpy as np
from PIL import Image

from .config import CROPS_DIR, DOCS_DIR, RENDERS_DIR
from .render_all import CROP_SPECS


def verify_all() -> None:
    for mode in ("day", "sunset", "night"):
        p = RENDERS_DIR / f"kilchberg_diorama_{mode}.png"
        assert p.exists(), f"Missing {p}"
        img = Image.open(p)
        w, h = img.size
        assert w >= 5500 and h >= 2500, f"Unexpected dimensions for {p.name}: {w}x{h}"
        arr = np.asarray(img)
        std = float(arr.std())
        min_std = 18.0 if mode == "night" else 28.0
        assert std > min_std, f"Low visual contrast ({std:.1f}) in {p.name}"

        wp = DOCS_DIR / "assets" / f"diorama_{mode}.webp"
        assert wp.exists() and wp.stat().st_size > 100_000, f"Missing/empty web overview {wp}"

        tdir = DOCS_DIR / "assets" / "tiles" / mode
        mf_p = tdir / "manifest.json"
        assert mf_p.exists(), f"Missing tile manifest {mf_p}"
        mf = json.loads(mf_p.read_text())
        assert mf["width"] >= 11500 and mf["height"] >= 5200, f"Expected >=11.5k x 5.2k tiled canvas, got {mf}"
        n_tiles = mf["cols"] * mf["rows"]
        existing_tiles = list(tdir.glob("*.webp"))
        assert len(existing_tiles) == n_tiles, f"Expected {n_tiles} tiles in {tdir}, found {len(existing_tiles)}"
        tiles_mb = sum(tp.stat().st_size for tp in existing_tiles) / 1e6
        print(
            f"[ok] {mode}: master={mf['width']}x{mf['height']} px ({mf['mpp']} m/px), "
            f"{n_tiles} tiles ({tiles_mb:.2f} MB), png={w}x{h} ({p.stat().st_size/1e6:.2f} MB)"
        )

    for _, fname in CROP_SPECS:
        cp = CROPS_DIR / fname
        assert cp.exists(), f"Missing crop {cp}"
        img = Image.open(cp)
        w, h = img.size
        assert w >= 2000 and h >= 1400, f"Unexpected crop size {fname}: {w}x{h}"
        print(f"[ok] crop {fname}: {w}x{h} px ({cp.stat().st_size/1e6:.2f} MB)")

    meta_p = DOCS_DIR / "data" / "kilchberg_interactive.json"
    assert meta_p.exists(), "Missing interactive metadata JSON"
    meta = json.loads(meta_p.read_text())
    assert len(meta["landmarks"]) == 10, "Expected 10 landmarks"
    assert len(meta["buildings"]) >= 1800, f"Expected >=1800 interactive buildings, got {len(meta['buildings'])}"
    print(f"[ok] interactive metadata: {len(meta['landmarks'])} landmarks, {len(meta['buildings'])} clickable 3D buildings")


if __name__ == "__main__":
    verify_all()
