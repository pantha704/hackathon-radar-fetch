"""WeMakeDevs adapter — rendered homepage carousels (kind: `browser`).

Live page: https://wemakedevs.org/ (the "Explore Upcoming Hackathons" and
"Find a Local Meetup" carousels).
Fixture: `tests/fixtures/wemakedevs/listing.html` (real captured render, M0).

The homepage is a Next.js page; fetch it through the shared browser backend
(`radar.fetch`) and parse the captured card DOM (`extracted_by="css"`).
Selectors are the fixture's Tailwind vocabulary (3 hackathon cards + 1 meetup
card in the fixture):

- section : the carousel section containing the page's own
            "Explore Upcoming Hackathons" heading; cards of the "Find a
            Local Meetup" carousel are skipped as non-hackathons (the
            fixture's meetup card is pinned absent by tests)
- card    : ``a.block.border`` inside that section (3 in the fixture)
- name    : the card's ``h3``
- url     : the card href resolved against https://wemakedevs.org
            (relative ``/hackathons/<slug>`` paths; empty/fragment-only
            hrefs and non-https schemes are skipped)
- location: the map-pin chip text kept raw ("Hybrid", "Remote")
- mode    : from the same chip — ``Remote`` / ``Online`` / ``Virtual`` ->
            ``online``; ``Hybrid`` -> ``hybrid``; any other non-empty text
            names a physical venue -> ``offline``; empty -> card skipped
            (no honest mode signal, never guessed)
- prize   : the card's ``p.mt-2`` text kept raw ("$20,000 across three
            tracks")
- dates   : the calendar-range chip text ("Oct 8–11", "Sep 30 – Oct 31",
            "Oct 22") is yearless; the start-date year is read from the
            page's embedded RSC payload (``self.__next_f`` card records
            carry ISO ``startDate`` timestamps), matched by raw href. The
            DOM genuinely lacks the year, so the embedded JSON supplies
            exactly that one field (report note; the month/day remain
            DOM-derived). A cross-month range whose end precedes its start
            wraps into the next year ("Dec 30 – Jan 2"); a same-month
            inversion is malformed. Unresolvable dates stay None.

Honesty notes:
- Status: the card's own "Live" badge -> ``open`` (running now; same reading
  as lablab's LIVE badge). Without a badge it is derived from the card's own
  dates vs ``ctx["now"]`` (ended -> ``closed``, not started -> ``upcoming``,
  otherwise ``open``); when neither a badge nor dates exist the section's
  own "Upcoming Hackathons" heading is the fallback flag -> ``upcoming``
  (flagged for review, mirroring the ethglobal carousel fallback; the runner
  recomputes at run time).
- reg_deadline / team / themes / eligibility / cost are not on the cards, so
  they stay None / [] — never invented.
"""

import json
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from radar.adapters.base import Adapter
from radar.fetch import fetch_page
from radar.models import Event, make_id

# Listing page backing https://wemakedevs.org/.
LISTING_URL = "https://wemakedevs.org/"

_SITE_BASE = "https://wemakedevs.org"

# The page's own heading for the hackathon carousel.
_HACKATHON_HEADING = "Explore Upcoming Hackathons"

# Card anchor inside the hackathon carousel section (3 in the fixture).
_CARD_SELECTOR = "a.block.border"

# The card's status badge ("Live") — the fixture's exact positioning classes;
# the 4 empty corner ornaments do not carry them.
_BADGE_SELECTOR = "div.absolute.bottom-2.left-2.z-10"

# Chip icons: the map-pin chip carries the location, the calendar-range chip
# the displayed date range.
_LOCATION_ICON = "svg.lucide-map-pin"
_DATE_ICON = "svg.lucide-calendar-range"

# Status badge vocabulary (exact text, case-insensitive).
_STATUS_BADGES = {"live": "open"}

# Location texts that read as digital/online or hybrid. Anything else
# non-empty is a physical location -> offline; empty -> skip.
_MODE_BY_LOCATION = {
    "remote": "online",
    "online": "online",
    "virtual": "online",
    "hybrid": "hybrid",
}

# Fallback status when neither a badge nor dates exist (flagged; see the
# module docstring).
_DEFAULT_STATUS = "upcoming"

# Displayed range, e.g. "Oct 8–11" / "Sep 30 – Oct 31" / "Oct 22".
_DATE_RANGE_RE = re.compile(
    r"^([A-Za-z]{3,9})\s+(\d{1,2})\s*[–—-]\s*(?:([A-Za-z]{3,9})\s+)?(\d{1,2})$"
)
_DATE_SINGLE_RE = re.compile(r"^([A-Za-z]{3,9})\s+(\d{1,2})$")

# RSC payload fragments: self.__next_f.push([1,"<js-string>"]) — decoded via
# json.loads, then the card records' href -> startDate year are read off.
_RSC_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_RSC_CARD_RE = re.compile(
    r'"href":"([^"]+)","isExternal":(?:true|false),"startDate":"(\d{4})-\d{2}-\d{2}T'
)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class WemakedevsAdapter(Adapter):
    """Adapter for the wemakedevs.org homepage hackathon carousel."""

    id = "wemakedevs"
    kind = "browser"

    def fetch(self, ctx: dict[str, Any]) -> Any:
        """Render the homepage and return its HTML.

        Uses `ctx["crawl"]` when the runner injects one, else the shared
        fetch layer (`radar.fetch.fetch_page`).
        """
        crawl = ctx.get("crawl") or fetch_page
        return crawl(LISTING_URL)

    def parse(self, payload: Any, ctx: dict[str, Any]) -> list[Event]:
        """Map hackathon cards to Events (pure: payload + ctx only)."""
        now = ctx["now"]
        soup = BeautifulSoup(payload if isinstance(payload, str) else "", "html.parser")
        section = _hackathon_section(soup)
        if section is None:
            return []
        years = _rsc_years(soup)

        events: list[Event] = []
        for card in section.select(_CARD_SELECTOR):
            name = _text(card.find("h3"))
            href = (card.get("href") or "").strip()
            url = _resolve_url(_SITE_BASE, href)
            if not name or not url.startswith("https://"):
                continue  # no identity -> cannot build a valid Event; skip

            location = _chip_text(card, _LOCATION_ICON)
            mode = _MODE_BY_LOCATION.get(location.lower()) if location else None
            if mode is None:
                if not location:
                    continue  # no location -> no honest mode signal; skip
                mode = "offline"  # a physical venue is named

            start, end = _parse_range(_chip_text(card, _DATE_ICON), years.get(href))
            status = _STATUS_BADGES.get(_text(card.select_one(_BADGE_SELECTOR)).lower())
            if status is None:
                status = (
                    _status_for(start, end, now.date())
                    if start is not None
                    else _DEFAULT_STATUS
                )

            prize_el = card.select_one("p.mt-2")
            events.append(
                Event(
                    id=make_id(self.id, url),
                    name=name,
                    source=self.id,
                    url=url,
                    mode=mode,
                    status=status,
                    first_seen=now,
                    last_seen=now,
                    extracted_by="css",
                    location=location,
                    start=start,
                    end=end,
                    prize=_text(prize_el) or None,
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


def _hackathon_section(soup: BeautifulSoup) -> Any:
    """The section wrapping the page's hackathon-carousel heading, or None."""
    for heading in soup.find_all("h2"):
        if _text(heading).startswith(_HACKATHON_HEADING):
            return heading.find_parent("section")
    return None


def _chip_text(card: Any, icon_selector: str) -> str:
    """Text of the meta chip whose icon matches ``icon_selector``."""
    icon = card.select_one(icon_selector)
    if icon is None:
        return ""
    return _text(icon.find_parent("div"))


def _rsc_years(soup: BeautifulSoup) -> dict[str, int]:
    """Raw card href -> start-date year from the embedded RSC payload.

    The DOM's date chips are yearless, so this one field comes from the
    page's own React-server payload (decoded ``self.__next_f.push`` string
    fragments). First occurrence wins; malformed fragments are ignored.
    """
    fragments: list[str] = []
    for script in soup.find_all("script"):
        for match in _RSC_PUSH_RE.finditer(script.string or ""):
            try:
                fragments.append(json.loads(match.group(1)))
            except json.JSONDecodeError:
                continue
    payload = "".join(fragments)
    years: dict[str, int] = {}
    for match in _RSC_CARD_RE.finditer(payload):
        years.setdefault(match.group(1), int(match.group(2)))
    return years


def _parse_range(text: str, year: int | None) -> tuple[date | None, date | None]:
    """Parse "MMM D – D" / "MMM D – MMM D" / "MMM D" with ``year`` into dates.

    Returns ``(None, None)`` when the text is malformed, unclear, or the
    year is unknown. A cross-month range whose end precedes its start wraps
    into the next year (e.g. "Dec 30 – Jan 2"); a same-month inversion is
    malformed. A single-day chip collapses start == end.
    """
    if year is None:
        return None, None
    text = text.strip()
    match = _DATE_RANGE_RE.match(text)
    if match is not None:
        month1, day1, month2, day2 = match.groups()
        start_month = _MONTHS.get(month1[:3].lower())
        end_month = _MONTHS.get((month2 or month1)[:3].lower())
        if start_month is None or end_month is None:
            return None, None
        try:
            start = date(year, start_month, int(day1))
            end = date(year, end_month, int(day2))
        except ValueError:
            return None, None
        if end < start:
            if end_month < start_month:
                # Cross-year wrap: the end lands in the next year.
                try:
                    end = date(year + 1, end_month, int(day2))
                except ValueError:
                    return None, None
            else:
                # Same-month range whose end precedes its start: malformed.
                return None, None
        return start, end
    match = _DATE_SINGLE_RE.match(text)
    if match is not None:
        month1, day1 = match.groups()
        month = _MONTHS.get(month1[:3].lower())
        if month is None:
            return None, None
        try:
            start = date(year, month, int(day1))
        except ValueError:
            return None, None
        return start, start
    return None, None


def _status_for(start: date, end: date | None, today: date) -> str:
    """Derive status from the card's own dates vs the run date (mlh ruling)."""
    if end is not None and end < today:
        return "closed"
    if start > today:
        return "upcoming"
    return "open"
