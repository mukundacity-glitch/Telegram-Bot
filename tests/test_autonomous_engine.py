from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,re
import pytest
from PIL import Image

from vortex.autonomous_schedule import SLOTS,BY_CRON,NEWS_CRONS,SPECIAL_CRONS,SPECIAL_EDITIONS,Slot,due_specials
from vortex.autonomous_content import build
from vortex.editorial_inputs import verified_feed,eo_for,RequiredInput
from vortex import autonomous_runner as runner
from vortex.syndication import publish_album
from test_publication_contract import snap


@pytest.fixture
def world():
    from dataclasses import replace
    s=snap();now=datetime.now(timezone.utc)
    teams={n:{'id':n,'code':n+2,'short_name':f'T{n}','name':f'Team {n}'} for n in range(1,5)}
    events=[{'id':n,'is_next':n==10,'finished':False,'deadline_time':(now+timedelta(days=(n-9)*7)).isoformat()} for n in range(10,15)]
    events += [{'id':n,'finished':True,'deadline_time':(now-timedelta(days=(10-n)*7)).isoformat()} for n in (7,8,9)]
    fixtures=[]
    for gw in range(10,15):
        for home,away in ((1,2),(3,4)):
            fixtures.append({'id':gw*10+home,'event':gw,'team_h':home,'team_a':away,'finished':False,
                             'kickoff_time':(now+timedelta(days=(gw-9)*7+1)).isoformat(),
                             'team_h_difficulty':2,'team_a_difficulty':3})
    fixtures.append({'id':90,'event':9,'team_h':1,'team_a':2,'finished':True,'kickoff_time':(now-timedelta(hours=5)).isoformat()})
    people=[]
    for pos in (1,2,3,4):
        for i in range(12):
            p=dict(s.players[0]);pid=pos*100+i
            p.update(id=pid,code=pid+1000,web_name=f'Player {pid}',element_type=pos,team=i%4+1,
                     now_cost=40+i*10+pos*2,selected_by_percent=str(1+i*2),ep_next=str(2+i*.25),transfers_in_event=1000+i,
                     transfers_out_event=200+i,saves=20,goals_scored=3,assists=2,expected_goal_involvements='2.25')
            people.append(p)
    s=replace(s,players=people,teams=teams,events=events,fixtures=fixtures,fetched_at=now)
    class Evidence:
        session=object()
        history={}
        def recent(self,p):return [{'round':n,'fixture':n*10+p['id'],'minutes':90,'total_points':p['id']%8+2,'expected_goal_involvements':'.5'} for n in (7,8,9)]
        def qualified(self,limit=16):return sorted(people,key=lambda p:p['id'],reverse=True)[:limit] if limit<30 else people
        def rank(self,p):return p['id']
    e=Evidence()
    feed={'gw':10,'generated_at':now.isoformat(),'model_version':'synthetic-unit-test-only',
          'methodology_url':'https://example.invalid/unit-test','eo_meta':{'gw':10,'population':'unit test','methodology':'synthetic'},
          'teams':{},'players':{}}
    for tid in teams:
        rows=[]
        for f in fixtures:
            if f['event']<10 or tid not in (f['team_h'],f['team_a']):continue
            home=f['team_h']==tid
            rows.append({'fixture_id':f['id'],'gw':f['event'],'venue':'H' if home else 'A',
                         'opponent_id':f['team_a'] if home else f['team_h'],
                         'attacking_fdr':1.5+tid*.2,'defensive_fdr':2.2+tid*.1,
                         'projected_goals':1.5,'clean_sheet_pct':35})
        feed['teams'][str(tid)]={'fixtures':rows}
    for p in people:
        feed['players'][str(p['id'])]={'eo':25,'fixtures':[{'fixture_id':r['fixture_id'],'gw':r['gw'],'xpts':4+p['id']%3} for r in feed['teams'][str(p['team'])]['fixtures']]}
    return s,now,e,feed


def test_original_news_and_additional_editions_never_share_a_clock_slot():
    from vortex.schedule import SLOT_CRONS
    from vortex.autonomous_schedule import CATCHUP_CRONS,OUTBOX_CRONS
    lanes=[set(SLOT_CRONS),NEWS_CRONS,SPECIAL_CRONS,CATCHUP_CRONS,OUTBOX_CRONS]
    for i,a in enumerate(lanes):
        for b in lanes[i+1:]:assert not a&b
    workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/telegram-daily.yml').read_text()
    crons=re.findall(r"- cron: '([^']+)'",workflow)
    assert len(crons)==len(set(crons))
    assert crons == ['43 5-22 * * *', '13 6-22 * * *']
    assert workflow.count('timezone: "America/New_York"') == 2
    assert 'python -m vortex.scheduled_dispatch' in workflow
    assert len(SLOTS) == 15
    assert 'vortex.combine_midfielder_posts' not in workflow
    assert 'deleteMessage' not in workflow


@pytest.mark.parametrize('name',sorted({s.edition for s in SLOTS}|set(SPECIAL_EDITIONS)-{'verified-press-availability','confirmed-price-changes'}))
def test_every_editorial_builder_is_executable_offline_without_chatgpt(world,name,monkeypatch,tmp_path):
    s,now,e,feed=world
    slot=next((slot for slot in SLOTS if slot.edition==name),Slot('task1',name,10,35))
    if name=='verified-press-availability':return
    if name=='confirmed-price-changes':return
    if name=='player-radar-comparison':
        s.events.extend({'id': n, 'finished': True} for n in (5, 6))
        monkeypatch.setattr('vortex.radar_comparison.get_history', lambda pid, session: [
            dict(round=n, minutes=90, total_points=5, goals_scored=1, assists=0,
                 expected_goals=.6, expected_assists=.2, bonus=1) for n in range(5, 10)
        ])
    if name=='availability-transfer-decisions':
        s.players[0].update(status='d',news='Test official availability flag',news_added=now.isoformat())
        # Existing source selector is covered separately with production schemas.
        from unittest.mock import patch
        with patch('vortex.autonomous_content.choose_news',return_value=[s.players[0]]):
            plan=build(slot,s,now,e,model=feed,research={'title':'Unit test question','url':'https://example.invalid/test'})
    else:
        plan=build(slot,s,now,e,model=feed,research={'title':'Unit test question','url':'https://example.invalid/test'})
    assert plan.edition==name and plan.gw==10
    assert len([w for w in plan.caption.split() if w.startswith('#')])==4
    assert len(plan.caption)<=1024
    if name == 'player-radar-comparison':
        from vortex.autonomous_render import render
        monkeypatch.setenv('FPL_TELEGRAM_HANDLE', '@FPLVortexDailyBot')
        monkeypatch.setenv('FPL_DISCORD_HANDLE', '@fplvortex')
        asset = Image.new('RGBA', (120, 120), '#5a9ac9')
        monkeypatch.setattr('vortex.radar_render._portrait', lambda *args: asset)
        monkeypatch.setattr('vortex.radar_render._media', lambda *args: asset)
        assert (slot.hour, slot.minute) == (10, 30)
        assert plan.players[0]['element_type'] == plan.players[1]['element_type']
        assert plan.extra['values'][0]['Points'] == 25
        assert plan.caption.splitlines()[1] == 'Last 5 GWs: 5–5 goals, 3.00–3.00 xG.'
        assert 'Next 5 GW avg FDR' in plan.caption
        assert len(plan.caption) <= 240
        assert [r['gw'] for r in plan.extra['fixtures'][0]] == list(range(10, 15))
        output, = render(plan, s, now, tmp_path / 'radar.png')
        with Image.open(output) as image:
            assert image.size == (1920, 1080)
            image.verify()
    if name=='vortex-captain':assert plan.labels[1]=='VORTEX CAPTAIN'
    if name=='four-midfielders':assert len(plan.players)==4 and plan.kind=='players'
    if name=='rank-booster':assert len(plan.players)==6
    if name=='market-verdict':assert len(plan.extra['groups'])==4
    if name=='market-trends-next-five':assert len(plan.players)==15


def test_imported_csv_not_accepted_as_fresh_verified_model(world):
    s,now,e,feed=world
    with pytest.raises(RequiredInput):verified_feed(s,now,payload={'sourceFile':'old-csv.csv','players':[]})
    feed['generated_at']=(now-timedelta(days=1)).isoformat()
    with pytest.raises(RequiredInput,match='stale'):verified_feed(s,now,payload=feed)


def test_ownership_is_not_effective_ownership(world):
    s,now,e,feed=world
    feed.pop('eo_meta')
    with pytest.raises(RequiredInput,match='captaincy-weighted'):eo_for(feed,s.players[0]['id'])


def test_specials_respect_completion_and_deadline(world):
    s,now,e,feed=world
    names={slot.edition for slot in due_specials(s,now,{})}
    assert names=={'market-trends-next-five'}
    s.events[-1]['finished']=False
    assert not due_specials(s,now,{})


def test_album_has_one_caption_per_platform_and_partial_retry_never_repeats(tmp_path):
    sent=[]
    class Telegram:
        def send_album(self,images,caption):sent.append(('telegram',caption));return [1,2,3,4]
    class Discord:
        fail=True
        def send_album(self,images,caption):
            if self.fail:
                from vortex.syndication import DeliveryRejected
                raise DeliveryRejected('temporary rejection')
            sent.append(('discord',caption));return 'id'
    d=Discord();images=[tmp_path/str(i) for i in range(4)];ledger=tmp_path/'receipts.json'
    with pytest.raises(RuntimeError,match='Partial delivery'):publish_album('one-edition',images,'one caption',ledger,Telegram(),d)
    d.fail=False
    publish_album('one-edition',images,'one caption',ledger,Telegram(),d)
    publish_album('one-edition',images,'one caption',ledger,Telegram(),d)
    assert sent==[('telegram','one caption'),('discord','one caption')]


def test_audit_art_is_never_enqueued_for_publication(world,tmp_path,monkeypatch):
    s,now,e,feed=world
    now = now.astimezone(runner.ET).replace(hour=2, minute=0)
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    def render(plan,snapshot,now,path,session):
        path.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(1920,1080),'navy').save(path)
        return [path]
    monkeypatch.setattr(runner,'render',render)
    slot=next(slot for slot in SLOTS if slot.edition=='form-minutes-targets')
    file,_,_=runner.stage(slot,s,now,e,model=feed,audit=True)
    assert file.is_relative_to(tmp_path/'output/autonomous-audit')
    assert not (tmp_path/'outbox').exists()


def test_special_identity_changes_between_seasons(world):
    from vortex.autonomous_schedule import publication_key
    _,now,_,_=world
    slot=Slot('task1','value-board',8,35)
    assert publication_key(slot,now,10,'2026-27') != publication_key(slot,now,10,'2027-28')


def test_market_eo_is_explicitly_unavailable_without_verified_source(world):
    from vortex.autonomous_render import _eo_label
    from types import SimpleNamespace
    s,_,_,feed=world
    plan=SimpleNamespace(extra={'model':feed})
    assert _eo_label(plan,s.players[0])=='25.0%'
    feed.pop('eo_meta')
    assert _eo_label(plan,s.players[0])=='Unavailable'


def test_album_lost_receipt_holds_instead_of_resending(tmp_path):
    calls=[]
    class Telegram:
        def send_album(self,images,caption):
            calls.append('telegram')
            raise RuntimeError('receipt lost after possible acceptance')
    class Discord:
        def send_album(self,images,caption):
            calls.append('discord');return 'confirmed'
    ledger=tmp_path/'receipts.json'
    for _ in range(2):
        with pytest.raises(RuntimeError,match='Partial delivery'):
            publish_album('album',[tmp_path/'a',tmp_path/'b'],'caption',ledger,Telegram(),Discord())
    assert calls==['telegram','discord']
    receipts=json.loads(ledger.read_text())
    assert all(r.get('telegram_album_pending') and r.get('discord_delivered') for r in receipts.values())


def test_delivery_validates_at_send_time_after_snapshot_fetch(world,tmp_path,monkeypatch):
    s,now,e,feed=world
    started=now-timedelta(seconds=10)
    monkeypatch.setattr(runner,'allowed',lambda when:True)
    monkeypatch.setattr(runner,'Evidence',lambda snapshot,when:e)
    monkeypatch.setattr(runner,'write_state',lambda *args:None)
    sent=[]
    # Fake a newly acknowledged delivery, not a receipt that existed before
    # the publisher was called. Reusing an old receipt is not a fresh post.
    monkeypatch.setattr(runner,'read_state',lambda path: ({
        'test-identity:page1':{'delivered':True,'discord_delivered':True}
    } if sent else {}) if path==runner.RECEIPTS else {})
    monkeypatch.setattr(runner,'stage',lambda *args,**kwargs:(runner.ROOT/'outbox/test.json','test-identity',1))
    def publish(when, **kwargs):
        assert when>=s.fetched_at
        sent.append(when)
        return 0
    monkeypatch.setattr(runner,'publish_outbox',publish)
    result=runner.run(now=started,snapshot=s,edition='vortex-captain')
    assert sent and result['confirmed_edition_deliveries']==1


def test_due_edition_hold_fails_actions_instead_of_reporting_published(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'argv', ['autonomous_runner'])
    monkeypatch.setattr(runner, 'run', lambda **kwargs: {
        'exit_code': 0, 'editions': [{'status': 'held', 'edition': 'captain-differential'}]})
    assert runner.main() == 1


def test_no_new_facts_is_not_a_false_delivery_failure(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'argv', ['autonomous_runner'])
    monkeypatch.setattr(runner, 'run', lambda **kwargs: {
        'exit_code': 0, 'editions': [{'status': 'no-new-facts'}]})
    assert runner.main() == 0
