"""Phase 4b/4c: read a candidate's reply, parse it, propose or escalate (4b);
and on an explicit recruiter confirm, book the slot with a real Meet event and
send confirmations (4c).

Parsing NEVER books. Booking happens only in confirm_booking, behind an explicit
recruiter click — the agent proposes, the human commits.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import gcal
import reply_parse as rp
from db.session import get_session
from tzutil import safe_zone

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
        rp.parse_reply, reply["body"], tz=tz, offered_slots=slots,
        already_booked=(cand["status"] == "confirmed"))

    # --- Chunk B/C: route on intent before the slot-pick logic ---
    if cand["status"] == "confirmed" and parsed["intent"] in ("cancel", "reschedule"):
        new_status = ("cancel_requested" if parsed["intent"] == "cancel"
                      else "reschedule_requested")
        await db.execute(
            text("UPDATE candidate SET status = :st WHERE id = :c"),
            {"st": new_status, "c": candidate_id})
        await db.execute(
            text("INSERT INTO reply_parse (candidate_id, thread_id, raw_text, windows, "
                 "confidence, note, outcome) VALUES (:c,:t,:r,CAST(:w AS JSONB),:conf,:n,:o)"),
            {"c": candidate_id, "t": thread, "r": reply["body"], "w": json.dumps([]),
             "conf": parsed["confidence"], "n": parsed["note"], "o": new_status})
        await db.execute(
            text("INSERT INTO event_log (session_id, actor, action, detail) "
                 "VALUES (:s,'agent','reply_intent', CAST(:d AS JSONB))"),
            {"s": job["session_id"],
             "d": json.dumps({"candidate_id": candidate_id, "intent": parsed["intent"],
                              "requested_date": parsed["requested_date"]})})
        await db.commit()
        return {
            "status": parsed["intent"],          # 'cancel' | 'reschedule'
            "reason": parsed["note"],
            "reply_from": reply["from"], "reply_body": reply["body"],
            "confidence": parsed["confidence"], "note": parsed["note"],
            "requested_date": parsed["requested_date"],
            "windows": [], "proposed_slots": [],
        }

    matched = rp.intersect_slots(parsed, slots, tz=tz)
    decision = rp.decide(parsed, matched)

    # Deterministic backstop: if the LLM escalated but the reply names a weekday
    # that uniquely maps to one offered slot ("Monday works"), trust the string
    # match and propose it. Prevents a clear pick from being wrongly escalated.
    if decision["action"] == "escalate":
        clean = rp.strip_quoted(reply["body"]) or reply["body"]
        det = rp.deterministic_match(clean, slots, tz=tz)
        if det:
            matched = det
            parsed["is_availability_answer"] = True
            parsed["confidence"] = max(parsed["confidence"], 0.8)
            parsed["note"] = (parsed["note"] + " | matched by weekday").strip(" |")
            decision = {"action": "confirm", "reason": "weekday uniquely matched an offered slot",
                        "slots": det}
            
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


# --- Phase 4c: recruiter confirms a proposed slot -> book + Meet + confirmations

class Confirm(BaseModel):
    slot_id: int


@router.post("/{candidate_id}/confirm")
async def confirm_booking(job_id: int, candidate_id: int, body: Confirm,
                          db: AsyncSession = Depends(get_session)):
    """The human commit. Books the recruiter-chosen slot for this candidate via
    the atomic path, creates a real Meet event, emails both parties, and frees
    the candidate's other holds. Never called automatically — explicit click.
    """
    job = (
        await db.execute(
            text("SELECT session_id, params, timezone FROM job WHERE id = :j"),
            {"j": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    card = job["params"]

    cand = (
        await db.execute(
            text("SELECT id, name, email, timezone FROM candidate "
                 "WHERE id = :c AND job_id = :j"), {"c": candidate_id, "j": job_id})
    ).mappings().one_or_none()
    if cand is None:
        raise HTTPException(404, "candidate not found")

    slot = (
        await db.execute(
            text("SELECT id, start_ts, end_ts, status, hold_owner "
                 "FROM slot WHERE id = :s AND job_id = :j"),
            {"s": body.slot_id, "j": job_id})
    ).mappings().one_or_none()
    if slot is None:
        raise HTTPException(404, "slot not found")

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

    # Atomically claim the slot for booking. Accept it if available, or held by
    # this candidate (their outreach hold), or an expired hold. Reuses the Phase 3
    # guard: exactly one booking wins; UNIQUE(slot_id) is the final backstop.
    import uuid as _uuid
    claimed = (
        await db.execute(
            text("UPDATE slot SET status='booked' WHERE id=:s AND job_id=:j AND "
                 "(status='available' OR (status='held' AND (hold_owner=:c OR "
                 "hold_expires_at <= now()))) RETURNING id"),
            {"s": body.slot_id, "j": job_id, "c": candidate_id})
    ).scalar_one_or_none()
    if claimed is None:
        raise HTTPException(409, "slot no longer bookable (already booked or taken)")

    interviewer = (
        await db.execute(
            text("SELECT name, email, calendar_id FROM interviewer "
                 "WHERE job_id = :j LIMIT 1"), {"j": job_id})
    ).mappings().one_or_none()
    iv_email = interviewer["email"] if interviewer else acc["email"]
    iv_name = interviewer["name"] if interviewer else "the interviewer"

    start_iso = slot["start_ts"].isoformat()
    end_iso = slot["end_ts"].isoformat()
    duration = card.get("duration_min", 30)
    title = card.get("job_title", "Interview")

    # Create the real calendar event + Meet link on the interviewer's calendar.
    try:
        ev = await run_in_threadpool(
            gcal.create_event_with_meet, creds, acc["email"],
            summary=f"{title} — interview with {cand['name'] or cand['email']}",
            description=f"{duration}-minute screen with {iv_name}.",
            start_iso=start_iso, end_iso=end_iso,
            attendees=[cand["email"], iv_email], request_id=str(_uuid.uuid4()))
    except Exception as e:
        # Roll the slot back so it isn't stuck 'booked' without an event.
        await db.execute(text("UPDATE slot SET status='available', hold_id=NULL, "
                              "hold_owner=NULL, hold_expires_at=NULL WHERE id=:s"),
                         {"s": body.slot_id})
        await db.commit()
        raise HTTPException(502, f"calendar event failed: {e}")

    await db.execute(
        text("INSERT INTO booking (candidate_id, slot_id, gcal_event_id, meet_link) "
             "VALUES (:c,:s,:e,:m)"),
        {"c": candidate_id, "s": body.slot_id, "e": ev["event_id"], "m": ev["meet_link"]})

    # Release this candidate's OTHER holds so those slots are offerable again.
    await db.execute(
        text("UPDATE slot SET status='available', hold_id=NULL, hold_owner=NULL, "
             "hold_expires_at=NULL WHERE job_id=:j AND hold_owner=:c AND status='held' "
             "AND id <> :s"), {"j": job_id, "c": candidate_id, "s": body.slot_id})

    await db.execute(text("UPDATE candidate SET status='confirmed' WHERE id=:c"),
                     {"c": candidate_id})

    # Confirmation emails to both parties (best-effort; booking already committed).
    tz = cand["timezone"] or job["timezone"]
    when = slot["start_ts"].astimezone(safe_zone(tz)).strftime("%A %d %B %Y, %I:%M %p %Z")
    cand_body = (f"Hi {cand['name'] or 'there'},\n\nYou're booked for a {duration}-minute "
                 f"{title} interview with {iv_name} on {when}.\n\n"
                 f"Google Meet: {ev['meet_link']}\n\nSee you then.")
    iv_body = (f"Hi {iv_name},\n\n{cand['name'] or cand['email']} is booked for a "
               f"{duration}-minute {title} interview on {when}.\n\n"
               f"Google Meet: {ev['meet_link']}")
    mail_status = "sent"
    try:
        await run_in_threadpool(gcal.send_email, creds, to=cand["email"],
                                subject=f"Interview confirmed — {title}", body=cand_body)
        await run_in_threadpool(gcal.send_email, creds, to=iv_email,
                                subject=f"Interview booked — {cand['name'] or cand['email']}",
                                body=iv_body)
    except Exception as e:
        mail_status = f"event created but confirmation email failed: {e}"

    await db.execute(
        text("UPDATE reply_parse SET outcome='confirmed' WHERE candidate_id=:c "
             "AND id = (SELECT max(id) FROM reply_parse WHERE candidate_id=:c)"),
        {"c": candidate_id})
    await db.execute(
        text("INSERT INTO event_log (session_id, actor, action, detail) "
             "VALUES (:s,'recruiter','confirmed_booking', CAST(:d AS JSONB))"),
        {"s": job["session_id"],
         "d": json.dumps({"candidate_id": candidate_id, "slot_id": body.slot_id,
                          "event_id": ev["event_id"], "meet": bool(ev["meet_link"])})})
    await db.commit()

    return {"status": "booked", "slot_id": body.slot_id, "when": when,
            "meet_link": ev["meet_link"], "event_link": ev["html_link"],
            "mail_status": mail_status}


# --- Chunk B: cancel a confirmed booking ---------------------------------

class Cancel(BaseModel):
    reason: str | None = None


@router.post("/{candidate_id}/cancel")
async def cancel_booking(job_id: int, candidate_id: int, body: Cancel,
                         db: AsyncSession = Depends(get_session)):
    """Cancel this candidate's active booking. Safe order: delete the calendar
    event -> free the slot -> mark booking cancelled -> candidate 'cancelled' ->
    notify both parties. Only acts on a candidate who is actually booked; the
    gated agent card / recruiter click is the authorisation (never auto-fired)."""
    job = (
        await db.execute(
            text("SELECT session_id, params, timezone FROM job WHERE id = :j"),
            {"j": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    card = job["params"]

    cand = (
        await db.execute(
            text("SELECT id, name, email, timezone, status FROM candidate "
                 "WHERE id = :c AND job_id = :j"), {"c": candidate_id, "j": job_id})
    ).mappings().one_or_none()
    if cand is None:
        raise HTTPException(404, "candidate not found")

    booking = (
        await db.execute(
            text("SELECT b.id, b.slot_id, b.gcal_event_id, s.start_ts "
                 "FROM booking b JOIN slot s ON s.id = b.slot_id "
                 "WHERE b.candidate_id = :c AND b.status = 'active' "
                 "ORDER BY b.id DESC LIMIT 1"), {"c": candidate_id})
    ).mappings().one_or_none()
    if booking is None:
        raise HTTPException(409, "no active booking to cancel for this candidate")

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

    # 1. Delete the Google event (idempotent). If this fails hard, abort BEFORE
    #    touching the DB so state stays consistent (booking still active).
    if booking["gcal_event_id"]:
        try:
            await run_in_threadpool(
                gcal.delete_event, creds, acc["email"], booking["gcal_event_id"])
        except Exception as e:
            raise HTTPException(502, f"could not cancel the calendar event: {e}")

    # 2. Free the slot, 3. mark booking cancelled, 4. candidate cancelled.
    await db.execute(
        text("UPDATE slot SET status='available', hold_id=NULL, hold_owner=NULL, "
             "hold_expires_at=NULL WHERE id=:s"), {"s": booking["slot_id"]})
    await db.execute(
        text("UPDATE booking SET status='cancelled', cancelled_at=now() WHERE id=:b"),
        {"b": booking["id"]})
    await db.execute(
        text("UPDATE candidate SET status='cancelled' WHERE id=:c"), {"c": candidate_id})

    # 5. Notify both parties (best-effort; cancellation already committed).
    interviewer = (
        await db.execute(
            text("SELECT name, email FROM interviewer WHERE job_id=:j LIMIT 1"), {"j": job_id})
    ).mappings().one_or_none()
    iv_email = interviewer["email"] if interviewer else acc["email"]
    iv_name = interviewer["name"] if interviewer else "the interviewer"
    title = card.get("job_title", "the interview")
    tz = cand["timezone"] or job["timezone"]
    when = booking["start_ts"].astimezone(safe_zone(tz)).strftime("%A %d %B %Y, %I:%M %p %Z")

    cand_body = (f"Hi {cand['name'] or 'there'},\n\nYour {title} interview scheduled for "
                 f"{when} has been cancelled. If you'd like to rebook, just reply with a "
                 f"date you're free from and I'll send new times.\n\nBest,\nThe scheduling team")
    iv_body = (f"Hi {iv_name},\n\nThe {title} interview with "
               f"{cand['name'] or cand['email']} on {when} has been cancelled.")
    mail_status = "sent"
    try:
        await run_in_threadpool(gcal.send_email, creds, to=cand["email"],
                                subject=f"Interview cancelled — {title}", body=cand_body)
        await run_in_threadpool(gcal.send_email, creds, to=iv_email,
                                subject=f"Interview cancelled — {cand['name'] or cand['email']}",
                                body=iv_body)
    except Exception as e:
        mail_status = f"cancelled, but notification email failed: {e}"

    await db.execute(
        text("INSERT INTO event_log (session_id, actor, action, detail) "
             "VALUES (:s,'recruiter','cancelled_booking', CAST(:d AS JSONB))"),
        {"s": job["session_id"],
         "d": json.dumps({"candidate_id": candidate_id, "slot_id": booking["slot_id"],
                          "reason": body.reason})})
    await db.commit()

    return {"status": "cancelled", "candidate_id": candidate_id,
            "slot_freed": booking["slot_id"], "when": when, "mail_status": mail_status}


# --- Chunk C: reschedule move-saga (book NEW before cancelling OLD) --------

class Rebook(BaseModel):
    slot_id: int   # the NEW slot the candidate/recruiter picked


@router.post("/{candidate_id}/rebook")
async def rebook_booking(job_id: int, candidate_id: int, body: Rebook,
                         db: AsyncSession = Depends(get_session)):
    """Move a confirmed interview to a new slot using EXA's safe saga:
    book the NEW slot first (claim + create new event + insert new booking), and
    ONLY THEN cancel the OLD one (delete old event, free old slot, supersede old
    booking). If any step before the old-cancel fails, the ORIGINAL booking is
    left fully intact and the new slot is rolled back — never a double-book, never
    a lost interview. Gated: only reachable by the recruiter's approval click."""
    job = (
        await db.execute(
            text("SELECT session_id, params, timezone FROM job WHERE id = :j"), {"j": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    card = job["params"]

    cand = (
        await db.execute(
            text("SELECT id, name, email, timezone, status FROM candidate "
                 "WHERE id = :c AND job_id = :j"), {"c": candidate_id, "j": job_id})
    ).mappings().one_or_none()
    if cand is None:
        raise HTTPException(404, "candidate not found")

    old = (
        await db.execute(
            text("SELECT b.id, b.slot_id, b.gcal_event_id, s.start_ts "
                 "FROM booking b JOIN slot s ON s.id = b.slot_id "
                 "WHERE b.candidate_id = :c AND b.status = 'active' "
                 "ORDER BY b.id DESC LIMIT 1"), {"c": candidate_id})
    ).mappings().one_or_none()
    if old is None:
        raise HTTPException(409, "no active booking to reschedule for this candidate")
    if old["slot_id"] == body.slot_id:
        raise HTTPException(409, "that is already the booked slot")

    new_slot = (
        await db.execute(
            text("SELECT id, start_ts, end_ts FROM slot WHERE id=:s AND job_id=:j"),
            {"s": body.slot_id, "j": job_id})
    ).mappings().one_or_none()
    if new_slot is None:
        raise HTTPException(404, "new slot not found")

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

    interviewer = (
        await db.execute(
            text("SELECT name, email FROM interviewer WHERE job_id=:j LIMIT 1"), {"j": job_id})
    ).mappings().one_or_none()
    iv_email = interviewer["email"] if interviewer else acc["email"]
    iv_name = interviewer["name"] if interviewer else "the interviewer"
    duration = card.get("duration_min", 30)
    title = card.get("job_title", "Interview")

    # === STEP 1: claim the NEW slot atomically (Phase-3 guard) ===============
    import uuid as _uuid
    claimed = (
        await db.execute(
            text("UPDATE slot SET status='booked' WHERE id=:s AND job_id=:j AND "
                 "(status='available' OR (status='held' AND (hold_owner=:c OR "
                 "hold_expires_at <= now()))) RETURNING id"),
            {"s": body.slot_id, "j": job_id, "c": candidate_id})
    ).scalar_one_or_none()
    if claimed is None:
        # New slot taken — OLD booking untouched. No double-book.
        raise HTTPException(409, "that new slot is no longer available; pick another")

    # === STEP 2: create the NEW calendar event ===============================
    try:
        ev = await run_in_threadpool(
            gcal.create_event_with_meet, creds, acc["email"],
            summary=f"{title} — interview with {cand['name'] or cand['email']}",
            description=f"{duration}-minute screen with {iv_name} (rescheduled).",
            start_iso=new_slot["start_ts"].isoformat(),
            end_iso=new_slot["end_ts"].isoformat(),
            attendees=[cand["email"], iv_email], request_id=str(_uuid.uuid4()))
    except Exception as e:
        # New event failed -> roll back the new slot; OLD booking still intact.
        await db.execute(text("UPDATE slot SET status='available', hold_id=NULL, "
                              "hold_owner=NULL, hold_expires_at=NULL WHERE id=:s"),
                         {"s": body.slot_id})
        await db.commit()
        raise HTTPException(502, f"could not create the new event (kept the original): {e}")

    # === STEP 3: record the NEW booking ======================================
    await db.execute(
        text("INSERT INTO booking (candidate_id, slot_id, gcal_event_id, meet_link) "
             "VALUES (:c,:s,:e,:m)"),
        {"c": candidate_id, "s": body.slot_id, "e": ev["event_id"], "m": ev["meet_link"]})

    # === STEP 4: NOW cancel the OLD one (delete event, free slot, supersede) ==
    # New booking already exists, so even if old-event deletion hiccups we never
    # lose the interview. delete_event is idempotent.
    if old["gcal_event_id"]:
        try:
            await run_in_threadpool(gcal.delete_event, creds, acc["email"], old["gcal_event_id"])
        except Exception:
            pass  # new booking stands; stale old event is a minor cleanup issue
    await db.execute(
        text("UPDATE slot SET status='available', hold_id=NULL, hold_owner=NULL, "
             "hold_expires_at=NULL WHERE id=:s"), {"s": old["slot_id"]})
    await db.execute(
        text("UPDATE booking SET status='superseded', cancelled_at=now() WHERE id=:b"),
        {"b": old["id"]})
    await db.execute(text("UPDATE candidate SET status='confirmed' WHERE id=:c"),
                     {"c": candidate_id})

    # === confirmations =======================================================
    tz = cand["timezone"] or job["timezone"]
    old_when = old["start_ts"].astimezone(safe_zone(tz)).strftime("%A %d %B, %I:%M %p %Z")
    new_when = new_slot["start_ts"].astimezone(safe_zone(tz)).strftime("%A %d %B %Y, %I:%M %p %Z")
    cand_body = (f"Hi {cand['name'] or 'there'},\n\nYour {title} interview has been moved from "
                 f"{old_when} to {new_when}.\n\nGoogle Meet: {ev['meet_link']}\n\nSee you then.")
    iv_body = (f"Hi {iv_name},\n\n{cand['name'] or cand['email']}'s {title} interview moved to "
               f"{new_when} (was {old_when}).\n\nGoogle Meet: {ev['meet_link']}")
    mail_status = "sent"
    try:
        await run_in_threadpool(gcal.send_email, creds, to=cand["email"],
                                subject=f"Interview rescheduled — {title}", body=cand_body)
        await run_in_threadpool(gcal.send_email, creds, to=iv_email,
                                subject=f"Interview rescheduled — {cand['name'] or cand['email']}",
                                body=iv_body)
    except Exception as e:
        mail_status = f"rescheduled, but notification email failed: {e}"

    await db.execute(
        text("INSERT INTO event_log (session_id, actor, action, detail) "
             "VALUES (:s,'recruiter','rescheduled_booking', CAST(:d AS JSONB))"),
        {"s": job["session_id"],
         "d": json.dumps({"candidate_id": candidate_id, "old_slot": old["slot_id"],
                          "new_slot": body.slot_id, "new_event": ev["event_id"]})})
    await db.commit()

    return {"status": "rescheduled", "candidate_id": candidate_id,
            "old_slot": old["slot_id"], "new_slot": body.slot_id,
            "when": new_when, "meet_link": ev["meet_link"], "mail_status": mail_status}