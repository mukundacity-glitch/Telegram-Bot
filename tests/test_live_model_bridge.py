"""Proof that the original Day 2/Day 3 data contracts never invent EO/xPts."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from vortex.autonomous_content import build
from vortex.autonomous_schedule import Slot
from vortex.editorial_inputs import RequiredInput, verified_feed, eo_for
from vortex.editorial_live_model import build_live_team_feed
from test_autonomous_engine import world  # shared synthetic official FPL snapshot fixture


def test_original_day3_model_is_imported_unchanged():
    from vortex import day3_fixture_forecast as day3
    assert day3.CANONICAL_MODEL_VERSION == "VORTEX-V1-PHASE4-POISSON-CS-FDR"
    assert day3.vx_phase4_attack_fdr(3.2) == pytest.approx(1.0)
    assert day3.vx_phase4_defence_fdr(__import__('math').exp(-0.4)) == pytest.approx(1.0)


def test_no_gw10_eo_does_not_block_official_fixture_target(world):
    snap, now, evidence, _ = world
    plan = build(Slot('three_daily','fixture-targets',7),snap,now,evidence,model=None)
    assert len(plan.players)==4
    assert all(plan.extra.get('eo',{}).get(str(p['id'])) is None for p in plan.players)
    assert 'EO N/A' in plan.extra['eo_disclosure']


def test_original_day3_team_math_reconstructs_all_fixture_sides(world,monkeypatch):
    from vortex import day3_fixture_forecast as day3
    snap, now, _, feed = world
    teams = {k:dict(v) for k,v in snap.teams.items()}
    for tid in range(5,21):
        teams[tid]={'id':tid,'code':tid+2,'short_name':str(tid),'name':str(tid)}
    snap = replace(snap,teams=teams)
    sha='a'*40
    checks=[]
    def fake_refresh(boot, official, root, checked_at, client):
        checks.append((len(boot['elements']),len(official)))
        return Path(root)/sha
    def fake_rebuild(boot, official, core, root, checked_at):
        assert core.name==sha
        return [
            {'fixture_id':fx['id'],'gameweek':fx['event'],
             'home_team_id':fx['team_h'],'away_team_id':fx['team_a'],
             'model_lambda_home':1.5,'model_lambda_away':1.2,
             'home_clean_sheet_probability':__import__('math').exp(-1.2),
             'away_clean_sheet_probability':__import__('math').exp(-1.5)}
            for fx in official if not fx.get('finished')]
    monkeypatch.setattr(day3,'refresh_fpl_core',fake_refresh)
    monkeypatch.setattr(day3,'rebuild',fake_rebuild)
    result = build_live_team_feed(snap,now)
    assert checks==[(len(snap.players),len(snap.fixtures))]
    assert result['model_version']==day3.CANONICAL_MODEL_VERSION
    assert result['fpl_core_source_commit']==sha
    assert result['players']=={} and result['eo_meta'] is None
    assert sum(len(v['fixtures']) for v in result['teams'].values())==20
    assert all(1<=x['attacking_fdr']<=5 and 0<=x['clean_sheet_pct']<=100
               for v in result['teams'].values() for x in v['fixtures'])
    checked=verified_feed(snap,datetime.now(timezone.utc),payload=result)
    with pytest.raises(RequiredInput,match='captaincy-weighted'):
        eo_for(checked,snap.players[0]['id'])


def test_day3_bad_fixture_join_stops_generation(world,monkeypatch):
    from vortex import day3_fixture_forecast as day3
    snap, now, _, _ = world
    snap = replace(snap,teams={tid:{'id':tid} for tid in range(1,21)})
    monkeypatch.setattr(day3,'refresh_fpl_core',lambda *args:Path('/tmp/'+('a'*40)))
    monkeypatch.setattr(day3,'rebuild',lambda *args:[{'fixture_id':101,
                'gameweek':10,'home_team_id':999,'away_team_id':2,
                'model_lambda_home':1.5,'model_lambda_away':1.0,
                'home_clean_sheet_probability':0.4,'away_clean_sheet_probability':0.2}])
    with pytest.raises(RequiredInput):
        build_live_team_feed(snap,now)


def test_no_future_or_stale_snapshots_are_accepted(world):
    snap, now, _, _ = world
    snap=replace(snap,teams={tid:{'id':tid} for tid in range(1,21)})
    old=replace(snap,fetched_at=now-timedelta(hours=4))
    with pytest.raises(RequiredInput,match='too old'):
        build_live_team_feed(old,now)


def test_official_fpl_projection_is_not_mislabelled_as_custom_model(world):
    snap,now,evidence,feed=world
    feed['players']={}
    plan=build(Slot('task1','value-board',12),snap,now,evidence,model=feed)
    assert len(plan.players)==12
    assert all(v['points_source']=='FPL EP_NEXT' for v in plan.extra['values'].values())
    assert 'FPL ep_next is official FPL forecast' in plan.extra['forecast_disclosure']
    # The first selected player's points are exactly the FPL ep_next value.
    p=plan.players[0]
    assert plan.extra['values'][str(p['id'])]['xpts']==pytest.approx(float(p['ep_next']))


def test_espn_name_alias_changes_only_the_verified_team_label():
    from vortex.editorial_live_model import _JsonClient
    from copy import deepcopy

    original={'events':[{'date':'2026-10-18T13:00:00Z',
               'competitions':[{'competitors':[
                  {'homeAway':'home','score':'2','team':{'displayName':'AFC Bournemouth'}},
                  {'homeAway':'away','score':'0','team':{'displayName':'Sunderland'}},
               ]}]}]}
    class Response:
        def raise_for_status(self):pass
        def json(self):return deepcopy(original)
    class Session:
        def get(self,url,timeout,headers):return Response()
    actual=_JsonClient(Session()).get('https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard')
    got=actual['events'][0]['competitions'][0]['competitors']
    assert got[0]['team']['displayName']=='Bournemouth'
    assert got[0]['score']=='2' and got[1]['score']=='0'
    assert actual['events'][0]['date']==original['events'][0]['date']
    unmodified=_JsonClient(Session()).get('https://example.invalid/data')
    assert unmodified==original
