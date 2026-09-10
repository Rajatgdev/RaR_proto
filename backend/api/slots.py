"""Phase 3: slot generation from the confirmed card, soft holds, and the
double-booking race guard.

Race design (per research): the hold claim is a single atomic conditional
UPDATE with a version bump — one statement, no read-then-write gap. Booking is a
short transaction validating the hold, then INSERT into booking whose
UNIQUE(slot_id) is the final backstop. Two racers => exactly one winner.
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import gcal
from availability import compute_slots
from db.session import get_session
from fairness import fairness_subset
from tzutil import safe_zone

router = APIRouter(prefix="/jobs/{job_id}/slots", tags=["slots"])

UTC = timezone.utc


async def _confirmed_job(db, job_id):
    job = (
        await db.execute(
            text("SELECT session_id, params, status, timezone, hold_ttl_min "
                 "FROM job WHERE id = :id"),
            {"id": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    if job["status"] != "confirmed":
        raise HTTPException(403, "job not confirmed (Gate 1)")
    return job


@router.post("/generate")
async def generate(job_id: int, db: AsyncSession = Depends(get_session)):
    job = await _confirmed_job(db, job_id)
    card = job["params"]
    tz = job["timezone"]

    account = (
        await db.execute(
            text("SELECT id, email, credentials FROM google_account "
                 "ORDER BY updated_at DESC LIMIT 1"))
    ).mappings().one_or_none()
    if account is None:
        raise HTTPException(400, "no Google account connected")

    iv = (
        await db.execute(
            text("SELECT id FROM interviewer WHERE job_id = :j LIMIT 1"), {"j": job_id})
    ).scalar_one_or_none()
    if iv is None:
        iv = (
            await db.execute(
                text("INSERT INTO interviewer (job_id, name, email, calendar_id) "
                     "VALUES (:j, :n, :e, :e) RETURNING id"),
                {"j": job_id,
                 "n": (card.get("interviewers") or [{}])[0].get("name") or "Interviewer",
                 "e": account["email"]})
        ).scalar_one()

    creds = gcal.credentials_from_json(account["credentials"])
    try:
        refreshed = await run_in_threadpool(gcal.ensure_fresh, creds)
    except Exception:
        raise HTTPException(401, "Google connection expired; reconnect required")
    if refreshed:
        await db.execute(
            text("UPDATE google_account SET credentials = CAST(:c AS JSONB), "
                 "updated_at = now() WHERE id = :id"),
            {"c": creds.to_json(), "id": account["id"]})
        await db.commit()

    zone = safe_zone(tz or "Europe/London")
    start_day = date.today()
    days = card["window_days"]
    time_min = datetime.combine(start_day, time(0, 0), zone).astimezone(UTC).isoformat()
    time_max = (datetime.combine(start_day + timedelta(days=days), time(0, 0), zone)
                .astimezone(UTC).isoformat())

    try:
        busy = await run_in_threadpool(
            gcal.free_busy, creds, account["email"], time_min, time_max)
    except Exception as e:
        raise HTTPException(502, f"FreeBusy failed: {e}")

    eligible = compute_slots(
        busy,
        start_day=start_day, num_days=days, tz=tz,
        work_start=time.fromisoformat(card["work_start"]),
        work_end=time.fromisoformat(card["work_end"]),
        duration_min=card["duration_min"], buffer_min=card["buffer_min"],
        now=datetime.now(UTC),
    )
    offers = fairness_subset(eligible)

    await db.execute(
        text("DELETE FROM slot WHERE job_id = :j AND status <> 'booked'"), {"j": job_id})
    created = []
    for s in offers:
        row = (
            await db.execute(
                text("INSERT INTO slot (job_id, interviewer_id, start_ts, end_ts, status) "
                     "VALUES (:j, :iv, :st, :et, 'available') RETURNING id"),
                {"j": job_id, "iv": iv,
                 "st": datetime.fromisoformat(s["start"]),
                 "et": datetime.fromisoformat(s["end"])})
        ).scalar_one()
        created.append({"slot_id": row, "start": s["start"], "end": s["end"]})

    await db.execute(
        text("INSERT INTO event_log (session_id, actor, action, detail) "
             "VALUES (:s,'agent','generated_slots', CAST(:d AS JSONB))"),
        {"s": job["session_id"],
         "d": _json({"eligible": len(eligible), "offered": len(created)})})
    await db.commit()
    return {"eligible": len(eligible), "offered": len(created), "slots": created}


@router.get("")
async def list_slots(job_id: int, db: AsyncSession = Depends(get_session)):
    rows = (
        await db.execute(
            text("SELECT id AS slot_id, start_ts, end_ts, status, hold_expires_at "
                 "FROM slot WHERE job_id = :j ORDER BY start_ts"), {"j": job_id})
    ).mappings().all()
    return [dict(r) for r in rows]


class Hold(BaseModel):
    candidate_id: int


@router.post("/{slot_id}/hold")
async def place_hold(job_id: int, slot_id: int, body: Hold,
                     db: AsyncSession = Depends(get_session)):
    job = await _confirmed_job(db, job_id)
    hold_id = str(uuid.uuid4())
    ttl = int(job["hold_ttl_min"])

    row = (
        await db.execute(
            text(
                "UPDATE slot SET status='held', hold_id=CAST(:h AS UUID), "
                "hold_owner=:c, hold_expires_at = now() + make_interval(mins => :ttl), "
                "version = version + 1 "
                "WHERE id=:sid AND job_id=:j AND "
                "(status='available' OR (status='held' AND hold_expires_at <= now())) "
                "RETURNING id, hold_id, hold_expires_at"),
            {"h": hold_id, "c": body.candidate_id, "ttl": ttl, "sid": slot_id, "j": job_id})
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(409, "slot no longer available")
    await db.commit()
    return {"slot_id": row["id"], "hold_id": str(row["hold_id"]),
            "hold_expires_at": row["hold_expires_at"].isoformat()}


class Book(BaseModel):
    candidate_id: int
    hold_id: str


@router.post("/{slot_id}/book")
async def book(job_id: int, slot_id: int, body: Book,
               db: AsyncSession = Depends(get_session)):
    await _confirmed_job(db, job_id)
    try:
        row = (
            await db.execute(
                text("UPDATE slot SET status='booked' "
                     "WHERE id=:sid AND job_id=:j AND status='held' "
                     "AND hold_id=CAST(:h AS UUID) AND hold_owner=:c "
                     "AND hold_expires_at > now() RETURNING id"),
                {"sid": slot_id, "j": job_id, "h": body.hold_id, "c": body.candidate_id})
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(409, "hold expired or not owned; re-hold required")

        await db.execute(
            text("INSERT INTO booking (candidate_id, slot_id) VALUES (:c, :sid)"),
            {"c": body.candidate_id, "sid": slot_id})
        await db.commit()
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(409, "slot was just booked by someone else")
    return {"slot_id": slot_id, "status": "booked"}


def _json(d):
    import json
    return json.dumps(d)