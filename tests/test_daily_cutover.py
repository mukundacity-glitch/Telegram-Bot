from datetime import datetime, timedelta, timezone
import json
from vortex.daily_cutover import slots, research_window, post_window, proof_valid, day_key, claimed_ids
from vortex.autonomous_schedule import ET, season_id
from vortex.research_gap import verified_gap
from test_extra_posts import sample

def test_daily_exact_windows_and_four_hour_research():
    post = datetime(2026,11,27,5,30,tzinfo=ET)
    slot, desk = slots(post)
    assert post_window(slot, post) and not post_window(slot, post+timedelta(minutes=15))
    assert research_window(slot, post-timedelta(hours=4,minutes=1))
    row = {"edition":slot.edition,"season":"2026-27","gw":12,"date":post.date().isoformat(),
           "checked_at":(post-timedelta(hours=4,minutes=1)).isoformat(),
           "source_at":(post-timedelta(hours=4,minutes=2)).isoformat(),"player_ids":[1,2,3,4]}
    assert proof_valid(slot,row,"2026-27",12,post)
    assert not proof_valid(slot,row,"2026-27",13,post)
    row["checked_at"]=(post-timedelta(hours=3,minutes=59)).isoformat()
    assert not proof_valid(slot,row,"2026-27",12,post)
    assert (desk.hour,desk.minute)==(22,0)
    saturday = slots(post+timedelta(days=1))[1]
    assert (saturday.hour,saturday.minute)==(10,30)
    assert day_key(slot,post)==day_key(slot,post+timedelta(minutes=5))

def test_dedup_reserves_pending_and_confirmed_facts(tmp_path):
    snap=sample()
    now=snap.fetched_at
    record={"season":season_id(snap,now),"gameweek":snap.gameweek(),
            "facts":{"players":[{"id":1,"element_type":1}],"player_ids":[2]}}
    (tmp_path/"prior.json").write_text(json.dumps(record))
    assert claimed_ids(snap,now,tmp_path)=={1,2}
    record["gameweek"]=snap.gameweek()-1
    (tmp_path/"prior.json").write_text(json.dumps(record))
    assert claimed_ids(snap,now,tmp_path)==set()

def test_gap_is_elapsed_not_dst_wall_clock():
    start=datetime(2027,3,14,0,30,tzinfo=ET)
    end=datetime(2027,3,14,3,30,tzinfo=ET)
    assert not verified_gap(start.isoformat(),end)


def test_final_outbox_weekly_and_radar_gate_rejects_short_gap_and_late_delivery():
    import pytest
    from vortex.research_gap import verify_settled_or_weekly_record
    post = datetime(2026,11,28,20,0,tzinfo=ET)
    row = {"date":post.date().isoformat(),"season":"2026-27","gw":12,
           "verified":True,"checked_at":post.replace(hour=15,minute=28).isoformat(),
           "fetched_at":post.replace(hour=15,minute=25).isoformat()}
    item = {"edition":"saturday-fdr-grid","season":"2026-27","gameweek":12,"facts":{"research":row}}
    assert "2026-W48" in verify_settled_or_weekly_record(item,post,post)
    with pytest.raises(ValueError, match="three-hour"):
        verify_settled_or_weekly_record(item,post+timedelta(minutes=15),post)
    row["checked_at"]=post.replace(hour=16,minute=0).isoformat()
    with pytest.raises(ValueError, match="three-hour"):
        verify_settled_or_weekly_record(item,post,post)
    row["checked_at"]=post.replace(hour=15,minute=28).isoformat()
    row["fetched_at"]=post.replace(hour=14,minute=57).isoformat()
    with pytest.raises(ValueError, match="three-hour"):
        verify_settled_or_weekly_record(item,post,post)
    row["checked_at"]=(post-timedelta(minutes=179)).isoformat()
    with pytest.raises(ValueError, match="three-hour"):
        verify_settled_or_weekly_record(item,post,post)
    post=post.replace(hour=11,minute=30)
    row.update(completed_gw=11,checked_at=post.replace(hour=5,minute=58).isoformat())
    item.update(edition="player-radar-comparison",facts={"research":row,"extra":{"completed_gw":11}})
    assert ":GW11:" in verify_settled_or_weekly_record(item,post,post)
    item["facts"]["extra"]["completed_gw"]=10
    with pytest.raises(ValueError, match="three-hour"):
        verify_settled_or_weekly_record(item,post,post)


def test_new_daily_slots_have_nominal_spacing_and_existing_heartbeats():
    from vortex.autonomous_schedule import SLOTS, eligible_on, slot_start
    from vortex.schedule import SLOT_HOURS
    from vortex.telegram_spacing import GAP
    for day in range(23,30):
        now=datetime(2026,11,day,12,tzinfo=ET)
        daily=slots(now)
        others=[slot_start(s,now) for s in SLOTS if eligible_on(s,now)]
        others += [now.replace(hour=h,minute=m) for h,m in SLOT_HOURS.values()]
        assert all(abs(slot_start(s,now)-t)>=GAP for s in daily for t in others)
        assert all(slot_start(s,now).astimezone(timezone.utc).minute in (0,30) for s in daily)
