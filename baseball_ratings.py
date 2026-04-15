import requests
from bs4 import BeautifulSoup
import numpy as np
import json
import csv
from datetime import datetime, date, timedelta
import time

SEASON_START  = date(2026, 3, 1)
SEASON_END    = date(2026, 6, 15)
BASE_URL      = "https://www.mshsaa.org/activities/scoreboard.aspx?alg=3&date={}"
MAX_RUNS      = 39
OUTPUT_PATH   = "ratings.json"
CSV_PATH      = "scoreboard.csv"
ITERATIONS    = 1000
LEARNING_RATE = 0.1

# --- SCRAPING ---

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
    return score if 0 <= score <= MAX_RUNS else None

def is_forfeit(c1, c2):
    return "forfeit" in (c1.get_text() + c2.get_text()).lower()

def scrape_date(target_date):
    url = BASE_URL.format(target_date.strftime("%m%d%Y"))
    try:
        resp = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BaseballRatingsBot/1.0)"
        })
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  Failed {target_date}: {e}")
        return []

    soup  = BeautifulSoup(resp.text, "html.parser")
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
        games.append((
            target_date.strftime("%Y-%m-%d"),
            l1.get_text().strip(),
            s1,
            l2.get_text().strip(),
            s2
        ))

    return games

def scrape_full_season():
    all_games = []
    current   = SEASON_START
    while current <= min(SEASON_END, date.today()):
        print(f"  Scraping {current}...", end=" ", flush=True)
        day_games = scrape_date(current)
        all_games.extend(day_games)
        print(f"{len(day_games)} games")
        current += timedelta(days=1)
        time.sleep(0.5)
    return all_games

def save_csv(all_games):
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Home Team", "Home Score", "Away Team", "Away Score"])
        for date_str, t1, s1, t2, s2 in all_games:
            writer.writerow([date_str, t1, s1, t2, s2])
    print(f"Saved {len(all_games)} games to {CSV_PATH}")

# --- RATING ENGINE ---

def calculate_ratings(all_games, iterations=ITERATIONS):
    # Strip date from games for rating calculations
    games = [(t1, t2, s1, s2) for _, t1, s1, t2, s2 in all_games]

    teams = list({t for t1, t2, _, _ in games for t in (t1, t2)})
    if not teams:
        return {}, {}, {}

    # Calculate league average runs per game
    all_scores = [s for _, _, s1, s2 in games for s in (s1, s2)]
    league_avg = sum(all_scores) / len(all_scores)
    print(f"  League average: {league_avg:.2f} runs per game")

    # Initialize all ratings at 0
    off_rating = {t: 0.0 for t in teams}
    def_rating = {t: 0.0 for t in teams}

    for iteration in range(iterations):

        off_error    = {t: 0.0 for t in teams}
        def_error    = {t: 0.0 for t in teams}
        games_played = {t: 0   for t in teams}

        for t1, t2, actual_s1, actual_s2 in games:

            predicted_s1 = off_rating[t1] - def_rating[t2] + league_avg
            predicted_s2 = off_rating[t2] - def_rating[t1] + league_avg

            error_s1 = actual_s1 - predicted_s1
            error_s2 = actual_s2 - predicted_s2

            off_error[t1]    += error_s1
            off_error[t2]    += error_s2
            def_error[t1]    += -error_s2
            def_error[t2]    += -error_s1

            games_played[t1] += 1
            games_played[t2] += 1

        for team in teams:
            if games_played[team] > 0:
                off_rating[team] += (off_error[team] / games_played[team]) * LEARNING_RATE
                def_rating[team] += (def_error[team] / games_played[team]) * LEARNING_RATE

        if (iteration + 1) % 100 == 0:
            print(f"  Iteration {iteration + 1}/{iterations} complete")

    # OVR = OFF + DEF (no normalization — raw sum in runs above/below average)
    ovr_rating = {t: round(off_rating[t] + def_rating[t], 2) for t in teams}

    return off_rating, def_rating, ovr_rating, league_avg


def save_json(off_rating, def_rating, ovr_rating, league_avg):
    teams      = sorted(ovr_rating, key=lambda t: ovr_rating[t], reverse=True)
    off_ranked = sorted(teams, key=lambda t: off_rating[t], reverse=True)
    def_ranked = sorted(teams, key=lambda t: def_rating[t], reverse=True)
    off_rank   = {t: i+1 for i, t in enumerate(off_ranked)}
    def_rank   = {t: i+1 for i, t in enumerate(def_ranked)}

    output = {
        "last_updated":   datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        "league_average": round(league_avg, 2),
        "teams": [{
            "ovr_rank":   i + 1,
            "school":     t,
            "ovr_rating": ovr_rating[t],
            "off_rating": round(off_rating[t], 2),
            "off_rank":   off_rank[t],
            "def_rating": round(def_rating[t], 2),
            "def_rank":   def_rank[t]
        } for i, t in enumerate(teams)]
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved {len(teams)} teams to {OUTPUT_PATH}")
    print(f"League average: {league_avg:.2f} runs/game")
    print(f"Top 5 teams:")
    for entry in output["teams"][:5]:
        print(f"  {entry['ovr_rank']}. {entry['school']} "
              f"| OVR: {entry['ovr_rating']:+.2f} "
              f"| OFF: {entry['off_rating']:+.2f} "
              f"| DEF: {entry['def_rating']:+.2f}")


if __name__ == "__main__":
    print("=== MSHSAA Baseball Ratings ===")
    all_games = scrape_full_season()
    print(f"\nTotal valid games: {len(all_games)}")
    if not all_games:
        print("No games found — exiting.")
        exit(1)

    print("\nSaving scoreboard CSV...")
    save_csv(all_games)

    print(f"\nRunning {ITERATIONS} iterations...")
    off_rating, def_rating, ovr_rating, league_avg = calculate_ratings(all_games)

    print("\nSaving ratings JSON...")
    save_json(off_rating, def_rating, ovr_rating, league_avg)
    print("\n=== Done ===")
