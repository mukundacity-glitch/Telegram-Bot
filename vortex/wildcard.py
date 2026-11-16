"""Select a legal FPL Wildcard and choose an XI and captain for each gameweek."""
from collections import Counter
from math import isfinite
from os import getenv

import numpy as np
from requests import RequestException
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from .editorial_inputs import RequiredInput
from .publication_rules import fetch_verified_xpts, five_gw_fixtures

QUOTAS = {1: 2, 2: 5, 3: 5, 4: 3}
START_MINIMUM = {1: 1, 2: 3, 3: 2, 4: 1}
BUDGET = 1000
POSITION_LABEL = {1: 'GK', 2: 'DEF', 3: 'MID', 4: 'FWD'}


def number(value, default=0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if isfinite(result) else default


def candidate_pool(snapshot, weeks, verified):
    completed = Counter(club for f in snapshot.fixtures if f.get('finished') is True
                        for club in (f['team_h'], f['team_a']))
    has_ep = [e['id'] for e in snapshot.events if e.get('is_next') is True] == [weeks[0]]
    result = []
    for p in snapshot.players:
        club, position = p.get('team'), p.get('element_type')
        played = completed[club]
        minutes, starts = number(p.get('minutes')), number(p.get('starts'))
        if (club not in snapshot.teams or position not in QUOTAS or p.get('status') != 'a'
                or p.get('chance_of_playing_next_round') not in (None, 100)
                or type(p.get('now_cost')) is not int or p['now_cost'] <= 0
                or not snapshot.photo_code(p) or not played or minutes / played < 45
                or starts / played < (.65 if position == 1 else .50)):
            continue
        fixtures = five_gw_fixtures(snapshot, p, verified)
        base = max(.1, .65 * max(0, number(p.get('points_per_game')))
                   + .35 * max(0, number(p.get('form'))))
        # Editorial fallback combines observed form, historical points, role
        # security and official difficulty. This is a ranking score, not xPts.
        role = min(1., minutes / (75 * played))
        scores, forecast = [], []
        for week in weeks:
            matches = [f for f in fixtures if f['gw'] == week and not f['blank']]
            score = sum(base * role * (1 + .11 * (3 - f['fdr'])) for f in matches)
            ep_next = number(p.get('ep_next'), -1)
            if week == weeks[0] and has_ep and matches and ep_next > 0:
                score = .7 * score + .3 * ep_next
            scores.append(score)
            forecast.append(sum(f['xpts'] for f in matches)
                            if all(f['xpts'] is not None for f in matches) else None)
        result.append((p, fixtures, scores, forecast))
    return result


def solve(candidates, values, *, time_limit=35, first_week_weight=1.2,
          bench_weight=.08, roster_priority=None):
    """Binary roster, XI and captain variables with budget and formation bounds."""
    points = np.asarray(values, dtype=float).T
    weeks, n = points.shape
    size = n * (1 + 2 * weeks)
    weights = np.ones(weeks)
    weights[0] = first_week_weight
    week_value = points * weights[:, None]
    roster_value = bench_weight * week_value.sum(axis=0)
    if roster_priority is not None:
        roster_value = np.asarray(roster_priority, dtype=float)
        week_value = np.zeros_like(points)
    objective = np.concatenate((roster_value, week_value.ravel(), week_value.ravel()))
    ids, rows, data, lower, upper = [], [], [], [], []

    def constraint(cols, lo, hi, coeff=None):
        cols = list(cols)
        ids.extend(cols)
        rows.extend([len(lower)] * len(cols))
        data.extend([1] * len(cols) if coeff is None else coeff)
        lower.append(lo)
        upper.append(hi)

    positions = {pos: [i for i, p in enumerate(candidates) if p['element_type'] == pos]
                 for pos in QUOTAS}
    for pos, amount in QUOTAS.items():
        constraint(positions[pos], amount, amount)
    for club in sorted({p['team'] for p in candidates}):
        constraint((i for i, p in enumerate(candidates) if p['team'] == club), 0, 3)
    constraint(range(n), 0, BUDGET, [p['now_cost'] for p in candidates])
    for w in range(weeks):
        start, captain = n * (w + 1), n * (weeks + w + 1)
        constraint(range(start, start + n), 11, 11)
        constraint(range(captain, captain + n), 1, 1)
        for pos, minimum in START_MINIMUM.items():
            constraint((start + i for i in positions[pos]), minimum, 1 if pos == 1 else QUOTAS[pos])
        for i in range(n):
            constraint((start+i, i), -np.inf, 0, (1, -1))
            constraint((captain+i, start+i), -np.inf, 0, (1, -1))
    matrix = coo_matrix((np.asarray(data, dtype=float), (rows, ids)), shape=(len(lower), size)).tocsc()
    result = milp(-objective, integrality=np.ones(size), bounds=Bounds(0, 1),
                  constraints=LinearConstraint(matrix, lower, upper),
                  options={'time_limit': time_limit, 'mip_rel_gap': .003})
    if result.x is None or result.status not in (0, 1):
        raise RequiredInput('No verified legal £100m Wildcard found')
    selected = list(np.flatnonzero(result.x[:n] > .5))
    starts, captains = [], []
    for w in range(weeks):
        xi = list(np.flatnonzero(result.x[n*(w+1):n*(w+2)] > .5))
        capt = list(np.flatnonzero(result.x[n*(weeks+w+1):n*(weeks+w+2)] > .5))
        counts = Counter(candidates[i]['element_type'] for i in xi)
        if (len(xi) != 11 or len(capt) != 1 or capt[0] not in xi or not set(xi) <= set(selected)
                or counts[1] != 1 or any(counts[p] < q for p, q in START_MINIMUM.items())):
            raise RequiredInput('Wildcard lineup failed formation or captain verification')
        starts.append(xi)
        captains.append(capt[0])
    squad = [candidates[i] for i in selected]
    if (Counter(p['element_type'] for p in squad) != QUOTAS
            or max(Counter(p['team'] for p in squad).values(), default=0) > 3
            or sum(p['now_cost'] for p in squad) > BUDGET):
        raise RequiredInput('Wildcard squad failed budget, position or club verification')
    return selected, starts, captains


def build_wildcard(slot, snapshot, now, evidence):
    from .autonomous_content import Plan

    gw = snapshot.gameweek()
    if not gw:
        raise RequiredInput('No upcoming FPL deadline for the Wildcard')
    weeks = list(range(gw, min(gw + 5, 39)))
    try:
        verified = fetch_verified_xpts(now, snapshot, evidence.session)
    except (RequestException, ValueError) as exc:
        print(f'Wildcard projection feed unavailable: {type(exc).__name__}; using official-data ranking')
        verified = {}
    pool = candidate_pool(snapshot, weeks, verified)
    if len(pool) < sum(QUOTAS.values()):
        raise RequiredInput('Too few available players with established minutes for the Wildcard')
    # Compare like for like across the complete pool. A partial feed does not
    # give covered players an artificial advantage over a differently scaled proxy.
    model = bool(verified) and all(None not in row[3] for row in pool)
    values = [row[3 if model else 2] for row in pool]
    players = [row[0] for row in pool]
    selected, starts, captains = solve(players, values)
    xi = sorted(starts[0], key=lambda i: (players[i]['element_type'], -values[i][0], players[i]['id']))
    captain = captains[0]
    vice = max((i for i in xi if i != captain), key=lambda i: values[i][0])
    bench = sorted(set(selected) - set(xi),
                   key=lambda i: (players[i]['element_type'] != 1, -values[i][0], players[i]['id']))
    cost = sum(players[i]['now_cost'] for i in selected)
    squad = [players[i] for i in xi + bench]
    title = f'Best FPL Wildcard for Gameweek {gw}'
    formation = '-'.join(str(sum(players[i]['element_type'] == pos for i in xi)) for pos in (2, 3, 4))
    method = 'Verified fixture xPts' if model else 'Official FPL form, points, minutes and FDR ranking'
    caption = '\n'.join((f'🏆 {title}',
                         f"£{cost / 10:.1f}m • {formation} • {snapshot.name(players[captain])} (C) • {snapshot.name(players[vice])} (VC).",
                         f"GW{gw}–{weeks[-1]} planned using {method.lower()}.",
                         "Who would you swap before the deadline?",
                         f'#FPL #GW{gw} #FPLWildcard #FPLVORTEX'))
    return Plan(slot.task, slot.edition, title, caption, gw, squad, [], 'wildcard', {
        'weeks': weeks, 'formation': formation, 'cost': cost, 'model': model, 'method': method,
        'captain': players[captain]['id'], 'vice': players[vice]['id'],
        'xi': [players[i]['id'] for i in xi], 'bench': [players[i]['id'] for i in bench],
        'fixtures': {str(players[i]['id']): pool[i][1] for i in selected},
        'lineups': [[players[i]['id'] for i in lineup] for lineup in starts],
        'weekly_captains': [players[i]['id'] for i in captains],
        'sources': [getenv('FPL_XPTS_SNAPSHOT_URL', '').strip()] if model and getenv('FPL_XPTS_SNAPSHOT_URL') else [],
    })
