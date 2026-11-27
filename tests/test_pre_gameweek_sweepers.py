from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from vortex import pre_gameweek_sweepers as s
from vortex.editorial_inputs import RequiredInput

def test_rank_strict_coverage_and_true_rate_leader():
    snapshot=SimpleNamespace(fixtures=[{"id":1,"event":1,"finished":True},
        {"id":2,"event":1,"finished":True},{"id":3,"event":1,"finished":True}],
        name=lambda p:f"Keeper {p['id']}",team_code=lambda p:1,photo_code=lambda p:p["id"])
    players=[({"id":i,"element_type":1},{"minutes":270,"appearances":3,"sweeper_actions":i}) for i in range(1,14)]
    histories={i:[{"fixture":j,"round":1,"minutes":90} for j in (1,2,3)] for i in range(1,14)}
    rows,leader=s.rank(snapshot,players,histories,1)
    assert len(rows)==12 and rows[0]["id"]==leader["id"]==13
    assert rows[0]["rate"]==pytest.approx(13/3)
    players[-1][1]["incomplete_metrics"]=True
    with pytest.raises(RequiredInput,match="Missing"):
        s.rank(snapshot,players,histories,1)

def test_legacy_cohort_and_release_gate():
    now=datetime(2026,11,27,12,tzinfo=timezone.utc)
    expected={"season":"2026-27","gw":12,"through":11}
    assert s.legacy_claimed({"2026-27:GW11:task2:weekly-analysis:day3":{"identity":"receipt"}},expected)
    assert not s.legacy_claimed({},expected)
    assert s.key("2026-27",12)!=s.key("2026-27",13)
    assert s.eligible(None,now,{}) is None
    with pytest.raises(ValueError,match="release"):
        s.validate_record({},now,now)

def test_three_hour_proof_and_deadline():
    research=datetime(2026,11,27,12,13,tzinfo=timezone.utc)
    post=s.choose_post(research,[])
    expected={"season":"2026-27","gw":12,"through":11,"deadline":(post+timedelta(hours=2)).isoformat()}
    proof={**expected,"research_at":research.isoformat(),"checked_at":research.isoformat(),
        "source_at":research.isoformat(),"post_at":post.isoformat(),"data_digest":"a"*64}
    assert s.valid(proof,expected,post)
    assert not s.valid({**proof,"checked_at":(post-timedelta(minutes=179)).isoformat()},expected,post)
    late={**expected,"deadline":post.isoformat()}
    assert not s.valid({**proof,**late},late,post)

def test_portrait_renderer(tmp_path,monkeypatch):
    from PIL import Image
    from vortex import premium_sweeper_render as r
    rows=[{"id":i,"name":f"Keeper {i}","code":1,"value":i,"rate":i/3,"detail":f"{i/3:.2f}/90 · 270 min · 3 apps"} for i in range(12,0,-1)]
    plan=SimpleNamespace(extra={"rows":rows,"through":11,"rate_leader":rows[0],"minimum_minutes":220})
    monkeypatch.setattr(r,"_media",lambda *args:Image.new("RGBA",(60,60),"#52775E"))
    path=r.render(plan,tmp_path/"keepers.png",None)
    with Image.open(path) as im:
        assert im.size==(1080,1920)
        im.verify()
