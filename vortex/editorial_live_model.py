"""Live, fail-closed adapter for the user's UNMODIFIED Day 3 Phase 1–4 math.

This file invokes the exact vendored original Day 3 engine and verifies the
FPL Core GitHub blob checksums, finished match identities, and the currently
scheduled official FPL fixtures. It never manufactures effective ownership
or divides official FPL ep_next into fictional fixture-level player xPts.
No original Day 1, Day 2 or Day 3 repository is modified.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import math
import requests

from .editorial_inputs import RequiredInput


class _JsonClient:
    def __init__(self, session):
        self.session = session

    def get(self, url, required=True, timeout=8):
        response = self.session.get(url, timeout=timeout,
                                    headers={'Accept': 'application/json'})
        response.raise_for_status()
        return response.json()


def build_live_team_feed(snapshot, now, session=None):
    """Produce original VORTEX custom FDR and team/CS predictions, or hold.

    Every row is matched to an official fixture ID, club, GW and venue.
    The absence of a verified player xPts/EO model is not disguised.
    """
    from . import day3_fixture_forecast as day3

    if now.tzinfo is None or snapshot.fetched_at.tzinfo is None:
        raise RequiredInput('Official FPL source or calculation timestamp has no timezone')
    if not timedelta(0) <= now - snapshot.fetched_at <= timedelta(hours=3):
        raise RequiredInput('Official FPL snapshot is too old for new Day 3 calculations')
    gw = snapshot.gameweek()
    if gw not in range(1, 39) or len(snapshot.teams) != 20:
        raise RequiredInput('No trustworthy upcoming Gameweek or full official team list')
    horizon = [f for f in snapshot.fixtures if
               f.get('event') in range(gw, min(39, gw+5)) and
               f.get('finished') is not True]
    if not horizon or any(type(f.get('id')) is not int or
                          type(f.get('team_h')) is not int or
                          type(f.get('team_a')) is not int for f in horizon):
        raise RequiredInput('Official future fixtures are missing identities')
    boot = {'events': snapshot.events, 'teams': list(snapshot.teams.values()),
            'elements': snapshot.players}
    client = _JsonClient(session or requests.Session())
    try:
        with TemporaryDirectory(prefix='fpl-vortex-day3-') as directory:
            root = Path(directory)
            source = day3.refresh_fpl_core(
                boot, snapshot.fixtures, root, now, client)
            computed = day3.rebuild(
                boot, snapshot.fixtures, source, root, now)
            source_commit = source.name
    except (RuntimeError, ValueError, KeyError, TypeError, IndexError,
            requests.RequestException, OSError) as exc:
        # Preserve the fail-closed requirement. Never invent a forecast when
        # the original Day 3 source or FPL Core identity checks cannot pass.
        raise RequiredInput(
            'Original Day 3 / FPL Core verified forecast unavailable: '
            + type(exc).__name__) from exc

    by_id = {row['fixture_id']: row for row in computed}
    expected_ids = {f['id'] for f in horizon}
    if len(by_id) != len(computed) or not expected_ids.issubset(by_id):
        raise RequiredInput('Day 3 forecast lacks unique official next-five fixture IDs')

    teams = {str(team_id): {'fixtures': []} for team_id in snapshot.teams}
    for fixture in sorted(horizon, key=lambda f: (f.get('event'), f['id'])):
        row = by_id[fixture['id']]
        if (row['gameweek'] != fixture['event']
                or row['home_team_id'] != fixture['team_h']
                or row['away_team_id'] != fixture['team_a']):
            raise RequiredInput('Day 3 fixture/team/GW mismatch')
        goal_h, goal_a = row['model_lambda_home'], row['model_lambda_away']
        cs_h, cs_a = row['home_clean_sheet_probability'], row['away_clean_sheet_probability']
        if any(type(x) not in (int, float) or not math.isfinite(x)
               for x in (goal_h, goal_a, cs_h, cs_a)):
            raise RequiredInput('Day 3 projected goals and CS rates must be finite')
        if not (0 < goal_h <= 12 and 0 < goal_a <= 12 and
                0 <= cs_h <= 1 and 0 <= cs_a <= 1):
            raise RequiredInput('Day 3 fixture rates outside validated publishing range')
        for tid, opponent, venue, goal, cs in (
            (fixture['team_h'], fixture['team_a'], 'H', goal_h, cs_h),
            (fixture['team_a'], fixture['team_h'], 'A', goal_a, cs_a),
        ):
            teams[str(tid)]['fixtures'].append({
                'fixture_id': fixture['id'], 'gw': fixture['event'],
                'opponent_id': opponent, 'venue': venue,
                'attacking_fdr': round(day3.vx_phase4_attack_fdr(goal), 2),
                'defensive_fdr': round(day3.vx_phase4_defence_fdr(cs), 2),
                'projected_goals': round(float(goal), 2),
                'clean_sheet_pct': round(float(cs)*100, 2),
            })
    required_rows = len(horizon)*2
    if sum(len(item['fixtures']) for item in teams.values()) != required_rows:
        raise RequiredInput('Incomplete Day 3 forecast coverage of both fixture sides')
    return {
        'gw': gw, 'generated_at': now.isoformat(),
        'model_version': day3.CANONICAL_MODEL_VERSION,
        'methodology_url': (
            'https://github.com/mukundacity-glitch/FPL-VORTEX-AGENT/'
            'blob/main/models/day3_fixture_forecast.py'),
        'fpl_core_source_commit': source_commit,
        'source': 'VORTEX Day 3 Phase 1-4 + verified original FPL Core',
        'teams': teams, 'players': {},
        # Genuine captaincy-weighted EO and original per-fixture Day 1 xPts
        # remain unavailable unless provided by a separately verified source.
        'eo_meta': None,
        'player_forecast_source': 'unavailable',
    }
