from dataclasses import replace
import pytest
from PIL import Image

from test_autonomous_engine import world
from vortex.autonomous_schedule import Slot
from vortex.autonomous_content import build
from vortex.editorial_inputs import RequiredInput


def slot():return Slot('task2', 'rank-booster', 6, 30)


def test_exactly_six_strictly_under_ten_sorted_by_official_forecast(world):
    s,now,e,_=world
    s.players[0].update(selected_by_percent='10.0',ep_next='99')
    plan=build(slot(),s,now,e)
    assert len(plan.players)==6 and plan.kind=='low_owned_six'
    assert all(float(p['selected_by_percent'])<10 for p in plan.players)
    values=[float(p['ep_next']) for p in plan.players]
    assert values==sorted(values,reverse=True)
    assert s.players[0] not in plan.players
    assert len(plan.caption)<=1024 and plan.caption.count('#')==4


def test_new_api_values_change_selection_without_named_players(world):
    s,now,e,_=world
    p=s.players[-1];p.update(selected_by_percent='0.2',ep_next='12.5',web_name='New API Leader')
    plan=build(slot(),s,now,e)
    assert plan.players[0]['id']==p['id'] and 'New API Leader' in plan.caption
    assert plan.extra['details'][str(p['id'])]['fpl_ep_next']==12.5


@pytest.mark.parametrize('field,value',[('ep_next',None),('ep_next','nan'),('ep_next','inf'),
                                       ('ep_next','0'),('ep_next','-1'),('selected_by_percent','nan'),
                                       ('status','i'),('status','d'),('chance_of_playing_next_round',0)])
def test_missing_invalid_or_unavailable_candidate_is_excluded(world,field,value):
    s,now,e,_=world;p=s.players[0]
    p.update(selected_by_percent='1',ep_next='99');p[field]=value
    plan=build(slot(),s,now,e)
    assert p not in plan.players


def test_insufficient_candidates_hold_instead_of_filling_with_high_ownership(world):
    s,now,e,_=world
    for p in s.players:p['selected_by_percent']='10'
    with pytest.raises(RequiredInput,match='Six available'):
        build(slot(),s,now,e)


def test_double_fixture_does_not_multiply_source_forecast(world):
    s,now,e,_=world;p=s.players[0];p.update(selected_by_percent='1',ep_next='12')
    f=dict(s.fixtures[0]);f.update(id=999,team_h=p['team'],team_a=2 if p['team']!=2 else 1)
    s=replace(s,fixtures=s.fixtures+[f])
    plan=build(slot(),s,now,e)
    assert plan.players[0]['id']==p['id']
    assert plan.extra['details'][str(p['id'])]['fpl_ep_next']==12
    assert len(plan.extra['details'][str(p['id'])]['fixtures'])==2


def test_missing_history_is_explicitly_missing_not_zero(world):
    s,now,e,_=world;e.recent=lambda p:[]
    plan=build(slot(),s,now,e)
    assert all(r['l3_points'] is None and r['l3_minutes'] is None for r in plan.extra['details'].values())


def test_six_cards_render_as_one_landscape_graphic(world,tmp_path,monkeypatch):
    from vortex import autonomous_render as renderer
    s,now,e,_=world;plan=build(slot(),s,now,e);seen=[]
    def assets(snapshot,p,*args):
        seen.append(p['id']);return Image.new('RGBA',(100,200),'blue'),Image.new('RGBA',(40,40),'gold')
    monkeypatch.setattr(renderer,'_assets',assets)
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE','@FPLVortexDailyBot')
    monkeypatch.setenv('FPL_DISCORD_HANDLE','@fplvortex')
    paths=renderer.render(plan,s,now,tmp_path/'six.png',session=object())
    assert len(paths)==1 and len(seen)==6
    with Image.open(paths[0]) as image:assert image.size==(1920,1080)


def test_ep_next_must_match_the_official_upcoming_gameweek(world):
    s,now,e,_=world
    s=replace(s,events=[dict(event,is_next=event['id']==11) for event in s.events])
    with pytest.raises(RequiredInput,match='ep_next event'):
        build(slot(),s,now,e)


def test_neon_six_cards_keep_dark_footer_and_mobile_resolution(world,tmp_path,monkeypatch):
    """Do not regress to the original low-contrast navy cards/white footer."""
    from vortex import autonomous_render as renderer
    s,now,e,_=world
    plan=build(slot(),s,now,e)
    monkeypatch.setattr(renderer,'_assets',lambda *args: (
        Image.new('RGBA',(100,200),'#336acc'),
        Image.new('RGBA',(40,40),'#e4f2ff')))
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE','@FPLVortexDailyBot')
    monkeypatch.setenv('FPL_DISCORD_HANDLE','@fplvortex')
    path=renderer.render(plan,s,now,tmp_path/'dynamic-neon.png',session=object())[0]
    with Image.open(path) as image:
        assert image.size==(1920,1080)
        # Studio is dark; the old white/paper footer is forbidden.
        assert max(image.getpixel((10,600))) < 105
        assert max(image.getpixel((1600,1052))) < 160
        # Contrast is supplied by bright cyan/violet borders, not dark text.
        pixels=image.convert('RGB')
        colors=pixels.getcolors(maxcolors=1920*1080)
        assert colors is not None
        neon=sum(count for count,color in colors
                 if color[2]>140 and (color[0]>110 or color[1]>170))
        assert neon>2000


def test_neon_renderer_uses_live_players_stats_and_gameweek_not_example_values():
    from pathlib import Path
    source=(Path(__file__).resolve().parents[1]/'vortex'/'low_owned_six.py').read_text()
    view=source.split('def render_low_owned(',1)[1]
    for demo in ('VUSKOVIC','AYARI','HILL','SILVA','MUHAREMOVIC','E.LE FEE',
                 'GW11','7.50','£5.3m','HUL(A)','NFO(H)'):
        assert demo not in view
    assert 'snapshot.name(p)' in view
    assert 'snapshot.price(p)' in view
    assert 'detail["fixtures"]' in view or "detail['fixtures']" in view
    assert "plan.gw" in view
    assert 'apply_footer(output)' not in view
