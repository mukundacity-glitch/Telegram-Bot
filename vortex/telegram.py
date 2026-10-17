"""Telegram Bot API delivery; tokens never logged."""
from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any

import requests


class TelegramClient:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN secret is not configured")
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def _post(self, method: str, data: dict[str, Any], files: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = requests.post(f"{self.base_url}/{method}", data=data, files=files, timeout=60)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise RuntimeError(f"Telegram {method} network or JSON failure ({type(error).__name__})") from None
        if not isinstance(payload, dict) or not payload.get("ok"):
            description = str(payload.get("description", "unknown API error")) if isinstance(payload, dict) else "invalid response"
            raise RuntimeError(f"Telegram {method} rejected: {description[:180]}")
        return payload

    def get_bot_username(self) -> str:
        try:
            response = requests.get(f"{self.base_url}/getMe", timeout=25)
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

    def send_png(self, image: Path, caption: str, title: str, gw: int) -> int:
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