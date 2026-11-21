"""Reference-style FPL VORTEX press poster; all statements are sourced data.

Preserves the existing assets/press logo and footer, never the sample's names,
quotes or its illustrative Gameweek 1 text. Real FPL clubs and status only.
"""
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .graphic_numbers import stamp

ASSETS = Path(__file__).resolve().parents[1] / "assets/press"
BG = (8, 8, 32)
PURPLE = (154, 47, 252)
CYAN = (63, 225, 252)
GOLD = (255, 219, 71)
WHITE = (245, 245, 255)
MUTED = (188, 187, 213)


def render(path, day, names, facts, locked, teams=None):
    width, height = 1920, 1080
    im = Image.new("RGB", (width, height), BG)
    pixels = im.load()
    # Quiet navy-to-violet studio gradient, inspired by the supplied reference.
    for y in range(984):
        for x in range(width):
            shade = min(1.0, x / width * .45 + y / height * .25)
            pixels[x, y] = (int(8 + 17 * shade), int(8 + 3 * shade),
                            int(32 + 53 * shade))
    d = ImageDraw.Draw(im)

    def font(size, bold=False):
        path = "DejaVuSansCondensed-Bold.ttf" if bold else "DejaVuSansCondensed.ttf"
        return ImageFont.truetype(path, size)

    def fit(value, max_width, size, minimum=17, bold=False):
        value = str(value).replace("\n", " ").strip()
        while size > minimum and d.textlength(value, font=font(size, bold)) > max_width:
            size -= 1
        if d.textlength(value, font=font(size, bold)) > max_width:
            while value and d.textlength(value + "…", font=font(size, bold)) > max_width:
                value = value[:-1]
            value = value.rstrip() + "…"
        return value, font(size, bold)

    def text(x, y, value, max_width, size=27, color=WHITE, bold=False):
        value, face = fit(value, max_width, size, bold=bold)
        d.text((x, y), value, font=face, fill=color)

    def wrap(value, max_width, size=26, limit=2):
        result, line = [], ""
        for word in str(value).replace("\n", " ").split():
            candidate = (line + " " + word).strip()
            if line and d.textlength(candidate, font=font(size)) > max_width:
                result.append(line)
                line = word
            else:
                line = candidate
        if line:
            result.append(line)
        if len(result) > limit:
            result = result[:limit]
            result[-1], _ = fit(result[-1] + "…", max_width, size)
        return result

    def panel(box, label, accent=PURPLE):
        x1, y1, x2, y2 = box
        d.rounded_rectangle(box, radius=28, fill=(15, 10, 44), outline=accent, width=4)
        d.rounded_rectangle((x1+10, y1+9, x2-10, y1+64), radius=18,
                            fill=(65, 21, 129))
        text(x1+27, y1+14, label, x2-x1-54, 35, WHITE, True)

    def note(x, y, s, color=GOLD):
        d.ellipse((x, y+9, x+13, y+22), fill=color)
        text(x+29, y, s, 548, 26, WHITE)

    with Image.open(ASSETS / "logo.jpg") as raw:
        logo = ImageOps.contain(raw.convert("RGB"), (405, 141))
        im.paste(logo, (12, (149-logo.height)//2))
    d.rounded_rectangle((431, 20, 1532, 126), radius=30,
                        fill=(68, 14, 179), outline=(152, 45, 253), width=5)
    d.ellipse((452, 37, 516, 104), outline=WHITE, width=4)
    d.rounded_rectangle((476, 46, 492, 77), radius=6, fill=WHITE)
    d.arc((468, 51, 500, 88), 0, 180, fill=WHITE, width=4)
    d.line((484, 88, 484, 97), fill=WHITE, width=4)
    text(535, 36, "PRESS CONFERENCE", 985, 73, WHITE, True)
    text(1562, 26, f"GAMEWEEK {day['gw']}", 345, 44, WHITE, True)
    text(1615, 85, f"{day['season']}/{str(day['season'] + 1)[-2:]}", 280, 35,
         (150, 253, 69), True)
    d.line((12, 155, 1908, 155), fill=(94, 31, 223), width=6)

    panel((12, 173, 656, 970), "LATEST NEWS")
    panel((670, 173, 1296, 713), "KEY QUOTES")
    panel((670, 730, 1296, 970), "MANAGER'S NOTES")
    panel((1310, 173, 1908, 970), "PRESS CONFERENCE ROUND-UP")

    ordered = sorted(
        facts.items(),
        key=lambda kv: (kv[1].get("published", ""), names.get(kv[0], "")),
        reverse=True,
    )
    # Each card is a real official-club paragraph. No sample quotes carried over.
    for index, (key, fact) in enumerate(
        [(key, fact) for key, fact in ordered if fact.get("news")][:8]
    ):
        y = 257 + index*85
        d.rounded_rectangle((27, y, 641, y+77), radius=17,
                            fill=(24, 13, 60), outline=(113, 34, 220), width=2)
        d.ellipse((42, y+16, 86, y+60), fill=(74, 26, 171))
        text(54, y+22, str(index+1), 28, 25, WHITE, True)
        text(101, y+6, names[key], 520, 26, CYAN, True)
        for i, line in enumerate(wrap(fact["news"], 518, 21, 2)):
            text(103, y+36+i*22, line, 518, 21, WHITE)
    if not ordered:
        text(49, 284, "Awaiting verified club reports.", 560, 31, MUTED)

    quotes = [(key, fact["quote"]) for key, fact in ordered if fact.get("quote")]
    for index, (key, quote) in enumerate(quotes[:4]):
        y = 254 + index*109
        d.rounded_rectangle((684, y, 1280, y+101), radius=17,
                            fill=(22, 12, 57), outline=(118, 42, 208), width=2)
        text(701, y+4, "“", 50, 47, GOLD, True)
        text(752, y+6, names[key], 495, 25, CYAN, True)
        for i, line in enumerate(wrap("“" + quote + "”", 528, 22, 2)):
            text(727, y+42+i*23, line, 528, 22)
    if not quotes:
        text(702, 290, "No attributable manager quotation verified yet.", 559, 24, MUTED)

    note(701, 811, f"{len(facts)}/{len(names)} clubs have verified reports.")
    note(701, 858, "Unconfirmed clubs remain marked as awaiting.")
    note(701, 906, "Sources: linked official club reports.")

    crests = {}
    if teams:
        with requests.Session() as session:
            for key in names:
                team = teams.get(int(key), {})
                code = team.get("code")
                if not isinstance(code, int) or code <= 0:
                    continue
                try:
                    r = session.get(
                        f"https://resources.premierleague.com/premierleague/badges/50/t{code}.png",
                        timeout=2.5,
                        headers={"User-Agent": "FPL-VORTEX/Press/1.0"},
                    )
                    if r.ok and r.headers.get("Content-Type", "").startswith("image/") and 500 < len(r.content) < 600000:
                        with Image.open(BytesIO(r.content)) as raw:
                            crests[key] = raw.convert("RGBA")
                except (requests.RequestException, OSError, ValueError):
                    continue
    for index, key in enumerate(sorted(names, key=lambda k: names[k])):
        y = 253 + index*34
        fact = facts.get(key)
        d.rounded_rectangle((1323, y, 1895, y+32), radius=12,
                            fill=(30, 14, 65) if index % 2 else (21, 10, 49))
        d.rounded_rectangle((1327, y+2, 1364, y+31), radius=12,
                            fill=(75, 25, 168))
        text(1333, y+2, str(index+1), 27, 20, WHITE, True)
        if key in crests:
            badge = crests[key]
            badge.thumbnail((29, 29))
            im.paste(badge, (1372+(29-badge.width)//2, y+1+(29-badge.height)//2), badge)
        else:
            text(1379, y+5, names[key][:1], 20, 17, GOLD, True)
        text(1409, y+3, names[key], 217, 21, WHITE, True)
        status = "CONFIRMED" if fact else "Awaiting club source"
        text(1635, y+5, status, 253, 18, CYAN if fact else MUTED, bool(fact))

    with Image.open(ASSETS / "footer.jpg") as raw:
        im.paste(raw.convert("RGB").resize((1920, 96)), (0, 984))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    stamp(path, "verified-press-availability")
