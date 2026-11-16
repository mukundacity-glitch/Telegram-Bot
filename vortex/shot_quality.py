"""Weekly Premier League chart of creation output and average shot quality."""
from math import isfinite

from .autonomous_schedule import ET, season_id
from .editorial_inputs import RequiredInput
from .fpl import latest_completed_gw
from .weekly_analysis import player_totals

TITLE = 'Assists per 90 vs xG per Shot'
MIN_MINUTES = 350
MIN_SHOTS = 10
FEATURED_COUNT = 8
POSITIONS = {2: 'DEF', 3: 'MID', 4: 'FWD'}


def build_shot_quality(slot, snapshot, now, session):
    from .autonomous_content import Plan

    gw, completed = snapshot.gameweek(), latest_completed_gw(snapshot)
    if not gw or completed is None:
        raise RequiredInput('Upcoming deadline or completed match data unavailable')
    year = int(season_id(snapshot, now).split('-')[0])
    players, sources = player_totals(snapshot, completed, session, year,
                                     ('assists', 'xg', 'total_shots'), require_shot_xg=True)
    rows = []
    total_minutes = total_shots = total_assists = total_xg = 0
    for player, stats in players:
        minutes, shots, xg = stats['minutes'], stats['total_shots'], stats['xg']
        if (minutes < MIN_MINUTES or shots < MIN_SHOTS or stats.get('incomplete_shot_xg')
                or player.get('element_type') not in POSITIONS or not 0 <= xg <= shots):
            continue
        assists_rate, shot_quality = stats['assists'] * 90 / minutes, xg / shots
        if not all(isfinite(n) for n in (assists_rate, shot_quality)):
            raise RequiredInput('Invalid player rates in verified match archive')
        total_minutes += minutes
        total_shots += shots
        total_assists += stats['assists']
        total_xg += xg
        rows.append({'position': POSITIONS[player['element_type']], 'name': snapshot.name(player), 'club': snapshot.teams[player['team']]['name'],
                     'photo': snapshot.photo_code(player), 'x': assists_rate, 'y': shot_quality,
                     'shots': int(shots)})
    if len(rows) < 5 or any(len({round(row[axis], 6) for row in rows}) < 2 for axis in ('x', 'y')):
        raise RequiredInput('Insufficient verified assists and shot quality for the Sunday chart')
    assists = max(rows, key=lambda row: (row['x'], row['shots']))
    quality = max(rows, key=lambda row: (row['y'], row['shots']))
    featured = [assists] if assists is quality else [assists, quality]
    ranked = sorted(rows, key=lambda row: (-(row['x'] / assists['x'] + row['y'] / quality['y']), row['name']))
    featured.extend(row for row in ranked if row is not assists and row is not quality)
    caption = '\n'.join((f'🎯 {TITLE}',
                         f"{assists['name']} leads on assists ({assists['x']:.2f}/90).",
                         f"{quality['name']} leads on shot quality ({quality['y']:.3f} xG/shot across {quality['shots']} shots).",
                         f'{len(rows)} Premier League players through GW{completed}. Who makes your GW{gw} shortlist?',
                         f'#FPL #GW{gw} #PremierLeague #FPLVORTEX'))
    return Plan(slot.task, slot.edition, TITLE, caption, gw, [], [], 'scouting_rotation', {
        'layout': 'scatter', 'rows': rows, 'featured': featured[:FEATURED_COUNT], 'through': completed,
        'minimum': MIN_MINUTES, 'percentiles': False, 'x_name': 'Assists', 'y_name': 'Expected goals',
        'units': ('PER 90', 'PER SHOT'),
        'benchmarks': (90 * total_assists / total_minutes, total_xg / total_shots),
        'subtitle': f'PREMIER LEAGUE  |  GW{completed}  |  {len(rows)} PLAYERS PLOTTED  |  350+ MIN  |  10+ SHOTS',
        'fetched_at': snapshot.fetched_at.astimezone(ET).isoformat(), 'sources': sources,
    })
