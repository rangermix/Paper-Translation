# Repository relocation: independent review

Reviewer: `acceptance_harness`. Result: **PASS for relocation scope** on 2026-09-07. This is a read-only review of current files, narrowly scoped validation outputs and preserved evidence. I did not start containers, run a browser, read credentials, access a product endpoint, or rerun the full functional suite.

The project now resides directly at `C:/workspaces-local/Paper-Translation`; the former nested project directory is absent. Reusable agent harness, memory and notes remain visible to Git under `.agent/`; temporary evidence and persistent private runtime state are separately ignored under `.agent/tmp/` and `.agent/local-data/`. Only `LICENSE` was already committed: its bytes still match `HEAD`. “Repository-owned” does not mean the other files have been committed.

Independent checks passed:

- All 27 actual `git check-ignore` positive/negative cases, using NUL-delimited paths. All 490 nonprivate, noncached source candidates remained unignored; no visible private-runtime paths or untracked files over 50 MiB appeared. Standalone `.spec` and `.manifest` are no longer broadly ignored.
- Docker excludes the entire `.agent/` and local keys while retaining the safe empty-key sentinel and delivered `html/` / `index.html`. Every local `COPY` input exists. Actual `docker compose config --format json` resolved production build contexts to the new Git root and all bind sources existed. The secret input was explicitly overridden to the empty sentinel; this was static configuration validation, without an engine or container run.
- Every exact file/prefix mapping in `.agent/relocation.json` resolves to its real destination. Four historical cost-control receipts resolve 73 artifact references whose original SHA-256 values all still match. Two changed test-source references remain stale, as required; moving evidence does not make old source certification current.
- The current Python relocation review's file hashes and its 48-test JUnit matched, with no failure/error/skip. The six recorded safe CLI checks and 165 syntax checks passed. The earlier 727 collection correctly preceded three additional mapper cases; the final relocated launcher log contains 730 collected nodes, without executing them. This review's Python interpreter also used the new root `.venv`.
- The frontend relocation review's source hashes, 13 unit passes, build output and 96-test/15-file collection matched. The rebuilt JavaScript remains byte-identical to the prior delivered `index-6muiN2d7.js`. Collection is not a new 96-test browser execution.
- Live read-only WSL listing showed Ubuntu running and BiblioCleanD99 stopped. The latter's registered base path is `.agent/local-data/wsl-hosts/BiblioCleanD99`; its VHDX exists with 10,585,374,720 bytes. I inspected registration and file metadata only, not disk contents. The approved shutdown/move/restart was performed by root, not repeated here.

Machine-readable findings, actual checks, relocated artifact references and input hashes: [independent-final-review.json](../tmp/repository-layout/independent-final-review.json). This final review contains 30 checks. Historical 708-test and product UI results were preserved, not rerun or re-certified by this relocation. Existing live-provider requirements remain separate.

The earlier inability to move the stopped VHDX was resolved by the user-authorized Ubuntu shutdown and official WSL move. The failed selective detach and initial move attempts remain preserved. No outstanding relocation finding remains in this reviewed scope.
