"""Normalize adapter output: status, days_left, cross-source dedupe, first_seen.

Status recomputation pattern
----------------------------
Adapters keep the source's raw badge as the event's "declared" status. For
FRESH adapter runs the runner recomputes the stored status with::

    event.status = compute_status(
        today, event.reg_deadline, event.start, event.end,
        declared=event.status,  # the adapter's raw value, read BEFORE this
    )

Rows retained from a previous run because their source failed in the
current run ("stale rows", see GLOSSARY) are NOT recomputed: their
last-known status stands — the run has no fresh evidence about them.

Truth table for ``compute_status`` (``today`` is a ``datetime.date``; all
date parameters are ``datetime.date | None``):

a. ``declared == "closed"`` → ``"closed"`` — never resurrected.
b. elif ``end`` is not None and ``end < today`` → ``"closed"``.
c. elif ``reg_deadline`` is not None: ``>= today`` → ``"open"``;
   ``< today`` → ``"upcoming"`` (not ended — rule b already filtered).
d. else → ``declared`` passes through (``"open"`` / ``"upcoming"``).

``start`` is part of the signature for callers passing the whole date set;
it plays no role in the truth table.

``days_left`` floors at 0 and is ``None`` when the deadline is unknown.
``dedupe`` merges rows for the same event by ``normalized(name) +
ISO(start)`` when the start is known — the same event listed on two
platforms merges into one row; rows with an unknown start additionally key
on ``host(url)``, so dateless rows only merge within one site. The first
row of each group wins and merged-away sources are appended to the kept
row's ``also_on`` (deduplicated, stable order). ``carry_first_seen``
copies ``first_seen`` forward across runs by ``id``. Missing values stay
``None`` — never invented.
"""

import re
from dataclasses import replace
from datetime import date
from urllib.parse import urlparse

from radar.models import Event

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def compute_status(
    today: date,
    reg_deadline: date | None,
    start: date | None,
    end: date | None,
    declared: str,
) -> str:
    """Derive the stored status from dates + the source's declared badge.

    Binding truth table (see module docstring): declared "closed" always
    wins; an ended event (``end < today``) is closed; otherwise a present
    ``reg_deadline`` decides open/upcoming, and with no deadline the
    declared badge passes through. ``start`` is unused by design.
    """
    if declared == "closed":
        return "closed"
    if end is not None and end < today:
        return "closed"
    if reg_deadline is not None:
        return "open" if reg_deadline >= today else "upcoming"
    return declared


def days_left(today: date, reg_deadline: date | None) -> int | None:
    """Whole days from ``today`` to ``reg_deadline``; ``None`` when unknown.

    Floors at 0: an already-passed deadline reads ``0``, never negative.
    """
    if reg_deadline is None:
        return None
    return max(0, (reg_deadline - today).days)


def _norm_title(title: str) -> str:
    """Lowercase, collapse every non-alphanumeric run to a space, strip."""
    return _NON_ALNUM_RE.sub(" ", title.lower()).strip()


def _dedupe_key(event: Event) -> str:
    """Group key: normalized name + ISO start; dateless rows add the host.

    Review ruling: dated rows (``start is not None``) key on title + start
    alone, so the same event listed on two platforms (different hosts)
    merges into one row. Rows whose start is unknown additionally key on
    ``host(url)``, so dateless rows only merge within one site.
    """
    title = _norm_title(event.name)
    if event.start is None:
        return f"{title}||{urlparse(event.url).netloc.lower()}"
    return f"{title}|{event.start.isoformat()}"


def dedupe(events: list[Event]) -> list[Event]:
    """Merge duplicate rows for the same event; keep the first of each group.

    Group key (review ruling): normalized ``name`` + ISO ``start`` when the
    start is known — the same event listed on two platforms merges into one
    row regardless of host. Rows with ``start is None`` additionally key on
    ``host(url)``, so dateless rows only merge within the same site; same
    title with a different start (or vice versa) is a different event and
    is NOT merged. The kept event's fields are otherwise unchanged; the
    merged-away rows' ``source`` values are appended to its ``also_on``
    (deduplicated, stable order). Input events are not mutated.
    """
    kept: list[Event] = []
    extra_sources: list[list[str]] = []
    slot_by_key: dict[str, int] = {}
    for event in events:
        key = _dedupe_key(event)
        slot = slot_by_key.get(key)
        if slot is None:
            slot_by_key[key] = len(kept)
            kept.append(event)
            extra_sources.append([])
        else:
            extra_sources[slot].append(event.source)
    return [
        replace(event, also_on=list(dict.fromkeys([*event.also_on, *extra])))
        if extra
        else event
        for event, extra in zip(kept, extra_sources)
    ]


def carry_first_seen(events: list[Event], prev: dict[str, Event]) -> list[Event]:
    """Copy ``first_seen`` forward from the previous run's events, by ``id``.

    ``prev`` maps ``id -> Event`` (typically the previous ``radar.json``).
    On a hit the event re-adopts the previous ``first_seen`` and keeps its
    new ``last_seen``; ids missing from ``prev`` are unchanged. Input
    events are not mutated.

    Relies on ``make_id`` ids being unique across sources: ``make_id``
    hashes ``(source, url)``, and a cross-source id collision would graft
    the wrong history onto an event — there is no guard for that here.
    """
    carried: list[Event] = []
    for event in events:
        previous = prev.get(event.id)
        if previous is not None:
            event = replace(event, first_seen=previous.first_seen)
        carried.append(event)
    return carried
