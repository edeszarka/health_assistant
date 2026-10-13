# AGENTS.md — health_assistant

How an agent works on this repository. The system itself and its invariants
are described in [ARCHITECTURE.md](ARCHITECTURE.md).

## Git discipline (MANDATORY, every task)
- The base branch is `main`. NEVER commit directly to `main`.
- At the start of every task: `git status` + `git branch --show-current`. If the working tree is not clean, stop and ask.
- Every self-contained change gets its own branch created from `main`, named `<type>/<short-descriptive-name>`:
  `git checkout -b fix/<short-descriptive-name> main`
- The repository is public; merges happen via pull requests by the owner. Do not push, do not merge automatically, do not rebase existing branches.
- Small, atomic commits in Conventional Commits format, in ENGLISH:
  `fix(rag): filter similarity_search by source_type`
- Before every commit, from `backend/`:
  - `pytest tests/ -v` is green (see Testing Protocols);
  - `bandit -r . -ll` passes (blocking CI step);
  - ruff, vulture and mypy are advisory in CI: add no new findings in the files you touch, and report the rest;
  - the diff touches only files within the task's scope.
- At the end of the task: print `git log --oneline <base>..HEAD` and `git diff --stat <base>..HEAD`. Do nothing else with the branch (no merge, no push).

## Clean code rules
- Follow the existing style: Google-style docstrings (see `risk_engine.py`, `rag_service.py`), type hints everywhere, `from __future__ import annotations`.
- One function, one responsibility (SRP). If a fix would grow a function past 40 lines, split it.
- In new or modified code, no silent `except Exception: pass` and no silent `continue`; always log via `logger.warning`/`logger.error` following the existing pattern. Existing violations outside the task are reported, not fixed.
- No magic numbers or strings without documentation; put configurable values in `config.py`/`Settings` or in a module-level constant, with a comment explaining why.
- Do not delete or modify code unrelated to the task (scope discipline). If you see a refactoring opportunity elsewhere, only mention it in the final summary; do not rewrite it.
- Every new or modified piece of logic gets a new or updated unit test in `backend/tests/`, following the existing pytest + pytest-asyncio pattern.

## Workflow
1. Briefly present the plan before writing code.
2. Modify only the files named in the task, unless test coverage justifies adding a test file.
3. Invariants: if a change could violate an Invariant in ARCHITECTURE.md, stop and ask before editing.
4. Docs sync: if your change makes README.md, ARCHITECTURE.md or GEMINI.md inaccurate, update the affected lines if they are in scope; otherwise list them in the final summary.
5. At the end, give a summary: which files, why, with what risk, and which questions remain open.

## Output protocol (lean)

Every task response must include these 5 items, but keep them compact:

1. **Full diff** — unchanged requirement, this is the primary review artifact.
2. **Checklist** — one line per required item: done/not done + file:line.
3. **Test evidence** — run the full suite, but only report:
   - the command used,
   - the final summary line (e.g. `54 passed, 0 failed, 4 warnings`),
   - FULL verbose output for any test that is NEW in this branch,
   - FULL verbose output for any FAILURE.
   Do NOT paste the full list of pre-existing PASSED tests — the summary
   line is sufficient proof they still pass.
4. **Scope check** — one line: which files changed, confirmation nothing
   else touched.
5. **git log --oneline <base>..<branch>** — one line per commit.

## Tiering
The prompt declares the tier. If it does not, treat the task as Logic. The
agent never downgrades a task's tier.
- **Mechanical changes** (deletion of confirmed-dead code, import cleanup,
  dependency bumps, config-only additions with no behavior change): items
  1–5 above, minimal prose, no extra discussion needed.
- **Logic changes** (business logic, prompts, SQL, data models, anything
  affecting runtime behavior): same 5 items, plus a short paragraph noting
  any edge cases considered or explicitly out of scope.

This protocol is loaded automatically from AGENTS.md — individual prompts
do not need to restate it in full. A one-line tag "[lean output protocol]"
at the top of a prompt is enough as a reminder for time-pressured runs.

## Testing Protocols
Tests must be run from the `backend/` directory, with these env vars set
first (the repo's `.env` file does not satisfy Settings' required fields
when tests are run outside Docker):
  DATABASE_URL=postgresql+asyncpg://healthuser:pw@localhost:5432/healthassistant
  SYNC_DATABASE_URL=postgresql+psycopg2://healthuser:pw@localhost:5432/healthassistant
Command: cd backend && pytest tests/ -v
