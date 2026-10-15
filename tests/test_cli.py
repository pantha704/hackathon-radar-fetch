"""Tests for the radar CLI shell and config module (Task 1 scaffold).

Includes the Task 7 fix-pass guards: `run` argparse errors for empty
``--sources`` / non-positive ``--limit``, and a corrupt ``sources.yaml``
hard-erroring through the CLI as exit code 1. All network-free.
"""

from datetime import datetime, timedelta, timezone

import pytest

from radar import config
from radar.cli import main


def test_version(capsys):
    assert main(["--version"]) == 0
    assert "radar 0.1.0" in capsys.readouterr().out


def test_no_args_prints_help_and_returns_zero(capsys):
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_run_is_wired_to_the_runner(tmp_path, capsys, monkeypatch):
    """`run` now invokes radar.run.run — the stub message is gone (Task 7)."""
    calls = {}

    def fake_run(**kwargs):
        calls.update(kwargs)
        return {
            "new": 0,
            "updated": 0,
            "closed": 0,
            "removed": 0,
            "failed": [],
            "total_open": 0,
        }

    monkeypatch.setattr("radar.run.run", fake_run)
    code = main(["run", "--dry-run", "--no-push", "--limit", "5", "--data-dir", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert calls == {
        "sources": None,
        "dry_run": True,
        "no_push": True,
        "limit": 5,
        "data_dir": tmp_path,
    }
    assert f"output: {tmp_path}" in out


def test_config_paths_are_repo_rooted():
    assert config.DATA_DIR == config.ROOT / "data"
    assert (config.ROOT / "radar" / "config.py").is_file()


def test_ist_now_is_ist_aware():
    now = config.ist_now()
    assert now.utcoffset() == timedelta(hours=5, minutes=30)


def test_fmt_ist_converts_to_ist():
    utc = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert config.fmt_ist(utc) == "2026-10-09 17:30 IST"


# --- run CLI guards (Task 7 fix pass) ---------------------------------------


def test_run_empty_sources_is_an_argparse_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--sources", " , ", "--dry-run"])

    assert excinfo.value.code == 2
    assert "--sources needs at least one source id" in capsys.readouterr().err


def test_run_limit_zero_is_an_argparse_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--limit", "0", "--dry-run"])

    assert excinfo.value.code == 2
    assert "--limit must be >= 1" in capsys.readouterr().err


def test_run_corrupt_sources_yaml_exits_one(tmp_path, capsys, monkeypatch):
    from radar import run as radar_run

    bad = tmp_path / "sources.yaml"
    bad.write_text("[unterminated", encoding="utf-8")  # not parseable YAML
    monkeypatch.setattr(radar_run, "SOURCES_PATH", bad)

    code = main(["run", "--dry-run", "--data-dir", str(tmp_path)])

    assert code == 1
    assert "radar run failed" in capsys.readouterr().out
