"""tools/step.sh records failures of non-critical steps (instead of '|| echo') and never blocks the publish."""
import json, os, subprocess, tempfile
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
d = tempfile.mkdtemp()
run = lambda *cmd: subprocess.run([os.path.join(root, "tools", "step.sh"), *cmd], cwd=d, capture_output=True, text=True)
assert run("good", "true").returncode == 0
r = run("bad", "python3", "-c", "import sys; print('boom', file=sys.stderr); sys.exit(3)")
assert r.returncode == 0, "a failed step must not stop the site from publishing"
h = json.load(open(os.path.join(d, "site/static/health.json")))
assert h["good"]["ok"] is True and h["bad"]["ok"] is False and "boom" in h["bad"]["error_tail"][-1]
assert json.load(open(os.path.join(d, "data/state/step_health.json")))["bad"]["ok"] is False
print("ok: step health")
