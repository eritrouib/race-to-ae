"""
Tests: the analysis core on hand-checkable cases, then steps 4-8 on the made-up
city from make_city.py.

    python -m unittest discover tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import networkx as nx
import numpy as np

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))
import race  # noqa: E402


def tiny(edges, coords):
    G = nx.MultiDiGraph()
    for n, (x, y) in coords.items():
        G.add_node(n, x=x, y=y)
    for a, b, L, hw in edges:
        G.add_edge(a, b, length=L, highway=hw)
    return race.network_arrays(G)


class Core(unittest.TestCase):
    def test_osm_tags(self):
        self.assertTrue(race.can_drive("residential", {}))
        self.assertFalse(race.can_drive("residential", {"access": "private"}))
        self.assertTrue(race.can_drive("residential", {"access": "private", "motor_vehicle": "yes"}))
        self.assertFalse(race.can_drive("footway", {}))
        self.assertEqual(race.oneway_of("primary", {"oneway": "-1"}), -1)
        self.assertEqual(race.oneway_of("residential", {"junction": "roundabout"}), 1)
        self.assertEqual(race.oneway_of("motorway", {}), 1)
        self.assertEqual(race.osm_tags('"oneway"=>"yes","maxspeed"=>"30"'), {"oneway": "yes", "maxspeed": "30"})

    def test_speeds(self):
        self.assertEqual(race.edge_speed("residential"), race.SPEEDS["residential"])
        self.assertEqual(race.edge_speed(["primary", "secondary"]), race.SPEEDS["primary"])
        self.assertAlmostEqual(race.edge_speed("primary", "20 mph"), 20 * 1.609344)   # lower limit wins
        self.assertEqual(race.edge_speed("residential", "50"), race.SPEEDS["residential"])  # higher limit doesn't
        self.assertEqual(race.edge_speed("primary", "FR:zone30"), 30)
        self.assertIsNone(race.parse_maxspeed("signals"))
        self.assertEqual(race.parse_maxspeed(["50", "30"]), 30)
        self.assertEqual(race.edge_speed("['primary', 'residential']", "['30', '50']"), 30)   # lists after a graphml reload

    def test_one_way_streets_respected(self):
        coords = {1: (0, 0), 2: (0.01, 0), 3: (0.02, 0)}
        net = tiny([(1, 2, 1000, "residential"), (2, 3, 1000, "residential"), (3, 2, 1000, "residential")], coords)
        dist, src = race.minutes_to_nearest(net, [0])          # hospital at junction 1 (index 0)
        per_km = 1000 / (race.SPEEDS["residential"] / 3.6) / 60
        self.assertEqual(dist[0], 0)
        self.assertTrue(np.isinf(dist[1]) and np.isinf(dist[2]), "1 -> 2 is one-way, so nobody can drive back to 1")
        dist, _ = race.minutes_to_nearest(net, [1])            # hospital at junction 2
        self.assertAlmostEqual(dist[0], per_km)               # 1 can drive to 2
        self.assertAlmostEqual(dist[2], per_km)

    def test_nearest_of_several_hospitals(self):
        coords = {i: (i * 0.01, 0) for i in range(5)}
        e = [(i, i + 1, 1000, "residential") for i in range(4)] + [(i + 1, i, 1000, "residential") for i in range(4)]
        net = tiny(e, coords)
        dist, src = race.minutes_to_nearest(net, [0, 4])
        per_km = 1000 / (race.SPEEDS["residential"] / 3.6) / 60
        np.testing.assert_allclose(dist, [0, per_km, 2 * per_km, per_km, 0])
        self.assertEqual(list(src[[1, 3]]), [0, 4])

    def test_coverage_and_summary(self):
        minutes = np.array([5.0, 12.0, 25.0, np.inf])
        pop = np.array([100.0, 100.0, 100.0, 100.0])
        s = race.summary(minutes, pop)
        self.assertAlmostEqual(s["within_10"], 0.25)
        self.assertAlmostEqual(s["within_15"], 0.5)
        self.assertAlmostEqual(s["within_15_busy"], 0.25)   # 12 x 1.5 = 18
        self.assertEqual(s["unreachable"], 100)
        grid, cum = race.coverage(minutes, pop)
        self.assertAlmostEqual(cum[list(grid).index(12.0)], 0.5)

    def test_urban_centre_rule(self):
        pop = np.zeros((30, 30))
        pop[5:15, 5:15] = 2000          # 100 km², 200,000 people: an urban centre
        pop[20:22, 20:22] = 5000        # dense but only 20,000 people: not one
        pop[9, 9] = 100                 # a park in the middle: filled in
        mask = race.urban_centre(pop, (10, 10))
        self.assertEqual(int(mask.sum()), 100)
        self.assertFalse(mask[21, 21])
        self.assertTrue(mask[9, 9])

    def test_tiles_and_dedupe(self):
        self.assertEqual(len(race.tiles_for_bbox(-50000, 6100000, 30000, 6200000)), 2)   # straddles a tile edge
        keep = race.dedupe_points(np.array([0, 0.001, 1]), np.array([50, 50, 50]), 300)
        self.assertEqual(list(keep), [0, 2])

    def test_edge_times_orient_from_first_reached(self):
        net = {"u": np.array([0]), "v": np.array([1]), "minutes": np.array([2.0])}
        t0, t1, flip = race.edge_times(net, np.array([9.0, 3.0]))
        self.assertEqual((t0[0], t1[0], bool(flip[0])), (3.0, 5.0, True))


class FromOsmFile(unittest.TestCase):
    """Steps 2 and 3 reading an OpenStreetMap file, as they do with the Geofabrik extracts."""

    @classmethod
    def setUpClass(cls):
        import make_city
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.info = make_city.make(cls.root, city="london")
        osm = make_city.write_osm(cls.root / "city.osm", "london")
        env = {**os.environ, "RACE_ROOT": str(cls.root)}
        for step in ["02_network.py", "03_hospitals.py"]:
            r = subprocess.run([sys.executable, str(SCRIPTS / step), "--cities", "london", "--osm-file", str(osm)],
                               env=env, capture_output=True, text=True)
            if r.returncode:
                raise AssertionError(f"{step} failed:\n{r.stdout[-1500:]}\n{r.stderr[-2500:]}")
        cls.d = cls.root / "data" / "processed" / "london"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_network_matches_the_grid(self):
        import importlib
        net = importlib.import_module("02_network").load_network(self.d / "network.npz")
        n = 41
        # 2 x 41 x 40 street blocks, two-way except the one-way top row: 4 x 41 x 40 - 40 links
        self.assertEqual(len(net["u"]), 4 * n * (n - 1) - (n - 1))
        self.assertEqual(len(net["lon"]), n * n)          # private road and bridge add no junctions

    def test_hospitals_from_osm(self):
        import pandas as pd
        h = pd.read_csv(self.d / "hospitals.csv")
        self.assertEqual(sorted(h["name"]), ["Central Hospital", "Corner Hospital"])   # emergency=no left out


class Pipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import make_city
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.info = make_city.make(cls.root)
        env = {**os.environ, "RACE_ROOT": str(cls.root), "MPLBACKEND": "Agg"}
        for step in [["04_drive_times.py", "--cities", "athens"], ["05_summarise.py"], ["06_build_dashboard.py", "--cities", "athens"],
                     ["07_make_videos.py", "--cities", "athens", "--seconds", "1", "--size", "320"], ["08_write_post.py"]]:
            r = subprocess.run([sys.executable, str(SCRIPTS / step[0]), *step[1:]], env=env, capture_output=True, text=True)
            if r.returncode:
                raise AssertionError(f"{step[0]} failed:\n{r.stdout[-1500:]}\n{r.stderr[-2500:]}")
        cls.d = cls.root / "data" / "processed" / "athens"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_urban_centre(self):
        self.assertEqual(self.info["km2"], 400)          # the dense 20 x 20 km square, not the village

    def test_drive_times_match_hand_calculation(self):
        node_min = np.load(self.d / "node_minutes.npz")["minutes"]
        c = self.info["centre_node"]
        self.assertEqual(node_min[c], 0)
        resid = 500 / (race.SPEEDS["residential"] / 3.6) / 60
        avenue = 500 / (race.SPEEDS["primary"] / 3.6) / 60
        self.assertAlmostEqual(node_min[c + 1], resid, places=6)        # one block east, on a side street
        self.assertAlmostEqual(node_min[c - 41], avenue, places=6)      # one block north, along the avenue
        self.assertAlmostEqual(node_min[c - 41 * 4], 4 * avenue, places=6)

    def test_outputs(self):
        s = json.loads((self.d / "summary.json").read_text())
        self.assertGreater(s["within_30"], s["within_15"])
        self.assertGreaterEqual(s["within_15"], s["within_15_busy"])
        for f in ["results/summary.csv", "figures/coverage_curves.png", "figures/six_capitals.png", "docs/index.html",
                  "docs/data/meta.js", "docs/data/athens.js", "videos/race_to_ae_athens.mp4", "results/post/index.qmd"]:
            self.assertTrue((self.root / f).exists(), f)
        self.assertGreater((self.root / "videos/race_to_ae_athens.mp4").stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
