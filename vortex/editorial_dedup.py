"""Durable semantic publication state across ET dates and backup runs.

Same topic + same verifiable facts => no post. A meaningful field change
creates a labeled revision. Exact same Telegram/Discord content version is
only acknowledged complete when both delivery receipts exist.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from typing import Any

from .publication_rules import semantic_fingerprint, publication_group


def evidence_summary(post: Any) -> dict[str, Any]:
    record = asdict(post)
    cards = []
    for row in record.get("cards", []):
        cards.append({
            "player": row.get("headline"),
            "team": row.get("team_code"),
            "metrics": row.get("metrics") or {},
            "fixtures": row.get("fixtures") or [],
        })
    data = {"kind": record.get("kind"), "gw": record.get("gw"),
            "players": cards}
    if record.get("fixtures"):
        data["fixtures"] = [
            {field: r.get(field) for field in ("id", "home_goals", "away_goals",
                                               "home_cs", "away_cs")}
            for r in record["fixtures"]
        ]
    if record.get("team_analysis"):
        data["team"] = record["team_analysis"].get("team")
        data["history"] = record["team_analysis"].get("history")
    if record.get("start_bench"):
        data["picks"] = [
            {k: p.get(k) for k in ("id", "advice", "price", "fdr", "form", "opponent")}
            for p in record["start_bench"]
        ]
    return data


def evidence_change_summary(old: dict[str, Any], new: dict[str, Any]) -> str:
    if not old:
        return "new evidence"
    changed = []
    for label in ("players", "fixtures", "team", "history", "picks"):
        if old.get(label) != new.get(label):
            changed.append({"players": "player stats", "fixtures": "fixture odds",
                            "team": "club selection", "history": "form history",
                            "picks": "start/bench ranks"}[label])
    return ", ".join(changed[:2]) or "verified new statistics"


def check_revision(history: dict[str, Any], post: Any,
                   deliveries: dict[str, dict[str, Any]],
                   delivery_key: str, dual: bool
                   ) -> tuple[str, Any, str, str, dict[str, Any], bool]:
    """Return group, post, stable delivery key, semantic version, evidence, skip."""
    group = publication_group(post)
    version = semantic_fingerprint(post)
    evidence = evidence_summary(post)
    old = history.get(group) if isinstance(history.get(group), dict) else None
    if old and old.get("version") == version:
        key = str(old.get("delivery_key") or delivery_key)
        receipt = deliveries.get(key, {})
        done = bool(receipt.get("delivered")) and (
            not dual or bool(receipt.get("discord_delivered")))
        return group, post, key, version, evidence, done
    if old and not old.get("confirmed", False):
        # Earlier partial failure: do not silently publish a new version while
        # the previous version has no matching receipt on both platforms.
        raise RuntimeError("An earlier topic revision is pending completion")
    if old:
        changed = evidence_change_summary(old.get("evidence", {}), evidence)
        if hasattr(post, "title"):
            post = replace(post, title="UPDATED • " + post.title)
        if hasattr(post, "caption"):
            caption = post.caption
            lines = caption.splitlines()
            if lines and lines[-1].startswith("#"):
                lines.insert(-1, f"UPDATED: {changed}.")
                maybe = "\n".join(lines)
                if len(maybe) <= 1024 and (len(maybe) < 280 or len(caption) >= 280):
                    post = replace(post, caption=maybe)
    return group, post, delivery_key, version, evidence, False


def revision_record(group: str, key: str, version: str,
                    evidence: dict[str, Any], receipt: dict[str, Any], dual: bool,
                    now_iso: str) -> dict[str, Any]:
    return {"group": group, "delivery_key": key, "version": version,
            "evidence": evidence,
            "confirmed": bool(receipt.get("delivered")) and (
                not dual or bool(receipt.get("discord_delivered"))),
            "timestamp": now_iso}
