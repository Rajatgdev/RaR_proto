"""Phase 4b: parse a candidate's free-text reply into an availability window.

One LLM call (gpt-4o-mini, structured output) extracts {windows, confidence,
is_availability_answer, note}. Everything that DECIDES anything — the confidence
gate and the window->slot intersection — is pure Python so it's testable and so
the guardrails are enforced in code, not in the prompt:

  1. Never returns a booking. Only proposes.
  2. Below threshold, or not an availability answer, or zero matching slot
     -> escalate. Never surface a shaky guess as solid.
"""
import json
from datetime import datetime

from config import settings
from tzutil import safe_zone

# Tunable during testing (build-plan says make it a config value).
CONFIDENCE_THRESHOLD = 0.75

_SYSTEM = """You read a candidate's email reply about an interview and decide what
they want. Return ONLY JSON in exactly this shape:
{
  "intent": "pick_slot | cancel | reschedule | other",
  "windows": [{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}],
  "requested_date": "YYYY-MM-DD | null",
  "confidence": 0.0,
  "is_availability_answer": true,
  "note": "one short line on what you understood"
}

INTENT — classify the reply first:
- "pick_slot": they are choosing one of the offered times (or proposing a time),
  and there is NO existing confirmed interview they're trying to change.
- "cancel": they want to cancel / can no longer attend / are withdrawing from an
  interview that was already booked. (e.g. "I need to cancel", "can't make it any
  more", "please cancel my interview").
- "reschedule": they want to MOVE an already-booked interview to a different time,
  OR (before booking) none of the offered times work and they name a new date
  they're free from. (e.g. "can we move it to the 16th?", "none of these work,
  I'm free from the 20th").
- "other": a question, small talk, or anything not about scheduling.

You are given a numbered list of OFFERED slots (weekday + date) — the SOURCE OF
TRUTH for which weekday maps to which date. Also given: whether the candidate
already has a CONFIRMED booking.

Rules:
- pick_slot: if they name a weekday, date, or time in the offered list — even bare
  ("Monday works", "the 1:30 one") — return a window spanning exactly that slot's
  start–end, is_availability_answer=true, confidence >=0.8. A bare weekday that
  matches the offered list IS a match; do not assume a different week.
- reschedule / "none of these work": set intent="reschedule". If they state a
  specific date they're free from, put it in requested_date (YYYY-MM-DD, resolved
  against the offered list's dates). windows may be empty. is_availability_answer
  can be false (we're not picking an offered slot).
- cancel: intent="cancel", windows empty, is_availability_answer=false.
- other: intent="other", windows empty, is_availability_answer=false, low confidence.
- Times are local to the job timezone; output naive ISO (no offset).
Output JSON only."""

# Everything below a quoted-original marker is not the candidate's new text.
_QUOTE_MARKERS = ("\nOn ", "\n> ", "\n-----Original", "\n________________")


def strip_quoted(text: str) -> str:
    """Remove the quoted original email from a reply, keeping only new text."""
    earliest = len(text)
    import re
    m = re.search(r"\nOn .+wrote:", text)
    if m:
        earliest = min(earliest, m.start())
    qm = re.search(r"\n>", text)
    if qm:
        earliest = min(earliest, qm.start())
    for marker in ("\n-----Original", "\n________________"):
        i = text.find(marker)
        if i != -1:
            earliest = min(earliest, i)
    return text[:earliest].strip()


def _slot_lines(slots: list[dict], tz: str) -> str:
    zone = safe_zone(tz)
    lines = []
    for i, s in enumerate(slots, 1):
        st = datetime.fromisoformat(s["start"]).astimezone(zone)
        en = datetime.fromisoformat(s["end"]).astimezone(zone)
        lines.append(f"{i}. {st.strftime('%A %d %B %Y, %I:%M %p')} "
                     f"(start {st.strftime('%Y-%m-%dT%H:%M:%S')}, "
                     f"end {en.strftime('%Y-%m-%dT%H:%M:%S')})")
    return "\n".join(lines)

def parse_reply(reply_text: str, *, tz: str, offered_slots: list[dict],
                already_booked: bool = False) -> dict:
    """LLM parse against the concrete offered slots. Strips quoted history first.
    Returns the validated structured dict (defaults on failure). already_booked
    tells the model whether a confirmed interview exists (so cancel/reschedule of
    an existing booking is distinguishable from a first-time pick)."""
    clean = strip_quoted(reply_text) or reply_text
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        booked_line = ("This candidate ALREADY HAS a confirmed interview booked."
                       if already_booked else
                       "This candidate does NOT yet have a confirmed interview.")
        user = (f"Job timezone: {tz}\n{booked_line}\n\n"
                f"Offered slots:\n{_slot_lines(offered_slots, tz)}\n\n"
                f"Candidate reply (quoted history removed):\n{clean}")
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = json.loads(resp.choices[0].message.content)
    except Exception as e:
        return {"intent": "other", "requested_date": None, "windows": [],
                "confidence": 0.0, "is_availability_answer": False,
                "note": f"parse failed ({type(e).__name__})"}
    return _coerce(raw)

def _coerce(raw: dict) -> dict:
    windows = []
    for w in raw.get("windows") or []:
        if isinstance(w, dict) and w.get("start") and w.get("end"):
            windows.append({"start": w["start"], "end": w["end"]})
    try:
        conf = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0

    intent = str(raw.get("intent", "pick_slot")).strip().lower()
    if intent not in ("pick_slot", "cancel", "reschedule", "other"):
        intent = "pick_slot"

    req = raw.get("requested_date")
    if isinstance(req, str) and req.strip():
        try:
            datetime.fromisoformat(req.strip())  # accepts YYYY-MM-DD
            requested_date = req.strip()[:10]
        except ValueError:
            requested_date = None
    else:
        requested_date = None

    return {
        "intent": intent,
        "requested_date": requested_date,
        "windows": windows,
        "confidence": max(0.0, min(1.0, conf)),
        "is_availability_answer": bool(raw.get("is_availability_answer", False)),
        "note": str(raw.get("note", ""))[:300],
    }


def _to_naive(iso: str) -> datetime:
    """Parse an ISO string to a naive datetime (drop any tz) for wall-clock compare."""
    dt = datetime.fromisoformat(iso)
    return dt.replace(tzinfo=None)


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday"]


def deterministic_match(clean_reply: str, slots: list[dict], *, tz: str) -> list[dict]:
    """String-level backstop for the LLM: if the reply names a weekday that maps
    to exactly ONE offered slot, return it. Catches bare picks like 'Monday works'
    that the model sometimes fumbles. Returns [] when ambiguous or no match.
    """
    zone = safe_zone(tz)
    low = clean_reply.lower()

    named = [wd for wd in _WEEKDAYS if wd in low]
    if len(named) != 1:
        return []  # zero or multiple weekdays named -> let the LLM decide

    wd = named[0]
    hits = [s for s in slots
            if datetime.fromisoformat(s["start"]).astimezone(zone)
            .strftime("%A").lower() == wd]
    return hits if len(hits) == 1 else []  # only if it uniquely identifies one slot


def intersect_slots(parsed: dict, slots: list[dict], *, tz: str) -> list[dict]:
    """Return the candidate's held/available slots that fall inside any parsed
    window. `slots` items: {slot_id, start, end} where start/end are ISO UTC.
    Windows are wall-clock in `tz`; compare in that zone.
    """
    zone = safe_zone(tz)

    wins = []
    for w in parsed["windows"]:
        try:
            wins.append((_to_naive(w["start"]), _to_naive(w["end"])))
        except ValueError:
            continue

    matched = []
    for s in slots:
        start_local = datetime.fromisoformat(s["start"]).astimezone(zone).replace(tzinfo=None)
        for ws, we in wins:
            if ws <= start_local < we:
                matched.append(s)
                break
    return matched


def decide(parsed: dict, matched_slots: list[dict],
           *, threshold: float = CONFIDENCE_THRESHOLD) -> dict:
    """The gate. Returns {'action': 'confirm'|'escalate', 'reason', 'slots'}.

    Confirm ONLY when it's an availability answer, confidence >= threshold, and
    at least one held/available slot matches. Everything else escalates.
    """
    if not parsed["is_availability_answer"]:
        return {"action": "escalate", "reason": "not an availability answer", "slots": []}
    if parsed["confidence"] < threshold:
        return {"action": "escalate",
                "reason": f"low confidence ({parsed['confidence']:.2f} < {threshold})",
                "slots": []}
    if not matched_slots:
        return {"action": "escalate",
                "reason": "the stated times don't match any open slot", "slots": []}
    return {"action": "confirm", "reason": "high-confidence match", "slots": matched_slots}