"""Download and cache all official swisstopo public datasets for Kilchberg (ZH).

Datasets fetched:
1. ch.swisstopo.swissboundaries3d (2026) — Official Kilchberg ZH polygon (BFS #0135)
2. ch.swisstopo.swissbuildings3d_3_0 (2025) — Watertight 3D LOD2 CityGML meshes
3. ch.swisstopo.swissalti3d (2026) — 0.5 m bare-earth LiDAR DTM GeoTIFFs
4. ch.swisstopo.swisssurface3d-raster (2024/25) — 0.5 m LiDAR DSM GeoTIFFs
5. ch.swisstopo.swissimage-dop10 (2025) — 10 cm true-color aerial orthophoto GeoTIFFs
6. ch.swisstopo.base.vt (z14 MVT) — Official swissTLM3D / swissNAMES3D / swissBATHY3D vectors
"""

from __future__ import annotations
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests
from pyproj import Transformer

from .config import RAW_CACHE_DIR


def fetch_all(cache_dir: Path = RAW_CACHE_DIR, workers: int = 8) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "alti3d").mkdir(exist_ok=True)
    (cache_dir / "surface3d").mkdir(exist_ok=True)
    (cache_dir / "swissimage").mkdir(exist_ok=True)
    (cache_dir / "mvt").mkdir(exist_ok=True)

    # 1. Municipal boundary (BFS #135 Kilchberg ZH)
    b_path = cache_dir / "kilchberg_boundary_2056.geojson"
    if not b_path.exists():
        url = (
            "https://api3.geo.admin.ch/rest/services/api/MapServer/"
            "ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill/135"
            "?geometryFormat=geojson&sr=2056"
        )
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        b_path.write_text(json.dumps(r.json()["feature"]))
        print(f"[boundary] Saved {b_path}")
    else:
        print(f"[boundary] Cached {b_path}")

    # 2. 3D Buildings LOD2 CityGML (sheets 1091-43 and 1111-21)
    for sheet in ("1091-43", "1111-21"):
        c_path = cache_dir / f"swissbuildings3d_{sheet}.citygml.zip"
        if not c_path.exists():
            url = (
                "https://data.geo.admin.ch/ch.swisstopo.swissbuildings3d_3_0/"
                f"swissbuildings3d_3_0_2025_{sheet}/"
                f"swissbuildings3d_3_0_2025_{sheet}_2056_5728.citygml.zip"
            )
            print(f"[buildings3d] Downloading {sheet}...")
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            c_path.write_bytes(r.content)
            print(f"[buildings3d] Saved {c_path} ({len(r.content)/1e6:.1f} MB)")
        else:
            print(f"[buildings3d] Cached {c_path}")

    # 3. MVT vector tiles (z=14, x=8580..8581, y=5740..5742)
    for x in (8580, 8581):
        for y in (5740, 5741, 5742):
            m_path = cache_dir / "mvt" / f"14_{x}_{y}.pbf"
            if not m_path.exists():
                url = f"https://vectortiles.geo.admin.ch/tiles/ch.swisstopo.base.vt/v1.0.0/14/{x}/{y}.pbf"
                r = requests.get(url, timeout=20)
                r.raise_for_status()
                m_path.write_bytes(r.content)
                print(f"[mvt] Saved {m_path.name}")

    # 4. 1km x 1km Raster tiles (swissALTI3D 0.5m, swissSURFACE3D 0.5m, SWISSIMAGE 0.1m/2m)
    tr = Transformer.from_crs(2056, 4326, always_xy=True)
    lon0, lat0 = tr.transform(2682000, 1240000)
    lon1, lat1 = tr.transform(2685900, 1243900)

    jobs = []
    for cid, subdir, res_tag in (
        ("ch.swisstopo.swissalti3d", "alti3d", "_0.5_"),
        ("ch.swisstopo.swisssurface3d-raster", "surface3d", "_0.5_"),
        ("ch.swisstopo.swissimage-dop10", "swissimage", "auto"),
    ):
        stac_url = (
            f"https://data.geo.admin.ch/api/stac/v1/collections/{cid}/items"
            f"?bbox={lon0},{lat0},{lon1},{lat1}&limit=200"
        )
        feats = requests.get(stac_url, timeout=20).json()["features"]
        by_tile = {}
        for f in feats:
            parts = f["id"].split("_")
            tile, yr = parts[-1], parts[1]
            if tile not in by_tile or yr > by_tile[tile][0]:
                by_tile[tile] = (yr, f)

        for t, (_, f) in sorted(by_tile.items()):
            if not (
                any(t.startswith(e) for e in ("2682-", "2683-", "2684-", "2685-"))
                and any(t.endswith(n) for n in ("-1240", "-1241", "-1242", "-1243"))
            ):
                continue
            if subdir == "surface3d" and t.startswith("2685-"):
                continue
            want = ("_2_" if t.startswith("2685-") else "_0.1_") if res_tag == "auto" else res_tag
            for ak, av in f["assets"].items():
                if ak.endswith(".tif") and want in ak:
                    outp = cache_dir / subdir / f"{t}.tif"
                    if not outp.exists():
                        jobs.append((subdir, t, av["href"], outp))

    if jobs:
        print(f"[rasters] Downloading {len(jobs)} missing GeoTIFF tiles...")

        def _dl(job):
            subdir, t, url, outp = job
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            outp.write_bytes(r.content)
            return f"{subdir}/{t}.tif ({len(r.content)/1e6:.1f} MB)"

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_dl, j) for j in jobs]
            for i, fut in enumerate(as_completed(futs), 1):
                msg = fut.result()
                if i % 6 == 0 or i == len(jobs):
                    print(f"  [{i}/{len(jobs)}] {msg}")
    else:
        print("[rasters] All 44 high-resolution GeoTIFF tiles already cached.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path, default=RAW_CACHE_DIR)
    args = ap.parse_args()
    fetch_all(args.cache_dir)
