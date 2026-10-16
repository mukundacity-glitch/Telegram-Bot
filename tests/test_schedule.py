from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from vortex.schedule import SLOT_CRONS, captaincy_due, resolve_slot


def test_all_eight_slots_have_different_schedule():
    assert len(SLOT_CRONS) == 16
    assert len(set(SLOT_CRONS.values())) == 8
    assert resolve_slot("auto", "15 8 * * *", datetime.now(timezone.utc)) == "comparison"


def test_scheduled_cron_wins_over_delayed_execution_time():
    delayed = datetime(2026, 10, 16, 21, 1, tzinfo=timezone.utc)
    assert resolve_slot("auto", "30 6 * * *", delayed) == "elite"


def test_manual_auto_outside_exact_time_fails_closed():
    with pytest.raises(ValueError):
        resolve_slot("auto", None, datetime(2026, 10, 16, 20, 6, tzinfo=timezone.utc))


def test_captaincy_only_if_tomorrow_is_deadline_in_eastern():
    now = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)
    tomorrow = [{"id": 7, "deadline_time": "2026-10-17T10:00:00Z", "finished": False}]
    not_tomorrow = [{"id": 7, "deadline_time": "2026-10-18T10:00:00Z", "finished": False}]
    assert captaincy_due(tomorrow, now)
    assert not captaincy_due(not_tomorrow, now)


def test_dst_zone_is_eastern():
    summer = datetime(2026, 6, 1, tzinfo=ZoneInfo("America/New_York"))
    winter = datetime(2026, 12, 1, tzinfo=ZoneInfo("America/New_York"))
    assert summer.utcoffset().total_seconds() == -14400
    assert winter.utcoffset().total_seconds() == -18000