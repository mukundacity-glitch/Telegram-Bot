"""Saturday rankings built from completed FPL returns and a rank-tier sample."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from math import isfinite
import json
import re

from .editorial_inputs import RequiredInput
from .fpl import latest_completed_gw
from .publication_rules import five_gw_fixtures

API = 'https://fantasy.premierleague.com/api/'
OWNERSHIP_URL = 'https://www.fantasyfootballpundit.com/fpl-effective-ownership/'
POSITIONS = {1: 'GK', 2: 'DEF', 3: 'MID', 4: 'FWD'}


def _round_stats(session, url):
    response = session.get(url, timeout=(8, 18))
    response.raise_for_status()
    elements = response.json()['elements']
    rows = {}
    for row in elements:
        stats = row['stats']
        values = tuple(stats[key] for key in ('minutes', 'bonus', 'total_points'))
        if row['id'] in rows or any(type(value) is not int for value in values):
            raise RequiredInput('Invalid official gameweek player stats')
        rows[row['id']] = values
    if len(rows) < 100:
        raise RequiredInput('Incomplete official gameweek player stats')
    return rows


def build_bonus(slot, snapshot, session):
    from .autonomous_content import Plan

    through = latest_completed_gw(snapshot)
    if through is None:
        raise RequiredInput('No completed gameweek for awarded bonus points')
    weeks = list(range(1, through + 1))
    if not all(any(e.get('id') == week and e.get('finished') is True for e in snapshot.events)
               and all(f.get('finished') is True for f in snapshot.fixtures if f.get('event') == week)
               for week in weeks):
        raise RequiredInput('Incomplete completed-gameweek sequence for bonus points')
    sources = [f'{API}event/{week}/live/' for week in weeks]
    with ThreadPoolExecutor(max_workers=6) as workers:
        rounds = list(workers.map(lambda url: _round_stats(session, url), sources))
    leaderboard = []
    for player in snapshot.players:
        if player.get('team') not in snapshot.teams or player.get('element_type') not in POSITIONS:
            continue
        returns = [stats.get(player['id'], (0, 0, 0)) for stats in rounds]
        minutes, bonus, points = map(sum, zip(*returns))
        if minutes >= 450 and bonus > 0:
            timeline = [value if played else None for played, value, _ in returns[-10:]]
            leaderboard.append((player, bonus, points, timeline))
    leaderboard.sort(key=lambda row: (-row[1], -row[2], row[0]['id']))
    leaders = leaderboard[:10]
    if len(leaders) != 10:
        raise RequiredInput('Fewer than ten qualified bonus leaders')
    players = [row[0] for row in leaders]
    lines = [f'→ {snapshot.price(p)} {snapshot.name(p)} · {bonus}' for p, bonus, _, _ in leaders]
    keepers = [snapshot.name(p) for p in players if p['element_type'] == 1]
    lead, runner = leaders[:2]
    lead_note = (f'{snapshot.name(lead[0])} tops the board with {lead[1]} bonus points.'
                 if lead[1] == runner[1] else
                 f'{snapshot.name(lead[0])} leads {snapshot.name(runner[0])} by {lead[1] - runner[1]} bonus points.')
    keeper_note = (f'{keepers[0]} is the only goalkeeper in the top ten.' if len(keepers) == 1 else
                   f'Goalkeepers in the top ten: {len(keepers)}.')
    caption = '\n'.join(['🚨 FPL Bonus Magnets', f'Most bonus points so far · GW1–GW{through}',
                         *lines, lead_note, keeper_note, '#FPL #FPLVortex #BonusPoints #FantasyPL'])
    return Plan(slot.task, slot.edition, 'FPL Bonus Magnets', caption, through, players, [],
                'saturday_bonus', {'rows': [{'total': bonus, 'timeline': timeline}
                                            for _, bonus, _, timeline in leaders],
                                   'weeks': weeks[-10:], 'sources': sources})


def _ownership_payload(html, expected_gw):
    stamp = re.search(r'>GW(\d+) updated<', html)
    sample_text = re.search(r'From(?:<!--\s*-->)?\s*<strong>([\d,]+)</strong>\s*teams', html)
    if not stamp or int(stamp[1]) != expected_gw or not sample_text:
        raise RequiredInput('Current gameweek rank-tier ownership is not yet available')
    sample = int(sample_text[1].replace(',', ''))
    if not 50_000 <= sample <= 100_000:
        raise RequiredInput('Top 100k ownership sample is not ready')

    decoder = json.JSONDecoder()
    for push in re.finditer(r'self\.__next_f\.push\(', html):
        chunk, _ = decoder.raw_decode(html[push.end():])
        if len(chunk) < 2 or not isinstance(chunk[1], str) or '"owned_pct"' not in chunk[1]:
            continue
        for field in re.finditer(r'"rows":\s*\[', chunk[1]):
            rows, _ = decoder.raw_decode(chunk[1][field.end()-1:])
            if rows and all(isinstance(row, dict) and {'owned_pct', 'player_code'} <= row.keys()
                            for row in rows):
                if len(rows) < 100:
                    break
                return sample, rows
    raise RequiredInput('Complete squad-ownership table could not be read')


def build_ownership(slot, snapshot, now, session):
    from .autonomous_content import Plan

    locked = [(e['id'], datetime.fromisoformat(e['deadline_time'].replace('Z', '+00:00')))
              for e in snapshot.events if e.get('deadline_time')]
    available = [item for item in locked if item[1] <= now]
    if not available or not snapshot.gameweek():
        raise RequiredInput('Current ownership gameweek or future FDR not verified')
    gw, deadline = max(available, key=lambda item: item[1])
    if now - deadline < timedelta(hours=4):
        raise RequiredInput('Waiting for the Top 100k ownership sample')
    response = session.get(OWNERSHIP_URL, timeout=(8, 18))
    response.raise_for_status()
    sample, fetched = _ownership_payload(response.text, gw)
    players_by_code = {p['code']: p for p in snapshot.players if p.get('code')}
    ranking = []
    seen = set()
    for row in fetched:
        code = int(row['player_code'])
        pct = float(row['owned_pct'])
        if code in seen or not isfinite(pct) or not 0 <= pct <= 100:
            raise RequiredInput('Invalid squad ownership values in the rank sample')
        seen.add(code)
        ranking.append((code, pct))
    ranking.sort(key=lambda item: (-item[1], item[0]))
    top = ranking[:10]
    if any(code not in players_by_code for code, _ in top):
        raise RequiredInput('Ownership leaders could not be joined to official FPL identities')
    players = [players_by_code[code] for code, _ in top]
    rows = [{'ownership': pct, 'fixtures': five_gw_fixtures(snapshot, p)}
            for p, (_, pct) in zip(players, top)]
    weeks = sorted({fixture['gw'] for row in rows for fixture in row['fixtures']})
    if not weeks:
        raise RequiredInput('Official fixtures missing for the ownership board')
    lines = [f'{i}. {snapshot.name(p)} – {pct:.1f}%' for i, (p, (_, pct)) in enumerate(zip(players, top), 1)]
    caption = '\n'.join(['Top 100k Ownership', f'10 most-owned players · GW{gw} · {sample:,} squads sampled',
                         *lines, 'How many of the 10 do you own? 👇',
                         '#FPL #FPLVortex #FPLOwnership #FantasyPL'])
    return Plan(slot.task, slot.edition, 'Top 100k Ownership', caption, gw, players, [],
                'saturday_ownership', {'rows': rows, 'weeks': weeks, 'sample': sample,
                                       'sources': [OWNERSHIP_URL]})
