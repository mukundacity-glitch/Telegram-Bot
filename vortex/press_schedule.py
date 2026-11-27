"""Discover source-published press conference times before each FPL deadline."""
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import re
from unicodedata import normalize
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import requests

SCOUT = "https://www.fantasyfootballscout.co.uk"
UK = ZoneInfo("Europe/London")
TIME = r"(?:1[0-2]|0?[1-9])(?:[.:][0-5]\d)?\s*[ap]m"


class Article(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.lines = []
        self.title = ""
        self.summary = []
        self.heading = False
        self.in_summary = False
        self.item = None

    def handle_starttag(self, tag, attrs):
        if tag == "meta" and dict(attrs).get("property") == "og:title":
            self.title = dict(attrs).get("content", "")
        if tag in {"h2", "h3", "h4"}:
            self.heading = True
            self.in_summary = False
            self.heading_text = []
        if tag == "li" and self.in_summary:
            self.item = []
        if tag == "a":
            self.links.append(dict(attrs).get("href") or "")
        if tag in {"br", "p", "blockquote", "li", "h2", "h3"}:
            self.lines.append("\n")

    def handle_endtag(self, tag):
        if self.heading and tag in {"h2", "h3", "h4"}:
            self.heading = False
            self.in_summary = bool(re.match(r"key gameweek \d+ team news\b",
                                            "".join(self.heading_text).strip(), re.I))
        if tag == "li" and self.item is not None:
            self.summary.append(" ".join("".join(self.item).split()))
            self.item = None
        if tag in {"p", "blockquote", "li", "h2", "h3"}:
            self.lines.append("\n")

    def handle_data(self, data):
        self.lines.append(data)
        if self.heading:
            self.heading_text.append(data)
        if self.item is not None:
            self.item.append(data)


def clock(raw):
    raw = re.sub(r"\s+", "", raw.lower()).replace(".", ":")
    fmt = "%I:%M%p" if ":" in raw else "%I%p"
    return datetime.strptime(raw, fmt).strftime("%H:%M")


def parse_slots(html):
    page = Article()
    page.feed(html)
    return slots_from(page)


def slots_from(page):
    body = "".join(page.lines)
    marker = re.search(r"FPL press conferences", body, re.I) or re.search(r"press conference times", body, re.I)
    if not marker:
        return []
    section = body[marker.end():][:4000]
    slots = {}
    for line in section.splitlines():
        match = re.match(rf"^[^\w\n]*({TIME})\s*[-–—]\s*(.+)", line.strip(), re.I)
        if match:
            names = re.split(r"https?://|pic\.twitter\.com", match[2])[0].strip()
            for name in re.split(r"\s*[,·/&]\s*|\s+and\s+", names):
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
    deadline_day = deadline.astimezone(UK).date()
    for link in dict.fromkeys(urljoin(SCOUT, href).split("#")[0] for href in page.links):
        url = urlsplit(link)
        match = re.fullmatch(rf"/(\d{{4}})/(\d{{2}})/(\d{{2}})/fpl-gameweek-{gw}-team-news-[\w-]*updates[\w-]*/?", url.path)
        if url.hostname != "www.fantasyfootballscout.co.uk" or not match or url.query:
            continue
        try:
            day = date(*map(int, match.groups()))
        except ValueError:
            continue
        if not deadline_day - timedelta(days=5) <= day <= deadline_day:
            continue
        try:
            article = requests.get(link, timeout=8)
            article.raise_for_status()
        except requests.RequestException as exc:
            print(f"Press source skipped: {type(exc).__name__}")
            continue
        page = Article()
        page.feed(article.text)
        slots = slots_from(page)
        if page.title and not re.search(rf"\bGameweek {gw}\b", page.title, re.I):
            continue
        if not slots and not page.summary:
            continue
        previous = days.get(str(day))
        if previous is None or (len(slots), len(page.summary)) > (len(previous["slots"]), len(previous["summary"])):
            days[str(day)] = {"url": link, "slots": slots, "summary": page.summary}
    return days


def conference_times(days, deadline):
    """Use the latest listed time for each manager, through the official deadline."""
    times = {}
    for day, source in sorted(days.items()):
        for time, manager in source["slots"]:
            at = datetime.fromisoformat(f"{day}T{time}").replace(tzinfo=UK)
            key = "".join(char for char in normalize("NFKD", manager.casefold()) if char.isalnum())
            times[key] = max(times.get(key, at), at)
    return sorted(at for at in times.values() if at < deadline)
