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


def test_landscape_combines_all_groups_and_preserves_doubles(tmp_path,monkeypatch):
    from PIL import Image
    from vortex.autonomous_content import Plan
    from vortex import position_watch_render as renderer
    from vortex.comparison_board import text as draw_text
    from pathlib import Path
    players=[];cards={};groups={}
    next_id=1
    for pos,_,count in w.GROUPS:
        groups[str(pos)]=[]
        for _ in range(count):
            pid=next_id;next_id+=1
            players.append({"id":pid,"web_name":f"Test {pid}","element_type":pos})
            groups[str(pos)].append(pid)
            cards[pid]={"id":pid,"position":pos,"minutes":[90,85,90],
                "metrics":{"clean_sheets":2,"expected_goals_conceded":2.1,"saves":9,
                           "expected_goals":1.1,"expected_assists":0.7,"expected_goal_involvements":1.8},
                "ownership":12.5,"in":123456,"out":65432,"fixtures":[
                    {"gw":12,"blank":False,"opponent":"AAA","venue":"H","fdr":2},
                    {"gw":12,"blank":False,"opponent":"BBB","venue":"A","fdr":5},
                    {"gw":13,"blank":True,"opponent":"BLANK","venue":"","fdr":None},
                    *({"gw":gw,"blank":False,"opponent":"CCC","venue":"H","fdr":3} for gw in (14,15,16))]}
    plan=Plan("task2",w.EDITION,"Expected stats","",12,players,["MONITOR"]*13,
              "weekly_position_watch",{"cards":cards,"groups":groups})
    snap=SimpleNamespace(name=lambda p:p["web_name"],price=lambda p:"£5.5m")
    monkeypatch.setattr("vortex.autonomous_render._assets",lambda *a:(
        Image.new("RGBA",(120,180),"#358477"),Image.new("RGBA",(60,60),"#D9B66B")))
    recorded=[]
    def observe(draw,value,*a,**kw):
        recorded.append(str(value))
        return draw_text(draw,value,*a,**kw)
    monkeypatch.setattr(renderer,"text",observe)
    path=renderer.render_position_watch(plan,snap,tmp_path/"watch.png",object())
    with Image.open(path) as image:
        assert image.size==(1920,1080)
        image.verify()
    for _,label,_ in w.GROUPS:
        assert label in recorded
    assert recorded.count("AAA(H) 2")==13 and recorded.count("BBB(A) 5")==13
    assert recorded.count("BLANK")==13
    assert recorded.count("MONITOR")==13
    assert recorded.count("GW IN 123,456 · OUT 65,432")==13
