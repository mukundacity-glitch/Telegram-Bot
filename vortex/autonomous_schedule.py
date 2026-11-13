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
    Slot('task1', 'availability-transfer-decisions', 5, 30),
    Slot('task2', 'rank-booster', 6, 30),
    Slot('three_daily', 'fixture-targets', 7, 30),
    Slot('task1', 'form-minutes-targets', 8, 30),
    Slot('task2', 'four-midfielders', 9, 30),
    Slot('task1', 'player-radar-comparison', 10, 30),
    Slot('task1', 'captain-differential', 11, 30),
    Slot('task2', 'four-team-targets', 12, 30),
    Slot('three_daily', 'squad-surgery', 13, 30),
    Slot('task1', 'transfer-market-team-news', 14, 30),
    Slot('task2', 'market-verdict', 15, 30),
    Slot('task1', 'deadline-watch', 16, 30),
    Slot('price_changes', 'confirmed-price-changes', 17, 30),
    Slot('press_news', 'verified-press-availability', 19, 0),
    Slot('three_daily', 'vortex-captain', 21, 0),
)
# Editorial slots are TIME-based catch-up slots, not bound to one cron string:
# a delayed, cancelled or dropped GitHub run can never lose an edition because
# the next run posts whatever is due and not yet closed for the Eastern day.
BY_CRON = {}
# Approved publishing day: 05:30 inclusive to 23:00 exclusive, Eastern time.
WINDOW_OPEN = (5, 30)
WINDOW_CLOSE = (23, 0)
# Heartbeat minutes are stated in America/New_York because the workflow schedule
# carries ``timezone: America/New_York``. Never derive them from UTC hours.
CATCHUP_CRONS = {f'{m} {h} * * *' for h in range(5, 23) for m in (10, 40) if (h, m) >= WINDOW_OPEN}
NEWS_CRONS = {f'5 {hour} * * *' for hour in range(6, 23)}
SPECIAL_CRONS = {f'35 {hour} * * *' for hour in range(5, 23)}
OUTBOX_CRONS = {f'50 {hour} * * *' for hour in range(5, 23)}
SPECIAL_EDITIONS = ('captaincy-comparison','value-board','start-bench-board','final-gameweek-news','market-trends-next-five')
CLOSED = {'delivered', 'already-delivered', 'no-new-facts', 'checked'}
MAX_ATTEMPTS = 3


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
    key = f"{now.astimezone(ET).date()}:{slot.task}:{slot.edition}:GW{gw}"
    # An edition that runs twice a day (press availability) needs one record per slot.
    return key + f':{slot.hour:02d}{slot.minute:02d}' if slot.task == 'press_news' else key


def slot_start(slot, now):
    return now.astimezone(ET).replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)


def catchup_slots(now, state, gw, season=None, limit=3):
    """Slots that are already due today and not yet closed, oldest first."""
    due = []
    for slot in sorted(SLOTS, key=lambda s: (s.hour, s.minute)):
        if now < slot_start(slot, now):
            continue
        row = state.get(publication_key(slot, now, gw, season), {})
        if row.get('status') in CLOSED:
            continue
        if row.get('status') in ('held', 'queued-or-partial') and row.get('attempts', 1) >= MAX_ATTEMPTS:
            continue
        due.append(slot)
    return due[:limit]


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
