"""Numbering coverage for the complete permanent 53-graphic production catalog."""
from PIL import Image
import pytest
from vortex.graphic_numbers import CATALOG, ACTIVE_CATALOG, PRESS_REPORT_KEY, graphic_key, stamp
from vortex.autonomous_schedule import SLOTS, SPECIAL_EDITIONS
from vortex.schedule import SLOT_HOURS

def test_all_active_scheduled_editions_cover_exactly_53_graphic_numbers():
    keys = set(SLOT_HOURS)
    for slot in SLOTS:
        for weekday in range(7):
            for day in range(1, 8) if slot.edition == "weekly-analysis" else (None,):
                keys.add(graphic_key(slot.edition, weekday, day))
    keys.update(graphic_key(edition, 0) for edition in SPECIAL_EDITIONS)
    keys.update((PRESS_REPORT_KEY, "news-rotation-planner", "price-prediction"))
    assert None not in keys
    assert len(CATALOG) == len(set(CATALOG)) == 53
    assert len(ACTIVE_CATALOG) == 53
    assert keys == set(ACTIVE_CATALOG)
    assert graphic_key('striker-watch', 0) is None
    assert graphic_key('goalkeeper-striker-watch', 0, page=1) is None
    assert CATALOG[12] == PRESS_REPORT_KEY
    assert CATALOG[15] == "price-prediction"
    assert CATALOG[-1] == "gw-key-players"

@pytest.mark.parametrize("key", ACTIVE_CATALOG)
def test_every_catalog_number_is_visible_and_idempotent(key, tmp_path):
    source = tmp_path / "source.png"
    target = tmp_path / "stamped-copy.png"
    Image.new("RGB", (640, 360), "#301030").save(source)
    stamp(source, key, required=True)
    with Image.open(source) as im:
        assert im.size == (640, 360)
        assert im.info["vortex_graphic_number"] == f"{CATALOG.index(key)+1}/53"
        # Bright cyan number occupies the reserved header, not the content.
        assert any(g > 200 and b > 200 for r,g,b in im.crop((460, 0, 640, 32)).getdata())
    before = source.read_bytes()
    assert stamp(source, key, target, required=True) == target
    assert source.read_bytes() == target.read_bytes() == before

def test_unregistered_scheduled_graphic_fails_closed(tmp_path):
    source = tmp_path / "unknown.png"
    Image.new("RGB", (640, 360)).save(source)
    with pytest.raises(ValueError, match="No permanent graphic number"):
        stamp(source, "unknown-edition", required=True)
