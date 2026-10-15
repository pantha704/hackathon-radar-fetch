"""Hack Club adapter — rendered hackathon listing (kind: `browser`).

Live page: https://hackathons.hackclub.com/ (the high-school hackathon
listing).
Fixture: `tests/fixtures/hackclub/listing.html` (real captured render, M0).

The listing is a server-rendered React page; fetch it through the shared
browser backend (`radar.fetch`) and parse the captured card DOM
(`extracted_by="css"`). Every card is annotated with schema.org Event
microdata, so the selectors are the microdata properties (120 cards in the
fixture):

- card     : ``a[itemtype="http://schema.org/Event"]``
- name     : ``[itemprop="name"]`` (the card's ``h3``)
- url      : the card anchor href resolved against
             https://hackathons.hackclub.com (empty/fragment-only hrefs and
             non-https schemes are skipped; the fixture also carries 3
             http-only links, which the shared https identity rule skips —
             an honest, reported skip)
- mode     : the card's own badge (the first direct-child ``span``) —
             ``Online`` -> ``online``, ``In-Person`` -> ``offline``,
             ``Hybrid`` -> ``hybrid``; unknown/missing -> card skipped,
             never guessed. (The microdata ``eventAttendanceMode`` collapses
             Hybrid to Offline, so the badge is the precise mode signal.)
- location : the ``[itemprop="address"]`` text kept raw ("San Francisco,
             California"), with the page's leading ":" separator stripped;
             online cards and ":"-only addresses -> None
- dates    : the ``[itemprop="startDate"]`` / ``[itemprop="endDate"]``
             microdata spans' ISO ``content`` instants (the page's own
             machine-readable annotation; UTC date part, as displayed) —
             a card without both, or with an end before its start, is
             skipped, never guessed
- status   : the cards carry no status badge; it is derived from the card's
             own dates vs ``ctx["now"]`` exactly like the mlh adapter
             (ended -> ``closed``, not started -> ``upcoming``, otherwise
             ``open``; a card ending today is still ``open``)

Cards are deduplicated by resolved URL, first occurrence wins (the listing
is newest-first, so the newest edition of a repeated URL is kept — the
ethglobal ruling). The fixture's 120 cards reduce to 108 events: 9 later
editions of 8 duplicate-URL pairs (one URL has three cards) plus the 3
http-only links. Both counts are pinned by tests and reported.

Honesty notes:
- The cards carry no prize / themes / registration deadline / team /
  eligibility / cost, so those fields stay None / [] — never invented.
- The page's own "913 events in 31 states + 26 countries" counter covers a
  larger catalogue than this capture's 120 rendered cards; only the cards
  actually present are parsed.
"""

from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from radar.adapters.base import Adapter
from radar.fetch import fetch_page
from radar.models import Event, make_id

# Listing page backing https://hackathons.hackclub.com/.
LISTING_URL = "https://hackathons.hackclub.com/"

_SITE_BASE = "https://hackathons.hackclub.com"

# Card container: the page's own schema.org Event annotation (120 in the
# fixture).
_CARD_SELECTOR = 'a[itemtype="http://schema.org/Event"]'

# Badge vocabulary (exact text, case-insensitive). Unknown -> card skipped.
_MODE_BADGES = {"online": "online", "in-person": "offline", "hybrid": "hybrid"}


class HackclubAdapter(Adapter):
    """Adapter for the hackathons.hackclub.com listing page."""

    id = "hackclub"
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
        seen: set[str] = set()
        for card in soup.select(_CARD_SELECTOR):
            name = _text(card.find(attrs={"itemprop": "name"}))
            url = _resolve_url(_SITE_BASE, card.get("href"))
            if not name or not url.startswith("https://"):
                continue  # no identity -> cannot build a valid Event; skip

            badge = _text(card.find("span", recursive=False))
            mode = _MODE_BADGES.get(badge.lower())
            if mode is None:
                continue  # unknown/missing mode badge; skip, never guess

            start = _iso_date(card.find(attrs={"itemprop": "startDate"}))
            end = _iso_date(card.find(attrs={"itemprop": "endDate"}))
            if start is None or end is None or end < start:
                continue  # no honest dates/status; skip, never guess

            if url in seen:
                continue  # first occurrence wins (newest-first listing)
            seen.add(url)

            events.append(
                Event(
                    id=make_id(self.id, url),
                    name=name,
                    source=self.id,
                    url=url,
                    mode=mode,
                    status=_status_for(start, end, now.date()),
                    first_seen=now,
                    last_seen=now,
                    extracted_by="css",
                    location=_location(card),
                    start=start,
                    end=end,
                )
            )
        return events


def _text(element: Any) -> str:
    """Visible text of an element: raw node text, whitespace collapsed."""
    if element is None:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def _resolve_url(base: str, href: Any) -> str:
    """Resolve a card href against ``base``; ``""`` when it is not usable.

    Empty/whitespace hrefs and fragment-only hrefs ("#", "#x") resolve to the
    bare site root and would falsely pass the ``https://`` identity check, so
    they are rejected before urljoin (T8 hardening). Non-https schemes
    ("javascript:") fail the caller's identity check.
    """
    raw = (href or "").strip() if isinstance(href, str) else ""
    if not raw or raw.startswith("#"):
        return ""
    return urljoin(base, raw)


def _iso_date(element: Any) -> date | None:
    """Date part of a microdata ISO instant (``content`` attr, else text).

    ``None`` when absent or malformed — never guessed.
    """
    if element is None:
        return None
    raw = (element.get("content") or _text(element) or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _location(card: Any) -> str | None:
    """Raw address text with the page's leading ":" separator stripped.

    The listing renders the separator inside the address span (": San
    Francisco, California"); an address that is only the separator (or
    absent, as on online cards) -> None.
    """
    address = card.find(attrs={"itemprop": "address"})
    if address is None:
        return None
    text = _text(address).removeprefix(":").strip()
    return text or None


def _status_for(start: date, end: date | None, today: date) -> str:
    """Derive status from the card's own dates vs the run date (mlh ruling)."""
    if end is not None and end < today:
        return "closed"
    if start > today:
        return "upcoming"
    return "open"
