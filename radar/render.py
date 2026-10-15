"""Deterministic markdown renderer (Task 6): hackathons.md / online.md / archive.md.

Every document is: title + blank line + header line + blank line + one pipe
table of the 15 pinned columns::

    Name | Platform | Mode | Status | Reg. deadline | Days left | Starts |
    Ends | Team | Prize | Themes | Eligibility | Cost | Also on | Updated

The header echoes ``meta`` verbatim — ``{"last_updated": <aware datetime>,
"open": int, "online": int, "new": int}`` — formatting ``last_updated``
through ``config.fmt_ist``; a missing, empty or otherwise invalid slot
renders ``—``. Output ends with a newline.

Cell rules (never invent values):
- Name is ``[name](url)``; Platform is the source; Status is the stored value.
- Mode: ``Online`` / ``Offline — {location}`` / ``Hybrid — {location}`` —
  the location is suppressed for online rows (it would just repeat "Online").
- Dates are ``YYYY-MM-DD`` (a timestamp renders as its IST calendar date);
  Days left is derived on the **run date** basis (GLOSSARY): ``max(0,
  (reg_deadline - run-date).days)`` — the same formula ``normalize.days_left``
  uses with ``today`` as the IST date of ``meta.last_updated``; the event's
  ``last_seen`` IST date stands in only when meta carries no valid
  ``last_updated``; ``None`` renders ``—``.
- Team from team_min/team_max/solo_ok: ``2–4``, ``2–4, solo ok``, ``solo ok``,
  ``1+`` (min only), ``≤4`` (max only), else ``—``.
- themes / also_on join with ``, ``; every None/empty value renders ``—``.

Cells escape ``|`` as ``\\|`` and collapse newlines to spaces. Render never
mutates its input and is byte-deterministic for the same inputs (stable sort).

Sorts (every key ends with ``event.id``, so exact ties are input-order
independent):
- ``hackathons``: live rows (status open/upcoming), mode group
  online → hybrid → offline, then days_left asc (None last), then name.
- ``online``: live rows with mode == "online", days_left asc (None last),
  then name.
- ``archive``: closed rows, ``(end or start or last_seen-date)`` DESC,
  then name asc.
"""

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

from radar import config
from radar.models import Event

LIVE_STATUSES = {"open", "upcoming"}

_MODE_RANK = {"online": 0, "hybrid": 1, "offline": 2}

TITLE_HACKATHONS = "# Hackathon Radar — live"
TITLE_ONLINE = "# Hackathon Radar — online only"
TITLE_ARCHIVE = "# Hackathon Radar — archive (closed)"

COLUMNS = (
    "Name",
    "Platform",
    "Mode",
    "Status",
    "Reg. deadline",
    "Days left",
    "Starts",
    "Ends",
    "Team",
    "Prize",
    "Themes",
    "Eligibility",
    "Cost",
    "Also on",
    "Updated",
)

_DASH = "—"


def hackathons(events: Iterable[Event], meta: Mapping[str, Any]) -> str:
    """Live table: open + upcoming, online → hybrid → offline, days_left, name."""
    selected = sorted(
        (event for event in events if event.status in LIVE_STATUSES),
        key=lambda event: _live_sort_key(event, meta),
    )
    return _document(TITLE_HACKATHONS, meta, selected)


def online(events: Iterable[Event], meta: Mapping[str, Any]) -> str:
    """Online-only lens over the live rows: days_left asc (None last), name."""
    selected = sorted(
        (
            event
            for event in events
            if event.status in LIVE_STATUSES and event.mode == "online"
        ),
        key=lambda event: _online_sort_key(event, meta),
    )
    return _document(TITLE_ONLINE, meta, selected)


def archive(events: Iterable[Event], meta: Mapping[str, Any]) -> str:
    """Closed rows, newest first (end or start or last_seen date), then name."""
    selected = sorted(
        (event for event in events if event.status == "closed"),
        key=_archive_sort_key,
    )
    return _document(TITLE_ARCHIVE, meta, selected)


# --- sorting keys -----------------------------------------------------------


def _run_date(meta: Mapping[str, Any]) -> date | None:
    """IST calendar date of the run (``meta["last_updated"]``); None unusable.

    The ``days_left`` basis per GLOSSARY ("whole days from the run date
    (IST)"). Only a real ``datetime`` is valid here — ISO strings are the
    store's shape and the runner converts before render.
    """
    value = meta.get("last_updated")
    if isinstance(value, datetime):
        return _ist_date(value)
    return None


def _days_left(event: Event, meta: Mapping[str, Any]) -> int | None:
    """Whole days from the run date to ``reg_deadline``; None when unknown.

    ``today`` is the IST date of the run — ``meta["last_updated"]`` — so a
    stale row is never overstated. The event's ``last_seen`` IST date stands
    in only when meta carries no valid ``last_updated``. Floors at 0 for
    passed deadlines (same formula as ``normalize.days_left``).
    """
    if event.reg_deadline is None:
        return None
    today = _run_date(meta)
    if today is None and event.last_seen is not None:
        today = _ist_date(event.last_seen)
    if today is None:
        return None
    return max(0, (event.reg_deadline - today).days)


def _live_sort_key(event: Event, meta: Mapping[str, Any]) -> tuple[int, bool, int, str, str]:
    days = _days_left(event, meta)
    return (_MODE_RANK[event.mode], days is None, days or 0, event.name, event.id)


def _online_sort_key(event: Event, meta: Mapping[str, Any]) -> tuple[bool, int, str, str]:
    days = _days_left(event, meta)
    return (days is None, days or 0, event.name, event.id)


def _archive_sort_key(event: Event) -> tuple[int, str, str]:
    when = event.end or event.start or _ist_date(event.last_seen)
    return (-when.toordinal(), event.name, event.id)


# --- cell rendering ---------------------------------------------------------


def _ist_date(moment: datetime) -> date:
    """IST calendar date of a timestamp; a naive datetime is taken as-is."""
    if moment.tzinfo is not None:
        return moment.astimezone(config.IST).date()
    return moment.date()


def _cell(value: str) -> str:
    """Escape one table cell: newlines collapse to spaces, ``|`` → ``\\|``."""
    value = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return value.replace("|", "\\|")


def _dash_if_empty(value: str | None) -> str:
    if value is None or not value.strip():
        return _DASH
    return value


def _date_cell(value: date | None) -> str:
    return value.isoformat() if value is not None else _DASH


def _int_cell(value: int | None) -> str:
    return str(value) if value is not None else _DASH


def _list_cell(items: list[str]) -> str:
    return ", ".join(items) if items else _DASH


def _mode_cell(event: Event) -> str:
    label = event.mode.capitalize()
    if event.mode == "online":
        return label  # location would just repeat "Online"
    if event.location and event.location.strip():
        return f"{label} — {event.location}"
    return label


def _team_cell(event: Event) -> str:
    if event.team_min is not None and event.team_max is not None:
        bounds = f"{event.team_min}–{event.team_max}"
    elif event.team_min is not None:
        bounds = f"{event.team_min}+"
    elif event.team_max is not None:
        bounds = f"≤{event.team_max}"
    else:
        bounds = ""
    if event.solo_ok:
        return f"{bounds}, solo ok" if bounds else "solo ok"
    return bounds or _DASH


def _cells(event: Event, meta: Mapping[str, Any]) -> list[str]:
    return [
        f"[{event.name}]({event.url})",
        event.source,
        _mode_cell(event),
        event.status,
        _date_cell(event.reg_deadline),
        _int_cell(_days_left(event, meta)),
        _date_cell(event.start),
        _date_cell(event.end),
        _team_cell(event),
        _dash_if_empty(event.prize),
        _list_cell(event.themes),
        _dash_if_empty(event.eligibility),
        _dash_if_empty(event.cost),
        _list_cell(event.also_on),
        _ist_date(event.last_seen).isoformat(),
    ]


# --- document assembly ------------------------------------------------------


def _header(meta: Mapping[str, Any]) -> str:
    return (
        f"**Last updated:** {_last_updated_cell(meta.get('last_updated'))}"
        f" · open: {_meta_count(meta.get('open'))}"
        f" · online: {_meta_count(meta.get('online'))}"
        f" · new: {_meta_count(meta.get('new'))}"
    )


def _last_updated_cell(value: Any) -> str:
    """Format a ``last_updated`` datetime in IST; missing/invalid → ``—``."""
    if isinstance(value, datetime):
        return config.fmt_ist(value)
    return _DASH


def _meta_count(value: Any) -> str:
    """Echo a count; missing or an empty/blank string → ``—`` (0 stays 0)."""
    if value is None:
        return _DASH
    text = str(value)
    return text if text.strip() else _DASH


def _table(events: list[Event], meta: Mapping[str, Any]) -> str:
    lines = [
        "| " + " | ".join(COLUMNS) + " |",
        "| " + " | ".join("---" for _ in COLUMNS) + " |",
    ]
    for event in events:
        lines.append("| " + " | ".join(_cell(cell) for cell in _cells(event, meta)) + " |")
    return "\n".join(lines)


def _document(title: str, meta: Mapping[str, Any], events: list[Event]) -> str:
    """Title + blank + header + blank + table; ends with a newline."""
    return f"{title}\n\n{_header(meta)}\n\n{_table(events, meta)}\n"
