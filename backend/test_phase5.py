"""Pure Phase 5 checks: python test_phase5.py"""
from datetime import datetime, timedelta, timezone

from sweep_logic import followup_is_due, within_working_hours

UTC = timezone.utc


def test_working_hours_weekday_inside():
    now = datetime(2026, 9, 9, 8, 0, tzinfo=UTC)  # Wed 09:00 London (BST +1)
    assert within_working_hours(now, tz="Europe/London", work_start="09:00", work_end="17:00")


def test_working_hours_outside():
    now = datetime(2026, 9, 9, 20, 0, tzinfo=UTC)  # 21:00 London
    assert not within_working_hours(now, tz="Europe/London", work_start="09:00", work_end="17:00")


def test_working_hours_weekend_skipped():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)  # Saturday
    assert not within_working_hours(now, tz="Europe/London", work_start="09:00", work_end="17:00")


def _cand(**kw):
    base = {"status": "slots_offered", "sent_at": datetime(2026, 9, 9, 10, 0, tzinfo=UTC),
            "followup_sent_at": None}
    base.update(kw)
    return base


def test_due_after_interval():
    now = datetime(2026, 9, 9, 10, 3, tzinfo=UTC)  # 3 min later, after_min=2
    assert followup_is_due(_cand(), now=now, after_min=2)


def test_not_due_before_interval():
    now = datetime(2026, 9, 9, 10, 1, tzinfo=UTC)  # only 1 min
    assert not followup_is_due(_cand(), now=now, after_min=2)


def test_only_one_followup():
    now = datetime(2026, 9, 9, 10, 30, tzinfo=UTC)
    already = _cand(followup_sent_at=datetime(2026, 9, 9, 10, 5, tzinfo=UTC))
    assert not followup_is_due(already, now=now, after_min=2)  # never a second


def test_replied_or_booked_not_due():
    now = datetime(2026, 9, 9, 11, 0, tzinfo=UTC)
    assert not followup_is_due(_cand(status="confirmed"), now=now, after_min=2)
    assert not followup_is_due(_cand(status="needs_attention"), now=now, after_min=2)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("all phase 5 pure tests passed")