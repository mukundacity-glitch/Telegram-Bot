from datetime import datetime, timedelta, timezone
import pytest
from vortex.research_gap import verified_gap

NOW = datetime(2026, 11, 27, 18, tzinfo=timezone.utc)

@pytest.mark.parametrize("elapsed, expected", [(179, False), (180, True), (181, True), (-1, False)])
def test_minimum_elapsed_research_gap(elapsed, expected):
    assert verified_gap((NOW - timedelta(minutes=elapsed)).isoformat(), NOW) is expected

@pytest.mark.parametrize("stamp", [None, "", "invalid", "2026-11-27T14:00:00"])
def test_invalid_research_evidence_fails_closed(stamp):
    assert not verified_gap(stamp, NOW)
