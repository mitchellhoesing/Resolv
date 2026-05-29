"""Unit tests for git-blame provenance extraction."""

from __future__ import annotations

import subprocess
from pathlib import Path

from resolv.utils.git_provenance import _parse_porcelain, blame_provenance


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


def _init_repo(path: Path) -> None:
    _run(["git", "init", "-q"], path)
    _run(["git", "config", "user.email", "dev@example.com"], path)
    _run(["git", "config", "user.name", "Dev Example"], path)


def test_blame_returns_commit_for_tracked_lines(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n")
    _run(["git", "add", "."], tmp_path)
    _run(["git", "commit", "-q", "-m", "add foo with off-by-one"], tmp_path)

    provenance = blame_provenance(str(tmp_path), "mod.py", 1, 2)

    assert len(provenance) == 1
    entry = provenance[0]
    assert "Dev Example" in entry
    assert "add foo with off-by-one" in entry


def test_blame_returns_empty_when_no_commits(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "mod.py").write_text("def foo():\n    return 1\n")
    # File is written but never committed: blame must fail gracefully.
    assert blame_provenance(str(tmp_path), "mod.py", 1, 2) == ()


def test_blame_returns_empty_outside_repo(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("x = 1\n")
    assert blame_provenance(str(tmp_path), "mod.py", 1, 1) == ()


def test_parse_porcelain_dedupes_and_orders_recent_first() -> None:
    porcelain = (
        "1111111111111111111111111111111111111111 1 1 1\n"
        "author Alice\n"
        "author-time 2000\n"
        "summary older change\n"
        "filename mod.py\n"
        "\tline one\n"
        "2222222222222222222222222222222222222222 2 2 1\n"
        "author Bob\n"
        "author-time 3000\n"
        "summary newer change\n"
        "filename mod.py\n"
        "\tline two\n"
        "1111111111111111111111111111111111111111 3 3 1\n"
        "\tline three\n"
    )
    entries = _parse_porcelain(porcelain, max_commits=3)

    assert len(entries) == 2  # the repeated sha is deduped
    assert entries[0].startswith("22222222")  # newer (author-time 3000) first
    assert "Bob — newer change" in entries[0]
    assert "Alice — older change" in entries[1]


def test_parse_porcelain_skips_uncommitted_sentinel() -> None:
    porcelain = (
        "0000000000000000000000000000000000000000 1 1 1\n"
        "author Not Committed Yet\n"
        "author-time 0\n"
        "summary Version of mod.py\n"
        "\tpending line\n"
    )
    assert _parse_porcelain(porcelain, max_commits=3) == ()
