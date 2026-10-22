"""
03_hospitals.py
Race to A&E - Step 3: the emergency departments.

EU capitals: Eurostat GISCO's register of healthcare services, which comes from
each country's health ministry or statistics office, keeping hospitals marked
as providing emergency care (emergency = yes).
London (the UK isn't in GISCO), and any city where GISCO has no emergency
flags: OpenStreetMap hospitals tagged emergency=yes, read from the same
Geofabrik files as step 2 (no Overpass server needed).

Hospitals within 8 km of the urban centre count, so people near the edge can
use one just outside. Sites within 300 m of each other are treated as one.

To correct a list, copy results/hospitals_<city>.csv to config/hospitals/<city>.csv
(columns name, lat, lon), edit it and run this step again: the config file wins.

Usage (from the project folder, after step 2):
    python scripts/03_hospitals.py
    python scripts/03_hospitals.py --clean      # then delete the OpenStreetMap downloads from step 2

Outputs:
    data/processed/<city>/hospitals.csv    name, lat, lon, source
    results/hospitals_<city>.csv           the same, to review
"""

import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

import race
from common import CONFIG, RAW, RESULTS, chosen, city_args, city_dir, download, log

GISCO = ["https://gisco-services.ec.europa.eu/pub/healthcare/{v}/gpkg/{cc}.gpkg"]
GISCO_VERSIONS = ["2023", "2023_v2025_11", "2020"]
YES = {"yes", "y", "true", "1", "si", "oui", "ja"}


def from_gisco(cc, area):
    for v in GISCO_VERSIONS:
        try:
            path = download(GISCO[0].format(v=v, cc=cc), RAW / "gisco" / f"{cc}_{v}.gpkg", quiet_404=True)
        except Exception as e:  # noqa: BLE001
            log(f"  ! GISCO {v}: {e}")
            continue
        if path:
            break
    else:
        return None
    g = gpd.read_file(path).to_crs(race.WGS84)
    if "emergency" not in g.columns:
        log("  ! GISCO file has no emergency column")
        return None
    flag = g["emergency"].astype(str).str.strip().str.lower()
    known = flag.isin(YES | {"no", "n", "false", "0"}).mean()
    g = g[flag.isin(YES) & g.intersects(area)]
    name_col = next((c for c in ["hospital_name", "name", "site_name"] if c in g.columns), None)
    log(f"  GISCO {v}: emergency flag filled for {known:.0%} of {cc} records; {len(g)} emergency hospitals in the area")
    if not len(g):
        return None
    pts = g.geometry.representative_point()
    return pd.DataFrame({"name": g[name_col].fillna("Hospital").values if name_col else "Hospital",
                         "lat": pts.y.values, "lon": pts.x.values, "source": f"Eurostat GISCO healthcare {v}"})


def from_osm(area, paths):
    """Hospitals tagged emergency=yes in the OpenStreetMap extracts from step 2."""
    import pyogrio
    rows = []
    like = "other_tags LIKE '%\"emergency\"=>\"yes\"%'"
    for p in paths:
        pts = pyogrio.read_dataframe(p, layer="points", columns=["name", "other_tags"], bbox=area.bounds,
                                     where=f"other_tags LIKE '%\"amenity\"=>\"hospital\"%' AND {like}")
        polys = pyogrio.read_dataframe(p, layer="multipolygons", columns=["name", "amenity", "other_tags"], bbox=area.bounds,
                                       where=f"amenity = 'hospital' AND {like}")
        for g in (pts, polys):
            if not len(g):
                continue
            g = g[g.intersects(area)]
            c = g.to_crs(race.LAEA).geometry.representative_point().to_crs(race.WGS84)
            rows.append(pd.DataFrame({"name": g["name"].fillna("Hospital").values, "lat": c.y.values, "lon": c.x.values,
                                      "source": "OpenStreetMap (emergency=yes)"}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["name", "lat", "lon", "source"])


def main():
    ap = city_args(__doc__)
    ap.add_argument("--osm-file", action="append", help="the .osm.pbf file(s) used in step 2, if you gave your own")
    ap.add_argument("--clean", action="store_true", help="delete the OpenStreetMap downloads from step 2 at the end")
    args = ap.parse_args()
    from importlib import import_module
    net_mod = import_module("02_network")
    search_area = net_mod.search_area
    RESULTS.mkdir(exist_ok=True)
    for city in chosen(args):
        cfg = race.CITIES[city]
        log(f"== {cfg['name']} ==")
        area, _ = search_area(city)
        override = Path(os.environ.get("RACE_HOSPITALS") or CONFIG / "hospitals") / f"{city}.csv"
        if override.exists():
            h = pd.read_csv(override)
            h["source"] = h.get("source", f"config/hospitals/{city}.csv")
            log(f"  using {len(h)} sites from {override.name}")
        else:
            h = from_gisco(cfg["gisco"], area) if cfg["gisco"] else None
            if h is None:
                log("  using OpenStreetMap hospitals tagged emergency=yes")
                h = from_osm(area, net_mod.extract_paths(city, args.osm_file))
        if not len(h):
            raise SystemExit(f"!! No emergency hospitals found for {cfg['name']}. Add config/hospitals/{city}.csv.")
        h = h.iloc[race.dedupe_points(h["lon"].values, h["lat"].values, 300)].reset_index(drop=True)
        h.to_csv(city_dir(city) / "hospitals.csv", index=False)
        h.to_csv(RESULTS / f"hospitals_{city}.csv", index=False)
        log(f"  {len(h)} emergency departments (review results/hospitals_{city}.csv)")
    if args.clean and (RAW / "osm").exists():
        import shutil
        shutil.rmtree(RAW / "osm")
        log("Deleted the OpenStreetMap downloads.")
    log("\nNext: python scripts/04_drive_times.py")


if __name__ == "__main__":
    main()
