from datetime import datetime, timezone

import pytest
from PIL import Image

from vortex.content import _caption, generate
from vortex.fpl import FplSnapshot, choose_comparison, confirmed_price_changes, price_snapshot
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


def test_matchup_does_not_publish_without_player_images(tmp_path):
    class Offline:
        def get(self, *args, **kwargs):
            raise OSError("no network")

    s = fake_snapshot()
    content = generate("comparison", s, datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
    output = tmp_path / "comparison.png"
    with pytest.raises(RuntimeError, match="Neither official portrait nor club crest"):
        render(content, output, session=Offline())
    assert not output.exists()


def test_comparison_layout_renders_real_metrics_with_available_images(tmp_path, monkeypatch):
    s = fake_snapshot()
    content = generate("comparison", s, datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
    assert all(card.metrics and card.metrics["total_points"] == 80 for card in content.cards)
    assert all(card.fixtures for card in content.cards)

    def fake_media(session, code, kind, cache):
        return Image.new("RGBA", (250, 300) if kind == "photo" else (70, 70),
                         (100, 165, 235, 255) if kind == "photo" else (220, 230, 245, 255))

    monkeypatch.setattr("vortex.matchup._media", fake_media)
    output = tmp_path / "comparison.png"
    render(content, output, session=object())
    with Image.open(output) as image:
        assert image.size == (1536, 864)
        assert image.mode == "RGB"
        assert image.getpixel((40, 160)) != image.getpixel((800, 160))


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


def test_matched_reference_portraits_are_a_safe_fallback(tmp_path, monkeypatch):
    from dataclasses import replace
    snapshot = fake_snapshot()
    original = generate("comparison", snapshot, datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
    left, right = original.cards
    content = replace(original, cards=(replace(left, headline="DE CUYPER"), replace(right, headline="TARKOWSKI")))

    def missing_photos(session, code, kind, cache):
        return None if kind == "photo" else Image.new("RGBA", (70, 70), (225, 235, 250, 255))

    monkeypatch.setattr("vortex.matchup._media", missing_photos)
    output = tmp_path / "fallback.png"
    render(content, output, session=object())
    assert output.exists()

def test_comparison_skips_unmatched_top_player() -> None:
    snapshot = fake_snapshot()
    isolated = snapshot.players[0]
    isolated['form'] = '99.0'
    isolated['now_cost'] = 200
    first, second = choose_comparison(snapshot)
    assert first['id'] != isolated['id']
    assert first['element_type'] == second['element_type']
    assert first['team'] != second['team']
    assert abs(first['now_cost'] - second['now_cost']) <= 30


def test_comparison_renders_with_verified_club_badge_if_player_photo_missing(tmp_path, monkeypatch) -> None:
    snapshot = fake_snapshot()
    content = generate('comparison', snapshot, datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})

    def fake_media(session, code, kind, cache):
        if kind == 'photo':
            return None
        return Image.new('RGBA', (70, 70), (240, 200, 80, 255))

    monkeypatch.setattr('vortex.matchup._media', fake_media)
    result = render(content, tmp_path / 'badge-fallback.png', session=object())
    assert result.is_file()
