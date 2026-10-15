"""lablab.ai adapter — rendered listing page (kind: `browser`).

Live page: https://lablab.ai/event (the AI-hackathon listing).
Fixture: `tests/fixtures/lablab/listing.html` (real captured render, M0).

The listing is a client-rendered Next.js page; fetch it through the shared
browser backend (`radar.fetch`) and parse the captured card DOM
(`extracted_by="css"`). Selectors (fixture-derived; 12 cards in the fixture):

- card      : ``div.card-animation``
- name      : the card's ``h2``
- url       : the card's wrapping anchor href — relative
              ``/ai-hackathons/<slug>`` paths are resolved against
              https://lablab.ai; empty/fragment-only hrefs are skipped
              (urljoin would otherwise pin the event to the listing page)
- start     : the ``<time datetime="...">`` attribute (ISO instant; its date
              part is taken as displayed by the page), never a guess
- end       : the displayed range (e.g. ``"SEP 1 - DEC 1"``) parsed with the
              datetime attribute's year; a range that ends before it starts
              wraps into the next year only when its end month is strictly
              earlier than the start month (``"DEC 28 - JAN 5"``) — a
              same-month inversion (``"JUN 30 - JUN 5"``) is malformed; a
              display whose start disagrees with the datetime is untrusted and
              leaves ``end`` None — dates are never invented
- status    : the top-left badge — ``LIVE`` -> ``open`` (running now),
              ``Register`` -> ``open`` (registration is currently open; the
              badge is the page's own live register CTA, mirroring the
              devfolio "Open" reading: a registerable event whose start is
              still in the future — flagged for review), ``Finished`` ->
              ``closed``; unknown/missing badge -> card skipped
- mode      : the top-right badge — ``Online`` -> ``online``, ``Hybrid`` ->
              ``hybrid``, ``On-site`` -> ``offline``; unknown/missing -> card
              skipped

Honesty notes:
- The cards carry no location, prize, themes, registration deadline, team,
  eligibility or cost, so those fields stay None / [] — never invented.
- The embedded hydration JSON blob (a React server payload listing many past
  events with raw fields) is deliberately NOT parsed: the DOM path above is
  the sanctioned extraction for this adapter and covers every field it
  writes (same choice as devfolio/mlh).
"""

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from radar.adapters.base import Adapter
from radar.fetch import fetch_page
from radar.models import Event, make_id

# Listing page backing https://lablab.ai/event.
LISTING_URL = "https://lablab.ai/event"

_SITE_BASE = "https://lablab.ai"

# Card container (12 cards in the fixture).
_CARD_SELECTOR = "div.card-animation"

# Status badge (top-left) and mode badge (top-right) — the fixture's exact
# positioning classes; the pulsing LIVE dot spans carry no positioning class
# and are not matched.
_STATUS_BADGE_SELECTOR = "span.absolute.left-2.top-2"
_MODE_BADGE_SELECTOR = "span.absolute.right-2.top-2"

# Badge vocabulary (exact text, case-insensitive). Unknown -> card skipped.
_STATUS_BADGES = {"live": "open", "register": "open", "finished": "closed"}
_MODE_BADGES = {"online": "online", "hybrid": "hybrid", "on-site": "offline"}

# Displayed range, e.g. "SEP 1 - DEC 1" / "SEP 25 - 27" / "OCT 12".
_DATE_RANGE_RE = re.compile(
    r"^([A-Za-z]{3})\s+(\d{1,2})(?:\s*-\s*(?:([A-Za-z]{3})\s+)?(\d{1,2}))?$"
)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class LablabAdapter(Adapter):
    """Adapter for the lablab.ai event listing page."""

    id = "lablab"
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
            name = _text(card.find("h2"))
            anchor = card.find("a")
            url = _resolve_url(_SITE_BASE, anchor.get("href") if anchor else None)
            if not name or not url.startswith("https://"):
                continue  # no identity -> cannot build a valid Event; skip

            status = _first_mapped(
                [_text(card.select_one(_STATUS_BADGE_SELECTOR))], _STATUS_BADGES
            )
            mode = _first_mapped(
                [_text(card.select_one(_MODE_BADGE_SELECTOR))], _MODE_BADGES
            )
            if status is None or mode is None:
                continue  # cannot assert status/mode honestly; skip, never guess

            start, end = _parse_dates(card)
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
                    start=start,
                    end=end,
                )
            )
        return events


def _text(element: Any) -> str:
    """Visible text of an element: raw node text, whitespace collapsed.

    ``get_text("", strip=False)`` keeps the page's own spacing (the React
    comment nodes split some text runs); the final collapse normalizes
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


def _first_mapped(texts: list[str], table: dict[str, str]) -> str | None:
    """First text that maps through ``table`` (case-insensitive), else None."""
    for text in texts:
        mapped = table.get(text.strip().lower())
        if mapped is not None:
            return mapped
    return None


def _parse_dates(card: Any) -> tuple[date | None, date | None]:
    """Parse the card's own ``<time datetime>`` + displayed range.

    The datetime attribute is the only place the year appears; the display
    range supplies the end day. Both are required to agree on the start day,
    otherwise the display is untrusted and only the datetime's start stands.
    A display that ends before it starts wraps into the next year only when
    its end month is strictly earlier than the start month; a same-month
    inversion leaves ``end`` None.
    """
    time_el = card.find("time")
    raw = (time_el.get("datetime") or "").strip() if time_el is not None else ""
    start = None
    if raw:
        try:
            start = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            start = None  # malformed instant -> honestly unknown, never invented
    if start is None:
        return None, None

    match = _DATE_RANGE_RE.match(_text(time_el))
    if match is None:
        return start, None
    month1, day1, month2, day2 = match.groups()
    start_month = _MONTHS.get(month1.lower())
    if start_month is None:
        return start, None
    try:
        range_start = date(start.year, start_month, int(day1))
    except ValueError:
        return start, None
    if range_start != start:
        return start, None  # display disagrees with the datetime -> untrusted
    if day2 is None:
        return start, start  # single-day display collapses start == end
    end_month = _MONTHS.get((month2 or month1).lower())
    if end_month is None:
        return start, None
    try:
        end = date(start.year, end_month, int(day2))
    except ValueError:
        return start, None
    if end < start:
        if end_month < start_month:
            # Cross-year wrap ("DEC 28 - JAN 5"): a strictly earlier end month
            # rolls the end into the next year.
            try:
                end = date(start.year + 1, end_month, int(day2))
            except ValueError:
                return start, None
        else:
            # Same-month inversion ("JUN 30 - JUN 5" / "JUN 30 - 5"): no
            # earlier month to wrap into -> the display is malformed, so end
            # stays honestly unknown.
            return start, None
    return start, end
