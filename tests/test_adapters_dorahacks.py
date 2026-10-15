"""Tests for the DoraHacks adapter (Task 8, browser kind).

Fixture-driven: `tests/fixtures/dorahacks/listing.html` is a real captured
render of https://dorahacks.io/hackathon (M0, 2026-10-09). No test here
touches the network.

The cards carry no calendar dates (only a countdown to an unlabeled
deadline), so start/end/reg_deadline stay None — see the honesty tests.
"""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.dorahacks import LISTING_URL, DorahacksAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "dorahacks" / "listing.html"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
HTML = FIXTURE.read_text(encoding="utf-8")


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(html=HTML, **ctx_overrides):
    """Run the DoraHacks parser on a payload (pure: payload + ctx only)."""
    return DorahacksAdapter().parse(html, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}


def _card(name, href, status, location, *, anchor=True, themes=("AI",)):
    """Build a synthetic DoraHacks card with the fixture's class vocabulary."""
    pills = "".join(
        f'<div class="me-2 inline-block rounded bg-accent-bg px-1 py-0.5 '
        f'text-xs text-accent-primary">{t}</div>'
        for t in themes
    )
    card = (
        '<div class="hackathon-card" data-v-x="">'
        '<div class="flex flex-row items-center">'
        f'<span class="ml-10 truncate">{name} Org</span>'
        '<div class="flex h-fit flex-row items-center whitespace-nowrap text-xs status-ongoing rounded ml-auto">'
        f'<span aria-label="hackathon-status" class="state rounded">{status}</span>'
        "</div></div>"
        f'<div><span class="line-clamp-2 font-semibold">{name}</span></div>'
        f'<div><span class="line-clamp-1 break-all text-ink-secondary">{location}</span></div>'
        f"<div>{pills}</div>"
        "</div>"
    )
    return f'<a href="{href}">{card}</a>' if anchor else card


# --- fixture sanity ---------------------------------------------------------


def test_fixture_is_a_real_captured_dorahacks_page():
    assert FIXTURE.is_file()
    assert "DoraHacks" in HTML
    assert HTML.count('class="hackathon-card"') >= 24


# --- parse contract ---------------------------------------------------------


def test_parse_produces_at_least_three_events_with_name_and_url():
    assert len(EVENTS) >= 3
    for event in EVENTS:
        assert isinstance(event.name, str) and event.name.strip()
        assert event.url.startswith("https://dorahacks.io/hackathon/")


def test_parse_extracts_every_card_in_the_fixture():
    assert len(EVENTS) == 24


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "css"
    assert event.id == make_id("dorahacks", event.url)


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    for event in EVENTS:
        assert event.source == "dorahacks"
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


def test_ongoing_virtual_card_maps_status_mode_location_prize_and_themes():
    event = BY_URL["https://dorahacks.io/hackathon/weex-ai-wars2"]
    assert event.name == "WEEX AI Wars II: Rise of Intelligence"
    assert event.status == "open"  # "Ongoing"
    assert event.mode == "online"  # "Virtual" location
    assert event.location == "Virtual"
    assert event.prize == "200,000 USD"
    assert event.themes == ["Al", "Trading", "Algorithmic", "Web3", "Crypto", "Risk Management"]


def test_upcoming_physical_card_maps_to_offline_with_its_location():
    event = BY_URL["https://dorahacks.io/hackathon/2285"]
    assert event.name == "HackTrent 2026"
    assert event.status == "upcoming"
    assert event.mode == "offline"
    assert event.location == "Peterborough, Ontario, Canada"
    assert event.prize == "2,000 USD"


def test_extended_status_maps_to_open():
    event = BY_URL["https://dorahacks.io/hackathon/2349"]
    assert event.name == "Anna AI App Builder Program"
    assert event.status == "open"


def test_pre_registration_maps_to_upcoming():
    event = BY_URL["https://dorahacks.io/hackathon/portaldot-hacker-house-2026"]
    assert event.status == "upcoming"


def test_ended_and_winner_cards_map_to_closed():
    chain_jam = BY_URL["https://dorahacks.io/hackathon/chain-jam-vol-1"]
    assert chain_jam.status == "closed"  # "Ended"
    keeperhub = BY_URL["https://dorahacks.io/hackathon/agent-economy"]
    assert keeperhub.status == "closed"  # "Winner Announced 🏅"
    assert keeperhub.name == "KeeperHub - The Agent Economy Hackathon"


def test_prize_text_is_kept_raw_when_it_is_not_an_amount():
    event = BY_URL["https://dorahacks.io/hackathon/web3-social-good-2026"]
    assert event.prize == "Pending"  # the page's own value, not invented
    assert event.mode == "offline"  # "Singapore, Singapore"


def test_status_split_matches_the_pages_own_badges():
    assert Counter(e.status for e in EVENTS) == {
        "open": 11,       # Ongoing (10) + Extended (1)
        "upcoming": 5,    # Upcoming (4) + Pre-registration (1)
        "closed": 8,      # Ended (4) + Winner Announced (4)
    }


def test_mode_split_matches_the_pages_own_locations():
    assert Counter(e.mode for e in EVENTS) == {"online": 21, "offline": 3}


def test_countdown_text_is_not_misfiled_as_a_date():
    # "3 days left" is a countdown to an unlabeled deadline: the model's
    # date fields stay None rather than guessing which date it counts to.
    event = BY_URL["https://dorahacks.io/hackathon/weex-ai-wars2"]
    assert event.reg_deadline is None
    assert event.start is None
    assert event.end is None


def test_fields_absent_from_the_cards_stay_none_or_empty():
    for event in EVENTS:
        assert event.reg_deadline is None
        assert event.start is None
        assert event.end is None
        assert event.team_min is None and event.team_max is None
        assert event.solo_ok is None
        assert event.eligibility is None
        assert event.cost is None
        assert event.also_on == []
        assert all(isinstance(t, str) and t.strip() for t in event.themes)


# --- synthetic edge cases (branches the captured fixture does not cover) ----


def test_pending_named_card_with_pipes_in_the_title_parses_cleanly():
    event = BY_URL["https://dorahacks.io/hackathon/arc-microgrants"]
    assert event.name == "Arc Microgrants | Circle"
    assert event.status == "open"


def test_cards_with_an_unknown_status_are_skipped_not_guessed():
    card = _card("Mystery Hack", "/hackathon/mystery", "Judging", "Virtual")
    assert _parse(card) == []


def test_cards_without_a_location_are_skipped_not_guessed():
    # No location text -> no honest mode signal -> skip.
    card = _card("No Place", "/hackathon/no-place", "Ongoing", "")
    assert _parse(card) == []


def test_cards_without_status_or_anchor_are_skipped_not_faked():
    assert _parse(_card("No Status", "/hackathon/no-status", "", "Virtual")) == []
    assert _parse(_card("No Anchor", "/hackathon/no-anchor", "Ongoing", "Virtual",
                        anchor=False)) == []


def test_relative_hrefs_are_resolved_against_dorahacks_io():
    card = _card("Relative Hack", "/hackathon/relative-hack", "Ongoing", "Virtual")
    (event,) = _parse(card)
    assert event.url == "https://dorahacks.io/hackathon/relative-hack"
    assert event.id == make_id("dorahacks", event.url)


def test_cards_with_empty_or_whitespace_hrefs_are_skipped_not_pinned_to_the_site_root():
    # urljoin(base, "") resolves to the bare site root — the card would pass
    # the https:// identity check and create a bogus event pinned to the
    # listing page. Empty/whitespace raw hrefs are skipped instead.
    assert _parse(_card("Hrefless", "", "Ongoing", "Virtual")) == []
    assert _parse(_card("Whitespace", "   ", "Ongoing", "Virtual")) == []


def test_fragment_only_hrefs_are_skipped_not_pinned_to_the_site_root():
    # "#" / "#x" would urljoin to the bare listing page and mint a bogus event.
    assert _parse(_card("Fragment", "#", "Ongoing", "Virtual")) == []
    assert _parse(_card("Fragment Top", "#top", "Ongoing", "Virtual")) == []


def test_non_string_payload_yields_no_events_instead_of_crashing():
    assert DorahacksAdapter().parse(None, _ctx()) == []


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
    result = DorahacksAdapter().fetch(_ctx(crawl=fake))
    assert result is HTML
    assert fake.calls == [LISTING_URL]


def test_listing_url_is_the_dorahacks_hackathon_page():
    assert LISTING_URL == "https://dorahacks.io/hackathon"


# --- registry, sources.yaml -------------------------------------------------


def test_registry_exposes_the_dorahacks_adapter():
    adapter = ADAPTERS["dorahacks"]
    assert isinstance(adapter, DorahacksAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "dorahacks"
    assert adapter.kind == "browser"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_dorahacks_as_browser_kind():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    dorahacks = next(entry for entry in entries if entry["id"] == "dorahacks")
    assert dorahacks["kind"] == "browser"
    assert dorahacks["enabled"] is True
    assert dorahacks["url"] == LISTING_URL
    assert isinstance(dorahacks["notes"], str) and dorahacks["notes"].strip()
