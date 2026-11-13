"""Draw a 1920×1080 comparison, with raw totals beside the radar."""
from concurrent.futures import ThreadPoolExecutor
from math import cos, pi, sin

from PIL import Image, ImageDraw

from .brand_footer import MASTER, verify_exact_master
from .comparison_board import contain, text
from .matchup import _image_from_url, _media
from .minimal_theme import social_footer
from .publication_rules import FDR_COLORS, required_footer_handles
from .render import font

CYAN = "#39ddf4"
GOLD = "#ffc959"
INK = "#f0f6ff"
MUTED = "#9db7d8"
PANEL = "#091932"


def _portrait(session, code):
    root = "https://resources.premierleague.com"
    for path in (
        f"premierleague25/photos/players/250x250/{code}.png",
        f"premierleague/photos/players/250x250/p{code}.png",
        f"premierleague25/photos/players/110x140/{code}.png",
    ):
        if (image := _image_from_url(session, f"{root}/{path}")) is not None:
            return image
    return None


def render_radar(plan, snapshot, output, session):
    verify_exact_master()
    with Image.open(MASTER) as original:
        canvas = original.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas, "RGBA")
    text(draw, plan.title, 310, 4, 1300, 46, INK, 30, center=True)
    rounds = plan.extra["rounds"]
    history = " · ".join(f"GW{gw}" for gw in rounds)
    text(draw, f"LAST FIVE COMPLETED GAMEWEEKS  /  {history}", 310, 78, 1300, 25, CYAN, 18, center=True)
    for box in ((55, 129, 1008, 777), (1030, 129, 1865, 777), (55, 793, 1865, 990)):
        draw.rounded_rectangle(box, 19, fill=PANEL, outline="#2d6199", width=2)

    with ThreadPoolExecutor(max_workers=4) as workers:
        portraits = [workers.submit(_portrait, session, snapshot.photo_code(p)) for p in plan.players]
        crests = [workers.submit(_media, session, snapshot.team_code(p), "crest", {}) for p in plan.players]
        media = [(photo.result(), crest.result()) for photo, crest in zip(portraits, crests)]
    if any(photo is None or crest is None for photo, crest in media):
        raise RuntimeError("Player Radar needs both official portraits and both club crests")

    colors = (CYAN, GOLD)
    for i, (player, (photo, crest)) in enumerate(zip(plan.players, media)):
        x = 1085 + i * 388
        contain(canvas, photo, (x+34, 151, 224, 198), bottom=True, crop_alpha=True)
        contain(canvas, crest, (x+253, 206, 78, 78))
        text(draw, snapshot.name(player), x, 352, 355, 36, colors[i], 21, center=True)
        team = snapshot.team(player)
        text(draw, f"{team}  •  {snapshot.price(player)}", x, 395, 355, 24, MUTED, 17, center=True)

    labels = plan.extra["metrics"]
    values = plan.extra["values"]
    cx, cy, radius = 531, 455, 225
    angles = [2*pi*i/len(labels)-pi/2 for i in range(len(labels))]

    def point(angle, fraction):
        return cx + radius*fraction*cos(angle), cy + radius*fraction*sin(angle)

    for ring in (.25, .5, .75, 1):
        draw.polygon([point(angle, ring) for angle in angles], outline="#355071", width=2)
    for label, angle in zip(labels, angles):
        draw.line([(cx, cy), point(angle, 1)], fill="#355071", width=2)
        lx, ly = point(angle, 1.23)
        draw.text((lx, ly), label, anchor="mm", font=font(24), fill=INK)

    for i, (row, color) in enumerate(zip(values, colors)):
        polygon = [point(angle, max(0, row[label]) / (max(0, *(v[label] for v in values)) or 1))
                   for label, angle in zip(labels, angles)]
        draw.polygon(polygon, fill=(57, 221, 244, 47) if i == 0 else (255, 201, 89, 47),
                     outline=color, width=4)
        for x, y in polygon:
            draw.ellipse((x-6, y-6, x+6, y+6), fill=color, outline=PANEL, width=2)
    text(draw, "RADAR SCALED TO THE HIGHER TOTAL ON EACH AXIS", 100, 740, 860, 21, MUTED, 16, center=True)

    for i, label in enumerate(labels):
        y = 439 + 39*i
        draw.rounded_rectangle((1054, y, 1841, y+34), 5, fill="#102749")
        text(draw, label, 1080, y+3, 350, 24, INK, 18)
        for column, row in enumerate(values):
            value = f"{row[label]:.2f}" if label in ("xG", "xA") else f"{row[label]:.0f}"
            text(draw, value, 1460 + 188*column, y+3, 134, 24, colors[column], 18, center=True)

    text(draw, "NEXT FIVE GAMEWEEKS  /  OFFICIAL FPL FIXTURE DIFFICULTY", 88, 806, 1680, 27, INK, 18)
    for i, (p, fixtures) in enumerate(zip(plan.players, plan.extra["fixtures"])):
        y = 849 + 62*i
        text(draw, snapshot.name(p), 88, y+10, 280, 27, colors[i], 18)
        for j, gw in enumerate(sorted({row["gw"] for row in fixtures})):
            items = [row for row in fixtures if row["gw"] == gw]
            left = 380 + 291*j
            draw.rounded_rectangle((left, y, left+280, y+49), 7, fill="#102749")
            text(draw, f"GW{gw}", left+7, y+14, 64, 19, MUTED, 12)
            width = 200 / len(items)
            for k, row in enumerate(items):
                start = left+73+k*width
                label = "BLANK" if row["blank"] else f"{row['opponent']} {row['venue']} · {row['fdr']}"
                color = FDR_COLORS.get(row["fdr"], "#9db7d8")
                draw.rounded_rectangle((start, y+7, start+width-4, y+42), 5, outline=color)
                text(draw, label, start+3, y+15, width-10, 18, color, 10, center=True)
    social_footer(canvas, *required_footer_handles())
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, "PNG", optimize=True)
    return output
