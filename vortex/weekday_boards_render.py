"""Reference-led evening boards with the approved VORTEX branding."""
from datetime import datetime

from PIL import ImageDraw

from .autonomous_render import _base, _save
from .autonomous_schedule import ET
from .comparison_board import CYAN, GOLD, WHITE, contain, text
from .editorial_inputs import RequiredInput
from .matchup import _media
from .weekday_boards import SET_PIECES

MUTED = '#B9CDE9'
INK = '#101D3B'
PANEL = '#15284D'


def _crest(canvas, session, cache, code, box):
    crest = _media(session, code, 'crest', cache)
    if crest is None:
        raise RequiredInput(f'Official club crest unavailable: {code}')
    contain(canvas, crest, box)


def _source(draw, plan, source, y=774):
    data = datetime.fromisoformat(plan.extra['data_at'])
    rendered = datetime.now(ET)
    text(draw, f'{source}  •  DATA {data:%d %b %H:%M %z}  •  RENDER {rendered:%d %b %H:%M %z}',
         40, y, 1456, 15, MUTED, minimum=12, center=True)


def _set_pieces(plan, output, session):
    canvas = _base(plan.title, plan.gw, f'GW{plan.gw}  •  OFFICIAL FPL ROLE ORDER  •  270+ SEASON MINUTES')
    draw = ImageDraw.Draw(canvas, 'RGBA')
    headers = (('PLAYER', 116, 385), ('CLUB', 518, 165), ('MIN', 699, 132),
               ('CORNERS / IFK', 846, 218), ('DIRECT FK', 1080, 190), ('PENALTIES', 1284, 190))
    draw.rounded_rectangle((40, 108, 1496, 151), 11, fill='#233762')
    for label, x, width in headers:
        text(draw, label, x, 117, width, 20, CYAN, center=x > 400)
    cache = {}
    for rank, row in enumerate(plan.extra['rows'], 1):
        y = 158 + (rank - 1) * 56
        draw.rounded_rectangle((40, y, 1496, y + 51), 9, fill=PANEL if rank % 2 else INK)
        text(draw, str(rank), 54, y + 12, 48, 22, GOLD, center=True)
        text(draw, row['name'], 115, y + 7, 385, 30, WHITE, minimum=18)
        _crest(canvas, session, cache, row['code'], (515, y + 5, 42, 40))
        text(draw, row['club'], 573, y + 11, 105, 25, WHITE)
        text(draw, str(row['minutes']), 699, y + 9, 132, 28, WHITE, center=True)
        for (_, x, width), role in zip(headers[-3:], row['roles']):
            color = GOLD if role == 1 else CYAN if role else MUTED
            text(draw, f'#{role}' if role else '—', x, y + 8, width, 30, color, center=True)
    text(draw, 'IFK = INDIRECT FREE KICKS    •    #1 = FIRST IN THE LISTED ORDER    •    — = NO LISTED ROLE',
         40, 730, 1456, 19, MUTED, minimum=15, center=True)
    _source(draw, plan, 'OFFICIAL FPL SET-PIECE ORDERS')
    return _save(canvas, output)


def render_weekday_board(plan, output, session):
    if plan.edition == SET_PIECES:
        return _set_pieces(plan, output, session)
    raise RequiredInput(f'Unknown weekday graphic: {plan.edition}')
