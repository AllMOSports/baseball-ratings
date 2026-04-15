import requests
from bs4 import BeautifulSoup
import numpy as np
import json
from datetime import datetime, date, timedelta
import time

SEASON_START = date(2026, 3, 1)
SEASON_END   = date(2026, 6, 15)
BASE_URL     = "https://www.mshsaa.org/activities/scoreboard.aspx?alg=3&date={}"
MAX_RUNS     = 39
OUTPUT_PATH  = "ratings.json"
ITERATIONS   = 1000
LEARNING_RATE = 0.1  # How much to adjust ratings each iteration (divisor = games played)

# --- SCRAPING (unchanged) ---

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
        games.append((l1.get_text().strip(), l2.get_text().strip(), s1, s2))

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

# --- RATING ENGINE ---

def calculate_ratings(games, iterations=ITERATIONS):
    # Build team list
    teams = list({t for t1, t2, _, _ in games for t in (t1, t2)})
    if not teams:
        return {}, {}, {}

    # Calculate league average runs per game
    all_scores = [s for _, _, s1, s2 in games for s in (s1, s2)]
    league_avg = sum(all_scores) / len(all_scores)
    print(f"  League average: {league_avg:.2f} runs per game")

    # Initialize all ratings at 0 (pure deviation from league average)
    off_rating = {t: 0.0 for t in teams}
    def_rating = {t: 0.0 for t in teams}

    for iteration in range(iterations):

        # Accumulators for this iteration's errors
        off_error   = {t: 0.0 for t in teams}
        def_error   = {t: 0.0 for t in teams}
        games_played = {t: 0   for t in teams}

        # Simulate every game using current ratings
        for t1, t2, actual_s1, actual_s2 in games:

            # Predict scores using the confirmed formula:
            # Team A predicted = Team A OFF - Team B DEF + League Average
            predicted_s1 = off_rating[t1] - def_rating[t2] + league_avg
            predicted_s2 = off_rating[t2] - def_rating[t1] + league_avg

            # Calculate prediction errors (actual - predicted)
            # Positive error = team outperformed prediction
            # Negative error = team underperformed prediction
            error_s1 = actual_s1 - predicted_s1
            error_s2 = actual_s2 - predicted_s2

            # Accumulate offensive errors
            # If we underpredicted t1's score, their OFF rating should go up
            off_error[t1]    += error_s1
            off_error[t2]    += error_s2

            # Accumulate defensive errors
            # If t1 allowed more than predicted, their DEF rating should go down
            # DEF is how much you SUPPRESS scoring, so if opponent scored more
            # than predicted, your DEF rating goes down (you were worse than expected)
            def_error[t1]    += -error_s2  # t1's defense faces t2's offense
            def_error[t2]    += -error_s1  # t2's defense faces t1's offense

            games_played[t1] += 1
            games_played[t2] += 1

        # Update ratings based on average error across all games
        for team in teams:
            if games_played[team] > 0:
                avg_off_error = off_error[team] / games_played[team]
                avg_def_error = def_error[team] / games_played[team]

                # Nudge ratings by the average error
                # This is exactly your described mechanism:
                # if they outperformed OFF by 1.0 across 10 games -> +0.1
                off_rating[team] += avg_off_error * LEARNING_RATE
                def_rating[team] += avg_def_error * LEARNING_RATE

        if (iteration + 1) % 100 == 0:
            print(f"  Iteration {iteration + 1}/{iterations} complete")

    # OVR = OFF + DEF (both positive = good, so they add together)
    ovr_rating = {t: off_rating[t] + def_rating[t] for t in teams}

    return off_rating, def_rating, ovr_rating, league_avg


def save_json(off_rating, def_rating, ovr_rating, league_avg):
    teams = sorted(ovr_rating, key=lambda t: ovr_rating[t], reverse=True)

    # Rank by each category
    off_ranked = sorted(teams, key=lambda t: off_rating[t], reverse=True)
    def_ranked = sorted(teams, key=lambda t: def_rating[t], reverse=True)
    off_rank   = {t: i+1 for i, t in enumerate(off_ranked)}
    def_rank   = {t: i+1 for i, t in enumerate(def_ranked)}

    # Normalize OVR to 0-100 for display
    ovr_vals = [ovr_rating[t] for t in teams]
    ovr_min, ovr_max = min(ovr_vals), max(ovr_vals)

    def normalize_ovr(val):
        if ovr_max == ovr_min:
            return 50.0
        return round((val - ovr_min) / (ovr_max - ovr_min) * 100, 1)

    output = {
        "last_updated": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        "league_average": round(league_avg, 2),
        "teams": [{
            "ovr_rank":   i + 1,
            "school":     t,
            "ovr_rating": normalize_ovr(ovr_rating[t]),
            "off_rating": round(off_rating[t], 2),
            "off_rank":   off_rank[t],
            "def_rating": round(def_rating[t], 2),
            "def_rank":   def_rank[t]
        } for i, t in enumerate(teams)]
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved {len(teams)} teams to {OUTPUT_PATH}")
    print(f"League average: {league_avg:.2f} runs/game")
    print(f"Top 5 teams:")
    for entry in output["teams"][:5]:
        print(f"  {entry['ovr_rank']}. {entry['school']} "
              f"| OVR: {entry['ovr_rating']} "
              f"| OFF: {entry['off_rating']:+.2f} "
              f"| DEF: {entry['def_rating']:+.2f}")


if __name__ == "__main__":
    print("=== MSHSAA Baseball Ratings ===")
    games = scrape_full_season()
    print(f"\nTotal valid games: {len(games)}")
    if not games:
        print("No games found — exiting.")
        exit(1)

    print(f"\nRunning {ITERATIONS} iterations...")
    off_rating, def_rating, ovr_rating, league_avg = calculate_ratings(games)

    print("\nSaving results...")
    save_json(off_rating, def_rating, ovr_rating, league_avg)
    print("\n=== Done ===")
