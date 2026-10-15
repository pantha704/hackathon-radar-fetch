"""Superteam Earn adapter — rendered listing page (kind: `browser`).

Live page: https://earn.superteam.fun/
Fixture: `tests/fixtures/superteam/listing.html` (real captured render, M0).

The homepage mixes listing types, and the radar tracks hackathons only:

- Bounty / Grant listings (20 in the fixture — 10 bounties + 10 grants —
  each carrying its own type-label element, e.g. ``<p class="hidden
  text-xs font-medium text-gray-500 sm:flex">Bounty</p>``): skipped. They
  are gigs/funding, not events. A listing that carries a "Hackathon" type
  label would be kept (the type-marker path; labelled listings are named
  from their own title and take precedence over the namespace markers when
  both match); the current capture contains none.
- Hackathon-type entries: kept. The page's own markers for these are
  (a) the hackathon route namespace — anchors linking into ``/earn/hackathon/``,
  and (b) the platform's hackathon asset namespace — anchors whose artwork
  lives under ``assets/hackathon/`` (this is what files "Next Stop
  Breakpoint" as a hackathon even though its custom route is not under
  ``/earn/hackathon/``).
- Each featured program appears three times on the page (nav strip, top
  hero, mid-page promo); candidates are deduplicated by resolved canonical
  URL, first occurrence wins. The fixture yields exactly two events:
  "Crypto World's Fair" and "Next Stop Breakpoint".

Honesty notes (all reflected in the task report):
- The listing page carries NO per-event mode/location and NO status marker
  for the featured programs. The model has no "unknown" mode/status, so the
  adapter writes two documented defaults rather than dropping the events:
  mode ``"online"`` — earn.superteam.fun is the Superteam global online earn
  platform: its programs are entered/submitted online from anywhere, and the
  page carries no per-event mode signal, so the platform-nature default
  "online" applies — and status ``"open"`` (featured programs are, by
  construction, the currently promoted hackathons — a finished one would
  not be featured with live click-through CTAs). Both are flagged for
  review.
- location / dates / prize / team / eligibility / cost: not on the featured
  cards -> None / []. The promo copy ("Deadline for submissions is 13 Oct",
  "$319,000+ in prizes") is deliberately NOT parsed: it is yearless
  marketing copy that disagrees across one program's three cards (the hero
  says "$197,000+", the promo "$319,000+").
"""

from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from radar.adapters.base import Adapter
from radar.fetch import fetch_page
from radar.models import Event, make_id

# Listing page backing https://earn.superteam.fun/.
LISTING_URL = "https://earn.superteam.fun/"

_SITE_BASE = "https://earn.superteam.fun"

# Route namespace of hackathon programs on the site.
_HACKATHON_PATH_PREFIX = "/earn/hackathon/"

# The platform files featured-hackathon artwork under `assets/hackathon/`
# (e.g. `.../assets/hackathon/next-stop-breakpoint/bp-mobile.png`).
_HACKATHON_ASSET_MARKER = "/hackathon/"

# Listing cards (bounties/grants/projects): the card is the anchor itself,
# matching `a.block.w-full.rounded-md`. The card's own type-label element
# (both variants seen in the fixture: bounties render it hidden on mobile,
# grants render it visible):
_LISTING_CARD_CLASSES = {"block", "w-full", "rounded-md"}
_TYPE_LABEL_SELECTOR = "p.text-xs.font-medium.text-gray-500"

_TYPE_HACKATHON = "hackathon"


class SuperteamAdapter(Adapter):
    """Adapter for the earn.superteam.fun homepage (hackathon entries only)."""

    id = "superteam"
    kind = "browser"

    def fetch(self, ctx: dict[str, Any]) -> Any:
        """Render the listing page and return its HTML.

        Uses `ctx["crawl"]` when the runner injects one, else the shared
        fetch layer (`radar.fetch.fetch_page`).
        """
        crawl = ctx.get("crawl") or fetch_page
        return crawl(LISTING_URL)

    def parse(self, payload: Any, ctx: dict[str, Any]) -> list[Event]:
        """Map the page's hackathon-type entries to Events (pure)."""
        now = ctx["now"]
        soup = BeautifulSoup(payload if isinstance(payload, str) else "", "html.parser")

        events: list[Event] = []
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href:
                # Empty/whitespace href: urljoin would yield the bare site
                # root and falsely pass the https:// identity check below.
                continue
            url, name = None, None
            # Type-labelled listings take precedence over the namespace
            # branch: a listing whose own label reads "Hackathon" is named
            # from its card title even when it also routes under
            # /earn/hackathon/ (not from image alt text).
            if _is_hackathon_labelled_listing(anchor):
                url = urljoin(_SITE_BASE, href)
                name = _listing_name(anchor)
            elif _is_hackathon_namespace(anchor):
                url = urljoin(_SITE_BASE, href)
                name = _featured_name(anchor)
            if url is None:
                continue
            if url in seen or not name or not url.startswith("https://"):
                continue
            seen.add(url)
            events.append(
                Event(
                    id=make_id(self.id, url),
                    name=name,
                    source=self.id,
                    url=url,
                    # Defaults per the module docstring: the page carries no
                    # per-event mode/status marker; "online" is the
                    # documented platform-nature default.
                    mode="online",
                    status="open",
                    first_seen=now,
                    last_seen=now,
                    extracted_by="css",
                )
            )
        return events


def _is_hackathon_namespace(anchor: Any) -> bool:
    """True when the anchor is a featured hackathon entry.

    Marker (a): the link target sits in the ``/earn/hackathon/`` route
    namespace. Marker (b): the anchor's artwork is filed under the
    platform's ``assets/hackathon/`` namespace.
    """
    if urlsplit(anchor["href"].strip()).path.startswith(_HACKATHON_PATH_PREFIX):
        return True
    for img in anchor.find_all("img"):
        for attr in (img.get("src"), img.get("srcset")):
            if attr and _HACKATHON_ASSET_MARKER in attr:
                return True
    return False


def _featured_name(anchor: Any) -> str:
    """Name of a featured hackathon entry.

    Preference order: image alt text (the nav logo carries the program's
    name), then aria-label/title, then the first heading, then the anchor
    text. Empty string when nothing usable exists (the card is skipped).
    """
    for img in anchor.find_all("img"):
        alt = (img.get("alt") or "").strip()
        if alt:
            return alt
    for attr in ("aria-label", "title"):
        value = (anchor.get(attr) or "").strip()
        if value:
            return value
    heading = anchor.find(["h1", "h2", "h3", "h4"])
    if heading is not None:
        text = heading.get_text(" ", strip=True)
        if text:
            return text
    return anchor.get_text(" ", strip=True)


def _is_hackathon_labelled_listing(anchor: Any) -> bool:
    """True when a listing card's own type label says "Hackathon"."""
    classes = set(anchor.get("class") or [])
    if not _LISTING_CARD_CLASSES.issubset(classes):
        return False
    label = anchor.select_one(_TYPE_LABEL_SELECTOR)
    return (
        label is not None
        and label.get_text(strip=True).casefold() == _TYPE_HACKATHON
    )


def _listing_name(anchor: Any) -> str:
    """Title of a hackathon-labelled listing card, or "" when absent."""
    title = anchor.select_one("p.line-clamp-1")
    return title.get_text(" ", strip=True) if title is not None else ""
