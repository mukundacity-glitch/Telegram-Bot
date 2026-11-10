# FPL VORTEX automatic Telegram + Discord publishing

## Automatic schedule

The GitHub Actions workflow `.github/workflows/telegram-daily.yml` publishes with no
human intervention. There are two compact DST-aware scheduled triggers:

- `43 5-21 * * *` America/New_York (hourly at :43, 05:43 to 21:43 ET).
- `13 6-21 * * *` America/New_York (hourly at :13, 06:13 to 21:13 ET).

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
