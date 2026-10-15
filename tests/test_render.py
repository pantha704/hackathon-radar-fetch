"""Tests for radar.render (Task 6).

Golden strings for a small fixed event set pin the exact markdown byte for
byte, plus one assertion per ruling:
- closed rows never appear in live/online; live rows never in archive;
- Mode: ``Online`` / ``Offline — <location>`` / ``Hybrid — <location>``,
  location suppressed for online rows;
- sorts: live = online → hybrid → offline, days_left asc (None last), name;
  online = days_left asc (None last), name; archive = (end or start or
  last_seen-date) DESC, then name asc;
- missing values render ``—``; ``|`` → ``\\|``; newlines collapse to spaces;
- header echoes ``meta`` exactly (missing slot → ``—``).

Days left is derived per event from ``reg_deadline`` vs the **run date** —
the IST calendar date of ``meta.last_updated`` (GLOSSARY basis) — falling
back to the event's ``last_seen`` IST date only when meta has no valid
``last_updated``. The goldens below share the run and ``last_seen`` dates
(2026-10-09 IST), so values are: AI 3, Rust 1, Campus 21, Quiet 0 (past
deadline floors), everything else ``—``.
"""

from datetime import date, datetime, timezone

from radar import render
from radar.models import Event, make_id

SEEN = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
META = {
    "last_updated": datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc),  # → 22:30 IST
    "open": 4,
    "online": 3,
    "new": 2,
}
HEADER = "**Last updated:** 2026-10-09 22:30 IST · open: 4 · online: 3 · new: 2"
COLUMNS = (
    "| Name | Platform | Mode | Status | Reg. deadline | Days left | Starts | "
    "Ends | Team | Prize | Themes | Eligibility | Cost | Also on | Updated |"
)
DIVIDER = (
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | "
    "--- | --- | --- |"
)


def _ev(
    name,
    source,
    url,
    *,
    mode="online",
    status="open",
    location=None,
    reg_deadline=None,
    start=None,
    end=None,
    team_min=None,
    team_max=None,
    solo_ok=None,
    prize=None,
    themes=(),
    eligibility=None,
    cost=None,
    also_on=(),
    last_seen=SEEN,
):
    return Event(
        id=make_id(source, url),
        name=name,
        source=source,
        url=url,
        mode=mode,
        status=status,
        first_seen=SEEN,
        last_seen=last_seen,
        extracted_by="api",
        location=location,
        reg_deadline=reg_deadline,
        start=start,
        end=end,
        team_min=team_min,
        team_max=team_max,
        solo_ok=solo_ok,
        prize=prize,
        themes=list(themes),
        eligibility=eligibility,
        cost=cost,
        also_on=list(also_on),
    )


E_AI = _ev(
    "AI Builders Hack",
    "devpost",
    "https://devpost.com/software/ai-builders-hack",
    location="Online",  # raw adapter value; suppressed for online mode
    reg_deadline=date(2026, 10, 12),  # 3 days after last_seen
    start=date(2026, 10, 15),
    end=date(2026, 10, 17),
    team_min=2,
    team_max=4,
    solo_ok=True,
    prize="₹1,00,000",
    themes=("AI", "ML"),
    eligibility="Students",
    cost="Free",
    also_on=("devfolio",),
)
E_ANVIL = _ev(
    "Anvil Online Jam",
    "devpost",
    "https://devpost.com/software/anvil-online-jam",
    prize="Cloud credits\nand swag",  # newline must collapse to a space
    themes=("Cloud",),
    also_on=("devpost", "mlh"),
)
E_BETA = _ev(
    "Beta Online Jam",
    "devpost",
    "https://devpost.com/software/beta-online-jam",
)
E_HYBRID = _ev(
    "Hybrid Tech Marathon",
    "mlh",
    "https://mlh.io/events/hybrid-tech-marathon",
    mode="hybrid",
    status="upcoming",
    location="Bengaluru",
    start=date(2026, 11, 5),
    end=date(2026, 11, 7),
    team_min=3,
    team_max=3,
    solo_ok=False,
    prize="Swag",
    themes=("Web3",),
    eligibility="18+",
)
E_RUST = _ev(
    "Rust Game Jam '26 | Delhi",  # the pipe must be escaped in the cell
    "devfolio",
    "https://devfolio.co/rust-game-jam",
    mode="offline",
    location="New Delhi, India",
    reg_deadline=date(2026, 10, 10),  # 1 day after last_seen
    start=date(2026, 10, 20),
    solo_ok=True,
    cost="Free",
)
E_CAMPUS = _ev(
    "Campus Hack Night",
    "devpost",
    "https://devpost.com/software/campus-hack-night",
    mode="offline",
    status="upcoming",
    reg_deadline=date(2026, 10, 30),  # 21 days after last_seen
)
E_QUIET = _ev(
    "Quiet Archive Jam",
    "devpost",
    "https://devpost.com/software/quiet-archive-jam",
    status="closed",
    location="Online",
    reg_deadline=date(2026, 9, 20),  # 5 days BEFORE last_seen → floors at 0
    start=date(2026, 9, 10),
    end=date(2026, 9, 18),  # archive key
    team_min=1,  # min only → "1+"
    themes=("Open Data",),
    cost="Free",
    also_on=("lablab.ai",),
    last_seen=datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc),
)
E_EARLY = _ev(
    "Early Bird Data Sprint",
    "lablab.ai",
    "https://lablab.ai/event/early-bird-data-sprint",
    status="closed",
    start=date(2026, 9, 1),  # archive key (no end)
    last_seen=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
)
E_GHOST = _ev(
    "Legacy Ghost Hack",
    "devpost",
    "https://devpost.com/software/legacy-ghost-hack",
    mode="offline",
    status="closed",
    last_seen=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),  # archive key
)

EVENTS = [
    E_AI,
    E_ANVIL,
    E_BETA,
    E_HYBRID,
    E_RUST,
    E_CAMPUS,
    E_QUIET,
    E_EARLY,
    E_GHOST,
]

EXPECTED_LIVE = """\
# Hackathon Radar — live

**Last updated:** 2026-10-09 22:30 IST · open: 4 · online: 3 · new: 2

| Name | Platform | Mode | Status | Reg. deadline | Days left | Starts | Ends | Team | Prize | Themes | Eligibility | Cost | Also on | Updated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [AI Builders Hack](https://devpost.com/software/ai-builders-hack) | devpost | Online | open | 2026-10-12 | 3 | 2026-10-15 | 2026-10-17 | 2–4, solo ok | ₹1,00,000 | AI, ML | Students | Free | devfolio | 2026-10-09 |
| [Anvil Online Jam](https://devpost.com/software/anvil-online-jam) | devpost | Online | open | — | — | — | — | — | Cloud credits and swag | Cloud | — | — | devpost, mlh | 2026-10-09 |
| [Beta Online Jam](https://devpost.com/software/beta-online-jam) | devpost | Online | open | — | — | — | — | — | — | — | — | — | — | 2026-10-09 |
| [Hybrid Tech Marathon](https://mlh.io/events/hybrid-tech-marathon) | mlh | Hybrid — Bengaluru | upcoming | — | — | 2026-11-05 | 2026-11-07 | 3–3 | Swag | Web3 | 18+ | — | — | 2026-10-09 |
| [Rust Game Jam '26 \\| Delhi](https://devfolio.co/rust-game-jam) | devfolio | Offline — New Delhi, India | open | 2026-10-10 | 1 | 2026-10-20 | — | solo ok | — | — | — | Free | — | 2026-10-09 |
| [Campus Hack Night](https://devpost.com/software/campus-hack-night) | devpost | Offline | upcoming | 2026-10-30 | 21 | — | — | — | — | — | — | — | — | 2026-10-09 |
"""

EXPECTED_ONLINE = """\
# Hackathon Radar — online only

**Last updated:** 2026-10-09 22:30 IST · open: 4 · online: 3 · new: 2

| Name | Platform | Mode | Status | Reg. deadline | Days left | Starts | Ends | Team | Prize | Themes | Eligibility | Cost | Also on | Updated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [AI Builders Hack](https://devpost.com/software/ai-builders-hack) | devpost | Online | open | 2026-10-12 | 3 | 2026-10-15 | 2026-10-17 | 2–4, solo ok | ₹1,00,000 | AI, ML | Students | Free | devfolio | 2026-10-09 |
| [Anvil Online Jam](https://devpost.com/software/anvil-online-jam) | devpost | Online | open | — | — | — | — | — | Cloud credits and swag | Cloud | — | — | devpost, mlh | 2026-10-09 |
| [Beta Online Jam](https://devpost.com/software/beta-online-jam) | devpost | Online | open | — | — | — | — | — | — | — | — | — | — | 2026-10-09 |
"""

EXPECTED_ARCHIVE = """\
# Hackathon Radar — archive (closed)

**Last updated:** 2026-10-09 22:30 IST · open: 4 · online: 3 · new: 2

| Name | Platform | Mode | Status | Reg. deadline | Days left | Starts | Ends | Team | Prize | Themes | Eligibility | Cost | Also on | Updated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [Quiet Archive Jam](https://devpost.com/software/quiet-archive-jam) | devpost | Online | closed | 2026-09-20 | 0 | 2026-09-10 | 2026-09-18 | 1+ | — | Open Data | — | Free | lablab.ai | 2026-09-25 |
| [Early Bird Data Sprint](https://lablab.ai/event/early-bird-data-sprint) | lablab.ai | Online | closed | — | — | 2026-09-01 | — | — | — | — | — | — | — | 2026-10-01 |
| [Legacy Ghost Hack](https://devpost.com/software/legacy-ghost-hack) | devpost | Offline | closed | — | — | — | — | — | — | — | — | — | — | 2026-09-01 |
"""

EXPECTED_EMPTY = """\
# Hackathon Radar — live

**Last updated:** — · open: — · online: — · new: —

| Name | Platform | Mode | Status | Reg. deadline | Days left | Starts | Ends | Team | Prize | Themes | Eligibility | Cost | Also on | Updated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""

EXPECTED_PARTIAL_META = """\
# Hackathon Radar — live

**Last updated:** 2026-10-09 22:30 IST · open: — · online: — · new: —

| Name | Platform | Mode | Status | Reg. deadline | Days left | Starts | Ends | Team | Prize | Themes | Eligibility | Cost | Also on | Updated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""


# --- exact golden output ----------------------------------------------------


def test_hackathons_golden():
    assert render.hackathons(EVENTS, META) == EXPECTED_LIVE


def test_online_golden():
    assert render.online(EVENTS, META) == EXPECTED_ONLINE


def test_archive_golden():
    assert render.archive(EVENTS, META) == EXPECTED_ARCHIVE


def test_empty_table_and_missing_meta():
    assert render.hackathons([], {}) == EXPECTED_EMPTY


def test_partial_meta_header_golden():
    meta = {"last_updated": datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc)}
    assert render.hackathons([], meta) == EXPECTED_PARTIAL_META


def test_header_empty_or_invalid_slots_render_dash():
    line = render.hackathons(
        [], {"last_updated": "", "open": "", "online": 0, "new": "2"}
    )
    assert line.splitlines()[2] == "**Last updated:** — · open: — · online: 0 · new: 2"
    # ISO strings are the store's shape; this slot only takes an aware datetime.
    line = render.hackathons([], {"last_updated": "2026-10-09T22:30:00+05:30"})
    assert line.splitlines()[2] == "**Last updated:** — · open: — · online: — · new: —"


def test_document_structure_title_header_table_newline():
    text = render.archive([], META)
    lines = text.splitlines()
    assert lines[0] == "# Hackathon Radar — archive (closed)"
    assert lines[1] == ""
    assert lines[2] == HEADER
    assert lines[3] == ""
    assert lines[4] == COLUMNS
    assert lines[5] == DIVIDER
    assert text.endswith("\n")


# --- filters ----------------------------------------------------------------


def test_closed_events_absent_from_live_and_online():
    for text in (render.hackathons(EVENTS, META), render.online(EVENTS, META)):
        assert "Quiet Archive Jam" not in text
        assert "Early Bird Data Sprint" not in text
        assert "Legacy Ghost Hack" not in text


def test_live_events_absent_from_archive():
    text = render.archive(EVENTS, META)
    for event in (E_AI, E_ANVIL, E_BETA, E_HYBRID, E_RUST, E_CAMPUS):
        assert event.name not in text


# --- days_left: run-date basis ----------------------------------------------


def test_days_left_stale_row_uses_run_date_not_last_seen():
    stale = _ev(
        "Stale Row Hack",
        "devpost",
        "https://devpost.com/software/stale-row-hack",
        reg_deadline=date(2026, 10, 12),
        last_seen=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
    )
    text = render.hackathons([stale], META)  # run date: 2026-10-09 IST
    (row,) = [line for line in text.splitlines() if line.startswith("| [")]
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[5] == "3"  # 10-12 − 10-09 (run), not − 10-01 (last_seen → 11)


def test_days_left_stale_rows_sort_on_run_date_basis():
    stale = _ev(
        "Stale Row Hack",
        "devpost",
        "https://devpost.com/software/stale-row-hack",
        reg_deadline=date(2026, 10, 5),  # passed by the run date → 0
        last_seen=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),  # basis would say 4
    )
    fresh = _ev(
        "Fresh Row Jam",
        "devpost",
        "https://devpost.com/software/fresh-row-jam",
        reg_deadline=date(2026, 10, 11),  # 2 on either basis
    )
    text = render.hackathons([fresh, stale], META)
    # Run basis: 0 sorts before 2; the last_seen basis would wrongly sort stale (4) last.
    assert text.index("Stale Row Hack") < text.index("Fresh Row Jam")


# --- sorts ------------------------------------------------------------------


def test_days_left_none_sorts_last_then_name():
    text = render.hackathons(EVENTS, META)
    assert text.index("AI Builders Hack") < text.index("Anvil Online Jam")
    assert text.index("Anvil Online Jam") < text.index("Beta Online Jam")
    assert text.index("Rust Game Jam") < text.index("Campus Hack Night")


def test_mode_group_order_online_then_hybrid_then_offline():
    text = render.hackathons(EVENTS, META)
    # Beta (online, no deadline) still precedes Rust (offline, 1 day left):
    # the mode group outranks days_left.
    assert text.index("Beta Online Jam") < text.index("Hybrid Tech Marathon")
    assert text.index("Hybrid Tech Marathon") < text.index("Rust Game Jam")


def test_archive_newest_first_then_name():
    text = render.archive(EVENTS, META)
    assert text.index("Quiet Archive Jam") < text.index("Early Bird Data Sprint")
    # tie on the date key (2026-09-01) → name ascending
    assert text.index("Early Bird Data Sprint") < text.index("Legacy Ghost Hack")


# --- cell rules -------------------------------------------------------------


def test_online_location_suppressed_for_online_rows():
    text = render.online(EVENTS, META)
    assert "| devpost | Online | open |" in text
    assert "Online —" not in text


def test_every_missing_value_renders_dash():
    event = _ev("Bare Hack", "devpost", "https://devpost.com/software/bare-hack")
    text = render.hackathons([event], META)
    (row,) = [line for line in text.splitlines() if line.startswith("| [")]
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert len(cells) == 15
    assert cells[4:14] == ["—"] * 10  # reg..also_on all unknown
    assert cells[14] == "2026-10-09"
    assert cells[2] == "Online"


def test_team_max_only_renders_leq():
    event = _ev(
        "Max Only Hack",
        "devpost",
        "https://devpost.com/software/max-only-hack",
        team_max=4,
    )
    text = render.hackathons([event], META)
    assert "| ≤4 |" in text


def test_naive_last_seen_taken_as_is_and_used_only_as_fallback():
    event = _ev(
        "Naive Clock Hack",
        "devpost",
        "https://devpost.com/software/naive-clock-hack",
        reg_deadline=date(2026, 10, 8),
        last_seen=datetime(2026, 10, 5, 23, 30),  # naive: taken as-is, no tz invented
    )
    # No valid meta last_updated → fallback basis is the naive last_seen date.
    text = render.hackathons([event], {})
    (row,) = [line for line in text.splitlines() if line.startswith("| [")]
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[5] == "3"  # 10-08 − 10-05
    assert cells[14] == "2026-10-05"  # Updated: naive date as-is
    # With a valid run date the meta basis wins (deadline already passed → 0).
    text = render.hackathons([event], META)
    (row,) = [line for line in text.splitlines() if line.startswith("| [")]
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[5] == "0"


def test_pipe_escaped_and_newlines_collapse():
    text = render.hackathons(EVENTS, META)
    assert "Rust Game Jam '26 \\| Delhi" in text
    assert "Cloud credits and swag" in text
    assert "Cloud credits\nand swag" not in text


# --- purity / determinism ---------------------------------------------------


def test_render_does_not_mutate_events():
    before = [event.to_dict() for event in EVENTS]
    order = [event.id for event in EVENTS]
    render.hackathons(EVENTS, META)
    render.online(EVENTS, META)
    render.archive(EVENTS, META)
    assert [event.to_dict() for event in EVENTS] == before
    assert [event.id for event in EVENTS] == order


def test_output_is_deterministic_and_input_order_independent():
    assert render.hackathons(EVENTS, META) == render.hackathons(EVENTS, META)
    shuffled = list(reversed(EVENTS))
    assert render.hackathons(shuffled, META) == render.hackathons(EVENTS, META)
    assert render.online(shuffled, META) == render.online(EVENTS, META)
    assert render.archive(shuffled, META) == render.archive(EVENTS, META)
