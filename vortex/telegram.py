"""Telegram Bot API delivery; tokens never logged."""
from __future__ import annotations

import html
import os
import time
from pathlib import Path
from typing import Any

import requests


class TelegramDeliveryError(RuntimeError):
    """Safe diagnostic code; never includes token, chat ID or API response."""


def rejection_code(status, payload):
    description = str(payload.get("description", "")).casefold() if isinstance(payload, dict) else ""
    for text, code in (("chat not found", "chat-not-found"),
                       ("bot was blocked", "bot-blocked"),
                       ("bot can't send messages to bots", "target-is-another-bot"),
                       ("not enough rights", "posting-permission-missing"),
                       ("not a member", "bot-not-in-target-chat"),
                       ("wrong file", "invalid-photo"),
                       ("caption is too long", "caption-too-long")):
        if text in description:
            return code
    return {401: "invalid-bot-token", 403: "target-access-denied", 429: "rate-limited"}.get(status, f"http-{status}")


class TelegramClient:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN secret is not configured")
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def _post(self, method: str, data: dict[str, Any], files: dict[str, Any] | None = None) -> dict[str, Any]:
        if method in ('sendPhoto', 'sendMessage', 'sendMediaGroup', 'editMessageMedia'):
            from .publishing_window import assert_allowed
            assert_allowed()
        try:
            for attempt in range(3):
                if files:
                    for part in files.values():
                        stream = part[1] if isinstance(part, tuple) else part
                        if hasattr(stream, "seek"):
                            stream.seek(0)
                response = requests.post(f"{self.base_url}/{method}", data=data, files=files, timeout=60)
                status = getattr(response, "status_code", 200)
                if status in (429, 500, 502, 503, 504) and attempt < 2:
                    try:
                        delay = float(response.json().get("parameters", {}).get("retry_after", 2 ** (attempt + 1)))
                    except (ValueError, TypeError, AttributeError):
                        delay = 2 ** (attempt + 1)
                    # Respect long rate limits by deferring to the next scheduled
                    # check, rather than retrying earlier than Telegram permits.
                    if delay > 30:
                        break
                    time.sleep(max(1, delay))
                    continue
                break
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError as error:
            # Never print response bodies or destination identifiers.
            status = error.response.status_code if error.response is not None else "unknown"
            try:
                detail = error.response.json() if error.response is not None else {}
            except ValueError:
                detail = {}
            raise TelegramDeliveryError(f"Telegram {method}: {rejection_code(status, detail)}") from None
        except (requests.RequestException, ValueError) as error:
            raise TelegramDeliveryError(f"Telegram {method} network or JSON failure ({type(error).__name__})") from None
        if not isinstance(payload, dict) or not payload.get("ok"):
            status = payload.get("error_code", "unknown") if isinstance(payload, dict) else "unknown"
            raise TelegramDeliveryError(f"Telegram {method}: {rejection_code(status, payload)}")
        return payload

    def verify_destination(self) -> None:
        """Read-only identity/destination checks, with no IDs in logs."""
        if self.get_bot_username().casefold() != "fplvortexdailybot":
            raise TelegramDeliveryError("Telegram preflight: wrong-bot-token")
        payload = self._post("getChat", {"chat_id": self.chat_id})
        chat = payload.get("result", {})
        if chat.get("username", "").casefold() == "fplvortexdailybot":
            raise TelegramDeliveryError("Telegram preflight: destination-is-bot-itself")
        print("Telegram preflight: bot identity and target chat verified")

    def get_bot_username(self) -> str:
        try:
            for attempt in range(3):
                response = requests.get(f"{self.base_url}/getMe", timeout=25)
                if getattr(response, "status_code", 200) in (500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                break
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError("Telegram getMe failed; verify TELEGRAM_BOT_TOKEN") from None
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        if not isinstance(payload, dict) or not payload.get("ok") or not isinstance(result, dict) or not result.get("username"):
            raise RuntimeError("Telegram getMe did not return a valid bot username")
        return str(result["username"])

    def discover_chats(self) -> list[dict[str, Any]]:
        try:
            response = requests.get(f"{self.base_url}/getUpdates", timeout=25)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError("Telegram getUpdates failed; confirm bot token and webhook settings") from None
        if not payload.get("ok"):
            raise RuntimeError("Telegram rejected getUpdates; disable an existing webhook if configured")
        chats: dict[str, dict[str, Any]] = {}
        for update in payload.get("result", []):
            message = update.get("message") or update.get("channel_post") or {}
            chat = message.get("chat", {}) if isinstance(message, dict) else {}
            if isinstance(chat, dict) and "id" in chat:
                chats[str(chat["id"])] = {"id": str(chat["id"]), "title": str(chat.get("title") or chat.get("first_name") or "Unknown"), "type": str(chat.get("type") or "unknown")}
        return list(chats.values())

    def send_text(self, text: str) -> int:
        if not self.chat_id:
            raise ValueError("TELEGRAM_CHAT_ID secret is not configured")
        payload = self._post("sendMessage", {"chat_id": self.chat_id, "text": text[:4000]})
        return int(payload["result"]["message_id"])

    def send_shared_png(self, image: Path, caption: str, title: str, gw: int) -> int:
        """Send exact copy-ready caption in Telegram; identical to Discord text.

        This is opt-in for the shared news system only. Legacy Telegram
        send_png remains unchanged until verified production cutover.
        """
        if not self.chat_id:
            raise ValueError("TELEGRAM_CHAT_ID secret is not configured")
        if not image.is_file() or image.stat().st_size < 500:
            raise ValueError("Shared PNG is missing or unexpectedly small")
        if not caption.strip() or len(caption) > 1024:
            raise ValueError("Shared Telegram caption must fit in 1024 characters")
        with image.open("rb") as source:
            data = self._post(
                "sendPhoto",
                {"chat_id": self.chat_id, "caption": caption},
                {"photo": (image.name, source, "image/png")},
            )
        return int(data["result"]["message_id"])

    def send_album(self, images, caption):
        import json
        from contextlib import ExitStack
        if not 2 <= len(images) <= 10 or len(caption)>1024:
            raise ValueError('Invalid shared album size/caption')
        with ExitStack() as stack:
            files={f'photo{i}':(path.name,stack.enter_context(path.open('rb')),'image/png') for i,path in enumerate(images)}
            media=[{'type':'photo','media':f'attach://photo{i}',**({'caption':caption} if i==0 else {})} for i in range(len(images))]
            result=self._post('sendMediaGroup',{'chat_id':self.chat_id,'media':json.dumps(media)},files)
        rows=result.get('result')
        if not isinstance(rows,list) or len(rows)!=len(images) or any(type(row.get('message_id')) is not int for row in rows):
            raise RuntimeError('Telegram album did not confirm every page receipt')
        return [row['message_id'] for row in rows]

    def edit_shared_png(self, image: Path, caption: str, message_id: int) -> int:
        """Update the EXISTING Telegram photo in place, never publish a repeat.

        Telegram editMessageMedia returns the edited Message for chat_id
        targets (True is for inline-message edits). Require actual matching
        message ID before recording any edit as confirmed.
        """
        import json
        if not self.chat_id or type(message_id) is not int or message_id <= 0:
            raise ValueError("Existing Telegram chat and post ID are required")
        if not image.is_file() or image.stat().st_size < 500:
            raise ValueError("Cannot edit Telegram news with missing image")
        if len(caption.splitlines()) != 5 or len(caption) > 1024:
            raise ValueError("Updated caption must be five Telegram-sized lines")
        media = {"type": "photo", "media": "attach://edited_photo",
                 "caption": caption}
        with image.open("rb") as source:
            payload = self._post(
                "editMessageMedia",
                {"chat_id": self.chat_id, "message_id": message_id,
                 "media": json.dumps(media, ensure_ascii=False)},
                {"edited_photo": (image.name, source, "image/png")},
            )
        msg = payload.get("result")
        if not isinstance(msg, dict) or msg.get("message_id") != message_id:
            raise RuntimeError("Telegram edit did not confirm the original post ID")
        return message_id

    def send_png(self, image: Path, caption: str, title: str, gw: int) -> int:
        # Finished production captions already contain the hook and hashtags.
        # Preserve their exact five lines on Telegram, as on Discord.
        if len(caption.splitlines()) == 5 and len([
                word for word in caption.split() if word.startswith("#")]) == 4:
            return self.send_shared_png(image, caption, title, gw)
        if not self.chat_id:
            raise ValueError("TELEGRAM_CHAT_ID secret is not configured")
        if not image.exists() or image.stat().st_size < 500:
            raise ValueError("Image file missing or unexpectedly small")
        lines = [line.strip() for line in caption.splitlines() if line.strip()]
        hashtags = lines[-1] if lines and lines[-1].startswith("#") else ""
        story = lines[:-1] if hashtags else lines
        icons = ("📣", "👤", "📊", "🎯", "💬")
        body = "\n".join(f"{icons[index % len(icons)]} {html.escape(line)}" for index, line in enumerate(story))
        header = f"🦁 <b>FPL VORTEX • GW{gw}</b>\n<b>{html.escape(title)}</b>"
        message = f"{header}\n\n{body}"
        if hashtags:
            message += f"\n\n{html.escape(hashtags)}"
        if len(message) > 1024:
            raise ValueError("Telegram photo caption exceeds 1024 characters")
        with image.open("rb") as file_handle:
            payload = self._post(
                "sendPhoto",
                {"chat_id": self.chat_id, "caption": message, "parse_mode": "HTML"},
                {"photo": (image.name, file_handle, "image/png")},
            )
        return int(payload["result"]["message_id"])
