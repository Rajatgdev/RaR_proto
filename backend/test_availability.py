"""Runnable check: python -m pytest test_availability.py  (or just run it)."""
from datetime import date, time, datetime, timezone

from availability import compute_slots


def _slots(busy):
    return compute_slots(
        busy,
        start_day=date(2026, 9, 7),  # Monday
        num_days=1,
        tz="UTC",
        work_start=time(9, 0),
        work_end=time(17, 0),
        duration_min=30,
        buffer_min=10,
        now=datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc),
    )


def test_empty_calendar_produces_slots():
    slots = _slots([])
    assert slots, "expected slots on a free day"
    assert slots[0]["start"] == "2026-09-07T09:00:00+00:00"
    assert slots[1]["start"] == "2026-09-07T09:40:00+00:00"


def test_busy_block_removes_that_slot():
    free = {s["start"] for s in _slots([])}
    busy = {s["start"] for s in _slots([{"start": "2026-09-07T09:00:00Z", "end": "2026-09-07T09:30:00Z"}])}
    assert "2026-09-07T09:00:00+00:00" in free
    assert "2026-09-07T09:00:00+00:00" not in busy


def test_weekend_is_skipped():
    slots = compute_slots(
        [], start_day=date(2026, 9, 12), num_days=1, tz="UTC",
        work_start=time(9, 0), work_end=time(17, 0), duration_min=30, buffer_min=10,
        now=datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc),
    )
    assert slots == []


if __name__ == "__main__":
    test_empty_calendar_produces_slots()
    test_busy_block_removes_that_slot()
    test_weekend_is_skipped()
    print("all availability tests passed")