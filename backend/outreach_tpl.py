"""Outreach email template. Pure rendering so it's testable without Gmail.

The recruiter approves ONE template at Gate 2; it's rendered per candidate with
their name, the interviewer, and the offered slots shown in the candidate's own
timezone. Placeholders: {name} {interviewer} {slots} {duration} {job}.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_SUBJECT = "Interview scheduling — {job}"

DEFAULT_BODY = """Hi {name},

Thanks for your interest in the {job} role. I'd like to set up a {duration}-minute
screen with {interviewer}. Here are some times that work — just reply with the one
you'd like (or suggest another that suits you):

{slots}

Looking forward to hearing back.

Best,
The scheduling team
"""


def format_slots(slots: list[dict], tz: str) -> str:
    """slots: [{start,end}] ISO UTC -> a readable bulleted list in the candidate's tz."""
    zone = ZoneInfo(tz)
    lines = []
    for s in slots:
        start = datetime.fromisoformat(s["start"]).astimezone(zone)
        lines.append("  • " + start.strftime("%A %d %B, %I:%M %p %Z"))
    return "\n".join(lines)


def render(template_subject: str, template_body: str, *, name: str | None,
           interviewer: str, job: str, duration: int,
           slots: list[dict], tz: str) -> tuple[str, str]:
    fields = {
        "name": name or "there",
        "interviewer": interviewer,
        "job": job,
        "duration": duration,
        "slots": format_slots(slots, tz),
    }
    return template_subject.format(**fields), template_body.format(**fields)