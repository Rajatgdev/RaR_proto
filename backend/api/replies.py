"""Phase 4b: read a candidate's reply, parse it, and either propose a slot
(high confidence -> Confirm/Edit card) or escalate (low confidence / no match).

This endpoint NEVER books. It records a reply_parse row and, on escalation,
moves the candidate to 'needs_attention'. Booking off a confirmed window is 4c.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import gcal
import reply_parse as rp
from db.session import get_session

router = APIRouter(prefix="/jobs/{job_id}/replies", tags=["replies"])


async def _account(db):
    acc = (
        await db.execute(
            text("SELECT id, email, credentials FROM google_account "
                 "ORDER BY updated_at DESC LIMIT 1"))
    ).mappings().one_or_none()
    if acc is None:
        raise HTTPException(400, "no Google account connected")
    return acc


@router.post("/{candidate_id}/parse")
async def parse_candidate_reply(job_id: int, candidate_id: int,
                                db: AsyncSession = Depends(get_session)):
    job = (
        await db.execute(
            text("SELECT session_id, params, timezone FROM job WHERE id = :j"),
            {"j": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")

    cand = (
        await db.execute(
            text("SELECT id, email, timezone FROM candidate WHERE id = :c AND job_id = :j"),
            {"c": candidate_id, "j": job_id})
    ).mappings().one_or_none()
    if cand is None:
        raise HTTPException(404, "candidate not found")

    thread = (
        await db.execute(
            text("SELECT thread_id FROM outreach WHERE candidate_id = :c "
                 "AND kind = 'outreach' ORDER BY id DESC LIMIT 1"), {"c": candidate_id})
    ).scalar_one_or_none()
    if not thread:
        raise HTTPException(422, "no outreach thread for this candidate")

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

    try:
        reply = await run_in_threadpool(
            gcal.read_latest_reply, creds, thread, acc["email"])
    except Exception as e:
        raise HTTPException(502, f"could not read reply: {e}")
    if reply is None:
        return {"status": "no_reply", "message": "no candidate reply in the thread yet"}

    tz = cand["timezone"] or job["timezone"]

    # Held/available slots owned by (or open to) this candidate — computed BEFORE
    # parsing so the LLM matches the reply against the concrete offered options.
    slot_rows = (
        await db.execute(
            text("SELECT id AS slot_id, start_ts, end_ts, status, hold_owner "
                 "FROM slot WHERE job_id = :j AND status IN ('available','held') "
                 "ORDER BY start_ts"), {"j": job_id})
    ).mappings().all()
    slots = [{"slot_id": s["slot_id"], "start": s["start_ts"].isoformat(),
              "end": s["end_ts"].isoformat()} for s in slot_rows]

    parsed = await run_in_threadpool(
        rp.parse_reply, reply["body"], tz=tz, offered_slots=slots)

    matched = rp.intersect_slots(parsed, slots, tz=tz)
    decision = rp.decide(parsed, matched)
    outcome = "confirmed" if decision["action"] == "confirm" else "escalated"

    await db.execute(
        text("INSERT INTO reply_parse (candidate_id, thread_id, raw_text, windows, "
             "confidence, note, outcome) VALUES (:c,:t,:r,CAST(:w AS JSONB),:conf,:n,:o)"),
        {"c": candidate_id, "t": thread, "r": reply["body"],
         "w": json.dumps(parsed["windows"]), "conf": parsed["confidence"],
         "n": parsed["note"], "o": outcome})

    if decision["action"] == "escalate":
        await db.execute(
            text("UPDATE candidate SET status = 'needs_attention' WHERE id = :c"),
            {"c": candidate_id})
    await db.execute(
        text("INSERT INTO event_log (session_id, actor, action, detail) "
             "VALUES (:s,'agent','parsed_reply', CAST(:d AS JSONB))"),
        {"s": job["session_id"],
         "d": json.dumps({"candidate_id": candidate_id, "outcome": outcome,
                          "confidence": parsed["confidence"], "reason": decision["reason"]})})
    await db.commit()

    return {
        "status": decision["action"],           # 'confirm' | 'escalate'
        "reason": decision["reason"],
        "reply_from": reply["from"],
        "reply_body": reply["body"],
        "confidence": parsed["confidence"],
        "is_availability_answer": parsed["is_availability_answer"],
        "note": parsed["note"],
        "windows": parsed["windows"],
        "proposed_slots": [
            {"slot_id": s["slot_id"], "start": s["start"], "end": s["end"]}
            for s in matched],
    }