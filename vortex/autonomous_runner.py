"""GitHub-only data → editorial rules → PNG → caption → dual receipts.

Original news/legacy dispatchers are retained and use different clock slots.
No scheduled ChatGPT execution, chat model, or OpenAI key is used here.
"""
import argparse
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,os

from PIL import Image
from .bot import ROOT,STATE,read_state,write_state
from .fpl import collect_snapshot,price_snapshot,upcoming_deadline
from .autonomous_schedule import SLOTS,NEWS_CRONS,SPECIAL_CRONS,SPECIAL_EDITIONS,Slot,due_specials,slot_for,publication_key,season_id,ET
from .autonomous_content import build,Evidence
from .autonomous_render import render
from .editorial_inputs import RequiredInput,NoUpdate
from .publishing_window import allowed
from .outbox import validate,run as publish_outbox,RECEIPTS

STATE_FILE=STATE/'autonomous_editions.json'
AUDIT=ROOT/'output/autonomous-audit.json'


def canonical(value):
    if isinstance(value,dict):
        return {k:canonical(v) for k,v in value.items() if k not in {
            'generated_at','retrieved_at','fetched_at','computed_at','data_at','caption','title','kicker','footer'}}
    if isinstance(value,(list,tuple)):return [canonical(v) for v in value]
    return value


def facts(plan,snapshot,evidence):
    keys=('id','code','team','element_type','now_cost','selected_by_percent','status','news',
          'minutes','total_points','form','expected_goals','expected_assists')
    return {'players':[{k:p.get(k) for k in keys}|{'recent':evidence.recent(p)} for p in plan.players],
            'edition':plan.edition,'extra':canonical(plan.extra or {}),'fixtures':[
                f for f in snapshot.fixtures if f.get('event') in range(plan.gw,plan.gw+5)
                and any(p['team'] in (f.get('team_h'),f.get('team_a')) for p in plan.players)]}


def stage(slot,snapshot,now,evidence,*,model=None,prices=None,research=None,audit=False):
    plan=build(slot,snapshot,now,evidence,model,prices,research)
    base=ROOT/'output/autonomous-audit' if audit else ROOT
    output=base/'outbox/assets'/f'{now.astimezone(ET).date()}-{slot.edition}-GW{plan.gw}.png'
    pages=render(plan,snapshot,now,output,evidence.session)
    if plan.edition=='four-midfielders' and len(pages)!=1:
        raise RuntimeError('Four midfielders must fit ONE approved comparison graphic')
    for path in pages:
        with Image.open(path) as image:
            if image.size not in ((1920,1080),(1080,1920)):raise RuntimeError('Generated PNG dimensions failed QA')
            image.verify()
    deadline=upcoming_deadline(snapshot)
    if deadline is None or deadline<=datetime.now(timezone.utc):raise RuntimeError('Verified next deadline elapsed during rendering')
    season=season_id(snapshot,now)
    record={'task':slot.task,'edition':slot.edition,'season':season,'gameweek':plan.gw,
            'title':plan.title,'caption':plan.caption,'facts':facts(plan,snapshot,evidence),
            'generated_at':snapshot.fetched_at.isoformat(),'publish_at':now.isoformat(),
            'deadline':deadline.isoformat(),'pre_deadline':True,'qa_passed':True,
            'generation_owner':'github-actions','sources':[
                'https://fantasy.premierleague.com/api/bootstrap-static/',
                'https://fantasy.premierleague.com/api/fixtures/']+[
                f"https://fantasy.premierleague.com/api/element-summary/{p['id']}/" for p in plan.players],
            'images':[str(p.relative_to(base)) for p in pages]}
    if audit and not allowed(now):
        target=now.astimezone(ET).replace(hour=5,minute=20,second=0,microsecond=0)
        if target<now:target+=timedelta(days=1)
        record['publish_at']=target.isoformat()
    identity,_,_=validate(record,root=base)
    file=base/'outbox'/f'{now.astimezone(ET).date()}-{slot.edition}.json'
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
    return file,identity,len(pages)


def run(*,cron=None,edition=None,audit=False,now=None,snapshot=None,model=None,research=None):
    now=now or datetime.now(timezone.utc)
    if not audit and not allowed(now):
        return {'status':'deferred-outside-window','posted':0,'safe_to_delete_chatgpt_tasks':False}
    if cron in NEWS_CRONS and not audit and not edition:
        from .unified_runner import run as news
        result=news(now=now,max_posts=1)
        return {'lane':'existing-news','result':result}
    if not audit and not edition and slot_for(cron) is None and cron not in SPECIAL_CRONS:
        from .schedule import SLOT_CRONS
        if cron in SLOT_CRONS:
            from .bot import run as legacy
            return {'lane':'existing-legacy','exit_code':legacy('auto',cron)}
        return {'status':'no-edition-due','posted':0}
    snapshot=snapshot or collect_snapshot()
    state=read_state(STATE_FILE)
    slots=(list(SLOTS)+[Slot('task1',name,now.astimezone(ET).hour,35) for name in SPECIAL_EDITIONS]) if audit else (
        due_specials(snapshot,now,state) if cron in SPECIAL_CRONS else
        ([s for s in SLOTS if s.edition==edition][:1] or [Slot('task1',edition,now.astimezone(ET).hour,35)] if edition else [slot_for(cron)]))
    if not slots:return {'status':'no-gameweek-special-due','posted':0}
    if any(s is None for s in slots):raise ValueError('Unknown executable edition')
    evidence=Evidence(snapshot,now)
    rows=[]
    previous_prices=read_state(STATE/'prices.json')
    if not audit:
        # Keep a durable real snapshot even when no price movement is found.
        write_state(STATE/'prices.json',price_snapshot(snapshot))
    for slot in slots:
        key=publication_key(slot,now,snapshot.gameweek(),season_id(snapshot,now))
        if not audit and state.get(key,{}).get('status')=='delivered':
            rows.append({'edition':slot.edition,'status':'already-delivered'});continue
        if slot.task=='press_news':
            if audit:
                from .unified_runner import run as news
                result=news(dry_run=True,snapshot=snapshot,now=now,max_posts=1)
            else:
                from .unified_runner import run as news
                result=news(snapshot=snapshot,now=now,max_posts=1)
            rows.append({'edition':slot.edition,'status':'news-checked','result':result});continue
        try:
            file,identity,count=stage(slot,snapshot,now,evidence,model=model,prices=previous_prices,research=research,audit=audit)
            row={'task':slot.task,'edition':slot.edition,'status':'generated','file':str(file.relative_to(ROOT)),
                 'identity':identity,'pages':count,'caption_hashtags':4}
            if not audit:
                # Validation must use delivery time: the fresh snapshot was fetched
                # after the scheduler captured its original start timestamp.
                result=publish_outbox(datetime.now(timezone.utc))
                receipts=read_state(RECEIPTS)
                complete=all(receipts.get(f'{identity}:page{i+1}',{}).get('delivered') and
                             receipts.get(f'{identity}:page{i+1}',{}).get('discord_delivered') for i in range(count))
                row['status']='delivered' if complete else 'queued-or-partial'
                row['publisher_exit_code']=result
                state[key]=row;write_state(STATE_FILE,state)
            rows.append(row)
            if not audit and row['status']=='delivered':break
        except NoUpdate as exc:
            rows.append({'task':slot.task,'edition':slot.edition,'status':'no-new-facts','reason':str(exc)})
        except (RequiredInput,RuntimeError,ValueError,OSError,TypeError,KeyError) as exc:
            # Internal reasons are never printed on public art or captions.
            reason=str(exc) if isinstance(exc,RequiredInput) else type(exc).__name__
            row={'task':slot.task,'edition':slot.edition,'status':'held','reason':reason}
            rows.append(row)
            if not audit:state[key]=row;write_state(STATE_FILE,state)
    report={'generation_owner':'github-actions','chatgpt_required':False,'at':now.isoformat(),
            'gw':snapshot.gameweek(),'editions':rows,'production_attempted':not audit,
            'confirmed_edition_deliveries':sum(r.get('status')=='delivered' for r in rows),
            'generation_audit_passed':audit and all(r['status'] in ('generated','news-checked','no-new-facts') for r in rows),
            'safe_to_delete_chatgpt_tasks':False}
    AUDIT.parent.mkdir(parents=True,exist_ok=True)
    if audit:AUDIT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--edition',choices=sorted({s.edition for s in SLOTS}|set(SPECIAL_EDITIONS)))
    parser.add_argument('--audit-all',action='store_true')
    args=parser.parse_args()
    result=run(cron=os.getenv('SCHEDULED_CRON'),edition=args.edition,audit=args.audit_all)
    print(json.dumps(result,ensure_ascii=False))
    return 1 if result.get('exit_code',0) or any(r.get('status')=='queued-or-partial' for r in result.get('editions',[])) else 0


if __name__=='__main__':raise SystemExit(main())
