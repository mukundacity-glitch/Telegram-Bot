#!/usr/bin/env bash
set -euo pipefail

git config user.name 'FPL VORTEX Publisher'
git config user.email 'fpl-vortex-bot@users.noreply.github.com'
for file in state/*.json outbox/*.json outbox/assets/*.png; do
  if [ -f "$file" ]; then git add -- "$file"; fi
done
if git diff --cached --quiet; then exit 0; fi
git commit -m 'Save autonomous source baselines, editions and platform receipts [skip ci]'
for attempt in 1 2 3 4; do
  if git push origin HEAD:main; then exit 0; fi
  echo "Receipt push race: rebase the receipt commit on newest main."
  git fetch origin main
  if ! git rebase origin/main; then
    git rebase --abort || true
    echo '::error::Receipt reconciliation needed; retain archived receipts before replay'
    exit 1
  fi
done
exit 1
