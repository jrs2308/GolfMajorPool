"""Pool payouts per major and season net, rendered as a PNG.

Rules (per major):
  - Every team buys in for $10, so the pot is $10 x number of teams.
  - The team that drafted the tournament's winning golfer gets its $10 back.
  - The team with the lowest combined score (tiebreak: lowest-scoring golfer) gets the rest.
  - If that team also has the winning golfer, it takes the whole pot.

Tournament winners are stored in results/<year>/winners.json (filled by golf-majors-pool.py
when a tournament goes final, or backfilled with --fetch-winners).

Usage:
    python3 payouts.py 2026                      # -> results/2026/payouts_2026.png
    python3 payouts.py 2024 2025 2026 --fetch-winners
"""
import argparse
import json
import os
import ssl
import urllib.request
from datetime import datetime

import certifi
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

import render_results as rr
import season_standings as ss

BUY_IN = 10
ESPN_CALENDAR = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard?dates={year}"
ESPN_LEADERBOARD = "https://site.web.api.espn.com/apis/site/v2/sports/golf/leaderboard?event={id}"
ESPN_MAJOR_LABELS = {
    "Masters Tournament": "masters",
    "PGA Championship": "pga_championship",
    "U.S. Open": "us_open",
    "The Open": "open_championship",
}


# ---------- winners.json ----------

def winners_path(year):
    return os.path.join(ss.RESULTS_DIR, str(year), "winners.json")


def load_winners(year):
    try:
        with open(winners_path(year), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_winner(year, slug, winner, event_id=None):
    winners = load_winners(year)
    winners[slug] = {"winner": winner, "event_id": event_id}
    os.makedirs(os.path.dirname(winners_path(year)), exist_ok=True)
    with open(winners_path(year), "w", encoding="utf-8") as f:
        json.dump(winners, f, ensure_ascii=False, indent=4)


def _get_json(url):
    ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def winner_from_event(event):
    """Name of the tournament winner from an ESPN leaderboard event, or None if not final."""
    if not event.get("status", {}).get("type", {}).get("completed"):
        return None
    for c in event["competitions"][0].get("competitors", []):
        if c.get("status", {}).get("position", {}).get("displayName") == "1":
            return c["athlete"]["displayName"]
    return None


def fetch_winners(year):
    """Backfill winners.json for a year's majors from ESPN."""
    cal = _get_json(ESPN_CALENDAR.format(year=year))["leagues"][0]["calendar"]
    for entry in cal:
        slug = ESPN_MAJOR_LABELS.get(entry.get("label"))
        if not slug:
            continue
        event = _get_json(ESPN_LEADERBOARD.format(id=entry["id"]))["events"][0]
        winner = winner_from_event(event)
        if winner:
            save_winner(year, slug, winner, entry["id"])
            print(f"  {year} {slug}: {winner}")


# ---------- payout math ----------

def major_payout(teams, winner):
    """Returns dict with pot, pool winner(s), golfer-winner owner, and {team: amount won}."""
    pot = BUY_IN * len(teams)
    ordered = sorted(teams, key=rr.sort_value)
    best = rr.sort_value(ordered[0])
    low_teams = [t["TEAM"] for t in ordered if rr.sort_value(t) == best and not best[0]]

    owner = None
    if winner:
        for t in teams:
            if any(_norm(g) == _norm(winner) for g in t if g not in ("TEAM", rr.SCORE_KEY)):
                owner = t["TEAM"]
                break

    won = {t["TEAM"]: 0.0 for t in teams}
    refund = BUY_IN if owner else 0
    if owner:
        won[owner] += refund
    rest = pot - refund
    for name in low_teams:  # only splits if tiebreakers can't separate teams
        won[name] += rest / len(low_teams)
    return {"pot": pot, "low_teams": low_teams, "owner": owner, "winner": winner,
            "refund": refund, "rest": rest, "won": won}


def _norm(name):
    import re
    import unicodedata
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c)).replace("ø", "o")
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def compute(year):
    winners = load_winners(year)
    majors = []
    for slug, path in ss.find_majors(year):
        with open(path, encoding="utf-8") as f:
            teams = [{**t, "TEAM": ss.TEAM_ALIASES.get(t["TEAM"], t["TEAM"])} for t in json.load(f)]
        info = winners.get(slug)
        majors.append((slug, major_payout(teams, info["winner"] if info else None), info is not None))

    season = {}
    for slug, p, final in majors:
        for team, amount in p["won"].items():
            name = ss.TEAM_ALIASES.get(team, team)
            s = season.setdefault(name, {"paid": 0, "won": 0.0})
            s["paid"] += BUY_IN
            if final:
                s["won"] += amount
            else:  # tournament still in progress: buy-in is paid, nothing awarded yet
                pass
    rows = sorted(({"team": t, **v, "net": v["won"] - v["paid"]} for t, v in season.items()),
                  key=lambda r: (-r["net"], r["team"]))
    return majors, rows


def money(x, sign=False):
    s = f"${abs(x):,.2f}".replace(".00", "")
    if sign:
        return ("+" if x > 0 else "−" if x < 0 else "") + s
    return s


# ---------- rendering ----------

def render(year, out_path):
    majors, rows = compute(year)
    W, pad = 1400, 40
    header_h, sec_h, mrow_h, srow_h, gap, footer_h = 150, 56, 96, 64, 10, 56
    H = header_h + pad + sec_h + len(majors) * (mrow_h + gap) + 24 + sec_h + 40 \
        + len(rows) * (srow_h + 6) + footer_h

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(rr.BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")

    # Header
    ax.add_patch(plt.Rectangle((0, 0), W, header_h, color=rr.GREEN, zorder=1))
    ax.add_patch(plt.Rectangle((0, header_h - 6), W, 6, color=rr.GOLD, zorder=2))
    ax.text(pad, 62, f"{year} Payouts", color="white", fontsize=34, fontweight="bold",
            va="center", zorder=3)
    ax.text(pad, 112, f"MAJORS POOL  ·  ${BUY_IN} buy-in per major", color="#cfe0d4",
            fontsize=13, va="center", zorder=3)
    if rows:
        top = rows[0]
        ax.text(W - pad, 62, "Biggest winner", color="#cfe0d4", fontsize=13, ha="right",
                va="center", zorder=3)
        ax.text(W - pad, 104, f"{top['team']}  {money(top['net'], sign=True)}", color="white",
                fontsize=22, fontweight="bold", ha="right", va="center", zorder=3)

    # --- By major ---
    y = header_h + pad
    ax.text(pad, y + 22, "BY MAJOR", fontsize=13, color=rr.MUTED, fontweight="bold", va="center")
    col_low, col_gw, col_pot = pad + 300, pad + 760, W - pad - 30
    ax.text(col_low, y + 22, "LOWEST SCORE", fontsize=11, color=rr.MUTED, fontweight="bold", va="center")
    ax.text(col_gw, y + 22, "WINNING GOLFER", fontsize=11, color=rr.MUTED, fontweight="bold", va="center")
    ax.text(col_pot, y + 22, "POT", fontsize=11, color=rr.MUTED, fontweight="bold", ha="right", va="center")
    y += sec_h
    for slug, p, final in majors:
        ax.add_patch(FancyBboxPatch((pad, y), W - 2 * pad, mrow_h,
                                    boxstyle="round,pad=0,rounding_size=14", fc=rr.CARD,
                                    ec="#d9dfd9", lw=1, zorder=1))
        cy = y + mrow_h / 2
        ax.text(pad + 28, cy, ss.SHORT_NAMES.get(slug, slug), fontsize=20, fontweight="bold",
                color=rr.INK, va="center", zorder=3)
        if not final:
            ax.text(col_low, cy, "In progress — paid out when the tournament is final",
                    fontsize=14, color=rr.MUTED, va="center", zorder=3)
        else:
            low = " & ".join(p["low_teams"]) or "—"
            sweep = p["owner"] and p["owner"] in p["low_teams"] and len(p["low_teams"]) == 1
            low_amt = p["won"][p["low_teams"][0]] if p["low_teams"] else 0
            ax.text(col_low, cy - 14, low, fontsize=19, fontweight="bold", color=rr.INK,
                    va="center", zorder=3)
            ax.text(col_low, cy + 18, (f"{money(low_amt)} — sweep! (also had the winner)" if sweep
                                       else f"{money(low_amt)}" + (" each" if len(p["low_teams"]) > 1 else "")),
                    fontsize=13, color=rr.GOLD if sweep else rr.GREEN, fontweight="bold",
                    va="center", zorder=3)
            ax.text(col_gw, cy - 14, p["winner"], fontsize=16, color=rr.INK, va="center", zorder=3)
            if p["owner"] and not sweep:
                gw_note, gw_color = f"{p['owner']} gets ${BUY_IN} back", rr.GREEN
            elif sweep:
                gw_note, gw_color = f"{p['owner']} — included in sweep", rr.MUTED
            else:
                gw_note, gw_color = "not drafted — lowest score takes the pot", rr.MUTED
            ax.text(col_gw, cy + 18, gw_note, fontsize=13, color=gw_color, va="center", zorder=3)
        ax.text(col_pot, cy, money(p["pot"]), fontsize=20, fontweight="bold", color=rr.INK,
                ha="right", va="center", zorder=3)
        y += mrow_h + gap

    # --- Season net ---
    y += 24
    ax.text(pad, y + 22, "SEASON NET", fontsize=13, color=rr.MUTED, fontweight="bold", va="center")
    c_paid, c_won, c_net = W - pad - 420, W - pad - 230, W - pad - 30
    for x, label in ((c_paid, "PAID IN"), (c_won, "WON"), (c_net, "NET")):
        ax.text(x, y + 22, label, fontsize=11, color=rr.MUTED, fontweight="bold", ha="right", va="center")
    y += sec_h
    for r in rows:
        ax.add_patch(FancyBboxPatch((pad, y), W - 2 * pad, srow_h,
                                    boxstyle="round,pad=0,rounding_size=12", fc=rr.CARD,
                                    ec="#d9dfd9", lw=1, zorder=1))
        cy = y + srow_h / 2
        ax.text(pad + 28, cy, r["team"], fontsize=18, fontweight="bold", color=rr.INK,
                va="center", zorder=3)
        ax.text(c_paid, cy, money(r["paid"]), fontsize=16, color=rr.MUTED, ha="right", va="center", zorder=3)
        ax.text(c_won, cy, money(r["won"]), fontsize=16, color=rr.INK, ha="right", va="center", zorder=3)
        net_color = rr.GREEN if r["net"] > 0 else (rr.UNDER if r["net"] < 0 else rr.MUTED)
        ax.text(c_net, cy, money(r["net"], sign=True), fontsize=20, fontweight="bold",
                color=net_color, ha="right", va="center", zorder=3)
        y += srow_h + 6

    fy = H - footer_h / 2 - 4
    ax.text(pad, fy, f"Winning golfer's team gets ${BUY_IN} back  ·  lowest combined score gets the rest "
            "(tiebreak: lowest-scoring golfer)  ·  both = whole pot", fontsize=11, color=rr.MUTED, va="center")
    ax.text(W - pad, fy, f"Updated {datetime.now():%b %-d, %Y}", fontsize=11, color=rr.MUTED,
            ha="right", va="center")

    fig.savefig(out_path, dpi=150, facecolor=rr.BG)
    plt.close(fig)
    return out_path


def output_path(year):
    return os.path.join(ss.RESULTS_DIR, str(year), f"payouts_{year}.png")


def main():
    parser = argparse.ArgumentParser(description="Render pool payouts")
    parser.add_argument("years", nargs="+")
    parser.add_argument("--fetch-winners", action="store_true",
                        help="look up each major's winning golfer from ESPN first")
    args = parser.parse_args()
    for year in args.years:
        if args.fetch_winners:
            fetch_winners(year)
        majors, rows = compute(year)
        print(f"\n{year} payouts")
        for slug, p, final in majors:
            if not final:
                print(f"  {slug:<18} in progress (no winner recorded)")
                continue
            print(f"  {slug:<18} pot {money(p['pot'])}  winner {p['winner']} -> {p['owner'] or 'nobody'}"
                  f"   lowest {' & '.join(p['low_teams'])}   payouts "
                  + ", ".join(f"{t} {money(a)}" for t, a in p["won"].items() if a))
        for r in rows:
            print(f"    {r['team']:<8} paid {money(r['paid']):>5}  won {money(r['won']):>7}  net {money(r['net'], sign=True)}")
        print("Wrote", render(year, output_path(year)))


if __name__ == "__main__":
    main()
