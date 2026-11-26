from dataclasses import replace
from datetime import datetime, timezone, timedelta
from PIL import Image
import pytest
from test_autonomous_engine import world
from vortex.price_prediction_board import build_board, next_published_update, render_board, select_rows
from vortex.graphic_numbers import stamp, CATALOG
from vortex.editorial_inputs import RequiredInput

def populated(world):
    s,now,e,_=world
    players=[]
    for i,p in enumerate(s.players[:20]):
        pct = 70+i if i<10 else -(70+i)
        players.append(dict(p,price_change_calibrating=False,can_transact=True,
            price_change_percent=str(pct-1),price_change_hourly_rate=i*17,
            price_change_projections=[dict(offset=1,projected_percent="999",likelihood=5),
                dict(offset=0,projected_percent=str(pct),likelihood=3 if pct>0 else -3)]))
    return replace(s,players=players),e

def test_ranked_16_players_and_no_links(world):
    s,e=populated(world)
    board=build_board(s,next_published_update(s.fetched_at))
    assert len(board["rises"])==len(board["falls"])==8
    assert [r["projected"] for r in board["rises"]]==list(range(79,71,-1))
    assert [r["projected"] for r in board["falls"]]==list(range(-89,-81))
    assert len({r["player"]["id"] for side in ("rises","falls") for r in board[side]})==16
    assert "http" not in board["caption"]
    assert board["caption"].count("#")==6

def test_locked_and_uncalibrated_excluded(world):
    s,e=populated(world)
    update=next_published_update(s.fetched_at)
    s.players[9]["price_change_calibrating"]=True
    s.players[19]["price_change_locked_until"]=(update+timedelta(hours=1)).isoformat()
    a,b=select_rows(s,update)
    assert a[0]["projected"]==78 and b[0]["projected"]==-88
    s.players[8]["price_change_projections"]=[]
    s.players[7]["price_change_projections"]=[]
    with pytest.raises(RequiredInput):
        select_rows(s,update)

def test_published_clock_tracks_uk_dst():
    winter=datetime(2026,11,26,18,tzinfo=timezone.utc)
    summer=datetime(2027,5,1,18,tzinfo=timezone.utc)
    assert next_published_update(winter).astimezone(timezone.utc).hour==0
    assert next_published_update(summer).astimezone(timezone.utc).hour==23

def test_portrait_render_and_catalog_id(world,monkeypatch,tmp_path):
    s,e=populated(world)
    board=build_board(s,next_published_update(s.fetched_at))
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE","@FPLVortexDailyBot")
    monkeypatch.setenv("FPL_DISCORD_HANDLE","@fplvortex")
    asset=Image.new("RGBA",(100,140),"#5a9ac9")
    monkeypatch.setattr("vortex.matchup._image_from_url",lambda *a:asset)
    monkeypatch.setattr("vortex.matchup._media",lambda *a:asset)
    p=render_board(s,board,tmp_path/"price.png",e.session)
    stamp(p,"price-prediction")
    with Image.open(p) as im:
        assert im.size==(1080,1920)
        assert im.info["vortex_graphic_number"]=="16/55"
        im.verify()
    assert len(CATALOG)==55
    monkeypatch.setattr("vortex.matchup._image_from_url",lambda *a:None)
    missing = render_board(s,board,tmp_path/"missing.png",e.session)
    assert missing.exists()
    monkeypatch.setattr("vortex.matchup._media",lambda *a:None)
    with pytest.raises(RequiredInput,match="Authentic club crest"):
        render_board(s,board,tmp_path/"missing-crest.png",e.session)

def test_ownership_trend_is_measured_not_guessed(world):
    from vortex.price_prediction_board import ownership_snapshot, ownership_trend
    s,e=populated(world)
    p=s.players[0]
    previous=ownership_snapshot(s)
    previous["at"]=(s.fetched_at-timedelta(hours=1)).isoformat()
    previous["players"][str(p["code"])]=5.0
    p["selected_by_percent"]="5.2"
    assert ownership_trend(s,previous,p)==0.2
    assert ownership_trend(s,None,p) is None
    previous["at"]=(s.fetched_at-timedelta(days=2)).isoformat()
    assert ownership_trend(s,previous,p) is None

def test_official_clock_uses_exact_feed_not_midnight():
    from vortex.price_prediction_board import official_clock
    now=datetime(2026,11,26,21,tzinfo=timezone.utc)
    data={"game_config":{"settings":{"price_change_deadlines":["2026-11-26T23:45:00Z","2026-11-28T00:00:00Z"]},
        "status":{"price_change_last_updated":"2026-11-26T20:55:00Z"}}}
    deadline,updated=official_clock(data,now)
    assert deadline.hour==23 and deadline.minute==45
    assert updated.minute==55
    with pytest.raises(RequiredInput):
        official_clock({},now)
    with pytest.raises(RequiredInput):
        official_clock(data,now+timedelta(hours=1))
    data["game_config"]["status"]["price_change_last_updated"]=now.isoformat()
    data["game_config"]["settings"]["price_change_deadlines"][0]="2026-11-26T20:59:00Z"
    with pytest.raises(RequiredInput):
        official_clock(data,now)

def test_legacy_edition_retired_and_only_new_catalog_entry():
    from vortex.autonomous_schedule import RETIRED_EDITIONS, SLOTS
    from vortex.graphic_numbers import CATALOG
    assert 'confirmed-price-changes' in RETIRED_EDITIONS
    assert all(s.task != 'price_changes' for s in SLOTS)
    assert CATALOG[15] == 'price-prediction'
    assert 'confirmed-price-changes' not in CATALOG
    assert len(CATALOG) == 55


def test_dynamic_clock_respects_existing_schedule(world, monkeypatch):
    from dataclasses import replace
    from vortex.price_prediction_board import opportunity
    from vortex.autonomous_schedule import publication_key
    from vortex import autonomous_schedule, schedule
    s, _, _, _ = world
    now = datetime(2026,11,26,23,0,tzinfo=timezone.utc)
    config={"settings":{"price_change_deadlines":["2026-11-27T00:00:00Z"]},
            "status":{"price_change_last_updated":"2026-11-26T22:55:00Z"}}
    s=replace(s,fetched_at=now,game_config=config)
    monkeypatch.setattr(autonomous_schedule,'special_triggers',lambda *_: [])
    slot,info=opportunity(s,now,{})
    assert slot is None and info['status']=='skipped-schedule-conflict'
    assert 'review' in {name for name,_ in info['conflicts']}
    monkeypatch.setattr(autonomous_schedule,'SLOTS',())
    monkeypatch.setattr(schedule,'SLOT_HOURS',{})
    slot,info=opportunity(s,now,{})
    assert info['status']=='due'
    assert slot.price_update_at=='2026-11-27T00:00:00+00:00'
    key=publication_key(slot,now,12,'2026-27')
    assert publication_key(slot,now,13,'2026-27')==key
    assert opportunity(s,now,{key:{'status':'delivered'}})[1]['status']=='closed'
    assert opportunity(s,now+timedelta(minutes=15),{})[1]['status']=='missed-window'

def test_outbox_rejects_all_old_price_task_paths_and_deduplicates_update(tmp_path):
    from test_chatgpt_outbox import record, NOW
    from vortex.outbox import validate, retired_record
    item=record(tmp_path)
    item.update(task='price_changes', edition='confirmed-price-changes')
    with pytest.raises(ValueError,match='Retired'):
        validate(item,tmp_path,NOW)
    item['edition']='old-price-report'
    assert retired_record(item)
    with pytest.raises(ValueError,match='Retired'):
        validate(item,tmp_path,NOW)
    update=NOW+timedelta(hours=1)
    item.update(edition='price-prediction', deadline=update.isoformat(),
                facts={'update_at':update.isoformat(),'source_updated_at':NOW.isoformat(),'projected':99})
    first=validate(item,tmp_path,NOW)[0]
    item['facts']['projected']=101
    item['gameweek']=11
    assert validate(item,tmp_path,NOW)[0]==first
    with pytest.raises(ValueError,match='one-hour'):
        validate(item,tmp_path,NOW+timedelta(minutes=15))
