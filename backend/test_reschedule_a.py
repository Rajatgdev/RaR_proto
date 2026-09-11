"""Chunk A pure checks (no OpenAI): python test_reschedule_a.py"""
from reply_parse import _coerce, parse_reply


def test_pick_slot_default_intent():
    c = _coerce({"windows": [{"start": "2026-09-14T09:00:00", "end": "2026-09-14T09:30:00"}],
                 "confidence": 0.9, "is_availability_answer": True})
    assert c["intent"] == "pick_slot"          # default when absent
    assert c["requested_date"] is None
    assert c["windows"]


def test_cancel_intent():
    c = _coerce({"intent": "cancel", "confidence": 0.9, "is_availability_answer": False,
                 "note": "wants to cancel"})
    assert c["intent"] == "cancel"
    assert c["windows"] == []


def test_reschedule_with_requested_date():
    c = _coerce({"intent": "reschedule", "requested_date": "2026-09-16",
                 "confidence": 0.8, "is_availability_answer": False})
    assert c["intent"] == "reschedule"
    assert c["requested_date"] == "2026-09-16"


def test_bad_intent_falls_back():
    c = _coerce({"intent": "explode", "confidence": 0.5})
    assert c["intent"] == "pick_slot"


def test_bad_date_dropped():
    c = _coerce({"intent": "reschedule", "requested_date": "the 16th"})
    assert c["requested_date"] is None          # unparseable -> None, no crash


def test_failure_path_has_new_keys():
    # With a real OPENAI key this makes a live call; without one it takes the
    # failure path. Either way, the new keys must always be present so callers
    # never KeyError.
    r = parse_reply("please cancel", tz="Europe/Dublin", offered_slots=[], already_booked=True)
    assert r["intent"] in ("pick_slot", "cancel", "reschedule", "other")
    assert "requested_date" in r and "windows" in r and "confidence" in r


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_") and callable(f):
            f()
    print("all chunk A tests passed")