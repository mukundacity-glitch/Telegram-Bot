"""Slot 7: one four-position board per official upcoming GW.

Branch implementation only. The release gate is deliberately closed until
the outstanding live settlement, all-legacy scheduling and delivery audits
are verified. No additional cron or publisher is required.
"""
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path

from .autonomous_schedule import ET, Slot, season_id
from .research_gap import verified_gap
from .editorial_inputs import RequiredInput

EDITION = "weekly-position-watch"
STATE_KEY = "_weekly_pre_kickoff_position_watch"
RELEASE_VERIFIED = False
WINDOW = timedelta(minutes=10)
MIN_LEAD = timedelta(hours=7)
MAX_LEAD = timedelta(hours=8)
GROUPS = ((1, "GOALKEEPER WATCH", 2), (2, "DEFENDER WATCH", 4),
          (3, "MIDFIELDER WATCH", 4), (4, "STRIKER WATCH", 3))


def clock(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Official timezone required")
    return stamp.astimezone(timezone.utc)


def target(snapshot):
    """Bootstrap identifies the event; fixtures provide the actual first kickoff."""
    gw = snapshot.gameweek()
    event = next((e for e in snapshot.events if e.get("id") == gw), {})
    if not gw or event.get("finished") or not event.get("deadline_time"):
        raise RequiredInput("Upcoming FPL event unavailable")
    matches = [m for m in snapshot.fixtures if m.get("event") == gw]
    if not matches or any(m.get("started") or m.get("finished") or not m.get("kickoff_time") for m in matches):
        raise RequiredInput("Complete, unstarted official GW fixture times required")
    try:
        kickoff = min(clock(m["kickoff_time"]) for m in matches)
        deadline = clock(event["deadline_time"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise RequiredInput("Invalid official kickoff/deadline") from exc
    if deadline >= kickoff:
        raise RequiredInput("Inconsistent official deadline")
    return gw, kickoff, deadline


def heartbeat(at):
    """Guaranteed existing quarter-hour UTC cron family, including overnight."""
    return at.minute in (13, 28, 43, 58) and at.second == 0 and at.microsecond == 0


def choose_schedule(kickoff, deadline, busy):
    """Find a research and post window on existing serialized heartbeats.

    busy: (name, inclusive start, exclusive end) reservations in aware time.
    Every candidate remains in the seven-to-eight-hour pre-kickoff interval.
    A late runner is held, not moved outside the specified window.
    """
    from .publishing_window import allowed
    def free(at):
        return not any(at < end and start < at + WINDOW for _, start, end in busy)
    start = (kickoff-MAX_LEAD).replace(second=0, microsecond=0)
    for offset in range(61):
        post = start+timedelta(minutes=offset)
        if (not heartbeat(post) or post < kickoff-MAX_LEAD
                or post+WINDOW > min(kickoff-MIN_LEAD, deadline)
                or not allowed(post) or not allowed(post+WINDOW) or not free(post)):
            continue
        # Research must finish at least three elapsed hours before the post.
        for lead in range(195, 361, 15):
            research = post-timedelta(minutes=lead)
            if heartbeat(research) and free(research):
                return research, post
    return None


def reservations(snapshot, now, state, kickoff):
    """Current known fixed, daily, research and dynamic reservations.

    Price has priority. Unknown official price clock holds Slot 7. Dynamic
    press/catch-up work also preempts at dispatch. Global verification remains
    a separate prerequisite; this list is not a claim of full legacy coverage.
    """
    from .autonomous_schedule import SLOTS, eligible_on, slot_start, special_triggers, publication_key, retryable
    from .schedule import SLOT_HOURS
    from .daily_cutover import slots
    from .price_prediction_board import official_clock, price_schedule
    from .telegram_spacing import GAP
    busy = []
    def post(name, at):
        busy.append((name, at.astimezone(timezone.utc)-GAP, at.astimezone(timezone.utc)+GAP+WINDOW))
    def check(name, at, minutes):
        at = at.astimezone(timezone.utc)
        busy.append((name, at, at+timedelta(minutes=minutes)))
    anchor = kickoff.astimezone(ET)
    for delta in (-2, -1, 0, 1):
        day = anchor+timedelta(days=delta)
        for s in (*SLOTS, *slots(day)):
            if eligible_on(s, day):
                post(s.edition, slot_start(s, day))
        for name, (hour, minute) in SLOT_HOURS.items():
            post(name, day.replace(hour=hour, minute=minute, second=0, microsecond=0))
        checks = [("transfer-research",1,13,17), ("desk-research",4,13,15),
                  ("radar-research",5,58,12)]
        if day.weekday() == 4:
            post("weekly-rotation", day.replace(hour=20,minute=0,second=0,microsecond=0))
        if day.weekday() in (4,5):
            checks.append(("matrix-research",15,28,12))
        if day.weekday() == 0:
            checks.extend([("legacy-position",3,13,15), ("legacy-defence",4,43,15)])
        if day.weekday() == 1:
            checks.append(("legacy-wildcard",3,13,15))
        for name,h,m,length in checks:
            check(name,day.replace(hour=h,minute=m,second=0,microsecond=0),length)
    gw, season = snapshot.gameweek(), season_id(snapshot, now)
    for s, at in special_triggers(snapshot, now):
        if at is not None and retryable(state.get(publication_key(s,now,gw,season),{})):
            post(s.edition,at)
    update, _ = official_clock({"game_config":snapshot.game_config},max(now,snapshot.fetched_at))
    check_at, post_at, _ = price_schedule(snapshot,now,update,state)
    if check_at is not None and post_at is not None:
        check("price-research",check_at,15)
        post("price-prediction",post_at)
    return busy


def schedule(snapshot, now, state):
    try:
        gw, kickoff, deadline = target(snapshot)
        busy = reservations(snapshot,now,state,kickoff)
        # Respect the other edition's durable reservation without recursion.
        from .telegram_spacing import GAP
        zones = state.get("_post_gameweek_shot_origins",{})
        if zones.get("season")==season_id(snapshot,now):
            zr,zp=clock(zones["research_at"]),clock(zones["post_at"])
            busy.extend((("shot-origins-research",zr,zr+WINDOW),
                         ("shot-origins-post",zp-GAP,zp+GAP+WINDOW)))
        availability = state.get("_weekly_availability_decisions",{})
        if availability.get("season")==season_id(snapshot,now):
            ar,ap=clock(availability["research_at"]),clock(availability["post_at"])
            busy.extend((("availability-research",ar,ar+WINDOW),
                         ("availability-post",ap-GAP,ap+GAP+WINDOW)))
        selected = choose_schedule(kickoff,deadline,busy)
        if selected is None:
            return None
        research, post = selected
        return {"season":season_id(snapshot,now),"gw":gw,"kickoff":kickoff.isoformat(),
                "deadline":deadline.isoformat(),"research_at":research.isoformat(),"post_at":post.isoformat()}
    except (RequiredInput, ValueError, TypeError, KeyError, AttributeError):
        return None


def key(season, gw):
    return f"{season}:GW{gw}:task2:{EDITION}"


def phase(schedule_row, now):
    if not schedule_row:
        return None
    for name, field in (("research","research_at"),("post","post_at")):
        start = clock(schedule_row[field])
        if start <= now < start+WINDOW:
            return name
    return None


def proof_valid(proof, expected, now, *, posting=True):
    try:
        if not expected or any(proof.get(k) != v for k,v in expected.items()):
            return False
        checked, source = clock(proof["checked_at"]),clock(proof["source_at"])
        research, post = clock(proof["research_at"]),clock(proof["post_at"])
        kickoff, deadline = clock(proof["kickoff"]),clock(proof["deadline"])
        groups = proof["groups"]
        ids = [pid for pos,_,count in GROUPS for pid in groups[str(pos)]]
        if (set(groups) != {str(p) for p,_,_ in GROUPS}
                or any(len(groups[str(p)]) != count for p,_,count in GROUPS)
                or len(ids) != 13 or len(set(ids)) != 13 or any(type(pid) is not int for pid in ids)):
            return False
        return (heartbeat(research) and heartbeat(post)
                and research <= checked < research+WINDOW
                and source <= checked and checked-source <= timedelta(minutes=30)
                and verified_gap(proof["checked_at"],post)
                and kickoff-MAX_LEAD <= post and post+WINDOW <= min(kickoff-MIN_LEAD,deadline)
                and (not posting or (phase(expected,now) == "post" and verified_gap(proof["checked_at"],now))))
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def number(value):
    try:
        if isinstance(value,bool) or value is None or value == "":
            raise ValueError
        value = float(value)
        if not isfinite(value) or value < 0:
            raise ValueError
        return value
    except (ValueError,TypeError) as exc:
        raise RequiredInput("Missing/non-finite official metric") from exc


def player_card(snapshot, player, evidence):
    """No missing-as-zero or duplicated fixture history."""
    from .recommendations import get_history
    from .publication_rules import five_gw_fixtures
    pid, pos = player["id"], player["element_type"]
    if (type(pid) is not int or player.get("status") != "a" or not snapshot.photo_code(player)
            or not snapshot.team_code(player) or not player.get("web_name")
            or type(player.get("now_cost")) is not int or player["now_cost"] <= 0
            or any(type(player.get(k)) is not int or player[k]<0 for k in ("transfers_in_event","transfers_out_event"))):
        raise RequiredInput("Incomplete current player identity/transfer fields")
    own = number(player.get("selected_by_percent"))
    if own > 100:
        raise RequiredInput("Invalid ownership")
    settled = {e["id"] for e in snapshot.events if e.get("finished") is True and e.get("data_checked") is True}
    completed = {m["id"]:m for m in snapshot.fixtures if m.get("finished") is True and m.get("event") in settled and m.get("kickoff_time")}
    if pid not in evidence.history:
        rows = [r for r in get_history(pid,evidence.session) if r.get("fixture") in completed
                and r.get("round") == completed[r["fixture"]].get("event")]
        if len({r["fixture"] for r in rows}) != len(rows):
            raise RequiredInput("Duplicate official history fixture")
        rows.sort(key=lambda r:clock(completed[r["fixture"]]["kickoff_time"]))
        evidence.history[pid] = rows[-3:]
    rows = evidence.history[pid]
    if len(rows) != 3:
        raise RequiredInput("Three completed match records required")
    mins = [number(r.get("minutes")) for r in rows]
    if any(m != int(m) or m < 60 or m > 120 for m in mins):
        raise RequiredInput("Insufficient verified recent minutes")
    keys = ("clean_sheets","expected_goals_conceded","saves") if pos == 1 else (
        ("clean_sheets","expected_goals_conceded") if pos == 2 else
        ("expected_goals","expected_assists","expected_goal_involvements"))
    totals = {k:sum(number(r.get(k)) for r in rows) for k in keys}
    fixtures = list(five_gw_fixtures(snapshot,player))
    return {"id":pid,"position":pos,"minutes":[int(m) for m in mins],"metrics":totals,"fixtures":fixtures,
            "ownership":own,"in":player["transfers_in_event"],"out":player["transfers_out_event"]}


def build(slot, snapshot, now, evidence, proof=None):
    from .autonomous_content import Plan
    selected, cards, groups = [], {}, {}
    for pos, label, count in GROUPS:
        if proof is None:
            pool = [p for p in snapshot.players if p.get("element_type")==pos and p.get("status")=="a"
                    and type(p.get("transfers_in_event")) is int]
            pool.sort(key=lambda p:(-p["transfers_in_event"],p["id"]))
            pool = pool[:18]
        else:
            wanted = proof["groups"][str(pos)]
            by_id = {p["id"]:p for p in snapshot.players if p.get("element_type")==pos}
            if any(pid not in by_id for pid in wanted):
                raise RequiredInput("Researched player identity changed")
            pool = [by_id[pid] for pid in wanted]
        groups[str(pos)] = []
        for player in pool:
            try:
                card = player_card(snapshot,player,evidence)
            except (RequiredInput,ValueError,TypeError,KeyError):
                if proof is not None:
                    raise
                continue
            if card["id"] in cards:
                raise RequiredInput("Duplicate player across position groups")
            selected.append(player)
            cards[card["id"]] = card
            groups[str(pos)].append(card["id"])
            if len(groups[str(pos)]) == count:
                break
        if len(groups[str(pos)]) != count:
            raise RequiredInput("Insufficient verified players for "+label)
    gw = snapshot.gameweek()
    caption = "\n".join((f"GW{gw} | EXPECTED STATS & POSITION WATCH",
        "2 GK · 4 DEF · 4 MID · 3 FWD — official transfer-led shortlist.",
        "Last three completed matches; next five gameweeks and official FDR.",
        "MONITOR team news, minutes and fixtures before making transfers.",
        f"#FPL #GW{gw} #FPLTips #FPLVORTEX"))
    return Plan(slot.task,EDITION,"EXPECTED STATS & POSITION WATCH",caption,gw,selected,
                ["MONITOR"]*len(selected),kind="weekly_position_watch",
                extra={"cards":cards,"groups":groups,"research":proof or {}})


def prepare(snapshot, now, state, evidence, clock_now):
    if not RELEASE_VERIFIED:
        return False
    row = schedule(snapshot,now,state)
    if phase(row,now) != "research":
        return False
    prior = state.get(STATE_KEY,{})
    if proof_valid(prior,row,now,posting=False):
        return False
    if state.get(key(row["season"],row["gw"]),{}).get("identity"):
        return False
    plan = build(Slot("task2",EDITION,0),snapshot,now,evidence)
    proof = {**row,"groups":plan.extra["groups"],"checked_at":clock_now().isoformat(),
             "source_at":snapshot.fetched_at.isoformat()}
    if not proof_valid(proof,row,now,posting=False):
        return False
    state[STATE_KEY] = proof
    return True


def eligible(snapshot, now, state):
    if not RELEASE_VERIFIED:
        return None
    row = schedule(snapshot,now,state)
    proof = state.get(STATE_KEY,{})
    if not proof_valid(proof,row,now):
        return None
    if state.get(key(row["season"],row["gw"]),{}).get("status") in ("delivered","already-delivered"):
        return None
    local = clock(row["post_at"]).astimezone(ET)
    return Slot("task2",EDITION,local.hour,local.minute)


def validate_record(record, now, publish_at, *, manual=False):
    from .publishing_window import allowed
    facts = record.get("facts") or {}
    extra = facts.get("extra") or {}
    proof = extra.get("research") or {}
    expected = {k:proof.get(k) for k in ("season","gw","kickoff","deadline","research_at","post_at")}
    if (not RELEASE_VERIFIED or manual or record.get("task")!="task2"
            or len(record.get("images") or [])!=1 or proof.get("season")!=record.get("season")
            or proof.get("gw")!=record.get("gameweek") or proof.get("deadline")!=record.get("deadline")
            or not allowed(now) or not allowed(publish_at)
            or not proof_valid(proof,expected,publish_at) or not proof_valid(proof,expected,now)):
        raise ValueError("Position Watch release/research/publication gate is closed")
    expected_ids = [pid for pos,_,_ in GROUPS for pid in proof["groups"][str(pos)]]
    if extra.get("groups") != proof["groups"] or facts.get("player_ids") != expected_ids:
        raise ValueError("Position Watch players do not match the researched groups")
    # Recheck official fixture/deadline and current reserved windows at the
    # final publisher boundary, not only at the start of the rendering run.
    from .autonomous_runner import STATE_FILE
    from .bot import read_state
    from .fpl import collect_snapshot
    state = read_state(STATE_FILE)
    if state.get(STATE_KEY) != proof:
        raise ValueError("Position Watch lacks matching durable research evidence")
    snapshot = collect_snapshot()
    fresh_now = max(now,snapshot.fetched_at)
    if not proof_valid(proof,schedule(snapshot,fresh_now,state),fresh_now):
        raise ValueError("Position Watch live kickoff or publication window changed")
    return "chatgpt:"+key(record["season"],record["gameweek"])


def audit():
    """Read-only branch QA: no scheduling, publication, receipts or state mutation."""
    from .autonomous_content import Evidence,retrying_session
    from .fpl import collect_snapshot
    from .position_watch_render import render_position_watch
    from PIL import Image
    import json
    session=retrying_session()
    snapshot=collect_snapshot(session)
    now=datetime.now(timezone.utc)
    plan=build(Slot("task2",EDITION,0),snapshot,now,Evidence(snapshot,now,session))
    output=Path("output/position-watch-audit/position-watch.png")
    render_position_watch(plan,snapshot,output,session)
    with Image.open(output) as image:
        if image.size!=(1920,1080):
            raise ValueError("Landscape contract failed")
        image.verify()
    print(json.dumps({"at":now.isoformat(),"gw":plan.gw,"groups":plan.extra["groups"],
                      "size":[1920,1080],"candidate":schedule(snapshot,now,{}),
                      "release_verified":RELEASE_VERIFIED,"mode":"read-only"},default=str))


if __name__ == "__main__":
    audit()
