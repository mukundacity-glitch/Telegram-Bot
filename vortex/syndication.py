"""Shared Telegram/Discord delivery with independent, durable receipts.

No network calls occur unless a caller explicitly enables the shared publisher.
Existing Telegram HTML/photo rendering is delegated to TelegramClient.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests


@dataclass(frozen=True)
class NewsPost:
    identity: str
    title: str
    caption: str
    gameweek: int
    image: Path | None = None
    source: str = ""
    source_url: str = ""
    player_name: str = ""
    team_name: str = ""
    photo_code: int | None = None
    club_code: int | None = None


def load_journal(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Cannot read delivery journal; refusing unsafe replay") from exc
    if not isinstance(raw, dict) or any(not isinstance(v, dict) for v in raw.values()):
        raise RuntimeError("Invalid delivery journal; refusing unsafe replay")
    return raw


def save_journal(path: Path, state: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


class DiscordWebhookClient:
    """Wait for a Discord message receipt. Never include webhook URLs in errors."""

    def __init__(self, webhook_url: str | None = None, session: requests.Session | None = None,
                 sleeper=time.sleep):
        self.url = webhook_url if webhook_url is not None else os.environ.get("DISCORD_WEBHOOK_URL", "")
        if not self.url or urlsplit(self.url).scheme != "https" or urlsplit(self.url).hostname not in {
            "discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"
        } or not urlsplit(self.url).path.startswith("/api/webhooks/"):
            raise ValueError("DISCORD_WEBHOOK_URL must be a configured Discord webhook secret")
        self.session = session or requests.Session()
        self.sleep = sleeper

    def _send(self, payload: dict[str, Any], file: Path | None) -> str:
        for attempt in range(4):
            try:
                args: dict[str, Any] = {
                    "params": {"wait": "true"}, "timeout": 35,
                }
                if file:
                    with file.open("rb") as stream:
                        response = self.session.post(
                            self.url, data={"payload_json": json.dumps(payload)},
                            files={"files[0]": (file.name, stream, "image/png")}, **args)
                else:
                    response = self.session.post(self.url, json=payload, **args)
                if response.status_code == 429:
                    delay = response.headers.get("Retry-After", "1")
                    try:
                        retry_seconds = min(10.0, max(0.5, float(delay)))
                    except ValueError:
                        retry_seconds = 2.0
                    if attempt < 3:
                        self.sleep(retry_seconds)
                        continue
                elif 500 <= response.status_code <= 599 and attempt < 3:
                    self.sleep(min(8, 2 ** attempt))
                    continue
                if not 200 <= response.status_code < 300:
                    raise RuntimeError(f"Discord rejected delivery (HTTP {response.status_code})")
                receipt = response.json()
                if not isinstance(receipt, dict) or not receipt.get("id"):
                    raise RuntimeError("Discord did not return a confirmed message ID")
                return str(receipt["id"])
            except requests.RequestException:
                if attempt < 3:
                    self.sleep(min(8, 2 ** attempt))
                    continue
                raise RuntimeError("Discord delivery network failure") from None
        raise RuntimeError("Discord rate limit persisted after bounded retries")

    def send(self, post: NewsPost) -> str:
        from .publishing_window import assert_allowed
        assert_allowed()
        content = post.caption
        if len(content) > 2000:
            raise ValueError("Discord content exceeds 2000 characters; no silent truncation")
        payload = {"username": "FPL VORTEX", "content": content,
                   "allowed_mentions": {"parse": []}}
        if post.image and (not post.image.is_file() or post.image.stat().st_size < 500):
            raise ValueError("Shared image missing or invalid")
        return self._send(payload, post.image)


def publish_shared(post: NewsPost, journal_path: Path, telegram: Any,
                   discord: DiscordWebhookClient | Any,
                   *, send_telegram: bool = True, send_discord: bool = True,
                   now_iso: str = "") -> dict[str, Any]:
    """Checkpoint *each* platform before attempting the next.

    An existing Telegram journal entry with delivered=true is respected.
    A Discord error does not erase the successful Telegram receipt. Retrying
    the same identity will only send to its unfinished destination.
    """
    if not post.identity or not post.caption.strip():
        raise ValueError("Missing immutable identity or content")
    journal = load_journal(journal_path)
    entry = dict(journal.get(post.identity, {}))
    errors: list[str] = []
    for platform, enabled in (("telegram", send_telegram), ("discord", send_discord)):
        if not enabled:
            continue
        already = bool(entry.get("delivered")) if platform == "telegram" else bool(entry.get("discord_delivered"))
        if already:
            continue
        try:
            if platform == "telegram":
                if post.image is None:
                    message_id = telegram.send_text(post.caption)
                else:
                    # Preserve legacy formatting for single-platform calls,
                    # but new unified delivery uses exact copy-ready captions.
                    send = getattr(telegram, "send_shared_png", telegram.send_png)
                    message_id = send(post.image, post.caption, post.title, post.gameweek)
                entry.update({"delivered": True, "telegram_message_id": message_id})
            else:
                message_id = discord.send(post)
                entry.update({"discord_delivered": True, "discord_message_id": str(message_id)})
        except (RuntimeError, ValueError, OSError, requests.RequestException) as exc:
            # A failed destination must not block the other destination. Do not
            # include external exception messages (which can include secrets).
            from .telegram import TelegramDeliveryError
            if isinstance(exc, TelegramDeliveryError):
                print(str(exc))
            errors.append(f"{platform} {type(exc).__name__}")
            continue
        entry.update({"timestamp": now_iso, "gameweek": post.gameweek,
                      "source": post.source, "source_url": post.source_url})
        journal[post.identity] = entry
        save_journal(journal_path, journal)
    if errors:
        raise RuntimeError("Partial delivery; retained successful receipts: " + ", ".join(errors))
    return entry
