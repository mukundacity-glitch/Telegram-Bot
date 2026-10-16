"""Focused tests for Telegram bot identity and chat discovery."""
from __future__ import annotations

from typing import Any

import pytest

import vortex.bot as bot
from vortex.telegram import TelegramClient


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


def test_get_bot_username(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, timeout: int) -> FakeResponse:
        assert url.endswith("/getMe")
        assert timeout == 25
        return FakeResponse({"ok": True, "result": {"username": "FPLVortexDailyBot"}})

    monkeypatch.setattr("vortex.telegram.requests.get", fake_get)
    client = TelegramClient(token="unit-test-token")
    assert client.get_bot_username() == "FPLVortexDailyBot"


def test_get_bot_username_rejects_malformed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, timeout: int) -> FakeResponse:
        return FakeResponse([])

    monkeypatch.setattr("vortex.telegram.requests.get", fake_get)
    client = TelegramClient(token="unit-test-token")
    with pytest.raises(RuntimeError, match="valid bot username"):
        client.get_bot_username()


def test_discovery_rejects_wrong_bot(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class FakeClient:
        def get_bot_username(self) -> str:
            return "OtherBot"

        def discover_chats(self) -> list[dict[str, str]]:
            pytest.fail("Wrong bot must not query chats")

    monkeypatch.setattr(bot, "TelegramClient", FakeClient)
    assert bot.run("discover") == 1
    assert "WRONG BOT TOKEN" in capsys.readouterr().err


def test_discovery_finds_chat(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    class FakeClient:
        def get_bot_username(self) -> str:
            return "FPLVortexDailyBot"

        def discover_chats(self) -> list[dict[str, str]]:
            return [{"title": "Example", "type": "private", "id": "123456789"}]

    monkeypatch.setattr(bot, "TelegramClient", FakeClient)
    assert bot.run("discover") == 0
    output = capsys.readouterr().out
    assert "@FPLVortexDailyBot" in output
    assert "chat id 123456789" in output
