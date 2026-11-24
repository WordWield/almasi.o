# AGENTS.md

## Canonical code style

Before writing, reviewing, or modifying code, read the current `code_style.md` directly from the `master` branch of `apodgorny/Knowledge`:

https://github.com/apodgorny/Knowledge/blob/master/code_style.md

This file is the sole authority for code style. Do not rely on copies in chats, project attachments, memory, or local directories: they may be outdated.

If the canonical file cannot be retrieved, report that limitation and do not claim compliance. Re-read the canonical file for each new code task rather than assuming previously retrieved rules are still current.

## Performance record in every commit

Every commit to O, including documentation, test and refactoring commits, must
update `docs/performance.txt` with freshly measured performance test results
for the code and dependencies being committed.

- Run the complete standard O performance benchmark against the final runtime
  code before committing. Record all operation timings, not just improvements.
- Replace the latest results section with the actual new measurements. Keep
  the historical record in Git; do not append a new section for every commit.
- Record the benchmark configuration, Python version, Almasi dependency
  revision, and the date and run reference where available. Compare with a
  compatible baseline and identify regressions.
- Never reuse stale numbers, invent timings, or change measured values merely
  to make a diff. Each commit must have its own run, even when rounded values
  happen to be equal.
- If execution is only available in CI, benchmark the candidate and include
  its results in the final commit (amend or squash the candidate as needed);
  do not create an endless chain of benchmark-only follow-up commits.
- If a fresh run cannot be obtained, report the blocker and do not present
  the commit as satisfying this rule.

