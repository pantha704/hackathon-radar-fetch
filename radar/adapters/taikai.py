"""TAIKAI adapter — rendered listing page (kind: `browser`).

Live page: https://taikai.network/hackathons (the public hackathon listing).
Fixture: `tests/fixtures/taikai/listing.html` (real captured render, M0).

The listing is a client-rendered Next.js page; fetch it through the shared
browser backend (`radar.fetch`) and parse the captured card DOM
(`extracted_by="css"`). Selectors (fixture-derived; 20 cards in the fixture):

- card   : ``div[data-public="true"]`` — the page's own marker for publicly
           listed hackathons (exactly the 20 cards in the fixture)
- name   : the card's ``h3``
- url    : the card's wrapping anchor href — relative
           ``/en/<org>/hackathons/<slug>/`` paths are resolved against
           https://taikai.network; empty/fragment-only hrefs are skipped
- state  : the cover's state element text, mapped by the platform's phase
           vocabulary (case-insensitive): ``Registration`` /
           ``Registrations open`` / ``Inscrições`` -> ``open`` (registration
           currently open, same reading as lablab's "Register" badge);
           ``Finished`` -> ``closed``; ``Award Ceremony`` -> ``closed`` (the
           submissions/judging are over and the event is in its final
           ceremony phase — not actionable; flagged for review, since the
           element's ``data-ended`` attribute is still ``false`` there).
           Unknown/missing state -> card skipped, never guessed
- prize  : the prize block's value kept raw exactly as displayed
           (``"3,500$"``, ``"9,000€"``); no prize block -> None
- themes : the tag spans, in card order

Mode (documented platform-nature default, flagged for review):
- The cards carry NO per-card mode/location. taikai.network is a hackathon
  platform whose own ld+json self-description on this page reads "Host online,
  virtual hackathons and open innovation challenges"; participation
  (registration, submission, judging) happens on the platform online. With no
  per-event mode signal the adapter therefore applies the documented
  platform-nature default ``mode="online"`` (same class of ruling as the
  superteam default) and leaves ``location`` None. Two cards' freeform
  descriptions happen to mention a venue ("Valencia, 6 - 8 October - Online
  participation possible") — deliberately NOT parsed: inconsistent marketing
  copy is not a mode signal (same stance as the dorahacks countdown).

Honesty notes:
- The cards carry no calendar dates. The only temporal text is an unlabeled
  countdown ("18 days left") to a deadline nothing on the card names, so it is
  NOT mapped to any date field (dorahacks ruling): start / end / reg_deadline
  stay None.
- The participant/project counters and the description copy are not Event
  fields -> not mapped.
"""

from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from radar.adapters.base import Adapter
from radar.fetch import fetch_page
from radar.models import Event, make_id

# Listing page backing https://taikai.network/hackathons.
LISTING_URL = "https://taikai.network/hackathons"

_SITE_BASE = "https://taikai.network"

# Card container: the page's own public-listing marker (20 cards in the
# fixture; private/draft entries would carry data-public="false").
_CARD_SELECTOR = 'div[data-public="true"]'

# The cover state badge, e.g. <div class="styles-module__…__state"
# data-ended="false">Registration</div>.
_STATE_SELECTOR = '[class*="__state"]'

# State vocabulary (exact text, case-insensitive). Unknown -> card skipped.
_STATE_STATUSES = {
    "registration": "open",
    "registrations open": "open",
    "inscrições": "open",  # the platform's pt label for the same phase
    "finished": "closed",
    "award ceremony": "closed",
}

# Platform-nature default: no per-card mode/location signal exists (see the
# module docstring).
_DEFAULT_MODE = "online"


class TaikaiAdapter(Adapter):
    """Adapter for the taikai.network hackathon listing page."""

    id = "taikai"
    kind = "browser"

    def fetch(self, ctx: dict[str, Any]) -> Any:
        """Render the listing page and return its HTML.

        Uses `ctx["crawl"]` when the runner injects one, else the shared
        fetch layer (`radar.fetch.fetch_page`).
        """
        crawl = ctx.get("crawl") or fetch_page
        return crawl(LISTING_URL)

    def parse(self, payload: Any, ctx: dict[str, Any]) -> list[Event]:
        """Map listing cards to Events (pure: payload + ctx only)."""
        now = ctx["now"]
        soup = BeautifulSoup(payload if isinstance(payload, str) else "", "html.parser")
        events: list[Event] = []
        for card in soup.select(_CARD_SELECTOR):
            name = _text(card.find("h3"))
            anchor = card.find("a")
            url = _resolve_url(_SITE_BASE, anchor.get("href") if anchor else None)
            if not name or not url.startswith("https://"):
                continue  # no identity -> cannot build a valid Event; skip

            state = _text(card.select_one(_STATE_SELECTOR))
            status = _STATE_STATUSES.get(state.lower())
            if status is None:
                continue  # unknown phase vocabulary; skip, never guess

            events.append(
                Event(
                    id=make_id(self.id, url),
                    name=name,
                    source=self.id,
                    url=url,
                    mode=_DEFAULT_MODE,
                    status=status,
                    first_seen=now,
                    last_seen=now,
                    extracted_by="css",
                    prize=_prize(card),
                    themes=[
                        _text(span) for span in card.select('[class*="__tags"] span')
                    ],
                )
            )
        return events


def _text(element: Any) -> str:
    """Visible text of an element: raw node text, whitespace collapsed.

    ``get_text("", strip=False)`` keeps the page's own spacing (React comment
    nodes split some text runs); the final collapse normalizes
    newlines/indentation only.
    """
    if element is None:
        return ""
    return " ".join(element.get_text("", strip=False).split())


def _resolve_url(base: str, href: Any) -> str:
    """Resolve a card href against ``base``; ``""`` when it is not usable.

    Empty/whitespace hrefs and fragment-only hrefs ("#", "#x") resolve to the
    bare site root and would falsely pass the ``https://`` identity check, so
    they are rejected before urljoin (T8 hardening).
    """
    raw = (href or "").strip() if isinstance(href, str) else ""
    if not raw or raw.startswith("#"):
        return ""
    return urljoin(base, raw)


def _prize(card: Any) -> str | None:
    """Raw prize value (``"3,500$"``) from the prize block, or None."""
    block = card.select_one('[class*="__prize"]')
    if block is None:
        return None
    value = block.find("div")
    text = _text(value)
    return text or None
