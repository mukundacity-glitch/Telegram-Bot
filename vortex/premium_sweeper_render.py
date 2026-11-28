"""Slot 11 portrait leaderboard, original cream / burgundy / copper palette."""
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PIL import Image,ImageDraw
from .comparison_board import contain,text
from .brand_footer import verify_exact_master
from .vortex_style import LION
from .matchup import _media
from .graphic_numbers import CATALOG
from .minimal_theme import extra_social_handles
from .editorial_inputs import RequiredInput

BG="#F0E7D8"
PAPER="#FFF9F0"
INK="#37231F"
WINE="#702B40"
COPPER="#AE5935"
MUTED="#725A4D"
LINE="#D6C2AD"
TRACK="#E4D1BE"
SAGE="#52775E"

def render(plan,output,session):
    verify_exact_master()
    data=plan.extra
    rows=data["rows"]
    if len(rows)!=12 or len({r["id"] for r in rows})!=12:
        raise RequiredInput("Twelve distinct goalkeeper rows required")
    codes=sorted({r["code"] for r in rows})
    with ThreadPoolExecutor(max_workers=8) as pool:
        crests=dict(zip(codes,pool.map(lambda c:_media(session,c,"crest",{}),codes)))
    if any(crests.get(c) is None for c in codes):
        raise RequiredInput("Authentic keeper club crest unavailable")
    canvas=Image.new("RGB",(1080,1920),BG)
    d=ImageDraw.Draw(canvas)
    d.rectangle((0,0,1080,258),fill=WINE)
    with Image.open(LION) as logo:
        contain(canvas,logo,(310,26,460,120))
    index=f"{CATALOG.index('weekly-analysis-3')+1}/{len(CATALOG)}"
    text(d,index,888,21,159,32,PAPER,26,center=True)
    text(d,"SWEEPER KEEPERS",30,151,1020,57,PAPER,44,center=True)
    text(d,f"WEEKLY ANALYSIS 3/7 · THROUGH GW{data['through']}",30,218,1020,28,"#F3C6A4",24,center=True)
    d.rounded_rectangle((38,280,1042,492),radius=18,fill=PAPER,outline=LINE,width=2)
    lead=rows[0]; rate=data["rate_leader"]
    text(d,"SWEEPER ACTIONS",64,300,640,26,WINE,22)
    text(d,lead["name"],64,337,690,47,INK,32)
    text(d,lead["value"],812,313,198,67,WINE,48,center=True)
    d.line((64,402,1016,402),fill=LINE,width=2)
    text(d,f"PER 90 LEADER · {rate['name']}  {rate['rate']:.2f}",64,429,952,32,SAGE,25)
    mx=max(r["value"] for r in rows)
    text(d,"RANK / GOALKEEPER",48,516,600,24,WINE,21)
    text(d,"TOTAL",904,516,125,24,WINE,21,center=True)
    for i,r in enumerate(rows):
        y=552+i*87
        d.rounded_rectangle((38,y,1042,y+80),radius=12,fill=PAPER,outline=LINE,width=1)
        fill=WINE if i<3 else COPPER
        d.rounded_rectangle((52,y+17,107,y+63),radius=9,fill=fill)
        text(d,f"{i+1:02d}",53,y+24,53,27,PAPER,24,center=True)
        contain(canvas,crests[r["code"]],(120,y+12,58,58))
        text(d,r["name"],192,y+8,470,32,INK,25)
        text(d,r["detail"],192,y+47,500,23,MUTED,19)
        d.rounded_rectangle((711,y+34,905,y+48),radius=7,fill=TRACK)
        length=round(194*r["value"]/mx) if mx else 0
        if length:
            d.rounded_rectangle((711,y+34,711+length,y+48),radius=min(7,length/2),fill=fill)
        text(d,r["value"],921,y+22,105,33,WINE,26,center=True)
    text(d,f"TOTALS AND PER 90 · {data['minimum_minutes']}+ MINUTES",40,1622,1000,27,INK,23,center=True)
    text(d,"FPL CORE MATCH DATA · VERIFIED FPL APPEARANCES",40,1664,1000,23,MUTED,20,center=True)
    text(d,"FPL VORTEX · CHECK MINUTES & FIXTURES BEFORE TRANSFERRING",32,1711,1016,26,WINE,20,center=True)
    d.rectangle((0,1775,1080,1920),fill=WINE)
    d.line((38,1775,1042,1775),fill=COPPER,width=4)
    yt,x=extra_social_handles()
    tg=os.getenv("FPL_TELEGRAM_HANDLE","")
    dc=os.getenv("FPL_DISCORD_HANDLE","")
    values=[v for v in ("TELEGRAM  t.me/"+tg.lstrip("@") if tg else "",
        "YOUTUBE  "+yt if yt else "", "DISCORD  "+dc if dc else "", "X  "+x if x else "") if v]
    for i,v in enumerate(values or ["FPL VORTEX"]):
        text(d,v,25+(i%2)*530,1799+(i//2)*55,510,26,PAPER,20,center=True)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"PNG",optimize=True)
    return output
