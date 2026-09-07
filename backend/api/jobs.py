import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import normalise as norm
import paramcard
from db.session import get_session

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _log(db, session_id, actor, action, detail):
    await db.execute(
        text("INSERT INTO event_log (session_id, actor, action, detail) "
             "VALUES (:s, :a, :ac, CAST(:d AS JSONB))"),
        {"s": session_id, "a": actor, "ac": action, "d": json.dumps(detail)},
    )


# --- create a job from a plain-English request ---------------------------

class CreateJob(BaseModel):
    request: str
    timezone: str = "Europe/London"


@router.post("")
async def create_job(body: CreateJob, db: AsyncSession = Depends(get_session)):
    card = paramcard.parse_request(body.request)

    session_id = (
        await db.execute(
            text("INSERT INTO session (actor) VALUES ('recruiter') RETURNING id")
        )
    ).scalar_one()
    job_id = (
        await db.execute(
            text("INSERT INTO job (session_id, title, timezone, params, status) "
                 "VALUES (:s, :t, :tz, CAST(:p AS JSONB), 'draft') RETURNING id"),
            {"s": session_id, "t": card["job_title"], "tz": body.timezone,
             "p": json.dumps(card)},
        )
    ).scalar_one()
    await _log(db, session_id, "agent", "parsed_request",
               {"request": body.request, "card": card})
    await db.commit()
    return {"job_id": job_id, "session_id": session_id, "card": card, "status": "draft"}


# --- edit the parameter card (recruiter tweaks before confirming) --------

class UpdateCard(BaseModel):
    card: dict


@router.put("/{job_id}/card")
async def update_card(job_id: int, body: UpdateCard, db: AsyncSession = Depends(get_session)):
    job = (
        await db.execute(text("SELECT session_id, status FROM job WHERE id = :id"),
                         {"id": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    if job["status"] == "confirmed":
        raise HTTPException(409, "job already confirmed; card is locked")

    await db.execute(
        text("UPDATE job SET params = CAST(:p AS JSONB), title = :t WHERE id = :id"),
        {"p": json.dumps(body.card), "t": body.card.get("job_title", "Untitled role"),
         "id": job_id},
    )
    await _log(db, job["session_id"], "recruiter", "edited_card", {"card": body.card})
    await db.commit()
    return {"job_id": job_id, "card": body.card}


# --- candidate intake + normalisation ------------------------------------

class Intake(BaseModel):
    csv: str | None = None
    candidates: list[dict] | None = None  # manual entry: [{name,email,phone,timezone}]


@router.post("/{job_id}/candidates")
async def intake(job_id: int, body: Intake, db: AsyncSession = Depends(get_session)):
    job = (
        await db.execute(text("SELECT session_id, timezone FROM job WHERE id = :id"),
                         {"id": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")

    raw = norm.parse_csv(body.csv) if body.csv else (body.candidates or [])
    if not raw:
        raise HTTPException(422, "no candidates provided")

    result = norm.normalise(raw, job_timezone=job["timezone"])

    # Upsert the ready set; dedupe on (job_id, email) is enforced by the table.
    for c in result["ready"]:
        await db.execute(
            text("INSERT INTO candidate (job_id, name, email, phone, timezone) "
                 "VALUES (:j, :n, :e, :p, :tz) "
                 "ON CONFLICT (job_id, email) DO UPDATE SET "
                 "name = EXCLUDED.name, phone = EXCLUDED.phone, timezone = EXCLUDED.timezone"),
            {"j": job_id, "n": c["name"], "e": c["email"], "p": c["phone"], "tz": c["timezone"]},
        )
    await _log(db, job["session_id"], "agent", "normalised_candidates",
               {"summary": result["summary"], "excluded": result["excluded"]})
    await db.commit()
    return result


# --- Approval Gate 1: hard stop before any calendar is touched -----------

@router.post("/{job_id}/confirm")
async def confirm(job_id: int, db: AsyncSession = Depends(get_session)):
    job = (
        await db.execute(text("SELECT session_id, params, status FROM job WHERE id = :id"),
                         {"id": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    if not job["params"]:
        raise HTTPException(422, "no parameter card to confirm")

    await db.execute(text("UPDATE job SET status = 'confirmed' WHERE id = :id"),
                     {"id": job_id})
    await _log(db, job["session_id"], "recruiter", "confirmed_gate1", {})
    await db.commit()
    return {"job_id": job_id, "status": "confirmed"}


@router.get("/{job_id}")
async def get_job(job_id: int, db: AsyncSession = Depends(get_session)):
    job = (
        await db.execute(
            text("SELECT id, title, timezone, params, status FROM job WHERE id = :id"),
            {"id": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    cands = (
        await db.execute(
            text("SELECT name, email, timezone, status FROM candidate "
                 "WHERE job_id = :id ORDER BY id"),
            {"id": job_id})
    ).mappings().all()
    return {**dict(job), "candidates": [dict(c) for c in cands]}