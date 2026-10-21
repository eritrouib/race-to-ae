"""
01_population.py
Race to A&E - Step 1: where people live, and where each city is.

Downloads the EU's Global Human Settlement Layer population grid (GHS-POP,
2025, 100 m), cuts out an 80 km box around each capital, and finds each city's
"urban centre" with the same rule everywhere (the UN/Eurostat Degree of
Urbanisation): contiguous 1 km² cells with at least 1,500 people each, and at
least 50,000 people in all. That makes London, Paris, Berlin, Madrid, Rome
and Athens comparable, whatever their administrative boundaries.

Usage (from the project folder):
    python scripts/01_population.py
    python scripts/01_population.py --cities london,athens
    python scripts/01_population.py --clean        # delete the big downloads afterwards

Downloads about 50-100 MB per GHSL tile (one or two per city); only small
cut-outs are kept in data/processed/<city>/.

Outputs (data/processed/<city>/):
    pop100.tif              population per 100 m cell (Mollweide)
    urban_centre.geojson    the study area (WGS84)
    area.json               population and area of the urban centre
"""

import shutil
import sys
import zipfile

import numpy as np
import shapely

import race
from common import RAW, Timer, chosen, city_args, city_dir, download, log, write_json

GHSL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
        "GHS_POP_E2025_GLOBE_R2023A_54009_100/V1-0/tiles/GHS_POP_E2025_GLOBE_R2023A_54009_100_V1_0_R{r}_C{c}.zip")


def tile_path(r, c):
    """Download a GHSL tile (cached). Returns a GDAL path into the zip, or None if the tile doesn't exist (sea)."""
    z = download(GHSL.format(r=r, c=c), RAW / "ghsl" / f"R{r}_C{c}.zip", quiet_404=True)
    if z is None:
        return None
    with zipfile.ZipFile(z) as zf:
        tif = next(n for n in zf.namelist() if n.lower().endswith(".tif"))
    return f"/vsizip/{z.as_posix()}/{tif}"


def read_window(window):
    import rasterio
    from rasterio.merge import merge
    paths = [p for p in (tile_path(r, c) for r, c in race.tiles_for_bbox(*window)) if p]
    if not paths:
        sys.exit("!! No GHSL tiles found for this area.")
    srcs = [rasterio.open(p) for p in paths]
    xmin, ymin, xmax, ymax = window
    inside = [s for s in srcs if s.bounds.left <= (xmin + xmax) / 2 <= s.bounds.right and s.bounds.bottom <= (ymin + ymax) / 2 <= s.bounds.top]
    if not inside:
        b = srcs[0].bounds
        sys.exit(f"!! The GHSL tile(s) downloaded don't cover the city (tile bounds {b}). "
                 "The tile numbering may have changed: check race.TILE_X0/TILE_Y0.")
    arr, transform = merge(srcs, bounds=window, res=100, nodata=0)
    for s in srcs:
        s.close()
    pop = arr[0].astype("float32")
    pop[pop < 0] = 0
    return pop, transform


def save_tif(path, pop, transform):
    import rasterio
    with rasterio.open(path, "w", driver="GTiff", width=pop.shape[1], height=pop.shape[0], count=1, dtype="float32",
                       crs=race.MOLLWEIDE, transform=transform, compress="deflate", predictor=3) as dst:
        dst.write(pop, 1)


def process(city, pop, window):
    cfg = race.CITIES[city]
    pop_km = race.to_km(pop)
    x, y = race.transformer(race.WGS84, race.MOLLWEIDE).transform(cfg["lon"], cfg["lat"])
    rc = (int((window[3] - y) // 1000), int((x - window[0]) // 1000))
    mask = race.urban_centre(pop_km, rc)
    poly = race.mask_polygon(mask, window[0], window[3], 1000)
    poly_wgs = race.reproject(poly, race.MOLLWEIDE, race.WGS84)
    return mask, poly_wgs, float(pop_km[mask].sum()), int(mask.sum())


def main():
    ap = city_args(__doc__)
    ap.add_argument("--clean", action="store_true", help="delete the downloaded GHSL tiles at the end")
    args = ap.parse_args()
    for city in chosen(args):
        t = Timer()
        cfg = race.CITIES[city]
        log(f"== {cfg['name']} ==")
        window = race.city_window(cfg["lat"], cfg["lon"], half_km=40)
        pop, transform = read_window(window)
        d = city_dir(city)
        save_tif(d / "pop100.tif", pop, transform)
        mask, poly, people, km2 = process(city, pop, window)
        (d / "urban_centre.geojson").write_text(
            '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":'
            + shapely.to_geojson(poly) + "}]}", encoding="utf-8")
        write_json(d / "area.json", {"city": city, "population": round(people), "area_km2": km2})
        log(f"  urban centre: {people / 1e6:.2f} million people on {km2:,} km² ({t})")
    if args.clean and (RAW / "ghsl").exists():
        shutil.rmtree(RAW / "ghsl")
        log("Deleted the GHSL downloads.")
    log("\nNext: python scripts/02_network.py")


if __name__ == "__main__":
    main()
