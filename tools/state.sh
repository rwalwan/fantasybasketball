#!/usr/bin/env bash
# Saved state (data/state) lives on the `state` branch. Review finding 8: a transient failure while restoring used
# to look like "no branch yet", the job ran on an empty folder, and the save step force-pushed a fresh history
# over everything (memory.sqlite, grades, timelines). Now:
#   restore: retry; "branch absent" (ls-remote exit 2) is the only case allowed to start empty; any other failure
#            fails the job. Writes data/state/.restored on success.
#   save:    refuses to run unless restore succeeded; keeps a once-a-day copy of the previous state on
#            `state-backup` before replacing `state` (one commit, so the branch doesn't grow without bound).
# Usage: REMOTE=<git url> tools/state.sh restore|save      (REMOTE defaults to origin)
set -uo pipefail
REMOTE="${REMOTE:-origin}"
DIR="${STATE_DIR:-data/state}"
MARK="$DIR/.restored"

SLEEP="${STATE_RETRY_SLEEP:-5}"
retry() { local n=0; until "$@"; do n=$((n + 1)); [ $n -ge 3 ] && return 1; sleep $((n * SLEEP)); done; }

restore() {
  mkdir -p "$DIR"
  local rc=0
  for i in 1 2 3; do
    git ls-remote --exit-code --heads "$REMOTE" state >/dev/null 2>&1; rc=$?
    [ $rc -eq 0 ] || [ $rc -eq 2 ] && break
    sleep $((i * SLEEP))
  done
  if [ $rc -eq 2 ]; then echo "state: no state branch yet, starting empty"; echo new > "$MARK"; return 0; fi
  if [ $rc -ne 0 ]; then echo "state: cannot reach $REMOTE (exit $rc); refusing to run on empty state" >&2; return 1; fi
  retry git fetch -q --depth 1 "$REMOTE" state || { echo "state: fetch failed" >&2; return 1; }
  git archive FETCH_HEAD | tar -x -C "$DIR" || { echo "state: extract failed" >&2; return 1; }
  if git cat-file -e FETCH_HEAD:memory.sqlite 2>/dev/null && [ ! -s "$DIR/memory.sqlite" ]; then
    echo "state: memory.sqlite missing after restore" >&2; return 1
  fi
  git rev-parse FETCH_HEAD > "$MARK"
  echo "state: restored $(cat "$MARK")"
}

save() {
  [ -f "$MARK" ] || { echo "state: restore did not succeed; not saving (would overwrite good state)" >&2; return 1; }
  local prev; prev=$(cat "$MARK")
  rm -f "$MARK"
  local tmp; tmp=$(mktemp -d)
  cp -a "$DIR/." "$tmp/"
  (
    cd "$tmp" || exit 1
    git init -q -b state && git config user.name "lock-desk-bot" && git config user.email "lock-desk-bot@users.noreply.github.com"
    git add -A && git commit -q -m "state $(date -u +%FT%TZ)" || exit 0
    if [ "$prev" != new ]; then
      # once a day, keep the state we started from on state-backup (restore point if something goes wrong)
      last=$(git ls-remote "$REMOTE" refs/heads/state-backup 2>/dev/null | cut -f1)
      day=""; [ -n "$last" ] && git fetch -q --depth 1 "$REMOTE" state-backup && day=$(git log -1 --format=%cs FETCH_HEAD)
      if [ "$day" != "$(date -u +%F)" ]; then
        git fetch -q --depth 1 "$REMOTE" state && git push -q --force "$REMOTE" FETCH_HEAD:refs/heads/state-backup \
          && echo "state: daily backup -> state-backup"
      fi
    fi
    retry git push -q --force "$REMOTE" state
  )
}

case "${1:-}" in
  restore) restore ;;
  save) save ;;
  *) echo "usage: tools/state.sh restore|save" >&2; exit 64 ;;
esac
