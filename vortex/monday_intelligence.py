"""One Monday board: verified elite picks, defensive thresholds, and shot origins."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
from PIL import Image, ImageDraw
from .autonomous_schedule import ET, MONDAY_DEFENCE, season_id
from .editorial_inputs import RequiredInput
from .fpl import latest_completed_gw, upcoming_deadline

RESEARCH = Path(__file__).resolve().parents[1] / "state" / "monday_intelligence_research.json"

def research_due(now):
    t=now.astimezone(ET)
    return t.weekday()==0 and (19,0)<=(t.hour,t.minute)<(20,0)

def publication_due(now):
    t=now.astimezone(ET)
    return t.weekday()==0 and (20,0)<=(t.hour,t.minute)<(23,0)

def _scope(snapshot, now):
    through=latest_completed_gw(snapshot)
    if through is None:
        raise RequiredInput("No verified completed gameweek for Monday intelligence")
    identity={"fixtures":[f for f in snapshot.fixtures if f.get("finished") and (f.get("event") or 0)<=through],
              "players":[(p["id"],p.get("code"),p.get("team"),p.get("element_type"),p.get("web_name")) for p in snapshot.players],
              "clubs":snapshot.teams}
    return {"date":now.astimezone(ET).date().isoformat(),"season":season_id(snapshot,now),
            "gw":snapshot.gameweek(),"through":through,
            "identity":sha256(json.dumps(identity,sort_keys=True,default=str).encode()).hexdigest()}

def _historical(snapshot,now,evidence):
    from .sunday_chances import build_monday_defence
    from .evening_intelligence import _attacking_zones
    defence=build_monday_defence(MONDAY_DEFENCE,snapshot,now,evidence.session)
    zones=_attacking_zones(MONDAY_DEFENCE,snapshot,now,evidence.session)
    if defence.extra["through"]!=zones.extra["through"]:
        raise RequiredInput("Monday historical cutoffs differ")
    return defence.extra,zones.extra

def _cache(snapshot,now):
    from .bot import read_state
    row=read_state(RESEARCH)
    try:
        stamp=datetime.fromisoformat(row["at"])
        if row["scope"]==_scope(snapshot,now) and timedelta(0)<=now-stamp<=timedelta(hours=2):
            return row["defence"],row["zones"]
    except (KeyError, ValueError, TypeError):
        pass
    return None

def prepare_research(snapshot,now):
    if not research_due(now) or _cache(snapshot,now) is not None:
        return False
    from .bot import write_state
    from .autonomous_content import Evidence
    from .gw_key_players import build_key_players
    e=Evidence(snapshot,now)
    defence,zones=_historical(snapshot,now,e)
    picks=build_key_players(MONDAY_DEFENCE,snapshot,now,e)
    write_state(RESEARCH,{"at":now.isoformat(),"scope":_scope(snapshot,now),
                          "defence":defence,"zones":zones,"preliminary_picks":[p["id"] for p in picks.players]})
    print("Monday defence, shot origins and elite picks researched; no publication")
    return True

def build_combined(slot,snapshot,now,evidence):
    from .autonomous_content import Plan
    from .gw_key_players import build_key_players
    deadline=upcoming_deadline(snapshot)
    if deadline is None or deadline<=now:
        raise RequiredInput("No future official FPL deadline")
    defence,zones=_cache(snapshot,now) or _historical(snapshot,now,evidence)
    picks=build_key_players(slot,snapshot,now,evidence)
    if picks.gw!=snapshot.gameweek() or len(picks.players)!=5 or len(zones["rows"])!=20:
        raise RequiredInput("Incomplete Monday intelligence inputs")
    names=[snapshot.name(p) for p in picks.players]
    title=f"GW{picks.gw} | MONDAY FPL INTELLIGENCE"
    caption="\n".join((title, f"Premium: {names[0]}, {names[1]} · Value: {names[2]}, {names[3]} · Defence: {names[4]}.",
        f"Defence watch: per-90 rates through GW{defence['through']}, minimum 450 minutes.",
        f"Shot origins: all 20 clubs, last {len(zones['weeks'])} completed rounds through GW{zones['through']}. Check team news.",
        f"#FPL #GW{picks.gw} #FPLTips #FPLVORTEX"))
    return Plan(slot.task,slot.edition,title,caption,picks.gw,picks.players,picks.labels,"monday_intelligence",
                {"combined_monday":True,"picks":picks.extra,"defence":defence,"zones":zones,
                 "sources":list(dict.fromkeys(defence["sources"]+zones["sources"]))})

def render_combined(plan,snapshot,output,client):
    from .content import Content
    from .premium import _background, _header
    from .brand_footer import MASTER, approved_sell_logo, approved_social_footer, verify_exact_master
    from .minimal_theme import background, edition_key
    from .comparison_board import contain, text
    from .autonomous_render import _assets
    from .sunday_chances import GROUP_ORDER
    from .sunday_chances_render import _media_for
    if len(plan.players)!=5 or plan.gw!=snapshot.gameweek():
        raise RequiredInput("Five unique upcoming picks required")
    verify_exact_master()
    article=Content("sell",plan.title,"VORTEX RECOMMENDATIONS · WEEKLY EDITION",(),
                    "",plan.caption,snapshot.fetched_at.isoformat(),plan.gw,"")
    # Exact SELL masthead and assets; taller native body instead of shrinking three images.
    header=_background(article)
    _header(header,article)
    approved_sell_logo(header)
    with Image.open(MASTER) as master:
        canvas=background(master,edition_key(article),(1080,1920))
    canvas.paste(header.crop((0,0,1536,145)).resize((1080,102),Image.Resampling.LANCZOS),(0,0))
    d=ImageDraw.Draw(canvas,"RGBA")
    NAVY="#0b1533"; PANEL="#142644"; WHITE="#f2f7ff"; MUTED="#bcd3e9"; GOLD="#ffce60"; CYAN="#65eaff"; GREEN="#76f1b0"
    def label(value,x,y,w,size=20,color=WHITE,center=False,minimum=15):
        text(d,value,x,y,w,size,color,min(size,minimum),center=center)
    def panel(box,color=CYAN):
        d.rounded_rectangle(box,radius=14,fill=NAVY,outline=color,width=2)
    def section(y,title,sub,color):
        label(title,30,y,1020,29,color)
        label(sub,30,y+34,1020,19,MUTED)
    picks=plan.extra["picks"]["details"]; defence=plan.extra["defence"]; zones=plan.extra["zones"]
    section(114,"FIVE ELITE FPL PICKS", "Official next-GW forecast · estimates, not guaranteed points",GOLD)
    cache={}
    for i,p in enumerate(plan.players):
        y=174+i*85
        color=GOLD if i<2 else CYAN if i<4 else GREEN
        panel((24,y,1056,y+79),color)
        photo,crest=_assets(snapshot,p,client,cache)
        contain(canvas,photo,(30,y+3,76,73),bottom=True,crop_alpha=True)
        contain(canvas,crest,(108,y+10,40,40))
        d=ImageDraw.Draw(canvas,"RGBA")
        m=picks[str(p["id"])]
        label(snapshot.name(p).upper(),160,y+7,355,25)
        label(f"{plan.labels[i]} · {snapshot.team(p)} · {snapshot.price(p)}",160,y+39,355,17,color)
        label(f"FORM {m['form']:.1f}" if m.get("form") is not None else "FORM NOT RECORDED",528,y+9,190,18)
        fixture=" / ".join(f"{opp} ({venue}) · FDR {fdr}" for opp,venue,fdr,_ in m["fixtures"])
        label(fixture,528,y+39,358,17,MUTED)
        label("FPL FORECAST",897,y+8,145,15,GOLD,True)
        label(f"{m['forecast']:.1f}",897,y+30,145,32,WHITE,True)
    section(610,"MONDAY DEFENCE WATCH",f"Through GW{defence['through']} · 450+ minutes · all metrics per 90",CYAN)
    featured=[r for rows in defence["rows"].values() for r in rows[:2]]
    media=_media_for(client,featured)
    for idx,(position,rows) in enumerate(defence["rows"].items()):
        x=24+idx*522; color=CYAN if idx==0 else "#c8a1ff"
        panel((x,670,x+510,1234),color)
        label(position,x+12,680,486,23,color)
        metrics=defence["metrics"][position]
        for n,row in enumerate(rows[:2]):
            yy=715+n*72
            d.rounded_rectangle((x+10,yy,x+500,yy+66),radius=8,fill=PANEL)
            photo,crest=media[row["player_id"]]
            contain(canvas,photo,(x+14,yy+3,65,60),bottom=True,crop_alpha=True)
            contain(canvas,crest,(x+82,yy+8,30,30))
            d=ImageDraw.Draw(canvas,"RGBA")
            label(row["name"],x+119,yy+4,367,22)
            label("  ·  ".join(f"{m[1]} {v:.2f}" for m,v in zip(metrics,row["rates"])),x+119,yy+36,367,15,MUTED,minimum=12)
        label("THRESHOLDS",x+13,864,480,15,color)
        for j,(_,name,threshold) in enumerate(metrics):
            label(f"{name} ≥{threshold:g}",x+12+j*162,884,158,15,MUTED,True,minimum=12)
        for n,mask in enumerate(GROUP_ORDER):
            yy=912+n*38
            group=[r for r in rows if r["mask"]==mask]
            d.rounded_rectangle((x+10,yy,x+500,yy+34),radius=5,fill=PANEL if n%2==0 else "#101d3d")
            for k,c in enumerate(("#d5a0ff","#ffcb67","#59f3d4")):
                xx=x+28+k*35
                d.ellipse((xx,yy+10,xx+14,yy+24),fill=c if mask&(1<<k) else "#26385e",outline=c,width=1)
            label(str(len(group)),x+134,yy+6,40,18,color,True)
            names=" · ".join(r["name"] for r in group[:2]) or "None"
            if len(group)>2:
                names+=f" +{len(group)-2}"
            label(names,x+182,yy+7,309,17,WHITE,minimum=13)
        label(f"{len(rows)} qualify · {defence['incomplete'][position]} incomplete excluded",x+12,1191,486,17,MUTED)
    section(1246,"ATTACKING ZONES · SHOT ORIGINS",f"All 20 clubs · last {len(zones['weeks'])} completed rounds through GW{zones['through']} · lateral thirds",GOLD)
    zone_colors=("#58ceef","#ffce60","#c3a0ff")
    for i,(word,color) in enumerate(zip(("LEFT","CENTRE","RIGHT"),zone_colors)):
        label(word,30+i*340,1311,320,19,color,True)
    clubs={v["code"]:v["short_name"] for v in snapshot.teams.values()}
    for i,row in enumerate(zones["rows"]):
        x=24+(i//10)*522; y=1341+(i%10)*46
        panel((x,y,x+510,y+42),"#3e5779")
        label(clubs[row["code"]],x+10,y+8,64,19,WHITE)
        vals=[row[k] for k in ("left","centre","right")]
        xx=x+80; width=238; used=0
        for j,(v,c) in enumerate(zip(vals,zone_colors)):
            n=round(width*v/100) if j<2 else width-used
            if n>0:d.rectangle((xx+used,y+7,xx+used+n-1,y+34),fill=c)
            used+=n
        for j,(v,c) in enumerate(zip(vals,zone_colors)):
            label(f"{v:.0f}%",x+324+j*59,y+10,56,17,c,True)
    label("Shot locations, not share of all attacks · percentages rounded",30,1809,1020,17,MUTED,True)
    label("CHECK MINUTES & TEAM NEWS BEFORE TRANSFERRING",30,1837,1020,21,WHITE,True)
    approved_social_footer(canvas)
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"PNG",optimize=True)
    return output
