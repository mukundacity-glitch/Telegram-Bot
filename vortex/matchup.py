"""FPL VORTEX two-player matchup layout based on the supplied 1536x864 reference."""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .content import Card, Content

CANVAS_SIZE = (1536, 864)
ROOT = Path(__file__).resolve().parents[1]
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf"
CYAN = (32, 216, 253)
GOLD = (255, 205, 84)
WHITE = (250, 252, 255)
MUTED = (174, 206, 226)


def _font(size: int, *, bold: bool = True) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)
    except OSError:
        return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), value, font=font)
    return box[2] - box[0]


def _fitted_font(draw: ImageDraw.ImageDraw, value: str, width: int, size: int, smallest: int = 18) -> ImageFont.ImageFont:
    while size > smallest and _text_width(draw, value, _font(size)) > width:
        size -= 1
    return _font(size)


def _center_text(draw: ImageDraw.ImageDraw, x: int, y: int, value: str, font: ImageFont.ImageFont, color: tuple[int, int, int]) -> None:
    draw.text((x - _text_width(draw, value, font) // 2, y), value, font=font, fill=color)


def _image_from_url(session: requests.Session, url: str) -> Image.Image | None:
    try:
        response = session.get(url, timeout=7, headers={"User-Agent": "FPL-VORTEX-Telegram/2.0"})
        if response.status_code != 200 or not response.headers.get("Content-Type", "").lower().startswith("image/"):
            return None
        if len(response.content) < 500 or len(response.content) > 4_000_000:
            return None
        with Image.open(BytesIO(response.content)) as original:
            original.load()
            result = original.convert("RGBA")
        if result.width < 48 or result.height < 48:
            return None
        return result
    except (OSError, ValueError, requests.RequestException):
        return None


def _media(session: requests.Session, code: int | None, kind: str, cache: dict[tuple[str, int], Image.Image | None]) -> Image.Image | None:
    if code is None or code <= 0:
        return None
    key = (kind, code)
    if key in cache:
        return cache[key]
    if kind == "photo":
        urls = [
            f"https://resources.premierleague.com/premierleague25/photos/players/250x250/{code}.png",
            f"https://resources.premierleague.com/premierleague25/photos/players/110x140/{code}.png",
            f"https://resources.premierleague.com/premierleague25/photos/players/250x250/p{code}.png",
            f"https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png",
            f"https://resources.premierleague.com/premierleague/photos/players/110x140/p{code}.png",
            f"https://images.fantasy.premierleague.com/premierleague/photos/players/250x250/p{code}.png",
        ]
    elif kind == "crest":
        urls = [
            f"https://resources.premierleague.com/premierleague/badges/70/t{code}.png",
            f"https://resources.premierleague.com/premierleague/badges/50/t{code}.png",
            f"https://resources.premierleague.com/premierleague/badges/t{code}.png",
        ]
    else:
        raise ValueError(f"Unsupported media kind: {kind}")
    image = next((found for url in urls if (found := _image_from_url(session, url)) is not None), None)
    cache[key] = image
    return image


def _angular_panel(draw: ImageDraw.ImageDraw, bounds: tuple[int, int, int, int], accent: tuple[int, int, int]) -> None:
    left, top, right, bottom = bounds
    points = [(left + 18, top), (right - 18, top), (right, top + 18), (right, bottom - 15),
              (right - 15, bottom), (left + 15, bottom), (left, bottom - 15), (left, top + 18)]
    draw.polygon(points, fill=(2, 17, 39, 243))
    draw.line(points + [points[0]], fill=(*accent, 245), width=3, joint="curve")


def _draw_stat_box(draw: ImageDraw.ImageDraw, bounds: tuple[int, int, int, int], outline: tuple[int, int, int] | None = None) -> None:
    draw.rounded_rectangle(bounds, radius=9, fill=(1, 14, 34, 229), outline=(*outline, 255) if outline else (21, 65, 105, 255), width=2)


def _bundled_portrait(player_name: str) -> Image.Image | None:
    # These are explicitly matched crops from the user's reference, never applied to other players.
    built_in = {"DE CUYPER": "de_cuyper.webp", "TARKOWSKI": "tarkowski.webp"}
    filename = built_in.get(player_name.upper().strip())
    if not filename:
        return None
    path = ROOT / "assets" / "players" / (filename + ".b64")
    if not path.exists():
        return None
    try:
        image_bytes = base64.b64decode(path.read_text(encoding="ascii"), validate=False)
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            return image.convert("RGBA")
    except (OSError, ValueError, binascii.Error):
        return None


def _brighten_portrait(portrait: Image.Image) -> Image.Image:
    alpha = portrait.getchannel("A")
    if alpha.getextrema() == (255, 255):
        # An opaque CDN portrait would otherwise paste a visible square over the stat card.
        soft = Image.new("L", portrait.size, 0)
        mask_draw = ImageDraw.Draw(soft)
        mask_draw.rounded_rectangle((0, 0, portrait.width - 1, portrait.height - 1), radius=35, fill=255)
        portrait.putalpha(soft.filter(ImageFilter.GaussianBlur(9)))
    return portrait


def _paste_player(canvas: Image.Image, portrait: Image.Image, *, left_player: bool) -> None:
    portrait = _brighten_portrait(portrait.copy())
    bbox = portrait.getchannel("A").getbbox()
    if bbox:
        portrait = portrait.crop(bbox)
    # Source API portraits vary between headshots and mid-torso; never distort aspect ratio.
    target_width, target_height = ((323, 448) if left_player else (302, 448))
    portrait.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
    left = 34 if left_player else 1501 - portrait.width
    top = 591 - portrait.height
    glow = Image.new("RGBA", canvas.size)
    glow_draw = ImageDraw.Draw(glow)
    accent = (10, 102, 212, 92) if left_player else (230, 160, 50, 78)
    glow_draw.ellipse((left - 38, 197, left + target_width + 35, 614), fill=accent)
    glow = glow.filter(ImageFilter.GaussianBlur(55))
    canvas.paste(glow, (0, 0), glow)
    canvas.paste(portrait, (left, top), portrait)


def _crest(canvas: Image.Image, picture: Image.Image, center_x: int, top: int, size: int) -> None:
    photo = picture.copy()
    photo.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas.paste(photo, (center_x - photo.width // 2, top + (size - photo.height) // 2), photo)


def _row_cell(draw: ImageDraw.ImageDraw, center_x: int, y: int, value: str, label: str, width: int, color: tuple[int, int, int]) -> None:
    actual_font = _fitted_font(draw, value, width - 10, 36, 24)
    _center_text(draw, center_x, y, value, actual_font, WHITE)
    label_font = _fitted_font(draw, label, width - 10, 18, 13)
    _center_text(draw, center_x, y + 41, label, label_font, color)


def _fixture_color(difficulty: int) -> tuple[int, int, int]:
    return (42, 211, 112) if difficulty <= 2 else (240, 196, 60) if difficulty == 3 else (244, 126, 67) if difficulty == 4 else (237, 83, 106)


def _fixture_strip(draw: ImageDraw.ImageDraw, canvas: Image.Image, card: Card, x: int, y: int, accent: tuple[int, int, int], session: requests.Session, cache: dict[tuple[str, int], Image.Image | None]) -> None:
    _center_text(draw, x + 343, y - 29, "NEXT 3 FIXTURES", _font(22), accent)
    fixtures = card.fixtures[:3]
    for idx in range(3):
        if idx >= len(fixtures):
            x0 = x + 21 + idx * 226
            draw.rounded_rectangle((x0, y, x0 + 210, y + 65), radius=8,
                                   fill=(13, 29, 47, 255), outline=(80, 107, 133, 255), width=2)
            _center_text(draw, x0 + 105, y + 21, "NO FIXTURE", _font(20), MUTED)
            continue
        opponent, venue, difficulty, team_code = fixtures[idx]
        x0 = x + 21 + idx * 226
        base_color = _fixture_color(difficulty)
        draw.rounded_rectangle((x0, y, x0 + 210, y + 65), radius=8,
                               fill=(*tuple(max(7, c // 5) for c in base_color), 242),
                               outline=(*base_color, 255), width=3)
        draw.rounded_rectangle((x0 + 165, y + 8, x0 + 204, y + 57), radius=7,
                               fill=(*base_color, 255))
        draw.text((x0 + 175, y + 13), str(difficulty), font=_font(30), fill=(4, 14, 27))
        code = team_code
        logo = _media(session, code, "crest", cache)
        if logo is None:
            raise RuntimeError(f"Missing official fixture club crest for {opponent} ({code})")
        _crest(canvas, logo, x0 + 33, y + 7, 49)
        label = f"{opponent} ({venue})"
        label_font = _fitted_font(draw, label, 103, 20, 14)
        draw.text((x0 + 62, y + 20), label, font=label_font, fill=WHITE)


def _draw_player_data(canvas: Image.Image, card: Card, *, left_side: bool, session: requests.Session, cache: dict[tuple[str, int], Image.Image | None]) -> None:
    if card.metrics is None:
        raise ValueError(f"Structured official FPL metrics missing for {card.headline}")
    metrics: dict[str, int | str] = card.metrics
    accent = CYAN if left_side else GOLD
    detail_left = 328 if left_side else 843
    detail_right = 699 if left_side else 1215
    draw = ImageDraw.Draw(canvas, "RGBA")
    name = card.headline.upper()
    draw.text((detail_left, 172), name, font=_fitted_font(draw, name, 273, 42, 22), fill=WHITE)
    draw.text((detail_left + 2, 228), card.subtitle.upper(), font=_font(30), fill=accent)
    club = _media(session, card.team_code, "crest", cache)
    if club is None:
        raise RuntimeError(f"Missing official club crest for {card.headline} ({card.team_code})")
    _crest(canvas, club, detail_right - 43, 173, 82)
    price_value = str(metrics["price"])
    price_x0 = detail_left + 2 if left_side else detail_left + 47
    draw.rounded_rectangle((price_x0, 277, price_x0 + 297, 330), radius=10, fill=(3, 22, 47, 224), outline=(*accent, 255), width=2)
    _center_text(draw, price_x0 + 147, 280, price_value, _font(38), WHITE)
    block_x0, block_x1 = detail_left - 4, detail_right
    for row_top in (339, 418, 499):
        _draw_stat_box(draw, (block_x0, row_top, block_x1, row_top + 80))
    half = (block_x0 + block_x1) // 2
    draw.line((half, 348, half, 408), fill=(*accent, 116), width=2)
    draw.line((half, 426, half, 493), fill=(*accent, 116), width=2)
    _row_cell(draw, (block_x0 + half) // 2, 344, f"{metrics['total_points']} pts", "TOTAL POINTS", half - block_x0, MUTED)
    _row_cell(draw, (half + block_x1) // 2, 344, str(metrics["form"]), "FORM", block_x1 - half, MUTED)
    _row_cell(draw, (block_x0 + half) // 2, 424, str(metrics["goals"]), "GOALS", half - block_x0, MUTED)
    _row_cell(draw, (half + block_x1) // 2, 424, f"{metrics['assists']}", "ASSISTS", block_x1 - half, MUTED)
    width = block_x1 - block_x0
    third = width / 3
    for separator in (block_x0 + third, block_x0 + 2 * third):
        draw.line((int(separator), 508, int(separator), 571), fill=(*accent, 118), width=2)
    _row_cell(draw, int(block_x0 + third * 0.5), 507, str(metrics["minutes"]), "MINS", int(third), MUTED)
    _row_cell(draw, int(block_x0 + third * 1.5), 507, str(metrics["clean_sheets"]), "CLEAN SHEETS", int(third), MUTED)
    _row_cell(draw, int(block_x0 + third * 2.5), 507, str(metrics["bonus"]), "BONUS", int(third), MUTED)
    _fixture_strip(draw, canvas, card, 30 if left_side else 814, 631, accent, session, cache)


def render_comparison(content: Content, output: Path, session: requests.Session) -> Path:
    """Use the supplied reference geometry, but ONLY live Content metrics and fixtures."""
    if len(content.cards) != 2:
        raise ValueError("The comparison reference requires exactly two players")
    if any(card.metrics is None for card in content.cards):
        raise ValueError("Live player comparison metrics are required")

    cache: dict[tuple[str, int], Image.Image | None] = {}
    portraits = [
        _media(session, card.photo_code, "photo", cache) or _bundled_portrait(card.headline)
        for card in content.cards
    ]
    for card, portrait in zip(content.cards, portraits):
        if portrait is None and _media(session, card.team_code, "crest", cache) is None:
            raise RuntimeError(f"Neither official portrait nor club crest available for {card.headline}")

    background_path = ROOT / "assets" / "references" / "brand_background.png"
    with Image.open(background_path) as original:
        canvas = ImageOps.fit(original.convert("RGB"), CANVAS_SIZE, method=Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle((312, 3, 1265, 142), fill=(1, 11, 30, 236))
    draw.rounded_rectangle((520, 86, 1015, 133), radius=11, fill=(0, 13, 33, 246), outline=(*CYAN, 185), width=2)
    title = content.title.upper()
    title_font = _fitted_font(draw, title, 770, 65, 41)
    if title == "THE FPL DECISION ROOM":
        first, second = "THE FPL ", "DECISION ROOM"
        x_start = 766 - _text_width(draw, first + second, title_font) // 2
        draw.text((x_start, 7), first, font=title_font, fill=WHITE)
        draw.text((x_start + _text_width(draw, first, title_font), 7), second, font=title_font, fill=GOLD)
    else:
        _center_text(draw, 766, 7, title, title_font, WHITE)
    draw.text((552, 91), content.kicker.upper(), font=_fitted_font(draw, content.kicker.upper(), 435, 28, 18), fill=CYAN)
    draw.rounded_rectangle((1375, 91, 1493, 137), radius=9, fill=(1, 12, 31, 242), outline=(*GOLD, 255), width=3)
    _center_text(draw, 1434, 94, f"GW{content.gw}", _font(32), GOLD)
    _angular_panel(draw, (32, 151, 722, 715), CYAN)
    _angular_panel(draw, (814, 151, 1504, 715), GOLD)

    # Prefer verified portraits; display the correct club crest if the CDN has no headshot.
    for index, (card, portrait) in enumerate(zip(content.cards, portraits)):
        left_side = index == 0
        if portrait is not None:
            _paste_player(canvas, portrait, left_player=left_side)
            continue
        club = _media(session, card.team_code, "crest", cache)
        assert club is not None
        center_x = 174 if left_side else 1360
        _crest(canvas, club, center_x, 330, 200)
        _center_text(ImageDraw.Draw(canvas), center_x, 545, "PORTRAIT UNAVAILABLE", _font(15), MUTED)
    _draw_player_data(canvas, content.cards[0], left_side=True, session=session, cache=cache)
    _draw_player_data(canvas, content.cards[1], left_side=False, session=session, cache=cache)
    draw = ImageDraw.Draw(canvas, "RGBA")
    _center_text(draw, 768, 354, "VS", _font(88), GOLD)
    draw.rounded_rectangle((69, 732, 1467, 797), radius=14, fill=(0, 14, 35, 246), outline=(*CYAN, 210), width=3)
    verdict = content.verdict.upper()
    verdict_font = _fitted_font(draw, verdict, 1270, 29, 22)
    _center_text(draw, 770, 747, verdict, verdict_font, WHITE)
    # The user's brand strip is left intact; source details are data-backed.
    draw.rectangle((1162, 802, 1536, 864), fill=(0, 12, 30, 235))
    source = "Source: Official Fantasy Premier League API"
    _center_text(draw, 1346, 805, source, _fitted_font(draw, source, 350, 15, 12), MUTED)
    _center_text(draw, 1346, 831, f"Verified {content.data_at}",
                 _fitted_font(draw, f"Verified {content.data_at}", 346, 15, 11), MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp.png")
    canvas.save(tmp, format="PNG", optimize=True)
    tmp.replace(output)
    return output