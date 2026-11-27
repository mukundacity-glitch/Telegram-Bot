from datetime import datetime,timedelta,timezone
import pytest
from vortex import pre_gameweek_availability as a

def test_four_hour_target_and_three_hour_elapsed_gap():
    kickoff=datetime(2026,11,27,20,tzinfo=timezone.utc)
    research,post=a.choose_schedule(kickoff,kickoff-timedelta(minutes=90),[])
    assert abs(kickoff-post-timedelta(hours=4))<=timedelta(minutes=30)
    assert post-research-a.WINDOW>=timedelta(hours=3)
    assert a.choose_schedule(kickoff,kickoff-timedelta(minutes=90),
        [("all reserved",kickoff-timedelta(hours=5),kickoff-timedelta(hours=3))]) is None

def test_stable_identity_and_research_gate():
    kickoff=datetime(2026,11,27,20,tzinfo=timezone.utc)
    research,post=a.choose_schedule(kickoff,kickoff-timedelta(minutes=90),[])
    row={"season":"2026-27","gw":12,"kickoff":kickoff.isoformat(),
         "deadline":(kickoff-timedelta(minutes=90)).isoformat(),
         "research_at":research.isoformat(),"post_at":post.isoformat()}
    proof={**row,"checked_at":research.isoformat(),"source_at":research.isoformat(),
           "tiers":{tier:list(range(i*5+1,i*5+6)) for i,tier in enumerate(a.TIERS)}}
    assert a.proof_valid(proof,row,post)
    assert not a.proof_valid(proof,row,post+a.WINDOW)
    assert not a.proof_valid({**proof,"checked_at":(post-timedelta(minutes=179)).isoformat()},row,post)
    assert not a.proof_valid({**proof,"tiers":{t:[1,2,3,4,5] for t in a.TIERS}},row,post)
    assert a.key("2026-27",12)!=a.key("2026-27",13)
    assert a.eligible(None,post,{}) is None
    with pytest.raises(ValueError,match="release"):
        a.validate_record({},post,post)
