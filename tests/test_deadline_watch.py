from dataclasses import replace
from datetime import datetime, timezone, timedelta
import re

import pytest
from PIL import Image

from test_autonomous_engine import world
from vortex.autonomous_schedule import SLOTS, BY_CRON, Slot
from vortex.autonomous_content import build
from vortex.deadline_watch import clock, ET, UK
from vortex.editorial_inputs import RequiredInput


def slot():
    return next(s for s in SLOTS if s.edition=='deadline-watch')


def test_replaces_only_old_420_press_slot_and_does_not_overlap():
    assert BY_CRON['29 16 * * *']==slot()
    assert '20 16 * * *' not in BY_CRON
    assert [(s.hour,s.minute) for s in SLOTS if s.task=='press_news']==[(10,20),(18,20)]


def test_deadline_watch_uses_snapshot_and_changes_with_data(world):
    s,now,e,_=world
    plan=build(slot(),s,now,e)
    assert plan.kind=='deadline' and len(plan.players)==4
    assert len(plan.caption)<=1024 and len(re.findall(r'#\w+',plan.caption))==4
    assert plan.title.startswith('GW10 DEADLINE WATCH')
    featured=plan.players[0]
    assert featured['element_type'] in (3,4)
    assert all(float(p['selected_by_percent'])<float(featured['selected_by_percent']) for p in plan.players[1:3])
    assert any(p['element_type']==2 for p in plan.players[1:3])
    featured.update(web_name='Fresh Name',now_cost=103)
    later=now+timedelta(days=2)
    changed=replace(s,events=[dict(ev,deadline_time=later.isoformat()) if ev['id']==10 else ev for ev in s.events])
    updated=build(slot(),changed,now,e)
    assert 'Fresh Name | £10.3m' in updated.caption
    assert updated.extra['deadline']==later.isoformat()
    assert 'Haaland' not in updated.caption


def test_flags_and_zero_chance_exclude_captains_and_refresh_current_club(world):
    s,now,e,_=world
    initial=build(slot(),s,now,e)
    flagged=initial.players[0]
    flagged.update(status='i',chance_of_playing_next_round=0,news='Official: unavailable.',team=2)
    other=initial.players[1]
    other.update(status='a',chance_of_playing_next_round=0)
    plan=build(slot(),s,now,e)
    assert flagged not in plan.players[:3] and other not in plan.players[:3]
    assert plan.players[-1]['id']==flagged['id']
    assert f"{s.name(flagged)} (T2): 0% chance" in plan.caption
    assert plan.extra['risks'][0]['team']==2


def test_blank_gameweek_and_insufficient_alternatives_hold(world):
    s,now,e,_=world
    class EmptyEvidence:
        def qualified(self,n):return []
    with pytest.raises(RequiredInput,match='captain candidate'):
        build(slot(),s,now,EmptyEvidence())


def test_no_unverified_captaincy_or_opponent_rank_claim(world):
    s,now,e,_=world
    plan=build(slot(),s,now,e)
    assert 'most-captained' not in plan.caption and 'rank-neutral' not in plan.caption
    assert '2nd-worst' not in plan.caption and '655k' not in plan.caption
    assert plan.extra['retrieved_at'].endswith(('-04:00','-05:00'))


def test_deadline_clocks_follow_nyc_and_london_dst():
    winter=datetime(2026,11,6,18,30,tzinfo=timezone.utc)
    summer=datetime(2026,8,6,17,30,tzinfo=timezone.utc)
    assert '1:30 PM EST' in clock(winter,ET)
    assert '6:30 PM GMT' in clock(winter,UK)
    assert '1:30 PM EDT' in clock(summer,ET)
    assert '6:30 PM BST' in clock(summer,UK)


def test_deadline_graphic_keeps_one_landscape_image_with_dynamic_heading(world,tmp_path,monkeypatch):
    from vortex import autonomous_render as renderer
    s,now,e,_=world
    s.players[0].update(status='i',chance_of_playing_next_round=0,news='Official test flag.')
    plan=build(slot(),s,now,e)
    monkeypatch.setattr(renderer,'_assets',lambda *args:(Image.new('RGBA',(150,250),'blue'),Image.new('RGBA',(50,50),'gold')))
    monkeypatch.setenv('FPL_ENRICHED_VISUALS_ENABLED','true')
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE','@FPLVortexDailyBot')
    monkeypatch.setenv('FPL_DISCORD_HANDLE','@fplvortex')
    paths=renderer.render(plan,s,now,tmp_path/'deadline.png',session=object())
    assert len(paths)==1
    with Image.open(paths[0]) as image:
        assert image.size==(1920,1080)


def test_missing_ownership_or_price_does_not_become_zero(world):
    s,now,e,_=world
    for p in s.players:
        p.pop('selected_by_percent',None)
        p.pop('now_cost',None)
    with pytest.raises(RequiredInput,match='captain candidate'):
        build(slot(),s,now,e)
