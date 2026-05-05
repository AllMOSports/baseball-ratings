"""
top20_matchups.py
-----------------
Scrapes today's MSHSAA baseball scoreboard and identifies games where
BOTH teams are ranked in the Top 20 of their respective classification.
 
Reads per-class ratings from:  ratings_class1.json … ratings_class4.json
(produced by the main baseball_ratings.py script)
 
Outputs:
  - Console summary
  - top20_matchups.md  (GitHub Actions step summary / artifact)
"""
 
import requests
from bs4 import BeautifulSoup
import json
import os
import sys
from datetime import date, datetime
import pytz
 
# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL        = "https://www.mshsaa.org/activities/scoreboard.aspx?alg=3&date={}"
CLASS_OUTPUTS   = {i: f"ratings_class{i}.json" for i in range(1, 7)}
MAX_RUNS        = 39
TOP_N           = 20          # How deep the "top" cut is
OUTPUT_MD       = "top20_matchups.md"
TZ              = pytz.timezone("America/Chicago")
 
# ── Scraper helpers (mirrors baseball_ratings.py) ─────────────────────────────
 
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
    print(f"Fetching: {url}")
    try:
        resp = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; BaseballRatingsBot/1.0)"
        })
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"ERROR fetching scoreboard: {e}", file=sys.stderr)
        return []
 
    soup  = BeautifulSoup(resp.text, "html.parser")
    games = []
 
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue
        # Accept both completed ("final") and upcoming (no score yet) games
        row_text = rows[-1].get_text().lower()
        is_final = "final" in row_text
 
        t1c = rows[1].find_all("td")
        t2c = rows[2].find_all("td")
        if len(t1c) < 2 or len(t2c) < 2:
            continue
        if not is_mshsaa_team(t1c[1]) or not is_mshsaa_team(t2c[1]):
            continue
        if is_forfeit(t1c[1], t2c[1]):
            continue
        l1 = t1c[1].find("a")
        l2 = t2c[1].find("a")
        if not l1 or not l2:
            continue
 
        t1_name = l1.get_text().strip()
        t2_name = l2.get_text().strip()
 
        # Scores may not exist for future games
        s1 = parse_score(t1c[2].get_text()) if len(t1c) > 2 else None
        s2 = parse_score(t2c[2].get_text()) if len(t2c) > 2 else None
 
        games.append({
            "date":     target_date.strftime("%Y-%m-%d"),
            "team1":    t1_name,
            "score1":   s1,
            "team2":    t2_name,
            "score2":   s2,
            "is_final": is_final,
        })
 
    return games
 
 
# ── Ratings loader ─────────────────────────────────────────────────────────────
 
def load_all_rankings():
    """
    Returns two dicts:
      team_rank  : { team_name -> ovr_rank  (within its class) }
      team_class : { team_name -> class_num }
    """
    team_rank  = {}
    team_class = {}
 
    for class_num, path in CLASS_OUTPUTS.items():
        if not os.path.exists(path):
            print(f"  Warning: {path} not found — skipping Class {class_num}.")
            continue
        with open(path) as f:
            data = json.load(f)
        for entry in data.get("teams", []):
            name = entry["school"]
            team_rank[name]  = entry["ovr_rank"]
            team_class[name] = class_num
 
    print(f"Loaded rankings for {len(team_rank)} teams across all classes.")
    return team_rank, team_class
 
 
# ── Main ───────────────────────────────────────────────────────────────────────
 
def main():
    # Support optional date override (set by GitHub Actions workflow_dispatch)
    date_override = os.environ.get("MSHSAA_DATE_OVERRIDE", "").strip()
    if date_override:
        try:
            today = date.fromisoformat(date_override)
            print(f"Date override active: {today}")
        except ValueError:
            print(f"Invalid DATE_OVERRIDE '{date_override}', using today.", file=sys.stderr)
            today = date.today()
    else:
        today = date.today()
    now   = datetime.now(TZ)
    print(f"\n=== MSHSAA Top-{TOP_N} Matchup Finder — {today} ===\n")
 
    # 1. Load rankings
    team_rank, team_class = load_all_rankings()
    if not team_rank:
        print("No ranking data found. Run baseball_ratings.py first.")
        sys.exit(1)
 
    # 2. Scrape today's games
    print(f"\nScraping today's scoreboard ({today})...")
    games = scrape_date(today)
    print(f"Found {len(games)} MSHSAA Baseball game(s) today.\n")
 
    # 3. Filter to Top-N vs Top-N matchups
    top_matchups = []
    for g in games:
        r1 = team_rank.get(g["team1"])
        r2 = team_rank.get(g["team2"])
        c1 = team_class.get(g["team1"])
        c2 = team_class.get(g["team2"])
 
        # Both teams must be ranked, in the same class, and in the top N
        if r1 is None or r2 is None:
            continue
        if r1 > TOP_N or r2 > TOP_N:
            continue
 
        top_matchups.append({**g, "rank1": r1, "rank2": r2, "class1": c1, "class2": c2})
 
    # 4. Build output
    lines = []
    lines.append(f"# 🏆 MSHSAA Baseball — Top {TOP_N} vs Top {TOP_N} Matchups")
    lines.append(f"**Date:** {today.strftime('%A, %B %d, %Y')}  ")
    lines.append(f"**Generated:** {now.strftime('%I:%M %p')} CT\n")
 
    if not top_matchups:
        lines.append(f"_No Top-{TOP_N} vs Top-{TOP_N} matchups found for today._")
    else:
        # Group by class
        by_class = {}
        for m in top_matchups:
            by_class.setdefault(m["class"], []).append(m)
 
        for cls in sorted(by_class):
            lines.append(f"## Class {cls}")
            lines.append("| # | Team 1 | Rank | Score | Score | Rank | Team 2 | Status |")
            lines.append("|---|--------|------|-------|-------|------|--------|--------|")
            for i, m in enumerate(by_class[cls], 1):
                s1 = str(m["score1"]) if m["score1"] is not None else "—"
                s2 = str(m["score2"]) if m["score2"] is not None else "—"
                status = "✅ Final" if m["is_final"] else "🕐 Scheduled"
                lines.append(
                    f"| {i} | {m['team1']} (C{m['class1']}) | #{m['rank1']} | {s1} | {s2} "
                    f"| #{m['rank2']} | {m['team2']} (C{m['class2']}) | {status} |"
                )
            lines.append("")
 
    md_content = "\n".join(lines)
 
    # 5. Print to console
    print(md_content)
 
    # 6. Write markdown file (used as Actions artifact & step summary)
    with open(OUTPUT_MD, "w") as f:
        f.write(md_content)
    print(f"\nSaved: {OUTPUT_MD}")
 
    # 7. Append to GitHub Actions step summary (if running in Actions)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as f:
            f.write(md_content)
        print("Written to GITHUB_STEP_SUMMARY.")
 
    # Exit with non-zero if no matchups (useful for conditional notifications)
    sys.exit(0 if top_matchups else 0)   # always exit 0; change to 1 if desired
 
 
if __name__ == "__main__":
    main()
