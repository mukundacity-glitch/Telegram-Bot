"""Offline contract tests for next-gameweek selection and new recommendation posts."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from test_content import fake_snapshot
from vortex.content import generate
from vortex.fpl import latest_completed_gw, next_upcoming_gw
from vortex.recommendations import recent_summary, select
from vortex.render import render
from vortex.schedule import SLOT_CRONS, SLOT_HOURS


def fixture(snapshot, event, home=1, away=2, finished=False, fdr=2, index=100):
    return {"id": index, "event": event, "finished": finished,
            "kickoff_time": "2026-10-18T13:00:00Z",
            "team_h": home, "team_a": away,
            "team_h_difficulty": fdr, "team_a_difficulty": fdr}


def test_latest_review_rejects_unfinished_or_postponed_fixture():
    snap = fake_snapshot()
    snap.events[:] = [{"id": 8, "finished": True},
                   {"id": 9, "finished": True},
                   {"id": 10, "is_next": True, "finished": False, "deadline_time": "2026-10-22T10:00:00Z"}]
    snap.fixtures[:] = [fixture(snap, 8, finished=True), fixture(snap, 9, finished=False)]
    assert latest_completed_gw(snap) == 8
    assert next_upcoming_gw(snap) == 10
    snap.fixtures[1]["finished"] = True
    assert latest_completed_gw(snap) == 9


def test_upcoming_gw_uses_deadline_not_stale_is_next_flag():
    snap = fake_snapshot()
    snap.events[:] = [{"id": 9, "finished": False, "is_next": True,
                    "deadline_time": "2026-10-15T10:00:00Z"},
                   {"id": 10, "finished": False, "is_next": False,
                    "deadline_time": "2026-10-23T10:00:00Z"}]
    assert snap.gameweek() == 10


def test_exact_event_blank_and_double():
    snap = fake_snapshot()
    snap.fixtures[:] = [fixture(snap, 7, home=2, away=3, fdr=2),
                     fixture(snap, 7, home=4, away=2, fdr=5, index=101),
                     fixture(snap, 8, home=2, away=5, fdr=1, index=102)]
    player = snap.players[0]  # team 2
    assert len(snap.fixtures_for_gameweek(player, 7)) == 2
    assert [row[2] for row in snap.fixtures_for_gameweek(player, 7)] == [2, 5]
    assert snap.fixtures_for_gameweek({"team": 19}, 7) == []


def test_defcon_is_match_threshold_not_season_floor_division():
    defender = [{"round": 5, "defensive_contribution": 9, "total_points": 2},
                {"round": 6, "defensive_contribution": 10, "total_points": 6},
                {"round": 7, "defensive_contribution": 21, "total_points": 7}]
    stats = recent_summary(defender, [5, 6, 7], 2)
    assert stats["dc_actions"] == 40
    assert stats["dc_points"] == 4
    mid = recent_summary(defender, [5, 6, 7], 3)
    assert mid["dc_points"] == 2
    goalkeeper = recent_summary([{"round": 7, "saves": 7, "total_points": 5,
                                  "defensive_contribution": 30}], [7], 1)
    assert goalkeeper["save_points"] == 2
    assert goalkeeper.get("dc_points") is None
    assert goalkeeper.get("dc_actions") is None


def recommendation_snapshot():
    snap = fake_snapshot()
    for index, p in enumerate(snap.players):
        p.update({
            "element_type": (index % 4) + 1,
            "transfers_in_event": 10000 - index * 19,
            "transfers_out_event": 9000 - index * 17,
            "selected_by_percent": "15.5",
            "defensive_contribution": 18,
            "saves": 24, "clean_sheets": 2,
            "expected_goals": "2.1",
            "expected_assists": "1.0",
        })
    snap.fixtures[:] = [fixture(snap, 7, home=i, away=i + 1, index=100 + i)
                     for i in range(1, 20, 2)]
    snap.fixtures.extend([fixture(snap, 6, finished=True, index=500)])
    return snap


@pytest.mark.parametrize("kind", ["buy", "sell"])
def test_new_post_has_four_ranked_cards_consistent_caption_and_true_transfer_period(kind, monkeypatch):
    snap = recommendation_snapshot()
    def history(player_id, session):
        return [{"round": 6, "total_points": 8, "minutes": 90, "goals_scored": 1,
                 "assists": 0, "saves": 4, "expected_goals_conceded": "1.1",
                 "defensive_contribution": 10, "clean_sheets": 1, "bonus": 2}]
    monkeypatch.setattr("vortex.recommendations.get_history", history)
    post = generate(kind, snap, datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
    assert len(post.cards) == 4
    assert post.title.startswith("GW7: FOUR ")
    assert "Market" not in post.title
    assert post.caption.splitlines()[-1] == "#FPL #GW7 #FPLVortex"
    assert len(post.caption.splitlines()) == 6
    assert "24 hour" not in post.caption.lower()
    transfer_key = "transfers_in_event" if kind == "buy" else "transfers_out_event"
    for card in post.cards:
        player = next(p for p in snap.players if p["web_name"] == card.headline)
        assert card.metrics["transfers"] == f"{player[transfer_key]:,}"
        assert card.metrics["transfer_period"] == "OFFICIAL EVENT-TO-DATE"
        assert card.metrics["decision"] in (kind.upper(), "WATCHLIST")
        assert card.metrics["next_gw"] == "7"


def test_new_cards_fail_closed_without_both_actual_images(monkeypatch, tmp_path: Path):
    snap = recommendation_snapshot()
    monkeypatch.setattr("vortex.recommendations.get_history", lambda *args: [])
    post = generate("buy", snap, datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
    monkeypatch.setattr("vortex.premium._media",
                        lambda session, code, kind, cache: None if kind == "photo" else Image.new("RGBA", (90, 90)))
    with pytest.raises(RuntimeError, match="requires verified player photo"):
        render(post, tmp_path / "should-not-publish.png", session=object())
    assert not (tmp_path / "should-not-publish.png").exists()


@pytest.mark.parametrize("kind", ["buy", "sell"])
def test_preview_render_size_with_verified_media(kind, monkeypatch, tmp_path: Path):
    snap = recommendation_snapshot()
    monkeypatch.setattr("vortex.recommendations.get_history", lambda *args: [])
    post = generate(kind, snap, datetime(2026, 10, 16, 14, tzinfo=timezone.utc), {})
    monkeypatch.setattr("vortex.premium._media", lambda session, code, media_kind, cache:
                        Image.new("RGBA", (260, 300) if media_kind == "photo" else (80, 80),
                                  (150, 200, 245, 255)))
    out = render(post, tmp_path / f"{kind}-preview.png", session=object())
    with Image.open(out) as img:
        assert img.size == (1536, 864)
        assert img.getbbox() is not None


def test_new_schedule_is_non_conflicting_and_has_backup():
    assert SLOT_HOURS["buy"] == (9, 0)
    assert SLOT_HOURS["sell"] == (18, 30)
    assert len(set(SLOT_HOURS.values())) == len(SLOT_HOURS)
    assert SLOT_CRONS["15 9 * * *"] == "buy"
    assert SLOT_CRONS["45 18 * * *"] == "sell"


def test_recommendation_risk_text_is_bounded_by_card_width():
    from PIL import ImageDraw
    from vortex.premium import _safe_line
    img = Image.new("RGB", (600, 100), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    left, width = 20, 315
    before = Image.new("RGB", img.size, (0, 0, 0))
    _safe_line(draw,
               "RISK: HOLD if a free transfer has higher value elsewhere because an exceptionally "
               "long official status note might otherwise overlap the adjacent player card",
               left, 20, width, 15, (255, 255, 255), 13)
    # Text pixels must stay entirely within the assigned card's usable region.
    changes = Image.new("RGB", img.size)
    from PIL import ImageChops
    bbox = ImageChops.difference(img, before).getbbox()
    assert bbox is not None
    assert bbox[2] <= left + width + 1
