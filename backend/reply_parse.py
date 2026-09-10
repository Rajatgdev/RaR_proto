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

_SYSTEM = """You read a candidate's email reply and decide which of the OFFERED
interview slots they chose (or whether they proposed a genuinely different time).

You are given a numbered list of offered slots, each labelled with its weekday
AND date (e.g. "Monday 14 September"). That list is the SOURCE OF TRUTH for which
weekday maps to which date. Return ONLY JSON in exactly this shape:
{
  "windows": [{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}],
  "confidence": 0.0,
  "is_availability_answer": true,
  "note": "one short line on what you understood"
}
Rules:
- The candidate is replying to an email that offered exactly those slots. If they
  name a weekday, a date, or a time that appears in the offered list — even bare
  ("Monday works", "Wednesday is good", "the 1:30 one") — treat it as choosing
  THAT offered slot. Return a window spanning exactly that slot's start–end, set
  is_availability_answer=true, confidence high (>=0.8).
- A bare weekday that matches a weekday in the offered list is a MATCH. Do NOT
  assume the candidate means a different week — the offered list defines the dates.
- Only if they name a day/time that is NOT anywhere in the offered list, return
  that window with lower confidence, is_availability_answer=true.
- Set is_availability_answer=false ONLY for a question, a decline, or a message
  that is not about picking a time at all.
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


def parse_reply(reply_text: str, *, tz: str, offered_slots: list[dict]) -> dict:
    """LLM parse against the concrete offered slots. Strips quoted history first.
    Returns the validated structured dict (defaults on failure)."""
    clean = strip_quoted(reply_text) or reply_text
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        user = (f"Job timezone: {tz}\n\nOffered slots:\n{_slot_lines(offered_slots, tz)}\n\n"
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
        return {"windows": [], "confidence": 0.0, "is_availability_answer": False,
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
    return {
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