from datetime import datetime, timedelta
from vortex.autonomous_schedule import ET, SLOTS, eligible_on, catchup_slots
from vortex.weekly_position_watch import research_due, publication_due
from vortex.outbox import retired_record
from vortex.graphic_numbers import CATALOG, ACTIVE_CATALOG, graphic_key

def test_monday_research_and_publication_windows():
    monday=datetime(2026,11,30,3,13,tzinfo=ET)
    post=monday.replace(hour=10,minute=30)
    slot=next(s for s in SLOTS if s.edition=="goalkeeper-striker-watch")
    assert research_due(monday) and not publication_due(monday)
    assert not research_due(monday-timedelta(minutes=1))
    assert not research_due(monday+timedelta(minutes=15))
    assert publication_due(post)
    assert slot not in catchup_slots(monday,{},12,limit=None)
    assert slot in catchup_slots(post,{},12,limit=None)
    for day in range(1,7):
        now=monday+timedelta(days=day,hours=1)
        assert not eligible_on(slot,now) and not publication_due(now) and not research_due(now)
        assert slot not in catchup_slots(now,{},12,limit=None)

def test_old_two_page_records_are_retired_and_number_is_vacant():
    assert retired_record({"edition":"striker-watch"})
    assert retired_record({"edition":"goalkeeper-striker-watch","facts":{"extra":{"pages":[]}}})
    assert not retired_record({"edition":"goalkeeper-striker-watch","facts":{"extra":{"combined_weekly":True}}})
    assert len(CATALOG)==51 and len(ACTIVE_CATALOG)==50
    assert CATALOG[4]=="goalkeeper-striker-watch" and "reserved-29" not in CATALOG
    assert graphic_key("goalkeeper-striker-watch",0,page=1) is None
