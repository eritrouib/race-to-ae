"""
02_network.py
Race to A&E - Step 2: the road network.

Builds the network of roads a car can use within 8 km of each urban centre
from OpenStreetMap extracts downloaded from Geofabrik (no Overpass server
needed), keeps the part where every junction can reach every other one, and
gives each road a free-flow driving time from consistent typical speeds
(scripts/race.py, SPEEDS), lowered where a lower limit is posted.

Usage (from the project folder, after step 1):
    python scripts/02_network.py
    python scripts/02_network.py --cities london --osm-file ../london-pedestrian-safety/data/raw/osm/greater-london-latest.osm.pbf
    python scripts/02_network.py --overpass       # use the Overpass API via OSMnx instead (often overloaded)

Downloads (cached in data/raw/osm/): one or more Geofabrik extracts per city,
100-500 MB each. Reading a large extract takes a few minutes.

Outputs (data/processed/<city>/):
    network.npz     junctions (lon, lat), roads (from, to, minutes, metres) and road shapes
"""

import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np

import race
from common import RAW, Timer, chosen, city_args, city_dir, download, log, need

MARGIN_M = 8000  # roads beyond the urban centre, so journeys can leave it and hospitals just outside count
GEOFABRIK = "https://download.geofabrik.de/europe/"
# Extracts that together cover each urban centre plus 8 km.
EXTRACTS = {
    "london": ["united-kingdom/england/greater-london", "united-kingdom/england/surrey", "united-kingdom/england/kent",
               "united-kingdom/england/essex", "united-kingdom/england/hertfordshire",
               "united-kingdom/england/buckinghamshire", "united-kingdom/england/berkshire"],
    "paris": ["france/ile-de-france"],
    "berlin": ["germany/berlin", "germany/brandenburg"],
    "madrid": ["spain/madrid"],
    "rome": ["italy/centro"],
    "athens": ["greece"],
}
OVERPASS = ["https://overpass-api.de/api", "https://overpass.private.coffee/api", "https://maps.mail.ru/osm/tools/overpass/api"]


def search_area(city):
    uc = gpd.read_file(need(city_dir(city) / "urban_centre.geojson", "01_population.py")).geometry.iloc[0]
    area = race.reproject(race.reproject(uc, race.WGS84, race.LAEA).buffer(MARGIN_M), race.LAEA, race.WGS84)
    return area, uc


def extract_paths(city, osm_files=None):
    """Local .osm.pbf files for a city: given ones, or the Geofabrik extracts (downloaded once)."""
    if osm_files:
        return [Path(p) for p in osm_files]
    out = []
    for name in EXTRACTS[city]:
        url = GEOFABRIK + name + "-latest.osm.pbf"
        dest = RAW / "osm" / (name.split("/")[-1] + "-latest.osm.pbf")
        if not dest.exists():
            log(f"  downloading {dest.name} from Geofabrik ...")
        try:
            got = download(url, dest, quiet_404=True)
        except Exception as e:  # noqa: BLE001
            got = None
            log(f"  ! couldn't download {url}: {e}")
        if got is None:
            log(f"  ! {url} wasn't found. Check the name on https://download.geofabrik.de and fix EXTRACTS in this script; "
                "carrying on without it, so roads near the edge may be missing.")
            continue
        out.append(got)
    if not out:
        sys.exit("!! No OpenStreetMap extract could be downloaded for this city.")
    return out


def read_roads(paths, area):
    """Drivable ways from .osm.pbf files, inside the search area."""
    import pyogrio
    bbox = area.bounds
    where = "highway IN (" + ",".join(f"'{h}'" for h in race.DRIVABLE) + ")"
    coords, highway, maxspeed, oneway = [], [], [], []
    seen = set()
    for p in paths:
        t = Timer()
        log(f"  reading roads from {p.name} (a few minutes for a big file) ...")
        g = pyogrio.read_dataframe(p, layer="lines", columns=["osm_id", "highway", "other_tags"], where=where, bbox=bbox)
        g = g[g.intersects(area)]
        n0 = len(coords)
        for oid, hw, other, geom in zip(g["osm_id"], g["highway"], g["other_tags"], g.geometry):
            if oid in seen or geom is None:
                continue                     # the same way in two overlapping extracts
            tags = race.osm_tags(other)
            if not race.can_drive(hw, tags):
                continue
            seen.add(oid)
            for part in getattr(geom, "geoms", [geom]):
                coords.append(np.asarray(part.coords)[:, :2])
                highway.append(hw)
                maxspeed.append(tags.get("maxspeed"))
                oneway.append(race.oneway_of(hw, tags))
        log(f"    {len(coords) - n0:,} roads ({t})")
    if not coords:
        sys.exit("!! No roads found. Is this the right OpenStreetMap file for the city?")
    return coords, highway, maxspeed, oneway


def from_overpass(city, area):
    import osmnx as ox
    ox.settings.cache_folder = str(RAW / "osm" / "cache")
    ox.settings.requests_timeout = 600
    ox.settings.useful_tags_way = list(set(ox.settings.useful_tags_way + ["maxspeed"]))
    path = RAW / "osm" / f"{city}_drive.graphml"
    if path.exists():
        return race.network_arrays(ox.load_graphml(path))
    for attempt in range(6):
        ox.settings.overpass_url = OVERPASS[attempt % len(OVERPASS)]
        try:
            log(f"  asking {ox.settings.overpass_url} ...")
            G = ox.graph_from_polygon(area, network_type="drive", simplify=True, retain_all=False)
            path.parent.mkdir(parents=True, exist_ok=True)
            ox.save_graphml(G, path)
            return race.network_arrays(G)
        except Exception as e:  # noqa: BLE001
            wait = 30 * 2 ** attempt
            log(f"  ! {str(e).splitlines()[0][:120]}; trying again in {wait}s")
            time.sleep(wait)
    sys.exit("!! The Overpass servers are busy. Run without --overpass to use the Geofabrik files instead.")


def save_network(path, net):
    lens = np.array([len(c) for c in net["coords"]])
    np.savez_compressed(path, lon=net["lon"], lat=net["lat"], u=net["u"], v=net["v"], minutes=net["minutes"],
                        length=net["length"], coords=np.vstack(net["coords"]), coord_len=lens)


def load_network(path):
    z = np.load(path)
    splits = np.cumsum(z["coord_len"])[:-1]
    return {"lon": z["lon"], "lat": z["lat"], "u": z["u"], "v": z["v"], "minutes": z["minutes"],
            "length": z["length"], "coords": np.split(z["coords"], splits)}


def main():
    ap = city_args(__doc__)
    ap.add_argument("--osm-file", action="append", help="use this .osm.pbf instead of downloading (repeat for several)")
    ap.add_argument("--overpass", action="store_true", help="download through the Overpass API (OSMnx) instead")
    args = ap.parse_args()
    for city in chosen(args):
        t = Timer()
        log(f"== {race.CITIES[city]['name']} ==")
        area, _ = search_area(city)
        if args.overpass:
            net = from_overpass(city, area)
        else:
            net = race.network_from_lines(*read_roads(extract_paths(city, args.osm_file), area))
        net = race.largest_strong_component(net)
        save_network(city_dir(city) / "network.npz", net)
        log(f"  {len(net['lon']):,} junctions, {len(net['u']):,} one-way road links, "
            f"{net['length'].sum() / 2000:,.0f} km of road ({t})")
    log("\nNext: python scripts/03_hospitals.py")


if __name__ == "__main__":
    main()
