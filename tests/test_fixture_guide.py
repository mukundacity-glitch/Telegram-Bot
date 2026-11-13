from dataclasses import replace
from datetime import datetime, timedelta

from PIL import Image
import pytest

from test_content import fake_snapshot
from vortex import bot
from vortex.content import generate
from vortex.publish_checks import render_checked, validate_article


@pytest.fixture
def fixture_snapshot():
    sample = fake_snapshot()
    events = [dict(id=6, finished=True), *[
        dict(id=gw, finished=False, deadline_time=f"2026-10-{gw+10:02d}T10:00:00Z")
        for gw in range(7, 13)
    ]]
    fixtures = [
        dict(id=gw*20+i, event=gw, team_h=i, team_a=i+10,
             team_h_difficulty=1+i%3, team_a_difficulty=4+i%2)
        for gw in range(7, 13) for i in range(1, 11)
    ]
    for player in sample.players:
        player["code"] = 1000 + player["id"]
    return replace(sample, events=events, fixtures=fixtures)


def test_guide_ranks_fixture_runs_and_keeps_double_and_blank(fixture_snapshot):
    snapshot = fixture_snapshot
    snapshot.fixtures[:] = [row for row in snapshot.fixtures if row["id"] != 143]
    snapshot.fixtures.append(dict(id=999, event=8, team_h=3, team_a=20,
                                  team_h_difficulty=1, team_a_difficulty=5))
    article = generate("elite", snapshot, snapshot.fetched_at, {})
    assert article.kind == "fixture_guide" and article.kicker == "GW7–12"
    assert len(article.cards) == 6
    assert {card.label for card in article.cards[:3]} == {"TARGET"}
    assert {card.label for card in article.cards[3:]} == {"CAUTION"}
    target = next(card for card in article.cards if card.headline == "Team 3")
    assert any(opp == "7 BLANK" for opp, *_ in target.fixtures)
    assert sum(opp.startswith("8 ") for opp, *_ in target.fixtures) == 2
    assert article.caption.endswith("#FPL #FPLCommunity #GW7 #FPLVORTEX #FantasyPremierLeague")


def test_checked_guide_renders_and_rejects_unverified_edits(fixture_snapshot, tmp_path, monkeypatch):
    monkeypatch.setenv("FPL_ENRICHED_VISUALS_ENABLED", "true")
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE", "@FPLVortexDailyBot")
    monkeypatch.setenv("FPL_DISCORD_HANDLE", "@fplvortex")
    monkeypatch.setattr("vortex.fixture_guide_render._media", lambda *a: None)
    monkeypatch.setattr("vortex.fixture_guide_render._player_image", lambda *a: None)
    article = generate("elite", fixture_snapshot, fixture_snapshot.fetched_at, {})
    with pytest.raises(RuntimeError, match="does not match"):
        validate_article(replace(article, cards=article.cards[:-1]), fixture_snapshot)
    path = render_checked(article, fixture_snapshot, tmp_path / "fixture-guide.png")
    with Image.open(path) as image:
        assert image.size == (1920, 1080)
        assert image.mode == "RGB"


def test_existing_daily_slot_delivers_guide_once(fixture_snapshot, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "STATE", tmp_path)
    monkeypatch.setattr(bot, "OUTPUT", tmp_path)
    monkeypatch.setattr(bot, "collect_snapshot", lambda: fixture_snapshot)
    monkeypatch.setenv("FPL_SEMANTIC_DEDUP_ENABLED", "true")
    monkeypatch.setenv("DUAL_PUBLISH_ENABLED", "false")
    monkeypatch.setattr("vortex.fixture_guide_render._media", lambda *a: None)
    monkeypatch.setattr("vortex.fixture_guide_render._player_image", lambda *a: None)
    posts = []

    class Telegram:
        def send_shared_png(self, image, caption, title, gw):
            posts.append((image, caption, title, gw))
            return 1

        send_png = send_shared_png

    monkeypatch.setattr(bot, "TelegramClient", Telegram)
    assert bot.run("auto", "30 6 * * *") == 0
    assert bot.run("auto", "45 6 * * *") == 0
    assert len(posts) == 1
    image, caption, title, gw = posts[0]
    assert image.name == "FPLVortex_GW7_fixture_guide.png" and image.exists()
    assert caption.endswith("#FantasyPremierLeague")
    assert title == "FPL GAMEWEEK 7 FIXTURE GUIDE" and gw == 7


def test_delete_only_confirmed_old_elite_message(tmp_path):
    from vortex.retire_elite_message import IDENTITY, SENT_AT, retire_replaced_elite

    path = tmp_path / "deliveries.json"
    receipt = {"delivered": True, "timestamp": SENT_AT, "source": "Official FPL",
               "telegram_message_id": 12}
    bot.write_state(path, {IDENTITY: receipt, "unrelated": {**receipt, "telegram_message_id": 13}})
    calls = []

    class Telegram:
        chat_id = "test-chat"

        def verify_destination(self):
            pass

        def _post(self, method, data):
            calls.append((method, data["message_id"]))
            return {"result": True}

    client = Telegram()
    sent = datetime.fromisoformat(SENT_AT)
    retire_replaced_elite(client, path, sent + timedelta(hours=48))
    assert not calls
    retire_replaced_elite(client, path, sent + timedelta(hours=12))
    retire_replaced_elite(client, path, sent + timedelta(hours=13))
    assert calls == [("deleteMessage", 12)]
    assert bot.read_state(path)[IDENTITY]["telegram_deleted"]
    assert not bot.read_state(path)["unrelated"].get("telegram_deleted")
