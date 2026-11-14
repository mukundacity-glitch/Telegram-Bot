from datetime import datetime, timedelta, timezone

from PIL import Image

from vortex.autonomous_render import render
from vortex.autonomous_schedule import SLOTS, RETIRED_EDITIONS, Slot, due_specials, publication_key, season_id
from vortex.chance_creators import build_chance_creators
from vortex.fpl import FplSnapshot


def test_chance_creators_uses_first_kickoff_and_gameweek_receipt():
    kickoff = datetime(2026, 11, 21, 12, 30, tzinfo=timezone.utc)
    trigger = kickoff - timedelta(hours=36)
    snapshot = FplSnapshot([], {}, [{'id': 11, 'deadline_time': (kickoff-timedelta(minutes=90)).isoformat()}],
                           [{'event': 11, 'kickoff_time': kickoff.isoformat()}], trigger)
    assert not any(s.edition == 'chance-creators' for s in
                   due_specials(snapshot, trigger-timedelta(seconds=1), {}))
    due = {slot.edition: slot for slot in due_specials(snapshot, trigger, {})}
    assert {'chance-creators', 'captaincy-comparison'} <= due.keys()
    key = publication_key(due['chance-creators'], trigger, 11, season_id(snapshot, trigger))
    assert not any(s.edition == 'chance-creators' for s in
                   due_specials(snapshot, trigger+timedelta(days=1), {key: {'status': 'delivered'}}))
    assert not {slot.edition for slot in SLOTS} & RETIRED_EDITIONS


def test_attributed_chances_per_90_and_branded_render(tmp_path, monkeypatch):
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE', '@FPLVortexDailyBot')
    monkeypatch.setenv('FPL_DISCORD_HANDLE', '@fplvortex')
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    snapshot = FplSnapshot([], {}, [{'id': 11, 'deadline_time': (now+timedelta(days=1)).isoformat()}],
                           [{'finished': True, 'kickoff_time': '2026-11-08T15:00:00Z'}], now)
    players = [{'id': str(i), 'player_name': f'Sample {i}', 'time': '450', 'team_title': 'Sample Club'}
               for i in range(1, 12)]
    league = {'players': players, 'dates': [{'id': '42', 'isResult': True, 'datetime': '2026-11-08 15:00:00'}]}
    counts = {'OpenPlay': 4, 'FromCorner': 2, 'SetPiece': 1, 'Penalty': 1, 'DirectFreekick': 1}
    match = {
        'rosters': {side: {p['id']: {'player_id': p['id'], 'player': p['player_name']} for p in players}
                    for side in ('h', 'a')},
        'shots': {'h': [{'player_assisted': 'Sample 1', 'situation': scenario}
                        for scenario, count in counts.items() for _ in range(count)], 'a': []},
    }

    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class Session:
        def get(self, url, **kwargs):
            return Response(match if url.endswith('/42') else league)

    plan = build_chance_creators(Slot('task1', 'chance-creators', 0), snapshot, now, Session())
    assert plan.extra['rows'][0]['open'] == .8
    assert plan.extra['rows'][0]['set'] == .6
    assert '#GW11' in plan.caption
    path = render(plan, snapshot, now, tmp_path / 'creators.png', Session())[0]
    with Image.open(path) as image:
        assert image.size == (1920, 1080)
        image.verify()
