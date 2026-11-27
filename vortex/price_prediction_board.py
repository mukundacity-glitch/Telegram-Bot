"""Price prediction 16/55: independent, read-only preparation for scheduler migration.

Official FPL bootstrap-static predictions, not confirmed price changes.
The caller supplies the verified next update time; never infer it from a player's data.
"""
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from math import isfinite
from .editorial_inputs import RequiredInput

UK = ZoneInfo("Europe/London")
EDITION = "price-prediction"  # replaces retired confirmed-price-changes at 16/55
SOURCE = "https://fantasy.premierleague.com/api/bootstrap-static/"


def next_published_update(now):
    """PL's published daily midnight UK rule; not a scraped API clock."""
    if now.tzinfo is None:
        raise ValueError("timezone-aware time required")
    local = now.astimezone(UK)
    return datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=UK)


def official_clock(bootstrap, now):
    """Exact live API paths verified in the 26 Nov 2026 read-only audit."""
    if now.tzinfo is None:
        raise ValueError("timezone-aware time required")
    try:
        config=bootstrap["game_config"]
        deadlines=config["settings"]["price_change_deadlines"]
        updated=datetime.fromisoformat(config["status"]["price_change_last_updated"].replace("Z","+00:00"))
        if updated.tzinfo is None or not -timedelta(minutes=2) <= now-updated <= timedelta(minutes=45):
            raise ValueError("stale prediction timestamp")
        if not isinstance(deadlines,list) or not deadlines:
            raise ValueError("missing deadlines")
        parsed=[datetime.fromisoformat(v.replace("Z","+00:00")) for v in deadlines]
        if any(v.tzinfo is None for v in parsed):
            raise ValueError("timezone missing")
        # Offset zero refers to the first source deadline, not the next guessed midnight.
        # Do not advance past a stale first deadline while keeping old projections.
        if parsed != sorted(set(parsed)) or not timedelta(0) < parsed[0]-now <= timedelta(hours=26):
            raise ValueError("invalid/stale first deadline")
        return parsed[0], updated
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError) as exc:
        raise RequiredInput("Official FPL price clock unavailable or stale") from exc


PRICE_LEAD = timedelta(hours=1)
PRICE_RESEARCH_LEAD = timedelta(hours=4, minutes=15)
PRICE_GRACE = timedelta(minutes=15)
RESEARCH_KEY = "_pre_gameweek_price_research"


def price_observation(snapshot):
    """Verified cost and calibrated next-update state, keyed by official player ID."""
    result = {}
    for player in snapshot.players:
        pid, cost = player.get("id"), player.get("now_cost")
        if type(pid) is not int or type(cost) is not int or cost <= 0:
            continue
        if str(pid) in result:
            raise RequiredInput("Duplicate official player identity")
        projection = player.get("price_change_projections")
        rows = [row for row in projection if isinstance(row, dict) and row.get("offset") == 0] if isinstance(projection, list) else []
        projected = numeric(rows[0].get("projected_percent")) if len(rows) == 1 and player.get("price_change_calibrating") is False else None
        band = rows[0].get("likelihood") if projected is not None else None
        result[str(pid)] = {"code": player.get("code"), "cost": cost,
                            "threshold": (1 if projected >= 100 else -1 if projected <= -100 else 0) if projected is not None else None,
                            "band": band if type(band) is int and -5 <= band <= 5 else None,
                            "transfers_in_event": player.get("transfers_in_event"),
                            "transfers_out_event": player.get("transfers_out_event"),
                            "ownership": player.get("selected_by_percent"),
                            "status": player.get("status"), "news": player.get("news")}
    if not result:
        raise RequiredInput("No verified price observation")
    return result


def material_changes(previous, current):
    """Only real cost deltas or a verified threshold/likelihood transition qualify."""
    changes = []
    for pid, new in current.items():
        old = previous.get(pid)
        if not isinstance(old, dict) or old.get("code") != new.get("code"):
            continue
        fields = [key for key in ("cost", "threshold", "band")
                  if old.get(key) is not None and new.get(key) is not None and old[key] != new[key]]
        if fields:
            changes.append({"id": int(pid), "before": {key: old[key] for key in fields},
                            "after": {key: new[key] for key in fields}})
    return changes


def research_evidence(snapshot, now, update, state):
    """Match verified advance research to the T-1 run; require at least three elapsed hours."""
    from .autonomous_schedule import season_id
    row = state.get(RESEARCH_KEY, {})
    if not isinstance(row, dict) or row.get("update_at") != update.isoformat() or row.get("gw") != snapshot.gameweek() or row.get("season") != season_id(snapshot, now):
        return None
    try:
        checked = datetime.fromisoformat(row["checked_at"])
        if not update-PRICE_RESEARCH_LEAD <= checked < update-PRICE_RESEARCH_LEAD+PRICE_GRACE:
            return None
        from .research_gap import verified_gap
        if snapshot.fetched_at <= checked or not verified_gap(row['checked_at'], update-PRICE_LEAD) or not verified_gap(row['checked_at'], now):
            return None
        changes = material_changes(row["players"], price_observation(snapshot))
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return {"checked_at": checked.isoformat(), "changes": changes}



def opportunity(snapshot, now, state):
    """Find the API-clock opportunity without moving any other editorial slot."""
    from .autonomous_schedule import ET, SLOTS, Slot, eligible_on, slot_start, special_triggers, publication_key, season_id, retryable
    from .schedule import SLOT_HOURS
    from .fpl import upcoming_deadline
    from .publishing_window import allowed
    from .telegram_spacing import GAP
    update, updated = official_clock({"game_config": snapshot.game_config}, max(now, snapshot.fetched_at))
    update = update.astimezone(timezone.utc)
    trigger = update - PRICE_LEAD
    local = trigger.astimezone(ET)
    slot = Slot("price_changes", EDITION, local.hour, local.minute,
                display_name="Price Change Prediction", price_update_at=update.isoformat())
    key = publication_key(slot, now, snapshot.gameweek(), season_id(snapshot, now))
    info = {"post": EDITION, "trigger": trigger.isoformat(), "update_at": update.isoformat(),
            "source_updated_at": updated.isoformat()}
    target_deadline = upcoming_deadline(snapshot)
    if not snapshot.gameweek() or target_deadline is None or now >= target_deadline or trigger >= target_deadline:
        return None, {**info, "status": "no-actionable-gameweek"}
    existing = state.get(key, {})
    if existing.get("identity") or not retryable(existing):
        return None, {**info, "status": "closed"}
    if now >= trigger + PRICE_GRACE:
        return None, {**info, "status": "missed-window"}
    if not allowed(trigger):
        return None, {**info, "status": "outside-publishing-window"}
    # Protect actual research and publication windows, not the idle time between.
    research_at = update - PRICE_RESEARCH_LEAD
    def collides(at):
        return (research_at-GAP < at < research_at+PRICE_GRACE
                or trigger-GAP < at < trigger+GAP)
    conflicts = []
    for offset in (-1, 0, 1):
        day = local + timedelta(days=offset)
        for other in SLOTS:
            if eligible_on(other, day):
                at = slot_start(other, day)
                if collides(at):
                    conflicts.append((other.edition, at.isoformat()))
        for name, (hour, minute) in SLOT_HOURS.items():
            at = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if collides(at):
                conflicts.append((name, at.isoformat()))
    for other, at in special_triggers(snapshot, now):
        if at is not None and collides(at):
            if retryable(state.get(publication_key(other, now, snapshot.gameweek(), season_id(snapshot, now)), {})):
                conflicts.append((other.edition, at.isoformat()))
    if conflicts:
        return None, {**info, "status": "skipped-schedule-conflict", "conflicts": sorted(set(conflicts))}
    research_at = update - PRICE_RESEARCH_LEAD
    if research_at <= now < research_at + PRICE_GRACE:
        prior = state.get(RESEARCH_KEY, {})
        if prior.get("update_at") != update.isoformat() or prior.get("gw") != snapshot.gameweek() or prior.get("season") != season_id(snapshot, now):
            state[RESEARCH_KEY] = {"update_at": update.isoformat(), "gw": snapshot.gameweek(),
                                   "season": season_id(snapshot, now), "checked_at": now.isoformat(),
                                   "fetched_at": snapshot.fetched_at.isoformat(), "players": price_observation(snapshot)}
        return None, {**info, "status": "research-verified"}
    if now < trigger:
        return None, {**info, "status": "waiting"}
    proof = research_evidence(snapshot, now, update, state)
    if proof is None:
        return None, {**info, "status": "research-missing"}
    if not proof["changes"]:
        return None, {**info, "status": "no-new-facts"}
    return slot, {**info, "status": "due", "research": proof}


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if isfinite(n) else None


def ownership_snapshot(snapshot):
    """Aggregate public ownership only; no authenticated manager data."""
    return {"at": snapshot.fetched_at.isoformat(), "players": {
        str(p["code"]): numeric(p.get("selected_by_percent"))
        for p in snapshot.players if type(p.get("code")) is int
    }}


def ownership_trend(snapshot, previous, player):
    """Measured percentage-point delta over the recorded interval, not a forecast."""
    if not isinstance(previous, dict) or not isinstance(previous.get("players"), dict):
        return None
    try:
        at = datetime.fromisoformat(previous["at"])
        elapsed = snapshot.fetched_at - at
    except (KeyError, TypeError, ValueError):
        return None
    if not timedelta(minutes=5) <= elapsed <= timedelta(hours=26):
        return None
    old = numeric(previous["players"].get(str(player.get("code"))))
    current = numeric(player.get("selected_by_percent"))
    return round(current-old, 2) if old is not None and current is not None else None


def select_rows(snapshot, update_at, previous=None):
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
                         owned=numeric(p.get("selected_by_percent")),
                         ownership_delta=ownership_trend(snapshot, previous, p)))
    rises = sorted((r for r in rows if r["projected"] > 0), key=lambda r:(-r["projected"],-r["progress"],r["player"]["id"]))[:8]
    falls = sorted((r for r in rows if r["projected"] < 0), key=lambda r:(r["projected"],r["progress"],r["player"]["id"]))[:8]
    if len(rises) != 8 or len(falls) != 8:
        raise RequiredInput("Need eight verified positive and eight negative next-update predictions")
    return rises, falls


def build_board(snapshot, update_at, previous=None):
    if update_at <= snapshot.fetched_at:
        raise RequiredInput("Prediction update is not in the future")
    rises, falls = select_rows(snapshot, update_at, previous)
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
                f"https://resources.premierleague.pulselive.com/photos/players/250x250/p{code}.png",
                f"https://resources.premierleague.pulselive.com/photos/players/110x140/p{code}.png",
            )
            photo=next((img for url in urls if (img:=_image_from_url(session,url)) is not None),None)
            crest=_media(session,snapshot.team_code(p),"crest",cache)
            if crest is None:
                raise RequiredInput(f"Authentic club crest missing for official player {p['id']}")
            if photo is None:
                # Do not silently omit or substitute a top-ranked player.
                # Authentic club crest and explicit missing-photo notice only.
                contain(canvas,crest,(x+30,y+49,76,76))
                text(d,"NO PHOTO",x+13,y+130,108,14,muted,12,center=True)
                print(f"::warning::Authentic portrait unavailable for FPL player {p['id']}; rank retained")
            else:
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
            text(d,"RATE/HR "+fmt(row["hourly_rate"],0,True),x+126,y+137,168,18,muted,12)
            text(d,"OWN "+fmt(row["owned"],suffix="%"),x+305,y+137,187,18,muted,12)
            status="THRESHOLD MET" if abs(row["projected"])>=100 else "BELOW THRESHOLD"
            text(d,status,x+126,y+156,170,14,accent,11)
            text(d,"OWN Δ "+fmt(row.get("ownership_delta"),2,True,"pp"),x+305,y+156,187,14,muted,11)
    side(board["rises"],18,green,"TOP 8 RISE WATCH")
    side(board["falls"],550,red,"TOP 8 FALL WATCH")
    d.rectangle((0,1770,W,H),fill=navy)
    text(d,"±100% THRESHOLD • NOT GUARANTEED • OWN Δ VS PRIOR SNAPSHOT",20,1778,1040,22,gold,16,center=True)
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
    folder=Path("output/price-prediction-preview")
    folder.mkdir(parents=True,exist_ok=True)
    # Audit public clock metadata without exporting player lists or any private data.
    from .fpl import _fetch_json
    boot=_fetch_json(session,"bootstrap-static/")
    metadata={}
    def inspect(obj,path=""):
        if not isinstance(obj,dict):
            return
        for key,value in obj.items():
            if key in ("elements","events","teams"):
                continue
            location=f"{path}.{key}" if path else key
            if any(word in key.lower() for word in ("price_change","price_update","cutoff","countdown")):
                metadata[location]=value
            elif isinstance(value,dict):
                inspect(value,location)
    inspect(boot)
    print("PRICE CLOCK METADATA:",json.dumps(metadata,default=str)[:5000])
    (folder/"clock-audit.json").write_text(json.dumps(metadata,indent=2),encoding="utf-8")
    update_at, refreshed_at=official_clock(boot,datetime.now(timezone.utc))
    # Use the same response for ranking and timing, preventing mixed-feed data.
    from dataclasses import replace
    snapshot=replace(snapshot,players=boot["elements"],fetched_at=datetime.now(timezone.utc))
    import os
    prior_path=os.getenv("PRICE_PREVIEW_PRIOR")
    prior=None
    if prior_path:
        try:
            prior=json.loads(Path(prior_path).read_text(encoding="utf-8"))
        except (OSError,ValueError):
            pass
    board=build_board(snapshot,update_at,prior)
    board["source_updated_at"]=refreshed_at.isoformat()
    board["clock_source"]="game_config.settings.price_change_deadlines[0]"
    board["ownership_baseline_at"]=prior.get("at") if isinstance(prior,dict) else None
    (folder/"ownership-snapshot.json").write_text(json.dumps(ownership_snapshot(snapshot)),encoding="utf-8")
    # Invalidate stale art before replacing evidence; never pair different snapshots.
    (folder/"graphic-16.png").unlink(missing_ok=True)
    # Save source evidence even if an authentic portrait cannot be fetched.
    (folder/"facts.json").write_text(json.dumps(board,indent=2,ensure_ascii=False),encoding="utf-8")
    (folder/"caption.txt").write_text(board["caption"],encoding="utf-8")
    path=render_board(snapshot,board,folder/"graphic-16.png",session)
    stamp(path,EDITION)
    print(board["caption"])

if __name__=="__main__":
    preview()
