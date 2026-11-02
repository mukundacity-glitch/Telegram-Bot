"""Strict player/team availability data guards; no N/A publications."""
from dataclasses import replace

import pytest

from test_publication_contract import snap
from vortex.extra_posts import ExtraPost
from vortex.publish_checks import validate_article


def test_team_analysis_holds_without_completed_gw_history(monkeypatch):
    s = snap()
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE", "@verifiedTelegram")
    monkeypatch.setenv("FPL_DISCORD_HANDLE", "@verifiedDiscord")
    post = ExtraPost(kind="team_analysis", title="TEAM", kicker="NEXT",
                     caption="Match analysis\n#FPL #GW10 #FPLVortex #Team",
                     data_at="", gw=10, footer="",
                     team_analysis={"history": [], "gf_total": None,
                                    "ga_total": None, "opponent_code": 8,
                                    "players": []})
    with pytest.raises(RuntimeError, match="Incomplete verified historical team form"):
        validate_article(post, s)


def test_transfer_suggestions_holds_unverified_visible_fdr(monkeypatch):
    s = snap()
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE", "@verifiedTelegram")
    monkeypatch.setenv("FPL_DISCORD_HANDLE", "@verifiedDiscord")
    outgoing = {"photo_code": 123, "club_code": 3, "price": "£7.1m", "form": "4.9",
                "fdr": None, "out_event": 18, "opponent": "Chelsea (H)"}
    post = ExtraPost(kind="transfer_suggestions", title="TRANSFERS", kicker="NEXT",
                     caption="Compare managers\n#FPL #GW10 #FPLVortex #Transfers",
                     data_at="", gw=10, footer="",
                     transfers=tuple({"out": outgoing, "incoming": None}
                                     for _ in range(4)))
    with pytest.raises(RuntimeError, match="unverified visible field"):
        validate_article(post, s)

def test_all20_fixture_only_graphic_is_not_blocked_by_missing_optional_bookmaker_odds(monkeypatch):
    s = snap()
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE", "@verifiedTelegram")
    monkeypatch.setenv("FPL_DISCORD_HANDLE", "@verifiedDiscord")
    fixture = {"id": 100, "home": "ARS", "away": "CHE",
               "home_code": 3, "away_code": 8, "h_fdr": 2, "a_fdr": 4,
               "home_goals": None, "away_goals": None,
               "home_cs": None, "away_cs": None}
    post = ExtraPost(kind="projections", title="GW10 MATCHUPS", kicker="NEXT",
                     caption="Real fixture only\n#FPL #GW10 #FPLVortex #Fixtures",
                     data_at="", gw=10, footer="", fixtures=(fixture,))
    validate_article(post, s)
    # Partial model data is misleading: must withhold numeric estimates.
    import dataclasses
    incomplete = dataclasses.replace(post,
        fixtures=(dict(fixture, home_goals=1.2),))
    with pytest.raises(RuntimeError, match="Partial bookmaker"):
        validate_article(incomplete, s)


def test_news_early_window_defers_to_shared_news_publisher(monkeypatch, tmp_path):
    import vortex.telegram_news_window as news
    monkeypatch.setenv("UNIFIED_NEWS_ENABLED", "true")
    monkeypatch.setattr(news, "BASELINE", tmp_path / "not-used.json")
    result = news.run(cron="0 22 * * *")
    assert result["status"] == "shared-news-owns-topic"
    assert result["posted"] == 0 and result["edited"] == 0
