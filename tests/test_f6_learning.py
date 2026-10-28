"""Finding 6 (review 2026-10-28): the learning scorecard was mis-graded.
Week 1 (state memory.sqlite): 8 graded 'calls', all 'keep' rows ("counts automatically", no decision), shown as
7 good and 242 points saved, because the counterfactual was the player's next game in ANY week, or 0. Keep rows
have no deadline, so they also overwrote the real pre-deadline call for the same game."""
import datetime as dt, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import learn, memory

memory.STATE = tempfile.mkdtemp(); memory.DB = os.path.join(memory.STATE, "m.sqlite")
con = memory.connect()
now = dt.datetime(2026, 10, 27, 20, tzinfo=dt.timezone.utc)
slot = lambda action, pid, score, tip: {"action": action, "slot": "C", "pid": pid, "name": pid, "detail": "", "score": score,
                                         "bar": 40.0, "gameDate": "2026-10-26", "deadline": {"tip": tip} if tip else None}
learn.record(con, {"week": 2, "slots": [slot("pass", "a", 32.0, "2026-10-28T23:00Z"), slot("keep", "b", 106.0, None)]}, now)
rows = con.execute("SELECT pid, mx_call FROM decisions").fetchall()
assert rows == [("a", "pass")], rows                     # no row for 'keep': nothing was decided
# a later keep for the same game must not overwrite the pass call made before the deadline
learn.record(con, {"week": 2, "slots": [dict(slot("keep", "a", 32.0, None))]}, now + dt.timedelta(days=2))
assert con.execute("SELECT mx_call FROM decisions WHERE pid='a'").fetchone() == ("pass",)

# grading uses the rest of the SAME week, replayed with the engine's stopping rule
# later = his remaining games this week, (score or None if he sat, projected mean)
cf, regret = learn.grade_lock_call(40.0, "lock", [(None, 40.0), (30.0, 40.0)])
assert (cf, regret) == (30.0, -10.0), (cf, regret)          # locking 40 beat what waiting produced
cf, regret = learn.grade_lock_call(40.0, "lock", [(50.0, 40.0), (20.0, 40.0)])
assert (cf, regret) == (50.0, 10.0), (cf, regret)           # waiting would have locked 50: locking cost 10
cf, regret = learn.grade_lock_call(40.0, "pass", [(50.0, 40.0), (20.0, 40.0)])
assert regret == -10.0                                      # passing gained 10
print("ok: finding 6")
