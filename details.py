"""Per-golfer leaderboard details (position, holes played, today's round) for the website.

Saved next to each results file as <slug>_<year>_details.json, keyed by the golfer name as it
appears in the results file:  {"Scottie Scheffler": {"pos": "T2", "thru": "14", "today": "-4"}}
The results file itself is unchanged, so scoring, payouts and season standings don't depend on it.

Backfill final positions for past majors (uses the ESPN event ids in winners.json):
    python3 details.py 2024 2025 2026
"""
import argparse
import json
import os
import re
import unicodedata
from datetime import datetime

import payouts
import season_standings as ss

SKIP_KEYS = ("TEAM", "TOP_3_SCORE")


def norm(name):
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.replace("ø", "o").replace("Ø", "o").replace("æ", "ae")
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def details_path(results_path):
    return re.sub(r"_results\.txt$", "_details.json", results_path)


def _tee_time(value):
    """ESPN tee times are ISO UTC; show them in this machine's local time, e.g. '1:45 PM'."""
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
        return f"{t:%-I:%M %p}"
    except (ValueError, AttributeError):
        return None


def from_competitor(c):
    """Position / thru / today for one ESPN competitor. Missing pieces are left out."""
    st = c.get("status", {}) or {}
    typ = st.get("type", {}) or {}
    out = {}
    pos = (st.get("position") or {}).get("displayName")
    if pos and pos != "-":
        out["pos"] = pos
    state = typ.get("state")
    hole = st.get("hole")
    if state == "in":
        out["thru"] = "F" if hole == 18 else str(hole) if hole else (typ.get("shortDetail") or "")
    elif state == "pre":
        tee = _tee_time(st.get("teeTime")) if st.get("teeTime") else None
        out["thru"] = tee or typ.get("shortDetail") or ""
    elif typ.get("name") == "STATUS_FINISH" or st.get("displayValue") == "F":
        out["thru"] = "F"
    period = st.get("period")
    for ls in c.get("linescores") or []:
        if ls.get("period") == period and ls.get("displayValue") not in (None, "", "-"):
            out["today"] = ls["displayValue"]
    if not out.get("thru"):
        out.pop("thru", None)
    return out


def from_event(event):
    """{normalized name: details} for every golfer in an ESPN leaderboard event."""
    comps = event["competitions"][0].get("competitors", [])
    return {norm(c["athlete"]["displayName"]): from_competitor(c) for c in comps}


def write(results_path, event):
    """Write the details file for the golfers picked in this results file."""
    with open(results_path, encoding="utf-8") as f:
        teams = json.load(f)
    by_name = from_event(event)
    final = bool(event.get("status", {}).get("type", {}).get("completed"))
    out = {}
    for t in teams:
        for name in t:
            if name in SKIP_KEYS:
                continue
            d = by_name.get(norm(name))
            if d is not None:
                # Once the tournament is over only the finishing position matters
                out[name] = {"pos": d["pos"]} if final and "pos" in d else ({} if final else d)
    path = details_path(results_path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return path


def load(results_path):
    try:
        with open(details_path(results_path), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def backfill(year):
    winners = payouts.load_winners(year)
    for slug, path in ss.find_majors(year):
        event_id = (winners.get(slug) or {}).get("event_id")
        if not event_id:
            print(f"  {year} {slug}: no ESPN event id in winners.json - skipped")
            continue
        event = payouts._get_json(payouts.ESPN_LEADERBOARD.format(id=event_id))["events"][0]
        out = write(path, event)
        with open(out, encoding="utf-8") as f:
            n = len(json.load(f))
        print(f"  {year} {slug}: {n} golfers -> {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill golfer positions for past majors")
    parser.add_argument("years", nargs="+")
    for y in parser.parse_args().years:
        backfill(y)
