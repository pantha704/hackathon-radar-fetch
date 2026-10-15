"""Tests for `radar.readme` — the README online-list seam.

Pure + file-level: no network, no run() involved. Pins the seam rulings:
- ``inject_online_section`` replaces exactly the text between the two
  markers (the start marker's line and the end marker are preserved
  verbatim; the injected body is ``online.md`` minus its H1 and blank
  edges, with its ``Last updated`` header relabeled ``Last fetched`` —
  the README's last-fetch date/time wording — and its table slimmed to
  ``README_COLUMNS``);
- ``slim_table`` drops the constant/empty columns (Mode, Team, Eligibility,
  Cost, Also on, Updated), relabels the kept headers, preserves cell
  content including ``\\|`` escaping, and never rewrites an unrecognized
  table;
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
    "| Name | Platform | Mode | Status | Reg. deadline | Days left | Team | Updated |\n"
    "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
    "| [Alpha](https://a.example) | devpost | Online | open | 2026-10-14 | 3 | — | 2026-10-11 |\n"
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
    "| Name | Platform | Status | Deadline | Days |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| [Alpha](https://a.example) | devpost | open | 2026-10-14 | 3 |\n"
    "<!-- ONLINE-LIST:END -->\n"
    "\n"
    "Footer.\n"
)


def test_injects_exact_expected_text():
    assert readme.inject_online_section(README_TEXT, ONLINE_MD) == EXPECTED


def test_injection_is_idempotent():
    once = readme.inject_online_section(README_TEXT, ONLINE_MD)
    assert readme.inject_online_section(once, ONLINE_MD) == once


def test_section_body_strips_h1_relabels_header_and_slims_table():
    assert readme.section_body(ONLINE_MD) == (
        "**Last fetched:** 2026-10-11 09:00 IST · open: 1 · online: 1 · new: 0\n"
        "\n"
        "| Name | Platform | Status | Deadline | Days |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| [Alpha](https://a.example) | devpost | open | 2026-10-14 | 3 |"
    )


REAL_HEADER = (
    "| Name | Platform | Mode | Status | Reg. deadline | Days left | Starts | Ends "
    "| Team | Prize | Themes | Eligibility | Cost | Also on | Updated |"
)


def test_slim_table_real_online_header_keeps_exactly_the_readme_columns():
    text = REAL_HEADER + "\n" + "| " + " | ".join("---" for _ in range(15)) + " |"

    slimmed = readme.slim_table(text).splitlines()

    assert slimmed[0] == (
        "| Name | Platform | Status | Deadline | Days | Starts | Ends | Prize | Themes |"
    )
    assert slimmed[1] == "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"


def test_slim_table_preserves_escaped_pipes():
    text = (
        "| Name | Platform | Mode | Status |\n"
        "| --- | --- | --- | --- |\n"
        "| [Arc Microgrants \\| Circle](https://x.example) | dorahacks | Online | open |\n"
    )

    rows = readme.slim_table(text).splitlines()

    assert rows[2] == "| [Arc Microgrants \\| Circle](https://x.example) | dorahacks | open |"


def test_slim_table_unrecognized_table_is_unchanged():
    text = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    assert readme.slim_table(text) == text


def test_slim_table_no_table_is_unchanged():
    text = "just prose\nno table here\n"
    assert readme.slim_table(text) == text


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
