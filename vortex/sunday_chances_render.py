"""Render the two position panels on the original FPL VORTEX blue master."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PIL import ImageDraw

from .autonomous_render import _base, _save
from .autonomous_schedule import ET
from .comparison_board import WHITE, contain, font, text
from .editorial_inputs import RequiredInput
from .matchup import _media
from .sunday_chances import GROUP_ORDER, METRICS, MINUTES

METRIC_COLORS = ('#D5A0FF', '#FFCB67', '#59F3D4')
MUTED = '#B7C9E5'
CYAN = '#55DDF9'
VIOLET = '#BB91FF'
PANEL_WIDTH = 716


def _media_for(session, featured):
    def read(row):
        return (_media(session, row['photo'], 'photo', {}),
                _media(session, row['code'], 'crest', {}))

    with ThreadPoolExecutor(max_workers=4) as pool:
        art = dict(zip((row['player_id'] for row in featured), pool.map(read, featured)))
    if any(photo is None or crest is None for photo, crest in art.values()):
        raise RequiredInput('Official player headshot or club crest unavailable for Sunday Chance Watch')
    return art


def _name_lines(draw, rows, width):
    if not rows:
        return ['—']
    face = font(20)
    values = [row['name'] for row in rows]
    for visible in range(len(values), 0, -1):
        parts = values[:visible]
        if visible < len(values):
            parts.append(f'+{len(values) - visible} more')
        for pivot in range(len(parts), 0, -1):
            groups = (parts[:pivot], parts[pivot:])
            lines = ['  ·  '.join(group) for group in groups if group]
            if all(draw.textlength(line, font=face) <= width for line in lines):
                return lines
    return [f'{len(rows)} qualified players']


def _position(canvas, draw, x, label, rows, eligible, missing, art, accent):
    right = x + PANEL_WIDTH
    draw.rounded_rectangle((x, 105, right, 748), 22, fill='#0C1738',
                           outline=accent, width=2)
    text(draw, label, x + 22, 120, 420, 35, WHITE)
    text(draw, f'{len(rows)} / {eligible - missing} QUALIFY', x + 480, 135, 211, 17,
         accent, center=True)

    for index, row in enumerate(rows[:2]):
        left = x + 21 + index * 338
        draw.rounded_rectangle((left, 170, left + 325, 266), 14, fill='#172956',
                               outline='#3E5591', width=1)
        photo, crest = art[row['player_id']]
        contain(canvas, photo, (left + 3, 174, 77, 90), bottom=True, crop_alpha=True)
        contain(canvas, crest, (left + 278, 181, 35, 34))
        text(draw, row['name'], left + 82, 183, 188, 25, WHITE, minimum=14)
        for i, rate in enumerate(row['rates']):
            stat_x = left + 82 + 73 * i
            text(draw, METRICS[i][1], stat_x, 216, 72, 11, MUTED, minimum=9)
            text(draw, f'{rate:.2f}', stat_x, 232, 68, 20, METRIC_COLORS[i])

    for index, (_, name, threshold) in enumerate(METRICS):
        left = x + 18 + index * 104
        text(draw, f'{name} ≥ {threshold:g}', left, 280, 100, 14,
             METRIC_COLORS[index], minimum=10, center=True)
    text(draw, 'MATCHING PLAYERS', x + 356, 279, 334, 17, MUTED)

    for i, mask in enumerate(GROUP_ORDER):
        top = 307 + 60 * i
        group = [row for row in rows if row['mask'] == mask]
        draw.rounded_rectangle((x + 16, top, right - 16, top + 54), 8,
                               fill='#232453' if i == 0 else ('#132044' if i % 2 else '#101C3D'))
        for index, color in enumerate(METRIC_COLORS):
            center = x + 68 + 104 * index
            selected = mask & (1 << index)
            draw.ellipse((center - 8, top + 19, center + 8, top + 35),
                         fill=color if selected else '#26385E',
                         outline=color if selected else '#5C6F94', width=1)
        text(draw, str(len(group)), x + 309, top + 15, 34, 19, accent, center=True)
        lines = _name_lines(draw, group, 327)
        for j, line in enumerate(lines):
            text(draw, line, x + 356, top + (15 if len(lines) == 1 else 3) + 23 * j,
                 331, 20, WHITE if group else MUTED, minimum=13)


def render_sunday_chances(plan, output, session):
    data = plan.extra
    scope = (f"GW{plan.gw} WATCH  •  {data['season']}  •  THROUGH GW{data['through']}  •  "
             f"{MINUTES}+ SEASON MINUTES  •  PER 90")
    canvas = _base(plan.title, plan.gw, scope)
    draw = ImageDraw.Draw(canvas, 'RGBA')
    featured = [row for rows in data['rows'].values() for row in rows[:2]]
    art = _media_for(session, featured)
    for x, accent, (label, rows) in zip((39, 781), (CYAN, VIOLET), data['rows'].items()):
        _position(canvas, draw, x, label, rows, data['eligible'][label],
                  data['incomplete'][label], art, accent)

    missing = sum(data['incomplete'].values())
    retrieved = datetime.fromisoformat(data['retrieved_at'])
    rendered = datetime.now(ET)
    source = f'FPL CORE MATCH STATS + OFFICIAL FPL  •  DATA {retrieved:%d %b %H:%M %z}'
    if missing:
        source += f'  •  {missing} INCOMPLETE PLAYER RECORDS EXCLUDED'
    text(draw, f'{source}  •  RENDER {rendered:%d %b %H:%M %z}',
         31, 777, 1474, 15, MUTED, minimum=12, center=True)
    return _save(canvas, output)
