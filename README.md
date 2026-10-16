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

1. Create an **empty private** GitHub repository named `Telegram-Bot` in the `mukundacity-glitch` account. (Display title: **Telegram Bot**.) Do not fork an existing project.
2. Upload the contents of this directory to that new repository, including `.github/workflows/telegram-daily.yml`, `vortex/`, `state/`, `tests/`, and `assets/references/`.
3. In your Telegram app, open [@FPLVortexDailyBot](https://t.me/FPLVortexDailyBot) and tap **Start** or send `/start`.
4. GitHub → new repository → **Settings → Secrets and variables → Actions → New repository secret**. Set:
   - `TELEGRAM_BOT_TOKEN` = BotFather bot token (never post or commit it).
5. In the new repo **Actions → FPL VORTEX Telegram Daily → Run workflow**, select **discover**. In the run's **Deliver to Telegram** log, note your chat ID (bot must already have received `/start`).
6. Add the other Actions secret `TELEGRAM_CHAT_ID` with that chat ID. For a Telegram channel, add the bot as an administrator and use its numeric channel chat ID instead. 
7. Run workflow manually with **test**. Confirm you receive the Telegram test message.
8. Run workflow manually with **comparison**. Confirm the PNG is downloadable and its text is correct.
9. Once testing succeeds, leave GitHub Actions enabled. The sixteen schedule rules (eight primary, eight backup) are in `.github/workflows/telegram-daily.yml` and take effect when present on the default branch. To stop publishing, disable that single workflow in the GitHub Actions interface.

**Warning:** When you first upload the workflow, the cron schedule becomes active. Set the two secrets promptly; otherwise early scheduled jobs will fail until configured.

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

## October 16 comparison design (reference-faithful)

The **8:00 AM player-vs-player** renderer uses `vortex/matchup.py`, which recreates the supplied two-column reference at **1536 × 864**: portrait-led cyan/gold panels, each club crest, price, points, form, goals, assists, minutes, clean sheets, bonus, three opponent crests and FDR-colored fixture chips, and a bottom verdict. Numbers are populated from **live official FPL** player and fixture records, not pixels or text from the example design.

Player portraits and team crests are requested from public Premier League CDNs. Only if a matching live portrait is unavailable, the renderer may use a portrait cutout **from the user-supplied example** for the explicitly named players De Cuyper and Tarkowski (`assets/players/*.webp.b64`). The rest of the roster never receives an unrelated fallback face. A missing featured portrait or required club crest aborts publishing that graphic; the bot will report the failure instead of silently sending a card without images. Missing upcoming fixtures display `NO FIXTURE` instead of fictional pairings.

The mock design preview contains illustrative sample values and is **not** proof of current live stats. The `comparison` manual workflow should be run again, and its delivered PNG visually checked, before enabling `PUBLISH_ENABLED`.
**Same-day validation:** use Actions → FPL VORTEX Telegram Daily → Run workflow → `preview` to send a fresh 8:00 AM comparison without writing to `state/deliveries.json`. The regular `comparison` slot remains deduplicated once per Eastern date. Preview is manual-only and never enables recurring publishing.
