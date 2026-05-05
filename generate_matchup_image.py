"""
generate_matchup_image.py
--------------------------
Reads top20_matchups.md (produced by top20_matchups.py) and renders
a clean, Twitter-ready PNG graphic styled like a sports prediction table.
 
Column order (both sides mirror each other):
  Class | Team | Class Rank | Overall Rank  ||  vs.  ||  Class | Team | Class Rank | Overall Rank
 
Higher overall-ranked team is always placed on the left.
 
Dependencies:
    pip install pillow pytz
 
Usage:
    python generate_matchup_image.py
    # Outputs: top20_matchups.png
"""
 
from PIL import Image, ImageDraw, ImageFont
import json, os, re, sys
from datetime import date, datetime
import pytz
 
# ── Config ────────────────────────────────────────────────────────────────────
INPUT_MD   = "top20_matchups.md"
OUTPUT_PNG = "top20_matchups.png"
LOGO_PATH  = "ALL_MO_SPORTS_LOGO_-_NEW.png"
TZ         = pytz.timezone("America/Chicago")
 
FONT_BOLD    = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
 
WHITE     = (255, 255, 255)
BLACK     = (0,   0,   0)
LIGHT_ROW = (235, 237, 240)
DARK_ROW  = (255, 255, 255)
GRAY_TEXT = (100, 100, 100)
HDR_BG    = (220, 222, 226)
DIV_COLOR = (180, 182, 186)
 
def fnt(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()
 
def parse_matchups_md(path):
    if not os.path.exists(path):
        print(f"ERROR: {path} not found. Run top20_matchups.py first.")
        sys.exit(1)
    with open(path) as f:
        lines = f.readlines()
    date_str = ""
    matchups = []
    cur_sec  = ""
    for line in lines:
        line = line.rstrip()
        m = re.match(r"\*\*Date:\*\*\s+(.+)", line)
        if m:
            date_str = m.group(1).strip()
        m = re.match(r"^## (.+)", line)
        if m:
            cur_sec = m.group(1).strip()
        m = re.match(r"^\|\s*\d+\s*\|(.+)", line)
        if m and cur_sec:
            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]
            if len(parts) >= 7:
                def extract(cell):
                    cm = re.match(r"(.+?)\s*\(C(\d)\)", cell)
                    if cm:
                        return cm.group(1).strip(), int(cm.group(2))
                    return cell.strip(), None
                def extract_rank(cell):
                    rm = re.match(r"#(\d+)", cell.strip())
                    return int(rm.group(1)) if rm else None
                t1, c1 = extract(parts[1])
                r1     = extract_rank(parts[2])
                t2, c2 = extract(parts[5])
                r2     = extract_rank(parts[4])
                matchups.append({
                    "section": cur_sec,
                    "team1": t1, "rank1": r1, "class1": c1,
                    "team2": t2, "rank2": r2, "class2": c2,
                })
    return date_str, matchups
 
def load_overall_rankings():
    overall = {}
    for i in range(1, 7):
        path = f"ratings_class{i}.json"
        if not os.path.exists(path):
            continue
        with open(path) as f:
            data = json.load(f)
        for entry in data.get("teams", []):
            overall[entry["school"]] = {
                "class_rank": entry["ovr_rank"],
                "ovr_rating": entry.get("ovr_rating", 0),
            }
    sorted_teams = sorted(overall.items(), key=lambda x: x[1]["ovr_rating"], reverse=True)
    for idx, (name, _) in enumerate(sorted_teams, 1):
        overall[name]["overall_rank"] = idx
    return overall
 
def render(date_str, matchups, overall_rankings):
    f_title  = fnt(FONT_BOLD,    26)
    f_sub    = fnt(FONT_BOLD,    17)
    f_col    = fnt(FONT_BOLD,    14)
    f_team   = fnt(FONT_BOLD,    16)
    f_num    = fnt(FONT_REGULAR, 16)
    f_vs     = fnt(FONT_BOLD,    14)
    f_footer = fnt(FONT_REGULAR, 12)
 
    for m in matchups:
        t1_info = overall_rankings.get(m["team1"], {})
        t2_info = overall_rankings.get(m["team2"], {})
        o1 = t1_info.get("overall_rank", 9999)
        o2 = t2_info.get("overall_rank", 9999)
        if o2 < o1:
            m["team1"],  m["team2"]  = m["team2"],  m["team1"]
            m["rank1"],  m["rank2"]  = m["rank2"],  m["rank1"]
            m["class1"], m["class2"] = m["class2"], m["class1"]
        m["o1"] = overall_rankings.get(m["team1"], {}).get("overall_rank", 0)
        m["o2"] = overall_rankings.get(m["team2"], {}).get("overall_rank", 0)
 
    IMG_W     = 1200
    PAD_X     = 30
    TITLE_H   = 90
    COL_HDR_H = 50
    ROW_H     = 44
    FOOTER_H  = 30
    n         = len(matchups) if matchups else 1
    IMG_H     = TITLE_H + COL_HDR_H + ROW_H * n + FOOTER_H
 
    img  = Image.new("RGB", (IMG_W, IMG_H), WHITE)
    draw = ImageDraw.Draw(img)
 
    def tw(text, font):
        return int(draw.textlength(text, font=font))
 
    def ctext(text, font, cx, y, color=BLACK):
        draw.text((cx - tw(text, font) // 2, y), text, font=font, fill=color)
 
    LOGO_H = 72
    logo_w = 0
    if os.path.exists(LOGO_PATH):
        logo  = Image.open(LOGO_PATH).convert("RGBA")
        ratio = LOGO_H / logo.height
        logo  = logo.resize((int(logo.width * ratio), LOGO_H), Image.LANCZOS)
        logo_w = logo.width
        lx = IMG_W - PAD_X - logo_w
        ly = (TITLE_H - LOGO_H) // 2
        bg = Image.new("RGB", logo.size, WHITE)
        bg.paste(logo.convert("RGB"), mask=logo.split()[3])
        img.paste(bg, (lx, ly))
 
    text_area_w = IMG_W - PAD_X * 2 - logo_w - 20
    cx_title    = PAD_X + text_area_w // 2
    ctext("ALL MO SPORTS", f_title, cx_title, 14)
    ctext(f"Missouri High School Baseball Big Matchups - {date_str}", f_sub, cx_title, 52)
    draw.line([(0, TITLE_H), (IMG_W, TITLE_H)], fill=BLACK, width=2)
 
    C_CLS  = 68
    C_CR   = 100
    C_OR   = 110
    C_VS   = 46
    C_TEAM = (IMG_W - PAD_X * 2 - C_CLS * 2 - C_CR * 2 - C_OR * 2 - C_VS) // 2
 
    xc1  = PAD_X
    xt1  = xc1  + C_CLS
    xcr1 = xt1  + C_TEAM
    xor1 = xcr1 + C_CR
    xvs  = xor1 + C_OR
    xc2  = xvs  + C_VS
    xt2  = xc2  + C_CLS
    xcr2 = xt2  + C_TEAM
    xor2 = xcr2 + C_CR
 
    def cx(x, w): return x + w // 2
 
    dividers = [xt1, xcr1, xor1, xvs, xc2 + C_CLS, xcr2, xor2]
 
    hy   = TITLE_H
    hbot = hy + COL_HDR_H
    draw.rectangle([0, hy, IMG_W, hbot], fill=HDR_BG)
    draw.line([(0, hbot), (IMG_W, hbot)], fill=BLACK, width=2)
 
    def hdr2(text, x, w):
        lines = text.split("\n")
        lh    = 15
        total = lh * len(lines) + 2 * (len(lines) - 1)
        sy    = hy + (COL_HDR_H - total) // 2
        for ln in lines:
            lw = tw(ln, f_col)
            draw.text((x + (w - lw) // 2, sy), ln, font=f_col, fill=BLACK)
            sy += lh + 2
 
    hdr2("Class",         xc1,  C_CLS)
    hdr2("Team",          xt1,  C_TEAM)
    hdr2("Class\nRank",   xcr1, C_CR)
    hdr2("Overall\nRank", xor1, C_OR)
    hdr2("",              xvs,  C_VS)
    hdr2("Class",         xc2,  C_CLS)
    hdr2("Team",          xt2,  C_TEAM)
    hdr2("Class\nRank",   xcr2, C_CR)
    hdr2("Overall\nRank", xor2, C_OR)
 
    for x in dividers:
        draw.line([(x, hy), (x, hbot)], fill=BLACK, width=1)
 
    if not matchups:
        msg = "No Top 20 vs Top 20 matchups today."
        mw  = tw(msg, f_num)
        draw.text(((IMG_W - mw) // 2, hbot + 14), msg, font=f_num, fill=GRAY_TEXT)
    else:
        for i, m in enumerate(matchups):
            ry  = hbot + i * ROW_H
            rb  = ry + ROW_H
            bg  = LIGHT_ROW if i % 2 == 0 else DARK_ROW
            draw.rectangle([0, ry, IMG_W, rb], fill=bg)
            for x in dividers:
                draw.line([(x, ry), (x, rb)], fill=DIV_COLOR, width=1)
            ty   = ry + (ROW_H - 16) // 2
            maxw = C_TEAM - 10
            ctext(str(m["class1"]), f_num, cx(xc1, C_CLS), ty)
            t1 = m["team1"]
            while tw(t1, f_team) > maxw and len(t1) > 3:
                t1 = t1[:-1]
            if t1 != m["team1"]: t1 = t1[:-1] + "…"
            ctext(t1, f_team, cx(xt1, C_TEAM), ty)
            ctext(str(m["rank1"]), f_num, cx(xcr1, C_CR), ty)
            ctext(str(m["o1"]) if m["o1"] else "—", f_num, cx(xor1, C_OR), ty)
            ctext("vs.", f_vs, cx(xvs, C_VS), ty, GRAY_TEXT)
            ctext(str(m["class2"]), f_num, cx(xc2, C_CLS), ty)
            t2 = m["team2"]
            while tw(t2, f_team) > maxw and len(t2) > 3:
                t2 = t2[:-1]
            if t2 != m["team2"]: t2 = t2[:-1] + "…"
            ctext(t2, f_team, cx(xt2, C_TEAM), ty)
            ctext(str(m["rank2"]), f_num, cx(xcr2, C_CR), ty)
            ctext(str(m["o2"]) if m["o2"] else "—", f_num, cx(xor2, C_OR), ty)
            draw.line([(0, rb), (IMG_W, rb)], fill=DIV_COLOR, width=1)
 
    last_y = hbot + n * ROW_H
    draw.line([(0, last_y), (IMG_W, last_y)], fill=BLACK, width=2)
    ctext("allMOsports.com", f_footer, IMG_W // 2, last_y + 8, GRAY_TEXT)
    draw.rectangle([0, 0, IMG_W - 1, IMG_H - 1], outline=BLACK, width=3)
    img.save(OUTPUT_PNG, dpi=(150, 150))
    print(f"Saved: {OUTPUT_PNG}  ({n} matchup{'s' if n != 1 else ''})")
 
if __name__ == "__main__":
    print("=== Matchup Image Generator ===")
    date_str, matchups = parse_matchups_md(INPUT_MD)
    overall_rankings   = load_overall_rankings()
    if not date_str:
        date_str = date.today().strftime("%A, %B %d, %Y")
    print(f"Date: {date_str}")
    print(f"Matchups found: {len(matchups)}")
    render(date_str, matchups, overall_rankings)
