"""Mobile 1920x1080 2-4 player card fixture/portrait layout contract."""
from PIL import Image

from test_publication_contract import snap
from vortex.content import Card, Content
import vortex.multi_profile as multi
import vortex.brand_footer as footer


def test_two_person_approved_master_with_five_gw_fdr_and_optional_xpts(monkeypatch, tmp_path):
    s = snap()
    second = dict(s.players[0])
    second.update({"id": 100, "code": 124, "web_name": "Second"})
    s.players.append(second)
    post = Content("comparison", "PLAYER COMPARISON", "NEXT GW",
        (Card("Example", "ARS", "HOLD", ("verified",), 123, 3),
         Card("Second", "ARS", "MONITOR", ("verified",), 124, 3)),
        "HOLD", "Updated insights\n#FPL #GW10 #FPLVortex #PremierLeague",
        "internal", 10, "")
    blue = tmp_path / "brand.png"
    Image.new("RGB", (1536, 864), (5, 16, 46)).save(blue)
    monkeypatch.setattr(multi, "MASTER", blue)
    monkeypatch.setattr(footer, "MASTER", blue)
    monkeypatch.setenv("FPL_TELEGRAM_HANDLE", "@realTelegram")
    monkeypatch.setenv("FPL_DISCORD_HANDLE", "@realDiscord")
    seen = []
    def media(session, code, kind, cache):
        seen.append((code, kind))
        return Image.new("RGBA", (225, 250) if kind == "photo" else (62, 64),
                         (110, 167, 231, 255))
    monkeypatch.setattr(multi, "_media", media)
    monkeypatch.setattr(multi, "get_history", lambda *args: [])
    monkeypatch.setattr(multi, "fetch_verified_xpts", lambda *args: {(99, 100): {"gw": 10, "xpts": 4.75}})
    target = tmp_path / "two-card.png"
    assert multi.render_multi_profile(post, s, target, session=object()) == target
    with Image.open(target) as output:
        assert output.size == (1920, 1080)
    assert seen.count((123, "photo")) == 1
    assert seen.count((124, "photo")) == 1
    assert seen.count((3, "crest")) == 2
