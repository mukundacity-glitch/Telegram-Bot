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
from .autonomous_schedule import SLOTS,NEWS_CRONS,SPECIAL_CRONS,CATCHUP_CRONS,SPECIAL_EDITIONS,Slot,due_specials,catchup_slots,slot_for,publication_key,season_id,ET
from .autonomous_content import build,Evidence
from .autonomous_render import render
from .editorial_inputs import RequiredInput,NoUpdate
from .publishing_window import OPEN_MINUTE, allowed
from .outbox import validate,run as publish_outbox,RECEIPTS

STATE_FILE=STATE/'autonomous_editions.json'
AUDIT=ROOT/'output/autonomous-audit.json'
# Every editorial slot is already published at most once per Eastern day, so a
# per-run cap can only ever REFUSE a slot that is genuinely due. When GitHub
# delayed or dropped several heartbeats the cap silently starved the older
# approved slots, which is why catch-up days produced 3-5 posts instead of the
# whole due backlog. The daily slot receipts remain the real volume control.
MAX_PER_RUN=None


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


def stage(slot,snapshot,now,evidence,*,model=None,prices=None,research=None,audit=False,manual=False):
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
            'data_retrieval_at_et':snapshot.fetched_at.astimezone(ET).isoformat(),
            'graphic_generated_at_et':datetime.now(timezone.utc).astimezone(ET).isoformat(),
            'deadline':deadline.isoformat(),'pre_deadline':True,'qa_passed':True,
            'generation_owner':'github-actions','sources':[
                'https://fantasy.premierleague.com/api/bootstrap-static/',
                'https://fantasy.premierleague.com/api/fixtures/']+[
                f"https://fantasy.premierleague.com/api/element-summary/{p['id']}/" for p in plan.players]+(
                    ['https://github.com/olbauday/FPL-Core-Insights',
                     'https://github.com/mukundacity-glitch/FPL-VORTEX-AGENT/blob/main/models/day3_fixture_forecast.py']
                    if plan.extra and plan.extra.get('model') else []),
            'images':[str(p.relative_to(base)) for p in pages]}
    if audit and not allowed(now):
        hour, minute = divmod(OPEN_MINUTE, 60)
        target = now.astimezone(ET).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target<now:target+=timedelta(days=1)
        record['publish_at']=target.isoformat()
    identity,_,_=validate(record,root=base,allow_outside_window=manual)
    file=base/'outbox'/f'{now.astimezone(ET).date()}-{slot.edition}.json'
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
    return file,identity,len(pages)


def run(*,cron=None,edition=None,audit=False,due=False,manual=False,now=None,snapshot=None,model=None,research=None,catchup_limit=3):
    now=now or datetime.now(timezone.utc)
    if manual and not edition:
        raise ValueError('Manual delivery requires one explicitly selected edition')
    if not audit and not manual and not allowed(now):
        return {'status':'deferred-outside-window','posted':0,'safe_to_delete_chatgpt_tasks':False}
    if cron in NEWS_CRONS and not audit and not edition:
        from .unified_runner import run as news
        result=news(now=now,max_posts=1)
        return {'lane':'existing-news','result':result}
    if not audit and not edition and not due and slot_for(cron) is None and cron not in SPECIAL_CRONS and cron not in CATCHUP_CRONS:
        from .schedule import SLOT_CRONS
        if cron in SLOT_CRONS:
            from .bot import run as legacy
            return {'lane':'existing-legacy','exit_code':legacy('auto',cron)}
        return {'status':'no-edition-due','posted':0}
    snapshot=snapshot or collect_snapshot()
    state=read_state(STATE_FILE)
    if audit:
        slots=list(SLOTS)+[Slot('task1',name,now.astimezone(ET).hour,35) for name in SPECIAL_EDITIONS]
    elif cron in SPECIAL_CRONS and not edition:
        slots=due_specials(snapshot,now,state)
    elif edition:
        slots=[s for s in SLOTS if s.edition==edition][:1] or [Slot('task1',edition,now.astimezone(ET).hour,35)]
    else:
        # Time-based catch-up: post anything already due and not yet closed today,
        # whichever cron (or delayed run) happens to be executing.
        slots=catchup_slots(now,state,snapshot.gameweek(),season_id(snapshot,now),limit=catchup_limit)
    if not slots:return {'status':'no-edition-due' if not audit and not edition and cron not in SPECIAL_CRONS else 'no-gameweek-special-due','posted':0}
    if any(s is None for s in slots):raise ValueError('Unknown executable edition')
    evidence=Evidence(snapshot,now)
    rows=[]
    previous_prices=read_state(STATE/'prices.json')
    if not audit and not previous_prices:
        # First ever run only. Afterwards the baseline moves ONLY when the price
        # edition has been closed, so an overnight change is still detectable
        # at the price slot instead of being absorbed by an earlier hourly run.
        write_state(STATE/'prices.json',price_snapshot(snapshot))
    sent_now=0
    for slot in slots:
        key=publication_key(slot,now,snapshot.gameweek(),season_id(snapshot,now))
        if not audit and state.get(key,{}).get('status') in ('delivered','already-delivered'):
            rows.append({'edition':slot.edition,'status':'already-delivered'});continue
        if slot.task=='press_news':
            if audit:
                from .unified_runner import run as news
                result=news(dry_run=True,snapshot=snapshot,now=now,max_posts=1)
            else:
                from .unified_runner import run as news
                result=news(snapshot=snapshot,now=now,max_posts=1)
            rows.append({'edition':slot.edition,'status':'news-checked','result':result})
            if not audit:
                state[key]={'task':slot.task,'edition':slot.edition,'status':'checked','at':now.isoformat()};write_state(STATE_FILE,state)
            continue
        try:
            file,identity,count=stage(slot,snapshot,now,evidence,model=model,prices=previous_prices,research=research,audit=audit,manual=manual)
            row={'task':slot.task,'edition':slot.edition,'status':'generated','file':str(file.relative_to(ROOT)),
                 'identity':identity,'pages':count,'caption_hashtags':4}
            if not audit:
                previous_receipts=read_state(RECEIPTS)
                previously_complete=all(previous_receipts.get(f'{identity}:page{i+1}',{}).get('delivered')
                    and previous_receipts.get(f'{identity}:page{i+1}',{}).get('discord_delivered')
                    for i in range(count))
                # Validation must use delivery time: the fresh snapshot was fetched
                # after the scheduler captured its original start timestamp.
                if manual:
                    # Target the new verified graphic, never a stale queued edition.
                    result=publish_outbox(datetime.now(timezone.utc),manual=True,target_file=file)
                else:
                    # Only publish the newly verified, generated edition. Historical
                    # stale queue entries cannot starve the current scheduled post.
                    result=publish_outbox(datetime.now(timezone.utc),target_file=file)
                receipts=read_state(RECEIPTS)
                complete=all(receipts.get(f'{identity}:page{i+1}',{}).get('delivered') and
                             receipts.get(f'{identity}:page{i+1}',{}).get('discord_delivered') for i in range(count))
                # Never call an old receipt a fresh upload. Identical factual
                # content may retain the same identity across different days.
                row['status']=('already-delivered' if previously_complete and complete
                               else 'delivered' if complete else 'queued-or-partial')
                row['publisher_exit_code']=result
                row['attempts']=state.get(key,{}).get('attempts',0)+1
                state[key]=row;write_state(STATE_FILE,state)
                if complete and slot.task=='price_changes':write_state(STATE/'prices.json',price_snapshot(snapshot))
            rows.append(row)
            if not audit and row['status']=='delivered':
                sent_now+=1
                if MAX_PER_RUN is not None and sent_now>=MAX_PER_RUN:break
        except NoUpdate as exc:
            row={'task':slot.task,'edition':slot.edition,'status':'no-new-facts','reason':str(exc)}
            rows.append(row)
            if not audit:
                state[key]=row;write_state(STATE_FILE,state)
                if slot.task=='price_changes':write_state(STATE/'prices.json',price_snapshot(snapshot))
        except (RequiredInput,RuntimeError,ValueError,OSError,TypeError,KeyError) as exc:
            # Internal reasons are never printed on public art or captions.
            reason=str(exc) if isinstance(exc,RequiredInput) else type(exc).__name__
            row={'task':slot.task,'edition':slot.edition,'status':'held','reason':reason,
                 'attempts':state.get(key,{}).get('attempts',0)+1}
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
    parser.add_argument('--due', action='store_true', help='Process eligible daily editions already due')
    parser.add_argument('--manual', action='store_true', help='Publish exactly one selected, verified edition immediately')
    args=parser.parse_args()
    if args.manual and not args.edition:
        parser.error('--manual requires --edition')
    result=run(cron=os.getenv('SCHEDULED_CRON'),edition=args.edition,audit=args.audit_all,due=args.due,manual=args.manual)
    print(json.dumps(result,ensure_ascii=False))
    if args.manual:
        for row in result.get('editions',[]):
            status=row.get('status','unknown')
            edition_name=row.get('edition','unknown')
            if status=='delivered':
                print(f"::notice::MANUAL DELIVERY CONFIRMED: {edition_name}; Telegram and Discord receipts found")
            else:
                print(f"::warning::MANUAL POST NOT SENT: {edition_name} ({status}); see edition reason/receipts above")
    if args.manual and result.get('confirmed_edition_deliveries',0) == 0:
        print('::error::Manual run completed without a NEW verified Telegram + Discord upload')
        return 1
    # A generated graphic is not a published post. Surface a failed due edition
    # as a failed Actions run instead of reporting a misleading green success.
    failures = {'held', 'queued-or-partial'}
    return 1 if result.get('exit_code', 0) or any(
        row.get('status') in failures for row in result.get('editions', [])) else 0


if __name__=='__main__':raise SystemExit(main())
