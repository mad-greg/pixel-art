# Kilchberg ZH — Isometric Pixel Art Diorama

An ultra-detailed isometric pixel-art diorama of **Kilchberg (ZH), Switzerland** (`BFS #0135`), built procedurally and deterministically from **100% official public Swiss geospatial datasets (`swisstopo`)**.

> **Build Status:** 🚧 *Active Pipeline Construction — Milestone 1 (GIS Ingestion & First Prototype Render)*

## Official Public Data Sources (`EPSG:2056 / LV95 + LHN95`)

| Layer | Dataset | Resolution / Spec | Features in Kilchberg ZH |
| :--- | :--- | :--- | :--- |
| **Municipal Boundary** | `ch.swisstopo.swissboundaries3d` (2026) | Official vector polygon | `258.04 ha` (`E: 2682828–2684500`, `N: 1240448–1243312`) |
| **Bare-Earth Terrain** | `ch.swisstopo.swissalti3d` (2026) | `0.5 m` LiDAR DTM | Lake Zurich shore (`406.0 m`) to Zimmerberg crest (`545 m`) |
| **Canopy & Surface** | `ch.swisstopo.swisssurface3d-raster` (2024/25) | `0.5 m` LiDAR DSM | Individual tree crowns, hedgerows, vineyards & moored boats |
| **3D Buildings (LOD2)** | `ch.swisstopo.swissbuildings3d_3_0` (2025) | Watertight 3D CityGML | `1,864` Kilchberg buildings (`2,203` w/ context), `139,986` 3D roof/wall triangles |
| **Satellite / Aerial** | `ch.swisstopo.swissimage-dop10` (2025) | `10 cm` True-Color RGB | Per-roof tile material & color, lawns, pools, plazas, harbor boats |
| **Streets, Rail & Lake** | `ch.swisstopo.base.vt` (`swissTLM3D` / `BATHY3D`) | Vector topography | Streets, footpaths, SBB Seebahn, 230 pools/water bodies, Zürichsee bathymetry |

## Key Landmarks Modeled in 3D

- **Lindt Home of Chocolate & Historic Lindt & Sprüngli Factory** (`Seestrasse`, incl. the `43.6 m` historic smokestack & 6 cocoa silos)
- **Reformierte Kirche Kilchberg & Cemetery** (`550.5 m` a.s.l. spire crest; resting place of Thomas Mann & Conrad Ferdinand Meyer)
- **Katholische Kirche St. Elisabeth** (`30.1 m` bell tower)
- **Bendlikon Bay, ZSG Steamer Pier (`Kilchberg ZH (See)`) & Seebad Kilchberg**
- **SBB Bahnhof Kilchberg, Weinberg Vineyards & Stockengut**
- **Sanatorium Kilchberg, Conrad Ferdinand Meyer-Haus & Historic Schooren Quarter**
