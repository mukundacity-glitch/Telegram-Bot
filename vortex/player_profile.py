"""One-player original-blue-master FPL decision board, not a generated slide.

Visuals contain only verified, position-relevant facts and concise advice.
Five successive future Gameweeks are always shown. Doubles have 2 fixtures;
blanks are clearly marked. Independent verified xPts appear immediately under
each associated fixture, otherwise the xPts field is *omitted* (never N/A).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import timezone

from PIL import Image, ImageDraw
import requests

from .brand_footer import MASTER, apply_footer
from .publication_rules import (FDR_COLORS, fetch_verified_xpts,
                                five_gw_fixtures, player_metrics,
                                choose_manager_action)
from .matchup import (_font, _fitted_font, _media, _brighten_portrait,
                      _bundled_portrait)
from .recommendations import completed_rounds, get_history
from .fplcore import completed_gw_enrichment


def _draw_text(draw: ImageDraw.ImageDraw, value: str, x: int, y: int,
               width: int, size: int = 22, color=(243, 251, 255)) -> None:
    val = str(value)
    draw.text((x, y), val, font=_fitted_font(draw, val, width, size, min(14, size)),
              fill=color)


def _panel(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], accent) -> None:
    draw.rounded_rectangle(rect, radius=12, fill=(1, 18, 43, 247),
                           outline=(*accent, 223), width=2)


def render_player_profile(content: Any, snapshot: Any, output: Path,
                          *, session: requests.Session | None = None) -> Path:
    if len(content.cards) != 1:
        raise ValueError("Full 5-GW player profile requires exactly one featured player")
    card = content.cards[0]
    selected = [p for p in snapshot.players
                if snapshot.photo_code(p) == card.photo_code
                and snapshot.team_code(p) == card.team_code
                and snapshot.name(p) == card.headline]
    if len(selected) != 1:
        raise ValueError("Featured player is not uniquely matched to live official FPL")
    p = selected[0]
    if p.get("status") != "a" and p.get("news") is None:
        raise ValueError("No verified player availability")
    if not MASTER.is_file():
        raise FileNotFoundError("Existing FPL VORTEX stadium master missing")
    client = session or requests.Session()
    photo = _media(client, snapshot.photo_code(p), "photo", {})
    if photo is None:
        photo = _bundled_portrait(snapshot.name(p))
    logo = _media(client, snapshot.team_code(p), "crest", {})
    if photo is None or logo is None:
        raise RuntimeError("Full FPL profile needs a verified player photo and authentic club badge")
    metrics = player_metrics(snapshot, p)
    history = get_history(p["id"], client)
    completed = set(completed_rounds(snapshot, 5))
    previous = [r for r in history if r.get("round") in completed and r.get("minutes", 0) > 0]
    if previous:
        pts = [r for r in previous if type(r.get("total_points")) in (int, float)]
        if pts:
            metrics["LAST RETURNS"] = "/".join(str(int(r["total_points"])) for r in pts[-3:])
        metrics["RECENT STARTS"] = f"{sum(int(r.get('minutes') or 0) >= 60 for r in previous[-3:])}/{len(previous[-3:])}"
        if p.get("element_type") in (2, 3, 4):
            threshold = 10 if p.get("element_type") == 2 else 12
            hits = sum(int(r.get("defensive_contribution") or 0) >= threshold for r in previous)
            metrics["DC HIT / GAMES"] = f"{hits}/{len(previous)}"
            metrics["DC AWARDED PTS"] = str(hits * 2)
    # An optional read-only completed-GW public FPL Core dataset is joined by
    # exact official player + current club code. FPL remains authoritative.
    enrichment = completed_gw_enrichment(snapshot, client, snapshot.fetched_at)
    extra = enrichment.get(p["id"], {})
    if "gw_tackles" in extra and p.get("element_type") == 2:
        metrics["LAST GW TACKLES"] = str(int(extra["gw_tackles"]))
    if "gw_clearances_blocks_interceptions" in extra and p.get("element_type") == 2:
        metrics["LAST GW CBI"] = str(int(extra["gw_clearances_blocks_interceptions"]))
    expected = fetch_verified_xpts(snapshot.fetched_at.astimezone(timezone.utc), snapshot, client)
    fixtures = five_gw_fixtures(snapshot, p, expected)
    action, reason = choose_manager_action(p, fixtures, previous[-3:])
    # Avoid policy-inappropriate "SELL" if club player remains in unusually
    # strong form despite one hard fixture; this is advice, not a guarantee.
    with Image.open(MASTER) as template:
        canvas = template.convert("RGB")
    draw = ImageDraw.Draw(canvas, "RGBA")
    cyanish = (45, 220, 249)
    green = (54, 238, 150)
    gold = (242, 193, 89)
    _panel(draw, (39, 90, 1500, 158), cyanish)
    _draw_text(draw, f"{snapshot.name(p).upper()} • {snapshot.team(p).upper()}",
               425, 101, 835, 42)
    _draw_text(draw, f"GW{snapshot.gameweek()} • {metrics['POSITION']}",
               1240, 111, 225, 25, gold)
    _panel(draw, (39, 174, 492, 728), cyanish)
    portrait = _brighten_portrait(photo.convert("RGBA").copy())
    box = portrait.getchannel("A").getbbox()
    if box:
        portrait = portrait.crop(box)
    portrait.thumbnail((410, 440), Image.Resampling.LANCZOS)
    canvas.paste(portrait, (266 - portrait.width//2, 260 + 440-portrait.height), portrait)
    badge = logo.convert("RGBA").copy()
    badge.thumbnail((89, 89), Image.Resampling.LANCZOS)
    canvas.paste(badge, (70, 196), badge)
    draw = ImageDraw.Draw(canvas, "RGBA")
    _draw_text(draw, snapshot.name(p).upper(), 77, 675, 390, 32, gold)

    _panel(draw, (514, 174, 1495, 505), cyanish)
    ordered = ["PRICE", "OWNERSHIP", "TOTAL PTS", "FORM", "MINUTES",
               "LAST RETURNS", "CS", "DC ACTIONS", "DC AWARDED PTS",
               "GOALS", "ASSISTS", "xG", "xA", "xGI", "SAVES",
               "xGC", "RECENT STARTS", "DC HIT / GAMES", "LAST GW TACKLES",
               "LAST GW CBI", "GC"]
    relevant = [(key, metrics[key]) for key in ordered if key in metrics]
    # 12 readable tiles per panel; all extras recorded internally.
    for index, (label, value) in enumerate(relevant[:12]):
        col, row = index % 4, index // 4
        x, y = 526 + col*239, 188 + row*100
        draw.rounded_rectangle((x, y, x+225, y+88), radius=8,
                               fill=(4, 34, 66, 240), outline=(70, 152, 200, 150), width=1)
        _draw_text(draw, label, x+14, y+8, 204, 17, cyanish)
        _draw_text(draw, str(value), x+15, y+35, 198, 33, gold)

    _panel(draw, (516, 516, 1496, 729), gold)
    _draw_text(draw, "NEXT FIVE GAMEWEEKS • FIXTURE DIFFICULTY",
               535, 522, 920, 23, gold)
    # Exactly five GW columns. Each column allows two independently scored
    # matches; multiple fixtures on the same GW remain distinct.
    grouped = {k: [r for r in fixtures if r["gw"] == k]
               for k in range(snapshot.gameweek(), min(39, snapshot.gameweek()+5))}
    for index, (gw, rows) in enumerate(grouped.items()):
        x0 = 527 + index * 192
        _draw_text(draw, f"GW{gw}", x0+7, 554, 165, 22, (255, 255, 255))
        for n, fi in enumerate(rows[:2]):
            y0 = 582 + n * 70
            color = (104, 138, 171) if fi["blank"] else tuple(bytes.fromhex(FDR_COLORS[fi["fdr"]][1:]))
            draw.rounded_rectangle((x0+5, y0, x0+181, y0+60),
                                   radius=6, fill=(2, 29, 59, 248), outline=(*color, 255), width=2)
            if fi["blank"]:
                _draw_text(draw, "BLANK", x0+17, y0+14, 154, 21, (224, 233, 243))
            else:
                _draw_text(draw, f"{fi['opponent']} ({fi['venue']})  FDR {fi['fdr']}",
                           x0+15, y0+5, 162, 18, color)
                if fi["xpts"] is not None:
                    _draw_text(draw, f"xPts {fi['xpts']:.2f}",
                               x0+16, y0+31, 157, 20, (242, 244, 254))
    # Finish with existing footer restoration and real handles.
    _draw_text(draw, f"{action} • {reason}", 556, 741, 895, 21, green)
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch = output.with_suffix(".staging.png")
    canvas.resize((1920, 1080), Image.Resampling.LANCZOS).save(scratch, "PNG", optimize=True)
    scratch.replace(output)
    apply_footer(output, verdict=f"{action} • {reason}")
    return output
