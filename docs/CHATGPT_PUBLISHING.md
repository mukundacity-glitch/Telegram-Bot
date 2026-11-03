# Shared ChatGPT → Telegram and Discord publishing

All five existing tasks' full latest instructions are in
`docs/chatgpt-task-specifications.json`. That is the content source of truth;
old Python task adapters are retained for historical compatibility only.

| Task | Generation hours, America/New_York |
|---|---|
| Task 1 | 05:00, 08:00, 11:00, 14:00 |
| Task 2 | 06:00, 09:00, 12:00, 15:00 |
| Three Daily Posts | 07:00, 13:00, 19:00 |
| Press News | 10:00, 16:00, 18:00, changed verified news only |
| Price Changes | 17:00, confirmed official changes only |

Every hour has one content owner. The existing shared GitHub workflow checks
at :15 and :45 from 05:15 through 19:45, posting at most one queued edition per
serialized job to BOTH platforms. Retries reuse independently saved platform
receipts. No automatic post may leave outside 05:00 inclusive to 20:00 exclusive.
The old Discord-only injury/price schedules are retired; manual diagnostics remain.
No new ChatGPT task or GitHub workflow was created. The existing price task is resumed at 17:00 under the user’s all-tasks instruction.

## Prepare an edition

1. Read the task's complete latest content requirements, original brand art,
   source data and previous receipts. Refresh official player IDs, current club,
   price, fixture H/A, availability, deadline and relevant actual performance.
   Verify required custom FDR/model code and inputs; never manufacture forecasts.
2. Fetch the official FPL/PL portrait using its verified photo code. On actual
   failure, use ChatGPT's image-generation tool for that named real player,
   review identity and proportions, and persist a labeled AI illustration.
   Use authentic crests as separate assets. Add metadata to
   `assets/ai-portraits/manifest.json`: key official code, fields player_code,
   player_name, type=AI_ILLUSTRATION, path and SHA-256 of actual image bytes.
   PNG or base64-encoded PNG is supported. The label is applied by the resolver.
   If no reviewed fallback exists, state/missing_portraits.json queues the ID;
   never silently replace it with a generic person or fake photograph.
3. Render all required pages as real 1920×1080 or 1080×1920 PNGs; inspect them,
   including mobile readability and the original master/footer. Store bytes
   under `outbox/assets/` using GitHub blobs, then add an immutable outbox JSON.

Required record example (replace every example value with verified current data):

```json
{
  "task": "task2", "edition": "four-midfielders", "season": "2026-27",
  "gameweek": 10, "title": "FOUR MIDFIELDERS",
  "generated_at": "2026-11-03T09:05:00-05:00",
  "publish_at": "2026-11-03T09:15:00-05:00",
  "deadline": "2026-11-07T06:00:00-05:00", "pre_deadline": true,
  "caption": "Hook\nVerified datapoint\nNext GW implication\nBUY / HOLD decision\n#FPL #FPLVortex #FPLTips #GW10",
  "images": ["outbox/assets/edition-page1.png"],
  "facts": {"players": [{"id": 123, "minutes": 800}]},
  "sources": ["https://fantasy.premierleague.com/api/bootstrap-static/"],
  "qa_passed": true
}
```

The worker requires a fresh generation time (at most 3 hours), a valid deadline,
four hashtags and source/QA evidence. Its identity hashes verified `facts` only,
not cosmetic changes, captions, generated_at or image bytes. Keep task/edition
slugs and facts canonical across unchanged editions. Check the older
state/deliveries.json as well when migrating an existing topic.

Commit with `[FPL-OUTBOX]` to request immediate real delivery inside the window,
or allow the next scheduled check. Check state/chatgpt_deliveries.json for BOTH
Telegram and Discord IDs before saying POSTED. Queued is not delivered.
For a partial failure, retry the same immutable outbox record. Never resend a
confirmed destination or discard an ambiguous timeout receipt.
