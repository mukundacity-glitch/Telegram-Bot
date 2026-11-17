"""FPL VORTEX rank tables with original player rows and filled fixture tiles."""
from concurrent.futures import ThreadPoolExecutor

from PIL import ImageDraw

from .autonomous_render import _base, _save
from .comparison_board import CYAN, WHITE, contain, text
from .matchup import _media
from .publication_rules import FDR_COLORS
from .saturday_boards import POSITIONS

BONUS_COLORS = ('#19364C', '#4A3E91', '#6439BC', '#007392')
INK = '#081625'
TILE = 130
FIRST_TILE = 452


def fixture_line(draw, fixtures, y, first_tile):
    """Allow two discrete colored tiles in doubles and preserve blank weeks."""
    weeks = sorted({fixture['gw'] for fixture in fixtures})
    for column, week in enumerate(weeks):
        matches = [item for item in fixtures if item['gw'] == week]
        x = first_tile + column * (TILE + 8)
        for i, match in enumerate(matches):
            width = TILE / len(matches)
            left = x + i * width
            blank = match.get('blank')
            fdr = match.get('fdr')
            draw.rounded_rectangle((left, y + 7, left + width - 2, y + 49), radius=6,
                                   fill=FDR_COLORS[fdr] if not blank else '#52627A')
            label = 'BLANK' if blank else match['opponent']
            detail = '—' if blank else f"{match['venue']} · {fdr}"
            text(draw, label, left + 2, y + 10, width - 6, 15, INK if not blank else WHITE, 10, center=True)
            text(draw, detail, left + 2, y + 30, width - 6, 13, INK if not blank else WHITE, 9, center=True)


def render_saturday(plan, snapshot, output, session):
    bonus = plan.kind == 'saturday_bonus'
    weeks = plan.extra['weeks']
    scope = (f'AWARDED BONUS • GW1–GW{plan.gw} • 450+ MINUTES' if bonus else
             f"GW{plan.gw} OWNERSHIP • {plan.extra['sample']:,} SQUADS SAMPLED • NEXT 5 GAMEWEEKS")
    canvas = _base(plan.title.upper(), plan.gw, scope)
    d = ImageDraw.Draw(canvas, 'RGBA')
    assets = [(snapshot.photo_code(p), snapshot.team_code(p)) for p in plan.players]
    requests = {(kind, code) for photo, crest in assets for kind, code in (('photo', photo), ('crest', crest)) if code}
    cache = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        media = dict(zip(requests, pool.map(lambda key: _media(session, key[1], key[0], cache), requests)))

    x0 = FIRST_TILE if bonus else FIRST_TILE + 260
    track = 79 if bonus else TILE + 8
    text(d, 'PLAYER', 192, 102, 250, 19, CYAN, 14)
    if not bonus:
        text(d, 'OWNED', 452, 102, 142, 19, CYAN, 14, center=True)
    for column, week in enumerate(weeks):
        text(d, f'GW{week}', x0 + track * column, 102, track - 8, 19, CYAN, 14, center=True)
    if bonus:
        text(d, 'TOTAL', 1302, 102, 146, 19, CYAN, 14, center=True)

    for index, (player, row, (photo_code, crest_code)) in enumerate(zip(plan.players, plan.extra['rows'], assets)):
        y = 134 + index * 61
        d.rounded_rectangle((64, y, 1472, y + 56), radius=14,
                            fill='#141D3D' if index % 2 == 0 else '#101831', outline='#384168', width=1)
        d.rounded_rectangle((67, y + 9, 72, y + 47), radius=2, fill='#4DE0E6' if index < 3 else '#825ACD')
        text(d, f'{index + 1:02}', 79, y + 13, 40, 22, CYAN, 16, center=True)
        photo = media.get(('photo', photo_code))
        crest = media.get(('crest', crest_code))
        if photo:
            contain(canvas, photo, (122, y + 2, 52, 53), bottom=True, crop_alpha=True)
        if crest:
            size = 21 if photo else 42
            contain(canvas, crest, (174 if photo else 134, y + 32 if photo else y + 8, size, size))
        text(d, snapshot.name(player), 202, y + 4, 237, 28, WHITE, 17)
        price = snapshot.price(player)
        text(d, f"{snapshot.team(player)}  ·  {POSITIONS[player['element_type']]}  ·  {price}",
             202, y + 34, 237, 15, '#BFCAE2', 12)
        if bonus:
            for column, points in enumerate(row['timeline']):
                x = x0 + track * column
                fill = BONUS_COLORS[min(points, 3)] if points is not None else '#24283D'
                d.rounded_rectangle((x, y + 10, x + 69, y + 47), radius=6, fill=fill)
                text(d, '—' if points is None else str(points), x + 3, y + 15, 63, 21, WHITE, 15, center=True)
            text(d, str(row['total']), 1302, y + 9, 146, 29, CYAN, 20, center=True)
        else:
            pct = row['ownership']
            text(d, f'{pct:.1f}%', 452, y + 8, 142, 27, WHITE, 20, center=True)
            d.rounded_rectangle((480, y + 43, 566, y + 48), radius=2, fill='#343157')
            d.rounded_rectangle((480, y + 43, 480 + 86*pct/100, y + 48), radius=2, fill='#43D9EF')
            fixture_line(d, row['fixtures'], y, x0)

    if bonus:
        text(d, '— DID NOT PLAY   •   LATEST 10 GAMEWEEKS SHOWN   •   TIES BROKEN BY FPL POINTS',
             64, 752, 1408, 19, '#CFD9F5', 14, center=True)
    else:
        text(d, 'SQUAD OWNERSHIP   •   H HOME   A AWAY   •   FDR',
             212, 750, 640, 19, '#CFD9F5', 14)
        for i, (difficulty, color) in enumerate(FDR_COLORS.items()):
            x = 884 + i * 54
            d.rounded_rectangle((x, 748, x + 47, 774), radius=6, fill=color)
            text(d, str(difficulty), x + 2, 751, 43, 17, INK, 13, center=True)
    return _save(canvas, output)
