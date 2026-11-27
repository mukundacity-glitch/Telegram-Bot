from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from vortex import position_watch as w
from vortex.editorial_inputs import RequiredInput

UTC=timezone.utc

def test_official_first_kickoff_not_deadline_or_fixed_weekday():
    s=SimpleNamespace(gameweek=lambda:12,events=[{"id":12,"deadline_time":"2026-11-27T18:30:00Z"}],
        fixtures=[{"event":12,"kickoff_time":"2026-11-28T12:30:00Z"},{"event":12,"kickoff_time":"2026-11-27T20:00:00Z"}])
    gw,kickoff,deadline=w.target(s)
    assert gw==12 and kickoff.hour==20 and deadline.hour==18
    s.fixtures[0]["kickoff_time"]=None
    with pytest.raises(RequiredInput):
        w.target(s)

def test_existing_heartbeat_and_elapsed_gap_and_busy_window():
    kickoff=datetime(2026,11,27,20,tzinfo=UTC)
    deadline=kickoff-timedelta(minutes=90)
    research,post=w.choose_schedule(kickoff,deadline,[])
    assert w.heartbeat(research) and w.heartbeat(post)
    assert timedelta(hours=7)<=kickoff-post<=timedelta(hours=8)
    assert post-(research+w.WINDOW)>=timedelta(hours=3)
    busy=[("reserved",kickoff-timedelta(hours=8),kickoff-timedelta(hours=7))]
    assert w.choose_schedule(kickoff,deadline,busy) is None

def test_early_kickoff_outside_existing_publishing_window_is_held():
    kickoff=datetime(2026,11,28,12,30,tzinfo=UTC)
    assert w.choose_schedule(kickoff,kickoff-timedelta(minutes=90),[]) is None

def test_research_proof_and_late_or_changed_kickoff_rejected():
    kickoff=datetime(2026,11,27,20,tzinfo=UTC)
    deadline=kickoff-timedelta(minutes=90)
    research,post=w.choose_schedule(kickoff,deadline,[])
    row={"season":"2026-27","gw":12,"kickoff":kickoff.isoformat(),"deadline":deadline.isoformat(),
         "research_at":research.isoformat(),"post_at":post.isoformat()}
    proof={**row,"checked_at":research.isoformat(),"source_at":research.isoformat(),
           "groups":{"1":[1,2],"2":[3,4,5,6],"3":[7,8,9,10],"4":[11,12,13]}}
    assert w.proof_valid(proof,row,post)
    assert not w.proof_valid(proof,row,post+w.WINDOW)
    assert not w.proof_valid(proof,{**row,"kickoff":(kickoff+timedelta(hours=1)).isoformat()},post)
    assert not w.proof_valid({**proof,"checked_at":(post-timedelta(minutes=179)).isoformat()},row,post)
    assert not w.proof_valid({**proof,"groups":{**proof["groups"],"4":[1,12,13]}},row,post)

def test_unverified_release_cannot_send():
    assert w.RELEASE_VERIFIED is False
    assert w.eligible(None,datetime.now(UTC),{}) is None
    with pytest.raises(ValueError,match="release"):
        w.validate_record({},datetime.now(UTC),datetime.now(UTC))

@pytest.mark.parametrize("value",[None,"",float("nan"),-1,True])
def test_missing_official_data_never_becomes_zero(value):
    with pytest.raises(RequiredInput):
        w.number(value)
