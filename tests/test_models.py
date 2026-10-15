"""Tests for the Event model and make_id (Task 2)."""

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest

from radar.models import EXTRACTED_BY, MODES, STATUSES, Event, make_id

IST = timezone(timedelta(hours=5, minutes=30))

# The nine fields that carry no default (identity/validation/provenance).
REQUIRED_FIELDS = dict(
    id="abc123def456",
    name="Example Hack",
    source="devpost",
    url="https://devpost.com/software/example",
    mode="online",
    status="open",
    first_seen=datetime(2026, 10, 1, 9, 30, tzinfo=IST),
    last_seen=datetime(2026, 10, 9, 18, 0, tzinfo=IST),
    extracted_by="api",
)

ALL_KEYS = {
    "id",
    "name",
    "source",
    "url",
    "mode",
    "location",
    "status",
    "reg_deadline",
    "start",
    "end",
    "team_min",
    "team_max",
    "solo_ok",
    "prize",
    "themes",
    "eligibility",
    "cost",
    "also_on",
    "first_seen",
    "last_seen",
    "extracted_by",
}


def _event(**overrides) -> Event:
    """Minimal valid Event (only required fields supplied)."""
    fields = dict(REQUIRED_FIELDS)
    fields.update(overrides)
    return Event(**fields)


def _full_event(**overrides) -> Event:
    """Event with every field populated."""
    fields = dict(
        REQUIRED_FIELDS,
        location="Remote",
        reg_deadline=date(2026, 11, 1),
        start=date(2026, 11, 10),
        end=date(2026, 11, 12),
        team_min=2,
        team_max=4,
        solo_ok=True,
        prize="$10,000",
        themes=["ai", "climate"],
        eligibility="Students",
        cost="Free",
        also_on=["mlh"],
    )
    fields.update(overrides)
    return Event(**fields)


def test_validation_sets_match_the_contract():
    assert STATUSES == {"open", "upcoming", "closed"}
    assert MODES == {"online", "offline", "hybrid"}
    assert EXTRACTED_BY == {"api", "css", "llm"}


def test_to_dict_carries_full_field_set_with_iso_strings():
    data = _full_event().to_dict()
    assert set(data) == ALL_KEYS
    assert data["reg_deadline"] == "2026-11-01"
    assert data["start"] == "2026-11-10"
    assert data["end"] == "2026-11-12"
    assert data["first_seen"] == "2026-10-01T09:30:00+05:30"
    assert data["last_seen"] == "2026-10-09T18:00:00+05:30"
    assert data["themes"] == ["ai", "climate"]
    assert data["also_on"] == ["mlh"]


def test_roundtrip_full_field_set():
    event = _full_event()
    data = event.to_dict()
    restored = Event.from_dict(data)
    assert restored == event
    assert restored.to_dict() == data
    assert restored.first_seen.utcoffset() == timedelta(hours=5, minutes=30)


def test_roundtrip_preserves_nulls_and_empty_lists():
    event = _full_event(
        location=None,
        reg_deadline=None,
        start=None,
        end=None,
        team_min=None,
        team_max=None,
        solo_ok=None,
        prize=None,
        themes=[],
        eligibility=None,
        cost=None,
        also_on=[],
    )
    data = event.to_dict()
    for key in (
        "location",
        "reg_deadline",
        "start",
        "end",
        "team_min",
        "team_max",
        "solo_ok",
        "prize",
        "eligibility",
        "cost",
    ):
        assert data[key] is None
    assert data["themes"] == []
    assert data["also_on"] == []

    restored = Event.from_dict(data)
    assert restored == event
    assert restored.to_dict() == data


def test_falsy_but_valid_optional_values_survive_roundtrip():
    event = _event(team_min=0, team_max=0, solo_ok=False)
    data = event.to_dict()
    assert data["team_min"] == 0
    assert data["team_max"] == 0
    assert data["solo_ok"] is False

    restored = Event.from_dict(data)
    assert restored == event
    assert restored.to_dict() == data
    assert restored.team_min == 0
    assert restored.team_max == 0
    assert restored.solo_ok is False


def test_optional_fields_default_to_none_and_empty_lists():
    event = _event()
    assert event.location is None
    assert event.reg_deadline is None
    assert event.start is None
    assert event.end is None
    assert event.team_min is None
    assert event.team_max is None
    assert event.solo_ok is None
    assert event.prize is None
    assert event.themes == []
    assert event.eligibility is None
    assert event.cost is None
    assert event.also_on == []
    assert Event.from_dict(event.to_dict()) == event


def test_mutable_defaults_are_not_shared_between_instances():
    first, second = _event(), _event()
    first.themes.append("ai")
    first.also_on.append("mlh")
    assert second.themes == []
    assert second.also_on == []


def test_make_id_is_sha1_of_source_pipe_url_truncated_to_12():
    source, url = "devpost", "https://devpost.com/software/example"
    expected = hashlib.sha1(f"{source}|{url}".encode()).hexdigest()[:12]
    assert make_id(source, url) == expected
    assert len(expected) == 12


def test_make_id_is_stable_and_input_sensitive():
    url_a = "https://devpost.com/software/a"
    url_b = "https://devpost.com/software/b"
    assert make_id("devpost", url_a) == make_id("devpost", url_a)
    assert make_id("devpost", url_a) != make_id("devpost", url_b)
    assert make_id("devpost", url_a) != make_id("devfolio", url_a)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("status", "soon"),
        ("status", None),
        ("mode", "onsite"),
        ("mode", None),
        ("extracted_by", "manual"),
        ("extracted_by", None),
    ],
)
def test_invalid_enum_values_raise_value_error(field, bad_value):
    with pytest.raises(ValueError):
        _event(**{field: bad_value})


@pytest.mark.parametrize("field", ["id", "name", "source", "url"])
@pytest.mark.parametrize(
    "bad_value",
    [None, "", "   ", "\t\n"],
    ids=["none", "empty", "spaces", "tabs"],
)
def test_required_string_fields_reject_null_blank_and_whitespace(field, bad_value):
    with pytest.raises(ValueError):
        _event(**{field: bad_value})


def test_all_valid_enum_values_are_accepted():
    for status in STATUSES:
        assert _event(status=status).status == status
    for mode in MODES:
        assert _event(mode=mode).mode == mode
    for extracted_by in EXTRACTED_BY:
        assert _event(extracted_by=extracted_by).extracted_by == extracted_by


def test_from_dict_does_not_fabricate_timezones():
    data = _full_event().to_dict()
    data["first_seen"] = "2026-10-01T09:30:00"
    data["last_seen"] = "2026-10-09T18:00:00"
    restored = Event.from_dict(data)
    assert restored.first_seen == datetime(2026, 10, 1, 9, 30)
    assert restored.first_seen.tzinfo is None
    assert restored.last_seen.tzinfo is None


@pytest.mark.parametrize("field", ["id", "name", "source", "url"])
def test_from_dict_rejects_null_required_fields(field):
    data = _event().to_dict()
    data[field] = None
    with pytest.raises(ValueError):
        Event.from_dict(data)
