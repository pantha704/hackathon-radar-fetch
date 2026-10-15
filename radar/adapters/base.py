"""Adapter contract shared by every source adapter (see GLOSSARY: Adapter)."""

from abc import ABC, abstractmethod
from typing import Any

from radar.models import Event


class Adapter(ABC):
    """One source adapter: fetch a source's payload, then normalize it.

    Attributes:
        id: source id — matches the `radar/sources.yaml` entry and
            `Event.source`.
        kind: how the adapter fetches: `api` (JSON endpoint via httpx),
            `browser` (rendered page) or `hybrid` (both).

    Methods:
        fetch(ctx): return this source's raw payload. May use network
            resources from `ctx` (`http` client, `crawl` callable); the
            fetch layer owns retries/backoff hardening.
        parse(payload, ctx): normalize a payload into `Event` records.
            Pure function: every value comes from `payload` + `ctx` (no
            network, no clock reads); new Events are stamped with
            `ctx["now"]` for `first_seen`/`last_seen`.
    """

    id: str
    kind: str

    @abstractmethod
    def fetch(self, ctx: dict[str, Any]) -> Any:
        """Fetch this source's raw payload (payload shape is adapter-specific)."""

    @abstractmethod
    def parse(self, payload: Any, ctx: dict[str, Any]) -> list[Event]:
        """Normalize a fetched payload into Events (pure: payload + ctx only)."""
