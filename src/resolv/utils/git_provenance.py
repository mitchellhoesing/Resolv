"""Git blame provenance — surfaces the commits that last touched a span of lines.

Used by the context broker to attach, to each code snippet shown to the coder,
the history of past changes (and their commit messages / intentions) for exactly
the lines the coder is about to modify.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

_ZERO_SHA = "0" * 40


def blame_provenance(
    workspace: str,
    file_path: str,
    start_line: int,
    end_line: int,
    *,
    max_commits: int = 3,
) -> tuple[str, ...]:
    """Return provenance for the commits touching ``[start_line, end_line]``.

    Each entry is ``"<short-sha> <YYYY-MM-DD> <author> — <summary>"``, most recent
    first, capped at ``max_commits``. Returns ``()`` when blame is unavailable
    (uncommitted file, not a git repo, or any git failure) — provenance is
    best-effort context, never a hard dependency.
    """
    result = subprocess.run(
        [
            "git",
            "blame",
            "--line-porcelain",
            "-L",
            f"{start_line},{end_line}",
            "--",
            file_path,
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ()
    return _parse_porcelain(result.stdout, max_commits)


def _parse_porcelain(output: str, max_commits: int) -> tuple[str, ...]:
    order: list[str] = []
    commits: dict[str, dict[str, str]] = {}
    current_sha: str | None = None
    for line in output.splitlines():
        head = line.split(" ", 1)[0]
        if len(head) == 40 and all(char in "0123456789abcdef" for char in head):
            current_sha = head
            if head != _ZERO_SHA and head not in commits:
                commits[head] = {}
                order.append(head)
            continue
        if current_sha is None or current_sha not in commits:
            continue
        meta = commits[current_sha]
        if line.startswith("author "):
            meta.setdefault("author", line[len("author ") :])
        elif line.startswith("author-time "):
            meta.setdefault("time", line[len("author-time ") :])
        elif line.startswith("summary "):
            meta.setdefault("summary", line[len("summary ") :])

    order.sort(key=lambda sha: int(commits[sha].get("time", "0")), reverse=True)
    entries: list[str] = []
    for sha in order[:max_commits]:
        meta = commits[sha]
        date = _format_date(meta.get("time", ""))
        author = meta.get("author", "unknown")
        summary = meta.get("summary", "")
        entries.append(f"{sha[:8]} {date} {author} — {summary}".rstrip(" —"))
    return tuple(entries)


def _format_date(epoch: str) -> str:
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).date().isoformat()
    except (ValueError, OverflowError, OSError):
        return "unknown-date"
