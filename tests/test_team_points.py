from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from PIL import Image

from vortex.autonomous_schedule import SERIES
from vortex.editorial_inputs import RequiredInput
from vortex.fpl import FplSnapshot
from vortex.team_points import build_team_points
from vortex.team_points_render import render_team_points


def test_board_uses_exact_fixture_join_and_shared_match_window(monkeypatch, tmp_path):
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    played = now - timedelta(days=1)
    snap = FplSnapshot([], {1: {'name': 'Home', 'short_name': 'HOM', 'code': 55},
                            2: {'name': 'Away', 'short_name': 'AWY', 'code': 66}},
                       [{'id': 1, 'finished': True, 'deadline_time': played.isoformat()},
                        {'id': 2, 'deadline_time': (now+timedelta(days=1)).isoformat()}],
                       [{'event': 1, 'finished': True, 'id': 100, 'kickoff_time': played.isoformat(),
                         'team_h': 1, 'team_a': 2, 'team_h_score': 2, 'team_a_score': 0}], now)
    body = ('finished,kickoff_time,home_team,away_team,home_score,away_score,'
            'home_expected_goals_xg,away_expected_goals_xg\n'
            f'True,{played.isoformat()},55,66,2,0,1.2,1.2\n')

    class Session:
        def get(self, url, **kwargs):
            assert '2026-2027/By%20Tournament/Premier%20League/GW1' in url
            return SimpleNamespace(text=body, raise_for_status=lambda: None)

    slot = SERIES
    assert (slot.hour, slot.minute) == (12, 30)
    plan = build_team_points(slot, snap, now, Session())
    home, away = plan.extra['teams']
    assert [home['actual'], away['actual']] == [3, 0]
    assert home['expected'] == away['expected']
    assert 1 < home['expected'] < 1.5
    assert len(plan.caption.splitlines()) == 5
    crest = Image.new('RGBA', (100, 100), '#e19a47')
    monkeypatch.setattr('vortex.team_points_render._media', lambda *args: crest)
    with Image.open(render_team_points(plan, tmp_path/'points.png', Session())) as image:
        assert image.size == (1080, 1920)
        image.verify()
    body = body.replace('55,66,2,0', '55,66,3,0')
    with pytest.raises(RequiredInput, match='score does not match'):
        build_team_points(slot, snap, now, Session())
