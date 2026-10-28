"""Finding 8 (review 2026-10-28): one failed fetch could wipe all saved state.
update.yml restored state only `if git ls-remote ...`, so a transient failure looked like 'no branch yet'; the job
ran on an empty folder and the save step force-pushed a fresh history over memory.sqlite, grades and timelines.
Also, the _load helpers turned a corrupt JSON file into defaults that were then saved over it."""
import json, os, subprocess, sys, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
SH = os.path.join(ROOT, "tools", "state.sh")
assert os.path.exists(SH), "tools/state.sh (guarded restore/save) missing"

def git(*a, cwd):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)

t = tempfile.mkdtemp()
remote, seed, work = (os.path.join(t, x) for x in ("remote.git", "seed", "work"))
git("init", "-q", "--bare", remote, cwd=t)
os.makedirs(seed); git("init", "-q", "-b", "state", cwd=seed)
open(os.path.join(seed, "memory.sqlite"), "wb").write(b"SQLite format 3\0" + b"x" * 100)
json.dump({"rotowire": {"n": 400}}, open(os.path.join(seed, "expert_scores_v2.json"), "w"))
git("-c", "user.name=t", "-c", "user.email=t@t", "add", "-A", cwd=seed)
git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed", cwd=seed)
git("push", "-q", remote, "state", cwd=seed)
os.makedirs(work); git("init", "-q", cwd=work)
env = dict(os.environ, STATE_RETRY_SLEEP="0", STATE_DIR="data/state", GIT_TERMINAL_PROMPT="0")
run = lambda cmd, remote_url: subprocess.run([SH, cmd], cwd=work, env=dict(env, REMOTE=remote_url), capture_output=True, text=True)
remote_tree = lambda: subprocess.run(["git", "ls-tree", "--name-only", "state"], cwd=remote, capture_output=True, text=True).stdout.split()

# 1) remote unreachable: restore fails, save refuses, the good state survives
r = run("restore", "file:///nonexistent/repo.git"); assert r.returncode != 0, r.stdout
r = run("save", "file:///nonexistent/repo.git"); assert r.returncode != 0
assert "memory.sqlite" in remote_tree()
# 2) normal cycle: restore brings memory.sqlite back; save replaces state and keeps a daily backup
r = run("restore", remote); assert r.returncode == 0, r.stderr
assert os.path.getsize(os.path.join(work, "data/state/memory.sqlite")) > 0
open(os.path.join(work, "data/state/new.json"), "w").write("{}")
r = run("save", remote); assert r.returncode == 0, r.stderr
assert {"memory.sqlite", "new.json"} <= set(remote_tree())
assert ".restored" not in remote_tree()
backup = subprocess.run(["git", "ls-tree", "--name-only", "state-backup"], cwd=remote, capture_output=True, text=True).stdout.split()
assert "memory.sqlite" in backup and "new.json" not in backup, backup
# 3) save without a restore in this run is refused
assert run("save", remote).returncode != 0
# 4) corrupt JSON fails loudly instead of being reset to defaults
from app import experts
experts.STATE = tempfile.mkdtemp()
open(os.path.join(experts.STATE, "x.json"), "w").write("{not json")
try:
    experts._load("x.json", {}); raise AssertionError("corrupt file was silently replaced by defaults")
except json.JSONDecodeError:
    pass
assert experts._load("missing.json", {"d": 1}) == {"d": 1}
print("ok: finding 8")
