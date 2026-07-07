* **Node 1 — Context Broker (nodes/context_broker.py:60)**
* **Job:** clone the repo and pick the code snippets worth showing the LLM.
* **1.** Clone if needed (:62) — if workspace/.git is absent, _clone (:117) does an authenticated https://@[github.com/](https://github.com/)... clone via GitPython. Failures become IngestionError.
* **2.** Build a haystack (:65) — title + body, lowercased.
* **3.** Walk first-party Python (:69) — rglob("*.py"), skipping anything under .git, venvs, site-packages, etc. (_EXCLUDED_DIRS, :31).
* **4.** Extract definitions — extract_definitions (ast_tools.py:21) parses each file with tree-sitter and returns top-level function/class/decorated defs with their name, source snippet, and 1-based line span.
* **5.** Match vs. fallback (:87) — if a definition's name appears in the issue text, it's a matched candidate; otherwise it's held as fallback. It stops early once matched hits max_chunks. If nothing matched, it uses the first max_chunks fallbacks (:94). This is the "v1 simplification" the docstring flags — crude name-substring matching, SCIP cross-file resolution deferred (hence scip_index_path is always None).
* **6.** Attach provenance — _finalize (:99) runs blame_provenance (git_provenance.py:16) on each chunk's line span: a git blame --line-porcelain, parsed into up to 3 entries of    — , most recent first. Best-effort — any git failure returns (). The point: tell the coder who changed these exact lines and why before it rewrites them.
* **Returns:** {"pruned_context": [...], "scip_index_path": None}.



---

* **Node 2 — Coder (nodes/coder.py:16)**
* **Job:** mutate the workspace in place to attempt a fix, then capture the diff.
* **1.** Reset on retry (:17) — on iteration > 0, _reset_workspace runs git reset --hard + git clean -fdx, throwing away the previous failed attempt. Each attempt starts from a clean tree — attempts don't stack.
* **2.** Compose feedback (_compose_feedback, :41) — on retries, builds a prompt block from history: every prior attempt's diff and (if FAILED) its test output, prefixed with "these failed, don't repeat them." This is how the loop learns.
* **3.** Dispatch to the backend (:21) — calls backend.generate_patch(...). The backend is a Protocol (adapters/coder.py:20), chosen by build_coder (:30): either claude_code (Claude Code SDK) or litellm. The shared prompt is built by render_user_prompt (:52), which lays out the issue, each context chunk with its blame provenance, and any prior feedback. The backend edits files directly; it returns nothing.
* **4.** Capture the diff (_capture_diff, :69) — git diff HEAD.
* **Returns:** {current_diff, iteration+1, test_status: "PENDING", test_output: None} — resetting status for the test runner.



---

* **Node 3 — Test Runner (nodes/test_runner.py:46)**
* **Job:** run the target repo's tests under isolation and judge pass/fail.
* **1.** Detect the framework (detect_test_command, :14) — ordered: pyproject.toml with [tool.pytest.ini_options] → pytest.ini/conftest.py → tox.ini → a tests/ dir with test_*.py (unittest). No recognizable layout → None, which is recorded as a FAILED "no test runner detected" (:48).
* **2.** Run isolated (:50) — delegates to run_isolated (sandbox.py:44). This is the security core: the untrusted test command is spawned under unshare --net (fresh network namespace, loopback up but no external route — can't exfiltrate) with a scrubbed env (*scrubbed_env, :92 — only PATH/HOME/LANG/LC_ALL/TERM; all secrets and RESOLV** dropped). A timeout returns a failed result rather than raising (:73), so the loop can feed it back. Missing unshare raises SandboxError. This needs --cap-add=SYS_ADMIN on the container.
* **3.** Judge (:55) — exit code 0 → PASSED, else FAILED. Output is stdout+stderr tail-capped at 10k chars.
* **4.** Record (_record_and_return, :62) — appends an IterationRecord to history.
* **Returns:** {test_status, test_output, history}.
* **Then the gate (core/graph.py:31) routes on the result:** PASSED → deliver; iteration >= max → END (stall); otherwise → back to coder with the new feedback.



---

* **Node 4 — Deliver (nodes/deliver.py:20)**
* **Job:** ship the verified fix. Only reached when tests passed.
* **1.** Branch + commit + push (:24) — via GitPython: create resolv/issue-, check out, add -A, commit fix: resolve issue # — , push to origin. Git failures → DeliveryError.
* **2.** Open the PR (:35) — github_client.open_pull_request(...) against base_branch (default main), body Resolves # plus the issue text.
* **Returns:** {"test_output": "PR opened: "} — which main.py:58 reads to decide its exit code.