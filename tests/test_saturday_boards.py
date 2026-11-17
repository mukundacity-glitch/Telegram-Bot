from datetime import datetime
import json

import pytest

from vortex.autonomous_schedule import BONUS_MAGNETS, TOP_100K_OWNERSHIP, ET, eligible_on, slot_start
from vortex.editorial_inputs import RequiredInput
from vortex.saturday_boards import _ownership_payload


def test_saturday_boards_fill_only_the_selected_openings():
    saturday = datetime(2026, 11, 21, 12, tzinfo=ET)
    sunday = datetime(2026, 11, 22, 12, tzinfo=ET)
    for slot, clock in ((BONUS_MAGNETS, (16, 15)), (TOP_100K_OWNERSHIP, (22, 30))):
        assert eligible_on(slot, saturday)
        assert not eligible_on(slot, sunday)
        due = slot_start(slot, saturday)
        assert (due.hour, due.minute) == clock


def test_ownership_uses_only_a_complete_current_rank_sample():
    rows = [{'player_code': i, 'owned_pct': '80.14', 'eo_pct': '151.02'} for i in range(100)]
    frame = json.dumps([1, json.dumps({'rows': rows})])
    html = ('<span>GW11 updated</span><p>From<!-- --> <strong>50,000</strong> teams</p>'
            f'<script>self.__next_f.push({frame})</script>')
    assert _ownership_payload(html, 11) == (50_000, rows)
    with pytest.raises(RequiredInput):
        _ownership_payload(html, 12)
    with pytest.raises(RequiredInput):
        _ownership_payload(html.replace('50,000', '10,000'), 11)
