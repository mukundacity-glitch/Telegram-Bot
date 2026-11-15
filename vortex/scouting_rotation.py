"""Sunday-to-Saturday scouting board using verified Premier League metrics."""
from itertools import groupby

from .autonomous_schedule import ET, season_id
from .editorial_inputs import RequiredInput
from .fpl import latest_completed_gw
from .weekly_analysis import player_totals

DRIBBLES = ('Completed dribbles', ('successful_dribbles',))
BOX = ('Opposition-box touches', ('touches_opposition_box',))
PASSING = ('Final-third passes', ('final_third_passes',))
CHANCES = ('Chances created', ('chances_created',))
XA = ('Expected assists (xA)', ('xa',))
DEFENCE = ('Tackles + interceptions', ('tackles', 'interceptions'))
GOALS = ('Goals', ('goals',))
AERIALS = ('Aerial duels won', ('aerial_duels_won',))

FPL_CLUB_NAMES = {
    'Brighton': 'Brighton & Hove Albion',
    'Leeds': 'Leeds United',
    'Man City': 'Manchester City',
    'Man Utd': 'Manchester United',
    'Newcastle': 'Newcastle United',
    "Nott'm Forest": 'Nottingham Forest',
    'Spurs': 'Tottenham Hotspur',
    'West Ham': 'West Ham United',
    'Wolves': 'Wolverhampton Wanderers',
}

TOPICS = (
    ('Dribblers Who Reach the Box', DRIBBLES, BOX, (), 350, 'Who takes defenders on and gets into the box?'),
    ('Dribbling vs Final-Third Passing', DRIBBLES, PASSING, (), 350, 'Who beats a man and moves the ball into dangerous areas?'),
    ('Dribbling vs Expected Assists', DRIBBLES, XA, (), 350, 'Which dribblers are setting up the best chances?'),
    ('Dribbling vs Chance Creation', DRIBBLES, CHANCES, (), 350, 'Who turns one-on-ones into chances for teammates?'),
    ('Midfield Creation vs Defensive Work', XA, DEFENCE, (3,), 450, 'Which FPL midfielders create chances and win the ball back?'),
    ('Striker Profiles: Goals vs Aerial Wins', GOALS, AERIALS, (4,), 350, 'Who scores, who wins it in the air, and who does both?'),
)


def profile_rows(snapshot, through, year, session, x_metric, y_metric, positions, minimum, percentiles):
    fields = x_metric[1] + y_metric[1]
    players, sources = player_totals(snapshot, through, session, year, fields)
    rows = []
    for player, stats in players:
        minutes = stats['minutes']
        if minutes < minimum or player.get('element_type') not in (positions or (2, 3, 4)):
            continue
        gx = sum(stats[field] for field in x_metric[1]) * 90 / minutes
        gy = sum(stats[field] for field in y_metric[1]) * 90 / minutes
        rows.append({'name': snapshot.name(player), 'club': snapshot.teams[player['team']]['name'],
                     'photo': snapshot.photo_code(player), 'rates': (gx, gy), 'x': gx, 'y': gy})
    if len(rows) < 2:
        raise RequiredInput('Scouting chart needs at least two qualifying players with verified match stats')
    if percentiles:
        for axis in ('x', 'y'):
            total = 0
            for _, tied in groupby(sorted(rows, key=lambda r: r[axis]), key=lambda r: r[axis]):
                group = list(tied)
                for row in group:
                    row[axis] = (total + (len(group) - 1) / 2) * 100 / (len(rows) - 1)
                total += len(group)

    x_leader = max(rows, key=lambda r: (r['x'], r['y']))
    y_leader = max(rows, key=lambda r: (r['y'], r['x']))
    x_max = max(r['x'] for r in rows) or 1
    y_max = max(r['y'] for r in rows) or 1
    ranked = sorted(rows, key=lambda r: (-(r['x'] / x_max + r['y'] / y_max), r['name']))
    featured = [x_leader]
    if y_leader is not x_leader:
        featured.append(y_leader)
    featured.extend(r for r in ranked if r is not x_leader and r is not y_leader)
    return rows, featured[:5], sources


def goalkeeper_fixtures(snapshot, gw):
    weeks = sorted({event['id'] for event in snapshot.events if gw <= event['id'] < gw + 7})
    if not weeks:
        raise RequiredInput('No upcoming gameweeks for goalkeeper FDR')
    pool = sorted(
        (p for p in snapshot.players if p.get('element_type') == 1 and p.get('status') == 'a'
         and p.get('chance_of_playing_next_round') in (None, 100)
         and p.get('team') in snapshot.teams and snapshot.photo_code(p)
         and (p.get('starts') or 0) > 0),
        key=lambda p: (-(p.get('starts') or 0), -(p.get('total_points') or 0), p['id']),
    )
    by_week = {week: [f for f in snapshot.fixtures
                      if f.get('event') == week and not f.get('finished')] for week in weeks}
    if any(not fixtures for fixtures in by_week.values()):
        raise RequiredInput('Official fixture schedule is incomplete for the goalkeeper comparison')
    rows = []
    teams = set()
    for player in pool:
        club = player['team']
        if club in teams:
            continue
        cells = []
        for week in weeks:
            opponents = []
            for fixture in sorted(by_week[week], key=lambda f: (f.get('kickoff_time') or '', f['id'])):
                if club not in (fixture['team_h'], fixture['team_a']):
                    continue
                home = club == fixture['team_h']
                side, other = ('h', 'a') if home else ('a', 'h')
                name = snapshot.teams.get(fixture[f'team_{other}'], {}).get('name')
                fdr = fixture.get(f'team_{side}_difficulty')
                if not name or type(fdr) is not int or fdr not in range(1, 6):
                    raise RequiredInput('Official opponent name or fixture difficulty missing')
                opponents.append((FPL_CLUB_NAMES.get(name, name), 'H' if home else 'A', fdr))
            cells.append(opponents)
        if not any(cells):
            continue
        rows.append({'name': snapshot.name(player), 'club': snapshot.teams[club]['name'],
                     'photo': snapshot.photo_code(player), 'cells': cells})
        teams.add(club)
        if len(rows) == 4:
            break
    if len(rows) < 4:
        raise RequiredInput('Four available starting goalkeepers from different clubs required')
    return weeks, rows


def build_scouting(slot, snapshot, now, session):
    from .autonomous_content import Plan

    gw = snapshot.gameweek()
    if not gw:
        raise RequiredInput('No upcoming Fantasy Premier League gameweek')
    local = now.astimezone(ET)
    day = (local.weekday() + 1) % 7
    tags = f'#FPL #GW{gw} #PremierLeague #FPLVORTEX'
    extra = {'day': day + 1, 'edition_date': local.date().isoformat(),
             'fetched_at': snapshot.fetched_at.astimezone(ET).isoformat()}
    if day == 6:
        title = 'Goalkeeper Fixture Difficulty'
        weeks, rows = goalkeeper_fixtures(snapshot, gw)
        lines = (f'Which keeper has the best run? 🧤 | {title}',
                 f"{', '.join(r['name'] for r in rows)} compared side by side.",
                 f'Official FPL FDR for GW{weeks[0]}–{weeks[-1]}, with every opponent and venue.',
                 'Who gets your starting spot?',
                 tags)
        extra.update(layout='fixtures', weeks=weeks, rows=rows,
                     sources=['https://fantasy.premierleague.com/api/fixtures/'])
    else:
        title, x_metric, y_metric, positions, minimum, hook = TOPICS[day]
        through = latest_completed_gw(snapshot)
        if through is None:
            raise RequiredInput('No completed Premier League gameweek for the scouting chart')
        year = int(season_id(snapshot, now).split('-')[0])
        percentiles = day == 5
        rows, featured, sources = profile_rows(snapshot, through, year, session, x_metric, y_metric,
                                              positions, minimum, percentiles)
        x_name, y_name = x_metric[0], y_metric[0]
        x_leader, y_leader = (max(rows, key=lambda r: (r['x'], r['y'])),
                              max(rows, key=lambda r: (r['y'], r['x'])))
        compare = (f"{x_leader['name']} leads both metrics per 90." if x_leader is y_leader
                   else f"{x_name}: {x_leader['name']}. {y_name}: {y_leader['name']}.")
        lines = (f'{hook} | {title}', compare,
                 f'Premier League through GW{through} • Per 90 • {minimum}+ minutes.',
                 f'One free transfer. Who makes your GW{gw} shortlist?', tags)
        extra.update(layout='scatter', rows=rows, featured=featured, through=through, minimum=minimum,
                     x_name=x_name, y_name=y_name, percentiles=percentiles, sources=sources)
    return Plan(slot.task, slot.edition, title, '\n'.join(lines), gw, [], [],
                kind='scouting_rotation', extra=extra)
