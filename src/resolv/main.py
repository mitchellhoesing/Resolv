"""Typer-based CLI entrypoint for Resolv.

Example:

    resolv run --repo octocat/Hello-World --issue 1
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from langchain_core.runnables import RunnableConfig

from resolv.adapters.github_client import GitHubClient
from resolv.config import get_settings
from resolv.core.app import (
    CHECKPOINT_DATABASE_NAME,
    build_production_graph,
    checkpoint_database_path,
)
from resolv.core.graph import sqlite_checkpointer
from resolv.core.state import BlackboardState
from resolv.dispatch import dispatch_issue, host_log_directory
from resolv.exceptions import ResolvError
from resolv.utils.diff_stats import describe_diff
from resolv.utils.run_log import log_event

app = typer.Typer(no_args_is_help=True, add_completion=False)

# How LangGraph records the node it queued next.
_BRANCH_CHANNEL_PREFIX = "branch:to:"


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


# UTC and lexicographically sortable, so the newest run of an issue is simply
# the greatest of its thread ids.
_RUN_MARKER_FORMAT = "%Y-%m-%dT%H-%M-%SZ"


def new_run_marker() -> str:
    """Mint the identity distinguishing this run from earlier runs of the same issue."""
    return datetime.now(timezone.utc).strftime(_RUN_MARKER_FORMAT)


def issue_thread_prefix(owner: str, name: str, issue: int) -> str:
    """Prefix shared by every run of one issue.

    The trailing '@' is load-bearing: without it the prefix for issue #1 also
    matches issue #10.
    """
    return f"{owner}/{name}#{issue}@"


def thread_id_for(owner: str, name: str, issue: int, run_marker: str) -> str:
    """Build the checkpointer thread id identifying one run of one issue.

    The database lives at one path per issue and outlives the container, so
    consecutive dispatches of the same issue land in the same file. The run
    marker is what keeps their state histories from interleaving there.
    """
    return f"{issue_thread_prefix(owner, name, issue)}{run_marker}"


def render_run_summary(final_state: dict[str, Any], verbose: bool) -> str:
    """Render the run's outcome: final status and the size of what it produced.

    Counts only by default: diffs and test output are unbounded, and this text is
    written to the run log. `verbose` opts in to the full content.
    """
    diff: str | None = final_state.get("current_diff")
    lines = [
        f"[summary] final status {final_state.get('test_status')}, "
        f"{describe_diff(diff)}"
    ]
    if verbose:
        lines.extend(_indented_block("diff", diff))
        lines.extend(_indented_block("test output", final_state.get("test_output")))
    return "\n".join(lines)


def _indented_block(label: str, content: str | None) -> list[str]:
    """Render one labelled, indented block of the run's captured content."""
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
        help="Include the full diff and test output in the run summary.",
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
    run_marker = new_run_marker()
    # The only place the log and the state history name the same run, so it is
    # what lets a log file be traced back to its checkpoints.
    log_event(f"[run] {owner}/{name}#{issue} run {run_marker}")
    run_config: RunnableConfig = {
        "configurable": {"thread_id": thread_id_for(owner, name, issue, run_marker)}
    }
    try:
        final_state = graph.invoke(initial_state, config=run_config)
    except ResolvError as exc:
        # Also to the run log: stderr dies with the --rm container, so without
        # this a crashed run is indistinguishable from a killed one — the log
        # just stops mid-node either way.
        log_event(f"[run] failed: {exc}")
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    # Both outcomes want the audit trail, and a stalled run wants it most.
    log_event(render_run_summary(final_state, verbose))

    if final_state.get("test_status") == "PASSED":
        typer.echo(final_state.get("test_output") or "PR opened")
        raise typer.Exit(0)
    # There is no retry: the coder agent already ran its own edit/test cycle, so
    # a non-PASSED verdict here is a handoff to a human.
    typer.echo(
        f"Coder agent did not reach a passing suite (test={final_state.get('test_status')}); "
        "see the run log for the agent's final message",
        err=True,
    )
    raise typer.Exit(1)


@dataclass(frozen=True)
class CheckpointSummary:
    """One node boundary, read from a checkpoint without rebuilding the state."""

    next_node: str
    test_status: str
    diff: str | None


def render_state_history(summaries: list[CheckpointSummary]) -> str:
    """Render one line per node boundary, oldest first.

    Each summary names the node that was about to run, so the sequence traces
    the executed path — including state the final result overwrote.
    """
    if not summaries:
        return "[history] no checkpoints recorded"
    lines = [f"[history] {len(summaries)} checkpoint(s)"]
    for summary in summaries:
        lines.append(
            f"  before {summary.next_node:<15} "
            f"test_status={summary.test_status:<8} "
            f"{describe_diff(summary.diff)}"
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


def _stored_thread_ids(database: Path) -> list[str]:
    """Every thread id the database holds, read directly rather than through the graph."""
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
        return [
            row[0]
            for row in connection.execute("SELECT DISTINCT thread_id FROM checkpoints")
        ]


def resolve_thread_id(
    stored_thread_ids: list[str], owner: str, name: str, issue: int, run: str | None
) -> tuple[str, list[str]]:
    """Pick which run of an issue to read, and report the markers to choose from.

    Databases written before runs carried a marker hold one bare `owner/name#issue`
    thread with every run interleaved into it; it is still readable, and reported
    as the marker-less run it is.
    """
    prefix = issue_thread_prefix(owner, name, issue)
    markers = sorted(
        thread_id[len(prefix) :]
        for thread_id in stored_thread_ids
        if thread_id.startswith(prefix)
    )
    if not markers:
        legacy = prefix.rstrip("@")
        if legacy in stored_thread_ids:
            return legacy, []
        typer.echo(f"error: no run of {legacy} in the database", err=True)
        raise typer.Exit(1)
    if run is None:
        return f"{prefix}{markers[-1]}", markers
    if run not in markers:
        typer.echo(
            f"error: no run '{run}'; the database holds {', '.join(markers)}",
            err=True,
        )
        raise typer.Exit(1)
    return f"{prefix}{run}", markers


def summarize_checkpoint(channel_values: dict[str, Any]) -> CheckpointSummary:
    """Read one checkpoint's node boundary straight from its channels.

    LangGraph queues the next node by writing a `branch:to:<node>` channel, so
    the executed path is recoverable from the channels alone. Going through the
    compiled graph instead would coerce every checkpoint back into a
    BlackboardState, which reinstantiates `workspace_path` as the concrete Path
    class of whichever machine wrote it — the container, always.
    """
    queued = [
        channel[len(_BRANCH_CHANNEL_PREFIX) :]
        for channel in channel_values
        if channel.startswith(_BRANCH_CHANNEL_PREFIX)
    ]
    if queued:
        next_node = queued[0]
    elif "__start__" in channel_values:
        next_node = "__start__"
    else:
        next_node = "(end)"
    return CheckpointSummary(
        next_node=next_node,
        test_status=str(channel_values.get("test_status", "-")),
        diff=channel_values.get("current_diff"),
    )


def _read_state_history(database: Path, thread_id: str) -> list[CheckpointSummary]:
    """Read a finished run's node boundaries, oldest first.

    Needs neither the real nodes nor any secrets — and no graph either: the
    checkpointer is the whole dependency.
    """
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    checkpointer = sqlite_checkpointer(database)
    return [
        summarize_checkpoint(checkpoint_tuple.checkpoint["channel_values"])
        for checkpoint_tuple in reversed(list(checkpointer.list(config)))
    ]


@app.command()
def inspect(
    repo: str = typer.Option(..., "--repo", help="Target repository as owner/name."),
    issue: int = typer.Option(..., "--issue", help="Issue number of the finished run."),
    database: Path = typer.Option(
        None,
        "--database",
        help="Checkpoint database to read; defaults to the run's log directory.",
    ),
    run: str = typer.Option(
        None,
        "--run",
        help="Which run of the issue to read; defaults to the most recent.",
    ),
) -> None:
    """Print the node-by-node state history of a run that has already finished."""
    owner, name = _split_repo(repo)
    resolved = database or _locate_checkpoint_database(owner, name, issue)
    if not resolved.is_file():
        typer.echo(f"error: no checkpoint database at {resolved}", err=True)
        raise typer.Exit(1)

    thread_id, markers = resolve_thread_id(
        _stored_thread_ids(resolved), owner, name, issue, run
    )
    # Silent when there is nothing to choose between; otherwise say which run
    # this is, so the default is not mistaken for the whole story.
    if len(markers) > 1:
        typer.echo(f"[run] {thread_id} ({len(markers)} runs; --run to pick another)")
    snapshots = _read_state_history(resolved, thread_id)
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
