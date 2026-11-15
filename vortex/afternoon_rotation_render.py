"""Landscape positional cards and transfer fixture heatmaps."""
from PIL import ImageDraw

from .afternoon_rotation import POSITIONS
from .autonomous_render import _assets, _base, _save
from .comparison_board import CYAN, GOLD, WHITE, contain, text
from .minimal_theme import action_fill

FDR_FILL = {1: '#087a61', 2: '#17544c', 3: '#2d456b', 4: '#754a2d', 5: '#782644'}


def draw_value(canvas, plan, snapshot, client, cache):
    d = ImageDraw.Draw(canvas, 'RGBA')
    for pos, title in enumerate(POSITIONS, start=1):
        y = 112 + (pos - 1) * 171
        d.rounded_rectangle((26, y, 235, y + 151), 15, fill='#081b37', outline=CYAN, width=2)
        text(d, title, 39, y + 63, 183, 23, CYAN, center=True)
        group = [p for p in plan.players if p['element_type'] == pos]
        for i, p in enumerate(group):
            x = 249 + i * 252 + (5 - len(group)) * 126
            d.rounded_rectangle((x, y, x + 241, y + 151), 13, fill='#132d58', outline=CYAN, width=2)
            portrait, crest = _assets(snapshot, p, client, cache)
            contain(canvas, portrait, (x + 60, y + 7, 120, 104), bottom=True, crop_alpha=True)
            contain(canvas, crest, (x + 193, y + 52, 36, 36))
            forecast = plan.extra['values'][str(p['id'])]
            fdr = forecast['fdr']
            text(d, f"{forecast['xpts']:.2f}", x + 10, y + 9, 73, 28, WHITE)
            unit = 'xPTS' if forecast['points_source'] == 'MODEL xPTS' else 'FPL EP'
            text(d, unit, x + 10, y + 42, 64, 14, CYAN, minimum=12)
            d.rounded_rectangle((x + 163, y + 11, x + 230, y + 39), 6, fill=FDR_FILL[round(fdr)])
            text(d, f'FDR {fdr:.1f}', x + 166, y + 17, 62, 14, WHITE, minimum=10, center=True)
            fixtures = snapshot.fixtures_for_gameweek(p, plan.gw)
            opponents = ' / '.join(f'{opp} ({venue})' for opp, venue, _, _ in fixtures)
            d.rounded_rectangle((x + 3, y + 101, x + 238, y + 148), 9, fill='#081832')
            text(d, f'{snapshot.name(p)}  ·  {snapshot.price(p)}', x + 7, y + 104, 228, 20, WHITE, center=True)
            text(d, opponents, x + 7, y + 129, 228, 14, GOLD, minimum=11, center=True)
    text(d, 'FPL EP: OFFICIAL FPL FORECAST  ·  xPTS: VORTEX MODEL  ·  LOWER FDR MEANS EASIER',
         28, 781, 1480, 16, GOLD, center=True)


def draw_transfers(canvas, plan, snapshot, client, cache):
    d = ImageDraw.Draw(canvas, 'RGBA')
    weeks = plan.extra['weeks']
    columns = [
        ('PLAYER', 279), ('CLUB', 60), ('PRICE', 88), ('OWN %', 87), ('GW IN', 127), ('GW OUT', 127),
        *[(f'GW{week}', 110) for week in weeks], ('VERDICT', 139),
    ]
    groups = [(title, [p for p in plan.players if p['element_type'] == pos])
              for pos, title in enumerate(POSITIONS, start=1)]
    labels = {p['id']: label for p, label in zip(plan.players, plan.labels)}
    y = 108
    for title, group in groups:
        if not group:
            continue
        x = 40
        for index, (label, width) in enumerate(columns):
            d.rectangle((x, y, x + width - 2, y + 25), fill='#1f4373')
            text(d, title if index == 0 else label, x + 6, y + 5, width - 12, 16, CYAN, center=index > 0)
            x += width
        y += 28
        for p in group:
            row = plan.extra['rows'][str(p['id'])]
            label = labels[p['id']]
            portrait, crest = _assets(snapshot, p, client, cache)
            values = [snapshot.name(p), '', snapshot.price(p), p['selected_by_percent'],
                      f"{row['in']:,}", f"{row['out']:,}",
                      *[' / '.join(f'{opp}({venue})' for opp, venue, _, _ in week) or 'BLANK'
                        for week in row['fixtures']], label]
            x = 40
            for index, ((_, width), value) in enumerate(zip(columns, values)):
                fill = '#122542'
                if 6 <= index < 6 + len(weeks):
                    difficulty = [f[2] for f in row['fixtures'][index - 6] if f[2] is not None]
                    fill = FDR_FILL[max(difficulty)] if difficulty else '#293244'
                if index == len(columns) - 1:
                    fill = '#ff7188' if label == 'SELL' else action_fill(label)
                d.rounded_rectangle((x, y, x + width - 2, y + 32), 5, fill=fill)
                color = ('#61f7a6' if index == 4 else '#ffa3ad' if index == 5
                         else '#06132a' if index == len(columns) - 1 else WHITE)
                start = 40 if index == 0 else 4
                text(d, value, x + start, y + 8, width - start - 4, 17, color, minimum=11, center=index > 0)
                x += width
            contain(canvas, portrait, (44, y + 1, 31, 33), bottom=True, crop_alpha=True)
            contain(canvas, crest, (334, y + 3, 29, 29))
            y += 36
        y += 3
    text(d, 'OFFICIAL FPL TRANSFERS  ·  FDR 1–5  ·  DOUBLE GAMEWEEKS SHADED BY THE TOUGHER FIXTURE',
         28, 799, 1480, 16, GOLD, center=True)


def render_players(plan, snapshot, output, client):
    subtitle = f"GW{plan.gw}  /  " + ('NEXT GAMEWEEK FORECASTS & FIXTURE DIFFICULTY'
                                    if plan.kind == 'rotation_value' else 'LIVE FPL TRANSFERS & NEXT FIVE GAMEWEEKS')
    canvas = _base(plan.title, plan.gw, subtitle)
    draw_board = draw_value if plan.kind == 'rotation_value' else draw_transfers
    draw_board(canvas, plan, snapshot, client, {})
    return _save(canvas, output)
