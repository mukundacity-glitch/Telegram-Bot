"""Render the daily fixture guide in the approved two-column stadium style."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
import requests

from .brand_footer import MASTER, verify_exact_master
from .content import Content
from .matchup import _media
from .minimal_theme import CYAN, GOLD, INK, MUTED, social_footer
from .publication_rules import FDR_COLORS
from .render import _fit_text, _player_image, font


def render_fixture_guide(content: Content, output: Path, session: requests.Session) -> Path:
    if len(content.cards) != 6:
        raise ValueError("The fixture guide requires six ranked clubs")
    verify_exact_master()
    with Image.open(MASTER) as master:
        canvas = master.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.text((960, 29), content.title, fill=GOLD, font=font(46), anchor="mm",
              stroke_width=2, stroke_fill="#051127")
    draw.text((960, 76), "WHO TO TARGET  •  WHO TO WATCH", fill=INK, font=font(30), anchor="mm")
    draw.rounded_rectangle((808, 102, 1112, 146), 9, fill=GOLD)
    draw.text((960, 124), content.kicker, fill="#07152d", font=font(29), anchor="mm")

    assets = {(kind, code) for card in content.cards
              for kind, code in (("crest", card.team_code), ("photo", card.photo_code)) if code}
    with ThreadPoolExecutor(max_workers=8) as workers:
        futures = {
            (kind, code): workers.submit(_player_image, session, code) if kind == "photo"
            else workers.submit(_media, session, code, kind, {})
            for kind, code in assets
        }
        media = {key: future.result() for key, future in futures.items()}

    for column, label in enumerate(("BEST FIXTURES / TARGETS", "TOUGH RUNS / CAUTION")):
        x = 77 + column * 896
        accent = "#5cf1aa" if column == 0 else GOLD
        draw.rounded_rectangle((x, 186, x + 870, 885), 22,
                               fill=(5, 18, 46, 223), outline=CYAN, width=3)
        draw.polygon([(x+144, 158), (x+754, 158), (x+732, 211), (x+122, 211)],
                     fill=(7, 27, 54), outline=accent, width=3)
        draw.text((x+435, 185), label, fill=INK, font=font(30), anchor="mm")

        for row, card in enumerate(content.cards[column*3:column*3+3]):
            y = 228 + row * 216
            draw.rounded_rectangle((x+14, y, x+856, y+204), 12,
                                   fill=(10, 28, 65, 239), outline=(33, 105, 167), width=2)
            crest = media.get(("crest", card.team_code))
            photo = media.get(("photo", card.photo_code))
            for asset, center, size in ((crest, x+78, 93), (photo, x+220, 134)):
                if asset is not None:
                    tile = ImageOps.contain(asset, (size, size), Image.Resampling.LANCZOS)
                    canvas.paste(tile, (center-tile.width//2, y+134-tile.height), tile)
            left = x+317 if photo is not None else x+151
            draw.text((left, y+16), card.headline.upper(), fill=INK,
                      font=_fit_text(draw, card.headline.upper(), x+828-left, 37))
            name = card.subtitle + "  •  " if card.subtitle else ""
            detail = name + card.fields[2]
            draw.text((left, y+61), detail, fill=MUTED,
                      font=_fit_text(draw, detail, x+828-left, 26))
            summary = f"{card.fields[0]}  •  {card.fields[1]}"
            draw.text((left, y+101), summary, fill=accent, font=font(26))

            fixtures = card.fixtures
            # Wrap double gameweeks onto another line while retaining every fixture.
            for i, (opponent, venue, fdr, _) in enumerate(fixtures):
                chip_row, chip_col = divmod(i, 8)
                if chip_row >= 2:
                    raise ValueError("Fixture guide cannot fit this gameweek span")
                count = min(8, len(fixtures) - chip_row * 8)
                width = 810 // count
                px, py = x + 30 + width * chip_col, y + 139 + chip_row * 29
                text = f"{opponent} {venue}".strip()
                draw.rounded_rectangle((px, py, px+width-6, py+25), 6,
                                       fill=FDR_COLORS.get(fdr, "#99abc3"))
                draw.text((px+(width-6)/2, py+13), text, fill="#091427", anchor="mm",
                          font=_fit_text(draw, text, width-12, 19, 13))

    draw.polygon([(133, 908), (1797, 908), (1820, 942), (1794, 983), (133, 983), (100, 945)],
                 fill=(6, 23, 53, 255), outline=GOLD, width=3)
    draw.text((158, 945), "FPL VORTEX VERDICT", fill=GOLD, font=font(29), anchor="lm")
    draw.text((537, 945), content.verdict, fill=INK, anchor="lm",
              font=_fit_text(draw, content.verdict, 1200, 32))
    social_footer(canvas, os.getenv("FPL_TELEGRAM_HANDLE", ""), os.getenv("FPL_DISCORD_HANDLE", ""))

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix(".tmp.png")
    canvas.save(staging, "PNG", optimize=True)
    staging.replace(output)
    return output
