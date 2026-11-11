"""The user-authorized Nov 3 migration uses one transport for all tasks."""
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/telegram-daily.yml'

def test_all_four_complete_task_specs_copied_and_primary_hours_do_not_overlap():
    tasks = json.loads((ROOT / 'docs/chatgpt-task-specifications.json').read_text())['tasks']
    active = [t for t in tasks if t['is_enabled']]
    assert len(active) == 5
    hours = []
    for task in active:
        assert len(task['prompt']) > 3000
        assert 'outbox' in task['prompt'] and 'BOTH Telegram and Discord' in task['prompt']
        rrule = task['schedule'].split('BYHOUR=')[1].split(';')[0]
        hours.extend(map(int, rrule.split(',')))
    assert len(hours) == len(set(hours))
    assert all(5 <= h < 20 for h in hours)

def test_only_one_shared_publisher_and_no_legacy_scheduled_sender():
    source = WORKFLOW.read_text()
    assert source.count('  publish:\n') == 1
    assert "cron: '43 9-23,0-2 * * *'" in source and "cron: '13 10-23,0-2 * * *'" in source
    assert 'python -m vortex.scheduled_dispatch' in source
    assert 'python -m vortex.bot' not in source
    assert 'python -m vortex.task_publisher' not in source
    assert 'TELEGRAM_BOT_TOKEN' in source and 'DISCORD_WEBHOOK_URL' in source
    assert "FPL_PUBLISH_WINDOW_ENFORCED: ${{ !(" in source
    assert "FPL_MANUAL_PUBLISH:" in source
