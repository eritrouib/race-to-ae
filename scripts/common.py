"""
common.py
Paths and helpers shared by the Race to A&E scripts.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

from race import CITIES

CODE = Path(__file__).resolve().parent.parent           # scripts and config
ROOT = Path(os.environ.get("RACE_ROOT") or CODE)        # data, results (tests point this elsewhere)
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
RESULTS = ROOT / "results"
FIGURES = ROOT / "figures"
VIDEOS = ROOT / "videos"
DOCS = ROOT / "docs"
CONFIG = CODE / "config"


def log(msg=""):
    print(msg, flush=True)


def city_dir(city):
    d = OUT / city
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(url, dest, refresh=False, quiet_404=False):
    """Download to dest (resumable-safe via .part). Returns the path, or None on 404 if quiet_404."""
    if dest.exists() and not refresh:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=180) as r:
        if r.status_code == 404 and quiet_404:
            return None
        r.raise_for_status()
        total, done = int(r.headers.get("content-length", 0)), 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total > 5e6:
                    print(f"\r    {dest.name}: {done / 1e6:5.0f} / {total / 1e6:.0f} MB", end="", flush=True)
    if total > 5e6:
        print()
    tmp.replace(dest)
    return dest


def city_args(description):
    ap = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cities", default=",".join(CITIES), help="comma-separated, e.g. london,paris (default: all six)")
    return ap


def chosen(args):
    cities = [c.strip().lower() for c in args.cities.split(",") if c.strip()]
    bad = [c for c in cities if c not in CITIES]
    if bad:
        sys.exit(f"Unknown city: {', '.join(bad)}. Choose from {', '.join(CITIES)}.")
    return cities


def need(path, step):
    if not path.exists():
        sys.exit(f"Missing {path}. Run scripts/{step} first.")
    return path


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class Timer:
    def __init__(self):
        self.t0 = time.time()

    def __str__(self):
        s = time.time() - self.t0
        return f"{s:.0f}s" if s < 120 else f"{s / 60:.1f} min"
