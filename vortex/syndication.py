"""Shared Telegram/Discord delivery with independent, durable receipts.

No network calls occur unless a caller explicitly enables the shared publisher.
Existing Telegram HTML/photo rendering is delegated to TelegramClient.
"""
from __future__ import annotations

import json
import os
import time
import fcntl
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests


class DeliveryRejected(RuntimeError):
    """Confirmed rejection: no message was accepted; retry is safe."""


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

    def send_album(self, images, caption):
        from contextlib import ExitStack
        from .publishing_window import assert_allowed
        assert_allowed()
        payload={'username':'FPL VORTEX','content':caption,'allowed_mentions':{'parse':[]}}
        try:
            with ExitStack() as stack:
                files=[(f'files[{i}]',(path.name,stack.enter_context(path.open('rb')),'image/png')) for i,path in enumerate(images)]
                response=self.session.post(self.url,params={'wait':'true'},timeout=60,
                                           data={'payload_json':json.dumps(payload)},files=files)
            if 400<=response.status_code<500:raise DeliveryRejected('Discord rejected album delivery')
            if not 200<=response.status_code<300:raise RuntimeError('Discord album acceptance is uncertain')
            receipt=response.json()
            if not receipt.get('id') or len(receipt.get('attachments',[]))!=len(images):
                raise RuntimeError('Discord album did not confirm every attachment')
            return str(receipt['id'])
        except (requests.RequestException,ValueError):
            raise RuntimeError('Discord album network/JSON failure; receipt not confirmed') from None


@contextmanager
def _receipt_lock(path: Path):
    """Lock journal readers/writers on the same runner, without changing jobs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".delivery.lock")
    with lock_path.open("a+b") as gate:
        fcntl.flock(gate.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(gate.fileno(), fcntl.LOCK_UN)


def _caption_digest(caption: str) -> str:
    return hashlib.sha256(" ".join(caption.split()).casefold().encode("utf-8")).hexdigest()


def publish_shared(post: NewsPost, journal_path: Path, telegram: Any,
                   discord: DiscordWebhookClient | Any,
                   *, send_telegram: bool = True, send_discord: bool = True,
                   now_iso: str = "") -> dict[str, Any]:
    with _receipt_lock(journal_path):
        return _publish_shared_locked(post, journal_path, telegram, discord,
                                      send_telegram=send_telegram,
                                      send_discord=send_discord, now_iso=now_iso)


def _publish_shared_locked(post: NewsPost, journal_path: Path, telegram: Any,
                           discord: DiscordWebhookClient | Any,
                           *, send_telegram: bool = True, send_discord: bool = True,
                           now_iso: str = "") -> dict[str, Any]:
    """Checkpoint platform receipts; fence uncertain Telegram uploads.

    A Telegram read timeout does not prove a missing message. The persisted
    telegram_send_pending fence prevents a duplicate on later scheduled runs.
    Confirmed 4xx rejections and ordinary stub failures remain retryable.
    """
    if not post.identity or not post.caption.strip():
        raise ValueError("Missing immutable identity or content")
    journal = load_journal(journal_path)
    entry = dict(journal.get(post.identity, {}))
    digest = _caption_digest(post.caption)
    # A semantic version change or another runner route cannot make an exact
    # same-caption delivery new. Copy only CONFIRMED per-platform receipts.
    for prior_id, prior in journal.items():
        if prior_id == post.identity or not isinstance(prior, dict):
            continue
        if prior.get("caption_sha256") != digest:
            continue
        if prior.get("delivered"):
            entry["delivered"] = True
            entry["telegram_message_id"] = prior.get("telegram_message_id")
        if prior.get("discord_delivered"):
            entry["discord_delivered"] = True
            entry["discord_message_id"] = prior.get("discord_message_id")
        if prior.get("telegram_send_pending"):
            entry["telegram_send_pending"] = True
        if prior.get("discord_send_pending"):
            entry["discord_send_pending"] = True
    entry["caption_sha256"] = digest
    errors: list[str] = []
    for platform, enabled in (("telegram", send_telegram), ("discord", send_discord)):
        if not enabled:
            continue
        already = bool(entry.get("delivered")) if platform == "telegram" else bool(entry.get("discord_delivered"))
        if already:
            continue
        if (platform == "telegram" and entry.get("telegram_send_pending")) or (
                platform == "discord" and entry.get("discord_send_pending")):
            # No Telegram Bot API method can query bot-authored chat history by
            # immutable post identity. Manual receipt reconciliation is needed.
            errors.append(platform + "-acceptance-uncertain; manual reconciliation required")
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
                entry.pop("telegram_send_pending", None)
                entry.pop("telegram_uncertain_at", None)
            else:
                message_id = discord.send(post)
                entry.update({"discord_delivered": True, "discord_message_id": str(message_id)})
                entry.pop("discord_send_pending", None)
        except (RuntimeError, ValueError, OSError, requests.RequestException) as exc:
            # A failed destination must not block the other destination. Do not
            # include external exception messages (which can include secrets).
            from .telegram import TelegramDeliveryError
            if isinstance(exc, TelegramDeliveryError):
                print(str(exc))
                if platform == "telegram" and getattr(exc, "delivery_uncertain", False):
                    # Durable fence: preserve accepted Discord receipt and avoid replay.
                    entry["telegram_send_pending"] = True
                    entry["telegram_uncertain_at"] = now_iso
                    journal[post.identity] = entry
                    save_journal(journal_path, journal)
            if platform == "discord" and isinstance(exc, requests.RequestException):
                # Discord 5xx/timeout may still have accepted the original.
                # Confirmed 4xx rejection is handled by the transport class.
                entry["discord_send_pending"] = True
                journal[post.identity] = entry
                save_journal(journal_path, journal)
            errors.append(f"{platform} {type(exc).__name__}")
            continue
        entry.update({"timestamp": now_iso, "gameweek": post.gameweek,
                      "source": post.source, "source_url": post.source_url})
        journal[post.identity] = entry
        save_journal(journal_path, journal)
    if errors:
        raise RuntimeError("Partial delivery; retained successful receipts: " + ", ".join(errors))
    # Also record a skipped duplicate identity without sending a second copy.
    if journal.get(post.identity) != entry:
        journal[post.identity] = entry
        save_journal(journal_path, journal)
    return entry


def publish_album(identity,images,caption,journal_path,telegram,discord,now_iso=''):
    with _receipt_lock(journal_path):
        return _publish_album_locked(identity,images,caption,journal_path,telegram,discord,now_iso)


def _publish_album_locked(identity,images,caption,journal_path,telegram,discord,now_iso):
    journal=load_journal(journal_path);errors=[]
    digest=_caption_digest(caption)
    keys=[f'{identity}:page{i+1}' for i in range(len(images))]
    rows=[dict(journal.get(key,{})) for key in keys]
    if not any(k in journal for k in keys):
        for key, old in journal.items():
            if key in keys or not isinstance(old,dict):
                continue
            if old.get("album_caption_sha256")==digest and (
                    old.get("delivered") or old.get("discord_delivered") or
                    old.get("telegram_album_pending") or old.get("discord_album_pending")):
                raise RuntimeError("Equivalent album already published/pending; refusing duplicate")
    for platform in ('telegram','discord'):
        flag='delivered' if platform=='telegram' else 'discord_delivered'
        if all(row.get(flag) for row in rows):continue
        if any(row.get(flag) for row in rows):
            raise RuntimeError('Legacy partial page group cannot be replayed as a new album')
        pending=platform+'_album_pending'
        if any(row.get(pending) for row in rows):
            errors.append(platform+' acceptance uncertain; reconcile before retry')
            continue
        # Persist before the external call: even process termination must not
        # silently replay an album whose receipt may have been lost.
        for key,row in zip(keys,rows):
            row[pending]=True;row['album_caption_sha256']=digest;journal[key]=row
        save_journal(journal_path,journal)
        try:
            ids=telegram.send_album(images,caption) if platform=='telegram' else [discord.send_album(images,caption)]*len(images)
            if len(ids)!=len(images):raise RuntimeError('Album receipt count mismatch')
            for key,row,message_id in zip(keys,rows,ids):
                row[flag]=True
                row.pop(pending,None)
                row['telegram_message_id' if platform=='telegram' else 'discord_message_id']=message_id
                row['timestamp']=now_iso;row['caption_once_album']=True
                row['album_caption_sha256']=digest;journal[key]=row
            save_journal(journal_path,journal)
        except (RuntimeError,ValueError,OSError,requests.RequestException) as exc:
            if isinstance(exc,DeliveryRejected) or getattr(exc,'confirmed_rejection',False):
                for key,row in zip(keys,rows):
                    row.pop(pending,None);journal[key]=row
                save_journal(journal_path,journal)
            errors.append(platform+' '+type(exc).__name__)
    if errors:raise RuntimeError('Partial delivery; retained album receipts: '+', '.join(errors))
    return rows
