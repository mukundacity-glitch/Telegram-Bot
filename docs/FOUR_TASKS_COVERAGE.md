# FPL VORTEX — four ChatGPT tasks + Telegram + Discord: release coverage

**Status:** Staged in `upgrade/unified-telegram-discord-news`, draft PR #5. **Not merged or enabled.** Keep all four ChatGPT automations and both original bot workflows intact until production parity is demonstrated. No private credentials in source control.

## Content parity (as of 2026-11-02)

| Original content | Canonical existing Telegram-Bot implementation | Status |
|---|---|---|
| Telegram existing scheduled editions | 13 original slots, graphics, captions and state untouched; two new isolated editions added at 10:45 and 13:00 ET | Preserved in code |
| Task 2 — 08:00 all 20 fixture goals & CS | `projections` at 07:00 ET, official fixtures/crests; revised no-vig 1X2 + O/U2.5 constrained Poisson fit; missing authentic odds => N/A | Coverage at a different existing time; market result depends on available fresh bookmaker prices |
| Task 2 — 10:45 three midfielders | New `midfielders` at 10:45 ET, 3 images/crests, exact GW, prices, season xG/xA and FDR, strict 1920×1080 PNG | Added and tested; no authenticated xPts projection |
| Task 2 — 12:00 team attack/defence | `team_analysis` at 11:00 ET; official fixture/score histories and sourced player art | Existing partial coverage, not independent xGC time series |
| Task 2 — 15:45 transfer suggestions | `transfer_suggestions` at 15:00 ET; official four-position swaps/holds with photos and crests | Existing four-position comparison; original requested nine recommendations not yet ported |
| Task 1 — captaincy, news, recommendations, bench/start | Existing `captaincy`, `news`, `elite`, `buy`, `sell` plus new `start_bench` at 13:00 ET | Partial; xPts value board and once-per-GW market-trends addendum not yet ported |
| Three daily posts — 07:30, 12:30, 19:30 | Existing comparison, price and evening watchlist posts, near those time windows | Topic-level overlap, not exact per-edition parity |
| Press News — manager availability and club news | Official FPL `news` daily and new `unified_runner` verified FPL delta + attributed player RSS | Partial; dedicated three-column graphic, authoritative manager quotes, and full X V2 verification pipeline not yet ported |
| Discord injury / price change | New FPL change and price-change feed with mandatory branded player image and real crest | Partial; original Discord combined injury grid and LiveFPL prediction visuals NOT yet ported |
| X source registry / social monitoring | Current 16 RSS-source integration, cautious unconfirmed labels | Partial; complete ~44 official/specialist X sources and press verification not yet ported |

## User's non-negotiable shared-delivery contract

- Every **new** shared news story uses a single immutable story identity, single exact 1920×1080 PNG, and single caption with **exactly four hashtags**.
- Both Telegram and Discord use exactly the same caption string (Telegram's old formatted caption remains untouched when shared delivery is not enabled).
- Official FPL player image identifier and authentic present-club crest; if not retrieved, **block the new shared news**. No text-only placeholder or fabricated sports data. Team-only fixtures use authentic badges with no invented player.
- Independent receipts for both services. When one succeeds and the other fails, only the unfinished destination is retried. No guarantees for provider-level ambiguity if an HTTP response is lost after acceptance; production end-to-end replay QA required.
- Identical topics from independent old Discord bot/workflows are **not automatically cross-repo deduplicated**. Full production cutover must select ONE authoritative publisher per type after confirming feature parity and backfilling delivery state.

## Release gate — all must be true before switching off any existing task or bot

1. GitHub CI green on **final PR head**, official FPL correctness and photos/crests QA pass, all new odds tests pass.
2. Confirm required secrets independently exist in the target GitHub repo: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`, optional `THE_ODDS_API_KEY`. GitHub Actions secret references are not proof of presence. Never expose values in chat or logs.
3. Validate both destinations as user-authorized staging targets. Real `sendPhoto` and Discord webhook message receipts and matching PNG SHA/caption are observed. Run retry and duplicate suppression tests **on staging only**.
4. Preserve the old Telegram state ledger and schedule; archive a restore point of old Discord source/state; no deletions.
5. Match Task 1 expected-points board, market-trends addendum, Task 2 full transfer matrix, Discord specialty cards, Press News verified-source workflow, and cross-repo idempotency at editorial event level — or explicitly obtain user's approval for lower parity.
6. Enable shared delivery flags on canonical runner, then retire redundant news *schedules*, one at a time, only after destination receipts verify no missed publications. **Do not delete bots, workflows, chat histories or repositories.**
7. Record rollback: disable canonical `UNIFIED_NEWS_ENABLED`/`DUAL_PUBLISH_ENABLED`, restore previous active schedule statuses and preserve checkpoints; avoid broadcasting replayed posts without reviewing retained receipts.

**Current blocker:** GitHub connector cannot read/provision Actions secrets for this repository or confirm end-to-end Telegram + Discord staging channels; no live confirmation. Do **not** enable `DUAL_PUBLISH_ENABLED` / `UNIFIED_NEWS_ENABLED` or disable ChatGPT tasks yet.


## Unified quality upgrade (2026-11-02, staged — NOT deployed)

### Existing schedules reviewed and preserved
- Four ChatGPT tasks **updated in place** without modifying their RRULEs: Task 1 `6ae494793fdc8191a72c714c4bdad61f` (06:00/10:00/15:00/19:00 ET), Task 2 `6ae1ba5280248191970af7523572ca38` (08:00/10:45/12:00/15:45 ET), Three Daily `6ae4947a31608191815d3915528bdacd` (07:30/12:30/19:30 ET), Press News `6ae4da1e097c81919ccaef4c8fba191a` (every third day 14:00 ET). All remain enabled; these are **existing** ChatGPT tasks, not GitHub jobs.
- Telegram GitHub workflow `.github/workflows/telegram-daily.yml` preserves its current 15 primary schedules and corresponding backup checks as found on this branch. No new workflow/task and no time change in this upgrade.
- Existing Discord GitHub workflows `injury-news.yml` every 15 min UTC and `price-change.yml` 23:45 Europe/London have separate staging changes in draft PR #3, with their scheduled times preserved. No secrets exposed, external messages sent or current production bots altered.

### Specific implementation
- Strict broadcast graphics use the user's **actual attached original** `59698.png` blue master. Its Git blob SHA is `b0d890a529ad7416a142d3cfbbadfc800eb26bd0`. The repository's **existing** `assets/references/brand_background.png` currently has a *different* Git blob SHA `01d87ec98cf4d8d8ccff4814f4ddf5b3c339725e`; **do not claim the files are identical or enable strict publishing until the attached original has been installed and verified in the repository**. SHA checking holds rather than silently substituting a different background.
- Two real public social handles are mandatory GitHub Actions variables `FPL_TELEGRAM_HANDLE` and `FPL_DISCORD_HANDLE`; no inferred usernames. Old YouTube/X/social geometry and original logo/footer are restored before inserting those handles. No source/API/version notes printed onto the strict public slide.
- Official current FPL IDs/prices/availability/ownership/minutes and completed-GW history govern all player decisions. Public FPL Core Insights project `olbauday/FPL-Core-Insights` season `data/2026-2027/` is a **read-only optional supplemental** source. Date and exact FPL player/team-code joins are validated against the official API. Screenshot data are layout references, **never live values**. Source provenance remains in internal logs.
- Shared source checks for **five consecutive Gameweek fixture slots** include future opponent, (H/A), authentic crest, colored FDR, blanks and doubles. Optional per-fixture xPts require an independently verified fresh model snapshot joined on player ID, fixture ID and GW through `FPL_XPTS_SNAPSHOT_URL`; absent xPts are omitted, not fabricated.
- Single player (`elite`, live injury/news) and 2-4 player (`comparison`, `midfielders`, `buy`, `sell`, `captaincy`, player `news`) have source-enriched clean-table original-blue slide layouts in strict mode. Other team/many-player templates retain current content and gain common strict source/brand/visual gates; complex eight-or-more player full five-GW layouts remain a **publication-quality limitation** and should be held rather than misrepresented as verified full profiles.
- Strict original-blue publishing only activates if `FPL_ENRICHED_VISUALS_ENABLED=true`; cross-day editorial version checking if `FPL_SEMANTIC_DEDUP_ENABLED=true`; Telegram-to-Discord paired delivery if `DUAL_PUBLISH_ENABLED=true`; newly sourced player news if `UNIFIED_NEWS_ENABLED=true`. Defaults remain OFF pending staged validation. Real Telegram+Discord receipts are required; changes to old tasks/bots must not be switched over without confirming the shared ledger. Old functionality is preserved.

### Release blockers
1. Install/verify the exact user-provided `59698.png` original as canonical `assets/references/brand_background.png`, and confirm the new Git blob SHA matches the approved one.
2. Confirm actual Telegram and Discord **public** handle strings and configure them as Actions variables in both repositories; bot token/chat ID/webhook URL is **not** a public social handle.
3. Configure one authorized staging Telegram destination and Discord webhook and verify photo+caption+real receipt on both services; verify retry protection and accepted-image quality on mobile.
4. Resolve remaining special Discord price/injury multi-page parity, Task 1 market xPts/full market-trends board, and cross-repo editorial-level dedup in live production. This PR alone does **not** disable any existing bot/task or guarantee duplicate freedom across all independent systems.
5. Do not merge these PRs or enable the new feature flags until the gates above pass. Rollback is to switch the flags OFF and retain both existing bots, ledgers, history and posting times.


## User clarification: approved slide exists in GitHub
On 2026-11-02 the user explicitly confirmed that the existing `Telegram-Bot/assets/references/brand_background.png` in the `upgrade/unified-telegram-discord-news` branch is their desired slide. Its verified Git blob SHA-1 is `01d87ec98cf4d8d8ccff4814f4ddf5b3c339725e` (172062 bytes). The other in-chat PNG file (`59698.png`, blob `b0d890a529ad7416a142d3cfbbadfc800eb26bd0`) is a distinct binary. **Use the user-confirmed GitHub master without asking for a re-upload.** Renderer fingerprints were updated to match the confirmed GitHub master. Prior guidance in this document requiring re-upload of `59698.png` is superseded. Actual Telegram+Discord delivery/staging configuration and end-to-end duplicate safety remain separate release gates.
