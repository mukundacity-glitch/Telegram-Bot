"""Additional editorial slots; original news/legacy slots remain separate."""
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    weekday: int | None = None
    display_name: str = ""
    price_update_at: str | None = None


RETIRED_EDITIONS = {
    "wildcard-draft", "striker-watch", "thursday-attacking-zones", "gw-key-players",
    "captaincy", "captaincy-showdown", "deadline-watch",
    "market-verdict", "transfer_suggestions", "transfer-suggestions",
    "four-team-targets", "transfer-desk", "transfer",
    "availability-transfer-decisions", "rank-booster", "fixture-targets",
    "confirmed-price-changes", "friday-rotation-planner",
    "start_bench", "squad-surgery", "transfer-market-team-news", "four-midfielders", "captain-differential",
}

SERIES = Slot('task2', 'weekly-analysis', 12, 30)
SERIES_STATE = '_weekly_analysis'
AFTERNOON = Slot('task2', 'afternoon-rotation', 13, 30)
SCOUTING = Slot('task2', 'scouting-rotation', 14, 30, display_name='FPL Player Performance Comparisons')
VULNERABILITY = Slot('task2', 'positional-vulnerability', 15, 30, weekday=1)
CLOCK_CRON = '0,30 0-3,9-23 * * *'
WILDCARD = Slot('task2', 'wildcard-draft', 15, 30, weekday=1)
CHIP_STRATEGY = Slot('task2', 'chip-strategy', 16, 30, weekday=1,
                     display_name='FPL Chip Strategy')
SHOT_QUALITY = Slot('task2', 'assists-vs-shot-quality', 16, 30, weekday=6,
                    display_name='Assists per 90 vs xG per Shot')

SUNDAY_CHANCES = Slot('task2', 'sunday-chance-watch', 20, 0, weekday=6,
                      display_name='Sunday Chance Watch')

MONDAY_DEFENCE = Slot('task2', 'monday-defence-watch', 20, 0, weekday=0,
                      display_name='Monday FPL Intelligence: Five Picks, Defence & Shot Origins')
# Fill the previously unused 20:00 ET slots without modifying GitHub cron.
# One weekday-only edition per date; Sunday and Monday remain unchanged.
TUESDAY_SET_PIECES = Slot('task2', 'tuesday-set-pieces', 20, 0, weekday=1,
                         display_name='FPL Set-Piece Takers')
WEDNESDAY_PREDICTED_XG = Slot('task2', 'wednesday-predicted-xg', 20, 0, weekday=2,
                             display_name='Predicted Team xG')
THURSDAY_ATTACKING_ZONES = Slot('task2', 'thursday-attacking-zones', 20, 0, weekday=3,
                               display_name='Attacking Zones • Shot Origins')
FRIDAY_ROTATION_PLANNER = Slot('task2', 'friday-rotation-planner', 20, 0, weekday=4,
                              display_name='Two-Club Rotation Planner')
SATURDAY_FDR_GRID = Slot('task2', 'saturday-fdr-grid', 20, 0, weekday=5,
                         display_name='Six-Gameweek FDR Grid')
EVENING_INTELLIGENCE_SLOTS = (
    TUESDAY_SET_PIECES, WEDNESDAY_PREDICTED_XG,
    SATURDAY_FDR_GRID,
)
EVENING_WATCH_SLOTS = (SUNDAY_CHANCES, MONDAY_DEFENCE, *EVENING_INTELLIGENCE_SLOTS)

PASSING_CREATORS = Slot('task2', 'passing-creators', 16, 15, weekday=2,
                        display_name='Completed Passes vs Chances Created')
BONUS_MAGNETS = Slot('task2', 'bonus-magnets', 16, 15, weekday=5,
                     display_name='FPL Bonus Magnets')
TOP_100K_OWNERSHIP = Slot('task2', 'top-100k-ownership', 22, 30, weekday=5,
                          display_name='Top 100k Ownership')
SATURDAY_BOARDS = (BONUS_MAGNETS, TOP_100K_OWNERSHIP)

SLOTS = (
    Slot('task1', 'form-minutes-targets', 8, 30),
    Slot('task2', 'defender-watch', 9, 30),
    Slot('task2', 'goalkeeper-striker-watch', 10, 30, weekday=0),
    Slot('task1', 'player-radar-comparison', 11, 30),
    SERIES,
    AFTERNOON,
    SCOUTING,
    VULNERABILITY,
    PASSING_CREATORS,
    BONUS_MAGNETS,
    SHOT_QUALITY,
    CHIP_STRATEGY,
    *EVENING_WATCH_SLOTS,
    Slot('three_daily', 'vortex-captain', 21, 0),
    TOP_100K_OWNERSHIP,
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
    if slot.edition == 'player-radar-comparison' and slot.series_gw is not None:
        return f'{season}:GW{slot.series_gw}:task1:player-radar-comparison'
    if slot.edition == 'price-prediction':
        if not slot.price_update_at:
            raise ValueError('Verified price update timestamp required')
        return f'{season}:GW{gw}:price_changes:price-prediction'
    if slot.weekday is not None or slot in (AFTERNOON, SCOUTING, VULNERABILITY):
        return f'{now.astimezone(ET).date()}:{slot.task}:{slot.edition}'
    if slot.series_day is not None:
        return f'{season}:GW{slot.series_gw}:{slot.task}:{slot.edition}:day{slot.series_day}'
    if slot.edition in SPECIAL_EDITIONS:
        return f'{season or str(now.year)}:GW{gw}:task1:{slot.edition}'
    key = f"{now.astimezone(ET).date()}:{slot.task}:{slot.edition}:GW{gw}"
    if slot.task == 'press_news':
        # Keep the existing evening receipt key after moving the send to 19:15.
        minute = 0 if slot.hour == 19 else slot.minute
        return key + f':{slot.hour:02d}{minute:02d}'
    return key


def slot_start(slot, now):
    day = now.astimezone(ET).date()
    return datetime(day.year, day.month, day.day, slot.hour, slot.minute, tzinfo=ET)


def eligible_on(slot, now):
    weekday = now.astimezone(ET).weekday()
    return slot.weekday is None or slot.weekday == weekday


def retryable(row):
    return row.get('status') not in CLOSED and row.get('attempts', 0) < MAX_ATTEMPTS


# Slot 6 uses the existing Saturday edition and serialized GitHub heartbeat.
FDR_RESEARCH_STATE = '_weekly_fdr_research'


def fdr_phase(now):
    local = now.astimezone(ET)
    if local.weekday() != 5:
        return None
    minute = local.hour * 60 + local.minute
    if 15 * 60 + 28 <= minute < 15 * 60 + 40:
        return 'research'
    if 20 * 60 <= minute < 20 * 60 + 15:
        return 'post'
    return None


def fdr_research_valid(state, snapshot, now):
    from .research_gap import verified_gap
    row = state.get(FDR_RESEARCH_STATE, {})
    return (fdr_phase(now) == 'post'
            and verified_gap(row.get('checked_at'), slot_start(SATURDAY_FDR_GRID, now))
            and verified_gap(row.get('checked_at'), now)
            and row.get('date') == now.astimezone(ET).date().isoformat()
            and row.get('gw') == snapshot.gameweek()
            and row.get('season') == season_id(snapshot, now)
            and row.get('verified') is True)


def catchup_slots(now, state, gw, season=None, limit=3):
    """Slots already due today with remaining attempts, oldest first."""
    return [
        slot for slot in sorted(SLOTS, key=lambda s: (s.hour, s.minute))
        if slot != SERIES and slot.edition != 'player-radar-comparison' and eligible_on(slot, now) and now >= slot_start(slot, now)
        and (slot != SATURDAY_FDR_GRID or (fdr_phase(now) == 'post'
             and not state.get(publication_key(slot, now, gw, season), {}).get('identity')))
        and retryable(state.get(publication_key(slot, now, gw, season), {}))
    ][:limit]


SPECIAL_LEAD_HOURS = {
    'captaincy-comparison': 36, 'value-board': 27,
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
    chance_time = first.astimezone(ET).replace(hour=6, minute=0, second=0, microsecond=0) - timedelta(days=2)
    if last is not None and chance_time == last:
        chance_time += timedelta(minutes=10)
    triggers['chance-creators'] = chance_time
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

def finalized_radar_slot(snapshot, now, state):
    """Only the latest officially settled GW, using the existing 11:30 slot."""
    from dataclasses import replace
    events = getattr(snapshot, 'events', ())
    fixtures = getattr(snapshot, 'fixtures', ())
    finalized = [e['id'] for e in events if type(e.get('id')) is int
                 and e.get('finished') is True and e.get('data_checked') is True
                 and any(f.get('event') == e['id'] for f in fixtures)
                 and all(f.get('finished') is True for f in fixtures if f.get('event') == e['id'])]
    if not finalized:
        return None
    slot = next((s for s in SLOTS if s.edition == 'player-radar-comparison'), None)
    if slot is None or now < slot_start(slot, now):
        return None
    slot = replace(slot, series_gw=max(finalized))
    key = publication_key(slot, now, snapshot.gameweek(), season_id(snapshot, now))
    return slot if retryable(state.get(key, {})) else None


RADAR_RESEARCH_STATE = '_settled_radar_research'


def radar_research_due(now):
    local = now.astimezone(ET)
    return (5, 58) <= (local.hour, local.minute) < (6, 10)


def radar_post_due(now):
    local = now.astimezone(ET)
    return (11, 30) <= (local.hour, local.minute) < (11, 45)


def radar_research_valid(state, slot, snapshot, now):
    from .research_gap import verified_gap
    row = state.get(RADAR_RESEARCH_STATE, {})
    return (radar_post_due(now) and slot.series_gw is not None and row.get('completed_gw') == slot.series_gw
            and row.get('season') == season_id(snapshot, now)
            and row.get('date') == now.astimezone(ET).date().isoformat()
            and verified_gap(row.get('checked_at'), slot_start(slot, now))
            and verified_gap(row.get('checked_at'), now))


def prepare_radar_research(snapshot, now, state, evidence, clock):
    if not radar_research_due(now):
        return False
    post = now.astimezone(ET).replace(hour=11, minute=30, second=0, microsecond=0)
    slot = finalized_radar_slot(snapshot, post, state)
    if slot is None or radar_research_valid(state, slot, snapshot, post):
        return False
    from .radar_comparison import build_radar
    plan = build_radar(slot, snapshot, now, evidence)
    state[RADAR_RESEARCH_STATE] = {
        'date': now.astimezone(ET).date().isoformat(), 'season': season_id(snapshot, now),
        'completed_gw': slot.series_gw, 'checked_at': clock().isoformat(),
        'player_ids': [p['id'] for p in plan.players],
    }
    return True
