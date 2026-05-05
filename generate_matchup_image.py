"""
generate_matchup_image.py
--------------------------
Reads top20_matchups.md (produced by top20_matchups.py) and renders
a clean, Twitter-ready 1200x675 PNG graphic.
 
Dependencies:
    pip install pillow
 
Usage:
    python generate_matchup_image.py
    # Outputs: top20_matchups.png
"""
 
from PIL import Image, ImageDraw, ImageFont
import json
import os
import re
import sys
from datetime import datetime
import pytz
 
# ── Config ────────────────────────────────────────────────────────────────────
INPUT_MD   = "top20_matchups.md"
OUTPUT_PNG = "top20_matchups.png"
TZ         = pytz.timezone("America/Chicago")
 
# Twitter optimal dimensions (16:9)
IMG_W = 1200
IMG_H = 675
 
# Palette — clean minimal
BG          = (255, 255, 255)
TITLE_COL   = (15,  15,  15)
DATE_COL    = (120, 120, 120)
CARD_BG     = (247, 248, 250)
CARD_BORDER = (220, 223, 228)
RANK_COL    = (180, 180, 180)
NAME_COL    = (20,  20,  20)
CLASS_COL   = (100, 120, 160)
VS_COL      = (200, 200, 200)
DIVIDER     = (230, 232, 236)
ACCENT      = (30,  80, 180)
FOOTER_COL  = (180, 180, 180)
 
# ── Font loader ───────────────────────────────────────────────────────────────
 
def load_font(size, bold=False):
    """Try to load a system font; fall back to PIL default."""
    candidates_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    candidates_regular = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    candidates = candidates_bold if bold else candidates_regular
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()
 
# ── Markdown parser ───────────────────────────────────────────────────────────
 
def parse_matchups_md(path):
    """
    Returns:
        date_str   : str  e.g. "Monday, May 05, 2026"
        matchups   : list of dicts with keys:
                     section, team1, rank1, class1, team2, rank2, class2
    """
    if not os.path.exists(path):
        print(f"ERROR: {path} not found. Run top20_matchups.py first.")
        sys.exit(1)
 
    with open(path) as f:
        lines = f.readlines()
 
    date_str = ""
    matchups = []
    current_section = ""
 
    for line in lines:
        line = line.rstrip()
 
        # Date line: **Date:** Monday, May 05, 2026
        m = re.match(r"\*\*Date:\*\*\s+(.+)", line)
        if m:
            date_str = m.group(1).strip()
 
        # Section header: ## Class 3  or  ## Class 3 vs Class 6
        m = re.match(r"^## (.+)", line)
        if m:
            current_section = m.group(1).strip()
 
        # Table data row: | 1 | Team A (C3) | #5 | — | — | #12 | Team B (C3) | 🕐 Scheduled |
        m = re.match(r"^\|\s*\d+\s*\|(.+)", line)
        if m and current_section:
            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]  # remove empty
            if len(parts) >= 7:
                def extract(cell):
                    """Pull team name and class number from 'Team Name (C3)'"""
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
                    "section": current_section,
                    "team1":   t1,
                    "rank1":   r1,
                    "class1":  c1,
                    "team2":   t2,
                    "rank2":   r2,
                    "class2":  c2,
                })
 
    return date_str, matchups
 
# ── Drawing helpers ───────────────────────────────────────────────────────────
 
def text_w(draw, text, font):
    return draw.textlength(text, font=font)
 
def draw_rounded_rect(draw, xy, radius, fill, outline=None, outline_width=1):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill,
                           outline=outline, width=outline_width)
 
# ── Main renderer ─────────────────────────────────────────────────────────────
 
def render(date_str, matchups):
    img  = Image.new("RGB", (IMG_W, IMG_H), BG)
    draw = ImageDraw.Draw(img)
 
    # Fonts
    f_title    = load_font(36, bold=True)
    f_date     = load_font(18)
    f_rank     = load_font(22, bold=True)
    f_name     = load_font(22, bold=True)
    f_class    = load_font(15)
    f_vs       = load_font(18, bold=True)
    f_section  = load_font(13, bold=True)
    f_footer   = load_font(13)
    f_no_match = load_font(22)
 
    # ── Header ────────────────────────────────────────────────────────────────
    HEADER_H = 90
    title_text = "MSHSAA Baseball · Top 20 Matchups"
    tw = text_w(draw, title_text, f_title)
    draw.text(((IMG_W - tw) / 2, 22), title_text, font=f_title, fill=TITLE_COL)
 
    dw = text_w(draw, date_str, f_date)
    draw.text(((IMG_W - dw) / 2, 62), date_str, font=f_date, fill=DATE_COL)
 
    # Thin accent line under header
    draw.line([(60, HEADER_H), (IMG_W - 60, HEADER_H)], fill=DIVIDER, width=1)
 
    # ── No matchups ───────────────────────────────────────────────────────────
    if not matchups:
        msg = "No Top 20 vs Top 20 matchups today."
        mw  = text_w(draw, msg, f_no_match)
        draw.text(((IMG_W - mw) / 2, IMG_H / 2 - 15), msg,
                  font=f_no_match, fill=DATE_COL)
        img.save(OUTPUT_PNG)
        print(f"Saved: {OUTPUT_PNG}")
        return
 
    # ── Layout cards ─────────────────────────────────────────────────────────
    CONTENT_TOP  = HEADER_H + 18
    CONTENT_BOT  = IMG_H - 40   # leave room for footer
    CONTENT_H    = CONTENT_BOT - CONTENT_TOP
    PAD_X        = 50
 
    n            = len(matchups)
    MAX_COLS     = 2
    cols         = min(n, MAX_COLS)
    rows         = (n + cols - 1) // cols
 
    GAP_X        = 20
    GAP_Y        = 14
    card_w       = (IMG_W - PAD_X * 2 - GAP_X * (cols - 1)) // cols
    card_h       = (CONTENT_H - GAP_Y * (rows - 1)) // rows
    card_h       = min(card_h, 130)   # cap height for aesthetics
 
    # Centre the grid vertically
    grid_h  = rows * card_h + (rows - 1) * GAP_Y
    start_y = CONTENT_TOP + (CONTENT_H - grid_h) // 2
 
    # Group matchups by section for section labels
    sections_seen = []
    for m in matchups:
        if m["section"] not in sections_seen:
            sections_seen.append(m["section"])
 
    for idx, m in enumerate(matchups):
        col = idx % cols
        row = idx // cols
        x   = PAD_X + col * (card_w + GAP_X)
        y   = start_y + row * (card_h + GAP_Y)
 
        # Card background
        draw_rounded_rect(draw, (x, y, x + card_w, y + card_h),
                          radius=10, fill=CARD_BG,
                          outline=CARD_BORDER, outline_width=1)
 
        # Section label (class header) — small pill top-left
        sec_label = m["section"]
        sl_w = text_w(draw, sec_label, f_section) + 16
        draw_rounded_rect(draw, (x + 14, y + 10, x + 14 + sl_w, y + 28),
                          radius=4, fill=ACCENT)
        draw.text((x + 22, y + 11), sec_label, font=f_section, fill=(255, 255, 255))
 
        # ── Team 1 (left side) ────────────────────────────────────────────────
        col_mid  = x + card_w // 2
        team_y   = y + 38
        rank_y   = team_y + 26
 
        # Rank
        r1_text = f"#{m['rank1']}" if m["rank1"] else "—"
        r1w     = text_w(draw, r1_text, f_rank)
        draw.text((col_mid - 30 - r1w, team_y), r1_text, font=f_rank, fill=ACCENT)
 
        # Team name — truncate if too long
        t1 = m["team1"]
        max_name_w = card_w // 2 - 55
        while text_w(draw, t1, f_name) > max_name_w and len(t1) > 4:
            t1 = t1[:-1]
        if t1 != m["team1"]:
            t1 = t1[:-1] + "…"
        t1w = text_w(draw, t1, f_name)
        draw.text((col_mid - 30 - r1w - 8 - t1w, team_y), t1, font=f_name, fill=NAME_COL)
 
        # Class badge team 1
        if m["class1"]:
            cl1 = f"Class {m['class1']}"
            cl1w = text_w(draw, cl1, f_class)
            draw.text((col_mid - 30 - r1w - 8 - cl1w, rank_y), cl1,
                      font=f_class, fill=CLASS_COL)
 
        # ── VS ────────────────────────────────────────────────────────────────
        vs_text = "vs"
        vsw     = text_w(draw, vs_text, f_vs)
        draw.text((col_mid - vsw // 2, team_y + 6), vs_text, font=f_vs, fill=VS_COL)
 
        # ── Team 2 (right side) ───────────────────────────────────────────────
        r2_text = f"#{m['rank2']}" if m["rank2"] else "—"
        draw.text((col_mid + 30, team_y), r2_text, font=f_rank, fill=ACCENT)
        r2w = text_w(draw, r2_text, f_rank)
 
        t2 = m["team2"]
        while text_w(draw, t2, f_name) > max_name_w and len(t2) > 4:
            t2 = t2[:-1]
        if t2 != m["team2"]:
            t2 = t2[:-1] + "…"
        draw.text((col_mid + 30 + r2w + 8, team_y), t2, font=f_name, fill=NAME_COL)
 
        if m["class2"]:
            cl2 = f"Class {m['class2']}"
            draw.text((col_mid + 30 + r2w + 8, rank_y), cl2,
                      font=f_class, fill=CLASS_COL)
 
    # ── Footer ────────────────────────────────────────────────────────────────
    now       = datetime.now(TZ).strftime("%I:%M %p CT")
    footer    = f"Generated {now}  ·  mshsaa.org"
    fw        = text_w(draw, footer, f_footer)
    draw.text(((IMG_W - fw) / 2, IMG_H - 26), footer, font=f_footer, fill=FOOTER_COL)
 
    img.save(OUTPUT_PNG, dpi=(150, 150))
    print(f"Saved: {OUTPUT_PNG}  ({n} matchup{'s' if n != 1 else ''})")
 
 
# ── Entry point ───────────────────────────────────────────────────────────────
 
if __name__ == "__main__":
    print("=== Matchup Image Generator ===")
    date_str, matchups = parse_matchups_md(INPUT_MD)
    print(f"Date: {date_str}")
    print(f"Matchups found: {len(matchups)}")
    render(date_str, matchups)
