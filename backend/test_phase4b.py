"""Pure Phase 4b checks: python test_phase4b.py"""
from reply_parse import CONFIDENCE_THRESHOLD, _coerce, decide, intersect_slots

# UTC slots; job tz Europe/London (UTC+1 in Sep) -> 08:00Z == 09:00 local.
SLOTS = [
    {"slot_id": 1, "start": "2026-09-08T08:00:00+00:00", "end": "2026-09-08T08:30:00+00:00"},  # Tue 09:00 local
    {"slot_id": 2, "start": "2026-09-09T13:00:00+00:00", "end": "2026-09-09T13:30:00+00:00"},  # Wed 14:00 local
]


def test_coerce_clamps_and_defaults():
    p = _coerce({"confidence": 5, "windows": [{"start": "x"}], "is_availability_answer": "yes"})
    assert p["confidence"] == 1.0                 # clamped
    assert p["windows"] == []                     # incomplete window dropped
    assert p["is_availability_answer"] is True


def test_intersection_matches_local_window():
    # "Wednesday afternoon" -> 14:00-17:00 local Wed
    parsed = {"windows": [{"start": "2026-09-09T14:00:00", "end": "2026-09-09T17:00:00"}],
              "confidence": 0.9, "is_availability_answer": True, "note": ""}
    m = intersect_slots(parsed, SLOTS, tz="Europe/London")
    assert [s["slot_id"] for s in m] == [2]


def test_high_confidence_match_confirms():
    parsed = {"windows": [{"start": "2026-09-09T14:00:00", "end": "2026-09-09T17:00:00"}],
              "confidence": 0.9, "is_availability_answer": True, "note": ""}
    m = intersect_slots(parsed, SLOTS, tz="Europe/London")
    assert decide(parsed, m)["action"] == "confirm"


def test_low_confidence_escalates():
    parsed = {"windows": [{"start": "2026-09-09T14:00:00", "end": "2026-09-09T17:00:00"}],
              "confidence": 0.5, "is_availability_answer": True, "note": ""}
    m = intersect_slots(parsed, SLOTS, tz="Europe/London")
    d = decide(parsed, m)
    assert d["action"] == "escalate" and "low confidence" in d["reason"]


def test_not_availability_answer_escalates():
    parsed = {"windows": [], "confidence": 0.9, "is_availability_answer": False, "note": "a question"}
    assert decide(parsed, [])["action"] == "escalate"


def test_zero_slot_match_escalates():
    # high confidence, clear window, but it matches NO open slot
    parsed = {"windows": [{"start": "2026-09-20T14:00:00", "end": "2026-09-20T17:00:00"}],
              "confidence": 0.95, "is_availability_answer": True, "note": ""}
    m = intersect_slots(parsed, SLOTS, tz="Europe/London")
    d = decide(parsed, m)
    assert m == [] and d["action"] == "escalate" and "don't match" in d["reason"]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("all phase 4b pure tests passed")