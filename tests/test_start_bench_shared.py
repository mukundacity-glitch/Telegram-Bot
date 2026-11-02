"""Task 1 start/bench slide and unified exact-caption transport."""
from datetime import datetime, timezone

import pytest
from PIL import Image

from test_recommendations import recommendation_snapshot
from vortex.content import generate
from vortex.render import render
from vortex.syndication import NewsPost, publish_shared


def _snapshot():
    snap = recommendation_snapshot()
    for i, p in enumerate(snap.players):
        p["code"] = 100000 + i
        p["form"] = str(2.0 + (i % 10)*0.5)
        p["points_per_game"] = str(3.0 + (i % 8)*0.6)
        p["status"] = "a"
        p["minutes"] = 900
    return snap


def test_start_bench_is_one_unique_card_per_player_and_four_positions():
    snap = _snapshot()
    output = generate("start_bench", snap, snap.fetched_at, {})
    assert output.title == "WHO TO BENCH • WHO TO START"
    assert len(output.start_bench) == 10
    assert len(set(p["id"] for p in output.start_bench)) == 10
    assert [p["advice"] for p in output.start_bench] == ["START"]*5 + ["BENCH"]*5
    for group in (output.start_bench[:5], output.start_bench[5:]):
        assert {p["pos"] for p in group} == {"GK", "DEF", "MID", "FWD"}
    assert all(p["photo_code"] is not None and p["club_code"] is not None
               and p["xpts"] is None for p in output.start_bench)
    assert len([word for word in output.caption.split() if word.startswith("#")]) == 4


def test_start_bench_graphic_is_real_1920x1080_with_all_media(monkeypatch, tmp_path):
    from vortex import extra_render
    snap = _snapshot()
    output = generate("start_bench", snap, snap.fetched_at, {})
    calls = []

    def media(session, code, kind, cache):
        calls.append((code, kind))
        return Image.new("RGBA", (250, 280) if kind == "photo" else (70, 70),
                         (100, 190, 240, 255))
    monkeypatch.setattr(extra_render, "_media", media)
    img = render(output, tmp_path / "start_bench.png", session=object())
    with Image.open(img) as result:
        assert result.size == (1920, 1080)
    assert len([item for item in calls if item[1] == "photo"]) == 10
    assert len([item for item in calls if item[1] == "crest"]) == 10


def test_start_bench_no_photo_blocks_publishing(monkeypatch, tmp_path):
    from vortex import extra_render
    output = generate("start_bench", _snapshot(), datetime.now(timezone.utc), {})
    monkeypatch.setattr(extra_render, "_media", lambda *args: None)
    with pytest.raises(RuntimeError, match="photo unavailable"):
        render(output, tmp_path / "blocked.png", session=object())
    assert not (tmp_path / "blocked.png").exists()


def test_shared_publisher_selects_exact_caption_without_legacy_icons(tmp_path):
    call = []
    class T:
        def send_shared_png(self, image, caption, title, gameweek):
            call.append(("telegram", caption, image))
            return 111
        def send_png(self, image, caption, title, gameweek):
            pytest.fail("Legacy Telegram formatting not allowed in shared mode")
    class D:
        def send(self, post):
            call.append(("discord", post.caption, post.image))
            return "222"
    image = tmp_path / "news.png"
    Image.new("RGB", (1920, 1080), "navy").save(image)
    text = "Official FPL update\nMonitor ahead of deadline\n#FPL #GW10 #FPLVortex #Availability"
    post = NewsPost("gw10-update", "Update", text, 10, image)
    result = publish_shared(post, tmp_path / "receipts.json", T(), D())
    assert result["delivered"] and result["discord_delivered"]
    assert call == [("telegram", text, image), ("discord", text, image)]
    assert len([w for w in text.split() if w.startswith("#")]) == 4
