"""Pure availability math: turn FreeBusy busy intervals into offerable slots.

No I/O here so it can be tested without Google. All datetimes are timezone-aware.
FreeBusy busy intervals are start-inclusive / end-exclusive; we treat them so.
"""
from datetime import date, datetime, time, timedelta, timezone
from tzutil import safe_zone

UTC = timezone.utc


def parse_rfc3339(s: str) -> datetime:
    """Parse a Google RFC3339 timestamp to an aware UTC datetime."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for s, e in sorted(intervals):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def free_gaps(
    window_start: datetime, window_end: datetime, busy: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    """Complement of busy intervals inside [window_start, window_end)."""
    gaps: list[tuple[datetime, datetime]] = []
    cursor = window_start
    for bs, be in busy:
        if be <= window_start or bs >= window_end:
            continue
        bs, be = max(bs, window_start), min(be, window_end)
        if bs > cursor:
            gaps.append((cursor, bs))
        cursor = max(cursor, be)
    if cursor < window_end:
        gaps.append((cursor, window_end))
    return gaps


def working_days(start: date, num_days: int):
    """Yield weekday dates (Mon-Fri) across num_days calendar days from start."""
    for i in range(num_days):
        d = start + timedelta(days=i)
        if d.weekday() < 5:
            yield d


def compute_slots(
    busy_rfc3339: list[dict],
    *,
    start_day: date,
    num_days: int,
    tz: str,
    work_start: time,
    work_end: time,
    duration_min: int,
    buffer_min: int,
    now: datetime | None = None,
    lead_min: int = 60,
) -> list[dict]:
    """Return offerable slots as [{start, end}] ISO-8601 UTC strings.

    Clips to per-day working hours in `tz`, subtracts busy, cuts fixed duration
    slots with `buffer_min` between them, and drops any slot starting before
    `now + lead_min` so past / too-soon times are never offered.
    """
    zone = safe_zone(tz)
    if now is None:
        now = datetime.now(UTC)
    earliest = now + timedelta(minutes=lead_min)
    busy = merge_intervals(
        [(parse_rfc3339(b["start"]), parse_rfc3339(b["end"])) for b in busy_rfc3339]
    )
    dur, buf = timedelta(minutes=duration_min), timedelta(minutes=buffer_min)

    slots: list[dict] = []
    for d in working_days(start_day, num_days):
        day_start = datetime.combine(d, work_start, zone).astimezone(UTC)
        day_end = datetime.combine(d, work_end, zone).astimezone(UTC)
        for gs, ge in free_gaps(day_start, day_end, busy):
            t = gs
            while t + dur <= ge:
                if t >= earliest:  # never offer a past / too-soon slot
                    slots.append({"start": t.isoformat(), "end": (t + dur).isoformat()})
                t = t + dur + buf
    return slots