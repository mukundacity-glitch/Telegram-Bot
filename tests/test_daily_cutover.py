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
    assert slots(post+timedelta(days=1))[1].minute==45
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
