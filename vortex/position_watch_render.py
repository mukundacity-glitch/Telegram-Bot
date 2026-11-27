"""Deterministic 1920x1080 landscape editorial board; no AI-generated assets."""
from pathlib import Path
from PIL import Image,ImageDraw
from .comparison_board import text,contain
from .brand_footer import verify_exact_master
from .vortex_style import LION
from .minimal_theme import social_footer
from .position_watch import GROUPS

SIZE=(1920,1080)
BG="#100D20"
PANEL="#211A34"
PAPER="#F8F6F1"
INK="#20172D"
GOLD="#D9B66B"
TEAL="#80DFD0"
MUTED="#655E72"
FDR={1:("#C7F3D8","#164B35"),2:("#D8F1E7","#1F5B48"),3:("#F2E3BA","#624B1D"),
     4:("#F3CCD2","#8F2941"),5:("#9D294A","#FFFFFF")}


def render_position_watch(plan,snapshot,output,session):
    from .autonomous_render import _assets
    verify_exact_master()
    canvas=Image.new("RGB",SIZE,BG)
    d=ImageDraw.Draw(canvas)
    d.rectangle((0,0,1920,114),fill=PANEL)
    d.rectangle((0,113,1920,117),fill=GOLD)
    with Image.open(LION) as logo:
        contain(canvas,logo,(30,8,245,98))
    text(d,"EXPECTED STATS & POSITION WATCH",292,19,1500,52,"#FFFFFF",37)
    text(d,f"GW{plan.gw}  ·  FORM, MINUTES & NEXT FIVE",295,78,1480,25,TEAL,22)
    text(d,"SLOT 07",1755,82,135,20,GOLD,16,center=True)
    cache={}
    players={p["id"]:p for p in plan.players}
    cards=plan.extra["cards"]
    for col,(pos,label,count) in enumerate(GROUPS):
        x=28+col*468
        w=460
        d.rounded_rectangle((x,135,x+w,939),radius=14,fill=PANEL,outline="#443755",width=2)
        d.rectangle((x+12,147,x+17,187),fill=GOLD)
        text(d,label,x+29,151,w-48,29,"#FFFFFF",23)
        ids=plan.extra["groups"][str(pos)]
        if len(ids)!=count:
            raise ValueError("Position group count changed")
        h=(739-(count-1)*9)//count
        for index,pid in enumerate(ids):
            p=players[pid]; row=cards[pid]; y=195+index*(h+9)
            d.rounded_rectangle((x+9,y,x+w-9,y+h),radius=10,fill=PAPER)
            d.rectangle((x+10,y+10,x+13,y+h-10),fill=GOLD)
            portrait,crest=_assets(snapshot,p,session,cache)
            info_x=x+112
            media_h=min(h-78,130)
            contain(canvas,portrait,(x+18,y+8,88,media_h),bottom=True,crop_alpha=True)
            contain(canvas,crest,(x+w-59,y+9,39,39))
            text(d,snapshot.name(p),info_x,y+8,w-174,29,INK,20)
            text(d,f"{snapshot.price(p)} · OWN {row['ownership']:.1f}%",info_x,y+42,w-130,19,INK,15)
            d.rounded_rectangle((info_x,y+67,info_x+100,y+88),radius=7,fill="#E8D2A5")
            text(d,"MONITOR",info_x+4,y+69,92,14,"#59401A",13,center=True)
            text(d,f"IN {row['in']:,} · OUT {row['out']:,}",info_x+107,y+67,w-230,15,INK,13)
            text(d,"LAST 3 MIN  "+" / ".join(map(str,row["minutes"])),info_x,y+92,w-130,17,MUTED,14)
            m=row["metrics"]
            if pos in (1,2):
                stat=f"CS {m['clean_sheets']:.0f}  ·  xGC {m['expected_goals_conceded']:.2f}"
                if pos==1: stat+=f"  ·  SAVES {m['saves']:.0f}"
            else:
                stat=f"xG {m['expected_goals']:.2f} · xA {m['expected_assists']:.2f} · xGI {m['expected_goal_involvements']:.2f}"
            # With four-card columns, use the whole card width below the portrait.
            text(d,stat,x+20,y+115,w-40,18,INK,15,center=True)
            weeks=sorted({r["gw"] for r in row["fixtures"]})
            if not weeks:
                raise ValueError("Missing official fixture strip")
            cw=(w-38)/5
            # Each double-GW fixture retains its own opponent, venue and numeric FDR.
            fy=y+h-43
            for j,gw in enumerate(weeks):
                xx=int(x+19+j*cw)
                matches=[r for r in row["fixtures"] if r["gw"]==gw]
                if len(matches)>2:
                    raise ValueError("More than two fixtures cannot fit verified landscape card")
                d.rounded_rectangle((xx,fy,xx+int(cw)-3,fy+37),radius=4,fill="#E5E0EB")
                text(d,f"GW{gw}",xx+1,fy+1,cw-5,12,INK,11,center=True)
                for n,r in enumerate(matches):
                    color,fg=FDR.get(r["fdr"],("#D8D8DF",INK))
                    cellw=(cw-4)/len(matches)
                    sx=xx+1+n*cellw
                    d.rectangle((sx,fy+15,sx+cellw-1,fy+36),fill=color)
                    if r["blank"]:
                        detail="BLANK"
                    else:
                        detail=f"{r['opponent']}({r['venue']}) {r['fdr']}"
                    text(d,detail,sx+1,fy+18,cellw-3,13,fg,10,center=True)
    d.rounded_rectangle((28,948,1892,994),radius=9,fill=PANEL,outline=GOLD,width=2)
    text(d,"TRANSFER CHECK  ·  Compare minutes, expected stats and fixtures before transferring. FDR: 1 easiest → 5 hardest.",
         46,958,1828,22,"#FFFFFF",18,center=True)
    social_footer(canvas)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"PNG",optimize=True)
    return output
