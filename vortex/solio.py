"""Match fresh public Solio Analytics team forecasts to official FPL fixtures.

Solio Analytics publishes market-INFORMED model estimates, not raw bookmaker
quotes. Its public HTML endpoint includes the ten best attacking fixtures and
ten best clean-sheet teams. Their projected goals-for/against can fill the
opposing side of a confirmed SINGLE-fixture gameweek; clean sheet odds not
explicitly published are Poisson-implied from those projected goals.

Never assign aggregate team-GW forecasts to individual double-GW fixtures.
Never use FPL fixture difficulty to invent an expected goal or CS percentage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from math import exp, isfinite
import re
from typing import Any

import requests

from .fpl import FplSnapshot
from .market_odds import canonical

URL = "https://fpl.solioanalytics.com/api/data/latest"
MAX_AGE = timedelta(hours=8)


class _Tables(HTMLParser):
    """Extract public team tables without needing a browser or third-party parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.heading: str | None = None
        self.heading_words: list[str] = []
        self.section: str | None = None
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cell_words: list[str] = []
        self.row: list[str] = []
        self.tables: dict[str, list[list[str]]] = {"attack": [], "clean": []}
        self.words: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3"}:
            self.heading, self.heading_words = tag, []
        elif tag == "table" and self.section in self.tables:
            self.in_table = True
        elif tag == "tr" and self.in_table:
            self.in_row, self.row = True, []
        elif tag in {"td", "th"} and self.in_row:
            self.in_cell, self.cell_words = True, []

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        self.words.append(data.strip())
        if self.heading:
            self.heading_words.append(data.strip())
        if self.in_cell:
            self.cell_words.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag == self.heading:
            title = " ".join(self.heading_words).casefold()
            self.section = (
                "attack" if "best attacking fixtures" in title
                else "clean" if "best clean sheet odds" in title
                else None
            )
            self.heading = None
        elif tag in {"th", "td"} and self.in_cell:
            self.row.append(" ".join(self.cell_words).strip())
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.section in self.tables and self.row:
                self.tables[self.section].append(self.row)
            self.in_row = False
        elif tag == "table":
            self.in_table = False


def _club(value: str) -> str:
    name = canonical(value)
    return {"spurs": "tottenham", "brighton hove albion": "brighton"}.get(name, name)


def _decimal(value: str, *, upper: float = 5.5) -> float | None:
    text = str(value).strip().replace(",", "")
    if re.fullmatch(r"\d{1,2}(?:\.\d{1,3})?", text) is None:
        return None
    result = float(text)
    return result if isfinite(result) and 0 <= result <= upper else None


def _timestamp(words: str) -> datetime | None:
    iso = re.search(r"Generated at\s+(\d{4}-\d\d-\d\dT[\d:.]+Z)", words, re.I)
    if iso:
        try:
            return datetime.fromisoformat(iso.group(1).replace("Z", "+00:00"))
        except ValueError:
            pass
    plain = re.search(r"Generated\s+(\d\d\.\d\d\.\d\d\s+\d\d:\d\d)\s+UTC", words, re.I)
    if plain:
        try:
            return datetime.strptime(plain.group(1), "%d.%m.%y %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _rows(table: list[list[str]], kind: str) -> list[dict[str, Any]]:
    if not table:
        return []
    header = [re.sub(r"\s+", " ", x).strip().casefold() for x in table[0]]
    try:
        team_ix = header.index("team")
        fixture_ix = header.index("fixtures")
        against_ix = next(i for i, x in enumerate(header) if "proj." in x and "against" in x)
        for_ix = (next(i for i, x in enumerate(header) if "proj." in x and "for" in x)
                  if kind == "attack" else None)
        cs_ix = (next(i for i, x in enumerate(header) if x.replace(" ", "") in {"cs%", "cs%."})
                 if kind == "clean" else None)
    except (StopIteration, ValueError):
        return []
    results: list[dict[str, Any]] = []
    for cells in table[1:]:
        needed = [team_ix, fixture_ix, against_ix] + ([for_ix] if for_ix is not None else []) + ([cs_ix] if cs_ix is not None else [])
        if len(cells) <= max(needed):
            continue
        against = _decimal(cells[against_ix])
        scored = _decimal(cells[for_ix]) if for_ix is not None else None
        cs = (_decimal(cells[cs_ix].removesuffix("%"), upper=100)
              if cs_ix is not None and cells[cs_ix].strip().endswith("%") else None)
        if against is None or (kind == "attack" and scored is None) or (kind == "clean" and cs is None):
            continue
        results.append({"team": _club(cells[team_ix]), "fixture": cells[fixture_ix].strip(),
                        "for": scored, "against": against, "cs": cs})
    return results


def _compatible_row(row: dict[str, Any], team: int, fixture: dict[str, Any],
                    snapshot: FplSnapshot) -> bool:
    opponent = fixture["team_a"] if team == fixture["team_h"] else fixture["team_h"]
    opponent_short = snapshot.teams.get(opponent, {}).get("short_name", "")
    label = re.fullmatch(r"(vs|@)\s+([A-Za-z]{2,5})", row["fixture"], re.I)
    if not label or label.group(2).upper() != str(opponent_short).upper():
        return False
    at_home = team == fixture["team_h"]
    return (label.group(1).lower() == "vs") == at_home


def _consistent_put(target: dict[int, dict[str, float]], team: int, label: str,
                    number: float) -> bool:
    existing = target.setdefault(team, {}).get(label)
    if existing is not None and abs(existing - number) > 0.02:
        return False
    target[team][label] = number
    return True


def parse_public_html(snapshot: FplSnapshot, fixtures: list[dict[str, Any]],
                      html: str, now: datetime | None = None) -> dict[int, dict[str, Any]]:
    """Return verified per-fixture Solio model values, keyed by FPL fixture ID."""
    now = now or snapshot.fetched_at
    if now.tzinfo is None:
        return {}
    parsed = _Tables()
    try:
        parsed.feed(html)
    except (ValueError, TypeError):
        return {}
    words = " ".join(parsed.words)
    title = re.search(r"\bFPL Gameweek\s+(\d+)\b", words, re.I)
    stamp = _timestamp(words)
    if not title or int(title.group(1)) != snapshot.gameweek() or stamp is None:
        return {}
    age = now.astimezone(timezone.utc) - stamp.astimezone(timezone.utc)
    if not -timedelta(minutes=5) <= age <= MAX_AGE:
        return {}

    # Public team data are GAMEWEEK TOTALS, so only the single-fixture case is
    # mathematically identifiable. Never split DGW aggregates by guesswork.
    fixture_by_team: dict[int, dict[str, Any]] = {}
    for f in fixtures:
        if not isinstance(f.get("id"), int) or not isinstance(f.get("team_h"), int) or not isinstance(f.get("team_a"), int):
            return {}
        for team in (f["team_h"], f["team_a"]):
            if team in fixture_by_team:
                return {}
            fixture_by_team[team] = f

    official_by_name = {_club(t.get("name", "")): ident for ident, t in snapshot.teams.items()}
    values: dict[int, dict[str, float]] = {}
    bad: set[int] = set()
    valid_count = 0
    for kind in ("attack", "clean"):
        for row in _rows(parsed.tables[kind], kind):
            team = official_by_name.get(row["team"])
            if team is None or team not in fixture_by_team:
                continue
            fixture = fixture_by_team[team]
            if not _compatible_row(row, team, fixture, snapshot):
                bad.add(fixture["id"])
                continue
            valid_count += 1
            for key in ("for", "against", "cs"):
                number = row.get(key)
                if number is not None and not _consistent_put(values, team, key, number):
                    bad.add(fixture["id"])
    if not valid_count:
        return {}

    # Each side's projected goals for = the opponent's projected goals against.
    # This is the same Solio fixture estimate viewed from the other team's side.
    output: dict[int, dict[str, Any]] = {}
    for f in fixtures:
        fid, h, a = f["id"], f["team_h"], f["team_a"]
        if fid in bad:
            continue
        hv, av = values.get(h, {}), values.get(a, {})
        hg = hv.get("for", av.get("against"))
        ag = av.get("for", hv.get("against"))
        if hg is None or ag is None:
            continue
        if ((hv.get("for") is not None and av.get("against") is not None
             and abs(hv["for"] - av["against"]) > 0.03)
            or (av.get("for") is not None and hv.get("against") is not None
                and abs(av["for"] - hv["against"]) > 0.03)):
            continue
        # Explicit site CS% has priority; otherwise the source's projected
        # goals-conceded Poisson-equivalent P(0) is a DERIVED model statistic.
        hc = hv.get("cs", round(100 * exp(-ag)))
        ac = av.get("cs", round(100 * exp(-hg)))
        if abs(hc - round(100 * exp(-ag))) > 3 or abs(ac - round(100 * exp(-hg))) > 3:
            continue
        output[fid] = {
            "home_goals": round(hg, 2), "away_goals": round(ag, 2),
            "home_cs": round(hc), "away_cs": round(ac),
            "home_books": 0, "away_books": 0,
            "home_quote_utc": None, "away_quote_utc": None,
            "model_generated_utc": stamp.isoformat(),
            "source": "Solio Analytics · market-informed model (NOT live bookmaker odds)",
            "method": "Team projected goals, Solio CS% where public; other CS% = exp(-opponent goals)",
        }
    return output


def solio_match_projections(snapshot: FplSnapshot, fixtures: list[dict[str, Any]],
                            session: requests.Session | None = None) -> dict[int, dict[str, Any]]:
    """Public no-key fallback; returns empty on network, freshness, or schema errors."""
    if not fixtures:
        return {}
    try:
        response = (session or requests.Session()).get(
            URL, headers={"Accept": "text/html",
                          "User-Agent": "FPLVortex/1.0 public-data-attributed"},
            timeout=7,
        )
        response.raise_for_status()
        if not isinstance(response.text, str) or len(response.text) > 2_000_000:
            return {}
        return parse_public_html(snapshot, fixtures, response.text)
    except (requests.RequestException, ValueError, TypeError):
        return {}
