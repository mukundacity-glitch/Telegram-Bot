# FPL VORTEX automatic Telegram + Discord publishing

## Automatic schedule

The GitHub Actions workflow `.github/workflows/telegram-daily.yml` publishes with no
human intervention. There are two UTC heartbeat triggers (GitHub's timezone-aware
cron recently fired hours late, leaving green runs outside the allowed window):

- `43 9-23,0-2 * * *` UTC (:43 checks).
- `13 10-23,0-2 * * *` UTC (:13 checks).

These provide a maximum 30-minute gap between permitted checks, spanning
05:43–21:43 America/New_York in both EST and EDT. GitHub may still delay
or drop a run; publication eligibility always uses actual Eastern time.

The publisher enforces 05:30–22:00 America/New_York at **actual execution time**.
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

The `schedule` triggers, 05:30–22:00 ET guard, active graphics, and
Telegram/Discord destinations are unchanged. Run pull-request tests for a
zero-publish dry check before merging.
