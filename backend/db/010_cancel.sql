-- Chunk B (cancel) + C (reschedule): a booking is no longer terminal.
-- booking.status tracks its lifecycle; candidate gains cancel/reschedule states.
--   booking.status: 'active' (default) | 'cancelled' | 'superseded' (C: replaced by a reschedule)
-- Candidate status values reused as strings (no enum): existing
--   not_contacted | slots_offered | followup_sent | confirmed | needs_attention
-- plus new: 'cancel_requested' | 'reschedule_requested' | 'cancelled'.

ALTER TABLE booking ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE booking ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;

-- The UNIQUE(slot_id) backstop from 003 blocks re-booking a slot after cancel.
-- Make it a PARTIAL unique index: only ACTIVE bookings must be unique per slot,
-- so a cancelled booking can coexist with a fresh one on the same freed slot.
ALTER TABLE booking DROP CONSTRAINT IF EXISTS booking_slot_id_key;
DROP INDEX IF EXISTS booking_slot_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_booking_active_slot
    ON booking (slot_id) WHERE status = 'active';