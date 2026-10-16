# 🦁 FPL VORTEX — Telegram Bot

Independent, no-paid-API required Python + GitHub Actions automation. **This repository is new**: do not fork, edit or commit into the user's existing repositories.

## The schedule

One GitHub Actions workflow, eight Eastern-time publication slots plus eight 15-minute-later catch-up checks (DST-aware):

| ET | Content | Frequency |
|---|---|---|
| 6:30 AM | Elite under-owned scout pick | Daily |
| 8:00 AM | Player comparison | Daily |
| 10:00 AM | Official FPL player-status/news board | Daily |
| 12:00 PM | Confirmed official FPL price snapshot differences | Daily |
| 2:00 PM | Transfer comparison/decision | Daily |
| 4:00 PM | Captaincy showdown | **Only when tomorrow is an official FPL deadline** |
| 5:30 PM | Last completed gameweek review | Daily |
| 8:00 PM | Evening assists/creator watch | Daily |

Each successful delivery sends a downloadable 1536×864 branded PNG **document** to Telegram, with 5 short X-copy lines followed by exactly `#FPL #GW<number> #FPLVortex` in a code-formatted caption. The graphic contains sourced official FPL details. Telegram does **not** automatically publish on X.

## Important limits

- GitHub Actions scheduled jobs may be **delayed or dropped** even with the additional catch-up checks. This is a no-subscription best-effort system, not a guaranteed delivery SLA.
- This version renders fixed layouts with Pillow using the supplied **blank FPL VORTEX master background**; supplied sample cards are **design references only** and their historical statistics are never reused. Genuine AI image synthesis would need an additional, possibly paid, provider.
- The price tracker can confirm a **change between its own official snapshots**, but not the exact minute of the change. **Its first execution establishes a baseline** and does not invent movements.
- 10 AM board uses fresh dated FPL availability/news flags; it does **not** claim to aggregate every official club press conference. No flagged news means an honest no-update card.
- Player photos and club crests are downloaded opportunistically from the Premier League image CDN; if unavailable, text-only layouts remain usable. Respect image and logo rights for public redistribution.
- Telegram receives attachments and retains message history. No Google Drive storage or paid AI is used. 
- GitHub state is committed to **this new repository only**; concurrency prevents overlapping state pushes. Rare delivery-then-push failures can cause duplicates on retry; the delivery ledger reduces but does not eliminate this risk.
- An occasional missing FPL player-photo URL will **not** break rendering. Failed official data verification prevents a fabricated card and sends an alert if Telegram works.

## Setup (new repository only)

1. The standalone `mukundacity-glitch/Telegram-Bot` repository is created and this source has been uploaded. **No other repository is modified.**
2. Your repository is currently **public**. GitHub Actions Secrets are required for credentials. You can change it to private in repository settings if preferred.
3. In your Telegram app, open [@FPLVortexDailyBot](https://t.me/FPLVortexDailyBot) and tap **Start** or send `/start`.
4. GitHub → new repository → **Settings → Secrets and variables → Actions → New repository secret**. Set:
   - `TELEGRAM_BOT_TOKEN` = BotFather bot token (never post or commit it).
5. In the new repo **Actions → FPL VORTEX Telegram Daily → Run workflow**, select **discover**. In the run's **Deliver to Telegram** log, note your chat ID (bot must already have received `/start`).
6. Add the other Actions secret `TELEGRAM_CHAT_ID` with that chat ID. For a Telegram channel, add the bot as an administrator and use its numeric channel chat ID instead. 
7. Run workflow manually with **test**. Confirm you receive the Telegram test message.
8. Run workflow manually with **comparison**. Confirm the PNG is downloadable and its text is correct.
9. After both delivery tests succeed, create repository **Variable** `PUBLISH_ENABLED=true` under **Settings → Secrets and variables → Actions → Variables**. The sixteen schedule rules are defined but **won't post unless this variable is set**. To pause automatic publication set `PUBLISH_ENABLED=false`; manual tests remain available.

**Safety:** Auto-posting is disabled by default using `PUBLISH_ENABLED`; do not enable it before adding both secrets and confirming a manual test. GitHub Actions schedule timing is best effort.

## Assists background

The user's shared [Drive asset folder](https://drive.google.com/drive/folders/1BI4O_ZmxaXVNeGMS8ahkbLf4CUUWdA_a) includes `5.png`. A copy has **already been included** under `assets/assists/5.png` in this new starter package. It is used for the 8 PM evening/assists slide only. The master Drive file and existing repositories are unchanged. The renderer overlays the old footer credit with an accurate official-FPL attribution.

## Run tests locally

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

## Manual local run

After setting `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in your environment (never in a code file):

```bash
python -m vortex.bot --slot test
python -m vortex.bot --slot comparison
```

## Source verification

Data source: `https://fantasy.premierleague.com/api/bootstrap-static/`, `/fixtures/`, and `/event/{gw}/live/` for completed-GW returns. The `state/prices.json` baseline is updated only after the noon price report succeeds. Do not compare the `now_cost` against `cost_change_start` and claim it happened overnight; official day-over-day snapshots are required for that wording.