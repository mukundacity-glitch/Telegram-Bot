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


def test_legacy_research_must_finish_inside_its_reserved_window():
    for edition, (day, rh, rm, ph, pm) in WINDOWS.items():
        # Cover both standard and daylight time; elapsed lead alone is not
        # sufficient evidence of a conflict-free reserved research window.
        for monday in (datetime(2026, 11, 30, tzinfo=ET),
                       datetime(2027, 7, 5, tzinfo=ET)):
            at = (monday + timedelta(days=day)).replace(hour=ph, minute=pm)
            start = at.replace(hour=rh, minute=rm)
            proof = {"date": at.date().isoformat(), "season": "2026-27", "gw": 12}
            for offset, accepted in ((-1, False), (0, True), (14, True),
                                     (15, False), (60, False)):
                proof["checked_at"] = (start + timedelta(minutes=offset)).isoformat()
                assert proof_valid(edition, proof, "2026-27", 12, at) is accepted
