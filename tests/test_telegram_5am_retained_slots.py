"""Protect existing Telegram slots while adding a receipt-safe 05:00 early check.

The user's existing 06:00-20:00 schedule and four ChatGPT streams
must not be deleted, renamed or silently moved.
"""
from datetime import datetime, timezone
from pathlib import Path
import re

from vortex.chatgpt_task_editions import CRONS, EDITIONS, due_editions
from vortex.task_publisher import _get_editions, _topic

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/telegram-daily.yml"

# Frozen snapshot of ORIGINAL main-branch scheduled cron entries before this
# feature was added. Every one must remain present and unchanged.
ORIGINAL_CRONS = {
    "0 6 * * *", "30 7 * * *", "30 12 * * *", "45 15 * * *",
    "0 19 * * *", "30 19 * * *", "30 6 * * *", "0 7 * * *",
    "0 8 * * *", "0 9 * * *", "0 10 * * *", "45 10 * * *",
    "0 11 * * *", "0 12 * * *", "0 13 * * *", "0 14 * * *",
    "0 15 * * *", "0 16 * * *", "30 17 * * *", "30 18 * * *",
    "0 20 * * *", "45 6 * * *", "15 7 * * *", "15 8 * * *",
    "15 9 * * *", "15 10 * * *", "15 11 * * *", "25 11 * * *",
    "15 12 * * *", "15 13 * * *", "15 14 * * *", "15 15 * * *",
    "15 16 * * *", "45 17 * * *", "45 18 * * *", "15 20 * * *",
}


def test_user_requested_window_replaces_older_overnight_triggers():
    workflow = WORKFLOW.read_text()
    crons = re.findall(r"- cron: '([^']+)'", workflow)
    assert crons == ['43 5-21 * * *', '13 6-21 * * *']
    assert 'timezone: America/New_York' in workflow
    assert 'python -m vortex.scheduled_dispatch' in workflow
    assert workflow.count("  publish:\n") == 1


def test_5am_and_backup_reuse_exact_task1_6am_receipt_topic():
    now = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)  # 5 AM EST
    early = due_editions(now, "0 5 * * *")
    backup = due_editions(now, "15 5 * * *")
    ordinary = due_editions(now, "0 6 * * *")
    assert len(early) == len(backup) == len(ordinary) == 1
    assert early[0] == backup[0] == ordinary[0]
    assert _topic(early[0], 10) == _topic(ordinary[0], 10)
    assert _get_editions(now, "0 5 * * *", None) == ordinary
    assert {e.task for e in EDITIONS} == {"task1", "task2", "three_daily", "press_news"}
    assert len(EDITIONS) == len(CRONS) == 12


def test_no_legacy_5am_double_publication():
    workflow = WORKFLOW.read_text()
    assert 'python -m vortex.scheduled_dispatch' in workflow
    assert 'python -m vortex.bot' not in workflow
    assert 'python -m vortex.task_publisher' not in workflow
