from dataclasses import replace
from datetime import timedelta

from PIL import Image
import pytest

from test_content import fake_snapshot
from vortex import bot
from vortex.content import generate
from vortex.publish_checks import render_checked, validate_article


@pytest.fixture
def stats_snapshot():
    snapshot = fake_snapshot()
    for i, p in enumerate(snapshot.players, 1):
        p.update(code=1000+i, expected_goals="1.25", bonus=i % 10,
                 selected_by_percent=str(i % 70), defensive_contribution=i,
                 transfers_in_event=10000-i*100, transfers_out_event=12000-i*150)
        if i % 10 == 0:
            p.update(element_type=1, saves=i, clean_sheets=i // 10)
    return snapshot


def test_stats_use_current_fields_rotate_and_keep_caption_in_sync(stats_snapshot):
    snapshot = stats_snapshot
    snapshot.players[6]["expected_goals"] = "13.77"
    snapshot.players[6]["goals_scored"] = 4
    now = snapshot.fetched_at
    article = generate("daily_stats", snapshot, now, {})
    tomorrow = generate("daily_stats", snapshot, now + timedelta(days=1), {})
    assert article.kind == "daily_stats" and len(article.cards) == 10
    assert article.cards[0].headline == "Player 7"
    assert article.cards[0].fields == ("13.77", "4 goals")
    assert article.cards[2].fields[0] == "9.77 short"
    assert article.cards[:5] == tomorrow.cards[:5]
    assert article.cards[5:] != tomorrow.cards[5:]
    assert "Player 7 (13.77)" in article.caption
    assert article.caption.endswith("#FPL #FPLCommunity #GW7 #FPLVORTEX #FantasyPremierLeague")
    assert "ELITE FPL EDGE" not in article.title


def test_checked_stats_png_and_unverified_content(stats_snapshot, tmp_path, monkeypatch):
    monkeypatch.setenv("FPL_ENRICHED_VISUALS_ENABLED", "true")
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE", "@FPLVortexDailyBot")
    monkeypatch.setenv("FPL_DISCORD_HANDLE", "@fplvortex")
    monkeypatch.setattr("vortex.daily_stats_render._media", lambda *a: None)
    monkeypatch.setattr("vortex.daily_stats_render._player_image", lambda *a: None)
    article = generate("daily_stats", stats_snapshot, stats_snapshot.fetched_at, {})
    with pytest.raises(RuntimeError, match="does not match"):
        validate_article(replace(article, cards=article.cards[:-1]), stats_snapshot)
    path = render_checked(article, stats_snapshot, tmp_path / "stats.png")
    with Image.open(path) as image:
        assert image.size == (1920, 1080)
        assert image.mode == "RGB"
        assert max(image.getpixel((100, 470))) < 120


def test_existing_cron_uses_daily_stats_and_reuses_receipt(stats_snapshot, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "STATE", tmp_path)
    monkeypatch.setattr(bot, "OUTPUT", tmp_path)
    monkeypatch.setattr(bot, "collect_snapshot", lambda: stats_snapshot)
    monkeypatch.setenv("FPL_SEMANTIC_DEDUP_ENABLED", "true")
    monkeypatch.setenv("DUAL_PUBLISH_ENABLED", "false")
    monkeypatch.setattr("vortex.daily_stats_render._media", lambda *a: None)
    monkeypatch.setattr("vortex.daily_stats_render._player_image", lambda *a: None)
    posts = []

    class Telegram:
        def send_shared_png(self, image, caption, title, gw):
            posts.append((image, caption, title, gw))
            return 1

        send_png = send_shared_png

    monkeypatch.setattr(bot, "TelegramClient", Telegram)
    assert bot.run("auto", "0 7 * * *") == 0
    assert bot.run("auto", "15 7 * * *") == 0
    assert len(posts) == 1
    image, caption, title, gw = posts[0]
    assert image.name == "FPLVortex_GW7_daily_stats.png" and image.exists()
    assert caption.endswith("#FantasyPremierLeague")
    assert title == "10 SURPRISING FPL STATS" and gw == 7
