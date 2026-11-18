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
from shapely.affinity import translate
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, shape
from shapely.ops import unary_union

from .config import E_MAX, E_MIN, LAKE_SURFACE_Z, N_MAX, N_MIN, RAW_CACHE_DIR
from .fetch_data import fetch_all

GRID_RES = 0.5  # 0.5 meter ground grid cells!
GRID_W = int(round((E_MAX - E_MIN) / GRID_RES))  # 4280
GRID_H = int(round((N_MAX - N_MIN) / GRID_RES))  # 5920

# Semantic ground codes
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


def _ensure_v2_rasters(cache_dir: Path, bldg_npz: Path) -> None:
    """Ensure 25cm SWISSIMAGE texture atlas and exact 2D building roof mask exist."""
    ortho25_p = cache_dir / "ortho_25cm.npy"
    roof_mask_p = cache_dir / "bldg_roof_mask_05m.npy"
    if not ortho25_p.exists():
        print("[scene] Building 25 cm SWISSIMAGE DOP10 true-color texture atlas (ortho_25cm.npy)...")
        w25 = int(round((E_MAX - E_MIN) / 0.25))
        h25 = int(round((N_MAX - N_MIN) / 0.25))
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

    if not roof_mask_p.exists() and bldg_npz.exists():
        print("[scene] Rasterizing exact 0.5m LOD2 building roof mask (bldg_roof_mask_05m.npy)...")
        b = np.load(bldg_npz)
        verts = b["verts"]
        stype = b["surf_type"]
        rv = verts[stype == 1][:, :, :2]
        tfm = from_bounds(E_MIN, N_MIN, E_MAX, N_MAX, GRID_W, GRID_H)
        polys = [Polygon(tri) for tri in rv if Polygon(tri).area > 0.02]
        rmask = rasterize([(g.buffer(0.35), 1) for g in polys], out_shape=(GRID_H, GRID_W), transform=tfm, dtype=np.uint8) > 0
        np.save(roof_mask_p, rmask)


def extract_scene(cache_dir: Path = RAW_CACHE_DIR, force: bool = False) -> Path:
    scene_npz = cache_dir / "scene_kilchberg_05m.npz"
    bldg_npz = cache_dir / "buildings_kilchberg_3d.npz"
    meta_json = cache_dir / "buildings_kilchberg_meta.json"
    if scene_npz.exists() and bldg_npz.exists() and meta_json.exists() and not force:
        _ensure_v2_rasters(cache_dir, bldg_npz)
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

    print("[scene] Mosaicking 0.5m swissSURFACE3D LiDAR canopy surface...")
    dsm = _mosaic_tiles(cache_dir, "surface3d", bands=1, dtype=np.float32)
    dsm_nan = np.isnan(dsm) | (dsm < 300.0)
    dsm[dsm_nan] = dem[dsm_nan]
    chm = np.maximum(0.0, dsm - dem)

    print("[scene] Mosaicking 10cm SWISSIMAGE DOP10 true-color orthophotos to 0.5m...")
    ortho = _mosaic_tiles(cache_dir, "swissimage", bands=3, dtype=np.uint8)

    print("[scene] Rasterizing semantic vector ground, streets, rail, pools & bathymetry...")
    diorama_mask = rasterize([(diorama_poly, 1)], out_shape=(GRID_H, GRID_W), transform=tfm, dtype=np.uint8) > 0
    kpoly_mask = rasterize([(kpoly, 1)], out_shape=(GRID_H, GRID_W), transform=tfm, dtype=np.uint8) > 0
    lake_mask = rasterize([(g, 1) for g in lake_geoms], out_shape=(GRID_H, GRID_W), transform=tfm, dtype=np.uint8) > 0

    # Clamp DEM on Lake Zurich to exact lake surface level
    dem[lake_mask] = LAKE_SURFACE_Z

    # Interpolate Lake Zurich underwater bathymetry from swisstopo bathymetry polygons + shoreline distance
    bathy_depth = np.zeros((GRID_H, GRID_W), dtype=np.float32)
    dist_offshore_m = ndimage.distance_transform_edt(lake_mask).astype(np.float32) * GRID_RES
    # Smooth baseline shelf + glacial drop-off calibrated to Zürichsee Kilchberg profile
    bathy_depth[lake_mask] = np.minimum(125.0, 0.14 * dist_offshore_m[lake_mask] + 0.00022 * (dist_offshore_m[lake_mask] ** 2))
    for g, p in mvt.get("bathymetry", []):
        d_val = abs(float(p.get("lake_depth", 0.0)))
        if d_val > 0:
            bm = rasterize([(g, 1)], out_shape=(GRID_H, GRID_W), transform=tfm, dtype=np.uint8) > 0
            bathy_depth[bm & lake_mask] = np.maximum(bathy_depth[bm & lake_mask], d_val)
    bathy_depth = ndimage.gaussian_filter(bathy_depth, sigma=6.0)
    bathy_depth[~lake_mask] = 0.0
    bathy_z = LAKE_SURFACE_Z - bathy_depth

    # Semantic ground rasterization (painter's order from broad landcover to crisp roads/rails/pools)
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
    _burn([g for g, p in mvt.get("landuse", []) if p.get("class") == "parking"], G_STREET_MINOR)

    # Waterways / streams
    _burn([g.buffer(1.4) for g, p in mvt.get("waterway", []) if p.get("class") == "stream"], G_STREAM)

    # Surface transportation (strictly excluding underground tunnels!)
    foot_geoms, minor_geoms, main_geoms, mw_geoms, rail_geoms = [], [], [], [], []
    for g, p in mvt.get("transportation", []):
        if p.get("brunnel") == "tunnel" or int(p.get("layer", 0)) < 0:
            continue
        cls = p.get("class")
        if cls in ("footway", "path", "track"):
            foot_geoms.append(g.buffer(1.15))
        elif cls in ("service", "minor", "tertiary"):
            minor_geoms.append(g.buffer(2.7 if cls != "service" else 1.9))
        elif cls in ("primary", "secondary"):
            main_geoms.append(g.buffer(4.1))
        elif cls == "motorway":
            mw_geoms.append(g.buffer(5.5 if not p.get("ramp") else 3.4))
        elif cls in ("rail", "transit"):
            rail_geoms.append(g.buffer(2.6))

    _burn(foot_geoms, G_FOOTPATH)
    _burn(minor_geoms, G_STREET_MINOR)
    _burn(main_geoms, G_STREET_MAIN)
    _burn(mw_geoms, G_MOTORWAY)
    _burn(rail_geoms, G_RAILWAY)
    _burn([g.buffer(0.6) for g, _ in mvt.get("construct", [])], G_PLATFORM_PIER)

    # Swimming pools & Lake Zurich on top
    pool_geoms = [g for g, p in mvt.get("water", []) if p.get("class") == "pool"]
    _burn(pool_geoms, G_POOL)
    sem[lake_mask] = G_LAKE

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
    print("[scene] Extracting 3D LOD2 CityGML triangles & sampling 10cm SWISSIMAGE roof colors...")
    ns_bldg = "{http://www.opengis.net/citygml/building/2.0}"
    ns_gml = "{http://www.opengis.net/gml}"
    ns_gen = "{http://www.opengis.net/citygml/generics/2.0}"

    tri_verts = []      # (N, 3, 3) float32
    tri_normals = []    # (N, 3) float32
    tri_bldg_idx = []   # (N,) int32
    tri_surf_type = []  # 0=Wall, 1=Roof
    tri_rgb = []        # (N, 3) uint8
    buildings_meta = []
    bldg_footprints_2d = []

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

                    # Quick check first posList
                    first_pos = elem.find(".//" + ns_gml + "posList")
                    if first_pos is None or not first_pos.text:
                        elem.clear()
                        continue
                    fvals = [float(v) for v in first_pos.text.split()[:3]]
                    if not (diorama_prep_box[0] - 30 <= fvals[0] <= diorama_prep_box[2] + 30 and
                            diorama_prep_box[1] - 30 <= fvals[1] <= diorama_prep_box[3] + 30):
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

                    # Extract roof and wall rings
                    b_tris_v = []
                    b_tris_st = []
                    roof_sample_rgbs = []

                    for st_code, st_tag in ((1, "RoofSurface"), (0, "WallSurface")):
                        for surf in elem.findall(".//" + ns_bldg + st_tag):
                            for pos in surf.findall(".//" + ns_gml + "posList"):
                                if not pos.text:
                                    continue
                                coords = np.fromstring(pos.text, sep=" ", dtype=np.float64)
                                if coords.size < 12 or coords.size % 3 != 0:
                                    continue
                                pts = coords.reshape(-1, 3)[:-1]  # Drop closing vertex
                                if len(pts) < 3:
                                    continue
                                # Fan triangulate ring (almost all swisstopo rings are already 3-vertex triangles!)
                                v0 = pts[0]
                                for i in range(1, len(pts) - 1):
                                    b_tris_v.append((v0, pts[i], pts[i + 1]))
                                    b_tris_st.append(st_code)

                    if not b_tris_v:
                        elem.clear()
                        continue

                    b_arr = np.asarray(b_tris_v, dtype=np.float64)  # (M, 3, 3)
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
                    bldg_footprints_2d.append(box(emin - 0.5, nmin - 0.5, emax + 0.5, nmax + 0.5))

                    # Compute normals and sample SWISSIMAGE DOP10 roof colors
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

                    # Orient roof normals upward (nz >= 0), wall normals outward from building center
                    roof_m = st_arr == 1
                    flip_r = roof_m & (norms[:, 2] < 0)
                    norms[flip_r] *= -1.0

                    wall_m = st_arr == 0
                    tri_centers = b_arr.mean(axis=1)
                    out_vec = tri_centers[:, :2] - np.array([[cx, cy]])
                    dot_out = norms[:, 0] * out_vec[:, 0] + norms[:, 1] * out_vec[:, 1]
                    flip_w = wall_m & (dot_out < 0)
                    norms[flip_w] *= -1.0

                    # Sample SWISSIMAGE RGB at roof triangle centroids
                    rc = tri_centers[roof_m]
                    if len(rc) > 0:
                        cols = np.clip(((rc[:, 0] - E_MIN) / GRID_RES).astype(np.int32), 0, GRID_W - 1)
                        rows = np.clip(((N_MAX - rc[:, 1]) / GRID_RES).astype(np.int32), 0, GRID_H - 1)
                        sampled = ortho[rows, cols]  # (K, 3)
                        med_roof = np.median(sampled, axis=0).astype(np.uint8)
                    else:
                        med_roof = np.array([175, 110, 88], dtype=np.uint8)

                    t_rgb = np.empty((len(b_arr), 3), dtype=np.uint8)
                    if roof_m.any():
                        cols = np.clip(((tri_centers[roof_m, 0] - E_MIN) / GRID_RES).astype(np.int32), 0, GRID_W - 1)
                        rows = np.clip(((N_MAX - tri_centers[roof_m, 1]) / GRID_RES).astype(np.int32), 0, GRID_H - 1)
                        # Blend 65% building median roof color + 35% per-triangle ortho color for cohesive roofs!
                        per_tri = ortho[rows, cols].astype(np.float32)
                        t_rgb[roof_m] = np.clip(0.62 * med_roof.astype(np.float32) + 0.38 * per_tri, 0, 255).astype(np.uint8)

                    # Wall base color: warm Swiss plaster / limestone / brick / sandstone tuned to building type & roof
                    r_r, r_g, r_b = int(med_roof[0]), int(med_roof[1]), int(med_roof[2])
                    if objektart == "Hochkamin":
                        wall_col = (168, 92, 72)   # Historic red-ochre industrial brick smokestack
                    elif objektart == "Lagertank":
                        wall_col = (212, 216, 220) # Brushed steel / white silo
                    elif objektart in ("Sakrales Gebaeude", "Sakraler Turm"):
                        wall_col = (234, 228, 212) # Warm historic church limestone/plaster
                    elif objektart == "Treibhaus":
                        wall_col = (182, 214, 224) # Glass greenhouse
                    else:
                        # Subtle deterministic variation of Swiss facade tones (cream, warm stucco, pale ochre, modern white)
                        h_seed = (int(cx * 7 + cy * 13) % 7)
                        facade_palette = [
                            (235, 229, 216),  # Warm Swiss chalk plaster
                            (228, 218, 198),  # Cream sand stucco
                            (240, 238, 233),  # Crisp modernist white (villas / Lindt HoC)
                            (218, 204, 182),  # Ochre village plaster
                            (208, 212, 215),  # Cool limestone grey
                            (225, 208, 194),  # Rose-warm plaster
                            (186, 156, 126),  # Timber / chalet upper facade
                        ]
                        # Large modern flat-roofed buildings lean crisp architectural white/limestone
                        if (emax - emin) * (nmax - nmin) > 1800 and abs(r_r - r_b) < 22:
                            wall_col = (238, 235, 228)
                        else:
                            wall_col = facade_palette[h_seed]
                    t_rgb[wall_m] = wall_col

                    tri_verts.append(b_arr.astype(np.float32))
                    tri_normals.append(norms.astype(np.float32))
                    tri_bldg_idx.append(np.full(len(b_arr), b_idx, dtype=np.int32))
                    tri_surf_type.append(st_arr)
                    tri_rgb.append(t_rgb)

                    # Nearest address & neighborhood
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

    # Enrich buildings_meta with nearest street, housenumber, and neighborhood using vectorized lookup
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

    # 6. Extract real individual trees from 0.5m LiDAR CHM (outside building footprints)
    print("[scene] Extracting real LiDAR tree crowns & moored Lake Zurich boats...")
    bldg_mask = rasterize(
        [(g.buffer(1.2), 1) for g in bldg_footprints_2d],
        out_shape=(GRID_H, GRID_W),
        transform=tfm,
        dtype=np.uint8,
    ) > 0

    # Vegetation index from 10cm->0.5m SWISSIMAGE RGB
    r_ch = ortho[:, :, 0].astype(np.float32)
    g_ch = ortho[:, :, 1].astype(np.float32)
    b_ch = ortho[:, :, 2].astype(np.float32)
    greenness = g_ch - 0.52 * r_ch - 0.42 * b_ch
    is_veg = (greenness > 6.0) | ((g_ch > r_ch) & (g_ch > b_ch) & (g_ch > 32.0))

    canopy_chm = ndimage.gaussian_filter(chm, sigma=1.1)
    valid_tree = diorama_mask & (~bldg_mask) & (~lake_mask) & (canopy_chm >= 2.2) & is_veg
    local_max = (canopy_chm == ndimage.maximum_filter(canopy_chm, size=9)) & valid_tree
    tr_rows, tr_cols = np.nonzero(local_max)

    tree_e = E_MIN + (tr_cols + 0.5) * GRID_RES
    tree_n = N_MAX - (tr_rows + 0.5) * GRID_RES
    tree_z = dem[tr_rows, tr_cols]
    tree_h = np.clip(chm[tr_rows, tr_cols], 2.2, 32.0)
    tree_rad = np.clip(1.1 + 0.24 * tree_h, 1.4, 6.2).astype(np.float32)
    tree_rgb = ortho[tr_rows, tr_cols]
    print(f"[scene] Detected {len(tree_e)} real LiDAR trees across Kilchberg ZH!")

    # 7. Detect real moored boats on Lake Zurich from SWISSIMAGE DOP10
    offshore_zone = diorama_mask & lake_mask & (dist_offshore_m > 10.0) & (dist_offshore_m < 240.0) & (sem != G_PLATFORM_PIER)
    lum = 0.30 * r_ch + 0.59 * g_ch + 0.11 * b_ch
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
                    # Orientation via covariance
                    if len(cc) >= 5:
                        cov = np.cov(cc, -rr)
                        eigvals, eigvecs = np.linalg.eigh(cov)
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
        tree_e=tree_e.astype(np.float32),
        tree_n=tree_n.astype(np.float32),
        tree_z=tree_z.astype(np.float32),
        tree_h=tree_h.astype(np.float32),
        tree_rad=tree_rad.astype(np.float32),
        tree_rgb=tree_rgb,
    )
    np.savez_compressed(
        bldg_npz,
        verts=all_verts,
        normals=all_norms,
        bldg_idx=all_bidx,
        surf_type=all_stype,
        rgb=all_rgb,
    )
    meta_json.write_text(json.dumps({"buildings": buildings_meta, "boats": boats}, indent=2))
    _ensure_v2_rasters(cache_dir, bldg_npz)
    print(f"[scene] Saved extracted scene -> {scene_npz.name}, {bldg_npz.name}, {meta_json.name}")
    return scene_npz


if __name__ == "__main__":
    extract_scene(force=True)
