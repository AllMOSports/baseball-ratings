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

def calculate_ratings(games, iterations=1000):
    teams = list({t for t1,t2,_,_ in games for t in (t1,t2)})
    if not teams:
        return {}, {}, {}

    ovr_s = {t: [] for t in teams}
    off_s = {t: [] for t in teams}
    def_s = {t: [] for t in teams}

    for _ in range(iterations):
        off_r = {}
        def_r = {}
        for team in teams:
            scored  = [s1 for t1,t2,s1,s2 in games if t1==team] + \
                      [s2 for t1,t2,s1,s2 in games if t2==team]
            allowed = [s2 for t1,t2,s1,s2 in games if t1==team] + \
                      [s1 for t1,t2,s1,s2 in games if t2==team]
            noise_o = np.random.normal(0, 0.5, len(scored))
            noise_d = np.random.normal(0, 0.5, len(allowed))
            off_r[team] = max(0.0, float(np.mean(scored))  + float(np.mean(noise_o))) if scored  else 0.0
            def_r[team] = max(0.0, 15.0 - (float(np.mean(allowed)) + float(np.mean(noise_d)))) if allowed else 7.5

        for team in teams:
            o = off_r[team]; d = def_r[team]
            off_s[team].append(o)
            def_s[team].append(d)
            ovr_s[team].append((o+d)/2.0)

    def norm(sd):
        raw = {t: float(np.mean(v)) for t,v in sd.items()}
        mn,mx = min(raw.values()), max(raw.values())
        if mx == mn:
            return {t: 50.0 for t in raw}
        return {t: round((v-mn)/(mx-mn)*100,1) for t,v in raw.items()}

    return norm(ovr_s), norm(off_s), norm(def_s)

def save_json(ovr, off, dfe):
    teams     = sorted(ovr, key=lambda t: ovr[t], reverse=True)
    off_rank  = {t:i+1 for i,t in enumerate(sorted(ovr, key=lambda t: off[t],  reverse=True))}
    def_rank  = {t:i+1 for i,t in enumerate(sorted(ovr, key=lambda t: dfe[t],  reverse=True))}

    output = {
        "last_updated": datetime.now().strftime("%B %d, %Y at %I:%M %p"),
        "teams": [{
            "ovr_rank":   i+1,
            "school":     t,
            "ovr_rating": ovr[t],
            "off_rating": off[t],
            "off_rank":   off_rank[t],
            "def_rating": dfe[t],
            "def_rank":   def_rank[t]
        } for i,t in enumerate(teams)]
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Saved {len(teams)} teams to {OUTPUT_PATH}")

if __name__ == "__main__":
    print("=== MSHSAA Baseball Ratings ===")
    games = scrape_full_season()
    print(f"Total valid games: {len(games)}")
    if not games:
        print("No games found — exiting.")
        exit(1)
    ovr, off, dfe = calculate_ratings(games)
    save_json(ovr, off, dfe)
    print("=== Done ===")

Scroll down and click Commit new file

Step 5 — Create the GitHub Actions Workflow
This is the file that tells GitHub to run your script every night at 2 AM.

In your repository click Add file → Create new file
In the filename box type exactly this path:

.github/workflows/nightly.yml

Paste in this content:

yamlname: Nightly Baseball Ratings

on:
  schedule:
    - cron: '0 7 * * *'  # 7:00 AM UTC = 2:00 AM Central Time
  workflow_dispatch:       # Allows you to run it manually anytime

jobs:
  update-ratings:
    runs-on: ubuntu-latest

    steps:
      - name: Check out repository
        uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install requests beautifulsoup4 numpy

      - name: Run ratings script
        run: python baseball_ratings.py

      - name: Commit and push ratings.json
        run: |
          git config user.name "GitHub Actions"
          git config user.email "actions@github.com"
          git add ratings.json
          git diff --staged --quiet || git commit -m "Update ratings $(date +'%Y-%m-%d')"
          git push
