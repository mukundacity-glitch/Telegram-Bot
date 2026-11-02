"""Same-workflow schedule migration must never change old primaries or create jobs."""
from pathlib import Path
import re
from vortex.chatgpt_task_editions import CRONS
from vortex.schedule import SLOT_CRONS

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/telegram-daily.yml"


def test_all_four_task_schedules_are_present_in_one_existing_workflow():
    yml = WORKFLOW.read_text(encoding="utf-8")
    scheduled = re.findall(r"^\s+- cron: '([^']+)'", yml, flags=re.MULTILINE)
    assert len(scheduled) == len(set(scheduled))
    for cron in CRONS:
        assert cron in scheduled, f"Missing former ChatGPT edition {cron}"
    for cron in SLOT_CRONS:
        assert cron in scheduled, f"Original Telegram scheduled trigger {cron} removed"
    assert "FPL_PORTED_TASKS_ENABLED" in yml
    assert "DUAL_PUBLISH_ENABLED" in yml
    assert "FPL_ENRICHED_VISUALS_ENABLED" in yml
    assert "python -m vortex.task_publisher" in yml
    assert "state/ported_task_versions.json" in yml
    assert yml.count("  publish:\n") == 1
    assert "  ported-task:" not in yml
    assert yml.count("name: Publish original four ChatGPT editions to both platforms") == 1


def test_new_task_only_crons_are_excluded_from_legacy_slot_dispatch():
    yml = WORKFLOW.read_text(encoding="utf-8")
    for cron in ("0 6 * * *", "30 7 * * *", "30 12 * * *",
                 "45 15 * * *", "0 19 * * *", "30 19 * * *"):
        assert cron not in SLOT_CRONS
        assert f'"{cron}"' in yml
