"""
race.py
Race to A&E: the analysis core. Pure functions (no downloads, no file paths)
so every step can be tested on a made-up city with known answers (tests/).

Coordinates: lon/lat (EPSG:4326) for maps, ETRS89 LAEA (EPSG:3035, metres,
equal-area for Europe) for distances, and Mollweide (ESRI:54009) for the GHSL
population grid.
"""

import math
import re

import numpy as np
import shapely
from pyproj import Transformer
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

LAEA = "EPSG:3035"
MOLLWEIDE = "ESRI:54009"
WGS84 = "EPSG:4326"

CITIES = {
    "london": {"name": "London", "country": "United Kingdom", "gisco": None, "lat": 51.5074, "lon": -0.1278},
    "paris": {"name": "Paris", "country": "France", "gisco": "FR", "lat": 48.8566, "lon": 2.3522},
    "berlin": {"name": "Berlin", "country": "Germany", "gisco": "DE", "lat": 52.5200, "lon": 13.4050},
    "madrid": {"name": "Madrid", "country": "Spain", "gisco": "ES", "lat": 40.4168, "lon": -3.7038},
    "rome": {"name": "Rome", "country": "Italy", "gisco": "IT", "lat": 41.9028, "lon": 12.4964},
    "athens": {"name": "Athens", "country": "Greece", "gisco": "EL", "lat": 37.9838, "lon": 23.7275},
}

# Typical free-flow urban driving speeds (km/h) by road class, the same in every
# city so that differences come from the network and the hospitals, not from how
# each country tags speed limits. A lower posted limit (a 20 mph or 30 km/h zone)
# still applies.
SPEEDS = {
    "motorway": 80, "motorway_link": 50, "trunk": 55, "trunk_link": 40, "primary": 40, "primary_link": 30,
    "secondary": 35, "secondary_link": 28, "tertiary": 30, "tertiary_link": 25, "unclassified": 25,
    "residential": 22, "living_street": 10, "road": 22, "service": 15,
}
DEFAULT_SPEED = 22
BUSY_FACTOR = 1.5          # "busy traffic": every journey takes 50% longer
ACCESS_KMH = 15            # from a home to the nearest drivable road (short, slow)
MINUTES = [10, 15, 20, 30]

# Degree of Urbanisation (Eurostat/UN): an urban centre is a cluster of
# contiguous 1 km² cells with at least 1,500 people per km² and 50,000 people.
URBAN_DENSITY = 1500
URBAN_MIN_POP = 50000

# GHSL tiles: 1,000 km Mollweide tiles; R1 C1 is the top-left of the world.
TILE_X0, TILE_Y0, TILE_SIZE = -18041000, 9000000, 1000000


def transformer(a, b):
    return Transformer.from_crs(a, b, always_xy=True)


def reproject(geom, src, dst):
    """A shapely geometry from one CRS to another."""
    t = transformer(src, dst)
    return shapely.transform(geom, lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1])))


# --------------------------------------------------------------------------
# POPULATION AND URBAN CENTRES
# --------------------------------------------------------------------------
def ghsl_tile(x, y):
    """(row, col) of the GHSL Mollweide tile containing (x, y)."""
    return int((TILE_Y0 - y) // TILE_SIZE) + 1, int((x - TILE_X0) // TILE_SIZE) + 1


def tiles_for_bbox(xmin, ymin, xmax, ymax):
    r0, c0 = ghsl_tile(xmin, ymax)
    r1, c1 = ghsl_tile(xmax, ymin)
    return [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]


def city_window(lat, lon, half_km=40):
    """A Mollweide box (aligned to whole km) around the city centre."""
    x, y = transformer(WGS84, MOLLWEIDE).transform(lon, lat)
    h = half_km * 1000
    return (math.floor((x - h) / 1000) * 1000, math.floor((y - h) / 1000) * 1000,
            math.ceil((x + h) / 1000) * 1000, math.ceil((y + h) / 1000) * 1000)


def to_km(pop100):
    """Sum a 100 m grid (rows/cols multiples of 10) into 1 km cells."""
    h, w = pop100.shape
    p = np.nan_to_num(pop100[: h - h % 10, : w - w % 10], nan=0.0)
    p[p < 0] = 0
    return p.reshape(h // 10, 10, w // 10, 10).sum(axis=(1, 3))


def urban_centre(pop_km, centre_rc):
    """
    The urban centre containing (or nearest to) the city centre, following the
    Degree of Urbanisation rules: dense 1 km cells (>= 1,500 people), joined
    edge to edge, at least 50,000 people; then gaps are filled and cells with
    most of their neighbours in the centre are added (majority rule).
    Returns a boolean 1 km mask.
    """
    dense = pop_km >= URBAN_DENSITY
    labels, n = ndimage.label(dense, structure=[[0, 1, 0], [1, 1, 1], [0, 1, 0]])
    if not n:
        raise ValueError("No dense cells: is the population grid in the right place?")
    sums = ndimage.sum(pop_km, labels, index=np.arange(1, n + 1))
    big = {i + 1 for i, s in enumerate(sums) if s >= URBAN_MIN_POP}
    r, c = centre_rc
    lab = labels[r, c]
    if lab not in big:   # centre not dense (a park, a river): take the nearest big cluster
        rr, cc = np.nonzero(np.isin(labels, list(big)))
        if not len(rr):
            raise ValueError("No urban centre of 50,000 people found near the city centre.")
        k = np.argmin((rr - r) ** 2 + (cc - c) ** 2)
        lab = labels[rr[k], cc[k]]
    mask = labels == lab
    for _ in range(20):  # majority rule: >= 5 of 8 neighbours in the centre
        neigh = ndimage.convolve(mask.astype(int), np.ones((3, 3), int), mode="constant") - mask
        grown = mask | (neigh >= 5)
        grown = ndimage.binary_fill_holes(grown)
        if (grown == mask).all():
            break
        mask = grown
    return mask


def mask_polygon(mask, x0, y_top, cell):
    """Polygon (Mollweide) of a boolean grid whose top-left corner is (x0, y_top)."""
    from rasterio import features
    from rasterio.transform import from_origin
    shapes = features.shapes(mask.astype("uint8"), mask=mask, transform=from_origin(x0, y_top, cell, cell))
    return shapely.union_all([shapely.geometry.shape(g) for g, v in shapes if v == 1])


# --------------------------------------------------------------------------
# ROAD NETWORK
# --------------------------------------------------------------------------
_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(mph)?", re.I)
ZONE_SPEEDS = {"zone30": 30, "zone:30": 30, "walk": 7, "living_street": 10}


def parse_maxspeed(value):
    """km/h from an OSM maxspeed value ('30', '20 mph', ['50', '30'], 'FR:zone30'); None if unknown."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (list, tuple)):
        found = [parse_maxspeed(v) for v in value]
        found = [f for f in found if f]
        return min(found) if found else None
    s = str(value).lower()
    for k, v in ZONE_SPEEDS.items():
        if k in s:
            return v
    m = _NUM.search(s)
    if not m:
        return None
    v = float(m.group(1))
    return v * 1.609344 if m.group(2) else v


def as_list(value):
    """OSMnx keeps lists as text ("['primary', 'secondary']") after a save and reload."""
    if isinstance(value, str) and value.startswith("["):
        import ast
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    return value


def edge_speed(highway, maxspeed=None):
    """Free-flow km/h for a road: the typical speed for its class, or a lower posted limit."""
    highway, maxspeed = as_list(highway), as_list(maxspeed)
    hw = highway[0] if isinstance(highway, (list, tuple)) and highway else highway
    base = SPEEDS.get(str(hw), DEFAULT_SPEED)
    limit = parse_maxspeed(maxspeed)
    return min(base, limit) if limit else base


def network_arrays(G):
    """
    Arrays from an OSMnx graph (or any networkx MultiDiGraph with x/y node
    attributes and length/highway edge attributes).
    Returns dict: node_ids, lon, lat, u, v, minutes, length, coords (list of (n, 2) lon/lat arrays).
    """
    node_ids = np.array(list(G.nodes), dtype=np.int64)
    index = {n: i for i, n in enumerate(node_ids)}
    lon = np.array([G.nodes[n]["x"] for n in node_ids], dtype=float)
    lat = np.array([G.nodes[n]["y"] for n in node_ids], dtype=float)
    u, v, minutes, length, coords = [], [], [], [], []
    for a, b, d in G.edges(data=True):
        L = float(d.get("length", 0.0))
        kmh = edge_speed(d.get("highway"), d.get("maxspeed"))
        u.append(index[a])
        v.append(index[b])
        length.append(L)
        minutes.append(L / (kmh / 3.6) / 60)
        g = d.get("geometry")
        coords.append(np.asarray(g.coords) if g is not None else np.array([[lon[index[a]], lat[index[a]]], [lon[index[b]], lat[index[b]]]]))
    return {"node_ids": node_ids, "lon": lon, "lat": lat, "u": np.array(u), "v": np.array(v),
            "minutes": np.array(minutes), "length": np.array(length), "coords": coords}


DRIVABLE = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
            "tertiary", "tertiary_link", "unclassified", "residential", "living_street", "road"]
_TAG = re.compile(r'"([^"]+)"=>"([^"]*)"')


def osm_tags(other_tags):
    return dict(_TAG.findall(other_tags)) if isinstance(other_tags, str) else {}


def can_drive(highway, tags):
    if highway not in DRIVABLE or tags.get("area") == "yes":
        return False
    motor = tags.get("motor_vehicle", tags.get("motorcar", tags.get("vehicle")))
    if motor in ("no", "private", "agricultural", "forestry", "delivery", "destination_no"):
        return False
    if tags.get("access") in ("no", "private") and motor not in ("yes", "permissive", "designated", "destination"):
        return False
    return True


def oneway_of(highway, tags):
    """+1 one-way in the drawn direction, -1 against it, 0 two-way."""
    v = tags.get("oneway", "")
    if v in ("yes", "true", "1"):
        return 1
    if v in ("-1", "reverse"):
        return -1
    if v == "no":
        return 0
    if highway in ("motorway", "motorway_link") or tags.get("junction") in ("roundabout", "circular"):
        return 1
    return 0


def network_from_lines(coords_list, highway, maxspeed, oneway):
    """
    Build the network arrays (as network_arrays does for OSMnx) straight from
    OpenStreetMap ways: lists of lon/lat coordinates. Ways join where they share
    a node, so bridges and tunnels don't create false junctions. Each way is cut
    at every junction; two-way roads get an edge in each direction.
    """
    lens = np.array([len(c) for c in coords_list])
    xy = np.vstack(coords_list)
    line = np.repeat(np.arange(len(coords_list)), lens)
    key = np.round(xy * 1e7).astype(np.int64)
    _, vid = np.unique(key[:, 0] * 4_000_000_000 + key[:, 1], return_inverse=True)
    first = np.r_[True, line[1:] != line[:-1]]
    last = np.r_[line[1:] != line[:-1], True]
    is_node = first | last | (np.bincount(vid)[vid] > 1)
    to_m = transformer(WGS84, LAEA)
    mx, my = to_m.transform(xy[:, 0], xy[:, 1])
    seg = np.flatnonzero(~last)
    seg_len = np.hypot(mx[seg + 1] - mx[seg], my[seg + 1] - my[seg])
    piece = (np.cumsum(is_node) - 1)[seg]
    _, piece = np.unique(piece, return_inverse=True)
    starts = np.r_[0, np.flatnonzero(np.diff(piece)) + 1]
    ends = np.r_[starts[1:], len(seg)]
    plen = np.bincount(piece, weights=seg_len)
    a_pos, b_pos = seg[starts], seg[ends - 1] + 1
    nodes, inv = np.unique(np.r_[vid[a_pos], vid[b_pos]], return_inverse=True)
    pu, pv = inv[: len(a_pos)], inv[len(a_pos):]
    first_pos = np.zeros(vid.max() + 1, dtype=np.int64)
    first_pos[vid[::-1]] = np.arange(len(vid))[::-1]
    lon, lat = xy[first_pos[nodes], 0], xy[first_pos[nodes], 1]
    pline = line[a_pos]
    u, v, minutes, length, coords = [], [], [], [], []
    for k in range(len(a_pos)):
        if pu[k] == pv[k] or plen[k] <= 0:
            continue
        i = pline[k]
        c = xy[a_pos[k]:b_pos[k] + 1]
        kmh = edge_speed(highway[i], maxspeed[i])
        mins = plen[k] / (kmh / 3.6) / 60
        ow = oneway[i]
        if ow >= 0:
            u.append(pu[k]); v.append(pv[k]); minutes.append(mins); length.append(plen[k]); coords.append(c)
        if ow <= 0:
            u.append(pv[k]); v.append(pu[k]); minutes.append(mins); length.append(plen[k]); coords.append(c[::-1])
    return {"lon": lon, "lat": lat, "u": np.array(u, dtype=np.int64), "v": np.array(v, dtype=np.int64),
            "minutes": np.array(minutes), "length": np.array(length), "coords": coords}


def largest_strong_component(net):
    """Keep only junctions that can all reach each other (drops dead-end fragments and one-way traps)."""
    from scipy.sparse.csgraph import connected_components
    n = len(net["lon"])
    m = coo_matrix((np.ones(len(net["u"])), (net["u"], net["v"])), shape=(n, n)).tocsr()
    _, labels = connected_components(m, directed=True, connection="strong")
    keep = labels == np.bincount(labels).argmax()
    new = -np.ones(n, dtype=np.int64)
    new[keep] = np.arange(keep.sum())
    e = keep[net["u"]] & keep[net["v"]]
    return {"lon": net["lon"][keep], "lat": net["lat"][keep], "u": new[net["u"][e]], "v": new[net["v"][e]],
            "minutes": net["minutes"][e], "length": net["length"][e], "coords": [c for c, k in zip(net["coords"], e) if k]}


def minutes_to_nearest(net, sources):
    """
    Drive time (minutes) from every junction TO the nearest of `sources`
    (junction indices), respecting one-way streets, and which source it is.
    Done in one Dijkstra run on the reversed network.
    """
    n = len(net["lon"])
    w = np.maximum(net["minutes"], 1e-6)
    # reversed: an edge a->b becomes b->a; keep the quickest of parallel edges
    rows, cols = net["v"], net["u"]
    order = np.lexsort((w, cols, rows))
    rows, cols, w = rows[order], cols[order], w[order]
    keep = np.r_[True, (rows[1:] != rows[:-1]) | (cols[1:] != cols[:-1])]
    m = coo_matrix((w[keep], (rows[keep], cols[keep])), shape=(n, n)).tocsr()
    sources = np.unique(np.asarray(sources, dtype=int))
    dist, _, src = dijkstra(m, directed=True, indices=sources, min_only=True, return_predecessors=True)
    return dist, src


def nearest_nodes(net, lon, lat, to_m=None):
    """Nearest junction to each point and the straight-line distance (m)."""
    to_m = to_m or transformer(WGS84, LAEA)
    nx_, ny_ = to_m.transform(net["lon"], net["lat"])
    px, py = to_m.transform(np.asarray(lon), np.asarray(lat))
    d, i = cKDTree(np.column_stack([nx_, ny_])).query(np.column_stack([px, py]))
    return i, d


def cell_minutes(node_minutes, node_index, snap_m, busy=False):
    """Minutes from a home (population cell) to the nearest A&E: the short trip to the road plus the drive."""
    t = node_minutes[node_index] + snap_m / (ACCESS_KMH / 3.6) / 60
    return t * (BUSY_FACTOR if busy else 1)


# --------------------------------------------------------------------------
# COVERAGE
# --------------------------------------------------------------------------
def coverage(minutes, pop, grid=np.arange(0, 60.5, 0.5)):
    """Share of people within each number of minutes (cumulative curve)."""
    ok = np.isfinite(minutes)
    total = pop.sum()
    m, p = minutes[ok], pop[ok]
    order = np.argsort(m)
    cum = np.cumsum(p[order])
    idx = np.searchsorted(m[order], grid, side="right")
    return grid, np.where(idx > 0, cum[np.maximum(idx - 1, 0)], 0) / total if total else grid * np.nan


def weighted_quantile(values, weights, q):
    ok = np.isfinite(values)
    v, w = values[ok], weights[ok]
    o = np.argsort(v)
    c = np.cumsum(w[o])
    return float(v[o][np.searchsorted(c, q * c[-1])]) if len(v) else float("nan")


def summary(minutes, pop):
    out = {"population": float(pop.sum())}
    for m in MINUTES:
        out[f"within_{m}"] = float(pop[minutes <= m].sum() / pop.sum())
        out[f"within_{m}_busy"] = float(pop[minutes * BUSY_FACTOR <= m].sum() / pop.sum())
    out["median_minutes"] = weighted_quantile(minutes, pop, 0.5)
    out["p90_minutes"] = weighted_quantile(minutes, pop, 0.9)
    out["unreachable"] = float(pop[~np.isfinite(minutes)].sum())
    return out


def dedupe_points(lon, lat, metres=300):
    """Indices to keep so no two points are closer than `metres` (first one wins)."""
    x, y = transformer(WGS84, LAEA).transform(np.asarray(lon), np.asarray(lat))
    tree = cKDTree(np.column_stack([x, y]))
    keep, dropped = [], set()
    for i in range(len(x)):
        if i in dropped:
            continue
        keep.append(i)
        dropped.update(tree.query_ball_point([x[i], y[i]], metres))
    return np.array(keep, dtype=int)


# --------------------------------------------------------------------------
# DRAWING THE SPREAD
# --------------------------------------------------------------------------
def edge_times(net, node_minutes):
    """
    For drawing: each road gets the time the 'front' reaches each end, oriented
    from the end reached first. Returns (t0, t1, flip) arrays; inf if unreached.
    """
    a, b = node_minutes[net["u"]], node_minutes[net["v"]]
    flip = b < a
    t0 = np.minimum(a, b)
    t1 = np.minimum(np.maximum(a, b), t0 + net["minutes"])
    return t0, t1, flip


BANDS = [5, 10, 15, 20, 30]
BAND_COLORS = ["#fcfdbf", "#fec287", "#fb8761", "#e65164", "#c03a76", "#8c2981"]  # validated on dark map


def band_of(t):
    for i, b in enumerate(BANDS):
        if t < b:
            return i
    return len(BANDS)
