"""Chunk C checks (mocked I/O): python test_reschedule_c.py

The load-bearing test: if creating the NEW event fails mid-saga, the OLD booking
must survive intact and the newly-claimed slot must be rolled back to available —
never a double-book, never a lost interview (EXA's book-new-before-cancel-old).
"""
import asyncio
import datetime as dt
from unittest.mock import patch


class Rows:
    def __init__(self, r): self.r = r
    def mappings(self): return self
    def one_or_none(self): return self.r
    def scalar_one_or_none(self): return self.r
    def all(self): return self.r if isinstance(self.r, list) else [self.r]


class FakeDB:
    def __init__(self, script):
        self.script = script
        self.i = 0
        self.writes = []
        self.committed = 0

    async def execute(self, clause, params=None):
        sql = str(clause)
        up = sql.strip().upper()
        if up.startswith(("INSERT", "UPDATE")):
            self.writes.append(sql.split("\n")[0][:60])
        r = self.script[self.i] if self.i < len(self.script) else Rows(None)
        self.i += 1
        return r

    async def commit(self): self.committed += 1


def _run(coro): return asyncio.new_event_loop().run_until_complete(coro)
async def _threadpool(fn, *a, **k): return fn(*a, **k)
def _boom(*a, **k): raise RuntimeError("calendar down")

UTC = dt.timezone.utc
_start = dt.datetime(2026, 9, 14, 8, 0, tzinfo=UTC)


def _script_up_to_claim():
    return [
        Rows({"session_id": 1, "params": {"job_title": "SW", "duration_min": 30},
              "timezone": "Europe/Dublin"}),                                     # job
        Rows({"id": 7, "name": "R", "email": "r@x", "timezone": None, "status": "confirmed"}),  # cand
        Rows({"id": 3, "slot_id": 10, "gcal_event_id": "old_ev", "start_ts": _start}),  # OLD booking
        Rows({"id": 20, "start_ts": _start, "end_ts": _start}),                  # NEW slot
        Rows({"id": 1, "email": "agent@x", "credentials": "{}"}),                # account
        Rows({"name": "Jamie", "email": "jamie@x"}),                            # interviewer
        Rows(20),                                                               # STEP1 claim -> returns id
    ]


def test_failed_new_event_keeps_old_booking():
    import api.replies as replies
    db = FakeDB(_script_up_to_claim())

    with patch.object(replies.gcal, "credentials_from_json", lambda *_: object()), \
         patch.object(replies, "run_in_threadpool", new=_threadpool), \
         patch.object(replies.gcal, "ensure_fresh", lambda *_: False), \
         patch.object(replies.gcal, "create_event_with_meet", _boom):
        try:
            _run(replies.rebook_booking(5, 7, replies.Rebook(slot_id=20), db))
            assert False, "should have raised 502"
        except replies.HTTPException as e:
            assert e.status_code == 502

    # The ONLY write after the failed event must be the new-slot rollback.
    # There must be NO booking insert, NO old-slot free, NO supersede.
    joined = " | ".join(db.writes)
    assert "INSERT INTO booking" not in joined, joined
    assert "SET status='superseded'" not in joined
    # exactly the claim (UPDATE slot ... booked) + the rollback (UPDATE slot ... available)
    assert any("UPDATE slot SET status='available'" in w for w in db.writes), db.writes
    print("test 1 PASS — new-event failure rolls back new slot, OLD booking intact")


def test_rebook_refuses_same_slot():
    import api.replies as replies
    db = FakeDB([
        Rows({"session_id": 1, "params": {}, "timezone": "Europe/Dublin"}),     # job
        Rows({"id": 7, "name": "R", "email": "r@x", "timezone": None, "status": "confirmed"}),  # cand
        Rows({"id": 3, "slot_id": 10, "gcal_event_id": "old_ev", "start_ts": _start}),  # OLD booking (slot 10)
    ])
    try:
        _run(replies.rebook_booking(5, 7, replies.Rebook(slot_id=10), db))  # same slot!
        assert False, "should 409"
    except replies.HTTPException as e:
        assert e.status_code == 409
    assert db.writes == []
    print("test 2 PASS — rebook refuses the already-booked slot (no writes)")


def test_reschedule_tool_proposes_only():
    import asyncio as _a, agent_tools as at
    async def m():
        class Boom:
            async def execute(self, *a, **k): raise AssertionError("tool touched DB")
            async def commit(self): raise AssertionError("committed")
        r = await at.run_tool("reschedule_booking", Boom(), 5, {"candidate_id": 7, "slot_id": 20})
        assert r["card"]["action"] == "rebook"
        assert r["card"]["endpoint"] == "/jobs/5/replies/7/rebook"
        assert r["card"]["payload"] == {"slot_id": 20}
    _a.new_event_loop().run_until_complete(m())
    print("test 3 PASS — reschedule_booking proposes a card, no DB touched")


if __name__ == "__main__":
    test_failed_new_event_keeps_old_booking()
    test_rebook_refuses_same_slot()
    test_reschedule_tool_proposes_only()
    print("all chunk C tests passed")