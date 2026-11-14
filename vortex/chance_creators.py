"""Build the Chance Creators scatter plot from attributed Premier League shots."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from math import ceil
import unicodedata

from PIL import ImageDraw

from .autonomous_schedule import ET, season_id
from .comparison_board import CYAN, GOLD, WHITE, font, panel, text
from .editorial_inputs import RequiredInput

SOURCE = 'https://understat.com'
MINUTES = 220
SET_PIECES = {'FromCorner', 'SetPiece'}


def get_data(session, path):
    response = session.get(SOURCE + path, headers={'X-Requested-With': 'XMLHttpRequest'},
                           timeout=(8, 15))
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RequiredInput('Understat did not return structured match data') from exc


def match_chances(session, match):
    data = get_data(session, f"/getMatchData/{int(match['id'])}")
    counts = Counter()
    for side in ('h', 'a'):
        roster = {row['player']: str(row['player_id']) for row in data['rosters'][side].values()}
        if not roster:
            raise RequiredInput('Understat match roster is incomplete')
        for shot in data['shots'][side]:
            creator = shot['player_assisted']
            if not creator:
                continue
            situation = shot['situation']
            if situation in {'Penalty', 'DirectFreekick'}:
                continue  # Direct attempts have no creating pass.
            if situation != 'OpenPlay' and situation not in SET_PIECES:
                raise RequiredInput('Unrecognized Understat shot situation')
            if creator not in roster:
                raise RequiredInput('Understat shot creator could not be joined to the match roster')
            counts[roster[creator], situation == 'OpenPlay'] += 1
    return counts


def norm(value):
    return ''.join(ch for ch in unicodedata.normalize('NFKD', value).casefold() if ch.isalnum())


def build_chance_creators(slot, snapshot, now, session):
    from .autonomous_content import Plan

    gw = snapshot.gameweek()
    season = season_id(snapshot, now).split('-')[0]
    session.get(SOURCE, timeout=(8, 15)).raise_for_status()
    data = get_data(session, f'/getLeagueData/EPL/{season}')
    completed = [f for f in snapshot.fixtures if f.get('finished')]
    matches = [match for match in data['dates'] if match['isResult'] is True]
    official_dates = Counter(datetime.fromisoformat(f['kickoff_time']).date() for f in completed)
    provider_dates = Counter(date.fromisoformat(m['datetime'][:10]) for m in matches)
    if not matches or official_dates != provider_dates or len({m['id'] for m in matches}) != len(matches):
        raise RequiredInput('Understat match coverage does not match the completed FPL fixture dates')

    totals = Counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for counts in pool.map(lambda match: match_chances(session, match), matches):
            totals.update(counts)
    if not totals:
        raise RequiredInput('Understat returned no attributed chances')

    names = {norm(f"{p.get('first_name', '')} {p.get('second_name', '')}"): p
             for p in snapshot.players}
    rows = []
    for player in data['players']:
        minutes = int(player['time'])
        if minutes < MINUTES:
            continue
        name, pid = player['player_name'], str(player['id'])
        fpl = names.get(norm(name))
        rows.append({'id': pid, 'name': snapshot.name(fpl) if fpl else name,
                     'club': snapshot.team(fpl) if fpl else player['team_title'].split(',')[-1].strip(),
                     'open': totals[pid, True] * 90 / minutes,
                     'set': totals[pid, False] * 90 / minutes})
    if len(rows) < 10 or not any(row['set'] for row in rows) or not any(row['open'] for row in rows):
        raise RequiredInput('Understat has insufficient chance-creation coverage for this edition')

    rows.sort(key=lambda row: (row['open'] + row['set'], row['id']), reverse=True)
    leaders = [max(rows, key=lambda row: row[key]) for key in ('open', 'set')]
    featured = list(dict.fromkeys(row['id'] for row in leaders + rows
                                  if row['open'] or row['set']))[:9]
    title = 'CHANCE CREATORS'
    caption = (f'GW{gw} • {title}\n'
               f"Open play: {leaders[0]['name']} leads with {leaders[0]['open']:.2f} chances per 90.\n"
               f"Set pieces: {leaders[1]['name']} leads with {leaders[1]['set']:.2f} chances per 90.\n"
               f'MONITOR their minutes and roles before transferring. Understat • {MINUTES}+ league minutes.\n'
               f'#FPL #GW{gw} #FPLCommunity #FPLVORTEX')
    return Plan(slot.task, slot.edition, title, caption, gw, [], [], 'chance_creators',
                {'rows': rows, 'featured': featured, 'leaders': leaders, 'matches': len(matches),
                 'source': f'{SOURCE}/league/EPL/{season}', 'through': str(max(official_dates))})


def draw_chart(canvas, plan):
    draw = ImageDraw.Draw(canvas, 'RGBA')
    rows = plan.extra['rows']
    by_id = {row['id']: row for row in rows}
    ranks = {pid: i for i, pid in enumerate(plan.extra['featured'], 1)}
    panel(draw, (38, 104, 1046, 790), CYAN)
    panel(draw, (1062, 104, 1498, 790), GOLD)
    text(draw, 'SET-PIECE CHANCES / 90', 64, 122, 920, 24, CYAN)
    x0, y0, x1, y1 = 122, 696, 1006, 187
    x_max, y_max = [max(.5, ceil(max(r[key] for r in rows) * 2 + .1) / 2)
                    for key in ('open', 'set')]
    for tick in range(6):
        i = tick / 5
        x, y = x0 + (x1 - x0) * i, y0 + (y1 - y0) * i
        draw.line((x, y0, x, y1), fill='#304663')
        draw.line((x0, y, x1, y), fill='#304663')
        text(draw, f'{x_max*i:.1f}', x-24, y0+12, 48, 19, WHITE, center=True)
        text(draw, f'{y_max*i:.1f}', 62, y-10, 52, 19, WHITE, center=True)
    text(draw, 'OPEN-PLAY CHANCES / 90', 124, 746, 878, 25, CYAN, center=True)

    def point(row):
        return (x0 + (x1 - x0) * row['open'] / x_max,
                y0 + (y1 - y0) * row['set'] / y_max)

    for row in rows:
        x, y = point(row)
        draw.ellipse((x-4, y-4, x+4, y+4), fill='#6E87A2')
    labels = []
    for pid, rank in ranks.items():
        x, y = point(by_id[pid])
        bx, by = next(((x+dx, y+dy) for dx, dy in
                       ((16,-15), (-16,-15), (16,15), (-16,15), (0,-31), (0,31), (31,0), (-31,0))
                       if x0+12 <= x+dx <= x1+20 and y1-20 <= y+dy <= y0-12
                       and all((x+dx-px)**2 + (y+dy-py)**2 >= 26**2 for px,py in labels)),
                      (max(x0+12, x+22), min(y0-12, y-22)))
        labels.append((bx, by))
        draw.line((x,y,bx,by), fill=GOLD, width=2)
        draw.ellipse((x-5,y-5,x+5,y+5), fill=GOLD)
        draw.ellipse((bx-11,by-11,bx+11,by+11), fill='#10203A', outline=GOLD, width=2)
        draw.text((bx,by), str(rank), font=font(13), fill=WHITE, anchor='mm')

    text(draw, 'FEATURED CREATORS', 1081, 126, 400, 27, GOLD)
    text(draw, 'PLAYER', 1120, 176, 190, 19, CYAN)
    text(draw, 'OPEN', 1340, 176, 65, 19, CYAN, center=True)
    text(draw, 'SET', 1413, 176, 65, 19, CYAN, center=True)
    for pid, rank in ranks.items():
        row = by_id[pid]
        y = 207 + (rank-1)*49
        draw.line((1080,y+39,1479,y+39), fill='#304663')
        text(draw, str(rank), 1083, y, 27, 19, GOLD, center=True)
        text(draw, f"{row['name']}  ·  {row['club']}", 1120, y, 213, 19, WHITE, 12)
        text(draw, f"{row['open']:.2f}", 1340, y, 65, 19, WHITE, center=True)
        text(draw, f"{row['set']:.2f}", 1413, y, 65, 19, WHITE, center=True)
    text(draw, f'UNDERSTAT • SEASON TO DATE • {MINUTES}+ MIN', 1081, 680, 398, 19, CYAN)
    text(draw, f"{len(rows)} players • {plan.extra['matches']} matches", 1081, 713, 398, 20, WHITE)
    text(draw, f"Completed matches through {plan.extra['through']}", 1081, 745, 398, 19, WHITE)
