"""Forecast four separate FPL chip scenarios for an ownership-based reference squad."""
from collections import Counter
from itertools import product
from os import getenv

from requests import RequestException

from .autonomous_content import Plan
from .autonomous_schedule import ET
from .editorial_inputs import NoUpdate, RequiredInput
from .fpl import latest_completed_gw
from .publication_rules import fetch_verified_xpts, five_gw_fixtures
from .wildcard import BUDGET, QUOTAS, START_MINIMUM, number, solve

CHIPS = {'bboost': 'Bench Boost', 'wildcard': 'Wildcard',
         'freehit': 'Free Hit', '3xc': 'Triple Captain'}
WATCH_CLUBS = ('Crystal Palace', 'Coventry City', 'Ipswich Town')
RULES_URL = 'https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627'


def chip_windows(chips):
    result = {chip: [] for chip in CHIPS}
    for row in chips:
        if not isinstance(row, dict) or row.get('name') not in CHIPS:
            continue
        first, last = row.get('start_event'), row.get('stop_event')
        if type(first) is int and type(last) is int and 1 <= first <= last <= 38:
            result[row['name']].append((first, last))
    for windows in result.values():
        windows.sort()
        if not windows or any(a[1] >= b[0] for a, b in zip(windows, windows[1:])):
            raise RequiredInput('Official FPL chip eligibility could not be verified')
    return result


def chip_usage(snapshot, chip, window, before):
    """Cumulative official uses in this set as a share of current registered entries."""
    through = min(before - 1, latest_completed_gw(snapshot) or 0)
    if type(snapshot.total_entries) is not int or snapshot.total_entries <= 0:
        return None, through
    events = {row['id']: row for row in snapshot.events}
    total = 0
    for gw in range(window[0], min(through, window[1]) + 1):
        event = events.get(gw, {})
        rows = event.get('chip_plays')
        if not event.get('finished') or not isinstance(rows, list) or not rows:
            return None, through
        reported = [row.get('num_played') for row in rows if row.get('chip_name') == chip]
        if len(reported) > 1 or any(type(count) is not int or count < 0 for count in reported):
            return None, through
        total += sum(reported)
    if total > snapshot.total_entries:
        return None, through
    return round(100 * total / snapshot.total_entries, 1), through


def forecast_pool(snapshot, weeks, verified):
    finished = Counter(club for row in snapshot.fixtures if row.get('finished') is True
                       for club in (row['team_h'], row['team_a']))
    official_next = {row['id'] for row in snapshot.events if row.get('is_next') is True}
    players, fixture_lists, modeled = [], [], []
    for player in snapshot.players:
        team, position, price = (player.get(key) for key in ('team', 'element_type', 'now_cost'))
        if team not in snapshot.teams or position not in QUOTAS or type(price) is not int or price <= 0:
            continue
        fixtures = five_gw_fixtures(snapshot, player, verified)
        games = finished[team]
        minutes = number(player.get('minutes'))
        starts = number(player.get('starts'))
        # Shrink short samples toward a 2-point contribution at starter minutes.
        season_rate = (number(player.get('total_points')) + 10) / (games + 5)
        recent = number(player.get('form'))
        base = max(0., .75 * season_rate + .25 * recent)
        if not minutes and not starts:
            base = 0.
        status = player.get('status')
        chance = player.get('chance_of_playing_next_round')
        availability = min(1., max(0., number(chance) / 100)) if chance is not None else float(status == 'a')
        weeks_xpts = []
        for week in weeks:
            matches = [row for row in fixtures if row['gw'] == week and not row['blank']]
            availability_this_week = availability if week == weeks[0] or status != 'a' else 1.
            estimates = [base * (1 + .13 * (3 - row['fdr']) + (.05 if row['venue'] == 'H' else -.05))
                         * availability_this_week for row in matches]
            ep_next = number(player.get('ep_next'), -1)
            if matches and week in official_next and ep_next >= 0 and status in ('a', 'd'):
                # FPL ep_next covers the whole GW, including doubles.
                total = sum(estimates)
                official_weight = .35 if minutes else 1.
                blended = (1 - official_weight) * total + official_weight * ep_next
                estimates = [blended * (v / total if total else 1 / len(matches)) for v in estimates]
            weeks_xpts.append(sum(estimates))
            for row, value in zip(matches, estimates):
                row['estimated_xpts'] = value
        players.append(player)
        fixture_lists.append(fixtures)
        modeled.append(weeks_xpts)
    # One consistent forecast scale across the compared squads.
    external = bool(verified) and all(row['xpts'] is not None
                                      for fixtures in fixture_lists for row in fixtures if not row['blank'])
    values = ([[sum(row['xpts'] for row in fixtures if row['gw'] == week and not row['blank'])
                for week in weeks] for fixtures in fixture_lists] if external else modeled)
    return players, fixture_lists, values, external


def lineups(players, points, squad):
    """Re-select the legal scoring XI and normal captain for a fixed 15."""
    positions = {pos: sorted((i for i in squad if players[i]['element_type'] == pos),
                             key=lambda i: (-points[i], players[i]['id'])) for pos in QUOTAS}
    formations = (
        positions[1][:1] + positions[2][:d] + positions[3][:m] + positions[4][:10-d-m]
        for d, m in product(range(START_MINIMUM[2], QUOTAS[2] + 1),
                            range(START_MINIMUM[3], QUOTAS[3] + 1))
        if START_MINIMUM[4] <= 10-d-m <= QUOTAS[4]
    )
    def score(xi):
        return sum(points[i] for i in xi) + max(points[i] for i in xi)

    xi = max(formations, key=score)
    captain = max(xi, key=lambda i: (points[i], -players[i]['id']))
    return score(xi), captain, sorted(set(squad) - set(xi), key=lambda i: -points[i])


def continuation(players, columns, candidates_by_position, squad, first_move=0):
    """Keep a legal roster, taking at most one improving free transfer each week."""
    squad = set(squad)
    scores = []
    for offset, points in enumerate(columns):
        if offset >= first_move:
            remaining = columns[offset:]
            old_scores = [lineups(players, week, squad)[0] for week in remaining]
            best_gain, best_change = 0.05, None
            clubs = Counter(players[i]['team'] for i in squad)
            cost = sum(players[i]['now_cost'] for i in squad)
            for out in sorted(squad):
                old = players[out]
                for new in candidates_by_position[offset][old['element_type']]:
                    if new in squad:
                        continue
                    player = players[new]
                    if (cost - old['now_cost'] + player['now_cost'] > BUDGET
                            or (player['team'] != old['team'] and clubs[player['team']] >= 3)):
                        continue
                    changed = (squad - {out}) | {new}
                    gain = sum(lineups(players, week, changed)[0] - prior
                               for week, prior in zip(remaining, old_scores))
                    if gain > best_gain:
                        best_gain, best_change = gain, changed
            if best_change is not None:
                squad = best_change
        scores.append(lineups(players, points, squad))
    return scores


def chip_scenarios(snapshot, players, fixtures, values, weeks, windows):
    owners = [number(p.get('selected_by_percent')) for p in players]
    reference, _, _ = solve(players, [[0.] for _ in players], time_limit=5, roster_priority=owners)
    # Only available or doubtful players with established minutes enter the rebuild
    # pool. Inactive players remain in the ownership baseline.
    active = [i for i, p in enumerate(players) if p.get('status') in ('a', 'd')
              and (number(p.get('minutes')) > 0 or number(p.get('ep_next')) > 0)]
    candidates = [players[i] for i in active]
    games = Counter(club for row in snapshot.fixtures if row.get('finished') is True
                    for club in (row['team_h'], row['team_a']))
    if len(candidates) < sum(QUOTAS.values()):
        raise RequiredInput('Too few players with official playing-time evidence for chip analysis')
    columns = list(zip(*values, strict=True))
    by_position = [
        {pos: sorted((i for i in active if players[i]['element_type'] == pos),
                     key=lambda i: (-sum(values[i][offset:]), players[i]['id']))[:12]
         for pos in QUOTAS}
        for offset in range(len(weeks))
    ]
    baseline = continuation(players, columns, by_position, reference,
                            first_move=0 if weeks[0] > 1 else 1)
    rows = {chip: [] for chip in CHIPS}
    for offset, gw in enumerate(weeks):
        points = columns[offset]
        score, captain, bench = baseline[offset]
        bench_value = sum(points[i] for i in bench)
        secure = sum(points[i] > 0 and players[i].get('status') == 'a'
                     and number(players[i].get('starts')) >= .65 * max(1, games[players[i]['team']])
                     for i in bench)
        matches = [f"{row['opponent']} ({row['venue']})"
                   for row in fixtures[captain] if row['gw'] == gw and not row['blank']]
        captain_name = snapshot.name(players[captain])
        details = {
            'bboost': (bench_value, f'{secure}/4 regular bench starters. Confirm all four can play.'),
            '3xc': (points[captain], f"{captain_name} vs {' / '.join(matches) or 'blank'} • best captain in reference XI"),
        }
        for chip, end in (('freehit', offset + 1), ('wildcard', len(weeks))):
            if not any(first <= gw <= last for first, last in windows[chip]):
                continue
            chosen, _, _ = solve(candidates, [values[i][offset:end] for i in active],
                                 time_limit=5, first_week_weight=1., bench_weight=0.)
            squad = [active[i] for i in chosen]
            path = continuation(players, columns[offset:end], by_position[offset:end], squad, first_move=1)
            total = sum(week[0] for week in path)
            old = sum(baseline[i][0] for i in range(offset, end))
            duration = 'One-week rebuild. Squad reverts next GW.' if chip == 'freehit' else f'Permanent rebuild, with gain measured through GW{weeks[-1]}.'
            details[chip] = (total - old, duration)
        for chip, entries in rows.items():
            entry = details.get(chip)
            legal = any(first <= gw <= last for first, last in windows[chip])
            entries.append({'gw': gw, 'xpts': round(entry[0], 2) if entry and legal else None,
                            'detail': entry[1] if entry and legal else 'Ineligible under FPL rules',
                            'player_id': players[captain]['id'] if chip == '3xc' else None,
                            'conditional': chip == 'bboost' and secure < 4})
    return rows, [players[i]['id'] for i in reference]


def recommendations(snapshot, rows, windows, start):
    # Schedule across distinct weeks using each chip's relative opportunity.
    # The scenarios themselves are standalone and their gains are not additive.
    current = {chip: next((window for window in sets if window[1] >= start), None)
               for chip, sets in windows.items()}
    available = {}
    for chip, window in current.items():
        available[chip] = [r for r in rows[chip] if window and r['xpts'] is not None
                           and r['xpts'] > 0 and window[0] <= r['gw'] <= window[1]]
    best = {chip: max((r['xpts'] for r in choices), default=1) for chip, choices in available.items()}

    def distinct(combo):
        weeks = [row['gw'] for row in combo if row]
        return len(weeks) == len(set(weeks))

    def fit(combo):
        return sum(row['xpts'] / best[chip] for chip, row in zip(CHIPS, combo) if row)

    choices = product(*([*available[chip], None] for chip in CHIPS))
    selected = max((combo for combo in choices if distinct(combo)), key=fit)
    cards = {}
    for chip, row in zip(CHIPS, selected):
        window = current[chip]
        usage, through = chip_usage(snapshot, chip, window, start) if window else (None, 0)
        cards[chip] = {'pick': row, 'peak': max(available[chip], key=lambda r: r['xpts'], default=None),
                       'usage': usage, 'through': through, 'expires': window[1] if window else None}
    return cards


def fixture_targets(snapshot, players, fixture_lists, external, *, all_clubs=False):
    opponents = {team['short_name']: name for team in snapshot.teams.values()
                 for name in WATCH_CLUBS if team.get('name') in (name, name.split(' City')[0], name.split(' Town')[0])
                 and team.get('short_name')}
    if all_clubs:
        opponents = {team['short_name']: team['name'] for team in snapshot.teams.values()
                     if team.get('short_name') and team.get('name')}
    by_fixture = {}
    field = 'xpts' if external else 'estimated_xpts'
    for player, fixtures in zip(players, fixture_lists, strict=True):
        for row in fixtures:
            if row['blank'] or row['opponent'] not in opponents or row[field] <= 0:
                continue
            key = row['fixture_id'], player['team']
            if key not in by_fixture:
                by_fixture[key] = {'gw': row['gw'], 'club': snapshot.teams[player['team']]['name'],
                                  'opponent': opponents[row['opponent']], 'venue': row['venue'],
                                  'points': []}
            by_fixture[key]['points'].append(row[field])
    ranked = []
    for row in by_fixture.values():
        if len(row['points']) >= 3:
            total = sum(sorted(row['points'], reverse=True)[:3])
            ranked.append({k: v for k, v in row.items() if k != 'points'} | {'total': round(total, 1)})
    best = sorted(ranked, key=lambda r: (-r['total'], r['gw'], r['club']))
    clubs = {}
    for row in best:
        clubs.setdefault(row['club'], row)
    return list(clubs.values())[:3]


def build_chip_strategy(slot, snapshot, now, session, *, dynamic_targets=False):
    start = snapshot.gameweek()
    if not start:
        raise NoUpdate('No upcoming FPL deadline for Chip Strategy')
    weeks = list(range(start, min(start + 5, 39)))
    windows = chip_windows(snapshot.chips)
    try:
        verified = fetch_verified_xpts(now, snapshot, session)
    except (RequestException, ValueError):
        verified = {}
    players, fixtures, values, external = forecast_pool(snapshot, weeks, verified)
    rows, squad = chip_scenarios(snapshot, players, fixtures, values, weeks, windows)
    cards = recommendations(snapshot, rows, windows, start)
    title = 'FPL CHIP STRATEGY'
    picks = []
    for chip, card in cards.items():
        row = card['pick']
        picks.append(f"{CHIPS[chip]} GW{row['gw']} {row['xpts']:+.1f} xPts" + (' if all four start' if row['conditional'] else '') if row else f'{CHIPS[chip]} hold')
    span = f'GW{start}–{weeks[-1]}' if len(weeks) > 1 else f'GW{start}'
    caption = '\n'.join((
        f'🏆 {title} | {span}', ' • '.join(picks[:2]), ' • '.join(picks[2:]),
        'Check your chips and squad first. Estimates use a £100m reference squad.',
        f'#FPL #GW{start} #FPLChips #FPLVORTEX',
    ))
    source = getenv('FPL_XPTS_SNAPSHOT_URL', '').strip() if external else ''
    return Plan(slot.task, slot.edition, title, caption, start, [], [], 'chip_strategy', {
        'weeks': weeks, 'span': span, 'rows': rows, 'cards': cards, 'squad': squad,
        'targets': fixture_targets(snapshot, players, fixtures, external, all_clubs=dynamic_targets),
        'forecast': 'VERIFIED FIXTURE PROJECTIONS' if external else 'FPL EP NEXT + FORM / MINUTES / FDR ESTIMATES',
        'data_date': snapshot.fetched_at.astimezone(ET).strftime('%d %b %Y'),
        'sources': [RULES_URL] + ([source] if source else []),
    })
