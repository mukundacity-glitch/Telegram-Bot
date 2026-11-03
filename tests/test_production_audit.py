"""Regression coverage for stale queued checkouts and receipt push races."""
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/telegram-daily.yml'


def test_scheduled_and_manual_runs_read_latest_receipts_and_full_rebase_history():
    checkout = WORKFLOW.read_text().split('      - name: Checkout isolated')[1].split('      - name: Set up Python')[0]
    assert 'ref: ${{ github.event.repository.default_branch }}' in checkout
    assert 'github.sha' not in checkout
    assert 'fetch-depth: 0' in checkout


def test_transport_receives_both_destination_secrets():
    step = WORKFLOW.read_text()
    for name in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'DISCORD_WEBHOOK_URL'):
        assert f'{name}: ${{{{ secrets.{name} }}}}' in step


def test_receipt_retry_preserves_confirmed_delivery_after_unrelated_main_push(tmp_path):
    def git(folder, *args):
        return subprocess.run(['git', '-C', str(folder), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    remote, source, worker = [tmp_path / n for n in ('remote.git', 'source', 'worker')]
    remote.mkdir(); source.mkdir()
    git(remote, 'init', '--bare', '--initial-branch=main')
    git(source, 'init', '--initial-branch=main')
    git(source, 'config', 'user.name', 'Regression')
    git(source, 'config', 'user.email', 'regression@example.invalid')
    (source / 'state').mkdir()
    (source / 'state/chatgpt_deliveries.json').write_text('{}\n')
    git(source, 'add', '.'); git(source, 'commit', '-m', 'baseline')
    git(source, 'remote', 'add', 'origin', str(remote))
    git(source, 'push', '-u', 'origin', 'main')
    subprocess.run(['git', 'clone', str(remote), str(worker)], check=True, capture_output=True)
    (source / 'code.py').write_text('# independent release\n')
    git(source, 'add', '.'); git(source, 'commit', '-m', 'independent release')
    git(source, 'push')
    receipt = {'topic': {'delivered': True, 'telegram_message_id': 154}}
    (worker / 'state/chatgpt_deliveries.json').write_text(json.dumps(receipt))
    tail = WORKFLOW.read_text().split('      - name: Preserve both-platform delivery receipts')[1].split('        run: |\n')[1]
    lines = []
    for line in tail.splitlines():
        if line and not line.startswith('          '):
            break
        lines.append(line[10:])
    script = '\n'.join(lines).replace('${{ github.ref_name }}', 'main')
    result = subprocess.run(['bash', '-e', '-c', script], cwd=worker,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'Receipt push race' in result.stdout
    assert json.loads(git(remote, 'show', 'main:state/chatgpt_deliveries.json')) == receipt
    assert git(remote, 'show', 'main:code.py') == '# independent release'


def test_recovered_154_does_not_erase_original_153():
    receipts = json.loads((ROOT / 'state/deliveries.json').read_text())
    assert receipts['2026-11-02:elite']['telegram_message_id'] == 153
    recovered = receipts['recovery:run41523140792:telegram154']
    assert recovered['telegram_message_id'] == 154
    assert 'discord_message_id' not in recovered


def test_valid_five_line_caption_reaches_telegram_unchanged(tmp_path, monkeypatch):
    from vortex.telegram import TelegramClient
    image = tmp_path / 'finished.png'
    image.write_bytes(b'x' * 600)
    client = TelegramClient(token='inert-test', chat_id='inert-test')
    calls = []
    def post(method, data, files):
        calls.append(data)
        return {'ok': True, 'result': {'message_id': 1}}
    monkeypatch.setattr(client, '_post', post)
    caption = 'GW10 decision\nVerified fact\nNext fixture\nHOLD\n#FPL #GW10 #FPLTips #FPLVortex'
    assert client.send_png(image, caption, 'Decision', 10) == 1
    assert calls[0]['caption'] == caption


def test_bookmaker_coordinate_medians_are_always_normalized():
    from datetime import datetime, timezone
    from vortex.odds_model import market_consensus
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    books = []
    for i, probs in enumerate(((.5, .251, .249), (.501, .25, .249), (.501, .251, .248))):
        books.append({'key': str(i), 'markets': [
            {'key': 'h2h', 'last_update': now.isoformat(), 'outcomes': [
                {'name': name, 'price': 1/(p*1.04)}
                for name, p in zip(('home', 'draw', 'away'), probs)]},
            {'key': 'totals', 'last_update': now.isoformat(), 'outcomes': [
                {'name': name, 'point': 2.5, 'price': 1/(p*1.04)}
                for name, p in (('Over', .55), ('Under', .45))]}]})
    result = market_consensus({'bookmakers': books}, 'home', 'away', now, str.lower)
    assert abs(sum(result[k] for k in ('home', 'draw', 'away')) - 1) < 1e-12


def test_differential_is_selected_by_verified_ownership():
    from dataclasses import replace
    from test_publication_contract import snap
    from vortex.chatgpt_task_editions import EDITIONS, generate_edition
    source = snap()
    base = source.players[0]
    people = [dict(base, id=i+1, code=100+i, element_type=3,
                   form=str(10-i), selected_by_percent=str(own))
              for i, own in enumerate((50, 40, 30, 8))]
    source = replace(source, players=people)
    edition = next(e for e in EDITIONS if e.kind == 'captain_differential')
    post = generate_edition(edition, source, source.fetched_at)
    assert post.cards[2].photo_code == 103


def test_missing_condensed_fonts_keep_requested_readable_size(monkeypatch):
    import vortex.matchup as layout
    monkeypatch.setattr(layout, 'FONT_BOLD', '/missing/condensed.ttf')
    font = layout._font(48)
    assert font.getbbox('GAMEWEEK')[3] - font.getbbox('GAMEWEEK')[1] >= 30
