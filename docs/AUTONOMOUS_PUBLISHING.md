# GitHub autonomous publishing

The existing `telegram-daily.yml` workflow now fetches official FPL evidence,
selects content, renders PNGs, writes captions with exactly four hashtags, and
publishes through the existing Telegram and Discord clients. Scheduled ChatGPT
execution and an OpenAI key are not needed by this engine. Full historical task
requirements remain in `chatgpt-task-specifications.json`.

## Schedule and preservation

All clocks use **America/New_York**, including DST. Public sends are allowed
from 05:30 inclusive until 22:00 exclusive. GitHub schedules can be delayed;
the runtime window check also applies to delayed jobs.

| Time ET | Additional edition |
|---|---|
| 05:20 | Availability and transfer decisions |
| 06:20 | Six under-10%-owned players, official FPL ep_next ranking, minimal 3×2 graphic |
| 07:20 | Four fixture targets, verified EO required |
| 08:20 | Form and reliable-minute targets |
| 09:20 | Four midfielders in ONE graphic |
| 10:20 | Changed verified press/availability news |
| 11:20 | Captain and differential comparison |
| 12:20 | Two attacking and two defensive team targets |
| 13:20 | Squad surgery, actual recent manager question evidence |
| 14:20 | Transfer market and team news |
| 15:20 | Market verdicts: four position slides, one caption |
| 16:29 | Deadline Watch: mainstream captain, two differentials and official availability risks |
| 17:20 | Confirmed price changes only |
| 18:20 | Changed verified press/availability news |
| 19:20 | VORTEX captain and two alternatives |

Original legacy cron strings remain enabled. Existing verified news checks use
:05, additional editions :20, conditional gameweek specials :35, and outbox
retries :50. Cron strings do not overlap, and the shared concurrency group
serializes delayed runs. Conditional specials cover captaincy, value, start/bench,
final availability and post-completion market trends. No code in this workflow
deletes audience messages or ChatGPT tasks.

Telegram and Discord use independently persisted receipts. Four midfielders
always produce one combined 1920x1080 graphic. Four-slide market posts use a
Telegram media group and one Discord message, each with one caption. A successful
destination is skipped on a partial retry. An album with a lost or ambiguous
receipt is held for reconciliation instead of blindly resending. Existing posts
and journals are kept.

## Data and graphics

Prices, clubs, availability, ownership, actual returns and fixture H/A are
refreshed from official bootstrap, fixtures and element-summary endpoints.
Minute eligibility means at least 70 minutes in each of the last three completed
appearances; this is evidence, not a guarantee of future starts. The editorial
ranking uses actual recent points/xGI and official FDR; it is not forecast xPts.
Forecasts are estimates, not guaranteed returns.

Official portraits and authentic club crests are used first. A reviewed, labeled
AI illustration already in `assets/ai-portraits/manifest.json` may be used as a
fallback. Runtime AI generation is not configured. Missing portraits with no
reviewed fallback hold the edition and queue the player ID for review.

## Required model/EO feed

Set repository variable `FPL_EDITORIAL_MODEL_URL` to a reviewed HTTPS endpoint
on `fplvortex.onrender.com` or `raw.githubusercontent.com`. Merely fetching a
file does not refresh its calculation age. The feed must contain:

```json
{
  "generated_at": "ACTUAL_MODEL_CALCULATION_TIME_WITH_TIMEZONE",
  "gw": 10,
  "model_version": "VERSION_OF_DISCLOSED_MODEL",
  "methodology_url": "https://YOUR_MODEL_METHODOLOGY",
  "eo_meta": {
    "gw": 10,
    "population": "ACTUAL_COHORT",
    "methodology": "CAPTAINCY_WEIGHTED_EFFECTIVE_OWNERSHIP_METHOD"
  },
  "teams": {
    "OFFICIAL_TEAM_ID": {
      "fixtures": [{
        "fixture_id": 123,
        "gw": 10,
        "opponent_id": 2,
        "venue": "H",
        "attacking_fdr": 2.5,
        "defensive_fdr": 3.0,
        "projected_goals": 1.4,
        "clean_sheet_pct": 30.0
      }]
    }
  },
  "players": {
    "OFFICIAL_PLAYER_ID": {
      "eo": 25.0,
      "fixtures": [{"fixture_id": 123, "gw": 10, "xpts": 4.5}]
    }
  }
}
```

This is a schema illustration, **not real data to publish**. Supply every official
next-five-gameweek fixture, including doubles; exact ID/GW/opponent/venue joins
are validated. Custom FDR must be numeric 1–5, projected goals 0–12,
clean-sheet percent 0–100, per-fixture xPts 0–40, and EO 0–300. Feed calculation
age must be at most three hours and match the upcoming official GW. Imported
benchmark CSVs without verified calculation freshness are rejected. Ordinary
selected-by ownership is never relabeled EO.

## Verification and remaining migration gates

Run `python -m pytest -q`. For a local read-only audit, use the same rendering
configuration as the workflow:

```sh
FPL_ENRICHED_VISUALS_ENABLED=true FPL_TELEGRAM_HANDLE=@FPLVortexDailyBot FPL_DISCORD_HANDLE=@fplvortex python -m vortex.autonomous_runner --audit-all
```
Audit art is isolated under `output/autonomous-audit/`; audit never queues a
production post or changes price baselines. Download the workflow artifact for
its report and PNGs. Manual `slot=audit` runs this same read-only audit.

The 2026-11-03 official-data audit rendered the standard editions and conditional
specials and checked press news. Four editions held for the missing verified
feed: fixture-targets, four-team-targets, market-verdict and value-board. The
reachable imported GW7 benchmark was deliberately rejected as current GW10
forecast evidence. These holds are data requirements, not permission requests.

Do not delete the ChatGPT tasks based on compilation or a green unit test alone.
The audit must pass all required input gates, and actual production receipts
must confirm BOTH destinations. `generation_audit_passed` reports the first gate;
`safe_to_delete_chatgpt_tasks` remains false until migration is explicitly
reviewed with production evidence. Do not run both ChatGPT generation and GitHub
generation for the same edition: keep pending ChatGPT tasks on standby during
cutover, without deleting them until the remaining feed and delivery gates pass.

Release commits with `[FPL-AUTONOMOUS]` request one real autonomous captain
edition inside the window. Rollback is a code revert to the preceding workflow;
retain all delivery journals and audience posts when reverting.


## Verified release, 2026-11-03

PR #21 added autonomous generation; PR #23 corrected delivery-time freshness
validation. GitHub Actions run [41736609285, attempt 2](https://github.com/mukundacity-glitch/Telegram-Bot/actions/runs/41736609285)
passed **228 tests**, generated the actual GW10 captain PNG and four-hashtag
caption, and confirmed Telegram message **172** and Discord message
**1567315557441871992**. Both receipts are persisted for immutable version
`fe20101bf013359e7daf`. The generation report records
`generation_owner=github-actions` and `chatgpt_required=false`.

The journal's historical `chatgpt:` identity prefix is retained so older receipts
continue to prevent duplicates; that prefix does not describe the current
generation engine. Existing audience posts were preserved.

Full migration is still gated on the verified model/EO feed in
[issue #22](https://github.com/mukundacity-glitch/Telegram-Bot/issues/22).
Do not delete the ChatGPT tasks yet.


## Deadline Watch replacement

The former 16:20 press-update edition is replaced by `deadline-watch` at
**16:29 America/New_York** in the same workflow. The 10:20 and 18:20 press
checks and original verified news schedule remain. Existing Telegram/Discord
messages are not deleted. The uploaded four-column blue/gold comparison style
is retained, with a dynamic GW DEADLINE WATCH heading and official deadline
in New York and UK time. One landscape PNG and one caption (four hashtags)
are delivered to both platforms.

The mainstream captain is the most-owned available attacker within the
verified-minute shortlist; two lower-owned alternatives use observed recent
form and official fixtures, including a defender when eligible. Defender
contrasts prioritise observed season xGI per 90 rather than clean-sheet points. This does not
claim effective ownership, captaincy popularity or rank neutrality. Flagged
players and zero-chance candidates cannot be captain picks. Injury/status
watch players, current clubs, chance fields and news come from the current
official snapshot. No fixed player names, prices, deadlines, return dates,
transfer counts, or opponent xGC ranks are copied from the example post.


## 06:20 six-player update

Only the `rank-booster` edition changes. It selects exactly six available
players with selected_by_percent strictly below 10 and positive finite official
`ep_next`, across the full bootstrap player list. The official `is_next` event
must match the upcoming deadline GW, so a rollover cannot relabel forecasts. Raw ep_next sorts descending;
mean official next-GW FDR breaks ties, followed by minutes and official ID.
The source forecast is never relabeled VORTEX xPts or multiplied again for a
double gameweek. A blank, flagged player, zero-chance player, missing forecast,
or unverified fixture difficulty is excluded. Fewer than six candidates holds
the edition; high-owned players are never added to fill it.

Official element summaries add actual recent points/minutes and role metrics.
The image uses a restrained dark palette, three cards above and three below,
with portraits, badges, FPL forecast, ownership, price, form, season minutes/points,
recent returns, position-specific stats and next-GW opponents/FDR. Missing
optional history uses a dash, never a fabricated zero. All other edition
schedules and graphics remain unchanged.

## Schedule and catch-up (05:30–22:00 America/New_York)

Posting window: 05:30 inclusive to 22:00 exclusive, Eastern time (DST handled).
Telegram and Discord receive every edition together; each platform keeps its own receipt.

| ET | Edition | ET | Edition |
|---|---|---|---|
| 05:30 | availability-transfer-decisions | 14:30 | transfer-market-team-news |
| 06:30 | rank-booster | 15:30 | market-verdict |
| 07:30 | fixture-targets | 16:30 | deadline-watch |
| 08:30 | form-minutes-targets | 17:30 | confirmed-price-changes |
| 09:30 | four-midfielders | 19:00 | verified-press-availability |
| 10:30 | verified-press-availability | 21:00 | vortex-captain |
| 11:30 | captain-differential | | |
| 12:30 | four-team-targets | | |
| 13:30 | squad-surgery | | |

Editions are time-based catch-up slots. A catch-up run starts at :10 and :40 each hour
(05:40 to 21:40). It posts the oldest edition that is already due and not yet closed for
the Eastern day, so a late, cancelled or dropped GitHub run loses nothing. An edition is
closed when delivered to both platforms, when there were no new facts, or when the news
check ran. A held or partly delivered edition is retried up to three times a day, and
only the missing platform is sent. The price baseline moves only when the price edition
closes. News (:05), gameweek specials (:35), outbox retry (:50) and the legacy slots keep
their own crons. GitHub gives no timing guarantee for scheduled runs; this design does
not depend on one.
