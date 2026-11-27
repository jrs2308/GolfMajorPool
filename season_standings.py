"""Season standings across the majors: points by finish in each major.

Scoring: in a major with N teams, 1st = N points ... last = 1 point. Tied teams split the
points for the places they occupy. N/A teams (too many cuts) tie for last place.
A team that didn't play a major gets 0 points for it.

Usage:
    python3 season_standings.py 2026            # -> results/2026/season_2026_standings.png
    python3 season_standings.py 2024 2025 2026
"""
import argparse
import glob
import json
import os
import re
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyBboxPatch

import render_results as rr

RESULTS_DIR = "results"
MAJOR_ORDER = ["masters", "pga_championship", "us_open", "open_championship", "the_open"]
SHORT_NAMES = {
    "masters": "Masters",
    "pga_championship": "PGA",
    "us_open": "U.S. Open",
    "open_championship": "The Open",
    "the_open": "The Open",
}
GOLD_TINT = "#f7efd2"

# Older results files used different spellings for the same team
TEAM_ALIASES = {"Brett C": "Brett", "Bret N": "Bret"}


def find_majors(year):
    """Results files for a year, in calendar order. Returns [(slug, path)]."""
    majors = []
    for path in glob.glob(os.path.join(RESULTS_DIR, str(year), "*_results.txt")):
        m = re.match(r"(.+?)_(\d{4})_results\.txt$", os.path.basename(path))
        if m and m.group(2) == str(year):
            majors.append((m.group(1), path))
    order = {slug: i for i, slug in enumerate(MAJOR_ORDER)}
    return sorted(majors, key=lambda sp: (order.get(sp[0], 99), os.path.getmtime(sp[1])))


def major_points(teams):
    """Points and place for each team in one major. Returns {team: (points, place_label)}."""
    ordered = sorted(teams, key=rr.sort_value)
    n = len(ordered)
    out, i = {}, 0
    while i < n:
        val = rr.sort_value(ordered[i])
        j = i
        while j < n and rr.sort_value(ordered[j]) == val:
            j += 1
        # places i+1 .. j share the points for those places
        pts = sum(n - p for p in range(i, j)) / (j - i)
        label = ("T" if j - i > 1 else "") + str(i + 1)
        for t in ordered[i:j]:
            out[TEAM_ALIASES.get(t["TEAM"], t["TEAM"])] = (pts, label)
        i = j
    return out


def compute(year):
    majors = find_majors(year)
    if not majors:
        raise FileNotFoundError(f"No results files in {RESULTS_DIR}/{year}/")
    per_major = []  # [(slug, {team: (pts, label)})]
    for slug, path in majors:
        with open(path, encoding="utf-8") as f:
            per_major.append((slug, major_points(json.load(f))))

    teams = sorted({t for _, res in per_major for t in res})
    rows = []
    for team in teams:
        cells = [res.get(team) for _, res in per_major]
        total = sum(c[0] for c in cells if c)
        wins = sum(1 for c in cells if c and c[1] == "1")
        rows.append({"team": team, "cells": cells, "total": total, "wins": wins})
    # Rank by points; tiebreaker = most outright major wins; still tied -> share the place
    key = lambda r: (-r["total"], -r["wins"])
    rows.sort(key=key)
    for i, r in enumerate(rows):
        first = next(k for k, o in enumerate(rows) if key(o) == key(r))
        tied = sum(1 for o in rows if key(o) == key(r)) > 1
        r["place"] = first + 1
        r["rank"] = ("T" if tied else "") + str(first + 1)
    updated = datetime.fromtimestamp(max(os.path.getmtime(p) for _, p in majors))
    return [slug for slug, _ in per_major], rows, updated


def fmt_pts(p):
    return str(int(p)) if float(p).is_integer() else f"{p:.1f}"


def render(year, out_path):
    slugs, rows, updated = compute(year)

    W = 1400
    header_h, colhead_h, row_h, gap, pad, footer_h = 150, 44, 92, 10, 40, 56
    H = header_h + pad + colhead_h + len(rows) * (row_h + gap) + footer_h

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(rr.BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")

    # Header
    ax.add_patch(plt.Rectangle((0, 0), W, header_h, color=rr.GREEN, zorder=1))
    ax.add_patch(plt.Rectangle((0, header_h - 6), W, 6, color=rr.GOLD, zorder=2))
    ax.text(pad, 62, f"{year} Season Standings", color="white", fontsize=34,
            fontweight="bold", va="center", zorder=3)
    played = f"{len(slugs)} of 4 majors" if len(slugs) < 4 else "all 4 majors"
    ax.text(pad, 112, f"MAJORS POOL  ·  points by finish  ·  {played}", color="#cfe0d4",
            fontsize=13, va="center", zorder=3)
    leaders = [r["team"] for r in rows if r["place"] == 1]
    ax.text(W - pad, 62, "Season leader" if len(slugs) < 4 else "Season champion",
            color="#cfe0d4", fontsize=13, ha="right", va="center", zorder=3)
    ax.text(W - pad, 104, f"{' & '.join(leaders)}  {fmt_pts(rows[0]['total'])} pts",
            color="white", fontsize=22, fontweight="bold", ha="right", va="center", zorder=3)

    # Columns
    team_x = pad + 92
    total_x = W - pad - 40
    majors_left, majors_right = 470, W - pad - 190
    col_w = (majors_right - majors_left) / max(len(slugs), 1)
    col_cx = [majors_left + col_w * (i + 0.5) for i in range(len(slugs))]

    y = header_h + pad
    for cx, slug in zip(col_cx, slugs):
        ax.text(cx, y + colhead_h / 2, SHORT_NAMES.get(slug, slug.replace("_", " ").title()).upper(),
                fontsize=12, color=rr.MUTED, fontweight="bold", ha="center", va="center")
    ax.text(total_x, y + colhead_h / 2, "POINTS", fontsize=12, color=rr.MUTED,
            fontweight="bold", ha="right", va="center")
    ax.text(team_x, y + colhead_h / 2, "TEAM", fontsize=12, color=rr.MUTED,
            fontweight="bold", va="center")
    y += colhead_h

    for r in rows:
        medal = rr.MEDALS.get(r["place"])
        ax.add_patch(FancyBboxPatch((pad, y), W - 2 * pad, row_h,
                                    boxstyle="round,pad=0,rounding_size=14", fc=rr.CARD,
                                    ec=medal or "#d9dfd9", lw=2.5 if medal else 1, zorder=1))
        cy = y + row_h / 2
        ax.add_patch(Circle((pad + 46, cy), 26, color=medal or rr.GREEN, zorder=2))
        ax.text(pad + 46, cy, r["rank"], color="white", fontsize=16 if len(r["rank"]) < 3 else 13,
                fontweight="bold", ha="center", va="center", zorder=3)
        ax.text(team_x, cy - 10, r["team"], color=rr.INK, fontsize=21, fontweight="bold",
                va="center", zorder=3)
        if r["wins"]:
            ax.text(team_x, cy + 22, f"{r['wins']} major win{'s' if r['wins'] > 1 else ''}",
                    color=rr.GOLD, fontsize=11, fontweight="bold", va="center", zorder=3)

        for cx, cell in zip(col_cx, r["cells"]):
            if cell is None:
                ax.text(cx, cy, "—", fontsize=16, color=rr.MUTED, ha="center", va="center")
                continue
            pts, place = cell
            if place == "1":
                ax.add_patch(FancyBboxPatch((cx - col_w / 2 + 10, y + 10), col_w - 20, row_h - 20,
                                            boxstyle="round,pad=0,rounding_size=8",
                                            fc=GOLD_TINT, ec="none", zorder=2))
            ax.text(cx, cy - 10, fmt_pts(pts), fontsize=19, fontweight="bold", color=rr.INK,
                    ha="center", va="center", zorder=3)
            ax.text(cx, cy + 20, ordinal(place), fontsize=11, color=rr.MUTED,
                    ha="center", va="center", zorder=3)

        ax.text(total_x, cy, fmt_pts(r["total"]), fontsize=26, fontweight="bold",
                color=rr.GREEN, ha="right", va="center", zorder=3)
        y += row_h + gap

    fy = H - footer_h / 2 - 4
    ax.text(pad, fy, "Each major: last = 1 pt, +1 per place  ·  ties split points  ·  "
            "N/A = tied for last  ·  gold = major winner  ·  season tiebreak: most wins",
            fontsize=11, color=rr.MUTED, va="center")
    ax.text(W - pad, fy, f"Updated {updated:%b %-d, %Y}", fontsize=11, color=rr.MUTED,
            ha="right", va="center")

    fig.savefig(out_path, dpi=150, facecolor=rr.BG)
    plt.close(fig)
    return out_path


def ordinal(place):
    tie = place.startswith("T")
    n = int(place.lstrip("T"))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{'T' if tie else ''}{n}{suffix}"


def output_path(year):
    return os.path.join(RESULTS_DIR, str(year), f"season_{year}_standings.png")


def main():
    parser = argparse.ArgumentParser(description="Render season standings")
    parser.add_argument("years", nargs="+")
    args = parser.parse_args()
    for year in args.years:
        slugs, rows, _ = compute(year)
        print(f"\n{year} season ({', '.join(SHORT_NAMES.get(s, s) for s in slugs)})")
        for r in rows:
            cells = "  ".join(f"{fmt_pts(c[0]):>4} ({c[1]:>3})" if c else "   —      "
                              for c in r["cells"])
            print(f"  {r['rank']:>3}  {r['team']:<8} {cells}   = {fmt_pts(r['total'])}")
        print("Wrote", render(year, output_path(year)))


if __name__ == "__main__":
    main()
