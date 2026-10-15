"""Tests for the lablab.ai adapter (Task 9, browser kind).

Fixture-driven: `tests/fixtures/lablab/listing.html` is a real captured render
of https://lablab.ai/event (M0, 2026-10-09). No test here touches the network.

Every card in the fixture is an AI hackathon (the page's own listing), so the
adapter keeps all 12; the skip branches (identity, badge vocabulary, href
guards) are covered by synthetic cards built with the fixture's exact class
vocabulary.
"""

from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml
from bs4 import BeautifulSoup

from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.lablab import LISTING_URL, LablabAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "lablab" / "listing.html"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
HTML = FIXTURE.read_text(encoding="utf-8")

BASE = "https://lablab.ai"

LIVE_URL = f"{BASE}/ai-hackathons/amd-lablab-ai-academy-challenge"
ACT3_URL = f"{BASE}/ai-hackathons/amd-developer-hackathon-act-iii"
ONSITE_URL = f"{BASE}/ai-hackathons/qualcomm-x-meta-executorch-hackathon"
DARK_FACTORY_URL = f"{BASE}/ai-hackathons/wearedevelopers-hackathon"


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(html=HTML, **ctx_overrides):
    """Run the lablab parser on a payload (pure: payload + ctx only)."""
    return LablabAdapter().parse(html, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}


def _card(name, href, dt, date_text, status, mode, *, wrap_anchor=True, time_el=True):
    """Build a synthetic lablab card with the fixture's exact class vocabulary."""
    time_html = (
        f'<time datetime="{dt}"><span>{date_text}</span></time>' if time_el else ""
    )
    inner = (
        '<div class="p-4 flex h-max flex-1 flex-col justify-start"><div class="mb-auto">'
        f'<h2 class="mt-1 line-clamp-1 font-bold leading-tight text-2xl">{name}</h2>'
        f"{time_html}</div></div>"
        '<span class="inline-flex items-center gap-1.5 rounded-full font-semibold '
        "tracking-wide px-3 py-1 text-sm bg-white text-gray-900 absolute left-2 top-2 "
        f'shadow-md">{status}</span>'
        '<span class="inline-flex items-center gap-1 rounded-full font-semibold px-3 '
        "py-1 text-sm bg-slate-100 text-slate-500 absolute right-2 top-2 shadow-md"
        f'">{mode}</span>'
    )
    if wrap_anchor:
        inner = (
            f'<a class="flex h-full flex-col justify-between" href="{href}">{inner}</a>'
        )
    return (
        '<div class="card-animation card-border card-shadow relative flex h-full '
        f'flex-col overflow-hidden rounded-lg bg-white">{inner}</div>'
    )


# --- fixture sanity ---------------------------------------------------------


def test_fixture_is_a_real_captured_lablab_event_page():
    assert FIXTURE.is_file()
    assert "AI Hackathons" in HTML
    soup = BeautifulSoup(HTML, "html.parser")
    assert len(soup.select("div.card-animation")) == 12


# --- parse contract ---------------------------------------------------------


def test_parse_produces_at_least_three_events_with_name_and_url():
    assert len(EVENTS) >= 3
    for event in EVENTS:
        assert isinstance(event.name, str) and event.name.strip()
        assert event.url.startswith("https://")


def test_parse_extracts_every_card_in_the_fixture_grid():
    assert len(EVENTS) == 12


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "css"
    assert event.id == make_id("lablab", event.url)


def test_ids_are_unique():
    assert len({event.id for event in EVENTS}) == len(EVENTS)


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    for event in EVENTS:
        assert event.source == "lablab"
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


def test_relative_card_hrefs_resolve_against_the_site_base():
    assert all(e.url.startswith(f"{BASE}/ai-hackathons/") for e in EVENTS)
    assert all("?" not in e.url and "#" not in e.url for e in EVENTS)


def test_live_card_maps_name_dates_mode_and_status():
    event = BY_URL[LIVE_URL]
    assert event.name == "AMD AI League"
    assert event.mode == "online"  # "Online" badge
    assert event.status == "open"  # "LIVE" badge
    assert event.start == date(2026, 9, 1)
    assert event.end == date(2026, 12, 1)


def test_register_card_maps_to_open_with_its_displayed_range():
    # "Register" = registration currently open (mirrors devfolio's "Open"
    # reading: a registerable event whose start is still in the future).
    event = BY_URL[ACT3_URL]
    assert event.name == "AMD Developer Hackathon: ACT III"
    assert event.mode == "hybrid"  # "Hybrid" badge
    assert event.status == "open"  # "Register" badge
    assert (event.start, event.end) == (date(2026, 10, 12), date(2026, 10, 18))


def test_on_site_card_maps_to_offline_and_finished_to_closed():
    event = BY_URL[ONSITE_URL]
    assert event.name == "ExecuTorch Hackathon"
    assert event.mode == "offline"  # "On-site" badge
    assert event.status == "closed"  # "Finished" badge
    assert (event.start, event.end) == (date(2026, 6, 27), date(2026, 6, 28))


def test_cross_month_display_range_keeps_its_end_month():
    event = BY_URL[DARK_FACTORY_URL]
    assert event.name == "WeAreDevelopers x BAND present: Dark Factory (hackathon edition)"
    assert (event.start, event.end) == (date(2026, 9, 26), date(2026, 10, 6))


def test_status_split_matches_the_pages_own_badges():
    # 1 "LIVE" + 2 "Register" -> open; 9 "Finished" -> closed.
    counts = Counter(e.status for e in EVENTS)
    assert counts == Counter({"closed": 9, "open": 3})


def test_mode_split_matches_the_pages_own_badges():
    # 8 "Online" -> online; 3 "Hybrid" -> hybrid; 1 "On-site" -> offline.
    counts = Counter(e.mode for e in EVENTS)
    assert counts == Counter({"online": 8, "hybrid": 3, "offline": 1})


def test_fields_absent_from_the_cards_stay_none_or_empty():
    # The cards carry name, date range, a status badge and a mode badge only.
    for event in EVENTS:
        assert event.location is None
        assert event.reg_deadline is None
        assert event.team_min is None and event.team_max is None
        assert event.solo_ok is None
        assert event.prize is None
        assert event.themes == []
        assert event.eligibility is None
        assert event.cost is None
        assert event.also_on == []


# --- synthetic edge cases (branches the captured fixture does not cover) ----


def test_fragment_only_hrefs_are_skipped_not_pinned_to_the_site_root():
    # "#" / "#x" would urljoin to the bare listing page and mint a bogus event.
    assert _parse(_card("A", "#", "2026-10-12T15:00:00.000Z", "OCT 12 - 18", "Register", "Online")) == []
    assert _parse(_card("B", "#top", "2026-10-12T15:00:00.000Z", "OCT 12 - 18", "Register", "Online")) == []


def test_empty_and_whitespace_hrefs_are_skipped_not_pinned_to_the_site_root():
    assert _parse(_card("A", "", "2026-10-12T15:00:00.000Z", "OCT 12 - 18", "Register", "Online")) == []
    assert _parse(_card("B", "   ", "2026-10-12T15:00:00.000Z", "OCT 12 - 18", "Register", "Online")) == []


def test_cards_without_name_or_anchor_are_skipped_not_faked():
    assert _parse(_card("", "/ai-hackathons/x", "2026-10-12T15:00:00.000Z", "OCT 12 - 18", "Register", "Online")) == []
    assert _parse(_card("No Anchor", "/ai-hackathons/y", "2026-10-12T15:00:00.000Z", "OCT 12 - 18", "Register", "Online", wrap_anchor=False)) == []


def test_card_with_unknown_status_or_mode_badge_is_skipped_not_guessed():
    unknown_status = _card("Odd Status", "/ai-hackathons/a", "2026-10-12T15:00:00.000Z", "OCT 12 - 18", "Postponed", "Online")
    unknown_mode = _card("Odd Mode", "/ai-hackathons/b", "2026-10-12T15:00:00.000Z", "OCT 12 - 18", "Register", "Metaverse")
    assert _parse(unknown_status) == []
    assert _parse(unknown_mode) == []


def test_card_without_a_time_element_keeps_honest_none_dates():
    # Status/mode come from the badges, so a missing time element leaves the
    # event valid with start/end honestly unknown (never invented).
    (event,) = _parse(_card("No Time", "/ai-hackathons/c", "", "", "Register", "Online", time_el=False))
    assert (event.start, event.end) == (None, None)
    assert event.status == "open"


def test_card_with_unparseable_time_datetime_keeps_none_dates():
    (event,) = _parse(_card("Bad Time", "/ai-hackathons/d", "not-a-date", "OCT 12 - 18", "Register", "Online"))
    assert (event.start, event.end) == (None, None)


def test_display_range_that_disagrees_with_the_datetime_leaves_end_unknown():
    # start comes from the exact <time datetime>; a display range whose start
    # does not match it is untrusted -> end stays None, never guessed.
    (event,) = _parse(_card("Mismatch", "/ai-hackathons/e", "2026-10-12T15:00:00.000Z", "OCT 15 - 18", "Register", "Online"))
    assert event.start == date(2026, 10, 12)
    assert event.end is None


def test_cross_year_display_range_wraps_into_the_next_year():
    (event,) = _parse(_card("Year Wrap", "/ai-hackathons/f", "2026-12-28T15:00:00.000Z", "DEC 28 - JAN 5", "Register", "Online"))
    assert (event.start, event.end) == (date(2026, 12, 28), date(2027, 1, 5))


def test_single_day_display_range_collapses_start_and_end():
    (event,) = _parse(_card("One Day", "/ai-hackathons/g", "2026-10-12T15:00:00.000Z", "OCT 12", "Register", "Online"))
    assert (event.start, event.end) == (date(2026, 10, 12), date(2026, 10, 12))


def test_same_month_day_inversion_leaves_end_unknown():
    # "JUN 30 - 5" has no second month to wrap into; an end before the start
    # is malformed, so end stays None rather than emitting end < start.
    (event,) = _parse(_card("Inverted", "/ai-hackathons/h", "2026-06-30T15:00:00.000Z", "JUN 30 - 5", "Register", "Online"))
    assert event.start == date(2026, 6, 30)
    assert event.end is None


def test_same_month_named_inversion_leaves_end_unknown():
    # "JUN 30 - JUN 5" names the same month twice: the cross-year wrap branch
    # requires end_month < start_month, so this malformed display leaves end
    # None instead of wrapping a full year.
    (event,) = _parse(_card("Inverted Named", "/ai-hackathons/i", "2026-06-30T15:00:00.000Z", "JUN 30 - JUN 5", "Register", "Online"))
    assert event.start == date(2026, 6, 30)
    assert event.end is None


def test_non_http_href_scheme_is_skipped():
    card = _card("Evil", "javascript:alert(1)", "2026-10-12T15:00:00.000Z", "OCT 12 - 18", "Register", "Online")
    assert _parse(card) == []


def test_non_string_payload_yields_no_events_instead_of_crashing():
    assert LablabAdapter().parse(None, _ctx()) == []


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
    result = LablabAdapter().fetch(_ctx(crawl=fake))
    assert result is HTML
    assert fake.calls == [LISTING_URL]


def test_listing_url_is_the_lablab_event_page():
    assert LISTING_URL == "https://lablab.ai/event"


# --- registry, sources.yaml -------------------------------------------------


def test_registry_exposes_the_lablab_adapter():
    adapter = ADAPTERS["lablab"]
    assert isinstance(adapter, LablabAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "lablab"
    assert adapter.kind == "browser"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_lablab_as_browser_kind():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    lablab = next(entry for entry in entries if entry["id"] == "lablab")
    assert lablab["kind"] == "browser"
    assert lablab["enabled"] is True
    assert lablab["url"] == LISTING_URL
    assert isinstance(lablab["notes"], str) and lablab["notes"].strip()
