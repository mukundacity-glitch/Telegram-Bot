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
