"""MLH season-page adapter — rendered listing page (kind: `browser`).

Live page: https://mlh.io/seasons/2026/events (the 2026-season schedule).
Fixture: `tests/fixtures/mlh/listing.html` (real captured render, M0).

The page is client-rendered; fetch it through the shared browser backend
(`radar.fetch`) and parse the captured card DOM (`extracted_by="css"`).
Selectors are the Tailwind utility-class vocabulary of the captured page
(the cards carry no semantic class names):

- card       : ``div.rounded-card`` (24 in the fixture)
- name       : the card's ``h4``
- canonical  : the URL of the card's wrapping anchor (``<a>``), with the
               ``utm_*`` campaign parameters stripped — the raw href carries
               mlh tracking tags, and stripping them keeps ids stable across
               captures
- date range : first info row, e.g. ``"JUN 12 - 14"`` (month/day only)
- location   : second info row, kept raw exactly as displayed
- mode       : the mode badge — ``"Digital"`` -> ``online``,
               ``"In-Person"`` -> ``offline``; cards without a recognised
               badge are skipped, never guessed

Honesty notes:
- The cards carry no status badge; status is derived from the page's own
  date range (plus the season year from the page title, e.g. "2026 Season
  Schedule") against ``ctx["now"]``: ended -> ``closed``, not started ->
  ``upcoming``, otherwise ``open``. The season year comes from the page
  payload, never a constant (the spare 2025 capture parses the same way).
- The embedded hydration JSON blob is deliberately NOT parsed: the DOM path
  above is the sanctioned extraction for this adapter (same choice as the
  devfolio adapter), and it works for both season captures.
- Digital cards keep their raw displayed location ("Everywhere, Worldwide");
  location is never rewritten from the mode badge.
- reg_deadline / prize / team / eligibility / cost are not on the cards, so
  they stay None / [] — never invented.
"""

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from radar.adapters.base import Adapter
from radar.fetch import fetch_page
from radar.models import Event, make_id

# Listing page backing https://mlh.io/seasons/2026/events.
LISTING_URL = "https://mlh.io/seasons/2026/events"

# Card container (24 cards in the fixture).
_CARD_SELECTOR = "div.rounded-card"

# Info rows: the date-range span comes first, the location span second.
_INFO_ROW_SELECTOR = (
    "div.flex.items-center.gap-2.min-w-0.text-gray-600 span.truncate"
)

# Mode badges, case-insensitive, exact text (extra badges such as DIVERSITY
# or HIGH SCHOOL are ignored; unknown/missing mode -> card skipped).
_MODE_BADGES = {"digital": "online", "in-person": "offline"}

# "JUN 12 - 14" | "JUN 30 - JUL 2" | "JUN 13" — the page shows no year.
_DATE_RANGE_RE = re.compile(
    r"^([A-Z]{3})\s+(\d{1,2})(?:\s*-\s*(?:([A-Z]{3})\s+)?(\d{1,2}))?$", re.IGNORECASE
)

# Season year from the page title, e.g. "2026 Season Schedule // ...".
_SEASON_YEAR_RE = re.compile(r"(\d{4})\s+season\b", re.IGNORECASE)

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


class MlhAdapter(Adapter):
    """Adapter for the mlh.io season schedule page."""

    id = "mlh"
    kind = "browser"

    def fetch(self, ctx: dict[str, Any]) -> Any:
        """Render the season page and return its HTML.

        Uses `ctx["crawl"]` when the runner injects one, else the shared
        fetch layer (`radar.fetch.fetch_page`).
        """
        crawl = ctx.get("crawl") or fetch_page
        return crawl(LISTING_URL)

    def parse(self, payload: Any, ctx: dict[str, Any]) -> list[Event]:
        """Map season cards to Events (pure: payload + ctx only)."""
        now = ctx["now"]
        soup = BeautifulSoup(payload if isinstance(payload, str) else "", "html.parser")
        year = _season_year(soup)
        if year is None:
            # Without the season year the month/day ranges cannot become
            # dates or a status; skip everything rather than guess.
            return []

        events: list[Event] = []
        for card in soup.select(_CARD_SELECTOR):
            name_el = card.find("h4")
            anchor = card.find_parent("a")
            name = name_el.get_text(" ", strip=True) if name_el else ""
            url = _strip_tracking((anchor.get("href") or "").strip()) if anchor else ""
            if not name or not url.startswith("https://"):
                continue  # no identity -> cannot build a valid Event; skip

            badges = [
                span.get_text(" ", strip=True)
                for span in card.select("span.inline-flex")
            ]
            mode = _first_mapped(badges, _MODE_BADGES)
            if mode is None:
                continue  # cannot assert mode honestly; skip, never guess

            rows = [
                span.get_text(" ", strip=True)
                for span in card.select(_INFO_ROW_SELECTOR)
            ]
            start, end = _parse_range(rows[0] if rows else "", year)
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
                    location=rows[1] if len(rows) > 1 else None,
                    start=start,
                    end=end,
                )
            )
        return events


def _season_year(soup: BeautifulSoup) -> int | None:
    """Season year from the page title ("2026 Season Schedule // ..."), or None."""
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    match = _SEASON_YEAR_RE.search(title)
    return int(match.group(1)) if match else None


def _strip_tracking(url: str) -> str:
    """Drop `utm_*` campaign parameters; the rest of the URL is kept as-is."""
    parts = urlsplit(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )


def _first_mapped(texts: list[str], table: dict[str, str]) -> str | None:
    """First text that maps through ``table`` (case-insensitive), else None."""
    for text in texts:
        mapped = table.get(text.strip().lower())
        if mapped is not None:
            return mapped
    return None


def _parse_range(text: str, year: int) -> tuple[date | None, date | None]:
    """Parse "MMM D - D" / "MMM D - MMM D" / "MMM D" into dates.

    Returns ``(None, None)`` when the badge is malformed or unclear. A
    cross-month range whose end precedes its start wraps into the next year
    (e.g. "DEC 30 - JAN 2"); a same-month range whose end precedes its start
    (e.g. "JUN 30 - 5") is malformed and also returns ``(None, None)``; a
    single-day badge collapses start == end.
    """
    match = _DATE_RANGE_RE.match(text.strip())
    if match is None:
        return None, None
    month1, day1, month2, day2 = match.groups()
    try:
        start = date(year, _MONTHS[month1.upper()], int(day1))
    except (KeyError, ValueError):
        return None, None
    if day2 is None:
        return start, start
    try:
        end_month = _MONTHS[(month2 or month1).upper()]
        end = date(year, end_month, int(day2))
    except (KeyError, ValueError):
        return None, None
    if end < start:
        if month2:
            end = date(year + 1, end_month, int(day2))
        else:
            # Same-month range whose end precedes its start ("JUN 30 - 5"):
            # no second month to wrap into, so the badge is malformed; skip.
            return None, None
    return start, end


def _status_for(start: date, end: date | None, today: date) -> str:
    """Derive status from the page's own dates vs the run date.

    The cards carry no status badge; see the module docstring.
    """
    if end is not None and end < today:
        return "closed"
    if start > today:
        return "upcoming"
    return "open"
