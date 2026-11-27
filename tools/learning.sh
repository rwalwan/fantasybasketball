#!/usr/bin/env bash
# Training history lives on the `learning` branch, checked out at data/learning. Unlike `state` (one force-pushed
# commit), it keeps real git history: one commit per nightly training run, never force-pushed, so every archived
# grade and every version of the learned numbers (learned.json) can be looked up or restored.
#   restore: clone the branch into data/learning (or start it empty if the branch doesn't exist yet; any other
#            failure fails the run, so a network blip can't start the archive over)
#   save:    commit what changed and push (retries; a rejected push fails the run rather than forcing)
#   pull:    (the 15-minute job) copy learned.json from the branch into data/state. If the fetch fails, the copy
#            already in data/state (from the last run) stays, so a network blip never drops the learned numbers;
#            no branch yet = no learned numbers (factory behavior).
# Usage: REMOTE=<git url> tools/learning.sh restore|save|pull
set -uo pipefail
REMOTE="${REMOTE:-$(git remote get-url origin)}"
DIR="${LEARN_DIR:-data/learning}"
SLEEP="${STATE_RETRY_SLEEP:-5}"
retry() { local n=0; until "$@"; do n=$((n + 1)); [ $n -ge 3 ] && return 1; sleep $((n * SLEEP)); done; }

restore() {
  local rc=0
  for i in 1 2 3; do
    git ls-remote --exit-code --heads "$REMOTE" learning >/dev/null 2>&1; rc=$?
    [ $rc -eq 0 ] || [ $rc -eq 2 ] && break
    sleep $((i * SLEEP))
  done
  rm -rf "$DIR"
  if [ $rc -eq 2 ]; then
    echo "learning: no learning branch yet, starting it"
    mkdir -p "$DIR" && git -C "$DIR" init -q -b learning && git -C "$DIR" remote add origin "$REMOTE"
    return 0
  fi
  [ $rc -eq 0 ] || { echo "learning: cannot reach $REMOTE (exit $rc)" >&2; return 1; }
  retry git clone -q --depth 1 --branch learning "$REMOTE" "$DIR" || { echo "learning: clone failed" >&2; return 1; }
  echo "learning: restored $(git -C "$DIR" rev-parse --short HEAD)"
}

save() {
  [ -d "$DIR/.git" ] || { echo "learning: nothing restored; not saving" >&2; return 1; }
  cd "$DIR" || return 1
  git config user.name "lock-desk-bot" && git config user.email "lock-desk-bot@users.noreply.github.com"
  git add -A
  git diff --cached --quiet && { echo "learning: nothing new"; return 0; }
  git commit -q -m "training $(date -u +%FT%TZ)" && retry git push -q origin HEAD:refs/heads/learning \
    && echo "learning: saved $(git rev-parse --short HEAD)"
}

pull() {
  local out="${STATE_DIR:-data/state}/learned.json" rc=0
  git ls-remote --exit-code --heads "$REMOTE" learning >/dev/null 2>&1; rc=$?
  if [ $rc -eq 2 ]; then echo "learning: no learning branch yet (factory numbers)"; rm -f "$out"; return 0; fi
  local tmp; tmp=$(mktemp)
  if [ $rc -eq 0 ] && retry git fetch -q --depth 1 "$REMOTE" learning && git show FETCH_HEAD:learned.json > "$tmp" 2>/dev/null \
     && python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$tmp"; then
    mkdir -p "$(dirname "$out")" && mv "$tmp" "$out" && echo "learning: learned numbers from $(git rev-parse --short FETCH_HEAD)"
  else
    rm -f "$tmp"; echo "::warning::learning: could not read learned.json from the learning branch; keeping the last copy"
  fi
  return 0
}

case "${1:-}" in
  restore) restore ;;
  save) save ;;
  pull) pull ;;
  *) echo "usage: tools/learning.sh restore|save|pull" >&2; exit 64 ;;
esac
