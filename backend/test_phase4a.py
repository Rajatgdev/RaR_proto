"""Pure Phase 4a checks: python test_phase4a.py"""
from outreach_tpl import DEFAULT_BODY, DEFAULT_SUBJECT, format_slots, render

SLOTS = [
    {"start": "2026-09-08T08:00:00+00:00", "end": "2026-09-08T08:30:00+00:00"},
    {"start": "2026-09-09T09:00:00+00:00", "end": "2026-09-09T09:30:00+00:00"},
]


def test_format_slots_uses_candidate_tz():
    # 08:00 UTC shown in New York (-4 in Sep) = 04:00 AM
    out = format_slots(SLOTS, "America/New_York")
    assert "04:00 AM" in out
    # same slot in London (+1) = 09:00 AM
    out_lon = format_slots(SLOTS, "Europe/London")
    assert "09:00 AM" in out_lon


def test_render_fills_placeholders():
    subject, body = render(
        DEFAULT_SUBJECT, DEFAULT_BODY,
        name="Alex", interviewer="Jamie", job="Backend Eng",
        duration=30, slots=SLOTS, tz="Europe/London")
    assert "Backend Eng" in subject
    assert "Hi Alex," in body
    assert "Jamie" in body
    assert "30-minute" in body
    assert "09:00 AM" in body


def test_render_defaults_missing_name():
    _, body = render(DEFAULT_SUBJECT, DEFAULT_BODY, name=None, interviewer="Jamie",
                     job="Role", duration=45, slots=SLOTS, tz="Europe/London")
    assert "Hi there," in body


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("all phase 4a pure tests passed")