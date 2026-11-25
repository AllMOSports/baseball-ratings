"""
MSHSAA Ratings - historical backfill for baseball, girls soccer and spring softball.

One script for any sport and any past season. The season is named by its
spring year (2016 = the 2015-16 school year).

    python ratings_historical.py --sport baseball 2014
    python ratings_historical.py --sport girls_soccer 2013 2014
    python ratings_historical.py --sport spring_softball 2024

Rules for keeping the load on mshsaa.org low:
  * One request at a time, with a randomized 6-10 s gap between requests
    (about 1 page every 8 s, roughly 15 minutes per season).
  * Every finished date is cached in seasons/<year>/games_cache.json.
    Past seasons are final, so a cached date is never requested again.
    Reruns and resumed runs only fetch the dates that are missing.
  * On 429/5xx it backs off (honoring Retry-After). After 3 failed dates in
    a row it stops for the day instead of retrying harder. Failed dates are
    not cached, so the next run picks them up.
  * Seasons with no games on a few mid-April probe dates are skipped
    after about 4 requests instead of 107.
  * One keep-alive session per run, plus an honest User-Agent with a
    contact address.

The rating engine is the same as in the 2016/2017/current scripts, so the
historical numbers line up with what's already on the site.
"""

import argparse
import csv
import json
import os
import random
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE_URL      = "https://www.mshsaa.org/activities/scoreboard.aspx?alg={alg}&date={date}"

# Same alg codes and score caps as the current-season scripts
SPORTS = {
    "baseball":        {"alg": 3,  "max_score": 39, "unit": "runs",  "name": "Baseball"},
    "girls_soccer":    {"alg": 34, "max_score": 20, "unit": "goals", "name": "Girls Soccer"},
    "spring_softball": {"alg": 68, "max_score": 30, "unit": "runs",  "name": "Spring Softball"},
}
SPORT = SPORTS["baseball"]   # set from --sport in main()

# Before scraping a whole season, check these mid-season dates. If none of
# them has a single game (sport not sanctioned yet, season canceled, etc.),
# the season is skipped after a handful of requests instead of ~107.
# Probes are the Tuesdays and Thursdays of two mid-April weeks (busy game
# days), worked out per year so they never land on a weekend.


def probe_dates(season):
    first_tue = date(season, 4, 8)
    first_tue += timedelta(days=(1 - first_tue.weekday()) % 7)   # Tuesday on/after Apr 8
    return [first_tue, first_tue + timedelta(days=2),
            first_tue + timedelta(days=7), first_tue + timedelta(days=9)]
ITERATIONS    = 1000
LEARNING_RATE = 0.1

# Politeness settings
MIN_DELAY            = 6.0    # seconds between requests (lower bound)
MAX_DELAY            = 10.0   # seconds between requests (upper bound)
MAX_RETRIES          = 3      # per date
BACKOFF_BASE         = 60     # seconds; doubles each retry (60, 120, 240)
MAX_CONSECUTIVE_FAIL = 3      # stop the run after this many dates fail in a row
USER_AGENT = (
    "AllMOSports-HistoricalRatings/1.0 "
    "(+https://allmosports.com; contact: CHANGE-ME@allmosports.com)"
)

SEASON_START_MMDD = (3, 1)
SEASON_END_MMDD   = (6, 15)


class StopScraping(Exception):
    """Raised when the server keeps refusing; ends the run gently."""


# --- SCRAPING (same parsing rules as the existing scripts) ---

def is_mshsaa_team(cell):
    return cell.find("a", href=lambda h: h and "/MySchool/Schedule.aspx" in h) is not None


def parse_score(text):
    text = text.strip()
    if not text:
        return None
    try:
        score = int(text)
    except ValueError:
        return None
    return score if 0 <= score <= SPORT["max_score"] else None


def is_forfeit(c1, c2):
    return "forfeit" in (c1.get_text() + c2.get_text()).lower()


def parse_scoreboard(html, target_date):
    soup  = BeautifulSoup(html, "html.parser")
    games = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue
        if "final" not in rows[-1].get_text().lower():
            continue
        t1c = rows[1].find_all("td")
        t2c = rows[2].find_all("td")
        if len(t1c) < 3 or len(t2c) < 3:
            continue
        if not is_mshsaa_team(t1c[1]) or not is_mshsaa_team(t2c[1]):
            continue
        if is_forfeit(t1c[1], t2c[1]):
            continue
        l1 = t1c[1].find("a")
        l2 = t2c[1].find("a")
        if not l1 or not l2:
            continue
        s1 = parse_score(t1c[2].get_text())
        s2 = parse_score(t2c[2].get_text())
        if s1 is None or s2 is None:
            continue
        games.append([
            target_date.strftime("%Y-%m-%d"),
            l1.get_text().strip(), s1,
            l2.get_text().strip(), s2,
        ])
    return games


def fetch_date(session, target_date):
    """Fetch one scoreboard page politely. Returns HTML, or None if this date failed."""
    url = BASE_URL.format(alg=SPORT["alg"], date=target_date.strftime("%m%d%Y"))
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=30)
        except requests.RequestException as e:
            wait = BACKOFF_BASE * (2 ** attempt)
            print(f"\n    network error ({e}); waiting {wait}s", flush=True)
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            return resp.text

        if resp.status_code in (429, 500, 502, 503, 504):
            retry_after = resp.headers.get("Retry-After", "")
            wait = int(retry_after) if retry_after.isdigit() else BACKOFF_BASE * (2 ** attempt)
            print(f"\n    HTTP {resp.status_code}; backing off {wait}s", flush=True)
            time.sleep(wait)
            continue

        if resp.status_code in (401, 403):
            raise StopScraping(f"HTTP {resp.status_code} on {target_date}; the site is refusing us, stopping.")

        print(f"\n    HTTP {resp.status_code}; skipping {target_date}", flush=True)
        return None
    return None


def load_cache(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def save_cache(path, cache):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def scrape_season(season, out_dir, start, end):
    cache_path = os.path.join(out_dir, "games_cache.json")
    cache      = load_cache(cache_path)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})

    # Probe a few mid-season dates first (cached like any other date)
    probes = [d for d in probe_dates(season) if d <= end]
    for i, d in enumerate(p for p in probes if p.isoformat() not in cache):
        if i > 0:
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        print(f"  probe {d} ...", end=" ", flush=True)
        html = fetch_date(session, d)
        if html is None:
            print("failed")
            session.close()
            return [], False
        cache[d.isoformat()] = parse_scoreboard(html, d)
        save_cache(cache_path, cache)
        print(f"{len(cache[d.isoformat()])} games")
    if probes and not any(cache.get(p.isoformat()) for p in probes):
        print("  No games on any probe date, so skipping this season.")
        session.close()
        return [], True
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    all_dates = []
    d = start
    while d <= end:
        all_dates.append(d)
        d += timedelta(days=1)
    todo = [d for d in all_dates if d.isoformat() not in cache]
    print(f"  {len(all_dates)} dates in season, {len(all_dates) - len(todo)} cached, {len(todo)} to fetch")
    if todo:
        est = len(todo) * (MIN_DELAY + MAX_DELAY) / 2 / 60
        print(f"  Estimated time: ~{est:.0f} min")

    complete = True
    if todo:
        consecutive_fail = 0
        try:
            for i, d in enumerate(todo):
                if i > 0:
                    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
                print(f"  {d} ...", end=" ", flush=True)
                html = fetch_date(session, d)
                if html is None:
                    consecutive_fail += 1
                    complete = False
                    print("failed (will retry next run)")
                    if consecutive_fail >= MAX_CONSECUTIVE_FAIL:
                        raise StopScraping(f"{consecutive_fail} dates failed in a row; stopping for now.")
                    continue
                consecutive_fail = 0
                games = parse_scoreboard(html, d)
                cache[d.isoformat()] = games
                save_cache(cache_path, cache)   # save after every date so progress survives a crash
                print(f"{len(games)} games")
        except StopScraping as e:
            print(f"\n  STOPPED: {e}")
            complete = False
    session.close()

    all_games = [g for k in sorted(cache) for g in cache[k]]
    return all_games, complete


# --- RATING ENGINE (identical to existing scripts) ---

def calculate_ratings(all_games, iterations=ITERATIONS):
    games = [(t1, t2, s1, s2) for _, t1, s1, t2, s2 in all_games]
    teams = list({t for t1, t2, _, _ in games for t in (t1, t2)})
    if not teams:
        return {}, {}, {}, 0

    all_scores = [s for _, _, s1, s2 in games for s in (s1, s2)]
    league_avg = sum(all_scores) / len(all_scores)
    print(f"  League average: {league_avg:.2f} {SPORT['unit']} per game")

    off_rating = {t: 0.0 for t in teams}
    def_rating = {t: 0.0 for t in teams}

    for _ in range(iterations):
        off_error    = {t: 0.0 for t in teams}
        def_error    = {t: 0.0 for t in teams}
        games_played = {t: 0   for t in teams}

        for t1, t2, actual_s1, actual_s2 in games:
            predicted_s1 = off_rating[t1] - def_rating[t2] + league_avg
            predicted_s2 = off_rating[t2] - def_rating[t1] + league_avg
            error_s1 = actual_s1 - predicted_s1
            error_s2 = actual_s2 - predicted_s2
            off_error[t1] += error_s1
            off_error[t2] += error_s2
            def_error[t1] += -error_s2
            def_error[t2] += -error_s1
            games_played[t1] += 1
            games_played[t2] += 1

        for team in teams:
            if games_played[team] > 0:
                off_rating[team] += (off_error[team] / games_played[team]) * LEARNING_RATE
                def_rating[team] += (def_error[team] / games_played[team]) * LEARNING_RATE

    ovr_rating = {t: round(off_rating[t] + def_rating[t], 2) for t in teams}
    return off_rating, def_rating, ovr_rating, league_avg


# --- OUTPUT ---

def load_classifications(path):
    """Optional per-season file, same format as classifications.json."""
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        data = json.load(f)
    return {e["school"]: {"classification": e["classification"], "district": e["district"]}
            for e in data["teams"]}


def save_outputs(season, out_dir, all_games, off_rating, def_rating, ovr_rating,
                 league_avg, classifications, complete):
    with open(os.path.join(out_dir, "scoreboard.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Home Team", "Home Score", "Away Team", "Away Score"])
        w.writerows(all_games)

    teams      = sorted(ovr_rating, key=lambda t: ovr_rating[t], reverse=True)
    off_rank   = {t: i + 1 for i, t in enumerate(sorted(teams, key=lambda t: off_rating[t], reverse=True))}
    def_rank   = {t: i + 1 for i, t in enumerate(sorted(teams, key=lambda t: def_rating[t], reverse=True))}

    def team_entry(i, t):
        entry = {
            "ovr_rank":   i + 1,
            "school":     t,
            "ovr_rating": ovr_rating[t],
            "off_rating": round(off_rating[t], 2),
            "off_rank":   off_rank[t],
            "def_rating": round(def_rating[t], 2),
            "def_rank":   def_rank[t],
        }
        if classifications:
            entry["classification"] = classifications.get(t, {}).get("classification", "")
            entry["district"]       = classifications.get(t, {}).get("district", "")
        return entry

    output = {
        "sport":          SPORT["name"],
        "season":         season,
        "school_year":    f"{season - 1}-{season}",
        "last_updated":   datetime.now(ZoneInfo("America/Chicago")).strftime("%B %d, %Y at %I:%M %p"),
        "complete":       complete,
        "games":          len(all_games),
        "league_average": round(league_avg, 2),
        "teams":          [team_entry(i, t) for i, t in enumerate(teams)],
    }
    with open(os.path.join(out_dir, "ratings.json"), "w") as f:
        json.dump(output, f, indent=2)

    with open(os.path.join(out_dir, "ratings_all.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Team", "OVR Rating", "OFF Rating", "DEF Rating"])
        for t in teams:
            w.writerow([t, f"{ovr_rating[t]:.2f}", f"{off_rating[t]:.2f}", f"{def_rating[t]:.2f}"])

    print(f"  Saved {len(teams)} teams to {out_dir}/ratings.json")
    for e in output["teams"][:5]:
        print(f"    {e['ovr_rank']}. {e['school']} | OVR {e['ovr_rating']:+.2f} "
              f"| OFF {e['off_rating']:+.2f} | DEF {e['def_rating']:+.2f}")

    if classifications:
        save_class_outputs(season, out_dir, off_rating, def_rating, ovr_rating,
                           league_avg, classifications, complete)


def save_class_outputs(season, out_dir, off_rating, def_rating, ovr_rating,
                       league_avg, classifications, complete):
    """Per-class files, same layout as the nightly scripts: ratings_classN.json / .csv.
    The classes come from that season's file, so 5-class and 6-class years both work."""
    classes = sorted({c["classification"] for c in classifications.values()})
    for class_num in classes:
        class_teams = [t for t in ovr_rating if classifications.get(t, {}).get("classification") == class_num]
        if not class_teams:
            continue
        ranked   = sorted(class_teams, key=lambda t: ovr_rating[t], reverse=True)
        off_rank = {t: i + 1 for i, t in enumerate(sorted(class_teams, key=lambda t: off_rating[t], reverse=True))}
        def_rank = {t: i + 1 for i, t in enumerate(sorted(class_teams, key=lambda t: def_rating[t], reverse=True))}
        output = {
            "sport":          SPORT["name"],
            "season":         season,
            "school_year":    f"{season - 1}-{season}",
            "last_updated":   datetime.now(ZoneInfo("America/Chicago")).strftime("%B %d, %Y at %I:%M %p"),
            "complete":       complete,
            "league_average": round(league_avg, 2),
            "classification": class_num,
            "teams": [{
                "ovr_rank":       i + 1,
                "school":         t,
                "classification": class_num,
                "district":       classifications[t]["district"],
                "ovr_rating":     ovr_rating[t],
                "off_rating":     round(off_rating[t], 2),
                "off_rank":       off_rank[t],
                "def_rating":     round(def_rating[t], 2),
                "def_rank":       def_rank[t],
            } for i, t in enumerate(ranked)],
        }
        with open(os.path.join(out_dir, f"ratings_class{class_num}.json"), "w") as f:
            json.dump(output, f, indent=2)
        with open(os.path.join(out_dir, f"ratings_class{class_num}.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Team", "OVR Rating", "OFF Rating", "DEF Rating"])
            for t in ranked:
                w.writerow([t, f"{ovr_rating[t]:.2f}", f"{off_rating[t]:.2f}", f"{def_rating[t]:.2f}"])
        print(f"  Class {class_num}: {len(ranked)} teams, top: {ranked[0]} ({ovr_rating[ranked[0]]:+.2f})")


def run_season(season, out_root):
    out_dir = os.path.join(out_root, str(season))
    os.makedirs(out_dir, exist_ok=True)
    start = date(season, *SEASON_START_MMDD)
    end   = min(date(season, *SEASON_END_MMDD), date.today())

    print(f"\n=== {SPORT['name']} {season} season ({season - 1}-{season}) ===")
    all_games, complete = scrape_season(season, out_dir, start, end)
    print(f"  Total valid games: {len(all_games)}{'' if complete else '  (INCOMPLETE - rerun to finish)'}")

    if not all_games:
        print("  No games found, so no ratings written. (Spring 2020 was canceled, so 2020 should be empty.)")
        return complete

    # Looks for seasons/classifications_<year>.json (flat, easy to upload),
    # falling back to the older seasons/<year>/classifications.json.
    class_path = os.path.join(out_root, f"classifications_{season}.json")
    if not os.path.exists(class_path):
        class_path = os.path.join(out_dir, "classifications.json")
    classifications = load_classifications(class_path)
    if classifications:
        print(f"  Classifications: {class_path} ({len(classifications)} schools)")
    if classifications:
        # Same rule as the nightly scripts: only games where both schools are in
        # that season's district list. Applied after the cache, so the raw games
        # are kept and the list can be fixed later without re-scraping.
        scraped_names = {t for g in all_games for t in (g[1], g[3])}
        unmatched = sorted(scraped_names - set(classifications))
        if unmatched:
            print(f"  {len(unmatched)} scoreboard names not in classifications_{season}.json "
                  f"(their games are left out):")
            for t in unmatched:
                print(f"    - {t}")
            with open(os.path.join(out_dir, "unmatched_teams.txt"), "w") as f:
                f.write("\n".join(unmatched) + "\n")
        all_games = [g for g in all_games if g[1] in classifications and g[3] in classifications]
        print(f"  Using {len(all_games)} games between listed schools")
    else:
        print(f"  No classifications_{season}.json in {out_root}/, so no team filter or per-class files.")
    if not all_games:
        print("  No games left after filtering, so no ratings written.")
        return complete

    off_r, def_r, ovr_r, avg = calculate_ratings(all_games)
    save_outputs(season, out_dir, all_games, off_r, def_r, ovr_r, avg, classifications, complete)
    return complete


def main():
    global SPORT
    p = argparse.ArgumentParser(description="Backfill MSHSAA ratings for past seasons.")
    p.add_argument("--sport", required=True, choices=sorted(SPORTS))
    p.add_argument("seasons", nargs="+", type=int, help="spring year(s), e.g. 2013 2014")
    p.add_argument("--out-root", default="seasons", help="output folder (default: seasons/)")
    p.add_argument("--pause-between-seasons", type=int, default=300,
                   help="seconds to rest between seasons in one run (default 300)")
    args = p.parse_args()
    SPORT = SPORTS[args.sport]

    all_complete = True
    for i, season in enumerate(args.seasons):
        if i > 0:
            print(f"\nResting {args.pause_between_seasons}s before next season...")
            time.sleep(args.pause_between_seasons)
        try:
            all_complete &= run_season(season, args.out_root)
        except StopScraping as e:
            print(f"\nSTOPPED: {e}")
            all_complete = False
            break

    print("\n=== Done ===" if all_complete else "\n=== Finished with gaps; rerun later to fill them ===")
    sys.exit(0)  # never fail the job, so the commit step always saves progress


if __name__ == "__main__":
    main()
