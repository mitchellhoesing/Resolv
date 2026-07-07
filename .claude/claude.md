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
│   └── architecture.md            # Deep-dive system design documentation
├── src/
│   └── resolv/
│       ├── __init__.py
│       ├── main.py                # Main system entrypoint (CLI parser / Event processor)
│       ├── config.py              # Configuration loading via Pydantic Settings
│       ├── exceptions.py          # Centralized custom exceptions (e.g., LoopStallError)
│       │
│       ├── adapters/              # External interface boundaries
│       │   ├── __init__.py
│       │   ├── github_client.py   # PyGithub wrapper for issues and PR lifecycle
│       │   └── llm_inference.py   # LiteLLM client abstraction for model routing
│       │
│       ├── core/                  # Orchestration and State Control
│       │   ├── __init__.py
│       │   ├── graph.py           # LangGraph workflow instantiation and edge compilation
│       │   └── state.py           # Strongly typed Pydantic V2 state definitions (Blackboard)
│       │
│       ├── nodes/                 # LangGraph Worker Nodes
│       │   ├── __init__.py
│       │   ├── context_broker.py  # Ingestion, AST parsing via tree-sitter, git-blame provenance, pruning
│       │   ├── coder.py           # LLM patch generation logic
│       │   ├── test_runner.py     # Runs the target tests as a network-isolated, secret-scrubbed subprocess
│       │   └── deliver.py         # GitPython branching, committing, and upstream delivery
│       │
│       └── utils/                 # Shared helper modules
│           ├── __init__.py
│           ├── ast_tools.py       # Low-level Tree-sitter tree traversal utilities
│           ├── git_provenance.py  # git-blame provenance for the lines in each context snippet
│           └── sandbox.py         # Spawns the test command under `unshare --net` with a scrubbed env
│
├── tests/                         # Multi-tier testing suite
│   ├── __init__.py
│   ├── conftest.py                # Shared pytest fixtures (mocks for LiteLLM, GitHub API)
│   ├── unit/                      # Fast, isolated node tests
│   │   ├── test_context_broker.py
│   │   ├── test_sandbox.py
│   │   └── test_state.py
│   └── integration/               # Multi-node graph loop execution verifications
│       ├── test_graph_cycle.py
│       └── test_sandbox_runtime.py
│
├── .coderabbit.yaml               # CodeRabbit cloud-review configuration (read from repo root)
├── .dockerignore
├── .gitignore
├── README.md                      # Human-facing project manual
└── pyproject.toml                 # Poetry packaging dependencies and tool configurations

## Tech Stack
Virtual Environment: venv
Language: Python
Orchestration & State Machine: langgraph, langchain-core, pydantic
Inference Layer: litellm
LLMs: Claude, OpenAI
Code Analysis: tree-sitter (git-blame provenance for context)
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



