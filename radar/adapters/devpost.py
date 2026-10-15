"""Devpost adapter — JSON listing API (kind: `api`).

Live endpoint: https://devpost.com/api/hackathons?page=1
Payload shape captured in `tests/fixtures/devpost/listing_p1.json`.
"""

import re
from datetime import date, datetime
from typing import Any

import httpx

from radar.adapters.base import Adapter
from radar.models import Event, make_id

# Listing endpoint backing https://devpost.com/hackathons (page 1).
LISTING_URL = "https://devpost.com/api/hackathons?page=1"

# Desktop Chrome UA: the endpoint serves the listing JSON to normal browsers.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_TAG_RE = re.compile(r"<[^>]+>")
_PERIOD_RE = re.compile(
    r"(?P<month1>[A-Za-z]{3,9})\s+(?P<day1>\d{1,2})\s*[-–—]\s*"
    r"(?:(?P<month2>[A-Za-z]{3,9})\s+)?(?P<day2>\d{1,2}),?\s+(?P<year>\d{4})"
)


def _clean_text(value: Any) -> str | None:
    """Visible text of an API string: drop HTML tags, collapse whitespace.

    E.g. ``"$<span data-currency-value>138,000</span>"`` → ``"$138,000"``.
    Unknown / empty values stay None (never invent).
    """
    if not isinstance(value, str):
        return None
    text = " ".join(_TAG_RE.sub("", value).split())
    return text or None


def _parse_month(name: str) -> int | None:
    try:
        return datetime.strptime(name[:3].title(), "%b").month
    except ValueError:
        return None


def _parse_period_dates(text: Any) -> tuple[date | None, date | None]:
    """Parse devpost's ``submission_period_dates`` (e.g. "Aug 31 - Oct 23, 2026"
    or "Oct 01 - 10, 2026") into (start, end).

    Dates are only returned when clearly parseable; otherwise (None, None).
    """
    if not isinstance(text, str):
        return None, None
    match = _PERIOD_RE.search(text)
    if match is None:
        return None, None
    month1 = _parse_month(match["month1"])
    month2 = _parse_month(match["month2"]) if match["month2"] else month1
    if month1 is None or month2 is None:
        return None, None
    try:
        start = date(int(match["year"]), month1, int(match["day1"]))
        end = date(int(match["year"]), month2, int(match["day2"]))
    except ValueError:
        return None, None
    if start > end:
        # Period wrapped across the year boundary, e.g. "Dec 20 - Jan 10, 2027".
        try:
            start = start.replace(year=start.year - 1)
        except ValueError:
            return None, None
        if start > end:
            return None, None
    return start, end


class DevpostAdapter(Adapter):
    """Adapter for the devpost.com hackathon listing API."""

    id = "devpost"
    kind = "api"

    def fetch(self, ctx: dict[str, Any]) -> Any:
        """GET the listing page; returns parsed JSON.

        Minimal for now — retries/backoff/pacing are the fetch-layer's job
        (later task).
        """
        http = ctx.get("http") or httpx
        response = http.get(
            LISTING_URL, headers={"User-Agent": USER_AGENT}, timeout=30.0
        )
        response.raise_for_status()
        return response.json()

    def parse(self, payload: Any, ctx: dict[str, Any]) -> list[Event]:
        """Map listing items to Events (interface per SDD Task 3 ruling 4)."""
        now = ctx["now"]
        items = payload.get("hackathons") if isinstance(payload, dict) else None
        events: list[Event] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            name = _clean_text(item.get("title"))
            url = _clean_text(item.get("url"))
            if not name or not url:
                continue  # no identity -> cannot build a valid Event; skip, never invent

            displayed = item.get("displayed_location")
            location = (
                _clean_text(displayed.get("location"))
                if isinstance(displayed, dict)
                else None
            )
            # Ruling: "Online" -> mode online; anything else -> offline. Live
            # listings always carry a location; closed-vs-upcoming is the
            # archive logic's job (later task).
            mode = "online" if (location or "").lower() == "online" else "offline"

            # The listing payload only exposes open_state "open" for live rows;
            # anything else is treated as upcoming here — closed-vs-upcoming
            # disambiguation is the archive logic's job (later task).
            status = "open" if item.get("open_state") == "open" else "upcoming"

            start, end = _parse_period_dates(item.get("submission_period_dates"))
            # reg_deadline drives days_left; devpost exposes no separate
            # registration deadline, so the submission period end (if any) is
            # the operative deadline.
            reg_deadline = end

            themes: list[str] = []
            for theme in item.get("themes") or []:
                if isinstance(theme, dict):
                    theme_name = _clean_text(theme.get("name"))
                    if theme_name:
                        themes.append(theme_name)

            # Prize only when the payload clearly carries it; team fields are
            # absent from listing rows, so they stay None (never invent).
            prize = _clean_text(item.get("prize_amount"))

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
                    extracted_by="api",
                    location=location,
                    reg_deadline=reg_deadline,
                    start=start,
                    end=end,
                    prize=prize,
                    themes=themes,
                )
            )
        return events
