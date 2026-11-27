"""Slot 30: gated, one-transfer horizon evaluator.

Inputs must come from a trusted squad/rules adapter and fresh reviewed
per-fixture forecasts. No authenticated squad adapter is registered yet.
Not a full dynamic multi-transfer or future free-transfer option-value model.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from os import getenv
from .autonomous_content import Plan
from .chip_strategy import lineups
from .editorial_inputs import RequiredInput
from .position_watch import clock
from .post_gameweek_zones import settled_rounds
from .publication_rules import fetch_verified_xpts, five_gw_fixtures
from .recommendations import get_history
from .weekly_chip_strategy import scope, choose_schedule, proof_valid
from .weekly_green_arrow import secure_history
from .wildcard import QUOTAS

EDITION="weekly-transfer-hit-value"
RELEASE_VERIFIED=False


def legal(players):
    return (len(players)==15 and len({p["id"] for p in players})==15
            and Counter(p["element_type"] for p in players)==QUOTAS
            and max(Counter(p["team"] for p in players).values(),default=0)<=3)


def forecast(snapshot,p,verified,weeks,model):
    rows=five_gw_fixtures(snapshot,p,verified)
    values=[]
    for gw in weeks:
        fixtures=[r for r in rows if r["gw"]==gw and not r["blank"]]
        if not any(r["gw"]==gw for r in rows):
            raise RequiredInput("Unverified forecast week")
        if any(r["xpts"] is None or verified[(p["id"],r["fixture_id"])]["model"]!=model for r in fixtures):
            raise RequiredInput("Incomplete or mixed model coverage")
        values.append(sum(r["xpts"] for r in fixtures))
    return values


def compare(players,values,squad,selling,bank,free_transfers,hit_cost,candidates):
    """Enumerate all legal single moves; reselect legal XI and captain each GW."""
    if not legal([players[i] for i in squad]):
        raise RequiredInput("Illegal starting roster")
    if (type(bank) is not int or bank<0 or type(free_transfers) is not int or free_transfers<0
            or type(hit_cost) is not int or hit_cost<=0
            or any(type(selling.get(players[i]["id"])) is not int
                   or not 0<selling[players[i]["id"]]<=players[i]["now_cost"] for i in squad)):
        raise RequiredInput("Verified selling prices, bank, transfer balance and rules required")
    columns=list(zip(*values,strict=True))
    if not 1<=len(columns)<=5:
        raise RequiredInput("Invalid projection horizon")
    baseline=[lineups(players,p,squad)[0] for p in columns]
    cost=0 if free_transfers else hit_cost
    result=[]
    roster=set(squad)
    for out in squad:
        for incoming in candidates:
            if incoming in roster or players[incoming]["element_type"]!=players[out]["element_type"]:
                continue
            cash=bank+selling[players[out]["id"]]-players[incoming]["now_cost"]
            changed=sorted((roster-{out})|{incoming})
            if cash<0 or not legal([players[i] for i in changed]):
                continue
            gains=[lineups(players,p,changed)[0]-b for p,b in zip(columns,baseline)]
            cumulative=0
            breakeven=None
            for i,gain in enumerate(gains,1):
                cumulative+=gain
                if breakeven is None and cumulative>=cost:
                    breakeven=i
            result.append({"out":players[out]["id"],"in":players[incoming]["id"],
                           "gw1":gains[0],"gross":sum(gains),"hit":cost,
                           "net":sum(gains)-cost,"break_even":breakeven,"bank_after":cash})
    return sorted(result,key=lambda r:(-r["net"],-r["gw1"],r["in"],r["out"]))


def build(snapshot,now,session,context=None):
    expected=scope(snapshot,now)
    # A verified adapter must supply this contract; no manager IDs or fabricated
    # personal/reference rosters are embedded. Never put credentials in a Plan.
    if not isinstance(context,dict) or context.get("scope")!=expected or context.get("active_chip") is not None:
        raise RequiredInput("Trusted current squad context unavailable or chip active")
    try:
        if not timedelta(0)<=now-clock(context["observed_at"])<=timedelta(minutes=30):
            raise RequiredInput("Stale squad context")
        if not context["source"] or not context["rules_source"] or context.get("pending_transfers")!=0:
            raise RequiredInput("Unverified squad/rules provenance or pending transfers")
        ids=context["player_ids"]
        if len(ids)!=15 or len(set(ids))!=15 or any(type(i) is not int for i in ids):
            raise RequiredInput("Verified 15-player squad required")
        selling={int(k):v for k,v in context["selling_prices"].items()}
    except (KeyError,ValueError,TypeError,AttributeError) as exc:
        raise RequiredInput("Incomplete trusted squad context") from exc
    verified=fetch_verified_xpts(now,snapshot,session)
    if not verified:
        raise RequiredInput("Verified fixture-level xPts unavailable; no hit recommendation")
    models={r["model"] for r in verified.values()}
    if len(models)!=1:
        raise RequiredInput("Single coherent forecast model required")
    model=models.pop()
    weeks=list(range(expected["gw"],min(expected["gw"]+5,max(e["id"] for e in snapshot.events)+1)))
    by_id={p["id"]:p for p in snapshot.players}
    if any(i not in by_id for i in ids):
        raise RequiredInput("Squad player identity missing")
    players=[by_id[i] for i in ids]
    values=[forecast(snapshot,p,verified,weeks,model) for p in players]
    rounds=settled_rounds(snapshot)[-6:]
    pool=[]
    for p in snapshot.players:
        if (p["id"] in ids or p.get("status")!="a"
                or p.get("chance_of_playing_next_round") not in (None,100)
                or p.get("element_type") not in QUOTAS
                or type(p.get("now_cost")) is not int or p["now_cost"]<=0
                or not snapshot.fixtures_for_gameweek(p)):
            continue
        try:
            points=forecast(snapshot,p,verified,weeks,model)
        except (RequiredInput,ValueError,KeyError):
            continue
        pool.append((p,points))
    with ThreadPoolExecutor(max_workers=6) as workers:
        histories=workers.map(lambda item:get_history(item[0]["id"],session),pool)
        for (p,points),history in zip(pool,histories):
            if secure_history(history,snapshot.fixtures,p["team"],rounds):
                players.append(p)
                values.append(points)
    if len(players)==15:
        raise RequiredInput("No verified, secure-minute transfer candidates")
    result=compare(players,values,list(range(15)),selling,context["bank"],
                   context["free_transfers"],context["hit_cost"],range(15,len(players)))
    if not result:
        raise RequiredInput("No verified legal transfer comparisons")
    def display(pid):
        p=by_id[pid]
        return {"name":snapshot.name(p),"photo":snapshot.photo_code(p),
                "code":snapshot.team_code(p),"price":snapshot.price(p)}
    rows=[{**r,"out_player":display(r["out"]),"in_player":display(r["in"])} for r in result[:6]]
    note="Static-squad single-move comparison vs no move; normal captaincy. Future free-transfer option value and auto-subs not modelled."
    title="TRANSFER HIT & FREE-TRANSFER VALUE"
    caption="\n".join((f"GW{expected['gw']} | {title}",note,
                       "Conditional on verified reference squad and model; no personal identifiers.",
                       f"#FPL #GW{expected['gw']} #FPLVORTEX #FPLTransfers"))
    extra={"scope":expected,"retrieved_at":snapshot.fetched_at.isoformat(),"weeks":weeks,
           "rows":rows,"model":model,"free_transfers":context["free_transfers"],
           "note":note,"source":getenv("FPL_XPTS_SNAPSHOT_URL",""),
           "positive":rows[0]["net"]>0}
    return Plan("task2",EDITION,title,caption,expected["gw"],[],[],EDITION,extra)
