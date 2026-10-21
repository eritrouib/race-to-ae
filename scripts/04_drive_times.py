"""
04_drive_times.py
Race to A&E - Step 4: how long to the nearest emergency department?

One shortest-path run per city, on the reversed road network, gives the drive
time from every junction to its nearest A&E (one-way streets respected). Each
100 m populated cell in the urban centre takes the time from its nearest
junction, plus a short, slow trip to reach that road.

Usage (from the project folder, after step 3):
    python scripts/04_drive_times.py

Outputs (data/processed/<city>/):
    node_minutes.npz    minutes from every junction, and which hospital is nearest
    cells.parquet       lon, lat, people, minutes, nearest hospital, for every populated cell
    minutes.tif         minutes per 100 m cell (for maps)
    summary.json        shares of people within 10/15/20/30 minutes (free-flow and busy), median, 90th percentile
"""

import geopandas as gpd
import numpy as np
import pandas as pd

import race
from common import Timer, chosen, city_args, city_dir, log, need, read_json, write_json


def populated_cells(city):
    import rasterio
    from rasterio import features
    d = city_dir(city)
    uc = gpd.read_file(d / "urban_centre.geojson").geometry.iloc[0]
    uc_m = race.reproject(uc, race.WGS84, race.MOLLWEIDE)
    with rasterio.open(need(d / "pop100.tif", "01_population.py")) as src:
        pop = src.read(1)
        inside = features.geometry_mask([uc_m], out_shape=pop.shape, transform=src.transform, invert=True)
        rows, cols = np.nonzero(inside & (pop > 0))
        xs, ys = rasterio.transform.xy(src.transform, rows, cols, offset="center")
    lon, lat = race.transformer(race.MOLLWEIDE, race.WGS84).transform(np.asarray(xs), np.asarray(ys))
    return pd.DataFrame({"lon": lon, "lat": lat, "people": pop[rows, cols].astype(float), "row": rows, "col": cols})


def save_minutes_raster(city, cells):
    """Minutes per 100 m cell, on the same grid as pop100.tif (for maps)."""
    import rasterio
    d = city_dir(city)
    with rasterio.open(d / "pop100.tif") as src:
        prof = src.profile
        shape = (src.height, src.width)
    arr = np.full(shape, np.nan, dtype="float32")
    arr[cells["row"].to_numpy(), cells["col"].to_numpy()] = cells["minutes"].to_numpy()
    prof.update(dtype="float32", nodata=np.nan, compress="deflate", predictor=3)
    with rasterio.open(d / "minutes.tif", "w", **prof) as dst:
        dst.write(arr, 1)


def main():
    ap = city_args(__doc__)
    args = ap.parse_args()
    from importlib import import_module
    load_network = import_module("02_network").load_network
    for city in chosen(args):
        t = Timer()
        log(f"== {race.CITIES[city]['name']} ==")
        d = city_dir(city)
        net = load_network(need(d / "network.npz", "02_network.py"))
        hosp = pd.read_csv(need(d / "hospitals.csv", "03_hospitals.py"))
        h_node, h_snap = race.nearest_nodes(net, hosp["lon"].values, hosp["lat"].values)
        far = h_snap > 500
        if far.any():
            log(f"  ! {int(far.sum())} hospital(s) more than 500 m from a road in the network: "
                + ", ".join(hosp.loc[far, "name"].astype(str)))
        node_min, src = race.minutes_to_nearest(net, h_node)
        # which hospital (row of hospitals.csv) each junction's nearest A&E is
        node_to_h = {n: i for i, n in enumerate(h_node)}
        nearest_h = np.array([node_to_h.get(s, -1) for s in src])
        np.savez_compressed(d / "node_minutes.npz", minutes=node_min, hospital=nearest_h)

        cells = populated_cells(city)
        idx, snap = race.nearest_nodes(net, cells["lon"].values, cells["lat"].values)
        cells["minutes"] = race.cell_minutes(node_min, idx, snap)
        cells["hospital"] = nearest_h[idx]
        cells["snap_m"] = snap.round(0)
        cells.to_parquet(d / "cells.parquet", index=False)
        save_minutes_raster(city, cells)

        s = race.summary(cells["minutes"].to_numpy(), cells["people"].to_numpy())
        grid, cum = race.coverage(cells["minutes"].to_numpy(), cells["people"].to_numpy())
        s.update({
            "city": city, "name": race.CITIES[city]["name"], "hospitals": int(len(hosp)),
            "hospital_source": str(hosp["source"].iloc[0]) if "source" in hosp else "",
            "area_km2": read_json(d / "area.json")["area_km2"],
            "people_per_hospital": float(cells["people"].sum() / max(len(hosp), 1)),
            "curve_minutes": grid.tolist(), "curve_share": np.round(cum, 4).tolist(),
            "far_from_road_people": float(cells.loc[cells["snap_m"] > 500, "people"].sum()),
        })
        write_json(d / "summary.json", s)
        log(f"  {s['within_15']:.1%} of {s['population'] / 1e6:.2f} million people within 15 min of an A&E "
            f"(busy traffic: {s['within_15_busy']:.1%}); median {s['median_minutes']:.1f} min ({t})")
    log("\nNext: python scripts/05_summarise.py")


if __name__ == "__main__":
    main()
