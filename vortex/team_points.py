"""Season-to-date Premier League points against a match-xG Poisson baseline."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from csv import DictReader
from datetime import datetime, timezone
from io import StringIO
from math import isfinite
from urllib.parse import quote

from .autonomous_schedule import ET, season_id
from .editorial_inputs import RequiredInput
from .fpl import latest_completed_gw
from .odds_model import predicted_probabilities

ARCHIVE = 'https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main/data'


def kickoff(value):
    timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    # The archive uses UTC without the suffix in some CSVs.
    return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp


def integral(value):
    number = float(value)
    if not number.is_integer() or number < 0:
        raise ValueError('Expected nonnegative integer')
    return int(number)


def match_xg(url, session, official):
    response = session.get(url, timeout=(8, 15))
    response.raise_for_status()
    results = {}
    for row in DictReader(StringIO(response.text)):
        if row.get('finished', '').casefold() not in ('true', '1'):
            continue
        try:
            key = (kickoff(row['kickoff_time']), integral(row['home_team']),
                   integral(row['away_team']))
            fixture = official.get(key)
            if fixture is None:
                continue
            if fixture['id'] in results:
                raise ValueError('Duplicate match from archive')
            if (integral(row['home_score']), integral(row['away_score'])) != (
                fixture['team_h_score'], fixture['team_a_score']
            ):
                raise ValueError('Archive score does not match official FPL')
            rates = (float(row['home_expected_goals_xg']), float(row['away_expected_goals_xg']))
            if not all(isfinite(rate) and 0 <= rate <= 12 for rate in rates):
                raise ValueError('Invalid match xG')
            results[fixture['id']] = rates
        except (ValueError, TypeError, KeyError) as exc:
            raise RequiredInput(f'Unverified FPL Core match record: {exc}') from exc
    if set(results) != {fixture['id'] for fixture in official.values()}:
        raise RequiredInput('FPL Core xG coverage is incomplete for a completed official gameweek')
    return results


def build_team_points(slot, snapshot, now, session, *, through=None):
    from .autonomous_content import Plan

    through = through or latest_completed_gw(snapshot)
    if through is None:
        raise RequiredInput('No completed official gameweek for team points')
    year = int(season_id(snapshot, now).split('-')[0])
    codes = {team_id: team['code'] for team_id, team in snapshot.teams.items()}
    rounds = {}
    for fixture in snapshot.fixtures:
        gw = fixture.get('event')
        if type(gw) is int and gw <= through and fixture.get('finished') is True:
            key = (kickoff(fixture['kickoff_time']), codes[fixture['team_h']], codes[fixture['team_a']])
            official = rounds.setdefault(gw, {})
            if key in official:
                raise RequiredInput('Duplicate official league fixture')
            official[key] = fixture
    if not rounds:
        raise RequiredInput('No completed official league fixtures')
    sources = [f'{ARCHIVE}/{year}-{year+1}/{quote(f"By Tournament/Premier League/GW{gw}/matches.csv", safe="/")}'
               for gw in sorted(rounds)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        verified = list(pool.map(lambda pair: match_xg(pair[0], session, pair[1]),
                                 zip(sources, (rounds[gw] for gw in sorted(rounds)))))

    expected, actual, played = Counter(), Counter(), Counter()
    matches = []
    for gw, rates_by_id in zip(sorted(rounds), verified):
        for fixture in rounds[gw].values():
            home, away = fixture['team_h'], fixture['team_a']
            xg = rates_by_id[fixture['id']]
            home_win, draw, away_win, _ = predicted_probabilities(*xg)
            expected[home] += 3 * home_win + draw
            expected[away] += 3 * away_win + draw
            hs, aws = fixture['team_h_score'], fixture['team_a_score']
            actual[home] += 3 if hs > aws else int(hs == aws)
            actual[away] += 3 if aws > hs else int(hs == aws)
            played.update((home, away))
            matches.append({'id': fixture['id'], 'xg': xg, 'score': [hs, aws]})

    teams = [{'name': team['name'], 'short': team['short_name'], 'code': team['code'],
              'expected': round(expected[team_id], 2), 'actual': actual[team_id],
              'played': played[team_id]} for team_id, team in snapshot.teams.items()]
    if not teams or any(not team['played'] for team in teams):
        raise RequiredInput('Complete club coverage is needed for the league points board')
    above = max(teams, key=lambda team: team['actual'] - team['expected'])
    below = min(teams, key=lambda team: team['actual'] - team['expected'])
    date = now.astimezone(ET).date().isoformat()
    gw = snapshot.gameweek() or through
    title = 'EXPECTED VS ACTUAL POINTS'
    caption = (
        f'{title} • Through GW{through} | {date}\n'
        f"{above['name']}: {above['actual']} actual vs {above['expected']:.1f} expected league points.\n"
        f"{below['name']}: {below['actual']} actual vs {below['expected']:.1f} expected league points.\n"
        'Use the gap to spot clubs worth a closer look. Check player minutes and fixtures before transferring.\n'
        f'#FPL #GW{gw} #PremierLeague #FPLVORTEX'
    )
    return Plan(slot.task, slot.edition, title, caption, gw, [], [], 'team_points',
                {'teams': teams, 'matches': matches, 'through': through, 'edition_date': date,
                 'sources': sources})
