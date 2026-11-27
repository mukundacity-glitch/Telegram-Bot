"""Slot 8: one post after each officially settled FPL gameweek.

Release disabled until the shared cutover validation is complete. The retired
Thursday route remains retired; the Monday combined edition is not deleted.
"""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from pathlib import Path
import json

from .autonomous_schedule import Slot,season_id
from .editorial_inputs import RequiredInput
from .position_watch import clock,heartbeat,reservations,WINDOW
from .research_gap import verified_gap
from .publishing_window import allowed

EDITION="post-gameweek-shot-origins"
STATE_KEY="_post_gameweek_shot_origins"
RELEASE_VERIFIED=False
MIN_GAP=timedelta(hours=3)
MAX_HORIZON=timedelta(days=2)


def settled_rounds(snapshot):
    """Only official finished + data_checked events with every assigned fixture finished."""
    rounds=[]
    for event in snapshot.events:
        gw=event.get("id")
        if type(gw) is not int or event.get("finished") is not True or event.get("data_checked") is not True:
            continue
        fixtures=[f for f in snapshot.fixtures if f.get("event")==gw]
        if fixtures and all(f.get("finished") is True and f.get("kickoff_time")
                            and type(f.get("id")) is int for f in fixtures):
            rounds.append(gw)
    return sorted(set(rounds))


def target(snapshot):
    weeks=settled_rounds(snapshot)[-5:]
    if not weeks or len(snapshot.teams)!=20:
        raise RequiredInput("Official finalized GW and 20 clubs required")
    # Never publish an older settlement once a newer finished round is pending
    # official data checking (which would mislabel the latest review).
    if any(type(e.get("id")) is int and e["id"]>weeks[-1] and e.get("finished") is True
           for e in snapshot.events):
        raise RequiredInput("Latest finished GW is not fully settled")
    return weeks


def key(season,gw):
    return f"{season}:GW{gw}:task2:{EDITION}"


def free(at,busy):
    return not any(at<end and start<at+WINDOW for _,start,end in busy)


def choose_post(research,busy):
    """Earliest existing heartbeat after three hours from research-window end."""
    start=(research+WINDOW+MIN_GAP).replace(second=0,microsecond=0)
    for offset in range(int(MAX_HORIZON.total_seconds()/60)+1):
        post=start+timedelta(minutes=offset)
        if heartbeat(post) and allowed(post) and allowed(post+WINDOW) and free(post,busy):
            return post
    return None


def busy_windows(snapshot,now,state,anchor):
    from .position_watch import schedule as position_schedule
    from .telegram_spacing import GAP
    busy=reservations(snapshot,now,state,anchor)
    position=position_schedule(snapshot,now,state)
    if position:
        r,p=clock(position["research_at"]),clock(position["post_at"])
        busy.extend((("position-watch-research",r,r+WINDOW),
                     ("position-watch-post",p-GAP,p+GAP+WINDOW)))
    availability=state.get("_weekly_availability_decisions",{})
    if availability.get("season")==season_id(snapshot,now):
        r,p=clock(availability["research_at"]),clock(availability["post_at"])
        busy.extend((("availability-research",r,r+WINDOW),("availability-post",p-GAP,p+GAP+WINDOW)))
    matchup=state.get("_post_gameweek_vulnerability",{})
    if matchup.get("season")==season_id(snapshot,now):
        mr,mp=clock(matchup["research_at"]),clock(matchup["post_at"])
        busy.extend((("vulnerability-research",mr,mr+WINDOW),("vulnerability-post",mp-GAP,mp+GAP+WINDOW)))
    return busy


def scope(snapshot,now):
    weeks=target(snapshot)
    fixtures=sorted((f["id"],f["event"],f["team_h"],f["team_a"],f["team_h_score"],f["team_a_score"],
                     f["kickoff_time"]) for f in snapshot.fixtures if f.get("event") in weeks)
    return {"season":season_id(snapshot,now),"through":weeks[-1],"weeks":weeks,
            "fixtures_digest":sha256(json.dumps(fixtures).encode()).hexdigest()}


def digest(extra):
    return sha256(json.dumps({k:extra[k] for k in ("rows","weeks","through","sources","method")},
                             sort_keys=True,separators=(",",":")).encode()).hexdigest()


def build(snapshot,now,evidence,proof=None):
    from .evening_intelligence import _attacking_zones
    from .autonomous_content import Plan
    weeks=target(snapshot)
    slot=Slot("task2",EDITION,0,series_gw=weeks[-1])
    raw=_attacking_zones(slot,snapshot,now,evidence.session,through=weeks[-1],verified_weeks=weeks)
    extra=raw.extra
    if len(extra["rows"])!=20 or len({r["code"] for r in extra["rows"]})!=20:
        raise RequiredInput("Exactly twenty unique official clubs required")
    if proof is not None and digest(extra)!=proof["data_digest"]:
        raise RequiredInput("Shot archive changed since advance research; hold and recheck")
    caption="\n".join((f"GW{weeks[-1]} | ATTACKING ZONES · SHOT ORIGINS",
        f"All 20 clubs · last {len(weeks)} completed rounds through GW{weeks[-1]}.",
        "Left / centre / right share of recorded shots; ranked by central share.",
        "FPL Core shot locations, reconciled to official final fixtures. Not all attacks.",
        f"#FPL #GW{weeks[-1]} #FPLTips #FPLVORTEX"))
    return Plan(slot.task,EDITION,"ATTACKING ZONES · SHOT ORIGINS",caption,weeks[-1],[],[],
                "post_gameweek_zones",{**extra,"research":proof or {}})


def proof_valid(proof,expected,now,*,posting=True):
    try:
        if any(proof.get(k)!=v for k,v in expected.items()):
            return False
        checked,source=clock(proof["checked_at"]),clock(proof["source_at"])
        research,post=clock(proof["research_at"]),clock(proof["post_at"])
        return (heartbeat(research) and heartbeat(post) and research<=checked<research+WINDOW
                and source<=checked and checked-source<=timedelta(minutes=30)
                and post-(research+WINDOW)>=MIN_GAP and post-research<=MAX_HORIZON+MIN_GAP+WINDOW
                and verified_gap(proof["checked_at"],post)
                and isinstance(proof["data_digest"],str) and len(proof["data_digest"])==64
                and (not posting or (post<=now<post+WINDOW and allowed(now)
                                     and verified_gap(proof["checked_at"],now))))
    except (KeyError,ValueError,TypeError,AttributeError):
        return False


def prepare(snapshot,now,state,evidence,clock_now):
    if not RELEASE_VERIFIED:
        return False
    try:
        expected=scope(snapshot,now)
        if state.get(key(expected["season"],expected["through"]),{}).get("identity"):
            return False
        previous=state.get(STATE_KEY,{})
        if proof_valid(previous,expected,now,posting=False) and now<clock(previous["post_at"])+WINDOW:
            return False
        research=now.astimezone(timezone.utc).replace(second=0,microsecond=0)
        # Only actual scheduled heartbeat windows; no invented research timestamp.
        for offset in range(10):
            candidate=research-timedelta(minutes=offset)
            if heartbeat(candidate):
                research=candidate
                break
        if not heartbeat(research) or not research<=now<research+WINDOW:
            return False
        busy=busy_windows(snapshot,now,state,research)
        if not free(research,busy):
            return False
        post=choose_post(research,busy)
        if post is None:
            return False
        plan=build(snapshot,now,evidence)
        proof={**expected,"research_at":research.isoformat(),"post_at":post.isoformat(),
               "checked_at":clock_now().isoformat(),"source_at":snapshot.fetched_at.isoformat(),
               "data_digest":digest(plan.extra)}
        if not proof_valid(proof,expected,now,posting=False):
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
        if not proof_valid(proof,expected,now):
            return None
        if state.get(key(expected["season"],expected["through"]),{}).get("status") in ("delivered","already-delivered"):
            return None
        post=clock(proof["post_at"])
        if not free(post,busy_windows(snapshot,now,state,post)):
            return None
        from .autonomous_schedule import ET
        local=post.astimezone(ET)
        return Slot("task2",EDITION,local.hour,local.minute,series_gw=expected["through"])
    except (RuntimeError,ValueError,KeyError,TypeError,AttributeError):
        return None


def validate_record(record,now,publish_at,*,manual=False):
    facts=record.get("facts") or {}
    extra=facts.get("extra") or {}
    proof=extra.get("research") or {}
    if (not RELEASE_VERIFIED or manual or record.get("task")!="task2"
            or len(record.get("images") or [])!=1 or proof.get("season")!=record.get("season")
            or proof.get("through")!=record.get("gameweek")):
        raise ValueError("Shot origins release gate closed")
    from .autonomous_runner import STATE_FILE
    from .bot import read_state
    from .fpl import collect_snapshot
    state=read_state(STATE_FILE)
    if state.get(STATE_KEY)!=proof or digest(extra)!=proof.get("data_digest"):
        raise ValueError("Shot origins research evidence mismatch")
    snapshot=collect_snapshot()
    fresh=max(now,snapshot.fetched_at)
    if not proof_valid(proof,scope(snapshot,fresh),publish_at) or eligible(snapshot,fresh,state) is None:
        raise ValueError("Shot origins settlement or publication window changed")
    return "chatgpt:"+key(record["season"],record["gameweek"])


def audit():
    """Read-only live source and renderer validation. No send or state writes."""
    from .autonomous_content import Evidence,retrying_session
    from .fpl import collect_snapshot
    from .shot_origins_render import render
    from PIL import Image
    session=retrying_session()
    snapshot=collect_snapshot(session)
    now=datetime.now(timezone.utc)
    plan=build(snapshot,now,Evidence(snapshot,now,session))
    output=Path("output/shot-origins-audit/shot-origins.png")
    render(plan,output,session)
    with Image.open(output) as image:
        if image.size!=(1920,1080):
            raise ValueError("Shot origins landscape contract failed")
        image.verify()
    print(json.dumps({"at":now.isoformat(),"through":plan.gw,"weeks":plan.extra["weeks"],
                      "clubs":len(plan.extra["rows"]),"release_verified":RELEASE_VERIFIED,
                      "mode":"read-only"}))


if __name__=="__main__":
    audit()
