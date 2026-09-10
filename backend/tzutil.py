"""Single source of truth for turning a (possibly blank/invalid) tz string into a
ZoneInfo. Every ZoneInfo(...) in the codebase routes through here so a bad or
empty timezone in the DB can never 500 a request again.
"""
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Europe/London"


def safe_zone(tz: str | None) -> ZoneInfo:
    """Return a ZoneInfo, falling back to DEFAULT_TZ for blank/unknown keys."""
    if not tz or not str(tz).strip():
        return ZoneInfo(DEFAULT_TZ)
    try:
        return ZoneInfo(str(tz).strip())
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def safe_tz_name(tz: str | None) -> str:
    """Return a valid tz string (the input if valid, else DEFAULT_TZ)."""
    return str(safe_zone(tz).key)