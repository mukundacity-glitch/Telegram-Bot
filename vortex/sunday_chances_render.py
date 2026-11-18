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
        raise RequiredInput('Official player headshot or club crest unavailable for the evening graphic')
    return art


def _name_lines(draw, rows, width, size):
    if not rows:
        return ['—']
    face = font(size)
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


def _position(canvas, draw, x, label, rows, eligible, missing, art, accent, metrics, *, large):
    right = x + PANEL_WIDTH
    draw.rounded_rectangle((x, 105, right, 748), 22, fill='#0C1738',
                           outline=accent, width=2)
    text(draw, label, x + 22, 116 if large else 120, 420, 42 if large else 35, WHITE)
    text(draw, f'{len(rows)} / {eligible - missing} QUALIFY', x + 480, 135, 211, 22 if large else 17,
         accent, center=True)

    for index, row in enumerate(rows[:2]):
        left = x + 21 + index * 338
        draw.rounded_rectangle((left, 170, left + 325, 266), 14, fill='#172956',
                               outline='#3E5591', width=1)
        photo, crest = art[row['player_id']]
        contain(canvas, photo, (left + 3, 174, 77, 90), bottom=True, crop_alpha=True)
        contain(canvas, crest, (left + 278, 181, 35, 34))
        text(draw, row['name'], left + 82, 183, 188, 31 if large else 25, WHITE, minimum=20 if large else 14)
        for i, rate in enumerate(row['rates']):
            stat_x = left + 82 + 73 * i
            text(draw, metrics[i][1], stat_x, 216, 72, 13 if large else 11, MUTED, minimum=9)
            text(draw, f'{rate:.2f}', stat_x, 232, 68, 26 if large else 20, METRIC_COLORS[i])

    name_x = 327 if large else 356
    name_width = right - (x + name_x) - 22
    name_size = 25 if large else 20
    metric_width = 94 if large else 104
    for index, (_, name, threshold) in enumerate(metrics):
        left = x + 18 + index * metric_width
        color = METRIC_COLORS[index]
        if large:
            text(draw, name, left, 271, metric_width - 4, 13, color, minimum=10, center=True)
            text(draw, f'≥ {threshold:g}', left, 286, metric_width - 4, 15, color, minimum=12, center=True)
        else:
            text(draw, f'{name} ≥ {threshold:g}', left, 280, metric_width - 4, 14,
                 color, minimum=10, center=True)
    text(draw, 'MATCHING PLAYERS', x + name_x, 279, name_width, 19 if large else 17, MUTED)

    for i, mask in enumerate(GROUP_ORDER):
        top = 307 + 60 * i
        group = [row for row in rows if row['mask'] == mask]
        draw.rounded_rectangle((x + 16, top, right - 16, top + 54), 8,
                               fill='#232453' if i == 0 else ('#132044' if i % 2 else '#101C3D'))
        for index, color in enumerate(METRIC_COLORS):
            center = x + (63 if large else 68) + metric_width * index
            selected = mask & (1 << index)
            draw.ellipse((center - 8, top + 19, center + 8, top + 35),
                         fill=color if selected else '#26385E',
                         outline=color if selected else '#5C6F94', width=1)
        text(draw, str(len(group)), x + (285 if large else 309), top + 13, 34, 23 if large else 19, accent, center=True)
        lines = _name_lines(draw, group, name_width - 4, name_size)
        first_line = top + ((11 if large else 15) if len(lines) == 1 else (1 if large else 3))
        line_height = 25 if large else 23
        for j, line in enumerate(lines):
            text(draw, line, x + name_x, first_line + line_height * j,
                 name_width, name_size, WHITE if group else MUTED, minimum=18 if large else 13)


def render_sunday_chances(plan, output, session):
    data = plan.extra
    scope = (f"GW{plan.gw} WATCH  •  {data['season']}  •  THROUGH GW{data['through']}  •  "
             f"{MINUTES}+ SEASON MINUTES  •  PER 90")
    canvas = _base(plan.title, plan.gw, scope)
    draw = ImageDraw.Draw(canvas, 'RGBA')
    featured = [row for rows in data['rows'].values() for row in rows[:2]]
    art = _media_for(session, featured)
    metrics = data.get('metrics', {})
    for x, accent, (label, rows) in zip((39, 781), (CYAN, VIOLET), data['rows'].items()):
        _position(canvas, draw, x, label, rows, data['eligible'][label],
                  data['incomplete'][label], art, accent, metrics.get(label, METRICS), large=bool(metrics))

    missing = sum(data['incomplete'].values())
    retrieved = datetime.fromisoformat(data['retrieved_at'])
    rendered = datetime.now(ET)
    source = f'FPL CORE MATCH STATS + OFFICIAL FPL  •  DATA {retrieved:%d %b %H:%M %z}'
    if missing:
        source += f'  •  {missing} INCOMPLETE PLAYER RECORDS EXCLUDED'
    text(draw, f'{source}  •  RENDER {rendered:%d %b %H:%M %z}',
         31, 777, 1474, 15, MUTED, minimum=12, center=True)
    return _save(canvas, output)
