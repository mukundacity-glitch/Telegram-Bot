"""Consistent portrait-first FPL VORTEX layouts for every non-comparison desk."""
from __future__ import annotations

from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageOps, ImageFilter

from .content import Card, Content
from .matchup import (
    CANVAS_SIZE, ROOT, CYAN, GOLD, WHITE, MUTED, _font, _fitted_font,
    _center_text, _text_width, _angular_panel, _fixture_color,
    _media, _bundled_portrait, _brighten_portrait,
)

PANEL = (3, 16, 38, 245)
ORANGE = (255, 145, 71)
GREEN = (45, 237, 133)
MAGENTA = (255, 94, 138)
PALETTE = (CYAN, GOLD, GREEN, (173, 141, 255))


def _panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], accent: tuple[int, int, int]) -> None:
    _angular_panel(draw, box, accent)


def _text(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, max_width: int,
          size: int, color: tuple[int, int, int] = WHITE, minimum: int = 16) -> None:
    value = str(text).replace('\n', ' ').strip()
    draw.text((x, y), value, font=_fitted_font(draw, value, max_width, size, minimum), fill=color)


def _wrapped(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, width: int,
             max_lines: int, size: int, color: tuple[int, int, int]) -> None:
    words = str(text).replace('\n', ' ').split()
    lines: list[str] = []
    current = ''
    for word in words:
        trial = (current + ' ' + word).strip()
        if _text_width(draw, trial, _font(size, bold=False)) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and _text_width(draw, lines[-1] + '…', _font(size, bold=False)) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += '…'
    for index, line in enumerate(lines):
        draw.text((x, y + index * (size + 6)), line, font=_font(size, bold=False), fill=color)


def _crest(canvas: Image.Image, image: Image.Image, x: int, y: int, diameter: int) -> None:
    picture = image.copy()
    picture.thumbnail((diameter, diameter), Image.Resampling.LANCZOS)
    canvas.paste(picture, (x + (diameter - picture.width) // 2, y + (diameter - picture.height) // 2), picture)


def _photo(canvas: Image.Image, image: Image.Image, box: tuple[int, int, int, int], accent: tuple[int, int, int]) -> None:
    left, top, right, bottom = box
    portrait = _brighten_portrait(image.copy())
    crop = portrait.getchannel('A').getbbox()
    if crop:
        portrait = portrait.crop(crop)
    portrait.thumbnail((right - left, bottom - top), Image.Resampling.LANCZOS)
    px = left + (right - left - portrait.width) // 2
    py = bottom - portrait.height
    glow = Image.new('RGBA', canvas.size)
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((px - 42, py - 36, px + portrait.width + 42, bottom + 28), fill=(*accent, 65))
    glow = glow.filter(ImageFilter.GaussianBlur(36))
    canvas.paste(glow, (0, 0), glow)
    canvas.paste(portrait, (px, py), portrait)


def _media_required(cards: tuple[Card, ...], session: requests.Session) -> list[tuple[Image.Image | None, Image.Image | None]]:
    cache: dict[tuple[str, int], Image.Image | None] = {}
    found: list[tuple[Image.Image | None, Image.Image | None]] = []
    for card in cards:
        # A verified empty-status card deliberately has no player identity or photo.
        if card.photo_code is None and card.team_code is None and card.metrics is None:
            found.append((None, None))
            continue
        portrait = _media(session, card.photo_code, 'photo', cache)
        if portrait is None:
            portrait = _bundled_portrait(card.headline)
        crest = _media(session, card.team_code, 'crest', cache)
        if crest is None:
            raise RuntimeError(f'Mandatory club badge unavailable: {card.headline} ({card.team_code})')
        found.append((portrait, crest))
    return found


def _background(content: Content) -> Image.Image:
    background_path = ROOT / 'assets' / 'references' / 'brand_background.png'
    if not background_path.is_file():
        raise FileNotFoundError(f'Missing branded background: {background_path}')
    with Image.open(background_path) as background:
        canvas = ImageOps.fit(background.convert('RGB'), CANVAS_SIZE, method=Image.Resampling.LANCZOS)
    return canvas


def _header(canvas: Image.Image, content: Content) -> None:
    draw = ImageDraw.Draw(canvas, 'RGBA')
    draw.rectangle((314, 0, 1268, 145), fill=(0, 11, 30, 244))
    _center_text(draw, 785, 5, content.title.upper(),
                 _fitted_font(draw, content.title.upper(), 864, 62, 37), WHITE)
    draw.rounded_rectangle((460, 88, 1090, 135), radius=11,
                           fill=(0, 15, 39, 248), outline=(*CYAN, 224), width=2)
    _center_text(draw, 775, 93, content.kicker.upper(),
                 _fitted_font(draw, content.kicker.upper(), 590, 27, 19), CYAN)
    draw.rounded_rectangle((1375, 90, 1493, 137), radius=9,
                           fill=(0, 12, 32, 248), outline=(*GOLD, 255), width=3)
    _center_text(draw, 1434, 94, f'GW{content.gw}', _font(32), GOLD)


def _footer(canvas: Image.Image, content: Content) -> None:
    draw = ImageDraw.Draw(canvas, 'RGBA')
    draw.rounded_rectangle((69, 735, 1468, 797), radius=13,
                           fill=(0, 13, 35, 251), outline=(*CYAN, 221), width=3)
    _center_text(draw, 764, 748, content.verdict.upper(),
                 _fitted_font(draw, content.verdict.upper(), 1300, 29, 19), WHITE)
    draw.rectangle((1162, 802, 1536, 864), fill=(0, 12, 30, 244))
    _center_text(draw, 1347, 806, 'Source: Official Fantasy Premier League API',
                 _font(14, bold=False), MUTED)
    _center_text(draw, 1347, 831, 'Verified ' + content.data_at,
                 _fitted_font(draw, 'Verified ' + content.data_at, 350, 15, 11), MUTED)


def _badge(draw: ImageDraw.ImageDraw, value: str, label: str,
           box: tuple[int, int, int, int], accent: tuple[int, int, int]) -> None:
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=10, fill=PANEL, outline=(*accent, 201), width=2)
    _center_text(draw, (left + right) // 2, top + 6, value,
                 _fitted_font(draw, value, right - left - 20, 38, 23), WHITE)
    _center_text(draw, (left + right) // 2, bottom - 24, label.upper(),
                 _fitted_font(draw, label.upper(), right - left - 12, 16, 12), MUTED)


def _fixture_tiles(canvas: Image.Image, draw: ImageDraw.ImageDraw, card: Card, x: int, y: int,
                   tile_width: int, session: requests.Session,
                   cache: dict[tuple[str, int], Image.Image | None]) -> None:
    for idx, fixture in enumerate(card.fixtures[:3]):
        opponent, venue, difficulty, team_code = fixture
        xx = x + idx * (tile_width + 8)
        color = _fixture_color(difficulty)
        draw.rounded_rectangle((xx, y, xx + tile_width, y + 58), radius=9,
                               fill=(*tuple(max(10, channel // 5) for channel in color), 250),
                               outline=(*color, 255), width=2)
        if team_code is None:
            raise RuntimeError(f'Missing opponent club code for {opponent}')
        crest = _media(session, team_code, 'crest', cache)
        if crest is None:
            raise RuntimeError(f'Missing fixture badge for {opponent}')
        _crest(canvas, crest, xx + 4, y + 6, 44)
        _text(draw, f'{opponent} ({venue})', xx + 49, y + 17, tile_width - 88, 18, WHITE, 12)
        draw.rounded_rectangle((xx + tile_width - 36, y + 6, xx + tile_width - 5, y + 52),
                               radius=6, fill=(*color, 255))
        _center_text(draw, xx + tile_width - 21, y + 12, str(difficulty), _font(25), (2, 14, 29))


def _news(canvas: Image.Image, content: Content,
          media: list[tuple[Image.Image | None, Image.Image | None]], session: requests.Session) -> None:
    draw = ImageDraw.Draw(canvas, 'RGBA')
    count = len(content.cards)
    gap = 22
    width = (1472 - gap * (count - 1)) // count
    for index, (card, (portrait, crest)) in enumerate(zip(content.cards, media)):
        x = 32 + index * (width + gap)
        accent = PALETTE[index]
        _panel(draw, (x, 150, x + width, 715), accent)
        _text(draw, 'FPL STATUS UPDATE  •  OFFICIAL FLAG', x + 25, 176, width - 50, 19, accent)
        _text(draw, card.headline.upper(), x + 23, 216, width - 120 if crest else width - 46, 34, WHITE)
        _text(draw, card.subtitle.upper(), x + 24, 259, width - 48, 26, accent)
        if crest is not None:
            _crest(canvas, crest, x + width - 96, 202, 66)
        if portrait is not None:
            _photo(canvas, portrait, (x + width - 227, 300, x + width - 19, 510), accent)
        elif crest is not None:
            _crest(canvas, crest, x + width - 208, 334, 145)
            _text(draw, 'PORTRAIT UNAVAILABLE', x + width - 221, 495, 203, 15, MUTED)
        price = str(card.metrics.get('price', '')) if card.metrics else ''
        _badge(draw, price, 'CURRENT PRICE', (x + 18, 318, x + width - 236 if width > 400 else x + 170, 386), accent)
        draw.rounded_rectangle((x + 18, 518, x + width - 18, 666), radius=11,
                               fill=(0, 14, 35, 252), outline=(*accent, 200), width=2)
        status = str(card.metrics.get('status', '')) if card.metrics else 'NO NEW UPDATE'
        _text(draw, f'FPL STATUS: {status.upper()}', x + 35, 530, width - 70, 22, accent)
        detail = card.fields[1] if card.metrics and len(card.fields) > 1 else (card.fields[0] if card.fields else 'No new dated FPL updates.')
        _wrapped(draw, detail, x + 35, 571, width - 70, 3, 22, WHITE)
        if not card.metrics:
            _center_text(draw, x + width // 2, 415, 'NO NEW PLAYER FLAGS', _font(33), MUTED)


def _large_feature(canvas: Image.Image, content: Content, card: Card,
                   portrait: Image.Image | None, crest: Image.Image | None, session: requests.Session) -> None:
    draw = ImageDraw.Draw(canvas, 'RGBA')
    _panel(draw, (35, 152, 1500, 715), CYAN)
    if crest is None or not card.metrics:
        raise RuntimeError('Elite feature must include verified club badge and metrics')
    if portrait is not None:
        _photo(canvas, portrait, (42, 190, 525, 702), CYAN)
    else:
        _crest(canvas, crest, 139, 315, 250)
        _text(draw, 'PORTRAIT UNAVAILABLE', 108, 592, 345, 20, MUTED)
    _crest(canvas, crest, 1340, 190, 100)
    _text(draw, card.label.upper(), 568, 180, 600, 27, CYAN)
    _text(draw, card.headline.upper(), 566, 220, 750, 65, WHITE)
    _text(draw, card.subtitle.upper(), 569, 296, 700, 35, GOLD)
    values = [
        (str(card.metrics['price']), 'PRICE'),
        (str(card.metrics['form']), 'FORM'),
        (str(card.metrics['total_points']), 'POINTS'),
        (str(card.metrics.get('ownership', 'N/A')) + '%', 'OWNED'),
        (str(card.metrics['goals']), 'GOALS'),
        (str(card.metrics['assists']), 'ASSISTS'),
    ]
    for idx, (value, label) in enumerate(values):
        column, row = idx % 3, idx // 3
        x = 567 + column * 298
        y = 366 + row * 93
        _badge(draw, value, label, (x, y, x + 277, y + 79), CYAN if column % 2 == 0 else GOLD)
    _text(draw, 'NEXT 3 FIXTURES', 576, 566, 530, 24, GOLD)
    _fixture_tiles(canvas, draw, card, 565, 608, 281, session, {})


def _four_card_layout(canvas: Image.Image, content: Content,
                     media: list[tuple[Image.Image | None, Image.Image | None]], session: requests.Session) -> None:
    draw = ImageDraw.Draw(canvas, 'RGBA')
    count = len(content.cards)
    gap = 16
    width = (1474 - gap * (count - 1)) // count
    for index, (card, (portrait, crest)) in enumerate(zip(content.cards, media)):
        x = 31 + index * (width + gap)
        accent = PALETTE[index]
        _panel(draw, (x, 151, x + width, 715), accent)
        _text(draw, card.label.upper(), x + 18, 175, width - 42, 19, accent)
        _text(draw, card.headline.upper(), x + 17, 211, width - 95 if crest else width - 30, 32, WHITE)
        _text(draw, card.subtitle.upper(), x + 18, 253, width - 40, 23, GOLD)
        if crest is not None:
            _crest(canvas, crest, x + width - 79, 209, 64)
        if portrait is not None:
            _photo(canvas, portrait, (x + width - 234, 288, x + width - 13, 521), accent)
        elif crest is not None:
            _crest(canvas, crest, x + width - 196, 329, 140)
            _text(draw, 'PORTRAIT UNAVAILABLE', x + width - 225, 498, 209, 14, MUTED)
        if content.kind == 'prices' and card.metrics:
            change = str(card.metrics['change'])
            before = str(card.metrics['before'])
            after = str(card.metrics['after'])
            _badge(draw, before, 'WAS', (x + 15, 333, x + 126, 404), accent)
            _badge(draw, after, 'NOW', (x + 15, 417, x + 126, 487), accent)
            _badge(draw, change, 'CONFIRMED', (x + 17, 544, x + width - 17, 633), GREEN if change.startswith('+') else MAGENTA)
        elif content.kind == 'review' and card.metrics:
            _badge(draw, str(card.metrics['gw_points']), 'GW POINTS', (x + 18, 340, x + 149, 417), accent)
            _badge(draw, str(card.metrics['total_points']), 'SEASON PTS', (x + 18, 433, x + 149, 508), accent)
            _badge(draw, str(card.metrics['price']), 'PRICE', (x + 17, 550, x + width - 18, 634), accent)
        elif content.kind == 'captaincy' and card.metrics:
            _badge(draw, str(card.metrics['total_points']), 'POINTS', (x + 15, 338, x + 140, 410), accent)
            _badge(draw, str(card.metrics['form']), 'FORM', (x + 15, 426, x + 140, 501), accent)
            if card.fixtures:
                _text(draw, 'NEXT FIXTURE', x + 21, 546, width - 35, 18, accent)
                _fixture_tiles(canvas, draw, card, x + 13, 577, width - 26, session, {})
        else:
            if card.metrics:
                _badge(draw, str(card.metrics['assists']), 'ASSISTS', (x + 14, 338, x + 142, 410), accent)
                _badge(draw, str(card.metrics.get('xa', 'N/A')), 'EXPECTED A', (x + 14, 425, x + 142, 500), accent)
                _badge(draw, str(card.metrics['form']), 'FORM', (x + 15, 551, x + width - 15, 635), accent)
            else:
                _wrapped(draw, '  '.join(card.fields), x + 25, 365, width - 50, 4, 24, WHITE)
        if content.kind in ('prices', 'review'):
            _text(draw, 'VERIFIED OFFICIAL FPL DATA', x + 22, 666, width - 44, 16, MUTED)


def render_premium(content: Content, output: Path, session: requests.Session) -> Path:
    """Render verified data with club crests when a CDN player portrait is unavailable."""
    supported = {'news', 'prices', 'captaincy', 'review', 'elite', 'evening'}
    if content.kind not in supported:
        raise ValueError(f'No premium layout for {content.kind}')
    if not content.cards:
        raise ValueError('Cannot publish an empty card list')
    media = _media_required(content.cards, session)
    canvas = _background(content)
    _header(canvas, content)
    if content.kind == 'elite':
        _large_feature(canvas, content, content.cards[0], *media[0], session)
    elif content.kind == 'news':
        _news(canvas, content, media, session)
    else:
        _four_card_layout(canvas, content, media, session)
    _footer(canvas, content)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.tmp.png')
    canvas.save(temp, format='PNG', optimize=True)
    temp.replace(output)
    return output