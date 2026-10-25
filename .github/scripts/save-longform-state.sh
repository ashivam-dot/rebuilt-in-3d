#!/usr/bin/env bash
set -euo pipefail
cd state
git config user.name "orbitwire bot"
git config user.email "335661989+ashivam-dot@users.noreply.github.com"
paths=()
if [[ -d longform-reviews ]]; then paths+=(longform-reviews); fi
if [[ "${1:-review}" == all && -f longform.json ]]; then paths+=(longform.json); fi
if (( ${#paths[@]} == 0 )); then exit 0; fi
git add -- "${paths[@]}"
if git diff --cached --quiet; then exit 0; fi
git commit -q -m "longform: retain exact media review and delivery ${GITHUB_RUN_ID:-local}" -- "${paths[@]}"
for delay in 1 2 3 4 5; do
  if git pull -q --rebase origin state && git push -q origin HEAD:state; then exit 0; fi
  sleep "$((delay * 5))"
done
exit 1
