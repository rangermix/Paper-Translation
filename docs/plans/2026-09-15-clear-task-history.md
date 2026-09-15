# Clear task history implementation plan

**Goal:** Add an option in the task center to clear all finished tasks from the default list, while retaining their details, logs, documents, and billing records.

**Architecture:** Store the cleared job generation in a nullable schema 13 column. Hide only that unchanged generation while the job is terminal and has no leased work or reserved/unknown requests. A later job update makes it visible again. An explicit list toggle includes cleared records. The clear command uses existing lifecycle locks, Settings generation CAS, maintenance protection, and transactional idempotency.

**Tech stack:** FastAPI, SQLAlchemy/PostgreSQL, React/TypeScript, pytest, Playwright.

## Design choices

- Clear all finished tasks across filters and pages. A confirmation explains that success, partial completion, failure, and cancellation are included; active/waiting/unknown work remains visible.
- Retain task rows rather than delete their execution and billing references. “Show cleared history” restores visibility without rerunning anything.
- Use per-job generation markers rather than a time cutoff, so excluded work does not disappear later merely because its outstanding request settles.
- Preserve the configured branch and all unrelated working changes. Commit verified backend and frontend checkpoints separately.

## 1. Backend checkpoint

1. Add PostgreSQL regressions in `tests/integration/test_clear_task_history.py` for terminal/active states, unsettled requests, pagination, retained records, replay/CAS/maintenance, changed generations, and schema 12 upgrade.
2. Run the tests against a dedicated Compose PostgreSQL test database and observe the missing endpoint failures.
3. Add `jobs.history_cleared_generation` through immutable migration `013.json`; update ORM, schema version, and migration index.
4. Add `GET /jobs/history`, `POST /jobs/history/clear`, and `include_cleared` on `GET /jobs`. Share eligibility between preview, clear, and default list filtering.
5. Run focused history, queue, job presentation, and migration regressions. Commit and push the verified API checkpoint.

## 2. Frontend checkpoint

1. Add Playwright scenarios covering confirmation/cancel, success count, empty history, errors, filters/pagination reset, refresh persistence, and the include-cleared toggle.
2. Add the clear control and confirmation to `apps/web/src/features/job-list.tsx`, using existing Modal, API, error feedback, and request deduplication patterns.
3. Run frontend unit tests, TypeScript/build, and desktop/mobile browser checks. Inspect screenshots and check console errors.
4. Review the final diff, record current verification evidence under `.agent/tmp/clear-task-history-20260915/`, and commit/push only this feature.

## Validation boundary

Use synthetic local jobs and an isolated database; no real model calls or production history clearing. Preserve published artifacts and provider configuration. A build/test result does not claim a production rollout.

## Verified outcome

- Backend checkpoint `16c8331`: 44 focused PostgreSQL tests passed, including schema upgrades, retained evidence, lifecycle/queue and billing regressions. Restored the registered CRLF bytes of migration 12 and protected them with its own Git attribute; all 13 staged migration checksums match.
- Frontend: 18 unit tests, TypeScript/Vite build, and 33 Playwright checks passed. Desktop and mobile confirmation, cancellation, empty/error states, filters, pagination, and retained-history viewing were exercised. Browser plugin was absent; the repository Playwright runner was used.
- Independent review identified and verified the pending-dismiss fix: cancel, close, and Escape cannot dismiss a submitted clear operation. Other dialogs retain their default behavior.
- Built UI at isolated `127.0.0.1:18194` used the real HTTP API and Compose PostgreSQL: three finished jobs cleared, running and unknown jobs remained, refresh preserved visibility, and logs/original PDF remained readable. No external provider calls or production data clearing occurred.
- Evidence: `.agent/tmp/clear-task-history-20260915/backend-2.xml`, `browser-final/browser-results.json`, `frontend-unit.log`, `frontend-build.log`, and `live-1789479100295/live-result.json`. Initial failing tests and intermediate harness failures are retained separately.
- Production rollout was not performed. The running 8080 instance still returned 404 for the new history endpoint at verification time; upgrade app/worker and apply schema 13 to expose the feature there.
