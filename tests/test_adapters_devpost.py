"""Tests for the adapter base, registry and devpost adapter (Task 3).

Fixture-driven: the devpost payload is a real captured API page; no network.
"""

import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.devpost import DevpostAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "devpost" / "listing_p1.json"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
PAYLOAD = json.loads(FIXTURE.read_text())


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(payload=PAYLOAD, **ctx_overrides):
    """Run the devpost parser on a payload (pure: payload + ctx only)."""
    return DevpostAdapter().parse(payload, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}
RAW_BY_URL = {item["url"]: item for item in PAYLOAD["hackathons"]}


# --- fixture sanity ---------------------------------------------------------


def test_fixture_has_at_least_five_listing_items():
    assert len(PAYLOAD["hackathons"]) >= 5


# --- parse contract ---------------------------------------------------------


def test_parse_produces_one_event_per_listing_item():
    assert len(EVENTS) >= 5
    assert len(EVENTS) == len(PAYLOAD["hackathons"])
    assert {event.url for event in EVENTS} == set(RAW_BY_URL)


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert isinstance(event.name, str) and event.name.strip()
    assert event.url.startswith("https://")
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "api"
    assert event.id == make_id("devpost", event.url)


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    for event in EVENTS:
        assert event.source == "devpost"
        assert event.extracted_by == "api"
        assert event.id == make_id("devpost", event.url)
        assert event.first_seen == NOW
        assert event.last_seen == NOW
        assert event.first_seen.tzinfo is not None


def test_parse_stamps_a_different_ctx_now_verbatim():
    other = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
    events = _parse(now=other)
    assert events
    assert all(
        event.first_seen == other and event.last_seen == other for event in events
    )


def test_parse_is_pure_deterministic_and_does_not_mutate_payload():
    before = copy.deepcopy(PAYLOAD)
    first = _parse()
    second = _parse()
    assert first == second == EVENTS
    assert PAYLOAD == before


# --- fixture field mapping --------------------------------------------------


def test_fixture_fields_map_to_event_fields():
    for url, item in RAW_BY_URL.items():
        event = BY_URL[url]
        assert event.name == item["title"]
        assert event.location == item["displayed_location"]["location"]
        assert event.mode == "online"  # every captured listing row is Online
        assert event.status == "open"  # every captured listing row is open
        assert event.themes == [theme["name"] for theme in item["themes"]]


def test_prize_is_the_visible_amount_without_markup():
    amazon = BY_URL["https://amazonappdev2026.devpost.com/"]
    assert amazon.prize == "$138,000"
    multimodal = BY_URL["https://multimodal-ai-hackathon-2026-7.devpost.com/"]
    assert multimodal.prize == "₹ 100,000"


def test_submission_period_dates_map_to_start_end_and_deadline():
    amazon = BY_URL["https://amazonappdev2026.devpost.com/"]  # "Aug 31 - Oct 23, 2026"
    assert amazon.start == date(2026, 8, 31)
    assert amazon.end == date(2026, 10, 23)
    assert amazon.reg_deadline == date(2026, 10, 23)

    forge = BY_URL["https://forgehacks-2026.devpost.com/"]  # "Oct 01 - 10, 2026"
    assert forge.start == date(2026, 10, 1)
    assert forge.end == date(2026, 10, 10)
    assert forge.reg_deadline == date(2026, 10, 10)


def test_team_fields_stay_none_when_payload_has_no_team_info():
    for event in EVENTS:
        assert event.team_min is None
        assert event.team_max is None
        assert event.solo_ok is None
        assert event.eligibility is None
        assert event.cost is None


# --- synthetic edge cases (branches the captured fixture does not cover) ----


def test_offline_and_upcoming_branch_and_missing_data_stay_honest():
    item = {
        "title": "Berlin Offline Hack",
        "url": "https://berlin-offline.devpost.com/",
        "displayed_location": {"location": "Berlin, Germany"},
        "open_state": "coming_soon",
        "submission_period_dates": "dates to be announced",
    }
    (event,) = _parse({"hackathons": [item]})
    assert event.mode == "offline"
    assert event.location == "Berlin, Germany"
    assert event.status == "upcoming"
    assert event.start is None and event.end is None and event.reg_deadline is None
    assert event.prize is None
    assert event.themes == []
    assert event.team_min is None and event.team_max is None and event.solo_ok is None


def test_period_crossing_new_year_parses_with_wrapped_start_year():
    item = {
        "title": "Year Wrap Hack",
        "url": "https://year-wrap.devpost.com/",
        "displayed_location": {"location": "Online"},
        "open_state": "open",
        "submission_period_dates": "Dec 20 - Jan 10, 2027",
    }
    (event,) = _parse({"hackathons": [item]})
    assert event.start == date(2026, 12, 20)
    assert event.end == date(2027, 1, 10)


def test_items_without_title_or_url_are_skipped_not_faked():
    items = [
        {
            "title": "Good Hack",
            "url": "https://good.devpost.com/",
            "open_state": "open",
            "displayed_location": {"location": "Online"},
        },
        {"url": "https://no-title.devpost.com/"},  # no title
        {"title": "No URL Hack"},  # no url
        {"title": "   ", "url": "https://blank-title.devpost.com/"},  # blank title
        {"title": "Blank URL", "url": ""},  # blank url
    ]
    events = _parse({"hackathons": items})
    assert [event.url for event in events] == ["https://good.devpost.com/"]


# --- fetch (contract only; no network) --------------------------------------


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeHTTP:
    """Records the GET it receives instead of touching the network."""

    def __init__(self, data):
        self._data = data
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers or {}, "timeout": timeout})
        return _FakeResponse(self._data)


def test_fetch_gets_the_listing_endpoint_with_a_desktop_chrome_ua():
    fake = _FakeHTTP(PAYLOAD)
    result = DevpostAdapter().fetch(_ctx(http=fake))
    assert result is PAYLOAD
    (call,) = fake.calls
    assert call["url"] == "https://devpost.com/api/hackathons?page=1"
    user_agent = call["headers"]["User-Agent"]
    assert "Mozilla" in user_agent and "Chrome" in user_agent


# --- base ABC, registry, sources.yaml ---------------------------------------


def test_adapter_base_is_abstract():
    with pytest.raises(TypeError):
        Adapter()
    assert isinstance(DevpostAdapter(), Adapter)


def test_registry_exposes_the_devpost_adapter():
    adapter = ADAPTERS["devpost"]
    assert isinstance(adapter, DevpostAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "devpost"
    assert adapter.kind == "api"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_devpost_with_the_agreed_shape():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    assert isinstance(entries, list) and entries
    expected_keys = {"id", "kind", "enabled", "url", "notes"}
    for entry in entries:
        assert set(entry) == expected_keys
        assert isinstance(entry["id"], str) and entry["id"]
        assert entry["kind"] in {"api", "browser", "hybrid"}
        assert isinstance(entry["enabled"], bool)
        assert entry["url"].startswith("https://")
        assert isinstance(entry["notes"], str) and entry["notes"].strip()

    devpost = next(entry for entry in entries if entry["id"] == "devpost")
    assert devpost["kind"] == "api"
    assert devpost["enabled"] is True
    assert "devpost.com" in devpost["url"]
