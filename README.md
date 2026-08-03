# Resolv

Autonomous, stateful AI assistant that ingests git repository issues, locates code defects, and generates verified pull requests.

## Setup

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# POSIX:   source venv/bin/activate
pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in `RESOLV_GITHUB_TOKEN`, `RESOLV_GITHUB_WEBHOOK_SECRET`, and one of the two Claude credentials: `RESOLV_ANTHROPIC_API_KEY` (API billing) or `CLAUDE_CODE_OAUTH_TOKEN` (subscription auth from `claude setup-token`).

Build the per-issue sandbox image that `resolv dispatch` and the webhook launch:

```bash
docker build -f .container/sandbox.Dockerfile -t resolv-sandbox:latest .
```

## Configuration

Non-secret settings live in `config/settings.toml` — that file is the source of truth for
the available keys and their defaults. Secrets are env-only and never appear in it.

Any setting can be overridden by an environment variable named
`RESOLV_<SECTION>__<KEY>` (double underscore separates the section from the key).
Precedence, lowest to highest: `config/settings.toml` → `.env` → process environment →
constructor kwargs.

```bash
RESOLV_CODER__MAX_TURNS=90 RESOLV_SANDBOX__TEST_TIMEOUT_SECONDS=900 resolv run ...
```

## Run

CLI (runs the pipeline in-process; this is what executes inside the sandbox container):
```bash
resolv run --repo owner/name --issue 123
resolv run --repo owner/name --issue 123 --verbose   # full diff + test output in the summary
resolv run --repo owner/name --issue 123 --workspace-root ./workspaces   # default: /workspace
resolv run --repo owner/name --issue 123 --dry-run   # run everything except opening the PR
```

`--dry-run` executes the full pipeline (fetch → env → code → test → validate) but
swaps the deliver node for one that logs the diff and skips the branch/commit/push
and PR — useful for validating Resolv's output on sensitive or self-referential
issues before granting it write access. `resolv dispatch --dry-run` forwards the
flag through to the in-container `resolv run`.

`resolv run` expects the container's environment: the test runner isolates the target
suite with `unshare --net`, which needs Linux and `--cap-add=SYS_ADMIN`. On any other
host the run reaches `test_runner` and fails there with a `SandboxError`. Use
`resolv dispatch` instead.

Manually launch one disposable per-issue container from the host (same `docker run` the webhook uses):
```bash
resolv dispatch --repo owner/name --issue 123
resolv dispatch --repo owner/name --issue 123 --dry-run   # skip PR opening (forwarded to `resolv run`)
```

Replay a finished run's state, node by node (see [State history](#state-history)):
```bash
resolv inspect --repo owner/name --issue 123
```

Webhook server:
```bash
uvicorn --factory resolv.webhook:create_app --host 0.0.0.0 --port 8080
```

## Inspecting a run

Each node is bracketed by a `starting...` / `finished in Ns` pair and reports what it
did in its own terms; the gate logs which branch it took. The lines go to stdout and to
`logs/<DD-MM-YYYYTHH-MM>Z.log`:

```
[coder] starting...
[coder-agent] turn usage={...} tools=['mcp__resolv__run_tests']
[coder-agent] run complete: turns=14 cost_usd=0.42 usage={...}
[coder] wrote +12/-3 lines across 2 file(s)
[coder] finished in 74.1s
[test_runner] starting...
[test_runner] running: pytest --tb=short
[test_runner] 4 passed, 0 failed — status PASSED
[test_runner] finished in 6.2s
[gate] deliver (test PASSED)
```

The coder agent runs the suite itself mid-session through `run_tests`, so several
`[coder-agent]` turns appear before the single authoritative `[test_runner]` line.

Diff and test-suite output are reported by counts, never inlined — the content
itself stays out of the log unless you pass `--verbose`.

A run ends with a one-line summary:

```
[summary] final status PASSED, wrote +15/-4 lines across 2 file(s)
```

A run whose suite does not pass ends at the gate with a non-zero exit code; there is
no retry, so read `[coder-agent] final message:` in the log to see where the agent
stopped.

`resolv dispatch` bind-mounts a per-issue host directory onto the container's log
directory, so both the logs and the checkpoint database survive the `--rm` container:
`logs/<owner>__<repo>__issue-<n>/`.

### State history

Separately from the text trace, the pipeline checkpoints the full Blackboard after
every step into `checkpoints.sqlite` in that same directory. It prints nothing — it is
there to be queried. Read a finished run back on the host:

```bash
resolv inspect --repo owner/name --issue 123
```
```
[history] 7 checkpoint(s)
  before context_broker  test_status=PENDING  no files changed
  before env_installer   test_status=PENDING  no files changed
  before coder           test_status=PENDING  no files changed
  before test_runner     test_status=PENDING  wrote +15/-4 lines across 2 file(s)
  before deliver         test_status=PASSED   wrote +15/-4 lines across 2 file(s)
```

Every intermediate state is recoverable, not just the final one — the `PENDING` row
above is the workspace as the coder left it, before the suite was judged. This needs
no credentials — it reads the database directly. Pass `--database <path>` to point at
one explicitly.

The database lives at one path per issue and outlives the `--rm` container, so
re-dispatching an issue adds to the same file. Each run is keyed separately, and
`inspect` reads the most recent one unless told otherwise:

```bash
resolv inspect --repo owner/name --issue 123 --run 2026-07-31T01-56-25Z
```

The run marker is a UTC timestamp minted at startup and logged as
`[run] owner/name#123 run <marker>`, which is what ties a log file to its
checkpoints. When a database holds more than one run, `inspect` names the one it
picked. Databases written before markers existed keep every run in a single
history; they are still readable, just interleaved.

In Python, `graph.get_state(config)` and `graph.get_state_history(config)` give the
same data as objects, keyed by a `thread_id` (`resolv.main.thread_id_for` builds one
as `owner/name#issue@<marker>`).

## Test

The three checks CI runs on every push and PR:

```bash
pytest --cov=src --cov-report=term-missing
ruff check src tests
mypy src
```
