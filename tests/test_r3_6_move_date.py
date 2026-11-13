"""Review 3, section 7: a lineup move was stored under the UTC date of its tip, so a game tipping after 8 pm ET
(00:00+ UTC) was graded against the next day's box score: 49 of 83 move rows on Nov 13 (Jerome's Oct 29 24.0 graded
as 0 under Oct 30). Moves must be stored under the game's US Eastern date, and old rows corrected once."""
import datetime as dt, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import learn, memory

memory.STATE = tempfile.mkdtemp(); memory.DB = os.path.join(memory.STATE, "m.sqlite")
con = memory.connect()
now = dt.datetime(2026, 10, 29, 20, tzinfo=dt.timezone.utc)
plan = {"week": 2, "slots": [{"action": "start", "slot": "G", "pid": "old", "name": "Old", "detail": "",
        "today": {"pid": "j", "name": "Jerome", "tip": "2026-10-30T02:00Z", "mu": 30.0, "move": True}}]}
learn.record(con, plan, now)
d = con.execute("SELECT date FROM decisions WHERE kind='move'").fetchone()[0]
assert d == "2026-10-29", d                      # 7 pm PT / 10 pm ET on Oct 29
# a row stored the old way (UTC date) is moved to the game date
con.execute("INSERT INTO decisions(week,date,slot,idx,pid,kind,score,deadline,made_at) VALUES(2,'2026-10-31','F',1,'k','move',20,'2026-10-31T00:30Z','x')")
learn.fix_move_dates(con)
assert con.execute("SELECT date FROM decisions WHERE pid='k'").fetchone()[0] == "2026-10-30"
assert con.execute("SELECT date FROM decisions WHERE pid='j'").fetchone()[0] == "2026-10-29"
print("ok: review 3 move dates")
# a row already graded under the wrong date is ungraded so it gets graded again
con.execute("INSERT INTO decisions(week,date,slot,idx,pid,kind,score,deadline,made_at,regret) VALUES(2,'2026-11-01','F',2,'m','move',20,'2026-11-01T01:00Z','x',-24.0)")
learn.fix_move_dates(con)
assert con.execute("SELECT date, regret FROM decisions WHERE pid='m'").fetchone() == ("2026-10-31", None)
print("ok: review 3 move dates (regrade)")
