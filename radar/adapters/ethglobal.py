"""ETHGlobal events adapter — rendered listing page (kind: `browser`).

Live page: https://ethglobal.com/events (the M0 spike notes it as
"upcoming + past mixed").
Fixture: `tests/fixtures/ethglobal/listing.html` (real captured render, M0).

The listing is a client-rendered Next.js page; fetch it through the shared
browser backend (`radar.fetch`) and parse the captured DOM
(`extracted_by="css"`). Two regions carry events:

1. The **"Upcoming" carousel** — the grid after the page's own ``Upcoming``
   heading (6 hero sections in the fixture). Each hero is a ``section`` inside
   a wrapping anchor; the hero's pill row is ``[location pill, type pill]``
   (fixture-verified), so the type is the last ``span.inline-flex``. Only
   hackathon types are kept — ``IRL Hackathon`` -> ``offline``,
   ``Online Hackathon`` -> ``online``; every other type (``Conference``,
   ``Co-Working``) is skipped as a non-hackathon.
   - status: derived from the hero's own dates vs ``ctx["now"]`` exactly like
     the table rows (ended -> ``closed``, not started -> ``upcoming``,
     otherwise ``open``); the page's own ``Upcoming`` section heading is the
     fallback flag when the dates do not parse.
   - dates: the date box shows month(s) + day range + weekday range but **no
     year**. The year is derived from the card's own weekday row: exactly one
     candidate year in ``[ctx["now"].year, ctx["now"].year + 1]`` must carry
     the displayed weekday; when none (or several) matches, dates stay None —
     never guessed. A single-day card collapses start == end. A cross-month
     range (``"October — Nov"``) takes its end month from the month row and
     rolls into the next year when that month is earlier than the start
     month; the displayed end weekday must then agree with the computed end
     date (day/weekday-consistency guard). Same-month ranges that run
     backwards are malformed -> None.
   - location: the location pill text kept raw ("Mumbai, India").
   The ``Featured`` carousel is deliberately NOT parsed: it is promo rotation
   whose cards duplicate ``Upcoming`` entries in this capture.

2. The **"Past" table** (333 rows; the page's own "Event Type" column).
   Only the hackathon event types are kept — ``Hackathon`` -> ``offline``,
   ``Online`` -> ``online``; ``Meetup`` / ``Co-working`` / ``Conference`` /
   ``Summit`` rows are skipped as non-hackathons.
   - name: the row's ``h3``; url: the row anchor href resolved against
     https://ethglobal.com (some rows link out to external sites).
   - dates: the row's own date text ("Sep 25th – Sep 27th, 2026" or
     "Oct 8th, 2026"); a row whose dates cannot be parsed is skipped (its
     status could not be derived honestly).
   - location: the two location cells joined ", " ("Tokyo, Japan"); empty
     cells -> None.
   - status: the rows carry no status badge, so it is derived from the row's
     own dates vs ``ctx["now"]`` (ended -> ``closed``, not started ->
     ``upcoming``, otherwise ``open``) — the same derivation as the mlh
     adapter. All 333 fixture rows are past events, so the kept rows are all
     ``closed`` at M0's now.

Both regions deduplicate by resolved URL (first occurrence wins — carousel
first, then the table). Two table rows share their landing page with another
row (``ETHIndia 2022`` -> ethindia.co, ``ETHWaterloo`` 2017 ->
ethwaterloo.com), so under the ``(source, url)`` id model only the newer
edition of each is representable; both collisions are pinned by tests.

The embedded RSC payload (``self.__next_f``) carries raw per-event records
(startTime/endTime/status/...). It is deliberately NOT parsed — the DOM path
is the sanctioned extraction — and was used only as a report-side
cross-validation (see the task report).
"""

import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from radar.adapters.base import Adapter
from radar.fetch import fetch_page
from radar.models import Event, make_id

# Listing page backing https://ethglobal.com/events.
LISTING_URL = "https://ethglobal.com/events"

_SITE_BASE = "https://ethglobal.com"

# Past-table row: the anchor carries the row's hover style class (333 in the
# fixture). Attribute-substring matching survives the utility-class churn.
_TABLE_ROW_SELECTOR = 'a[class*="hover:bg-black-100"]'

# The page's own section heading for the future-events grid.
_UPCOMING_HEADING = "Upcoming"

# Event-type vocabularies (exact text, case-insensitive). Unknown -> skipped.
_TABLE_TYPE_MODES = {"hackathon": "offline", "online": "online"}
_HERO_TYPE_MODES = {"irl hackathon": "offline", "online hackathon": "online"}

# Table date text: "Sep 25th – Sep 27th, 2026" / "Feb 28th – Mar 1st, 2020" /
# "Oct 8th, 2026" (single day). Ordinal suffixes are optional.
_TABLE_RANGE_RE = re.compile(
    r"^([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*[–—-]\s*"
    r"(?:([A-Za-z]{3,9})\s+)?(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})$"
)
_TABLE_SINGLE_RE = re.compile(
    r"^([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})$"
)

# Weekday abbreviations on the hero date box ("Thu — Sat").
_WEEKDAY_RE = re.compile(r"[A-Z][a-z]{2}")

# Month-name tokens on the hero date box's month row ("November", "Dec").
_MONTH_TOKEN_RE = re.compile(r"[A-Za-z]{3,}")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class EthglobalAdapter(Adapter):
    """Adapter for the ethglobal.com events listing page."""

    id = "ethglobal"
    kind = "browser"

    def fetch(self, ctx: dict[str, Any]) -> Any:
        """Render the listing page and return its HTML.

        Uses `ctx["crawl"]` when the runner injects one, else the shared
        fetch layer (`radar.fetch.fetch_page`).
        """
        crawl = ctx.get("crawl") or fetch_page
        return crawl(LISTING_URL)

    def parse(self, payload: Any, ctx: dict[str, Any]) -> list[Event]:
        """Map the upcoming carousel + past table to Events (pure)."""
        now = ctx["now"]
        soup = BeautifulSoup(payload if isinstance(payload, str) else "", "html.parser")
        events: list[Event] = []
        seen: set[str] = set()

        for event in _parse_carousel(soup, now, self.id):
            if event.url not in seen:
                seen.add(event.url)
                events.append(event)
        for event in _parse_table(soup, now, self.id):
            if event.url not in seen:
                seen.add(event.url)
                events.append(event)
        return events


def _parse_carousel(soup: BeautifulSoup, now: datetime, source_id: str) -> list[Event]:
    """Events from the grid after the page's ``Upcoming`` heading."""
    events: list[Event] = []
    for heading in soup.find_all("h2"):
        if not _text(heading).startswith(_UPCOMING_HEADING):
            continue
        grid = heading.find_next_sibling("div")
        if grid is None:
            continue
        for section in grid.select("section"):
            name = _text(section.find("h2"))
            anchor = section.find_parent("a")
            url = _resolve_url(_SITE_BASE, anchor.get("href") if anchor else None)
            if not name or not url.startswith("https://"):
                continue  # no identity -> cannot build a valid Event; skip

            pills = [_text(span) for span in section.select("span.inline-flex")]
            mode = _HERO_TYPE_MODES.get(pills[-1].lower()) if pills else None
            if mode is None:
                continue  # not a hackathon-type card (or no type pill); skip

            start, end = _parse_hero_dates(section, now)
            # The status derives from the hero's own dates when they parse
            # (started-not-ended must not read "upcoming"); the page's own
            # "Upcoming" section heading is the fallback flag otherwise.
            status = _status_for(start, end, now.date()) if start is not None else "upcoming"
            events.append(
                Event(
                    id=make_id(source_id, url),
                    name=name,
                    source=source_id,
                    url=url,
                    mode=mode,
                    status=status,
                    first_seen=now,
                    last_seen=now,
                    extracted_by="css",
                    location=pills[0] if len(pills) >= 2 else None,
                    start=start,
                    end=end,
                )
            )
    return events


def _parse_table(soup: BeautifulSoup, now: datetime, source_id: str) -> list[Event]:
    """Events from the hackathon-type rows of the "Past" table."""
    today = now.date()
    events: list[Event] = []
    for row in soup.select(_TABLE_ROW_SELECTOR):
        badge = _table_badge(row)
        mode = _TABLE_TYPE_MODES.get(badge.lower()) if badge else None
        if mode is None:
            continue  # not a hackathon-type row; skip, never guess

        name = _text(row.find("h3"))
        url = _resolve_url(_SITE_BASE, row.get("href"))
        if not name or not url.startswith("https://"):
            continue  # no identity -> cannot build a valid Event; skip

        start, end = _parse_table_dates(row)
        if start is None:
            continue  # no honest dates -> no honest status; skip, never guess

        events.append(
            Event(
                id=make_id(source_id, url),
                name=name,
                source=source_id,
                url=url,
                mode=mode,
                status=_status_for(start, end, today),
                first_seen=now,
                last_seen=now,
                extracted_by="css",
                location=_table_location(row),
                start=start,
                end=end,
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


def _month_number(name: str) -> int | None:
    """Month number for a month name ("Sep", "September"), else None."""
    return _MONTHS.get(name[:3].lower()) if name else None


def _table_badge(row: Any) -> str:
    """The row's event-type badge text, or "" when the row has none."""
    for div in row.find_all("div"):
        classes = div.get("class") or []
        if "uppercase" in classes and "px-3" in classes:
            return _text(div)
    return ""


def _parse_table_dates(row: Any) -> tuple[date | None, date | None]:
    """Parse the row's own date text into (start, end); (None, None) if absent.

    The table renders the same date cell twice (mobile + desktop copies) with
    identical text; the first ``<p>`` that fully matches the date grammar is
    used. A single-day cell collapses start == end. A range whose end lands
    before its start wraps the start back one year when the end month is
    earlier than the start month ("Dec 28th – Jan 5th, 2021" — the trailing
    year belongs to the end date); otherwise it is malformed and returns
    (None, None) so the row is skipped.
    """
    for p in row.find_all("p"):
        text = _text(p)
        match = _TABLE_RANGE_RE.match(text)
        if match is not None:
            month1, day1, month2, day2, year = match.groups()
            start_month = _month_number(month1)
            end_month = _month_number(month2 or month1)
            if start_month is None or end_month is None:
                return None, None
            try:
                start = date(int(year), start_month, int(day1))
                end = date(int(year), end_month, int(day2))
            except ValueError:
                return None, None
            if end < start:
                if end_month < start_month:
                    # Cross-year wrap: the trailing year belongs to the end
                    # date ("Dec 28th – Jan 5th, 2021" = Dec 28 2020 – Jan 5
                    # 2021), so the start rolls back one year.
                    try:
                        start = date(int(year) - 1, start_month, int(day1))
                    except ValueError:
                        return None, None
                else:
                    return None, None  # backwards range -> malformed; skip
            return start, end
        match = _TABLE_SINGLE_RE.match(text)
        if match is not None:
            month1, day1, year = match.groups()
            month = _month_number(month1)
            if month is None:
                return None, None
            try:
                start = date(int(year), month, int(day1))
            except ValueError:
                return None, None
            return start, start
    return None, None


def _table_location(row: Any) -> str | None:
    """The row's location cells joined ", " ("Tokyo, Japan"); None when empty."""
    cells = row.select_one("div.flex-4.flex-col")
    if cells is None:
        return None
    parts = [_text(p) for p in cells.find_all("p")]
    joined = ", ".join(part for part in parts if part)
    return joined or None


def _hero_months(text: str) -> list[int]:
    """Month numbers named in the hero date box's month row, in order.

    A single-month card names one month ("November"); a cross-month range
    names two ("November — Dec" — the page renders the start month in full
    and the end month abbreviated). Non-month tokens are ignored.
    """
    return [
        number
        for number in (_month_number(token) for token in _MONTH_TOKEN_RE.findall(text))
        if number is not None
    ]


def _parse_hero_dates(section: Any, now: datetime) -> tuple[date | None, date | None]:
    """Parse the hero date box (month[s] + days + weekdays, no year).

    The year is derived from the card's own weekday row: exactly one candidate
    in ``[now.year, now.year + 1]`` must have that weekday for the start day;
    otherwise (none or several) the dates stay None. A cross-month range
    ("October — Nov") takes its end month from the month row and rolls into
    the next year when that month is earlier than the start month; the second
    displayed weekday must then agree with the computed end date
    (day/weekday-consistency guard). See the module docstring.
    """
    box = section.select_one("div.flex.space-x-4")
    holder = box.select_one("div.text-center") if box is not None else None
    if holder is None:
        return None, None
    children = holder.find_all("div", recursive=False)
    if len(children) < 3:
        return None, None
    months = _hero_months(_text(children[0]))
    days = [
        int(span.get_text(strip=True))
        for span in children[1].find_all("span")
        if span.get_text(strip=True).isdigit()
    ]
    weekdays = _WEEKDAY_RE.findall(_text(children[2]))
    if not months or len(months) > 2 or not days or len(days) > 2 or not weekdays:
        return None, None
    start_month = months[0]
    end_month = months[1] if len(months) > 1 else start_month
    day1 = days[0]
    day2 = days[1] if len(days) > 1 else days[0]
    if end_month == start_month and day2 < day1:
        return None, None  # backwards same-month range -> malformed; never guess
    year = _derive_year(start_month, day1, weekdays[0], now)
    if year is None:
        return None, None
    end_year = year + 1 if end_month < start_month else year
    try:
        start = date(year, start_month, day1)
        end = date(end_year, end_month, day2)
    except ValueError:
        return None, None
    if len(days) > 1 and (
        len(weekdays) < 2 or end.strftime("%a").lower() != weekdays[1].lower()
    ):
        return None, None  # display disagrees with the parsed range; never guess
    return start, end


def _derive_year(month: int, day: int, weekday: str, now: datetime) -> int | None:
    """Year for a yearless hero date: the unique weekday match near ``now``.

    Candidates are ``[now.year, now.year + 1]`` (the grid lists future
    events). Exactly one candidate must carry the displayed weekday; none or
    several -> None (never guessed). Consecutive years differ by one weekday,
    so two matches cannot occur for a well-formed date.
    """
    matches: list[int] = []
    for candidate in (now.year, now.year + 1):
        try:
            day_date = date(candidate, month, day)
        except ValueError:
            continue
        if day_date.strftime("%a").lower() == weekday.lower():
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def _status_for(start: date, end: date | None, today: date) -> str:
    """Derive status from the row's own dates vs the run date (mlh ruling)."""
    if end is not None and end < today:
        return "closed"
    if start > today:
        return "upcoming"
    return "open"
