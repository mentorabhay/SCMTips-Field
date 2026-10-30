#!/usr/bin/env bash
# Publish ci-out/*.log to the ci-logs branch under runs/<job>/<run id>-<attempt>/ (agent-readable).
# Token-shaped strings are scrubbed first. Retries the push because two jobs publish concurrently.
# Usage: scripts/ci/publish_logs.sh <job> <job status>
set -uo pipefail
job="$1"; job_status="$2"
cd "${GITHUB_WORKSPACE}"
mkdir -p ci-out
sed -i -E "s/(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})/***/g" ci-out/*.log ci-out/*.txt 2>/dev/null
dest="runs/${job}/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
git config user.name "ci-logs-bot"
git config user.email "ci@users.noreply.github.com"
for attempt in 1 2 3 4 5; do
  rm -rf /tmp/logs
  if git fetch -q origin ci-logs 2>/dev/null; then
    git worktree add -q -f /tmp/logs FETCH_HEAD 2>/dev/null || git worktree add -q --detach /tmp/logs FETCH_HEAD
  else
    git worktree add -q --detach /tmp/logs && git -C /tmp/logs checkout -q --orphan ci-logs-new && git -C /tmp/logs rm -rqf . 2>/dev/null
  fi
  mkdir -p "/tmp/logs/${dest}"
  if [ -n "$(ls -A ci-out 2>/dev/null)" ]; then cp ci-out/* "/tmp/logs/${dest}/" 2>/dev/null; else echo "no logs" > "/tmp/logs/${dest}/EMPTY"; fi
  echo "${GITHUB_SHA} ${GITHUB_REF_NAME} ${job_status}" > "/tmp/logs/${dest}/META"
  git -C /tmp/logs add -A
  git -C /tmp/logs commit -qm "logs: ${job} ${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT} ${job_status}"
  if git -C /tmp/logs push -q origin HEAD:refs/heads/ci-logs; then
    echo "published ${dest}"
    git worktree remove -f /tmp/logs
    exit_code=0
    break
  fi
  exit_code=1
  git worktree remove -f /tmp/logs
  sleep $((attempt * 3))
done
exit "${exit_code}"
