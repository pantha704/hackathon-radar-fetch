"""Tests for the fetch layer and the devfolio adapter (Task 4).

Fixture-driven: `tests/fixtures/devfolio/listing.html` is a real captured
rendered page (M0). No test here touches the network.
"""

import importlib
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from radar import browser, fetch
from radar.adapters import ADAPTERS
from radar.adapters.base import Adapter
from radar.adapters.devfolio import LISTING_URL, DevfolioAdapter
from radar.models import MODES, STATUSES, make_id

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "devfolio" / "listing.html"
SOURCES_YAML = ROOT / "radar" / "sources.yaml"

NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
HTML = FIXTURE.read_text(encoding="utf-8")


def _ctx(**overrides):
    """Runner context (SDD ruling 1: plain dict — now / http / crawl)."""
    ctx = {"now": NOW, "http": None, "crawl": None}
    ctx.update(overrides)
    return ctx


def _parse(html=HTML, **ctx_overrides):
    """Run the devfolio parser on a payload (pure: payload + ctx only)."""
    return DevfolioAdapter().parse(html, _ctx(**ctx_overrides))


EVENTS = _parse()
BY_URL = {event.url: event for event in EVENTS}


# --- fixture sanity ---------------------------------------------------------


def test_fixture_is_a_real_captured_devfolio_page():
    assert FIXTURE.is_file()
    assert "devfolio" in HTML.lower()
    assert HTML.count("CompactHackathonCard__StyledCard") >= 3


# --- parse contract ---------------------------------------------------------


def test_parse_produces_at_least_three_events_with_name_and_url():
    assert len(EVENTS) >= 3
    for event in EVENTS:
        assert isinstance(event.name, str) and event.name.strip()
        assert event.url.startswith("https://")


@pytest.mark.parametrize("event", EVENTS, ids=[event.id for event in EVENTS])
def test_every_event_satisfies_the_contract(event):
    assert event.status in STATUSES
    assert event.mode in MODES
    assert event.extracted_by == "css"
    assert event.id == make_id("devfolio", event.url)


def test_events_are_stamped_with_adapter_identity_and_ctx_now():
    for event in EVENTS:
        assert event.source == "devfolio"
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


def test_wild_bugs_card_maps_mode_status_starts_date_and_themes():
    event = BY_URL["https://wild-bugs.devfolio.co/"]
    assert event.name == "Wild Bugs"
    assert event.mode == "online"
    assert event.status == "open"
    assert event.start == date(2026, 10, 14)
    assert event.themes == ["No Restrictions"]


def test_offline_card_maps_to_offline_mode_with_its_starts_date():
    event = BY_URL["https://codearambh.devfolio.co/"]
    assert event.mode == "offline"
    assert event.status == "open"
    assert event.start == date(2026, 10, 23)


def test_live_card_is_open_but_has_no_start_date_on_the_card():
    event = BY_URL["https://codestorm-futureforge.devfolio.co/"]
    assert event.status == "open"
    assert event.start is None  # card shows "Live", no date — never invented
    assert event.themes == ["Design", "AI", "Future Mobility"]


def test_upcoming_card_opens_date_is_not_misfiled_as_start():
    # "Opens 20/10/26" = applications open; the model has no field for it,
    # so start stays None (never misfiled).
    event = BY_URL["https://lean-in-hacks-8.devfolio.co/"]
    assert event.status == "upcoming"
    assert event.start is None


def test_ended_card_maps_to_closed_status():
    event = BY_URL["https://recursiveacm.devfolio.co/"]
    assert event.status == "closed"
    assert event.mode == "offline"


def test_name_entities_are_decoded():
    event = BY_URL["https://tum.devfolio.co/"]
    assert event.name == "TUM Blockchain & AI Hackathon"


def test_fields_absent_from_the_cards_stay_none_or_empty():
    # The compact cards carry no location, prize, deadline, end, team or
    # eligibility info — those fields must stay unset, never invented.
    for event in EVENTS:
        assert event.location is None
        assert event.reg_deadline is None
        assert event.end is None
        assert event.prize is None
        assert event.team_min is None and event.team_max is None
        assert event.solo_ok is None
        assert event.eligibility is None
        assert event.cost is None
        assert event.also_on == []
        assert all(isinstance(t, str) and t.strip() for t in event.themes)


# --- synthetic edge cases (branches the captured fixture does not cover) ----


_SYNTHETIC_CARD = (
    '<div class="CompactHackathonCard__StyledCard-sc-abc x">'
    '<div><a href="https://fake-hack.devfolio.co/"><h3>Fake Hack</h3></a></div>'
    '<p class="badge">Online</p><p class="badge">Upcoming</p>'
    '<p class="badge">Opens 01/12/26</p>'
    "</div>"
)


def test_synthetic_card_without_starts_date_or_themes_stays_honest():
    (event,) = _parse(_SYNTHETIC_CARD)
    assert event.name == "Fake Hack"
    assert event.url == "https://fake-hack.devfolio.co/"
    assert event.mode == "online"
    assert event.status == "upcoming"
    assert event.start is None
    assert event.themes == []


def test_malformed_starts_date_stays_none_never_invented():
    # "31/02/26" is not a real date -> the badge is unusable, so start stays
    # None rather than raising or inventing a date.
    card = _SYNTHETIC_CARD.replace("Opens 01/12/26", "Starts 31/02/26")
    (event,) = _parse(card)
    assert event.name == "Fake Hack"
    assert event.start is None


def test_cards_without_name_or_url_are_skipped_not_faked():
    no_name = (
        '<div class="CompactHackathonCard__StyledCard-sc-abc x">'
        "<p>Online</p><p>Open</p></div>"
    )
    no_url = (
        '<div class="CompactHackathonCard__StyledCard-sc-abc x">'
        "<h3>No Anchor</h3><p>Online</p><p>Open</p></div>"
    )
    assert _parse(no_name + no_url) == []


def test_cards_without_mode_or_status_badges_are_skipped_not_guessed():
    no_mode = (
        '<div class="CompactHackathonCard__StyledCard-sc-abc x">'
        '<a href="https://a.devfolio.co/"><h3>A</h3></a><p>Open</p></div>'
    )
    no_status = (
        '<div class="CompactHackathonCard__StyledCard-sc-abc x">'
        '<a href="https://b.devfolio.co/"><h3>B</h3></a><p>Online</p></div>'
    )
    assert _parse(no_mode + no_status) == []


def test_non_string_payload_yields_no_events_instead_of_crashing():
    assert DevfolioAdapter().parse(None, _ctx()) == []


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
    result = DevfolioAdapter().fetch(_ctx(crawl=fake))
    assert result is HTML
    assert fake.calls == [LISTING_URL]


def test_listing_url_is_the_devfolio_hackathons_page():
    assert LISTING_URL == "https://devfolio.co/hackathons"


# --- registry, sources.yaml -------------------------------------------------


def test_registry_exposes_the_devfolio_adapter():
    adapter = ADAPTERS["devfolio"]
    assert isinstance(adapter, DevfolioAdapter)
    assert isinstance(adapter, Adapter)
    assert adapter.id == "devfolio"
    assert adapter.kind == "browser"
    assert set(ADAPTERS) == {a.id for a in ADAPTERS.values()}


def test_sources_yaml_registers_devfolio_as_browser_kind():
    entries = yaml.safe_load(SOURCES_YAML.read_text())
    devfolio = next(entry for entry in entries if entry["id"] == "devfolio")
    assert devfolio["kind"] == "browser"
    assert devfolio["enabled"] is True
    assert devfolio["url"] == "https://devfolio.co/hackathons"
    assert isinstance(devfolio["notes"], str) and devfolio["notes"].strip()


# --- fetch layer selectors (no network) -------------------------------------


def test_backend_defaults_to_crawl4ai(monkeypatch):
    monkeypatch.delenv("RADAR_FETCH_BACKEND", raising=False)
    assert fetch._backend() == "crawl4ai"


def test_backend_selects_playwright_when_env_set(monkeypatch):
    monkeypatch.setenv("RADAR_FETCH_BACKEND", "playwright")
    assert fetch._backend() == "playwright"


def test_pw_browsers_default_is_the_repo_symlink_tree():
    assert browser.PW_BROWSERS_DEFAULT == ROOT / ".pw-browsers"


def test_importing_browser_sets_playwright_browsers_path(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    importlib.reload(browser)
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(ROOT / ".pw-browsers")


def test_importing_browser_does_not_clobber_an_existing_path(monkeypatch, tmp_path):
    custom = str(tmp_path / "custom-pw")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", custom)
    importlib.reload(browser)
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == custom


def test_cloak_bin_env_override_is_readable_and_restores():
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("RADAR_CLOAK_BIN", "/tmp/other-chrome")
        importlib.reload(browser)
        assert browser.CLOAK_BIN == "/tmp/other-chrome"
    importlib.reload(browser)  # env restored -> back to the default binding
    assert browser.CLOAK_BIN == browser.DEFAULT_CLOAK_BIN


def test_ensure_pw_browsers_raises_when_tree_missing_or_incomplete(monkeypatch, tmp_path):
    missing = tmp_path / "missing"
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(missing))
    with pytest.raises(RuntimeError, match="provision_browsers.sh"):
        browser.ensure_pw_browsers()

    empty = tmp_path / "empty-pw"
    empty.mkdir()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(empty))
    with pytest.raises(RuntimeError, match="provision_browsers.sh"):
        browser.ensure_pw_browsers()


def test_ensure_pw_browsers_accepts_a_provisioned_tree(monkeypatch, tmp_path):
    tree = tmp_path / ".pw-browsers"
    (tree / "chromium-1243").mkdir(parents=True)
    (tree / "chromium-1243" / "INSTALLATION_COMPLETE").touch()
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tree))
    assert browser.ensure_pw_browsers() == tree


def test_fetch_page_dispatches_on_backend_without_network(monkeypatch):
    async def fake_crawl4ai(url):
        return f"c4ai:{url}"

    monkeypatch.setattr(fetch, "_fetch_crawl4ai", fake_crawl4ai)
    monkeypatch.setattr(fetch, "_fetch_playwright", lambda url: f"pw:{url}")

    monkeypatch.delenv("RADAR_FETCH_BACKEND", raising=False)
    assert fetch.fetch_page("https://example.test/x") == "c4ai:https://example.test/x"

    monkeypatch.setenv("RADAR_FETCH_BACKEND", "playwright")
    assert fetch.fetch_page("https://example.test/x") == "pw:https://example.test/x"


def test_fetch_module_does_not_import_crawl4ai_at_import_time():
    code = (
        "import sys, radar.browser, radar.fetch;"
        "assert 'crawl4ai' not in sys.modules, 'crawl4ai imported eagerly';"
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
