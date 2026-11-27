from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from vortex import post_gameweek_zones as z
from vortex.editorial_inputs import RequiredInput

UTC=timezone.utc

def snapshot():
    return SimpleNamespace(teams={i:{} for i in range(20)},
        events=[{"id":i,"finished":True,"data_checked":True} for i in range(1,8)],
        fixtures=[{"id":i,"event":i,"finished":True,"kickoff_time":"2026-11-25T20:00:00Z"}
                  for i in range(1,8)])

def test_only_latest_five_officially_settled_rounds():
    s=snapshot()
    assert z.target(s)==[3,4,5,6,7]
    s.events[-1]["data_checked"]=False
    with pytest.raises(RequiredInput):
        z.target(s)
    s.events[-1]["data_checked"]=True
    s.fixtures[-1]["finished"]=False
    with pytest.raises(RequiredInput):
        z.target(s)

def test_no_fixed_weekday_and_three_hour_gap_with_reserved_windows():
    research=datetime(2026,11,27,12,13,tzinfo=UTC)
    post=z.choose_post(research,[])
    assert z.heartbeat(post) and post>=research+z.WINDOW+z.MIN_GAP
    later=z.choose_post(research,[("other",post,post+timedelta(hours=2))])
    assert later>=post+timedelta(hours=2)
    assert z.key("2026-27",7)!=z.key("2026-27",8)

def test_release_and_late_publication_gate():
    research=datetime(2026,11,27,12,13,tzinfo=UTC)
    post=z.choose_post(research,[])
    expected={"season":"2026-27","through":7,"weeks":[3,4,5,6,7],"fixtures_digest":"fixture"}
    proof={**expected,"checked_at":research.isoformat(),"source_at":research.isoformat(),
           "research_at":research.isoformat(),"post_at":post.isoformat(),"data_digest":"a"*64}
    assert z.proof_valid(proof,expected,post)
    assert not z.proof_valid(proof,expected,post+z.WINDOW)
    assert not z.proof_valid(proof,{**expected,"through":8},post)
    assert not z.proof_valid({**proof,"checked_at":(post-timedelta(minutes=179)).isoformat()},expected,post)
    assert z.eligible(None,post,{}) is None
    with pytest.raises(ValueError,match="release"):
        z.validate_record({},post,post)

def test_render_all_twenty_clubs_and_all_shares(tmp_path,monkeypatch):
    from PIL import Image
    from vortex import shot_origins_render as renderer
    from vortex.comparison_board import text
    rows=[{"code":i,"name":f"Club {i}","left":1.0,"centre":98.0,"right":1.0,"shots":100}
          for i in range(1,21)]
    plan=SimpleNamespace(extra={"rows":rows,"through":7,"weeks":[3,4,5,6,7]})
    monkeypatch.setattr(renderer,"_crest",lambda *a:None)
    labels=[]
    def observe(draw,value,*a,**kw):
        labels.append(str(value))
        return text(draw,value,*a,**kw)
    monkeypatch.setattr(renderer,"text",observe)
    path=renderer.render(plan,tmp_path/"zones.png",None)
    with Image.open(path) as image:
        assert image.size==(1920,1080)
        image.verify()
    assert labels.count("1%")==40 and labels.count("98%")==20
    assert labels.count("100")==20
