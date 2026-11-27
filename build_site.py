"""Build the pool website (docs/index.html) from results/<year>/ for GitHub Pages.

One self-contained page: a tab per year, and inside each year the major leaderboards,
winners, payouts and season standings. Uses the same scoring/payout logic as the PNGs.

Usage:
    python3 build_site.py            # every year in results/ -> docs/index.html
    open docs/index.html             # preview locally
"""
import glob
import json
import os
from datetime import datetime

import details
import payouts
import render_results as rr
import season_standings as ss

SITE_DIR = "docs"            # GitHub Pages: serve from /docs on main
TEMPLATE = "site_template.html"


def years():
    found = [os.path.basename(p) for p in glob.glob(os.path.join(ss.RESULTS_DIR, "*"))
             if os.path.basename(p).isdigit() and ss.find_majors(os.path.basename(p))]
    return sorted(found, reverse=True)


def leaderboard(path, winner):
    extra = details.load(path)
    with open(path, encoding="utf-8") as f:
        teams = sorted(json.load(f), key=rr.sort_value)
    labels = rr.ranks(teams)
    out = []
    for team, rank in zip(teams, labels):
        golfers = [(k, v) for k, v in team.items() if k not in ("TEAM", rr.SCORE_KEY)]
        total = team.get(rr.SCORE_KEY, "")
        counting = rr.counting_indices([rr.parse_score(v) for _, v in golfers]) if total != "N/A" else set()
        tied = total != "N/A" and sum(1 for t in teams if t.get(rr.SCORE_KEY) == total) > 1
        out.append({
            "team": ss.TEAM_ALIASES.get(team["TEAM"], team["TEAM"]),
            "rank": rank,
            "total": total,
            "tiebreak": rr.over_under_par(rr.golfer_scores(team)[0]) if tied else None,
            "golfers": [{
                "name": name,
                "score": val,
                "counts": i in counting,
                "out": (val or "").upper() in rr.OUT_MARKS,
                "champ": bool(winner) and payouts._norm(name) == payouts._norm(winner),
                **{k: v for k, v in extra.get(name, {}).items() if k in ("pos", "thru", "today")},
            } for i, (name, val) in enumerate(golfers)],
        })
    return out


def year_data(year):
    winners = payouts.load_winners(year)
    pay_majors, pay_rows = payouts.compute(year)
    pay_by_slug = {slug: (p, final) for slug, p, final in pay_majors}
    slugs, season_rows, season_updated = ss.compute(year)

    majors = []
    for slug, path in ss.find_majors(year):
        info = winners.get(slug)
        p, final = pay_by_slug[slug]
        majors.append({
            "slug": slug,
            "name": rr.EVENT_TITLES.get(slug, slug.replace("_", " ").title()),
            "short": ss.SHORT_NAMES.get(slug, slug),
            "final": final,
            "updated": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="minutes"),
            "winner": info["winner"] if info else None,
            "teams": leaderboard(path, info["winner"] if info else None),
            "payout": {
                "pot": p["pot"], "low_teams": p["low_teams"], "owner": p["owner"],
                "won": {t: a for t, a in p["won"].items() if a},
            },
        })
    return {
        "year": year,
        "majors": majors,
        "season": {
            "majors": [ss.SHORT_NAMES.get(s, s) for s in slugs],
            "final": [s in ss.final_slugs(year) for s in slugs],
            "complete": len(slugs) >= 4 and set(slugs) <= ss.final_slugs(year),
            "rows": [{"team": r["team"], "rank": r["rank"], "place": r["place"],
                      "total": r["total"], "wins": r["wins"],
                      "cells": [list(c) if c else None for c in r["cells"]]} for r in season_rows],
        },
        "payouts": [{"team": r["team"], "paid": r["paid"], "won": r["won"], "net": r["net"]}
                    for r in pay_rows],
    }


def build(out_dir=SITE_DIR):
    data = {
        "buyIn": payouts.BUY_IN,
        "counting": rr.COUNTING_GOLFERS,
        "cutPenalty": rr.CUT_PENALTY,
        "built": datetime.now().isoformat(timespec="minutes"),
        "years": [year_data(y) for y in years()],
    }
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, TEMPLATE), encoding="utf-8") as f:
        html = f.read()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", payload)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    # Tell GitHub Pages not to run Jekyll on the folder
    open(os.path.join(out_dir, ".nojekyll"), "w").close()
    return out_path


if __name__ == "__main__":
    print("Wrote", build())
