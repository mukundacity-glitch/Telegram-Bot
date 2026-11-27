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
        from .daily_cutover import slots as daily_slots
        for daily in daily_slots(day):
            at = slot_start(daily, day)
            if collides(at):
                conflicts.append((daily.edition, at.isoformat()))
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
    rises = sorted((r for r in rows if r["projected"] > 0), key=lambda r:(-r["projected"],-r["progress"],r["player"]["id"]))[:10]
    falls = sorted((r for r in rows if r["projected"] < 0), key=lambda r:(r["projected"],r["progress"],r["player"]["id"]))[:10]
    if not rises and not falls:
        raise RequiredInput("No verified next-update predictions")
    return rises, falls


def build_board(snapshot, update_at, previous=None):
    if update_at <= snapshot.fetched_at:
        raise RequiredInput("Prediction update is not in the future")
    rises, falls = select_rows(snapshot, update_at, previous)
    label = update_at.astimezone(UK).strftime("%H:%M UK")
    caption = (
        "⏱ PRICE CHANGE PREDICTION\n"
        f"MONITOR {label}\n\n"
        f"📈 {len(rises)} rise candidates • 📉 {len(falls)} fall candidates\n"
        "Official FPL projections. Moves are not guaranteed.\n\n"
        "#FPL #PriceChanges #FPLTips #FantasyPremierLeague #FPLVORTEX #FPLUpdates"
    )
    return dict(rises=rises, falls=falls, update_at=update_at.isoformat(), caption=caption)


PRICE_ART_SIZE = (1600, 1200)


def render_board(snapshot, board, output, session):
    """The supplied 4:3 two-panel price reference, with current official data."""
    from PIL import Image, ImageDraw
    from .brand_footer import MASTER, verify_exact_master
    from .comparison_board import contain, text
    from .matchup import _image_from_url, _media

    verify_exact_master()
    W, H = PRICE_ART_SIZE
    purple, ink, muted = "#37003C", "#201A29", "#535366"
    white, cyan, emerald = "#FFFFFF", "#04F5FF", "#00FF87"
    green, red = "#008553", "#B91F45"
    canvas = Image.new("RGB", (W, H), purple)
    d = ImageDraw.Draw(canvas)
    with Image.open(MASTER) as original:
        master = original.convert("RGB").resize((1536,864))
        canvas.paste(master.crop((0,0,310,80)).resize((158,41),Image.Resampling.LANCZOS),(34,37))
    def label(value, x, y, width, size, color=white, center=False, minimum=14):
        text(d, value, x, y, width, size=size, color=color, minimum=minimum, center=center)

    update = datetime.fromisoformat(board["update_at"])
    local = snapshot.fetched_at.astimezone(UK)
    label("PRICE CHANGE PREDICTIONS", 220, 26, 1340, 52)
    label(local.strftime("%A, %d %B %Y"), 220, 83, 1340, 29, emerald)
    label("Fantasy Premier League • daily price movement watch", 220, 119, 1340, 21)
    cache = {}
    def side(rows, x, accent, heading, pale):
        width = 756
        d.rounded_rectangle((x,160,x+width,1122),radius=20,fill=white,outline=cyan,width=2)
        d.rounded_rectangle((x,160,x+width,216),radius=18,fill=accent)
        d.rectangle((x,192,x+width,216),fill=accent)
        label(heading,x+22,171,width-44,31)
        label("PLAYER / CLUB",x+87,225,360,20,ink)
        label("LIKELIHOOD",x+443,225,142,17,ink,True)
        label("PREDICTION",x+598,225,145,17,ink,True)
        if not rows:
            label("No verified candidates",x+25,280,width-50,24,muted,True)
        for index, row in enumerate(rows[:10]):
            p = row["player"]
            y = 260 + index*84
            d.rounded_rectangle((x+12,y,x+width-12,y+76),radius=11,fill=pale,outline="#DDD6E0",width=1)
            d.rectangle((x+12,y,x+19,y+76),fill=accent)
            code = snapshot.photo_code(p)
            urls = (
                f"https://resources.premierleague.com/premierleague25/photos/players/250x250/{code}.png",
                f"https://resources.premierleague.com/premierleague25/photos/players/110x140/{code}.png",
                f"https://resources.premierleague.com/premierleague/photos/players/250x250/p{code}.png",
                f"https://images.fantasy.premierleague.com/premierleague/photos/players/250x250/p{code}.png",
            )
            photo = next((img for url in urls if (img := _image_from_url(session,url)) is not None),None)
            crest = _media(session,snapshot.team_code(p),"crest",cache)
            if crest is None:
                raise RequiredInput(f"Authentic club crest missing for official player {p['id']}")
            if photo is not None:
                contain(canvas,photo,(x+25,y+4,66,69),bottom=True,crop_alpha=True)
            else:
                contain(canvas,crest,(x+33,y+7,48,48))
                label("NO PHOTO",x+23,y+56,70,11,muted,True,10)
            label(snapshot.name(p),x+102,y+5,327,29,ink)
            contain(canvas,crest,(x+103,y+43,23,23))
            label(f"{snapshot.team(p)}  •  {snapshot.price(p)}",x+132,y+43,300,19,muted)
            d.rounded_rectangle((x+446,y+25,x+583,y+54),radius=14,fill="#E2F5EA" if accent==green else "#FBE2E8")
            # Official signed likelihood band; no invented probability/word mapping.
            label(f"BAND {row['likelihood']:+d}",x+450,y+29,129,17,accent,True)
            label("TARGET %",x+600,y+7,139,14,muted,True,12)
            label(f"{abs(row['projected']):.1f}%",x+599,y+28,140,29,accent,True)
    side(board["rises"],28,green,"▲ PRICE RISES","#F9FCFA")
    side(board["falls"],816,red,"▼ PRICE DROPS","#FFF9FA")
    label("FPL VORTEX • Official FPL projections • Target progress, not probability • Likelihood: official signed band",
          30,1136,1540,19,white,True)
    label("Expected update: "+update.astimezone(UK).strftime("%H:%M UK")+" • Price movements are not guaranteed",
          30,1166,1540,17,emerald,True)
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
