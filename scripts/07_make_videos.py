"""
07_make_videos.py
Race to A&E - Step 7: short videos for social media.

For each city, a square 1080 x 1080 MP4 (about 13 seconds): the road network
lights up from every emergency department at once, coloured by drive time,
with a clock and the share of people reached so far. A still of the last
frame is saved too.

Usage (from the project folder, after step 4):
    python scripts/07_make_videos.py
    python scripts/07_make_videos.py --cities athens --seconds 8 --size 720

Outputs:
    videos/race_to_ae_<city>.mp4
    videos/race_to_ae_<city>.png
"""

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

import race
from common import CONFIG, OUT, VIDEOS, Timer, chosen, city_args, log, need, read_json

BG = (22, 23, 26)
NET = (52, 55, 60)
INK = (237, 239, 240)
MUTED = (163, 171, 177)
HOT = (254, 194, 135)
MAXT = 30
SS = 2  # supersampling for smooth lines


def font(name, size, bold=False):
    f = CONFIG / "fonts" / name
    try:
        ft = ImageFont.truetype(str(f), size)
        if "Overpass" in name:
            try:
                ft.set_variation_by_name("ExtraBold")
            except Exception:  # noqa: BLE001
                pass
        return ft
    except OSError:
        return ImageFont.load_default()


def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def project(net, size, pad, header, footer):
    """Road coordinates in pixels (equal-area metres, fitted to the frame)."""
    to_m = race.transformer(race.WGS84, race.LAEA)
    allc = np.vstack(net["coords"])
    x, y = to_m.transform(allc[:, 0], allc[:, 1])
    x0, x1, y0, y1 = np.percentile(x, 0.2), np.percentile(x, 99.8), np.percentile(y, 0.2), np.percentile(y, 99.8)
    w, h = size - 2 * pad, size - header - footer
    scale = min(w / (x1 - x0), h / (y1 - y0))
    ox = pad + (w - (x1 - x0) * scale) / 2
    oy = header + (h - (y1 - y0) * scale) / 2

    def px(lon, lat):
        mx, my = to_m.transform(np.asarray(lon), np.asarray(lat))
        return ox + (mx - x0) * scale, oy + (y1 - my) * scale

    return px, scale


def render_city(city, seconds=10, size=1080, fps=30):
    from importlib import import_module
    import imageio_ffmpeg
    load_network = import_module("02_network").load_network
    d = OUT / city
    net = load_network(need(d / "network.npz", "02_network.py"))
    node_min = np.load(d / "node_minutes.npz")["minutes"]
    hosp = pd.read_csv(d / "hospitals.csv")
    s = read_json(d / "summary.json")
    name = race.CITIES[city]["name"]
    S = size * SS
    header, footer, pad = int(0.13 * S), int(0.17 * S), int(0.04 * S)
    px, scale = project(net, S, pad, header, footer)

    t0, _, _ = race.edge_times(net, node_min)
    lens = np.array([len(c) for c in net["coords"]])
    allc = np.vstack(net["coords"])
    X, Y = px(allc[:, 0], allc[:, 1])
    starts = np.r_[0, np.cumsum(lens)[:-1]]
    polys = [list(zip(X[a:a + n].tolist(), Y[a:a + n].tolist())) for a, n in zip(starts, lens)]
    order = np.argsort(np.where(np.isfinite(t0), t0, np.inf))
    colors = [hex_rgb(c) for c in race.BAND_COLORS]
    lw = max(2, int(S / 900))

    canvas = Image.new("RGB", (S, S), BG)
    draw = ImageDraw.Draw(canvas)
    for p in polys:               # the whole network, faint, before anything lights up
        draw.line(p, fill=NET, width=max(1, lw // 2))
    hx, hy = px(hosp["lon"].values, hosp["lat"].values)

    f_title = font("Overpass-Variable.ttf", int(0.05 * S))
    f_sub = font("AtkinsonHyperlegible-Regular.ttf", int(0.024 * S))
    f_clock = font("Overpass-Variable.ttf", int(0.105 * S))
    f_small = font("AtkinsonHyperlegible-Regular.ttf", int(0.021 * S))
    f_bold = font("AtkinsonHyperlegible-Bold.ttf", int(0.03 * S))
    curve_x, curve_y = np.array(s["curve_minutes"]), np.array(s["curve_share"])

    def overlay(img, t):
        dr = ImageDraw.Draw(img)
        r = max(5, int(S / 220))
        for x, y in zip(hx, hy):
            dr.ellipse([x - r - 3, y - r - 3, x + r + 3, y + r + 3], fill=BG)
            dr.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255))
        dr.text((pad, int(0.03 * S)), name, font=f_title, fill=INK)
        dr.text((pad, int(0.03 * S) + int(0.062 * S)), "Race to A&E: drive time to the nearest emergency department", font=f_sub, fill=MUTED)
        base_y = S - footer + int(0.004 * S)
        dr.text((pad, base_y), f"{int(t):d} min", font=f_clock, fill=INK)
        share = float(np.interp(t, curve_x, curve_y))
        dr.text((pad, base_y + int(0.115 * S)), f"{share:.0%} of people reached", font=f_bold, fill=HOT)
        # legend
        lx, ly = int(0.56 * S), base_y + int(0.01 * S)
        labels = ["< 5", "5–10", "10–15", "15–20", "20–30", "30+ min"]
        for i, (c, lab) in enumerate(zip(colors, labels)):
            cx, cy = lx + (i % 3) * int(0.135 * S), ly + (i // 3) * int(0.045 * S)
            dr.rounded_rectangle([cx, cy + int(0.008 * S), cx + int(0.035 * S), cy + int(0.018 * S)], radius=4, fill=c)
            dr.text((cx + int(0.042 * S), cy), lab, font=f_small, fill=INK)
        dr.ellipse([lx, ly + int(0.1 * S), lx + int(0.02 * S), ly + int(0.12 * S)], fill=(255, 255, 255))
        dr.text((lx + int(0.03 * S), ly + int(0.095 * S)), "Emergency department", font=f_small, fill=INK)
        brand = "@ET · etymo.co.uk"
        dr.text((S - pad - dr.textlength(brand, font=f_small), int(0.04 * S)), brand, font=f_small, fill=MUTED)
        # 5 km scale bar
        sb = 5000 * scale
        y = int(0.105 * S)
        dr.line([(S - pad - sb, y), (S - pad, y)], fill=MUTED, width=lw)
        dr.text((S - pad - sb, y - int(0.03 * S)), "5 km", font=f_small, fill=MUTED)
        return img

    VIDEOS.mkdir(exist_ok=True)
    out = VIDEOS / f"race_to_ae_{city}.mp4"
    writer = imageio_ffmpeg.write_frames(str(out), (size, size), fps=fps, codec="libx264", macro_block_size=8,
                                         pix_fmt_out="yuv420p", output_params=["-crf", "20", "-movflags", "+faststart"])
    writer.send(None)
    n_frames = int(seconds * fps)
    hold_start, hold_end = int(0.6 * fps), int(2.5 * fps)
    k = 0
    frame = None
    for i in range(-hold_start, n_frames + hold_end):
        t = MAXT * min(max(i, 0), n_frames) / n_frames
        while k < len(order) and t0[order[k]] <= t:
            e = order[k]
            draw.line(polys[e], fill=colors[race.band_of(t0[e])], width=lw)
            k += 1
        frame = overlay(canvas.copy(), t).resize((size, size), Image.LANCZOS)
        writer.send(frame.tobytes())
    writer.close()
    frame.save(VIDEOS / f"race_to_ae_{city}.png")
    return out


def main():
    ap = city_args(__doc__)
    ap.add_argument("--seconds", type=float, default=10, help="length of the spread (plus a short hold)")
    ap.add_argument("--size", type=int, default=1080)
    args = ap.parse_args()
    for city in chosen(args):
        if not (OUT / city / "summary.json").exists():
            log(f"  skipping {city}: no results")
            continue
        t = Timer()
        path = render_city(city, args.seconds, args.size)
        log(f"  {race.CITIES[city]['name']}: {path.name} ({t})")
    log("\nNext: python scripts/08_write_post.py")


if __name__ == "__main__":
    main()
