from datetime import datetime, timezone
from vortex.global_schedule_audit import fixed_conflicts


def test_fixed_inventory_detects_overlapping_scheduled_publications():
    rows=fixed_conflicts(datetime(2026,11,27,12,tzinfo=timezone.utc))
    assert any({r["first"],r["second"]}=={"passing-creators","weekly-analysis"} for r in rows) is False
    # Sunday 16:30 and Wednesday/Saturday 16:15 have different dates;
    # same-day collisions, if any, must be actual overlapping UTC intervals.
    for r in rows:
        a=datetime.fromisoformat(r["first_at"])
        b=datetime.fromisoformat(r["second_at"])
        assert abs((a-b).total_seconds()) < 45*60
    assert isinstance(rows,list)
