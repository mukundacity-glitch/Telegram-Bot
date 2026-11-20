"""One evidence-backed Telegram photo per gameweek and UK fixture date."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path
import hashlib
import json
import os
import subprocess
from zoneinfo import ZoneInfo
from .press_sources import lookup
from .press_graphic import render

UK=ZoneInfo('Europe/London')
EAST=ZoneInfo('America/New_York')
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'state/matchday_press.json'

def clock(value): return datetime.fromisoformat(value.replace('Z','+00:00'))

def matchdays(snapshot,now):
    groups={}
    for f in snapshot.fixtures:
        gw=f.get('event')
        if not gw or not f.get('kickoff_time'): continue
        kickoff=clock(f['kickoff_time'])
        date=str(kickoff.astimezone(UK).date())
        g=groups.setdefault((gw,date),dict(gw=gw,date=date,first=kickoff,pairs={}))
        g['first']=min(g['first'],kickoff)
        h,a=f['team_h'],f['team_a']
        g['pairs'].update({str(h):a,str(a):h})
    for e in snapshot.events:
        if not e.get('deadline_time') or e.get('finished'): continue
        dates=sorted(k for k in groups if k[0]==e['id'])
        for index,k in enumerate(dates):
            day=groups[k]; deadline=clock(e['deadline_time'])
            target=deadline-timedelta(hours=2) if index==0 else None
            start=day['first']-timedelta(hours=12)
            if target: start=min(start,target-timedelta(hours=1))
            if start<=now<day['first']:
                yield dict(day,deadline=deadline,target=target)

def caption_for(day,names,facts,now):
    lines=[f"GW{day['gw']} • Press conference • {day['date']}",
           f"{len(facts)}/{len(names)} clubs verified",
           ("Gameweek locked" if now>=day['deadline'] else 'FPL deadline')+' • '+day['deadline'].astimezone(EAST).strftime('%a %I:%M %p %Z'),
           'Club sources: ', '#FPL #FPLVORTEX']
    entities=[]
    for key,v in facts.items():
        if entities: lines[3]+=' · '
        pos=len(('\n'.join(lines[:4])).encode('utf-16-le'))//2
        name=names[key];lines[3]+=name
        entities.append(dict(type='text_link',offset=pos,length=len(name.encode('utf-16-le'))//2,url=v['url']))
    return '\n'.join(lines),entities

def run(snapshot,now,read,write,client_factory,fetch=lookup,render_image=render,live_clock=None):
    from .publishing_window import press_delivery
    from .telegram_spacing import GAP
    state=read(STATE)
    for day in matchdays(snapshot,now):
        key=f"{day['gw']}:{day['date']}"
        row=state.setdefault(key,{})
        if row.get('sending'): continue  # uncertain Telegram acceptance; reconcile before another send
        pairs=day['pairs']
        facts={k:v for k,v in row.get('facts',{}).items() if pairs.get(k)==v['opponent']}
        missing=[k for k in pairs if k not in facts]
        target=day['target']
        opening_due=target is not None and now>=target-timedelta(minutes=15)
        # At the deadline target, send already-verified coverage before waiting on slower sources.
        publish_cached=opening_due and facts and not row.get('message')
        if missing and not publish_cached and (not row.get('checked') or now-clock(row['checked'])>=timedelta(minutes=12)):
            def find(k):
                club=snapshot.teams[int(k)]; opponent=snapshot.teams[pairs[k]]
                prior=[clock(f['kickoff_time']) for f in snapshot.fixtures if f.get('kickoff_time') and
                       int(k) in (f.get('team_h'),f.get('team_a')) and clock(f['kickoff_time'])<day['first']]
                since=max([day['first']-timedelta(days=6),*prior])
                return k,fetch(club,opponent,now,since)
            with ThreadPoolExecutor(max_workers=10) as pool:
                for k,item in pool.map(find,missing):
                    if item: facts[k]=dict(item,opponent=pairs[k])
            row.update(facts=facts,checked=now.isoformat());write(STATE,state)
        current=live_clock() if live_clock else now
        if current>=day['first']: continue
        opening_due=target is not None and current>=target-timedelta(minutes=15)
        ready=bool(facts) and (len(facts)==len(pairs) or opening_due)
        names={k:snapshot.teams[int(k)]['name'] for k in pairs}
        version=hashlib.sha256(json.dumps([pairs,facts,day['deadline'].isoformat()],sort_keys=True).encode()).hexdigest()
        if ready and row.get('version')!=version:
            path=ROOT/'outbox/assets'/f"press-GW{day['gw']}-{day['date']}.png"
            render_image(path,day,names,facts,current>=day['deadline'])
            caption,entities=caption_for(day,names,facts,current)
            client=client_factory()
            if not row.get('message'):
                row['sending']=True;write(STATE,state)
                if os.getenv('GITHUB_ACTIONS')=='true':
                    subprocess.run(['bash','.github/scripts/persist-publishing-receipts.sh'],cwd=ROOT,check=True)
            try:
                with press_delivery():
                    if row.get('message'):
                        mid=client.edit_shared_png(path,caption,row['message'],entities=entities)
                    else: mid=client.send_shared_png(path,caption,'Press conference',day['gw'],entities=entities)
            except Exception as error:
                if getattr(error,'confirmed_rejection',False):
                    row.pop('sending',None);write(STATE,state)
                raise
            row.update(message=mid,version=version,sending=False);write(STATE,state)
            return True
        if target and current < target and target-current<=GAP and not row.get('message') and facts:
            return True
    return False
