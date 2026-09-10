"""Phase 4a: Outreach + Approval Gate 2.

Gate 2 is a single approval of the outreach template + the generated slot pool.
Only after approval can the agent send. Sending emails each candidate via
gmail.send and records the outreach row with the Gmail thread_id (so replies
can be matched in 4b). Slots are OFFERED to every candidate but not held at
send time — a slot has a single owner, so the atomic claim at booking
(/replies/{cid}/confirm, accepts status='available') is the race guard, with
UNIQUE(slot_id) as the final backstop (Phase 3).
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import gcal
import outreach_tpl as tpl
from db.session import get_session

router = APIRouter(prefix="/jobs/{job_id}/outreach", tags=["outreach"])


async def _job(db, job_id):
    job = (
        await db.execute(
            text("SELECT id, session_id, params, status, timezone, hold_ttl_min, "
                 "outreach_subject, outreach_body, outreach_approved "
                 "FROM job WHERE id = :id"), {"id": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    return job


async def _account(db):
    acc = (
        await db.execute(
            text("SELECT id, email, credentials FROM google_account "
                 "ORDER BY updated_at DESC LIMIT 1"))
    ).mappings().one_or_none()
    if acc is None:
        raise HTTPException(400, "no Google account connected")
    return acc


@router.get("/template")
async def get_template(job_id: int, db: AsyncSession = Depends(get_session)):
    job = await _job(db, job_id)
    subject = job["outreach_subject"] or tpl.DEFAULT_SUBJECT
    body = job["outreach_body"] or tpl.DEFAULT_BODY
    return {"subject": subject, "body": body, "approved": job["outreach_approved"]}


class Approve(BaseModel):
    subject: str
    body: str


@router.post("/preview")
async def preview(job_id: int, body: Approve, db: AsyncSession = Depends(get_session)):
    """Render the template as the FIRST candidate would receive it — no send.

    Lets the recruiter approve the real email, not the {placeholder} template.
    """
    job = await _job(db, job_id)
    card = job["params"]
    interviewer = (card.get("interviewers") or [{}])[0].get("name") or "the interviewer"
    duration = card.get("duration_min", 30)

    cand = (
        await db.execute(
            text("SELECT name, email, timezone FROM candidate "
                 "WHERE job_id = :j ORDER BY id LIMIT 1"), {"j": job_id})
    ).mappings().one_or_none()
    slots = (
        await db.execute(
            text("SELECT start_ts, end_ts FROM slot "
                 "WHERE job_id = :j AND status IN ('available','held') ORDER BY start_ts"),
            {"j": job_id})
    ).mappings().all()
    slot_dicts = [{"start": s["start_ts"].isoformat(), "end": s["end_ts"].isoformat()}
                  for s in slots]

    try:
        subject, mail_body = tpl.render(
            body.subject, body.body,
            name=cand["name"] if cand else None, interviewer=interviewer,
            job=card.get("job_title", "the role"), duration=duration,
            slots=slot_dicts, tz=(cand["timezone"] if cand else None) or job["timezone"])
    except KeyError as e:
        raise HTTPException(422, f"unknown placeholder {e} in template")

    return {"to": cand["email"] if cand else "(no candidate yet)",
            "subject": subject, "body": mail_body}


@router.post("/approve")
async def approve(job_id: int, body: Approve, db: AsyncSession = Depends(get_session)):
    job = await _job(db, job_id)
    if job["status"] != "confirmed":
        raise HTTPException(403, "job not confirmed (Gate 1)")
    n_slots = (
        await db.execute(
            text("SELECT count(*) FROM slot WHERE job_id = :j AND status = 'available'"),
            {"j": job_id})
    ).scalar_one()
    if n_slots == 0:
        raise HTTPException(422, "no available slots in the pool; generate slots first")

    await db.execute(
        text("UPDATE job SET outreach_subject = :s, outreach_body = :b, "
             "outreach_approved = true WHERE id = :id"),
        {"s": body.subject, "b": body.body, "id": job_id})
    await db.execute(
        text("INSERT INTO event_log (session_id, actor, action, detail) "
             "VALUES (:s,'recruiter','approved_gate2', CAST(:d AS JSONB))"),
        {"s": job["session_id"], "d": json.dumps({"slots": n_slots})})
    await db.commit()
    return {"job_id": job_id, "approved": True, "pool_size": n_slots}


@router.post("/send")
async def send(job_id: int, db: AsyncSession = Depends(get_session)):
    job = await _job(db, job_id)
    if not job["outreach_approved"]:
        raise HTTPException(403, "outreach not approved (Gate 2)")

    acc = await _account(db)
    creds = gcal.credentials_from_json(acc["credentials"])
    try:
        refreshed = await run_in_threadpool(gcal.ensure_fresh, creds)
    except Exception:
        raise HTTPException(401, "Google connection expired; reconnect required")
    if refreshed:
        await db.execute(
            text("UPDATE google_account SET credentials = CAST(:c AS JSONB), "
                 "updated_at = now() WHERE id = :id"),
            {"c": creds.to_json(), "id": acc["id"]})
        await db.commit()

    card = job["params"]
    interviewer = (card.get("interviewers") or [{}])[0].get("name") or "the interviewer"
    duration = card.get("duration_min", 30)

    slots = (
        await db.execute(
            text("SELECT id, start_ts, end_ts FROM slot "
                 "WHERE job_id = :j AND status = 'available' ORDER BY start_ts"),
            {"j": job_id})
    ).mappings().all()
    slot_dicts = [{"start": s["start_ts"].isoformat(), "end": s["end_ts"].isoformat()}
                  for s in slots]
    if not slot_dicts:
        raise HTTPException(422, "no available slots to offer")

    candidates = (
        await db.execute(
            text("SELECT id, name, email, timezone FROM candidate "
                 "WHERE job_id = :j AND status = 'not_contacted' ORDER BY id"),
            {"j": job_id})
    ).mappings().all()
    if not candidates:
        raise HTTPException(422, "no candidates in 'not_contacted' state to email")

    # Option A: offer the same pool to every candidate; do NOT hold at send time.
    # A slot has one owner, so pre-holding can serve only the first candidate.
    # The atomic claim in /replies/{cid}/confirm (accepts status='available') is
    # the race guard, with UNIQUE(slot_id) as the final backstop (Phase 3).
    sent = []
    for c in candidates:
        subject, mail_body = tpl.render(
            job["outreach_subject"], job["outreach_body"],
            name=c["name"], interviewer=interviewer, job=card.get("job_title", "the role"),
            duration=duration, slots=slot_dicts, tz=c["timezone"] or job["timezone"])

        try:
            res = await run_in_threadpool(
                gcal.send_email, creds, to=c["email"], subject=subject, body=mail_body)
        except Exception as e:
            raise HTTPException(502, f"send failed for {c['email']}: {e}")

        await db.execute(
            text("INSERT INTO outreach (candidate_id, thread_id, kind, sent_at) "
                 "VALUES (:c, :t, 'outreach', now())"),
            {"c": c["id"], "t": res["thread_id"]})
        await db.execute(
            text("UPDATE candidate SET status='slots_offered' WHERE id = :id"),
            {"id": c["id"]})
        sent.append({"candidate_id": c["id"], "email": c["email"],
                     "thread_id": res["thread_id"], "offered": len(slot_dicts)})

    await db.execute(
        text("INSERT INTO event_log (session_id, actor, action, detail) "
             "VALUES (:s,'agent','sent_outreach', CAST(:d AS JSONB))"),
        {"s": job["session_id"], "d": json.dumps({"count": len(sent)})})
    await db.commit()
    return {"sent": len(sent), "candidates": sent}