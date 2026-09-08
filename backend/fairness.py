"""Fairness subset: from all eligible slots, pick the offer pool (max 5) that's
spread across days and times rather than clustered in one morning.

Pure function, no I/O. Fairness rules (build plan): prefer spreading across
distinct days first, then across distinct time-of-day buckets, earliest first
as the tiebreak so offers stay soon.
"""
from datetime import datetime

MAX_OFFERS = 5


def _bucket(dt: datetime) -> str:
    h = dt.hour
    if h < 11:
        return "early_am"
    if h < 13:
        return "late_am"
    if h < 15:
        return "early_pm"
    return "late_pm"


def fairness_subset(slots: list[dict], *, cap: int = MAX_OFFERS) -> list[dict]:
    """slots: [{start, end, ...}] ISO strings, assumed sorted earliest-first.

    Round-robin across days: take the earliest still-unused slot from each day
    in turn, preferring a time-of-day bucket not yet used that day, until we hit
    the cap or run out.
    """
    if len(slots) <= cap:
        return list(slots)

    by_day: dict[str, list[dict]] = {}
    for s in slots:
        day = s["start"][:10]  # YYYY-MM-DD
        by_day.setdefault(day, []).append(s)

    days = sorted(by_day)
    chosen: list[dict] = []
    used_buckets: dict[str, set[str]] = {d: set() for d in days}
    exhausted: set[str] = set()

    while len(chosen) < cap and len(exhausted) < len(days):
        for day in days:
            if len(chosen) >= cap:
                break
            if day in exhausted:
                continue
            pool = by_day[day]
            pick = next(
                (s for s in pool if _bucket(datetime.fromisoformat(s["start"])) not in used_buckets[day]),
                None,
            )
            if pick is None:
                pick = pool[0]
            pool.remove(pick)
            used_buckets[day].add(_bucket(datetime.fromisoformat(pick["start"])))
            chosen.append(pick)
            if not pool:
                exhausted.add(day)

    chosen.sort(key=lambda s: s["start"])
    return chosen