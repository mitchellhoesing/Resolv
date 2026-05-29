# Design Choices

A running log of design discussions, the options weighed, and the decisions reached.

---

## 2026-05-28 — Repo materialization, history/blame as context, and test-output capture size

### Context

The discussion started from a question about the Test Runner node: do we have to
clone the target repository to run its tests, and is memory a concern given the
(assumed) clone-inside-container-then-delete model?

Investigating the code corrected the premise and opened up two larger questions:
what context the coder model should receive, and how much test output we capture.

### How the system actually works (premise correction)

- The target repo is **not** cloned inside the Docker container. It is cloned onto
  the **host** filesystem at `workspace_path` (`main.py`, `context_broker.py`) via
  GitPython `Repo.clone_from`.
- `run_in_sandbox` (`utils/docker_client.py`) **bind-mounts** that host workspace
  into a disposable container at `/workspace` and runs the test command. The
  container is ephemeral; the clone persists on the host across the whole
  coder → QA → test loop, because each node mutates and reads the same directory.
- "Memory" conflated two resources:
  - **RAM** — a clone streams to disk; it does not live in RAM. The container's
    `mem_limit="2g"` bounds the *test process*, independent of the clone. Cloning
    has effectively zero RAM cost.
  - **Disk** — the only resource the clone consumes. One workspace at a time on the
    CLI path, bounded by the largest single repo.

### Options considered

**Reducing clone footprint:**

| Approach | Tradeoff | Verdict |
|---|---|---|
| Shallow `depth=1` + single-branch | Drops all history; shrinks `.git` 10–100× on long-history repos; faster ingestion | Deferred — see decision |
| Blobless partial clone (`--filter=blob:none`) | Defers blobs until checkout; extra network round-trips when we check out the tip immediately | Rejected — little gain over depth=1 |
| Sparse checkout | Only relevant subdirs; can't reliably predict test-import paths; breaks discovery | Rejected for general repos |
| Tarball download (no `.git`) | Smallest source-only footprint, but `deliver.py` needs a real git repo to commit/push a PR branch | Rejected — defeats the delivery purpose |

**Using history as context:**

- `state.history` (the loop's `IterationRecord` audit trail) is currently
  **write-only** — appended in `test_runner.py` but read by no node. The coder's
  `_compose_feedback` reads only the *current* scalar fields (`qa_findings`,
  `test_output`), i.e. the most recent iteration. `record_iteration()` on the state
  object is dead code (never called in `src/`).
- The context broker is purely structural: tree-sitter `extract_definitions`
  matched against the issue text. No `git log`, `git blame`, or provenance is used.
- **Git commit history / blame** carries genuine value for a defect-fixing tool:
  the commit that last touched the implicated lines often states *intent* in its
  message, and history shows what was previously tried that may have led to the
  issue. This is the value the user explicitly wants the model to see: past
  changes, their intentions, and what has been attempted.

### Decision

1. **Test-output capture increased: `_OUTPUT_TAIL_CHARS` 4000 → 10000.**
   The captured tail of combined stdout/stderr is the feedback the coder reads to
   fix the next patch. 4000 chars was judged too small to reliably contain a full
   failing traceback plus summary. 10000 is a provisional value, open to adjustment
   once we observe real failure output volume.

2. **Shallow `depth=1` cloning deferred, not adopted.**
   `depth=1` would be free *only if* history is never consumed. Because we have
   decided commit history/blame has real value as coder context (see below), we do
   **not** default to discarding history. When history-as-context is built, the
   right move is a bounded `depth=N` (recent slice) or on-demand `git fetch
   --deepen` / targeted blame, rather than full unbounded history.

3. **History-as-context recognized as a future feature (not yet built).**
   - Wire `git blame` on the issue's target files into `pruned_context` so the
     coder sees who/what last changed the relevant lines and why.
   - Wire `state.history` into (a) loop-stall / anti-thrashing detection — compare
     successive diffs to catch the coder oscillating between wrong fixes; note
     `exceptions.py` already defines `LoopStallError` — and (b) richer feedback that
     shows the coder all prior failed attempts, not just the last.
   - Consider removing or consolidating the dead `record_iteration()` path once the
     consumer is defined.

### Changes made in this session

- `refactor(test_runner)`: renamed `_OUTPUT_TAIL_BYTES` → `_OUTPUT_TAIL_CHARS`
  (the cap is a `str` slice counting characters, not bytes). Committed `1c65f24`.
- `_OUTPUT_TAIL_CHARS` increased 4000 → 10000 (this session).
- This design-choices document created.
