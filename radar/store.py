"""JSON store: ``data/radar.json`` is the canonical dataset (Task 6).

Shape: ``{"meta": {...}, "events": [<Event.to_dict()>, ...]}``.

- ``load`` reads that shape back; a missing file is an empty store
  (``{"meta": {}, "events": []}``); malformed JSON raises — a corrupt store
  must fail loud, never read as "no events".
- ``save`` writes the canonical bytes: events are sorted by ``id`` for
  stable diffs, the payload is serialized with
  ``json.dumps(..., indent=2, ensure_ascii=False)``, then the text is
  written — two saves of the same data are byte-equal and a serialization
  error cannot truncate an existing file.
- ``load_events`` is the ``id -> Event`` view the runner uses (previous-run
  lookups, ``carry_first_seen``).
"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from radar.models import Event


def load(path: Path) -> dict[str, Any]:
    """Read the store; a missing file is ``{"meta": {}, "events": []}``.

    Malformed JSON raises (fail loud): a corrupt store must never be read
    as an empty one.
    """
    if not path.exists():
        return {"meta": {}, "events": []}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save(path: Path, events: Iterable[Event], meta: dict[str, Any]) -> None:
    """Write the store as deterministic JSON (parent dirs created).

    Events are sorted by ``id`` and the payload is serialized with
    ``indent=2`` + ``ensure_ascii=False``, so saving the same data twice is
    byte-equal (spec §7: deterministic output, clean git diffs). The text is
    produced *before* the target is opened: a serialization failure (e.g. a
    non-JSON meta) raises ``TypeError`` and leaves any existing
    ``radar.json`` untouched — never truncated.
    """
    payload = {
        "meta": meta,
        "events": [event.to_dict() for event in sorted(events, key=lambda e: e.id)],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_events(path: Path) -> dict[str, Event]:
    """Return ``id -> Event`` from the store; ``{}`` when the file is missing."""
    data = load(path)
    return {raw["id"]: Event.from_dict(raw) for raw in data.get("events") or []}
