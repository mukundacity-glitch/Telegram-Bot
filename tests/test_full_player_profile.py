"""No-network visual QA for full branded 5-GW player card."""
from datetime import datetime, timezone

from PIL import Image

from vortex.content import Card, Content
from test_publication_contract import snap
import vortex.player_profile as profile
import vortex.brand_footer as footer


def test_minimal_full_player_graphic_with_fixture_fdr_and_source_free_footer(monkeypatch, tmp_path):
    data = snap()
    bg = tmp_path / "original-master.png"
    Image.new("RGB", (1536, 864), (5, 22, 57)).save(bg)
    monkeypatch.setattr(profile, "MASTER", bg)
    monkeypatch.setattr(footer, "MASTER", bg)
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE", "@verifiedTelegram")
    monkeypatch.setenv("FPL_DISCORD_HANDLE", "@verifiedDiscord")
    def image(session, code, media_kind, cache):
        if media_kind == "photo":
            return Image.new("RGBA", (245, 300), (75, 148, 218, 255))
        return Image.new("RGBA", (82, 90), (237, 72, 95, 255))
    monkeypatch.setattr(profile, "_media", image)
    monkeypatch.setattr(profile, "get_history", lambda *args: [
        {"round": 9, "minutes": 90, "total_points": 7, "defensive_contribution": 11}
    ])
    monkeypatch.setattr(profile, "completed_gw_enrichment", lambda *args: {})
    monkeypatch.setattr(profile, "fetch_verified_xpts", lambda *args: {
        (99, 100): {"gw": 10, "xpts": 5.75}})
    article = Content("news_profile", "PLAYER STATUS CHANGE", "new info",
        (Card("Example", "ARS", "MONITOR", (), 123, 3),), "MONITOR",
        "Monitor latest lineup news\n#FPL #GW10 #FPLVortex #PremierLeague",
        "internal", 10, "")
    path = tmp_path / "verified-player.png"
    assert profile.render_player_profile(article, data, path, session=object()) == path
    with Image.open(path) as result:
        assert result.size == (1920, 1080)
        assert result.getpixel((1000, 400)) != result.getpixel((0, 400))
        assert result.getpixel((5, 1060)) == (255, 255, 255)
