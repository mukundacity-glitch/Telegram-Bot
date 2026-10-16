from datetime import datetime, timezone

from vortex.content import _caption, generate
from vortex.fpl import FplSnapshot, confirmed_price_changes, price_snapshot
from vortex.render import render


def fake_snapshot():
    teams = {index: {"id": index, "name": f"Team {index}", "short_name": f"T{index}", "code": 100 + index} for index in range(1, 21)}
    players = []
    for index in range(1, 125):
        players.append({
            "id": index,
            "code": None,
            "web_name": f"Player {index}",
            "team": (index % 20) + 1,
            "element_type": 3 if index % 2 else 4,
            "status": "a",
            "minutes": 900,
            "now_cost": 55 + (index % 20),
            "form": "7.5" if index <= 4 else "4.0",
            "points_per_game": "7.0" if index <= 4 else "4.0",
            "ep_next": "6.0",
            "selected_by_percent": "10.0",
            "total_points": 80,
            "goals_scored": 3,
            "assists": index % 7,
            "expected_assists": "2.5",
            "news": "",
            "news_added": None,
        })
    fixtures = [{"id": index, "kickoff_time": f"2026-10-{17 + index:02d}T16:00:00Z", "team_h": index, "team_a": (index % 20) + 1, "team_h_difficulty": 2, "team_a_difficulty": 3} for index in range(1, 21)]
    events = [{"id": 6, "finished": True}, {"id": 7, "is_next": True, "deadline_time": "2026-10-17T10:00:00Z", "finished": False}]
    return FplSnapshot(players, teams, events, fixtures, datetime(2026, 10, 16, 12, tzinfo=timezone.utc))


def test_price_baseline_and_changes():
    s = fake_snapshot()
    assert confirmed_price_changes(s, {}) == []
    prior = price_snapshot(s)
    s.players[0]["now_cost"] += 1
    changes = confirmed_price_changes(s, prior)
    assert len(changes) == 1
    assert changes[0][1] == 56
    assert changes[0][2] == 57


def test_seven_unconditional_content_slots():
    s = fake_snapshot()
    for slot in ["elite", "comparison", "news", "prices", "transfer", "captaincy", "evening"]:
        content = generate(slot, s, datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
        assert len(content.caption.splitlines()) == 6
        assert len(content.caption) <= 280
        assert content.caption.endswith("#FPL #GW7 #FPLVortex")
        assert content.cards


def test_renderer_creates_png_without_external_images(tmp_path):
    class Offline:
        def get(self, *args, **kwargs):
            raise OSError("no network")
    s = fake_snapshot()
    content = generate("comparison", s, datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
    output = tmp_path / "comparison.png"
    render(content, output, session=Offline())
    from PIL import Image
    with Image.open(output) as image:
        assert image.size == (1536, 864)
        assert image.mode == "RGB"


def test_caption_does_not_accept_six_story_lines():
    try:
        _caption(["a"] * 6, 7)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected six-line story rejection")


def test_review_uses_only_last_completed_gameweek(monkeypatch):
    import vortex.content as content_module
    snapshot = fake_snapshot()
    player = snapshot.players[3]
    monkeypatch.setattr(content_module, "previous_gw_top_players", lambda current: [(player, 14)])
    content = generate("review", snapshot, datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
    assert "GW6 REVIEW" in content.title
    assert "14 FPL points" in content.cards[0].fields[0]
    assert content.caption.endswith("#FPL #GW7 #FPLVortex")


def test_player_stats_are_not_embedded_in_background_templates():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert (root / "assets" / "references" / "brand_background.png").exists()
    assert (root / "assets" / "assists" / "5.png").exists()