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


# --- list all jobs (sidebar of job-chats) -------------------------------

@router.get("")
async def list_jobs(db: AsyncSession = Depends(get_session)):
    """All jobs with per-state candidate counts, newest first — powers the
    job-chat sidebar."""
    rows = (
        await db.execute(
            text(
                "SELECT j.id, j.title, j.status, j.timezone, j.created_at, "
                "count(c.id) AS candidates, "
                "count(c.id) FILTER (WHERE c.status = 'confirmed') AS confirmed, "
                "count(c.id) FILTER (WHERE c.status = 'reply_received') AS to_review, "
                "count(c.id) FILTER (WHERE c.status = 'needs_attention') AS needs_attention "
                "FROM job j "
                "LEFT JOIN candidate c ON c.job_id = j.id "
                "GROUP BY j.id ORDER BY j.created_at DESC"))
    ).mappings().all()
    return [dict(r) for r in rows]


# --- job event timeline (chat thread replay) ----------------------------

@router.get("/{job_id}/events")
async def job_events(job_id: int, db: AsyncSession = Depends(get_session)):
    """The job's durable action log, oldest first — the chat thread replays this
    so a reopened job shows its true history (not lost React state)."""
    sid = (
        await db.execute(text("SELECT session_id FROM job WHERE id=:j"), {"j": job_id})
    ).scalar_one_or_none()
    if sid is None:
        raise HTTPException(404, "job not found")
    rows = (
        await db.execute(
            text("SELECT ts, actor, action, detail FROM event_log "
                 "WHERE session_id=:s ORDER BY ts ASC"), {"s": sid})
    ).mappings().all()
    return [{"ts": r["ts"].isoformat(), "actor": r["actor"],
             "action": r["action"], "detail": r["detail"]} for r in rows]


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

    # Editing after confirmation re-opens Gate 1: the job drops back to draft
    # and the recruiter must confirm again before any calendar is touched.
    await db.execute(
        text("UPDATE job SET params = CAST(:p AS JSONB), title = :t, status = 'draft' "
             "WHERE id = :id"),
        {"p": json.dumps(body.card), "t": body.card.get("job_title", "Untitled role"),
         "id": job_id},
    )
    await _log(db, job["session_id"], "recruiter", "edited_card", {"card": body.card})
    await db.commit()
    return {"job_id": job_id, "card": body.card, "status": "draft"}


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
    # Persist how many rows are still faulty so Gate 1 can refuse to confirm.
    await db.execute(
        text("UPDATE job SET excluded_count = :n WHERE id = :id"),
        {"n": len(result["excluded"]), "id": job_id},
    )
    await _log(db, job["session_id"], "agent", "normalised_candidates",
               {"summary": result["summary"], "excluded": result["excluded"]})
    await db.commit()
    return result


# --- Approval Gate 1: hard stop before any calendar is touched -----------

@router.post("/{job_id}/confirm")
async def confirm(job_id: int, db: AsyncSession = Depends(get_session)):
    job = (
        await db.execute(
            text("SELECT session_id, params, status, excluded_count FROM job WHERE id = :id"),
            {"id": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    if not job["params"]:
        raise HTTPException(422, "no parameter card to confirm")

    n_candidates = (
        await db.execute(
            text("SELECT count(*) FROM candidate WHERE job_id = :id"), {"id": job_id})
    ).scalar_one()
    if n_candidates == 0:
        raise HTTPException(422, "add at least one candidate before confirming")
    if job["excluded_count"] > 0:
        raise HTTPException(
            422,
            f"{job['excluded_count']} candidate row(s) need fixing; "
            "correct the CSV and re-run Normalise before confirming",
        )

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
            text("SELECT id, name, email, timezone, status FROM candidate "
                 "WHERE job_id = :id ORDER BY id"),
            {"id": job_id})
    ).mappings().all()
    return {**dict(job), "candidates": [dict(c) for c in cands]}