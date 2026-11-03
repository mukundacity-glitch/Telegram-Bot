"""Additional editorial slots; original news/legacy slots remain separate."""
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')


@dataclass(frozen=True)
class Slot:
    task: str
    edition: str
    hour: int
    minute: int = 20


SLOTS = (
    Slot('task1', 'availability-transfer-decisions', 5),
    Slot('task2', 'rank-booster', 6),
    Slot('three_daily', 'fixture-targets', 7),
    Slot('task1', 'form-minutes-targets', 8),
    Slot('task2', 'four-midfielders', 9),
    Slot('press_news', 'verified-press-availability', 10),
    Slot('task1', 'captain-differential', 11),
    Slot('task2', 'four-team-targets', 12),
    Slot('three_daily', 'squad-surgery', 13),
    Slot('task1', 'transfer-market-team-news', 14),
    Slot('task2', 'market-verdict', 15),
    Slot('press_news', 'verified-press-availability', 16),
    Slot('price_changes', 'confirmed-price-changes', 17),
    Slot('press_news', 'verified-press-availability', 18),
    Slot('three_daily', 'vortex-captain', 19),
)
BY_CRON = {f'{s.minute} {s.hour} * * *': s for s in SLOTS}
NEWS_CRONS = {f'5 {hour} * * *' for hour in range(5, 20)}
SPECIAL_CRONS = {f'35 {hour} * * *' for hour in range(5,20)}
SPECIAL_EDITIONS = ('captaincy-comparison','value-board','start-bench-board','final-gameweek-news','market-trends-next-five')


def slot_for(cron):
    return BY_CRON.get((cron or '').strip())


def season_id(snapshot, now):
    start = next((datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00"))
                  for e in snapshot.events if e.get("id") == 1), now)
    year = start.year if start.month >= 7 else start.year - 1
    return f"{year}-{(year+1)%100:02d}"


def publication_key(slot, now, gw, season=None):
    if slot.edition in SPECIAL_EDITIONS:
        return f'{season or str(now.year)}:GW{gw}:task1:{slot.edition}'
    return f"{now.astimezone(ET).date()}:{slot.task}:{slot.edition}:GW{gw}"


def due_specials(snapshot,now,state):
    from datetime import timedelta
    gw=snapshot.gameweek()
    future=[f for f in snapshot.fixtures if f.get('event')==gw and f.get('kickoff_time')]
    if not future:return []
    first=min(datetime.fromisoformat(f['kickoff_time'].replace('Z','+00:00')) for f in future)
    deadline=next(datetime.fromisoformat(e['deadline_time'].replace('Z','+00:00')) for e in snapshot.events if e.get('id')==gw)
    if now>=deadline:return []
    due=[]
    for name,hours in (('captaincy-comparison',36),('value-board',27),('start-bench-board',8),('final-gameweek-news',5)):
        slot=Slot('task1',name,now.astimezone(ET).hour,35)
        if first-timedelta(hours=hours)<=now and state.get(publication_key(slot,now,gw,season_id(snapshot,now)),{}).get('status')!='delivered':due.append(slot)
    previous=[f for f in snapshot.fixtures if f.get('event')==gw-1]
    event=next((e for e in snapshot.events if e.get('id')==gw-1),{})
    if previous and event.get('finished') and all(f.get('finished') for f in previous):
        last=max(datetime.fromisoformat(f['kickoff_time'].replace('Z','+00:00')) for f in previous if f.get('kickoff_time'))
        # FPL has no actual full-time timestamp. Requiring <=24h from kickoff
        # is conservative: confirmed completion is necessarily within 24h.
        slot=Slot('task1','market-trends-next-five',now.astimezone(ET).hour,35)
        if timedelta(0)<=now-last<=timedelta(hours=24) and state.get(publication_key(slot,now,gw,season_id(snapshot,now)),{}).get('status')!='delivered':due.append(slot)
    return due
