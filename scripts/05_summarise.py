"""
05_summarise.py
Race to A&E - Step 5: comparing the capitals.

Usage (from the project folder, after step 4):
    python scripts/05_summarise.py

Outputs:
    results/summary.csv              one row per city
    results/headline.json            the numbers used in the write-up and on the dashboard
    figures/coverage_curves.png      share of people within each number of minutes, all cities
    figures/within_15.png            within 15 minutes, free-flow and busy traffic
    figures/six_capitals.png         maps of drive time, all at the same scale
    figures/map_<city>.png           one map per city
"""

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402

import race  # noqa: E402
from common import CONFIG, FIGURES, OUT, RESULTS, log, read_json, write_json  # noqa: E402

INK, MUTED, LINE = "#22272B", "#5D676E", "#CDD2D5"
# categorical slots (validated palette order); identity also carried by direct labels
CITY_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
DARK = "#1e1f22"
HALF_KM = 30   # every map shows 60 x 60 km, so the cities are at the same scale


def style():
    for f in (CONFIG / "fonts").glob("Atkinson*.ttf"):
        font_manager.fontManager.addfont(str(f))
    names = {f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams.update({
        "font.family": "Atkinson Hyperlegible" if "Atkinson Hyperlegible" in names else "DejaVu Sans",
        "font.size": 11, "axes.edgecolor": LINE, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": INK,
        "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlesize": 14,
        "axes.titlelocation": "left", "figure.dpi": 150, "savefig.bbox": "tight", "axes.grid": True,
        "axes.axisbelow": True, "grid.color": "#EDEFF0", "grid.linewidth": 0.8,
    })


def clean(v):
    v = v.item() if hasattr(v, "item") else v
    return round(v, 4) if isinstance(v, float) else v


def load():
    rows = []
    for city in race.CITIES:
        p = OUT / city / "summary.json"
        if p.exists():
            rows.append(read_json(p))
    if not rows:
        raise SystemExit("No results yet. Run scripts/04_drive_times.py first.")
    return rows


def fig_curves(rows):
    fig, ax = plt.subplots(figsize=(8.5, 5))
    ends = []
    for k, r in enumerate(rows):
        c = CITY_COLORS[list(race.CITIES).index(r["city"]) % len(CITY_COLORS)]
        x, y = np.array(r["curve_minutes"]), 100 * np.array(r["curve_share"])
        ax.plot(x, y, color=c, lw=2)
        ends.append([y[np.searchsorted(x, 25)], r["name"], c])
    ends.sort()
    last = -99
    for y, name, c in ends:  # direct labels, nudged apart
        y = max(y, last + 3.2)
        ax.text(25.4, y, name, color=INK, va="center", fontsize=10)
        ax.plot([25, 25.3], [y, y], color=c, lw=2)
        last = y
    for m in (10, 15, 20):
        ax.axvline(m, color=LINE, lw=1, zorder=0)
    ax.set_xlim(0, 25)
    ax.set_ylim(0, 102)
    ax.set_xlabel("Minutes by car to the nearest emergency department (free-flow)")
    ax.set_ylabel("% of people")
    ax.set_title("How quickly can people reach an A&E?")
    fig.savefig(FIGURES / "coverage_curves.png")
    plt.close(fig)


def fig_within(rows):
    rows = sorted(rows, key=lambda r: r["within_15"])
    fig, ax = plt.subplots(figsize=(8, 0.6 * len(rows) + 1.6))
    y = np.arange(len(rows))
    free = [100 * r["within_15"] for r in rows]
    busy = [100 * r["within_15_busy"] for r in rows]
    ax.hlines(y, busy, free, color=LINE, lw=3)
    ax.scatter(busy, y, s=70, color="white", edgecolor="#c03a76", lw=2, zorder=3, label="Busy traffic (journeys 50% longer)")
    ax.scatter(free, y, s=70, color="#2a78d6", zorder=4, label="Free-flowing traffic")
    for yi, f in zip(y, free):
        ax.annotate(f"{f:.0f}%", (f, yi), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=9)
    ax.set_yticks(y, [r["name"] for r in rows])
    ax.set_xlim(0, 104)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("% of people within 15 minutes' drive of an A&E")
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, -0.45), ncol=2)
    ax.set_title("Within 15 minutes of an emergency department")
    fig.savefig(FIGURES / "within_15.png")
    plt.close(fig)


def city_map(ax, city, show_title=True):
    import rasterio
    d = OUT / city
    with rasterio.open(d / "minutes.tif") as src:
        arr = src.read(1)
        b = src.bounds
    cfg = race.CITIES[city]
    cx, cy = race.transformer(race.WGS84, race.MOLLWEIDE).transform(cfg["lon"], cfg["lat"])
    cmap = ListedColormap(race.BAND_COLORS)
    norm = BoundaryNorm([0] + race.BANDS + [1e9], cmap.N)
    ax.set_facecolor(DARK)
    ax.imshow(np.ma.masked_invalid(arr), cmap=cmap, norm=norm, extent=(b.left, b.right, b.bottom, b.top), interpolation="nearest")
    h = pd.read_csv(d / "hospitals.csv")
    hx, hy = race.transformer(race.WGS84, race.MOLLWEIDE).transform(h["lon"].values, h["lat"].values)
    ax.scatter(hx, hy, marker="P", s=36, color="white", edgecolor=DARK, lw=0.6, zorder=3)
    ax.set_xlim(cx - HALF_KM * 1000, cx + HALF_KM * 1000)
    ax.set_ylim(cy - HALF_KM * 1000, cy + HALF_KM * 1000)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    if show_title:
        ax.set_title(cfg["name"], color=INK, fontsize=13)


def legend_handles():
    from matplotlib.patches import Patch
    labels = ["Under 5 min", "5–10", "10–15", "15–20", "20–30", "Over 30"]
    return [Patch(color=c, label=l) for c, l in zip(race.BAND_COLORS, labels)] + [
        plt.Line2D([], [], marker="P", ls="", color="white", markeredgecolor=INK, label="Emergency department")]


def fig_maps(rows):
    cities = [r["city"] for r in rows]
    n = len(cities)
    cols = 3 if n > 4 else n
    nrows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(nrows, cols, figsize=(4.2 * cols, 4.4 * nrows + 0.8), squeeze=False)
    for ax in axes.flat:
        ax.set_visible(False)
    for ax, city in zip(axes.flat, cities):
        ax.set_visible(True)
        city_map(ax, city)
    fig.legend(handles=legend_handles(), loc="lower center", ncol=7, frameon=False, fontsize=9)
    fig.suptitle("Drive time to the nearest A&E, every capital at the same scale (60 × 60 km)", x=0.02, ha="left",
                 fontweight="bold", fontsize=14)
    fig.savefig(FIGURES / "six_capitals.png")
    plt.close(fig)
    for city in cities:
        fig, ax = plt.subplots(figsize=(7, 7.6))
        city_map(ax, city)
        fig.legend(handles=legend_handles(), loc="lower center", ncol=4, frameon=False, fontsize=9)
        fig.savefig(FIGURES / f"map_{city}.png")
        plt.close(fig)


def main():
    RESULTS.mkdir(exist_ok=True)
    FIGURES.mkdir(exist_ok=True)
    style()
    rows = load()
    keep = ["name", "population", "area_km2", "hospitals", "people_per_hospital", "within_10", "within_15", "within_20",
            "within_30", "within_15_busy", "median_minutes", "p90_minutes", "hospital_source"]
    df = pd.DataFrame(rows).set_index("city")[keep]
    df.round(4).to_csv(RESULTS / "summary.csv")
    best = df["within_15"].idxmax()
    worst = df["within_15"].idxmin()
    write_json(RESULTS / "headline.json", {
        "cities": {c: {k: clean(v) for k, v in df.loc[c].items()} for c in df.index},
        "best_15": best, "worst_15": worst, "busy_factor": race.BUSY_FACTOR,
    })
    log(df[["population", "hospitals", "within_10", "within_15", "within_15_busy", "median_minutes", "p90_minutes"]]
        .assign(population=lambda x: (x["population"] / 1e6).round(2)).round(3).to_string())
    fig_curves(rows)
    fig_within(rows)
    fig_maps(rows)
    log("\nSaved results/ and figures/. Next: python scripts/06_build_dashboard.py")


if __name__ == "__main__":
    main()
