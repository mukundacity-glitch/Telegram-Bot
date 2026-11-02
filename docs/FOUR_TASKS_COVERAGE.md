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
