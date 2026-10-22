# Race to A&E

How quickly can people in six European capitals reach an emergency department by car? London, Paris, Berlin, Madrid, Rome and Athens, compared like for like, with the road network lighting up from every A&E at once.

**[Watch the race](https://etymo.co.uk/race-to-ae/)**

## Status

| Step | What | Status |
|---|---|---|
| 1 | Population (GHSL 100 m) and each city's urban centre | Done |
| 2 | Road network from OpenStreetMap, consistent driving speeds | Done |
| 3 | Emergency departments (Eurostat GISCO; OpenStreetMap for London) | Done |
| 4 | Drive time from every street and every 100 m of population | Done |
| 5 | Comparison tables and figures | Done |
| 6 | Animated dashboard | Done |
| 7 | Square MP4 videos for social media | Done |
| 8 | Draft write-up, filled in from the results | Done |

## Getting started

Requires Python 3.10 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

python scripts/01_population.py --clean
python scripts/02_network.py
python scripts/03_hospitals.py --clean
python scripts/04_drive_times.py
python scripts/05_summarise.py
python scripts/06_build_dashboard.py
python scripts/07_make_videos.py
python scripts/08_write_post.py
```

Every step takes `--cities london,athens` to run only some cities. Step 2 is the slow one: it downloads OpenStreetMap extracts from Geofabrik (about 2 GB for all six cities, 100–500 MB each) and reads the roads out of them, a few minutes per city. Step 1 downloads one or two population tiles per city (50–100 MB each). `--clean` on steps 1 and 3 deletes the big downloads once the small cut-outs are saved.

### Step 1: people and the urban centre

Capitals' administrative boundaries mean very different things (the City of Paris is a fraction of Greater London; the Municipality of Rome includes farmland), so each city is defined the same way: its **urban centre** under the UN/Eurostat **Degree of Urbanisation**. That is the cluster of contiguous 1 km² cells with at least 1,500 residents each and 50,000 in total, with gaps filled and cells mostly surrounded by it added.

Population comes from the European Commission's [Global Human Settlement Layer](https://human-settlement.emergency.copernicus.eu/) (GHS-POP R2023A, 2025, 100 m, Mollweide).

### Step 2: roads and speeds

All roads a car can use within 8 km of each urban centre, read straight from Geofabrik's OpenStreetMap extracts (London needs Greater London plus the surrounding counties; Berlin needs Brandenburg too; see `EXTRACTS` in the script). Private roads and `motor_vehicle=no` are left out, one-way streets and roundabouts are respected, and ways join only where they share a node, so bridges and tunnels don't create false junctions. Only the part of the network where every junction can reach every other is kept.

There's no dependence on the public Overpass server, which is often overloaded. `--overpass` uses it through OSMnx anyway (with retries across three servers), and `--osm-file` uses .osm.pbf files you already have. Speeds are the same **typical free-flow urban speeds** in every city (`scripts/race.py`, `SPEEDS`): 80 km/h on motorways, 40 on main roads, 22 on residential streets. A lower posted limit (a 20 mph or 30 km/h zone) applies where tagged. Using one table everywhere means the comparison reflects the roads and the hospitals, not how each country tags speed limits.

### Step 3: emergency departments

| City | Source |
|---|---|
| Paris, Berlin, Madrid, Rome, Athens | [Eurostat GISCO healthcare services](https://ec.europa.eu/eurostat/web/gisco/geodata/basic-services) (national health ministries and statistics offices), hospitals with `emergency = yes` |
| London | OpenStreetMap hospitals tagged `emergency=yes` (the UK isn't in GISCO) |

If GISCO has no emergency flags for a country, the script falls back to OpenStreetMap and says so (in the first run this happened for Berlin, Madrid and Rome). OpenStreetMap's `emergency=yes` is sometimes used for eye hospitals, clinics or closed A&Es, so the London, Madrid and Rome lists were reviewed by hand: `config/hospitals/` holds the cleaned lists and `config/hospitals/REMOVED.md` says what was taken out and why. Hospitals up to 8 km outside the urban centre count. Sites within 300 m are merged. **Review `results/hospitals_<city>.csv`**; to correct a list, copy it to `config/hospitals/<city>.csv`, edit and re-run step 3.

### Step 4: drive times

One shortest-path run per city on the reversed network gives the time from every junction **to** its nearest A&E, respecting one-way streets. Each 100 m populated cell takes its nearest junction's time plus a short, slow trip (15 km/h) to reach the road.

| File (`data/processed/<city>/`) | Contents |
|---|---|
| `cells.parquet` | lon, lat, people, minutes, nearest hospital for every populated cell |
| `minutes.tif` | the same as a 100 m grid |
| `summary.json` | shares of people within 10/15/20/30 minutes (free-flow and busy), median and 90th percentile |

### Step 5: comparison

`results/summary.csv`, `results/headline.json` and figures: `coverage_curves.png` (share of people within each number of minutes), `within_15.png` (free-flow and busy), `six_capitals.png` (all six maps at the same 60 × 60 km scale) and `map_<city>.png`.

**Busy traffic** multiplies every journey by 1.5. It's a simple stress test, not a congestion model.

### Step 6: dashboard

Writes `docs/` (one page plus a data file per city, loaded only when the city is chosen). Push and switch on GitHub Pages (Settings → Pages → main branch, `/docs`); it appears at `etymo.co.uk/race-to-ae/`. Choose a capital and press play: the network lights up from every A&E at once, coloured by minutes, while the clock shows the share of people reached so far. Switch to busy traffic, scrub the timeline, click anywhere for the drive time from there, and compare all six on one chart. Built with deck.gl; open `docs/index.html#athens` to start on a city.

### Step 7: videos

`videos/race_to_ae_<city>.mp4`: 1080 × 1080, about 13 seconds, plus a still of the last frame. `videos/race_to_ae_six_capitals.mp4`: all six racing side by side in one video (LinkedIn takes one video per post), also copied to `docs/media/` for the blog. `--seconds` and `--size` change the length and size; `--grid-only` remakes just the six-city video.

### Step 8: write-up

`results/post/index.qmd`: a draft post with this run's numbers. Copy to `posts/<date>-race-to-ae/index.qmd` in the website repo, then read every sentence against the numbers before publishing.

## Tests

```bash
python -m unittest discover tests
```

The tests check the core on cases worked out by hand (speeds and posted limits, one-way streets, the nearest of several hospitals, the urban-centre rule, coverage shares), then build a made-up city (`tests/make_city.py`): a 20 × 20 km block of 3,000 people per km² with a 500 m street grid, a fast avenue, a one-way street and two hospitals, and run steps 4–8 on it. The drive times match the hand calculation exactly; for example, one block north along the avenue is 500 m at 40 km/h, 0.75 minutes.

## Data

| Data | Publisher | Licence |
|---|---|---|
| Roads, London A&Es | © OpenStreetMap contributors | ODbL |
| GHS-POP R2023A (2025, 100 m) | European Commission, Joint Research Centre | CC BY 4.0 |
| Healthcare services (hospitals) | Eurostat GISCO, from national sources | see GISCO metadata |
| Basemap | Esri | Esri terms |

## Known limitations

- These are journeys **to** hospital at typical free-flow speeds, not ambulance response times. Blue lights are faster; rush hour is slower.
- Not every emergency department treats everything: major trauma, stroke and cardiac care are concentrated in fewer centres.
- Countries define "emergency care" differently in their registers, and London's list comes from OpenStreetMap.
- A single traffic factor can't capture congestion that varies by street and hour.

Tools: Python, OSMnx, GeoPandas, rasterio, SciPy (sparse graphs, Dijkstra), Matplotlib, Pillow, FFmpeg, deck.gl.

Made by Eriola Trungu Impersimi · @ET
