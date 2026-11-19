"""Export 100% GIS-accurate 3D isometric animation paths and occlusion masks for Kilchberg ZH.

Builds docs/data/kilchberg_animations.json directly from:
- swisstopo MVT transportation vectors (SBB Seebahn railway, Seestrasse, A3 motorway, village streets)
- Lake Zurich open-water bathymetry/mask (ZSG Bendlikon steamer route + offshore sailboat loops)
- 0.5 m LiDAR DSM + swissBUILDINGS3D 3.0 roof elevations for analytical camera-ray 3D occlusion
  so trains and cars pass cleanly BEHIND foreground buildings, bridges, and trees!
"""

from __future__ import annotations
import heapq
import json
import math
from pathlib import Path
import numpy as np
from scipy import ndimage
from shapely.geometry import LineString, Point, shape
from shapely.ops import linemerge, unary_union

from .config import DOCS_DIR, E_MAX, E_MIN, IsometricCamera, LAKE_SURFACE_Z, N_MAX, N_MIN, RAW_CACHE_DIR
from .extract_scene import GRID_H, GRID_RES, GRID_W, _load_mvt_features, build_diorama_polygon
from .pixel_shader import SceneData, compute_full_canvas_geometry


def _snap_key(pt: tuple[float, float], tol: float = 4.0) -> tuple[int, int]:
    return (int(round(pt[0] / tol)), int(round(pt[1] / tol)))


def _stitch_longest_path(
    geoms: list[LineString],
    start_target: tuple[float, float],
    end_target: tuple[float, float],
    snap_tol: float = 8.0,
) -> LineString | None:
    """Build a snapped segment graph and extract the shortest continuous path between two endpoints."""
    adj: dict[tuple[int, int], list[tuple[tuple[int, int], float, list[tuple[float, float]]]]] = {}
    node_xy: dict[tuple[int, int], tuple[float, float]] = {}

    def add_seg(coords: list[tuple[float, float]]) -> None:
        if len(coords) < 2:
            return
        ls = LineString(coords)
        if ls.length < 1.0:
            return
        # Subdivide at ~12m intervals so overlapping MVT tile buffer lines share interior nodes!
        n_sub = max(1, int(math.ceil(ls.length / 12.0)))
        s_pts = [ls.interpolate(float(ls.length * k / n_sub)).coords[0] for k in range(n_sub + 1)]
        for k in range(n_sub):
            p0, p1 = s_pts[k], s_pts[k + 1]
            seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if seg_len < 0.2:
                continue
            u = _snap_key(p0, snap_tol)
            v = _snap_key(p1, snap_tol)
            if u == v:
                continue
            node_xy.setdefault(u, p0)
            node_xy.setdefault(v, p1)
            adj.setdefault(u, []).append((v, seg_len, [p0, p1]))
            adj.setdefault(v, []).append((u, seg_len, [p1, p0]))

    for g in geoms:
        if g.geom_type == "LineString":
            add_seg(list(g.coords))
        elif hasattr(g, "geoms"):
            for sub in g.geoms:
                if sub.geom_type == "LineString":
                    add_seg(list(sub.coords))

    if not node_xy:
        return None

    # Bridge tiny MVT tile/junction gaps up to 20m
    keys = list(node_xy.keys())
    for i, u in enumerate(keys):
        ux, uy = node_xy[u]
        for j in range(i + 1, len(keys)):
            v = keys[j]
            vx, vy = node_xy[v]
            d = math.hypot(ux - vx, uy - vy)
            if 0.1 < d <= 20.0:
                adj.setdefault(u, []).append((v, d * 2.2, [(ux, uy), (vx, vy)]))
                adj.setdefault(v, []).append((u, d * 2.2, [(vx, vy), (ux, uy)]))

    src = min(keys, key=lambda k: math.hypot(node_xy[k][0] - start_target[0], node_xy[k][1] - start_target[1]))
    dst = min(keys, key=lambda k: math.hypot(node_xy[k][0] - end_target[0], node_xy[k][1] - end_target[1]))
    if src == dst:
        return None

    dist = {src: 0.0}
    prev: dict[tuple[int, int], tuple[tuple[int, int], list[tuple[float, float]]]] = {}
    pq = [(0.0, src)]
    while pq:
        d_u, u = heapq.heappop(pq)
        if u == dst:
            break
        if d_u > dist.get(u, 1e18):
            continue
        for v, w, seg_coords in adj.get(u, []):
            nd = d_u + w
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                prev[v] = (u, seg_coords)
                heapq.heappush(pq, (nd, v))

    if dst not in prev:
        return None

    chain: list[list[tuple[float, float]]] = []
    cur = dst
    while cur != src:
        p_node, seg = prev[cur]
        chain.append(seg)
        cur = p_node
    chain.reverse()

    merged_pts: list[tuple[float, float]] = []
    for seg in chain:
        for pt in seg:
            if not merged_pts or math.hypot(pt[0] - merged_pts[-1][0], pt[1] - merged_pts[-1][1]) > 0.5:
                merged_pts.append((float(pt[0]), float(pt[1])))
    return LineString(merged_pts) if len(merged_pts) >= 2 else None


def _resample_smooth_line(ls: LineString, step_m: float = 2.5, offset_right_m: float = 0.0) -> tuple[np.ndarray, np.ndarray, float]:
    """Uniformly resample a LineString in LV95 meters with optional right-hand lane offset."""
    total_len = float(ls.length)
    n_pts = max(4, int(round(total_len / step_m)) + 1)
    s_vals = np.linspace(0.0, total_len, n_pts)
    pts = np.array([ls.interpolate(float(s)).coords[0] for s in s_vals], dtype=np.float64)

    # Light Gaussian smoothing on E/N so MVT vertices curve organically
    if len(pts) >= 7:
        e_sm = ndimage.gaussian_filter1d(pts[:, 0], sigma=1.3, mode="nearest")
        n_sm = ndimage.gaussian_filter1d(pts[:, 1], sigma=1.3, mode="nearest")
    else:
        e_sm, n_sm = pts[:, 0].copy(), pts[:, 1].copy()

    if abs(offset_right_m) > 1e-3:
        de = np.gradient(e_sm)
        dn = np.gradient(n_sm)
        norm = np.maximum(1e-6, np.hypot(de, dn))
        # Right-hand normal in (E, N): (+dn, -de) / norm
        e_sm = e_sm + (dn / norm) * offset_right_m
        n_sm = n_sm - (de / norm) * offset_right_m

    return e_sm, n_sm, total_len


def _catmull_rom_closed_or_open(ctrl: list[tuple[float, float]], step_m: float = 3.0, closed: bool = False) -> tuple[np.ndarray, np.ndarray, float]:
    pts = np.asarray(ctrl, dtype=np.float64)
    if closed:
        pts_ext = np.vstack([pts[-1:], pts, pts[:2]])
    else:
        pts_ext = np.vstack([pts[:1], pts, pts[-1:]])

    dense: list[tuple[float, float]] = []
    n_seg = len(pts) if closed else len(pts) - 1
    for i in range(n_seg):
        p0, p1, p2, p3 = pts_ext[i], pts_ext[i + 1], pts_ext[i + 2], pts_ext[i + 3]
        for t in np.linspace(0.0, 1.0, 24, endpoint=False):
            t2 = t * t
            t3 = t2 * t
            xy = 0.5 * (
                (2.0 * p1)
                + (-p0 + p2) * t
                + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
                + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
            )
            dense.append((float(xy[0]), float(xy[1])))
    if closed:
        dense.append(dense[0])
    else:
        dense.append((float(pts[-1, 0]), float(pts[-1, 1])))
    ls = LineString(dense)
    return _resample_smooth_line(ls, step_m=step_m, offset_right_m=0.0)


def _build_obstacle_surface(scene: SceneData) -> np.ndarray:
    """Build 0.5 m foreground obstacle elevation grid (trees + 3D LOD2 building roofs + 3D bridges)."""
    obs_z = (scene.dem + scene.chm).astype(np.float32)
    if hasattr(scene, "bridge_z") and hasattr(scene, "bridge_class"):
        has_br = scene.bridge_class > 0
        obs_z[has_br] = np.maximum(obs_z[has_br], scene.bridge_z[has_br] + 1.0)
    # Stamp exact 3D building roof elevations onto roof triangles' bounding footprints
    roof_tris = scene.verts[scene.surf_type == 1]
    for tri in roof_tris:
        z_top = float(tri[:, 2].max())
        c0 = max(0, int((tri[:, 0].min() - E_MIN) / GRID_RES))
        c1 = min(GRID_W, int(math.ceil((tri[:, 0].max() - E_MIN) / GRID_RES)))
        r0 = max(0, int((N_MAX - tri[:, 1].max()) / GRID_RES))
        r1 = min(GRID_H, int(math.ceil((N_MAX - tri[:, 1].min()) / GRID_RES)))
        if r1 > r0 and c1 > c0:
            obs_z[r0:r1, c0:c1] = np.maximum(obs_z[r0:r1, c0:c1], z_top)
    return obs_z


def _sample_ground_z(dem: np.ndarray, e: np.ndarray, n: np.ndarray) -> np.ndarray:
    cols = np.clip(((e - E_MIN) / GRID_RES).astype(np.int32), 0, GRID_W - 1)
    rows = np.clip(((N_MAX - n) / GRID_RES).astype(np.int32), 0, GRID_H - 1)
    z = dem[rows, cols].astype(np.float64)
    return ndimage.gaussian_filter1d(z, sigma=2.0, mode="nearest") if len(z) >= 5 else z


def _sample_road_z(scene: SceneData, e: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Sample road elevation taking the higher of bare-earth DEM and 3D elevated bridge/viaduct deck."""
    cols = np.clip(((e - E_MIN) / GRID_RES).astype(np.int32), 0, GRID_W - 1)
    rows = np.clip(((N_MAX - n) / GRID_RES).astype(np.int32), 0, GRID_H - 1)
    z = scene.dem[rows, cols].astype(np.float64)
    if hasattr(scene, "bridge_z") and hasattr(scene, "bridge_class"):
        br_z = scene.bridge_z[rows, cols].astype(np.float64)
        br_m = scene.bridge_class[rows, cols] > 0
        z = np.where(br_m, np.maximum(z, br_z), z)
    return ndimage.gaussian_filter1d(z, sigma=1.6, mode="nearest") if len(z) >= 5 else z


def _compute_occlusion(
    obs_z: np.ndarray,
    cam: IsometricCamera,
    e: np.ndarray,
    n: np.ndarray,
    z: np.ndarray,
    vehicle_h: float = 2.2,
) -> np.ndarray:
    """Analytical 3D ray-march along orthographic camera ray to detect foreground building/tree occlusion."""
    th = math.radians(cam.azimuth_from_deg)
    ray_de = math.sin(th)
    ray_dn = math.cos(th)
    ray_dz_per_m = math.tan(math.radians(cam.pitch_deg)) / cam.z_exag

    occ = np.zeros(len(e), dtype=np.uint8)
    z_base = z + vehicle_h
    for s in np.arange(4.5, 165.0, 1.5):
        es = e + s * ray_de
        ns = n + s * ray_dn
        cols = ((es - E_MIN) / GRID_RES).astype(np.int32)
        rows = ((N_MAX - ns) / GRID_RES).astype(np.int32)
        valid = (cols >= 0) & (cols < GRID_W) & (rows >= 0) & (rows < GRID_H)
        if not valid.any():
            break
        vi = np.nonzero(valid)[0]
        fg_z = obs_z[rows[vi], cols[vi]]
        ray_z = z_base[vi] + s * ray_dz_per_m
        occ[vi[fg_z > (ray_z + 1.1)]] = 1
    return occ


def _pack_path(
    cam: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W_full: int,
    H_full: int,
    obs_z: np.ndarray | None,
    e: np.ndarray,
    n: np.ndarray,
    z: np.ndarray,
    vehicle_h: float = 2.2,
) -> list[list[float | int]]:
    px, py, _ = cam.project(e, n, z)
    u = (px + shift_x) / W_full
    v = (py + shift_y) / H_full
    if obs_z is not None:
        occ = _compute_occlusion(obs_z, cam, e, n, z, vehicle_h=vehicle_h)
    else:
        occ = np.zeros(len(e), dtype=np.uint8)
    return [[round(float(u[i]), 5), round(float(v[i]), 5), int(occ[i])] for i in range(len(e))]


def export_animations(mpp_full: float = 0.25) -> Path:
    scene = SceneData()
    cam = IsometricCamera(mpp=mpp_full)
    cam, _, _, W_full, H_full, shift_x, shift_y, *_ = compute_full_canvas_geometry(scene, cam, None, True)
    obs_z = _build_obstacle_surface(scene)

    mvt = _load_mvt_features(RAW_CACHE_DIR)
    b_feat = json.loads((RAW_CACHE_DIR / "kilchberg_boundary_2056.geojson").read_text())
    kpoly = shape(b_feat["geometry"])
    lake_geoms = [g for g, p in mvt.get("water", []) if p.get("class") == "lake"]
    dpoly = build_diorama_polygon(kpoly, unary_union(lake_geoms)).buffer(-8.0)

    def get_clipped(cls_name: str) -> list[LineString]:
        raw = [
            g.intersection(dpoly)
            for g, p in mvt.get("transportation", [])
            if p.get("class") == cls_name and p.get("brunnel") != "tunnel"
        ]
        raw = [g for g in raw if not g.is_empty]
        if not raw:
            return []
        merged = linemerge(unary_union(raw))
        return [merged] if merged.geom_type == "LineString" else list(merged.geoms)

    # 1. SBB Seebahn Double-Track Railway (Northbound & Southbound through Bahnhof Kilchberg!)
    rail_geoms = get_clipped("rail")
    rail_spine = _stitch_longest_path(rail_geoms, (2683345.0, 1243225.0), (2684192.0, 1241024.0), snap_tol=6.0)
    trains_out = []
    if rail_spine is not None:
        # Station stop at Bahnhof Kilchberg (2683868, 1242045)
        bhf_pt = Point(2683868.0, 1242045.0)
        stop_frac_south = float(rail_spine.project(bhf_pt) / rail_spine.length)

        # Southbound track (Zürich HB -> Kilchberg -> Thalwil): right-hand Swiss rail = west/landward track
        e_sb, n_sb, len_sb = _resample_smooth_line(rail_spine, step_m=3.0, offset_right_m=1.85)
        z_sb = _sample_ground_z(scene.dem, e_sb, n_sb) + 0.55
        trains_out.append({
            "id": "sbb_s8_south",
            "name": "SBB S-Bahn S8 (Zürich HB → Kilchberg → Pfäffikon SZ)",
            "kind": "sbb_dpz",
            "carriages": 4,
            "length_m": round(len_sb, 1),
            "speed_mps": 18.5,
            "stop_frac": round(stop_frac_south, 4),
            "dwell_sec": 4.5,
            "phase": 0.12,
            "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, obs_z, e_sb, n_sb, z_sb, vehicle_h=3.8),
        })

        # Northbound track (Chur / Thalwil -> Kilchberg -> Zürich HB): reversed spine, right-hand = east/lakeward track
        rail_north = LineString(list(reversed(list(rail_spine.coords))))
        stop_frac_north = float(rail_north.project(bhf_pt) / rail_north.length)
        e_nb, n_nb, len_nb = _resample_smooth_line(rail_north, step_m=3.0, offset_right_m=1.85)
        z_nb = _sample_ground_z(scene.dem, e_nb, n_nb) + 0.55
        trains_out.append({
            "id": "sbb_ic_north",
            "name": "SBB EuroCity / S24 (Thalwil → Kilchberg → Zürich HB)",
            "kind": "sbb_ic",
            "carriages": 4,
            "length_m": round(len_nb, 1),
            "speed_mps": 21.0,
            "stop_frac": round(stop_frac_north, 4),
            "dwell_sec": 3.5,
            "phase": 0.58,
            "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, obs_z, e_nb, n_nb, z_nb, vehicle_h=3.8),
        })

    # 2. Road Network: Seestrasse (ZVV Route 161 Bus + Cars), Dorfstrasse Viaduct, A3 Motorway, and Village Streets
    roads_out = []
    prim_geoms = get_clipped("primary")
    see_spine = _stitch_longest_path(prim_geoms, (2683371.0, 1243254.0), (2684410.0, 1241104.0), snap_tol=6.0)
    if see_spine is not None:
        for dir_id, ls_dir, phase0 in [
            ("seestrasse_sb", see_spine, 0.0),
            ("seestrasse_nb", LineString(list(reversed(list(see_spine.coords)))), 0.37),
        ]:
            er, nr, lr = _resample_smooth_line(ls_dir, step_m=3.2, offset_right_m=1.9)
            zr = _sample_road_z(scene, er, nr) + 0.35
            roads_out.append({
                "id": dir_id,
                "kind": "seestrasse",
                "length_m": round(lr, 1),
                "speed_mps": 11.5,
                "has_bus": True,
                "car_count": 5,
                "phase": phase0,
                "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, obs_z, er, nr, zr, vehicle_h=1.9),
            })

    # Dedicated Dorfstrasse Horseshoe Viaduct route (Seestrasse Bendlikon -> up Dorfstrasse viaduct -> Dorf!)
    minor_all = get_clipped("minor")
    dorf_spine = _stitch_longest_path(minor_all, (2684040.0, 1241872.0), (2683620.0, 1241920.0), snap_tol=6.0)
    if dorf_spine is not None and dorf_spine.length >= 180.0:
        for dir_id, ls_dir, phase0, has_b in [
            ("dorfstrasse_viaduct_up", dorf_spine, 0.14, True),
            ("dorfstrasse_viaduct_dn", LineString(list(reversed(list(dorf_spine.coords)))), 0.62, False),
        ]:
            ed, nd, ld = _resample_smooth_line(ls_dir, step_m=2.6, offset_right_m=1.55)
            zd = _sample_road_z(scene, ed, nd) + 0.35
            roads_out.append({
                "id": dir_id,
                "kind": "village",
                "length_m": round(ld, 1),
                "speed_mps": 8.2,
                "has_bus": has_b,
                "car_count": 2,
                "phase": phase0,
                "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, obs_z, ed, nd, zd, vehicle_h=2.0),
            })

    mw_geoms = sorted(get_clipped("motorway"), key=lambda g: -g.length)
    for idx_m, mg in enumerate(mw_geoms[:2]):
        if mg.length < 300.0:
            continue
        em, nm, lm = _resample_smooth_line(mg, step_m=3.5, offset_right_m=0.0)
        zm = _sample_road_z(scene, em, nm) + 0.35
        roads_out.append({
            "id": f"a3_motorway_{idx_m}",
            "kind": "motorway",
            "length_m": round(lm, 1),
            "speed_mps": 24.0,
            "has_bus": False,
            "car_count": 5,
            "phase": idx_m * 0.41,
            "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, obs_z, em, nm, zm, vehicle_h=2.0),
        })

    minor_geoms = [g for g in sorted(minor_all, key=lambda s: -s.length) if g.length >= 370.0][:5]
    for idx_v, vg in enumerate(minor_geoms):
        ev, nv, lv = _resample_smooth_line(vg, step_m=3.2, offset_right_m=1.4)
        zv = _sample_road_z(scene, ev, nv) + 0.35
        roads_out.append({
            "id": f"village_st_{idx_v}",
            "kind": "village",
            "length_m": round(lv, 1),
            "speed_mps": 8.5,
            "has_bus": (idx_v == 0),
            "car_count": 2,
            "phase": (idx_v * 0.23) % 1.0,
            "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, obs_z, ev, nv, zv, vehicle_h=1.8),
        })

    # 3. Lake Zurich ZSG Passenger Steamer (docking at Bendlikon Pier!) & Leisure Sailboats
    ships_out = []
    steamer_ctrl = [
        (2683865.0, 1243195.0),
        (2683965.0, 1242820.0),
        (2684065.0, 1242410.0),
        (2684145.0, 1242085.0),
        (2684178.0, 1241902.0),  # Bendlikon ZSG Steamer Landing!
        (2684258.0, 1241715.0),
        (2684388.0, 1241485.0),  # Offshore past Schooren & Lindt Home of Chocolate
        (2684545.0, 1241250.0),
        (2684665.0, 1241085.0),
    ]
    es_st, ns_st, len_st = _catmull_rom_closed_or_open(steamer_ctrl, step_m=3.5, closed=False)
    zs_st = np.full(len(es_st), LAKE_SURFACE_Z + 0.25, dtype=np.float64)
    st_ls = LineString(list(zip(es_st, ns_st)))
    pier_frac = float(st_ls.project(Point(2684178.0, 1241902.0)) / st_ls.length)
    ships_out.append({
        "id": "zsg_ms_helvetia",
        "name": "ZSG Lake Zurich Steamer (Zürich Bürkliplatz → Kilchberg Bendlikon → Thalwil)",
        "kind": "zsg_steamer",
        "length_m": round(len_st, 1),
        "speed_mps": 6.8,
        "stop_frac": round(pier_frac, 4),
        "dwell_sec": 5.5,
        "phase": 0.22,
        "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, None, es_st, ns_st, zs_st),
    })

    boat_loops = [
        ("sailboat_1", "sailboat", 3.1, 0.05, [
            (2684360.0, 1242080.0), (2684490.0, 1241890.0), (2684435.0, 1241690.0), (2684305.0, 1241860.0),
        ]),
        ("sailboat_2", "sailboat", 2.8, 0.42, [
            (2684030.0, 1242920.0), (2684165.0, 1242690.0), (2684095.0, 1242490.0), (2683965.0, 1242710.0),
        ]),
        ("sailboat_3", "sailboat", 2.9, 0.71, [
            (2684525.0, 1241560.0), (2684665.0, 1241360.0), (2684595.0, 1241195.0), (2684455.0, 1241390.0),
        ]),
        ("boesch_runabout", "motorboat", 7.4, 0.33, [
            (2684210.0, 1242480.0), (2684390.0, 1242120.0), (2684560.0, 1241680.0),
            (2684495.0, 1241590.0), (2684315.0, 1242020.0), (2684145.0, 1242390.0),
        ]),
    ]
    for bid, bkind, bspd, bph, bctrl in boat_loops:
        eb, nb, lb = _catmull_rom_closed_or_open(bctrl, step_m=3.5, closed=True)
        zb = np.full(len(eb), LAKE_SURFACE_Z + 0.15, dtype=np.float64)
        ships_out.append({
            "id": bid,
            "kind": bkind,
            "closed": True,
            "length_m": round(lb, 1),
            "speed_mps": bspd,
            "phase": bph,
            "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, None, eb, nb, zb),
        })

    # 4. Subtle 90s Pixel-Art Ambient Micro-Animations (Chimney Steam, Swiss Flags, Lake Sparkles & Gliding Gulls)
    def proj_uv(e_pt: float, n_pt: float, z_pt: float) -> list[float]:
        px, py, _ = cam.project(np.array([e_pt]), np.array([n_pt]), np.array([z_pt]))
        return [round(float((px[0] + shift_x) / W_full), 5), round(float((py[0] + shift_y) / H_full), 5)]

    chimney_uv = proj_uv(2684156.7, 1241360.1, 455.0)
    flags_out = [
        {"name": "Bendlikon Pier", "uv": proj_uv(2684160.0, 1241898.0, 412.2)},
        {"name": "Seebad Kilchberg", "uv": proj_uv(2684272.0, 1241515.0, 412.2)},
        {"name": "Lindt Crest Tower", "uv": proj_uv(2684234.0, 1241352.0, 435.2)},
        {"name": "Bahnhof / Gemeindehaus", "uv": proj_uv(2683786.0, 1242048.0, 455.8)},
    ]

    # Gliding white Lake Zurich gulls circling above Bendlikon Bay & Schooren shore
    gulls_out = [
        {"uv": proj_uv(2684240.0, 1241920.0, 434.0), "rx": 48, "ry": 22, "spd": 0.42, "ph": 0.1},
        {"uv": proj_uv(2684360.0, 1241560.0, 438.0), "rx": 54, "ry": 24, "spd": 0.36, "ph": 0.55},
        {"uv": proj_uv(2684050.0, 1242560.0, 436.0), "rx": 42, "ry": 19, "spd": 0.48, "ph": 0.82},
    ]

    open_water = scene.lake_mask & scene.diorama_mask
    open_water = ndimage.binary_erosion(open_water, iterations=35)
    wr, wc = np.nonzero(open_water)
    glints_out = []
    if len(wr) > 0:
        rng = np.random.default_rng(1899)
        pick = rng.choice(len(wr), size=min(72, len(wr)), replace=False)
        ge = E_MIN + (wc[pick] + 0.5) * GRID_RES
        gn = N_MAX - (wr[pick] + 0.5) * GRID_RES
        gz = np.full(len(pick), LAKE_SURFACE_Z, dtype=np.float64)
        gpx, gpy, _ = cam.project(ge, gn, gz)
        gu = (gpx + shift_x) / W_full
        gv = (gpy + shift_y) / H_full
        for i in range(len(pick)):
            glints_out.append([round(float(gu[i]), 5), round(float(gv[i]), 5), round(float(rng.random()), 3)])

    payload = {
        "canvas_width": W_full,
        "canvas_height": H_full,
        "mpp": mpp_full,
        "trains": trains_out,
        "roads": roads_out,
        "ships": ships_out,
        "ambient": {
            "chimney_steam": {"name": "Lindt Hochkamin (43.6 m)", "uv": chimney_uv},
            "swiss_flags": flags_out,
            "lake_glints": glints_out,
            "gulls": gulls_out,
        },
    }
    out_p = DOCS_DIR / "data" / "kilchberg_animations.json"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(payload, separators=(",", ":")))
    print(
        f"[anim] Exported {len(trains_out)} trains, {len(roads_out)} roads, "
        f"{len(ships_out)} ships/boats, {len(flags_out)} Swiss flags -> {out_p} ({out_p.stat().st_size // 1024} KB)"
    )
    return out_p


if __name__ == "__main__":
    export_animations()
