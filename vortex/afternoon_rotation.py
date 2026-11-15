"""Seven distinct 13:30 Eastern editions, one per local weekday."""
from dataclasses import replace
from statistics import mean

from .autonomous_schedule import ET
from .editorial_inputs import RequiredInput
from .low_owned_six import number

POSITIONS = ('GOALKEEPERS', 'DEFENDERS', 'MIDFIELDERS', 'FORWARDS')
TRANSFER_COUNTS = (2, 5, 5, 3)
TOPIC_TAGS = ('FPLTransfers', 'FPLDifferentials', 'FPLFixtures', 'FPLValue',
              'FPLTransfers', 'FPLCleanSheets', 'FPLTransfers')


def value_board(slot, snapshot, evidence, model, now):
    from .autonomous_content import Plan, build

    gw = snapshot.gameweek()
    try:
        return build(replace(slot, edition='value-board'), snapshot, now, evidence, model,
                     value_quotas=(2, 5, 5, 5))
    except RequiredInput:
        pass

    if [event['id'] for event in snapshot.events if event.get('is_next') is True] != [gw]:
        raise RequiredInput('Official FPL forecast is not aligned to the next gameweek')
    players, values = [], {}
    for pos, quota in enumerate((2, 5, 5, 5), start=1):
        options = []
        for p in snapshot.players:
            if (p.get('element_type') != pos or p.get('status') != 'a'
                    or p.get('chance_of_playing_next_round') not in (None, 100)
                    or not snapshot.photo_code(p) or not snapshot.team_code(p)
                    or not p.get('now_cost')):
                continue
            forecast = number(p.get('ep_next'))
            fixtures = snapshot.fixtures_for_gameweek(p, gw)
            if forecast is None or not 0 < forecast <= 40 or not fixtures or any(f[2] is None for f in fixtures):
                continue
            fdr = mean(f[2] for f in fixtures)
            values[str(p['id'])] = {'xpts': forecast, 'fdr': fdr, 'points_source': 'FPL EP_NEXT',
                                    'fdr_source': 'OFFICIAL FPL FDR'}
            options.append(p)
        options.sort(key=lambda p: (-values[str(p['id'])]['xpts'], values[str(p['id'])]['fdr'], p['id']))
        if len(options) < quota:
            raise RequiredInput(f'Insufficient verified next-GW forecasts for {POSITIONS[pos-1]}')
        players.extend(options[:quota])
    return Plan(slot.task, slot.edition, 'VALUE BOARD', '', gw, players, ['MONITOR'] * len(players),
                'rotation_value', {'values': values})


def transfer_board(slot, snapshot, evidence, *, selling):
    from .autonomous_content import Plan

    gw = snapshot.gameweek()
    direction = 'transfers_out_event' if selling else 'transfers_in_event'
    weeks = sorted(e['id'] for e in snapshot.events if gw <= e['id'] < gw + 5)
    rows, players, labels = {}, [], []
    for pos, quota in enumerate(TRANSFER_COUNTS, start=1):
        pool = [p for p in snapshot.players if p.get('element_type') == pos
                and snapshot.photo_code(p) and snapshot.team_code(p)
                and number(p.get('selected_by_percent')) is not None and p.get('now_cost')
                and all(type(p.get(k)) is int and p[k] >= 0 for k in
                        ('transfers_in_event', 'transfers_out_event')) and p[direction] > 0]
        pool.sort(key=lambda p: (-p[direction], p['id']))
        for p in pool[:quota]:
            fixtures = [snapshot.fixtures_for_gameweek(p, week) for week in weeks]
            fdr = [f[2] for week in fixtures for f in week if f[2] is not None]
            recent = evidence.recent(p)
            if p.get('status') in ('i', 's', 'u') and p.get('chance_of_playing_next_round') == 0:
                verdict = 'SELL'
            elif (not selling and fixtures and fixtures[0] and fdr and mean(fdr) <= 3
                  and p.get('status') == 'a' and p.get('chance_of_playing_next_round') in (None, 100)
                  and len(recent) >= 3 and all((r.get('minutes') or 0) >= 70 for r in recent[:3])):
                verdict = 'BUY'
            else:
                verdict = 'HOLD'
            players.append(p)
            labels.append(verdict)
            rows[str(p['id'])] = {'fixtures': fixtures, 'in': p['transfers_in_event'],
                                  'out': p['transfers_out_event']}
    if not players:
        raise RequiredInput('No verified FPL transfer activity for the gameweek')
    title = 'MOST SOLD • HOLD OR SELL' if selling else 'MOST BOUGHT • BUY / HOLD / SELL'
    return Plan(slot.task, slot.edition, title, '', gw, players, labels,
                'rotation_transfers', {'weeks': weeks, 'rows': rows})


def build_rotation(slot, snapshot, now, evidence, model=None):
    from .autonomous_content import build
    from .odds_board import build_odds_board

    local = now.astimezone(ET)
    day = local.weekday()
    if day == 0:
        plan = build(replace(slot, edition='availability-transfer-decisions'), snapshot, now, evidence)
        lines = (f'{len(plan.players)} FPL players assessed across five transfer tiers.',
                 'See availability, price and five-gameweek fixture runs.',
                 'Prioritize secure minutes and the next matchup before using a free transfer.')
    elif day == 1:
        plan = build(replace(slot, edition='rank-booster'), snapshot, now, evidence)
        lines = tuple(plan.caption.splitlines()[1:4])
    elif day in (2, 5):
        plan = build_odds_board(slot, snapshot, evidence, market_outlook=day == 2)
        rows = [row for row in plan.extra['rows'] if row['goals'] is not None]
        attack = max(rows, key=lambda row: row['goals'])
        defence = max(rows, key=lambda row: row['clean_sheet'])
        if day == 2:
            win = max((row for row in plan.extra['rows'] if row['win'] is not None),
                      key=lambda row: row['win'])
            takeaway = f"{win['team']} has the highest verified win probability ({win['win']:.0f}%)."
        else:
            takeaway = 'Use official fixture difficulty to compare defender starts.'
        lines = (f"{attack['team']} leads covered fixtures with {attack['goals']:.2f} projected goals.",
                 f"{defence['team']} leads clean-sheet forecasts at {defence['clean_sheet']:.0f}%.",
                 takeaway)
    elif day == 3:
        plan = value_board(slot, snapshot, evidence, model, now)
        plan = replace(plan, title='NEXT GAMEWEEK VALUE BOARD', kind='rotation_value')
        values = plan.extra['values']
        leader = max(plan.players, key=lambda p: values[str(p['id'])]['xpts'])
        forecast = values[str(leader['id'])]
        lines = (f"{snapshot.name(leader)} leads the board at {forecast['xpts']:.2f} ({forecast['points_source']}).",
                 'Compare the top options by position, price and fixture difficulty.',
                 'Weigh the projected return against how much budget the move frees up.')
    else:
        selling = day == 6
        plan = transfer_board(slot, snapshot, evidence, selling=selling)
        direction = 'out' if selling else 'in'
        lead = max(plan.players, key=lambda p: plan.extra['rows'][str(p['id'])][direction])
        count = plan.extra['rows'][str(lead['id'])][direction]
        lines = (f'{snapshot.name(lead)} leads the board with {count:,} transfers {direction}.',
                 'Compare ownership, both transfer counts and the next five gameweeks.',
                 'Check return dates before selling.' if selling
                 else 'Check recent starts and fixture difficulty before following the market.')
    caption = '\n'.join((f'GW{plan.gw} • {plan.title}', *lines,
                         f'#FPL #GW{plan.gw} #FPLVORTEX #{TOPIC_TAGS[day]}'))
    return replace(plan, task=slot.task, edition=slot.edition, caption=caption,
                   extra={**plan.extra, 'rotation_day': day + 1, 'rotation_date': local.date().isoformat()})
