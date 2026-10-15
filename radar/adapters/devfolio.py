"""Devfolio adapter — rendered listing page (kind: `browser`).

Live page: https://devfolio.co/hackathons
Fixture: `tests/fixtures/devfolio/listing.html` (real captured render, M0).

The listing is a client-rendered React page, so it must be fetched with the
browser backend (`radar.fetch`) before parsing; selectors below are derived
from the captured fixture. `beautifulsoup4` arrives as a hard dependency of
crawl4ai (a direct dependency of this project).

The captured page also embeds a Next.js `__NEXT_DATA__` hydration blob with
raw per-hackathon fields (starts_at/ends_at/reg_ends_at, ...). The agreed
extraction path for this adapter is the rendered cards
(`extracted_by="css"`); the blob is deliberately not parsed — it is a
build-detail shape and mixing methods would blur extraction provenance.
"""

import re
from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup

from radar.adapters.base import Adapter
from radar.fetch import fetch_page
from radar.models import Event, make_id

# Listing page backing https://devfolio.co/hackathons.
LISTING_URL = "https://devfolio.co/hackathons"

# Card container: styled-components class `CompactHackathonCard__StyledCard-*`
# (the semantic prefix is stable across hash changes; 25 cards in the fixture).
_CARD_SELECTOR = 'div[class*="CompactHackathonCard__StyledCard"]'

# Badge vocabulary seen on the captured cards (exact text, case-insensitive):
# mode badge <-> Event.mode, status badge <-> Event.status. Cards whose badges
# are missing or outside this vocabulary are skipped, never guessed.
_MODE_BADGES = {"online": "online", "offline": "offline", "hybrid": "hybrid"}
_STATUS_BADGES = {"open": "open", "upcoming": "upcoming", "ended": "closed"}

# Timeline badge, e.g. "Starts 14/10/26" (dd/mm/yy) -> the hackathon start.
# NOTE: upcoming cards instead show "Opens dd/mm/yy" (applications open). That
# is a different thing and the model has no matching field, so it is NOT
# written into start — those rows keep start=None rather than misfiling dates.
_STARTS_RE = re.compile(r"^starts\s+(\d{2}/\d{2}/\d{2})$", re.IGNORECASE)


class DevfolioAdapter(Adapter):
    """Adapter for the devfolio.co hackathon listing page."""

    id = "devfolio"
    kind = "browser"

    def fetch(self, ctx: dict[str, Any]) -> Any:
        """Render the listing page and return its HTML.

        Uses `ctx["crawl"]` when the runner injects one, else the shared
        fetch layer (`radar.fetch.fetch_page`).
        """
        crawl = ctx.get("crawl") or fetch_page
        return crawl(LISTING_URL)

    def parse(self, payload: Any, ctx: dict[str, Any]) -> list[Event]:
        """Map listing cards to Events (pure: payload + ctx only).

        Field honesty (from the captured fixture):
        - url: the card anchor points at the project's dedicated devfolio page
          (https://<slug>.devfolio.co/). No canonical devfolio.co/hackathons/
          <uuid> page URL appears in the fixture (uuid only shows up inside
          asset URLs), so the anchor href is the canonical page we have.
        - mode/status: from the exact badge vocabulary above.
        - start: "Starts dd/mm/yy" only (see _STARTS_RE note).
        - themes: the theme pills under the "Theme" label, in card order.
        - end / reg_deadline / location / prize / team / eligibility / cost:
          not present on the compact cards -> left unset, never invented.
        """
        now = ctx["now"]
        soup = BeautifulSoup(payload if isinstance(payload, str) else "", "html.parser")
        events: list[Event] = []
        for card in soup.select(_CARD_SELECTOR):
            name_el = card.select_one("h3")
            anchor = name_el.find_parent("a") if name_el else None
            name = name_el.get_text(" ", strip=True) if name_el else ""
            url = (anchor.get("href") or "").strip() if anchor else ""
            if not name or not url.startswith("https://"):
                continue  # no identity -> cannot build a valid Event; skip, never invent

            texts = [p.get_text(" ", strip=True) for p in card.find_all("p")]
            mode = _first_mapped(texts, _MODE_BADGES)
            status = _first_mapped(texts, _STATUS_BADGES)
            if mode is None or status is None:
                continue  # cannot assert mode/status honestly; skip, never guess

            themes = [
                p.get_text(" ", strip=True)
                for p in card.select('div[class*="TsCKF"] p')
            ]

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
                    start=_parse_starts(texts),
                    themes=themes,
                )
            )
        return events


def _first_mapped(texts: list[str], table: dict[str, str]) -> str | None:
    """First text that maps through ``table`` (case-insensitive), else None."""
    for text in texts:
        mapped = table.get(text.strip().lower())
        if mapped is not None:
            return mapped
    return None


def _parse_starts(texts: list[str]) -> date | None:
    """Parse a "Starts dd/mm/yy" badge into a date; None when absent/unclear."""
    for text in texts:
        match = _STARTS_RE.match(text.strip())
        if match is None:
            continue
        try:
            return datetime.strptime(match.group(1), "%d/%m/%y").date()
        except ValueError:
            return None  # malformed date -> honestly unknown, never invented
    return None
