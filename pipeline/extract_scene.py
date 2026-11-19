"""Fuse 0.5m LiDAR terrain/canopy, 10cm SWISSIMAGE orthophotos, CityGML 3D buildings,
and swisstopo MVT topography into a unified 3D scene for Kilchberg ZH."""

from __future__ import annotations
import json
import math
import zipfile
from pathlib import Path
import mapbox_vector_tile
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from lxml import etree
from pyproj import Transformer
from scipy import ndimage
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, shape
from shapely.ops import linemerge, unary_union

from .config import E_MAX, E_MIN, LAKE_SURFACE_Z, N_MAX, N_MIN, RAW_CACHE_DIR
from .fetch_data import fetch_all

GRID_RES = 0.5  # 0.5 meter ground grid cells!
GRID_W = int(round((E_MAX - E_MIN) / GRID_RES))  # 4280
GRID_H = int(round((N_MAX - N_MIN) / GRID_RES))  # 5920

# Semantic ground codes (surface layer <= 0)
G_TERRAIN = 0
G_LAKE = 1
G_STREAM = 2
G_POOL = 3
G_VINEYARD = 4
G_FOREST = 5
G_PARK_CEMETERY = 6
G_PITCH = 7
G_FOOTPATH = 8
G_STREET_MINOR = 9
G_STREET_MAIN = 10
G_MOTORWAY = 11
G_RAILWAY = 12
G_PLATFORM_PIER = 13
G_PARKING = 14

# Elevated 3D bridge / viaduct codes (layer >= 1)
BR_NONE = 0
BR_FOOTBRIDGE = 1
BR_ROAD_VIADUCT = 2
BR_MOTORWAY = 3
BR_RAIL_BRIDGE = 4
BR_STEPS = 5


def _tile_bounds_3857(x: int, y: int, z: int = 14):
    n = 2.0 ** z
    world = 20037508.342789244
    minx = -world + (x / n) * (2.0 * world)
    maxx = -world + ((x + 1) / n) * (2.0 * world)
    maxy = world - (y / n) * (2.0 * world)
    miny = world - ((y + 1) / n) * (2.0 * world)
    return minx, miny, maxx, maxy


def _load_mvt_features(cache_dir: Path):
    tr = Transformer.from_crs(3857, 2056, always_xy=True)
    layers: dict[str, list[tuple[object, dict]]] = {}
    clip_box = box(E_MIN - 100, N_MIN - 100, E_MAX + 100, N_MAX + 100)

    for x in (8580, 8581):
        for y in (5740, 5741, 5742):
            pbf = (cache_dir / "mvt" / f"14_{x}_{y}.pbf").read_bytes()
            minx, miny, maxx, maxy = _tile_bounds_3857(x, y, 14)
            decoded = mapbox_vector_tile.decode(pbf)

            for lname, ldata in decoded.items():
                ext = float(ldata.get("extent", 4096))

                def conv_pts(pts):
                    xs = minx + (np.asarray([p[0] for p in pts], dtype=np.float64) / ext) * (maxx - minx)
                    ys = miny + (np.asarray([p[1] for p in pts], dtype=np.float64) / ext) * (maxy - miny)
                    es, ns = tr.transform(xs, ys)
                    return list(zip(es, ns))

                out_list = layers.setdefault(lname, [])
                for feat in ldata["features"]:
                    props = feat["properties"]
                    g = feat["geometry"]
                    gtype = g["type"]
                    coords = g["coordinates"]
                    geom = None
                    try:
                        if gtype == "Point":
                            mx = minx + (coords[0] / ext) * (maxx - minx)
                            my = miny + (coords[1] / ext) * (maxy - miny)
                            geom = Point(*tr.transform(mx, my))
                        elif gtype == "MultiPoint":
                            pts = conv_pts(coords)
                            if pts:
                                geom = Point(pts[0])
                        elif gtype == "LineString":
                            pts = conv_pts(coords)
                            if len(pts) >= 2:
                                geom = LineString(pts)
                        elif gtype == "MultiLineString":
                            lines = [LineString(conv_pts(c)) for c in coords if len(c) >= 2]
                            if lines:
                                geom = unary_union(lines)
                        elif gtype == "Polygon":
                            ext_r = conv_pts(coords[0])
                            if len(ext_r) >= 4:
                                holes = [conv_pts(h) for h in coords[1:] if len(h) >= 4]
                                geom = Polygon(ext_r, holes).buffer(0)
                        elif gtype == "MultiPolygon":
                            polys = []
                            for poly in coords:
                                ext_r = conv_pts(poly[0])
                                if len(ext_r) >= 4:
                                    holes = [conv_pts(h) for h in poly[1:] if len(h) >= 4]
                                    polys.append(Polygon(ext_r, holes).buffer(0))
                            if polys:
                                geom = unary_union(polys)
                    except Exception:
                        geom = None

                    if geom is not None and not geom.is_empty and geom.intersects(clip_box):
                        out_list.append((geom, props))
    return layers


def _mosaic_tiles(cache_dir: Path, subdir: str, bands: int = 1, dtype=np.float32) -> np.ndarray:
    """Assemble 1km x 1km swisstopo GeoTIFF tiles onto our exact 0.5m LV95 grid."""
    if bands == 1:
        out = np.full((GRID_H, GRID_W), np.nan if dtype == np.float32 else 0, dtype=dtype)
    else:
        out = np.zeros((GRID_H, GRID_W, bands), dtype=dtype)

    for e_km in (2682, 2683, 2684, 2685):
        for n_km in (1240, 1241, 1242, 1243):
            tpath = cache_dir / subdir / f"{e_km}-{n_km}.tif"
            if not tpath.exists():
                continue
            tb_min_e = e_km * 1000.0
            tb_max_e = (e_km + 1) * 1000.0
            tb_min_n = n_km * 1000.0
            tb_max_n = (n_km + 1) * 1000.0

            ie0 = max(E_MIN, tb_min_e)
            ie1 = min(E_MAX, tb_max_e)
            in0 = max(N_MIN, tb_min_n)
            in1 = min(N_MAX, tb_max_n)
            if ie1 <= ie0 or in1 <= in0:
                continue

            # Destination slice in out (row 0 = N_MAX, row GRID_H = N_MIN)
            c0 = int(round((ie0 - E_MIN) / GRID_RES))
            c1 = int(round((ie1 - E_MIN) / GRID_RES))
            r0 = int(round((N_MAX - in1) / GRID_RES))
            r1 = int(round((N_MAX - in0) / GRID_RES))
            dh, dw = r1 - r0, c1 - c0

            with rasterio.open(tpath) as ds:
                win = rasterio.windows.from_bounds(ie0, in0, ie1, in1, transform=ds.transform)
                if bands == 1:
                    arr = ds.read(
                        1,
                        window=win,
                        out_shape=(dh, dw),
                        resampling=Resampling.bilinear,
                    )
                    out[r0:r1, c0:c1] = arr
                else:
                    arr = ds.read(
                        [1, 2, 3],
                        window=win,
                        out_shape=(3, dh, dw),
                        resampling=Resampling.average,
                    )
                    out[r0:r1, c0:c1, :] = np.transpose(arr, (1, 2, 0))
    return out


def build_diorama_polygon(kpoly: MultiPolygon | Polygon, lake_poly: MultiPolygon | Polygon) -> Polygon:
    """Create the carved floating diorama footprint:
    - Exact official Municipality of Kilchberg (ZH) (+16m bevel so border buildings stay whole)
    - Plus a 430m foreground strip of Lake Zurich perpendicular to Kilchberg's 2.3 km shoreline!
    """
    land_part = kpoly.buffer(16.0, join_style=2)

    # Kilchberg's shoreline runs NNW (~334.8°); offshore ENE normal is (+0.905, +0.425)
    # Build a clean architectural museum-prism cut across Lake Zurich ~440m offshore!
    s0 = (2684468.0, 1241001.0)  # Southern shore boundary (Rotfarb / Sulzergut)
    n0 = (2683545.0, 1243312.0)  # Northern shore boundary (Horn / Stadtgrenze)
    nx_off, ny_off = 0.9063, 0.4226  # Unit offshore vector (65° ENE)
    # Straight outer aquarium cut line 430m offshore from mean shoreline
    p_se = (s0[0] + 390.0 * nx_off, s0[1] + 390.0 * ny_off)
    p_ne = (n0[0] + 520.0 * nx_off, n0[1] + 520.0 * ny_off)
    prism = Polygon([
        (s0[0] - 250.0 * nx_off, s0[1] - 250.0 * ny_off),
        p_se,
        p_ne,
        (n0[0] - 250.0 * nx_off, n0[1] - 250.0 * ny_off),
    ])
    lake_part = prism.intersection(lake_poly.buffer(3.0))
    combined = unary_union([land_part, lake_part]).buffer(3.0, join_style=2).buffer(-3.0, join_style=2)
    if isinstance(combined, MultiPolygon):
        combined = max(combined.geoms, key=lambda g: g.area)
    return combined


def _iter_linestrings(geom) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom] if geom.length > 0.2 else []
    if hasattr(geom, "geoms"):
        out = []
        for sub in geom.geoms:
            out.extend(_iter_linestrings(sub))
        return out
    return []


def _ensure_v2_rasters(cache_dir: Path, bldg_npz: Path, force: bool = False) -> None:
    """Ensure 25cm SWISSIMAGE texture atlas, exact 2D building roof mask, and 25cm roof parapet edge step exist."""
    ortho25_p = cache_dir / "ortho_25cm.npy"
    roof_mask_p = cache_dir / "bldg_roof_mask_05m.npy"
    roof_edge25_p = cache_dir / "roof_edge_step_25cm.npy"

    w25 = int(round((E_MAX - E_MIN) / 0.25))
    h25 = int(round((N_MAX - N_MIN) / 0.25))

    if not ortho25_p.exists():
        print("[scene] Building 25 cm SWISSIMAGE DOP10 true-color texture atlas (ortho_25cm.npy)...")
        out25 = np.zeros((h25, w25, 3), dtype=np.uint8)
        for e_km in (2682, 2683, 2684, 2685):
            for n_km in (1240, 1241, 1242, 1243):
                tp = cache_dir / "swissimage" / f"{e_km}-{n_km}.tif"
                if not tp.exists():
                    continue
                ie0, ie1 = max(E_MIN, e_km * 1000.0), min(E_MAX, (e_km + 1) * 1000.0)
                in0, in1 = max(N_MIN, n_km * 1000.0), min(N_MAX, (n_km + 1) * 1000.0)
                if ie1 <= ie0 or in1 <= in0:
                    continue
                c0 = int(round((ie0 - E_MIN) / 0.25))
                c1 = int(round((ie1 - E_MIN) / 0.25))
                r0 = int(round((N_MAX - in1) / 0.25))
                r1 = int(round((N_MAX - in0) / 0.25))
                with rasterio.open(tp) as ds:
                    win = rasterio.windows.from_bounds(ie0, in0, ie1, in1, transform=ds.transform)
                    arr = ds.read([1, 2, 3], window=win, out_shape=(3, r1 - r0, c1 - c0), resampling=Resampling.average)
                    out25[r0:r1, c0:c1, :] = np.transpose(arr, (1, 2, 0))
        np.save(ortho25_p, out25)

    if (force or not roof_mask_p.exists() or not roof_edge25_p.exists()) and bldg_npz.exists():
        print("[scene] Rasterizing exact LOD2 building roof mask & 25cm parapet rim bands...")
        b = np.load(bldg_npz)
        verts = b["verts"]
        stype = b["surf_type"]
        bidx = b["bldg_idx"]
        rm = stype == 1
        rv = verts[rm][:, :, :2]
        rb = bidx[rm]

        tfm05 = from_bounds(E_MIN, N_MIN, E_MAX, N_MAX, GRID_W, GRID_H)
        shapes_id = []
        polys_05 = []
        for tri, bid in zip(rv, rb):
            p = Polygon(tri)
            if p.area > 0.015:
                polys_05.append((p.buffer(0.25), 1))
                shapes_id.append((p, int(bid) + 1))

        rmask = rasterize(polys_05, out_shape=(GRID_H, GRID_W), transform=tfm05, dtype=np.uint8) > 0
        np.save(roof_mask_p, rmask)

        # Rasterize building ID onto 25cm grid and compute fast perimeter bands:
        # 0 = outside, 1 = outer 0.50m coping rim, 2 = inner 0.50..0.85m parapet shadow band,
        # 3 = near-edge 0.85..1.35m, 4 = interior (>1.35m from roof perimeter)
        tfm25 = from_bounds(E_MIN, N_MIN, E_MAX, N_MAX, w25, h25)
        bmap25 = rasterize(shapes_id, out_shape=(h25, w25), transform=tfm25, dtype=np.int32)

        def _erode_same_id(cur_id: np.ndarray) -> np.ndarray:
            nxt = cur_id.copy()
            bad = np.zeros(cur_id.shape, dtype=np.bool_)
            bad[:, :-1] |= cur_id[:, :-1] != cur_id[:, 1:]
            bad[:, 1:] |= cur_id[:, 1:] != cur_id[:, :-1]
            bad[:-1, :] |= cur_id[:-1, :] != cur_id[1:, :]
            bad[1:, :] |= cur_id[1:, :] != cur_id[:-1, :]
            nxt[bad] = 0
            return nxt

        step = np.zeros((h25, w25), dtype=np.uint8)
        step[bmap25 > 0] = 1
        e1 = _erode_same_id(bmap25)       # > 0.25m
        e2 = _erode_same_id(e1)           # > 0.50m
        step[e2 > 0] = 2
        e3 = _erode_same_id(e2)           # > 0.75m
        step[e3 > 0] = 3
        e4 = _erode_same_id(_erode_same_id(e3))  # > 1.25m
        step[e4 > 0] = 4
        np.save(roof_edge25_p, step)


def _rasterize_centerline_field(
    lines_with_hw: list[tuple[LineString, float]],
    max_dist_m: float = 12.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Compute exact 0.5m Euclidean distance, arc-length s, half-width, and tangent angle
    to a set of LineStrings using fast C-speed distance_transform_edt."""
    seed_mask = np.zeros((GRID_H, GRID_W), dtype=np.bool_)
    seed_s = np.zeros((GRID_H, GRID_W), dtype=np.float32)
    seed_hw = np.zeros((GRID_H, GRID_W), dtype=np.float32)
    seed_ang = np.zeros((GRID_H, GRID_W), dtype=np.float32)

    s_accum = 0.0
    for ls, hw in lines_with_hw:
        length = float(ls.length)
        if length < 0.4:
            continue
        n_pts = max(2, int(math.ceil(length / 0.25)) + 1)
        s_local = np.linspace(0.0, length, n_pts, dtype=np.float32)
        coords = np.asarray(ls.coords, dtype=np.float64)
        seg_d = np.hypot(np.diff(coords[:, 0]), np.diff(coords[:, 1]))
        cum_d = np.concatenate([[0.0], np.cumsum(seg_d)])
        if cum_d[-1] < 0.2:
            continue
        es = np.interp(s_local, cum_d, coords[:, 0])
        ns = np.interp(s_local, cum_d, coords[:, 1])
        de = np.gradient(es)
        dn = np.gradient(ns)
        ang = np.arctan2(dn, de).astype(np.float32)

        cols = np.clip(((es - E_MIN) / GRID_RES).astype(np.int32), 0, GRID_W - 1)
        rows = np.clip(((N_MAX - ns) / GRID_RES).astype(np.int32), 0, GRID_H - 1)
        # Wider road wins if two centerlines cross at an intersection
        take = (~seed_mask[rows, cols]) | (hw >= seed_hw[rows, cols])
        rr, cc = rows[take], cols[take]
        seed_mask[rr, cc] = True
        seed_s[rr, cc] = s_accum + s_local[take]
        seed_hw[rr, cc] = hw
        seed_ang[rr, cc] = ang[take]
        s_accum = (s_accum + length + 10.0) % 10000.0

    if not seed_mask.any():
        return (
            np.full((GRID_H, GRID_W), max_dist_m, dtype=np.float16),
            np.zeros((GRID_H, GRID_W), dtype=np.float16),
            np.zeros((GRID_H, GRID_W), dtype=np.float16),
            np.zeros((GRID_H, GRID_W), dtype=np.float16),
        )

    dist_px, (ir, ic) = ndimage.distance_transform_edt(~seed_mask, return_indices=True)
    dist_m = np.minimum(max_dist_m, dist_px * GRID_RES).astype(np.float16)
    along_m = (seed_s[ir, ic] % 1024.0).astype(np.float16)
    hw_m = seed_hw[ir, ic].astype(np.float16)
    ang_r = seed_ang[ir, ic].astype(np.float16)
    return dist_m, along_m, hw_m, ang_r


def _extend_bridge_ramp(
    bridge_ls: LineString,
    surf_roads: list[LineString],
    dem: np.ndarray,
    dsm: np.ndarray,
    max_ext_m: float = 16.0,
) -> LineString:
    """Extend road bridge endpoints by up to 16m along connecting approach roads where DSM > DEM + 0.30m,
    so viaduct ramps (such as Dorfstrasse Viaduct NE & SW approaches) meet ground roads with zero step!"""
    coords = list(bridge_ls.coords)

    def _sample_diff(e_pt: float, n_pt: float) -> float:
        c = int(np.clip((e_pt - E_MIN) / GRID_RES, 0, GRID_W - 1))
        r = int(np.clip((N_MAX - n_pt) / GRID_RES, 0, GRID_H - 1))
        return float(dsm[r, c] - dem[r, c])

    for at_start in (True, False):
        ep = coords[0] if at_start else coords[-1]
        if _sample_diff(ep[0], ep[1]) < 0.35:
            continue
        best_ext = []
        for rls in surf_roads:
            rc = list(rls.coords)
            d0 = math.hypot(rc[0][0] - ep[0], rc[0][1] - ep[1])
            d1 = math.hypot(rc[-1][0] - ep[0], rc[-1][1] - ep[1])
            if d0 <= 1.8 or d1 <= 1.8:
                ordered = rc if d0 <= d1 else list(reversed(rc))
                cand_ls = LineString(ordered)
                ext_pts = []
                for dist in np.arange(2.0, min(max_ext_m, cand_ls.length) + 0.1, 2.0):
                    pt = cand_ls.interpolate(float(dist)).coords[0]
                    ext_pts.append(pt)
                    if _sample_diff(pt[0], pt[1]) <= 0.22:
                        break
                if len(ext_pts) > len(best_ext):
                    best_ext = ext_pts
        if best_ext:
            if at_start:
                coords = list(reversed(best_ext)) + coords
            else:
                coords = coords + best_ext

    return LineString(coords)


def extract_scene(cache_dir: Path = RAW_CACHE_DIR, force: bool = False) -> Path:
    scene_npz = cache_dir / "scene_kilchberg_05m.npz"
    bldg_npz = cache_dir / "buildings_kilchberg_3d.npz"
    meta_json = cache_dir / "buildings_kilchberg_meta.json"
    if scene_npz.exists() and bldg_npz.exists() and meta_json.exists() and not force:
        _ensure_v2_rasters(cache_dir, bldg_npz, force=False)
        print(f"[scene] Using cached extracted scene at {scene_npz}")
        return scene_npz

    fetch_all(cache_dir)
    print("[scene] Loading boundary & MVT vector topography...")
    b_feat = json.loads((cache_dir / "kilchberg_boundary_2056.geojson").read_text())
    kpoly = shape(b_feat["geometry"])
    mvt = _load_mvt_features(cache_dir)

    lake_geoms = [g for g, p in mvt.get("water", []) if p.get("class") == "lake"]
    lake_poly = unary_union(lake_geoms) if lake_geoms else Polygon()
    diorama_poly = build_diorama_polygon(kpoly, lake_poly)

    tfm = from_bounds(E_MIN, N_MIN, E_MAX, N_MAX, GRID_W, GRID_H)

    print("[scene] Mosaicking 0.5m swissALTI3D bare-earth terrain...")
    dem = _mosaic_tiles(cache_dir, "alti3d", bands=1, dtype=np.float32)
    nan_mask = np.isnan(dem)
    if nan_mask.any():
        dem[nan_mask] = LAKE_SURFACE_Z

    print("[scene] Mosaicking 0.5m swissSURFACE3D LiDAR canopy & bridge surface...")
    dsm = _mosaic_tiles(cache_dir, "surface3d", bands=1, dtype=np.float32)
    dsm_nan = np.isnan(dsm) | (dsm < 300.0)
    dsm[dsm_nan] = dem[dsm_nan]
    chm = np.maximum(0.0, dsm - dem)

    print("[scene] Mosaicking 10cm SWISSIMAGE DOP10 true-color orthophotos to 0.5m...")
    ortho = _mosaic_tiles(cache_dir, "swissimage", bands=3, dtype=np.uint8)

    print("[scene] Rasterizing semantic vector ground, roads, rail, pools & 3D viaducts...")
    diorama_mask = rasterize([(diorama_poly, 1)], out_shape=(GRID_H, GRID_W), transform=tfm, dtype=np.uint8) > 0
    kpoly_mask = rasterize([(kpoly, 1)], out_shape=(GRID_H, GRID_W), transform=tfm, dtype=np.uint8) > 0
    lake_mask = rasterize([(g, 1) for g in lake_geoms], out_shape=(GRID_H, GRID_W), transform=tfm, dtype=np.uint8) > 0

    dem[lake_mask] = LAKE_SURFACE_Z

    # Interpolate Lake Zurich underwater bathymetry from swisstopo bathymetry polygons + shoreline distance
    bathy_depth = np.zeros((GRID_H, GRID_W), dtype=np.float32)
    dist_offshore_m = ndimage.distance_transform_edt(lake_mask).astype(np.float32) * GRID_RES
    bathy_depth[lake_mask] = np.minimum(125.0, 0.14 * dist_offshore_m[lake_mask] + 0.00022 * (dist_offshore_m[lake_mask] ** 2))
    for g, p in mvt.get("bathymetry", []):
        d_val = abs(float(p.get("lake_depth", 0.0)))
        if d_val > 0:
            bm = rasterize([(g, 1)], out_shape=(GRID_H, GRID_W), transform=tfm, dtype=np.uint8) > 0
            bathy_depth[bm & lake_mask] = np.maximum(bathy_depth[bm & lake_mask], d_val)
    bathy_depth = ndimage.gaussian_filter(bathy_depth, sigma=6.0)
    bathy_depth[~lake_mask] = 0.0
    bathy_z = LAKE_SURFACE_Z - bathy_depth

    # True Swiss road hierarchy directly from swisstopo MVT transportation classes:
    # - ONLY primary, secondary, tertiary (and Dorfstrasse Viaduct) are 2-lane main roads (G_STREET_MAIN)
    # - minor (route=11) -> medium residential Quartierstrasse (G_STREET_MINOR, NO dashed centerline)
    # - minor (route=None) / service -> narrow 1-lane residential lane / driveway (hw=1.85m, NO dashed centerline)
    # - footway / path / track / pedestrian / cycleway -> narrow warm gravel walking path (G_FOOTPATH, hw=1.05m)
    def _is_main_road(ls: LineString, props: dict) -> bool:
        cls = props.get("class")
        if cls in ("primary", "secondary", "tertiary"):
            return True
        # Dorfstrasse horseshoe viaduct (tagged minor + route=11 in MVT) is a real 2-lane collector viaduct
        if cls == "minor" and props.get("is_route") == 11 and props.get("brunnel") == "bridge":
            cx, cy = ls.centroid.x, ls.centroid.y
            if 2683890.0 <= cx <= 2684020.0 and 1241695.0 <= cy <= 1241820.0:
                return True
        return False

    def _is_pedestrian_overpass(ls: LineString, props: dict) -> bool:
        """Detect pedestrian/bicycle overpasses tagged as minor bridges (e.g. Bahnhof Kilchberg station overpass)."""
        cls = props.get("class")
        if cls in ("footway", "path", "track", "pedestrian", "cycleway"):
            return True
        if cls == "minor" and props.get("is_route") is None:
            cx, cy = ls.centroid.x, ls.centroid.y
            # Bahnhof Kilchberg station overpass (connects directly to station stairs!)
            if 2683800.0 <= cx <= 2683920.0 and 1242000.0 <= cy <= 1242140.0:
                return True
            # Narrow lakeside pedestrian bridge near Bendlikon
            if ls.length <= 15.0:
                return True
        return False

    sem = np.zeros((GRID_H, GRID_W), dtype=np.uint8)

    def _burn(shapes_list, code: int):
        if shapes_list:
            burned = rasterize(
                [(g, code) for g in shapes_list if g is not None and not g.is_empty],
                out_shape=(GRID_H, GRID_W),
                transform=tfm,
                dtype=np.uint8,
            )
            m = burned > 0
            sem[m] = burned[m]

    # Landuse / Landcover
    _burn([g for g, p in mvt.get("landcover", []) if p.get("class") == "wood"], G_FOREST)
    _burn([g for g, p in mvt.get("landuse", []) if p.get("class") in ("cemetery", "hospital", "school")], G_PARK_CEMETERY)
    _burn([g for g, p in mvt.get("landcover", []) if p.get("subclass") in ("park", "orchard", "plant_nursery")], G_PARK_CEMETERY)
    _burn([g for g, p in mvt.get("landcover", []) if p.get("subclass") == "vineyard"], G_VINEYARD)
    _burn([g for g, p in mvt.get("landuse", []) if p.get("class") in ("pitch", "sports")], G_PITCH)
    _burn([g for g, p in mvt.get("landuse", []) if p.get("class") == "parking"], G_PARKING)

    # Waterways / streams
    _burn([g.buffer(1.4) for g, p in mvt.get("waterway", []) if p.get("class") == "stream"], G_STREAM)

    # Partition MVT transportation into:
    # 1) Surface ground network (layer <= 0, not tunnel, not elevated bridge)
    # 2) Elevated 3D viaducts & bridges (brunnel == 'bridge' or layer > 0, not lake pier)
    foot_geoms, minor_geoms, main_geoms, mw_geoms, rail_surf_geoms = [], [], [], [], []
    road_centerlines_hw: list[tuple[LineString, float]] = []
    rail_all_centerlines: list[tuple[LineString, float]] = []
    surf_road_lines: list[LineString] = []

    raw_bridges_main_road: list[LineString] = []
    raw_bridges_local_road: list[LineString] = []
    raw_bridges_mw: list[LineString] = []
    raw_bridges_foot: list[LineString] = []
    raw_bridges_steps: list[LineString] = []
    raw_bridges_rail: list[LineString] = []
    pier_gangways: list[LineString] = []

    for g, p in mvt.get("transportation", []):
        if p.get("brunnel") == "tunnel" or int(p.get("layer", 0)) < 0:
            continue
        cls = p.get("class")
        subcls = p.get("subclass")
        is_elev = (p.get("brunnel") == "bridge") or (int(p.get("layer", 0)) > 0)

        for ls in _iter_linestrings(g):
            # Lake Zurich steamer pier gangways stay on G_PLATFORM_PIER
            if is_elev and lake_poly.buffer(1.5).contains(ls.centroid):
                pier_gangways.append(ls)
                continue

            if cls in ("rail", "transit"):
                rail_all_centerlines.append((ls, 2.35))
                if is_elev:
                    raw_bridges_rail.append(ls)
                else:
                    rail_surf_geoms.append(ls.buffer(2.55))
                continue

            if is_elev:
                if cls == "motorway":
                    raw_bridges_mw.append(ls)
                elif _is_pedestrian_overpass(ls, p):
                    if subcls == "steps":
                        raw_bridges_steps.append(ls)
                    else:
                        raw_bridges_foot.append(ls)
                elif cls in ("primary", "secondary", "tertiary", "minor", "service"):
                    if _is_main_road(ls, p):
                        raw_bridges_main_road.append(ls)
                    else:
                        raw_bridges_local_road.append(ls)
                continue

            # Surface ground transportation
            if cls in ("footway", "path", "track", "pedestrian", "cycleway"):
                foot_geoms.append(ls.buffer(1.05))
            elif cls == "motorway":
                hw = 5.4 if not p.get("ramp") else 3.4
                mw_geoms.append(ls.buffer(hw))
                road_centerlines_hw.append((ls, hw))
                surf_road_lines.append(ls)
            elif cls in ("primary", "secondary", "tertiary", "minor", "service"):
                if _is_main_road(ls, p):
                    hw = 4.35  # 3.15m 2-lane carriageway half-width + 1.20m raised stone sidewalk
                    main_geoms.append(ls.buffer(hw))
                    road_centerlines_hw.append((ls, hw))
                    surf_road_lines.append(ls)
                elif cls == "minor" and p.get("is_route") == 11:
                    hw = 2.55  # Medium residential Quartierstrasse (NO dashed centerline!)
                    minor_geoms.append(ls.buffer(hw))
                    road_centerlines_hw.append((ls, hw))
                    surf_road_lines.append(ls)
                else:
                    hw = 1.85  # Narrow 1-lane residential lane / driveway (e.g. Pilgerweg!)
                    minor_geoms.append(ls.buffer(hw))
                    road_centerlines_hw.append((ls, hw))
                    if cls == "minor":
                        surf_road_lines.append(ls)

    _burn(foot_geoms, G_FOOTPATH)
    _burn(minor_geoms, G_STREET_MINOR)
    _burn(main_geoms, G_STREET_MAIN)
    _burn(mw_geoms, G_MOTORWAY)
    _burn(rail_surf_geoms, G_RAILWAY)
    _burn([g.buffer(0.75) for g, _ in mvt.get("construct", [])] + [g.buffer(1.6) for g in pier_gangways], G_PLATFORM_PIER)

    print("[scene] Computing exact 0.5m vector road & SBB railway distance/tangent fields...")
    rail_dist, rail_along, _, rail_ang = _rasterize_centerline_field(rail_all_centerlines, max_dist_m=10.0)
    road_dist, road_along, road_hw, road_ang = _rasterize_centerline_field(road_centerlines_hw, max_dist_m=10.0)

    # Add Bahnhof Kilchberg SBB passenger platforms alongside tracks (E≈2683842..2683892, N≈1241990..1242125)
    rr_grid, cc_grid = np.meshgrid(np.arange(GRID_H, dtype=np.int32), np.arange(GRID_W, dtype=np.int32), indexing="ij")
    e_grid_1d = E_MIN + (np.arange(GRID_W, dtype=np.float64) + 0.5) * GRID_RES
    n_grid_1d = N_MAX - (np.arange(GRID_H, dtype=np.float64) + 0.5) * GRID_RES
    bhf_r0 = int(np.clip((N_MAX - 1242125.0) / GRID_RES, 0, GRID_H))
    bhf_r1 = int(np.clip((N_MAX - 1241990.0) / GRID_RES, 0, GRID_H))
    bhf_c0 = int(np.clip((2683835.0 - E_MIN) / GRID_RES, 0, GRID_W))
    bhf_c1 = int(np.clip((2683898.0 - E_MIN) / GRID_RES, 0, GRID_W))
    sub_rd = rail_dist[bhf_r0:bhf_r1, bhf_c0:bhf_c1]
    bhf_plat = (sub_rd >= 1.55) & (sub_rd <= 4.25)
    sem[bhf_r0:bhf_r1, bhf_c0:bhf_c1][bhf_plat] = G_PLATFORM_PIER

    # Swimming pools & Lake Zurich on top
    pool_geoms = [g for g, p in mvt.get("water", []) if p.get("class") == "pool"]
    _burn(pool_geoms, G_POOL)
    sem[lake_mask] = G_LAKE

    # Clean geometric Swiss yellow pedestrian crosswalk zones detected from SWISSIMAGE on streets
    r_ch = ortho[:, :, 0].astype(np.float32)
    g_ch = ortho[:, :, 1].astype(np.float32)
    b_ch = ortho[:, :, 2].astype(np.float32)
    raw_yel = (
        ((sem == G_STREET_MAIN) | (sem == G_STREET_MINOR))
        & (r_ch > 134.0)
        & (g_ch > 118.0)
        & ((r_ch - b_ch) >= 20.0)
        & ((g_ch - b_ch) >= 12.0)
    )
    lbl_xw, n_xw = ndimage.label(ndimage.binary_dilation(raw_yel, iterations=2))
    crosswalk_mask = np.zeros((GRID_H, GRID_W), dtype=np.bool_)
    if n_xw > 0:
        objs_xw = ndimage.find_objects(lbl_xw)
        for idx_x, sl in enumerate(objs_xw, 1):
            if sl is None:
                continue
            sub_x = lbl_xw[sl] == idx_x
            area_x = float(sub_x.sum()) * (GRID_RES ** 2)
            if 3.2 <= area_x <= 75.0:
                yr, xc = np.nonzero(sub_x)
                cr = int(round(sl[0].start + float(yr.mean())))
                cc = int(round(sl[1].start + float(xc.mean())))
                s_cent = float(road_along[cr, cc])
                r_lo, r_hi = max(0, cr - 12), min(GRID_H, cr + 13)
                c_lo, c_hi = max(0, cc - 12), min(GRID_W, cc + 13)
                ds = np.abs(road_along[r_lo:r_hi, c_lo:c_hi].astype(np.float32) - s_cent)
                in_road = (sem[r_lo:r_hi, c_lo:c_hi] == G_STREET_MAIN) | (sem[r_lo:r_hi, c_lo:c_hi] == G_STREET_MINOR)
                rd_sub = road_dist[r_lo:r_hi, c_lo:c_hi].astype(np.float32)
                hw_sub = np.minimum(3.2, road_hw[r_lo:r_hi, c_lo:c_hi].astype(np.float32) * 0.72)
                crosswalk_mask[r_lo:r_hi, c_lo:c_hi] |= in_road & (ds <= 1.85) & (rd_sub <= hw_sub)

    # -------------------------------------------------------------------------
    # Build 3D Elevated Viaducts & Bridges (Dorfstrasse Horseshoe Viaduct,
    # Bahnhofstrasse Bridge, Spiral Stairs, A3 Overpasses & SBB Rail Bridges!)
    # -------------------------------------------------------------------------
    print("[scene] Constructing 3D elevated viaducts, concrete piers & bridge decks...")
    bridge_cls = np.zeros((GRID_H, GRID_W), dtype=np.uint8)
    bridge_z = np.zeros((GRID_H, GRID_W), dtype=np.float32)
    bridge_sdist = np.zeros((GRID_H, GRID_W), dtype=np.float16)
    bridge_along = np.zeros((GRID_H, GRID_W), dtype=np.float16)
    bridge_hw = np.zeros((GRID_H, GRID_W), dtype=np.float16)
    bridge_ang = np.zeros((GRID_H, GRID_W), dtype=np.float16)
    bridge_id = np.zeros((GRID_H, GRID_W), dtype=np.uint8)
    viaduct_piers: list[dict] = []

    def _merge_group(lines: list[LineString]) -> list[LineString]:
        if not lines:
            return []
        u = unary_union(lines)
        if u.geom_type == "LineString":
            return [u] if u.length > 0.2 else []
        return _iter_linestrings(linemerge(u))

    # Process main bridges before steps so viaduct deck elevation is ready for connecting stairs!
    bridge_groups = [
        (BR_RAIL_BRIDGE, 3.05, False, _merge_group(raw_bridges_rail)),
        (BR_FOOTBRIDGE, 1.65, False, _merge_group(raw_bridges_foot)),
        (BR_ROAD_VIADUCT, 3.25, True, _merge_group(raw_bridges_local_road)),
        (BR_ROAD_VIADUCT, 4.95, True, _merge_group(raw_bridges_main_road)),  # Dorfstrasse Viaduct & main A3 bridges
        (BR_MOTORWAY, 5.80, True, _merge_group(raw_bridges_mw)),
        (BR_STEPS, 1.55, False, _merge_group(raw_bridges_steps)),
    ]

    cur_bid = 0
    for b_code, deck_hw, do_extend, merged_list in bridge_groups:
        for base_ls in merged_list:
            if not base_ls.intersects(diorama_poly):
                continue
            ls = _extend_bridge_ramp(base_ls, surf_road_lines, dem, dsm) if do_extend else base_ls
            total_l = float(ls.length)
            if total_l < 3.0:
                continue
            cur_bid = min(254, cur_bid + 1)

            n_samp = max(5, int(math.ceil(total_l / 0.20)) + 1)
            s_arr = np.linspace(0.0, total_l, n_samp, dtype=np.float64)
            c_arr = np.asarray([ls.interpolate(float(s)).coords[0] for s in s_arr], dtype=np.float64)
            de = np.gradient(c_arr[:, 0])
            dn = np.gradient(c_arr[:, 1])
            dlen = np.maximum(1e-6, np.hypot(de, dn))
            tx_b, ty_b = de / dlen, dn / dlen
            nx_b, ny_b = ty_b, -tx_b  # Right-hand normal
            ang_b = np.arctan2(ty_b, tx_b).astype(np.float32)

            scols = np.clip(((c_arr[:, 0] - E_MIN) / GRID_RES).astype(np.int32), 0, GRID_W - 1)
            srows = np.clip(((N_MAX - c_arr[:, 1]) / GRID_RES).astype(np.int32), 0, GRID_H - 1)
            dem_c = dem[srows, scols].astype(np.float64)
            dsm_c = dsm[srows, scols].astype(np.float64)

            if b_code == BR_STEPS:
                # Connect low ground end smoothly to elevated bridge deck (or DSM) at high end!
                r0_s, c0_s = srows[0], scols[0]
                r1_s, c1_s = srows[-1], scols[-1]
                nb0 = bridge_z[max(0, r0_s - 4) : min(GRID_H, r0_s + 5), max(0, c0_s - 4) : min(GRID_W, c0_s + 5)]
                nb1 = bridge_z[max(0, r1_s - 4) : min(GRID_H, r1_s + 5), max(0, c1_s - 4) : min(GRID_W, c1_s + 5)]
                z0 = float(nb0.max()) if nb0.max() > 100.0 else float(max(dem_c[0], min(dsm_c[0], dem_c[0] + 6.5)))
                z1 = float(nb1.max()) if nb1.max() > 100.0 else float(max(dem_c[-1], min(dsm_c[-1], dem_c[-1] + 6.5)))
                z_prof = np.linspace(z0, z1, n_samp)
            else:
                z0 = float(dem_c[0])
                z1 = float(dem_c[-1])
                # If bridge terminates at diorama edge mid-span, use DSM height
                if not diorama_poly.buffer(-3.0).contains(Point(c_arr[0])):
                    z0 = float(min(dsm_c[0], dem_c[0] + 8.0))
                if not diorama_poly.buffer(-3.0).contains(Point(c_arr[-1])):
                    z1 = float(min(dsm_c[-1], dem_c[-1] + 8.0))

                z_lin = np.linspace(z0, z1, n_samp)
                # Use real swissSURFACE3D bridge deck height, clamped against overhanging tree crowns!
                z_raw = np.clip(dsm_c, np.minimum(dem_c, z_lin), np.maximum(z_lin + 4.8, dem_c + 9.2))
                z_smooth = ndimage.gaussian_filter1d(ndimage.median_filter(z_raw, size=9), sigma=16.0, mode="nearest")

                # Guarantee minimum vertical clearance (>= 5.1m) directly over railways, motorways & underpass roads
                under_sem = sem[srows, scols]
                over_corridor = np.isin(under_sem, [G_RAILWAY, G_MOTORWAY, G_STREET_MAIN, G_STREET_MINOR])
                if over_corridor.any():
                    min_clear = dem_c + np.where(over_corridor, 5.1, 0.0)
                    min_clear = ndimage.gaussian_filter1d(np.maximum(z_smooth, min_clear), sigma=14.0, mode="nearest")
                    z_smooth = np.maximum(z_smooth, min_clear)

                # Smoothly pin exact abutment ends over outer 3.5m so road/rail transitions seamlessly
                taper = np.minimum(1.0, np.minimum(s_arr, total_l - s_arr) / 3.5)
                z_prof = (1.0 - taper) * z_lin + taper * np.maximum(z_smooth, dem_c)

            # Rasterize bridge strip inside tight bounding box
            min_e, min_n, max_e, max_n = ls.bounds
            pad = deck_hw + 1.2
            c_lo = max(0, int(math.floor((min_e - pad - E_MIN) / GRID_RES)))
            c_hi = min(GRID_W, int(math.ceil((max_e + pad - E_MIN) / GRID_RES)))
            r_lo = max(0, int(math.floor((N_MAX - (max_n + pad)) / GRID_RES)))
            r_hi = min(GRID_H, int(math.ceil((N_MAX - (min_n - pad)) / GRID_RES)))
            if c_hi <= c_lo or r_hi <= r_lo:
                continue

            ge_2d, gn_2d = np.meshgrid(e_grid_1d[c_lo:c_hi], n_grid_1d[r_lo:r_hi])
            ge_f = ge_2d.ravel()
            gn_f = gn_2d.ravel()

            # Nearest centerline vertex k in memory-safe chunks
            best_k = np.empty(len(ge_f), dtype=np.int32)
            best_d2 = np.full(len(ge_f), 1e18, dtype=np.float64)
            STEP_P = 8192
            for p0 in range(0, len(ge_f), STEP_P):
                p1 = min(len(ge_f), p0 + STEP_P)
                dx = ge_f[p0:p1, None] - c_arr[None, :, 0]
                dy = gn_f[p0:p1, None] - c_arr[None, :, 1]
                d2 = dx * dx + dy * dy
                kk = np.argmin(d2, axis=1)
                best_k[p0:p1] = kk
                best_d2[p0:p1] = d2[np.arange(p1 - p0), kk]

            # Exact longitudinal & signed lateral projection onto centerline tangent
            de_p = ge_f - c_arr[best_k, 0]
            dn_p = gn_f - c_arr[best_k, 1]
            along_off = de_p * tx_b[best_k] + dn_p * ty_b[best_k]
            s_exact = s_arr[best_k] + along_off
            sdist_exact = de_p * nx_b[best_k] + dn_p * ny_b[best_k]

            inside_deck = (
                (np.abs(sdist_exact) <= deck_hw)
                & (s_exact >= -0.25)
                & (s_exact <= total_l + 0.25)
            )
            if inside_deck.any():
                sub_r, sub_c = np.unravel_index(np.nonzero(inside_deck)[0], ge_2d.shape)
                gr_i = r_lo + sub_r
                gc_i = c_lo + sub_c
                z_here = z_prof[best_k[inside_deck]].astype(np.float32)

                # Only write elevated bridge where it rises above terrain (or over corridor) and beats lower bridge
                dem_here = dem[gr_i, gc_i]
                take = (z_here >= dem_here + 0.18) & (z_here >= bridge_z[gr_i, gc_i] - 0.05)
                if b_code == BR_STEPS:
                    take &= bridge_cls[gr_i, gc_i] == 0
                if take.any():
                    tr_i, tc_i = gr_i[take], gc_i[take]
                    idx_in = np.nonzero(inside_deck)[0][take]
                    bridge_cls[tr_i, tc_i] = b_code
                    bridge_z[tr_i, tc_i] = z_here[take]
                    bridge_sdist[tr_i, tc_i] = sdist_exact[idx_in].astype(np.float16)
                    bridge_along[tr_i, tc_i] = s_exact[idx_in].astype(np.float16)
                    bridge_hw[tr_i, tc_i] = np.float16(deck_hw)
                    bridge_ang[tr_i, tc_i] = ang_b[best_k[idx_in]].astype(np.float16)
                    bridge_id[tr_i, tc_i] = cur_bid

            # Place concrete viaduct support piers every ~21m where clearance >= 2.8m and clear of rail/road!
            if b_code in (BR_ROAD_VIADUCT, BR_MOTORWAY) and total_l >= 24.0:
                for sp_s in np.arange(12.0, total_l - 10.0, 21.0):
                    ki = int(np.argmin(np.abs(s_arr - sp_s)))
                    pe_c, pn_c = float(c_arr[ki, 0]), float(c_arr[ki, 1])
                    pc_i = int(np.clip((pe_c - E_MIN) / GRID_RES, 2, GRID_W - 3))
                    pr_i = int(np.clip((N_MAX - pn_c) / GRID_RES, 2, GRID_H - 3))
                    z_dk = float(z_prof[ki])
                    z_gd = float(dem[pr_i, pc_i])
                    if (z_dk - z_gd) < 2.8:
                        continue
                    nb_sem = sem[pr_i - 3 : pr_i + 4, pc_i - 3 : pc_i + 4]
                    if np.isin(nb_sem, [G_RAILWAY, G_MOTORWAY, G_STREET_MAIN, G_STREET_MINOR, G_LAKE, G_STREAM]).any():
                        continue
                    viaduct_piers.append({
                        "e": round(pe_c, 2),
                        "n": round(pn_c, 2),
                        "z_bot": round(z_gd, 2),
                        "z_top": round(z_dk - 1.25, 2),
                        "nx": round(float(nx_b[ki]), 4),
                        "ny": round(float(ny_b[ki]), 4),
                        "offset": round(deck_hw * 0.56, 2),
                        "bid": int(cur_bid),
                    })

    # Place SBB overhead steel catenary portals every ~52m along the railway corridor (clear of bridges!)
    catenary_portals: list[dict] = []
    rail_chains = sorted(_merge_group([ls for ls, _ in rail_all_centerlines]), key=lambda g: -g.length)
    bridge_clear_zone = ndimage.binary_dilation(
        np.isin(bridge_cls, [BR_ROAD_VIADUCT, BR_MOTORWAY, BR_FOOTBRIDGE, BR_STEPS]),
        iterations=14,
    )
    placed_cat_pts: list[tuple[float, float]] = []
    for rls in rail_chains[:4]:
        if rls.length < 120.0:
            continue
        for cs in np.arange(26.0, rls.length - 20.0, 52.0):
            pt = rls.interpolate(float(cs)).coords[0]
            if not diorama_poly.buffer(-6.0).contains(Point(pt)):
                continue
            if any(math.hypot(pt[0] - q[0], pt[1] - q[1]) < 34.0 for q in placed_cat_pts):
                continue
            cc_i = int(np.clip((pt[0] - E_MIN) / GRID_RES, 0, GRID_W - 1))
            cr_i = int(np.clip((N_MAX - pt[1]) / GRID_RES, 0, GRID_H - 1))
            if bridge_clear_zone[cr_i, cc_i]:
                continue
            p_prev = rls.interpolate(max(0.0, float(cs) - 2.0)).coords[0]
            p_next = rls.interpolate(min(float(rls.length), float(cs) + 2.0)).coords[0]
            dx_c, dy_c = p_next[0] - p_prev[0], p_next[1] - p_prev[1]
            dl_c = max(1e-6, math.hypot(dx_c, dy_c))
            nx_c, ny_c = dy_c / dl_c, -dx_c / dl_c
            z_b = float(bridge_z[cr_i, cc_i]) if bridge_cls[cr_i, cc_i] == BR_RAIL_BRIDGE else float(dem[cr_i, cc_i])
            placed_cat_pts.append(pt)
            catenary_portals.append({
                "e": round(float(pt[0]), 2),
                "n": round(float(pt[1]), 2),
                "z": round(z_b, 2),
                "nx": round(nx_c, 4),
                "ny": round(ny_c, 4),
                "span_hw": 4.2,
            })

    print(
        f"[scene] Built {cur_bid} elevated 3D bridges/viaducts, "
        f"{len(viaduct_piers)} concrete viaduct piers & {len(catenary_portals)} SBB catenary portals!"
    )

    # Collect street names & housenumbers for building metadata matching
    street_pts = []
    for g, p in mvt.get("transportation_name", []):
        nm = p.get("name")
        if nm:
            c = g.centroid
            street_pts.append((c.x, c.y, nm))
    house_pts = []
    for g, p in mvt.get("housenumber", []):
        hn = p.get("housenumber")
        if hn:
            c = g.centroid
            house_pts.append((c.x, c.y, str(hn)))
    place_pts = []
    for g, p in mvt.get("place", []):
        nm = p.get("name")
        if nm and p.get("class") == "neighbourhood":
            c = g.centroid
            place_pts.append((c.x, c.y, nm))

    # 5. Parse CityGML 3D LOD2 buildings (RoofSurface + WallSurface triangles)
    print("[scene] Extracting 3D LOD2 CityGML triangles & sampling clean roof colors...")
    ns_bldg = "{http://www.opengis.net/citygml/building/2.0}"
    ns_gml = "{http://www.opengis.net/gml}"
    ns_gen = "{http://www.opengis.net/citygml/generics/2.0}"

    tri_verts = []
    tri_normals = []
    tri_bldg_idx = []
    tri_surf_type = []
    tri_rgb = []
    buildings_meta = []

    seen_gml_ids = set()
    diorama_prep_box = diorama_poly.bounds

    for sheet in ("1091-43", "1111-21"):
        zpath = cache_dir / f"swissbuildings3d_{sheet}.citygml.zip"
        with zipfile.ZipFile(zpath) as zf:
            with zf.open(zf.namelist()[0]) as fp:
                for _, elem in etree.iterparse(fp, events=("end",), tag=ns_bldg + "Building"):
                    gml_id = elem.get(ns_gml + "id") or ""
                    if gml_id in seen_gml_ids:
                        elem.clear()
                        continue

                    first_pos = elem.find(".//" + ns_gml + "posList")
                    if first_pos is None or not first_pos.text:
                        elem.clear()
                        continue
                    fvals = [float(v) for v in first_pos.text.split()[:3]]
                    if not (
                        diorama_prep_box[0] - 30 <= fvals[0] <= diorama_prep_box[2] + 30
                        and diorama_prep_box[1] - 30 <= fvals[1] <= diorama_prep_box[3] + 30
                    ):
                        elem.clear()
                        continue

                    attrs = {}
                    for sa in elem.findall(".//" + ns_gen + "stringAttribute"):
                        k = sa.get("name")
                        val = sa.findtext(ns_gen + "value")
                        if k and val and k not in attrs:
                            attrs[k] = val
                    objektart = attrs.get("OBJEKTART", "Gebaeude Einzelhaus")
                    if objektart == "Unterirdisches Gebaeude":
                        elem.clear()
                        continue

                    b_tris_v = []
                    b_tris_st = []

                    for st_code, st_tag in ((1, "RoofSurface"), (0, "WallSurface")):
                        for surf in elem.findall(".//" + ns_bldg + st_tag):
                            for pos in surf.findall(".//" + ns_gml + "posList"):
                                if not pos.text:
                                    continue
                                coords = np.fromstring(pos.text, sep=" ", dtype=np.float64)
                                if coords.size < 12 or coords.size % 3 != 0:
                                    continue
                                pts = coords.reshape(-1, 3)[:-1]
                                if len(pts) < 3:
                                    continue
                                v0 = pts[0]
                                for i in range(1, len(pts) - 1):
                                    b_tris_v.append((v0, pts[i], pts[i + 1]))
                                    b_tris_st.append(st_code)

                    if not b_tris_v:
                        elem.clear()
                        continue

                    b_arr = np.asarray(b_tris_v, dtype=np.float64)
                    cx = float(b_arr[:, :, 0].mean())
                    cy = float(b_arr[:, :, 1].mean())
                    if not diorama_poly.contains(Point(cx, cy)):
                        elem.clear()
                        continue

                    seen_gml_ids.add(gml_id)
                    b_idx = len(buildings_meta)

                    zmin = float(b_arr[:, :, 2].min())
                    zmax = float(b_arr[:, :, 2].max())
                    emin, emax = float(b_arr[:, :, 0].min()), float(b_arr[:, :, 0].max())
                    nmin, nmax = float(b_arr[:, :, 1].min()), float(b_arr[:, :, 1].max())

                    st_arr = np.asarray(b_tris_st, dtype=np.uint8)
                    e1 = b_arr[:, 1, :] - b_arr[:, 0, :]
                    e2 = b_arr[:, 2, :] - b_arr[:, 0, :]
                    norms = np.cross(e1, e2)
                    nlen = np.linalg.norm(norms, axis=1, keepdims=True)
                    valid = nlen[:, 0] > 1e-5
                    b_arr = b_arr[valid]
                    st_arr = st_arr[valid]
                    norms = norms[valid] / np.maximum(nlen[valid], 1e-8)
                    if len(b_arr) == 0:
                        elem.clear()
                        continue

                    roof_m = st_arr == 1
                    flip_r = roof_m & (norms[:, 2] < 0)
                    norms[flip_r] *= -1.0

                    wall_m = st_arr == 0
                    tri_centers = b_arr.mean(axis=1)
                    out_vec = tri_centers[:, :2] - np.array([[cx, cy]])
                    dot_out = norms[:, 0] * out_vec[:, 0] + norms[:, 1] * out_vec[:, 1]
                    flip_w = wall_m & (dot_out < 0)
                    norms[flip_w] *= -1.0

                    rc = tri_centers[roof_m]
                    if len(rc) > 0:
                        cols = np.clip(((rc[:, 0] - E_MIN) / GRID_RES).astype(np.int32), 0, GRID_W - 1)
                        rows = np.clip(((N_MAX - rc[:, 1]) / GRID_RES).astype(np.int32), 0, GRID_H - 1)
                        sampled = ortho[rows, cols].astype(np.float32)
                        # Reject overhanging green tree branches unless >60% of roof is eco-green
                        not_tree = (sampled[:, 1] - sampled[:, 0]) <= 7.0
                        if not_tree.sum() >= max(1, int(0.40 * len(sampled))):
                            med_roof = np.median(sampled[not_tree], axis=0).astype(np.uint8)
                        else:
                            med_roof = np.median(sampled, axis=0).astype(np.uint8)
                    else:
                        med_roof = np.array([175, 110, 88], dtype=np.uint8)

                    t_rgb = np.empty((len(b_arr), 3), dtype=np.uint8)
                    if roof_m.any():
                        t_rgb[roof_m] = med_roof

                    r_r, r_g, r_b = int(med_roof[0]), int(med_roof[1]), int(med_roof[2])
                    t_rgb[wall_m] = (220, 214, 202)

                    tri_verts.append(b_arr.astype(np.float32))
                    tri_normals.append(norms.astype(np.float32))
                    tri_bldg_idx.append(np.full(len(b_arr), b_idx, dtype=np.int32))
                    tri_surf_type.append(st_arr)
                    tri_rgb.append(t_rgb)

                    in_k = bool(kpoly.contains(Point(cx, cy)))
                    buildings_meta.append({
                        "idx": b_idx,
                        "gml_id": gml_id,
                        "objektart": objektart,
                        "in_kilchberg": in_k,
                        "e": round(cx, 1),
                        "n": round(cy, 1),
                        "z_ground": round(zmin, 1),
                        "z_roof": round(zmax, 1),
                        "height": round(zmax - zmin, 1),
                        "footprint_w": round(emax - emin, 1),
                        "footprint_l": round(nmax - nmin, 1),
                        "roof_rgb": [r_r, r_g, r_b],
                    })
                    elem.clear()

    if buildings_meta:
        be = np.array([b["e"] for b in buildings_meta])
        bn = np.array([b["n"] for b in buildings_meta])
        if place_pts:
            pe = np.array([p[0] for p in place_pts])
            pn = np.array([p[1] for p in place_pts])
            for i, b in enumerate(buildings_meta):
                d2 = (pe - be[i]) ** 2 + (pn - bn[i]) ** 2
                b["neighbourhood"] = place_pts[int(np.argmin(d2))][2]
        if street_pts and house_pts:
            se = np.array([p[0] for p in street_pts])
            sn = np.array([p[1] for p in street_pts])
            he = np.array([p[0] for p in house_pts])
            hn_arr = np.array([p[1] for p in house_pts])
            for i, b in enumerate(buildings_meta):
                ds = (se - be[i]) ** 2 + (sn - bn[i]) ** 2
                si = int(np.argmin(ds))
                dh = (he - be[i]) ** 2 + (hn_arr - bn[i]) ** 2
                hi = int(np.argmin(dh))
                st_name = street_pts[si][2] if ds[si] < 160**2 else ""
                h_num = house_pts[hi][2] if dh[hi] < 32**2 else ""
                b["address"] = f"{st_name} {h_num}".strip()

    all_verts = np.concatenate(tri_verts, axis=0)
    all_norms = np.concatenate(tri_normals, axis=0)
    all_bidx = np.concatenate(tri_bldg_idx, axis=0)
    all_stype = np.concatenate(tri_surf_type, axis=0)
    all_rgb = np.concatenate(tri_rgb, axis=0)
    print(f"[scene] Extracted {len(buildings_meta)} 3D buildings ({len(all_verts)} triangles)!")

    np.savez_compressed(
        bldg_npz,
        verts=all_verts,
        normals=all_norms,
        bldg_idx=all_bidx,
        surf_type=all_stype,
        rgb=all_rgb,
    )
    _ensure_v2_rasters(cache_dir, bldg_npz, force=True)

    # 6. Extract exact individual real LiDAR trees & garden hedges (strictly clear of buildings, bridges, rail & roads!)
    print("[scene] Extracting individual 3D LiDAR tree entities, species & garden hedges...")
    exact_roof_mask = np.load(cache_dir / "bldg_roof_mask_05m.npy")
    bldg_excl = ndimage.binary_dilation(exact_roof_mask, iterations=2)
    bridge_excl = ndimage.binary_dilation(bridge_cls > 0, iterations=4)  # 2.0m strict buffer around every viaduct/bridge!
    hard_surface_excl = np.isin(
        sem,
        [G_LAKE, G_POOL, G_PITCH, G_STREET_MINOR, G_STREET_MAIN, G_MOTORWAY, G_RAILWAY, G_PLATFORM_PIER, G_PARKING],
    )
    non_veg = bldg_excl | bridge_excl | hard_surface_excl

    greenness = g_ch - 0.50 * r_ch - 0.44 * b_ch
    lum = 0.299 * r_ch + 0.587 * g_ch + 0.114 * b_ch
    # Note: SWISSIMAGE is early-spring (leaf-off for deciduous trees), so tall CHM outside non_veg is genuine tree canopy!
    is_veg_low = (greenness > 3.5) | ((g_ch > r_ch * 0.96) & (g_ch > 24.0) & (lum < 155.0))

    canopy_chm = ndimage.gaussian_filter(chm, sigma=0.85)
    valid_tree = diorama_mask & (~non_veg) & (canopy_chm >= 2.0) & ((canopy_chm >= 2.8) | is_veg_low)

    # Multi-scale crown peak detection: tighter spacing (2.5m) for smaller garden/fruit trees, 3.5m for large park trees
    max_small = canopy_chm == ndimage.maximum_filter(canopy_chm, size=5)
    max_large = canopy_chm == ndimage.maximum_filter(canopy_chm, size=7)
    peaks = valid_tree & (
        ((canopy_chm < 7.5) & max_small)
        | ((canopy_chm >= 7.5) & max_large)
    )
    tr_rows, tr_cols = np.nonzero(peaks)

    tree_e = (E_MIN + (tr_cols + 0.5) * GRID_RES).astype(np.float32)
    tree_n = (N_MAX - (tr_rows + 0.5) * GRID_RES).astype(np.float32)
    tree_z = dem[tr_rows, tr_cols].astype(np.float32)
    tree_h = np.clip(chm[tr_rows, tr_cols], 2.0, 30.0).astype(np.float32)

    # Measure local canopy compactness around each peak to distinguish slender cypresses/conifers from broad oaks
    chm_ave = ndimage.uniform_filter(chm, size=7)[tr_rows, tr_cols]
    compact_ratio = chm_ave / np.maximum(tree_h, 1.0)
    tree_rad = np.clip((0.95 + 0.215 * tree_h) * np.clip(0.75 + 0.42 * compact_ratio, 0.72, 1.15), 1.30, 5.10).astype(np.float32)

    # Classify species from leaf-off March SWISSIMAGE + crown geometry:
    # 0 = Lush Emerald Broadleaf (Oak / Beech / Sycamore)
    # 1 = Sunlit Warm-Lime Broadleaf (Linden / Maple / Orchard)
    # 2 = Alpine Spruce / Fir Conifer (already deep evergreen in early-spring SWISSIMAGE!)
    # 3 = Slender Cypress / Lombardy Poplar (slender crown along villas & cemetery)
    # 4 = Copper Beech / Blutbuche (majestic Zürichsee parkland estates)
    tr_r = r_ch[tr_rows, tr_cols]
    tr_g = g_ch[tr_rows, tr_cols]
    tr_b = b_ch[tr_rows, tr_cols]
    tr_lum = lum[tr_rows, tr_cols]
    tr_hash = ((tr_cols.astype(np.int64) * 73856093) ^ (tr_rows.astype(np.int64) * 19349663)) & 0xFFFF

    is_evergreen = ((tr_g > tr_r + 4.5) & (tr_lum < 86.0)) | ((sem[tr_rows, tr_cols] == G_FOREST) & ((tr_hash % 5) == 0))
    is_slender = (compact_ratio < 0.56) & (tree_h >= 5.5) & (~(sem[tr_rows, tr_cols] == G_FOREST))
    is_copper = (
        (~is_evergreen)
        & (~is_slender)
        & (tree_h >= 9.5)
        & (((tr_r > tr_g * 1.18) & (tr_r > 68.0)) | ((sem[tr_rows, tr_cols] == G_PARK_CEMETERY) & ((tr_hash % 19) == 3)) | ((tr_hash % 43) == 7))
    )

    tree_species = np.where(
        is_slender,
        3,
        np.where(
            is_evergreen,
            2,
            np.where(
                is_copper,
                4,
                np.where((tr_hash & 1) == 0, 0, 1),
            ),
        ),
    ).astype(np.uint8)
    # Narrow radius on slender cypresses & conifers so silhouettes read unmistakably
    tree_rad = np.where(tree_species == 3, np.clip(tree_h * 0.14, 0.95, 2.15), tree_rad).astype(np.float32)
    tree_rad = np.where(tree_species == 2, np.clip(tree_rad * 0.84, 1.25, 3.85), tree_rad).astype(np.float32)

    # Trimmed garden hedges & low shrubs (0.85m <= chm < 2.25m, strictly outside roads/bridges/buildings)
    hedge_mask = diorama_mask & (~non_veg) & (chm >= 0.85) & (chm < 2.25) & is_veg_low
    print(f"[scene] Extracted {len(tree_e):,} individual 3D trees & {int(hedge_mask.sum()):,} hedge cells across Kilchberg ZH!")

    # 7. Detect real moored boats on Lake Zurich from SWISSIMAGE DOP10
    offshore_zone = diorama_mask & lake_mask & (dist_offshore_m > 10.0) & (dist_offshore_m < 240.0) & (sem != G_PLATFORM_PIER)
    bg_lum = ndimage.median_filter(lum, size=25)
    boat_cand = offshore_zone & ((lum - bg_lum) > 34.0) & (lum > 95.0)
    lbl, n_comp = ndimage.label(boat_cand)
    boats = []
    if n_comp > 0:
        objs = ndimage.find_objects(lbl)
        for idx_c, sl in enumerate(objs, 1):
            if sl is None:
                continue
            sub = lbl[sl] == idx_c
            area_m2 = float(sub.sum()) * (GRID_RES ** 2)
            if 4.5 <= area_m2 <= 95.0:
                rr, cc = np.nonzero(sub)
                h_span = (rr.max() - rr.min() + 1) * GRID_RES
                w_span = (cc.max() - cc.min() + 1) * GRID_RES
                length_m = max(h_span, w_span)
                width_m = max(min(h_span, w_span), 1.5)
                if length_m / width_m <= 5.5 and length_m <= 18.0:
                    mr = sl[0].start + float(rr.mean())
                    mc = sl[1].start + float(cc.mean())
                    be_pt = E_MIN + (mc + 0.5) * GRID_RES
                    bn_pt = N_MAX - (mr + 0.5) * GRID_RES
                    if len(cc) >= 5:
                        cov = np.cov(cc, -rr)
                        _, eigvecs = np.linalg.eigh(cov)
                        vx, vy = eigvecs[:, -1]
                        angle = float(math.degrees(math.atan2(vy, vx)))
                    else:
                        angle = 25.0
                    boats.append({
                        "e": round(be_pt, 1),
                        "n": round(bn_pt, 1),
                        "length": round(float(length_m), 1),
                        "angle": round(angle, 1),
                        "sail": bool(length_m >= 6.2 and (idx_c % 3 != 0)),
                    })
    print(f"[scene] Detected {len(boats)} real moored boats in Kilchberg's Lake Zurich harbors!")

    np.savez_compressed(
        scene_npz,
        dem=dem,
        chm=chm.astype(np.float16),
        ortho=ortho,
        sem=sem,
        diorama_mask=diorama_mask,
        kpoly_mask=kpoly_mask,
        lake_mask=lake_mask,
        bathy_z=bathy_z,
        rail_dist=rail_dist,
        rail_along=rail_along,
        rail_ang=rail_ang,
        road_dist=road_dist,
        road_along=road_along,
        road_hw=road_hw,
        road_ang=road_ang,
        crosswalk_mask=crosswalk_mask.astype(np.uint8),
        bridge_cls=bridge_cls,
        bridge_z=bridge_z,
        bridge_sdist=bridge_sdist,
        bridge_along=bridge_along,
        bridge_hw=bridge_hw,
        bridge_ang=bridge_ang,
        bridge_id=bridge_id,
        hedge_mask=hedge_mask.astype(np.uint8),
        tree_e=tree_e,
        tree_n=tree_n,
        tree_z=tree_z,
        tree_h=tree_h,
        tree_rad=tree_rad,
        tree_species=tree_species,
    )
    meta_json.write_text(
        json.dumps(
            {
                "buildings": buildings_meta,
                "boats": boats,
                "viaduct_piers": viaduct_piers,
                "catenary_portals": catenary_portals,
            },
            indent=2,
        )
    )
    print(f"[scene] Saved extracted scene -> {scene_npz.name}, {bldg_npz.name}, {meta_json.name}")
    return scene_npz


if __name__ == "__main__":
    extract_scene(force=True)
