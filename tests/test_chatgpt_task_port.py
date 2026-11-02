"""Migration contract for the four prior ChatGPT schedules, both real channels."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from PIL import Image
import pytest

from test_publication_contract import snap
from vortex.chatgpt_task_editions import EDITIONS, due_editions, CRONS, generate_edition
import vortex.task_publisher as publisher


def test_all_four_task_catalogs_have_exact_original_slots():
    assert len(EDITIONS) == 12
    assert {e.task for e in EDITIONS} == {"task1", "task2", "three_daily", "press_news"}
    assert len(CRONS) == len(EDITIONS)
    by_task = {}
    for e in EDITIONS:
        by_task.setdefault(e.task, []).append(f"{e.hour:02d}:{e.minute:02d}")
    assert by_task["task1"] == ["06:00", "10:00", "15:00", "19:00"]
    assert by_task["task2"] == ["08:00", "10:45", "12:00", "15:45"]
    assert by_task["three_daily"] == ["07:30", "12:30", "19:30"]
    assert by_task["press_news"] == ["14:00"]


def test_press_news_keeps_actual_three_day_cadence():
    nov2 = datetime(2026, 11, 2, 19, 0, tzinfo=timezone.utc)
    due = due_editions(nov2, "0 14 * * *")
    assert len(due) == 1 and due[0].task == "press_news"
    assert due_editions(nov2 + timedelta(days=1), "0 14 * * *") == ()


def test_player_topic_uses_verified_football_stats_and_four_hashtags():
    s = snap()
    article = generate_edition(next(e for e in EDITIONS if e.kind == "form_targets"), s, s.fetched_at)
    assert 1 <= len(article.cards) <= 3
    assert all(c.photo_code == 123 and c.team_code == 3 for c in article.cards)
    assert all("£7.1m" in " ".join(c.fields) for c in article.cards)
    assert "N/A" not in article.caption
    assert len([p for p in article.caption.split() if p.startswith("#")]) == 4


def test_no_fake_press_conference_when_no_new_status(monkeypatch):
    s = snap()
    monkeypatch.setattr("vortex.chatgpt_task_editions.choose_news", lambda *a: [])
    press = next(e for e in EDITIONS if e.task == "press_news")
    with pytest.raises(RuntimeError, match="no duplicate filler"):
        generate_edition(press, s, s.fetched_at)


def _source_with_safe_deadline():
    s = snap()
    now = datetime.now(timezone.utc)
    for event in s.events:
        if isinstance(event.get("id"), int) and event["id"] >= 10:
            event["deadline_time"] = (now + timedelta(days=5 + (event["id"]-10)*7)).isoformat()
    s.fixtures[1]["kickoff_time"] = (now + timedelta(days=6)).isoformat()
    s.fixtures[2]["kickoff_time"] = (now + timedelta(days=7)).isoformat()
    return s, now


def test_true_same_caption_real_dual_receipts_and_no_repost(monkeypatch, tmp_path):
    s, now = _source_with_safe_deadline()
    monkeypatch.setenv("FPL_PORTED_TASKS_ENABLED", "true")
    monkeypatch.setenv("DUAL_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("FPL_ENRICHED_VISUALS_ENABLED", "true")
    monkeypatch.setattr(publisher, "STATE", tmp_path)
    monkeypatch.setattr(publisher, "OUTPUT", tmp_path)
    monkeypatch.setattr(publisher, "RECEIPTS", tmp_path / "deliveries.json")
    monkeypatch.setattr(publisher, "TASK_VERSIONS", tmp_path / "versions.json")
    def fake_render(article, snapshot, destination):
        Image.new("RGB", (1920, 1080), "#051936").save(destination)
        return destination
    monkeypatch.setattr(publisher, "render_checked", fake_render)
    messages = []
    class Telegram:
        def send_shared_png(self, img, caption, title, gw):
            assert img.is_file()
            messages.append(("telegram", img, caption, gw))
            return 999
        def send_png(self, *args):
            pytest.fail("Should send exact original caption instead of legacy formatting")
    class Discord:
        def send(self, post):
            messages.append(("discord", post.image, post.caption, post.gameweek))
            return "discord-message-21"

    inputs = dict(cron="0 10 * * *", snapshot=s, now=now,
                  telegram=Telegram(), discord=Discord())
    result = publisher.run(**inputs)
    assert result["published"] == 1 and not result["held"]
    assert len(messages) == 2
    assert messages[0][1:] == messages[1][1:]
    again = publisher.run(**inputs)
    assert again["skipped"] == 1 and again["published"] == 0
    assert len(messages) == 2


def test_original_task2_edition_never_fires_duplicate_after_legacy_delivery(monkeypatch, tmp_path):
    s, now = _source_with_safe_deadline()
    monkeypatch.setenv("FPL_PORTED_TASKS_ENABLED", "true")
    monkeypatch.setenv("DUAL_PUBLISH_ENABLED", "true")
    monkeypatch.setenv("FPL_ENRICHED_VISUALS_ENABLED", "true")
    monkeypatch.setattr(publisher, "STATE", tmp_path)
    monkeypatch.setattr(publisher, "RECEIPTS", tmp_path / "deliveries.json")
    monkeypatch.setattr(publisher, "TASK_VERSIONS", tmp_path / "versions.json")
    key = f"{now.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).date()}:projections:GW10"
    (tmp_path/"deliveries.json").write_text(json.dumps({key: {"delivered": True}}))
    result = publisher.run(cron="0 8 * * *", snapshot=s, now=now)
    assert result["skipped"] == 1 and result["published"] == 0
    assert not (tmp_path / "versions.json").exists()


def test_disabled_config_does_not_attempt_live_network(monkeypatch):
    monkeypatch.delenv("FPL_PORTED_TASKS_ENABLED", raising=False)
    result = publisher.run(cron="0 6 * * *")
    assert result["reason"] == "staging" and result["published"] == 0
