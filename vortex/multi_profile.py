"""Readable blue-master multi-player comparison, with five fixture GW rows per player.

For 2-4 players this replaces cramped old tiles only when opt-in strict
visuals are enabled. Authentic current club/portrait assets are mandatory.
"""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw
import requests

from .brand_footer import MASTER, apply_footer
from .matchup import _font, _fitted_font, _media, _bundled_portrait
from .publication_rules import (
    FDR_COLORS, five_gw_fixtures, fetch_verified_xpts,
    player_metrics, choose_manager_action,
)
from .recommendations import get_history, completed_rounds


def _text(draw, value, x, y, w, fontsize=21, color=(245, 251, 255)):
    label = str(value)
    draw.text((x, y), label,
              font=_fitted_font(draw, label, w, fontsize, min(13, fontsize)),
              fill=color)


def render_multi_profile(post, snapshot, output: Path, session=None) -> Path:
    cards = tuple(post.cards)
    if not 2 <= len(cards) <= 4:
        raise RuntimeError("Multi-player infographic supports 2 to 4 current players")
    client = session or requests.Session()
    with Image.open(MASTER) as original:
        if original.width * 9 != original.height * 16:
            raise RuntimeError("Approved master aspect ratio differs from required 16:9")
        canvas = original.convert("RGB").resize((1536, 864), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle((38, 96, 1497, 155), radius=10,
                           fill=(1, 17, 41, 245),
                           outline=(43, 207, 251, 210), width=2)
    title = post.title.upper()
    if "API" in title or "SOURCE" in title or "OFFICIAL FPL AVAILABILITY" in title:
        title = "PLAYER DECISION DESK"
    _text(draw, title, 59, 104, 1110, 38)
    _text(draw, f"GW{post.gw}", 1376, 111, 100, 29, (244, 202, 96))
    gap = 14
    width = (1470 - gap*(len(cards)-1))//len(cards)
    xpts = fetch_verified_xpts(snapshot.fetched_at, snapshot, client)
    completed = set(completed_rounds(snapshot, 4))
    cache = {}
    for idx, card in enumerate(cards):
        x0 = 34 + idx*(width+gap)
        x1 = x0 + width
        players = [p for p in snapshot.players
                   if snapshot.photo_code(p) == card.photo_code
                   and snapshot.team_code(p) == card.team_code
                   and snapshot.name(p) == card.headline]
        if len(players) != 1:
            raise RuntimeError("Featured card is not a unique verified current FPL player")
        player = players[0]
        portrait = _media(client, card.photo_code, "photo", cache)
        if portrait is None:
            portrait = _bundled_portrait(card.headline)
        badge = _media(client, card.team_code, "crest", cache)
        if portrait is None or badge is None:
            raise RuntimeError("Full verified portrait and authentic crest mandatory")
        history = get_history(player["id"], client)
        recent = [r for r in history if r.get("round") in completed
                  and int(r.get("minutes") or 0) > 0]
        values = player_metrics(snapshot, player, recent[-3:])
        fixtures = five_gw_fixtures(snapshot, player, xpts)
        action, reason = choose_manager_action(player, fixtures, recent[-3:])
        # Preserve existing editorial categories, while not advising an
        # unavailable/doubtful player to start or buy on a numeric score.
        published_label = str(card.label or "").upper()
        if player.get("status") == "a":
            if post.kind in ("buy", "sell") and published_label in ("BUY", "SELL", "HOLD", "WATCHLIST"):
                action = "MONITOR" if published_label == "WATCHLIST" else published_label
            elif post.kind == "captaincy" and idx == 0:
                action = "CAPTAIN"
        accent = ((53, 227, 244), (240, 202, 97), (71, 224, 148),
                  (160, 166, 250))[idx]
        draw.rounded_rectangle((x0, 168, x1, 715), radius=13,
                               fill=(1, 21, 50, 247), outline=(*accent, 255), width=2)
        _text(draw, card.headline.upper(), x0+14, 178, width-80, 28)
        emblem = badge.convert("RGBA").copy()
        emblem.thumbnail((57, 57), Image.Resampling.LANCZOS)
        canvas.paste(emblem, (x1-65, 172), emblem)
        photo = portrait.convert("RGBA").copy()
        bounds = photo.getchannel("A").getbbox()
        if bounds:
            photo = photo.crop(bounds)
        photo.thumbnail((min(151, int(width*.42)), 163), Image.Resampling.LANCZOS)
        canvas.paste(photo, (x1-20-photo.width, 226+163-photo.height), photo)
        draw = ImageDraw.Draw(canvas, "RGBA")
        _text(draw, f"{values['POSITION']}  •  {snapshot.team(player)}",
              x0+16, 218, width-30, 19, accent)
        metrics = [("PRICE", values["PRICE"]), ("OWN", values["OWNERSHIP"]),
                   ("FORM", values["FORM"]), ("MINS", values["MINUTES"])]
        right_limit = width-166
        for row, (label, value) in enumerate(metrics):
            _text(draw, f"{label}  {value}", x0+17, 249+row*33,
                  max(120, right_limit), 20)
        # Small position-specific evidence strip; actual DC actions never
        # appear under an FPL points label.
        relevant = ("SAVES", "CS") if player["element_type"] == 1 else (
            ("CS", "DC ACTIONS") if player["element_type"] == 2 else
            ("GOALS", "xGI"))
        statline = " • ".join(f"{key} {values[key]}" for key in relevant if key in values)
        if statline:
            _text(draw, statline, x0+15, 391, width-26, 19, (246, 210, 115))
        _text(draw, "NEXT FIVE GAMEWEEKS", x0+16, 419,
              width-26, 18, accent)
        by_gw = {}
        for fi in fixtures:
            by_gw.setdefault(fi["gw"], []).append(fi)
        for row, (event, matches) in enumerate(by_gw.items()):
            top = 444+row*47
            if top+45 > 697:
                raise RuntimeError("Five-GW fixture table does not fit clear mobile space")
            draw.rounded_rectangle((x0+11, top, x1-10, top+44), radius=5,
                                   fill=(5, 40, 77, 248), outline=(83, 140, 190, 130), width=1)
            if all(fi["blank"] for fi in matches):
                _text(draw, f"GW{event}  BLANK", x0+19, top+13,
                      width-36, 19)
                continue
            real_matches = [fi for fi in matches if not fi["blank"]]
            if len(real_matches) > 2:
                raise RuntimeError("Complex three-match GW needs separate readable slide")
            span = (width - 28) / len(real_matches)
            for n, fi in enumerate(real_matches):
                cx = x0+17+int(n*span)
                color = tuple(bytes.fromhex(FDR_COLORS[fi["fdr"]][1:]))
                tag = f"GW{event} {fi['opponent']}({fi['venue']}) FDR{fi['fdr']}"
                _text(draw, tag, cx, top+4,
                      int(span)-6, 17, color)
                if fi["xpts"] is not None:
                    _text(draw, f"xPts {fi['xpts']:.2f}", cx+3, top+25,
                          int(span)-8, 16, (242, 247, 252))
        _text(draw, f"{action} • {reason}", x0+14, 688,
              width-28, 17, (98, 236, 157))
    output.parent.mkdir(parents=True, exist_ok=True)
    interim = output.with_suffix(".tmp.png")
    canvas.resize((1920,1080), Image.Resampling.LANCZOS).save(interim, "PNG", optimize=True)
    interim.replace(output)
    return apply_footer(output, verdict="VERIFY MINUTES • FIXTURES • PLAYER FORM BEFORE TRANSFERS")
