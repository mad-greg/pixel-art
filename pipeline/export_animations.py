"""Export 100% GIS-accurate 3D isometric animation paths and ambient anchors for Kilchberg ZH.

Builds docs/data/kilchberg_animations.json directly from cached official swisstopo datasets
(/tmp/kilchberg-cache/scene_kilchberg_05m.npz, buildings_kilchberg_3d.npz,
buildings_kilchberg_meta.json, and mvt/*.pbf) with zero external downloads and zero PNG hacks:
- SBB Seebahn double-track railway (true West/Gleis 2 & East/Gleis 1 tracks, strictly flat
  BR_RAIL_BRIDGE elevations, centered Bahnhof Kilchberg platform stops)
- All 8 edge-to-edge road lanes (Seestrasse NB/SB, Dorfstrasse Horseshoe Viaduct up/dn with
  smooth G1 Bezier junction fillets, A3 Motorway NB/SB, Alte Landstrasse EB/WB) clipped cleanly
  against scene.diorama_mask with class-filtered bilinear bridge_z, full 3D camera-ray occlusion,
  16-bit depth packing, and official ZVV/DIDOK bus stop fractions
- Lake Zurich ZSG steamer (edge-to-edge NE->SW path docking parallel to canonical Bendlikon Pier
  Badweg 1.1) plus 4 offshore leisure vessels and deterministic coastal shoreline extraction
- LV95-projected ambient anchors (Lindt Hochkamin, 10 residential pitched-roof village chimneys,
  3 village Dorfbrunnen fountains, 4 Swiss/Kilchberg flags, 4 open-water gull orbits, vignettes)
"""

from __future__ import annotations

import gc
import heapq
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rasterio.features import shapes as rio_shapes
from rasterio.transform import from_bounds
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, shape
from shapely.ops import linemerge, nearest_points, unary_union
from shapely.prepared import prep

from .config import (
    DOCS_DIR,
    E_MAX,
    E_MIN,
    IsometricCamera,
    LAKE_SURFACE_Z,
    N_MAX,
    N_MIN,
    RAW_CACHE_DIR,
)
from .extract_scene import (
    BR_MOTORWAY,
    BR_RAIL_BRIDGE,
    BR_ROAD_VIADUCT,
    GRID_H,
    GRID_RES,
    GRID_W,
    _load_mvt_features,
    build_diorama_polygon,
)
from .pixel_shader import compute_full_canvas_geometry

DEPTH_MIN = -2400.0
DEPTH_MAX = 2400.0

# Official swisstopo / ZVV DIDOK bus stop catalog in LV95 (Lines 161, 162, 165)
BUS_STOP_CATALOG: list[tuple[str, float, float]] = [
    ("Paradiesstrasse (Mönchhof)", 2683794.2, 1242581.3),
    ("Bendlikon",                  2684046.7, 1241843.7),
    ("Lindt & Sprüngli",           2684145.0, 1241545.0),
    ("Schooren",                   2684272.2, 1241360.5),
    ("Schulhaus Dorfstrasse",      2683836.9, 1241822.6),
    ("Schwelle (Kilchberg Dorf)",  2683654.9, 1241790.5),
    ("Gemeindehaus",               2683651.3, 1242162.0),
    ("Sanatorium",                 2683594.3, 1242379.5),
    ("Paradiessteig",              2683488.3, 1242671.6),
    ("Hornhaldenstrasse",          2683400.2, 1242915.3),
]

# Curated pitched-roof Kilchberg residential buildings (bldg_idx, smoke phase)
VILLAGE_CHIMNEY_SPECS: list[tuple[int, float]] = [
    (1506, 0.05),  # Dorfstrasse 118 (Lebern / Dorf)
    (1546, 0.17),  # C.-F.-Meyer-Strasse 18 (Böndler)
    (1640, 0.29),  # Schoorenstrasse 38 (Schooren)
    (939,  0.41),  # Brunnenmoosstrasse 4 (Schwelle / St. Elisabeth)
    (1809, 0.53),  # Stockenstrasse 117 (Stocken Ridge)
    (1560, 0.62),  # Dorfstrasse 5 (Bendlikon)
    (1241, 0.71),  # Alte Landstrasse 134 (Schwelle / C.F. Meyer)
    (537,  0.80),  # Mönchhofstrasse 14 (Schwelle / Mönchhof)
    (203,  0.89),  # Stockenstrasse 55 (Im Breitloo / Weinberg)
    (103,  0.96),  # Rennweg 100 (Mönchhof / Horn)
]

# Verified village Dorfbrunnen (name, E, N) — clear of all buildings, bridges, and road lanes
FOUNTAIN_SPECS: list[tuple[str, float, float]] = [
    ("Dorfplatz (Reformierte Kirche)",     2683429.0, 1241314.0),
    ("C.F. Meyer-Haus (Alte Landstrasse)", 2683720.0, 1241434.0),
    ("Bahnhofplatz Kilchberg",             2683888.0, 1242049.0),
]


@dataclass
class _AnimScene:
    """Lightweight subset of SceneData (~280 MB RSS) bit-for-bit identical for geometry & occlusion."""

    dem: np.ndarray
    diorama_mask: np.ndarray
    lake_mask: np.ndarray
    bridge_cls: np.ndarray
    bridge_z: np.ndarray
    verts: np.ndarray
    surf_type: np.ndarray
    bldg_idx: np.ndarray
    meta: dict


def _load_anim_scene(cache_dir: Path = RAW_CACHE_DIR) -> _AnimScene:
    with np.load(cache_dir / "scene_kilchberg_05m.npz") as s:
        dem = np.asarray(s["dem"], dtype=np.float32)
        diorama_mask = np.asarray(s["diorama_mask"], dtype=np.bool_)
        lake_mask = np.asarray(s["lake_mask"], dtype=np.bool_)
        bridge_cls = np.asarray(s["bridge_cls"], dtype=np.uint8)
        bridge_z = np.asarray(s["bridge_z"], dtype=np.float32)
    with np.load(cache_dir / "buildings_kilchberg_3d.npz") as b:
        verts = np.asarray(b["verts"], dtype=np.float32)
        surf_type = np.asarray(b["surf_type"], dtype=np.uint8)
        bldg_idx = np.asarray(b["bldg_idx"], dtype=np.int32)
    meta = json.loads((cache_dir / "buildings_kilchberg_meta.json").read_text())
    return _AnimScene(
        dem=dem,
        diorama_mask=diorama_mask,
        lake_mask=lake_mask,
        bridge_cls=bridge_cls,
        bridge_z=bridge_z,
        verts=verts,
        surf_type=surf_type,
        bldg_idx=bldg_idx,
        meta=meta,
    )


def _snap_key(pt: tuple[float, float], tol: float) -> tuple[int, int]:
    return (int(round(pt[0] / tol)), int(round(pt[1] / tol)))


def _flatten_lines(geoms: list) -> list[LineString]:
    out: list[LineString] = []
    for g in geoms:
        if g is None or g.is_empty:
            continue
        if g.geom_type == "LineString":
            out.append(g)
        elif hasattr(g, "geoms"):
            for sub in g.geoms:
                if sub.geom_type == "LineString" and not sub.is_empty:
                    out.append(sub)
    return out


def _stitch_exact_path(
    geoms: list,
    start_target: tuple[float, float],
    end_target: tuple[float, float],
    subdiv_m: float = 4.0,
    snap_m: float = 1.2,
    bridge_m: float = 3.5,
) -> LineString | None:
    """Build a tightly-snapped, subdivided LV95 segment graph and extract the exact shortest path."""
    adj: dict[tuple[int, int], list[tuple[tuple[int, int], float, list[tuple[float, float]]]]] = {}
    node_xy: dict[tuple[int, int], tuple[float, float]] = {}

    for ls in _flatten_lines(geoms):
        coords = list(ls.coords)
        if len(coords) < 2:
            continue
        for k in range(len(coords) - 1):
            x0, y0 = float(coords[k][0]), float(coords[k][1])
            x1, y1 = float(coords[k + 1][0]), float(coords[k + 1][1])
            seg_len = math.hypot(x1 - x0, y1 - y0)
            if seg_len < 0.1:
                continue
            n_sub = max(1, int(math.ceil(seg_len / subdiv_m)))
            for s in range(n_sub):
                t0 = s / n_sub
                t1 = (s + 1) / n_sub
                p0 = (x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0)
                p1 = (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)
                d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
                if d < 0.05:
                    continue
                u = _snap_key(p0, snap_m)
                v = _snap_key(p1, snap_m)
                if u == v:
                    continue
                node_xy.setdefault(u, p0)
                node_xy.setdefault(v, p1)
                adj.setdefault(u, []).append((v, d, [p0, p1]))
                adj.setdefault(v, []).append((u, d, [p1, p0]))

    if not node_xy:
        return None

    keys = list(node_xy.keys())
    if bridge_m > 0.1 and len(keys) > 1:
        xy_arr = np.asarray([node_xy[k] for k in keys], dtype=np.float64)
        tree = cKDTree(xy_arr)
        for i, j in sorted(tree.query_pairs(r=bridge_m)):
            u, v = keys[i], keys[j]
            ux, uy = node_xy[u]
            vx, vy = node_xy[v]
            d = math.hypot(ux - vx, uy - vy)
            if 0.05 < d <= bridge_m:
                w = d * 2.5
                adj.setdefault(u, []).append((v, w, [(ux, uy), (vx, vy)]))
                adj.setdefault(v, []).append((u, w, [(vx, vy), (ux, uy)]))

    src = min(keys, key=lambda k: math.hypot(node_xy[k][0] - start_target[0], node_xy[k][1] - start_target[1]))
    dst = min(keys, key=lambda k: math.hypot(node_xy[k][0] - end_target[0], node_xy[k][1] - end_target[1]))
    if src == dst:
        return None

    dist: dict[tuple[int, int], float] = {src: 0.0}
    prev: dict[tuple[int, int], tuple[tuple[int, int], list[tuple[float, float]]]] = {}
    pq: list[tuple[float, tuple[int, int]]] = [(0.0, src)]
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
            if not merged_pts or math.hypot(pt[0] - merged_pts[-1][0], pt[1] - merged_pts[-1][1]) > 0.25:
                merged_pts.append((float(pt[0]), float(pt[1])))
    return LineString(merged_pts) if len(merged_pts) >= 2 else None


def _fillet_polyline(
    coords: list[tuple[float, float]],
    corner_deg: float = 20.0,
    max_trim_m: float = 6.5,
    n_arc: int = 10,
) -> LineString:
    """Replace sharp interior polyline corners with G1 tangent-continuous quadratic Bezier arcs."""
    pts: list[np.ndarray] = []
    for c in coords:
        p = np.array([float(c[0]), float(c[1])], dtype=np.float64)
        if not pts or float(np.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1])) >= 0.5:
            pts.append(p)
    if len(pts) < 3:
        return LineString([(float(p[0]), float(p[1])) for p in pts])

    out: list[tuple[float, float]] = [(float(pts[0][0]), float(pts[0][1]))]
    ts = np.linspace(0.0, 1.0, n_arc + 1)
    for i in range(1, len(pts) - 1):
        p_prev, p_cur, p_next = pts[i - 1], pts[i], pts[i + 1]
        v1 = p_cur - p_prev
        v2 = p_next - p_cur
        l1 = float(np.hypot(v1[0], v1[1]))
        l2 = float(np.hypot(v2[0], v2[1]))
        if l1 < 1e-3 or l2 < 1e-3:
            continue
        u1 = v1 / l1
        u2 = v2 / l2
        dot = max(-1.0, min(1.0, float(u1[0] * u2[0] + u1[1] * u2[1])))
        theta_deg = math.degrees(math.acos(dot))
        if theta_deg > corner_deg:
            t1 = min(max_trim_m, 0.44 * l1)
            t2 = min(max_trim_m, 0.44 * l2)
            q0 = p_cur - t1 * u1
            q1 = p_cur
            q2 = p_cur + t2 * u2
            for t in ts:
                omt = 1.0 - float(t)
                b = (omt * omt) * q0 + (2.0 * omt * float(t)) * q1 + (float(t) * float(t)) * q2
                pt = (float(b[0]), float(b[1]))
                if math.hypot(pt[0] - out[-1][0], pt[1] - out[-1][1]) > 0.1:
                    out.append(pt)
        else:
            pt = (float(p_cur[0]), float(p_cur[1]))
            if math.hypot(pt[0] - out[-1][0], pt[1] - out[-1][1]) > 0.1:
                out.append(pt)

    last = (float(pts[-1][0]), float(pts[-1][1]))
    if math.hypot(last[0] - out[-1][0], last[1] - out[-1][1]) > 0.1:
        out.append(last)
    return LineString(out)


def _join_with_fillet(
    ls_a: LineString,
    ls_b: LineString,
    junc_pt: tuple[float, float],
    trim_m: float = 8.0,
    n_arc: int = 12,
) -> LineString:
    """Join two road LineStrings at junc_pt using a G1 quadratic Bezier junction fillet."""
    jp = Point(float(junc_pt[0]), float(junc_pt[1]))
    sa = float(ls_a.project(jp))
    sb = float(ls_b.project(jp))
    sa_end = max(0.0, sa - trim_m)
    sb_start = min(float(ls_b.length), sb + trim_m)

    pts: list[tuple[float, float]] = []

    def _append_range(ls: LineString, s0: float, s1: float, step: float = 2.0) -> None:
        if s1 <= s0 + 0.05:
            p = ls.interpolate(s0).coords[0]
            pt = (float(p[0]), float(p[1]))
            if not pts or math.hypot(pt[0] - pts[-1][0], pt[1] - pts[-1][1]) > 0.1:
                pts.append(pt)
            return
        n_s = max(2, int(math.ceil((s1 - s0) / step)) + 1)
        for s in np.linspace(s0, s1, n_s):
            p = ls.interpolate(float(s)).coords[0]
            pt = (float(p[0]), float(p[1]))
            if not pts or math.hypot(pt[0] - pts[-1][0], pt[1] - pts[-1][1]) > 0.1:
                pts.append(pt)

    _append_range(ls_a, 0.0, sa_end, step=2.0)

    q0_c = ls_a.interpolate(sa_end).coords[0]
    q2_c = ls_b.interpolate(sb_start).coords[0]
    q0 = np.array([float(q0_c[0]), float(q0_c[1])], dtype=np.float64)
    q1 = np.array([float(junc_pt[0]), float(junc_pt[1])], dtype=np.float64)
    q2 = np.array([float(q2_c[0]), float(q2_c[1])], dtype=np.float64)
    for t in np.linspace(0.0, 1.0, n_arc + 1)[1:-1]:
        omt = 1.0 - float(t)
        b = (omt * omt) * q0 + (2.0 * omt * float(t)) * q1 + (float(t) * float(t)) * q2
        pt = (float(b[0]), float(b[1]))
        if not pts or math.hypot(pt[0] - pts[-1][0], pt[1] - pts[-1][1]) > 0.1:
            pts.append(pt)

    _append_range(ls_b, sb_start, float(ls_b.length), step=2.0)
    return LineString(pts)


def _offset_then_clip(
    ls: LineString,
    diorama_mask: np.ndarray,
    step_m: float = 3.0,
    offset_right_m: float = 0.0,
    sig_m: float = 3.6,
    inset_m: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Smooth & laterally offset an unclipped LV95 spine, then clip cleanly edge-to-edge to diorama_mask."""
    L_raw = float(ls.length)
    if L_raw < 10.0:
        return None
    n_d = max(4, int(math.ceil(L_raw)) + 1)
    ss_d = np.linspace(0.0, L_raw, n_d)
    pts_d = np.asarray([ls.interpolate(float(s)).coords[0] for s in ss_d], dtype=np.float64)

    e_sm = ndimage.gaussian_filter1d(pts_d[:, 0], sigma=sig_m, mode="nearest") if n_d >= 7 else pts_d[:, 0].copy()
    n_sm = ndimage.gaussian_filter1d(pts_d[:, 1], sigma=sig_m, mode="nearest") if n_d >= 7 else pts_d[:, 1].copy()

    if abs(offset_right_m) > 1e-3:
        de = np.gradient(e_sm)
        dn = np.gradient(n_sm)
        nm = np.maximum(1e-6, np.hypot(de, dn))
        # Right-hand Swiss lane normal in (E, N): (+dn, -de) / nm
        e_sm = e_sm + (dn / nm) * offset_right_m
        n_sm = n_sm - (de / nm) * offset_right_m
        # Light post-offset smoothing eliminates inner-corner cusp pinching on tight bends
        e_sm = ndimage.gaussian_filter1d(e_sm, sigma=1.8, mode="nearest")
        n_sm = ndimage.gaussian_filter1d(n_sm, sigma=1.8, mode="nearest")

    ls_off = LineString(list(zip(e_sm.tolist(), n_sm.tolist())))
    L_off = float(ls_off.length)
    n_c = max(4, int(math.ceil(L_off / 0.25)) + 1)
    ss_c = np.linspace(0.0, L_off, n_c)
    pts_c = np.asarray([ls_off.interpolate(float(s)).coords[0] for s in ss_c], dtype=np.float64)

    cols = np.floor((pts_c[:, 0] - E_MIN) / GRID_RES).astype(np.int32)
    rows = np.floor((N_MAX - pts_c[:, 1]) / GRID_RES).astype(np.int32)
    in_bounds = (cols >= 0) & (cols < GRID_W) & (rows >= 0) & (rows < GRID_H)
    inside = np.zeros(n_c, dtype=bool)
    inside[in_bounds] = diorama_mask[rows[in_bounds], cols[in_bounds]]

    idx_t = np.nonzero(inside)[0]
    if len(idx_t) < 4:
        return None
    runs = np.split(idx_t, np.where(np.diff(idx_t) > 1)[0] + 1)
    best_run = max(runs, key=len)

    s0 = float(ss_c[best_run[0]]) + inset_m
    s1 = float(ss_c[best_run[-1]]) - inset_m
    if s1 <= s0 + step_m:
        return None

    L_fin = s1 - s0
    n_fin = max(4, int(round(L_fin / step_m)) + 1)
    ss_fin = np.linspace(s0, s1, n_fin)
    pts_fin = np.asarray([ls_off.interpolate(float(s)).coords[0] for s in ss_fin], dtype=np.float64)
    return pts_fin[:, 0], pts_fin[:, 1], float(L_fin)


def _resample_smooth_line(
    ls: LineString,
    step_m: float = 2.5,
    offset_right_m: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Uniformly resample a LineString in LV95 meters with optional right-hand offset."""
    total_len = float(ls.length)
    n_pts = max(4, int(round(total_len / step_m)) + 1)
    s_vals = np.linspace(0.0, total_len, n_pts)
    pts = np.asarray([ls.interpolate(float(s)).coords[0] for s in s_vals], dtype=np.float64)

    if len(pts) >= 7:
        e_sm = ndimage.gaussian_filter1d(pts[:, 0], sigma=1.3, mode="nearest")
        n_sm = ndimage.gaussian_filter1d(pts[:, 1], sigma=1.3, mode="nearest")
    else:
        e_sm, n_sm = pts[:, 0].copy(), pts[:, 1].copy()

    if abs(offset_right_m) > 1e-3:
        de = np.gradient(e_sm)
        dn = np.gradient(n_sm)
        norm = np.maximum(1e-6, np.hypot(de, dn))
        e_sm = e_sm + (dn / norm) * offset_right_m
        n_sm = n_sm - (de / norm) * offset_right_m

    return e_sm, n_sm, total_len


def _catmull_rom_closed_or_open(
    ctrl: list[tuple[float, float]],
    step_m: float = 3.0,
    closed: bool = False,
) -> tuple[np.ndarray, np.ndarray, float]:
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
        ls = LineString(dense)
        total_len = float(ls.length)
        n_unique = max(24, int(round(total_len / step_m)))
        s_vals = np.linspace(0.0, total_len, n_unique, endpoint=False)
        u_pts = np.asarray([ls.interpolate(float(s)).coords[0] for s in s_vals], dtype=np.float64)
        e_sm = ndimage.gaussian_filter1d(u_pts[:, 0], sigma=1.3, mode="wrap")
        n_sm = ndimage.gaussian_filter1d(u_pts[:, 1], sigma=1.3, mode="wrap")

        # Rotate closed loop so index 0 sits at the flattest mid-side stretch (zero seam kink & smooth tanWin=3 wrap)
        de_prev = e_sm - np.roll(e_sm, 1)
        dn_prev = n_sm - np.roll(n_sm, 1)
        de_next = np.roll(e_sm, -1) - e_sm
        dn_next = np.roll(n_sm, -1) - n_sm
        l1 = np.maximum(1e-9, np.hypot(de_prev, dn_prev))
        l2 = np.maximum(1e-9, np.hypot(de_next, dn_next))
        dots = np.clip((de_prev * de_next + dn_prev * dn_next) / (l1 * l2), -1.0, 1.0)
        turn_deg = np.degrees(np.arccos(dots))
        turn_win = ndimage.uniform_filter1d(turn_deg, size=7, mode="wrap")
        best_k = int(np.argmin(turn_win))
        e_sm = np.roll(e_sm, -best_k)
        n_sm = np.roll(n_sm, -best_k)

        # Explicitly close the loop so pts[-1] == pts[0] identically (0.000 m seam gap)
        e_sm = np.append(e_sm, e_sm[0])
        n_sm = np.append(n_sm, n_sm[0])
        closed_len = float(np.sum(np.hypot(np.diff(e_sm), np.diff(n_sm))))
        return e_sm, n_sm, closed_len

    dense.append((float(pts[-1, 0]), float(pts[-1, 1])))
    ls = LineString(dense)
    return _resample_smooth_line(ls, step_m=step_m, offset_right_m=0.0)


def _bilinear_weights(e: np.ndarray, n: np.ndarray):
    cf = np.clip((e - E_MIN) / GRID_RES - 0.5, 0.0, GRID_W - 1.001)
    rf = np.clip((N_MAX - n) / GRID_RES - 0.5, 0.0, GRID_H - 1.001)
    c0 = np.floor(cf).astype(np.int32)
    r0 = np.floor(rf).astype(np.int32)
    dc = cf - c0
    dr = rf - r0
    w00 = (1.0 - dr) * (1.0 - dc)
    w01 = (1.0 - dr) * dc
    w10 = dr * (1.0 - dc)
    w11 = dr * dc
    return r0, c0, w00, w01, w10, w11


def _sample_bilinear_dem(dem: np.ndarray, e: np.ndarray, n: np.ndarray) -> np.ndarray:
    r0, c0, w00, w01, w10, w11 = _bilinear_weights(e, n)
    return (
        w00 * dem[r0, c0]
        + w01 * dem[r0, c0 + 1]
        + w10 * dem[r0 + 1, c0]
        + w11 * dem[r0 + 1, c0 + 1]
    ).astype(np.float64)


def _sample_road_z(
    scene: _AnimScene,
    e: np.ndarray,
    n: np.ndarray,
    underpass_poly=None,
    allowed_bridge_cls: tuple[int, ...] = (),
) -> tuple[np.ndarray, np.ndarray]:
    """Bilinear DEM + class-filtered normalized bilinear bridge_z, plus underpass depth drop."""
    r0, c0, w00, w01, w10, w11 = _bilinear_weights(e, n)
    z_dem = (
        w00 * scene.dem[r0, c0]
        + w01 * scene.dem[r0, c0 + 1]
        + w10 * scene.dem[r0 + 1, c0]
        + w11 * scene.dem[r0 + 1, c0 + 1]
    ).astype(np.float64)

    on_bridge = np.zeros(len(e), dtype=bool)
    z = z_dem.copy()
    if allowed_bridge_cls:
        cls_arr = np.asarray(allowed_bridge_cls, dtype=np.uint8)
        b00 = np.isin(scene.bridge_cls[r0, c0], cls_arr)
        b01 = np.isin(scene.bridge_cls[r0, c0 + 1], cls_arr)
        b10 = np.isin(scene.bridge_cls[r0 + 1, c0], cls_arr)
        b11 = np.isin(scene.bridge_cls[r0 + 1, c0 + 1], cls_arr)
        bw00 = np.where(b00, w00, 0.0)
        bw01 = np.where(b01, w01, 0.0)
        bw10 = np.where(b10, w10, 0.0)
        bw11 = np.where(b11, w11, 0.0)
        bw_sum = bw00 + bw01 + bw10 + bw11
        on_bridge = bw_sum > 0.25
        bz_num = (
            bw00 * scene.bridge_z[r0, c0]
            + bw01 * scene.bridge_z[r0, c0 + 1]
            + bw10 * scene.bridge_z[r0 + 1, c0]
            + bw11 * scene.bridge_z[r0 + 1, c0 + 1]
        )
        bz_interp = bz_num / np.maximum(1e-6, bw_sum)
        z = np.where(on_bridge, np.maximum(z_dem, bz_interp), z_dem)

    if len(z) >= 5:
        z = ndimage.gaussian_filter1d(z, sigma=1.2, mode="nearest")

    z_vis = z.copy()
    z_depth = z.copy()
    if underpass_poly is not None:
        p_under = prep(underpass_poly)
        for i in range(len(e)):
            if not on_bridge[i] and p_under.contains(Point(float(e[i]), float(n[i]))):
                z_depth[i] -= 6.0
    return z_vis, z_depth


def _sample_rail_z(scene: _AnimScene, e: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Bilinear DEM + strictly flat bridge_z ONLY where bridge_cls == BR_RAIL_BRIDGE (4)."""
    r0, c0, w00, w01, w10, w11 = _bilinear_weights(e, n)
    z_dem = (
        w00 * scene.dem[r0, c0]
        + w01 * scene.dem[r0, c0 + 1]
        + w10 * scene.dem[r0 + 1, c0]
        + w11 * scene.dem[r0 + 1, c0 + 1]
    ).astype(np.float64)

    b00 = scene.bridge_cls[r0, c0] == BR_RAIL_BRIDGE
    b01 = scene.bridge_cls[r0, c0 + 1] == BR_RAIL_BRIDGE
    b10 = scene.bridge_cls[r0 + 1, c0] == BR_RAIL_BRIDGE
    b11 = scene.bridge_cls[r0 + 1, c0 + 1] == BR_RAIL_BRIDGE
    bw00 = np.where(b00, w00, 0.0)
    bw01 = np.where(b01, w01, 0.0)
    bw10 = np.where(b10, w10, 0.0)
    bw11 = np.where(b11, w11, 0.0)
    bw_sum = bw00 + bw01 + bw10 + bw11
    on_rbr = bw_sum > 0.25
    bz_num = (
        bw00 * scene.bridge_z[r0, c0]
        + bw01 * scene.bridge_z[r0, c0 + 1]
        + bw10 * scene.bridge_z[r0 + 1, c0]
        + bw11 * scene.bridge_z[r0 + 1, c0 + 1]
    )
    bz_interp = bz_num / np.maximum(1e-6, bw_sum)
    z_raw = np.where(on_rbr, np.maximum(z_dem, bz_interp), z_dem)
    z_sm = ndimage.gaussian_filter1d(z_raw, sigma=1.0, mode="nearest") if len(z_raw) >= 5 else z_raw
    # Preserve strictly flat rail bridge elevation on BR_RAIL_BRIDGE spans!
    return np.where(on_rbr, z_raw, z_sm) + 0.55


def _build_obstacle_surface(scene: _AnimScene, include_bridges: bool = True) -> np.ndarray:
    """Build 0.5 m foreground obstacle elevation grid (3D LOD2 building roofs + optional bridges)."""
    obs_z = scene.dem.astype(np.float32).copy()
    if include_bridges:
        has_br = scene.bridge_cls > 0
        obs_z[has_br] = np.maximum(obs_z[has_br], scene.bridge_z[has_br] + 1.0)
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


def _compute_occlusion(
    obs_z: np.ndarray,
    cam: IsometricCamera,
    e: np.ndarray,
    n: np.ndarray,
    z: np.ndarray,
    vehicle_h: float = 2.2,
) -> np.ndarray:
    """Analytical 3D ray-march along orthographic camera ray to detect foreground building/bridge occlusion."""
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
    z_depth: np.ndarray | None = None,
) -> list[list[float | int]]:
    px, py, _ = cam.project(e, n, z)
    zd_use = z if z_depth is None else z_depth
    _, _, pd_veh = cam.project(e, n, zd_use + vehicle_h * 0.72)
    d_u16 = np.clip(
        np.round((pd_veh - DEPTH_MIN) / (DEPTH_MAX - DEPTH_MIN) * 65535.0),
        0,
        65535,
    ).astype(np.int32)
    u = (px + shift_x) / W_full
    v = (py + shift_y) / H_full
    if obs_z is not None:
        occ = _compute_occlusion(obs_z, cam, e, n, zd_use, vehicle_h=vehicle_h)
    else:
        occ = np.zeros(len(e), dtype=np.uint8)
    return [
        [round(float(u[i]), 5), round(float(v[i]), 5), int(occ[i]), int(d_u16[i])]
        for i in range(len(e))
    ]


def _extract_double_track_rail(
    rail_lines: list[LineString],
    step_m: float = 3.0,
) -> tuple[tuple[np.ndarray, np.ndarray, float], tuple[np.ndarray, np.ndarray, float]] | None:
    """Extract true West (Gleis 2, SB) and East (Gleis 1, NB) SBB tracks via ±8 m perpendicular cross-sections."""
    spine0 = _stitch_exact_path(
        rail_lines,
        (2683345.0, 1243350.0),
        (2684250.0, 1240950.0),
        subdiv_m=4.0,
        snap_m=6.0,
        bridge_m=12.0,
    )
    if spine0 is None or spine0.length < 200.0:
        return None

    e0, n0, _ = _resample_smooth_line(spine0, step_m=step_m, offset_right_m=0.0)
    de = np.gradient(e0)
    dn = np.gradient(n0)
    nm = np.maximum(1e-6, np.hypot(de, dn))
    # Right-hand unit normal for southbound (NE -> SW) points West / landward (Gleis 2)
    rx0 = dn / nm
    ry0 = -de / nm

    rail_u = unary_union(rail_lines)
    n_pts = len(e0)
    ew = np.empty(n_pts, dtype=np.float64)
    nw = np.empty(n_pts, dtype=np.float64)
    ee = np.empty(n_pts, dtype=np.float64)
    ne = np.empty(n_pts, dtype=np.float64)

    def _collect_xy(geom) -> list[tuple[float, float]]:
        if geom.is_empty:
            return []
        gt = geom.geom_type
        if gt == "Point":
            return [(float(geom.x), float(geom.y))]
        if gt == "LineString":
            mid = geom.interpolate(0.5, normalized=True)
            return [(float(mid.x), float(mid.y))]
        if hasattr(geom, "geoms"):
            res: list[tuple[float, float]] = []
            for sub in geom.geoms:
                res.extend(_collect_xy(sub))
            return res
        return []

    for i in range(n_pts):
        seg = LineString([
            (float(e0[i] - 8.0 * rx0[i]), float(n0[i] - 8.0 * ry0[i])),
            (float(e0[i] + 8.0 * rx0[i]), float(n0[i] + 8.0 * ry0[i])),
        ])
        hits = _collect_xy(rail_u.intersection(seg))
        best_pair: tuple[float, tuple[float, float], tuple[float, float]] | None = None
        if len(hits) >= 2:
            scored = [
                ((hx - e0[i]) * rx0[i] + (hy - n0[i]) * ry0[i], (hx, hy))
                for hx, hy in hits
            ]
            scored.sort(key=lambda x: x[0])
            for a in range(len(scored)):
                for b in range(a + 1, len(scored)):
                    sep = scored[b][0] - scored[a][0]
                    if 2.8 <= sep <= 6.0:
                        mid_err = abs(0.5 * (scored[a][0] + scored[b][0]))
                        if best_pair is None or mid_err < best_pair[0]:
                            best_pair = (mid_err, scored[a][1], scored[b][1])
        if best_pair is not None:
            east_pt, west_pt = best_pair[1], best_pair[2]
            ee[i], ne[i] = east_pt
            ew[i], nw[i] = west_pt
        else:
            ew[i] = e0[i] + 2.05 * rx0[i]
            nw[i] = n0[i] + 2.05 * ry0[i]
            ee[i] = e0[i] - 2.05 * rx0[i]
            ne[i] = n0[i] - 2.05 * ry0[i]

    # Small sigma=0.7 keeps tracks cleanly on narrow Paradiesstrasse rail bridges with 0 platform hits;
    # uniform linear arc-length resampling guarantees exact alignment between stop_frac and app.js index interpolation.
    ew = ndimage.gaussian_filter1d(ew, sigma=0.7, mode="nearest")
    nw = ndimage.gaussian_filter1d(nw, sigma=0.7, mode="nearest")
    ee = ndimage.gaussian_filter1d(ee, sigma=0.7, mode="nearest")[::-1].copy()
    ne = ndimage.gaussian_filter1d(ne, sigma=0.7, mode="nearest")[::-1].copy()

    def _uniform_resample(e_arr: np.ndarray, n_arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
        ls = LineString(list(zip(e_arr.tolist(), n_arr.tolist())))
        total_len = float(ls.length)
        n_u = max(4, int(round(total_len / step_m)) + 1)
        ss = np.linspace(0.0, total_len, n_u)
        u_pts = np.asarray([ls.interpolate(float(s)).coords[0] for s in ss], dtype=np.float64)
        return u_pts[:, 0], u_pts[:, 1], total_len

    return _uniform_resample(ew, nw), _uniform_resample(ee, ne)


def project_bus_stops(
    route_e: np.ndarray,
    route_n: np.ndarray,
    max_perp_m: float = 12.0,
    min_edge_frac: float = 0.06,
    min_gap_frac: float = 0.075,
) -> tuple[list[float], list[str]]:
    """Project official Kilchberg ZVV/DIDOK bus stops onto an LV95 road polyline."""
    ls = LineString(list(zip(route_e.tolist(), route_n.tolist())))
    L = float(ls.length)
    if L < 100.0:
        return [], []
    hits: list[tuple[float, str]] = []
    for name, se, sn in BUS_STOP_CATALOG:
        pt = Point(se, sn)
        if ls.distance(pt) <= max_perp_m:
            frac = float(ls.project(pt) / L)
            if min_edge_frac <= frac <= (1.0 - min_edge_frac):
                hits.append((frac, name))
    hits.sort(key=lambda x: x[0])
    kept: list[tuple[float, str]] = []
    for frac, name in hits:
        if not kept or (frac - kept[-1][0]) >= min_gap_frac:
            kept.append((frac, name))
    return [round(f, 4) for f, _ in kept], [nm for _, nm in kept]


def _extract_shoreline_uv(
    scene: _AnimScene,
    cam: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W_full: int,
    H_full: int,
    n_pts: int = 120,
) -> list[list[float]]:
    """Deterministically extract ordered SW -> NE Lake Zurich coastal shoreline from lake_mask & diorama_mask."""
    water = scene.lake_mask.astype(bool) & scene.diorama_mask.astype(bool)
    lbl, _ = ndimage.label(water)
    vals, cnts = np.unique(lbl[lbl > 0], return_counts=True)
    main_lake = lbl == vals[int(np.argmax(cnts))]

    transform = from_bounds(E_MIN, N_MIN, E_MAX, N_MAX, GRID_W, GRID_H)
    polys = [
        shape(geom)
        for geom, val in rio_shapes(main_lake.astype(np.uint8), mask=main_lake.astype(np.uint8), transform=transform)
        if val == 1
    ]
    ring = np.asarray(max(polys, key=lambda p: p.area).exterior.coords[:-1], dtype=np.float64)

    # Coastal vertices border dry land inside diorama_mask; straight aquarium glass cut-edges do not
    land_dil = ndimage.binary_dilation(
        scene.diorama_mask.astype(bool) & (~scene.lake_mask.astype(bool)),
        iterations=4,
    )
    rc_c = np.clip(((ring[:, 0] - E_MIN) / GRID_RES).astype(np.int32), 0, GRID_W - 1)
    rc_r = np.clip(((N_MAX - ring[:, 1]) / GRID_RES).astype(np.int32), 0, GRID_H - 1)
    is_coast = land_dil[rc_r, rc_c]

    rot = int(np.nonzero(~is_coast)[0][0])
    is_coast_rot = np.roll(is_coast, -rot)
    ring_rot = np.roll(ring, -rot, axis=0)
    idx_t = np.nonzero(is_coast_rot)[0]
    runs = np.split(idx_t, np.where(np.diff(idx_t) > 1)[0] + 1)
    coast_xy = ring_rot[max(runs, key=len)]

    # Enforce SW -> NE orientation (N increasing => u increasing, v decreasing => outward SE normal)
    if coast_xy[0, 1] > coast_xy[-1, 1]:
        coast_xy = coast_xy[::-1]

    coast_simp = LineString(coast_xy).simplify(7.0, preserve_topology=False)
    s_vals = np.linspace(0.0, float(coast_simp.length), n_pts)
    pts = np.asarray([coast_simp.interpolate(float(s)).coords[0] for s in s_vals], dtype=np.float64)
    e_sh = ndimage.gaussian_filter1d(pts[:, 0], sigma=1.5, mode="nearest")
    n_sh = ndimage.gaussian_filter1d(pts[:, 1], sigma=1.5, mode="nearest")
    px, py, _ = cam.project(e_sh, n_sh, np.full(n_pts, LAKE_SURFACE_Z, dtype=np.float64))
    u_sh = (px + shift_x) / W_full
    v_sh = (py + shift_y) / H_full
    return [[round(float(u_sh[i]), 5), round(float(v_sh[i]), 5)] for i in range(n_pts)]


def _bldg_ridge_apex(scene: _AnimScene, bidx: int) -> tuple[float, float, float]:
    """Compute roof ridge apex (E, N, z_roof) from 3D LOD2 roof triangles for building bidx."""
    b_list = scene.meta.get("buildings", [])
    b_meta = b_list[bidx] if 0 <= bidx < len(b_list) else None
    mask = (scene.bldg_idx == bidx) & (scene.surf_type == 1)
    if np.any(mask):
        rv = scene.verts[mask].reshape(-1, 3)
        z_max = float(rv[:, 2].max())
        top = rv[rv[:, 2] >= (z_max - 0.35)]
        if len(top) > 0:
            return float(top[:, 0].mean()), float(top[:, 1].mean()), z_max
    if b_meta is not None:
        return float(b_meta["e"]), float(b_meta["n"]), float(b_meta["z_roof"])
    raise ValueError(f"Building index {bidx} not found in buildings metadata or mesh")


def _bldg_roof_anchor(scene: _AnimScene, bidx: int) -> tuple[float, float, float]:
    """Select a guaranteed on-roof 3D triangle centroid on the highest primary roof facet of building bidx.

    Avoids concave/L-shaped bounding-box centroids that can fall outside the actual roof polygon.
    """
    mask = (scene.bldg_idx == bidx) & (scene.surf_type == 1)
    if np.any(mask):
        tris = scene.verts[mask]
        v0 = tris[:, 0, :2]
        v1 = tris[:, 1, :2]
        v2 = tris[:, 2, :2]
        areas = 0.5 * np.abs((v1[:, 0] - v0[:, 0]) * (v2[:, 1] - v0[:, 1]) - (v1[:, 1] - v0[:, 1]) * (v2[:, 0] - v0[:, 0]))
        centroids = tris.mean(axis=1)
        valid = np.nonzero(areas >= 5.0)[0]
        cand = valid if len(valid) > 0 else np.arange(len(tris))
        best = int(max(cand, key=lambda idx: (float(centroids[idx, 2]), float(areas[idx]))))
        return float(centroids[best, 0]), float(centroids[best, 1]), float(centroids[best, 2])
    return _bldg_ridge_apex(scene, bidx)


_PROHIBITED_AERIAL_RE = re.compile(r"paraglider|hot-air|balloon|glider", re.IGNORECASE)


def _is_valid_land(scene: _AnimScene, e_pt: float, n_pt: float) -> bool:
    """Return True iff LV95 (e_pt, n_pt) lies strictly inside diorama_mask and outside lake_mask."""
    col = int(math.floor((e_pt - E_MIN) / GRID_RES))
    row = int(math.floor((N_MAX - n_pt) / GRID_RES))
    if col < 0 or col >= GRID_W or row < 0 or row >= GRID_H:
        return False
    return bool(scene.diorama_mask[row, col]) and not bool(scene.lake_mask[row, col])


def _is_valid_land_arr(scene: _AnimScene, e_arr: np.ndarray, n_arr: np.ndarray) -> np.ndarray:
    """Vectorized dry-land diorama mask check: inside diorama_mask and outside lake_mask."""
    cols = np.floor((e_arr - E_MIN) / GRID_RES).astype(np.int32)
    rows = np.floor((N_MAX - n_arr) / GRID_RES).astype(np.int32)
    in_bounds = (cols >= 0) & (cols < GRID_W) & (rows >= 0) & (rows < GRID_H)
    valid = np.zeros(len(e_arr), dtype=bool)
    valid[in_bounds] = scene.diorama_mask[rows[in_bounds], cols[in_bounds]] & (
        ~scene.lake_mask[rows[in_bounds], cols[in_bounds]]
    )
    return valid


def _proj_uv_d16(
    cam: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W_full: int,
    H_full: int,
    e_pt: float,
    n_pt: float,
    z_pt: float,
    vehicle_h: float = 1.7,
) -> tuple[float, float, int]:
    """Project a single LV95 3D point to normalized (u, v) and 16-bit depth d16."""
    ea = np.array([e_pt], dtype=np.float64)
    na = np.array([n_pt], dtype=np.float64)
    za = np.array([z_pt], dtype=np.float64)
    px, py, _ = cam.project(ea, na, za)
    _, _, pd = cam.project(ea, na, za + vehicle_h * 0.72)
    d16 = int(np.clip(np.round((float(pd[0]) - DEPTH_MIN) / (DEPTH_MAX - DEPTH_MIN) * 65535.0), 1, 65534))
    u = round(float((px[0] + shift_x) / W_full), 5)
    v = round(float((py[0] + shift_y) / H_full), 5)
    return u, v, d16


def _clip_land_polyline(
    ls: LineString,
    scene: _AnimScene,
    step_m: float = 5.5,
    sig_m: float = 1.2,
    inset_m: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Smooth an LV95 polyline, clip strictly to (diorama_mask & ~lake_mask), and resample uniformly."""
    L_raw = float(ls.length)
    if L_raw < 4.0:
        return None
    n_d = max(4, int(math.ceil(L_raw)) + 1)
    ss_d = np.linspace(0.0, L_raw, n_d)
    pts_d = np.asarray([ls.interpolate(float(s)).coords[0] for s in ss_d], dtype=np.float64)

    if sig_m > 0.0 and n_d >= 7:
        e_sm = ndimage.gaussian_filter1d(pts_d[:, 0], sigma=sig_m, mode="nearest")
        n_sm = ndimage.gaussian_filter1d(pts_d[:, 1], sigma=sig_m, mode="nearest")
    else:
        e_sm, n_sm = pts_d[:, 0].copy(), pts_d[:, 1].copy()

    ls_sm = LineString(list(zip(e_sm.tolist(), n_sm.tolist())))
    L_sm = float(ls_sm.length)
    if L_sm < 4.0:
        return None
    n_c = max(4, int(math.ceil(L_sm / 0.5)) + 1)
    ss_c = np.linspace(0.0, L_sm, n_c)
    pts_c = np.asarray([ls_sm.interpolate(float(s)).coords[0] for s in ss_c], dtype=np.float64)

    inside = _is_valid_land_arr(scene, pts_c[:, 0], pts_c[:, 1])
    idx_t = np.nonzero(inside)[0]
    if len(idx_t) < 2:
        return None
    runs = np.split(idx_t, np.where(np.diff(idx_t) > 1)[0] + 1)
    best_run = max(runs, key=len)

    s0 = float(ss_c[best_run[0]]) + inset_m
    s1 = float(ss_c[best_run[-1]]) - inset_m
    if s1 <= s0 + max(2.0, step_m * 0.5):
        s0 = float(ss_c[best_run[0]])
        s1 = float(ss_c[best_run[-1]])
        if s1 <= s0 + 2.0:
            return None

    L_fin = s1 - s0
    n_fin = max(3, int(round(L_fin / step_m)) + 1)
    ss_fin = np.linspace(s0, s1, n_fin)
    pts_fin = np.asarray([ls_sm.interpolate(float(s)).coords[0] for s in ss_fin], dtype=np.float64)
    # Final per-point dry-land filter in case coarse resampling straddles a concave shore pixel
    keep = _is_valid_land_arr(scene, pts_fin[:, 0], pts_fin[:, 1])
    if not np.all(keep):
        idx_k = np.nonzero(keep)[0]
        if len(idx_k) < 3:
            return None
        kruns = np.split(idx_k, np.where(np.diff(idx_k) > 1)[0] + 1)
        best_k = max(kruns, key=len)
        if len(best_k) < 3:
            return None
        pts_fin = pts_fin[best_k]
        L_fin = float(LineString(pts_fin.tolist()).length)
    return pts_fin[:, 0], pts_fin[:, 1], float(L_fin)


def _largest_connected_lines(
    lines: list[LineString],
    snap_m: float = 1.5,
    bridge_m: float = 10.0,
) -> list[LineString]:
    """Return only the LineStrings belonging to the largest connected component (within bridge_m)."""
    if len(lines) <= 1:
        return lines
    parent = list(range(len(lines)))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: int, b: int) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    pts: list[tuple[float, float]] = []
    owners: list[int] = []
    for idx, ls in enumerate(lines):
        coords = list(ls.coords)
        for c in coords:
            pts.append((float(c[0]), float(c[1])))
            owners.append(idx)
        # Also sample midpoints for T-junction connectivity
        if ls.length > snap_m * 2.0:
            mp = ls.interpolate(0.5, normalized=True).coords[0]
            pts.append((float(mp[0]), float(mp[1])))
            owners.append(idx)

    arr = np.asarray(pts, dtype=np.float64)
    tree = cKDTree(arr)
    for i, j in tree.query_pairs(r=bridge_m):
        oi, oj = owners[i], owners[j]
        if oi != oj:
            _union(oi, oj)

    comp_counts: dict[int, int] = {}
    for idx in range(len(lines)):
        r = _find(idx)
        comp_counts[r] = comp_counts.get(r, 0) + 1
    best_root = max(comp_counts, key=lambda r: comp_counts[r])
    return [ls for idx, ls in enumerate(lines) if _find(idx) == best_root]


def _project_onto_roads(
    e_pt: float,
    n_pt: float,
    road_ls_map: dict[str, LineString],
    candidate_ids: tuple[str, ...] | None = None,
    max_dist_m: float = 35.0,
) -> tuple[str, float, float, float, float] | None:
    """Project an LV95 point onto exported road LineStrings; returns (road_id, frac, dist_m, se, sn)."""
    pt = Point(e_pt, n_pt)
    best: tuple[str, float, float, float, float] | None = None
    ids = candidate_ids if candidate_ids is not None else tuple(road_ls_map.keys())
    for rid in ids:
        ls = road_ls_map.get(rid)
        if ls is None or ls.length < 1.0:
            continue
        d = float(ls.distance(pt))
        if d <= max_dist_m and (best is None or d < best[2]):
            s = float(ls.project(pt))
            frac = float(np.clip(s / float(ls.length), 0.0, 1.0))
            sp = ls.interpolate(s).coords[0]
            best = (rid, round(frac, 4), d, float(sp[0]), float(sp[1]))
    return best


def _build_network(
    scene: _AnimScene,
    cam: IsometricCamera,
    shift_x: float,
    shift_y: float,
    W_full: int,
    H_full: int,
    mvt: dict,
    obs_z_road: np.ndarray,
    underpass_poly,
    road_lv95: dict[str, tuple[np.ndarray, np.ndarray, float]],
) -> dict:
    """Build and strictly validate the Interface Contract #2 multimodal Kilchberg network."""
    road_ls_map: dict[str, LineString] = {
        rid: LineString(list(zip(er.tolist(), nr.tolist())))
        for rid, (er, nr, _lr) in road_lv95.items()
    }
    trans_feats = mvt.get("transportation", [])
    trans_name_feats = mvt.get("transportation_name", [])
    poi_feats = mvt.get("poi", [])

    def _dem_z(e_pt: float, n_pt: float) -> float:
        return float(_sample_bilinear_dem(scene.dem, np.array([e_pt]), np.array([n_pt]))[0])

    def _mvt_poi_coord(name_match: str, fallback: tuple[float, float]) -> tuple[float, float]:
        for g, p in poi_feats:
            if p.get("name") == name_match:
                c = g.centroid
                if _is_valid_land(scene, float(c.x), float(c.y)):
                    return float(c.x), float(c.y)
        return fallback

    def _validate_uv_d16(u: float, v: float, d16: int, label: str) -> None:
        assert 0.0 <= u <= 1.0, f"network {label}: u={u} out of [0,1]"
        assert 0.0 <= v <= 1.0, f"network {label}: v={v} out of [0,1]"
        assert 1 <= d16 <= 65534, f"network {label}: d16={d16} out of [1,65534]"

    # 1. Crosswalks (8 verified Swiss zebra crossings anchored to exact exported road frac)
    crosswalk_specs: list[tuple[str, str, str, str | None, float, float]] = [
        ("cw_bendlikon",      "Bendlikon (Seestrasse)",            "seestrasse_sb",          "seestrasse_nb",          2684046.7, 1241843.7),
        ("cw_lindt",          "Lindt & Sprüngli (Seestrasse)",     "seestrasse_sb",          "seestrasse_nb",          2684145.0, 1241545.0),
        ("cw_schooren_seebad", "Schooren / Seebad (Seestrasse)",   "seestrasse_sb",          "seestrasse_nb",          2684272.2, 1241360.5),
        ("cw_paradies",       "Paradiesstrasse / Mönchhof",        "seestrasse_sb",          "seestrasse_nb",          2683794.2, 1242581.3),
        ("cw_bahnhof_dorf",   "Bahnhof / Dorfstrasse",             "dorfstrasse_viaduct_up", "dorfstrasse_viaduct_dn", 2683968.7, 1241858.4),
        ("cw_schulhaus_dorf", "Schulhaus Dorfstrasse",             "dorfstrasse_viaduct_up", "dorfstrasse_viaduct_dn", 2683836.9, 1241822.6),
        ("cw_gemeindehaus",   "Gemeindehaus (Alte Landstrasse)",   "alte_landstrasse_eb",    "alte_landstrasse_wb",    2683651.3, 1242162.0),
        ("cw_schwelle",       "Schwelle / Dorf (Alte Landstrasse)", "alte_landstrasse_eb",   "alte_landstrasse_wb",    2683654.9, 1241790.5),
    ]
    crosswalks_out: list[dict] = []
    for cw_id, cw_name, rid, opp_rid, ce_raw, cn_raw in crosswalk_specs:
        ls = road_ls_map.get(rid)
        if ls is None:
            continue
        pt = Point(ce_raw, cn_raw)
        s = float(ls.project(pt))
        frac = round(float(np.clip(s / float(ls.length), 0.0, 1.0)), 4)
        p_main = ls.interpolate(s).coords[0]
        ce, cn = float(p_main[0]), float(p_main[1])
        # Center zebra anchor midway between opposing lanes so stripes straddle the full carriageway
        ls_opp = road_ls_map.get(opp_rid) if opp_rid else None
        if ls_opp is not None:
            p_opp = ls_opp.interpolate(float(ls_opp.project(Point(ce, cn)))).coords[0]
            mid_e, mid_n = 0.5 * (ce + float(p_opp[0])), 0.5 * (cn + float(p_opp[1]))
            if _is_valid_land(scene, mid_e, mid_n):
                ce, cn = mid_e, mid_n
        assert _is_valid_land(scene, ce, cn), f"crosswalk {cw_id} not on dry land"
        cz = _dem_z(ce, cn) + 0.35
        u, v, d16 = _proj_uv_d16(cam, shift_x, shift_y, W_full, H_full, ce, cn, cz, vehicle_h=1.7)
        _validate_uv_d16(u, v, d16, cw_id)

        # Screen-pixel unit normal perpendicular to road tangent at s +- 2.0 m
        sa = max(0.0, s - 2.0)
        sb = min(float(ls.length), s + 2.0)
        pa = ls.interpolate(sa).coords[0]
        pb = ls.interpolate(sb).coords[0]
        ua, va, _ = _proj_uv_d16(cam, shift_x, shift_y, W_full, H_full, float(pa[0]), float(pa[1]), _dem_z(float(pa[0]), float(pa[1])) + 0.35)
        ub, vb, _ = _proj_uv_d16(cam, shift_x, shift_y, W_full, H_full, float(pb[0]), float(pb[1]), _dem_z(float(pb[0]), float(pb[1])) + 0.35)
        tx = (ub - ua) * W_full
        ty = (vb - va) * H_full
        tn = max(1e-6, math.hypot(tx, ty))
        nx = round(-ty / tn, 4)
        ny = round(tx / tn, 4)

        crosswalks_out.append({
            "id": cw_id,
            "name": cw_name,
            "road_id": rid,
            "frac": frac,
            "u": u,
            "v": v,
            "d16": d16,
            "nx": nx,
            "ny": ny,
        })

    # 2. Major Kilchberg Junctions (6 verified intersections with exact links into roads[8])
    junction_specs: list[tuple[str, str, float, float]] = [
        ("junc_bendlikon",      "Bendlikon (Seestrasse / Dorfstrasse)",          2684040.7, 1241872.4),
        ("junc_moenchhof",      "Mönchhof (Alte Landstrasse / Dorfstrasse)",     2683629.4, 1242300.0),
        ("junc_bahnhof",        "Bahnhofplatz (Dorfstrasse / Bahnhofstrasse)",   2683968.7, 1241858.4),
        ("junc_schooren_lindt", "Schooren / Lindt (Seestrasse / Schoorenstr.)",  2684154.2, 1241527.5),
        ("junc_dorfplatz",      "Schwelle / Dorfplatz (Alte Landstrasse)",       2683654.9, 1241790.5),
        ("junc_paradies",       "Paradiesstrasse (Seestrasse / Paradiesstr.)",   2683770.5, 1242646.8),
    ]
    junctions_out: list[dict] = []
    for jid, jname, je, jn in junction_specs:
        assert _is_valid_land(scene, je, jn), f"junction {jid} not on dry land"
        jz = _dem_z(je, jn) + 0.35
        u, v, d16 = _proj_uv_d16(cam, shift_x, shift_y, W_full, H_full, je, jn, jz, vehicle_h=2.0)
        _validate_uv_d16(u, v, d16, jid)
        jpt = Point(je, jn)
        links: list[dict] = []
        for rid, ls in road_ls_map.items():
            if rid.startswith("a3_motorway"):
                continue
            if float(ls.distance(jpt)) <= 22.0:
                frac = round(float(np.clip(ls.project(jpt) / float(ls.length), 0.0, 1.0)), 4)
                links.append({"road_id": rid, "frac": frac})
        assert len(links) >= 1, f"junction {jid} has no road links"
        junctions_out.append({
            "id": jid,
            "name": jname,
            "u": u,
            "v": v,
            "d16": d16,
            "links": links,
        })

    # Pre-build the largest connected dry-land walkable MVT graph (used to snap off-street
    # landmark/school/park POIs to their authentic pedestrian street/footway entrance AND
    # to route all village footpaths on genuine MVT geometry).
    walk_raw = _flatten_lines([
        g for g, p in trans_feats
        if p.get("class") in ("footway", "path", "minor", "primary", "secondary", "tertiary", "service", "track")
        and p.get("brunnel") != "tunnel"
    ])
    land_walk_all: list[LineString] = []
    for ls in walk_raw:
        if ls.length < 0.8:
            continue
        c0, c1 = ls.coords[0], ls.coords[-1]
        mp = ls.interpolate(0.5, normalized=True).coords[0]
        if (
            _is_valid_land(scene, float(c0[0]), float(c0[1]))
            and _is_valid_land(scene, float(c1[0]), float(c1[1]))
            and _is_valid_land(scene, float(mp[0]), float(mp[1]))
        ):
            land_walk_all.append(ls)
    land_walk = _largest_connected_lines(land_walk_all, snap_m=1.5, bridge_m=10.0)
    u_walk = unary_union(land_walk)

    # Pre-build drivable dry-land MVT road segments for feeders that traverse unnamed minor
    # connectors or bridge short gaps (e.g. Schoorenstrasse railway crossing, upper Dorfstrasse/
    # Stockenstrasse, Breitloostrasse access).
    drive_raw = _flatten_lines([
        g for g, p in trans_feats
        if p.get("class") in ("minor", "tertiary", "secondary", "primary", "service")
        and p.get("brunnel") != "tunnel"
    ])
    drive_land: list[LineString] = []
    for ls in drive_raw:
        if ls.length < 0.8:
            continue
        c0, c1 = ls.coords[0], ls.coords[-1]
        mp = ls.interpolate(0.5, normalized=True).coords[0]
        if (
            _is_valid_land(scene, float(c0[0]), float(c0[1]))
            or _is_valid_land(scene, float(c1[0]), float(c1[1]))
            or _is_valid_land(scene, float(mp[0]), float(mp[1]))
        ):
            drive_land.append(ls)

    def _snap_to_walk_entrance(pe: float, pn: float, max_snap_m: float = 80.0) -> tuple[float, float]:
        """Snap an off-street building/campus centroid to its nearest dry-land walkable MVT entrance."""
        pt = Point(pe, pn)
        _, np_walk = nearest_points(pt, u_walk)
        we, wn = float(np_walk.x), float(np_walk.y)
        if pt.distance(np_walk) <= max_snap_m and _is_valid_land(scene, we, wn):
            return we, wn
        return pe, pn

    # 3. Typed POIs & Residential Neighbourhood Clusters
    bldgs_meta = scene.meta.get("buildings", [])
    b_gem = bldgs_meta[856] if len(bldgs_meta) > 856 else None
    b_st_e = bldgs_meta[1254] if len(bldgs_meta) > 1254 else None
    gem_en = (float(b_gem["e"]), float(b_gem["n"])) if b_gem else (2683610.2, 1242084.4)
    st_e_en = (float(b_st_e["e"]), float(b_st_e["n"])) if b_st_e else (2683480.0, 1241656.0)

    # Canonical LV95 coordinates for POIs (MVT-extracted where available; landward pierhead for Bendlikon Pier)
    poi_coords: dict[str, tuple[float, float]] = {}
    poi_uv: dict[str, tuple[float, float]] = {}
    pois_out: list[dict] = []
    non_mw_roads = tuple(rid for rid in road_ls_map if not rid.startswith("a3_motorway"))

    def _add_poi(
        pid: str,
        pname: str,
        pkind: str,
        pe: float,
        pn: float,
        max_road_dist_m: float = 35.0,
        vehicle_h: float = 1.7,
        snap_walk: bool = False,
    ) -> None:
        if snap_walk:
            pe, pn = _snap_to_walk_entrance(pe, pn)
        assert _is_valid_land(scene, pe, pn), f"POI {pid} ({pe:.1f}, {pn:.1f}) not on dry land"
        pz = _dem_z(pe, pn) + 0.35
        u, v, d16 = _proj_uv_d16(cam, shift_x, shift_y, W_full, H_full, pe, pn, pz, vehicle_h=vehicle_h)
        _validate_uv_d16(u, v, d16, pid)
        entry: dict = {
            "id": pid,
            "name": pname,
            "kind": pkind,
            "u": u,
            "v": v,
            "d16": d16,
        }
        proj = _project_onto_roads(pe, pn, road_ls_map, candidate_ids=non_mw_roads, max_dist_m=max_road_dist_m)
        if proj is not None:
            entry["road_id"] = proj[0]
            entry["road_frac"] = proj[1]
        pois_out.append(entry)
        poi_coords[pid] = (pe, pn)
        poi_uv[pid] = (u, v)

    # Transit hubs (rail + landward Bendlikon ZSG pierhead)
    _add_poi("poi_bahnhof", "Bahnhof Kilchberg (SBB)", "rail", 2683882.9, 1242070.7, max_road_dist_m=140.0)
    _add_poi("poi_bendlikon_pier", "Bendlikon Pier (ZSG Badweg)", "pier", 2684036.7, 1242066.4, max_road_dist_m=80.0)

    # Official ZVV/DIDOK bus stops from BUS_STOP_CATALOG
    bus_stop_ids = [
        "poi_bus_paradies",
        "poi_bus_bendlikon",
        "poi_bus_lindt",
        "poi_bus_schooren",
        "poi_bus_schulhaus_dorf",
        "poi_bus_schwelle",
        "poi_bus_gemeindehaus",
        "poi_bus_sanatorium",
        "poi_bus_paradiessteig",
        "poi_bus_hornhalden",
    ]
    for bs_id, (bs_name, bse, bsn) in zip(bus_stop_ids, BUS_STOP_CATALOG):
        _add_poi(bs_id, f"Bus {bs_name}", "bus_stop", bse, bsn, max_road_dist_m=25.0)

    # Landmarks, attractions, civic & cultural POIs (off-street campuses snapped to walkable entrance)
    _add_poi("poi_lindt_plaza", "Lindt Home of Chocolate", "landmark", 2684129.0, 1241412.0, max_road_dist_m=95.0, snap_walk=True)
    seebad_e, seebad_n = _mvt_poi_coord("Seebad Kilchberg", (2684322.8, 1241427.1))
    _add_poi("poi_seebad", "Seebad Kilchberg", "bath", seebad_e, seebad_n, max_road_dist_m=95.0, snap_walk=True)
    san_e, san_n = _mvt_poi_coord("Sanatorium Kilchberg", (2683512.0, 1242428.5))
    _add_poi("poi_sanatorium", "Sanatorium Kilchberg", "hospital", san_e, san_n, max_road_dist_m=120.0, snap_walk=True)
    _add_poi("poi_kirche", "Reformierte Kirche Kilchberg", "church", 2683400.0, 1241313.8, max_road_dist_m=60.0)
    _add_poi("poi_st_elisabeth", "Kirche St. Elisabeth", "church", st_e_en[0], st_e_en[1], max_road_dist_m=60.0)
    _add_poi("poi_gemeindehaus", "Gemeindehaus Kilchberg", "civic", gem_en[0], gem_en[1], max_road_dist_m=70.0, snap_walk=True)

    # Schools
    sd_e, sd_n = _mvt_poi_coord("Schulhaus Dorfstrasse", (2683795.4, 1241861.6))
    _add_poi("poi_schulhaus_dorf", "Schulhaus Dorfstrasse", "school", sd_e, sd_n, max_road_dist_m=70.0, snap_walk=True)
    sb_e, sb_n = _mvt_poi_coord("Schulhaus Brunnenmoos", (2683573.8, 1241554.4))
    _add_poi("poi_schulhaus_brunnenmoos", "Schulhaus Brunnenmoos", "school", sb_e, sb_n, max_road_dist_m=80.0, snap_walk=True)
    sal_e, sal_n = _mvt_poi_coord("Schulhaus Alte Landstrasse und Gemeindehaus", (2683617.4, 1242060.5))
    _add_poi("poi_schulhaus_alte_landstr", "Schulhaus Alte Landstrasse", "school", sal_e, sal_n, max_road_dist_m=70.0)
    camp_e, camp_n = _mvt_poi_coord("Campus Kilchberg", (2683507.3, 1240809.0))
    if _is_valid_land(scene, camp_e, camp_n):
        _add_poi("poi_campus_kilchberg", "Campus Kilchberg", "school", camp_e, camp_n, max_road_dist_m=80.0)

    # Parks & Fountains
    morf_e, morf_n = _mvt_poi_coord("Morfanlage", (2683888.0, 1242367.1))
    _add_poi("poi_morfanlage", "Morfanlage", "park", morf_e, morf_n, max_road_dist_m=80.0, snap_walk=True)
    nav_e, nav_n = _mvt_poi_coord("Navillepark", (2684165.0, 1241627.9))
    _add_poi("poi_navillepark", "Navillepark", "park", nav_e, nav_n, max_road_dist_m=80.0)
    sulz_e, sulz_n = _mvt_poi_coord("Sulzergut", (2684456.6, 1241147.6))
    if _is_valid_land(scene, sulz_e, sulz_n):
        _add_poi("poi_sulzergut", "Sulzergut Park", "park", sulz_e, sulz_n, max_road_dist_m=80.0)

    fountain_ids = ["poi_fountain_kirche", "poi_fountain_cf_meyer", "poi_fountain_bahnhof"]
    for fid, (fname, fe, fn) in zip(fountain_ids, FOUNTAIN_SPECS):
        _add_poi(fid, f"Brunnen {fname}", "fountain", fe, fn, max_road_dist_m=50.0)

    # Residential neighbourhood clusters computed dynamically from buildings_kilchberg_meta.json
    nb_accum: dict[str, list[tuple[float, float]]] = {}
    for b in bldgs_meta:
        nb = b.get("neighbourhood") or b.get("quartier") or ""
        if not nb:
            continue
        be, bn = float(b["e"]), float(b["n"])
        if _is_valid_land(scene, be, bn):
            nb_accum.setdefault(nb, []).append((be, bn))
    top_nbs = sorted(nb_accum.items(), key=lambda kv: -len(kv[1]))[:9]
    for nb_name, pts_nb in top_nbs:
        arr_nb = np.asarray(pts_nb, dtype=np.float64)
        ce, cn = float(arr_nb[:, 0].mean()), float(arr_nb[:, 1].mean())
        if not _is_valid_land(scene, ce, cn):
            # Fall back to building closest to centroid
            d2 = (arr_nb[:, 0] - ce) ** 2 + (arr_nb[:, 1] - cn) ** 2
            best_i = int(np.argmin(d2))
            ce, cn = float(arr_nb[best_i, 0]), float(arr_nb[best_i, 1])
        slug = re.sub(r"[^a-z0-9]+", "_", nb_name.lower().replace("ö", "oe").replace("ä", "ae").replace("ü", "ue")).strip("_")
        _add_poi(f"poi_res_{slug}", f"Quartier {nb_name}", "residential", ce, cn, max_road_dist_m=150.0)

    # 4. Residential / Village Feeder Streets (genuine MVT road geometry, every feeder snapped
    #    at pts[0] or pts[-1] within <= 25 px of its declared connects_road @ connects_frac)
    # route_mode: "named" (trans_name_feats only), "named+bridge" (named + nearby drive_land),
    #             or "drive_land" (genuine MVT minor/residential road network from main road).
    feeder_specs: list[tuple[str, str, str, tuple[float, float], tuple[float, float], float, str | None, str]] = [
        ("feeder_bahnhofstrasse",    "Bahnhofstrasse",    "residential", (2683968.7, 1241858.4), (2683882.9, 1242070.7), 6.5, "poi_bahnhof",        "named"),
        ("feeder_badweg",            "Badweg",            "lane",        (2683977.8, 1242044.9), (2684036.7, 1242066.4), 5.0, "poi_bendlikon_pier", "named"),
        ("feeder_paradiesstrasse",   "Paradiesstrasse",   "residential", (2683770.5, 1242646.8), (2683602.7, 1242358.2), 7.5, None,                 "named"),
        ("feeder_schoorenstrasse",   "Schoorenstrasse",   "residential", (2684154.2, 1241527.5), (2683959.5, 1240988.1), 7.5, "poi_lindt_plaza",    "named+bridge"),
        ("feeder_weinbergstrasse",   "Weinbergstrasse",   "residential", (2683879.6, 1241758.9), (2683512.3, 1242931.9), 8.0, None,                 "named"),
        ("feeder_schlimbergstrasse", "Schlimbergstrasse", "residential", (2683654.3, 1241800.6), (2683229.2, 1242268.9), 7.5, None,                 "named"),
        ("feeder_stockenstrasse",    "Stockenstrasse",    "residential", (2683654.9, 1241790.5), (2683055.5, 1242859.1), 9.0, "poi_kirche",         "drive_land"),
        ("feeder_breitloostrasse",   "Breitloostrasse",   "residential", (2683651.3, 1242162.0), (2682893.7, 1242447.3), 8.5, None,                 "drive_land"),
        ("feeder_kirchenweg",        "Kirchenweg",        "lane",        (2683752.4, 1241356.8), (2684009.6, 1241398.8), 7.0, "poi_kirche",         "named"),
    ]
    feeders_out: list[dict] = []
    for fid, fname, fkind, start_en, end_en, step_m, poi_id, route_mode in feeder_specs:
        if route_mode == "drive_land":
            route_segs = drive_land
        else:
            raw_segs = _flatten_lines([g for g, p in trans_name_feats if p.get("name") == fname])
            route_segs = []
            for ls in raw_segs:
                if ls.length < 1.0:
                    continue
                mp = ls.interpolate(0.5, normalized=True).coords[0]
                c0, c1 = ls.coords[0], ls.coords[-1]
                if (
                    _is_valid_land(scene, float(mp[0]), float(mp[1]))
                    or _is_valid_land(scene, float(c0[0]), float(c0[1]))
                    or _is_valid_land(scene, float(c1[0]), float(c1[1]))
                ):
                    route_segs.append(ls)
            if route_mode == "named+bridge" and route_segs:
                u_named = unary_union(route_segs)
                bridge_segs = [ls for ls in drive_land if ls.distance(u_named) < 15.0]
                route_segs = route_segs + bridge_segs
        if not route_segs:
            continue
        stitched = _stitch_exact_path(route_segs, start_en, end_en, subdiv_m=4.0, snap_m=1.5, bridge_m=12.0)
        if stitched is None:
            u_geom = unary_union(route_segs)
            merged_list = [u_geom] if u_geom.geom_type == "LineString" else _flatten_lines([linemerge(u_geom)])
            if not merged_list:
                continue
            stitched = max(merged_list, key=lambda g: float(g.length))
        clipped = _clip_land_polyline(stitched, scene, step_m=step_m, sig_m=1.4, inset_m=0.5)
        if clipped is None:
            continue
        ef, nf, lf = clipped
        assert np.all(_is_valid_land_arr(scene, ef, nf)), f"feeder {fid} has out-of-land point"
        zf, zf_d = _sample_road_z(scene, ef, nf, underpass_poly, allowed_bridge_cls=())
        pts = _pack_path(
            cam, shift_x, shift_y, W_full, H_full, obs_z_road,
            ef, nf, zf + 0.35, vehicle_h=2.0, z_depth=zf_d + 0.35,
        )
        for i, p in enumerate(pts):
            _validate_uv_d16(float(p[0]), float(p[1]), int(p[3]), f"{fid}[{i}]")
            if i > 0:
                assert abs(int(p[3]) - int(pts[i - 1][3])) < 1500, f"feeder {fid} d16 spike at {i}"

        # Connect feeder to nearest non-motorway main road (prefer closer endpoint)
        proj_start = _project_onto_roads(float(ef[0]), float(nf[0]), road_ls_map, candidate_ids=non_mw_roads, max_dist_m=30.0)
        proj_end = _project_onto_roads(float(ef[-1]), float(nf[-1]), road_ls_map, candidate_ids=non_mw_roads, max_dist_m=30.0)
        if proj_start is not None and (proj_end is None or proj_start[2] <= proj_end[2]):
            conn_road, conn_frac, conn_e, conn_n = proj_start[0], proj_start[1], proj_start[3], proj_start[4]
        elif proj_end is not None:
            conn_road, conn_frac, conn_e, conn_n = proj_end[0], proj_end[1], proj_end[3], proj_end[4]
        else:
            raise AssertionError(f"feeder {fid} endpoints did not snap within 30 m of any main road")

        # Verify screen-pixel snap distance <= 25 px at connects_road @ connects_frac
        cu, cv, _ = _proj_uv_d16(cam, shift_x, shift_y, W_full, H_full, conn_e, conn_n, _dem_z(conn_e, conn_n) + 0.35, vehicle_h=2.0)
        d_px_0 = math.hypot((float(pts[0][0]) - cu) * W_full, (float(pts[0][1]) - cv) * H_full)
        d_px_1 = math.hypot((float(pts[-1][0]) - cu) * W_full, (float(pts[-1][1]) - cv) * H_full)
        assert min(d_px_0, d_px_1) <= 25.0, (
            f"feeder {fid} endpoint snap to {conn_road}@{conn_frac} too far: {min(d_px_0, d_px_1):.1f} px"
        )

        f_entry: dict = {
            "id": fid,
            "name": fname,
            "kind": fkind,
            "length_m": round(lf, 1),
            "pts": pts,
            "connects_road": conn_road,
            "connects_frac": conn_frac,
        }
        if poi_id is not None and poi_id in poi_coords:
            f_entry["poi_id"] = poi_id
        feeders_out.append(f_entry)

    # 5. Connected DEM-Sampled Footpaths & Promenades (1 single connected component over land_walk)
    footpath_specs: list[tuple[str, str, str, str, str, tuple[float, float] | None, tuple[float, float] | None]] = [
        ("fp_bahnhof_dorf",          "Bahnhof → Bendlikon",              "commuter",  "poi_bahnhof",               "poi_bus_bendlikon",          None, None),
        ("fp_bahnhof_pier",          "Bahnhof → Bendlikon Pier",         "commuter",  "poi_bahnhof",               "poi_bendlikon_pier",         None, None),
        ("fp_pier_bendlikon",        "Bendlikon Pier → Seestrasse",      "promenade", "poi_bendlikon_pier",        "poi_bus_bendlikon",          None, None),
        ("fp_bendlikon_lindt",       "Seestrasse Promenade → Lindt",     "promenade", "poi_bus_bendlikon",         "poi_lindt_plaza",            None, None),
        ("fp_bus_lindt_plaza",       "Bus Lindt → Lindt Plaza",          "promenade", "poi_bus_lindt",             "poi_lindt_plaza",            None, None),
        ("fp_lindt_seebad",          "Lindt → Seebad Kilchberg",         "promenade", "poi_bus_lindt",             "poi_seebad",                 None, None),
        ("fp_seebad_schooren",       "Seebad → Schooren",                "promenade", "poi_seebad",                "poi_bus_schooren",           None, None),
        ("fp_bahnhof_schulhaus_dorf", "Bahnhof Footbridge → Schulhaus",  "commuter",  "poi_bahnhof",               "poi_schulhaus_dorf",         None, None),
        ("fp_schulhaus_dorf_schwelle", "Schulhaus Dorf → Schwelle",      "village",   "poi_schulhaus_dorf",        "poi_bus_schwelle",           None, None),
        ("fp_schwelle_gemeindehaus", "Schwelle → Gemeindehaus",          "village",   "poi_bus_schwelle",          "poi_gemeindehaus",           None, None),
        ("fp_schwelle_brunnenmoos",  "Schwelle → Schulhaus Brunnenmoos", "village",   "poi_bus_schwelle",          "poi_schulhaus_brunnenmoos",  None, None),
        ("fp_brunnenmoos_kirche",    "Brunnenmoos → Reformierte Kirche", "village",   "poi_schulhaus_brunnenmoos", "poi_kirche",                 None, None),
        ("fp_gemeindehaus_sanatorium", "Gemeindehaus → Sanatorium Park", "park",      "poi_gemeindehaus",          "poi_sanatorium",             None, None),
        ("fp_pier_morfanlage",       "Bendlikon Pier → Morfanlage",      "promenade", "poi_bendlikon_pier",        "poi_morfanlage",             None, None),
    ]
    # Sidewalk preference (+1.0 = inland sidewalk, -1.0 = lakeward sidewalk) when a footpath
    # follows Seestrasse's MVT primary centerline.
    seestrasse_fp_side: dict[str, float] = {
        "fp_bahnhof_dorf": +1.0,
        "fp_bendlikon_lindt": +1.0,
        "fp_bus_lindt_plaza": +1.0,
        "fp_bahnhof_pier": +1.0,
        "fp_pier_morfanlage": -1.0,
        "fp_pier_bendlikon": -1.0,
        "fp_lindt_seebad": -1.0,
        "fp_seebad_schooren": -1.0,
    }
    see_sb_ls = road_ls_map.get("seestrasse_sb")
    see_nb_ls = road_ls_map.get("seestrasse_nb")

    footpaths_out: list[dict] = []
    for fpid, fpname, fpkind, from_poi, to_poi, start_ov, end_ov in footpath_specs:
        if from_poi not in poi_coords or to_poi not in poi_coords:
            continue
        s_en = start_ov if start_ov is not None else poi_coords[from_poi]
        e_en = end_ov if end_ov is not None else poi_coords[to_poi]
        stitched = _stitch_exact_path(land_walk, s_en, e_en, subdiv_m=4.0, snap_m=1.5, bridge_m=10.0)
        if stitched is None:
            continue
        clipped = _clip_land_polyline(stitched, scene, step_m=5.5, sig_m=1.2, inset_m=0.5)
        if clipped is None:
            continue
        ep, np_, lp = clipped
        if see_sb_ls is not None and see_nb_ls is not None:
            side = seestrasse_fp_side.get(fpid, +1.0)
            ep = ep.copy()
            np_ = np_.copy()
            for idx in range(len(ep)):
                pt = Point(float(ep[idx]), float(np_[idx]))
                p_sb = see_sb_ls.interpolate(see_sb_ls.project(pt))
                p_nb = see_nb_ls.interpolate(see_nb_ls.project(pt))
                cl_e = 0.5 * (p_sb.x + p_nb.x)
                cl_n = 0.5 * (p_sb.y + p_nb.y)
                ve = p_sb.x - p_nb.x
                vn = p_sb.y - p_nb.y
                vlen2 = ve * ve + vn * vn
                if math.hypot(ep[idx] - cl_e, np_[idx] - cl_n) < 7.5 and vlen2 > 1.0:
                    lat = ((ep[idx] - cl_e) * ve + (np_[idx] - cl_n) * vn) / vlen2
                    if abs(lat) < 1.15:
                        delta_lat = (side * 1.25) - lat
                        cand_e = ep[idx] + delta_lat * ve
                        cand_n = np_[idx] + delta_lat * vn
                        if _is_valid_land(scene, float(cand_e), float(cand_n)):
                            ep[idx] = cand_e
                            np_[idx] = cand_n
        assert np.all(_is_valid_land_arr(scene, ep, np_)), f"footpath {fpid} has out-of-land point"
        zp, zp_d = _sample_road_z(scene, ep, np_, underpass_poly, allowed_bridge_cls=())
        pts = _pack_path(
            cam, shift_x, shift_y, W_full, H_full, obs_z_road,
            ep, np_, zp + 0.25, vehicle_h=1.7, z_depth=zp_d + 0.25,
        )
        for i, p in enumerate(pts):
            _validate_uv_d16(float(p[0]), float(p[1]), int(p[3]), f"{fpid}[{i}]")
            if i > 0:
                assert abs(int(p[3]) - int(pts[i - 1][3])) < 1500, f"footpath {fpid} d16 spike at {i}"
        fu0, fv0 = poi_uv[from_poi]
        tu0, tv0 = poi_uv[to_poi]
        d_from_px = math.hypot((float(pts[0][0]) - fu0) * W_full, (float(pts[0][1]) - fv0) * H_full)
        d_to_px = math.hypot((float(pts[-1][0]) - tu0) * W_full, (float(pts[-1][1]) - tv0) * H_full)
        assert d_from_px <= 40.0 and d_to_px <= 40.0, (
            f"footpath {fpid} endpoint gap too large: d_from={d_from_px:.1f} px, d_to={d_to_px:.1f} px"
        )
        footpaths_out.append({
            "id": fpid,
            "name": fpname,
            "kind": fpkind,
            "length_m": round(lp, 1),
            "pts": pts,
            "from_poi": from_poi,
            "to_poi": to_poi,
        })

    # 6. Additional Active Sports Fields (5 verified fields from buildings_kilchberg_meta.json sports_fields[4:])
    sports_fields = scene.meta.get("sports_fields", [])
    extra_sports_specs: list[tuple[str, int]] = [
        ("sports_lakeside_tennis",        13),
        ("sports_brunnenmoos_football",   12),
        ("sports_brunnenmoos_multisport", 11),
        ("sports_gemeindehaus_multisport", 14),
        ("sports_hochweid_upper_football", 4),
    ]
    extra_sports_out: list[dict] = []
    for sp_id, sf_idx in extra_sports_specs:
        if sf_idx >= len(sports_fields):
            continue
        sf = sports_fields[sf_idx]
        se, sn = float(sf["e"]), float(sf["n"])
        if not _is_valid_land(scene, se, sn):
            continue
        sz = float(sf.get("z", _dem_z(se, sn)))
        u, v, d16 = _proj_uv_d16(cam, shift_x, shift_y, W_full, H_full, se, sn, sz + 0.25, vehicle_h=1.7)
        _validate_uv_d16(u, v, d16, sp_id)
        extra_sports_out.append({
            "id": sp_id,
            "kind": str(sf.get("kind", "multisport")),
            "u": u,
            "v": v,
            "d16": d16,
            "w_m": round(float(sf["width"]), 1),
            "h_m": round(float(sf["length"]), 1),
            "angle": round(float(sf["angle"]), 4),
        })

    network_out = {
        "crosswalks": crosswalks_out,
        "junctions": junctions_out,
        "feeders": feeders_out,
        "footpaths": footpaths_out,
        "pois": pois_out,
        "extra_sports": extra_sports_out,
    }

    # Final guardrail assertions on network block
    assert 6 <= len(crosswalks_out) <= 8, f"expected 6..8 crosswalks, got {len(crosswalks_out)}"
    assert len(junctions_out) >= 5, f"expected >=5 junctions, got {len(junctions_out)}"
    assert len(feeders_out) >= 8, f"expected >=8 feeders, got {len(feeders_out)}"
    assert len(footpaths_out) >= 10, f"expected >=10 footpaths, got {len(footpaths_out)}"
    assert len(pois_out) >= 25, f"expected >=25 pois, got {len(pois_out)}"
    assert 3 <= len(extra_sports_out) <= 5, f"expected 3..5 extra_sports, got {len(extra_sports_out)}"
    net_text = json.dumps(network_out, separators=(",", ":"))
    assert _PROHIBITED_AERIAL_RE.search(net_text) is None, "prohibited aerial term found in network JSON"
    return network_out


def export_animations(mpp_full: float = 0.125) -> Path:
    scene = _load_anim_scene(RAW_CACHE_DIR)
    cam = IsometricCamera(mpp=mpp_full)
    cam, _, _, W_full, H_full, shift_x, shift_y, *_ = compute_full_canvas_geometry(scene, cam, None, True)

    def proj_uv(e_pt: float, n_pt: float, z_pt: float) -> list[float]:
        px, py, _ = cam.project(np.array([e_pt]), np.array([n_pt]), np.array([z_pt]))
        return [round(float((px[0] + shift_x) / W_full), 5), round(float((py[0] + shift_y) / H_full), 5)]

    mvt = _load_mvt_features(RAW_CACHE_DIR)
    b_feat = json.loads((RAW_CACHE_DIR / "kilchberg_boundary_2056.geojson").read_text())
    kpoly = shape(b_feat["geometry"])
    lake_geoms = [g for g, p in mvt.get("water", []) if p.get("class") == "lake"]
    dpoly_rail = build_diorama_polygon(kpoly, unary_union(lake_geoms)).buffer(-1.0)

    # 1. SBB Seebahn Double-Track Railway (True Gleis 2 SB & Gleis 1 NB, Flat Rail Bridges, DIDOK 8503200 Stops)
    obs_z_rail = _build_obstacle_surface(scene, include_bridges=True)
    raw_rail = [
        g.intersection(dpoly_rail)
        for g, p in mvt.get("transportation", [])
        if p.get("class") == "rail" and p.get("brunnel") != "tunnel" and p.get("service") is None
    ]
    raw_rail = [g for g in raw_rail if not g.is_empty]
    rail_lines: list[LineString] = []
    if raw_rail:
        merged_r = linemerge(unary_union(raw_rail))
        rail_lines = _flatten_lines([merged_r])

    trains_out = []
    tracks = _extract_double_track_rail(rail_lines, step_m=3.0) if rail_lines else None
    if tracks is not None:
        (e_sb, n_sb, len_sb), (e_nb, n_nb, len_nb) = tracks
        carriages = 4
        # Canonical Bahnhof Kilchberg platform center (both Gleis 2 SB and Gleis 1 NB project directly here)
        bhf_pt = Point(2683868.0, 1242045.0)

        # Southbound track (Gleis 2, West/landward)
        ls_sb = LineString(list(zip(e_sb.tolist(), n_sb.tolist())))
        stop_frac_south = float(ls_sb.project(bhf_pt) / ls_sb.length)
        z_sb = _sample_rail_z(scene, e_sb, n_sb)
        trains_out.append({
            "id": "sbb_s8_south",
            "name": "SBB S-Bahn S8 (Zürich HB → Kilchberg → Pfäffikon SZ)",
            "kind": "sbb_dpz",
            "carriages": carriages,
            "length_m": round(len_sb, 1),
            "speed_mps": 18.5,
            "stop_frac": round(stop_frac_south, 4),
            "dwell_sec": 4.5,
            "phase": 0.12,
            "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, obs_z_rail, e_sb, n_sb, z_sb, vehicle_h=3.8),
        })

        # Northbound track (Gleis 1, East/lakeward)
        ls_nb = LineString(list(zip(e_nb.tolist(), n_nb.tolist())))
        stop_frac_north = float(ls_nb.project(bhf_pt) / ls_nb.length)
        z_nb = _sample_rail_z(scene, e_nb, n_nb)
        trains_out.append({
            "id": "sbb_ic_north",
            "name": "SBB EuroCity / S24 (Thalwil → Kilchberg → Zürich HB)",
            "kind": "sbb_ic",
            "carriages": carriages,
            "length_m": round(len_nb, 1),
            "speed_mps": 21.0,
            "stop_frac": round(stop_frac_north, 4),
            "dwell_sec": 3.5,
            "phase": 0.58,
            "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, obs_z_rail, e_nb, n_nb, z_nb, vehicle_h=3.8),
        })
    del obs_z_rail
    gc.collect()

    # 2. Road Network: All 8 Edge-to-Edge Corridors (Stitched UNCLIPPED -> Filleted -> Offset-Then-Clipped)
    obs_z_road = _build_obstacle_surface(scene, include_bridges=False)
    trans_feats = mvt.get("transportation", [])
    trans_name_feats = mvt.get("transportation_name", [])

    road_tunnel_geoms = [
        g.buffer(5.5)
        for g, p in trans_feats
        if p.get("class") != "rail"
        and (p.get("brunnel") == "tunnel" or (p.get("layer") is not None and p.get("layer") < 0))
    ]
    rail_occ_geoms = [
        g.buffer(7.5)
        for g, p in trans_feats
        if p.get("class") == "rail" and p.get("brunnel") != "tunnel"
    ]
    underpass_poly = unary_union(road_tunnel_geoms + rail_occ_geoms) if (road_tunnel_geoms or rail_occ_geoms) else None

    roads_out = []
    road_lv95: dict[str, tuple[np.ndarray, np.ndarray, float]] = {}

    def _emit_road(
        route_id: str,
        kind: str,
        ls_raw: LineString,
        step_m: float,
        offset_right_m: float,
        sig_m: float,
        speed_mps: float,
        has_bus: bool,
        bus_count: int,
        car_count: int,
        phase: float,
        allowed_bridge_cls: tuple[int, ...] = (),
        vehicle_h: float = 2.4,
    ) -> None:
        clipped = _offset_then_clip(
            ls_raw,
            scene.diorama_mask,
            step_m=step_m,
            offset_right_m=offset_right_m,
            sig_m=sig_m,
            inset_m=0.5,
        )
        if clipped is None:
            return
        er, nr, lr = clipped
        road_lv95[route_id] = (er, nr, lr)
        zr, zr_d = _sample_road_z(scene, er, nr, underpass_poly, allowed_bridge_cls=allowed_bridge_cls)
        entry: dict = {
            "id": route_id,
            "kind": kind,
            "length_m": round(lr, 1),
            "speed_mps": speed_mps,
            "has_bus": has_bus,
            "car_count": car_count,
            "phase": phase,
        }
        if has_bus:
            entry["bus_count"] = bus_count
            stops, stop_names = project_bus_stops(er, nr)
            if stops:
                entry["stops"] = stops
                entry["stop_names"] = stop_names
        entry["pts"] = _pack_path(
            cam,
            shift_x,
            shift_y,
            W_full,
            H_full,
            obs_z_road,
            er,
            nr,
            zr + 0.35,
            vehicle_h=vehicle_h,
            z_depth=zr_d + 0.35,
        )
        roads_out.append(entry)

    # Corridor 1: Seestrasse (NE <-> SW)
    see_geoms = [
        g for g, p in trans_feats
        if p.get("class") == "primary" and p.get("is_route") == 5 and p.get("brunnel") != "tunnel"
    ]
    see_sb_raw = _stitch_exact_path(
        see_geoms,
        (2683200.0, 1243450.0),
        (2684550.0, 1240800.0),
        subdiv_m=4.0,
        snap_m=1.2,
        bridge_m=3.5,
    )
    see_nb_raw = LineString(list(reversed(list(see_sb_raw.coords)))) if see_sb_raw is not None else None
    if see_sb_raw is not None and see_nb_raw is not None:
        _emit_road(
            "seestrasse_sb", "seestrasse", see_sb_raw,
            step_m=3.0, offset_right_m=1.80, sig_m=3.6,
            speed_mps=11.5, has_bus=True, bus_count=2, car_count=12, phase=0.0,
            allowed_bridge_cls=(), vehicle_h=2.4,
        )
        _emit_road(
            "seestrasse_nb", "seestrasse", see_nb_raw,
            step_m=3.0, offset_right_m=1.80, sig_m=3.6,
            speed_mps=11.5, has_bus=True, bus_count=2, car_count=12, phase=0.37,
            allowed_bridge_cls=(), vehicle_h=2.4,
        )

    # Corridor 2: Alte Landstrasse / Kilchbergstrasse (SW <-> NE)
    alte_geoms = [
        g for g, p in trans_name_feats
        if p.get("name") in ("Alte Landstrasse", "Kilchbergstrasse")
    ]
    alte_eb_stitched = _stitch_exact_path(
        alte_geoms,
        (2684180.0, 1240370.0),
        (2682950.0, 1243680.0),
        subdiv_m=4.0,
        snap_m=1.5,
        bridge_m=10.0,
    )
    alte_eb_raw = (
        _fillet_polyline(list(alte_eb_stitched.coords), corner_deg=20.0, max_trim_m=6.0, n_arc=8)
        if alte_eb_stitched is not None
        else None
    )
    alte_wb_raw = LineString(list(reversed(list(alte_eb_raw.coords)))) if alte_eb_raw is not None else None

    # Corridor 3: Dorfstrasse Horseshoe Viaduct (SW Seestrasse -> Bendlikon -> Viaduct bid=10 -> Gemeindehaus -> Mönchhof -> NE)
    dorf_geoms = [
        g for g, p in trans_feats
        if p.get("is_route") == 11 and p.get("class") in ("primary", "minor") and p.get("brunnel") != "tunnel"
    ]
    bendlikon_junc = (2684040.7, 1241872.4)
    viaduct_apex = (2683973.1, 1241714.5)
    gemeindehaus_pt = (2683785.4, 1241907.6)
    moenchhof_junc = (2683629.4, 1242300.0)

    leg1 = _stitch_exact_path(dorf_geoms, bendlikon_junc, viaduct_apex, subdiv_m=4.0, snap_m=1.2, bridge_m=3.5)
    leg2 = _stitch_exact_path(dorf_geoms, viaduct_apex, gemeindehaus_pt, subdiv_m=4.0, snap_m=1.2, bridge_m=3.5)
    leg3 = _stitch_exact_path(dorf_geoms, gemeindehaus_pt, moenchhof_junc, subdiv_m=4.0, snap_m=1.2, bridge_m=3.5)
    if leg1 is not None and leg2 is not None and leg3 is not None and see_nb_raw is not None and alte_eb_raw is not None:
        dorf_core_coords = list(leg1.coords) + list(leg2.coords)[1:] + list(leg3.coords)[1:]
        dorf_core_up = _fillet_polyline(dorf_core_coords, corner_deg=20.0, max_trim_m=6.5, n_arc=10)
        dorf_up_1 = _join_with_fillet(see_nb_raw, dorf_core_up, bendlikon_junc, trim_m=8.0, n_arc=12)
        dorf_up_raw = _join_with_fillet(dorf_up_1, alte_eb_raw, moenchhof_junc, trim_m=8.0, n_arc=12)
        dorf_dn_raw = LineString(list(reversed(list(dorf_up_raw.coords))))

        _emit_road(
            "dorfstrasse_viaduct_up", "viaduct", dorf_up_raw,
            step_m=2.0, offset_right_m=1.25, sig_m=3.8,
            speed_mps=8.5, has_bus=True, bus_count=2, car_count=7, phase=0.14,
            allowed_bridge_cls=(BR_ROAD_VIADUCT,), vehicle_h=2.4,
        )
        _emit_road(
            "dorfstrasse_viaduct_dn", "viaduct", dorf_dn_raw,
            step_m=2.0, offset_right_m=1.25, sig_m=3.8,
            speed_mps=8.5, has_bus=True, bus_count=2, car_count=7, phase=0.62,
            allowed_bridge_cls=(BR_ROAD_VIADUCT,), vehicle_h=2.4,
        )

    # Corridor 4: A3 Motorway (NB a3_motorway_0 & SB a3_motorway_1 — rides BR_MOTORWAY only, ignores overhead bid=9!)
    mw_lines = _flatten_lines([
        g for g, p in trans_feats
        if p.get("class") == "motorway" and p.get("brunnel") != "tunnel"
    ])
    mw_nb_segs = [ls for ls in mw_lines if ls.coords[-1][1] > ls.coords[0][1]]
    mw_sb_segs = [ls for ls in mw_lines if ls.coords[-1][1] <= ls.coords[0][1]]

    mw_nb_raw = _stitch_exact_path(
        mw_nb_segs, (2683540.0, 1240370.0), (2682659.0, 1242040.0),
        subdiv_m=4.0, snap_m=1.2, bridge_m=3.5,
    )
    mw_sb_raw = _stitch_exact_path(
        mw_sb_segs, (2682650.0, 1242040.0), (2683528.0, 1240370.0),
        subdiv_m=4.0, snap_m=1.2, bridge_m=3.5,
    )
    if mw_nb_raw is not None:
        _emit_road(
            "a3_motorway_0", "motorway", mw_nb_raw,
            step_m=3.2, offset_right_m=0.0, sig_m=3.2,
            speed_mps=24.0, has_bus=False, bus_count=0, car_count=12, phase=0.0,
            allowed_bridge_cls=(BR_MOTORWAY,), vehicle_h=2.4,
        )
    if mw_sb_raw is not None:
        _emit_road(
            "a3_motorway_1", "motorway", mw_sb_raw,
            step_m=3.2, offset_right_m=0.0, sig_m=3.2,
            speed_mps=24.0, has_bus=False, bus_count=0, car_count=12, phase=0.41,
            allowed_bridge_cls=(BR_MOTORWAY,), vehicle_h=2.4,
        )

    # Emit Corridor 2 (Alte Landstrasse EB/WB) with 1.05 m offset (100% on narrow hw=1.85m mid-section) + full occlusion
    if alte_eb_raw is not None and alte_wb_raw is not None:
        _emit_road(
            "alte_landstrasse_eb", "village", alte_eb_raw,
            step_m=2.4, offset_right_m=1.05, sig_m=4.2,
            speed_mps=9.2, has_bus=True, bus_count=1, car_count=6, phase=0.11,
            allowed_bridge_cls=(), vehicle_h=2.2,
        )
        _emit_road(
            "alte_landstrasse_wb", "village", alte_wb_raw,
            step_m=2.4, offset_right_m=1.05, sig_m=4.2,
            speed_mps=9.2, has_bus=True, bus_count=1, car_count=6, phase=0.58,
            allowed_bridge_cls=(), vehicle_h=2.2,
        )
    # 2b. Multimodal Geography & Network Export (reuses obs_z_road & exact road_lv95 before freeing)
    network_out = _build_network(
        scene, cam, shift_x, shift_y, W_full, H_full, mvt, obs_z_road, underpass_poly, road_lv95,
    )
    del obs_z_road
    gc.collect()

    # 3. Lake Zurich ZSG Passenger Steamer (Edge-to-Edge NE -> SW docking at canonical Badweg 1.1) & Leisure Vessels
    ships_out = []
    dock_pt = (2684074.4, 1242080.2)  # +8.5 m lakeward along outer pier normal of Badweg 1.1
    steamer_ctrl = [
        (2683825.0, 1243358.0),  # NE Lake Zurich aquarium cut-edge entry
        (2683910.0, 1243040.0),  # Offshore Mönchhof / Horn
        (2684015.0, 1242670.0),  # Offshore Paradies / Mönchhof
        (2684095.0, 1242330.0),  # Wide offshore sweep north of Bendlikon Bay
        (2684068.0, 1242142.0),  # Aligned berthing approach NNW of Badweg 1.1
        dock_pt,                 # Bendlikon ZSG Steamer Pier (Badweg 1.1 outer pontoon)
        (2684116.0, 1242008.0),  # Smooth departure clearing south-side moored boats
        (2684265.0, 1241830.0),  # Offshore past Bendlikon south jetty
        (2684405.0, 1241515.0),  # Offshore past Seebad Kilchberg & Lindt HoC
        (2684545.0, 1241275.0),  # Offshore past Sulzergut
        (2684670.0, 1241098.0),  # SW Lake Zurich aquarium cut-edge exit
    ]
    es_st, ns_st, len_st = _catmull_rom_closed_or_open(steamer_ctrl, step_m=3.5, closed=False)
    zs_st = np.full(len(es_st), LAKE_SURFACE_Z + 0.25, dtype=np.float64)
    st_ls = LineString(list(zip(es_st.tolist(), ns_st.tolist())))
    pier_frac = float(st_ls.project(Point(dock_pt)) / st_ls.length)
    ships_out.append({
        "id": "zsg_ms_helvetia",
        "name": "ZSG Lake Zurich Steamer (Zürich Bürkliplatz → Kilchberg Bendlikon → Thalwil)",
        "kind": "zsg_steamer",
        "length_m": round(len_st, 1),
        "speed_mps": 6.8,
        "stop_frac": round(pier_frac, 4),
        "dwell_sec": 5.5,
        "phase": 0.22,
        "pts": _pack_path(cam, shift_x, shift_y, W_full, H_full, None, es_st, ns_st, zs_st, vehicle_h=2.8),
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

    # 4. Ambient Anchors (Chimney Steam, Village Chimneys, Fountains, Swiss Flags, Gulls, Shoreline, Vignettes)
    bldgs_meta = scene.meta.get("buildings", [])

    # Lindt Hochkamin (idx=1773, Pilgerweg 52, 43.6 m brick chimney)
    if len(bldgs_meta) > 1773 and bldgs_meta[1773].get("objektart") == "Hochkamin":
        b_chim = bldgs_meta[1773]
        chimney_uv = proj_uv(float(b_chim["e"]), float(b_chim["n"]), float(b_chim["z_roof"]) + 0.4)
    else:
        chimney_uv = proj_uv(2684156.7, 1241360.1, 455.0)

    # 4 Swiss flags (preserve index order so fIdx===3 keeps the Kilchberg municipal crest flag in app.js!)
    if len(bldgs_meta) > 1390:
        b_seebad = bldgs_meta[1390]
        seebad_flag_uv = proj_uv(float(b_seebad["e"]), float(b_seebad["n"]), float(b_seebad["z_roof"]))
    else:
        seebad_flag_uv = proj_uv(2684263.1, 1241521.0, 415.1)

    if len(bldgs_meta) > 856:
        ge, gn, gz = _bldg_roof_anchor(scene, 856)
        gem_flag_uv = proj_uv(ge, gn, gz)
    else:
        gem_flag_uv = proj_uv(2683610.2, 1242084.4, 496.1)

    flags_out = [
        {"name": "Bendlikon Pier", "uv": proj_uv(2684061.0, 1242076.0, 410.2)},
        {"name": "Seebad Kilchberg", "uv": seebad_flag_uv},
        {"name": "Lindt Crest Tower", "uv": proj_uv(2684234.0, 1241352.0, 435.2)},
        {"name": "Bahnhof / Gemeindehaus", "uv": gem_flag_uv},
    ]

    # 10 curated pitched-roof residential chimneys projected dynamically from 3D LOD2 ridge vertices
    village_chimneys_out = []
    for bidx, ph in VILLAGE_CHIMNEY_SPECS:
        re, rn, rz = _bldg_ridge_apex(scene, bidx)
        cuv = proj_uv(re, rn, rz + 0.8)
        village_chimneys_out.append({"u": cuv[0], "v": cuv[1], "phase": ph})

    # 3 verified Kilchberg Dorfbrunnen fountains projected at bilinear DEM + 0.5 m
    fountains_out = []
    for fname, fe, fn in FOUNTAIN_SPECS:
        fz = float(_sample_bilinear_dem(scene.dem, np.array([fe]), np.array([fn]))[0]) + 0.5
        fuv = proj_uv(fe, fn, fz)
        fountains_out.append({"u": fuv[0], "v": fuv[1], "name": fname})

    # 4 open-water Lake Zurich gull orbits (canonical pixel-radii schema)
    gulls_out = [
        {"uv": proj_uv(2684190.0, 1242120.0, 435.0), "rx": 48, "ry": 22, "spd": 0.42, "ph": 0.10},
        {"uv": proj_uv(2684260.0, 1241880.0, 434.0), "rx": 46, "ry": 21, "spd": 0.39, "ph": 0.35},
        {"uv": proj_uv(2684380.0, 1241560.0, 438.0), "rx": 54, "ry": 24, "spd": 0.36, "ph": 0.58},
        {"uv": proj_uv(2684050.0, 1242560.0, 436.0), "rx": 42, "ry": 19, "spd": 0.48, "ph": 0.82},
    ]

    # Deterministic 120-point ordered SW -> NE Lake Zurich coastal shoreline
    shoreline_out = _extract_shoreline_uv(scene, cam, shift_x, shift_y, W_full, H_full, n_pts=120)

    # LV95-projected landmark vignette anchors (including St. Elisabeth freestanding bell tower fix)
    if len(bldgs_meta) > 1254:
        b_st_e = bldgs_meta[1254]
        st_e_e, st_e_n = float(b_st_e["e"]), float(b_st_e["n"])
        st_e_apex = float(b_st_e["z_roof"])
        st_e_belfry = st_e_apex - 6.0
    else:
        st_e_e, st_e_n, st_e_belfry, st_e_apex = 2683480.0, 1241656.0, 512.0, 518.0

    sports_fields = scene.meta.get("sports_fields", [])

    def _proj_field_vec(sf: dict, scale_l: float, scale_w: float) -> tuple[list[float], list[float], list[float]]:
        ce, cn, cz = float(sf["e"]), float(sf["n"]), float(sf["z"])
        ang = float(sf["angle"])
        hl = 0.5 * float(sf["length"]) * scale_l
        hw = 0.5 * float(sf["width"]) * scale_w
        ca, sa = math.cos(ang), math.sin(ang)
        uv_c = proj_uv(ce, cn, cz)
        uv_l = proj_uv(ce + hl * ca, cn + hl * sa, cz)
        uv_w = proj_uv(ce - hw * sa, cn + hw * ca, cz)
        return (
            uv_c,
            [round(uv_l[0] - uv_c[0], 5), round(uv_l[1] - uv_c[1], 5)],
            [round(uv_w[0] - uv_c[0], 5), round(uv_w[1] - uv_c[1], 5)],
        )

    if len(sports_fields) >= 4:
        sf_hoch = sports_fields[3]
        hoch_c, hoch_hl_raw, hoch_hw_raw = _proj_field_vec(sf_hoch, scale_l=0.957, scale_w=0.937)
        # Orient half_l SW -> NE (positive du) and half_w toward lake (positive dv) matching app.js pitch axis
        hoch_hl = hoch_hl_raw if hoch_hl_raw[0] >= 0.0 else [-hoch_hl_raw[0], -hoch_hl_raw[1]]
        hoch_hw = hoch_hw_raw if hoch_hw_raw[1] >= 0.0 else [-hoch_hw_raw[0], -hoch_hw_raw[1]]
        hoch_vignette = {"center": hoch_c, "half_l": hoch_hl, "half_w": hoch_hw}
    else:
        hoch_vignette = {
            "center": [0.31377, 0.22953],
            "half_l": [0.01364, -0.00936],
            "half_w": [0.00506, 0.00945],
        }

    tc_vignettes = []
    if len(sports_fields) >= 3:
        for sf_idx in (1, 2, 0):
            sf_tc = sports_fields[sf_idx]
            ce, cn, cz = float(sf_tc["e"]), float(sf_tc["n"]), float(sf_tc["z"])
            ang = float(sf_tc["angle"])
            hl = 0.5 * float(sf_tc["length"]) * 0.90
            hw = 0.5 * float(sf_tc["width"]) * 0.75
            ca, sa = math.cos(ang), math.sin(ang)
            p_a = proj_uv(ce - hl * ca, cn - hl * sa, cz)
            p_b = proj_uv(ce + hl * ca, cn + hl * sa, cz)
            sw_uv, ne_uv = (p_a, p_b) if p_a[0] <= p_b[0] else (p_b, p_a)
            uv_c = proj_uv(ce, cn, cz)
            uv_lat = proj_uv(ce - hw * sa, cn + hw * ca, cz)
            lat_vec = [round(uv_lat[0] - uv_c[0], 5), round(uv_lat[1] - uv_c[1], 5)]
            if lat_vec[1] < 0.0:
                lat_vec = [-lat_vec[0], -lat_vec[1]]
            tc_vignettes.append({"sw": sw_uv, "ne": ne_uv, "lat": lat_vec})

    def _dem_z(e_pt: float, n_pt: float) -> float:
        return float(_sample_bilinear_dem(scene.dem, np.array([e_pt]), np.array([n_pt]))[0])

    def _vig_land_uv(label: str, e_pt: float, n_pt: float, dz: float = 0.5) -> list[float]:
        assert _is_valid_land(scene, e_pt, n_pt), f"vignette {label} ({e_pt}, {n_pt}) not on dry land"
        z_pt = _dem_z(e_pt, n_pt) + dz
        u, v, d16 = _proj_uv_d16(cam, shift_x, shift_y, W_full, H_full, e_pt, n_pt, z_pt, vehicle_h=1.7)
        assert 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0, f"vignette {label} UV out of [0,1]: {(u, v)}"
        assert 1 <= d16 <= 65534, f"vignette {label} d16 out of range: {d16}"
        return [u, v]

    def _vig_water_uv(label: str, e_pt: float, n_pt: float, dz: float = 0.05) -> list[float]:
        col = int(math.floor((e_pt - E_MIN) / GRID_RES))
        row = int(math.floor((N_MAX - n_pt) / GRID_RES))
        assert 0 <= col < GRID_W and 0 <= row < GRID_H, f"vignette {label} out of grid bounds"
        assert bool(scene.diorama_mask[row, col]) and bool(scene.lake_mask[row, col]), (
            f"vignette {label} ({e_pt}, {n_pt}) not on Lake Zurich water"
        )
        u, v, d16 = _proj_uv_d16(cam, shift_x, shift_y, W_full, H_full, e_pt, n_pt, LAKE_SURFACE_Z + dz, vehicle_h=1.0)
        assert 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0, f"vignette {label} UV out of [0,1]: {(u, v)}"
        assert 1 <= d16 <= 65534, f"vignette {label} d16 out of range: {d16}"
        return [u, v]

    vignettes_out = {
        "reformierte_kirche": {
            "clock": proj_uv(2683413.0, 1241288.0, 529.6),
            "belfry": proj_uv(2683413.0, 1241288.0, 537.4),
            "spire": proj_uv(2683413.0, 1241288.0, 546.2),
        },
        "st_elisabeth": {
            "belfry": proj_uv(st_e_e, st_e_n, st_e_belfry),
            "apex": proj_uv(st_e_e, st_e_n, st_e_apex),
        },
        "lindt_hoc": {
            "atrium": proj_uv(2684128.8, 1241412.7, 420.0),
            "plaza": proj_uv(2684129.0, 1241412.0, 413.9),
        },
        "bendlikon_pier": {
            "pier": proj_uv(2684061.0, 1242076.0, 410.2),
            "pax": proj_uv(2684054.3, 1242075.8, 407.2),
            "beacon": proj_uv(2684057.0, 1242086.0, 407.5),
        },
        "bahnhof_kilchberg": {
            "plat_sw": proj_uv(2683866.6, 1242011.4, 424.6),
            "plat_ne": proj_uv(2683855.9, 1242057.8, 424.7),
            "footbridge": [
                proj_uv(2683841.8, 1242055.5, 424.0),
                proj_uv(2683860.3, 1242064.1, 424.0),
            ],
            "signal": proj_uv(2683851.2, 1242071.4, 425.6),
        },
        "seebad_kilchberg": {
            "pool": proj_uv(2684287.7, 1241476.0, 405.7),
            "jetty": [
                proj_uv(2684303.3, 1241484.0, 406.5),
                proj_uv(2684334.6, 1241505.7, 406.5),
            ],
            "beacon": proj_uv(2684337.0, 1241507.1, 407.0),
        },
        "sportplatz_hochweid": hoch_vignette,
        "tc_kilchberg": tc_vignettes,
        "cf_meyer_haus": {
            "center": _vig_land_uv("cf_meyer_haus.center", 2683714.0, 1241442.0, dz=2.5),
            "fountain": _vig_land_uv("cf_meyer_haus.fountain", 2683720.0, 1241434.0, dz=0.5),
            "pergola": _vig_land_uv("cf_meyer_haus.pergola", 2683702.0, 1241426.0, dz=1.5),
            "gate": _vig_land_uv("cf_meyer_haus.gate", 2683727.1, 1241440.9, dz=1.0),
        },
        "sanatorium_ridge": {
            "pavilion": _vig_land_uv("sanatorium_ridge.pavilion", 2683535.3, 1242471.8, dz=4.0),
            "pergola": _vig_land_uv("sanatorium_ridge.pergola", 2683514.0, 1242442.0, dz=1.5),
            "greenhouses": [
                _vig_land_uv("sanatorium_ridge.gh1", 2683466.0, 1242355.0, dz=2.0),
                _vig_land_uv("sanatorium_ridge.gh2", 2683497.0, 1242332.0, dz=2.0),
            ],
        },
        "moenchhof_horn": {
            "hafenbeiz": _vig_land_uv("moenchhof_horn.hafenbeiz", 2683570.0, 1243005.0, dz=3.0),
            "terrace": _vig_land_uv("moenchhof_horn.terrace", 2683578.0, 1243008.0, dz=1.2),
            "boathouse": _vig_land_uv("moenchhof_horn.boathouse", 2683590.0, 1243016.0, dz=1.2),
            "water": _vig_water_uv("moenchhof_horn.water", 2683612.0, 1243025.0, dz=0.05),
        },
        "sulzergut_park": {
            "villa": _vig_land_uv("sulzergut_park.villa", 2684458.0, 1241153.0, dz=4.0),
            "boathouses": [
                _vig_land_uv("sulzergut_park.bh1", 2684432.0, 1241178.0, dz=1.2),
                _vig_land_uv("sulzergut_park.bh2", 2684410.0, 1241174.0, dz=1.2),
            ],
            "water": _vig_water_uv("sulzergut_park.water", 2684470.0, 1241205.0, dz=0.05),
        },
        "gemeindehaus_alte_landstr": {
            "center": _vig_land_uv("gemeindehaus.center", 2683628.9, 1242100.7, dz=4.0),
            "cupola": _vig_land_uv("gemeindehaus.cupola", 2683628.9, 1242100.7, dz=12.0),
            "flag_swiss": _vig_land_uv("gemeindehaus.flag_swiss", 2683646.0, 1242086.0, dz=1.0),
            "flag_muni": _vig_land_uv("gemeindehaus.flag_muni", 2683648.5, 1242091.0, dz=1.0),
            "schulhaus": _vig_land_uv("gemeindehaus.schulhaus", 2683635.0, 1242018.0, dz=3.0),
        },
        "stockengut_farm": {
            "barn": _vig_land_uv("stockengut_farm.barn", 2683207.0, 1242037.0, dz=4.0),
            "hofladen": _vig_land_uv("stockengut_farm.hofladen", 2683222.0, 1242024.0, dz=1.0),
            "silos": _vig_land_uv("stockengut_farm.silos", 2683187.0, 1241975.0, dz=8.0),
            "greenhouse": _vig_land_uv("stockengut_farm.greenhouse", 2683252.0, 1241998.0, dz=2.0),
        },
        "hallenbad_hochweid": {
            "pool_hall": _vig_land_uv("hallenbad_hochweid.pool_hall", 2683112.0, 1241399.0, dz=4.0),
            "entry": _vig_land_uv("hallenbad_hochweid.entry", 2683080.0, 1241431.0, dz=2.0),
            "track": _vig_land_uv("hallenbad_hochweid.track", 2683165.0, 1241435.0, dz=0.5),
        },
        "broelberggut_estate": {
            "manor": _vig_land_uv("broelberggut_estate.manor", 2683775.0, 1241245.0, dz=4.0),
            "tempelchen": _vig_land_uv("broelberggut_estate.tempelchen", 2683733.0, 1241261.0, dz=3.0),
            "terrace": _vig_land_uv("broelberggut_estate.terrace", 2683786.0, 1241244.0, dz=1.0),
        },
        "villa_spinnergut_tc": {
            "villa": _vig_land_uv("villa_spinnergut_tc.villa", 2683473.0, 1240852.0, dz=4.0),
            "pavilion": _vig_land_uv("villa_spinnergut_tc.pavilion", 2683471.0, 1240828.0, dz=2.0),
            "clubhouse": _vig_land_uv("villa_spinnergut_tc.clubhouse", 2683393.0, 1240918.0, dz=2.5),
        },
        "morfanlage_promenade": {
            "promenade": _vig_land_uv("morfanlage_promenade.promenade", 2683885.0, 1242360.0, dz=0.8),
            "boathouses": [
                _vig_land_uv("morfanlage_promenade.bh1", 2683867.0, 1242417.0, dz=1.2),
                _vig_land_uv("morfanlage_promenade.bh2", 2683867.0, 1242409.0, dz=1.2),
            ],
            "water": _vig_water_uv("morfanlage_promenade.water", 2683910.0, 1242375.0, dz=0.05),
        },
    }

    payload = {
        "canvas_width": W_full,
        "canvas_height": H_full,
        "mpp": mpp_full,
        "shift_y": round(float(shift_y), 6),
        "depth_min": DEPTH_MIN,
        "depth_max": DEPTH_MAX,
        "trains": trains_out,
        "roads": roads_out,
        "ships": ships_out,
        "ambient": {
            "chimney_steam": {"name": "Lindt Hochkamin (43.6 m)", "uv": chimney_uv},
            "village_chimneys": village_chimneys_out,
            "fountains": fountains_out,
            "swiss_flags": flags_out,
            "gulls": gulls_out,
            "shoreline": shoreline_out,
            "vignettes": vignettes_out,
        },
        "network": network_out,
    }

    out_p = DOCS_DIR / "data" / "kilchberg_animations.json"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, separators=(",", ":"))
    assert _PROHIBITED_AERIAL_RE.search(serialized) is None, "prohibited aerial term found in kilchberg_animations.json"
    out_p.write_text(serialized)
    size_bytes = out_p.stat().st_size
    assert size_bytes < 650 * 1024, f"kilchberg_animations.json too large: {size_bytes} bytes (>= 650 KB)"
    print(
        f"[anim] Exported {len(trains_out)} trains, {len(roads_out)} roads, "
        f"{len(ships_out)} ships/boats, {len(flags_out)} flags, "
        f"{len(village_chimneys_out)} chimneys, {len(fountains_out)} fountains, "
        f"{len(gulls_out)} gulls, {len(shoreline_out)} shoreline pts, "
        f"network(cw={len(network_out['crosswalks'])}, junc={len(network_out['junctions'])}, "
        f"feeders={len(network_out['feeders'])}, fp={len(network_out['footpaths'])}, "
        f"pois={len(network_out['pois'])}, sports={len(network_out['extra_sports'])}) -> "
        f"{out_p} ({size_bytes // 1024} KB)"
    )
    return out_p


if __name__ == "__main__":
    export_animations()
