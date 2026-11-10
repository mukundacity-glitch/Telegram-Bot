"""Purple/gold portrait market boards render at 1080x1920 for every position group."""
import os
from pathlib import Path

from PIL import Image, ImageDraw

from vortex import autonomous_render as render_module
from vortex.autonomous_content import build
from vortex.autonomous_schedule import Slot
from vortex.autonomous_render import _market_reason
from test_autonomous_engine import world  # noqa: F401  (shared synthetic FPL snapshot)


def _placeholder(kind):
    image = Image.new('RGBA', (250, 250), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    if kind == 'photo':
        d.ellipse((85, 30, 165, 120), fill=(224, 172, 140, 255))
        d.rounded_rectangle((40, 120, 210, 250), radius=40, fill=(30, 90, 190, 255))
    else:
        d.ellipse((30, 30, 220, 220), fill=(200, 30, 40, 255), outline=(255, 255, 255, 255), width=8)
    return image


def test_market_pages_render_for_all_groups(monkeypatch, tmp_path, world):
    s, now, e, feed = world
    for name, value in (('FPL_TELEGRAM_HANDLE', '@FPLVortexDailyBot'), ('FPL_DISCORD_HANDLE', '@fplvortex'),
                        ('FPL_YOUTUBE_HANDLE', 'FPLVORTEX'), ('FPL_X_HANDLE', 'FPLVORTEXM')):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(render_module, '_assets', lambda *a, **k: (_placeholder('photo'), _placeholder('badge')))
    plan = build(Slot('task2', 'market-verdict', 15, 30), s, now, e, model=feed, research=None)
    out = Path(os.environ.get('FPL_PREVIEW_DIR') or tmp_path)
    pages = render_module._market(plan, s, out / 'market.png', None)
    assert len(pages) == 4
    for page in pages:
        with Image.open(page) as image:
            assert image.size == (1080, 1920)
            image.verify()


def test_market_reason_uses_only_supplied_fixture_numbers():
    class Snap:
        teams = {1: {'short_name': 'AAA'}, 2: {'short_name': 'BBB'}}
    rows = [{'gw': 11, 'opponent_id': 1, 'venue': 'H', 'attacking_fdr': 2.0},
            {'gw': 12, 'opponent_id': 2, 'venue': 'A', 'attacking_fdr': 4.0}]
    text = _market_reason(rows, 'attacking_fdr', Snap)
    assert 'AVG FDR 3.0' in text and 'EASIEST GW11 AAA(H)' in text and 'TOUGHEST GW12 BBB(A)' in text
    assert _market_reason(rows[:1], 'attacking_fdr', Snap) == ''
