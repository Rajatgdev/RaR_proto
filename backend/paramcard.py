"""Parameter card: parse a recruiter's plain-English request into a structured
card. One LLM call (gpt-4o-mini) extracts what was stated; everything unstated
falls back to the locked defaults. The LLM only *extracts* — defaults, validation
and coercion are deterministic Python so they're testable without OpenAI.
"""
import json
from datetime import time

from config import settings

# Locked defaults from the build plan's parameter table.
DEFAULTS = {
    "duration_min": 30,          # 30 / 45 / 60
    "format": "google_meet",
    "window_days": 10,           # next 10 working days
    "work_start": "09:00",
    "work_end": "17:00",
    "buffer_min": 10,
    "max_per_interviewer_per_day": 4,
}

_ALLOWED_DURATION = {30, 45, 60}

_SYSTEM = """You extract interview scheduling parameters from a recruiter's request.
Return ONLY JSON, no prose, matching exactly this shape:
{
  "duration_min": 30|45|60|null,
  "window_days": integer|null,
  "work_start": "HH:MM"|null,
  "work_end": "HH:MM"|null,
  "buffer_min": integer|null,
  "max_per_interviewer_per_day": integer|null,
  "interviewers": [{"name": string, "email": string|null}],
  "job_title": string|null,
  "note": string
}
Rules:
- Only fill a field if the recruiter stated or clearly implied it; otherwise null.
- "mornings only" => work_start "09:00", work_end "12:00".
- "over the next two weeks" => window_days 10 (working days). "next week" => 5.
- Interviewer names without emails: include the name, email null.
- note: one short line on what you understood.
Output JSON only."""


def _coerce(raw: dict) -> dict:
    """Merge LLM output over defaults, validating/normalising each field."""
    card = dict(DEFAULTS)

    dur = raw.get("duration_min")
    if dur in _ALLOWED_DURATION:
        card["duration_min"] = dur

    wd = raw.get("window_days")
    if isinstance(wd, int) and 1 <= wd <= 30:
        card["window_days"] = wd

    for key in ("work_start", "work_end"):
        val = raw.get(key)
        if isinstance(val, str):
            try:
                time.fromisoformat(val)  # validates HH:MM
                card[key] = val
            except ValueError:
                pass

    buf = raw.get("buffer_min")
    if isinstance(buf, int) and 0 <= buf <= 60:
        card["buffer_min"] = buf

    cap = raw.get("max_per_interviewer_per_day")
    if isinstance(cap, int) and 1 <= cap <= 20:
        card["max_per_interviewer_per_day"] = cap

    interviewers = []
    for iv in raw.get("interviewers") or []:
        if isinstance(iv, dict) and iv.get("name"):
            interviewers.append({"name": iv["name"], "email": iv.get("email")})
    card["interviewers"] = interviewers

    card["format"] = "google_meet"  # only supported format in prototype
    card["job_title"] = raw.get("job_title") or "Untitled role"
    card["note"] = raw.get("note") or ""
    return card


def parse_request(text: str) -> dict:
    """LLM parse -> validated parameter card. Falls back to pure defaults on any
    LLM/parse failure so the recruiter can still edit a card manually."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = json.loads(resp.choices[0].message.content)
    except Exception as e:
        raw = {"note": f"could not auto-parse ({type(e).__name__}); using defaults"}
    return _coerce(raw)