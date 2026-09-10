"""Case-2 re-offer: a candidate rejected all offered times and proposed their own.
The recruiter clicks 're-offer'; this parses their latest reply for a target
window, generates fresh eligible slots (via the same compute_slots path, so the
card's work-hours/duration/buffer rules still bind — "closest within rules"),
picks the 5 nearest the target, adds any new ones to the shared pool, and emails
this one candidate. Never auto-sends: it is only reachable by an explicit call,
mirroring the outreach/confirm gates. No booking happens here.
"""
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import gcal
import outreach_tpl as tpl
import reply_parse as rp
from availability import compute_slots
from fairness import slots_near_target
from db.session import get_session

router = APIRouter(prefix="/jobs/{job_id}/reoffer", tags=["reoffer"])

UTC = timezone.utc

REOFFER_BODY = """Hi {name},

Thanks — I looked for a time around your preference. These are the closest
interview times currently available for the {duration}-minute {job} interview
with {interviewer}:

{slots}

Please reply with whichever suits, or share another window that works better.

Thanks!
The scheduling team
"""


async def _account(db):
    acc = (
        await db.execute(
            text("SELECT id, email, credentials FROM google_account "
                 "ORDER BY updated_at DESC LIMIT 1"))
    ).mappings().one_or_none()
    if acc is None:
        raise HTTPException(400, "no Google account connected")
    return acc


@router.post("/{candidate_id}")
async def reoffer(job_id: int, candidate_id: int, db: AsyncSession = Depends(get_session)):
    job = (
        await db.execute(
            text("SELECT id, session_id, params, status, timezone FROM job WHERE id=:j"),
            {"j": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")
    if job["status"] != "confirmed":
        raise HTTPException(403, "job not confirmed (Gate 1)")
    card = job["params"]

    cand = (
        await db.execute(
            text("SELECT id, name, email, timezone FROM candidate "
                 "WHERE id=:c AND job_id=:j"), {"c": candidate_id, "j": job_id})
    ).mappings().one_or_none()
    if cand is None:
        raise HTTPException(404, "candidate not found")
    tz = cand["timezone"] or job["timezone"]

    thread = (
        await db.execute(
            text("SELECT thread_id FROM outreach WHERE candidate_id=:c "
                 "ORDER BY sent_at DESC LIMIT 1"), {"c": candidate_id})
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
            text("UPDATE google_account SET credentials=CAST(:c AS JSONB), "
                 "updated_at=now() WHERE id=:id"),
            {"c": creds.to_json(), "id": acc["id"]})
        await db.commit()

    # 1. Read + parse the candidate's latest reply for a target window.
    try:
        reply = await run_in_threadpool(gcal.read_latest_reply, creds, thread, acc["email"])
    except Exception as e:
        raise HTTPException(502, f"could not read reply: {e}")
    if reply is None:
        raise HTTPException(422, "no candidate reply to re-offer around")

    current = (
        await db.execute(
            text("SELECT id AS slot_id, start_ts, end_ts FROM slot "
                 "WHERE job_id=:j AND status IN ('available','held') ORDER BY start_ts"),
            {"j": job_id})
    ).mappings().all()
    offered = [{"slot_id": s["slot_id"], "start": s["start_ts"].isoformat(),
                "end": s["end_ts"].isoformat()} for s in current]
    parsed = await run_in_threadpool(rp.parse_reply, reply["body"], tz=tz, offered_slots=offered)
    windows = parsed.get("windows") or []
    if not windows:
        raise HTTPException(422, "could not read a preferred time from the reply; "
                                 "read the reply manually")
    target_iso = windows[0]["start"]

    # 2. Fresh eligibility via the same constrained path (card rules still bind).
    iv = (
        await db.execute(
            text("SELECT id FROM interviewer WHERE job_id=:j LIMIT 1"), {"j": job_id})
    ).scalar_one_or_none()
    if iv is None:
        raise HTTPException(422, "no interviewer on this job; generate slots first")

    zone = ZoneInfo(job["timezone"] or "Europe/London")
    start_day = date.today()
    days = card["window_days"]
    time_min = datetime.combine(start_day, time(0, 0), zone).astimezone(UTC).isoformat()
    time_max = (datetime.combine(start_day + timedelta(days=days), time(0, 0), zone)
                .astimezone(UTC).isoformat())
    try:
        busy = await run_in_threadpool(gcal.free_busy, creds, acc["email"], time_min, time_max)
    except Exception as e:
        raise HTTPException(502, f"FreeBusy failed: {e}")

    eligible = compute_slots(
        busy, start_day=start_day, num_days=days, tz=job["timezone"],
        work_start=time.fromisoformat(card["work_start"]),
        work_end=time.fromisoformat(card["work_end"]),
        duration_min=card["duration_min"], buffer_min=card["buffer_min"],
        now=datetime.now(UTC))
    near = slots_near_target(eligible, target_iso)
    if not near:
        raise HTTPException(422, "no interview times available near the requested time; "
                                 "try another day/window")

    # 3. Add genuinely-new near slots to the shared pool (dedupe on start_ts).
    existing_starts = {datetime.fromisoformat(o["start"]) for o in offered}
    created = []
    for s in near:
        st = datetime.fromisoformat(s["start"])
        if st not in existing_starts:
            await db.execute(
                text("INSERT INTO slot (job_id, interviewer_id, start_ts, end_ts, status) "
                     "VALUES (:j,:iv,:st,:et,'available')"),
                {"j": job_id, "iv": iv, "st": st, "et": datetime.fromisoformat(s["end"])})
        created.append({"start": s["start"], "end": s["end"]})

    # 4. Email this candidate the near slots (warm copy; recruiter-approved by the click).
    subject, mail_body = tpl.render(
        f"Re: Interview scheduling — {card.get('job_title', 'the role')}",
        REOFFER_BODY, name=cand["name"],
        interviewer=(card.get("interviewers") or [{}])[0].get("name") or "the interviewer",
        job=card.get("job_title", "the role"), duration=card.get("duration_min", 30),
        slots=created, tz=tz)
    try:
        await run_in_threadpool(gcal.send_email, creds, to=cand["email"],
                                subject=subject, body=mail_body, thread_id=thread)
    except Exception as e:
        raise HTTPException(502, f"send failed: {e}")

    # 5. Back to slots_offered so a follow-up/reply cycle can resume; log it.
    await db.execute(
        text("UPDATE candidate SET status='slots_offered', followup_sent_at=NULL WHERE id=:c"),
        {"c": candidate_id})
    await db.execute(
        text("INSERT INTO event_log (session_id, actor, action, detail) "
             "VALUES (:s,'recruiter','reoffer_sent', CAST(:d AS JSONB))"),
        {"s": job["session_id"],
         "d": json.dumps({"candidate_id": candidate_id, "target": target_iso,
                          "offered": len(created)})})
    await db.commit()

    when_target = datetime.fromisoformat(target_iso).astimezone(ZoneInfo(tz)).strftime(
        "%A %d %B, %I:%M %p %Z")
    return {"status": "reoffered", "candidate_id": candidate_id,
            "target_time": when_target, "slots_offered": len(created),
            "slots": created}