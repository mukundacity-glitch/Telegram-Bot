"""FPL VORTEX rotation planner: live official fixtures, no hard-coded clubs.

Runs within the existing news heartbeat. The reference layout is not a data source.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

from .brand_footer import MASTER
from .matchup import _media
from .minimal_theme import background, social_footer

ET = ZoneInfo("America/New_York")
INK = (38, 17, 61)
PURPLE = (73, 25, 111)
FDR = {
    1: ((8, 200, 124), (14, 52, 46)),
    2: ((112, 224, 174), (15, 53, 48)),
    3: ((255, 207, 154), (69, 42, 36)),
    4: ((237, 87, 110), (255, 255, 255)),
    5: ((181, 27, 80), (255, 255, 255)),
}


@dataclass(frozen=True)
class RotationPlan:
    identity: str
    title: str
    caption: str
    gameweek: int
    weeks: tuple[int, ...]
    clubs: tuple[dict, ...]


def build_rotation_plan(snapshot, now: datetime) -> RotationPlan:
    """Choose four complementary PL clubs; verified FDR and transparent option counts."""
    if now.tzinfo is None:
        raise ValueError("Rotation date must have timezone")
    gw = snapshot.gameweek()
    if not isinstance(gw, int) or gw < 1:
        raise ValueError("No upcoming FPL gameweek")
    weeks = tuple(sorted(e["id"] for e in snapshot.events
                         if type(e.get("id")) is int and e["id"] >= gw)[:9])
    if not weeks or weeks[0] != gw:
        raise ValueError("Official future gameweeks missing")
    eligible = {team_id: [] for team_id in snapshot.teams}
    for player in snapshot.players:
        club = player.get("team")
        if (club in eligible and player.get("status") == "a"
                and type(player.get("now_cost")) is int and player["now_cost"] > 0
                and int(player.get("minutes") or 0) >= 270):
            eligible[club].append(player)
    grid = {club: {gw_id: [] for gw_id in weeks} for club in snapshot.teams}
    for fixture in snapshot.fixtures:
        week = fixture.get("event")
        if week not in weeks or fixture.get("finished"):
            continue
        home, away = fixture.get("team_h"), fixture.get("team_a")
        if home not in grid or away not in grid:
            raise ValueError("Unknown club in official fixture")
        for club, opponent, venue, key in (
            (home, away, "H", "team_h_difficulty"),
            (away, home, "A", "team_a_difficulty")
        ):
            score = fixture.get(key)
            grid[club][week].append({
                "opponent": snapshot.teams[opponent].get("short_name") or "TBD",
                "venue": venue,
                "fdr": score if type(score) is int and 1 <= score <= 5 else None,
                "fixture_id": fixture.get("id")
            })
    candidates = [
        club for club in sorted(snapshot.teams)
        if eligible[club] and snapshot.teams[club].get("short_name")
        and type(snapshot.teams[club].get("code")) is int
        and any(grid[club][week] for week in weeks[:5])
    ]
    if len(candidates) < 4:
        raise ValueError("Four eligible current PL clubs unavailable")

    def rotation_score(clubs):
        coverage, depth = 0, 0
        for week in weeks[:5]:
            difficulties = sorted(row["fdr"] for club in clubs
                                  for row in grid[club][week] if row["fdr"] is not None)
            if difficulties:
                coverage += 5 if difficulties[0] <= 2 else 2 if difficulties[0] == 3 else -2
                depth += sum(6 - value for value in difficulties[:2])
        return (coverage, depth, sum(len(eligible[club]) for club in clubs),
                tuple(-club for club in clubs))

    selected = max(combinations(candidates, 4), key=rotation_score)
    clubs = tuple({
        "id": club,
        "name": str(snapshot.teams[club].get("name") or ""),
        "short": str(snapshot.teams[club]["short_name"]),
        "code": int(snapshot.teams[club]["code"]),
        "options": len(eligible[club]),
        "min_price": min(player["now_cost"] for player in eligible[club]) / 10,
        "fixtures": tuple(tuple(grid[club][week]) for week in weeks)
    } for club in selected)
    identity = f"rotation:{now.astimezone(ET).date()}:GW{gw}"
    title = f"FPL VORTEX • ROTATION PLANNER • GW{gw}–{weeks[-1]}"
    caption = "\n".join((
        title,
        "Comparing " + ", ".join(club["short"] for club in clubs) + " over future FPL fixtures.",
        "Green is easier FDR, red harder. Home/away, blanks and doubles are marked.",
        "Options are available assets with 270+ season minutes; price is lowest of these.",
        f"#FPL #GW{gw} #FPLVortex #RotationPlanner"
    ))
    if len(caption) > 1024:
        raise ValueError("Caption too long")
    return RotationPlan(identity, title, caption, gw, weeks, clubs)


def _font(size):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def _center(draw, value, rect, size, fill, minimum=12):
    x0, y0, x1, y1 = rect
    while size > minimum and draw.textbbox((0, 0), value, font=_font(size))[2] > x1 - x0 - 12:
        size -= 1
    font = _font(size)
    bbox = draw.textbbox((0, 0), value, font=font)
    draw.text((x0 + (x1 - x0 - (bbox[2] - bbox[0]))//2,
               y0 + (y1 - y0 - (bbox[3] - bbox[1]))//2 - bbox[1]),
              value, font=font, fill=fill)


def render_rotation_plan(plan: RotationPlan, output: Path,
                         session: requests.Session | None = None) -> Path:
    """Render branded 16:9 matrix; hold publishing if authentic crests are missing."""
    if len(plan.clubs) != 4 or not 1 <= len(plan.weeks) <= 9:
        raise ValueError("Rotation plan must have four clubs and 1–9 gameweeks")
    if not MASTER.is_file():
        raise FileNotFoundError("Approved FPL VORTEX master missing")
    session = session or requests.Session()
    cache = {}
    badges = []
    for club in plan.clubs:
        image = _media(session, club["code"], "crest", cache)
        if image is None:
            raise RuntimeError("Required official Premier League club crest unavailable")
        badges.append(image.convert("RGBA"))
    with Image.open(MASTER) as master:
        if master.width * 9 != master.height * 16:
            raise ValueError("Brand master not 16:9")
        canvas = background(master, plan.identity, (1536, 864))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((28, 79, 1508, 798), radius=18,
                           fill=(250, 248, 253), outline=(205, 188, 220), width=2)
    _center(draw, "ROTATION PLANNER", (322, 85, 1214, 122), 40, INK)
    _center(draw, f"GW{plan.weeks[0]}–GW{plan.weeks[-1]} • FOUR CLUB FIXTURE MATRIX",
            (310, 124, 1225, 149), 20, PURPLE)
    x0, cw, gap = 173, 322, 8
    for i, (club, badge) in enumerate(zip(plan.clubs, badges)):
        x = x0 + i * (cw + gap)
        draw.rounded_rectangle((x, 161, x + cw, 235), radius=13,
                               fill=(233, 224, 241), outline=(201, 185, 215), width=2)
        draw.text((x + 18, 171), club["short"], font=_font(32), fill=PURPLE)
        draw.text((x + 18, 207),
                  f'{club["options"]} options • from £{club["min_price"]:.1f}m',
                  font=_font(17), fill=INK)
        badge.thumbnail((62, 62), Image.Resampling.LANCZOS)
        canvas.paste(badge, (x + 250 + (62 - badge.width)//2,
                             167 + (62 - badge.height)//2), badge)
    step = min(56, 503 // len(plan.weeks))
    for row, gw in enumerate(plan.weeks):
        y = 244 + row * step
        draw.rounded_rectangle((43, y, 160, y + step - 6), radius=10, fill=PURPLE)
        _center(draw, f"GW{gw}", (45, y, 157, y + step - 6), 24, (255, 255, 255))
        for i, club in enumerate(plan.clubs):
            x = x0 + i * (cw + gap)
            matches = club["fixtures"][row]
            if not matches:
                bg, ink, label = (229, 230, 237), INK, "— BLANK"
            else:
                difficulties = [m["fdr"] for m in matches if m["fdr"] is not None]
                bg, ink = FDR[max(difficulties)] if difficulties else ((217, 223, 230), INK)
                label = " / ".join(
                    f'{m["fdr"] if m["fdr"] is not None else "N/A"} '
                    f'{m["opponent"]}({m["venue"]})' for m in matches)
            draw.rounded_rectangle((x, y, x + cw, y + step - 6), radius=11, fill=bg)
            _center(draw, label, (x + 4, y, x + cw - 4, y + step - 6),
                    23 if len(matches) < 2 else 18, ink)
    draw.text((53, 766), "FDR  1 EASIEST", font=_font(17), fill=INK)
    for i, (fdr, (bg, ink)) in enumerate(FDR.items()):
        x = 257 + 72 * i
        draw.rounded_rectangle((x, 761, x + 61, 791), radius=7, fill=bg)
        _center(draw, str(fdr), (x, 761, x + 61, 791), 18, ink)
    draw.text((652, 766), "5 HARDEST  •  H HOME / A AWAY  •  — NO FIXTURE",
              font=_font(17), fill=INK)
    social_footer(canvas, "FPLVortexDailyBot", "@fplvortex")
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp.png")
    canvas.resize((1920, 1080), Image.Resampling.LANCZOS).save(tmp, "PNG", optimize=True)
    with Image.open(tmp) as check:
        if check.size != (1920, 1080):
            raise RuntimeError("Wrong graphic dimensions")
        check.verify()
    tmp.replace(output)
    return output
