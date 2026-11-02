"""Telegram Bot API photo-edit contract for one player/topic/GW."""
from pathlib import Path

from PIL import Image
import pytest

from vortex.telegram import TelegramClient


def test_edit_media_updates_confirmed_message_without_sending_new_post(tmp_path, monkeypatch):
    original = 725
    filename = tmp_path / "updated.png"
    Image.new("RGB", (1920, 1080), (2, 20, 50)).save(filename)
    client = TelegramClient(token="unit-test-placeholder", chat_id="-100123")
    calls = []
    def fake_post(method, data, files=None):
        calls.append((method, data, files))
        return {"ok": True, "result": {"message_id": original}}
    monkeypatch.setattr(client, "_post", fake_post)
    caption = ("UPDATED • GW10 availability\nExample injury flag\n"
               "Next: CHE (H)\nMONITOR before deadline\n"
               "#FPL #GW10 #FPLVortex #TeamNews")
    assert client.edit_shared_png(filename, caption, original) == original
    assert len(calls) == 1 and calls[0][0] == "editMessageMedia"
    assert calls[0][1]["message_id"] == original
    assert "attach://edited_photo" in calls[0][1]["media"]
    assert "edited_photo" in calls[0][2]


def test_mismatched_edit_receipt_must_not_be_treated_as_delivered(tmp_path, monkeypatch):
    filename = tmp_path / "updated.png"
    Image.new("RGB", (1920, 1080)).save(filename)
    client = TelegramClient(token="unit-test-placeholder", chat_id="-100123")
    monkeypatch.setattr(client, "_post",
                        lambda *args, **kwargs: {"ok": True, "result": {"message_id": 999}})
    with pytest.raises(RuntimeError, match="did not confirm"):
        client.edit_shared_png(
            filename,
            "a\nb\nc\nd\n#FPL #GW10 #FPLVortex #TeamNews", 725)
