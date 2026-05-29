"""Unit tests for the context broker node."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from resolv.core.state import BlackboardState, IssueRef
from resolv.exceptions import IngestionError
from resolv.nodes.context_broker import make_context_broker_node


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(path), check=True)


def _commit_all(path: Path, message: str) -> None:
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(path), check=True)
    subprocess.run(["git", "add", "."], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=str(path), check=True)


def _state_for(path: Path, title: str = "fix foo", body: str = "") -> BlackboardState:
    issue = IssueRef(owner="a", repo="b", number=1, title=title, body=body, labels=())
    return BlackboardState(issue=issue, workspace_path=path)


def test_extracts_chunks_whose_symbol_appears_in_issue(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "module.py").write_bytes(
        b"def foo():\n    return 1\n\ndef unrelated():\n    return 2\n"
    )
    node = make_context_broker_node(max_chunks=10)
    result = node(_state_for(tmp_path, title="bug in foo"))
    chunks = result["pruned_context"]
    assert [c.symbol for c in chunks] == ["foo"]
    assert chunks[0].file_path == "module.py"
    assert "return 1" in chunks[0].snippet


def test_attaches_blame_provenance_to_surfaced_chunks(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "module.py").write_bytes(b"def foo():\n    return 1\n")
    _commit_all(tmp_path, "introduce foo")
    node = make_context_broker_node(max_chunks=10)
    chunks = node(_state_for(tmp_path, title="bug in foo"))["pruned_context"]
    assert chunks[0].provenance  # non-empty
    assert "introduce foo" in chunks[0].provenance[0]


def test_falls_back_to_first_definitions_when_no_name_matches(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "m.py").write_bytes(b"def alpha():\n    pass\n\ndef beta():\n    pass\n")
    node = make_context_broker_node(max_chunks=10)
    result = node(_state_for(tmp_path, title="unrelated title", body=""))
    names = [c.symbol for c in result["pruned_context"]]
    assert "alpha" in names and "beta" in names


def test_respects_max_chunks(tmp_path: Path) -> None:
    _init_git(tmp_path)
    body = b"\n\n".join(f"def sym{i}():\n    pass".encode() for i in range(20))
    (tmp_path / "m.py").write_bytes(body)
    node = make_context_broker_node(max_chunks=3)
    result = node(_state_for(tmp_path, title="sym0 sym1 sym2 sym3 sym4"))
    assert len(result["pruned_context"]) == 3


def test_ignores_venv_and_git_directories(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "noisy.py").write_bytes(b"def foo(): pass\n")
    (tmp_path / "real.py").write_bytes(b"def foo():\n    return 1\n")
    node = make_context_broker_node(max_chunks=10)
    result = node(_state_for(tmp_path, title="foo bug"))
    files = {c.file_path for c in result["pruned_context"]}
    assert files == {"real.py"}


@pytest.mark.parametrize(
    "excluded_dir",
    [".venv", "env", ".env", "virtualenv", ".virtualenv", ".tox"],
)
def test_ignores_alternately_named_virtualenvs(
    tmp_path: Path, excluded_dir: str
) -> None:
    _init_git(tmp_path)
    (tmp_path / excluded_dir).mkdir()
    (tmp_path / excluded_dir / "noisy.py").write_bytes(b"def foo(): pass\n")
    (tmp_path / "real.py").write_bytes(b"def foo():\n    return 1\n")
    node = make_context_broker_node(max_chunks=10)
    result = node(_state_for(tmp_path, title="foo bug"))
    files = {c.file_path for c in result["pruned_context"]}
    assert files == {"real.py"}


def test_ignores_site_packages_in_unconventional_venv(tmp_path: Path) -> None:
    _init_git(tmp_path)
    site_packages = tmp_path / "weirdname" / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True)
    (site_packages / "noisy.py").write_bytes(b"def foo(): pass\n")
    (tmp_path / "real.py").write_bytes(b"def foo():\n    return 1\n")
    node = make_context_broker_node(max_chunks=10)
    result = node(_state_for(tmp_path, title="foo bug"))
    files = {c.file_path for c in result["pruned_context"]}
    assert files == {"real.py"}


def test_clone_invoked_when_no_git_present(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    target = tmp_path / "workspace"

    def fake_clone(url: str, to_path: str) -> None:
        Path(to_path).mkdir(parents=True)
        (Path(to_path) / ".git").mkdir()
        (Path(to_path) / "m.py").write_bytes(b"def foo(): return 1\n")

    fake_repo = mocker.patch(
        "resolv.nodes.context_broker.Repo.clone_from", side_effect=fake_clone
    )
    node = make_context_broker_node(max_chunks=5)
    result = node(_state_for(target, title="foo bug"))
    fake_repo.assert_called_once()
    assert any(c.symbol == "foo" for c in result["pruned_context"])


def test_clone_failure_raises_ingestion_error(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    from git import GitCommandError

    mocker.patch(
        "resolv.nodes.context_broker.Repo.clone_from",
        side_effect=GitCommandError("clone", 128, b"not found"),
    )
    target = tmp_path / "missing"
    node = make_context_broker_node(max_chunks=5)
    with pytest.raises(IngestionError, match="clone of"):
        node(_state_for(target))
