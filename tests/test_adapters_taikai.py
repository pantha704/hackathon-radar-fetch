"""Tests for the TAIKAI adapter (Task 9, browser kind).

Fixture-driven: `tests/fixtures/taikai/listing.html` is a real captured render
of https://taikai.network/hackathons (M0, 2026-10-09). No test here touches
the network.

The page lists public hackathons only (`div[data-public="true"]` — 20 cards in
the fixture). The cards carry no dates and no per-card mode/location, so the
adapter applies its documented platform-nature default (`mode="online"`, see
the module docstring) and leaves `start`/`end`/`reg_deadline` honestly None —
the unlabeled "N days left" countdown is deliberately NOT mapped to a date
field (same ruling as the dorahacks adapter).
"""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from bs4 import BeautifulSoup

from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.taikai import LISTING_URL, TaikaiAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "taikai" / "listing.html"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
HTML = FIXTURE.read_text(encoding="utf-8")

BASE = "https://taikai.network"

SPACEX_URL = f"{BASE}/en/spacexai/hackathons/spacexai-digital-transformation-lab/"
CASSINI_URL = f"{BASE}/en/cassinihackathons/hackathons/space-for-peace-resilience/"
HACK4_URL = f"{BASE}/en/cmguimaraes/hackathons/hack4guimaraes2035/"
VELES_URL = f"{BASE}/en/eclipse-foundation/hackathons/veles-hack-2026/"
PORTO_URL = f"{BASE}/en/instituto-amigu/hackathons/porto-hack-santos-2026/"


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(html=HTML, **ctx_overrides):
    """Run the TAIKAI parser on a payload (pure: payload + ctx only)."""
    return TaikaiAdapter().parse(html, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}


def _card(name, href, state, *, ended="false", prize=("3,500", "$"), tags=(), wrap_anchor=True):
    """Build a synthetic TAIKAI card with the fixture's exact class vocabulary."""
    prize_html = (
        '<div class="styles-module__Yh3-Za__prize"><span>Prize</span><div>'
        f"<span>{prize[0]}</span><span>{prize[1]}</span></div></div>"
        if prize is not None
        else ""
    )
    tags_html = "".join(f"<span>{tag}</span>" for tag in tags)
    inner = (
        '<div class="styles-module__Yh3-Za__coverWrapper">'
        f'<div class="styles-module__Yh3-Za__state" data-ended="{ended}">{state}</div></div>'
        '<div class="styles-module__Yh3-Za__container">'
        '<div class="styles-module__Yh3-Za__content">'
        f"<h3>{name}</h3><div style=\"overflow:hidden\"><span>copy</span></div>"
        f'<div class="styles-module__Yh3-Za__tags">{tags_html}</div></div>'
        f'<div class="styles-module__Yh3-Za__footer">{prize_html}</div></div>'
    )
    if wrap_anchor:
        inner = f'<a href="{href}">{inner}</a>'
    return f'<div class="styles-module__Yh3-Za__wrapper" data-public="true">{inner}</div>'


# --- fixture sanity ---------------------------------------------------------


def test_fixture_is_a_real_captured_taikai_hackathon_page():
    assert FIXTURE.is_file()
    assert "TAIKAI" in HTML
    soup = BeautifulSoup(HTML, "html.parser")
    assert len(soup.select('div[data-public="true"]')) == 20


# --- parse contract ---------------------------------------------------------


def test_parse_produces_at_least_three_events_with_name_and_url():
    assert len(EVENTS) >= 3
    for event in EVENTS:
        assert isinstance(event.name, str) and event.name.strip()
        assert event.url.startswith("https://")


def test_parse_extracts_every_public_card_in_the_fixture():
    assert len(EVENTS) == 20


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "css"
    assert event.id == make_id("taikai", event.url)


def test_ids_are_unique():
    assert len({event.id for event in EVENTS}) == len(EVENTS)


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    for event in EVENTS:
        assert event.source == "taikai"
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
    assert all(e.url.startswith(f"{BASE}/en/") for e in EVENTS)
    assert all("?" not in e.url and "#" not in e.url for e in EVENTS)


def test_registration_card_maps_name_prize_and_open_status():
    event = BY_URL[SPACEX_URL]
    assert event.name == "SpaceXAI Digital Transformation Lab"
    assert event.status == "open"  # "Registration" state
    assert event.prize == "3,500$"  # kept raw as displayed
    assert event.themes == ["Artificial Intelligence"]


def test_registrations_open_and_localised_state_map_to_open():
    # "Registrations open" (English) and "Inscrições" (pt) are the same
    # registration phase on the platform.
    assert BY_URL[CASSINI_URL].status == "open"
    assert BY_URL[CASSINI_URL].name == "CASSINI Hackathons - Space for Peace and Resilience"
    assert BY_URL[CASSINI_URL].prize == "9,000€"
    assert BY_URL[CASSINI_URL].themes == [
        "Defense & Security",
        "Satellite Communication",
        "European Defence",
        "Space",
    ]
    assert BY_URL[HACK4_URL].status == "open"
    assert BY_URL[HACK4_URL].name == "Hack4Guimarães 2035"


def test_award_ceremony_state_is_closed_not_actionable():
    # The event is in its final ceremony phase (submissions/registration over);
    # data-ended is still "false" there, so the state text is the signal.
    event = BY_URL[VELES_URL]
    assert event.name == "Veles Hack 2026"
    assert event.status == "closed"


def test_finished_card_maps_to_closed_with_no_prize_left_none():
    event = BY_URL[PORTO_URL]
    assert event.name == "Porto Hack Santos 2026"
    assert event.status == "closed"  # "Finished" state
    assert event.prize is None  # no prize block on the card
    assert event.themes == ["Social Good & Impact"]


def test_status_split_matches_the_pages_own_states():
    # 3 registration-phase cards -> open; 1 award ceremony + 16 finished -> closed.
    counts = Counter(e.status for e in EVENTS)
    assert counts == Counter({"closed": 17, "open": 3})


def test_mode_defaults_to_online_with_the_platform_rationale():
    # The cards carry no per-card mode/location and the platform self-describes
    # as hosting "online, virtual hackathons" (its own ld+json on this page);
    # the documented platform-nature default applies to every row.
    assert all(e.mode == "online" for e in EVENTS)


def test_fields_absent_from_the_cards_stay_none_or_empty():
    # No dates, no location, no team/eligibility/cost anywhere on the cards.
    for event in EVENTS:
        assert event.location is None
        assert event.reg_deadline is None
        assert event.start is None
        assert event.end is None
        assert event.team_min is None and event.team_max is None
        assert event.solo_ok is None
        assert event.eligibility is None
        assert event.cost is None
        assert event.also_on == []


# --- synthetic edge cases (branches the captured fixture does not cover) ----


def test_fragment_only_hrefs_are_skipped_not_pinned_to_the_site_root():
    assert _parse(_card("A", "#", "Registration")) == []
    assert _parse(_card("B", "#top", "Registration")) == []


def test_empty_and_whitespace_hrefs_are_skipped_not_pinned_to_the_site_root():
    assert _parse(_card("A", "", "Registration")) == []
    assert _parse(_card("B", "   ", "Registration")) == []


def test_non_http_href_scheme_is_skipped():
    card = _card("Evil", "javascript:alert(1)", "Registration")
    assert _parse(card) == []


def test_cards_without_name_or_anchor_are_skipped_not_faked():
    assert _parse(_card("", "/en/x/hackathons/y/", "Registration")) == []
    assert _parse(_card("No Anchor", "/en/x/hackathons/y/", "Registration", wrap_anchor=False)) == []


def test_card_with_unknown_state_text_is_skipped_not_guessed():
    assert _parse(_card("Mystery", "/en/x/hackathons/y/", "Under Review")) == []
    assert _parse(_card("Mystery", "/en/x/hackathons/y/", "")) == []


def test_prize_is_none_when_the_card_carries_no_prize_block():
    (event,) = _parse(_card("No Prize", "/en/x/hackathons/y/", "Finished", prize=None))
    assert event.prize is None


def test_the_countdown_text_is_never_mapped_to_a_date_field():
    # "18 days left" counts down to an unlabeled deadline; mapping it to
    # reg_deadline/start/end would be a guess (dorahacks ruling).
    card = _card("Countdown", "/en/x/hackathons/y/", "Registration").replace(
        '<div class="styles-module__Yh3-Za__footer">',
        '<div class="styles-module__Yh3-Za__progress"><div><div>18 days left</div></div></div>'
        '<div class="styles-module__Yh3-Za__footer">',
    )
    (event,) = _parse(card)
    assert event.reg_deadline is None
    assert event.start is None and event.end is None


def test_non_string_payload_yields_no_events_instead_of_crashing():
    assert TaikaiAdapter().parse(None, _ctx()) == []


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
    result = TaikaiAdapter().fetch(_ctx(crawl=fake))
    assert result is HTML
    assert fake.calls == [LISTING_URL]


def test_listing_url_is_the_taikai_hackathon_listing():
    assert LISTING_URL == "https://taikai.network/hackathons"


# --- registry, sources.yaml -------------------------------------------------


def test_registry_exposes_the_taikai_adapter():
    adapter = ADAPTERS["taikai"]
    assert isinstance(adapter, TaikaiAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "taikai"
    assert adapter.kind == "browser"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_taikai_as_browser_kind():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    taikai = next(entry for entry in entries if entry["id"] == "taikai")
    assert taikai["kind"] == "browser"
    assert taikai["enabled"] is True
    assert taikai["url"] == LISTING_URL
    assert isinstance(taikai["notes"], str) and taikai["notes"].strip()
