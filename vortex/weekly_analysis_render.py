"""FPL VORTEX weekly graphics with consistent title, canvas and footer."""

from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw, ImageOps

from .comparison_board import CYAN, GOLD, WHITE, contain, text
from .matchup import _media
from .minimal_theme import social_footer
from .team_points_render import render_team_points
from .vortex_style import LION, gradient

PANEL = '#172340'
MUTED = '#c1cde6'
RULE = '#39547e'


def render_weekly_analysis(plan, output, session):
    if plan.extra['day'] == 1:
        return render_team_points(plan, output, session)
    canvas = gradient((1080, 1920), (22, 13, 49), (8, 13, 31))
    draw = ImageDraw.Draw(canvas)
    rows = plan.extra['rows']
    layout = plan.extra['layout']
    with Image.open(LION.parent / 'midfield-watch-logo.png') as logo:
        brand = ImageOps.contain(logo.convert('RGB'), (500, 170), Image.Resampling.LANCZOS)
        draw.rounded_rectangle((267, 19, 813, 192), 24, fill='#000000', outline='#76553a', width=2)
        canvas.paste(brand, ((1080-brand.width)//2, 21))
    text(draw, plan.title, 24, 211, 1032, 52, WHITE, center=True)
    text(draw, f"WEEKLY ANALYSIS {plan.extra['day']}/7  •  THROUGH GW{plan.extra['through']}",
         38, 279, 1004, 25, GOLD, center=True)

    codes = [] if layout == 'scatter' else sorted({r['code'] for r in rows if r.get('code')})
    with ThreadPoolExecutor(max_workers=8) as pool:
        crests = dict(zip(codes, pool.map(lambda code: _media(session, code, 'crest', {}), codes)))

    def crest(row, x, y, size):
        badge = crests.get(row.get('code'))
        if badge is not None:
            contain(canvas, badge, (x, y, size, size))

    if layout == 'pitch':
        draw.rounded_rectangle((40, 354, 1040, 1548), 24, fill='#104135', outline='#65bc9a', width=3)
        draw.rectangle((78, 390, 1002, 1510), outline='#83bf9e', width=3)
        draw.line((78, 950, 1002, 950), fill='#83bf9e', width=3)
        draw.ellipse((416, 826, 664, 1074), outline='#83bf9e', width=3)
        for position, y in ((1, 444), (2, 690), (3, 966), (4, 1259)):
            group = [row for row in rows if row['position'] == position]
            for index, row in enumerate(group):
                center = 78 + (index+.5) * 924/len(group)
                crest(row, round(center-45), y, 90)
                text(draw, row['name'], center-91, y+98, 182, 27, WHITE, 14, center=True)
                draw.rounded_rectangle((center-55, y+138, center+55, y+181), 12, fill='#142540')
                text(draw, f"{row['value']:.0f}", center-50, y+142, 100, 28, GOLD, center=True)
    elif layout == 'fixtures':
        cell_w = 171
        for index, gw in enumerate(plan.extra['weeks']):
            text(draw, f'GW{gw}', 328+index*cell_w, 384, cell_w-8, 28, CYAN, center=True)
        for index, row in enumerate(rows):
            y = 448+index*191
            draw.rounded_rectangle((38, y, 1042, y+164), 18, fill=PANEL, outline=RULE, width=2)
            crest(row, 56, y+45, 70)
            text(draw, row['name'], 138, y+41, 172, 26, WHITE, 15)
            text(draw, f"AVG FDR {row['value']:.2f}", 138, y+91, 172, 21, GOLD)
            for j, cell in enumerate(row['cells']):
                x = 328+j*cell_w
                draw.rounded_rectangle((x, y+42, x+cell_w-8, y+122), 12, fill='#29345b')
                lines = cell.split(' / ')
                for k, line in enumerate(lines):
                    text(draw, line, x+4, y+69-(len(lines)-1)*13+k*25, cell_w-16, 24, WHITE, 14, center=True)
    elif layout == 'scatter':
        left, right, top, bottom = 130, 989, 458, 1392
        draw.rounded_rectangle((left, top, right, bottom), 12, fill=PANEL, outline=RULE, width=2)
        for pct in range(0, 101, 20):
            x = left+(right-left)*pct/100
            y = bottom-(bottom-top)*pct/100
            draw.line((x, top, x, bottom), fill=RULE)
            draw.line((left, y, right, y), fill=RULE)
            text(draw, str(pct), x-24, bottom+13, 48, 19, MUTED, center=True)
            text(draw, str(pct), 64, y-12, 54, 19, MUTED, center=True)
        middle_x, middle_y = (left+right)//2, (top+bottom)//2
        draw.line((middle_x, top, middle_x, bottom), fill='#60719b', width=2)
        draw.line((left, middle_y, right, middle_y), fill='#60719b', width=2)
        text(draw, 'BOX TOUCHES PERCENTILE ↑', 130, 399, 859, 25, GOLD)
        text(draw, 'BALL WINNING PERCENTILE →', 130, 1445, 859, 26, CYAN, center=True)
        labels = []
        for row in reversed(rows):
            x = left+(right-left)*row['x']/100
            y = bottom-(bottom-top)*row['y']/100
            high = row in rows[:8]
            color = GOLD if high else '#6c8cac'
            draw.ellipse((x-6, y-6, x+6, y+6), fill=color)
            if high:
                labels.append((x, y, row))
        for index, (x, y, row) in enumerate(reversed(labels), 1):
            draw.ellipse((x-12, y-12, x+12, y+12), fill='#263558', outline=GOLD)
            text(draw, str(index), x-11, y-9, 22, 15, WHITE, center=True)
            px = 56+(index-1)%4*243
            py = 1502+(index-1)//4*49
            text(draw, f"{index}  {row['name']}", px, py, 232, 20, WHITE, 12)
    else:
        leader = rows[0]
        if plan.extra['day'] == 4 and leader.get('photo'):
            portrait = _media(session, leader['photo'], 'photo', {})
            if portrait is not None:
                contain(canvas, portrait, (788, 340, 218, 209), bottom=True, crop_alpha=True)
        text(draw, plan.extra['unit'].upper(), 56, 366, 642, 30, CYAN)
        text(draw, leader['name'], 56, 420, 708, 48, WHITE)
        if plan.extra['day'] == 3:
            rate = plan.extra['rate_leader']
            text(draw, f"PER 90 LEADER  •  {rate['name']}  {rate['rate']:.2f}", 56, 484, 840, 25, GOLD)
        upper = max(1, *(row['value'] for row in rows))
        for index, row in enumerate(rows, 1):
            y = 560+(index-1)*81
            draw.rounded_rectangle((40, y, 1040, y+72), 14, fill=PANEL)
            text(draw, str(index), 49, y+15, 43, 22, GOLD, center=True)
            crest(row, 99, y+10, 48)
            text(draw, row['name'], 163, y+8, 430, 27, WHITE)
            text(draw, row['detail'], 163, y+42, 480, 19, MUTED, 13)
            draw.rounded_rectangle((658, y+32, 893, y+43), 5, fill=RULE)
            length = row['value']/upper * 235
            if length >= 1:
                draw.rounded_rectangle((658, y+32, 658+length, y+43), 5, fill=CYAN if index > 3 else GOLD)
            value = f"{row['value']:.2f}" if plan.extra['day'] == 6 else f"{row['value']:.0f}"
            text(draw, value, 906, y+16, 110, 27, WHITE, center=True)
    text(draw, plan.extra['note'], 36, 1643, 1008, 22, CYAN, 14, center=True)
    text(draw, 'FPL VORTEX  •  CHECK MINUTES & FIXTURES BEFORE TRANSFERRING',
         34, 1723, 1012, 23, GOLD, center=True)
    social_footer(canvas)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, 'PNG', optimize=True)
    return output
