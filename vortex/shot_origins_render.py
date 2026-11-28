"""Slot 8 native landscape: legible labels even for tiny shot-share segments."""
from pathlib import Path
from math import isfinite
from PIL import Image,ImageDraw
from .comparison_board import text,contain
from .brand_footer import verify_exact_master
from .vortex_style import LION
from .minimal_theme import social_footer
from .evening_intelligence_render import _crest
from .editorial_inputs import RequiredInput

BG="#102D2B"
PANEL="#193E3A"
ALT="#214A45"
PAPER="#F3F0E6"
MUTED="#BCD1C7"
GOLD="#E8C77B"
COLORS=("#D5A64E","#66C9A9","#D98A9E")
KEYS=("left","centre","right")


def render(plan,output,session):
    verify_exact_master()
    rows=plan.extra["rows"]
    if len(rows)!=20 or len({r["code"] for r in rows})!=20:
        raise RequiredInput("Shot origins requires 20 distinct clubs")
    canvas=Image.new("RGB",(1920,1080),BG)
    d=ImageDraw.Draw(canvas)
    d.rectangle((0,0,1920,111),fill=PANEL)
    with Image.open(LION) as logo:
        contain(canvas,logo,(30,8,220,94))
    text(d,"ATTACKING ZONES · SHOT ORIGINS",270,16,1590,46,PAPER,35)
    text(d,f"THROUGH GW{plan.extra['through']} · LAST {len(plan.extra['weeks'])} COMPLETED ROUNDS",
         274,72,1540,27,GOLD,21)
    d.line((30,111,1890,111),fill=GOLD,width=3)
    text(d,"RANK / TEAM",42,124,390,25,PAPER,22)
    text(d,"LEFT · CENTRE · RIGHT  /  SHARE OF SHOTS",440,124,950,25,PAPER,21)
    for x,key,color in zip((1400,1532,1664),KEYS,COLORS):
        text(d,key.upper(),x,124,122,21,color,18,center=True)
    text(d,"SHOTS",1798,124,95,23,PAPER,19,center=True)
    cache={}
    for i,row in enumerate(rows):
        y=158+i*39
        shares=[float(row[k]) for k in KEYS]
        if (not all(isfinite(v) and 0<=v<=100 for v in shares)
                or abs(sum(shares)-100)>1e-6 or type(row["shots"]) is not int or row["shots"]<=0):
            raise RequiredInput("Invalid shot share or total")
        d.rounded_rectangle((30,y,1890,y+36),radius=5,fill=PANEL if i%2 else ALT)
        text(d,f"{i+1:02d}",42,y+4,46,26,GOLD,21,center=True)
        _crest(canvas,session,cache,row["code"],100,y+2,32)
        text(d,row["name"],146,y+4,282,25,PAPER,20)
        # Widths are proportional to unrounded values; label every share in
        # the aligned columns rather than hiding narrow left/right segments.
        x=440; width=944; used=0
        for j,(value,color) in enumerate(zip(shares,COLORS)):
            edge=round(width*sum(shares[:j+1])/100) if j<2 else width
            if edge>used:
                d.rectangle((x+used,y+6,x+edge-1,y+30),fill=color)
            used=edge
        for x,value,color in zip((1400,1532,1664),shares,COLORS):
            text(d,f"{value:.0f}%",x,y+4,122,26,color,22,center=True)
        text(d,row["shots"],1798,y+4,95,26,PAPER,22,center=True)
    text(d,"FPL Core shot start_y · lateral thirds, not total attacks or FotMob attack-channel data. Shares rounded.",
         35,948,1850,22,MUTED,19,center=True)
    social_footer(canvas)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"PNG",optimize=True)
    return output
