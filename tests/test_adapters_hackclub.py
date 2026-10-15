"""Tests for the hackathons.hackclub.com adapter (Task 10, browser kind).

Fixture-driven: `tests/fixtures/hackclub/listing.html` is a real captured
render of https://hackathons.hackclub.com/ (M0, 2026-10-09). No test here
touches the network.

The fixture's card grid carries 120 schema.org-annotated cards. The parse
keeps 108 of them: 9 later editions of 8 duplicate-URL pairs (one URL has
three cards) are dropped (first occurrence wins — the newest edition), and
3 cards whose links are http-only (no https form) are skipped by the https
identity rule. Both counts are pinned below and reported in the task report.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.hackclub import LISTING_URL, HackclubAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "hackclub" / "listing.html"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
HTML = FIXTURE.read_text(encoding="utf-8")


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(html=HTML, **ctx_overrides):
    """Run the hackclub parser on a payload (pure: payload + ctx only)."""
    return HackclubAdapter().parse(html, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}


def _card(
    name="Test Hack",
    href="https://test.example/",
    start="2026-10-30T09:00:00.000Z",
    end="2026-10-31T17:00:00.000Z",
    badge="Online",
    location=None,
    *,
    with_dates=True,
):
    """Build a synthetic card with the fixture's schema.org microdata shape."""
    if location is None:
        loc = (
            '<span class="css-lgbo0i" itemprop="location" itemscope="" '
            'itemtype="http://schema.org/Place"></span>'
        )
    else:
        loc = (
            '<span class="css-lgbo0i" itemprop="location" itemscope="" '
            'itemtype="http://schema.org/Place">'
            f'<span itemprop="address">: {location}</span></span>'
        )
    dates = ""
    if with_dates:
        dates = (
            f'<span content="{start}" itemprop="startDate">{start}</span>'
            f'<span content="{end}" itemprop="endDate">{end}</span>'
        )
    return (
        f'<a class="css-18i15e0" href="{href}" itemscope="" '
        'itemtype="http://schema.org/Event" rel="noopener noreferrer" target="_blank">'
        f'<span class="css-1qp34pt" itemtype="VirtualLocation">{badge}</span>'
        f'<h3 class="css-1da4wop" itemprop="name">{name}</h3>'
        '<footer class="css-1eev5yq">'
        '<span class="css-lgbo0i">October 30–31</span>'
        f"{loc}</footer>"
        '<div class="css-lnimg4">'
        '<span itemprop="eventAttendanceMode">https://schema.org/OnlineEventAttendanceMode</span>'
        f'<span itemprop="url">{href}</span>'
        f"{dates}</div></a>"
    )


def _page(*cards):
    """Wrap card fragments in a minimal page shell."""
    return "<!doctype html><html><body>" + "".join(cards) + "</body></html>"


# --- fixture sanity ---------------------------------------------------------


def test_fixture_is_a_real_captured_hackclub_listing():
    assert FIXTURE.is_file()
    assert "High School Hackathons in 2026" in HTML
    assert HTML.count('itemtype="http://schema.org/Event"') == 120


# --- parse contract ---------------------------------------------------------


def test_parse_produces_at_least_three_events_with_name_and_url():
    assert len(EVENTS) >= 3
    for event in EVENTS:
        assert isinstance(event.name, str) and event.name.strip()
        assert event.url.startswith("https://")


def test_parse_keeps_108_of_the_120_cards():
    # 120 cards - 9 later duplicate-URL editions - 3 http-only links = 108.
    assert len(EVENTS) == 108


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "css"
    assert event.id == make_id("hackclub", event.url)
    assert event.source == "hackclub"


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    for event in EVENTS:
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


def test_online_card_maps_name_dates_and_mode():
    event = BY_URL["https://www.bananahacks.tech"]
    assert event.name == "Banana Hacks"
    assert event.mode == "online"  # "Online" badge
    assert event.location is None  # online cards carry no address
    assert (event.start, event.end) == (date(2026, 10, 9), date(2026, 10, 12))
    assert event.status == "open"


def test_in_person_card_maps_location_and_single_day_dates():
    event = BY_URL["https://www.hyphen-hacks.com/"]
    assert event.name == "Hyphen-Hacks"
    assert event.mode == "offline"  # "In-Person" badge
    assert event.location == "San Francisco, California"  # raw, ":" stripped
    assert (event.start, event.end) == (date(2026, 10, 10), date(2026, 10, 10))
    assert event.status == "upcoming"


def test_cross_year_card_keeps_its_iso_end_year():
    event = BY_URL["https://earth.firstcommit.xyz"]
    assert event.name == "Build for Earth"
    assert (event.start, event.end) == (date(2026, 11, 8), date(2027, 1, 16))
    assert event.status == "upcoming"


def test_card_that_ends_today_is_open_not_closed():
    event = BY_URL["https://capitol.hackclub.com/"]
    assert (event.start, event.end) == (date(2026, 9, 1), date(2026, 10, 9))
    assert event.status == "open"


def test_hybrid_card_maps_to_hybrid_mode():
    event = BY_URL["https://www.hacktheskies.com/"]
    assert event.name == "Hack the Skies"
    assert event.mode == "hybrid"
    assert event.location == "Canada"
    assert event.status == "closed"  # November 2025


def test_cards_without_an_address_keep_location_none():
    # ":"-only addresses (the page's empty separator) and online cards
    # both stay None; location is never fabricated from the mode.
    assert BY_URL["https://www.thebrilliantmove.com/"].location is None  # hybrid
    assert BY_URL["https://outpost.hackclub.com"].location is None  # in-person


def test_duplicate_url_editions_keep_only_the_newest_first_occurrence():
    names = {event.name for event in EVENTS}
    assert "MathHacks 2.0" in names and "MathHacks" not in names
    assert "Pixel Forge Mega Jam" in names
    assert "Pixel Forge Jam #2 [Haunted Edition]" not in names
    assert "Pixel Forge Jam 2026" not in names
    assert "Grizzly Hacks II" in names and "Grizzly Hacks Fall 2025" not in names
    assert "RePlay Alexandria: Shipaton Edition" in names
    assert "RePlay Alexandria" not in names
    assert "CipherHacks 2026" in names and "CipherHacks" not in names
    assert "Girls Got Game Jam" in names and "Girls Got Game Jam 2" not in names
    assert "Oink Game Jam 2" in names and "Oink Game Jam" not in names


def test_dreamventure_keeps_the_newer_may_edition():
    kept = [event for event in EVENTS if event.name == "DreamVenture"]
    assert len(kept) == 1
    assert kept[0].start == date(2026, 5, 23)


def test_ids_are_unique_after_url_dedupe():
    assert len({event.id for event in EVENTS}) == 108


def test_http_only_links_are_skipped_by_the_https_identity_rule():
    # These 3 cards link to http-only sites; the shared https identity
    # rule skips them (reported in the task report as an honest skip).
    names = {event.name for event in EVENTS}
    assert "Blu's Hacks 2026" not in names
    assert "Winter MelonJam 2025" not in names
    assert "Bug Bash" not in names


def test_status_split_matches_the_dates_vs_context_now():
    assert sum(e.status == "closed" for e in EVENTS) == 91
    assert sum(e.status == "upcoming" for e in EVENTS) == 15
    assert sum(e.status == "open" for e in EVENTS) == 2


def test_mode_split_matches_the_pages_own_badges():
    assert sum(e.mode == "offline" for e in EVENTS) == 84
    assert sum(e.mode == "online" for e in EVENTS) == 22
    assert sum(e.mode == "hybrid" for e in EVENTS) == 2


def test_fields_absent_from_the_cards_stay_none_or_empty():
    for event in EVENTS:
        assert event.reg_deadline is None
        assert event.team_min is None and event.team_max is None
        assert event.solo_ok is None
        assert event.prize is None
        assert event.themes == []
        assert event.eligibility is None
        assert event.cost is None
        assert event.also_on == []


# --- synthetic edge cases (branches the captured fixture does not cover) ----


def test_future_ongoing_and_past_cards_derive_status_from_their_dates():
    page = _page(
        _card("Future", "https://f.example/", "2026-10-30T09:00:00.000Z", "2026-10-31T17:00:00.000Z"),
        _card("Ongoing", "https://o.example/", "2026-10-08T09:00:00.000Z", "2026-10-12T17:00:00.000Z"),
        _card("Past", "https://p.example/", "2026-08-01T09:00:00.000Z", "2026-08-02T17:00:00.000Z"),
    )
    assert [e.status for e in _parse(page)] == ["upcoming", "open", "closed"]


def test_unknown_or_missing_badge_is_skipped_not_guessed():
    assert _parse(_page(_card(badge="Maybe"))) == []
    assert _parse(_page(_card(badge=""))) == []


def test_cards_without_dates_are_skipped_not_guessed():
    assert _parse(_page(_card(with_dates=False))) == []


def test_inverted_iso_range_is_skipped_not_guessed():
    page = _page(
        _card(start="2026-10-31T09:00:00.000Z", end="2026-10-30T09:00:00.000Z")
    )
    assert _parse(page) == []


def test_cards_without_name_or_usable_href_are_skipped():
    assert _parse(_page(_card(name=""))) == []
    assert _parse(_page(_card(href=""))) == []
    assert _parse(_page(_card(href="#"))) == []
    assert _parse(_page(_card(href="javascript:alert(1)"))) == []


def test_relative_href_is_resolved_against_the_site_base():
    (event,) = _parse(_page(_card(href="/events/local")))
    assert event.url == "https://hackathons.hackclub.com/events/local"


def test_address_separator_is_stripped_and_empty_addresses_stay_none():
    (event,) = _parse(_page(_card(location="Berlin, Germany")))
    assert event.location == "Berlin, Germany"
    (event,) = _parse(_page(_card(location="")))
    assert event.location is None


def test_duplicate_urls_keep_the_first_card_only():
    page = _page(_card("First", "https://dup.example/"), _card("Second", "https://dup.example/"))
    (event,) = _parse(page)
    assert event.name == "First"


def test_non_string_payload_yields_no_events_instead_of_crashing():
    assert HackclubAdapter().parse(None, _ctx()) == []


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
    result = HackclubAdapter().fetch(_ctx(crawl=fake))
    assert result is HTML
    assert fake.calls == [LISTING_URL]


def test_listing_url_is_the_hackclub_listing():
    assert LISTING_URL == "https://hackathons.hackclub.com/"


# --- registry, sources.yaml -------------------------------------------------


def test_registry_exposes_the_hackclub_adapter():
    adapter = ADAPTERS["hackclub"]
    assert isinstance(adapter, HackclubAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "hackclub"
    assert adapter.kind == "browser"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_hackclub_as_browser_kind():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    entry = next(e for e in entries if e["id"] == "hackclub")
    assert entry["kind"] == "browser"
    assert entry["enabled"] is True
    assert entry["url"] == LISTING_URL
    assert isinstance(entry["notes"], str) and entry["notes"].strip()
