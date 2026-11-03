"""One-player news/price editions must not fall back to the retired card style."""
from PIL import Image
from vortex.content import Card, Content
from vortex.publish_checks import render_checked
from test_publication_contract import snap


def test_single_news_player_uses_reference2_profile(monkeypatch, tmp_path):
    monkeypatch.setenv('FPL_ENRICHED_VISUALS_ENABLED', 'true')
    monkeypatch.setenv('FPL_TELEGRAM_HANDLE', '@verifiedTelegram')
    monkeypatch.setenv('FPL_DISCORD_HANDLE', '@verifiedDiscord')
    article = Content('news', 'PLAYER STATUS UPDATE', 'NEXT GW',
                      (Card('Example', 'ARS', 'MONITOR', (), 123, 3),),
                      'MONITOR', '#FPL #GW10 #FPLVortex #PremierLeague',
                      'verified', 10, '')
    calls = []
    def profile(post, snapshot, output, session=None):
        calls.append(post.kind)
        Image.new('RGB', (1920, 1080)).save(output)
        return output
    monkeypatch.setattr('vortex.player_profile.render_player_profile', profile)
    target = tmp_path / 'profile.png'
    assert render_checked(article, snap(), target) == target
    assert calls == ['news']
