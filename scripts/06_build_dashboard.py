"""
06_build_dashboard.py
Race to A&E - Step 6: the animated dashboard.

Writes docs/: one page plus a data file per city, loaded as scripts so the
page also works when opened straight from disk. Every road in each urban
centre (and 2 km around it) is stored with the time the "front" reaches each
end, so the page can replay the spread from every A&E at once.

Usage (from the project folder, after step 5):
    python scripts/06_build_dashboard.py
    python scripts/06_build_dashboard.py --repo https://github.com/eritrouib/race-to-ae

Outputs (docs/):
    index.html           copied from scripts/dashboard_template.html
    data/meta.js         cities, summaries and coverage curves
    data/<city>.js       roads (with times), hospitals and the urban centre outline
"""

import json
import shutil
import subprocess
from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

import race
from common import CODE, DOCS, OUT, ROOT, Timer, city_args, chosen, log, need, read_json

SHOW_MARGIN_M = 2000
MAX_MIN = 40


def write_js(path, key, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    path.write_text(f"window.RACE=window.RACE||{{}};RACE[{json.dumps(key)}]={payload};", encoding="utf-8")
    return path.stat().st_size


def encode_edges(net, node_min, area):
    """[t0*10, t1*10, lon0*1e5, lat0*1e5, dlon, dlat, ...] per road, each two-way street once."""
    t0, t1, flip = race.edge_times(net, node_min)
    a, b = np.minimum(net["u"], net["v"]), np.maximum(net["u"], net["v"])
    order = np.lexsort((t0, b, a))
    first = np.r_[True, (a[order][1:] != a[order][:-1]) | (b[order][1:] != b[order][:-1])]
    pick = order[first]
    minx, miny, maxx, maxy = area.bounds
    out = []
    for i in pick:
        if not np.isfinite(t0[i]) or t0[i] > MAX_MIN:
            continue
        c = net["coords"][i]
        if flip[i]:
            c = c[::-1]
        if not (minx <= c[0, 0] <= maxx and miny <= c[0, 1] <= maxy):
            continue
        q = np.round(c * 1e5).astype(np.int64)
        flat = [int(q[0, 0]), int(q[0, 1])]
        d = np.diff(q, axis=0)
        flat += d.ravel().tolist()
        out.append([int(round(t0[i] * 10)), int(round(min(t1[i], MAX_MIN + 10) * 10))] + flat)
    return out


def git_remote():
    try:
        url = subprocess.run(["git", "config", "--get", "remote.origin.url"], cwd=ROOT, capture_output=True,
                             text=True, timeout=5).stdout.strip()
        return url[:-4] if url.endswith(".git") else url or None
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = city_args(__doc__)
    ap.add_argument("--repo", help="link to the GitHub repository, shown on the page")
    args = ap.parse_args()
    from importlib import import_module
    load_network = import_module("02_network").load_network
    data = DOCS / "data"
    meta_cities = []
    for city in chosen(args):
        d = OUT / city
        if not (d / "summary.json").exists():
            log(f"  skipping {city}: no results (run steps 1-4)")
            continue
        t = Timer()
        net = load_network(d / "network.npz")
        node_min = np.load(d / "node_minutes.npz")["minutes"]
        uc = gpd.read_file(d / "urban_centre.geojson").geometry.iloc[0]
        area = race.reproject(race.reproject(uc, race.WGS84, race.LAEA).buffer(SHOW_MARGIN_M), race.LAEA, race.WGS84)
        edges = encode_edges(net, node_min, area)
        hosp = pd.read_csv(d / "hospitals.csv")
        outline = [np.round(np.asarray(r.coords), 5).tolist() for g in shapely.get_parts(uc) for r in [g.exterior]]
        s = read_json(d / "summary.json")
        cfg = race.CITIES[city]
        size = write_js(data / f"{city}.js", city, {
            "edges": edges, "outline": outline,
            "hospitals": [[round(a, 5), round(b, 5), str(n)] for a, b, n in zip(hosp["lon"], hosp["lat"], hosp["name"])],
        })
        meta_cities.append({"key": city, "name": cfg["name"], "country": cfg["country"], "lon": cfg["lon"], "lat": cfg["lat"],
                            "bounds": [round(x, 4) for x in uc.bounds], "summary": {k: v for k, v in s.items() if not k.startswith("curve")},
                            "curve": [s["curve_minutes"][:61], s["curve_share"][:61]]})
        log(f"  {cfg['name']}: {len(edges):,} roads, data/{city}.js {size / 1e6:.1f} MB ({t})")
    if not meta_cities:
        raise SystemExit("Nothing to build: run steps 1-5 first.")
    write_js(data / "meta.js", "meta", {
        "built": date.today().isoformat(), "cities": meta_cities, "bands": race.BANDS, "colors": race.BAND_COLORS,
        "busy": race.BUSY_FACTOR, "repo": args.repo or git_remote() or "https://github.com/eritrouib/race-to-ae",
    })
    shutil.copy2(CODE / "scripts" / "dashboard_template.html", DOCS / "index.html")
    (DOCS / ".nojekyll").touch()
    log("\nDone. Open docs/index.html, or push and switch on GitHub Pages (main branch, /docs).")


if __name__ == "__main__":
    main()
