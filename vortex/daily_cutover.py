"""Slots 2 and 4: one serialized GitHub check and one daily publication opportunity.

No new cron, publisher, or change to the historical graphic catalogue.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from .autonomous_schedule import ET, Slot, season_id, slot_start
from .research_gap import verified_gap

KINDS = {"most-transferred-in": "most_transferred_in", "team-decision-desk": "team_analysis"}
RESEARCH_STATE = "_daily_cutover_research"


def slots(now):
    # 05:30 is the first approved time in the requested five-o'clock hour.
    # On Saturdays the existing 22:30 edition needs its 45-minute spacing.
    desk = (21, 45) if now.astimezone(ET).weekday() == 5 else (22, 0)
    return (Slot("task2", "most-transferred-in", 5, 30),
            Slot("task2", "team-decision-desk", *desk))


def day_key(slot, now):
    return f"{now.astimezone(ET).date()}:cutover:{slot.edition}"


def research_window(slot, now):
    t = now.astimezone(ET)
    lo, hi = ((1, 13), (1, 30)) if slot.edition == "most-transferred-in" else ((4, 13), (4, 28))
    return lo <= (t.hour, t.minute) < hi


def post_window(slot, now):
    local = now.astimezone(ET)
    start = slot_start(slot, local)
    return start <= local < start + timedelta(minutes=15)


def player_ids(article):
    if article.kind == "most_transferred_in":
        return [r["player"]["id"] for r in article.transfers]
    return [r["id"] for r in article.team_analysis["players"]]


def claimed_ids(snapshot, now, queue, ledger=None):
    """Reserve prior and pending player identities, including other staged editions."""
    ids = set()
    season, gw = season_id(snapshot, now), snapshot.gameweek()
    official = {p["id"] for p in snapshot.players}
    by_code = {p["code"]: p["id"] for p in snapshot.players if type(p.get("code")) is int}
    def walk(value):
        if isinstance(value, dict):
            pid = value.get("id")
            if type(pid) is int and pid in official and any(k in value for k in ("element_type", "photo_code", "now_cost", "position", "web_name")):
                ids.add(pid)
            code = value.get("photo_code")
            if type(code) is int and code in by_code:
                ids.add(by_code[code])
            for p in value.get("player_ids", []) or []:
                if type(p) is int and p in official:
                    ids.add(p)
            for key, item in value.items():
                if key not in ("fixtures", "history", "player_ids"):
                    walk(item)
        elif isinstance(value, (tuple, list)):
            for item in value:
                walk(item)
    for path in sorted(Path(queue).glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("season") == season and row.get("gameweek") == gw:
            walk(row.get("facts") or {})
    for row in (ledger or {}).values():
        if row.get("season") == season and row.get("gw") == gw:
            walk(row)
    return frozenset(ids)


def conflicts(slot, snapshot, now, state, *, research=False):
    from .autonomous_schedule import SLOTS, eligible_on, special_triggers, publication_key, retryable
    from .schedule import SLOT_HOURS
    from .telegram_spacing import GAP
    from .price_prediction_board import official_clock, PRICE_LEAD, PRICE_RESEARCH_LEAD
    from .editorial_inputs import RequiredInput
    at = now if research else slot_start(slot, now)
    other_times = [(s.edition, slot_start(s, now)) for s in SLOTS if eligible_on(s, now)]
    other_times += [(name, now.astimezone(ET).replace(hour=h, minute=m, second=0, microsecond=0))
                    for name, (h,m) in SLOT_HOURS.items()]
    if now.astimezone(ET).weekday() == 4:
        other_times.append(("rotation-planner", now.astimezone(ET).replace(hour=20,minute=0,second=0,microsecond=0)))
    other_times += [(s.edition, t) for s,t in special_triggers(snapshot, now) if t is not None and
                    retryable(state.get(publication_key(s, now, snapshot.gameweek(), season_id(snapshot, now)), {}))]
    try:
        update, _ = official_clock({"game_config": snapshot.game_config}, max(now, snapshot.fetched_at))
        other_times.extend([("price-research", update-PRICE_RESEARCH_LEAD), ("price-prediction", update-PRICE_LEAD)])
    except (RequiredInput, AttributeError):
        # A missing price clock cannot authorize a conflicting run.
        return ["unverified-price-clock"]
    # Publication needs the existing cooldown on either side. Research occupies
    # a separate serialized heartbeat. In-flight/late work is checked by the dispatcher.
    distance = timedelta(minutes=15) if research else GAP
    return [name for name,t in other_times if abs(t-at) < distance]


def proof_valid(slot, row, season, gw, now):
    if not isinstance(row, dict):
        return False
    start = slot_start(slot, now)
    try:
        checked = datetime.fromisoformat(row["checked_at"])
        fetched = datetime.fromisoformat(row["source_at"])
        return (row["date"] == now.astimezone(ET).date().isoformat()
                and row["season"] == season and row["gw"] == gw
                and row["edition"] == slot.edition
                and checked.tzinfo is not None and fetched.tzinfo is not None
                and fetched <= checked and checked-fetched <= timedelta(minutes=30)
                and research_window(slot, checked)
                and verified_gap(row["checked_at"], start)
                and verified_gap(row["checked_at"], now)
                and (slot.edition != "most-transferred-in" or start.astimezone(timezone.utc)-checked.astimezone(timezone.utc) >= timedelta(hours=4))
                and len(set(row["player_ids"])) == (4 if slot.edition == "most-transferred-in" else 3))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def prepare(slot, snapshot, now, state, queue, ledger, clock):
    from .extra_posts import generate_extra
    from .fpl import upcoming_deadline
    if not research_window(slot, now) or conflicts(slot, snapshot, now, state, research=True):
        return False
    deadline = upcoming_deadline(snapshot)
    if not deadline or slot_start(slot, now) >= deadline:
        return False
    prior = state.get(RESEARCH_STATE, {}).get(slot.edition, {})
    if proof_valid(slot, prior, season_id(snapshot, now), snapshot.gameweek(), slot_start(slot, now)):
        return False
    article = generate_extra(KINDS[slot.edition], snapshot, now,
                             excluded_ids=claimed_ids(snapshot, now, queue, ledger))
    done = clock()
    row = {"date": now.astimezone(ET).date().isoformat(), "season": season_id(snapshot, now),
           "gw": snapshot.gameweek(), "edition": slot.edition, "checked_at": done.isoformat(),
           "source_at": snapshot.fetched_at.isoformat(), "player_ids": player_ids(article)}
    if not proof_valid(slot, row, row["season"], row["gw"], slot_start(slot, now)):
        return False
    state.setdefault(RESEARCH_STATE, {})[slot.edition] = row
    return True


def eligible(slot, snapshot, now, state):
    from .fpl import upcoming_deadline
    deadline = upcoming_deadline(snapshot)
    row = state.get(RESEARCH_STATE, {}).get(slot.edition)
    return (post_window(slot, now) and deadline is not None and now < deadline
            and not state.get(day_key(slot, now), {}).get("identity")
            and proof_valid(slot, row, season_id(snapshot, now), snapshot.gameweek(), now)
            and not conflicts(slot, snapshot, now, state))


def validate_record(record, now, publish_at):
    slot = next((s for s in slots(publish_at) if s.edition == record.get("edition")), None)
    facts = record.get("facts") or {}
    if (slot is None or not post_window(slot, publish_at) or not post_window(slot, now)
            or now.astimezone(ET).date() != publish_at.astimezone(ET).date()
            or not proof_valid(slot, facts.get("research"), record["season"], record["gameweek"], publish_at)
            or not proof_valid(slot, facts.get("research"), record["season"], record["gameweek"], now)):
        raise ValueError("Daily cutover requires verified research and its exact publication window")
    ids = facts.get("player_ids") or []
    if len(ids) != (4 if slot.edition == "most-transferred-in" else 3) or len(set(ids)) != len(ids) or not all(type(pid) is int for pid in ids):
        raise ValueError("Daily cutover requires distinct verified player IDs")
    return f"chatgpt:{publish_at.astimezone(ET).date()}:cutover:{slot.edition}"
