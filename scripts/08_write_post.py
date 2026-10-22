"""
08_write_post.py
Race to A&E - Step 8: a draft write-up for the blog, with this run's numbers.

Usage (from the project folder, after step 5):
    python scripts/08_write_post.py

Output:
    results/post/index.qmd   copy to posts/2026-10-race-to-ae/index.qmd in the website repo,
                             then read it through: some sentences change with the results,
                             but it is a starting point, not a finished article.
"""

from datetime import date

from common import RESULTS, log, need, read_json

SITE = "https://etymo.co.uk"
REPO = "eritrouib/race-to-ae"


def p(x):
    return f"{100 * x:.0f}%"


def p1(x):
    return f"{100 * x:.1f}%"


def join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def article(h):
    c = h["cities"]
    keys = list(c)
    by15 = sorted(keys, key=lambda k: -c[k]["within_15"])
    by10 = sorted(keys, key=lambda k: -c[k]["within_10"])
    by_med = sorted(keys, key=lambda k: c[k]["median_minutes"])
    by_per = sorted(keys, key=lambda k: c[k]["people_per_hospital"])
    fig = f"https://raw.githubusercontent.com/{REPO}/main/figures"
    vid = f"{SITE}/race-to-ae/media"
    lo15, hi15 = min(c[k]["within_15"] for k in keys), max(c[k]["within_15"] for k in keys)
    close_at_15 = hi15 - lo15 < 0.08
    b10, w10 = c[by10[0]], c[by10[-1]]
    rows = "\n".join(
        f"| {c[k]['name']} | {c[k]['population'] / 1e6:.1f}m | {c[k]['hospitals']} | {p(c[k]['within_10'])} | "
        f"{p1(c[k]['within_15'])} | {c[k]['median_minutes']:.1f} | {c[k]['p90_minutes']:.0f} |" for k in by10)
    gisco = [c[k]["name"] for k in keys if "GISCO" in str(c[k].get("hospital_source", ""))]
    osm = [c[k]["name"] for k in keys if "GISCO" not in str(c[k].get("hospital_source", ""))]
    sources = []
    if gisco:
        sources.append(f"for {join(gisco)}, Eurostat's European register of healthcare services, compiled from national "
                       "health ministries and statistics offices, which marks hospitals that provide emergency care")
    if osm:
        sources.append(f"for {join(osm)}, hospitals tagged with an emergency department in OpenStreetMap, which I checked by "
                       "hand and cleaned (eye hospitals, dental and primary care clinics, a closed A&E and similar sites "
                       "taken out)")
    if close_at_15:
        headline = (f"At 15 minutes the race is close: between **{p1(lo15)}** and **{p1(hi15)}** of people in every capital can "
                    "drive to an emergency department in that time on clear roads. The real differences are in the first ten "
                    "minutes.")
        lesson1_title = "Lesson one: the race is won in the first ten minutes"
        lesson1 = (f"Within ten minutes, **{p(b10['within_10'])}** of people in **{b10['name']}** can reach an A&E, against "
                   f"**{p(w10['within_10'])}** in **{w10['name']}**. The typical (median) drive ranges from "
                   f"{c[by_med[0]]['median_minutes']:.1f} minutes in {c[by_med[0]]['name']} to "
                   f"{c[by_med[-1]]['median_minutes']:.1f} in {c[by_med[-1]]['name']}. For most journeys a few minutes make "
                   "little difference; for a stroke, a heart attack or a serious bleed, they are exactly the minutes that matter.")
    else:
        headline = (f"In **{c[by15[0]]['name']}**, **{p(hi15)}** of people can reach an emergency department within 15 "
                    f"minutes on clear roads; in **{c[by15[-1]]['name']}**, **{p(lo15)}**.")
        lesson1_title = "Lesson one: not every capital is a 15-minute city for emergencies"
        lesson1 = (f"Within ten minutes the spread is wider still: from **{p(b10['within_10'])}** in {b10['name']} to "
                   f"**{p(w10['within_10'])}** in {w10['name']}.")
    few, many = c[by_per[-1]], c[by_per[0]]
    osm_count = ["none", "one", "two", "three", "four", "five", "six"][len(osm)] if len(osm) <= 6 else str(len(osm))
    athens_note = ("\n- **Athens hospitals take turns.** Greek hospitals share emergency duty on a rota, so on any given day fewer "
                   "emergency departments take new patients than this map assumes. On a typical day the Athens numbers would be lower."
                   if "athens" in keys else "")
    return f'''---
title: "Race to A&E: how quickly can you reach an emergency department in six European capitals?"
description: "I measured the drive from where people live to the nearest emergency department in London, Paris, Berlin, Madrid, Rome and Athens, and turned it into a race."
date: {date.today().isoformat()}
categories: [health, network analysis, spatial analysis, Python]
image: {fig}/six_capitals.png
---

In an emergency, minutes matter. So I asked a simple question of six European capitals: **how long does it take to drive from where people live to the nearest emergency department?**

The answer is easier to see than to read. I started the clock at every A&E in each city at the same moment and let the road network light up as each street came within reach. The last streets to light up are the gaps.

{{{{< video {vid}/race_to_ae_six_capitals.mp4 >}}}}

*All six capitals at once: the clock runs to 30 minutes in about 10 seconds.*

[Play the race for any of the six cities on the dashboard]({SITE}/race-to-ae/), switch to busy traffic, or click anywhere to see how far the nearest A&E is.

## Comparing like with like

Comparing capitals is harder than it looks, because their administrative boundaries mean very different things: the City of Paris is tiny next to Greater London, and the Municipality of Rome includes farmland. So I used the same definition of a city everywhere, the **urban centre** from the UN and Eurostat's Degree of Urbanisation: all the neighbouring square kilometres with at least 1,500 residents each.

- **People:** the EU's Global Human Settlement Layer, population per 100 m square for 2025.
- **Emergency departments:** {"; and ".join(sources)}. Hospitals up to 8 km outside each urban centre count.
- **Roads:** OpenStreetMap, with the same typical urban driving speeds in every city (lower where a lower limit is posted), and one-way streets respected.

## The race

{headline}

| City | People | A&Es | Within 10 min | Within 15 min | Typical drive (min) | Slowest 10% (min+) |
|---|---:|---:|---:|---:|---:|---:|
{rows}

![Share of people who can reach an A&E within each number of minutes.]({fig}/coverage_curves.png){{.callout-figure}}

## {lesson1_title}

{lesson1}

## Lesson two: it isn't just how many hospitals

{many['name']} has an emergency department for every {many['people_per_hospital'] / 1e3:.0f},000 people in its urban centre; {few['name']} has one for every {few['people_per_hospital'] / 1e3:.0f},000. Yet {few['name']} still gets {p(few['within_15'])} of people to an A&E within 15 minutes. What decides the wait is where the hospitals sit relative to where people live, and how well the roads connect them.

![Drive time to the nearest A&E, each city at the same scale.]({fig}/six_capitals.png){{.callout-figure}}

## Lesson three: rush hour eats the margin

The numbers above assume the roads are clear. If every journey takes 50% longer, being within 15 minutes means being within 10 minutes on clear roads, so the shares fall to the ten-minute column: from {p1(lo15)}–{p1(hi15)} to {p(w10['within_10'])}–{p(b10['within_10'])}. Rush hour turns a comfortable margin into a tight one.

![Within 15 minutes, with clear roads and busy traffic.]({fig}/within_15.png){{.callout-figure}}

## What this doesn't tell you

- **These are journeys to hospital, not ambulance response times.** Ambulances on blue lights are faster; most people with a broken wrist drive or take a taxi.
- **Not every emergency department treats everything.** Major trauma, stroke and heart attack care is concentrated in fewer specialist centres.
- **Registers differ.** Each country defines "emergency care" a little differently, and {osm_count} of the {["none", "one", "two", "three", "four", "five", "six"][len(keys)] if len(keys) <= 6 else len(keys)} lists come from OpenStreetMap.{athens_note}
- **Traffic is a single factor.** Real congestion varies by street and by hour.

## Then and now

My [pedestrian safety project]({SITE}/london-pedestrian-safety/) measured drive times to London's four major trauma centres. This time the same idea runs on six capitals, with open data from three different sources, and turns into an animation as well as a table.

As before, I worked with an AI assistant, Claude. The questions, the choice of a fair city definition, the review of the hospital lists and the judgement about what the numbers mean are mine. Everything was tested on a made-up city with known answers before it ran on real ones.

- **Watch the race:** [{SITE.replace("https://", "")}/race-to-ae]({SITE}/race-to-ae/)
- **Code and method:** [github.com/{REPO}](https://github.com/{REPO})

---

*Data: © OpenStreetMap contributors (ODbL); European Commission JRC, Global Human Settlement Layer GHS-POP R2023A (CC BY 4.0); Eurostat GISCO healthcare services. Drive times assume free-flowing traffic at typical urban speeds.*
'''


def main():
    h = read_json(need(RESULTS / "headline.json", "05_summarise.py"))
    out = RESULTS / "post" / "index.qmd"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(article(h), encoding="utf-8")
    log(f"Draft saved to {out}. Read it through before publishing.")


if __name__ == "__main__":
    main()
