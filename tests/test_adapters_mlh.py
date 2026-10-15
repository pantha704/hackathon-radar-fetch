"""Tests for the MLH season-page adapter (Task 8, browser kind).

Fixture-driven: `tests/fixtures/mlh/listing.html` is a real captured render
of https://mlh.io/seasons/2026/events (M0, 2026-10-09). No test here touches
the network.

The second-season capture `tests/fixtures/mlh_2025/listing.html` (the spare)
is used to prove the season year is derived from the page itself, never
hardcoded.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.mlh import LISTING_URL, MlhAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "mlh" / "listing.html"
SPARE_2025 = ROOT / "tests" / "fixtures" / "mlh_2025" / "listing.html"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
HTML = FIXTURE.read_text(encoding="utf-8")


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(html=HTML, **ctx_overrides):
    """Run the MLH parser on a payload (pure: payload + ctx only)."""
    return MlhAdapter().parse(html, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}


def _card(name, href, date_text, location, badge, *, anchor=True):
    """Build a synthetic MLH card with the fixture's exact class vocabulary."""
    card = (
        '<div class="rounded-card relative overflow-hidden">'
        f"<div><h4>{name}</h4></div>"
        '<div class="flex flex-col gap-2">'
        '<div class="flex items-center gap-2 min-w-0 text-gray-600">'
        f'<span class="text-sm truncate">{date_text}</span></div>'
        '<div class="flex items-center gap-2 min-w-0 text-gray-600">'
        f'<span class="text-sm truncate">{location}</span></div>'
        "</div>"
        f'<div><span class="inline-flex items-center">{badge}</span></div>'
        "</div>"
    )
    return f'<a href="{href}">{card}</a>' if anchor else card


def _page(*fragments):
    """Wrap card fragments in a minimal season-page shell (title carries year)."""
    return (
        "<!doctype html><html><head>"
        "<title>2026 Season Schedule // Major League Hacking</title>"
        "</head><body>" + "".join(fragments) + "</body></html>"
    )


# --- fixture sanity ---------------------------------------------------------


def test_fixture_is_a_real_captured_mlh_season_page():
    assert FIXTURE.is_file()
    assert "2026 Season Schedule" in HTML
    assert HTML.count("rounded-card") >= 24
    assert SPARE_2025.is_file()  # the second-season capture used below


# --- parse contract ---------------------------------------------------------


def test_parse_produces_at_least_three_events_with_name_and_url():
    assert len(EVENTS) >= 3
    for event in EVENTS:
        assert isinstance(event.name, str) and event.name.strip()
        assert event.url.startswith("https://")


def test_parse_extracts_every_card_in_the_fixture_grid():
    assert len(EVENTS) == 24


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "css"
    assert event.id == make_id("mlh", event.url)


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    for event in EVENTS:
        assert event.source == "mlh"
        assert event.first_seen == NOW
        assert event.last_seen == NOW
        assert event.first_seen.tzinfo is not None


def test_parse_is_deterministic():
    assert _parse() == _parse() == EVENTS


def test_parse_stamps_a_different_ctx_now_verbatim():
    other = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
    events = _parse(now=other)
    assert events
    assert all(e.first_seen == other and e.last_seen == other for e in events)


# --- fixture field mapping --------------------------------------------------


def test_tracking_params_are_stripped_from_every_url():
    # Cards link out with mlh utm_* parameters; the canonical (stable-id)
    # URL is the destination without tracking params.
    for event in EVENTS:
        assert "utm_" not in event.url
        assert "?" not in event.url  # nothing else was in the query string either


def test_offline_card_maps_name_dates_location_and_mode():
    event = BY_URL["https://jamhacks.ca/"]
    assert event.name == "JAMHacks 10"
    assert event.mode == "offline"  # "In-Person" badge
    assert event.start == date(2026, 6, 12)
    assert event.end == date(2026, 6, 14)
    assert event.location == "Waterloo, Ontario, CA"


def test_digital_card_maps_to_online_with_its_own_location_text():
    event = BY_URL["https://events.mlh.io/events/14302-global-hack-week-hacking-for-good"]
    assert event.name == "Global Hack Week: Hacking for Good"
    assert event.mode == "online"  # "Digital" badge
    assert event.start == date(2026, 6, 12)
    assert event.end == date(2026, 6, 18)
    assert event.location == "Everywhere, Worldwide"


def test_external_card_url_is_the_destination_without_tracking():
    event = BY_URL["https://s3.hackprix.tech/"]
    assert event.name == "HackPrix Season 3"
    assert event.mode == "offline"
    assert (event.start, event.end) == (date(2026, 6, 13), date(2026, 6, 14))


def test_april_card_dates_use_the_season_year():
    event = BY_URL["https://lahacks.com/"]
    assert event.start == date(2026, 4, 24)
    assert event.end == date(2026, 4, 26)


def test_location_is_kept_raw_even_when_it_is_a_full_address():
    event = BY_URL["https://www.keanuhackthis.com/"]
    assert event.location == "Union, 1075 Morris Ave, Union, NJ 07083, US"


def test_status_is_derived_from_the_date_range_vs_context_now():
    # The cards carry no status badge; every 2026-season card in this capture
    # ended before ctx["now"] (2026-10-09), so all are closed.
    assert all(event.status == "closed" for event in EVENTS)


def test_mode_split_matches_the_pages_own_badges():
    # 3 "Digital" badges -> online; 21 "In-Person" badges -> offline.
    assert sum(e.mode == "online" for e in EVENTS) == 3
    assert sum(e.mode == "offline" for e in EVENTS) == 21


def test_fields_absent_from_the_cards_stay_none_or_empty():
    # The season cards carry name, date range, location and a mode badge only.
    for event in EVENTS:
        assert event.reg_deadline is None
        assert event.team_min is None and event.team_max is None
        assert event.solo_ok is None
        assert event.prize is None
        assert event.themes == []
        assert event.eligibility is None
        assert event.cost is None
        assert event.also_on == []


def test_extra_badges_beyond_the_mode_badge_are_ignored():
    # JAMHacks 10 also carries a "HIGH SCHOOL" badge; it must not disturb mode.
    event = BY_URL["https://jamhacks.ca/"]
    assert event.mode == "offline"


# --- synthetic edge cases (branches the captured fixture does not cover) ----


def test_future_card_is_upcoming_and_present_card_is_open():
    upcoming = _card("Future Hack", "https://future.example/", "OCT 30 - 31",
                     "Nowhere, US", "In-Person")
    ongoing = _card("Ongoing Hack", "https://ongoing.example/", "OCT 08 - 12",
                    "Elsewhere, US", "Digital")
    events = _parse(_page(upcoming, ongoing))
    assert [e.status for e in events] == ["upcoming", "open"]
    assert events[1].mode == "online"


def test_cross_month_range_keeps_its_end_in_the_next_month():
    card = _card("Year Wrap", "https://wrap.example/", "DEC 30 - JAN 2",
                 "Somewhere, CA", "In-Person")
    (event,) = _parse(_page(card))
    assert (event.start, event.end) == (date(2026, 12, 30), date(2027, 1, 2))


def test_single_day_range_collapses_start_and_end():
    card = _card("One Day", "https://oneday.example/", "OCT 09",
                 "Somewhere, US", "In-Person")
    (event,) = _parse(_page(card))
    assert (event.start, event.end) == (date(2026, 10, 9), date(2026, 10, 9))
    assert event.status == "open"


def test_payload_without_a_season_year_yields_nothing_instead_of_guessing():
    # No "NNNN Season" in the title -> no honest dates/status for any card.
    card = _card("No Year", "https://noyear.example/", "OCT 30 - 31", "X", "In-Person")
    assert _parse("<!doctype html><html><body>" + card + "</body></html>") == []


def test_the_season_year_comes_from_the_page_not_a_constant():
    # Same selectors against the 2025-season capture: dates must be 2025.
    events = MlhAdapter().parse(SPARE_2025.read_text(encoding="utf-8"), _ctx())
    assert len(events) == 24
    by_url = {e.url: e for e in events}
    gdg = by_url["https://thesolutionhacks.site/"]
    assert (gdg.start, gdg.end) == (date(2025, 6, 27), date(2025, 6, 29))
    assert gdg.mode == "offline"
    assert all(e.status == "closed" for e in events)


def test_cards_without_name_or_anchor_are_skipped_not_faked():
    assert _parse(_page(_card("", "https://x.example/", "OCT 30 - 31", "X", "In-Person"))) == []
    assert _parse(_page(_card("No Anchor", "https://y.example/", "OCT 30 - 31", "Y",
                        "In-Person", anchor=False))) == []


def test_card_with_unknown_mode_badge_is_skipped_not_guessed():
    card = _card("Odd Badge", "https://odd.example/", "OCT 30 - 31", "X", "HYBRID")
    assert _parse(_page(card)) == []


def test_card_with_unparseable_or_missing_date_is_skipped_not_guessed():
    assert _parse(_page(_card("TBD Hack", "https://tbd.example/", "TBD", "X", "In-Person"))) == []
    assert _parse(_page(_card("No Date", "https://nodate.example/", "", "X", "In-Person"))) == []


def test_same_month_day_inversion_is_skipped_not_guessed():
    # "JUN 30 - 5" has no second month to wrap into; an end before the start
    # is malformed, so the card is skipped rather than emitting end < start.
    card = _card("Inverted", "https://inverted.example/", "JUN 30 - 5",
                 "Somewhere, US", "In-Person")
    assert _parse(_page(card)) == []


def test_non_string_payload_yields_no_events_instead_of_crashing():
    assert MlhAdapter().parse(None, _ctx()) == []


# --- fetch (contract only; no network) --------------------------------------


class _FakeCrawl:
    """Records the URL it receives instead of touching the network."""

    def __init__(self):
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return HTML


def test_fetch_uses_the_ctx_crawl_callable_on_the_listing_url():
    fake = _FakeCrawl()
    result = MlhAdapter().fetch(_ctx(crawl=fake))
    assert result is HTML
    assert fake.calls == [LISTING_URL]


def test_listing_url_is_the_2026_season_page():
    assert LISTING_URL == "https://mlh.io/seasons/2026/events"


# --- registry, sources.yaml -------------------------------------------------


def test_registry_exposes_the_mlh_adapter():
    adapter = ADAPTERS["mlh"]
    assert isinstance(adapter, MlhAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "mlh"
    assert adapter.kind == "browser"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_mlh_as_browser_kind():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    mlh = next(entry for entry in entries if entry["id"] == "mlh")
    assert mlh["kind"] == "browser"
    assert mlh["enabled"] is True
    assert mlh["url"] == LISTING_URL
    assert isinstance(mlh["notes"], str) and mlh["notes"].strip()
