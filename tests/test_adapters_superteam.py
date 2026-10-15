"""Tests for the Superteam Earn adapter (Task 8, browser kind).

Fixture-driven: `tests/fixtures/superteam/listing.html` is a real captured
render of https://earn.superteam.fun/ (M0, 2026-10-09). No test here touches
the network.

This page mixes listing types: bounty and grant listings (20 of them, each
carrying its own type label) plus the featured hackathon entries. The adapter
keeps hackathon-type items only — see the skip tests and the module docstring
of `radar/adapters/superteam.py` for the extraction rationale.
"""

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import pytest
import yaml
from bs4 import BeautifulSoup

from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.superteam import LISTING_URL, SuperteamAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "superteam" / "listing.html"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

BASE = "https://earn.superteam.fun"
NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
HTML = FIXTURE.read_text(encoding="utf-8")

_SOUP = BeautifulSoup(HTML, "html.parser")
LISTING_CARDS = _SOUP.select("a.block.w-full.rounded-md")
LISTING_CARD_URLS = {urljoin(BASE, a["href"]) for a in LISTING_CARDS}


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(html=HTML, **ctx_overrides):
    """Run the Superteam parser on a payload (pure: payload + ctx only)."""
    return SuperteamAdapter().parse(html, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}

CRYPTO_URL = "https://earn.superteam.fun/earn/hackathon/crypto-worlds-fair"
BREAKPOINT_URL = "https://earn.superteam.fun/earn/next-stop-breakpoint"


def _listing_card(title, href, badge=None):
    """Build a synthetic listing card with the fixture's class vocabulary."""
    label = (
        f'<div class="flex items-center gap-1"><p class="hidden text-xs '
        f'font-medium text-gray-500 sm:flex">{badge}</p></div>'
        if badge is not None
        else ""
    )
    return (
        '<a class="block w-full rounded-md px-2 py-4 no-underline hover:bg-gray-100 sm:px-4" '
        f'href="{href}">'
        '<div class="flex w-full items-center justify-between"><div class="flex w-full">'
        '<img alt="Sponsor" class="mr-3 h-14 w-14 rounded-md" src="https://cdn.example/a.png"/>'
        '<div class="flex w-full flex-col justify-between">'
        f'<p class="line-clamp-1 text-sm font-semibold text-slate-700 sm:text-base">{title}</p>'
        '<div class="mt-px flex items-center gap-1 sm:gap-2">'
        f"{label}"
        "</div></div></div></div></a>"
    )


def _featured_anchor(href, alt, img_src="https://cdn.example/assets/hackathon/x/logo.png"):
    """Build a synthetic featured-hackathon anchor (nav/hero/promo shape)."""
    return f'<a class="group block rounded-lg" href="{href}"><img alt="{alt}" src="{img_src}"/></a>'


# --- fixture sanity ---------------------------------------------------------


def test_fixture_is_a_real_captured_superteam_page():
    assert FIXTURE.is_file()
    assert "Superteam Earn" in HTML
    assert "/earn/hackathon/" in HTML
    assert len(LISTING_CARDS) == 20  # the bounty/grant listings that must be skipped


# --- parse contract ---------------------------------------------------------


def test_parse_extracts_exactly_the_two_hackathon_type_entries_the_fixture_carries():
    # The capture contains the two featured hackathon programs only; every
    # bounty/grant listing carries a non-hackathon type label (see skip tests).
    assert len(EVENTS) == 2
    assert [e.url for e in EVENTS] == [CRYPTO_URL, BREAKPOINT_URL]


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "css"
    assert event.id == make_id("superteam", event.url)


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    assert EVENTS
    for event in EVENTS:
        assert event.source == "superteam"
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


def test_crypto_worlds_fair_featured_entry_is_kept_with_canonical_url():
    event = BY_URL[CRYPTO_URL]
    assert event.name == "Crypto World's Fair"


def test_next_stop_breakpoint_featured_entry_is_kept_with_canonical_url():
    event = BY_URL[BREAKPOINT_URL]
    assert event.name == "Next Stop Breakpoint"


def test_repeated_card_instances_of_one_program_collapse_to_one_event():
    # Each featured program appears in the nav strip, top hero and mid-page
    # promo; they share a URL and must not produce duplicate rows.
    assert len(EVENTS) == len({e.url for e in EVENTS}) == 2


def test_no_bounty_or_grant_listing_is_kept():
    kept_urls = {e.url for e in EVENTS}
    assert len(LISTING_CARD_URLS) == 20
    assert kept_urls.isdisjoint(LISTING_CARD_URLS)


def test_skip_split_is_exactly_ten_bounties_and_ten_grants():
    # The 20 skipped listings split 10 Bounty / 10 Grant — pinned exactly, so
    # a future capture whose split changes (e.g. hackathon-labelled listings
    # entering the page) shows up as an explicit test failure, not drift.
    labels = Counter(
        label.get_text(strip=True)
        for anchor in LISTING_CARDS
        if (label := anchor.select_one("p.text-xs.font-medium.text-gray-500"))
        is not None
    )
    assert labels == Counter({"Bounty": 10, "Grant": 10})


def test_fields_absent_from_the_featured_cards_stay_none_or_empty():
    # The featured cards show no location, dates, prize or team information.
    for event in EVENTS:
        assert event.location is None
        assert event.reg_deadline is None
        assert event.start is None
        assert event.end is None
        assert event.team_min is None and event.team_max is None
        assert event.solo_ok is None
        assert event.prize is None
        assert event.themes == []
        assert event.eligibility is None
        assert event.cost is None
        assert event.also_on == []


def test_featured_entries_default_mode_and_status_when_the_page_carries_neither():
    # The listing page carries no per-event mode/location and no status
    # marker for the featured programs; the adapter must not crash by
    # writing None (the model has no unknown mode/status) — it applies its
    # documented defaults: mode "online" (platform nature — earn.superteam.fun
    # programs are entered/submitted online from anywhere) and status "open"
    # (featured = currently promoted, live click-through).
    for event in EVENTS:
        assert event.mode == "online"
        assert event.status == "open"


# --- synthetic edge cases (branches the captured fixture does not cover) ----


def test_hackathon_labelled_listing_is_kept():
    card = _listing_card("Fake Hackathon Listing", "/earn/listing/fake-hackathon", "Hackathon")
    (event,) = _parse(card)
    assert event.name == "Fake Hackathon Listing"
    assert event.url == "https://earn.superteam.fun/earn/listing/fake-hackathon"
    assert event.mode == "online"
    assert event.status == "open"


def test_hackathon_labelled_listing_under_the_hackathon_route_is_named_from_its_title():
    # Branch order: a listing card whose own type label reads "Hackathon"
    # takes the title branch even when it also routes under /earn/hackathon/;
    # the name must come from the card title, not from image alt ("Sponsor").
    card = _listing_card("Future Hackathon", "/earn/hackathon/future-hack", "Hackathon")
    (event,) = _parse(card)
    assert event.name == "Future Hackathon"
    assert event.url == "https://earn.superteam.fun/earn/hackathon/future-hack"


def test_anchors_with_empty_or_whitespace_hrefs_are_skipped_not_pinned_to_the_site_root():
    # urljoin(base, "") resolves to the bare site root — the anchor would
    # pass the https:// identity check and create a bogus event pinned to
    # the listing page. Empty/whitespace raw hrefs are skipped instead.
    empty = _listing_card("Hrefless Hack", "", "Hackathon")
    blank = _listing_card("Whitespace Hack", "   ", "Hackathon")
    featured_empty = _featured_anchor("", "Hrefless Featured")
    assert _parse(empty + blank + featured_empty) == []


def test_bounty_grant_and_unlabelled_listings_are_skipped():
    bounty = _listing_card("Bounty B", "/earn/listing/bounty-b", "Bounty")
    grant = _listing_card("Grant G", "/earn/grants/grant-g", "Grant")
    unlabelled = _listing_card("Mystery M", "/earn/listing/mystery-m")
    assert _parse(bounty + grant + unlabelled) == []


def test_featured_hackathon_namespace_anchor_is_kept_and_deduplicated():
    first = _featured_anchor("/earn/hackathon/dup-event", "Dup Event")
    second = _featured_anchor("/earn/hackathon/dup-event", "Other Alt")
    (event,) = _parse(first + second)
    assert event.name == "Dup Event"  # first occurrence wins
    assert event.url == "https://earn.superteam.fun/earn/hackathon/dup-event"


def test_plain_page_chrome_anchors_are_not_treated_as_hackathons():
    # No hackathon route, no hackathon-namespace artwork, no type label.
    chrome = (
        '<a class="flex items-center py-2" href="/earn/sponsor">'
        '<img alt="Sponsor" src="https://cdn.example/assets/earn-sponsor/x.png"/></a>'
        '<a class="flex items-center py-2" href="/earn/all?tab=bounties">Bounties</a>'
    )
    assert _parse(chrome) == []


def test_non_string_payload_yields_no_events_instead_of_crashing():
    assert SuperteamAdapter().parse(None, _ctx()) == []


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
    result = SuperteamAdapter().fetch(_ctx(crawl=fake))
    assert result is HTML
    assert fake.calls == [LISTING_URL]


def test_listing_url_is_the_superteam_earn_homepage():
    assert LISTING_URL == "https://earn.superteam.fun/"


# --- registry, sources.yaml -------------------------------------------------


def test_registry_exposes_the_superteam_adapter():
    adapter = ADAPTERS["superteam"]
    assert isinstance(adapter, SuperteamAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "superteam"
    assert adapter.kind == "browser"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_superteam_as_browser_kind():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    superteam = next(entry for entry in entries if entry["id"] == "superteam")
    assert superteam["kind"] == "browser"
    assert superteam["enabled"] is True
    assert superteam["url"] == LISTING_URL
    assert isinstance(superteam["notes"], str) and superteam["notes"].strip()
