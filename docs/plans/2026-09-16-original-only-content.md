# Original-only academic content implementation plan

> **For Claude:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Detect author lists, affiliations, contact/identifier lines and bibliography sections, skip their translation, and show their original content once in generated static pages and exports.

**Architecture:** A deterministic, read-only policy over the existing source IR is shared by planning, editorial operations, QA and validation. It applies to new translations of already parsed PDFs without rewriting source snapshots. Sealed results record explicit retention reasons; published artifacts and previously sealed translations remain unchanged. Rendering uses the recorded result and keeps retained content visible in every reading mode.

**Tech stack:** Python, existing IR/SQLAlchemy/PostgreSQL pipeline, static HTML reader, pytest and Playwright. No model or new runtime dependency.

**Status:** Implementation and targeted verification complete in `27d6848`, pushed to the configured `main` branch. 188 Python tests and three offline desktop/mobile/browser checks passed. An independent code review identified and verified fixes for long-text matching, ambiguous name lists and paragraph section boundaries. Production deployment and live model calls were not part of this run. See [behavior contract](../../shared/original-only-content.md).

## Boundaries and alternatives

Use heading/reading-order evidence for reference sections and tightly bounded front matter patterns for author/affiliation lists. Recognize pure email/ORCID/DOI lines, retaining inline links. Exact numbered and multilingual reference headings are supported; a subsequent section ends the range. Titles, abstracts, acknowledgments, body prose, normal lists, captions and substantive footnotes still translate. Ambiguous text defaults to translation.

A model classifier would add cost and nondeterminism. A broad keyword filter would wrongly skip prose discussing authors, organisations or references. The shared local policy avoids both and preserves source text, hashes, structure and provenance. Existing code/math/image retention continues.

The current configured branch is `main`; preserve all unrelated dirty files and commit only this feature's verified checkpoints, per the repository user instruction.

## Task 1: Detection and translation policy

Files: create `packages/ir/retention.py`, `tests/unit/test_original_only.py`; modify `packages/translation/planner.py`, `packages/editorial/drafts.py`, `packages/ir/validator.py`.

1. Add failing cases for bylines/affiliations, contact lines, bibliography headings and entries, reference-section boundaries, and false-positive prose. Assert planning does not mutate the input.
2. Run focused pytest and record the expected missing-policy failures in the run directory.
3. Implement `original_only_blocks(source) -> dict[block_id, reason]`; use it to omit units and produce `retained` results with empty targets. QA must not report deliberate skips as missing translations. Validator permits only matching detected reasons for otherwise required prose.
4. Run detection, planner and IR regressions. Commit and push the verified checkpoint.

## Task 2: Reader and editing consistency

Files: modify `packages/publisher/renderer.py`, `apps/api/editorial.py`, `apps/api/candidates.py`, `apps/api/workflow.py`, `apps/api/knowledge.py`; add reader assertions and `tests/browser/original-only.spec.ts`.

1. Add failing assertions that retained content occurs once, has no target/fallback placeholder, and remains visible in source/target/bilingual views.
2. Render retained text/headings without language-toggle hiding and with full available width. Keep the frozen reader-v1 CSS untouched; do not edit existing artifacts.
3. Align editable flags, selection validation, glossary impact and preflight counts with actual translation planning.
4. Verify desktop/mobile, offline single HTML and bundle output, links, no-JavaScript readability and unchanged existing translated content.

## Task 3: Durable workflow and final checkpoint

Files: create `tests/integration/test_original_only_execution.py`, add contract documentation in `shared/original-only-content.md`.

1. Use a dedicated Compose PostgreSQL test service and synthetic source fixture with the production queue/planner/QA/seal/publisher. Inspect FakeProvider calls to prove excluded blocks are never translation units. FakeProvider does not certify real translation quality.
2. Check empty targets, retention reasons, no false missing warnings, source snapshot immutability, candidate rejection and retained old review handling.
3. Run related unit/integration/browser regressions; record commands, output and source commit under `.agent/tmp/original-only-20260916-a6610dd9/`.
4. Inspect the final diff, verify only feature files are staged, then commit and push to the configured remote. Report deployment and live-provider scope honestly; no production restart or paid model call is needed for this implementation request.
