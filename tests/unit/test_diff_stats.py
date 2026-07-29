"""Unit tests for the shared diff description helper."""

from __future__ import annotations

from resolv.utils.diff_stats import describe_diff


def test_empty_diff_reports_no_files_changed() -> None:
    assert describe_diff("") == "no files changed"


def test_missing_diff_reports_no_files_changed() -> None:
    assert describe_diff(None) == "no files changed"


def test_counts_added_and_removed_lines_in_one_file() -> None:
    diff = (
        "diff --git a/x.py b/x.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,3 +1,4 @@\n"
        " unchanged context\n"
        "-old line\n"
        "+new line\n"
        "+extra line\n"
    )

    assert describe_diff(diff) == "wrote +2/-1 lines across 1 file(s)"


def test_counts_files_across_a_multi_file_diff() -> None:
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/y.py b/y.py\n"
        "--- a/y.py\n"
        "+++ b/y.py\n"
        "@@ -1 +1 @@\n"
        "-gone\n"
        "+here\n"
    )

    assert describe_diff(diff) == "wrote +2/-2 lines across 2 file(s)"


def test_file_headers_are_not_counted_as_changed_lines() -> None:
    """The ---/+++ headers precede the first @@, so they must not inflate the counts."""
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -0,0 +1 @@\n"
        "+only addition\n"
    )

    assert describe_diff(diff) == "wrote +1/-0 lines across 1 file(s)"


def test_changed_lines_whose_content_starts_with_dashes_are_counted() -> None:
    """A removed '--flag' line renders as '---flag' — prefix matching would drop it."""
    diff = (
        "diff --git a/args.txt b/args.txt\n"
        "--- a/args.txt\n"
        "+++ b/args.txt\n"
        "@@ -1,2 +1,2 @@\n"
        "---verbose\n"
        "+++quiet\n"
    )

    assert describe_diff(diff) == "wrote +1/-1 lines across 1 file(s)"
