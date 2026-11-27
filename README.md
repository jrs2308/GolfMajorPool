# Golf Majors Pool

Scores `picks.csv` against ESPN's live leaderboard (best 3 of 6, cut golfers count +15,
4+ cut = N/A) and writes the results file.

## Run
```
python3 golf-majors-pool.py                    # current event, updates every 30 min, stops when final
python3 golf-majors-pool.py --once --no-upload # single update, local file only
python3 golf-majors-pool.py --event <ESPN id> --output open_championship_2026_results.txt
```

Each update also renders a standings image next to the results (`--image png|none`,
default png). To render an existing results file:
```
python3 render_results.py results/2026/masters_2026_results.txt
```

## Season standings
Points by finish in each major (last = 1 pt, +1 per place, ties split, N/A = tied for last).
Refreshed automatically after each update; to regenerate by hand:
```
python3 season_standings.py 2024 2025 2026   # -> results/<year>/season_<year>_standings.png
```
Team name spellings that changed over time are merged via `TEAM_ALIASES` in `season_standings.py`.

## Payouts
$10 buy-in per major (pot = $10 x teams). The team with the tournament's winning golfer gets
$10 back; the lowest combined score (tiebreak: lowest-scoring golfer) gets the rest; both = whole pot.
The winner is recorded in `results/<year>/winners.json` when a tournament goes final, and
`payouts_<year>.png` is refreshed each update. To backfill winners from ESPN and re-render:
```
python3 payouts.py 2024 2025 2026 --fetch-winners
```

## Google Drive
Results (.txt) and standings images (.png) are saved locally to `results/<year>/`. Only the .png
is copied into the Google Drive for desktop folder `~/Library/CloudStorage/GoogleDrive-*/My Drive/GolfMajorPool/<year>/`, and Drive syncs them.
Google Drive for desktop must be running and signed in. Override the folder with `--drive-folder`.
No API credentials are needed.

## Website
`build_site.py` turns everything in `results/` into one page, `docs/index.html`, with tabs for
each year: leaderboards, winners, payouts and season standings. Each scoring update rebuilds it.
GitHub Pages serves it from the `docs/` folder on `main`. After each update the scorer commits and pushes
`docs/` only (skipped with `--no-upload`), so the live site follows the tournament. Look/layout lives in `site_template.html`.
```
python3 build_site.py && open docs/index.html   # rebuild and preview locally
```
Each update also saves `<major>_<year>_details.json` (position, holes played, today's round per
golfer) for the site's leaderboard. To backfill final positions for past majors from ESPN:
```
python3 details.py 2024 2025 2026
```
