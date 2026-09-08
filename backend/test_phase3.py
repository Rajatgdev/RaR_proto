"""Pure Phase 3 checks: python test_phase3.py"""
from datetime import datetime, timedelta

from fairness import MAX_OFFERS, _bucket, fairness_subset


def _mk(day_offsets_and_hours):
    base = datetime(2026, 9, 7, 0, 0)  # Monday
    out = []
    for d, h in day_offsets_and_hours:
        start = base + timedelta(days=d, hours=h)
        out.append({"start": start.isoformat(), "end": (start + timedelta(minutes=30)).isoformat()})
    return sorted(out, key=lambda s: s["start"])


def test_cap_is_five():
    # 8 slots all on one day -> capped at 5
    slots = _mk([(0, 9 + i) for i in range(8)])
    picked = fairness_subset(slots)
    assert len(picked) == MAX_OFFERS


def test_small_pool_passes_through():
    slots = _mk([(0, 9), (1, 10), (2, 11)])
    assert fairness_subset(slots) == slots


def test_spreads_across_days_before_doubling_up():
    # 3 days, 4 slots each. Cap 5 should hit all 3 days, not 5-from-one-day.
    slots = _mk([(d, 9 + h) for d in range(3) for h in range(4)])
    picked = fairness_subset(slots)
    days = {s["start"][:10] for s in picked}
    assert len(picked) == 5
    assert len(days) == 3  # every day represented


def test_bucket_boundaries():
    assert _bucket(datetime(2026, 9, 7, 9)) == "early_am"
    assert _bucket(datetime(2026, 9, 7, 12)) == "late_am"
    assert _bucket(datetime(2026, 9, 7, 14)) == "early_pm"
    assert _bucket(datetime(2026, 9, 7, 16)) == "late_pm"


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("all phase 3 pure tests passed")