"""Review 2, finding 7a: a corrupt state file stopped every run (alerts included) until fixed by hand.
Restore now swaps a corrupt file for the state-backup copy, or moves it aside (<name>.corrupt) if the backup
is bad too, so the run continues."""
import json, os, sqlite3, subprocess, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SH = os.path.join(ROOT, "tools", "state.sh")
git = lambda *a, cwd: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)

t = tempfile.mkdtemp()
remote = os.path.join(t, "remote.git"); git("init", "-q", "--bare", remote, cwd=t)
def push(branch, files):
    d = tempfile.mkdtemp(); git("init", "-q", "-b", branch, cwd=d)
    for name, content in files.items():
        if name.endswith(".sqlite"):
            c = sqlite3.connect(os.path.join(d, name)); c.execute("CREATE TABLE t(x)"); c.execute("INSERT INTO t VALUES(?)", (content,)); c.commit(); c.close()
        else:
            open(os.path.join(d, name), "w").write(content)
    git("add", "-A", cwd=d); git("commit", "-qm", branch, cwd=d); git("push", "-q", "--force", remote, branch, cwd=d)
push("state-backup", {"memory.sqlite": "backup", "timelines.json": json.dumps({"good": 1}), "news.json": "{broken too"})
push("state", {"memory.sqlite": "today", "timelines.json": '{"truncated": ', "news.json": "{also broken", "claims.json": "[]"})
work = tempfile.mkdtemp(); git("init", "-q", cwd=work)
r = subprocess.run([SH, "restore"], cwd=work, capture_output=True, text=True,
                   env=dict(os.environ, REMOTE=remote, STATE_RETRY_SLEEP="0", STATE_DIR="data/state", GIT_TERMINAL_PROMPT="0"))
print(r.stdout.strip())
S = os.path.join(work, "data", "state")
assert r.returncode == 0, r.stderr
assert json.load(open(os.path.join(S, "timelines.json"))) == {"good": 1}, "corrupt file -> backup copy"
assert not os.path.exists(os.path.join(S, "news.json")) and os.path.exists(os.path.join(S, "news.json.corrupt")), "no good backup -> moved aside"
assert sqlite3.connect(os.path.join(S, "memory.sqlite")).execute("SELECT x FROM t").fetchone() == ("today",), "good files untouched"
print("ok: review 2 finding 7a")
