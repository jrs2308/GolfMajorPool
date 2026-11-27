"""Render a pool results file (JSON list of teams) to a readable PNG or PDF standings sheet.

Usage:
    python3 render_results.py results/2026/masters_2026_results.txt            # -> .png next to it
    python3 render_results.py results/2026/masters_2026_results.txt --pdf      # -> .pdf
    python3 render_results.py results/2026/*.txt --pdf --png                   # both, many files
"""
import argparse
import json
import os
import re
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle

# Must match the pool rules in golf-majors-pool.py
COUNTING_GOLFERS = 3
CUT_PENALTY = 15
OUT_MARKS = {"CUT", "WD", "DQ", "MC", "DNS"}
SCORE_KEY = "TOP_3_SCORE"

EVENT_TITLES = {
    "masters": "The Masters",
    "pga_championship": "PGA Championship",
    "us_open": "U.S. Open",
    "open_championship": "The Open Championship",
    "the_open": "The Open Championship",
}

# Palette
GREEN = "#1f5135"
GREEN_LIGHT = "#e8f1ea"
GOLD = "#c9a227"
SILVER = "#9aa3ab"
BRONZE = "#b0723f"
MEDALS = {1: GOLD, 2: SILVER, 3: BRONZE}
INK = "#1d2420"
MUTED = "#7b857f"
UNDER = "#c0392b"      # golf convention: under par in red
ROW_ALT = "#f7f8f6"
CARD = "#ffffff"
BG = "#eef1ec"
CUT_BG = "#eceeed"


def parse_score(text):
    text = (text or "").strip().upper()
    if text in OUT_MARKS:
        return CUT_PENALTY
    if text == "E":
        return 0
    try:
        return int(text)
    except ValueError:
        return None  # N/F, N/A, unknown


def over_under_par(score):
    return "E" if score == 0 else (f"+{score}" if score > 0 else str(score))


def golfer_scores(team):
    """Team's golfer scores best-first (cut = CUT_PENALTY), for the tiebreaker."""
    scores = [parse_score(v) for k, v in team.items() if k not in ("TEAM", SCORE_KEY)]
    return tuple(sorted(s for s in scores if s is not None))


def sort_value(team):
    """Ranking key: team total, then tiebreaker = best golfer score, then next best, ...
    N/A teams all tie for last (no tiebreaker)."""
    v = parse_score(team.get(SCORE_KEY))
    if v is None:
        return (True, 0, ())
    return (False, v, golfer_scores(team))


def title_from_filename(path):
    base = os.path.basename(path)
    m = re.match(r"(.+?)_(\d{4})_results", base)
    if not m:
        return os.path.splitext(base)[0].replace("_", " ").title(), ""
    slug, year = m.groups()
    return EVENT_TITLES.get(slug, slug.replace("_", " ").title()), year


def counting_indices(scores):
    """Indices of the golfers whose scores make up the team total (lowest N)."""
    valid = [(s, i) for i, s in enumerate(scores) if s is not None]
    if len(valid) < COUNTING_GOLFERS:
        return set()
    return {i for _, i in sorted(valid)[:COUNTING_GOLFERS]}


def totals_match_rules(teams):
    """True if every team total in the file equals best-N-with-cut-penalty under current rules."""
    for t in teams:
        total = parse_score(t.get(SCORE_KEY))
        if total is None:
            continue
        scores = [parse_score(v) for k, v in t.items() if k not in ("TEAM", SCORE_KEY)]
        idx = counting_indices(scores)
        if sum(scores[i] for i in idx) != total:
            return False
    return True


def score_color(text):
    v = parse_score(text)
    if (text or "").upper() in OUT_MARKS or v is None:
        return MUTED
    return UNDER if v < 0 else INK


def ranks(teams):
    """Standard competition ranking with ties shown as T2 etc."""
    out, prev, prev_rank = [], None, 0
    values = [sort_value(t) for t in teams]
    for i, val in enumerate(values):
        if val[0]:
            out.append("-")
            continue
        rank = prev_rank if val == prev else i + 1
        tied = values.count(val) > 1
        out.append(f"T{rank}" if tied else str(rank))
        prev, prev_rank = val, rank
    return out


def render(results_path, out_paths, updated=None):
    with open(results_path, encoding="utf-8") as f:
        teams = json.load(f)
    teams = sorted(teams, key=sort_value)
    rank_labels = ranks(teams)
    event, year = title_from_filename(results_path)
    updated = updated or datetime.fromtimestamp(os.path.getmtime(results_path))

    # Layout in "pixel" units; figure is W x H at 1 unit = 1px @ dpi 100
    W = 1400
    header_h, row_h, gap, pad, footer_h = 150, 118, 12, 40, 50
    H = header_h + pad + len(teams) * (row_h + gap) + footer_h

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")

    # Header band
    ax.add_patch(plt.Rectangle((0, 0), W, header_h, color=GREEN, zorder=1))
    ax.add_patch(plt.Rectangle((0, header_h - 6), W, 6, color=GOLD, zorder=2))
    ax.text(pad, 62, f"{event} {year}".strip(), color="white", fontsize=34,
            fontweight="bold", va="center", zorder=3)
    picks = max((len(t) - 2 for t in teams), default=6)
    subtitle = f"MAJORS POOL STANDINGS  ·  best {COUNTING_GOLFERS} of {picks} count"
    if totals_match_rules(teams):  # older files used different cut rules - don't mislabel them
        subtitle += f"  ·  cut = +{CUT_PENALTY}"
    ax.text(pad, 112, subtitle,
            color="#cfe0d4", fontsize=13, va="center", zorder=3)
    ax.text(W - pad, 62, "Leader", color="#cfe0d4", fontsize=13, ha="right", va="center", zorder=3)
    if teams and rank_labels[0] != "-":
        leaders = [t["TEAM"] for t, r in zip(teams, rank_labels) if r == rank_labels[0]]
        ax.text(W - pad, 104, f"{' & '.join(leaders)}  {teams[0][SCORE_KEY]}", color="white",
                fontsize=22, fontweight="bold", ha="right", va="center", zorder=3)

    left_w = 330                      # rank + team + total column
    grid_x = pad + left_w
    grid_w = W - pad - grid_x - 16
    cols = 3
    cell_w = grid_w / cols
    cell_h = (row_h - 24) / 2

    y = header_h + pad
    for idx, (team, rank) in enumerate(zip(teams, rank_labels)):
        golfers = [(k, v) for k, v in team.items() if k not in ("TEAM", SCORE_KEY)]
        scores = [parse_score(v) for _, v in golfers]
        counting = counting_indices(scores) if team.get(SCORE_KEY) != "N/A" else set()
        place = int(rank.lstrip("T")) if rank != "-" else None
        medal = MEDALS.get(place)  # ties share the medal (e.g. T2 = silver)

        # Card
        ax.add_patch(FancyBboxPatch((pad, y), W - 2 * pad, row_h,
                                    boxstyle="round,pad=0,rounding_size=14",
                                    fc=CARD, ec=medal or "#d9dfd9",
                                    lw=2.5 if medal else 1, zorder=1))

        # Rank badge
        cx, cy = pad + 46, y + row_h / 2
        ax.add_patch(Circle((cx, cy), 28, color=medal or GREEN, zorder=2))
        ax.text(cx, cy, rank, color="white", fontsize=17 if len(rank) < 3 else 14,
                fontweight="bold", ha="center", va="center", zorder=3)

        # Team + total
        ax.text(pad + 92, cy - 18, team["TEAM"], color=INK, fontsize=21,
                fontweight="bold", va="center", zorder=3)
        total = team.get(SCORE_KEY, "")
        total_text = ax.text(pad + 92, cy + 22, total,
                             color=score_color(total) if total != "N/A" else MUTED,
                             fontsize=24, fontweight="bold", va="center", zorder=3)
        total_w = total_text.get_window_extent(renderer=fig.canvas.get_renderer()).width
        same_total = [t for t in teams if t is not team and total != "N/A"
                      and t.get(SCORE_KEY) == total]
        if same_total and team.get(SCORE_KEY) != "N/A":
            best = golfer_scores(team)[0]
            ax.text(pad + 92 + total_w + 14, cy + 24, f"tiebreak: best {over_under_par(best)}",
                    color=MUTED, fontsize=11, va="center", zorder=3)
        else:
            ax.text(pad + 92 + total_w + 14, cy + 24, "team total", color=MUTED,
                    fontsize=11, va="center", zorder=3)

        # Golfer grid (2 rows x 3 cols)
        for gi, (name, val) in enumerate(golfers[:6]):
            r, c = divmod(gi, cols)
            gx = grid_x + c * cell_w + 6
            gy = y + 12 + r * cell_h + 4
            is_out = (val or "").upper() in OUT_MARKS
            counts = gi in counting
            fc = GREEN_LIGHT if counts else (CUT_BG if is_out else ROW_ALT)
            ax.add_patch(FancyBboxPatch((gx, gy), cell_w - 12, cell_h - 8,
                                        boxstyle="round,pad=0,rounding_size=8", fc=fc,
                                        ec=GREEN if counts else "none", lw=1.4, zorder=2))
            ax.text(gx + 14, gy + (cell_h - 8) / 2, name, fontsize=13.5, va="center",
                    color=MUTED if is_out else INK,
                    fontweight="bold" if counts else "normal", zorder=3)
            ax.text(gx + cell_w - 26, gy + (cell_h - 8) / 2, val, fontsize=14.5,
                    ha="right", va="center", color=score_color(val),
                    fontweight="bold", zorder=3)
        y += row_h + gap

    # Footer / legend
    fy = H - footer_h / 2 - 4
    ax.add_patch(FancyBboxPatch((pad, fy - 9), 30, 18, boxstyle="round,pad=0,rounding_size=4",
                                fc=GREEN_LIGHT, ec=GREEN, lw=1.4))
    ax.text(pad + 40, fy, "counts toward team total", fontsize=11, color=MUTED, va="center")
    ax.text(pad + 270, fy, "red = under par", fontsize=11, color=UNDER, va="center")
    # A file stamped exactly midnight has a known date but no known time - show the date only
    stamp = (f"{updated:%b %-d, %Y}" if (updated.hour, updated.minute) == (0, 0)
             else f"{updated:%b %-d, %Y %-I:%M %p}")
    ax.text(W - pad, fy, f"Updated {stamp}", fontsize=11,
            color=MUTED, ha="right", va="center")

    for out in out_paths:
        fig.savefig(out, dpi=150 if out.endswith(".png") else 100, facecolor=BG)
    plt.close(fig)
    return out_paths


def main():
    parser = argparse.ArgumentParser(description="Render pool results to PNG/PDF")
    parser.add_argument("files", nargs="+", help="results .txt (JSON) files")
    parser.add_argument("--png", action="store_true", help="write a .png (default if no format given)")
    parser.add_argument("--pdf", action="store_true", help="write a .pdf")
    args = parser.parse_args()
    exts = [e for e, on in ((".png", args.png), (".pdf", args.pdf)) if on] or [".png"]
    for path in args.files:
        outs = [os.path.splitext(path)[0] + e for e in exts]
        render(path, outs)
        for o in outs:
            print(f"Wrote {o}")


if __name__ == "__main__":
    main()
