from datetime import timedelta
from dataclasses import replace
from PIL import Image
import pytest

from test_autonomous_engine import world
from vortex.gw_key_players import discover_reference, select, build_key_players, render_key_players
from vortex.autonomous_schedule import Slot, publication_key, special_triggers, season_id, ET
from vortex.graphic_numbers import CATALOG, graphic_key
from vortex.editorial_inputs import RequiredInput

@pytest.mark.parametrize('gw,headline', [
    (1,'Five essential picks for Gameweek 1'),
    (12,'FPL GW12: Best 5 players'),
    (38,'Gameweek 38: Five must-have targets'),
])
def test_discovers_changed_titles(gw,headline):
    html = f'<a href="/blog-index/weekly-preview-{gw}/">{headline}</a>'
    html += '<a href="/blog-index/fpl-gw11-top-5-players/">Top 5 players GW11</a>'
    assert discover_reference(html,gw).endswith(f'/weekly-preview-{gw}/')
    assert discover_reference(html,2) is None

def test_rejects_other_categories_and_hosts():
    html = '<a href="/blog-index/other/">GW12 Top 5 differentials</a>'
    html += '<a href="https://example.com/blog-index/picks/">GW12 Top 5 picks</a>'
    assert discover_reference(html,12) is None

def test_five_tiers_and_stable_number(world):
    s,now,e,_ = world
    players = select(s)
    assert len({p['id'] for p in players}) == 5
    assert all(p['element_type'] in (3,4) and p['now_cost'] >= 75 for p in players[:2])
    assert all(p['element_type'] in (3,4) and p['now_cost'] < 75 for p in players[2:4])
    assert players[4]['element_type'] in (1,2)
    assert graphic_key('gw-key-players',0) is None
    assert CATALOG[-1] == 'retired-53' and len(CATALOG) == 53
    assert 'custom-outbox' not in CATALOG
    assert graphic_key('custom-outbox',0) is None
    assert graphic_key('unknown-news',0) is None
    plan = build_key_players(Slot('task1','gw-key-players',10,35),s,now,e)
    assert plan.gw == s.gameweek()
    assert len([line for line in plan.caption.splitlines() if line]) == 7
    assert plan.caption.startswith(f'🎯 GW{plan.gw} | FIVE ELITE FPL PICKS\n\n')
    assert '💎 Premium:' in plan.caption and '💰 Value:' in plan.caption and '🛡️ Defence:' in plan.caption
    from vortex.queue_retry import verified_caption
    assert verified_caption(plan.title, plan.caption) == plan.caption
    assert plan.caption.endswith(f'#FPL #GW{plan.gw} #FPLTips #FPLVORTEX')
    assert len(plan.extra['details']) == 5

def test_old_five_pick_trigger_is_retired(world):
    s,now,e,_ = world
    assert all(slot.edition != 'gw-key-players' for slot,_ in special_triggers(s,now))


def test_render_dark_and_missing_portrait_holds(world,monkeypatch,tmp_path):
    s,now,e,_ = world
    plan = build_key_players(Slot('task1','gw-key-players',10,35),s,now,e)
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE','@FPLVortexDailyBot')
    monkeypatch.setenv('FPL_DISCORD_HANDLE','@fplvortex')
    asset = Image.new('RGBA',(100,140),'#5a9ac9')
    monkeypatch.setattr('vortex.matchup._image_from_url',lambda *args: asset)
    monkeypatch.setattr('vortex.matchup._media',lambda *args: asset)
    output = render_key_players(plan,s,tmp_path/'key.png',e.session)
    with Image.open(output) as image:
        assert image.size == (1920,1080)
        assert max(image.convert('RGB').getpixel((10,500))) < 150
    with Image.open(output) as image:
        image.verify()
    monkeypatch.setattr('vortex.matchup._image_from_url',lambda *args: None)
    with pytest.raises(RequiredInput,match='Authentic'):
        render_key_players(plan,s,tmp_path/'missing.png',e.session)
