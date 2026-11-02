"""No-network checks: new Telegram-only news window preserves all old times."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from PIL import Image

from vortex.fpl import FplSnapshot
import vortex.telegram_news_window as news

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/telegram-daily.yml"
NOW = datetime(2026, 11, 2, 13, 0, tzinfo=timezone.utc)


def snap(status="a", cost=70):
    player = {"id": 99, "code": 123456, "team": 1, "web_name": "Example",
              "status": status, "now_cost": cost, "news": "",
              "chance_of_playing_next_round": None,
              "chance_of_playing_this_round": None,
              "selected_by_percent": "20.0", "minutes": 900,
              "total_points": 60, "form": "4.5"}
    teams = {1: {"name": "Arsenal", "short_name": "ARS", "code": 3},
             2: {"name": "Chelsea", "short_name": "CHE", "code": 8}}
    events = [{"id": 9, "finished": True},
              {"id": 10, "finished": False,
               "deadline_time": (NOW + timedelta(days=4)).isoformat()}]
    fixtures = [{"id": 10, "team_h": 1, "team_a": 2, "event": 10,
                 "finished": False, "team_h_difficulty": 2,
                 "team_a_difficulty": 4,
                 "kickoff_time": (NOW + timedelta(days=5)).isoformat()}]
    return FplSnapshot([player], teams, events, fixtures, NOW)


def setup_files(monkeypatch, path):
    for name in ("BASELINE", "PENDING", "RECEIPTS", "SHARED"):
        monkeypatch.setattr(news, name, path / (name.lower() + ".json"))
    monkeypatch.setattr(news, "OUTPUT", path / "rendered")
    monkeypatch.delenv("FPL_PUBLISH_PAUSED", raising=False)


def test_news_window_follows_scheduled_local_cron_not_wall_clock():
    assert news.in_window("0 6 * * *")
    assert news.in_window("0 21 * * *")
    assert not news.in_window("0 5 * * *")
    assert not news.in_window("0 22 * * *")
    assert not news.in_window("15 21 * * *")
    assert not news.in_window(None)


def test_existing_cron_times_and_task_jobs_are_retained():
    workflow = WORKFLOW.read_text()
    crons = re.findall(r"^\s+- cron: '([^']+)'", workflow, re.MULTILINE)
    assert len(crons) == len(set(crons)) == 41
    assert "0 5 * * *" in crons and "15 5 * * *" in crons
    assert "0 6 * * *" in crons and "0 19 * * *" in crons
    assert "0 17 * * *" in crons and "0 18 * * *" in crons
    assert "0 20 * * *" in crons and "0 21 * * *" in crons
    assert workflow.count("  publish:\n") == 1
    assert "Check verified Telegram news from 6 AM through 9 PM ET" in workflow
    assert '"0 21 * * *"' in workflow.split("      - name: Deliver existing graphic")[1].split(
        "      - name: Audit unified news")[0]
    assert "python -m vortex.task_publisher" in workflow


def test_cold_start_is_baseline_not_false_news(monkeypatch, tmp_path):
    setup_files(monkeypatch, tmp_path)
    result = news.run(cron="0 6 * * *", now=NOW, snapshot=snap())
    assert result["posted"] == 0 and "baseline" in result["status"]
    assert news.BASELINE.exists()
    assert not news.RECEIPTS.exists()


def test_change_generates_real_png_five_line_caption_and_receipt(monkeypatch, tmp_path):
    setup_files(monkeypatch, tmp_path)
    news.run(cron="0 6 * * *", now=NOW, snapshot=snap())
    published = []
    class FakeTelegram:
        def send_shared_png(self, file, caption, title, gw):
            assert file.exists()
            with Image.open(file) as check:
                assert check.size == (1920, 1080)
            lines = caption.splitlines()
            assert len(lines) == 5
            assert lines[-1].count("#") == 4
            assert "doubt" in caption
            assert gw == 10
            published.append((file, title, caption))
            return 725
    def render(snapshot, player, title, caption, action, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1920, 1080)).save(path)
    changed = snap(status="d")
    result = news.run(cron="0 7 * * *", now=NOW + timedelta(hours=1),
                      snapshot=changed, telegram=FakeTelegram(), renderer=render)
    assert result["posted"] == 1 and len(published) == 1
    receipt_keys = list(news.read_state(news.RECEIPTS))
    assert receipt_keys[0].startswith("2026-27:GW10:news:availability:")
    assert news.read_state(news.RECEIPTS)[receipt_keys[0]]["telegram_message_id"] == 725
    repeated = news.run(cron="0 8 * * *", now=NOW + timedelta(hours=2),
                        snapshot=changed, telegram=FakeTelegram(), renderer=render)
    assert repeated["posted"] == 0 and len(published) == 1


def test_no_fake_image_means_no_post_and_retriable_queue(monkeypatch, tmp_path):
    setup_files(monkeypatch, tmp_path)
    news.run(cron="0 6 * * *", now=NOW, snapshot=snap())
    class NeverSend:
        def send_shared_png(self, *args, **kwargs):
            raise AssertionError("Text-only or fake media delivery prohibited")
    def no_media(*args, **kwargs):
        raise RuntimeError("Premier League image 403")
    result = news.run(cron="0 7 * * *", now=NOW + timedelta(hours=1),
                      snapshot=snap(status="i"), telegram=NeverSend(),
                      renderer=no_media)
    assert result["posted"] == 0 and result["held"] == 1
    assert len(news.read_state(news.PENDING)) == 1
    assert not news.RECEIPTS.exists()


def test_manual_and_5am_do_not_publish(monkeypatch, tmp_path):
    setup_files(monkeypatch, tmp_path)
    for cron in ("0 5 * * *", "", "0 22 * * *"):
        assert news.run(cron=cron, now=NOW)["posted"] == 0
    assert not news.BASELINE.exists()
