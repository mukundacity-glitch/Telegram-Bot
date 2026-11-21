"""Discover source-published press conference times before each FPL deadline."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state/press_schedule.json"
SCOUT = "https://www.fantasyfootballscout.co.uk"
UK = ZoneInfo("Europe/London")
NEPAL = ZoneInfo("Asia/Kathmandu")
TIME = r"(?:1[0-2]|0?[1-9])(?:[.:][0-5]\d)?\s*[ap]m"


class Article(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.lines = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href") or "")
        if tag in {"br", "p", "blockquote", "li", "h2", "h3"}:
            self.lines.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "blockquote", "li", "h2", "h3"}:
            self.lines.append("\n")

    def handle_data(self, data):
        self.lines.append(data)


def clock(raw):
    raw = re.sub(r"\s+", "", raw.lower()).replace(".", ":")
    fmt = "%I:%M%p" if ":" in raw else "%I%p"
    return datetime.strptime(raw, fmt).strftime("%H:%M")


def parse_slots(html):
    page = Article()
    page.feed(html)
    body = "".join(page.lines)
    marker = re.search(r"FPL press conferences", body, re.I) or re.search(r"press conference times", body, re.I)
    if not marker:
        return []
    section = body[marker.end():][:4000]
    slots = {}
    for line in section.splitlines():
        match = re.match(rf"^[^\w\n]*({TIME})\s*[-–—]\s*(.+)", line.strip(), re.I)
        if match:
            name = re.split(r"https?://|pic\.twitter\.com", match[2])[0].strip()
            if re.fullmatch(r"[^\W\d_][\w ’'\-\.]{0,40}", name):
                slots[name] = clock(match[1])
        elif slots and line.strip() and not re.search(r"^https?://", line.strip()):
            break
    for name in slots:
        correction = re.search(rf"{re.escape(name)}[’']s presser has now been moved to\s+({TIME})", section, re.I)
        if correction:
            slots[name] = clock(correction[1])
    return sorted([[time, name] for name, time in slots.items()])


def discover(gw, now, deadline):
    response = requests.get(SCOUT + "/", params={"s": f"FPL Gameweek {gw} team news"}, timeout=8)
    response.raise_for_status()
    page = Article()
    page.feed(response.text)
    days = {}
    for link in dict.fromkeys(urljoin(SCOUT, href).split("#")[0] for href in page.links):
        url = urlsplit(link)
        match = re.fullmatch(rf"/(\d{{4}})/(\d{{2}})/(\d{{2}})/fpl-gameweek-{gw}-team-news-[\w-]*updates[\w-]*/?", url.path)
        if url.hostname != "www.fantasyfootballscout.co.uk" or not match or url.query:
            continue
        day = date(*map(int, match.groups()))
        if not deadline.astimezone(UK).date()-timedelta(days=5) <= day <= now.astimezone(UK).date() or str(day) in days:
            continue
        article = requests.get(link, timeout=8)
        article.raise_for_status()
        slots = parse_slots(article.text)
        if slots:
            days[str(day)] = {"url": link, "slots": slots}
    return days


def render(path, gw, deadline, days):
    rows = []
    for day, source in sorted(days.items()):
        rows.append((date.fromisoformat(day).strftime("%A  %d %B").upper(), ""))
        groups = defaultdict(list)
        for time, name in sorted(source["slots"]):
            local = datetime.fromisoformat(f"{day}T{time}").replace(tzinfo=UK).astimezone(NEPAL)
            groups[local.strftime("%I:%M %p").lstrip("0")].append(name)
        for time, names in groups.items():
            for start in range(0, len(names), 4):
                rows.append((time if start == 0 else " ", "  ·  ".join(names[start:start+4])))
    height = 360 + 67*len(rows)
    image = Image.new("RGB", (1280, height), "#100d26")
    draw = ImageDraw.Draw(image)
    def label(x, y, value, size, color, bold=False):
        font = ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
        while draw.textlength(value,font=font) > 1240-x:
            size -= 1
            font = ImageFont.truetype(font.path, size)
        draw.text((x,y), value, font=font, fill=color)
    assets = ROOT / "assets/press"
    with Image.open(assets/"logo.jpg") as logo:
        image.paste(ImageOps.contain(logo,(225,120)), (30,20))
    label(280,30,f"GAMEWEEK {gw}   /   FPL VORTEX",29,"#91f3dc",True)
    label(280,72,"Press conference schedule",54,"white",True)
    label(38,162,"All times in Nepal   •   Deadline " + deadline.astimezone(NEPAL).strftime("%a %d %b, %I:%M %p"),32,"#cfc2f6")
    for i, (left, right) in enumerate(rows):
        y = 226 + i*67
        if right:
            label(52,y,left,32,"#8bf2db",True)
            label(265,y,right,34,"#ffffff")
        else:
            draw.rounded_rectangle((30,y-4,1250,y+53),10,fill="#34234e")
            label(50,y+3,left,31,"#dfc5ff",True)
    label(40,height-122,"Timetable source  •  Fantasy Football Scout",25,"#cfc2f6")
    with Image.open(assets/"footer.jpg") as footer:
        image.paste(footer.resize((1280,64)),(0,height-64))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def run(snapshot, now, read, write, client_factory, lookup=discover, live_clock=None):
    from .publishing_window import press_delivery
    upcoming = sorted((datetime.fromisoformat(e["deadline_time"].replace("Z","+00:00")), e["id"])
                      for e in snapshot.events if e.get("deadline_time") and 1 <= e["id"] <= 38 and not e.get("finished"))
    event = next(((d,g) for d,g in upcoming if now < d <= now+timedelta(days=5)), None)
    if not event:
        return False
    deadline, gw = event
    state = read(STATE)
    key = f"{deadline.astimezone(UK).year if deadline.month >= 7 else deadline.year-1}:{gw}"
    row = state.setdefault(key, {})
    if row.get("sending"):
        return False
    days = row.setdefault("days", {})
    # Never replay a historical static timetable: use published live source dates.
    if not row.get("checked") or now-datetime.fromisoformat(row["checked"]) >= timedelta(minutes=30):
        days.update(lookup(gw, now, deadline))
        row["checked"] = now.isoformat()
        write(STATE,state)
    if not days:
        return False
    version = sha256(json.dumps([deadline.isoformat(),days],sort_keys=True).encode()).hexdigest()
    if row.get("version") == version:
        return False
    path = ROOT/"outbox/assets"/f"press-schedule-{key.replace(':','-')}.png"
    render(path,gw,deadline,days)
    # editMessageMedia requires five lines. Earlier free-form URL lists caused
    # production edit failures even though the original image was published.
    source_urls = " · ".join(d["url"] for _, d in sorted(days.items()))
    caption = "\n".join([
        f"GW{gw} • FPL VORTEX press conference timetable",
        f"FPL deadline: {deadline.astimezone(NEPAL):%a %d %b, %I:%M %p} NPT",
        "Verified published press times • Nepal local time",
        "Sources: " + source_urls[:550],
        f"#FPL #FPLVORTEX #GW{gw}",
    ])
    current = live_clock() if live_clock else now
    if current >= deadline:
        return False
    client = client_factory()
    if not row.get("message"):
        row["sending"] = True
        write(STATE,state)
        if os.getenv("GITHUB_ACTIONS") == "true":
            subprocess.run(["bash",".github/scripts/persist-publishing-receipts.sh"],cwd=ROOT,check=True)
    try:
        with press_delivery():
            if row.get("message"):
                mid = client.edit_shared_png(path,caption,row["message"])
            else:
                mid = client.send_shared_png(path,caption,"Press conference schedule",gw)
    except Exception as error:
        if getattr(error,"confirmed_rejection",False):
            row.pop("sending",None)
            write(STATE,state)
        raise
    row.update(message=mid,version=version,sending=False)
    write(STATE,state)
    return True
