"""Automated verification checks for all Kilchberg ZH pixel-art renders and interactive assets."""

from __future__ import annotations
import json
from pathlib import Path
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
        assert w >= 4000 and h >= 1900, f"Unexpected dimensions for {p.name}: {w}x{h}"
        arr = np.asarray(img)
        std = float(arr.std())
        min_std = 18.0 if mode == "night" else 28.0
        assert std > min_std, f"Low visual contrast ({std:.1f}) in {p.name}"
        wp = DOCS_DIR / "assets" / f"diorama_{mode}.webp"
        assert wp.exists() and wp.stat().st_size > 100_000, f"Missing/empty web asset {wp}"
        print(f"[ok] {p.name}: {w}x{h} px, std={std:.1f}, size={p.stat().st_size/1e6:.2f} MB")

    for _, fname in CROP_SPECS:
        cp = CROPS_DIR / fname
        assert cp.exists(), f"Missing crop {cp}"
        img = Image.open(cp)
        w, h = img.size
        assert w >= 1500 and h >= 1200, f"Unexpected crop size {fname}: {w}x{h}"
        print(f"[ok] crop {fname}: {w}x{h} px ({cp.stat().st_size/1e6:.2f} MB)")

    meta_p = DOCS_DIR / "data" / "kilchberg_interactive.json"
    assert meta_p.exists(), "Missing interactive metadata JSON"
    meta = json.loads(meta_p.read_text())
    assert len(meta["landmarks"]) == 10, "Expected 10 landmarks"
    assert len(meta["buildings"]) >= 1800, f"Expected >=1800 interactive buildings, got {len(meta['buildings'])}"
    print(f"[ok] interactive metadata: {len(meta['landmarks'])} landmarks, {len(meta['buildings'])} clickable 3D buildings")


if __name__ == "__main__":
    verify_all()
