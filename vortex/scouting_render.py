"""Branded landscape scatterplots and a seven-gameweek goalkeeper heatmap."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from math import ceil, log10

from PIL import ImageDraw

from .autonomous_render import _base, _save
from .autonomous_schedule import ET
from .comparison_board import CYAN, GOLD, WHITE, contain, paragraph, text
from .editorial_inputs import RequiredInput
from .matchup import _media

PANEL = '#122644'
GRID = '#345370'
MUTED = '#b1c7db'
FDR_COLORS = ('#14604f', '#205449', '#344c70', '#77452e', '#762947')


def axis_limit(maximum):
    if maximum <= 0:
        return 1
    magnitude = 10 ** (int(log10(maximum)) if maximum >= 1 else -ceil(-log10(maximum)))
    return ceil(maximum / magnitude) * magnitude


def portraits(session, rows):
    codes = list(dict.fromkeys(row['photo'] for row in rows if row['photo']))
    with ThreadPoolExecutor(max_workers=5) as pool:
        return dict(zip(codes, pool.map(lambda code: _media(session, code, 'photo', {}), codes)))


def draw_scatter(canvas, details, session):
    draw = ImageDraw.Draw(canvas, 'RGBA')
    left, right, top, bottom = 105, 920, 163, 686
    rows, featured = details['rows'], details['featured']
    photos = portraits(session, featured)
    percentile = details['percentiles']
    x_max = 100 if percentile else axis_limit(max(r['x'] for r in rows))
    y_max = 100 if percentile else axis_limit(max(r['y'] for r in rows))
    unit = 'PERCENTILE' if percentile else 'PER 90'
    draw.rounded_rectangle((left, top, right, bottom), 11, fill=PANEL, outline=GRID, width=2)
    for tick in range(6):
        fraction = tick / 5
        x = left + (right - left) * fraction
        y = bottom - (bottom - top) * fraction
        draw.line((x, top, x, bottom), fill=GRID)
        draw.line((left, y, right, y), fill=GRID)
        text(draw, f'{x_max * fraction:.3g}', x - 35, bottom + 9, 70, 17, MUTED, center=True)
        text(draw, f'{y_max * fraction:.3g}', 42, y - 10, 51, 17, MUTED, center=True)
    text(draw, f"{details['y_name'].upper()}  ·  {unit} ↑", left, 125, right-left, 20, GOLD)
    text(draw, f"{details['x_name'].upper()}  ·  {unit} →", left, 724, right-left, 20, CYAN, center=True)
    featured_ids = {id(row): index for index, row in enumerate(featured, 1)}
    for row in sorted(rows, key=lambda row: id(row) in featured_ids):
        x = left + (right - left) * row['x'] / x_max
        y = bottom - (bottom - top) * row['y'] / y_max
        index = featured_ids.get(id(row))
        radius = 11 if index else 3
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=GOLD if index else '#7aafd5')
        if index:
            text(draw, index, x-10, y-8, 20, 14, '#122644', minimum=11, center=True)
    text(draw, 'PLAYERS TO WATCH', 963, 125, 535, 24, CYAN)
    for index, row in enumerate(featured, 1):
        y = 167 + (index - 1) * 105
        draw.rounded_rectangle((955, y, 1500, y+94), 14, fill=PANEL, outline=GRID)
        text(draw, index, 970, y+34, 29, 24, GOLD, center=True)
        photo = photos.get(row['photo'])
        if photo is not None:
            contain(canvas, photo, (1003, y+6, 75, 82), bottom=True, crop_alpha=True)
        text(draw, row['name'], 1090, y+9, 396, 27, WHITE)
        text(draw, row['club'], 1090, y+42, 396, 16, MUTED)
        gx, gy = (row['x'], row['y']) if percentile else row['rates']
        phrase = f'X {gx:.0f}  •  Y {gy:.0f}' if percentile else f'X {gx:.2f}  •  Y {gy:.2f}'
        text(draw, phrase, 1090, y+65, 396, 18, GOLD)


def draw_fixtures(canvas, details, session):
    draw = ImageDraw.Draw(canvas, 'RGBA')
    rows, weeks = details['rows'], details['weeks']
    photos = portraits(session, rows)
    if any(photos.get(row['photo']) is None for row in rows):
        raise RequiredInput('Official goalkeeper portrait unavailable')
    width = (1503 - 295) // len(weeks)
    for index, week in enumerate(weeks):
        text(draw, f'GW{week}', 295+index*width, 160, width-6, 25, CYAN, center=True)
    for index, row in enumerate(rows):
        y = 207 + index * 130
        draw.rounded_rectangle((28, y, 1506, y+121), 12, fill=PANEL, outline=GRID)
        contain(canvas, photos[row['photo']], (31, y+5, 91, 110), bottom=True, crop_alpha=True)
        text(draw, row['name'], 130, y+28, 154, 25, WHITE, minimum=14)
        paragraph(draw, row['club'], (130, y+65, 154), size=15, color=MUTED)
        for j, matches in enumerate(row['cells']):
            x = 295 + j * width
            if not matches:
                text(draw, 'BLANK', x, y+49, width-6, 18, MUTED, center=True)
                continue
            height = 112 // len(matches)
            for k, (opponent, venue, fdr) in enumerate(matches):
                cell_y = y+4+k*height
                draw.rounded_rectangle((x, cell_y, x+width-6, cell_y+height-4), 8, fill=FDR_COLORS[fdr-1])
                text(draw, f'{venue}  ·  FDR {fdr}', x+4, cell_y+4, width-14, 20 if height > 60 else 15,
                     WHITE, minimum=12, center=True)
                paragraph(draw, opponent, (x+7, cell_y+(46 if height > 60 else 24), width-20),
                          size=16 if height > 60 else 13, color=WHITE, lines=2)
    text(draw, 'OFFICIAL FPL FDR   ·   1 EASIEST   /   5 HARDEST   ·   H HOME   /   A AWAY',
         35, 743, 1465, 20, GOLD, center=True)


def render_scouting(plan, output, session):
    data = plan.extra
    is_fixtures = data['layout'] == 'fixtures'
    subtitle = (f"GW{plan.gw}  |  GOALKEEPER SCOUTING  |  FIXTURE DIFFICULTY"
                if is_fixtures else
                f"PREMIER LEAGUE  |  THROUGH GW{data['through']}  |  {data['minimum']}+ MINUTES")
    canvas = _base(plan.title.upper(), plan.gw, subtitle)
    if is_fixtures:
        draw_fixtures(canvas, data, session)
    else:
        draw_scatter(canvas, data, session)
    retrieved = datetime.fromisoformat(data['fetched_at']).strftime('%b %d %H:%M %z')
    generated = datetime.now(ET).strftime('%b %d %H:%M %z')
    origin = 'OFFICIAL FPL' if is_fixtures else 'FPL CORE MATCH STATS'
    text(ImageDraw.Draw(canvas, 'RGBA'),
         f'{origin}   ·   DATA {retrieved} ET   ·   RENDERED {generated} ET',
         30, 776, 1476, 16, MUTED, center=True)
    return _save(canvas, output)
