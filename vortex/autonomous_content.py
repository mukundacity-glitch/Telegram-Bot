"""Executable editions: official evidence, deterministic copy, no chat model.

Editorial scores order candidates, never masquerade as forecast points. Model
and effective-ownership fields use the strict independently verified feed.
"""
from dataclasses import dataclass
from datetime import datetime
import json
import requests

from .chatgpt_task_editions import _make_cards, _report
from .content import Content
from .fpl import score, choose_news, confirmed_price_changes
from .publication_rules import five_gw_fixtures, player_metrics
from .recommendations import get_history, completed_rounds
from .editorial_inputs import RequiredInput, NoUpdate, verified_feed, eo_for


@dataclass
class Plan:
    task: str
    edition: str
    title: str
    caption: str
    gw: int
    players: list
    labels: list
    kind: str = 'players'
    extra: dict | None = None


class Evidence:
    def __init__(self, snapshot, now, session=None):
        self.snapshot, self.now = snapshot, now
        self.session = session or requests.Session()
        self.history = {}
        self.completed = set(completed_rounds(snapshot, 4))

    def recent(self, player):
        pid = player['id']
        if pid not in self.history:
            self.history[pid] = [r for r in get_history(pid, self.session)
                                 if r.get('round') in self.completed][-3:]
        return self.history[pid]

    def qualified(self, limit=16):
        pool = [p for p in self.snapshot.players if p.get('status') == 'a'
                and int(p.get('minutes') or 0) >= 450
                and self.snapshot.fixtures_for_gameweek(p)]
        result = []
        for p in sorted(pool, key=score, reverse=True)[:45]:
            rows = self.recent(p)
            if len(rows) == 3 and all(int(r.get('minutes') or 0) >= 70 for r in rows):
                result.append(p)
            if len(result) >= limit:
                break
        return result

    def rank(self, p):
        # Observed recent returns + per-90 attacking involvement + official
        # next-fixture difficulty. This is editorial ordering, not xPts.
        rows = self.recent(p)
        minutes = sum(int(r.get('minutes') or 0) for r in rows)
        points = sum(int(r.get('total_points') or 0) for r in rows)
        xgi = sum(float(r.get('expected_goal_involvements') or 0) for r in rows)
        fdr = [r[2] for r in self.snapshot.fixtures_for_gameweek(p) if r[2] in (1,2,3,4,5)]
        return points/max(minutes, 1)*90 + xgi/max(minutes, 1)*90*2 + (3-sum(fdr)/len(fdr) if fdr else -3)


def caption(snapshot, title, players, action='MONITOR'):
    lead = players[0]
    fixture = ' / '.join(f'{opp} ({venue})' for opp, venue, _, _ in snapshot.fixtures_for_gameweek(lead))
    return _report(snapshot.gameweek(), title.lower(),
                   f"{snapshot.name(lead)} {snapshot.price(lead)}; form {lead['form']}; next {fixture}.",
                   action, 'FPLTips')


def _team_rows(feed, snapshot, team_id):
    rows = (feed.get('teams') or {}).get(str(team_id), {}).get('fixtures') or []
    official = {f['id']: f for f in snapshot.fixtures if f.get('event') in range(snapshot.gameweek(), snapshot.gameweek()+5)
                and team_id in (f.get('team_h'), f.get('team_a')) and not f.get('finished')}
    if set(r.get('fixture_id') for r in rows) != set(official):
        raise RequiredInput('Custom FDR feed does not cover every official next-five fixture')
    for row in rows:
        f = official[row['fixture_id']]
        home = f['team_h'] == team_id
        if row.get('gw') != f['event'] or row.get('opponent_id') != f['team_a' if home else 'team_h'] or row.get('venue') != ('H' if home else 'A'):
            raise RequiredInput('Custom FDR feed fixture/current-club join differs from official FPL')
        for key, lo, hi in (('attacking_fdr',1,5),('defensive_fdr',1,5),('projected_goals',0,12),('clean_sheet_pct',0,100)):
            if type(row.get(key)) not in (int,float) or not lo <= row[key] <= hi:
                raise RequiredInput('Invalid verified custom FDR/goals/clean-sheet field')
    return rows


def build(slot, snapshot, now, evidence=None, model=None, prices=None, research=None):
    e = evidence or Evidence(snapshot, now)
    gw = snapshot.gameweek()
    name = slot.edition
    if name == 'rank-booster':
        from .low_owned_six import build_low_owned
        return build_low_owned(slot,snapshot,now,e)
    if name == 'deadline-watch':
        from .deadline_watch import build_deadline_watch
        return build_deadline_watch(slot,snapshot,now,e)
    if name == 'four-midfielders':
        # Reuse the approved quantile/match-minutes selection, now called by
        # the GitHub generator rather than a ChatGPT task.
        from statistics import median, quantiles
        mids = [p for p in snapshot.players if p.get('element_type') == 3]
        values = [p['now_cost'] for p in mids if p.get('now_cost')]
        high, low = quantiles(values, n=4)[2], median(values)
        pool = e.qualified(30)
        premium = [p for p in pool if p['element_type']==3 and p['now_cost']>=high][:3]
        budget = [p for p in pool if p['element_type']==3 and p['now_cost']<=low and p not in premium][:1]
        players, labels = premium+budget, ['PREMIUM']*3+['BUDGET VALUE']
        if len(players)!=4: raise RequiredInput('Four secure-minute midfielders with the approved price mix not available')
        title = 'FOUR MIDFIELDERS • THREE PREMIUM + ONE VALUE'
    elif name == 'start-bench-board':
        from .content import generate
        from dataclasses import asdict
        article=generate('start_bench',snapshot,now,{})
        return Plan(slot.task,name,article.title,article.caption,gw,[],[],kind='legacy',extra={'content':asdict(article)})
    elif name == 'value-board':
        feed=verified_feed(snapshot,now,e.session,payload=model)
        from math import isfinite
        players=[];values={}
        for pos in (1,2,3,4):
            options=[]
            for p in snapshot.players:
                if p.get('element_type')!=pos or p.get('status')!='a':continue
                current={f['id'] for f in snapshot.fixtures if f.get('event')==gw and p['team'] in (f.get('team_h'),f.get('team_a')) and not f.get('finished')}
                if not current:continue
                team=_team_rows(feed,snapshot,p['team'])
                fdr_key='defensive_fdr' if pos in (1,2) else 'attacking_fdr'
                fdrs=[r[fdr_key] for r in team if r['gw']==gw]
                if not fdrs:continue
                rows=(feed.get('players')or{}).get(str(p['id']),{}).get('fixtures')or[]
                next_rows=[r for r in rows if r.get('gw')==gw]
                if next_rows:
                    # Full per-fixture xPts from the separately proven Day 1
                    # model is usable ONLY with exact official fixture joins.
                    if set(r.get('fixture_id') for r in next_rows)!=current:continue
                    if any(type(r.get('xpts')) not in (int,float) or
                           not isfinite(r['xpts']) or not 0<=r['xpts']<=40
                           for r in next_rows):continue
                    points=sum(r['xpts'] for r in next_rows)
                    source='MODEL xPTS'
                else:
                    # The official next-GW FPL projection is NOT custom xPts.
                    # Never divide it across a double Gameweek or relabel it.
                    if type(p.get('ep_next')) not in (str,int,float):continue
                    try:points=float(p['ep_next'])
                    except ValueError:continue
                    if not isfinite(points) or not 0 < points <= 40:continue
                    source='FPL EP_NEXT'
                values[str(p['id'])]={'xpts':points,'fdr':sum(fdrs)/len(fdrs),
                                     'points_source':source,'fdr_source':feed['model_version']}
                options.append(p)
            options.sort(key=lambda p:values[str(p['id'])]['xpts'],reverse=True)
            if len(options)<3:raise RequiredInput('Value board lacks three verified official/model forecasts in every position')
            players+=options[:3]
        title='NEXT GW • FPL PROJECTION + VORTEX FDR' if not (feed.get('players')or{}) else 'NEXT GW • FORECAST VALUE BOARD'
        return Plan(slot.task,name,title,caption(snapshot,'next-GW forecast value',players),gw,players,['MONITOR']*len(players),
                    kind='value',extra={'values':values,'model':feed['model_version'],
                                        'forecast_disclosure':'FPL ep_next is official FPL forecast, not Day 1 model xPts; forecasts are not guaranteed returns.'})
    elif name == 'market-trends-next-five':
        players=[]
        for pos,quota in ((1,2),(2,5),(3,5),(4,3)):
            candidates=[p for p in snapshot.players if p.get('element_type')==pos and snapshot.fixtures_for_gameweek(p)
                        and type(p.get('transfers_in_event')) is int and type(p.get('transfers_out_event')) is int]
            candidates.sort(key=lambda p:(p['transfers_in_event']-p['transfers_out_event'],p['transfers_in_event']),reverse=True)
            if len(candidates)<quota:raise RequiredInput('Official market data does not support all fifteen positional rows')
            players+=candidates[:quota]
        labels=['SELL' if p.get('status')!='a' else 'HOLD' for p in players]
        return Plan(slot.task,name,f'GAMEWEEK {gw} • MOST BOUGHT • BUY / HOLD / SELL',caption(snapshot,'market decisions',players,'HOLD'),gw,players,labels,kind='market15')
    elif name in ('availability-transfer-decisions','transfer-market-team-news','final-gameweek-news'):
        pool = choose_news(snapshot, now) if name.startswith('availability') else snapshot.players
        if name=='final-gameweek-news':pool=[p for p in snapshot.players if p.get('status')!='a'] or e.qualified(3)
        players = [p for p in pool if snapshot.fixtures_for_gameweek(p) and p.get('code') and p.get('team') in snapshot.teams]
        players.sort(key=lambda p:int(p.get('transfers_out_event') or 0), reverse=True)
        players=players[:3]
        if not players: raise NoUpdate('No new verified actionable availability story')
        labels=['MONITOR' if p.get('status')!='a' else 'HOLD' for p in players]
        title='FINAL GAMEWEEK AVAILABILITY' if name=='final-gameweek-news' else 'AVAILABILITY & TRANSFER DECISIONS' if name.startswith('availability') else 'TRANSFER MARKET • TEAM NEWS'
    elif name == 'confirmed-price-changes':
        changes = confirmed_price_changes(snapshot, prices or {})
        if not changes: raise NoUpdate('No confirmed price movement versus the persisted official baseline')
        players=[p for p, _, _ in changes[:4]];labels=['MONITOR']*len(players)
        title='CONFIRMED FPL PRICE CHANGES'
        moves={p['id']:f'£{old/10:.1f}m → £{new/10:.1f}m' for p,old,new in changes}
        return Plan(slot.task,name,title,caption(snapshot,title,players),gw,players,labels,extra={'price_moves':moves})
    elif name == 'four-team-targets':
        feed = verified_feed(snapshot,now,e.session,payload=model)
        teams=[]
        for tid, club in snapshot.teams.items():
            rows=_team_rows(feed,snapshot,tid)
            current=[r for r in rows if r['gw']==gw]
            if current: teams.append({'id':tid,'club':club,'fixtures':rows,'current':current})
        attacks=sorted(teams,key=lambda t:sum(r['attacking_fdr'] for r in t['current'])/len(t['current']))[:2]
        defences=sorted([t for t in teams if t not in attacks],key=lambda t:sum(r['defensive_fdr'] for r in t['current'])/len(t['current']))[:2]
        if len(attacks+defences)!=4: raise RequiredInput('Four verified independent team forecast targets not available')
        return Plan(slot.task,name,'FOUR FIXTURE TARGETS',_report(gw,'four next-GW fixture targets',
                    'Two attacking targets and two defensive targets; five-GW context.', 'MONITOR','FPLFixtures'),
                    gw,[],[],kind='teams',extra={'teams':attacks+defences,'categories':['ATTACKING']*2+['DEFENSIVE']*2,'model':feed['model_version']})
    elif name == 'market-verdict':
        feed=verified_feed(snapshot,now,e.session,payload=model)
        safe=e.qualified(30)
        players=[];groups=[]
        for pos, quota in ((1,1),(2,4),(3,4),(4,3)):
            pool=sorted([p for p in safe if p['element_type']==pos],key=lambda p:int(p.get('transfers_in_event') or 0),reverse=True)[:quota]
            if not pool: raise RequiredInput('No eligible 70-minute-evidence market candidate in a required position')
            for p in pool: _team_rows(feed,snapshot,p['team'])
            players+=pool;groups.append([p['id'] for p in pool])
        labels=['BUY' if e.rank(p)>7 else 'MONITOR' for p in players]
        return Plan(slot.task,name,'MARKET TREND • VORTEX VERDICTS',caption(snapshot,'market verdicts',players),gw,
                    players,labels,kind='market',extra={'groups':groups,'model':feed,'eligibility':'Recent three completed appearances each ≥70 minutes; future minutes not guaranteed'})
    elif name == 'squad-surgery':
        from .manager_questions import recent_question
        question=research or recent_question(now,e.session)
        players=sorted(e.qualified(10),key=e.rank,reverse=True)[:4]
        if len(players)!=4: raise RequiredInput('Four verified squad-decision examples unavailable')
        labels=['MAKE THE MOVE','HOLD / ROLL','HIT OR NO HIT','PLAN AHEAD']
        return Plan(slot.task,name,'SQUAD SURGERY • TRANSFER STRATEGY',caption(snapshot,'squad decisions',players),gw,
                    players,labels,kind='surgery',extra={'research':question})
    else:
        pool=sorted(e.qualified(24),key=e.rank,reverse=True)
        if name in ('vortex-captain','captain-differential','captaincy-comparison'):
            attack=[p for p in pool if p['element_type'] in (3,4)]
            if not attack: raise RequiredInput('No available reliable-minute captain candidate')
            main=attack[0]
            alternatives=[p for p in attack[1:] if float(p['selected_by_percent'])<float(main['selected_by_percent'])][:2]
            if len(alternatives)!=2: raise RequiredInput('Two evidenced lower-ownership captain alternatives unavailable')
            players=[alternatives[0],main,alternatives[1]]
            labels=['DIFFERENTIAL CAPTAIN 1','VORTEX CAPTAIN','DIFFERENTIAL CAPTAIN 2']
            title='VORTEX CAPTAIN • TWO ALTERNATIVES'
            return Plan(slot.task,name,title,caption(snapshot,title,[main]+alternatives,'CAPTAIN'),gw,players,labels)
        if name == 'fixture-targets':
            players=pool[:4]
            # Effective ownership is fundamentally unavailable until the
            # managers' GW picks/captaincies can be independently observed.
            # Never block the otherwise official-data fixture card for EO.
            feed=model
            eo={}
            if feed is not None:
                for p in players:
                    try:eo[str(p['id'])]=eo_for(feed,p['id'])
                    except RequiredInput:eo[str(p['id'])]=None
            labels=['START','HOLD','MONITOR','HOLD'];title='NEXT GAMEWEEK • FOUR TARGETS'
            if len(players)==4:
                return Plan(slot.task,name,title,caption(snapshot,title,players),gw,players,labels,kind='targets',
                            extra={'eo':eo,'recent':{str(p['id']):e.recent(p) for p in players},
                                   'eo_disclosure':'EO N/A without verified GW-specific manager captaincy sample.'})
            if len(players)!=4: raise RequiredInput('Four verified fixture targets unavailable')
        elif name == 'form-minutes-targets':
            players=pool[:3];labels=['MONITOR','HOLD','START'];title='FORM • MINUTES • UNDERLYING STATS'
        else:
            raise ValueError('Edition has no executable generator: '+name)
    if not players: raise RequiredInput('No verified players selected')
    return Plan(slot.task,name,title,caption(snapshot,title,players),gw,players,labels)


def as_content(plan, snapshot, now, players=None, labels=None):
    players=players if players is not None else plan.players
    labels=labels if labels is not None else plan.labels
    return Content(kind='ported_task',title=plan.title,kicker='NEXT GAMEWEEK',
                   cards=_make_cards(snapshot,players,labels),verdict='DECIDE ON VERIFIED MINUTES, FORM AND FIXTURES',
                   caption=plan.caption,data_at=now.isoformat(),gw=plan.gw,footer='Forecasts are not guaranteed returns')
