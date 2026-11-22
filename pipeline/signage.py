"""Facade lettering baked into building surface textures.

A sign is rasterised ONCE from a real typeface (OpenType outlines rendered by FreeType through
Pillow) into a high-resolution coverage atlas.  The shader then samples that atlas per fragment in
the *wall plane's own metric coordinates* (s = metres along the facade, left->right as seen from the
camera; v = metres above a reference height).  Because the wall fragments are produced by the real
isometric rasteriser, orientation, shear and foreshortening come out of the projection itself --
no screen-space overlay, no rotation guess.

Typefaces (all vector fonts shipped with the URW base-35 set, metric clones of classic signage faces):
  * URW Gothic Demi (ITC Avant Garde Gothic clone) -- geometric caps, used for the Lindt & Sprüngli
    rooftop sign (typical 1960s-70s geometric sans letter-sign style).
  * P052 Bold (Palatino clone) -- engraved/applied serif caps for the Home of Chocolate frieze, in
    keeping with the Lindt wordmark's serif heritage.
  * Liberation Sans Bold (Helvetica/Arial metrics) -- Swiss-standard station / municipal signage.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_FILES = {
    "gothic": [
        "/usr/share/fonts/opentype/urw-base35/URWGothic-Demi.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "serif": [
        "/usr/share/fonts/opentype/urw-base35/P052-Bold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    ],
    "swiss": [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
}


def _load_font(kind: str, px: int) -> ImageFont.FreeTypeFont:
    for p in FONT_FILES[kind]:
        if Path(p).exists():
            return ImageFont.truetype(p, px)
    return ImageFont.load_default()


@dataclass
class SignAtlas:
    alpha: np.ndarray       # float32 (H, W) coverage 0..1, row 0 = top of the caps
    width_m: float          # physical width of the text run
    height_m: float         # physical cap height (ink bounding box height)
    text: str

    def sample(self, s: np.ndarray, v: np.ndarray, s0: float, v_base: float) -> np.ndarray:
        """Coverage at facade coords (s metres rightwards, v metres up). Sign's left edge at s0,
        baseline at v_base. Bilinear; returns 0 outside the sign box."""
        H, W = self.alpha.shape
        fx = (s - s0) / self.width_m * (W - 1)
        fy = (1.0 - (v - v_base) / self.height_m) * (H - 1)
        inside = (fx >= 0) & (fx <= W - 1) & (fy >= 0) & (fy <= H - 1)
        out = np.zeros(s.shape, dtype=np.float32)
        if not inside.any():
            return out
        x = fx[inside]
        y = fy[inside]
        x0 = np.floor(x).astype(np.int32)
        y0 = np.floor(y).astype(np.int32)
        x1 = np.minimum(x0 + 1, W - 1)
        y1 = np.minimum(y0 + 1, H - 1)
        ax = (x - x0).astype(np.float32)
        ay = (y - y0).astype(np.float32)
        a = self.alpha
        out[inside] = (
            a[y0, x0] * (1 - ax) * (1 - ay) + a[y0, x1] * ax * (1 - ay)
            + a[y1, x0] * (1 - ax) * ay + a[y1, x1] * ax * ay
        )
        return out


_CACHE: dict = {}


def build_sign(text: str, kind: str, cap_height_m: float, tracking: float = 0.06,
               px_cap: int = 96) -> SignAtlas:
    """Rasterise `text` in the given typeface with real letterforms; width follows font metrics."""
    key = (text, kind, round(cap_height_m, 3), tracking)
    if key in _CACHE:
        return _CACHE[key]
    font = _load_font(kind, px_cap * 4 // 3)
    # measure cap height from 'H' and lay out glyph by glyph (real advance widths + tracking)
    hb = font.getbbox("H")
    cap_px = max(1, hb[3] - hb[1])
    gap = int(round(tracking * cap_px))
    adv = []
    for ch in text:
        adv.append(font.getlength(ch) if ch != " " else font.getlength("n") * 0.9)
    total = int(sum(adv) + gap * (len(text) - 1)) + 8
    pad_top = int(cap_px * 0.35)  # room for umlauts / ampersand overshoot
    img = Image.new("L", (total, cap_px + pad_top + int(cap_px * 0.25)), 0)
    d = ImageDraw.Draw(img)
    x = 4.0
    base_y = pad_top + cap_px
    for ch, a in zip(text, adv):
        if ch != " ":
            d.text((x, base_y), ch, font=font, fill=255, anchor="ls")
        x += a + gap
    arr = np.asarray(img, dtype=np.float32) / 255.0
    ys, xs = np.nonzero(arr > 0.02)
    arr = arr[:, xs.min():xs.max() + 1]
    # keep vertical box = cap region (pad above for umlauts is cropped to ink top, below to baseline+desc)
    top = ys.min()
    bot = max(ys.max(), base_y)
    arr = arr[top:bot + 1]
    ink_h = base_y - top  # pixels from ink top to baseline
    height_m = cap_height_m * (arr.shape[0] / cap_px)
    width_m = cap_height_m * (arr.shape[1] / cap_px)
    sa = SignAtlas(alpha=arr.astype(np.float32), width_m=float(width_m), height_m=float(height_m), text=text)
    sa._ink_above_base = ink_h / cap_px * cap_height_m  # type: ignore[attr-defined]
    sa._below_base = (arr.shape[0] - ink_h) / cap_px * cap_height_m  # type: ignore[attr-defined]
    _CACHE[key] = sa
    return sa


def sample_on_baseline(sign: SignAtlas, s, v, s0: float, v_base: float) -> np.ndarray:
    """Like SignAtlas.sample but `v_base` is the letters' baseline (caps sit on it)."""
    below = getattr(sign, "_below_base", 0.0)
    return sign.sample(s, v, s0, v_base - below)


# ---------------------------------------------------------------------------------------------
# Sign registry: every sign is baked into the wall texture of a specific real building.
#   key       LANDMARK_SPECS key of the building the sign is mounted on
#   text      lettering as it exists in reality
#   font      typeface family (see FONT_FILES)
#   cap_m     preferred capital height in metres (auto-shrunk so the run fits the wall)
#   top_off   metres from the roof edge down to the TOP of the capitals
#   fg        letter colour (RGB)  /  panel optional background RGB (None = letters straight on wall)
#   lit       True if the real sign is illuminated (glows at night, warm glow at sunset)
# ---------------------------------------------------------------------------------------------
SIGNS = [
    # Iconic roof-line gilded letters of the 1899 Lindt & Sprüngli works (Seestrasse 204), seen from the lake
    dict(key="lindt_main", text="LINDT & SPRÜNGLI", font="serif", cap_m=2.7, top_off=1.5,
         fg=(212, 168, 56), panel=None, lit=True, edge=(88, 68, 28), edge_m=0.06, sh_off=0.14, sh_mul=0.58, fit=0.80),
    # Home of Chocolate: applied serif capitals stacked on the 13 m wide, 22 m tall white glazed-ceramic
    # curved facade (3 lines because the real curve is far narrower than the one-line word length)
    dict(key="lindt_hoc", text="LINDT", font="serif", cap_m=1.5, top_off=2.2, fg=(192, 144, 52), panel=None,
         lit=True, edge=None, sh_off=0.09, sh_mul=0.72, fit=0.96, thr=0.46, bins=[2, 3, 32, 33, 34, 35, 0, 1], curve=0.93, e_min=2684118.0, min_len=6.0),
    dict(key="lindt_hoc", text="HOME OF", font="serif", cap_m=1.5, top_off=4.0, fg=(192, 144, 52), panel=None,
         lit=True, edge=None, sh_off=0.09, sh_mul=0.72, fit=0.96, thr=0.46, bins=[2, 3, 32, 33, 34, 35, 0, 1], curve=0.93, e_min=2684118.0, min_len=6.0),
    dict(key="lindt_hoc", text="CHOCOLATE", font="serif", cap_m=1.5, top_off=5.8, fg=(192, 144, 52), panel=None,
         lit=True, edge=None, sh_off=0.09, sh_mul=0.72, fit=0.96, thr=0.46, bins=[2, 3, 32, 33, 34, 35, 0, 1], curve=0.93, e_min=2684118.0, min_len=6.0),
    # Station name board (SBB standard: white sans-serif "Kilchberg" on deep SBB blue, between upper floors)
    dict(key="bahnhof_station", text="Kilchberg", font="swiss", cap_m=0.65, top_off=3.4,
         fg=(248, 248, 246), panel=(36, 68, 128), lit=True, edge=None, fit=0.45),
    # Gemeindehaus Alte Landstrasse 110: clean dark lettering in upper plaster frieze above windows
    dict(key="gemeindehaus_main", text="GEMEINDEHAUS", font="swiss", cap_m=0.78, top_off=0.55,
         fg=(46, 40, 34), panel=(218, 210, 184), lit=False, edge=None, fit=0.58),
    # Hafenbeiz (Seestrasse 30): slab-serif cream on oxblood-red below attic gable taper
    dict(key="moenchhof_hafenbeiz_243", text="HAFENBEIZ", font="serif", cap_m=0.80, top_off=3.6,
         fg=(248, 240, 224), panel=(128, 44, 38), lit=True, edge=None, fit=0.78),
    # Real ZSG Waiting Pavilion (Seestrasse 157.1): dark lettering painted directly on white ENE lakeside gable
    dict(key="bendlikon_pavilion", text="Kilchberg-Bendlikon", font="serif", cap_m=0.52, top_off=2.55,
         fg=(28, 30, 34), panel=None, lit=False, edge=None, fit=0.88, bins=[0, 1, 2, 3, 4, 34, 35], min_len=3.5),
    # Real Hallenbad Kilchberg (Hochweidstr. 10) & Sporthalle Hochweid (Hochweidstr. 13): direct wall lettering
    dict(key="hallenbad_main_1835", text="Hallenbad Kilchberg", font="swiss", cap_m=0.85, top_off=0.75,
         fg=(62, 68, 74), panel=None, lit=False, edge=(244, 246, 246), edge_m=0.05, sh_off=0.08, fit=0.58, min_len=8.0),
    dict(key="hallenbad_entry_1628", text="SPORTHALLE HOCHWEID", font="swiss", cap_m=0.82, top_off=1.20,
         fg=(46, 50, 54), panel=None, lit=False, edge=None, fit=0.58, min_len=8.0),
]

def best_wall_run(scene, bidx: int, cam_az_deg: float, bins=None):
    """Longest contiguous coplanar facade run of building `bidx` that faces the camera.
    Returns dict(bin, d, s_lo, s_hi, ztop, t=(tx,ty), n=(nx,ny)) in absolute LV95 plane coordinates."""
    import math
    th = math.radians(cam_az_deg)
    cam = (math.sin(th), math.cos(th))
    m_b = (scene.bldg_idx == bidx) & (scene.surf_type == 0)
    best = None
    cand = bins if bins is not None else range(36)
    for bn in cand:
        a = bn * (2.0 * math.pi / 36.0)
        nx, ny = math.cos(a), math.sin(a)
        if nx * cam[0] + ny * cam[1] < 0.45:
            continue
        mm = m_b & (scene.tri_dir_bin == bn)
        if not mm.any():
            continue
        vv = scene.verts[mm].astype(np.float64)
        tx, ty = -ny, nx
        d = (vv[:, :, 0] * nx + vv[:, :, 1] * ny).mean(1)
        sv = vv[:, :, 0] * tx + vv[:, :, 1] * ty
        s0, s1 = sv.min(1), sv.max(1)
        zt, zb = vv[:, :, 2].max(1), vv[:, :, 2].min(1)
        planes = {}
        for k in range(len(d)):
            if s1[k] - s0[k] < 0.3:
                continue
            planes.setdefault(int(round(d[k])), []).append((s0[k], s1[k], zb[k], zt[k], d[k]))
        for pk, L in planes.items():
            L.sort()
            cur = list(L[0])
            runs = []
            for q in L[1:]:
                if q[0] <= cur[1] + 0.5:
                    cur[1] = max(cur[1], q[1]); cur[2] = min(cur[2], q[2]); cur[3] = max(cur[3], q[3])
                else:
                    runs.append(cur); cur = list(q)
            runs.append(cur)
            for r in runs:
                ln = r[1] - r[0]
                if best is None or ln > best["len"]:
                    best = dict(bin=bn, d=float(r[4]), s_lo=float(r[0]), s_hi=float(r[1]), ztop=float(r[3]),
                                zbot=float(r[2]), t=(tx, ty), n=(nx, ny), len=float(ln))
    return best


def proj_run(scene, bidx: int, cam_az_deg: float, bins, e_min: float, div: float):
    """Curved facade (polyline of short facets over several direction bins): coordinate s is the
    camera-horizontal position divided by the mean facet foreshortening `div`, i.e. ~arc length."""
    import math
    th = math.radians(cam_az_deg - 90.0)
    rx, ry = math.sin(th), math.cos(th)
    mm = (scene.bldg_idx == bidx) & (scene.surf_type == 0) & np.isin(scene.tri_dir_bin, list(bins))
    vv = scene.verts[mm].astype(np.float64)
    keep = vv[:, :, 0].mean(1) >= e_min
    vv = vv[keep]
    if len(vv) == 0:
        return None
    sr = vv[:, :, 0] * rx + vv[:, :, 1] * ry
    return dict(proj=True, bins=list(bins), e_min=e_min, rx=rx, ry=ry, div=div,
                s_lo=float(sr.min() / div), s_hi=float(sr.max() / div), len=float((sr.max() - sr.min()) / div),
                ztop=float(vv[:, :, 2].max()))


def resolve_signs(scene, cam_az_deg: float):
    """Pre-compute placement for each sign on the longest camera-facing contiguous wall, auto-fit."""
    out = []
    for sp in SIGNS:
        bidx = scene.lm_idx.get(sp["key"], -1)
        if bidx < 0:
            continue
        if sp.get("curve"):
            run = proj_run(scene, bidx, cam_az_deg, sp["bins"], sp["e_min"], sp["curve"])
        else:
            run = best_wall_run(scene, bidx, cam_az_deg, sp.get("bins"))
        if run is None or run["len"] < sp.get("min_len", 8.0):
            continue
        cap = sp["cap_m"]
        sign = build_sign(sp["text"], sp["font"], cap)
        max_w = run["len"] * sp["fit"]
        if sign.width_m > max_w:
            cap = cap * max_w / sign.width_m
            sign = build_sign(sp["text"], sp["font"], cap)
        if cap < 0.28:
            continue
        out.append(dict(bidx=bidx, run=run, sign=sign, s_c=0.5 * (run["s_lo"] + run["s_hi"]) + sp.get("shift", 0.0),
                        s0=-sign.width_m / 2.0, v_base=-(sp["top_off"] + cap), cap=cap, spec=sp))
    return out


def bake_signs(resolved, w_bi, w_dbin, w_e, w_n, w_z, w_base, f_mat, wi, lit_mat,
               preset_key: str, is_night: bool):
    """Paint every resolved sign into wall fragment colours (in place).  Coordinates are the wall
    plane's own metric (s along the facade, v below the wall's roof edge) so projection is exact."""
    for r in resolved:
        run = r["run"]
        if not (w_bi == r["bidx"]).any():
            continue
        if run.get("proj"):
            m = (w_bi == r["bidx"]) & np.isin(w_dbin, run["bins"]) & (w_e >= run["e_min"])
        else:
            m = (w_bi == r["bidx"]) & (w_dbin == run["bin"])
            if m.any():
                m &= np.abs(w_e * run["n"][0] + w_n * run["n"][1] - run["d"]) <= 1.0
        if not m.any():
            continue
        idx = np.nonzero(m)[0]
        if run.get("proj"):
            s = ((w_e[idx] * run["rx"] + w_n[idx] * run["ry"]) / run["div"] - r["s_c"]).astype(np.float32)
        else:
            s = (w_e[idx] * run["t"][0] + w_n[idx] * run["t"][1] - r["s_c"]).astype(np.float32)
        v = (w_z[idx] - run["ztop"]).astype(np.float32)
        sg, sp = r["sign"], r["spec"]
        cov = sample_on_baseline(sg, s, v, r["s0"], r["v_base"])
        thr = sp.get('thr', 0.5)
        letter = cov >= thr
        col = w_base[idx]
        if sp["panel"] is not None:
            mg = 0.35 + 0.35 * r["cap"]
            below = getattr(sg, "_below_base", 0.0)
            lo_v, hi_v = r["v_base"] - below, r["v_base"] - below + sg.height_m
            inbox = (s >= r["s0"] - mg) & (s <= r["s0"] + sg.width_m + mg) \
                & (v >= lo_v - mg * 0.6) & (v <= hi_v + mg * 0.6)
            inner = (s >= r["s0"] - mg + 0.12) & (s <= r["s0"] + sg.width_m + mg - 0.12) \
                & (v >= lo_v - mg * 0.6 + 0.12) & (v <= hi_v + mg * 0.6 - 0.12)
            col[inbox] = np.array(sp["panel"], dtype=np.float32)
            col[inbox & ~inner] = np.array(sp["panel"], dtype=np.float32) * 0.62
        else:
            sh_off = float(sp.get("sh_off", 0.16))
            sh_mul = float(sp.get("sh_mul", 0.58))
            sh = sample_on_baseline(sg, s - sh_off, v + sh_off, r["s0"], r["v_base"]) >= thr
            col[sh & ~letter] *= sh_mul
            if sp["edge"] is not None:
                em = float(sp.get("edge_m", 0.08))
                near = np.zeros_like(letter)
                for ds, dv in ((em, 0), (-em, 0), (0, em), (0, -em)):
                    near |= sample_on_baseline(sg, s + ds, v + dv, r["s0"], r["v_base"]) >= thr
                col[near & ~letter] = np.array(sp["edge"], dtype=np.float32)
        fg = np.array(sp["fg"], dtype=np.float32)
        glow = sp["lit"] and (is_night or preset_key == "sunset")
        if glow:
            if sp["key"] == "lindt_hoc" and is_night:
                fg = np.array((246, 204, 108), dtype=np.float32)
            else:
                fg = np.minimum(255.0, fg * (1.25 if is_night else 1.1) + (30.0 if is_night else 0.0))
        col[letter] = fg
        w_base[idx] = col
        if glow:
            f_mat[wi[idx[letter]]] = lit_mat


# ---------------------------------------------------------------------------------------------
# Wall clocks (white enamel dial, black ring/ticks/hands) in the same facade-plane coordinates.
#   r        dial radius in metres;  top_off  metres from roof edge down to the dial centre
#   shift    metres along the wall from the wall-run centre (left negative)
#   hm       (hour, minute) shown;   lit  glows at dusk/night (illuminated dial)
# ---------------------------------------------------------------------------------------------
# v11: All duplicate/phantom wall clocks removed (St. Elisabeth & Gemeindehaus have NO clocks;
# Reformierte Kirche's dark stone-tower dial, Lindt wing_twr clock, Bahnhof canopy clocks &
# Schulhaus Alte Landstrasse Dachreiter cupola clock are rendered authentically in pixel_shader.py).
CLOCKS = []


def resolve_clocks(scene, cam_az_deg: float):
    out = []
    for ck in CLOCKS:
        bidx = scene.lm_idx.get(ck["key"], -1)
        if bidx < 0:
            continue
        run = best_wall_run(scene, bidx, cam_az_deg, ck.get("bins"))
        if run is None or run["len"] < ck["min_len"]:
            continue
        r = min(ck["r"], run["len"] * 0.22)
        out.append(dict(bidx=bidx, run=run, s_c=0.5 * (run["s_lo"] + run["s_hi"]) + ck["shift"], r=r, spec=ck))
    return out


def bake_clocks(resolved, w_bi, w_dbin, w_e, w_n, w_z, w_base, f_mat, wi, lit_mat,
                preset_key: str, is_night: bool):
    for c in resolved:
        run, sp = c["run"], c["spec"]
        m = (w_bi == c["bidx"]) & (w_dbin == run["bin"])
        if not m.any():
            continue
        m &= np.abs(w_e * run["n"][0] + w_n * run["n"][1] - run["d"]) <= 1.0
        if not m.any():
            continue
        idx = np.nonzero(m)[0]
        x = (w_e[idx] * run["t"][0] + w_n[idx] * run["t"][1] - c["s_c"]).astype(np.float32)
        y = (w_z[idx] - run["ztop"] + sp["top_off"]).astype(np.float32)   # up positive from dial centre
        r = c["r"]
        rr = np.hypot(x, y)
        bezel_outer = r * 1.08
        on_all = rr <= bezel_outer
        if not on_all.any():
            continue
        on = rr <= r
        col = w_base[idx]
        glow = sp["lit"] and (is_night or preset_key == "sunset")
        face = np.array((250, 236, 168) if glow else (244, 240, 228), dtype=np.float32)
        ink = np.array((24, 24, 28), dtype=np.float32)
        # 3D metallic or gilded outer bezel ring (sunlit top-left, shaded bottom-right)
        bezel = on_all & (rr >= r - max(0.10, 0.06 * r))
        bezel_sun = (y - x) > 0.0
        if sp.get("gilded"):
            b_hi = np.array((222, 186, 98), dtype=np.float32)
            b_lo = np.array((118, 90, 42), dtype=np.float32)
        else:
            b_hi = np.array((198, 204, 212), dtype=np.float32)
            b_lo = np.array((72, 78, 88), dtype=np.float32)
        col[bezel & bezel_sun] = b_hi
        col[bezel & ~bezel_sun] = b_lo
        inner_r = r - max(0.10, 0.06 * r)
        dial = rr < inner_r
        col[dial] = face
        # Crisp dark inner rim
        rim = dial & (rr >= inner_r - max(0.08, 0.05 * r))
        col[rim] = ink
        ang = np.arctan2(x, y)  # clockwise from 12 o'clock
        # 4 bold cardinal hour bars (12/3/6/9) + 8 slender hour ticks
        card_step = np.pi / 2.0
        card_dev = np.abs(((ang + card_step / 2) % card_step) - card_step / 2) * rr
        card_ticks = dial & (rr >= 0.66 * r) & (rr < inner_r - max(0.08, 0.05 * r)) & (card_dev < max(0.08, 0.055 * r))
        step = np.pi / 6.0
        dev = np.abs(((ang + step / 2) % step) - step / 2) * rr
        hour_ticks = dial & (rr >= 0.74 * r) & (rr < inner_r - max(0.08, 0.05 * r)) & (dev < max(0.055, 0.032 * r))
        col[hour_ticks | card_ticks] = ink
        h, mi = sp["hm"]
        th_m = 2 * np.pi * mi / 60.0
        th_h = 2 * np.pi * ((h % 12) + mi / 60.0) / 12.0

        def hand(theta, length, width, tail=0.14):
            ux, uy = np.sin(theta), np.cos(theta)
            along = x * ux + y * uy
            perp = np.abs(x * uy - y * ux)
            return dial & (along >= -tail * r) & (along <= length * r) & (perp <= width * r)

        col[hand(th_h, 0.50, 0.072) | hand(th_m, 0.78, 0.048)] = ink
        # Authentic SBB red seconds-paddle hand on Bahnhof Kilchberg clock
        if sp.get("sbb"):
            th_s = 2 * np.pi * 22.0 / 60.0  # classic ~22s SBB paddle pose
            sbb_red = np.array((214, 34, 34), dtype=np.float32)
            stem = hand(th_s, 0.62, 0.028, tail=0.18)
            px_c = np.sin(th_s) * 0.60 * r
            py_c = np.cos(th_s) * 0.60 * r
            paddle = dial & (np.hypot(x - px_c, y - py_c) <= 0.11 * r)
            col[stem | paddle] = sbb_red
        col[dial & (rr <= 0.085 * r)] = ink
        w_base[idx] = col
        if glow:
            f_mat[wi[idx[dial]]] = lit_mat
