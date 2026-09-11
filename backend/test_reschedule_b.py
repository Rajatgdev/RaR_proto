"""Chunk B checks (mocked I/O): python test_reschedule_b.py"""
import asyncio
import types
from unittest.mock import patch


class Rows:
    def __init__(self, r): self.r = r
    def mappings(self): return self
    def one_or_none(self): return self.r
    def scalar_one_or_none(self): return self.r
    def all(self): return self.r if isinstance(self.r, list) else [self.r]


class FakeDB:
    def __init__(self, script):
        self.script = script      # list of Rows served in order
        self.i = 0
        self.writes = []
        self.committed = False

    async def execute(self, clause, params=None):
        sql = str(clause)
        if sql.strip().upper().startswith(("INSERT", "UPDATE")):
            self.writes.append(sql)
        r = self.script[self.i] if self.i < len(self.script) else Rows(None)
        self.i += 1
        return r

    async def commit(self): self.committed = True


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_cancel_refuses_when_no_active_booking():
    import api.replies as replies
    # job row, candidate row (confirmed), booking row = None -> 409
    db = FakeDB([
        Rows({"session_id": 1, "params": {}, "timezone": "Europe/Dublin"}),      # job
        Rows({"id": 7, "name": "R", "email": "r@x", "timezone": None, "status": "confirmed"}),  # cand
        Rows(None),                                                              # no active booking
    ])
    try:
        _run(replies.cancel_booking(5, 7, replies.Cancel(), db))
        assert False, "should have raised 409"
    except replies.HTTPException as e:
        assert e.status_code == 409
    # no destructive writes happened
    assert db.writes == [], f"unexpected writes: {db.writes}"
    print("test 1 PASS — cancel refuses a candidate with no active booking (no writes)")


def test_cancel_aborts_before_db_if_event_delete_fails():
    import api.replies as replies
    db = FakeDB([
        Rows({"session_id": 1, "params": {"job_title": "SW"}, "timezone": "Europe/Dublin"}),  # job
        Rows({"id": 7, "name": "R", "email": "r@x", "timezone": None, "status": "confirmed"}),  # cand
        Rows({"id": 3, "slot_id": 99, "gcal_event_id": "ev1",
              "start_ts": __import__("datetime").datetime(2026, 9, 14, 8, 0,
                          tzinfo=__import__("datetime").timezone.utc)}),          # active booking
        Rows({"id": 1, "email": "agent@x", "credentials": "{}"}),                 # account
    ])

    with patch.object(replies.gcal, "credentials_from_json", lambda *_: object()), \
         patch.object(replies, "run_in_threadpool", new=_threadpool), \
         patch.object(replies.gcal, "ensure_fresh", lambda *_: False), \
         patch.object(replies.gcal, "delete_event", _boom):
        try:
            _run(replies.cancel_booking(5, 7, replies.Cancel(), db))
            assert False, "should have raised 502"
        except replies.HTTPException as e:
            assert e.status_code == 502
    # THE INVARIANT: event delete failed -> NO db writes, booking stays active.
    assert db.writes == [], f"state was mutated despite failed event delete: {db.writes}"
    print("test 2 PASS — failed event delete aborts before any DB write (booking stays active)")


async def _threadpool(fn, *a, **k):
    return fn(*a, **k)


def _boom(*a, **k):
    raise RuntimeError("calendar down")


if __name__ == "__main__":
    test_cancel_refuses_when_no_active_booking()
    test_cancel_aborts_before_db_if_event_delete_fails()
    print("all chunk B tests passed")