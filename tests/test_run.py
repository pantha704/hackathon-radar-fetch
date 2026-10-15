"""Tests for `radar.run` + the `radar run` CLI wiring (Task 7).

Network-free by construction: fake adapters are injected through
``run.run(adapters=...)`` and git is intercepted by faking
``radar.run._git`` (spy), so nothing touches the network, the real
``data/`` directory or a remote.

Pins the T7 rulings:
- happy path: two sources, four output files, real IST header + counts;
- per-source isolation: a raising source lands in ``failed[]`` with its
  previous rows kept as-is (stale retention, ``last_seen`` untouched);
- ``updated`` = |refreshed-this-run kept ids ∩ prev|: stale/carried/
  unselected rows never count (fix pass);
- empty-parse guard: 0 parsed rows with prior NON-CLOSED history = failure,
  stale rows kept; 0 parsed rows with no history, or with only-closed
  history, is acceptable;
- input guards (fix pass): ``limit`` < 1 rejected before any fetch (never
  reaches the empty-parse guard); a custom ``data_dir`` combined with real
  git raises up front; corrupt ``sources.yaml`` is a hard error;
- cross-source ``dedupe``; ``first_seen`` carry; ``limit`` slicing;
- store assembly: a successful source's vanished rows are removed while
  previously closed rows are retained indefinitely; rows of sources not
  attempted this run (filtered out) are kept as-is;
- git: dry_run = no git at all; no_push = commit without push; clean
  index = no commit; default = add/diff/commit/push; every git call is
  pathspec-bounded to ``data`` + ``README.md`` and failures raise
  RuntimeError carrying stderr (fix pass);
- README seam: a canonical run (default ``data_dir``) regenerates the
  README's marked online-list section from the fresh ``online.md``; a
  custom-dir preview leaves the README untouched;
- meta conversion seam: ``radar.json`` gets the ISO string, markdown gets
  the aware datetime (real formatted IST header, never "—");
- summary keys exactly {new, updated, closed, removed, failed, total_open}.
"""

import json
import re
from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
import yaml

from radar import config
from radar import run as radar_run
from radar.cli import main
from radar.models import Event, make_id
from radar.store import load_events, save

OLD = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
FUTURE = date(2099, 1, 1)  # date-independent: always ahead of "today"
PAST = date(2020, 1, 1)  # date-independent: always behind "today"
SEED_META = {"last_updated": "2026-01-01T00:00:00+00:00", "open": 0, "online": 0, "new": 0}

HEADER_RE = re.compile(
    r"\*\*Last updated:\*\* \d{4}-\d{2}-\d{2} \d{2}:\d{2} IST"
    r" · open: \d+ · online: \d+ · new: \d+"
)

SUMMARY_KEYS = {"new", "updated", "closed", "removed", "failed", "total_open"}


@pytest.fixture(autouse=True)
def readme_path(monkeypatch, tmp_path):
    """Keep every test off the repo's real README (canonical runs update it)."""
    monkeypatch.setattr(radar_run, "README_PATH", tmp_path / "README.md")
    return tmp_path / "README.md"


def _event(
    source,
    slug,
    *,
    name=None,
    mode="online",
    status="open",
    start=None,
    reg_deadline=FUTURE,
    end=None,
    first_seen=OLD,
    last_seen=OLD,
):
    url = f"https://{source}.example.com/{slug}"
    return Event(
        id=make_id(source, url),
        name=name or slug.replace("-", " ").title(),
        source=source,
        url=url,
        mode=mode,
        status=status,
        first_seen=first_seen,
        last_seen=last_seen,
        extracted_by="api",
        start=start,
        reg_deadline=reg_deadline,
        end=end,
    )


class FakeAdapter:
    """Minimal adapter stand-in: canned payload, canned events or an error.

    Mirrors the Adapter contract: ``parse`` stamps new events with
    ``ctx["now"]``.
    """

    kind = "api"

    def __init__(self, source_id, events=(), raises=None):
        self.id = source_id
        self._events = list(events)
        self._raises = raises

    def fetch(self, ctx):
        if self._raises is not None:
            raise self._raises
        return {"source": self.id}

    def parse(self, payload, ctx):
        now = ctx["now"]
        return [replace(e, first_seen=now, last_seen=now) for e in self._events]


class RecordingAdapter(FakeAdapter):
    """FakeAdapter that counts ``fetch`` calls (proves the pipeline never ran)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fetches = 0

    def fetch(self, ctx):
        self.fetches += 1
        return super().fetch(ctx)


class GitSpy:
    """Stand-in for ``radar.run._git``: records calls, fakes the diff probe."""

    def __init__(self, staged_changes=True):
        self.calls = []
        self._staged_changes = staged_changes

    def __call__(self, args, check=True):
        args = list(args)
        self.calls.append(args)
        exit_code = (1 if self._staged_changes else 0) if args[0] == "diff" else 0
        return SimpleNamespace(returncode=exit_code, stdout="", stderr="")

    def names(self):
        return [args[0] for args in self.calls]


def _run(tmp_path, adapters, **kwargs):
    kwargs.setdefault("dry_run", True)
    kwargs.setdefault("data_dir", tmp_path)
    return radar_run.run(adapters=adapters, **kwargs)


def _seed(tmp_path, *events):
    save(tmp_path / "radar.json", list(events), dict(SEED_META))


# --- happy path -------------------------------------------------------------


def test_happy_path_two_sources_writes_all_outputs(tmp_path):
    dp = FakeAdapter(
        "devpost",
        [
            _event("devpost", "alpha", mode="online"),
            _event("devpost", "beta", mode="offline", status="upcoming", reg_deadline=None),
            _event("devpost", "gamma", mode="hybrid", status="closed"),
        ],
    )
    df = FakeAdapter("devfolio", [_event("devfolio", "delta", mode="hybrid")])
    summary = _run(tmp_path, {"devpost": dp, "devfolio": df}, sources=["devpost", "devfolio"])

    for name in ("radar.json", "hackathons.md", "online.md", "archive.md"):
        assert (tmp_path / name).is_file()

    assert summary == {
        "new": 4,
        "updated": 0,
        "closed": 0,  # a first-seen closed row is new, not a transition
        "removed": 0,
        "failed": [],
        "total_open": 2,
    }

    hack = (tmp_path / "hackathons.md").read_text(encoding="utf-8")
    online_md = (tmp_path / "online.md").read_text(encoding="utf-8")
    archive_md = (tmp_path / "archive.md").read_text(encoding="utf-8")
    assert "Alpha" in hack and "Beta" in hack and "Delta" in hack
    assert "Gamma" not in hack and "Gamma" in archive_md
    assert "Alpha" in online_md
    assert "Beta" not in online_md and "Delta" not in online_md and "Gamma" not in online_md

    header = hack.splitlines()[2]
    assert HEADER_RE.fullmatch(header), header
    assert "—" not in header  # REAL formatted IST datetime, not the missing marker
    assert "open: 2" in header and "online: 1" in header and "new: 4" in header

    kept = load_events(tmp_path / "radar.json")
    assert len(kept) == 4
    assert all(e.last_seen.tzinfo is not None and e.last_seen > OLD for e in kept.values())


# --- per-source isolation + stale retention ---------------------------------


def test_failed_source_is_reported_and_its_rows_stay_stale(tmp_path):
    stale = _event("devfolio", "stale", mode="offline", status="upcoming", reg_deadline=None)
    _seed(tmp_path, stale)
    dp = FakeAdapter("devpost", [_event("devpost", "alpha")])
    df = FakeAdapter("devfolio", raises=RuntimeError("boom"))

    summary = _run(tmp_path, {"devpost": dp, "devfolio": df}, sources=["devpost", "devfolio"])

    assert summary == {
        "new": 1,
        "updated": 0,  # the stale row was NOT refreshed this run -> never counted
        "closed": 0,
        "removed": 0,
        "failed": [{"source": "devfolio", "error": "RuntimeError: boom"}],
        "total_open": 1,
    }
    kept = load_events(tmp_path / "radar.json")
    assert stale.id in kept
    assert kept[stale.id].last_seen == OLD  # stale: untouched
    assert kept[stale.id].status == "upcoming"  # never recomputed


def test_suspicious_empty_parse_is_a_failure_that_keeps_stale_rows(tmp_path):
    one = _event("devfolio", "one")
    two = _event("devfolio", "two")
    _seed(tmp_path, one, two)
    df = FakeAdapter("devfolio", [])  # 0 rows while history has 2 -> markup drift

    summary = _run(tmp_path, {"devfolio": df}, sources=["devfolio"])

    assert summary["failed"] == [
        {"source": "devfolio", "error": "parsed 0 rows; previous run had 2"}
    ]
    assert summary["removed"] == 0
    assert summary["updated"] == 0 and summary["new"] == 0  # zero fresh rows at all
    kept = load_events(tmp_path / "radar.json")
    assert set(kept) == {one.id, two.id}
    assert all(kept[e.id].last_seen == OLD for e in (one, two))


def test_empty_parse_with_only_closed_history_is_accepted(tmp_path):
    """A source whose rows all closed legitimately can parse 0 fresh rows."""
    closed = _event("devfolio", "ended", status="closed")
    _seed(tmp_path, closed)
    df = FakeAdapter("devfolio", [])  # between seasons: history is all closed

    summary = _run(tmp_path, {"devfolio": df}, sources=["devfolio"])

    assert summary["failed"] == []  # closed history is not "expected rows"
    kept = load_events(tmp_path / "radar.json")
    assert closed.id in kept  # closed history retained
    assert kept[closed.id].last_seen == OLD


def test_empty_parse_with_no_history_is_accepted(tmp_path):
    summary = _run(tmp_path, {"devfolio": FakeAdapter("devfolio", [])}, sources=["devfolio"])

    assert summary["failed"] == []
    assert summary["new"] == 0 and summary["total_open"] == 0
    assert load_events(tmp_path / "radar.json") == {}


# --- updated semantics (fix pass) -------------------------------------------


def test_updated_counts_only_rows_refreshed_this_run(tmp_path):
    """``updated`` = |fresh kept ids ∩ prev| — stale rows never count."""
    refreshed = _event("devpost", "alpha")  # comes back this run -> refreshed
    stale = _event("devfolio", "stale", mode="offline", status="upcoming", reg_deadline=None)
    _seed(tmp_path, refreshed, stale)
    dp = FakeAdapter("devpost", [_event("devpost", "alpha"), _event("devpost", "beta")])
    df = FakeAdapter("devfolio", raises=RuntimeError("boom"))

    summary = _run(tmp_path, {"devpost": dp, "devfolio": df})

    assert summary["updated"] == 1  # only alpha (refreshed); the stale row is excluded
    assert summary["new"] == 1  # beta
    kept = load_events(tmp_path / "radar.json")
    assert kept[refreshed.id].last_seen > OLD  # refreshed
    assert kept[stale.id].last_seen == OLD  # retained as-is, never counted


# --- input guards (fix pass) ------------------------------------------------


def test_limit_zero_is_rejected_before_any_fetch(tmp_path):
    """limit=0 must never reach the empty-parse guard (or any fetch)."""
    _seed(tmp_path, _event("devpost", "one"), _event("devpost", "two"))
    adapter = RecordingAdapter("devpost", [_event("devpost", "one"), _event("devpost", "two")])

    with pytest.raises(ValueError, match="limit must be >= 1"):
        radar_run.run(
            adapters={"devpost": adapter},
            sources=["devpost"],
            dry_run=True,
            data_dir=tmp_path,
            limit=0,
        )

    assert adapter.fetches == 0  # guarded before any fetch
    kept = load_events(tmp_path / "radar.json")
    assert len(kept) == 2 and all(e.last_seen == OLD for e in kept.values())  # untouched


def test_limit_one_is_accepted(tmp_path):
    dp = FakeAdapter("devpost", [_event("devpost", "one"), _event("devpost", "two")])

    summary = _run(tmp_path, {"devpost": dp}, sources=["devpost"], limit=1)

    assert summary["new"] == 1
    assert len(load_events(tmp_path / "radar.json")) == 1


def test_custom_data_dir_with_real_git_raises_before_any_fetch(tmp_path):
    adapter = RecordingAdapter("devpost", [_event("devpost", "alpha")])

    with pytest.raises(ValueError, match="dry-run"):
        radar_run.run(
            adapters={"devpost": adapter},
            sources=["devpost"],
            dry_run=False,
            data_dir=tmp_path,
        )

    assert adapter.fetches == 0  # guarded before any fetch
    assert not (tmp_path / "radar.json").exists()
    assert not (tmp_path / "hackathons.md").exists()


def test_corrupt_sources_yaml_is_a_hard_error(tmp_path, monkeypatch):
    bad = tmp_path / "sources.yaml"
    monkeypatch.setattr(radar_run, "SOURCES_PATH", bad)

    bad.write_text("id: devpost\nenabled: true\n", encoding="utf-8")  # dict, not a list
    with pytest.raises(RuntimeError, match="must contain a YAML list"):
        radar_run.run(dry_run=True, data_dir=tmp_path, adapters={})

    bad.write_text("[unterminated", encoding="utf-8")  # not valid YAML at all
    with pytest.raises(yaml.YAMLError):
        radar_run.run(dry_run=True, data_dir=tmp_path, adapters={})

    assert not (tmp_path / "radar.json").exists()  # died before writing anything


# --- normalize / store assembly ---------------------------------------------


def test_cross_source_duplicates_merge_into_one_row(tmp_path):
    shared_start = date(2026, 12, 1)
    dp_ev = _event("devpost", "shared", name="Shared Hack", start=shared_start)
    df_ev = _event("devfolio", "shared", name="Shared Hack", start=shared_start)

    summary = _run(
        tmp_path,
        {"devpost": FakeAdapter("devpost", [dp_ev]), "devfolio": FakeAdapter("devfolio", [df_ev])},
    )

    kept = load_events(tmp_path / "radar.json")
    assert len(kept) == 1  # merged, never double-counted
    assert kept[dp_ev.id].also_on == ["devfolio"]  # first source in file order wins
    assert summary["new"] == 1 and summary["removed"] == 0


def test_first_seen_is_carried_from_previous_store(tmp_path):
    old_first = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    was = _event("devpost", "alpha", first_seen=old_first, last_seen=old_first)
    _seed(tmp_path, was)
    dp = FakeAdapter("devpost", [_event("devpost", "alpha")])  # same url -> same id

    summary = _run(tmp_path, {"devpost": dp}, sources=["devpost"])

    kept = load_events(tmp_path / "radar.json")[was.id]
    assert kept.first_seen == old_first  # carried forward
    assert kept.last_seen > old_first  # this run's stamp
    assert summary["updated"] == 1 and summary["new"] == 0


def test_limit_slices_events_per_source(tmp_path):
    one = _event("devpost", "one")
    two = _event("devpost", "two")
    three = _event("devpost", "three")
    dp = FakeAdapter("devpost", [one, two, three])

    summary = _run(tmp_path, {"devpost": dp}, sources=["devpost"], limit=2)

    kept = load_events(tmp_path / "radar.json")
    assert set(kept) == {one.id, two.id}  # first two in parse order
    assert summary["new"] == 2


def test_closed_counts_transitions_only_never_resurrects(tmp_path):
    was_open = _event("devpost", "alpha", name="Alpha Hack")
    _seed(tmp_path, was_open)
    now_ended = _event("devpost", "alpha", name="Alpha Hack", end=PAST)  # end < today -> closed
    brand_new_closed = _event("devpost", "ended", name="Fresh Ended", status="closed")
    dp = FakeAdapter("devpost", [now_ended, brand_new_closed])

    summary = _run(tmp_path, {"devpost": dp}, sources=["devpost"])

    assert summary["closed"] == 1  # the open -> closed transition; first-seen closed not counted
    kept = load_events(tmp_path / "radar.json")
    assert kept[was_open.id].status == "closed"
    assert kept[brand_new_closed.id].status == "closed"
    archive_md = (tmp_path / "archive.md").read_text(encoding="utf-8")
    assert "Alpha Hack" in archive_md and "Fresh Ended" in archive_md
    assert "Alpha Hack" not in (tmp_path / "hackathons.md").read_text(encoding="utf-8")


def test_vanished_row_removed_but_closed_history_retained(tmp_path):
    vanished = _event("devpost", "vanished", status="open")
    closed_old = _event("devpost", "closed-old", status="closed")
    _seed(tmp_path, vanished, closed_old)
    dp = FakeAdapter("devpost", [_event("devpost", "alpha")])

    summary = _run(tmp_path, {"devpost": dp}, sources=["devpost"])

    kept = load_events(tmp_path / "radar.json")
    assert vanished.id not in kept  # absent from a successful source -> removed
    assert closed_old.id in kept  # closed history is retained indefinitely
    assert summary == {
        "new": 1,
        "updated": 0,  # retained closed row is not refreshed this run
        "closed": 0,
        "removed": 1,
        "failed": [],
        "total_open": 1,
    }


def test_rows_of_sources_not_attempted_this_run_are_retained(tmp_path):
    other = _event("devfolio", "other")
    _seed(tmp_path, other)
    dp = FakeAdapter("devpost", [_event("devpost", "alpha")])

    summary = _run(tmp_path, {"devpost": dp}, sources=["devpost"])

    kept = load_events(tmp_path / "radar.json")
    assert other.id in kept and kept[other.id].last_seen == OLD
    assert summary["failed"] == []
    assert summary["updated"] == 0 and summary["new"] == 1 and summary["removed"] == 0


def test_requested_unknown_source_is_reported(tmp_path):
    summary = _run(tmp_path, {"devpost": FakeAdapter("devpost", [])}, sources=["nope"])

    assert summary["failed"] == [
        {"source": "nope", "error": "unknown source (no sources.yaml entry)"}
    ]
    assert summary["new"] == 0


def test_missing_adapter_is_reported_and_rows_kept(tmp_path):
    row = _event("devpost", "old")
    _seed(tmp_path, row)

    summary = _run(tmp_path, {}, sources=["devpost"])

    assert summary["failed"] == [
        {"source": "devpost", "error": "no adapter registered for source 'devpost'"}
    ]
    assert load_events(tmp_path / "radar.json")[row.id].last_seen == OLD


# --- git --------------------------------------------------------------------


def test_dry_run_writes_files_but_touches_no_git(tmp_path, monkeypatch):
    spy = GitSpy()
    monkeypatch.setattr(radar_run, "_git", spy)

    _run(tmp_path, {"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])},
         sources=["devpost"])

    assert spy.calls == []
    assert (tmp_path / "radar.json").is_file()


def test_no_push_commits_but_never_pushes(tmp_path, monkeypatch):
    spy = GitSpy(staged_changes=True)
    monkeypatch.setattr(radar_run, "_git", spy)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)  # guard: real git only for repo data/

    _run(tmp_path, {"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])},
         sources=["devpost"], dry_run=False, no_push=True)

    assert spy.names() == ["add", "diff", "commit"]
    commit = spy.calls[2]
    assert commit[:2] == ["commit", "-m"] and commit[3:] == ["--", "data", "README.md"]
    assert commit[2].startswith("data: radar run ")
    stamp = datetime.fromisoformat(commit[2].removeprefix("data: radar run "))
    assert stamp.tzinfo is not None  # ISO 8601 with offset


def test_push_happens_by_default(tmp_path, monkeypatch):
    spy = GitSpy(staged_changes=True)
    monkeypatch.setattr(radar_run, "_git", spy)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    _run(tmp_path, {"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])},
         sources=["devpost"], dry_run=False)

    assert spy.names() == ["add", "diff", "commit", "push"]


def test_clean_index_skips_commit_and_push(tmp_path, monkeypatch):
    spy = GitSpy(staged_changes=False)
    monkeypatch.setattr(radar_run, "_git", spy)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    _run(tmp_path, {"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])},
         sources=["devpost"], dry_run=False)

    assert spy.names() == ["add", "diff"]  # no staged diff -> no commit, no push


def test_every_git_call_is_pathspec_bounded_to_data_and_readme(tmp_path, monkeypatch):
    spy = GitSpy(staged_changes=True)
    monkeypatch.setattr(radar_run, "_git", spy)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    _run(tmp_path, {"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])},
         sources=["devpost"], dry_run=False)

    assert spy.calls[0] == ["add", "--", "data", "README.md"]
    assert spy.calls[1] == ["diff", "--cached", "--quiet", "--", "data", "README.md"]
    assert spy.calls[2][:2] == ["commit", "-m"]
    assert spy.calls[2][2].startswith("data: radar run ")
    assert spy.calls[2][3:] == ["--", "data", "README.md"]
    assert spy.calls[3] == ["push"]


def test_git_nonzero_exit_raises_runtime_error_with_stderr(monkeypatch):
    result = SimpleNamespace(returncode=128, stdout="", stderr="fatal: not a git repository")
    monkeypatch.setattr(radar_run.subprocess, "run", lambda *a, **k: result)

    with pytest.raises(RuntimeError) as excinfo:
        radar_run._git(["push"])

    message = str(excinfo.value)
    assert "git push" in message and "failed" in message
    assert "fatal: not a git repository" in message

    with pytest.raises(RuntimeError, match="fatal: not a git repository"):
        radar_run._git(["add", "--", "data"])


# --- README seam ------------------------------------------------------------

README_MARKERS = "<!-- ONLINE-LIST:START (auto) -->\nstale\n<!-- ONLINE-LIST:END -->\n"


def _readme_text():
    return "# Test README\n\nIntro.\n\n## Latest\n\n" + README_MARKERS + "\n## Footer\n\nEnd.\n"


def test_canonical_run_regenerates_readme_online_section(tmp_path, monkeypatch, readme_path):
    readme_path.write_text(_readme_text(), encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)  # canonical dir for this run

    radar_run.run(
        adapters={"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])},
        sources=["devpost"],
        dry_run=True,
        data_dir=None,
    )

    text = readme_path.read_text(encoding="utf-8")
    assert "stale" not in text
    assert "<!-- ONLINE-LIST:START (auto) -->" in text  # marker line preserved
    assert "<!-- ONLINE-LIST:END -->" in text
    assert "**Last updated:**" in text and "| Name | Platform |" in text
    assert "Alpha" in text  # the fresh online.md row
    assert text.startswith("# Test README") and text.endswith("End.\n")


def test_custom_data_dir_preview_leaves_readme_untouched(tmp_path, readme_path):
    original = _readme_text()
    readme_path.write_text(original, encoding="utf-8")

    _run(tmp_path, {"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])},
         sources=["devpost"])  # custom data_dir -> README untouched

    assert readme_path.read_text(encoding="utf-8") == original


def test_readme_change_is_committed_with_data(tmp_path, monkeypatch, readme_path):
    spy = GitSpy(staged_changes=True)
    monkeypatch.setattr(radar_run, "_git", spy)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    readme_path.write_text(_readme_text(), encoding="utf-8")

    radar_run.run(
        adapters={"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])},
        sources=["devpost"],
        dry_run=False,
        data_dir=None,
    )

    assert spy.names() == ["add", "diff", "commit", "push"]
    assert spy.calls[0] == ["add", "--", "data", "README.md"]


# --- meta conversion seam ---------------------------------------------------


def test_meta_conversion_store_gets_iso_render_gets_datetime(tmp_path):
    _run(tmp_path, {"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])},
         sources=["devpost"])

    meta = json.loads((tmp_path / "radar.json").read_text(encoding="utf-8"))["meta"]
    assert isinstance(meta["last_updated"], str)  # store keeps the ISO string (fail-loud)
    stamp = datetime.fromisoformat(meta["last_updated"])
    assert stamp.tzinfo is not None

    header = (tmp_path / "hackathons.md").read_text(encoding="utf-8").splitlines()[2]
    assert HEADER_RE.fullmatch(header), header
    rendered = datetime.strptime(
        header.removeprefix("**Last updated:** ").split(" IST")[0], "%Y-%m-%d %H:%M"
    )
    expected = stamp.astimezone(config.IST).replace(tzinfo=None, second=0, microsecond=0)
    assert rendered == expected  # render received the aware datetime, not "—"
    assert "open: 1 · online: 1 · new: 1" in header


def test_summary_keys_are_exact(tmp_path):
    summary = _run(
        tmp_path, {"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])},
        sources=["devpost"],
    )

    assert set(summary) == SUMMARY_KEYS


# --- CLI wiring -------------------------------------------------------------


def test_cli_run_dry_run_with_fake_registry(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        radar_run, "ADAPTERS", {"devpost": FakeAdapter("devpost", [_event("devpost", "alpha")])}
    )

    code = main(["run", "--sources", "devpost", "--dry-run", "--data-dir", str(tmp_path)])

    assert code == 0
    out = capsys.readouterr().out
    assert "new=1" in out and "total_open=1" in out
    assert "failed: none" in out
    assert f"output: {tmp_path}" in out
    assert (tmp_path / "hackathons.md").is_file()


def test_cli_run_partial_failure_exits_zero(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        radar_run,
        "ADAPTERS",
        {
            "devpost": FakeAdapter("devpost", [_event("devpost", "alpha")]),
            "devfolio": FakeAdapter("devfolio", raises=RuntimeError("boom")),
        },
    )

    code = main(["run", "--dry-run", "--data-dir", str(tmp_path)])

    assert code == 0  # partial success is ok; failures are listed, others proceed
    out = capsys.readouterr().out
    assert "failed: devfolio: RuntimeError: boom" in out


def test_cli_run_hard_error_exits_one(tmp_path, capsys, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(radar_run, "run", boom)

    code = main(["run", "--dry-run", "--data-dir", str(tmp_path)])

    assert code == 1
    assert "radar run failed" in capsys.readouterr().out
