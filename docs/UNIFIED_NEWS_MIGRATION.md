# FPL VORTEX — shared Telegram + Discord migration audit (2026-11-02)

**Deployment status: DRAFT ONLY. No live flags or old tasks have been changed.**
This document records inspected repository behavior, not assumptions.

## Existing producers and overlap

| System | Trigger | Content / actual backing | Current destination |
| --- | --- | --- | --- |
| Telegram-Bot / telegram-daily.yml | 13 daily Eastern-time editions, each with backup triggers | Official FPL; captions, branded PNGs; optional The Odds API 0.5 team totals; price-baseline comparisons | Telegram only |
| Vortex-Injury-Price-Discord / injury-news.yml | 7,22,37,52 minutes hourly, best-effort UTC Actions cron | FPL player status/chance/news deltas, combined injury/doubt/suspension/available PNG and X drafts | Discord only |
| Vortex-Injury-Price-Discord / price-change.yml | 23:45 Europe/London | LiveFPL third-party price-progress feed; on failure, uncalibrated official-FPL transfer-volume heuristic | Discord only |
| Vortexnews-bot-Xpost / bot.yml | Every 20 minutes and push | Feed registry (16 RSS/Google News feeds, Bluesky specialist); verified transfers, loans, injuries, suspension, renewals; player card assets | X only |
| Vortexnews-bot-Xpost / fpl-deadline-news.yml | Every 10 minutes, guarded by FPL deadline window | Premier League press conference source collection/verification | X only |
| ChatGPT Task 1 | 06:00, 10:00, 15:00, 19:00 ET | Player availability, form, captaincy, transfer news + branded graphic | ChatGPT result and optionally connected X |
| ChatGPT Task 2 | 08:00, 10:45, 12:00, 15:45 ET | Fixtures/odds, midfielder comparison, team attack/defence, BUY/HOLD/SELL | ChatGPT result and optionally connected X |
| ChatGPT Three Daily Posts | 07:30, 12:30, 19:30 ET | Fixture targets, transfer strategy, deadline decision | ChatGPT result and optionally connected X |
| ChatGPT Press News | Every 3 days | Press/availability graphic | ChatGPT result |

The X bot's 2026-11-02 run 41413557251 **failed its final posting gate** after Twikit errors including "ClientTransaction object has no attribute 'key'"; tests and story verification succeeded but successful X posting was not confirmed. Do not treat X published history as a reliable realtime input.

## Implemented in this DRAFT

1. **Single Post object** shared by Telegram and Discord. Existing Telegram's photo/HTML format stays in TelegramClient; the original image, body caption and hashtags go to Discord without rewriting facts.
2. **Independent receipt journal:** track Telegram message IDs and Discord IDs separately; checkpoint success before attempting the other destination. Existing delivered Telegram entries are respected. Discord 429/5xx retry is bounded. API uncertainty cannot guarantee exactly-once without provider-level idempotency.
3. **Official FPL change feed:** compare real consecutive bootstrap snapshots. Emit only changed FPL availability flags, FPL notes, and observed old/new prices. No prediction or fitness certainty is inferred. First run warms a baseline to avoid false "new" items.
4. **Attributed news feed adapter:** read existing X config/feeds.json dynamically. Candidate headlines must be recent, FPL-club-relevant and topic-relevant. RSS headlines are **reported leads, not X V2-verified news**. Filter close duplicates and include original URL, source label and explicit uncertainty.
5. **Persistent news pending queue**, bounded sends per run, four derived hashtags, cold-start no-flood behavior, dry-run with no state writes and no outward post.
6. **Odds math:** pre-match age checks, two-bookmaker minimum, no-vig Poisson-equivalent 0.5 team-total goals and opponent clean sheet probabilities remain distinct from separate three-way no-vig market win/draw/loss percentages. If markets are not available, values stay null; no FDR substitution.
7. **No new workflow** and no existing task or channel deleted. Live dual publish requires GitHub variable DUAL_PUBLISH_ENABLED=true. Breaking news requires UNIFIED_NEWS_ENABLED=true. Both are OFF by default, and require secrets and test confirmation.

## Explicit gaps / release blockers

- The Discord injury renderer and predictor-card layout remain in their own repository. FPL changes are represented in a new text feed, **not yet the identical existing Discord combined injury card**. The existing Discord 23:45 predictor has NOT been ported; its transfer-flow "likelihood" fallback is uncalibrated and must not be misrepresented as probability.
- The X repository's V2 truth verification, X social feeds and deadline press compilation are not in the shared runtime. The RSS adapter uses its feed list but does not replicate its verification gates or all social-source coverage.
- ChatGPT Task 1, Task 2, Three Daily Posts, and Press News generate unique graphics that have NOT been migrated one-for-one. Telegram's 13 existing editions overlap conceptually but are not full replacements.
- This draft does not change schedule frequency. If the new news lane is eventually enabled on the current Telegram workflow, it runs only on its existing daily cron invocations, **not** every 10–20 minutes. A deliberate schedule merge is required for true near-real-time parity.
- There is no permission to read GitHub Secret values. DISCORD_WEBHOOK_URL is currently configured in the Discord repo but must also be configured securely in the Telegram repo for this shared publisher. Telegram token/chat secrets remain unchanged.
- Publishing to actual live channels and recreating third-party API historical price/odds results are **not tested** by the PR's mock tests.
- Journal persistence is Git-commit-based and depends on successful push. Before production, review race/recovery semantics and ensure uncertain network sends cannot replay accidentally. Do not switch legacy producers off until end-to-end receipt checks and at least one successful live window are recorded.

## Safe staged validation and cutover

1. Confirm CI success and inspect all changed files. In Actions, run the existing Telegram workflow with dispatch slot **audit-news**. This audits fresh sources without external delivery or persistent state modification.
2. Provision separate *staging* Telegram bot/chat and Discord webhook via staging-only GitHub secrets or a separate, controlled test environment; do NOT point test runs to public channels.
3. Run FPL/price/press/transfer synthetic fixtures and real-data dry-run; verify both outputs have same sourced facts/captions/hashtags and that each delivered ID is stored. Test Discord failure then recovery, Telegram failure then recovery, 429 and unknown receipts.
4. Port/validate missing Discord predictor card and X V2-approved article adapter. Preserve existing media assets, safety gates and previously posted messages. Resolve uncaught price-predictor calibration/odds data gaps.
5. Rework **the existing Telegram schedule only**, after approval, to accommodate fast breaking-news checks and every unique content edition; account for Eastern DST and one canonical dedup ledger.
6. Enable the dual publisher on a controlled live slot; watch source health/receipts, rate limits, states and rendered media. Once replacement is demonstrably complete, stop the old Discord schedules and four ChatGPT automations without deleting their histories. Keep X workflow if it serves separate X publishing.
7. Roll back using the repository variables (set both false) and the previous main SHA. Do not delete state or previously sent Telegram/Discord messages.

No guarantee of 100% forecast accuracy or of perfect delivery exactly once over a network is made.
