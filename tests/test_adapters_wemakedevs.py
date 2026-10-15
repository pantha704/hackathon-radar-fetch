"""Tests for the wemakedevs.org adapter (Task 10, browser kind).

Fixture-driven: `tests/fixtures/wemakedevs/listing.html` is a real captured
render of https://wemakedevs.org/ (M0, 2026-10-09). No test here touches the
network.

The homepage's "Explore Upcoming Hackathons" carousel carries 3 hackathon
cards; the "Find a Local Meetup" carousel carries 1 meetup card that is
skipped as a non-hackathon. The card date chips are yearless ("Oct 8–11");
the year is read from the page's embedded RSC payload (the DOM genuinely
lacks it) — see the adapter docstring.
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.wemakedevs import LISTING_URL, WemakedevsAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "wemakedevs" / "listing.html"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
HTML = FIXTURE.read_text(encoding="utf-8")

BASE = "https://wemakedevs.org"
ENV_URL = f"{BASE}/aws/env"
FALKORDB_URL = f"{BASE}/hackathons/falkordb"
MERGETOBER_URL = f"{BASE}/hackathons/mergetober"


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(html=HTML, **ctx_overrides):
    """Run the wemakedevs parser on a payload (pure: payload + ctx only)."""
    return WemakedevsAdapter().parse(html, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}


def _card(href, name, location, date_text, *, prize=None, badge=None):
    """Build a synthetic card with the fixture's exact class vocabulary."""
    badge_html = ""
    if badge is not None:
        badge_html = (
            '<div class="flex items-center gap-1.5 border border-border bg-background/80 '
            'px-2 py-1 font-mono text-xs uppercase tracking-wider text-foreground '
            'backdrop-blur-sm absolute bottom-2 left-2 z-10">'
            f'<span class="translate-y-[1px]">{badge}</span></div>'
        )
    prize_html = f'<p class="mt-2 text-muted-foreground">{prize}</p>' if prize else ""
    return (
        f'<a class="block border border-border p-4 h-fit relative group" href="{href}">'
        f'<div class="overflow-clip relative aspect-[3/2]">{badge_html}</div>'
        '<div class="mt-4">'
        '<div class="flex gap-2 items-center text-sm text-muted-foreground '
        'border-b border-border pb-4">'
        '<div class="flex items-center px-2.5 py-1.5 border border-border gap-2">'
        '<svg class="lucide lucide-map-pin"></svg>'
        f'<span class="translate-y-[1px]">{location}</span></div>'
        '<div class="flex items-center px-2.5 py-1.5 border border-border gap-2">'
        '<svg class="lucide lucide-calendar-range"></svg>'
        f'<span class="translate-y-[1px]">{date_text}</span></div>'
        "</div>"
        f'<h3 class="text-[26px] font-semibold text-foreground mt-3 leading-[125%]">{name}</h3>'
        f"{prize_html}"
        "</div></a>"
    )


def _section(heading, cards):
    """A carousel section with the fixture's class vocabulary."""
    return (
        '<section class="relative scroll-mt-20"><div class="box-border">'
        f'<h2 class="mt-6 text-4xl font-medium tracking-tight">{heading}</h2>'
        '<div class="mt-16"><div class="relative">'
        '<div class="flex overflow-x-auto snap-x gap-6 pb-1 items-stretch">'
        + "".join(cards)
        + "</div></div></div></div></section>"
    )


def _page(sections, *, rsc_years=None):
    """Wrap sections in a page shell; optionally embed an RSC year payload.

    ``rsc_years`` maps raw card href -> start-date year and is embedded the
    way the live page does it (a ``self.__next_f.push`` fragment).
    """
    rsc = ""
    if rsc_years:
        payload = ",".join(
            f'{{"href":"{href}","isExternal":false,"startDate":"{year}-10-08T02:30:00Z"}}'
            for href, year in rsc_years.items()
        )
        rsc = f"<script>self.__next_f.push([1,{json.dumps(payload)}])</script>"
    return "<!doctype html><html><body>" + rsc + "".join(sections) + "</body></html>"


def _hackathon_page(cards, **kwargs):
    """The page's hackathon carousel with the given cards."""
    return _page([_section("Explore Upcoming Hackathons", cards)], **kwargs)


# --- fixture sanity ---------------------------------------------------------


def test_fixture_is_a_real_captured_wemakedevs_homepage():
    assert FIXTURE.is_file()
    assert "Explore Upcoming Hackathons" in HTML
    assert "Find a Local Meetup" in HTML
    # 3 hackathon cards + 1 meetup card carry the card anchor classes.
    assert HTML.count('class="block border border-border p-4 h-fit relative group"') == 4
    # The RSC payload carries a startDate for each of the 4 cards.
    assert HTML.count('\\"startDate\\"') == 4


# --- parse contract ---------------------------------------------------------


def test_parse_produces_at_least_three_events_with_name_and_url():
    assert len(EVENTS) >= 3
    for event in EVENTS:
        assert isinstance(event.name, str) and event.name.strip()
        assert event.url.startswith("https://")


def test_parse_extracts_the_three_hackathon_cards():
    assert len(EVENTS) == 3


def test_meetup_card_is_skipped_as_a_non_hackathon():
    # The page carries 4 cards total; the 4th ("Agentic AI in the Wild")
    # lives in the "Find a Local Meetup" carousel and is never parsed.
    assert len(EVENTS) == 3
    assert all(event.name != "Agentic AI in the Wild" for event in EVENTS)
    assert all("luma.com" not in event.url for event in EVENTS)


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "css"
    assert event.id == make_id("wemakedevs", event.url)


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    for event in EVENTS:
        assert event.source == "wemakedevs"
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


def test_urls_are_resolved_against_the_site_and_unique():
    for event in EVENTS:
        assert event.url.startswith(f"{BASE}/")
    assert len({event.id for event in EVENTS}) == 3


def test_hybrid_live_card_maps_name_mode_location_prize_and_dates():
    event = BY_URL[ENV_URL]
    assert event.name == "Environmental Hacks"
    assert event.mode == "hybrid"  # "Hybrid" location chip
    assert event.location == "Hybrid"
    assert event.prize == "₹20 Lakh in prizes and Fast Track to Amazon Job Interviews"
    assert (event.start, event.end) == (date(2026, 10, 8), date(2026, 10, 11))
    assert event.status == "open"  # "Live" badge


def test_remote_card_without_badge_derives_upcoming_from_its_dates():
    event = BY_URL[FALKORDB_URL]
    assert event.name == "Graph Hacks: Building Next-Gen RAG"
    assert event.mode == "online"  # "Remote" chip
    assert event.location == "Remote"
    assert event.prize == "$20,000 across three tracks"
    assert (event.start, event.end) == (date(2026, 10, 14), date(2026, 10, 18))
    assert event.status == "upcoming"  # no badge; start is after ctx["now"]


def test_live_cross_month_card_keeps_its_range():
    event = BY_URL[MERGETOBER_URL]
    assert event.name == "Mergetober: Open Source Month"
    assert event.mode == "online"
    assert event.location == "Remote"
    assert event.prize == "$5,000 in prizes for contributing to Cognee"
    assert (event.start, event.end) == (date(2026, 9, 30), date(2026, 10, 31))
    assert event.status == "open"  # "Live" badge


def test_status_split_matches_badges_and_dates():
    assert sum(e.status == "open" for e in EVENTS) == 2  # both "Live" cards
    assert sum(e.status == "upcoming" for e in EVENTS) == 1  # derived from dates
    assert sum(e.status == "closed" for e in EVENTS) == 0


def test_year_is_read_from_the_rsc_payload_because_the_dom_lacks_it():
    # The card date chips are yearless ("Oct 8–11"); parsed dates carry 2026.
    assert "Oct 8–11" in HTML
    assert BY_URL[ENV_URL].start == date(2026, 10, 8)
    assert BY_URL[FALKORDB_URL].start == date(2026, 10, 14)


def test_fields_absent_from_the_cards_stay_none_or_empty():
    for event in EVENTS:
        assert event.reg_deadline is None
        assert event.team_min is None and event.team_max is None
        assert event.solo_ok is None
        assert event.themes == []
        assert event.eligibility is None
        assert event.cost is None
        assert event.also_on == []


# --- synthetic edge cases (branches the captured fixture does not cover) ----


def test_live_badge_wins_over_dates():
    card = _card("/x", "Live Future", "Remote", "Oct 30 – 31", badge="Live")
    (event,) = _parse(_hackathon_page([card], rsc_years={"/x": 2026}))
    assert event.status == "open"
    assert (event.start, event.end) == (date(2026, 10, 30), date(2026, 10, 31))


def test_cards_without_badge_derive_status_from_their_dates():
    cards = [
        _card("/future", "Future", "Remote", "Oct 30 – 31"),
        _card("/ongoing", "Ongoing", "Remote", "Oct 8–12"),
        _card("/past", "Past", "Remote", "Aug 1–2"),
    ]
    events = _parse(
        _hackathon_page(
            cards, rsc_years={"/future": 2026, "/ongoing": 2026, "/past": 2026}
        )
    )
    assert [e.status for e in events] == ["upcoming", "open", "closed"]


def test_card_without_a_resolvable_year_keeps_dates_none_and_defaults_status():
    card = _card("/no-year", "No Year", "Remote", "Oct 30 – 31")
    (event,) = _parse(_hackathon_page([card]))  # no RSC payload at all
    assert (event.start, event.end) == (None, None)
    assert event.status == "upcoming"  # flagged default; see the docstring


def test_cross_year_range_wraps_into_the_next_year():
    card = _card("/wrap", "Wrap", "Remote", "Dec 30 – Jan 2")
    (event,) = _parse(_hackathon_page([card], rsc_years={"/wrap": 2026}))
    assert (event.start, event.end) == (date(2026, 12, 30), date(2027, 1, 2))


def test_same_month_inversion_keeps_dates_none_not_guessed():
    card = _card("/inv", "Inverted", "Remote", "Jun 30 – Jun 5")
    (event,) = _parse(_hackathon_page([card], rsc_years={"/inv": 2026}))
    assert (event.start, event.end) == (None, None)
    assert event.status == "upcoming"  # no badge -> flagged default


def test_unknown_location_text_maps_to_offline_and_stays_raw():
    card = _card("/mars", "Mars Base Jam", "Mars Base", "Oct 30 – 31", badge="Live")
    (event,) = _parse(_hackathon_page([card], rsc_years={"/mars": 2026}))
    assert event.mode == "offline"
    assert event.location == "Mars Base"


def test_card_without_location_has_no_mode_signal_and_is_skipped():
    card = _card("/noloc", "No Location", "", "Oct 30 – 31")
    assert _parse(_hackathon_page([card], rsc_years={"/noloc": 2026})) == []


def test_cards_without_name_or_usable_href_are_skipped():
    assert _parse(_hackathon_page([_card("/x", "", "Remote", "Oct 30 – 31")])) == []
    assert _parse(_hackathon_page([_card("", "Empty Href", "Remote", "Oct 30 – 31")])) == []
    assert _parse(_hackathon_page([_card("#", "Fragment", "Remote", "Oct 30 – 31")])) == []
    assert (
        _parse(_hackathon_page([_card("javascript:alert(1)", "Evil", "Remote", "Oct 30 – 31")]))
        == []
    )


def test_meetup_section_cards_are_never_parsed():
    meetup = _card("https://luma.com/x", "Agentic AI", "New York, US", "Oct 22")
    assert _parse(_page([_section("Find a Local Meetup", [meetup])])) == []


def test_page_without_the_hackathon_heading_yields_nothing():
    card = _card("/x", "No Section", "Remote", "Oct 30 – 31")
    assert _parse(_page([card])) == []  # card outside any section
    assert _parse("<!doctype html><html><body></body></html>") == []


def test_non_string_payload_yields_no_events_instead_of_crashing():
    assert WemakedevsAdapter().parse(None, _ctx()) == []


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
    result = WemakedevsAdapter().fetch(_ctx(crawl=fake))
    assert result is HTML
    assert fake.calls == [LISTING_URL]


def test_listing_url_is_the_homepage():
    assert LISTING_URL == "https://wemakedevs.org/"


# --- registry, sources.yaml -------------------------------------------------


def test_registry_exposes_the_wemakedevs_adapter():
    adapter = ADAPTERS["wemakedevs"]
    assert isinstance(adapter, WemakedevsAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "wemakedevs"
    assert adapter.kind == "browser"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_wemakedevs_as_browser_kind():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    entry = next(e for e in entries if e["id"] == "wemakedevs")
    assert entry["kind"] == "browser"
    assert entry["enabled"] is True
    assert entry["url"] == LISTING_URL
    assert isinstance(entry["notes"], str) and entry["notes"].strip()
