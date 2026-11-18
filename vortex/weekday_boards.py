"""Additional 8 PM editions sourced and rendered without publishing in previews."""
from datetime import datetime

from .autonomous_schedule import ET
from .editorial_inputs import RequiredInput

FPL = 'https://fantasy.premierleague.com/api/bootstrap-static/'
FIXTURES = 'https://fantasy.premierleague.com/api/fixtures/'
SET_PIECES = 'tuesday-set-piece-watch'
ROLES = ('corners_and_indirect_freekicks_order', 'direct_freekicks_order', 'penalties_order')


def set_piece_rows(snapshot):
    candidates = []
    for player in snapshot.players:
        minutes = player.get('minutes') or 0
        roles = tuple(player.get(field) for field in ROLES)
        if minutes < 270 or player.get('status') == 'u' or not any(type(n) is int and n > 0 for n in roles):
            continue
        club = snapshot.teams.get(player['team'])
        if not club or not club.get('code'):
            continue
        candidates.append((player, club, minutes, roles))
    candidates.sort(key=lambda row: (row[3][0] or 999, -row[2], row[0]['id']))
    if len(candidates) < 10:
        raise RequiredInput('Insufficient official set-piece roles for a verified shortlist')
    return [{
        'name': snapshot.name(player), 'club': club['short_name'],
        'code': club['code'], 'minutes': minutes, 'roles': roles,
    } for player, club, minutes, roles in candidates[:10]]


def _plan(slot, snapshot, now, title, lines, **extra):
    from .autonomous_content import Plan

    gw = snapshot.gameweek()
    if not gw:
        raise RequiredInput('No verified upcoming FPL gameweek')
    caption = '\n'.join((f'{title} | GW{gw}', *lines, f'#FPL #GW{gw} #FPLVORTEX #PremierLeague'))
    return Plan(slot.task, slot.edition, title, caption, gw, [], [], 'weekday_board', {
        'data_at': snapshot.fetched_at.astimezone(ET).isoformat(),
        'retrieved_at': now.astimezone(ET).isoformat(), **extra,
    })


def build_weekday_board(slot, snapshot, now, session):
    if slot.edition != SET_PIECES:
        raise RequiredInput(f'Unknown weekday board: {slot.edition}')
    rows = set_piece_rows(snapshot)
    featured = ', '.join(row['name'] for row in rows[:3])
    return _plan(slot, snapshot, now, 'SET-PIECE TAKERS', (
        f'Official corner and indirect free-kick shortlist: {featured}.',
        'Compare corner duties, direct free kicks and penalties by listed pecking order.',
        '270+ season minutes. Check recent starts and availability before transferring.',
    ), rows=rows, sources=[FPL])


def preview():
    """Generate images, data and copy without touching the outbox or sending posts."""
    import argparse
    import json
    from pathlib import Path

    from .autonomous_content import Evidence
    from .autonomous_render import render
    from .autonomous_schedule import EVENING_WATCH_SLOTS
    from .fpl import collect_snapshot

    parser = argparse.ArgumentParser()
    parser.add_argument('edition')
    args = parser.parse_args()
    slot = next(slot for slot in EVENING_WATCH_SLOTS if slot.edition == args.edition)
    snapshot = collect_snapshot()
    now = datetime.now(ET)
    evidence = Evidence(snapshot, now)
    plan = build_weekday_board(slot, snapshot, now, evidence.session)
    target = Path('output/weekday-previews') / slot.edition
    render(plan, snapshot, now, target / f'{slot.edition}.png', evidence.session)
    (target / 'data.json').write_text(json.dumps(plan.extra, ensure_ascii=False, indent=2) + '\n',
                                     encoding='utf-8')
    (target / 'caption.txt').write_text(plan.caption + '\n', encoding='utf-8')
    print(plan.caption)


if __name__ == '__main__':
    preview()
