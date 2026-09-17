# Recovery and Translation Repair Implementation Plan

**Goal:** Preserve parsed paragraphs, expose recovery before/after evidence, and make actual translation available from saved parse results with reliable startup.

**Architecture:** Retain parser paragraphs whenever their native text evidence is equivalent; repair only affected regions and group new native lines geometrically. Read recovery comparisons through the existing source-draft evidence reference, keeping logs content-free and deletion rules intact. Reuse the current translation confirmation and continuation APIs from the parse result screen; preserve immutable sources, explicit destination confirmation, CAS/fencing, and unknown-request protection.

**Tech Stack:** Python/FastAPI/SQLAlchemy/PostgreSQL, React/TypeScript, pytest, Playwright, Docker Compose.

## Checkpoint 1: Recovery and evidence

1. Add failing cases to tests/unit/test_native_page_recovery.py for small omissions, split/hyphenated native regions, missing multiline paragraphs, columns, and retained complex content.
2. Fix src/packages/parsers/recovery.py without losing source evidence or duplicating prose. Replay the saved Paddle output from job_9968a100a2e54ce188169136099b1a06 offline; do not invoke the model.
3. Add API integration tests for recovery comparisons, missing historical evidence, document ownership and deletion. Expose paginated before/after blocks through an endpoint in src/apps/api/workflow.py backed by SourceDraft evidence.
4. Add a recovery comparison component in src/apps/web/src/features/ and embed it in task details. Verify desktop/mobile interaction and content escaping.
5. Commit and push only verified recovery/evidence changes.

## Checkpoint 2: Parse result translation action

1. Add browser and API tests for translating both unsealed and automatically sealed parse results.
2. Reuse the existing confirmation dialog/continuation routes with current source/profile/generation; show explicit waiting/active/finished state and safe stale-source behavior.
3. Verify the actual button creates a translation job with the selected configuration, respects external-processing confirmation and prevents accidental repeated jobs.
4. Commit and push this verified checkpoint.

## Checkpoint 3: Translation startup and configuration

1. Trace the observed CONTROL_CHANGED and PROVIDER_CONFIG paths against current configuration and frozen job state.
2. Reproduce with focused PostgreSQL tests before fixing. Cover initial start and continuation under current local provider settings, preserve real control-change rejection and stale-configuration handling.
3. Run targeted backend/browser suites and build. Deploy the verified changes through the configured Compose stack when idle; confirm current UI and existing recovery-task details against live data.
4. Validate current-source recovery with persisted input evidence and record whether historical source needs a fresh revision. No paid external provider call without the required explicit budget/authorization.
5. Commit/push final verified checkpoint and record test/runtime boundaries.

## Workspace handling

Use configured main/origin as requested. Existing unrelated unstaged extraction/deployment/UI changes are preserved; snapshot pre-existing changes before editing shared files and stage only this task's deltas. Temporary scripts/logs/screenshots go in an isolated .agent/tmp directory.
