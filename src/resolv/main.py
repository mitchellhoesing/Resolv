"""Typer-based CLI entrypoint for Resolv.

Example:

    resolv run --repo octocat/Hello-World --issue 1
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer
from langchain_core.runnables import RunnableConfig
from langgraph.types import StateSnapshot

from resolv.adapters.github_client import GitHubClient
from resolv.config import get_settings
from resolv.core.app import (
    CHECKPOINT_DATABASE_NAME,
    build_production_graph,
    checkpoint_database_path,
)
from resolv.core.graph import build_graph, sqlite_checkpointer
from resolv.core.state import BlackboardState, IterationRecord
from resolv.dispatch import dispatch_issue, host_log_directory
from resolv.exceptions import ResolvError
from resolv.utils.run_log import log_event

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def _main() -> None:
    """Resolv — autonomous issue-to-PR pipeline."""


def _split_repo(repo: str) -> tuple[str, str]:
    """Split an 'owner/name' argument, exiting 2 on bad format."""
    if "/" not in repo:
        typer.echo("error: --repo must be in 'owner/name' form", err=True)
        raise typer.Exit(2)
    owner, name = repo.split("/", 1)
    return owner, name


def thread_id_for(owner: str, name: str, issue: int) -> str:
    """Build the checkpointer thread id identifying one issue's run."""
    return f"{owner}/{name}#{issue}"


def render_run_summary(final_state: dict[str, Any], verbose: bool) -> str:
    """Render the per-iteration audit trail the loop accumulated in `history`.

    Sizes only by default: diffs and test output are unbounded, and this text is
    written to the run log. `verbose` opts in to the full content.
    """
    history: list[IterationRecord] = final_state.get("history") or []
    lines = [
        f"[summary] {len(history)} iteration(s), "
        f"final status {final_state.get('test_status')}"
    ]
    for record in history:
        diff_bytes = len(record.diff) if record.diff else 0
        lines.append(
            f"  iteration {record.iteration}: {record.test_status}, "
            f"diff {diff_bytes} bytes"
        )
        if verbose:
            lines.extend(_indented_block("diff", record.diff))
            lines.extend(_indented_block("test output", record.test_output))
    return "\n".join(lines)


def _indented_block(label: str, content: str | None) -> list[str]:
    """Render one labelled, indented block of an iteration's captured content."""
    if not content:
        return []
    body = "\n".join(f"      {line}" for line in content.splitlines())
    return [f"    {label}:", body]


@app.command()
def run(
    repo: str = typer.Option(..., "--repo", help="Target repository as owner/name."),
    issue: int = typer.Option(..., "--issue", help="Issue number to resolve."),
    workspace_root: Path = typer.Option(
        Path("/workspace"),
        "--workspace-root",
        help="Directory under which per-issue workspaces are created (in-container default).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        help="Include each iteration's diff and test output in the run summary.",
    ),
) -> None:
    """Run the pipeline in-process for a single issue (inside the sandbox container)."""
    owner, name = _split_repo(repo)

    settings = get_settings()
    github_client = GitHubClient(settings.github_token)
    issue_ref = github_client.fetch_issue(owner, name, issue)

    workspace_path = workspace_root / f"{owner}__{name}__issue-{issue}"
    initial_state = BlackboardState(issue=issue_ref, workspace_path=workspace_path)

    graph = build_production_graph(settings)
    # The compiled graph is checkpointed, so a thread id is mandatory; it also
    # keys the state history for post-run inspection.
    run_config: RunnableConfig = {
        "configurable": {"thread_id": thread_id_for(owner, name, issue)}
    }
    try:
        final_state = graph.invoke(initial_state, config=run_config)
    except ResolvError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    # Both outcomes want the audit trail, and a stalled run wants it most.
    log_event(render_run_summary(final_state, verbose))

    if final_state.get("test_status") == "PASSED":
        typer.echo(final_state.get("test_output") or "PR opened")
        raise typer.Exit(0)
    typer.echo(
        f"Loop did not converge after {final_state.get('iteration', 0)} iterations "
        f"(test={final_state.get('test_status')})",
        err=True,
    )
    raise typer.Exit(1)


def render_state_history(snapshots: list[StateSnapshot]) -> str:
    """Render one line per node boundary, oldest first.

    Each snapshot's `next` names the node that was about to run, so the sequence
    traces the executed path — including iterations the final state overwrote.
    """
    if not snapshots:
        return "[history] no checkpoints recorded"
    lines = [f"[history] {len(snapshots)} checkpoint(s)"]
    for snapshot in snapshots:
        next_node = snapshot.next[0] if snapshot.next else "(end)"
        values = snapshot.values
        lines.append(
            f"  before {next_node:<15} "
            f"iteration={values.get('iteration', 0)} "
            f"test_status={str(values.get('test_status', '-')):<8} "
            f"history={len(values.get('history') or [])}"
        )
    return "\n".join(lines)


def _locate_checkpoint_database(owner: str, name: str, issue: int) -> Path:
    """Find a finished run's database: dispatched layout first, then a local run."""
    dispatched = host_log_directory(owner, name, issue) / CHECKPOINT_DATABASE_NAME
    if dispatched.is_file():
        return dispatched
    local = checkpoint_database_path()
    if local.is_file():
        return local
    typer.echo(
        f"error: no checkpoint database at {dispatched} or {local}",
        err=True,
    )
    raise typer.Exit(1)


def _read_state_history(database: Path, thread_id: str) -> list[StateSnapshot]:
    """Read a finished run's history without needing the real nodes or any secrets.

    Only the graph topology matters for resolving which node each checkpoint sat
    before, so the placeholder nodes below are compiled but never executed.
    """

    def placeholder(state: BlackboardState) -> dict[str, Any]:
        raise AssertionError("placeholder node must never run")

    graph = build_graph(
        context_broker_fn=placeholder,
        env_installer_fn=placeholder,
        coder_fn=placeholder,
        test_runner_fn=placeholder,
        deliver_fn=placeholder,
        checkpointer=sqlite_checkpointer(database),
    )
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    return list(reversed(list(graph.get_state_history(config))))


@app.command()
def inspect(
    repo: str = typer.Option(..., "--repo", help="Target repository as owner/name."),
    issue: int = typer.Option(..., "--issue", help="Issue number of the finished run."),
    database: Path = typer.Option(
        None,
        "--database",
        help="Checkpoint database to read; defaults to the run's log directory.",
    ),
) -> None:
    """Print the node-by-node state history of a run that has already finished."""
    owner, name = _split_repo(repo)
    resolved = database or _locate_checkpoint_database(owner, name, issue)
    if not resolved.is_file():
        typer.echo(f"error: no checkpoint database at {resolved}", err=True)
        raise typer.Exit(1)

    snapshots = _read_state_history(resolved, thread_id_for(owner, name, issue))
    typer.echo(render_state_history(snapshots))


@app.command()
def dispatch(
    repo: str = typer.Option(..., "--repo", help="Target repository as owner/name."),
    issue: int = typer.Option(..., "--issue", help="Issue number to resolve."),
) -> None:
    """Launch a disposable per-issue container that runs `resolv run` (host-side)."""
    owner, name = _split_repo(repo)
    settings = get_settings()
    exit_code = dispatch_issue(settings, owner, name, issue)
    raise typer.Exit(exit_code)


if __name__ == "__main__":
    sys.exit(app())
