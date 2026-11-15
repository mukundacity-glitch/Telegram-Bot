"""FPL VORTEX portrait board with three independently sorted tables."""
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw

from .brand_footer import MASTER, verify_exact_master
from .comparison_board import CYAN, GOLD, WHITE, contain, text
from .matchup import _media
from .minimal_theme import social_footer
from .publication_rules import required_footer_handles


def render_odds_board(plan, output, session):
    verify_exact_master()
    rows = plan.extra["rows"]
    codes = {row["team_code"] for row in rows} | {row["opponent_code"] for row in rows}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {code: pool.submit(_media, session, code, "crest", {}) for code in codes}
        crests = {code: job.result() for code, job in jobs.items()}

    market = plan.extra.get("market_outlook", False)
    one_image = getattr(plan, "edition", None) == "afternoon-rotation"
    columns = (
        ("PROJECTED GOALS", "goals"),
        ("CLEAN SHEET %", "clean_sheet"),
        ("WIN PROBABILITY", "win") if market else ("FIXTURE DIFFICULTY", "fdr"),
    )
    ranked = [
        sorted(rows, key=lambda row: (row[key] is None,
               (row[key] or 0) * (1 if key == "fdr" else -1), row["team"], row["fixture"]))
        for _, key in columns
    ]
    pages = []
    rows_per_page = len(rows) if one_image else 20
    row_height = min(64, (980 if market else 1280) // rows_per_page)
    total_pages = (len(rows) + rows_per_page - 1) // rows_per_page
    for page in range(total_pages):
        canvas = Image.new("RGB", (1080, 1920), "#09152e")
        with Image.open(MASTER) as master:
            masthead = master.crop((0, 0, master.width, round(master.height * .072)))
            canvas.paste(masthead.resize((1080, 65), Image.Resampling.LANCZOS), (0, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")
        text(draw, f"GAMEWEEK {plan.gw}", 32, 93, 1016, 32, GOLD, center=True)
        text(draw, "MARKET OUTLOOK" if market else "PROJECTED GOALS & CLEAN SHEETS", 32, 143, 1016, 48, WHITE, center=True)
        coverage = ("LAYOUT PREVIEW  •  SAMPLE NUMBERS" if plan.extra.get("preview")
                    else f"{plan.extra['edition_date']} ET  •  MARKET {plan.extra['market_count']}  •  SOLIO MODEL {plan.extra['solio_count']}  •  {plan.extra['covered']}/{plan.extra['fixture_count']} MATCHES")
        text(draw, coverage, 32, 211, 1016, 24, CYAN, center=True)
        for index, (label, key) in enumerate(columns):
            x = 28 + 346 * index
            text(draw, label, x, 279, 332, 27, CYAN, center=True)
            draw.rounded_rectangle((x, 324, x+332, 369), 7, fill="#213b60")
            text(draw, "CLUB", x+14, 334, 120, 22, WHITE)
            text(draw, "OPPONENT / " + ("FDR" if key == "fdr" else "FORECAST"),
                 x+139, 335, 180, 19, WHITE, center=True)
            for i, row in enumerate(ranked[index][page*rows_per_page:(page+1)*rows_per_page]):
                y = 376 + i * row_height
                inset = max(3, row_height // 8)
                icon = min(43, row_height - 2 * inset)
                label_size = min(25, row_height - 14)
                v = row[key]
                if v is None:
                    value, fill = "—", "#25334c"
                elif key == "fdr":
                    value = f"{row['opponent']} ({row['venue']}) · {v}"
                    fill = ("#174a45", "#17534f", "#293e62", "#624330", "#6c2944")[v-1]
                else:
                    value = f"{v:.2f}" if key == "goals" else f"{v:.0f}%"
                    threshold = (2.0, 1.6, 1.1) if key == "goals" else (40, 30, 19)
                    fill = ("#145349" if v >= threshold[0] else "#194644" if v >= threshold[1]
                            else "#293e62" if v >= threshold[2] else "#622845")
                draw.rounded_rectangle((x, y, x+332, y+row_height-5), 6, fill="#152747")
                draw.rounded_rectangle((x+129, y+3, x+329, y+row_height-8), 5, fill=fill)
                crest = crests[row["team_code"]]
                if crest is not None:
                    contain(canvas, crest, (x+8, y+inset, icon, icon))
                text(draw, row["team"], x+54, y+inset, 70, label_size, WHITE)
                if key != "fdr":
                    opponent = crests[row["opponent_code"]]
                    if opponent is not None:
                        contain(canvas, opponent, (x+273, y+inset, icon, icon))
                    else:
                        text(draw, row["opponent"], x+270, y+inset, 49, min(18, label_size), WHITE, center=True)
                text(draw, value, x+134, y+inset, 189 if key == "fdr" else 132, label_size, WHITE, center=True)
                if key != "fdr" and row.get("source") == "solio":
                    text(draw, "S", x+139, y+inset, 22, 15, GOLD)
        if market:
            draw_market_fixtures(draw, rows)
            leaders = [max((r for r in rows if r[key] is not None), key=lambda r: r[key])
                       for key in ("goals", "clean_sheet", "win")]
            attack, defence, win = leaders
            takeaway = (f"{attack['team']} {attack['goals']:.2f} GOALS   ·   "
                        f"{defence['team']} {defence['clean_sheet']:.0f}% CLEAN SHEET   ·   "
                        f"{win['team']} {win['win']:.0f}% WIN")
            text(draw, takeaway, 34, 1661, 1012, 19, GOLD, center=True)
        draw.line((34, 1693, 1046, 1693), fill=CYAN, width=2)
        text(draw, ("THE ODDS API • MARKET IMPLIED • —: NO VERIFIED MARKET" if market else
                    "FDR: OFFICIAL FPL 1–5  •  S: SOLIO ANALYTICS MODEL  •  —: NO VERIFIED FIGURE"), 36, 1715, 1008, 22, WHITE, center=True)
        text(draw, ("ONE ROW PER CLUB FIXTURE" if one_image else
                    f"ONE ROW PER CLUB FIXTURE   •   PAGE {page+1}/{total_pages}"),
             36, 1751, 1008, 19, GOLD, center=True)
        social_footer(canvas, *required_footer_handles())
        path = output if total_pages == 1 else output.with_stem(f"{output.stem}-{page+1}")
        path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(path, "PNG", optimize=True)
        pages.append(path)
    return pages


def draw_market_fixtures(draw, rows):
    home = [row for row in rows if row['venue'] == 'H']
    away = {row['fixture']: row for row in rows if row['venue'] == 'A'}
    text(draw, "FIXTURES  ·  HOME / AWAY  ·  PROJECTED GOALS", 34, 1368, 1012, 25, CYAN, center=True)
    half = (len(home) + 1) // 2
    height = min(48, 250 // half)
    for index, row in enumerate(home):
        x = 30 + (index // half) * 515
        y = 1410 + (index % half) * height
        other = away[row['fixture']]
        draw.rounded_rectangle((x, y, x + 500, y + height - 4), 5, fill="#152747")
        text(draw, f"{row['team']}  vs  {other['team']}", x + 10, y + 3, 270, min(24, height - 8), WHITE)
        figures = "  /  ".join(f"{side['goals']:.2f}" if side['goals'] is not None else "—"
                               for side in (row, other))
        text(draw, figures, x + 280, y + 3, 209, min(24, height - 8), GOLD, center=True)
