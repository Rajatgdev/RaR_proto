"""Runnable checks for the pure Phase 2 logic: python test_phase2.py"""
from paramcard import DEFAULTS, _coerce
from normalise import normalise, parse_csv, valid_email


# --- parameter card coercion ---------------------------------------------

def test_empty_llm_output_falls_back_to_defaults():
    card = _coerce({})
    for k, v in DEFAULTS.items():
        assert card[k] == v, (k, card[k], v)
    assert card["interviewers"] == []
    assert card["format"] == "google_meet"


def test_stated_fields_override_defaults():
    card = _coerce({
        "duration_min": 45,
        "work_start": "09:00", "work_end": "12:00",  # "mornings only"
        "buffer_min": 15,
        "interviewers": [{"name": "Jamie", "email": None}],
    })
    assert card["duration_min"] == 45
    assert card["work_end"] == "12:00"
    assert card["buffer_min"] == 15
    assert card["interviewers"] == [{"name": "Jamie", "email": None}]


def test_invalid_values_are_rejected():
    card = _coerce({"duration_min": 37, "buffer_min": 999, "work_start": "9am"})
    assert card["duration_min"] == 30      # 37 not allowed -> default
    assert card["buffer_min"] == 10        # out of range -> default
    assert card["work_start"] == "09:00"   # unparseable -> default


# --- candidate normalisation ---------------------------------------------

def test_email_validation():
    assert valid_email("a@b.co")
    assert not valid_email("nope")
    assert not valid_email(None)


def test_dedupe_and_bad_email_and_tz_default():
    raw = [
        {"name": "A", "email": "a@x.com", "timezone": None},
        {"name": "A2", "email": "A@x.com", "timezone": None},   # dup (case-insensitive)
        {"name": "B", "email": "bad", "timezone": None},         # invalid
        {"name": "C", "email": "c@x.com", "timezone": "America/New_York"},
    ]
    out = normalise(raw, job_timezone="Europe/London")
    emails = [c["email"] for c in out["ready"]]
    assert emails == ["a@x.com", "c@x.com"]
    assert out["ready"][0]["timezone"] == "Europe/London"       # defaulted
    assert out["ready"][0]["timezone_assumed"] is True
    assert out["ready"][1]["timezone"] == "America/New_York"    # kept
    assert len(out["excluded"]) == 2
    assert out["summary"] == "2 candidates ready, 2 need attention"


def test_csv_parse():
    rows = parse_csv("Name,Email\nJane,jane@x.com\nJohn,john@x.com\n")
    assert rows == [
        {"name": "Jane", "email": "jane@x.com", "phone": None, "timezone": None},
        {"name": "John", "email": "john@x.com", "phone": None, "timezone": None},
    ]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("all phase 2 tests passed")