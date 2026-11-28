from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from PIL import Image
from vortex import weekly_chip_strategy as slot
from vortex.chip_strategy import CHIPS, fixture_targets
from vortex.weekly_chip_strategy_render import render, SIZE


def at(h,m=0):
    return datetime(2026,11,27,h,m,tzinfo=timezone.utc)


def test_schedule_requires_complete_inventory_and_predeadline_window():
    assert slot.choose_schedule(at(18,30),at(8),[]) is None
    r,p=slot.choose_schedule(at(18,30),at(8),[],inventory_verified=True)
    assert p+slot.WINDOW<=at(18,30)
    assert p-r-slot.WINDOW>=timedelta(hours=3)
    assert slot.choose_schedule(at(18,30),at(8),
                                [("busy",at(7),at(20))],inventory_verified=True) is None


def test_evidence_and_release_gate():
    expected={"season":"2026-27","gw":12,"deadline":at(18,30).isoformat()}
    r,p=slot.choose_schedule(at(18,30),at(8),[],inventory_verified=True)
    extra={"scope":expected,"retrieved_at":r.isoformat()}
    proof={"scope":expected,"research_at":r.isoformat(),"post_at":p.isoformat(),
           "checked_at":(r+timedelta(minutes=2)).isoformat(),"data_digest":slot.digest(extra)}
    assert slot.proof_valid(proof,expected,extra,p,[],inventory_verified=True)
    assert not slot.proof_valid(proof,expected,extra,p,[])
    assert not slot.proof_valid(proof,expected,extra,p+slot.WINDOW,[],inventory_verified=True)
    assert not slot.proof_valid(proof,expected,{**extra,"changed":True},p,[],inventory_verified=True)
    assert not slot.eligible(proof,expected,extra,p,[],{},inventory_verified=True,legacy_reconciled=True)


def test_fixture_targets_consider_all_official_clubs():
    snapshot=SimpleNamespace(teams={1:{"name":"Test A","short_name":"AAA"},
                                    2:{"name":"Test B","short_name":"BBB"}})
    players=[{"team":1} for _ in range(3)]
    fixtures=[[{"blank":False,"opponent":"BBB","fixture_id":10,"gw":12,
                "venue":"H","estimated_xpts":5.0}] for _ in players]
    rows=fixture_targets(snapshot,players,fixtures,False,all_clubs=True)
    assert len(rows)==1 and rows[0]["opponent"]=="Test B" and rows[0]["total"]==15


def test_reference_layout_png(tmp_path):
    weeks=[12,13]
    cards={chip:{"pick":None,"peak":None,"usage":None,"expires":19} for chip in CHIPS}
    rows={chip:[{"gw":gw,"xpts":None} for gw in weeks] for chip in CHIPS}
    plan=SimpleNamespace(kind=slot.EDITION,title="FPL CHIP STRATEGY",
        extra={"weeks":weeks,"span":"GW12–13","data_date":"27 Nov 2026",
               "cards":cards,"rows":rows,"targets":[],"forecast":"Unit test only",
               "retrieved_at":at(12).isoformat()})
    path=render(plan,SimpleNamespace(players=[]),tmp_path/"chip.png",None)
    with Image.open(path) as im:
        assert im.size==SIZE
        assert im.getpixel((0,600))==(8,45,37)
    with Image.open(path) as im:
        im.verify()
