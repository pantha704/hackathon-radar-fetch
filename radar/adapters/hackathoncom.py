"""hackathon.com adapter — rendered homepage highlights (kind: `browser`).

Live page: https://www.hackathon.com/ (the homepage highlights carousel).
Fixture: `tests/fixtures/hackathoncom/listing.html` (real captured render, M0).

The homepage is server-rendered; fetch it through the shared browser backend
(`radar.fetch`) and parse the captured hero DOM (`extracted_by="css"`).
Selectors are the page's own block-class vocabulary (4 featured events in the
fixture):

- card       : ``div.hero`` (4 in the fixture: 1 ``hero active`` + 3 ``hero``)
- name / url : ``.hero__title`` anchor text + href (relative ``/event/...``
               paths resolved against https://www.hackathon.com)
- themes     : ``.ht-event-topics__tag`` texts, in card order
- location   : ``.hero__key-info__location`` kept raw ("Online")
- mode       : from the same location line — ``Online`` / ``Virtual`` ->
               ``online``; any other non-empty location names a physical
               venue -> ``offline``; empty location -> card skipped (no
               honest mode signal, never guessed). The topic pills
               (``Virtual`` / ``Hybrid``) are NOT mode signals — they are
               themes (the Huawei hero is tagged "Hybrid" while its own
               location line reads "Online").
- dates      : ``.hero__key-info__date`` ("Starts 02 Nov Ends 02 Dec" — no
               year on the hero). The year comes from the highlights nav
               row (``.ht-highlights__item``), which shows the same event's
               start date with its year ("2nd November 2026"); entries are
               matched to heroes by exact name. The hero range is
               authoritative for day/month; the nav supplies the year only.
               Cross-month ranges whose end precedes their start wrap into
               the next year ("Starts 30 Dec Ends 02 Jan"); a same-month
               inversion is malformed. A card without a parseable range or
               without a matching highlights year is skipped — without
               dates its status could not be derived honestly (the heroes
               carry no status badge; never guessed).

Honesty notes:
- Status is derived from the hero's own dates vs ``ctx["now"]`` (ended ->
  ``closed``, not started -> ``upcoming``, otherwise ``open``), like the mlh
  adapter. At the M0 capture (2026-10-09) that is 1 ``open`` + 3
  ``upcoming``.
- reg_deadline / prize / team / eligibility / cost are not on the heroes, so
  they stay None / [] — never invented.
- The embedded ``$MC`` hydration JSON (per-event ``type`` / ``online`` /
  ``venue`` fields) is deliberately NOT parsed: the DOM path above covers
  every field this adapter writes. One fixture hero (IBM Z Day 2026) is
  tagged ``eventType: "Event"`` in that JSON while the other three are
  ``Hackathon`` — the DOM presents all four uniformly as featured heroes
  (no DOM-level type marker exists), so all four are kept; flagged in the
  task report.
"""

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from radar.adapters.base import Adapter
from radar.fetch import fetch_page
from radar.models import Event, make_id

# Listing page backing https://www.hackathon.com/.
LISTING_URL = "https://www.hackathon.com/"

_SITE_BASE = "https://www.hackathon.com"

# Hero card (4 in the fixture).
_CARD_SELECTOR = "div.hero"

# Highlights-nav entries carrying the year ("2nd November 2026").
_HIGHLIGHT_ITEM_SELECTOR = ".ht-highlights__item"

# Location lines that read as digital/online. Anything else non-empty is a
# physical location -> offline; empty -> skip (no mode signal).
_ONLINE_LOCATIONS = {"online", "virtual"}

# Hero date line: "Starts 02 Nov Ends 02 Dec" / "Starts 09 Oct".
_DATE_RANGE_RE = re.compile(
    r"^Starts\s+(\d{1,2})\s+([A-Za-z]{3,9})"
    r"(?:\s+Ends\s+(\d{1,2})\s+([A-Za-z]{3,9}))?$",
    re.IGNORECASE,
)

# Highlights-nav date: "2nd November 2026".
_HIGHLIGHT_DATE_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]{3,9})\s+(\d{4})$")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class HackathoncomAdapter(Adapter):
    """Adapter for the hackathon.com homepage highlights carousel."""

    id = "hackathoncom"
    kind = "browser"

    def fetch(self, ctx: dict[str, Any]) -> Any:
        """Render the homepage and return its HTML.

        Uses `ctx["crawl"]` when the runner injects one, else the shared
        fetch layer (`radar.fetch.fetch_page`).
        """
        crawl = ctx.get("crawl") or fetch_page
        return crawl(LISTING_URL)

    def parse(self, payload: Any, ctx: dict[str, Any]) -> list[Event]:
        """Map featured heroes to Events (pure: payload + ctx only)."""
        now = ctx["now"]
        soup = BeautifulSoup(payload if isinstance(payload, str) else "", "html.parser")
        years = _highlight_years(soup)

        events: list[Event] = []
        for card in soup.select(_CARD_SELECTOR):
            title = card.select_one(".hero__title")
            name = _text(title)
            url = _resolve_url(_SITE_BASE, title.get("href") if title else None)
            if not name or not url.startswith("https://"):
                continue  # no identity -> cannot build a valid Event; skip

            location = _text(card.select_one(".hero__key-info__location"))
            mode = _mode_for(location)
            if mode is None:
                continue  # no location -> no honest mode signal; skip

            year = years.get(name)
            if year is None:
                continue  # no year -> no honest dates/status; skip
            start, end = _parse_range(_text(card.select_one(".hero__key-info__date")), year)
            if start is None:
                continue  # no honest dates/status; skip, never guess

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
                    location=location,
                    start=start,
                    end=end,
                    themes=[
                        _text(tag) for tag in card.select(".ht-event-topics__tag")
                    ],
                )
            )
        return events


def _text(element: Any) -> str:
    """Visible text of an element: raw node text, whitespace collapsed."""
    if element is None:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def _resolve_url(base: str, href: Any) -> str:
    """Resolve a hero href against ``base``; ``""`` when it is not usable.

    Empty/whitespace hrefs and fragment-only hrefs ("#", "#x") resolve to the
    bare site root and would falsely pass the ``https://`` identity check, so
    they are rejected before urljoin (T8 hardening). Non-https schemes
    ("javascript:") fail the caller's identity check.
    """
    raw = (href or "").strip() if isinstance(href, str) else ""
    if not raw or raw.startswith("#"):
        return ""
    return urljoin(base, raw)


def _mode_for(location: str) -> str | None:
    """Mode for a location line: online for digital texts, offline otherwise.

    ``None`` only when the location is empty (no honest mode signal).
    """
    if not location:
        return None
    return "online" if location.lower() in _ONLINE_LOCATIONS else "offline"


def _highlight_years(soup: BeautifulSoup) -> dict[str, int]:
    """Event name -> start-date year from the highlights nav row.

    The heroes' own date lines are yearless; the nav row for the same event
    ("2nd November 2026") carries the year. First occurrence wins.
    """
    years: dict[str, int] = {}
    for item in soup.select(_HIGHLIGHT_ITEM_SELECTOR):
        name = _text(item.select_one(".ht-highlights__item__name"))
        match = _HIGHLIGHT_DATE_RE.match(_text(item.select_one(".ht-highlights__item__date")))
        if name and match:
            years.setdefault(name, int(match.group(3)))
    return years


def _parse_range(text: str, year: int) -> tuple[date | None, date | None]:
    """Parse "Starts D MMM Ends D MMM" with ``year`` into dates.

    Returns ``(None, None)`` when the line is malformed or unclear. A
    cross-month range whose end precedes its start wraps into the next year
    (e.g. "Starts 30 Dec Ends 02 Jan"); a same-month range whose end
    precedes its start is malformed and also returns ``(None, None)``; a
    "Starts D MMM" line without "Ends" collapses start == end.
    """
    match = _DATE_RANGE_RE.match(text.strip())
    if match is None:
        return None, None
    day1, month1, day2, month2 = match.groups()
    start_month = _MONTHS.get(month1[:3].lower())
    if start_month is None:
        return None, None
    try:
        start = date(year, start_month, int(day1))
    except ValueError:
        return None, None
    if day2 is None:
        return start, start
    end_month = _MONTHS.get(month2[:3].lower())
    if end_month is None:
        return None, None
    try:
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


def _status_for(start: date, end: date | None, today: date) -> str:
    """Derive status from the hero's own dates vs the run date (mlh ruling)."""
    if end is not None and end < today:
        return "closed"
    if start > today:
        return "upcoming"
    return "open"
