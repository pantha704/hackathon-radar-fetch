"""Tests for `radar.readme` — the README online-list seam.

Pure + file-level: no network, no run() involved. Pins the seam rulings:
- ``inject_online_section`` replaces exactly the text between the two
  markers (the start marker's line and the end marker are preserved
  verbatim; the injected body is ``online.md`` minus its H1 and blank
  edges, with its ``Last updated`` header relabeled ``Last fetched`` —
  the README's last-fetch date/time wording);
- a README without valid markers is returned unchanged — a hand-written
  README is never clobbered;
- ``update_readme`` writes only when the content actually changes, and
  reports (warning + False) a missing README or missing markers.
"""

import pytest

from radar import readme

ONLINE_MD = (
    "# Hackathon Radar — online only\n"
    "\n"
    "**Last updated:** 2026-10-11 09:00 IST · open: 1 · online: 1 · new: 0\n"
    "\n"
    "| Name | Platform |\n"
    "| --- | --- |\n"
    "| [Alpha](https://a.example) | devpost |\n"
)

README_TEXT = (
    "# Title\n"
    "\n"
    "Intro.\n"
    "\n"
    "<!-- ONLINE-LIST:START (auto-generated — do not edit) -->\n"
    "stale\n"
    "<!-- ONLINE-LIST:END -->\n"
    "\n"
    "Footer.\n"
)

EXPECTED = (
    "# Title\n"
    "\n"
    "Intro.\n"
    "\n"
    "<!-- ONLINE-LIST:START (auto-generated — do not edit) -->\n"
    "\n"
    "**Last fetched:** 2026-10-11 09:00 IST · open: 1 · online: 1 · new: 0\n"
    "\n"
    "| Name | Platform |\n"
    "| --- | --- |\n"
    "| [Alpha](https://a.example) | devpost |\n"
    "<!-- ONLINE-LIST:END -->\n"
    "\n"
    "Footer.\n"
)


def test_injects_exact_expected_text():
    assert readme.inject_online_section(README_TEXT, ONLINE_MD) == EXPECTED


def test_injection_is_idempotent():
    once = readme.inject_online_section(README_TEXT, ONLINE_MD)
    assert readme.inject_online_section(once, ONLINE_MD) == once


def test_section_body_strips_h1_and_relabels_header():
    assert readme.section_body(ONLINE_MD) == (
        "**Last fetched:** 2026-10-11 09:00 IST · open: 1 · online: 1 · new: 0\n"
        "\n"
        "| Name | Platform |\n"
        "| --- | --- |\n"
        "| [Alpha](https://a.example) | devpost |"
    )


@pytest.mark.parametrize(
    "text",
    [
        "no markers at all\n",
        "<!-- ONLINE-LIST:END -->\nold\n<!-- ONLINE-LIST:START -->\n",  # end first
        "<!-- ONLINE-LIST:START -->\nno end marker\n",
    ],
)
def test_unmarked_or_invalid_readme_is_unchanged(text):
    assert readme.inject_online_section(text, ONLINE_MD) == text


def test_update_readme_writes_only_when_changed(tmp_path):
    path = tmp_path / "README.md"
    path.write_text(README_TEXT, encoding="utf-8")

    assert readme.update_readme(path, ONLINE_MD) is True
    assert path.read_text(encoding="utf-8") == EXPECTED
    assert readme.update_readme(path, ONLINE_MD) is False  # second call: no-op


def test_update_readme_missing_file_warns(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        assert readme.update_readme(tmp_path / "nope.md", ONLINE_MD) is False

    assert "not found" in caplog.text


def test_update_readme_without_markers_warns_and_leaves_file(tmp_path, caplog):
    path = tmp_path / "README.md"
    path.write_text("# Hand written\n", encoding="utf-8")

    with caplog.at_level("WARNING"):
        assert readme.update_readme(path, ONLINE_MD) is False

    assert path.read_text(encoding="utf-8") == "# Hand written\n"
    assert "no ONLINE-LIST markers" in caplog.text
