"""Do not permit text-only news: validate the exact mandatory image path."""
from pathlib import Path

import pytest
from PIL import Image

import vortex.news_graphics as graphics
from vortex.syndication import NewsPost


def _post():
    return NewsPost(
        identity="availability:123", title="GW10 • VERIFIED AVAILABILITY UPDATE",
        caption="GW10 • VERIFIED AVAILABILITY UPDATE\nExample availability flag changed.\n"
                "FPL source snapshot\nMonitor before transfer deadline\n"
                "#FPL #FPLVortex #Availability #GW10",
        gameweek=10, player_name="Example", team_name="Arsenal",
        photo_code=123456, club_code=3, source="Official FPL",
    )


def test_graphic_has_player_and_crest_and_true_16_by_9(monkeypatch, tmp_path):
    master = tmp_path / "blue_master.png"
    Image.new("RGB", (1536, 864), "#07192e").save(master)
    monkeypatch.setattr(graphics, "MASTER", master)
    called = []

    def media(session, code, kind, cache):
        called.append((code, kind))
        return Image.new("RGBA", (250, 300), (115, 150, 220, 255)) if kind == "photo" else \
               Image.new("RGBA", (90, 90), (0, 220, 120, 255))
    monkeypatch.setattr(graphics, "_media", media)
    output = tmp_path / "posted.png"
    assert graphics.render_news_card(_post(), output) == output
    with Image.open(output) as final:
        assert final.size == (1920, 1080)
    assert (123456, "photo") in called and (3, "crest") in called


def test_missing_player_media_is_a_hard_block(monkeypatch, tmp_path):
    master = tmp_path / "blue_master.png"
    Image.new("RGB", (1536, 864), "#07192e").save(master)
    monkeypatch.setattr(graphics, "MASTER", master)
    monkeypatch.setattr(graphics, "_media", lambda *a, **kw: None)
    monkeypatch.setattr(graphics, "_bundled_portrait", lambda name: None)
    target = tmp_path / "blocked.png"
    with pytest.raises(RuntimeError, match="portrait"):
        graphics.render_news_card(_post(), target)
    assert not target.exists()


def test_missing_club_crest_is_a_hard_block(monkeypatch, tmp_path):
    master = tmp_path / "blue_master.png"
    Image.new("RGB", (1536, 864), "#07192e").save(master)
    monkeypatch.setattr(graphics, "MASTER", master)
    monkeypatch.setattr(graphics, "_media",
                        lambda session, code, kind, cache: Image.new("RGBA", (250, 300))
                        if kind == "photo" else None)
    with pytest.raises(RuntimeError, match="crest"):
        graphics.render_news_card(_post(), tmp_path / "blocked.png")


def test_missing_visual_ids_are_not_silently_omitted(tmp_path):
    with pytest.raises(ValueError, match="mandatory"):
        graphics.render_news_card(NewsPost("a", "b", "c", 10),
                                  tmp_path / "not-created.png")
