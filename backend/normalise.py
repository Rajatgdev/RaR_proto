"""Candidate normalisation: validate + dedupe an intake set before anything is
done with it. Pure functions, no I/O — the route persists the result.
"""
import csv
import io
import re

# Deliberately simple, not RFC 5322. Good enough to flag obviously-bad addresses.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(email: str | None) -> bool:
    return bool(email and _EMAIL_RE.match(email.strip()))


def parse_csv(text: str) -> list[dict]:
    """Accept a CSV with name/email[/phone/timezone] headers (case-insensitive)."""
    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        norm = { (k or "").strip().lower(): (v or "").strip() for k, v in row.items() }
        rows.append({
            "name": norm.get("name") or None,
            "email": norm.get("email") or None,
            "phone": norm.get("phone") or None,
            "timezone": norm.get("timezone") or None,
        })
    return rows


def normalise(raw: list[dict], *, job_timezone: str) -> dict:
    """Return {ready, excluded, summary}.

    ready:    valid, deduped candidates (timezone defaulted to the job's)
    excluded: rows dropped, each with a reason
    """
    ready: list[dict] = []
    excluded: list[dict] = []
    seen: set[str] = set()

    for row in raw:
        email = (row.get("email") or "").strip().lower()
        if not valid_email(email):
            excluded.append({**row, "reason": "missing or malformed email"})
            continue
        if email in seen:
            excluded.append({**row, "reason": "duplicate email in this job"})
            continue
        seen.add(email)
        ready.append({
            "name": row.get("name") or None,
            "email": email,
            "phone": row.get("phone") or None,
            "timezone": row.get("timezone") or job_timezone,
            "timezone_assumed": not row.get("timezone"),
        })

    n_ready, n_bad = len(ready), len(excluded)
    parts = [f"{n_ready} candidate{'s' if n_ready != 1 else ''} ready"]
    if n_bad:
        parts.append(f"{n_bad} need{'s' if n_bad == 1 else ''} attention")
    summary = ", ".join(parts)
    return {"ready": ready, "excluded": excluded, "summary": summary}