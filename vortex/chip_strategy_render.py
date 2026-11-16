"""Render the four chip recommendations, usage and five-gameweek matrix."""
from PIL import ImageDraw

from .autonomous_render import _base, _save
from .chip_strategy import CHIPS
from .comparison_board import CYAN, GOLD, WHITE, contain, paragraph, text
from .matchup import _media

ACCENTS = ('#7DE8C4', '#D9B4FE', '#7EDDFA', '#FFE195')
PANEL = '#132541'
DARK = '#0C1930'
MUTED = '#B9CBE0'


def render_chip_strategy(plan, snapshot, output, client):
    data = plan.extra
    canvas = _base(plan.title, plan.gw, f"{data['span']}  •  {data['data_date']}  •  FIVE-GAMEWEEK OUTLOOK")
    draw = ImageDraw.Draw(canvas, 'RGBA')
    tc = data['cards']['3xc']['pick']
    featured = next((p for p in snapshot.players if tc and p.get('id') == tc['player_id']), None)
    if featured:
        try:
            portrait = _media(client, snapshot.photo_code(featured), 'photo', {})
        except OSError:
            portrait = None
    else:
        portrait = None
    for i, ((chip, name), color) in enumerate(zip(CHIPS.items(), ACCENTS)):
        x = 30 + 371 * i
        card = data['cards'][chip]
        pick, peak = card['pick'], card['peak']
        draw.rounded_rectangle((x, 110, x+362, 430), radius=16, fill=PANEL, outline=color, width=2)
        draw.rounded_rectangle((x+2, 112, x+360, 163), radius=14, fill='#302454')
        text(draw, name.upper(), x+14, 124, 334, 25, color, center=True)
        usage = card['usage']
        usage_label = f'{usage:.1f}% of entries used' if usage is not None else 'Usage pending official counts'
        text(draw, usage_label, x+14, 179, 334, 22, WHITE, 17, center=True)
        count_scope = f"Through GW{card['through']}  •  Set ends GW{card['expires']}" if card['through'] else f"Set ends GW{card['expires']}"
        text(draw, count_scope, x+14, 211, 334, 16, MUTED, center=True)
        draw.rounded_rectangle((x+13, 244, x+349, 298), radius=10, fill='#685321' if pick and pick['conditional'] else '#185145' if pick else DARK)
        call = f"GW{pick['gw']}  {pick['xpts']:+.1f} xPts" if pick else 'HOLD THIS CHIP'
        text(draw, call, x+18, 252, 326, 32, WHITE, 20, center=True)
        details = pick['detail'] if pick else 'Wait for a stronger or open gameweek within this chip set.'
        show_portrait = chip == '3xc' and portrait is not None
        if show_portrait:
            contain(canvas, portrait, (x+273, 307, 75, 71), bottom=True, crop_alpha=True)
        paragraph(draw, details, (x+16, 311, 253 if show_portrait else 331), 18, WHITE, lines=3)
        if peak and (not pick or peak['gw'] != pick['gw']):
            note = f"Standalone peak  GW{peak['gw']}  {peak['xpts']:+.1f}"
        else:
            note = {'bboost': 'Gross bench xPts before auto-subs', 'wildcard': 'Gain from use until horizon ends',
                    'freehit': 'One-week gain vs reference XI', '3xc': 'Extra xPts above normal captaincy'}[chip]
        text(draw, note, x+16, 399, 330, 17, color, 14)

    weeks = data['weeks']
    cell = 1182 / len(weeks)
    draw.rounded_rectangle((30, 448, 1506, 686), radius=12, fill=DARK, outline='#416380', width=2)
    text(draw, 'CHIP UPLIFT (xPts)', 48, 461, 258, 20, GOLD)
    for col, gw in enumerate(weeks):
        text(draw, f'GW{gw}', 312+col*cell, 460, cell-8, 22, GOLD, center=True)
    for i, ((chip, name), color) in enumerate(zip(CHIPS.items(), ACCENTS)):
        y = 495 + i*45
        text(draw, name, 48, y+8, 250, 20, color)
        pick = data['cards'][chip]['pick']
        for j, row in enumerate(data['rows'][chip]):
            x = 312+j*cell
            highlight = bool(pick and row['gw'] == pick['gw'])
            draw.rounded_rectangle((x, y, x+cell-7, y+39), radius=6,
                                   fill=('#685321' if row['conditional'] else '#1C6350') if highlight else PANEL)
            value = f"{row['xpts']:+.1f}" if row['xpts'] is not None else 'Ineligible'
            if row['xpts'] is not None and row['gw'] > data['cards'][chip]['expires']:
                value += '  •  New set'
            text(draw, value, x+5, y+6, cell-17, 22, WHITE if highlight else MUTED, 14, center=True)

    draw.rounded_rectangle((30, 697, 1506, 758), radius=12, fill=PANEL, outline='#416380', width=2)
    text(draw, 'FIXTURE TARGETS', 48, 703, 240, 19, GOLD)
    text(draw, 'TOP THREE PLAYER xPts', 48, 728, 240, 14, MUTED)
    if not data['targets']:
        text(draw, 'No qualifying fixtures against Crystal Palace, Coventry City or Ipswich Town this window.',
             310, 715, 1155, 20, WHITE)
    for i, row in enumerate(data['targets']):
        x = 299 + 399*i
        text(draw, f"GW{row['gw']}  {row['club']} v {row['opponent']}", x, 703, 390, 18, WHITE, 13)
        text(draw, f"{row['total']:.1f} combined xPts  •  {'HOME' if row['venue'] == 'H' else 'AWAY'}",
             x, 727, 390, 16, CYAN, 13)
    text(draw, f"{data['forecast']}  •  £100m OWNERSHIP XI + BENCH  •  UP TO 1 FREE MOVE PER GW",
         45, 764, 1445, 16, WHITE, 13, center=True)
    text(draw, 'ONE CHIP PER GW  •  FREE HIT CANNOT BE USED IN CONSECUTIVE GWs  •  SCENARIOS ARE SEPARATE',
         45, 783, 1445, 15, MUTED, 13, center=True)
    return _save(canvas, output)
