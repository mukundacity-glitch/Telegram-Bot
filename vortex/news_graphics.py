"""Mobile-readable official-brand news graphic, identical for both destinations.

Do not publish a player story unless a sourced portrait and official team crest
are actually loaded. Never draw synthetic/placeholder faces, crests or stats.
"""
from __future__ import annotations
from .minimal_theme import background as minimal_background, edition_key, action_fill, social_footer

from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .matchup import _bundled_portrait, _media
from .syndication import NewsPost

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "assets" / "references" / "brand_background.png"
BLUE = (9, 22, 54)
CYAN = (23, 229, 249)
GOLD = (255, 205, 82)
WHITE = (239, 247, 255)
MUTED = (158, 189, 222)
SIZE = (1536, 864)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(BOLD if bold else FONT, size=size)
    except OSError:
        return ImageFont.load_default(size=size)


def _fit(draw: ImageDraw.ImageDraw, value: str, width: int,
         size: int = 38, minimum: int = 19) -> ImageFont.ImageFont:
    while size > minimum and draw.textbbox((0, 0), value, font=_font(size, True))[2] > width:
        size -= 2
    return _font(size, True)


def _lines(draw: ImageDraw.ImageDraw, value: str, width: int,
           size: int, limit: int) -> list[str]:
    """Fit headline-derived copy into a predetermined panel; no extra facts."""
    output: list[str] = []
    for paragraph in value.splitlines():
        current = ""
        for word in paragraph.split():
            expanded = (current + " " + word).strip()
            if draw.textbbox((0, 0), expanded, font=_font(size))[2] <= width:
                current = expanded
            else:
                if current:
                    output.append(current)
                current = word
        if current:
            output.append(current)
        if len(output) >= limit:
            break
    output = output[:limit]
    if len(output) == limit and output[-1]:
        last = output[-1]
        while last and draw.textbbox((0, 0), last + "…", font=_font(size))[2] > width:
            last = last[:-1]
        output[-1] = last + "…"
    return output


def render_news_card(post: NewsPost, output: Path,
                     session: requests.Session | None = None) -> Path:
    """Create ONE verified player image + club logo graphic for both platforms.

    If the photo, logo or approved stadium master cannot be obtained, fail
    closed before either network destination receives a text-only substitute.
    """
    if not post.player_name or not isinstance(post.photo_code, int) or not isinstance(post.club_code, int):
        raise ValueError("Player name, official photo ID and club badge ID are mandatory")
    if not MASTER.is_file():
        raise FileNotFoundError("The approved FPL VORTEX broadcast master is not installed")
    client = session or requests.Session()
    cache: dict[tuple[str, int], Image.Image | None] = {}
    photo = _media(client, post.photo_code, "photo", cache)
    if photo is None:
        photo = _bundled_portrait(post.player_name)
    if photo is None:
        raise RuntimeError("No verified player portrait available: graphic blocked")
    crest = _media(client, post.club_code, "crest", cache)
    if crest is None:
        raise RuntimeError("No authentic team crest available: graphic blocked")

    with Image.open(MASTER) as master:
        # Approved 16:9 blue stadium background. Preserve geometry.
        if master.width * 9 != master.height * 16:
            raise ValueError("Approved master is not 16:9")
        canvas = minimal_background(master, edition_key(post), SIZE)
    painter = ImageDraw.Draw(canvas, "RGBA")
    painter.rounded_rectangle((56, 146, 1480, 734), radius=21,
                             fill=(*BLUE, 242), outline=(*CYAN, 232), width=3)
    painter.rounded_rectangle((80, 164, 533, 700), radius=16,
                             fill=(10, 25, 58, 255), outline=(*GOLD, 235), width=2)
    painter.rectangle((546, 165, 553, 702), fill=(*CYAN, 220))
    painter.text((589, 171), "FPL VORTEX  •  VERIFIED PLAYER UPDATE",
                 font=_font(27, True), fill=WHITE)
    painter.text((589, 218), post.title.upper(),
                 font=_fit(painter, post.title.upper(), 770, 42, 23), fill=WHITE)

    # Preserve natural portrait and crest proportions, no forced stretch.
    portrait = photo.convert("RGBA").copy()
    portrait.thumbnail((420, 404), Image.Resampling.LANCZOS)
    canvas.paste(portrait, (303 - portrait.width // 2,
                           280 + (404 - portrait.height)), portrait)

    emblem = crest.convert("RGBA").copy()
    emblem.thumbnail((118, 118), Image.Resampling.LANCZOS)
    canvas.paste(emblem, (1278 + (118 - emblem.width) // 2, 283), emblem)

    name = post.player_name.upper()
    painter = ImageDraw.Draw(canvas, "RGBA")
    painter.rounded_rectangle((97, 600, 510, 674), radius=10, fill=(10, 25, 58, 255))
    painter.text((107, 610), name, font=_fit(painter, name, 390, 33, 21), fill=WHITE)
    painter.text((109, 652), (post.team_name or "").upper(),
                 font=_fit(painter, (post.team_name or "").upper(), 390, 22, 16), fill=WHITE)

    # Caption is the only source of story facts; use the exact same caption
    # string in both Telegram and Discord deliveries.
    content_lines = [line for line in post.caption.splitlines()
                     if line.strip() and not line.strip().startswith("#")
                     and not line.strip().startswith(post.title)]
    detail = " ".join(content_lines)
    detail = detail.replace(post.source_url, "").strip()
    for idx, line in enumerate(_lines(painter, detail, width=755, size=30, limit=8)):
        painter.text((596, 316 + idx * 45), line, font=_font(30), fill=WHITE)
    provenance = (post.source or "Unverified source") + " • " + datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC")
    painter.text((584, 666), provenance[:79],
                 font=_fit(painter, provenance[:79], 811, 19, 15), fill=MUTED)

    import os
    social_footer(canvas, os.getenv('FPL_TELEGRAM_HANDLE', ''), os.getenv('FPL_DISCORD_HANDLE', ''))
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".tmp.png")
    canvas.resize((1920, 1080), Image.Resampling.LANCZOS).save(temp, "PNG", optimize=True)
    with Image.open(temp) as exported:
        if exported.size != (1920, 1080):
            raise RuntimeError("Graphic dimensions did not pass final validation")
        exported.verify()
    temp.replace(output)
    return output
