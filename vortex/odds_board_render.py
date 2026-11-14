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

    columns = (
        ("PROJECTED GOALS", "goals"),
        ("CLEAN SHEET %", "clean_sheet"),
        ("FIXTURE DIFFICULTY", "fdr"),
    )
    ranked = [
        sorted(rows, key=lambda row: (row[key] is None,
               (row[key] or 0) * (1 if key == "fdr" else -1), row["team"], row["fixture"]))
        for _, key in columns
    ]
    pages = []
    total_pages = (len(rows) + 19) // 20
    for page in range(total_pages):
        canvas = Image.new("RGB", (1080, 1920), "#09152e")
        with Image.open(MASTER) as master:
            masthead = master.crop((0, 0, master.width, round(master.height * .072)))
            canvas.paste(masthead.resize((1080, 65), Image.Resampling.LANCZOS), (0, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")
        text(draw, f"GAMEWEEK {plan.gw}", 32, 93, 1016, 32, GOLD, center=True)
        text(draw, "PROJECTED GOALS & CLEAN SHEETS", 32, 143, 1016, 48, WHITE, center=True)
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
            for i, row in enumerate(ranked[index][page*20:(page+1)*20]):
                y = 376 + i * 64
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
                draw.rounded_rectangle((x, y, x+332, y+59), 6, fill="#152747")
                draw.rounded_rectangle((x+129, y+3, x+329, y+56), 5, fill=fill)
                crest = crests[row["team_code"]]
                if crest is not None:
                    contain(canvas, crest, (x+8, y+8, 43, 43))
                text(draw, row["team"], x+54, y+14, 70, 24, WHITE)
                if key != "fdr":
                    opponent = crests[row["opponent_code"]]
                    if opponent is not None:
                        contain(canvas, opponent, (x+273, y+9, 41, 41))
                    else:
                        text(draw, row["opponent"], x+270, y+18, 49, 18, WHITE, center=True)
                text(draw, value, x+134, y+13, 189 if key == "fdr" else 132, 25, WHITE, center=True)
                if key != "fdr" and row.get("source") == "solio":
                    text(draw, "S", x+139, y+20, 22, 15, GOLD)
        draw.line((34, 1693, 1046, 1693), fill=CYAN, width=2)
        text(draw, "FDR: OFFICIAL FPL 1–5  •  S: SOLIO ANALYTICS MODEL  •  —: NO VERIFIED FIGURE", 36, 1715, 1008, 22, WHITE, center=True)
        text(draw, f"ONE ROW PER CLUB FIXTURE   •   PAGE {page+1}/{total_pages}",
             36, 1751, 1008, 19, GOLD, center=True)
        social_footer(canvas, *required_footer_handles())
        path = output if total_pages == 1 else output.with_stem(f"{output.stem}-{page+1}")
        path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(path, "PNG", optimize=True)
        pages.append(path)
    return pages
