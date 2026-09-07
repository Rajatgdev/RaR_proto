from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session

router = APIRouter(prefix="/ping", tags=["ping"])


class PingIn(BaseModel):
    note: str


@router.post("")
async def write_ping(body: PingIn, db: AsyncSession = Depends(get_session)):
    row = (
        await db.execute(
            text("INSERT INTO ping (note) VALUES (:n) RETURNING id, note, ts"),
            {"n": body.note},
        )
    ).mappings().one()
    await db.commit()
    return dict(row)


@router.get("")
async def latest_ping(db: AsyncSession = Depends(get_session)):
    row = (
        await db.execute(
            text("SELECT id, note, ts FROM ping ORDER BY id DESC LIMIT 1")
        )
    ).mappings().one_or_none()
    return dict(row) if row else None
