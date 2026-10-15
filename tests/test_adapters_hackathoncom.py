"""Tests for the hackathon.com adapter (Task 10, browser kind).

Fixture-driven: `tests/fixtures/hackathoncom/listing.html` is a real captured
render of https://www.hackathon.com/ (M0, 2026-10-09). No test here touches
the network.

The homepage highlights carousel carries exactly 4 featured events. Their
hero date lines are yearless ("Starts 02 Nov Ends 02 Dec"); the start-date
years live in the highlights nav row ("2nd November 2026"), which is the
documented year source for this adapter (see the module docstring).
"""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.hackathoncom import LISTING_URL, HackathoncomAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "hackathoncom" / "listing.html"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
HTML = FIXTURE.read_text(encoding="utf-8")

BASE = "https://www.hackathon.com"
AI_BUILDERS_URL = f"{BASE}/event/ai-builders-challenge---north-america-6abbf8d772b8a910818d2070"
IBM_Z_URL = f"{BASE}/event/ibm-z-day-2026-6a90a131d4372f7cdf912da6"
XYLEM_URL = f"{BASE}/event/xylem-global-student-innovation-challenge-2026-6aa862e261509030e7e6436f"
HUAWEI_URL = f"{BASE}/event/huawei-ireland-tech-arena-2026-6ac54367612836bf413df387"


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(html=HTML, **ctx_overrides):
    """Run the hackathon.com parser on a payload (pure: payload + ctx only)."""
    return HackathoncomAdapter().parse(html, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}


def _hero(name, href, date_text, location, *, anchor=True):
    """Build a synthetic hero card with the fixture's exact class vocabulary."""
    if anchor:
        title = f'<a class="hero__title roboto-300" href="{href}">{name}</a>'
    else:
        title = f'<span class="hero__title roboto-300">{name}</span>'
    return (
        '<div class="hero">'
        '<div class="hero__left">'
        '<a class="hero__more-link" href="/event/more">More details</a>'
        "</div>"
        '<div class="hero__right">'
        '<div class="hero__top-line">'
        '<a class="hero__arrow-link" href="/event/more">More details</a>'
        "</div>"
        f"{title}"
        '<ul class="ht-event-topics"></ul>'
        '<div class="hero__key-info">'
        f'<div class="hero__key-info__location">{location}</div>'
        f'<div class="hero__key-info__date">{date_text}</div>'
        "</div>"
        "</div>"
        "</div>"
    )


def _highlight(name, date_text):
    """Build a highlights-nav entry (the fixture's year-bearing date row)."""
    return (
        '<button class="ht-highlights__item">'
        f'<span class="ht-highlights__item__name">{name}</span>'
        f'<span class="ht-highlights__item__date">{date_text}</span>'
        "</button>"
    )


def _page(heroes, highlights):
    """Wrap hero cards + highlights entries in a minimal highlights shell."""
    return (
        "<!doctype html><html><body>"
        '<section class="ht-highlights">'
        '<div class="ht-highlights__hero container">' + "".join(heroes) + "</div>"
        '<div class="ht-highlights__list container">' + "".join(highlights) + "</div>"
        "</section></body></html>"
    )


def _hero_page(
    name="Test Hack",
    href="https://test.example/",
    date_text="Starts 30 Oct Ends 31 Oct",
    location="Online",
    *,
    highlight: str | None = "30th October 2026",
    highlight_name: str | None = None,
    anchor=True,
):
    """One hero + its matching highlights-nav entry (the fixture's shape)."""
    highlights = []
    if highlight is not None:
        highlights.append(
            _highlight(name if highlight_name is None else highlight_name, highlight)
        )
    return _page([_hero(name, href, date_text, location, anchor=anchor)], highlights)


# --- fixture sanity ---------------------------------------------------------


def test_fixture_is_a_real_captured_hackathoncom_homepage():
    assert FIXTURE.is_file()
    assert "Organize Hackathons Worldwide" in HTML
    # 4 featured heroes + the 4 matching highlights-nav entries.
    assert HTML.count('class="hero"') + HTML.count('class="hero active"') == 4
    assert HTML.count("ht-highlights__item__name") == 4


# --- parse contract ---------------------------------------------------------


def test_parse_produces_at_least_three_events_with_name_and_url():
    assert len(EVENTS) >= 3
    for event in EVENTS:
        assert isinstance(event.name, str) and event.name.strip()
        assert event.url.startswith("https://")


def test_parse_extracts_every_featured_hero_in_the_fixture():
    assert len(EVENTS) == 4


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "css"
    assert event.id == make_id("hackathoncom", event.url)


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    for event in EVENTS:
        assert event.source == "hackathoncom"
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


def test_all_urls_are_resolved_event_pages_with_unique_ids():
    for event in EVENTS:
        assert event.url.startswith(f"{BASE}/event/")
        assert "?" not in event.url  # no tracking params on the hero hrefs
    assert len({event.id for event in EVENTS}) == 4


def test_online_hero_maps_name_dates_location_and_topics():
    event = BY_URL[AI_BUILDERS_URL]
    assert event.name == "AI Builders Challenge - North America"
    assert event.mode == "online"  # "Online" location line
    assert event.location == "Online"
    assert (event.start, event.end) == (date(2026, 11, 2), date(2026, 12, 2))
    assert event.status == "upcoming"
    assert event.themes == ["University", "Beginner friendly", "AI", "Student"]


def test_single_day_hero_collapses_start_and_end():
    event = BY_URL[IBM_Z_URL]
    assert event.name == "IBM Z Day 2026"
    assert (event.start, event.end) == (date(2026, 11, 18), date(2026, 11, 18))
    assert event.status == "upcoming"


def test_ongoing_hero_is_open():
    event = BY_URL[XYLEM_URL]
    assert (event.start, event.end) == (date(2026, 9, 28), date(2026, 11, 20))
    assert event.status == "open"
    assert event.themes == ["Student", "High School", "University", "Virtual"]


def test_future_hero_keeps_its_topics_in_card_order():
    event = BY_URL[HUAWEI_URL]
    assert (event.start, event.end) == (date(2026, 10, 14), date(2026, 11, 15))
    assert event.status == "upcoming"
    assert event.themes == ["AI", "University", "Student", "Hybrid"]


def test_status_split_matches_the_pages_own_dates():
    # No status badge exists on the heroes; status derives from the dates
    # vs ctx["now"] (2026-10-09): Xylem started but has not ended -> open.
    assert sum(e.status == "open" for e in EVENTS) == 1
    assert sum(e.status == "upcoming" for e in EVENTS) == 3
    assert sum(e.status == "closed" for e in EVENTS) == 0


def test_fields_absent_from_the_heroes_stay_none_or_empty():
    for event in EVENTS:
        assert event.reg_deadline is None
        assert event.team_min is None and event.team_max is None
        assert event.solo_ok is None
        assert event.prize is None
        assert event.eligibility is None
        assert event.cost is None
        assert event.also_on == []


# --- synthetic edge cases (branches the captured fixture does not cover) ----


def test_future_ongoing_and_past_heroes_map_to_upcoming_open_closed():
    page = _page(
        [
            _hero("Future", "https://f.example/", "Starts 30 Oct Ends 31 Oct", "Online"),
            _hero("Ongoing", "https://o.example/", "Starts 08 Oct Ends 12 Oct", "Online"),
            _hero("Past", "https://p.example/", "Starts 01 Aug Ends 02 Aug", "Online"),
        ],
        [
            _highlight("Future", "30th October 2026"),
            _highlight("Ongoing", "8th October 2026"),
            _highlight("Past", "1st August 2026"),
        ],
    )
    assert [e.status for e in _parse(page)] == ["upcoming", "open", "closed"]


def test_cross_month_range_wraps_into_the_next_year():
    events = _parse(
        _hero_page(date_text="Starts 30 Dec Ends 02 Jan", highlight="30th December 2026")
    )
    (event,) = events
    assert (event.start, event.end) == (date(2026, 12, 30), date(2027, 1, 2))


def test_same_month_inversion_is_skipped_not_guessed():
    assert (
        _parse(_hero_page(date_text="Starts 30 Jun Ends 05 Jun", highlight="30th June 2026"))
        == []
    )


def test_start_only_line_collapses_start_and_end():
    events = _parse(_hero_page(date_text="Starts 09 Oct", highlight="9th October 2026"))
    (event,) = events
    assert (event.start, event.end) == (date(2026, 10, 9), date(2026, 10, 9))
    assert event.status == "open"


def test_year_comes_from_the_highlights_nav_not_a_constant():
    events = _parse(_hero_page(highlight="30th October 2027"))
    (event,) = events
    assert event.start == date(2027, 10, 30)


def test_hero_without_a_matching_highlight_is_skipped_not_guessed():
    assert _parse(_hero_page(highlight=None)) == []
    assert _parse(_hero_page(highlight_name="Some Other Event")) == []


def test_heroes_without_name_or_anchor_are_skipped_not_faked():
    assert _parse(_hero_page(name="")) == []
    assert _parse(_hero_page(anchor=False)) == []


def test_hero_without_a_location_has_no_mode_signal_and_is_skipped():
    assert _parse(_hero_page(location="")) == []


def test_physical_location_maps_to_offline_and_is_kept_raw():
    (event,) = _parse(_hero_page(location="Paris, France"))
    assert event.mode == "offline"
    assert event.location == "Paris, France"


def test_unusable_hrefs_are_skipped():
    assert _parse(_hero_page(href="")) == []
    assert _parse(_hero_page(href="#")) == []
    assert _parse(_hero_page(href="javascript:alert(1)")) == []


def test_non_string_payload_yields_no_events_instead_of_crashing():
    assert HackathoncomAdapter().parse(None, _ctx()) == []


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
    result = HackathoncomAdapter().fetch(_ctx(crawl=fake))
    assert result is HTML
    assert fake.calls == [LISTING_URL]


def test_listing_url_is_the_homepage():
    assert LISTING_URL == "https://www.hackathon.com/"


# --- registry, sources.yaml -------------------------------------------------


def test_registry_exposes_the_hackathoncom_adapter():
    adapter = ADAPTERS["hackathoncom"]
    assert isinstance(adapter, HackathoncomAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "hackathoncom"
    assert adapter.kind == "browser"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_hackathoncom_as_browser_kind():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    entry = next(e for e in entries if e["id"] == "hackathoncom")
    assert entry["kind"] == "browser"
    assert entry["enabled"] is True
    assert entry["url"] == LISTING_URL
    assert isinstance(entry["notes"], str) and entry["notes"].strip()
