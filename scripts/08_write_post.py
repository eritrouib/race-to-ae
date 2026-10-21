"""
08_write_post.py
Race to A&E - Step 8: a draft write-up for the blog, with this run's numbers.

Usage (from the project folder, after step 5):
    python scripts/08_write_post.py

Output:
    results/post/index.qmd   copy to posts/<date>-race-to-ae/index.qmd in the website repo,
                             then read it through and edit: some sentences change with the
                             results, but it is a starting point, not a finished article.
"""

from datetime import date

from common import RESULTS, log, need, read_json

SITE = "https://etymo.co.uk"
REPO = "eritrouib/race-to-ae"


def p(x):
    return f"{100 * x:.0f}%"


def join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def article(h):
    c = h["cities"]
    order = sorted(c, key=lambda k: -c[k]["within_15"])
    best, worst = c[order[0]], c[order[-1]]
    fig = f"https://raw.githubusercontent.com/{REPO}/main/figures"
    rows = "\n".join(
        f"| {c[k]['name']} | {c[k]['population'] / 1e6:.1f}m | {c[k]['hospitals']} | {p(c[k]['within_10'])} | "
        f"{p(c[k]['within_15'])} | {p(c[k]['within_15_busy'])} | {c[k]['median_minutes']:.1f} | {c[k]['p90_minutes']:.0f} |"
        for k in order)
    drop = max(order, key=lambda k: c[k]["within_15"] - c[k]["within_15_busy"])
    per_h = sorted(order, key=lambda k: c[k]["people_per_hospital"])
    names = [c[k]["name"] for k in order]
    gap = best["within_15"] - worst["within_15"]
    spread = ("The gap between the best and the worst is small" if gap < 0.1 else
              f"That is a gap of {100 * gap:.0f} percentage points between capitals that all think of themselves as well served")
    return f'''---
title: "Race to A&E: how quickly can you reach an emergency department in six European capitals?"
description: "I measured the drive from every street in London, Paris, Berlin, Madrid, Rome and Athens to the nearest emergency department, and turned it into a race."
date: {date.today().isoformat()}
categories: [health, network analysis, spatial analysis, Python]
image: {fig}/six_capitals.png
---

In an emergency, minutes matter. So I asked a simple question of six European capitals: **how long does it take to drive from where people live to the nearest emergency department?**

The answer is easier to see than to read. I started the clock at every A&E in a city at the same moment and let the road network light up as each street came within reach. The last streets to light up are the gaps.

[Watch it for any of the six cities on the dashboard]({SITE}/race-to-ae/).

## Comparing like with like

Comparing capitals is harder than it looks, because their administrative boundaries mean different things: the City of Paris is tiny next to Greater London, and the Municipality of Rome includes farmland. So I used the same definition of a city everywhere, the **urban centre** from the UN and Eurostat's Degree of Urbanisation: all the neighbouring square kilometres with at least 1,500 residents each.

- **People:** the EU's Global Human Settlement Layer, population per 100 m square for 2025.
- **Emergency departments:** Eurostat's European register of healthcare services, compiled from national health ministries and statistics offices, which marks hospitals that provide emergency care. The UK isn't in it, so for London I used OpenStreetMap hospitals tagged with an emergency department. Hospitals up to 8 km outside each urban centre count.
- **Roads:** OpenStreetMap, with the same typical free-flow speeds in every city (lower where a lower limit is posted), and one-way streets respected.

## The race

| City | People | A&Es | Within 10 min | Within 15 min | 15 min, busy traffic | Typical drive (min) | Slowest 10% (min+) |
|---|---:|---:|---:|---:|---:|---:|---:|
{rows}

In order, from the most people within 15 minutes to the fewest: {join(names)}. In **{best['name']}**, **{p(best['within_15'])}** of people can reach an emergency department in 15 minutes on clear roads; in **{worst['name']}** it is **{p(worst['within_15'])}**. {spread}.

![Share of people who can reach an A&E within each number of minutes.]({fig}/coverage_curves.png){{.callout-figure}}

## Traffic changes the ranking less than the map does

Free-flowing traffic is the best case. If every journey takes 50% longer, the share within 15 minutes falls everywhere, most in **{c[drop]['name']}**, from {p(c[drop]['within_15'])} to {p(c[drop]['within_15_busy'])}. Where the hospitals are matters more than how fast the traffic moves: a city with emergency departments spread across its neighbourhoods holds up much better than one where they cluster in the centre.

![Within 15 minutes, with clear roads and busy traffic.]({fig}/within_15.png){{.callout-figure}}

## Same scale, very different shapes

![Drive time to the nearest A&E, each city at the same scale.]({fig}/six_capitals.png){{.callout-figure}}

The number of emergency departments is only part of the story. {c[per_h[0]]['name']} has one for every {c[per_h[0]]['people_per_hospital'] / 1e3:.0f},000 people in its urban centre and {c[per_h[-1]]['name']} one for every {c[per_h[-1]]['people_per_hospital'] / 1e3:.0f},000, but what decides the wait is where they sit relative to where people live, and how the roads connect them.

## What this doesn't tell you

- **These are journeys to hospital, not ambulance response times.** Ambulances on blue lights are faster; most people with a sprained ankle drive or take a taxi.
- **Not every emergency department treats everything.** Major trauma, stroke and heart attack care is concentrated in fewer specialist centres.
- **Registers differ.** Each country defines "emergency care" a little differently, and London's list comes from OpenStreetMap.
- **Traffic is a single factor.** Real congestion varies by street and by hour.

## Then and now

My pedestrian safety project measured drive times to London's four major trauma centres. This time the same method runs on six capitals with one command each, using open data from three different sources, and turns the results into an animation as well as a table.

As before, I worked with an AI assistant, Claude. The questions, the choice of a fair city definition and the judgement about what the numbers mean are mine. Everything was tested on a made-up city with known answers before it ran on real ones.

- **Watch the race:** [{SITE.replace("https://", "")}/race-to-ae]({SITE}/race-to-ae/)
- **Code and method:** [github.com/{REPO}](https://github.com/{REPO})

---

*Data: © OpenStreetMap contributors (ODbL); European Commission JRC, Global Human Settlement Layer GHS-POP R2023A; Eurostat GISCO healthcare services. Drive times assume free-flowing traffic at typical urban speeds.*
'''


def main():
    h = read_json(need(RESULTS / "headline.json", "05_summarise.py"))
    out = RESULTS / "post" / "index.qmd"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(article(h), encoding="utf-8")
    log(f"Draft saved to {out}. Read it through before publishing.")


if __name__ == "__main__":
    main()
