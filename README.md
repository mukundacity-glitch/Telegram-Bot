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
| 4:00 PM | Captaincy showdown | Daily |
| 5:30 PM | Last completed gameweek review | Daily |
| 8:00 PM | Evening assists/creator watch | Daily |

Each successful delivery sends a downloadable 1536×864 branded PNG **document** to Telegram, with 5 short X-copy lines followed by exactly `#FPL #GW<number> #FPLVortex` in a code-formatted caption. The graphic contains sourced official FPL details. Telegram does **not** automatically publish on X.

## Important limits

- GitHub Actions scheduled jobs may be **delayed or dropped** even with the additional catch-up checks. This is a no-subscription best-effort system, not a guaranteed delivery SLA.
- This version renders fixed layouts with Pillow using the supplied **blank FPL VORTEX master background**; supplied sample cards are **design references only** and their historical statistics are never reused. Genuine AI image synthesis would need an additional, possibly paid, provider.
- The price tracker can confirm a **change between its own official snapshots**, but not the exact minute of the change. **Its first execution establishes a baseline** and does not invent movements.
- 10 AM board uses fresh dated FPL availability/news flags; it does **not** claim to aggregate every official club press conference. No flagged news means an honest no-update card.
- Featured player photos and club crests are mandatory. If a photo or required crest cannot be verified/downloaded, that graphic does not publish; the bot attempts to send a Telegram failure alert. Respect image and logo rights for public redistribution.
- Telegram receives attachments and retains message history. No Google Drive storage or paid AI is used. 
- GitHub state is committed to **this new repository only**; concurrency prevents overlapping state pushes. Rare delivery-then-push failures can cause duplicates on retry; the delivery ledger reduces but does not eliminate this risk.
- Missing mandatory images stop the affected graphic rather than producing a half-empty poster. Data-source failures also fail closed and attempt an alert. No external service can guarantee delivery, particularly when GitHub Actions scheduled runs are delayed.

## Setup (new repository only)

1. Existing production repository: `mukundacity-glitch/Telegram-Bot` (public). Do not publish Telegram tokens or personal data in tracked files.
2. All current Python sources, branded assets, and workflow configuration are already deployed to the default branch.
3. In your Telegram app, open [@FPLVortexDailyBot](https://t.me/FPLVortexDailyBot) and tap **Start** or send `/start`.
4. GitHub → new repository → **Settings → Secrets and variables → Actions → New repository secret**. Set:
   - `TELEGRAM_BOT_TOKEN` = BotFather bot token (never post or commit it).
5. In the new repo **Actions → FPL VORTEX Telegram Daily → Run workflow**, select **discover**. In the run's **Deliver to Telegram** log, note your chat ID (bot must already have received `/start`).
6. Add the other Actions secret `TELEGRAM_CHAT_ID` with that chat ID. For a Telegram channel, add the bot as an administrator and use its numeric channel chat ID instead. 
7. Run workflow manually with **test**. Confirm you receive the Telegram test message.
8. Run workflow manually with **comparison**. Confirm the PNG is downloadable and its text is correct.
9. **Automatic Telegram publishing is ON by default** when the Actions workflow is enabled. To pause scheduled posts without disabling manual testing, set repository Actions Variable `PUBLISH_ENABLED=false`. Setting it back to `true` or deleting it resumes publishing.

**Warning:** The workflow is active. Telegram secrets are already connected in this deployment. All eight Eastern-time schedules run daily, including the 4 PM captaincy card. Schedules are best effort.

## Assists background

The user's shared [Drive asset folder](https://drive.google.com/drive/folders/1BI4O_ZmxaXVNeGMS8ahkbLf4CUUWdA_a) includes `5.png`, preserved under `assets/assists/5.png` for reference. The evening graphic deliberately uses the same blank premium broadcast master as the other seven slots, because `5.png` contains dated embedded copy that would otherwise appear underneath new live data.

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

The mock design preview contains illustrative sample values and is **not** proof of current live stats.

## All eight premium layouts and manual preview

Seven additional layouts are implemented in `vortex/premium.py` for `news`, `prices`, `captaincy`, `review`, `elite`, and `evening`, with `transfer` sharing the two-player comparison layout. All feature the same typography, high-contrast cyan/gold section headers, portrait-led player cards, visible club badges, official FPL metrics, result-focused verdict strips, and safe no-update states. The module tests include full rendering and required-image validation for every slot.

To preview any new template on demand without affecting the once-per-day ledger, use Actions → FPL VORTEX Telegram Daily → Run workflow and choose `preview`, `preview-news`, `preview-transfer`, `preview-prices`, `preview-captaincy`, `preview-review`, `preview-elite`, or `preview-evening`.

**Manual normal runs:** explicitly selecting `comparison`, `news`, etc. sends a new post even if one already went out today. **Automatic scheduled runs:** deduplicated by the Eastern calendar date and slot. This avoids silently ignoring the user's manual tests while preventing routine duplicate scheduled posts.
