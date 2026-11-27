"""Retired individual FPL NEWS is rejected even if manually constructed."""
import pytest
from vortex.content import Card, Content, generate
from vortex.publish_checks import render_checked
from vortex.schedule import resolve_slot
from test_publication_contract import snap

def test_retired_player_news_has_no_manual_generation_or_preview(tmp_path):
    from datetime import datetime, timezone
    now = datetime(2026, 11, 27, tzinfo=timezone.utc)
    for slot in ("news", "preview-news"):
        with pytest.raises(ValueError):
            resolve_slot(slot, None, now)
    with pytest.raises(ValueError):
        generate("news", snap(), now, {})
    for kind in ("news", "news_profile"):
        article = Content(kind, "Retired", "", (Card("Example","ARS","",()),), "", "", "", 12, "")
        with pytest.raises(ValueError, match="retired"):
            render_checked(article, snap(), tmp_path/"retired.png")
    assert not (tmp_path/"retired.png").exists()
