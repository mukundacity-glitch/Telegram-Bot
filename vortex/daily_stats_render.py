"""Render the ten-card stats edition on the original blue broadcast master."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
import requests

from .brand_footer import MASTER, verify_exact_master
from .content import Content
from .matchup import _media
from .minimal_theme import CYAN, INK, MUTED, social_footer
from .render import _fit_text, _player_image, font


def render_daily_stats(content: Content, output: Path, session: requests.Session) -> Path:
    if len(content.cards) != 10:
        raise ValueError("The stats graphic requires exactly ten verified facts")
    verify_exact_master()
    with Image.open(MASTER) as master:
        canvas = master.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.text((960, 29), content.title, fill=INK, font=font(47), anchor="mm",
              stroke_width=2, stroke_fill="#06142c")
    draw.polygon([(719, 75), (1224, 75), (1201, 124), (696, 124)],
                 fill=(6, 26, 65, 255), outline=CYAN, width=2)
    draw.text((960, 100), content.kicker, fill=INK, font=font(28), anchor="mm")

    # Download each official crest once. The verified club code remains
    # available as a short club label when the image CDN is unavailable.
    team_codes = sorted({card.team_code for card in content.cards if card.team_code})
    photo_codes = sorted({card.photo_code for card in content.cards if card.photo_code})
    with ThreadPoolExecutor(max_workers=8) as workers:
        futures = {code: workers.submit(_media, session, code, "crest", {})
                   for code in team_codes}
        portraits = {code: workers.submit(_player_image, session, code) for code in photo_codes}
        crests = {code: future.result() for code, future in futures.items()}
        photos = {code: future.result() for code, future in portraits.items()}

    for index, card in enumerate(content.cards):
        row, col = divmod(index, 5)
        x, y = 71 + 359 * col, 148 + 418 * row
        right, bottom = x + 341, y + 397
        points = [(x + 18, y), (right - 16, y), (right, y + 16),
                  (right, bottom - 16), (right - 16, bottom), (x, bottom), (x, y + 18)]
        draw.polygon(points, fill=(5, 19, 47, 244), outline=(23, 153, 223), width=2)
        draw.line([(x + 18, y), (right - 16, y), (right, y + 16)], fill=CYAN, width=3)
        draw.polygon([(x + 18, y), (x + 74, y), (x + 59, y + 50), (x, y + 50), (x, y + 18)],
                     fill=CYAN)
        draw.text((x + 35, y + 25), f"{index + 1:02d}", fill="#04172c", font=font(27), anchor="mm")
        draw.text((x + 81, y + 26), card.label.upper(), fill=INK,
                  font=_fit_text(draw, card.label.upper(), 246, 24, 17), anchor="lm")

        crest = crests.get(card.team_code)
        photo = photos.get(card.photo_code)
        if photo is not None:
            portrait = ImageOps.contain(photo, (134, 134), Image.Resampling.LANCZOS)
            canvas.paste(portrait, (x + 149 - portrait.width // 2, y + 184 - portrait.height), portrait)
            if crest is not None:
                badge = ImageOps.contain(crest, (67, 67), Image.Resampling.LANCZOS)
                canvas.paste(badge, (x + 231, y + 111), badge)
        elif crest is not None:
            badge = ImageOps.contain(crest, (108, 108), Image.Resampling.LANCZOS)
            canvas.paste(badge, (x + (341 - badge.width) // 2, y + 113 - badge.height // 2), badge)
        else:
            draw.text((x + 171, y + 113), card.subtitle, fill=MUTED, font=font(43), anchor="mm")
        draw.text((x + 171, y + 203), card.headline, fill=INK, anchor="mm",
                  font=_fit_text(draw, card.headline, 300, 36))
        draw.rounded_rectangle((x + 18, y + 237, right - 18, y + 346), radius=11,
                               fill=(6, 36, 76), outline=(35, 102, 152), width=2)
        value, detail = card.fields
        draw.text((x + 171, y + 291), value, fill=CYAN, anchor="mm",
                  font=_fit_text(draw, value, 286, 65))
        draw.text((x + 171, y + 370), detail, fill=MUTED, anchor="mm",
                  font=_fit_text(draw, detail, 297, 25, 18))

    social_footer(canvas, os.getenv("FPL_TELEGRAM_HANDLE", ""), os.getenv("FPL_DISCORD_HANDLE", ""))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix(".tmp.png")
    canvas.save(staging, "PNG", optimize=True)
    staging.replace(output)
    return output
