"""Rasterize data into the user's original FPL VORTEX broadcast background."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .content import Card, Content

ROOT = Path(__file__).resolve().parents[1]
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"
WHITE = (251, 254, 255)
CYAN = (35, 233, 255)
GOLD = (255, 190, 65)
GREEN = (45, 255, 125)
MUTED = (176, 207, 225)


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except OSError:
        return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, value: str, max_width: int, size: int, min_size: int = 17) -> ImageFont.ImageFont:
    while size > min_size:
        current = font(size)
        if draw.textbbox((0, 0), value, font=current)[2] <= max_width:
            return current
        size -= 2
    return font(max(size, min_size))


def _trim(draw: ImageDraw.ImageDraw, text: str, width: int, size: int) -> str:
    result = text.strip().replace("\n", " ")
    current = font(size, False)
    while result and draw.textbbox((0, 0), result, font=current)[2] > width:
        result = result[:-2].rstrip(" ")
    return result + ("…" if result != text and result else "")


def _image_from_url(session: requests.Session, url: str) -> Image.Image | None:
    try:
        response = session.get(url, timeout=7, headers={"User-Agent": "FPL-VORTEX-Telegram/1.0"})
        if response.status_code != 200 or not response.headers.get("Content-Type", "").startswith("image/"):
            return None
        if len(response.content) > 3_000_000:
            return None
        image = Image.open(BytesIO(response.content))
        image.load()
        return image.convert("RGBA")
    except (OSError, ValueError, requests.RequestException):
        return None


def _player_image(session: requests.Session, code: int | None) -> Image.Image | None:
    if code is None:
        return None
    return _image_from_url(session, f"https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png")


def _team_image(session: requests.Session, code: int | None) -> Image.Image | None:
    if code is None:
        return None
    return _image_from_url(session, f"https://resources.premierleague.com/premierleague/badges/70/t{code}.png")


def _background(content: Content) -> Image.Image:
    asset = ROOT / "assets" / "references" / "brand_background.png"
    if content.kind == "evening":
        assists = ROOT / "assets" / "assists" / "5.png"
        if assists.exists():
            asset = assists
    if not asset.exists():
        raise FileNotFoundError(f"Missing graphic background: {asset}")
    with Image.open(asset) as original:
        bg = ImageOps.fit(original.convert("RGB"), (1536, 864), method=Image.Resampling.LANCZOS)
    if content.kind == "evening" and asset.name == "5.png":
        # Preserve visual identity while keeping text legible on this user-supplied slide.
        return Image.blend(bg, Image.new("RGB", bg.size, (0, 13, 32)), 0.29)
    return bg


def _panel(canvas: Image.Image, box: tuple[int, int, int, int], accent: tuple[int, int, int]) -> None:
    drawer = ImageDraw.Draw(canvas, "RGBA")
    drawer.rounded_rectangle(box, radius=19, fill=(1, 13, 35, 231), outline=(*accent, 255), width=3)
    x0, y0, x1, _ = box
    drawer.rounded_rectangle((x0 + 10, y0 + 11, x1 - 10, y0 + 21), radius=5, fill=(*accent, 200))


def _draw_card(canvas: Image.Image, card: Card, box: tuple[int, int, int, int], color: tuple[int, int, int], session: requests.Session) -> None:
    _panel(canvas, box, color)
    draw = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = box
    padding = 27
    width = x1 - x0 - padding * 2
    columns = len(card.fields)
    draw.text((x0 + padding, y0 + 34), _trim(draw, card.label.upper(), width - 12, 20), font=font(20), fill=color)
    name_size = 40 if width > 500 else 30
    name = _trim(draw, card.headline.upper(), width - 6, name_size)
    draw.text((x0 + padding, y0 + 79), name, font=_fit_text(draw, name, width - 10, name_size), fill=WHITE)
    draw.text((x0 + padding, y0 + 127), _trim(draw, card.subtitle.upper(), width, 23), font=font(23), fill=GOLD)
    photo = _player_image(session, card.photo_code)
    available = photo is not None
    if available:
        assert photo is not None
        target = 190 if width > 500 else 128
        photo.thumbnail((target, target), Image.Resampling.LANCZOS)
        px, py = x1 - padding - photo.width, y0 + 140
        canvas.paste(photo, (px, py), photo)
    crest = _team_image(session, card.team_code)
    if crest is not None:
        crest.thumbnail((55, 55), Image.Resampling.LANCZOS)
        canvas.paste(crest, (x1 - padding - crest.width, y0 + 33), crest)
    detail_y = y0 + (174 if available else 176)
    max_field_width = width - (130 if available else 0)
    max_lines = min(columns, max(1, int((y1 - detail_y - 25) / 44)))
    for i, line in enumerate(card.fields[:max_lines]):
        text = _trim(draw, str(line), max_field_width, 22)
        draw.text((x0 + padding, detail_y + 45 * i), text, font=font(22, False), fill=WHITE if i == 0 else MUTED)


def render(content: Content, output: Path, session: requests.Session | None = None) -> Path:
    if not content.cards:
        raise ValueError("Cannot render without sourced content")
    if content.kind == "comparison":
        from .matchup import render_comparison
        return render_comparison(content, output, session or requests.Session())
    canvas = _background(content)
    draw = ImageDraw.Draw(canvas, "RGBA")
    if content.kind == "evening":
        # The user's 5.png has a printed Opta credit; this workflow does not consume Opta.
        draw.rectangle((0, 800, 1536, 864), fill=(0, 8, 26, 255))
        draw.text((72, 812), "FPL VORTEX  •  Verified data: Official FPL API  •  @FPLVORTEXM", font=font(21), fill=MUTED)
    draw.rounded_rectangle((45, 93, 1491, 176), radius=16, fill=(0, 12, 33, 235), outline=(*CYAN, 230), width=3)
    heading = _trim(ImageDraw.Draw(canvas), content.title, 1340, 45)
    text_font = _fit_text(ImageDraw.Draw(canvas), heading, 1340, 45, 29)
    draw.text((73, 111), heading, font=text_font, fill=WHITE)
    draw.text((70, 188), content.kicker, font=font(26), fill=CYAN)
    draw.text((1250, 190), f"GW{content.gw}", font=font(29), fill=GOLD)
    cards = list(content.cards[:4]); count = len(cards)
    gap = 22
    if count == 1:
        boxes = [(140, 245, 1396, 657)]
    elif count == 2:
        boxes = [(55, 245, 757, 658), (779, 245, 1481, 658)]
    elif count == 3:
        width = (1450 - 2 * gap) // 3
        boxes = [(46 + i * (width + gap), 245, 46 + i * (width + gap) + width, 658) for i in range(3)]
    else:
        width = (1450 - 3 * gap) // 4
        boxes = [(45 + i * (width + gap), 245, 45 + i * (width + gap) + width, 658) for i in range(4)]
    palette = [CYAN, GOLD, GREEN, (180, 133, 255)]
    client = session or requests.Session()
    for card, box, tint in zip(cards, boxes, palette):
        _draw_card(canvas, card, box, tint, client)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle((60, 681, 1470, 740), radius=16, fill=(1, 13, 33, 245), outline=(*GOLD, 255), width=3)
    verdict = _trim(ImageDraw.Draw(canvas), content.verdict.upper(), 1340, 31)
    draw.text((84, 697), verdict, font=_fit_text(ImageDraw.Draw(canvas), verdict, 1320, 31), fill=GOLD)
    draw.rounded_rectangle((60, 751, 1470, 792), radius=9, fill=(0, 12, 35, 205))
    footer = f"{content.footer}   •   VERIFIED {content.data_at}"
    draw.text((74, 760), _trim(ImageDraw.Draw(canvas), footer, 1350, 20), font=font(20, False), fill=MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".tmp.png")
    canvas.save(temp, format="PNG", optimize=True)
    temp.replace(output)
    return output