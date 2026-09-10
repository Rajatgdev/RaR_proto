"""Pure decision logic for the Phase 5 sweep. No I/O so it's testable."""
from datetime import datetime, time
from tzutil import safe_zone


def within_working_hours(now: datetime, *, tz: str, work_start: str, work_end: str,
                         weekdays_only: bool = True) -> bool:
    local = now.astimezone(safe_zone(tz))
    if weekdays_only and local.weekday() >= 5:
        return False
    ws = time.fromisoformat(work_start)
    we = time.fromisoformat(work_end)
    return ws <= local.time() < we


def followup_is_due(candidate: dict, *, now: datetime, after_min: int) -> bool:
    if candidate.get("status") != "slots_offered":
        return False
    if candidate.get("followup_sent_at") is not None:
        return False
    sent_at = candidate.get("sent_at")
    if sent_at is None:
        return False
    elapsed_min = (now - sent_at).total_seconds() / 60.0
    return elapsed_min >= after_min