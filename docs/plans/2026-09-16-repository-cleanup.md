# Repository cleanup implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Commit the existing workspace, then remove the retired prototype without breaking the actual application or its controlled reference inputs.

**Architecture:** Keep the production application, immutable reader templates, and the two allowlisted seed documents. Move the seed files into `reference/legacy/`, remove the separate demo UI/server and redundant exports, and use the production Compose definition from the root entry point. Markdown remains the documentation source; remove the stale generated design portal and its generators.

**Tech Stack:** Python, React/TypeScript, PostgreSQL, Docker Compose, pytest, Playwright.

## 1. Preserve the existing work

- Inspect all tracked and untracked changes and retain the configured `main` branch and `origin` remote.
- Run Python units, affected PostgreSQL integration tests, frontend tests, and the frontend build.
- Commit and push all non-ignored changes before cleanup. Completed as `0d1599a`: 596 units, 43 integrations, 18 frontend tests, and build passed.

## 2. Retire the demo and relocate runtime references

- Move `prototype/reader/` to `reference/legacy/` without changing document, PDF, image, or CSS bytes.
- Update both reference manifests, the seed manifest digest, parser tests, and the parser concurrency harness.
- Remove `prototype/`, root `Dockerfile`, `tools/build_prototype.py`, and `tools/serve_prototype.py`.
- Remove prototype-only image COPY instructions and the obsolete browser visual-reference test. Keep production UI tests and seed/export tests.
- Run the frozen-reference, seed boundary, parser fidelity, and seed integration suites.

## 3. Make maintained entry points consistent

- Replace root `compose.yaml` with an include of `deployment/compose.production.yaml` and the optional isolated package verifier.
- Preserve the separate single-file CPU/CUDA/MLX example and its documented customization path.
- Remove generated `index.html`, `html/`, `tools/build_docs.py`, and `tools/generate_specs.py`; retain Markdown specifications and machine-readable contracts.
- Update README, deployment guidance, fixtures/reference guidance, and package validation for the maintained layout. Drop the now-unused Markdown rendering dependency.
- Keep historical agent notes/evidence and persistent local data intact.

## 4. Verify and checkpoint

- Validate root, explicit production, and example configurations with `docker compose config`; compare the resolved production service graph and volume paths.
- Run package/link/reference checks, Python regression tests with the isolated test PostgreSQL, frontend tests/build, and affected Chromium browser tests.
- Build the application image and check seed resources in the image without deploying it to the user's running instance.
- Obtain an independent code review, address defects, and commit/push the verified cleanup.
- Stop only the test services created for this run. Record results under `.agent/tmp/repo-cleanup-20260916-01/` and confirm a clean Git worktree.

## Verification results

- All 28 relocated paper resources and the existing `reader-v1.css` retain their original SHA-256 values. The seed manifest changes only repository paths; its pinned digest was updated accordingly.
- Root and explicit production Compose resolve to identical production services, volumes, networks, secrets and host paths. The root adds only the optional isolated verifier. The standalone example also passes `docker compose config`.
- Docker package verification: 50 passed, including Markdown links, seed assets/anchors, frozen reference hashes and Compose boundaries.
- Focused reference/seed/fidelity regression: 27 passed. Frontend: 18 unit tests and production build passed. Chromium: 33 product UI/parser tests passed.
- Full Python run on macOS: 1,160 passed, 18 conditional skips, 2 environment-dependent failures. The unchanged native-inspector test requires a finite Linux cgroup memory limit and passed separately in a 4 GiB Linux test container. The other unchanged test requires the absent `.agent/tmp/evidence/live-provider-final-en/independent-manual-target-review.json`; no historical review evidence was synthesized or test assertion relaxed. Thus 1,161 unique Python cases passed, with one historical-fixture case unavailable.
- Application image `bilingual-personal-pdf-app:cleanup-20260916-01` built successfully. Its isolated audit checked two intact seeds, three frozen templates, the built frontend, and absence of demo/agent files.
- An isolated root-Compose stack reached healthy schema 13 on port 18097. Both seeds imported, and actual HTTP reads matched their original PDFs and the permitted reader navigation patch. No model inference was requested. The initial app-only readiness probe correctly failed until worker/parser heartbeats were present; the full stack subsequently became healthy.
- Independent review found one stale restore-guide statement, corrected before completion, and no remaining actionable findings. The user's existing production stack and persistent local environments were not redeployed or removed.
