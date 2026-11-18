"""Premium 16:9 graphics for the day-specific verified FPL VORTEX editions.

Uses the existing authenticated master and social footer. Rendering never
initiates delivery. Every team crest comes from its official FPL club code.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from .autonomous_render import _base, _save
from .comparison_board import CYAN, GOLD, WHITE, contain, text
from .editorial_inputs import RequiredInput
from .matchup import _media
from .minimal_theme import social_footer

BACKGROUND = "#0c1838"
TILE = "#152853"
MUTED = "#B5C7E5"
RULE = "#3A5883"
GREEN = "#42DDA2"
LILAC = "#C4A4FF"
AMBER = "#FFCB6B"
RED = "#F47786"


def _crest(canvas, session, cache, code, x, y, size):
    if not code:
        return
    asset = _media(session, code, "crest", cache)
    if asset is None:
        raise RequiredInput(f"Verified club crest unavailable for code {code}")
    contain(canvas, asset, (int(x), int(y), int(size), int(size)))


def _label(draw, value, x, y, width, size=16, color=WHITE, center=False):
    text(draw, str(value), x, y, width, size, color,
         minimum=max(10, size - 4), center=center)


def _board(plan, subtitle):
    canvas = _base(plan.title, plan.gw, subtitle)
    return canvas, ImageDraw.Draw(canvas, "RGBA")


def _footnote(draw, words):
    draw.rounded_rectangle((28, 750, 1508, 777), 7, fill="#162650")
    _label(draw, words, 36, 755, 1460, 17, MUTED, center=True)


def _header(draw, labels, xs, widths, y=132, height=40):
    draw.rounded_rectangle((28, y, 1508, y + height), 9, fill="#21345e",
                           outline=CYAN, width=1)
    for label, x, width in zip(labels, xs, widths):
        _label(draw, label, x, y + 9, width, 17, CYAN, center=True)


def _set_pieces(plan, output, session):
    """Each of the 20 clubs has independently ranked duties, not global leaders."""
    rows = plan.extra["rows"]
    if len(rows) != 20:
        raise RequiredInput("Set-piece graphic requires 20 current PL club rows")
    canvas, draw = _board(plan, f"GW{plan.gw} • OFFICIAL FPL SET-PIECE PECKING ORDER • 270+ MIN")
    headings = (("CORNERS / INDIRECT FK", GREEN), ("DIRECT FREE KICKS", GOLD),
                ("PENALTIES", LILAC))
    counts = plan.extra["leader_counts"]
    for i, (heading, colour) in enumerate(headings):
        x = 30 + i * 502
        draw.rounded_rectangle((x, 106, x + 484, 202), 15,
                               fill=BACKGROUND, outline=colour, width=2)
        _label(draw, heading, x + 12, 119, 460, 20, colour, center=True)
        _label(draw, f"{counts[i]} / 20 CLUBS HAVE RANK 1", x + 12, 157,
               460, 25, WHITE, center=True)

    _label(draw, "CLUB", 50, 208, 135, 17, CYAN)
    _label(draw, "CORNERS", 208, 208, 174, 17, GREEN, center=True)
    _label(draw, "FREE KICKS", 384, 208, 174, 17, GOLD, center=True)
    _label(draw, "PENALTIES", 558, 208, 174, 17, LILAC, center=True)
    _label(draw, "CLUB", 802, 208, 135, 17, CYAN)
    _label(draw, "CORNERS", 960, 208, 174, 17, GREEN, center=True)
    _label(draw, "FREE KICKS", 1136, 208, 174, 17, GOLD, center=True)
    _label(draw, "PENALTIES", 1309, 208, 174, 17, LILAC, center=True)
    cache = {}
    for n, row in enumerate(rows):
        column, index = divmod(n, 10)
        x = 30 + column * 752
        y = 232 + index * 50
        draw.rounded_rectangle((x, y, x + 724, y + 45), 8,
                               fill=BACKGROUND if index % 2 else TILE,
                               outline=RULE, width=1)
        _crest(canvas, session, cache, row["code"], x + 8, y + 6, 30)
        _label(draw, row["club"], x + 47, y + 12, 122, 20)
        for j, duty in enumerate(row["duties"]):
            bx = x + 177 + j * 176
            draw.rounded_rectangle((bx, y + 4, bx + 167, y + 40), 7,
                                   fill="#20355e",
                                   outline=(GREEN, GOLD, LILAC)[j], width=1)
            if duty is None:
                name = "UNVERIFIED"
                ink = MUTED
            else:
                name = f'{duty["name"]} #{duty["order"]}'
                ink = WHITE if duty["order"] == 1 else MUTED
            _label(draw, name, bx + 4, y + 12, 159, 16, ink, center=True)
    _footnote(draw, "Official FPL per-club order • rank 1 = first choice • not corners, free kicks or chances per 90.")
    return _save(canvas, output)

def _predicted_xg(plan, output, session):
    weeks = plan.extra["weeks"]
    rows = plan.extra["rows"]
    model = ("FPL xG-RATE MODEL" if plan.extra["model"] == "official-FPL-xG-rate-v1"
             else "VORTEX MODEL xG")
    canvas, draw = _board(plan, f"GW{weeks[0]}–GW{weeks[-1]} • {model} • 20 PREMIER LEAGUE CLUBS")
    gap = 5
    first_x = 332
    cell_w = int(945 / len(weeks))
    for j, week in enumerate(weeks):
        _label(draw, f"GW{week}", first_x + j * cell_w, 112, cell_w - gap, 20, CYAN, center=True)
    _label(draw, "TOTAL", 1302, 112, 91, 19, GOLD, center=True)
    _label(draw, "AVG", 1400, 112, 90, 19, GOLD, center=True)
    cache = {}
    for i, row in enumerate(rows):
        y = 147 + i * 30
        draw.rounded_rectangle((30, y, 1507, y + 28), 8,
                               fill=TILE if i % 2 else BACKGROUND)
        _crest(canvas, session, cache, row["code"], 36, y + 3, 23)
        _label(draw, row["name"], 66, y + 4, 245, 17)
        for j, cell in enumerate(row["cells"]):
            x = first_x + j * cell_w
            value = cell["xg"]
            fill = "#205c53" if value >= 2 else "#384a59" if value >= 1.3 else "#66394b"
            draw.rounded_rectangle((x + 3, y + 2, x + cell_w - 7, y + 26),
                                   5, fill=fill, outline=RULE)
            opponents = cell["opponents"]
            if not opponents:
                _label(draw, "BLANK", x + 7, y + 5, cell_w - 17, 16, MUTED, center=True)
                continue
            for index, opponent in enumerate(opponents):
                _crest(canvas, session, cache, opponent["code"], x + 8 + 20 * index, y + 5, 17)
            labels = " + ".join(f'{opp["opp"]}({opp["venue"]})' for opp in opponents)
            start = x + 10 + 20 * len(opponents)
            text(draw, labels, start, y + 6, x + cell_w - 52 - start, 14, WHITE, minimum=9)
            _label(draw, f"{value:.2f}", x + cell_w - 48, y + 4, 42, 17, WHITE, center=True)
        _label(draw, f'{row["total"]:.2f}', 1302, y + 5, 91, 16, GOLD, center=True)
        _label(draw, f'{row["average"]:.2f}', 1400, y + 5, 90, 16, WHITE, center=True)
    _footnote(draw, f'Model: {plan.extra["model"]} • xG is estimated, not observed • double fixtures are summed.')
    return _save(canvas, output)


def _attacking_zones(plan, output, session):
    rows = plan.extra["rows"]
    canvas, draw = _board(plan,
                          f"THROUGH GW{plan.extra['through']} • LAST {len(plan.extra['weeks'])} COMPLETED ROUNDS")
    _label(draw, "RANK / TEAM", 42, 112, 340, 19, CYAN)
    _label(draw, "LEFT  •  CENTRE  •  RIGHT  (SHARE OF SHOTS)", 408, 112, 917, 19, CYAN)
    _label(draw, "SHOTS", 1392, 112, 109, 19, CYAN, center=True)
    cache = {}
    colours = ("#73849A", "#576EDF", "#89B7B7")
    for i, row in enumerate(rows):
        y = 141 + 30 * i
        draw.rounded_rectangle((28, y, 1508, y + 29), 7,
                               fill=BACKGROUND if i % 2 else TILE)
        _label(draw, f"{i+1:02d}", 41, y + 4, 37, 15, GOLD)
        _crest(canvas, session, cache, row["code"], 81, y + 2, 25)
        _label(draw, row["name"], 116, y + 4, 267, 17, WHITE)
        left = 398
        width = 934
        used = 0
        for key, colour in zip(("left", "centre", "right"), colours):
            percentage = row[key]
            segment = (width * percentage / 100
                       if key != "right" else width - used)
            right = left + used + segment
            if segment > 0:
                draw.rectangle((left + used, y + 3, right, y + 26),
                               fill=colour)
            if segment > 55:
                _label(draw, f"{percentage:.0f}%", left + used + 2, y + 6,
                       segment - 4, 15, WHITE, center=True)
            used += segment
        _label(draw, row["shots"], 1385, y + 5, 109, 17, WHITE, center=True)
    _footnote(draw, "FPL Core shot origin locations • not total attacking entries or FotMob attack-channel data.")
    return _save(canvas, output)


def _rotation(plan, output, session):
    rows = plan.extra["rows"]
    canvas, draw = _board(plan, f"GW{rows[0]['gw']}–GW{rows[-1]['gw']} • LIVE DEFENSIVE ROTATION")
    clubs = rows[0]["choices"]
    cache = {}
    for j, club in enumerate(clubs):
        x = 35 + j * 749
        draw.rounded_rectangle((x, 116, x + 718, 207), 16,
                               fill=BACKGROUND, outline=CYAN if j == 0 else LILAC, width=2)
        _crest(canvas, session, cache, club["code"], x + 22, 125, 69)
        _label(draw, club["name"] + " • DEFENSIVE ROTATION", x + 109, 142, 586, 28)
    cols = [37, 123, 395, 736, 837, 1109, 1437]
    widths = [65, 268, 325, 83, 266, 317, 66]
    _header(draw, ["GW", clubs[0]["name"], "OPP / FDR / CS%",
                   "GW", clubs[1]["name"], "OPP / FDR / CS%", "PICK"], cols, widths, y=224, height=39)
    for i, row in enumerate(rows):
        y = 270 + i * 43
        draw.rounded_rectangle((31, y, 1507, y + 38), 9,
                               fill=TILE if i % 2 else BACKGROUND)
        for j, option in enumerate(row["choices"]):
            base = 36 if j == 0 else 836
            chosen = row["chosen"] == option["team"]
            if chosen:
                draw.rounded_rectangle((base + 6, y + 4, base + 686, y + 34), 8,
                                       fill="#154a44", outline=GREEN)
            _label(draw, "GW" + str(row["gw"]), base + 8, y + 10, 66, 17, GOLD)
            _crest(canvas, session, cache, option["code"], base + 92, y + 6, 26)
            _label(draw, option["name"], base + 125, y + 10, 150, 18, WHITE)
            if option["opp"] == "BLANK":
                details = "BLANK • no scheduled match"
            else:
                details = (f'{option["opp"]} ({option["venue"]}) • '
                           f'FDR {option["fdr"]:.1f} • '
                           f'CS {option["cs"]:.0f}%' if option["cs"] is not None
                           else f'{option["opp"]} ({option["venue"]}) • FDR {option["fdr"]:.0f} • CS —')
            _label(draw, details, base + 278, y + 10, 407, 17, WHITE)
    _footnote(draw, "GREEN = PREFERRED TEAM BY VERIFIED CS% WHEN AVAILABLE; OTHERWISE OFFICIAL FDR. NO CS GUARANTEES.")
    return _save(canvas, output)


def _fdr_colour(value):
    return {1: "#D3FF77", 2: "#ADFA65", 3: "#D4D4D8",
            4: "#E10931", 5: "#60051D"}[value]


def _fdr(plan, output, session):
    """Keep the reference's cyan sheet, dense square grid and FDR colour scale."""
    weeks = plan.extra["weeks"]
    canvas = Image.new("RGB", (1080, 1920))
    draw = ImageDraw.Draw(canvas)
    for x in range(canvas.width):
        fraction = x / (canvas.width - 1)
        colour = (round(12 + 86*fraction), round(233 - 56*fraction), 242)
        draw.line((x, 0, x, 1920), fill=colour)
    ink, rule, blue = "#091C48", "#153960", "#5BD2F5"
    _label(draw, plan.title, 24, 34, 1032, 56, ink, center=True)
    _label(draw, f"GW{weeks[0]} – GW{weeks[-1]}", 24, 108, 1032, 39, ink, center=True)
    left, team_width, header_y, row_height = 24, 131, 175, 73
    width = (1032 - team_width) / (len(weeks) + 1)
    cols = [(left, team_width)] + [(left + team_width + n*width, width)
                                   for n in range(len(weeks) + 1)]
    headers = ["TEAM", *(f"GW{gw}" for gw in weeks), "AVG FDR"]
    for title, (x, w) in zip(headers, cols):
        draw.rectangle((x, header_y, x+w, header_y+54), fill=blue, outline=rule, width=2)
        _label(draw, title, x+2, header_y+14, w-4, 23, ink, center=True)
    cache = {}
    for i, row in enumerate(plan.extra["rows"]):
        y = header_y + 54 + i*row_height
        draw.rectangle((left, y, left+team_width, y+row_height), fill=blue, outline=rule, width=2)
        _crest(canvas, session, cache, row["code"], left+10, y+18, 36)
        _label(draw, row["short"], left+50, y+23, team_width-56, 27, ink)
        for j, matches in enumerate(row["cells"], 1):
            x, w = cols[j]
            if not matches:
                draw.rectangle((x, y, x+w, y+row_height), fill="#D4D4D8", outline=rule, width=2)
                _label(draw, "BLANK", x+1, y+24, w-2, 19, ink, center=True)
            for k, match in enumerate(matches):
                h = row_height / len(matches)
                top = y + k*h
                value = match["fdr"]
                colour = WHITE if value >= 4 else ink
                draw.rectangle((x, top, x+w, top+h), fill=_fdr_colour(value), outline=rule, width=2)
                crest_size = 27 if len(matches) == 1 else min(24, int(h)-5)
                _crest(canvas, session, cache, match["code"], x+6, top+5, crest_size)
                label = f'{match["opp"]}({match["venue"]})'
                if len(matches) == 1:
                    _label(draw, label, x+36, top+9, w-39, 20, colour)
                    _label(draw, f"{value:.1f}", x+2, top+36, w-4, 25, colour, center=True)
                else:
                    _label(draw, f"{label} {value:.1f}", x+crest_size+9, top+5, w-crest_size-11, 14, colour)
        x, w = cols[-1]
        draw.rectangle((x, y, x+w, y+row_height), fill=blue, outline=rule, width=2)
        _label(draw, f'{row["average"]:.1f}', x+2, y+21, w-4, 28, ink, center=True)
    _label(draw, "OFFICIAL FPL FDR   •   1 EASIEST, 5 HARDEST   •   AVERAGE PER FIXTURE",
           24, 1713, 1032, 20, ink, center=True)
    social_footer(canvas)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "PNG", optimize=True)
    return output


def render_evening(plan, output, session):
    functions = {
        "set_pieces": _set_pieces,
        "predicted_xg": _predicted_xg,
        "attacking_zones": _attacking_zones,
        "rotation_planner": _rotation,
        "fdr_grid": _fdr,
    }
    render = functions.get(plan.kind)
    if render is None:
        raise ValueError("Unsupported verified evening graphic")
    return render(plan, output, session)
