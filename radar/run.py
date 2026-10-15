"""Runner: the `radar run` pipeline (Task 7).

One run: load the source registry → fetch → parse → normalize → dedupe →
store → render → commit/push (skippable). Rulings implemented here (SDD
Task 7, binding):

- Per-source isolation: a fetch/parse failure is recorded in ``failed``
  (``[{source, error}]``) and never blocks other sources.
- Empty-parse guard: a source that contributes 0 events while the previous
  store holds >= 1 NON-CLOSED rows for it is treated as a FAILURE ("parsed
  0 rows; previous run had N") — suspicious markup drift, not "no
  hackathons". With no prior history, or with a history whose rows have
  all legitimately closed, 0 rows is acceptable.
- Stale retention: a failed source's previous rows are kept exactly as-is
  (``last_seen`` untouched, status never recomputed — the run has no fresh
  evidence about them).
- Fresh events: ``last_seen = ctx["now"]``; status recomputed through
  ``normalize.compute_status`` with ``declared`` = the adapter's raw badge
  (read before the recompute); ``first_seen`` carried from the previous
  store by id (``carry_first_seen``).
- Cross-source ``dedupe`` runs over the collected fresh events (file order
  wins the merge).
- Store assembly: fresh + stale rows + previously closed rows (retained
  indefinitely). A successful source's previous rows that are absent from
  its fresh output are REMOVED (counted in ``removed``) unless already
  closed; rows of sources not attempted this run (filtered out) are kept
  as-is. Never fabricated, never kept stale.
- Meta conversion seam: ``render`` receives ``last_updated`` as the aware
  ``datetime``; ``store.save`` receives the same meta with
  ``last_updated`` as ``now.isoformat()`` (the store stays fail-loud and
  stores it verbatim).
- README seam: after the data files are written, the README's marked
  "Latest global remote hackathons" section is regenerated from the fresh
  ``online.md`` (``radar.readme``) — the README always lists the live
  online hackathons as of this run. Only canonical runs (default
  ``data_dir``) touch the README; a custom-dir preview leaves it alone.
  The README change is committed together with ``data``.
- Git: ``dry_run`` skips git entirely (files are still written); otherwise
  ``git add -- data README.md`` → commit ``data: radar run <ISO ts>`` only
  when ``git diff --cached --quiet -- data README.md`` reports staged
  changes → ``git push`` unless ``no_push``. Every git call is
  pathspec-bounded to ``data`` + ``README.md`` so unrelated pre-staged
  changes are never swept into the run commit, and a custom ``data_dir``
  combined with real git is rejected up front (git only ever commits the
  repo's ``data/``). Git failures raise ``RuntimeError`` carrying stderr
  (loud).

Counts (summary): ``open`` = status open; ``online`` = mode online among
status in {open, upcoming}; ``new`` = kept ids not in the previous store;
``updated`` = ids refreshed by this run (present in the post-dedupe fresh
output) that already existed in the previous store — stale, carried and
unselected rows never count; ``closed`` = events that transitioned to
closed this run (a previous non-closed row that is closed now — a
first-seen closed row is ``new``, not a transition); ``removed`` as above;
``total_open`` = the open count.
"""

import subprocess
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from radar import config
from radar import readme
from radar.adapters import ADAPTERS
from radar.models import Event
from radar.normalize import carry_first_seen, compute_status, dedupe
from radar.render import LIVE_STATUSES, archive, hackathons, online
from radar.store import load_events, save

SOURCES_PATH = config.ROOT / "radar" / "sources.yaml"
README_PATH = config.ROOT / "README.md"


def run(
    sources: list[str] | None = None,
    dry_run: bool = False,
    no_push: bool = False,
    limit: int | None = None,
    data_dir: Path | str | None = None,
    adapters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full pipeline; return the run summary.

    ``sources`` limits the run to those source ids (default: every enabled
    ``sources.yaml`` entry). ``dry_run`` skips git entirely (output files
    are still written). ``no_push`` commits but never pushes. ``limit``
    caps the events taken per source (must be >= 1 when given).
    ``data_dir`` overrides the output directory (default
    ``config.DATA_DIR``; a custom dir requires ``dry_run`` because git can
    only ever commit the repo's ``data/``). ``adapters`` replaces the live
    registry (tests inject fakes).

    Per-source failures never raise — they come back in ``failed[]``. Hard
    errors (limit < 1, custom ``data_dir`` with git enabled, corrupt
    registry, git failure) raise.
    """
    data_dir = Path(data_dir) if data_dir is not None else config.DATA_DIR
    if not dry_run and data_dir != config.DATA_DIR:
        raise ValueError(
            f"data_dir {data_dir} differs from the repo data dir "
            f"({config.DATA_DIR}) while git commit/push is enabled; "
            "pass --dry-run for custom output directories"
        )
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit!r}")
    registry = ADAPTERS if adapters is None else adapters

    now = config.ist_now()
    prev = load_events(data_dir / "radar.json")
    candidates, failed = _select_sources(sources)

    fresh_by_source: dict[str, list[Event]] = {}
    client = httpx.Client(timeout=30)
    ctx: dict[str, Any] = {"now": now, "http": client, "crawl": None}
    try:
        for entry in candidates:
            source_id = entry["id"]
            adapter = registry.get(source_id)
            if adapter is None:
                failed.append(
                    {
                        "source": source_id,
                        "error": f"no adapter registered for source {source_id!r}",
                    }
                )
                continue
            try:
                payload = adapter.fetch(ctx)
                events = list(adapter.parse(payload, ctx))
            except Exception as exc:  # per-source isolation: isolate and report
                failed.append({"source": source_id, "error": f"{type(exc).__name__}: {exc}"})
                continue
            if limit is not None:
                events = events[:limit]
            prev_rows = [e for e in prev.values() if e.source == source_id]
            # Closed history is not "expected fresh rows": a source whose
            # previous rows have all legitimately closed may parse 0 rows
            # without being a failure (its closed rows stay archived).
            prev_nonclosed = [e for e in prev_rows if e.status != "closed"]
            if not events and prev_nonclosed:
                failed.append(
                    {
                        "source": source_id,
                        "error": f"parsed 0 rows; previous run had {len(prev_nonclosed)}",
                    }
                )
                continue
            fresh_by_source[source_id] = carry_first_seen(
                [_refresh(e, now) for e in events], prev
            )
    finally:
        client.close()

    fresh_events = [event for events in fresh_by_source.values() for event in events]
    fresh_kept = dedupe(fresh_events)
    kept, removed = _assemble_store(prev, fresh_by_source, fresh_kept)

    prev_ids = set(prev)
    kept_ids = {event.id for event in kept}
    fresh_kept_ids = {event.id for event in fresh_kept}
    open_count = sum(1 for event in kept if event.status == "open")
    online_count = sum(
        1 for event in kept if event.status in LIVE_STATUSES and event.mode == "online"
    )
    closed_count = sum(
        1
        for event in kept
        if event.status == "closed"
        and event.id in prev
        and prev[event.id].status != "closed"
    )

    meta_counts = {"open": open_count, "online": online_count, "new": len(kept_ids - prev_ids)}
    meta_dt = {"last_updated": now, **meta_counts}
    meta_store = {"last_updated": now.isoformat(), **meta_counts}

    save(data_dir / "radar.json", kept, meta_store)
    renders = {
        "hackathons.md": hackathons(kept, meta_dt),
        "online.md": online(kept, meta_dt),
        "archive.md": archive(kept, meta_dt),
    }
    for name, text in renders.items():
        (data_dir / name).write_text(text, encoding="utf-8")
    if data_dir == config.DATA_DIR:
        # README seam: only canonical runs touch the repo's README (a
        # custom-dir preview must never dirty the worktree).
        readme.update_readme(README_PATH, renders["online.md"])

    if not dry_run:
        _commit_and_push(now, no_push)

    return {
        "new": len(kept_ids - prev_ids),
        "updated": len(fresh_kept_ids & prev_ids),
        "closed": closed_count,
        "removed": removed,
        "failed": failed,
        "total_open": open_count,
    }


def _refresh(event: Event, now: datetime) -> Event:
    """Restamp a freshly parsed event: ``last_seen = now``, status recomputed.

    ``declared`` is the adapter's raw badge, read before the recompute
    (``compute_status`` truth table: a declared-closed row is never
    resurrected). ``first_seen`` is left alone for ``carry_first_seen`` to
    restore from the previous store.
    """
    status = compute_status(
        now.astimezone(config.IST).date(),
        event.reg_deadline,
        event.start,
        event.end,
        declared=event.status,
    )
    return replace(event, last_seen=now, status=status)


def _select_sources(
    sources: list[str] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Load ``sources.yaml``: enabled candidates in scope + pre-flight failures.

    ``sources`` (when given) filters to those ids; a requested id that is
    unknown or disabled becomes a ``failed`` entry rather than a silent
    no-op. Invalid entries (not a dict / no non-empty string ``id``) are
    reported too, per the T7 rulings.
    """
    failed: list[dict[str, str]] = []
    enabled: dict[str, dict[str, Any]] = {}
    all_ids: set[str] = set()
    order: list[str] = []

    for index, raw in enumerate(_read_sources_yaml()):
        if not isinstance(raw, dict) or not (
            isinstance(raw.get("id"), str) and raw["id"].strip()
        ):
            failed.append(
                {
                    "source": f"<entry {index}>",
                    "error": "invalid sources.yaml entry: missing non-empty string id",
                }
            )
            continue
        source_id = raw["id"]
        all_ids.add(source_id)
        if raw.get("enabled") and source_id not in enabled:
            enabled[source_id] = raw
            order.append(source_id)

    requested_set = None
    if sources is not None:
        requested_set = set(sources)
        for source_id in dict.fromkeys(sources):  # preserve caller order, dedupe
            if source_id not in enabled:
                reason = (
                    "source is disabled in sources.yaml"
                    if source_id in all_ids
                    else "unknown source (no sources.yaml entry)"
                )
                failed.append({"source": source_id, "error": reason})

    candidates = [
        enabled[source_id]
        for source_id in order
        if requested_set is None or source_id in requested_set
    ]
    return candidates, failed


def _read_sources_yaml() -> list[Any]:
    """Parse ``radar/sources.yaml``; a corrupt registry is a hard error."""
    data = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8"))
    if data is None:
        return []
    if not isinstance(data, list):
        raise RuntimeError(f"{SOURCES_PATH} must contain a YAML list of sources")
    return data


def _assemble_store(
    prev: dict[str, Event],
    fresh_by_source: dict[str, list[Event]],
    kept_fresh: list[Event],
) -> tuple[list[Event], int]:
    """Final store: fresh + stale/retained rows; count the removals.

    - Successfully processed sources: previous rows absent from that
      source's fresh output are dropped (``removed``) unless already
      closed — closed history is retained indefinitely.
    - Failed sources and sources not attempted this run: every previous
      row is kept as-is (stale retention).
    """
    fresh_ids = {
        source_id: {event.id for event in events}
        for source_id, events in fresh_by_source.items()
    }
    kept = list(kept_fresh)
    removed = 0
    for event in prev.values():
        if event.source in fresh_ids:
            if event.id in fresh_ids[event.source]:
                continue  # superseded by this run's fresh copy (if any)
            if event.status == "closed":
                kept.append(event)
            else:
                removed += 1
        else:
            kept.append(event)
    return kept, removed


# --- git (injectable seam for tests) ----------------------------------------


def _git(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in the repo root; failures raise RuntimeError.

    ``check=False`` returns the raw result for probes whose exit code is
    meaningful (``git diff --cached --quiet``: 1 = staged changes).
    """
    result = subprocess.run(
        ["git", *args], cwd=config.ROOT, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _staged_changes() -> bool:
    """True when the ``data`` + ``README.md`` pathspec has staged changes vs HEAD.

    Probe: ``git diff --cached --quiet -- data README.md`` → 0 = clean,
    1 = staged changes. Pathspec-bounded so unrelated staged changes
    neither trigger a run commit nor get swept into one.
    """
    result = _git(
        ["diff", "--cached", "--quiet", "--", "data", "README.md"], check=False
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"git diff --cached --quiet failed: {(result.stderr or '').strip()}"
        )
    return result.returncode == 1


def _commit_and_push(now: datetime, no_push: bool) -> None:
    """Stage ``data/`` + ``README.md``, commit when staged, then push.

    All three invocations are pathspec-bounded to ``data`` + ``README.md``
    so unrelated pre-staged changes are never committed and never mistaken
    for "data changed".
    """
    _git(["add", "--", "data", "README.md"])
    if not _staged_changes():
        return  # no staged run diff: no commit, no push (clean tree stays clean)
    _git(["commit", "-m", f"data: radar run {now.isoformat()}", "--", "data", "README.md"])
    if not no_push:
        _git(["push"])
