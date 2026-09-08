"""Phase 3 race verification — RUN AGAINST NEON (needs DATABASE_URL).

    cd backend && python race_test.py

Fires N concurrent hold+book attempts at ONE slot and asserts exactly one
booking wins. This is the Phase 3 verify gate (concurrency, not two browsers).
Creates a throwaway session/job/interviewer/candidate + one slot, then cleans up.
"""
import asyncio
import uuid

from sqlalchemy import text

from db.session import engine, SessionLocal

N = 20  # concurrent racers


async def _setup():
    async with SessionLocal() as db:
        sid = (await db.execute(text("INSERT INTO session (actor) VALUES ('test') RETURNING id"))).scalar_one()
        jid = (await db.execute(text(
            "INSERT INTO job (session_id, title, status, hold_ttl_min) "
            "VALUES (:s,'race-test','confirmed',30) RETURNING id"), {"s": sid})).scalar_one()
        iv = (await db.execute(text(
            "INSERT INTO interviewer (job_id, name, email, calendar_id) "
            "VALUES (:j,'iv','iv@test','iv@test') RETURNING id"), {"j": jid})).scalar_one()
        slot = (await db.execute(text(
            "INSERT INTO slot (job_id, interviewer_id, start_ts, end_ts, status) "
            "VALUES (:j,:iv, now()+interval '1 day', now()+interval '1 day 30 min','available') "
            "RETURNING id"), {"j": jid, "iv": iv})).scalar_one()
        cands = []
        for i in range(N):
            c = (await db.execute(text(
                "INSERT INTO candidate (job_id, email) VALUES (:j,:e) RETURNING id"),
                {"j": jid, "e": f"c{i}-{uuid.uuid4().hex[:6]}@test"})).scalar_one()
            cands.append(c)
        await db.commit()
        return sid, jid, iv, slot, cands


async def _attempt(slot_id, candidate_id):
    """One racer: try to hold, then book. Returns True if it booked."""
    hold_id = str(uuid.uuid4())
    async with SessionLocal() as db:
        held = (await db.execute(text(
            "UPDATE slot SET status='held', hold_id=CAST(:h AS UUID), hold_owner=:c, "
            "hold_expires_at = now()+interval '30 min', version=version+1 "
            "WHERE id=:s AND (status='available' OR (status='held' AND hold_expires_at <= now())) "
            "RETURNING id"), {"h": hold_id, "c": candidate_id, "s": slot_id})).scalar_one_or_none()
        if held is None:
            return False
        await db.commit()
    async with SessionLocal() as db:
        try:
            ok = (await db.execute(text(
                "UPDATE slot SET status='booked' WHERE id=:s AND status='held' "
                "AND hold_id=CAST(:h AS UUID) AND hold_owner=:c AND hold_expires_at > now() "
                "RETURNING id"), {"s": slot_id, "h": hold_id, "c": candidate_id})).scalar_one_or_none()
            if ok is None:
                return False
            await db.execute(text("INSERT INTO booking (candidate_id, slot_id) VALUES (:c,:s)"),
                             {"c": candidate_id, "s": slot_id})
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            return False


async def _cleanup(jid):
    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM job WHERE id=:j"), {"j": jid})  # cascades
        await db.commit()


async def main():
    sid, jid, iv, slot, cands = await _setup()
    try:
        results = await asyncio.gather(*[_attempt(slot, c) for c in cands])
        winners = sum(results)
        async with SessionLocal() as db:
            bookings = (await db.execute(
                text("SELECT count(*) FROM booking WHERE slot_id=:s"), {"s": slot})).scalar_one()
        print(f"racers={N}  hold+book winners={winners}  bookings_in_db={bookings}")
        assert winners == 1, f"expected exactly 1 winner, got {winners}"
        assert bookings == 1, f"expected exactly 1 booking row, got {bookings}"
        print("PASS: exactly one winner, no double-booking")
    finally:
        await _cleanup(jid)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())