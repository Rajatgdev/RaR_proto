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

# Tunable during testing (build-plan says make it a config value).
CONFIDENCE_THRESHOLD = 0.75

_SYSTEM = """You read a candidate's email reply about interview scheduling and
extract when they are available. Return ONLY JSON in exactly this shape:
{
  "windows": [{"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS"}],
  "confidence": 0.0,
  "is_availability_answer": true,
  "note": "one short line on what you understood or why unsure"
}
Rules:
- Interpret relative dates ("next Tuesday", "tomorrow afternoon") against the
  job timezone and interview window given in the user message, NOT today's date.
- Times are local to the job timezone; output naive ISO (no offset).
- "afternoon" = 12:00-17:00, "morning" = 09:00-12:00 unless they say otherwise.
- If the message is a question, a decline, or not about availability, set
  is_availability_answer=false and confidence low.
- confidence reflects how sure you are you understood their availability.
Output JSON only."""


def parse_reply(reply_text: str, *, tz: str, window_hint: str) -> dict:
    """LLM parse. Returns the raw structured dict (validated shape, defaults on
    failure). No decisions here — the caller applies the gate."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        user = (f"Job timezone: {tz}\nInterview window: {window_hint}\n\n"
                f"Candidate reply:\n{reply_text}")
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


def intersect_slots(parsed: dict, slots: list[dict], *, tz: str) -> list[dict]:
    """Return the candidate's held/available slots that fall inside any parsed
    window. `slots` items: {slot_id, start, end} where start/end are ISO UTC.
    Windows are wall-clock in `tz`; compare in that zone.
    """
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(tz)

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