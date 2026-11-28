"""Slot 30 4:3 conditional transfer comparison, original brand assets."""
from pathlib import Path
from PIL import Image,ImageDraw
from .brand_footer import approved_sell_logo,approved_social_footer
from .comparison_board import text,contain
from .matchup import _media
from .editorial_inputs import RequiredInput
from .weekly_transfer_value import EDITION

BG="#262A30"
BRASS="#D6B66E"
PANEL="#42484F"
INK="#202B32"
WHITE="#FFFFFF"


def render(plan,output,session):
    if plan.kind!=EDITION:
        raise RequiredInput("Wrong transfer board")
    data=plan.extra
    canvas=Image.new("RGB",(1600,1200),BG)
    d=ImageDraw.Draw(canvas)
    approved_sell_logo(canvas,box=(12,8,350,166),matte=BG)
    text(d,plan.title,365,30,1030,44,WHITE,28,center=True)
    text(d,f"GW{data['weeks'][0]}–{data['weeks'][-1]} • {data['free_transfers']} FREE TRANSFERS • CONDITIONAL",
         365,100,1030,24,BRASS,16,center=True)
    d.rounded_rectangle((1415,32,1575,135),radius=14,fill=PANEL,outline=BRASS,width=3)
    text(d,"30/30",1425,62,140,35,WHITE,25,center=True)
    cols=[("GW1 GAIN",810),("HORIZON",960),("HIT",1110),("NET GAIN",1240),("BREAK EVEN",1400)]
    d.rounded_rectangle((18,180,1582,235),radius=10,fill=PANEL,outline=BRASS,width=2)
    text(d,"OUT → IN",35,192,700,26,WHITE,18)
    for label,x in cols:
        text(d,label,x,196,135,19,WHITE,13,center=True)
    cache={}
    for i,row in enumerate(data["rows"]):
        y=248+i*118
        d.rounded_rectangle((18,y,1582,y+109),radius=12,fill=WHITE,outline=BRASS,width=2)
        for j,k in enumerate(("out_player","in_player")):
            p=row[k]
            x=30+j*385
            photo=_media(session,p["photo"],"photo",cache)
            crest=_media(session,p["code"],"crest",cache)
            if photo is None or crest is None:
                raise RequiredInput("Verified transfer pair media required")
            contain(canvas,photo,(x,y+5,87,99),bottom=True,crop_alpha=True)
            contain(canvas,crest,(x+91,y+12,49,49))
            text(d,p["name"],x+145,y+19,224,26,INK,18)
            text(d,p["price"],x+145,y+62,224,20,PANEL,15)
        values=[f"{row['gw1']:+.1f}",f"{row['gross']:+.1f}",str(row["hit"]),
                f"{row['net']:+.1f}",f"{row['break_even']} GW" if row["break_even"] else "Not reached"]
        for value,(_,x) in zip(values,cols):
            text(d,value,x,y+36,135,29,INK,16,center=True)
    text(d,"Positive net gain is a model estimate, not a guaranteed return.",25,970,1550,23,BRASS,16,center=True)
    text(d,data["note"],25,1007,1550,19,WHITE,14,center=True)
    text(d,"Model: "+str(data["model"])+" • Retrieved "+data["retrieved_at"],25,1049,1550,18,WHITE,13,center=True)
    approved_social_footer(canvas,reserved_height=88)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"PNG",optimize=True)
    return output
