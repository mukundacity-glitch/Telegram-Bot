"""Build the two-panel evening watch boards from verified completed rounds."""
from datetime import datetime
from math import isfinite

from .autonomous_schedule import ET, SUNDAY_CHANCES, MONDAY_DEFENCE, season_id
from .editorial_inputs import RequiredInput
from .fpl import latest_completed_gw
from .weekly_analysis import player_totals

TITLE = 'SUNDAY CHANCE WATCH'
MINUTES = 450
METRICS = (
    ('xg', 'xG', 0.4),
    ('total_shots', 'SHOTS', 3),
    ('touches_opposition_box', 'BOX TOUCHES', 5),
)
POSITIONS = {3: 'MIDFIELDERS', 4: 'FORWARDS'}
DEFENCE_TITLE = 'MONDAY DEFENCE WATCH'
DEFENCE_POSITIONS = {1: 'GOALKEEPERS', 2: 'DEFENDERS'}
DEFENCE_METRICS = {
    'GOALKEEPERS': (('saves', 'SAVES', 3), ('saves_inside_box', 'BOX SAVES', 2),
                    ('sweeper_actions', 'SWEEPS', 0.5)),
    'DEFENDERS': (('clearances', 'CLEARANCES', 4), ('interceptions', 'INTERCEPTIONS', 1),
                  ('tackles_won', 'TACKLES WON', 1.5)),
}
GROUP_ORDER = (7, 3, 5, 6, 1, 2, 4)


def _rank(row):
    return (-row['mask'].bit_count(), -row['rates'][0], -row['rates'][1],
            -row['rates'][2], -row['minutes'], row['name'].casefold(), row['player_id'])


def build_sunday_chances(slot, snapshot, now, session):
    return _build(slot, snapshot, now, session, TITLE, POSITIONS,
                  dict.fromkeys(POSITIONS.values(), METRICS),
                  'The board groups players by xG, shots and opposition-box touches.')


def build_monday_defence(slot, snapshot, now, session):
    return _build(slot, snapshot, now, session, DEFENCE_TITLE, DEFENCE_POSITIONS, DEFENCE_METRICS,
                  'Keeper shot-stopping and sweeping on the left, defender actions on the right.',
                  defence=True)


def _build(slot, snapshot, now, session, title, positions, metrics, description, *, defence=False):
    from .autonomous_content import Plan

    gw, through = snapshot.gameweek(), latest_completed_gw(snapshot)
    if not gw or through is None:
        raise RequiredInput(f'{title} requires a verified completed gameweek')
    season = season_id(snapshot, now)
    fields = tuple(dict.fromkeys(field for group in metrics.values() for field, _, _ in group))
    required_by_position = ({number: tuple(field for field, _, _ in metrics[label])
                             for number, label in positions.items()} if defence else {})
    stats, sources = player_totals(
        snapshot, through, session, int(season.split('-')[0]), fields,
        require_shot_xg=not defence,
        required_nonblank_fields=() if defence else ('touches_opposition_box',),
        required_nonblank_by_position=required_by_position,
    )
    rows = {label: [] for label in positions.values()}
    eligible = dict.fromkeys(positions.values(), 0)
    incomplete = dict.fromkeys(positions.values(), 0)
    for player, values in stats:
        position = positions.get(player.get('element_type'))
        minutes = values['minutes']
        if position is None or minutes < MINUTES:
            continue
        eligible[position] += 1
        if values.get('incomplete_shot_xg') or values.get('incomplete_metrics'):
            incomplete[position] += 1
            continue
        rates = tuple(round(values[field] * 90 / minutes, 10) for field, _, _ in metrics[position])
        if not all(isfinite(rate) for rate in rates):
            raise RequiredInput('Invalid season performance rate in FPL Core match archive')
        mask = sum(1 << index for index, (_, _, threshold) in enumerate(metrics[position])
                   if rates[index] >= threshold)
        if mask:
            rows[position].append({
                'player_id': player['id'], 'name': snapshot.name(player),
                'photo': snapshot.photo_code(player), 'code': snapshot.team_code(player),
                'rates': rates, 'mask': mask, 'minutes': int(minutes),
            })
    for position in positions.values():
        if eligible[position] <= incomplete[position]:
            raise RequiredInput(f'No verified {position.lower()} with {MINUTES}+ minutes')
        rows[position].sort(key=_rank)

    leaders = ' and '.join(f"{sum(row['mask'] == 7 for row in rows[position])} {position.lower()}"
                           for position in positions.values())
    coverage = sum(incomplete.values())
    scope = (f'{MINUTES}+ season minutes through GW{through}. '
             f'{coverage} players have incomplete coverage.' if coverage
             else f'{MINUTES}+ season minutes through GW{through}. Source: FPL Core match stats.')
    caption = '\n'.join((
        f'🎯 {title} | GW{gw}',
        f'{leaders} clear all three per-90 thresholds.',
        description,
        f'{scope} Who makes your watchlist?',
        f'#FPL #GW{gw} #FPLVORTEX #PremierLeague',
    ))
    return Plan(slot.task, slot.edition, title, caption, gw, [], [], 'sunday_chances', {
        'season': season, 'through': through, 'rows': rows, 'eligible': eligible,
        'incomplete': incomplete, 'sources': sources,
        **({'metrics': metrics} if defence else {}),
        'retrieved_at': datetime.now(ET).isoformat(),
        'data_at': snapshot.fetched_at.astimezone(ET).isoformat(),
    })


def preview():
    """Render current football data and write a review bundle without publishing."""
    import argparse
    import json
    from pathlib import Path

    from .autonomous_content import Evidence
    from .fpl import collect_snapshot
    from .sunday_chances_render import render_sunday_chances

    parser = argparse.ArgumentParser()
    parser.add_argument('--monday', action='store_true', help='Preview Monday Defence Watch')
    monday = parser.parse_args().monday
    slot, build = ((MONDAY_DEFENCE, build_monday_defence) if monday
                   else (SUNDAY_CHANCES, build_sunday_chances))
    snapshot = collect_snapshot()
    now = datetime.now(ET)
    evidence = Evidence(snapshot, now)
    plan = build(slot, snapshot, now, evidence.session)
    target = Path('output') / slot.edition
    render_sunday_chances(plan, target / f'{slot.edition}.png', evidence.session)
    (target / 'data.json').write_text(json.dumps(plan.extra, indent=2, ensure_ascii=False) + '\n',
                                     encoding='utf-8')
    (target / 'caption.txt').write_text(plan.caption + '\n', encoding='utf-8')
    print(plan.caption)


if __name__ == '__main__':
    preview()
