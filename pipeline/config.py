"""Configuration, LV95 bounds, isometric camera math, and curated pixel-art palettes."""

from __future__ import annotations
import math
from dataclasses import dataclass
from pathlib import Path
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_CACHE_DIR = Path("/tmp/kilchberg-cache")
RENDERS_DIR = REPO_ROOT / "renders"
CROPS_DIR = RENDERS_DIR / "crops"
GIS_LAYERS_DIR = RENDERS_DIR / "gis_layers"
DOCS_DIR = REPO_ROOT / "docs"

# Official LV95 (EPSG:2056) domain covering 100% of Kilchberg (ZH) + Lake Zurich foreground basin
E_MIN = 2682780.0
E_MAX = 2684920.0
N_MIN = 1240400.0
N_MAX = 1243360.0

LAKE_SURFACE_Z = 405.95     # Zürichsee mean water level (m a.s.l., LHN95)
PLINTH_BASE_Z = 348.0       # Base elevation of the carved floating geological diorama block

# Center of projection in LV95
CENTER_E = 2683780.0
CENTER_N = 1241890.0


@dataclass(frozen=True)
class IsometricCamera:
    """Exact 3D orthographic dimetric (2:1 isometric) camera."""
    azimuth_from_deg: float = 102.0   # ESE over Lake Zurich looking WNW (282°) up Kilchberg's hillside
    pitch_deg: float = 30.0           # sin(30°)=0.5 -> classic 2:1 isometric ground slope
    z_exag: float = 1.16              # Subtle miniature-diorama vertical relief emphasis
    mpp: float = 0.72                 # Meters per pixel horizontally
    center_e: float = CENTER_E
    center_n: float = CENTER_N
    base_z: float = PLINTH_BASE_Z

    @property
    def basis(self):
        th = math.radians(self.azimuth_from_deg)
        # Camera sits in direction (+sin th, +cos th); depth goes away (-sin th, -cos th)
        e_depth = (-math.sin(th), -math.cos(th))
        # Right-hand horizontal screen +X vector (90° CCW from camera-to-origin in EN plane)
        e_right = (math.cos(th) if False else -e_depth[1], e_depth[0])
        # Wait: let's verify! At th=90° (camera due East, looking due West):
        # sin(90)=1, cos(90)=0 -> e_depth = (-1, 0) [West].
        # Looking West, North (0, +1) is to the RIGHT!
        # Let's check formula: (sin(th - 90°), cos(th - 90°)) -> at th=90°, (0, +1)!
        # At th=102°, th-90° = 12° -> (sin 12°, cos 12°) = (+0.2079, +0.9781)!
        # Cross product e_right_x * e_depth_y - e_right_y * e_depth_x:
        # sin(th-90)*(-cos th) - cos(th-90)*(-sin th) = cos(th)*cos(th) + sin(th)*sin(th) = +1.0!
        th_r = math.radians(self.azimuth_from_deg - 90.0)
        e_right = (math.sin(th_r), math.cos(th_r))
        pitch = math.radians(self.pitch_deg)
        return e_right, e_depth, math.sin(pitch), math.cos(pitch)

    def project(self, e: np.ndarray, n: np.ndarray, z: np.ndarray):
        """Project world (E, N, Z) -> (x_px_unshifted, y_px_unshifted_down, depth)."""
        e_right, e_depth, sp, cp = self.basis
        de = e - self.center_e
        dn = n - self.center_n
        dz = (z - self.base_z) * self.z_exag

        u_m = de * e_right[0] + dn * e_right[1]
        d_m = de * e_depth[0] + dn * e_depth[1]

        x_px = u_m / self.mpp
        y_up_m = sp * d_m + cp * dz
        y_px = -y_up_m / self.mpp
        depth = cp * d_m - sp * dz   # Smaller = closer to viewer
        return x_px, y_px, depth


# Curated landmarks of Kilchberg ZH (verified against swisstopo LV95 coordinates)
LANDMARKS = [
    {
        "id": "lindt_hoc",
        "name": "Lindt Home of Chocolate & Historic Factory",
        "subtitle": "Flagship atrium, 1899 chocolate works, 43.6 m brick chimney & cocoa silos",
        "category": "Architecture & Heritage",
        "e": 2684175.0,
        "n": 1241405.0,
        "z": 434.0,
        "crop_radius_m": 215.0,
    },
    {
        "id": "reformierte_kirche",
        "name": "Reformierte Kirche Kilchberg & Cemetery",
        "subtitle": "13th-century hilltop church (550.5 m spire) & graves of Thomas Mann and C.F. Meyer",
        "category": "Historic Monument",
        "e": 2683415.0,
        "n": 1241295.0,
        "z": 532.0,
        "crop_radius_m": 195.0,
    },
    {
        "id": "bendlikon_pier",
        "name": "Bendlikon Bay & ZSG Boat Pier",
        "subtitle": "Kilchberg ZH (See) steamer landing, moored sailboats & lakeside villas",
        "category": "Waterfront & Harbor",
        "e": 2684061.0,
        "n": 1242076.0,
        "z": 410.2,
        "crop_radius_m": 205.0,
    },
    {
        "id": "bahnhof_stockengut",
        "name": "Bahnhof Kilchberg, Dorfstrasse Viaduct & Schulhaus Dorfstrasse",
        "subtitle": "SBB Seebahn station, curved Dorfstrasse viaduct, hillside schoolhouse & Weinberg vineyards",
        "category": "Transit & Civic Core",
        "e": 2683885.0,
        "n": 1241910.0,
        "z": 438.0,
        "crop_radius_m": 235.0,
    },
    {
        "id": "schooren_seebad",
        "name": "Schooren Porcelain Quarter & Seebad Kilchberg",
        "subtitle": "1763 porcelain manufactory site, lakeside lido, Navillepark & Villa Naville",
        "category": "Parks & Lakefront",
        "e": 2684265.0,
        "n": 1241485.0,
        "z": 410.0,
        "crop_radius_m": 200.0,
    },
    {
        "id": "sanatorium_ridge",
        "name": "Sanatorium Kilchberg & Park Estate",
        "subtitle": "Historic 1906 pavilion campus amidst terraced woods above Alte Landstrasse",
        "category": "Historic Campus",
        "e": 2683505.0,
        "n": 1242435.0,
        "z": 488.0,
        "crop_radius_m": 205.0,
    },
    {
        "id": "st_elisabeth",
        "name": "Katholische Kirche St. Elisabeth & Brunnenmoos",
        "subtitle": "Sculptural modern church with freestanding 30.1 m bell tower & school campus",
        "category": "Architecture",
        "e": 2683505.0,
        "n": 1241635.0,
        "z": 505.0,
        "crop_radius_m": 175.0,
    },
    {
        "id": "cf_meyer_haus",
        "name": "Conrad Ferdinand Meyer-Haus",
        "subtitle": "19th-century poet's estate and literary museum (KGS-Nr. 7525) at Alte Landstrasse 170",
        "category": "Cultural Heritage",
        "e": 2683714.0,
        "n": 1241442.0,
        "z": 502.0,
        "crop_radius_m": 175.0,
    },
    {
        "id": "moenchhof_horn",
        "name": "Horn & Mönchhof Northern Shore",
        "subtitle": "Northern lakeside villas, Fischers Fritz waterfront & Zürich Wollishofen border",
        "category": "Waterfront",
        "e": 2683560.0,
        "n": 1243050.0,
        "z": 418.0,
        "crop_radius_m": 200.0,
    },
    {
        "id": "sulzergut_park",
        "name": "Sulzergut Lakeside Park & Boathouses",
        "subtitle": "Southern shoreline arboretum, historic boathouses & Rüschlikon boundary",
        "category": "Parks & Lakefront",
        "e": 2684410.0,
        "n": 1241150.0,
        "z": 410.0,
        "crop_radius_m": 180.0,
    },
    {
        "id": "gemeindehaus_alte_landstr",
        "name": "Gemeindehaus & Schulhaus Alte Landstrasse",
        "subtitle": "1930s Heimatstil town hall, civic forecourt, protected schoolhouse & ridge bell cupola",
        "category": "Civic & Education",
        "e": 2683630.0,
        "n": 1242075.0,
        "z": 455.0,
        "crop_radius_m": 190.0,
    },
    {
        "id": "stockengut_farm",
        "name": "Stockengut (Gutsbetrieb Uf-Stocken)",
        "subtitle": "Historic 507 m municipal hilltop farmstead, twin silos, glasshouse & alpine pastures",
        "category": "Rural Heritage & Ridge",
        "e": 2683207.0,
        "n": 1242037.0,
        "z": 507.0,
        "crop_radius_m": 195.0,
    },
    {
        "id": "hallenbad_hochweid",
        "name": "Hallenbad Kilchberg & Sportanlage Hochweid",
        "subtitle": "Terraced indoor swimming pavilion, red-ochre 400 m athletics track & upland pitches",
        "category": "Sports & Recreation",
        "e": 2683140.0,
        "n": 1241415.0,
        "z": 515.0,
        "crop_radius_m": 190.0,
    },
    {
        "id": "broelberggut_estate",
        "name": "Broelberggut & Parkpavillon",
        "subtitle": "Listed country manor (KGS-Nr. 12593), octagonal Tempelchen pavilion & parterre gardens",
        "category": "Cultural Heritage",
        "e": 2683775.0,
        "n": 1241245.0,
        "z": 468.0,
        "crop_radius_m": 175.0,
    },
    {
        "id": "villa_spinnergut_tc",
        "name": "Villa Spinnergut & Tennisclub Kilchberg",
        "subtitle": "1914 neo-baroque country villa, music school park & three clay tennis courts",
        "category": "Heritage & Sports",
        "e": 2683440.0,
        "n": 1240875.0,
        "z": 502.0,
        "crop_radius_m": 180.0,
    },
    {
        "id": "morfanlage_promenade",
        "name": "Morfanlage & Mönchhof Lakeside Park",
        "subtitle": "Public Lake Zurich shoreline park, limestone quay wall, bathing steps & timber boathouses",
        "category": "Parks & Lakefront",
        "e": 2683885.0,
        "n": 1242360.0,
        "z": 408.0,
        "crop_radius_m": 180.0,
    },
]
