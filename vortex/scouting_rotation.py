"""Sunday-to-Saturday scouting board using verified Premier League metrics."""
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby

from .autonomous_schedule import ET, season_id
from .editorial_inputs import RequiredInput
from .fpl import latest_completed_gw
from .recommendations import completed_rounds, get_history
from .weekly_analysis import player_totals

DRIBBLES = ('Completed dribbles', ('successful_dribbles',))
BOX = ('Opposition-box touches', ('touches_opposition_box',))
PASSING = ('Final-third passes', ('final_third_passes',))
CHANCES = ('Chances created', ('chances_created',))
XA = ('Expected assists (xA)', ('xa',))
DEFENCE = ('Tackles won + interceptions', ('tackles_won', 'interceptions'))
SHOTS = ('Shots', ('total_shots',))
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
    ('Completed Dribbles vs Opposition-Box Touches', DRIBBLES, BOX, (), 350, 'Who takes defenders on and gets into the box?'),
    ('Dribbling vs Final-Third Passing', DRIBBLES, PASSING, (), 350, 'Who beats a man and moves the ball into dangerous areas?'),
    ('Dribbling vs Expected Assists', DRIBBLES, XA, (), 350, 'Which dribblers are setting up the best chances?'),
    ('Dribbling vs Chance Creation', DRIBBLES, CHANCES, (), 350, 'Who turns one-on-ones into chances for teammates?'),
    ('Midfield Creation vs Defensive Work', XA, DEFENCE, (3,), 450, 'Which FPL midfielders create chances and win the ball back?'),
    ('Striker Profiles: Goals vs Aerial Wins', GOALS, AERIALS, (4,), 350, 'Who scores, who wins it in the air, and who does both?'),
)


# Some archived seasons omit dribbles for every player. These replacement
# editions use real metrics and change their titles, axes and captions together.
DRIBBLE_FALLBACKS = (
    ('Final-Third Passes vs Opposition-Box Touches', PASSING, BOX, 'Who links the final third with the penalty area?'),
    ('Shots vs Final-Third Passing', SHOTS, PASSING, 'Who combines shot volume with final-third involvement?'),
    ('Box Touches vs Expected Assists', BOX, XA, 'Who gets into the box and creates chances for teammates?'),
    ('Shots vs Chances Created', SHOTS, CHANCES, 'Who brings both shot volume and chance creation?'),
)


def profile_rows(players, snapshot, x_metric, y_metric, positions, minimum, percentiles, *, feature_limit=5):
    rows = []
    for player, stats in players:
        minutes = stats['minutes']
        if minutes < minimum or player.get('element_type') not in (positions or (2, 3, 4)):
            continue
        gx = sum(stats.get(field, 0) for field in x_metric[1]) * 90 / minutes
        gy = sum(stats.get(field, 0) for field in y_metric[1]) * 90 / minutes
        rows.append({'name': snapshot.name(player), 'club': snapshot.teams[player['team']]['name'],
                     'photo': snapshot.photo_code(player), 'rates': (gx, gy), 'x': gx, 'y': gy})
        if feature_limit > 5:
            rows[-1]['player_id'] = player['id']
    if len(rows) < 2 or any(len({round(r[axis], 6) for r in rows}) < 2 for axis in ('x', 'y')):
        return [], []
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
    return rows, featured[:feature_limit]


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
        fallback = DRIBBLE_FALLBACKS[day] if day < len(DRIBBLE_FALLBACKS) else None
        fields = x_metric[1] + y_metric[1]
        if fallback:
            fields = tuple(dict.fromkeys(fields + fallback[1][1] + fallback[2][1]))
        players, sources = player_totals(snapshot, through, session, year, fields,
                                         optional_fields=DRIBBLES[1] if fallback else ())
        rows, featured = profile_rows(players, snapshot, x_metric, y_metric, positions, minimum, percentiles)
        used_fallback = not rows and fallback is not None
        if used_fallback:
            title, x_metric, y_metric, hook = fallback
            rows, featured = profile_rows(players, snapshot, x_metric, y_metric, positions, minimum, percentiles)
        if not rows:
            raise RequiredInput('Scouting chart axes lack verified variation across qualifying players')
        x_name, y_name = x_metric[0], y_metric[0]
        x_leader, y_leader = (max(rows, key=lambda r: (r['x'], r['y'])),
                              max(rows, key=lambda r: (r['y'], r['x'])))
        compare = (f"{x_leader['name']} leads both metrics per 90." if x_leader is y_leader
                   else f"{x_name}: {x_leader['name']}. {y_name}: {y_leader['name']}.")
        lines = (f'{hook} | {title}', compare,
                 f'Premier League through GW{through} • Per 90 • {minimum}+ minutes.',
                 f'One free transfer. Who makes your GW{gw} shortlist?', tags)
        extra.update(layout='scatter', rows=rows, featured=featured, through=through, minimum=minimum,
                     x_name=x_name, y_name=y_name, percentiles=percentiles, sources=sources,
                     metric_note='Dribble counts unavailable in the match archive' if used_fallback else '')
    return Plan(slot.task, slot.edition, title, '\n'.join(lines), gw, [], [],
                kind='scouting_rotation', extra=extra)


def build_passing_creators(slot, snapshot, now, session):
    """Compare completed passes with passes leading directly to a shot."""
    from .autonomous_content import Plan

    gw = snapshot.gameweek()
    through = latest_completed_gw(snapshot)
    if not gw or through is None:
        raise RequiredInput('No verified gameweek for the passing and creation chart')

    year = int(season_id(snapshot, now).split('-')[0])
    passing = ('Completed passes', ('accurate_passes',))
    fields = passing[1] + CHANCES[1]
    players, sources = player_totals(snapshot, through, session, year, fields,
                                     optional_fields=fields)
    verified = [(player, stats) for player, stats in players
                if all(field in stats for field in fields)]
    minimum = 450
    rows, ranked = profile_rows(verified, snapshot, passing, CHANCES, (), minimum, False,
                                feature_limit=10)
    if not rows:
        raise RequiredInput('Complete passes and chances-created data are required')

    featured, additional = ranked[:5], ranked[5:]
    rounds = {week for week in completed_rounds(snapshot, limit=38) if week <= through}

    def season_record(row):
        history = [entry for entry in get_history(row['player_id'], session) if entry.get('round') in rounds]
        if not history or any(type(entry.get(key)) is not int
                              for entry in history for key in ('minutes', 'total_points')):
            raise RequiredInput('Official FPL season points or minutes unavailable for the shortlist')
        played = [entry['minutes'] for entry in history if entry['minutes'] > 0]
        if not played:
            raise RequiredInput('No verified appearances for a featured player')
        minutes = sum(played)
        return sum(entry['total_points'] for entry in history), minutes, minutes / len(played)

    with ThreadPoolExecutor(max_workers=5) as workers:
        for row, (points, minutes, average) in zip(featured, workers.map(season_record, featured)):
            row.update(total_points=points, total_minutes=minutes, average_minutes=average)
    sources.extend(f"https://fantasy.premierleague.com/api/element-summary/{row['player_id']}/"
                   for row in featured)

    x_leader = max(rows, key=lambda row: (row['x'], row['y']))
    y_leader = max(rows, key=lambda row: (row['y'], row['x']))
    title = slot.display_name
    caption = '\n'.join((
        f'🎯 {title}',
        f"{x_leader['name']} leads passing ({x_leader['x']:.1f}/90). {y_leader['name']} leads creation ({y_leader['y']:.2f}/90).",
        f'Premier League through GW{through} · Outfield players with {minimum}+ minutes.',
        'Who makes your FPL shortlist?',
        f'#FPL #GW{gw} #PremierLeague #FPLVORTEX',
    ))
    return Plan(slot.task, slot.edition, title, caption, gw, [], [], kind='scouting_rotation',
                extra={'layout': 'scatter', 'rows': rows, 'featured': featured,
                       'through': through, 'minimum': minimum, 'percentiles': False,
                       'x_name': passing[0], 'y_name': CHANCES[0], 'sources': sources,
                       'subtitle': f'PREMIER LEAGUE THROUGH GW{through}  |  {minimum}+ MINUTES',
                       'additional': additional,
                       'chart_hint': 'EACH DOT IS ONE PLAYER  •  RED MARKERS MATCH THE TOP LABELS',
                       'metric_note': 'A CHANCE CREATED IS A PASS THAT LEADS TO A SHOT',
                       'fetched_at': snapshot.fetched_at.astimezone(ET).isoformat()})
