from datetime import datetime, timedelta
from vortex.autonomous_schedule import ET
from vortex.legacy_research_gap import WINDOWS, proof_valid

def test_existing_weekly_editions_require_advance_research_at_actual_post():
    for edition, (day, rh, rm, ph, pm) in WINDOWS.items():
        at = datetime(2026, 11, 30, ph, pm, tzinfo=ET) + timedelta(days=day)
        checked = at.replace(hour=rh, minute=rm)
        proof = {"date": at.date().isoformat(), "season": "2026-27", "gw": 12,
                 "checked_at": checked.isoformat()}
        assert proof_valid(edition, proof, "2026-27", 12, at)
        assert not proof_valid(edition, proof, "2026-27", 13, at)
        assert not proof_valid(edition, proof, "2026-27", 12, at-timedelta(minutes=1))
        proof["checked_at"] = (at-timedelta(minutes=179)).isoformat()
        assert not proof_valid(edition, proof, "2026-27", 12, at)
