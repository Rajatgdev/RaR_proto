"""Phase 5 sweep body, shared by the Railway Cron entrypoint (jobs/sweep.py) and
a manual trigger endpoint. Two idempotent jobs, safe to run repeatedly."""
import json
from datetime import datetime, timezone

from sqlalchemy import text

import gcal
import outreach_tpl as tpl
from sweep_logic import followup_is_due, within_working_hours

UTC = timezone.utc

FOLLOWUP_BODY = """Hi {name},

Just following up on my note below about scheduling a {duration}-minute
{job} interview with {interviewer}. The times I offered are still open —
reply with whichever suits and I'll lock it in:

{slots}

Thanks!
The scheduling team
"""


async def expire_holds(db) -> int:
    rows = (
        await db.execute(
            text("UPDATE slot SET status='available', hold_id=NULL, hold_owner=NULL, "
                 "hold_expires_at=NULL "
                 "WHERE status='held' AND hold_expires_at <= now() RETURNING id"))
    ).all()
    return len(rows)


async def send_followups(db) -> int:
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            text("SELECT c.id, c.name, c.email, c.timezone, c.status, c.followup_sent_at, "
                 "o.thread_id, o.sent_at, "
                 "j.id AS job_id, j.session_id, j.params, j.timezone AS job_tz, "
                 "j.followup_after_min "
                 "FROM candidate c "
                 "JOIN outreach o ON o.candidate_id = c.id AND o.kind='outreach' "
                 "JOIN job j ON j.id = c.job_id "
                 "WHERE c.status = 'slots_offered' AND c.followup_sent_at IS NULL"))
    ).mappings().all()
    if not rows:
        return 0

    acc = (
        await db.execute(
            text("SELECT id, email, credentials FROM google_account "
                 "ORDER BY updated_at DESC LIMIT 1"))
    ).mappings().one_or_none()
    if acc is None:
        return 0
    creds = gcal.credentials_from_json(acc["credentials"])
    try:
        if gcal.ensure_fresh(creds):
            await db.execute(
                text("UPDATE google_account SET credentials=CAST(:c AS JSONB), "
                     "updated_at=now() WHERE id=:id"),
                {"c": creds.to_json(), "id": acc["id"]})
            await db.commit()
    except Exception:
        return 0

    sent = 0
    for r in rows:
        card = r["params"]
        tz = r["timezone"] or r["job_tz"]
        work_start = card.get("work_start", "09:00")
        work_end = card.get("work_end", "17:00")

        if not within_working_hours(now, tz=tz, work_start=work_start, work_end=work_end):
            continue
        cand = {"status": r["status"], "sent_at": r["sent_at"],
                "followup_sent_at": r["followup_sent_at"]}
        if not followup_is_due(cand, now=now, after_min=r["followup_after_min"]):
            continue

        slot_rows = (
            await db.execute(
                text("SELECT start_ts, end_ts FROM slot WHERE job_id=:j AND "
                     "(status='available' OR (status='held' AND hold_owner=:c)) "
                     "ORDER BY start_ts"), {"j": r["job_id"], "c": r["id"]})
        ).mappings().all()
        if not slot_rows:
            continue
        slot_dicts = [{"start": s["start_ts"].isoformat(), "end": s["end_ts"].isoformat()}
                      for s in slot_rows]

        interviewer = (card.get("interviewers") or [{}])[0].get("name") or "the interviewer"
        subject, body = tpl.render(
            f"Re: Interview scheduling — {card.get('job_title', 'the role')}",
            FOLLOWUP_BODY, name=r["name"], interviewer=interviewer,
            job=card.get("job_title", "the role"), duration=card.get("duration_min", 30),
            slots=slot_dicts, tz=tz)

        try:
            gcal.send_email(creds, to=r["email"], subject=subject, body=body,
                            thread_id=r["thread_id"])
        except Exception:
            continue

        await db.execute(
            text("UPDATE candidate SET status='followup_sent', followup_sent_at=now() "
                 "WHERE id=:c"), {"c": r["id"]})
        await db.execute(
            text("INSERT INTO outreach (candidate_id, thread_id, kind, sent_at) "
                 "VALUES (:c,:t,'followup', now())"),
            {"c": r["id"], "t": r["thread_id"]})
        await db.execute(
            text("INSERT INTO event_log (session_id, actor, action, detail) "
                 "VALUES (:s,'agent','sent_followup', CAST(:d AS JSONB))"),
            {"s": r["session_id"], "d": json.dumps({"candidate_id": r["id"]})})
        await db.commit()
        sent += 1

    return sent


async def run_sweep(db) -> dict:
    freed = await expire_holds(db)
    await db.commit()
    followups = await send_followups(db)
    return {"holds_expired": freed, "followups_sent": followups}