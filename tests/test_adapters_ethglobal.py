"""Tests for the ETHGlobal events adapter (Task 9, browser kind).

Fixture-driven: `tests/fixtures/ethglobal/listing.html` is a real captured
render of https://ethglobal.com/events (M0, 2026-10-09; "upcoming + past
mixed", per the M0 spike). No test here touches the network.

The page has two regions, both parsed by the adapter:

- the "Upcoming" carousel (the grid after the ``Upcoming`` heading) — kept only
  for hackathon-type cards (``IRL Hackathon`` pill); every other pill
  (``Conference`` / ``Co-Working``) is skipped as a non-hackathon;
- the "Past" table (333 rows) — kept only for the page's own hackathon event
  types (``Hackathon`` / ``Online``); Meetup / Co-working / Conference / Summit
  rows are skipped. The table is the source of the exact field pins below.

The ``Featured`` carousel is deliberately not parsed (promo rotation; its two
cards duplicate ``Upcoming`` entries in this capture).
"""

from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import pytest
import yaml
from bs4 import BeautifulSoup

from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.ethglobal import LISTING_URL, EthglobalAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "ethglobal" / "listing.html"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
HTML = FIXTURE.read_text(encoding="utf-8")

BASE = "https://ethglobal.com"

MUMBAI_URL = f"{BASE}/events/mumbai"
TOKYO_URL = f"{BASE}/events/tokyo2026"
ETHONLINE_URL = f"{BASE}/events/ethonline2026"
ETHINDIA_URL = "https://ethindia.co"

_SOUP = BeautifulSoup(HTML, "html.parser")
TABLE_ROWS = _SOUP.select('a[class*="hover:bg-black-100"]')
TABLE_URLS = {urljoin(BASE, row["href"].strip()) for row in TABLE_ROWS}


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(html=HTML, **ctx_overrides):
    """Run the ETHGlobal parser on a payload (pure: payload + ctx only)."""
    return EthglobalAdapter().parse(html, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}


def _row(name, href, date_text, *, city="", country="", badge="Hackathon", wrap_anchor=True):
    """Build a synthetic past-table row with the fixture's class vocabulary."""
    inner = (
        '<div class="flex-12 flex items-center gap-2">'
        '<img alt="logo" class="w-14 h-14 min-w-14 min-h-14 object-cover border-2 border-2-black rounded-full" src="https://cdn.example/l.png"/>'
        '<div class="flex-1 flex flex-col gap-1">'
        f'<h3 class="font-semibold">{name}</h3>'
        '<p class="text-sm font-medium text-black-400"></p>'
        f'<p class="flex-4 md:hidden text-sm"><time class="text-nowrap">{date_text}</time></p>'
        "</div></div>"
        f'<p class="hidden md:block flex-4 text-sm"><time class="text-nowrap">{date_text}</time></p>'
        '<div class="flex-4 hidden md:flex flex-col">'
        f'<p class="text-sm">{city}</p><p class="text-sm text-black-400">{country}</p></div>'
        '<div class="flex-4 flex justify-between gap-2">'
        '<div class="inline-flex overflow font-semibold items-center space-x-2 uppercase '
        f'py-1 bg-blue-300 text-xs border-black px-3 border-2 rounded-sm">{badge}</div>'
        "</div>"
    )
    if wrap_anchor:
        inner = (
            '<a class="cursor-pointer flex gap-4 p-4 items-center hover:bg-black-100 '
            f'transition-colors duration-200" href="{href}">{inner}</a>'
        )
    return inner


def _hero(name, href, month, days, weekdays, location, pill, *, wrap_anchor=True):
    """Build a synthetic upcoming-carousel hero with the fixture's structure."""
    day_spans = "".join(
        f'<span class="">{day}</span>'
        + ('<span class="px-1 self-center">&rarr;</span>' if i < len(days) - 1 else "")
        for i, day in enumerate(days)
    )
    inner = (
        '<section class="relative w-full h-full overflow-hidden rounded-[0.75rem] text-white font-jakarta">'
        '<div class="flex space-x-4 bg-white text-black w-fit px-4 py-2 rounded-b-lg">'
        '<div class="text-center">'
        f'<div class="uppercase text-xs font-semibold tracking-wider">{month}</div>'
        f'<div class="text-2xl md:text-3xl font-extrabold leading-none flex justify-center">{day_spans}</div>'
        f'<div class="text-xxs tracking-wider -mt-0 lg:-mt-1 justify-center">{weekdays}</div>'
        "</div></div>"
        f'<div class="mt-6"><h2 class="text-2xl md:text-4xl font-bold mb-4">{name}</h2>'
        '<div class="flex flex-wrap gap-2 mb-5 lg:mb-8 flex-col lg:flex-row">'
        '<span class="inline-flex items-center pl-2 pr-3 py-1 rounded-full bg-white/25 '
        f'text-xs lg:text-sm font-semibold backdrop-blur-md w-fit">{location}</span>'
        '<span class="inline-flex items-center pl-2 pr-3 py-1 rounded-full bg-[#ACDFF6]/35 '
        f'border border-[#ACDFF6]/35 text-xs lg:text-sm font-medium backdrop-blur-md w-fit">{pill}</span>'
        "</div></div></section>"
    )
    if wrap_anchor:
        inner = f'<a class="block lg:col-span-2" href="{href}">{inner}</a>'
    return inner


def _page(*fragments):
    """Wrap hero fragments in the Upcoming heading + grid shell."""
    return (
        "<!doctype html><html><body>"
        f'<h2 class="text-2xl lg:text-4xl">Upcoming <span class="ml-1">{len(fragments)}</span></h2>'
        '<div class="grid gap-8 lg:grid-cols-2">' + "".join(fragments) + "</div>"
        "</body></html>"
    )


# --- fixture sanity ---------------------------------------------------------


def test_fixture_is_a_real_captured_ethglobal_events_page():
    assert FIXTURE.is_file()
    assert "ETHGlobal" in HTML
    assert len(TABLE_ROWS) == 333
    assert "Upcoming" in HTML


def test_table_event_type_badge_split_is_pinned():
    # The page's own "Event Type" vocabulary across all 333 past rows.
    badges = Counter(
        div.get_text(" ", strip=True)
        for row in TABLE_ROWS
        for div in row.find_all("div")
        if "uppercase" in " ".join(div.get("class") or [])
        and "px-3" in " ".join(div.get("class") or [])
    )
    assert badges == Counter(
        {
            "Meetup": 168,
            "Co-working": 56,
            "Online": 43,
            "Hackathon": 38,
            "Conference": 24,
            "Summit": 4,
        }
    )


# --- parse contract ---------------------------------------------------------


def test_parse_produces_at_least_three_events_with_name_and_url():
    assert len(EVENTS) >= 3
    for event in EVENTS:
        assert isinstance(event.name, str) and event.name.strip()
        assert event.url.startswith("https://")


def test_parse_extracts_the_hackathon_type_table_rows_and_the_upcoming_hero():
    # 38 "Hackathon" + 43 "Online" rows = 81 rows, minus the 2 rows whose URL
    # duplicates another row (ETHIndia 2022 / ETHWaterloo 2017 share their
    # landing page with the 2023/2019 editions and collapse under the
    # (source, url) id model), plus the 1 upcoming hackathon hero = 80.
    assert len(EVENTS) == 80


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "css"
    assert event.id == make_id("ethglobal", event.url)


def test_ids_and_urls_are_unique():
    assert len({event.id for event in EVENTS}) == len(EVENTS)
    assert len({event.url for event in EVENTS}) == len(EVENTS)


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    for event in EVENTS:
        assert event.source == "ethglobal"
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


# --- fixture field mapping: the upcoming carousel ---------------------------


def test_upcoming_hero_is_first_and_maps_dates_derived_from_its_own_weekday():
    # The hero date box shows month + day range + weekday range but no year;
    # the weekday pins the year uniquely within [now.year, now.year+1].
    event = EVENTS[0]
    assert event.url == MUMBAI_URL
    assert event.name == "ETHGlobal Mumbai"
    assert event.mode == "offline"  # "IRL Hackathon" pill
    assert event.status == "upcoming"  # the page's own "Upcoming" section
    assert event.location == "Mumbai, India"
    assert (event.start, event.end) == (date(2026, 11, 5), date(2026, 11, 7))


# --- fixture field mapping: the past table ----------------------------------


def test_offline_hackathon_row_maps_name_dates_location_and_mode():
    event = BY_URL[TOKYO_URL]
    assert event.name == "ETHGlobal Tokyo 2026"
    assert event.mode == "offline"  # "Hackathon" event type
    assert event.status == "closed"  # ended before ctx["now"]
    assert event.location == "Tokyo, Japan"
    assert (event.start, event.end) == (date(2026, 9, 25), date(2026, 9, 27))


def test_online_hackathon_row_maps_to_online_with_no_location():
    event = BY_URL[ETHONLINE_URL]
    assert event.name == "ETHOnline 2026"
    assert event.mode == "online"  # "Online" event type
    assert event.status == "closed"
    assert event.location is None  # the row's location cells are empty
    assert (event.start, event.end) == (date(2026, 9, 4), date(2026, 9, 16))


def test_external_row_url_is_kept_and_dates_use_the_shown_year():
    event = BY_URL[ETHINDIA_URL]
    assert event.name == "ETHIndia 2023"
    assert event.mode == "offline"
    assert event.status == "closed"
    assert event.location == "Bengaluru, India"
    assert (event.start, event.end) == (date(2023, 12, 8), date(2023, 12, 10))


def test_mode_and_status_splits_match_the_pages_own_labels_and_dates():
    # 43 "Online" rows -> online; 36 unique "Hackathon" rows + 1 hero -> offline.
    # Every table row ended before 2026-10-09 -> closed; the hero is upcoming.
    assert Counter(e.mode for e in EVENTS) == Counter({"online": 43, "offline": 37})
    assert Counter(e.status for e in EVENTS) == Counter({"closed": 79, "upcoming": 1})


def test_non_hackathon_table_rows_are_skipped():
    names = {e.name for e in EVENTS}
    for skipped in (
        "ETHGlobal Happy Hour @ KBW",  # Meetup
        "Cowork with ETHGlobal in Bengaluru with Arc, Zo World + WAGMI Tribe",  # Co-working
        "Pragma Tokyo 2026",  # Conference
        "Ethereum Stablecoin Summit",  # Summit (hero, non-hackathon pill)
    ):
        assert skipped not in names


def test_url_duplicate_rows_collapse_to_the_first_occurrence():
    # ETHIndia 2022 and ETHWaterloo (2017) link to the same landing page as
    # their newer editions; under the (source, url) id model only the first
    # occurrence in table order (the newer edition) is kept.
    names = {e.name for e in EVENTS}
    assert "ETHIndia 2023" in names and "ETHIndia 2022" not in names
    assert "ETHWaterloo 2019" in names and "ETHWaterloo" not in names


def test_every_table_row_url_is_a_real_row_href():
    for event in EVENTS:
        if event.url == MUMBAI_URL:
            continue  # the carousel hero, not a table row
        assert event.url in TABLE_URLS


def test_fields_absent_from_the_rows_stay_none_or_empty():
    # Rows carry name, date(s), location and an event type only.
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


def test_future_hackathon_row_derives_upcoming_and_ongoing_derives_open():
    future = _row("Future Hack", "/events/future", "Nov 5th – Nov 7th, 2099", city="X", country="Y")
    ongoing = _row("Ongoing Hack", "/events/ongoing", "Oct 1st – Oct 20th, 2026", city="X", country="Y")
    events = _parse(future + ongoing)
    assert [e.status for e in events] == ["upcoming", "open"]
    assert events[0].start == date(2099, 11, 5)


def test_single_day_row_collapses_start_and_end():
    (event,) = _parse(_row("One Day", "/events/one", "Oct 8th, 2026", city="X", country="Y"))
    assert (event.start, event.end) == (date(2026, 10, 8), date(2026, 10, 8))


def test_cross_year_table_range_rolls_the_start_back_one_year():
    # "Dec 28th – Jan 5th, 2021": the trailing year belongs to the end date,
    # so the start is in the previous year (end < start before the wrap).
    (event,) = _parse(
        _row("Holiday Hack", "/events/holiday", "Dec 28th – Jan 5th, 2021", city="X", country="Y")
    )
    assert (event.start, event.end) == (date(2020, 12, 28), date(2021, 1, 5))
    assert event.status == "closed"  # both ends before ctx["now"]


def test_same_month_backwards_table_range_is_still_skipped():
    # The wrap requires end_month < start_month; a same-month inversion
    # ("Dec 28th – Dec 5th, 2021") stays malformed -> the row is skipped.
    backwards = _row("Backwards", "/events/backwards", "Dec 28th – Dec 5th, 2021", city="X", country="Y")
    assert _parse(backwards) == []


def test_dateless_row_is_skipped_not_guessed():
    # No honest dates -> no honest status derivation -> skip.
    assert _parse(_row("TBD Hack", "/events/tbd", "TBD", city="X", country="Y")) == []


def test_non_hackathon_badge_row_is_skipped():
    meetup = _row("Happy Hour", "/events/hh", "Oct 8th, 2026", city="X", country="Y", badge="Meetup")
    assert _parse(meetup) == []


def test_fragment_only_and_empty_hrefs_are_skipped_not_pinned_to_the_site_root():
    fragment = _row("Frag", "#", "Oct 8th, 2026", city="X", country="Y")
    anchorless = _row("No Anchor", "/events/x", "Oct 8th, 2026", city="X", country="Y", wrap_anchor=False)
    hero_fragment = _hero("Frag Hero", "#", "November", ["5", "7"], "Thu — Sat", "X, Y", "IRL Hackathon")
    assert _parse(fragment) == []
    assert _parse(anchorless) == []
    assert _parse(_page(hero_fragment)) == []


def test_empty_href_row_is_skipped_not_pinned_to_the_site_root():
    assert _parse(_row("Empty", "", "Oct 8th, 2026", city="X", country="Y")) == []
    assert _parse(_row("Blank", "   ", "Oct 8th, 2026", city="X", country="Y")) == []


def test_non_http_href_scheme_is_skipped():
    # javascript: hrefs fail the https:// identity check in both URL paths
    # (past-table row and carousel hero) -> skipped, never minted.
    row = _row("Evil", "javascript:alert(1)", "Oct 8th, 2026", city="X", country="Y")
    hero = _hero("Evil Hero", "javascript:alert(1)", "November", ["5", "7"], "Thu — Sat", "X, Y", "IRL Hackathon")
    assert _parse(row) == []
    assert _parse(_page(hero)) == []


def test_hero_with_online_hackathon_pill_maps_to_online():
    hero = _hero("Remote Jam", "/events/remote", "November", ["5", "7"], "Thu — Sat", "Everywhere", "Online Hackathon")
    (event,) = _parse(_page(hero))
    assert event.mode == "online"
    assert event.status == "upcoming"
    assert event.location == "Everywhere"
    assert event.url == f"{BASE}/events/remote"


def test_hero_with_non_hackathon_or_missing_pill_is_skipped():
    conference = _hero("Conf", "/events/conf", "November", ["5", "7"], "Thu — Sat", "X, Y", "Conference")
    pillless = _hero("No Pill", "/events/nopill", "November", ["5", "7"], "Thu — Sat", "X, Y", "")
    assert _parse(_page(conference)) == []
    assert _parse(_page(pillless)) == []


def test_hero_with_weekday_matching_no_candidate_year_leaves_dates_none():
    # November 5 is Thu in 2026 and Fri in 2027 — "Mon" matches neither year.
    hero = _hero("Wrong Day", "/events/wrong", "November", ["5", "7"], "Mon — Wed", "X, Y", "IRL Hackathon")
    (event,) = _parse(_page(hero))
    assert (event.start, event.end) == (None, None)


def test_hero_status_is_derived_from_its_own_dates_when_they_parse():
    # Started-not-ended must not read "upcoming"; ended -> closed. The page's
    # own "Upcoming" heading is only the fallback when no dates parse.
    ongoing = _hero("Ongoing", "/events/ongoing", "October", ["1", "20"], "Thu — Tue", "X, Y", "IRL Hackathon")
    ended = _hero("Ended", "/events/ended", "September", ["25", "27"], "Fri — Sun", "X, Y", "IRL Hackathon")
    undated = _hero("Undated", "/events/undated", "November", ["5", "7"], "Mon — Wed", "X, Y", "IRL Hackathon")
    ongoing_event, ended_event, undated_event = _parse(_page(ongoing, ended, undated))
    assert ongoing_event.status == "open"  # started, not ended, at ctx["now"]
    assert ended_event.status == "closed"  # ended before ctx["now"]
    assert undated_event.status == "upcoming"  # no dates -> the section flag stays


def test_hero_whose_month_is_before_now_derives_the_next_year():
    # January 20 is Wed in 2027 (Tue in 2026): the weekday picks 2027.
    hero = _hero("New Year Jam", "/events/newyear", "January", ["20", "22"], "Wed — Fri", "X, Y", "IRL Hackathon")
    (event,) = _parse(_page(hero))
    assert (event.start, event.end) == (date(2027, 1, 20), date(2027, 1, 22))


def test_hero_cross_month_range_parses_with_a_day_weekday_consistency_guard():
    # A cross-month range renders as "October — Nov" (start month in full,
    # end month abbreviated) with the days split across the boundary; the end
    # month comes from the box and rolls into the next year when it is
    # earlier than the start month. The second displayed weekday must agree
    # with the computed end date (day/weekday-consistency guard).
    same_year = _hero("Autumn Jam", "/events/autumn", "October — Nov", ["1", "20"], "Thu — Fri", "X, Y", "IRL Hackathon")
    wrapped = _hero("Holiday Jam", "/events/holiday", "December — Jan", ["28", "5"], "Mon — Tue", "X, Y", "IRL Hackathon")
    same_year_event, wrapped_event = _parse(_page(same_year, wrapped))
    assert (same_year_event.start, same_year_event.end) == (date(2026, 10, 1), date(2026, 11, 20))
    assert same_year_event.status == "open"  # started, not ended, at ctx["now"]
    assert (wrapped_event.start, wrapped_event.end) == (date(2026, 12, 28), date(2027, 1, 5))


def test_hero_cross_month_range_with_an_inconsistent_end_weekday_stays_undated():
    # The guard: a second weekday that disagrees with the computed end date
    # means the display cannot be trusted -> dates stay None, never guessed.
    bad = _hero("Bad Range", "/events/badrange", "October — Nov", ["1", "20"], "Thu — Sun", "X, Y", "IRL Hackathon")
    (event,) = _parse(_page(bad))
    assert (event.start, event.end) == (None, None)


def test_duplicate_hero_instances_of_one_event_collapse_to_one_event():
    first = _hero("Dup", "/events/dup", "November", ["5", "7"], "Thu — Sat", "X, Y", "IRL Hackathon")
    second = _hero("Dup", "/events/dup", "November", ["5", "7"], "Thu — Sat", "X, Y", "IRL Hackathon")
    assert len(_parse(_page(first, second))) == 1


def test_payload_without_an_upcoming_heading_yields_no_carousel_events():
    hero = _hero("No Heading", "/events/nh", "November", ["5", "7"], "Thu — Sat", "X, Y", "IRL Hackathon")
    assert _parse("<html><body>" + hero + "</body></html>") == []


def test_non_string_payload_yields_no_events_instead_of_crashing():
    assert EthglobalAdapter().parse(None, _ctx()) == []


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
    result = EthglobalAdapter().fetch(_ctx(crawl=fake))
    assert result is HTML
    assert fake.calls == [LISTING_URL]


def test_listing_url_is_the_ethglobal_events_page():
    assert LISTING_URL == "https://ethglobal.com/events"


# --- registry, sources.yaml -------------------------------------------------


def test_registry_exposes_the_ethglobal_adapter():
    adapter = ADAPTERS["ethglobal"]
    assert isinstance(adapter, EthglobalAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "ethglobal"
    assert adapter.kind == "browser"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_ethglobal_as_browser_kind():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    ethglobal = next(entry for entry in entries if entry["id"] == "ethglobal")
    assert ethglobal["kind"] == "browser"
    assert ethglobal["enabled"] is True
    assert ethglobal["url"] == LISTING_URL
    assert isinstance(ethglobal["notes"], str) and ethglobal["notes"].strip()
