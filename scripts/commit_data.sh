#!/usr/bin/env bash
# 把資料庫、前端 JSON、執行報告 commit 回 repo（GitHub Actions 用）。
set -euo pipefail
msg="${1:-更新資料}"

git config user.name "newsfetch-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add data/ docs/data/ logs/
if git diff --cached --quiet; then
  echo "沒有資料變更，略過 commit"
  exit 0
fi
git commit -m "$msg"

branch="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD)}"
for delay in 2 4 8 16 0; do
  if git push origin "HEAD:$branch"; then
    exit 0
  fi
  [ "$delay" = 0 ] && break
  echo "push 失敗，${delay} 秒後重試"
  sleep "$delay"
  # 資料檔由同一組 concurrency 序列化寫入，遠端若有新 commit 通常是程式碼變更，可安全 rebase
  git pull --rebase origin "$branch"
done
echo "push 失敗，請檢查是否有其他流程同時寫入資料" >&2
exit 1
