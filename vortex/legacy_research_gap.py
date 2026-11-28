"""Three-hour proof for existing weekly legacy boards; not the new Slot 7."""
from datetime import datetime, timedelta
from .autonomous_schedule import ET, season_id
from .research_gap import verified_gap

WINDOWS = {
    "goalkeeper-striker-watch": (0, 3, 13, 10, 30),
    "positional-vulnerability": (1, 3, 13, 15, 30),
    "monday-defence-watch": (0, 4, 43, 20, 0),
}


def proof_valid(edition, proof, season, gw, at):
    try:
        day, rh, rm, ph, pm = WINDOWS[edition]
        local = at.astimezone(ET)
        nominal = local.replace(hour=ph, minute=pm, second=0, microsecond=0)
        checked = datetime.fromisoformat(proof["checked_at"])
        start = local.replace(hour=rh, minute=rm, second=0, microsecond=0)
        return (at.tzinfo is not None and checked.tzinfo is not None
                and local.weekday() == day and nominal <= local
                and (local.hour, local.minute) < (23, 0)
                and proof["date"] == local.date().isoformat()
                and proof["season"] == season and proof["gw"] == gw
                # Research that finishes outside its reserved window can
                # overlap another workflow even when the elapsed gap is long.
                and start <= checked.astimezone(ET) < start + timedelta(minutes=15)
                and verified_gap(proof["checked_at"], nominal)
                and verified_gap(proof["checked_at"], at))
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def read_proof(edition, snapshot, now, evidence):
    from .bot import read_state
    from . import weekly_position_watch as position, weekly_wildcard_vulnerability as wildcard, monday_intelligence as monday
    if edition == "goalkeeper-striker-watch":
        module = position
        row = read_state(module.RESEARCH)
        matches = module._matching(row, snapshot, now, evidence.completed)
    elif edition == "positional-vulnerability":
        module = wildcard
        row = read_state(module.RESEARCH)
        matches = module._cache(snapshot, now) is not None
    elif edition == "monday-defence-watch":
        module = monday
        row = read_state(module.RESEARCH)
        matches = module._cache(snapshot, now) is not None
    else:
        return None
    if not matches:
        return None
    season = season_id(snapshot, now)
    proof = {"date": now.astimezone(ET).date().isoformat(), "season": season,
             "gw": snapshot.gameweek(), "checked_at": row.get("at")}
    return proof if proof_valid(edition, proof, season, snapshot.gameweek(), now) else None
