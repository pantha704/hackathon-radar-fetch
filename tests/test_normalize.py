"""Tests for radar.normalize (Task 5).

Pins the bindings from the task brief + SDD rulings:
- ``compute_status(today, reg_deadline, start, end, declared)`` truth table:
  a declared "closed" is never resurrected; ``end < today`` → closed; else a
  present deadline gives "open" (``>= today``) or "upcoming" (``< today``
  when not over); otherwise the declared badge passes through.
- ``days_left``: None when the deadline is unknown; otherwise
  ``max(0, (reg_deadline - today).days)``.
- ``dedupe``: group key = normalized(name) + ISO(start) when the start is
  known; rows with an unknown start additionally key on host(url). The
  first row of a group wins; merged-away sources append to ``also_on``
  (deduplicated, stable order).
- ``carry_first_seen``: match by ``id`` against the previous run; on a hit
  the previous ``first_seen`` is re-adopted and the new ``last_seen`` kept.
"""

from datetime import date, datetime, timezone

import pytest

from radar.models import Event, make_id
from radar.normalize import carry_first_seen, compute_status, days_left, dedupe

TODAY = date(2026, 10, 9)
PAST = date(2026, 10, 1)
YESTERDAY = date(2026, 10, 8)
TOMORROW = date(2026, 10, 10)
FUTURE = date(2026, 11, 1)
NOW = datetime(2026, 10, 9, 18, 30, tzinfo=timezone.utc)
EARLIER = datetime(2026, 9, 20, 7, 0, tzinfo=timezone.utc)


def _event(
    source="devpost",
    url="https://devpost.com/software/ai-hack",
    name="AI Hackathon",
    status="open",
    start=FUTURE,
    end=None,
    reg_deadline=None,
    also_on=None,
    first_seen=NOW,
    last_seen=NOW,
    **overrides,
):
    """Build a valid Event with test-friendly defaults."""
    kwargs = dict(
        id=make_id(source, url),
        name=name,
        source=source,
        url=url,
        mode="online",
        status=status,
        first_seen=first_seen,
        last_seen=last_seen,
        extracted_by="api",
        start=start,
        end=end,
        reg_deadline=reg_deadline,
        also_on=list(also_on) if also_on is not None else [],
    )
    kwargs.update(overrides)
    return Event(**kwargs)


# --- compute_status: full truth table (ruling 2) ----------------------------


@pytest.mark.parametrize(
    "reg_deadline,start,end,declared,expected",
    [
        # a. declared "closed" — never resurrected, whatever the dates say
        (FUTURE, FUTURE, FUTURE, "closed", "closed"),
        (None, None, None, "closed", "closed"),
        (PAST, TOMORROW, FUTURE, "closed", "closed"),
        # a+b combined: declared closed AND already ended, no deadline
        (None, PAST, YESTERDAY, "closed", "closed"),
        # b. event over (end < today) → closed
        (None, PAST, YESTERDAY, "open", "closed"),
        (FUTURE, PAST, YESTERDAY, "upcoming", "closed"),
        (PAST, PAST, YESTERDAY, "open", "closed"),
        # b boundary: end == today is not over yet
        (None, None, TODAY, "open", "open"),
        # c. deadline present, event not over
        (TODAY, None, None, "open", "open"),
        (TODAY, TOMORROW, FUTURE, "upcoming", "open"),
        (FUTURE, FUTURE, FUTURE, "open", "open"),
        (FUTURE, None, None, "upcoming", "open"),
        (PAST, PAST, FUTURE, "open", "upcoming"),
        (YESTERDAY, TOMORROW, FUTURE, "open", "upcoming"),
        (PAST, None, None, "open", "upcoming"),
        (YESTERDAY, None, TODAY, "upcoming", "upcoming"),
        # d. no deadline, not over → declared passes through
        (None, FUTURE, FUTURE, "open", "open"),
        (None, FUTURE, FUTURE, "upcoming", "upcoming"),
        (None, None, None, "open", "open"),
        (None, None, None, "upcoming", "upcoming"),
    ],
    ids=[
        "declared-closed-all-future",
        "declared-closed-all-none",
        "declared-closed-deadline-past",
        "declared-closed-end-past-no-deadline",
        "end-past-no-deadline",
        "end-past-deadline-future",
        "end-past-deadline-past",
        "end-today-not-over-yet",
        "deadline-today-open",
        "deadline-today-overrides-upcoming-badge",
        "deadline-future-open",
        "deadline-future-overrides-upcoming-badge",
        "deadline-past-end-future-upcoming",
        "deadline-past-start-future-upcoming",
        "deadline-past-no-end-upcoming",
        "deadline-past-end-today-upcoming",
        "no-deadline-declared-open",
        "no-deadline-declared-upcoming",
        "all-none-declared-open",
        "all-none-declared-upcoming",
    ],
)
def test_compute_status_truth_table(reg_deadline, start, end, declared, expected):
    assert compute_status(TODAY, reg_deadline, start, end, declared) == expected


def test_compute_status_accepts_declared_as_keyword():
    assert compute_status(TODAY, None, None, None, declared="upcoming") == "upcoming"


# --- days_left --------------------------------------------------------------


@pytest.mark.parametrize(
    "reg_deadline,expected",
    [
        (None, None),
        (TODAY, 0),
        (TOMORROW, 1),
        (date(2026, 11, 8), 30),
        (YESTERDAY, 0),
        (date(2026, 9, 1), 0),
    ],
    ids=["unknown", "today", "tomorrow", "thirty-days", "yesterday-floors", "long-past-floors"],
)
def test_days_left(reg_deadline, expected):
    assert days_left(TODAY, reg_deadline) == expected


# --- dedupe -----------------------------------------------------------------


def test_dedupe_merges_two_rows_for_the_same_event_and_keeps_the_first():
    # Ruled key: normalized(name) + ISO(start) — host/path/query do not
    # matter for dated rows; the first row wins outright.
    first = _event(source="devpost", url="https://devpost.com/software/ai-hack")
    second = _event(source="devfolio", url="https://devpost.com/software/ai-hack?ref=mirror")
    out = dedupe([first, second])
    assert len(out) == 1
    (kept,) = out
    assert kept.id == first.id
    assert kept.source == "devpost"
    assert kept.url == first.url
    assert kept.name == first.name
    assert kept.start == first.start
    assert kept.status == "open"
    assert kept.also_on == ["devfolio"]


def test_dedupe_normalizes_title_for_grouping():
    first = _event(name="AI  Hackathon!!")
    second = _event(
        source="devfolio",
        url="https://devpost.com/software/ai-hack-2",
        name=" ai  hackathon ",
    )
    assert len(dedupe([first, second])) == 1


def test_dedupe_normalizes_host_case_for_dateless_grouping():
    # host(url) only enters the key for rows whose start is unknown.
    first = _event(url="https://devpost.com/software/ai-hack", start=None)
    second = _event(source="devfolio", url="https://DEVPOST.com/software/ai-hack", start=None)
    assert len(dedupe([first, second])) == 1


def test_dedupe_merges_same_title_and_start_across_different_hosts():
    # Review ruling: dated rows key on title + start only, so the same
    # event on devpost.com and devfolio.co merges into one row; the first
    # row wins and the merged-away source lands in ``also_on``.
    first = _event(source="devpost", url="https://devpost.com/software/ai-hack")
    second = _event(source="devfolio", url="https://devfolio.co/ai-hack")
    out = dedupe([first, second])
    assert len(out) == 1
    (kept,) = out
    assert kept.id == first.id
    assert kept.url == first.url
    assert kept.source == "devpost"
    assert kept.also_on == ["devfolio"]


def test_dedupe_does_not_merge_same_title_with_a_different_start():
    first = _event(start=date(2026, 11, 1))
    second = _event(
        source="devfolio",
        url="https://devpost.com/software/ai-hack-2",
        start=date(2026, 12, 1),
    )
    assert len(dedupe([first, second])) == 2


def test_dedupe_does_not_merge_cross_platform_rows_with_different_starts():
    # Same title but different starts stay apart even across hosts.
    first = _event(
        source="devpost",
        url="https://devpost.com/software/ai-hack",
        start=date(2026, 11, 1),
    )
    second = _event(
        source="devfolio",
        url="https://devfolio.co/ai-hack",
        start=date(2026, 12, 1),
    )
    assert len(dedupe([first, second])) == 2


def test_dedupe_does_not_merge_same_start_with_a_different_title():
    first = _event(name="AI Hackathon")
    second = _event(
        source="devfolio",
        url="https://devpost.com/software/ai-hack-2",
        name="Climate Hackathon",
    )
    assert len(dedupe([first, second])) == 2


def test_dedupe_does_not_merge_dateless_rows_across_different_hosts():
    # start is None on both → host(url) is part of the key, so dateless
    # rows from two platforms stay apart.
    first = _event(source="devpost", url="https://devpost.com/software/ai-hack", start=None)
    second = _event(source="devfolio", url="https://devfolio.co/ai-hack", start=None)
    assert len(dedupe([first, second])) == 2


def test_dedupe_merges_dateless_rows_within_the_same_host():
    first = _event(source="devpost", url="https://devpost.com/software/ai-hack", start=None)
    second = _event(source="devfolio", url="https://devpost.com/software/ai-hack-2", start=None)
    out = dedupe([first, second])
    assert len(out) == 1
    assert out[0].id == first.id
    assert out[0].also_on == ["devfolio"]


def test_dedupe_groups_none_starts_together_but_not_with_dated_starts():
    a = _event(name="TBA Hack", start=None)
    b = _event(
        source="devfolio", url="https://devpost.com/software/tba", name="TBA Hack", start=None
    )
    c = _event(
        source="mlh",
        url="https://devpost.com/software/tba-2",
        name="TBA Hack",
        start=date(2026, 11, 1),
    )
    out = dedupe([a, b, c])
    assert len(out) == 2
    assert out[0].also_on == ["devfolio"]
    assert out[1].also_on == []


def test_dedupe_appends_merged_sources_deduped_and_stable():
    first = _event(also_on=["mlh"])
    second = _event(source="devfolio", url="https://devpost.com/software/ai-hack-2")
    third = _event(source="mlh", url="https://devpost.com/software/ai-hack-3")
    out = dedupe([first, second, third])
    assert len(out) == 1
    assert out[0].also_on == ["mlh", "devfolio"]


def test_dedupe_preserves_first_occurrence_order_of_kept_events():
    a = _event(name="A", url="https://devpost.com/software/a")
    b = _event(name="B", url="https://devpost.com/software/b")
    a2 = _event(source="devfolio", url="https://devpost.com/software/a-mirror", name="A")
    out = dedupe([a, b, a2])
    assert [event.name for event in out] == ["A", "B"]


def test_dedupe_does_not_mutate_inputs():
    first = _event()
    second = _event(source="devfolio", url="https://devpost.com/software/ai-hack-2")
    dedupe([first, second])
    assert first.also_on == []
    assert second.also_on == []


def test_dedupe_is_idempotent():
    first = _event()
    second = _event(source="devfolio", url="https://devpost.com/software/ai-hack-2")
    once = dedupe([first, second])
    assert dedupe(once) == once


def test_dedupe_of_empty_list_is_empty():
    assert dedupe([]) == []


# --- carry_first_seen -------------------------------------------------------


def test_carry_first_seen_adopts_previous_first_seen_and_keeps_new_last_seen():
    previous = _event(first_seen=EARLIER, last_seen=EARLIER)
    fresh = _event(first_seen=NOW, last_seen=NOW)
    out = carry_first_seen([fresh], {previous.id: previous})
    assert len(out) == 1
    assert out[0].id == fresh.id
    assert out[0].first_seen == EARLIER
    assert out[0].last_seen == NOW


def test_carry_first_seen_missing_id_leaves_event_unchanged():
    fresh = _event(first_seen=NOW, last_seen=NOW)
    other = _event(url="https://devpost.com/software/other", first_seen=EARLIER, last_seen=EARLIER)
    out = carry_first_seen([fresh], {other.id: other})
    assert out[0].first_seen == NOW


def test_carry_first_seen_empty_prev_is_a_noop():
    fresh = _event()
    assert carry_first_seen([fresh], {}) == [fresh]


def test_carry_first_seen_does_not_mutate_inputs():
    previous = _event(first_seen=EARLIER, last_seen=EARLIER)
    fresh = _event(first_seen=NOW, last_seen=NOW)
    carry_first_seen([fresh], {previous.id: previous})
    assert fresh.first_seen == NOW


def test_carry_first_seen_mixes_hits_and_misses_in_order():
    old_a = _event(name="A", url="https://devpost.com/software/a", first_seen=EARLIER, last_seen=EARLIER)
    fresh_a = _event(name="A", url="https://devpost.com/software/a", first_seen=NOW, last_seen=NOW)
    fresh_b = _event(name="B", url="https://devpost.com/software/b", first_seen=NOW, last_seen=NOW)
    out = carry_first_seen([fresh_a, fresh_b], {old_a.id: old_a})
    assert [event.id for event in out] == [fresh_a.id, fresh_b.id]
    assert out[0].first_seen == EARLIER
    assert out[1].first_seen == NOW
