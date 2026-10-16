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
    client = session or requests.Session()
    if content.kind in {"comparison", "transfer"}:
        from .matchup import render_comparison
        return render_comparison(content, output, client)
    from .premium import render_premium
    return render_premium(content, output, client)