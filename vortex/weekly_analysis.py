"""Seven Premier League analysis editions from official FPL and FPL Core."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from csv import DictReader
from dataclasses import replace
from io import StringIO
from itertools import groupby
from math import isfinite
from urllib.parse import quote

from .autonomous_schedule import season_id
from .editorial_inputs import RequiredInput
from .fpl import latest_completed_gw
from .odds_model import predicted_probabilities
from .team_points import ARCHIVE, build_team_points, integral, kickoff


def archive_url(year, name, gw=None):
    path = f'By Tournament/Premier League/GW{gw}/{name}' if gw else name
    return f'{ARCHIVE}/{year}-{year+1}/{quote(path, safe="/")}'


def csv_rows(session, url):
    response = session.get(url, timeout=(8, 18))
    response.raise_for_status()
    return list(DictReader(StringIO(response.text)))


def rounds_for(snapshot, through):
    return sorted({f['event'] for f in snapshot.fixtures
                   if type(f.get('event')) is int and f['event'] <= through and f.get('finished')})


def archive_rounds(session, year, rounds, name):
    urls = [archive_url(year, name, gw) for gw in rounds]
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(lambda url: csv_rows(session, url), urls)), urls


def number(row, field):
    if field not in row:
        raise RequiredInput(f'FPL Core metric missing: {field}')
    return float(row[field] or 0)


def player_totals(snapshot, through, session, year, fields, *, previous=False, optional_fields=()):
    players = {p['code']: p for p in snapshot.players if p.get('code') and p.get('team') in snapshot.teams}
    totals = {}
    sources = []
    incomplete_optional = set()
    seasons = [(year, rounds_for(snapshot, through))]
    if previous:
        seasons.append((year-1, range(1, 39)))
    for start, rounds in seasons:
        identity_url = archive_url(start, 'players.csv')
        identity = {integral(p['player_id']): integral(p['player_code'])
                    for p in csv_rows(session, identity_url) if p.get('player_id') and p.get('player_code')}
        batches, urls = archive_rounds(session, start, rounds, 'playermatchstats.csv')
        sources.extend([identity_url, *urls])
        expected_matches = {gw: sum(f.get('event') == gw and f.get('finished') is True
                                    for f in snapshot.fixtures) for gw in rounds}
        for gw, batch in zip(rounds, batches):
            matches = {r['match_id'] for r in batch if number(r, 'minutes_played') > 0}
            if len(matches) != (expected_matches[gw] if start == year else 10):
                # A previous season can have blank/double rounds; the complete
                # season is checked as a whole below.
                if start == year or not matches:
                    raise RequiredInput('FPL Core player data does not cover the completed fixtures')
            for field in optional_fields:
                covered = {row['match_id'] for row in batch
                           if row.get(field) and number(row, 'minutes_played') > 0}
                if covered != matches:
                    incomplete_optional.add(field)
            for row in batch:
                if not row.get('player_id') or number(row, 'minutes_played') <= 0:
                    continue
                code = identity.get(integral(row['player_id']))
                if code not in players:
                    continue
                record = totals.setdefault(code, defaultdict(float))
                record['minutes'] += number(row, 'minutes_played')
                record['appearances'] += 1
                for field in fields:
                    if field in optional_fields and not row.get(field):
                        continue
                    value = number(row, field)
                    if not isfinite(value) or value < 0:
                        raise RequiredInput(f'Invalid FPL Core metric: {field}')
                    record[field] += value
        if start != year and len({row['match_id'] for batch in batches for row in batch
                                  if number(row, 'minutes_played') > 0}) != 380:
            raise RequiredInput('Previous Premier League season player archive is incomplete')
    return [(players[code], {key: value for key, value in values.items() if key not in incomplete_optional})
            for code, values in totals.items()], sources


def common_row(snapshot, player, values, value, detail):
    return {'name': snapshot.name(player), 'code': snapshot.team_code(player),
            'photo': snapshot.photo_code(player), 'value': value,
            'detail': detail, 'minutes': int(values.get('minutes', 0))}


def fixture_rows(snapshot):
    start = snapshot.gameweek()
    last = max(e['id'] for e in snapshot.events)
    if not start:
        raise RequiredInput('No upcoming official gameweek for the fixture board')
    weeks = list(range(start, min(last+1, start+4)))
    rows = []
    for team_id, team in snapshot.teams.items():
        cells, difficulty = [], []
        for gw in weeks:
            fixtures = snapshot.fixtures_for_gameweek({'team': team_id}, gw)
            if any(fdr not in range(1, 6) for _, _, fdr, _ in fixtures):
                raise RequiredInput('Official fixture difficulty is incomplete')
            cells.append(' / '.join(f'{opp} ({venue})' for opp, venue, _, _ in fixtures) or 'BLANK')
            difficulty.extend(fdr for _, _, fdr, _ in fixtures)
        if difficulty:
            rows.append({'name': team['name'], 'code': team['code'], 'cells': cells,
                         'value': sum(difficulty)/len(difficulty), 'played': len(difficulty)})
    return sorted(rows, key=lambda r: (-r['played'], r['value'], r['name']))[:5], weeks


def goal_points(snapshot, through, session, year):
    rounds = rounds_for(snapshot, through)
    match_batches, sources = archive_rounds(session, year, rounds, 'matches.csv')
    shot_batches, shot_sources = archive_rounds(session, year, rounds, 'shots.csv')
    identity_url = archive_url(year, 'players.csv')
    identity = {integral(p['player_id']): integral(p['player_code'])
                for p in csv_rows(session, identity_url) if p.get('player_id') and p.get('player_code')}
    people = {p['code']: p for p in snapshot.players if p.get('code')}
    official = {(kickoff(f['kickoff_time']), snapshot.teams[f['team_h']]['code'],
                 snapshot.teams[f['team_a']]['code']): f for f in snapshot.fixtures
                if f.get('event') in rounds and f.get('finished')}
    tally = {}
    verified = set()
    for matches, shots in zip(match_batches, shot_batches):
        by_match = defaultdict(list)
        for shot in shots:
            if shot['outcome'].casefold() in ('goal', 'own_goal', 'owngoal', 'own goal'):
                by_match[shot['match_id']].append(shot)
        for match in matches:
            if match['finished'].casefold() not in ('1', 'true'):
                continue
            f = official.get((kickoff(match['kickoff_time']), integral(match['home_team']), integral(match['away_team'])))
            if f is None:
                continue
            if f['id'] in verified:
                raise RequiredInput('Duplicate match in goal timeline')
            verified.add(f['id'])
            rates = [number(match, k) for k in ('home_expected_goals_xg', 'away_expected_goals_xg')]
            if any(not match[k] for k in ('home_expected_goals_xg', 'away_expected_goals_xg')) or not all(0 <= rate <= 12 for rate in rates):
                raise RequiredInput('Missing or invalid match xG for a goal timeline')
            scores = [0, 0]
            goals = sorted(by_match[match['match_id']], key=lambda r: (number(r, 'minute'), number(r, 'added_time'),
                                                                      -number(r, 'shot_index')))
            for goal in goals:
                side = 0 if goal['is_home'].casefold() in ('true', '1') else 1
                remaining = max(0, 90 - number(goal, 'minute')) / 90
                home, draw, away, _ = predicted_probabilities(*(r*remaining for r in rates), goal_offset=scores[0]-scores[1])
                before = 3 * (home if side == 0 else away) + draw
                scores[side] += 1
                home, draw, away, _ = predicted_probabilities(*(r*remaining for r in rates), goal_offset=scores[0]-scores[1])
                added = 3 * (home if side == 0 else away) + draw - before
                if goal['outcome'].casefold() != 'goal' or not goal.get('player_id'):
                    continue
                code = identity.get(integral(goal['player_id']))
                if code not in people:
                    continue
                entry = tally.setdefault(code, {'total': 0., 'goals': 0, 'biggest': -1., 'note': ''})
                entry['total'] += added
                entry['goals'] += 1
                if added > entry['biggest']:
                    opponent = snapshot.teams[f['team_a' if side == 0 else 'team_h']]['short_name']
                    entry.update(biggest=added, note=f"{integral(goal['minute'])}′ vs {opponent}  +{added:.2f}")
            if scores != [f['team_h_score'], f['team_a_score']]:
                raise RequiredInput('Goal events could not be reconciled to an official final score')
    if len(verified) != len(official):
        raise RequiredInput('Goal timelines do not cover the completed gameweek fixtures')
    rows = [common_row(snapshot, people[code], {}, r['total'],
                       f"{r['goals']} goals  •  {r['total']/r['goals']:.2f}/goal  •  Biggest {r['note']}")
            for code, r in tally.items()]
    return sorted(rows, key=lambda r: (-r['value'], r['name']))[:12], sources+shot_sources+[identity_url]


def build_weekly_analysis(slot, snapshot, now, session):
    from .autonomous_content import Plan

    through = slot.series_gw or latest_completed_gw(snapshot)
    day = slot.series_day or 1
    if through is None:
        raise RequiredInput('No completed official gameweek for the analysis series')
    year = int(season_id(snapshot, now).split('-')[0])
    if day == 1:
        plan = build_team_points(slot, snapshot, now, session, through=through)
        return replace(plan, extra={**plan.extra, 'day': day})
    extra = {'through': through, 'day': day, 'layout': 'rank'}
    sources = []
    if day == 5:
        rows, weeks = fixture_rows(snapshot)
        extra.update(layout='fixtures', weeks=weeks)
        title, unit = 'TEAMS TO TARGET', 'average FDR'
        note = 'Official FPL FDR • fixture count first, then average difficulty'
    elif day == 6:
        rows, sources = goal_points(snapshot, through, session, year)
        title, unit = 'GOALS THAT ADDED POINTS', 'model points added'
        note = 'Goal-time points swing • Poisson model using remaining time and final match xG'
    else:
        fields = {2: ('chances_created',), 3: ('sweeper_actions',), 4: ('touches_opposition_box',),
                  7: ('tackles_won', 'interceptions', 'recoveries', 'touches_opposition_box')}[day]
        players, sources = player_totals(snapshot, through, session, year, fields, previous=day == 2)
        if day == 2:
            title, unit = 'CHANCE CREATORS XI', 'chances created'
            note = 'Premier League • from start of previous season • current FPL players'
            extra['layout'] = 'pitch'
            rows = []
            for pos, count in ((1, 1), (2, 4), (3, 5), (4, 1)):
                group = sorted((item for item in players if item[0]['element_type'] == pos),
                               key=lambda item: (-item[1]['chances_created'], -item[1]['minutes'], item[0]['code']))
                if len(group) < count:
                    raise RequiredInput('Incomplete position coverage for Chance Creators XI')
                rows.extend(common_row(snapshot, p, v, v['chances_created'], '') | {'position': pos}
                            for p, v in group[:count])
        elif day == 7:
            title, unit = 'BALL WINNING VS BOX INVOLVEMENT', 'role percentile'
            note = 'Midfielders with 220+ minutes • tackles won, interceptions and recoveries vs opposition box touches'
            extra['layout'] = 'scatter'
            rows = [common_row(snapshot, p, v, 0, '') | {
                'wins': (v['tackles_won']+v['interceptions']+v['recoveries'])*90/v['minutes'],
                'box_touches': v['touches_opposition_box']*90/v['minutes']}
                    for p, v in players if p['element_type'] == 3 and v['minutes'] >= 220]
            for metric, axis in (('wins', 'x'), ('box_touches', 'y')):
                ordered = sorted(rows, key=lambda r: r[metric])
                rank = 0
                for _, group in groupby(ordered, key=lambda r: r[metric]):
                    tied = list(group)
                    percentile = (rank+(len(tied)-1)/2)*100/max(1, len(rows)-1)
                    for entry in tied:
                        entry[axis] = percentile
                    rank += len(tied)
            for row in rows:
                row['value'] = (row['x']+row['y'])/2
            rows.sort(key=lambda r: (-r['value'], r['name']))
        else:
            title, unit = ('SWEEPER KEEPERS', 'sweeper actions') if day == 3 else ('OPPOSITION BOX TOUCHES', 'box touches')
            note = ('Totals and per 90 • 220+ minutes' if day == 3
                    else 'Opposition box touches • 220+ minutes')
            metric = fields[0]
            rows = [common_row(snapshot, p, v, v[metric],
                               f"{v[metric]*90/v['minutes']:.2f}/90  •  {int(v['minutes'])} min  •  {int(v['appearances'])} apps")
                    | {'rate': v[metric]*90/v['minutes']}
                    for p, v in players if v['minutes'] >= 220 and (p['element_type'] == 1 if day == 3 else p['element_type'] != 1)]
            if day == 3 and rows:
                extra['rate_leader'] = max(rows, key=lambda row: row['rate'])
            rows = sorted(rows, key=lambda r: (-r['value'], -r['rate'], r['name']))[:12]
    if not rows:
        raise RequiredInput('Verified data produced no qualifying rows for the analysis')
    leader = max(rows, key=lambda row: row['value']) if day == 2 else rows[0]
    if day == 5:
        result = f"{leader['name']} ranks first for the next {len(extra['weeks'])} GWs with {leader['value']:.2f} average FDR."
    else:
        value = f"{leader['value']:.2f}" if day == 6 else f"{leader['value']:.0f}"
        result = f"{leader['name']} leads this board with {value} {unit}."
    gw = snapshot.gameweek() or through
    if day == 7:
        ball_winner = max(rows, key=lambda row: row['x'])
        box_threat = max(rows, key=lambda row: row['y'])
        comparison = (f"Ball wins: {ball_winner['name']}. Box touches: {box_threat['name']}."
                      if ball_winner is not box_threat else 'The same midfielder leads both metrics per 90.')
        copy = '\n'.join((
            f"Who wins it back AND gets into the box? 👀 | {title.title()}",
            f"{leader['name']} tops the combined midfield ranking.",
            comparison,
            f"One free transfer. Who's your GW{gw} pick?",
            f"#FPL #GW{gw} #PremierLeague #FPLVORTEX",
        ))
    else:
        copy = '\n'.join((f'{title} • Weekly Analysis {day}/7', result,
                          note + '.', 'Use the data to shortlist targets, then verify minutes and fixtures before making a transfer.',
                          f'#FPL #GW{gw} #PremierLeague #FPLVORTEX'))
    return Plan(slot.task, slot.edition, title, copy, gw, [], [], 'weekly_analysis',
                {**extra, 'rows': rows, 'unit': unit, 'note': note, 'sources': sources})
