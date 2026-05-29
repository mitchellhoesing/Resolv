# Resolv — End-to-End Implementation Plan

> **ARCHITECTURE UPDATE (supersedes parts of this plan).** The execution model was
> later inverted: the **whole pipeline now runs inside one disposable per-issue
> container** (clone, context broker, coder, tests, push), not "coder on host +
> Docker for QA/tests." **CodeRabbit was removed as a pipeline gate** — it now runs in
> the cloud on the pushed PR — so `qa_status`/`qa_findings`, the `coderabbit_qa` node,
> and `QAGateError` no longer exist, and the gate converges on `test_status == PASSED`
> alone. The nested-container `run_in_sandbox` is replaced by `utils/sandbox.py`, which
> runs the untrusted test suite as an in-process child under `unshare --net` with a
> scrubbed env (requires `--cap-add=SYS_ADMIN`). SCIP indexing was never built; the
> broker is tree-sitter only (plus git-blame provenance). The sections below are
> retained as historical context; where they conflict with this note, this note wins.

## Context

Resolv is greenfield: only `.claude/claude.md` and `docs/architecture.txt` exist. The goal is to build the full autonomous loop described in those documents — an agent that ingests a GitHub issue, locates the defect, generates and verifies a patch through a CodeRabbit QA gate + tests in a Docker sandbox, and opens a PR. This plan covers the full end-to-end system.

**Decisions locked in:**
- Target repos: **Python only** (scip-python indexer, tree-sitter Python grammar).
- Triggers: **CLI + GitHub webhook server** (FastAPI). Both launch a per-issue container.
- CodeRabbit QA: **removed from the pipeline** — runs in the cloud on the pushed PR (see update banner).
- Coder: **selectable backend** — Claude Code (Agent SDK) *or* LiteLLM, chosen via `settings.toml`.
- Whole pipeline runs **inside one disposable per-issue container**; only the untrusted test suite is network-isolated in-process via `unshare --net` (see update banner).
- Test runner: detect **pytest → tox → unittest** and dispatch accordingly.

## Architecture

### Workspace lifecycle
- Per-issue dir: `./workspaces/<owner>__<repo>__issue-<id>/` (host path).
- Git-clone target repo there at ingress. Cleaned on success unless `RESOLV_KEEP_WORKSPACE=true`; retained on failure for debugging.
- Docker mounts the workspace dir at `/workspace` for QA + tests. Host-side Coder edits the same files directly.

### Graph topology (LangGraph)
```
ingress -> context_broker -> coder -> test_runner -> gate
gate:
  if test_status == PASSED -> deliver -> END
  elif iteration < max_iterations -> coder (loop, with feedback)
  else -> END (LoopStallError logged)
```
**Context Broker runs once at ingress**, not in the loop — ingestion is expensive and the context doesn't change meaningfully between Coder attempts. The loop body is Coder → Tests.

### State (Blackboard)
`src/resolv/core/state.py`: Pydantic V2 model with frozen sub-models where possible. Fields:
- `issue: IssueRef` (owner, repo, number, title, body, labels)
- `workspace_path: Path`
- `scip_index_path: Path | None`
- `pruned_context: list[ContextChunk]` (file_path, symbol, snippet)
- `current_diff: str | None`
- `qa_status: Literal["PENDING","APPROVED","REJECTED"]`
- `qa_findings: list[str]`
- `test_status: Literal["PENDING","PASSED","FAILED"]`
- `test_output: str | None`
- `iteration: int`
- `history: list[IterationRecord]` (append-only audit trail per loop)

### Coder backend abstraction
`src/resolv/adapters/coder.py` defines:
```python
class CoderBackend(Protocol):
    def generate_patch(self, issue: IssueRef, workspace_path: Path,
                       pruned_context: list[ContextChunk],
                       prior_feedback: str | None) -> None:
        """Mutates workspace_path in place. Orchestrator captures git diff after."""
```
Two implementations:
- `ClaudeCodeBackend` (`adapters/claude_code_client.py`): wraps `claude-agent-sdk`. Calls `query()` with a system prompt + workspace path; SDK runs its own multi-turn tool-use loop. Requires `claude` CLI authenticated on the host.
- `LiteLLMBackend` (`adapters/llm_inference.py`): single-shot completion. Prompt = pruned context + issue + (optional) prior_feedback; instructs the model to return a unified diff only. Validate with `unidiff`, apply with `git apply --3way`. Retry once on parse/apply failure before raising.

Backend selected in `config.py` from `settings.toml::coder.backend` (`"claude_code"` or `"litellm"`).

After backend returns, `nodes/coder.py` runs `git diff` in the workspace and writes the result into `state.current_diff`.

### Trigger surfaces
- **CLI** (`main.py`, using `typer`): `resolv run --repo owner/name --issue 123 [--backend claude_code|litellm]`.
- **Webhook** (`src/resolv/webhook.py`): FastAPI app, `POST /github`, validates `X-Hub-Signature-256` against `GITHUB_WEBHOOK_SECRET`, filters for `issues.opened` and `issue_comment.created` matching a trigger phrase (`/resolv fix`), enqueues an in-process `asyncio.Queue` consumed by a single worker task that invokes the same graph as the CLI. In-process queue is sufficient for v1; the scale ceiling is documented.

### Sandbox (`.container/sandbox.Dockerfile`)
- Base: `python:3.12-slim`
- System: `git`, `nodejs`, `npm`, `curl`
- `pip install pytest tox`
- `npm install -g @sourcegraph/scip-python`
- Install CodeRabbit CLI: `curl -fsSL https://cli.coderabbit.ai/install.sh | sh`
- Workdir `/workspace`; no entrypoint (commands invoked per-exec by docker-py).

`utils/docker_client.py` provides:
- `get_client()` — `docker.from_env()` with a single-image-build cache.
- `run_in_sandbox(command, workspace_path, timeout)` — mounts workspace read-write, sets resource limits (mem 2g, cpus 2.0, network=`none` for tests; network=`bridge` only for CodeRabbit if it needs outbound), captures stdout/stderr/exit, kills on timeout.

### Node implementations
- `nodes/context_broker.py`: clones repo if not present, shells out to `scip-python index` inside the sandbox (writes `index.scip` into workspace), parses the SCIP protobuf for symbols referenced in the issue text, uses tree-sitter (`utils/ast_tools.py`) to extract surrounding snippets, returns top-k as `pruned_context`. Top-k is `settings.toml::context.max_chunks` (default 20).
- `nodes/coder.py`: dispatches to selected backend, captures diff.
- `nodes/coderabbit_qa.py`: `run_in_sandbox(["coderabbit", "review", "--plain"], workspace, timeout=300)`. Non-empty findings or non-zero exit → REJECTED with findings text into `state.qa_findings`. Approved → APPROVED.
- `nodes/test_runner.py`: detection chain on host (cheap, file-existence checks):
  - `pyproject.toml` with `[tool.pytest.ini_options]` *or* `pytest.ini`/`conftest.py` → `pytest -q --tb=short`
  - `tox.ini` → `tox -q`
  - `tests/` dir with `test_*.py` and none of the above → `python -m unittest discover -s tests`
  - else → FAILED with message "no test runner detected"
  Dispatch to `run_in_sandbox`. Non-zero exit → FAILED with truncated stdout/stderr in `state.test_output`.
- `nodes/deliver.py`: `GitPython` — create branch `resolv/issue-<id>`, commit with Conventional Commits message (`fix: resolve issue #<id> — <issue title>`), push via PyGithub-authenticated remote, open PR against the configured base branch (default `main`).

### Configuration
`src/resolv/config.py` — `pydantic-settings` `BaseSettings`:
- Loads `config/settings.toml` + `.env` + process env.
- Sections: `coder.backend`, `coder.litellm_model`, `coder.claude_model`, `loop.max_iterations` (default 5), `context.max_chunks`, `delivery.base_branch`, `sandbox.image_tag`, `webhook.trigger_phrase`.
- Secrets via env: `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GITHUB_WEBHOOK_SECRET`, `LITELLM_*`.

### Exceptions (`src/resolv/exceptions.py`)
`LoopStallError`, `IngestionError`, `SandboxError`, `QAGateError`, `DeliveryError`. All inherit from `ResolvError`.

## Critical files to create

**Project root:** `pyproject.toml`, `.gitignore`, `.dockerignore`, `README.md`.

**Config:** `config/settings.toml`, `config/.coderabbit.yaml`.

**Sandbox:** `.container/sandbox.Dockerfile`.

**Source tree** (matches `claude.md` layout, plus `webhook.py` and `adapters/coder.py`):
```
src/resolv/{__init__,main,config,exceptions,webhook}.py
src/resolv/adapters/{__init__,github_client,llm_inference,claude_code_client,coder}.py
src/resolv/core/{__init__,graph,state}.py
src/resolv/nodes/{__init__,context_broker,coder,coderabbit_qa,test_runner,deliver}.py
src/resolv/utils/{__init__,ast_tools,docker_client}.py
```

**Tests:** `tests/conftest.py` + `tests/unit/{test_state,test_context_broker,test_coderabbit_qa,test_coder_backends,test_test_runner,test_deliver}.py` + `tests/integration/{test_graph_cycle,test_sandbox_runtime,test_webhook}.py`.

**CI:** `.github/workflows/{ci,cd}.yml`.

## Build phases

Each phase is a series of atomic commits per the Git Protocol (`feat:`/`test:`/`refactor:`). Each phase ends with the listed verification passing.

**Phase 1 — Foundation.** `pyproject.toml` with deps (`langgraph`, `langchain-core`, `pydantic>=2`, `pydantic-settings`, `litellm`, `claude-agent-sdk`, `PyGithub`, `GitPython`, `docker`, `tree-sitter`, `tree-sitter-python`, `unidiff`, `typer`, `fastapi`, `uvicorn`, `pytest`, `pytest-mock`, `pytest-cov`); `.gitignore` including `.env` and `workspaces/`; venv setup documented in README. `src/resolv/exceptions.py`, `src/resolv/config.py`, `src/resolv/core/state.py`. **Verify:** `pytest tests/unit/test_state.py` passes round-trip serialization tests.

**Phase 2 — Graph wiring with stub nodes.** `src/resolv/core/graph.py` builds the `StateGraph`, edges, and conditional gate; all five nodes are no-op stubs that bump state to plausible values. **Verify:** `pytest tests/integration/test_graph_cycle.py` runs ingress → deliver and a forced-loop path; both reach END within `max_iterations`.

**Phase 3 — Adapters.** `adapters/github_client.py` (fetch issue, push branch, open PR — mocked in tests), `adapters/llm_inference.py` (LiteLLM `completion()` wrapper), `adapters/claude_code_client.py` (Agent SDK `query()` wrapper), `adapters/coder.py` (Protocol + factory). **Verify:** unit tests mock external boundaries and assert request/response shapes.

**Phase 4 — Real nodes, bottom-up.**
1. `utils/docker_client.py` + `nodes/test_runner.py` with detection + sandbox dispatch. Fixture repo under `tests/fixtures/sample_python_repo/`. Integration test runs `test_runner` against the fixture inside Docker.
2. `utils/ast_tools.py` + `nodes/context_broker.py`. Integration test asserts SCIP index produced and `pruned_context` populated.
3. `nodes/coder.py` wired to both backends. Unit tests mock both backends; one integration test uses `LiteLLMBackend` with a recorded VCR-style fixture to assert diff capture.
4. `nodes/coderabbit_qa.py`. Integration test invokes the sandboxed CodeRabbit CLI against a fixture diff.
5. `nodes/deliver.py`. Unit test mocks PyGithub; integration test against a throwaway GitHub repo (gated behind `RESOLV_E2E=1`).

**Verify after each:** `pytest --cov=src --cov-report=term-missing`, coverage trending >80%.

**Phase 5 — Trigger surfaces.** `src/resolv/main.py` (typer CLI), `src/resolv/webhook.py` (FastAPI). **Verify:** `resolv run --help` works; `pytest tests/integration/test_webhook.py` posts a signed fake payload and asserts the issue is enqueued and processed.

**Phase 6 — CI/CD.** `.github/workflows/ci.yml` runs `pytest`, `ruff`, `mypy` on push. `.github/workflows/cd.yml` builds and pushes the sandbox image to GHCR on tag. **Verify:** push a PR, watch CI green.

## End-to-end verification

1. **Unit + integration:** `pytest --cov=src --cov-report=term-missing` — all green, coverage ≥ 80%.
2. **CLI smoke test:** `resolv run --repo <owner>/<small-public-py-repo> --issue <known-trivial-bug>` produces a PR with a working fix. Repeat with `--backend litellm` to validate the alternative coder.
3. **Webhook smoke test:** expose `webhook.py` via `ngrok`, register a GitHub test webhook against a sandbox repo, comment `/resolv fix` on an open issue, observe end-to-end PR creation.
4. **Loop guard:** synthetic test injects always-FAILED test_runner; assert `LoopStallError` raised after `max_iterations` and final state recorded in `history`.

## Open design choices flagged for review
- **LiteLLM-as-Coder is weaker than Claude-Code-as-Coder by construction** (single-shot diff vs. agentic multi-turn). If LiteLLM frequently produces malformed diffs in practice, `LiteLLMBackend` may need its own minimal tool-use loop. Not building that for v1.
- **Webhook queue is in-process** (`asyncio.Queue`). Fine for one-host, low-concurrency v1; would need Redis/Celery if scaled.
- **Workspace dir lives under repo root** (`./workspaces/`). Convenient for debugging; if `$TMPDIR` or `~/.resolv/workspaces` is preferred, decide before Phase 1.
