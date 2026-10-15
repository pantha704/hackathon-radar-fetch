"""Tests for radar.store (Task 6).

Pins the bindings from the task brief + SDD rulings:
- ``load(path)`` reads the ``{"meta": {...}, "events": [...]}`` shape; a
  missing file is an empty store (``{"meta": {}, "events": []}``); malformed
  JSON raises (fail loud — a corrupt store must never read as "no events").
- ``save(path, events, meta)`` creates parent dirs and writes
  ``{"meta": meta, "events": [e.to_dict(), ...]}`` with
  ``json.dumps(..., indent=2, ensure_ascii=False)``; events are sorted by
  ``id`` so two saves of the same data are byte-equal (clean git diffs).
  The payload is serialized before the file is opened, so a failure (e.g.
  a datetime meta → ``TypeError``) leaves an existing store byte-identical.
- ``load_events(path)`` returns ``id -> Event`` via ``Event.from_dict``;
  ``{}`` when the file is missing.
"""

import json
from datetime import date, datetime, timezone

import pytest

from radar.models import Event, make_id
from radar.store import load, load_events, save

SEEN = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
META = {"last_updated": "2026-10-09T22:30:00+05:30", "open": 4, "online": 3, "new": 2}


def _event(i: int, **overrides) -> Event:
    source = "devpost"
    url = f"https://devpost.com/software/event-{i}"
    kwargs = dict(
        id=make_id(source, url),
        name=f"Event {i}",
        source=source,
        url=url,
        mode="online",
        status="open",
        first_seen=SEEN,
        last_seen=SEEN,
        extracted_by="api",
        reg_deadline=date(2026, 11, 1),
        prize="Prize — 1",
        themes=["AI"],
        also_on=[],
    )
    kwargs.update(overrides)
    return Event(**kwargs)


EVENTS = [_event(2), _event(1)]  # deliberately NOT sorted by id


def _expected_events() -> list[dict]:
    return [event.to_dict() for event in sorted(EVENTS, key=lambda e: e.id)]


# --- save -------------------------------------------------------------------


def test_save_creates_parents_and_writes_meta_and_event_dicts(tmp_path):
    path = tmp_path / "data" / "radar.json"
    save(path, EVENTS, META)
    assert path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["meta"] == META
    assert raw["events"] == _expected_events()


def test_save_sorts_events_by_id(tmp_path):
    path = tmp_path / "radar.json"
    save(path, EVENTS, META)
    raw = json.loads(path.read_text(encoding="utf-8"))
    ids = [event["id"] for event in raw["events"]]
    assert ids == sorted(ids)


def test_save_is_byte_deterministic(tmp_path):
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    save(first, EVENTS, META)
    save(second, EVENTS, META)
    assert first.read_bytes() == second.read_bytes()
    before = first.read_bytes()
    save(first, EVENTS, META)  # re-save over the same path
    assert first.read_bytes() == before


def test_save_writes_indented_utf8_without_ascii_escapes(tmp_path):
    path = tmp_path / "radar.json"
    save(path, EVENTS, META)
    text = path.read_text(encoding="utf-8")
    assert '\n  "meta"' in text  # indent=2
    assert "Prize — 1" in text  # ensure_ascii=False keeps unicode as-is
    assert "\\u2014" not in text


def test_save_raises_typeerror_on_datetime_meta(tmp_path):
    path = tmp_path / "data" / "radar.json"
    bad_meta = {"last_updated": datetime(2026, 10, 9, 22, 30, tzinfo=timezone.utc)}
    with pytest.raises(TypeError):
        save(path, EVENTS, bad_meta)
    assert not path.exists()  # serialization failed before the file was opened


def test_save_failure_never_truncates_existing_store(tmp_path):
    path = tmp_path / "radar.json"
    save(path, EVENTS, META)
    before = path.read_bytes()
    bad_meta = {"last_updated": datetime(2026, 10, 9, 22, 30, tzinfo=timezone.utc)}
    with pytest.raises(TypeError):
        save(path, EVENTS, bad_meta)
    assert path.read_bytes() == before


# --- load -------------------------------------------------------------------


def test_load_missing_file_is_the_empty_store(tmp_path):
    assert load(tmp_path / "nope.json") == {"meta": {}, "events": []}


def test_load_round_trips_saved_data(tmp_path):
    path = tmp_path / "radar.json"
    save(path, EVENTS, META)
    assert load(path) == {"meta": META, "events": _expected_events()}


def test_load_malformed_json_raises_loud(tmp_path):
    path = tmp_path / "radar.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load(path)


# --- load_events ------------------------------------------------------------


def test_load_events_missing_file_is_empty_dict(tmp_path):
    assert load_events(tmp_path / "nope.json") == {}


def test_load_events_maps_id_to_event(tmp_path):
    path = tmp_path / "radar.json"
    save(path, EVENTS, META)
    got = load_events(path)
    assert set(got) == {event.id for event in EVENTS}
    for event in EVENTS:
        assert isinstance(got[event.id], Event)
        assert got[event.id] == event


def test_load_events_malformed_json_raises_loud(tmp_path):
    path = tmp_path / "radar.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_events(path)
