"""Build the Sunday midfield and forward chance-volume board from complete rounds."""
from datetime import datetime
from math import isfinite

from .autonomous_schedule import ET, SUNDAY_CHANCES, season_id
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
GROUP_ORDER = (7, 3, 5, 6, 1, 2, 4)


def _rank(row):
    return (-row['mask'].bit_count(), -row['rates'][0], -row['rates'][1],
            -row['rates'][2], -row['minutes'], row['name'].casefold(), row['player_id'])


def build_sunday_chances(slot, snapshot, now, session):
    from .autonomous_content import Plan

    gw, through = snapshot.gameweek(), latest_completed_gw(snapshot)
    if not gw or through is None:
        raise RequiredInput('Sunday Chance Watch requires a verified completed gameweek')
    season = season_id(snapshot, now)
    stats, sources = player_totals(
        snapshot, through, session, int(season.split('-')[0]),
        tuple(metric[0] for metric in METRICS), require_shot_xg=True,
        required_nonblank_fields=('touches_opposition_box',),
    )
    rows = {label: [] for label in POSITIONS.values()}
    eligible = {label: 0 for label in POSITIONS.values()}
    incomplete = {label: 0 for label in POSITIONS.values()}
    for player, values in stats:
        position = POSITIONS.get(player.get('element_type'))
        minutes = values['minutes']
        if position is None or minutes < MINUTES:
            continue
        eligible[position] += 1
        if values.get('incomplete_shot_xg') or values.get('incomplete_metrics'):
            incomplete[position] += 1
            continue
        rates = tuple(round(values[field] * 90 / minutes, 10) for field, _, _ in METRICS)
        if not all(isfinite(rate) for rate in rates):
            raise RequiredInput('Invalid season chance rate in FPL Core match archive')
        mask = sum(1 << index for index, (_, _, threshold) in enumerate(METRICS)
                   if rates[index] >= threshold)
        if mask:
            rows[position].append({
                'player_id': player['id'], 'name': snapshot.name(player),
                'photo': snapshot.photo_code(player), 'code': snapshot.team_code(player),
                'rates': rates, 'mask': mask, 'minutes': int(minutes),
            })
    for position in POSITIONS.values():
        if eligible[position] <= incomplete[position]:
            raise RequiredInput(f'No verified {position.lower()} with {MINUTES}+ minutes')
        rows[position].sort(key=_rank)

    mids, fwds = (sum(row['mask'] == 7 for row in rows[position])
                  for position in POSITIONS.values())
    coverage = sum(incomplete.values())
    scope = (f'{MINUTES}+ season minutes through GW{through}. '
             f'{coverage} players have incomplete coverage.' if coverage
             else f'{MINUTES}+ season minutes through GW{through}. Source: FPL Core match stats.')
    caption = '\n'.join((
        f'🎯 {TITLE} | GW{gw}',
        f'{mids} midfielders and {fwds} forwards clear all three per-90 thresholds.',
        'The board groups players by xG, shots and opposition-box touches.',
        f'{scope} Who makes your watchlist?',
        f'#FPL #GW{gw} #FPLVORTEX #PremierLeague',
    ))
    return Plan(slot.task, slot.edition, TITLE, caption, gw, [], [], 'sunday_chances', {
        'season': season, 'through': through, 'rows': rows, 'eligible': eligible,
        'incomplete': incomplete, 'sources': sources,
        'retrieved_at': datetime.now(ET).isoformat(),
        'data_at': snapshot.fetched_at.astimezone(ET).isoformat(),
    })


def preview():
    """Render current football data and write a review bundle without publishing."""
    import json
    from pathlib import Path

    from .autonomous_content import Evidence
    from .fpl import collect_snapshot
    from .sunday_chances_render import render_sunday_chances

    snapshot = collect_snapshot()
    now = datetime.now(ET)
    evidence = Evidence(snapshot, now)
    plan = build_sunday_chances(SUNDAY_CHANCES, snapshot, now, evidence.session)
    target = Path('output/sunday-chance-watch')
    render_sunday_chances(plan, target / 'sunday-chance-watch.png', evidence.session)
    (target / 'data.json').write_text(json.dumps(plan.extra, indent=2, ensure_ascii=False) + '\n',
                                     encoding='utf-8')
    (target / 'caption.txt').write_text(plan.caption + '\n', encoding='utf-8')
    print(plan.caption)


if __name__ == '__main__':
    preview()
