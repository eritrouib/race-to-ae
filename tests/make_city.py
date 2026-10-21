"""
make_city.py
A made-up city for testing: a dense square of people (so the urban centre can
be worked out by hand), a 500 m street grid with one fast avenue, a one-way
street and a 20 mph zone, and two emergency departments.

Writes the files steps 1-3 would produce, so steps 4-8 run unchanged:
    data/processed/<city>/pop100.tif, urban_centre.geojson, area.json, network.npz, hospitals.csv
"""

import importlib
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import race  # noqa: E402

STEP = 500        # metres between junctions
N = 41            # 41 x 41 junctions = a 20 km square
DENSE = 30        # people per 100 m cell (3,000 per km²) in the 20 x 20 km centre


def grid_graph(city):
    cfg = race.CITIES[city]
    to_m = race.transformer(race.WGS84, race.LAEA)
    to_w = race.transformer(race.LAEA, race.WGS84)
    cx, cy = to_m.transform(cfg["lon"], cfg["lat"])
    G = nx.MultiDiGraph()
    half = (N - 1) * STEP / 2
    for i in range(N):
        for j in range(N):
            lon, lat = to_w.transform(cx - half + j * STEP, cy + half - i * STEP)
            G.add_node(i * N + j, x=lon, y=lat)
    for i in range(N):
        for j in range(N):
            a = i * N + j
            for b, horiz in ((a + 1, True), (a + N, False)):
                if (horiz and j == N - 1) or (not horiz and i == N - 1):
                    continue
                hw = "primary" if (not horiz and j == N // 2) else "residential"     # a north-south avenue through the middle
                attrs = {"length": float(STEP), "highway": hw}
                if horiz and i == 5:
                    attrs["maxspeed"] = "20 mph"                                    # a 20 mph street
                if horiz and i == 0:
                    G.add_edge(a, b, **attrs)                                       # the top row is one-way, west to east
                    continue
                G.add_edge(a, b, **attrs)
                G.add_edge(b, a, **attrs)
    return G, (cx, cy)


def make(root, city="athens"):
    root = Path(root)
    import os
    os.environ["RACE_ROOT"] = str(root)
    for m in ["common", "01_population", "02_network"]:
        if m in sys.modules:
            del sys.modules[m]
    pop_mod = importlib.import_module("01_population")
    net_mod = importlib.import_module("02_network")
    from common import city_dir, write_json
    import rasterio
    from rasterio.transform import from_origin
    cfg = race.CITIES[city]
    window = race.city_window(cfg["lat"], cfg["lon"], 40)
    w, h = (window[2] - window[0]) // 100, (window[3] - window[1]) // 100
    pop = np.zeros((h, w), dtype="float32")
    cx, cy = race.transformer(race.WGS84, race.MOLLWEIDE).transform(cfg["lon"], cfg["lat"])
    r0, c0 = int((window[3] - cy) // 100), int((cx - window[0]) // 100)
    pop[r0 - 100:r0 + 100, c0 - 100:c0 + 100] = DENSE        # 20 x 20 km dense square
    pop[r0 + 150:r0 + 160, c0 + 150:c0 + 160] = DENSE        # a small dense village: not part of the centre
    transform = from_origin(window[0], window[3], 100, 100)
    d = city_dir(city)
    pop_mod.save_tif(d / "pop100.tif", pop, transform)
    mask, poly, people, km2 = pop_mod.process(city, pop, window)
    import shapely
    (d / "urban_centre.geojson").write_text('{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":'
                                             + shapely.to_geojson(poly) + "}]}", encoding="utf-8")
    write_json(d / "area.json", {"city": city, "population": round(people), "area_km2": km2})
    G, _ = grid_graph(city)
    net_mod.save_network(d / "network.npz", race.network_arrays(G))
    centre, corner = (N // 2) * N + N // 2, (N - 1) * N + (N - 1)
    pd.DataFrame({"name": ["Central Hospital", "Corner Hospital"],
                  "lat": [G.nodes[centre]["y"], G.nodes[corner]["y"]], "lon": [G.nodes[centre]["x"], G.nodes[corner]["x"]],
                  "source": "test"}).to_csv(d / "hospitals.csv", index=False)
    return {"people": people, "km2": km2, "centre_node": centre, "corner_node": corner}


if __name__ == "__main__":
    print(make(sys.argv[1] if len(sys.argv) > 1 else "/tmp/race-city"))


def write_osm(path, city="london"):
    """The same grid as an OpenStreetMap XML file, with hospitals, a private road and a bridge with no junctions."""
    from xml.sax.saxutils import quoteattr
    G, _ = grid_graph(city)
    nodes = {n: (d["y"], d["x"]) for n, d in G.nodes(data=True)}
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="make_city">']
    for n, (lat, lon) in nodes.items():
        out.append(f'<node id="{n + 1}" version="1" lat="{lat:.7f}" lon="{lon:.7f}"/>')
    nid = len(nodes) + 10
    ways = []
    for i in range(N):
        tags = {"highway": "residential", "name": f"Row {i}"}
        if i == 0:
            tags["oneway"] = "yes"
        if i == 5:
            tags["maxspeed"] = "20 mph"
        ways.append(([i * N + j + 1 for j in range(N)], tags))
    for j in range(N):
        ways.append(([i * N + j + 1 for i in range(N)], {"highway": "primary" if j == N // 2 else "residential"}))
    # a private road straight across a block and a bridge with no junctions: neither may become a shortcut
    c = (N // 2) * N + N // 2
    extra = []
    for a, b, tags in [(c + 1, c + N + 2, {"highway": "residential", "access": "private"}),
                       (c - 3 * N - 3, c + 3 * N + 3, {"highway": "motorway", "bridge": "yes", "layer": "1"})]:
        (la, lo), (lb, lob) = nodes[a], nodes[b]
        ids = []
        for t in (0.13, 0.87):   # end points that are not shared with the grid
            nid += 1
            extra.append(f'<node id="{nid}" version="1" lat="{la + (lb - la) * t:.7f}" lon="{lo + (lob - lo) * t:.7f}"/>')
            ids.append(nid)
        ways.append((ids, tags))
    for h, name in [(c, "Central Hospital"), ((N - 1) * N + N - 1, "Corner Hospital")]:
        nid += 1
        lat, lon = nodes[h]
        extra.append(f'<node id="{nid}" version="1" lat="{lat + 0.0006:.7f}" lon="{lon:.7f}"><tag k="amenity" v="hospital"/>'
                     f'<tag k="emergency" v="yes"/><tag k="name" v={quoteattr(name)}/></node>')
    nid += 1
    lat, lon = nodes[N * 3 + 3]
    extra.append(f'<node id="{nid}" version="1" lat="{lat:.7f}" lon="{lon:.7f}"><tag k="amenity" v="hospital"/>'
                 '<tag k="emergency" v="no"/><tag k="name" v="No A&amp;E Clinic"/></node>')
    out += extra
    for k, (refs, tags) in enumerate(ways, start=1):
        out.append(f'<way id="{k}" version="1">' + "".join(f'<nd ref="{r}"/>' for r in refs)
                   + "".join(f"<tag k={quoteattr(a)} v={quoteattr(b)}/>" for a, b in tags.items()) + "</way>")
    out.append("</osm>")
    Path(path).write_text("\n".join(out), encoding="utf-8")
    return path
