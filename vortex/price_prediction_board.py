"""Price prediction 16/55: independent, read-only preparation for scheduler migration.

Official FPL bootstrap-static predictions, not confirmed price changes.
The caller supplies the verified next update time; never infer it from a player's data.
"""
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from pathlib import Path
from math import isfinite
from .editorial_inputs import RequiredInput

UK = ZoneInfo("Europe/London")
EDITION = "confirmed-price-changes"  # stable graphic ID 16/55, not a new catalog entry
SOURCE = "https://fantasy.premierleague.com/api/bootstrap-static/"


def next_published_update(now):
    """PL's published daily midnight UK rule; not a scraped API clock."""
    if now.tzinfo is None:
        raise ValueError("timezone-aware time required")
    local = now.astimezone(UK)
    return datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=UK)


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if isfinite(n) else None


def select_rows(snapshot, update_at):
    if update_at.tzinfo is None:
        raise ValueError("timezone-aware update required")
    rows = []
    seen = set()
    for p in snapshot.players:
        pid = p.get("id")
        if type(pid) is not int or pid in seen or p.get("price_change_calibrating") is not False:
            continue
        if p.get("can_transact") is False:
            continue
        locked = p.get("price_change_locked_until")
        if locked:
            try:
                lock = datetime.fromisoformat(locked.replace("Z", "+00:00"))
                if lock.tzinfo is None or lock > update_at:
                    continue
            except (ValueError, TypeError, AttributeError):
                continue
        projections = p.get("price_change_projections")
        if not isinstance(projections, list):
            continue
        next_rows = [r for r in projections if isinstance(r, dict) and type(r.get("offset")) is int and r["offset"] == 0]
        if len(next_rows) != 1:
            continue
        projected = numeric(next_rows[0].get("projected_percent"))
        progress = numeric(p.get("price_change_percent"))
        band = next_rows[0].get("likelihood")
        cost = p.get("now_cost")
        if (projected is None or projected == 0 or progress is None or type(band) is not int
                or not -5 <= band <= 5 or type(cost) is not int or cost <= 0
                or p.get("element_type") not in (1,2,3,4)
                or not snapshot.photo_code(p) or not snapshot.team_code(p)):
            continue
        seen.add(pid)
        rows.append(dict(player=p, projected=projected, progress=progress, likelihood=band,
                         hourly_rate=numeric(p.get("price_change_hourly_rate")),
                         owned=numeric(p.get("selected_by_percent"))))
    rises = sorted((r for r in rows if r["projected"] > 0), key=lambda r:(-r["projected"],-r["progress"],r["player"]["id"]))[:8]
    falls = sorted((r for r in rows if r["projected"] < 0), key=lambda r:(r["projected"],r["progress"],r["player"]["id"]))[:8]
    if len(rises) != 8 or len(falls) != 8:
        raise RequiredInput("Need eight verified positive and eight negative next-update predictions")
    return rises, falls


def build_board(snapshot, update_at):
    if update_at <= snapshot.fetched_at:
        raise RequiredInput("Prediction update is not in the future")
    rises, falls = select_rows(snapshot, update_at)
    label = update_at.astimezone(UK).strftime("%H:%M UK")
    caption = (
        "⏱ PRICE CHANGE PREDICTION\n"
        f"MONITOR {label}\n\n"
        "📈 Top 8 risers • 📉 Top 8 fallers\n"
        "Official FPL projections. Moves are not guaranteed.\n\n"
        "#FPL #PriceChanges #FPLTips #FantasyPremierLeague #FPLVORTEX #FPLUpdates"
    )
    return dict(rises=rises, falls=falls, update_at=update_at.isoformat(), caption=caption)


def render_board(snapshot, board, output, session):
    """White data body, navy/gold 55-style masthead and icon footer; one portrait PNG."""
    from PIL import Image, ImageDraw, ImageFilter
    from .brand_footer import MASTER, verify_exact_master
    from .comparison_board import contain, text
    from .matchup import _image_from_url, _media
    from .minimal_theme import extra_social_handles
    from .publication_rules import required_footer_handles
    verify_exact_master()
    W,H = 1080,1920
    navy=(5,15,40); gold=(255,205,82); cyan=(34,208,248)
    white=(255,255,255); ink=(18,35,53); muted=(75,94,110)
    green=(0,133,90); red=(202,32,65)
    canvas=Image.new("RGB",(W,H),navy)
    d=ImageDraw.Draw(canvas,"RGBA")
    for points,col in [
        ([(0,0),(290,0),(0,230)],(17,98,225,230)),
        ([(0,40),(160,0),(0,142)],(20,183,255,200)),
        ([(W,0),(W-240,0),(W,235)],(80,54,215,210)),
        ([(0,H),(0,H-200),(220,H)],(20,87,200,190)),
        ([(W,H),(W,H-220),(W-190,H)],(94,52,220,190))]:
        d.polygon(points,fill=col)
    with Image.open(MASTER) as original:
        master=original.convert("RGB").resize((1536,864))
        canvas.paste(master.crop((0,0,310,80)).resize((218,56),Image.Resampling.LANCZOS),(15,12))
        canvas.paste(master.crop((1336,0,1536,80)).resize((145,58),Image.Resampling.LANCZOS),(920,12))
    d=ImageDraw.Draw(canvas,"RGBA")
    text(d,"PRICE CHANGE PREDICTION",248,11,657,40,white,25,center=True)
    update=datetime.fromisoformat(board["update_at"])
    d.polygon([(273,77),(807,77),(793,126),(259,126)],fill=gold)
    text(d,"MONITOR "+update.astimezone(UK).strftime("%H:%M UK"),280,83,520,31,navy,21,center=True)
    text(d,"OFFICIAL FPL • NEXT UPDATE • RANKED BY PROJECTED PROGRESS",30,142,1020,24,white,17,center=True)
    d.line((25,178,1055,178),fill=cyan,width=3)

    cache={}
    def fmt(v,dp=1,signed=False,suffix=""):
        return "—" if v is None else (f"{v:+,.{dp}f}" if signed else f"{v:,.{dp}f}")+suffix

    def side(rows,x,accent,heading):
        width=512
        d.rounded_rectangle((x,188,x+width,1763),radius=18,fill=white,outline=cyan,width=3)
        d.rounded_rectangle((x+3,191,x+width-3,253),radius=12,fill=accent)
        text(d,heading,x+12,204,width-24,32,white,23,center=True)
        for rank,row in enumerate(rows,1):
            p=row["player"]
            y=262+(rank-1)*186
            d.rounded_rectangle((x+8,y,x+width-8,y+176),radius=12,
                                fill=(248,252,250) if accent==green else (255,248,250),
                                outline=(218,230,232),width=2)
            code=snapshot.photo_code(p)
            urls=(
                f"https://resources.premierleague.com/premierleague25/photos/players/250x250/{code}.png",
                f"https://resources.premierleague.com/premierleague25/photos/players/110x140/{code}.png",
                f"https://resources.premierleague.com/premierleague25/photos/players/250x250/p{code}.png",
                f"https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png",
                f"https://resources.premierleague.com/premierleague/photos/players/110x140/p{code}.png",
                f"https://images.fantasy.premierleague.com/premierleague/photos/players/250x250/p{code}.png",
            )
            photo=next((img for url in urls if (img:=_image_from_url(session,url)) is not None),None)
            crest=_media(session,snapshot.team_code(p),"crest",cache)
            if photo is None or crest is None:
                raise RequiredInput(f"Authentic photo/crest missing for official player {p['id']}")
            contain(canvas,photo,(x+16,y+34,104,116),bottom=True,crop_alpha=True)
            contain(canvas,crest,(x+18,y+9,32,32))
            text(d,f"{rank:02d}",x+74,y+8,36,18,accent,15,center=True)
            name=snapshot.name(p)
            text(d,name.upper(),x+126,y+9,width-142,28,ink,18)
            position={1:"GK",2:"DEF",3:"MID",4:"FWD"}[p["element_type"]]
            text(d,f"{snapshot.team(p)} • {position} • {snapshot.price(p)}",x+126,y+42,width-144,19,muted,14)
            # Progress is signed and projected % is a threshold meter, not a probability.
            text(d,"PROGRESS",x+126,y+69,162,17,muted,13)
            text(d,"PREDICTED",x+305,y+69,187,17,muted,13)
            text(d,fmt(row["progress"],signed=True,suffix="%"),x+126,y+89,166,25,ink,18)
            text(d,fmt(row["projected"],signed=True,suffix="%"),x+305,y+86,187,30,accent,19)
            bx=x+126; by=y+120; bw=163
            d.rounded_rectangle((bx,by,bx+bw,by+7),radius=3,fill=(222,230,233))
            n=max(1,round(bw*min(1,abs(row["progress"])/100)))
            d.rounded_rectangle((bx,by,bx+n,by+7),radius=3,fill=accent)
            # Raw hourly-rate unit is not independently documented: do not mislabel it
            # as verified net transfers or manufacture an ownership trend.
            text(d,"RATE "+fmt(row["hourly_rate"],0,True),x+126,y+137,168,18,muted,12)
            text(d,"OWN "+fmt(row["owned"],suffix="%"),x+305,y+137,187,18,muted,12)
            status="THRESHOLD MET" if abs(row["projected"])>=100 else "BELOW THRESHOLD"
            text(d,status,x+126,y+156,width-146,14,accent,11)
    side(board["rises"],18,green,"TOP 8 RISE WATCH")
    side(board["falls"],550,red,"TOP 8 FALL WATCH")
    d.rectangle((0,1770,W,H),fill=navy)
    text(d,"±100% IS THE PRICE-MOVE THRESHOLD • NOT A GUARANTEE",20,1778,1040,22,gold,16,center=True)
    d.line((25,1812,1055,1812),fill=gold,width=2)
    telegram,discord=required_footer_handles()
    youtube,x_handle=extra_social_handles()
    channels=[("youtube",youtube),("x",x_handle),("telegram","t.me/"+telegram.lstrip("@")),("discord",discord)]
    for i,(kind,value) in enumerate(channels):
        if not value:
            continue
        x=30+(i%2)*540;y=1824+(i//2)*43
        if kind=="youtube":
            d.rounded_rectangle((x,y,x+34,y+25),radius=6,fill="#ff1735")
            d.polygon([(x+13,y+5),(x+13,y+20),(x+25,y+12)],fill="white")
        elif kind=="x":
            d.line((x+3,y,x+28,y+26),fill="white",width=3)
            d.line((x+27,y,x+2,y+26),fill="white",width=2)
        elif kind=="telegram":
            d.ellipse((x,y-3,x+32,y+29),fill="#29a9ec")
            d.polygon([(x+5,y+10),(x+27,y+2),(x+21,y+23),(x+15,y+17),(x+10,y+21),(x+12,y+13)],fill="white")
        else:
            d.rounded_rectangle((x,y,x+34,y+25),radius=8,fill="#5865f2")
            d.ellipse((x+7,y+8,x+13,y+14),fill="white")
            d.ellipse((x+21,y+8,x+27,y+14),fill="white")
            d.arc((x+8,y+10,x+26,y+21),0,180,fill="white",width=2)
        text(d,value,x+44,y+1,465,21,white,14)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,"PNG",optimize=True)
    return output


def preview():
    """Never writes outbox, receipts, or calls a publishing client."""
    import json
    from .fpl import collect_snapshot
    from .autonomous_content import retrying_session
    from .graphic_numbers import stamp
    session=retrying_session()
    snapshot=collect_snapshot(session)
    board=build_board(snapshot,next_published_update(snapshot.fetched_at))
    folder=Path("output/price-prediction-preview")
    folder.mkdir(parents=True,exist_ok=True)
    # Save source evidence even if an authentic portrait cannot be fetched.
    (folder/"facts.json").write_text(json.dumps(board,indent=2,ensure_ascii=False),encoding="utf-8")
    (folder/"caption.txt").write_text(board["caption"],encoding="utf-8")
    path=render_board(snapshot,board,folder/"graphic-16.png",session)
    stamp(path,EDITION)
    print(board["caption"])

if __name__=="__main__":
    preview()
