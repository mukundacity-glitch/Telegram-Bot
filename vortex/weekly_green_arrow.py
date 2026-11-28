"""Gated weekly green-arrow research boards (26–29).

Official FPL match history supplies scored defensive/save returns and minutes;
FPL Core supplies observed chance and shot counts; rank-cohort ownership is
separate from EO. No publisher, cron, or fabricated fallback is registered.
"""
from concurrent.futures import ThreadPoolExecutor
from math import isfinite
from datetime import timedelta
from .autonomous_schedule import Slot
from .autonomous_content import Plan
from .editorial_inputs import RequiredInput
from .post_gameweek_zones import settled_rounds
from .recommendations import get_history
from .weekly_analysis import player_totals
from .saturday_boards import build_ownership
from .weekly_chip_strategy import scope, choose_schedule, proof_valid

RELEASE_VERIFIED = False
EDITIONS = {
    26: ("weekly-defensive-save-potential", "DEFENSIVE CONTRIBUTION & SAVE POTENTIAL"),
    27: ("weekly-chance-creation", "CHANCE CREATION & ASSIST POTENTIAL"),
    28: ("weekly-goal-threat", "GOAL THREAT & SHOT QUALITY RADAR"),
    29: ("weekly-rank-exposure", "RANK-TIER OWNERSHIP & EXPOSURE"),
}
MIN_MINUTES = 220
MIN_RECENT = 64
HISTORY_GWS = 6
LIMIT = 10
POSITION = {1:"GK",2:"DEF",3:"MID",4:"FWD"}
# Scoring rules for the current official DC scoring regime, not player data.
DC_THRESHOLD = {2:10,3:12,4:12}
OFFICIAL = "https://fantasy.premierleague.com/api/"


def numeric(value):
    if value is None or isinstance(value,bool) or str(value).strip()=="":
        raise ValueError("Missing numeric observation")
    result=float(value)
    if not isfinite(result) or result<0:
        raise ValueError("Invalid numeric observation")
    return result


def secure_history(history, fixtures, club, rounds):
    """Require actual fixture coverage and the latest three club matches >=64m.
    Missing, duplicate, transferred-team, blank or cameo evidence never qualifies.
    """
    wanted={f["id"]:f for f in fixtures if f.get("event") in rounds
            and f.get("finished") is True and club in (f.get("team_h"),f.get("team_a"))}
    if len(wanted)<3:
        return []
    matched={}
    for row in history:
        fid=row.get("fixture")
        if fid not in wanted:
            continue
        f=wanted[fid]
        if (fid in matched or row.get("round")!=f["event"]
                or type(row.get("minutes")) is not int or row["minutes"]<0):
            return []
        matched[fid]=row
    if set(matched)!=set(wanted):
        return []
    ordered=sorted(wanted,key=lambda fid:(wanted[fid]["kickoff_time"],fid))
    if any(matched[fid]["minutes"]<MIN_RECENT for fid in ordered[-3:]):
        return []
    return [matched[fid] for fid in ordered]


def base_row(snapshot,p,history):
    fixtures=snapshot.fixtures_for_gameweek(p)
    if not fixtures or any(fdr not in range(1,6) or opp=="TBD" for opp,_,fdr,_ in fixtures):
        raise ValueError("Unverified upcoming fixture")
    own=numeric(p["selected_by_percent"])
    if own>100 or type(p["now_cost"]) is not int or p["now_cost"]<=0:
        raise ValueError("Invalid player ownership/price")
    return {"id":p["id"],"name":snapshot.name(p),"photo":snapshot.photo_code(p),
            "code":snapshot.team_code(p),"pos":POSITION[p["element_type"]],
            "price":snapshot.price(p),"own":own,"recent_minutes":[r["minutes"] for r in history[-3:]],
            "fixture":" / ".join(f"{opp}({venue}) {fdr}" for opp,venue,fdr,_ in fixtures)}


def defensive_metrics(position,history):
    """Historical realized points, not a calibrated future probability."""
    if not history:
        raise ValueError("No completed match history")
    minutes=sum(numeric(r["minutes"]) for r in history)
    if not minutes:
        raise ValueError("No played minutes")
    if position==1:
        actions=[numeric(r["saves"]) for r in history]
        if any(not a.is_integer() for a in actions):
            raise ValueError("Invalid save count")
        points=[int(a)//3 for a in actions]
        hits=sum(a>=3 for a in actions)
    else:
        threshold=DC_THRESHOLD[position]
        actions=[numeric(r["defensive_contribution"]) for r in history]
        if any(not a.is_integer() for a in actions):
            raise ValueError("Invalid DC count")
        points=[2 if a>=threshold else 0 for a in actions]
        hits=sum(a>=threshold for a in actions)
    return {"actions90":90*sum(actions)/minutes,"hit_pct":100*hits/len(history),
            "points_per_match":sum(points)/len(history),"matches":len(history)}


def core_metrics(number, values):
    minutes=numeric(values["minutes"])
    if minutes<MIN_MINUTES or values.get("incomplete_metrics") or values.get("incomplete_shot_xg"):
        raise ValueError("Incomplete FPL Core observations")
    if number==27:
        chances=numeric(values["chances_created"])
        xa=numeric(values["xa"])
        assists=numeric(values["assists"])
        return {"chances90":90*chances/minutes,"xa90":90*xa/minutes,
                "assists":assists,"xa":xa,"assist_delta":assists-xa}
    shots=numeric(values["total_shots"])
    if shots==0:
        raise ValueError("No recorded shots")
    xg=numeric(values["xg"])
    goals=numeric(values["goals"])
    box=numeric(values["touches_opposition_box"])
    return {"xg90":90*xg/minutes,"xg_per_shot":xg/shots,"shots90":90*shots/minutes,
            "box90":90*box/minutes,"goals":goals,"xg":xg,"goal_delta":goals-xg}


def build(number,snapshot,now,session):
    edition,title=EDITIONS[number]
    expected=scope(snapshot,now)
    gw=expected["gw"]
    rounds=settled_rounds(snapshot)
    if not rounds or rounds!=list(range(1,gw)):
        raise RequiredInput("Complete finalized history before the target GW required")
    sources=[OFFICIAL+"bootstrap-static/",OFFICIAL+"fixtures/"]
    if number==29:
        legacy=build_ownership(Slot("task2",edition,0,0),snapshot,now,session)
        rows=[]
        for p,observed in zip(legacy.players,legacy.extra["rows"],strict=True):
            global_own=numeric(p["selected_by_percent"])
            cohort=numeric(observed["ownership"])
            if global_own>100 or cohort>100:
                raise RequiredInput("Invalid ownership")
            rows.append({"id":p["id"],"name":snapshot.name(p),"code":snapshot.team_code(p),
                         "photo":snapshot.photo_code(p),"pos":POSITION[p["element_type"]],
                         "price":snapshot.price(p),"own":global_own,"cohort":cohort,
                         "difference":cohort-global_own,
                         "fixture":" / ".join(f"{f['opponent']}({f['venue']})" for f in observed["fixtures"]
                                              if f["gw"]==gw and not f["blank"]) or "BLANK"})
        columns=[("TOP 100K %","cohort"),("LIVE OWN %","own"),("GAP pp","difference")]
        note=f"Locked GW{legacy.gw} sample: {legacy.extra['sample']:,} squads vs current overall ownership. NOT EO."
        groups=[("TOP 100K OWNERSHIP",rows)]
        sources.extend(legacy.extra["sources"])
        coverage={"sample":legacy.extra["sample"],"locked_gw":legacy.gw}
    else:
        selected_rounds=rounds[-HISTORY_GWS:]
        pool=[p for p in snapshot.players if p.get("status")=="a"
              and p.get("chance_of_playing_next_round") in (None,100)
              and p.get("element_type") in (POSITION if number==26 else (2,3,4))
              and type(p.get("id")) is int and type(p.get("minutes")) is int
              and p["minutes"]>=MIN_MINUTES and snapshot.fixtures_for_gameweek(p)]
        values={}
        if number in (27,28):
            fields=("chances_created","xa","assists") if number==27 else ("total_shots","xg","goals","touches_opposition_box")
            # Core uses blank cells for some unavailable measures. Do not impute
            # them as zero for a ranked metric. FPL Core xG includes penalties.
            stats,urls=player_totals(snapshot,rounds[-1],session,int(expected["season"].split("-")[0]),
                fields,required_nonblank_by_position={pos:fields for pos in (2,3,4)},
                require_shot_xg=number==28)
            values={p["id"]:v for p,v in stats}
            sources.extend(urls)
            pool=[p for p in pool if p["id"] in values]
        rows=[]
        with ThreadPoolExecutor(max_workers=6) as workers:
            histories=workers.map(lambda p:get_history(p["id"],session),pool)
            for p,history in zip(pool,histories):
                try:
                    recent=secure_history(history,snapshot.fixtures,p["team"],selected_rounds)
                    if not recent:
                        continue
                    row=base_row(snapshot,p,recent)
                    metrics=defensive_metrics(p["element_type"],recent) if number==26 else core_metrics(number,values[p["id"]])
                    rows.append({**row,**metrics})
                    sources.append(OFFICIAL+f"element-summary/{p['id']}/")
                except (ValueError,KeyError,TypeError):
                    continue
        coverage={"candidates":len(pool),"qualified":len(rows),"completed_gws":selected_rounds}
        if number==26:
            columns=[("ACT / 90","actions90"),("HIT %","hit_pct"),("PTS / MATCH","points_per_match")]
            ranked=lambda r:(-r["points_per_match"],-r["hit_pct"],-r["actions90"],r["id"])
            groups=[("GOALKEEPER SAVE POINTS",sorted((r for r in rows if r["pos"]=="GK"),key=ranked)[:5]),
                    ("OUTFIELD DEFENSIVE CONTRIBUTION",sorted((r for r in rows if r["pos"]!="GK"),key=ranked)[:5])]
            note="Observed last six finalized GWs; hit rate is historical, not a forecast. GK 3 saves/pt; DEF 10, MID/FWD 12 actions for 2 pts."
        elif number==27:
            columns=[("CHANCES / 90","chances90"),("xA / 90","xa90"),("A − xA","assist_delta")]
            groups=[("CREATIVE RETURN WATCH",sorted(rows,key=lambda r:(-r["xa90"],-r["chances90"],r["id"]))[:LIMIT])]
            note="FPL Core total chance creation and xA through finalized GW. Open-play/set-piece split unavailable in this source."
        else:
            columns=[("xG / 90","xg90"),("xG / SHOT","xg_per_shot"),("BOX / 90","box90"),("G − xG","goal_delta")]
            groups=[("SUSTAINABLE GOAL THREAT WATCH",sorted(rows,key=lambda r:(-r["xg90"],-r["xg_per_shot"],r["id"]))[:LIMIT])]
            note="FPL Core season xG includes penalties; not npxG. Goal minus xG is descriptive, not a guaranteed regression."
    if any(not entries for _,entries in groups):
        raise RequiredInput("No verified qualifying rows for a required panel")
    if any(not r["code"] or not r["photo"] for _,entries in groups for r in entries):
        raise RequiredInput("Authentic player/club identity unavailable")
    caption="\n".join((f"GW{gw} | {title}",note,
                       "Check live minutes, availability and fixtures before transfers.",
                       f"#FPL #GW{gw} #FPLVORTEX #FPLTips"))
    extra={"scope":expected,"retrieved_at":snapshot.fetched_at.isoformat(),
           "through":rounds[-1],"groups":groups,"columns":columns,"note":note,
           "sources":sorted(set(sources)),"coverage":coverage}
    return Plan("task2",edition,title,caption,gw,[],[],edition,extra)


def eligible(number,proof,expected,extra,now,busy,claims,*,inventory_verified=False,legacy_reconciled=False):
    identity=f"{expected['season']}:GW{expected['gw']}:task2:{EDITIONS[number][0]}"
    return (RELEASE_VERIFIED and legacy_reconciled and not claims.get(identity)
            and proof_valid(proof,expected,extra,now,busy,inventory_verified=inventory_verified))
