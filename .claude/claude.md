## Project Overview
Resolv is an autonomous, stateful AI assistant designed to ingest git repository issues, locate code defects, and generate verified, production-grade Pull Requests.

## Repository structure
resolv-pipeline/
├── .claude/
│   └── claude.md                  # Project overview optimized for LLM development tools
├── .github/
│   └── workflows/
│       ├── ci.yml                 # Runs test suite, linters, and type checking
│       └── cd.yml                 # Automates image publishing or deployment
├── .container/
│   └── sandbox.Dockerfile         # Ships the whole resolv app; the per-issue container runs the full pipeline
├── config/
│   └── settings.toml              # Project configuration (limits, models, timeouts)
├── docs/
│   └── architecture.txt           # Deep-dive system design documentation
├── plan/
│   └── implementation_plan.md     # Historical build plan; superseded parts flagged in its update banner
├── src/
│   └── resolv/
│       ├── __init__.py
│       ├── main.py                # Typer CLI entrypoint (`resolv run` in-container, `resolv dispatch` host-side)
│       ├── webhook.py             # FastAPI GitHub webhook listener; launches a per-issue container per event
│       ├── dispatch.py            # Host-side per-issue `docker run` launcher shared by webhook and CLI
│       ├── config.py              # Configuration loading via Pydantic Settings
│       ├── exceptions.py          # Centralized custom exceptions (e.g., LoopStallError)
│       │
│       ├── adapters/              # External interface boundaries
│       │   ├── __init__.py
│       │   ├── github_client.py   # PyGithub wrapper for issues and PR lifecycle
│       │   ├── claude_code_client.py  # Claude Agent SDK wrapper + agentic Coder backend
│       │   └── coder.py           # CoderBackend Protocol and shared prompt rendering/logging
│       │
│       ├── core/                  # Orchestration and State Control
│       │   ├── __init__.py
│       │   ├── app.py             # Production wiring: Settings → compiled LangGraph application
│       │   ├── graph.py           # LangGraph workflow instantiation and edge compilation
│       │   └── state.py           # Strongly typed Pydantic V2 state definitions (Blackboard)
│       │
│       ├── nodes/                 # LangGraph Worker Nodes
│       │   ├── __init__.py
│       │   ├── context_broker.py  # Ingestion: clones the target repo into the workspace
│       │   ├── env_installer.py   # Installs target repo dev/test deps into a per-repo venv
│       │   ├── coder.py           # LLM patch generation logic
│       │   ├── test_runner.py     # Runs the target tests as a network-isolated, secret-scrubbed subprocess
│       │   └── deliver.py         # GitPython branching, committing, and upstream delivery
│       │
│       └── utils/                 # Shared helper modules
│           ├── __init__.py
│           └── sandbox.py         # Scrubbed-env subprocess spawning: `unshare --net` for tests, networked for installs
│
├── tests/                         # Multi-tier testing suite
│   ├── __init__.py
│   ├── conftest.py                # Shared pytest fixtures (sample issue/state)
│   ├── unit/                      # Fast, isolated tests — one test_*.py per source module
│   │   └── test_*.py              # (test_state, test_sandbox, test_context_broker, ...)
│   └── integration/               # Multi-node graph loop execution verifications
│       ├── _stub_nodes.py         # Deterministic stub nodes for graph-cycle tests
│       ├── test_graph_cycle.py
│       └── test_webhook.py
│
├── .coderabbit.yaml               # CodeRabbit cloud-review configuration (read from repo root)
├── .dockerignore
├── .gitignore
├── LICENSE
├── README.md                      # Human-facing project manual
├── nodes_jobs.md                  # Per-node walkthrough of what each LangGraph node does
└── pyproject.toml                 # Poetry packaging dependencies and tool configurations

## Tech Stack
Virtual Environment: venv
Language: Python
Orchestration & State Machine: langgraph, langchain-core, pydantic
Inference Layer: Claude Agent SDK (agentic Coder backend)
LLMs: Claude
Execution model: the whole pipeline runs inside one disposable per-issue Docker container; the untrusted test suite is isolated in-process via a Linux network namespace (`unshare --net`) with a scrubbed environment. Requires `--cap-add=SYS_ADMIN`.
QA: CodeRabbit runs in the cloud on the pushed PR — it is not invoked in-pipeline.
Git operations: GitPython, PyGithub

## Standards
# Variable naming convention

Use snake-casing. Do not write single character variable names. Variable names should be expressive to what they are.

Use a virtual environment for the packages in this project.

# Git Protocol
- Commits must be atomic, addressing one logical change.
- Follow Conventional Commits (`feat:`, `fix:`, `test:`, `refactor:`).
- Commit messages should be descriptive of the changes.

## 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.
- Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

## 5. Security & Integrity

Security is a primary constraint, not an afterthought.

- **Secrets:** Never hardcode credentials. Use environment variables and `.env` files. Ensure `.env` is in `.gitignore`.
- **Input Sanitization:** Treat all external data (user input, API responses, file reads) as untrusted. Validate types and bounds before processing.
- **Safe Serialization:** Avoid `pickle`. Use `json` or `yaml.safe_load` for data persistence.
- **Least Privilege:** Ensure components only have access to the data and permissions required for their specific task.
- **Error Handling:** Use explicit exception handling. Log detailed errors internally, but provide generic, safe messages to end-users to avoid info-leaks.



