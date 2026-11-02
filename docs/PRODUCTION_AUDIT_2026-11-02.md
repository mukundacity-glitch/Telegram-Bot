# FPL VORTEX production audit — 2026-11-02

Evidence cutoff: 2026-11-02T16:34:35.954480-05:00. This report distinguishes code, trigger, PNG, delivery and saved receipt evidence. No public test messages were sent. The YouTube repository was read-only; no uploads or workflows were triggered there.

## A. System health

- Telegram: real scheduled deliveries confirmed, but recurring stale-checkout duplication and a receipt push failure were found. PR #6, #7 and #8 are merged on main (b6c0bc7, 11d9c3e, a35dd67). PR #8 retries receipt pushes; this audit adds current-main checkout after concurrency acquisition and full history for rebase. A local real-Git integration test reproduces a concurrent main update and verifies the saved platform ID survives.
- Discord: PR #5 is merged at 3044272. Latest native injury run returned message ID 1566909920903831663. Injury and price ledgers live in separate GitHub Actions caches, not permanent repository history. Cache eviction and cross-workflow divergent copies remain risks. Saving now runs after partial failures too; that does not make caches permanent storage.
- Official FPL: bootstrap-static, fixtures and element-summary/1 all returned HTTP 200 in this audit. Official event deadlines establish 2026/27 (first 2026-08-21, last 2027-05-30). GW9 is unfinished; GW10 is next, deadline 2026-11-06 13:30 EST. Featured-player renderers fetch individual summaries.
- Odds: math checked against the read-only Day1 Phase 5 implementation: per-book inverse-price normalization, separate 1X2 and total-2.5 consensus, multi-start bounded L-BFGS-B independent Poisson rates, fit threshold, CS(home)=exp(-away rate). Synthetic regression tests verify recovery of known rates. Coordinate-wise medians now always renormalize to sum 1. Quotes older than 12 hours, future quote timestamps, incomplete markets and unmatched fixtures are excluded. Twelve-hour kickoff matching tolerance and quote-age policy remain reviewable model choices, not a proof of bookmaker accuracy.
- Credentials: the latest inspected Telegram production log had THE_ODDS_API_KEY empty. Its historical runtime did not include ODDS_API_KEY; current legacy step supports both. The migrated Task 2 step lacked both bindings and is repaired here. The connector cannot inspect secret inventory/values, so current credential usability is NOT verified. Set THE_ODDS_API_KEY or ODDS_API_KEY in Telegram-Bot Actions secrets if absent; a secret in the YouTube repo is not inherited. No values were revealed or copied.
- Graphics: Library master libfile_0947818b02d88191b357fe10080957ce is 1536x864, 194358 bytes, Git blob b0d890a529ad7416a142d3cfbbadfc800eb26bd0. The prior pinned asset was different (01d87ec...). This audit installs exact Library bytes in Telegram and updates both pins. Twelve task editions produced real 1920x1080 PNGs during non-publishing rendering. Portraits and crests load proportionally; unverified xPts are omitted. Font fallback was found to silently ignore requested size when condensed fonts were missing; repaired and covered by regression tests. Detailed mobile tables still need editorial simplification before being called premium at phone width.

## B. Complete configured timetable

All Telegram rows below are America/New_York with timezone-aware cron entries (42 distinct checks). These are checks/eligible routes, NOT 42 guaranteed posts. Backups and original editions remain. Hourly news is conditional on genuinely changed verified information and is seeded with a baseline on first use.

| Eastern time | Existing routing/check |
|---|---|
| 05:00 | Task 1 early availability; verified news check |
| 05:15 | Task 1 early availability backup; verified news check |
| 06:00 | task1 / availability-transfer-decisions; verified news check |
| 06:30 | elite primary |
| 06:45 | elite backup |
| 07:00 | projections primary; verified news check |
| 07:15 | projections backup |
| 07:30 | three_daily / fixture-targets |
| 08:00 | comparison primary; task2 / all20-projected-goals; verified news check |
| 08:15 | comparison backup |
| 09:00 | buy primary; verified news check |
| 09:15 | buy backup |
| 10:00 | news primary; task1 / form-minutes-targets; verified news check |
| 10:15 | news backup |
| 10:45 | midfielders primary; task2 / three-midfielders |
| 11:00 | team_analysis primary; verified news check |
| 11:15 | team_analysis backup |
| 11:25 | midfielders backup |
| 12:00 | prices primary; task2 / team-attack-defence; verified news check |
| 12:15 | prices backup |
| 12:30 | three_daily / transfer-squad-structure |
| 13:00 | start_bench primary; verified news check |
| 13:15 | start_bench backup |
| 14:00 | transfer primary; press_news / verified-press-availability; verified news check |
| 14:15 | transfer backup |
| 15:00 | transfer_suggestions primary; task1 / captain-differential; verified news check |
| 15:15 | transfer_suggestions backup |
| 15:45 | task2 / four-position-transfers |
| 16:00 | captaincy primary; verified news check |
| 16:15 | captaincy backup |
| 17:00 | verified news check |
| 17:30 | review primary |
| 17:45 | review backup |
| 18:00 | verified news check |
| 18:30 | sell primary |
| 18:45 | sell backup |
| 19:00 | task1 / transfer-market-team-news; verified news check |
| 19:30 | three_daily / next-gw-evening-decisions |
| 20:00 | evening primary; verified news check |
| 20:15 | evening backup |
| 21:00 | verified news check |
| 22:00 | verified news check |

Task 2 overlap is intentional in current code: 07:00 projections can suppress unchanged 08:00 all-20 board; 10:45 midfielders share their original receipt; 11:00 team analysis can suppress noon; 15:00 transfers can suppress 15:45. This preserves existing slots and avoids a second identical edition. If four distinct Task 2 posts at their named times are required in addition to originals, that needs an editorial decision; no times were removed or shifted here.

Press eligibility is every three days anchored 2026-10-30 at 14:00 ET; November 2 is eligible. An original transfer edition can also run at 14:00. Captaincy original 16:00 is conditional on the following day's official deadline. Reviews require a completed GW.

Discord injury cron is unchanged: 7,22,37,52 * * * * (all day). Editorial routes at 12:00, 14:00, 17:00 ET inside that monitor, normally first eligible :07 check; actual Actions delay can be substantial. Price cron is unchanged: 23:45 Europe/London. This is usually 18:45 New York, and 19:45 during US/UK DST mismatch weeks. It is not fixed to one Eastern hour year-round.

## ChatGPT task state and latest recorded results

| Task | Enabled | Configured ET times | Latest result |
|---|---|---|---|
| Task 1 / 6ae494793fdc8191a72c714c4bdad61f | No | 06:00,10:00,15:00,19:00 | Completed response, no finished graphic, NOT POSTED |
| Task 2 / 6ae1ba5280248191970af7523572ca38 | Yes | 08:00,10:45,12:00,15:45 | Completed response, no finished graphic, NOT POSTED |
| Three Daily / 6ae4947a31608191815d3915528bdacd | Yes | 07:30,12:30,19:30 | Completed response, no finished graphic, NOT POSTED |
| Press / 6ae4da1e097c81919ccaef4c8fba191a | Yes | 14:00 every 3 days | Completed response, no finished graphic, NOT POSTED |

Only latest task run/result is exposed, not full task execution history. next_run_time was null in the returned records; do not invent a next trigger. Prompts contain quality and receipt requirements but no accessible atomic shared state with GitHub. They also retain older conflicting sections below overrides. No automation was created, edited, enabled or deleted in this audit.

## C. Confirmed last delivery evidence

- Telegram #154: 2026-11-02 15:53:12 EST, run 41523140792. Log explicitly confirms delivery, followed by failure saving state. Historic confirmation is recovered in deliveries.json under a separate recovery key. Original #153 remains unchanged. The artifact from that historical run contained only the PNG, not a ledger; its associated Discord success has no exposed message ID, so no Discord ID is invented.
- Latest Discord ID with explicit native-bot receipt: 1566909920903831663 at 2026-11-02 15:20:37 EST, run 41518297806; cache save succeeded. Telegram-Bot also has a durable dual-platform receipt for Telegram #153 / Discord 1566917868736745473 at approximately 15:52 EST, plus Telegram #152 / Discord 1566867655191699547 at 12:32 EST. A later Discord send was logged with Telegram #154, but its ID is unavailable.
- Configured Telegram footer/destination is @FPLVortexDailyBot. Numeric chat secret cannot be read by this connector; successful run receipts prove the configured runtime destination accepted messages, not independently that a particular public channel owns the numeric chat. Discord username @fplvortex is a footer handle, not a channel identifier or invite URL. No direct authenticated platform history/read API was available in this session.

## D. Failures and root causes

1. Telegram run 41523140792, receipt persistence step: delivered message 154, then `! [rejected] HEAD -> main (fetch first)` / exit 1. Checkout used old trigger SHA 11d9c3e. Prior scheduled run 41522981732 had already sent #153 for the same elite edition. Concurrency alone did not refresh stale event checkouts. Latest PR #8's retry was merged afterward; no production retry execution on that fix was present at initial cutoff. Local integration verifies retry behavior, not live production.
2. Telegram run 41330307384: `Telegram sendPhoto network or JSON failure (ReadTimeout)`. A backup later confirmed #143. A timeout has ambiguous server outcome; automatic external POST retry without idempotency can duplicate. No claim of exactly-once network delivery is made.
3. Discord price run 41488573891 and earlier runs: old resources.premierleague.com player URL returned HTTP 403. Current branded renderer tries official alternate image hosts and holds if authentic media cannot be obtained. Strict price production now uses that same renderer instead of the portrait renderer that could omit missing imagery.
4. Missing odds bindings in task-publisher step; empty primary key in examined historical legacy runtime. Unverified odds must not be represented as live. Fixture-only 20-club graphics remain allowed.
5. Wrong master pin, six-line legacy captions, four-line Discord captions, size-ignoring font fallback, mislabeled high-owned differential, code-vs-ID cross-repo comparison and rejection of multi-fixture completed GW history were found and repaired.
6. Latest ChatGPT task results were marked completed at response level but did not finish the requested graphics or external delivery. These are not publishing successes.

## E. Repairs and validation

See the audit PR in each repository for exact commit/files/checks. No cron expression, timezone, task enablement or YouTube file changed.

Telegram: current default-branch checkout for scheduled events plus fetch-depth 0; existing safe push retry retained and integration tested; recovery receipt #154 added without erasing #153; artifacts retained 30 days; both odds-key bindings injected into Task 2 process; consensus normalized; exact master installed/pinned; five-line legacy captions retained unchanged on Telegram; font fallback preserves requested size; differential requires <=15% verified ownership; card actions preserve editorial CAPTAIN/BUY labels.

Discord: exact master pin; strict price output on original blue 1920x1080 pages (three players each, all candidates retained in one message, up to seven pages for 20 players); captions five lines/four hashtags; history sums double-GW fixture rows; external player-code comparison repaired; state cache saved even after partial error; headline font fallback repaired. The legacy portrait renderer remains available to its existing offline tests, but is not the strict production route.

Regression suites and compileall are required on both branches; final CI links and results are recorded in the PR and user-facing completion report. A passed local suite/PR check does not prove a new scheduled post or live receipt-push race has occurred.

## F. Remaining blockers and limits

- Current usable odds credential and paid endpoint access/coverage require an actual authenticated runtime result. Never transfer a secret value through chat.
- Discord cache retention is not a permanent receipt database. Two native workflow caches and the Telegram repo ledger are not atomic shared state. Best-effort external receipt lookup cannot guarantee cross-platform deduplication or prevent concurrent publishers selecting the same topic.
- Native Discord price and added editorial categories lack confirmed post-repair live receipts. A valid render/test is insufficient.
- Genuine club/manager press statements are separate from FPL flags; this repository's availability edition does not implement a complete verified press-conference sourcing service. Do not label FPL flags as manager quotes.
- Telegram sender network timeouts remain ambiguous; a delivery acknowledgement lost in transit cannot be safely reconstructed from code alone.
- Existing Task 2 canonical-receipt overlaps can skip named later slots; preserve timing until the user chooses otherwise.
- ChatGPT Task 1 is paused. It was not enabled because no task-status change was requested. The corresponding GitHub routes are independent of that ChatGPT toggle.
- Detailed five-GW graphics are rendered and structurally verified, but full phone-width readability and club-portrait visual currency need human editorial review before every public edition.

## G. Production readiness

Every category is PARTIALLY VERIFIED unless noted: code/schedule and real PNG generation are established for the 12 ported editions, but individual post-repair scheduled delivery and durable receipt evidence are not yet established. Bookmaker goals/CS numerics are BLOCKED pending usable current odds access; the fixture-only board is PARTIALLY VERIFIED. Native Discord injury is PARTIALLY VERIFIED (real receipt before repair); price and three additional editorials are PARTIALLY VERIFIED (code/tests, no new live receipt). Independently sourced manager/club press statements are BLOCKED as a complete category. ChatGPT Task 1 scheduling is BLOCKED by its current paused state; other tasks are enabled but their latest graphics/delivery were incomplete.

## H. Final distinction

Code/tests: verify final PR checks. Scheduled triggers: observed in the 72-hour run history, not a guarantee of exact future wall-clock delivery. Graphics: 12 genuine PNGs rendered offline from current official snapshots; no public test. Actual delivery: only the IDs above and the companion evidence file. Receipt persistence: Telegram #153/#152 on main, #154 recovery in this repair; native Discord receipt cached. Post-repair production delivery and end-to-end permanence are not yet fully verified.

## Evidence links

- https://github.com/mukundacity-glitch/Telegram-Bot/actions/runs/41523140792
- https://github.com/mukundacity-glitch/Telegram-Bot/actions/runs/41522981732
- https://github.com/mukundacity-glitch/Telegram-Bot/actions/runs/41492032343
- https://github.com/mukundacity-glitch/Telegram-Bot/actions/runs/41330307384
- https://github.com/mukundacity-glitch/Vortex-Injury-Price-Discord/actions/runs/41518297806
- https://github.com/mukundacity-glitch/Vortex-Injury-Price-Discord/actions/runs/41488573891
- audit-2026-11-02-evidence.json contains summaries from 68 publishing jobs (46 Telegram and 22 Discord) plus task schedule/status metadata. The scan fetched all 180 Telegram and 40 Discord runs returned for the requested window, including validation and skipped push jobs. The 68 publishing jobs' full job logs were inspected; unrelated validation logs were not all downloaded.
