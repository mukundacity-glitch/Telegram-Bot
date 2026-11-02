# 🦁 FPL VORTEX — Telegram Bot

Independent, no-paid-API required Python + GitHub Actions automation. **This repository is new**: do not fork, edit or commit into the user's existing repositories.

## Automatic Telegram publishing — enabled

**You do not have to click "Run workflow"** to start automatic publishing.
GitHub Actions fires all 13 `schedule` entries on the default `main` branch.
The manual workflow dropdown defaults to `auto`, not `test`. Clicking manual
`auto` safely confirms the schedule configuration **without sending a message**;
actual publication happens when a scheduled cron event triggers.

Scheduled jobs are explicitly enabled; a stale `PUBLISH_ENABLED=false` repository
variable can no longer silently prevent publishing. To stop scheduled posts,
disable **FPL VORTEX Telegram Daily** from the repository's **Actions** tab.
The 15-minute backup checks reuse the same scheduled-delivery ledger, so they
cannot intentionally publish a duplicate after a successful first delivery.

GitHub's cron service can still queue, delay, or occasionally drop scheduled
runs. A scheduled job must successfully fetch official FPL data and verified
images, pass its deadline checks, and send to Telegram; no setting can guarantee
delivery if those prerequisites fail. The 07:00 bookmaker figures remain N/A
until `THE_ODDS_API_KEY` and independent market odds are available.

## The schedule

One **existing** GitHub Actions workflow, thirteen Eastern-time publication slots plus thirteen 15-minute-later catch-up checks (DST-aware). No new task or separate automation is created:

| ET | Content | Frequency |
|---|---|---|
| 6:30 AM | Elite under-owned scout pick | Daily |
| **7:00 AM** | **NEW — All 20 teams projected goals & clean-sheet board** | Daily |
| 8:00 AM | Player comparison | Daily |
| 9:00 AM | Four next-GW buy candidates (firm or conditional) | Daily |
| 10:00 AM | Official FPL player-status/news board | Daily |
| **11:00 AM** | **NEW — Single-team attack, defence & FPL decision desk** | Daily |
| 12:00 PM | Confirmed official FPL price snapshot differences | Daily |
| 2:00 PM | Transfer comparison/decision | Daily |
| **3:00 PM** | **NEW — Positional GK/DEF/MID/FWD transfer suggestions** | Daily |
| 4:00 PM | Captaincy showdown | Daily |
| 5:30 PM | Last completed gameweek review | Daily |
| 6:30 PM | Four next-GW sell candidates (firm or conditional) | Daily |
| 8:00 PM | Evening assists/creator watch | Daily |

Each successful delivery sends a 1536×864 branded PNG to Telegram with five short X-copy lines. The **existing ten posts** retain their exact existing hashtags (`#FPL #GW<number> #FPLVortex`); **the three new editions** use four hashtags (`#FPL #GW<number> #FPLVortex #PremierLeague`). The graphic contains sourced official FPL details. Telegram does **not** automatically publish on X.

## Next-GW recommendations and metric periods

The two new graphics target the **first future FPL deadline event**. They identify the most recently **confirmed completed** review GW by checking the official event completion marker **and every assigned fixture**, rather than subtracting one from the next event. During an unfinished round the review explicitly notes that the prior round remains live; postponed fixtures prevent premature completion labels.

The next-GW BUY/SELL research starts with the official `transfers_in_event` and `transfers_out_event` counters, clearly labeled **event-to-date at the snapshot**. These counters are not 24-hour movements and are not treated as evidence of managers' motives. Four names appear, but those without a defensible strong verdict are explicitly **WATCHLIST**. Only the next gameweek's official fixtures enter the FDR table; a blank is marked and double fixtures are individually shown. No automatic transfer or points hit is executed.

Season counts, points from the last three **verified completed** gameweeks, and official current playing status are kept separate. Outfield defensive contributions are **actions**, not automatic points: the award is +2 points per match at 10 (DEF) or 12 (MID/FWD) qualifying actions, never to GK. GK save points are calculated per fixture in groups of three saves, not from season totals. If a required metric is absent it is N/A, never an assumed zero. Featured authentic Premier League portraits and crests are mandatory for the two new graphics, otherwise the publish fails closed.

The default Telegram copy and `#FPL #GW<number> #FPLVortex` hashtag line remain unchanged. Use workflow dispatch `preview-buy` or `preview-sell` to send a **preview to Telegram** without writing the scheduled-delivery ledger; use normal `buy`/`sell` only when intentional repeat posting is desired. All source retrieval timestamps display **America/New_York**.

## Three additional blue-master editions (added November 2, 2026)

- **07:00 ET · Projected Goals & Clean Sheets.** All confirmed next-event official FPL fixtures, with five matchups on the left and five on the right for a standard 10-match, 20-club gameweek. Each team has its official club crest and its OWN market-implied goals / opponent-nil clean-sheet probability. No matchup is invented; irregular blank/double events report the true number of fixtures instead. Numbers are calculated only from **current and independently corroborated sportsbook 0.5 team-goal Over/Under prices**, de-vigged across at least two bookmakers using a Poisson-equivalent conversion. Figures are model-based market forecasts, not actual FPL points or published bookmaker xG. Without credible fresh markets, projected goals and CS% are **N/A** (the verified official fixtures and crests can still publish).
- **11:00 ET · Team Attack & Defence.** Dynamic next-GW favourable opponent selection, rotating the featured club among high-potential fixtures to avoid identical daily editions. Display the last up to nine FINISHED league-match goals for and against from the official FPL fixture scores, not unverified xG. Show three available FPL assets with verified photos, crests, season minutes/form and next-GW fixture FDR.
- **15:00 ET · Transfer Suggestions.** Four clearly different goalkeeper/defender/midfielder/forward one-GW comparisons. Official event-to-date transfer-out/in counts, price, form, minutes, status and next-GW fixture FDR drive conservative BUY/HOLD/SELL-to-BUY decisions. A swap only appears if a same-position, near-budget alternative has stronger verified indicators. There are no invented expected-point figures and no automatic transfers or points hits.

All three use the unchanged FPL VORTEX **blue stadium master** plus original portrait-and-crest layouts. The references are **design inspiration only**, and their numbers/teams are never copied.

### Optional real bookmaker data

To enable odds, set an Actions secret named `THE_ODDS_API_KEY` with a valid [The Odds API](https://the-odds-api.com/) key supporting `soccer_epl` **event odds** and `alternate_team_totals` or `team_totals` markets. Do not store the key in source or chat messages. The 07:00 run checks the API for exact matching matchups and accurate kickoff times, and accepts a metric **only** when 2+ different bookmaker records each provide valid Over AND Under 0.5 goal odds updated within 12 hours. Missing credentials, bookmaker offerings, unavailable fixtures, stale quotes or API failures give **N/A**; the FPL API itself does **not** include sportsbook odds. This optional odds provider can incur API usage charges.

New manual preview choices: `preview-projections`, `preview-team_analysis`, `preview-transfer_suggestions`. These send explicitly labeled previews to Telegram without modifying the scheduled delivery ledger. All three scheduled posts use the existing serialized queue and GW-aware duplicate protection; their generation rechecks the FPL deadline before sending.

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
9. **Automatic Telegram publishing is ON by default.** You never need to press **Run workflow**. To stop posts, disable the existing **FPL VORTEX Telegram Daily** workflow under **Actions**; re-enable the same workflow to resume. A stale `PUBLISH_ENABLED` variable no longer blocks the scheduled publisher.

**Warning:** The workflow is active. Telegram secrets are already connected in this deployment. All thirteen Eastern-time schedules run daily, including the 4 PM captaincy card. Schedules are best effort.

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

Additional layouts are implemented in `vortex/premium.py` for `news`, `prices`, `captaincy`, `review`, `elite`, and `evening`, with `transfer` sharing the two-player comparison layout. All feature the same typography, high-contrast cyan/gold section headers, portrait-led player cards, visible club badges, official FPL metrics, result-focused verdict strips, and safe no-update states. The module tests include full rendering and required-image validation for every slot.

To preview any new template on demand without affecting the once-per-day ledger, use Actions → FPL VORTEX Telegram Daily → Run workflow and choose `preview`, `preview-news`, `preview-transfer`, `preview-prices`, `preview-captaincy`, `preview-review`, `preview-elite`, or `preview-evening`.

**Manual normal runs:** explicitly selecting `comparison`, `news`, etc. sends a new post even if one already went out today. **Automatic scheduled runs:** deduplicated by the Eastern calendar date and slot. This avoids silently ignoring the user's manual tests while preventing routine duplicate scheduled posts.
