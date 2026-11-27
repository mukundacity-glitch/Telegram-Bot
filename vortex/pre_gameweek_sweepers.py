"""Slot 11: verified season-to-date sweeper actions before each target GW.

The existing FPL Core field is not a standard official FPL statistic.
Research and publishing remain disabled until the global release gate clears.
"""
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from math import isfinite
import json

from .autonomous_schedule import ET,Slot,season_id
from .editorial_inputs import RequiredInput
from .position_watch import clock,heartbeat,target as kickoff_target,WINDOW
from .post_gameweek_zones import settled_rounds,free,choose_post,proof_valid
from .post_gameweek_vulnerability import busy as matchup_busy
from .weekly_analysis import player_totals,common_row
from .recommendations import get_history

EDITION="weekly-sweeper-keepers"
STATE_KEY="_weekly_sweeper_keepers"
RELEASE_VERIFIED=False
MIN_MINUTES=220
MIN_GAP=timedelta(hours=3)

def key(season,gw):
    return f"{season}:GW{gw}:task2:{EDITION}"

def legacy_claimed(state,expected):
    # Do not replay a cohort previously covered by the existing series.
    prior=state.get(f"{expected['season']}:GW{expected['through']}:task2:weekly-analysis:day3",{})
    return bool(prior.get("identity") or prior.get("status") in ("delivered","already-delivered","sent","uncertain"))

def scope(snapshot,now):
    gw,kickoff,deadline=kickoff_target(snapshot)
    rounds=settled_rounds(snapshot)
    if not rounds or rounds!=list(range(1,gw)):
        raise RequiredInput("Complete officially finalized history before the next GW required")
    if now>=deadline:
        raise RequiredInput("Upcoming official transfer deadline elapsed")
    matches=sorted((f["id"],f["event"],f["team_h"],f["team_a"],f.get("team_h_score"),
                    f.get("team_a_score"),f["kickoff_time"]) for f in snapshot.fixtures
                   if f.get("event") in rounds+[gw])
    return {"season":season_id(snapshot,now),"gw":gw,"through":rounds[-1],
            "kickoff":kickoff.isoformat(),"deadline":deadline.isoformat(),
            "fixtures_digest":sha256(json.dumps(matches).encode()).hexdigest()}

def digest(extra):
    return sha256(json.dumps({k:extra[k] for k in ("rows","rate_leader","through","sources","minimum_minutes")},
                            sort_keys=True,separators=(",",":")).encode()).hexdigest()

def rank(snapshot,players,histories,through):
    rows=[]
    official={f["id"]:f for f in snapshot.fixtures if type(f.get("event")) is int
              and f["event"]<=through and f.get("finished") is True}
    for p,v in players:
        if p.get("element_type")!=1 or v["minutes"]<MIN_MINUTES:
            continue
        if v.get("incomplete_metrics"):
            raise RequiredInput("Missing goalkeeper sweeper actions in match archive")
        history=histories.get(p["id"],[])
        played=[r for r in history if type(r.get("round")) is int and r["round"]<=through
                and type(r.get("minutes")) is int and r["minutes"]>0]
        fixtures=[r.get("fixture") for r in played]
        if (not played or len(fixtures)!=len(set(fixtures)) or any(fid not in official for fid in fixtures)
                or any(official[r["fixture"]]["event"]!=r["round"] for r in played)
                or len(played)!=v["appearances"]):
            raise RequiredInput("Goalkeeper appearance coverage differs from official FPL history")
        minutes=float(v["minutes"])
        value=float(v["sweeper_actions"])
        if not isfinite(value) or value<0 or not value.is_integer() or not isfinite(minutes) or minutes<=0:
            raise RequiredInput("Invalid sweeper action or minute count")
        row=common_row(snapshot,p,v,int(value),
                       f"{value*90/minutes:.2f}/90 · {int(minutes)} min · {len(played)} apps")
        rows.append({**row,"id":p["id"],"rate":value*90/minutes,"apps":len(played)})
    if len(rows)<12 or len({r["id"] for r in rows})!=len(rows):
        raise RequiredInput("Twelve unique verified goalkeepers required")
    if any(not r["code"] for r in rows):
        raise RequiredInput("Official goalkeeper club identity unavailable")
    leader=max(rows,key=lambda r:(r["rate"],r["value"],r["minutes"],-r["id"]))
    return sorted(rows,key=lambda r:(-r["value"],-r["rate"],r["name"],r["id"]))[:12],leader

def build(snapshot,now,evidence,proof=None):
    from .autonomous_content import Plan
    expected=scope(snapshot,now)
    players,sources=player_totals(snapshot,expected["through"],evidence.session,
        int(expected["season"].split("-")[0]),("sweeper_actions",),
        required_nonblank_by_position={1:("sweeper_actions",)})
    keepers=[p for p,v in players if p.get("element_type")==1 and v["minutes"]>=MIN_MINUTES]
    with ThreadPoolExecutor(max_workers=6) as pool:
        histories=dict(zip((p["id"] for p in keepers),
                           pool.map(lambda p:get_history(p["id"],evidence.session),keepers)))
    rows,leader=rank(snapshot,players,histories,expected["through"])
    sources=list(sources)+[f"https://fantasy.premierleague.com/api/element-summary/{p['id']}/" for p in keepers]
    extra={"rows":rows,"rate_leader":leader,"through":expected["through"],"sources":sources,
           "minimum_minutes":MIN_MINUTES,"research":proof or {}}
    if proof is not None and digest(extra)!=proof.get("data_digest"):
        raise RequiredInput("Sweeper ranking changed since advance research")
    gw=expected["gw"]
    caption="\n".join((f"GW{gw} | SWEEPER KEEPERS",
        f"{rows[0]['name']} leads with {rows[0]['value']} recorded sweeper actions.",
        f"Per 90 leader: {leader['name']} · {leader['rate']:.2f}.",
        f"Through GW{expected['through']} · FPL Core match metrics · Check minutes and fixtures.",
        f"#FPL #GW{gw} #FPLTips #FPLVORTEX"))
    return Plan("task2",EDITION,"SWEEPER KEEPERS",caption,gw,[],[],"weekly_sweeper_keepers",extra)

def reservations(snapshot,now,state,anchor):
    other={k:v for k,v in state.items() if k!=STATE_KEY}
    result=matchup_busy(snapshot,now,other,anchor)
    from .telegram_spacing import GAP
    row=other.get("_post_gameweek_vulnerability",{})
    if row.get("season")==season_id(snapshot,now):
        r,p=clock(row["research_at"]),clock(row["post_at"])
        result.extend((("vulnerability-research",r,r+WINDOW),("vulnerability-post",p-GAP,p+GAP+WINDOW)))
    return result

def valid(proof,expected,now,*,posting=True):
    return (proof_valid(proof,expected,now,posting=posting)
            and clock(proof["post_at"])+WINDOW<=clock(expected["deadline"])
            and now<clock(expected["deadline"]))

def prepare(snapshot,now,state,evidence,clock_now):
    if not RELEASE_VERIFIED:
        return False
    try:
        expected=scope(snapshot,now)
        if legacy_claimed(state,expected) or state.get(key(expected["season"],expected["gw"]),{}).get("identity"):
            return False
        old=state.get(STATE_KEY,{})
        if valid(old,expected,now,posting=False) and now<clock(old["post_at"])+WINDOW:
            return False
        minute=now.astimezone(timezone.utc).replace(second=0,microsecond=0)
        research=next((minute-timedelta(minutes=i) for i in range(10)
                       if heartbeat(minute-timedelta(minutes=i))),None)
        if research is None or not research<=now<research+WINDOW:
            return False
        busy=reservations(snapshot,now,state,research)
        if not free(research,busy):
            return False
        post=choose_post(research,busy)
        if post is None or post+WINDOW>clock(expected["deadline"]):
            return False
        plan=build(snapshot,now,evidence)
        proof={**expected,"research_at":research.isoformat(),"post_at":post.isoformat(),
               "checked_at":clock_now().isoformat(),"source_at":snapshot.fetched_at.isoformat(),
               "data_digest":digest(plan.extra)}
        if not valid(proof,expected,now,posting=False):
            return False
        state[STATE_KEY]=proof
        return True
    except (RuntimeError,ValueError,KeyError,TypeError,AttributeError,OSError):
        return False

def eligible(snapshot,now,state):
    if not RELEASE_VERIFIED:
        return None
    try:
        expected=scope(snapshot,now)
        proof=state.get(STATE_KEY,{})
        if (legacy_claimed(state,expected) or not valid(proof,expected,now)
                or state.get(key(expected["season"],expected["gw"]),{}).get("status") in ("delivered","already-delivered")):
            return None
        post=clock(proof["post_at"])
        if not free(post,reservations(snapshot,now,state,post)):
            return None
        local=post.astimezone(ET)
        return Slot("task2",EDITION,local.hour,local.minute)
    except (RuntimeError,ValueError,KeyError,TypeError,AttributeError):
        return None

def validate_record(record,now,publish_at,*,manual=False):
    extra=(record.get("facts") or {}).get("extra") or {}
    proof=extra.get("research") or {}
    if (not RELEASE_VERIFIED or manual or record.get("task")!="task2"
            or len(record.get("images") or [])!=1 or proof.get("season")!=record.get("season")
            or proof.get("gw")!=record.get("gameweek") or proof.get("deadline")!=record.get("deadline")):
        raise ValueError("Sweeper keepers release gate closed")
    from .autonomous_runner import STATE_FILE
    from .bot import read_state
    from .fpl import collect_snapshot
    state=read_state(STATE_FILE)
    if state.get(STATE_KEY)!=proof or digest(extra)!=proof.get("data_digest"):
        raise ValueError("Sweeper keeper research evidence mismatch")
    snapshot=collect_snapshot()
    fresh=max(now,snapshot.fetched_at)
    if not valid(proof,scope(snapshot,fresh),publish_at) or eligible(snapshot,fresh,state) is None:
        raise ValueError("Sweeper keeper official GW or reservation changed")
    return "chatgpt:"+key(record["season"],record["gameweek"])

def audit():
    from .autonomous_content import Evidence,retrying_session
    from .fpl import collect_snapshot
    from .premium_sweeper_render import render
    from PIL import Image
    session=retrying_session()
    snapshot=collect_snapshot(session)
    now=datetime.now(timezone.utc)
    plan=build(snapshot,now,Evidence(snapshot,now,session))
    output=Path("output/sweeper-keepers-audit/sweeper-keepers.png")
    render(plan,output,session)
    with Image.open(output) as im:
        if im.size!=(1080,1920):
            raise ValueError("Sweeper keepers portrait contract failed")
        im.verify()
    print(json.dumps({"at":now.isoformat(),"gw":plan.gw,"through":plan.extra["through"],
                      "keepers":len(plan.extra["rows"]),"release_verified":RELEASE_VERIFIED,"mode":"read-only"}))

if __name__=="__main__":
    audit()
