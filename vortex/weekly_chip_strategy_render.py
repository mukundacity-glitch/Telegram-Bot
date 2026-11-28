"""Approved Slot 25 emerald/gold 4:3 reference; all figures come from Plan."""
from pathlib import Path
from PIL import Image, ImageDraw
from .brand_footer import approved_sell_logo, approved_social_footer
from .chip_strategy import CHIPS
from .comparison_board import text, paragraph, contain
from .editorial_inputs import RequiredInput
from .matchup import _media

SIZE = (1600,1200)
BG = "#082D25"
FOREST = "#10513D"
GOLD = "#E8BC58"
INK = "#142E26"
WHITE = "#FFFFFF"
MINT = "#E0F3E6"
MUTED = "#A9D8C2"


def render(plan, snapshot, output, session):
    from .weekly_chip_strategy import EDITION
    if plan.kind != EDITION or not 1 <= len(plan.extra["weeks"]) <= 5:
        raise RequiredInput("Slot 25 plan and verified rolling horizon required")
    data = plan.extra
    canvas = Image.new("RGB",SIZE,BG)
    draw = ImageDraw.Draw(canvas)
    approved_sell_logo(canvas,box=(12,8,350,169),matte=BG)
    draw.line((364,22,364,153),fill=GOLD,width=3)
    text(draw,plan.title,382,32,1004,49,WHITE,30,center=True)
    text(draw,data["span"]+"  •  "+data["data_date"]+"  •  REFERENCE SQUAD",382,100,1004,25,GOLD,17,center=True)
    draw.rounded_rectangle((1400,26,1577,139),radius=16,fill=FOREST,outline=GOLD,width=3)
    text(draw,"25/25",1410,55,157,39,WHITE,27,center=True)

    for i,(chip,name) in enumerate(CHIPS.items()):
        x = 18+i*395
        card = data["cards"][chip]
        pick = card["pick"]
        draw.rounded_rectangle((x,177,x+378,590),radius=17,fill=WHITE,outline=GOLD,width=3)
        draw.rounded_rectangle((x+3,180,x+375,239),radius=13,fill=FOREST)
        text(draw,name.upper(),x+11,192,356,30,WHITE,21,center=True)
        conditional = pick and pick["conditional"]
        call = "HOLD / CONDITIONAL" if conditional else "PLAN" if pick else "HOLD"
        draw.rounded_rectangle((x+13,315,x+365,360),radius=9,fill=GOLD)
        text(draw,call,x+18,321,342,26,INK,19,center=True)
        draw.rounded_rectangle((x+13,370,x+365,427),radius=9,fill=FOREST)
        value = f"GW{pick['gw']}  {pick['xpts']:+.1f} xPts" if pick else "WAIT FOR BETTER WINDOW"
        text(draw,value,x+18,382,342,32,WHITE,18,center=True)
        usage = card["usage"]
        if chip=="3xc" and pick:
            p = next((p for p in snapshot.players if p["id"]==pick["player_id"]),None)
            if p is None:
                raise RequiredInput("Reference captain identity unavailable")
            photo = _media(session,snapshot.photo_code(p),"photo",{})
            crest = _media(session,snapshot.team_code(p),"crest",{})
            if photo is None or crest is None:
                raise RequiredInput("Authentic captain portrait and crest required")
            contain(canvas,photo,(x+18,242,74,68),bottom=True,crop_alpha=True)
            contain(canvas,crest,(x+302,248,55,55))
            text(draw,snapshot.name(p),x+97,261,200,22,INK,15,center=True)
        else:
            text(draw,f"{usage:.1f}% used" if usage is not None else "Usage not verified",
                 x+18,253,342,24,INK,17,center=True)
            text(draw,f"Set ends GW{card['expires']}" if card["expires"] else "No active chip set",
                 x+18,284,342,18,INK,14,center=True)
        detail = pick["detail"] if pick else "No positive eligible scenario selected in this window."
        paragraph(draw,detail,(x+19,440,340),22,INK,lines=4)
        notes = {"bboost":"Gross bench gain before auto-subs","wildcard":"Gain through forecast horizon",
                 "freehit":"One-week gain vs reference XI","3xc":"Extra above normal captaincy"}
        text(draw,notes[chip],x+15,553,348,17,FOREST,13,center=True)

    weeks = data["weeks"]
    left = 315
    cell = 1260/len(weeks)
    draw.rounded_rectangle((18,610,1580,865),radius=14,fill=WHITE,outline=GOLD,width=3)
    draw.rounded_rectangle((21,613,1577,666),radius=10,fill=FOREST)
    text(draw,"CHIP UPLIFT (xPts)",32,625,270,25,WHITE,19)
    for j,gw in enumerate(weeks):
        text(draw,f"GW{gw}",left+j*cell,623,cell-5,28,GOLD,18,center=True)
    for i,(chip,name) in enumerate(CHIPS.items()):
        y=671+i*46
        rows=data["rows"][chip]
        if [r["gw"] for r in rows]!=weeks:
            raise RequiredInput("Chip scenario weeks do not match target horizon")
        text(draw,name.upper(),32,y+7,270,23,INK,17)
        for j,row in enumerate(rows):
            x=left+j*cell
            draw.rounded_rectangle((x,y,x+cell-5,y+42),radius=5,fill=MINT)
            val=row["xpts"]
            text(draw,f"{val:+.1f}" if val is not None else "Ineligible",x+5,y+5,cell-15,27,INK,17,center=True)

    draw.rounded_rectangle((18,885,1580,1002),radius=14,fill=WHITE,outline=GOLD,width=3)
    text(draw,"FIXTURE TARGETS",32,909,265,23,FOREST,16)
    text(draw,"Top three player xPts",32,945,265,17,INK,13)
    targets=data["targets"]
    if not targets:
        text(draw,"No verified qualifying fixture targets",325,920,1225,25,INK,18,center=True)
    for i,row in enumerate(targets[:3]):
        x=315+i*420
        text(draw,f"GW{row['gw']}  {row['club']} v {row['opponent']}",x,909,403,21,INK,15)
        text(draw,f"{row['total']:.1f} combined xPts  •  {row['venue']}",x,945,403,19,FOREST,14)
    text(draw,data["forecast"]+"  •  £100m reference squad  •  scenarios are separate",
         24,1017,1552,20,WHITE,15,center=True)
    text(draw,"Retrieved "+data["retrieved_at"]+"  •  one chip per GW  •  check your actual squad",
         24,1054,1552,18,MUTED,14,center=True)
    approved_social_footer(canvas,reserved_height=88)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"PNG",optimize=True)
    return output
