"""Shared diff description — the one place a unified diff is summarized for humans."""

from __future__ import annotations


def describe_diff(diff: str | None) -> str:
    """Changed-line and changed-file counts for one unified diff.

    Returns a clause ("wrote +2/-1 lines across 1 file(s)", "no files changed")
    that reads as the tail of a sentence its caller has already begun. Used by
    the coder node's run-log line and by the end-of-run summary, so the two
    report the same measurement in the same words. The diff's content stays out
    of both — it is unbounded, and `--verbose` on the run summary is the opt-in
    for seeing it.
    """
    if not diff:
        return "no files changed"
    added_lines = 0
    removed_lines = 0
    changed_file_count = 0
    inside_hunk = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            changed_file_count += 1
            inside_hunk = False
        elif line.startswith("@@"):
            # The ---/+++ file headers precede the first @@ of their file, so
            # only counting inside a hunk excludes them without a prefix test —
            # which would misread a removed line whose own content starts '--'.
            inside_hunk = True
        elif inside_hunk and line.startswith("+"):
            added_lines += 1
        elif inside_hunk and line.startswith("-"):
            removed_lines += 1
    return (
        f"wrote +{added_lines}/-{removed_lines} lines "
        f"across {changed_file_count} file(s)"
    )
