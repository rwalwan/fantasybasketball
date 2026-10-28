#!/usr/bin/env bash
# Run only code that passed the Tests workflow (review 2, finding 7b: Tests ran on push but didn't gate the
# 15-minute job, so a broken commit on main ran in production). If the newest commit hasn't passed (failed or still
# running), check out app/, site/, tools/, worker/ and requirements.txt from the newest commit that did. The workflow
# file itself always comes from main. Needs GH_TOKEN with actions: read.
set -uo pipefail
head=$(git rev-parse HEAD)
green=$(gh api "repos/$GITHUB_REPOSITORY/actions/workflows/tests.yml/runs?branch=main&status=success&per_page=1" \
  --jq '.workflow_runs[0].head_sha' 2>/dev/null)
if [ -z "$green" ] || [ "$green" = "null" ]; then
  echo "tested code: no passing Tests run found; running $head"; exit 0
fi
if [ "$green" = "$head" ]; then echo "tested code: $head passed Tests"; exit 0; fi
git fetch -q --depth 1 origin "$green" && git checkout -q "$green" -- app site tools worker requirements.txt \
  && echo "::warning::main ($head) hasn't passed Tests; running the last passing commit $green" \
  || { echo "::warning::could not check out $green; running $head"; exit 0; }
