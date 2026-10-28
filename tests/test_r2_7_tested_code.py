"""Review 2, finding 7b: the 15-minute job ran whatever was on main, even a commit that failed Tests.
tools/tested_code.sh checks out the code of the newest commit that passed (a stand-in `gh` reports it here)."""
import os, subprocess, tempfile
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SH = os.path.join(ROOT, "tools", "tested_code.sh")
git = lambda *a, cwd: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

t = tempfile.mkdtemp()
remote, work = os.path.join(t, "remote.git"), os.path.join(t, "work")
git("init", "-q", "--bare", remote, cwd=t)
git("init", "-q", "-b", "main", work, cwd=t)
for d in ("app", "site", "tools", "worker"):
    os.makedirs(os.path.join(work, d))
open(os.path.join(work, "requirements.txt"), "w").write("numpy\n")
open(os.path.join(work, "app", "run.py"), "w").write("good\n")
for d in ("site", "tools", "worker"):
    open(os.path.join(work, d, "x"), "w").write("x\n")
git("add", "-A", cwd=work); git("commit", "-qm", "good", cwd=work)
good = git("rev-parse", "HEAD", cwd=work)
open(os.path.join(work, "app", "run.py"), "w").write("broken\n")
git("commit", "-qam", "broken", cwd=work)
git("remote", "add", "origin", remote, cwd=work); git("push", "-q", "origin", "main", cwd=work)
git("config", "uploadpack.allowReachableSHA1InWant", "true", cwd=remote)
bin_ = os.path.join(t, "bin"); os.makedirs(bin_)
open(os.path.join(bin_, "gh"), "w").write(f"#!/bin/sh\necho {good}\n"); os.chmod(os.path.join(bin_, "gh"), 0o755)
env = dict(os.environ, PATH=bin_ + os.pathsep + os.environ["PATH"], GITHUB_REPOSITORY="o/r")
r = subprocess.run([SH], cwd=work, env=env, capture_output=True, text=True)
print(r.stdout.strip())
assert r.returncode == 0, r.stderr
assert open(os.path.join(work, "app", "run.py")).read() == "good\n", "must run the last commit that passed Tests"
# when HEAD itself passed, nothing changes
open(os.path.join(bin_, "gh"), "w").write("#!/bin/sh\ngit rev-parse HEAD\n")
git("checkout", "-q", "HEAD", "--", "app", cwd=work)
r = subprocess.run([SH], cwd=work, env=env, capture_output=True, text=True)
assert "passed Tests" in r.stdout and open(os.path.join(work, "app", "run.py")).read() == "broken\n"
print("ok: review 2 finding 7b")
