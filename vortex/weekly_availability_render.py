"""Native landscape five-tier transfer desk; missing model points stay blank."""
from pathlib import Path
from PIL import Image,ImageDraw
from .comparison_board import text,contain
from .brand_footer import verify_exact_master
from .vortex_style import LION
from .minimal_theme import social_footer
from .availability_board import TIERS,ACTIONS
from .editorial_inputs import RequiredInput

BG="#131E30"
PANEL="#223248"
PAPER="#F7F3E8"
INK="#17243B"
GOLD="#E3BD77"
COLORS=("#D99B91","#E5B980","#E6D6A5","#A8D6B9","#A9C8E0")
FDR={1:"#A0E7B8",2:"#C9E7C0",3:"#E8D8A6",4:"#F1B6AA",5:"#DC8B9B"}

def render(plan,snapshot,output,session):
    from .autonomous_render import _assets
    verify_exact_master()
    canvas=Image.new("RGB",(1920,1080),BG)
    d=ImageDraw.Draw(canvas)
    with Image.open(LION) as logo:
        contain(canvas,logo,(24,8,214,98))
    text(d,"AVAILABILITY & TRANSFER DECISIONS",260,12,1610,45,PAPER,34)
    text(d,f"GW{plan.gw} · VERIFIED MINUTES · FIXTURES · DECISIONS",264,63,1590,25,GOLD,21)
    text(d,"NEXT GW PRIORITY / FIVE GW OUTLOOK / VERIFIED PLAYER DATA",264,92,1590,19,PAPER,16)
    cache={}
    for index,tier in enumerate(TIERS):
        y=124+index*163
        color=COLORS[index]
        d.rounded_rectangle((24,y,221,y+155),radius=11,fill=color)
        for n,word in enumerate(tier.split(" ")):
            text(d,word,30,y+39+n*31,185,30,INK,23,center=True)
        text(d,ACTIONS[index],30,y+116,185,18,INK,15,center=True)
        ids=plan.extra["tiers"][tier]
        for i in range(5):
            x=231+i*333;w=325
            d.rounded_rectangle((x,y,x+w,y+155),radius=10,fill=PAPER)
            if i>=len(ids):
                text(d,"NO QUALIFIED PICK",x+8,y+66,w-16,21,INK,16,center=True)
                continue
            r=plan.extra["rows"][str(ids[i])];p=r["player"]
            portrait,crest=_assets(snapshot,p,session,cache)
            contain(canvas,portrait,(x+7,y+8,97,97),bottom=True,crop_alpha=True)
            contain(canvas,crest,(x+92,y+13,31,31))
            text(d,snapshot.name(p),x+126,y+6,w-134,25,INK,18)
            text(d,snapshot.price(p),x+126,y+34,83,22,INK,17)
            d.rounded_rectangle((x+210,y+33,x+w-7,y+55),radius=4,fill=color)
            text(d,ACTIONS[index],x+211,y+35,w-219,16,INK,12,center=True)
            for j,metric in enumerate(("xpts1","xpts5")):
                value=r[metric]
                label=("xPts1" if j==0 else "xPts5")+(" —" if value is None else f" {value:.1f}")
                text(d,label,x+126,y+60+j*22,w-134,21,INK,17)
            text(d,"MIN "+" / ".join(map(str,r["recent_minutes"])),x+8,y+106,w-16,17,INK,14,center=True)
            weeks=sorted({m["gw"] for m in r["fixtures"]})
            for j,gw in enumerate(weeks):
                matches=[m for m in r["fixtures"] if m["gw"]==gw and not m["blank"]]
                label="/".join(m["opponent"] for m in matches) or "BLK"
                shade=FDR[max(m["fdr"] for m in matches)] if matches else "#CDD0D6"
                xx=x+5+j*63
                d.rounded_rectangle((xx,y+127,xx+61,y+150),radius=3,fill=shade)
                text(d,label,xx+1,y+130,59,17,INK,10,center=True)
    for j,label in enumerate(("SELL REVIEW","AVOID","HOLD")):
        x=25+j*625
        row=plan.extra["signals"].get(label)
        detail=f"{row['name']} · {row['reason']}" if row else "No verified signal"
        text(d,label+" · "+detail,x,947,610,20,GOLD,15)
    text(d,"xPts — = no verified model coverage · Fixture colours: FDR 1–5 · General watchlist, not a squad-specific transfer instruction.",
         25,974,1870,17,PAPER,14,center=True)
    social_footer(canvas)
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"PNG",optimize=True)
    return output
