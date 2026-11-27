"""Dynamic premium press broadcast. The approved mock-up is layout only.

Real club badges, original approved brand marks, optional matched official player
portrait, verified source text. No sample report, club roster or quote is reused.
"""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
import re

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter
from .brand_footer import MASTER
from .matchup import _image_from_url

W, H = 1920, 1080
WHITE = "#f8f7ff"
GOLD = "#ffed38"
MUTED = "#c2c2e3"
PURPLE = "#b950ff"
BLUE = "#416bff"
DARK = "#090820"


@lru_cache(maxsize=128)
def font(size, bold=False, italic=False):
    suffix = "-BoldOblique" if bold and italic else "-Bold" if bold else "-Oblique" if italic else ""
    return ImageFont.truetype("DejaVuSansCondensed" + suffix + ".ttf", size)


def _crest(team):
    code = team.get("code")
    if type(code) is not int or code <= 0:
        return None
    with requests.Session() as session:
        for size in (70, 50):
            found = _image_from_url(session, f"https://resources.premierleague.com/premierleague/badges/{size}/t{code}.png")
            if found is not None:
                return found
    return None


def featured_player(players, facts):
    """Only an unambiguous current-club player named in actual report text."""
    for key, fact in facts.items():
        try:
            club = int(key)
        except (ValueError, TypeError):
            continue
        report = str(fact.get("news", "")) + " " + str(fact.get("quote", ""))
        candidates = []
        for p in players:
            if p.get("team") != club or type(p.get("code")) is not int or p["code"] <= 0:
                continue
            aliases = (p.get("web_name", ""), " ".join((p.get("first_name", ""), p.get("second_name", ""))).strip())
            if any(len(a) >= 5 and re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", report, re.I) for a in aliases):
                candidates.append(p)
        if len(candidates) == 1:
            return candidates[0]
    return None


def _portrait(player):
    if not player:
        return None
    code = player["code"]
    with requests.Session() as session:
        for url in (f"https://resources.premierleague.com/premierleague25/photos/players/250x250/{code}.png",
                    f"https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png",
                    f"https://images.fantasy.premierleague.com/premierleague/photos/players/250x250/p{code}.png"):
            found = _image_from_url(session, url)
            if found is not None:
                return found
    return None


def render(path, day, names, facts, locked, teams=None):
    # Smooth broadcast gradient with violet and electric-blue edge lighting.
    canvas = Image.new("RGB", (W, H), DARK)
    grad = Image.new("RGB", (1, H))
    grad.putdata([(int(7+8*y/H), int(7+3*y/H), int(22+30*y/H)) for y in range(H)])
    canvas = grad.resize((W, H))
    glow = Image.new("RGB", (W, H))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-430, 260, 470, 1160), fill="#480391")
    gd.ellipse((1450, -180, 2370, 1220), fill="#004ac0")
    gd.ellipse((390, -350, 1500, 200), fill="#7100bf")
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    from PIL import ImageChops
    canvas = ImageChops.screen(canvas, glow)
    d = ImageDraw.Draw(canvas)

    def fit(value, width, size, bold=False, italic=False, minimum=15):
        value = " ".join(str(value).split())
        while size > minimum and d.textlength(value, font=font(size, bold, italic)) > width:
            size -= 1
        face = font(size, bold, italic)
        if d.textlength(value, font=face) > width:
            while value and d.textlength(value+"…", font=face) > width:
                value = value[:-1]
            value = value.rstrip()+"…"
        return value, face

    def text(x, y, value, width, size=26, color=WHITE, bold=False, italic=False, anchor="lt"):
        value, face = fit(value, width, size, bold, italic)
        d.text((x, y), value, font=face, fill=color, anchor=anchor)

    def wrap(value, width, size, max_lines, bold=False):
        lines, line = [], ""
        for word in str(value).split():
            trial = (line+" "+word).strip()
            if line and d.textlength(trial, font=font(size, bold)) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip()+"…"
        return lines

    def card(box, radius=18, accent=PURPLE, strong=False, banner=False):
        x,y,r,b = box
        # Soft glow outside the edge, with a bright bevel and a dark glossy interior.
        for n in (12, 8, 4):
            d.rounded_rectangle((x-n,y-n,r+n,b+n), radius=radius+n,
                                outline=("#36156b" if n>4 else "#7937d0") if strong else "#24103d", width=2)
        d.rounded_rectangle(box, radius=radius, fill="#100b2b" if not banner else "#381193",
                            outline=accent, width=3 if strong else 1)
        d.line((x+radius,y+2,r-radius,y+2), fill="#e4baff" if strong else "#7852b9", width=2)
        if banner:
            d.rounded_rectangle((x+3,y+3,r-3,y+max(5,(b-y)//2)), radius=max(5,radius-3), fill="#5820d0")
            d.line((x+radius,y+3,r-radius,y+3), fill="#f0c6ff", width=2)

    def icon(x, y, kind, size=36):
        # Draw vector icons, not font-dependent emoji.
        c = WHITE
        if kind == "mic":
            d.rounded_rectangle((x+size*.34,y+2,x+size*.66,y+size*.57),radius=6,fill=c)
            d.arc((x+size*.19,y+size*.18,x+size*.81,y+size*.73),0,180,fill=c,width=3)
            d.line((x+size/2,y+size*.72,x+size/2,y+size*.9),fill=c,width=3)
            d.line((x+size*.28,y+size*.9,x+size*.72,y+size*.9),fill=c,width=3)
        else:
            d.rounded_rectangle((x+3,y+6,x+size-3,y+size-3),radius=5,outline=c,width=3)
            d.line((x+4,y+size*.36,x+size-4,y+size*.36),fill=c,width=3)
            for dx in (.28,.69):
                d.line((x+size*dx,y+1,x+size*dx,y+size*.24),fill=c,width=4)
            for dx in (.29,.5,.71):
                for dy in (.53,.72):
                    d.ellipse((x+size*dx-2,y+size*dy-2,x+size*dx+2,y+size*dy+2),fill=c)

    def panel(box,label,kind,tab):
        x,y,r,b=box
        card(box,26,strong=True)
        card((x+14,y+12,x+tab,y+71),17,strong=True,banner=True)
        icon(x+27,y+23,kind,37)
        text(x+79,y+23,label,tab-93,33,bold=True,italic=True)

    def badge(pic, box):
        if pic is None:
            return
        x,y,r,b=box
        a=ImageOps.contain(pic.convert("RGBA"),(r-x,b-y),Image.Resampling.LANCZOS)
        canvas.paste(a,(x+(r-x-a.width)//2,y+(b-y-a.height)//2),a)

    def highlight(x,y,line,width,size):
        # Highlight existing factual keywords without changing the report.
        words=re.split(r"(\s+)",line)
        for word in words:
            f=font(size)
            strong=bool(re.search(r"\b(fit|available|injur\w*|out|doubt\w*|return\w*|training|rotation|minutes|suspend\w*)\b",word,re.I))
            w=d.textlength(word,font=f)
            if w>width: break
            d.text((x,y),word,font=f,fill=GOLD if strong else WHITE,anchor="lt")
            x+=w
            width-=w

    # Actual official logo and league mark are cropped from the pinned user master.
    with Image.open(MASTER) as source:
        master=source.convert("RGB")
        mw,mh=master.size
        brand=master.crop((0,0,round(mw*.145),round(mh*.071)))
        league=master.crop((round(mw*.885),0,mw,round(mh*.071)))
        canvas.paste(brand.resize((396,110),Image.Resampling.LANCZOS),(8,6))
        canvas.paste(league.resize((232,104),Image.Resampling.LANCZOS),(1680,7))
    card((430,10,1292,103),24,strong=True,banner=True)
    icon(456,23,"mic",64)
    text(536,27,"PRESS CONFERENCE",735,66,bold=True,italic=True)
    text(1318,15,f"GAMEWEEK {day['gw']}",345,40,bold=True,italic=True)
    text(1318,62,f"{day['season']}/{str(day['season']+1)[-2:]}",345,36,GOLD,True,True)
    at=day.get("data_at")
    stamp=at.strftime("%d %b %Y • %H:%M UTC") if at else "Report time unavailable"
    text(960,119,("UPDATED • " if day.get("updated") else "DATA AS OF • ")+stamp,1850,23,GOLD,True,anchor="mt")
    d.line((16,146,1904,146),fill="#8e44ff",width=3)

    panel((12,162,564,965),"LATEST NEWS","calendar",410)
    panel((578,162,1256,678),"KEY QUOTES","mic",410)
    panel((578,692,1256,965),"MANAGER'S NOTES","calendar",510)
    panel((1270,162,1908,965),"PRESS CONFERENCE ROUND-UP","mic",624)

    ordered=sorted(((k,v) for k,v in facts.items() if k in names and v.get("news")),
                   key=lambda kv:(kv[1].get("published",""),names[kv[0]]),reverse=True)
    crests={}
    if teams:
        with ThreadPoolExecutor(max_workers=8) as pool:
            keys=list(names)
            crests=dict(zip(keys,pool.map(_crest,[teams.get(int(k),{}) for k in keys])))
    for i,(key,fact) in enumerate(ordered[:8]):
        y=244+i*88
        card((26,y,550,y+81),15)
        badge(crests.get(key),(36,y+11,95,y+71))
        if crests.get(key) is None:
            text(64,y+25,names[key][:2].upper(),48,23,GOLD,True,anchor="mt")
        text(108,y+8,names[key],428,22,"#d3b9ff",True)
        for j,line in enumerate(wrap(fact["news"],428,22,2)):
            highlight(108,y+34+j*23,line,428,22)
    if not ordered:
        text(35,266,"Awaiting verified club reports",505,27,MUTED)

    quotes=[(k,v["quote"]) for k,v in ordered if v.get("quote")]
    player=featured_player(day.get("players",()),dict(ordered))
    portrait=_portrait(player) if player and len(quotes)<=4 else None
    # Use a real player only if clearly mentioned and there is a safe dedicated strip.
    right=1036 if portrait is not None else 1242
    if portrait is not None:
        badge(portrait,(1040,270,1242,590))
        text(1141,604,player.get("web_name",""),192,22,GOLD,True,anchor="mt")
    for i,(key,quote) in enumerate(quotes[:4]):
        y=244+i*104
        card((591,y,right,y+96),15)
        text(606,y+5,"“",44,52,GOLD,True)
        text(653,y+7,names[key],right-666,21,"#d3b9ff",True)
        for j,line in enumerate(wrap("“"+quote+"”",right-655,23,2)):
            highlight(648,y+34+j*25,line,right-655,23)
    if not quotes:
        text(600,267,"No attributable quote verified yet.",right-616,25,MUTED)
    # Fill otherwise unused space with source coverage rather than invented quotes.
    if len(quotes)<4:
        y=244+len(quotes)*104+(44 if not quotes else 4)
        if y+56<670:
            text(605,y,f"{len(ordered)}/{len(names)} club reports verified",right-620,23,GOLD,True)
            text(605,y+29,"Further updates follow verified sources.",right-620,21,MUTED)
    notes=ordered[:2]
    for i,(key,fact) in enumerate(notes):
        y=773+i*65
        d.ellipse((601,y+7,617,y+23),fill=GOLD)
        for j,line in enumerate(wrap(f"{names[key]}: {fact['news']}",610,22,2)):
            text(630,y+j*24,line,610,22)
        d.line((600,y+54,1237,y+54),fill="#422172",width=1)
    text(601,915,f"COVERAGE  {len(ordered)}/{len(names)} clubs • Pending reports are not confirmed",635,21,GOLD,True)

    for i,key in enumerate(sorted(names,key=lambda k:names[k])):
        y=244+i*35
        fact=facts.get(key)
        card((1282,y,1896,y+33),10,accent="#5633a6")
        d.rounded_rectangle((1285,y+2,1326,y+31),radius=13,fill="#4b0fc7",outline="#ba6bff",width=1)
        text(1305,y+5,str(i+1),38,22,bold=True,italic=True,anchor="mt")
        badge(crests.get(key),(1331,y+1,1365,y+32))
        if crests.get(key) is None:
            text(1348,y+7,names[key][:2],30,15,GOLD,True,anchor="mt")
        label=names[key]
        text(1374,y+6,label,185,22,bold=True)
        # A report summary is not a quote. Add quotation marks only for verified quotes.
        summary=("“"+fact["quote"]+"”" if fact.get("quote") else fact.get("news","")) if fact else "Awaiting verified report"
        text(1565,y+7,summary,319,21,WHITE if fact else MUTED)
    card((12,984,1908,1070),21,strong=True)
    text(30,993,"STAY UPDATED:",250,29,GOLD,True,True)
    text(265,997,"Verified club reports • Linked sources in caption • Check before FPL deadline",1600,24,WHITE)
    handles=("TELEGRAM  t.me/FPLVortexDailyBot","YOUTUBE  @FPLVORTEX","DISCORD  @fplvortex","X  @FPLVORTEXM")
    for i,value in enumerate(handles):
        text(240+i*480,1035,value,455,24,bold=True,anchor="mt")
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(path,format="PNG")
    from .graphic_numbers import PRESS_REPORT_KEY, stamp as stamp_graphic
    stamp_graphic(path, PRESS_REPORT_KEY, required=True)
