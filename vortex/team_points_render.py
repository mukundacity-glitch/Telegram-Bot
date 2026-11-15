"""Two aligned crest columns with a shared league-points axis."""

from concurrent.futures import ThreadPoolExecutor
from math import ceil

from PIL import Image, ImageDraw, ImageOps

from .comparison_board import CYAN, GOLD, WHITE, contain, text
from .matchup import _media
from .vortex_style import LION, gradient


def arrange(rows, value, center, y_for, accent):
    # Draw at the exact score height. Resolve ties and nearby markers horizontally.
    ordered = sorted(rows, key=lambda row: (-row[value], row['short']))
    for size in range(54, 9, -4):
        step = size + 4
        offsets = sorted(range(-(172 // step), (172 // step) + 1), key=abs)
        occupied = []
        for row in ordered:
            y = round(y_for(row[value]))
            x = next((center + idx * step for idx in offsets
                      if all(abs(center + idx*step - px) >= step or abs(y-py) >= step
                             for px, py, _, _ in occupied)), None)
            if x is None:
                break
            occupied.append((x, y, row, accent))
        else:
            return size, occupied
    raise ValueError('League points crest placement exceeds available chart width')


def render_team_points(plan, output, session):
    canvas = gradient((1080, 1920), (22, 13, 49), (8, 13, 31))
    draw = ImageDraw.Draw(canvas)
    rows = plan.extra['teams']
    draw.rounded_rectangle((267, 19, 813, 192), 24, fill='#000000', outline='#76553a', width=2)
    with Image.open(LION.parent / 'midfield-watch-logo.png') as logo:
        brand = ImageOps.contain(logo.convert('RGB'), (500, 170), Image.Resampling.LANCZOS)
        canvas.paste(brand, ((1080-brand.width)//2, 21))
    text(draw, plan.title, 24, 211, 1032, 53, WHITE, center=True)
    series = "WEEKLY ANALYSIS 1/7" if plan.extra.get("day") == 1 else "PREMIER LEAGUE"
    text(draw, f"{series}  •  THROUGH GW{plan.extra['through']}  •  {len(plan.extra['matches'])} MATCHES",
         38, 279, 1004, 25, GOLD, center=True)

    draw.rounded_rectangle((32, 350, 1048, 1575), 26, fill='#101a38', outline='#413a68', width=2)
    draw.rounded_rectangle((128, 366, 564, 1559), 18, fill='#16213e')
    draw.rounded_rectangle((576, 366, 1031, 1559), 18, fill='#171d38')
    text(draw, 'EXPECTED', 128, 393, 436, 36, CYAN, center=True)
    text(draw, 'ACTUAL', 576, 393, 455, 36, GOLD, center=True)
    text(draw, 'PTS', 42, 399, 70, 20, WHITE, center=True)

    top, bottom = 487, 1505
    values = [row[key] for row in rows for key in ('expected', 'actual')]
    minimum = max(0, int(min(values)) - 1)
    maximum = max(minimum+2, ceil(max(values)) + 1)
    step = max(1, ceil((maximum - minimum) / 24))

    def y_for(points):
        return bottom - (points - minimum) * (bottom-top) / (maximum-minimum)

    for mark in range(minimum, maximum+1, step):
        y = round(y_for(mark))
        draw.line((114, y, 1011, y), fill='#35446a', width=1)
        text(draw, str(mark), 47, y-13, 55, 23, WHITE, center=True)
    draw.line((114, top, 114, bottom), fill='#7586ad', width=2)

    with ThreadPoolExecutor(max_workers=8) as pool:
        crests = dict(zip((row['code'] for row in rows),
                          pool.map(lambda row: _media(session, row['code'], 'crest', {}), rows)))
    for key, x, accent in (('expected', 346, CYAN), ('actual', 806, GOLD)):
        size, placed = arrange(rows, key, x, y_for, accent)
        for cx, cy, row, color in placed:
            radius = size // 2
            draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
                         fill='#e8eef9', outline=color, width=2)
            crest = crests[row['code']]
            if crest is not None:
                contain(canvas, crest, (cx-radius+4, cy-radius+4, size-8, size-8))
            else:
                text(draw, row['short'], cx-radius+2, cy-size*.16, size-4, size*.32,
                     '#17213d', minimum=6, center=True)

    text(draw, 'EXPECTED: MATCH-xG MODEL     •     ACTUAL: LEAGUE MATCH POINTS',
         38, 1613, 1004, 24, CYAN, center=True)
    text(draw, 'SAME FIXTURES IN BOTH COLUMNS', 38, 1652, 1004, 21, WHITE, center=True)
    text(draw, 'FPL VORTEX  •  CHECK MINUTES & FIXTURES BEFORE TRANSFERRING',
         34, 1723, 1012, 23, GOLD, center=True)
    with Image.open(LION.parent / 'midfield-watch-footer.png') as footer:
        bar = ImageOps.contain(footer.convert('RGB'), (1056, 116), Image.Resampling.LANCZOS)
        canvas.paste(bar, ((1080-bar.width)//2, 1782))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, 'PNG', optimize=True)
    return output
