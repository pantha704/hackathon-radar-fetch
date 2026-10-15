"""DoraHacks adapter — rendered listing page (kind: `browser`).

Live page: https://dorahacks.io/hackathon
Fixture: `tests/fixtures/dorahacks/listing.html` (real captured render, M0).

The listing is a Vue server-rendered page; fetch through the shared browser
backend (`radar.fetch`) and parse the captured card DOM
(`extracted_by="css"`). Selectors (fixture-derived):

- card     : ``div.hackathon-card`` (24 in the fixture)
- link     : the card's wrapping anchor — relative ``/hackathon/<slug>``
             hrefs are resolved against https://dorahacks.io
- name     : ``span.line-clamp-2.font-semibold``
- status   : ``span[aria-label="hackathon-status"]`` text, mapped by its
             first word: Ongoing / Extended -> ``open``; Upcoming /
             Pre-registration -> ``upcoming``; Winner Announced / Ended ->
             ``closed``. Unknown vocabulary -> card skipped, never guessed.
- location : ``span.line-clamp-1.break-all`` — ``"Virtual"`` -> mode
             ``online``; any other non-empty location -> mode ``offline``
             (physical). Missing location -> card skipped (no honest mode).
- prize    : the "Prize Pool" row text, kept raw ("200,000 USD", "Pending").
- themes   : the accent-bg pill texts of the tag row.

Honesty notes:
- The cards carry no calendar dates. The only temporal text is a countdown
  ("3 days left") to an unlabeled deadline; it is NOT mapped to any date
  field (nothing on the card says which date it counts to, so mapping it
  would be a guess). start / end / reg_deadline therefore stay None.
- Status mapping: "Pre-registration" and "Upcoming" both mean the event has
  not started/opened yet -> ``upcoming`` (mirrors the devpost ruling that
  non-open states map to upcoming); "Extended" is a deadline extension of a
  running event -> ``open``.
- No hybrid marker exists on the cards; ``hybrid`` is never written.
- team / eligibility / cost / also_on are not on the cards -> None / [].
"""

from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from radar.adapters.base import Adapter
from radar.fetch import fetch_page
from radar.models import Event, make_id

# Listing page backing https://dorahacks.io/hackathon.
LISTING_URL = "https://dorahacks.io/hackathon"

_SITE_BASE = "https://dorahacks.io"

_CARD_SELECTOR = "div.hackathon-card"

# Status badge vocabulary, keyed by the first word of the badge text
# (the winner badge reads "Winner Announced 🏅").
_STATUS_BY_FIRST_WORD = {
    "ongoing": "open",
    "extended": "open",
    "upcoming": "upcoming",
    "pre-registration": "upcoming",
    "winner": "closed",
    "ended": "closed",
}

# Location texts that read as digital/online. Anything else non-empty is a
# physical location -> offline.
_ONLINE_LOCATIONS = {"virtual", "online"}


class DorahacksAdapter(Adapter):
    """Adapter for the dorahacks.io hackathon listing page."""

    id = "dorahacks"
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
            anchor = card.find_parent("a")
            raw_href = (anchor.get("href") or "").strip() if anchor else ""
            # Empty/whitespace raw hrefs: urljoin would yield the bare site
            # root and falsely pass the https:// identity check below.
            # Fragment-only hrefs ("#", "#x") resolve to the listing page
            # itself — the same bogus site-root event — so they are rejected
            # before urljoin too (T8 hardening).
            url = (
                urljoin(_SITE_BASE, raw_href)
                if raw_href and not raw_href.startswith("#")
                else ""
            )
            title_el = card.select_one("span.line-clamp-2.font-semibold")
            name = title_el.get_text(" ", strip=True) if title_el else ""
            if not name or not url.startswith("https://"):
                continue  # no identity -> cannot build a valid Event; skip

            status_el = card.select_one('[aria-label="hackathon-status"]')
            status = _map_status(
                status_el.get_text(" ", strip=True) if status_el else ""
            )
            if status is None:
                continue  # unknown status vocabulary; skip, never guess

            location_el = card.select_one("span.line-clamp-1.break-all")
            location = location_el.get_text(" ", strip=True) if location_el else ""
            if not location:
                continue  # no location -> no honest mode signal; skip

            mode = "online" if location.lower() in _ONLINE_LOCATIONS else "offline"
            prize_el = card.select_one("div.inset-border-t span.text-lg")
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
                    prize=prize_el.get_text(" ", strip=True) if prize_el else None,
                    themes=[
                        pill.get_text(" ", strip=True)
                        for pill in card.select("div.bg-accent-bg")
                    ],
                )
            )
        return events


def _map_status(text: str) -> str | None:
    """Map a status badge text through the first-word vocabulary, else None."""
    words = text.split()
    if not words:
        return None
    return _STATUS_BY_FIRST_WORD.get(words[0].lower())
