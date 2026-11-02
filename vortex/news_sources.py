"""Verified official FPL changes plus attributed RSS headlines from existing X feeds.

This module does NOT treat RSS/Google News titles as confirmed manager quotes.
It never estimates injuries, odds, probabilities or price-change likelihoods.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from .fpl import FplSnapshot
from .syndication import NewsPost

X_FEED_REGISTRY = os.getenv(
    "NEWS_FEED_REGISTRY_URL",
    "https://raw.githubusercontent.com/mukundacity-glitch/Vortexnews-bot-Xpost/main/config/feeds.json",
)
MAX_AGE = timedelta(hours=8)
# Deny arbitrary endpoints if a feed registry is altered; extend through an
# explicit reviewed GitHub variable, never from arbitrary RSS metadata.
DEFAULT_FEED_HOSTS = frozenset({
    "news.google.com", "www.fotmob.com", "feeds.bbci.co.uk",
    "www.transfermarkt.com", "www.skysports.com", "www.theguardian.com",
    "www.espn.com",
})
FPL_NEWS_FIELDS = ("status", "chance_of_playing_next_round",
                   "chance_of_playing_this_round", "news")


def _identity(kind: str, *parts: Any) -> str:
    clean = "\x1f".join(str(p).strip().casefold() for p in parts)
    return kind + ":" + hashlib.sha256(clean.encode("utf-8")).hexdigest()[:24]


def _tags(category: str, gw: int, team: str = "") -> str:
    """Hashtags are derived from live event attributes and configurable bases."""
    seeds = os.getenv("NEWS_BASE_HASHTAGS", "FPL,FPLVortex").split(",")
    topic = re.sub(r"[^A-Za-z0-9]", "", category.title()) or "PremierLeague"
    club = re.sub(r"[^A-Za-z0-9]", "", team) if team else f"GW{gw}"
    tags = [re.sub(r"[^A-Za-z0-9]", "", item) for item in [*seeds, topic, club]]
    tags = [x for x in dict.fromkeys(tags) if x]
    while len(tags) < 4:
        tags.append(f"GW{gw}" if f"GW{gw}" not in tags else "PremierLeague")
    return " ".join("#" + tag for tag in tags[:4])


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", str(text or ""))).strip()


def _visual_fields(snapshot: FplSnapshot, player: dict[str, Any]) -> dict[str, Any]:
    # Official FPL identifiers; do not invent likenesses, club badges or transfers.
    return {
        "player_name": snapshot.name(player),
        "team_name": snapshot.team(player),
        "photo_code": snapshot.photo_code(player),
        "club_code": snapshot.team_code(player),
    }


def _headline_player(title: str, snapshot: FplSnapshot) -> dict[str, Any] | None:
    """Require a uniquely matched official player before making a portrait graphic."""
    words = " " + re.sub(r"[^a-z0-9 ]", " ", title.casefold()).strip() + " "
    words = re.sub(r"\\s+", " ", words)
    best: list[dict[str, Any]] = []
    lengths: list[int] = []
    for player in snapshot.players:
        full = f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()
        aliases = [full, str(player.get("web_name") or "")]
        match_len = 0
        for alias in aliases:
            needle = re.sub(r"\\s+", " ", re.sub(r"[^a-z0-9 ]", " ", alias.casefold())).strip()
            if len(needle) >= 5 and f" {needle} " in words:
                match_len = max(match_len, len(needle))
        if match_len:
            best.append(player)
            lengths.append(match_len)
    if not best:
        return None
    winning = max(lengths)
    selected = [player for player, length in zip(best, lengths) if length == winning]
    return selected[0] if len(selected) == 1 else None


def fpl_baseline(snapshot: FplSnapshot) -> dict[str, dict[str, Any]]:
    return {str(p["id"]): {k: p.get(k) for k in (*FPL_NEWS_FIELDS, "now_cost")}
            for p in snapshot.players if isinstance(p.get("id"), int)}


def collect_fpl_changes(snapshot: FplSnapshot, previous: dict[str, Any],
                        now: datetime) -> list[NewsPost]:
    """Compare snapshot against a real previous snapshot, not synthetic prices."""
    if not previous:
        return []  # cold start: baseline only, no fabricated 'new' changes
    gw = snapshot.gameweek()
    outputs: list[NewsPost] = []
    for p in snapshot.players:
        pid = str(p.get("id"))
        old = previous.get(pid)
        if not isinstance(old, dict) or not isinstance(p.get("id"), int):
            continue
        team = snapshot.team(p)
        name = snapshot.name(p)
        actual = {k: p.get(k) for k in FPL_NEWS_FIELDS}
        before = {k: old.get(k) for k in FPL_NEWS_FIELDS}
        if actual != before:
            status = str(p.get("status") or "unknown")
            label = {"i": "FPL injury flag", "s": "FPL suspension flag",
                     "d": "FPL doubtful flag", "a": "FPL available flag",
                     "u": "FPL unavailable flag"}.get(status, "FPL availability update")
            details = _clean(p.get("news"))
            # Do not interpret the FPL availability flag as a calibrated probability.
            text = f"{name} ({team}): {label}."
            if details:
                text += f" Official FPL note: {details[:260]}."
            chance = p.get("chance_of_playing_next_round")
            if chance is not None:
                text += f" FPL next-round flag: {chance}% (not a predicted start probability)."
            fixture = snapshot.fixtures_for_gameweek(p, gw)
            if fixture:
                text += " Next GW: " + ", ".join(f"{op} ({side})" for op, side, _, _ in fixture) + "."
            category = ("Suspension" if status == "s" else "Availability")
            title = f"GW{gw} • {label.upper()} — {name}"
            caption = f"{title}\n{text}\nSource: Official Fantasy Premier League, {now:%Y-%m-%d %H:%M} UTC\n{_tags(category, gw, team)}"
            outputs.append(NewsPost(
                identity=_identity("availability", pid, *(actual[k] for k in FPL_NEWS_FIELDS)),
                title=title, caption=caption, gameweek=gw, source="Official FPL",
                source_url="https://fantasy.premierleague.com/",
                **_visual_fields(snapshot, p),
            ))
        old_cost, new_cost = old.get("now_cost"), p.get("now_cost")
        if type(old_cost) is int and type(new_cost) is int and old_cost != new_cost:
            if not 20 <= old_cost <= 250 or not 20 <= new_cost <= 250:
                continue
            direction = "RISE" if new_cost > old_cost else "FALL"
            title = f"GW{gw} • CONFIRMED PRICE {direction} — {name}"
            text = f"{name} ({team}) officially changed from £{old_cost / 10:.1f}m to £{new_cost / 10:.1f}m in the FPL snapshots."
            caption = f"{title}\n{text}\nSource: Official FPL snapshots; confirmed at {now:%Y-%m-%d %H:%M} UTC\n{_tags('PriceChange', gw, team)}"
            outputs.append(NewsPost(
                identity=_identity("price", pid, old_cost, new_cost),
                title=title, caption=caption, gameweek=gw, source="Official FPL",
                source_url="https://fantasy.premierleague.com/",
                **_visual_fields(snapshot, p),
            ))
    return outputs


def _link_clean(link: str) -> str:
    parts = urlsplit(link.strip())
    filtered = [(k, v) for k, v in parse_qsl(parts.query)
                if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                       parts.path.rstrip("/"), urlencode(filtered), ""))


def _parse_date(text: str) -> datetime | None:
    try:
        result = parsedate_to_datetime(text)
        if result.tzinfo:
            return result.astimezone(timezone.utc)
    except (ValueError, TypeError, IndexError):
        pass
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if result.tzinfo:
            return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    return None


def _feed_items(xml: bytes) -> list[tuple[str, str, datetime | None]]:
    """RSS 2.0 and Atom support. Reject XML DTDs / entity definitions."""
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper() or len(xml) > 2_000_000:
        return []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    result: list[tuple[str, str, datetime | None]] = []
    for node in root.findall(".//item") + root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        title = _clean(node.findtext("title") or node.findtext("{http://www.w3.org/2005/Atom}title"))
        link = _clean(node.findtext("link"))
        if not link:
            atom_link = node.find("{http://www.w3.org/2005/Atom}link")
            if atom_link is not None:
                link = str(atom_link.attrib.get("href") or "")
        published = _parse_date(_clean(node.findtext("pubDate") or
            node.findtext("{http://www.w3.org/2005/Atom}published") or
            node.findtext("{http://www.w3.org/2005/Atom}updated")))
        if title and urlsplit(link).scheme in {"https", "http"}:
            result.append((title, _link_clean(link), published))
    return result


def _topic(title: str) -> str | None:
    lower = title.casefold()
    topics = {
        "PressConference": ("press conference", "manager reaction", "team news", "press briefing"),
        "Injury": ("injury", "injured", "ruled out", "fitness", "return to training"),
        "Suspension": ("suspension", "suspended", "banned", "red card"),
        "Transfer": ("signs", "signed", "transfer", "joins", "joined", "loan deal", "new contract"),
        "TeamNews": ("line-up", "lineup", "selection", "starting xi", "squad update"),
    }
    return next((k for k, words in topics.items() if any(w in lower for w in words)), None)


def _team_matches(title: str, snapshot: FplSnapshot) -> bool:
    lower = re.sub(r"[^a-z0-9 ]", " ", title.lower())
    lower = " " + re.sub(r"\s+", " ", lower).strip() + " "
    for t in snapshot.teams.values():
        variants = [str(t.get("name") or ""), str(t.get("short_name") or "")]
        for variant in variants:
            norm = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", variant.lower())).strip()
            if len(norm) >= 4 and f" {norm} " in lower:
                return True
    return False


def collect_reported_headlines(snapshot: FplSnapshot, now: datetime,
                               session: requests.Session | None = None,
                               registry: dict[str, Any] | None = None) -> list[NewsPost]:
    """Source-identified headlines, NEVER silently promoted into confirmed facts.

    The existing X source registry is reused; X's verification gates and social
    posts are not imported or falsely represented as already validated here.
    """
    client = session or requests.Session()
    if registry is None:
        try:
            result = client.get(X_FEED_REGISTRY, timeout=12)
            result.raise_for_status()
            registry = result.json()
        except (requests.RequestException, ValueError):
            return []  # fail closed; official FPL changes still work
    feeds = registry.get("feeds", []) if isinstance(registry, dict) else []
    if not isinstance(feeds, list):
        return []
    gw = snapshot.gameweek()
    found: list[NewsPost] = []
    approved_hosts = DEFAULT_FEED_HOSTS | frozenset(
        part.strip().lower() for part in os.getenv("NEWS_EXTRA_FEED_HOSTS", "").split(",") if part.strip()
    )
    for feed in feeds[:40]:
        if not isinstance(feed, dict):
            continue
        feed_url = str(feed.get("url", ""))
        parsed = urlsplit(feed_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in approved_hosts:
            continue
        try:
            response = client.get(feed["url"], timeout=8, headers={"User-Agent": "FPL-VORTEX-News/1.0"})
            response.raise_for_status()
            entries = _feed_items(response.content)
        except requests.RequestException:
            continue
        source = str(feed.get("source_hint") or feed.get("id") or "news feed")
        for title, link, published in entries[:min(10, max(1, int(feed.get("max_entries") or 10)))]:
            if not published or not (timedelta(0) <= now - published <= MAX_AGE):
                continue
            category = _topic(title)
            if category is None or not _team_matches(title, snapshot):
                continue
            # Mandatory photo + authentic crest: match exactly one FPL player.
            # Do not pretend a club/manager-only story has a player portrait.
            player = _headline_player(title, snapshot)
            if player is None:
                continue
            headline = f"GW{gw} • {category.upper()} WATCH"
            body = f"Reported headline: {title}\nFeed: {source} • {published:%Y-%m-%d %H:%M} UTC\n{link}"
            caption = f"{headline}\n{body}\nReport only; details not independently confirmed.\n{_tags(category, gw)}"
            found.append(NewsPost(
                identity=_identity("rss", _link_clean(link)),
                title=headline, caption=caption, gameweek=gw, source=source, source_url=link,
                **_visual_fields(snapshot, player),
            ))
    # Cross-feed overlap: identical URL, or very similar reported headlines.
    # Keep materially different updates, even about the same club/player.
    selected: list[NewsPost] = []
    seen_ids: set[str] = set()
    tokens: list[set[str]] = []
    noise = {"latest", "news", "report", "reports", "premier", "league",
             "football", "update", "updates", "club", "could", "after",
             "from", "with", "about", "says", "said", "team"}
    for post in found:
        if post.identity in seen_ids:
            continue
        reported = post.caption.partition("Reported headline: ")[2].partition("\n")[0]
        words = {w for w in re.findall(r"[a-z]{4,}", reported.casefold()) if w not in noise}
        near_repeat = any(
            bool(words and prior) and
            len(words & prior) / len(words | prior) >= 0.75
            for prior in tokens
        )
        if near_repeat:
            continue
        selected.append(post)
        tokens.append(words)
        seen_ids.add(post.identity)
    return selected
