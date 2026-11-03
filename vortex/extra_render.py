"""Original broadcast-style layouts based on the existing FPL VORTEX BLUE master.

Three new formats: ten matchup board, one-team attack/defence desk and
four-position transfer suggestions. Do not reuse pixels or copyrighted
layouts from reference screenshots.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
import requests

from .extra_posts import ExtraPost
from .comparison_board import TABLE_YELLOW, TABLE_INK, TABLE_RULE
from .matchup import (ROOT, CANVAS_SIZE, _font, _fitted_font, _text_width,
                      _center_text, _media, _brighten_portrait,
                      CYAN, GOLD, WHITE, MUTED, _fixture_color)

BG = (1, 15, 37, 244)
PANEL = (3, 20, 47, 245)
GREEN = (45, 237, 140)
RED = (250, 110, 135)


def _line(draw: ImageDraw.ImageDraw, value: str, x: int, y: int,
          max_width: int, size: int = 23, color=WHITE, floor: int = 15) -> None:
    value = str(value).replace("\n", " ").strip()
    font = _fitted_font(draw, value, max_width, size, floor)
    if _text_width(draw, value, font) > max_width:
        while value and _text_width(draw, value + "…", font) > max_width:
            value = value[:-1]
        value = value.rstrip() + "…"
    draw.text((x, y), value, font=font, fill=color)


def _paragraph(draw: ImageDraw.ImageDraw, words: str, x: int, y: int, width: int,
               size: int = 19, lines: int = 2, color=WHITE) -> None:
    current = ""
    result = []
    for word in str(words).split():
        trial = (current + " " + word).strip()
        if _text_width(draw, trial, _font(size)) <= width:
            current = trial
        else:
            if current:
                result.append(current)
            current = word
    if current:
        result.append(current)
    for idx, line in enumerate(result[:lines]):
        _line(draw, line, x, y + idx * (size + 5), width, size, color, 14)


def _portrait(canvas: Image.Image, img: Image.Image, left: int, top: int,
              w: int, h: int) -> None:
    player = _brighten_portrait(img.convert("RGBA").copy())
    bbox = player.getchannel("A").getbbox()
    if bbox:
        player = player.crop(bbox)
    player.thumbnail((w, h), Image.Resampling.LANCZOS)
    canvas.paste(player, (left + (w - player.width) // 2,
                          top + h - player.height), player)


def _crest(canvas: Image.Image, img: Image.Image, cx: int, y: int, size: int) -> None:
    image = img.convert("RGBA").copy()
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas.paste(image, (cx - image.width // 2, y + (size - image.height) // 2), image)


def _badge(draw: ImageDraw.ImageDraw, label: str, box: tuple, color=CYAN) -> None:
    draw.rounded_rectangle(box, radius=9, fill=TABLE_YELLOW, outline=TABLE_RULE, width=2)
    x0, y0, x1, y1 = box
    _center_text(draw, (x0 + x1) // 2, y0 + 9, label,
                 _fitted_font(draw, label, x1 - x0 - 10, 21, 14), TABLE_INK)


def _base(post: ExtraPost) -> Image.Image:
    bg = ROOT / "assets/references/brand_background.png"
    if not bg.is_file():
        raise FileNotFoundError("FPL VORTEX blue stadium background not installed")
    with Image.open(bg) as source:
        return ImageOps.fit(source.convert("RGB"), CANVAS_SIZE, method=Image.Resampling.LANCZOS)


def _header(canvas: Image.Image, post: ExtraPost) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle((290, 0, 1335, 142), fill=BG)
    _center_text(draw, 807, 7, post.title.upper(),
                 _fitted_font(draw, post.title.upper(), 1000, 57, 30), WHITE)
    draw.rounded_rectangle((438, 85, 1170, 133), radius=10,
                           fill=BG, outline=(*CYAN, 200), width=2)
    _center_text(draw, 804, 95, post.kicker.upper(),
                 _fitted_font(draw, post.kicker.upper(), 697, 25, 18), CYAN)
    _badge(draw, f"GW{post.gw}", (1380, 90, 1496, 137), GOLD)


def _footer(canvas: Image.Image, post: ExtraPost, detail: str) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle((68, 738, 1468, 796), radius=12, fill=BG,
                           outline=(*CYAN, 217), width=2)
    _center_text(draw, 758, 754, detail.upper(),
                 _fitted_font(draw, detail.upper(), 1290, 24, 17), WHITE)


def _required(session: requests.Session, cache: dict, code: int | None,
              kind: str, subject: str) -> Image.Image:
    result = _media(session, code, kind, cache)
    if result is None:
        raise RuntimeError(f"Verified {kind} unavailable for {subject}; skipping incomplete post")
    return result


def _num(value: object, suffix: str = "", decimal: int = 2) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        return f"{value:.{decimal}f}{suffix}" if isinstance(value, float) else f"{value}{suffix}"
    return "N/A"


def _market_chip(draw: ImageDraw.ImageDraw, x: int, y: int,
                 name: str, value: object, kind: str) -> None:
    """Premium traffic-light fills: green/black is favorable, red/white risky."""
    if kind == "goals":
        favorable = type(value) in (int, float) and value >= 1.65
        risky = type(value) in (int, float) and value <= 0.90
        display = f"{value:.2f}" if type(value) in (int, float) else "N/A"
    else:
        favorable = type(value) in (int, float) and value >= 42
        risky = type(value) in (int, float) and value <= 20
        display = f"{value:.0f}%" if type(value) in (int, float) else "N/A"
    fill, foreground = TABLE_YELLOW, TABLE_INK
    border = GREEN if favorable else RED if risky else TABLE_RULE
    draw.rounded_rectangle((x, y, x + 112, y + 31), radius=7,
                           fill=fill, outline=border, width=2)
    message = f"{name} {display}"
    _center_text(draw, x + 56, y + 6, message,
                 _fitted_font(draw, message, 107, 19, 14), foreground)


def _major_tag(draw: ImageDraw.ImageDraw, x: int, y: int,
               data: dict | None) -> None:
    if not data:
        return
    details = []
    if data.get("goals") is not None:
        details.append(f"prG {data['goals']:+.2f}")
    if data.get("cs_points") is not None:
        details.append(f"CS {data['cs_points']:+.0f}pp")
    if not details:
        return
    label = "MAJOR " + ("DROP" if (data.get("goals") or data.get("cs_points") or 0) < 0 else "RISE")
    label += "  " + " · ".join(details)
    _line(draw, label, x, y, 239, 15, TABLE_INK, 12)


def _fixtures(canvas: Image.Image, post: ExtraPost,
              session: requests.Session, cache: dict) -> str:
    rows = post.fixtures
    if not rows:
        raise ValueError("No official fixtures for matchup board")
    count = len(rows)
    if count == 10:
        if len({club for f in rows for club in (f["home_name"], f["away_name"])}) != 20:
            raise ValueError("Standard 10-game GW must list exactly 20 unique teams")
    draw = ImageDraw.Draw(canvas, "RGBA")
    per_side = (count + 1) // 2
    gutter = 18
    columns = ((31, 755), (780, 1505))
    top, lower = 163, 722
    height = (lower - top - 31) // per_side
    valid = 0
    for idx, match in enumerate(rows):
        side, row = divmod(idx, per_side)
        x0, x1 = columns[side]
        y0 = top + 31 + row * height
        y1 = y0 + height - 8
        draw.rounded_rectangle((x0, y0, x1, y1), radius=12,
                               fill=TABLE_YELLOW, outline=TABLE_RULE, width=2)
        home = _required(session, cache, match.get("home_code"), "crest", match["home"])
        away = _required(session, cache, match.get("away_code"), "crest", match["away"])
        _crest(canvas, home, x0 + 55, y0 + 5, 56)
        _crest(canvas, away, x1 - 52, y0 + 5, 56)
        _line(draw, match["home"], x0 + 96, y0 + 8, 108, 25, TABLE_INK, 18)
        _line(draw, match["away"], x1 - 205, y0 + 8, 105, 25, TABLE_INK, 18)
        _center_text(draw, (x0+x1)//2, y0 + 10, "VS", _font(23), TABLE_INK)
        if match["home_goals"] is not None and match["away_goals"] is not None:
            valid += 1
        # Distinct projected-goals and clean-sheet colored cells for BOTH
        # teams, not FDR. Dark text on green; white text on red.
        for chip_x, side in ((x0 + 92, "home"), (x1 - 346, "away")):
            _market_chip(draw, chip_x, y0 + 43, "prG",
                         match.get(side + "_goals"), "goals")
            _market_chip(draw, chip_x + 120, y0 + 43, "CS",
                         match.get(side + "_cs"), "cs")
            _major_tag(draw, chip_x, y0 + 77,
                       match.get(side + "_major_change"))
    for idx, (x0, x1) in enumerate(columns):
        _line(draw, f"OFFICIAL MATCHUPS {idx*per_side + 1}–{min(count, (idx + 1)*per_side)}",
              x0 + 21, 158, x1-x0-40, 18, GOLD, 16)
    quotes = [x for f in rows for x in (f.get("home_quote_utc"), f.get("away_quote_utc")) if x]
    latest = max(quotes) if quotes else None
    if latest:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        latest_et = datetime.fromisoformat(latest).astimezone(ZoneInfo("America/New_York"))
        quote_note = f" · LATEST BOOK QUOTE {latest_et:%I:%M %p ET}"
    else:
        quote_note = ""
    solio = sum("Solio Analytics" in f.get("odds_source", "") for f in rows)
    book = valid - solio
    if solio:
        detail = f"GOAL/CS: {valid}/{count} · SOLIO MODEL {solio} · VERIFIED BOOKMAKER {max(0, book)}"
    elif valid:
        detail = f"GOAL/CS: {valid}/{count} · VERIFIED BOOKMAKER MODELS"
    else:
        detail = "GOAL/CS DATA UNAVAILABLE · DO NOT SUBSTITUTE FDR"
    changes = sum(bool(f.get(side + "_major_change")) for f in rows
                  for side in ("home", "away"))
    if changes:
        detail += f" · {changes} MAJOR DAILY SHIFTS"
    if count != 10:
        detail = f"GW WITH {count} FIXTURES • " + detail
    return detail


def _chart(canvas: Image.Image, box: tuple[int, int, int, int],
           title: str, values: list[int], labels: list[str],
           accent: tuple[int, int, int]) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=13, fill=PANEL,
                           outline=(*accent, 228), width=2)
    _line(draw, title, x0 + 28, y0 + 17, x1 - x0 - 56, 29, accent)
    if not values:
        _center_text(draw, (x0+x1)//2, y0 + 139, "NO VERIFIED MATCH HISTORY", _font(25), MUTED)
        return
    chart_l, chart_r = x0 + 65, x1 - 26
    base_y, top_y = y1 - 69, y0 + 78
    max_y = max(3, max(values))
    step = (chart_r - chart_l) / len(values)
    for i in range(max_y + 1):
        ty = base_y - i * (base_y - top_y) / max_y
        draw.line((chart_l, int(ty), chart_r, int(ty)), fill=(80, 116, 147, 90), width=1)
    for i, (val, label) in enumerate(zip(values, labels)):
        mid = chart_l + step * (i + 0.5)
        bar_w = min(42, step * 0.52)
        h = (base_y - top_y) * val / max_y
        draw.rounded_rectangle((int(mid-bar_w/2), int(base_y-h), int(mid+bar_w/2), base_y),
                               radius=4, fill=(*accent, 210))
        _center_text(draw, int(mid), int(base_y-h-27), str(val), _font(20), WHITE)
        _center_text(draw, int(mid), base_y+13, label, _fitted_font(draw, label, int(step)-5, 16, 11), MUTED)


def _team(canvas: Image.Image, post: ExtraPost,
          session: requests.Session, cache: dict) -> str:
    team = post.team_analysis
    if not team:
        raise ValueError("Missing team scout data")
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle((33, 155, 1504, 248), radius=12, fill=BG,
                           outline=(*CYAN, 200), width=2)
    logo = _required(session, cache, team.get("code"), "crest", team["team"])
    opponent = _required(session, cache, team.get("opponent_code"), "crest", team["opponent"])
    _crest(canvas, logo, 85, 170, 64)
    _line(draw, team["team"].upper(), 133, 166, 590, 44, WHITE, 28)
    _crest(canvas, opponent, 1220, 174, 58)
    _line(draw, f"NEXT {team['opponent']} ({team['venue']}) · FDR {team['fdr']}",
          896, 196, 295, 22, GOLD)
    hist = team["history"]
    labels = [f"{str(x['opponent'])[:3]} {x['venue']}" for x in hist]
    _chart(canvas, (34, 265, 744, 508), f"ATTACK · GF · {team['period']}",
           [x["gf"] for x in hist], labels, GREEN)
    _chart(canvas, (787, 265, 1502, 508), f"DEFENCE · GA · {team['period']}",
           [x["ga"] for x in hist], labels, CYAN)
    for idx, player in enumerate(team["players"]):
        x0 = 34 + idx * 493
        x1 = x0 + 479
        draw.rounded_rectangle((x0, 526, x1, 721), radius=12, fill=PANEL,
                               outline=(*((CYAN, GOLD, GREEN)[idx]), 218), width=2)
        portrait = _required(session, cache, player.get("photo_code"), "photo", player["name"])
        club_logo = _required(session, cache, player.get("club_code"), "crest", player["team"])
        _portrait(canvas, portrait, x0 + 13, 551, 122, 158)
        _crest(canvas, club_logo, x1 - 40, 542, 49)
        _line(draw, player["name"].upper(), x0 + 143, 546, 263, 25, WHITE, 18)
        draw.rounded_rectangle((x0+140, 579, x1-14, 712), radius=7,
                               fill=TABLE_YELLOW, outline=TABLE_RULE, width=1)
        _line(draw, f"{player['position']} · {player['price']} · FORM {player['form']}",
              x0 + 143, 583, 297, 20, TABLE_INK, 14)
        _line(draw, f"SEASON MINS {player['minutes'] if player['minutes'] is not None else 'N/A'}",
              x0 + 143, 615, 291, 20, TABLE_INK, 14)
        _paragraph(draw, player["opponent"], x0 + 143, 651, 296, 18, 2, WHITE)
    return (f"{team['short']} LAST {len(hist)} FINISHED MATCHES: GF "
            f"{team['gf_total'] if team['gf_total'] is not None else 'N/A'} · "
            f"GA {team['ga_total'] if team['ga_total'] is not None else 'N/A'} · FPL FDR {team['fdr']}")


def _transfers(canvas: Image.Image, post: ExtraPost,
               session: requests.Session, cache: dict) -> str:
    draw = ImageDraw.Draw(canvas, "RGBA")
    rows = post.transfers
    if len(rows) != 4:
        raise ValueError("Transfer comparison must cover GK, DEF, MID, FWD")
    for idx, row in enumerate(rows):
        out, incoming = row["out"], row.get("incoming")
        x0, x1 = 34, 1503
        y0 = 158 + idx * 143
        y1 = y0 + 132
        color = (CYAN, TABLE_INK, TABLE_INK, (168, 135, 255))[idx]
        draw.rounded_rectangle((x0, y0, x1, y1), radius=12, fill=TABLE_YELLOW,
                               outline=(*color, 224), width=2)
        _badge(draw, row["position"], (x0 + 12, y0 + 15, x0 + 92, y0 + 55), color)
        outbound = _required(session, cache, out.get("photo_code"), "photo", out["name"])
        outgoing_crest = _required(session, cache, out.get("club_code"), "crest", out["team"])
        _portrait(canvas, outbound, x0 + 102, y0 + 13, 104, 111)
        _crest(canvas, outgoing_crest, x0 + 227, y0 + 7, 39)
        _line(draw, out["name"].upper(), x0 + 250, y0 + 10, 306, 31, TABLE_INK, 19)
        _line(draw, f"{out['price']} · FORM {out['form']} · FDR {_num(out['fdr'],'',1)}",
              x0 + 250, y0 + 49, 350, 20, TABLE_INK, 16)
        _line(draw, f"OUT EVENT: {_num(out['out_event'], '', 0)} · {out['opponent']}",
              x0 + 250, y0 + 78, 405, 18, TABLE_INK, 13)
        _badge(draw, row["verdict"], (x0 + 682, y0 + 13, x0 + 855, y0 + 54),
               GREEN if incoming else GOLD)
        if incoming:
            pic = _required(session, cache, incoming.get("photo_code"), "photo", incoming["name"])
            crest = _required(session, cache, incoming.get("club_code"), "crest", incoming["team"])
            _portrait(canvas, pic, x0 + 887, y0 + 13, 104, 111)
            _crest(canvas, crest, x0 + 1010, y0 + 7, 39)
            _line(draw, incoming["name"].upper(), x0 + 1034, y0 + 10, 346, 30, TABLE_INK, 18)
            _line(draw, f"{incoming['price']} · FORM {incoming['form']} · FDR {_num(incoming['fdr'],'',1)}",
                  x0 + 1034, y0 + 49, 355, 20, TABLE_INK, 15)
            _line(draw, f"IN EVENT: {_num(incoming['in_event'], '', 0)} · {incoming['opponent']}",
                  x0 + 1034, y0 + 77, 387, 18, TABLE_INK, 13)
        else:
            _line(draw, "HOLD · NO CLEAR SAME-BUDGET UPGRADE", x0 + 885, y0 + 28, 514, 27, TABLE_INK, 18)
        _line(draw, row["reason"], x0 + 108, y0 + 108, x1-x0-139, 15, TABLE_INK, 13)
    return "FOUR POSITIONS · EVENT-TO-DATE TRANSFERS · OFFICIAL NEXT-GW FDR · NO INVENTED xPTS"



def _start_bench(canvas: Image.Image, post: ExtraPost,
                 session: requests.Session, cache: dict) -> str:
    """Two balanced five-player watchlist panels, each with photo and crest."""
    rows = post.start_bench
    if len(rows) != 10 or any(x.get("advice") != ("START" if i < 5 else "BENCH") for i,x in enumerate(rows)):
        raise ValueError("Start/bench board requires exactly five players per group")
    draw = ImageDraw.Draw(canvas, "RGBA")
    for col in range(2):
        x0 = 33 if col == 0 else 784
        x1 = x0 + 717
        accent = GREEN if col == 0 else GOLD
        title = "START WATCHLIST" if col == 0 else "BENCH WATCHLIST"
        draw.rounded_rectangle((x0, 151, x1, 725), radius=14,
                               fill=PANEL, outline=(*accent, 243), width=3)
        _line(draw, title, x0 + 26, 162, 620, 31, accent, 25)
        for j, row in enumerate(rows[col*5:col*5+5]):
            y0 = 212 + j*101
            draw.rounded_rectangle((x0+12, y0, x1-12, y0+94),
                                   radius=10, fill=TABLE_YELLOW, outline=(*accent, 111), width=1)
            photo = _required(session, cache, row.get("photo_code"), "photo", row["name"])
            crest = _required(session, cache, row.get("club_code"), "crest", row["team"])
            _portrait(canvas, photo, x0+20, y0+5, 85, 86)
            _crest(canvas, crest, x0+125, y0+5, 40)
            _line(draw, row["name"].upper(), x0+155, y0+6, 220, 24, TABLE_INK, 18)
            _line(draw, f"{row['pos']} • {row['team']} • {row['price']}", x0+158,
                  y0+39, 255, 19, TABLE_INK, 15)
            _line(draw, f"NEXT {row['opponent']} · FDR {row['fdr']:.1f}",
                  x0+420, y0+11, 265, 18, TABLE_INK, 14)
            _line(draw, f"FORM {row['form']:.1f} • PPG {row['ppg']:.1f} • MINS {row['minutes']}",
                  x0+420, y0+44, 265, 18, TABLE_INK, 14)
            _line(draw, "CHECK LATEST TEAM NEWS", x0+422,
                  y0+70, 259, 15, TABLE_INK, 12)
    return "GENERIC FPL COMPARISONS • NOT YOUR PERSONAL SQUAD • NO FABRICATED xPTS"


def render_extra(post: ExtraPost, output: Path, session: requests.Session) -> Path:
    canvas = _base(post)
    cache = {}
    _header(canvas, post)
    if post.kind == "start_bench":
        detail = _start_bench(canvas, post, session, cache)
    elif post.kind == "projections":
        detail = _fixtures(canvas, post, session, cache)
    elif post.kind == "team_analysis":
        detail = _team(canvas, post, session, cache)
    elif post.kind == "transfer_suggestions":
        detail = _transfers(canvas, post, session, cache)
    else:
        raise ValueError("Unsupported new graphics template")
    _footer(canvas, post, detail)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp.png")
    # Every edition is a true 1920x1080 PNG, without cropping, stretching
    # portraits or rewriting any part of the approved blue master.
    canvas = canvas.resize((1920, 1080), Image.Resampling.LANCZOS)
    canvas.save(tmp, format="PNG", optimize=True)
    tmp.replace(output)
    return output
