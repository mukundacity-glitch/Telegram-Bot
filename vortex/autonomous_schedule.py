"""Additional editorial slots; original news/legacy slots remain separate."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')


@dataclass(frozen=True)
class Slot:
    task: str
    edition: str
    hour: int
    minute: int = 20
    series_gw: int | None = None
    series_day: int | None = None
    on_date: date | None = None


RETIRED_EDITIONS = {
    "market-verdict", "transfer_suggestions", "transfer-suggestions",
    "four-team-targets", "transfer-desk", "transfer",
    "availability-transfer-decisions", "rank-booster", "fixture-targets",
    "start_bench", "squad-surgery", "transfer-market-team-news", "four-midfielders", "captain-differential",
}

SERIES = Slot('task2', 'weekly-analysis', 12, 30)
SERIES_STATE = '_weekly_analysis'
AFTERNOON = Slot('task2', 'afternoon-rotation', 13, 30)
SCOUTING = Slot('task2', 'scouting-rotation', 14, 30)
WILDCARD_CRON = '30 20 17 11 *'
WILDCARD = Slot('task2', 'wildcard-draft', 15, 30, on_date=date(2026, 11, 17))

SLOTS = (
    Slot('task1', 'form-minutes-targets', 8, 30),
    Slot('task2', 'defender-watch', 9, 30),
    Slot('task2', 'goalkeeper-striker-watch', 10, 30),
    Slot('task1', 'player-radar-comparison', 11, 30),
    SERIES,
    AFTERNOON,
    SCOUTING,
    WILDCARD,
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
SPECIAL_EDITIONS = ('chance-creators','captaincy-comparison','value-board','start-bench-board','final-gameweek-news','market-trends-next-five')
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
    if slot.on_date:
        return f'{slot.on_date}:{slot.task}:{slot.edition}'
    if slot in (AFTERNOON, SCOUTING):
        return f'{now.astimezone(ET).date()}:{slot.task}:{slot.edition}'
    if slot.series_day is not None:
        return f'{season}:GW{slot.series_gw}:{slot.task}:{slot.edition}:day{slot.series_day}'
    if slot.edition in SPECIAL_EDITIONS:
        return f'{season or str(now.year)}:GW{gw}:task1:{slot.edition}'
    key = f"{now.astimezone(ET).date()}:{slot.task}:{slot.edition}:GW{gw}"
    # An edition that runs twice a day (press availability) needs one record per slot.
    return key + f':{slot.hour:02d}{slot.minute:02d}' if slot.task == 'press_news' else key


def slot_start(slot, now):
    day = slot.on_date or now.astimezone(ET).date()
    return datetime(day.year, day.month, day.day, slot.hour, slot.minute, tzinfo=ET)


def eligible_on(slot, now):
    return slot.on_date is None or slot.on_date == now.astimezone(ET).date()


def retryable(row):
    return row.get('status') not in CLOSED and row.get('attempts', 0) < MAX_ATTEMPTS


def catchup_slots(now, state, gw, season=None, limit=3):
    """Slots already due today with remaining attempts, oldest first."""
    return [
        slot for slot in sorted(SLOTS, key=lambda s: (s.hour, s.minute))
        if slot != SERIES and eligible_on(slot, now) and now >= slot_start(slot, now)
        and retryable(state.get(publication_key(slot, now, gw, season), {}))
    ][:limit]


SPECIAL_LEAD_HOURS = {
    'chance-creators': 36, 'captaincy-comparison': 36, 'value-board': 27,
    'start-bench-board': 8, 'final-gameweek-news': 5,
}


def special_triggers(snapshot, now):
    """Return each special and its trigger, or None while awaiting an event."""
    gw = snapshot.gameweek()
    future = [f for f in snapshot.fixtures if f.get('event') == gw and f.get('kickoff_time')]
    if not gw or not future:
        return []
    first = min(datetime.fromisoformat(f['kickoff_time'].replace('Z', '+00:00')) for f in future)
    from .fpl import upcoming_deadline
    deadline = upcoming_deadline(snapshot)
    if deadline is None or now >= deadline:
        return []
    triggers = {name: first - timedelta(hours=hours) for name, hours in SPECIAL_LEAD_HOURS.items()}
    previous = [f for f in snapshot.fixtures if f.get('event') == gw - 1]
    event = next((e for e in snapshot.events if e.get('id') == gw - 1), {})
    last = max((datetime.fromisoformat(f['kickoff_time'].replace('Z', '+00:00'))
                for f in previous if f.get('kickoff_time')), default=None)
    if last is None or now <= last + timedelta(hours=24):
        triggers['market-trends-next-five'] = (
            last if last and event.get('finished') and all(f.get('finished') for f in previous) else None
        )
    return [
        (Slot('task1', name, now.astimezone(ET).hour, 35), trigger)
        for name, trigger in triggers.items()
    ]


def due_specials(snapshot, now, state):
    gw, season = snapshot.gameweek(), season_id(snapshot, now)
    return [slot for slot, trigger in special_triggers(snapshot, now)
            if trigger is not None and trigger <= now
            and retryable(state.get(publication_key(slot, now, gw, season), {}))]


def weekly_analysis_slot(snapshot, now, state):
    """Start one seven-day series per completed GW, pinned for all seven days."""
    from dataclasses import replace
    from .fpl import latest_completed_gw

    latest = latest_completed_gw(snapshot)
    if latest is None or now < slot_start(SERIES, now):
        return None
    season = season_id(snapshot, now)
    today = now.astimezone(ET).date()
    tracker = state.get(SERIES_STATE, {})
    if tracker.get('season') == season:
        elapsed = (today - datetime.fromisoformat(tracker['start']).date()).days
        if 0 <= elapsed < 7:
            return replace(SERIES, series_gw=tracker['gw'], series_day=elapsed+1)
        if latest <= tracker['gw']:
            return None
    state[SERIES_STATE] = {'season': season, 'gw': latest, 'start': today.isoformat()}
    return replace(SERIES, series_gw=latest, series_day=1)
