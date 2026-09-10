"""Phase 5: status board data + a manual sweep trigger (for demos)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from db.session import get_session
from sweep import run_sweep

router = APIRouter(prefix="/jobs/{job_id}", tags=["board"])

_LABELS = {
    "not_contacted": "Not contacted",
    "slots_offered": "Slots offered",
    "followup_sent": "Follow-up sent",
    "confirmed": "Confirmed",
    "needs_attention": "Needs attention",
}


@router.get("/board")
async def board(job_id: int, db: AsyncSession = Depends(get_session)):
    job = (
        await db.execute(text("SELECT id, title, status, timezone FROM job WHERE id=:j"), {"j": job_id})
    ).mappings().one_or_none()
    if job is None:
        raise HTTPException(404, "job not found")

    rows = (
        await db.execute(
            text(
                "SELECT c.id, c.name, c.email, c.status, c.followup_sent_at, "
                "b.slot_id AS booked_slot, bs.start_ts AS booked_start, b.meet_link, "
                "(SELECT max(created_at) FROM reply_parse rp WHERE rp.candidate_id=c.id) "
                "  AS last_parse "
                "FROM candidate c "
                "LEFT JOIN booking b ON b.candidate_id = c.id "
                "LEFT JOIN slot bs ON bs.id = b.slot_id "
                "WHERE c.job_id = :j ORDER BY c.id"),
            {"j": job_id})
    ).mappings().all()

    candidates = []
    for r in rows:
        candidates.append({
            "candidate_id": r["id"],
            "name": r["name"],
            "email": r["email"],
            "status": r["status"],
            "status_label": _LABELS.get(r["status"], r["status"]),
            "followup_sent": r["followup_sent_at"] is not None,
            "booked_start": (r["booked_start"].astimezone(ZoneInfo(job["timezone"])).isoformat()
                             if r["booked_start"] else None),
            "meet_link": r["meet_link"],
            "has_reply_parse": r["last_parse"] is not None,
        })
    return {"job_id": job_id, "title": job["title"], "timezone": job["timezone"],
            "candidates": candidates}


@router.post("/sweep")
async def manual_sweep(job_id: int, db: AsyncSession = Depends(get_session)):
    result = await run_sweep(db)
    return result