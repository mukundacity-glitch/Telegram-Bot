"""Deterministic premium 4:3 boards with original user-approved branding."""
from pathlib import Path
from PIL import Image, ImageDraw
from .brand_footer import approved_sell_logo, approved_social_footer
from .comparison_board import text, contain
from .editorial_inputs import RequiredInput
from .matchup import _media
from .weekly_green_arrow import EDITIONS

SIZE=(1600,1200)
PALETTES={26:("#172D42","#275671","#77D8E0"),27:("#39263D","#68446B","#E7ACCF"),
          28:("#42261D","#79432B","#F7B96C"),29:("#222C4D","#424F85","#B7CBFF")}
INK="#142333"
GOLD="#E5BA61"
WHITE="#FFFFFF"


def render(number,plan,output,session):
    if plan.kind!=EDITIONS[number][0]:
        raise RequiredInput("Graphic edition mismatch")
    bg,panel,accent=PALETTES[number]
    canvas=Image.new("RGB",SIZE,bg)
    d=ImageDraw.Draw(canvas)
    approved_sell_logo(canvas,box=(12,8,350,166),matte=bg)
    text(d,plan.title,365,28,1035,43,WHITE,27,center=True)
    data=plan.extra
    text(d,f"GW{plan.gw}  •  THROUGH GW{data['through']}  •  VERIFIED RESEARCH",365,101,1035,25,accent,18,center=True)
    d.rounded_rectangle((1415,32,1575,135),radius=14,fill=panel,outline=GOLD,width=3)
    text(d,f"{number}/30",1425,61,140,35,WHITE,25,center=True)
    groups=data["groups"]
    cols=data["columns"]
    total=sum(len(rows) for _,rows in groups)
    if not 1<=total<=10:
        raise RequiredInput("Invalid graphic row count")
    y=177
    row_h=min(77,(835-45*len(groups))//total)
    col_w=550/len(cols)
    cache={}
    for label,rows in groups:
        d.rounded_rectangle((18,y,1582,y+42),radius=9,fill=panel,outline=GOLD,width=2)
        text(d,label,35,y+8,650,23,WHITE,17)
        for j,(name,_) in enumerate(cols):
            text(d,name,1010+j*col_w,y+10,col_w-5,18,WHITE,12,center=True)
        y+=46
        for index,row in enumerate(rows):
            d.rounded_rectangle((18,y,1582,y+row_h-4),radius=9,fill=WHITE,outline=accent,width=1)
            text(d,f"{index+1:02}",29,y+14,45,24,panel,18)
            photo=_media(session,row["photo"],"photo",cache)
            crest=_media(session,row["code"],"crest",cache)
            if photo is None or crest is None:
                raise RequiredInput("Verified media unavailable; no substitute artwork")
            contain(canvas,photo,(78,y+3,70,row_h-9),bottom=True,crop_alpha=True)
            contain(canvas,crest,(151,y+7,48,row_h-18))
            text(d,row["name"],212,y+5,485,26,INK,18)
            minutes=row.get("recent_minutes")
            detail=f"{row['pos']} · {row['price']} · {row['own']:.1f}% OWN"
            if minutes:
                detail+=" · L3 "+"/".join(map(str,minutes))+" min"
            text(d,detail,212,y+35,485,17,INK,12)
            text(d,row["fixture"],710,y+14,285,20,panel,14)
            for j,(_,key) in enumerate(cols):
                value=row[key]
                display=f"{value:+.1f}" if key in ("difference","assist_delta","goal_delta") else f"{value:.2f}" if key in ("xa90","xg90","xg_per_shot") else f"{value:.1f}"
                text(d,display,1010+j*col_w,y+14,col_w-5,27,panel,18,center=True)
            y+=row_h
    if y>1020:
        raise RequiredInput("Graphic data exceeds reserved body")
    text(d,data["note"],25,1025,1550,20,WHITE,14,center=True)
    text(d,"Retrieved "+data["retrieved_at"]+"  •  Check minutes & fixtures before transferring",
         25,1064,1550,18,accent,13,center=True)
    approved_social_footer(canvas,reserved_height=88)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"PNG",optimize=True)
    return output
