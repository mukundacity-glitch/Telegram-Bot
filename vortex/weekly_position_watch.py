"""Monday-only official research cache and one-page goalkeeper/striker board."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image, ImageDraw
from .autonomous_schedule import ET, SLOTS
from .brand_footer import approved_sell_logo, approved_social_footer, verify_exact_master

RESEARCH = Path(__file__).resolve().parents[1] / "state" / "weekly_position_research.json"

def research_due(now):
    local = now.astimezone(ET)
    return local.weekday() == 0 and (3,13) <= (local.hour,local.minute) < (3,28)

def publication_due(now):
    local = now.astimezone(ET)
    return local.weekday() == 0 and (10,30) <= (local.hour,local.minute) < (23,0)

def _matching(row, snapshot, now, completed):
    try:
        stamp = datetime.fromisoformat(row["at"])
        return (stamp.tzinfo is not None and timedelta(0) <= now.astimezone(timezone.utc)-stamp.astimezone(timezone.utc) <= timedelta(hours=24)
                and stamp.astimezone(ET).date() == now.astimezone(ET).date()
                and row["gw"] == snapshot.gameweek()
                and row["completed"] == sorted(completed)
                and isinstance(row["history"], dict))
    except (KeyError, ValueError, TypeError):
        return False

def prepare_research(snapshot, now, *, clock=None):
    """Read-only FPL research, independent of the publishing cooldown."""
    if not research_due(now):
        return False
    from .bot import read_state, write_state
    from .autonomous_content import Evidence, build
    evidence = Evidence(snapshot, now)
    if _matching(read_state(RESEARCH), snapshot, now, evidence.completed):
        return False
    slot = next(s for s in SLOTS if s.edition == "goalkeeper-striker-watch")
    plan = build(slot, snapshot, now, evidence)
    write_state(RESEARCH, {"at": (clock() if clock else now).isoformat(), "gw": plan.gw,
                           "completed": sorted(evidence.completed),
                           "history": {str(pid): rows for pid, rows in evidence.history.items() if rows},
                           "selected": [p["id"] for p in plan.players]})
    print("Combined watch: Monday official research recorded; no publication")
    return True

def restore_research(snapshot, now, evidence):
    """Re-rank against the fresh posting snapshot; reuse only matching history."""
    from .bot import read_state
    if not publication_due(now):
        return False
    row = read_state(RESEARCH)
    if not _matching(row, snapshot, now, evidence.completed):
        return False
    for pid, rows in row["history"].items():
        if pid.isdecimal() and isinstance(rows, list) and rows:
            evidence.history.setdefault(int(pid), rows)
    return True

def render_combined(plan, snapshot, output, client):
    from .content import Content
    from .premium import _background, _header, _safe_line
    from .autonomous_render import _assets
    from .comparison_board import text, contain
    from .publication_rules import five_gw_fixtures, FDR_COLORS
    if [p.get("element_type") for p in plan.players] != [1,1,4,4,4]:
        raise ValueError("Combined watch needs exactly two goalkeepers and three strikers")
    verify_exact_master()
    article = Content("sell", plan.title, "VORTEX RECOMMENDATIONS · NEXT FIVE", (),
                      "", plan.caption, snapshot.fetched_at.isoformat(), plan.gw, "")
    canvas = _background(article)
    _header(canvas, article)
    approved_sell_logo(canvas)
    draw = ImageDraw.Draw(canvas, "RGBA")
    left, gap, width = 30, 12, 286
    for x0,x1,title,color in ((left, left+2*width+gap, "GOALKEEPERS", "#82f4ff"),
                              (left+2*(width+gap), left+5*width+4*gap, "STRIKERS", "#ffce60")):
        draw.rounded_rectangle((x0,153,x1,186), radius=8, fill="#142341", outline=color,width=2)
        text(draw,title,x0+6,156,x1-x0-12,26,color,21,center=True)
    cache = {}
    for i, player in enumerate(plan.players):
        x = left+i*(width+gap)
        accent = "#82f4ff" if i<2 else "#ffce60"
        draw.rounded_rectangle((x,198,x+width,735),radius=12,fill="#0b1533",outline=accent,width=2)
        text(draw,snapshot.name(player).upper(),x+8,210,width-16,30,"#ffffff",23,center=True)
        text(draw,f"{snapshot.team(player)} · {'GK' if i<2 else 'FWD'}",x+8,244,width-16,22,accent,17,center=True)
        portrait,crest = _assets(snapshot,player,client,cache)
        contain(canvas,portrait,(x+40,275,width-80,166),bottom=True,crop_alpha=True)
        contain(canvas,crest,(x+width-61,279,48,48))
        draw = ImageDraw.Draw(canvas,"RGBA")
        rows = plan.extra["recent"][str(player["id"])]
        minutes = " / ".join(str(r["minutes"]) for r in rows)
        pts = sum(int(r["total_points"]) for r in rows) if all(r.get("total_points") is not None for r in rows) else None
        metrics = [("PRICE",snapshot.price(player)),("OWNERSHIP",f"{player['selected_by_percent']}%"),
                   ("FORM",str(player["form"])),("LAST 3 MIN",minutes)]
        if pts is not None:
            metrics.append(("LAST 3 PTS",str(pts)))
        key,label = ("saves","LAST 3 SAVES") if i<2 else ("expected_goal_involvements","LAST 3 xGI")
        if all(r.get(key) not in (None,"") for r in rows):
            value=sum(float(r[key]) for r in rows)
            metrics.append((label,f"{value:.0f}" if i<2 else f"{value:.2f}"))
        for n,(label,value) in enumerate(metrics):
            y=453+n*31
            draw.rounded_rectangle((x+8,y,x+width-8,y+27),radius=4,fill="#172748")
            text(draw,label,x+13,y+3,129,21,"#b6d6ed",14)
            text(draw,value,x+141,y+2,width-154,23,"#ffffff",18,center=True)
        fixtures=five_gw_fixtures(snapshot,player)
        for n,gw in enumerate(sorted({r["gw"] for r in fixtures})):
            matches=[r for r in fixtures if r["gw"]==gw]
            opponents="/".join(r["opponent"] for r in matches)
            venues="/".join(r["venue"] for r in matches)
            fdr=[r["fdr"] for r in matches if r["fdr"] in FDR_COLORS]
            xx=x+8+n*(width-16)/5
            cw=(width-16)/5-3
            draw.rounded_rectangle((xx,652,xx+cw,705),radius=4,fill="#111e3b",
                                   outline=FDR_COLORS[max(fdr)] if fdr else "#718096",width=2)
            text(draw,f"GW{gw}",xx+2,655,cw-4,13,"#ffffff",11,center=True)
            text(draw,opponents,xx+2,671,cw-4,15,"#ffffff",11,center=True)
            text(draw,venues,xx+2,688,cw-4,12,"#ffffff",10,center=True)
        text(draw,"MONITOR",x+8,709,width-16,20,accent,15,center=True)
    draw.rounded_rectangle((30,747,1504,780),radius=8,fill="#112240",outline="#82f4ff",width=2)
    text(draw,"COMPARE MINUTES, FORM & FIXTURES BEFORE TRANSFERRING",42,751,1450,25,"#ffffff",21,center=True)
    approved_social_footer(canvas)
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.resize((1920,1080),Image.Resampling.LANCZOS).save(output,"PNG",optimize=True)
    return output
