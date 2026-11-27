"""Read-only nominal reservation audit for existing fixed routes.

A collision is evidence of a conflict, not permission to move either slot.
This does not cover dynamic triggers, catch-up, pending/manual outbox or
actual publication receipts; the release gate remains closed.
"""
from datetime import timedelta, timezone
from .autonomous_schedule import ET, SLOTS, eligible_on, slot_start
from .daily_cutover import slots
from .schedule import SLOT_HOURS
from .telegram_spacing import GAP
from .legacy_research_gap import WINDOWS


def fixed_conflicts(now):
    if now.tzinfo is None:
        raise ValueError("Timezone-aware audit time required")
    local = now.astimezone(ET)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start -= timedelta(days=start.weekday())
    reservations = []
    # Include a boundary day on either side for cross-midnight reservations.
    for offset in range(-1, 8):
        day = start+timedelta(days=offset)
        def add(name, phase, at, length):
            at = at.astimezone(timezone.utc)
            reservations.append((name, phase, at, at+length))
        def at(h,m):
            return day.replace(hour=h,minute=m)
        for s in (*SLOTS, *slots(day)):
            if eligible_on(s,day):
                add(s.edition,"post",slot_start(s,day),GAP)
        for name,(h,m) in SLOT_HOURS.items():
            add(name,"post",at(h,m),GAP)
        if day.weekday()==4:
            add("rotation-planner","post",at(20,0),GAP)
        for name,h,m,length in (("most-transferred-in",1,13,17),
                                  ("team-decision-desk",4,13,15),
                                  ("player-radar-comparison",5,58,12)):
            add(name,"research",at(h,m),timedelta(minutes=length))
        if day.weekday() in (4,5):
            add("rotation-planner" if day.weekday()==4 else "saturday-fdr-grid",
                "research",at(15,28),timedelta(minutes=12))
        for name,(weekday,h,m,_,_) in WINDOWS.items():
            if day.weekday()==weekday:
                add(name,"research",at(h,m),timedelta(minutes=15))
    result=[]
    for i,(a,ap,astart,aend) in enumerate(reservations):
        for b,bp,bstart,bend in reservations[i+1:]:
            if (astart < bend and bstart < aend
                    and start <= max(astart,bstart).astimezone(ET) < start+timedelta(days=7)):
                result.append({"first":a,"first_phase":ap,"first_at":astart.isoformat(),
                               "second":b,"second_phase":bp,"second_at":bstart.isoformat()})
    return result
