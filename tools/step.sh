#!/usr/bin/env bash
# Run a non-critical job step without blocking the site publish, but RECORD the outcome (review finding 8:
# '|| echo' kept the job green and hid failures). Appends {step, ok, at, error_tail} to site/static/health.json
# (shown as a warning on the site) and data/state/step_health.json.
# Usage: tools/step.sh <name> <command...>
name="$1"; shift
log=$(mktemp)
"$@" 2> >(tee "$log" >&2)
rc=$?
python3 - "$name" "$rc" "$log" <<'PY'
import json, os, sys, datetime as dt
name, rc, log = sys.argv[1], int(sys.argv[2]), sys.argv[3]
tail = open(log, errors="replace").read().strip().splitlines()[-6:]
entry = {"step": name, "ok": rc == 0, "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
         "error_tail": tail if rc else []}
for path in ("site/static/health.json", "data/state/step_health.json"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        cur = json.load(open(path))
    except Exception:
        cur = {}
    cur[name] = entry
    json.dump(cur, open(path, "w"), indent=1)
PY
[ $rc -ne 0 ] && echo "::warning::$name failed (exit $rc); site still publishes"
exit 0
