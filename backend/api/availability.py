from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

import gcal
from availability import compute_slots
from db.session import get_session

router = APIRouter(prefix="/availability", tags=["availability"])

UTC = timezone.utc


async def _load_account(db: AsyncSession):
    return (
        await db.execute(
            text(
                "SELECT id, email, credentials FROM google_account "
                "ORDER BY updated_at DESC LIMIT 1"
            )
        )
    ).mappings().one_or_none()


@router.get("")
async def availability(
    db: AsyncSession = Depends(get_session),
    days: int = Query(10, ge=1, le=30),
    duration: int = Query(30, ge=15, le=120),
    buffer: int = Query(10, ge=0, le=60),
    work_start: str = Query("09:00"),
    work_end: str = Query("17:00"),
    tz: str = Query("Europe/London"),
):
    account = await _load_account(db)
    if account is None:
        raise HTTPException(400, "no Google account connected")

    try:
        zone = ZoneInfo(tz)
    except Exception:
        raise HTTPException(422, f"unknown timezone: {tz}")
    ws, we = time.fromisoformat(work_start), time.fromisoformat(work_end)

    creds = gcal.credentials_from_json(account["credentials"])
    try:
        refreshed = await run_in_threadpool(gcal.ensure_fresh, creds)
    except Exception:
        # Testing-mode refresh tokens die after ~7 days -> ask user to reconnect.
        raise HTTPException(401, "Google connection expired; reconnect required")
    if refreshed:
        await db.execute(
            text("UPDATE google_account SET credentials = CAST(:c AS JSONB), "
                 "updated_at = now() WHERE id = :id"),
            {"c": creds.to_json(), "id": account["id"]},
        )
        await db.commit()

    start_day = date.today()
    time_min = datetime.combine(start_day, time(0, 0), zone).astimezone(UTC).isoformat()
    time_max = (
        datetime.combine(start_day + timedelta(days=days), time(0, 0), zone)
        .astimezone(UTC)
        .isoformat()
    )

    try:
        busy = await run_in_threadpool(
            gcal.free_busy, creds, account["email"], time_min, time_max
        )
    except Exception as e:
        raise HTTPException(502, f"FreeBusy failed: {e}")

    slots = compute_slots(
        busy,
        start_day=start_day,
        num_days=days,
        tz=tz,
        work_start=ws,
        work_end=we,
        duration_min=duration,
        buffer_min=buffer,
    )
    return {"calendar": account["email"], "count": len(slots), "slots": slots}