# FPL VORTEX automatic Telegram + Discord publishing

## Automatic schedule

The GitHub Actions workflow `.github/workflows/telegram-daily.yml` publishes with no
human intervention. The heartbeat is scheduled **in Eastern time**, not in a
hand-converted UTC offset:

```yaml
schedule:
  - cron: '43 5-22 * * *'
    timezone: "America/New_York"
  - cron: '13 6-22 * * *'
    timezone: "America/New_York"
```

`timezone` is an IANA zone, so GitHub's scheduler applies EST/EDT through the tz
database. The cron fields are therefore plain Eastern wall-clock hours: 18 `:43`
ticks (05:43–22:43) plus 17 `:13` ticks (06:13–22:13) = 35 ticks/day with a
30-minute maximum gap. No tick fires below the 05:30 opening or after 23:00.

A previous revision declared the heartbeat list in UTC
(`43 9-23,0-2 * * *` / `13 10-23,0-2 * * *`). Because a fixed UTC pair cannot
track DST, that schedule drifted by an hour at each transition and left the
first and last parts of the Eastern day uncovered.

The publisher enforces 05:30–23:00 America/New_York at **actual execution time**
via `zoneinfo` in `vortex/publishing_window.py`, so a late or delayed run can
never post outside the approved day.
GitHub scheduled runs are best-effort and may arrive late or be dropped. Missing a
specific cron occurrence is recovered at the next run using the current local time,
eligible edition slots, confirmed FPL evidence, and existing delivery receipts.

`python -m vortex.scheduled_dispatch` is the sole scheduled entrypoint. It
processes time-due autonomous editions, eligible special editions, the verified
news pipeline, one original legacy content slot, and fresh queued outbox assets.

## Delivery proof

Never treat a green GitHub Actions badge or uploaded artifact as proof of a
Telegram or Discord upload. Check the following:

- Workflow publish logs: `SCHEDULED PUBLISH REPORT`.
- The `new_posts` count and `status` in `state/scheduled_dispatch_status.json`.
- Telegram and Discord receipt IDs in `state/chatgpt_deliveries.json`,
  `state/news_deliveries.json`, and `state/deliveries.json`.
- The configured Telegram bot's actual destination is set by the GitHub
  Actions `TELEGRAM_CHAT_ID` secret. Never commit or paste its numeric value.

There is **no** guaranteed posting when no new verified information exists,
when official FPL data is unavailable, or when the publication window is closed.
A held or partial delivery is logged separately. Older unchanged content is
not resent just to make a green run.

## Manual publishing

Actions > FPL VORTEX Telegram Daily > Run workflow > choose an edition.
This is a **different** mode from the scheduled heartbeat: manual publishing
targets exactly one verified edition immediately and does not alter the
scheduled cron expressions. Manual also verifies both destination receipts.

## Troubleshooting

If Telegram's message ID exists but the expected channel is blank, check that
`TELEGRAM_CHAT_ID` points to the *channel* rather than a personal bot chat,
and the bot is a channel administrator with posting permission. A Telegram
API message ID proves acceptance to the configured chat, not which Telegram
chat the user is viewing.

## Telegram sendPhoto ReadTimeout recovery (no duplicate posts)

A Telegram **ReadTimeout** is not a confirmed rejection: the destination may
already display the photo even if GitHub never received its message ID.
Outbound photo requests now allow up to 120 seconds for the Telegram response.
If an upload still times out, the per-edition receipt is fenced with
`telegram_send_pending=true`; the confirmed Discord receipt is preserved and
future scheduled runs do **not** blindly resend that Telegram edition.
The workflow reports a held delivery until the exact Telegram message can be
reconciled by an operator. Do not manually clear this flag just to turn a run
green; first verify whether Telegram accepted the original photo. A deliberate
repost must use fresh verified evidence and a new identity.

The `schedule` triggers, 05:30–23:00 ET guard, active graphics, and
Telegram/Discord destinations are unchanged. Run pull-request tests for a
zero-publish dry check before merging.

## Reconcile an uncertain Telegram outbox photo

A bot's update feed cannot search older outgoing messages. Open the actual
Telegram chat in a signed-in client and check the time around
`telegram_uncertain_at`. Match the exact caption and graphic from the
outbox record at the original commit. A later edition with the same filename
or topic is insufficient evidence.

From **Actions → FPL VORTEX Telegram Daily → Run workflow**, select
`reconcile-telegram`. Enter the exact page key from
`state/chatgpt_deliveries.json` in the `post_id` JSON field, the history check
time including its offset in `history_checked_at`, and one outcome:

- `"outcome": "found"` with the Telegram `message_id` as a number and the
  original `delivered_at` including its offset. This only writes the receipt.
- `"outcome": "absent"` with the original full commit SHA in `revision`
  and the original outbox JSON basename in `outbox_file`. Use only after
  checking the complete relevant history in the channel and confirming it
  is the configured Telegram destination. The workflow validates the original
  edition and graphic before sending it once. Discord is not sent again.

If access to history is missing or the result is inconclusive, keep the record
pending. If the reconciliation send itself fails, check history again before
taking any action. The workflow records the one-time attempt before contacting
Telegram and leaves the receipt unresolved until it has a valid message ID.
