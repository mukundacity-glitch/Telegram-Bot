from datetime import datetime,timedelta
from PIL import Image
from vortex.autonomous_schedule import ET, MONDAY_DEFENCE, THURSDAY_ATTACKING_ZONES, SLOTS, catchup_slots, special_triggers
from vortex.monday_intelligence import research_due,publication_due
from vortex.outbox import retired_record
from vortex.graphic_numbers import CATALOG,ACTIVE_CATALOG,graphic_key

def test_monday_only_research_and_one_active_slot():
    at=datetime(2026,11,30,19,0,tzinfo=ET)
    assert research_due(at) and not publication_due(at)
    assert not research_due(at+timedelta(hours=1))
    assert publication_due(at+timedelta(hours=1))
    assert MONDAY_DEFENCE not in catchup_slots(at,{},12,limit=None)
    assert MONDAY_DEFENCE in catchup_slots(at+timedelta(hours=1),{},12,limit=None)
    for n in range(1,7):
        assert not research_due(at+timedelta(days=n))
        assert not publication_due(at+timedelta(days=n,hours=1))
        assert MONDAY_DEFENCE not in catchup_slots(at+timedelta(days=n,hours=1),{},12,limit=None)
    assert THURSDAY_ATTACKING_ZONES not in SLOTS
    assert retired_record({"edition":"thursday-attacking-zones"})
    assert retired_record({"edition":"gw-key-players"})
    assert retired_record({"edition":"monday-defence-watch"})
    assert not retired_record({"edition":"monday-defence-watch","facts":{"extra":{"combined_monday":True}}})
    assert CATALOG[13]=="monday-defence-watch" and len(CATALOG)==51 and len(ACTIVE_CATALOG)==51
    assert graphic_key("thursday-attacking-zones",3) is None and graphic_key("gw-key-players",0) is None
