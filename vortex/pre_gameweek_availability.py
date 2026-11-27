"""Slot 9: pre-kickoff transfer decisions, one edition per season/GW."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from math import isfinite
import json
from .autonomous_schedule import ET,Slot,season_id
from .position_watch import target,clock,heartbeat,reservations,WINDOW
from .post_gameweek_zones import free
from .publishing_window import allowed
from .research_gap import verified_gap
from .editorial_inputs import RequiredInput
from .availability_board import select,TIERS,ACTIONS

EDITION="weekly-availability-decisions"
STATE_KEY="_weekly_availability_decisions"
RELEASE_VERIFIED=False
MIN_LEAD=timedelta(hours=3,minutes=30)
MAX_LEAD=timedelta(hours=4,minutes=30)

def key(season,gw):
    return f"{season}:GW{gw}:task2:{EDITION}"

def choose_schedule(kickoff,deadline,busy):
    candidates=[]
    start=(kickoff-MAX_LEAD).replace(second=0,microsecond=0)
    for n in range(61):
        post=start+timedelta(minutes=n)
        if (heartbeat(post) and post>=kickoff-MAX_LEAD
                and post+WINDOW<=min(kickoff-MIN_LEAD,deadline)
                and allowed(post) and allowed(post+WINDOW) and free(post,busy)):
            candidates.append(post)
    for post in sorted(candidates,key=lambda p:(abs(kickoff-p-timedelta(hours=4)),p)):
        for lead in range(195,361,15):
            research=post-timedelta(minutes=lead)
            if heartbeat(research) and free(research,busy):
                return research,post
    return None

def schedule(snapshot,now,state):
    try:
        gw,kickoff,deadline=target(snapshot)
        busy=reservations(snapshot,now,state,kickoff)
        from .position_watch import schedule as position_schedule
        from .telegram_spacing import GAP
        position=position_schedule(snapshot,now,state)
        for label,row in (("position",position),("shot-origins",state.get("_post_gameweek_shot_origins"))):
            if row and row.get("season")==season_id(snapshot,now):
                r,p=clock(row["research_at"]),clock(row["post_at"])
                busy.extend(((label+"-research",r,r+WINDOW),(label+"-post",p-GAP,p+GAP+WINDOW)))
        pair=choose_schedule(kickoff,deadline,busy)
        if pair is None:
            return None
        research,post=pair
        return {"season":season_id(snapshot,now),"gw":gw,"kickoff":kickoff.isoformat(),
                "deadline":deadline.isoformat(),"research_at":research.isoformat(),"post_at":post.isoformat()}
    except (RuntimeError,ValueError,KeyError,TypeError,AttributeError):
        return None

def phase(row,now):
    if row:
        for name,field in (("research","research_at"),("post","post_at")):
            at=clock(row[field])
            if at<=now<at+WINDOW:
                return name
    return None

def proof_valid(proof,expected,now,*,posting=True):
    try:
        if not expected or any(proof.get(k)!=v for k,v in expected.items()):
            return False
        checked,source=clock(proof["checked_at"]),clock(proof["source_at"])
        research,post=clock(proof["research_at"]),clock(proof["post_at"])
        kickoff,deadline=clock(proof["kickoff"]),clock(proof["deadline"])
        tiers=proof["tiers"]
        ids=[pid for tier in TIERS for pid in tiers[tier]]
        return (set(tiers)==set(TIERS) and all(len(tiers[t])==5 for t in TIERS)
                and len(ids)==len(set(ids))==25 and all(type(pid) is int for pid in ids)
                and heartbeat(research) and heartbeat(post) and research<=checked<research+WINDOW
                and source<=checked and checked-source<=timedelta(minutes=30)
                and post-(research+WINDOW)>=timedelta(hours=3)
                and verified_gap(proof["checked_at"],post)
                and kickoff-MAX_LEAD<=post and post+WINDOW<=min(kickoff-MIN_LEAD,deadline)
                and (not posting or (phase(expected,now)=="post" and allowed(now)
                                    and verified_gap(proof["checked_at"],now))))
    except (ValueError,KeyError,TypeError,AttributeError):
        return False

def signals(snapshot,evidence,excluded):
    """Only factual availability/minutes signals; no personalized sell advice."""
    result={}
    pool=[p for p in snapshot.players if type(p.get("id")) is int and p["id"] not in excluded
          and p.get("status") in ("a","d","i","s","u") and type(p.get("transfers_out_event")) is int]
    pool.sort(key=lambda p:(-p["transfers_out_event"],p["id"]))
    for p in pool[:40]:
        status=p["status"]
        chance=p.get("chance_of_playing_next_round")
        label=reason=None
        if status in ("i","s","u") and p["transfers_out_event"]>0:
            label,reason="SELL REVIEW",{"i":"injured","s":"suspended","u":"unavailable"}[status]
        elif status=="d" or (type(chance) is int and chance<75):
            label,reason="AVOID","availability doubt"
        elif status=="a":
            recent=evidence.recent(p)
            if len(recent)==3 and all(type(r.get("minutes")) is int and r["minutes"]>=70 for r in recent):
                label,reason="HOLD","3 recent matches 70+ min"
        if label and label not in result:
            result[label]={"id":p["id"],"name":snapshot.name(p),"reason":reason,
                           "out":p["transfers_out_event"]}
        if len(result)==3:
            break
    return result

def build(snapshot,now,evidence,proof=None,*,audit=False):
    from .autonomous_content import Plan
    selected,tiers,meta=select(snapshot,now,evidence,session=evidence.session)
    ids=[pid for tier in TIERS for pid in tiers[tier]]
    if len(ids)!=len(set(ids)):
        raise RequiredInput("Duplicate availability player")
    if not audit and any(len(tiers[t])!=5 for t in TIERS):
        raise RequiredInput("Five verified players per tier required; do not fill with weak picks")
    if proof is not None and tiers!=proof["tiers"]:
        raise RequiredInput("Availability ranking changed since research; hold rather than replace researched picks")
    gw=snapshot.gameweek()
    rows={str(r["player"]["id"]):r for r in selected}
    decisions=signals(snapshot,evidence,set(ids))
    covered=sum(r["xpts5"] is not None for r in selected)
    caption="\n".join((f"GW{gw} | AVAILABILITY & TRANSFER DECISIONS",
        f"{len(ids)} verified selections · five tiers · last three match minutes.",
        f"xPts5 verified for {covered}/{len(ids)}; dash means unavailable, not zero.",
        "Review availability, fixtures and hold/sell/avoid signals before transferring.",
        f"#FPL #GW{gw} #FPLTips #FPLVORTEX"))
    return Plan("task2",EDITION,"AVAILABILITY & TRANSFER DECISIONS",caption,gw,
        [r["player"] for r in selected],[ACTIONS[TIERS.index(t)] for t in TIERS for _ in tiers[t]],
        "weekly_availability",{"tiers":tiers,"rows":rows,"method":meta,"signals":decisions,"research":proof or {}})

def prepare(snapshot,now,state,evidence,clock_now):
    if not RELEASE_VERIFIED:
        return False
    row=schedule(snapshot,now,state)
    if phase(row,now)!="research" or proof_valid(state.get(STATE_KEY,{}),row,now,posting=False):
        return False
    if state.get(key(row["season"],row["gw"]),{}).get("identity"):
        return False
    plan=build(snapshot,now,evidence)
    proof={**row,"tiers":plan.extra["tiers"],"checked_at":clock_now().isoformat(),
           "source_at":snapshot.fetched_at.isoformat()}
    if not proof_valid(proof,row,now,posting=False):
        return False
    state[STATE_KEY]=proof
    return True

def eligible(snapshot,now,state):
    if not RELEASE_VERIFIED:
        return None
    row=schedule(snapshot,now,state)
    if not proof_valid(state.get(STATE_KEY,{}),row,now):
        return None
    if state.get(key(row["season"],row["gw"]),{}).get("status") in ("delivered","already-delivered"):
        return None
    local=clock(row["post_at"]).astimezone(ET)
    return Slot("task2",EDITION,local.hour,local.minute)

def validate_record(record,now,publish_at,*,manual=False):
    facts=record.get("facts") or {}
    extra=facts.get("extra") or {}
    proof=extra.get("research") or {}
    if (not RELEASE_VERIFIED or manual or record.get("task")!="task2"
            or len(record.get("images") or [])!=1 or proof.get("season")!=record.get("season")
            or proof.get("gw")!=record.get("gameweek") or proof.get("deadline")!=record.get("deadline")):
        raise ValueError("Availability release gate closed")
    from .autonomous_runner import STATE_FILE
    from .bot import read_state
    from .fpl import collect_snapshot
    state=read_state(STATE_FILE)
    if state.get(STATE_KEY)!=proof or extra.get("tiers")!=proof.get("tiers"):
        raise ValueError("Availability research evidence mismatch")
    snapshot=collect_snapshot()
    fresh=max(now,snapshot.fetched_at)
    if not proof_valid(proof,schedule(snapshot,fresh,state),publish_at) or eligible(snapshot,fresh,state) is None:
        raise ValueError("Availability official kickoff or publication window changed")
    return "chatgpt:"+key(record["season"],record["gameweek"])

def audit():
    from .autonomous_content import Evidence,retrying_session
    from .fpl import collect_snapshot
    from .weekly_availability_render import render
    from PIL import Image
    session=retrying_session()
    snapshot=collect_snapshot(session)
    now=datetime.now(timezone.utc)
    plan=build(snapshot,now,Evidence(snapshot,now,session),audit=True)
    output=Path("output/availability-audit/availability.png")
    render(plan,snapshot,output,session)
    with Image.open(output) as im:
        if im.size!=(1920,1080):
            raise ValueError("Availability landscape contract failed")
        im.verify()
    print(json.dumps({"at":now.isoformat(),"gw":plan.gw,
        "counts":{t:len(plan.extra["tiers"][t]) for t in TIERS},
        "xpts5_covered":sum(r["xpts5"] is not None for r in plan.extra["rows"].values()),
        "candidate":schedule(snapshot,now,{}),"release_verified":RELEASE_VERIFIED,"mode":"read-only"}))

if __name__=="__main__":
    audit()
