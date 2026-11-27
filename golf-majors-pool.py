import argparse
import csv
import glob
import json
import os
import re
import shutil
import ssl
import sys
import time
import traceback
import unicodedata
import urllib.request
from datetime import datetime

import certifi

import render_results
import payouts
import season_standings

# ESPN's JSON leaderboard feed. With no event id it returns the current event(s).
LEADERBOARD_API = "https://site.web.api.espn.com/apis/site/v2/sports/golf/leaderboard"
# Google Drive desktop syncs this local folder; files copied here upload automatically.
DRIVE_FOLDER_GLOB = "~/Library/CloudStorage/GoogleDrive-*/My Drive/GolfMajorPool"
PICKS_FILE = "picks.csv"
RESULTS_DIR = "results"  # results are saved to results/<year>/ (and <drive folder>/<year>/)
PICK_COLUMNS = ["p1", "p2", "p3", "p4", "p5", "p6"]

# Pool rules
COUNTING_GOLFERS = 3     # best N scores count
CUT_PENALTY = 15         # score used for a cut golfer when ranking a team's best N
MAX_CUT_PLAYERS = 3      # a team with more cut golfers than this scores N/A

# Golfer statuses that count as missing the weekend
OUT_STATUSES = {"CUT", "WD", "DQ", "MC", "DNS"}

RETRY_DELAY = 300        # seconds to wait after a failed update


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def normalize_name(name):
    """Lowercase, strip accents and punctuation so 'Ludvig Åberg' == 'Ludvig Aberg'."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.replace("ø", "o").replace("Ø", "o").replace("æ", "ae")
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def load_entries():
    with open(PICKS_FILE, encoding="utf-8-sig") as csvfile:
        return [row for row in csv.DictReader(csvfile) if row.get("TEAM", "").strip()]


def fetch_leaderboard(event_id=None):
    url = LEADERBOARD_API + (f"?event={event_id}" if event_id else "")
    # This Python install has no system CA store, so verify against certifi's bundle
    context = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=context, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_to_par(value):
    """'-5' -> -5, '+3' -> 3, 'E' -> 0, anything else (e.g. '-' before tee off) -> 0."""
    value = (value or "").strip()
    if value == "E":
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def transform_leaderboard(data):
    """Returns (event, golfers) where golfers maps normalized name -> golfer info."""
    events = data.get("events") or []
    if not events:
        raise RuntimeError("ESPN returned no events")
    event = events[0]
    competitors = event["competitions"][0].get("competitors", [])

    golfers = {}
    for c in competitors:
        status = c.get("status", {})
        status_type = status.get("type", {})
        short = (status_type.get("shortDetail") or status.get("displayValue") or "").upper()
        name_code = status_type.get("name", "").upper()
        is_out = short in OUT_STATUSES or any(
            s in name_code for s in ("CUT", "WITHDRAW", "DISQUAL"))
        score = c.get("score")
        if isinstance(score, dict):
            score = score.get("displayValue")
        name = c["athlete"]["displayName"]
        golfers[normalize_name(name)] = {
            "name": name,
            "topar": parse_to_par(score),
            "out": is_out,
            "status": short if is_out else "",
        }
    return event, golfers


def over_under_par(score):
    if score == 0:
        return "E"
    return f"+{score}" if score > 0 else str(score)


def score_entries(entries, golfers):
    """Builds the results list. Returns (results, picks not found on the leaderboard)."""
    results = []
    missing = set()
    for entry in entries:
        result = {"TEAM": entry["TEAM"]}
        counting_scores = []
        cut_players = 0
        for col in PICK_COLUMNS:
            pick = (entry.get(col) or "").strip()
            if not pick:
                continue
            golfer = golfers.get(normalize_name(pick))
            if golfer is None:
                missing.add(pick)
                result[pick] = "N/F"
            elif golfer["out"]:
                cut_players += 1
                result[pick] = golfer["status"]
                counting_scores.append(CUT_PENALTY)
            else:
                result[pick] = over_under_par(golfer["topar"])
                counting_scores.append(golfer["topar"])

        if cut_players > MAX_CUT_PLAYERS or len(counting_scores) < COUNTING_GOLFERS:
            result["TOP_3_SCORE"] = "N/A"
        else:
            best = sorted(counting_scores)[:COUNTING_GOLFERS]
            result["TOP_3_SCORE"] = over_under_par(sum(best))
        results.append(result)
    return results, missing


def event_year(event):
    return (event.get("date") or str(datetime.now().year))[:4]


# ESPN event names -> the file name slugs used by past results
EVENT_SLUGS = {"masters_tournament": "masters", "the_open": "open_championship",
               "the_open_championship": "open_championship", "us_open": "us_open",
               "pga_championship": "pga_championship"}


def default_output_name(event):
    slug = re.sub(r"[^a-z0-9]+", "_", normalize_name(event["name"])).strip("_")
    slug = EVENT_SLUGS.get(slug, slug)
    return f"{slug}_{event_year(event)}_results.txt"


def slug_from_file(file_name):
    m = re.match(r"(.+?)_\d{4}_results\.txt$", os.path.basename(file_name))
    return m.group(1) if m else None


def find_drive_folder(override=None):
    if override:
        folder = os.path.expanduser(override)
        if not os.path.isdir(folder):
            raise FileNotFoundError(f"Drive folder not found: {folder}")
        return folder
    matches = sorted(glob.glob(os.path.expanduser(DRIVE_FOLDER_GLOB)))
    if not matches:
        raise FileNotFoundError(
            f"No Google Drive desktop folder matching {DRIVE_FOLDER_GLOB} - is Drive for desktop "
            "running and signed in? Or pass --drive-folder.")
    if len(matches) > 1:
        raise RuntimeError(f"Multiple Drive folders match, pass --drive-folder: {matches}")
    return matches[0]


def copy_to_google_drive(file_name, drive_folder, year):
    """Copy into <drive folder>/<year>/, overwriting in place so the Drive file id/link stays the same."""
    year_folder = os.path.join(drive_folder, year)
    os.makedirs(year_folder, exist_ok=True)
    dest = os.path.join(year_folder, os.path.basename(file_name))
    shutil.copyfile(file_name, dest)
    return dest


def run_once(args):
    """One update cycle. Returns True when the tournament is final."""
    if args.leaderboard_file:
        with open(args.leaderboard_file, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = fetch_leaderboard(args.event)
    event, golfers = transform_leaderboard(data)
    state = event.get("status", {}).get("type", {})
    log(f"{event['name']} (event {event['id']}): {state.get('description', '?')}, "
        f"{len(golfers)} golfers on leaderboard")

    entries = load_entries()
    if golfers:
        results, missing = score_entries(entries, golfers)
        for name in sorted(missing):
            log(f"WARNING: pick '{name}' not found on leaderboard (check spelling / WD) - shown as N/F")
        total_picks = len({(e.get(c) or "").strip() for e in entries for c in PICK_COLUMNS} - {""})
        if total_picks and len(missing) > total_picks / 2:
            raise RuntimeError(f"{len(missing)} of {total_picks} picks are not on this leaderboard - "
                               "wrong event? Use --event <ESPN event id>. Results NOT written.")
    else:
        log("Leaderboard has no golfers yet - nothing to score")
        return False

    year = event_year(event)
    file_name = os.path.join(RESULTS_DIR, year, args.output or default_output_name(event))
    os.makedirs(os.path.dirname(file_name), exist_ok=True)
    with open(file_name, mode="w", encoding="utf-8") as out:
        json.dump(results, out, ensure_ascii=False, indent=4)
    log(f"Wrote {file_name}")
    # Only the standings image goes to Google Drive; the .txt results stay local.
    image_file = None
    if args.image == "png":
        image_file = os.path.splitext(file_name)[0] + ".png"
        try:
            render_results.render(file_name, [image_file], updated=datetime.now())
            log(f"Wrote {image_file}")
        except Exception as e:
            log(f"ERROR rendering standings image (results file still written): {e}")
            image_file = None

    # Season standings across this year's majors (includes the in-progress one)
    season_file = None
    if args.image == "png":
        try:
            season_file = season_standings.render(year, season_standings.output_path(year))
            log(f"Wrote {season_file}")
        except Exception as e:
            log(f"ERROR rendering season standings: {e}")

    # Payouts: record the winning golfer once the tournament is final, then re-render
    payouts_file = None
    if args.image == "png":
        try:
            winner = payouts.winner_from_event(event)
            slug = slug_from_file(file_name)
            if winner and slug:
                payouts.save_winner(year, slug, winner, event.get("id"))
                log(f"Recorded tournament winner: {winner}")
            payouts_file = payouts.render(year, payouts.output_path(year))
            log(f"Wrote {payouts_file}")
        except Exception as e:
            log(f"ERROR rendering payouts: {e}")

    if not args.no_upload:
        uploads = [f for f in (image_file, season_file, payouts_file) if f]
        if not uploads:
            log("Nothing copied to Google Drive (no standings image this update)")
        else:
            try:
                drive_folder = find_drive_folder(args.drive_folder)
                for path in uploads:
                    dest = copy_to_google_drive(path, drive_folder, year)
                    log(f"Copied to Google Drive folder: {dest}")
            except Exception as e:
                log(f"ERROR copying to Google Drive (local files still written): {e}")

    return bool(state.get("completed")) and state.get("state") == "post"


def main():
    parser = argparse.ArgumentParser(description="Golf majors pool scorer")
    parser.add_argument("--event", help="ESPN event id (default: current event)")
    parser.add_argument("--output", help="results file name, saved under results/<year>/ "
                        "(default: derived from event name)")
    parser.add_argument("--interval", type=int, default=1800, help="seconds between updates")
    parser.add_argument("--once", action="store_true", help="run a single update and exit")
    parser.add_argument("--no-upload", action="store_true", help="skip copying to Google Drive")
    parser.add_argument("--drive-folder", help="Google Drive desktop folder to copy results into "
                        f"(default: {DRIVE_FOLDER_GLOB})")
    parser.add_argument("--image", choices=["png", "none"], default="png",
                        help="render the standings .png (the only file copied to Drive; default: png)")
    parser.add_argument("--leaderboard-file", help="read ESPN JSON from a file (testing)")
    args = parser.parse_args()

    while True:
        try:
            final = run_once(args)
        except KeyboardInterrupt:
            raise
        except Exception:
            log("ERROR during update:\n" + traceback.format_exc())
            if args.once:
                sys.exit(1)
            log(f"Retrying in {RETRY_DELAY}s")
            time.sleep(RETRY_DELAY)
            continue

        if final:
            log("Tournament is final - final results posted, exiting")
            return
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
