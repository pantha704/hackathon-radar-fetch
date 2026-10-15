"""Shared data model: the normalized Event record for Hackathon Radar."""

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

STATUSES = {"open", "upcoming", "closed"}
MODES = {"online", "offline", "hybrid"}
EXTRACTED_BY = {"api", "css", "llm"}


def make_id(source: str, url: str) -> str:
    """Stable event id: first 12 hex chars of sha1("source|url")."""
    return hashlib.sha1(f"{source}|{url}".encode()).hexdigest()[:12]


@dataclass
class Event:
    """One normalized hackathon record (see GLOSSARY: Event).

    Required fields come first (dataclasses cannot put defaulted fields
    before required ones); construct with keyword arguments.
    ``id``, ``name``, ``source`` and ``url`` must be non-empty strings.
    Missing scalar values stay ``None`` and are never invented.
    """

    id: str
    name: str
    source: str
    url: str
    mode: str
    status: str
    first_seen: datetime
    last_seen: datetime
    extracted_by: str

    location: str | None = None
    reg_deadline: date | None = None
    start: date | None = None
    end: date | None = None
    team_min: int | None = None
    team_max: int | None = None
    solo_ok: bool | None = None
    prize: str | None = None
    themes: list[str] = field(default_factory=list)
    eligibility: str | None = None
    cost: str | None = None
    also_on: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("id", "name", "source", "url"):
            value = getattr(self, name)
            if not (isinstance(value, str) and value.strip()):
                raise ValueError(
                    f"invalid {name} {value!r}: expected a non-empty string"
                )
        if self.mode not in MODES:
            raise ValueError(
                f"invalid mode {self.mode!r}: expected one of {sorted(MODES)}"
            )
        if self.status not in STATUSES:
            raise ValueError(
                f"invalid status {self.status!r}: expected one of {sorted(STATUSES)}"
            )
        if self.extracted_by not in EXTRACTED_BY:
            raise ValueError(
                f"invalid extracted_by {self.extracted_by!r}: "
                f"expected one of {sorted(EXTRACTED_BY)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict; dates/timestamps as ISO 8601 strings."""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "url": self.url,
            "mode": self.mode,
            "location": self.location,
            "status": self.status,
            "reg_deadline": self.reg_deadline.isoformat() if self.reg_deadline else None,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "team_min": self.team_min,
            "team_max": self.team_max,
            "solo_ok": self.solo_ok,
            "prize": self.prize,
            "themes": list(self.themes),
            "eligibility": self.eligibility,
            "cost": self.cost,
            "also_on": list(self.also_on),
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "extracted_by": self.extracted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        """Rebuild an Event from ``to_dict()`` output (exact roundtrip).

        ISO strings are parsed as-is: a naive timestamp stays naive
        (no timezone is fabricated).
        """

        def _date(value: str | None) -> date | None:
            return date.fromisoformat(value) if value is not None else None

        return cls(
            id=data["id"],
            name=data["name"],
            source=data["source"],
            url=data["url"],
            mode=data["mode"],
            status=data["status"],
            first_seen=datetime.fromisoformat(data["first_seen"]),
            last_seen=datetime.fromisoformat(data["last_seen"]),
            extracted_by=data["extracted_by"],
            location=data.get("location"),
            reg_deadline=_date(data.get("reg_deadline")),
            start=_date(data.get("start")),
            end=_date(data.get("end")),
            team_min=data.get("team_min"),
            team_max=data.get("team_max"),
            solo_ok=data.get("solo_ok"),
            prize=data.get("prize"),
            themes=list(data.get("themes") or []),
            eligibility=data.get("eligibility"),
            cost=data.get("cost"),
            also_on=list(data.get("also_on") or []),
        )
